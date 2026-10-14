"""
HH.ru apply functions: send response, fill questionnaire, check vacancy, check limit, touch resume.
"""

import re
import json
import time
import requests
import aiohttp
import asyncio

from glom import glom

from app.logging_utils import log_debug, _is_login_page
from app.config import CONFIG, hh_base
from app.human_pace import respect_retry_after
from app.hh_http import HH
from app.mutation_safety import ensure_mutation_allowed, MutationBlocked, OutcomeUnknown
# Egress-helpers aiohttp переехали в app/hh_http.py (единая точка egress);
# реэкспорт для совместимости — routes/apply.py и тесты импортируют отсюда.
from app.hh_http import _aio_proxy, _aio_session_connector, _aio_egress_kwargs  # noqa: F401
from app.user_agent import webview_user_agent
from app.hh_api import get_headers
from app.oauth import _oauth_touch_resume, _token_key
from app.questionnaire import (_parse_questionnaire_fields, _parse_questionnaire_rich,
                               resolve_questionnaire_option)
from app.questionnaire_claims import unsupported_questionnaire_claims
from app.gender_guard import conflicting_gender_words
from app.llm import _randomize_text, generate_llm_questionnaire_answers, get_llm_last_status
from app.hh_resume import fetch_resume_text

_HH_DEFAULT_TIMEOUT = 15


def _parse_retry_after(value: str) -> int | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        return max(0, int(dt.timestamp() - time.time()))
    except Exception:
        return None


def _with_retry(func, retries=3, backoff_base=2.0):
    def wrapper(*args, **kwargs):
        for attempt in range(retries + 1):
            try:
                resp = func(*args, **kwargs)
                if hasattr(resp, "status_code") and resp.status_code in (502, 503, 504):
                    if attempt == retries:
                        return resp
                    sleep = backoff_base * (2 ** attempt)
                    log_debug(f"_with_retry {getattr(func, '__name__', 'unknown')}: HTTP {resp.status_code}, sleep {sleep}s ({attempt+1}/{retries+1})")
                    time.sleep(sleep)
                    continue
                return resp
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt == retries:
                    raise
                sleep = backoff_base * (2 ** attempt)
                log_debug(f"_with_retry {getattr(func, '__name__', 'unknown')}: {type(e).__name__}, sleep {sleep}s ({attempt+1}/{retries+1})")
                time.sleep(sleep)
        return func(*args, **kwargs)
    wrapper.__name__ = getattr(func, "__name__", "unknown")
    return wrapper


def classify_apply_response(status_code: int, txt: str) -> tuple:
    """Pure: классифицирует ответ HH popup на отклик в (result, info).
    Вынесено из send_response_async чтобы было тестируемо без mock'ов HTTP.

    Порядок проверок важен:
    1. 401/403 → auth_error
    2. 200 + login-page HTML → auth_error
    3. известные error-маркеры в теле (limit/test/already) — даже на 200, т.к. HH
       отдаёт их с status=200 (см. audit C5)
    4. 200 + success-маркер → sent
    5. всё остальное → error
    """
    if status_code >= 500:
        return "unknown", {"http_status": status_code}
    from app.captcha import parse
    try:
        challenge = parse(status_code, json.loads(txt))
    except (ValueError, TypeError):
        challenge = None
    if challenge is not None:
        return 'challenge', challenge
    if status_code in (401, 403):
        return "auth_error", {}

    if status_code == 200 and _is_login_page(txt):
        return "auth_error", {}

    info = {}
    parsed = None
    txt = txt.lstrip()
    if txt.startswith("{"):
        try:
            parsed = json.loads(txt)
        except Exception:
            parsed = None

    if parsed is not None:
        # info из responseStatus.shortVacancy (старый формат popup)
        info = {
            "title": glom(parsed, "responseStatus.shortVacancy.name", default="") or "",
            "company": glom(parsed, "responseStatus.shortVacancy.company.name", default="") or "",
            "salary_from": glom(parsed, "responseStatus.shortVacancy.compensation.from", default=None),
            "salary_to": glom(parsed, "responseStatus.shortVacancy.compensation.to", default=None),
        }
        ci = glom(parsed, "responseStatus.shortVacancy.contactInfo", default={}) or {}
        if ci and (ci.get("email") or ci.get("fio")):
            contact = {"fio": ci.get("fio", ""), "email": ci.get("email", ""), "phone": ""}
            phones = (ci.get("phones") or {}).get("phones", [])
            if phones:
                ph = phones[0]
                contact["phone"] = f"+{ph.get('country','')}{ph.get('city','')}{ph.get('number','')}"
            info["contact"] = contact

        # Сначала отказы (test/limit/already) — они могут сосуществовать с
        # success-маркером в нестандартных ответах, и приоритет должен быть у отказа.

        # top-level "error":"..." (HTTP 400 формат)
        top_error = parsed.get("error")
        if top_error:
            ts = str(top_error).lower()
            if "test-required" in ts or "test_required" in ts:
                return "test", info
            if "limit" in ts or "negotiations-limit" in ts:
                return "limit", info
            if "already" in ts:
                return "already", info
            return "error", {"raw": txt[:300], **info, "error_code": str(top_error)}

        # Старый формат: responseStatus.*
        rs = parsed.get("responseStatus") or {}
        if rs.get("alreadyApplied") is True:
            return "already", info
        if rs.get("test-required") is True or rs.get("testRequired") is True:
            return "test", info
        if (rs.get("negotiationsLimitExceeded") is True
                or rs.get("negotiations-limit-exceeded") is True):
            return "limit", info

        # top-level отказы как поля рядом с success (защита от неоднозначных ответов)
        if parsed.get("test-required") is True or parsed.get("testRequired") is True:
            return "test", info
        if parsed.get("alreadyApplied") is True:
            return "already", info
        if (parsed.get("negotiationsLimitExceeded") is True
                or parsed.get("negotiations-limit-exceeded") is True):
            return "limit", info

        # Теперь успех: новый формат top-level success/topic_id
        if not 200 <= status_code < 300:
            return "error", {"http_status": status_code, **info}
        top_success = parsed.get("success")
        if top_success in (True, "true", "True") or parsed.get("topic_id") or parsed.get("status") == "ok":
            info["topic_id"] = parsed.get("topic_id", "")
            info["chat_id"] = parsed.get("chat_id", "")
            return "sent", info
        if rs.get("responded") is True or rs.get("success") is True:
            return "sent", info
        # A parsed false flag (or a marker inside descriptive text) is not a
        # refusal. Substring matching is only for genuinely non-JSON bodies.
        return "unknown", {"reason": "unconfirmed_response", **info}

    # ── 3. Substring fallback для не-JSON ответов (HTML страница и т.п.) ──
    if "negotiations-limit-exceeded" in txt:
        return "limit", info
    if "test-required" in txt:
        return "test", info
    if "alreadyApplied" in txt:
        return "already", info

    if 200 <= status_code < 300:
        return "unknown", {"reason": "unconfirmed_response", **info}

    if status_code in (502, 503, 504):
        return "error", {"raw": txt[:200], "transient": True, **info}

    return "error", {"raw": txt[:200], **info}


async def generate_hh_ai_letter(acc: dict, resume_hash: str, vid: str, timeout_s: int = 6) -> str:
    """`POST /shards/hhpro_ai_letter {resumeHash, vacancyId}` — HH-Pro фича,
    но сервер даёт по одной бесплатной попытке на пару (resumeHash, vacancyId)
    независимо от подписки. Async: poll `/shards/hhpro_ai_check_status`.
    Возвращает текст письма или "" если не сгенерилось / уже использовали.

    Асинхронная целиком: `HH` — sync wrapper, гоним в thread-pool через
    `asyncio.to_thread`; sleep — `asyncio.sleep`. Иначе последовательный
    poll блокирует event loop и рушит `asyncio.gather` из send_response_async
    (10 вакансий × 6с = 60с фризу цикла).
    """
    import asyncio as _asyncio
    xsrf = (acc.get("cookies") or {}).get("_xsrf", "")
    if not xsrf or not resume_hash or not vid:
        return ""
    headers = get_headers(xsrf)
    try:
        ensure_mutation_allowed(acc)
        r = await _asyncio.to_thread(
            HH.post,
            f"{hh_base()}/shards/hhpro_ai_letter",
            headers={**headers, "Content-Type": "application/json"},
            cookies=acc.get("cookies", {}),
            json={"resumeHash": resume_hash, "vacancyId": str(vid)},
            timeout=8,
        )
        if r.status_code == 400 and "service_already_used" in r.text.lower():
            log_debug(f"hhpro_ai_letter {vid}: service_already_used — эту пару уже использовали, юзаем шаблон")
            return ""
        if r.status_code not in (200, 202):
            log_debug(f"hhpro_ai_letter {vid}: HTTP {r.status_code}, body={r.text[:150]}")
            return ""
    except Exception as e:
        log_debug(f"hhpro_ai_letter start {vid}: {e}")
        return ""

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        await _asyncio.sleep(1)
        try:
            r = await _asyncio.to_thread(
                HH.get,
                f"{hh_base()}/shards/hhpro_ai_check_status",
                params={"resumeHash": resume_hash, "vacancyId": str(vid)},
                cookies=acc.get("cookies", {}),
                headers=headers,
                timeout=6,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            text = (data.get("generatedLetter") or data.get("letter")
                    or data.get("text") or (data.get("result") or {}).get("text")
                    or data.get("content") or "").strip()
            status = (data.get("status") or "").lower()
            if text:
                return text
            if status in ("ready", "done", "success") and not text:
                log_debug(f"hhpro_ai_check_status {vid}: ready но текст пуст, ключи={list(data.keys())}")
                return ""
        except Exception:
            continue
    return ""


async def send_response_async(acc: dict, vid: str, letter_max_length: int | None = None) -> tuple:
    """Асинхронная отправка отклика. Возвращает (результат, инфо).
    `letter_max_length` — hard-cap длины письма из vacancyView.applicantVacancyResponseStatuses;
    если задан и превышает — режем чтобы HH не отказал 400.
    Если `CONFIG.hh_ai_letter_first_try` включен и у нас ещё есть бесплатная попытка
    (сервер даст 1 раз на пару resumeHash×vacancyId) — берём письмо от HH-AI.
    """
    from app.apply_quarantine import blocked
    if blocked(acc, vid):
        raise MutationBlocked('Повтор неподтверждённого отклика заблокирован')
    log_debug(f"📤 ОТПРАВКА ОТКЛИКА на вакансию {vid} | Аккаунт: {acc['name']}")

    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    if not xsrf:
        return "error", {"exception": "Missing _xsrf token"}
    headers = get_headers(xsrf)

    letter = _randomize_text(acc.get("letter", ""))
    try:
        if getattr(CONFIG, "hh_ai_letter_first_try", True):
            ai_letter = await generate_hh_ai_letter(acc, acc.get("resume_hash", ""), vid)
            if ai_letter:
                letter = ai_letter
                log_debug(f"   AI-letter от HH: {len(letter)} симв, юзаю его вместо шаблона")
    except Exception as e:
        log_debug(f"   hhpro_ai_letter fail {vid}: {e}")
    if letter_max_length and len(letter) > letter_max_length:
        letter = letter[:letter_max_length].rstrip()
    gender_words = conflicting_gender_words(letter)
    if gender_words:
        log_debug(f"Apply {vid}: cover letter gender conflicts blocked: {gender_words}")
        return "error", {"error_code": "gender_mismatch", "words": gender_words}

    data = aiohttp.FormData()
    data.add_field("resume_hash", acc["resume_hash"])
    data.add_field("vacancy_id", vid)
    data.add_field("letterRequired", "true")
    data.add_field("letter", letter)
    data.add_field("lux", "true")
    data.add_field("ignore_postponed", "true")

    try:
        # Egress через HH_PROXY: socks → ProxyConnector на сессию,
        # http(s) → proxy= на запрос (см. _aio_egress_kwargs).
        sess_kw, req_kw = _aio_egress_kwargs()
        async with aiohttp.ClientSession(headers=headers, cookies=acc["cookies"], **sess_kw) as session:
            ensure_mutation_allowed(acc)
            async with session.post(
                hh_base() + "/applicant/vacancy_response/popup",
                data=data,
                timeout=aiohttp.ClientTimeout(total=_HH_DEFAULT_TIMEOUT),
                **req_kw,
            ) as r:
                txt = await r.text()
                status_code = r.status
                if status_code == 429:
                    delay = respect_retry_after(r.headers, default_sec=60)
                    log_debug(f'HH rate-limit, ждём {delay}с')
                    await asyncio.sleep(delay)

        from app.captcha import capture
        try:
            challenge_payload = json.loads(txt)
        except ValueError:
            challenge_payload = None
        if capture(acc, status_code, challenge_payload) is not None:
            return 'challenge', {'error_type': 'captcha_required'}
        log_debug(f"   Ответ HTTP: {status_code} | Размер: {len(txt)}")
        if status_code >= 400:
            log_debug(f"   Тело ответа: {txt[:300]}")
        elif status_code == 200 and 500 < len(txt) < 30000 and '"topic_id"' not in txt and '"success"' not in txt:
            # Диагностика: HTML-редирект после отклика — что там?
            log_debug(f"   200 (не-JSON, {len(txt)}b): {txt[:200]}")
        return classify_apply_response(status_code, txt)
    except MutationBlocked:
        return "cancelled", {}
    except Exception as e:
        return "unknown", {"exception": str(e)}


async def _fill_and_submit_questionnaire_impl(acc: dict, vid: str,
                                        vacancy_title: str = "", company: str = "", *,
                                        receipt_account: dict | None = None,
                                        trace=None, require_llm: bool = False,
                                        preview_only: bool = False,
                                        approved_answers: dict | None = None,
                                        expected_questions: list | None = None) -> tuple:
    """
    Получает страницу опроса, заполняет шаблонными ответами и отправляет.
    Поддерживает textarea, radio, checkbox.
    Возвращает (result, info): result = sent | limit | test | error
    """
    from app.apply_quarantine import blocked
    if blocked(receipt_account or acc, vid):
        raise MutationBlocked('Повтор неподтверждённого отклика заблокирован')
    resume_id = str(acc.get("_pinned_resume_id") or acc.get("resume_hash") or "")
    source_account = acc if receipt_account is None else receipt_account
    dispatched = False
    dispatched_at = None
    confirmation_attempted = False
    confirmation_result = ("unknown", {"error_code": "submission_unconfirmed"})

    def emit(stage: str, **details):
        if trace is not None:
            trace(stage, details)

    async def unconfirmed():
        # A redirect/timeout is not an ACK. Reconcile once with a fresh read;
        # never repeat the questionnaire POST, even if this read also fails.
        from app.apply_confirmation import confirm_application_receipt
        import asyncio
        from datetime import datetime
        nonlocal confirmation_attempted, confirmation_result
        if confirmation_attempted:
            return confirmation_result
        confirmation_attempted = True
        try:
            receipt = await asyncio.to_thread(
                confirm_application_receipt, source_account, str(vid), resume_id)
        except Exception:
            receipt = None
        if receipt is not None:
            # Existence is enough to prevent a duplicate POST, but only a new
            # receipt may increment today's applications. Missing/old dates
            # mean already applied, never a newly confirmed send.
            fresh = False
            try:
                created = datetime.fromisoformat(receipt["receipt_created_at"])
                fresh = (created.tzinfo is not None and dispatched_at is not None and
                         dispatched_at - 5 <= created.timestamp() <= time.time() + 5)
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
            confirmation_result = ("sent" if fresh else "already", receipt)
        return confirmation_result

    if not resume_id:
        return "error", {"error_code": "resume_required"}
    headers_get = {
        "User-Agent": webview_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{hh_base()}/vacancy/{vid}",
    }

    try:
        # Egress через HH_PROXY: socks → ProxyConnector на сессию,
        # http(s) → proxy= на каждый запрос (и GET формы, и POST ниже).
        sess_kw, req_kw = _aio_egress_kwargs()
        async with aiohttp.ClientSession(
            cookies=acc["cookies"],
            headers=headers_get,
            **sess_kw,
        ) as session:
            url_form = f"{hh_base()}/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"

            # Шаг 1: GET форма опроса
            async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=_HH_DEFAULT_TIMEOUT), **req_kw) as r:
                html = await r.text()
                status_code = r.status

            from app.captcha import capture
            try:
                form_payload = json.loads(html)
            except ValueError:
                form_payload = None
            if capture(acc, status_code, form_payload) is not None:
                return "challenge", {"error_type": "captcha_required"}
            # Auth check: 401/403/login-page → не считать "test" (валидный отклик),
            # а отдать auth_error чтобы воркер обновил куки/спаузил аккаунт.
            if status_code in (401, 403) or _is_login_page(html):
                return "auth_error", {}
            if status_code != 200:
                emit("form_fetch_failed", http_status=status_code)
                return "error", {"http_status": status_code}

            # HH keeps the same vacancy_response URL for a vacancy that was
            # already answered, but replaces the questions with this marker.
            # Do not report it as an unrecognized test and retry indefinitely.
            if re.search(r'data-qa\s*=\s*["\']already-responded-text["\']', html):
                emit("already_responded")
                return "already", {"reason": "hh_already_responded"}
            if re.search(r'data-qa\s*=\s*["\']hidden-resume-warning["\']', html):
                emit("resume_visibility_blocked")
                return "error", {"error_code": "resume_visibility_restricted"}

            # Hidden поля
            hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
            hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))

            # Парсим все поля опроса
            questions, field_answers = _parse_questionnaire_fields(html)
            answer_sources = {field: "template" for field in field_answers}
            rich_qs = _parse_questionnaire_rich(html)
            if expected_questions is not None and rich_qs != expected_questions:
                emit("reviewed_form_changed")
                return "error", {"error_code": "reviewed_form_changed"}
            resume_text = ""
            emit("form_parsed", http_status=status_code, questions=rich_qs,
                 fields_found=list(field_answers))

            if not field_answers:
                log_debug(f"Questionnaire: no task fields found for {vid}")
                emit("form_unrecognized")
                return "test", {}

            # LLM-заполнение опросника (если включено)
            if CONFIG.llm_fill_questionnaire and CONFIG.llm_enabled and questions:
                if CONFIG.llm_use_resume:
                    import asyncio as _aio
                    resume_source = "none"
                    if str(acc.get("mode") or "").lower() == "oauth":
                        def fetch_oauth_resume():
                            from app.hh_client_factory import get_client
                            from app.manager import _resume_plain_text
                            try:
                                return _resume_plain_text(get_client(acc).fetch_resume())
                            except Exception as exc:
                                log_debug(f"Questionnaire resume OAuth fetch: {type(exc).__name__}")
                                return ""
                        resume_text = await _aio.get_event_loop().run_in_executor(None, fetch_oauth_resume)
                        if resume_text:
                            resume_source = "oauth"
                    if not resume_text:
                        # Web fallback; both sync transports run outside the event loop.
                        resume_text = await _aio.get_event_loop().run_in_executor(None, fetch_resume_text, acc)
                        if resume_text:
                            resume_source = "web"
                    emit("resume_context", available=bool(resume_text), characters=len(resume_text),
                         source=resume_source)
                    if require_llm and not resume_text:
                        return "error", {"error_code": "resume_unavailable"}
                # generate_llm_questionnaire_answers тоже sync (OpenAI client).
                import asyncio as _aio2
                if approved_answers is not None:
                    if not isinstance(approved_answers, dict) or not set(approved_answers) <= set(field_answers):
                        return "error", {"error_code": "reviewed_fields_changed"}
                    optional_custom = set()
                    by_field = {q["field"]: q for q in rich_qs}
                    for q in rich_qs:
                        field = q["field"]
                        if q["type"] != "textarea" or not field.endswith("_text"):
                            continue
                        choice = by_field.get(field[:-5])
                        if not choice or not any(o["value"] == "open" for o in choice["options"]):
                            continue
                        selected = approved_answers.get(field[:-5])
                        if selected != "open" and not (isinstance(selected, list) and "open" in selected):
                            optional_custom.add(field)
                    if set(field_answers) - set(approved_answers) - optional_custom:
                        return "error", {"error_code": "reviewed_fields_changed"}
                    llm_ans = approved_answers
                    emit("reviewed_answers_reused", fields=list(approved_answers))
                else:
                    llm_ans = await _aio2.get_event_loop().run_in_executor(
                        None,
                        lambda: generate_llm_questionnaire_answers(
                            rich_qs, vacancy_title, company, resume_text=resume_text,
                            account_key=f"questionnaire:{acc.get('resume_hash') or acc.get('short') or vid}",
                            **({"trace": trace} if trace is not None else {}),
                        ),
                    )
                if llm_ans:
                    # Validate LLM answers against actual options
                    rich_fields = {q["field"]: q for q in rich_qs}
                    validated_ans = {}
                    for field, llm_val in llm_ans.items():
                        if field not in rich_fields:
                            # Free-text or unknown field — only accept scalars
                            if isinstance(llm_val, (str, int, float, bool)):
                                validated_ans[field] = str(llm_val)
                            continue
                        q = rich_fields[field]
                        if not (q["type"] in ("radio", "checkbox", "select") and q["options"]):
                            if isinstance(llm_val, (str, int, float, bool)):
                                validated_ans[field] = str(llm_val)
                            continue
                        selected = resolve_questionnaire_option(
                            llm_val, q["options"], multiple=q["type"] == "checkbox")
                        if selected is None and q["type"] == "checkbox":
                            # HH's "Свой вариант" uses task_N=open plus task_N_text.
                            custom_text = llm_ans.get(field + "_text")
                            if custom_text and any(o["value"] == "open" for o in q["options"]):
                                selected = "open"
                        if selected is not None:
                            validated_ans[field] = selected
                        else:
                            log_debug(f"LLM choice for {field}: no unique matching option")
                    missing_choices = [q["field"] for q in rich_qs
                                       if q["type"] in ("radio", "checkbox", "select")
                                       and q["options"] and q["field"] not in validated_ans]
                    if missing_choices:
                        emit("llm_answers_rejected", fields=missing_choices, reason="choice_unresolved")
                        return "error", {"error_code": "llm_answers_rejected"}
                    def custom_option_selected(field):
                        selected = validated_ans.get(field)
                        return selected == "open" or (isinstance(selected, list) and "open" in selected)
                    missing_text = [q["field"] for q in rich_qs
                                    if q["type"] == "textarea" and q["field"] not in validated_ans
                                    and not (q["field"].endswith("_text")
                                             and q["field"][:-5] in rich_fields
                                             and not custom_option_selected(q["field"][:-5]))]
                    if missing_text:
                        emit("llm_answers_rejected", fields=missing_text, reason="text_missing")
                        return "error", {"error_code": "llm_answers_rejected"}
                    overridden = [f for f in validated_ans if f in field_answers]
                    for f in overridden:
                        field_answers[f] = validated_ans[f]
                        answer_sources[f] = "llm"
                    for q in rich_qs:
                        field = q["field"]
                        if q["type"] != "textarea" or not field.endswith("_text"):
                            continue
                        choice = rich_fields.get(field[:-5])
                        if not choice or not any(o["value"] == "open" for o in choice["options"]):
                            continue
                        selected = field_answers.get(field[:-5])
                        if selected != "open" and not (isinstance(selected, list) and "open" in selected):
                            field_answers.pop(field, None)
                            answer_sources.pop(field, None)
                    log_debug(f"Questionnaire {vid}: LLM заполнил {len(overridden)}/{len(field_answers)} полей: {overridden}")
                    emit("llm_answers_validated", proposed=llm_ans, accepted=validated_ans,
                         overridden_fields=overridden)
                    if require_llm and not overridden:
                        return "error", {"error_code": "llm_answers_rejected"}
                    if approved_answers is not None and set(overridden) != set(field_answers):
                        return "error", {"error_code": "reviewed_answers_rejected"}
                else:
                    llm_status = get_llm_last_status(f"questionnaire:{acc.get('resume_hash') or acc.get('short') or vid}", "questionnaire")
                    provider = llm_status.get("provider") or "unknown"
                    status = llm_status.get("status") or "empty"
                    log_debug(
                        f"Questionnaire {vid}: LLM не дал валидный ответ "
                        f"(provider={provider}, status={status}); отправка остановлена"
                    )
                    emit("llm_no_answer", provider=provider, status=status)
                    return "error", {"error_code": "llm_no_answer"}
            elif require_llm:
                emit("llm_disabled")
                return "error", {"error_code": "llm_disabled"}

            emit("answers_ready", answers=field_answers, sources=answer_sources)
            if CONFIG.llm_check_questionnaire_claims:
                issues = unsupported_questionnaire_claims(
                    rich_qs, field_answers, answer_sources, resume_text,
                    str(getattr(CONFIG, "llm_system_prompt", "") or "")[:4000])
                if issues:
                    emit("answer_review_blocked", issues=issues)
                    log_debug(f"Questionnaire {vid}: unsupported LLM claims blocked: {issues}")
                    return "error", {"error_code": "unsupported_claims", "issues": issues}
            gender_issues = [{"field": field, "words": words}
                             for field, answer in field_answers.items()
                             if isinstance(answer, str)
                             if (words := conflicting_gender_words(answer))]
            letter = _randomize_text(acc.get("letter", ""))
            letter_words = conflicting_gender_words(letter)
            if letter_words:
                gender_issues.append({"field": "letter", "words": letter_words})
            if gender_issues:
                emit("answer_gender_blocked", issues=gender_issues)
                log_debug(f"Questionnaire {vid}: gender conflicts blocked: {gender_issues}")
                return "error", {"error_code": "gender_mismatch", "issues": gender_issues}
            if preview_only:
                emit("preview_ready", fields=list(field_answers))
                return "preview", {"questions": rich_qs, "answers": field_answers,
                                   "sources": answer_sources}

            log_debug(f"Questionnaire {vid}: {len(field_answers)} fields, {len(questions)} questions")
            for name, val in field_answers.items():
                log_debug(f"  {name} = {str(val)[:80]}")

            # Шаг 2: POST данные
            data = aiohttp.FormData()
            data.add_field("resume_hash", resume_id)
            data.add_field("vacancy_id", vid)
            data.add_field("letter", letter)
            data.add_field("lux", "true")

            for name in ("_xsrf", "uidPk", "guid", "startTime", "testRequired"):
                if name in hidden:
                    data.add_field(name, hidden[name])

            for name, value in field_answers.items():
                # checkbox с несколькими выбранными значениями → несколько полей одного name
                if isinstance(value, list):
                    for v in value:
                        data.add_field(name, str(v))
                else:
                    data.add_field(name, str(value))

            # Шаг 3: POST
            ensure_mutation_allowed(acc)
            emit("submission_started")
            dispatched_at = time.time()
            dispatched = True
            async with session.post(
                url_form,
                headers={"X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""), "Referer": url_form},
                data=data,
                timeout=aiohttp.ClientTimeout(total=_HH_DEFAULT_TIMEOUT),
                allow_redirects=False,
                **req_kw,
            ) as r2:
                status = r2.status
                location = r2.headers.get("location", "")
                txt = await r2.text()

            log_debug(f"Questionnaire submit {vid}: HTTP {status} location={location}")
            emit("submission_response", http_status=status, redirect_to_form=(
                "withoutTest=no" in location or f"vacancyId={vid}" in location))

            from app.captcha import capture
            try:
                challenge_payload = json.loads(txt)
            except ValueError:
                challenge_payload = None
            if capture(acc, status, challenge_payload) is not None:
                return "challenge", {"error_type": "captcha_required"}

            if status in (401, 403) or _is_login_page(txt) or '/account/login' in location:
                return 'auth_error', {}

            if status in (302, 303):
                if "negotiations-limit-exceeded" in location or "negotiations-limit-exceeded" in txt:
                    return "limit", {}
                # Редирект назад на форму — ошибка валидации
                if "withoutTest=no" in location or f"vacancyId={vid}" in location:
                    log_debug(f"Questionnaire {vid}: form rejected, redirect back")
                    return "test", {"error_code": "questionnaire_rejected", "http_status": status}
                return await unconfirmed()

            if status == 200:
                # HTML 200 can be a validation error or captcha. Only explicit
                # structured success is sufficient to update application counts.
                result, info = classify_apply_response(status, txt)
                if result in ('sent', 'limit', 'test', 'already', 'auth_error', 'error'):
                    return result, info
                return await unconfirmed()

            if status >= 500:
                return await unconfirmed()
            return "test", {}

    except MutationBlocked:
        return "cancelled", {}
    except Exception as e:
        log_debug(f"fill_and_submit_questionnaire error: {e}")
        emit("exception", error_type=type(e).__name__, dispatched=dispatched)
        if dispatched:
            return await unconfirmed()
        return "error", {"error_code": "questionnaire_fetch_failed"}


async def fill_and_submit_questionnaire(acc: dict, vid: str,
                                        vacancy_title: str = "", company: str = "", *,
                                        receipt_account: dict | None = None,
                                        trace=None, require_llm: bool = False,
                                        preview_only: bool = False,
                                        approved_answers: dict | None = None,
                                        expected_questions: list | None = None) -> tuple:
    """Record every ordinary questionnaire run; targeted runs bring their own trace."""
    if trace is not None:
        return await _fill_and_submit_questionnaire_impl(
            acc, vid, vacancy_title, company, receipt_account=receipt_account,
            trace=trace, require_llm=require_llm, preview_only=preview_only,
            approved_answers=approved_answers, expected_questions=expected_questions)
    if not re.fullmatch(r"\d{5,20}", str(vid)):
        # Synthetic test IDs must not become entries in the durable UI history.
        return await _fill_and_submit_questionnaire_impl(
            acc, vid, vacancy_title, company, receipt_account=receipt_account,
            require_llm=require_llm, preview_only=preview_only,
            approved_answers=approved_answers, expected_questions=expected_questions)

    from uuid import uuid4
    from app.routes.questionnaire_trace import _record
    source = receipt_account or acc
    run_id = uuid4().hex
    account = str(source.get("name") or source.get("short") or source.get("resume_hash") or "")
    def record(stage, details):
        try:
            _record(run_id, account, str(vid), stage, details)
        except OSError as exc:
            log_debug(f"Questionnaire trace write failed: {type(exc).__name__}")
    record("started", {"mode": source.get("mode", "web"),
                       "title": vacancy_title, "company": company, "origin": "automatic"})
    try:
        result, info = await _fill_and_submit_questionnaire_impl(
            acc, vid, vacancy_title, company, receipt_account=receipt_account,
            trace=record, require_llm=require_llm, preview_only=preview_only,
            approved_answers=approved_answers, expected_questions=expected_questions)
    except Exception as exc:
        record("error", {"error_type": type(exc).__name__})
        raise
    safe_info = {k: v for k, v in (info or {}).items()
                 if k in ("error_code", "error_type", "http_status", "reason", "receipt_confirmed")
                 and isinstance(v, (str, int, bool))}
    record("result", {"status": result, "info": safe_info})
    return result, info


def _check_vacancy_before_apply(acc: dict, vid: str) -> dict:
    """Pre-check vacancy before applying: detect impossible responses and experience mismatches.
    Returns {"ok": bool, "reason": str}
    """
    ua = webview_user_agent()
    try:
        r = _with_retry(
            lambda: HH.get(
                f"{hh_base()}/applicant/vacancy_response/popup?vacancyId={vid}",
                headers={"User-Agent": ua, "Accept": "application/json, */*",
                         "Referer": f"{hh_base()}/vacancy/{vid}"},
                cookies=acc.get("cookies", {}),
                cookie_jar_key=_token_key(acc) or None,
                timeout=_HH_DEFAULT_TIMEOUT,
            ),
            retries=3, backoff_base=2.0,
        )()
        if r.status_code in (401, 403) or _is_login_page(r.text):
            return {"ok": False, "reason": "auth_error", "skip_reason": "auth"}
        if r.status_code == 429:
            retry_after = respect_retry_after(r.headers, default_sec=60)
            log_debug(f'HH rate-limit, ждём {retry_after}с')
            time.sleep(retry_after)
            result = {"ok": False, "reason": "rate_limit", "skip_reason": "retry"}
            if retry_after is not None:
                result["retry_after_seconds"] = retry_after
            return result
        if r.status_code >= 500:
            # HH server issue — попробовать позже.
            return {"ok": False, "reason": f"http_{r.status_code}", "skip_reason": "retry"}
        if r.status_code != 200:
            # 4xx (другие, кроме 401/403/429) — permanent skip.
            return {"ok": False, "reason": f"http_{r.status_code}", "skip_reason": "skip"}
        try:
            data = r.json()
        except (json.JSONDecodeError, ValueError):
            return {"ok": False, "reason": "bad_json", "skip_reason": "parse_error"}
        # Check responseImpossible
        resp_status = data.get("responseStatus") or {}
        if resp_status.get("responseImpossible"):
            reason = resp_status.get("responseImpossibleReason", "responseImpossible")
            return {"ok": False, "reason": str(reason)}
        # Check resume inconsistencies (experience type mismatch)
        body = data.get("body", {})
        inner_rs = body.get("responseStatus", resp_status)
        incon_data = inner_rs.get("resumeInconsistencies", resp_status.get("resumeInconsistencies", {}))
        if isinstance(incon_data, dict):
            for resume_entry in incon_data.get("resume", []):
                for inc in (resume_entry.get("inconsistencies", {}).get("inconsistency", [])):
                    if inc.get("type") == "EXPERIENCE":
                        return {"ok": False, "reason": f"опыт: нужен {inc.get('required','?')}, есть {inc.get('actual','?')}"}
        elif isinstance(incon_data, list):
            for inc in incon_data:
                if isinstance(inc, dict) and inc.get("type") == "EXPERIENCE":
                    return {"ok": False, "reason": f"несовпадение опыта"}

        # Extract contactInfo if available
        contact = {}
        sv = inner_rs.get("shortVacancy", {})
        ci = sv.get("contactInfo", {})
        if ci and (ci.get("email") or ci.get("fio")):
            contact = {
                "fio": ci.get("fio", ""),
                "email": ci.get("email", ""),
                "phone": "",
            }
            phones = ci.get("phones", {}).get("phones", [])
            if phones:
                p = phones[0]
                contact["phone"] = f"+{p.get('country','')}{p.get('city','')}{p.get('number','')}"

        # applicantVacancyResponseStatuses{vid} — test.required / letterMaxLength;
        # aiAssistantInfo — HR подключил ML-скрининг откликов.
        avrs = ((body.get("vacancyView") or {}).get("applicantVacancyResponseStatuses")
                or data.get("applicantVacancyResponseStatuses") or {})
        vac_status = avrs.get(str(vid), {}) if isinstance(avrs, dict) else {}
        letter_max = vac_status.get("letterMaxLength")
        test_info = vac_status.get("test") or {}
        ai_info = ((body.get("vacancyView") or {}).get("aiAssistantInfo")
                   or data.get("aiAssistantInfo") or {})
        extras = {
            "letter_max_length": int(letter_max) if isinstance(letter_max, (int, str)) and str(letter_max).isdigit() else None,
            "test_required": bool(test_info.get("required")) if test_info else False,
            "ai_assistant_enabled": bool(ai_info.get("isCurrentlyEnabled")),
        }

        return {"ok": True, "reason": "", "contact": contact, "extras": extras}
    except Exception as e:
        log_debug(f"_check_vacancy_before_apply {vid}: {e}")
        # Fail-closed: на любой неожиданной ошибке лучше пропустить вакансию,
        # чем зря потратить лимит откликов.
        return {"ok": False, "reason": str(e), "skip_reason": "exception"}


def check_limit(acc: dict) -> bool:
    """True если лимит активен. Uses GET popup (no side effects)."""
    # GET popup — safe, no side effects, no wasted apply slots
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    if not xsrf:
        return True
    try:
        r_search = _with_retry(
            lambda: HH.get(
                hh_base() + "/search/vacancy?text=&area=1&page=0",
                headers={"User-Agent": webview_user_agent(),
                         "Accept": "text/html"},
                cookies=acc["cookies"], cookie_jar_key=_token_key(acc) or None,
                timeout=_HH_DEFAULT_TIMEOUT,
            ),
            retries=3, backoff_base=2.0,
        )()
        vids = re.findall(r'/vacancy/(\d+)', r_search.text)
        if not vids:
            return True
        vid = vids[0]
        # Use GET popup — safe, no side effects
        r = _with_retry(
            lambda: HH.get(
                f"{hh_base()}/applicant/vacancy_response/popup?vacancyId={vid}",
                headers={"User-Agent": webview_user_agent(),
                         "Accept": "application/json", "X-Xsrftoken": xsrf},
                cookies=acc["cookies"], cookie_jar_key=_token_key(acc) or None,
                timeout=_HH_DEFAULT_TIMEOUT,
            ),
            retries=3, backoff_base=2.0,
        )()
        if "negotiations-limit-exceeded" in r.text:
            return True
        return None  # Absence of the marker does not prove quota recovery.
    except Exception:
        return True


def touch_resume(acc: dict) -> tuple:
    """
    Поднять резюме в поиске.
    Порядок попыток:
      1. OAuth — не требует капчи, но иногда 429.
      2. `POST /shards/resume/batch_update` — обновляет все резюме аккаунта одним
         вызовом, без fingerprint, без капчи. Если пройдёт — бесплатный boost.
      3. `POST /applicant/resumes/touch` — старый путь, может отдать капчу.
    Возвращает (success: bool, message: str)
    """
    ok, msg = _oauth_touch_resume(acc)
    if ok:
        return True, msg
    if "429" not in msg:
        log_debug(f"touch_resume OAuth failed: {msg}, пробую batch_update")

    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    if not xsrf:
        return False, msg or "Missing _xsrf token"
    headers = get_headers(xsrf)

    try:
        ensure_mutation_allowed(acc)
        r = HH.post(
            hh_base() + "/shards/resume/batch_update",
            headers=headers,
            cookies=acc["cookies"],
            cookie_jar_key=_token_key(acc) or None,
            timeout=_HH_DEFAULT_TIMEOUT,
        )
        if r.status_code == 200:
            captcha_flag = False
            try:
                _bd = r.json()
                captcha_flag = bool(
                    (_bd.get("hhcaptcha") or {}).get("isBot")
                    or (_bd.get("recaptcha") or {}).get("isBot")
                )
            except Exception:
                captcha_flag = '"isbot":true' in (r.text or "").lower().replace(" ", "")
            if captcha_flag:
                log_debug("batch_update: сервер отдал hhcaptcha/recaptcha isBot=true")
            else:
                return True, "Резюме подняты (batch_update)"
        elif r.status_code >= 500:
            raise OutcomeUnknown("Поднятие резюме не подтверждено")
        elif r.status_code == 429:
            return False, "Слишком часто (429)"
        else:
            log_debug(f"batch_update HTTP {r.status_code}, пробую /applicant/resumes/touch")
    except (MutationBlocked, OutcomeUnknown):
        raise
    except Exception as e:
        raise OutcomeUnknown("Поднятие резюме не подтверждено") from e

    resume_hash = acc["resume_hash"]
    touch_files = {
        "resume": (None, resume_hash),
        "undirectable": (None, "true"),
    }
    try:
        ensure_mutation_allowed(acc)
        response = _with_retry(
            lambda: HH.post(
                hh_base() + "/applicant/resumes/touch",
                headers=headers,
                cookies=acc["cookies"],
                cookie_jar_key=_token_key(acc) or None,
                files=touch_files,
                timeout=_HH_DEFAULT_TIMEOUT,
            ),
            retries=0, backoff_base=2.0,
        )()

        if response.status_code == 200:
            return True, "Резюме поднято (web)!"
        elif response.status_code >= 500:
            raise OutcomeUnknown("Поднятие резюме не подтверждено")
        elif response.status_code == 429:
            return False, "Слишком часто (429)"
        else:
            return False, msg or f"HTTP {response.status_code}"

    except (MutationBlocked, OutcomeUnknown):
        raise
    except Exception as e:
        raise OutcomeUnknown("Поднятие резюме не подтверждено") from e


def fetch_related_vacancies(acc: dict, seed_vid: str, max_pages: int = 1) -> list:
    """`GET /shards/vacancy/related_vacancies?vacancyId=X&SourceLabel=suitable_vacancies`
    — рекомендательный фид HH: подбирает похожие вакансии под seed по своему
    ML-ranker'у. Обычно лучше match'ит чем текстовый поиск.
    Возвращает уникальный список vacancy_id (строки).
    """
    if not seed_vid:
        return []
    xsrf = (acc.get("cookies") or {}).get("_xsrf", "")
    headers = get_headers(xsrf) if xsrf else {}
    # X-Proxied-* обязательны для /shards/* endpoint'ов чтобы сервер не отказал 4xx.
    headers.update({
        "X-Proxied-Hhtm-Source": "vacancy",
        "X-Proxied-Page-Name": "vacancy",
        "X-Proxied-Place": "related_vacancies",
        "X-Proxied-Type": "Component",
        "X-Use-SSR": "False",
        "X-Is-SPA": "true",
        "Accept": "application/json",
    })
    out = []
    seen = set()
    for page in range(1, max_pages + 1):
        try:
            r = HH.get(
                f"{hh_base()}/shards/vacancy/related_vacancies",
                params={
                    "vacancyId": str(seed_vid),
                    "page": page,
                    "SourceLabel": "suitable_vacancies",
                },
                headers=headers,
                cookies=acc.get("cookies", {}),
                cookie_jar_key=_token_key(acc) or None,
                timeout=8,
            )
            if r.status_code != 200:
                break
            data = r.json()
            items = data.get("vacancies") or data.get("items") or []
            for it in items:
                vid = str((it or {}).get("vacancyId") or (it or {}).get("id") or "")
                if vid and vid not in seen:
                    seen.add(vid)
                    out.append(vid)
            total = data.get("totalPages") or 1
            if page >= total:
                break
        except Exception as e:
            log_debug(f"fetch_related_vacancies seed={seed_vid} p={page}: {e}")
            break
    return out

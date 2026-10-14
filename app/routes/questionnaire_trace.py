"""One controlled questionnaire application while background automation stays paused."""

import asyncio
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from app.config import CONFIG
from app.instances import bot
from app.storage import add_applied, get_test_vacancy_stats, is_applied, is_test


router = APIRouter()
TRACE_FILE = Path("data/questionnaire_trace.jsonl")
_write_lock = threading.Lock()
_run_lock = asyncio.Lock()
_VID = re.compile(r"\d{5,20}\Z")
_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
_review_drafts: dict[str, dict] = {}
_REVIEW_TTL_SECONDS = 1200


def _read_runs() -> dict[str, list[dict]]:
    """Read durable traces, tolerating a torn final line after a crash."""
    runs: dict[str, list[dict]] = {}
    if not TRACE_FILE.exists():
        return runs
    with TRACE_FILE.open(encoding="utf-8") as source:
        for line in source:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or not _RUN_ID.fullmatch(str(event.get("run_id", ""))):
                continue
            runs.setdefault(event["run_id"], []).append(event)
    return runs


def _run_summary(run_id: str, events: list[dict]) -> dict:
    start = next((e for e in events if e.get("stage") == "started"), events[0])
    start_details = start.get("details") or {}
    result = next((e for e in reversed(events) if e.get("stage") == "result"), None)
    error = next((e for e in reversed(events) if e.get("stage") == "error"), None)
    blocked = next((e for e in reversed(events) if e.get("stage") in ("answer_review_blocked", "answer_gender_blocked")), None)
    submitted = any(e.get("stage") == "submission_started" for e in events)
    no_fields = any(e.get("stage") == "form_unrecognized" for e in events)
    form = next((e for e in events if e.get("stage") == "form_parsed"), None)
    result_details = (result or {}).get("details") or {}
    review = next((e for e in reversed(events) if e.get("stage") == "post_run_review"), None)
    review_details = (review or {}).get("details") or {}
    status = result_details.get("status") or ("error" if error else "unknown" if submitted else "in_progress")
    return {"run_id": run_id, "at": start.get("at", ""),
            "account": start.get("account", ""), "vacancy_id": start.get("vacancy_id", ""),
            "title": start_details.get("title", ""), "company": start_details.get("company", ""),
            "origin": start_details.get("origin", "targeted"), "status": status,
            "submitted": submitted, "question_count": len(((form or {}).get("details") or {}).get("questions") or []),
            "error_code": (result_details.get("info") or {}).get("error_code", ""),
            "diagnosis": review_details.get("diagnosis", ""),
            "no_fields": no_fields,
            "blocked": bool(blocked)}


@router.get("/api/apply/questionnaire-history")
async def questionnaire_history(limit: int = 100, offset: int = 0):
    """Summaries of questionnaire attempts, newest first."""
    runs = _read_runs()
    items = [_run_summary(run_id, events) for run_id, events in runs.items() if events]
    items.sort(key=lambda item: item["at"], reverse=True)
    start = max(0, offset)
    outcomes = {
        "confirmed": sum(item["status"] == "sent" for item in items),
        "already": sum(item["status"] == "already" for item in items),
        "no_fields": sum(item["no_fields"] for item in items),
        "returned_to_form": sum(item["status"] == "test" and item["submitted"] for item in items),
        "visibility_blocked": sum(item["error_code"] == "resume_visibility_restricted"
                                  or item["diagnosis"] == "resume_visibility_restricted"
                                  for item in items),
        "unconfirmed": sum(item["status"] == "unknown" for item in items),
    }
    no_field_vacancies = {item["vacancy_id"] for item in items if item["no_fields"]}
    outcomes["no_field_vacancies"] = len(no_field_vacancies)
    return {"ok": True, "total": len(items), "stats": get_test_vacancy_stats(),
            "outcomes": outcomes,
            "items": items[start:start + min(max(1, limit), 200)]}


@router.get("/api/apply/questionnaire-history/{run_id}")
async def questionnaire_history_detail(run_id: str):
    """Questionnaire, final answers, LLM metadata, and full recorded timeline."""
    if not _RUN_ID.fullmatch(run_id):
        return {"ok": False, "error": "Некорректный ID прогона"}
    events = _read_runs().get(run_id)
    if not events:
        return {"ok": False, "error": "Прогон не найден"}
    summary = _run_summary(run_id, events)
    form = next((e for e in events if e.get("stage") == "form_parsed"), None)
    ready = next((e for e in reversed(events) if e.get("stage") == "answers_ready"), None)
    llm = next((e for e in reversed(events) if e.get("stage") == "llm_request"), None)
    questions = ((form or {}).get("details") or {}).get("questions") or []
    answers = ((ready or {}).get("details") or {}).get("answers") or {}
    sources = ((ready or {}).get("details") or {}).get("sources") or {}
    question_rows = [{"field": q.get("field", ""), "text": q.get("text", ""),
                      "type": q.get("type", ""), "answer": answers.get(q.get("field")),
                      "source": sources.get(q.get("field"), "")}
                     for q in questions if isinstance(q, dict)]
    # Explicit allowlist prevents future trace fields from exposing credentials.
    allowed = {"started", "web_session_ready", "form_parsed", "form_fetch_failed", "already_responded",
               "form_unrecognized", "resume_visibility_blocked", "resume_context", "llm_context", "llm_request", "llm_response",
               "llm_answers_validated", "llm_answers_rejected", "llm_no_answer", "llm_quota_exceeded",
               "llm_empty_response", "llm_invalid_json", "answers_ready",
               "answer_review_blocked", "answer_gender_blocked", "submission_started", "submission_response",
               "preview_ready", "reviewed_answers_reused", "reviewed_form_changed",
               "result", "error", "exception", "post_run_review", "context_audit"}
    timeline = [{"at": e.get("at", ""), "stage": e.get("stage", ""),
                 "details": e.get("details") or {}}
                for e in events if e.get("stage") in allowed]
    return {"ok": True, "run": summary, "questions": question_rows,
            "llm": ((llm or {}).get("details") or {}), "timeline": timeline}


def _record(run_id: str, account: str, vacancy_id: str, stage: str, details: dict | None = None):
    """Append a private, durable JSONL event without credentials or resume text."""
    event = {"at": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
             "account": account, "vacancy_id": vacancy_id, "stage": stage,
             "details": details or {}}
    TRACE_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _write_lock:
        fd = os.open(TRACE_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            payload = (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode()
            while payload:
                payload = payload[os.write(fd, payload):]
            os.fsync(fd)
        finally:
            os.close(fd)


def _already_submitted(account: str, vacancy_id: str) -> bool:
    if not TRACE_FILE.exists():
        return False
    with TRACE_FILE.open(encoding="utf-8") as source:
        for line in source:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if (item.get("account") == account and item.get("vacancy_id") == vacancy_id
                    and item.get("stage") == "submission_started"):
                return True
    return False


@router.get("/api/apply/trace-questionnaire/probe/{idx}/{vid}")
async def probe_questionnaire(idx: int, vid: str):
    """Read the current HH form for a known test vacancy without applying."""
    if not _VID.fullmatch(vid):
        return {"ok": False, "error": "Некорректный ID вакансии"}
    state = bot._get_apply_state(idx)
    if state is None or not is_test(vid):
        return {"ok": False, "error": "Аккаунт или тестовая вакансия не найдены"}
    if is_applied(state.name, vid):
        return {"ok": False, "error": "Отклик уже записан"}
    if not bot.paused:
        return {"ok": False, "error": "Сначала остановите автоматические отклики"}
    try:
        import aiohttp
        from app.hh_apply import _aio_egress_kwargs
        from app.config import hh_base
        from app.questionnaire import _parse_questionnaire_rich
        from app.user_agent import webview_user_agent
        from app.logging_utils import _is_login_page

        account = {**state.acc}
        if str(account.get("mode") or "").lower() == "oauth":
            from app.mobile_questionnaire import oauth_web_account
            account = await oauth_web_account(account)
        url = f"{hh_base()}/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"
        sess_kw, req_kw = _aio_egress_kwargs()
        async with aiohttp.ClientSession(cookies=account.get("cookies") or {},
                headers={"User-Agent": webview_user_agent(), "Referer": f"{hh_base()}/vacancy/{vid}"},
                **sess_kw) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), **req_kw) as response:
                html = await response.text()
                status = response.status
        if status in (401, 403) or _is_login_page(html):
            return {"ok": False, "status": "auth", "http_status": status}
        if status != 200:
            return {"ok": False, "status": "form_unavailable", "http_status": status}
        if re.search(r'data-qa\s*=\s*["\']already-responded-text["\']', html):
            return {"ok": False, "status": "already_responded", "vacancy_id": vid,
                    "question_count": 0, "question_types": []}
        questions = _parse_questionnaire_rich(html)
        return {"ok": bool(questions), "status": "ready" if questions else "no_questions",
                "vacancy_id": vid, "question_count": len(questions),
                "question_types": [q.get("type") for q in questions]}
    except Exception as exc:
        return {"ok": False, "status": "probe_error", "error_type": type(exc).__name__}


@router.post("/api/apply/trace-questionnaire")
async def trace_questionnaire(body: dict):
    """Send one known test vacancy, keeping the global automation pause on."""
    phase = str(body.get("phase") or "direct")
    if phase not in ("direct", "preview", "submit_reviewed"):
        return {"ok": False, "error": "Неизвестная фаза проверки анкеты"}
    try:
        idx = int(body.get("account_idx"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Укажите account_idx"}
    vid = str(body.get("vacancy_id") or "")
    if not _VID.fullmatch(vid):
        return {"ok": False, "error": "Некорректный ID вакансии"}

    async with _run_lock:
        state = bot._get_apply_state(idx)
        if state is None:
            return {"ok": False, "error": "Аккаунт не найден"}
        if not bot.paused or not CONFIG.automation_paused:
            return {"ok": False, "error": "Сначала остановите автоматические отклики"}
        if not CONFIG.llm_enabled or not CONFIG.llm_fill_questionnaire:
            return {"ok": False, "error": "LLM-заполнение анкет выключено"}
        if not is_test(vid):
            return {"ok": False, "error": "Вакансия отсутствует в базе тестов"}
        if is_applied(state.name, vid):
            return {"ok": False, "error": "Отклик уже записан"}
        if _already_submitted(state.name, vid):
            return {"ok": False, "error": "Для этой вакансии уже была точечная отправка; проверьте журнал и HH"}
        if not bot._can_mutate(state, allow_global_pause=True):
            return {"ok": False, "error": "Аккаунт недоступен: пауза, капча, лимит или неподтверждённый отклик"}
        now = time.time()
        for key, draft in list(_review_drafts.items()):
            if draft["expires_at"] <= now:
                del _review_drafts[key]
        draft_id = str(body.get("draft_id") or "")
        draft = _review_drafts.get(draft_id) if phase == "submit_reviewed" else None
        if phase == "submit_reviewed" and (draft is None or draft["account_idx"] != idx
                                            or draft["account"] != state.name or draft["vacancy_id"] != vid):
            return {"ok": False, "error": "Проверенный черновик не найден или устарел; создайте новый предпросмотр"}

        run_id = uuid.uuid4().hex
        def trace(stage, details):
            _record(run_id, state.name, vid, stage, details)

        meta = getattr(state, "vacancy_meta", {}).get(vid, {})
        trace("started", {"account_idx": idx, "mode": state.acc.get("mode", "web"),
                          "title": meta.get("title", ""), "company": meta.get("company", ""),
                          "origin": "targeted", "phase": phase,
                          "reviewed_from": draft.get("preview_run_id") if draft else ""})
        # Only this copied account bypasses the global pause. All protective
        # account guards remain active, and unpausing globally aborts the POST.
        account = {**state.acc}
        account["_mutation_guard"] = lambda: (bot.paused and
            bot._get_apply_state(idx) is state and
            bot._can_mutate(state, allow_global_pause=True))
        try:
            if str(account.get("mode") or "").lower() == "oauth":
                from app.mobile_questionnaire import oauth_web_account
                account = await oauth_web_account(account)
                trace("web_session_ready", {"source": "oauth_bridge"})
            from app.hh_apply import fill_and_submit_questionnaire
            result, info = await fill_and_submit_questionnaire(
                account, vid, receipt_account=state.acc,
                trace=trace, require_llm=True, preview_only=(phase == "preview"),
                approved_answers=draft["answers"] if draft else None,
                expected_questions=draft["questions"] if draft else None)
            if phase == "submit_reviewed":
                _review_drafts.pop(draft_id, None)
            if phase == "preview" and result == "preview":
                review_id = uuid.uuid4().hex
                _review_drafts[review_id] = {
                    "account_idx": idx, "account": state.name, "vacancy_id": vid,
                    "preview_run_id": run_id, "expires_at": time.time() + _REVIEW_TTL_SECONDS,
                    "questions": info["questions"], "answers": info["answers"],
                }
                trace("result", {"status": "preview", "info": {"review_expires_in": _REVIEW_TTL_SECONDS}})
                return {"ok": True, "status": "preview", "vacancy_id": vid,
                        "run_id": run_id, "draft_id": review_id,
                        "questions": info["questions"], "answers": info["answers"],
                        "sources": info["sources"]}
            safe_info = {k: v for k, v in (info or {}).items()
                         if k in ("error_code", "error_type", "http_status", "reason", "receipt_confirmed")
                         and isinstance(v, (str, int, bool))}
            trace("result", {"status": result, "info": safe_info})
            if result == "sent":
                add_applied(state.name, vid)
                bot._maybe_roll_daily_counter(state)
                state.sent += 1
                state.daily_sent += 1
                state.questionnaire_sent += 1
                bot._add_log(state.short, state.color, f"📝 Точечный отклик с LLM: {vid}", "success")
            elif result == "already":
                add_applied(state.name, vid, confirmed=False)
            elif result == "unknown":
                bot.hold_pending_apply(state, vid,
                    str(state.acc.get("_pinned_resume_id") or state.acc.get("resume_hash") or ""),
                    flow="questionnaire", reason_code="questionnaire_unconfirmed")
            return {"ok": result in ("sent", "already"), "status": result,
                    "vacancy_id": vid, "run_id": run_id,
                    "log": str(TRACE_FILE)}
        except Exception as exc:
            trace("error", {"error_type": type(exc).__name__})
            return {"ok": False, "status": "error", "run_id": run_id,
                    "error": "Не удалось завершить точечный отклик; проверьте журнал и HH"}

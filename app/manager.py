"""
BotManager — core bot logic with per-account worker threads.
"""

import asyncio
import aiohttp
import json
import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from collections import deque
from contextlib import nullcontext
from pathlib import Path
import time
import threading
import requests
import urllib.parse
from types import SimpleNamespace
from app import human_pace, chat_humanize
from app.hh_http import HH
from app.user_agent import mobile_user_agent, webview_user_agent
try:
    from zoneinfo import ZoneInfo
    _MSK = ZoneInfo("Europe/Moscow")
except Exception:
    _MSK = None  # fallback на local

from app.logging_utils import log_debug, log_exception, _is_login_page
from app.questionnaire import questionnaire_preset_previews
from app.vacancy_signals import normalize_vacancy_signals, vacancy_signal_priority
from app.vacancy_salary import salary_for_ruble_threshold
from app.mutation_safety import MutationBlocked, ensure_mutation_allowed
from app.search_scope import remote_it_filters, remote_it_url, remote_it_rejection, scope_metadata
from app.apply_quarantine import blocked as quarantine_blocked
from app.telegram_alerts import (AlertCategory, TOGGLES, account_key, scope_key,
                                 classify_chat_message, send_alert, notify_account_state_change)
from app.telegram_notify import is_configured as telegram_is_configured, send_once as telegram_send_once


def parse_search_url(url: str) -> tuple[str, int | str | list[str] | None, dict]:
    """Convert an HH web/API search URL to ``search_vacancies`` arguments."""
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(url).query, keep_blank_values=False
    )

    def _take(name, default):
        values = query.pop(name, None)
        return values[-1] if values else default

    text = _take("text", "")
    # Missing area means no country/region restriction, as in the HH API.
    # Do not silently turn a worldwide search into Russia-only (113).
    areas = query.pop("area", [])
    area = areas if len(areas) > 1 else (areas[0] if areas else None)
    # Pagination is controlled by the collector/mobile client.  These keys are
    # properties of the SSR URL, not vacancy filters.
    for key in ("page", "per_page", "items_on_page", "ored_clusters"):
        query.pop(key, None)
    filters = {
        key: values[0] if len(values) == 1 else values
        for key, values in query.items()
    }
    return text, area, filters


def _mobile_search_filters(filters: dict) -> dict:
    """Add Android-native ordering/period controls to a mobile search.

    The API supports period values 1, 3 and 7 days.  Fresh mode requests the
    newest vacancies from HH before the local page cap is applied; otherwise a
    locally sorted result can still miss the globally newest vacancies.
    """
    result = dict(filters or {})
    if CONFIG.remote_it_only:
        result = remote_it_filters(result)
    labels = result.get("label", [])
    labels = list(labels) if isinstance(labels, (list, tuple)) else [labels]
    if CONFIG.filter_agencies:
        labels.append("not_from_agency")
    if CONFIG.filter_low_competition:
        labels.append("low_performance")
    labels = list(dict.fromkeys(label for label in labels if label))
    if labels:
        result["label"] = labels[0] if len(labels) == 1 else labels
    if CONFIG.prefer_hh_signals:
        result["with_skills_match"] = "true"
    if CONFIG.fresh_vacancies_mode:
        result.setdefault("order_by", "publication_time")
    try:
        period = int(CONFIG.search_period_days)
    except (TypeError, ValueError):
        period = 0
    if period in (1, 3, 7):
        result.setdefault("period", period)
    return result


def _uses_api_search(acc: dict, state) -> bool:
    """Mobile accounts use APK-native API search; web uses it in degradation."""
    if str(acc.get("mode", "")).strip().lower() in ("mobile", "oauth"):
        return True
    return bool(
        state.cookies_expired
        and acc.get("resume_hash")
        and state.degraded_fallback_enabled
    )


def _current_vacancy_signals(state) -> dict:
    meta = state.vacancy_meta.get(getattr(state, "current_vacancy_id", ""), {})
    return {key: meta.get(key) for key in (
        "manager_activity", "skills_match_percent", "relations", "first_observed_at", "publication_updated", "observation_unavailable")}


def _server_next_publish_datetime(status: dict) -> datetime | None:
    """Convert HH next_publish_at to the local naive datetime used by AccountState."""
    raw = (status or {}).get("next_publish_at")
    if not raw:
        return None
    try:
        value = str(raw).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError):
        return None


def _vacancy_published_at(meta: dict) -> datetime | None:
    """Parse an HH ISO timestamp without assuming the server timezone."""
    raw = (meta or {}).get("published_at") or (meta or {}).get("created_at")
    if not raw:
        return None
    try:
        value = str(raw).strip().replace("Z", "+00:00")
        # HH uses ISO-8601 offsets in the compact +0300 form; Python versions
        # before 3.11 require the colon form +03:00.
        if len(value) >= 5 and value[-5] in "+-" and value[-4:].isdigit():
            value = value[:-2] + ":" + value[-2:]
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _is_fresh_vacancy(meta: dict, hours: int, now: datetime | None = None) -> bool:
    if meta.get("observation_unavailable") or meta.get("publication_updated"):
        return False
    published = _vacancy_published_at(meta)
    from app.vacancy_history import timestamp
    first = timestamp(meta.get("first_observed_at"))
    earliest = timestamp(meta.get("earliest_published_at"))
    if published and published.tzinfo:
        published = min(x for x in (published, first, earliest) if x)
    if published is None or bool((meta or {}).get("archived")):
        return False
    if now is None:
        now = datetime.now(published.tzinfo) if published.tzinfo else datetime.now()
    elif published.tzinfo and now.tzinfo is None:
        now = now.astimezone(published.tzinfo)
    elif not published.tzinfo and now.tzinfo:
        published = published.replace(tzinfo=now.tzinfo)
    age_seconds = (now - published).total_seconds()
    return 0 <= age_seconds <= max(int(hours), 1) * 3600


def _effective_daily_ceiling() -> int:
    limits = [int(v) for v in (CONFIG.daily_apply_limit, CONFIG.hh_daily_limit)
              if isinstance(v, (int, float)) and int(v) > 0]
    return min(limits) if limits else 200


def _cap_apply_batch(batch, daily_sent, hh_today_applies):
    remaining = max(0, _effective_daily_ceiling() - max(
        daily_sent or 0, hh_today_applies or 0))
    return batch[:remaining]


def _completed_apply_results(batch, results):
    return sorted(zip(batch, results), key=lambda item: not (
        isinstance(item[1], tuple) and item[1][0] in ('sent', 'already')))


def _protect_fresh_batch(batch: list, vacancy_meta: dict, *, hours: int,
                         ceiling: int, reserve: int, used: int,
                         now: datetime | None = None) -> tuple[list, int]:
    """Return allowed batch and count of deferred old vacancies."""
    old_slots = max(0, ceiling - min(max(reserve, 0), ceiling) - max(used, 0))
    total_slots = max(0, ceiling - max(used, 0))
    selected, deferred = [], 0
    for vid in batch:
        if total_slots <= 0:
            deferred += 1
        elif _is_fresh_vacancy(vacancy_meta.get(vid, {}) or {}, hours, now):
            selected.append(vid)
            total_slots -= 1
            # A fresh response also advances the shared daily counter toward
            # the reserve boundary for subsequent old vacancies in this batch.
            old_slots = max(0, old_slots - 1)
        elif old_slots > 0:
            selected.append(vid)
            old_slots -= 1
            total_slots -= 1
        else:
            deferred += 1
    return selected, deferred


def _resume_plain_text(raw) -> str:
    """Mobile API gives resume JSON; keep what an employer reads, drop contacts/URLs/ids."""
    if isinstance(raw, dict) and "text" in raw:
        return str(raw.get("text") or "")
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return raw
    if not isinstance(data, dict):
        return ""
    name = lambda v: (v or {}).get("name", "") if isinstance(v, dict) else str(v or "")
    lines = [f"Должность: {data.get('title') or ''}"]
    salary = data.get("salary") or {}
    if isinstance(salary, dict) and salary.get("amount"):
        lines.append(f"Зарплатные ожидания: {salary['amount']} {salary.get('currency') or ''}".strip())
    if data.get("area"):
        lines.append(f"Город: {name(data['area'])}")
    months = (data.get("total_experience") or {}).get("months") if isinstance(data.get("total_experience"), dict) else None
    if months:
        lines.append(f"Общий опыт: {months // 12} л. {months % 12} мес.")
    for job in (data.get("experience") or [])[:8]:
        if isinstance(job, dict):
            period = f"{job.get('start') or ''}–{job.get('end') or 'н.в.'}"
            lines.append(f"- {job.get('position') or ''}, {job.get('company') or ''} ({period}): "
                         f"{(job.get('description') or '').strip()[:700]}")
    if data.get("skill_set"):
        lines.append("Навыки: " + ", ".join(str(x) for x in data["skill_set"][:40]))
    if data.get("skills"):
        lines.append("О себе: " + str(data["skills"]).strip()[:1500])
    edu = data.get("education") or {}
    for e in (edu.get("primary") or [])[:4] if isinstance(edu, dict) else []:
        if isinstance(e, dict):
            lines.append(f"Образование: {e.get('name') or ''}, {e.get('result') or ''} {e.get('year') or ''}".strip())
    langs = [f"{name(l)} ({name(l.get('level'))})" for l in (data.get("language") or []) if isinstance(l, dict)]
    if langs:
        lines.append("Языки: " + ", ".join(langs))
    return "\n".join(line for line in lines if line.strip(": -"))


def _today_msk() -> str:
    """Дата по Москве. HH работает в MSK; используем её как «день» бота
    чтобы midnight rollover не зависел от TZ контейнера (Docker = UTC по дефолту).
    """
    if _MSK is not None:
        return datetime.now(_MSK).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def _fingerprint_key(key: str) -> str:
    """Безопасный fingerprint API-ключа для UI: first4…last4 (N симв.).
    Полный ключ никогда не уходит в snapshot, но юзер видит что именно
    сохранилось (особенно полезно после релоада когда type=password input
    показывает только звёздочки)."""
    if not key:
        return ""
    s = (key or "").strip()
    if len(s) <= 12:
        return f"••• ({len(s)} симв.)"
    return f"{s[:4]}…{s[-4:]} ({len(s)} симв.)"

from app.config import (
    CONFIG, accounts_data,
    save_config, load_config, save_accounts, load_accounts,
    _url_entry, _url_pages_map, hh_base, questionnaire_default_answer,
)

from app.storage import (
    _load_cache, _cache_applied, _cache_lock,
    add_applied, is_applied, add_test_vacancy, is_test, get_stats,
    load_browser_sessions, save_browser_sessions,
    upsert_interview, get_no_chat_neg_ids, get_replied_keys,
    _schedule_save,
)

from app.oauth import (
    _oauth_apply,
    get_oauth_status,
    _obtain_oauth_token,
    _token_key,
    refresh_oauth_tokens_proactive,
    fetch_saved_vacancy_searches,
    fetch_favorited_vacancies,
    fetch_blacklisted_vacancies,
    fetch_resume_status,
    fetch_employer_rating,
    fetch_vacancy_details,
    fetch_negotiation_messages_oauth,
    send_negotiation_message_oauth,
    fetch_negotiations_today_count,
    fetch_negotiations_statistic,
)

from app.hh_api import (
    get_headers, parse_ids, parse_vacancy_meta, parse_salaries,
    parse_work_schedules, extract_search_query, parse_apply_strategy_meta,
)

from app.llm import generate_llm_reply, _openclaw_command, get_llm_last_status, get_llm_status_summary
from app.gender_guard import conflicting_gender_words

from app.hh_client_factory import get_client
from app.user_agent import login_device_identity
from app.captcha import active as captcha_active
from app.captcha_journal import llm_week as captcha_llm_week

from app.hh_chat import (
    _build_thread_from_chat_item, _check_chat_locked,
    ChatikWSClient,
)

from app.state import AccountState
from app.account_activity import activity_view, set_activity, note_pause, aware_iso
from app.cycle_report import (begin_cycle, found_cycle, consider_cycle, cycle_outcome,
    questionnaire_cycle, cycle_operation_error, finish_cycle, resolve_cycle_unknown, cycle_snapshot)

LLM_LOG_FILE = Path("data") / "llm_log.jsonl"

# -- Async page fetcher (used only by BotManager) --

async def fetch_page(session, url, sem, req_kw: dict | None = None):
    async with sem:
        try:
            await asyncio.sleep(0.05)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10), **(req_kw or {})) as r:
                html = await r.text()
                # Логируем только не-200 и аномальные размеры — иначе hundreds
                # of disk writes per cycle давят RotatingFileHandler (swarm-16 #9).
                if r.status != 200 or len(html) < 1000:
                    log_debug(f"⚠️ URL: {url} | Статус: {r.status} | Размер: {len(html)}")
                return html
        except Exception as e:
            log_debug(f"❌ ОШИБКА при загрузке: {url} | {type(e).__name__}: {e}")
            return ""


# ============================================================
# BOT MANAGER
# ============================================================

def _handle_edited_event(state, payload: dict) -> None:
    """HR отредактировал сообщение — кэшированный draft устарел (строился на
    старом тексте). Дропаем ключи по этому чату, LLM пересчитает на след. цикле."""
    chat_id = str(payload.get("chatId") or payload.get("chat_id") or "")
    if not chat_id:
        return
    with state._llm_drafts_lock:
        if state._llm_drafts:
            to_drop = [k for k in list(state._llm_drafts.keys()) if str(k[0]) == chat_id]
            for k in to_drop:
                state._llm_drafts.pop(k, None)
            if to_drop:
                log_debug(f"WS push [{state.short}] edited в {chat_id}: сброшено {len(to_drop)} черновиков")


class BotManager:
    def __init__(self):
        self.paused = CONFIG.automation_paused
        self._stop_event = threading.Event()
        self.account_states: list[AccountState] = []
        self.activity_log: deque = deque(maxlen=100)
        self.recent_responses: deque = deque(maxlen=100)
        self.llm_log: deque = deque(maxlen=200)    # LLM reply history
        # Защищает list(deque) snapshot от race с concurrent appendleft.
        # В CPython deque.appendleft атомарен, но `list(deque)` иногда падает с RuntimeError при гонке.
        self._deque_lock = threading.Lock()
        self.vacancy_queues: dict = {}
        self._start_time: datetime = None
        self.temp_sessions: list = load_browser_sessions()  # сессии из браузера (персистентные)
        self.temp_states: dict[int, AccountState] = {}  # temp_idx → AccountState для активных сессий
        # Global dedup across all accounts: {(cur_pid, neg_id, last_msg_id)}
        # Prevents double-sends when multiple accounts share the same HH user (same cur_pid)
        self._llm_sent_global: set = set()
        self._llm_sent_by_neg_id: dict = {}  # индекс neg_id -> set(global_key) для O(1) очистки
        self._llm_sent_lock = threading.Lock()
        # HR contacts collected from contactInfo during pre-checks
        self.hr_contacts: list = []  # capped at 500
        self._hr_contacts_lock = threading.Lock()
        # Guards activate_session against concurrent WS calls spawning duplicate workers
        self._activate_lock = threading.Lock()
        self._pause_persist_lock = threading.Lock()
        self._retiring_sessions = []  # (session object, state), until workers exit
        # Сериализация append к data/llm_log.jsonl (kimi-search-1 #5).
        self._llm_log_write_lock = threading.Lock()

    def _can_mutate(self, state, *, llm=False, chat=False, allow_global_pause=False):
        from app.captcha import active as captcha_active
        stop = getattr(self, "_stop_event", None)
        # The daily apply quota does not apply to answering HR in existing chats.
        chat = chat or llm
        limit_only = chat and getattr(state, "paused_reason", "") == "limit"
        return not (
            (stop is not None and stop.is_set())
            or (getattr(self, "paused", False) and not allow_global_pause)
            or (state.paused and not limit_only) or state._deleted
            or (getattr(state, "hard_stopped", False) and not chat)
            or getattr(state, "pending_apply", None)
            or getattr(state, "_auth_recovery_pending", False)
            or human_pace.captcha_cooldown_remaining(state) > 0
            or captcha_active(getattr(state, 'acc', {}))
            or (llm and (not state.llm_enabled or not CONFIG.llm_enabled or not CONFIG.llm_auto_send))
        )

    def _bind_mutation_guard(self, state):
        state.acc["_mutation_guard"] = lambda: self._can_mutate(state)
        state.acc['_on_challenge'] = lambda: self._hold_captcha(state)

    def _hold_captcha(self, state):
        with state._state_lock:
            state._last_captcha_at = time.time()
            state.acc['_last_captcha_at'] = state._last_captcha_at
            state.paused = True
            if not state.pending_apply and state.paused_reason not in ('auth', 'limit', 'message_outcome_unknown'):
                state.paused_reason = 'challenge'
            state.status_detail = 'HH требует капчу. Пройдите проверку вручную; отправки остановлены.'
        self._persist_pauses(wait=True)

    @staticmethod
    def _activity_vacancy(state, vacancy_id=None):
        """Presentation only: a batch has no single current vacancy."""
        with state._state_lock:
            meta = state.vacancy_meta.get(str(vacancy_id), {}) if vacancy_id else {}
            state.current_vacancy_id = str(vacancy_id) if vacancy_id else ""
            state.current_vacancy_title = str(meta.get("title") or "")
            state.current_vacancy_company = str(meta.get("company") or "")

    def _persist_pauses(self, *, wait=False):
        # Serialize the entire capture + queue/barrier sequence. setdefault
        # supports intentionally minimal __new__ test/manually built managers.
        lock = self.__dict__.setdefault("_pause_persist_lock", threading.Lock())
        with lock:
            self._persist_pauses_locked(wait=wait)

    def _persist_pauses_locked(self, *, wait=False):
        def snapshot(state):
            note_pause(state)
            return {**{k: getattr(state, k) for k in
                       ("paused", "paused_reason", "hard_stopped", "limit_exceeded")},
                    "pending_apply": dict(state.pending_apply) if state.pending_apply else None,
                    "pending_applies": [dict(item) for item in state.pending_applies],
                    "network_recovery": dict(state.network_recovery) if getattr(state, "network_recovery", None) else None,
                    # Post-captcha cooldown/rate cut must survive restarts.
                    "last_captcha_at": float(getattr(state, "_last_captcha_at", 0) or 0),
                    "pause_date": _today_msk()}
        for state in getattr(self, "account_states", []):
            with state._state_lock:
                state.acc.update(snapshot(state))
        for idx, state in list(getattr(self, "temp_states", {}).items()):
            sessions = getattr(self, "temp_sessions", [])
            if idx < len(sessions):
                with state._state_lock:
                    captured = snapshot(state)
                    state.acc.update(captured)
                    sessions[idx].update(captured)
        # A stopped worker may receive an ambiguous ACK while it is retiring.
        # Activation waits for that worker; do not lose its protective state.
        for session, state in getattr(self, "_retiring_sessions", []):
            if any(session is item for item in getattr(self, "temp_sessions", [])):
                with state._state_lock:
                    session.update(snapshot(state))
        # File I/O may block. Never hold an account lock while waiting for it.
        if wait:
            save_accounts(wait=True)
        else:
            save_accounts()
        save_browser_sessions(getattr(self, "temp_sessions", []), wait=True)

    @staticmethod
    def _pause_detail(state):
        if state.paused_reason == "outcome_unknown" or state.pending_apply:
            return "Исход отклика неизвестен. Нужна сверка в HH; повторная отправка заблокирована"
        return {
            "manual": "Пауза пользователем",
            "auth": "Пауза: требуется восстановить авторизацию HH",
            "hh_rate_limit": "HH ограничил запросы к анкете. Автоматические попытки остановлены",
            "challenge": "HH запросил проверку доступа. Это не означает, что вход истёк",
            "auto_errors": "Защитная пауза: несколько ошибок подряд; нужна проверка подключения",
            "network_error": "Сетевая пауза: веб-анкеты не отправлены. Проверка соединения без повторной отправки",
            "message_outcome_unknown": "Результат сообщения неизвестен. Проверьте чат HH перед продолжением",
            "limit": "Пауза: достигнут лимит откликов",
        }.get(state.paused_reason, "Автоматизация приостановлена")

    @staticmethod
    def _resume_manual(state):
        """Explicit user activation cannot override a protective stop."""
        if (state.paused and state.paused_reason == "manual"
                and not state.pending_applies and not state.hard_stopped
                and (not state.limit_exceeded or getattr(state, "_limit_is_throttle", False))
                and not state.cookies_expired):
            state.paused = False
            state.paused_reason = ""
            state.consecutive_errors = 0
            state.status = "idle"
            state.status_detail = "Ожидание следующего цикла"
            return True
        return False

    def hold_pending_apply(self, state, vacancy_id, resume_id, flow="apply", reason_code="unconfirmed"):
        """Record an ambiguous result locally, never retry or contact HH."""
        reason_code = reason_code if reason_code in (
            "unconfirmed", "transport_unknown", "questionnaire_unconfirmed") else "unconfirmed"
        item = {"vacancy_id": str(vacancy_id), "resume_id": str(resume_id or ""),
                "flow": "questionnaire" if flow == "questionnaire" else "apply",
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "reason_code": reason_code,
                "reconcile_attempts": 0,
                "reconcile_next_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
                "reconcile_last_started_at": None}
        with state._state_lock:
            if not any(p.get("vacancy_id") == item["vacancy_id"] and
                       p.get("resume_id") == item["resume_id"] for p in state.pending_applies):
                state.pending_applies.append(item)
            state.pending_apply = state.pending_applies[0]
            state.paused = True
            state.paused_reason = "outcome_unknown"
            state.status = "idle"
            state.status_detail = self._pause_detail(state)
        self._persist_pauses()

    def _quarantine_exhausted_apply(self, state):
        """Release only an exhausted unknown pause, after durable exclusion."""
        from app.apply_quarantine import retain
        from app.captcha import active as captcha_active
        with state._state_lock:
            pending = state.pending_apply
            if (self.paused or self._stop_event.is_set() or state._deleted
                    or not state.paused or state.paused_reason != 'outcome_unknown'
                    or not pending or state.receipt_check_started_at
                    or state.hard_stopped or state.limit_exceeded or state.cookies_expired
                    or captcha_active(state.acc)
                    or (CONFIG.auto_pause_errors > 0 and state.consecutive_errors >= CONFIG.auto_pause_errors)
                    or getattr(state, '_reconcile_persistence_failed', False)
                    or pending.get('reconcile_attempts') != 3
                    or pending.get('reconcile_last_error') != 'unconfirmed'):
                return False
            previous = list(state.pending_applies)
            try:
                retain(state.acc, pending)
            except Exception:
                state._reconcile_persistence_failed = True
                return False
            state._auth_recovery_pending = True
            state.pending_applies = [p for p in previous if p != pending]
            state.pending_apply = state.pending_applies[0] if state.pending_applies else None
            if not state.pending_apply:
                state.paused = False
                state.paused_reason = ''
                state.status = 'idle'
                state.status_detail = 'Неизвестный отклик изолирован; поиск других вакансий продолжится'
        try:
            self._persist_pauses(wait=True)
        except Exception:
            with state._state_lock:
                state.pending_applies = previous
                state.pending_apply = pending
                state.paused = True
                state.paused_reason = 'outcome_unknown'
                state._reconcile_persistence_failed = True
            return False
        finally:
            state._auth_recovery_pending = False
        self._add_log(state.short, state.color,
            'Неподтверждённый отклик изолирован без повторной отправки. Другие вакансии разрешены.', 'warning')
        return True

    def _reconcile_pending_if_due(self, state, *, now=None):
        """At most three scheduled receipt checks, never a repeated application.

        Runs in the existing worker thread. The shared receipt marker also
        excludes a manual HTTP-route check until this GET and local CAS finish.
        Each helper check may make one list GET and one exact-topic GET.
        """
        current_time = now or datetime.now(timezone.utc)
        with state._state_lock:
            if (self.paused or self._stop_event.is_set() or state._deleted
                    or not state.paused or state.paused_reason != "outcome_unknown"
                    or not state.pending_apply or state.receipt_check_started_at
                    or getattr(state, "_reconcile_persistence_failed", False)):
                return False
            # Worker indices for temporary accounts are 900+n, whereas public
            # reconciliation uses len(regular)+n. Resolve by object identity.
            idx = next((i for i, item in enumerate(self.account_states) if item is state), None)
            if idx is None:
                idx = next((len(self.account_states) + i for i, item in self.temp_states.items()
                            if item is state), None)
            if idx is None:
                return False
            pending = state.pending_apply
            if pending.get("reconcile_last_error") in ("auth", "rate_limit"):
                return False  # Also applies to legacy records lacking a schedule.
            schedule_keys = ("reconcile_attempts", "reconcile_next_at", "reconcile_last_started_at")
            initialize = not any(key in pending for key in schedule_keys)
            if initialize:
                pending.update(reconcile_attempts=0,
                    reconcile_next_at=(current_time + timedelta(seconds=30)).isoformat(),
                    reconcile_last_started_at=None)
            attempts = pending.get("reconcile_attempts")
            if type(attempts) is not int or not 0 <= attempts <= 3:
                # A malformed persisted budget is not permission to start over.
                state._reconcile_persistence_failed = True
                return False
            if attempts >= 3:
                return False
            try:
                due = datetime.fromisoformat(str(pending.get("reconcile_next_at") or "").replace("Z", "+00:00"))
                if due.tzinfo is None:
                    return False
            except (ValueError, TypeError):
                return False
            if not initialize and due > current_time:
                return False
            if not pending.get("vacancy_id") or not pending.get("resume_id"):
                return False
            if initialize:
                marker = None
            else:
                attempts += 1
                marker = current_time.isoformat()
                pending["reconcile_attempts"] = attempts
                pending["reconcile_last_started_at"] = marker
                # Reserve the following deadline before I/O as crash recovery.
                delay = {1: 90, 2: 300}.get(attempts)
                pending["reconcile_next_at"] = (current_time + timedelta(seconds=delay)).isoformat() if delay else None
                state.receipt_check_started_at = marker
            expected_pending = dict(pending)
            expected_account = {"resume_hash": state.acc.get("resume_hash"),
                                "user_id": state.acc.get("user_id"),
                                "cookies": dict(state.acc.get("cookies") or {})}
            acc = {**state.acc, "cookies": expected_account["cookies"].copy()}
            acc["_pinned_resume_id"] = str(pending["resume_id"])
            # Persisting this same state must not itself look like a newer
            # user control transition during the compare-and-swap below.
            note_pause(state)
            control_before = self._limit_check_guard(state)
        try:
            self._persist_pauses(wait=True)
        except Exception:
            with state._state_lock:
                state._reconcile_persistence_failed = True
                if marker and state.receipt_check_started_at == marker:
                    state.receipt_check_started_at = None
            self._add_log(state.short, state.color,
                "Автосверка не запущена: не удалось сохранить безопасное состояние. Отклик не повторялся.", "error")
            return False
        if initialize:
            return False
        try:
            with state._state_lock:
                if (self._get_apply_state(idx) is not state
                        or self._limit_check_guard(state) != control_before
                        or state.pending_apply != expected_pending
                        or any(state.acc.get(key) != expected_account.get(key)
                               for key in ("resume_hash", "user_id", "cookies"))):
                    return False
            from app import apply_confirmation as confirmation
            receipt_failure = "unconfirmed"
            try:
                receipt = confirmation.confirm_application_receipt(acc,
                    str(expected_pending["vacancy_id"]), str(expected_pending["resume_id"]))
                if receipt is None:
                    # Thread-local diagnostics must be consumed immediately in
                    # this same worker, not later by the UI/event-loop thread.
                    getter = getattr(confirmation, "receipt_check_failure_reason", None)
                    if callable(getter):
                        code = getter()
                        if isinstance(code, str) and code in (
                                "connect_timeout", "read_timeout", "auth", "rate_limit", "unconfirmed"):
                            receipt_failure = code
            except Exception:
                receipt = None  # No raw proxy, auth or response details in logs.
            with state._state_lock:
                controls_unchanged = self._limit_check_guard(state) == control_before
            if controls_unchanged and receipt and receipt.get("receipt_confirmed") is True:
                if self.confirm_pending_apply(idx,
                        str(expected_pending["vacancy_id"]), str(expected_pending["resume_id"]),
                        str(receipt.get("negotiation_id") or ""),
                        receipt_created_at=str(receipt.get("receipt_created_at") or ""),
                        expected_state=state, expected_pending=expected_pending,
                        expected_account=expected_account, expected_control=control_before):
                    self._add_log(state.short, state.color,
                        "Автосверка: отклик подтверждён в HH. Повторной отправки не было.", "success")
                    return True
            with state._state_lock:
                if (self._get_apply_state(idx) is not state or state.pending_apply != expected_pending
                        or any(state.acc.get(key) != expected_account.get(key)
                               for key in ("resume_hash", "user_id", "cookies"))):
                    return False
                delay = {1: 90, 2: 300}.get(attempts)
                finished_at = now or datetime.now(timezone.utc)
                state.pending_apply["reconcile_last_error"] = receipt_failure
                if receipt_failure in ("auth", "rate_limit"):
                    delay = None  # No automatic probes after an explicit access/rate restriction.
                state.pending_apply["reconcile_next_at"] = (finished_at + timedelta(seconds=delay)).isoformat() if delay else None
            try:
                self._persist_pauses(wait=True)
            except Exception:
                state._reconcile_persistence_failed = True
            self._add_log(state.short, state.color,
                f"Автосверка {attempts}/3: результат не удалось безопасно подтвердить; пауза сохранена. Отклик не повторялся.", "warning")
            return False
        finally:
            with state._state_lock:
                if state.receipt_check_started_at == marker:
                    state.receipt_check_started_at = None

    def record_receipt_failure(self, idx, reason, *, expected_state, expected_pending, expected_account):
        """Persist a bounded GET diagnostic without resuming or resetting budget."""
        code = reason if isinstance(reason, str) and reason in (
            "connect_timeout", "read_timeout", "auth", "rate_limit", "unconfirmed") else "unconfirmed"
        state = self._get_apply_state(idx)
        if state is None or state is not expected_state:
            return False
        with state._state_lock:
            if (state._deleted or self._get_apply_state(idx) is not state
                    or not state.pending_apply or state.pending_apply != expected_pending
                    or any(state.acc.get(key) != expected_account.get(key)
                           for key in ("resume_hash", "user_id", "cookies"))):
                return False
            state.pending_apply["reconcile_last_error"] = code
            if code in ("auth", "rate_limit"):
                state.pending_apply["reconcile_next_at"] = None
        try:
            self._persist_pauses(wait=True)
            return True
        except Exception:
            with state._state_lock:
                state._reconcile_persistence_failed = True
            return False

    def confirm_pending_apply(self, idx, vacancy_id, resume_id, topic_id, *,
                              receipt_created_at="", expected_state=None, expected_pending=None,
                              expected_account=None, expected_control=None):
        """Consume an externally verified receipt; this method performs no RPC.

        The caller must verify exact account/vacancy/resume ownership using a
        fresh HH receipt, and pass the state/pending snapshots from before I/O.
        """
        state = self._get_apply_state(idx)
        if state is None or (expected_state is not None and state is not expected_state):
            return False
        with state._state_lock:
            if state._deleted or self._get_apply_state(idx) is not state or not topic_id:
                return False
            if expected_control is not None and self._limit_check_guard(state) != expected_control:
                return False
            if expected_account is not None and any(
                    state.acc.get(key) != expected_account.get(key)
                    for key in ("resume_hash", "user_id", "cookies")):
                return False
            pending = state.pending_apply
            if (not isinstance(pending, dict) or pending.get("vacancy_id") != str(vacancy_id)
                    or pending.get("resume_id") != str(resume_id)
                    or (expected_pending is not None and pending != expected_pending)):
                return False
            # A receipt proves existence, not that an old application happened
            # today. Missing/malformed/future dates never inflate daily counts.
            today_receipt = False
            try:
                from zoneinfo import ZoneInfo
                receipt_at = datetime.fromisoformat(str(receipt_created_at).replace("Z", "+00:00"))
                today_receipt = (receipt_at.tzinfo is not None
                    and receipt_at <= datetime.now().astimezone()
                    and receipt_at.astimezone(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d") == _today_msk())
            except (ValueError, TypeError, OverflowError):
                pass
            newly_counted = today_receipt and not is_applied(state.name, str(vacancy_id))
            add_applied(state.name, str(vacancy_id), confirmed=newly_counted)
            if newly_counted:
                if state.daily_date != _today_msk():
                    state.daily_date = _today_msk()
                    state.daily_sent = 0
                state.sent += 1
                state.daily_sent += 1
                if pending.get("flow") == "questionnaire":
                    state.questionnaire_sent += 1
                state.last_apply_at = str(receipt_created_at)
            state.pending_applies.pop(0)
            resolve_cycle_unknown(state, vacancy_id, receipt_created_at, locked=True)
            state.pending_apply = state.pending_applies[0] if state.pending_applies else None
            if not state.pending_apply and state.paused_reason == "outcome_unknown":
                from app.captcha import active as captcha_active
                if state.hard_stopped or state.limit_exceeded:
                    state.paused_reason = "limit"
                elif captcha_active(state.acc):
                    state.paused_reason = 'challenge'
                elif state.cookies_expired:
                    state.paused_reason = "auth"
                elif CONFIG.auto_pause_errors > 0 and state.consecutive_errors >= CONFIG.auto_pause_errors:
                    state.paused_reason = "auto_errors"
                else:
                    state.paused = False
                    state.paused_reason = ""
            state.status = "idle"
            state.status_detail = self._pause_detail(state) if state.paused else "Отклик подтверждён в HH"
        self._persist_pauses()
        return True

    def recover_verified_auth(self, idx, *, expected_state, expected_account, expected_control,
                              recovery_reason="auth", expected_network_recovery=None):
        """Local CAS only, after the route verifies account AND web bridge.

        No RPC, refresh, quota reset, or recovery of other protective pauses.
        Mutation dispatch stays blocked until the durable save has completed.
        """
        state = self._get_apply_state(idx)
        if state is None or state is not expected_state or not isinstance(expected_account, dict):
            return False
        account_keys = ("resume_hash", "user_id", "cookies")
        if (recovery_reason not in ("auth", "network_error")
                or any(key not in expected_account for key in account_keys) or expected_control is None):
            return False
        with state._state_lock:
            if (self._get_apply_state(idx) is not state or state._deleted
                    or self.paused or self._stop_event.is_set() or state.pending_apply
                    or state.pending_applies or state.hard_stopped or state.limit_exceeded
                    or not state.paused or state.paused_reason != recovery_reason
                    or (recovery_reason == "network_error" and (
                        not isinstance(expected_network_recovery, dict)
                        or state.network_recovery != expected_network_recovery
                        or not self._valid_network_record(state, expected_network_recovery)))
                    or getattr(state, "_auth_recovery_pending", False)
                    or self._limit_check_guard(state) != expected_control
                    or any(state.acc.get(key) != expected_account[key] for key in account_keys)):
                return False
            state._auth_recovery_pending = True
            old_cookies_expired = state.cookies_expired
            old_network_recovery = getattr(state, "network_recovery", None)
            if recovery_reason == "network_error":
                state.network_recovery = None
            state.cookies_expired = False
            state.paused = False
            state.paused_reason = ""
            note_pause(state)
            recovered_control = self._limit_check_guard(state)
        saved = False
        try:
            self._persist_pauses(wait=True)
            saved = True
        except Exception:
            pass  # No raw storage/account data in the public result.
        with state._state_lock:
            if not saved and recovery_reason == "network_error":
                state._network_recovery_persistence_failed = True
            same_account = (all(state.acc.get(key) == expected_account[key] for key in account_keys)
                and (recovery_reason != "network_error" or self._valid_network_record(state, old_network_recovery)))
            success = (saved and self._get_apply_state(idx) is state
                and self._limit_check_guard(state) == recovered_control and same_account)
            if success:
                state.consecutive_errors = 0
                state._network_error_streak = 0
                state._network_error_last_count = 0
                state._network_recovery_persistence_failed = False
                state.status = "idle"
                state.status_detail = "Вход в HH и доступ к веб-анкете подтверждены"
            elif not state.paused and state.paused_reason == "":
                # A late failed/stale commit must not reopen after global pause
                # or account replacement. Preserve any newer protective reason.
                state.paused = True
                state.paused_reason = recovery_reason
                if recovery_reason == "network_error":
                    state.network_recovery = old_network_recovery
                if same_account:
                    state.cookies_expired = old_cookies_expired
                state.status_detail = "Снятие паузы не подтверждено; нужна повторная проверка"
                note_pause(state)
            state._auth_recovery_pending = False
        if not success:
            try:
                self._persist_pauses(wait=True)
            except Exception:
                pass  # RAM remains blocked even if the storage is unavailable.
        return success

    @staticmethod
    def _network_account_key(acc):
        identity = {key: acc.get(key) for key in ("resume_hash", "user_id", "cookies", "mode")}
        try:
            return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _network_reason(info):
        allowed = ("proxy_error", "tls_error", "connect_timeout", "read_timeout", "timeout",
                   "connection_error", "network_error")
        if (isinstance(info, dict) and info.get("error_type") == "oauth_bridge_network"
                and info.get("phase") == "oauth_bridge" and info.get("dispatched") is False
                and isinstance(info.get("reason"), str) and info["reason"] in allowed):
            return info["reason"]
        return None

    @staticmethod
    def network_recovery_view(state):
        with state._state_lock:
            record = getattr(state, "network_recovery", None)
            if not isinstance(record, dict):
                return None
            return {key: record.get(key) for key in ("reason", "attempts", "next_check_at",
                    "last_started_at", "last_error")}

    def _valid_network_record(self, state, record):
        account_key = self._network_account_key(state.acc)
        return (isinstance(record, dict) and self._network_reason(record) is not None
            and str(state.acc.get("mode") or "").lower() == "oauth"
            and account_key is not None and record.get("account_key") == account_key
            and type(record.get("attempts")) is int and 0 <= record["attempts"] < 1_000_000_000)

    def _network_recovery_matches(self, idx, state, expected_account, expected_control, expected_record):
        # Caller holds the state lock. No network or nested lock acquisition.
        return (self._get_apply_state(idx) is state and not state._deleted
            and not self.paused and not self._stop_event.is_set()
            and state.paused and state.paused_reason == "network_error"
            and not state.pending_apply and not state.pending_applies
            and not state.hard_stopped and not state.limit_exceeded
            and isinstance(expected_record, dict) and state.network_recovery == expected_record
            and self._valid_network_record(state, expected_record)
            and self._limit_check_guard(state) == expected_control
            and all(state.acc.get(key) == expected_account.get(key)
                    for key in ("resume_hash", "user_id", "cookies")))

    def record_network_probe_failure(self, idx, reason, *, expected_state, expected_account,
                                     expected_control, expected_network_recovery):
        """Store only a known probe category; never clear pause or retry a POST."""
        code = reason if isinstance(reason, str) and reason in (
            "network", "auth", "challenge", "rate_limit", "unavailable", "stale") else "unavailable"
        state = self._get_apply_state(idx)
        if state is None or state is not expected_state:
            return False
        with state._state_lock:
            if not self._network_recovery_matches(idx, state, expected_account,
                    expected_control, expected_network_recovery):
                return False
            state.network_recovery["last_error"] = code
            if code != "network":
                state.network_recovery["next_check_at"] = None
        try:
            self._persist_pauses(wait=True)
        except Exception:
            with state._state_lock:
                state._network_recovery_persistence_failed = True
            return False
        return True

    def _network_probe_if_due(self, state, *, now=None):
        """GET-only recovery, 30/90/300/900s backoff; 900s thereafter.

        Only a persisted, owner-bound, known pre-POST network failure qualifies.
        Every attempt is durably reserved before I/O. Restart cannot reset it.
        """
        at = now or datetime.now(timezone.utc)
        invalid = False
        with state._state_lock:
            record = getattr(state, "network_recovery", None)
            if (state.paused and state.paused_reason == "network_error" and isinstance(record, dict)
                    and not self._valid_network_record(state, record) and record.get("next_check_at")):
                record["last_error"] = "stale"
                record["next_check_at"] = None
                invalid = True
        if invalid:
            try:
                self._persist_pauses(wait=True)
            except Exception:
                with state._state_lock:
                    state._network_recovery_persistence_failed = True
            return False
        with state._state_lock:
            if (self.paused or self._stop_event.is_set() or state._deleted
                    or not state.paused or state.paused_reason != "network_error"
                    or state.pending_apply or state.pending_applies or state.hard_stopped
                    or state.limit_exceeded or state.cookies_expired
                    or state.auth_check_started_at or state.receipt_check_started_at
                    or getattr(state, "_auth_recovery_pending", False)
                    or getattr(state, "_network_recovery_persistence_failed", False)
                    or str(state.acc.get("mode") or "").lower() != "oauth"):
                return False
            record = state.network_recovery
            if (not isinstance(record, dict) or self._network_reason(record) is None
                    or record.get("account_key") != self._network_account_key(state.acc)
                    or record.get("last_error") not in (None, "network")
                    or type(record.get("attempts")) is not int
                    or not 0 <= record["attempts"] < 1_000_000_000):
                return False
            try:
                due = datetime.fromisoformat(str(record.get("next_check_at") or "").replace("Z", "+00:00"))
                if due.tzinfo is None or due > at:
                    return False
            except (ValueError, TypeError):
                return False
            idx = next((i for i, item in enumerate(self.account_states) if item is state), None)
            if idx is None:
                idx = next((len(self.account_states) + i for i, item in self.temp_states.items()
                            if item is state), None)
            if idx is None:
                return False
            record["attempts"] += 1
            delay = {1: 90, 2: 300}.get(record["attempts"], 900)
            marker = at.isoformat()
            record["last_started_at"] = marker
            record["next_check_at"] = (at + timedelta(seconds=delay)).isoformat()
            state.auth_check_started_at = marker
            expected_record = dict(record)
            expected_account = {"resume_hash": state.acc.get("resume_hash"),
                "user_id": state.acc.get("user_id"), "cookies": dict(state.acc.get("cookies") or {})}
            acc = {**state.acc, "cookies": expected_account["cookies"].copy()}
            note_pause(state)
            control = self._limit_check_guard(state)
        try:
            try:
                self._persist_pauses(wait=True)
            except Exception:
                with state._state_lock:
                    state._network_recovery_persistence_failed = True
                return False
            with state._state_lock:
                if not self._network_recovery_matches(idx, state, expected_account, control, expected_record):
                    return False
            from app.auth_verification import verify_oauth_and_web_access
            try:
                proof = verify_oauth_and_web_access(acc)
            except Exception:
                proof = None  # Unexpected failure is not permission to keep probing.
            if isinstance(proof, dict) and proof.get("verified") is True:
                return self.recover_verified_auth(idx, expected_state=state,
                    expected_account=expected_account, expected_control=control,
                    recovery_reason="network_error", expected_network_recovery=expected_record)
            reason = proof.get("reason") if isinstance(proof, dict) else "unavailable"
            return self.record_network_probe_failure(idx, reason, expected_state=state,
                expected_account=expected_account, expected_control=control,
                expected_network_recovery=expected_record)
        finally:
            with state._state_lock:
                if state.auth_check_started_at == marker:
                    state.auth_check_started_at = None

    def _hold_questionnaire_access(self, state, result):
        """An explicit access/rate denial is not an expired token or quota."""
        if result not in ("rate_limit", "challenge"):
            return
        with state._state_lock:
            state.errors += 1
            state.consecutive_errors += 1
            # Never replace an unrelated manual/unknown/protective pause.
            if not state.paused and not state.pending_apply:
                state.paused = True
                state.paused_reason = "hh_rate_limit" if result == "rate_limit" else "challenge"
            state.status_detail = self._pause_detail(state)
        self._persist_pauses()
        self._add_log(state.short, state.color, state.status_detail, "warning")

    def reload_temp_sessions(self, sessions: list | None = None) -> int:
        """Refresh browser accounts after OTP materializes their sessions.

        ``sessions`` avoids racing the asynchronous disk writer.  Other callers may
        omit it to reload the persisted snapshot.
        """
        fresh = load_browser_sessions() if sessions is None else sessions
        if not isinstance(fresh, list):
            fresh = []
        self.temp_sessions[:] = fresh
        return len(self.temp_sessions)

    LLM_CHAT_DAILY_REPLY_CAP = 3

    def _chat_sends_today(self, acc_short, neg_id, *, add=False) -> int:
        """Auto-replies sent to one chat today (MSK); seeded once from llm_log.jsonl."""
        from zoneinfo import ZoneInfo
        msk = ZoneInfo("Europe/Moscow")
        today = _today_msk()
        lock = self.__dict__.setdefault("_chat_sends_lock", threading.Lock())
        with lock:
            if getattr(self, "_chat_sends_day", None) != today:
                counts = {}
                try:
                    with open(LLM_LOG_FILE, encoding="utf-8") as f:
                        for line in f:
                            try:
                                e = json.loads(line)
                                when = datetime.fromisoformat(e["time"]).astimezone(msk)
                            except (ValueError, KeyError, TypeError):
                                continue
                            if e.get("send_ok") is True and when.strftime("%Y-%m-%d") == today:
                                k = (str(e.get("acc")), str(e.get("neg_id")))
                                counts[k] = counts.get(k, 0) + 1
                except OSError:
                    pass
                self._chat_sends, self._chat_sends_day = counts, today
            k = (str(acc_short), str(neg_id))
            if add:
                self._chat_sends[k] = self._chat_sends.get(k, 0) + 1
            return self._chat_sends.get(k, 0)

    def _persist_llm_log(self, entry: dict):
        """Append-only JSONL write-through for LLM reply events (async via _schedule_save).
        Сериализуем через _llm_log_write_lock — иначе concurrent appends могут интерливить
        большие JSON-строки (>PIPE_BUF на Linux) и корраптить JSONL (kimi-search-1 #5).
        """
        if entry.get("send_ok") is True:
            self._chat_sends_today(entry.get("acc"), entry.get("neg_id"), add=True)
        def _write():
            try:
                line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
                with self._llm_log_write_lock:
                    with open(LLM_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(line)
            except Exception as e:
                log_debug(f"llm_log persist error: {e}")
        _schedule_save(_write)

    def _build_session_urls(self, resume_hash: str) -> list[str]:
        """Собрать URL конкретной сессии, не изменяя глобальный конфиг.

        Этот метод вызывается при автоматическом восстановлении активных
        сессий во время старта. Поэтому он обязан быть read-only: resume URL
        является runtime URL аккаунта, а не пользовательской настройкой
        ``CONFIG.url_pool``.
        """
        default_resume_url = (
            f"{hh_base()}/search/vacancy?resume={resume_hash}"
            "&area=113&order_by=publication_time&items_on_page=20"
        )
        urls = []
        for item in CONFIG.url_pool:
            entry = _url_entry(item)
            url = entry["url"]
            if not url:
                continue
            _text, _area, filters = parse_search_url(url)
            url_resume = str(filters.get("resume") or "")
            # Берём настройки поиска именно выбранного резюме. URL другого
            # резюме нельзя подмешивать в эту сессию.
            if not url_resume or url_resume == str(resume_hash):
                urls.append(url)
        if not any(str(parse_search_url(url)[2].get("resume") or "") == str(resume_hash)
                   for url in urls):
            urls.insert(0, default_resume_url)
        return urls

    def activate_session(self, temp_idx: int, *, resume_manual: bool = True) -> bool:
        """Запустить браузерную сессию как полноценный бот-аккаунт."""
        with self._activate_lock:
            if temp_idx < 0 or temp_idx >= len(self.temp_sessions):
                return False
            ts = self.temp_sessions[temp_idx]
            self._retiring_sessions[:] = [
                (session, old) for session, old in self._retiring_sessions
                if any(t.is_alive() for t in getattr(old, '_workers', []))
            ]
            if any(session is ts for session, old in self._retiring_sessions):
                return False
            if not ts.get("resume_hash"):
                return False
            if temp_idx in self.temp_states:
                if resume_manual:
                    state = self.temp_states[temp_idx]
                    with state._state_lock:
                        self._resume_manual(state)
                    self._persist_pauses()
                return True  # уже запущен
            # Отфильтровываем сохранённые URL от других резюме — юзер мог
            # сменить resume_hash сессии, а ts["urls"] содержит `resume=<старый_hash>`.
            # Без фильтра mobile-collect соберёт вакансии по чужому фильтру,
            # а отклики пойдут с текущего resume → шумовые отклики (audit #2).
            _rh = str(ts["resume_hash"])
            saved_urls = []
            for item in (ts.get("urls") or []):
                url = _url_entry(item)["url"]
                if not url:
                    continue
                try:
                    _text, _area, _flt = parse_search_url(url)
                    url_rh = str(_flt.get("resume") or "")
                except Exception:
                    url_rh = ""
                if not url_rh or url_rh == _rh:
                    saved_urls.append(url)
            acc = {
                "name": ts["name"],
                "short": ts.get("short", ts["name"]),
                "color": "yellow",
                "resume_hash": ts["resume_hash"],
                "letter": ts.get("letter", ""),
                "cookies": ts.get("cookies", {}),
                # Настройки конкретного аккаунта имеют приоритет. Если их нет,
                # используем URL из глобального пула для выбранного resume.
                "urls": saved_urls or self._build_session_urls(ts["resume_hash"]),
                "url_pages": dict(ts.get("url_pages") or {}),
                # Подтягиваем persistent флаги из temp_sessions — без этого
                # после restart browser-сессии теряли use_oauth/apply_tests (swarm-12 #9).
                "use_oauth": bool(ts.get("use_oauth", False)),
                "apply_tests": bool(ts.get("apply_tests", False)),
                "safety_enabled": bool(ts.get("safety_enabled", CONFIG.skip_inconsistent)),
                "mode": ts.get("mode", "web"),
                "user_id": ts.get("user_id"),
                "paused": ts.get("paused", False),
                "paused_reason": ts.get("paused_reason", ""),
                "hard_stopped": ts.get("hard_stopped", False),
                "limit_exceeded": ts.get("limit_exceeded", False),
                "pending_apply": ts.get("pending_apply"),
                "pending_applies": ts.get("pending_applies"),
                "network_recovery": ts.get("network_recovery"),
                "all_resumes": ts.get("all_resumes", []),
                # Persisted, or every restart would present the token from a new random phone.
                "device_identity": ts.setdefault("device_identity", login_device_identity()),
                "last_captcha_at": ts.get("last_captcha_at", 0.0),
                "pause_date": ts.get("pause_date"),
            }
            state = AccountState(acc)
            if resume_manual:
                self._resume_manual(state)
            self._bind_mutation_guard(state)
            self.temp_states[temp_idx] = state
            ts["bot_active"] = True
            ts["paused"] = state.paused
            ts["paused_reason"] = state.paused_reason
        save_browser_sessions(self.temp_sessions)
        log_debug(f"activate_session({temp_idx}): starting threads...")
        t1 = threading.Thread(target=self._run_account_worker, args=(900 + temp_idx, state), daemon=True, name=f"worker-{temp_idx}")
        t2 = threading.Thread(target=self._fetch_hh_stats_worker, args=(900 + temp_idx, state), daemon=True, name=f"stats-{temp_idx}")
        # Store handles + attach на state — stop()/deactivate join'ит их (round-1 #6/#19).
        # Round-2 #4: чистим is_alive() перед extend, чтобы список dead thread'ов
        # не рос навсегда.
        # Round-3 #7: read-modify-write под _activate_lock — иначе два
        # параллельных activate могли перезаписать список друг друга.
        state._workers = [t1, t2]
        with self._activate_lock:
            if state._deleted:
                return False
            t1.start()
            t2.start()
            if not hasattr(self, "_temp_workers"):
                self._temp_workers = []
            self._temp_workers[:] = [t for t in self._temp_workers if t.is_alive()]
            self._temp_workers.extend([t1, t2])
        try:
            with self._activate_lock:
                if not state._deleted:
                    self._start_ws_push(state)
        except Exception as e:
            log_debug(f"_start_ws_push temp({temp_idx}): {e}")
        log_debug(f"activate_session({temp_idx}): threads started t1={t1.is_alive()} t2={t2.is_alive()}")
        self._add_log(state.short, "yellow", f"\U0001f310 Сессия {ts['name']} запущена как бот", "success")
        return True

    def deactivate_session(self, temp_idx: int) -> bool:
        """Остановить браузерную сессию: сигналим воркерам выйти, удаляем state,
        сохраняем сессию на диск с bot_active=False. Кнопка «Стоп» в карточке.
        Сами cookies / resume / letter не трогаем — юзер может позже жмёт «▶ Запустить».
        """
        with self._activate_lock:
            if temp_idx < 0 or temp_idx >= len(self.temp_sessions):
                return False
            ts = self.temp_sessions[temp_idx]
            state = self.temp_states.pop(temp_idx, None)
            if state is not None:
                self._retiring_sessions.append((ts, state))
                # Сигналим воркерам: проверки `state._deleted` в каждом цикле
                # и в pause-loop приведут к graceful exit потоков.
                state._deleted = True
                state.paused = True
                if not getattr(state, "paused_reason", ""):
                    state.paused_reason = 'manual'
                ts.update({k: getattr(state, k) for k in (
                    "paused_reason", "hard_stopped", "limit_exceeded", "pending_apply", "pending_applies", "network_recovery") if hasattr(state, k)})
            ts["bot_active"] = False
            ts["paused"] = True
            if not ts.get("paused_reason"):
                ts["paused_reason"] = "manual"
        # Аудит 2026-08-17 #19: раньше deactivate возвращался мгновенно, а
        # rapid activate → deactivate → activate успевало создать вторую
        # (перекрывающуюся) пару worker'ов для того же HH-аккаунта. Join'им
        # старых, чтобы reactivate шёл на чистом slot'е. Join вне _activate_lock
        # т.к. worker сам берёт lock через save_browser_sessions/etc.
        if state is not None:
            ws = getattr(state, '_ws_client', None)
            if ws is not None:
                ws.stop()
            for t in getattr(state, "_workers", []):
                try:
                    t.join(timeout=5)
                except Exception:
                    pass
        save_browser_sessions(self.temp_sessions)
        log_debug(f"deactivate_session({temp_idx}): bot_active=False")
        if state is not None:
            self._add_log(state.short, "yellow", f"🛑 Сессия {ts.get('name','?')} остановлена", "warning")
        return True

    def _get_apply_acc(self, idx: int) -> dict | None:
        """Вернуть acc dict для apply-эндпоинтов (обычный или временный аккаунт)"""
        state = self._get_apply_state(idx)
        if state is not None:
            self._bind_mutation_guard(state)
            return dict(state.acc)
        if 0 <= idx < len(self.account_states):
            return dict(self.account_states[idx].acc)
        temp_idx = idx - len(self.account_states)
        if 0 <= temp_idx < len(self.temp_sessions):
            acc = dict(self.temp_sessions[temp_idx])
            session = self.temp_sessions[temp_idx]
            acc["_mutation_guard"] = lambda: (
                any(item is session for item in self.temp_sessions)
                and not session.get("paused", False)
                and not self.paused and not self._stop_event.is_set())
            return acc
        return None

    def _get_apply_state(self, idx: int):
        """Вернуть AccountState или None для temp-сессий"""
        if 0 <= idx < len(self.account_states):
            return self.account_states[idx]
        return getattr(self, "temp_states", {}).get(idx - len(self.account_states))

    def _start_ws_push(self, state) -> None:
        """Подписать аккаунт на chatik WS push.
        На chat_message_create — дёргаем _process_llm_replies в фоне (с debounce).
        Защита от спама: не чаще раз в 10с на аккаунт (HH может прислать пачку событий).
        """
        if not getattr(CONFIG, "llm_ws_push_enabled", True):
            return
        if getattr(state, "_ws_client", None) and state._ws_client.alive:
            return
        _last_trigger = [0.0]  # mutable nonlocal для closure
        _self = self

        def _on_event(event_name: str, payload: dict) -> None:
            if state._deleted or _self._stop_event.is_set():
                return
            if event_name == "chat_message_create":
                _self._start_telegram_message_scan(state)
                import time as _t
                now = _t.time()
                if now - _last_trigger[0] < 10:
                    return
                _last_trigger[0] = now
                # HH-limit пауза НЕ распространяется на чат-ответы, только на
                # новые отклики. Стопаем только manual/auth, остальное пропускаем.
                _is_blocking_pause = _self.paused or (state.paused and state.paused_reason in ("manual", "auth"))
                if not CONFIG.llm_enabled or not state.llm_enabled or _is_blocking_pause:
                    return
                log_debug(f"WS push [{state.short}] {event_name} → триггерим LLM")
                threading.Thread(
                    target=_self._process_llm_replies, args=(state,),
                    daemon=True, name=f"ws-llm-{state.short}",
                ).start()
            elif event_name == "chat_message_edited":
                _handle_edited_event(state, payload)
            elif event_name == "last_viewed_message_change":
                # HR прочитал наше сообщение — засветим в лог для UI-нотификации.
                chat_id = str(payload.get("chatId") or payload.get("chat_id") or "")
                if chat_id:
                    _self._add_log(state.short, state.color,
                        f"\U0001f441 HR прочитал ({chat_id})", "info", neg_id=chat_id)
            elif event_name in ("chat_state_changed", "chat_message_deleted", "chat_participant_action"):
                log_debug(f"WS push [{state.short}] {event_name}: {str(payload)[:200]}")
        state._ws_client = ChatikWSClient(state.acc, _on_event, label=state.short)
        state._ws_client.start()

    def on_realtime_event(self, acc: dict, event) -> None:
        """Realtime-событие websocket.hh.ru (Phase 1, mobile push-канал).

        Вызывается из WS-треда ws_manager. Не должен кидать/блокировать.
        Активен только при CONFIG.use_websocket_realtime (иначе no-op)."""
        try:
            if not getattr(CONFIG, "use_websocket_realtime", False):
                return
            state = next((st for st in list(self.account_states) + list(self.temp_states.values())
                          if st.acc is acc), None)
            if state is None:
                return
            etype = getattr(event, "type", "") or ""
            if etype == "chat_message_create":
                self._start_telegram_message_scan(state)
                import time as _t
                now = _t.time()
                if now - getattr(state, "_ws_realtime_last_trigger", 0.0) < 10:
                    return  # debounce: HH может прислать пачку событий
                state._ws_realtime_last_trigger = now
                _is_blocking_pause = self.paused or (state.paused and state.paused_reason in ("manual", "auth"))
                if not CONFIG.llm_enabled or not state.llm_enabled or _is_blocking_pause:
                    return
                log_debug(f"WS realtime [{state.short}] {etype} → триггерим LLM")
                self._add_log(state.short, state.color, "\U0001f4ac Новое сообщение HR (WS realtime)", "info")
                threading.Thread(
                    target=self._process_llm_replies, args=(state,),
                    daemon=True, name=f"ws-realtime-llm-{state.short}",
                ).start()
            elif etype == "chat_message_edited":
                payload = getattr(event, "event_data", {}) or {}
                # _handle_edited_event читает только chatId/chat_id, но push-канал
                # может нести id чата в другом ключе (ws_events нормализует его в
                # event.chat_id). Докинем chatId, иначе сброс устаревших черновиков
                # молча пропустится и LLM ответит на отредактированный текст старым.
                if getattr(event, "chat_id", None) and not payload.get("chatId") and not payload.get("chat_id"):
                    payload = {**payload, "chatId": event.chat_id}
                _handle_edited_event(state, payload)
            elif etype == "last_viewed_message_change":
                chat_id = str((getattr(event, "event_data", {}) or {}).get("chatId") or getattr(event, "chat_id", "") or "")
                if chat_id:
                    self._add_log(state.short, state.color, f"\U0001f441 HR прочитал (WS, {chat_id})", "info", neg_id=chat_id)
            else:
                log_debug(f"WS realtime [{state.short}] {etype}")
        except Exception as e:
            log_debug(f"on_realtime_event error: {e}")

    def _start_telegram_message_scan(self, state: AccountState) -> None:
        """Schedule a read-only chat scan without blocking a polling/WS worker."""
        if not telegram_is_configured() or state._deleted or self._stop_event.is_set():
            return
        if not state._telegram_notify_lock.acquire(blocking=False):
            return
        worker = threading.Thread(
            target=self._notify_employer_messages,
            args=(state, True),
            daemon=True,
            name=f"telegram-chat-{state.short}",
        )
        try:
            worker.start()
        except Exception:
            state._telegram_notify_lock.release()
            raise

    def _notify_employer_messages(self, state: AccountState, lock_held: bool = False) -> None:
        """Alert about unread employer messages; this never writes to HH."""
        if not telegram_is_configured():
            if lock_held:
                state._telegram_notify_lock.release()
            return
        acquired = lock_held or state._telegram_notify_lock.acquire(blocking=False)
        if not acquired:
            return
        try:
            items_by_id, display_info, cur_pid = get_client(state.acc).fetch_chat_list(max_pages=3)
            for neg_id, item in items_by_id.items():
                if item.get("type") != "NEGOTIATION":
                    continue
                thread = _build_thread_from_chat_item(item, display_info, cur_pid, str(neg_id))
                last = item.get("last_msg") or (item.get("messages") or {}).get("last") or item.get("lastMessage") or {}
                workflow = last.get("workflow_transition") or last.get("workflowTransition")
                workflow_unread = (workflow and item.get("unreadCount", 0) > 0
                                   and str(last.get("participant_id", last.get("participantId", ""))) != str(cur_pid))
                if not thread.get("needs_reply") and not workflow_unread:
                    continue
                participant = last.get("participant_display") or last.get("participantDisplay") or {}
                is_bot = last.get("is_bot", participant.get("is_bot", participant.get("isBot", False)))
                is_bot = is_bot or str(last.get("participant_id", last.get("participantId", ""))).endswith("-BOT")
                category, key, text = classify_chat_message(
                    neg_id, thread.get("last_employer_msg") or last.get("body") or last.get("text", ""), workflow, is_bot,
                    [{"msg_id": thread.get("last_msg_id")}],
                )
                if category:
                    from app.telegram_alerts import build_alert_html
                    html_text = build_alert_html(
                        category, acc_short=state.short,
                        employer=thread.get('employer_name'),
                        vacancy_title=thread.get('vacancy_title'),
                        vacancy_id=str(thread.get('vacancy_id') or ''),
                        neg_id=neg_id,
                        body=thread.get('last_employer_msg') or last.get('body') or last.get('text', ''),
                    )
                    from app.telegram_alerts import chat_buttons
                    send_alert(category, scope_key(account_key(state), key), html_text,
                               sender=telegram_send_once, parse_mode='HTML',
                               reply_markup=chat_buttons(state.acc, neg_id))

        except Exception as exc:
            log_debug(f"telegram message scan [{state.short}] failed: {type(exc).__name__}: {exc}")
        finally:
            if acquired:
                state._telegram_notify_lock.release()

    def _notify_new_interviews(self, state: AccountState, interviews: list) -> None:
        """Alert once for every interview negotiation found during stats refresh."""
        if not telegram_is_configured():
            return
        from app.telegram_alerts import build_alert_html
        for item in interviews:
            neg_id = str(item.get("neg_id", "")).strip()
            if not neg_id:
                continue
            extra = []
            if item.get('date'):
                extra.append(f"Дата в HH: {item.get('date')}")
            html_text = build_alert_html(
                AlertCategory.interview_invitation, acc_short=state.short,
                vacancy_title=item.get('text'),
                vacancy_id=str(item.get('vacancy_id') or ''),
                neg_id=neg_id, extra_lines=extra,
            )
            from app.telegram_alerts import chat_buttons
            send_alert(AlertCategory.interview_invitation,
                       scope_key(account_key(state), f"interview:{neg_id}"), html_text,
                       sender=telegram_send_once, parse_mode='HTML',
                       reply_markup=chat_buttons(state.acc, neg_id))

    def start(self):
        # Регистр всех worker-threads чтобы stop() мог их join'нуть — иначе
        # in-flight работа после SIGTERM продолжается, save_executor уже закрыт,
        # add_applied молча теряет запись (аудит 2026-08-17 #6 critical).
        self._workers: list = []
        _load_cache()
        load_config()
        self.paused = CONFIG.automation_paused
        # После load_config: если env HH_PROXY не задан, но в CONFIG.hh_proxy_url
        # что-то сохранено (пользователь выставлял через UI) — применить.
        # env всегда приоритет чтобы docker-compose override работал.
        try:
            import os as _os
            if not _os.environ.get("HH_PROXY", "").strip() and getattr(CONFIG, "hh_proxy_url", ""):
                from app.hh_http import set_proxy
                set_proxy(CONFIG.hh_proxy_url)
                log_debug(f"HH_PROXY из CONFIG.hh_proxy_url применён: {CONFIG.hh_proxy_url[:40]}")
        except Exception as _e:
            log_debug(f"applying stored proxy failed: {_e}")
        self._start_time = datetime.now()
        # Load recent responses from applied_vacancies into deque
        try:
            with _cache_lock:
                if _cache_applied:
                    all_items = []
                    for acc_name, vacancies in _cache_applied.items():
                        if isinstance(vacancies, dict):
                            for vid, info in vacancies.items():
                                if isinstance(info, dict):
                                    all_items.append({
                                        "id": vid, "title": info.get("title", ""),
                                        "company": info.get("company", ""),
                                        "time": (info.get("at", "") or "")[:16].replace("T", " "),
                                        "icon": "✅", "acc": acc_name,
                                    })
                    # Sort by time, take last 100
                    all_items.sort(key=lambda x: x.get("time", ""), reverse=True)
                    for item in all_items[:100]:
                        self.recent_responses.append(item)
                    log_debug(f"Loaded {len(self.recent_responses)} recent responses from cache")
        except Exception as e:
            log_debug(f"Failed to load recent responses: {e}")
        self.account_states = [AccountState(acc) for acc in accounts_data]
        for i, state in enumerate(self.account_states):
            self._bind_mutation_guard(state)
            t1 = threading.Thread(
                target=self._run_account_worker, args=(i, state), daemon=True
            )
            t2 = threading.Thread(
                target=self._fetch_hh_stats_worker, args=(i, state), daemon=True
            )
            t1.start()
            t2.start()
            self._workers.extend([t1, t2])
            try:
                self._start_ws_push(state)
            except Exception as e:
                log_debug(f"_start_ws_push({state.short}): {e}")
        # Phase 1: mobile WS-слушатель websocket.hh.ru (read-only push).
        # Стартуем только при явно включённом флаге — иначе поведение бота не меняется.
        if getattr(CONFIG, "use_websocket_realtime", False):
            try:
                from app.ws_manager import ws_manager
                ws_manager.auto_start_enabled()
            except Exception as e:
                log_debug(f"ws_manager auto_start error: {e}")
        # Proactive OAuth refresh — раз в 6 часов обновляет токены,
        # у которых TTL < 48ч, чтобы refresh_token не успел истечь когда
        # аккаунт долго на паузе (лимит HH, ручная пауза).
        _oauth_t = threading.Thread(
            target=self._oauth_refresh_worker, daemon=True,
            name="oauth_refresh",
        )
        _oauth_t.start()
        self._workers.append(_oauth_t)
        # Real HH-limit tracker — каждые 30 мин синхронизирует daily_sent с
        # фактическим числом откликов из HH и снимает hard_stopped если лимит
        # реально не достигнут (например HH сам сбросил счётчик).
        _limit_t = threading.Thread(
            target=self._hh_limit_tracker_worker, daemon=True,
            name="hh_limit_tracker",
        )
        _limit_t.start()
        self._workers.append(_limit_t)

        # Авто-активация браузерных сессий, которые были запущены до перезапуска
        log_debug(f"start(): {len(self.temp_sessions)} temp sessions to check")
        for i, ts in enumerate(self.temp_sessions):
            log_debug(f"start(): session {i}: bot_active={ts.get('bot_active')}, resume_hash={bool(ts.get('resume_hash'))}")
            if ts.get("bot_active") and ts.get("resume_hash"):
                try:
                    result = self.activate_session(i, resume_manual=False)
                    log_debug(f"start(): activate_session({i}) = {result}")
                except Exception as e:
                    log_debug(f"start(): activate_session({i}) ERROR: {e}")
        self._add_log("", "", "\U0001f680 Бот запущен", "success")

    def stop(self):
        self._stop_event.set()
        self._persist_pauses()
        # Останавливаем WS-клиенты у всех аккаунтов (regular + temp)
        for st in list(self.account_states) + list(self.temp_states.values()):
            ws = getattr(st, "_ws_client", None)
            if ws:
                try:
                    ws.stop()
                except Exception:
                    pass
        # Phase 1: глушим mobile WS-слушатель ws_manager (no-op если не стартовал).
        try:
            from app.ws_manager import ws_manager
            ws_manager.stop_all()
        except Exception:
            pass
        # Аудит round-1 #6: join всех worker'ов чтобы in-flight цикл добежал
        # до `if _stop_event: return` ДО того как save_executor выключится.
        # Round-2 #3: раньше join(timeout=15) на каждый = 300с для 10 accounts.
        # Используем ОБЩИЙ deadline, чтобы shutdown был ограничен сверху.
        import time as _time
        deadline = _time.monotonic() + 20  # весь shutdown уложить в ~20с
        for t in list(getattr(self, "_workers", [])) + list(getattr(self, "_temp_workers", [])):
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                break
            try:
                t.join(timeout=remaining)
            except Exception:
                pass

    def toggle_pause(self):
        self.paused = not self.paused
        self._activity_global_pause_revision = getattr(self, "_activity_global_pause_revision", 0) + 1
        self._activity_global_pause_started_at = aware_iso(datetime.now(timezone.utc)) if self.paused else None
        CONFIG.automation_paused = self.paused
        save_config()
        msg = "⏸️ Пауза" if self.paused else "▶️ Продолжение"
        level = "warning" if self.paused else "success"
        self._add_log("", "", msg, level)
        # Phase 1: глобальная пауза приостанавливает и mobile WS-слушатели.
        try:
            from app.ws_manager import ws_manager
            if self.paused:
                ws_manager.suspend()
            else:
                ws_manager.resume()
        except Exception:
            pass

    def toggle_account_pause(self, idx: int):
        state = None
        if 0 <= idx < len(self.account_states):
            state = self.account_states[idx]
        else:
            temp_idx = idx - len(self.account_states)
            state = self.temp_states.get(temp_idx)
        if not state:
            return
        with state._state_lock:
            if state.paused:
                resumed = self._resume_manual(state)
                if (not resumed and state.paused_reason == "auto_errors"
                        and not state.pending_applies and not state.hard_stopped
                        and (not state.limit_exceeded or getattr(state, "_limit_is_throttle", False))
                        and not state.cookies_expired):
                    state.paused = False
                    state.paused_reason = ""
                    state.consecutive_errors = 0
                    state.status = "idle"
                    state.status_detail = "Ожидание следующего цикла"
            else:
                state.paused = True
                state.paused_reason = "outcome_unknown" if state.pending_apply else "manual"
            if state.paused:
                state.status_detail = self._pause_detail(state)
        self._persist_pauses()
        msg = (
            f"⏸️ Аккаунт {state.short} приостановлен"
            if state.paused
            else f"▶️ Аккаунт {state.short} возобновлён"
        )
        self._add_log(state.short, state.color, msg, "warning" if state.paused else "success")
        # Phase 1: пауза regular-аккаунта приостанавливает его mobile WS-слушатель.
        # temp-сессии (browser) в ws_manager не обслуживаются — только regular idx.
        if 0 <= idx < len(self.account_states):
            try:
                from app.ws_manager import ws_manager
                if state.paused:
                    ws_manager.suspend_account(idx)
                else:
                    ws_manager.resume_account(idx)
            except Exception:
                pass

    def toggle_account_llm(self, idx: int):
        state = None
        if 0 <= idx < len(self.account_states):
            state = self.account_states[idx]
        else:
            temp_idx = idx - len(self.account_states)
            state = self.temp_states.get(temp_idx)
        if state:
            state.llm_enabled = not state.llm_enabled
            msg = (
                f"\U0001f916 LLM включён для {state.short}"
                if state.llm_enabled
                else f"\U0001f916 LLM выключен для {state.short}"
            )
            self._add_log(state.short, state.color, msg, "info")

    def toggle_account_oauth(self, idx: int):
        state = None
        if 0 <= idx < len(self.account_states):
            state = self.account_states[idx]
        else:
            temp_idx = idx - len(self.account_states)
            state = self.temp_states.get(temp_idx)
        if state:
            state.use_oauth = not state.use_oauth
            mode = "\U0001f511 OAuth" if state.use_oauth else "\U0001f310 Web"
            self._add_log(state.short, state.color, f"{mode} откликов для {state.short}", "info")
            # Persist to account data
            state.acc["use_oauth"] = state.use_oauth
            if 0 <= idx < len(accounts_data):
                accounts_data[idx]["use_oauth"] = state.use_oauth
                save_accounts()
            else:
                temp_idx = idx - len(self.account_states)
                if 0 <= temp_idx < len(self.temp_sessions):
                    self.temp_sessions[temp_idx]["use_oauth"] = state.use_oauth
                    save_browser_sessions(self.temp_sessions)

    def trigger_resume_touch(self, idx: int):
        if 0 <= idx < len(self.account_states):
            self.account_states[idx].next_resume_touch = datetime.now()
        else:
            temp_idx = idx - len(self.account_states)
            if temp_idx in self.temp_states:
                self.temp_states[temp_idx].next_resume_touch = datetime.now()

    def toggle_resume_touch(self, idx: int) -> bool:
        state = None
        if 0 <= idx < len(self.account_states):
            state = self.account_states[idx]
        else:
            temp_idx = idx - len(self.account_states)
            if temp_idx in self.temp_states:
                state = self.temp_states[temp_idx]
        if state:
            state.resume_touch_enabled = not state.resume_touch_enabled
            return state.resume_touch_enabled
        return False

    def _add_log(self, acc_short: str, acc_color: str, message: str, level: str = "info", neg_id: str = ""):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "acc": acc_short,
            "color": acc_color,
            "message": message,
            "level": level,
        }
        if neg_id:
            entry["neg_id"] = str(neg_id)
        with self._deque_lock:
            self.activity_log.appendleft(entry)

    def _add_acc_event(self, state: AccountState, icon: str, etype: str,
                        title: str, company: str, extra: str = ""):
        with state._deque_lock:
            state.acc_event_log.appendleft({
                "time": datetime.now().strftime("%H:%M"),
                "icon": icon,
                "type": etype,
                "title": title[:45],
                "company": company[:25],
                "extra": extra[:70],
            })

    def _push_action(self, state: AccountState, entry: str) -> None:
        """Thread-safe append в state.action_history под _deque_lock.
        Раньше writers делали bare append, snap builder читал `list(deque)` —
        при конкурентной мутации CPython бросает RuntimeError, broadcast_loop
        ловил, но дропал ВЕСЬ snapshot того тика → UI подвисал на 300ms.
        """
        with state._deque_lock:
            state.action_history.append(entry)

    def _push_llm_log(self, entry: dict) -> None:
        """Thread-safe appendleft в self.llm_log под _deque_lock.
        Аудит 2026-08-17 #23: раньше writers жали bare appendleft, snapshot
        builder читал list(llm_log) — та же гонка, что закрыта в _push_action.
        """
        with self._deque_lock:
            self.llm_log.appendleft(entry)

    @staticmethod
    def _snap_deque(dq, lock):
        """Snapshot deque под lock — снапшот-ридер не должен ронять весь
        snapshot тика из-за конкурентного append/appendleft (RuntimeError:
        deque mutated during iteration). Возвращает обычный list."""
        with lock:
            return list(dq)

    def _check_auto_pause(self, state: AccountState, *, network_reason=None):
        """Авто-пауза при превышении лимита ошибок подряд."""
        n = CONFIG.auto_pause_errors
        changed = False
        with state._state_lock:
            if network_reason is not None:
                if getattr(state, "_network_error_last_count", 0) != state.consecutive_errors - 1:
                    state._network_error_streak = 0
                state._network_error_streak = getattr(state, "_network_error_streak", 0) + 1
            else:
                state._network_error_streak = 0
            state._network_error_last_count = state.consecutive_errors
        if n > 0 and state.consecutive_errors >= n:
            with state._state_lock:
                # Не перетираем manual pause: если пользователь только что снял паузу,
                # `toggle_account_pause` обнулил `consecutive_errors`. Если он стоит на 0,
                # auto-pause не должен срабатывать заново.
                if state.consecutive_errors >= n and not state.paused:
                    state.paused = True
                    state.paused_reason = "auto_errors"
                    if (network_reason is not None
                            and state._network_error_streak == state.consecutive_errors
                            and str(state.acc.get("mode") or "").lower() == "oauth"
                            and not state.pending_apply and not state.pending_applies
                            and not state.cookies_expired and not state.hard_stopped and not state.limit_exceeded):
                        state.paused_reason = "network_error"
                        state.network_recovery = {"reason": network_reason, "attempts": 0,
                            "next_check_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
                            "last_started_at": None, "last_error": None,
                            "error_type": "oauth_bridge_network", "phase": "oauth_bridge", "dispatched": False,
                            "account_key": self._network_account_key(state.acc)}
                    state.status_detail = self._pause_detail(state)
                    changed = True
                    self._add_log(
                        state.short, state.color,
                        f"⛔ Сетевая пауза: {n} ошибок подготовки анкеты; соединение проверится без отправки отклика."
                        if state.paused_reason == "network_error" else f"⛔ Авто-пауза: {n} ошибок подряд. Снимите вручную.",
                        "error",
                    )
        if changed:
            self._persist_pauses()

    def _maybe_roll_daily_counter(self, state: AccountState) -> bool:
        today = _today_msk()
        with state._state_lock:
            if state.daily_date != today:
                state.daily_sent = 0
                state.daily_date = today
                state.hard_stopped = False
                # Сбрасываем и limit-флаги: иначе после rollover остаёмся в limit-check
                # block с уже обнулённым счётчиком (kimi-search-1 #9).
                state.limit_exceeded = False
                state.limit_reset_time = None
                # A new day resets limits, not unknown outcomes or connectivity
                # failures. Those require reconciliation / explicit retry.
                if state.paused and state.paused_reason == "limit" and not state.pending_apply:
                    if captcha_active(state.acc):
                        # A captcha that arrived during the limit stop outlives midnight.
                        state.paused_reason = "challenge"
                    else:
                        state.paused = False
                        state.paused_reason = ""
                    # Также сбрасываем счётчик ошибок — иначе следующая ошибка
                    # сразу re-pause'нет аккаунт (consistency с toggle_account_pause).
                    state.consecutive_errors = 0
                return True
        return False

    def _limit_check_guard(self, state):
        """Capture only control state, never credentials or mutable HTTP data."""
        return (state.paused, state.paused_reason, state.hard_stopped,
                state.limit_exceeded, state._deleted, bool(state.pending_apply),
                getattr(state, "_activity_control_revision", 0), self.paused,
                getattr(self, "_activity_global_pause_revision", 0), self._stop_event.is_set())

    def _clear_checked_limit(self, state, before):
        """A completed read must not undo a newer user/protective stop."""
        with state._state_lock:
            if (self._limit_check_guard(state) != before or state._deleted
                    or state.pending_apply or self.paused or self._stop_event.is_set()
                    or (state.paused and state.paused_reason != "limit")):
                return False
            state.limit_exceeded = False
            state.limit_reset_time = None
            state.paused = False
            state.hard_stopped = False
            state.status_detail = ""
            return True

    def _add_response(
        self,
        state: AccountState,
        vid: str,
        title: str,
        company: str,
        result: str,
        salary: str = "",
    ):
        result_icons = {
            "sent": "✅",
            "test": "\U0001f9ea",
            "already": "\U0001f504",
            "limit": "\U0001f6ab",
            "error": "❌",
            "unknown": "❔",
        }
        # HR online/offline + chat status вытаскиваем из vacancy_meta —
        # фронт показывает их в карточке отклика без extra-fetch'ей.
        _vm = state.vacancy_meta.get(vid, {}) if hasattr(state, "vacancy_meta") else {}
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "acc": state.short,
            "color": state.color,
            "id": vid,
            "title": title,
            "company": company,
            "salary": salary,
            "result": result,
            "icon": result_icons.get(result, "❓"),
            "hr_online": _vm.get("hr_online", ""),
            "chat_write": _vm.get("chat_write_possibility", ""),
            "accept_auto": _vm.get("accept_auto_response"),
            "employer_rating": _vm.get("employer_rating") or None,
            "manager_activity": _vm.get("manager_activity") or {},
            "skills_match_percent": _vm.get("skills_match_percent"),
            "relations": _vm.get("relations") or [],
            "first_observed_at": _vm.get("first_observed_at"),
            "publication_updated": _vm.get("publication_updated", False),
            "observation_unavailable": _vm.get("observation_unavailable", False),
        }
        # Держим _deque_lock т.к. snap builder читает `list(self.recent_responses)`
        # без lock'а в другом потоке — иначе CPython RuntimeError и дроп тика.
        with self._deque_lock:
            self.recent_responses.appendleft(entry)

    def _telegram_captcha_pending(self, acc):
        coordinator = getattr(self, 'telegram_captcha_coordinator', None)
        if coordinator is None:
            return False
        keys = (str(acc.get('user_id', '')), str(acc.get('resume_hash', '')))
        return any(not item.get('automatic') and item['acc_key'] in keys and item['captcha_key']
                   for item in list(coordinator.pending.values()))

    def _captcha_llm_status(self, acc):
        """What the LLM did with this account's pending captcha (for the card)."""
        coordinator = getattr(self, 'telegram_captcha_coordinator', None)
        if coordinator is None:
            return None
        keys = (str(acc.get('user_id', '')), str(acc.get('resume_hash', '')))
        return next((dict(item['llm_result']) for item in list(coordinator.pending.values())
                     if item.get('acc_key') in keys and item.get('llm_result')), None)

    _LLM_RESUME_TTL = 3600

    def _resume_for_llm(self, state) -> tuple[str, bool]:
        """Plain-text resume for the LLM prompt, cached per resume; errors never fail the chat."""
        rh = str(state.acc.get("resume_hash") or "")
        cache = self.__dict__.setdefault("_llm_resume_cache", {})
        hit = cache.get(rh)
        if hit and time.time() - hit[1] < self._LLM_RESUME_TTL:
            return hit[0], True
        try:
            raw = get_client(state.acc).fetch_resume()
        except Exception as e:
            log_debug(f"LLM resume fetch [{state.short}]: {type(e).__name__}")
            return (hit[0], True) if hit else ("", False)
        text = _resume_plain_text(raw)
        if text:
            cache[rh] = (text, time.time())
        return text, False

    # Pauses with no automatic exit; the plain pause toggle deliberately cannot lift them.
    HUMAN_CONFIRMABLE_PAUSES = ("hh_rate_limit", "message_outcome_unknown", "challenge")

    def confirm_protective_resume(self, idx: int, reason: str) -> tuple[bool, str]:
        """Explicit 'I checked HH myself' for pauses that have no verified exit path."""
        state = self._get_apply_state(idx)
        if state is None:
            return False, "Аккаунт не найден"
        with state._state_lock:
            if not state.paused or state.paused_reason != reason or reason not in self.HUMAN_CONFIRMABLE_PAUSES:
                return False, "Состояние аккаунта изменилось. Обновите страницу."
            if reason == "challenge" and captcha_active(state.acc):
                return False, "Есть активная проверка HH — пройдите её в блоке капчи."
            if (state.pending_apply or state.pending_applies or state.hard_stopped or state.cookies_expired
                    or (state.limit_exceeded and not getattr(state, "_limit_is_throttle", False))
                    or getattr(state, "_auth_recovery_pending", False) or state._deleted):
                return False, "Действует другая защитная пауза — она не снимается этим подтверждением."
            state.paused = False
            state.paused_reason = ""
            state.consecutive_errors = 0
            state.status = "idle"
            state.status_detail = "Продолжено после ручной проверки"
        self._persist_pauses(wait=True)
        event = getattr(state, "_captcha_wake", None)
        if event is not None:
            event.set()
        self._add_log(state.short, state.color, f"▶️ Продолжено после ручной проверки ({reason})", "success")
        return True, "Продолжено. Если HH снова ограничит запросы, отправки остановятся."

    def resume_challenge_account(self, user_id: str):
        """Resume resolved challenges while preserving other protective pauses."""
        from app import captcha
        for state in list(self.account_states) + list(self.temp_states.values()):
            if str(user_id) not in (str(state.acc.get('user_id', '')), str(state.acc.get('resume_hash', ''))):
                continue
            with state._state_lock:
                if (state._deleted or state.paused_reason != 'challenge'
                        or captcha.active(state.acc) or state.pending_apply or state.pending_applies
                        or state.hard_stopped or state.limit_exceeded or state.cookies_expired
                        or getattr(state, '_auth_recovery_pending', False)):
                    continue
                state.paused = False
                state.paused_reason = None
                state.consecutive_errors = 0
                # Legacy/recovered challenges may predate the timestamp hook.
                if not (getattr(state, '_last_captcha_at', 0) or state.acc.get('_last_captcha_at')):
                    state._last_captcha_at = time.time()
                    state.acc['_last_captcha_at'] = state._last_captcha_at
                event = getattr(state, '_captcha_wake', None)
                if event is not None:
                    event.set()
        self._persist_pauses(wait=True)

    def get_state_snapshot(self) -> dict:
        """Full JSON snapshot for WS broadcast"""
        now = datetime.now()
        uptime = int((now - self._start_time).total_seconds()) if self._start_time else 0

        # All states: regular + temp sessions (for global_stats, vacancy_queues)
        all_states = list(self.account_states) + list(self.temp_states.values())

        accounts = []
        for i, s in enumerate(self.account_states):
            next_touch_str = ""
            if s.next_resume_touch:
                rem = (s.next_resume_touch - now).total_seconds()
                if rem > 0:
                    h = int(rem // 3600)
                    m = int((rem % 3600) // 60)
                    next_touch_str = f"{s.next_resume_touch.strftime('%H:%M')} ({h}ч{m}м)"
                else:
                    next_touch_str = "сейчас!"

            hh_updated_str = ""
            if s.hh_stats_updated:
                ago = int((now - s.hh_stats_updated).total_seconds() / 60)
                hh_updated_str = (
                    f"{ago}м назад" if ago < 60 else f"{ago // 60}ч{ago % 60}м назад"
                )

            with s._state_lock:
                _status = s.status
                _status_detail = s.status_detail
                if s.paused and s.paused_reason not in ("limit", ""):
                    _status_detail = self._pause_detail(s)
                _hh_interviews = s.hh_interviews
                _hh_interviews_recent = s.hh_interviews_recent
                _hh_viewed = s.hh_viewed
                _hh_discards = s.hh_discards
                _hh_not_viewed = s.hh_not_viewed
                _hh_unread_by_employer = s.hh_unread_by_employer
                _hh_interviews_list = s.hh_interviews_list[:20]
                _current_vacancy_idx = s.current_vacancy_idx
                _total_vacancies = s.total_vacancies

            with _cache_lock:
                _total_applied = len((_cache_applied or {}).get(s.name, {}))

            accounts.append({
                "idx": i,
                "name": s.name,
                "short": s.short,
                "resume_hash": s.acc.get("resume_hash", ""),
                "telegram_captcha_pending": self._telegram_captcha_pending(s.acc),
                "captcha_record": captcha_active(s.acc),
                "captcha_llm": self._captcha_llm_status(s.acc),
                "all_resumes": s.acc.get("all_resumes", []),
                "color": s.color,
                "status": _status,
                "status_detail": _status_detail,
                "sent": s.sent,
                "total_applied": _total_applied,
                "tests": s.tests,
                "errors": s.errors,
                "already_applied": s.already_applied,
                "found_vacancies": s.found_vacancies,
                "current_vacancy_title": s.current_vacancy_title,
                "current_vacancy_company": s.current_vacancy_company,
                "current_vacancy_signals": _current_vacancy_signals(s),
                "current_vacancy_idx": _current_vacancy_idx,
                "total_vacancies": _total_vacancies,
                "salary_skipped": s.salary_skipped,
                "questionnaire_sent": s.questionnaire_sent,
                "limit_exceeded": s.limit_exceeded,
                "paused": s.paused,
                "next_resume_touch": next_touch_str,
                "resume_touch_status": s.resume_touch_status,
                "resume_touch_enabled": s.resume_touch_enabled,
                "letter": s.acc.get("letter", ""),
                "urls": s.acc.get("urls", []),
                "url_pages": s.acc.get("url_pages", {}),
                "hh_interviews": _hh_interviews,
                "hh_interviews_recent": _hh_interviews_recent,
                "hh_viewed": _hh_viewed,
                "hh_discards": _hh_discards,
                "hh_not_viewed": _hh_not_viewed,
                "hh_unread_by_employer": _hh_unread_by_employer,
                "hh_stats_updated": hh_updated_str,
                "hh_stats_loading": s.hh_stats_loading,
                "hh_interviews_list": _hh_interviews_list,
                "hh_possible_offers": s.hh_possible_offers[:10],
                "action_history": self._snap_deque(s.action_history, s._deque_lock),
                "resume_views_7d": s.resume_views_7d,
                "resume_views_new": s.resume_views_new,
                "resume_shows_7d": s.resume_shows_7d,
                "resume_invitations_7d": s.resume_invitations_7d,
                "resume_invitations_new": s.resume_invitations_new,
                "resume_next_touch_seconds": s.resume_next_touch_seconds,
                "resume_free_touches": s.resume_free_touches,
                "resume_global_invitations": s.resume_global_invitations,
                "resume_new_invitations_total": s.resume_new_invitations_total,
                "acc_event_log": self._snap_deque(s.acc_event_log, s._deque_lock),
                "apply_tests": s.apply_tests,
                "safety_enabled": s.safety_enabled,
                "safety_inconsistent_skipped": s.safety_inconsistent_skipped,
                "safety_misleading_skipped": s.safety_misleading_skipped,
                "safety_redirect_skipped": s.safety_redirect_skipped,
                "safety_last_reason": s.safety_last_reason,
                "consecutive_errors": s.consecutive_errors,
                "url_stats": dict(s.url_stats),
                "cookies_expired": s.cookies_expired,
                "degraded_mode": s.degraded_mode,
                "degraded_skipped": s.degraded_skipped,
                "mode": str(s.acc.get("mode", "") or "").strip().lower(),
                "degraded_fallback_enabled": s.degraded_fallback_enabled,
                "resume_status_oauth": dict(s.resume_status or {}),
                "hh_today_applies": s.hh_today_applies,
                "hh_today_applies_updated": s.hh_today_applies_updated,
                "hh_daily_limit": CONFIG.hh_daily_limit or 200,
                "responses_streak_count": getattr(s, "responses_streak_count", 0),
                "responses_streak_required": getattr(s, "responses_streak_required", 0),
                "oauth_status": get_oauth_status(s.acc.get("resume_hash", "")),
                "llm_enabled": s.llm_enabled,
                "llm_status": s.llm_status,
                "llm_replied_count": s.llm_replied_count,
                "llm_pending_chats": s.llm_pending_chats,
                "llm_current_neg_id": getattr(s, "llm_current_neg_id", ""),
                "llm_current_employer": getattr(s, "llm_current_employer", ""),
                "llm_current_idx": getattr(s, "llm_current_idx", 0),
                "llm_current_total": getattr(s, "llm_current_total", 0),
                "llm_last_check_at": getattr(s, "llm_last_check_at", ""),
                "llm_next_check_at": getattr(s, "llm_next_check_at", ""),
                "use_oauth": s.use_oauth,
                "daily_sent": s.daily_sent,
                "daily_limit": CONFIG.daily_apply_limit,
                "hard_stopped": s.hard_stopped,
                "last_apply_at": s.last_apply_at,
                "last_apply_attempt_at": s.last_apply_attempt_at,
                "paused_reason": s.paused_reason,
                "network_recovery": self.network_recovery_view(s),
                "cycle_report": cycle_snapshot(s, blocked=s.paused or self.paused or s._deleted
                    or getattr(self, "_stop_event", threading.Event()).is_set()),
                "activity": activity_view(s, global_paused=self.paused,
                    stopped=getattr(self, "_stop_event", threading.Event()).is_set(),
                    global_started_at=getattr(self, "_activity_global_pause_started_at", None)),
                "pending_apply": dict(s.pending_apply) if s.pending_apply else None,
                "pending_applies": [dict(item) for item in s.pending_applies],
            })

        # Temp browser sessions — append after regular accounts
        base_idx = len(self.account_states)
        for i, ts in enumerate(self.temp_sessions):
            idx = base_idx + i
            state = self.temp_states.get(i)
            if state:
                # Активная сессия — реальные данные из AccountState
                s = state
                nrt = s.next_resume_touch.strftime("%H:%M") if s.next_resume_touch else ""
                ts_hh_updated_str = ""
                if s.hh_stats_updated:
                    ago = int((now - s.hh_stats_updated).total_seconds() / 60)
                    ts_hh_updated_str = (
                        f"{ago}м назад" if ago < 60 else f"{ago // 60}ч{ago % 60}м назад"
                    )
                with s._state_lock:
                    _status = s.status
                    _status_detail = s.status_detail
                    if s.paused and s.paused_reason not in ("limit", ""):
                        _status_detail = self._pause_detail(s)
                    _hh_interviews = s.hh_interviews
                    _hh_interviews_recent = s.hh_interviews_recent
                    _hh_viewed = s.hh_viewed
                    _hh_discards = s.hh_discards
                    _hh_not_viewed = s.hh_not_viewed
                    _hh_unread_by_employer = s.hh_unread_by_employer
                    _hh_interviews_list = s.hh_interviews_list[:20]
                    _current_vacancy_idx = s.current_vacancy_idx
                    _total_vacancies = s.total_vacancies

                with _cache_lock:
                    _total_applied = len((_cache_applied or {}).get(s.acc["name"], {}))

                accounts.append({
                    "idx": idx,
                    "name": s.acc["name"],
                    "short": s.acc.get("short", ""),
                    "color": "yellow",
                    "temp": True,
                    "bot_active": True,
                    "resume_hash": s.acc.get("resume_hash", ""),
                    "telegram_captcha_pending": self._telegram_captcha_pending(s.acc),
                    "captcha_record": captcha_active(s.acc),
                "captcha_llm": self._captcha_llm_status(s.acc),
                    "all_resumes": ts.get("all_resumes", []),
                    "letter": s.acc.get("letter", ""),
                    "urls": s.acc.get("urls", []),
                    "url_pages": s.acc.get("url_pages", {}),
                    "status": _status,
                    "status_detail": _status_detail,
                    "sent": s.sent,
                    "total_applied": _total_applied,
                    "tests": s.tests,
                    "errors": s.errors,
                    "already_applied": s.already_applied,
                    "found_vacancies": s.found_vacancies,
                    "current_vacancy_title": s.current_vacancy_title,
                    "current_vacancy_company": s.current_vacancy_company,
                    "current_vacancy_signals": _current_vacancy_signals(s),
                    "current_vacancy_idx": _current_vacancy_idx,
                    "total_vacancies": _total_vacancies,
                    "salary_skipped": s.salary_skipped,
                    "questionnaire_sent": s.questionnaire_sent,
                    "limit_exceeded": s.limit_exceeded,
                    "paused": s.paused,
                    "next_resume_touch": nrt,
                    "resume_touch_status": s.resume_touch_status,
                    "resume_touch_enabled": s.resume_touch_enabled,
                    "hh_interviews": _hh_interviews,
                    "hh_interviews_recent": _hh_interviews_recent,
                    "hh_viewed": _hh_viewed,
                    "hh_discards": _hh_discards,
                    "hh_not_viewed": _hh_not_viewed,
                    "hh_unread_by_employer": _hh_unread_by_employer,
                    "hh_stats_updated": ts_hh_updated_str,
                    "hh_stats_loading": s.hh_stats_loading,
                    "hh_interviews_list": _hh_interviews_list,
                    "hh_possible_offers": s.hh_possible_offers[:10],
                    "action_history": self._snap_deque(s.action_history, s._deque_lock),
                    "resume_views_7d": s.resume_views_7d,
                    "resume_views_new": s.resume_views_new,
                    "resume_shows_7d": s.resume_shows_7d,
                    "resume_invitations_7d": s.resume_invitations_7d,
                    "resume_invitations_new": s.resume_invitations_new,
                    "resume_next_touch_seconds": s.resume_next_touch_seconds,
                    "resume_free_touches": s.resume_free_touches,
                    "resume_global_invitations": s.resume_global_invitations,
                    "resume_new_invitations_total": s.resume_new_invitations_total,
                    "acc_event_log": self._snap_deque(s.acc_event_log, s._deque_lock),
                    "apply_tests": s.apply_tests,
                    "safety_enabled": s.safety_enabled,
                    "safety_inconsistent_skipped": s.safety_inconsistent_skipped,
                    "safety_misleading_skipped": s.safety_misleading_skipped,
                    "safety_redirect_skipped": s.safety_redirect_skipped,
                    "safety_last_reason": s.safety_last_reason,
                    "consecutive_errors": s.consecutive_errors,
                    "url_stats": dict(s.url_stats),
                    "cookies_expired": s.cookies_expired,
                    "degraded_mode": s.degraded_mode,
                    "degraded_skipped": s.degraded_skipped,
                    "degraded_fallback_enabled": s.degraded_fallback_enabled,
                    "mode": str(s.acc.get("mode", "") or "").strip().lower(),
                    "resume_status_oauth": dict(s.resume_status or {}),
                    "hh_today_applies": s.hh_today_applies,
                    "hh_today_applies_updated": s.hh_today_applies_updated,
                    "hh_daily_limit": CONFIG.hh_daily_limit or 200,
                    "oauth_status": get_oauth_status(s.acc.get("resume_hash", "")),
                    "llm_enabled": s.llm_enabled,
                    "llm_status": s.llm_status,
                    "llm_pending_chats": s.llm_pending_chats,
                    "llm_current_neg_id": getattr(s, "llm_current_neg_id", ""),
                    "llm_current_employer": getattr(s, "llm_current_employer", ""),
                    "llm_current_idx": getattr(s, "llm_current_idx", 0),
                    "llm_current_total": getattr(s, "llm_current_total", 0),
                    "llm_last_check_at": getattr(s, "llm_last_check_at", ""),
                    "llm_next_check_at": getattr(s, "llm_next_check_at", ""),
                    "use_oauth": s.use_oauth,
                    "daily_sent": s.daily_sent,
                    "daily_limit": CONFIG.daily_apply_limit,
                    "hard_stopped": s.hard_stopped,
                    "last_apply_at": s.last_apply_at,
                    "last_apply_attempt_at": s.last_apply_attempt_at,
                    "paused_reason": s.paused_reason,
                    "network_recovery": self.network_recovery_view(s),
                    "cycle_report": cycle_snapshot(s, blocked=s.paused or self.paused or s._deleted
                        or getattr(self, "_stop_event", threading.Event()).is_set()),
                    "activity": activity_view(s, global_paused=self.paused,
                        stopped=getattr(self, "_stop_event", threading.Event()).is_set(),
                        global_started_at=getattr(self, "_activity_global_pause_started_at", None)),
                    "pending_apply": dict(s.pending_apply) if s.pending_apply else None,
                    "pending_applies": [dict(item) for item in s.pending_applies],
                })
            else:
                # Неактивная сессия — заглушка
                accounts.append({
                    "idx": idx,
                    "name": ts.get("name", f"Браузер #{i+1}"),
                    "short": ts.get("short", f"Браузер#{i+1}"),
                    "color": "yellow",
                    "temp": True,
                    "bot_active": False,
                    "cycle_report": None,
                    "activity": activity_view(SimpleNamespace(
                        pending_apply=ts.get("pending_apply"),
                        paused_reason=ts.get("paused_reason", "")), stopped=True),
                    "resume_hash": ts.get("resume_hash", ""),
                    "all_resumes": ts.get("all_resumes", []),
                    "letter": ts.get("letter", ""),
                    "status": "—", "status_detail": "", "sent": 0, "tests": 0,
                    "errors": 0, "already_applied": 0, "found_vacancies": 0,
                    "current_vacancy_title": "", "current_vacancy_company": "",
                    "current_vacancy_idx": 0, "total_vacancies": 0,
                    "salary_skipped": 0, "questionnaire_sent": 0,
                    "limit_exceeded": bool(ts.get("limit_exceeded")), "paused": bool(ts.get("paused")),
                    "paused_reason": ts.get("paused_reason", ""),
                    "network_recovery": {key: ts["network_recovery"].get(key) for key in (
                        "reason", "attempts", "next_check_at", "last_started_at", "last_error")}
                        if isinstance(ts.get("network_recovery"), dict) else None,
                    "pending_apply": dict(ts["pending_apply"]) if ts.get("pending_apply") else None,
                    "pending_applies": [dict(item) for item in ts.get("pending_applies") or []],
                    "next_resume_touch": "", "resume_touch_status": "",
                    "hh_interviews": 0, "hh_viewed": 0, "hh_discards": 0,
                    "hh_not_viewed": 0, "hh_unread_by_employer": 0,
                    "hh_stats_updated": "", "hh_stats_loading": False,
                    "hh_interviews_list": [], "hh_possible_offers": [], "action_history": [],
                    "resume_views_7d": 0, "resume_views_new": 0, "resume_shows_7d": 0,
                    "resume_invitations_7d": 0, "resume_invitations_new": 0,
                    "resume_next_touch_seconds": 0, "resume_free_touches": 0,
                    "resume_global_invitations": 0, "resume_new_invitations_total": 0,
                    "acc_event_log": [],
                    "apply_tests": bool(ts.get("apply_tests", False)),
                    "safety_enabled": bool(ts.get("safety_enabled", CONFIG.skip_inconsistent)),
                    "safety_inconsistent_skipped": 0,
                    "safety_misleading_skipped": 0,
                    "safety_redirect_skipped": 0,
                    "safety_last_reason": "",
                    "consecutive_errors": 0,
                    "url_stats": {},
                    "cookies_expired": False,
                    "degraded_mode": False,
                    "degraded_skipped": 0,
                    "degraded_fallback_enabled": bool(ts.get("degraded_fallback_enabled", True)),
                    "resume_status_oauth": {},
                    "hh_today_applies": 0,
                    "hh_today_applies_updated": "",
                    "hh_daily_limit": CONFIG.hh_daily_limit or 200,
                    "responses_streak_count": 0,
                    "responses_streak_required": 0,
                    "llm_enabled": True,
                    "use_oauth": bool(ts.get("use_oauth", False)),
                    "daily_sent": 0,
                    "daily_limit": CONFIG.daily_apply_limit,
                    "hard_stopped": False,
                })

        storage_stats = get_stats()

        _vacancy_queues = {}
        for s in all_states:
            with s._state_lock:
                _current_vacancy_idx = s.current_vacancy_idx
                _vacancies_queue = list(s.vacancies_queue)
            _vacancy_queues[s.short] = {
                "remaining": max(0, len(_vacancies_queue) - _current_vacancy_idx),
                "next": _vacancies_queue[_current_vacancy_idx: _current_vacancy_idx + 5]
                if _vacancies_queue
                else [],
            }

        return {
            "type": "state_update",
            "snapshot_at": aware_iso(datetime.now(timezone.utc)),
            "uptime_seconds": uptime,
            "paused": self.paused,
            "accounts": accounts,
            "recent_responses": self._snap_deque(self.recent_responses, self._deque_lock),
            # Аудит 2026-08-17 #23: list(deque) без lock даёт RuntimeError или
            # неполный/повреждённый snapshot если writer в этот момент делает
            # append/appendleft. Оборачиваем в _snap_deque как recent_responses.
            "log": self._snap_deque(self.activity_log, self._deque_lock),
            "llm_log": self._snap_deque(self.llm_log, self._deque_lock),
            "config": {
                **{key: getattr(CONFIG, key) for key in TOGGLES.values()},
                "telegram_captcha_enabled": CONFIG.telegram_captcha_enabled,
                **{key: getattr(CONFIG, key) for key in ("captcha_llm_enabled", "captcha_model_name", "captcha_llm_solved", "captcha_llm_forwarded")},
                "telegram_bot_token_set": bool(CONFIG.telegram_bot_token),
                "telegram_connected": bool(getattr(getattr(self, "telegram_captcha_bot", None), "connected", False)),
                "pages_per_url": CONFIG.pages_per_url,
                **{key: getattr(CONFIG, key) for key in human_pace.HUMAN_CONFIG_KEYS},
                "human_target_applies_per_hour": human_pace.TARGET_APPLIES_PER_HOUR,
                "human_local_hour": datetime.now(human_pace._MSK).hour,
                "captcha_llm_week": captcha_llm_week(),
                "human_weekend_variance": human_pace.weekend_variance(),
                "human_mode_enabled": CONFIG.human_mode_enabled,
                "response_delay": CONFIG.response_delay,
                "pause_between_cycles": CONFIG.pause_between_cycles,
                "batch_responses": CONFIG.batch_responses,
                "limit_check_interval": CONFIG.limit_check_interval,
                "min_salary": CONFIG.min_salary,
                "auto_pause_errors": CONFIG.auto_pause_errors,
                "auto_apply_tests": CONFIG.auto_apply_tests,
                "use_oauth_apply": CONFIG.use_oauth_apply,
                "daily_apply_limit": CONFIG.daily_apply_limit,
                "hh_daily_limit": CONFIG.hh_daily_limit,
                "fresh_vacancies_mode": CONFIG.fresh_vacancies_mode,
                "prefer_hh_signals": CONFIG.prefer_hh_signals,
                "fresh_vacancy_hours": CONFIG.fresh_vacancy_hours,
                "fresh_apply_reserve": CONFIG.fresh_apply_reserve,
                "stop_on_hh_limit": CONFIG.stop_on_hh_limit,
                "llm_check_interval": CONFIG.llm_check_interval,
                "allowed_schedules": CONFIG.allowed_schedules,
                "remote_it_only": CONFIG.remote_it_only,
                "title_include_keywords": getattr(CONFIG, "title_include_keywords", []),
                "title_exclude_keywords": getattr(CONFIG, "title_exclude_keywords", []),
                "questionnaire_templates": CONFIG.questionnaire_templates,
                "questionnaire_preset_previews": questionnaire_preset_previews(),
                "questionnaire_default_answer": questionnaire_default_answer(),
                "letter_templates": CONFIG.letter_templates,
                "url_pool": CONFIG.url_pool,
                "skip_inconsistent": CONFIG.skip_inconsistent,
                "filter_agencies": CONFIG.filter_agencies,
                "filter_low_competition": CONFIG.filter_low_competition,
                "search_period_days": CONFIG.search_period_days,
                "llm_enabled": CONFIG.llm_enabled,
                "llm_auto_send": CONFIG.llm_auto_send,
                "llm_fill_questionnaire": CONFIG.llm_fill_questionnaire,
                "llm_check_questionnaire_claims": CONFIG.llm_check_questionnaire_claims,
                "llm_use_cover_letter": CONFIG.llm_use_cover_letter,
                "llm_use_resume": CONFIG.llm_use_resume,
                "llm_applicant_gender": CONFIG.llm_applicant_gender,
                "llm_use_quick_replies": getattr(CONFIG, "llm_use_quick_replies", True),
                "hh_ai_letter_first_try": getattr(CONFIG, "hh_ai_letter_first_try", True),
                "related_vacancies_enabled": getattr(CONFIG, "related_vacancies_enabled", True),
                "llm_model": CONFIG.llm_model,
                "llm_base_url": CONFIG.llm_base_url,
                "llm_status_summary": get_llm_status_summary(),
                # Системный промпт нужен в снимке: после релоада фронт инитит
                # textarea дефолтом, а потом любая правка ругого поля LLM
                # autosave'ила бы этот дефолт обратно на диск. Снимок служит
                # источником истины для UI.
                "llm_system_prompt": CONFIG.llm_system_prompt,
                # Note: don't include llm_api_key in snapshot for security,
                # но кладём fingerprint + key_set, чтобы UI мог показать
                # «✓ ключ сохранён (sk-p…wxyz, 164 симв.)» после релоада —
                # type=password input не покажет значение даже если бы оно было.
                "llm_api_key_set": bool((CONFIG.llm_api_key or "").strip()),
                "llm_api_key_fingerprint": _fingerprint_key(CONFIG.llm_api_key),
                "llm_profiles": [
                    {
                        "name": p.get("name", ""),
                        "base_url": p.get("base_url", ""),
                        "model": p.get("model", ""),
                        "enabled": p.get("enabled", True),
                        "key_set": bool((p.get("api_key") or "").strip()),
                        "key_fingerprint": _fingerprint_key(p.get("api_key", "")),
                        "key_len": len((p.get("api_key") or "").strip()),
                    }
                    for p in (CONFIG.llm_profiles or [])
                ],
                "llm_profile_mode": CONFIG.llm_profile_mode,
            },
            "global_stats": {
                "applied_today": sum(max(s.daily_sent or 0, s.hh_today_applies or 0) for s in all_states),
                "total_sent": sum(s.sent for s in all_states),
                "total_tests": sum(s.tests for s in all_states),
                "total_errors": sum(s.errors for s in all_states),
                "total_found": sum(s.found_vacancies for s in all_states),
                "storage_total": storage_stats["total"],
                "storage_tests": storage_stats["tests"],
            },
            "vacancy_queues": _vacancy_queues,
        }

    def _run_account_worker(self, idx: int, state: AccountState) -> None:
        """Thread worker for an account — auto-restarts on crash"""
        while not self._stop_event.is_set() and not getattr(state, '_deleted', False):
            try:
                self._run_account_worker_inner(idx, state)
                break  # normal exit
            except MutationBlocked:
                # Пауза/капча/остановка запретили запись (например поднятие резюме) — это
                # штатное ожидание, а не сбой: без падения, лога ошибки и Telegram-алерта
                # каждые 30 с (так было 845 раз за ночь при неподтверждённой капче).
                set_activity(state, "paused_wait", "Запись запрещена (пауза/капча/остановка); ждёт снятия",
                    "Продолжит рабочий цикл, когда ограничение будет снято",
                    wait_until=datetime.now(timezone.utc) + timedelta(seconds=30))
                if not human_pace.interruptible_wait(
                        self._stop_event, 30, lambda: not getattr(state, '_deleted', False)):
                    break
            except Exception as e:
                log_exception(f"WORKER CRASHED [{state.short}]", e)
                cycle_operation_error(state)
                finish_cycle(state, "error")
                state.status = "error"
                state.status_detail = f"Перезапуск через 30с ({str(e)[:30]})"
                self._add_log(state.short, state.color, f"⚠️ Worker упал: {str(e)[:50]}. Перезапуск через 30с", "error")
                set_activity(state, "recover_error", "Рабочий цикл завершился ошибкой; ожидает перезапуска",
                    "Попробует начать новый цикл, если нет паузы или остановки",
                    wait_until=datetime.now(timezone.utc) + timedelta(seconds=30))
                if not human_pace.interruptible_wait(
                        self._stop_event, 30, lambda: not getattr(state, '_deleted', False)):
                    break
                state.status = "idle"
                state.status_detail = "Перезапущен после ошибки"
                self._add_log(state.short, state.color, "\U0001f504 Worker перезапущен", "info")

    def _worker_sleep(self, state, seconds):
        """Sleep in 1s slices so stop/delete are honoured (time.sleep keeps test doubles valid)."""
        for _ in range(int(seconds)):
            if self._stop_event.is_set() or state._deleted:
                return
            time.sleep(1)

    def _wait_human_pace(self, state):
        """Reserve a durable slot before sending; cancellation never clears it."""
        while CONFIG.human_mode_enabled:
            if not self._can_mutate(state):
                return False
            human_pace.sleep_until_active_hour(
                state, self._stop_event, allowed=lambda: self._can_mutate(state))
            if not self._can_mutate(state):
                return False
            if not CONFIG.human_mode_enabled:
                return False
            delay = human_pace.reserve_attempt(state.acc, multiplier=human_pace.delay_multiplier(state))
            if delay <= 0:
                return True
            set_activity(state, "wait_between_batches", "Выдерживает сохранённый интервал",
                "Проверит активные часы и ограничения перед одним откликом",
                wait_until=datetime.now(timezone.utc) + timedelta(seconds=delay))
            # Re-evaluate edited intervals at least once a minute, without
            # waiting out a stale hours-long deadline.
            if not human_pace.interruptible_wait(self._stop_event, min(delay, 60),
                    lambda: CONFIG.human_mode_enabled and self._can_mutate(state)):
                return False
        return self._can_mutate(state)

    def _wait_account_start_jitter(self, state):
        if not CONFIG.human_mode_enabled:
            return True
        if not hasattr(state, '_human_start_at'):
            state._human_start_at = time.monotonic() + human_pace.account_start_jitter()
        remaining = max(0, state._human_start_at - time.monotonic())
        if not remaining:
            return True
        set_activity(state, 'wait_between_batches', 'Ожидает начала работы аккаунта',
            'Проверит паузы и ограничения перед началом работы',
            wait_until=datetime.now(timezone.utc) + timedelta(seconds=remaining))
        return human_pace.interruptible_wait(self._stop_event, remaining,
            lambda: not state._deleted)

    def _wait_post_captcha_cooldown(self, state):
        """Wait in the worker; a resume notification cannot cancel the deadline."""
        event = state.__dict__.setdefault('_captcha_wake', threading.Event())
        while not self._stop_event.is_set() and not state._deleted:
            if self.paused or state.paused:
                return False
            remaining = human_pace.captcha_cooldown_remaining(state)
            if remaining <= 0:
                return True
            state.status_detail = (f'Пауза после капчи: ещё {math.ceil(remaining)} сек'
                                   if remaining < 60 else
                                   f'Пауза после капчи: ещё {math.ceil(remaining / 60)} мин')
            set_activity(state, 'wait_between_batches', state.status_detail,
                'После паузы проверит ограничения перед возобновлением',
                wait_until=datetime.now(timezone.utc) + timedelta(seconds=remaining))
            event.wait(timeout=min(1.0, remaining))
            event.clear()
        return False

    def _prepare_human_apply(self, state, acc, vacancy_id):
        if not CONFIG.human_mode_enabled:
            return True
        allowed = lambda: CONFIG.human_mode_enabled and self._can_dispatch_apply(state, vacancy_id)
        wait = lambda seconds: human_pace.interruptible_wait(self._stop_event, seconds, allowed)
        if not wait(human_pace.random_apply_delay() * human_pace.delay_multiplier(state)):
            return False
        # The helper owns the single 30% draw and the 5–15 second reading wait.
        human_pace.warm_up_read_vacancy({**acc, '_human_wait': wait}, vacancy_id)
        return allowed()

    def _human_burst_pause(self, state):
        idle = human_pace.long_idle_burst()
        delay = (idle if idle is not None else human_pace.random_burst_pause())
        delay *= human_pace.delay_multiplier(state)
        if idle is not None:
            self._add_log(state.short, state.color, f'human: отвлёкся на {delay / 60:.0f} мин', 'info')
        return delay

    def _wait_human_burst(self, state):
        if not CONFIG.human_mode_enabled:
            return True
        if not getattr(state, '_human_burst_target', 0):
            state._human_burst_target = human_pace.random_burst_size()
        state._human_burst_count = getattr(state, '_human_burst_count', 0) + 1
        if state._human_burst_count < state._human_burst_target:
            return True
        state._human_burst_count = 0
        state._human_burst_target = human_pace.random_burst_size()
        delay = self._human_burst_pause(state)
        set_activity(state, 'wait_between_batches', 'Пауза между сериями откликов',
            'Проверит сохранённый интервал и ограничения перед следующим откликом',
            wait_until=datetime.now(timezone.utc) + timedelta(seconds=delay))
        return human_pace.interruptible_wait(self._stop_event, delay,
            lambda: CONFIG.human_mode_enabled and self._can_mutate(state))

    def _can_dispatch_apply(self, state, vacancy_id):
        """Last local check at the write boundary; never sends or clears pauses."""
        if not self._can_mutate(state) or state.limit_exceeded:
            return False
        if CONFIG.human_mode_enabled and not human_pace.is_active_hour():
            return False
        # Serial OAuth successes enter daily_sent after the batch. Include them
        # now so a concurrent tracker update cannot reopen already used slots.
        used = (max(state.daily_sent or 0, state.hh_today_applies or 0)
                + getattr(state, '_unaccounted_apply_successes', 0))
        if not _cap_apply_batch([vacancy_id], used, used):
            return False
        if CONFIG.fresh_vacancies_mode:
            selected, _ = _protect_fresh_batch(
                [vacancy_id], state.vacancy_meta, hours=CONFIG.fresh_vacancy_hours,
                ceiling=_effective_daily_ceiling(), reserve=CONFIG.fresh_apply_reserve,
                used=used)
            if not selected:
                return False
        return (not quarantine_blocked(state.acc, vacancy_id)
                and (not CONFIG.remote_it_only
                     or remote_it_rejection(state.vacancy_meta.get(vacancy_id, {})) is None))

    def _recheck_apply_batch(self, state, batch):
        """Refresh mutable budgets after preflight / a potentially long wait."""
        self._maybe_roll_daily_counter(state)
        if not self._can_mutate(state) or state.limit_exceeded:
            return []
        batch = _cap_apply_batch(batch, state.daily_sent, state.hh_today_applies)
        if not batch:
            with state._state_lock:
                # Do not replace a newer user or protective pause.
                if not self._can_mutate(state):
                    return []
                state.hard_stopped = True
                state.paused = True
                state.paused_reason = 'limit'
                state.status = 'limit'
                used = max(state.daily_sent or 0, state.hh_today_applies or 0)
                state.status_detail = f'Дневной лимит: {used}/{_effective_daily_ceiling()}. Сброс в 00:00 МСК'
            self._persist_pauses()
            return []
        if CONFIG.fresh_vacancies_mode:
            selected, deferred = _protect_fresh_batch(
                batch, state.vacancy_meta, hours=CONFIG.fresh_vacancy_hours,
                ceiling=_effective_daily_ceiling(), reserve=CONFIG.fresh_apply_reserve,
                used=max(state.daily_sent or 0, state.hh_today_applies or 0))
            state.fresh_reserved_skipped += deferred
            for vid in set(batch) - set(selected):
                cycle_outcome(state, vid, 'skipped', 'fresh_reserve')
            batch = selected
            if not batch:
                set_activity(state, 'fresh_reserve', 'Оставшиеся отклики зарезервированы для свежих вакансий',
                    'Повторит поиск новых вакансий; лимит и свежесть проверены после ожидания')
        return batch

    def _run_account_worker_inner(self, idx: int, state: AccountState) -> None:
        acc = state.acc
        self._bind_mutation_guard(state)
        if not self._wait_account_start_jitter(state):
            return
        if not state._active_search_forced and self._can_mutate(state):
            try:
                set_activity(state, "resume_check", "Устанавливает статус поиска работы в HH",
                    "Проверит доступность резюме и перейдёт к поиску вакансий")
                r = get_client(acc).set_job_search_status("active_search")
                if r.get("ok"):
                    state._active_search_forced = True
                    self._add_log(state.short, state.color,
                                  "\U0001f7e2 Статус: активный поиск", "info")
                else:
                    # Транзиентный fail — не выставляем флаг, попробуем на следующем
                    # перезапуске воркера (после crash или ручной паузы).
                    log_debug(f"active_search [{state.short}]: {r.get('error', '?')[:80]}")
            except Exception as e:
                log_debug(f"active_search [{state.short}] exception: {e}")

        while not self._stop_event.is_set() and not state._deleted:
            notify_account_state_change(state, AlertCategory.account_blocked)
            notify_account_state_change(state, AlertCategory.daily_limit_reached)
            # Global + per-account pause
            while (self.paused or state.paused or getattr(state, "_auth_recovery_pending", False)) and not self._stop_event.is_set() and not state._deleted:
                notify_account_state_change(state, AlertCategory.account_blocked)
                notify_account_state_change(state, AlertCategory.daily_limit_reached)
                self._reconcile_pending_if_due(state)
                self._quarantine_exhausted_apply(state)
                self._network_probe_if_due(state)
                if not self.paused and not state.paused and not getattr(state, "_auth_recovery_pending", False):
                    break
                # Auto-reset daily limit pause when new day starts
                if state.hard_stopped:
                    if self._maybe_roll_daily_counter(state):
                        # _maybe_roll_daily_counter clears limit pauses only;
                        # an unresolved write must survive midnight unchanged.
                        state.status = "idle"
                        state.status_detail = "Новый день — лимит сброшен"
                        self._add_log(state.short, state.color,
                            "\U0001f305 Новый день! Лимит сброшен" + (
                                "" if state.paused_reason != "manual" else ", аккаунт остался на manual pause"),
                            "success")
                        self._persist_pauses()
                        if not state.paused and not self.paused:
                            break
                if state.hard_stopped:
                    state.status = "limit"
                    if CONFIG.daily_apply_limit > 0 and state.daily_sent >= CONFIG.daily_apply_limit:
                        state.status_detail = f"Дневной лимит: {state.daily_sent}/{CONFIG.daily_apply_limit}. Сброс завтра в 00:00"
                    else:
                        state.status_detail = "Лимит HH. Сброс завтра в 00:00"
                elif state.limit_exceeded:
                    state.status = "limit"
                    if state.limit_reset_time:
                        remaining = int((state.limit_reset_time - datetime.now()).total_seconds())
                        if remaining > 0:
                            state.status_detail = f"Лимит HH. Проверка через {remaining // 60}м{remaining % 60:02d}с"
                        else:
                            state.status_detail = "Лимит HH. Проверка сейчас..."
                    else:
                        state.status_detail = "Лимит HH. Проверка через 1м"
                else:
                    state.status = "idle"
                    state.status_detail = (self._pause_detail(state) if state.paused else
                        "Сохраняет результат проверки авторизации" if getattr(state, "_auth_recovery_pending", False)
                        else "Общая пауза")
                if not hasattr(state, '_captcha_wake'):
                    state._captcha_wake = threading.Event()
                state._captcha_wake.wait(1)
                state._captcha_wake.clear()

            if self._stop_event.is_set():
                break

            if not self._wait_post_captcha_cooldown(state):
                continue

            now = datetime.now()

            # === АВТОПОДНЯТИЕ РЕЗЮМЕ ===
            if state.resume_touch_enabled:
                should_touch = False
                if state.next_resume_touch is None:
                    should_touch = True
                elif now >= state.next_resume_touch:
                    should_touch = True

                if should_touch:
                    set_activity(state, "resume_check", "Проверяет в HH, доступно ли поднятие резюме",
                        "Поднимет резюме только при разрешении HH, затем продолжит поиск")
                    # Всегда сверяемся с сервером непосредственно перед publish:
                    # UI/фоновая статистика используют 5-минутный cache и после
                    # предыдущего touch могут ещё показывать устаревшее `true`.
                    fresh_status = get_client(acc).fetch_resume_status(force=True)
                    server_next = _server_next_publish_datetime(fresh_status)
                    if fresh_status and not fresh_status.get("can_publish_or_update"):
                        state.resume_free_touches = 0
                        if server_next and server_next > now:
                            state.next_resume_touch = server_next
                            state.resume_touch_status = f"⏳ Доступно в {server_next.strftime('%H:%M')}"
                        else:
                            # Сервер запретил publish, но не отдал время. Не вызываем
                            # publish в этом проходе; свежий статус проверится в
                            # следующем обычном цикле без ложного запроса на поднятие.
                            state.next_resume_touch = now + timedelta(minutes=5)
                            state.resume_touch_status = "⏳ HH пока не разрешает поднятие"
                    elif fresh_status.get("can_publish_or_update"):
                        self._add_log(state.short, state.color, "\U0001f4e4 Поднимаю резюме...", "info")
                        set_activity(state, "resume_touch", "Выполняет поднятие резюме и проверяет результат",
                            "После ответа HH продолжит рабочий цикл")
                        success, message = get_client(acc).touch_resume()
                        # Результат publish немедленно делает прежний cache статуса
                        # недействительным. Следующее время берём только у HH.
                        after_status = get_client(acc).fetch_resume_status(force=True)
                        server_next = _server_next_publish_datetime(after_status)
                        state.resume_free_touches = int(bool(after_status.get("can_publish_or_update")))
                        if server_next and server_next > now:
                            state.next_resume_touch = server_next
                        else:
                            # Защита на случай eventual consistency API: повторно
                            # читаем статус позже, но publish без разрешения не шлём.
                            state.next_resume_touch = now + timedelta(minutes=5)
                        if success:
                            state.resume_touch_status = "✅ Поднято!"
                            self._add_log(
                                state.short, state.color,
                                f"✅ Резюме поднято! Следующая проверка в {state.next_resume_touch.strftime('%H:%M')}",
                                "success",
                            )
                        else:
                            state.resume_touch_status = f"⏳ {message}"
                            self._add_log(
                                state.short, state.color,
                                f"\U0001f4e4 {message}. Следующая проверка статуса в {state.next_resume_touch.strftime('%H:%M')}",
                                "warning",
                            )
                    else:
                        # Без подтверждённого разрешения от HH ручку publish не
                        # вызываем. Сетевая ошибка статуса не должна вести к 429.
                        state.next_resume_touch = now + timedelta(minutes=5)
                        state.resume_touch_status = "⏳ Не удалось проверить доступность"

            # === ПРОВЕРКА ЛИМИТА ===
            if state.limit_exceeded and self._maybe_roll_daily_counter(state):
                state._limit_is_throttle = False
            if state.limit_exceeded:
                # If no reset time set, schedule a check soon
                if not state.limit_reset_time:
                    state.limit_reset_time = now + timedelta(minutes=1)

                if now >= state.limit_reset_time:
                    state.status = "checking"
                    state.status_detail = "Проверка сброса лимита..."
                    set_activity(state, "limit_check", "Проверяет в HH, снят ли лимит откликов",
                        "Продолжит только при подтверждённой доступности и отсутствии паузы")
                    self._add_log(state.short, state.color, "\U0001f50d Проверяю сброс лимита...", "info")

                    with state._state_lock:
                        limit_check_before = self._limit_check_guard(state)
                    # A 429 throttle expires by time; check_limit() never proves "not limited".
                    throttled = getattr(state, "_limit_is_throttle", False)
                    if (throttled or get_client(acc).check_limit() is False) and self._clear_checked_limit(state, limit_check_before):
                        state._limit_is_throttle = False
                        self._add_log(
                            state.short, state.color, "✅ Лимит сброшен! Продолжаю работу", "success"
                        )
                    else:
                        state.limit_reset_time = now + timedelta(minutes=CONFIG.limit_check_interval)
                        state.status = "limit"
                        state.status_detail = f"Проверка в {state.limit_reset_time.strftime('%H:%M')}"
                        self._add_log(
                            state.short, state.color,
                            f"⏳ Лимит ещё активен, попробую в {state.limit_reset_time.strftime('%H:%M')}",
                            "warning",
                        )
                        set_activity(state, "limit_wait", "Лимит ещё не подтверждён как снятый; ожидает проверки",
                            "Проверит доступность откликов после ожидания",
                            wait_until=state.limit_reset_time)
                        self._worker_sleep(state, 60)
                        continue
                else:
                    state.status = "limit"
                    remaining = int((state.limit_reset_time - now).total_seconds())
                    state.status_detail = f"Проверка через {remaining}с"
                    set_activity(state, "limit_wait", "Ожидает запланированной проверки лимита HH",
                        "Проверит доступность откликов, если нет паузы",
                        wait_until=state.limit_reset_time)
                    self._worker_sleep(state, 30)
                    continue

            # === СБОР ВАКАНСИЙ (ПАРАЛЛЕЛЬНО) ===
            begin_cycle(state)
            set_activity(state, "search_setup", "Получает сохранённые поиски HH и готовит параметры поиска",
                "Загрузит вакансии по выбранным поискам")
            # Если у аккаунта нет своих URL — используем глобальный пул
            effective_urls = list(acc.get("urls") or [_url_entry(u)["url"] for u in CONFIG.url_pool])
            # Auto-merge сохранённых поисков юзера с hh.ru (cached 1h) — добавляются
            # к существующему пулу. items_url у HH возвращается в api.hh.ru-домене;
            # cookie-collector использует hh.ru/search/vacancy, поэтому конвертируем.
            try:
                for ss in fetch_saved_vacancy_searches(acc):
                    iu = ss.get("items_url", "") or ""
                    if not iu:
                        continue
                    web_url = iu.replace("api.hh.ru/vacancies", "hh.ru/search/vacancy")
                    if web_url not in effective_urls:
                        effective_urls.append(web_url)
            except Exception as e:
                log_debug(f"saved_searches merge error [{state.short}]: {e}")
                cycle_operation_error(state)
            state.total_urls = len(effective_urls)

            state.status = "collecting"
            state.status_detail = "Начинаю параллельный сбор..."
            set_activity(state, "collect", "Загружает вакансии из HH",
                "Проверит результаты и исключит уже обработанные вакансии")
            state.vacancies_by_url = {}
            state.vacancy_meta = {}  # Сброс метаданных вакансий для нового цикла

            self._add_log(
                state.short, state.color,
                f"\U0001f4e5 Параллельный сбор: {len(effective_urls)} URL × {CONFIG.pages_per_url} стр",
                "info",
            )

            # Degraded mode: cookies протухли, но OAuth refresh_token живой.
            # Используем api.hh.ru/vacancies вместо cookie-based scraping.
            # Per-account тумблер degraded_fallback_enabled (default True) даёт
            # юзеру отключить авто-fallback для конкретного аккаунта.
            use_oauth_collect = _uses_api_search(acc, state)
            try:
                if use_oauth_collect:
                    results_by_url, salary_map, schedule_map = self._collect_via_oauth_api(state)
                    # degraded_mode = "web cookies были живые и умерли, теперь
                    # едем на OAuth-fallback". Для чисто mobile-flow (OTP-логин,
                    # никогда не было web cookies) это НЕ degraded — это штатный
                    # native mode. UI-баджа с "⚠️ Degraded" пугала юзеров без
                    # реальной проблемы.
                    is_mobile_native = str(acc.get("mode", "")).strip().lower() in ("mobile", "oauth")
                    has_results = bool(any(v for v in results_by_url.values()))
                    state.degraded_mode = has_results and not is_mobile_native
                    if state.degraded_mode:
                        self._add_log(
                            state.short, state.color,
                            "⚠️ Cookies dead → degraded OAuth-режим (без опросников/тестов)",
                            "warning",
                        )
                else:
                    results_by_url, salary_map, schedule_map = asyncio.run(self._collect_all_urls_parallel(state))
                    if not state.cookies_expired:
                        # Снимаем degraded флаг если cookies снова валидны.
                        state.degraded_mode = False
            except Exception as e:
                log_exception(f"COLLECT CRASH [{state.short}]", e)
                cycle_operation_error(state)
                finish_cycle(state, "error")
                state.status = "error"
                state.status_detail = f"Ошибка сбора: {str(e)[:50]}"
                set_activity(state, "recover_error", "Не удалось завершить сбор вакансий; ожидает повторного цикла",
                    "Повторит поиск, если нет защитной остановки",
                    wait_until=datetime.now(timezone.utc) + timedelta(seconds=60))
                self._worker_sleep(state, 60)
                continue

            all_vacancies = []
            set_activity(state, "filter", "Объединяет результаты и проверяет дополнительные подборки HH",
                "Исключит неподходящие и уже обработанные вакансии")
            for url in effective_urls:
                url_vacancies = results_by_url.get(url, set())
                state.vacancies_by_url[url] = len(url_vacancies)
                all_vacancies.extend(url_vacancies)

                query = extract_search_query(url)
                if url_vacancies:
                    self._add_log(state.short, state.color, f"\U0001f4ca {query}: {len(url_vacancies)}", "info")
            # Сохраняем статистику по URL для снапшота
            state.url_stats = dict(state.vacancies_by_url)

            unique_vacancies = set(all_vacancies)
            cycle_raw_count = len(all_vacancies)
            # related_vacancies — рекомендательный фид HH под seed-вакансию.
            # Обычно match'ит лучше чем текстовый поиск (внутренний ML ranker).
            # Один запрос на цикл — берём последнюю applied как seed.
            if CONFIG.related_vacancies_enabled and unique_vacancies:
                seed_vid = None
                for rr in self._snap_deque(self.recent_responses, self._deque_lock)[:20]:
                    if rr.get("acc") == state.short:
                        cand = str(rr.get("id") or "")
                        if cand:
                            seed_vid = cand
                            break
                if not seed_vid:
                    seed_vid = next(iter(unique_vacancies), None)
                if seed_vid:
                    try:
                        related = get_client(acc).fetch_related_vacancies(str(seed_vid), max_pages=1)
                        if related is None:
                            cycle_raw_count = None
                        elif cycle_raw_count is not None:
                            cycle_raw_count += len(related)
                        if related:
                            new_ids = set(related) - unique_vacancies
                            unique_vacancies |= set(related)
                            if new_ids:
                                self._add_log(state.short, state.color,
                                    f"\U0001f517 Related: +{len(new_ids)} вакансий (seed {seed_vid})", "info")
                    except Exception as e:
                        log_debug(f"related_vacancies error [{state.short}]: {e}")
                        cycle_raw_count = None
                        cycle_operation_error(state)
            # Favorited из HH — приоритетные кандидаты юзера. Подмешиваем в общий
            # пул (фильтры применятся как обычно — has_test и т.д.). Хранятся
            # отдельно чтобы apply phase могла отсортировать их вперёд.
            favorited_ids: set = set()
            try:
                fav = fetch_favorited_vacancies(acc)
                if fav is None:
                    cycle_raw_count = None
                elif cycle_raw_count is not None:
                    cycle_raw_count += len(fav)
                if fav:
                    favorited_ids = set(fav)
                    new_count = len(favorited_ids - unique_vacancies)
                    unique_vacancies |= favorited_ids
                    if new_count:
                        self._add_log(
                            state.short, state.color,
                            f"⭐ Избранное: +{new_count} вакансий из HH",
                            "info",
                        )
            except Exception as e:
                log_debug(f"favorited merge error [{state.short}]: {e}")
                cycle_raw_count = None
                cycle_operation_error(state)
            found_cycle(state, unique_vacancies, cycle_raw_count)
            # Blacklisted из HH — фильтруем сразу
            try:
                bl = fetch_blacklisted_vacancies(acc)
                if bl:
                    blocked_count = len(unique_vacancies & bl)
                    for blocked_vid in unique_vacancies & bl:
                        cycle_outcome(state, blocked_vid, "skipped", "hh_blacklist")
                    unique_vacancies -= bl
                    if blocked_count:
                        self._add_log(
                            state.short, state.color,
                            f"🚫 HH-blacklist: -{blocked_count} вакансий",
                            "info",
                        )
            except Exception as e:
                log_debug(f"blacklist filter error [{state.short}]: {e}")
                cycle_operation_error(state)
            state._favorited_ids = favorited_ids  # для приоритизации в apply
            total_collected = len(unique_vacancies)

            self._add_log(
                state.short, state.color,
                f"\U0001f4ca Всего собрано: {len(all_vacancies)} ({total_collected} уникальных)",
                "info",
            )

            if not unique_vacancies:
                if state.cookies_expired and not state.degraded_mode:
                    # Cookies dead AND OAuth fallback тоже не вернул ничего —
                    # тогда уже честная пауза до обновления кук.
                    state.paused = True
                    state.paused_reason = "auth"
                    self._add_log(
                        state.short, state.color,
                        "⚠️ Куки протухли и OAuth-fallback пуст. Обновите куки.", "error",
                    )
                    self._add_acc_event(state, "⚠️", "error", "Авторизация", "", "Обновите куки")
                    finish_cycle(state, "blocked")
                    continue
                state.status = "waiting"
                state.status_detail = "Нет вакансий"
                set_activity(state, "no_new", "Поиск не вернул вакансий; ожидает следующего цикла",
                    "Снова проверит выбранные поиски HH",
                    wait_until=datetime.now(timezone.utc) + timedelta(seconds=120))
                self._add_log(
                    state.short, state.color,
                    "⚠️ Не найдено ни одной вакансии, пауза 2 мин",
                    "warning",
                )
                finish_cycle(state)
                self._worker_sleep(state, 120)
                continue

            # Фильтрация
            set_activity(state, "filter", "Проверяет условия вакансий и исключает уже обработанные",
                "Соберёт очередь подходящих вакансий для проверки перед откликом")
            filtered = []
            already_count = 0
            test_count = 0
            salary_skipped = 0
            schedule_skipped = 0
            title_skipped = 0
            state.rating_skipped = 0  # per-cycle counter, reset here
            apply_tests = state.apply_tests or CONFIG.auto_apply_tests
            title_include_keywords = [
                str(k).strip().lower()
                for k in getattr(CONFIG, "title_include_keywords", [])
                if str(k).strip()
            ]
            title_exclude_keywords = [
                str(k).strip().lower()
                for k in getattr(CONFIG, "title_exclude_keywords", [])
                if str(k).strip()
            ]

            discard_skipped = 0
            unsafe_skipped = 0
            for vid in unique_vacancies:
                consider_cycle(state, vid)
                meta = state.vacancy_meta.get(vid, {})
                title = (meta.get("title") or "").lower()
                log_debug(f"Processing vacancy {vid}: {title}")
                if CONFIG.remote_it_only:
                    scope_reason = remote_it_rejection(meta)
                    if scope_reason:
                        cycle_outcome(state, vid, 'skipped', scope_reason)
                        continue
                if not title:
                    cycle_outcome(state, vid, "skipped", "missing_title")
                    continue
                if meta.get("archived"):
                    cycle_outcome(state, vid, "skipped", "archived")
                    continue
                # Android requests these flags on resume-based searches. A
                # misleading vacancy needs a human decision; an immediate
                # redirect is an obsolete/duplicate vacancy shell.
                if state.safety_enabled and meta.get("misleading_vacancy_alert"):
                    unsafe_skipped += 1
                    state.safety_misleading_skipped += 1
                    state.safety_last_reason = f"{vid}: предупреждение HH о вакансии"
                    cycle_outcome(state, vid, "skipped", "hh_warning")
                    continue
                if state.safety_enabled and meta.get("immediate_redirect_vacancy_id"):
                    unsafe_skipped += 1
                    state.safety_redirect_skipped += 1
                    state.safety_last_reason = (
                        f"{vid}: redirect → {meta.get('immediate_redirect_vacancy_id')}"
                    )
                    cycle_outcome(state, vid, "skipped", "redirect")
                    continue
                if title_include_keywords and not any(k in title for k in title_include_keywords):
                    title_skipped += 1
                    cycle_outcome(state, vid, "skipped", "title_include")
                    continue
                if title_exclude_keywords and any(k in title for k in title_exclude_keywords):
                    title_skipped += 1
                    cycle_outcome(state, vid, "skipped", "title_exclude")
                    continue
                # HH сам метит вакансии меткой DISCARD когда нас уже отвергли —
                # повторный отклик чаще всего бесполезен, экономим лимит/токены.
                hh_labels = meta.get("hh_labels") or []
                if "DISCARD" in hh_labels:
                    discard_skipped += 1
                    cycle_outcome(state, vid, "skipped", "previous_rejection")
                    continue
                # В strict OAuth/mobile режиме анкета открывается через штатный
                # autologin WebView bridge. Только degraded web-сессия без этого
                # flow должна заранее пропускать web-only формы.
                if state.degraded_mode and (
                    meta.get("has_test") or meta.get("response_letter_required")
                ):
                    state.degraded_skipped += 1
                    cycle_outcome(state, vid, "skipped", "degraded_form")
                    continue
                # Vacancy quality gates через GET /vacancies/{vid} — lazy: вызываем
                # только если хотя бы один из флагов включён (иначе extra-fetch для
                # каждой вакансии слишком дорог).
                need_details = (
                    CONFIG.skip_auto_response_vacancies
                    or CONFIG.accredited_it_only
                    or CONFIG.prefer_quick_responses
                )
                if need_details:
                    det = fetch_vacancy_details(acc, vid)
                    if det:
                        meta["auto_response"] = det.get("auto_response")
                        meta["quick_responses_allowed"] = det.get("quick_responses_allowed")
                        meta["accredited_it_employer"] = det.get("accredited_it_employer")
                        meta["key_skills"] = det.get("key_skills") or []
                        if det.get("archived"):
                            cycle_outcome(state, vid, "skipped", "archived")
                            continue
                        if CONFIG.skip_auto_response_vacancies and det.get("auto_response"):
                            state.rating_skipped = getattr(state, "rating_skipped", 0) + 1
                            cycle_outcome(state, vid, "skipped", "auto_response")
                            continue
                        if CONFIG.accredited_it_only and not det.get("accredited_it_employer"):
                            state.rating_skipped = getattr(state, "rating_skipped", 0) + 1
                            cycle_outcome(state, vid, "skipped", "accreditation")
                            continue
                # Employer rating gate: пропускаем низкорейтинговых работодателей.
                # Только если у нас есть employer_id (OAuth-сбор всегда даёт,
                # cookie-сбор — если SSR HTML содержит /employer/{id} ссылку).
                if (CONFIG.min_employer_rating > 0 or CONFIG.min_recommendations_percent > 0):
                    eid = meta.get("employer_id", "")
                    if eid:
                        rating_info = fetch_employer_rating(acc, eid)
                        if rating_info and rating_info.get("reviews_count", 0) >= CONFIG.min_employer_reviews:
                            if (CONFIG.min_employer_rating > 0
                                and rating_info.get("rating", 0) < CONFIG.min_employer_rating):
                                state.rating_skipped = getattr(state, "rating_skipped", 0) + 1
                                cycle_outcome(state, vid, "skipped", "employer_rating")
                                continue
                            if (CONFIG.min_recommendations_percent > 0
                                and rating_info.get("recommendations_percent", 0) < CONFIG.min_recommendations_percent):
                                state.rating_skipped = getattr(state, "rating_skipped", 0) + 1
                                cycle_outcome(state, vid, "skipped", "recommendations")
                                continue
                        # Cache hit для UI / Apply tab
                        if rating_info:
                            meta["employer_rating"] = rating_info
                if quarantine_blocked(acc, vid):
                    cycle_outcome(state, vid, 'skipped', 'outcome_unknown')
                    continue
                if is_applied(acc["name"], vid):
                    already_count += 1
                    state.already_applied += 1
                    cycle_outcome(state, vid, "already")
                elif state._visibility_blocked_until.get(vid, 0) > time.time():
                    cycle_outcome(state, vid, "skipped", "resume_visibility_restricted")
                elif state._test_failures.get(vid, 0) >= 2:
                    test_count += 1
                    state.tests += 1
                    cycle_outcome(state, vid, "skipped", "questionnaire_rejected_twice")
                elif is_test(vid) and not apply_tests:
                    test_count += 1
                    state.tests += 1
                    cycle_outcome(state, vid, "skipped", "questionnaire_disabled")
                elif CONFIG.allowed_schedules:
                    sched = schedule_map.get(vid, set())
                    if sched and not sched.intersection(CONFIG.allowed_schedules):
                        schedule_skipped += 1
                        cycle_outcome(state, vid, "skipped", "schedule")
                    elif CONFIG.min_salary > 0:
                        sal = salary_map.get(vid)
                        if sal is None or sal < CONFIG.min_salary:
                            salary_skipped += 1
                            state.salary_skipped += 1
                            cycle_outcome(state, vid, "skipped", "salary")
                        else:
                            filtered.append(vid)
                    else:
                        filtered.append(vid)
                elif CONFIG.min_salary > 0:
                    sal = salary_map.get(vid)
                    if sal is None or sal < CONFIG.min_salary:
                        salary_skipped += 1
                        state.salary_skipped += 1
                        cycle_outcome(state, vid, "skipped", "salary")
                    else:
                        filtered.append(vid)
                else:
                    filtered.append(vid)

            # Приоритизация: свежие → favorited → quick-response → остальные.
            # Сначала перемешиваем, чтобы старые вакансии одного класса не имели
            # постоянного перекоса из-за порядка set, затем stable-sort по стратегии.
            fav_set = getattr(state, "_favorited_ids", set()) or set()
            if filtered:
                random.shuffle(filtered)
                signal_now = datetime.now(timezone.utc)
                def _bucket(v):
                    meta = state.vacancy_meta.get(v, {}) or {}
                    fresh = CONFIG.fresh_vacancies_mode and _is_fresh_vacancy(
                        meta, CONFIG.fresh_vacancy_hours)
                    published = _vacancy_published_at(meta)
                    published_score = -(published.timestamp()) if published else 0
                    return (
                        0 if fresh else 1,
                        *(vacancy_signal_priority(meta, now=signal_now) if CONFIG.prefer_hh_signals else ()),
                        0 if v in fav_set else 1,
                        0 if CONFIG.prefer_quick_responses and meta.get("quick_responses_allowed") else 1,
                        published_score if fresh else 0,
                    )
                filtered.sort(key=_bucket)

            sal_msg = f", \U0001f4b0 зарплата {salary_skipped}" if CONFIG.min_salary > 0 else ""
            sched_msg = f", \U0001f3e2 формат {schedule_skipped}" if CONFIG.allowed_schedules else ""
            title_msg = f", \U0001f3f7️ заголовок {title_skipped}" if title_skipped else ""
            discard_msg = f", \U0001f6ab отказали {discard_skipped}" if discard_skipped else ""
            unsafe_msg = f", \u26a0\ufe0f сомнительные/redirect {unsafe_skipped}" if unsafe_skipped else ""
            rating_msg = f", ⭐ рейтинг {state.rating_skipped}" if state.rating_skipped else ""
            self._add_log(
                state.short, state.color,
                f"\U0001f50d Фильтрация: ✅ уже {already_count}, \U0001f9ea тест {test_count}{sal_msg}{sched_msg}{title_msg}{discard_msg}{unsafe_msg}{rating_msg}, \U0001f195 новые {len(filtered)}",
                "info",
            )

            if not filtered:
                finish_cycle(state)
                state.status = "waiting"
                state.status_detail = "Нет новых вакансий"
                set_activity(state, "no_new", "После фильтров не осталось новых вакансий для отклика",
                    "Повторит поиск; уже обработанные вакансии повторно не отправляет",
                    wait_until=datetime.now(timezone.utc) + timedelta(seconds=120))
                self._add_log(
                    state.short, state.color,
                    f"⚠️ Все вакансии уже обработаны ({already_count} откликов, {test_count} тестов), пауза 2 мин",
                    "warning",
                )
                self._worker_sleep(state, 120)
                continue

            # Hot leads priority: fetch possible_job_offers and put matching vacancies first
            try:
                r_offers = HH.get(
                    hh_base() + "/shards/applicant/negotiations/possible_job_offers",
                    headers={
                        "User-Agent": webview_user_agent(),
                        "Accept": "application/json",
                        "X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""),
                        "Referer": hh_base() + "/applicant/negotiations",
                    },
                    cookies=acc.get("cookies", {}), cookie_jar_key=_token_key(acc) or None,
                    timeout=10,
                )
                if r_offers.status_code == 200:
                    offers_data = r_offers.json()
                    offer_items = offers_data if isinstance(offers_data, list) else offers_data.get("possibleJobOffers", [])
                    offer_vids = set()
                    for o in offer_items:
                        vid_val = o.get("vacancyId", "")
                        if vid_val:
                            offer_vids.add(str(vid_val))
                    if offer_vids:
                        # Hot leads выше внутри своей freshness-категории, но
                        # старый hot lead не вытесняет только что опубликованную вакансию.
                        filtered.sort(key=lambda v: (
                            0 if (CONFIG.fresh_vacancies_mode and _is_fresh_vacancy(
                                state.vacancy_meta.get(v, {}) or {}, CONFIG.fresh_vacancy_hours)) else 1,
                            *(vacancy_signal_priority(state.vacancy_meta.get(v, {}) or {}, now=signal_now)
                              if CONFIG.prefer_hh_signals else ()),
                            0 if v in offer_vids else 1,
                        ))
                        hot = [v for v in filtered if v in offer_vids]
                        if hot:
                            self._add_log(state.short, state.color,
                                f"\U0001f525 {len(hot)} горячих лидов в начале очереди", "success")
            except Exception:
                pass

            state.vacancies_queue = filtered
            state.total_vacancies = len(filtered)
            state.found_vacancies += len(all_vacancies)

            self._add_log(
                state.short, state.color,
                f"✅ Найдено {len(filtered)} новых вакансий для отклика!",
                "success",
            )
            self.vacancy_queues[state.short] = {
                "vacancies": filtered,
                "current": 0,
                "color": state.color,
            }

            # === ОТПРАВКА ОТКЛИКОВ (ПАКЕТАМИ) ===
            state.status = "applying"
            state.status_detail = f"0/{state.total_vacancies}"
            self._activity_vacancy(state)
            set_activity(state, "preflight", "Готовит очередь вакансий к проверке перед откликом",
                "Проверит ограничения и пригодность очередной вакансии",
                progress=(0, state.total_vacancies))

            batch_size = CONFIG.batch_responses
            i = 0

            while i < len(filtered):
                if CONFIG.human_mode_enabled:
                    human_pace.sleep_until_active_hour(
                        state, self._stop_event, allowed=lambda: self._can_mutate(state))
                # Serialize web submissions as well as OAuth in human mode.
                batch_size = 1 if CONFIG.human_mode_enabled else CONFIG.batch_responses
                if (self._stop_event.is_set() or self.paused or state.paused
                        or state.limit_exceeded or getattr(state, "_deleted", False)):
                    break

                self._maybe_roll_daily_counter(state)
                batch = _cap_apply_batch(filtered[i: i + batch_size],
                                         state.daily_sent, state.hh_today_applies)
                if not batch:
                    self._recheck_apply_batch(state, filtered[i: i + batch_size])
                    break
                if CONFIG.human_mode_enabled and human_pace.random_skip_vacancy():
                    self._add_log(state.short, state.color, 'human: пропуск случайной вакансии', 'info')
                    cycle_outcome(state, batch[0], 'skipped', 'human_skip')
                    i += batch_size
                    continue
                state.current_vacancy_idx = i + 1
                state.status_detail = (
                    f"{i + 1}-{min(i + batch_size, len(filtered))}/{state.total_vacancies}"
                )

                if state.short in self.vacancy_queues:
                    self.vacancy_queues[state.short]["current"] = i

                # Daily limit check
                if self._maybe_roll_daily_counter(state):
                    # Cleanup unbounded dicts on new day
                    if len(state._msg_consecutive) > 500:
                        state._msg_consecutive.clear()
                if CONFIG.daily_apply_limit > 0 and state.daily_sent >= CONFIG.daily_apply_limit:
                    state.hard_stopped = True
                    state.paused = True
                    state.paused_reason = "limit"  # чтобы midnight-rollover мог снять
                    state.status = "limit"
                    state.status_detail = f"Дневной лимит: {state.daily_sent}/{CONFIG.daily_apply_limit}. Сброс завтра в 00:00"
                    self._add_log(state.short, state.color,
                        f"\U0001f6d1 Дневной лимит {CONFIG.daily_apply_limit} откликов. Пауза до завтра 00:00.", "error")
                    self._persist_pauses()
                    break
                # Pre-flight HH-лимит: если фактический счётчик от HH достиг порога —
                # не сжигаем «холостой» отклик чтобы узнать. Дождёмся либо tracker
                # сброса либо ручного toggle.
                _hh_limit = CONFIG.hh_daily_limit or 200
                if state.hh_today_applies and state.hh_today_applies >= _hh_limit:
                    state.hard_stopped = True
                    state.paused = True
                    state.paused_reason = "limit"
                    state.status = "limit"
                    state.status_detail = f"HH-лимит: {state.hh_today_applies}/{_hh_limit}. Сброс в 00:00 МСК"
                    self._add_log(state.short, state.color,
                        f"\U0001f6d1 HH daily-limit {_hh_limit} достигнут ({state.hh_today_applies} откликов). Пауза.", "error")
                    self._persist_pauses()
                    break

                # Защищённый остаток: старые вакансии могут расходовать лимит
                # только до ceiling-reserve. Свежие допускаются до полного
                # дневного ceiling. Это ожидание, не pause: следующий цикл снова
                # соберёт поиск и немедленно увидит новые публикации.
                if CONFIG.fresh_vacancies_mode:
                    ceiling = _effective_daily_ceiling()
                    reserve = min(max(int(CONFIG.fresh_apply_reserve), 0), ceiling)
                    used = max(int(state.daily_sent or 0), int(state.hh_today_applies or 0))
                    # Перед границей резерва принудительно учитываем ручные
                    # отклики и отклики из другого процесса/устройства.
                    if used >= max(0, ceiling - reserve - max(int(batch_size), 1)):
                        exact = fetch_negotiations_today_count(acc, force=True)
                        if exact and exact.get("msk_date") == _today_msk():
                            server_used = max(int(exact.get("today") or 0), 0)
                            with state._state_lock:
                                state.hh_today_applies = server_used
                                state.hh_today_applies_updated = datetime.now().isoformat(timespec="seconds")
                            used = max(used, server_used)
                    cycle_batch_before = set(batch)
                    protected_batch, deferred_old = _protect_fresh_batch(
                        batch, state.vacancy_meta,
                        hours=CONFIG.fresh_vacancy_hours,
                        ceiling=ceiling,
                        reserve=reserve,
                        used=used,
                    )
                    if deferred_old:
                        state.fresh_reserved_skipped += deferred_old
                    for deferred_vid in cycle_batch_before - set(protected_batch):
                        cycle_outcome(state, deferred_vid, "skipped", "fresh_reserve")
                    batch = protected_batch
                    if not batch:
                        state.status = "waiting"
                        state.status_detail = f"Резерв {reserve} откликов для свежих вакансий"
                        set_activity(state, "fresh_reserve", "Оставшиеся отклики зарезервированы для свежих вакансий",
                            "В следующем цикле снова проверит свежие вакансии")
                        self._add_log(
                            state.short, state.color,
                            f"🆕 Резерв: старые вакансии отложены; {reserve} слотов сохранено для публикаций ≤{CONFIG.fresh_vacancy_hours}ч",
                            "info",
                        )
                        break

                # A private account copy pins one resume for the entire attempt.
                attempt_accounts = {vid: dict(acc) for vid in batch}
                for scope_vid, attempt_acc in attempt_accounts.items():
                    attempt_acc['_mutation_guard'] = lambda vid=scope_vid: self._can_dispatch_apply(state, vid)
                # Pre-check: skip inconsistent vacancies if enabled
                if state.safety_enabled:
                    set_activity(state, "preflight", "Проверяет вакансии и выбранное резюме перед отправкой",
                        "Отправит только прошедшие проверку отклики, если нет ограничений",
                        progress=(min(i, len(filtered)), len(filtered)))
                    checked_batch = []
                    for vid in batch:
                        if self.paused or self._stop_event.is_set() or state.paused or getattr(state, "_deleted", False):
                            break
                        self._activity_vacancy(state, vid)
                        precheck = get_client(attempt_accounts[vid]).check_vacancy_before_apply(vid)
                        if not precheck["ok"]:
                            cycle_outcome(state, vid, "skipped", "preflight")
                            reason = precheck.get('reason') or ', '.join(precheck.get('hard_missing', []))
                            state.safety_inconsistent_skipped += 1
                            state.safety_last_reason = f"{vid}: {reason}"
                            meta = state.vacancy_meta.get(vid, {})
                            display_title = (meta.get("title") or vid)[:40]
                            self._add_log(state.short, state.color,
                                f"⏭ {display_title}: пропуск ({reason})", "warning")
                        else:
                            if precheck.get("resume_id"):
                                attempt_accounts[vid]["resume_hash"] = str(precheck["resume_id"])
                                attempt_accounts[vid]["_pinned_resume_id"] = str(precheck["resume_id"])
                            if precheck.get("soft_missing"):
                                self._add_log(state.short, state.color,
                                    f"⚠️ {vid}: можно откликнуться; рекомендуется: {', '.join(precheck['soft_missing'])}", "warning")
                            checked_batch.append(vid)
                            # Обогащаем vacancy_meta полями popup'а (letter_max_length,
                            # test_required, ai_assistant_enabled) — используются на этапе
                            # отправки для обрезки письма и адаптации LLM-prompt'а.
                            extras = precheck.get("extras") or {}
                            if extras:
                                meta = state.vacancy_meta.setdefault(vid, {})
                                for k, v in extras.items():
                                    if v is not None:
                                        meta[k] = v
                            # Collect HR contact info if available
                            contact = precheck.get("contact")
                            if contact and (contact.get("email") or contact.get("fio")):
                                meta = state.vacancy_meta.get(vid, {})
                                entry = {
                                    "vacancy_id": vid,
                                    "title": meta.get("title", ""),
                                    "company": meta.get("company", ""),
                                    "fio": contact.get("fio", ""),
                                    "email": contact.get("email", ""),
                                    "phone": contact.get("phone", ""),
                                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                    "account": state.short,
                                }
                                with self._hr_contacts_lock:
                                    if len(self.hr_contacts) < 500:
                                        self.hr_contacts.append(entry)
                    batch = checked_batch
                    if not batch:
                        i += batch_size
                        continue

                if len(batch) > 1:
                    self._add_log(
                        state.short, state.color,
                        f"\U0001f4e4 Пакет {len(batch)} откликов: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}",
                        "info",
                    )

                # Choose apply method: OAuth API or Web (per-account or global).
                # Также форс-OAuth в degraded mode (cookies dead, токен живой).
                if self.paused or self._stop_event.is_set() or state.paused or state._deleted:
                    break
                if CONFIG.human_mode_enabled:
                    batch = batch[:1]
                    batch_size = 1
                    if not self._wait_human_pace(state):
                        break
                    if not self._prepare_human_apply(state, attempt_accounts[batch[0]], batch[0]):
                        break
                batch = self._recheck_apply_batch(state, batch)
                if not batch:
                    i += batch_size
                    if state.paused or state.limit_exceeded or not self._can_mutate(state):
                        break
                    continue
                if state.use_oauth or CONFIG.use_oauth_apply or state.degraded_mode:
                    # OAuth: synchronous, one by one (API doesn't support batch)
                    state._unaccounted_apply_successes = 0
                    results = []
                    for vid in batch:
                        if self.paused or self._stop_event.is_set() or state.paused or getattr(state, "_deleted", False):
                            break
                        try:
                            self._activity_vacancy(state, vid)
                            set_activity(state, "apply", "Отправляет отклик и ожидает ответа HH",
                                "Учтёт ответ HH; при неизвестном результате остановится для сверки",
                                progress=(min(i + batch.index(vid), len(filtered)), len(filtered)), operation=(i, vid))
                            if state.vacancy_meta.get(vid, {}).get("has_test") is True:
                                # Like the app: a test vacancy opens its questionnaire directly.
                                # A plain POST first only earns "Must process test first" on
                                # the very endpoint where HH hands out captchas.
                                result = ("test", {})
                            else:
                                result = _oauth_apply(attempt_accounts[vid], vid, acc.get("letter", ""))
                            results.append(result)
                            if isinstance(result, tuple) and result[0] == 'sent':
                                state._unaccounted_apply_successes += 1
                            if isinstance(result, tuple) and result[0] == 'challenge':
                                self._hold_captcha(state)
                                break
                            if isinstance(result, tuple) and result[0] == "unknown":
                                self.hold_pending_apply(state, vid,
                                    attempt_accounts[vid].get("_pinned_resume_id") or attempt_accounts[vid].get("resume_hash", ""),
                                    reason_code="transport_unknown")
                                break
                        except Exception as e:
                            results.append(e)
                            if (getattr(e, "outcome_unknown", False)
                                    or getattr(e, "status_code", None) == 0
                                    or (getattr(e, "status_code", 0) or 0) >= 500):
                                self.hold_pending_apply(state, vid,
                                    attempt_accounts[vid].get("_pinned_resume_id") or attempt_accounts[vid].get("resume_hash", ""),
                                    reason_code="transport_unknown")
                                break
                        if not CONFIG.human_mode_enabled and CONFIG.response_delay > 0:
                            set_activity(state, "wait_between_batches", "Выдерживает интервал между откликами",
                                "Проверит возможность обработки следующей вакансии",
                                wait_until=datetime.now(timezone.utc) + timedelta(seconds=CONFIG.response_delay))
                            self._stop_event.wait(CONFIG.response_delay)
                else:
                    self._activity_vacancy(state)
                    set_activity(state, "apply", "Отправляет пакет откликов и ожидает ответы HH",
                        "Учтёт подтверждённые результаты; неизвестные результаты потребуют сверки",
                        progress=(min(i, len(filtered)), len(filtered)), operation=(i, tuple(batch)))
                    # Web: async batch via aiohttp
                    def _make_send_batch(b):
                        async def send_batch():
                            tasks = [get_client(attempt_accounts[vid]).submit_response(vid,
                                        letter_max_length=state.vacancy_meta.get(vid, {}).get("letter_max_length"))
                                     for vid in b]
                            return await asyncio.gather(*tasks, return_exceptions=True)
                        return send_batch
                    results = asyncio.run(_make_send_batch(batch)())

                # Confirmed responses enter daily_sent below, before any
                # questionnaire continuations. Do not count them twice.
                state._unaccounted_apply_successes = 0
                # Persist confirmed successes first, even if stop/limit arrives
                # while requests are in flight. Error handling below may break.
                completed = _completed_apply_results(batch, results)
                # Persist every ambiguous write before an unrelated limit/auth
                # result can stop processing this already-completed batch.
                for pending_vid, pending_result in completed:
                    ambiguous = (isinstance(pending_result, tuple) and pending_result[0] == "unknown")
                    ambiguous = ambiguous or (isinstance(pending_result, Exception) and (
                        getattr(pending_result, "outcome_unknown", False)
                        or getattr(pending_result, "status_code", None) == 0
                        or (getattr(pending_result, "status_code", 0) or 0) >= 500))
                    # Account for all completed replies before the legacy loop
                    # can break on an unrelated auth/limit result. No dispatch.
                    if isinstance(pending_result, MutationBlocked):
                        cycle_outcome(state, pending_vid, "skipped", "cancelled")
                    elif ambiguous:
                        cycle_outcome(state, pending_vid, "unknown")
                    elif isinstance(pending_result, Exception):
                        cycle_outcome(state, pending_vid, "error")
                    elif isinstance(pending_result, tuple) and pending_result:
                        cycle_result = pending_result[0]
                        if cycle_result in ("sent", "already"):
                            cycle_outcome(state, pending_vid, cycle_result)
                        elif cycle_result in ("error", "auth_error", "rate_limit", "challenge"):
                            cycle_outcome(state, pending_vid, "error")
                        elif cycle_result in ("cancelled", "limit"):
                            cycle_outcome(state, pending_vid, "skipped",
                                "cancelled" if cycle_result == "cancelled" else "hh_limit")
                        elif cycle_result == "test":
                            if state.apply_tests or CONFIG.auto_apply_tests:
                                questionnaire_cycle(state, pending_vid)
                            else:
                                cycle_outcome(state, pending_vid, "skipped", "questionnaire_disabled")
                    if ambiguous:
                        self.hold_pending_apply(state, pending_vid,
                            attempt_accounts[pending_vid].get("_pinned_resume_id") or attempt_accounts[pending_vid].get("resume_hash", ""),
                            reason_code="transport_unknown")
                for j, (vid, result_data) in enumerate(completed):
                    if isinstance(result_data, MutationBlocked):
                        continue
                    if isinstance(result_data, Exception) and (
                            getattr(result_data, "outcome_unknown", False)
                            or getattr(result_data, "status_code", None) == 0
                            or (getattr(result_data, "status_code", 0) or 0) >= 500):
                        result_data = ("unknown", {})
                    # A pause cancels future sends, never accounting for replies
                    # already received from HH.
                    # Любая итерация — это попытка отклика. Запоминаем время,
                    # чтобы UI мог показать «бот живой, последний раз пробовал
                    # 30с назад» даже когда удачных откликов давно не было.
                    state.last_apply_attempt_at = datetime.now().isoformat(timespec="seconds")
                    if isinstance(result_data, Exception):
                        state.errors += 1
                        state.consecutive_errors += 1
                        err_msg = str(result_data)[:60]
                        self._add_log(state.short, state.color, f"❌ {vid}: {err_msg}", "error")
                        self._add_acc_event(state, "❌", "error", vid, "", err_msg)
                        self._check_auto_pause(state)
                        continue

                    result, info = result_data

                    if result == 'challenge':
                        self._hold_captcha(state)
                        cycle_outcome(state, vid, 'skipped', 'challenge')
                        continue

                    if result == "cancelled":
                        continue
                    if result == "unknown":
                        self.hold_pending_apply(state, vid,
                            attempt_accounts[vid].get("_pinned_resume_id") or attempt_accounts[vid].get("resume_hash", ""),
                            reason_code="transport_unknown")
                        self._add_log(state.short, state.color, state.status_detail, "warning")
                        meta = state.vacancy_meta.get(vid, {})
                        self._add_response(state, vid, meta.get("title", ""), meta.get("company", ""), "unknown")
                        continue  # Still account for all other completed batch results.

                    if result == "sent":
                        state.sent += 1
                        # Daily counter
                        self._maybe_roll_daily_counter(state)
                        state.daily_sent += 1
                        state.consecutive_errors = 0  # сброс счётчика ошибок
                        state.last_apply_at = datetime.now().isoformat(timespec="seconds")
                        # Дополняем info мета-данными из поиска если API не вернул title
                        if not info.get("title"):
                            meta_fb = state.vacancy_meta.get(vid, {})
                            info = {**meta_fb, **info}
                        add_applied(acc["name"], vid, info)

                        # Collect HR contact if available
                        contact = info.get("contact", {})
                        if contact and (contact.get("email") or contact.get("fio")):
                            with self._hr_contacts_lock:
                                if len(self.hr_contacts) < 500:
                                    self.hr_contacts.append({
                                        "vacancy_id": vid,
                                        "title": info.get("title", ""),
                                        "company": info.get("company", ""),
                                        "fio": contact.get("fio", ""),
                                        "email": contact.get("email", ""),
                                        "phone": contact.get("phone", ""),
                                        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                        "acc": state.short,
                                    })

                        title = info.get("title", "Неизвестно")
                        company = info.get("company", "?")
                        sal_from = info.get("salary_from")
                        sal_to = info.get("salary_to")
                        salary = ""
                        if sal_from or sal_to:
                            salary = f"{sal_from or '?'} - {sal_to or '?'}"

                        state.current_vacancy_title = title
                        state.current_vacancy_id = vid
                        state.current_vacancy_company = company
                        self._push_action(state, f"✅ {title[:30]}")

                        self._add_response(state, vid, title, company, "sent", salary)
                        self._add_log(
                            state.short, state.color,
                            f"✅ {title[:40]} @ {company[:20]}",
                            "success",
                        )
                        self._add_acc_event(state, "✅", "sent", title or vid, company,
                                            salary if salary else "")

                    elif result == "test":
                        if (self.paused or self._stop_event.is_set() or state.paused
                                or state.hard_stopped or state._deleted):
                            continue
                        title = info.get("title", "")
                        company = info.get("company", "")
                        display_title = title[:40] if title else vid
                        # Record the discovery even when this run immediately
                        # proceeds to the questionnaire and succeeds.
                        add_test_vacancy(vid, title, company,
                                         acc["name"], acc.get("resume_hash", ""))

                        if not (state.apply_tests or CONFIG.auto_apply_tests):
                            cycle_outcome(state, vid, "skipped", "questionnaire_disabled")
                            # Откликаться на тесты выключено — пропускаем
                            state.tests += 1
                            self._push_action(state, f"⏭️ {display_title[:25]}")
                            self._add_response(state, vid, title, company, "test")
                            self._add_log(state.short, state.color,
                                          f"⏭️ Тест пропущен: {display_title}", "info")
                            self._add_acc_event(state, "⏭️", "test_skip",
                                                title or vid, company, "пропущено")
                        else:
                            # Пробуем автозаполнить опрос
                            self._activity_vacancy(state, vid)
                            set_activity(state, "questionnaire", "Обрабатывает анкету вакансии и проверяет результат",
                                "Подтвердит отклик по ответу HH либо остановится для безопасной сверки",
                                progress=(min(i + batch.index(vid), len(filtered)), len(filtered)), operation=(i, vid))
                            questionnaire_cycle(state, vid)
                            q_result, q_info = asyncio.run(get_client(attempt_accounts[vid]).fill_questionnaire(
                                vid, vacancy_title=title, company=company))
                            if q_result in ("sent", "already"):
                                cycle_outcome(state, vid, q_result)
                            elif q_result == "error" and (q_info or {}).get("error_code") == "resume_visibility_restricted":
                                cycle_outcome(state, vid, "skipped", "resume_visibility_restricted")
                            elif q_result in ("error", "auth_error", "rate_limit", "challenge"):
                                cycle_outcome(state, vid, "error")
                            elif q_result == "unknown":
                                cycle_outcome(state, vid, "unknown")
                            else:
                                cycle_outcome(state, vid, "skipped",
                                    {"limit": "hh_limit", "cancelled": "cancelled"}.get(q_result, "questionnaire_incomplete"))
                            if q_result == "sent":
                                state.sent += 1
                                state.questionnaire_sent += 1
                                state.consecutive_errors = 0
                                # Daily counter
                                self._maybe_roll_daily_counter(state)
                                state.daily_sent += 1
                                state.current_vacancy_title = title
                                state.current_vacancy_id = vid
                                state.current_vacancy_company = company
                                self._push_action(state, f"\U0001f4dd {display_title[:25]}")
                                self._add_response(state, vid, title, company, "sent")
                                self._add_log(state.short, state.color,
                                              f"\U0001f4dd Опрос пройден: {display_title}", "success")
                                q_info_full = {**state.vacancy_meta.get(vid, {}), **info}
                                add_applied(acc["name"], vid, q_info_full)
                                answer_preview = questionnaire_default_answer()[:50]
                                self._add_acc_event(state, "\U0001f4dd", "questionnaire",
                                                    title or vid, company,
                                                    f"Ответ: {answer_preview}")
                            elif q_result == "already":
                                # Receipt predating this attempt proves existence,
                                # not a new application or today's conversion.
                                state.already_applied += 1
                                add_applied(acc["name"], vid,
                                    {**state.vacancy_meta.get(vid, {}), **info}, confirmed=False)
                                self._add_response(state, vid, title, company, "already")
                            elif q_result == "limit":
                                state.limit_exceeded = True
                                notify_account_state_change(state, AlertCategory.daily_limit_reached)
                                state.limit_reset_time = datetime.now() + timedelta(
                                    minutes=CONFIG.limit_check_interval
                                )
                                state.status = "limit"
                                state.status_detail = f"Проверка в {state.limit_reset_time.strftime('%H:%M')}"
                                self._add_log(state.short, state.color,
                                              f"\U0001f6ab ЛИМИТ при опросе! Повторная попытка в {state.limit_reset_time.strftime('%H:%M')}",
                                              "error")
                                break
                            elif q_result in ("rate_limit", "challenge"):
                                self._hold_questionnaire_access(state, q_result)
                                self._add_response(state, vid, title, company, "error")
                                break
                            elif q_result == "auth_error":
                                log_debug(f"AUTH_ERROR [{state.short}] vid={vid} flow=questionnaire")
                                with state._state_lock:
                                    state.cookies_expired = True
                                    notify_account_state_change(state, AlertCategory.account_blocked)
                                    if not state.paused:
                                        state.paused = True
                                        state.paused_reason = "outcome_unknown" if state.pending_apply else "auth"
                                self._persist_pauses()
                                self._add_log(
                                    state.short, state.color,
                                    "⚠️ Куки протухли! Обновите куки и снимите паузу.", "error",
                                )
                                self._add_acc_event(state, "⚠️", "error", "Авторизация", "", "Обновите куки")
                                break
                            elif q_result == 'cancelled':
                                continue
                            elif q_result == 'error' and (q_info or {}).get('error_code') == 'resume_visibility_restricted':
                                state._visibility_blocked_until[vid] = time.time() + 3600
                                state.tests += 1
                                self._add_response(state, vid, title, company, "test")
                                self._add_log(state.short, state.color,
                                    f"HH требует изменить видимость резюме для отклика: {display_title}", "warning")
                            elif q_result == 'error':
                                # The client uses 'error' only for a known failure
                                # before submitting; no unknown write to reconcile.
                                state.errors += 1
                                state.consecutive_errors += 1
                                self._add_response(state, vid, title, company, "error")
                                self._add_log(state.short, state.color,
                                    "Анкета не отправлена: не удалось подготовить форму. Проверьте подключение.", "warning")
                                network_reason = self._network_reason(q_info)
                                diagnostic_reason = q_info.get("reason") if isinstance(q_info, dict) else None
                                if not isinstance(diagnostic_reason, str) or diagnostic_reason not in (
                                        "proxy_error", "tls_error", "connect_timeout", "read_timeout", "timeout",
                                        "connection_error", "network_error", "token_unavailable", "invalid_response",
                                        "bridge_unavailable", "auth", "challenge", "access_denied", "rate_limit"):
                                    diagnostic_reason = "unclassified_pre_submit_error"
                                self._add_log(state.short, state.color,
                                    "Причина подготовки анкеты: " + diagnostic_reason, "warning")
                                self._check_auto_pause(state, network_reason=network_reason)
                            elif q_result == 'unknown':
                                # A transport/confirmation error does not mean
                                # the applicant failed the employer's test.
                                state.errors += 1
                                self.hold_pending_apply(state, vid,
                                    attempt_accounts[vid].get("_pinned_resume_id") or attempt_accounts[vid].get("resume_hash", ""),
                                    flow="questionnaire", reason_code="questionnaire_unconfirmed")
                                self._add_response(state, vid, title, company, q_result)
                                self._add_log(state.short, state.color,
                                              'Анкета: результат не подтверждён. Нужна сверка в HH; повторная отправка заблокирована.', 'warning')
                                # Hold ambiguous submissions for manual review;
                                # never blindly resend a potentially accepted form.
                                add_test_vacancy(vid, title, company, acc['name'], acc.get('resume_hash', ''))
                            elif q_result == "test":
                                # HH вернул на форму; после двух отказов не отправляем повторно.
                                state._test_failures[vid] = state._test_failures.get(vid, 0) + 1
                                if state._test_failures[vid] >= 2:
                                    add_test_vacancy(vid, title, company,
                                                     acc["name"], acc.get("resume_hash", ""))
                                state.tests += 1
                                self._push_action(state, f"\U0001f9ea {display_title[:25]}")
                                self._add_response(state, vid, title, company, "test")
                                rejected = (q_info or {}).get("error_code") == "questionnaire_rejected"
                                self._add_log(state.short, state.color,
                                              f"\U0001f9ea Анкета не принята HH (попытка {state._test_failures[vid]}): {display_title}"
                                              if rejected else
                                              f"\U0001f9ea Анкета не завершена (попытка {state._test_failures[vid]}): {display_title}", "warning")
                                self._add_acc_event(state, "\U0001f9ea", "test",
                                                    title or vid, company,
                                                    "не принята HH" if rejected else "не завершена")
                            else:
                                self._add_log(state.short, state.color,
                                              f"Анкета не отправлена ({q_result}): {display_title}", "warning")

                    elif result == "already":
                        state.already_applied += 1
                        already_info = state.vacancy_meta.get(vid, {})
                        add_applied(acc["name"], vid, already_info if already_info else None, confirmed=False)
                        self._push_action(state, f"\U0001f504 {vid}")
                        self._add_response(state, vid, "", "", "already")

                    elif result == "limit":
                        log_debug(f"HH_LIMIT [{state.short}] vid={vid} retry_after={info.get('retry_after_seconds', '?')}")
                        state.limit_exceeded = True
                        if isinstance(info, dict) and info.get("http_429"):
                            # "Too many requests" is a short throttle, not the daily quota.
                            wait = max(int(info.get("retry_after_seconds") or 0),
                                       CONFIG.limit_check_interval * 60)
                            state.limit_reset_time = datetime.now() + timedelta(seconds=wait)
                            state._limit_is_throttle = True
                            state.status = "limit"
                            state.status_detail = f"HH: слишком часто (429). Проверка в {state.limit_reset_time.strftime('%H:%M')}"
                            self._add_log(state.short, state.color,
                                f"⏳ HH ответил 429 (слишком часто) — пауза до {state.limit_reset_time.strftime('%H:%M')}",
                                "warning")
                            break
                        notify_account_state_change(state, AlertCategory.daily_limit_reached)
                        if CONFIG.stop_on_hh_limit:
                            # Hard stop — no retries
                            state.hard_stopped = True
                            state.paused = True
                            # paused_reason="limit" — чтобы _maybe_roll_daily_counter
                            # автоматически снял паузу в полночь МСК. Без этого
                            # бот сидел на паузе несколько дней подряд (bug fix).
                            if not state.pending_apply:
                                state.paused_reason = "limit"
                            state.status = "limit"
                            state.status_detail = "\U0001f6d1 Лимит HH — остановлен до 00:00 МСК"
                            self._add_log(
                                state.short, state.color,
                                f"\U0001f6d1 ЛИМИТ HH! Бот остановлен. Автоматический сброс в 00:00 МСК.",
                                "error",
                            )
                            self._persist_pauses()
                        else:
                            state.limit_reset_time = datetime.now() + timedelta(
                                minutes=CONFIG.limit_check_interval
                            )
                            state.status = "limit"
                            state.status_detail = f"Проверка в {state.limit_reset_time.strftime('%H:%M')}"
                            self._add_log(
                                state.short, state.color,
                                f"\U0001f6ab ЛИМИТ! Повторная попытка в {state.limit_reset_time.strftime('%H:%M')}",
                                "error",
                            )
                        break

                    elif result in ("rate_limit", "challenge"):
                        self._hold_questionnaire_access(state, result)
                        self._add_response(state, vid, "", "", "error")
                        break
                    elif result == "auth_error":
                        oauth_capable = (
                            state.use_oauth
                            or CONFIG.use_oauth_apply
                            or (state.degraded_fallback_enabled and bool(acc.get("resume_hash")))
                        )
                        if oauth_capable:
                            # Cookies истекли, но OAuth доступен — переходим на degraded
                            # путь: выходим из батча, следующий цикл соберёт через
                            # api.hh.ru и применит через _oauth_apply.
                            if not getattr(state, '_web_auth_warned', False):
                                self._add_log(
                                    state.short, state.color,
                                    "⚠️ Web cookies истекли → переключаюсь на OAuth API", "warning",
                                )
                                state._web_auth_warned = True
                            log_debug(f"AUTH_ERROR [{state.short}] vid={vid} flow=apply → degraded")
                            state.cookies_expired = True
                            notify_account_state_change(state, AlertCategory.account_blocked)
                            # Прервать текущий батч cookie-applies, не пытаемся снова
                            # тем же путём в этом цикле.
                            break
                        else:
                            log_debug(f"AUTH_ERROR [{state.short}] vid={vid} flow=apply")
                            state.cookies_expired = True
                            notify_account_state_change(state, AlertCategory.account_blocked)
                            state.paused = True
                            if not state.pending_apply:
                                state.paused_reason = "auth"
                            self._persist_pauses()
                            self._add_log(
                                state.short, state.color,
                                "⚠️ Куки протухли! Обновите куки и снимите паузу.", "error",
                            )
                            self._add_acc_event(state, "⚠️", "error", "Авторизация", "", "Обновите куки")
                            break

                    elif result == "error":
                        state.errors += 1
                        self._push_action(state, f"❌ {vid}")
                        self._add_response(state, vid, "", "", "error")
                        raw = info.get("raw", "")[:80] if info else ""
                        exc = info.get("exception", "") if info else ""
                        debug_info = raw or exc or "unknown"
                        # HH иногда возвращает {"error":"unknown"} — это его сервер-сайд сбой,
                        # не наша проблема (сеть/куки OK). Не растим consecutive_errors чтобы
                        # auto_pause не срабатывал зря — тогда все успешные отклики в этом
                        # батче не бракуются `if state.paused: break` циклом ниже.
                        transient = 'error_code' in (info or {}) and (info or {}).get('error_code') == 'unknown'
                        transient = transient or 'unknown' in raw.lower()[:40]
                        if not transient:
                            state.consecutive_errors += 1
                        self._add_log(state.short, state.color, f"❌ {vid}: {debug_info}", "error")
                        self._add_acc_event(state, "❌", "error", vid, "", debug_info[:60])
                        self._check_auto_pause(state)

                if state.limit_exceeded:
                    break
                # Cookies протухли в этом цикле — выходим из всего apply-цикла,
                # на следующем тике воркер пойдёт OAuth-путём.
                if state.cookies_expired:
                    break

                i += batch_size
                if i < len(filtered) and not self._wait_human_burst(state):
                    break
                if i < len(filtered) and not CONFIG.human_mode_enabled:
                    set_activity(state, "wait_between_batches", "Выдерживает интервал между пакетами откликов",
                        "Проверит ограничения перед обработкой следующего пакета",
                        progress=(min(i, len(filtered)), len(filtered)),
                        wait_until=datetime.now(timezone.utc) + timedelta(seconds=CONFIG.response_delay))
                    self._stop_event.wait(CONFIG.response_delay)

            finish_cycle(state, "blocked" if (self.paused or state.paused
                or state.limit_exceeded or state.hard_stopped or state._deleted
                or self._stop_event.is_set()) else "waiting")
            # Очистка
            state.current_vacancy_title = ""
            state.current_vacancy_id = ""
            state.current_vacancy_company = ""
            if state.short in self.vacancy_queues:
                self.vacancy_queues[state.short] = {
                    "vacancies": [],
                    "current": 0,
                    "color": state.color,
                }

            if not state.limit_exceeded and not state.paused:
                state.status = "waiting"
                state.status_detail = "Цикл завершён"
                cycle_pause = (self._human_burst_pause(state)
                               if CONFIG.human_mode_enabled else CONFIG.pause_between_cycles)
                self._add_log(
                    state.short, state.color,
                    f"⏳ Цикл завершён, пауза {cycle_pause:.0f}с",
                    "info",
                )
                reserve_wait = state.activity.get("phase") == "fresh_reserve"
                set_activity(state, "fresh_reserve" if reserve_wait else "cycle_wait",
                    "Ожидает свежие вакансии: действует резерв откликов" if reserve_wait else "Цикл обработки завершён; ожидает следующего поиска",
                    "Снова загрузит вакансии и проверит новые предложения",
                    wait_until=datetime.now(timezone.utc) + timedelta(seconds=cycle_pause))
                # Not _can_mutate: a blocked-but-unpaused account (e.g. captcha record)
                # would skip the wait and re-run the whole search every loop.
                human_pace.interruptible_wait(self._stop_event, cycle_pause,
                    lambda: not state._deleted and not state.paused and not self.paused)

    def _hh_limit_tracker_worker(self):
        """Каждые 30 мин дёргает GET /negotiations через OAuth, считает реальное
        число сегодняшних откликов для каждого активного аккаунта.

        - Синхронизирует state.hh_today_applies = truth count из HH
        - Если бот был hard_stopped, но фактический count < CONFIG.hh_daily_limit —
          снимает hard_stopped/paused (auto-recovery, не ждём midnight).
        - На rollover в полночь MSK HH сам обнулит count → автоматически снимется.
        """
        # После рестарта быстро добираем из HH ручные/внешние отклики.
        if self._stop_event.wait(5):
            return
        while not self._stop_event.is_set():
            try:
                from datetime import datetime
                # Все активные state'ы (regular + temp)
                states = list(self.account_states) + list(self.temp_states.values())
                for state in states:
                    if not state.acc.get("resume_hash"):
                        continue
                    info = fetch_negotiations_today_count(state.acc, force=True)
                    if not info or info.get('msk_date') != _today_msk():
                        continue
                    count = info.get("today", 0)
                    with state._state_lock:
                        state.hh_today_applies = count
                        state.hh_today_applies_updated = datetime.now().isoformat(timespec="seconds")
                    # Streak-геймификация HH через mobile-endpoint (bonus поле для UI).
                    try:
                        streak = fetch_negotiations_statistic(state.acc)
                        if streak:
                            with state._state_lock:
                                state.responses_streak_count = streak.get("responses_count", 0)
                                state.responses_streak_required = streak.get("responses_required", 0)
                    except Exception as _e:
                        log_debug(f"streak fetch [{state.short}]: {_e}")
                    # Auto-recovery: если стоим в лимит-stop, а реально count < лимит
                    limit = _effective_daily_ceiling()
                    if (state.hard_stopped or state.paused_reason == "limit") and max(count, state.daily_sent) < limit - 5:
                        # 5-вакансиевый запас на гонку с in-flight откликами
                        with state._state_lock:
                            if state._deleted or max(count, state.daily_sent) >= limit - 5:
                                continue
                            state.hard_stopped = False
                            state.limit_exceeded = False
                            state.limit_reset_time = None
                            if state.paused and state.paused_reason == "limit":
                                state.paused = False
                                state.paused_reason = ""
                            # Local confirmed sends may be newer than this HTTP
                            # snapshot. Never roll them back during recovery.
                        self._add_log(
                            state.short, state.color,
                            f"✅ HH-лимит снят: фактически {count}/{limit} откликов сегодня (auto-recovery)",
                            "success",
                        )
            except Exception as e:
                log_debug(f"HH limit tracker error: {e}")
            # Пять минут: небольшой drift без лишней нагрузки на HH.
            if self._stop_event.wait(300):
                return

    def _oauth_refresh_worker(self):
        """Proactive OAuth refresh: каждые 6ч пробегает все сохранённые токены и
        обновляет те, у которых < 48ч до истечения. Идея — не дать
        refresh_token (TTL ~14 дней) самому истечь когда аккаунт не активен."""
        # Первый запуск через 60с после старта — даём lazy-refresh успеть
        # отработать после restart'а перед нашим вмешательством.
        if self._stop_event.wait(60):
            return
        while not self._stop_event.is_set():
            try:
                stats = refresh_oauth_tokens_proactive(min_ttl_hours=48)
                if stats["refreshed"] or stats["failed"]:
                    log_debug(
                        f"OAuth refresh worker: checked={stats['checked']} "
                        f"refreshed={stats['refreshed']} failed={stats['failed']}"
                    )
            except Exception as e:
                log_debug(f"OAuth refresh worker error: {e}")
            # 6 hours между запусками
            if self._stop_event.wait(6 * 3600):
                return

    def _collect_via_oauth_api(self, state: AccountState) -> tuple:
        """Degraded-mode collection via api.hh.ru/vacancies with Bearer token.
        Used when cookies are dead but OAuth refresh_token still valid.

        URL pool entries (hh.ru/search/vacancy?text=...) → api.hh.ru/vacancies?{same params}.
        HH preserves identical query-string parameter names between the search UI and
        the public OAuth API, so we can just swap host and forward the params.

        Returns the same (results_by_url, salary_map, schedule_map) shape as the cookie
        collector. Also writes has_test / response_letter_required into vacancy_meta so
        the apply loop can skip vacancies we can't fulfil without cookies.
        """
        acc = dict(state.acc)
        acc['_search_guard'] = lambda: (not state._deleted and not getattr(state, 'paused', False)
            and not getattr(self, 'paused', False)
            and not (getattr(self, '_stop_event', None) and self._stop_event.is_set()))
        effective_urls = acc.get("urls") or [_url_entry(u)["url"] for u in CONFIG.url_pool]
        results_by_url = {url: [] for url in effective_urls}
        salary_map: dict = {}
        schedule_map: dict = {}
        total_pages = 0
        completed = 0
        # Mobile collection has one authoritative page limit. Old
        # browser_sessions/url_pool overrides must not silently request more
        # pages than the value currently shown in Settings.
        try:
            configured_pages = max(1, min(int(CONFIG.pages_per_url), 100))
        except (TypeError, ValueError):
            configured_pages = 1
        total_pages = len(effective_urls) * configured_pages
        log_debug(
            f"MOBILE_COLLECT_CONFIG [{state.short}] configured_pages={configured_pages} "
            f"urls={len(effective_urls)}"
        )
        # Translate one search URL → OAuth API request
        for search_index, url in enumerate(effective_urls):
            pages = configured_pages
            text, area, query = parse_search_url(url)
            query = _mobile_search_filters(query)
            ids_for_url: set = set()
            if state._deleted:
                break
            try:
                set_activity(state, "collect", "Загружает вакансии по поисковым запросам HH",
                    "Проверит результаты и исключит уже обработанные вакансии",
                    progress=(search_index, len(effective_urls)))
                # Ограничение передаём внутрь клиента: он не должен сначала
                # загрузить 20 страниц, а затем выбросить лишние результаты.
                items = get_client(acc).search_vacancies(
                    text, area_id=area, per_page=50, page=0, filters=query,
                    max_pages=pages)
                pagination = getattr(items, 'pagination', None)
                if isinstance(pagination, dict):
                    with getattr(state, '_state_lock', nullcontext()):
                        report = getattr(state, '_cycle_report', None)
                        if report is not None:
                            report['search_pages_loaded'] = report.get('search_pages_loaded', 0) + pagination['pages_loaded']
                            if pagination['stop_reason'] != 'end':
                                report['partial'] = True
                                report['search_stop_reasons'] = list(set(report.get('search_stop_reasons', [])) | {pagination['stop_reason']})
                # Defensive cap для сторонних реализаций контракта.
                items = items[:pages * 50]
                set_activity(state, "collect", "Загружает вакансии по поисковым запросам HH",
                    "Проверит результаты и исключит уже обработанные вакансии",
                    progress=(search_index + 1, len(effective_urls)))
                completed += pagination['pages_loaded'] if pagination else pages
                state.status_detail = f"OAuth-сбор {min(completed, total_pages)}/{total_pages}"
                for it in items:
                    vid = str(it.get("id") or "")
                    if not vid:
                        continue
                    ids_for_url.add(vid)
                    # Build meta entry — mirror parse_vacancy_meta shape
                    meta_entry = state.vacancy_meta.setdefault(vid, {})
                    meta_entry.update(scope_metadata(it))
                    meta_entry["title"] = it.get("name", "") or meta_entry.get("title", "")
                    emp = it.get("employer") or {}
                    meta_entry["company"] = emp.get("name", "") or meta_entry.get("company", "")
                    meta_entry["employer_id"] = str(emp.get("id") or "") or meta_entry.get("employer_id", "")
                    meta_entry["has_test"] = bool(it.get("has_test"))
                    meta_entry["response_letter_required"] = bool(it.get("response_letter_required"))
                    meta_entry["published_at"] = it.get("published_at") or it.get("created_at") or ""
                    meta_entry["created_at"] = it.get("created_at") or ""
                    meta_entry["archived"] = bool(it.get("archived"))
                    meta_entry["misleading_vacancy_alert"] = bool(it.get("misleading_vacancy_alert"))
                    meta_entry["immediate_redirect_vacancy_id"] = str(
                        it.get("immediate_redirect_vacancy_id") or ""
                    )
                    meta_entry["is_adv"] = bool(it.get("is_adv"))
                    meta_entry.pop("skills_match_percent", None)
                    meta_entry.update(normalize_vacancy_signals(it))
                    salary_map[vid] = salary_for_ruble_threshold(it)
                    sch = it.get("schedule")
                    if isinstance(sch, dict) and sch.get("id"):
                        schedule_map.setdefault(vid, set()).add(sch["id"])
            except Exception as e:
                cycle_operation_error(state)
                log_debug(f"OAuth collect error [{state.short}]: {e}")
            results_by_url[url] = ids_for_url
        from app.vacancy_history import observe
        observe(state.vacancy_meta)
        return results_by_url, salary_map, schedule_map

    async def _collect_all_urls_parallel(self, state: AccountState) -> tuple:
        """
        Параллельный сбор вакансий со ВСЕХ URL и страниц одновременно.
        Возвращает (results_by_url: dict[url, set[ids]], salary_map: dict[vid, int|None], schedule_map: dict[vid, set])
        """
        acc = state.acc
        xsrf = acc.get("cookies", {}).get("_xsrf", "")
        if not xsrf:
            return {}, {}, {}
        headers = get_headers(xsrf)
        sem = asyncio.Semaphore(CONFIG.max_concurrent * 3)

        # Единый egress: collect тоже идёт через HH_PROXY, если задан (audit HIGH #5).
        # Общие helpers из app.hh_http (split-egress): socks → ProxyConnector,
        # http(s) → proxy= на каждый запрос.
        from app.hh_http import _aio_proxy, _aio_session_connector
        proxy = _aio_proxy()
        # socks → ProxyConnector(limit=...); http(s)/пусто → None
        connector = _aio_session_connector(proxy, limit=CONFIG.max_concurrent * 3)
        collect_req_kw: dict = {}
        if connector is None:
            # enable_cleanup_closed=True — закрывает половинно-закрытые TCP keep-alive
            # подключения (HH иногда дропает их), иначе fetch падает с ServerDisconnectedError.
            connector = aiohttp.TCPConnector(
                limit=CONFIG.max_concurrent * 3,
                enable_cleanup_closed=True,
            )
            if proxy:
                collect_req_kw = {"proxy": proxy}

        all_tasks = []
        url_pages = _url_pages_map()
        acc_url_pages = acc.get("url_pages", {})  # per-account override
        effective_urls = acc.get("urls") or [_url_entry(u)["url"] for u in CONFIG.url_pool]
        # Build extra search filter params from config
        extra_params = ""
        if CONFIG.filter_low_competition:
            extra_params += "&label=low_performance"
        if CONFIG.filter_agencies:
            extra_params += "&label=not_from_agency"
        if CONFIG.search_period_days > 0:
            extra_params += f"&search_period={CONFIG.search_period_days}"
        for url_idx, url in enumerate(effective_urls):
            pages = max(1, min(int(acc_url_pages.get(url) or url_pages.get(url, CONFIG.pages_per_url)), 100))
            sep = "&" if "?" in url else "?"
            for page in range(pages):
                page_url = f"{url}{sep}page={page}{extra_params}"
                if CONFIG.remote_it_only:
                    page_url = remote_it_url(page_url)
                all_tasks.append((url_idx, url, page, page_url))

        total_tasks = len(all_tasks)
        results_by_url = {url: [] for url in effective_urls}
        salary_map = {}
        completed = 0

        # connector передаётся явно — ClientSession его НЕ закрывает,
        set_activity(state, "collect", "Загружает страницы поиска HH",
            "Проверит результаты и исключит уже обработанные вакансии",
            progress=(0, total_tasks))
        # нужен ручной close, иначе утечка socket'ов на каждый цикл (swarm-11 #1).
        async with aiohttp.ClientSession(
            headers=headers, cookies=acc["cookies"], connector=connector,
            connector_owner=True,  # делегируем close обратно сессии
        ) as session:
            async def fetch_one(url_idx, url, page, page_url):
                nonlocal completed
                if state._deleted:
                    return url, set(), {}, {}, {}
                log_debug(
                    f"COLLECT_PAGE start [{state.short}] mode=web "
                    f"page={page + 1} page_index={page} url={page_url}"
                )
                html = await fetch_page(session, page_url, sem, collect_req_kw)
                completed += 1
                state.status_detail = f"Загрузка {completed}/{total_tasks}"
                set_activity(state, "collect", "Загружает страницы поиска HH",
                    "Проверит результаты и исключит уже обработанные вакансии",
                    progress=(completed, total_tasks))
                if html and _is_login_page(html):
                    cycle_operation_error(state)
                    if not (state.use_oauth or CONFIG.use_oauth_apply):
                        log_debug(f"AUTH_ERROR [{state.short}] vid=- flow=collect")
                        state.cookies_expired = True
                        notify_account_state_change(state, AlertCategory.account_blocked)
                    return url, set(), {}, {}, {}
                if html:
                    ids = parse_ids(html)
                    log_debug(
                        f"COLLECT_PAGE parsed [{state.short}] mode=web "
                        f"page={page + 1} vacancies={len(ids)} url={page_url}"
                    )
                    salaries = parse_salaries(html, ids)
                    meta = parse_vacancy_meta(html)
                    schedules = parse_work_schedules(html, ids)
                    # Pre-apply стратегические поля из SSR (autoResponse,
                    # chatWritePossibility, HR online). Без extra-fetch'ей —
                    # эти данные уже в HTML поисковой страницы.
                    strat = parse_apply_strategy_meta(html)
                    for vid, sm in strat.items():
                        if vid in meta:
                            meta[vid].update(sm)
                        else:
                            meta[vid] = sm
                    return url, ids, salaries, meta, schedules
                cycle_operation_error(state)
                log_debug(
                    f"COLLECT_PAGE empty [{state.short}] mode=web "
                    f"page={page + 1} url={page_url}"
                )
                return url, set(), {}, {}, {}

            # Searches can run in parallel; pages within a search must not:
            # stop on empty/repeated results instead of scheduling 100 at once.
            async def fetch_search(url):
                rows, seen = [], set()
                stop_reason = 'configured_limit'
                loaded = 0
                for args in (task for task in all_tasks if task[1] == url):
                    if state._deleted or getattr(state, 'paused', False) or getattr(self, 'paused', False) or (
                            getattr(self, '_stop_event', None) and self._stop_event.is_set()):
                        stop_reason = 'cancelled'
                        break
                    result = await fetch_one(*args)
                    loaded += 1
                    ids = set(result[1])
                    if not ids or ids <= seen:
                        stop_reason = 'empty_page' if not ids else 'repeated_page'
                        break
                    seen.update(ids)
                    rows.append(result)
                with getattr(state, '_state_lock', nullcontext()):
                    report = getattr(state, '_cycle_report', None)
                    if report is not None:
                        report['search_pages_loaded'] = report.get('search_pages_loaded', 0) + loaded
                        report['partial'] = True  # Empty HTML alone does not prove the server's last page.
                        report['search_stop_reasons'] = list(set(report.get('search_stop_reasons', [])) | {stop_reason})
                return rows

            groups = await asyncio.gather(*(fetch_search(url) for url in results_by_url), return_exceptions=True)
            task_results = []
            for group in groups:
                if isinstance(group, Exception):
                    cycle_operation_error(state)
                    task_results.append(group)
                else:
                    task_results.extend(group)

            schedule_map = {}
            for result in task_results:
                if isinstance(result, Exception):
                    log_debug(f"❌ Ошибка при загрузке: {result}")
                    continue
                url, ids, salaries, meta, schedules = result
                results_by_url[url].extend(ids)
                salary_map.update(salaries)
                state.vacancy_meta.update(meta)
                for vid, sched_set in schedules.items():
                    if sched_set:
                        schedule_map.setdefault(vid, set()).update(sched_set)

        from app.vacancy_history import observe
        await asyncio.to_thread(observe, state.vacancy_meta)
        return {url: set(ids) for url, ids in results_by_url.items()}, salary_map, schedule_map

    def _process_llm_replies(self, state: AccountState) -> None:
        """Check recent unread negotiations for employer messages and auto-reply using LLM."""
        if not state.llm_enabled:
            return
        # Non-blocking: if another thread is already processing this account, skip
        if not state._llm_lock.acquire(blocking=False):
            log_debug(f"LLM [{state.short}]: уже выполняется, пропуск")
            return
        try:
            try:
                self._process_llm_replies_inner(state)
            finally:
                # Live-статус для UI сбрасываем ВСЕГДА — иначе исключение внутри
                # (fetch_chat_list бросил MobileAPIError и т.п.) оставит UI
                # застрявшим на «обрабатывается 5/15» до следующего успешного
                # цикла. Юзер думает что бот повис.
                state.llm_current_neg_id = ""
                state.llm_current_employer = ""
                state.llm_current_idx = 0
                state.llm_current_total = 0
                state.llm_last_check_at = datetime.now().isoformat(timespec="seconds")
                state.llm_next_check_at = (
                    datetime.now() + timedelta(seconds=max(CONFIG.llm_check_interval * 60, 120))
                ).isoformat(timespec="seconds")
        finally:
            state._llm_lock.release()

    def _process_llm_replies_inner(self, state: AccountState) -> None:
        """Inner implementation — called only when _llm_lock is held."""
        self._bind_mutation_guard(state)
        if not self._can_mutate(state, chat=True):
            return
        replied = 0

        # Sync _llm_no_chat from persisted DB (catches 409 failures from previous sessions)
        state._llm_no_chat.update(get_no_chat_neg_ids())
        # Seed llm_replied_msgs from persisted store ONCE per worker lifetime —
        # повторный merge каждый цикл с обрезкой делал бы trim случайным (set без порядка)
        # и мог выкидывать только что записанные ключи.
        if not getattr(state, "_replied_seeded", False):
            # dict-init: ключи seeded из disk — для них insertion-order не важен (legacy).
            for _k in get_replied_keys():
                state.llm_replied_msgs[_k] = None
            state._replied_seeded = True

        # Memory leak prevention: purge expired temp_skip + cap in-memory sets.
        now_ts = time.time()
        state._llm_temp_skip = {
            k: v for k, v in state._llm_temp_skip.items() if v > now_ts
        }
        if len(state.llm_replied_msgs) > 5000:
            # Hard cap — dict сохраняет insertion order, [-2000:] retains *recent* keys
            # (раньше set делал случайный slice, mid-session re-reply, kimi-r14-2 #11).
            recent = list(state.llm_replied_msgs)[-2000:]
            state.llm_replied_msgs = dict.fromkeys(recent)
        with self._llm_sent_lock:
            if len(self._llm_sent_global) >= 10000:
                # Round-5 #1: раньше `> 10000` создавало boundary trap: ровно
                # на 10000 eviction не запускался, set застревал навсегда если
                # все текущие кандидаты уже в нём (новых add не будет).
                self._llm_sent_global = set(list(self._llm_sent_global)[-5000:])
                # перестраиваем индекс после массовой обрезки
                self._llm_sent_by_neg_id = {}
                for gk in self._llm_sent_global:
                    self._llm_sent_by_neg_id.setdefault(gk[1], set()).add(gk)

        # Fetch recent chat pages sorted by last activity. Chats needing reply
        # (employer just wrote) will always be near the top.
        self._add_log(state.short, state.color, "\U0001f916 LLM: загружаю список чатов…", "info")
        log_debug(f"LLM [{state.short}]: загружаю чат-лист")
        items_by_id, display_info, cur_pid = get_client(state.acc).fetch_chat_list(max_pages=3)
        log_debug(f"LLM [{state.short}]: чат-лист загружен, {len(items_by_id)} чатов")

        # Process items that need a reply: NEGOTIATION type, unread, from employer, not rejection
        candidates = []
        skipped_ours = 0
        skipped_system = 0
        skipped_read = 0
        skipped_locked = 0
        for item_id, item in items_by_id.items():
            if item.get("type") != "NEGOTIATION":
                continue
            unread = item.get("unreadCount", 0)
            last_msg = item.get("lastMessage") or {}
            sender_id = last_msg.get("participantId", "")
            last_text = (last_msg.get("text") or "")[:40]
            wf = last_msg.get("workflowTransition") or {}
            # Аудит 2026-08-17 #27: если cur_pid не определён (пустой ответ
            # /participants от mobile API), раньше from_employer всегда False
            # → чаты с unread=0 от работодателя (ключевой кейс: HR прочитал
            # твоё, ответил, HH сбросил unread) молча пропускались. Без cur_pid
            # достоверно определить нельзя — консервативно считаем sender_id
            # employer'ом (наш ответ всё равно ловится через _llm_sent_global /
            # llm_replied_msgs дедупом на уровне цикла).
            if cur_pid:
                from_employer = bool(sender_id and sender_id != cur_pid)
            else:
                from_employer = bool(sender_id)
            # Early check: known 409 (persisted from DB or current session)
            if item_id in state._llm_no_chat:
                skipped_locked += 1
                log_debug(f"LLM [{state.short}] {item_id}: 409-закрыт, пропуск кандидата")
                continue
            # Early check: HH пометил как DISCARD — нет смысла отвечать, экономим LLM API call.
            if item_id in state.hh_discard_neg_ids:
                skipped_locked += 1
                # Также добавляем в постоянный _llm_no_chat чтобы не проверять каждый цикл.
                state._llm_no_chat.add(item_id)
                log_debug(f"LLM [{state.short}] {item_id}: HH-DISCARD, пропуск кандидата")
                continue
            # Early check: chat locked via text/flags (employer disabled messaging or invite-only)
            if _check_chat_locked(item):
                skipped_locked += 1
                log_debug(f"LLM [{state.short}] {item_id}: чат заблокирован, пропуск кандидата len={len(last_text)}")
                continue
            # Early check: writePossibility from chatik API
            write_poss = (item.get("writePossibility") or {}).get("name", "")
            if write_poss not in ("ENABLED_FOR_ALL", "ENABLED_FOR_ALL_BY_EMPLOYER", ""):
                skipped_locked += 1
                log_debug(f"LLM [{state.short}] {item_id}: writePossibility={write_poss}, пропуск")
                continue
            if unread == 0:
                if from_employer and not wf:
                    last_msg_id_early = str((item.get("lastMessage") or {}).get("id", ""))
                    key_early = (str(item_id), last_msg_id_early)
                    if key_early not in state.llm_replied_msgs:
                        log_debug(f"LLM [{state.short}] {item_id}: unread=0 но от работодателя, не отвечали — добавляю кандидатом: len={len(last_text)}")
                    else:
                        skipped_read += 1
                        di = display_info.get(str(item_id), {})
                        upsert_interview(str(item_id), acc=state.short, acc_color=state.color,
                                         employer=di.get("subtitle", ""), vacancy_title=di.get("title", ""),
                                         chat_status="waiting_hr")
                        log_debug(f"LLM [{state.short}] {item_id}: unread=0, от работодателя, уже отвечали, пропуск: len={len(last_text)}")
                        continue
                else:
                    skipped_read += 1
                    continue
            if cur_pid and sender_id == cur_pid:
                skipped_ours += 1
                log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, последнее наше, пропуск")
                di = display_info.get(str(item_id), {})
                upsert_interview(str(item_id), acc=state.short, acc_color=state.color,
                                 employer=di.get("subtitle", ""), vacancy_title=di.get("title", ""),
                                 chat_status="waiting_hr")
                continue
            if wf:
                wf_id = wf.get("id", "") if isinstance(wf, dict) else ""
                # Аудит 2026-08-17 #26: mobile API возвращает и системные типы
                # ("APPLICATION_ACCEPTED"), и числовые reference ("1234") строкой.
                # Раньше любая непустая строка считалась системным событием и
                # чат пропускался, включая обычные сообщения HR с числовым
                # workflow_transition.id. Пропускаем только НЕ-цифровые строки.
                if isinstance(wf_id, str) and wf_id and not wf_id.isdigit():
                    skipped_system += 1
                    log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, системное событие wf={wf_id!r}, пропуск")
                    continue
                log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, wf.id={wf_id!r} (числовой/int, реальное сообщение)")
            from app.hr_rejection import is_rejection
            if is_rejection(last_msg.get("text")):
                skipped_system += 1
                log_debug(f"LLM [{state.short}] {item_id}: отказ HR, ответ не нужен")
                continue
            # Не флудим логи структурой каждого item — только метаданные кандидата (swarm-16 #8).
            log_debug(f"LLM [{state.short}] {item_id}: ✅ кандидат unread={unread}, sender={sender_id}, len={len(last_text)}")
            candidates.append(item_id)

        log_debug(f"LLM [{state.short}]: {len(candidates)} кандидатов (прочитанных: {skipped_read}, наших: {skipped_ours}, системных: {skipped_system})")
        if not candidates:
            state.llm_pending_chats = 0
            state.llm_current_neg_id = ""
            state.llm_current_employer = ""
            state.llm_current_idx = 0
            state.llm_current_total = 0
            state.llm_last_check_at = datetime.now().isoformat(timespec="seconds")
            state.llm_next_check_at = (
                datetime.now() + timedelta(seconds=max(CONFIG.llm_check_interval * 60, 120))
            ).isoformat(timespec="seconds")
            state.llm_status = f"\U0001f4a4 Нет новых (наших: {skipped_ours}, закр.: {skipped_locked})"
            self._add_log(state.short, state.color,
                f"\U0001f916 LLM: нет новых сообщений (прочит.: {skipped_read}, наших: {skipped_ours}, сист.: {skipped_system}, закрыт: {skipped_locked})", "info")
            return

        # Cap на 15 — LLM цикл ограничен чтобы не сжигать токены за один заход.
        cycle = candidates[:15]
        state.llm_pending_chats = len(candidates)
        state.llm_current_total = len(cycle)
        state.llm_current_idx = 0
        state.llm_current_neg_id = ""
        state.llm_current_employer = ""
        state.llm_status = f"\U0001f504 Обработка {len(cycle)} чатов..."
        self._add_log(state.short, state.color, f"\U0001f916 LLM: {len(candidates)} чатов требуют ответа", "info")

        for i, neg_id in enumerate(cycle):
            if not self._can_mutate(state, chat=True) or not state.llm_enabled or not CONFIG.llm_enabled:
                self._add_log(state.short, state.color, f"\U0001f916 LLM: выключен в процессе цикла, прерываю", "warning")
                break
            # Reset per-iteration: иначе exception на новой итерации видит global_key из ПРЕДЫДУЩЕЙ.
            global_key = None
            try:
                from app.message_quarantine import blocked as chat_blocked
                if chat_blocked(state.acc, neg_id):
                    continue
                if neg_id in state._llm_no_chat:
                    item = items_by_id.get(neg_id, {})
                    info = display_info.get(str(neg_id), {})
                    emp = (info.get("subtitle") or neg_id).strip(" ,")[:25]
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{emp}] \U0001f512 переписка закрыта, пропуск", "warning", neg_id=neg_id)
                    continue

                item = items_by_id.get(neg_id)
                if not item:
                    log_debug(f"LLM [{state.short}] {neg_id}: не найден в items_by_id, пропуск")
                    continue
                thread = _build_thread_from_chat_item(item, display_info, cur_pid, neg_id)
                employer_short = thread.get("employer_name", neg_id)[:25]
                if thread.get("error"):
                    self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] ошибка треда: {thread['error']}", "error", neg_id=neg_id)
                    continue

                employer = thread.get("employer_name", neg_id)[:35]
                employer_msg = thread.get("last_employer_msg", "")
                vacancy_title = thread.get("vacancy_title", "")
                # Live-статус в UI: какой чат сейчас в работе + позиция в цикле.
                # Обновляем ПОСЛЕ построения thread'а — до этого могли выпасть
                # по фильтрам (закрыт/DISCARD/wf) и не считались бы обработанными.
                state.llm_current_idx = i + 1
                state.llm_current_neg_id = str(neg_id)
                state.llm_current_employer = employer
                # vacancy_id из resources чата — нужен фронту чтобы дёрнуть рейтинг
                # работодателя по цепочке vid→employerId→rating (без extra fetch
                # здесь — фронт делает lazy lookup только когда строка видна).
                _vac_resources = (item.get("resources") or {}).get("VACANCY") or []
                vacancy_id = str(_vac_resources[0]) if _vac_resources else ""

                # Pre-filter: chatWritePossibility=DISABLED → LLM-ответ гарантированно
                # отбракуется HH'ом. Не жжём токены, не делаем сетевой вызов.
                # Поле кладётся parse_apply_strategy_meta при сборе search-страницы.
                if vacancy_id:
                    vac_meta = state.vacancy_meta.get(vacancy_id, {})
                    cwp = (vac_meta.get("chat_write_possibility") or "").upper()
                    if cwp == "DISABLED":
                        log_debug(f"LLM [{state.short}] {neg_id}: chatWritePossibility=DISABLED — пропуск (vacancy {vacancy_id})")
                        self._add_log(state.short, state.color,
                            f"\U0001f916 [{employer_short}] \U0001f6ab чат закрыт работодателем (chatWritePossibility=DISABLED), пропуск",
                            "warning", neg_id=neg_id)
                        state._llm_no_chat.add(neg_id)
                        # Аудит 2026-08-17 #21/#28: раньше здесь state.llm_replied_msgs[key] = None,
                        # но `key` создаётся позже (2655) → UnboundLocalError на каждом DISABLED-чате.
                        # _llm_no_chat достаточно: этот neg_id больше в кандидаты не попадёт.
                        continue

                if not thread.get("needs_reply") and not thread.get("chat_locked"):
                    raw_item = items_by_id.get(neg_id, {})
                    raw_unread = raw_item.get("unreadCount", 0)
                    raw_last = raw_item.get("lastMessage") or {}
                    raw_sender = raw_last.get("participantId", "")
                    if raw_unread == 0 and cur_pid and raw_sender and raw_sender != cur_pid:
                        thread["needs_reply"] = True
                        if not employer_msg:
                            employer_msg = (raw_last.get("text") or "").strip()
                            thread["last_employer_msg"] = employer_msg

                if thread.get("chat_locked"):
                    lock_reason = thread["chat_locked"]
                    log_debug(f"LLM [{state.short}] {neg_id}: переписка недоступна — {lock_reason!r}")
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] \U0001f512 переписка недоступна, пропуск", "warning", neg_id=neg_id)
                    state.llm_replied_msgs[(neg_id, "locked")] = None
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color, chat_status="locked")
                    continue

                upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                 employer=employer, vacancy_title=vacancy_title, vacancy_id=vacancy_id,
                                 employer_last_msg=employer_msg if employer_msg else None,
                                 needs_reply=bool(thread.get("needs_reply")))

                if not thread.get("needs_reply"):
                    log_debug(f"LLM [{state.short}] {neg_id}: ответ не нужен (последнее сообщение — от соискателя)")
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color, chat_status="waiting_hr")
                    self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] последнее сообщение наше, пропуск", "info", neg_id=neg_id)
                    continue
                last_msg_id = thread["last_msg_id"]
                key = (neg_id, last_msg_id)
                # Legacy: pre-r1 records без replied_msg_id мечены sentinel '__legacy__'.
                # Если такой sentinel есть — значит мы уже отвечали в этот чат до апгрейда.
                # Пропускаем, не дожидаясь нового HH-сообщения (r13-1 #6).
                if key in state.llm_replied_msgs or (neg_id, "__legacy__") in state.llm_replied_msgs:
                    log_debug(f"LLM [{state.short}] {neg_id}: уже отвечали на msg {last_msg_id}")
                    self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] уже отвечали в этой сессии, пропуск", "info", neg_id=neg_id)
                    continue
                # temp_skip может быть выставлен и под key=(neg_id, last_msg_id), и под
                # (neg_id, "exception") (chat-level backoff после исключения в H6).
                _skip_until = max(
                    state._llm_temp_skip.get(key, 0),
                    state._llm_temp_skip.get((neg_id, "exception"), 0),
                )
                if time.time() < _skip_until:
                    mins = max(1, int((_skip_until - time.time()) / 60))
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] повтор через ~{mins}м (ошибка в предыдущем цикле)", "info", neg_id=neg_id)
                    log_debug(f"LLM [{state.short}] {neg_id}: temp_skip до {_skip_until:.0f}")
                    continue
                global_key = (cur_pid, neg_id, last_msg_id)
                with self._llm_sent_lock:
                    if global_key in self._llm_sent_global:
                        log_debug(f"LLM [{state.short}] {neg_id}: уже отправлено другим аккаунтом (pid={cur_pid})")
                        self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] уже отправлено другим аккаунтом, пропуск", "info")
                        state.llm_replied_msgs[key] = None
                        continue
                from app.hr_rejection import is_stop_request
                if is_stop_request(employer_msg):
                    log_debug(f"LLM [{state.short}] {neg_id}: HR просит не писать — автоответ не отправляем")
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] HR просит больше не писать — автоответ отключён, проверьте чат", "warning", neg_id=neg_id)
                    state.llm_replied_msgs[key] = None
                    continue
                if self._chat_sends_today(state.short, neg_id) >= self.LLM_CHAT_DAILY_REPLY_CAP:
                    log_debug(f"LLM [{state.short}] {neg_id}: дневной лимит автоответов в чате исчерпан")
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] уже {self.LLM_CHAT_DAILY_REPLY_CAP} автоответа сегодня — дальше отвечайте вручную", "warning", neg_id=neg_id)
                    state.llm_replied_msgs[key] = None
                    continue

                progress = f"[{i+1}/{min(len(candidates),15)}]"
                self._add_log(state.short, state.color,
                    f"\U0001f916 {progress} [{employer_short}]: «{employer_msg[:50]}»", "info", neg_id=neg_id)
                log_debug(f"LLM [{state.short}] {progress} {neg_id} ({employer_short}): загружаю историю чата")
                cover_letter = state.acc.get("letter", "") if CONFIG.llm_use_cover_letter else ""
                # Fetch resume for LLM context
                if CONFIG.llm_use_resume:
                    resume_text, _cached = self._resume_for_llm(state)
                    if resume_text:
                        src = "кэш" if _cached else "загружено"
                        self._add_log(state.short, state.color,
                            f"\U0001f916 \U0001f4c4 Резюме в контексте LLM ({src}, {len(resume_text)} симв.)", "info", neg_id=neg_id)
                    else:
                        self._add_log(state.short, state.color,
                            f"\U0001f916 \U0001f4c4 Резюме не удалось загрузить — LLM работает без него", "warning", neg_id=neg_id)
                else:
                    resume_text = ""
                # OAuth-путь когда cookies dead или включён CONFIG.chat_use_oauth —
                # GET /negotiations/{id}/messages не зависит от chatik-кук.
                if state.cookies_expired or CONFIG.chat_use_oauth:
                    full_history = fetch_negotiation_messages_oauth(state.acc, neg_id, max_messages=20)
                    if not full_history:
                        # Fallback на chatik если OAuth ничего не вернул (404 / 403 / token issue)
                        full_history = get_client(state.acc).fetch_chat_history(neg_id, max_messages=20)
                else:
                    full_history = get_client(state.acc).fetch_chat_history(neg_id, max_messages=20)
                conversation = full_history if full_history else thread["messages"]

                _last_emp_raw = None
                if full_history:
                    for msg_raw in reversed(full_history):
                        if msg_raw.get("sender") == "employer":
                            _last_emp_raw = msg_raw
                            break
                _raw_actions = (_last_emp_raw or {}).get("actions") or {}
                _text_buttons = _raw_actions.get("text_buttons", [])
                if _text_buttons and full_history[-1] is not _last_emp_raw:
                    # Something (usually our answer) follows the button message:
                    # pressing again would repeat it. The text path guards "last is ours".
                    _text_buttons = []
                _is_bot_msg = (_last_emp_raw or {}).get("is_bot", False)
                if _text_buttons:
                    # Draft mode covers workflow actions as well as ordinary text.
                    # Never put button captions in the sendable text-draft cache.
                    if not CONFIG.llm_auto_send and key in state._llm_robot_drafts:
                        continue
                    # Умный выбор кнопки: heuristic для очевидных Да/Нет,
                    # LLM-консультация если кнопок 3+ или Да/Нет не определяется.
                    from app.llm import pick_robot_button as _pick_robot_button
                    _btn_idx, btn_text, _btn_source = _pick_robot_button(
                        _text_buttons, conversation, thread.get("employer_name", ""), state.short,
                    )
                    if not btn_text:
                        btn_text = (_text_buttons[0].get("text") if _text_buttons else "ДА") or "ДА"
                    log_debug(
                        f"LLM [{state.short}] {neg_id}: робот-рекрутер, кнопки={[b.get('text') for b in _text_buttons]}, "
                        f"выбрана [{_btn_idx}] '{btn_text}' (src={_btn_source})"
                    )
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] \U0001f916 Робот → '{btn_text}' ({_btn_source})", "info", neg_id=neg_id)
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                     employer=employer_short, vacancy_title=vacancy_title, vacancy_id=vacancy_id,
                                     chat_status="robot")
                    if not CONFIG.llm_auto_send:
                        state._llm_robot_drafts.add(key)
                        self._add_log(state.short, state.color,
                            f"🤖 Черновик кнопки [{employer_short}]: {btn_text}. Не отправлено; подтвердите действие в чате.",
                            "info", neg_id=neg_id)
                        self._push_llm_log({
                            "time": datetime.now().strftime("%d.%m %H:%M"),
                            "acc": state.short, "color": state.color,
                            "employer": employer_short, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "vacancy_id": vacancy_id,
                            "employer_msg": employer_msg,
                            "bot_reply": f"Кнопка: {btn_text} (не отправлено)",
                            "sent": False, "source": "robot_draft",
                        })
                        continue
                    gender_words = conflicting_gender_words(btn_text)
                    if gender_words:
                        self._add_log(state.short, state.color,
                            f"⚠️ [{employer_short}] Кнопка робота не отправлена: род не совпадает с настройкой ({', '.join(gender_words)})",
                            "warning", neg_id=neg_id)
                        state._llm_temp_skip[key] = time.time() + 1800
                        continue
                    # Аудит 2026-08-17 #10: раньше robot-flow отправлял сразу без
                    # резервации global_key → под конкурентными циклами двух
                    # аккаунтов один и тот же workflow_button слался дважды.
                    # Резервируем ДО send, discard при неудаче — как в auto-send.
                    with self._llm_sent_lock:
                        if global_key in self._llm_sent_global:
                            log_debug(f"LLM [{state.short}] {neg_id}: робот-кнопка уже отправлена (pid={cur_pid}), пропуск")
                            state.llm_replied_msgs[key] = None
                            continue
                        self._llm_sent_global.add(global_key)
                    try:
                        _selected_btn = (
                            _text_buttons[_btn_idx]
                            if isinstance(_btn_idx, int) and 0 <= _btn_idx < len(_text_buttons)
                            else _text_buttons[0]
                        )
                        _event = (
                            _selected_btn.get("event")
                            or _selected_btn.get("event_type")
                            or _selected_btn.get("eventType")
                        )
                        _event_params = _selected_btn.get(
                            "event_params", _selected_btn.get("eventParams", {})
                        )
                        if isinstance(_event, dict):
                            _event_params = (
                                _event_params
                                or _event.get("event_params")
                                or _event.get("eventParams")
                                or _event.get("params")
                                or {}
                            )
                            _event = (
                                _event.get("event_type")
                                or _event.get("eventType")
                                or _event.get("type")
                            )
                        _client = get_client({**state.acc, "_message_trigger_id": str(last_msg_id), "_mutation_guard": lambda: self._can_mutate(state, llm=True)})
                        # Settings can change while the picker is running.
                        if not self._can_mutate(state, llm=True):
                            with self._llm_sent_lock:
                                self._llm_sent_global.discard(global_key)
                            continue
                        if _event:
                            ok = _client.send_workflow_event(
                                neg_id, str(_event),
                                _event_params if isinstance(_event_params, dict) else {},
                            )
                        else:
                            ok = _client.send_message(neg_id, btn_text)
                    except Exception:
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                        raise
                    if ok and ok != "chat_not_found":
                        state._llm_robot_drafts.discard(key)
                        state.llm_replied_msgs[key] = None
                        replied += 1
                        # Аудит #22: persist llm_sent+replied_msg_id, чтобы после
                        # рестарта дедуп удержал factor robot-ответы, а не только
                        # in-memory. Без этого перезапуск снова жмёт ту же кнопку.
                        upsert_interview(neg_id, acc=state.short, employer=employer_short,
                                         llm_sent=True, replied_msg_id=str(last_msg_id))
                        ts = datetime.now().strftime("%H:%M")
                        self._push_llm_log({
                            "time": ts, "acc": state.short, "color": state.color,
                            "employer": employer_short, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "vacancy_id": vacancy_id, "employer_msg": employer_msg[:50],
                            "bot_reply": f"\U0001f916 Кнопка: {btn_text}", "sent": True,
                        })
                        self._persist_llm_log({
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "acc": state.short,
                            "neg_id": str(neg_id),
                            "last_msg_id": str(last_msg_id),
                            "employer": employer_short,
                            "reply_len": len(btn_text),
                            "send_ok": True,
                            "source": "robot",
                        })
                    elif ok == "chat_not_found":
                        state._llm_no_chat.add(neg_id)
                        state.llm_replied_msgs[key] = None
                        log_debug(f"LLM [{state.short}] {neg_id}: робот-кнопка 409, чат закрыт — добавлен в _llm_no_chat")
                    elif not ok:
                        # Отправка не удалась — отпускаем резервацию, чтобы
                        # следующий цикл смог попробовать снова.
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                        state._llm_temp_skip[key] = time.time() + 1800
                    continue

                has_employer_msg = any(m.get("sender") == "employer" for m in conversation)
                last_real_sender = conversation[-1].get("sender") if conversation else None
                if not has_employer_msg:
                    log_debug(f"LLM [{state.short}] {neg_id}: нет реальных сообщений работодателя (только системные), пропуск")
                    state.llm_replied_msgs[key] = None
                    continue
                if last_real_sender == "applicant":
                    log_debug(f"LLM [{state.short}] {neg_id}: последнее реальное сообщение наше — уже ответили, пропуск")
                    state.llm_replied_msgs[key] = None
                    continue
                _consecutive_ours = 0
                for _cm in reversed(conversation):
                    if _cm.get("sender") == "applicant":
                        _consecutive_ours += 1
                    else:
                        break
                state._msg_consecutive[neg_id] = _consecutive_ours
                if _consecutive_ours >= 4:
                    log_debug(f"LLM [{state.short}] {neg_id}: in_a_row_limit: {_consecutive_ours} сообщений без ответа HR, пропуск")
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] ⚠️ in_a_row_limit: {_consecutive_ours} сообщения без ответа HR, пропуск", "warning", neg_id=neg_id)
                    state.llm_replied_msgs[key] = None
                    continue
                # Если для этого (neg_id, last_msg_id) уже есть кэшированный черновик
                # с прошлого цикла (auto_send был выкл) — используем его, чтобы не жечь
                # токены заново. Если auto_send всё ещё False — вообще скипаем без
                # перегенерации (черновик уже сохранён в llm_log и interviews DB).
                with state._llm_drafts_lock:
                    cached_draft = state._llm_drafts.get(key)
                if cached_draft and not CONFIG.llm_auto_send:
                    log_debug(f"LLM [{state.short}] {neg_id}: уже есть черновик в кэше, auto_send выкл — пропуск")
                    continue
                reply_source = "llm"
                if cached_draft and CONFIG.llm_auto_send:
                    log_debug(f"LLM [{state.short}] {neg_id}: отправляю кэшированный черновик ({len(cached_draft)} симв.)")
                    reply_text = cached_draft
                    reply_source = "cached"
                else:
                    reply_text = ""
                    hr_last = (employer_msg or "").strip()
                    # Есть ли у нас свой LLM? Если да — идёт первым (даёт
                    # контекстный ответ). quick_replies HH — шаблонные подсказки,
                    # часто не в тему (могут ответить "готов работать в гибком
                    # графике" на "можем созвониться?"). Только fallback.
                    _has_own_llm = bool(
                        (CONFIG.llm_api_key or "").strip()
                        or any(p.get("api_key") for p in (CONFIG.llm_profiles or []) if p.get("enabled", True))
                        or (getattr(CONFIG, "llm_openclaw_enabled", False))
                    )
                    if not _has_own_llm and getattr(CONFIG, "llm_use_quick_replies", True):
                        # Своего LLM нет — берём quick_replies с умным ranking.
                        qr = get_client(state.acc).fetch_quick_replies(neg_id, last_msg_id)
                        if qr:
                            is_question = "?" in hr_last
                            _greet = ("здравствуйте", "добрый день", "добрый вечер", "приветствую")
                            def _score(s):
                                s_low = s.strip().lower()
                                is_greet = len(s) < 25 and any(g in s_low for g in _greet)
                                return (0 if (is_question and is_greet) else 1, len(s))
                            best = max(qr, key=_score)
                            _min_ok = 20 if is_question else 5
                            if len(best) >= _min_ok:
                                reply_text = best
                                reply_source = "quick_reply"
                                log_debug(f"LLM [{state.short}] {neg_id}: quick_replies {len(qr)} вариантов (LLM нет), взял '{reply_text[:40]}…'")
                                self._add_log(state.short, state.color,
                                    f"\U0001f4a1 {progress} [{employer_short}]: HH-quick_reply (LLM недоступен)", "info", neg_id=neg_id)
                    if not reply_text:
                        log_debug(f"LLM [{state.short}] {neg_id}: история {len(conversation)} сообщений, резюме {len(resume_text)} симв., отправляю в LLM")
                        self._add_log(state.short, state.color,
                            f"\U0001f916 {progress} [{employer_short}]: история {len(conversation)} сообщ., жду LLM…", "info", neg_id=neg_id)
                        ai_hint = bool(state.vacancy_meta.get(vacancy_id, {}).get("ai_assistant_enabled"))
                        reply_text = generate_llm_reply(
                            conversation,
                            thread.get("employer_name", ""),
                            cover_letter,
                            resume_text,
                            account_key=f"{state.short}:{neg_id}",
                            ai_screener_hint=ai_hint,
                        )
                        reply_source = "llm"
                    if not reply_text and _has_own_llm and getattr(CONFIG, "llm_use_quick_replies", True):
                        # LLM молчит (rate-limit / down) — попробуем quick_replies как последний резерв.
                        qr = get_client(state.acc).fetch_quick_replies(neg_id, last_msg_id)
                        if qr:
                            is_question = "?" in hr_last
                            _greet = ("здравствуйте", "добрый день", "добрый вечер", "приветствую")
                            def _score2(s):
                                s_low = s.strip().lower()
                                is_greet = len(s) < 25 and any(g in s_low for g in _greet)
                                return (0 if (is_question and is_greet) else 1, len(s))
                            best = max(qr, key=_score2)
                            if len(best) >= (20 if is_question else 5):
                                reply_text = best
                                reply_source = "quick_reply_fallback"
                                log_debug(f"LLM [{state.short}] {neg_id}: LLM молчит, взял quick_reply '{reply_text[:40]}…'")
                    if not reply_text:
                        llm_status = get_llm_last_status(f"{state.short}:{neg_id}", "reply")
                        if llm_status.get("provider") == "openclaw" and llm_status.get("status") == "timeout":
                            self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] OpenClaw timeout, повтор через 30м", "warning", neg_id=neg_id)
                        else:
                            self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] LLM не дал ответ, повтор через 30м", "warning", neg_id=neg_id)
                        log_debug(f"LLM [{state.short}] {neg_id}: пустой ответ от LLM, ставим temp_skip 30м")
                        empties = state.__dict__.setdefault("_llm_empty_replies", {})
                        empties[key] = empties.get(key, 0) + 1
                        if empties[key] >= 3:
                            # Regenerating forever only burns tokens; a human should answer this one.
                            state.llm_replied_msgs[key] = None
                            self._add_log(state.short, state.color,
                                f"\U0001f916 [{employer_short}] LLM 3 раза не смог ответить — ответьте вручную", "warning", neg_id=neg_id)
                            continue
                        state._llm_temp_skip[key] = time.time() + 1800
                        continue
                    gender_words = conflicting_gender_words(reply_text)
                    if gender_words:
                        self._add_log(state.short, state.color,
                            f"⚠️ [{employer_short}] Ответ не отправлен: род не совпадает с настройкой ({', '.join(gender_words)})",
                            "warning", neg_id=neg_id)
                        state._llm_temp_skip[key] = time.time() + 1800
                        continue
                    log_debug(f"LLM [{state.short}] {neg_id}: ответ получен ({len(reply_text)} симв.), отправляю")

                ts = datetime.now().strftime("%d.%m %H:%M")

                if CONFIG.llm_auto_send:
                    with self._llm_sent_lock:
                        if global_key in self._llm_sent_global:
                            log_debug(f"LLM [{state.short}] {neg_id}: другой поток уже отправил (pid={cur_pid}), пропуск")
                            self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] другой аккаунт уже отправил, пропуск", "info")
                            state.llm_replied_msgs[key] = None
                            continue
                        self._llm_sent_global.add(global_key)
                        self._llm_sent_by_neg_id.setdefault(neg_id, set()).add(global_key)
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] отправляю: «{reply_text[:60]}»", "info", neg_id=neg_id)
                    # Имитация человека: «читает» → галочка «прочитано» → «думает» →
                    # «печатает…» (пульсы, время от длины ответа). Прерывается стопом/паузой;
                    # при прерывании проверка _can_mutate ниже снимает typing и не шлёт.
                    chat_humanize.simulate(
                        get_client(state.acc), neg_id, last_msg_id, employer_msg, reply_text,
                        sleep=self._stop_event.wait,
                        can_continue=lambda: self._can_mutate(state, llm=True))
                    if not self._can_mutate(state, llm=True):
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                            self._llm_sent_by_neg_id.get(neg_id, set()).discard(global_key)
                        with state._llm_drafts_lock:
                            state._llm_drafts[key] = reply_text
                        try:
                            get_client(state.acc).send_participant_action(neg_id, "NONE")
                        except Exception:
                            pass
                        continue
                    log_debug(f"LLM [{state.short}] {neg_id}: отправляю сообщение в chatik")
                    sender = get_client({**state.acc, "_message_trigger_id": str(last_msg_id), "_mutation_guard": lambda: self._can_mutate(state, llm=True)})
                    if not self._can_mutate(state, llm=True):
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                        continue
                    ok = sender.send_message(neg_id, reply_text, topic_id=thread.get("topic_id", ""))
                    try:
                        get_client(state.acc).send_participant_action(neg_id, "NONE")
                    except Exception:
                        pass
                    if ok == "chat_not_found":
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                            self._llm_sent_by_neg_id.get(neg_id, set()).discard(global_key)
                        state.llm_replied_msgs[key] = None
                        state._llm_no_chat.add(neg_id)
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         employer=employer, vacancy_title=vacancy_title, vacancy_id=vacancy_id,
                                         chat_not_found=True)
                        self._add_log(state.short, state.color,
                            f"\U0001f916 [{employer_short}] \U0001f512 переписка закрыта (409), пропуск", "warning", neg_id=neg_id)
                        continue
                    if ok:
                        state.llm_replied_msgs[key] = None
                        with state._llm_drafts_lock:
                            state._llm_drafts.pop(key, None)  # отправили — кэш не нужен
                        state._msg_consecutive[neg_id] = state._msg_consecutive.get(neg_id, 0) + 1
                        state._llm_neg_failures.pop(neg_id, None)  # clear backoff on success
                        state.__dict__.get("_llm_send_fails", {}).pop(key, None)
                        replied += 1
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         llm_reply=reply_text, llm_sent=True,
                                         replied_msg_id=last_msg_id)
                        self._add_log(state.short, state.color,
                            f"\U0001f916 Авто-ответ → {employer}: {reply_text[:60]}…", "success", neg_id=neg_id)
                        self._push_llm_log({
                            "time": ts, "acc": state.short, "color": state.color,
                            "employer": employer, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "vacancy_id": vacancy_id, "employer_msg": employer_msg,
                            "bot_reply": reply_text, "sent": True, "source": reply_source,
                        })
                        self._persist_llm_log({
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "acc": state.short,
                            "neg_id": str(neg_id),
                            "last_msg_id": str(last_msg_id),
                            "employer": employer,
                            "reply_len": len(reply_text),
                            "send_ok": True,
                            "source": reply_source,
                        })
                    else:
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                            self._llm_sent_by_neg_id.get(neg_id, set()).discard(global_key)
                        # Перманентно отвергаемый чат (HTTP 400: бот-работодатель, закрыто) иначе
                        # крутился бы каждые 30 мин вечно: LLM-вызов + запросы в HH на каждый круг.
                        _fails = state.__dict__.setdefault("_llm_send_fails", {})
                        _fails[key] = _fails.get(key, 0) + 1
                        state._llm_temp_skip[key] = time.time() + (1800, 7200, 21600, 86400)[min(_fails[key] - 1, 3)]
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         llm_reply=reply_text, llm_sent=False)
                        self._add_log(state.short, state.color,
                            f"\U0001f916 Черновик (ошибка отправки, повтор ~30м) → {employer}: {reply_text[:60]}…", "warning", neg_id=neg_id)
                        self._push_llm_log({
                            "time": ts, "acc": state.short, "color": state.color,
                            "employer": employer, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "vacancy_id": vacancy_id, "employer_msg": employer_msg,
                            "bot_reply": reply_text, "sent": False,
                        })
                        self._persist_llm_log({
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "acc": state.short,
                            "neg_id": str(neg_id),
                            "last_msg_id": str(last_msg_id),
                            "employer": employer,
                            "reply_len": len(reply_text),
                            "send_ok": False,
                            "source": "draft_error",
                        })
                else:
                    # auto_send=False — сохраняем черновик в кэш чтобы при включении
                    # auto_send отправить без повторного LLM-вызова.
                    with state._llm_drafts_lock:
                        state._llm_drafts[key] = reply_text
                    # НЕ помечаем llm_replied_msgs[key]=None — иначе при флипе auto_send
                    # бот посчитает чат «уже обработан» и пропустит. Без этой метки
                    # следующий цикл увидит чат, найдёт черновик в кэше и (если
                    # auto_send=True) отправит.
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                     llm_reply=reply_text, llm_sent=False)
                    self._add_log(state.short, state.color,
                        f"\U0001f916 Черновик [{employer}] (вкл «Автоотправку» → отправлю): {reply_text[:60]}…", "info", neg_id=neg_id)
                    self._push_llm_log({
                        "time": ts, "acc": state.short, "color": state.color,
                        "employer": employer, "vacancy_title": vacancy_title,
                        "neg_id": neg_id, "vacancy_id": vacancy_id, "employer_msg": employer_msg,
                        "bot_reply": reply_text, "sent": False,
                    })
                    self._persist_llm_log({
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "acc": state.short,
                        "neg_id": str(neg_id),
                        "last_msg_id": str(last_msg_id),
                        "employer": employer,
                        "reply_len": len(reply_text),
                        "send_ok": False,
                        "source": "draft_manual",
                    })

                time.sleep(3)  # rate limit between messages
            except Exception as e:
                if getattr(e, "outcome_unknown", False):
                    from app.message_quarantine import retain as retain_chat
                    try:
                        retain_chat(state.acc, neg_id)
                        self._add_log(state.short, state.color,
                            "Результат сообщения неизвестен: этот чат изолирован без повторной отправки. Другие чаты и отклики продолжаются.",
                            "warning", neg_id=neg_id)
                    except Exception:
                        # A failed durable exclusion must still stop all writes.
                        state.paused = True
                        if not state.pending_apply:
                            state.paused_reason = "message_outcome_unknown"
                        state.status_detail = "Не удалось сохранить блокировку чата; нужна ручная проверка"
                        self._persist_pauses()
                        self._add_log(state.short, state.color, state.status_detail, "warning", neg_id=neg_id)
                log_exception(f"_process_llm_replies {neg_id}", e)
                try:
                    # Чистим только текущий global_key. На иммедиатных exception'ах
                    # (до reserve блока) он = None — ничего не трогаем.
                    if global_key is not None:
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                            bucket = self._llm_sent_by_neg_id.get(neg_id)
                            if bucket is not None:
                                bucket.discard(global_key)
                                if not bucket:
                                    self._llm_sent_by_neg_id.pop(neg_id, None)
                except Exception:
                    pass
                # Backoff at chat-level: предотвращает бесконечный retry перманентной ошибки.
                # 1 ошибка → 5 мин, 2 → 15 мин, 3-5 → 1 час, после 5 → 24 часа (но не permanent —
                # _llm_no_chat зарезервирован под реальный 409, чтобы не путать).
                fail_count = state._llm_neg_failures.get(neg_id, 0) + 1
                state._llm_neg_failures[neg_id] = fail_count
                backoff = {1: 300, 2: 900, 3: 3600, 4: 3600, 5: 3600}.get(fail_count, 86400)
                state._llm_temp_skip[(neg_id, "exception")] = time.time() + backoff
            finally:
                state.llm_pending_chats = max(0, state.llm_pending_chats - 1)

        state.llm_replied_count += replied
        if not replied:
            # Leftover candidates of a cycle that sent nothing are skip-only chats;
            # a fast re-cycle would just re-poll /chats every few seconds.
            state.llm_pending_chats = 0
        if replied:
            state.llm_status = f"✅ {replied} ответов отправлено"
            log_debug(f"LLM auto-reply [{state.short}]: {replied} ответов отправлено")
        elif candidates:
            state.llm_status = f"⏳ {len(candidates)} чатов, 0 отправлено"
        # Цикл завершён — сбрасываем «текущий чат» и ставим таймеры для UI.
        state.llm_current_neg_id = ""
        state.llm_current_employer = ""
        state.llm_current_idx = 0
        state.llm_current_total = 0
        state.llm_last_check_at = datetime.now().isoformat(timespec="seconds")
        state.llm_next_check_at = (
            datetime.now() + timedelta(seconds=max(CONFIG.llm_check_interval * 60, 120))
        ).isoformat(timespec="seconds")

    def _fetch_hh_stats_worker(self, idx: int, state: AccountState) -> None:
        """Thread worker for HH stats polling — auto-restarts on crash.

        Без этого цикла один краш парсинга / network exception → у аккаунта
        НАВСЕГДА выключаются stats + LLM до перезапуска процесса (swarm-1 critical).
        """
        while not self._stop_event.is_set() and not getattr(state, "_deleted", False):
            try:
                self._fetch_hh_stats_worker_inner(idx, state)
                return  # inner вышел нормально (stop_event / _deleted) — выходим из restart-loop
            except Exception as e:
                log_exception(f"STATS WORKER CRASHED [{state.short}]", e)
                self._add_log(
                    state.short, state.color,
                    f"⚠️ Stats worker упал: {str(e)[:80]} — рестарт через 30с",
                    "error",
                )
                # Используем wait вместо sleep, чтобы shutdown будил быстро.
                if self._stop_event.wait(30):
                    return

    def _fetch_hh_stats_worker_inner(self, idx: int, state: AccountState) -> None:
        while not self._stop_event.is_set():
            # state.paused тоже учитываем — иначе paused account продолжает hammer HH APIs (swarm-12 #7).
            while (
                (self.paused or state.paused or getattr(state, "hard_stopped", False))
                and not self._stop_event.is_set()
                and not getattr(state, "_deleted", False)
            ):
                if self._stop_event.wait(2):
                    return
            if self._stop_event.is_set() or getattr(state, '_deleted', False):
                break

            state.hh_stats_loading = True
            # Parallel — resume status через OAuth (5-min cache, дешёвый запрос)
            try:
                rs = fetch_resume_status(state.acc)
                if rs:
                    state.resume_status = rs
            except Exception as e:
                log_debug(f"resume_status fetch error [{state.short}]: {e}")
            try:
                stats = get_client(state.acc).fetch_negotiations()
                if stats.get("auth_error"):
                    log_debug(f"AUTH_ERROR [{state.short}] vid=- flow=stats")
                    state.cookies_expired = True
                    notify_account_state_change(state, AlertCategory.account_blocked)
                    self._add_log(
                        state.short, state.color,
                        "⚠️ Куки протухли! (HH stats) Обновите куки.", "error",
                    )
                    state.hh_stats_loading = False
                    self._stop_event.wait(max(CONFIG.llm_check_interval * 60, 120))
                    continue
                old_interviews = state.hh_interviews
                state.hh_interviews = stats["interview"]
                state.hh_interviews_recent = stats["recent_interview"]
                state.hh_viewed = stats["viewed"]
                state.hh_not_viewed = stats["not_viewed"]
                state.hh_discards = stats["discard"]
                state.hh_interviews_list = stats["interviews_list"]
                state.hh_interview_neg_ids = stats.get("neg_ids", [])
                state.hh_discard_neg_ids = set(str(x) for x in stats.get("discard_neg_ids", []))
                state.hh_unread_by_employer = stats.get("unread_by_employer", 0)

                self._notify_new_interviews(state, stats["interviews_list"])
                self._start_telegram_message_scan(state)

                for neg_id in state.hh_interview_neg_ids:
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color)
                if len(state.hh_interview_neg_ids) == len(stats["interviews_list"]):
                    for neg_id, item in zip(state.hh_interview_neg_ids, stats["interviews_list"]):
                        parts = item.get("text", "").rsplit(" ", 1)
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         vacancy_title=item.get("text", ""))

                offers = get_client(state.acc).fetch_possible_offers()
                state.hh_possible_offers = offers

                was_touch_available = state.resume_free_touches > 0
                rs = get_client(state.acc).fetch_stats()
                state.resume_views_7d = rs["views"]
                state.resume_views_new = rs["views_new"]
                state.resume_shows_7d = rs["shows"]
                state.resume_invitations_7d = rs["invitations"]
                state.resume_invitations_new = rs["invitations_new"]
                state.resume_next_touch_seconds = rs["next_touch_seconds"]
                state.resume_free_touches = rs["free_touches"]
                # `resume_free_touches` и `next_resume_touch` раньше были двумя
                # независимыми состояниями. Если HH только что сообщил, что
                # публикация снова доступна, старый четырёхчасовой schedule не
                # должен удерживать автоматический подъём.
                if (
                    state.resume_touch_enabled
                    and not was_touch_available
                    and state.resume_free_touches > 0
                ):
                    state.next_resume_touch = datetime.now()
                    state.resume_touch_status = "🚀 Поднятие доступно"
                state.resume_global_invitations = rs["global_invitations"]
                state.resume_new_invitations_total = rs["new_invitations_total"]

                state.resume_view_history = get_client(state.acc).fetch_resume_view_history(limit=100)

                state.hh_stats_updated = datetime.now()

                if old_interviews > 0 and stats["interview"] > old_interviews:
                    new_count = stats["interview"] - old_interviews
                    self._add_log(
                        state.short, state.color,
                        f"\U0001f3af НОВОЕ ПРИГЛАШЕНИЕ! (+{new_count} интервью)",
                        "success",
                    )

                log_debug(
                    f"HH stats {state.short}: {stats['interview']} интервью, "
                    f"{rs['views']} просмотров резюме, {rs['new_invitations_total']} новых инвайтов"
                )

                # HH-лимит applies только к НОВЫМ откликам, не к ответам в
                # существующих чатах. Так что limit-пауза НЕ должна стопать LLM.
                # Стопаем только на manual паузу или auth (куки протухли — LLM
                # всё равно не отправит).
                _llm_skip = self.paused or (state.paused and state.paused_reason in ("manual", "auth"))
                if _llm_skip:
                    log_debug(f"LLM [{state.short}]: пропуск — на паузе (reason={state.paused_reason or 'global'})")
                    state.hh_stats_loading = False
                    if self._stop_event.wait(max(CONFIG.llm_check_interval * 60, 120)):
                        return
                    continue

                _has_llm = (CONFIG.llm_api_key or "").strip() or any(
                    p.get("api_key") for p in (CONFIG.llm_profiles or []) if p.get("enabled", True)
                ) or (getattr(CONFIG, "llm_openclaw_enabled", False) and bool(_openclaw_command()))
                _neg_count = len(state.hh_interview_neg_ids)
                if not CONFIG.llm_enabled:
                    log_debug(f"LLM [{state.short}]: пропуск — глобально выключено")
                elif not _has_llm:
                    self._add_log(state.short, state.color, "\U0001f916 LLM: не настроен ни API, ни OpenClaw", "warning")
                elif not state.llm_enabled:
                    log_debug(f"LLM [{state.short}]: пропуск — выключено для аккаунта")
                else:
                    if _neg_count:
                        self._add_log(state.short, state.color, f"\U0001f916 LLM: проверяю {_neg_count} переговоров…", "info")
                    else:
                        self._add_log(state.short, state.color, "\U0001f916 LLM: нет переговоров в статусе Интервью, проверяю чаты…", "info")
                    self._process_llm_replies(state)
            except Exception as e:
                log_exception(f"HH stats fetch error ({state.short})", e)
            finally:
                state.hh_stats_loading = False

            # Back-to-back cycles когда backlog большой: если после цикла
            # осталось pending > 15 (per-cycle cap), нет смысла спать полный
            # интервал — HR-ответы задерживаются часами. Спим короткое время
            # чтобы дать HH подышать, но не полный 2-минутный wait.
            pending = getattr(state, "llm_pending_chats", 0) or 0
            if pending > 15:
                if self._stop_event.wait(60):  # короткая пауза между back-to-back
                    return
            else:
                if self._stop_event.wait(max(CONFIG.llm_check_interval * 60, 120)):
                    return

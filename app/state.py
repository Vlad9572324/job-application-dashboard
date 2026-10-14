"""
AccountState — per-account state object for the bot.
"""

import random
import copy
import threading
from datetime import datetime, timedelta
from collections import deque

from app.config import CONFIG
from app.storage import count_applied_on_day, get_questionnaire_rejection_counts
from app.account_activity import initial_activity


class AccountState:
    """Полное состояние аккаунта"""

    def __init__(self, acc_data: dict):
        self.acc = acc_data
        self._last_captcha_at = max(float(acc_data.get("_last_captcha_at") or 0),
                                    float(acc_data.get("last_captcha_at") or 0))
        acc_data["_last_captcha_at"] = self._last_captcha_at
        self._human_burst_count = 0
        self._human_burst_target = 0
        self._human_burst_started = 0.0
        # Прокидываем cookies_lock в acc, чтобы hh_chat / hh_apply могли
        # сериализовать мутации acc["cookies"] (defensive — см. _ensure_chatik_cookies).
        # Сам lock создаётся ниже как self._cookies_lock; ставим shared reference.
        # Делаем это сразу до использования self чтобы AccountState видна.
        self.name = acc_data["name"]
        self.short = acc_data["short"]
        self.color = acc_data["color"]

        self.status = "idle"
        self.status_detail = ""
        self.activity = initial_activity()
        self.activity_pause_started_at = None
        self.receipt_check_started_at = None
        self._reconcile_persistence_failed = False
        # Per-cycle observations are deliberately not restored from day totals.
        self._cycle_report = None
        self._cycle_universe = None
        self._cycle_considered = set()
        self._cycle_outcomes = {}
        self._cycle_questionnaires = set()

        self.sent = 0
        self.tests = 0
        self.errors = 0
        self.already_applied = 0
        self.found_vacancies = 0
        # ISO datetime последнего УСПЕШНОГО отклика (result=='sent') — для UI
        # «удачный отклик: 14:23, 5м назад».
        self.last_apply_at: str = ""
        # ISO datetime последней ПОПЫТКИ отклика (любой result: sent/test/
        # already/limit/error). Используется чтоб видеть «бот вообще что-то
        # пробовал» когда last_apply_at пустой / далеко в прошлом.
        self.last_apply_attempt_at: str = ""

        self.total_urls = len(acc_data["urls"])

        self.current_vacancy_title = ""
        self.current_vacancy_id = ""
        self.current_vacancy_company = ""
        self.current_vacancy_idx = 0
        self.total_vacancies = 0

        self.vacancies_by_url = {}
        self.vacancies_queue = []

        self.limit_exceeded = acc_data.get("limit_exceeded") is True
        self.limit_reset_time = None

        self.use_oauth = bool(acc_data.get("use_oauth", False))  # per-account OAuth toggle
        self.oauth_status = ""  # "active", "no_token", "error"

        # daily_date — дата сброса счётчика. Использует MSK (как и
        # _maybe_roll_daily_counter), иначе после restart в Docker (UTC) поля
        # рассинхронизированы и rollover не срабатывает в полночь по Москве.
        try:
            from zoneinfo import ZoneInfo
            self.daily_date = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")
        except Exception:
            self.daily_date = datetime.now().strftime("%Y-%m-%d")
        # Count today's applies from persisted cache
        self.daily_sent = 0
        try:
            self.daily_sent = count_applied_on_day(self.name, self.daily_date)
        except Exception:
            pass
        self.hard_stopped = acc_data.get("hard_stopped") is True

        self.resume_touch_enabled = True
        # Startup jitter: первый touch отсрочен на 0-120s, чтобы 100 аккаунтов
        # не ударили hh.ru/oauth/token одновременно (kimi-r13-2 #7, r13-3 #10).
        self.next_resume_touch = datetime.now() + timedelta(seconds=random.uniform(0, 120))
        self.resume_touch_status = ""
        # active_search принудительно проставляем один раз за жизнь worker'а —
        # HR-фильтр «готов сразу» отсекает всех без него.
        self._active_search_forced = False
        # HH-геймификация: сколько откликов сделали в текущей streak-серии + сколько
        # нужно для бейджа «часто отвечает». Обновляется _hh_limit_tracker_worker
        # раз в 30 мин через api.hh.ru/negotiations_statistic/mine.
        self.responses_streak_count = 0
        self.responses_streak_required = 0



        self.action_history = deque(maxlen=20)
        self.recent_responses = deque(maxlen=10)

        self.salary_skipped = 0       # Пропущено из-за зарплаты
        self.vacancy_meta = {}        # {vid: {title, company}} из HTML поиска
        self.questionnaire_sent = 0   # Успешно пройдено опросов
        self.fresh_reserved_skipped = 0  # старые вакансии, отложенные ради резерва

        self.hh_interviews = 0
        self.hh_interviews_recent = 0  # за последние 60 дней
        self.hh_viewed = 0
        self.hh_not_viewed = 0
        self.hh_discards = 0
        self.hh_interviews_list = []
        self.hh_possible_offers = []
        self.hh_stats_updated = None
        self.hh_stats_loading = False
        self.hh_unread_by_employer = 0  # count of negotiations where employer hasn't read our messages

        # Resume statistics
        self.resume_views_7d = 0
        self.resume_views_new = 0
        self.resume_shows_7d = 0
        self.resume_invitations_7d = 0
        self.resume_invitations_new = 0
        self.resume_next_touch_seconds = 0
        self.resume_free_touches = 0
        self.resume_global_invitations = 0
        self.resume_new_invitations_total = 0

        # Resume view history
        self.resume_view_history: list = []   # [{employer_id, name, date, vacancy}]

        # Per-account pause (new for web dashboard)
        self.paused = acc_data.get("paused") is True
        self._deleted = False  # Set True to stop worker thread

        # Per-account event log (last 8 events shown on card)
        self.acc_event_log: deque = deque(maxlen=8)
        # Skip vacancies that require tests
        self.apply_tests: bool = bool(acc_data.get("apply_tests", False))
        self.safety_enabled: bool = bool(
            acc_data.get("safety_enabled", CONFIG.skip_inconsistent)
        )
        self.safety_inconsistent_skipped: int = 0
        self.safety_misleading_skipped: int = 0
        self.safety_redirect_skipped: int = 0
        self.safety_last_reason: str = ""
        # Consecutive errors counter for auto-pause
        self.consecutive_errors: int = 0
        # Per-URL vacancy counts from last collection cycle
        self.url_stats: dict = {}
        # Per-account per-URL pages override {url: pages}
        # (overrides global pool pages for this account)
        # stored in acc["url_pages"]
        # Cookie expiry flag — set when 401/403 or login redirect detected
        self.cookies_expired: bool = False
        # Degraded mode: cookies dead, но OAuth token живой → продолжаем
        # работать через api.hh.ru (поиск + отклик + чат). Опросники / тесты
        # недоступны — такие вакансии отфильтровываются.
        self.degraded_mode: bool = False
        # Stats для UI: счётчик пропусков вакансий из-за has_test/letter_required
        # в degraded mode (не можем заполнить опросник без cookies).
        self.degraded_skipped: int = 0
        # Per-account toggle. Default True: при cookies_expired автоматически
        # уходим в OAuth-режим. False → классическая пауза до обновления кук.
        self.degraded_fallback_enabled: bool = bool(
            acc_data.get("degraded_fallback_enabled", True)
        )
        # Resume status via OAuth API — обновляется stats worker'ом
        self.resume_status: dict = {}
        # Favorited vacancy ids — установлен collection-фазой для приоритизации
        self._favorited_ids: set = set()
        # Сколько вакансий пропущено по employer rating-фильтру в этом цикле
        self.rating_skipped: int = 0
        # Реальное число сегодняшних откликов из HH (через OAuth-counter).
        # 0 пока счётчик не вернул значение. Используется как источник истины
        # для лимит-логики вместо локального daily_sent.
        self.hh_today_applies: int = 0
        self.hh_today_applies_updated: str = ""  # ISO timestamp последнего refresh

        # LLM auto-reply tracking — dict (not set) для insertion-order eviction:
        # set.list() возвращал произвольный порядок, [-2000:] вырезал случайные ключи →
        # mid-session re-reply на recent чаты (kimi-r14-2 #11). Dict preserves order with O(1) lookup.
        # Keys are tuples (neg_id, last_msg_id); values unused (None).
        self.llm_replied_msgs: dict = {}
        self._llm_temp_skip: dict = {}       # {(neg_id, last_msg_id): expiry_ts} — transient failure, retry after TTL
        self._llm_no_chat: set = set()       # {neg_id} chats that returned 409 (permanently closed/locked)
        self._llm_drafts: dict = {}          # {(neg_id, last_msg_id): reply_text} — кэш сгенерированных черновиков
        self._llm_robot_drafts: set = set()  # Separate from sendable text drafts: workflow buttons are actions.
        self._llm_drafts_lock = threading.Lock()  # WS-поток edit-invalidate vs LLM-поток write — гоняются
                                              # на сессию воркера. Если auto_send позже включится — отправляем
                                              # сохранённый текст без повторного LLM-вызова. Сбрасывается
                                              # вместе с llm_replied_msgs через "🔄 Сбросить историю".
        self._llm_neg_failures: dict = {}    # {neg_id: count} — exception-counter for exponential backoff
        self.hh_interview_neg_ids: list = [] # negotiation IDs from last INTERVIEW fetch
        self.hh_discard_neg_ids: set = set() # negotiation IDs HH marked as DISCARD — пропускаем в LLM до вызова API
        self.llm_enabled: bool = True        # per-account LLM toggle (overridden by global CONFIG.llm_enabled)
        self.llm_status: str = ""            # human-readable LLM status for dashboard display
        self.llm_replied_count: int = 0      # total replies sent this session
        self.llm_pending_chats: int = 0      # chats awaiting reply (from last scan)
        # Live-статус LLM-цикла для UI: какой чат прямо сейчас обрабатывается
        # и когда закончился/запланирован следующий проход. Раньше UI видел
        # только summary («N чатов требуют ответа») и юзер не понимал что
        # происходит между двумя циклами.
        self.llm_current_neg_id: str = ""    # neg_id чата, который в этот момент отправляется в LLM
        self.llm_current_employer: str = ""  # employer чата, для человекочитаемого label
        self.llm_current_idx: int = 0        # позиция в текущем цикле (1..N)
        self.llm_current_total: int = 0      # длина текущего цикла (N)
        self.llm_last_check_at: str = ""     # ISO-timestamp конца последнего цикла (для «X сек назад»)
        self.llm_next_check_at: str = ""     # ISO-timestamp когда стартует следующий цикл
        self._llm_lock = threading.Lock()    # prevents concurrent _process_llm_replies for this account
        # Polling and WebSocket events may ask to scan chats at the same time.
        self._telegram_notify_lock = threading.Lock()
        self._msg_consecutive: dict = {}     # {neg_id: count} consecutive applicant messages without HR reply
        self._test_failures: dict = get_questionnaire_rejection_counts(self.name)
        self._visibility_blocked_until: dict[str, float] = {}

        # Защита deques от race с broadcast loop (list(deque) при concurrent appendleft → RuntimeError).
        # Используется в _add_log/_add_response/_add_acc_event + snapshot reader.
        self._deque_lock = threading.Lock()
        # Защищает простые композитные read'ы (status+status_detail, hh-stats группой, vacancies_queue+idx).
        self._state_lock = threading.Lock()
        # Сериализует мутации acc["cookies"] между workers одного аккаунта.
        self._cookies_lock = threading.Lock()
        # Прокидываем lock в сам acc dict — чтобы hh_chat._ensure_chatik_cookies
        # мог найти его без знания о AccountState.
        self.acc["_cookies_lock"] = self._cookies_lock
        # Reason for pause — manual vs auto vs limit — чтобы midnight reset не сбрасывал manual pause.
        self.paused_reason: str = str(acc_data.get("paused_reason") or "manual") if self.paused else ""
        # An unconfirmed write is not a user pause. Keep every in-flight result
        # from a batch until its exact vacancy/resume receipt is reconciled.
        pending = acc_data.get("pending_applies")
        if not isinstance(pending, list):
            pending = [acc_data["pending_apply"]] if isinstance(acc_data.get("pending_apply"), dict) else []
        self.pending_applies: list = copy.deepcopy(pending)
        self.pending_apply = self.pending_applies[0] if self.pending_applies else None
        if self.pending_applies or acc_data.get("paused_reason") == "outcome_unknown":
            self.paused = True
            self.paused_reason = "outcome_unknown"
        # A limit stop persisted on an earlier MSK day: the midnight rollover
        # never fires for it because daily_date starts as today.
        if acc_data.get("pause_date") and acc_data.get("pause_date") != self.daily_date:
            self.hard_stopped = False
            self.limit_exceeded = False
            if self.paused and self.paused_reason == "limit" and not self.pending_applies:
                self.paused = False
                self.paused_reason = ""
        # Restored pauses have no known start time unless the pending receipt
        # carries one. A later real transition is timestamped by note_pause.
        self._activity_pause_key = (self.paused, self.paused_reason, self.hard_stopped, self.limit_exceeded)
        self._activity_control_revision = 0
        self.auth_check_started_at = None
        self._auth_recovery_pending = False
        recovery = acc_data.get("network_recovery")
        self.network_recovery = copy.deepcopy(recovery) if isinstance(recovery, dict) else None
        self._network_error_streak = 0
        self._network_error_last_count = 0
        self._network_recovery_persistence_failed = False


    def reset_vacancy_meta(self):
        """Clear vacancy_meta before each collection cycle to prevent unbounded growth."""
        self.vacancy_meta = {}

    @property
    def device_identity(self) -> dict:
        """Expose (and lazily migrate) the persisted account device identity."""
        from app.user_agent import ensure_device_identity

        return ensure_device_identity(self.acc)

    @device_identity.setter
    def device_identity(self, value: dict) -> None:
        self.acc["device_identity"] = value

    def cleanup_old_failures(self, max_size=500):
        """Trim _llm_neg_failures to max_size by removing oldest entries."""
        excess = len(self._llm_neg_failures) - max_size
        if excess > 0:
            for k in list(self._llm_neg_failures.keys())[:excess]:
                self._llm_neg_failures.pop(k, None)

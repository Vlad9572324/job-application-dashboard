"""
MobileHHClient — mobile-клиент hh.ru (api.hh.ru, OAuth Bearer).

Реализовано:
  - fetch_counters() — smoke-test абстракции (GET /me?with_user_statuses=true);
  - oauth-extras (группа E) — эти вызовы уже живут в app/oauth.py и работают
    через Bearer одинаково для web и mobile, поэтому просто делегируем туда;
  - Phase 2 (переговоры/чаты) — реальные вызовы api.hh.ru через общий
    транспорт app/hh_mobile_transport.py (модули app/mobile_*.py):
    fetch_negotiations, fetch_thread, fetch_chat_history, send_message,
    fetch_chat_list, fetch_quick_replies, send_participant_action,
    mark_chat_read, fetch_possible_offers, fetch_negotiations_metadata.
    Политика ошибок: fallback-статусы (0/401/403/5xx) поднимаются
    MobileAPIError — фабрика оборачивает клиент в FallbackHHClient,
    который прозрачно повторяет такие вызовы через web-flow; прочие
    статусы обработаны в модулях (дефолты/sentinel'ы как в web).

  - Phase 4 (резюме/статистика) — реальные вызовы api.hh.ru через тот же
    транспорт (модули app/mobile_resume*.py + app/mobile_job_search_status.py):
    fetch_resume, fetch_stats, fetch_resume_view_history,
    fetch_resume_views_aggregate, analyze_resume, edit_resume_field,
    set_job_search_status. Политика ошибок та же: fallback-статусы
    (0/401/403/5xx) поднимаются MobileAPIError → авто-повтор через web.
    Расхождения форматов с web (fetch_resume: dict вместо str;
    fetch_resume_view_history: dict {items, total} вместо list)
    задокументированы в модулях и отчёте Phase 4.

Web-only аналоги, перенесённые на mobile API:
  - auto_decline_discards, fetch_employer_rating, fetch_account_diagnostics.
"""

import asyncio
import copy
import threading
import time
import requests

from app import (
    hh_apply,
    hh_negotiations,
    mobile_apply,
    mobile_auto_response,
    mobile_chat_actions,
    mobile_chat_list,
    mobile_chat_thread,
    mobile_check_limit,
    mobile_job_search_status,
    mobile_hedi,
    mobile_neg_meta,
    mobile_negotiations,
    mobile_precheck,
    mobile_questionnaire,
    mobile_relevance,
    mobile_related,
    mobile_resume,
    mobile_resume_aggregate,
    mobile_resume_analyze,
    mobile_resume_edit,
    mobile_resume_stats,
    mobile_resume_views,
    mobile_search,
    mobile_send_message,
    mobile_touch_resume,
    mobile_web_only,
    oauth,
)
from app.hh_client import HHClient
from app.hh_http import egress_proxies
from app.llm import _randomize_text
from app.logging_utils import log_debug


CHAT_CACHE_TTL_SEC = 5.0
CHAT_FULL_SWEEP_SEC = 1800.0
_CHAT_CACHE: dict = {}
_CHAT_FULL_SWEEP_AT: dict = {}
_CHAT_LOCKS: dict = {}
_CHAT_LOCKS_GUARD = threading.Lock()


def _chat_lock(key: str) -> threading.Lock:
    with _CHAT_LOCKS_GUARD:
        return _CHAT_LOCKS.setdefault(key, threading.Lock())


class MobileHHClient(HHClient):
    """Mobile-flow реализация полного контракта HHClient (HHClientBase +
    WebOnlyOps + MobileOnlyOps): api.hh.ru через OAuth Bearer. Реально:
    fetch_counters (MobileOnlyOps), OAuth-extras и группы A–C через
    app/mobile_*.py; оставшиеся неподдержанные операции явно представлены
    NotImplementedError-заглушками."""

    def __init__(self, acc: dict):
        super().__init__(acc)
        self.mode = str(acc.get("mode") or "mobile").strip().lower()

    def search_vacancies(self, text: str, area_id=113, per_page: int = 20,
                         page: int = 0, filters=None, max_pages: int = 100) -> list:
        return mobile_search.search_vacancies(
            self.acc, text, area_id, per_page, page, filters, max_pages)
    def start_hedi(self) -> str:
        """Start the mobile-only HH AI vacancy-search assistant."""
        return mobile_hedi.start_hedi(self.acc)

    def fetch_auto_response_rules(self) -> list[dict]:
        return mobile_auto_response.fetch_rules(self.acc)

    def fetch_auto_response_statistics(self, rule_id: str, days: int = 7) -> dict:
        return mobile_auto_response.fetch_statistics(self.acc, rule_id, days=days)

    def create_auto_response_rule(self, resume_id: str,
                                  filters: dict | None = None) -> dict:
        return mobile_auto_response.create_rule(self.acc, resume_id, filters)

    def update_auto_response_rule(self, rule_id: str, resume_id: str, *,
                                  enabled: bool,
                                  filters: dict | None = None) -> dict:
        return mobile_auto_response.update_rule(
            self.acc, rule_id, resume_id, enabled=enabled, filters=filters,
        )

    # ── Phase 2: переговоры/чаты (реализовано: api.hh.ru, Bearer) ─────────────
    # Делегирование в app/mobile_*.py; транспорт — app/hh_mobile_transport.py
    # (requests + responses-mock'и в тестах, конвенция fetch_counters).

    def fetch_negotiations(self, max_pages: int = 20) -> dict:
        """Список переговоров + статистика: GET api.hh.ru/negotiations
        (пагинация до конца). Совместим по ключам с web
        hh_negotiations.fetch_hh_negotiations_stats."""
        return mobile_negotiations.fetch_negotiations(self.acc, max_pages)

    def fetch_thread(self, neg_id: str) -> dict:
        """Тред переговоров (chat_id == neg_id):
        GET api.hh.ru/chats/{neg_id}?limit=50&order=next."""
        return mobile_chat_thread.fetch_thread(self.acc, neg_id)

    def send_message(self, neg_id: str, text: str, topic_id: str = "") -> bool | str:
        """Отправка сообщения: POST api.hh.ru/chats/{neg_id}/messages
        {text, idempotency_key(uuid4)}. topic_id в mobile-flow не нужен
        (один чат = один топик), сохранён в сигнатуре ради контракта."""
        return mobile_send_message.send_message(self.acc, neg_id, text)

    def send_workflow_event(self, neg_id: str, event_type: str,
                            event_params: dict | None = None) -> bool:
        """Нажатие workflow-кнопки: POST api.hh.ru/chats/{id}/event."""
        return mobile_chat_actions.send_event(self.acc, neg_id, event_type, event_params)

    def fetch_chat_list(self, max_pages: int = 5) -> tuple:
        """Single-flight + короткий кэш поверх _fetch_chat_list_uncached.

        LLM-цикл и Telegram-сканер вызывают это одновременно, и каждый раз шёл
        полный двойной проход (~46 GET /chats). Теперь параллельные вызовы
        одного аккаунта делят один результат (TTL 5 с), а полный проход по
        непрочитанным (до 20 страниц) делается раз в CHAT_FULL_SWEEP_SEC — в
        остальное время хватает первых страниц (свежие непрочитанные наверху).
        """
        key = str(self.acc.get("user_id") or self.acc.get("resume_hash") or "")
        with _chat_lock(key):
            now = time.monotonic()
            hit = _CHAT_CACHE.get(key)
            if hit and now - hit[0] < CHAT_CACHE_TTL_SEC and hit[1] >= max_pages:
                return copy.deepcopy(hit[2])
            last_full = _CHAT_FULL_SWEEP_AT.get(key)
            full = last_full is None or now - last_full >= CHAT_FULL_SWEEP_SEC
            result = self._fetch_chat_list_uncached(max_pages, unread_pages=20 if full else 3)
            if full:
                _CHAT_FULL_SWEEP_AT[key] = time.monotonic()
            _CHAT_CACHE[key] = (time.monotonic(), max_pages, copy.deepcopy(result))
            return result

    def _fetch_chat_list_uncached(self, max_pages: int = 5, unread_pages: int = 20) -> tuple:
        """Список чатов: GET api.hh.ru/chats (page/per_page<=20). Возврат
        совместим с web hh_chat._fetch_chat_list:
        (items_by_id, display_info, current_participant_id).

        Гибридная стратегия: сначала все непрочитанные (filter_unread=true —
        сервер вернёт даже старые из глубины 2000+ переговоров), затем top-N
        свежих без фильтра (чтобы поймать «unread=0 от работодателя, не
        отвечали» — новые reads/updates могут сбросить unread до 0 но чат
        всё равно требует ответа). Без первого прохода бот видел только
        последние 60 чатов и игнорировал сотни старых HR-веток.
        """
        # Каждый вызов оборачиваем в свой try: если unread-пасс упадёт с
        # MobileAPIError (fallback-статус) — FallbackHHClient снаружи перекинет
        # весь метод на web, где нет filter_unread → мы бы тихо потеряли
        # 300+ старых непрочитанных. Реrent-пасс должен отработать независимо.
        # Re-raise только если оба пасса упали.
        from app.hh_mobile_transport import MobileAPIError, is_fallback_status
        unread_items, unread_display, unread_cur = {}, {}, ""
        recent_items, recent_display, recent_cur = {}, {}, ""
        unread_err: Exception | None = None
        recent_err: Exception | None = None
        try:
            unread_items, unread_display, unread_cur = mobile_chat_list.fetch_chat_list(
                self.acc, max_pages=unread_pages, filter_unread=True,
            )
        except Exception as e:  # noqa: BLE001
            unread_err = e
        try:
            recent_items, recent_display, recent_cur = mobile_chat_list.fetch_chat_list(
                self.acc, max_pages, filter_unread=False,
            )
        except Exception as e:  # noqa: BLE001
            recent_err = e
        if unread_err and recent_err:
            raise recent_err
        # Эволюция: round-1 #12 → round-2 #11 → round-3 #5 → round-4 #4.
        # Правило: fallback на web делает FallbackHHClient когда мы re-raise
        # MobileAPIError с fallback-статусом. НЕ re-raise когда собрано хоть
        # что-то полезное — иначе теряем already-fetched. Специальный случай:
        # unread законно пустой + recent упал = данных НЕТ, надо re-raise
        # чтобы web-fallback показал recent чаты (иначе UI думает «чатов нет»).
        if isinstance(recent_err, MobileAPIError) and is_fallback_status(recent_err.status_code):
            if not unread_items:
                # Нет ни свежих (fail), ни старых (пусто) — эквивалент полного fail
                raise recent_err
            log_debug(
                f"mobile fetch_chat_list: recent-пасс упал HTTP {recent_err.status_code}, "
                f"возвращаем unread как есть ({len(unread_items)} шт.) — "
                f"свежие могут быть stale до следующего цикла"
            )
        if isinstance(unread_err, MobileAPIError) and is_fallback_status(unread_err.status_code):
            if not recent_items:
                raise unread_err  # симметрично: recent пустой + unread fail
            log_debug(
                f"mobile fetch_chat_list: unread-пасс упал HTTP {unread_err.status_code}, "
                f"возвращаем только recent ({len(recent_items)} шт.) — часть старых "
                f"непрочитанных может быть невидна до следующего цикла"
            )
        # merge: свежие перезаписывают unread (у recent актуальнее lastMessage
        # если между вызовами HR прислал новое сообщение).
        items = {**unread_items, **recent_items}
        display = {**unread_display, **recent_display}
        cur = recent_cur or unread_cur
        return items, display, cur

    def fetch_chat_history(self, chat_id: str, max_messages: int = 20) -> list:
        """История сообщений чата:
        GET api.hh.ru/chats/{chat_id}?limit&order=next (текст в
        body.text.content)."""
        return mobile_chat_thread.fetch_chat_history(self.acc, chat_id, max_messages)

    def fetch_quick_replies(self, chat_id: str, msg_id: str) -> list:
        """Быстрые ответы HH: PUT
        api.hh.ru/chats/{chat_id}/suggestions/quick_replies?message_id=...
        (глагол PUT по контракту APK; GET на пути -> 405)."""
        return mobile_chat_actions.fetch_quick_replies(self.acc, chat_id, msg_id)

    def send_participant_action(self, chat_id: str, action_type: str = "TYPING") -> bool:
        """Typing-индикатор: PUT api.hh.ru/chats/{chat_id}/participants/action
        {action_type: "typing"|"none"} (контракт APK, нормализация регистра
        в модуле)."""
        return mobile_chat_actions.send_participant_action(self.acc, chat_id, action_type)

    def mark_chat_read(self, chat_id: str, message_id: str) -> bool:
        """Read-receipt «прочитано до...»: PUT
        api.hh.ru/chats/{chat_id}/messages/last_viewed_id
        (form-urlencoded message_id=<long>)."""
        return mobile_chat_actions.mark_chat_read(self.acc, chat_id, message_id)

    def fetch_possible_offers(self) -> list:
        """Возможные офферы: GET api.hh.ru/vacancies/possible_job_offers."""
        return mobile_neg_meta.fetch_possible_offers(self.acc)

    def auto_decline_discards(self) -> int:
        """Отклонить DISCARD-переговоры через Android mobile endpoint."""
        return mobile_web_only.auto_decline_discards(self.acc)

    def fetch_negotiations_metadata(self) -> dict:
        """Метаданные переговоров: GET api.hh.ru/negotiations ->
        topics_by_vid (per-vacancy статусы). politeness/activity доступны
        только в web-SSR — в mobile пусты."""
        return mobile_neg_meta.fetch_negotiations_metadata(self.acc)

    # ── Phase 3: отклики и vacancy-метаданные ─────────────────────────────────

    async def submit_response(self, vid: str, letter_max_length: int | None = None) -> tuple:
        letter = _randomize_text(self.acc.get("letter", "")) if self.acc.get("letter") else ""
        if letter_max_length and len(letter) > letter_max_length:
            letter = letter[:letter_max_length].rstrip()
        visibility_id = self.acc.get("required_applicant_visibility_id", "")
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: mobile_apply.submit_response(
                self.acc, vid, self.acc.get("resume_hash", ""), letter,
                required_applicant_visibility_id=visibility_id))
        if result.get("ok"):
            return "sent", {"negotiation_id": result.get("negotiation_id", "")}
        info = {"error_type": result.get("error_type", ""),
                "http_status": result.get("http_status")}
        return {"captcha_required": "challenge", "limit_exceeded": "limit", "test_required": "test",
                "already_applied": "already"}.get(info["error_type"], "error"), info

    async def fill_questionnaire(self, vid: str, vacancy_title: str = "", company: str = "") -> tuple:
        """Заполнить анкету через штатный Android WebView/autologin bridge."""
        return await mobile_questionnaire.fill_questionnaire(self.acc, vid, vacancy_title, company)

    def check_vacancy_before_apply(self, vid: str) -> dict:
        """Пре-проверка вакансии перед откликом (phase 3)."""
        return mobile_precheck.check_vacancy_before_apply(
            self.acc, vid, self.acc.get("resume_hash", ""))

    def fetch_setka_relevance(self, vid: str) -> bool | None:
        """Setka employee-referral relevance (not a resume match score)."""
        return mobile_relevance.fetch_setka_relevance(self.acc, vid)

    def check_limit(self) -> bool | None:
        """Проверка дневного лимита откликов (phase 3)."""
        allowed = mobile_check_limit.check_limit(self.acc).get("can_apply")
        return None if allowed is None else not allowed

    def touch_resume(self) -> tuple:
        """Поднять резюме (touch) (phase 3)."""
        try:
            return mobile_touch_resume.touch_resume(self.acc, self.acc.get("resume_hash", ""))
        except NotImplementedError:
            if self.mode != "oauth":
                raise
            # Android WebView fallback, но с cookies, полученными одноразово из
            # OAuth autologin. Постоянную web-сессию в аккаунт не записываем.
            from app.mobile_questionnaire import oauth_web_account_sync
            return hh_apply.touch_resume(oauth_web_account_sync(self.acc))

    def fetch_related_vacancies(self, seed_vid: str, max_pages: int = 1) -> list:
        """Похожие вакансии для расширения пула (phase 3)."""
        return mobile_related.fetch_related_vacancies(self.acc, seed_vid, max_pages)

    def fetch_employer_rating(self, employer_id) -> dict | None:
        """Рейтинг работодателя из /employers/{id} и reviews API."""
        return mobile_web_only.fetch_employer_rating(self.acc, employer_id)

    def fetch_employer_id_for_vacancy(self, vacancy_id) -> int | None:
        """employer_id из OAuth GET /vacancies/{id}."""
        details = oauth.fetch_vacancy_details(self.acc, str(vacancy_id))
        employer_id = details.get("employer_id") if isinstance(details, dict) else None
        try:
            return int(employer_id) if employer_id is not None else None
        except (TypeError, ValueError):
            return None

    def fetch_vacancy_owner_hr_hhid(self, vacancy_id) -> int | None:
        """HHID HR-а из SSR через временный OAuth-autologin WebView."""
        if self.mode != "oauth":
            raise NotImplementedError("mobile API does not expose vacancy owner HR hhid")
        from app.mobile_questionnaire import oauth_web_account_sync
        return hh_negotiations.fetch_vacancy_owner_hr_hhid(
            oauth_web_account_sync(self.acc), vacancy_id
        )

    # ── Phase 4: резюме/статистика (реализовано: api.hh.ru, Bearer) ──────────
    # Делегирование в app/mobile_resume*.py и app/mobile_job_search_status.py;
    # транспорт — app/hh_mobile_transport.py, резолв hash'а резюме —
    # app/mobile_resume_common.py (контракты: scratchpad/apidocs
    # apidocs_group_2/3/5.yaml + apk_writes_group_5.yaml).

    def fetch_resume(self, resume_id: str | None = None) -> str:
        """Полное резюме JSON: GET api.hh.ru/resumes/{id}
        (?with_professional_roles=true&with_creds=true). resume_id=None —
        первое резюме аккаунта (mobile_resume_common.resolve_resume_id).
        ВНИМАНИЕ: mobile возвращает dict (полный JSON резюме), web — str
        (текст для LLM); расхождение задокументировано в отчёте Phase 4."""
        import json
        data = mobile_resume.fetch_resume(self.acc, resume_id)
        return json.dumps(data, ensure_ascii=False, indent=2) if data else ""

    def fetch_stats(self, resume_id: str | None = None) -> dict:
        """Статистика резюме: GET /me?with_user_statuses=true (counters:
        new_resume_views/unread_negotiations/resumes_count) +
        GET /resumes/{id} (total_views/new_views) +
        GET /negotiations_statistic/mine (streak). Ключи совместимы с web
        hh_resume.fetch_resume_stats; shows/invitations в mobile недоступны
        (web-SSR данные) — нули."""
        return mobile_resume_stats.fetch_stats(self.acc, resume_id)

    def fetch_resume_view_history(self, limit: int = 50, resume_id: str | None = None) -> list:
        """Кто смотрел резюме: GET api.hh.ru/resumes/{id}/views (пагинация
        до limit). Возврат {items: [{employer_id, name, viewed_at, viewed}],
        total}. ВНИМАНИЕ: mobile возвращает dict с флагом viewed, web —
        list; расхождение задокументировано в отчёте Phase 4."""
        result = mobile_resume_views.fetch_resume_view_history(self.acc, resume_id, limit)
        items = result.get("items", []) if isinstance(result, dict) else result
        return items if isinstance(items, list) else []

    def fetch_resume_views_aggregate(self, resume_id: str | None = None) -> dict:
        """Агрегация просмотров: GET /resumes/{id}/views (все страницы) →
        {total, new (viewed=false), by_employer_top10} + web-алиасы
        total_all_time/total_new (graph_30d в mobile пуст)."""
        return mobile_resume_aggregate.fetch_resume_views_aggregate(self.acc, resume_id)

    def analyze_resume(self, extra_terms: list = None, resume_id: str | None = None) -> dict:
        """ML-аудит резюме: комбинация GET /resumes/{id} +
        POST /skills_profile/predictions/recommended_skills/resume +
        POST /skills_profile/suggestions/duties +
        POST /skills_profile/predictions/subroles/by_title +
        GET /career_platform/profile?profession_description=true. Возврат
        {ok, missing_skills, recommended_duties, subroles, grade,
        current_score}. extra_terms в mobile не используется (web-SSR
        supply/demand), сохранён в сигнатуре ради контракта."""
        return mobile_resume_analyze.analyze_resume(self.acc, resume_id)

    def edit_resume_field(self, resume_hash: str, fields: dict) -> dict:
        """Редактирование полей резюме: валидация по
        GET /resumes/{id}/conditions (regexp/длины) +
        PUT /resume_profile/{id} с JSON-diff
        {resume: fields, creds: {}, additional_properties: {}}
        (контракт APK EditResumeProfileRequestNetwork). Возврат
        {ok, error?, updated_field?}."""
        return mobile_resume_edit.edit_resume_field(self.acc, resume_hash, fields)

    def set_job_search_status(self, status: str) -> dict:
        """Смена статуса поиска работы: PUT
        /user_statuses/job_search_statuses/mine (form id=<status>, контракт
        APK JobSearchStatusRemoteApi). Возврат {ok, status, label} либо
        {ok: False, error}."""
        return mobile_job_search_status.set_job_search_status(self.acc, status)

    def fetch_account_diagnostics(self) -> dict:
        """Диагностика из /me, /counters/user и negotiation statistics."""
        return mobile_web_only.fetch_account_diagnostics(self.acc)

    # ── Реально в Phase 0 ─────────────────────────────────────────────────────

    def fetch_counters(self) -> dict:
        """GET /me?with_user_statuses=true — единственный реальный метод
        skeleton'а (smoke-test что абстракция работает). Возвращает {} если
        нет токена, произошла сетевая ошибка или не удалось разобрать JSON
        (конвенция app/oauth.py).

        HTTP ходит через библиотеку `requests` (не curl_cffi-обёртку HH),
        чтобы тесты могли mock'ать его через `responses`; прокси инжектится
        из HH_PROXY через egress_proxies() — как и весь hh.ru egress.
        """
        token = oauth._obtain_oauth_token(self.acc)
        if not token:
            return {}
        try:
            r = requests.get(
                "https://api.hh.ru/me",
                params={"with_user_statuses": "true"},
                headers={
                    # Тот же UA, что app/oauth.py использует для api.hh.ru
                    # (см. oauth._oauth_headers).
                    "User-Agent": "job-application-dashboard/1.0",
                    "Authorization": f"Bearer {token}",
                },
                # split-egress: api.hh.ru тоже обязан идти через HH_PROXY.
                proxies=egress_proxies(),
                timeout=15,
            )
            if r.status_code != 200:
                return {}
            return r.json()
        except (requests.RequestException, ValueError):
            # ValueError покрывает ошибку парсинга JSON из r.json().
            return {}

    # ── OAuth-extras: уже реализованы в app/oauth.py (Bearer api.hh.ru),
    #    одинаково для web и mobile — просто делегируем. ──────────────────────

    def fetch_saved_vacancy_searches(self) -> list:
        """Сохранённые поиски вакансий → oauth.fetch_saved_vacancy_searches."""
        return oauth.fetch_saved_vacancy_searches(self.acc)

    def fetch_favorited_vacancies(self) -> list:
        """Избранные вакансии → oauth.fetch_favorited_vacancies."""
        return oauth.fetch_favorited_vacancies(self.acc)

    def fetch_blacklisted_vacancies(self) -> set:
        """Вакансии в чёрном списке → oauth.fetch_blacklisted_vacancies."""
        return oauth.fetch_blacklisted_vacancies(self.acc)

    def fetch_vacancy_details(self, vid: str) -> dict:
        """Детали вакансии через OAuth → oauth.fetch_vacancy_details."""
        return oauth.fetch_vacancy_details(self.acc, vid)

    def fetch_negotiations_today_count(self) -> dict:
        """Число сегодняшних откликов → oauth.fetch_negotiations_today_count."""
        return oauth.fetch_negotiations_today_count(self.acc)

    def fetch_negotiations_statistic(self) -> dict:
        """Streak-статистика откликов → oauth.fetch_negotiations_statistic."""
        return oauth.fetch_negotiations_statistic(self.acc)

    def fetch_resume_status(self, force: bool = False) -> dict:
        """Статус резюме → oauth.fetch_resume_status."""
        if force:
            return oauth.fetch_resume_status(self.acc, force)
        return oauth.fetch_resume_status(self.acc)

    def fetch_employer_rating_oauth(self, employer_id: str) -> dict:
        """Рейтинг работодателя через OAuth → oauth.fetch_employer_rating
        (имя с `_oauth`, чтобы не сталкиваться с web-методом fetch_employer_rating)."""
        return oauth.fetch_employer_rating(self.acc, employer_id)

"""
Configuration: Config class, accounts_data, save/load functions, URL helpers.

Схема данных — поле mode (Phase 0 HHClient-абстракции)
======================================================

Каждый аккаунт в data/accounts.json и каждая temp-сессия в
data/browser_sessions.json принимают OPTIONAL поле `mode`:
"web" | "mobile" | "auto". Если поле отсутствует — используется
CONFIG.default_client_mode (дефолт "web").

1. data/accounts.json (load_accounts()/save_accounts() в этом модуле):
   список account-dict'ов. Поле `mode` сохраняется автоматически:
   save_accounts() при записи отбрасывает только ключи с префиксом "_"
   (runtime-объекты вроде "_cookies_lock"), все остальные ключи — включая
   `mode` — попадают на диск как есть.

2. data/browser_sessions.json (app/storage.py: load_browser_sessions()/
   save_browser_sessions()): temp-сессии — такие же account-подобные dict'ы
   с cookies, принимают то же optional поле `mode` с тем же смыслом
   (сохраняется автоматически: при записи удаляются только
   "_raw_cookie_line"/"raw_cookie_line"). get_client() работает с любым
   account-подобным dict'ом, различий между аккаунтом и temp-сессией нет.

3. Семантика значений:
   - "web"    → WebHHClient (app/hh_client_web.py): cookies hh.ru,
                существующий web-flow.
   - "mobile" → MobileHHClient (app/hh_client_mobile.py): OAuth Bearer
                через api.hh.ru.
   - "auto"   → mobile при живом OAuth-токене, иначе web.

Выбор клиента по полю `mode` делает app/hh_client_factory.py::get_client(account).
"""

import json
import copy
import threading
from pathlib import Path

from app.logging_utils import log_debug
# Используем storage executor вместо своего fire-and-forget thread per save.
try:
    from app.storage import _schedule_save
except Exception:
    _schedule_save = None  # cycle-safe fallback

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True, mode=0o700)
try:
    DATA_DIR.chmod(0o700)
except Exception:
    pass

CONFIG_FILE = DATA_DIR / "config.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"

# Защищаем write+rename последовательность от конкурентных вызовов из разных потоков.
_config_write_lock = threading.Lock()
_accounts_write_lock = threading.Lock()
_accounts_schedule_lock = threading.Lock()


# ============================================================
# АККАУНТЫ
# ============================================================

# Загружается из data/accounts.json при старте (через load_accounts())
accounts_data: list = []


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

class Config:
    """Глобальные настройки (можно менять в runtime)"""
    tg_alert_interview_enabled: bool = True
    tg_alert_offer_enabled: bool = True
    tg_alert_hr_question_enabled: bool = True
    tg_alert_account_blocked_enabled: bool = True
    tg_alert_daily_limit_enabled: bool = False
    pages_per_url = 100  # Maximum safety budget; API stops at the reported end.
    automation_paused: bool = False
    max_concurrent = 20
    human_mode_enabled: bool = True
    human_active_hours: str = '07-24'
    human_apply_delay_min: int = 15
    human_apply_delay_max: int = 45
    human_burst_size_min: int = 2
    human_burst_size_max: int = 4
    human_burst_pause_min_sec: int = 600
    human_burst_pause_max_sec: int = 1500
    human_captcha_backoff_hours: int = 4
    response_delay = 1
    pause_between_cycles = 60
    limit_check_interval = 30
    resume_touch_interval = 4
    batch_responses = 3
    min_salary = 0  # Минимальная зарплата в руб (0 = без фильтра)
    auto_pause_errors = 5  # Авто-пауза после N ошибок подряд (0 = выключено)
    auto_apply_tests: bool = False  # Автоматически проходить опросники при откликах
    use_oauth_apply: bool = False  # Использовать OAuth API для откликов (вместо web cookies)
    auto_pick_resume: bool = True  # Выбирать наиболее подходящее резюме для mobile-отклика
    # Режим HH-клиента: web, mobile (с web fallback), oauth (строгий), auto.
    # Auto выбирает mobile только при живом OAuth-токене.
    default_client_mode: str = "web"
    # WebSocket realtime updates от chatik.hh.ru (Phase 1). Off by default —
    # legacy polling loop продолжает работать. Включать per-account через /api/ws/{idx}/enable.
    use_websocket_realtime: bool = False
    daily_apply_limit: int = 0  # Жёсткий лимит откликов в день (0 = без ограничения)
    stop_on_hh_limit: bool = True  # Полная остановка при HH лимите (не перепроверять)
    # Фильтр по формату работы (пустой = без фильтра, все форматы)
    # Возможные значения: "fullDay", "remote", "flexible", "shift", "flyInFlyOut"
    allowed_schedules: list = []
    remote_it_only: bool = False
    # Фильтр по заголовку вакансии. Пустой include = все заголовки разрешены.
    # Сравнение регистронезависимое, по вхождению подстроки.
    title_include_keywords: list = []
    title_exclude_keywords: list = []

    # LLM auto-reply settings
    llm_enabled: bool = False
    llm_auto_send: bool = False       # True = отправлять, False = только логировать черновик
    llm_use_cover_letter: bool = True  # Передавать сопроводительное письмо в контекст
    llm_use_resume: bool = True        # Включать текст резюме в системный промпт
    # HH сам генерит quick_replies под каждое HR-сообщение — пробуем сначала их,
    # только на пустой ответ идём в свой LLM (экономит токены + официально-выглядящий текст).
    llm_use_quick_replies: bool = False
    # HH-Pro AI cover letter: `POST /shards/hhpro_ai_letter` даёт 1 бесплатное
    # письмо на пару (resumeHash, vacancyId) даже без подписки. Пробуем первым —
    # доменная модель HH пишет письмо под конкретную вакансию с учётом резюме.
    hh_ai_letter_first_try: bool = True
    # related_vacancies: раз в цикл сбора запрашиваем HH-рекомендательный фид
    # `GET /shards/vacancy/related_vacancies?vacancyId=<seed>` — обычно
    # match'ит лучше текстового поиска (внутренний ML ranker).
    related_vacancies_enabled: bool = True
    # Прокси для исходящих запросов к hh.ru (обход soft-ban DDoS-Guard по IP).
    # Формат: `socks5h://host:port` / `http://user:pass@host:port`. Пусто = напрямую.
    # При старте `hh_http._PROXY` берётся сначала из env `HH_PROXY`, иначе из этого поля.
    hh_proxy_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    captcha_llm_enabled: bool = True
    captcha_model_name: str = "default"
    captcha_llm_solved: int = 0
    captcha_llm_forwarded: int = 0
    telegram_status_enabled: bool = True
    telegram_status_interval_min: int = 30
    telegram_captcha_enabled: bool = True
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # "female" (default), "male" or "neutral".
    llm_applicant_gender: str = "female"
    llm_profiles: list = None         # [{name, api_key, base_url, model, enabled}]
    llm_profile_mode: str = "fallback"  # "fallback" | "roundrobin"
    llm_openclaw_enabled: bool = False
    llm_openclaw_agent: str = "main"
    llm_openclaw_model: str = ""
    llm_openclaw_timeout: int = 120
    skip_inconsistent: bool = False  # Пропускать вакансии с несовпадением опыта
    filter_agencies: bool = False  # Исключить кадровые агентства из поиска
    filter_low_competition: bool = False  # Только вакансии с <10 откликами
    search_period_days: int = 0  # 0 = все, 1-30 = последние N дней
    # Employer rating gate (через OAuth /employers/{eid}/reviews). Применяется
    # только при cookie- или OAuth-сборе если в meta есть employer_id.
    # Работодатели без отзывов (0 reviews_count) НЕ блокируются.
    min_employer_rating: float = 0.0        # 0.0 = выкл; типичный порог 3.0/3.5
    min_employer_reviews: int = 3           # минимум отзывов для применения фильтра
    min_recommendations_percent: int = 0    # 0 = выкл; % "рекомендую этого работодателя"
    # Vacancy quality gates (через OAuth /vacancies/{vid}). Lazy enrichment
    # выполняется только когда хотя бы один из этих флагов включён.
    skip_auto_response_vacancies: bool = False  # auto_response=true → массовые auto-feed вакансии, мусор
    prefer_quick_responses: bool = False        # quick_responses_allowed=true идут в начало queue
    accredited_it_only: bool = False            # только аккредитованные IT-работодатели
    # HH daily limit (откликов на резюме в день; HH = 200). Используется как порог
    # для proactive limit-tracker. 0 = выкл (старое поведение по daily_apply_limit).
    hh_daily_limit: int = 200
    fresh_vacancies_mode: bool = False  # резервировать часть лимита для новых вакансий
    prefer_hh_signals: bool = False    # внутри категории свежести: менеджер онлайн, затем совпадение навыков
    fresh_vacancy_hours: int = 24       # возраст вакансии для категории «свежая»
    fresh_apply_reserve: int = 50       # сколько последних откликов не тратить на старые
    llm_fill_questionnaire: bool = False  # Использовать LLM для заполнения опросников
    llm_check_questionnaire_claims: bool = True  # Останавливать неподтверждённые утверждения LLM
    llm_check_interval: int = 5  # Интервал проверки чатов LLM (в минутах, мин 2)
    llm_ws_push_enabled: bool = True  # Подписаться на wss://websocket.hh.ru для мгновенных ответов
    chat_use_oauth: bool = False  # Сначала пробовать официальный OAuth-путь POST /common/chats/{id}/messages,
                                  # fallback на reverse-engineered chatik.hh.ru/api/send. Требует у аккаунта OAuth-токен.
    llm_system_prompt: str = (
        "Ты помощник соискателя работы. Отвечай вежливо и кратко (2-4 предложения) "
        "на сообщения от HR и работодателей. Пиши от первого лица. "
        "Соглашайся на предложенное время собеседования или уточни детали. "
        "Не используй слишком формальный язык."
    )

    # Шаблонные ответы на опросы (list of {keywords: [...], answer: "..."})
    questionnaire_templates: list = []
    # Ответ по умолчанию (когда ни один шаблон не подошёл)
    questionnaire_default_answer: str = "Готова рассказать подробнее на собеседовании."

    # Глобальный пул поисковых URL (выбираются на карточке каждого аккаунта)
    url_pool: list = []  # [{url, pages}, ...] или plain строки (legacy)

    # Региональный поддомен HH (например, "syktyvkar" → https://syktyvkar.hh.ru).
    # Пусто = основной домен hh.ru. OAuth и chatik всегда на основном (не региональные).
    # GitHub issue: апплай/поиск/резюме надо ходить на региональный, если задан.
    hh_region: str = ""

    # Шаблоны сопроводительных писем (list of {name: str, text: str})
    letter_templates: list = [
        {
            "name": "Стандартное",
            "text": (
                "Здравствуйте!\n\n"
                "Я выражаю искренний интерес к возможности присоединиться к вашей компании.\n\n"
                "Деятельность вашей организации мне интересна. Считаю, что мой опыт и навыки "
                "смогут внести вклад в вашу команду.\n\n"
                "Хочу учиться новому и развиваться в профессиональном плане.\n\n"
                "Считаю, что ваша компания предоставляет отличные возможности для роста и "
                "самосовершенствования, и мне бы хотелось стать частью вашей команды.\n\n"
                "С уважением,\n[ИМЯ]\n[t.me: @username]\n[📞 телефон]"
            ),
        }
    ]


CONFIG = Config()
CONFIG.llm_profiles = []

_BUILTIN_QUESTIONNAIRE_DEFAULT_ANSWER = Config.questionnaire_default_answer


def applicant_gender_forms() -> dict:
    gender = (getattr(CONFIG, "llm_applicant_gender", "") or "female").strip().lower()
    if gender in ("male", "m", "masculine", "мужской"):
        return {
            "instruction": "Пиши от первого лица, мужской род.",
            "responded": "соискатель откликнулся",
            "consistency": "будь последователен",
            "ready": "готов",
            "ready_title": "Готов",
            "default_questionnaire_answer": "Готов рассказать подробнее на собеседовании.",
        }
    if gender in ("neutral", "n", "неважно", "нейтральный"):
        return {
            "instruction": "Пиши от первого лица; избегай формулировок, где нужно выбирать мужской или женский род.",
            "responded": "отклик был отправлен",
            "consistency": "сохраняй последовательность",
            "ready": "готов(а)",
            "ready_title": "Готов(а)",
            "default_questionnaire_answer": "Подробнее расскажу на собеседовании.",
        }
    return {
        "instruction": "Пиши от первого лица, женский род.",
            "responded": "соискательница откликнулась",
        "consistency": "будь последовательна",
        "ready": "готова",
        "ready_title": "Готова",
        "default_questionnaire_answer": "Готова рассказать подробнее на собеседовании.",
    }


def questionnaire_default_answer() -> str:
    if CONFIG.questionnaire_default_answer in (
        _BUILTIN_QUESTIONNAIRE_DEFAULT_ANSWER,
        "Готов рассказать подробнее на собеседовании.",
        "Готов(а) рассказать подробнее на собеседовании.",
        "Подробнее расскажу на собеседовании.",
    ):
        return applicant_gender_forms()["default_questionnaire_answer"]
    return CONFIG.questionnaire_default_answer

# Cache for _url_pages_map — invalidated in save_config() when url_pool mutates.
_url_pages_map_cache: dict | None = None
_url_pool_version: int = 0


def _url_entry(item) -> dict:
    """Нормализует элемент url_pool в {url, pages}."""
    if isinstance(item, str):
        return {"url": item.strip(), "pages": CONFIG.pages_per_url}
    return {"url": item.get("url", "").strip(), "pages": int(item.get("pages", CONFIG.pages_per_url))}


def valid_list_item(key: str, item) -> bool:
    """Element check for list settings whose bad items crash snapshot/collection."""
    if key == "llm_profiles":
        return isinstance(item, dict) and all(
            isinstance(item.get(f), str) for f in ("name", "api_key", "base_url", "model") if f in item)
    if key == "url_pool":
        if isinstance(item, str):
            return True
        try:
            return isinstance(item, dict) and isinstance(item.get("url", ""), str) and int(item.get("pages", 1)) >= 1
        except (TypeError, ValueError):
            return False
    if key in ("allowed_schedules", "title_include_keywords", "title_exclude_keywords"):
        return isinstance(item, str)
    return True


def _url_pages_map() -> dict:
    """Возвращает {url_str: pages} из CONFIG.url_pool."""
    global _url_pages_map_cache
    if _url_pages_map_cache is None:
        _url_pages_map_cache = {e["url"]: e["pages"] for u in CONFIG.url_pool for e in [_url_entry(u)]}
    return _url_pages_map_cache


_CONFIG_KEYS = [
    'human_mode_enabled',
    'human_active_hours',
    'human_apply_delay_min',
    'human_apply_delay_max',
    'human_burst_size_min',
    'human_burst_size_max',
    'human_burst_pause_min_sec',
    'human_burst_pause_max_sec',
    'human_captcha_backoff_hours',

    "tg_alert_interview_enabled",
    "tg_alert_offer_enabled",
    "tg_alert_hr_question_enabled",
    "tg_alert_account_blocked_enabled",
    "tg_alert_daily_limit_enabled",

    "telegram_bot_token", "telegram_chat_id", "telegram_captcha_enabled",
    "telegram_status_enabled", "telegram_status_interval_min",
    "captcha_llm_enabled",
    "pages_per_url", "max_concurrent", "response_delay", "pause_between_cycles", "remote_it_only",
    "limit_check_interval", "resume_touch_interval", "batch_responses", "min_salary",
    "auto_pause_errors", "questionnaire_default_answer", "llm_fill_questionnaire", "llm_check_questionnaire_claims",
    "skip_inconsistent", "use_oauth_apply", "auto_pick_resume", "default_client_mode", "daily_apply_limit", "stop_on_hh_limit", "llm_check_interval",
    "filter_agencies", "filter_low_competition", "search_period_days",
    "min_employer_rating", "min_employer_reviews", "min_recommendations_percent",
    "skip_auto_response_vacancies", "prefer_quick_responses", "accredited_it_only",
    "hh_daily_limit", "fresh_vacancies_mode", "fresh_vacancy_hours", "fresh_apply_reserve", "prefer_hh_signals", "automation_paused",
    "hh_region", "llm_applicant_gender", "llm_auto_send", "llm_enabled",
    "llm_ws_push_enabled", "use_websocket_realtime", "chat_use_oauth", "llm_use_quick_replies",
    "hh_ai_letter_first_try", "related_vacancies_enabled", "hh_proxy_url",
]


def _coerce_config_value(key: str, value):
    """Coerce a persisted value without Python's ``bool('false')`` trap."""
    current = getattr(CONFIG, key)
    expected = type(current)
    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("true", "1", "yes", "on"):
                return True
            if normalized in ("false", "0", "no", "off"):
                return False
        raise ValueError(f"{key} expects bool")
    if expected in (int, float):
        if isinstance(value, bool):
            raise ValueError(f"{key} expects {expected.__name__}")
        return expected(value)
    if expected is str:
        return str(value)
    if expected in (list, dict):
        if not isinstance(value, expected):
            raise ValueError(f"{key} expects {expected.__name__}")
        return value
    if not isinstance(value, expected):
        raise ValueError(f"{key} expects {expected.__name__}")
    return value


def hh_base() -> str:
    """Базовый URL HH с учётом регионального поддомена.
    Пусто → https://hh.ru. С регионом «syktyvkar» → https://syktyvkar.hh.ru.
    OAuth (`hh.ru/oauth/`) и chatik (`chatik.hh.ru`) всегда основной домен — region не применяется.
    """
    region = (getattr(CONFIG, "hh_region", "") or "").strip().lower()
    # Защита: только [a-z0-9-], чтобы не сделать SSRF через переменную.
    import re as _re
    if region and _re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", region):
        return f"https://{region}.hh.ru"
    return "https://hh.ru"


def hh_url(path: str) -> str:
    """Собирает URL: hh_base() + path. path должен начинаться со слеша."""
    if not path.startswith("/"):
        path = "/" + path
    return hh_base() + path


def config_snapshot() -> dict:
    """Полный JSON-совместимый снимок текущих настроек приложения.

    Функция не пишет на диск. Она также используется мобильной авторизацией,
    чтобы первый созданный ``config.json`` сразу содержал всю схему, а не
    только namespaced-секцию ``mobile_auth``.
    """
    data = {k: getattr(CONFIG, k) for k in _CONFIG_KEYS}
    data["captcha_model_name"] = CONFIG.captcha_model_name
    data["questionnaire_templates"] = CONFIG.questionnaire_templates
    data["letter_templates"] = CONFIG.letter_templates
    data["allowed_schedules"] = CONFIG.allowed_schedules
    data["title_include_keywords"] = CONFIG.title_include_keywords
    data["title_exclude_keywords"] = CONFIG.title_exclude_keywords
    data["auto_apply_tests"] = CONFIG.auto_apply_tests
    data["use_oauth_apply"] = CONFIG.use_oauth_apply
    data["default_client_mode"] = CONFIG.default_client_mode
    data["url_pool"] = CONFIG.url_pool
    data["llm_api_key"] = CONFIG.llm_api_key
    data["llm_base_url"] = CONFIG.llm_base_url
    data["llm_model"] = CONFIG.llm_model
    data["llm_applicant_gender"] = CONFIG.llm_applicant_gender
    data["llm_enabled"] = CONFIG.llm_enabled
    data["llm_auto_send"] = CONFIG.llm_auto_send
    data["llm_use_cover_letter"] = CONFIG.llm_use_cover_letter
    data["llm_use_resume"] = CONFIG.llm_use_resume
    data["llm_system_prompt"] = CONFIG.llm_system_prompt
    data["llm_profiles"] = CONFIG.llm_profiles
    data["llm_profile_mode"] = CONFIG.llm_profile_mode
    data["llm_openclaw_enabled"] = CONFIG.llm_openclaw_enabled
    data["llm_openclaw_agent"] = CONFIG.llm_openclaw_agent
    data["llm_openclaw_model"] = CONFIG.llm_openclaw_model
    data["llm_openclaw_timeout"] = CONFIG.llm_openclaw_timeout
    return data


def save_config():
    """Сохранить текущий CONFIG на диск."""
    global _url_pages_map_cache, _url_pool_version
    data = config_snapshot()
    target_file = CONFIG_FILE
    _url_pool_version += 1
    _url_pages_map_cache = None
    def _write():
        with _config_write_lock:
            # Mobile OTP settings live in the same config.json under a namespaced
            # object. Preserve them when the legacy bot Config is saved.
            try:
                existing = json.loads(target_file.read_text(encoding="utf-8")) if target_file.exists() else {}
                if isinstance(existing, dict) and isinstance(existing.get("mobile_auth"), dict):
                    data["mobile_auth"] = existing["mobile_auth"]
            except (OSError, json.JSONDecodeError):
                pass
            tmp = target_file.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                tmp.replace(target_file)
                try:
                    import os as _os
                    _os.chmod(target_file, 0o600)  # PII (phone, telegram в letter_templates)
                except Exception:
                    pass
            except Exception as e:
                log_debug(f"save_config error: {e}")
                tmp.unlink(missing_ok=True)
    (_schedule_save(_write) if _schedule_save else threading.Thread(target=_write, daemon=True).start())


def load_config():
    """Загрузить CONFIG с диска (если файл есть)."""
    global _url_pages_map_cache
    if not CONFIG_FILE.exists():
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in _CONFIG_KEYS:
            if k in data:
                try:
                    setattr(CONFIG, k, _coerce_config_value(k, data[k]))
                except (ValueError, TypeError):
                    log_debug(f"⚠️ Невалидное значение конфига {k}={data[k]!r}, пропуск")
        if isinstance(data.get("captcha_model_name"), str):
            from app.captcha_models import model_exists
            if model_exists(data["captcha_model_name"]):
                CONFIG.captcha_model_name = data["captcha_model_name"]
        if "questionnaire_templates" in data and isinstance(data["questionnaire_templates"], list):
            CONFIG.questionnaire_templates = data["questionnaire_templates"]
        if "letter_templates" in data and isinstance(data["letter_templates"], list):
            CONFIG.letter_templates = data["letter_templates"]
        if "url_pool" in data and isinstance(data["url_pool"], list):
            CONFIG.url_pool = [u for u in data["url_pool"] if valid_list_item("url_pool", u)]
            # load_config вызывается при старте уже после импортов. Не оставляем
            # map, построенный ранее из class defaults/старого значения.
            _url_pages_map_cache = None
        for k in ("llm_api_key", "llm_base_url", "llm_model", "llm_system_prompt", "llm_applicant_gender"):
            if k in data and isinstance(data[k], str):
                setattr(CONFIG, k, data[k])
        for k in ("llm_enabled", "llm_auto_send", "llm_use_cover_letter", "llm_use_resume", "llm_fill_questionnaire"):
            if k in data:
                try:
                    setattr(CONFIG, k, _coerce_config_value(k, data[k]))
                except (ValueError, TypeError):
                    log_debug(f"⚠️ Невалидное boolean-значение {k}={data[k]!r}, пропуск")
        if "allowed_schedules" in data and isinstance(data["allowed_schedules"], list):
            CONFIG.allowed_schedules = data["allowed_schedules"]
        if "title_include_keywords" in data and isinstance(data["title_include_keywords"], list):
            CONFIG.title_include_keywords = data["title_include_keywords"]
        if "title_exclude_keywords" in data and isinstance(data["title_exclude_keywords"], list):
            CONFIG.title_exclude_keywords = data["title_exclude_keywords"]
        if "auto_apply_tests" in data:
            try:
                CONFIG.auto_apply_tests = _coerce_config_value("auto_apply_tests", data["auto_apply_tests"])
            except (ValueError, TypeError):
                log_debug(f"⚠️ Невалидное boolean-значение auto_apply_tests={data['auto_apply_tests']!r}, пропуск")
        if "use_oauth_apply" in data:
            try:
                CONFIG.use_oauth_apply = _coerce_config_value("use_oauth_apply", data["use_oauth_apply"])
            except (ValueError, TypeError):
                log_debug(f"⚠️ Невалидное boolean-значение use_oauth_apply={data['use_oauth_apply']!r}, пропуск")
        if "default_client_mode" in data:
            _mode = str(data["default_client_mode"]).strip().lower()
            # Мусорное значение → "web" (не "auto": с Phase 2 auto сможет выбирать mobile).
            CONFIG.default_client_mode = _mode if _mode in ("web", "mobile", "oauth", "auto") else "web"
        if "llm_profiles" in data and isinstance(data["llm_profiles"], list):
            CONFIG.llm_profiles = [p for p in data["llm_profiles"] if valid_list_item("llm_profiles", p)]
        if "llm_profile_mode" in data and isinstance(data["llm_profile_mode"], str):
            CONFIG.llm_profile_mode = data["llm_profile_mode"]
        if "llm_openclaw_enabled" in data:
            try:
                CONFIG.llm_openclaw_enabled = _coerce_config_value(
                    "llm_openclaw_enabled", data["llm_openclaw_enabled"])
            except (ValueError, TypeError):
                log_debug(
                    f"⚠️ Невалидное boolean-значение "
                    f"llm_openclaw_enabled={data['llm_openclaw_enabled']!r}, пропуск"
                )
        if "llm_openclaw_agent" in data and isinstance(data["llm_openclaw_agent"], str):
            CONFIG.llm_openclaw_agent = data["llm_openclaw_agent"]
        if "llm_openclaw_model" in data and isinstance(data["llm_openclaw_model"], str):
            CONFIG.llm_openclaw_model = data["llm_openclaw_model"]
        if "llm_openclaw_timeout" in data:
            try:
                CONFIG.llm_openclaw_timeout = int(data["llm_openclaw_timeout"])
            except Exception:
                pass
        # Migration: if no profiles defined but old-style api_key exists, create one profile
        if not CONFIG.llm_profiles and CONFIG.llm_api_key:
            CONFIG.llm_profiles = [{"name": "Основной", "api_key": CONFIG.llm_api_key,
                "base_url": CONFIG.llm_base_url, "model": CONFIG.llm_model, "enabled": True}]
    except Exception as e:
        log_debug(f"load_config error: {e}")


def save_accounts(*, wait: bool = False):
    """Save an isolated snapshot; wait=True is a durable, fail-closed barrier.

    Both modes use the same ordered queue, so an older asynchronous snapshot
    cannot overwrite a synchronously reserved receipt-check attempt.
    """
    # Lazy import also avoids the config/storage initialization cycle fallback.
    from app.storage import _atomic_write_json, _schedule_save as schedule_save

    with _accounts_schedule_lock:
        snapshot = copy.deepcopy([
            {k: v for k, v in acc.items() if not k.startswith("_")}
            for acc in accounts_data
        ])
        target_file = ACCOUNTS_FILE

        def _write():
            with _accounts_write_lock:
                try:
                    _atomic_write_json(target_file, snapshot)
                except Exception as exc:
                    log_debug(f"save_accounts error: {type(exc).__name__}")
                    if wait:
                        raise

        if wait:
            schedule_save(_write, wait=True)
        else:
            schedule_save(_write)


def load_accounts():
    """Загрузить accounts_data с диска (если файл есть)."""
    if not ACCOUNTS_FILE.exists():
        save_accounts()  # первый запуск — сохраняем текущие дефолты
        return
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # Аудит 2026-08-17 #20: раньше `and data` игнорировало валидный
            # пустой список [] → удалённые из UI аккаунты «воскресали» из
            # прежней in-memory копии после reload. Пустой список — легальное
            # состояние, атомарно заменяем содержимое в любом случае.
            accounts_data.clear()
            accounts_data.extend(data)
    except Exception as e:
        log_debug(f"load_accounts error: {e}")

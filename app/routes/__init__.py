"""
FastAPI app creation and route registration.
"""

import asyncio
import contextlib
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Singleton bot/manager are created in app.instances so every router module
# can import them without pulling in the package __init__ (avoids circular imports).
from app.instances import bot, manager  # re-exported for back-compat
from app.logging_utils import log_debug


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    """FastAPI lifespan — единая точка startup + graceful shutdown.

    ВАЖНО: при наличии `lifespan=`, FastAPI ИГНОРИРУЕТ все `@app.on_event("startup")`
    хендлеры. Поэтому startup-логика (load_accounts, bot.start, broadcast_loop) должна
    жить ЗДЕСЬ, иначе бот не загрузит accounts и не запустит воркеров (r13-1 #1).
    """
    # ── startup ──
    broadcast_task = None
    captcha_task = None
    status_task = None
    try:
        from app.storage import _cleanup_stale_tmp
        _cleanup_stale_tmp()  # подметаем config.tmp/accounts.tmp от прошлых crash'ей
        from app.config import CONFIG, load_accounts
        load_accounts()
        # ENV → CONFIG для TG (deploy-friendly: одни креды на captcha и alerts).
        # Приоритет TELEGRAM_* (наши) > HH_TELEGRAM_* (PR #27 by Antiokh).
        _tg_token = (os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                     or os.environ.get("HH_TELEGRAM_BOT_TOKEN", "").strip())
        _tg_chat = (os.environ.get("TELEGRAM_CHAT_ID", "").strip()
                    or os.environ.get("HH_TELEGRAM_CHAT_ID", "").strip())
        if _tg_token and not CONFIG.telegram_bot_token:
            CONFIG.telegram_bot_token = _tg_token
        if _tg_chat and not CONFIG.telegram_chat_id:
            CONFIG.telegram_chat_id = _tg_chat
        from app.telegram_status import install_status_tracking, status_heartbeat
        from app import telegram_notify
        install_status_tracking(bot)
        bot.start()
        from app.captcha_worker import captcha_orchestrator
        captcha_task = asyncio.create_task(captcha_orchestrator(bot), name="captcha_orchestrator")
        # Let the orchestrator create the Telegram bot and its HTTP session.
        await asyncio.sleep(0)
        telegram_bot = getattr(bot, "telegram_captcha_bot", None)
        if telegram_bot is not None and telegram_bot._session is not None:
            from app.telegram_menu import BOT_COMMANDS
            try:
                await telegram_bot._set_commands(BOT_COMMANDS)
            except Exception:
                log_debug("telegram: command menu registration failed")
        # send_once uses HH credentials; align with dashboard credentials.
        if CONFIG.telegram_bot_token and CONFIG.telegram_chat_id:
            os.environ["HH_TELEGRAM_BOT_TOKEN"] = CONFIG.telegram_bot_token
            os.environ["HH_TELEGRAM_CHAT_ID"] = CONFIG.telegram_chat_id
        if CONFIG.telegram_status_enabled and telegram_notify.is_configured():
            status_task = asyncio.create_task(
                status_heartbeat(bot, getattr(bot, "telegram_captcha_bot", None),
                                 CONFIG.telegram_status_interval_min), name="telegram_status")
        from app.routes.core import broadcast_loop
        # Сохраняем handle: иначе task может быть garbage-collected до завершения
        # (Python docs warn) и shutdown не может его отменить (kimi-r14-1 #1).
        broadcast_task = asyncio.create_task(broadcast_loop(), name="broadcast_loop")
        log_debug("lifespan: startup ok — accounts loaded, bot started, broadcast_loop scheduled")
    except Exception as e:
        log_debug(f"lifespan startup error: {e}")
        raise

    yield

    # ── shutdown ──
    if status_task is not None:
        status_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(status_task, timeout=5)
    if captcha_task is not None:
        captcha_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(captcha_task, timeout=5)
    if broadcast_task is not None:
        broadcast_task.cancel()
        try:
            await broadcast_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log_debug(f"lifespan broadcast_task error: {e}")
    try:
        log_debug("lifespan: stopping bot...")
        bot.stop()
    except Exception as e:
        log_debug(f"lifespan bot.stop error: {e}")
    try:
        from app.storage import _save_executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: _save_executor.shutdown(wait=True))
    except Exception as e:
        log_debug(f"lifespan save_executor shutdown error: {e}")


app = FastAPI(title="HH Bot Dashboard", lifespan=_lifespan)

STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── API key middleware ──────────────────────────────────────────────────────
# Закрывает все "attacker reaches localhost" сценарии: token exfil через
# /api/account/{idx}/oauth_token, config poison через /api/raw/config, DoS
# через /api/llm_run_now и т.д. Один middleware вместо отдельных проверок.
#
# Активируется если установлен `HH_BOT_API_KEY` env. Без env — пропускает всё
# (backward compat для локального dev на 127.0.0.1).
_API_KEY = os.environ.get("HH_BOT_API_KEY", "").strip()
# GET-only публичные пути. "/" — ТОЛЬКО точное совпадение: startswith("/")
# совпадал бы с ЛЮБЫМ путём и при заданном ключе открывал бы все GET-эндпоинты
# (включая /api/raw/config с llm_api_key) без auth (audit CRITICAL #1, follow-up).
_PUBLIC_PATHS_EXACT = ("/", "/favicon.ico", "/healthz")
_PUBLIC_PATH_PREFIXES = ("/static/",)
# Пути, требующие API-key ВСЕГДА — даже при пустом HH_BOT_API_KEY и
# HH_BOT_UNSAFE_EXPOSE=1: в бэкапе ВСЕ секреты (cookies, oauth_tokens,
# llm_api_key), их нельзя отдавать без auth (audit CRITICAL #1).
_ALWAYS_AUTH_PREFIXES = ("/api/backup",)


_SAFE_METHODS = frozenset(("GET", "HEAD", "OPTIONS"))


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    path = request.url.path
    # State-changing методы запрещают ?api_key= (CSRF: form POST с query-string проходил
    # без CORS preflight; теперь нужен X-API-Key header, см. kimi-r13-4 #3).
    if request.method in _SAFE_METHODS:
        presented = request.headers.get("X-API-Key", "") or request.query_params.get("api_key", "")
    else:
        presented = request.headers.get("X-API-Key", "")
    # Backup всегда за API-key: если ключ не задан/не совпадает — 401 на любом методе.
    if any(path == p or path.startswith(p) for p in _ALWAYS_AUTH_PREFIXES):
        if not _API_KEY or not presented or not secrets.compare_digest(str(presented), str(_API_KEY)):
            log_debug(f"auth_denied path={path} method={request.method} ip={request.client.host if request.client else '?'}")
            resp = JSONResponse(
                {"ok": False, "error": "API key required for backup operations"},
                status_code=401,
            )
            _set_security_headers(resp)
            return resp
    # Если ключ не задан — auth выключен (опасно, но не ломает существующие deployments).
    if not _API_KEY:
        resp = await call_next(request)
        _set_security_headers(resp)
        return resp
    if request.method == "GET" and (
        path in _PUBLIC_PATHS_EXACT
        or any(path.startswith(pfx) for pfx in _PUBLIC_PATH_PREFIXES)
    ):
        resp = await call_next(request)
        _set_security_headers(resp)
        return resp
    if not presented or not secrets.compare_digest(str(presented), str(_API_KEY)):
        log_debug(f"auth_denied path={path} method={request.method} ip={request.client.host if request.client else '?'}")
        # 401 тоже должен иметь security headers — clickjacking/MIME-sniffing
        # одинаково опасны на error responses (kimi-r14-1 #9).
        resp = JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
        _set_security_headers(resp)
        return resp
    resp = await call_next(request)
    _set_security_headers(resp)
    return resp


def _set_security_headers(resp):
    """CSP + базовые security headers (kimi-r13-4 #6)."""
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self' ws: wss:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")


def api_key_required() -> str:
    """Helper для WS handshake: вернуть текущий API key (или '' если выключено)."""
    return _API_KEY


# Public /healthz — для k8s/docker liveness probe. Не требует API key.
@app.get("/healthz")
async def healthz():
    n_accounts = len(bot.account_states) if hasattr(bot, "account_states") else 0
    n_temp = len(bot.temp_sessions) if hasattr(bot, "temp_sessions") else 0
    n_active_temp = len(bot.temp_states) if hasattr(bot, "temp_states") else 0
    return {"ok": True, "accounts": n_accounts, "temp_sessions": n_temp,
            "active_temp_sessions": n_active_temp}

# -- Register routers (imported after app is created) --
from app.routes.core import router as core_router          # noqa: E402
from app.routes.accounts import router as accounts_router  # noqa: E402
from app.routes.sessions import router as sessions_router  # noqa: E402
from app.routes.data import router as data_router          # noqa: E402
from app.routes.apply import router as apply_router        # noqa: E402
from app.routes.settings import router as settings_router  # noqa: E402
from app.routes.llm import router as llm_router            # noqa: E402
from app.routes.debug import router as debug_router        # noqa: E402
from app.routes.ws import router as ws_router              # noqa: E402
# UI-integrations (прототипы mobile API → REST routes для dashboard)
from app.routes.hr_activity import router as hr_activity_router            # noqa: E402
from app.routes.preflight import router as preflight_router                # noqa: E402
from app.routes.skills_recommend import router as skills_recommend_router  # noqa: E402
from app.routes.counters_v2 import router as counters_v2_router            # noqa: E402
from app.routes.hh_recommendations import router as hh_recommendations_router  # noqa: E402
from app.routes.autologin import router as autologin_router                # noqa: E402
from app.routes.account_mode import router as account_mode_router          # noqa: E402
from app.routes.hedi import router as hedi_router          # noqa: E402
from app.routes.ui_skills import router as ui_skills_router    # noqa: E402
from app.routes.ui_reviews import router as ui_reviews_router  # noqa: E402
from app.routes.mobile_auth import router as mobile_auth_router  # noqa: E402
from app.routes.auto_response import router as auto_response_router  # noqa: E402
from app.routes.career_visibility import router as career_visibility_router  # noqa: E402
from app.routes.discovery import router as discovery_router  # noqa: E402
from app.routes.captcha_models import router as captcha_models_router  # noqa: E402

app.include_router(core_router)
app.include_router(accounts_router)
app.include_router(sessions_router)
app.include_router(data_router)
app.include_router(apply_router)
app.include_router(settings_router)
app.include_router(llm_router)
app.include_router(debug_router)
app.include_router(ws_router)
app.include_router(hr_activity_router)
app.include_router(preflight_router)
app.include_router(skills_recommend_router)
app.include_router(counters_v2_router)
app.include_router(hh_recommendations_router)
app.include_router(autologin_router)
app.include_router(account_mode_router)
app.include_router(hedi_router)
app.include_router(ui_skills_router)
app.include_router(ui_reviews_router)
app.include_router(mobile_auth_router)
app.include_router(auto_response_router)
app.include_router(career_visibility_router)
app.include_router(discovery_router)
app.include_router(captcha_models_router)
from app.routes.questionnaire_trace import router as questionnaire_trace_router
app.include_router(questionnaire_trace_router)


@app.post('/api/telegram/test')
async def telegram_test():
    """Send a test photo without exposing saved credentials."""
    import base64
    import aiohttp
    from app.telegram_bot import TelegramCaptchaBot
    from app.config import CONFIG
    if not CONFIG.telegram_bot_token or not CONFIG.telegram_chat_id:
        return {'ok': False, 'error': 'Задайте TG token и chat ID'}
    test_bot = TelegramCaptchaBot()
    try:
        test_bot._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAeklEQVR4nO3PUQkAIBTAwJfJTEY0oCH8OITBAtxmnf11wwUNaEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQgBY0oAUNaEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQgBY0oAUNaEEDWtCAFjSgBQ1oQQNa0IAWPHYBOXKhLZzLTGoAAAAASUVORK5CYII=')
        await test_bot._call('sendPhoto', {'chat_id': test_bot.chat_id, 'caption': '✅ TG captcha подключён'}, image)
        return {'ok': True}
    except Exception:
        return {'ok': False, 'error': 'Не удалось отправить фото в TG'}
    finally:
        await test_bot.stop()


@app.get('/api/telegram/status-settings')
async def telegram_status_settings():
    from app.config import CONFIG
    return {"enabled": CONFIG.telegram_status_enabled,
            "interval_min": CONFIG.telegram_status_interval_min}

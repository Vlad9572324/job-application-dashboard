"""HH.RU Auto Response Bot - FastAPI Web Dashboard"""
import os
import signal
import sys
from pathlib import Path

# A frozen release keeps mutable data, CAPTCHA weights and bundled static files
# beside the executable. Source and Docker runs retain their current paths.
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)

from app.routes import app
import uvicorn


_SAFE_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _install_shutdown_hook():
    """Gracefully stop bot + flush save executor on SIGTERM/SIGINT.
    Без этого daemon-threads умирают мid-write → corrupted JSON.
    """
    from app.instances import bot as _bot
    from app.storage import _save_executor

    def _handler(signum, frame):
        sys.stderr.write(f"\n[hh-bot] signal {signum} → graceful shutdown...\n")
        try:
            _bot.stop()
        except Exception as e:
            sys.stderr.write(f"[hh-bot] bot.stop() error: {e}\n")
        try:
            _save_executor.shutdown(wait=True, cancel_futures=False)
        except Exception:
            pass
        # Pass to default handler to actually exit
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass  # signal not available on this platform / not in main thread


def _resolve_host() -> str:
    """Validate HH_BOT_HOST: by default only loopback allowed.
    Non-loopback bind требует HH_BOT_API_KEY + явный HH_BOT_UNSAFE_EXPOSE=1
    (kimi-search-3 #9: defense против env injection; audit CRITICAL #1:
    без API-ключа наружу нельзя даже с UNSAFE_EXPOSE).

    Исключение — container opt-in HH_BOT_ALLOW_CONTAINER_BIND=1: разрешает
    bind ТОЛЬКО на 0.0.0.0 без ключа. Внутри Docker слушать 127.0.0.1
    бессмысленно: DNAT направляет published-трафик на container IP, а не на
    container loopback, поэтому дашборд был бы недоступен даже с хоста.
    Граница безопасности при opt-in — host-side loopback publish
    (`127.0.0.1:8000:8000` в docker-compose `ports`), не bind внутри.
    Произвольный non-loopback opt-in НЕ разрешает — там по-прежнему нужен
    ключ + HH_BOT_UNSAFE_EXPOSE (fail-closed сохранён полностью).
    """
    raw = os.environ.get("HH_BOT_HOST", "127.0.0.1").strip()
    if raw in _SAFE_HOSTS:
        return raw
    # Ключ проверяем ПЕРВЫМ: любой non-loopback bind, включая container opt-in,
    # без HH_BOT_API_KEY = LAN-доступ к cookies/токенам/управлению без auth.
    # Аудит 2026-08-17 CRITICAL #4: раньше ALLOW_CONTAINER_BIND=1 давал bind
    # 0.0.0.0 без ключа с одним лишь WARNING — стирание .env полностью
    # оголяло dashboard в LAN. Теперь fail-closed для ВСЕХ веток.
    if not os.environ.get("HH_BOT_API_KEY", "").strip():
        raise RuntimeError(
            f"HH_BOT_HOST={raw!r}: non-loopback bind без HH_BOT_API_KEY запрещён "
            f"(включая HH_BOT_ALLOW_CONTAINER_BIND=1 и HH_BOT_UNSAFE_EXPOSE=1). "
            f"Задай API-ключ или верни host на loopback."
        )
    # Container opt-in: с ключом bind на 0.0.0.0 допустим для Docker DNAT.
    if os.environ.get("HH_BOT_ALLOW_CONTAINER_BIND", "").strip() in ("1", "true", "yes"):
        if raw == "0.0.0.0":
            return raw
    if os.environ.get("HH_BOT_UNSAFE_EXPOSE", "").strip() in ("1", "true", "yes"):
        return raw  # admin signed off, ключ задан
    sys.stderr.write(
        f"[hh-bot] HH_BOT_HOST={raw!r} blocked: not in {_SAFE_HOSTS}. "
        f"Set HH_BOT_UNSAFE_EXPOSE=1 to override (API key задан).\n"
    )
    return "127.0.0.1"


if __name__ == "__main__":
    try:
        host = _resolve_host()
    except RuntimeError as e:
        sys.stderr.write(f"[hh-bot] fatal: {e}\n")
        sys.exit(1)
    port = int(os.environ.get("HH_BOT_PORT", "8000"))
    _install_shutdown_hook()
    uvicorn.run(app, host=host, port=port, log_level="info")

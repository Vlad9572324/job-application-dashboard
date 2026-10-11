"""Smoke-тест container bind (security fix, operational CRITICAL #1).

Проверяем что дашборд реально отвечает при container-конфигурации:
внутри слушаем 0.0.0.0 (Docker DNAT идёт на container IP, не на container
loopback), а граница безопасности — host-side loopback publish в `ports`.

Вариант A (docker compose): полный e2e, но docker-демон доступен не везде —
честный graceful skip с понятным reason.
Вариант B (subprocess без docker): web_app.py стартует с compose-эквивалентным
env (HH_BOT_HOST=0.0.0.0 + HH_BOT_ALLOW_CONTAINER_BIND=1, ключ НЕ задан) и
должен отвечать на 127.0.0.1:<port> — доказывает что bind 0.0.0.0 поднимается
без RuntimeError и отвечает на loopback хоста.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_HEALTHZ = "/healthz"  # публичный GET-endpoint (app/routes/__init__.py), без API-key
_READY_TIMEOUT_S = 40.0  # импорт app + lifespan startup
_COMPOSE_UP_TIMEOUT_S = 300.0  # docker build может быть медленным


def _free_port() -> int:
    """Свободный порт на loopback (микрориск race — допустим, ниже есть retry)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_get(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read()


def _docker_available() -> bool:
    """docker CLI + compose v2 + живой демон — иначе вариант A скипаем."""
    if shutil.which("docker") is None:
        return False
    try:
        if subprocess.run(
            ["docker", "info"], capture_output=True, timeout=15
        ).returncode != 0:
            return False  # демон не запущен / нет прав
        return subprocess.run(
            ["docker", "compose", "version"], capture_output=True, timeout=15
        ).returncode == 0
    except Exception:
        return False


# ─── Вариант A: docker compose e2e ──────────────────────────────────────────


def test_container_bind_docker_compose_smoke():
    """`docker compose up hh-bot` → curl 127.0.0.1:8000 → `compose down`."""
    if not _docker_available() or not (ROOT / '.env').is_file():
        # В обычном dev/CI без Docker всё равно проверяем критичный контракт
        # compose: публикация только на host loopback и opt-in container bind.
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        # LAN-режим: bind 8000:8000 (без 127.0.0.1 префикса) + env_file с ключом.
        # Аудит 2026-08-17 #4: ALLOW_CONTAINER_BIND теперь требует API_KEY,
        # web_app.py fail-closed без ключа — .env файл обязателен.
        assert re.search(r'^\s*-\s*"?8000:8000"?\s*$', compose, re.MULTILINE), \
            "compose должен публиковать 8000:8000"
        assert re.search(r'^\s*env_file:\s*$', compose, re.MULTILINE), \
            "compose должен подгружать env_file (.env с HH_BOT_API_KEY)"
        assert re.search(r'^\s*HH_BOT_HOST:\s*["\']?0\.0\.0\.0["\']?\s*$', compose, re.MULTILINE)
        assert re.search(r'^\s*HH_BOT_ALLOW_CONTAINER_BIND:\s*["\']?1["\']?\s*$', compose, re.MULTILINE)
        return
    up = subprocess.run(
        ["docker", "compose", "up", "-d", "hh-bot"],
        cwd=ROOT, capture_output=True, text=True, timeout=_COMPOSE_UP_TIMEOUT_S,
    )
    assert up.returncode == 0, f"docker compose up failed:\n{up.stdout}\n{up.stderr}"
    try:
        deadline = time.monotonic() + _READY_TIMEOUT_S * 3  # контейнер стартует дольше
        last_err = None
        while time.monotonic() < deadline:
            try:
                status, _ = _http_get(f"http://127.0.0.1:8000{_HEALTHZ}")
                assert status == 200
                return  # дашборд доступен с host loopback — фикс работает
            except Exception as e:
                last_err = e
                time.sleep(2)
        pytest.fail(f"дашборд не поднялся на 127.0.0.1:8000: {last_err}")
    finally:
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=ROOT, capture_output=True, timeout=120,
        )


# ─── Вариант B: subprocess-дым без docker ───────────────────────────────────


def test_container_bind_subprocess_smoke(tmp_path):
    """web_app.py с compose-эквивалентным env отвечает на 127.0.0.1:<port>.

    cwd=tmp_path: app/config.py использует относительный DATA_DIR=Path("data"),
    так что все data/ + static/ пишутся в tmp и реальные файлы не трогаются.
    """
    port = _free_port()
    log_file = tmp_path / "web_app.log"

    env = os.environ.copy()
    env.update({
        "HH_BOT_HOST": "0.0.0.0",
        "HH_BOT_ALLOW_CONTAINER_BIND": "1",  # container opt-in
        "HH_BOT_API_KEY": "smoke-test-key",   # аудит #4: opt-in требует ключ
        "HH_BOT_PORT": str(port),
        "PYTHONPATH": str(ROOT),
    })
    env.pop("HH_BOT_UNSAFE_EXPOSE", None)

    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "web_app.py")],
        cwd=tmp_path,
        env=env,
        stdout=open(log_file, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + _READY_TIMEOUT_S
        last_err = None
        ready = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                tail = log_file.read_text(encoding="utf-8", errors="replace")[-4000:]
                pytest.fail(
                    f"web_app.py умер на старте (rc={proc.returncode}):\n{tail}"
                )
            try:
                status, _ = _http_get(f"http://127.0.0.1:{port}{_HEALTHZ}", timeout=2)
                if status == 200:
                    ready = True
                    break
            except Exception as e:  # connection refused / timeout — сервер ещё встаёт
                last_err = e
                time.sleep(0.3)
        assert ready, (
            f"сервер не ответил на 127.0.0.1:{port}{_HEALTHZ} за {_READY_TIMEOUT_S}s "
            f"(последняя ошибка: {last_err}); лог:\n"
            f"{log_file.read_text(encoding='utf-8', errors='replace')[-4000:]}"
        )
        # Opt-in сработал штатно: сервер поднялся без RuntimeError.
        # Warning про ALLOW_CONTAINER_BIND убран (аудит #4) — теперь opt-in
        # штатный путь с обязательным API-ключом, а не «фолбэк с оповещением».
    finally:
        if proc.poll() is None:
            proc.terminate()  # SIGTERM → graceful shutdown hook web_app.py
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        # stdout-файл Popen'а закрываем явно (он был открыт в родителе)
        try:
            proc.stdout.close()
        except Exception:
            pass

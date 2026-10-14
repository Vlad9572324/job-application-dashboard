#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke-тест мобильного API HH.ru (read-only health-check).

Берёт первый живой OAuth-токен из data/oauth_tokens.json
(expires_at > now; ключи с просроченным токеном пропускаются),
делает GET-запросы к 10 эндпоинтам и печатает таблицу
`endpoint | status | ms | ok?` (ok = status < 400).

Тактика для мобильных заголовков: сначала запрос с базовыми
заголовками; если сервер вернул 406 — повтор с заголовками
мобильного приложения (x-force-app-access + User-Agent
ru.hh.android), такой эндпоинт помечается в таблице "(mobile-hdrs)".

Лог пишется в <log-dir>/mobile_smoke_YYYYMMDD.log (append, не
перезапись): timestamp запуска, те же строки таблицы и итог.

Exit code: 0 — все запросы ok; 1 — есть падения;
2 — нет файла токенов или живого токена.

Скрипт делает только GET-запросы (read-only по отношению к HH).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Все пути в коде бота относительные — работаем из корня репозитория.
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_BASE_URL = "https://api.hh.ru"
TOKENS_PATH = Path("data") / "oauth_tokens.json"
USER_AGENT_BASE = "job-application-dashboard/1.0"
USER_AGENT_MOBILE = "ru.hh.android/26.28.1"

# 10 эндпоинтов для health-check (только GET).
ENDPOINTS = [
    "/me",
    "/counters/user",
    "/negotiations_statistic/mine",
    "/vacancies/possible_job_offers",
    "/negotiations",
    "/saved_searches/vacancies",
    "/vacancies/favorited",
    "/vacancies/blacklisted",
    "/dictionaries",
    "/areas",
]


def base_headers(access_token: str) -> dict:
    """Базовые заголовки для api.hh.ru."""
    return {
        "User-Agent": USER_AGENT_BASE,
        "Authorization": f"Bearer {access_token}",
    }


def mobile_headers(access_token: str) -> dict:
    """Заголовки мобильного приложения: без них чисто мобильные
    эндпоинты (например /negotiations_statistic/mine) отдают 406."""
    return {
        "User-Agent": USER_AGENT_MOBILE,
        "Authorization": f"Bearer {access_token}",
        "x-force-app-access": "true",
    }


def _access_of(entry) -> "str | None":
    """Достаёт access_token из записи токенов, если запись валидна."""
    if isinstance(entry, dict):
        token = entry.get("access_token")
        if isinstance(token, str) and token:
            return token
    return None


def _expires_at(entry) -> float:
    """Достаёт expires_at (epoch) из записи; мусор/отсутствие = 0."""
    if isinstance(entry, dict):
        try:
            return float(entry.get("expires_at") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def load_tokens() -> "tuple[dict | None, str]":
    """Читает data/oauth_tokens.json.

    Возвращает (словарь токенов, "") при успехе либо (None, причина).
    """
    if not TOKENS_PATH.exists():
        return None, f"файл токенов не найден: {TOKENS_PATH}"
    try:
        data = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"не удалось прочитать {TOKENS_PATH}: {exc}"
    if not isinstance(data, dict) or not data:
        return None, f"в {TOKENS_PATH} нет непустого словаря с токенами"
    return data, ""


def pick_token(tokens: dict, token_key: "str | None" = None):
    """Выбирает живой токен: по явному ключу либо первый живой.

    Возвращает (key, access_token, "") при успехе
    либо (None, None, причина).
    """
    now = time.time()
    if token_key is not None:
        if token_key not in tokens:
            return None, None, f"ключ '{token_key}' не найден в {TOKENS_PATH}"
        entry = tokens[token_key]
        access = _access_of(entry)
        if access is None:
            return None, None, f"у ключа '{token_key}' нет access_token"
        if _expires_at(entry) <= now:
            return None, None, f"токен ключа '{token_key}' истёк (expires_at <= now)"
        return token_key, access, ""
    for key, entry in tokens.items():
        access = _access_of(entry)
        if not access:
            continue
        if _expires_at(entry) > now:
            return key, access, ""
    return None, None, "нет ни одного живого токена (expires_at > now)"


def check_endpoint(session: requests.Session, base_url: str, path: str,
                   access_token: str, timeout: float):
    """GET к эндпоинту; при 406 — повтор с mobile-заголовками.

    Возвращает (status | None, ms, used_mobile, error_text).
    status=None означает сетевую ошибку (таймаут, DNS и т.п.).
    """
    url = base_url.rstrip("/") + path
    used_mobile = False
    started = time.monotonic()
    try:
        resp = session.get(url, headers=base_headers(access_token), timeout=timeout)
        if resp.status_code == 406:
            # Чисто мобильный эндпоинт: пробуем с заголовками приложения.
            used_mobile = True
            resp = session.get(url, headers=mobile_headers(access_token),
                               timeout=timeout)
        status = resp.status_code
        error = ""
    except requests.RequestException as exc:
        status = None
        error = str(exc) or exc.__class__.__name__
    ms = int((time.monotonic() - started) * 1000)
    return status, ms, used_mobile, error


def render_table(results) -> "list[str]":
    """Собирает строки таблицы `endpoint | status | ms | ok?`."""
    rows = []
    for path, status, ms, used_mobile, _err in results:
        endpoint = path + (" (mobile-hdrs)" if used_mobile else "")
        status_s = str(status) if status is not None else "ERR"
        ok_s = "ok" if status is not None and status < 400 else "FAIL"
        rows.append((endpoint, status_s, str(ms), ok_s))
    header = ("endpoint", "status", "ms", "ok?")
    widths = [
        max(len(header[i]), *(len(r[i]) for r in rows))
        for i in range(len(header))
    ]
    lines = [" | ".join(h.ljust(w) for h, w in zip(header, widths))]
    lines.append("-+-".join("-" * w for w in widths))
    lines.extend(" | ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows)
    return lines


def parse_args() -> argparse.Namespace:
    """Разбирает аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Smoke-тест мобильного API HH.ru: 10 GET-запросов "
                    "с первым живым OAuth-токеном из data/oauth_tokens.json.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help="базовый URL API (default: %(default)s)")
    parser.add_argument("--token-key", default=None,
                        help="конкретный ключ из data/oauth_tokens.json "
                             "вместо первого живого")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help="таймаут одного запроса, сек (default: %(default)s)")
    parser.add_argument("--log-dir", default="data/",
                        help="директория для лога mobile_smoke_YYYYMMDD.log "
                             "(default: %(default)s)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # 1. Токены: без живого токена запускаться бессмысленно.
    tokens, err = load_tokens()
    if tokens is None:
        print(f"[mobile-smoke] {err}")
        print("[mobile-smoke] запуск невозможен: нужен живой OAuth-токен "
              f"в {TOKENS_PATH}")
        return 2
    token_key, access_token, err = pick_token(tokens, args.token_key)
    if access_token is None:
        print(f"[mobile-smoke] {err}")
        return 2
    print(f"[mobile-smoke] использую токен с ключом '{token_key}'")

    # 2. Обходим 10 эндпоинтов (только GET).
    session = requests.Session()
    results = []
    for path in ENDPOINTS:
        status, ms, used_mobile, error = check_endpoint(
            session, args.base_url, path, access_token, args.timeout)
        results.append((path, status, ms, used_mobile, error))

    # 3. Таблица в stdout.
    ok_count = sum(
        1 for _p, status, _ms, _m, _e in results
        if status is not None and status < 400
    )
    total = len(results)
    table_lines = render_table(results)
    for line in table_lines:
        print(line)
    for path, status, _ms, _m, error in results:
        if error:
            print(f"[mobile-smoke] {path}: ошибка запроса: {error}")
    summary = f"итог: {ok_count}/{total} ok"
    print(summary)

    # 4. Лог (append): timestamp запуска + строки таблицы + итог.
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"mobile_smoke_{datetime.now():%Y%m%d}.log"
    started_at = datetime.now().isoformat(timespec="seconds")
    log_lines = [f"=== mobile smoke test @ {started_at} | "
                 f"token key: {token_key} | base-url: {args.base_url} ==="]
    log_lines.extend(table_lines)
    log_lines.append(summary)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(log_lines) + "\n")
    print(f"[mobile-smoke] лог: {log_path}")

    return 0 if ok_count == total else 1


if __name__ == "__main__":
    sys.exit(main())

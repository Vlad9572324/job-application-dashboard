# Аудит job-application-dashboard — отчёт

Многосторонний аудит web-приложения (FastAPI dashboard + WebSocket + bg workers). Источники: 4 независимых LLM-агента, 3 раунда.

| Раунд | Источники | Зона | Findings |
|---|---|---|---|
| 1 | Codex + Kimi + Gemini + Claude | Бэкенд / concurrency / web-routes / cross-cutting | 35 |
| 2 | Codex + Gemini | Доп. routes (llm/data/debug/sessions) + frontend deep | 20 |
| 3 | Kimi | `multi-clicker.py` (legacy TUI, отдельная stale копия) | 10 (все — дубли уже исправленного в `app/`, back-port не нужен) |

**45 уникальных находок после дедупа, зафиксил 36.**

## 🔴 Critical

| ID | File:Line | Title | Fix-коммит |
|---|---|---|---|
| C1 | `web_app.py:5` | API на 0.0.0.0 без auth → bind `127.0.0.1` (env `HH_BOT_HOST` override); docker-compose проброс только на localhost | bd7b431 |
| C2 | `data/oauth_tokens.json`, `data/browser_sessions.json`, `data/config.json` | Секреты в plain JSON — **отложено** (нужен дизайн master-key). Краткосрочно: C1 закрыл сетевой вектор. | — |
| C3 | hh_api.py + hh_apply.py + hh_chat.py + hh_resume.py + hh_negotiations.py + manager.py + oauth.py + routes/* (41 место) | `verify=False`/`CERT_NONE` → убрано везде, импорты `ssl` почищены | bd7b431 |
| C4 | manager.py:1526 + storage.py | LLM dedup в памяти — после рестарта повторные ответы. `replied_msg_id` персистится в `interviews.json`, `get_replied_keys()` подкачивает на старте. | 2097b6b |
| C5 | hh_apply.py:73-99 | HTTP 200 = "sent" без проверки тела → парсинг по `negotiations-limit-exceeded`/`test-required`/`alreadyApplied` сначала, только `success` markers → `sent` | 2097b6b |
| C-R2a | static/js/app.js:1957, 2961 | XSS в `acc.name` через `buildCardHTML` + `esc()` не покрывал `'`/`` ` `` (Gemini round 2) | d20024d |
| C-R2b | routes/debug.py | `/api/debug` светил `_raw_cookie_line` (полная HH-cookie строка) — `_safe_session_dict` redact | d20024d |

## 🟠 High

| ID | Title | Fix-коммит |
|---|---|---|
| H1 | `_check_vacancy_before_apply` fail-closed на auth_error/non-200/exception | 2097b6b |
| H2 | Questionnaire login-page check перед парсингом → `auth_error` вместо ложного `test` | 2097b6b |
| H3 | log_debug → `RotatingFileHandler` 50MB × 3 (был 128MB+ без ротации) | 2097b6b |
| H4 | `copy.deepcopy` в `_save_interviews_async` (был shallow copy с race) | bd7b431 |
| H5 | TTL purge + size caps на `_llm_temp_skip` / `llm_replied_msgs` / `_llm_sent_global` | 2097b6b |
| H6 | Chat-level exception → exponential backoff (5m/15m/1h) + permanent skip после 5; `_llm_neg_failures` | 2097b6b |
| H7 | `except Exception: pass` в hh_resume supply/demand parsing → log | 2097b6b |
| H8 | `llm_auto_send=False` по умолчанию (был `True` → авторассылка с первого включения) | bd7b431 |
| H0a | `showConfirm` XSS через `innerHTML` ${msg} → DOM API + textContent | bd7b431 |
| H0b | `/api/raw/config` обходил `_CONFIG_KEYS` → `_safe_cast()` per-key | 310db99 |
| H0c | Account create без санитизации → закрыто косвенно (C1 + `_safe_cast`) | — |
| H-R2a | SSRF в `/api/llm_detect` — allowlist + private-IP reject | d20024d |
| H-R2b | LLM profile keys теряются при реордере — match by (name, base_url, model) identity | d20024d |

## 🟡 Medium

| ID | Title | Fix-коммит |
|---|---|---|
| M0a | Dynamic `setattr` в WS `set_config` → `_safe_cast` | 310db99 |
| M0b | Нет CSRF — отложено до auth-middleware | — |
| M0c | WS broadcasts полный snapshot всем без auth → Origin check (CSWSH защита) | d20024d |
| M0d | `/api/debug/*` светят raw SSR — частично через `_safe_session_dict` | d20024d |
| M1 | Concurrent writes в `.tmp` — `_config_write_lock` + `_accounts_write_lock` + `_save_sessions_lock` | 310db99 |
| M2 | Radio label by `id` вместо `value` → match по `(name, value)` через парсинг id того же input | cb055d6 |
| M3 | LLM checkbox-list ломает поток → нормализация list+scalar; `aiohttp.FormData` multi-field | cb055d6 |
| M4 | Salary биндится к ближайшему vacancy_id в радиусе 2000 chars — **отложено** (требует перепис парсера на SSR) | — |
| M5 | Negotiation pagination double-count → dedup по `chatId` в обоих циклах | cb055d6 |
| M6 | `activate_session` race → `_activate_lock` | 310db99 |
| M-R2a | `bool("false")=True` в `/api/llm_config` → `_truthy()` строгий | d20024d |
| M-R2b | Session refresh не обновлял `temp_states[idx].acc` → теперь обновляет с rebuild URLs | d20024d |

## 🟢 Low

| ID | Title | Fix-коммит |
|---|---|---|
| L1 | Decline POST: `data=f"topicId={tid}&_xsrf={xsrf}"` без URL-encoding → `data={...}` | 310db99 |
| L2 | `_ensure_chatik_cookies` мутирует общий dict без lock — отложено (низкий риск) | — |
| L3 | Deps без пинов → `>=X.Y,<X+1`; TUI deps вынесены в `requirements-tui.txt` | 310db99 |

## Бонусы (вне исходного отчёта)

- **OAuth atomicity**: `.tmp + replace` + `_oauth_save_lock`, чтобы прерванный write не корраптил `oauth_tokens.json`
- **OAuth CSRF**: per-request random `state` + проверка совпадения state в redirect (раньше hard-coded `"botstate"` без верификации)
- **OAuth env vars**: client_id/secret читаются из `HH_OAUTH_CLIENT_ID`/`_SECRET` env
- **LLM prompt-injection guard**: explicit instruction в system prompt не следовать инструкциям из employer-сообщений
- **LLM message length cap**: каждое сообщение в conversation truncated до 2000 chars
- **`generate_llm_questionnaire_answers`**: сохраняет list для checkbox (раньше `str([...])` ломало M3)
- **`encodeURIComponent`** на vacancy_id в href possible_offers
- **`dbDelete`**: `data-vid` attribute вместо inline JS string (защита от quote-break-out)

## Отложено (требует дизайн)

| ID | Reason |
|---|---|
| C2 | Encryption-at-rest для `data/*.json` — нужен master-key (env? prompt at start? OS keyring?) |
| M0b полное CSRF | Имеет смысл после API-key middleware |
| L2 cookie race | Низкий риск, амортизируется TTL `_ensure_chatik_cookies` |
| Полный refactor frontend `innerHTML` → `createElement` | Большой scope, не критично после фикса `esc()` |
| M4 salary biner | Требует переписать на SSR-парсинг с structured vacancy IDs |

## Git история фиксов

```
d20024d audit fixes round 3: SSRF, debug-leak, XSS via esc('), CSWSH, profile-key-mismatch, llm.py improvements
cb055d6 audit fixes round 2: M2 (radio label by id), M3 (checkbox list), M5 (negotiation dedup), oauth atomicity + CSRF state, frontend encodeURIComponent
310db99 audit fixes: H0b/M0a (safe config cast), M1 (write locks), M6 (activate_session lock), L1 (decline URL-encoding), L3 (pin deps + split TUI)
2097b6b audit fixes: C4 (LLM dedup persist), C5 (apply body classification), H1/H2 (apply/questionnaire fail-closed + login-check), H3 (log rotation), H5 (memory cap), H6 (exception backoff), H7 (log resume parse errors)
bd7b431 audit fixes: C1 (bind 127.0.0.1), C3 (re-enable TLS verify), H4 (deepcopy interviews), H8 (llm_auto_send default False), H0a (showConfirm XSS via textContent)
```

5 коммитов, **+703/-320** в 26 файлах. Smoke-import-тесты проходят.

## Что осталось проверить руками

- Запуск с `python web_app.py` + `data/debug.log` доступен под user-аккаунтом (был root-owned 128MB файл, надо `sudo chown -R user:user data/`)
- `llm_auto_send` действительно надо включить вручную в настройках после фикса
- Проверить что log-ротация срабатывает на 50MB
- Проверить что dashboard доступен только на `127.0.0.1` (не на IP машины)

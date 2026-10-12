# CONTRIBUTING — как вносить изменения в hh.ru-clicker

Коротко о проекте: FastAPI-дашборд (`web_app.py` + `app/*.py`, `app/routes/*.py`)
для автоматизации hh.ru; фронтенд — vanilla JS + CSS в `static/` **без build-step**;
тесты — pytest в `tests/`; запуск локально или в Docker.

Актуальный рефакторинг: абстракция `HHClient` (`app/hh_client.py` +
`hh_client_web.py` + `hh_client_mobile.py` + `hh_client_factory.py`) — ветка
`refactor/mobile-api`. Новый код, работающий с API hh.ru, должен идти через эту
абстракцию, а не прямыми вызовами в `app/hh_*.py` (см. «HHClient-абстракция» ниже).

---

## 1. Coding style

### Бэкенд (Python 3.10+, FastAPI + asyncio)

- **Роуты**: один `APIRouter()` на модуль в `app/routes/*.py`
  (`core.py`, `accounts.py`, `sessions.py`, `data.py`, `apply.py`, `settings.py`,
  `llm.py`, `debug.py`). Регистрация — в `app/routes/__init__.py`
  (`app.include_router(...)`). Новый роут = добавить хендлер в существующий router
  по смыслу или новый модуль + одна строка регистрации.
- Хендлеры — `async def`, декораторы `@router.get/post/...`. Pydantic-модели для
  body там, где нужен validation (пример: `ConfigUpdate` в `app/routes/settings.py`).
- **Логгирование**: только через `app/logging_utils.py` — `log_debug(...)` и
  `log_exception(...)`. Пишет в ротируемый `data/debug.log` (50MB × 4 файла).
  Не использовать `print()` для диагностического вывода (допустим только
  stderr в `web_app.py` для signal-hook сообщений).
- Startup/shutdown живёт в **lifespan** (`app/routes/__init__.py::_lifespan`).
  `@app.on_event("startup")` FastAPI игнорирует при заданном `lifespan=` —
  не добавляйте их.
- Singleton'ы бота/менеджера — в `app/instances.py` (импортировать оттуда,
  чтобы не создать циклические импорты).
- Долгие блокирующие операции не выполнять в event loop: либо `await`,
  либо `run_in_executor` (в истории был critical-баг на event-loop block —
  см. коммит `cf73bf6`).
- Комментарии и docstring'и в коде — как правило русские, часто со ссылкой на
  причину/инцидент (`(kimi-r14-4 #5)`, `(issue #19)`). Сохраняйте этот стиль:
  комментарий объясняет *почему*, а не *что*.

### Фронтенд (vanilla JS, БЕЗ build-step)

- Весь фронт: `static/index.html` + `static/js/app.js` (~6k строк) +
  `static/css/style.css`, `static/css/theme-autoclicker.css`.
- Подключение напрямую: `<script src="/static/js/app.js?v=5">` и `<link>` в
  `index.html`. **Никаких npm/webpack/vite/bundler'ов в проекте нет и не нужно.**
  Правка фронта = просто правка файла; кэш бьётся автоматически — роут `/`
  подставляет `?v=<mtime>` в ссылки на ассеты (`_bust()` в `app/routes/core.py`).
- **Никаких новых фреймворков/сборок (React/Vue/TypeScript-компиляция и т.п.)
  без предварительного обсуждения с владельцем проекта.**
- Фичи, добавленные на бэкенде и видимые в UI, обычно требуют правки
  `static/js/app.js` + `static/index.html` в том же PR.

### Типизация

- Текущее состояние — **частичные аннотации** (~60% функций в `app/` имеют
  return-аннотации; параметры аннотированы выборочно). mypy **не настроен и не
  запускается** (см. «Линтеры»).
- Правило: **новые функции и методы — с аннотациями** параметров и возвращаемого
  значения (в стиле кодовой базы: `int | None`, `dict`, `tuple`; новый
  `app/hh_client.py` — образец: все методы типизированы).
- Линтер не гоняет аннотации автоматически — это на совести автора и review.

### HHClient-абстракция (рефакторинг mobile-API)

- `app/hh_client.py` — базовый `HHClient` (интерфейс: `fetch_negotiations`,
  `fetch_thread`, `send_message`, `submit_response`, `fill_questionnaire`,
  `check_limit`, `touch_resume` и т.д.).
- `app/hh_client_web.py` (`WebHHClient`) — действующая web-реализация
  (browser cookies/chatik), `app/hh_client_mobile.py` (`MobileHHClient`) —
  mobile-реализация через OAuth api.hh.ru.
- Выбор реализации — **только через `app/hh_client_factory.py::get_client(account)`**
  (поле `mode` аккаунта: `"web" | "mobile" | "auto"`; fallback —
  `CONFIG.default_client_mode`).
- Новый код не должен хардкодить `WebHHClient`/`MobileHHClient` — только
  интерфейс `HHClient` + фабрика. Поведенческие различия реализаций покрывать
  тестами (образец: `tests/test_hh_client_abstraction.py`).

---

## 2. Branching

| Ветка | Назначение |
|---|---|
| `main` | Стабильная версия, зеркалит `origin/main` (remote: `git@github.com:Vlad9572324/hh.ru-clicker.git`). Прямые пуши нежелательны — через PR. |
| `refactor/mobile-api` | Текущий рефакторинг: абстракция HHClient (web/mobile). Базируется на `main`; мержится обратно в `main` по завершении фаз. |
| `pr-N` (`pr-11`, `pr-12`, `pr20`, …) | Фиче-ветки под конкретные PR. Историческое замечание: именование неконсистентно (`pr-11` vs `pr20`); новые ветки заводите как `pr-<номер>`. |

Куда слать изменения:

- **Фича/фикс поверх стабильного** → ветка от `main` (`pr-N`), PR в `main`.
- **Код, завязанный на mobile-API/HIClient-абстракцию** → ветка от
  `refactor/mobile-api`, PR в `refactor/mobile-api`.

Ребазинг:

```bash
git fetch origin
git checkout pr-NN
git rebase origin/main          # или origin/refactor/mobile-api — по базе ветки
# решить конфликты, затем:
git push --force-with-lease     # для уже опубликованных веток
```

Не ребазьте `main` и опубликованный `refactor/mobile-api` — только фиче-ветки.

---

## 3. Commit format

Конвенция выведена из реального `git log` (последние ~80 коммитов):

```
тип(scope): краткое описание

опциональное тело: что сломалось / почему / как чинили / какие тесты добавлены
```

**Типы**, которые реально используются: `feat`, `fix`, `ux`, `ui`, `test`,
`debug`, `docs`, `chore` (+ редкие `Merge PR #N from <автор>: ...` для чужих PR).
Самые частые — `feat` и `fix`.

**Scope** — область в скобках, по смыслу: `(oauth)`, `(llm)`, `(ui)`, `(card)`,
`(session)`, `(http)`, `(chat)`, `(tests)` и т.п. Для мелких/общих изменений
scope опускается: `feat: ...`, `fix: ...`.

Примеры из истории:

```
fix(oauth): deadlock invalidate_oauth_token ↔ _save_oauth_tokens (issue #19)
feat(session): OAuth fallback for /refresh when cookies dead
ux: autosave LLM-профилей через 1.5с бездействия
test: pytest-покрытие новых фич + fix quick_replies bare-list crash
debug: логгируем причину пропуска hhpro_ai_letter
feat(ui): runtime-editor прокси через /api/proxy/set
```

Правила:

- **Ссылки на issue — как `#N` или `(issue #N)`** прямо в subject/теле.
- **Язык описаний: русский или английский — оба допустимы.** Исторически микс:
  коммиты владельца сейчас преимущественно русские, PR от контрибьюторов —
  английские. Главное — последовательность внутри своей серии коммитов.
- Тело коммита приветствуется для нетривиальных фиксов: симптом → причина →
  что изменено → какие тесты добавлены (см. `b3bba5a`, `8bfea62` в `git log`).

### ⚠️ Обязательное правило: НЕ писать Co-Authored-By трейлеры

**В коммитах запрещено указывать трейлеры `Co-Authored-By` для AI/ассистентов**
(никаких `Co-Authored-By: Claude <...>`, `Co-Authored-By: Copilot <...>` и т.п.).
Просьба владельца проекта. В истории есть такие трейлеры (например коммит
`76d00e1`) — это легаси, не повторять. Настроенные AI-инструменты часто
добавляют трейлер автоматически — отключите/вычищайте перед коммитом.

---

## 4. Тестирование

**pytest — основной gate.** [CI](../.github/workflows/ci-release.yml) запускает
его для PR, `main` и релизных тегов. Дополнительно
есть GUI e2e-сьют на Playwright: `tests/e2e/` (всё мокается: aiohttp-сервер
со static + мок-WebSocket, `/api/**` перехватывается через `page.route`;
наружу не уходит ни одного запроса). Контракт фикстур (`static_url`,
`ws_server`, `ui`) — в `tests/e2e/README.md`.

Запуск (из корня репозитория):

```bash
cd <repo>
python3 -m pytest                # или просто: pytest
python3 -m pytest tests/e2e      # GUI e2e (нужен playwright + браузеры:
                                 # pip install playwright && playwright install chromium)
```

`pytest.ini` в корне уже настроен: `testpaths = tests`, discovery
`test_*.py` / `Test*` / `test_*`, `addopts = -ra --strict-markers`, подавлен
известный DeprecationWarning FastAPI `on_event`. Ничего дополнительно
конфигурировать не нужно.

Текущий сьют: `tests/`; точное число тестов и итог запуска показывает CI.
Общие фикстуры — `tests/conftest.py` (sys.path до корня + `tmp_data_dir`,
которая уводит запись в tmp вместо реального `data/`). Таблица покрытия с
историей регрессов — `tests/README.md`.

Конвенции именования (из существующих тестов):

- Файл: `tests/test_<область или функция>.py` — `test_oauth_composite_key.py`,
  `test_classify_apply.py`, `test_ws_origin.py`, `test_quick_replies.py`.
- Тест-функция: `test_<поведение>` — `test_web_client_delegates_fetch_thread`,
  `test_key_preserved_on_model_change`.
- Классы не используются — только функции (pytest-стиль, без `unittest`).
- Моки — `monkeypatch` и `responses`; HTTP наружу не ходит.

Требования:

- **Новый код — с тестами** в том же PR/коммите (история: `test: pytest-покрытие
  новых фич + fix quick_replies bare-list crash`).
- Тесты для абстракции `HHClient` — в `tests/test_hh_client_abstraction.py`
  или рядом по образцу: делегирование `WebHHClient`, API-вызовы
  `MobileHHClient` под `responses`, логика выбора `get_client()` (web/mobile/auto,
  живой/протухший OAuth-токен).
- Фикс бага — по возможности с regression-тестом, воспроизводящим баг
  (образец: `tests/test_llm_profile_key_preservation.py`).

---

## 5. Локальный запуск и конфигурация

### Запуск

```bash
pip install -r requirements.txt
python web_app.py
# → http://localhost:8000
```

Или Docker (Dockerfile + docker-compose.yml; образ `python:3.11-slim`,
в compose также поднимается sing-box sidecar-прокси и монтируются `./data`,
`./app`, `./static`, `./web_app.py`). Для Compose подготовьте `.env` с
`HH_BOT_API_KEY`: конфигурация публикует порт 8000 в локальную сеть.

```bash
docker compose up --build
```

Полезные env: `HH_BOT_PORT` (8000 по умолчанию), `HH_BOT_HOST` (по умолчанию
только loopback; наружу — лишь с `HH_BOT_UNSAFE_EXPOSE=1` и обязательным
`HH_BOT_API_KEY`), `HH_PROXY`, `LLM_PROXY` (детали в README.md).
Для TUI-инструментов есть отдельный `requirements-tui.txt` (web_app.py он
не нужен).

### Конфигурация и персональные данные

- Конфиг: **`data/config.json`** (плюс `data/accounts.json`,
  `data/browser_sessions.json`, `data/debug.log`). Каталог `data/` создаётся
  самим приложением при первом запуске.
- **Весь каталог `data/` в `.gitignore` — не коммитится никогда.** Туда попадают
  cookies, OAuth-токены, ключи LLM, логи. Никогда не добавляйте файлы из
  `data/` в git (`git add -f` запрещён для них).
- Также игнорятся: `__pycache__/`, `.venv/`, `*.log`, IDE-файлы, локальные
  AI-конфиги (`.openclaw/`, `AGENTS.md`, `SOUL.md` и т.п.).
- Перед коммитом проверьте `git status` / `git diff --cached` — в diff не должно
  быть ни токенов, ни персональных данных (в истории уже был коммит
  `chore(privacy): scrub personal names + email from source` — не усугубляйте).

### Линтеры / CI — текущее состояние

- **Линтер не настроен**: нет конфигов ruff/mypy/flake8/pre-commit — формат и
  стиль держатся на review. Не добавляйте линтер-конфиги в PR без обсуждения.
- **CI работает** на PR и коммитах в `main`: устанавливает зависимости,
  запускает `pytest` и GUI тесты Playwright. Релизный тег дополнительно собирает
  Linux и Windows бинарники, проверяет их запуск и публикует Docker-образ и
  GitHub Release. Перед пушем локально запустите `python3 -m pytest`.

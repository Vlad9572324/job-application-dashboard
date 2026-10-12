# HH Bot Dashboard

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-39d0d8?style=flat-square)](https://www.python.org)
[![CI](https://github.com/Vlad9572324/hh.ru-clicker/actions/workflows/ci-release.yml/badge.svg)](https://github.com/Vlad9572324/hh.ru-clicker/actions/workflows/ci-release.yml)
[![Clients](https://img.shields.io/badge/HH-web%20%7C%20mobile%20%7C%20auto-b967ff?style=flat-square)](app/hh_client_factory.py)
[![WebSocket](https://img.shields.io/badge/realtime-WebSocket-00f0ff?style=flat-square)](app/ws_client.py)

Локальный веб-дашборд для автоматизации работы соискателя на hh.ru: поиск и
отклики, LLM-ответы рекрутерам, опросники, аналитика резюме и управление
несколькими аккаунтами.

> Проект автоматизирует действия на hh.ru. Вы самостоятельно отвечаете за
> соблюдение правил сервиса, корректность откликов и сохранность своих данных.

## Возможности

- Завершены Phase 0–5 миграции на mobile API: единый `HHClient`, OAuth Bearer,
  SMS/email OTP, мобильные чаты, отклики, резюме и сервисные операции.
- Для каждого аккаунта выбирается `web`, `mobile` или `auto`; недоступная
  mobile-операция безопасно повторяется через web там, где есть web-capability.
- Вкладка **🤖 HH Хэдди** показывает диалоги с помощником и историю сообщений.
- WebSocket push обновляет чаты и счётчики без ожидания polling; polling остаётся
  запасным каналом.
- В UI добавлены 8 интеграций: HR-ranking, pre-flight проверки, skill
  verifications, realtime counters/streak, рекомендации по резюме, autologin,
  per-account mode selector и WS toggle.

## Быстрый старт

Скачайте [последний релиз](https://github.com/Vlad9572324/hh.ru-clicker/releases/latest)
для [Linux x64](https://github.com/Vlad9572324/hh.ru-clicker/releases/download/v1.0.2/hh-clicker-linux-x64.tar.gz)
или [Windows x64](https://github.com/Vlad9572324/hh.ru-clicker/releases/download/v1.0.2/hh-clicker-windows-x64.zip),
распакуйте и запустите `hh-clicker` или `hh-clicker.exe`. Затем откройте
<http://127.0.0.1:8000>. Для Docker используйте [готовый образ и инструкцию](docs/RELEASE.md#запуск-docker-образа).

При запуске из исходников `docker compose` требует локальный `.env` с
`HH_BOT_API_KEY` и публикует порт 8000 в локальную сеть. Перед этим прочитайте
[руководство по безопасности](docs/SECURITY.md).

### Подключение аккаунта через SMS OTP

1. Откройте **⚙️ Настройки → Авторизация по телефону / email**.
2. Введите телефон, запросите SMS и укажите одноразовый код.
3. Дождитесь сообщения о созданной браузерной сессии. Проверка после кода может
   занять несколько минут: бот получает профиль и резюме, импортирует OAuth и
   выполняет autologin.
4. В карточке аккаунта выберите `mobile` либо `auto` и запустите аккаунт.

![SMS OTP](docs/screenshots/otp-auth.svg)

Подробности: [руководство пользователя](docs/USER_GUIDE.md) и [миграция на
mobile](docs/MOBILE_MIGRATION_GUIDE.md).

## Интерфейс

| Экран | Назначение |
|---|---|
| [Главная](docs/screenshots/dashboard.svg) | два аккаунта, counters и streak |
| [HH Хэдди](docs/screenshots/hedi-chat.svg) | чат с помощником |
| [Навыки](docs/screenshots/skill-verifications.svg) | статусы подтверждения skills |
| [Статус поиска](docs/screenshots/job-search-status.svg) | job search status аккаунта |
| [Режим клиента](docs/screenshots/mode-selector.svg) | web/mobile/auto per account |
| [Отклики](docs/screenshots/applications-ranking.svg) | HR-ranking и история откликов |
| [Pre-flight](docs/screenshots/preflight-modal.svg) | блокирующие поля перед откликом |
| [Анализ резюме](docs/screenshots/analyze-resume.svg) | missing skills и рекомендации |

Все изображения — детерминированные SVG-мокапы. В них нет выгрузок из
пользовательских данных: имя, телефон и `resume_hash` заменены тестовыми
значениями.

## Режимы клиента

- `web` — browser cookies и web endpoints;
- `mobile` — OAuth/mobile API с поддерживаемым fallback на web;
- `auto` — mobile при наличии пригодного OAuth-токена, иначе web.

Архитектурная схема и состояние фаз: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Проверка

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

Актуальный результат показывает CI и локальный запуск `pytest -q`.

## Релизы

CI проверяет PR и `main`. Для тега `vX.Y.Z` workflow проверяет приложение,
собирает бинарники Linux и Windows, публикует Docker-образ в GHCR и создаёт
GitHub Release. Актуальный выпуск — [v1.0.2](https://github.com/Vlad9572324/hh.ru-clicker/releases/tag/v1.0.2).
Установка, проверка контрольных сумм и порядок публикации описаны в
[docs/RELEASE.md](docs/RELEASE.md).

## Документация

- [Руководство пользователя](docs/USER_GUIDE.md)
- [Mobile migration guide](docs/MOBILE_MIGRATION_GUIDE.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Защита данных](docs/SECURITY.md)
- [API reference](docs/API_REFERENCE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Changelog](CHANGELOG.md)

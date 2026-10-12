# Документация hh.ru-clicker

Индекс документации проекта. Актуальный выпуск —
[v1.0.2](https://github.com/Vlad9572324/hh.ru-clicker/releases/tag/v1.0.2).

## Для юзеров бота

| Документ | О чём |
|---|---|
| [MOBILE_MIGRATION_GUIDE.md](MOBILE_MIGRATION_GUIDE.md) | Пошаговый перевод аккаунта с web-flow (cookies) на mobile OTP (SMS-авторизация api.hh.ru): кнопки UI, поля `mode`/`default_client_mode`, откат на web, ограничения (нет телефона → только web), FAQ |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Типовые проблемы: протух OAuth-токен, mobile API 401 и fallback на web, DDoS-Guard soft-ban, chatik cookies wipe, «200 + SPA HTML вместо JSON», HH-лимиты, опросники, LLM-ошибки + таблица «симптом → секция» |
| [RELEASE.md](RELEASE.md) | Готовые Linux и Windows файлы, проверка SHA256, запуск Docker-образа, выпуск следующей версии через GitHub Actions |

## Для разработчиков

| Документ | О чём |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Устройство проекта: FastAPI + воркеры + два канала к hh.ru; интерфейс `HHClient` (37 методов), `WebHHClient`/`MobileHHClient`, фабрика `get_client()` и выбор `mode`; два сквозных пути запроса (отклик, WebSocket-push); известные несоответствия Phase 0 |
| [API_REFERENCE.md](API_REFERENCE.md) | Reference по `HHClient`: сигнатура + вызов + форма ответа для всех 37 методов; таблица web/mobile-поддержки с кандидат-эндпоинтами api.hh.ru для фаз 2–4; конвенция ошибок |
| [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) | Все 56 полей `Config` (`app/config.py`): default, смысл, где используется; env-переменные (настоящий override — `HH_PROXY`); детально про `default_client_mode` и поле `mode` аккаунтов/temp-сессий |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Как контрибутить: coding style, формат коммитов, тестирование через pytest, Playwright и CI, запрет Co-Authored-By трейлеров |

## Реверс-инжиниринг hh.ru

| Файл | О чём |
|---|---|
| [HH_OPENAPI_KEY_FINDINGS.md](HH_OPENAPI_KEY_FINDINGS.md) | Находки по OpenAPI-спеке hh.ru |
| [hh_openapi.yaml](hh_openapi.yaml) | Выгруженная OpenAPI-спека публичного API hh.ru |
| [../HH_API_MAP.md](../HH_API_MAP.md) | Карта API hh.ru, используемая ботом (файл в корне репо) |

## Сопутствующее в корне репо

| Файл | О чём |
|---|---|
| [../CHANGELOG.md](../CHANGELOG.md) | История выпусков и изменений |
| [../README.md](../README.md) | Главный README: возможности, скриншоты, быстрый старт и релизы |
| [../AUDIT_REPORT.md](../AUDIT_REPORT.md) | Аудит приложения (4 агента, 3 раунда, 45 находок) |

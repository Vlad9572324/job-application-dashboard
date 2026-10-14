# API_REFERENCE — HHClient (Phase 0 mobile-api рефакторинга)

Reference для разработчиков job-application-dashboard: как использовать доменный клиент
`HHClient` в новом коде. Порядок методов — как в `app/hh_client.py`.

Источники:
- код: `app/hh_client.py`, `app/hh_client_web.py`, `app/hh_client_mobile.py`,
  `app/hh_client_factory.py`, web-flow модули `app/hh_chat.py`, `app/hh_apply.py`,
  `app/hh_negotiations.py`, `app/hh_resume.py`, `app/oauth.py`;
- контракты mobile API hh.ru: `scratchpad/apidocs/apidocs_INDEX.md` +
  `apidocs_group_{1..8}.yaml` (169 endpoints, probe-ответы от 2026-08-10,
  Android-клиент ru.hh.android/26.28.1). Ссылки вида **(гр.N)** указывают на
  apidocs-группу, откуда взят endpoint/пример ответа.

> ⚠️ Не путать: `app.hh_client.HHClient` — доменная абстракция (этот документ).
> `app.hh_http.HHClient` (singleton `HH`) — низкоуровневая транспортная
> curl_cffi/requests-обёртка, к домену отношения не имеет.

---

## 1. Как получить клиента

```python
from app.hh_client_factory import get_client

client = get_client(acc)          # acc — dict аккаунта
stats = client.fetch_negotiations(max_pages=5)
```

Выбор реализации (`get_client`):

| `account["mode"]` | Результат |
|---|---|
| `"mobile"` | `MobileHHClient` безусловно |
| `"web"` (или неизвестный mode) | `WebHHClient` безусловно |
| `"auto"` / поле отсутствует | `MobileHHClient`, если `oauth.get_oauth_status(resume_hash)["has_token"]` == True, иначе `WebHHClient` |
| поле отсутствует | берётся `CONFIG.default_client_mode` (дефолт `"auto"`, валидные значения `web`/`mobile`/`auto`, см. `app/config.py`) |

Правила для нового кода:

1. Всегда получать клиента через `get_client(acc)` — никогда не инстанцировать
   `WebHHClient`/`MobileHHClient` напрямую.
2. Код НЕ должен зависеть от реализации: клиент может оказаться web (cookies
   hh.ru + chatik.hh.ru) или mobile (OAuth Bearer api.hh.ru).
3. Методы аккаунт не принимают — клиент привязан к одному аккаунту через
   конструктор (`self.acc`).
4. Готовиться к `NotImplementedError` от незавершённых реализаций (см. §4) —
   в Phase 0 это нормальное состояние mobile-клиента.

Текущий статус реализаций:

| Реализация | Состояние |
|---|---|
| `WebHHClient` | все 37 методов, кроме `fetch_counters` (у web нет аналога `GET /me`) |
| `MobileHHClient` | реально: `fetch_counters` + группа E (делегирование в `app/oauth.py`); остальное — заглушки `NotImplementedError("phase 2/3/4: TODO mobile ...")` |

Легенда таблиц: ✅ реализовано · 🔜 заглушка `NotImplementedError` (указан phase) ·
❌ не поддерживается в этой реализации · ⚠️ частичный/составной кандидат в mobile.

---

## 2. Оглавление методов

### Группа A — переговоры / чат

| # | Метод | Назначение | Web-реализация | Mobile-реализация (api.hh.ru) | Статус |
|---|---|---|---|---|---|
| 1 | `fetch_negotiations` | Статистика откликов/переговоров | HTML-парсинг `GET hh.ru/applicant/negotiations` (2 прохода: `state=INTERVIEW` + общий) | 🔜 phase 2; кандидаты: `GET /chats` (гр.1), `GET /negotiations/{topic_id}` (гр.1), `GET /counters/user` (гр.5) | web ✅ / mobile 🔜 |
| 2 | `fetch_thread` | Тред переговоров по neg_id | `GET chatik.hh.ru/chatik/api/chats` — полный список, поиск по id | 🔜 phase 2; `GET /negotiations/{topic_id}` → `chat_id`-мост → `GET /chats/{chat_id}` (гр.1) | web ✅ / mobile 🔜 |
| 3 | `send_message` | Отправка сообщения | OAuth-first: `POST api.hh.ru/negotiations/{neg_id}/messages`, затем `POST api.hh.ru/common/chats/{chat_id}/messages`; fallback `POST chatik.hh.ru/chatik/api/send` | 🔜 phase 2; mobile-контракт `POST /chats/{chat_id}/messages` с `idempotency_key` (гр.1, APK); официальные пути уже реализованы в `app/oauth.py` | web ✅ / mobile 🔜 |
| 4 | `fetch_chat_list` | Список чатов | `GET chatik.hh.ru/chatik/api/chats` (page/cursor-пагинация) | 🔜 phase 2; `GET /chats?page=&per_page=` (гр.1, live) | web ✅ / mobile 🔜 |
| 5 | `fetch_chat_history` | История сообщений чата | `GET chatik.hh.ru/chatik/api/chat_data?chatId=` | 🔜 phase 2; `GET /chats/{chat_id}?limit=&order=&start_message_id=` (гр.1, live) | web ✅ / mobile 🔜 |
| 6 | `fetch_quick_replies` | Быстрые ответы HH | `GET chatik.hh.ru/chatik/api/quick_replies?chatId&messageId` | 🔜 phase 2; `POST /chats/{chat_id}/suggestions/quick_replies` (гр.1, APK, метод не подтверждён: POST vs PUT) | web ✅ / mobile 🔜 |
| 7 | `send_participant_action` | Typing-индикатор | `POST chatik.hh.ru/chatik/api/participant_action` | 🔜 phase 2; `POST /chats/{chat_id}/participants/action` (гр.1, APK) | web ✅ / mobile 🔜 |
| 8 | `mark_chat_read` | Read-receipt | `POST chatik.hh.ru/chatik/api/mark_read` | 🔜 phase 2; `PUT /chats/{chat_id}/messages/last_viewed_id` (гр.1, APK) | web ✅ / mobile 🔜 |
| 9 | `fetch_possible_offers` | Возможные офферы | `GET hh.ru/shards/applicant/negotiations/possible_job_offers` | 🔜 phase 2; аналог в apidocs не найден | web ✅ / mobile 🔜 |
| 10 | `auto_decline_discards` | Автоотклонение отказов | SSR `?state=DISCARD` → `POST hh.ru/applicant/negotiations/decline` | 🔜 phase 2; write-эндпоинт в apidocs отсутствует (в `GET /negotiations/{topic_id}` есть только флаг `decline_allowed`, гр.1) | web ✅ / mobile 🔜 |
| 11 | `fetch_negotiations_metadata` | Politeness/HR-активность/статусы топиков | SSR `GET hh.ru/applicant/negotiations` одним запросом | 🔜 phase 2; ⚠️ частично: `GET /vacancies/{id}/employer_stats` (гр.2), `chat_states` в `GET /chats/{id}` (гр.1) | web ✅ / mobile 🔜 |
| 12 | `fetch_employer_rating` | Рейтинг работодателя | `GET hh.ru/employer_reviews/proxy_components/small_widget?employerId=` | 🔜 phase 2; `GET /employers/{id}/reviews` (гр.4, live) — фактически = `fetch_employer_rating_oauth` | web ✅ / mobile 🔜 |
| 13 | `fetch_employer_id_for_vacancy` | employer_id по вакансии | SSR `GET hh.ru/vacancy/{vid}` → `vacancyView.company.id` | 🔜 phase 2; `GET /vacancies/{id}` → `employer.id` (гр.2) | web ✅ / mobile 🔜 |
| 14 | `fetch_vacancy_owner_hr_hhid` | HR-vladelec вакансии | SSR `GET hh.ru/vacancy/{vid}` → `vacancyInternalInfo.ownerEmployerManagerHhid` | 🔜 phase 2; аналог в apidocs не найден | web ✅ / mobile 🔜 |

### Группа B — отклики

| # | Метод | Назначение | Web-реализация | Mobile-реализация (api.hh.ru) | Статус |
|---|---|---|---|---|---|
| 15 | `submit_response` (async) | Отклик на вакансию | AI-письмо `POST /shards/hhpro_ai_letter` + poll, затем `POST hh.ru/applicant/vacancy_response/popup` | 🔜 phase 3; `POST api.hh.ru/negotiations` уже реализован в `oauth._oauth_apply` (официальный API, в apidocs не пробивался) | web ✅ / mobile 🔜 |
| 16 | `fill_questionnaire` (async) | Заполнение анкеты | `GET hh.ru/applicant/vacancy_response?vacancyId=&withoutTest=no` → парсинг/заполнение HTML-формы → POST | 🔜 phase 3; web-only механизм (HTML-форма); аналога в apidocs нет, ближайший пре-чек — `GET /resume_profile/data_inconsistency` (гр.2) | web ✅ / mobile 🔜 |
| 17 | `check_vacancy_before_apply` | Пре-проверка вакансии | `GET hh.ru/applicant/vacancy_response/popup?vacancyId=` (JSON) | 🔜 phase 3; ⚠️ составной: `GET /vacancies/{id}` + `GET /vacancies/{id}/resumes_by_status` (гр.2) | web ✅ / mobile 🔜 |
| 18 | `check_limit` | Лимит откликов | `GET /search/vacancy` (первый vid) + GET popup → маркер `negotiations-limit-exceeded` | 🔜 phase 3; прямого аналога нет; кандидат — подсчёт сегодняшних откликов через `GET api.hh.ru/negotiations` (см. `fetch_negotiations_today_count`) | web ✅ / mobile 🔜 |
| 19 | `touch_resume` | Поднять резюме | 3 каскада: 1) OAuth `POST api.hh.ru/resumes/{hash}/publish` 2) `POST hh.ru/shards/resume/batch_update` 3) `POST hh.ru/applicant/resumes/touch` | 🔜 phase 3; `POST /resumes/{hash}/publish` уже реализован в `oauth._oauth_touch_resume` (первый каскад web-метода); в гр.2 подтверждено что GET на publish → 405 (write-метод) | web ✅ / mobile 🔜 |
| 20 | `fetch_related_vacancies` | Похожие вакансии | `GET hh.ru/shards/vacancy/related_vacancies?vacancyId=&SourceLabel=suitable_vacancies` | 🔜 phase 3; аналог в apidocs не найден | web ✅ / mobile 🔜 |

### Группа C — резюме

| # | Метод | Назначение | Web-реализация | Mobile-реализация (api.hh.ru) | Статус |
|---|---|---|---|---|---|
| 21 | `fetch_stats` | Статистика резюме | SSR `GET hh.ru/applicant/resumes` (userStats + applicantResumesStatistics + toUpdate-таймер) | 🔜 phase 4; ⚠️ частично: `total_views`/`new_views` в `GET /resumes/{id}` (гр.2), `GET /counters/user` (гр.5) | web ✅ / mobile 🔜 |
| 22 | `fetch_resume` | Текст резюме | `GET hh.ru/resume/{hash}` HTML → текст (кэш 4ч) | 🔜 phase 4; `GET /resumes/{id}` (гр.2) — полный JSON резюме вместо текста | web ✅ / mobile 🔜 |
| 23 | `fetch_resume_view_history` | Кто смотрел резюме | SSR `GET hh.ru/applicant/resumeview/history?resumeHash=` (fallback HTML) | 🔜 phase 4; `GET /resumes/{id}/views` (гр.2, live) | web ✅ / mobile 🔜 |
| 24 | `fetch_resume_views_aggregate` | Агрегированные просмотры | SSR `GET hh.ru/applicant/resumeview/history` (total/new + graphHistoryViews) | 🔜 phase 4; ⚠️ частично: total/new в `GET /resumes/{id}` (гр.2); 30-дневный граф в apidocs не найден | web ✅ / mobile 🔜 |
| 25 | `analyze_resume` | Аудит резюме | локальный анализ SSR `hh.ru/resume/{hash}` + `/applicant/resumes` | 🔜 phase 4; локальная логика поверх `GET /resumes/{id}` + `GET /resumes/{id}/conditions` (гр.2) | web ✅ / mobile 🔜 |
| 26 | `edit_resume_field` | Редактирование полей | `POST hh.ru/applicant/resume/edit?resume={hash}&hhtmSource=resume_partial_edit` | 🔜 phase 4; write-контракт в apidocs отсутствует (`GET /resumes/{id}/conditions`, гр.2 — только правила валидации) | web ✅ / mobile 🔜 |
| 27 | `set_job_search_status` | Статус поиска работы | `PUT hh.ru/shards/user_statuses/job_search_status?status=` | 🔜 phase 4; аналог в apidocs не найден (в гр.8 есть только `GET /user_statuses/need_update` и `POST /user_statuses/mark_read`) | web ✅ / mobile 🔜 |
| 28 | `fetch_account_diagnostics` | Диагностика аккаунта | SSR `GET hh.ru/applicant/resumes` (статусы, резюме, статистика) | 🔜 phase 4; ⚠️ составной: `GET /me` (гр.5), `GET /resumes/{id}`, `GET /resumes/creation_availability` (гр.2) | web ✅ / mobile 🔜 |

### Группа D — счётчики

| # | Метод | Назначение | Web-реализация | Mobile-реализация (api.hh.ru) | Статус |
|---|---|---|---|---|---|
| 29 | `fetch_counters` | Счётчики профиля | ❌ `NotImplementedError("phase 0: web-клиент не имеет аналога GET /me")` | ✅ `GET /me?with_user_statuses=true` (гр.5) | web ❌ / mobile ✅ |

### Группа E — OAuth-extras (Bearer api.hh.ru, общая для обеих реализаций)

Все 8 методов в обоих клиентах делегируют в `app/oauth.py` — вызовы уже ходят
через Bearer одинаково независимо от web/mobile, различий в реализациях нет.

| # | Метод | Назначение | Эндпоинт api.hh.ru | Статус |
|---|---|---|---|---|
| 30 | `fetch_saved_vacancy_searches` | Сохранённые поиски | `GET /saved_searches/vacancies` (официальный API; в apidocs не пробивался) | ✅ оба |
| 31 | `fetch_favorited_vacancies` | Избранные вакансии | `GET /vacancies/favorited` (гр.2, live) | ✅ оба |
| 32 | `fetch_blacklisted_vacancies` | ЧС вакансий | `GET /vacancies/blacklisted` (гр.2, live) | ✅ оба |
| 33 | `fetch_vacancy_details` | Детали вакансии | `GET /vacancies/{id}` (гр.2, live) | ✅ оба |
| 34 | `fetch_negotiations_today_count` | Отклики за сегодня | `GET /negotiations` (официальный API; в apidocs не пробивался) | ✅ оба |
| 35 | `fetch_negotiations_statistic` | Streak-статистика | `GET /negotiations_statistic/mine` (гр.5; требует `x-force-app-access: true` + mobile UA, иначе 406) | ✅ оба |
| 36 | `fetch_resume_status` | Статус резюме | `GET /resumes/{hash}/status` (официальный API; в apidocs не пробивался) | ✅ оба |
| 37 | `fetch_employer_rating_oauth` | Рейтинг работодателя | `GET /employers/{id}/reviews` (гр.4, live) | ✅ оба |

---

## 3. Методы подробно

### Группа A — переговоры / чат

#### A1. fetch_negotiations

```python
def fetch_negotiations(self, max_pages: int = 20) -> dict
```

Статистика откликов/переговоров аккаунта (web: двухпроходный парсинг
`hh.ru/applicant/negotiations`: точный счёт интервью через фильтр
`state=INTERVIEW`, затем просмотры/отказы с общей страницы).

```python
stats = client.fetch_negotiations(max_pages=5)
if stats["auth_error"]:
    ...  # куки протухли
```

Форма ответа (web, из кода):

```python
{
  "interview": 3,               # всего интервью
  "recent_interview": 2,        # за последние 60 дней
  "viewed": 12, "not_viewed": 5, "discard": 7,
  "interviews_list": [{"text": "...", "date": "30.07", "recent": True, "neg_id": "5465575576"}],
  "neg_ids": ["5465575576", ...],
  "discard_neg_ids": ["..."],   # chatId DISCARD-переговоров
  "auth_error": False,
  "unread_by_employer": 2       # HR не прочитал наши сообщения
}
```

Mobile: 🔜 phase 2. Кандидаты из apidocs: счётчики `GET /counters/user` (гр.5) —
`{"new_resume_views":0,"unread_negotiations":430,"resumes_count":1,...}`;
список чатов с состояниями переговоров — `GET /chats` (гр.1). Единого
«negotiations stats» endpoint'а в apidocs нет.

#### A2. fetch_thread

```python
def fetch_thread(self, neg_id: str) -> dict
```

Тред переговоров по `neg_id` (chatId). Web: выкачивает полный список чатов
chatik и строит тред по найденному item'у.

```python
thread = client.fetch_thread("5512844915")
if thread["error"] or thread["chat_locked"]:
    ...
```

Форма ответа (web, из кода):

```python
{
  "neg_id": "5512844915", "employer_name": "Студия МГЛА",
  "vacancy_title": "Художник по окружению / Level artist (gamedev)",
  "messages": [{"sender": "employer", "text": "...", "msg_id": "14932421768"}],
  "needs_reply": True, "last_msg_id": "14932421768",
  "last_employer_msg": "...", "topic_id": "5465575576",
  "error": "", "chat_locked": ""    # lock reason, если писать нельзя
}
```

Mobile: 🔜 phase 2. Схема: `GET /negotiations/{topic_id}` (гр.1) даёт
`chat_id`-мост, состояние и счётчики:

```json
{"id":"5465575576","state":{"id":"discard","name":"Отказ"},
 "counters":{"messages":2,"unread_messages":0},"chat_id":5512844915,
 "messaging_status":"no_invitation","decline_allowed":false,
 "vacancy":{"id":"134210190","name":"Художник по окружению / Level artist (gamedev)","employer":{"id":"12540637","name":"Студия МГЛА"}, "...": "..."}}
```

Сообщения — через `GET /chats/{chat_id}?limit=N` (см. A5); статус переговоров
доступен и прямо из чата: `workflow_transition` + `resources.negotiations`
(гр.1, notes). Ошибка: 404 `errors[{value:topic_not_found,type:negotiations}]`
для не-переговорных id.

#### A3. send_message

```python
def send_message(self, neg_id: str, text: str, topic_id: str = "") -> bool | str
```

Отправка сообщения в переговоры. Web: при `CONFIG.chat_use_oauth` (или мёртвых
куках) сначала официальный OAuth-путь `POST api.hh.ru/negotiations/{neg_id}/messages`
→ `POST api.hh.ru/common/chats/{chat_id}/messages` (помечает `is_automated: true`),
fallback — reverse-engineered `POST chatik.hh.ru/chatik/api/send`.

```python
res = client.send_message(neg_id, "Здравствуйте!")
if res == "chat_not_found":
    ...  # чат закрыт/архивирован — снимать с очереди
```

Возврат: `True` (отправлено) | `False` (ошибка/duplicate/rate) |
`"chat_not_found"` (чат не существует/закрыт/архивирован).

Mobile: 🔜 phase 2. Контракт мобильного клиента (гр.1, APK):
`POST /chats/{chat_id}/messages`, body: `text` (лимит 20000 символов),
`idempotency_key` (обязателен), опц. `upload_id`, `metadata`. Единый контракт
для обычных negotiation-чатов и AI-бот-чатов. Live не пробивался (SAFETY).

#### A4. fetch_chat_list

```python
def fetch_chat_list(self, max_pages: int = 5) -> tuple
```

Список чатов из chatik.hh.ru. Возвращает кортеж
`(items_by_id: dict[str, dict], display_info: dict, current_participant_id: str)`.

```python
items_by_id, display_info, cur_pid = client.fetch_chat_list(max_pages=3)
```

Mobile: 🔜 phase 2. `GET /chats?page=0&per_page=20` (гр.1, live) — форма
ответа другая:

```json
{"chats": {"items": [{"id": "5522666855", "unread_count": 5, "type": "BOT",
   "subtype": "CAREER_ASSISTANT", "display": {"title": "Карьерный помощник"},
   "messages": {"last": {"id": 15047614423, "participant_id": "128627571-BOT", "...": "..."}},
   "participants": {"ids": ["128627571-BOT", "153336782-APPLICANT_USER"]},
   "write_possibility": {"name": "ENABLED_FOR_ALL", "write_disabled_reasons": []}}],
  "found": 10000, "pages": 500, "page": 0, "per_page": 20, "has_next_page": true},
 "participants": {"163778010-EMPLOYER_USER": {"display": {"name": "Анна"}, "...": "..."}},
 "resources": {"employers": {}, "vacancies": {}, "resumes": {}, "negotiations": {}},
 "...": "..."}
```

Ограничения (гр.1): `per_page` максимум 20 (иначе 400); фильтр `type` сервером
игнорируется (фильтрация клиентская по `item.type`); `filter_unread=true`
работает; batch-поллинг — повторяемым `?id=A&id=B`.

#### A5. fetch_chat_history

```python
def fetch_chat_history(self, chat_id: str, max_messages: int = 20) -> list
```

История сообщений чата (web: `chatik/api/chat_data`), последние
`max_messages` записей, oldest first, без системных/workflow-сообщений.
Форма элемента (web): `{"sender": "employer"|"applicant", "text": str,
"msg_id": str, "actions": dict, "is_bot": bool}`.

Mobile: 🔜 phase 2. `GET /chats/{chat_id}?limit=50` (гр.1, live; БЕЗ
query-параметров → 400). Текст в `body.text.content` (не верхнеуровневый
`text`!). Инкрементальный дочит: `order=next&start_message_id=<oldest>`
(inclusive), вглубь: `order=prev&start_message_id=<id>`. Ключевые поля
сообщения (из live-пробы):

```json
{"id": 14932421768, "participant_id": "153336782-APPLICANT_USER",
 "participant_display": {"name": "Тестовый Пользователь", "is_bot": false},
 "created_at": "2026-07-30T03:48:33+0300", "type": "SIMPLE",
 "body": {"text": {"content": "Здравствуйте! ..."}},
 "workflow_transition": {"id": "14932421765", "topic_id": "5465575576",
                          "applicant_state": {"id": "response", "name": "Отклик"}}}
```

Плюс готовый гейт «можно ли писать» в ответе:
`chat_states.write_message_state.{allowed,reasons}`.

#### A6. fetch_quick_replies

```python
def fetch_quick_replies(self, chat_id: str, msg_id: str) -> list
```

Быстрые ответы, которые HH генерирует на конкретное сообщение HR.
Возврат: `list[str]` (пустой список при отказе/отсутствии).

Mobile: 🔜 phase 2. `POST /chats/{chat_id}/suggestions/quick_replies?message_id=`
(гр.1, APK-контракт; live не пробивался; конфликт источников POST vs PUT;
GET → 405). Схема ответа в apidocs не зафиксирована.

#### A7. send_participant_action

```python
def send_participant_action(self, chat_id: str, action_type: str = "TYPING") -> bool
```

Эмуляция typing indicator (`TYPING`/`NONE`). Возврат: `bool`; web считает
409 ожидаемым (typing неприменим) и возвращает `False`.

Mobile: 🔜 phase 2. `POST /chats/{chat_id}/participants/action`, body
`{action_type}` (гр.1, APK-контракт; точный enum в отчётах не приведён).

#### A8. mark_chat_read

```python
def mark_chat_read(self, chat_id: str, message_id: str) -> bool
```

Пометить чат прочитанным до `message_id` (read-receipt для HR). Возврат:
`bool`; web пропускает нечисловые `message_id` (hash-fallback).

Mobile: 🔜 phase 2. `PUT /chats/{chat_id}/messages/last_viewed_id`,
form-body `message_id=<long>` (гр.1, APK-контракт; это write-маркер, не
геттер — GET → 405). Read-state для чтения уже лежит в объекте чата:
`last_viewed_by_current_participant_message_id` + `unread_count`.

#### A9. fetch_possible_offers

```python
def fetch_possible_offers(self) -> list
```

Компании, готовые пригласить (`possible_job_offers`). Возврат (web):
`[{"name": str, "vacancyNames": [str, ...]}, ...]`, `[]` при ошибке.

Mobile: 🔜 phase 2. Аналог в apidocs (169 endpoints) **не найден** —
подтвердить/найти при реализации.

#### A10. auto_decline_discards

```python
def auto_decline_discards(self) -> int
```

Автоотклонение DISCARD-переговоров (до 50 за раз). Возврат: число отклонённых.
Web: SSR `?state=DISCARD` → `topic_ids` из `actions[].id == "decline"` →
`POST hh.ru/applicant/negotiations/decline {topicId, _xsrf}`.

Mobile: 🔜 phase 2. Write-эндпоинта decline в apidocs нет; в
`GET /negotiations/{topic_id}` (гр.1) наблюдается только флаг
`"decline_allowed": false`.

#### A11. fetch_negotiations_metadata

```python
def fetch_negotiations_metadata(self) -> dict
```

Метаданные переговоров одним SSR-запросом (кэш 1ч). Форма ответа (web, из кода):

```python
{
  "politeness": {<employer_id>: {"read_percent": 94, "reply_days": 1, "total_topics": 12}},
  "activity": {<hr_hhid>: {"trl_code": "...", "inactive_minutes": 19, "inactive_days": 0}},
  "topics_by_vid": {"135164800": {"viewed_by_opponent": True, "unread_by_employer": 0,
      "last_state": "...", "has_pending_survey": False, "has_new_messages": True,
      "inbox_availability_state": "...", "applicant_summary_enabled": False}}
}
```

Mobile: 🔜 phase 2. Частичные аналоги: `GET /vacancies/{id}/employer_stats`
(гр.2, live) — `{"employer_responses_read_percent":94,"manager_inactive_minutes":19}`
(scorинг живости HR); per-chat `chat_states` и `write_possibility` в
`GET /chats/{id}` (гр.1). Politeness/activity индексов как в web-SSR в
apidocs нет.

#### A12. fetch_employer_rating

```python
def fetch_employer_rating(self, employer_id) -> dict | None
```

Рейтинг работодателя (web-scraping small_widget, кэш 24ч). Возврат (web):
`{"id", "name", "total": float, "recommend_pct", "ratings": {workplace, team,
management, career, rest, salary}, "advantages": [{name,count}×3],
"reviews_count", "neg_count", "staff_count", "status", "is_open"}` или `None`
если работодатель закрыт/без отзывов.

Mobile: 🔜 phase 2. Аналог — `GET /employers/{id}/reviews` (гр.4, live),
который уже обёрнут в `fetch_employer_rating_oauth` (E37). Пример (гр.4,
employer 3036416):

```json
{"recommendations_percent": 61, "total_rating": "3.4",
 "ratings": [{"id": "WORKPLACE", "value": "3.7"}, {"id": "TEAM", "value": "3.8"},
             {"id": "MANAGEMENT", "value": "3.5"}, {"id": "CAREER", "value": "2.9"},
             {"id": "REST_RECOVERY", "value": "3.3"}, {"id": "SALARY", "value": "3.3"}],
 "reviews_count": 51, "reviews_are_hidden": false, "reviews": [{"id": "4851264", "...": "..."}],
 "last_3_months_reviews_info": {"reviews_count": 5, "feedbacks_count": 0, "...": 0},
 "activity_status": "INACTIVE_EMPLOYER"}
```

#### A13. fetch_employer_id_for_vacancy

```python
def fetch_employer_id_for_vacancy(self, vacancy_id) -> int | None
```

`employer_id` по вакансии (SSR страницы вакансии, кэш 7 дней). Возврат:
`int | None` (None если страница недоступна/вакансия снята).

Mobile: ✅ `GET /vacancies/{id}` (гр.2) — поле `employer.id` прямо
в карточке вакансии:

```json
{"id": "135164800", "name": "Начинающий сотрудник на склад маркетплейса (СЦ)",
 "employer": {"id": "...", "name": "...", "trusted": true, "...": "..."}, "...": "..."}
```

#### A14. fetch_vacancy_owner_hr_hhid

```python
def fetch_vacancy_owner_hr_hhid(self, vacancy_id) -> int | None
```

HHID HR-а, опубликовавшего вакансию (SSR `vacancyInternalInfo.ownerEmployerManagerHhid`,
кэш 7 дней). Возврат: `int | None`.

Mobile: 🔜 phase 2. Аналог в apidocs **не найден** (owner-manager hhid в
пробитых endpoint'ах не встречается).

### Группа B — отклики

#### B15. submit_response (async)

```python
async def submit_response(self, vid: str, letter_max_length: int | None = None) -> tuple
```

Отклик на вакансию. Возвращает `(result, info)`. `letter_max_length` —
hard-cap длины письма (из `check_vacancy_before_apply` → `extras`); длиннее —
обрезается чтобы HH не отказал 400.

```python
result, info = await client.submit_response(vid, letter_max_length=1500)
```

`result` ∈ `sent` | `limit` | `test` | `already` | `auth_error` | `error`
(классификация `hh_apply.classify_apply_response`). `info`: для `sent` —
`title`, `company`, `salary_from/to`, `contact`, `topic_id`, `chat_id`; для
`error` — `raw`/`exception`/`error_code`; для 429-путей — `retry_after`.

Web-механика: опциональная AI-генерация письма
(`POST /shards/hhpro_ai_letter` + poll `/shards/hhpro_ai_check_status`,
одна бесплатная попытка на пару resumeHash×vacancyId), затем multipart-POST
`hh.ru/applicant/vacancy_response/popup` (resume_hash, vacancy_id, letter, lux).

Mobile: 🔜 phase 3. Готовый строительный блок — `oauth._oauth_apply`:
`POST https://api.hh.ru/negotiations`
(form: `vacancy_id`, `resume_id` (URL-quoted hash), опц. `message`).
Классификация уже написана: 200/201/204 → `sent`; 400 с `limit`/`already`/`test`
в `errors[].value` → соответствующий result; 401/403 → `auth_error` +
invalidate токена; 429 → `limit` + `Retry-After`; 502-504 → transient.
В apidocs endpoint не пробивался (группа 1: `/negotiations?vacancy_id=...`
«в отчётах НЕ пробовался — записи нет»).

#### B16. fill_questionnaire (async)

```python
async def fill_questionnaire(self, vid: str, vacancy_title: str = "", company: str = "") -> tuple
```

Заполнение анкеты при отклике (textarea/radio/checkbox, опц. LLM-заполнение).
Возврат: `(result, info)`, `result` ∈ `sent` | `limit` | `test` | `auth_error` | `error`.

Mobile: 🔜 phase 3, фактически **web-only механизм**: анкеты — HTML-форма
`hh.ru/applicant/vacancy_response?vacancyId=X&withoutTest=no`, в apidocs
аналогичного write-контракта нет. Близкий mobile-пре-чек (нужен ли вообще
отклик с доп. данными): `GET /resume_profile/data_inconsistency?vacancy_id=&resume_id=&flow=vacancy_response`
(гр.2, live):

```json
{"data_inconsistency": {"required_additional_data":
  ["WORK_FORMAT", "ADDRESS_COORDINATES", "PREFERRED_WORK_AREAS", "PHOTO"]}}
```

#### B17. check_vacancy_before_apply

```python
def check_vacancy_before_apply(self, vid: str) -> dict
```

Проверка вакансии перед откликом: невозможные отклики, несовпадение опыта,
лимиты. Форма ответа (web, из кода):

```python
{"ok": True, "reason": "",
 "contact": {"fio": "...", "email": "...", "phone": "+7..."},
 "extras": {"letter_max_length": 1500, "test_required": False, "ai_assistant_enabled": True}}
# при отказе:
{"ok": False, "reason": "auth_error"|"rate_limit"|"http_503"|"опыт: нужен X, есть Y"|...,
 "skip_reason": "auth"|"retry"|"skip"|"parse_error"|"exception",
 "retry_after_seconds": 60}   # только для rate_limit
```

Mobile: 🔜 phase 3. Составной кандидат (гр.2): `GET /vacancies/{id}` —
фильтры `archived`, `closed_for_applicants`, `response_letter_required`,
`has_test`, `allow_messages`, `relations`; `GET /vacancies/{id}/resumes_by_status` —
причины блокировки ДО отклика:

```json
{"counters": {"suitable": 0, "not_published": 0, "already_applied": 1, "unavailable": 0},
 "resume_inconsistencies": {"RESUME_HASH_EXAMPLE...": [
   {"type": "DISTANCE", "actual": "1498.66", "required": "30.0"}]},
 "already_applied": [{"id": "RESUME_HASH_EXAMPLE...", "title": "Тестировщик ПО / Автоматизация", "...": "..."}]}
```

#### B18. check_limit

```python
def check_limit(self) -> bool
```

True если дневной лимит откликов активен. Web: берёт первую вакансию из
`/search/vacancy`, GET popup (без побочных эффектов) и ищет маркер
`negotiations-limit-exceeded`. На любую ошибку — fail-closed `True`.

Mobile: 🔜 phase 3. Прямого аналога в apidocs нет. Кандидат: фактическое
число сегодняшних откликов через `GET api.hh.ru/negotiations` (см. E34
`fetch_negotiations_today_count` — уже реализовано в `app/oauth.py`).

#### B19. touch_resume

```python
def touch_resume(self) -> tuple
```

«Поднять» резюме в поиске. Возврат: `(success: bool, message: str)`.
Web-каскад: 1) OAuth `POST api.hh.ru/resumes/{hash}/publish` (без капчи,
бывает 429) → 2) `POST hh.ru/shards/resume/batch_update` (все резюме одним
вызовом) → 3) `POST hh.ru/applicant/resumes/touch` (может отдать капчу).

```python
ok, msg = client.touch_resume()
```

Mobile: 🔜 phase 3, но строительный блок уже есть — `oauth._oauth_touch_resume`
(`POST https://api.hh.ru/resumes/{hash}/publish`, 200/204 = успех, 429 =
кулдаун ~4 часа). Это и есть первый каскад web-метода. В гр.2 подтверждено:
GET на `/resumes/{id}/publish` → 405 (публикация — write-метод POST/PUT).

#### B20. fetch_related_vacancies

```python
def fetch_related_vacancies(self, seed_vid: str, max_pages: int = 1) -> list
```

Похожие вакансии от seed (рекомендательный фид HH). Возврат: уникальный
`list[str]` vacancy_id. Web: `GET /shards/vacancy/related_vacancies` с
обязательными `X-Proxied-*` заголовками.

Mobile: 🔜 phase 3. Аналог в apidocs **не найден** (`/shards/vacancy/*` в
группах отсутствует; близкий по префиксу `/setka/vacancy/{id}/relevance`
(гр.8) — про релевантность резюме, не то).

### Группа C — резюме

#### C21. fetch_stats

```python
def fetch_stats(self) -> dict
```

Статистика резюме за 7 дней + таймер поднятия. Форма ответа (web, из кода):

```python
{"views": 120, "views_new": 9, "shows": 3400,
 "invitations": 5, "invitations_new": 2,
 "next_touch_seconds": 12345, "free_touches": 3,
 "global_invitations": 7, "new_invitations_total": 2}
```

Mobile: 🔜 phase 4. Частичные источники (гр.2/гр.5): `GET /resumes/{id}` —
`total_views: int`, `new_views: int`, `views_url`; `GET /counters/user` —
`new_resume_views`; `GET /me` — `counters.new_resume_views`. Поиска/shows/
invitations в пробитых mobile-эндпоинтах нет.

#### C22. fetch_resume

```python
def fetch_resume(self) -> str
```

Текстовое представление резюме (для LLM-контекста), кэш 4ч. Возврат: `str`
("" при ошибке/отсутствии resume_hash).

Mobile: 🔜 phase 4. `GET /resumes/{resume_id}` (гр.2, live) — полное резюме
в JSON (63 top-level ключа, ~9 КБ): `title`, `experience[]`, `skill_set`,
`education`, `total_experience.months` и т.д. Текст придётся собирать из
JSON. Пример начала объекта (live-проба):

```json
{"last_name": "Пользователь", "first_name": "Тестовый",
 "title": "Тестировщик ПО / Автоматизация",
 "total_experience": {"months": 36},
 "id": "RESUME_HASH_EXAMPLE", "...": "..."}
```

ПДн — не логировать в открытом виде (примечание гр.2).

#### C23. fetch_resume_view_history

```python
def fetch_resume_view_history(self, limit: int = 50) -> list
```

Кто смотрел резюме. Возврат (web): `[{"employer_id": str, "name": str,
"date": "YYYY-MM-DD", "vacancy": ""}, ...]`.

Mobile: 🔜 phase 4. `GET /resumes/{resume_id}/views` (гр.2, live):

```json
{"items": [
  {"created_at": "2026-08-10T10:33:00+0300", "viewed": false,
   "employer": {"id": "11583314", "name": "Глобал Сервис",
                "url": "https://api.hh.ru/employers/11583314",
                "logo_urls": {"90": "https://hh.ru/employer/logo/11583314"}}},
  {"created_at": "2026-08-07T22:52:00+0300", "viewed": true, "employer": {"...": "..."}}],
 "found": 938, "pages": 47, "page": 0, "per_page": 20, "resume": {"...": "..."}
}
```

Отличие от web: есть флаг `viewed` (прочитан ли просмотр нами) и пагинация.

#### C24. fetch_resume_views_aggregate

```python
def fetch_resume_views_aggregate(self) -> dict
```

Агрегированные просмотры за всё время + 30-дневный граф для sparkline.
Форма ответа (web): `{"total_all_time": int, "total_new": int,
"graph_30d": [{"date": "YYYY-MM-DD", "count": int}, ...]}`.

Mobile: 🔜 phase 4. Частично: total/new есть в `GET /resumes/{id}`
(`total_views`, `new_views`, гр.2); daily-граф (`graphHistoryViews`) в
apidocs не найден.

#### C25. analyze_resume

```python
def analyze_resume(self, extra_terms: list = None) -> dict
```

Аудит резюме: что видит HR, что не заполнено, рекомендации. Локальная логика
поверх web-SSR. Успех: `{"ok": True, "name", "title", "roles", "skills",
"percent", "status", "job_search_status", "salary", "work_schedule",
"work_formats", "employment", "has_photo", "area", "stats_7d": {search_shows,
views, views_new, invitations, invitations_new}, "issues": [{level, text, fix?}],
"green_fields", "market", "weight_analysis", ..., "hr_activity"}`; ошибка:
`{"error": "auth_error" | "Нет resume_hash" | str(e)}`.

Mobile: 🔜 phase 4. Данные для той же локальной логики: `GET /resumes/{id}`
(гр.2) + `GET /resumes/{id}/conditions` (правила валидации полей:
required/regexp/min-max length, гр.2).

#### C26. edit_resume_field

```python
def edit_resume_field(self, resume_hash: str, fields: dict) -> dict
```

Редактирование полей резюме. Возврат: `{"ok": True}` или
`{"ok": False, "error": str}`. Web: warm-up GET (DDoS Guard) +
`POST hh.ru/applicant/resume/edit?resume={hash}&hhtmSource=resume_partial_edit`
с JSON-телом `fields`.

Mobile: 🔜 phase 4. В apidocs только read-контракты: правила валидации
`GET /resumes/{id}/conditions` (гр.2); write-методы редактирования резюме
не пробивались (safe-scope).

#### C27. set_job_search_status

```python
def set_job_search_status(self, status: str) -> dict
```

Установка статуса поиска. Валидные `status`: `active_search`,
`looking_for_offers`, `accept_offers`, `has_job_offer`, `accepted_job_offer`,
`not_looking_for_job`. Возврат: `{"ok": True, "status": ..., "label": ...}` |
`{"ok": False, "error": ...}`. Web: `PUT hh.ru/shards/user_statuses/job_search_status?status=`.

Mobile: 🔜 phase 4. Аналог в apidocs **не найден**: в гр.8 есть только
`GET /user_statuses/need_update` и `POST /user_statuses/mark_read`; текущий
статус чтения — `GET /me?with_user_statuses=true` →
`user_statuses.job_search_status.{id,name}` (гр.5).

#### C28. fetch_account_diagnostics

```python
def fetch_account_diagnostics(self) -> dict
```

Диагностика аккаунта (SSR `/applicant/resumes`). Форма ответа (web, из кода):

```python
{"status": "active_search", "status_label": "🟢 Активно ищу работу",
 "red_flags": ["🚨 ...", "⚠️ ..."],       # строки для показа юзеру
 "stats": {"per_resume": {hash: {search_shows, views, views_new, invitations,
                                  invites_new, period_days, recommendation}},
           "resume_limits": {...}, "suitable_vacancies": {...},
           "user_stats": {...}, "global_invitations": int},
 "resumes": [{"title", "hash", "canTouch", "canPublishOrUpdate",
              "hasPublicVisibility", "hasErrors", "hasConditions", "accessType"}]}
```

Mobile: 🔜 phase 4. Составной кандидат: `GET /me?with_user_statuses=true`
(статус поиска, гр.5), `GET /resumes/{id}` (`status`, `blocked`, `finished`,
`progress`, `can_publish_or_update`, `access`, гр.2),
`GET /resumes/creation_availability` (`{"max":20,"remaining":19,
"created":1,"is_creation_available":true}`, гр.2), `GET /resumes/{id}/access_types`
(типы видимости clients/whitelist/blacklist/direct/no_one, гр.2).

### Группа D — счётчики

#### D29. fetch_counters

```python
def fetch_counters(self) -> dict
```

Счётчики профиля. **Единственный метод с обратной поддержкой**: реализован
только в `MobileHHClient`, web-клиент кидает `NotImplementedError`.

```python
me = client.fetch_counters()     # {} если нет токена/любая ошибка
counters = me.get("counters", {})
```

Mobile (реализовано): `GET https://api.hh.ru/me?with_user_statuses=true`
через `requests` с Bearer (не через curl_cffi-обёртку `HH` — чтобы тесты
мокали через `responses`); любой сбой → `{}` (конвенция `app/oauth.py`).

Форма ответа (гр.5, live-пробы):

```json
{"auth_type": "applicant", "id": "USER_ID_EXAMPLE",
 "first_name": "...", "last_name": "...",
 "crypted_id": "CRYPTED_ID_EXAMPLE...",
 "counters": {"new_resume_views": 938, "unread_negotiations": 428, "resumes_count": 1},
 "user_statuses": {"job_search_status": {"id": "...", "name": "Активно ищу работу"}}}
```

`user_statuses` только при `with_user_statuses=true`. `crypted_hhuid` в
ответе НЕТ (только `id`/`crypted_id`). Дешёвый альтернативный источник
бейджей — `GET /counters/user?uuid=` (гр.5):

```json
{"new_resume_views": 0, "unread_negotiations": 430, "resumes_count": 1,
 "new_notifications": 0, "unread_chats": 100, "unread_support_messages": 0,
 "rejected_employer_reviews": 0, "unread_employer_review_feedbacks": 0}
```

(`uuid` обязателен, принимается любое значение; без него 400 bad_argument.)

### Группа E — OAuth-extras

Общая реализация для web и mobile: делегирование в `app/oauth.py` (Bearer
api.hh.ru, UA `job-application-dashboard/1.0`); токены добываются/рефрешатся через
`oauth._obtain_oauth_token`. Ошибки транспорта → пустые значения, не
исключения.

#### E30. fetch_saved_vacancy_searches

```python
def fetch_saved_vacancy_searches(self) -> list
```

Сохранённые поиски вакансий. Возврат: `[{"id": str, "name": str,
"items_url": str, "new_count": int}, ...]` (кэш 1ч). Эндпоинт:
`GET https://api.hh.ru/saved_searches/vacancies?per_page=50&page=` (до 5
страниц). В apidocs не пробивался — официальный публичный API.

#### E31. fetch_favorited_vacancies

```python
def fetch_favorited_vacancies(self) -> list
```

Избранные вакансии. Возврат: `list[str]` vacancy_id (кэш 30мин). Эндпоинт:
`GET /vacancies/favorited` (гр.2, live):

```json
{"items": [{"id": "134025609", "name": "Инженер по сопровождению изделий (ПО)",
  "relations": ["favorited"], "salary": {"from": 140000, "to": 140000, "currency": "RUR"},
  "employer": {"id": "1540476", "name": "НПО ПКРВ"}, "archived": false, "...": "..."}],
 "found": 1, "pages": 1, "page": 0, "per_page": 20}
```

#### E32. fetch_blacklisted_vacancies

```python
def fetch_blacklisted_vacancies(self) -> set
```

Вакансии в ЧС. Возврат: `set[str]` vacancy_id (кэш 30мин). Эндпоинт:
`GET /vacancies/blacklisted` (гр.2, live):

```json
{"items": [], "found": 0, "pages": 1, "page": 0, "per_page": 20, "limit_reached": false}
```

#### E33. fetch_vacancy_details

```python
def fetch_vacancy_details(self, vid: str) -> dict
```

Детали вакансии (поля сверх поисковой выдачи). Возврат: `{"auto_response",
"quick_responses_allowed", "accredited_it_employer", "trusted_employer",
"key_skills": [str], "work_format": [id], "languages": [id],
"response_letter_required", "billing_type"}`; `{}` при transient-ошибке
(negative-cache 60с); `{"archived": True}` при 404 (кэш 1ч). Кэш успеха 6ч.
Эндпоинт: `GET /vacancies/{id}` (гр.2, live; полная карточка ~70 ключей).

#### E34. fetch_negotiations_today_count

```python
def fetch_negotiations_today_count(self) -> dict
```

Число сегодняшних откликов по MSK — источник истины для daily-limit.
Возврат: `{"today": int, "msk_date": "YYYY-MM-DD", "total_found": int}` или
`{}` (кэш 5мин). Эндпоинт: `GET https://api.hh.ru/negotiations?per_page=100&page=`
(официальный API; лента newest-first, остановка при достижении полуночи MSK).
В apidocs не пробивался.

#### E35. fetch_negotiations_statistic

```python
def fetch_negotiations_statistic(self) -> dict
```

Streak-статистика откликов (геймификация «часто отвечает»). Возврат:
`{"responses_count": int, "responses_required": int}` или `{}` (кэш 30мин).
Эндпоинт: `GET /negotiations_statistic/mine` (гр.5, live) с обязательными
`x-force-app-access: true` + `User-Agent: ru.hh.android/26.28.1` (без них 406):

```json
{"applicant_statistic": {"responses_streak": {"responses_count": 1000, "responses_required": 10}}}
```

#### E36. fetch_resume_status

```python
def fetch_resume_status(self) -> dict
```

Статус резюме. Возврат: `{"status_id", "status_name", "blocked": bool,
"finished": bool, "progress": int, "moderation_note": [str]}` или `{}`
(кэш 5мин). Эндпоинт: `GET https://api.hh.ru/resumes/{hash}/status`
(официальный API; в apidocs не пробивался).

#### E37. fetch_employer_rating_oauth

```python
def fetch_employer_rating_oauth(self, employer_id: str) -> dict
```

Рейтинг работодателя через OAuth (имя с `_oauth` чтобы не сталкиваться с
web-методом A12). Возврат: `{"rating": float, "reviews_count": int,
"recommendations_percent": int}`; `{}` если нет отзывов (404, кэш 1ч) или
нет токена; транспортная ошибка → `{}` с кэшем 60с. Кэш успеха 24ч глобальный
(рейтинг не зависит от аккаунта). Эндпоинт: `GET /employers/{id}/reviews`
(гр.4, live — полный пример в A12).

---

## 4. Ошибки и исключения

**Собственных типов исключений у интерфейса/реализаций нет.** Проверено по
репозиторию: классы вида `*Error`/`HHTTPError` в проекте отсутствуют (в т.ч.
в `app/hh_http.py`). Конвенции:

1. **`NotImplementedError`** — единственное, что реально кидается.
   - `MobileHHClient`: все заглушки — `raise NotImplementedError("phase N: TODO mobile <method>")`
     (phase 2 = переговоры/чаты, phase 3 = отклики, phase 4 = резюме/статистика).
     Текст сообщения стабилен, содержит фазу и имя метода — можно парсить/тестировать.
   - `WebHHClient.fetch_counters`: `NotImplementedError("phase 0: web-клиент не имеет аналога GET /me")`.
   Новый код, вызывающий клиент, должен быть готов к `NotImplementedError`,
   пока фазы 2–4 не реализованы.

2. **Error-values вместо исключений** — все прочие ошибки возвращаются
   значениями, не raise:
   - `False` — `send_message`, `send_participant_action`, `mark_chat_read`;
   - `"chat_not_found"` — специальный строковый маркер `send_message`;
   - `{}` — большинство dict-методов (`fetch_counters`, группа E при
     отсутствии токена/ошибке), `[]`/`set()` — list/set-методы группы E,
     `""` — `fetch_resume`;
   - `None` — `fetch_employer_rating`, `fetch_employer_id_for_vacancy`,
     `fetch_vacancy_owner_hr_hhid`;
   - `("error", {...})` / `("auth_error", {})` — tuple-методы группы B
     (`submit_response`, `fill_questionnaire`);
   - `{"ok": False, "error": ...}` — `edit_resume_field`, `set_job_search_status`;
   - `"auth_error": True` внутри результата — `fetch_negotiations` (протухли куки);
   - `{"error": ...}` — `analyze_resume`, `fetch_thread` (поле `error` в dict).

3. **Транспортные исключения гасятся внутри реализаций**: `requests.*`,
   `aiohttp.*`, `json.JSONDecodeError` ловятся в каждой web-flow функции
   (обычно `except Exception` → пустое значение / log_debug). Исключение —
   `submit_response`: `("error", {"exception": str(e)})` при сбое aiohttp.

4. **Транспортный слой `HH` (app/hh_http.py)** не кидает собственных типов:
   при сбое curl_cffi — fallback на `requests` с записью в `data/diag.log`;
   не-2xx ответы классифицируются (`auth`, `ddos_guard`, `captcha`,
   `ratelimit`, `server_error`, `blocked`) и логируются в diag, но наверх
   отдаётся обычный `Response`.

5. **Семантика кодов HH, зашитая в реализациях** (полезно знать при портировании на mobile):
   - 401/403/login-page → `auth_error` (web) / invalidate OAuth-токена (mobile);
   - 404 → `not_found`-ветки (`{"archived": True}` у `fetch_vacancy_details`,
     `chat_not_found` у отправки, `topic_not_found` у `GET /negotiations/{topic_id}`, гр.1);
   - 409 → duplicate/rate (отправка сообщений) либо `chat_not_found` по маркерам тела;
   - 429 → лимит/кулдаун (`limit` + `Retry-After`; touch: «подождите 4 часа»);
   - mobile-эндпоинты групп 1–8 требуют заголовки `Authorization: Bearer`,
     для mobile-only ручек — `x-force-app-access: true` + mobile UA
     (без них наблюдался 406, см. E35).

---

## 5. Что не подтверждено apidocs (сводка для портирующих)

| Метод | Проблема |
|---|---|
| `fetch_negotiations`, `check_limit` | список/лимит переговоров в apidocs не пробивался (гр.1: `GET /negotiations?...` — «записи нет») |
| `fetch_possible_offers`, `fetch_related_vacancies`, `fetch_vacancy_owner_hr_hhid`, `set_job_search_status`, `auto_decline_discards` (write-часть), `edit_resume_field` (write-часть) | аналогов среди 169 endpoints не найдено |
| `send_message`, `mark_chat_read`, `fetch_quick_replies`, `send_participant_action` | APK-контракты без live-проб (SAFETY); у quick_replies конфликт источников POST vs PUT |
| `fill_questionnaire` | HTML-формы анкет в mobile API не задокументированы |
| `fetch_stats`, `fetch_resume_views_aggregate` | покрытия 1:1 нет — только частичные поля (total/new views) |
| E30/E34/E36 (`saved_searches`, `GET /negotiations`, `/resumes/{hash}/status`) | официальный публичный API, в apidocs-пробах отсутствует (контракты взяты из работающего кода `app/oauth.py`) |

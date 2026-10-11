"""Тесты Phase 4: mobile-версия analyze_resume (app/mobile_resume_analyze.py).

Проверяется полный путь: analyze_resume(acc) →
app.hh_mobile_transport.mobile_request → реальный HTTP (перехваченный
библиотекой `responses`) → разбор ответов пяти endpoint'ов
(GET /resumes/{id}, POST skills_profile/predictions/recommended_skills/resume,
POST skills_profile/suggestions/duties,
POST skills_profile/predictions/subroles/by_title,
GET /career_platform/profile?profession_description=true).
Никаких живых запросов: все URL api.hh.ru замокан, Bearer-токен подменён
через monkeypatch app.oauth._obtain_oauth_token (конвенция
tests/test_mobile_phase2_integration.py).

Контракт результата: {"ok", "resume_id", "title", "missing_skills",
"recommended_duties", "subroles", "grade", "current_score"}.
Политика ошибок: fallback-статусы (0/401/403/5xx) на ЛЮБОМ endpoint'е —
MobileAPIError; не-fallback сбой вспомогательного endpoint'а (2-5) —
соответствующая часть пустая, остальные считаются; не-fallback (404)
GET /resumes/{id} — {"ok": False, "error": "resume_not_found"};
пустой rid — {"ok": False, "error": "no_resume_id"} без запросов аудита.

ИМПОРТ модуля реализации — ВНУТРИ тест-функций (конвенция phase 2/4):
пока Phase 4 пишется параллельно, отсутствующий модуль должен ронять
только свои тесты, а не коллекционирование всего файла.
"""
import json

import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

PATH_RESUME = MOBILE_BASE + "/resumes/rh1"
PATH_REC_SKILLS = (MOBILE_BASE +
                   "/skills_profile/predictions/recommended_skills/resume")
PATH_DUTIES = MOBILE_BASE + "/skills_profile/suggestions/duties"
PATH_SUBROLES = MOBILE_BASE + "/skills_profile/predictions/subroles/by_title"
PATH_PROFILE = MOBILE_BASE + "/career_platform/profile"

# ---------------------------------------------------------------------------
# Мок-ответы. Форма — по контрактам reverse APK + live-пробам
# (apidocs_group_2/3.yaml), зафиксированным в докстринге модуля.
# ---------------------------------------------------------------------------

RESUME_RESPONSE = {
    "id": "rh1",
    "title": "Тестировщик",
    "skill_set": ["Python", "SQL"],
    "skills": [],
}

# Python есть в резюме (точное совпадение), sQl — тоже есть
# (регистронезависимо) → оба исключаются из missing_skills.
REC_SKILLS_RESPONSE = {
    "skills": [
        {"name": "PostgreSQL"},
        {"name": "Python"},
        "Allure",
        {"name": "sQl"},
    ],
}

DUTIES_RESPONSE = {
    "items": [
        {"name": "Проведение ручного тестирования"},
        "Написание тест-кейсов",
    ],
}

SUBROLES_RESPONSE = {
    "subroles": [
        {
            "id": 72,
            "name": "Тестировщик",
            "main": True,
            "probability": 0.975,
            "grades": [{"id": 4, "name": "Junior"}],
            "parent_professional_role": {"id": 113, "name": "IT"},
            "specializations": [],
        },
        {
            "id": 95,
            "name": "Инженер по автоматизации тестирования",
            "main": False,
            "probability": 0.4,
            "grades": [],
        },
    ],
}

PROFILE_RESPONSE = {
    "career_user_goal": {"id": "goal1"},
    "grade": {"id": 5, "name": "Middle"},
    "profession": {"id": 72},
    "skills": {"items": []},
}

ERROR_BODY = {"errors": [{"value": "bad_request"}]}


@pytest.fixture
def oauth_token(monkeypatch):
    """Bearer-токен добывается через app.oauth._obtain_oauth_token —
    подменяем, чтобы не идти в реальный OAuth-flow."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


def _called_urls():
    """Список URL запросов (без query-строки) в порядке вызовов."""
    return [c.request.url.split("?")[0] for c in responses.calls]


def _assert_bearer(req):
    assert req.headers["Authorization"] == "Bearer t"
    # мобильные заголовки транспорта (контракт APK)
    assert req.headers["x-force-app-access"] == "true"


def _body_as_dict(req):
    """JSON-тело запроса как dict."""
    raw = req.body or ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _add_all_mocks(*, resume=RESUME_RESPONSE, resume_status=200,
                   skills=REC_SKILLS_RESPONSE, skills_status=200,
                   duties=DUTIES_RESPONSE, duties_status=200,
                   subroles=SUBROLES_RESPONSE, subroles_status=200,
                   profile=PROFILE_RESPONSE, profile_status=200):
    """Стандартный набор успешных ответов всех пяти endpoint'ов;
    параметры — точечные подмены тела/статуса для тестов сбоев."""
    responses.add(responses.GET, PATH_RESUME,
                  json=resume, status=resume_status)
    responses.add(responses.POST, PATH_REC_SKILLS,
                  json=skills, status=skills_status)
    responses.add(responses.POST, PATH_DUTIES,
                  json=duties, status=duties_status)
    responses.add(responses.POST, PATH_SUBROLES,
                  json=subroles, status=subroles_status)
    responses.add(responses.GET, PATH_PROFILE,
                  json=profile, status=profile_status)


# ---------------------------------------------------------------------------
# 1. Happy-path: все пять endpoint'ов отвечают 2xx.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_analyze_resume_happy_path(oauth_token):
    from app.mobile_resume_analyze import analyze_resume

    _add_all_mocks()

    result = analyze_resume(ACC)

    assert result["ok"] is True
    assert result["resume_id"] == "rh1"
    assert result["title"] == "Тестировщик"
    # Python (точное совпадение) и sQl (регистронезависимо) уже есть
    # в резюме → исключены из рекомендаций
    assert result["missing_skills"] == ["PostgreSQL", "Allure"]
    assert result["recommended_duties"] == [
        "Проведение ручного тестирования",
        "Написание тест-кейсов",
    ]
    assert len(result["subroles"]) == 2
    main_subrole = result["subroles"][0]
    assert main_subrole["id"] == 72
    assert main_subrole["name"] == "Тестировщик"
    assert main_subrole["main"] is True
    assert main_subrole["probability"] == 0.975
    # current_score — max probability по сабролям
    assert result["current_score"] == 0.975
    # грейд из career_platform/profile: dict → name
    assert result["grade"] == "Middle"

    # все пять endpoint'ов, порядок: резюме → skills → duties → subroles
    # → profile
    assert _called_urls() == [
        PATH_RESUME, PATH_REC_SKILLS, PATH_DUTIES, PATH_SUBROLES, PATH_PROFILE,
    ]

    # тела POST-запросов (контракты endpoint'ов 2-4)
    body_skills = _body_as_dict(responses.calls[1].request)
    assert body_skills["resume_id"] == "rh1"
    assert body_skills["limit"] == 20
    body_duties = _body_as_dict(responses.calls[2].request)
    assert body_duties == {"resume_id": "rh1"}
    body_subroles = _body_as_dict(responses.calls[3].request)
    assert body_subroles == {"title": "Тестировщик"}

    # GET career_platform/profile с profession_description=true
    req_profile = responses.calls[4].request
    assert req_profile.method == "GET"
    assert "profession_description=true" in req_profile.url

    # Bearer + x-force-app-access на каждом запросе
    for call in responses.calls:
        _assert_bearer(call.request)


# ---------------------------------------------------------------------------
# 2. Сбой вспомогательного endpoint'а (duties → 400): duties пустые,
#    остальные части заполнены, БЕЗ исключения.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_analyze_resume_duties_400_rest_survives(oauth_token):
    from app.mobile_resume_analyze import analyze_resume

    _add_all_mocks(duties_status=400, duties=ERROR_BODY)

    result = analyze_resume(ACC)  # НЕ кидает

    assert result["ok"] is True
    assert result["recommended_duties"] == []
    # остальные части считаются несмотря на сбой duties
    assert result["missing_skills"] == ["PostgreSQL", "Allure"]
    assert result["subroles"][0]["name"] == "Тестировщик"
    assert result["current_score"] == 0.975
    assert result["grade"] == "Middle"


@responses.activate
def test_mobile_analyze_resume_paused_returns_partial_json(oauth_token):
    from app.mobile_resume_analyze import analyze_resume

    _add_all_mocks()
    paused_acc = {**ACC, "_mutation_guard": lambda: False}

    result = analyze_resume(paused_acc)

    assert result["ok"] is True
    assert result["partial"] is True
    assert result["missing_skills"] == []
    assert result["recommended_duties"] == []
    assert result["subroles"] == []
    assert [error["error"] for error in result["errors"]] == ["account_paused"] * 3
    assert _called_urls() == [PATH_RESUME, PATH_PROFILE]


# ---------------------------------------------------------------------------
# 3. GET /resumes/{id}: 404 → resume_not_found; 401/500 → MobileAPIError.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_analyze_resume_404_resume_not_found(oauth_token):
    from app.mobile_resume_analyze import analyze_resume

    responses.add(responses.GET, PATH_RESUME,
                  json={"errors": [{"value": "resume_not_found"}]},
                  status=404)

    result = analyze_resume(ACC)

    assert result == {"ok": False, "error": "resume_not_found"}
    # дальше GET /resumes/{id} дело не пошло
    assert _called_urls() == [PATH_RESUME]


@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_mobile_analyze_resume_resume_fallback_status_raises(oauth_token,
                                                             status):
    """401/5xx на основном endpoint'е — fallback-статус: кидает
    MobileAPIError, вызов целиком повторится через web-flow."""
    from app.mobile_resume_analyze import analyze_resume

    responses.add(responses.GET, PATH_RESUME,
                  json={"errors": [{"value": "token_expired"}]},
                  status=status)

    with pytest.raises(MobileAPIError) as ei:
        analyze_resume(ACC)
    assert ei.value.status_code == status
    assert _called_urls() == [PATH_RESUME]


@responses.activate
def test_mobile_analyze_resume_aux_fallback_status_raises(oauth_token):
    """Fallback-статус на вспомогательном endpoint'е тоже поднимается
    (политика: ЛЮБОЙ endpoint) — повтор через web-flow целиком."""
    from app.mobile_resume_analyze import analyze_resume

    _add_all_mocks(skills_status=500, skills=ERROR_BODY)

    with pytest.raises(MobileAPIError) as ei:
        analyze_resume(ACC)
    assert ei.value.status_code == 500


# ---------------------------------------------------------------------------
# 4. career_platform/profile: grade строкой; 404 → grade None, ok True.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_analyze_resume_grade_string(oauth_token):
    from app.mobile_resume_analyze import analyze_resume

    _add_all_mocks(profile={"career_user_goal": None, "grade": "JUNIOR",
                            "profession": None, "skills": None})

    result = analyze_resume(ACC)

    assert result["ok"] is True
    assert result["grade"] == "JUNIOR"


@responses.activate
def test_mobile_analyze_resume_profile_404_grade_none(oauth_token):
    from app.mobile_resume_analyze import analyze_resume

    _add_all_mocks(profile_status=404, profile=ERROR_BODY)

    result = analyze_resume(ACC)  # НЕ кидает

    assert result["ok"] is True
    assert result["grade"] is None
    # сбой profile не роняет остальные части
    assert result["missing_skills"] == ["PostgreSQL", "Allure"]
    assert result["current_score"] == 0.975


# ---------------------------------------------------------------------------
# 5. Пустой title: POST by_title НЕ выполняется, subroles/current_score
#    пустые.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_analyze_resume_empty_title_skips_subroles(oauth_token):
    from app.mobile_resume_analyze import analyze_resume

    _add_all_mocks(resume={"id": "rh1", "title": "",
                           "skill_set": [], "skills": []})

    result = analyze_resume(ACC)

    assert result["ok"] is True
    assert result["title"] == ""
    assert result["subroles"] == []
    assert result["current_score"] is None
    # by_title с пустым title не запрашивается: 4 запроса вместо 5
    assert PATH_SUBROLES not in _called_urls()
    assert len(responses.calls) == 4


# ---------------------------------------------------------------------------
# 6. Пустой rid: резолв ничего не нашёл → no_resume_id без запросов аудита.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_analyze_resume_no_resume_id(oauth_token):
    from app.mobile_resume_analyze import analyze_resume

    acc_no_hash = {"name": "a1", "cookies": {}}  # без resume_hash
    # оба пути списка резюме (mobile_resume_common) вернули пусто
    responses.add(responses.GET, MOBILE_BASE + "/mobile/resumes/mine",
                  json={"items": []}, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/mine",
                  json={"items": []}, status=200)

    result = analyze_resume(acc_no_hash)

    assert result == {"ok": False, "error": "no_resume_id"}
    # дальше резолва дело не пошло — ни одного запроса аудита
    assert _called_urls() == [
        MOBILE_BASE + "/mobile/resumes/mine",
        MOBILE_BASE + "/resumes/mine",
    ]


# ---------------------------------------------------------------------------
# 7. Делегат: MobileHHClient(ACC).analyze_resume(extra_terms, resume_id).
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_client_analyze_resume_delegate(oauth_token):
    from app.hh_client_mobile import MobileHHClient

    _add_all_mocks()

    # extra_terms позиционно (в mobile не используется — web-SSR
    # supply/demand), resume_id явно
    result = MobileHHClient(ACC).analyze_resume(["qa"], "rh1")

    assert result["ok"] is True
    assert result["resume_id"] == "rh1"
    assert result["title"] == "Тестировщик"
    assert result["missing_skills"] == ["PostgreSQL", "Allure"]
    assert result["current_score"] == 0.975
    assert result["grade"] == "Middle"

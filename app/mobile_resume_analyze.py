"""Mobile-версия analyze_resume: ML-аудит резюме через api.hh.ru (Phase 4).

Комбинация четырёх endpoint'ов (контракты — reverse APK
ru.hh.android/26.28.1 + live-пробы scratchpad/apidocs/apidocs_group_3.yaml):

1. GET https://api.hh.ru/resumes/{resume_id} — title/skills резюме
   (база для остальных запросов; apidocs_group_2.yaml).
2. POST https://api.hh.ru/skills_profile/predictions/recommended_skills/resume
   body {"resume_id", "chosen_skills"?, "limit"?} → {"skills": [...]} —
   навыки, которые стоит добавить (APK zy/InterfaceC10766b.java).
3. POST https://api.hh.ru/skills_profile/suggestions/duties
   body {"resume_id", "experience_title"?} → {"items": [...]} —
   рекомендуемые обязанности (APK oB/InterfaceC8495a.java).
4. POST https://api.hh.ru/skills_profile/predictions/subroles/by_title
   body {"title"} → {"subroles": [{id, name, main, probability, grades}]}
   — саброли/грейды по тайтлу (apidocs_group_3.yaml, live).
5. GET https://api.hh.ru/career_platform/profile?profession_description=true
   → {career_user_goal, grade, profession, skills} — грейд профессии
   (APK CareerGoalNetworkApi.kt).

Возврат (контракт Phase 4):
    {"ok": True, "resume_id", "title",
     "missing_skills": [...],        # что добавить в резюме
     "recommended_duties": [...],    # обязанности
     "subroles": [...],              # [{id, name, main, probability}]
     "grade": "MIDDLE"|...,          # из career_platform/profile
     "current_score": 0.85|None}     # max probability сабролей (эвристика)

Отказоустойчивость: не-fallback ошибка вспомогательного endpoint'а
(2-5) — log_debug, соответствующая часть результата пустая, остальные
считаются. Fallback-статус (0/401/403/5xx) на ЛЮБОМ endpoint'е —
MobileAPIError наверх (вызов целиком повторится через web-flow).
Не-fallback ошибка основного GET /resumes/{id} (404) —
{"ok": False, "error": "resume_not_found"}; rid не зарезолвился —
{"ok": False, "error": "no_resume_id"} без сетевых запросов аудита.

extra_terms (аргумент web-версии, supply/demand по SSR-поискам) в
mobile не используется — сохранён в клиентской сигнатуре ради контракта.
"""

from app.mutation_safety import MutationBlocked
from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug
from app.mobile_resume_common import resolve_resume_id


def _item_name(item) -> str:
    """Имя элемента mobile-ответа: str либо dict {"name"|"string"|"text"}
    (формы элементов skill_set/skills/items у endpoint'ов 2-3). Пустая
    строка, если элемент другой формы."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("name", "string", "text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _names(items) -> list:
    """Список непустых имён из массива str/dict-элементов; не-массив → []."""
    if not isinstance(items, list):
        return []
    return [name for name in (_item_name(it) for it in items) if name]


def _as_float(value) -> float:
    """probability саброли → float; None/мусор → 0.0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dict_items(items) -> list:
    """Только dict-элементы массива (саброли); не-массив/мусор → []."""
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict)]


def _aux_request(acc: dict, label: str, method: str, path: str, errors=None, **kwargs):
    """Вспомогательный запрос (endpoint'ы 2-5): fallback-статусы
    (0/401/403/5xx) поднимаем MobileAPIError наверх — вызов целиком
    повторится через web-flow; не-fallback ошибки — log_debug и None
    (соответствующая часть результата останется пустой)."""
    try:
        return mobile_request(acc, method, path, **kwargs)
    except MutationBlocked:
        # The POST prediction endpoints only read suggestions, but the shared
        # transport guards every POST while an account is paused.
        log_debug(f"mobile analyze_resume {label}: аккаунт на паузе — часть результата пустая")
        if errors is not None:
            errors.append({"endpoint": label, "error": "account_paused"})
        return None
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise
        log_debug(f"mobile analyze_resume {label}: HTTP {e.status_code} | "
                  f"{e.payload} — часть результата пустая")
        if errors is not None:
            errors.append({"endpoint": label, "error": f"HTTP {e.status_code}"})
        return None


def analyze_resume(acc: dict, resume_id=None) -> dict:
    """ML-аудит резюме через mobile-API (аналог web
    hh_resume._analyze_resume — другой состав данных: вместо SSR-парсинга
    ML-предсказания skills_profile/career_platform).

    resume_id=None — резолвится в первое резюме аккаунта
    (mobile_resume_common.resolve_resume_id: явный аргумент →
    acc["resume_hash"] → GET /mobile/resumes/mine). Возвращает dict
    (см. докстринг модуля): {"ok", "resume_id", "title", "missing_skills",
    "recommended_duties", "subroles", "grade", "current_score"}.

    Политика ошибок: fallback-статусы (0/401/403/5xx) на ЛЮБОМ endpoint'е
    — MobileAPIError наверх (повтор через web-flow); не-fallback (404)
    GET /resumes/{id} — {"ok": False, "error": "resume_not_found"};
    не-fallback сбои вспомогательных endpoint'ов (2-5) — соответствующая
    часть пустая, остальные считаются; пустой rid —
    {"ok": False, "error": "no_resume_id"} без запросов аудита.
    """
    rid = resolve_resume_id(acc, resume_id)
    if not rid:
        log_debug("mobile analyze_resume: resume_id не зарезолвлено — "
                  "аудит без резюме невозможен")
        return {"ok": False, "error": "no_resume_id"}

    # 1. Резюме — база для остальных запросов (title + существующие навыки).
    try:
        resume = mobile_request(acc, "GET", f"/resumes/{rid}")
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # 0 (сеть) / 401 / 403 / 5xx: не глотим — fallback-обёртка
            # повторит вызов через web-flow.
            raise
        log_debug(f"mobile analyze_resume GET /resumes/{rid}: HTTP "
                  f"{e.status_code} | {e.payload}")
        return {"ok": False, "error": "resume_not_found"}
    if not isinstance(resume, dict):
        return {"ok": False, "error": "resume_not_found"}

    title_raw = resume.get("title")
    title = title_raw.strip() if isinstance(title_raw, str) else ""

    # Существующие навыки резюме (skill_set в приоритете, при пустом —
    # skills; регистронезависимая база для вычитания recommended_skills).
    raw_skills = resume.get("skill_set") or resume.get("skills")
    existing_lower = {name.lower() for name in _names(raw_skills)}
    errors: list = []

    # 2. Рекомендуемые навыки → missing_skills: что стоит ДОБАВИТЬ в резюме
    # (регистронезависимо минус существующие, порядок ответа сохраняем).
    missing_skills: list = []
    data = _aux_request(acc, "recommended_skills", "POST",
                        "/skills_profile/predictions/recommended_skills/resume",
                        errors=errors, json_body={"resume_id": rid, "limit": 20})
    if isinstance(data, dict):
        seen_lower = set(existing_lower)
        for name in _names(data.get("skills")):
            low = name.lower()
            if low in seen_lower:
                # уже есть в резюме либо дубль в самих рекомендациях
                continue
            seen_lower.add(low)
            missing_skills.append(name)

    # 3. Рекомендуемые обязанности.
    recommended_duties: list = []
    data = _aux_request(acc, "duties", "POST",
                        "/skills_profile/suggestions/duties",
                        errors=errors, json_body={"resume_id": rid})
    if isinstance(data, dict):
        recommended_duties = _names(data.get("items"))

    # 4. Саброли/грейды по тайтлу (пустой title — запрос не выполняется).
    subroles: list = []
    if title:
        data = _aux_request(acc, "subroles", "POST",
                            "/skills_profile/predictions/subroles/by_title",
                            errors=errors, json_body={"title": title})
        raw_subroles = data.get("subroles") if isinstance(data, dict) else None
        for sub in _dict_items(raw_subroles):
            subroles.append({
                "id": sub.get("id"),
                "name": _item_name(sub),
                "main": bool(sub.get("main")),
                "probability": _as_float(sub.get("probability")),
            })
    # Эвристика overall-скора резюме: max probability сабролей.
    current_score = max((s["probability"] for s in subroles), default=None)

    # 5. Грейд профессии из career_platform/profile.
    grade = None
    data = _aux_request(acc, "career_platform/profile", "GET",
                        "/career_platform/profile",
                        errors=errors, params={"profession_description": "true"})
    if isinstance(data, dict):
        grade_raw = data.get("grade")
        if isinstance(grade_raw, dict):
            grade_raw = grade_raw.get("name") or grade_raw.get("id")
        if grade_raw is not None:
            grade = grade_raw if isinstance(grade_raw, str) else str(grade_raw)

    return {
        "ok": True,
        "resume_id": rid,
        "title": title,
        "missing_skills": missing_skills,
        "recommended_duties": recommended_duties,
        "subroles": subroles,
        "grade": grade,
        "current_score": current_score,
        "partial": bool(errors),
        "errors": errors,
    }

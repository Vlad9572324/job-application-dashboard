"""Known unsupported claims must stop before questionnaire submission."""

import asyncio
from types import SimpleNamespace

from app.questionnaire_claims import unsupported_questionnaire_claims
import app.hh_apply as hh_apply


QUESTIONS = [
    {"field": "task_1_text", "type": "textarea", "text": "Какие у Вас зарплатные ожидания?"},
    {"field": "task_2_text", "type": "textarea", "text": "Как скоро вы готовы приступить к работе?"},
    {"field": "task_3_text", "type": "textarea", "text": "Расскажите про опыт работы."},
]


def test_blocks_claims_from_previous_traces():
    answers = {"task_1_text": "Мои ожидания 100 000 рублей gross + премия.",
               "task_2_text": "Я готова приступить через 2 недели.",
               "task_3_text": "Имею 5 лет опыта QA."}
    issues = unsupported_questionnaire_claims(
        QUESTIONS, answers, dict.fromkeys(answers, "llm"),
        "Общий опыт: 3 л. 0 мес. Зарплата не указана.", "Отвечай кратко.")
    assert issues == [
        {"field": "task_1_text", "reasons": ["salary_amount", "salary_bonus"]},
        {"field": "task_2_text", "reasons": ["start_delay"]},
        {"field": "task_3_text", "reasons": ["experience_years"]},
    ]


def test_blocks_salary_range_when_question_says_zarabotnaya_plata():
    questions = [{"field": "task_1_text", "type": "textarea",
                  "text": "На какую заработную плату Вы рассчитываете? Укажите минимальный и оптимальный уровень."}]
    answers = {"task_1_text": "Я рассчитываю на диапазон от 100000 до 120000 рублей в месяц."}
    assert unsupported_questionnaire_claims(
        questions, answers, {"task_1_text": "llm"},
        "Общий опыт: 3 л. 0 мес. Зарплата не указана.", "Отвечай кратко.") == [
        {"field": "task_1_text", "reasons": ["salary_amount"]}]


def test_blocks_unsupported_product_example_from_live_questionnaire():
    questions = [{"field": "task_3_text", "type": "textarea",
                  "text": "С какими типами продуктов приходилось сталкиваться в работе QA: REST API, сайты, десктоп?"}]
    answers = {"task_3_text": "Я тестировала REST API и десктопный софт."}
    issues = unsupported_questionnaire_claims(
        questions, answers, {"task_3_text": "llm"}, "Работала с REST и SQL.", "Отвечай кратко.")
    assert issues == [{"field": "task_3_text", "reasons": ["unsupported_domain_desktop"]}]


def test_allows_supported_and_noncommittal_answers():
    answers = {"task_1_text": "Ожидания 100 тыс. рублей, без премии.",
               "task_2_text": "Могу приступить через две недели.",
               "task_3_text": "У меня 3 года опыта."}
    source = "Зарплата: 100 000 рублей. Премия не предусмотрена. Выход через 2 недели. Общий опыт: 3 л. 0 мес."
    assert unsupported_questionnaire_claims(
        QUESTIONS, answers, dict.fromkeys(answers, "llm"), source, "") == []
    noncommittal = {"task_1_text": "Предпочтения обсудим.",
                    "task_2_text": "Дату выхода обсудим.",
                    "task_3_text": "Опыт описан в резюме."}
    assert unsupported_questionnaire_claims(
        QUESTIONS, noncommittal, dict.fromkeys(noncommittal, "llm"), "", "") == []


def test_blocks_before_questionnaire_post(monkeypatch):
    class Response:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def text(self):
            return ('<div data-qa="task-question">Какие у Вас зарплатные ожидания?</div>'
                    '<textarea name="task_1_text"></textarea>')

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def get(self, *args, **kwargs): return Response()
        def post(self, *args, **kwargs): raise AssertionError("POST must be blocked")

    monkeypatch.setattr(hh_apply, "aiohttp", SimpleNamespace(
        ClientSession=lambda **kwargs: Session(), ClientTimeout=lambda **kwargs: kwargs))
    monkeypatch.setattr(hh_apply, "_aio_egress_kwargs", lambda: ({}, {}))
    monkeypatch.setattr(hh_apply, "fetch_resume_text", lambda acc: "Общий опыт: 3 л. 0 мес.")
    monkeypatch.setattr(hh_apply, "generate_llm_questionnaire_answers", lambda *args, **kwargs:
                        {"task_1_text": "Ожидания 100 000 рублей."})
    monkeypatch.setattr(hh_apply.CONFIG, "llm_enabled", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_fill_questionnaire", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_check_questionnaire_claims", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_use_resume", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_system_prompt", "Отвечай кратко.")
    events = []
    result = asyncio.run(hh_apply.fill_and_submit_questionnaire(
        {"cookies": {}, "resume_hash": "r", "mode": "web"}, "12345678",
        trace=lambda stage, details: events.append((stage, details)), require_llm=True))
    assert result[0] == "error"
    assert result[1]["error_code"] == "unsupported_claims"
    assert any(stage == "answer_review_blocked" for stage, _ in events)
    assert all(stage != "submission_started" for stage, _ in events)

    monkeypatch.setattr(hh_apply.CONFIG, "llm_check_questionnaire_claims", False)
    events.clear()
    preview, info = asyncio.run(hh_apply.fill_and_submit_questionnaire(
        {"cookies": {}, "resume_hash": "r", "mode": "web"}, "12345678",
        trace=lambda stage, details: events.append((stage, details)),
        require_llm=True, preview_only=True))
    assert preview == "preview"
    assert info["answers"]["task_1_text"] == "Ожидания 100 000 рублей."
    assert all(stage != "answer_review_blocked" for stage, _ in events)


def test_preview_returns_reviewable_answers_without_post(monkeypatch):
    class Response:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def text(self):
            return ('<div data-qa="task-question">Какие ваши ожидания?</div>'
                    '<textarea name="task_1_text"></textarea>')

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def get(self, *args, **kwargs): return Response()
        def post(self, *args, **kwargs): raise AssertionError("preview must not POST")

    monkeypatch.setattr(hh_apply, "aiohttp", SimpleNamespace(
        ClientSession=lambda **kwargs: Session(), ClientTimeout=lambda **kwargs: kwargs))
    monkeypatch.setattr(hh_apply, "_aio_egress_kwargs", lambda: ({}, {}))
    monkeypatch.setattr(hh_apply, "fetch_resume_text", lambda acc: "Общий опыт: 3 л. 0 мес.")
    monkeypatch.setattr(hh_apply, "generate_llm_questionnaire_answers", lambda *args, **kwargs:
                        {"task_1_text": "Готова обсудить ожидания."})
    monkeypatch.setattr(hh_apply.CONFIG, "llm_enabled", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_fill_questionnaire", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_use_resume", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_applicant_gender", "female")
    result, info = asyncio.run(hh_apply.fill_and_submit_questionnaire(
        {"cookies": {}, "resume_hash": "r", "mode": "web"}, "12345678",
        trace=lambda *args: None, require_llm=True, preview_only=True))
    assert result == "preview"
    assert info["answers"] == {"task_1_text": "Готова обсудить ожидания."}
    changed, details = asyncio.run(hh_apply.fill_and_submit_questionnaire(
        {"cookies": {}, "resume_hash": "r", "mode": "web"}, "12345678",
        trace=lambda *args: None, require_llm=True,
        approved_answers=info["answers"], expected_questions=[]))
    assert (changed, details) == ("error", {"error_code": "reviewed_form_changed"})

import asyncio
from types import SimpleNamespace

from app.config import CONFIG, Config, applicant_gender_forms
from app.gender_guard import conflicting_gender_words
import app.hh_apply as hh_apply
from app import mobile_apply
from app import oauth


def test_opposite_gender_words_are_detected(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "female")
    assert conflicting_gender_words("Я ознакомился с вакансией и готов работать.") == ["ознакомился", "готов"]
    assert conflicting_gender_words("Я ознакомилась с вакансией и готова работать.") == []
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "male")
    assert conflicting_gender_words("Я работала QA и заинтересована в роли.") == ["работала", "заинтересована"]
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "neutral")
    assert conflicting_gender_words("Могу рассказать подробнее.") == []
    assert conflicting_gender_words("Я готова рассказать подробнее.") == ["готова"]


def test_default_letter_and_prompt_follow_gender(monkeypatch):
    assert not conflicting_gender_words(Config.letter_templates[0]["text"], "female")
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "female")
    assert applicant_gender_forms()["responded"] == "соискательница откликнулась"


def test_mobile_cover_letter_blocked_before_transport(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "female")
    monkeypatch.setattr(mobile_apply, "pick_suitable_resume", lambda *args: (_ for _ in ()).throw(
        AssertionError("must stop before transport")))
    result = mobile_apply.submit_response({}, "12345678", "r", "Я готов работать.")
    assert result["error_type"] == "gender_mismatch"


def test_web_and_oauth_letters_blocked_before_transport(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "female")
    monkeypatch.setattr(CONFIG, "hh_ai_letter_first_try", False)
    result = asyncio.run(hh_apply.send_response_async(
        {"name": "Tester", "cookies": {"_xsrf": "x"}, "resume_hash": "r",
         "letter": "Я готов работать."}, "12345678"))
    assert result[1]["error_code"] == "gender_mismatch"
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda acc: (_ for _ in ()).throw(
        AssertionError("OAuth token fetch must not occur")))
    result = oauth._oauth_apply({}, "12345678", "Я готов работать.")
    assert result[1]["error_code"] == "gender_mismatch"


def test_questionnaire_gender_blocked_before_post(monkeypatch):
    class Response:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def text(self):
            return ('<div data-qa="task-question">Расскажите о себе</div>'
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
                        {"task_1_text": "Я работал в тестировании."})
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "female")
    monkeypatch.setattr(CONFIG, "llm_enabled", True)
    monkeypatch.setattr(CONFIG, "llm_fill_questionnaire", True)
    monkeypatch.setattr(CONFIG, "llm_use_resume", True)
    stages = []
    result = asyncio.run(hh_apply.fill_and_submit_questionnaire(
        {"cookies": {}, "resume_hash": "r", "mode": "web"}, "12345678",
        trace=lambda stage, details: stages.append(stage), require_llm=True))
    assert result[0] == "error" and result[1]["error_code"] == "gender_mismatch"
    assert "answer_gender_blocked" in stages and "submission_started" not in stages

"""A targeted questionnaire submission must stay isolated from automation."""

import asyncio
import json
from types import SimpleNamespace

from app.routes import questionnaire_trace as mod
import app.hh_apply as hh_apply
import app.llm as llm
import app.storage as storage


def test_trace_requires_global_pause(monkeypatch, tmp_path):
    state = SimpleNamespace(name="Tester", acc={"mode": "web"})
    bot = SimpleNamespace(paused=False, _get_apply_state=lambda idx: state)
    monkeypatch.setattr(mod, "bot", bot)
    monkeypatch.setattr(mod, "TRACE_FILE", tmp_path / "trace.jsonl")
    result = asyncio.run(mod.trace_questionnaire({"account_idx": 0, "vacancy_id": "12345678"}))
    assert result["ok"] is False
    assert "остановите" in result["error"]
    assert not mod.TRACE_FILE.exists()


def test_trace_records_answer_and_blocks_duplicate(monkeypatch, tmp_path):
    state = SimpleNamespace(name="Tester", short="T", color="", acc={"mode": "web", "resume_hash": "r"},
                            sent=0, daily_sent=0, questionnaire_sent=0)
    bot = SimpleNamespace(paused=True, _get_apply_state=lambda idx: state,
                          _can_mutate=lambda state, **kwargs: True,
                          _maybe_roll_daily_counter=lambda state: None,
                          _add_log=lambda *args: None)
    monkeypatch.setattr(mod, "bot", bot)
    monkeypatch.setattr(mod.CONFIG, "automation_paused", True)
    monkeypatch.setattr(mod.CONFIG, "llm_enabled", True)
    monkeypatch.setattr(mod.CONFIG, "llm_fill_questionnaire", True)
    monkeypatch.setattr(mod, "is_test", lambda vid: True)
    monkeypatch.setattr(mod, "is_applied", lambda account, vid: False)
    saved = []
    monkeypatch.setattr(mod, "add_applied", lambda *args, **kwargs: saved.append((args, kwargs)))
    monkeypatch.setattr(mod, "TRACE_FILE", tmp_path / "trace.jsonl")

    async def fake_fill(account, vid, **kwargs):
        assert account["_mutation_guard"]() is True
        assert kwargs["require_llm"] is True
        kwargs["trace"]("llm_response", {"provider": "api", "model": "test-model", "answers": {"task_1_text": "answer"}})
        kwargs["trace"]("submission_started", {})
        return "sent", {}

    monkeypatch.setattr("app.hh_apply.fill_and_submit_questionnaire", fake_fill)
    result = asyncio.run(mod.trace_questionnaire({"account_idx": 0, "vacancy_id": "12345678"}))
    assert result["status"] == "sent"
    assert (state.sent, state.daily_sent, state.questionnaire_sent) == (1, 1, 1)
    assert saved == [(("Tester", "12345678"), {})]
    lines = [json.loads(line) for line in mod.TRACE_FILE.read_text().splitlines()]
    assert [line["stage"] for line in lines] == ["started", "llm_response", "submission_started", "result"]
    assert lines[1]["details"]["answers"] == {"task_1_text": "answer"}
    duplicate = asyncio.run(mod.trace_questionnaire({"account_idx": 0, "vacancy_id": "12345678"}))
    assert duplicate["ok"] is False
    assert "уже была" in duplicate["error"]


def test_reviewed_preview_reuses_exact_answers(monkeypatch, tmp_path):
    state = SimpleNamespace(name="Tester", short="T", color="", acc={"mode": "web", "resume_hash": "r"},
                            sent=0, daily_sent=0, questionnaire_sent=0)
    bot = SimpleNamespace(paused=True, _get_apply_state=lambda idx: state,
                          _can_mutate=lambda state, **kwargs: True,
                          _maybe_roll_daily_counter=lambda state: None,
                          _add_log=lambda *args: None)
    monkeypatch.setattr(mod, "bot", bot)
    monkeypatch.setattr(mod.CONFIG, "automation_paused", True)
    monkeypatch.setattr(mod.CONFIG, "llm_enabled", True)
    monkeypatch.setattr(mod.CONFIG, "llm_fill_questionnaire", True)
    monkeypatch.setattr(mod, "is_test", lambda vid: True)
    monkeypatch.setattr(mod, "is_applied", lambda account, vid: False)
    monkeypatch.setattr(mod, "add_applied", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "TRACE_FILE", tmp_path / "trace.jsonl")
    mod._review_drafts.clear()
    questions = [{"field": "task_1_text", "type": "textarea", "text": "Опыт?", "options": []}]
    answers = {"task_1_text": "По резюме три года."}

    async def fake_fill(account, vid, **kwargs):
        if kwargs["preview_only"]:
            assert kwargs["approved_answers"] is None
            kwargs["trace"]("answers_ready", {"answers": answers})
            return "preview", {"questions": questions, "answers": answers, "sources": {"task_1_text": "llm"}}
        assert kwargs["approved_answers"] == answers
        assert kwargs["expected_questions"] == questions
        kwargs["trace"]("submission_started", {})
        return "sent", {}

    monkeypatch.setattr("app.hh_apply.fill_and_submit_questionnaire", fake_fill)
    preview = asyncio.run(mod.trace_questionnaire(
        {"account_idx": 0, "vacancy_id": "12345678", "phase": "preview"}))
    assert preview["status"] == "preview" and preview["answers"] == answers
    assert state.sent == 0
    submitted = asyncio.run(mod.trace_questionnaire(
        {"account_idx": 0, "vacancy_id": "12345678", "phase": "submit_reviewed",
         "draft_id": preview["draft_id"]}))
    assert submitted["status"] == "sent" and state.sent == 1
    assert preview["draft_id"] not in mod._review_drafts


def test_targeted_questionnaire_stops_before_post_without_resume(monkeypatch):
    class Response:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def text(self):
            return '<div data-qa="task-question">Experience?</div><textarea name="task_1_text"></textarea>'

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def get(self, *args, **kwargs): return Response()
        def post(self, *args, **kwargs): raise AssertionError("questionnaire POST must not occur")

    monkeypatch.setattr(hh_apply, "aiohttp", SimpleNamespace(
        ClientSession=lambda **kwargs: Session(), ClientTimeout=lambda **kwargs: kwargs))
    monkeypatch.setattr(hh_apply, "_aio_egress_kwargs", lambda: ({}, {}))
    monkeypatch.setattr(hh_apply, "fetch_resume_text", lambda acc: "")
    monkeypatch.setattr(hh_apply.CONFIG, "llm_enabled", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_fill_questionnaire", True)
    monkeypatch.setattr(hh_apply.CONFIG, "llm_use_resume", True)
    stages = []
    result, info = asyncio.run(hh_apply.fill_and_submit_questionnaire(
        {"cookies": {}, "resume_hash": "r", "mode": "web"}, "12345678",
        trace=lambda stage, details: stages.append(stage), require_llm=True))
    assert (result, info) == ("error", {"error_code": "resume_unavailable"})
    assert "resume_context" in stages
    assert "submission_started" not in stages


def test_questionnaire_api_receives_saved_prompt_and_resume(monkeypatch):
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"task_1_text":"Готова обсудить опыт."}'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_make_openai_client", lambda profile: client)
    monkeypatch.setattr(llm, "_openai_available", True)
    monkeypatch.setattr(llm, "_check_questionnaire_quota", lambda key: True)
    monkeypatch.setattr(llm, "_increment_questionnaire_quota", lambda key: None)
    monkeypatch.setattr(llm, "_track_usage", lambda *args: None)
    monkeypatch.setattr(llm.CONFIG, "llm_profiles", [{"name": "P", "model": "fake", "api_key": "test"}])
    monkeypatch.setattr(llm.CONFIG, "llm_system_prompt", "Мой стиль: коротко и по делу.")
    monkeypatch.setattr(llm.CONFIG, "llm_applicant_gender", "female")
    events = []

    answers = llm.generate_llm_questionnaire_answers(
        [{"field": "task_1_text", "type": "textarea", "text": "Опыт?", "options": []}],
        resume_text="Общий опыт: 3 л. 0 мес.",
        trace=lambda stage, details: events.append((stage, details)))

    assert answers == {"task_1_text": "Готова обсудить опыт."}
    system = captured["messages"][0]["content"]
    assert "Мой стиль: коротко и по делу." in system
    assert "Общий опыт: 3 л. 0 мес." in system
    assert "В целом у меня есть опыт" in system
    assert "Пиши от первого лица в женском роде" in system
    assert any(stage == "llm_context" and details["resume_included"] for stage, details in events)


def test_history_exposes_questions_answers_and_result(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "TRACE_FILE", tmp_path / "trace.jsonl")
    monkeypatch.setattr(mod, "get_test_vacancy_stats", lambda: {"found": 3, "applied": 1})
    run_id = "a" * 32
    mod._record(run_id, "Tester", "12345678", "started", {"title": "QA", "origin": "automatic"})
    mod._record(run_id, "Tester", "12345678", "form_parsed", {"questions": [
        {"field": "task_1_text", "type": "textarea", "text": "Когда готовы выйти?"}]})
    mod._record(run_id, "Tester", "12345678", "llm_request",
                {"provider": "api", "model": "test-model"})
    mod._record(run_id, "Tester", "12345678", "answers_ready",
                {"answers": {"task_1_text": "Обсудим дату."}, "sources": {"task_1_text": "llm"}})
    mod._record(run_id, "Tester", "12345678", "answer_review_blocked",
                {"issues": [{"field": "task_1_text", "reasons": ["start_delay"]}]})
    mod._record(run_id, "Tester", "12345678", "result",
                {"status": "error", "info": {"error_code": "unsupported_claims"}})
    with mod.TRACE_FILE.open("a") as stream:
        stream.write('{broken\n')

    listing = asyncio.run(mod.questionnaire_history())
    assert listing["total"] == 1
    assert listing["stats"] == {"found": 3, "applied": 1}
    assert listing["items"][0]["blocked"] is True
    detail = asyncio.run(mod.questionnaire_history_detail(run_id))
    assert detail["questions"] == [{"field": "task_1_text", "text": "Когда готовы выйти?",
                                   "type": "textarea", "answer": "Обсудим дату.", "source": "llm"}]
    assert detail["llm"]["model"] == "test-model"
    assert detail["run"]["status"] == "error"
    assert detail["timeline"][-1]["stage"] == "result"


def test_ordinary_questionnaire_records_result(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "TRACE_FILE", tmp_path / "trace.jsonl")

    async def fake_impl(acc, vid, title, company, *, receipt_account, trace, require_llm, **kwargs):
        trace("form_parsed", {"questions": []})
        trace("submission_started", {})
        return "sent", {"receipt_confirmed": True}

    monkeypatch.setattr(hh_apply, "_fill_and_submit_questionnaire_impl", fake_impl)
    result = asyncio.run(hh_apply.fill_and_submit_questionnaire(
        {"name": "Tester", "resume_hash": "r"}, "12345678", "QA", "Company"))
    assert result == ("sent", {"receipt_confirmed": True})
    listing = asyncio.run(mod.questionnaire_history())
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["title"] == "QA" and item["company"] == "Company"
    assert item["status"] == "sent" and item["submitted"] is True


def test_history_counts_repeated_no_field_runs_by_vacancy(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "TRACE_FILE", tmp_path / "trace.jsonl")
    monkeypatch.setattr(mod, "get_test_vacancy_stats", lambda: {"found": 1, "applied": 0})
    for run_id in ("a" * 32, "b" * 32):
        mod._record(run_id, "Tester", "12345678", "started", {"origin": "automatic"})
        mod._record(run_id, "Tester", "12345678", "form_unrecognized", {})
        mod._record(run_id, "Tester", "12345678", "result", {"status": "test", "info": {}})
    listing = asyncio.run(mod.questionnaire_history())
    assert listing["outcomes"]["no_fields"] == 2
    assert listing["outcomes"]["no_field_vacancies"] == 1
    assert all(item["no_fields"] and not item["submitted"] for item in listing["items"])


def test_history_shows_post_run_visibility_diagnosis(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "TRACE_FILE", tmp_path / "trace.jsonl")
    monkeypatch.setattr(mod, "get_test_vacancy_stats", lambda: {"found": 1, "applied": 0})
    run_id = "c" * 32
    mod._record(run_id, "Tester", "12345678", "started", {})
    mod._record(run_id, "Tester", "12345678", "submission_started", {})
    mod._record(run_id, "Tester", "12345678", "result",
                {"status": "test", "info": {"error_code": "questionnaire_rejected"}})
    mod._record(run_id, "Tester", "12345678", "post_run_review",
                {"diagnosis": "resume_visibility_restricted", "source": "current_hh_form"})
    item = asyncio.run(mod.questionnaire_history())["items"][0]
    assert item["diagnosis"] == "resume_visibility_restricted"
    assert item["error_code"] == "questionnaire_rejected"


def test_test_vacancy_stats_count_unique_vacancies(monkeypatch):
    monkeypatch.setattr(storage, "_load_cache", lambda: None)
    monkeypatch.setattr(storage, "_cache_tests", {"11111": {}, "22222": {}, "33333": {}})
    monkeypatch.setattr(storage, "_cache_applied", {
        "A": {"11111": {}, "22222": {}},
        "B": {"11111": {}, "99999": {}},
    })
    assert storage.get_test_vacancy_stats() == {"found": 3, "applied": 2}

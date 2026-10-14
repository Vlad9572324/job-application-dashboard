"""A rejected questionnaire stays blocked after a worker restart."""

import json

from app import storage
from app.state import AccountState


def test_rejected_form_redirects_restore_failure_count(monkeypatch, tmp_path):
    trace = tmp_path / "questionnaire_trace.jsonl"
    rows = [
        {"account": "Tester", "vacancy_id": "12345678", "stage": "submission_response",
         "details": {"http_status": 302, "redirect_to_form": True}},
        {"account": "Tester", "vacancy_id": "12345678", "stage": "submission_response",
         "details": {"http_status": 302, "redirect_to_form": True}},
        {"account": "Other", "vacancy_id": "12345678", "stage": "submission_response",
         "details": {"http_status": 302, "redirect_to_form": True}},
        {"account": "Tester", "vacancy_id": "98765432", "stage": "submission_response",
         "details": {"http_status": 302, "redirect_to_form": False}},
    ]
    trace.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(storage, "QUESTIONNAIRE_TRACE_FILE", trace)
    state = AccountState({"name": "Tester", "short": "T", "color": "", "urls": []})
    assert state._test_failures == {"12345678": 2}

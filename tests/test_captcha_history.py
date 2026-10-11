"""Saved captcha attempts stay inspectable without touching an active challenge."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from urllib.parse import quote, unquote

import pytest
from fastapi.testclient import TestClient

from app import captcha_journal, captcha_solver


@pytest.fixture
def samples(tmp_data_dir):
    folder = tmp_data_dir / "captcha_samples"
    folder.mkdir()
    return folder


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def test_history_uses_exact_journal_answer_and_accepted_labels(samples):
    from app.captcha_history import list_attempts

    accepted = "20261003T110000_Слово-Два.png"
    rejected = "20261003T110356_local-rejected_клюёшь-лунную.png"
    (samples / accepted).write_bytes(b"accepted image")
    (samples / rejected).write_bytes(b"rejected image")
    _jsonl(samples / "labels.jsonl", [{"file": accepted, "answer": "Слово  Два!",
           "source": "telegram", "t": "2026-10-03T11:00:00+00:00"}])
    _jsonl(samples.parent / "captcha_events.jsonl", [{"event": "solve", "sample": rejected,
           "answer": "Клюёшь  лунную?", "path": "local", "ok": False, "reason": "isBot",
           "acc": "Account A", "t": "2026-10-03T11:03:56+00:00"}])

    failed, success = list_attempts()
    assert failed["sample"] == rejected
    assert failed["answer"] == "Клюёшь  лунную?"
    assert failed["source"] == "local" and failed["ok"] is False
    assert failed["reason"] == "isBot" and failed["account"] == "Account A"
    assert failed["legacy"] is False
    assert datetime.fromisoformat(failed["at"]) == datetime(2026, 10, 3, 11, 3, 56, tzinfo=timezone.utc)
    assert unquote(failed["image_url"]) == "/api/captcha/samples/" + rejected
    assert success["sample"] == accepted
    assert success["answer"] == "Слово  Два!"
    assert success["source"] == "telegram" and success["ok"] is True


def test_legacy_rejected_sample_is_explicitly_approximate(samples):
    from app.captcha_history import list_attempts

    name = "20261003T110356_local-rejected_клюёшь-лунную.png"
    (samples / name).write_bytes(b"legacy")
    item, = list_attempts()
    assert item["sample"] == name
    assert item["answer"] == "клюёшь лунную"
    assert item["source"] == "local"
    assert item["ok"] is False and item["legacy"] is True
    assert datetime.fromisoformat(item["at"]) == datetime(2026, 10, 3, 11, 3, 56, tzinfo=timezone.utc)


def test_rejected_samples_never_become_accepted_training_labels(tmp_data_dir):
    from app.captcha_history import list_attempts

    accepted = captcha_journal.save_sample(b"accepted", "Верный ответ", source="telegram")
    rejected = captcha_journal.save_sample(b"rejected", "Ошибка  Модели!",
                                           kind="local-rejected", source="local")
    assert isinstance(accepted, str) and isinstance(rejected, str)
    captcha_journal.record("solve", {"short": "A"}, sample=rejected, answer="Ошибка  Модели!",
                           path="local", ok=False, reason="isBot")
    folder = tmp_data_dir / "captcha_samples"
    labels = [json.loads(line) for line in (folder / "labels.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["file"] for row in labels] == [accepted]
    assert labels[0]["answer"] == "Верный ответ"
    attempts = {row["sample"]: row for row in list_attempts()}
    assert attempts[rejected]["answer"] == "Ошибка  Модели!"
    assert attempts[rejected]["ok"] is False
    assert (folder / rejected).read_bytes() == b"rejected"


def test_history_ignores_broken_metadata_and_unknown_samples(samples):
    from app.captcha_history import list_attempts

    name = "20261003T110356_local-rejected_слово-два.png"
    (samples / name).write_bytes(b"sample")
    bad_lines = '{not json}\nnull\n[]\n42\n'
    (samples / "labels.jsonl").write_text(bad_lines + json.dumps({
        "file": "missing.png", "answer": "must not appear"}) + "\n", encoding="utf-8")
    _jsonl(samples.parent / "captcha_events.jsonl", [
        {"event": "solve", "sample": "missing.png", "answer": "missing", "ok": True},
        {"event": "solve", "sample": "../outside.png", "answer": "outside", "ok": True},
        {"event": "challenge", "sample": name, "answer": "not a submitted answer", "ok": True},
    ])
    with (samples.parent / "captcha_events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(bad_lines)
    item, = list_attempts()
    assert item["sample"] == name and item["answer"] == "слово два"
    assert item["ok"] is False and item["legacy"] is True


def test_history_is_newest_first_and_limit_is_bounded(samples):
    from app.captcha_history import list_attempts

    start = datetime(2026, 10, 3, 11, tzinfo=timezone.utc)
    names = []
    for i in range(105):
        name = (start + timedelta(seconds=i)).strftime("%Y%m%dT%H%M%S") + "_local-rejected_guess.png"
        names.append(name)
        (samples / name).write_bytes(b"sample")
    assert [row["sample"] for row in list_attempts(limit=3)] == names[-1:-4:-1]
    assert len(list_attempts()) == 20
    assert len(list_attempts(limit=0)) == 1
    assert len(list_attempts(limit=-10)) == 1
    assert len(list_attempts(limit=1000)) == 100


@pytest.mark.parametrize("name", ["../secret.png", "subdir/secret.png", r"..\secret.png",
                                  "/tmp/secret.png", "labels.jsonl", "", "sample.png/.."])
def test_sample_paths_reject_traversal_and_non_images(samples, name):
    from app.captcha_history import sample_path

    with pytest.raises(ValueError):
        sample_path(name)


def test_history_and_image_paths_ignore_symlinks(samples):
    from app.captcha_history import list_attempts, sample_path

    outside = samples.parent / "outside.png"
    outside.write_bytes(b"not a captcha")
    link = samples / "20261003T110356_local-rejected_hidden.png"
    link.symlink_to(outside)
    with pytest.raises(ValueError):
        sample_path(link.name)
    assert list_attempts() == []


def test_history_routes_show_saved_bytes_without_fetching_or_submitting(samples, monkeypatch):
    from app import routes
    from app.captcha_history import sample_path

    name = "20261003T110356_local-rejected_клюёшь-лунную.png"
    payload = b"\x89PNG\r\n\x1a\narchived-image"
    (samples / name).write_bytes(payload)
    expected_files = {path.name: path.read_bytes() for path in samples.iterdir()}
    fetch, submit = Mock(), Mock()
    monkeypatch.setattr(captcha_solver, "fetch_captcha_image", fetch)
    monkeypatch.setattr(captcha_solver, "submit_captcha", submit)
    monkeypatch.setattr(routes, "_API_KEY", "history-test-key")
    # No context manager: do not start the live bot or background workers.
    client = TestClient(routes.app)
    headers = {"X-API-Key": "history-test-key"}

    result = client.get("/api/captcha/attempts", headers=headers)
    assert result.status_code == 200 and result.json()["ok"] is True
    item, = result.json()["attempts"]
    response = client.get(item["image_url"], headers=headers)
    assert response.status_code == 200 and response.content == payload
    assert response.headers["content-type"] == "image/png"
    assert "private" in response.headers["cache-control"]
    assert "no-store" in response.headers["cache-control"]
    assert sample_path(name) == (samples / name).resolve()
    assert sample_path(name).is_absolute()
    assert {path.name: path.read_bytes() for path in samples.iterdir()} == expected_files
    fetch.assert_not_called()
    submit.assert_not_called()


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "incorrect"}])
def test_history_and_saved_images_require_configured_api_key(samples, monkeypatch, headers):
    from app import routes

    name = "20261003T110356_local-rejected_слово.png"
    (samples / name).write_bytes(b"private sample")
    monkeypatch.setattr(routes, "_API_KEY", "history-test-key")
    client = TestClient(routes.app)
    for path in ("/api/captcha/attempts", "/api/captcha/samples/" + quote(name)):
        assert client.get(path, headers=headers).status_code == 401

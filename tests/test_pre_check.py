"""Тесты на _check_vacancy_before_apply — фикс H1 + retry distinction.

Защищает:
- H1: fail-closed на 401/403/non-200/parse-error/exception
- swarm-9 #10: 5xx → retry, 4xx → permanent skip
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.hh_apply as hh_apply
from app.hh_apply import _check_vacancy_before_apply


def _mock_resp(status=200, text="", json_data=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json = MagicMock(return_value=json_data) if json_data is not None else MagicMock(side_effect=ValueError())
    r.headers = {}
    return r


def _hh(resp):
    # Граница моков — HH (код ушёл с requests.get на HH.get)
    return SimpleNamespace(get=lambda *a, **kw: resp)


def _conn_fail(*a, **kw):
    raise ConnectionError("net")


def test_h1_401_returns_auth_error(monkeypatch):
    monkeypatch.setattr(hh_apply, "HH", _hh(_mock_resp(401)))
    result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is False
    assert result["reason"] == "auth_error"
    assert result["skip_reason"] == "auth"


def test_h1_403_login_page_returns_auth_error(monkeypatch):
    html = '<html>Войти в аккаунт</html>'
    monkeypatch.setattr(hh_apply, "HH", _hh(_mock_resp(200, html)))
    result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["reason"] == "auth_error"


def test_h1_429_returns_retry_not_skip(monkeypatch):
    """Rate-limit ≠ permanent skip."""
    monkeypatch.setattr(hh_apply.time, "sleep", lambda *_: None)
    monkeypatch.setattr(hh_apply, "HH", _hh(_mock_resp(429, "")))
    result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["skip_reason"] == "retry"


def test_h1_502_returns_retry_not_skip(monkeypatch):
    """5xx ≠ permanent skip. После _with_retry дёргает HTTP несколько раз — патчим sleep."""
    monkeypatch.setattr(hh_apply.time, "sleep", lambda *_: None)
    monkeypatch.setattr(hh_apply, "HH", _hh(_mock_resp(502, "")))
    result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["skip_reason"] == "retry"


def test_h1_404_returns_permanent_skip(monkeypatch):
    """4xx other → permanent skip."""
    monkeypatch.setattr(hh_apply, "HH", _hh(_mock_resp(404, "Not found")))
    result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["skip_reason"] == "skip"


def test_h1_bad_json_fails_closed(monkeypatch):
    """Невалидный JSON → не пропускаем (fail-closed)."""
    monkeypatch.setattr(hh_apply, "HH", _hh(_mock_resp(200, "<html>not json</html>")))
    result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is False
    assert result["reason"] == "bad_json"


def test_h1_exception_fails_closed(monkeypatch):
    """Network error → не пропускаем (fail-closed). ConnectionError ретраится → no sleep."""
    monkeypatch.setattr(hh_apply.time, "sleep", lambda *_: None)
    monkeypatch.setattr(hh_apply, "HH", SimpleNamespace(get=_conn_fail))
    result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is False
    assert result["skip_reason"] == "exception"


def test_h1_response_impossible_returns_not_ok(monkeypatch):
    json_data = {"responseStatus": {"responseImpossible": True, "responseImpossibleReason": "blacklist"}}
    monkeypatch.setattr(hh_apply, "HH", _hh(_mock_resp(200, '{"foo":1}', json_data)))
    result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is False

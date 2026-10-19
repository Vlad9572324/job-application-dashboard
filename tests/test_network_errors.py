import asyncio
import socket

import aiohttp
import pytest
import requests

from app import network_errors as ne
from app.manager import BotManager


@pytest.mark.parametrize("exc,expected", [
    (asyncio.TimeoutError(), "timeout"),
    (TimeoutError(), "timeout"),
    (requests.exceptions.ConnectTimeout(), "connect_timeout"),
    (requests.exceptions.ReadTimeout(), "read_timeout"),
    (requests.exceptions.ProxyError(), "proxy_error"),
    (requests.exceptions.SSLError(), "tls_error"),
    (requests.exceptions.ConnectionError(), "connection_error"),
    (socket.gaierror(-2, "Name or service not known"), "connection_error"),   # DNS — наш реальный случай
    (aiohttp.ServerDisconnectedError(), "connection_error"),
    (ValueError("boom"), None),
    (KeyError("x"), None),
])
def test_classify(exc, expected):
    assert ne.classify_network_exception(exc) == expected


def test_classifies_through_cause_chain():
    try:
        try:
            raise socket.gaierror(-2, "dns")
        except OSError as inner:
            raise aiohttp.ClientConnectorError(None, inner) from inner
    except aiohttp.ClientError as outer:
        assert ne.classify_network_exception(outer) == "connection_error"


def test_info_is_accepted_by_manager_as_recoverable_network_failure():
    info = ne.pre_dispatch_network_info(asyncio.TimeoutError(), "questionnaire_fetch_failed")
    assert info["dispatched"] is False
    assert BotManager._network_reason(info) == "timeout"


def test_non_network_error_has_no_recovery_info():
    assert ne.pre_dispatch_network_info(ValueError("parse"), "questionnaire_fetch_failed") is None


def test_questionnaire_network_failure_before_post_is_marked_recoverable(monkeypatch):
    """Сбой соединения при загрузке анкеты (до POST) — сетевой, а не безымянная ошибка."""
    from app import hh_apply
    monkeypatch.setattr(hh_apply, "_aio_egress_kwargs", lambda: (_ for _ in ()).throw(asyncio.TimeoutError()))
    acc = {"cookies": {"_xsrf": "x"}, "user_id": "net-test", "resume_hash": "r", "name": "N", "mode": "oauth"}
    result, info = asyncio.run(hh_apply.fill_and_submit_questionnaire(acc, "synthetic", "t", "c"))
    assert result == "error"
    assert BotManager._network_reason(info) == "timeout"
    assert info["error_code"] == "questionnaire_fetch_failed"


def test_questionnaire_parse_error_stays_unclassified(monkeypatch):
    from app import hh_apply
    monkeypatch.setattr(hh_apply, "_aio_egress_kwargs", lambda: (_ for _ in ()).throw(ValueError("parse")))
    acc = {"cookies": {"_xsrf": "x"}, "user_id": "net-test", "resume_hash": "r", "name": "N", "mode": "oauth"}
    result, info = asyncio.run(hh_apply.fill_and_submit_questionnaire(acc, "synthetic", "t", "c"))
    assert result == "error" and info == {"error_code": "questionnaire_fetch_failed"}
    assert BotManager._network_reason(info) is None

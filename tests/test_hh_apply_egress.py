"""Функциональные тесты egress-wiring'а aiohttp-путей app/hh_apply.py.

Security fix split-egress: ВСЕ HTTP-запросы к HH.ru обязаны идти через
HH_PROXY. Обе aiohttp.ClientSession в hh_apply.py (send_response_async и
fill_and_submit_questionnaire) берут (sess_kw, req_kw) из
hh_http._aio_egress_kwargs(); проверяем что kwargs реально доезжают:

- http(s)-прокси  → sess_kw пустые, каждый session.get/post получает proxy=...;
- прокси нет      → ни в конструкторе сессии, ни в запросах нет proxy/connector.

(socks-ветка с ProxyConnector здесь не гоняется: aiohttp_socks не установлен
в тестовом окружении; её fail-closed поведение покрыто отдельно.)

pytest-asyncio нет — корутины запускаем через asyncio.run() в отдельном
потоке (pytest-playwright держит session-scoped loop «running» в главном
потоке, прямой asyncio.run() в main-thread падает с RuntimeError).
"""
import asyncio
import concurrent.futures
import sys
import types
from datetime import datetime, timezone

import pytest

import app.hh_apply as hh_apply
from app import hh_http

PROXY_URL = "http://proxy.test:3128"


def test_socks5h_connector_uses_supported_scheme_and_remote_dns(monkeypatch):
    """aiohttp-socks не понимает socks5h URL: конвертируем в socks5 + rdns."""
    calls = []

    class FakeProxyConnector:
        @classmethod
        def from_url(cls, url, **kwargs):
            calls.append((url, kwargs))
            return "connector"

    monkeypatch.setitem(
        sys.modules, "aiohttp_socks",
        types.SimpleNamespace(ProxyConnector=FakeProxyConnector),
    )

    connector = hh_http._aio_session_connector(
        "socks5h://user:pass@proxy.test:1080", limit=7,
    )

    assert connector == "connector"
    assert calls == [("socks5://user:pass@proxy.test:1080", {"rdns": True, "limit": 7})]


def _run_coro(coro):
    """Запуск корутины через asyncio.run() в отдельном потоке — см. докстринг
    модуля. Исключения корутины пробрасываются через future.result()."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


# ── fixtures: прокси в hh_http singleton ─────────────────────────────────────

@pytest.fixture
def hh_proxy():
    """Выставить http-прокси runtime, вернуть как было (включая пустой)."""
    old = hh_http.proxy_url()
    hh_http.set_proxy(PROXY_URL)
    yield PROXY_URL
    hh_http.set_proxy(old)


@pytest.fixture
def hh_no_proxy():
    """Гарантированно прямой egress (HH_PROXY мог прийти из env)."""
    old = hh_http.proxy_url()
    hh_http.set_proxy("")
    yield
    hh_http.set_proxy(old)


# ── recorder-замена aiohttp.ClientSession ────────────────────────────────────

class _RecResp:
    """Стаб aiohttp-ответа: .status, .headers, async .text()."""

    def __init__(self, status=200, text=""):
        self.status = status
        self._text = text
        self.headers = {}

    async def text(self):
        return self._text


class _RecCallCtx:
    """async with session.get/post(...) as r: — отдаёт записанный стаб."""

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _RecordingSession:
    """Подмена ClientSession: запоминает kwargs конструктора и каждого
    get/post-вызова. Ответы — стабы из recorder'а."""

    def __init__(self, recorder, *args, **kwargs):
        self._recorder = recorder
        recorder.ctor_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, **kw):
        self._recorder.calls.append(("GET", url, kw))
        return _RecCallCtx(self._recorder.get_resp)

    def post(self, url, **kw):
        self._recorder.calls.append(("POST", url, kw))
        return _RecCallCtx(self._recorder.post_resp)


class _SessionRecorder:
    def __init__(self, *, get_resp=None, post_resp=None):
        self.ctor_kwargs = None
        self.calls = []  # list of (method, url, kwargs)
        self.get_resp = get_resp or _RecResp()
        self.post_resp = post_resp or _RecResp()


def _install_recorder(monkeypatch, **resp_kw):
    """Подменить aiohttp.ClientSession на recorder в модуле app.hh_apply."""
    rec = _SessionRecorder(**resp_kw)

    def _factory(*args, **kwargs):
        return _RecordingSession(rec, *args, **kwargs)

    monkeypatch.setattr(hh_apply.aiohttp, "ClientSession", _factory)
    return rec


def _make_acc():
    return {
        "name": "t",
        "cookies": {"_xsrf": "x", "hhtoken": "t"},
        "resume_hash": "rh",
        "letter": "hi",
    }


@pytest.fixture
def no_ai_letter(monkeypatch):
    """Заглушить generate_hh_ai_letter чтобы не ходить в реальный HH API."""
    async def _stub(*args, **kwargs):
        return ""
    monkeypatch.setattr(hh_apply, "generate_hh_ai_letter", _stub)


# ── send_response_async ──────────────────────────────────────────────────────

def test_send_response_async_http_proxy_in_request_kwargs(hh_proxy, no_ai_letter, monkeypatch):
    """http-прокси: sess_kw пустые, POST получает proxy=HH_PROXY."""
    rec = _install_recorder(
        monkeypatch,
        post_resp=_RecResp(200, '{"success":true,"topic_id":"1"}'),
    )

    result, info = _run_coro(hh_apply.send_response_async(_make_acc(), "123"))

    assert result == "sent" and info.get("topic_id") == "1"
    # конструктор сессии: без proxy/connector (http-ветка решает proxy= на запрос)
    assert "connector" not in rec.ctor_kwargs
    assert "proxy" not in rec.ctor_kwargs
    # единственный запрос — POST popup, и в нём прокси
    assert len(rec.calls) == 1
    method, url, kw = rec.calls[0]
    assert method == "POST"
    assert url.endswith("/applicant/vacancy_response/popup")
    assert kw.get("proxy") == PROXY_URL


def test_send_response_async_no_proxy_direct(hh_no_proxy, no_ai_letter, monkeypatch):
    """Без прокси: ни в конструкторе сессии, ни в запросе нет proxy/connector."""
    rec = _install_recorder(
        monkeypatch,
        post_resp=_RecResp(200, '{"success":true,"topic_id":"1"}'),
    )

    result, _info = _run_coro(hh_apply.send_response_async(_make_acc(), "123"))

    assert result == "sent"
    assert "connector" not in rec.ctor_kwargs
    assert "proxy" not in rec.ctor_kwargs
    assert len(rec.calls) == 1
    _method, _url, kw = rec.calls[0]
    assert "proxy" not in kw
    assert "connector" not in kw


# ── fill_and_submit_questionnaire ────────────────────────────────────────────

def test_questionnaire_form_get_passes_proxy(hh_proxy, monkeypatch):
    """GET формы опроса получает proxy=HH_PROXY. Ответ 403 → ("auth_error", {})
    до всякого POST — простой детерминированный срез через egress-ветку."""
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(403, ""))

    result, info = _run_coro(
        hh_apply.fill_and_submit_questionnaire(_make_acc(), "777", "Dev", "Comp")
    )

    assert (result, info) == ("auth_error", {})
    assert "connector" not in rec.ctor_kwargs
    assert "proxy" not in rec.ctor_kwargs
    # один GET формы; POST не успевает случиться (early-return на 403)
    assert len(rec.calls) == 1
    method, url, kw = rec.calls[0]
    assert method == "GET"
    assert "/applicant/vacancy_response?vacancyId=777" in url
    assert kw.get("proxy") == PROXY_URL


def test_questionnaire_no_proxy_direct(hh_no_proxy, monkeypatch):
    """Без прокси GET формы идёт напрямую: нигде нет proxy/connector."""
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(403, ""))

    result, _info = _run_coro(
        hh_apply.fill_and_submit_questionnaire(_make_acc(), "777", "Dev", "Comp")
    )

    assert result == "auth_error"
    assert "connector" not in rec.ctor_kwargs
    assert "proxy" not in rec.ctor_kwargs
    _method, _url, kw = rec.calls[0]
    assert "proxy" not in kw
    assert "connector" not in kw


@pytest.mark.parametrize('status,body,location,expected', [
    (302, '', '/account/login', 'auth_error'),
    (302, '', '/vacancy/777', 'unknown'),
    (200, '<html>validation failed</html>', '', 'unknown'),
    (200, '<html>"/account/login"</html>', '', 'auth_error'),
    (200, '{"success":true,"topic_id":"1"}', '', 'sent'),
    (302, '', '/?withoutTest=no', 'test'),
])
def test_questionnaire_requires_confirmed_success(hh_no_proxy, monkeypatch, status, body, location, expected):
    from app import apply_confirmation
    monkeypatch.setattr(apply_confirmation, 'confirm_application_receipt', lambda *args: None)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', False)
    response = _RecResp(status, body)
    response.headers = {'location': location}
    rec = _install_recorder(monkeypatch,
        get_resp=_RecResp(200, '<textarea name="task_1_text"></textarea>'),
        post_resp=response)
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(_make_acc(), '777'))
    assert result == expected
    if location == '/?withoutTest=no':
        assert info == {"error_code": "questionnaire_rejected", "http_status": 302}
    assert [call[0] for call in rec.calls] == ['GET', 'POST']


def test_questionnaire_already_responded_page_does_not_post(hh_no_proxy, monkeypatch):
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', False)
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(
        200, '<form name="vacancy_response"><div data-qa="already-responded-text">'
             'Already responded</div></form>'))
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(_make_acc(), '777'))
    assert (result, info) == ('already', {'reason': 'hh_already_responded'})
    assert [call[0] for call in rec.calls] == ['GET']


def test_questionnaire_hidden_resume_warning_does_not_post(hh_no_proxy, monkeypatch):
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(
        200, '<form name="vacancy_response">'
             '<div data-qa="hidden-resume-warning">Change resume visibility</div>'
             '<div data-qa="task-question">Опыт?</div>'
             '<textarea name="task_1_text"></textarea></form>'))
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(_make_acc(), '777'))
    assert (result, info) == ('error', {'error_code': 'resume_visibility_restricted'})
    assert [call[0] for call in rec.calls] == ['GET']


def test_questionnaire_resolves_choice_label_before_preview(hh_no_proxy, monkeypatch):
    html = ('<div data-qa="task-question">Готовы?</div>'
            '<label><input type="radio" name="task_1" value="101">Да</label>'
            '<label><input type="radio" name="task_1" value="102">Нет</label>')
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(200, html))
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_enabled', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_use_resume', False)
    monkeypatch.setattr(hh_apply, 'generate_llm_questionnaire_answers',
                        lambda *args, **kwargs: {'task_1': 'Нет'})
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(
        _make_acc(), '777', preview_only=True))
    assert result == 'preview' and info['answers']['task_1'] == '102'
    assert [call[0] for call in rec.calls] == ['GET']


def test_questionnaire_does_not_submit_unresolved_choice(hh_no_proxy, monkeypatch):
    html = ('<div data-qa="task-question">Готовы?</div>'
            '<label><input type="radio" name="task_1" value="101">Да</label>'
            '<label><input type="radio" name="task_1" value="102">Нет</label>')
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(200, html))
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_enabled', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_use_resume', False)
    monkeypatch.setattr(hh_apply, 'generate_llm_questionnaire_answers',
                        lambda *args, **kwargs: {'task_1': 'Возможно'})
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(_make_acc(), '777'))
    assert (result, info) == ('error', {'error_code': 'llm_answers_rejected'})
    assert [call[0] for call in rec.calls] == ['GET']


def test_questionnaire_selects_custom_option_for_custom_text(hh_no_proxy, monkeypatch):
    html = ('<div data-qa="task-question">Другой инструмент?</div>'
            '<label><input type="checkbox" name="task_1" value="101">Java</label>'
            '<label><input type="checkbox" name="task_1" value="open">Свой вариант</label>'
            '<input type="text" name="task_1_text">')
    _install_recorder(monkeypatch, get_resp=_RecResp(200, html))
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_enabled', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_use_resume', False)
    monkeypatch.setattr(hh_apply, 'generate_llm_questionnaire_answers',
                        lambda *args, **kwargs: {'task_1': '', 'task_1_text': 'Python'})
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(
        _make_acc(), '777', preview_only=True))
    assert result == 'preview'
    assert info['answers']['task_1'] == 'open'
    assert info['answers']['task_1_text'] == 'Python'


def test_questionnaire_omits_custom_text_for_regular_choice(hh_no_proxy, monkeypatch):
    html = ('<div data-qa="task-question">Инструмент?</div>'
            '<label><input type="checkbox" name="task_1" value="101">Java</label>'
            '<label><input type="checkbox" name="task_1" value="open">Свой вариант</label>'
            '<input type="text" name="task_1_text">')
    _install_recorder(monkeypatch, get_resp=_RecResp(200, html))
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_enabled', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_use_resume', False)
    monkeypatch.setattr(hh_apply, 'generate_llm_questionnaire_answers',
                        lambda *args, **kwargs: {'task_1': 'Java'})
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(
        _make_acc(), '777', preview_only=True))
    assert result == 'preview'
    assert info['answers'] == {'task_1': '101'}
    reviewed, reviewed_info = _run_coro(hh_apply.fill_and_submit_questionnaire(
        _make_acc(), '777', preview_only=True,
        approved_answers=info['answers'], expected_questions=info['questions']))
    assert reviewed == 'preview' and reviewed_info['answers'] == info['answers']


def test_questionnaire_does_not_fallback_to_templates_when_llm_is_empty(hh_no_proxy, monkeypatch):
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(
        200, '<div data-qa="task-question">Опыт?</div><textarea name="task_1_text"></textarea>'))
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_enabled', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', True)
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_use_resume', False)
    monkeypatch.setattr(hh_apply, 'generate_llm_questionnaire_answers', lambda *args, **kwargs: {})
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(_make_acc(), '777'))
    assert (result, info) == ('error', {'error_code': 'llm_no_answer'})
    assert [call[0] for call in rec.calls] == ['GET']


@pytest.mark.parametrize('status,body,location', [
    (302, '', '/vacancy/777'),
    (303, '', '/vacancy/777'),
    (200, '<html>ambiguous</html>', ''),
    (503, '', ''),
])
def test_questionnaire_ambiguous_response_uses_one_fresh_receipt(
        hh_no_proxy, monkeypatch, status, body, location):
    from app import apply_confirmation
    from unittest.mock import Mock
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', False)
    confirm = Mock(return_value={'negotiation_id': 'topic1', 'receipt_confirmed': True,
                                'receipt_created_at': datetime.now(timezone.utc).isoformat()})
    monkeypatch.setattr(apply_confirmation, 'confirm_application_receipt', confirm)
    response = _RecResp(status, body)
    response.headers = {'location': location}
    rec = _install_recorder(monkeypatch,
        get_resp=_RecResp(200, '<textarea name="task_1_text"></textarea>'), post_resp=response)
    original = {**_make_acc(), '_pinned_resume_id': 'pinned'}
    ephemeral = {**original, 'cookies': {'hhtoken': 'temporary'}}
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(
        ephemeral, '777', receipt_account=original))
    assert result == 'sent' and info['receipt_confirmed'] is True
    confirm.assert_called_once_with(original, '777', 'pinned')
    assert [call[0] for call in rec.calls] == ['GET', 'POST']
    fields = {entry[0]['name']: entry[2] for entry in rec.calls[1][2]['data']._fields}
    assert fields['resume_hash'] == 'pinned'


@pytest.mark.parametrize('confirmed', [False, True])
def test_questionnaire_post_timeout_reconciles_without_second_post(hh_no_proxy, monkeypatch, confirmed):
    from app import apply_confirmation
    from unittest.mock import Mock
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', False)
    receipt = {'negotiation_id': 'topic1', 'receipt_confirmed': True,
               'receipt_created_at': datetime.now(timezone.utc).isoformat()} if confirmed else None
    confirm = Mock(return_value=receipt)
    monkeypatch.setattr(apply_confirmation, 'confirm_application_receipt', confirm)
    rec = _install_recorder(monkeypatch,
        get_resp=_RecResp(200, '<textarea name="task_1_text"></textarea>'))

    def timeout(self, url, **kwargs):
        self._recorder.calls.append(('POST', url, kwargs))
        raise TimeoutError('synthetic')

    monkeypatch.setattr(_RecordingSession, 'post', timeout)
    result, _ = _run_coro(hh_apply.fill_and_submit_questionnaire(_make_acc(), '777'))
    assert result == ('sent' if confirmed else 'unknown')
    assert confirm.call_count == 1
    assert [call[0] for call in rec.calls] == ['GET', 'POST']


def test_questionnaire_cancel_before_post_does_not_confirm(hh_no_proxy, monkeypatch):
    from app import apply_confirmation
    from unittest.mock import Mock
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', False)
    confirm = Mock()
    monkeypatch.setattr(apply_confirmation, 'confirm_application_receipt', confirm)
    rec = _install_recorder(monkeypatch,
        get_resp=_RecResp(200, '<textarea name="task_1_text"></textarea>'))
    acc = {**_make_acc(), '_mutation_guard': lambda: False}
    result, _ = _run_coro(hh_apply.fill_and_submit_questionnaire(acc, '777'))
    assert result == 'cancelled'
    confirm.assert_not_called()
    assert [call[0] for call in rec.calls] == ['GET']


@pytest.mark.parametrize('created', [None, '2020-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00'])
def test_old_or_undated_receipt_is_already_not_new_sent(hh_no_proxy, monkeypatch, created):
    from app import apply_confirmation
    from unittest.mock import Mock
    monkeypatch.setattr(hh_apply.CONFIG, 'llm_fill_questionnaire', False)
    receipt = {'negotiation_id': 'topic1', 'receipt_confirmed': True}
    if created is not None:
        receipt['receipt_created_at'] = created
    monkeypatch.setattr(apply_confirmation, 'confirm_application_receipt', Mock(return_value=receipt))
    response = _RecResp(302, '')
    response.headers = {'location': '/vacancy/777'}
    rec = _install_recorder(monkeypatch,
        get_resp=_RecResp(200, '<textarea name="task_1_text"></textarea>'), post_resp=response)
    result, _ = _run_coro(hh_apply.fill_and_submit_questionnaire(_make_acc(), '777'))
    assert result == 'already'
    assert [call[0] for call in rec.calls] == ['GET', 'POST']


def test_questionnaire_form_get_exception_is_not_unknown_mutation(hh_no_proxy, monkeypatch):
    from app import apply_confirmation
    from unittest.mock import Mock
    confirm = Mock()
    monkeypatch.setattr(apply_confirmation, 'confirm_application_receipt', confirm)
    _install_recorder(monkeypatch)
    def fail_get(self, url, **kwargs):
        raise TimeoutError('synthetic')
    monkeypatch.setattr(_RecordingSession, 'get', fail_get)
    result, info = _run_coro(hh_apply.fill_and_submit_questionnaire(_make_acc(), '777'))
    assert result == 'error' and info['error_code'] == 'questionnaire_fetch_failed'
    confirm.assert_not_called()

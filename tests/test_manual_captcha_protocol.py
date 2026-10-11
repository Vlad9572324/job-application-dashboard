"""Match HH's human form protocol, without OCR, live requests or auto-resume.

Primary source inspected 2026-09-28:
https://i.hh.ru/build/AccountCaptcha-route.1fe8dc3dc321034b.js
SHA256: 62e1ac45341a6b386114339435b3a2be032a072549d699e73b5ff5c2dc65a7f5
Its form navigates to backurl on XHR HTTP 302, without inspecting Location.
"""
from html import escape
import json
from unittest.mock import Mock
import pytest
from app import captcha_solver as solver


SUCCESS = 'https://hh.ru/?manual_captcha_return=test'
FAIL = 'https://hh.ru/account/captcha?state=test'


@pytest.mark.parametrize('status,location,body,expected', [
    (302, '', None, True),
    (302, '', {'hhcaptcha': {'isBot': True}}, False),
    (302, '', {'recaptcha': {'isBot': True}}, False),
    (200, '', None, False),
    (303, '', None, False),
    (302, 'https://ekaterinburg.hh.ru/account/captcha?state=test', None, False),
    (302, '/account/login', None, False),
    (302, 'https://evil.example/', None, False),
    (403, '', None, False),
    (429, '', None, False),
])
def test_only_documented_manual_completion_is_success(status, location, body, expected):
    session = Mock()
    session.cookies.get.return_value = 'test'
    response = Mock(status_code=status, headers={'Location': location}, json=lambda: body)
    session.post.return_value = response
    assert solver.submit_captcha(session, 'human', 'key', 'state', SUCCESS, FAIL,
                                 require_confirmation=True)[0] is expected
    session.post.assert_called_once()


def test_xhr_success_requires_safe_distinct_return_addresses():
    session = Mock()
    session.post.return_value = Mock(status_code=302, headers={}, json=lambda: None)
    for back, fail in [(SUCCESS, SUCCESS), ('https://evil.example/', FAIL), (SUCCESS, None)]:
        assert not solver.submit_captcha(session, 'human', 'key', 'state', back, fail,
                                         require_confirmation=True)[0]


def test_requests_stay_on_region_selected_by_captcha_page(monkeypatch):
    region = 'https://ekaterinburg.hh.ru'
    session = Mock()
    session.proxies = {}
    session.cookies.get.return_value = 'test'
    session.get.side_effect = [Mock(status_code=200, url=region + '/account/captcha?state=test'),
                               Mock(status_code=200, content=b'png')]
    session.post.side_effect = [Mock(status_code=200, json=lambda: {'key': 'test'}),
                                Mock(status_code=302, headers={}, json=lambda: None)]
    monkeypatch.setattr(solver, '_make_session', lambda: session)
    monkeypatch.setattr(solver, 'egress_proxies', lambda: {})
    solver.fetch_captcha_image({}, FAIL)
    assert solver.submit_captcha(session, 'human', 'test', 'test', SUCCESS, FAIL,
                                  require_confirmation=True)[0]
    assert session.post.call_args_list[0].args[0] == region + '/captcha'
    assert session.post.call_args_list[1].args[0] == region + '/account/captcha'
    assert session.get.call_args_list[1].args[0] == region + '/captcha/picture'
    assert session.post.call_args_list[1].kwargs['headers']['Referer'].startswith(region + '/')


def test_non_hh_origin_cannot_be_used():
    session = Mock(hh_captcha_origin='https://evil.example')
    assert solver._captcha_origin(session) == 'https://hh.ru'


@pytest.mark.parametrize('bootstrap,expected_state', [
    ({'hhcaptcha': {'captchaState': 'replacement+state&opaque'},
      'recaptcha': {'captchaState': 'unused-state'}}, 'replacement+state&opaque'),
    ({'hhcaptcha': {'captchaState': ''},
      'recaptcha': {'captchaState': 'recaptcha-state'}}, 'recaptcha-state'),
    ({'hhcaptcha': {'captchaState': {'invalid': 'object'}},
      'recaptcha': {'captchaState': 'recaptcha-state'}}, 'recaptcha-state'),
])
def test_answer_uses_server_page_state_instead_of_replaced_url_state(
        monkeypatch, bootstrap, expected_state):
    """The page's current state must stay paired with the fetched image/key."""
    session = Mock()
    session.proxies = {}
    session.cookies.get.return_value = 'xsrf-test'
    page = '<template id="HH-Lux-InitialState">' + escape(json.dumps(bootstrap)) + '</template>'
    session.get.side_effect = [Mock(status_code=200, url=FAIL, text=page),
                               Mock(status_code=200, content=b'png')]
    session.post.side_effect = [Mock(status_code=200, json=lambda: {'key': 'fresh-key'}),
                               Mock(status_code=302, headers={}, json=lambda: None)]
    monkeypatch.setattr(solver, '_make_session', lambda: session)
    monkeypatch.setattr(solver, 'egress_proxies', lambda: {})

    fetched, key, image, state, _ = solver.fetch_captcha_image({}, FAIL)
    assert fetched is session and key == 'fresh-key' and image == b'png'
    assert state == expected_state
    assert solver.submit_captcha(session, 'human', key, state, SUCCESS, FAIL,
                                 require_confirmation=True) == (True, '')
    assert session.post.call_args.kwargs['params']['captchaState'] == expected_state
    assert session.post.call_args.kwargs['params']['captchaKey'] == key


@pytest.mark.parametrize('page', [
    '',
    '<html>No bootstrap</html>',
    '<template id="HH-Lux-InitialState">not-json</template>',
    '<template id="HH-Lux-InitialState">[]</template>',
    '<template id="HH-Lux-InitialState">{"hhcaptcha":null,"recaptcha":[]}</template>',
    '<template id="HH-Lux-InitialState">{"hhcaptcha":{"captchaState":false},'
    '"recaptcha":{"captchaState":""}}</template>',
])
def test_missing_or_malformed_page_state_preserves_original_url_state(monkeypatch, page):
    session = Mock()
    session.proxies = {}
    session.get.return_value = Mock(status_code=200, url=FAIL, text=page)
    monkeypatch.setattr(solver, '_make_session', lambda: session)
    monkeypatch.setattr(solver, 'egress_proxies', lambda: {})

    fetched, state, backurl = solver._prime_session(FAIL)
    assert fetched is session and state == 'test' and backurl == 'https://hh.ru/'
    session.post.assert_not_called()

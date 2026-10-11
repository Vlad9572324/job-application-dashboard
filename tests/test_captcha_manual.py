import asyncio
from unittest.mock import Mock
import pytest
from app import captcha, oauth
from app.hh_apply import classify_apply_response


PAYLOAD = {'errors': [{'type': 'captcha_required', 'value': 'captcha_required',
    'captcha_url': 'https://hh.ru/account/captcha?state=synthetic-state'}]}


@pytest.mark.parametrize('status', [400, 403])
def test_oauth_preserves_challenge_and_stops_guard(monkeypatch, status):
    acc = {'user_id': 'synthetic-owner', 'resume_hash': 'resume', '_on_challenge': Mock()}
    monkeypatch.setattr(oauth, '_obtain_oauth_token', lambda acc: 'synthetic')
    response = Mock(status_code=status)
    response.json.return_value = PAYLOAD
    monkeypatch.setattr(oauth.HH, 'post', Mock(return_value=response))
    result, info = oauth._oauth_apply(acc, '123')
    assert result == 'challenge'
    assert 'synthetic-state' not in str(info)
    acc['_on_challenge'].assert_called_once()
    record = captcha.current(acc)
    assert record['captcha_url'] == PAYLOAD['errors'][0]['captcha_url']
    assert 'backurl=https%3A%2F%2Fhh.ru%2F' in captcha.browser_url(record)
    with pytest.raises(ValueError):
        captcha.clear(acc, 'stale')
    assert captcha.current(acc)
    captcha.clear(acc, record['id'])
    assert not captcha.current(acc)


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://hh.ru.evil.test/captcha',
    'https://user:password@hh.ru/captcha', 'https://hh.ru:123/captcha',
    'http://hh.ru/captcha', '//hh.ru/captcha', 'https://hh.ru\\@evil.test/captcha'])
def test_unsafe_url_rejected(url):
    assert captcha.safe_url(url) == ''


@pytest.mark.parametrize('status', [401, 429, 500, 502])
def test_other_protections_not_reclassified(status):
    assert captcha.parse(status, PAYLOAD) is None


def test_web_classifies_before_auth():
    import json
    assert classify_apply_response(403, json.dumps(PAYLOAD))[0] == 'challenge'


def test_parser_checks_all_errors():
    assert captcha.parse(403, {'errors': [{}, {'value': 'captcha_required'}]})
    assert captcha.parse(403, {'errors': None}) is None


def test_missing_link_is_not_homepage_and_can_be_recovered():
    acc = {'user_id': 'synthetic-recovery'}
    captcha.hold(acc, {})
    old = captcha.current(acc)
    assert captcha.browser_url(old) == ''
    captcha.capture(acc, 403, PAYLOAD)
    new = captcha.current(acc)
    assert new['id'] != old['id']
    assert new['captcha_url']


def test_no_server_proof_without_explicit_confirmation(monkeypatch):
    from app.routes.accounts import api_account_captcha_continue
    class Request:
        async def json(self): return {'confirmed': False}
    assert asyncio.run(api_account_captcha_continue(0, Request()))['ok'] is False


def test_read_only_probe_preserves_pause_and_throttles(monkeypatch):
    import threading
    from types import SimpleNamespace
    from app.routes import accounts
    state = SimpleNamespace(acc={'user_id': 'probe'}, _state_lock=threading.RLock(),
                            _deleted=False, paused=True, paused_reason='challenge')
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: state)
    monkeypatch.setattr(oauth, '_oauth_headers', lambda acc: {'Authorization': 'synthetic'})
    monkeypatch.setattr(oauth, '_token_key', lambda acc: 'synthetic')
    get = Mock(return_value=Mock(status_code=200, json=lambda: {}))
    monkeypatch.setattr(accounts.HH, 'get', get)
    result = asyncio.run(accounts.api_account_captcha_refresh(0))
    assert result['ok'] and result['probe_status'] == 200
    assert not result['challenge_received'] and not result['challenge_replaced']
    assert state.paused and state.paused_reason == 'challenge'
    assert not asyncio.run(accounts.api_account_captcha_refresh(0))['ok']
    get.assert_called_once()
    assert get.call_args.args == ('https://api.hh.ru/me',)


def test_probe_response_cannot_overwrite_newer_challenge(monkeypatch):
    import threading
    from types import SimpleNamespace
    from app.routes import accounts
    acc = {'user_id': 'probe-race'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=old'})
    state = SimpleNamespace(acc=acc, _state_lock=threading.RLock(),
                            _deleted=False, paused=True, paused_reason='challenge')
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: state)
    monkeypatch.setattr(oauth, '_oauth_headers', lambda acc: {'Authorization': 'synthetic'})
    monkeypatch.setattr(oauth, '_token_key', lambda acc: 'synthetic')
    def response(*args, **kwargs):
        captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=newest'})
        return Mock(status_code=403, json=lambda: PAYLOAD)
    monkeypatch.setattr(accounts.HH, 'get', response)
    assert not asyncio.run(accounts.api_account_captcha_refresh(0))['ok']
    assert captcha.current(acc)['captcha_url'].endswith('state=newest')
    assert state.paused


def test_oauth_batch_has_immediate_challenge_break():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('app/manager.py').read_text())
    conditions = [n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and "result[0] == 'challenge'" in ast.unparse(n.test)]
    assert conditions and any(isinstance(n, ast.Break) for n in ast.walk(conditions[0]))


def _continue_env(monkeypatch, **flags):
    import threading
    from types import SimpleNamespace
    from app.routes import accounts
    base = dict(acc={'user_id': 'orphan'}, _state_lock=threading.RLock(), _deleted=False,
                paused=False, paused_reason='', pending_apply=None, pending_applies=[],
                hard_stopped=False, limit_exceeded=False, cookies_expired=False,
                consecutive_errors=3, short='O')
    base.update(flags)
    state = SimpleNamespace(**base)
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: state)
    monkeypatch.setattr(accounts.bot, '_persist_pauses', lambda wait=False: None)
    captcha.hold(state.acc, {'captcha_url': 'https://hh.ru/account/captcha?state=s'})
    cid = captcha.current(state.acc)['id']

    class Req:
        async def json(self): return {'confirmed': True, 'id': cid}
    return accounts, state, Req(), cid


def test_confirm_clears_challenge_that_exists_only_in_file(monkeypatch):
    """Капча создана вне бота (аккаунт в памяти не на паузе): подтверждение человека её снимает."""
    accounts, state, req, cid = _continue_env(monkeypatch)
    result = asyncio.run(accounts.api_account_captcha_continue(0, req))
    assert result['ok'] is True
    assert not captcha.current(state.acc)
    assert state.paused is False and state.consecutive_errors == 0


def test_confirm_still_refused_under_other_protective_pause(monkeypatch):
    accounts, state, req, cid = _continue_env(monkeypatch, paused=True, paused_reason='limit')
    result = asyncio.run(accounts.api_account_captcha_continue(0, req))
    assert result['ok'] is False
    assert captcha.current(state.acc)['id'] == cid
    captcha.clear(state.acc, cid)

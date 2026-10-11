from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest

from app import captcha


def test_new_server_state_keeps_challenge_identity_and_manual_ownership():
    acc = {'user_id': 'state-update'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=old&backurl=https%3A%2F%2Fhh.ru%2F'})
    original = captcha.current(acc)
    captcha.claim_manual(acc, original['id'])
    assert captcha.update_challenge_state(acc, original['id'], 'new+/=&value')
    current = captcha.current(acc)
    assert current['id'] == original['id']
    assert current['created_at'] == original['created_at']
    assert current['manual_only'] is True
    assert parse_qs(urlsplit(current['captcha_url']).query) == {
        'state': ['new+/=&value'], 'backurl': ['https://hh.ru/']}
    assert not captcha.update_challenge_state(acc, original['id'], 'new+/=&value')


def test_old_or_invalid_result_cannot_update_replacement_challenge():
    acc = {'user_id': 'state-update'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=old'})
    original = captcha.current(acc)
    for value in (None, {}, '', ' ', 'x' * 8193):
        assert not captcha.update_challenge_state(acc, original['id'], value)
    assert not captcha.update_challenge_state(acc, 'stale-id', 'new')
    assert captcha.current(acc) == original


def test_stale_retry_cannot_change_replacement_challenge():
    acc = {'user_id': 'retry-state'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=old'})
    old_id = captcha.current(acc)['id']
    captcha.clear(acc, old_id)
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new'})
    current = captcha.current(acc)
    captcha.claim_manual(acc, current['id'])
    assert not captcha.set_local_retry(acc, old_id, 60, 'http_429', 3)
    assert not captcha.release_manual(acc, old_id)
    assert captcha.current(acc)['manual_only']
    assert 'local_retry_at' not in captcha.current(acc)


def _owned_challenge(url):
    acc = {'user_id': 'issued-state', 'paused': True, 'paused_reason': 'challenge',
           '_on_challenge': Mock()}
    captcha.hold(acc, {'captcha_url': url})
    cid = captcha.current(acc)['id']
    captcha.claim_manual(acc, cid, auto_retry_after=120)
    captcha.set_local_retry(acc, cid, 60, 'isBot', 8)
    return acc, captcha.current(acc)


def test_newly_issued_state_replaces_identity_and_invalidates_old_gui_result():
    acc, old = _owned_challenge('https://hh.ru/account/captcha?state=old')
    fresh_url = 'https://hh.ru/account/captcha?state=new%2Bopaque%26value'
    payload = {'errors': [{'type': 'captcha_required', 'captcha_url': fresh_url}]}

    assert captcha.capture(acc, 403, payload)
    current = captcha.current(acc)
    assert current['id'] != old['id']
    assert current['created_at'] != old['created_at']
    assert current['captcha_url'] == fresh_url
    assert current['fallback_url'] == ''
    assert not any(field in current for field in (
        'manual_only', 'auto_retry_until', 'local_retry_at', 'local_retry_reason', 'local_attempts'))
    assert captcha.active(acc)
    assert acc['paused'] is True and acc['paused_reason'] == 'challenge'
    assert acc['_on_challenge'].call_count == 2
    with pytest.raises(ValueError, match='Challenge changed'):
        captcha.clear(acc, old['id'])
    assert not captcha.update_challenge_state(acc, old['id'], 'late-response')
    assert not captcha.set_local_retry(acc, old['id'], 60, 'isBot', 9)
    assert not captcha.release_manual(acc, old['id'])
    assert captcha.current(acc) == current


@pytest.mark.parametrize('new_url', [
    'https://hh.ru/account/captcha?state=a%2Bb%26c&backurl=https%3A%2F%2Fhh.ru%2Fnew',
    'https://hh.ru/account/captcha?backurl=https://hh.ru/new&state=a%2bb%26c',
    'https://ekaterinburg.hh.ru/account/captcha?state=a%2Bb%26c',
])
def test_same_decoded_state_preserves_manual_ownership_and_retry_metadata(new_url):
    acc, old = _owned_challenge('https://hh.ru/account/captcha?state=a%2Bb%26c&backurl=https://hh.ru/')
    captcha.hold(acc, {'captcha_url': new_url})
    assert captcha.current(acc) == old


@pytest.mark.parametrize('details', [
    {},
    {'captcha_url': ''},
    {'captcha_url': 'https://hh.ru/account/captcha'},
    {'captcha_url': 'https://hh.ru/account/captcha?state='},
    {'captcha_url': 'https://hh.ru/account/captcha?state=%20'},
    {'captcha_url': 'https://evil.example/account/captcha?state=new'},
    {'fallback_url': 'https://hh.ru/'},
])
def test_missing_or_invalid_fresh_state_does_not_downgrade_usable_challenge(details):
    acc, old = _owned_challenge('https://hh.ru/account/captcha?state=old')
    captcha.hold(acc, details)
    assert captcha.current(acc) == old


def test_new_direct_state_replaces_existing_fallback_challenge():
    acc = {'user_id': 'fallback-state'}
    captcha.hold(acc, {'fallback_url': 'https://hh.ru/account/captcha?state=old'})
    old = captcha.current(acc)
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new'})
    current = captcha.current(acc)
    assert current['id'] != old['id']
    assert current['captcha_url'] == 'https://hh.ru/account/captcha?state=new'
    assert current['fallback_url'] == ''

"""Retain the original rejected apply target without publishing request secrets."""
from unittest.mock import Mock

import pytest

from app import captcha, captcha_journal, oauth


URL = 'https://hh.ru/account/captcha?state=PRIVATE_STATE'
CONTEXT = {'operation': 'apply', 'vacancy_id': '123456', 'resume_id': 'resume_test'}


def payload(url=URL):
    return {'errors': [{'type': 'captcha_required', 'captcha_url': url}]}


@pytest.mark.parametrize('status', [400, 403])
def test_oauth_apply_captures_original_vacancy_and_resume_without_logging_them(monkeypatch, status):
    acc = {'user_id': 'context-account', 'resume_hash': CONTEXT['resume_id'], '_on_challenge': Mock()}
    monkeypatch.setattr(oauth, '_obtain_oauth_token', lambda acc: 'PRIVATE_TOKEN')
    monkeypatch.setattr(oauth, '_account_headers', lambda acc, token: {'Authorization': token})
    post = Mock(return_value=Mock(status_code=status, json=lambda: payload()))
    monkeypatch.setattr(oauth.HH, 'post', post)
    journal = Mock()
    monkeypatch.setattr(captcha_journal, 'record', journal)

    result, info = oauth._oauth_apply(acc, CONTEXT['vacancy_id'], 'PRIVATE_LETTER')
    assert result == 'challenge' and info == {'error_type': 'captcha_required'}
    current = captcha.current(acc)
    assert current['request_context'] == CONTEXT
    assert captcha.active(acc)
    acc['_on_challenge'].assert_called_once()
    post.assert_called_once()
    assert post.call_args.kwargs['data']['vacancy_id'] == CONTEXT['vacancy_id']
    assert post.call_args.kwargs['data']['resume_id'] == CONTEXT['resume_id']
    assert journal.call_args.kwargs['source'] == 'oauth_apply'
    assert 'request_context' not in journal.call_args.kwargs
    assert 'PRIVATE' not in str(journal.call_args)
    assert 'PRIVATE_TOKEN' not in str(current) and 'PRIVATE_LETTER' not in str(current)


def test_only_whitelisted_context_fields_are_stored_and_error_details_stay_unchanged():
    acc = {'user_id': 'context-account'}
    context = {**CONTEXT, 'access_token': 'PRIVATE_TOKEN', 'cookies': {'secret': 'PRIVATE_COOKIE'},
               'captcha_state': 'PRIVATE_OTHER_STATE', 'headers': {'Authorization': 'PRIVATE_AUTH'}}
    details = captcha.capture(acc, 403, payload(), 'caller', request_context=context)
    assert captcha.current(acc)['request_context'] == CONTEXT
    assert details == {**captcha.parse(403, payload()), 'source': 'caller'}
    assert 'request_context' not in details
    assert 'PRIVATE_TOKEN' not in captcha.PATH.read_text()
    assert 'PRIVATE_COOKIE' not in captcha.PATH.read_text()


@pytest.mark.parametrize('context', [
    None, 'invalid', {},
    {**CONTEXT, 'operation': 'delete'},
    {**CONTEXT, 'vacancy_id': '0'},
    {**CONTEXT, 'vacancy_id': {'id': '123'}},
    {**CONTEXT, 'vacancy_id': 'https://example.com/123'},
    {**CONTEXT, 'resume_id': ''},
    {**CONTEXT, 'resume_id': 'value\nAuthorization: secret'},
    {**CONTEXT, 'resume_id': 'x' * 129},
])
def test_invalid_context_does_not_block_challenge_capture(context):
    acc = {'user_id': 'context-account'}
    assert captcha.capture(acc, 403, payload(), request_context=context)
    assert captcha.active(acc)
    assert 'request_context' not in captcha.current(acc)


def test_same_state_fills_missing_context_without_changing_manual_ownership_or_retry():
    acc = {'user_id': 'context-account'}
    captcha.capture(acc, 403, payload())
    original = captcha.current(acc)
    captcha.claim_manual(acc, original['id'], auto_retry_after=120)
    captcha.set_local_retry(acc, original['id'], 60, 'isBot', 4)
    original = captcha.current(acc)
    captcha.capture(acc, 403, payload(URL + '&backurl=https%3A%2F%2Fhh.ru%2F'),
                    request_context=CONTEXT)
    assert captcha.current(acc) == {**original, 'request_context': CONTEXT}


def test_repeat_same_state_preserves_original_target():
    acc = {'user_id': 'context-account'}
    captcha.capture(acc, 403, payload(), request_context=CONTEXT)
    original = captcha.current(acc)
    captcha.capture(acc, 403, payload(), request_context={**CONTEXT, 'vacancy_id': '654321'})
    assert captcha.current(acc) == original


def test_unmatched_response_without_state_cannot_fill_context_of_existing_challenge():
    acc = {'user_id': 'context-account'}
    captcha.capture(acc, 403, payload())
    original = captcha.current(acc)
    captcha.capture(acc, 403, payload('https://hh.ru/account/captcha'), request_context=CONTEXT)
    assert captcha.current(acc) == original


@pytest.mark.parametrize('new_context', [None, {**CONTEXT, 'vacancy_id': '654321'}])
def test_replacement_state_never_inherits_previous_apply_target(new_context):
    acc = {'user_id': 'context-account'}
    captcha.capture(acc, 403, payload(), request_context=CONTEXT)
    original = captcha.current(acc)
    captcha.capture(acc, 403, payload('https://hh.ru/account/captcha?state=NEW_STATE'),
                    request_context=new_context)
    current = captcha.current(acc)
    assert current['id'] != original['id']
    assert current.get('request_context') == new_context
    with pytest.raises(ValueError, match='Challenge changed'):
        captcha.clear(acc, original['id'])


def test_existing_capture_calls_need_no_context_and_non_challenge_does_not_store_it():
    acc = {'user_id': 'context-account'}
    assert captcha.capture(acc, 200, {}, request_context=CONTEXT) is None
    assert not captcha.current(acc)
    assert captcha.capture(acc, 403, payload())
    assert 'request_context' not in captcha.current(acc)

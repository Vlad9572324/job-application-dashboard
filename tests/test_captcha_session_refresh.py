"""A rejected answer must refresh the picture without resetting HH cookies."""
from unittest.mock import Mock

import pytest

from app import captcha_solver as solver


def test_refresh_uses_rejection_cookies_new_key_and_original_region(monkeypatch):
    session = Mock()
    session.hh_captcha_origin = 'https://spb.hh.ru'
    session.cookies.get.return_value = 'xsrf-after-rejection'
    session.post.return_value = Mock(status_code=200, json=lambda: {'key': 'new-key'})
    session.get.return_value = Mock(status_code=200, content=b'new-image')
    prime = Mock(side_effect=AssertionError('A refresh must not recreate the session'))
    monkeypatch.setattr(solver, '_prime_session', prime)

    result = solver.refresh_captcha_image(session, 'state-after-rejection', 'https://hh.ru/')

    assert result == (session, 'new-key', b'new-image', 'state-after-rejection', 'https://hh.ru/')
    prime.assert_not_called()
    session.post.assert_called_once()
    assert session.post.call_args.args == ('https://spb.hh.ru/captcha',)
    assert session.post.call_args.kwargs['headers']['X-Xsrftoken'] == 'xsrf-after-rejection'
    session.get.assert_called_once()
    assert session.get.call_args.args == ('https://spb.hh.ru/captcha/picture',)
    assert session.get.call_args.kwargs['params'] == {'key': 'new-key'}
    session.close.assert_not_called()


def test_refresh_rate_limit_propagates_wait_and_leaves_cleanup_to_owner():
    session = Mock()
    session.cookies.get.return_value = 'xsrf'
    session.post.return_value = Mock(status_code=429, headers={'Retry-After': '300'})

    with pytest.raises(ValueError, match='get_key_http_429') as exc:
        solver.refresh_captcha_image(session, 'state', 'https://hh.ru/')

    assert exc.value.retry_after == 300
    session.get.assert_not_called()
    session.close.assert_not_called()


def test_refresh_without_state_never_requests_a_picture():
    session = Mock()
    with pytest.raises(ValueError, match='missing_state'):
        solver.refresh_captcha_image(session, '', 'https://hh.ru/')
    session.post.assert_not_called()
    session.get.assert_not_called()

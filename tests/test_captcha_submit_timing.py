"""Readiness is attached to the opened check, not to every refreshed image."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import captcha_solver as solver


def test_initial_image_sets_deadline_and_refresh_keeps_it(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(solver.time, 'monotonic', lambda: clock[0])
    session = Mock()
    session.cookies.get.return_value = 'xsrf'
    session.post.return_value = Mock(status_code=200, json=lambda: {'key': 'key'})
    session.get.return_value = Mock(status_code=200, content=b'image')

    solver.refresh_captcha_image(session, 'state', 'https://hh.ru/')
    assert session.hh_captcha_submit_not_before == 110.0
    assert solver.captcha_submit_delay(session) == 10.0
    clock[0] = 104.0  # Local recognition time already counts toward readiness.
    assert solver.captcha_submit_delay(session) == 6.0
    clock[0] = 112.0
    solver.refresh_captcha_image(session, 'state', 'https://hh.ru/')
    assert session.hh_captcha_submit_not_before == 110.0
    assert solver.captcha_submit_delay(session) == 0.0


@pytest.mark.parametrize('deadline', [None, True, '123', float('nan'), float('inf'), Mock()])
def test_untracked_or_invalid_deadline_has_no_wait(deadline):
    assert solver.captcha_submit_delay(SimpleNamespace(hh_captcha_submit_not_before=deadline)) == 0


def test_failed_image_does_not_start_the_readiness_clock():
    session = Mock()
    session.cookies.get.return_value = 'xsrf'
    session.post.return_value = Mock(status_code=200, json=lambda: {'key': 'key'})
    session.get.return_value = Mock(status_code=500)
    with pytest.raises(ValueError, match='image_http_500'):
        solver.refresh_captcha_image(session, 'state', 'https://hh.ru/')
    assert 'hh_captcha_submit_not_before' not in vars(session)

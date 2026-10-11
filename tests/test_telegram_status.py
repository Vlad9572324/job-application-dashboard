import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import telegram_status as status


@pytest.fixture
def manager(monkeypatch, tmp_path):
    monkeypatch.setattr(status, '_EVENTS_FILE', tmp_path / 'events.json')
    monkeypatch.setattr(status.CONFIG, 'daily_apply_limit', 50)
    monkeypatch.setattr(status.CONFIG, 'hh_daily_limit', 200)
    monkeypatch.setattr(status.CONFIG, 'automation_paused', False)
    monkeypatch.setattr(status.CONFIG, 'human_mode_enabled', False)
    monkeypatch.setattr(status.CONFIG, 'fresh_vacancies_mode', False)
    monkeypatch.setattr(status.CONFIG, 'prefer_hh_signals', False)
    monkeypatch.setattr(status.CONFIG, 'captcha_llm_enabled', False)
    monkeypatch.setattr(status.storage, '_load_cache', lambda: None)
    now = datetime.now(status._MSK)
    monkeypatch.setattr(status.storage, '_cache_applied', {'Maria': {
        '1': {'at': now.isoformat()},
        '2': {'at': (now - timedelta(days=1)).isoformat()},
        '3': {'at': ''},
    }})
    account = SimpleNamespace(name='Maria', short='Мария', status='applying',
                              current_vacancy_title='Python Developer',
                              current_vacancy_company='Yandex')
    bot = SimpleNamespace(account_states=[account], temp_states={}, _add_log=Mock())
    status.install_status_tracking(bot)
    return bot


def test_snapshot(manager):
    manager._add_log('Мария', '', '🔐 HH запросил капчу', 'warning')
    manager._add_log('Мария', '', 'Ошибка запроса', 'error')
    snapshot = status.build_status_snapshot(manager)
    assert snapshot['accounts'][0].pop('last_error_time') == datetime.now(status._MSK).strftime('%H:%M')
    assert snapshot['accounts'] == [dict(short='Мария', state='🟢 работает',
        applied_today=1, daily_limit=50, hourly_rate=1.0,
        current_vacancy='Python Developer / Yandex', last_error='Ошибка запроса',
        captcha_count=1, next_apply_sec=None, detail=None, next_step=None,
        wait_reason='', remaining_today=49, daily_used=1, fresh_only=False,
        fresh_hours=None, fresh_reserve=0, prefer_hh_signals=False,
        captcha_manual_required=False)]
    assert snapshot['totals'] == dict(applied_today=1, captcha_today=1, errors_today=1)


def test_html(manager):
    snapshot = status.build_status_snapshot(manager)
    html = status.build_status_html(snapshot)
    assert '1/50 (2%)' in html
    assert 'За последний час: 1' in html
    assert '<i>Python Developer / Yandex</i>' in html
    snapshot['accounts'][0]['short'] = '<script>&'
    assert '&lt;script&gt;&amp;' in status.build_status_html(snapshot)


def test_unchanged(manager):
    snapshot = status.build_status_snapshot(manager)
    assert not status.should_send(snapshot, deepcopy(snapshot))


@pytest.mark.parametrize('field,value', [('applied_today', 2), ('state', '🚫 ждёт капчу'),
                                         ('captcha_count', 1), ('last_error', 'error')])
def test_changed(manager, field, value):
    previous = status.build_status_snapshot(manager)
    current = deepcopy(previous)
    current['accounts'][0][field] = value
    assert status.should_send(previous, current)


def test_new_error_same_text(manager):
    previous = status.build_status_snapshot(manager)
    current = deepcopy(previous)
    current['totals']['errors_today'] += 1
    assert status.should_send(previous, current)


def test_rate_alone_does_not_send(manager):
    previous = status.build_status_snapshot(manager)
    current = deepcopy(previous)
    current['accounts'][0]['hourly_rate'] = 0
    assert not status.should_send(previous, current)


@pytest.mark.parametrize('reason,expected', [('challenge', '🚫 ждёт капчу'), ('limit', '🔴 лимит')])
def test_state_priority(manager, reason, expected):
    manager.account_states[0].paused = True
    manager.account_states[0].paused_reason = reason
    assert status.build_status_snapshot(manager)['accounts'][0]['state'] == expected


def test_daily_rollover(manager):
    manager._add_log('Мария', '', 'HH запросил капчу', 'warning')
    manager._telegram_status_events['day'] -= timedelta(days=1)
    assert status.build_status_snapshot(manager)['totals']['captcha_today'] == 0


def test_heartbeat_send_and_cancel(manager, monkeypatch):
    monkeypatch.setattr(status.CONFIG, 'telegram_status_enabled', True)
    send = Mock(return_value=True)
    monkeypatch.setattr(status.telegram_notify, 'send_once', send)
    sleeps = 0

    async def sleep(seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(status.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(status.status_heartbeat(manager, None, 30))
    assert send.call_count == 1
    assert send.call_args.args[0].startswith('status:')
    assert send.call_args.kwargs == {'parse_mode': 'HTML'}


def test_counters_survive_restart(manager):
    manager._add_log(acc_short='Мария', acc_color='', message='HH запросил капчу', level='warning')
    restarted = SimpleNamespace(account_states=manager.account_states, temp_states={}, _add_log=Mock())
    status.install_status_tracking(restarted)
    assert status.build_status_snapshot(restarted)['totals']['captcha_today'] == 1


def test_idle_wait_is_running_not_paused(manager):
    s = manager.account_states[0]
    s.status, s.status_detail, s.paused = 'idle', 'Пауза после капчи: ещё 14 мин', False
    snap = status.build_status_snapshot(manager)
    assert snap['accounts'][0]['state'] == '🟢 работает'
    assert snap['header'] == '🟢 Бот работает'
    assert 'Пауза после капчи' in status.build_status_html(snap)


def test_stale_error_hidden_and_challenge_file_shows_waiting(manager, monkeypatch):
    manager._add_log('Мария', '', 'Старая ошибка', 'error')
    events = manager._telegram_status_events['accounts']['Мария']
    events['last_error_at'] = (datetime.now(status._MSK) - timedelta(hours=5)).isoformat()
    snapshot = status.build_status_snapshot(manager)
    assert snapshot['accounts'][0]['last_error'] is None
    monkeypatch.setattr(status, '_challenge_pending', lambda acc: True)
    snapshot = status.build_status_snapshot(manager)
    assert snapshot['accounts'][0]['state'] == '🚫 ждёт капчу'
    assert 'Ждём решения капчи' in snapshot['header']
    html = status.build_status_html(snapshot)
    assert 'через сейчас' not in html and 'Нужна капча' in html

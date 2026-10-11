"""Telegram status must describe the actual gate, not only the pace timer."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import captcha, human_pace
from app import telegram_status as status


NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


@pytest.fixture
def mode_manager(monkeypatch):
    for key, value in {
        'daily_apply_limit': 200, 'hh_daily_limit': 200,
        'fresh_vacancies_mode': True, 'fresh_vacancy_hours': 24,
        'fresh_apply_reserve': 50, 'prefer_hh_signals': True,
        'automation_paused': False, 'human_mode_enabled': True,
        'human_active_hours': '07-24', 'human_apply_delay_min': 0,
        'human_apply_delay_max': 0, 'human_burst_pause_min_sec': 0,
        'human_burst_pause_max_sec': 0,
        'captcha_llm_enabled': True,
    }.items():
        monkeypatch.setattr(status.CONFIG, key, value)
    monkeypatch.setattr(status, 'datetime', FixedDateTime)
    monkeypatch.setattr(human_pace, 'datetime', FixedDateTime)
    monkeypatch.setattr(status, '_challenge_pending', lambda acc: False)
    monkeypatch.setattr(captcha, 'current', lambda acc: {})
    monkeypatch.setattr(human_pace, '_pace_read', lambda: {})
    monkeypatch.setattr(human_pace, 'captcha_cooldown_remaining', lambda state: 0.0)
    monkeypatch.setattr(status.storage, '_load_cache', lambda: None)
    monkeypatch.setattr(status.storage, '_cache_applied', {'Test': {
        str(index): {'at': NOW.isoformat()} for index in range(157)
    }})
    state = SimpleNamespace(
        name='Test', short='Тест', acc={'user_id': 'test-status-only'},
        status='waiting', status_detail='Цикл завершён',
        activity={'phase': 'fresh_reserve', 'current': 'Ожидает свежие вакансии',
                  'next': 'Повторит поиск', 'wait_until': None,
                  'started_at': NOW.isoformat(), 'requires_action': False},
        daily_sent=157, hh_today_applies=157, paused=False, paused_reason='',
        hard_stopped=False, limit_exceeded=False, _deleted=False,
        pending_apply=None, pending_applies=[], _auth_recovery_pending=False,
        current_vacancy_title='', current_vacancy_company='',
        _workers=[SimpleNamespace(is_alive=lambda: True)],
    )
    return SimpleNamespace(account_states=[state], temp_states={}, paused=False,
                           _stop_event=threading.Event(), _add_log=Mock())


def account_row(manager):
    return status.build_status_snapshot(manager)['accounts'][0]


@pytest.mark.parametrize('phase, expected', [
    ('collect', '🔎 ищет свежие вакансии'),
    ('filter', '🔎 ищет свежие вакансии'),
    ('fresh_reserve', '🆕 ждёт свежие вакансии'),
    ('no_new', '🆕 ждёт свежие вакансии'),
    ('cycle_wait', '🆕 ждёт свежие вакансии'),
    ('idle', '🆕 ждёт свежие вакансии'),
    ('apply', '🟢 работает'),
    ('preflight', '🟢 работает'),
    ('questionnaire', '🟢 работает'),
])
def test_fresh_mode_preserves_actual_work_phase(mode_manager, phase, expected):
    mode_manager.account_states[0].activity['phase'] = phase
    row = account_row(mode_manager)
    assert row['state'] == expected
    assert row['fresh_only'] is True
    assert row['fresh_hours'] == 24
    assert row['fresh_reserve'] == 50
    assert row['prefer_hh_signals'] is True
    assert row['remaining_today'] == 43
    if expected != '🟢 работает':
        assert row['wait_reason']


@pytest.mark.parametrize('used, remaining, fresh_only', [
    (149, 51, False), (150, 50, True), (199, 1, True),
    (200, 0, False), (203, 0, False),
])
def test_reserve_boundary_and_exhausted_limit(mode_manager, monkeypatch, used, remaining, fresh_only):
    monkeypatch.setattr(status.storage, '_cache_applied', {})
    state = mode_manager.account_states[0]
    state.daily_sent = state.hh_today_applies = used
    row = account_row(mode_manager)
    assert row['daily_used'] == used
    assert row['remaining_today'] == remaining
    assert row['fresh_only'] is fresh_only
    if remaining == 0:
        assert row['state'] == '🔴 лимит'


@pytest.mark.parametrize('stored, local, hh, expected', [
    (157, 140, 150, 157), (1, 158, 155, 158), (1, 152, 160, 160),
])
def test_budget_uses_highest_confirmed_counter(mode_manager, monkeypatch, stored, local, hh, expected):
    monkeypatch.setattr(status.storage, '_cache_applied', {'Test': {
        str(index): {'at': NOW.isoformat()} for index in range(stored)
    }})
    state = mode_manager.account_states[0]
    state.daily_sent, state.hh_today_applies = local, hh
    row = account_row(mode_manager)
    assert row['applied_today'] == stored
    assert row['daily_used'] == expected
    assert row['remaining_today'] == 200 - expected


@pytest.mark.parametrize('enabled, reserve', [(False, 50), (True, 0), (True, -10)])
def test_disabled_reserve_does_not_reuse_stale_wait_phase(mode_manager, monkeypatch, enabled, reserve):
    monkeypatch.setattr(status.CONFIG, 'fresh_vacancies_mode', enabled)
    monkeypatch.setattr(status.CONFIG, 'fresh_apply_reserve', reserve)
    row = account_row(mode_manager)
    assert row['fresh_only'] is False
    assert row['state'] not in ('🆕 ждёт свежие вакансии', '🔎 ищет свежие вакансии')


def test_reserve_is_clamped_to_effective_daily_ceiling(mode_manager, monkeypatch):
    monkeypatch.setattr(status.storage, '_cache_applied', {})
    monkeypatch.setattr(status.CONFIG, 'daily_apply_limit', 120)
    monkeypatch.setattr(status.CONFIG, 'fresh_apply_reserve', 500)
    state = mode_manager.account_states[0]
    state.daily_sent = state.hh_today_applies = 0
    row = account_row(mode_manager)
    assert row['daily_limit'] == 120
    assert row['fresh_reserve'] == 120
    assert row['remaining_today'] == 120
    assert row['fresh_only'] is True


@pytest.mark.parametrize('protection', [
    'manual', 'global', 'auth', 'network_error', 'hh_rate_limit',
    'challenge', 'limit', 'outcome_unknown', 'auth_pending', 'stopped',
])
def test_protective_gate_overrides_fresh_wait(mode_manager, monkeypatch, protection):
    state = mode_manager.account_states[0]
    if protection == 'global':
        mode_manager.paused = True
    elif protection == 'challenge':
        # Persistent challenge must win even before state.pause catches up.
        monkeypatch.setattr(status, '_challenge_pending', lambda acc: True)
    elif protection == 'auth_pending':
        state._auth_recovery_pending = True
    elif protection == 'stopped':
        state._workers = []
    else:
        state.paused, state.paused_reason = True, protection
        if protection == 'outcome_unknown':
            state.pending_apply = {'recorded_at': NOW.isoformat()}
    snapshot = status.build_status_snapshot(mode_manager)
    row = snapshot['accounts'][0]
    assert row['state'] not in ('🆕 ждёт свежие вакансии', '🔎 ищет свежие вакансии', '🟢 работает')
    assert row['wait_reason']
    assert 'Следующий отклик: сейчас' not in status.build_status_html(snapshot)


def test_closed_active_hours_override_stale_collect_phase(mode_manager, monkeypatch):
    monkeypatch.setattr(status.CONFIG, 'human_active_hours', '22-23')
    mode_manager.account_states[0].activity['phase'] = 'collect'
    row = account_row(mode_manager)
    assert row['state'] == '🌙 ждёт активного времени'
    assert row['wait_reason']


def test_disabled_human_mode_does_not_block_on_active_hours(mode_manager, monkeypatch):
    monkeypatch.setattr(status.CONFIG, 'human_mode_enabled', False)
    monkeypatch.setattr(status.CONFIG, 'human_active_hours', '22-23')
    mode_manager.account_states[0].activity['phase'] = 'collect'
    assert account_row(mode_manager)['state'] == '🔎 ищет свежие вакансии'


@pytest.mark.parametrize('human_enabled', [True, False])
def test_post_captcha_cooldown_is_visible_even_without_human_mode(mode_manager, monkeypatch, human_enabled):
    monkeypatch.setattr(status.CONFIG, 'human_mode_enabled', human_enabled)
    monkeypatch.setattr(human_pace, 'captcha_cooldown_remaining', lambda state: 17.0)
    row = account_row(mode_manager)
    assert row['state'] == '⏳ пауза после капчи'
    assert row['wait_reason']


def test_html_shows_actual_reserved_remainder_without_immediate_apply_promise(mode_manager):
    snapshot = status.build_status_snapshot(mode_manager)
    html = status.build_status_html(snapshot)
    assert '157/200' in html
    assert '43' in html
    assert 'свеж' in html.lower()
    assert 'Следующий отклик: сейчас' not in html
    assert snapshot['header'] != '⏸ Нет активных аккаунтов'


def test_in_flight_apply_does_not_show_reserved_next_attempt_as_current_wait(mode_manager, monkeypatch):
    state = mode_manager.account_states[0]
    state.activity.update(phase='apply', current='Отправляет отклик и ожидает ответа HH')
    reserved = time.time()
    monkeypatch.setattr(human_pace, '_pace_read', lambda: {
        'test-status-only': {'reserved_at': reserved, 'next_at': reserved + 600},
    })
    assert status._next_apply_seconds(state.acc) > 590
    snapshot = status.build_status_snapshot(mode_manager)
    assert snapshot['accounts'][0]['state'] == '🟢 работает'
    assert snapshot['accounts'][0]['next_apply_sec'] is None
    assert 'Интервал перед отправкой' not in status.build_status_html(snapshot)


def test_actual_worker_wait_uses_activity_deadline(mode_manager, monkeypatch):
    state = mode_manager.account_states[0]
    state.activity.update(
        phase='wait_between_batches', current='Выдерживает интервал между откликами',
        wait_until=(NOW + timedelta(seconds=17)).isoformat(),
    )
    # A different durable reservation must not replace the observed wait.
    reserved = time.time()
    monkeypatch.setattr(human_pace, '_pace_read', lambda: {
        'test-status-only': {'reserved_at': reserved, 'next_at': reserved + 600},
    })
    snapshot = status.build_status_snapshot(mode_manager)
    row = snapshot['accounts'][0]
    assert row['state'] == '🟢 работает'
    assert row['wait_reason'] == 'wait_between_batches'
    assert row['next_apply_sec'] == 17.0
    assert 'Интервал перед отправкой: ещё 17с' in status.build_status_html(snapshot)


@pytest.mark.parametrize('record', [
    {'local_retry_reason': 'recaptcha'},
    {'local_retry_reason': 'missing_state'},
    {'manual_only': True},
])
def test_manual_challenge_still_offers_manual_action_with_auto_enabled(mode_manager, monkeypatch, record):
    monkeypatch.setattr(status, '_challenge_pending', lambda acc: True)
    monkeypatch.setattr(captcha, 'current', lambda acc: record)
    snapshot = status.build_status_snapshot(mode_manager)
    row = snapshot['accounts'][0]
    assert row['state'] == '🚫 ждёт капчу'
    assert row['captcha_manual_required'] is True
    assert 'вручную' in row['detail'] or 'ручного' in row['detail']
    assert '/captcha' in status.build_status_html(snapshot)


def test_automatic_challenge_reports_local_processing_without_manual_requirement(mode_manager, monkeypatch):
    monkeypatch.setattr(status, '_challenge_pending', lambda acc: True)
    monkeypatch.setattr(captcha, 'current', lambda acc: {'local_retry_reason': 'isBot'})
    snapshot = status.build_status_snapshot(mode_manager)
    row = snapshot['accounts'][0]
    assert row['state'] == '🚫 ждёт капчу'
    assert row['captcha_manual_required'] is False
    assert 'автоматически' in row['detail']
    assert 'локальной моделью' in row['detail']
    assert '/captcha' not in status.build_status_html(snapshot)


def test_account_without_challenge_has_no_manual_captcha_requirement(mode_manager):
    assert account_row(mode_manager)['captcha_manual_required'] is False


@pytest.mark.parametrize('field, value', [
    ('fresh_only', False), ('fresh_hours', 12), ('fresh_reserve', 30),
    ('wait_reason', 'active_hours'),
])
def test_stable_mode_change_triggers_status_report(mode_manager, field, value):
    previous = status.build_status_snapshot(mode_manager)
    current = deepcopy(previous)
    current['accounts'][0][field] = value
    assert status.should_send(previous, current)


def test_countdown_and_progress_alone_do_not_trigger_status_report(mode_manager):
    previous = status.build_status_snapshot(mode_manager)
    current = deepcopy(previous)
    row = current['accounts'][0]
    row['next_apply_sec'] = 9.0
    row['wait_seconds'] = 9.0
    row['wait_until'] = (NOW + timedelta(seconds=9)).isoformat()
    row['progress'] = {'done': 2, 'total': 10}
    assert not status.should_send(previous, current)


def test_snapshot_does_not_reenter_account_lock(mode_manager):
    state = mode_manager.account_states[0]
    state._state_lock = threading.Lock()
    results, errors = [], []

    def snapshot():
        try:
            results.append(status.build_status_snapshot(mode_manager))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=snapshot, daemon=True)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive(), 'snapshot deadlocked by reacquiring AccountState._state_lock'
    assert not errors
    assert results[0]['accounts'][0]['state'] == '🆕 ждёт свежие вакансии'

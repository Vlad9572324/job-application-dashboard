"""Local retries use fresh images and durable delays without Telegram delivery."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import requests

from app import captcha, captcha_worker as worker
from app.config import CONFIG


@pytest.fixture
def flow(monkeypatch):
    clock = SimpleNamespace(now=2_000_000_000.0)
    fake_time = SimpleNamespace(time=lambda: clock.now, monotonic=lambda: clock.now)
    monkeypatch.setattr(worker, 'time', fake_time)
    monkeypatch.setattr(captcha, 'time', fake_time, raising=False)
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(CONFIG, 'captcha_llm_solved', 0)
    monkeypatch.setattr(CONFIG, 'captcha_llm_forwarded', 0)
    acc = {'user_id': 'automatic-test-account', 'short': 'Test'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test-state'})
    cid = captcha.current(acc)['id']
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc, _deleted=False)],
                              temp_states={}, resume_challenge_account=Mock(), _add_log=Mock())
    bot = Mock(connected=False, _task=None,
               push_challenge=AsyncMock(return_value=False),
               send_message=AsyncMock(), send_browser_option=AsyncMock())
    sessions = []
    images = []

    def next_image(session, state, backurl):
        number = len(images) + 1
        image = f'image-{number}'.encode()
        images.append(image)
        return session, f'key-{number}', image, state, backurl

    def fresh_image(*args):
        session = SimpleNamespace(close=Mock(), hh_captcha_diagnostic={},
                                  hh_captcha_next_state=None, hh_captcha_retry_after=None)
        sessions.append(session)
        return next_image(session, 'test-state', 'https://hh.ru/')

    fetch = Mock(side_effect=fresh_image)
    refresh = Mock(side_effect=next_image)
    recognize = Mock(return_value='ответ модели')
    submit = Mock(return_value=(False, 'isBot'))
    monkeypatch.setattr(worker, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(worker, 'refresh_captcha_image', refresh)
    monkeypatch.setattr(worker, 'recognize_captcha', recognize)
    monkeypatch.setattr(worker, 'submit_captcha', submit)

    def change_record(**values):
        with captcha.LOCK:
            records = captcha._read()
            records[captcha.account_key(acc)].update(values)
            captcha._atomic_write_json(captcha.PATH, records)

    def coordinator():
        return worker.CaptchaCoordinator(manager, bot)

    return SimpleNamespace(clock=clock, acc=acc, cid=cid, manager=manager, bot=bot,
                           sessions=sessions, fetch=fetch, recognize=recognize,
                           refresh=refresh, images=images, submit=submit,
                           change_record=change_record, coordinator=coordinator)


def test_rejected_answers_retry_with_fresh_images_then_resume_without_telegram(flow):
    async def run():
        coord = flow.coordinator()
        coord._seen.add(flow.cid)  # A previous delivery must not disable local retries.
        for attempt, delay in enumerate((5, 10, 20, 40, 60, 60), start=1):
            await coord.scan()
            record = captcha.current(flow.acc)
            assert record['local_attempts'] == attempt
            assert record['local_retry_reason'] == 'isBot'
            assert record['local_retry_at'] == pytest.approx(flow.clock.now + delay)
            assert flow.submit.call_count == attempt
            flow.sessions[0].close.assert_not_called()
            assert coord.pending[flow.cid]['session'] is flow.sessions[0]
            assert coord.pending[flow.cid]['captcha_key'] is None
            flow.clock.now += delay - 0.1
            await coord.scan()
            assert len(flow.images) == attempt
            flow.clock.now += 0.1
        flow.submit.return_value = (True, '')
        await coord.scan()
        assert not captcha.current(flow.acc)
        flow.manager.resume_challenge_account.assert_called_once_with(flow.acc['user_id'])
        flow.bot.push_challenge.assert_not_awaited()
        assert CONFIG.captcha_llm_solved == 1
        flow.fetch.assert_called_once()
        assert flow.refresh.call_count == 6
        assert [call.args[2] for call in flow.submit.call_args_list] == [
            f'key-{i}' for i in range(1, 8)]
        for call in flow.submit.call_args_list:
            assert call.args[0] is flow.sessions[0]
            assert call.kwargs['require_confirmation'] is True
        flow.sessions[0].close.assert_called_once()

    asyncio.run(run())


def test_unreadable_image_waits_and_next_attempt_fetches_new_image(flow):
    async def run():
        flow.recognize.return_value = None
        coord = flow.coordinator()
        await coord.scan()
        assert captcha.current(flow.acc)['local_retry_at'] == flow.clock.now + 30
        flow.submit.assert_not_called()
        flow.sessions[0].close.assert_called_once()
        await coord.scan()
        flow.fetch.assert_called_once()
        flow.clock.now += 30
        flow.recognize.return_value = 'ответ модели'
        flow.submit.return_value = (True, '')
        await coord.scan()
        assert flow.fetch.call_count == 2
        assert flow.submit.call_args.args[2] == 'key-2'
        assert not captcha.current(flow.acc)

    asyncio.run(run())


def test_transport_timeout_persists_backoff_and_never_replays_consumed_keys(flow):
    async def run():
        flow.submit.side_effect = requests.Timeout('synthetic')
        for attempt, expected_delay in enumerate((30, 60, 120, 240, 480, 600), start=1):
            coord = flow.coordinator()
            await coord.scan()
            record = captcha.current(flow.acc)
            assert record['local_retry_at'] == flow.clock.now + expected_delay
            assert flow.fetch.call_count == attempt
            flow.sessions[-1].close.assert_called_once()
            restarted = flow.coordinator()
            await restarted.scan()
            assert flow.fetch.call_count == attempt
            flow.clock.now += expected_delay
        assert [call.args[2] for call in flow.submit.call_args_list] == [
            f'key-{i}' for i in range(1, 7)]
        flow.manager.resume_challenge_account.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize('retry_after,minimum_delay', [(None, 60), (120, 120)])
def test_rate_limit_waits_for_retry_after_across_coordinator_restart(flow, retry_after, minimum_delay):
    def limited(session, *args, **kwargs):
        session.hh_captcha_retry_after = retry_after
        return False, 'http_429'

    async def run():
        flow.submit.side_effect = limited
        await flow.coordinator().scan()
        retry_at = captcha.current(flow.acc)['local_retry_at']
        assert retry_at >= flow.clock.now + minimum_delay
        flow.clock.now = retry_at - 0.1
        await flow.coordinator().scan()
        flow.fetch.assert_called_once()
        flow.submit.assert_called_once()
        flow.sessions[0].close.assert_called_once()
        flow.clock.now = retry_at
        await flow.coordinator().scan()
        assert flow.submit.call_count == 2
        assert flow.submit.call_args.args[2] == 'key-2'

    asyncio.run(run())


def test_recaptcha_remains_blocked_after_restart(flow):
    async def run():
        flow.submit.return_value = (False, 'recaptcha')
        coord = flow.coordinator()
        await coord.scan()
        assert captcha.current(flow.acc)
        flow.sessions[0].close.assert_called_once()
        await coord.scan()
        flow.clock.now += 86400
        await flow.coordinator().scan()
        flow.fetch.assert_called_once()
        flow.submit.assert_called_once()
        flow.manager.resume_challenge_account.assert_not_called()

    asyncio.run(run())


def test_fetch_rate_limit_persists_retry_after_without_running_model(flow):
    async def run():
        error = ValueError('get_key_http_429')
        error.retry_after = 180
        flow.fetch.side_effect = error
        await flow.coordinator().scan()
        record = captcha.current(flow.acc)
        assert record['local_retry_at'] == flow.clock.now + 180
        assert record['local_retry_reason'] == 'http_429'
        await flow.coordinator().scan()
        flow.fetch.assert_called_once()
        flow.recognize.assert_not_called()
        flow.submit.assert_not_called()
        flow.manager.resume_challenge_account.assert_not_called()

    asyncio.run(run())


def test_expired_manual_lease_releases_gui_and_telegram_sessions(flow):
    async def run():
        flow.change_record(manual_only=True, auto_retry_until=flow.clock.now + 5)
        coord = flow.coordinator()
        telegram_session, gui_session = Mock(), Mock()
        coord.pending[flow.cid] = {'session': telegram_session, 'captcha_key': 'telegram-key'}
        coord.gui_pending = {flow.cid: {'session': gui_session, 'created': flow.clock.now}}
        await coord.scan()
        flow.fetch.assert_not_called()
        flow.clock.now += 5
        await coord.scan()
        assert not captcha.current(flow.acc).get('manual_only')
        assert flow.fetch.call_count == 1
        assert flow.submit.call_args.args[2] == 'key-1'
        telegram_session.close.assert_called()
        gui_session.close.assert_called()
        assert flow.cid not in coord.gui_pending

    asyncio.run(run())


def test_manual_owner_without_auto_lease_is_not_released(flow):
    async def run():
        flow.change_record(manual_only=True)
        coord = flow.coordinator()
        await coord.scan()
        flow.clock.now += 86400
        await coord.scan()
        flow.fetch.assert_not_called()
        flow.submit.assert_not_called()
        assert captcha.current(flow.acc)['manual_only'] is True

    asyncio.run(run())


@pytest.mark.parametrize('next_state', ['server-next-state', None])
def test_retry_reuses_session_with_latest_server_state(flow, next_state):
    def rejected(session, *args, **kwargs):
        session.hh_captcha_next_state = next_state
        return False, 'isBot'

    original_fetch = flow.fetch.side_effect

    def bootstrapped(*args):
        session, key, image, _, backurl = original_fetch(*args)
        return session, key, image, 'bootstrap-state', backurl

    async def run():
        flow.fetch.side_effect = bootstrapped
        flow.submit.side_effect = rejected
        coord = flow.coordinator()
        await coord.scan()
        flow.clock.now += 5
        await coord.scan()
        expected = next_state or 'bootstrap-state'
        assert flow.refresh.call_args.args == (flow.sessions[0], expected, 'https://hh.ru/')
        assert flow.submit.call_args.args[3] == expected
        assert flow.submit.call_args.args[2] == 'key-2'
        flow.sessions[0].close.assert_not_called()
        coord.close()
        flow.sessions[0].close.assert_called_once()

    asyncio.run(run())


@pytest.mark.parametrize('reason', ['recaptcha', 'http_429', 'network_error', 'model_unavailable'])
def test_retained_session_closes_after_non_rejection_outcome(flow, reason):
    async def run():
        coord = flow.coordinator()
        await coord.scan()
        session = flow.sessions[0]
        flow.clock.now += 5
        if reason == 'network_error':
            flow.refresh.side_effect = requests.Timeout('synthetic')
        elif reason == 'model_unavailable':
            flow.recognize.return_value = None
        else:
            flow.submit.return_value = (False, reason)
        await coord.scan()
        flow.fetch.assert_called_once()
        flow.refresh.assert_called_once()
        session.close.assert_called_once()
        assert coord.pending[flow.cid]['session'] is None
        assert captcha.current(flow.acc)['local_retry_reason'] == reason
        coord.close()
        session.close.assert_called_once()

    asyncio.run(run())


@pytest.mark.parametrize('transition', ['manual', 'removed', 'deleted', 'replaced', 'disabled', 'shutdown'])
def test_retained_session_closes_when_ownership_ends(flow, transition, monkeypatch):
    async def run():
        coord = flow.coordinator()
        await coord.scan()
        session = flow.sessions[0]
        if transition == 'manual':
            flow.change_record(manual_only=True)
            await coord.scan()
        elif transition == 'removed':
            flow.manager.account_states = []
            await coord.scan()
        elif transition == 'deleted':
            flow.manager.account_states[0]._deleted = True
            flow.clock.now += 5
            await coord.scan()
            flow.fetch.assert_called_once()
            flow.submit.assert_called_once()
        elif transition == 'replaced':
            captcha.hold(flow.acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new-state'})
            flow.submit.return_value = (True, '')
            await coord.scan()
            assert flow.fetch.call_count == 2
        elif transition == 'disabled':
            monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', False)
            coord.close(automatic_only=True)
        else:
            coord.close()
        session.close.assert_called_once()
        assert flow.cid not in coord.pending
        flow.refresh.assert_not_called()
        coord.close()
        session.close.assert_called_once()

    asyncio.run(run())


@pytest.mark.parametrize('stage', ['fetch', 'refresh', 'submit'])
def test_cancelled_http_thread_keeps_exclusive_session_until_it_finishes(flow, stage):
    import threading

    async def run():
        coord = flow.coordinator()
        if stage != 'fetch':
            await coord.scan()
            flow.clock.now += 5
        started, release = threading.Event(), threading.Event()
        closed_while_running = []
        operation = flow.fetch if stage == 'fetch' else flow.refresh if stage == 'refresh' else flow.submit
        original = operation.side_effect

        def blocking(*args, **kwargs):
            if stage == 'fetch':
                result = original(*args, **kwargs)
                session = result[0]
            else:
                session = args[0]
                result = original(*args, **kwargs) if stage == 'refresh' else (False, 'isBot')
            started.set()
            assert release.wait(5)
            closed_while_running.append(session.close.call_count)
            return result

        operation.side_effect = blocking
        task = asyncio.create_task(coord.scan())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            session = flow.sessions[0]
            assert coord.pending[flow.cid]['session'] is None
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            coord.close()
            session.close.assert_not_called()
        finally:
            release.set()
        # Drain the worker threads and the task's close callback.
        await asyncio.get_running_loop().shutdown_default_executor()
        await asyncio.sleep(0)
        assert closed_while_running == [0]
        session.close.assert_called_once()
        flow.manager.resume_challenge_account.assert_not_called()

    asyncio.run(run())


def test_failed_final_state_read_closes_retained_session(flow, monkeypatch):
    original = captcha.current
    calls = 0

    def unreadable_on_cleanup(acc):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError('synthetic storage failure')
        return original(acc)

    async def run():
        monkeypatch.setattr(captcha, 'current', unreadable_on_cleanup)
        coord = flow.coordinator()
        await coord.scan()
        assert calls == 4
        flow.sessions[0].close.assert_called_once()
        assert coord.pending[flow.cid]['session'] is None

    asyncio.run(run())


def test_orchestrator_shutdown_closes_idle_retry_session(flow, monkeypatch):
    async def run():
        finished = asyncio.Event()
        original_scan = worker.CaptchaCoordinator.scan

        async def scanned_then_wait(coordinator):
            await original_scan(coordinator)
            finished.set()
            await asyncio.Future()

        monkeypatch.setattr(worker.CaptchaCoordinator, 'scan', scanned_then_wait)
        monkeypatch.setattr(worker, 'TelegramCaptchaBot', lambda: flow.bot)
        flow.bot.start = AsyncMock()
        flow.bot.stop = AsyncMock()
        task = asyncio.create_task(worker.captcha_orchestrator(flow.manager))
        await asyncio.wait_for(finished.wait(), 5)
        flow.sessions[0].close.assert_not_called()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        flow.sessions[0].close.assert_called_once()
        flow.bot.stop.assert_awaited_once()
        assert flow.manager.telegram_captcha_coordinator is None

    asyncio.run(run())

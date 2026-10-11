"""First submission waits asynchronously and retains exclusive ownership."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import captcha, captcha_worker as worker
from app.config import CONFIG


@pytest.fixture
def delayed_flow(monkeypatch):
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(CONFIG, 'captcha_llm_solved', 0)
    acc = {'user_id': 'waiting-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test-state'})
    cid = captcha.current(acc)['id']
    state = SimpleNamespace(acc=acc, _deleted=False)
    manager = SimpleNamespace(account_states=[state], temp_states={},
                              resume_challenge_account=Mock(), _add_log=Mock())
    bot = Mock(send_message=AsyncMock())
    session = SimpleNamespace(close=Mock(), hh_captcha_next_state=None,
                              hh_captcha_diagnostic={})
    fetch = Mock(return_value=(session, 'key-1', b'image-1', 'test-state', 'https://hh.ru/'))
    refresh = Mock(return_value=(session, 'key-2', b'image-2', 'test-state', 'https://hh.ru/'))
    recognize = Mock(return_value='ответ модели')
    submit = Mock(return_value=(True, ''))
    delay = Mock(return_value=7.25)
    sleep = AsyncMock()
    journal = Mock()
    monkeypatch.setattr(worker, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(worker, 'refresh_captcha_image', refresh)
    monkeypatch.setattr(worker, 'recognize_captcha', recognize)
    monkeypatch.setattr(worker, 'submit_captcha', submit)
    monkeypatch.setattr(worker, 'captcha_submit_delay', delay)
    monkeypatch.setattr(worker.captcha_journal, 'record', journal)
    # Patching the worker namespace keeps pytest/event-loop scheduling intact.
    async_api = {name: getattr(asyncio, name) for name in
                 ('Lock', 'create_task', 'to_thread', 'shield', 'CancelledError')}
    monkeypatch.setattr(worker, 'asyncio', SimpleNamespace(**async_api, sleep=sleep))
    coordinator = worker.CaptchaCoordinator(manager, bot)
    return SimpleNamespace(acc=acc, cid=cid, state=state, manager=manager,
                           session=session, fetch=fetch, refresh=refresh,
                           recognize=recognize, submit=submit, delay=delay,
                           sleep=sleep, journal=journal, coordinator=coordinator)


def test_first_submit_waits_remaining_time_after_ocr_and_records_wait(delayed_flow):
    flow = delayed_flow

    async def waiting(seconds):
        assert seconds == 7.25
        flow.recognize.assert_called_once_with(b'image-1')
        flow.submit.assert_not_called()
        item = flow.coordinator.pending[flow.cid]
        assert item['session'] is None
        assert item['llm_result'] == {'status': 'waiting', 'answer': 'ответ модели',
                                      'retry_seconds': 8}
        flow.session.close.assert_not_called()
        await asyncio.sleep(0)

    flow.sleep.side_effect = waiting
    asyncio.run(flow.coordinator.scan())
    flow.sleep.assert_awaited_once_with(7.25)
    flow.submit.assert_called_once()
    assert flow.journal.call_args.kwargs['initial_wait_seconds'] == 7.25
    flow.session.close.assert_called_once()
    assert not captcha.current(flow.acc)


def test_refresh_after_rejection_uses_elapsed_deadline_without_second_wait(delayed_flow):
    flow = delayed_flow
    flow.delay.side_effect = [7.25, 0.0]
    flow.submit.side_effect = [(False, 'isBot'), (True, '')]

    async def run():
        await flow.coordinator.scan()
        flow.session.close.assert_not_called()
        assert captcha.set_local_retry(flow.acc, flow.cid, 0, 'isBot', 1)
        await flow.coordinator.scan()

    asyncio.run(run())
    flow.sleep.assert_awaited_once_with(7.25)
    flow.fetch.assert_called_once()
    flow.refresh.assert_called_once_with(flow.session, 'test-state', 'https://hh.ru/')
    assert [call.args[2] for call in flow.submit.call_args_list] == ['key-1', 'key-2']
    assert [call.kwargs['initial_wait_seconds'] for call in flow.journal.call_args_list] == [7.25, 0.0]
    flow.session.close.assert_called_once()


@pytest.mark.parametrize('transition', ['challenge', 'manual', 'deleted', 'removed',
                                       'disabled', 'owner', 'coordinator'])
def test_ownership_change_during_wait_prevents_submission(delayed_flow, monkeypatch, transition):
    flow = delayed_flow

    async def changed_while_waiting(seconds):
        if transition == 'challenge':
            captcha.hold(flow.acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new-state'})
        elif transition == 'manual':
            captcha.claim_manual(flow.acc, flow.cid)
        elif transition == 'deleted':
            flow.state._deleted = True
        elif transition == 'removed':
            flow.manager.account_states = []
        elif transition == 'disabled':
            monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', False)
        elif transition == 'coordinator':
            worker.CaptchaCoordinator(flow.manager, Mock())
        else:
            flow.coordinator.pending[flow.cid] = {'automatic': True, 'session': None}
        await asyncio.sleep(0)

    flow.sleep.side_effect = changed_while_waiting
    asyncio.run(flow.coordinator.scan())
    flow.submit.assert_not_called()
    assert not any(call.args[0] == 'solve' for call in flow.journal.call_args_list)
    flow.session.close.assert_called_once()
    flow.manager.resume_challenge_account.assert_not_called()
    assert captcha.current(flow.acc)


def test_cancellation_during_wait_closes_without_dispatching_post(delayed_flow):
    flow = delayed_flow

    async def run():
        waiting = asyncio.Event()

        async def blocked(seconds):
            waiting.set()
            await asyncio.Future()

        flow.sleep.side_effect = blocked
        task = asyncio.create_task(flow.coordinator.scan())
        await asyncio.wait_for(waiting.wait(), 5)
        assert flow.coordinator.pending[flow.cid]['session'] is None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        flow.coordinator.close()

    asyncio.run(run())
    flow.submit.assert_not_called()
    flow.journal.assert_not_called()
    flow.session.close.assert_called_once()
    assert captcha.current(flow.acc)['id'] == flow.cid

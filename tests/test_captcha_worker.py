"""Test the complete persisted challenge → Telegram reply → HH submission → resume flow."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from app import captcha, captcha_worker as worker
from app.config import CONFIG
from app.telegram_bot import TelegramCaptchaBot


@pytest.mark.parametrize('outcomes', [[(True, '')], [(False, 'isBot'), (True, '')],
                                     [(False, 'isBot')] * 3, [(False, 'recaptcha')]])
def test_flow(monkeypatch, outcomes):
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', False)
    monkeypatch.setattr(CONFIG, 'telegram_bot_token', 'test-placeholder')
    monkeypatch.setattr(CONFIG, 'telegram_chat_id', '-123')
    acc = {'user_id': 'test-account', 'short': 'Test', 'cookies': {}}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test-state&backurl=ignored'})
    cid = captcha.current(acc)['id']
    failurl = captcha.browser_url(captcha.current(acc))
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={},
                              resume_challenge_account=Mock())
    session = SimpleNamespace()
    fetch = Mock(return_value=(session, 'test-key', b'png', 'test-state', 'https://hh.ru/'))
    submit = Mock(side_effect=outcomes)
    monkeypatch.setattr(worker, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(worker, 'submit_captcha', submit)
    async def run():
        bot = TelegramCaptchaBot()
        bot._call = AsyncMock(return_value={'message_id': 7})
        coordinator = worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        await coordinator.scan()
        assert fetch.call_count == 1
        assert coordinator.pending[cid]['captcha_state'] == 'test-state'
        for _ in outcomes:
            await bot.on_message('answer', -123, 7)
        assert submit.call_args.args == (session, 'answer', 'test-key', 'test-state', 'https://hh.ru/', failurl)
        if outcomes[-1][0]:
            # На успехе challenge снят, worker разбужен (auto-resume UX).
            assert not captcha.current(acc)
            manager.resume_challenge_account.assert_called_once_with('test-account')
        else:
            assert captcha.current(acc)['id'] == cid
            manager.resume_challenge_account.assert_not_called()
            assert 'вручную' in bot._call.call_args.args[1]['text']
        assert not coordinator.pending and not bot.pending
    asyncio.run(asyncio.wait_for(run(), 5))


def test_stale_answer(monkeypatch):
    acc = {'user_id': 'test-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test-state'})
    old_id = captcha.current(acc)['id']
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={},
                              resume_challenge_account=Mock())
    monkeypatch.setattr(worker, 'fetch_captcha_image', Mock(return_value=(SimpleNamespace(), 'key', b'png', 'test-state', 'https://hh.ru/')))
    submit = Mock()
    monkeypatch.setattr(worker, 'submit_captcha', submit)
    async def run():
        bot = Mock(push_challenge=AsyncMock(return_value={'message_id': 7}))
        coordinator = worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        captcha.clear(acc, old_id)
        captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new-state'})
        await coordinator.resolve(old_id, 'answer')
        submit.assert_not_called()
        assert captcha.current(acc)['id'] != old_id
    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize('temporary', [False, True])
def test_manager_resume(temporary):
    import threading
    from app.manager import BotManager
    state = SimpleNamespace(acc={'user_id': 'test-account', 'resume_hash': 'test-resume'},
                            _state_lock=threading.RLock(), _deleted=False, paused=True,
                            paused_reason='challenge', pending_apply=None, pending_applies={},
                            hard_stopped=False, limit_exceeded=False, cookies_expired=False,
                            consecutive_errors=3, _captcha_wake=threading.Event())
    manager = SimpleNamespace(account_states=[] if temporary else [state],
                              temp_states={0: state} if temporary else {}, _persist_pauses=Mock())
    BotManager.resume_challenge_account(manager, 'test-resume')
    assert state.paused is False and state.paused_reason is None
    assert state._captcha_wake.is_set()
    state.paused, state.paused_reason = True, 'auth'
    BotManager.resume_challenge_account(manager, 'test-account')
    assert state.paused is True and state.paused_reason == 'auth'


def test_shutdown(monkeypatch):
    monkeypatch.setattr(CONFIG, 'telegram_bot_token', 'test-placeholder')
    monkeypatch.setattr(CONFIG, 'telegram_chat_id', '-123')
    monkeypatch.setattr(CONFIG, 'telegram_captcha_enabled', True)
    async def run():
        started = asyncio.Event()
        fake = SimpleNamespace(start=AsyncMock(side_effect=started.set), stop=AsyncMock(), _task=True)
        monkeypatch.setattr(worker, 'TelegramCaptchaBot', lambda: fake)
        manager = SimpleNamespace(account_states=[], temp_states={})
        task = asyncio.create_task(worker.captcha_orchestrator(manager))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        fake.stop.assert_awaited_once()
        assert manager.telegram_captcha_bot is None
    asyncio.run(asyncio.wait_for(run(), 5))


def test_snapshot_hides_telegram_credentials(monkeypatch):
    from app.manager import BotManager
    monkeypatch.setattr(CONFIG, 'telegram_bot_token', 'test-placeholder')
    monkeypatch.setattr(CONFIG, 'telegram_chat_id', '-123')
    manager = BotManager()
    snapshot = manager.get_state_snapshot()
    assert snapshot['config']['telegram_bot_token_set'] is True
    assert 'telegram_bot_token' not in snapshot['config']
    assert 'telegram_chat_id' not in snapshot['config']


def test_failed_delivery_retries(monkeypatch):
    acc = {'user_id': 'test-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test-state'})
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={})
    monkeypatch.setattr(worker, 'fetch_captcha_image', Mock(return_value=(SimpleNamespace(), 'key', b'png', 'test-state', 'https://hh.ru/')))
    async def run():
        bot = Mock(push_challenge=AsyncMock(side_effect=[RuntimeError('offline'), {'message_id': 7}]))
        coordinator = worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        assert not coordinator._seen
        await coordinator.scan()
        assert len(coordinator.pending) == 1
    asyncio.run(asyncio.wait_for(run(), 5))

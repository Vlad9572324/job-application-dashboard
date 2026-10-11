import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from app import captcha, captcha_journal, captcha_llm, captcha_solver, telegram_notify
from app.config import CONFIG
from app.routes import accounts


@pytest.mark.parametrize('status,location,expected', [(302, 'https://hh.ru/account/login', False),
                                          (303, 'https://hh.ru/account/captcha?failed=1', False)])
def test_unconfirmed_response_never_success(status, location, expected):
    response = Mock(status_code=status, headers={'Location': location})
    response.json.side_effect = ValueError('HTML')
    session = Mock()
    session.post.return_value = response
    assert captcha_solver.submit_captcha(session, 'human', 'key', 'state')[0] is expected


def test_telegram_exception_cannot_log_token(monkeypatch):
    logs = []
    monkeypatch.setattr(telegram_notify, '_credentials', lambda: ('synthetic-secret', '123'))
    monkeypatch.setattr(telegram_notify, '_load_sent_events', lambda: {})
    monkeypatch.setattr(telegram_notify, 'log_debug', logs.append)
    monkeypatch.setattr(telegram_notify.requests, 'post', Mock(side_effect=RuntimeError(
        'https://api.telegram.org/botsynthetic-secret/sendMessage')))
    assert not telegram_notify.send_once('test', 'test')
    assert logs and all('synthetic-secret' not in line for line in logs)


@pytest.mark.parametrize('body', [[], {'text': 42}, {'text': 'human', 'id': 'stale', 'key': 'old'}])
def test_invalid_or_stale_ui_answer_never_submitted(monkeypatch, body):
    acc = {'user_id': 'synthetic-route'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    submit = Mock()
    fetch = Mock()
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: SimpleNamespace(acc=acc))
    async def run():
        coord = SimpleNamespace(_lock=asyncio.Lock(), gui_pending={cid: {
            'session': Mock(), 'captcha_key': 'current'}})
        monkeypatch.setattr(accounts.bot, 'telegram_captcha_coordinator', coord, raising=False)
        class Request:
            async def json(self): return body
        result = await accounts.api_account_captcha_solve(0, Request())
        assert result['ok'] is False
    asyncio.run(run())
    submit.assert_not_called()
    fetch.assert_not_called()
    assert captcha.current(acc)['id'] == cid


@pytest.fixture
def gui_flow(monkeypatch):
    from urllib.parse import urlsplit, parse_qs
    acc = {'user_id': 'gui-manual'}
    state = SimpleNamespace(acc=acc, _deleted=False, paused=True, paused_reason='challenge')
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    session = Mock()
    def fetch(acc, url):
        return session, 'key', b'png', 'state', parse_qs(urlsplit(url).query)['backurl'][0]
    monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', Mock(side_effect=fetch))
    monkeypatch.setattr(captcha_solver, 'verify_manual_completion', Mock(return_value=(False, 'unconfirmed_verification')))
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: state)
    resume = Mock()
    monkeypatch.setattr(accounts.bot, 'resume_challenge_account', resume)
    coord = SimpleNamespace(_lock=asyncio.Lock(), gui_pending={}, pending={})
    monkeypatch.setattr(accounts.bot, 'telegram_captcha_coordinator', coord, raising=False)
    request = SimpleNamespace(json=AsyncMock(return_value={'text': 'human', 'id': cid, 'key': 'key'}))
    return acc, cid, state, coord, request, session, resume


def test_local_confirmed_answer_resumes_once_and_cannot_be_replayed(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    request.json.return_value = {'id': cid, 'key': 'key'}
    recognize = Mock(return_value='клюёшь лунную')
    submit = Mock(return_value=(True, ''))
    save_sample = Mock()
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', recognize)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    monkeypatch.setattr(captcha_journal, 'save_sample', save_sample)
    monkeypatch.setattr(CONFIG, 'captcha_llm_solved', 0)
    async def run():
        await accounts.api_account_captcha_image(0)
        item = coord.gui_pending[cid]
        first = await accounts.api_account_captcha_solve_local(0, request)
        assert first['ok'] and first['confirmed'] and first['id'] == cid
        assert first['answer'] == 'клюёшь лунную'
        assert not captcha.current(acc) and cid not in coord.gui_pending
        assert not (await accounts.api_account_captcha_solve_local(0, request))['ok']
        submit.assert_called_once_with(session, 'клюёшь лунную', 'key', 'state',
                                       item['backurl'], item['failurl'], require_confirmation=True)
        assert item['backurl'] != item['failurl']
    asyncio.run(run())
    recognize.assert_called_once_with(b'png')
    resume.assert_called_once_with(captcha.account_key(acc))
    session.close.assert_called_once()
    save_sample.assert_called_once_with(b'png', 'клюёшь лунную', source='local')
    assert CONFIG.captcha_llm_solved == 1


@pytest.mark.parametrize('reason', ['isBot', 'unconfirmed_response', 'http_429'])
def test_local_rejected_or_unconfirmed_answer_stays_paused(gui_flow, monkeypatch, reason):
    acc, cid, state, coord, request, session, resume = gui_flow
    request.json.return_value = {'id': cid, 'key': 'key'}
    recognize = Mock(return_value='клюёшь лунную')
    submit = Mock(return_value=(False, reason))
    save_sample = Mock()
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', recognize)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    monkeypatch.setattr(captcha_journal, 'save_sample', save_sample)
    async def run():
        await accounts.api_account_captcha_image(0)
        first = await accounts.api_account_captcha_solve_local(0, request)
        assert not first['ok']
        if reason.startswith('unconfirmed'):
            assert first['unconfirmed']
        assert not (await accounts.api_account_captcha_solve_local(0, request))['ok']
    asyncio.run(run())
    recognize.assert_called_once_with(b'png')
    submit.assert_called_once()
    assert submit.call_args.kwargs['require_confirmation'] is True
    resume.assert_not_called()
    assert captcha.current(acc)['id'] == cid
    assert state.paused and state.paused_reason == 'challenge'
    # A rejected or uncertain prediction must never enter accepted-answer labels.
    save_sample.assert_called_once_with(b'png', 'клюёшь лунную', kind='local-rejected', source='local')
    if reason.startswith('unconfirmed'):
        captcha_solver.verify_manual_completion.assert_called_once()
    else:
        captcha_solver.verify_manual_completion.assert_not_called()


@pytest.mark.parametrize('field,value', [('id', 'stale'), ('key', 'old'),
                                        ('id', None), ('key', None)])
def test_local_stale_or_missing_identifiers_never_recognize_or_submit(gui_flow, monkeypatch, field, value):
    acc, cid, state, coord, request, session, resume = gui_flow
    body = {'id': cid, 'key': 'key'}
    body[field] = value
    request.json.return_value = body
    recognize, submit = Mock(), Mock()
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', recognize)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        assert not (await accounts.api_account_captcha_solve_local(0, request))['ok']
        assert not coord.gui_pending[cid].get('local_attempted')
        assert not coord.gui_pending[cid]['submitted']
    asyncio.run(run())
    recognize.assert_not_called()
    submit.assert_not_called()
    resume.assert_not_called()
    assert captcha.current(acc)['id'] == cid


def test_local_unreadable_image_still_accepts_manual_answer(gui_flow, monkeypatch):
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', False)
    acc, cid, state, coord, request, session, resume = gui_flow
    local_request = SimpleNamespace(json=AsyncMock(return_value={'id': cid, 'key': 'key'}))
    recognize = Mock(return_value=None)
    submit = Mock(return_value=(True, ''))
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', recognize)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        result = await accounts.api_account_captcha_solve_local(0, local_request)
        assert not result['ok'] and result['manual_available']
        assert not coord.gui_pending[cid]['submitted']
        submit.assert_not_called()
        session.close.assert_not_called()
        assert not (await accounts.api_account_captcha_solve_local(0, local_request))['ok']
        manual_result = await accounts.api_account_captcha_solve(0, request)
        assert manual_result['ok'] and manual_result['requires_confirmation']
    asyncio.run(run())
    recognize.assert_called_once_with(b'png')
    submit.assert_called_once()
    assert submit.call_args.args[1] == 'human'
    assert submit.call_args.kwargs['require_confirmation'] is True


@pytest.mark.parametrize('reason,delay', [('isBot', 5), ('http_429', 180), ('recaptcha', None)])
def test_local_gui_failure_returns_ownership_to_worker_with_cooldown(gui_flow, monkeypatch, reason, delay):
    import time
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value='тест слова'))
    monkeypatch.setattr(captcha_solver, 'submit_captcha', Mock(return_value=(False, reason)))
    session.hh_captcha_retry_after = 180
    async def run():
        await accounts.api_account_captcha_image(0)
        record = captcha.current(acc)
        assert record['manual_only'] and record['auto_retry_until'] > time.time()
        result = await accounts.api_account_captcha_solve_local(0, request)
        assert not result['ok'] and result['answer'] == 'тест слова'
        assert result['auto_retry'] is (delay is not None)
        record = captcha.current(acc)
        assert not record.get('manual_only')
        assert record['local_retry_reason'] == reason and record['local_attempts'] == 1
        assert coord.gui_pending[cid]['submitted']
        if reason == 'isBot':
            assert coord.pending[cid]['session'] is session
            assert coord.pending[cid]['captcha_key'] is None
            assert coord.gui_pending[cid]['session'] is None
            session.close.assert_not_called()
        else:
            assert cid not in coord.pending
            session.close.assert_called_once()
        if delay:
            assert delay - 2 <= record['local_retry_at'] - time.time() <= delay
        if reason == 'http_429':
            captcha_solver.fetch_captcha_image.reset_mock()
            assert not (await accounts.api_account_captcha_image(0))['ok']
            captcha_solver.fetch_captcha_image.assert_not_called()
        assert not (await accounts.api_account_captcha_solve_local(0, request))['ok']
    asyncio.run(run())
    captcha_solver.submit_captcha.assert_called_once()
    resume.assert_not_called()


@pytest.mark.parametrize('next_state,expected_state', [('updated state/+==', 'updated state/+=='),
                                                       (None, 'state')])
def test_local_gui_rejection_hands_same_session_to_fresh_worker_attempt(gui_flow, monkeypatch, next_state, expected_state):
    from app import captcha_worker
    from app.captcha_worker import CaptchaCoordinator
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value='first answer'))
    monkeypatch.setattr(captcha_solver, 'submit_captcha', Mock(return_value=(False, 'isBot')))
    session.hh_captcha_next_state = next_state
    old_session = Mock()
    coord.pending[cid] = {'session': old_session, 'captcha_key': 'old-pending-key'}
    worker_recognize = Mock(return_value='second answer')
    worker_submit = Mock(return_value=(True, ''))
    worker_fetch = Mock()
    refresh = Mock()
    monkeypatch.setattr(captcha_worker, 'recognize_captcha', worker_recognize)
    monkeypatch.setattr(captcha_worker, 'submit_captcha', worker_submit)
    monkeypatch.setattr(captcha_worker, 'fetch_captcha_image', worker_fetch)
    monkeypatch.setattr(captcha_worker, 'refresh_captcha_image', refresh)
    async def run():
        await accounts.api_account_captcha_image(0)
        gui = coord.gui_pending[cid]
        backurl, created = gui['backurl'], gui['created']
        result = await accounts.api_account_captcha_solve_local(0, request)
        assert result['auto_retry']
        pending = coord.pending[cid]
        assert pending['automatic'] and pending['session'] is session
        assert pending['captcha_state'] == expected_state
        assert pending['backurl'] == backurl and pending['session_started'] == created
        assert pending['captcha_key'] is None and 'image' not in pending
        assert pending['llm_result']['answer'] == 'first answer'
        assert gui['session'] is None and gui['captcha_key'] is None
        old_session.close.assert_called_once()
        session.close.assert_not_called()
        refresh.return_value = (session, 'fresh-key', b'fresh-image', expected_state, backurl)
        manager = SimpleNamespace(account_states=[state], temp_states={}, resume_challenge_account=resume)
        telegram = SimpleNamespace(forget=Mock(), send_message=AsyncMock())
        worker = CaptchaCoordinator(manager, telegram)
        worker.pending = coord.pending
        worker.gui_pending = coord.gui_pending
        await worker._local_attempt(cid, pending, acc, 2)
        refresh.assert_called_once_with(session, expected_state, backurl)
        worker_recognize.assert_called_once_with(b'fresh-image')
        assert worker_submit.call_args.args[:3] == (session, 'second answer', 'fresh-key')
        worker_fetch.assert_not_called()
        assert cid not in worker.pending and not captcha.current(acc)
    asyncio.run(run())
    session.close.assert_called_once()
    resume.assert_called_once_with(captcha.account_key(acc))


@pytest.mark.parametrize('outcome', ['disabled', 'superseded', 'deleted', 'exception', 'coordinator_closed'])
def test_local_gui_session_not_handed_off_after_ineligible_rejection(gui_flow, monkeypatch, outcome):
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', outcome != 'disabled')
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value='answer'))
    def submit(*args, **kwargs):
        assert coord.gui_pending[cid]['session'] is None
        session.close.assert_not_called()
        if outcome == 'coordinator_closed':
            coord.gui_pending.clear()
        if outcome == 'superseded':
            captcha.clear(acc, cid)
            captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new'})
        if outcome == 'deleted':
            state._deleted = True
        if outcome == 'exception':
            raise TimeoutError()
        return False, 'isBot'
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        assert not (await accounts.api_account_captcha_solve_local(0, request))['ok']
        assert cid not in coord.pending
    asyncio.run(run())
    session.close.assert_called_once()
    resume.assert_not_called()


def test_local_gui_journal_error_closes_session(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value='answer'))
    monkeypatch.setattr(captcha_solver, 'submit_captcha', Mock(return_value=(False, 'isBot')))
    async def run():
        await accounts.api_account_captcha_image(0)
        monkeypatch.setattr(captcha_journal, 'record', Mock(side_effect=OSError('journal unavailable')))
        with pytest.raises(OSError):
            await accounts.api_account_captcha_solve_local(0, request)
        assert cid not in coord.pending
    asyncio.run(run())
    session.close.assert_called_once()


def test_unreadable_gui_image_is_released_for_new_local_attempt(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value=None))
    submit = Mock()
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        result = await accounts.api_account_captcha_solve_local(0, request)
        assert result['auto_retry'] and result['retry_seconds'] == 30
        assert not captcha.current(acc).get('manual_only')
        assert coord.gui_pending[cid]['submitted']
    asyncio.run(run())
    session.close.assert_called_once()
    submit.assert_not_called()
    resume.assert_not_called()
    resume.assert_not_called()
    assert captcha.current(acc)['id'] == cid


@pytest.mark.parametrize('result', [(True, ''), (False, 'unconfirmed_response'),
                                   (False, 'isBot'), (False, 'http_429')])
def test_gui_single_submission_never_auto_resumes(gui_flow, monkeypatch, result):
    acc, cid, state, coord, request, session, resume = gui_flow
    submit = Mock(return_value=result)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        first = await accounts.api_account_captcha_solve(0, request)
        second = await accounts.api_account_captcha_solve(0, request)
        assert first['ok'] is result[0]
        assert not second['ok']
        if result[0]:
            assert first['requires_confirmation'] and first['id'] == cid
    asyncio.run(run())
    submit.assert_called_once()
    assert submit.call_args.kwargs['require_confirmation'] is True
    assert 'manual_captcha_return=' in submit.call_args.args[4]
    resume.assert_not_called()
    assert captcha.current(acc)['manual_only']
    assert state.paused and state.paused_reason == 'challenge'
    if result[1] == 'http_429':
        captcha_solver.verify_manual_completion.assert_not_called()


def test_gui_timeout_never_replays(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    submit = Mock(side_effect=TimeoutError())
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        assert (await accounts.api_account_captcha_solve(0, request))['unconfirmed']
        assert not (await accounts.api_account_captcha_solve(0, request))['ok']
    asyncio.run(run())
    submit.assert_called_once()
    resume.assert_not_called()


def test_gui_expired_image_is_not_submitted(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    submit = Mock()
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        coord.gui_pending[cid]['created'] -= 601
        assert not (await accounts.api_account_captcha_solve(0, request))['ok']
    asyncio.run(run())
    submit.assert_not_called()


@pytest.mark.parametrize('mode', ['local', 'local-auto-off', 'manual'])
def test_gui_waits_for_image_deadline_before_sending_answer(gui_flow, monkeypatch, mode):
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', mode != 'local-auto-off')
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value='answer'))
    deadline = Mock(return_value=7.5)
    monkeypatch.setattr(captcha_solver, 'captcha_submit_delay', deadline)
    waited = []
    async def wait(delay):
        assert coord.gui_pending[cid]['session'] is None
        assert coord._lock.locked()
        session.close.assert_not_called()
        waited.append(delay)
    monkeypatch.setattr(accounts.asyncio, 'sleep', wait)
    def submit(*args, **kwargs):
        assert waited == [7.5]
        return True, ''
    send = Mock(side_effect=submit)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', send)
    async def run():
        await accounts.api_account_captcha_image(0)
        solve = accounts.api_account_captcha_solve if mode == 'manual' else accounts.api_account_captcha_solve_local
        result = await solve(0, request)
        assert result['ok']
    asyncio.run(run())
    deadline.assert_called_once_with(session)
    send.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize('change', ['superseded', 'deleted', 'expired', 'disabled',
                                    'owner-replaced', 'coordinator-replaced'])
def test_gui_wait_rechecks_ownership_before_post(gui_flow, monkeypatch, change):
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value='answer'))
    monkeypatch.setattr(captcha_solver, 'captcha_submit_delay', lambda _: 5)
    submit = Mock()
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def wait(delay):
        assert coord.gui_pending[cid]['session'] is None
        if change == 'superseded':
            captcha.clear(acc, cid)
            captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new'})
        elif change == 'deleted':
            state._deleted = True
        elif change == 'expired':
            coord.gui_pending[cid]['created'] -= 601
        elif change == 'disabled':
            CONFIG.captcha_llm_enabled = False
        elif change == 'owner-replaced':
            coord.gui_pending[cid] = {}
        else:
            monkeypatch.setattr(accounts.bot, 'telegram_captcha_coordinator', SimpleNamespace())
    monkeypatch.setattr(accounts.asyncio, 'sleep', wait)
    async def run():
        await accounts.api_account_captcha_image(0)
        result = await accounts.api_account_captcha_solve_local(0, request)
        assert not result['ok'] and result['auto_retry'] is False
        assert cid not in coord.pending
    asyncio.run(run())
    submit.assert_not_called()
    resume.assert_not_called()
    session.close.assert_called_once()


def test_cancelling_gui_deadline_wait_closes_session_without_post(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value='answer'))
    monkeypatch.setattr(captcha_solver, 'captcha_submit_delay', lambda _: 10)
    submit = Mock()
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        waiting = asyncio.Event()
        async def wait(delay):
            waiting.set()
            await asyncio.Future()
        monkeypatch.setattr(accounts.asyncio, 'sleep', wait)
        await accounts.api_account_captcha_image(0)
        work = asyncio.create_task(accounts.api_account_captcha_solve_local(0, request))
        await asyncio.wait_for(waiting.wait(), 1)
        assert coord.gui_pending[cid]['session'] is None
        session.close.assert_not_called()
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        assert captcha.current(acc)['id'] == cid and cid not in coord.pending
    asyncio.run(run())
    submit.assert_not_called()
    resume.assert_not_called()
    session.close.assert_called_once()


def test_gui_confirmation_uses_guarded_continue_and_preserves_global_pause(gui_flow, monkeypatch):
    import threading
    acc, cid, state, coord, request, session, resume = gui_flow
    state._state_lock = threading.RLock()
    state.pending_apply = None
    state.pending_applies = {}
    state.hard_stopped = state.limit_exceeded = state.cookies_expired = False
    state.consecutive_errors = 1
    monkeypatch.setattr(accounts.bot, 'paused', True)
    persist = Mock()
    monkeypatch.setattr(accounts.bot, '_persist_pauses', persist)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', Mock(return_value=(True, '')))
    async def run():
        await accounts.api_account_captcha_image(0)
        assert (await accounts.api_account_captcha_solve(0, request))['requires_confirmation']
        assert state.paused
        confirmation = SimpleNamespace(json=AsyncMock(return_value={'id': cid, 'confirmed': True}))
        assert (await accounts.api_account_captcha_continue(0, confirmation))['ok']
    asyncio.run(run())
    assert not state.paused and not captcha.current(acc)
    assert accounts.bot.paused
    persist.assert_called_once_with(wait=True)
    resume.assert_not_called()


def test_gui_failed_refresh_keeps_previous_session(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    async def run():
        await accounts.api_account_captcha_image(0)
        previous = coord.gui_pending[cid]
        monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', Mock(side_effect=TimeoutError()))
        assert not (await accounts.api_account_captcha_image(0))['ok']
        assert coord.gui_pending[cid] is previous
        session.close.assert_not_called()
    asyncio.run(run())


def test_gui_stale_success_does_not_confirm_replacement(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    def submit(*args, **kwargs):
        captcha.clear(acc, cid)
        captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new'})
        return True, ''
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        result = await accounts.api_account_captcha_solve(0, request)
        assert not result['ok'] and 'изменилась' in result['error']
    asyncio.run(run())
    assert captcha.current(acc)['id'] != cid
    resume.assert_not_called()


@pytest.mark.parametrize('stage', ['fetch', 'submit', 'local-submit'])
def test_cancelled_gui_request_closes_session_after_thread_finishes(gui_flow, monkeypatch, stage):
    import threading
    acc, cid, state, coord, request, session, resume = gui_flow
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(captcha_llm, 'recognize_captcha', Mock(return_value='answer'))
    release = threading.Event()
    async def run():
        started, closed = asyncio.Event(), asyncio.Event()
        loop = asyncio.get_running_loop()
        session.close.side_effect = lambda: loop.call_soon_threadsafe(closed.set)
        def operation(*args, **kwargs):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(2)
            return ((session, 'key', b'png', 'state', 'https://hh.ru/')
                    if stage == 'fetch' else (False, 'isBot') if stage == 'local-submit' else (True, ''))
        if stage in ('submit', 'local-submit'):
            await accounts.api_account_captcha_image(0)
            monkeypatch.setattr(captcha_solver, 'submit_captcha', operation)
            solve = accounts.api_account_captcha_solve_local if stage == 'local-submit' else accounts.api_account_captcha_solve
            work = asyncio.create_task(solve(0, request))
        else:
            monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', operation)
            work = asyncio.create_task(accounts.api_account_captcha_image(0))
        await asyncio.wait_for(started.wait(), 1)
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        session.close.assert_not_called()
        assert cid not in coord.gui_pending
        release.set()
        await asyncio.wait_for(closed.wait(), 1)
        assert captcha.current(acc)['id'] == cid
    try:
        asyncio.run(run())
    finally:
        release.set()
    session.close.assert_called_once()
    resume.assert_not_called()


def test_gui_refresh_replaces_key_without_changing_telegram(monkeypatch):
    acc = {'user_id': 'gui-refresh'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    sessions = [Mock(), Mock()]
    fetch = Mock(side_effect=[(sessions[0], 'key-1', b'png1', 'state', 'https://hh.ru/'),
                              (sessions[1], 'key-2', b'png2', 'state', 'https://hh.ru/')])
    monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: SimpleNamespace(acc=acc))
    async def run():
        tg = {'captcha_key': 'tg-key', 'session': Mock()}
        coord = SimpleNamespace(_lock=asyncio.Lock(), pending={cid: tg})
        monkeypatch.setattr(accounts.bot, 'telegram_captcha_coordinator', coord, raising=False)
        first = await accounts.api_account_captcha_image(0)
        second = await accounts.api_account_captcha_image(0)
        assert first.headers['X-Captcha-Key'] == 'key-1'
        assert second.headers['X-Captcha-Key'] == 'key-2'
        assert coord.gui_pending[cid]['backurl'] == 'https://hh.ru/'
        assert coord.gui_pending[cid]['failurl'] != coord.gui_pending[cid]['backurl']
        sessions[0].close.assert_called_once()
        assert coord.pending[cid] is tg and tg['captcha_key'] == 'tg-key'
    asyncio.run(run())

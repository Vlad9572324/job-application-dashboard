"""Local captcha recognition and coordinator auto-submit regressions."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import captcha, captcha_llm, captcha_worker, llm
from app.config import CONFIG


@pytest.fixture
def vision(monkeypatch):
    monkeypatch.setattr(CONFIG, 'llm_profiles', [dict(api_key='test', base_url='https://api.openai.com/v1')])
    monkeypatch.setattr(CONFIG, 'llm_api_key', '')
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(CONFIG, 'captcha_llm_solved', 0)
    monkeypatch.setattr(CONFIG, 'captcha_llm_forwarded', 0)
    client = Mock()
    client.with_options.return_value = client
    factory = Mock(return_value=client)
    monkeypatch.setattr(llm, '_make_openai_client', factory)
    return client, factory


@pytest.fixture
def local_predict(monkeypatch):
    model = object()
    predictor = SimpleNamespace(load_model=Mock(return_value=model),
                                predict_bytes=Mock(return_value='клюёшь лунную'))
    monkeypatch.setitem(sys.modules, 'app.captcha_predict', predictor)
    captcha_llm._local_model.cache_clear()
    yield predictor
    captcha_llm._local_model.cache_clear()


@pytest.mark.parametrize('content,expected', [
    ('клюёшь лунную', 'клюёшь лунную'), (' "Тернисто  Синтез" ', 'тернисто синтез'),
    ('abc123', None), ('одно', None), ('Извините, я не могу помочь с этим изображением.', None),
    ('', None), (None, None),
])
def test_local_reading_is_normalized_without_cloud(vision, local_predict, content, expected):
    local_predict.predict_bytes.return_value = content
    assert captcha_llm.recognize_captcha(b'png') == expected
    local_predict.load_model.assert_called_once_with()
    local_predict.predict_bytes.assert_called_once_with(b'png', local_predict.load_model.return_value)
    vision[1].assert_not_called()


def test_local_recognition_needs_no_api_credentials(vision, local_predict, monkeypatch):
    monkeypatch.setattr(CONFIG, 'llm_profiles', [])
    monkeypatch.setattr(CONFIG, 'llm_api_key', '')
    assert captcha_llm.recognize_captcha(b'png') == 'клюёшь лунную'
    local_predict.predict_bytes.assert_called_once()
    vision[1].assert_not_called()


@pytest.mark.parametrize('failing_step', ['load_model', 'predict_bytes'])
def test_local_failure_never_uses_cloud(vision, local_predict, failing_step):
    getattr(local_predict, failing_step).side_effect = RuntimeError('local model unavailable')
    assert captcha_llm.recognize_captcha(b'png') is None
    vision[1].assert_not_called()


def test_empty_image_does_not_load_or_call_model(vision, local_predict):
    assert captcha_llm.recognize_captcha(b'') is None
    local_predict.load_model.assert_not_called()
    local_predict.predict_bytes.assert_not_called()
    vision[1].assert_not_called()


def test_local_model_is_reused_between_images(vision, local_predict):
    assert captcha_llm.recognize_captcha(b'first') == 'клюёшь лунную'
    assert captcha_llm.recognize_captcha(b'second') == 'клюёшь лунную'
    local_predict.load_model.assert_called_once_with()
    assert local_predict.predict_bytes.call_count == 2
    vision[1].assert_not_called()


@pytest.mark.parametrize('answer,accepted', [('Ab123', True), ('Ab123', False), (None, False)])
def test_coordinator(vision, monkeypatch, answer, accepted):
    acc = {'user_id': 'vision-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={},
                              resume_challenge_account=Mock(), _add_log=Mock())
    session = Mock()
    fetch = Mock(return_value=(session, 'key', b'png', 'test', 'https://hh.ru/'))
    recognize = Mock(return_value=answer)
    submit = Mock(return_value=(accepted, 'isBot'))
    monkeypatch.setattr(captcha_worker, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(captcha_worker, 'recognize_captcha', recognize)
    monkeypatch.setattr(captcha_worker, 'submit_captcha', submit)
    async def run():
        bot = Mock(push_challenge=AsyncMock(return_value=True),
                   send_message=AsyncMock(return_value=None), connected=False)
        coordinator = captcha_worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        await coordinator.scan()
        recognize.assert_called_once_with(b'png')
        if accepted:
            assert not captcha.current(acc)
            assert cid not in coordinator.pending
            bot.push_challenge.assert_not_called()
            bot.send_message.assert_awaited_once()
            manager.resume_challenge_account.assert_called_once_with('vision-account')
            assert CONFIG.captcha_llm_solved == 1
        else:
            assert cid in coordinator.pending
            assert CONFIG.captcha_llm_forwarded == 0
            bot.push_challenge.assert_not_called()
            assert fetch.call_count == 1
            assert coordinator.pending[cid]['llm_result']['status'] == 'retry'
            assert coordinator.pending[cid]['llm_result']['retry_seconds'] == (5 if answer else 30)
            manager.resume_challenge_account.assert_not_called()
        if answer:
            submit.assert_called_once_with(
                session, answer, 'key', 'test', 'https://hh.ru/',
                'https://hh.ru/account/captcha?state=test&backurl=https%3A%2F%2Fhh.ru%2F',
                require_confirmation=True)
        else:
            submit.assert_not_called()
    asyncio.run(run())


def test_manual_delivery_retries_without_local_recognition(vision, monkeypatch):
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', False)
    acc = {'user_id': 'retry-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={})
    recognize = Mock(side_effect=RuntimeError('provider unavailable'))
    monkeypatch.setattr(captcha_worker, 'recognize_captcha', recognize)
    monkeypatch.setattr(captcha_worker, 'fetch_captcha_image', Mock(
        return_value=(Mock(), 'key', b'png', 'test', 'https://hh.ru/')))
    async def run():
        bot = Mock(push_challenge=AsyncMock(side_effect=[RuntimeError('offline'), True]))
        coordinator = captcha_worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        await coordinator.scan()
        assert bot.push_challenge.await_count == 1  # backoff: no hammering HH
        for item in coordinator.pending.values():
            assert item['retry_delay'] == 30
            item['retry_at'] = 0
        await coordinator.scan()
        recognize.assert_not_called()
        assert bot.push_challenge.await_count == 2
        assert CONFIG.captcha_llm_forwarded == 1
    asyncio.run(run())


def test_coordinator_exposes_llm_outcome_for_the_card(vision, monkeypatch):
    acc = {'user_id': 'card-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={},
                              resume_challenge_account=Mock(), _add_log=Mock())
    monkeypatch.setattr(captcha_worker, 'fetch_captcha_image', Mock(
        return_value=(Mock(), 'key', b'png', 'test', 'https://hh.ru/')))
    monkeypatch.setattr(captcha_worker, 'recognize_captcha', Mock(return_value=None))
    async def run():
        bot = Mock(push_challenge=AsyncMock(return_value=True), send_browser_option=AsyncMock())
        coordinator = captcha_worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        assert coordinator.pending[cid]['llm_result'] == {
            'status': 'retry', 'reason': 'model_unavailable', 'retry_seconds': 30}
        bot.push_challenge.assert_not_called()
    asyncio.run(run())

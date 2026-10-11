"""Manual-only CAPTCHA UX; every backend response is a local mock."""

from playwright.sync_api import expect
import base64


def paused_page(ui):
    ui.state['accounts'][0].update(paused=True, paused_reason='challenge')
    ui.state['config']['captcha_llm_enabled'] = False
    ui.open()
    ui.page.evaluate("""() => {
        const image = document.getElementById('acc-captcha-img-0');
        image.dataset.busy = '';
        image.dataset.challengeId = 'manual-test';
        image.dataset.challengeKey = 'one-use-key';
        captchaControlsBusy(0, false);
    }""")
    return ui.page


def test_confirmed_answer_requires_separate_explicit_continue(ui):
    page = paused_page(ui)
    page.route('**/api/account/0/captcha/solve', lambda route: route.fulfill(json={
        'ok': True, 'confirmed': True, 'requires_confirmation': True,
        'message': 'HH подтвердил ответ. Подтвердите продолжение отдельно.',
    }))
    requests = []

    def resume(route):
        requests.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'message': 'Продолжение разрешено вами'})

    page.route('**/api/account/0/captcha/continue', resume)
    page.locator('#acc-captcha-input-0').fill('human-entered-text')
    page.get_by_role('button', name='✓ Отправить').click()
    box = page.locator('#acc-captcha-result-0')
    expect(box).to_contain_text('HH подтвердил ответ')
    assert requests == []
    ui.push_state()
    expect(page.locator('#acc-captcha-0')).to_be_visible()
    button = box.get_by_role('button', name='Подтвердить продолжение откликов')
    page.once('dialog', lambda dialog: dialog.dismiss())
    button.click()
    assert requests == []
    page.once('dialog', lambda dialog: dialog.accept())
    button.click()
    expect(box).to_have_text('Продолжение разрешено вами')
    assert requests == [{'id': 'manual-test', 'confirmed': True}]


def test_invalid_response_is_unknown_and_answer_is_not_replayed(ui):
    page = paused_page(ui)
    requests = []

    def submit(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=502, content_type='text/html', body='<html>gateway</html>')

    page.route('**/api/account/0/captcha/solve', submit)
    page.locator('#acc-captcha-input-0').fill('human-entered-text')
    page.get_by_role('button', name='✓ Отправить').click()
    expect(page.locator('#acc-captcha-result-0')).to_contain_text('Не удалось получить результат')
    expect(page.locator('#acc-captcha-result-0')).not_to_contain_text('JSON')
    page.get_by_role('button', name='✓ Отправить').click()
    expect(page.locator('#acc-captcha-result-0')).to_contain_text('уже отправлена или устарела')
    assert len(requests) == 1
    assert requests[0]['key'] == 'one-use-key'


def test_inflight_answer_blocks_refresh_and_duplicate_submit(ui):
    page = paused_page(ui)
    requests = []
    page.route('**/api/account/0/captcha/solve', lambda route: requests.append(route))
    page.locator('#acc-captcha-input-0').fill('human-entered-text')
    page.get_by_role('button', name='✓ Отправить').click()
    expect(page.locator('#acc-captcha-0')).to_have_attribute('aria-busy', 'true')
    expect(page.get_by_role('button', name='🔄 Другая')).to_be_disabled()
    expect(page.locator('#acc-captcha-input-0')).to_be_disabled()
    page.evaluate('void solveCaptcha(0); void loadCaptchaImg(0); void loadAccountCaptcha(0);')
    assert len(requests) == 1
    requests[0].fulfill(json={'ok': False, 'unconfirmed': True})
    expect(page.locator('#acc-captcha-result-0')).to_contain_text('Результат неизвестен')
    expect(page.get_by_role('button', name='🔄 Другая')).to_be_enabled()


def test_blank_answer_has_actionable_feedback(ui):
    page = paused_page(ui)
    page.get_by_role('button', name='✓ Отправить').click()
    expect(page.locator('#acc-captcha-result-0')).to_contain_text('Введите текст с картинки')
    expect(page.locator('#acc-captcha-input-0')).to_be_focused()
    assert not any(call['path'].endswith('/captcha/solve') for call in ui.calls)


def test_new_image_focuses_answer_after_loading_finishes(ui):
    page = paused_page(ui)
    pixel = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6SAAAAABJRU5ErkJggg==')
    page.route('**/api/account/0/captcha/image?*', lambda route: route.fulfill(
        body=pixel, content_type='image/png', headers={'X-Captcha-Id': 'test-new', 'X-Captcha-Key': 'key-new'}))
    page.get_by_role('button', name='🔄 Другая').click()
    expect(page.locator('#acc-captcha-input-0')).to_be_focused()
    expect(page.locator('#acc-captcha-0')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('#acc-captcha-img-0')).to_have_attribute('data-challenge-key', 'key-new')


def test_pace_settings_do_not_claim_save_while_disconnected(ui):
    ui.open()
    ui.page.locator('.tab[data-tab="settings"]').click()
    ui.page.locator('#hp-human_apply_delay_min').fill('30')
    ui.page.evaluate("""() => {
        const connection = State.ws;
        State.ws = {readyState: 3};
        applyHumanSettings();
        State.ws = connection;
    }""")
    expect(ui.page.locator('#human-settings-status')).to_contain_text('Настройки не отправлены')
    assert not any(cmd.get('type') == 'set_config' for cmd in ui.commands)
    ui.push_state()
    expect(ui.page.locator('#hp-human_apply_delay_min')).to_have_value('30')


def test_pace_settings_wait_for_server_ack_and_explain_actual_limits(ui):
    ui.state['config'].update(human_mode_enabled=True, human_active_hours='07-24',
                              human_apply_delay_min=5, human_apply_delay_max=20)
    ui.open()
    ui.page.locator('.tab[data-tab="settings"]').click()
    expect(ui.page.locator('#human-preview')).to_contain_text('15.0 мин')
    ui.page.locator('#hp-human_apply_delay_max').fill('1800')
    ui.page.get_by_role('button', name='✅ Применить ограничения темпа').click()
    expect(ui.page.locator('#human-settings-status')).to_contain_text('ожидаю подтверждения')
    ui.push_state()
    expect(ui.page.locator('#human-settings-status')).to_contain_text('ожидаю подтверждения')
    expect(ui.page.locator('#hp-human_apply_delay_max')).to_have_value('1800')
    ui.state['config']['human_apply_delay_max'] = 1800
    ui.push_state()
    expect(ui.page.locator('#human-settings-status')).to_have_text('✓ Настройки сохранены сервером')
    expect(ui.page.locator('#human-preview')).to_contain_text('30.0 мин')


def test_blank_pace_delay_is_not_silently_saved_as_zero(ui):
    ui.open()
    ui.page.locator('.tab[data-tab="settings"]').click()
    ui.page.locator('#hp-human_apply_delay_min').fill('')
    expect(ui.page.locator('#human-preview')).to_contain_text('Укажите обе задержки')
    ui.page.get_by_role('button', name='✅ Применить ограничения темпа').click()
    expect(ui.page.locator('#human-settings-status')).to_contain_text('Введите неотрицательные')
    assert not any(cmd.get('type') == 'set_config' for cmd in ui.commands)

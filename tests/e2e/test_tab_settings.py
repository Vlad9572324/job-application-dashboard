"""E2E: вкладка «⚙️ Настройки» (subagent_5).

Зоны покрытия:
- рендер настроек из state["config"] (слайдеры SETTINGS_DEF / чекбоксы / селекты / LLM-профили);
- toggle-чекбоксы → WS sendCmd {type:'set_config', key, value} (ассерт по ui.commands);
- applySettings() → 9 set_config по всем слайдерам сразу;
- LLM profiles editor: добавление, удаление, РЕГРЕССИЯ 8bfea62 (api_key не
  стирается при смене model — проверяется на уровне исходящего POST /api/llm_profiles);
- runtime proxy editor: рендер из lazy GET /api/proxy/info (ui.data["proxy_info"]),
  POST /api/proxy/set, ошибка/откат при ok:false и при HTTP 500.

ОТКЛОНЕНИЯ ОТ ТЗ (фичи не существует в UI — заменено реальными, grep по static/):
- chat_deduplication (3 уровня) — в UI нет; заменено селектом рода
  #cfg-llm-applicant-gender (female/male/neutral — ровно 3 значения, onchange
  шлёт set_config llm_applicant_gender).
- temp_skip-флаги — это внутрянка бэкенда (state._llm_temp_skip), в настройках
  их нет; заменены чекбоксами auto_apply_tests / skip_inconsistent.
- «ввод мусора в прокси → запрос не уходит»: в app.js нет клиентской валидации,
  proxySave() шлёт ЛЮБОЙ url; реальный fail-path — это ok:false / HTTP 500 от
  сервера (тесты test_proxy_save_rejected_* и test_proxy_save_http_500_*), плюс
  очистка поля (пусто = напрямую) в test_proxy_save_empty_url_clears_proxy.

WS-команды и HTTP-перехваты наблюдаются только в python-списках ui.commands /
ui.calls, поэтому для них используется bounded-polling (_wait_until) — это
auto-wait с дедлайном, а не слепой sleep; для DOM — только expect/locator.
"""

from playwright.sync_api import expect

# Ключи SETTINGS_DEF (app.js) — по ним applySettings() шлёт set_config.
SETTINGS_KEYS = [
    "pages_per_url",
    "response_delay",
    "pause_between_cycles",
    "batch_responses",
    "limit_check_interval",
    "min_salary",
    "min_employer_rating",
    "min_recommendations_percent",
    "auto_pause_errors",
]

FILTERS_SECTION_SUMMARY = "Фильтры и автоматизация"


# ── helpers ────────────────────────────────────────────────────────────────

def _wait_until(ui, predicate, timeout=6.0, interval=0.05, message="condition"):
    """Bounded polling (auto-wait) для python-списков ui.commands/ui.calls.

    ВАЖНО: поллинг идёт через ui.wait_until → page.wait_for_timeout, а не
    time.sleep: обработчики page.route (sync API) крутятся только пока
    playwright качает события. На чистом time.sleep второй fetch внутри
    llmSave (POST /api/llm_config) зависал навсегда — route не fulfill'ился.
    """
    try:
        ui.wait_until(predicate, timeout=timeout, interval=interval, message="ok")
    except AssertionError:
        raise AssertionError(f"timeout {timeout}s waiting for {message}")


def _seed(ui, config=None, data=None):
    """Дополняем снапшот минимумом ключей, чтобы renderAll не споткнулся.

    setdefault — не затираем дефолты, которые уже выставил conftest.
    """
    state = ui.state
    for key, default in (
        ("accounts", []),
        ("log", []),
        ("recent_responses", []),
        ("llm_log", []),
        ("paused", False),
        ("uptime_seconds", 0),
    ):
        state.setdefault(key, default)
    state.setdefault(
        "global_stats",
        {"total_found": 0, "total_sent": 0, "storage_total": 0, "storage_tests": 0},
    )
    cfg = state.get("config")
    if not isinstance(cfg, dict):
        cfg = {}
        state["config"] = cfg
    cfg.update(config or {})
    if data:
        ui.data.update(data)
    return cfg


def _open_settings_tab(page):
    page.locator('.tab[data-tab="settings"]').click()
    expect(page.locator("#panel-settings")).to_be_visible()


def _open_filters_section(page):
    """Секция «Фильтры и автоматизация» — <details> без open, раскрываем."""
    page.locator("#panel-settings summary", has_text=FILTERS_SECTION_SUMMARY).click()
    expect(page.locator("#use-oauth-apply")).to_be_visible()


def _boot(ui, config=None, data=None):
    _seed(ui, config=config, data=data)
    ui.open()
    _open_settings_tab(ui.page)
    return ui.page


def _set_config_cmds(ui, key=None):
    return [
        c
        for c in ui.commands
        if isinstance(c, dict)
        and c.get("type") == "set_config"
        and (key is None or c.get("key") == key)
    ]


def _wait_set_config(ui, key, value, timeout=6.0):
    try:
        _wait_until(
            ui,
            lambda: any(
                c.get("value") == value for c in _set_config_cmds(ui, key)
            ),
            timeout=timeout,
            message=f"WS set_config {key}={value!r}",
        )
    except AssertionError:
        raise AssertionError(
            f"WS set_config {key}={value!r} не пришёл за {timeout}s; "
            f"получено: {_set_config_cmds(ui, key)}"
        )
    return next(c for c in _set_config_cmds(ui, key) if c.get("value") == value)


def _http_calls(ui, method, path_sub):
    return [
        c
        for c in ui.calls
        if c.get("method") == method and path_sub in (c.get("path") or "")
    ]


def _wait_http_call(ui, method, path_sub, timeout=6.0):
    try:
        _wait_until(
            ui,
            lambda: _http_calls(ui, method, path_sub),
            timeout=timeout,
            message=f"HTTP {method} {path_sub}",
        )
    except AssertionError:
        raise AssertionError(
            f"HTTP {method} {path_sub} не пришёл за {timeout}s; "
            f"все calls: {[(c.get('method'), c.get('path')) for c in ui.calls]}"
        )
    return _http_calls(ui, method, path_sub)


# ── 1. рендер из state["config"] ───────────────────────────────────────────

def test_settings_render_from_state_config(ui):
    _boot(
        ui,
        config={
            "pages_per_url": 30,
            "response_delay": 4,
            "min_salary": 60000,
            "llm_auto_send": False,
            "llm_use_quick_replies": True,
            "llm_applicant_gender": "male",
            "search_period_days": 7,
            "llm_profiles": [
                {
                    "name": "DeepSeek",
                    "api_key": "secret123",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "enabled": True,
                }
            ],
        },
    )
    page = ui.page

    # слайдеры SETTINGS_DEF: значение input + подсказка sv-*
    expect(page.locator("#sr-pages_per_url")).to_have_value("30")
    expect(page.locator("#sv-pages_per_url")).to_have_text("30")
    expect(page.locator("#sr-response_delay")).to_have_value("4")
    expect(page.locator("#sr-min_salary")).to_have_value("60000")

    # чекбоксы в открытой секции LLM
    expect(page.locator("#llm-auto-send")).not_to_be_checked()
    expect(page.locator("#llm-use-quick-replies")).to_be_checked()

    # селекты в закрытой секции «Фильтры и автоматизация»
    _open_filters_section(page)
    expect(page.locator("#cfg-llm-applicant-gender")).to_have_value("male")
    expect(page.locator("#search-period")).to_have_value("7")

    # профиль LLM отрисован из config.llm_profiles
    row = page.locator(".llm-profile-row")
    expect(row).to_have_count(1)
    expect(row.locator(".lp-name")).to_have_value("DeepSeek")
    expect(row.locator(".lp-model")).to_have_value("deepseek-chat")
    expect(row.locator(".lp-url")).to_have_value("https://api.deepseek.com")


# ── 2-5. toggle-чекбоксы → set_config через WS ─────────────────────────────

def test_toggle_use_oauth_apply_sends_set_config(ui):
    page = _boot(ui, config={"use_oauth_apply": False})
    _open_filters_section(page)
    cb = page.locator("#use-oauth-apply")
    expect(cb).not_to_be_checked()

    cb.click()  # False → True
    _wait_set_config(ui, "use_oauth_apply", True)

    cb.click()  # True → False (инверсия в обе стороны)
    _wait_set_config(ui, "use_oauth_apply", False)


def test_toggle_llm_use_quick_replies_sends_set_config(ui):
    page = _boot(ui, config={"llm_use_quick_replies": True})
    cb = page.locator("#llm-use-quick-replies")
    expect(cb).to_be_checked()

    cb.click()
    cmd = _wait_set_config(ui, "llm_use_quick_replies", False)
    assert cmd == {"type": "set_config", "key": "llm_use_quick_replies", "value": False}


def test_toggle_llm_auto_send_sends_set_config(ui):
    page = _boot(ui, config={"llm_auto_send": False})
    cb = page.locator("#llm-auto-send")
    expect(cb).not_to_be_checked()

    cb.click()
    _wait_set_config(ui, "llm_auto_send", True)


def test_toggle_auto_apply_tests_and_skip_inconsistent(ui):
    """Замена temp_skip-флагов (их нет в UI): auto_apply_tests + skip_inconsistent."""
    page = _boot(
        ui, config={"auto_apply_tests": False, "skip_inconsistent": True}
    )
    _open_filters_section(page)

    at = page.locator("#auto-apply-tests")
    expect(at).not_to_be_checked()
    at.click()
    _wait_set_config(ui, "auto_apply_tests", True)

    si = page.locator("#skip-inconsistent")
    expect(si).to_be_checked()
    si.click()
    _wait_set_config(ui, "skip_inconsistent", False)


# ── 6. три уровня (замена chat_deduplication): род соискателя ──────────────

def test_applicant_gender_three_levels_send_set_config(ui):
    page = _boot(ui, config={"llm_applicant_gender": "female"})
    _open_filters_section(page)
    sel = page.locator("#cfg-llm-applicant-gender")
    expect(sel).to_have_value("female")

    for value in ("male", "neutral", "female"):
        sel.select_option(value=value)
        _wait_set_config(ui, "llm_applicant_gender", value)


def test_saved_questionnaire_preset_previews_gender_without_rewriting_source(ui):
    original = "Да, работала с CRM-системами и 1С."
    male = "Да, работал с CRM-системами и 1С."
    neutral = "Да, есть опыт работы с CRM-системами и 1С."
    page = _boot(ui, config={
        "llm_applicant_gender": "male",
        "questionnaire_templates": [{"keywords": ["crm"], "answer": original}],
        "questionnaire_preset_previews": {original: male},
    })
    page.locator("#panel-settings summary", has_text="Шаблонные ответы на опросы").click()
    answer = page.locator("#q-templates-list .q-answer-input")
    expect(answer).to_have_value(male)
    assert page.evaluate("qReadTemplates()[0].answer") == original

    ui.state["config"]["llm_applicant_gender"] = "neutral"
    ui.state["config"]["questionnaire_preset_previews"] = {original: neutral}
    ui.push_state()
    expect(answer).to_have_value(neutral)
    assert page.evaluate("qReadTemplates()[0].answer") == original

    answer.fill("Мой собственный ответ.")
    ui.state["config"]["questionnaire_preset_previews"] = {original: male}
    ui.push_state()
    expect(answer).to_have_value("Мой собственный ответ.")


# ── 7. applySettings(): все слайдеры одним кликом ──────────────────────────

def test_apply_settings_sends_set_config_for_all_sliders(ui):
    cfg_values = {
        "pages_per_url": 25,
        "response_delay": 2,
        "pause_between_cycles": 60,
        "batch_responses": 3,
        "limit_check_interval": 15,
        "min_salary": 50000,
        "min_employer_rating": 3.5,
        "min_recommendations_percent": 50,
        "auto_pause_errors": 5,
    }
    page = _boot(ui, config=dict(cfg_values))
    expect(page.locator("#sr-pages_per_url")).to_have_value("25")

    # двигаем один слайдер, остальные остаются как в config
    page.evaluate("document.getElementById('sr-pages_per_url').value = '45'")
    page.locator("#settings-apply").click()

    for key, value in cfg_values.items():
        expected = 45 if key == "pages_per_url" else value
        _wait_set_config(ui, key, expected)

    # все 9 ключей SETTINGS_DEF покрыты set_config-командами
    applied = {c["key"]: c["value"] for c in _set_config_cmds(ui)}
    assert set(SETTINGS_KEYS) <= set(applied)
    assert applied["pages_per_url"] == 45
    assert applied["min_employer_rating"] == 3.5


# ── 8-10. LLM profiles editor ──────────────────────────────────────────────

def test_llm_profile_add_posts_profiles(ui):
    # llm_profile_mode фиксируем явно — чтобы не зависеть от дефолтов conftest
    page = _boot(ui, config={"llm_profiles": [], "llm_profile_mode": "fallback"})
    page.locator("button", has_text="Добавить профиль вручную").click()

    row = page.locator(".llm-profile-row")
    expect(row).to_have_count(1)
    row.locator(".lp-name").fill("MyProfile")
    row.locator(".lp-key").fill("sk-test-abcd1234")
    row.locator(".lp-model").fill("gpt-4o-mini")
    row.locator(".lp-url").fill("https://api.openai.com/v1")

    page.locator("button[onclick^='llmSave']").click()

    call = _wait_http_call(ui, "POST", "/api/llm_profiles")[0]
    body = call["json"]
    assert body["mode"] == "fallback"
    assert body["profiles"] == [
        {
            "name": "MyProfile",
            "api_key": "sk-test-abcd1234",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "enabled": True,
        }
    ]


def test_llm_profile_remove_posts_remaining_profiles(ui):
    page = _boot(
        ui,
        config={
            "llm_profiles": [
                {
                    "name": "A",
                    "api_key": "key-a-12345",
                    "base_url": "https://a.example/v1",
                    "model": "model-a",
                    "enabled": True,
                },
                {
                    "name": "B",
                    "api_key": "key-b-67890",
                    "base_url": "https://b.example/v1",
                    "model": "model-b",
                    "enabled": True,
                },
            ]
        },
    )
    rows = page.locator(".llm-profile-row")
    expect(rows).to_have_count(2)

    # ✕ в шапке первой строки: remove() + reindex + autosave
    rows.nth(0).locator(".llm-profile-row-header .btn-sm").click()
    expect(rows).to_have_count(1)

    page.locator("button[onclick^='llmSave']").click()

    call = _wait_http_call(ui, "POST", "/api/llm_profiles")[0]
    profiles = call["json"]["profiles"]
    assert [p["name"] for p in profiles] == ["B"]
    assert profiles[0]["api_key"] == "key-b-67890"


def test_llm_profile_api_key_preserved_on_model_change(ui):
    """Регрессия 8bfea62: смена model не должна стирать api_key в исходящем payload."""
    page = _boot(
        ui,
        config={
            "llm_profiles": [
                {
                    "name": "OpenAI",
                    "api_key": "secret123",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini",
                    "enabled": True,
                }
            ]
        },
    )
    row = page.locator(".llm-profile-row")
    expect(row).to_have_count(1)
    # ключ отрисован в type=password из config — на нём строится сохранение
    expect(row.locator(".lp-key")).to_have_value("secret123")

    # меняем ТОЛЬКО model, ключ не трогаем
    row.locator(".lp-model").fill("gpt-4o")
    page.locator("button[onclick^='llmSave']").click()

    call = _wait_http_call(ui, "POST", "/api/llm_profiles")[0]
    sent = call["json"]["profiles"][0]
    assert sent["api_key"] == "secret123", "api_key стёрся при смене model (8bfea62)"
    assert sent["model"] == "gpt-4o"
    assert sent["base_url"] == "https://api.openai.com/v1"
    assert sent["name"] == "OpenAI"

    # legacy-путь /api/llm_config тоже уносит ключ первого профиля
    legacy = _wait_http_call(ui, "POST", "/api/llm_config")[0]
    assert legacy["json"]["api_key"] == "secret123"
    assert legacy["json"]["model"] == "gpt-4o"


# ── 11-15. Proxy editor ────────────────────────────────────────────────────

def test_proxy_section_renders_proxy_info(ui):
    _boot(
        ui,
        config={},
        data={
            "proxy_info": {
                "proxy": "socks5h://proxy.example:1080",
                "ip": "203.0.113.7",
                "impersonate": "chrome-124",
            }
        },
    )
    page = ui.page
    # auto-probe GET /api/proxy/info при загрузке страницы
    expect(page.locator("#proxy-url")).to_have_text("socks5h://proxy.example:1080")
    expect(page.locator("#proxy-ip")).to_have_text("203.0.113.7")
    expect(page.locator("#proxy-impersonate")).to_have_text("chrome-124")
    expect(page.locator("#proxy-url-input")).to_have_value("socks5h://proxy.example:1080")


def test_proxy_save_posts_url_and_applies(ui):
    page = _boot(
        ui, data={"proxy_info": {"proxy": "", "ip": "198.51.100.1", "impersonate": "нет"}}
    )
    ui.set_response(
        "POST",
        r"/api/proxy/set",
        {"ok": True, "proxy": "socks5h://new.example:1080", "ip": "203.0.113.9"},
    )
    page.locator("#proxy-url-input").fill("socks5h://new.example:1080")
    page.locator("button[onclick^='proxySave']").click()

    call = _wait_http_call(ui, "POST", "/api/proxy/set")[0]
    assert call["json"] == {"url": "socks5h://new.example:1080"}

    expect(page.locator("#proxy-url")).to_have_text("socks5h://new.example:1080")
    expect(page.locator("#proxy-ip")).to_have_text("203.0.113.9")
    expect(page.locator("#proxy-status")).to_contain_text("Применено")


def test_proxy_save_rejected_reverts_and_shows_error(ui):
    page = _boot(
        ui,
        data={"proxy_info": {"proxy": "http://old.example:8080", "ip": "198.51.100.1"}},
    )
    ui.set_response(
        "POST",
        r"/api/proxy/set",
        {"ok": False, "error": "probe timeout", "reverted_to": "http://old.example:8080"},
    )
    inp = page.locator("#proxy-url-input")
    inp.fill("socks5h://bad.example:1080")
    page.locator("button[onclick^='proxySave']").click()

    # запрос уходит (клиентской валидации в app.js нет), сервер отклоняет
    call = _wait_http_call(ui, "POST", "/api/proxy/set")[0]
    assert call["json"]["url"] == "socks5h://bad.example:1080"

    err = page.locator("#proxy-error")
    expect(err).to_be_visible()
    expect(err).to_contain_text("probe timeout")
    expect(err).to_contain_text("откат")
    # revert: input синхронизирован с реальным (старым) прокси
    expect(inp).to_have_value("http://old.example:8080")


def test_proxy_save_http_500_shows_error(ui):
    page = _boot(ui, data={"proxy_info": {"proxy": "", "ip": "?"}})
    ui.set_response("POST", r"/api/proxy/set", status=500)

    page.locator("#proxy-url-input").fill("socks5h://err.example:1080")
    page.locator("button[onclick^='proxySave']").click()

    _wait_http_call(ui, "POST", "/api/proxy/set")
    err = page.locator("#proxy-error")
    expect(err).to_be_visible()
    expect(err).to_contain_text("⚠️")


def test_proxy_save_empty_url_clears_proxy(ui):
    """Пустой url — штатный режим «напрямую», app.js шлёт {url: ''} без валидации."""
    page = _boot(
        ui,
        data={"proxy_info": {"proxy": "http://old.example:8080", "ip": "198.51.100.1"}},
    )
    ui.set_response(
        "POST", r"/api/proxy/set", {"ok": True, "proxy": "", "ip": "198.51.100.1"}
    )
    inp = page.locator("#proxy-url-input")
    expect(inp).to_have_value("http://old.example:8080")  # предзаполнен из proxy_info

    inp.fill("")
    page.locator("button[onclick^='proxySave']").click()

    call = _wait_http_call(ui, "POST", "/api/proxy/set")[0]
    assert call["json"] == {"url": ""}
    expect(page.locator("#proxy-url")).to_have_text("(нет — напрямую)")

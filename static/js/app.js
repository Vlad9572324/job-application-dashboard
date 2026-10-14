// ── i18n ──────────────────────────────────────────────────────
// Невалидный/протухший lang в localStorage не должен ломать UI всеми raw-ключами.
const _storedLang = localStorage.getItem('hh-lang');
let lang = (_storedLang === 'ru' || _storedLang === 'en') ? _storedLang : 'ru';

// ── API-key fetch wrapper ─────────────────────────────────────
// Если backend требует HH_BOT_API_KEY, прокидываем X-API-Key в каждый запрос.
// Поддерживаются 2 источника: ?key=... в URL → переносится в localStorage; либо вручную в localStorage.
(function() {
  const _urlParams = new URLSearchParams(location.search);
  const _urlKey = _urlParams.get('key');
  const apiKey = (_urlKey || localStorage.getItem('hh-api-key') || '').trim();
  if (apiKey) localStorage.setItem('hh-api-key', apiKey);
  // Ключ в query string → в history/bookmarks/sync → утечка. Убираем сразу
  // после чтения, оставляя остальные параметры (аудит 2026-08-17, critical).
  if (_urlKey && window.history && typeof window.history.replaceState === 'function') {
    _urlParams.delete('key');
    const q = _urlParams.toString();
    const clean = location.pathname + (q ? '?' + q : '') + location.hash;
    try { window.history.replaceState(null, '', clean); } catch (_) {}
  }
  if (!apiKey) return;
  const _origFetch = window.fetch.bind(window);
  window.fetch = (resource, init = {}) => {
    // КРИТИЧНО: шлём X-API-Key ТОЛЬКО на same-origin запросы.
    // Иначе fetch на cross-origin URL (например в каком-нибудь helper'е) утечёт ключ.
    let sameOrigin = true;
    try {
      const target = new URL(typeof resource === 'string' ? resource : resource.url, location.href);
      sameOrigin = target.origin === location.origin;
    } catch(_) {}
    if (!sameOrigin) return _origFetch(resource, init);
    const headers = new Headers(init.headers || {});
    if (!headers.has('X-API-Key')) headers.set('X-API-Key', apiKey);
    return _origFetch(resource, {...init, headers});
  };
})();

const T = {
  ru: {
    // Tabs
    tab_main: '📊 Главная',
    tab_log: '📜 Лог',
    tab_llm: '🤖 LLM Ответы',
    tab_applied: '✅ Отклики',
    tab_tests: '🧪 Тесты',
    tab_questionnaire_history: '🧾 История тестовых откликов',
    tab_db: '📂 База',
    tab_hh: '🎯 HH Статус',
    tab_views: '👁️ Просмотры',
    tab_apply: '🚀 Отклик',
    tab_settings: '⚙️ Настройки',
    // Header
    hdr_found: 'найдено',
    hdr_replies: 'откликов',
    hdr_in_db: 'в базе',
    hdr_tests: 'тестов',
    hdr_new_views: 'новых просм.',
    hdr_new_inv: 'новых приглаш.',
    hdr_shows: 'показов',
    btn_pause: '⏸ Пауза',
    btn_resume: '▶ Продолжить (все)',
    // Status badges
    status_idle: 'ОЖИДАНИЕ',
    status_collecting: 'СБОР ВАКАНСИЙ',
    status_applying: 'ОТПРАВКА ОТКЛИКОВ',
    status_limit: 'ЛИМИТ',
    status_waiting: 'ПАУЗА',
    status_checking: 'ПРОВЕРКА ЛИМИТА',
    status_inactive: 'НЕАКТИВНА',
    status_all_paused: '⏸ ВСЕ НА ПАУЗЕ',
    status_acc_paused: '⏸ НА ПАУЗЕ',
    status_daily_limit: 'ДНЕВНОЙ ЛИМИТ',
    status_daily_limit_hint: 'Дневной лимит откликов исчерпан. Сбросится завтра в 00:00',
    status_hh_limit: 'ЛИМИТ HH',
    status_hh_limit_hint: 'HH ограничил отклики. Бот проверит снятие лимита автоматически',
    // Card labels
    stat_replies: 'Отклики',
    stat_tests: 'Тесты',
    stat_surveys: '📝 Опросы',
    stat_already: 'Уже',
    stat_errors: 'Ошибки',
    stat_salary: '💰 Зарплата',
    stat_interviews: '🎯 Интервью',
    stat_new_inv: '📬 Новые',
    card_waiting: 'Ожидание...',
    card_hh_loading: '⏳ Загружаю HH данные...',
    card_sending: 'Отправка...',
    btn_acc_pause: '⏸ Пауза аккаунта',
    btn_acc_resume: '▶ Продолжить',
    btn_acc_global_pause: '⏸ Глобальная пауза',
    btn_resume_touch: '📤 Поднять резюме',
    btn_clear_discards: '🗑️ Очистить дискарды',
    btn_launch: '▶ Запустить',
    btn_delete: '✕ Удалить',
    card_apply_tests: 'Откликаться на вакансии с тестом',
    letter_section: '✉️ Письмо',
    url_section: '🔗 URL поиска',
    btn_save: '💾 Сохранить',
    btn_apply_url: '💾 Применить',
    cookies_expired_badge: '⚠️ Куки протухли! Обновите куки',
    errs_in_row: 'ошибок подряд',
    // Global stats
    gs_session: '📊 Сессия',
    gs_found: '🔍 Найдено',
    gs_applied: '✅ Отклики',
    gs_tests: '🧪 Тесты',
    gs_errors: '❌ Ошибки',
    gs_in_db: '💾 В базе',
    gs_in_db_tests: '🧪 Тест.',
    sidebar_recent: '📬 Последние отклики',
    recent_empty: 'Ожидание откликов...',
    no_accounts: 'Нет аккаунтов. Добавьте аккаунт в настройках ⚙️',
    // Resume stats
    rs_views: 'просм. (7д)',
    rs_shows: 'показов',
    rs_inv: 'приглаш.',
    rs_raise_in: 'поднять через',
    rs_raises_avail: 'поднятий доступно',
    // Log tab
    log_search_ph: '🔍 Поиск...',
    log_all_accs: 'Все аккаунты',
    log_all: 'Все',
    // Applied tab
    applied_title: '✅ Отклики',
    applied_search_ph: '🔍 Поиск по названию / компании...',
    applied_all_accs: 'Все аккаунты',
    applied_only_named: 'Только с названием',
    col_date: 'Дата',
    col_account: 'Аккаунт',
    col_vacancy: 'Вакансия',
    col_company: 'Компания',
    col_salary: 'Зарплата',
    btn_show_more: 'Показать ещё',
    shown_of: 'показано',
    shown_of2: 'из',
    // Tests tab
    tests_title: '🧪 Вакансии с тестами',
    col_applied_yn: 'Отклик',
    col_link: 'Ссылка',
    // DB tab
    db_title: '📂 База вакансий',
    db_search_ph: '🔍 Название / компания / ID...',
    db_all_statuses: 'Все статусы',
    db_status_sent: '✅ Отклик отправлен',
    db_status_test_passed: '📝 Тест пройден',
    db_status_test_pending: '🧪 Тест не пройден',
    db_all_accs: 'Все аккаунты',
    col_status: 'Статус',
    col_accounts: 'Аккаунты',
    // HH Status
    hh_interviews: 'Интервью',
    hh_viewed: 'Просмотрено',
    hh_discards: 'Отказы',
    hh_not_viewed: 'Не просм.',
    hh_updated: 'Обновлено:',
    hh_inv_list: '📋 Приглашения на интервью:',
    hh_offers: '🏢 Возможные предложения:',
    hh_no_data: 'Нет данных',
    hh_loading: '⏳ Загружаю данные HH...',
    // Views tab
    views_7d: 'Просмотров резюме (7д)',
    views_new: 'Новых просмотров',
    views_shows: 'Показов в поиске',
    views_invitations: 'Приглашений (7д)',
    views_inv_new: 'Новых приглашений',
    views_loading: 'Загружаю историю просмотров...',
    btn_load_history: '↻ Загрузить историю',
    views_no_data: 'Нет данных (обновите через 15 мин)',
    col_employer: 'Компания',
    // Apply tab
    apply_title: '🚀 Ручной отклик',
    apply_desc: 'Введите ссылку или ID вакансии — бот проверит, нужен ли опрос, покажет вопросы и отправит отклик.',
    apply_label_acc: 'Аккаунт',
    apply_label_vacancy: 'Ссылка на вакансию или ID',
    apply_vacancy_ph: 'https://hh.ru/vacancy/130334718 или просто 130334718',
    apply_label_tpl: 'Шаблон письма',
    apply_tpl_ph: '— выбрать шаблон —',
    apply_btn_clear: '✕ Очистить',
    apply_label_letter: 'Сопроводительное письмо',
    apply_letter_ph: 'Сопроводительное письмо (необязательно)',
    apply_btn_check: '🔍 Проверить / Откликнуться',
    // Settings tab
    settings_title: '⚙️ Настройки бота',
    btn_apply_settings: '✅ Применить',
    settings_applied: '✅ Настройки применены',
    // Settings param labels
    lbl_pages_per_url: 'Страниц на URL',
    hint_pages_per_url: 'Максимум страниц на поиск. По умолчанию 100: API остановится на последней странице или пределе HH (2000 результатов).',
    lbl_response_delay: 'Задержка отклика (с)',
    hint_response_delay: 'Пауза между пачками откликов в секундах',
    lbl_pause_between_cycles: 'Пауза между циклами (с)',
    hint_pause_between_cycles: 'Ожидание после завершения полного цикла обработки вакансий',
    lbl_batch_responses: 'Размер пачки откликов',
    hint_batch_responses: 'Сколько откликов отправлять параллельно',
    lbl_limit_check_interval: 'Интервал проверки лимита (м)',
    hint_limit_check_interval: 'Как часто проверять сброс дневного лимита откликов',
    lbl_min_salary: 'Минимальная зарплата (₽)',
    hint_min_salary: 'Пропускать вакансии с зарплатой ниже указанной (0 = без фильтра)',
    lbl_min_employer_rating: 'Мин. рейтинг работодателя',
    hint_min_employer_rating: '⭐ Пропускать вакансии работодателей с рейтингом ниже (0 = без фильтра, 3.0–3.5 типично)',
    lbl_min_recommendations_percent: 'Мин. % рекомендаций',
    hint_min_recommendations_percent: '% бывших сотрудников рекомендующих работодателя (0 = без фильтра)',
    smart_filter_skip_auto_resp: 'Без auto-feed',
    smart_filter_quick_resp: 'Quick-response в начало',
    smart_filter_it_only: 'Только IT-аккредитация',
    smart_filter_fresh_reserve: 'Резерв для свежих',
    lbl_auto_pause_errors: 'Авто-пауза при ошибках',
    hint_auto_pause_errors: 'Авто-пауза аккаунта после N ошибок подряд (0 = выключено)',
    // Settings sections
    sec_main_accounts: '👤 Основные аккаунты',
    sec_main_accounts_desc: 'Добавляйте и редактируйте основные аккаунты. Изменения сохраняются в data/accounts.json.',
    sec_url_pool: '🔗 Пул поисковых запросов',
    sec_url_pool_desc: 'Добавьте URL-адреса поиска вакансий — они появятся как чекбоксы на карточке каждого аккаунта.',
    sec_letters: '✉️ Шаблоны писем',
    sec_letters_desc: 'Создайте именованные шаблоны — они появятся в выпадающем списке на каждой карточке аккаунта.',
    sec_questionnaire: '📝 Шаблонные ответы на опросы',
    sec_questionnaire_desc: 'Когда вакансия требует опрос — бот автоматически заполнит его.',
    sec_cookies: '🔑 Обновить куки аккаунтов',
    sec_sessions: '🌐 Браузерные сессии',
    // Account form
    acc_field_name: 'Имя (полное)',
    acc_field_short: 'Короткое имя',
    acc_field_color: 'Цвет',
    acc_ph_name: 'Иван (основной)',
    acc_ph_short: 'основной',
    acc_cookies_label: 'Cookies (cURL или строка)',
    btn_add: '✅ Добавить',
    btn_add_account: '＋ Добавить аккаунт',
    btn_add_url: '＋ Добавить URL',
    btn_save_pool: '💾 Сохранить пул',
    btn_add_template: '＋ Добавить шаблон',
    btn_save_templates: '💾 Сохранить шаблоны',
    // Questionnaire
    q_keywords_ph: 'опыт, работа, QA',
    q_keywords_label: 'Ключевые слова (через запятую)',
    q_answer_label: 'Ответ',
    q_default_label: 'Ответ по умолчанию (если ни один шаблон не подошёл)',
    q_default_ph: 'Готова рассказать подробнее на собеседовании.',
    // Cookies section
    ck_desc: 'Вставьте новый cURL или строку cookie: hhtoken=…',
    btn_update_cookies: '🔑 Обновить куки',
    // Sessions
    sess_add: '➕ Добавить сессию из браузера',
    sess_mode_curl: 'cURL / строка',
    sess_mode_manual: 'Вручную',
    sess_curl_desc: 'Самый простой способ — Copy as cURL',
    sess_name_label: 'Имя (необязательно)',
    sess_name_ph: 'Например: Иван',
    sess_letter_label: 'Сопроводительное письмо (необязательно)',
    btn_connect: '🔗 Подключить сессию',
    sess_active: '🟢 активна',
    sess_inactive: '⭕ неактивна',
    // Confirm dialogs
    confirm_delete: 'Удалить',
    confirm_cancel: 'Отмена',
    // Shortcuts
    shortcuts_title: '⌨️ Горячие клавиши',
    shortcuts_tabs: 'Переключить вкладку',
    shortcuts_pause: 'Пауза / продолжить все',
    shortcuts_help: 'Это окно',
    shortcuts_esc: 'Закрыть это окно',
    btn_close: 'Закрыть',
    // Notifications
    notif_new_inv: '📬 Новое приглашение — ',
    notif_inv_count_pre: 'Теперь',
    notif_inv_count_mid: 'интервью (+',
    notif_limit: '🚫 Лимит — ',
    notif_limit_body: 'Дневной лимит откликов исчерпан',
    notif_cookies: '⚠️ Куки протухли — ',
    notif_cookies_body: 'Обновите куки в настройках аккаунта',
    // Page titles
    title_limit: '🚫 ЛИМИТ | HH Bot',
    title_paused: '⏸ Пауза | HH Bot',
    // Confirm dialog texts
    confirm_del_acc_pre: 'Удалить аккаунт',
    confirm_del_acc_body: 'Воркер будет остановлен.',
    confirm_del_db_pre: 'Удалить',
    confirm_del_db_mid: 'из базы?',
    confirm_del_db_body: 'Бот сможет откликнуться повторно.',
    confirm_del_sess: 'Удалить браузерную сессию?',
    // Audit / Smart filters / LLM status
    audit_search_status: 'Статус поиска',
    audit_filled: 'Заполненность',
    audit_recommendations: 'Рекомендации',
    audit_no_issues: 'Проблем не найдено — резюме в хорошей форме!',
    audit_market_analysis: 'Анализ рынка',
    smart_filters: 'Умные фильтры',
    smart_filter_low_comp: '<10 откликов',
    smart_filter_no_agency: 'Без агентств',
    smart_filter_auto_tests: 'Авто-тесты',
    smart_filter_pre_check: 'Защитный пре-чек',
    smart_filter_freshness: 'Свежесть:',
    smart_filter_llm_interval: 'LLM каждые:',
    smart_filter_daily_limit: 'Лимит/день:',
    audit_exp: 'Опыт',
    audit_salary: 'Зарплата',
    audit_photo: 'Фото',
    audit_resume_status: 'Статус резюме',
    audit_format: 'Формат:',
    audit_schedule: 'График:',
    audit_employment: 'Занятость:',
    audit_roles: 'Роли:',
    llm_st_off: 'LLM выключен',
    llm_st_paused: 'На паузе',
    llm_st_on: 'LLM работает',
    llm_st_no_acc: 'Нет аккаунтов с LLM',
  },
  en: {
    // Tabs
    tab_main: '📊 Main',
    tab_log: '📜 Log',
    tab_llm: '🤖 LLM Replies',
    tab_applied: '✅ Applied',
    tab_tests: '🧪 Tests',
    tab_questionnaire_history: '🧾 Test application history',
    tab_db: '📂 Database',
    tab_hh: '🎯 HH Status',
    tab_views: '👁️ Views',
    tab_apply: '🚀 Apply',
    tab_settings: '⚙️ Settings',
    // Header
    hdr_found: 'found',
    hdr_replies: 'applied',
    hdr_in_db: 'in DB',
    hdr_tests: 'tests',
    hdr_new_views: 'new views',
    hdr_new_inv: 'new invitations',
    hdr_shows: 'shows',
    btn_pause: '⏸ Pause',
    btn_resume: '▶ Resume (all)',
    // Status badges
    status_idle: 'IDLE',
    status_collecting: 'COLLECTING',
    status_applying: 'APPLYING',
    status_limit: 'LIMIT',
    status_waiting: 'PAUSED',
    status_checking: 'CHECKING LIMIT',
    status_inactive: 'INACTIVE',
    status_all_paused: '⏸ ALL PAUSED',
    status_acc_paused: '⏸ PAUSED',
    status_daily_limit: 'DAILY LIMIT',
    status_daily_limit_hint: 'Daily apply limit reached. Resets at midnight',
    status_hh_limit: 'HH LIMIT',
    status_hh_limit_hint: 'HH rate-limited responses. Bot will auto-check for reset',
    // Card labels
    stat_replies: 'Replies',
    stat_tests: 'Tests',
    stat_surveys: '📝 Surveys',
    stat_already: 'Already',
    stat_errors: 'Errors',
    stat_salary: '💰 Salary',
    stat_interviews: '🎯 Interviews',
    stat_new_inv: '📬 New inv.',
    card_waiting: 'Waiting...',
    card_hh_loading: '⏳ Loading HH data...',
    card_sending: 'Sending...',
    btn_acc_pause: '⏸ Pause account',
    btn_acc_resume: '▶ Resume',
    btn_acc_global_pause: '⏸ Global pause',
    btn_resume_touch: '📤 Raise resume',
    btn_clear_discards: '🗑️ Clear discards',
    btn_launch: '▶ Launch',
    btn_delete: '✕ Delete',
    card_apply_tests: 'Apply to vacancies with test',
    letter_section: '✉️ Letter',
    url_section: '🔗 Search URLs',
    btn_save: '💾 Save',
    btn_apply_url: '💾 Apply',
    cookies_expired_badge: '⚠️ Cookies expired! Update cookies',
    errs_in_row: 'errors in a row',
    // Global stats
    gs_session: '📊 Session',
    gs_found: '🔍 Found',
    gs_applied: '✅ Applied',
    gs_tests: '🧪 Tests',
    gs_errors: '❌ Errors',
    gs_in_db: '💾 In DB',
    gs_in_db_tests: '🧪 Tests',
    sidebar_recent: '📬 Recent Replies',
    recent_empty: 'Waiting for replies...',
    no_accounts: 'No accounts. Add an account in Settings',
    // Resume stats
    rs_views: 'views (7d)',
    rs_shows: 'shows',
    rs_inv: 'invitations',
    rs_raise_in: 'raise in',
    rs_raises_avail: 'raises available',
    // Log tab
    log_search_ph: '🔍 Search...',
    log_all_accs: 'All accounts',
    log_all: 'All',
    // Applied tab
    applied_title: '✅ Applied',
    applied_search_ph: '🔍 Search by title / company...',
    applied_all_accs: 'All accounts',
    applied_only_named: 'Only with title',
    col_date: 'Date',
    col_account: 'Account',
    col_vacancy: 'Vacancy',
    col_company: 'Company',
    col_salary: 'Salary',
    btn_show_more: 'Show more',
    shown_of: 'showing',
    shown_of2: 'of',
    // Tests tab
    tests_title: '🧪 Vacancies with tests',
    col_applied_yn: 'Applied',
    col_link: 'Link',
    // DB tab
    db_title: '📂 Vacancy Database',
    db_search_ph: '🔍 Title / company / ID...',
    db_all_statuses: 'All statuses',
    db_status_sent: '✅ Applied',
    db_status_test_passed: '📝 Test passed',
    db_status_test_pending: '🧪 Test pending',
    db_all_accs: 'All accounts',
    col_status: 'Status',
    col_accounts: 'Accounts',
    // HH Status
    hh_interviews: 'Interviews',
    hh_viewed: 'Viewed',
    hh_discards: 'Discards',
    hh_not_viewed: 'Not viewed',
    hh_updated: 'Updated:',
    hh_inv_list: '📋 Interview invitations:',
    hh_offers: '🏢 Possible offers:',
    hh_no_data: 'No data',
    hh_loading: '⏳ Loading HH data...',
    // Views tab
    views_7d: 'Resume views (7d)',
    views_new: 'New views',
    views_shows: 'Search shows',
    views_invitations: 'Invitations (7d)',
    views_inv_new: 'New invitations',
    views_loading: 'Loading view history...',
    btn_load_history: '↻ Load history',
    views_no_data: 'No data (refresh in 15 min)',
    col_employer: 'Company',
    // Apply tab
    apply_title: '🚀 Manual Apply',
    apply_desc: 'Enter vacancy URL or ID — the bot will check if a survey is required, show questions, and submit the reply.',
    apply_label_acc: 'Account',
    apply_label_vacancy: 'Vacancy URL or ID',
    apply_vacancy_ph: 'https://hh.ru/vacancy/130334718 or just 130334718',
    apply_label_tpl: 'Letter template',
    apply_tpl_ph: '— select template —',
    apply_btn_clear: '✕ Clear',
    apply_label_letter: 'Cover letter',
    apply_letter_ph: 'Cover letter (optional)',
    apply_btn_check: '🔍 Check / Apply',
    // Settings tab
    settings_title: '⚙️ Bot Settings',
    btn_apply_settings: '✅ Apply',
    settings_applied: '✅ Settings applied',
    // Settings param labels
    lbl_pages_per_url: 'Pages per URL',
    hint_pages_per_url: 'Maximum pages per search. Default 100: the API stops at its last page or HH’s 2000-result window.',
    lbl_response_delay: 'Reply delay (s)',
    hint_response_delay: 'Pause between reply batches in seconds',
    lbl_pause_between_cycles: 'Pause between cycles (s)',
    hint_pause_between_cycles: 'Wait after completing a full vacancy processing cycle',
    lbl_batch_responses: 'Reply batch size',
    hint_batch_responses: 'How many replies to send in parallel',
    lbl_limit_check_interval: 'Limit check interval (m)',
    hint_limit_check_interval: 'How often to check daily reply limit reset',
    lbl_min_salary: 'Minimum salary (₽)',
    hint_min_salary: 'Skip vacancies with salary below specified (0 = no filter)',
    lbl_min_employer_rating: 'Min. employer rating',
    hint_min_employer_rating: '⭐ Skip vacancies from employers below this rating (0 = off, 3.0–3.5 typical)',
    lbl_min_recommendations_percent: 'Min. recommendations %',
    hint_min_recommendations_percent: '% of ex-employees recommending the employer (0 = off)',
    smart_filter_skip_auto_resp: 'No auto-feed',
    smart_filter_quick_resp: 'Quick-response first',
    smart_filter_it_only: 'IT-accredited only',
    smart_filter_fresh_reserve: 'Reserve for fresh vacancies',
    lbl_auto_pause_errors: 'Auto-pause on errors',
    hint_auto_pause_errors: 'Auto-pause account after N consecutive errors (0 = disabled)',
    // Settings sections
    sec_main_accounts: '👤 Main Accounts',
    sec_main_accounts_desc: 'Add and edit main accounts. Changes are saved to data/accounts.json.',
    sec_url_pool: '🔗 Search URL Pool',
    sec_url_pool_desc: 'Add search URLs — they will appear as checkboxes on each account card.',
    sec_letters: '✉️ Letter Templates',
    sec_letters_desc: 'Create named templates — they will appear in the dropdown on each account card.',
    sec_questionnaire: '📝 Questionnaire Templates',
    sec_questionnaire_desc: 'When a vacancy requires a survey — the bot will fill it automatically.',
    sec_cookies: '🔑 Update Account Cookies',
    sec_sessions: '🌐 Browser Sessions',
    // Account form
    acc_field_name: 'Full name',
    acc_field_short: 'Short name',
    acc_field_color: 'Color',
    acc_ph_name: 'Ivan (main)',
    acc_ph_short: 'main',
    acc_cookies_label: 'Cookies (cURL or string)',
    btn_add: '✅ Add',
    btn_add_account: '＋ Add account',
    btn_add_url: '＋ Add URL',
    btn_save_pool: '💾 Save pool',
    btn_add_template: '＋ Add template',
    btn_save_templates: '💾 Save templates',
    // Questionnaire
    q_keywords_ph: 'experience, work, QA',
    q_keywords_label: 'Keywords (comma-separated)',
    q_answer_label: 'Answer',
    q_default_label: 'Default answer (if no template matched)',
    q_default_ph: 'I\'d be happy to share more details at the interview.',
    // Cookies section
    ck_desc: 'Paste new cURL or cookie string: hhtoken=…',
    btn_update_cookies: '🔑 Update cookies',
    // Sessions
    sess_add: '➕ Add browser session',
    sess_mode_curl: 'cURL / string',
    sess_mode_manual: 'Manual',
    sess_curl_desc: 'Easiest way — Copy as cURL',
    sess_name_label: 'Name (optional)',
    sess_name_ph: 'e.g.: Maria',
    sess_letter_label: 'Cover letter (optional)',
    btn_connect: '🔗 Connect session',
    sess_active: '🟢 active',
    sess_inactive: '⭕ inactive',
    // Confirm dialogs
    confirm_delete: 'Delete',
    confirm_cancel: 'Cancel',
    // Shortcuts
    shortcuts_title: '⌨️ Keyboard Shortcuts',
    shortcuts_tabs: 'Switch tab',
    shortcuts_pause: 'Pause / resume all',
    shortcuts_help: 'This window',
    shortcuts_esc: 'Close this window',
    btn_close: 'Close',
    // Notifications
    notif_new_inv: '📬 New invitation — ',
    notif_inv_count_pre: 'Now',
    notif_inv_count_mid: 'interviews (+',
    notif_limit: '🚫 Limit — ',
    notif_limit_body: 'Daily reply limit reached',
    notif_cookies: '⚠️ Cookies expired — ',
    notif_cookies_body: 'Update cookies in account settings',
    // Page titles
    title_limit: '🚫 LIMIT | HH Bot',
    title_paused: '⏸ Paused | HH Bot',
    // Confirm dialog texts
    confirm_del_acc_pre: 'Delete account',
    confirm_del_acc_body: 'Worker will be stopped.',
    confirm_del_db_pre: 'Delete',
    confirm_del_db_mid: 'from DB?',
    confirm_del_db_body: 'Bot will be able to apply again.',
    confirm_del_sess: 'Delete browser session?',
    // Audit / Smart filters / LLM status
    audit_search_status: 'Search status',
    audit_filled: 'Completeness',
    audit_recommendations: 'Recommendations',
    audit_no_issues: 'No issues found — resume looks good!',
    audit_market_analysis: 'Market analysis',
    smart_filters: 'Smart filters',
    smart_filter_low_comp: '<10 replies',
    smart_filter_no_agency: 'No agencies',
    smart_filter_auto_tests: 'Auto-tests',
    smart_filter_pre_check: 'Safety pre-check',
    smart_filter_freshness: 'Freshness:',
    smart_filter_llm_interval: 'LLM every:',
    smart_filter_daily_limit: 'Daily limit:',
    audit_exp: 'Experience',
    audit_salary: 'Salary',
    audit_photo: 'Photo',
    audit_resume_status: 'Resume status',
    audit_format: 'Format:',
    audit_schedule: 'Schedule:',
    audit_employment: 'Employment:',
    audit_roles: 'Roles:',
    llm_st_off: 'LLM off',
    llm_st_paused: 'Paused',
    llm_st_on: 'LLM running',
    llm_st_no_acc: 'No accounts with LLM',
  }
};

function t(key) {
  return (T[lang]?.[key]) ?? (T.ru[key]) ?? key;
}

function applyI18n() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const val = t(key);
    // For th elements with sort arrows, preserve the arrow span
    const arrow = el.querySelector('.sort-arrow');
    if (arrow) {
      // Replace text before the arrow span
      const nodes = Array.from(el.childNodes);
      const textNode = nodes.find(n => n.nodeType === Node.TEXT_NODE);
      if (textNode) textNode.textContent = val + ' ';
      else el.insertBefore(document.createTextNode(val + ' '), el.firstChild);
    } else {
      el.textContent = val;
    }
  });
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPh);
  });
  // Rebuild settings labels/hints
  document.querySelectorAll('[data-setting-label]').forEach(el => {
    const key = el.dataset.settingLabel;
    const def = SETTINGS_DEF.find(s => s.key === key);
    if (def) {
      const span = el.querySelector('span');
      el.textContent = t(def.labelKey) + ' ';
      if (span) el.appendChild(span);
    }
  });
  document.querySelectorAll('[data-setting-desc]').forEach(el => {
    const key = el.dataset.settingDesc;
    const def = SETTINGS_DEF.find(s => s.key === key);
    if (def) el.textContent = t(def.descKey);
  });
  if (State && State.lastSnapshot) {
    try { renderAll(State.lastSnapshot); } catch(e) {}
  }
}

function toggleLang() {
  lang = lang === 'ru' ? 'en' : 'ru';
  localStorage.setItem('hh-lang', lang);
  document.getElementById('lang-btn').textContent = lang.toUpperCase();
  applyI18n();
}

// ── State ──────────────────────────────────────────────────────
const State = {
  ws: null,
  lastSnapshot: null,
  snapshotReceivedAt: null, // monotonic receipt time, never a backend phase timestamp
  snapshotServerAt: null,
  snapshotSocket: null,
  currentTab: 'main',
  reconnectDelay: 1000,
  reconnectTimer: null,
  MAX_LOG_NODES: 100,
  prevInterviews: {},      // {acc_idx: count} — для браузерных уведомлений
  prevLimitState: {},      // {acc_idx: bool}
  prevCookiesExpired: {},  // {acc_idx: bool}
  compactCards: new Set(), // idx карточек в компактном режиме
  logLevel: '',          // фильтр уровня лога
  lastResponsesHash: '',
  settingsDrafts: new Map(), // key -> number; защищает ввод от фоновых WS snapshot
  applicationChecks: new Map(), // read-only reconciliation feedback bound to account identity
  authChecks: new Map(), // explicit verification only; never a background request
};
let _llmSettingsEditing = false;
let _llmSettingsEditTimer = null;
const AppliedSort = { field: 'at', dir: -1 };  // -1=desc 1=asc
const DBSort      = { field: 'at', dir: -1 };

// Settings config definition
const SETTINGS_DEF = [
  { key: 'pages_per_url',        labelKey: 'lbl_pages_per_url',        descKey: 'hint_pages_per_url',        min: 5,  max: 100, step: 5  },
  { key: 'response_delay',       labelKey: 'lbl_response_delay',       descKey: 'hint_response_delay',       min: 0,  max: 30,  step: 1  },
  { key: 'pause_between_cycles', labelKey: 'lbl_pause_between_cycles', descKey: 'hint_pause_between_cycles', min: 15, max: 600, step: 15 },
  { key: 'batch_responses',      labelKey: 'lbl_batch_responses',      descKey: 'hint_batch_responses',      min: 1,  max: 10,  step: 1  },
  { key: 'limit_check_interval', labelKey: 'lbl_limit_check_interval', descKey: 'hint_limit_check_interval', min: 5,  max: 120, step: 5  },
  { key: 'min_salary',           labelKey: 'lbl_min_salary',           descKey: 'hint_min_salary',           min: 0,  max: 300000, step: 10000 },
  { key: 'min_employer_rating',  labelKey: 'lbl_min_employer_rating',  descKey: 'hint_min_employer_rating',  min: 0,  max: 5,   step: 0.1, isFloat: true },
  { key: 'min_recommendations_percent', labelKey: 'lbl_min_recommendations_percent', descKey: 'hint_min_recommendations_percent', min: 0, max: 100, step: 5 },
  { key: 'auto_pause_errors',    labelKey: 'lbl_auto_pause_errors',    descKey: 'hint_auto_pause_errors',    min: 0,  max: 20,  step: 1  },
];

// Build settings UI once
function buildSettings() {
  const grid = document.getElementById('settings-grid');
  grid.innerHTML = '';
  SETTINGS_DEF.forEach(s => {
    const row = document.createElement('div');
    row.className = 'setting-row';
    row.dataset.settingKey = s.key;
    row.innerHTML = `
      <div class="setting-label" data-setting-label="${s.key}">${t(s.labelKey)} <span id="sv-${s.key}">—</span></div>
      <div class="setting-desc" data-setting-desc="${s.key}">${t(s.descKey)}</div>
      <input type="range" id="sr-${s.key}" min="${s.min}" max="${s.max}" step="${s.step}" value="${s.min}"
        oninput="settingsInput('${s.key}', this)">
    `;
    grid.appendChild(row);
  });
}

function settingsInput(key, input) {
  const value = Number(input.value);
  State.settingsDrafts.set(key, value);
  const label = document.getElementById('sv-' + key);
  if (label) label.textContent = input.value;
}

// ── Letter templates (Settings) ──────────────────────────────
function ltRenderTemplates(templates) {
  const list = document.getElementById('lt-templates-list');
  if (!list) return;
  list.innerHTML = '';
  (templates || []).forEach((t, i) => {
    const row = document.createElement('div');
    row.className = 'q-template-row';
    row.dataset.idx = i;
    row.innerHTML =
      `<button class="q-del" onclick="ltDelTemplate(${i})">✕</button>` +
      `<div style="flex:1">` +
        `<input class="q-keywords-input" placeholder="Название шаблона (напр: IT, Аналитик)" value="${esc(t.name||'')}">` +
        `<textarea class="q-answer-input" rows="3" placeholder="Текст письма...">${esc(t.text||'')}</textarea>` +
      `</div>`;
    list.appendChild(row);
  });
}

function ltAddTemplate() {
  const list = document.getElementById('lt-templates-list');
  if (!list) return;
  const i = list.children.length;
  const row = document.createElement('div');
  row.className = 'q-template-row';
  row.dataset.idx = i;
  row.innerHTML =
    `<button class="q-del" onclick="ltDelTemplate(${i})">✕</button>` +
    `<div style="flex:1">` +
      `<input class="q-keywords-input" placeholder="Название шаблона">` +
      `<textarea class="q-answer-input" rows="3" placeholder="Текст письма..."></textarea>` +
    `</div>`;
  list.appendChild(row);
}

function ltDelTemplate(idx) {
  const list = document.getElementById('lt-templates-list');
  if (!list) return;
  const rows = list.querySelectorAll('.q-template-row');
  if (rows[idx]) rows[idx].remove();
  // Re-index delete buttons
  list.querySelectorAll('.q-template-row').forEach((r, i) => {
    r.dataset.idx = i;
    const btn = r.querySelector('.q-del');
    if (btn) btn.onclick = () => ltDelTemplate(i);
  });
}

function ltReadTemplates() {
  const list = document.getElementById('lt-templates-list');
  if (!list) return [];
  return Array.from(list.querySelectorAll('.q-template-row')).map(r => ({
    name: (r.querySelector('.q-keywords-input')?.value || '').trim(),
    text: (r.querySelector('.q-answer-input')?.value || '').trim(),
  })).filter(t => t.name || t.text);
}

function ltSave() {
  const templates = ltReadTemplates();
  sendCmd({ type: 'set_letter_templates', templates });
  const st = document.getElementById('lt-status');
  if (st) { st.textContent = '✅ Сохранено'; setTimeout(() => { st.textContent = ''; }, 3000); }
}

function ltSyncFromSnapshot(snap) {
  const templates = snap?.config?.letter_templates || [];
  ltRenderTemplates(templates);
}

// ── LLM multi-profile ─────────────────────────────────────────
let _llmDetectTimers = {};

function llmProfileAdd(profile) {
  const p = profile || {name: '', api_key: '', base_url: '', model: '', enabled: true};
  const list = document.getElementById('llm-profiles-list');
  const idx = list.children.length;
  const row = document.createElement('div');
  row.className = 'llm-profile-row' + (p.enabled === false ? ' disabled' : '');
  row.dataset.idx = idx;
  row.innerHTML = `
    <div class="llm-profile-row-header">
      <input class="apply-input lp-name" style="font-size:11px;flex:1" placeholder="Название (например: DeepSeek)" value="${esc(p.name||'')}" oninput="llmProfileAutoSave()">
      <label style="display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer;white-space:nowrap">
        <input type="checkbox" class="lp-enabled" ${p.enabled !== false ? 'checked' : ''} style="accent-color:var(--cyan)" onchange="llmProfileAutoSave()"> Вкл
      </label>
      <button class="btn-sm" style="color:var(--red);border-color:var(--red);padding:1px 8px" onclick="this.closest('.llm-profile-row').remove();llmProfileReindex();llmProfileAutoSave()">✕</button>
    </div>
    <div class="llm-profile-fields">
      <div>
        <div style="font-size:10px;color:var(--dim);margin-bottom:2px;display:flex;align-items:center;gap:6px">
          <span>API Key</span>
          <span class="lp-key-fingerprint" data-idx="${idx}" style="color:var(--green);font-family:monospace"></span>
        </div>
        <input class="apply-input lp-key" type="password" style="font-size:11px" placeholder="sk-..." value="${esc(p.api_key||'')}" oninput="llmProfileDetectDebounce(this);_llmUpdateKeyFingerprint(this);llmProfileAutoSave()">
      </div>
      <div>
        <div style="font-size:10px;color:var(--dim);margin-bottom:2px">Модель</div>
        <input class="apply-input lp-model" style="font-size:11px" placeholder="gpt-4o-mini" value="${esc(p.model||'')}" oninput="llmProfileAutoSave()">
      </div>
    </div>
    <div style="display:flex;gap:6px;align-items:center">
      <div style="flex:1">
        <div style="font-size:10px;color:var(--dim);margin-bottom:2px">Base URL</div>
        <input class="apply-input lp-url" style="font-size:11px" placeholder="https://api.openai.com/v1" value="${esc(p.base_url||'')}" oninput="llmProfileAutoSave()">
      </div>
      <div style="display:flex;flex-direction:column;gap:3px;padding-top:14px">
        <button class="btn-sm" onclick="llmProfileDetect(this.closest('.llm-profile-row'))" title="Определить провайдера и загрузить модели">🔍 Определить</button>
        <span class="lp-status" style="font-size:10px;color:var(--dim)"></span>
      </div>
    </div>
  `;
  list.appendChild(row);
  // oninput не срабатывает при программной установке value, поэтому явно
  // обновим fingerprint — иначе новый row всегда рендерится с пустым span'ом,
  // даже когда backend знает про сохранённый ключ этого профиля.
  const keyInp = row.querySelector('.lp-key');
  if (keyInp) _llmUpdateKeyFingerprint(keyInp);
}

// Alias: llmProfileAutoSave = _llmAutoSave (используется в oninput каждого поля
// row'а профиля, см. llmProfileAdd). Дублирующая переменная удалена — уже есть
// _llmAutoSaveTimer / _llmAutoSave ниже в файле.
function llmProfileAutoSave() { _llmAutoSave(); }

function llmProfileReindex() {
  document.querySelectorAll('#llm-profiles-list .llm-profile-row').forEach((row, i) => { row.dataset.idx = i; });
}

// Возвращает «безопасный фингерпринт» ключа — первые 4 + последние 4 символа +
// длину. Юзеру не покажем ключ целиком (он type=password), но он видит что
// именно сохранилось. Пример: "sk-p...oTuvw (164 симв.)"
function _llmKeyFingerprint(key) {
  if (!key) return '';
  if (key.length <= 12) return `••• (${key.length} симв.)`;
  return `${key.slice(0, 4)}…${key.slice(-4)} (${key.length} симв.)`;
}

function _llmUpdateKeyFingerprint(inp) {
  const row = inp?.closest('.llm-profile-row');
  if (!row) return;
  const fp = row.querySelector('.lp-key-fingerprint');
  if (!fp) return;
  if (inp.value) {
    const raw = _llmKeyFingerprint(inp.value);
    fp.textContent = '✓ ' + raw;
    // Round-4 #5: fingerprint sync-check в syncLlmSettings сравнивает
    // decorated text с raw snapshot → всегда несовпадение. Кладём raw в
    // dataset, UI сравнивает по dataset.fp а не по textContent.
    fp.dataset.fp = raw;
    fp.style.color = 'var(--green)';
    return;
  }
  // Поле в инпуте пустое (после релоада type=password ничего не показал).
  // Берём fingerprint из последнего snapshot.config.llm_profiles[idx] —
  // он не содержит сам ключ, но говорит «✓ ключ на сервере: sk-p…wxyz».
  const idx = parseInt(row.dataset.idx);
  const cfg = State?.lastSnapshot?.config || {};
  const snapProf = (cfg.llm_profiles || [])[idx];
  if (snapProf && snapProf.key_set) {
    const raw = snapProf.key_fingerprint || '';
    fp.textContent = `🔒 на сервере: ${raw || '✓ есть'}`;
    fp.dataset.fp = raw;
    fp.style.color = 'var(--cyan)';
    fp.title = 'Ключ хранится на сервере. Введи новый чтобы перезаписать, или оставь пустым.';
  } else {
    // Явный плейсхолдер вместо пустого span — юзеру видно "ключа нет" вместо "визуально пусто".
    fp.textContent = '⚠ ключ не задан';
    fp.dataset.fp = '';
    fp.style.color = 'var(--red)';
    fp.title = 'Вставь API ключ в поле ниже и подожди 1.5с — автосохранение включится.';
  }
}

function llmProfileDetectDebounce(keyInput) {
  const row = keyInput.closest('.llm-profile-row');
  const idx = row.dataset.idx;
  clearTimeout(_llmDetectTimers[idx]);
  _llmDetectTimers[idx] = setTimeout(() => llmProfileDetect(row), 900);
}

async function llmProfileDetect(row) {
  const keyEl = row.querySelector('.lp-key');
  const urlEl = row.querySelector('.lp-url');
  const modelEl = row.querySelector('.lp-model');
  const st = row.querySelector('.lp-status');
  const key = keyEl?.value.trim() || '';
  if (!key || key.length < 8) return;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch('/api/llm_detect', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({api_key: key, base_url: urlEl?.value.trim() || ''})
    });
    const data = await res.json();
    if (!data.ok) {
      if (st) { st.textContent = '❌ ' + (data.error||'').slice(0,40); st.style.color = 'var(--red)'; }
      return;
    }
    if (data.base_url && urlEl && !urlEl.value.trim()) urlEl.value = data.base_url;
    if (data.models?.length) {
      if (modelEl && !modelEl.value.trim()) modelEl.value = data.models[0];
      if (st) { st.textContent = `✅ ${data.models.length} моделей`; st.style.color = 'var(--green)'; }
      llmShowModelPicker(row, data.base_url, data.models);
    } else {
      if (st) { st.textContent = '⚠️ Нет моделей'; st.style.color = 'var(--yellow)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  }
}

function llmShowModelPicker(row, base_url, models) {
  row.querySelector('.lp-model-picker')?.remove();
  const modelEl = row.querySelector('.lp-model');
  const picker = document.createElement('select');
  picker.className = 'apply-input lp-model-picker';
  picker.style.cssText = 'font-size:11px;margin-top:4px;width:100%';
  picker.innerHTML = '<option value="">— выбрать из найденных —</option>' +
    models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
  picker.onchange = () => {
    if (picker.value) { modelEl.value = picker.value; picker.remove(); }
  };
  modelEl.parentElement.appendChild(picker);
}

function llmProfilesRead() {
  const rows = document.querySelectorAll('#llm-profiles-list .llm-profile-row');
  // Авто-фикс: если в поле «Название» вставили ключ (sk-... / 40+ символов без пробелов),
  // а api_key пустой — переносим в api_key. Это спасает от типичной путаницы полей.
  const KEY_RE = /^(sk-|gsk_|gemini-|AIza|hf_|tk-|pk_|st-)[A-Za-z0-9_\-]{15,}$/;
  return [...rows].map(row => {
    const nameEl = row.querySelector('.lp-name');
    const keyEl = row.querySelector('.lp-key');
    let name = nameEl?.value.trim() || '';
    let api_key = keyEl?.value.trim() || '';
    if (!api_key && (KEY_RE.test(name) || (name.length >= 32 && !name.includes(' ')))) {
      api_key = name;
      name = '';
      if (keyEl) keyEl.value = api_key;
      if (nameEl) { nameEl.value = ''; nameEl.placeholder = '⚠️ Ключ перенесён в поле API Key — задай Название'; nameEl.style.borderColor = 'var(--yellow)'; }
    }
    return {
      name,
      api_key,
      base_url: row.querySelector('.lp-url')?.value.trim() || '',
      model: row.querySelector('.lp-model')?.value.trim() || '',
      enabled: row.querySelector('.lp-enabled')?.checked ?? true,
    };
  });
}

// Аудит 2026-08-17 #14: раньше два быстрых кликa на «Сохранить» стартовали
// параллельные POST, завершившиеся в непредсказуемом порядке — устаревший
// snapshot затирал более свежий. Сериализуем через promise-chain: пока
// предыдущий save не завершён, следующий ждёт.
let _llmSaveChain = Promise.resolve();
async function llmSave(btn) {
  const prev = _llmSaveChain;
  _llmSaveChain = prev.catch(() => {}).then(() => _llmSaveImpl(btn));
  return _llmSaveChain;
}
async function _llmSaveImpl(btn) {
  _llmSettingsEditing = false;
  clearTimeout(_llmSettingsEditTimer);
  const st = document.getElementById('llm-status');
  if (btn) btn.disabled = true;
  if (st) st.textContent = '⏳ Сохраняю...';
  try {
    const profiles = llmProfilesRead();
    const mode = document.getElementById('llm-profile-mode')?.value || 'fallback';
    // Аудит #30: раньше не проверяли res.ok первого запроса → ошибка
    // сохранения профилей отображалась зелёным «Сохранено». Теперь падаем.
    const rProfiles = await fetch('/api/llm_profiles', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({profiles, mode})
    });
    if (!rProfiles.ok) throw new Error(`profiles HTTP ${rProfiles.status}`);
    const pData = await rProfiles.json().catch(() => ({}));
    if (pData && pData.ok === false) throw new Error(pData.error || 'profiles rejected');
    // Save other settings via llm_config
    const res = await fetch('/api/llm_config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        system_prompt: document.getElementById('llm-system-prompt')?.value || '',
        auto_send: document.getElementById('llm-auto-send')?.checked || false,
        use_cover_letter: document.getElementById('llm-use-cover-letter')?.checked ?? true,
        use_resume: document.getElementById('llm-use-resume')?.checked ?? true,
        api_key: profiles[0]?.api_key || '',
        base_url: profiles[0]?.base_url || '',
        model: profiles[0]?.model || '',
      })
    });
    if (!res.ok) throw new Error(`config HTTP ${res.status}`);
    const data = await res.json().catch(() => ({}));
    if (data && data.ok === false) throw new Error(data.error || 'config rejected');
    if (st) {
      const ts = new Date().toLocaleTimeString('ru', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
      const promptLen = (document.getElementById('llm-system-prompt')?.value || '').length;
      const withKey = profiles.filter(pf => pf.api_key).length;
      st.innerHTML = `✅ Сохранено в ${ts} · профилей: <b>${profiles.length}</b> (с ключом: <b>${withKey}</b>) · промпт: <b>${promptLen}</b> симв.`;
      st.style.color = 'var(--green)';
    }
    document.querySelectorAll('#llm-profiles-list .lp-key').forEach(inp => _llmUpdateKeyFingerprint(inp));
  } catch(e) {
    if (st) { st.textContent = '❌ ' + (e.message || e); st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function llmGlobalToggle(btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/llm_toggle', {method: 'POST'});
    const data = await res.json();
    _llmUpdateToggleBtn(data.llm_enabled);
  } catch(e) {}
  finally { if (btn) btn.disabled = false; }
}

function _llmUpdateToggleBtn(enabled) {
  const btn = document.getElementById('llm-global-toggle-btn');
  if (!btn) return;
  if (enabled) {
    btn.textContent = '▶️ ВКЛ';
    btn.style.color = 'var(--green)';
    btn.style.borderColor = 'var(--green)';
  } else {
    btn.textContent = '⏸ ВЫКЛ';
    btn.style.color = 'var(--dim)';
    btn.style.borderColor = 'var(--dim)';
  }
}

function _llmMarkEditing() {
  _llmSettingsEditing = true;
  clearTimeout(_llmSettingsEditTimer);
  _llmSettingsEditTimer = setTimeout(() => { _llmSettingsEditing = false; }, 5000);
}

// Автосейв LLM-формы при blur. Раньше юзер вводил api_key и забывал нажать
// «💾 Сохранить» — профиль не уходил на бэк, /api/llm_run_now сваливался с
// «нет ключа». Теперь любое изменение в форме (профиль/чекбоксы/промпт)
// триггерит таймер, и через 1.5с без активности форма уезжает на сервер.
let _llmAutoSaveTimer = null;
function _llmAutoSave() {
  _llmMarkEditing();
  clearTimeout(_llmAutoSaveTimer);
  _llmAutoSaveTimer = setTimeout(() => {
    const st = document.getElementById('llm-status');
    if (st && !st.textContent) st.textContent = '⏳ автосохранение…';
    llmSave(null);
  }, 1500);
}

// Делегирование на blur+input+change. Textarea с системным промптом не
// генерит 'change' до blur, поэтому ловим ещё и 'input' (каждый keystroke,
// дебаунс 1.5с защищает от спама /api/llm_*).
function _isLlmAutoField(t) {
  if (!t || !t.classList) return false;
  return t.classList.contains('lp-name') || t.classList.contains('lp-key') ||
         t.classList.contains('lp-url') || t.classList.contains('lp-model') ||
         t.classList.contains('lp-enabled') || t.id === 'llm-system-prompt';
}
document.addEventListener('change', (e) => { if (_isLlmAutoField(e.target)) _llmAutoSave(); }, true);
document.addEventListener('input',  (e) => { if (_isLlmAutoField(e.target)) _llmAutoSave(); }, true);
document.addEventListener('blur',   (e) => { if (_isLlmAutoField(e.target)) _llmAutoSave(); }, true);

// ⚡ Быстрая настройка LLM — вставил ключ, нажал Enter, готово.
// Сам определяет провайдера по префиксу и подбирает дефолтную модель.
// Юзеры терялись в форме из 5 полей и забывали нажать "Сохранить".
function _llmDetectProvider(key) {
  const k = (key || '').trim();
  if (!k) return null;
  if (k.startsWith('sk-or-'))   return {name:'OpenRouter', base_url:'https://openrouter.ai/api/v1', model:'openai/gpt-4o-mini'};
  if (k.startsWith('sk-ant-'))  return {name:'Anthropic',  base_url:'https://api.anthropic.com/v1', model:'claude-haiku-4-5-20251001'};
  if (k.startsWith('sk-proj-')) return {name:'OpenAI',     base_url:'https://api.openai.com/v1', model:'gpt-4o-mini'};
  if (k.startsWith('gsk_'))     return {name:'Groq',       base_url:'https://api.groq.com/openai/v1', model:'llama-3.3-70b-versatile'};
  if (k.startsWith('AIza'))     return {name:'Gemini',     base_url:'https://generativelanguage.googleapis.com/v1beta/openai', model:'gemini-2.0-flash'};
  if (k.startsWith('hf_'))      return {name:'HuggingFace',base_url:'https://api-inference.huggingface.co/v1', model:'meta-llama/Llama-3.3-70B-Instruct'};
  if (k.startsWith('sk-') && k.length < 45) return {name:'DeepSeek', base_url:'https://api.deepseek.com', model:'deepseek-chat'};
  if (k.startsWith('sk-'))      return {name:'OpenAI',     base_url:'https://api.openai.com/v1', model:'gpt-4o-mini'};
  return {name:'Custom', base_url:'https://api.openai.com/v1', model:'gpt-4o-mini'};
}

async function llmQuickSetup(inp) {
  const status = document.getElementById('llm-quick-status');
  const setStatus = (text, color) => {
    if (!status) return;
    status.textContent = text;
    status.style.color = color || 'var(--dim)';
  };
  const key = (inp?.value || '').trim();
  if (!key) { setStatus('⚠️ Вставь ключ в поле выше', 'var(--yellow)'); inp?.focus(); return; }
  if (key.length < 20) { setStatus('⚠️ Ключ слишком короткий — проверь, что скопировал целиком', 'var(--yellow)'); return; }

  const prov = _llmDetectProvider(key);
  setStatus(`⏳ Сохраняю профиль ${prov.name}…`, 'var(--cyan)');

  try {
    // 1) Берём текущие профили (если есть), мерджим — не затираем чужие ключи.
    let existing = [];
    try {
      const snapResp = await fetch('/api/raw/config');
      if (snapResp.ok) {
        const cfg = await snapResp.json();
        existing = Array.isArray(cfg.llm_profiles) ? cfg.llm_profiles : [];
      }
    } catch(e) {}

    const newProfile = {
      name: prov.name,
      api_key: key,
      base_url: prov.base_url,
      model: prov.model,
      enabled: true,
    };

    // Если профиль с таким провайдером уже есть — обновим его, иначе добавим в начало.
    let merged;
    const idx = existing.findIndex(p => (p.base_url || '').trim() === prov.base_url);
    if (idx >= 0) {
      merged = existing.slice();
      merged[idx] = {...existing[idx], ...newProfile};
    } else {
      merged = [newProfile, ...existing];
    }

    // 2) Сохраняем профили
    const r1 = await fetch('/api/llm_profiles', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({profiles: merged, mode: 'fallback'})
    });
    if (!r1.ok) throw new Error('llm_profiles HTTP ' + r1.status);

    // 3) Также пишем в плоский llm_config (legacy путь) и включаем авто-отправку
    await fetch('/api/llm_config', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        api_key: key, base_url: prov.base_url, model: prov.model,
        enabled: true, auto_send: true,
      })
    });

    // 4) Глобальный тумблер LLM — llm_config выше уже выставил enabled=true,
    //    но дублируем через WS на случай гонки и обновляем кнопку в UI.
    try {
      if (typeof sendCmd === 'function') {
        sendCmd({type:'set_config', key:'llm_enabled', value:true});
        sendCmd({type:'set_config', key:'llm_auto_send', value:true});
      }
      _llmUpdateToggleBtn(true);
    } catch(e) {}

    // 5) Проверяем, что ключ реально лёг на диск
    let saved = false;
    try {
      const v = await fetch('/api/raw/config');
      if (v.ok) {
        const cfg = await v.json();
        const profs = cfg.llm_profiles || [];
        saved = profs.some(p => (p.api_key || '') === key) || (cfg.llm_api_key || '') === key;
      }
    } catch(e) {}

    if (saved) {
      const fp = key.slice(0,4) + '…' + key.slice(-4);
      setStatus(`✅ ${prov.name} сохранён · ${fp} (${key.length} симв.) · модель: ${prov.model} · LLM включён`, 'var(--green)');
      if (inp) inp.value = '';
    } else {
      setStatus('⚠️ Сохранение прошло, но при проверке ключ не виден. Проверь права на data/config.json', 'var(--yellow)');
    }
  } catch(e) {
    setStatus('❌ ' + (e.message || e), 'var(--red)');
  }
}

function setQuestionnaireClaimsCheck(enabled) {
  for (const id of ['llm-check-questionnaire-claims', 'questionnaire-history-check-claims']) {
    const checkbox = document.getElementById(id);
    if (checkbox) checkbox.checked = enabled;
  }
  sendCmd({type: 'set_config', key: 'llm_check_questionnaire_claims', value: enabled});
}

function syncLlmSettings(snap) {
  const cfg = snap?.config || {};
  const as = document.getElementById('llm-auto-send');
  const cl = document.getElementById('llm-use-cover-letter');
  const ur = document.getElementById('llm-use-resume');
  const fq = document.getElementById('llm-fill-questionnaire');
  const cq = document.getElementById('llm-check-questionnaire-claims');
  const cqHistory = document.getElementById('questionnaire-history-check-claims');
  const qr = document.getElementById('llm-use-quick-replies');
  const ail = document.getElementById('hh-ai-letter-first-try');
  const rv = document.getElementById('related-vacancies-enabled');
  // Дубли в главной панели «LLM Ответы» — тот же state, чекбоксы на двух вкладках.
  const qrM = document.getElementById('llm-use-quick-replies-main');
  const ailM = document.getElementById('hh-ai-letter-first-try-main');
  const rvM = document.getElementById('related-vacancies-enabled-main');
  const modeEl = document.getElementById('llm-profile-mode');
  if (!_llmSettingsEditing) {
    if (as && cfg.llm_auto_send !== undefined) as.checked = cfg.llm_auto_send;
    if (cl && cfg.llm_use_cover_letter !== undefined) cl.checked = cfg.llm_use_cover_letter;
    if (ur && cfg.llm_use_resume !== undefined) ur.checked = cfg.llm_use_resume;
    if (fq && cfg.llm_fill_questionnaire !== undefined) fq.checked = cfg.llm_fill_questionnaire;
    if (qr && cfg.llm_use_quick_replies !== undefined) qr.checked = cfg.llm_use_quick_replies;
    if (ail && cfg.hh_ai_letter_first_try !== undefined) ail.checked = cfg.hh_ai_letter_first_try;
    if (rv && cfg.related_vacancies_enabled !== undefined) rv.checked = cfg.related_vacancies_enabled;
    if (qrM && cfg.llm_use_quick_replies !== undefined) qrM.checked = cfg.llm_use_quick_replies;
    if (ailM && cfg.hh_ai_letter_first_try !== undefined) ailM.checked = cfg.hh_ai_letter_first_try;
    if (rvM && cfg.related_vacancies_enabled !== undefined) rvM.checked = cfg.related_vacancies_enabled;
  }
  if (cfg.llm_check_questionnaire_claims !== undefined) {
    if (cq) cq.checked = cfg.llm_check_questionnaire_claims;
    if (cqHistory) cqHistory.checked = cfg.llm_check_questionnaire_claims;
  }
  if (modeEl && cfg.llm_profile_mode) modeEl.value = cfg.llm_profile_mode;
  // Update the global toggle button
  if (cfg.llm_enabled !== undefined) _llmUpdateToggleBtn(cfg.llm_enabled);
  // Syncим текстовый промпт из конфига — но не во время редактирования и
  // не если поле в фокусе (юзер сейчас печатает, не затирай).
  const sp = document.getElementById('llm-system-prompt');
  if (sp && cfg.llm_system_prompt !== undefined && !_llmSettingsEditing && document.activeElement !== sp) {
    if (sp.value !== cfg.llm_system_prompt) sp.value = cfg.llm_system_prompt;
  }
  // Пересобираем список профилей когда backend не совпадает с UI и юзер не
  // редактирует — иначе после reload юзер видел "пустой список" пока snap
  // с 0 профилей не сменялся snap'ом с N (типичная race после autosave).
  // Во время редактирования не трогаем — иначе стёрли бы наполовину набранный ключ.
  const list = document.getElementById('llm-profiles-list');
  if (list && !_llmSettingsEditing) {
    const snapProfiles = cfg.llm_profiles || [];
    // Аудит 2026-08-17 #13: раньше сравнивали только количество → правки в
    // другой вкладке (переименование/смена модели/перестановка при том же
    // количестве) не подтягивались. Fingerprint по несекретным полям всех
    // профилей ловит любую содержательную правку.
    // Round-2 #6: реальные классы .lp-url (не base) / .lp-enabled.
    // Round-3 #6: раньше fingerprint не включал api_key → замена ключа
    // из другой вкладки не подтягивалась, stale K1 оставался в input.
    // Ключ сам в snapshot не идёт (security), но есть key_fingerprint
    // (например «sk-p…oTuvw|164»); в UI берём data-key-fingerprint из
    // .lp-key-fingerprint элемента, который синхронно рисуется по input'у.
    const fpOf = p => {
      if (!p) return '';
      return [p.name || '', p.model || '', p.base_url || '',
              (p.enabled !== false ? '1' : '0'),
              p.key_fingerprint || (p.key_set ? '1' : '0')].join('|');
    };
    const snapFp = snapProfiles.map(fpOf).join('||');
    const uiFp = Array.from(list.children).map(el => {
      const q = sel => (el.querySelector(sel)?.value || '');
      const en = el.querySelector('.lp-enabled')?.checked !== false ? '1' : '0';
      // Round-4 #5: читаем dataset.fp (raw fingerprint), не textContent
      // (decorated с эмодзи/префиксом). textContent никогда не совпадёт с
      // snapshot.key_fingerprint → был бесконечный rebuild.
      const fp = el.querySelector('.lp-key-fingerprint');
      const fpRaw = (fp?.dataset?.fp || '');
      return [q('.lp-name'), q('.lp-model'), q('.lp-url'), en, fpRaw].join('|');
    }).join('||');
    if (snapFp !== uiFp) {
      list.innerHTML = '';
      snapProfiles.forEach(p => llmProfileAdd(p));
    }
  }
  // Обновим fingerprint api_key для каждой строки — даже если строка уже
  // существует (юзер потёр поле или восстановил из конфига). type=password
  // прячет значение, юзеру нужен какой-то визуальный feedback что ключ есть.
  document.querySelectorAll('#llm-profiles-list .lp-key').forEach(inp => _llmUpdateKeyFingerprint(inp));
  // Populate account selector for resume preview
  const sel = document.getElementById('llm-resume-acc-sel');
  if (sel && snap?.accounts?.length && sel.options.length !== snap.accounts.length) {
    sel.innerHTML = snap.accounts.map(a =>
      `<option value="${a.idx}">${esc(a.name || a.short)}</option>`).join('');
  }
  renderLlmDiagnostics(snap);
}

function _fmtLlmStatusLine(label, data) {
  if (!data || !Object.keys(data).length) return `${label}: —`;
  const provider = data.provider || 'unknown';
  const status = data.status || 'unknown';
  const detail = data.detail ? ` (${data.detail})` : '';
  return `${label}: ${provider}/${status}${detail}`;
}

function renderLlmDiagnostics(snap) {
  const summary = snap?.config?.llm_status_summary || {};
  const providerEl = document.getElementById('llm-diag-provider');
  const replyEl = document.getElementById('llm-diag-reply');
  const questionnaireEl = document.getElementById('llm-diag-questionnaire');
  const providerBarEl = document.getElementById('llm-st-provider');
  const lastBarEl = document.getElementById('llm-st-last');

  let providerText = 'LLM провайдер не настроен';
  if (summary.configured_provider === 'openclaw') providerText = 'OpenClaw готов';
  else if (summary.configured_provider === 'api') providerText = 'API профили готовы';

  const replyText = _fmtLlmStatusLine('Reply', summary.reply);
  const questionnaireText = _fmtLlmStatusLine('Questionnaire', summary.questionnaire);
  const lastText = summary.reply?.status ? replyText : (summary.questionnaire?.status ? questionnaireText : 'Последний статус: —');

  if (providerEl) providerEl.textContent = providerText;
  if (replyEl) replyEl.textContent = replyText;
  if (questionnaireEl) questionnaireEl.textContent = questionnaireText;
  if (providerBarEl) providerBarEl.textContent = providerText;
  if (lastBarEl) lastBarEl.textContent = lastText;
}

// ── Schedule filter & auto-tests sync ────────────────────────
let _schedInited = false;
let _titleKwInited = false;
// Локальный кэш активных списков — на нём строим WS-команду при добавлении/удалении.
// Снапшот перезапишет его при следующем broadcast'е.
const _titleKwState = {title_include_keywords: [], title_exclude_keywords: []};

function _normKw(s) { return String(s || '').trim().toLowerCase(); }

function _syncTitleKwTags(containerId, kws, key, color) {
  const box = document.getElementById(containerId);
  if (!box) return;
  // Не обновляем DOM если состояние уже совпадает — иначе крестики «прыгают» при каждом snapshot 300ms.
  const arr = Array.isArray(kws) ? kws.map(_normKw).filter(Boolean) : [];
  const prev = _titleKwState[key] || [];
  _titleKwState[key] = arr.slice();
  if (prev.length === arr.length && prev.every((v, i) => v === arr[i]) && box.children.length === arr.length) return;
  box.innerHTML = '';
  if (!arr.length) {
    const hint = document.createElement('span');
    hint.style.cssText = 'font-size:10px;color:var(--dim);font-style:italic';
    hint.textContent = '(пусто)';
    box.appendChild(hint);
    return;
  }
  arr.forEach((kw, idx) => {
    const tag = document.createElement('span');
    tag.style.cssText = `display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.05);border:1px solid ${color};color:${color};padding:2px 6px;border-radius:10px;font-size:11px;font-family:monospace`;
    tag.innerHTML = `<span></span><button type="button" title="Удалить" style="background:transparent;border:none;color:${color};cursor:pointer;font-size:13px;line-height:1;padding:0">×</button>`;
    tag.querySelector('span').textContent = kw;
    tag.querySelector('button').onclick = () => {
      const next = (_titleKwState[key] || []).filter((_, i) => i !== idx);
      _titleKwState[key] = next;
      sendCmd({type:'set_config', key, value: next});
      _titleKwStatus(`удалено: «${kw}» → ${next.length} осталось`);
    };
    box.appendChild(tag);
  });
}

function _bindTitleKwInput(inputId, key) {
  const inp = document.getElementById(inputId);
  if (!inp) return;
  const commit = () => {
    const raw = inp.value;
    const parts = raw.split(/[,;\n]/).map(_normKw).filter(Boolean);
    if (!parts.length) return;
    const cur = _titleKwState[key] || [];
    const added = [];
    const merged = cur.slice();
    parts.forEach(p => {
      if (!merged.includes(p)) { merged.push(p); added.push(p); }
    });
    _titleKwState[key] = merged;
    sendCmd({type:'set_config', key, value: merged});
    inp.value = '';
    if (added.length) _titleKwStatus(`+ ${added.join(', ')} → всего ${merged.length}`);
    else _titleKwStatus(`(уже есть, всего ${merged.length})`);
  };
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); commit(); }
  });
  inp.addEventListener('blur', () => { if (inp.value.trim()) commit(); });
}

function _titleKwStatus(text) {
  const st = document.getElementById('title-kw-status');
  if (!st) return;
  st.textContent = text;
  st.style.color = 'var(--green)';
  clearTimeout(_titleKwStatus._t);
  _titleKwStatus._t = setTimeout(() => { st.textContent = ''; }, 3500);
}
function syncScheduleSettings(snap) {
  const cfg = snap?.config || {};
  // Sync schedule checkboxes
  if (cfg.allowed_schedules !== undefined) {
    document.querySelectorAll('.sched-cb').forEach(cb => {
      cb.checked = cfg.allowed_schedules.includes(cb.value);
    });
  }
  // Bind onchange only once
  if (!_schedInited) {
    _schedInited = true;
    document.querySelectorAll('.sched-cb').forEach(cb => {
      cb.onchange = () => {
        const checked = [...document.querySelectorAll('.sched-cb:checked')].map(c => c.value);
        sendCmd({type: 'set_config', key: 'allowed_schedules', value: checked});
      };
    });
  }
  // Title keyword filters (include/exclude) — теги + input по Enter/запятой.
  // Не должен затирать ввод пока юзер печатает: только при изменении в снапшоте
  // перерисовываем теги. Биндим обработчики один раз.
  _syncTitleKwTags('title-incl-tags', cfg.title_include_keywords || [], 'title_include_keywords', 'var(--green)');
  _syncTitleKwTags('title-excl-tags', cfg.title_exclude_keywords || [], 'title_exclude_keywords', 'var(--red)');
  if (!_titleKwInited) {
    _titleKwInited = true;
    _bindTitleKwInput('title-incl-input', 'title_include_keywords');
    _bindTitleKwInput('title-excl-input', 'title_exclude_keywords');
  }
  // Auto-tests
  const at = document.getElementById('auto-apply-tests');
  if (at && cfg.auto_apply_tests !== undefined) at.checked = cfg.auto_apply_tests;
  const oa = document.getElementById('use-oauth-apply');
  if (oa && cfg.use_oauth_apply !== undefined) oa.checked = cfg.use_oauth_apply;
  const dal = document.getElementById('daily-apply-limit');
  if (dal && cfg.daily_apply_limit !== undefined) dal.value = cfg.daily_apply_limit;
  const sohl = document.getElementById('stop-on-hh-limit');
  if (sohl && cfg.stop_on_hh_limit !== undefined) sohl.checked = cfg.stop_on_hh_limit;
  const fvm = document.getElementById('fresh-vacancies-mode');
  if (fvm && cfg.fresh_vacancies_mode !== undefined) fvm.checked = cfg.fresh_vacancies_mode;
  const fvh = document.getElementById('fresh-vacancy-hours');
  if (fvh && cfg.fresh_vacancy_hours !== undefined && document.activeElement !== fvh) fvh.value = cfg.fresh_vacancy_hours;
  const far = document.getElementById('fresh-apply-reserve');
  if (far && cfg.fresh_apply_reserve !== undefined && document.activeElement !== far) far.value = cfg.fresh_apply_reserve;
  // Skip inconsistent
  const si = document.getElementById('skip-inconsistent');
  if (si && cfg.skip_inconsistent !== undefined) si.checked = cfg.skip_inconsistent;
  // Регион (string) — синкаем только если поле не в фокусе (юзер может печатать)
  const reg = document.getElementById('cfg-hh-region');
  if (reg && cfg.hh_region !== undefined && document.activeElement !== reg) {
    reg.value = cfg.hh_region || '';
  }
  // Грамматический род соискателя — нормализуем алиасы из бэка в одно из трёх
  // значений селекта (female/male/neutral).
  const gen = document.getElementById('cfg-llm-applicant-gender');
  if (gen && cfg.llm_applicant_gender !== undefined && document.activeElement !== gen) {
    const v = (cfg.llm_applicant_gender || 'female').toLowerCase();
    const norm = (v === 'male' || v === 'm' || v === 'masculine' || v === 'мужской') ? 'male'
               : (v === 'neutral' || v === 'n' || v === 'неважно' || v === 'нейтральный') ? 'neutral'
               : 'female';
    gen.value = norm;
  }
  qUpdateGenderPreview(snap);
  // Баннер «есть несохранённые черновики»: показываем когда auto_send выкл
  // и в llm_log есть незаотправленные записи. Чтобы юзер не пропустил что
  // бот сгенерил кучу ответов и сидит ждёт флипа.
  const draftsBanner = document.getElementById('llm-drafts-pending-banner');
  if (draftsBanner) {
    const autoSendOn = cfg.llm_auto_send === true;
    const llmLog = State.lastSnapshot?.llm_log || [];
    const draftsCount = llmLog.filter(r => !r.sent).length;
    draftsBanner.style.display = (!autoSendOn && draftsCount > 0) ? '' : 'none';
    if (!autoSendOn && draftsCount > 0) {
      draftsBanner.innerHTML = `📝 <b>Есть ${draftsCount} несохранённых черновиков</b> — включи «Автоотправка» (чекбокс ниже) и они уйдут на следующем цикле без новых LLM-вызовов.`;
    }
  }
  // Smart search filters
  const fa = document.getElementById('filter-agencies');
  if (fa && cfg.filter_agencies !== undefined) fa.checked = cfg.filter_agencies;
  const flc = document.getElementById('filter-low-comp');
  if (flc && cfg.filter_low_competition !== undefined) flc.checked = cfg.filter_low_competition;
  const sp = document.getElementById('search-period');
  if (sp && cfg.search_period_days !== undefined) sp.value = cfg.search_period_days;
}

// ── LLM resume preview ───────────────────────────────────────
async function llmPreviewResume(btn) {
  const sel = document.getElementById('llm-resume-acc-sel');
  const pre = document.getElementById('llm-resume-preview');
  const st  = document.getElementById('llm-resume-status');
  const idx = sel?.value;
  if (!idx && idx !== 0) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Загружаю…'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch(`/api/account/${idx}/resume_text`);
    const data = await res.json();
    if (data.ok && data.text) {
      if (pre) { pre.textContent = data.text; pre.style.display = ''; }
      if (st) { st.textContent = `✅ ${data.length} симв.`; st.style.color = 'var(--green)'; }
    } else {
      if (pre) { pre.style.display = 'none'; }
      if (st) { st.textContent = '⚠️ Резюме не удалось извлечь (пустой результат). Проверь куки.'; st.style.color = 'var(--yellow)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Account diagnostics ──────────────────────────────────────
// SSR / shards reveal: jobSearchStatus, hasPublicVisibility, accessType,
// hasErrors per resume. Дёргаем при отрисовке карточки, кэшируем
// чтоб не бомбить /api при каждом snapshot (raw HTML 700KB+).
const _AccDiagCache = {}; // idx → {data, fetchedAt}
const _ACC_DIAG_TTL_MS = 5 * 60 * 1000;

async function _accDiagFetch(idx) {
  const cached = _AccDiagCache[idx];
  if (cached && Date.now() - cached.fetchedAt < _ACC_DIAG_TTL_MS) return cached.data;
  try {
    const r = await fetch(`/api/account/${idx}/diagnostics`);
    if (!r.ok) return null;
    const d = await r.json();
    _AccDiagCache[idx] = {data: d, fetchedAt: Date.now()};
    return d;
  } catch(e) { return null; }
}

function _accDiagBadgeApply(idx, data) {
  const el = document.getElementById('acc-diagbadge-' + idx);
  if (!el) return;
  const flags = (data && data.red_flags) || [];
  if (!flags.length) {
    el.style.display = 'none';
    return;
  }
  // Только заголовок в badge; подробности по клику
  el.style.display = 'block';
  const status = data.status || '?';
  const statusLbl = data.status_label || status;
  el.innerHTML = `⚠️ Диагностика: ${flags.length} проблем${flags.length>1?'ы':'а'} · статус: ${esc(statusLbl)} · 👁 раскрыть`;
  el.dataset.expanded = '0';
}

async function _accDiagAutoLoad(idx) {
  const data = await _accDiagFetch(idx);
  if (data) _accDiagBadgeApply(idx, data);
}

async function accDiagnostics(idx, btn) {
  if (!btn) return;
  // Принудительно обновляем кэш
  delete _AccDiagCache[idx];
  const data = await _accDiagFetch(idx);
  if (!data) { btn.textContent = '❌ Не удалось загрузить'; return; }
  const expanded = btn.dataset.expanded === '1';
  if (expanded) { _accDiagBadgeApply(idx, data); return; }
  btn.dataset.expanded = '1';
  const statusKeys = Object.keys(data.available_statuses || {});
  const statusOptions = statusKeys.map(k => {
    const lbl = data.available_statuses[k];
    const sel = data.status === k ? 'selected' : '';
    return `<option value="${k}" ${sel}>${esc(lbl)}</option>`;
  }).join('');
  const flagsHtml = (data.red_flags || []).map(f => `<div style="padding:2px 0">${esc(f)}</div>`).join('') || '<div style="color:var(--green)">✅ Проблем не найдено</div>';
  const stats = data.stats || {};
  let statsHtml = '';
  for (const [rh, s] of Object.entries(stats.per_resume || {})) {
    statsHtml += `<div style="font-size:10px;color:var(--dim);padding:2px 0">📊 ${esc(rh.slice(0,8))}…: показы ${s.search_shows}, просмотры ${s.views} (+${s.views_new}), инвайты ${s.invitations} (+${s.invites_new}) за ${s.period_days}д · ${esc(s.recommendation||'')}</div>`;
  }
  const userStats = stats.user_stats || {};
  const newInv = userStats['new-applicant-invitations'];
  const totalView = userStats['resumes-views'];
  const extraStats = (newInv !== undefined || totalView !== undefined)
    ? `<div style="font-size:10px;color:var(--dim);padding:2px 0">📬 непрочитанных инвайтов: <b>${newInv ?? '?'}</b> · всего просмотров: ${totalView ?? '?'}</div>` : '';
  btn.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:6px">
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <span>Сменить статус:</span>
        <select id="acc-jobstatus-${idx}" class="apply-input" style="font-size:11px;padding:2px 6px">${statusOptions}</select>
        <button type="button" class="btn-sm" onclick="event.stopPropagation();accSetJobStatus(${idx},this)" style="font-size:11px;padding:2px 6px">💾</button>
      </div>
      <div>${flagsHtml}</div>
      ${statsHtml ? `<div>${statsHtml}</div>` : ''}
      ${extraStats}
      <div style="text-align:right;font-size:10px"><span style="color:var(--dim);cursor:pointer" onclick="event.stopPropagation();_accDiagBadgeApply(${idx}, _AccDiagCache[${idx}]?.data)">▲ свернуть</span></div>
    </div>`;
}

async function accSetJobStatus(idx, btn) {
  const sel = document.getElementById('acc-jobstatus-' + idx);
  const status = sel?.value;
  if (!status) return;
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(`/api/account/${idx}/job_status`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({status}),
    });
    const d = await r.json();
    if (d.ok) {
      // Инвалидируем кэш + перезагружаем
      delete _AccDiagCache[idx];
      const data = await _accDiagFetch(idx);
      if (data) _accDiagBadgeApply(idx, data);
    } else {
      alert('Ошибка: ' + (d.error || 'unknown'));
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── LLM per-account toggle ────────────────────────────────────
function llmToggleAccount(idx, btn) {
  // Double-click guard: блокируем кнопку на 800мс — иначе rapid clicks
  // спамят WS дублями (kimi-r14-3 #8). Снимается следующим snapshot'ом
  // (updateCard перерисовывает кнопку) или таймером-страховкой.
  if (btn) {
    if (btn.disabled) return;
    btn.disabled = true;
    setTimeout(() => { if (btn) btn.disabled = false; }, 800);
  }
  sendCmd({type: 'account_llm', idx});
}

function updateLlmStatusBar(snap) {
  const stState = document.getElementById('llm-st-state');
  const stInterval = document.getElementById('llm-st-interval');
  const stChats = document.getElementById('llm-st-chats');
  const stReplied = document.getElementById('llm-st-replied');
  if (!stState) return;

  const cfg = snap?.config || {};
  const accs = snap?.accounts || [];
  const globalOn = cfg.llm_enabled;
  const autoSend = cfg.llm_auto_send;
  const interval = Math.max(cfg.llm_check_interval || 5, 2);
  const anyAccOn = accs.some(a => a.llm_enabled !== false);
  const paused = snap?.paused || accs.every(a => a.paused);
  const hasKey = (cfg.llm_api_key_set || (cfg.llm_profiles || []).some(p => p.key_set) ||
    (cfg.llm_status_summary && cfg.llm_status_summary.configured_provider === 'openclaw'));

  // State — actionable hint в одной фразе.
  let stateText, stateColor;
  if (!hasKey) {
    stateText = '🔑 Нет API-ключа';
    stateColor = 'var(--red)';
  } else if (!globalOn) {
    stateText = '⏹ Тумблер LLM выключен (нажми кнопку ⏸ ВЫКЛ слева)';
    stateColor = 'var(--dim)';
  } else if (paused) {
    stateText = '⏸ Все аккаунты на паузе (HH-лимит / ручная пауза)';
    stateColor = 'var(--yellow)';
  } else if (!anyAccOn) {
    stateText = '⚠️ Ни один аккаунт не включён для LLM (тумблеры под фильтрами)';
    stateColor = 'var(--yellow)';
  } else if (!autoSend) {
    stateText = '📝 Работает в режиме черновиков (включи «Автоотправку» чтобы отправлять)';
    stateColor = 'var(--yellow)';
  } else {
    stateText = '✅ Работает — авто-ответы идут';
    stateColor = 'var(--green)';
  }
  stState.textContent = stateText;
  stState.style.color = stateColor;

  // Interval + last activity
  const llmLog = snap?.llm_log || [];
  let last = '—';
  if (llmLog.length > 0) {
    const t = llmLog[0].time || '';
    last = `последний: ${t}`;
  }
  stInterval.textContent = `🔄 каждые ${interval}м · ${last}`;

  // Pending + interviews per snapshot
  const totalInterviews = accs.reduce((s, a) => s + (a.hh_interviews || 0), 0);
  const pendingByAcc = accs.reduce((s, a) => s + (a.llm_pending_chats || 0), 0);
  stChats.textContent = `🎯 ${totalInterviews} интервью${pendingByAcc ? ` · ⏳ ${pendingByAcc} в обработке` : ''}`;

  // Replied count from llm_log
  const sentCount = llmLog.filter(l => l.sent).length;
  const draftCount = llmLog.filter(l => !l.sent).length;
  const draftHint = draftCount && !autoSend ? ' ← ждут «Автоотправку»' : '';
  stReplied.textContent = `✅ ${sentCount} отправлено · 📝 ${draftCount} черновиков${draftHint}`;
  const stProvider = document.getElementById('llm-st-provider');
  const stLast = document.getElementById('llm-st-last');
  if (stProvider && !stProvider.textContent.trim()) stProvider.textContent = '—';
  if (stLast && !stLast.textContent.trim()) stLast.textContent = 'Последний статус: —';
}

function oauthToggleAccount(idx, btn) {
  if (btn) {
    if (btn.disabled) return;
    btn.disabled = true;
    setTimeout(() => { if (btn) btn.disabled = false; }, 800);
  }
  sendCmd({type: 'account_oauth', idx});
}

// ── LLM tab: interviews from DB ───────────────────────────────
let _llmRowsCache = [];

// Кэш рейтингов работодателей: vacancy_id → {total, recommend_pct, name} | null.
// Бэкенд тоже кэширует 24ч, но клиентский кэш экономит сетевой round-trip
// при перерисовках таблицы (фильтр/сорт/поиск дёргают render).
const _EmpRatingCache = {};
let _enrichInflight = new Set();

async function _enrichEmpRatings() {
  // Берём первый аккаунт из snapshot — для backend cookies'ов нужен валидный acc idx.
  const accs = (State.lastSnapshot?.accounts || []).filter(a => !a.cookies_expired);
  if (!accs.length) return;
  const accIdx = accs[0].idx;
  const slots = document.querySelectorAll('.emp-rating-slot');
  // Уникальные vacancy_id в порядке появления (видимые ряды грузятся первыми).
  const uniqVids = [...new Set([...slots].map(s => s.dataset.vid).filter(Boolean))];
  for (const vid of uniqVids) {
    // Если уже знаем — рендерим из кэша.
    if (vid in _EmpRatingCache) {
      _renderEmpRatingSlots(vid, _EmpRatingCache[vid]);
      continue;
    }
    if (_enrichInflight.has(vid)) continue;
    _enrichInflight.add(vid);
    (async () => {
      try {
        const r = await fetch(`/api/account/${accIdx}/rating_by_vacancy/${encodeURIComponent(vid)}`);
        const d = r.ok ? await r.json() : null;
        const cached = (d && d.ok) ? {
          total: d.total, recommend_pct: d.recommend_pct, name: d.name,
          ratings: d.ratings,
          politeness: d.politeness || null,
          hr_activity: d.hr_activity || null,
          topic: d.topic || null,
        } : null;
        _EmpRatingCache[vid] = cached;
        _renderEmpRatingSlots(vid, cached);
      } catch(e) {
        _EmpRatingCache[vid] = null;
      } finally {
        _enrichInflight.delete(vid);
      }
    })();
  }
}

function _renderEmpRatingSlots(vid, data) {
  document.querySelectorAll(`.emp-rating-slot[data-vid="${CSS.escape(vid)}"]`).forEach(slot => {
    if (!data) { slot.textContent = ''; return; }
    const parts = [];
    // 1) Rating chip
    if (data.total) {
      const total = Number(data.total).toFixed(1);
      const color = data.total >= 4.3 ? 'var(--green)'
                  : data.total >= 3.8 ? 'var(--yellow)'
                  : 'var(--red)';
      const recommend = data.recommend_pct != null ? ` ${data.recommend_pct}%` : '';
      const r = data.ratings || {};
      const tooltip = `Workplace ${r.workplace||'?'} · Team ${r.team||'?'} · Management ${r.management||'?'} · Career ${r.career||'?'} · Rest ${r.rest||'?'} · Salary ${r.salary||'?'}`;
      parts.push(`<span style="color:${color};font-weight:600" title="${esc(tooltip)}">⭐${total}${recommend}</span>`);
    }
    // 2) Politeness chip: % чтения откликов + дни ответа
    if (data.politeness) {
      const p = data.politeness;
      const rp = p.read_percent;
      const polColor = rp >= 90 ? 'var(--green)' : rp >= 70 ? 'var(--yellow)' : 'var(--red)';
      const tot = p.total_topics ? ` (на ${p.total_topics} откл.)` : '';
      const tooltip = `Работодатель читает ${rp}% откликов, отвечает за ${p.reply_days} дн${tot}`;
      parts.push(`<span style="color:${polColor};font-size:10px" title="${esc(tooltip)}">📖${rp}%·${p.reply_days}д</span>`);
    }
    // 2b) Topic state — viewed_by_opponent + last_state
    if (data.topic) {
      const tp = data.topic;
      // last_state chip
      const stateLabels = {
        DISCARD:  '<span style="color:var(--red);font-size:10px" title="HH-статус: HR отказал">🚫 отказ</span>',
        INVITE:   '<span style="color:var(--green);font-size:10px" title="HH-статус: HR пригласил">🎯 invite</span>',
        RESPONSE: '<span style="color:var(--dim);font-size:10px" title="HH-статус: отклик">📨 отклик</span>',
        INTERVIEW:'<span style="color:var(--cyan);font-weight:600;font-size:10px" title="HH-статус: интервью">💼 интервью</span>',
        HIRED:    '<span style="color:var(--green);font-weight:600;font-size:10px" title="HH-статус: нанят">🎉 нанят</span>',
      };
      if (stateLabels[tp.last_state]) parts.push(stateLabels[tp.last_state]);
      // viewedByOpponent
      if (tp.viewed_by_opponent) {
        parts.push('<span style="color:var(--cyan);font-size:10px" title="HR увидел наш отклик">👁 видел</span>');
      } else if (tp.viewed_by_opponent === false && tp.last_state) {
        parts.push('<span style="color:var(--dim);font-size:10px" title="HR ещё не открыл наш отклик">💤 не видел</span>');
      }
      // unread_by_employer: сообщений от нас, которые HR не прочитал
      if (tp.unread_by_employer > 0) {
        parts.push(`<span style="color:var(--yellow);font-size:10px" title="HR не прочитал ${tp.unread_by_employer} ваших сообщений">📬 ${tp.unread_by_employer}</span>`);
      }
      if (tp.inbox_availability_state === 'DISABLED_BY_EMPLOYER') {
        parts.push('<span style="color:var(--red);font-size:10px" title="Работодатель отключил свой inbox — наши сообщения не дойдут">📪 inbox off</span>');
      }
    }
    // 3) HR online-status chip
    if (data.hr_activity) {
      const a = data.hr_activity;
      const code = (a.trl_code || '').toLowerCase();
      const labels = {online:'🟢 онлайн', today:'🟡 сегодня', yesterday:'🟠 вчера', weekexact:'🔴 неделю назад'};
      const label = labels[code] || code;
      const mins = a.inactive_minutes;
      const tip = `Owner HR (id ${a.hr_hhid||''}): ${code} (был ${mins!=null ? mins+' мин назад' : '?'})`;
      parts.push(`<span style="font-size:10px" title="${esc(tip)}">${label}</span>`);
    }
    slot.innerHTML = parts.length ? '· ' + parts.join(' · ') : '';
  });
}

function captchaControlsBusy(idx, busy) {
  const panel = document.getElementById('acc-captcha-' + idx);
  if (!panel) return;
  panel.setAttribute('aria-busy', String(busy));
  panel.querySelectorAll('input, button').forEach(el => { el.disabled = busy; });
}

let captchaHistoryView = null;

function closeCaptchaHistory() {
  const view = captchaHistoryView;
  if (!view) return;
  captchaHistoryView = null;
  view.controller?.abort();
  view.urls.forEach(url => URL.revokeObjectURL(url));
  document.removeEventListener('keydown', view.onKeydown, true);
  view.overlay.remove();
  if (view.previousFocus?.isConnected) view.previousFocus.focus();
}

function openCaptchaHistory() {
  if (captchaHistoryView) { captchaHistoryView.close.focus(); return; }
  const overlay = document.createElement('div');
  overlay.className = 'confirm-overlay captcha-history-overlay';
  overlay.innerHTML = `
    <section class="confirm-box captcha-history-box" role="dialog" aria-modal="true" aria-labelledby="captcha-history-title">
      <div class="captcha-history-heading">
        <h2 id="captcha-history-title">История капч</h2>
        <div class="captcha-history-actions">
          <button type="button" class="btn-sm" data-history-refresh>Обновить</button>
          <button type="button" class="btn-sm" data-history-close>Закрыть</button>
        </div>
      </div>
      <div class="captcha-history-note">Последние 20 попыток по всем аккаунтам. Время — по часовому поясу браузера.</div>
      <div class="captcha-history-status" role="status"></div>
      <div class="captcha-history-list"></div>
    </section>`;
  const view = {
    overlay,
    close: overlay.querySelector('[data-history-close]'),
    refresh: overlay.querySelector('[data-history-refresh]'),
    status: overlay.querySelector('.captcha-history-status'),
    list: overlay.querySelector('.captcha-history-list'),
    previousFocus: document.activeElement,
    urls: new Set(),
    controller: null,
  };
  view.onKeydown = event => {
    // Keep dashboard shortcuts (including pause/resume) out of this read-only view.
    event.stopImmediatePropagation();
    if (event.key === 'Escape') { event.preventDefault(); closeCaptchaHistory(); }
    if (event.key === 'Tab') {
      const buttons = [...overlay.querySelectorAll('button:not(:disabled)')];
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && (document.activeElement === first || !overlay.contains(document.activeElement))) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !overlay.contains(document.activeElement))) {
        event.preventDefault(); first?.focus();
      }
    }
  };
  captchaHistoryView = view;
  view.close.onclick = closeCaptchaHistory;
  view.refresh.onclick = refreshCaptchaHistory;
  overlay.onclick = event => { if (event.target === overlay) closeCaptchaHistory(); };
  document.body.appendChild(overlay);
  document.addEventListener('keydown', view.onKeydown, true);
  view.close.focus();
  refreshCaptchaHistory();
}

async function refreshCaptchaHistory() {
  const view = captchaHistoryView;
  if (!view) return;
  view.controller?.abort();
  const controller = new AbortController();
  view.controller = controller;
  view.urls.forEach(url => URL.revokeObjectURL(url));
  view.urls.clear();
  view.list.replaceChildren();
  view.refresh.disabled = true;
  view.status.textContent = 'Загружаю историю…';
  const isCurrent = () => captchaHistoryView === view && view.controller === controller && !controller.signal.aborted;
  try {
    const response = await fetch('/api/captcha/attempts?limit=20', {signal: controller.signal, cache: 'no-store'});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    if (!isCurrent()) return;
    const attempts = Array.isArray(data.attempts) ? data.attempts.slice(0, 20) : [];
    view.status.textContent = attempts.length ? `Попыток: ${attempts.length}` : 'Сохранённых попыток пока нет.';
    const sources = {local: 'Локальная модель', llm: 'LLM', gui: 'Веб-панель', telegram: 'Telegram', tg_manual: 'Telegram · вручную', unknown: 'Источник не сохранён'};
    const reasons = {
      isBot: 'HH отклонил ответ', recaptcha: 'HH запросил дополнительную проверку',
      http_429: 'HH ограничил частоту запросов', unconfirmed: 'HH не подтвердил прохождение проверки',
      unconfirmed_response: 'Ответ HH не содержит подтверждения прохождения',
      unconfirmed_transport: 'Не удалось получить подтверждение из-за ошибки связи',
      unconfirmed_verification: 'Проверка результата в HH не подтвердила прохождение',
      exception: 'Ошибка при отправке или проверке ответа',
    };
    await Promise.all(attempts.map(async attempt => {
      const item = document.createElement('article');
      item.className = 'captcha-history-item';
      const visual = document.createElement('div');
      visual.className = 'captcha-history-visual';
      visual.textContent = 'Загружаю картинку…';
      const details = document.createElement('div');
      details.className = 'captcha-history-details';
      const status = document.createElement('strong');
      status.className = 'captcha-history-outcome';
      status.textContent = attempt.ok === true ? 'Подтверждено HH'
        : attempt.ok === false ? (attempt.reason === 'isBot' ? 'HH отклонил ответ' : 'Не подтверждено HH')
        : 'Результат неизвестен';
      status.style.color = attempt.ok === true ? 'var(--green)' : attempt.reason === 'isBot' ? 'var(--red)' : 'var(--yellow)';
      details.appendChild(status);
      const addLine = (text, className = '') => {
        const line = document.createElement('div');
        line.className = className;
        line.textContent = text;
        details.appendChild(line);
      };
      addLine('Ответ: ' + (attempt.answer || 'не сохранён'), 'captcha-history-answer');
      addLine(sources[attempt.source] || String(attempt.source || sources.unknown));
      const date = attempt.at ? new Date(attempt.at) : null;
      addLine(date && !Number.isNaN(date.getTime()) ? date.toLocaleString('ru-RU') : 'Время не сохранено', 'captcha-history-note');
      if (attempt.account) addLine('Аккаунт: ' + attempt.account, 'captcha-history-note');
      if (attempt.reason) addLine('Причина: ' + (reasons[attempt.reason] || attempt.reason));
      if (attempt.legacy) addLine('Восстановлено из сохранённого образца', 'captcha-history-note');
      item.append(visual, details);
      view.list.appendChild(item);
      try {
        // Only archived local images: opening history never requests a live challenge.
        const imagePath = String(attempt.image_url || '');
        const imageUrl = new URL(imagePath, location.href);
        if (imageUrl.origin !== location.origin || !imagePath.startsWith('/api/captcha/samples/')) throw new Error('missing_image');
        const imageResponse = await fetch(imagePath, {signal: controller.signal});
        if (!imageResponse.ok || !(imageResponse.headers.get('Content-Type') || '').startsWith('image/')) throw new Error('missing_image');
        const blob = await imageResponse.blob();
        if (!isCurrent()) return;
        const url = URL.createObjectURL(blob);
        view.urls.add(url);
        const image = document.createElement('img');
        image.alt = 'Сохранённая картинка капчи';
        image.onerror = () => {
          URL.revokeObjectURL(url); view.urls.delete(url);
          if (isCurrent()) visual.textContent = 'Картинка недоступна';
        };
        image.src = url;
        visual.replaceChildren(image);
      } catch (_) {
        if (isCurrent()) visual.textContent = 'Картинка недоступна';
      }
    }));
  } catch (error) {
    if (isCurrent()) view.status.textContent = 'Не удалось загрузить историю: ' + (error.message || error);
  } finally {
    if (isCurrent()) view.refresh.disabled = false;
  }
}

async function loadCaptchaImg(idx, tryLocal = State.lastSnapshot?.config?.captcha_llm_enabled !== false) {
  const img = document.getElementById('acc-captcha-img-' + idx);
  const box = document.getElementById('acc-captcha-result-' + idx);
  if (!img) return;
  if (img.dataset.busy === '1') return;
  img.dataset.busy = '1';
  captchaControlsBusy(idx, true);
  const answer = document.getElementById('acc-captcha-input-' + idx);
  if (answer) answer.value = '';
  img.dataset.challengeId = '';
  img.dataset.challengeKey = '';
  img.style.display = 'none';
  if (box) { box.textContent = 'Загружаю картинку…'; box.style.color = ''; }
  let loaded = false;
  try {
    // cache-buster чтобы браузер каждый раз тянул свежую
    const url = `/api/account/${idx}/captcha/image?_=${Date.now()}`;
    const r = await fetch(url);
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.error || `HTTP ${r.status}`);
    }
    if (!(r.headers.get('Content-Type') || '').startsWith('image/')) {
      const data = await r.json(); throw new Error(data.error || 'HH не вернул картинку');
    }
    const blob = await r.blob();
    if (document.getElementById('acc-captcha-' + idx)?.hidden) return;
    img.dataset.challengeId = r.headers.get('X-Captcha-Id') || '';
    img.dataset.challengeKey = r.headers.get('X-Captcha-Key') || '';
    if (!img.dataset.challengeId || !img.dataset.challengeKey) {
      throw new Error('Сервер не вернул данные проверки. Нажмите «Другая», чтобы загрузить новую картинку.');
    }
    if (img.src.startsWith('blob:')) URL.revokeObjectURL(img.src);
    img.src = URL.createObjectURL(blob);
    img.style.display = 'block';
    if (box) box.textContent = '';
    loaded = true;
  } catch (e) {
    if (box && !document.getElementById('acc-captcha-' + idx)?.hidden) {
      box.textContent = '❌ ' + (e.message || e); box.style.color = 'var(--red)';
    }
  } finally {
    img.dataset.busy = '';
    captchaControlsBusy(idx, false);
    if (loaded && !tryLocal) answer?.focus();
  }
  if (loaded && tryLocal) {
    await solveCaptchaLocal(idx);
  }
}

async function solveCaptcha(idx) {
  const input = document.getElementById('acc-captcha-input-' + idx);
  const box = document.getElementById('acc-captcha-result-' + idx);
  if (!input) return;
  if (!input.value.trim()) {
    if (box) box.textContent = 'Введите текст с картинки и нажмите «Отправить».';
    input.focus(); return;
  }
  const img = document.getElementById('acc-captcha-img-' + idx);
  if (!img || img.dataset.busy === '1') return;
  if (!img.dataset.challengeKey) {
    if (box) box.textContent = 'Эта картинка уже отправлена или устарела. Дождитесь результата либо нажмите «Другая» для новой попытки.';
    return;
  }
  img.dataset.busy = '1';
  captchaControlsBusy(idx, true);
  const text = input.value.trim();
  const id = img.dataset.challengeId;
  const key = img.dataset.challengeKey;
  // Consume before dispatch: a timeout or invalid response must not replay the
  // same answer, even if Enter is pressed again after the request ends.
  img.dataset.challengeKey = '';
  if (box) { box.textContent = '⏳ Отправляю…'; box.style.color = ''; }
  try {
    const r = await fetch(`/api/account/${idx}/captcha/solve`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({text, id, key})
    });
    const d = await r.json();
    if (r.ok && d.ok) {
      if (box) {
        box.textContent = d.message || '✅ HH подтвердил ответ. Проверьте состояние аккаунта перед продолжением.';
        box.style.color = 'var(--green)';
        if (d.requires_confirmation) {
          const button = document.createElement('button');
          button.className = 'btn-sm';
          button.textContent = 'Подтвердить продолжение откликов';
          button.style.cssText = 'display:block;margin-top:8px';
          button.onclick = () => continueAccountCaptcha(idx, id, button, box);
          box.appendChild(button);
        }
      }
      input.value = '';
      img.dataset.challengeKey = '';
      // Only a server snapshot can hide this panel. A delayed local timer can
      // otherwise hide a new challenge or erase explicit resume confirmation.
    } else {
      if (d.unconfirmed) {
        if (box) {
          box.textContent = '⚠ Результат неизвестен: HH не подтвердил прохождение. Это не означает, что ответ неверный. Отклики остаются на паузе. Нажмите «Открыть проверку на HH / продолжить» и завершите проверку на странице HH; пока не подтверждайте продолжение.';
          box.style.color = 'var(--yellow)';
          if (d.diagnostic && Number.isInteger(d.diagnostic.http_status)) {
            const details = document.createElement('div');
            details.textContent = 'Диагностика: HTTP ' + d.diagnostic.http_status +
              '; формат: ' + (d.diagnostic.format === 'json' ? 'JSON' : 'не JSON') +
              '; перенаправление: ' + (d.diagnostic.redirect_present ? 'да' : 'нет');
            for (const key of ['hhcaptcha_isBot', 'recaptcha_isBot']) {
              if (typeof d.diagnostic[key] === 'boolean') details.textContent += '; ' + key + '=' + d.diagnostic[key];
            }
            box.appendChild(details);
          }
        }
        img.dataset.challengeKey = '';
        return;
      }
      if (box) { box.textContent = '❌ ' + (d.error || 'HH не принял ответ'); box.style.color = 'var(--red)'; }
      if (d.refresh_needed) {
        img.dataset.challengeKey = '';
        if (box) box.textContent += ' Отклики на паузе. Нажмите «Другая» и введите ответ с новой картинки.';
      }
    }
  } catch (e) {
    if (box) {
      box.textContent = '⚠ Не удалось получить результат отправки. Это не означает неверный ответ. Повтор не выполняется; отклики остаются на паузе. Откройте проверку HH или загрузите новую картинку.';
      box.style.color = 'var(--yellow)';
    }
  } finally {
    img.dataset.busy = '';
    captchaControlsBusy(idx, false);
  }
}

async function solveCaptchaLocal(idx) {
  const box = document.getElementById('acc-captcha-result-' + idx);
  const img = document.getElementById('acc-captcha-img-' + idx);
  if (!img || img.dataset.busy === '1') return;
  if (!img.dataset.challengeKey) {
    await loadCaptchaImg(idx, true);
    return;
  }
  const id = img.dataset.challengeId;
  const key = img.dataset.challengeKey;
  img.dataset.busy = '1';
  img.dataset.challengeKey = '';
  captchaControlsBusy(idx, true);
  if (box) { box.textContent = '⏳ Решение и отправка…'; box.style.color = ''; }
  try {
    const r = await fetch(`/api/account/${idx}/captcha/solve-local`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id, key})
    });
    const result = await r.json();
    // A success snapshot can arrive while this request is pending. It owns the
    // cleared panel; a late response must not bring back the previous attempt.
    if (document.getElementById('acc-captcha-' + idx)?.hidden) return;
    if (box) {
      box.textContent = result.message || result.error || 'Не удалось решить капчу';
      if (result.answer) {
        const answer = document.createElement('div');
        answer.textContent = 'Ответ локальной модели: ' + result.answer;
        box.appendChild(answer);
      }
      if (result.auto_retry) {
        const retry = document.createElement('div');
        const seconds = Number(result.retry_seconds);
        retry.textContent = Number.isFinite(seconds) && seconds > 0
          ? `Следующая автоматическая попытка — через ${seconds} сек. Эта картинка и ответ сохранены; новые попытки доступны в истории капч.`
          : 'Автоматические попытки продолжаются в фоне. Эта картинка и ответ сохранены; новые попытки доступны в истории капч.';
        box.appendChild(retry);
      }
    }
    if (result.manual_available && !result.auto_retry) img.dataset.challengeKey = key;
  } catch (e) {
    if (box && !document.getElementById('acc-captcha-' + idx)?.hidden) box.textContent = 'Ошибка связи при проверке капчи';
  } finally {
    img.dataset.busy = '';
    captchaControlsBusy(idx, false);
  }
}

async function continueAccountCaptcha(idx, id, button, box) {
  if (button.disabled) return;
  const img = document.getElementById('acc-captcha-img-' + idx);
  if (img?.dataset.busy === '1') return;
  if (!confirm('Подтверждаете, что вручную прошли проверку в HH именно для этого аккаунта? Это разрешит новые отправки.')) return;
  if (img) img.dataset.busy = '1';
  captchaControlsBusy(idx, true);
  button.disabled = true;
  try {
    const r = await fetch(`/api/account/${idx}/captcha/continue`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id, confirmed:true})});
    const result = await r.json();
    if (!r.ok || !result.ok) throw new Error(result.error || 'Не удалось продолжить');
    box.textContent = result.message || 'Продолжение разрешено. Дождитесь обновления состояния аккаунта.';
  } catch(e) {
    button.disabled = false;
    let error = box.querySelector('[data-captcha-error]');
    if (!error) { error = document.createElement('div'); error.dataset.captchaError = '1'; box.appendChild(error); }
    error.textContent = e instanceof SyntaxError ? 'Сервер не подтвердил продолжение. Проверьте состояние аккаунта.' : (e.message || 'Не удалось продолжить');
    error.style.color = 'var(--yellow)';
  } finally {
    if (img) img.dataset.busy = '';
    captchaControlsBusy(idx, false);
  }
}

async function loadAccountCaptcha(idx) {
  const box = document.getElementById('acc-captcha-result-' + idx);
  if (!box) return;
  const img = document.getElementById('acc-captcha-img-' + idx);
  if (img?.dataset.busy === '1') return;
  if (img) img.dataset.busy = '1';
  captchaControlsBusy(idx, true);
  box.textContent = 'Загружаю ссылку…';
  box.style.color = '';
  try {
    const response = await fetch(`/api/account/${idx}/captcha`);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Ошибка загрузки');
    if (!box.isConnected || document.getElementById('acc-captcha-' + idx)?.hidden) return;
    if (!data.has_direct_link || !data.url) {
      box.textContent = 'Ссылка из ответа API не сохранилась. Вход на главную HH не снимает эту проверку. Отправки остаются на паузе. ';
      const probe = document.createElement('button');
      probe.className = 'btn-sm'; probe.textContent = 'Проверить API без отклика';
      probe.onclick = async () => {
        probe.disabled = true;
        try {
          const r = await fetch(`/api/account/${idx}/captcha/refresh`, {method:'POST'});
          const result = await r.json();
          if (!r.ok || !result.ok) throw new Error(result.error || 'Ошибка проверки');
          await loadAccountCaptcha(idx);
          const note = document.createElement('div'); note.textContent = result.message; box.appendChild(note);
        } catch(e) { box.textContent = e.message; }
      };
      box.appendChild(probe);
      return;
    }
    const url = new URL(data.url);
    if (url.protocol !== 'https:' || !(url.hostname === 'hh.ru' || url.hostname.endsWith('.hh.ru')) || url.username || url.password) throw new Error('Небезопасная ссылка');
    box.textContent = '';
    const link = document.createElement('a');
    link.href = data.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    link.textContent = 'Пройти капчу на HH ↗';
    link.className = 'btn-sm';
    link.style.cssText = 'display:inline-block;padding:10px 14px;margin:6px 8px 6px 0;border:1px solid var(--yellow);border-radius:6px;color:var(--yellow);font-weight:700';
    box.appendChild(link);
    const button = document.createElement('button');
    button.className = 'btn-sm'; button.textContent = 'Я прошёл проверку — продолжить';
    button.onclick = () => continueAccountCaptcha(idx, data.id, button, box);
    box.appendChild(button);
  } catch(e) {
    box.textContent = e instanceof SyntaxError ? 'Сервер не вернул данные проверки. Попробуйте загрузить ссылку ещё раз; пауза сохранена.' : (e.message || 'Не удалось загрузить проверку');
  } finally {
    if (img) img.dataset.busy = '';
    captchaControlsBusy(idx, false);
  }
}

async function llmInterviewsLoad() {
  llmQuarantineLoad();
  if (_llmLoading) return;   // уже идёт запрос — не запускаем параллельный
  _llmLoading = true;
  const acc = document.getElementById('llm-log-acc-filter')?.value || '';
  const statusF = document.getElementById('llm-log-sent-filter')?.value || '';
  let url = `/api/interviews?limit=10000${acc ? '&acc=' + encodeURIComponent(acc) : ''}${statusF ? '&status=' + encodeURIComponent(statusF) : ''}`;
  let rows;
  try {
    const res = await fetch(url);
    rows = await res.json();
    _llmLastDbRefresh = Date.now();
  } catch(e) {
    _llmLoading = false;
    return; // Сетевая ошибка — не трогаем текущее содержимое таблицы
  } finally {
    _llmLoading = false;
  }
  _llmRowsCache = Array.isArray(rows) ? rows : [];
  llmInterviewsRender();
  // HR-ссылки (Google Forms / Yandex Forms / Telegram / etc.) — извлекаем при
  // каждой перезагрузке interviews. Отдельный рендер, чтобы фильтры/сортировка
  // основной таблицы не перезаписывали блок ссылок.
  _llmRenderHrLinks(_llmRowsCache);
}

async function llmQuarantineLoad() {
  const el = document.getElementById('llm-quarantine');
  if (!el) return;
  try {
    const response = await fetch('/api/llm/quarantine');
    if (!response.ok) throw new Error('request failed');
    const data = await response.json();
    if (!data.ok) throw new Error('storage unavailable');
    el.innerHTML = data.items.length ? '<b>Чаты, требующие проверки</b>' + data.items.map(item =>
      `<div style="margin-top:8px">${esc(item.account)} · ${esc(item.recorded_at || '')}<br>${esc(item.reason)} · <a href="https://hh.ru/chat/${encodeURIComponent(item.chat_id)}" target="_blank" rel="noopener noreferrer">Проверить в HH ↗</a>${item.can_review ? ` <button class="btn-sm" onclick="${esc(`llmQuarantineReview(${JSON.stringify(item)})`)}">Проверил — разрешить новые ответы</button>` : '<br>Старая запись без ID входящего сообщения: безопасное снятие через интерфейс недоступно.'}</div>`
    ).join('') + '<div style="margin-top:8px">Другие чаты и отклики работают. Автоматическая повторная отправка в эти чаты запрещена.</div>' : 'Нет изолированных чатов.';
  } catch(e) {
    el.textContent = 'Не удалось загрузить блокировки чатов. Обновите страницу; это не означает, что блокировок нет.';
  }
}

async function llmQuarantineReview(item) {
  if (!confirm('Вы проверили чат в HH? Старый ответ повторяться не будет. Разрешить ответы только на новые сообщения HR?')) return;
  try {
    const response = await fetch('/api/llm/quarantine/review', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({idx: item.idx, chat_id: item.chat_id, fingerprint: item.fingerprint, confirmed: true})
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Ошибка сохранения');
    await llmQuarantineLoad();
  } catch(e) { alert(e.message || 'Не удалось сохранить проверку'); }
}

function llmInterviewsRender() {
  let rows = _llmRowsCache.slice();
  const acc = document.getElementById('llm-log-acc-filter')?.value || '';
  const statusF = document.getElementById('llm-log-sent-filter')?.value || '';
  const sort = document.getElementById('llm-log-sort')?.value || 'date_desc';
  const search = (document.getElementById('llm-log-search')?.value || '').trim().toLowerCase();

  // Client-side search (по работодателю / вакансии / сообщению / ответу)
  if (search) {
    rows = rows.filter(r => {
      const blob = `${r.employer||''} ${r.vacancy_title||''} ${r.employer_last_msg||''} ${r.llm_reply||''}`.toLowerCase();
      return blob.includes(search);
    });
  }

  // Sort
  const t = (r) => Date.parse(r.last_seen || r.first_seen || '') || 0;
  if (sort === 'date_desc')     rows.sort((a,b) => t(b) - t(a));
  else if (sort === 'date_asc') rows.sort((a,b) => t(a) - t(b));
  else if (sort === 'pending_first') {
    const pri = (r) => (r.status === 'pending_reply') ? 0 : (r.status === 'draft') ? 1 : (r.status === 'replied') ? 2 : 3;
    rows.sort((a,b) => pri(a) - pri(b) || t(b) - t(a));
  }
  else if (sort === 'oldest_pending') {
    const isP = r => r.status === 'pending_reply' || r.status === 'draft';
    rows.sort((a,b) => (isP(b)?0:1) - (isP(a)?0:1) || t(a) - t(b));
  }
  else if (sort === 'employer') rows.sort((a,b) => (a.employer||'').localeCompare(b.employer||'', 'ru'));

  const table = document.getElementById('llm-interviews-table');
  const empty = document.getElementById('llm-interviews-empty');
  const countEl = document.getElementById('llm-log-count');
  const tbody = document.getElementById('llm-interviews-body');
  if (!tbody) return;
  if (countEl) {
    const total = _llmRowsCache.length;
    countEl.textContent = rows.length === total ? `${rows.length} записей` : `${rows.length} из ${total}`;
  }

  if (rows.length === 0) {
    if (statusF || acc || search) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--dim);padding:12px">Нет записей по выбранному фильтру/поиску</td></tr>`;
      if (table) table.style.display = '';
      if (empty) empty.style.display = 'none';
    } else if (_llmRowsCache.length === 0) {
      if (table) table.style.display = 'none';
      if (empty) empty.style.display = '';
    }
    return;
  }
  if (table) table.style.display = '';
  if (empty) empty.style.display = 'none';

  const statusBadge = s => {
    if (s === 'replied')         return '<span class="llm-sent-badge">✅ Отправлено</span>';
    if (s === 'draft')           return '<span class="llm-draft-badge">📝 Черновик</span>';
    if (s === 'pending_reply')   return '<span style="color:var(--yellow);font-size:11px">⏳ Ждёт ответа</span>';
    if (s === 'chat_closed')     return '<span style="color:var(--dim);font-size:11px">🔒 Закрыт</span>';
    return '<span style="color:var(--dim);font-size:11px">— нет</span>';
  };

  const chatBadge = s => {
    if (s === 'robot')       return '<span style="color:var(--magenta);font-size:10px">🤖 Робот</span>';
    if (s === 'locked')      return '<span style="color:var(--dim);font-size:10px">🔒 Закрыт</span>';
    if (s === 'waiting_hr')  return '<span style="color:var(--cyan);font-size:10px">⏳ Ждём HR</span>';
    if (s === 'replied')     return '<span style="color:var(--green);font-size:10px">💬 Ответили</span>';
    return '';
  };

  // Row background по статусу — чтобы юзер с расстояния видел что красное,
  // что зелёное, что жёлтое.
  const rowBg = (r) => {
    if (r.status === 'replied')        return 'background:rgba(0,200,80,0.05);border-left:3px solid var(--green)';
    if (r.status === 'draft')          return 'background:rgba(255,180,0,0.08);border-left:3px solid var(--yellow)';
    if (r.status === 'pending_reply')  return 'background:rgba(255,80,80,0.08);border-left:3px solid var(--red)';
    if (r.status === 'chat_closed')    return 'opacity:0.5;border-left:3px solid var(--dim)';
    if (r.chat_status === 'robot')     return 'background:rgba(200,80,200,0.05);border-left:3px solid var(--magenta)';
    return 'border-left:3px solid transparent';
  };

  tbody.innerHTML = rows.map(r => {
    const empMsg = esc(r.employer_last_msg || '—').replace(/\n/g, '<br>');
    const botReply = esc(r.llm_reply || '').replace(/\n/g, '<br>');
    const negLink = r.neg_id
      ? `<a href="https://hh.ru/chat/${encodeURIComponent(r.neg_id)}" target="_blank" style="font-size:10px;color:var(--cyan)">🔗</a>` : '';
    const dateStr = (r.last_seen || r.first_seen || '').replace('T', ' ').slice(0, 16);
    // Slot для async-чипа рейтинга — заполнится через _enrichRatings ниже
    const ratingSlot = r.vacancy_id
      ? `<span class="emp-rating-slot" data-vid="${esc(r.vacancy_id)}" style="font-size:10px;color:var(--dim);margin-left:4px"></span>`
      : '';
    return `<tr style="${rowBg(r)}">
      <td style="font-size:11px;color:var(--dim);white-space:nowrap">${dateStr}</td>
      <td style="font-size:11px;color:${colorVar(r.acc_color||'')}">${esc(r.acc||'')}</td>
      <td style="font-size:11px">${esc(r.employer||'')} ${negLink}${ratingSlot}</td>
      <td style="font-size:11px;color:var(--dim)">${esc(r.vacancy_title||'')}</td>
      <td class="llm-msg-cell">${empMsg}</td>
      <td class="llm-reply-cell">${botReply}</td>
      <td>${statusBadge(r.status)}</td>
      <td>${chatBadge(r.chat_status || '')}</td>
    </tr>`;
  }).join('');
  // Подгрузим рейтинги для всех уникальных vacancy_id в таблице. Делается
  // лениво и in-the-background, не блокирует первый рендер.
  _enrichEmpRatings();

  // Populate account filter from loaded data
  const accSel = document.getElementById('llm-log-acc-filter');
  if (accSel) {
    // Маппинг short→full name из snapshot, чтобы в выпадающем списке
    // показывать полное имя ("account (🌐)") вместо обрезанного "🌐account".
    const fullByShort = {};
    (State.lastSnapshot?.accounts || []).forEach(a => {
      if (a.short) fullByShort[a.short] = a.name || a.short;
    });
    const previous = accSel.value;
    const firstLabel = accSel.options[0]?.textContent || 'Все аккаунты';
    accSel.replaceChildren(new Option(firstLabel, ''));
    const known = new Set();
    const activeShorts = new Set((State.lastSnapshot?.accounts || []).map(a => a.short).filter(Boolean));
    rows.forEach(r => {
      if (r.acc && activeShorts.has(r.acc) && !known.has(r.acc)) {
        const opt = document.createElement('option');
        opt.value = r.acc;
        opt.textContent = fullByShort[r.acc] || r.acc;
        accSel.appendChild(opt);
        known.add(r.acc);
      }
    });
    if (known.has(previous)) accSel.value = previous;
  }

  // Per-account stats (always from full unfiltered data — re-fetch all)
  llmRenderAccStats();
}

async function llmRenderAccStats() {
  const statsEl = document.getElementById('llm-acc-stats');
  if (!statsEl) return;
  let all;
  try {
    const res = await fetch('/api/interviews?limit=10000');
    all = await res.json();
  } catch(e) { return; }

  // Group by acc
  const byAcc = {};
  all.forEach(r => {
    const a = r.acc || '?';
    if (!byAcc[a]) byAcc[a] = {acc: a, color: r.acc_color || '', pending: 0, draft: 0, replied: 0, total: 0};
    byAcc[a].total++;
    if (r.status === 'pending_reply') byAcc[a].pending++;
    else if (r.status === 'draft')    byAcc[a].draft++;
    else if (r.status === 'replied')  byAcc[a].replied++;
  });

  // Маппинг short→full name из текущего snapshot.
  const fullByShort = {};
  (State.lastSnapshot?.accounts || []).forEach(x => {
    if (x.short) fullByShort[x.short] = x.name || x.short;
  });
  statsEl.innerHTML = Object.values(byAcc).map(a => `
    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:8px 14px;min-width:160px">
      <div style="font-size:12px;font-weight:700;color:${colorVar(a.color)};margin-bottom:6px">${esc(fullByShort[a.acc] || a.acc)}</div>
      <div style="display:flex;gap:10px;font-size:12px">
        <span title="Ждёт ответа">⏳ <b>${a.pending}</b></span>
        <span title="Черновик" style="color:var(--yellow)">📝 <b>${a.draft}</b></span>
        <span title="Отправлено" style="color:var(--green)">✅ <b>${a.replied}</b></span>
      </div>
    </div>`).join('');
}

async function llmRunNow(btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳…'; }
  try {
    const res = await fetch('/api/llm_run_now', {method:'POST'});
    const data = await res.json();
    if (data.started) {
      if (btn) { btn.textContent = `✅ Запущено (${data.accounts || '?'} аккаунтов)`; }
      setTimeout(() => llmInterviewsLoad(), 8000);
    } else {
      const msg = data.error || 'Не запустилось';
      if (btn) { btn.textContent = '⚠️ ' + msg.slice(0, 60); }
      console.warn('llm_run_now refused:', msg);
    }
    setTimeout(() => { if (btn) { btn.textContent = '▶ Запустить сейчас'; btn.disabled = false; } }, 5000);
  } catch(e) {
    if (btn) { btn.textContent = '❌ ' + e; btn.disabled = false; }
    setTimeout(() => { if (btn) btn.textContent = '▶ Запустить сейчас'; }, 4000);
  }
}

async function llmResetReplied(btn) {
  if (!confirm('Сбросить историю «уже отвечали» для всех аккаунтов?\n\nБот повторно обработает все чаты работодателей в следующем цикле.')) return;
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = '⏳…';
  try {
    const r = await fetch('/api/llm_reset_replied', {method:'POST'});
    const data = await r.json();
    // Round-4 #6: honestly report skipped busy states — user thought полный
    // сброс произошёл, но их per-state markers не очистились (worker LLM-lock
    // держал дольше 5с timeout). Юзеру нужно повторить сброс для них.
    const busy = Array.isArray(data.skipped_busy) ? data.skipped_busy : [];
    if (busy.length) {
      btn.textContent = `⚠ Пропущены занятые: ${busy.join(', ')} — повторите`;
    } else {
      btn.textContent = '✅ Сброшено';
    }
    setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 6000);
  } catch(e) {
    btn.textContent = orig; btn.disabled = false;
  }
}

// ── LLM log tab: debug log from WS snapshot + auto-refresh DB ─
let _llmLastDbRefresh = 0;
let _llmDebugHash = '';
let _llmLoading = false;   // guard: only one fetch at a time
function _llmUpdateAccToggles(snap) {
  const container = document.getElementById('llm-acc-toggles');
  if (!container || !snap?.accounts) return;
  const accs = snap.accounts;
  // Add missing buttons
  accs.forEach(acc => {
    let btn = document.getElementById(`llm-acc-btn-${acc.idx}`);
    if (!btn) {
      btn = document.createElement('button');
      btn.id = `llm-acc-btn-${acc.idx}`;
      btn.style.cssText = 'padding:4px 10px;border-radius:4px;border:1px solid;cursor:pointer;font-size:11px;background:transparent;transition:color .15s,border-color .15s';
      btn.setAttribute('data-idx', acc.idx);
      btn.onclick = function() { llmToggleAccount(acc.idx, this); };
      container.appendChild(btn);
    }
    // Update label and color
    const on = acc.llm_enabled !== false;
    btn.textContent = `🤖 ${acc.name || acc.short || ''}`;
    btn.style.color = on ? colorVar(acc.color || 'green') : 'var(--dim)';
    btn.style.borderColor = on ? colorVar(acc.color || 'green') : 'var(--dim)';
    btn.style.opacity = on ? '1' : '0.5';
    btn.title = on ? 'LLM вкл — нажми чтобы выключить' : 'LLM выкл — нажми чтобы включить';
  });
  // Remove stale buttons
  const idxSet = new Set(accs.map(a => String(a.idx)));
  container.querySelectorAll('[id^="llm-acc-btn-"]').forEach(btn => {
    const i = btn.id.replace('llm-acc-btn-', '');
    if (!idxSet.has(i)) btn.remove();
  });
}

function _llmFmtRel(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (!t) return '';
  const d = Math.round((Date.now() - t) / 1000);
  if (d < 0) {
    const s = -d;
    if (s < 60) return `через ${s} с`;
    if (s < 3600) return `через ${Math.round(s/60)} мин`;
    return `через ${Math.round(s/3600)} ч`;
  }
  if (d < 60) return `${d} с назад`;
  if (d < 3600) return `${Math.round(d/60)} мин назад`;
  return `${Math.round(d/3600)} ч назад`;
}

// URL типизация — по домену / vendor'у формы. Позволяет группировать «все Google Forms»,
// «все Яндекс.Формы», «все Telegram», «прочие». HR обычно шлёт в чат ссылку и просит пройти
// анкету/тест — заполнение через API невозможно (Google captcha), но юзер должен видеть эти
// ссылки одним списком и не искать вручную по 100+ чатам.
const _LINK_TYPES = [
  {re: /docs\.google\.com\/forms|forms\.gle/i,           icon: '📝', label: 'Google Forms',   color: '#4285f4'},
  {re: /forms\.yandex\.|yandex\.ru\/forms/i,            icon: '📋', label: 'Яндекс.Формы',   color: '#fc3f1d'},
  {re: /forms\.office\.com|forms\.microsoft/i,          icon: '📊', label: 'MS Forms',        color: '#0078d4'},
  {re: /typeform\.com/i,                                 icon: '✏️', label: 'Typeform',        color: '#262627'},
  {re: /surveymonkey/i,                                  icon: '🐵', label: 'SurveyMonkey',   color: '#00bf6f'},
  {re: /(https?:\/\/)?t\.me\/|telegram\.me/i,           icon: '✈️', label: 'Telegram',        color: '#0088cc'},
  {re: /wa\.me\/|whatsapp\.com\/send/i,                 icon: '💬', label: 'WhatsApp',        color: '#25d366'},
  {re: /calendly\.com|calendar\.google/i,               icon: '📅', label: 'Календарь',       color: '#eb4335'},
  {re: /zoom\.us\/j\/|meet\.google\.com|teams\.microsoft/i, icon: '📹', label: 'Видеозвонок', color: '#2d8cff'},
  {re: /hh\.ru\/employer|career\.habr/i,                icon: '🏢', label: 'Профиль HH',      color: '#d6001c'},
];

// URL regex — greedy до whitespace/HTML-скобок/кавычек. Trailing punctuation
// (запятая, точка, ), ], !, ?, », ; :) обрезаем ПОСЛЕ match — иначе non-greedy
// съедал важные символы (query-string с ? или fragment с #).
const _URL_RE = /(?:https?:\/\/|www\.)[^\s<>«»"'`]+|(?:forms\.gle|t\.me|wa\.me|clck\.ru|bit\.ly|clickup\.com|notion\.so|typeform\.com)\/[^\s<>«»"'`]+/gi;
// Символы которые часто оказываются после URL в русском тексте.
const _URL_TRIM = /[.,;:!?)\]»}"']+$/;

// Короткий label для отображения: [domain]/…[последние-15-символов-path].
// Полный URL остаётся в href/title — юзер видит куда идёт при hover.
function _shortUrl(url) {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, '');
    let tail = u.pathname + u.search + u.hash;
    if (tail.length <= 32) return host + tail;
    return host + '/…' + tail.slice(-28);
  } catch(e) {
    return url.length > 60 ? url.slice(0, 30) + '…' + url.slice(-25) : url;
  }
}

function _classifyLink(url) {
  for (const t of _LINK_TYPES) if (t.re.test(url)) return t;
  return {icon: '🔗', label: 'Прочее', color: 'var(--dim)'};
}

function _extractHrLinks(rows) {
  // Пробегаем все интервью, вытаскиваем URL из employer_last_msg + llm_reply.
  // Dedup по (neg_id, url) — один и тот же линк в разных сообщениях не дублируем.
  const seen = new Set();
  const out = [];
  for (const r of rows || []) {
    const text = String(r.employer_last_msg || '');
    if (!text) continue;
    const matches = text.match(_URL_RE);
    if (!matches) continue;
    for (const rawUrl of matches) {
      // Триммим trailing пунктуацию (`«` , `.` , `?` etc.). Она попадает в match
      // потому что regex greedy до whitespace, но не является частью URL.
      let url = rawUrl.trim().replace(_URL_TRIM, '');
      if (url.length < 8) continue;
      if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
      const key = `${r.neg_id}|${url}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({
        url, neg_id: r.neg_id,
        acc: r.acc || '',
        employer: r.employer || '',
        vacancy_title: r.vacancy_title || '',
        last_seen: r.last_seen || r.first_seen || '',
        snippet: text.length > 140 ? text.slice(0, 140) + '…' : text,
        status: r.status || '',
        type: _classifyLink(url),
      });
    }
  }
  // Сортировка: свежие сверху.
  out.sort((a, b) => (Date.parse(b.last_seen) || 0) - (Date.parse(a.last_seen) || 0));
  return out;
}

// «Пройдено» персистится в localStorage — SPA-only, отдельный backend
// не заводим ради single-user клика. Ключ = neg_id|url (тот же что для dedup),
// значение = ISO-timestamp когда отметили. Восстанавливается после reload.
const _LLM_DONE_KEY = 'hh-links-done-v1';
let _llmLinksDone = (() => {
  try { return _llmReadLinkDone(); }
  catch(e) { return {}; }
})();

function _llmReadLinkDone() {
  const value = JSON.parse(localStorage.getItem(_LLM_DONE_KEY) || '{}');
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Некорректное хранилище отметок');
  }
  return value;
}

window.addEventListener('storage', event => {
  if (event.key !== _LLM_DONE_KEY && event.key !== null) return;
  try {
    _llmLinksDone = _llmReadLinkDone();
    _llmRenderHrLinks(_llmRowsCache);
  } catch(e) { /* Keep the last known state if storage is unavailable. */ }
});

function _llmLinkKey(l) { return `${l.neg_id}|${l.url}`; }

function _llmToggleLinkDone(neg_id, url, btn) {
  const key = `${neg_id}|${url}`;
  try {
    // Re-read before writing: another tab may have changed other links.
    const latest = _llmReadLinkDone();
    // Apply the intent displayed in this tab, not a blind toggle of newer state.
    if (_llmLinksDone[key]) delete latest[key];
    else latest[key] = new Date().toISOString();
    localStorage.setItem(_LLM_DONE_KEY, JSON.stringify(latest));
    _llmLinksDone = latest;
  } catch(e) {
    alert('Не удалось сохранить отметку. Проверьте, разрешено ли браузеру хранить данные сайта. Статус не изменён.');
    return;
  }
  // Ре-рендер только этой панели — не трогаем всю таблицу интервью.
  _llmRenderHrLinks(_llmRowsCache);
}

function _llmRenderHrLinks(rows) {
  const body = document.getElementById('llm-links-body');
  const countEl = document.getElementById('llm-links-count');
  if (!body || !countEl) return;
  const links = _extractHrLinks(rows);
  const doneCount = links.filter(l => _llmLinksDone[_llmLinkKey(l)]).length;
  countEl.textContent = doneCount
    ? `${links.length - doneCount} осталось / ${doneCount} ✓`
    : String(links.length);
  if (links.length === 0) {
    body.innerHTML = `<div style="color:var(--dim);font-size:11px">Пока ни один HR не прислал ссылку — здесь появятся формы, тесты и приглашения.</div>`;
    return;
  }
  // Группировка по типу + сортировка: pending сверху, done снизу.
  const byType = new Map();
  for (const l of links) {
    if (!byType.has(l.type.label)) byType.set(l.type.label, {type: l.type, items: []});
    byType.get(l.type.label).items.push(l);
  }
  for (const g of byType.values()) {
    g.items.sort((a, b) => {
      const da = _llmLinksDone[_llmLinkKey(a)] ? 1 : 0;
      const db = _llmLinksDone[_llmLinkKey(b)] ? 1 : 0;
      if (da !== db) return da - db;
      return (Date.parse(b.last_seen) || 0) - (Date.parse(a.last_seen) || 0);
    });
  }
  const groups = [...byType.values()].sort((a, b) => b.items.length - a.items.length);
  body.innerHTML = groups.map(g => {
    const rows = g.items.map(l => {
      const key = _llmLinkKey(l);
      const done = !!_llmLinksDone[key];
      const doneHandler = esc(`_llmToggleLinkDone(${JSON.stringify(String(l.neg_id))},${JSON.stringify(l.url)},this)`);
      // 3 отдельных clickable-зоны:
      //   [🔗 URL]        → открыть саму ссылку HR-а (форма/Telegram/…)
      //   [employer/msg]  → открыть чат с этим HR на hh.ru
      //   [Пройти]        → toggle localStorage-метки «сделано»
      // Раньше вся строка была одним <a> на URL — юзер не мог перейти в чат.
      const rowStyle = done
        ? 'display:flex;gap:8px;padding:6px 8px;background:rgba(0,200,80,0.06);border-radius:4px;align-items:flex-start;font-size:11px;opacity:0.55;border:1px solid transparent'
        : 'display:flex;gap:8px;padding:6px 8px;background:rgba(255,255,255,0.03);border-radius:4px;align-items:flex-start;font-size:11px;border:1px solid transparent;transition:border-color 0.15s';
      const urlStyle = done
        ? `color:${g.type.color};text-decoration:line-through;font-weight:600;flex-shrink:0;white-space:nowrap`
        : `color:${g.type.color};text-decoration:underline;font-weight:600;flex-shrink:0;white-space:nowrap`;
      const shortLabel = _shortUrl(l.url);
      // URL в чат HH: `hh.ru/chat/<neg_id>` — тот же формат что использует
      // интервью-таблица (renderInterviews). `negotiations/item?topicId=`
      // возвращает 404 (deprecated).
      const chatUrl = `https://hh.ru/chat/${encodeURIComponent(l.neg_id)}`;
      const btn = done
        ? `<button onclick="${doneHandler}"
                    style="background:transparent;border:1px solid var(--green);color:var(--green);border-radius:3px;padding:2px 10px;cursor:pointer;font-size:10px;flex-shrink:0"
                    title="Снять отметку — вернуть в список активных">✓ Пройдено</button>`
        : `<button onclick="${doneHandler}"
                    style="background:transparent;border:1px solid var(--dim);color:var(--dim);border-radius:3px;padding:2px 10px;cursor:pointer;font-size:10px;flex-shrink:0"
                    title="Отметить что заполнил/прошёл — уберётся из активных">☐ Пройти</button>`;
      return `
        <div style="${rowStyle}"
             onmouseover="this.style.borderColor='${g.type.color}'"
             onmouseout="this.style.borderColor='transparent'">
          <a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer"
             style="${urlStyle}" title="Открыть форму: ${esc(l.url)}">🔗 ${esc(shortLabel)}</a>
          <a href="${esc(chatUrl)}" target="_blank" rel="noopener noreferrer"
             style="color:var(--dim);flex:1;min-width:0;text-decoration:none;cursor:pointer"
             title="Открыть чат с ${esc(l.employer)} на hh.ru">
            <b style="color:var(--fg)">${esc(l.employer)}</b> · ${esc(l.vacancy_title || '—')}
            <span style="color:var(--dim);font-size:10px;margin-left:6px">${_llmFmtRel(l.last_seen)}</span>
            <div style="color:var(--fg);opacity:0.75;font-size:10px;margin-top:2px;font-style:italic">«${esc(l.snippet)}» <span style="color:var(--cyan);font-style:normal">→ открыть чат</span></div>
          </a>
          ${btn}
        </div>
      `;
    }).join('');
    const gDone = g.items.filter(l => _llmLinksDone[_llmLinkKey(l)]).length;
    const gLabel = gDone
      ? `<span style="color:var(--dim);font-weight:400">(${g.items.length - gDone} / ${g.items.length}, ${gDone} ✓)</span>`
      : `<span style="color:var(--dim);font-weight:400">(${g.items.length})</span>`;
    return `
      <div style="margin-top:6px">
        <div style="font-weight:600;color:${g.type.color};font-size:11px;margin-bottom:4px">
          ${g.type.icon} ${esc(g.type.label)} ${gLabel}
        </div>
        <div style="display:flex;flex-direction:column;gap:3px">${rows}</div>
      </div>
    `;
  }).join('');
}

function _llmRenderLiveBar(snap) {
  const bar = document.getElementById('llm-live-bar');
  const wrap = document.getElementById('llm-live-accounts');
  if (!bar || !wrap) return;
  const accs = (snap.accounts || []).filter(a =>
    a.llm_enabled !== false && (
      a.llm_current_neg_id || a.llm_current_total || a.llm_last_check_at || a.llm_next_check_at || a.llm_pending_chats
    )
  );
  if (accs.length === 0) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  wrap.innerHTML = accs.map(a => {
    const busy = a.llm_current_idx && a.llm_current_total;
    let mid;
    if (busy) {
      const neg = a.llm_current_neg_id || '';
      const negLink = neg
        ? `<a href="https://hh.ru/chat/${esc(neg)}" target="_blank" style="color:var(--cyan);text-decoration:none" title="Открыть чат в HH">#${esc(neg)}</a>`
        : '';
      mid = `<span style="color:var(--cyan);font-weight:600">🔄 [${a.llm_current_idx}/${a.llm_current_total}]</span>
             <span style="color:var(--fg)">${esc(a.llm_current_employer || '?')}</span>
             ${negLink}`;
    } else if (a.llm_pending_chats) {
      mid = `<span style="color:var(--yellow)">⏳ ${a.llm_pending_chats} в очереди, цикл завершён</span>`;
    } else {
      mid = `<span style="color:var(--dim)">💤 нет активных чатов</span>`;
    }
    const last = a.llm_last_check_at
      ? `<span style="color:var(--dim)" title="${esc(a.llm_last_check_at)}">последняя: ${_llmFmtRel(a.llm_last_check_at)}</span>` : '';
    const next = a.llm_next_check_at
      ? `<span style="color:var(--dim)" title="${esc(a.llm_next_check_at)}">следующая: ${_llmFmtRel(a.llm_next_check_at)}</span>` : '';
    return `<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;padding:2px 0">
      <span style="color:${colorVar(a.color || 'yellow')};font-weight:600;min-width:80px">${esc(a.name || a.short || '')}</span>
      ${mid}
      <span style="margin-left:auto;display:flex;gap:12px">${last}${next}</span>
    </div>`;
  }).join('');
}

function renderLlmLog(snap) {
  if (!snap) return;

  // Мини-статистика источников в llm_log (последние 200 записей в памяти).
  // Показывает сколько ответов пришло из HH-quick_replies vs своего LLM vs кэша.
  const srcEl = document.getElementById('llm-st-sources');
  if (srcEl && Array.isArray(snap.llm_log)) {
    const cnt = {quick_reply: 0, llm: 0, ai_letter: 0, cached: 0, robot: 0, other: 0};
    for (const r of snap.llm_log) {
      const s = r.source || 'other';
      cnt[s] = (cnt[s] || 0) + 1;
    }
    const parts = [];
    if (cnt.quick_reply) parts.push(`<span style="color:var(--green)">💡${cnt.quick_reply}</span>`);
    if (cnt.ai_letter)   parts.push(`<span style="color:var(--yellow)">✍️${cnt.ai_letter}</span>`);
    if (cnt.llm)         parts.push(`<span style="color:var(--cyan)">🤖${cnt.llm}</span>`);
    if (cnt.cached)      parts.push(`<span style="color:var(--dim)">📝${cnt.cached}</span>`);
    if (cnt.robot)       parts.push(`<span style="color:var(--dim)">🤖${cnt.robot}</span>`);
    srcEl.innerHTML = parts.length ? parts.join(' · ') : '<span style="color:var(--dim)">без ответов</span>';
  }

  // Update per-account LLM toggles
  _llmUpdateAccToggles(snap);

  // Live-статус LLM-цикла: пер-аккаунт «сейчас обрабатывает X/N [chat_id]»
  // + «следующая проверка через Y сек» / «последняя завершилась Z сек назад».
  // Без этого юзер не понимал что происходит между визуально-статичными
  // ре-рендерами таблицы (цикл идёт ~10 сек на чат, log в дебаг-панели прокручен).
  _llmRenderLiveBar(snap);

  // Auto-refresh interviews table from DB every 30s
  const now = Date.now();
  if (now - _llmLastDbRefresh > 30000) {
    _llmLastDbRefresh = now;
    llmInterviewsLoad();
  }

  // Update debug log from activity log — preserve scroll position
  const debugBox = document.getElementById('llm-debug-log');
  const debugCount = document.getElementById('llm-debug-count');
  if (debugBox && snap.log) {
    const debugEntries = snap.log.filter(e => (e.message || '').includes('🤖') || (e.message || '').includes('LLM'));
    // Skip rebuild if content hasn't changed
    const newHash = debugEntries.map(e => e.time + e.message).join('|');
    if (newHash === _llmDebugHash) return;
    _llmDebugHash = newHash;
    if (debugCount) debugCount.textContent = debugEntries.length ? `(${debugEntries.length})` : '';
    // Preserve scroll position
    const wasAtBottom = debugBox.scrollHeight - debugBox.scrollTop <= debugBox.clientHeight + 4;
    const savedTop = debugBox.scrollTop;
    debugBox.innerHTML = debugEntries.length === 0
      ? '<span style="color:var(--dim)">Нет LLM-записей в логе. Первый запуск через ~15 мин после старта HH-статистики.</span>'
      : debugEntries.map(e => {
          const lvlColor = e.level === 'error' ? 'var(--red)' : e.level === 'warning' ? 'var(--yellow)' : e.level === 'success' ? 'var(--green)' : 'var(--dim)';
          const chatLink = e.neg_id ? `<a href="https://hh.ru/chat/${encodeURIComponent(e.neg_id)}" target="_blank" style="color:var(--cyan);text-decoration:none" title="Открыть чат">🔗</a> ` : '';
          return `<div style="line-height:1.5"><span style="color:var(--dim)">${esc(e.time||'')}</span> <span style="color:${colorVar(e.color)}">${esc(e.acc||'')}</span> ${chatLink}<span style="color:${lvlColor}">${esc(e.message||'')}</span></div>`;
        }).join('');
    // Restore scroll: if was at bottom stay at bottom, otherwise restore position
    if (wasAtBottom) debugBox.scrollTop = debugBox.scrollHeight;
    else debugBox.scrollTop = savedTop;
  }
}

// ── Letter in account cards ───────────────────────────────────
function syncLetterSelects(snap) {
  const templates = snap?.config?.letter_templates || [];
  if (!templates.length) return;
  document.querySelectorAll('[id^="acc-letter-tpl-"]').forEach(sel => {
    const idx = sel.id.replace('acc-letter-tpl-', '');
    const ta = document.getElementById('acc-letter-ta-' + idx);
    const curText = ta?.value || '';
    const matched = templates.findIndex(t => t.text === curText);
    // Rebuild only if count differs or first option is wrong
    const needsRebuild = sel.options.length !== templates.length + 2 ||
      (templates.length > 0 && sel.options[1]?.text !== templates[0].name);
    if (!needsRebuild) return;
    sel.innerHTML = '<option value="">— пусто —</option>' +
      templates.map((t, i) => `<option value="${i}"${matched===i?' selected':''}>${esc(t.name)}</option>`).join('') +
      '<option value="__custom__"' + (curText && matched === -1 ? ' selected' : '') + '>✏️ Своё</option>';
  });
}

function letterPickTpl(idx) {
  const sel = document.getElementById('acc-letter-tpl-' + idx);
  const ta  = document.getElementById('acc-letter-ta-'  + idx);
  if (!sel || !ta) return;
  const val = sel.value;
  if (val === '' ) { ta.value = ''; return; }
  if (val === '__custom__') { ta.focus(); return; }
  const templates = State.lastSnapshot?.config?.letter_templates || [];
  const tpl = templates[parseInt(val)];
  if (tpl) ta.value = tpl.text;
}

async function proxyCheck(btn) {
  const urlEl = document.getElementById('proxy-url');
  const ipEl = document.getElementById('proxy-ip');
  const impEl = document.getElementById('proxy-impersonate');
  const errEl = document.getElementById('proxy-error');
  const inputEl = document.getElementById('proxy-url-input');
  if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
  try {
    const r = await fetch('/api/proxy/info', {method: 'GET'});
    const d = await r.json();
    if (urlEl) urlEl.textContent = d.proxy || '(нет — напрямую)';
    if (ipEl) ipEl.textContent = d.ip || '?';
    if (impEl) impEl.textContent = d.impersonate || 'нет';
    // input предзаполняем текущим URL — юзер видит что там и может править
    if (inputEl && !inputEl.value) inputEl.value = d.proxy || '';
    if (errEl) {
      if (d.error) { errEl.textContent = '⚠️ ' + d.error; errEl.style.display = ''; }
      else errEl.style.display = 'none';
    }
  } catch (e) {
    if (errEl) { errEl.textContent = '⚠️ ' + e.message; errEl.style.display = ''; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Проверить'; }
  }
}

async function proxySave(btn) {
  const inputEl = document.getElementById('proxy-url-input');
  const errEl = document.getElementById('proxy-error');
  const statusEl = document.getElementById('proxy-status');
  const urlEl = document.getElementById('proxy-url');
  const ipEl = document.getElementById('proxy-ip');
  if (!inputEl) return;
  const url = (inputEl.value || '').trim();
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Пробую...'; }
  if (statusEl) { statusEl.textContent = '⏳ probe api.ipify.org через новый прокси…'; statusEl.style.color = 'var(--dim)'; }
  if (errEl) errEl.style.display = 'none';
  try {
    const r = await fetch('/api/proxy/set', {method: 'POST', headers: {'Content-Type':'application/json'},
                                              body: JSON.stringify({url})});
    const d = await r.json();
    if (d.ok) {
      if (urlEl) urlEl.textContent = d.proxy || '(нет — напрямую)';
      if (ipEl) ipEl.textContent = d.ip || '?';
      if (statusEl) {
        const ts = new Date().toLocaleTimeString('ru', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
        statusEl.innerHTML = `✅ Применено в ${ts} · IP: <b>${d.ip || '?'}</b>`;
        statusEl.style.color = 'var(--green)';
      }
    } else {
      if (errEl) {
        errEl.textContent = `⚠️ ${d.error || 'error'} — откат к предыдущему прокси (${d.reverted_to || 'нет'})`;
        errEl.style.display = '';
      }
      if (statusEl) { statusEl.textContent = ''; }
      // синхронизируем input с реальным (реверт)
      if (inputEl && d.reverted_to !== undefined) inputEl.value = d.reverted_to || '';
    }
  } catch (e) {
    if (errEl) { errEl.textContent = '⚠️ ' + e.message; errEl.style.display = ''; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '💾 Применить'; }
  }
}

// Auto-probe при первом раскрытии секции (чтобы не жечь на каждом рендере).
document.addEventListener('DOMContentLoaded', () => {
  const sec = document.getElementById('proxy-section');
  if (sec && !sec._proxyProbed) {
    sec._proxyProbed = true;
    setTimeout(() => proxyCheck(), 800);
  }
});

async function letterSave(idx, btn) {
  const ta = document.getElementById('acc-letter-ta-' + idx);
  const st = document.getElementById('acc-letter-st-' + idx);
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch(`/api/account/${idx}/set_letter`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ letter: ta?.value || '' })
    });
    const data = await res.json();
    if (data.ok) {
      if (st) { st.textContent = '✅ Сохранено'; st.style.color = 'var(--green)'; }
      // Update ApplyLetters cache
      ApplyLetters[idx] = ta?.value || '';
    } else {
      if (st) { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) { btn.disabled = false; }
    if (st) setTimeout(() => { if (st.textContent !== '') st.textContent = ''; }, 4000);
  }
}

async function resumeSelectSave(idx, btn) {
  const sel = document.getElementById('acc-resume-sel-' + idx);
  const st  = document.getElementById('acc-resume-st-' + idx);
  const cur = document.getElementById('acc-resume-current-' + idx);
  const newHash = sel?.value || '';
  if (!newHash) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ переключаю…'; st.style.color = 'var(--dim)'; }
  try {
    const r = await fetch(`/api/account/${idx}/active_resume`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ resume_hash: newHash })
    });
    const d = await r.json();
    if (d.status === 'ok' || d.ok) {
      if (st) { st.textContent = '✅ Резюме переключено'; st.style.color = 'var(--green)'; }
      const opt = sel.options[sel.selectedIndex];
      if (cur && opt) cur.textContent = opt.textContent.split(' · ')[0];
      showResumeToast('Активное резюме: ' + (opt ? opt.textContent.split(' · ')[0] : newHash));
    } else {
      if (st) { st.textContent = '❌ ' + (d.message || d.error || 'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch (e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    if (st) setTimeout(() => { st.textContent = ''; }, 4000);
  }
}

function showResumeToast(message) {
  let el = document.getElementById('resume-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'resume-toast';
    el.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:9999;padding:10px 14px;border-radius:8px;background:var(--panel);color:var(--green);border:1px solid var(--green);box-shadow:0 4px 18px #0008';
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.style.display = 'block';
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => { el.style.display = 'none'; }, 3500);
}

async function sessRefresh(idx, btn) {
  const st = document.getElementById('acc-resume-st-' + idx);
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ читаю резюме из HH…'; st.style.color = 'var(--dim)'; }
  try {
    const r = await fetch(`/api/session/${idx}/refresh`, {method: 'POST'});
    const d = await r.json();
    if (d.status === 'ok') {
      if (st) { st.textContent = '✅ Обновлено, перезагрузи страницу'; st.style.color = 'var(--green)'; }
    } else {
      if (st) { st.textContent = '❌ ' + (d.message || 'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch (e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Search URLs section ───────────────────────────────────────
const HH_AREAS = {
  '1':'Москва','2':'Санкт-Петербург','3':'Екатеринбург','4':'Новосибирск',
  '5':'Казань','16':'Нижний Новгород','54':'Краснодар','88':'Россия','1001':'СНГ'
};
const HH_EXP = {
  'noExperience':'без опыта','between1And3':'1–3 года',
  'between3And6':'3–6 лет','moreThan6':'6+ лет'
};
const HH_SCHEDULE = {
  'fullDay':'полный день','shift':'сменный','flexible':'гибкий',
  'remote':'удалённо','flyInFlyOut':'вахта'
};

function parseUrlFilter(url) {
  try {
    const u = new URL(url.startsWith('http') ? url : 'https://' + url);
    const p = u.searchParams;
    const parts = [];

    const text = p.get('text');
    if (text) parts.push('🔍 ' + decodeURIComponent(text.replace(/\+/g,' ')));

    const resume = p.get('resume');
    if (resume && !text) {
      // Пытаемся развернуть resume_hash в имя/название аккаунта чтобы две
      // одинаковые badge'и («📄 По резюме») разных аккаунтов не сливались.
      let label = 'По резюме';
      const accs = State?.lastSnapshot?.accounts || [];
      const owner = accs.find(a => a.resume_hash === resume);
      if (owner) {
        // Приоритет: name (полное) → short → первые 6 чаров хеша
        label = `[${owner.name || owner.short}]`;
      } else {
        label = `По резюме ${resume.slice(0, 6)}…`;
      }
      parts.push('📄 ' + label);
    }

    const area = p.get('area');
    if (area) parts.push('📍 ' + (HH_AREAS[area] || 'регион ' + area));
    else parts.push('🌍 Все страны HH');

    const exp = p.get('experience');
    if (exp) parts.push('⏱ ' + (HH_EXP[exp] || exp));

    const sal = p.get('salary');
    if (sal) parts.push('💰 от ' + Number(sal).toLocaleString('ru') + '₽');

    const sched = p.get('schedule');
    if (sched) parts.push(HH_SCHEDULE[sched] || sched);

    const role = p.get('professional_role');
    const roles = p.getAll('professional_role');
    if (role) parts.push(roles.length > 1 ? `👔 Специализаций: ${roles.length}` : '👔 роль ' + role);

    const order = p.get('order_by');
    if (order === 'publication_time') parts.push('🕐 по дате');
    else if (order === 'salary_desc') parts.push('💹 по зарплате↓');

    return parts.length ? parts.join('  ') : '🔗 ' + u.pathname;
  } catch(e) { return url; }
}

// ── URL pool (Settings) ───────────────────────────────────────
function buildPoolRow(item, rowIdx) {
  const url = typeof item === 'string' ? item : (item?.url || '');
  const pages = typeof item === 'object' && item !== null ? (item?.pages ?? '') : '';
  const badge = parseUrlFilter(url);
  return `<div class="url-row" id="pool-row-${rowIdx}">
    <div class="url-badge">${esc(badge)}</div>
    <div style="display:flex;gap:4px;align-items:center">
      <input class="apply-input url-input" style="font-size:10px;padding:2px 6px;flex:1"
        value="${esc(url)}" oninput="urlPoolReparse(${rowIdx},this.value)">
      <input type="number" class="apply-input url-pages-input" min="1" max="200"
        style="font-size:10px;padding:2px 4px;width:54px;text-align:center"
        placeholder="стр." title="Глубина поиска (страниц)" value="${esc(String(pages))}">
      <button class="btn-sm" style="padding:2px 7px;color:var(--red);border-color:var(--red)"
        onclick="urlPoolRemoveRow(${rowIdx})">✕</button>
    </div>
  </div>`;
}

function urlPoolReparse(rowIdx, val) {
  const badge = document.querySelector(`#pool-row-${rowIdx} .url-badge`);
  if (badge) badge.textContent = parseUrlFilter(val);
}

function urlPoolRemoveRow(rowIdx) {
  const row = document.getElementById(`pool-row-${rowIdx}`);
  if (row) row.remove();
  document.getElementById('url-pool-rows')?.querySelectorAll('.url-row').forEach((r, i) => {
    r.id = `pool-row-${i}`;
    const inp = r.querySelector('.url-input');
    if (inp) inp.oninput = function() { urlPoolReparse(i, this.value); };
    const btn = r.querySelector('button');
    if (btn) btn.onclick = () => urlPoolRemoveRow(i);
  });
}

function urlPoolAddRow() {
  const container = document.getElementById('url-pool-rows');
  if (!container) return;
  const rowIdx = container.querySelectorAll('.url-row').length;
  const div = document.createElement('div');
  div.innerHTML = buildPoolRow('', rowIdx);
  container.appendChild(div.firstElementChild);
}

async function urlPoolSave(btn) {
  const container = document.getElementById('url-pool-rows');
  if (!container) return;
  const globalPages = State.lastSnapshot?.config?.pages_per_url || 40;
  const urls = Array.from(container.querySelectorAll('.url-row')).map(row => {
    const urlInp = row.querySelector('.url-input');
    const pagesInp = row.querySelector('.url-pages-input');
    const url = urlInp?.value?.trim() || '';
    const pages = parseInt(pagesInp?.value) || globalPages;
    return {url, pages};
  }).filter(u => u.url);
  const st = document.getElementById('url-pool-st');
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    sendCmd({type: 'set_url_pool', urls});
    if (st) { st.textContent = `✅ Сохранено (${urls.length} URL)`; st.style.color = 'var(--green)'; }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    setTimeout(() => { if (st) st.textContent = ''; }, 4000);
  }
}

function urlPoolBuild(snap) {
  const el = document.getElementById('url-pool-rows');
  if (!el || el.dataset.built === 'true') return;
  el.dataset.built = 'true';
  el.innerHTML = '';
  const pool = snap?.config?.url_pool || [];
  pool.forEach((item, i) => {
    const div = document.createElement('div');
    div.innerHTML = buildPoolRow(item, i);
    el.appendChild(div.firstElementChild);
  });
  if (!pool.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--dim)">Пул пустой — добавьте первый URL</div>';
  }
}

// ── URL selector on account cards ────────────────────────────
function _renderAccUrlChecksInto(container, acc, pool) {
  const selected = new Set(acc.urls || []);
  if (!pool.length) {
    container.innerHTML = '<div style="font-size:11px;color:var(--dim)">Пул пустой — добавьте URL в Настройках или прямо ниже.</div>';
    return;
  }
  const globalPages = State.lastSnapshot?.config?.pages_per_url || 40;
  container.innerHTML = pool.map((item, i) => {
    const url = typeof item === 'string' ? item : (item?.url || '');
    const poolPages = typeof item === 'object' && item?.pages ? item.pages : globalPages;
    const accPages = acc.url_pages?.[url] || '';
    const checked = selected.has(url) ? 'checked' : '';
    const badge = parseUrlFilter(url);
    const urlCount = acc.url_stats?.[url];
    const countInfo = urlCount != null ? `<span style="color:var(--green);font-size:10px;margin-left:4px">→${urlCount}</span>` : '';
    const previewId = `url-prev-${acc.idx}-${i}`;
    return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:5px">
      <label style="display:flex;align-items:flex-start;gap:5px;cursor:pointer;font-size:11px;flex:1;min-width:0">
        <input type="checkbox" value="${esc(url)}" ${checked} style="margin-top:2px;flex-shrink:0">
        <span style="color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(badge)}${countInfo} <span id="${previewId}" data-url="${esc(url)}" data-acc="${acc.idx}" style="margin-left:4px"></span></span>
      </label>
      <input type="number" class="apply-input acc-url-pages-inp" data-url="${esc(url)}"
        min="1" max="200" placeholder="${poolPages}"
        value="${esc(String(accPages))}"
        title="Глубина для этого URL (пусто = ${poolPages} стр. из пула)"
        style="width:52px;font-size:10px;padding:2px 4px;text-align:center;flex-shrink:0">
    </div>`;
  }).join('');
  container.querySelectorAll('[id^="url-prev-"]').forEach(el => urlPreviewLoad(el));
}

function syncAccUrlChecks(snap) {
  const pool = snap?.config?.url_pool || [];
  (snap?.accounts || []).forEach(acc => {
    const container = document.getElementById(`acc-url-checks-${acc.idx}`);
    const wrap = document.getElementById(`acc-url-wrap-${acc.idx}`);
    if (!container) return;
    // Если details открыт — не перерисовываем чтобы не сбрасывать чекбоксы
    // пока юзер их выбирает (UX). Но если кол-во URL'ов в пуле изменилось,
    // принудительно делаем дозапись новой строки в конец (не теряя выборы).
    if (wrap && wrap.open) {
      const rendered = container.querySelectorAll('input[type=checkbox]').length;
      if (rendered === pool.length) return; // ничего нового не появилось
      // Иначе — перерендер: новые URL'ы добавились, нужно показать
    }
    _renderAccUrlChecksInto(container, acc, pool);
  });
}

const _urlPreviewCache = new Map();  // "idx|url" → result (in-mem)
async function urlPreviewLoad(el) {
  if (!el || el.dataset.loaded === '1') return;
  el.dataset.loaded = '1';
  const url = el.dataset.url;
  const idx = el.dataset.acc;
  if (!url) return;
  const ck = idx + '|' + url;  // ключ включает idx — иначе чужие/свои резюме затирают друг друга
  let data = _urlPreviewCache.get(ck);
  if (!data) {
    try {
      const r = await fetch(`/api/url_preview?idx=${encodeURIComponent(idx)}&url=${encodeURIComponent(url)}`);
      data = await r.json();
      _urlPreviewCache.set(ck, data);
    } catch(e) { return; }
  }
  if (!data || data.error) return;
  if (data.foreign_resume) {
    el.innerHTML = `<span style="color:var(--dim)" title="URL содержит чужой resume_hash — HH не отдаст вакансии">· 🔒 чужое резюме</span>`;
    return;
  }
  const parts = [];
  if (data.vacancies) parts.push(`<span style="color:var(--cyan)" title="Вакансий по этой выдаче">${data.vacancies.toLocaleString('ru')}</span>`);
  if (data.ratio > 0) {
    const ratioColor = data.ratio >= 50 ? 'var(--red)' : data.ratio >= 25 ? 'var(--yellow)' : 'var(--green)';
    const ratioIcon = data.ratio >= 50 ? '🔴' : data.ratio >= 25 ? '🟡' : '🟢';
    parts.push(`<span style="color:${ratioColor}" title="Активных соискателей на вакансию">${ratioIcon} ${data.ratio} ч/в</span>`);
  } else if (data.seekers > 0) {
    parts.push(`<span style="color:var(--dim)" title="Активных соискателей">👥${data.seekers}</span>`);
  }
  if (parts.length) el.innerHTML = `· ${parts.join(' · ')}`;
}

function _syncSuggestAccSel(snap) {
  const sel = document.getElementById('suggest-acc-sel');
  if (!sel || !snap?.accounts) return;
  const key = snap.accounts.map(a => a.idx + ':' + (a.name || a.short || '')).join('|');
  if (sel.dataset.key === key) return;
  sel.dataset.key = key;
  const prev = sel.value;
  sel.innerHTML = snap.accounts.map(a =>
    `<option value="${a.idx}">${esc(a.name || a.short || '')}</option>`).join('');
  if (prev) sel.value = prev;
}

async function suggestUrls(btn) {
  const sel = document.getElementById('suggest-acc-sel');
  const st = document.getElementById('suggest-status');
  const res = document.getElementById('suggest-result');
  if (!sel || !res) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Анализирую резюме (10-30с)...'; st.style.color = 'var(--dim)'; }
  res.style.display = 'none';
  try {
    const r = await fetch(`/api/account/${sel.value}/suggest_urls`);
    const data = await r.json();
    if (!data.ok) {
      if (st) { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
      return;
    }
    const items = data.suggestions || [];
    if (!items.length) {
      if (st) { st.textContent = '⚠️ Нет данных'; st.style.color = 'var(--yellow)'; }
      return;
    }
    if (st) { st.textContent = `✅ ${items.length} вариантов`; st.style.color = 'var(--green)'; }
    res.style.display = '';
    res.innerHTML = `<table class="applied-table" style="font-size:11px">
      <thead><tr>
        <th>Запрос</th>
        <th style="width:90px;text-align:right">Вакансий</th>
        <th style="width:100px;text-align:right">Конкуренция</th>
        <th style="width:60px"></th>
      </tr></thead>
      <tbody>${items.map(s => {
        const ratio = Number(s.ratio || 0);
        const ratioColor = ratio >= 50 ? 'var(--red)' : ratio >= 25 ? 'var(--yellow)' : ratio > 0 ? 'var(--green)' : 'var(--dim)';
        const ratioIcon = ratio >= 50 ? '🔴' : ratio >= 25 ? '🟡' : ratio > 0 ? '🟢' : '—';
        const ratioStr = ratio > 0 ? `${ratio} ч/в` : '—';
        return `<tr>
          <td>${esc(s.term)}</td>
          <td style="text-align:right">${(s.vacancies || 0).toLocaleString('ru')}</td>
          <td style="text-align:right;color:${ratioColor}">${ratioIcon} ${ratioStr}</td>
          <td><button class="btn-sm" onclick="suggestAddToPool('${esc(s.url)}',this)">➕</button></td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function suggestAddToPool(url, btn) {
  // Добавляем строку в видимый пул, отмечаем кнопку как добавлено.
  const container = document.getElementById('url-pool-rows');
  if (!container) return;
  // Проверим что уже не добавлено
  const existing = Array.from(container.querySelectorAll('.url-input')).some(i => i.value === url);
  if (existing) {
    if (btn) { btn.textContent = '✓'; btn.disabled = true; }
    return;
  }
  const newIdx = container.children.length;
  const div = document.createElement('div');
  div.innerHTML = buildPoolRow(url, newIdx);
  const row = div.firstElementChild;
  if (row) container.appendChild(row);
  if (btn) { btn.textContent = '✓'; btn.disabled = true; }
}

async function urlAccQuickAdd(accIdx, btn) {
  const input = document.getElementById(`acc-url-new-${accIdx}`);
  const st = document.getElementById(`url-quick-st-${accIdx}`);
  if (!input) return;
  let url = (input.value || '').trim();
  if (!url) { if (st) { st.textContent = '⚠️ Введи URL'; st.style.color = 'var(--yellow)'; } return; }
  // Auto-prefix https:// если юзер вставил без схемы
  if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
  // Принимаем основной hh.ru или *.hh.ru/search/
  if (!/^https:\/\/(?:[a-z0-9-]+\.)?hh\.ru\/search\//i.test(url)) {
    if (st) { st.textContent = '❌ Должен быть hh.ru/search/vacancy?…'; st.style.color = 'var(--red)'; }
    return;
  }
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Добавляю…'; st.style.color = 'var(--dim)'; }
  try {
    // 1. Подтянуть текущий url_pool
    const cfg = await (await fetch('/api/raw/config')).json();
    const pool = Array.isArray(cfg.url_pool) ? cfg.url_pool.slice() : [];
    const exists = pool.some(p => (typeof p === 'string' ? p : p?.url) === url);
    if (!exists) pool.push({ url: url, pages: cfg.pages_per_url || 40 });
    // 2. Сохранить пул
    const saved = await (await fetch('/api/raw/config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ url_pool: pool })
    })).json();
    if (!saved.ok) {
      if (st) { st.textContent = '❌ Не сохранилось: ' + (saved.error || JSON.stringify(saved.errors || {})); st.style.color = 'var(--red)'; }
      return;
    }
    // 3. Включить URL для этого аккаунта (добавить в его список + сохранить)
    const acc = (State.lastSnapshot?.accounts || []).find(a => a.idx === accIdx) || {};
    const accUrls = Array.isArray(acc.urls) ? acc.urls.slice() : [];
    if (!accUrls.includes(url)) accUrls.push(url);
    const setRes = await (await fetch(`/api/account/${accIdx}/set_urls`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ urls: accUrls, url_pages: acc.url_pages || {}, short: acc.short || '', name: acc.name || '' })
    })).json();
    if (setRes.ok) {
      input.value = '';
      if (st) { st.textContent = exists ? `✅ Уже в пуле — включил для аккаунта (${setRes.count} URL)` : `✅ Добавлено в пул и включил (${setRes.count} URL)`; st.style.color = 'var(--green)'; }
      // Принудительно перерендерим чекбоксы этой карточки СРАЗУ, не ждём
      // следующего WS-тика (300мс) и не зависим от open-guard'а в syncAccUrlChecks.
      try {
        const container = document.getElementById(`acc-url-checks-${accIdx}`);
        const localAcc = { ...acc, urls: accUrls };
        if (container) _renderAccUrlChecksInto(container, localAcc, pool);
      } catch(e) {}
    } else {
      const hint = setRes.hint ? ' (' + setRes.hint + ')' : '';
      if (st) { st.textContent = '⚠️ В пул сохранил, но включить не вышло: ' + (setRes.error || 'ошибка') + hint; st.style.color = 'var(--yellow)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    setTimeout(() => { if (st) st.textContent = ''; }, 6000);
  }
}

async function urlAccSave(accIdx, btn) {
  const container = document.getElementById(`acc-url-checks-${accIdx}`);
  if (!container) return;
  const urls = Array.from(container.querySelectorAll('input[type=checkbox]:checked'))
    .map(cb => cb.value).filter(Boolean);
  // Collect per-URL pages overrides
  const url_pages = {};
  container.querySelectorAll('.acc-url-pages-inp').forEach(inp => {
    const v = parseInt(inp.value);
    if (v > 0) url_pages[inp.dataset.url] = v;
  });
  const st = document.getElementById(`url-acc-st-${accIdx}`);
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    // Дублируем short/name из snapshot — бэкенд использует их как fallback,
    // если idx устарел (после удаления другой сессии / рестарта).
    const acc = (State.lastSnapshot?.accounts || []).find(a => a.idx === accIdx) || {};
    const res = await fetch(`/api/account/${accIdx}/set_urls`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({urls, url_pages, short: acc.short || '', name: acc.name || ''})
    });
    const data = await res.json();
    if (data.ok) {
      if (st) { st.textContent = `✅ ${data.count} URL`; st.style.color = 'var(--green)'; }
    } else {
      const hint = data.hint ? ' (' + data.hint + ')' : '';
      if (st) { st.textContent = '❌ ' + (data.error||'Ошибка') + hint; st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    setTimeout(() => { if (st) st.textContent = ''; }, 4000);
  }
}

// ── Main accounts management ──────────────────────────────────
const ACC_COLORS = ['cyan','magenta','green','yellow','blue','red'];

async function accDeleteCard(idx, btn) {
  // Determine if this is a temp (browser session) account or regular
  const acc = (State.lastSnapshot?.accounts || []).find(a => a.idx === idx);
  const isTemp = acc?.temp === true;
  const url = isTemp ? `/api/session/${idx}` : `/api/account/${idx}/delete`;
  // showConfirm теперь textContent — никаких HTML-тегов, иначе они показываются буквально.
  const label = isTemp ? `сессию ${acc?.name || '#'+idx}` : `аккаунт #${idx}`;

  // Защита от double-click: блокируем кнопку ДО показа диалога.
  if (btn) btn.disabled = true;
  try {
    if (!await showConfirm(`Удалить ${label}? Действие необратимо.`)) {
      if (btn) btn.disabled = false;
      return;
    }
    const res = await fetch(url, {method: 'DELETE'});
    const data = await res.json();
    if (data.ok || data.status === 'ok') {
      removeAccountFromCurrentSnapshot(idx);
    } else {
      alert('Ошибка: ' + (data.error || data.message || JSON.stringify(data)));
      if (btn) btn.disabled = false;
    }
  } catch(e) {
    alert('Ошибка: ' + e);
    if (btn) btn.disabled = false;
  }
}

function removeAccountFromCurrentSnapshot(idx) {
  const snap = State.lastSnapshot;
  if (!snap || !Array.isArray(snap.accounts)) return;
  snap.accounts = snap.accounts
    .filter(a => Number(a.idx) !== Number(idx))
    .map(a => Number(a.idx) > Number(idx) ? {...a, idx: Number(a.idx) - 1} : a);
  renderAll(snap);
}

// ── Browser sessions management in Settings ──────────────────
function buildSessList(snap) {
  const el = document.getElementById('sess-list');
  if (!el) return;
  const sessions = (snap?.accounts || []).filter(a => a.temp);
  if (!sessions.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--dim);margin-bottom:8px">Нет сессий — добавьте первую ниже.</div>';
    delete el.dataset.fingerprint;  // иначе следующий 1-сессии рендер совпадёт с прошлым fingerprint и скипнется
    return;
  }
  // Build fingerprint of session data — rebuild on any change.
  // count нужен в fingerprint, иначе после delete+add того же idx detail не меняется.
  const fingerprint = sessions.length + '|' + sessions.map(a => `${a.idx}:${a.bot_active}:${a.cookies_expired}:${a.name||''}`).join('|');
  if (el.dataset.fingerprint === fingerprint) return;
  el.dataset.fingerprint = fingerprint;
  el.innerHTML = '';
  sessions.forEach(acc => {
    const div = document.createElement('div');
    div.id = `sess-row-${acc.idx}`;
    div.style.cssText = 'margin-bottom:8px;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px';
    div.innerHTML =
      `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">` +
        `<div>` +
          `<span style="font-size:12px;font-weight:600;color:var(--yellow)">${esc(acc.name)}</span>` +
          `<span style="font-size:11px;color:var(--dim);margin-left:8px">${acc.bot_active ? t('sess_active') : t('sess_inactive')}</span>` +
          (acc.cookies_expired ? `<span style="font-size:10px;color:var(--red);margin-left:6px">⚠️ куки</span>` : `<span style="font-size:10px;color:var(--green);margin-left:6px">🍪 ок</span>`) +
        `</div>` +
        `<div style="display:flex;gap:6px">` +
          (!acc.bot_active ? `<button class="btn-sm" style="color:var(--green);border-color:var(--green)" onclick="sessActivate(${acc.idx},this)">▶ Запустить</button>` : '') +
          `<button class="btn-sm" onclick="sessEditToggle(${acc.idx})">✏️ Изменить</button>` +
          `<button class="btn-sm" style="color:var(--red);border-color:var(--red)" onclick="sessionRemove(${acc.idx})">🗑️</button>` +
        `</div>` +
      `</div>` +
      `<div style="font-size:11px;color:var(--dim)">` +
        `resume_hash: <b style="font-family:monospace;color:var(--text)">${esc((acc.resume_hash||'').slice(0,14))}...</b>` +
      `</div>` +
      `<div id="sess-edit-form-${acc.idx}" style="display:none;margin-top:10px">` +
        `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">` +
          `<div><div style="font-size:11px;color:var(--dim);margin-bottom:3px">Имя</div>` +
            `<input id="sess-edit-name-${acc.idx}" class="apply-input" style="font-size:11px" value="${esc(acc.name)}"></div>` +
          `<div><div style="font-size:11px;color:var(--dim);margin-bottom:3px">Короткое</div>` +
            `<input id="sess-edit-short-${acc.idx}" class="apply-input" style="font-size:11px" value="${esc(acc.short||'')}"></div>` +
          `<div><div style="font-size:11px;color:var(--dim);margin-bottom:3px">Цвет</div>` +
            `<select id="sess-edit-color-${acc.idx}" class="apply-input" style="font-size:11px">` +
              ACC_COLORS.map(c => `<option value="${c}"${c===(acc.color||'yellow')?' selected':''}>${c}</option>`).join('') +
            `</select></div>` +
          `<div><div style="font-size:11px;color:var(--dim);margin-bottom:3px">resume_hash</div>` +
            `<input id="sess-edit-hash-${acc.idx}" class="apply-input" style="font-size:11px;font-family:monospace" value="${esc(acc.resume_hash||'')}"></div>` +
        `</div>` +
        `<div style="margin:8px 0 10px">` +
          `<div style="font-size:11px;color:var(--dim);margin-bottom:3px">Обновить куки (cURL или строка cookie)</div>` +
          `<textarea id="sess-edit-cookies-${acc.idx}" class="apply-input" rows="3" style="font-size:11px;margin-bottom:6px" ` +
            `placeholder="curl 'https://hh.ru/...' -b 'hhtoken=...' ...&#10;— или: hhtoken=xxx; _xsrf=yyy; ..."></textarea>` +
          `<div style="display:flex;gap:8px;align-items:center">` +
            `<button class="btn-sm" onclick="updateCookiesFromTextarea(${acc.idx}, 'sess-edit-cookies-${acc.idx}', 'sess-edit-cookie-st-${acc.idx}')">🔑 Обновить куки</button>` +
            `<span id="sess-edit-cookie-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>` +
          `</div>` +
        `</div>` +
        `<div style="display:flex;gap:8px;align-items:center">` +
          `<button class="btn-sm" onclick="sessProfileSave(${acc.idx},this)">💾 Сохранить</button>` +
          `<span id="sess-edit-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>` +
        `</div>` +
      `</div>`;
    el.appendChild(div);
  });
}

async function sessActivate(idx, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Запуск…'; }
  try {
    const res = await fetch(`/api/session/${idx}/activate`, {method: 'POST'});
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) {}
    const success = res.ok && (data.ok === true || data.status === 'ok');
    if (success) {
      const listEl = document.getElementById('sess-list');
      // buildSessList использует fingerprint, а не count. Сбрасываем именно
      // его, чтобы ближайший WS snapshot заменил кнопку на активный статус.
      if (listEl) listEl.dataset.fingerprint = '';
    } else {
      const reason = data.message || data.error || data.detail || text || `HTTP ${res.status}`;
      alert('Ошибка: ' + reason);
      if (btn) { btn.disabled = false; btn.textContent = '▶ Запустить'; }
    }
  } catch(e) {
    alert('Сетевая ошибка: ' + (e?.message || String(e)));
    if (btn) { btn.disabled = false; btn.textContent = '▶ Запустить'; }
  }
}

async function touchToggle(idx, el) {
  if (!el) return;
  const wasOn = el.classList.contains('on');
  // оптимистично переключаем сразу
  el.classList.toggle('on', !wasOn);
  el.classList.toggle('off', wasOn);
  const lbl = document.getElementById('acc-touch-label-' + idx);
  if (lbl) lbl.textContent = !wasOn ? '🔁 вкл' : '⏸ выкл';
  try {
    const res = await fetch(`/api/account/${idx}/resume_touch_toggle`, {method: 'POST'});
    if (!res.ok) throw new Error(res.status);
    // финальное состояние придёт через WebSocket
  } catch(e) {
    // откат
    el.classList.toggle('on', wasOn);
    el.classList.toggle('off', !wasOn);
    if (lbl) lbl.textContent = wasOn ? '🔁 вкл' : '⏸ выкл';
  }
}

async function resumeTouchNow(idx, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ поднимаю...'; btn.style.color = ''; }
  try {
    await fetch(`/api/account/${idx}/resume_touch`, {method: 'POST'});
    // держим disabled — updateCard разблокирует кнопку когда придёт реальный таймер
    if (btn) btn.setAttribute('data-touching', '1');
    // страховка: разблокировать через 15с если WebSocket не пришёл
    setTimeout(() => {
      if (btn && btn.getAttribute('data-touching')) {
        btn.removeAttribute('data-touching');
        btn.disabled = false;
        btn.textContent = '📤 Поднять';
        btn.style.color = '';
      }
    }, 15000);
  } catch(e) {
    if (btn) { btn.textContent = '❌'; btn.style.color = 'var(--red)'; btn.disabled = false; btn.removeAttribute('data-touching'); }
  }
}

function sessEditToggle(idx) {
  const form = document.getElementById(`sess-edit-form-${idx}`);
  if (form) form.style.display = form.style.display === 'none' ? 'block' : 'none';
}

async function sessProfileSave(idx, btn) {
  const st = document.getElementById(`sess-edit-st-${idx}`);
  const body = {
    name:        document.getElementById(`sess-edit-name-${idx}`)?.value.trim(),
    short:       document.getElementById(`sess-edit-short-${idx}`)?.value.trim(),
    color:       document.getElementById(`sess-edit-color-${idx}`)?.value,
    resume_hash: document.getElementById(`sess-edit-hash-${idx}`)?.value.trim(),
  };
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch(`/api/session/${idx}/profile`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.ok) {
      if (st) { st.textContent = '✅ Сохранено'; st.style.color = 'var(--green)'; }
      const listEl = document.getElementById('sess-list');
      if (listEl) listEl.dataset.count = '';
    } else {
      if (st) { st.textContent = '❌ ' + (data.error||'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    setTimeout(() => { if (st) st.textContent = ''; }, 4000);
  }
}

// Build/refresh account cookies list from snapshot
function buildAccCookiesList(snap) {
  const el = document.getElementById('acc-cookies-list');
  if (!el) return;
  const accs = (snap?.accounts || []);
  if (!accs.length) { el.innerHTML = '<div class="c-dim" style="font-size:12px">Нет аккаунтов</div>'; return; }
  // Only rebuild if account count changed
  if (el.dataset.count === String(accs.length)) return;
  el.dataset.count = String(accs.length);
  el.innerHTML = '';
  accs.forEach(acc => {
    const colorStyle = `color:${colorVar(acc.color || 'text')}`;
    const div = document.createElement('div');
    div.style.cssText = 'margin-bottom:14px;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px';
    div.innerHTML =
      `<div style="font-size:12px;font-weight:600;margin-bottom:6px;${colorStyle}">${esc(acc.name)}</div>` +
      `<textarea id="ck-ta-${acc.idx}" class="apply-input" rows="2" style="font-size:11px;margin-bottom:6px" ` +
        `placeholder="curl 'https://hh.ru/...' -H 'cookie: hhtoken=...' ...&#10;— или: hhtoken=xxx; _xsrf=yyy; hhul=zzz; crypted_id=aaa"></textarea>` +
      `<div style="display:flex;gap:8px;align-items:center">` +
        `<button class="btn-sm" onclick="updateAccCookies(${acc.idx})">${t('btn_update_cookies')}</button>` +
        `<span id="ck-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>` +
      `</div>`;
    el.appendChild(div);
  });
}

async function updateAccCookies(idx) {
  return updateCookiesFromTextarea(idx, 'ck-ta-' + idx, 'ck-st-' + idx);
}

async function updateCookiesFromTextarea(idx, textareaId, statusId) {
  const ta = document.getElementById(textareaId);
  const st = document.getElementById(statusId);
  const val = ta?.value.trim();
  if (!val) { if (st) { st.textContent = '❌ Пусто'; st.style.color = 'var(--red)'; } return; }
  if (st) { st.textContent = '⏳ Обновляю...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch(`/api/account/${idx}/update_cookies`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cookies: val})
    });
    const data = await res.json();
    if (data.ok) {
      if (ta) ta.value = '';
      if (st) { st.textContent = `✅ Обновлено (${(data.keys||[]).length} ключей)`; st.style.color = 'var(--green)'; }
    } else {
      if (st) { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  }
}

function applySettings() {
  SETTINGS_DEF.forEach(s => {
    const el = document.getElementById('sr-' + s.key);
    if (el) {
      const value = Number(el.value);
      // Оставляем значение pending до snapshot-подтверждения от backend.
      // Иначе следующий ещё старый snapshot визуально отменит изменение.
      State.settingsDrafts.set(s.key, value);
      sendCmd({ type: 'set_config', key: s.key, value });
    }
  });
  const st = document.getElementById('settings-status');
  st.textContent = t('settings_applied');
  setTimeout(() => { st.textContent = ''; }, 3000);
}

// ── WebSocket ──────────────────────────────────────────────────
function connect() {
  // Защита от flapping (error→close→error): иначе несколько setTimeout повисают
  // и плодят дубликаты соединений.
  if (State.reconnectTimer) {
    clearTimeout(State.reconnectTimer);
    State.reconnectTimer = null;
  }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  // API key из ?key=... или localStorage передаём в WS upgrade (HH_BOT_API_KEY).
  const _apiKey = (new URLSearchParams(location.search).get('key') || localStorage.getItem('hh-api-key') || '').trim();
  if (_apiKey) localStorage.setItem('hh-api-key', _apiKey);
  const wsUrl = _apiKey
    ? `${proto}://${location.host}/ws?api_key=${encodeURIComponent(_apiKey)}`
    : `${proto}://${location.host}/ws`;
  const ws = new WebSocket(wsUrl);
  State.ws = ws;

  ws.onopen = () => {
    if (State.ws !== ws) return;
    document.getElementById('conn-dot').classList.add('connected');
    State.reconnectDelay = 1000;
    // Аудит 2026-08-17 #16: раньше onopen делал disabled=false ВСЕМ кнопкам,
    // включая кнопки in-flight async операций (save/apply/toggle) → юзер мог
    // повторно кликнуть и запустить дубликат. Снимаем только у тех, у кого
    // стоит наш ws-marker (был выключен ИМЕННО из-за разрыва WS).
    document.querySelectorAll('button[data-ws-disabled="1"]').forEach(b => {
      b.disabled = false;
      b.removeAttribute('data-ws-disabled');
    });
    tickAccountActivities(); // old connection's snapshot is not fresh on reconnect
  };

  ws.onmessage = (ev) => {
    if (State.ws !== ws) return;
    try {
      const snap = JSON.parse(ev.data);
      if (snap.type === 'state_update') {
        // Cap large arrays — иначе lastSnapshot копит память за дни uptime
        // (kimi-r14-3 #6). Render-функции уже slice'ят, но source держится в State.
        if (Array.isArray(snap.log)) snap.log = snap.log.slice(-State.MAX_LOG_NODES);
        if (Array.isArray(snap.recent_responses)) snap.recent_responses = snap.recent_responses.slice(-100);
        if (Array.isArray(snap.llm_log)) snap.llm_log = snap.llm_log.slice(-200);
        State.lastSnapshot = snap;
        State.snapshotReceivedAt = performance.now();
        State.snapshotServerAt = activityTimestamp(snap.snapshot_at);
        State.snapshotSocket = ws;
        try {
          renderAll(snap);
          const dbg = document.getElementById('dbg-err');
          if (dbg) dbg.style.display = 'none';
        } catch (renderErr) {
          const dbg = document.getElementById('dbg-err');
          if (dbg) { dbg.style.display = ''; dbg.textContent = 'JS ERROR: ' + renderErr; }
          console.error('renderAll error:', renderErr);
        }
      }
    } catch (e) { console.error('WS parse error:', e); }
  };

  ws.onclose = (ev) => {
    if (State.ws !== ws) return;
    document.getElementById('conn-dot').classList.remove('connected');
    tickAccountActivities();
    // Помечаем ws-marker'ом, чтобы onopen снял disabled только с этих кнопок
    // и не тронул те, что заблокированы in-flight операциями (аудит #16).
    document.querySelectorAll('.btn-sm, .apply-btn, button[onclick]').forEach(b => {
      if (!b.disabled) {
        b.disabled = true;
        b.setAttribute('data-ws-disabled', '1');
      }
    });
    showCommandError('Нет связи с панелью. Команды паузы недоступны; состояние аккаунтов может быть устаревшим. Ожидаем переподключения.');
    // 4401 = server отверг api_key. Бесконечный reconnect — спам и пустой стрим
    // ошибок в логах (kimi-r14-2 #10). Останавливаем и показываем баннер.
    if (ev && ev.code === 4401) {
      const dot = document.getElementById('conn-dot');
      if (dot) dot.title = 'Unauthorized — нужен API key (?key=…)';
      const dbg = document.getElementById('dbg-err');
      if (dbg) {
        dbg.style.display = '';
        dbg.textContent = 'Нет доступа — введите API-ключ для этого устройства.';
      }
      showApiKeyPrompt();
      return;  // прекращаем reconnect-цикл до перезагрузки страницы
    }
    State.reconnectTimer = setTimeout(() => {
      State.reconnectDelay = Math.min(State.reconnectDelay * 2, 30000);
      connect();
    }, State.reconnectDelay);
  };

  ws.onerror = (e) => { console.error('WS error:', e); ws.close(); };
}

function showApiKeyPrompt() {
  if (document.getElementById('api-key-prompt')) return;
  const overlay = document.createElement('div');
  overlay.id = 'api-key-prompt';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(5,9,14,.92);display:flex;align-items:center;justify-content:center;padding:18px';
  overlay.innerHTML = `
    <form style="width:min(430px,100%);background:var(--bg-card);border:1px solid var(--red);border-radius:10px;padding:20px;box-shadow:0 18px 60px #000">
      <div style="font-size:18px;font-weight:700;margin-bottom:9px">🔐 Требуется доступ</div>
      <div style="color:var(--dim);font-size:13px;line-height:1.45;margin-bottom:14px">
        На этом устройстве ещё не сохранён API-ключ. Введите его один раз — он останется только в хранилище этого браузера.
      </div>
      <input type="password" autocomplete="current-password" required placeholder="API-ключ"
        style="box-sizing:border-box;width:100%;padding:10px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--text);margin-bottom:12px">
      <button type="submit" style="width:100%;padding:10px;border:1px solid var(--green);border-radius:5px;background:rgba(63,185,80,.13);color:var(--green);cursor:pointer">Войти</button>
    </form>`;
  overlay.querySelector('form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const key = overlay.querySelector('input').value.trim();
    if (!key) return;
    localStorage.setItem('hh-api-key', key);
    // Удаляем возможный неверный ?key= из URL: он имеет приоритет над storage.
    const url = new URL(location.href);
    url.searchParams.delete('key');
    location.replace(url.toString());
  });
  document.body.appendChild(overlay);
  overlay.querySelector('input').focus();
}

function showCommandError(message) {
  const dbg = document.getElementById('dbg-err');
  if (dbg) {
    dbg.style.display = '';
    dbg.style.whiteSpace = 'normal';
    dbg.style.overflowWrap = 'anywhere';
    dbg.setAttribute('role', 'alert');
    dbg.textContent = message;
    dbg.title = message;
  }
}

function sendCmd(obj) {
  if (!State.ws || State.ws.readyState !== 1) {
    showCommandError('Нет связи с панелью: команда не отправлена и не поставлена в очередь. Дождитесь подключения и проверьте состояние.');
    return false;
  }
  if (obj?.type === 'account_pause') {
    const acc = State.lastSnapshot?.accounts?.find(a => a.idx === obj.idx);
    if (acc?.paused && hasUnknownApplication(acc)) {
      showCommandError('Исход отклика неизвестен. Сначала нужна сверка в HH; обычное продолжение заблокировано, чтобы не повторить отклик.');
      return false;
    }
    if (acc?.paused && acc.paused_reason === 'auth') {
      showCommandError(acc.mode === 'oauth'
        ? 'Сначала подтвердите вход в HH кнопкой «Проверить вход и продолжить». Обычное продолжение не снимает эту защитную паузу.'
        : 'Восстановите вход в HH для этого аккаунта. Обычное продолжение не снимает защитную паузу авторизации.');
      return false;
    }
    if (acc?.paused && acc.paused_reason === 'network_error') {
      showCommandError(acc.mode === 'oauth'
        ? 'Связь с HH ещё не подтверждена. Используйте «Проверить связь и продолжить» или дождитесь серверной проверки; обычное продолжение не снимает эту защитную паузу.'
        : 'Восстановите связь и доступ к HH для этого аккаунта. Обычное продолжение не снимает защитную паузу сети.');
      return false;
    }
  }
  try {
    State.ws.send(JSON.stringify(obj));
    return true;
  } catch (_) {
    showCommandError('Не удалось передать команду панели. Она не повторяется автоматически; проверьте связь и состояние аккаунта.');
    return false;
  }
}

// ── Rendering ──────────────────────────────────────────────────
function renderAll(snap) {
  syncAccountDependentUi(snap);
  renderHeader(snap);
  updateHeaderResumeStats(snap);
  syncLetterSelects(snap);
  syncAccUrlChecks(snap);
  syncLlmSettings(snap);
  syncCaptchaMode(snap.config);
  syncScheduleSettings(snap);
  syncAuditSelector(snap);
  updateLlmStatusBar(snap);
  // Sliders are built before the first WebSocket snapshot arrives. Without this
  // sync they keep their HTML minimum and the value label stays as an em dash
  // until the user switches away from Settings and back.
  if (State.currentTab === 'settings') syncSettingsSliders(snap);
  updatePageTitle(snap);
  checkNotifications(snap);
  if (State.currentTab === 'main') renderMain(snap);
  else if (State.currentTab === 'log') renderLog(snap);
  else if (State.currentTab === 'hh') renderHH(snap);
  else if (State.currentTab === 'llm') renderLlmLog(snap);
  else if (State.currentTab === 'views') loadViews();
  else if (State.currentTab === 'settings') {
    buildAccCookiesList(snap);
    buildSessList(snap);
    _syncSuggestAccSel(snap);
  }
  else if (State.currentTab === 'apply') {
    applyBuildAccountSelect(snap);
  }
  // Опциональные feature-модули получают тот же фактический WS snapshot.
  // Вызов через публичный API работает и для лексической renderAll(), которую
  // невозможно надёжно перехватить заменой window.renderAll.
  if (window.WsToggle && typeof window.WsToggle.syncSnapshot === 'function') {
    window.WsToggle.syncSnapshot(snap);
  }
  // applied/tests/views rendered on tab switch
}

let _accountIdentityByIdx = new Map();
function syncAccountDependentUi(snap) {
  const accounts = Array.isArray(snap?.accounts) ? snap.accounts : [];
  const next = new Map(accounts.map(a => [
    String(a.idx), `${a.temp ? 't' : 'r'}|${a.resume_hash || ''}|${a.name || a.short || ''}`
  ]));
  for (const [idx, identity] of _accountIdentityByIdx) {
    if (next.get(idx) !== identity) {
      delete _AccDiagCache[idx];
      delete ApplyLetters[idx];
      delete State.prevInterviews[idx];
      delete State.prevLimitState[idx];
      delete State.prevCookiesExpired[idx];
      State.authChecks.delete(Number(idx));
      for (const key of [..._urlPreviewCache.keys()]) {
        if (String(key).startsWith(idx + '|')) _urlPreviewCache.delete(key);
      }
    }
  }
  _accountIdentityByIdx = next;
  if (typeof window.JobStatusSyncAccounts === 'function') window.JobStatusSyncAccounts();
  if (typeof hediAccounts === 'function') hediAccounts();
}

function updatePageTitle(snap) {
  const hasLimit = (snap.accounts || []).some(a => a.status === 'limit');
  const sent = snap.global_stats?.total_sent || 0;
  if (hasLimit) {
    document.title = t('title_limit');
  } else if (snap.paused) {
    document.title = t('title_paused');
  } else if (sent > 0) {
    document.title = `✅ ${sent} откл. | HH Bot`;
  } else {
    document.title = 'HH Bot Dashboard';
  }
}

function checkNotifications(snap) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  // На первом snapshot инициализируем prev-state без алертов — иначе любой
  // reload страницы с уже-в-лимите аккаунтом стреляет нотификацией заново.
  const isFirstSnapshot = !State.notificationsInited;
  (snap.accounts || []).forEach(acc => {
    const prevInv = State.prevInterviews[acc.idx] ?? acc.hh_interviews;
    if (!isFirstSnapshot && acc.hh_interviews > prevInv) {
      sendBotNotification(
        `${t('notif_new_inv')}${acc.short}`,
        `${t('notif_inv_count_pre')} ${acc.hh_interviews} ${t('notif_inv_count_mid')}${acc.hh_interviews - prevInv})`
      );
    }
    State.prevInterviews[acc.idx] = acc.hh_interviews;

    const wasLimit = State.prevLimitState[acc.idx];
    if (!isFirstSnapshot && acc.status === 'limit' && !wasLimit) {
      sendBotNotification(`${t('notif_limit')}${acc.short}`, t('notif_limit_body'));
    }
    State.prevLimitState[acc.idx] = acc.status === 'limit';

    const wasExpired = State.prevCookiesExpired[acc.idx];
    if (!isFirstSnapshot && acc.cookies_expired && !wasExpired) {
      sendBotNotification(`${t('notif_cookies')}${acc.short}`, t('notif_cookies_body'));
    }
    State.prevCookiesExpired[acc.idx] = acc.cookies_expired;
    State.prevCaptchaState ??= {};
    const needsCaptcha = acc.paused && acc.paused_reason === 'challenge';
    if (!isFirstSnapshot && needsCaptcha && !State.prevCaptchaState[acc.idx]) {
      sendBotNotification('HH: нужна капча', 'Отправки остановлены. Откройте карточку аккаунта и нажмите «Пройти капчу на HH».');
    }
    State.prevCaptchaState[acc.idx] = needsCaptcha;
  });
  State.notificationsInited = true;
}

function sendBotNotification(title, body) {
  try { new Notification(title, { body, icon: '/favicon.ico' }); } catch(e) {}
}

function fmtUptime(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}ч ${String(m).padStart(2,'0')}м`;
  return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}

function renderHeader(snap) {
  document.getElementById('uptime').textContent = '⏱ ' + fmtUptime(snap.uptime_seconds);
  // Без optional chaining упавший snapshot (missing global_stats) валит весь UI.
  const gs = snap.global_stats || {};
  document.getElementById('global-found').textContent = gs.total_found ?? 0;
  document.getElementById('global-sent').textContent = gs.total_sent ?? 0;
  document.getElementById('storage-total').textContent = gs.storage_total ?? 0;
  document.getElementById('storage-tests').textContent = gs.storage_tests ?? 0;

  // Daily counter
  const dailyEl = document.getElementById('hdr-daily-counter');
  if (dailyEl) {
    const accs = snap.accounts || [];
    const totalDaily = accs.reduce((s, a) => s + (a.daily_sent || 0), 0);
    const limit = snap.config?.daily_apply_limit || 0;
    const stopped = accs.some(a => a.hard_stopped);
    if (limit > 0) {
      dailyEl.textContent = `(${totalDaily}/${limit} сегодня)`;
      dailyEl.style.color = totalDaily >= limit ? 'var(--red)' : 'var(--yellow)';
    } else if (totalDaily > 0) {
      dailyEl.textContent = `(${totalDaily} сегодня)`;
      dailyEl.style.color = stopped ? 'var(--red)' : 'var(--yellow)';
    } else {
      dailyEl.textContent = '';
    }
  }

  // Smart search filter badges
  const filterEl = document.getElementById('hdr-filters');
  if (filterEl && snap.config) {
    const badges = [];
    if (snap.config.filter_agencies) badges.push('🏢 Без агентств');
    if (snap.config.remote_it_only) badges.push('ИТ · только удалёнка');
    if (snap.config.filter_low_competition) badges.push('🎯 <10 откликов');
    if (snap.config.search_period_days > 0) badges.push(`📅 ${snap.config.search_period_days}д`);
    const protectedCount = (snap.accounts || []).filter(a => a.safety_enabled).length;
    if (protectedCount) badges.push(`🛡️ Защита ${protectedCount}/${(snap.accounts || []).length}`);
    filterEl.innerHTML = badges.map(b => `<span style="background:rgba(57,208,216,0.12);color:var(--cyan);padding:1px 6px;border-radius:3px;font-size:9px">${b}</span>`).join(' ');
  }

  const btn = document.getElementById('pause-btn');
  if (btn) {
    if (snap.paused) {
      btn.textContent = t('btn_resume');
      btn.classList.add('paused');
    } else {
      const pausedAccs = (snap.accounts || []).filter(a => a.paused).length;
      btn.textContent = pausedAccs ? `${t('btn_pause')} (${pausedAccs})` : t('btn_pause');
      btn.classList.remove('paused');
    }
  }

  const pauseControl = document.getElementById('pause-btn');
  if (pauseControl) {
    pauseControl.disabled = !State.ws || State.ws.readyState !== 1;
    pauseControl.title = pauseControl.disabled ? 'Нет связи с панелью: команда паузы недоступна' : '';
  }

  // Apply mode badge — show per-account summary
  const modeBadge = document.getElementById('apply-mode-badge');
  if (modeBadge) {
    const accs = snap.accounts || [];
    const oauthCount = accs.filter(a => a.use_oauth).length;
    const globalOAuth = snap.config?.use_oauth_apply;
    if (oauthCount > 0 || globalOAuth) {
      const label = globalOAuth ? '🔑 OAuth (все)' : `🔑 OAuth (${oauthCount}/${accs.length})`;
      modeBadge.textContent = label;
      modeBadge.style.background = 'rgba(63,185,80,0.15)';
      modeBadge.style.color = 'var(--green)';
    } else {
      modeBadge.textContent = '🌐 Web';
      modeBadge.style.background = 'rgba(57,208,216,0.15)';
      modeBadge.style.color = 'var(--cyan)';
    }
  }
}

// ── Main tab ──
function renderMain(snap) {
  renderAccounts(snap);
  renderGlobalStats(snap);
  renderRecentResponses(snap);
}

const STATUS_MAP = {
  idle:       ['⏸', 'status_idle',       'status-idle'],
  collecting: ['📥', 'status_collecting', 'status-collecting'],
  applying:   ['📤', 'status_applying',   'status-applying'],
  limit:      ['🚫', 'status_limit',      'status-limit'],
  waiting:    ['⏳', 'status_waiting',    'status-waiting'],
  checking:   ['🔍', 'status_checking',   'status-checking'],
  '—':        ['⭕', 'status_inactive',   'status-idle'],
};

function renderAccounts(snap) {
  const grid = document.getElementById('accounts-grid');
  // Пустое состояние — нет аккаунтов
  let emptyEl = document.getElementById('accounts-empty');
  if (!snap.accounts || snap.accounts.length === 0) {
    // Удалить старые карточки которые остались от предыдущего стейта
    // (иначе после wipe аккаунт продолжает висеть до перезагрузки страницы).
    grid.querySelectorAll('.acc-card').forEach(el => el.remove());
    if (!emptyEl) {
      emptyEl = document.createElement('div');
      emptyEl.id = 'accounts-empty';
      emptyEl.style.cssText = 'grid-column:1/-1;text-align:center;padding:48px 16px;color:var(--dim);font-size:14px';
      emptyEl.innerHTML = `<div style="font-size:32px;margin-bottom:12px">📭</div>${t('no_accounts')}`;
      grid.appendChild(emptyEl);
    }
    return;
  }
  if (emptyEl) emptyEl.remove();
  // Убираем карточки которых больше нет
  const alive = new Set(snap.accounts.map(a => 'card-' + a.idx));
  grid.querySelectorAll('.acc-card').forEach(el => {
    if (el.id && !alive.has(el.id)) el.remove();
  });
  snap.accounts.forEach(acc => {
    let card = document.getElementById('card-' + acc.idx);
    // Действия временной сессии зависят от bot_active (Стоп/Запустить).
    // Перестраиваем карточку при смене состояния, иначе старая кнопка остаётся.
    const identity = `${acc.temp ? 't' : 'r'}|${acc.resume_hash || ''}|${acc.name || acc.short || ''}|${acc.temp ? Boolean(acc.bot_active) : ''}`;
    if (card && card.dataset.accountIdentity !== identity) {
      card.remove();
      card = null;
    }
    if (!card) {
      card = document.createElement('div');
      card.id = 'card-' + acc.idx;
      card.className = 'acc-card color-' + (acc.color || 'yellow');
      card.dataset.accountIdentity = identity;
      card.innerHTML = buildCardHTML(acc);
      grid.appendChild(card);
      // Диагностику не дёргаем сразу для всех — иначе на старте N запросов
      // подряд + 700KB SSR HTML каждый. Отложим на 2с после первого рендера.
      setTimeout(() => _accDiagAutoLoad(acc.idx), 2000 + acc.idx * 500);
    } else {
      card.className = 'acc-card color-' + (acc.color || 'yellow');
      updateCard(card, acc);
    }
  });
}

function buildCardHTML(acc) {
  return `
    <div class="acc-header">
      <div class="acc-name" id="acc-name-${acc.idx}">${esc(acc.name)}</div>
      <button class="compact-btn" title="Свернуть/развернуть карточку" onclick="toggleCompact(${acc.idx})">⬜</button>
      <button class="compact-btn" title="Удалить аккаунт" style="color:var(--red);margin-left:2px" onclick="accDeleteCard(${acc.idx}, this)">🗑</button>
      <div class="acc-status-badge status-idle" id="acc-badge-${acc.idx}">⏸ ${t('status_idle')}</div>
      <button id="acc-oauth-btn-${acc.idx}" style="font-size:9px;padding:1px 6px;border-radius:3px;border:1px solid;cursor:pointer;background:transparent;margin-left:4px;color:${acc.use_oauth ? 'var(--green)' : 'var(--cyan)'};border-color:${acc.use_oauth ? 'var(--green)' : 'var(--cyan)'}"
        onclick="oauthToggleAccount(${acc.idx},this)" title="Метод откликов: OAuth API или Web cookies">${acc.use_oauth ? '🔑API' : '🌐Web'}</button>
    </div>
    <section class="acc-activity" id="acc-activity-${acc.idx}" aria-label="Текущий этап работы">
      <div class="acc-activity-heading"><span class="acc-activity-eyebrow">Состояние бота</span> <span class="acc-activity-chip" data-activity="phase">Ожидаем данные</span></div>
      <div class="acc-activity-current" data-activity="current">Ожидаем состояние панели</div>
      <div class="acc-activity-next"><span class="acc-activity-label">Следующий шаг</span> <span data-activity="next">Пока не указано сервером</span></div>
      <div class="acc-activity-action" data-activity="action" hidden></div>
      <div class="acc-activity-meta" data-activity="progress" hidden></div>
      <progress class="acc-activity-meter" data-activity-meter aria-label="Прогресс текущего этапа" max="100" hidden></progress>
      <div class="acc-activity-meta" data-activity="time" hidden></div>
      <div class="acc-network-meta" data-activity="network" hidden></div>
      <div class="acc-search-box"><div class="acc-search-label">Почему ждём</div><div class="acc-search-summary" data-activity="situation" hidden></div></div>
      <section class="acc-cycle" id="acc-cycle-${acc.idx}" aria-label="Отчёт за цикл">
        <div class="acc-cycle-heading"><span data-cycle="title">За цикл</span> <span data-cycle="status"></span></div>
        <div class="acc-cycle-note" data-cycle="empty">Отчёт появится с новым циклом поиска. Дневной итог сохранён ниже.</div>
        <div data-cycle="body" hidden>
          <div class="acc-cycle-grid">
            <div><span data-cycle="found">—</span><small>Найдено</small></div>
            <div><span data-cycle="sent">—</span><small>Отклики</small></div>
            <div><span data-cycle="skipped">—</span><small>Пропущено</small></div>
            <div><span data-cycle="remaining">—</span><small>Осталось</small></div>
          </div>
          <div class="acc-cycle-warning" data-cycle="notice" hidden></div>
          <div class="acc-cycle-warning" data-cycle="flags" hidden></div>
          <div class="acc-cycle-note" data-cycle="pagination" hidden></div>
          <details class="acc-cycle-details" data-cycle="details">
            <summary>Детали цикла и причины</summary>
            <div class="acc-cycle-note" data-cycle="processed"></div>
            <div class="acc-cycle-note" data-cycle="preview" hidden></div>
            <div class="acc-cycle-facts" data-cycle="facts"></div>
            <div class="acc-cycle-facts" data-cycle="reasons"></div>
          </details>
        </div>
      </section>
      <div class="acc-activity-freshness" data-activity="freshness">Нет свежих данных: последнее известное состояние</div>
    </section>
    <div class="acc-progress"><div class="acc-progress-fill" id="acc-prog-${acc.idx}"></div></div>
    <div class="acc-stats">
      <div class="stat-box acc-apply-summary" title="Подтверждённые отклики бота сегодня и за текущий запуск; отдельный счётчик HH">
        <div class="acc-apply-counts">
          <div><div class="stat-val c-green" id="acc-daily-${acc.idx}">—</div><div class="stat-lbl">Сегодня · бот</div></div>
          <div><div class="stat-val acc-session-value" id="acc-sent-${acc.idx}">0</div><div class="stat-lbl">За этот запуск</div></div>
        </div>
        <div class="acc-apply-totals">Всего бот: <span id="acc-total-${acc.idx}">0</span> · <span id="acc-hh-today-${acc.idx}" title="Отдельный счётчик HH сегодня / лимит">—</span></div>
      </div>
      <div class="stat-box">
        <div class="stat-val c-magenta" id="acc-tests-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_tests')}</div>
      </div>
      <div class="stat-box" id="acc-qsent-box-${acc.idx}" style="display:none">
        <div class="stat-val c-cyan" id="acc-qsent-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_surveys')}</div>
      </div>
      <div class="stat-box">
        <div class="stat-val c-blue" id="acc-already-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_already')}</div>
      </div>
      <div class="stat-box">
        <div class="stat-val c-red" id="acc-err-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_errors')}</div>
      </div>
      <div class="stat-box" id="acc-sal-box-${acc.idx}" style="display:none">
        <div class="stat-val c-yellow" id="acc-sal-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_salary')}</div>
      </div>
      <div class="stat-box" id="acc-intrv-box-${acc.idx}" style="display:none">
        <div class="stat-val" style="color:#f0c060" id="acc-intrv-${acc.idx}">0</div>
        <div id="acc-intrv-total-${acc.idx}" style="font-size:10px;color:var(--dim);line-height:1.2"></div>
        <div class="stat-lbl">${t('stat_interviews')}</div>
      </div>
    </div>
    <div class="acc-vacancy" id="acc-vacancy-${acc.idx}">
      <div class="acc-vacancy-title c-dim">${t('card_waiting')}</div>
    </div>
    <div id="acc-application-check-${acc.idx}" style="display:none;margin:7px 0;overflow-wrap:anywhere">
      <button class="btn-sm" id="acc-application-check-btn-${acc.idx}" onclick="reconcileApplication(${acc.idx})" style="max-width:100%;white-space:normal">Проверить в HH и продолжить</button>
      <div id="acc-application-check-result-${acc.idx}" role="status" style="font-size:11px;margin-top:5px;line-height:1.45"></div>
    </div>
    <div class="acc-auth-check" id="acc-auth-check-${acc.idx}" hidden>
      <button class="btn-sm" id="acc-auth-check-btn-${acc.idx}" onclick="recheckAccountAuth(${acc.idx})">Проверить вход и продолжить</button>
      <div id="acc-auth-check-result-${acc.idx}" role="status"></div>
    </div>
    <div class="acc-protective" id="acc-protective-${acc.idx}" hidden style="margin:7px 0">
      <button class="btn-sm" id="acc-protective-btn-${acc.idx}" onclick="confirmProtectiveResume(${acc.idx})">Проверил в HH — продолжить</button>
      <div id="acc-protective-result-${acc.idx}" role="status" style="font-size:11px;margin-top:5px"></div>
    </div>
    <div class="captcha-history-launch"><button type="button" class="btn-sm" onclick="openCaptchaHistory()">История капч</button></div>
    <div id="acc-captcha-${acc.idx}" hidden style="margin:8px 0;padding:10px;border:1px solid var(--yellow);border-radius:6px">
      <div role="alert" style="font-weight:700;color:var(--yellow);margin-bottom:8px">⏸ Отклики остановлены — проверка HH</div>
      <div id="acc-captcha-llm-${acc.idx}" hidden style="font-size:12px;margin-bottom:8px;color:var(--cyan)"></div>
      <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-start">
        <img id="acc-captcha-img-${acc.idx}" alt="Проверка HH: введите символы с картинки" style="max-width:min(280px,100%);border:1px solid var(--dim);border-radius:4px;background:#fff;display:none">
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <input id="acc-captcha-input-${acc.idx}" type="text" aria-label="Текст с картинки HH" placeholder="Текст с картинки" autocomplete="off" autocapitalize="off" spellcheck="false" style="padding:4px 8px;font-size:16px;max-width:100%;box-sizing:border-box" onkeydown="if(event.key==='Enter'){solveCaptcha(${acc.idx})}">
          <button class="btn-sm" onclick="solveCaptcha(${acc.idx})">✓ Отправить</button>
          <button class="btn-sm" onclick="solveCaptchaLocal(${acc.idx})">🤖 Решить локально</button>
          <button class="btn-sm" onclick="loadCaptchaImg(${acc.idx})">🔄 Другая</button>
          <button class="btn-sm" onclick="loadAccountCaptcha(${acc.idx})">Открыть проверку на HH / продолжить</button>
        </div>
      </div>
      <div id="acc-captcha-result-${acc.idx}" role="status" style="margin-top:6px;font-size:12px"></div>
    </div>
    <div class="acc-meta" id="acc-meta-${acc.idx}"></div>
    <div class="acc-hh-stats" id="acc-hh-${acc.idx}">${t('card_hh_loading')}</div>
    <div id="acc-llm-status-${acc.idx}" style="font-size:11px;padding:2px 0;color:var(--cyan);display:none"></div>
    <div class="acc-resume-stats" id="acc-rs-${acc.idx}" style="display:none">
      <span class="acc-resume-stat">👁️ <span id="acc-rs-views-${acc.idx}">0</span> ${t('rs_views')}</span>
      <span class="acc-resume-stat c-cyan">+<span id="acc-rs-vnew-${acc.idx}">0</span> новых</span>
      <span class="acc-resume-stat">🔎 <span id="acc-rs-shows-${acc.idx}">0</span> ${t('rs_shows')}</span>
      <span class="acc-resume-stat c-green">📬 <span id="acc-rs-inv-${acc.idx}">0</span> ${t('rs_inv')}</span>
      <span class="acc-touch-timer c-yellow" id="acc-touch-timer-${acc.idx}" style="display:none"></span>
    </div>
    <div id="acc-last-apply-${acc.idx}" style="display:none;font-size:11px;color:var(--dim);padding:2px 0"></div>
    <div id="acc-limit-eta-${acc.idx}" style="display:none;font-size:11px;padding:2px 0"></div>
    <div class="acc-history" id="acc-hist-${acc.idx}"></div>
    <div class="acc-event-log" id="acc-elog-${acc.idx}"></div>
    <div id="acc-errbadge-${acc.idx}" style="display:none;font-size:11px;padding:2px 0;margin-bottom:2px"></div>
    <div id="acc-cookiesbadge-${acc.idx}" class="cookies-expired-badge" style="display:none">${t('cookies_expired_badge')}</div>
    <div id="acc-diagbadge-${acc.idx}" style="display:none;font-size:11px;padding:4px 6px;margin-bottom:4px;background:rgba(255,180,0,0.08);border:1px solid var(--yellow);border-radius:4px;color:var(--yellow);cursor:pointer" onclick="accDiagnostics(${acc.idx},this)" title="Кликни — раскрыть подробности"></div>
    <label class="acc-skip-tests${acc.apply_tests ? ' active' : ''}" id="acc-apply-label-${acc.idx}">
      <input type="checkbox" id="acc-apply-cb-${acc.idx}" ${acc.apply_tests ? 'checked' : ''}
        onchange="applyTestsToggle(${acc.idx}, this)">
      ${t('card_apply_tests')}
    </label>
    <label class="acc-skip-tests${(acc.degraded_fallback_enabled !== false) ? ' active' : ''}" id="acc-degraded-label-${acc.idx}" title="При протухших cookies автоматически продолжать откликаться через OAuth API (без опросников/тестов)">
      <input type="checkbox" id="acc-degraded-cb-${acc.idx}" ${(acc.degraded_fallback_enabled !== false) ? 'checked' : ''}
        onchange="degradedFallbackToggle(${acc.idx}, this)">
      🔑 OAuth-fallback при протухших cookies
    </label>
    <label class="acc-skip-tests" id="acc-humanmode-label-${acc.idx}" title="Ограничение темпа: последовательные отклики, интервалы и активные часы. Не гарантирует отсутствие капчи. При проверке HH отправки останавливаются.">
      <input type="checkbox" id="acc-humanmode-cb-${acc.idx}"
        onchange="humanModeToggle(this)">
      ⏱ Ограничение темпа · все аккаунты
    </label>
    <div class="acc-actions">
      <button class="btn-sm" id="acc-pause-btn-${acc.idx}"
        onclick="sendCmd({type:'account_pause', idx:${acc.idx}})">${t('btn_acc_pause')}</button>
      <span class="touch-toggle ${acc.resume_touch_enabled !== false ? 'on' : 'off'}" id="acc-touch-toggle-${acc.idx}" onclick="touchToggle(${acc.idx},this)" title="Авто-подъём резюме вкл/выкл">
        <span class="tgl-dot"></span>
        <span>Авто-подъём резюме</span>
        <span id="acc-touch-label-${acc.idx}">${acc.resume_touch_enabled !== false ? '🔁 вкл' : '⏸ выкл'}</span>
      </span>
      <button class="btn-sm" id="acc-touch-btn-${acc.idx}"
        onclick="resumeTouchNow(${acc.idx},this)" title="Поднять резюме прямо сейчас">📤 Сейчас</button>
      <button class="btn-sm"
        onclick="declineDiscards(${acc.idx},this)">${t('btn_clear_discards')}</button>
      <button class="btn-sm llm-toggle-btn llm-on" id="acc-llm-btn-${acc.idx}"
        onclick="llmToggleAccount(${acc.idx},this)" title="LLM авто-ответы на сообщения HR">💬 Ответы</button>
      <button class="btn-sm" style="font-size:9px;padding:1px 5px;color:var(--green);border-color:var(--green)"
        onclick="llmRunNow(this)" title="Проверить чаты и ответить прямо сейчас">🔄 Сейчас</button>
      ${acc.temp && !acc.bot_active ? `<button class="btn-sm" style="color:var(--green);border-color:var(--green)" onclick="sessionActivate(${acc.idx}, this)">${t('btn_launch')}</button>` : ''}
      ${acc.temp && acc.bot_active ? `<button class="btn-sm" style="color:var(--orange);border-color:var(--orange)" onclick="sessionDeactivate(${acc.idx},this)" title="Остановить бот для этого аккаунта (сессия сохранится — можно запустить снова)">🛑 Стоп</button>` : ''}
      ${acc.temp ? `<button class="btn-sm" style="color:var(--red);border-color:var(--red)" onclick="sessionRemove(${acc.idx})">${t('btn_delete')}</button>` : ''}
    </div>
    <details class="acc-letter-wrap" id="acc-letter-wrap-${acc.idx}">
      <summary>${t('letter_section')}</summary>
      <div class="acc-letter-body">
        <select id="acc-letter-tpl-${acc.idx}" class="apply-input" style="font-size:11px;padding:3px 6px;margin-bottom:6px"
          onchange="letterPickTpl(${acc.idx})">
          <option value="">— пусто —</option>
          <option value="__custom__">✏️ Своё</option>
        </select>
        <textarea id="acc-letter-ta-${acc.idx}" class="apply-input" rows="3"
          style="font-size:11px" placeholder="Сопроводительное письмо...">${esc(acc.letter||'')}</textarea>
        <div style="display:flex;gap:6px;margin-top:6px;align-items:center">
          <button class="btn-sm" onclick="letterSave(${acc.idx},this)">${t('btn_save')}</button>
          <span id="acc-letter-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>
        </div>
      </div>
    </details>
    <details class="acc-letter-wrap" id="acc-auto-response-wrap-${acc.idx}"
      ontoggle="if(this.open) autoResponseLoad(${acc.idx})">
      <summary>🤖 Нативный автоотклик HH Pro</summary>
      <div class="acc-letter-body" style="font-size:11px">
        <input type="hidden" id="acc-ar-resume-${acc.idx}" value="${esc(acc.resume_hash || '')}">
        <div id="acc-ar-status-${acc.idx}" style="color:var(--dim);margin-bottom:7px">
          Откройте карточку для загрузки правил HH.
        </div>
        <div id="acc-ar-rules-${acc.idx}" style="margin-bottom:8px"></div>
        <div style="border-top:1px solid var(--border);padding-top:7px">
          <div style="color:var(--dim);margin-bottom:5px">Фильтры нового правила</div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px">
            <input id="acc-ar-roles-${acc.idx}" class="apply-input" placeholder="ID профессий: 96, 10"
              style="min-width:180px;flex:1;font-size:10px">
            <select id="acc-ar-exp-${acc.idx}" class="apply-input" style="font-size:10px;width:auto">
              <option value="">Любой опыт</option>
              <option value="noExperience">Нет опыта</option>
              <option value="between1And3">1–3 года</option>
              <option value="between3And6">3–6 лет</option>
              <option value="moreThan6">Более 6 лет</option>
            </select>
            <input id="acc-ar-salary-${acc.idx}" class="apply-input" type="number" min="0"
              placeholder="Зарплата от" style="width:110px;font-size:10px">
          </div>
          <label style="display:flex;align-items:center;gap:5px;margin-bottom:7px;cursor:pointer">
            <input id="acc-ar-only-salary-${acc.idx}" type="checkbox"> Только вакансии с зарплатой
          </label>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            <button class="btn-sm" onclick="autoResponseCreate(${acc.idx},this)">＋ Создать правило</button>
            <button class="btn-sm" onclick="autoResponseLoad(${acc.idx},true)">↻ Обновить</button>
            <span style="color:var(--yellow)">Изменения выполняются на сервере HH</span>
          </div>
        </div>
      </div>
    </details>
    <details class="acc-letter-wrap" id="acc-career-wrap-${acc.idx}"
      ontoggle="if(this.open) careerRadarLoad(${acc.idx})">
      <summary>📈 Карьерный радар</summary>
      <div class="acc-letter-body" id="acc-career-body-${acc.idx}" style="font-size:11px;color:var(--dim)">
        Откройте для загрузки зарплат и динамики вакансий HH.
      </div>
    </details>
    <details class="acc-letter-wrap" id="acc-visibility-wrap-${acc.idx}"
      ontoggle="if(this.open) resumeVisibilityLoad(${acc.idx})">
      <summary>👁️ Видимость резюме <span id="acc-visibility-chip-${acc.idx}" style="font-size:10px"></span></summary>
      <div class="acc-letter-body" id="acc-visibility-body-${acc.idx}" style="font-size:11px;color:var(--dim)">
        Откройте для проверки, кто видит выбранное резюме.
      </div>
    </details>
    <details class="acc-letter-wrap" ontoggle="if(this.open) autosearchesLoad(${acc.idx})">
      <summary>🔎 Автопоиски HH</summary>
      <div class="acc-letter-body" id="acc-autosearches-${acc.idx}" style="font-size:11px;color:var(--dim)">Откройте для загрузки.</div>
    </details>
    <details class="acc-letter-wrap" ontoggle="if(this.open) hiddenItemsLoad(${acc.idx})">
      <summary>🚫 Скрытые вакансии и работодатели</summary>
      <div class="acc-letter-body" id="acc-hidden-${acc.idx}" style="font-size:11px;color:var(--dim)">Откройте для загрузки.</div>
    </details>
    <details class="acc-letter-wrap" ontoggle="if(this.open) bellNotificationsLoad(${acc.idx})">
      <summary>🔔 Уведомления HH</summary>
      <div class="acc-letter-body" id="acc-bell-${acc.idx}" style="font-size:11px;color:var(--dim)">Откройте для загрузки.</div>
    </details>
    <details class="acc-letter-wrap" ontoggle="if(this.open) conversionLoad(${acc.idx})">
      <summary>🎯 Конверсия откликов</summary>
      <div class="acc-letter-body" id="acc-conversion-${acc.idx}" style="font-size:11px;color:var(--dim)">Откройте для расчёта.</div>
    </details>
    <details class="acc-letter-wrap">
      <summary>💬 Контакт до отклика</summary>
      <div class="acc-letter-body">
        <input id="contact-vid-${acc.idx}" placeholder="ID вакансии или ссылка HH" aria-label="Вакансия для проверки контактов">
        <button class="btn-sm" onclick="checkVacancyContact(${acc.idx},this)">Проверить</button>
        <div id="contact-result-${acc.idx}" aria-live="polite">Только проверка. Сообщения не отправляются.</div>
      </div>
    </details>
    ${acc.temp ? (() => {
      // HH SSR отдаёт title как list of {string: "..."} — нормализуем
      const normTitle = (t) => {
        if (!t) return '—';
        if (typeof t === 'string') return t;
        if (Array.isArray(t)) return t.map(x => (x && x.string) || x).filter(Boolean).join(' ');
        if (typeof t === 'object' && t.string) return t.string;
        return '—';
      };
      const cur = (acc.all_resumes||[]).find(r=>r.hash===acc.resume_hash);
      const curTitle = cur ? normTitle(cur.title) : (acc.resume_hash ? acc.resume_hash.slice(0,8)+'…' : '—');
      return `<details class="acc-letter-wrap" id="acc-resume-wrap-${acc.idx}">
      <summary>📄 Резюме <span id="acc-resume-current-${acc.idx}" style="font-size:10px;color:var(--dim)">${esc(curTitle)}</span></summary>
      <div class="acc-letter-body">
        <div style="font-size:11px;color:var(--dim);margin-bottom:6px">
          С каким резюме бот откликается. У аккаунта: <b>${(acc.all_resumes||[]).length}</b> шт.
        </div>
        <select id="acc-resume-sel-${acc.idx}" class="apply-input" onchange="resumeSelectSave(${acc.idx},this)" style="font-size:11px;padding:3px 6px;margin-bottom:6px;width:100%">
          ${(acc.all_resumes||[]).map(r =>
            `<option value="${esc(r.hash)}" ${r.hash===acc.resume_hash?'selected':''}>${esc(normTitle(r.title))} · ${esc((r.hash||'').slice(0,10))}…</option>`
          ).join('') || '<option value="">— пусто, обнови сессию —</option>'}
        </select>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <button class="btn-sm" onclick="sessRefresh(${acc.idx},this)" title="Заново прочитать список резюме из HH">🔄 Обновить</button>
          <span id="acc-resume-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>
        </div>
      </div>
    </details>`;
    })() : ''}
    <details class="acc-letter-wrap" id="acc-url-wrap-${acc.idx}">
      <summary>${t('url_section')}</summary>
      <div class="acc-letter-body">
        <div id="acc-url-checks-${acc.idx}" style="margin-bottom:8px"></div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
          <button class="btn-sm" onclick="urlAccSave(${acc.idx},this)">${t('btn_apply_url')}</button>
          <span id="url-acc-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>
        </div>
        <div style="border-top:1px solid var(--border);padding-top:8px">
          <div style="font-size:11px;color:var(--dim);margin-bottom:5px">➕ Добавить новый URL в пул и сразу включить:</div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            <input id="acc-url-new-${acc.idx}" class="apply-input" type="text" placeholder="https://hh.ru/search/vacancy?text=..." style="flex:1;min-width:200px;font-size:11px">
            <button class="btn-sm" onclick="urlAccQuickAdd(${acc.idx},this)">＋ Добавить</button>
            <span id="url-quick-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>
          </div>
        </div>
      </div>
    </details>
    <details class="acc-letter-wrap">
      <summary>🧠 ${t('smart_filters')}</summary>
      <div class="acc-letter-body" style="font-size:11px">
        <div style="display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:8px">
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px">
            <input type="checkbox" class="smart-filter-cb" data-key="filter_low_competition" style="accent-color:var(--green)"> 🎯 ${t('smart_filter_low_comp')}
          </label>
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px">
            <input type="checkbox" class="smart-filter-cb" data-key="filter_agencies" style="accent-color:var(--yellow)"> 🏢 ${t('smart_filter_no_agency')}
          </label>
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px">
            <input type="checkbox" class="smart-filter-cb" data-key="remote_it_only" style="accent-color:var(--cyan)"> Только ИТ + удалёнка (все поиски)
          </label>
          <label id="acc-safety-label-${acc.idx}" style="cursor:pointer;display:flex;align-items:center;gap:4px" title="Настройка только этого аккаунта: HH выбирает подходящее резюме; обязательные несовпадения, предупреждения о недостоверности и redirect-дубликаты пропускаются">
            <input type="checkbox" id="acc-safety-cb-${acc.idx}" ${acc.safety_enabled ? 'checked' : ''}
              onchange="safetyToggle(${acc.idx},this)" style="accent-color:var(--cyan)"> ⚡ ${t('smart_filter_pre_check')}
          </label>
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px">
            <input type="checkbox" class="smart-filter-cb" data-key="auto_apply_tests" style="accent-color:var(--magenta)"> 🧪 ${t('smart_filter_auto_tests')}
          </label>
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px" title="auto_response=true: вакансии массовой раздачи откликов, обычно низкое качество">
            <input type="checkbox" class="smart-filter-cb" data-key="skip_auto_response_vacancies" style="accent-color:var(--red)"> 🤖 ${t('smart_filter_skip_auto_resp')}
          </label>
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px" title="quick_responses_allowed → в начало очереди">
            <input type="checkbox" class="smart-filter-cb" data-key="prefer_quick_responses" style="accent-color:var(--green)"> ⚡ ${t('smart_filter_quick_resp')}
          </label>
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px" title="Только аккредитованные IT-работодатели">
            <input type="checkbox" class="smart-filter-cb" data-key="accredited_it_only" style="accent-color:var(--cyan)"> 💻 ${t('smart_filter_it_only')}
          </label>
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px" title="Старые вакансии не расходуют защищённый остаток дневного лимита">
            <input type="checkbox" class="smart-filter-cb" data-key="fresh_vacancies_mode" style="accent-color:var(--green)"> 🆕 ${t('smart_filter_fresh_reserve')}
          </label>
          <label style="cursor:pointer;display:flex;align-items:center;gap:4px" title="Для всех аккаунтов, со следующего сбора. Внутри категории свежести: менеджер онлайн, затем совпадение навыков. Если HH не прислал сигналы, используется обычный порядок. Онлайн не гарантирует ответ.">
            <input type="checkbox" class="smart-filter-cb" data-key="prefer_hh_signals" style="accent-color:var(--cyan)"> 📡 Приоритет по сигналам HH
          </label>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:8px">
          <label style="display:flex;align-items:center;gap:4px">📅 ${t('smart_filter_freshness')}
            <select class="smart-filter-sel" data-key="search_period_days" style="font-size:10px;padding:1px 4px">
              <option value="0">Все</option><option value="1">1д</option><option value="3">3д</option><option value="7">7д</option>
            </select>
          </label>
          <label style="display:flex;align-items:center;gap:4px">💬 ${t('smart_filter_llm_interval')}
            <select class="smart-filter-sel" data-key="llm_check_interval" style="font-size:10px;padding:1px 4px">
              <option value="2">2м</option><option value="5">5м</option><option value="10">10м</option><option value="15">15м</option><option value="30">30м</option>
            </select>
          </label>
          <label style="display:flex;align-items:center;gap:4px">🛑 ${t('smart_filter_daily_limit')}
            <input type="number" class="smart-filter-num" data-key="daily_apply_limit" min="0" max="500" style="width:50px;font-size:10px;padding:1px 4px" placeholder="0">
          </label>
          <label style="display:flex;align-items:center;gap:4px">🕐 Свежая ≤
            <input type="number" class="smart-filter-num" data-key="fresh_vacancy_hours" min="1" max="168" style="width:44px;font-size:10px;padding:1px 4px" placeholder="24">ч
          </label>
          <label style="display:flex;align-items:center;gap:4px">🛡️ Резерв
            <input type="number" class="smart-filter-num" data-key="fresh_apply_reserve" min="0" max="200" style="width:44px;font-size:10px;padding:1px 4px" placeholder="50">
          </label>
        </div>
        <div class="fresh-mode-summary" style="display:none;margin-bottom:7px;padding:5px 7px;border:1px solid rgba(34,197,94,.35);border-radius:5px;color:var(--green);font-size:10px"></div>
        <div id="acc-safety-stats-${acc.idx}" style="display:none;margin-bottom:7px;padding:5px 7px;border:1px solid rgba(0,240,255,.3);border-radius:5px;color:var(--cyan);font-size:10px"></div>
        <div style="color:var(--dim);font-size:10px;line-height:1.5">
          💡 Из анализа 14К переговоров: удалёнка 74%, junior 78%, аналитик 100%, IT-аккред. только 17% интервью
        </div>
      </div>
    </details>
  `;
}

function activityTimestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function activityDuration(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  if (value >= 86400) return `${Math.floor(value / 86400)} д ${Math.floor(value % 86400 / 3600)} ч`;
  if (value >= 3600) return `${Math.floor(value / 3600)} ч ${Math.floor(value % 3600 / 60)} мин`;
  if (value >= 60) return `${Math.floor(value / 60)} мин ${value % 60} с`;
  return `${value} с`;
}

function cycleReportView(report) {
  const valid = report && typeof report === 'object' && !Array.isArray(report)
    && typeof report.cycle_id === 'string' && report.cycle_id.trim().length > 0
    && report.cycle_id.length <= 128 && activityTimestamp(report.started_at) !== null;
  if (!valid) return {available: false};
  const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
  const show = value => count(value) === null ? '—' : String(value);
  const finished = activityTimestamp(report.finished_at) !== null;
  const statuses = {running: 'В работе', waiting: 'Ожидание', blocked: 'Приостановлен', error: 'Ошибка в цикле'};
  const reasons = (Array.isArray(report.skip_reasons) ? report.skip_reasons : [])
    .filter(item => item && typeof item.label === 'string' && item.label.trim() && count(item.count) > 0)
    .slice(0, 50).map(item => ({label: item.label.trim().slice(0, 160), count: item.count}))
    .sort((a, b) => b.count - a.count);
  const flags = [];
  const searchStops = {hh_limit: 'Достигнут предел выдачи HH — это не весь рынок вакансий',
    empty_page: 'Страница без вакансий; конец веб-выдачи не подтверждён',
    configured_limit: 'Достигнут настроенный предел страниц — поиск просмотрен не полностью',
    repeated_page: 'HH повторил страницу; загрузка остановлена',
    missing_pagination: 'HH не сообщил конец выдачи', invalid_response: 'Не удалось прочитать страницу поиска',
    cancelled: 'Загрузка страниц прервана'};
  for (const reason of Array.isArray(report.search_stop_reasons) ? report.search_stop_reasons : [])
    if (Object.hasOwn(searchStops, reason)) flags.push(searchStops[reason]);
  if (count(report.unknown) > 0) flags.push(`Не подтверждено: ${report.unknown} (не считаются отправленными)`);
  if (count(report.errors) > 0) flags.push(`Ошибки по вакансиям: ${report.errors}`);
  if (count(report.operation_errors) > 0) flags.push(`Ошибки операций: ${report.operation_errors}`);
  if (count(report.questionnaires_pending) > 0) flags.push(`Анкеты ждут ответа: ${report.questionnaires_pending}`);
  const facts = [
    `Найдено до общего удаления дублей: ${show(report.found_raw)}`,
    `Уникальных полученных вакансий: ${show(report.found_unique)}`,
    `Рассмотрено фильтрами: ${show(report.considered)}`,
    `Учтено исходов: ${show(report.processed)} (включая неподтверждённые)`,
    `Подтверждённые отклики: ${show(report.sent)}`,
    `Уже откликались: ${show(report.already)} (входит в «Пропущено»)`,
    `Ошибки по вакансиям: ${show(report.errors)}; ошибки операций: ${show(report.operation_errors)}`,
    `Исход не подтверждён: ${show(report.unknown)}; анкеты ждут ответа: ${show(report.questionnaires_pending)}`,
    'Осталось — вакансии без учтённого результата; анкеты, ожидающие ответа, входят в остаток.'
  ];
  return {available: true, identity: report.cycle_id,
    title: finished ? 'За последний цикл' : 'За текущий цикл',
    status: statuses[report.status] || 'Статус не указан',
    found: show(report.found_unique), sent: show(report.sent), skipped: show(report.skipped), remaining: show(report.remaining),
    processed: `Разобрано: ${show(report.processed)} · за этот цикл`,
    notice: report.partial === true ? 'Промежуточный или неполный итог — подробности ниже.' : '',
    flags: flags.join('\n'),
    pagination: count(report.search_pages_loaded) !== null ? `Загружено страниц поиска: ${report.search_pages_loaded}` : '',
    preview: reasons.length ? 'Пропуски: ' + reasons.slice(0, 2).map(item => `${item.label} — ${item.count}`).join('; ')
      + (reasons.length > 2 ? `; ещё причин: ${reasons.length - 2}` : '') : '',
    facts: facts.join('\n'), reasons: reasons.map(item => `${item.label}: ${item.count}`).join('\n')};
}

function renderCycleReport(acc) {
  const region = document.getElementById('acc-cycle-' + acc.idx);
  if (!region) return;
  const view = cycleReportView(acc.cycle_report);
  const body = region.querySelector('[data-cycle="body"]');
  const empty = region.querySelector('[data-cycle="empty"]');
  if (body) body.hidden = !view.available;
  if (empty) empty.hidden = view.available;
  const details = region.querySelector('[data-cycle="details"]');
  if (region._cycleIdentity !== view.identity && details) details.open = false;
  region._cycleIdentity = view.identity;
  for (const key of ['title', 'status', 'found', 'sent', 'skipped', 'remaining', 'processed', 'notice', 'flags', 'pagination', 'preview', 'facts', 'reasons']) {
    const node = region.querySelector(`[data-cycle="${key}"]`);
    if (!node) continue;
    const value = view.available ? view[key] : (key === 'title' ? 'За цикл' : '');
    if (node.textContent !== value) node.textContent = value;
    node.hidden = !value;
  }
}

function networkRecoveryDetails(acc) {
  if (acc.paused !== true || acc.paused_reason !== 'network_error') return '';
  const recovery = acc.network_recovery;
  if (!recovery || typeof recovery !== 'object' || Array.isArray(recovery)) return '';
  const reasons = {proxy_error: 'ошибка соединения через прокси', tls_error: 'ошибка защищённого соединения',
    connect_timeout: 'не удалось вовремя подключиться к HH', read_timeout: 'HH не ответил вовремя',
    timeout: 'время ожидания HH истекло', connection_error: 'соединение с HH недоступно',
    network_error: 'сетевая ошибка'};
  const outcomes = {network: 'связь ещё не подтверждена', auth: 'нужно подтвердить вход в HH',
    challenge: 'HH запрашивает проверку доступа', rate_limit: 'HH ограничил частоту запросов',
    unavailable: 'безопасная проверка сейчас недоступна', stale: 'состояние изменилось; нужна новая проверка'};
  const parts = ['Причина паузы: ' + (typeof recovery.reason === 'string' && Object.hasOwn(reasons, recovery.reason)
    ? reasons[recovery.reason] : 'связь с HH не подтверждена')];
  if (Number.isSafeInteger(recovery.attempts) && recovery.attempts >= 0)
    parts.push('Попыток проверки связи: ' + recovery.attempts);
  if (typeof recovery.last_error === 'string' && Object.hasOwn(outcomes, recovery.last_error)) {
    const stopped = recovery.next_check_at === null && recovery.last_error !== 'network';
    parts.push((stopped ? 'Автопроверки остановлены: ' : 'Последний результат: ') + outcomes[recovery.last_error]);
  }
  return parts.join('\n');
}

function accountActivityView(acc, fresh, now, globalPaused = false) {
  const activity = acc.activity && typeof acc.activity === 'object' && !Array.isArray(acc.activity)
    ? acc.activity : null;
  const text = value => typeof value === 'string' ? value.trim().slice(0, 1000) : '';
  const supplied = Boolean(activity && text(activity.current));
  const fallbackNames = {idle: 'Ожидание', collecting: 'Сбор вакансий', applying: 'Отправка отклика',
    waiting: 'Ожидание', checking: 'Проверка лимита', limit: 'Лимит откликов', '—': 'Бот не запущен'};
  const pause = supplied ? null : accountPauseInfo(acc, globalPaused);
  let current = supplied ? text(activity.current)
    : pause ? pause.label + '. ' + pause.detail
      : text(acc.status_detail) || fallbackNames[acc.status] || 'Состояние не указано';
  let next = supplied ? text(activity.next) || 'Пока не указано сервером' : 'Пока не указано сервером';
  let situation = '';
  const report = acc.cycle_report;
  // Explain only a fresh, complete, empty-result cycle. Never mask protective
  // pauses, a reserve, unfinished questionnaires, partial searches or errors.
  if (fresh && supplied && ['cycle_wait', 'no_new'].includes(activity.phase)
      && !globalPaused && !acc.paused && !acc.hard_stopped && !acc.limit_exceeded
      && !acc.pending_apply && !(acc.pending_applies?.length) && activity.requires_action === false
      && cycleReportView(report).available && activityTimestamp(report.finished_at) !== null
      && report.status === 'waiting' && report.partial === false
      && ['sent', 'remaining', 'errors', 'operation_errors', 'unknown', 'questionnaires_pending'].every(k => report[k] === 0)
      && Number.isSafeInteger(report.found_unique) && report.found_unique >= 0
      && report.processed === report.found_unique && report.skipped === report.found_unique
      && Number.isSafeInteger(report.already) && report.already >= 0 && report.already <= report.found_unique
      && Array.isArray(report.skip_reasons)
      && !report.skip_reasons.some(item => ['fresh_reserve', 'hh_limit', 'cancelled'].includes(item?.key))) {
    current = report.found_unique === 0 ? 'Текущий поиск не нашёл вакансий'
      : report.already >= report.found_unique * 0.9 ? 'В текущем поиске почти всё уже обработано'
      : 'В текущей выдаче нет вакансий для нового отклика';
    const reasons = (Array.isArray(report.skip_reasons) ? report.skip_reasons : [])
      .filter(item => item && item.key !== 'already' && typeof item.label === 'string'
        && Number.isSafeInteger(item.count) && item.count > 0)
      .slice(0, 3).map(item => `${item.label.slice(0, 100)}: ${item.count}`);
    situation = `Найдено: ${report.found_unique}\nУже откликались: ${report.already} (за разные дни)`
      + (reasons.length ? '\n' + reasons.map(reason => '• ' + reason).join('\n') : '');
    next = 'Повторит поиск новых вакансий. Чтобы увеличить выбор, можно расширить поисковые запросы.';
  }
  const progress = supplied ? activity.progress : null;
  const validProgress = progress && Number.isSafeInteger(progress.done) && Number.isSafeInteger(progress.total)
    && progress.done >= 0 && progress.total > 0 && progress.done <= progress.total;
  const times = [];
  if (supplied && fresh && Number.isFinite(now)) {
    const started = activityTimestamp(activity.started_at);
    let until = activityTimestamp(activity.wait_until);
    const networkWait = activity.phase === 'network_recovery';
    // Never invent a recovery schedule from attempt count or show a timer under
    // another protective pause. A network deadline must match the saved schedule.
    if (networkWait && (globalPaused || acc.paused_reason !== 'network_error' || activity.requires_action !== false
      || ![null, undefined, 'network'].includes(acc.network_recovery?.last_error)
      || until !== activityTimestamp(acc.network_recovery?.next_check_at))) until = null;
    if (acc.paused_reason === 'network_error' && !networkWait) until = null;
    if (started !== null && started <= now) times.push('На этом этапе: ' + activityDuration((now - started) / 1000));
    if (until !== null) times.push(until > now
      ? (networkWait ? 'До проверки связи: ' : 'Ожидание: ещё ') + activityDuration(Math.ceil((until - now) / 1000))
      : networkWait ? 'Время проверки наступило; ждём новый статус' : 'Плановое время наступило; ждём новый статус');
  }
  return {current, next, progress: validProgress ? `Прогресс этапа: ${progress.done} / ${progress.total}` : '',
    time: times.join('\n'), network: networkRecoveryDetails(acc), situation,
    requiresAction: supplied && activity.requires_action === true, stale: !fresh};
}

function renderAccountActivity(acc, monotonicNow = performance.now(), wallNow = Date.now()) {
  const region = document.getElementById('acc-activity-' + acc.idx);
  if (!region) return;
  renderCycleReport(acc);
  const received = State.snapshotReceivedAt;
  const age = Number.isFinite(received) ? monotonicNow - received : null;
  const fresh = Boolean(State.ws && State.ws.readyState === 1 && State.snapshotSocket === State.ws
    && age !== null && age >= 0 && age <= 15000);
  // Anchor durations to server time, not the potentially skewed browser clock.
  const now = Number.isFinite(State.snapshotServerAt) && age !== null
    ? State.snapshotServerAt + age : wallNow;
  const view = accountActivityView(acc, fresh, now, State.lastSnapshot?.paused === true);
  const phase = acc.activity?.phase;
  const phases = {collecting: 'Поиск вакансий', search: 'Поиск вакансий', apply: 'Отправка отклика',
    collect: 'Поиск вакансий', search_setup: 'Подготовка поиска', filter: 'Отбор вакансий',
    no_new: 'Ждёт новые вакансии', fresh_reserve: 'Резерв для свежих вакансий',
    resume_check: 'Проверка резюме', resume_touch: 'Поднятие резюме', limit_wait: 'Ожидание лимита',
    recover_error: 'Повтор после сбоя', manual_pause: 'На паузе', challenge: 'Проверка доступа HH',
    hh_rate_limit: 'Ограничение запросов HH', message_outcome_unknown: 'Нужна проверка сообщения',
    preflight: 'Проверка вакансии', questionnaire: 'Заполнение анкеты', cycle_wait: 'Ждёт новые вакансии',
    wait_between_batches: 'Плановая пауза', network_recovery: 'Восстанавливает связь',
    network_error: 'Нет связи', auth_check: 'Проверка входа', auth: 'Нужен вход',
    receipt_check: 'Проверка результата', outcome_unknown: 'Нужна сверка',
    limit: 'Лимит откликов', limit_check: 'Проверка лимита', stopped: 'Остановлен',
    manual: 'На паузе', global_pause: 'Общая пауза', auto_errors: 'Защитная пауза', idle: 'Ожидание'};
  const tone = !fresh ? 'stale' : view.requiresAction || phase === 'recover_error' ? 'attention'
    : ['cycle_wait', 'wait_between_batches', 'idle', 'stopped', 'manual', 'manual_pause', 'global_pause',
      'limit', 'limit_wait', 'no_new', 'fresh_reserve'].includes(phase) ? 'waiting' : 'active';
  region.dataset.tone = tone;
  const meter = region.querySelector('[data-activity-meter]');
  if (meter) {
    meter.hidden = !fresh || !view.progress;
    if (!meter.hidden) {
      meter.max = acc.activity.progress.total;
      meter.value = acc.activity.progress.done;
    }
  }
  const values = {current: view.current, next: view.next, progress: view.progress, time: view.time, network: view.network,
    situation: view.situation,
    phase: !fresh ? 'Нет свежих данных' : Object.hasOwn(phases, phase) ? phases[phase]
      : view.requiresAction ? 'Нужно ваше внимание' : 'Текущий этап',
    action: view.requiresAction ? 'Требуется ваше действие' : '',
    freshness: fresh ? `Обновлено ${activityDuration(age / 1000)} назад`
      : 'Нет свежих данных: последнее известное состояние'};
  for (const [key, value] of Object.entries(values)) {
    const node = region.querySelector(`[data-activity="${key}"]`);
    if (!node) continue;
    if (node.textContent !== value) node.textContent = value;
    node.hidden = !value;
  }
  region.classList.toggle('is-stale', view.stale);
  region.classList.toggle('requires-action', view.requiresAction);
}

function tickAccountActivities() {
  const now = performance.now(), wallNow = Date.now();
  for (const acc of State.lastSnapshot?.accounts || []) renderAccountActivity(acc, now, wallNow);
}

setInterval(tickAccountActivities, 1000); // local display only: no requests or worker commands

function hasUnknownApplication(acc) {
  return acc.paused_reason === 'outcome_unknown'
    || Boolean(acc.pending_apply && typeof acc.pending_apply === 'object')
    || (Array.isArray(acc.pending_applies) && acc.pending_applies.length > 0);
}

function accountPauseInfo(acc, globalPaused = false) {
  const unknown = hasUnknownApplication(acc);
  if (!acc.paused && !globalPaused && !unknown) return null;
  const reason = acc.paused_reason;
  let label, detail, cls = 'status-idle';
  if (unknown) {
    label = '⚠ Исход отклика неизвестен';
    detail = 'Нужна сверка результата в HH. Не отправляйте этот отклик повторно: сервер мог его принять. Проверка ниже не отправляет новый отклик.';
    cls = 'status-limit';
  } else if (reason === 'auto_errors') {
    label = '⏸ Авто-пауза: ошибки подряд';
    detail = 'Проверьте журнал ошибок и связь с HH перед продолжением.';
    cls = 'status-limit';
  } else if (reason === 'auth') {
    label = '🔐 Пауза: нужна авторизация';
    detail = 'Доступ к HH требует проверки. Обычное продолжение не обновляет авторизацию.';
    cls = 'status-limit';
  } else if (reason === 'network_error') {
    label = '⏸ Пауза: нет подтверждённой связи с HH';
    detail = 'Сетевая ошибка не означает, что вход истёк. Продолжение — только после проверки связи и доступа; обычное продолжение не снимает защиту.';
    cls = 'status-waiting';
  } else if (reason === 'hh_rate_limit') {
    label = '⏸ HH ограничил частоту запросов';
    detail = 'Ограничение запросов не подтверждает выход из аккаунта. Автоматические попытки приостановлены; нужна проверка доступа к HH.';
    cls = 'status-waiting';
  } else if (reason === 'challenge') {
    label = '⏸ HH запрашивает проверку доступа';
    detail = 'Нужна ручная проверка на HH. Повторные автоматические попытки приостановлены; это не подтверждение истёкшего входа.';
    cls = 'status-waiting';
  } else if (reason === 'limit' || acc.limit_exceeded || acc.hard_stopped) {
    cls = 'status-limit';
    const hhUsed = acc.hh_today_applies || 0, hhLimit = acc.hh_daily_limit || 200;
    if (acc.hard_stopped && hhUsed >= hhLimit) label = `🛑 HH-лимит ${hhUsed}/${hhLimit}`;
    else if (acc.hard_stopped && acc.daily_limit > 0 && acc.daily_sent >= acc.daily_limit) label = `🛑 ${t('status_daily_limit')} ${acc.daily_sent}/${acc.daily_limit}`;
    else label = '🚫 ' + t('status_hh_limit');
    detail = 'Достигнут лимит откликов. Проверьте счётчики и время сброса; продолжение не отменяет лимит HH.';
  } else {
    label = acc.paused ? t('status_acc_paused') : t('status_all_paused');
    detail = acc.paused ? 'Аккаунт приостановлен.' : 'Отклики остановлены общей паузой.';
  }
  const status = typeof acc.status_detail === 'string' ? acc.status_detail.trim() : '';
  // Старые worker snapshots могли заменять любую причину текстом manual pause.
  if (status && !(reason && reason !== 'manual' && status === 'Пауза пользователем')) detail = status + ' ' + detail;
  if (globalPaused && (acc.paused || unknown)) detail = 'Также включена общая пауза. ' + detail;
  return {label, detail, cls, unknown};
}

function renderAccountVacancy(acc, pauseInfo) {
  if (pauseInfo) {
    const previous = acc.current_vacancy_title
      ? `<div class="acc-vacancy-company c-dim" style="margin-top:6px">Последняя вакансия: ${esc(acc.current_vacancy_title)}</div>` : '';
    if (pauseInfo.unknown && typeof acc.activity?.current === 'string' && acc.activity.current.trim()) {
      // The activity block already explains the hold and its next step. Keep the
      // safety note next to the check button without repeating all three notices.
      return `<div class="acc-protective-note">Не отправляйте повторно: HH мог принять отклик. Проверка только сверяет результат.</div>${previous}`;
    }
    if (acc.paused_reason === 'network_error' && typeof acc.activity?.current === 'string' && acc.activity.current.trim()) {
      return `<div class="acc-protective-note">Проверки связи не отправляют отклики. Продолжение — только после подтверждения связи и доступа к HH; остальные ограничения сохраняются.</div>${previous}`;
    }
    return `<div class="acc-vacancy-title" style="white-space:normal;overflow-wrap:anywhere">${esc(pauseInfo.label)}</div>
      <div style="font-size:12px;line-height:1.45;margin-top:4px;white-space:normal;overflow-wrap:anywhere">${esc(pauseInfo.detail)}</div>${previous}`;
  }
  if (acc.current_vacancy_title) return `<div class="acc-vacancy-title">${esc(acc.current_vacancy_title)}</div>
    <div class="acc-vacancy-company c-dim">@ ${esc(acc.current_vacancy_company)}</div>
    <div style="font-size:11px;margin-top:4px">${renderVacancySignals(acc.current_vacancy_signals, State.lastSnapshot?.config?.prefer_hh_signals === true)}</div>`;
  return `<div class="acc-vacancy-title c-dim">${acc.status === 'applying' ? t('card_sending') : (esc(acc.status_detail) || t('card_waiting'))}</div>`;
}

function applicationCheckIdentity(acc) {
  return JSON.stringify([acc.idx, acc.temp === true, acc.resume_hash || '', acc.name || acc.short || '']);
}

function applicationCheckState(acc) {
  const pending = acc.pending_apply && typeof acc.pending_apply === 'object'
    ? acc.pending_apply : (Array.isArray(acc.pending_applies) ? acc.pending_applies[0] : null);
  const pendingIdentity = pending ? JSON.stringify([pending.vacancy_id ?? null,
    pending.resume_id ?? null, pending.recorded_at ?? null]) : '';
  const source = pending ? JSON.stringify([pendingIdentity, pending.reconcile_last_started_at ?? null]) : '';
  const activity = acc.activity;
  const nextAt = pending ? activityTimestamp(pending.reconcile_next_at) : null;
  const scheduled = activity?.phase === 'outcome_unknown' && activity.requires_action === false
    && Number.isSafeInteger(pending?.reconcile_attempts) && pending.reconcile_attempts >= 0
    && pending.reconcile_attempts < 3 && nextAt !== null && activityTimestamp(activity.wait_until) === nextAt;
  return {pendingIdentity, source, scheduled, checking: activity?.phase === 'receipt_check'};
}

function renderApplicationCheck(acc) {
  const region = document.getElementById('acc-application-check-' + acc.idx);
  if (!region) return;
  let entry = State.applicationChecks.get(acc.idx);
  const check = applicationCheckState(acc);
  if (entry && (entry.identity !== applicationCheckIdentity(acc)
      || (!entry.busy && entry.source !== check.source))) {
    State.applicationChecks.delete(acc.idx);
    entry = null;
  }
  const pending = hasUnknownApplication(acc);
  region.style.display = pending || entry ? '' : 'none';
  const button = document.getElementById('acc-application-check-btn-' + acc.idx);
  if (button) {
    button.style.display = pending ? '' : 'none';
    button.disabled = Boolean(entry?.busy) || check.checking || !State.ws || State.ws.readyState !== 1;
    button.textContent = entry?.busy || check.checking ? 'Проверяем результат в HH…'
      : check.scheduled ? 'Проверить сейчас' : 'Проверить в HH и продолжить';
    button.title = 'Только сверка уже отправленного отклика. Новый отклик не отправляется; при нескольких неопределённых результатах проверяем по одному.';
  }
  const result = document.getElementById('acc-application-check-result-' + acc.idx);
  if (result) result.textContent = entry?.message || '';
}

async function reconcileApplication(idx) {
  const acc = State.lastSnapshot?.accounts?.find(a => a.idx === idx);
  if (!acc || !hasUnknownApplication(acc)) return false;
  if (!State.ws || State.ws.readyState !== 1) {
    showCommandError('Нет связи с панелью. Дождитесь свежего состояния перед проверкой в HH.');
    return false;
  }
  const identity = applicationCheckIdentity(acc);
  const check = applicationCheckState(acc);
  if (check.checking) return false; // server is already checking; never overlap it
  if (State.applicationChecks.get(idx)?.busy) return false;
  const entry = {identity, source: check.source, pendingIdentity: check.pendingIdentity,
    busy: true, message: 'Сверяем уже отправленный отклик. Повторной отправки нет.'};
  State.applicationChecks.set(idx, entry);
  renderApplicationCheck(acc);
  try {
    const response = await fetch(`/api/account/${idx}/reconcile-application`, {method: 'POST'});
    const result = await response.json();
    if (response.ok && result?.ok === true && result.confirmed === true
        && typeof result.paused === 'boolean' && typeof result.pending === 'boolean') {
      entry.message = result.pending === true
        ? 'Этот отклик подтверждён. Остались другие неопределённые результаты — проверьте следующий отдельно.'
        : result.paused === true
          ? 'Отклик подтверждён. Аккаунт остаётся на паузе; проверьте её причину.'
          : 'Отклик подтверждён. Блокировка неизвестного исхода снята; ожидаем свежий статус панели.';
    } else {
      entry.message = typeof result?.message === 'string' && result.message.trim()
        ? result.message.slice(0, 500) : 'Проверка не подтвердила отклик. Пауза сохранена; повторный отклик не отправлялся.';
    }
  } catch (_) {
    entry.message = 'Не удалось получить результат проверки. Она не повторяется автоматически; повторный отклик не отправлялся. Проверьте связь и свежий статус.';
  } finally {
    entry.busy = false;
    const current = State.lastSnapshot?.accounts?.find(a => a.idx === idx);
    if (State.applicationChecks.get(idx) === entry && current && applicationCheckIdentity(current) === identity) {
      const latest = applicationCheckState(current);
      if (latest.pendingIdentity !== entry.pendingIdentity) State.applicationChecks.delete(idx);
      // Persisted last_started_at belongs only to automatic checks. If it changed
      // during this request, render clears our now-stale feedback after busy ends.
      renderApplicationCheck(current);
    } else if (State.applicationChecks.get(idx) === entry) State.applicationChecks.delete(idx);
  }
  return false;
}

function accountNeedsAuthCheck(acc) {
  return acc.mode === 'oauth' && acc.paused === true
    && ['auth', 'network_error'].includes(acc.paused_reason) && !hasUnknownApplication(acc);
}

function authCheckSource(acc) {
  const recovery = acc.paused_reason === 'network_error' ? acc.network_recovery : null;
  const value = key => typeof recovery?.[key] === 'string' ? recovery[key] : '';
  return JSON.stringify([acc.paused_reason, value('reason'), value('last_started_at'), value('next_check_at'), value('last_error')]);
}

function authCheckBlockReason(acc) {
  const kind = acc.paused_reason === 'network_error' ? 'Проверка связи' : 'Проверка входа';
  if (State.lastSnapshot?.paused === true) return 'Включена общая пауза. ' + kind + ' не снимает её и сейчас недоступна.';
  if (acc.hard_stopped || acc.limit_exceeded) return 'Действует ограничение откликов. ' + kind + ' не отменяет лимиты и сейчас недоступна.';
  return '';
}

function renderAuthCheck(acc) {
  const region = document.getElementById('acc-auth-check-' + acc.idx);
  if (!region) return;
  const eligible = accountNeedsAuthCheck(acc);
  let entry = State.authChecks.get(acc.idx);
  if (entry && (entry.identity !== applicationCheckIdentity(acc)
    || (!entry.busy && (!eligible || entry.source !== authCheckSource(acc))))) {
    State.authChecks.delete(acc.idx);
    entry = null;
  }
  region.hidden = !eligible && !entry;
  const checking = acc.activity?.phase === 'auth_check';
  const network = acc.paused_reason === 'network_error';
  const blocked = authCheckBlockReason(acc);
  const button = document.getElementById('acc-auth-check-btn-' + acc.idx);
  if (button) {
    button.hidden = !eligible;
    button.disabled = Boolean(entry?.busy) || checking || Boolean(blocked) || !State.ws || State.ws.readyState !== 1;
    button.textContent = entry?.busy || checking
      ? (network ? 'Проверяем связь с HH…' : 'Проверяем вход в HH…')
      : (network ? 'Проверить связь и продолжить' : 'Проверить вход и продолжить');
    button.title = blocked || 'Свежая проверка связи, входа и доступа к веб-анкете. Отклики не отправляются; другие защитные паузы не снимаются.';
  }
  const result = document.getElementById('acc-auth-check-result-' + acc.idx);
  if (result) result.textContent = blocked || entry?.message || '';
}

// Pauses with no automatic exit: an explicit human confirmation lifts them.
function protectiveResumeReason(acc) {
  if (!acc?.paused) return '';
  const r = acc.paused_reason;
  if (r === 'hh_rate_limit' || r === 'message_outcome_unknown') return r;
  if (r === 'challenge' && acc.captcha_record === false) return r;
  return '';
}

function renderProtectiveResume(acc) {
  const region = document.getElementById('acc-protective-' + acc.idx);
  if (!region) return;
  const reason = protectiveResumeReason(acc);
  region.hidden = !reason;
  const button = document.getElementById('acc-protective-btn-' + acc.idx);
  if (button) {
    button.title = reason === 'message_outcome_unknown'
      ? 'Откройте чат в HH и убедитесь, что сообщение не нужно отправлять повторно'
      : 'Убедитесь в HH, что ограничение снято';
  }
}

async function confirmProtectiveResume(idx) {
  const acc = State.lastSnapshot?.accounts?.find(a => a.idx === idx);
  const reason = protectiveResumeReason(acc);
  if (!reason) return;
  const hint = reason === 'message_outcome_unknown'
    ? 'Вы проверили чат в HH и сообщение не нужно отправлять повторно?'
    : 'Вы проверили в HH, что ограничение снято?';
  if (!confirm(hint)) return;
  const result = document.getElementById('acc-protective-result-' + idx);
  try {
    const r = await fetch(`/api/account/${idx}/protective/continue`, {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({confirmed: true, reason})});
    const d = await r.json();
    if (result) result.textContent = (d.ok ? d.message : d.error) || '';
  } catch (_) {
    if (result) result.textContent = 'Не удалось связаться с панелью.';
  }
}

async function recheckAccountAuth(idx) {
  const acc = State.lastSnapshot?.accounts?.find(a => a.idx === idx);
  if (!acc || !accountNeedsAuthCheck(acc)) return false;
  const network = acc.paused_reason === 'network_error';
  if (!State.ws || State.ws.readyState !== 1) {
    showCommandError('Нет связи с панелью. Дождитесь свежего состояния перед проверкой доступа к HH.');
    return false;
  }
  const blocked = authCheckBlockReason(acc);
  if (blocked) {
    showCommandError(blocked);
    return false;
  }
  if (State.authChecks.get(idx)?.busy || acc.activity?.phase === 'auth_check') return false;
  const identity = applicationCheckIdentity(acc);
  const entry = {identity, source: authCheckSource(acc), busy: true,
    message: network ? 'Проверяем связь и доступ к HH. Отклики не отправляются.'
      : 'Проверяем вход и доступ к HH. Отклики не отправляются.'};
  State.authChecks.set(idx, entry);
  renderAuthCheck(acc);
  try {
    const response = await fetch(`/api/account/${idx}/recheck-auth`, {method: 'POST'});
    const result = await response.json();
    if (response.ok && result?.ok === true && result.verified === true && result.paused === false) {
      entry.message = (network ? 'Связь и доступ к HH подтверждены.' : 'Вход в HH подтверждён.')
        + ' Ожидаем свежий статус панели; остальные ограничения сохраняются.';
    } else {
      entry.message = result?.ok === false && typeof result.message === 'string' && result.message.trim()
        ? result.message.slice(0, 500)
        : (network ? 'Связь и доступ не подтверждены.' : 'Вход не подтверждён.')
          + ' Защитная пауза сохранена; отклики не отправлялись.';
    }
  } catch (_) {
    entry.message = network
      ? 'Результат ручной проверки не получен. Запрос из панели не повторяется; расписание серверных проверок смотрите выше.'
      : 'Не удалось получить результат проверки входа. Автоматического повтора нет; проверьте связь и свежий статус панели.';
  } finally {
    entry.busy = false;
    const current = State.lastSnapshot?.accounts?.find(a => a.idx === idx);
    if (State.authChecks.get(idx) === entry && current && applicationCheckIdentity(current) === identity) renderAuthCheck(current);
    else if (State.authChecks.get(idx) === entry) State.authChecks.delete(idx);
  }
  return false;
}

function updateCard(card, acc) {
  renderAccountActivity(acc);
  const pauseInfo = accountPauseInfo(acc, State.lastSnapshot?.paused === true);
  // Status badge — глобальная пауза перекрывает статус
  const badge = document.getElementById('acc-badge-' + acc.idx);
  if (badge) {
    const globalPaused = State.lastSnapshot?.paused;
    const accPaused = acc.paused;
    if (globalPaused) {
      badge.className = 'acc-status-badge status-idle';
      badge.textContent = t('status_all_paused');
      badge.title = pauseInfo?.detail || '';
    } else if (accPaused) {
      badge.className = 'acc-status-badge ' + pauseInfo.cls;
      badge.textContent = pauseInfo.label;
      badge.title = pauseInfo.detail;
    } else {
      const [icon, labelKey, cls] = STATUS_MAP[acc.status] || ['❓', null, 'status-idle'];
      badge.className = 'acc-status-badge ' + cls;
      badge.textContent = icon + ' ' + (labelKey ? t(labelKey) : acc.status.toUpperCase());
      badge.title = acc.status_detail || '';
    }
  }

  // Resume stats block
  const rsBlock = document.getElementById('acc-rs-' + acc.idx);
  if (rsBlock && acc.resume_views_7d > 0) {
    rsBlock.style.display = '';
    setText('acc-rs-views-' + acc.idx, acc.resume_views_7d);
    setText('acc-rs-vnew-' + acc.idx, acc.resume_views_new);
    setText('acc-rs-shows-' + acc.idx, acc.resume_shows_7d);
    setText('acc-rs-inv-' + acc.idx, acc.resume_invitations_7d);
    // Touch timer
    const timerEl = document.getElementById('acc-touch-timer-' + acc.idx);
    if (timerEl) {
      const secs = acc.resume_next_touch_seconds || 0;
      if (secs > 0) {
        const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
        timerEl.style.display = '';
        timerEl.textContent = `⏱ ${t('rs_raise_in')} ${h > 0 ? h + 'ч ' : ''}${m}м`;
      } else {
        timerEl.style.display = '';
        timerEl.textContent = `✅ ${acc.resume_free_touches || 0} ${t('rs_raises_avail')}`;
        timerEl.className = 'acc-touch-timer c-green';
      }
    }
  }

  // Auto-touch toggle + button
  const touchToggleEl = document.getElementById('acc-touch-toggle-' + acc.idx);
  const touchLabelEl  = document.getElementById('acc-touch-label-' + acc.idx);
  const touchBtn      = document.getElementById('acc-touch-btn-' + acc.idx);
  // ── Last apply + limit ETA ──
  // Helper: ISO → {time, ago} или null
  const fmtTimeAgo = (iso) => {
    if (!iso) return null;
    const ts = new Date(iso);
    const diffSec = Math.max(0, Math.floor((Date.now() - ts.getTime()) / 1000));
    let ago;
    if      (diffSec < 60)    ago = `${diffSec}с`;
    else if (diffSec < 3600)  ago = `${Math.floor(diffSec/60)}м`;
    else if (diffSec < 86400) ago = `${Math.floor(diffSec/3600)}ч ${Math.floor((diffSec%3600)/60)}м`;
    else                       ago = `${Math.floor(diffSec/86400)}д`;
    return {time: ts.toLocaleTimeString('ru', {hour:'2-digit',minute:'2-digit'}), ago};
  };
  const laEl = document.getElementById('acc-last-apply-' + acc.idx);
  if (laEl) {
    const parts = [];
    const attempt = fmtTimeAgo(acc.last_apply_attempt_at);
    const sent    = fmtTimeAgo(acc.last_apply_at);
    if (attempt) {
      parts.push(`📤 попытка: <span style="color:var(--cyan)">${esc(attempt.time)}</span> · ${esc(attempt.ago)} назад`);
    }
    if (sent) {
      parts.push(`✅ удачный: <span style="color:var(--green)">${esc(sent.time)}</span> · ${esc(sent.ago)} назад`);
    }
    if (parts.length) {
      laEl.style.display = 'block';
      laEl.innerHTML = parts.join('<br>');
    } else {
      laEl.style.display = 'none';
    }
  }
  const etaEl = document.getElementById('acc-limit-eta-' + acc.idx);
  if (etaEl) {
    const isLimited = acc.paused_reason === 'limit' || acc.hard_stopped || (acc.daily_limit > 0 && acc.daily_sent >= acc.daily_limit);
    if (isLimited) {
      // До 00:00 МСК (UTC+3)
      const nowUtc = new Date();
      // Construct next midnight MSK
      const mskNow = new Date(nowUtc.getTime() + 3*3600*1000); // shift to MSK
      const mskNextMidnight = new Date(Date.UTC(mskNow.getUTCFullYear(), mskNow.getUTCMonth(), mskNow.getUTCDate() + 1, 0, 0, 0));
      const diffMs = mskNextMidnight.getTime() - mskNow.getTime();
      const totalMin = Math.max(0, Math.floor(diffMs / 60000));
      const h = Math.floor(totalMin / 60);
      const min = totalMin % 60;
      etaEl.style.display = 'block';
      etaEl.innerHTML = `🛑 <span style="color:var(--red)">лимит HH</span> · сбросится через <b style="color:var(--yellow)">${h}ч ${min}м</b> (00:00 МСК)`;
    } else {
      etaEl.style.display = 'none';
    }
  }
  const autoOn = acc.resume_touch_enabled !== false;
  const m = acc.next_resume_touch ? acc.next_resume_touch.match(/\(([^)]+)\)/) : null;
  const countdown = m && m[1]; // "2ч30м"
  if (touchToggleEl) {
    touchToggleEl.className = 'touch-toggle ' + (autoOn ? 'on' : 'off');
    if (touchLabelEl) {
      if (autoOn) {
        touchLabelEl.textContent = countdown ? `🔁 вкл · через ${countdown}` : '🔁 вкл';
      } else {
        touchLabelEl.textContent = countdown ? `⏸ выкл · было через ${countdown}` : '⏸ выкл';
      }
    }
  }
  if (touchBtn) {
    const touching = touchBtn.getAttribute('data-touching');
    if (touching) {
      if (countdown) {
        touchBtn.removeAttribute('data-touching');
        touchBtn.disabled = false;
        touchBtn.textContent = '📤 Сейчас';
        touchBtn.style.color = '';
      }
    } else if (!touchBtn.disabled) {
      touchBtn.textContent = '📤 Сейчас';
      touchBtn.style.color = '';
    }
  }

  // Stats
  setText('acc-daily-' + acc.idx, Number.isSafeInteger(acc.daily_sent) && acc.daily_sent >= 0 ? acc.daily_sent : '—');
  setText('acc-sent-' + acc.idx, acc.sent ?? 0);
  setText('acc-total-' + acc.idx, acc.total_applied ?? '—');
  // Real HH count today (из OAuth-tracker, обновляется раз в 30 мин)
  const hhUsed = acc.hh_today_applies || 0;
  const hhLim = acc.hh_daily_limit || 200;
  const hhCell = document.getElementById('acc-hh-today-' + acc.idx);
  if (hhCell) {
    if (acc.hh_today_applies_updated) {
      // streak — HH-геймификация: сколько подряд ответов для бейджа "часто отвечает"
      const strCount = acc.responses_streak_count || 0;
      const strReq = acc.responses_streak_required || 0;
      const streakHtml = strReq > 0
        ? ` · <span style="color:${strCount >= strReq ? 'var(--green)' : 'var(--dim)'}" title="responses_streak — HH-бейдж 'часто отвечает'">🔥${strCount}/${strReq}</span>`
        : '';
      hhCell.innerHTML = `HH сегодня ${hhUsed}/${hhLim}${streakHtml}`;
      hhCell.style.color = hhUsed >= hhLim ? 'var(--red)' : (hhUsed >= hhLim - 10 ? 'var(--yellow)' : 'var(--dim)');
    } else {
      hhCell.textContent = 'HH сегодня —';
      hhCell.style.color = 'var(--dim)';
    }
  }
  setText('acc-tests-' + acc.idx, acc.tests);
  setText('acc-already-' + acc.idx, acc.already_applied);
  setText('acc-err-' + acc.idx, acc.errors);

  // Questionnaire sent (show when > 0)
  const qBox = document.getElementById('acc-qsent-box-' + acc.idx);
  if (qBox) {
    const qSent = acc.questionnaire_sent || 0;
    qBox.style.display = qSent > 0 ? '' : 'none';
    setText('acc-qsent-' + acc.idx, qSent);
  }

  // Salary filter stat (only show when filter is active)
  const salBox = document.getElementById('acc-sal-box-' + acc.idx);
  if (salBox) {
    const minSal = acc.min_salary || (State.lastSnapshot && State.lastSnapshot.config && State.lastSnapshot.config.min_salary) || 0;
    salBox.style.display = minSal > 0 ? '' : 'none';
    setText('acc-sal-' + acc.idx, acc.salary_skipped || 0);
  }

  // HH interviews stat box — свежие (60д) крупно, всего мелко
  const intrvBox = document.getElementById('acc-intrv-box-' + acc.idx);
  if (intrvBox) {
    const recent = acc.hh_interviews_recent ?? acc.hh_interviews ?? 0;
    const total  = acc.hh_interviews || 0;
    intrvBox.style.display = total > 0 ? '' : 'none';
    setText('acc-intrv-' + acc.idx, recent);
    const totalEl = document.getElementById('acc-intrv-total-' + acc.idx);
    if (totalEl) totalEl.textContent = total > recent ? `всего ${total}` : '';
  }


  // Progress bar
  const prog = document.getElementById('acc-prog-' + acc.idx);
  if (prog) {
    let pct = 0;
    if (acc.status === 'applying' && acc.total_vacancies > 0) {
      pct = Math.round(acc.current_vacancy_idx / acc.total_vacancies * 100);
      prog.className = 'acc-progress-fill applying';
    } else if (acc.status === 'collecting') {
      pct = 30; // indeterminate pulse
      prog.className = 'acc-progress-fill';
    } else if (acc.status === 'limit') {
      pct = 100;
      prog.className = 'acc-progress-fill limit';
    } else {
      pct = 0;
      prog.className = 'acc-progress-fill';
    }
    prog.style.width = pct + '%';
  }

  // Compact card mode
  if (State.compactCards.has(acc.idx)) {
    card.classList.add('compact');
  } else {
    card.classList.remove('compact');
  }

  // Consecutive errors badge
  const errBadge = document.getElementById('acc-errbadge-' + acc.idx);
  if (errBadge) {
    const n = acc.consecutive_errors || 0;
    const threshold = State.lastSnapshot?.config?.auto_pause_errors || 5;
    if (n > 0) {
      errBadge.style.display = '';
      errBadge.textContent = `⚡ ${n} ${t('errs_in_row')}`;
      errBadge.style.color = n >= threshold ? 'var(--red)' : 'var(--yellow)';
    } else {
      errBadge.style.display = 'none';
    }
  }

  // Cookies + OAuth status badge
  const cookiesBadge = document.getElementById('acc-cookiesbadge-' + acc.idx);
  if (cookiesBadge) {
    const oa = acc.oauth_status || {};
    if (acc.cookies_expired && oa.has_token) {
      cookiesBadge.style.display = '';
      const skipNote = acc.degraded_skipped ? ` · пропущено ${acc.degraded_skipped} (опросники/тесты)` : '';
      const rs = acc.resume_status_oauth || {};
      const rsNote = rs.blocked
        ? ` · 🚨 резюме заблокировано HH`
        : (rs.progress && rs.progress < 80 ? ` · 📝 резюме ${rs.progress}%` : '');
      // Mobile-native (OTP-логин, cookies никогда не было) — это штатный
      // режим, не «Degraded». Юзеров пугала предупреждающая жёлтая плашка
      // при вполне рабочем аккаунте.
      const isMobileNative = ['mobile', 'oauth'].includes((acc.mode || '').toLowerCase());
      if (isMobileNative) {
        const oauthLabel = (acc.mode || '').toLowerCase() === 'oauth' ? 'OAuth-only' : 'Mobile OAuth';
        cookiesBadge.innerHTML = `📱 ${oauthLabel} (${oa.expires_hours}ч)${skipNote}${rsNote}`;
        cookiesBadge.style.color = rs.blocked ? 'var(--red)' : 'var(--cyan)';
      } else {
        cookiesBadge.innerHTML = acc.degraded_mode
          ? `⚠️ Degraded OAuth-режим (${oa.expires_hours}ч)${skipNote}${rsNote}`
          : `⚠️ Куки протухли | 🔑 OAuth: ✅ токен (${oa.expires_hours}ч)${rsNote}`;
        cookiesBadge.style.color = rs.blocked ? 'var(--red)' : 'var(--yellow)';
      }
    } else if (acc.cookies_expired && !oa.has_token) {
      cookiesBadge.style.display = '';
      cookiesBadge.innerHTML = `⚠️ Куки протухли | 🔑 OAuth: ❌ нет токена — обновите куки!`;
      cookiesBadge.style.color = 'var(--red)';
    } else if (!acc.cookies_expired && oa.has_token) {
      cookiesBadge.style.display = '';
      const rs2 = acc.resume_status_oauth || {};
      const rsNote2 = rs2.blocked
        ? ` · 🚨 резюме заблокировано`
        : (rs2.progress && rs2.progress < 80 ? ` · 📝 резюме ${rs2.progress}%` : '');
      cookiesBadge.innerHTML = `🍪 Куки ✅ | 🔑 OAuth: ✅ токен (${oa.expires_hours}ч)${rsNote2}`;
      cookiesBadge.style.color = rs2.blocked ? 'var(--red)' : 'var(--green)';
    } else {
      cookiesBadge.style.display = '';
      cookiesBadge.innerHTML = `🍪 Куки ✅ | 🔑 OAuth: ⏳ будет получен при отклике`;
      cookiesBadge.style.color = 'var(--dim)';
    }
  }

  // Current vacancy
  const vac = document.getElementById('acc-vacancy-' + acc.idx);
  if (vac) {
    vac.innerHTML = renderAccountVacancy(acc, pauseInfo);
  }
  renderApplicationCheck(acc);
  renderAuthCheck(acc);
  renderProtectiveResume(acc);

  // Meta
  const meta = document.getElementById('acc-meta-' + acc.idx);
  if (meta) {
    const parts = [];
    if (acc.found_vacancies > 0) parts.push(`🔍 ${acc.found_vacancies} найдено`);
    if (acc.next_resume_touch) parts.push(`📤 резюме: ${acc.next_resume_touch}`);
    meta.textContent = parts.join('  ');
  }

  // HH stats
  const hh = document.getElementById('acc-hh-' + acc.idx);
  if (hh) {
    if (acc.hh_stats_loading && !acc.hh_stats_updated) {
      hh.textContent = t('card_hh_loading');
    } else if (acc.hh_stats_updated) {
      const recent = acc.hh_interviews_recent ?? acc.hh_interviews ?? 0;
      const total  = acc.hh_interviews || 0;
      const intrvStr = total > recent
        ? `<span style="color:#f0c060">🎯 ${recent}</span><span class="c-dim"> (${total} всего)</span>`
        : `<span style="color:#f0c060">🎯 ${recent}</span>`;
      const unreadStr = acc.hh_unread_by_employer ? ` &nbsp;<span class="c-blue">📨 ${acc.hh_unread_by_employer} HR не чит.</span>` : '';
      hh.innerHTML =
        intrvStr + ` ${t('hh_interviews')} &nbsp;` +
        `<span class="c-yellow">👁 ${acc.hh_viewed}</span> ${t('hh_viewed')} &nbsp;` +
        `<span class="c-red">❌ ${acc.hh_discards}</span> ${t('hh_discards')}` +
        unreadStr +
        ` &nbsp;<span class="c-dim">(${acc.hh_stats_updated})</span>`;
    } else {
      hh.textContent = acc.hh_stats_loading ? '⏳ HH...' : '—';
    }
  }

  // History
  const hist = document.getElementById('acc-hist-' + acc.idx);
  if (hist && acc.action_history && acc.action_history.length > 0) {
    hist.textContent = acc.action_history.slice(-5).join('  |  ');
  }

  // Per-account event log
  const elog = document.getElementById('acc-elog-' + acc.idx);
  if (elog && acc.acc_event_log) {
    if (acc.acc_event_log.length === 0) {
      elog.innerHTML = '';
    } else {
      elog.innerHTML = acc.acc_event_log.map(e => {
        const co = e.company ? ` <span style="color:var(--dim)">@ ${esc(e.company)}</span>` : '';
        const extra = e.extra ? `<div class="acc-elog-extra">${esc(e.extra)}</div>` : '';
        return `<div class="acc-elog-entry">
          <span class="acc-elog-time">${e.time}</span>
          <span class="acc-elog-icon">${e.icon}</span>
          <div class="acc-elog-body">
            <div class="acc-elog-title">${esc(e.title)}${co}</div>
            ${extra}
          </div>
        </div>`;
      }).join('');
    }
  }

  // Apply tests checkbox
  const skipCb = document.getElementById('acc-apply-cb-' + acc.idx);
  const skipLabel = document.getElementById('acc-apply-label-' + acc.idx);
  if (skipCb) {
    const localToggleAt = parseInt(skipCb.dataset.localToggleAt || '0', 10);
    if (Date.now() - localToggleAt > 2000 && skipCb.checked !== !!acc.apply_tests) {
      skipCb.checked = !!acc.apply_tests;
    }
  }
  if (skipLabel) {
    if (acc.apply_tests) skipLabel.classList.add('active');
    else skipLabel.classList.remove('active');
  }

  // Human mode checkbox — синк из глобального config snapshot.
  const humanCb = document.getElementById('acc-humanmode-cb-' + acc.idx);
  const humanLabel = document.getElementById('acc-humanmode-label-' + acc.idx);
  const humanOn = State.lastSnapshot?.config?.human_mode_enabled !== false;
  if (humanCb && humanCb.checked !== humanOn) humanCb.checked = humanOn;
  if (humanLabel) {
    if (humanOn) humanLabel.classList.add('active');
    else humanLabel.classList.remove('active');
  }

  // Per-account protective preflight and its session counters.
  const safetyCb = document.getElementById('acc-safety-cb-' + acc.idx);
  if (safetyCb) {
    const localToggleAt = parseInt(safetyCb.dataset.localToggleAt || '0', 10);
    if (Date.now() - localToggleAt > 2000) safetyCb.checked = !!acc.safety_enabled;
  }
  const safetyStats = document.getElementById('acc-safety-stats-' + acc.idx);
  if (safetyStats) {
    const mismatch = parseInt(acc.safety_inconsistent_skipped) || 0;
    const misleading = parseInt(acc.safety_misleading_skipped) || 0;
    const redirects = parseInt(acc.safety_redirect_skipped) || 0;
    const total = mismatch + misleading + redirects;
    safetyStats.style.display = acc.safety_enabled ? '' : 'none';
    safetyStats.innerHTML = `🛡️ Защита активна · пропущено ${total}`
      + ` (резюме ${mismatch}, предупреждения ${misleading}, redirect ${redirects})`
      + (acc.safety_last_reason ? `<br><span style="color:var(--dim)">Последнее: ${esc(acc.safety_last_reason)}</span>` : '');
  }

  // Degraded-fallback checkbox (default ON — if field missing, treat as enabled)
  const degCb = document.getElementById('acc-degraded-cb-' + acc.idx);
  const degLabel = document.getElementById('acc-degraded-label-' + acc.idx);
  const degOn = acc.degraded_fallback_enabled !== false;
  if (degCb) {
    const localToggleAt = parseInt(degCb.dataset.localToggleAt || '0', 10);
    if (Date.now() - localToggleAt > 2000 && degCb.checked !== degOn) {
      degCb.checked = degOn;
    }
  }
  if (degLabel) {
    if (degOn) degLabel.classList.add('active');
    else degLabel.classList.remove('active');
  }

  // Pause button — учитываем глобальную паузу
  const captchaPanel = document.getElementById('acc-captcha-' + acc.idx);
  if (captchaPanel) {
    const needsCaptcha = acc.paused && acc.paused_reason === 'challenge';
    const newlyShown = captchaPanel.hidden && needsCaptcha;
    const autoSolve = State.lastSnapshot?.config?.captcha_llm_enabled !== false;
    captchaPanel.hidden = !needsCaptcha;
    // Loading a live GUI image claims this challenge for manual handling.
    // Merely opening an account card must leave the background solver running.
    if (newlyShown && !autoSolve) { loadCaptchaImg(acc.idx, false); }
    const llmLine = document.getElementById('acc-captcha-llm-' + acc.idx);
    if (llmLine) {
      const r = acc.captcha_llm || {};
      const retrySeconds = Number(r.retry_seconds);
      const retryDelay = Number.isFinite(retrySeconds) && retrySeconds > 0
        ? `Следующая попытка через ${retrySeconds} сек.` : 'Следующая попытка запланирована.';
      const retryReasons = {
        isBot: 'HH отклонил ответ',
        unsure: 'модель не смогла распознать картинку',
        recognition_failed: 'модель не смогла распознать картинку',
        model_unavailable: 'локальная модель не вернула ответ',
        http_429: 'HH ограничил частоту запросов',
        unconfirmed: 'HH не подтвердил прохождение проверки',
        unconfirmed_response: 'HH не подтвердил прохождение проверки',
        unconfirmed_transport: 'не удалось получить ответ HH',
        unconfirmed_verification: 'HH не подтвердил завершение проверки',
        network_error: 'не удалось связаться с HH',
        exception: 'ошибка при проверке ответа',
      };
      const retryReason = r.reason ? ` ${retryReasons[r.reason] || r.reason}.` : '';
      const retryAnswer = r.answer ? ` Ответ: «${r.answer}».` : '';
      const text = r.status === 'reading' ? '🤖 Локальная модель читает капчу в фоне. Картинки и ответы доступны в истории капч.'
        : r.status === 'waiting' ? '🤖 Ответ готов. Ожидается отправка в HH.'
        : r.status === 'submitting' ? '🤖 Отправляю ответ HH…'
        : r.status === 'retry' ? `🤖 Фоновая попытка локальной модели.${retryAnswer}${retryReason} ${retryDelay} Картинка и ответ — в истории капч.`
        : r.status === 'blocked' ? (r.reason === 'recaptcha'
          ? 'HH запросил дополнительную проверку reCAPTCHA. Откройте проверку на HH и завершите её вручную.'
          : 'Автоматическое решение приостановлено. Откройте проверку на HH; подробности — в истории капч.')
        : r.status === 'unsure' ? '🤖 Локальная модель не смогла распознать капчу — введите вручную'
        : r.status === 'rejected' ? `🤖 Локальная модель предложила «${r.answer || ''}» — HH не принял, введите вручную`
        : autoSolve ? '🤖 Капчу автоматически решает локальная модель. Картинки и ответы доступны в истории капч.' : '';
      llmLine.textContent = text;
      llmLine.hidden = !needsCaptcha || !text;
    }
    if (!needsCaptcha) {
      const result = document.getElementById('acc-captcha-result-' + acc.idx);
      if (result) result.replaceChildren();
      const image = document.getElementById('acc-captcha-img-' + acc.idx);
      if (image) {
        image.dataset.challengeId = '';
        image.dataset.challengeKey = '';
        image.style.display = 'none';
        if (image.src.startsWith('blob:')) URL.revokeObjectURL(image.src);
        image.removeAttribute('src');
      }
      const input = document.getElementById('acc-captcha-input-' + acc.idx);
      if (input) input.value = '';
    }
  }
  const pauseBtn = document.getElementById('acc-pause-btn-' + acc.idx);
  if (pauseBtn) {
    const globalPaused = State.lastSnapshot?.paused;
    if (acc.paused && hasUnknownApplication(acc)) {
      pauseBtn.textContent = 'Нужна сверка HH';
      pauseBtn.classList.add('paused');
      pauseBtn.disabled = true;
      pauseBtn.title = 'Обычное продолжение заблокировано: сначала проверьте неизвестный исход отклика в HH.';
    } else if (acc.paused && acc.paused_reason === 'challenge') {
      pauseBtn.textContent = acc.telegram_captcha_pending ? '📱 Ждёт TG-ответа' : 'Нужно пройти проверку HH';
      pauseBtn.classList.add('paused');
      pauseBtn.disabled = true;
      pauseBtn.title = 'Используйте панель ручного прохождения проверки.';
    } else if (acc.paused && acc.paused_reason === 'auth') {
      pauseBtn.textContent = acc.mode === 'oauth' ? 'Нужна проверка входа' : 'Нужен вход в HH';
      pauseBtn.classList.add('paused');
      pauseBtn.disabled = true;
      pauseBtn.title = acc.mode === 'oauth'
        ? 'Сначала подтвердите вход в HH кнопкой проверки. Обычное продолжение не снимает защитную паузу.'
        : 'Восстановите авторизацию этого аккаунта в HH. Обычное продолжение не снимает защитную паузу.';
    } else if (acc.paused && acc.paused_reason === 'network_error') {
      pauseBtn.textContent = 'Нужна проверка связи';
      pauseBtn.classList.add('paused');
      pauseBtn.disabled = true;
      pauseBtn.title = 'Сначала нужна проверка связи и доступа к HH. Обычное продолжение не снимает защитную паузу.';
    } else if (globalPaused) {
      pauseBtn.textContent = t('btn_acc_global_pause');
      pauseBtn.classList.add('paused');
      pauseBtn.disabled = true;
      pauseBtn.title = 'Снимите глобальную паузу в правом верхнем углу';
    } else {
      pauseBtn.disabled = false;
      pauseBtn.title = '';
      if (acc.paused) {
        pauseBtn.textContent = t('btn_acc_resume');
        pauseBtn.classList.add('paused');
      } else {
        pauseBtn.textContent = t('btn_acc_pause');
        pauseBtn.classList.remove('paused');
      }
    }
  }

  if (pauseBtn && (!State.ws || State.ws.readyState !== 1)) {
    pauseBtn.disabled = true;
    pauseBtn.title = 'Нет связи с панелью: команда паузы недоступна';
  }

  // LLM toggle button
  const llmBtn = document.getElementById('acc-llm-btn-' + acc.idx);
  if (llmBtn) {
    const enabled = acc.llm_enabled !== false; // default true
    llmBtn.textContent = enabled ? '💬 Ответы ✅' : '💬 Ответы ❌';
    llmBtn.classList.toggle('llm-on', enabled);
    llmBtn.classList.toggle('llm-off', !enabled);
  }
  // LLM status block on card — HUD with reply counter + queue + state
  const llmSt = document.getElementById('acc-llm-status-' + acc.idx);
  if (llmSt) {
    const globalLlm = State.lastSnapshot?.config?.llm_enabled;
    const accLlm = acc.llm_enabled !== false;
    const replied = acc.llm_replied_count || 0;
    const pending = acc.llm_pending_chats || 0;
    let stateChip = '';
    let stateColor = 'var(--dim)';
    let off = false;
    if (!globalLlm) {
      stateChip = 'LLM выкл (глобально)'; stateColor = 'var(--red)'; off = true;
    } else if (!accLlm) {
      stateChip = 'LLM выкл (для акка)'; stateColor = 'var(--dim)'; off = true;
    } else if (acc.llm_status) {
      stateChip = acc.llm_status;
      stateColor = acc.llm_status.startsWith('✅') ? 'var(--green)'
                 : acc.llm_status.startsWith('💤') ? 'var(--dim)'
                 : 'var(--cyan)';
    } else {
      stateChip = 'ожидание первого цикла'; stateColor = 'var(--dim)';
    }
    llmSt.style.display = 'flex';
    llmSt.style.cssText = 'display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:6px 8px;margin:4px 0;'
      + 'background:linear-gradient(180deg,rgba(0,240,255,0.04) 0%,rgba(0,0,0,0.25) 100%);'
      + 'border:1px solid var(--border);border-left:3px solid '+stateColor+';'
      + 'border-radius:3px;font-size:11px;';
    llmSt.innerHTML = `
      <span style="color:${stateColor};text-shadow:0 0 6px ${stateColor};font-weight:700;letter-spacing:0.04em;text-transform:uppercase;font-size:10px">🤖 ${esc(stateChip)}</span>
      <span style="color:var(--dim);font-size:9px;letter-spacing:0.08em;text-transform:uppercase">всего</span>
      <span style="color:var(--green);font-weight:800;font-size:14px;font-variant-numeric:tabular-nums;text-shadow:0 0 6px rgba(0,255,136,0.5)">${replied.toLocaleString('ru')}</span>
      ${off ? '' : `
        <span style="color:var(--dim);font-size:9px;letter-spacing:0.08em;text-transform:uppercase">в очереди</span>
        <span style="color:${pending>0?'var(--yellow)':'var(--dim)'};font-weight:800;font-size:14px;font-variant-numeric:tabular-nums${pending>0?';text-shadow:0 0 6px rgba(255,212,0,0.5)':''}">${pending}</span>
      `}
    `;
  }
  const oauthBtn = document.getElementById('acc-oauth-btn-' + acc.idx);
  if (oauthBtn) {
    const oauth = !!acc.use_oauth;
    oauthBtn.textContent = oauth ? '🔑API' : '🌐Web';
    oauthBtn.style.color = oauth ? 'var(--green)' : 'var(--cyan)';
    oauthBtn.style.borderColor = oauth ? 'var(--green)' : 'var(--cyan)';
  }

  // Smart filters sync (global config → card checkboxes)
  const cfg = State.lastSnapshot?.config || {};
  const freshSummary = card.querySelector('.fresh-mode-summary');
  if (freshSummary) {
    const enabled = cfg.fresh_vacancies_mode === true;
    freshSummary.style.display = enabled ? '' : 'none';
    if (enabled) {
      const hours = Math.max(parseInt(cfg.fresh_vacancy_hours) || 24, 1);
      const reserve = Math.max(parseInt(cfg.fresh_apply_reserve) || 0, 0);
      const ceiling = Math.min(
        ...[parseInt(cfg.daily_apply_limit), parseInt(cfg.hh_daily_limit) || 200].filter(v => v > 0)
      );
      const oldCeiling = Math.max(ceiling - Math.min(reserve, ceiling), 0);
      const used = Math.max(parseInt(acc.daily_sent) || 0, parseInt(acc.hh_today_applies) || 0);
      freshSummary.textContent = `🟢 Свежие ≤${hours}ч идут первыми · резерв ${reserve} · использовано ${used}/${ceiling} · старым до ${oldCeiling}`;
    }
  }
  card.querySelectorAll('.smart-filter-cb').forEach(cb => {
    const key = cb.dataset.key;
    if (key === 'prefer_hh_signals' || key === 'remote_it_only') {
      cb.disabled = typeof cfg[key] !== 'boolean';
      cb.title = cb.disabled ? 'Нужен перезапуск бэкенда для новой настройки' : '';
      if (cb.disabled) cb.checked = false;
    }
    if (cfg[key] !== undefined) cb.checked = cfg[key];
    if (!cb._bound) {
      cb._bound = true;
      cb.onchange = () => sendCmd({type: 'set_config', key, value: cb.checked});
    }
  });
  card.querySelectorAll('.smart-filter-sel').forEach(sel => {
    const key = sel.dataset.key;
    if (cfg[key] !== undefined) sel.value = cfg[key];
    if (!sel._bound) {
      sel._bound = true;
      sel.onchange = () => sendCmd({type: 'set_config', key, value: parseInt(sel.value) || 0});
    }
  });
  card.querySelectorAll('.smart-filter-num').forEach(inp => {
    const key = inp.dataset.key;
    if (cfg[key] !== undefined && !inp._focused) inp.value = cfg[key] || '';
    if (!inp._bound) {
      inp._bound = true;
      inp.onfocus = () => { inp._focused = true; };
      inp.onblur = () => { inp._focused = false; };
      inp.onchange = () => sendCmd({type: 'set_config', key, value: parseInt(inp.value) || 0});
    }
  });
}

function renderGlobalStats(snap) {
  const g = snap.global_stats;
  const el = document.getElementById('global-stats-body');
  if (!el) return;
  const rows = [
    [t('gs_found'),    `<span class="c-cyan">${g.total_found}</span>`],
    [t('gs_applied'),  `<span class="c-green">${g.total_sent}</span>`],
    [t('gs_tests'),    `<span class="c-magenta">${g.total_tests}</span>`],
    [t('gs_errors'),   `<span class="c-red">${g.total_errors}</span>`],
    [t('gs_in_db'),    `<span class="c-blue">${g.storage_total}</span>`],
    [t('gs_in_db_tests'), `<span class="c-magenta">${g.storage_tests}</span>`],
  ];
  el.innerHTML = rows.map(([l, v]) =>
    `<div class="global-row"><span class="lbl">${l}</span>${v}</div>`
  ).join('');
}

async function checkVacancyContact(idx, button) {
  const output = document.getElementById(`contact-result-${idx}`);
  const raw = document.getElementById(`contact-vid-${idx}`)?.value.trim() || '';
  const match = raw.match(/^(\d{1,20})$/) || raw.match(/^https:\/\/(?:[a-z0-9-]+\.)?hh\.ru\/vacancy\/(\d{1,20})(?:[/?#]|$)/i);
  if (!output) return;
  if (!match) { output.textContent = 'Введите ID вакансии или ссылку https://hh.ru/vacancy/…'; return; }
  button.disabled = true;
  output.textContent = 'Проверяю опубликованные контакты…';
  try {
    const response = await fetch(`/api/account/${idx}/vacancy_contact/${match[1]}`);
    const data = await response.json();
    output.textContent = data.message || data.error || 'Данные недоступны';
    if (data.ok) {
      const link = document.createElement('a');
      link.href = `https://hh.ru/vacancy/${match[1]}`;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = ' Открыть в HH';
      output.appendChild(link);
    }
  } catch (_) { output.textContent = 'Не удалось проверить контакты. Попробуйте позже.'; }
  finally { button.disabled = false; }
}

function renderVacancySignals(meta, showUnknown = false, now = Date.now()) {
  meta = meta && typeof meta === 'object' ? meta : {};
  const chips = [];
  if (meta.observation_unavailable) {
    chips.push('<span>❔ История новизны недоступна</span>');
  } else if (meta.publication_updated) {
    chips.push('<span title="Дата публикации изменилась после нашего наблюдения; резерв новинок не используется">♻️ Дата публикации обновлена</span>');
  } else if (meta.first_observed_at) {
    const seen = Date.parse(meta.first_observed_at);
    if (Number.isFinite(seen)) chips.push(`<span title="Первое наблюдение кликера, не доказательство новой публикации">👁 Впервые замечена: ${esc(new Date(seen).toLocaleString())}</span>`);
  }
  const expiry = Date.parse(meta.manager_activity?.is_online_until || '');
  if (Number.isFinite(expiry) && expiry > now) {
    chips.push(`<span data-hh-online-until="${expiry}" style="color:var(--green)" title="Присутствие менеджера по данным HH, не гарантия ответа">🟢 Менеджер онлайн</span>`);
  }
  const score = meta.skills_match_percent;
  if (typeof score === 'number' && Number.isFinite(score) && score >= 0 && score <= 100) {
    chips.push(`<span title="Совпадение навыков по данным HH, не вероятность приглашения">🧩 Навыки ${Math.round(score)}%</span>`);
  }
  const names = {
    got_response: 'Уже есть отклик в HH', got_invitation: 'Приглашение в HH',
    got_rejection: 'Отказ в HH', favorited: 'В избранном HH', blacklisted: 'Скрыта в HH'
  };
  for (const relation of new Set(Array.isArray(meta.relations) ? meta.relations : [])) {
    if (Object.prototype.hasOwnProperty.call(names, relation)) {
      chips.push(`<span title="Статус аккаунта в HH; может относиться к другому резюме">${names[relation]}</span>`);
    }
  }
  return chips.join(' · ') || (showUnknown ? '<span class="c-dim">HH: нет доступных сигналов</span>' : '');
}

function expireVacancyOnlineSignals() {
  const now = Date.now();
  document.querySelectorAll('[data-hh-online-until]').forEach(el => {
    if (Number(el.dataset.hhOnlineUntil) <= now) {
      el.textContent = 'Онлайн-статус HH устарел';
      el.style.color = 'var(--dim)';
      el.removeAttribute('data-hh-online-until');
    }
  });
}
setInterval(expireVacancyOnlineSignals, 1000);

function renderRecentResponses(snap) {
  const list = document.getElementById('recent-list');
  if (!list) return;
  if (!snap.recent_responses.length) {
    list.innerHTML = `<div class="c-dim" style="padding:8px;font-size:11px">${t('recent_empty')}</div>`;
    State.lastResponsesHash = '';
    return;
  }
  const first = snap.recent_responses[0];
  const hash = snap.recent_responses.length + '|' + (first?.time || '') + '|' + (first?.id || '');
  if (hash === State.lastResponsesHash) return;
  State.lastResponsesHash = hash;
  list.innerHTML = snap.recent_responses.slice(0, 50).map(r => {
    const title = r.title ? r.title.substring(0, 35) + (r.title.length > 35 ? '…' : '') : `ID:${r.id}`;
    // HR online / chat status chips — данные пришли с бэка в vacancy_meta.
    const chips = [];
    const hhSignals = renderVacancySignals(r);
    if (hhSignals) chips.push(hhSignals);
    if (r.hr_online === 'online' && !r.manager_activity?.is_online_until) {
      chips.push('<span style="color:var(--dim);font-size:10px" title="HR был онлайн при проверке; текущий статус неизвестен">🟢</span>');
    } else if (r.hr_online === 'offline') {
      chips.push('<span style="color:var(--dim);font-size:10px" title="HR offline">⚫</span>');
    }
    if ((r.chat_write || '').toUpperCase() === 'DISABLED') {
      chips.push('<span style="color:var(--red);font-size:10px" title="Чат закрыт работодателем — нельзя писать">🚫</span>');
    }
    if (r.accept_auto === false) {
      chips.push('<span style="color:var(--yellow);font-size:10px" title="Требует cover letter или опросник">📝</span>');
    }
    const er = r.employer_rating;
    if (er && er.rating) {
      const col = er.rating >= 4 ? 'var(--green)' : (er.rating >= 3 ? 'var(--yellow)' : 'var(--red)');
      chips.push(`<span style="color:${col};font-size:10px" title="HH рейтинг: ${er.rating}/5 (${er.reviews_count} отз., ${er.recommendations_percent}% рек.)">⭐${er.rating.toFixed(1)}</span>`);
    }
    const chipsHtml = chips.length ? ` ${chips.join(' ')}` : '';
    return `
      <div class="resp-item">
        <span class="resp-time">${r.time}</span>
        <span>${r.icon}</span>
        <div>
          <div class="resp-title">${esc(title)}${chipsHtml}</div>
          ${r.company ? `<div class="resp-company">@ ${esc(r.company)}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// ── Log tab ──
function logSetLevel(btn, level) {
  State.logLevel = level;
  document.querySelectorAll('.log-level-btn').forEach(b => {
    const isActive = b.dataset.level === level;
    if (isActive) b.classList.add('active');
    else b.classList.remove('active');
  });
  if (State.lastSnapshot) renderLog(State.lastSnapshot);
}

function logSyncAccFilter(snap) {
  const sel = document.getElementById('log-acc-filter');
  if (!sel) return;
  const current = sel.value;
  const names = [...new Set((snap.accounts||[]).map(a => a.short).filter(Boolean))];
  sel.innerHTML = `<option value="">${t('log_all_accs')}</option>` +
    names.map(n => `<option value="${esc(n)}"${current===n?' selected':''}>${esc(n)}</option>`).join('');
}

let _renderLogLastKey = '';
function renderLog(snap) {
  if (!snap) return;
  logSyncAccFilter(snap);
  const list = document.getElementById('log-list');
  if (!list || !snap.log) return;

  const search = (document.getElementById('log-search')?.value || '').toLowerCase();
  const accF   = document.getElementById('log-acc-filter')?.value || '';
  const level  = State.logLevel;

  let entries = snap.log;
  if (level)  entries = entries.filter(e => e.level === level);
  if (accF)   entries = entries.filter(e => e.acc === accF);
  if (search) entries = entries.filter(e =>
    (e.message||'').toLowerCase().includes(search) || (e.acc||'').toLowerCase().includes(search)
  );
  entries = entries.slice(0, State.MAX_LOG_NODES);

  const cnt = document.getElementById('log-count');
  if (cnt) cnt.textContent = `${entries.length} записей`;

  const last = entries.length > 0 ? entries[entries.length - 1] : null;
  const logKey = entries.length + '|' + (last ? last.time + last.acc + (last.message||'') : '');
  if (logKey === _renderLogLastKey) return;
  _renderLogLastKey = logKey;

  const frag = document.createDocumentFragment();
  entries.forEach(entry => {
    const el = document.createElement('div');
    el.className = 'log-item';
    el.innerHTML = `
      <span class="log-time">${entry.time}</span>
      <span class="log-acc" style="color:${colorVar(entry.color)}">${esc(entry.acc)}</span>
      <span class="log-msg log-${entry.level}">${esc(entry.message)}</span>
    `;
    frag.appendChild(el);
  });
  list.innerHTML = '';
  list.appendChild(frag);
}

// ── HH Status tab ──
function renderHH(snap) {
  const content = document.getElementById('hh-content');
  if (!content || !snap.accounts) return;

  content.innerHTML = snap.accounts.filter(acc => !acc.temp || acc.bot_active).map(acc => {
    let body = '';
    if (acc.hh_stats_loading && !acc.hh_stats_updated) {
      body = `<div class="c-dim">${t('hh_loading')}</div>`;
    } else if (!acc.hh_stats_updated) {
      body = `<div class="c-dim">${t('hh_no_data')}</div>`;
    } else {
      // Counters
      body += `<div class="hh-counters">
        <div class="hh-counter"><div class="hh-counter-val c-green">${acc.hh_interviews}</div><div class="hh-counter-lbl">${t('hh_interviews')}</div></div>
        <div class="hh-counter"><div class="hh-counter-val c-yellow">${acc.hh_viewed}</div><div class="hh-counter-lbl">${t('hh_viewed')}</div></div>
        <div class="hh-counter"><div class="hh-counter-val c-red">${acc.hh_discards}</div><div class="hh-counter-lbl">${t('hh_discards')}</div></div>
        <div class="hh-counter"><div class="hh-counter-val c-dim">${acc.hh_not_viewed}</div><div class="hh-counter-lbl">${t('hh_not_viewed')}</div></div>
        ${acc.hh_unread_by_employer ? `<div class="hh-counter"><div class="hh-counter-val c-blue">${acc.hh_unread_by_employer}</div><div class="hh-counter-lbl">HR не чит.</div></div>` : ''}
      </div>`;
      body += `<div class="c-dim" style="font-size:11px;margin-bottom:10px">${t('hh_updated')} ${acc.hh_stats_updated}</div>`;

      // Interview list
      if (acc.hh_interviews_list && acc.hh_interviews_list.length) {
        body += `<div style="font-weight:700;margin-bottom:6px;color:var(--green)">${t('hh_inv_list')}</div>`;
        body += acc.hh_interviews_list.map(item => {
          const url = item.neg_id ? `https://hh.ru/applicant/negotiations/${encodeURIComponent(item.neg_id)}` : '';
          const textEl = url
            ? `<a class="hh-interview-text" href="${url}" target="_blank" rel="noopener">${esc(item.text || '')}</a>`
            : `<span class="hh-interview-text">${esc(item.text || '')}</span>`;
          return `<div class="hh-interview-item">` +
            (item.date ? `<span class="hh-interview-date">${esc(item.date)}</span>` : '') +
            textEl +
            `</div>`;
        }).join('');
      }

      // Possible offers
      if (acc.hh_possible_offers && acc.hh_possible_offers.length) {
        body += `<div style="font-weight:700;margin:12px 0 6px;color:var(--yellow)">${t('hh_offers')}</div>`;
        body += acc.hh_possible_offers.map(o =>
          `<div class="hh-offer-item">
            <div class="hh-offer-name">${esc(o.name)}</div>
            <div class="hh-offer-vacs">${o.vacancyNames.slice(0,3).map(n=>esc(n)).join(', ')}</div>
          </div>`
        ).join('');
      }
    }

    // Whitelist цветов — иначе acc.color мог бы быть `foo" onmouseover="alert(1)`.
    const colorStyle = `color:${colorVar(acc.color || '')}`;
    return `
      <div class="hh-account-block">
        <div class="hh-account-title" style="${colorStyle}">${esc(acc.name)}</div>
        ${body}
      </div>
    `;
  }).join('');
}

// ── Applied / Tests tabs ──
const QuestionnaireHistoryState = {offset: 0, pageSize: 50, total: 0};

function questionnaireStatusLabel(run) {
  if (run.blocked) return '🛑 Остановлен проверкой ответа';
  if (run.error_code === 'resume_visibility_restricted') return '🔒 HH требует открыть видимость резюме';
  if (run.diagnosis === 'resume_visibility_restricted') return '🔒 HH требует открыть видимость резюме';
  if (run.status === 'test') {
    return run.submitted ? '⚠️ HH вернул на анкету' :
      run.no_fields ? '⚠️ В форме не было вопросов' : '⚠️ Анкета не заполнена';
  }
  const labels = {
    sent: '✅ Отклик подтверждён', already: '↩ Уже откликались',
    unknown: '⚠️ Результат не подтверждён', error: '❌ Не отправлен',
    auth_error: '🔐 Ошибка входа', challenge: '🧩 Капча',
    limit: '🚫 Лимит HH',
    cancelled: '⏸ Отменён', preview: '🔎 Предпросмотр, не отправлен',
    in_progress: '⏳ Нет итоговой записи'
  };
  return labels[run.status] || `⚠️ ${run.status || 'Неизвестно'}`;
}

async function loadQuestionnaireHistory(append = false) {
  const list = document.getElementById('questionnaire-history-list');
  if (!list) return;
  if (!append) { QuestionnaireHistoryState.offset = 0; list.textContent = 'Загрузка…'; }
  const offset = QuestionnaireHistoryState.offset;
  try {
    const response = await fetch(`/api/apply/questionnaire-history?limit=${QuestionnaireHistoryState.pageSize}&offset=${offset}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(response.status === 401 ? 'Нужен API-ключ' : `HTTP ${response.status}`);
    const data = await response.json();
    if (!data.ok || !Array.isArray(data.items)) throw new Error(data.error || 'Некорректный ответ сервера');
    QuestionnaireHistoryState.total = data.total;
    QuestionnaireHistoryState.offset += data.items.length;
    document.getElementById('questionnaire-history-count').textContent = `(${data.total} трассы)`;
    document.getElementById('questionnaire-tests-found').textContent = Number.isInteger(data.stats?.found) ? data.stats.found.toLocaleString('ru-RU') : '—';
    document.getElementById('questionnaire-tests-applied').textContent = Number.isInteger(data.stats?.applied) ? data.stats.applied.toLocaleString('ru-RU') : '—';
    const outcomes = data.outcomes || {};
    const outcomeBox = document.getElementById('questionnaire-history-outcomes');
    if (outcomeBox) outcomeBox.textContent = `Трассы: подтверждено ${outcomes.confirmed ?? '—'} · HH уже видел отклик ${outcomes.already ?? '—'} · без вопросов ${outcomes.no_fields ?? '—'} (${outcomes.no_field_vacancies ?? '—'} вакансии) · HH вернул на форму ${outcomes.returned_to_form ?? '—'} (видимость резюме: ${outcomes.visibility_blocked ?? '—'}) · результат не подтверждён ${outcomes.unconfirmed ?? '—'}.`;
    if (!append) list.innerHTML = '';
    if (!data.total) list.textContent = 'Пока нет сохранённых трасс анкет.';
    else list.insertAdjacentHTML('beforeend', data.items.map(run => {
      const date = run.at ? new Date(run.at).toLocaleString('ru-RU') : '—';
      const link = /^\d{5,20}$/.test(String(run.vacancy_id))
        ? `<a href="https://hh.ru/vacancy/${encodeURIComponent(run.vacancy_id)}" target="_blank" rel="noopener noreferrer">${esc(run.title || `Вакансия ${run.vacancy_id}`)}</a>`
        : esc(run.title || run.vacancy_id || 'Вакансия');
      return `<details class="questionnaire-run" data-run-id="${esc(run.run_id)}" style="border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin:8px 0;background:var(--bg-card2)">
        <summary style="cursor:pointer;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <span class="c-dim">${esc(date)}</span><strong>${link}</strong>
          <span>${esc(questionnaireStatusLabel(run))}</span>
          <span class="c-dim">${esc(run.account || '')} · ${Number(run.question_count) || 0} вопросов · ${run.origin === 'automatic' ? 'авто' : 'точечный'}</span>
        </summary>
        <div class="questionnaire-run-detail c-dim" style="padding:12px 2px 2px">Откройте, чтобы загрузить вопросы и трассу.</div>
      </details>`;
    }).join(''));
    document.getElementById('questionnaire-history-more').style.display = QuestionnaireHistoryState.offset < data.total ? '' : 'none';
  } catch (error) {
    if (!append) list.textContent = `Не удалось загрузить историю: ${error.message}`;
  }
}

function loadMoreQuestionnaireHistory() { loadQuestionnaireHistory(true); }

async function loadQuestionnaireRun(details) {
  const box = details.querySelector('.questionnaire-run-detail');
  if (!box || box.dataset.loaded) return;
  box.textContent = 'Загрузка вопросов и трассы…';
  try {
    const runId = details.dataset.runId;
    const response = await fetch(`/api/apply/questionnaire-history/${encodeURIComponent(runId)}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(response.status === 401 ? 'Нужен API-ключ' : `HTTP ${response.status}`);
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Прогон не найден');
    const questions = data.questions || [];
    const qHtml = questions.length ? questions.map((q, index) => `
      <div style="border-top:1px solid var(--border);padding:10px 0">
        <div style="font-weight:600">${index + 1}. ${esc(q.text || q.field)}</div>
        <div style="white-space:pre-wrap;margin-top:5px">${q.answer == null ? '<span class="c-dim">Ответ не сформирован</span>' : esc(Array.isArray(q.answer) ? q.answer.join(', ') : String(q.answer))}</div>
        <small class="c-dim">${q.source === 'llm' ? 'Ответ LLM' : q.source === 'template' ? 'Шаблон' : 'Источник не записан'}</small>
      </div>`).join('') : '<div class="c-dim">Вопросы не были получены.</div>';
    const llm = data.llm || {};
    const llmHtml = llm.provider ? `<div style="margin:8px 0">LLM: ${esc(llm.provider)}${llm.profile ? ' · ' + esc(llm.profile) : ''}${llm.model ? ' · ' + esc(llm.model) : ''}</div>` : '';
    const stages = data.timeline || [];
    const timeline = stages.map(e => `<li style="margin:5px 0"><span class="c-dim">${esc(e.at ? new Date(e.at).toLocaleTimeString('ru-RU') : '')}</span> <strong>${esc(e.stage)}</strong><pre style="white-space:pre-wrap;overflow-wrap:anywhere;margin:3px 0 0;font-size:11px">${esc(JSON.stringify(e.details || {}, null, 2))}</pre></li>`).join('');
    box.innerHTML = `<div style="margin-bottom:8px">${esc(questionnaireStatusLabel(data.run))}${data.run.error_code ? ' · ' + esc(data.run.error_code) : ''}</div>${llmHtml}<h4>Вопросы и отправленные ответы</h4>${qHtml}<details style="margin-top:12px"><summary style="cursor:pointer">Полная трасса (${stages.length} событий)</summary><ol style="padding-left:20px">${timeline}</ol></details>`;
    box.dataset.loaded = 'true';
  } catch (error) { box.textContent = `Не удалось загрузить детали: ${error.message}`; }
}

document.getElementById('questionnaire-history-list')?.addEventListener('toggle', event => {
  const details = event.target;
  if (details.matches?.('.questionnaire-run') && details.open) loadQuestionnaireRun(details);
}, true);

// Applied tab state
const AppliedState = { all: [], shown: 0, pageSize: 80 };

async function loadApplied(force) {
  try {
    const res = await fetch('/api/applied?limit=2000');
    if (!res.ok) throw new Error(res.status === 401 ? 'Unauthorized: укажите API-ключ' : `HTTP ${res.status}`);
    const items = await res.json();
    if (!Array.isArray(items)) throw new Error(items?.error || 'Некорректный ответ сервера');
    AppliedState.all = items;
    // Populate account filter
    const sel = document.getElementById('applied-acc-filter');
    const prev = sel.value;
    const activeNames = new Set((State.lastSnapshot?.accounts || []).flatMap(a => [a.name, a.short]).filter(Boolean));
    const accs = [...new Set(items.map(i => i.account).filter(a => a && activeNames.has(a)))].sort();
    sel.innerHTML = `<option value="">${t('applied_all_accs')}</option>` +
      accs.map(a => `<option value="${esc(a)}"${a===prev?' selected':''}>${esc(a)}</option>`).join('');
    appliedRender();
  } catch(e) { console.error('loadApplied', e); alert(e.message); }
}

function appliedSort(field) {
  if (AppliedSort.field === field) AppliedSort.dir *= -1;
  else { AppliedSort.field = field; AppliedSort.dir = -1; }
  // update header arrows
  document.querySelectorAll('#panel-applied .sort-th').forEach(th => {
    const f = th.getAttribute('onclick')?.match(/appliedSort\('(\w+)'\)/)?.[1];
    th.classList.toggle('sorted', f === field);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = (f === field) ? (AppliedSort.dir === -1 ? '↓' : '↑') : '↕';
  });
  appliedRender();
}

function appliedRender() {
  const search = (document.getElementById('applied-search')?.value || '').toLowerCase();
  const accF   = document.getElementById('applied-acc-filter')?.value || '';
  const hideEmpty = document.getElementById('applied-hide-empty')?.checked;

  let items = AppliedState.all;
  if (accF)      items = items.filter(i => i.account === accF);
  if (hideEmpty) items = items.filter(i => i.title || i.company);
  if (search)    items = items.filter(i =>
    (i.title||'').toLowerCase().includes(search) ||
    (i.company||'').toLowerCase().includes(search) ||
    (i.vacancy_id||'').includes(search)
  );

  // Sort
  const sf = AppliedSort.field, sd = AppliedSort.dir;
  items = [...items].sort((a, b) => {
    let av = a[sf] ?? '', bv = b[sf] ?? '';
    if (typeof av === 'number') return (av - bv) * sd;
    return String(av).localeCompare(String(bv), 'ru') * sd;
  });

  document.getElementById('applied-count').textContent = `(${items.length})`;
  AppliedState.shown = Math.min(AppliedState.pageSize, items.length);
  appliedFillTable(items.slice(0, AppliedState.shown));

  const lm = document.getElementById('applied-loadmore');
  const sh = document.getElementById('applied-shown');
  if (items.length > AppliedState.shown) {
    lm.style.display = 'block';
    sh.textContent = `${t('shown_of')} ${AppliedState.shown} ${t('shown_of2')} ${items.length}`;
    lm._items = items;
  } else {
    lm.style.display = 'none';
  }
}

function appliedShowMore() {
  const lm = document.getElementById('applied-loadmore');
  const items = lm._items || [];
  AppliedState.shown = Math.min(AppliedState.shown + AppliedState.pageSize, items.length);
  appliedFillTable(items.slice(0, AppliedState.shown));
  const sh = document.getElementById('applied-shown');
  if (AppliedState.shown >= items.length) {
    lm.style.display = 'none';
  } else {
    sh.textContent = `${t('shown_of')} ${AppliedState.shown} ${t('shown_of2')} ${items.length}`;
  }
}

function appliedFillTable(items) {
  const tbody = document.getElementById('applied-tbody');
  if (!tbody) return;
  tbody.innerHTML = items.map(item => {
    const dt = item.at
      ? new Date(item.at).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})
      : '';
    const acc = (item.account || '').replace(/^(.*?)\s*\((.+?)\)\s*$/, '$2') || item.account || '';
    const sal = item.salary_from || item.salary_to
      ? `${item.salary_from ? item.salary_from.toLocaleString('ru') : '?'} — ${item.salary_to ? item.salary_to.toLocaleString('ru') : '?'}`
      : '';
    const hasTitle = !!(item.title || item.company);
    const titleCell = item.title
      ? `<a href="${safeHref(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>`
      : `<a href="${safeHref(item.url)}" target="_blank" rel="noopener noreferrer" style="color:var(--dim)">hh.ru/vacancy/${esc(item.vacancy_id)}</a>`;
    return `<tr class="${hasTitle ? '' : 'row-no-title'}">
      <td class="c-dim" style="white-space:nowrap">${dt}</td>
      <td style="white-space:nowrap">${esc(acc)}</td>
      <td>${titleCell} <button class="btn-sm" style="padding:0 6px;font-size:11px" title="Похожие вакансии (api.hh.ru)" onclick="showSimilarVacancies('${esc(item.vacancy_id)}',this)">🔁</button></td>
      <td>${esc(item.company || '')}</td>
      <td class="c-green" style="white-space:nowrap">${sal}</td>
    </tr>`;
  }).join('');
}

// Similar vacancies expand: api.hh.ru /vacancies/{vid}/similar_vacancies
// public endpoint, 36k результатов на один seed. Backend кэширует 6ч.
const _SimilarCache = {};
async function showSimilarVacancies(vid, btn) {
  if (!vid || !btn) return;
  const tr = btn.closest('tr');
  if (!tr) return;
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains('similar-row')) {
    existing.remove();
    return;
  }
  const newTr = document.createElement('tr');
  newTr.className = 'similar-row';
  newTr.innerHTML = `<td colspan="5" style="padding:8px 12px;background:rgba(0,200,255,0.03)"><div style="color:var(--dim);font-size:12px">⏳ Загружаю похожие…</div></td>`;
  tr.parentNode.insertBefore(newTr, tr.nextSibling);
  let data = _SimilarCache[vid];
  if (!data) {
    try {
      const r = await fetch(`/api/vacancy/${encodeURIComponent(vid)}/similar?per_page=10`);
      data = await r.json();
      _SimilarCache[vid] = data;
    } catch(e) {
      newTr.querySelector('div').textContent = '❌ Ошибка загрузки';
      return;
    }
  }
  const items = data.items || [];
  if (!items.length) {
    newTr.querySelector('div').textContent = '— похожих не найдено';
    return;
  }
  const rowsHtml = items.map(v => {
    const sal = v.salary_from || v.salary_to
      ? `${v.salary_from ? v.salary_from.toLocaleString('ru') : '?'} — ${v.salary_to ? v.salary_to.toLocaleString('ru') : '?'} ${v.salary_currency||''}`
      : '<span style="color:var(--dim)">—</span>';
    const chips = [];
    if (v.has_test) chips.push('<span style="color:var(--yellow);font-size:10px" title="С тестом">🧪</span>');
    if (v.response_letter_required) chips.push('<span style="color:var(--yellow);font-size:10px" title="Нужно письмо">📝</span>');
    if (v.accept_incomplete_resumes) chips.push('<span style="color:var(--green);font-size:10px" title="Принимают неполные резюме">✅</span>');
    if (v.internship) chips.push('<span style="color:var(--dim);font-size:10px" title="Стажировка">🎓</span>');
    return `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:3px 6px;font-size:11px"><a href="${safeHref(v.alternate_url)}" target="_blank" rel="noopener">${esc(v.name||'?').slice(0,55)}</a> ${chips.join(' ')}</td>
      <td style="padding:3px 6px;font-size:11px">${esc(v.employer_name||'').slice(0,25)}</td>
      <td style="padding:3px 6px;font-size:10px;color:var(--dim)">${esc(v.area_name)} · ${esc(v.schedule)} · ${esc(v.experience)}</td>
      <td style="padding:3px 6px;font-size:11px;color:var(--green);white-space:nowrap">${sal}</td>
    </tr>`;
  }).join('');
  newTr.querySelector('td').innerHTML = `
    <div style="font-size:11px;color:var(--dim);margin-bottom:4px">HH знает ${(data.found||0).toLocaleString('ru')} похожих на эту вакансию · показано ${items.length}</div>
    <table style="width:100%"><tbody>${rowsHtml}</tbody></table>
  `;
}

// ── Vacancy DB tab ───────────────────────────────────────────────
const DBState = { all: [], shown: 0, pageSize: 100 };
const DB_STATUS = {
  sent:         ['✅', 'db_status_sent_lbl',        'c-green'],
  test_passed:  ['📝', 'db_status_test_passed_lbl', 'c-cyan'],
  test_pending: ['🧪', 'db_status_test_pending_lbl','c-magenta'],
};
// DB_STATUS translated labels
T.ru.db_status_sent_lbl         = 'Отклик отправлен';
T.ru.db_status_test_passed_lbl  = 'Тест пройден';
T.ru.db_status_test_pending_lbl = 'Не пройден';
T.en.db_status_sent_lbl         = 'Applied';
T.en.db_status_test_passed_lbl  = 'Test passed';
T.en.db_status_test_pending_lbl = 'Not passed';

async function loadDB(force) {
  try {
    const res = await fetch('/api/vacancies?limit=3000');
    if (!res.ok) throw new Error(res.status === 401 ? 'Unauthorized: укажите API-ключ' : `HTTP ${res.status}`);
    const items = await res.json();
    if (!Array.isArray(items)) throw new Error(items?.error || 'Некорректный ответ сервера');
    DBState.all = items;
    // Populate account filter
    const sel = document.getElementById('db-acc-filter');
    const prev = sel.value;
    const activeNames = new Set((State.lastSnapshot?.accounts || []).flatMap(a => [a.name, a.short]).filter(Boolean));
    const accs = [...new Set(items.flatMap(i => i.applied_by || []).filter(a => activeNames.has(a)))].sort();
    sel.innerHTML = `<option value="">${t('db_all_accs')}</option>` +
      accs.map(a => `<option value="${esc(a)}"${a===prev?' selected':''}>${esc(a)}</option>`).join('');
    dbRender();
  } catch(e) { console.error('loadDB', e); alert(e.message); }
}

function dbSort(field) {
  if (DBSort.field === field) DBSort.dir *= -1;
  else { DBSort.field = field; DBSort.dir = -1; }
  document.querySelectorAll('#panel-db .sort-th').forEach(th => {
    const f = th.getAttribute('onclick')?.match(/dbSort\('(\w+)'\)/)?.[1];
    th.classList.toggle('sorted', f === field);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = (f === field) ? (DBSort.dir === -1 ? '↓' : '↑') : '↕';
  });
  dbRender();
}

function dbRender() {
  const search  = (document.getElementById('db-search')?.value || '').toLowerCase();
  const statusF = document.getElementById('db-status-filter')?.value || '';
  const accF    = document.getElementById('db-acc-filter')?.value || '';

  let items = DBState.all;
  if (statusF) items = items.filter(i => i.status === statusF);
  if (accF)    items = items.filter(i => (i.applied_by || []).includes(accF));
  if (search)  items = items.filter(i =>
    (i.title||'').toLowerCase().includes(search) ||
    (i.company||'').toLowerCase().includes(search) ||
    (i.vacancy_id||'').includes(search)
  );

  // Sort
  const sf = DBSort.field, sd = DBSort.dir;
  items = [...items].sort((a, b) => {
    let av = a[sf] ?? '', bv = b[sf] ?? '';
    if (typeof av === 'number') return (av - bv) * sd;
    return String(av).localeCompare(String(bv), 'ru') * sd;
  });

  document.getElementById('db-count').textContent =
    `(${items.length} из ${DBState.all.length})`;
  DBState.shown = Math.min(DBState.pageSize, items.length);
  dbFillTable(items.slice(0, DBState.shown));

  const lm = document.getElementById('db-loadmore');
  const sh = document.getElementById('db-shown');
  if (items.length > DBState.shown) {
    lm.style.display = 'block';
    sh.textContent = `${t('shown_of')} ${DBState.shown} ${t('shown_of2')} ${items.length}`;
    lm._items = items;
  } else {
    lm.style.display = 'none';
  }
}

function dbShowMore() {
  const lm = document.getElementById('db-loadmore');
  const items = lm._items || [];
  DBState.shown = Math.min(DBState.shown + DBState.pageSize, items.length);
  dbFillTable(items.slice(0, DBState.shown));
  const sh = document.getElementById('db-shown');
  if (DBState.shown >= items.length) lm.style.display = 'none';
  else sh.textContent = `${t('shown_of')} ${DBState.shown} ${t('shown_of2')} ${items.length}`;
}

function dbFillTable(items) {
  const tbody = document.getElementById('db-tbody');
  if (!tbody) return;
  tbody.innerHTML = items.map(item => {
    const [icon, labelKey, cls] = DB_STATUS[item.status] || ['❓', null, 'c-dim'];
    const label = labelKey ? t(labelKey) : esc(item.status);
    const dt = item.at
      ? new Date(item.at).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})
      : '';
    const titleCell = item.title
      ? `<a href="${safeHref(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>`
      : `<a href="${safeHref(item.url)}" target="_blank" rel="noopener noreferrer" style="color:var(--dim)">hh.ru/vacancy/${esc(item.vacancy_id)}</a>`;
    const accs = (item.applied_by || [])
      .map(a => `<span style="font-size:10px;background:var(--bg-card2);padding:1px 5px;border-radius:3px">${esc(a.replace(/^.*?\((.+?)\).*$/, '$1') || a)}</span>`)
      .join(' ');
    return `<tr>
      <td><span class="${cls}" style="white-space:nowrap">${icon} ${label}</span></td>
      <td class="c-dim" style="white-space:nowrap">${dt}</td>
      <td>${titleCell}</td>
      <td>${esc(item.company || '')}</td>
      <td>${accs || '<span class="c-dim">—</span>'}</td>
      <td><button class="btn-sm" style="padding:1px 6px;color:var(--red);border-color:var(--red)"
        data-vid="${esc(item.vacancy_id)}" onclick="dbDelete(this.dataset.vid,this)" title="Удалить из базы">✕</button></td>
    </tr>`;
  }).join('');
}

async function dbDelete(vid, btn) {
  if (!await showConfirm(`${t('confirm_del_db_pre')} ${vid} ${t('confirm_del_db_mid')}\n${t('confirm_del_db_body')}`)) return;
  btn.disabled = true;
  try {
    const res = await fetch(`/api/vacancy/${vid}`, {method:'DELETE'});
    const data = await res.json();
    if (data.ok) {
      DBState.all = DBState.all.filter(i => i.vacancy_id !== vid);
      btn.closest('tr').remove();
      const cnt = document.getElementById('db-count');
      if (cnt) cnt.textContent = `(${DBState.all.length})`;
    } else {
      btn.disabled = false;
    }
  } catch(e) { btn.disabled = false; }
}

async function loadTests() {
  try {
    const res = await fetch('/api/tests?limit=300');
    const items = await res.json();
    const tbody = document.getElementById('tests-tbody');
    document.getElementById('tests-count').textContent = `(${items.length})`;

    tbody.innerHTML = items.map(item => {
      const dt = item.at ? new Date(item.at).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
      // Account name: short (strip parenthetical) if possible
      const accFull = item.account_name || '';
      const accShort = accFull.replace(/^.*?\((.+?)\).*$/, '$1') || accFull;
      const resumeLink = item.resume_hash
        ? `<a href="https://hh.ru/resume/${encodeURIComponent(item.resume_hash)}" target="_blank" style="font-size:11px;color:var(--cyan)">${esc(accShort)}</a>`
        : `<span class="c-dim">${esc(accShort) || '—'}</span>`;
      // Applied by list — каждое имя через esc() (account name может прийти от пользователя)
      const appliedBy = item.applied_by || [];
      const appliedCell = appliedBy.length
        ? `<span style="color:var(--green)">✅ ${appliedBy.map(a => esc(a.replace(/^.*?\((.+?)\).*$/, '$1') || a)).join(', ')}</span>`
        : `<span class="c-dim">—</span>`;
      return `<tr>
        <td class="c-dim">${dt}</td>
        <td>${esc(item.title || item.vacancy_id)}</td>
        <td>${esc(item.company)}</td>
        <td>${resumeLink}</td>
        <td>${appliedCell}</td>
        <td><a href="${safeHref(item.url || '')}" target="_blank" rel="noopener noreferrer">hh.ru/vacancy/${esc(item.vacancy_id)}</a></td>
      </tr>`;
    }).join('');
  } catch(e) {}
}

// ── Tabs switching ──────────────────────────────────────────────
document.getElementById('tabs').addEventListener('click', e => {
  const t = e.target.closest('.tab');
  if (!t) return;
  const tab = t.dataset.tab;
  if (!tab) return;

  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(el => el.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('panel-' + tab).classList.add('active');
  State.currentTab = tab;
  try { localStorage.setItem('hh-tab', tab); } catch(e) {}

  // Reset settings-tab built flags so they rebuild with fresh data on next open
  if (tab !== 'settings') {
    const urlEl = document.getElementById('url-pool-rows');
    if (urlEl) urlEl.dataset.built = 'false';
    const sessEl = document.getElementById('sess-list');
    if (sessEl) sessEl.dataset.count = '';
  }

  // Load REST tabs on switch
  if (tab === 'applied') loadApplied();
  else if (tab === 'tests') loadTests();
  else if (tab === 'questionnaire-history') loadQuestionnaireHistory();
  else if (tab === 'db') loadDB();
  else if (tab === 'hh' && State.lastSnapshot) renderHH(State.lastSnapshot);
  else if (tab === 'hedi' && typeof initHediTab === 'function') initHediTab();
  else if (tab === 'llm') {
    // Only reload table if stale (>10s since last load) — prevents wipe on quick tab switches
    const stale = Date.now() - _llmLastDbRefresh > 10000;
    if (stale) { llmInterviewsLoad(); llmRenderAccStats(); }
    if (State.lastSnapshot) renderLlmLog(State.lastSnapshot);
  }
  else if (tab === 'log' && State.lastSnapshot) renderLog(State.lastSnapshot);
  else if (tab === 'views') loadViews();
  else if (tab === 'apply') {
    if (State.lastSnapshot) applyBuildAccountSelect(State.lastSnapshot);
  }
  else if (tab === 'settings') {
    loadCaptchaModels();
    if (!State.lastSnapshot) return;
    syncCaptchaMode(State.lastSnapshot.config);
    syncSettingsSliders(State.lastSnapshot);
    qSyncFromSnapshot(State.lastSnapshot);
    ltSyncFromSnapshot(State.lastSnapshot);
    buildAccCookiesList(State.lastSnapshot);
    urlPoolBuild(State.lastSnapshot);
    buildSessList(State.lastSnapshot);
  }
});

const HUMAN_SETTINGS = [
  ['human_mode_enabled', 'Включён', 'checkbox', true],
  ['human_active_hours', 'Активные часы (HH-HH)', 'text', '07-24'],
  ['human_apply_delay_min', 'Задержка min (сек)', 'number', 15],
  ['human_apply_delay_max', 'Задержка max (сек)', 'number', 45],
];
const humanDrafts = new Map();
const humanPending = new Map();
let humanSubmissionComplete = false;

function humanValue(key, type, scale = 1) {
  const el = document.getElementById('hp-' + key);
  return type === 'checkbox' ? el.checked : type === 'number' ? (el.value.trim() ? Number(el.value) * scale : NaN) : el.value.trim();
}

function syncHumanSettings(snap) {
  const container = document.getElementById('human-settings');
  if (!container) return;
  if (!container.children.length) {
    HUMAN_SETTINGS.forEach(([key, label, type, initial, scale = 1]) => {
      const row = document.createElement('label');
      row.textContent = label + ' ';
      const el = document.createElement('input');
      el.id = 'hp-' + key;
      el.type = type;
      if (type === 'number') { el.min = key.includes('size') ? 1 : 0; el.step = 1; }
      if (type === 'checkbox') el.checked = initial; else el.value = initial;
      el.addEventListener('input', () => {
        humanDrafts.set(key, humanValue(key, type, scale));
        humanPending.delete(key);
        humanPreview();
      });
      row.appendChild(el);
      container.appendChild(row);
    });
  }
  const awaitingConfirmation = humanPending.size > 0;
  HUMAN_SETTINGS.forEach(([key, , type, , scale = 1]) => {
    const value = snap.config[key];
    if (value === undefined) return;
    if (humanPending.has(key) && humanPending.get(key) === value) {
      humanPending.delete(key); humanDrafts.delete(key);
    }
    if (humanDrafts.has(key)) return;
    const el = document.getElementById('hp-' + key);
    if (document.activeElement === el) return;
    if (type === 'checkbox') el.checked = value; else el.value = type === 'number' ? value / scale : value;
  });
  if (awaitingConfirmation && humanSubmissionComplete && humanPending.size === 0) {
    document.getElementById('human-settings-status').textContent = '✓ Настройки сохранены сервером';
  }
  humanPreview();
}

function humanPreview() {
  const hours = document.getElementById('hp-human_active_hours');
  if (!hours) return;
  const match = /^(\d{2})-(\d{2})$/.exec(hours.value.trim());
  const start = match ? Number(match[1]) : -1, end = match ? Number(match[2]) : -1;
  const valid = start >= 0 && start < 24 && end >= 0 && end <= 24 && start !== end;
  const config = State.lastSnapshot?.config || {};
  const hour = config.human_local_hour;
  const active = valid && hour !== undefined && (start < end ? hour >= start && hour < end : hour >= start || hour < end);
  const minimum = humanValue('human_apply_delay_min', 'number');
  const maximum = humanValue('human_apply_delay_max', 'number');
  const delaysValid = Number.isInteger(minimum) && Number.isInteger(maximum) && minimum >= 0 && minimum <= maximum;
  const target = Number(config.human_target_applies_per_hour) || 4;
  const interval = Math.max(3600 / target, minimum, maximum);
  const appliedToday = Math.max(0, Number(State.lastSnapshot?.global_stats?.applied_today) || 0);
  const week = config.captcha_llm_week || {};
  const enabled = document.getElementById('hp-human_mode_enabled').checked;
  document.getElementById('human-preview').textContent = !valid ? 'Некорректные часы: используйте HH-HH (например 07-24 или 22-06).' :
    !delaysValid ? 'Укажите обе задержки: неотрицательные целые числа, минимум не больше максимума.' :
    `Целевой темп: ~${target.toFixed(1)} applies/час (~${Math.round(target * 17)} в день) на аккаунт. Текущий час активен: ${hour === undefined ? 'нет данных' : active ? 'да' : 'нет'} (МСК: ${hour ?? '—'} ч); ${enabled ? 'одна попытка не чаще чем раз в ' + (interval / 60).toFixed(1) + ' мин; интервал сохраняется после перезапуска.' : 'режим выключен'}. Отклики сегодня: ${appliedToday}. Капчи за 7 дней: ${week.challenges || 0}, из них решено автоматически: ${week.llm_solved || 0}.`;
}

function applyHumanSettings() {
  const values = Object.fromEntries(HUMAN_SETTINGS.map(([key, , type, , scale = 1]) => [key, humanValue(key, type, scale)]));
  const status = document.getElementById('human-settings-status');
  if (!State.ws || State.ws.readyState !== 1) {
    status.textContent = 'Нет связи с панелью. Настройки не отправлены; черновик сохранён в полях.';
    return;
  }
  const match = /^(\d{2})-(\d{2})$/.exec(values.human_active_hours);
  if (!match || +match[1] > 23 || +match[2] > 24 || +match[1] === +match[2]) { status.textContent = 'Проверьте активные часы'; return; }
  for (const [key, , type] of HUMAN_SETTINGS) {
    if (type === 'number' && (!Number.isInteger(values[key]) || values[key] < 0)) { status.textContent = 'Введите неотрицательные целые значения задержки'; return; }
  }
  for (const [low, high] of [['human_apply_delay_min', 'human_apply_delay_max']]) {
    if (values[low] > values[high]) { status.textContent = 'Минимум не должен превышать максимум'; return; }
  }
  humanSubmissionComplete = false;
  for (const [key, value] of Object.entries(values)) {
    humanDrafts.set(key, value);
    if (!sendCmd({type: 'set_config', key, value})) {
      status.textContent = 'Связь прервалась: не все настройки отправлены. Черновик сохранён; проверьте значения после подключения.';
      return;
    }
    humanPending.set(key, value);
  }
  humanSubmissionComplete = true;
  status.textContent = 'Настройки отправлены — ожидаю подтверждения сервера';
}

function syncSettingsSliders(snap) {
  if (!snap.config) return;
  syncHumanSettings(snap);
  SETTINGS_DEF.forEach(s => {
    const el = document.getElementById('sr-' + s.key);
    const sv = document.getElementById('sv-' + s.key);
    if (el && snap.config[s.key] !== undefined) {
      if (State.settingsDrafts.has(s.key)) {
        const draft = State.settingsDrafts.get(s.key);
        if (Number(snap.config[s.key]) !== draft) return;
        // Backend подтвердил применённое значение; снова синхронизируем с ним.
        State.settingsDrafts.delete(s.key);
      }
      el.value = snap.config[s.key];
      if (sv) sv.textContent = snap.config[s.key];
    }
  });
}

// ── Helpers ──────────────────────────────────────────────────
async function diagFetch() {
  const st = document.getElementById('diag-status');
  const ta = document.getElementById('diag-textarea');
  if (st) st.textContent = '⏳ читаю…';
  const r = await fetch('/api/diagnostic_bundle');
  const txt = await r.text();
  if (ta) ta.value = txt;
  if (st) st.textContent = `${(txt.length/1024).toFixed(1)} KB готово`;
  return txt;
}

async function diagCopy(btn) {
  try {
    const txt = await diagFetch();
    await navigator.clipboard.writeText(txt);
    const st = document.getElementById('diag-status');
    if (st) st.textContent = '✅ скопировано в буфер';
    if (btn) { const old = btn.textContent; btn.textContent = '✅ Скопировано'; setTimeout(()=>btn.textContent=old, 2000); }
  } catch (e) {
    const st = document.getElementById('diag-status');
    if (st) st.textContent = '⚠️ буфер недоступен — выдели текст ниже и Ctrl+C';
  }
}

async function diagDownload(btn) {
  const txt = await diagFetch();
  const blob = new Blob([txt], {type: 'text/plain;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const stamp = new Date().toISOString().replace(/[:.]/g,'-').slice(0,19);
  a.href = url;
  a.download = `hh-bot-diag-${stamp}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/`/g, '&#96;');
}

// Safe href: блокирует javascript:/data:/vbscript: URL — esc() не защищает от них,
// потому что HTML-entity escape не меняет схему (kimi-search-3 #7).
function safeHref(url) {
  if (!url) return '#';
  let s = String(url).trim();
  // Decode percent-encoded префикс: `j%61vascript:` → `javascript:` (kimi-r13-4 #5).
  // Декодируем до стабилизации (4+ вложенных %25 обходили предел 3, kimi-r14-1 #6).
  // Hard cap 10 — защита от пат. входов; 10 достаточно для любого реального URL.
  for (let i = 0; i < 10; i++) {
    try {
      const dec = decodeURIComponent(s);
      if (dec === s) break;
      s = dec;
    } catch (_) { break; }
  }
  if (/^\s*(javascript|data|vbscript|file):/i.test(s)) return '#';
  // Whitelist: только http(s) и хеши/относительные пути.
  if (/^[a-z][a-z0-9+.-]*:/i.test(s) && !/^https?:/i.test(s)) return '#';
  return s;
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function colorVar(color) {
  const map = {
    cyan: 'var(--cyan)',
    magenta: 'var(--magenta)',
    green: 'var(--green)',
    yellow: 'var(--yellow)',
    red: 'var(--red)',
    blue: 'var(--blue)',
  };
  return map[color] || 'var(--text)';
}

// ── Session mode toggle ───────────────────────────────────────
let _sessMode = 'curl';
function sessSetMode(mode) {
  _sessMode = mode;
  const panelCurl = document.getElementById('sess-panel-curl');
  const panelManual = document.getElementById('sess-panel-manual');
  if (panelCurl) panelCurl.style.display = mode === 'curl' ? '' : 'none';
  if (panelManual) panelManual.style.display = mode === 'manual' ? '' : 'none';
  const btnCurl = document.getElementById('sess-mode-curl');
  const btnManual = document.getElementById('sess-mode-manual');
  if (btnCurl) { btnCurl.style.background = mode === 'curl' ? 'var(--cyan)' : 'transparent'; btnCurl.style.color = mode === 'curl' ? '#000' : 'var(--dim)'; }
  if (btnManual) { btnManual.style.background = mode === 'manual' ? 'var(--cyan)' : 'transparent'; btnManual.style.color = mode === 'manual' ? '#000' : 'var(--dim)'; }
}

// ── Session Add ───────────────────────────────────────────────
async function sessionAdd() {
  const nameEl   = document.getElementById('session-name');
  const letterEl = document.getElementById('session-letter');
  const st       = document.getElementById('session-status');
  let cookieStr = '';

  if (_sessMode === 'manual') {
    const hhtoken   = document.getElementById('ck-hhtoken')?.value.trim();
    const xsrf      = document.getElementById('ck-xsrf')?.value.trim();
    const hhul      = document.getElementById('ck-hhul')?.value.trim();
    const cryptedId = document.getElementById('ck-crypted-id')?.value.trim();
    if (!hhtoken) { st.textContent = '❌ hhtoken обязателен'; st.style.color = 'var(--red)'; return; }
    if (!xsrf)    { st.textContent = '❌ _xsrf обязателен';   st.style.color = 'var(--red)'; return; }
    const parts = [`hhtoken=${hhtoken}`, `_xsrf=${xsrf}`];
    if (hhul)      parts.push(`hhul=${hhul}`);
    if (cryptedId) parts.push(`crypted_id=${cryptedId}`);
    cookieStr = parts.join('; ');
  } else {
    const ta = document.getElementById('session-cookies');
    cookieStr = ta?.value.trim();
    if (!cookieStr) { st.textContent = '❌ Вставьте строку cookies'; st.style.color = 'var(--red)'; return; }
  }

  await _doSessionAdd(cookieStr, nameEl, letterEl, st, false);
}

async function _doSessionAdd(cookieStr, nameEl, letterEl, st, force) {
  st.textContent = force ? '⏳ Добавляю без проверки...' : '⏳ Проверяю сессию...';
  st.style.color = 'var(--dim)';
  try {
    const res = await fetch('/api/session/add', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        cookies: cookieStr,
        name: nameEl?.value.trim() || '',
        letter: letterEl?.value || '',
        force: !!force,
      })
    });
    const data = await res.json();
    if (data.status === 'ok') {
      st.textContent = '✅ ' + data.message;
      st.style.color = 'var(--green)';
      const ta = document.getElementById('session-cookies');
      if (ta) ta.value = '';
      ['ck-hhtoken','ck-xsrf','ck-hhul','ck-crypted-id'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
      });
      if (nameEl)   nameEl.value = '';
      if (letterEl) letterEl.value = '';
    } else {
      // HH вернул 401/403 — DDoS-Guard или anti-bot. Предлагаем добавить без проверки.
      if (data.can_force && !force) {
        st.innerHTML = '';
        const msg = document.createElement('span');
        msg.textContent = '⚠️ ' + data.message + ' ';
        msg.style.color = 'var(--yellow)';
        const btn = document.createElement('button');
        btn.className = 'btn-sm';
        btn.textContent = 'Добавить всё равно';
        btn.style.marginLeft = '8px';
        btn.onclick = () => _doSessionAdd(cookieStr, nameEl, letterEl, st, true);
        st.appendChild(msg);
        st.appendChild(btn);
      } else {
        st.textContent = '❌ ' + data.message;
        st.style.color = 'var(--red)';
      }
    }
  } catch(e) {
    st.textContent = '❌ ' + e; st.style.color = 'var(--red)';
  }
}


async function sessionChangeResume(idx, hash) {
  await fetch('/api/session/' + idx, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume_hash: hash })
  });
  // Обновляем ссылку на резюме в карточке без перерисовки
  const card = document.getElementById('sess-card-' + idx);
  if (card) {
    const link = card.querySelector('a[href*="/resume/"]');
    if (link) link.href = 'https://hh.ru/resume/' + hash;
  }
}

async function sessionSaveLetter(idx) {
  const ta = document.getElementById('sess-letter-' + idx);
  const st = document.getElementById('sess-letter-st-' + idx);
  if (!ta || !st) return;
  st.textContent = '⏳'; st.style.color = 'var(--dim)';
  try {
    const res = await fetch('/api/session/' + idx, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({letter: ta.value})
    });
    const data = await res.json();
    if (data.status === 'ok') {
      st.textContent = '✅ Сохранено'; st.style.color = 'var(--green)';
      // Обновить ApplyLetters чтобы шаблон в дропдауне тоже обновился
      ApplyLetters[idx] = ta.value;
      setTimeout(() => { st.textContent = ''; }, 2000);
    } else {
      st.textContent = '❌ ' + data.message; st.style.color = 'var(--red)';
    }
  } catch(e) {
    st.textContent = '❌ ' + e; st.style.color = 'var(--red)';
  }
}

async function sessionRemove(idx) {
  if (!await showConfirm(t('confirm_del_sess'))) return;
  const res = await fetch('/api/session/' + idx, {method: 'DELETE'});
  const data = await res.json().catch(() => ({}));
  if (res.ok && data.status === 'ok') removeAccountFromCurrentSnapshot(idx);
  else alert('Ошибка: ' + (data.message || data.error || `HTTP ${res.status}`));
}

async function sessionRefresh(idx) {
  const res = await fetch('/api/session/' + idx + '/refresh', {method: 'POST'});
  const data = await res.json();
  // snapshot will update via WS
}

async function sessionActivate(idx, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Запуск…'; }
  try {
    const res = await fetch('/api/session/' + idx + '/activate', {method: 'POST'});
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) {}
    if (!res.ok || data.status !== 'ok') {
      const reason = data.message || data.error || data.detail || text || `HTTP ${res.status}`;
      alert('Ошибка: ' + reason);
      if (btn) { btn.disabled = false; btn.textContent = '▶ Запустить'; }
      return;
    }
    setSessionActiveInCurrentSnapshot(idx, true);
    // Snapshot will redraw the card. Keep the button disabled meanwhile to
    // prevent a second activation request racing the first one.
  } catch (e) {
    alert('Сетевая ошибка: ' + (e?.message || String(e)));
    if (btn) { btn.disabled = false; btn.textContent = '▶ Запустить'; }
  }
}

async function sessionDeactivate(idx, btn) {
  if (!confirm('Остановить бот для этой сессии? Cookies и письмо сохранятся, можно запустить снова.')) return;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Стоп…'; }
  try {
    const res = await fetch('/api/session/' + idx + '/deactivate', {method: 'POST'});
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) {}
    if (!res.ok || data.status !== 'ok') {
      alert('Ошибка: ' + (data.message || data.error || data.detail || text || `HTTP ${res.status}`));
      if (btn) { btn.disabled = false; btn.textContent = '🛑 Стоп'; }
      return;
    }
    setSessionActiveInCurrentSnapshot(idx, false);
  } catch (e) {
    alert('Сетевая ошибка: ' + e);
    if (btn) { btn.disabled = false; btn.textContent = '🛑 Стоп'; }
  }
}

function setSessionActiveInCurrentSnapshot(idx, active) {
  const snap = State.lastSnapshot;
  if (!snap || !Array.isArray(snap.accounts)) return;
  const acc = snap.accounts.find(a => Number(a.idx) === Number(idx));
  if (!acc || !acc.temp) return;
  acc.bot_active = Boolean(active);
  if (!active) {
    acc.paused = false;
    acc.status = '—';
    acc.status_detail = '';
  }
  renderAll(snap);
}

// ── Apply Tab ────────────────────────────────────────────────
const ApplyState = { checking: false, submitting: false, vid: '', accIdx: 0, questions: [] };

const ApplyLetters = {};

function applyBuildAccountSelect(snap) {
  const sel = document.getElementById('apply-account');
  const tpl = document.getElementById('apply-letter-tpl');
  if (!sel || !snap) return;

  (snap.accounts || []).forEach(a => { ApplyLetters[a.idx] = a.letter || ''; });

  // пересоздаём только если изменился состав аккаунтов
  const newKey = (snap.accounts || []).map(a => a.idx + ':' + a.name).join(',');
  if (sel.dataset.builtKey !== newKey) {
    sel.dataset.builtKey = newKey;
    const prev = sel.value;
    sel.innerHTML = (snap.accounts || []).map(a =>
      `<option value="${a.idx}">${esc(a.name)}</option>`
    ).join('');
    if (prev) sel.value = prev;
  }

  // Rebuild template dropdown: one option per account letter
  if (tpl) {
    const newTplKey = newKey;
    if (tpl.dataset.builtKey !== newTplKey) {
      tpl.dataset.builtKey = newTplKey;
      const prevTpl = tpl.value;
      tpl.innerHTML = `<option value="">— выбрать шаблон —</option>` +
        (snap.accounts || []).map(a =>
          `<option value="${a.idx}">${esc(a.name)}</option>`
        ).join('');
      if (prevTpl) tpl.value = prevTpl;
    }
  }

  // Fill letter textarea if it's empty or still contains a default letter
  const ta = document.getElementById('apply-letter');
  if (ta && (!ta.value || Object.values(ApplyLetters).includes(ta.value))) {
    ta.value = ApplyLetters[parseInt(sel.value) || 0] || '';
  }
}

function applyFillLetter(idx) {
  const ta = document.getElementById('apply-letter');
  if (ta) ta.value = ApplyLetters[parseInt(idx)] || '';
  // Sync template selector to the chosen account
  const tpl = document.getElementById('apply-letter-tpl');
  if (tpl) tpl.value = idx;
}

function applyPickTemplate(idx) {
  if (!idx) return;
  const ta = document.getElementById('apply-letter');
  if (ta && ApplyLetters[parseInt(idx)] !== undefined)
    ta.value = ApplyLetters[parseInt(idx)];
}

function applyShowResult(msg, type) {
  const el = document.getElementById('apply-result');
  if (!el) return;
  el.style.display = '';
  el.className = 'apply-result ' + type;
  // Messages can contain raw HH response text or exception strings.
  // Treat them as text so a remote error cannot inject dashboard markup.
  el.textContent = msg;
}

function applyHideQuestionnaire() {
  const el = document.getElementById('apply-questionnaire');
  if (el) { el.style.display = 'none'; el.innerHTML = ''; }
}

async function applyCheck() {
  if (ApplyState.checking) return;
  const accSel = document.getElementById('apply-account');
  if (!accSel || !accSel.options.length) { applyShowResult('Сначала добавьте аккаунт', 'err'); return; }
  const accIdx = parseInt(accSel.value);
  if (isNaN(accIdx)) { applyShowResult('Сначала добавьте аккаунт', 'err'); return; }
  const raw = document.getElementById('apply-vacancy').value.trim();
  if (!raw) { applyShowResult('Введите ссылку или ID вакансии', 'err'); return; }

  ApplyState.checking = true;
  ApplyState.accIdx = accIdx;
  applyHideQuestionnaire();
  applyShowResult('⏳ Проверяю вакансию...', 'info');

  try {
    const letter = document.getElementById('apply-letter')?.value || '';
    const res = await fetch('/api/apply/check', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({account_idx: accIdx, vacancy_id: raw, letter})
    });
    const data = await res.json();
    ApplyState.vid = data.vacancy_id || raw;

    if (data.status === 'sent') {
      applyShowResult(`✅ ${data.message}`, 'ok');
      applyHideQuestionnaire();
    } else if (data.status === 'already') {
      applyShowResult(`🔄 ${data.message}`, 'warn');
    } else if (data.status === 'limit') {
      applyShowResult(`🚫 ${data.message}`, 'err');
    } else if (data.status === 'unknown' || data.status === 'cancelled') {
      applyShowResult(`⚠️ ${data.message}`, 'warn');
      applyHideQuestionnaire();
    } else if (data.status === 'test_required') {
      ApplyState.questions = data.questions || [];
      applyShowResult(
        `📝 ${data.message}\nПроверьте ответы ниже и нажмите «Откликнуться»`,
        'info'
      );
      applyRenderQuestionnaire(data);
    } else {
      applyShowResult(`❌ ${data.message || 'Неизвестная ошибка'}`, 'err');
    }
  } catch(e) {
    applyShowResult('❌ Ошибка запроса: ' + e, 'err');
  } finally {
    ApplyState.checking = false;
  }
}

function applyRenderQuestionnaire(data) {
  const el = document.getElementById('apply-questionnaire');
  if (!el) return;
  el.style.display = '';
  const qs = data.questions || [];

  let html = `
    <hr class="apply-divider">
    <div style="font-size:13px;font-weight:700;margin-bottom:12px">
      📋 Опросник — ${qs.length} вопросов
    </div>

    <div class="apply-q-list">
  `;

  qs.forEach((q, i) => {
    html += `<div class="apply-q-item">
      <div class="apply-q-num">Вопрос ${i+1} из ${qs.length}</div>
      <div class="apply-q-text">${esc(q.text)}</div>
    `;

    // q.field — scraped from HH HTML, может быть атакером. esc() для атрибутов.
    const fieldAttr = esc(q.field);
    if (q.type === 'radio') {
      html += `<div class="apply-radio-opts">`;
      q.options.forEach(opt => {
        const checked = opt.value === q.suggested ? 'checked' : '';
        html += `<label class="apply-radio-opt">
          <input type="radio" name="aq_${fieldAttr}" value="${esc(opt.value)}" ${checked}>
          ${esc(opt.label)}
        </label>`;
      });
      html += `</div>`;
    } else if (q.type === 'checkbox') {
      const suggested = Array.isArray(q.suggested) ? q.suggested : [q.suggested];
      html += `<div class="apply-radio-opts">`;
      q.options.forEach(opt => {
        const checked = suggested.includes(opt.value) ? 'checked' : '';
        html += `<label class="apply-radio-opt">
          <input type="checkbox" name="aq_${fieldAttr}" value="${esc(opt.value)}" ${checked}>
          ${esc(opt.label)}
        </label>`;
      });
      html += `</div>`;
    } else if (q.type === 'select') {
      html += `<select class="apply-q-answer" id="aq_${fieldAttr}">`;
      q.options.forEach(opt => {
        const selected = opt.value === q.suggested ? 'selected' : '';
        html += `<option value="${esc(opt.value)}" ${selected}>${esc(opt.label)}</option>`;
      });
      html += `</select>`;
    } else if (q.type === 'textarea') {
      html += `<textarea class="apply-q-answer" id="aq_${fieldAttr}" rows="3">${esc(q.suggested)}</textarea>`;
    }
    html += `</div>`;
  });

  html += `</div>
    <div class="apply-btn-row" style="margin-top:16px">
      <button class="apply-btn" onclick="applySubmit()">🚀 Откликнуться</button>
      <button class="apply-btn-secondary" onclick="applyHideQuestionnaire();applyShowResult('','');document.getElementById('apply-result').style.display='none'">Отмена</button>
      <span id="apply-submit-status" style="font-size:12px;color:var(--dim)"></span>
    </div>
  `;

  el.innerHTML = html;
}

async function applySubmit() {
  if (ApplyState.submitting) return;
  if (isNaN(ApplyState.accIdx)) {
    applyShowResult('Сначала добавьте аккаунт', 'err');
    return;
  }
  ApplyState.submitting = true;
  const statusEl = document.getElementById('apply-submit-status');
  if (statusEl) statusEl.textContent = '⏳ Отправляю...';

  // Собираем ответы
  const answers = {};
  ApplyState.questions.forEach(q => {
    if (q.type === 'radio') {
      const checked = document.querySelector(`input[name="aq_${q.field}"]:checked`);
      if (checked) answers[q.field] = checked.value;
    } else if (q.type === 'checkbox') {
      answers[q.field] = Array.from(
        document.querySelectorAll(`input[name="aq_${q.field}"]:checked`)
      ).map(input => input.value);
    } else if (q.type === 'select') {
      const select = document.getElementById('aq_' + q.field);
      if (select) answers[q.field] = select.value;
    } else if (q.type === 'textarea') {
      const ta = document.getElementById('aq_' + q.field);
      if (ta) answers[q.field] = ta.value;
    }
  });

  const letter = document.getElementById('apply-letter')?.value || '';

  try {
    const res = await fetch('/api/apply/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({account_idx: ApplyState.accIdx, vacancy_id: ApplyState.vid, letter, answers})
    });
    const data = await res.json();

    if (data.status === 'sent') {
      applyShowResult(`✅ ${data.message}`, 'ok');
      applyHideQuestionnaire();
    } else if (data.status === 'limit') {
      applyShowResult(`🚫 ${data.message}`, 'err');
    } else if (data.status === 'unknown' || data.status === 'cancelled') {
      applyShowResult(`⚠️ ${data.message}`, 'warn');
      applyHideQuestionnaire();
    } else {
      applyShowResult(`❌ ${data.message}`, 'err');
    }
  } catch(e) {
    applyShowResult('❌ Ошибка: ' + e, 'err');
  } finally {
    // Спиннер чистим всегда — иначе network error оставлял "⏳ Отправляю..." навсегда.
    if (statusEl) statusEl.textContent = '';
    ApplyState.submitting = false;
  }
}

// ── Resume Views Tab ────────────────────────────────────────
let _loadViewsLastTs = 0;
async function loadViews() {
  const now = Date.now();
  if (now - _loadViewsLastTs < 30000) return;
  _loadViewsLastTs = now;
  const statsRow = document.getElementById('views-stats-row');
  const accsEl = document.getElementById('views-accounts');
  if (!statsRow || !accsEl) return;

  const snap = State.lastSnapshot;
  if (!snap) return;

  // Aggregate header stats
  let totalViews = 0, totalViewsNew = 0, totalShows = 0, totalInv = 0, totalInvNew = 0;
  (snap.accounts || []).forEach(a => {
    totalViews += a.resume_views_7d || 0;
    totalViewsNew += a.resume_views_new || 0;
    totalShows += a.resume_shows_7d || 0;
    totalInv += a.resume_invitations_7d || 0;
    totalInvNew += a.resume_invitations_new || 0;
  });

  statsRow.innerHTML = `
    <div class="views-stat-card"><div class="views-stat-val c-cyan">${totalViews}</div><div class="views-stat-lbl">${t('views_7d')}</div></div>
    <div class="views-stat-card"><div class="views-stat-val c-green">+${totalViewsNew}</div><div class="views-stat-lbl">${t('views_new')}</div></div>
    <div class="views-stat-card"><div class="views-stat-val" style="color:var(--dim)">${totalShows}</div><div class="views-stat-lbl">${t('views_shows')}</div></div>
    <div class="views-stat-card"><div class="views-stat-val c-magenta">${totalInv}</div><div class="views-stat-lbl">${t('views_invitations')}</div></div>
    <div class="views-stat-card"><div class="views-stat-val c-green">+${totalInvNew}</div><div class="views-stat-lbl">${t('views_inv_new')}</div></div>
  `;

  // Per-account blocks
  const existingIds = new Set([...accsEl.querySelectorAll('.views-acc-block')].map(el => el.dataset.idx));
  const snapIds = new Set((snap.accounts || []).map(a => String(a.idx)));
  const needRebuild = [...snapIds].some(id => !existingIds.has(id)) || [...existingIds].some(id => !snapIds.has(id));

  if (needRebuild) {
    accsEl.innerHTML = '';
    for (const acc of (snap.accounts || [])) {
      const block = document.createElement('div');
      block.className = 'views-acc-block';
      block.dataset.idx = String(acc.idx);
      const colorStyle = `color:${colorVar(acc.color)}`;
      block.innerHTML = `
        <div class="views-acc-title">
          <span style="${colorStyle}">${esc(acc.name)}</span>
          <button class="btn-refresh" onclick="loadViewHistory(${acc.idx})">${t('btn_load_history')}</button>
          <button class="btn-sm" onclick="declineDiscards(${acc.idx},this)">🗑️ Очистить дискарды</button>
        </div>
        <div id="views-hist-${acc.idx}"><div class="c-dim" style="font-size:12px;padding:8px 0">⏳ Загружаю...</div></div>
      `;
      accsEl.appendChild(block);
      loadViewHistory(acc.idx);
    }
  } else {
    // повторяем загрузку для тех у кого ещё нет данных и не помечено как loaded
    for (const acc of (snap.accounts || [])) {
      const histEl = document.getElementById('views-hist-' + acc.idx);
      if (histEl && !histEl.dataset.loaded && !histEl.dataset.loading) {
        histEl.dataset.loading = '1';
        loadViewHistory(acc.idx).finally(() => { histEl.removeAttribute('data-loading'); });
      }
    }
  }
}

// ── Resume Audit ─────────────────────────────────────────────
function syncAuditSelector(snap) {
  const sel = document.getElementById('audit-acc-sel');
  if (!sel) return;
  const accs = snap?.accounts || [];
  if (!accs.length) return;
  // Перестраиваем при изменении состава (а не один раз) — иначе после add/delete
  // аккаунта список залипает на старом наборе.
  const key = accs.map(a => a.idx + ':' + (a.name || a.short || '')).join('|');
  if (sel.dataset.key === key) return;
  sel.dataset.key = key;
  const prev = sel.value;
  sel.innerHTML = accs.map(a => `<option value="${a.idx}">${esc(a.name || a.short || '')}</option>`).join('');
  if (prev) sel.value = prev;
}

async function runResumeAudit(btn) {
  const sel = document.getElementById('audit-acc-sel');
  const st = document.getElementById('audit-status');
  const res = document.getElementById('audit-result');
  if (!sel || !res) return;
  const idx = sel.value;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Анализирую...'; st.style.color = 'var(--dim)'; }
  res.style.display = 'none';
  try {
    const extraTerms = (document.getElementById('audit-extra-terms')?.value || '').trim();
    const qs = extraTerms ? `?extra_terms=${encodeURIComponent(extraTerms)}` : '';
    const r = await fetch(`/api/account/${idx}/resume_audit${qs}`);
    const data = await r.json();
    if (data.error) {
      if (st) { st.textContent = '❌ ' + data.error; st.style.color = 'var(--red)'; }
      return;
    }
    if (st) st.textContent = '';
    res.style.display = '';
    res.innerHTML = renderAuditResult(data);
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderAuditResult(d) {
  const levelIcon = {critical: '🔴', high: '🟠', medium: '🟡', low: '🔵', info: 'ℹ️'};
  const levelOrder = {critical: 0, high: 1, medium: 2, low: 3, info: 4};
  const issues = (d.issues || []).sort((a, b) => (levelOrder[a.level] ?? 5) - (levelOrder[b.level] ?? 5));

  const expYears = Math.floor((d.total_experience_months || 0) / 12);
  const expMonths = (d.total_experience_months || 0) % 12;
  const expStr = expYears ? `${expYears} г. ${expMonths ? expMonths + ' м.' : ''}` : `${expMonths} м.`;

  const statusColors = {
    'not_looking_for_job': 'var(--red)',
    'looking_for_offers': 'var(--yellow)',
    'actively_searching': 'var(--green)',
  };
  const statusColor = statusColors[d.job_search_status] || 'var(--dim)';

  const pctColor = (d.percent || 0) >= 80 ? 'var(--green)' : (d.percent || 0) >= 60 ? 'var(--yellow)' : 'var(--red)';

  let html = `
    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:12px">
      <div style="font-size:14px;font-weight:700;margin-bottom:8px">${esc(d.name || '?')}</div>
      <div style="font-size:12px;color:var(--dim);margin-bottom:12px">${esc(d.title || '')}</div>

      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;margin-bottom:14px">
        <div class="audit-card">
          <div class="audit-label">${t('audit_search_status')}</div>
          <div style="color:${statusColor};font-weight:600">${esc(d.job_search_status_label || '?')}</div>
        </div>
        <div class="audit-card">
          <div class="audit-label">${t('audit_filled')}</div>
          <div style="color:${pctColor};font-weight:600">${d.percent || 0}%</div>
        </div>
        <div class="audit-card">
          <div class="audit-label">${t('audit_exp')}</div>
          <div>${expStr}</div>
        </div>
        <div class="audit-card">
          <div class="audit-label">${t('audit_salary')}</div>
          <div>${d.salary ? d.salary + ' ₽' : '<span style="color:var(--red)">не указана</span>'}</div>
        </div>
        <div class="audit-card">
          <div class="audit-label">${t('audit_photo')}</div>
          <div>${d.has_photo ? '<span style="color:var(--green)">Есть</span>' : '<span style="color:var(--red)">Нет</span>'}</div>
        </div>
        <div class="audit-card">
          <div class="audit-label">${t('audit_resume_status')}</div>
          <div style="color:${d.status === 'published' ? 'var(--green)' : 'var(--red)'}">${esc(d.status || '?')}</div>
        </div>
      </div>

      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px;font-size:12px">
        <div><span style="color:var(--dim)">${t('audit_format')}</span> ${(d.work_formats || []).map(esc).join(', ') || '—'}</div>
        <div><span style="color:var(--dim)">${t('audit_schedule')}</span> ${(d.work_schedule || []).map(esc).join(', ') || '—'}</div>
        <div><span style="color:var(--dim)">${t('audit_employment')}</span> ${(d.employment || []).map(esc).join(', ') || '—'}</div>
        <div><span style="color:var(--dim)">${t('audit_roles')}</span> ${(d.roles || []).map(r => esc(r)).join(', ') || '—'}</div>
      </div>

      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px;font-size:12px">
        <div>🔍 <b>${d.stats_7d?.search_shows ?? 0}</b> показов/7д</div>
        <div>👁️ <b>${d.stats_7d?.views ?? 0}</b> просмотров <span class="c-green">+${d.stats_7d?.views_new ?? 0}</span></div>
        <div>💌 <b>${d.stats_7d?.invitations ?? 0}</b> приглашений <span class="c-green">+${d.stats_7d?.invitations_new ?? 0}</span></div>
      </div>

      <div style="font-size:12px;color:var(--dim);margin-bottom:6px">Навыки: <span style="color:var(--text)">${(d.skills || []).slice(0, 15).map(s => esc(s)).join(', ')}</span></div>
    </div>`;

  if (issues.length) {
    html += `<div style="font-size:13px;font-weight:700;margin-bottom:8px">${t('audit_recommendations')} (${issues.length})</div>`;
    html += issues.map(iss => `
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:10px 12px;margin-bottom:6px;display:flex;gap:8px;align-items:flex-start">
        <div style="flex-shrink:0;font-size:14px">${levelIcon[iss.level] || '❓'}</div>
        <div>
          <div style="font-size:12px">${esc(iss.text)}</div>
          ${iss.fix ? `<div style="font-size:11px;color:var(--cyan);margin-top:3px">💡 ${esc(iss.fix)}</div>` : ''}
        </div>
      </div>
    `).join('');
  } else {
    html += '<div style="color:var(--green);font-size:13px">✅ ' + t('audit_no_issues') + '</div>';
  }

  // Market analytics
  const m = d.market;
  if (m && (m.vacancy_count || m.active_seekers)) {
    const ratioColor = m.supply_demand_ratio > 5 ? 'var(--red)' : m.supply_demand_ratio > 2 ? 'var(--yellow)' : 'var(--green)';
    html += `
      <div style="font-size:13px;font-weight:700;margin-top:16px;margin-bottom:8px">${t('audit_market_analysis')}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;margin-bottom:14px">
        <div class="audit-card">
          <div class="audit-label">Вакансий</div>
          <div style="font-weight:600;color:var(--cyan)">${(m.vacancy_count || 0).toLocaleString()}</div>
        </div>
        <div class="audit-card">
          <div class="audit-label">Активных соискателей</div>
          <div style="font-weight:600;color:var(--yellow)">${(m.active_seekers || 0).toLocaleString()}</div>
        </div>
        <div class="audit-card">
          <div class="audit-label">Конкуренция (чел/вак)</div>
          <div style="font-weight:600;color:${ratioColor}">${m.supply_demand_ratio || '—'}</div>
        </div>
      </div>`;

    // Experience distribution
    if (m.experience_distribution && m.experience_distribution.length) {
      html += `<div style="font-size:12px;color:var(--dim);margin-bottom:6px">Опыт конкурентов:</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">`;
      for (const ed of m.experience_distribution) {
        html += `<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:4px;padding:4px 8px;font-size:11px">
          ${esc(ed.name)} <span style="color:var(--cyan);font-weight:600">${(ed.count || 0).toLocaleString()}</span>
        </div>`;
      }
      html += '</div>';
    }

    // Top skills from competitors: green if user has it, red if missing
    if (m.top_competitor_skills && m.top_competitor_skills.length) {
      const userSkills = new Set((d.skills || []).map(s => s.toLowerCase()));
      html += `<div style="font-size:12px;color:var(--dim);margin-bottom:6px">Топ навыки конкурентов:</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">`;
      for (const sk of m.top_competitor_skills) {
        const skName = typeof sk === 'string' ? sk : (sk.name || '');
        const skCount = typeof sk === 'object' ? (sk.count || '') : '';
        const has = userSkills.has(skName.toLowerCase());
        const skColor = has ? 'var(--green)' : 'var(--red)';
        const skBg = has ? 'rgba(0,255,0,0.08)' : 'rgba(255,0,0,0.08)';
        const countLabel = skCount ? ` (${(skCount/1000).toFixed(0)}K)` : '';
        html += `<span style="background:${skBg};color:${skColor};border:1px solid ${skColor};border-radius:4px;padding:2px 7px;font-size:11px">${esc(skName)}${countLabel}</span>`;
      }
      html += '</div>';
    }
  }

  // ── Weight analysis — exact recipe for 100% ──
  if (d.weight_analysis && d.weight_analysis.length) {
    const filled = d.filled_weight || 0;
    const total = d.total_weight || 1;
    const pct = Math.round(filled / total * 100);
    html += `<div style="font-size:13px;font-weight:700;margin:14px 0 8px">Заполненность резюме: ${filled}/${total} (${pct}%)</div>`;
    html += `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">`;
    for (const f of d.weight_analysis) {
      const color = f.filled ? 'var(--green)' : 'var(--red)';
      const bg = f.filled ? 'rgba(63,185,80,0.1)' : 'rgba(248,81,73,0.1)';
      const icon = f.filled ? '✅' : '❌';
      html += `<span style="background:${bg};color:${color};border:1px solid ${color};border-radius:4px;padding:2px 8px;font-size:11px" title="weight=${f.weight}, status=${f.status}">${icon} ${esc(f.label)} <b>×${f.weight}</b></span>`;
    }
    html += `</div>`;
    // How to reach 80%+
    const unfilled = d.weight_analysis.filter(f => !f.filled);
    if (unfilled.length && pct < 80) {
      const needed80 = Math.ceil(total * 0.8) - filled;
      html += `<div style="font-size:11px;color:var(--cyan);margin-bottom:12px">💡 Для 80%+ нужно ещё <b>${needed80}</b> веса. Самые ценные: ${unfilled.slice(0,4).map(f => `<b>${esc(f.label)}</b> (×${f.weight})`).join(', ')}</div>`;
    }
  }

  // ── Supply/demand comparison ──
  if (d.supply_demand_comparison && d.supply_demand_comparison.length) {
    html += `<div style="font-size:13px;font-weight:700;margin:14px 0 8px">Конкуренция по запросам</div>`;
    html += `<table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:12px">`;
    html += `<tr style="color:var(--dim);text-align:left"><th style="padding:4px 8px">Запрос</th><th style="padding:4px 8px">Вакансий</th><th style="padding:4px 8px">Конкуренция</th><th style="padding:4px 8px">Оценка</th></tr>`;
    for (const item of d.supply_demand_comparison) {
      const ratio = item.ratio || 0;
      const rColor = ratio > 30 ? 'var(--red)' : ratio > 15 ? 'var(--yellow)' : 'var(--green)';
      const label = ratio > 30 ? '🔴 высокая' : ratio > 15 ? '🟡 средняя' : ratio > 0 ? '🟢 низкая' : '—';
      html += `<tr style="border-top:1px solid var(--border)">
        <td style="padding:4px 8px">${esc(item.term)}</td>
        <td style="padding:4px 8px;font-weight:600">${item.vacancies || 0}</td>
        <td style="padding:4px 8px;color:${rColor};font-weight:600">${ratio ? ratio + ' чел/вак' : '—'}</td>
        <td style="padding:4px 8px">${label}</td>
      </tr>`;
    }
    html += `</table>`;
    // Best term recommendation
    const best = d.supply_demand_comparison.find(x => x.ratio > 0);
    if (best && d.supply_demand_comparison.length > 1) {
      const worst = d.supply_demand_comparison[d.supply_demand_comparison.length - 1];
      if (best.term !== worst.term && worst.ratio > best.ratio * 1.5) {
        html += `<div style="font-size:11px;color:var(--cyan);margin-bottom:8px">💡 Запрос «<b>${esc(best.term)}</b>» имеет наименьшую конкуренцию — оптимизируй заголовок резюме под него</div>`;
      }
    }
  }

  // HR Activity
  if (d.hr_activity) {
    const ha = d.hr_activity;
    const total = ha.active_count + ha.slow_count + ha.dead_count;
    if (total > 0) {
      html += `<div style="margin-top:14px;border-top:1px solid var(--border);padding-top:10px">
        <div style="font-size:13px;font-weight:700;margin-bottom:8px">👥 Активность HR-менеджеров</div>
        <div style="display:flex;gap:16px;font-size:12px">
          <div><span style="color:var(--green);font-weight:600">${ha.active_count}</span> <span style="color:var(--dim)">активных (&lt;3 дн.)</span></div>
          <div><span style="color:var(--yellow);font-weight:600">${ha.slow_count}</span> <span style="color:var(--dim)">медленных (3-7 дн.)</span></div>
          <div><span style="color:var(--red);font-weight:600">${ha.dead_count}</span> <span style="color:var(--dim)">неактивных (&gt;7 дн.)</span></div>
        </div>`;
      if (ha.dead_count > ha.active_count) {
        html += `<div style="font-size:11px;color:var(--yellow);margin-top:6px">⚠️ Много неактивных HR — часть откликов может не получить ответа</div>`;
      }
      html += `</div>`;
    }
  }

  return html;
}

// ── Hot Leads ────────────────────────────────────────────────
async function loadHotLeads(btn) {
  const sel = document.getElementById('audit-acc-sel');
  const st = document.getElementById('leads-status');
  const res = document.getElementById('leads-result');
  if (!sel || !res) return;
  const idx = sel.value;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Загружаю...'; st.style.color = 'var(--dim)'; }
  res.style.display = 'none';
  try {
    const r = await fetch(`/api/account/${idx}/hot_leads`);
    const data = await r.json();
    if (data.error) {
      if (st) { st.textContent = '❌ ' + data.error; st.style.color = 'var(--red)'; }
      return;
    }
    if (st) st.textContent = `${data.total || 0} работодателей`;
    res.style.display = '';
    const offers = data.offers || [];
    if (!offers.length) {
      res.innerHTML = '<div style="color:var(--dim);font-size:12px">Нет горячих лидов</div>';
      return;
    }
    res.innerHTML = `<div style="display:flex;flex-direction:column;gap:6px">${offers.map(o => {
      const vacs = (o.vacancies || []).slice(0, 2).map(v => esc(v)).join(', ');
      const invBadge = o.has_invitation ? '<span style="background:rgba(63,185,80,0.15);color:var(--green);padding:1px 6px;border-radius:3px;font-size:10px;margin-left:6px">приглашение</span>' : '';
      const link = o.vacancy_id ? `<a href="https://hh.ru/vacancy/${encodeURIComponent(o.vacancy_id)}" target="_blank" style="color:var(--cyan);font-size:11px;margin-left:6px">→ вакансия</a>` : '';
      return `<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:8px 12px">
        <div style="font-size:12px;font-weight:600">${esc(o.employer)}${invBadge}${link}</div>
        <div style="font-size:11px;color:var(--dim);margin-top:2px">${vacs}</div>
      </div>`;
    }).join('')}</div>`;
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── HR Contacts ─────────────────────────────────────────────
async function loadHrContacts(btn) {
  const st = document.getElementById('contacts-status');
  const res = document.getElementById('contacts-result');
  if (!res) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Загружаю...'; st.style.color = 'var(--dim)'; }
  res.style.display = 'none';
  try {
    const r = await fetch('/api/hr_contacts');
    const data = await r.json();
    if (st) st.textContent = `${data.total || 0} контактов`;
    res.style.display = '';
    const contacts = data.contacts || [];
    if (!contacts.length) {
      res.innerHTML = '<div style="color:var(--dim);font-size:12px">Нет собранных контактов. Контакты HR собираются автоматически при проверке вакансий (skip_inconsistent).</div>';
      return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:11px">';
    html += '<tr style="color:var(--dim);border-bottom:1px solid var(--border)"><th style="text-align:left;padding:4px 6px">Время</th><th style="text-align:left;padding:4px 6px">Вакансия</th><th style="text-align:left;padding:4px 6px">Компания</th><th style="text-align:left;padding:4px 6px">ФИО</th><th style="text-align:left;padding:4px 6px">Email</th><th style="text-align:left;padding:4px 6px">Телефон</th></tr>';
    contacts.slice().reverse().forEach(c => {
      const link = c.vacancy_id ? `<a href="https://hh.ru/vacancy/${encodeURIComponent(c.vacancy_id)}" target="_blank" style="color:var(--cyan)">${esc(c.title || c.vacancy_id)}</a>` : esc(c.title || '?');
      html += `<tr style="border-bottom:1px solid rgba(48,54,61,0.5)">
        <td style="padding:4px 6px;color:var(--dim);white-space:nowrap">${esc(c.time || '')}</td>
        <td style="padding:4px 6px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${link}</td>
        <td style="padding:4px 6px;color:var(--dim)">${esc(c.company || '')}</td>
        <td style="padding:4px 6px">${esc(c.fio || '')}</td>
        <td style="padding:4px 6px">${c.email ? `<a href="mailto:${esc(c.email)}" style="color:var(--cyan)">${esc(c.email)}</a>` : ''}</td>
        <td style="padding:4px 6px">${esc(c.phone || '')}</td>
      </tr>`;
    });
    html += '</table>';
    res.innerHTML = html;
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Remindable Negotiations ─────────────────────────────────
async function loadRemindable(btn) {
  const sel = document.getElementById('audit-acc-sel');
  const st = document.getElementById('remindable-status');
  const res = document.getElementById('remindable-result');
  if (!sel || !res) return;
  const idx = sel.value;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Проверяю...'; st.style.color = 'var(--dim)'; }
  res.style.display = 'none';
  try {
    const r = await fetch(`/api/account/${idx}/remindable`);
    const data = await r.json();
    if (data.error) {
      if (st) { st.textContent = '❌ ' + data.error; st.style.color = 'var(--red)'; }
      return;
    }
    if (st) st.textContent = `${data.total || 0} переговоров`;
    res.style.display = '';
    const items = data.remindable || [];
    if (!items.length) {
      res.innerHTML = '<div style="color:var(--dim);font-size:12px">Нет переговоров, где можно отправить напоминание.</div>';
      return;
    }
    res.innerHTML = `<div style="display:flex;flex-direction:column;gap:6px">${items.map(item => {
      return `<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:8px 12px">
        <div style="font-size:12px;font-weight:600">${esc(item.employer || '?')}</div>
        <div style="font-size:11px;color:var(--dim);margin-top:2px">${esc(item.vacancy || '')}</div>
      </div>`;
    }).join('')}</div>`;
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── OAuth API ────────────────────────────────────────────────
async function oauthGetToken(btn) {
  const sel = document.getElementById('audit-acc-sel');
  const st = document.getElementById('oauth-status');
  if (!sel) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Получаю токен...'; st.style.color = 'var(--dim)'; }
  try {
    const r = await fetch(`/api/account/${sel.value}/oauth_token`, {method: 'POST'});
    const d = await r.json();
    if (d.ok) {
      const hrs = Math.round(d.expires_in / 3600);
      if (st) { st.textContent = `✅ Токен получен | ${hrs}ч осталось | refresh: ${d.has_refresh ? 'да' : 'нет'}`; st.style.color = 'var(--green)'; }
    } else {
      if (st) { st.textContent = '❌ ' + (d.error || 'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function oauthTouch(btn) {
  const sel = document.getElementById('audit-acc-sel');
  const st = document.getElementById('oauth-status');
  if (!sel) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Поднимаю резюме...'; st.style.color = 'var(--dim)'; }
  try {
    const r = await fetch(`/api/account/${sel.value}/oauth_touch`, {method: 'POST'});
    const d = await r.json();
    if (d.ok) {
      if (st) { st.textContent = '✅ ' + d.message; st.style.color = 'var(--green)'; }
    } else {
      if (st) { st.textContent = '⚠️ ' + (d.message || d.error); st.style.color = 'var(--yellow)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Resume Cloning ───────────────────────────────────────────
async function loadAllResumes(btn) {
  const sel = document.getElementById('audit-acc-sel');
  const st = document.getElementById('resumes-status');
  const res = document.getElementById('resumes-result');
  if (!sel || !res) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  res.style.display = 'none';
  try {
    const r = await fetch(`/api/account/${sel.value}/all_resumes`);
    const data = await r.json();
    if (st) st.textContent = `${data.total || 0} резюме`;
    res.style.display = '';
    const items = data.resumes || [];
    if (!items.length) { res.innerHTML = '<div style="color:var(--dim);font-size:12px">Нет резюме</div>'; return; }
    res.innerHTML = items.map(r => {
      const STATUS_MAP = {
        'published': ['var(--green)', 'опубликовано'],
        'not_finished': ['var(--red)', 'не завершено'],
        'modified': ['var(--yellow)', 'изменено'],
        'auto_approved': ['var(--green)', 'опубликовано'],
        'blocked': ['var(--red)', 'заблокировано'],
      };
      const [statusColor, statusLabel] = STATUS_MAP[r.status] || ['var(--dim)', r.status || '—'];
      const pct = Number(r.percent) || 0;
      const pctColor = pct >= 80 ? 'var(--green)' : pct > 0 ? 'var(--yellow)' : 'var(--dim)';
      const pctStr = pct > 0 ? `${pct}%` : '';  // 0% не показываем (HH не отдаёт на странице списка)
      const statsInfo = (r.views_7d || r.shows_7d) ? `👁️${r.views_7d||0} · 🔍${r.shows_7d||0}` : '';
      const skills = r.skills_count || 0;
      const exp = r.experience_count;
      const expStr = exp == null ? '' : (exp === 0 ? 'без опыта' : `${exp} мест работы`);
      const contentInfo = [
        skills ? `${skills} навыков` : '',
        expStr,
      ].filter(Boolean).join(', ') || 'пусто';
      const parts = [
        `<span style="color:${statusColor}">${esc(statusLabel)}</span>`,
        pctStr ? `<span style="color:${pctColor}">${pctStr}</span>` : '',
        r.is_searchable ? '🔍 в поиске' : '🚫 скрыто',
        contentInfo,
        statsInfo,
      ].filter(Boolean).join(' · ');
      return `<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:10px 12px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;gap:12px">
        <div style="flex:1;min-width:0">
          <div style="font-size:12px;font-weight:600">${esc(r.title)}</div>
          <div style="font-size:11px;color:var(--dim);margin-top:2px">${parts}</div>
        </div>
        <div style="display:flex;gap:4px;flex-shrink:0">
          <a href="${safeHref(r.edit_url)}" target="_blank" rel="noopener noreferrer" class="btn-sm" style="font-size:11px">✏️ hh.ru</a>
          <button class="btn-sm" style="font-size:11px" onclick="quickEditResume('${esc(r.hash)}')">⚡ Быстро</button>
        </div>
      </div>`;
    }).join('');
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function cloneResume(btn) {
  const sel = document.getElementById('audit-acc-sel');
  const st = document.getElementById('resumes-status');
  if (!sel) return;
  const preset = document.getElementById('clone-preset')?.value || '';
  const custom = document.getElementById('clone-title')?.value.trim() || '';
  const title = custom || preset;
  if (!title) {
    if (!confirm('Клонировать без заголовка? Придётся задать вручную на hh.ru')) return;
  }
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Клонирую...'; st.style.color = 'var(--dim)'; }
  try {
    const r = await fetch(`/api/account/${sel.value}/clone_resume`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title})
    });
    const data = await r.json();
    if (data.ok) {
      const msg = data.title_set ? `✅ Склонировано: "${title}"` : '✅ Склонировано (заголовок задай на hh.ru)';
      if (st) { st.textContent = msg; st.style.color = 'var(--green)'; }
      // Refresh list
      setTimeout(() => loadAllResumes(), 500);
    } else {
      if (st) { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function quickEditResume(hash) {
  const sel = document.getElementById('audit-acc-sel');
  if (!sel) return;
  const idx = sel.value;
  const title = prompt('Заголовок резюме (должность):', '');
  if (title === null) return;
  const salary = prompt('Зарплата (₽, 0 = убрать):', '0');
  const skills = prompt('О себе (описание, пусто = не менять):', '');

  const body = {resume_hash: hash};
  if (title) body.title = title;
  if (salary && parseInt(salary) > 0) body.salary = parseInt(salary);
  if (skills) body.skills = skills;

  if (!Object.keys(body).some(k => k !== 'resume_hash')) {
    alert('Нечего менять'); return;
  }

  try {
    const r = await fetch(`/api/account/${idx}/edit_resume`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const data = await r.json();
    if (data.ok) {
      alert('✅ Резюме обновлено!');
      loadAllResumes();
    } else {
      alert('❌ ' + (data.error || 'Ошибка'));
    }
  } catch(e) {
    alert('❌ ' + e);
  }
}

async function loadViewHistory(idx) {
  const el = document.getElementById('views-hist-' + idx);
  if (!el) return;
  el.innerHTML = '<div class="c-dim" style="font-size:12px;padding:8px 0">⏳ Загружаю...</div>';
  try {
    const res = await fetch(`/api/account/${idx}/resume_views`);
    const data = await res.json();

    // обновляем карточки статов сразу из ответа API не дожидаясь WebSocket
    const s = data.stats || {};
    const statsRow = document.getElementById('views-stats-row');
    if (statsRow && (s.views_7d || s.shows_7d || s.invitations_7d)) {
      statsRow.querySelector('.views-stat-val.c-cyan') && (statsRow.querySelector('.views-stat-val.c-cyan').textContent = s.views_7d || 0);
      const greens = statsRow.querySelectorAll('.views-stat-val.c-green');
      if (greens[0]) greens[0].textContent = '+' + (s.views_new || 0);
      if (greens[1]) greens[1].textContent = '+' + (s.invitations_new || 0);
      const dim = statsRow.querySelector('.views-stat-val[style]');
      if (dim) dim.textContent = s.shows_7d || 0;
      const magenta = statsRow.querySelector('.views-stat-val.c-magenta');
      if (magenta) magenta.textContent = s.invitations_7d || 0;
    }

    el.dataset.loaded = '1'; // помечаем — больше не ретраить
    // Aggregate за всё время + 30-day sparkline. Реверс-найдено в SSR
    // applicantResumeViewHistory.historyViews.total + graphHistoryViews.
    const totalAll = s.total_all_time || 0;
    const totalNew = s.total_new_unseen || 0;
    const graph = s.graph_30d || [];
    let aggHtml = '';
    if (totalAll || graph.length) {
      // Inline SVG sparkline — 30 точек, последняя — вчера
      let svg = '';
      if (graph.length) {
        const max = Math.max(...graph.map(p => p.count), 1);
        const w = 240, h = 36, pad = 2;
        const xstep = (w - pad*2) / Math.max(graph.length - 1, 1);
        const points = graph.map((p, i) => {
          const x = pad + i*xstep;
          const y = h - pad - ((p.count / max) * (h - pad*2));
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');
        const bars = graph.map((p, i) => {
          const x = pad + i*xstep - 1.5;
          const bh = (p.count / max) * (h - pad*2);
          const y = h - pad - bh;
          return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="3" height="${Math.max(bh,1).toFixed(1)}" fill="var(--cyan)" opacity="0.7"><title>${esc(p.date)}: ${p.count}</title></rect>`;
        }).join('');
        svg = `<svg width="${w}" height="${h}" style="display:block">${bars}<polyline points="${points}" fill="none" stroke="var(--cyan)" stroke-width="1" opacity="0.9"/></svg>`;
      }
      aggHtml = `
        <div style="display:flex;gap:18px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);margin-bottom:8px">
          <div>
            <div style="font-size:11px;color:var(--dim)">всего просмотров</div>
            <div style="font-size:18px;color:var(--cyan);font-weight:600">${totalAll.toLocaleString('ru')}</div>
            ${totalNew ? `<div style="font-size:10px;color:var(--green)">+${totalNew} новых</div>` : ''}
          </div>
          ${svg ? `<div><div style="font-size:11px;color:var(--dim);margin-bottom:2px">30 дней:</div>${svg}</div>` : ''}
        </div>
      `;
    }
    const history = data.history || [];
    if (!history.length) {
      el.innerHTML = aggHtml + `<div class="c-dim" style="font-size:12px;padding:8px 0">${t('views_no_data')}</div>`;
      return;
    }
    el.innerHTML = aggHtml + `
      <table class="views-table">
        <thead><tr><th>${t('col_date')}</th><th>${t('col_employer')}</th><th>${t('col_vacancy')}</th></tr></thead>
        <tbody>
          ${history.map(h => `<tr>
            <td class="c-dim">${esc(h.date)}</td>
            <td><a href="https://hh.ru/employer/${esc(h.employer_id)}" target="_blank">${esc(h.name)}</a></td>
            <td class="c-dim">${esc(h.vacancy)}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    `;
  } catch(e) {
    el.innerHTML = '<div class="c-red" style="font-size:12px">Ошибка загрузки</div>';
    // не ставим loaded — пусть retry при следующем тике
  }
}

function autoResponseFilters(idx) {
  const splitIds = (id) => ((document.getElementById(id)?.value || '').split(',')
    .map(v => v.trim()).filter(Boolean));
  const filters = {};
  const roles = splitIds(`acc-ar-roles-${idx}`);
  const experience = document.getElementById(`acc-ar-exp-${idx}`)?.value || '';
  const salary = parseInt(document.getElementById(`acc-ar-salary-${idx}`)?.value || '0', 10);
  const onlySalary = !!document.getElementById(`acc-ar-only-salary-${idx}`)?.checked;
  if (roles.length) filters.professional_roles = roles;
  if (experience) filters.experience = experience;
  if (salary > 0) filters.salary = {currency_code: 'RUR', from: salary};
  if (onlySalary) filters.only_with_salary = true;
  return filters;
}

async function autoResponseLoad(idx, force) {
  const status = document.getElementById(`acc-ar-status-${idx}`);
  const rulesEl = document.getElementById(`acc-ar-rules-${idx}`);
  if (!status || !rulesEl) return;
  if (!force && status.dataset.loaded === '1') return;
  status.textContent = '⏳ Загружаю правила и статистику…';
  try {
    const res = await fetch(`/api/account/${idx}/auto_response`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const rules = Array.isArray(data.rules) ? data.rules : [];
    status.dataset.loaded = '1';
    status.textContent = rules.length
      ? `Найдено правил: ${rules.length}`
      : 'Правил пока нет. Создание может требовать подписку HH Pro.';
    rulesEl.innerHTML = rules.map(rule => {
      const id = String(rule.auto_response_id || rule.id || '');
      const enabled = rule.enabled === true;
      const stats = (data.statistics || {})[id] || {};
      const counters = stats.counters || {};
      const total = Number(counters.total || 0);
      const invites = Number(counters.invitation || 0);
      const viewed = Number(counters.vacancy_from_search_count || 0);
      const encodedId = esc(encodeURIComponent(id));
      return `<div style="padding:7px;border:1px solid var(--border);border-radius:5px;margin-bottom:6px">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
          <b style="color:${enabled ? 'var(--green)' : 'var(--dim)'}">${enabled ? '● Включён' : '○ Выключен'}</b>
          <button class="btn-sm" onclick="autoResponseToggle(${idx},'${encodedId}',${enabled ? 'false' : 'true'},this)">
            ${enabled ? '⏸ Выключить' : '▶ Включить'}
          </button>
        </div>
        <div style="color:var(--dim);margin-top:4px">За 7 дней: откликов <b>${total}</b> · приглашений <b>${invites}</b> · вакансий <b>${viewed}</b></div>
      </div>`;
    }).join('');
  } catch (e) {
    status.dataset.loaded = '';
    status.textContent = `❌ ${e.message || 'Ошибка загрузки'}`;
    rulesEl.innerHTML = '';
  }
}

async function autoResponseCreate(idx, btn) {
  const resumeId = document.getElementById(`acc-ar-resume-${idx}`)?.value || '';
  if (!resumeId) { alert('Сначала выберите резюме в карточке аккаунта'); return; }
  if (!confirm('Создать серверное правило автоотклика HH для выбранного резюме?')) return;
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/account/${idx}/auto_response`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({confirm: true, resume_id: resumeId, filters: autoResponseFilters(idx)}),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const status = document.getElementById(`acc-ar-status-${idx}`);
    if (status) status.dataset.loaded = '';
    await autoResponseLoad(idx, true);
  } catch (e) {
    alert(`Не удалось создать правило: ${e.message || e}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function autoResponseToggle(idx, encodedRuleId, enabled, btn) {
  const action = enabled ? 'включить' : 'выключить';
  if (!confirm(`Точно ${action} серверный автоотклик HH?`)) return;
  const resumeId = document.getElementById(`acc-ar-resume-${idx}`)?.value || '';
  const ruleId = decodeURIComponent(encodedRuleId);
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/account/${idx}/auto_response/${encodeURIComponent(ruleId)}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({confirm: true, resume_id: resumeId, enabled: !!enabled}),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await autoResponseLoad(idx, true);
  } catch (e) {
    alert(`Не удалось ${action} автоотклик: ${e.message || e}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _radarBars(items, valueKey, suffix='') {
  if (!Array.isArray(items) || !items.length) return '<span style="color:var(--dim)">Нет данных</span>';
  const rows = items.filter(x => x && Number.isFinite(Number(x[valueKey])));
  const max = Math.max(...rows.map(x => Number(x[valueKey])), 1);
  return rows.map(x => {
    const value = Number(x[valueKey]);
    const width = Math.max(4, Math.round(value / max * 100));
    return `<div style="display:grid;grid-template-columns:36px 1fr auto;gap:6px;align-items:center;margin:3px 0">`
      + `<span>${esc(String(x.year || '—'))}</span>`
      + `<span style="height:6px;background:rgba(0,240,255,.12);border-radius:4px;overflow:hidden"><i style="display:block;width:${width}%;height:100%;background:var(--cyan)"></i></span>`
      + `<b style="color:var(--fg)">${value.toLocaleString('ru')}${suffix}</b></div>`;
  }).join('');
}

async function careerRadarLoad(idx, force=false) {
  const body = document.getElementById('acc-career-body-' + idx);
  if (!body || (body.dataset.loaded && !force)) return;
  body.textContent = '⏳ Загружаю карьерную статистику HH…';
  try {
    const res = await fetch(`/api/account/${idx}/career_radar`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Недоступно');
    body.dataset.loaded = '1';
    body.innerHTML = `<div style="color:var(--cyan);font-weight:700;margin-bottom:7px">${esc(data.profession || 'Профессия')} · ${esc(data.grade || 'грейд не указан')}</div>`
      + `<div style="color:var(--dim);margin:6px 0 3px">Средняя зарплата по годам</div>${_radarBars(data.salary,'salary',' ₽')}`
      + `<div style="color:var(--dim);margin:8px 0 3px">Количество вакансий</div>${_radarBars(data.vacancies,'vacancy_count')}`
      + `<button class="btn-sm" style="margin-top:7px" onclick="careerRadarLoad(${idx},true)">↻ Обновить</button>`;
  } catch(e) {
    body.innerHTML = `<span style="color:var(--red)">❌ ${esc(e.message)}</span>`;
  }
}

async function resumeVisibilityLoad(idx, force=false) {
  const body = document.getElementById('acc-visibility-body-' + idx);
  const chip = document.getElementById('acc-visibility-chip-' + idx);
  if (!body || (body.dataset.loaded && !force)) return;
  body.textContent = '⏳ Проверяю видимость резюме…';
  try {
    const res = await fetch(`/api/account/${idx}/resume_visibility`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Недоступно');
    body.dataset.loaded = '1';
    const active = data.active || {};
    const color = data.warning ? 'var(--red)' : 'var(--green)';
    if (chip) { chip.textContent = data.warning ? '⚠️ ограничено' : '✅ открыто'; chip.style.color = color; }
    const variants = (data.access_types || []).map(x =>
      `<div style="padding:3px 5px;margin:2px 0;border-left:2px solid ${x.active ? color : 'var(--border)'};color:${x.active ? 'var(--fg)' : 'var(--dim)'}">${x.active ? '● ' : '○ '}${esc(x.name || x.id || '—')}</div>`
    ).join('');
    body.innerHTML = `<div style="color:${color};font-weight:700;margin-bottom:6px">${data.warning ? '⚠️ Проверьте ограничения: ' : '✅ Активная видимость: '}${esc(active.name || active.id || 'не определена')}</div>`
      + variants
      + `<div style="margin-top:7px;color:var(--dim)">Чёрный список: <b>${data.blacklist_total || 0}</b> · Белый список: <b>${data.whitelist_total || 0}</b></div>`
      + `<div style="margin-top:5px;color:var(--yellow)">Изменение видимости выполняйте осознанно в HH; эта панель только проверяет состояние.</div>`
      + `<button class="btn-sm" style="margin-top:7px" onclick="resumeVisibilityLoad(${idx},true)">↻ Обновить</button>`;
  } catch(e) {
    body.innerHTML = `<span style="color:var(--red)">❌ ${esc(e.message)}</span>`;
  }
}

function _itemLabel(item) {
  if (!item || typeof item !== 'object') return '—';
  const employer = item.employer && (item.employer.name || item.employer.id);
  return item.name || item.title || item.employer_name || employer || item.text || item.id || '—';
}

async function autosearchesLoad(idx, force=false) {
  const el = document.getElementById('acc-autosearches-' + idx);
  if (!el || (el.dataset.loaded && !force)) return;
  el.textContent = '⏳ Загружаю автопоиски…';
  try {
    const d = await (await fetch(`/api/account/${idx}/autosearches`)).json();
    if (!d.ok) throw new Error(d.error || 'Недоступно');
    el.dataset.loaded = '1';
    const items = d.items || [];
    el.innerHTML = items.length ? items.map(x => `<div style="padding:6px;border-bottom:1px solid var(--border)">
      <div><b>${esc(x.name || 'Без названия')}</b> <span style="color:var(--green)">+${Number(x.new_count)||0} новых</span></div>
      <div style="display:flex;gap:5px;margin-top:4px">
        <button class="btn-sm" onclick="autosearchRename(${idx},'${esc(String(x.id||''))}')">✏️ Имя</button>
        <button class="btn-sm" onclick="autosearchSubscription(${idx},'${esc(String(x.id||''))}',${x.email_subscription !== false})">✉️ Подписка</button>
        <button class="btn-sm" style="color:var(--red)" onclick="autosearchDelete(${idx},'${esc(String(x.id||''))}')">🗑</button>
      </div></div>`).join('') : 'Сохранённых поисков нет.';
  } catch(e) { el.innerHTML = `<span style="color:var(--red)">❌ ${esc(e.message)}</span>`; }
}

async function autosearchRename(idx, id) {
  const name = prompt('Новое название автопоиска:');
  if (!name) return;
  const d = await (await fetch(`/api/account/${idx}/autosearches/${encodeURIComponent(id)}`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})})).json();
  if (!d.ok) return alert(d.error || 'Ошибка HH');
  autosearchesLoad(idx,true);
}

async function autosearchSubscription(idx, id, enabled) {
  if (!confirm(`${enabled ? 'Отключить' : 'Включить'} email-подписку этого автопоиска?`)) return;
  const d = await (await fetch(`/api/account/${idx}/autosearches/${encodeURIComponent(id)}`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({email_subscription:!enabled})})).json();
  if (!d.ok) return alert(d.error || 'Ошибка HH');
  autosearchesLoad(idx,true);
}

async function autosearchDelete(idx, id) {
  if (!confirm('Удалить этот автопоиск из HH? Отменить действие автоматически нельзя.')) return;
  const d = await (await fetch(`/api/account/${idx}/autosearches/${encodeURIComponent(id)}`, {method:'DELETE'})).json();
  if (!d.ok) return alert(d.error || 'Ошибка HH');
  autosearchesLoad(idx,true);
}

async function hiddenItemsLoad(idx, force=false) {
  const el = document.getElementById('acc-hidden-' + idx);
  if (!el || (el.dataset.loaded && !force)) return;
  el.textContent = '⏳ Загружаю скрытые списки…';
  try {
    const d = await (await fetch(`/api/account/${idx}/hidden`)).json();
    if (!d.ok) throw new Error(d.error || 'Недоступно');
    el.dataset.loaded = '1';
    const section = (title, kind, items, total) => `<div style="color:var(--cyan);margin:6px 0">${title}: ${total}</div>` +
      ((items||[]).map(x => `<div style="display:flex;justify-content:space-between;gap:6px;padding:4px;border-bottom:1px solid var(--border)"><span>${esc(_itemLabel(x))}</span><button class="btn-sm" onclick="hiddenRestore(${idx},'${kind}','${esc(String(x.id || x.vacancy_id || x.employer_id || ''))}')">↩ Вернуть</button></div>`).join('') || '<span style="color:var(--dim)">Список пуст</span>');
    el.innerHTML = section('Вакансии','vacancy',d.vacancies,d.vacancies_total) + section('Работодатели','employer',d.employers,d.employers_total);
  } catch(e) { el.innerHTML = `<span style="color:var(--red)">❌ ${esc(e.message)}</span>`; }
}

async function hiddenRestore(idx, kind, id) {
  if (!id || !confirm('Вернуть этот объект из скрытого списка HH?')) return;
  const d = await (await fetch(`/api/account/${idx}/hidden/${kind}/${encodeURIComponent(id)}`, {method:'DELETE'})).json();
  if (!d.ok) return alert(d.error || 'Ошибка HH');
  hiddenItemsLoad(idx,true);
}

async function bellNotificationsLoad(idx, force=false) {
  const el = document.getElementById('acc-bell-' + idx);
  if (!el || (el.dataset.loaded && !force)) return;
  el.textContent = '⏳ Загружаю уведомления…';
  try {
    const d = await (await fetch(`/api/account/${idx}/bell_notifications`)).json();
    if (!d.ok) throw new Error(d.error || 'Недоступно');
    el.dataset.loaded = '1';
    const items = d.notifications || [];
    el.innerHTML = items.length ? items.slice(0,30).map(x => `<div style="padding:5px;border-bottom:1px solid var(--border);color:${x.viewed ? 'var(--dim)' : 'var(--fg)'}">${esc(_itemLabel(x))}</div>`).join('') : 'Новых уведомлений нет.';
  } catch(e) { el.innerHTML = `<span style="color:var(--red)">❌ ${esc(e.message)}</span>`; }
}

async function conversionLoad(idx) {
  const el = document.getElementById('acc-conversion-' + idx);
  if (!el) return;
  el.textContent = '⏳ Считаю…';
  try {
    const d = await (await fetch(`/api/account/${idx}/conversion`)).json();
    if (!d.ok) throw new Error(d.error || 'Недоступно');
    el.innerHTML = `<div style="display:flex;gap:18px;align-items:end"><div><b style="font-size:22px;color:var(--cyan)">${d.conversion_percent}%</b><br>конверсия</div><div><b>${d.applied}</b><br>откликов</div><div><b style="color:var(--green)">${d.interviews}</b><br>интервью</div></div>`;
  } catch(e) { el.innerHTML = `<span style="color:var(--red)">❌ ${esc(e.message)}</span>`; }
}

async function declineDiscards(idx, btn) {
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '⏳ Обрабатываю...';
  try {
    const res = await fetch(`/api/account/${idx}/decline_discards`, {method:'POST'});
    const data = await res.json();
    btn.textContent = `✅ Отклонено: ${data.declined || 0}`;
    setTimeout(() => { btn.disabled = false; btn.textContent = t('btn_clear_discards'); }, 4000);
  } catch(e) {
    btn.textContent = '❌ Ошибка';
    setTimeout(() => { btn.disabled = false; btn.textContent = t('btn_clear_discards'); }, 3000);
  }
}

async function applyTestsToggle(idx, cb) {
  cb.dataset.localToggleAt = String(Date.now());
  try {
    const res = await fetch(`/api/account/${idx}/apply_tests`, {method:'POST'});
    const data = await res.json();
    if (!data.ok) { cb.checked = !cb.checked; return; }
    const label = document.getElementById('acc-apply-label-' + idx);
    if (label) {
      if (data.apply_tests) label.classList.add('active');
      else label.classList.remove('active');
    }
  } catch(e) {
    cb.checked = !cb.checked;
  }
}

async function safetyToggle(idx, cb) {
  cb.dataset.localToggleAt = String(Date.now());
  try {
    const res = await fetch(`/api/account/${idx}/safety_toggle`, {method:'POST'});
    const data = await res.json();
    if (!res.ok || !data.ok) cb.checked = !cb.checked;
  } catch(e) {
    cb.checked = !cb.checked;
  }
}

async function humanModeToggle(cb) {
  // Глобальный флаг (общий для всех аккаунтов) — но toggle доступен с любой
  // карточки. Синхронизируем состояние всех остальных чекбоксов на этом snapshot.
  const enabled = cb.checked;
  try {
    const res = await fetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({key:'human_mode_enabled', value: enabled})
    });
    const data = await res.json();
    if (!data.ok) { cb.checked = !enabled; return; }
    // Обновить остальные чекбоксы на других карточках + в Settings
    document.querySelectorAll('[id^="acc-humanmode-cb-"]').forEach(el => el.checked = enabled);
    const settingsCb = document.getElementById('hp-human_mode_enabled');
    if (settingsCb) settingsCb.checked = enabled;
  } catch(e) {
    cb.checked = !enabled;
  }
}

async function degradedFallbackToggle(idx, cb) {
  cb.dataset.localToggleAt = String(Date.now());
  try {
    const res = await fetch(`/api/account/${idx}/degraded_fallback`, {method:'POST'});
    const data = await res.json();
    if (!data.ok) { cb.checked = !cb.checked; return; }
    const label = document.getElementById('acc-degraded-label-' + idx);
    if (label) {
      if (data.degraded_fallback_enabled) label.classList.add('active');
      else label.classList.remove('active');
    }
  } catch(e) {
    cb.checked = !cb.checked;
  }
}

// ── JSON Editor ─────────────────────────────────────────────────
const JSON_CONFIG_TEMPLATE = {
  "pages_per_url": 3,
  "max_concurrent": 5,
  "response_delay": 2,
  "pause_between_cycles": 5,
  "limit_check_interval": 30,
  "resume_touch_interval": 4,
  "batch_responses": 5,
  "min_salary": 0,
  "questionnaire_default_answer": "Готова рассказать подробнее на собеседовании.",
  "questionnaire_templates": [
    {"keyword": "ключевое слово вопроса", "answer": "ответ на этот вопрос"}
  ],
  "letter_templates": [
    {"name": "Название шаблона", "text": "Текст сопроводительного письма..."}
  ],
  "url_pool": [
    {"url": "https://hh.ru/search/vacancy?text=QA&area=113&order_by=publication_time&items_on_page=20", "pages": 40}
  ]
};

const JSON_ACCOUNT_TEMPLATE = {
  "name": "Имя (Компания)",
  "short": "Имя",
  "color": "yellow",
  "resume_hash": "ВСТАВЬТЕ_ХЭШ_РЕЗЮМЕ",
  "letter": "",
  "apply_tests": false,
  "urls": [],
  "cookies": {
    "hhtoken": "",
    "_xsrf": "",
    "hhul": "",
    "crypted_id": ""
  }
};

function jsonConfigTemplate() {
  const ta = document.getElementById('json-config-ta');
  const st = document.getElementById('json-config-st');
  ta.value = JSON.stringify(JSON_CONFIG_TEMPLATE, null, 2);
  st.textContent = '📋 Шаблон загружен — отредактируйте и сохраните';
  st.style.color = 'var(--cyan)';
}

function jsonAccountsTemplate() {
  const ta = document.getElementById('json-accounts-ta');
  const st = document.getElementById('json-accounts-st');
  // Если уже есть данные — добавляем новый аккаунт в конец массива
  let arr = [];
  try { arr = JSON.parse(ta.value); if (!Array.isArray(arr)) arr = []; } catch(e) {}
  arr.push(JSON.parse(JSON.stringify(JSON_ACCOUNT_TEMPLATE)));
  ta.value = JSON.stringify(arr, null, 2);
  st.textContent = arr.length > 1
    ? `📋 Добавлен шаблон аккаунта (всего ${arr.length})`
    : '📋 Шаблон загружен — заполните данные и сохраните';
  st.style.color = 'var(--cyan)';
}
async function jsonConfigLoad(btn) {
  btn.disabled = true;
  try {
    const res = await fetch('/api/raw/config');
    const data = await res.json();
    document.getElementById('json-config-ta').value = JSON.stringify(data, null, 2);
    document.getElementById('json-config-st').textContent = '✅ Загружено';
    document.getElementById('json-config-st').style.color = 'var(--green)';
  } catch(e) {
    document.getElementById('json-config-st').textContent = '❌ ' + e;
    document.getElementById('json-config-st').style.color = 'var(--red)';
  }
  btn.disabled = false;
}

async function jsonConfigSave(btn) {
  const ta = document.getElementById('json-config-ta');
  const st = document.getElementById('json-config-st');
  let parsed;
  try { parsed = JSON.parse(ta.value); }
  catch(e) { st.textContent = '❌ Невалидный JSON: ' + e.message; st.style.color = 'var(--red)'; return; }
  btn.disabled = true;
  try {
    const res = await fetch('/api/raw/config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(parsed)
    });
    const data = await res.json();
    if (data.ok) { st.textContent = '✅ Сохранено'; st.style.color = 'var(--green)'; }
    else { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
  } catch(e) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  btn.disabled = false;
}

async function jsonAccountsLoad(btn) {
  btn.disabled = true;
  try {
    const res = await fetch('/api/raw/accounts');
    const data = await res.json();
    document.getElementById('json-accounts-ta').value = JSON.stringify(data, null, 2);
    document.getElementById('json-accounts-st').textContent = '✅ Загружено';
    document.getElementById('json-accounts-st').style.color = 'var(--green)';
  } catch(e) {
    document.getElementById('json-accounts-st').textContent = '❌ ' + e;
    document.getElementById('json-accounts-st').style.color = 'var(--red)';
  }
  btn.disabled = false;
}

async function jsonAllLoad(btn) {
  const ta = document.getElementById('json-all-ta');
  const st = document.getElementById('json-all-st');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/backup');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (ta) {
      ta.value = JSON.stringify(data, null, 2);
      ta.dataset.dirty = '0';  // снимаем флаг ручных правок
    }
    if (st && btn) { st.textContent = '✅ Загружено'; st.style.color = 'var(--green)'; }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  }
  if (btn) btn.disabled = false;
}

async function jsonAllWipe(btn) {
  const st = document.getElementById('json-all-st');
  if (!confirm('УДАЛИТЬ все аккаунты, сессии, токены и конфиг? Это необратимо.')) return;
  if (!confirm('Точно? Будут стёрты все cookies и API-ключи.')) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Удаляю...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch('/api/backup', {method: 'DELETE'});
    const data = await res.json();
    if (data.ok) {
      if (st) { st.textContent = `✅ Удалено: ${(data.cleared||[]).join(', ')}`; st.style.color = 'var(--green)'; }
      jsonAllLoad(null);
      try { if (State.ws) State.ws.close(); } catch(e) {}
    } else {
      if (st) { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  }
  if (btn) btn.disabled = false;
}

async function jsonAllSave(btn) {
  const ta = document.getElementById('json-all-ta');
  const st = document.getElementById('json-all-st');
  let parsed;
  try { parsed = JSON.parse(ta.value); }
  catch(e) { if (st) { st.textContent = '❌ Невалидный JSON: ' + e.message; st.style.color = 'var(--red)'; } return; }
  // Diff vs текущий бэкенд-стейт — если что-то теряется (пустые list/string на месте непустых),
  // показываем предупреждение перед сохранением.
  let current = null;
  try { const r = await fetch('/api/backup'); current = await r.json(); } catch(e) {}
  const TRACK = {
    'config.json': ['llm_profiles', 'letter_templates', 'questionnaire_templates', 'url_pool', 'allowed_schedules', 'llm_api_key', 'llm_system_prompt'],
    'accounts.json': null,  // целиком
    'browser_sessions.json': null,
  };
  const lost = [];
  if (current) {
    for (const [fname, fields] of Object.entries(TRACK)) {
      const oldF = current[fname];
      const newF = parsed[fname];
      if (fields) {
        for (const f of fields) {
          const ov = (oldF || {})[f];
          const nv = (newF || {})[f];
          const oNonEmpty = Array.isArray(ov) ? ov.length > 0 : (typeof ov === 'string' ? ov.length > 0 : !!ov);
          const nEmpty = Array.isArray(nv) ? nv.length === 0 : (typeof nv === 'string' ? nv.length === 0 : !nv);
          if (oNonEmpty && nEmpty) {
            const oldCount = Array.isArray(ov) ? ov.length : '~';
            lost.push(`${fname}/${f} (${oldCount} → 0)`);
          }
        }
      } else {
        const oldArr = Array.isArray(oldF) ? oldF : [];
        const newArr = Array.isArray(newF) ? newF : [];
        if (oldArr.length > 0 && newArr.length === 0) lost.push(`${fname} (${oldArr.length} → 0)`);
      }
    }
  }
  let confirmMsg = 'Сохранить и перезаписать ВСЕ data/*.json? Текущие данные потеряются.';
  if (lost.length) {
    confirmMsg = '⚠️ Потеряются непустые поля:\n• ' + lost.join('\n• ') +
                 '\n\nПродолжить (затрёт всё)? Жми Cancel чтобы не сохранять.';
  }
  if (!confirm(confirmMsg)) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Сохраняю...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch('/api/backup', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(parsed)
    });
    const data = await res.json();
    if (data.ok) {
      if (st) { st.textContent = `✅ Сохранено: ${(data.restored||[]).join(', ')}. ${data.warning||''}`; st.style.color = 'var(--green)'; }
      // Перечитаем из бэка чтобы textarea показывала актуальное состояние.
      jsonAllLoad(null);
      // Форс-реконнект WS → свежий snapshot → UI перерисовывается без F5.
      try { if (State.ws) State.ws.close(); } catch(e) {}
    } else {
      if (st) { st.textContent = '❌ ' + (data.error || JSON.stringify(data.errors||{})); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  }
  if (btn) btn.disabled = false;
}

async function backupDownload(btn) {
  const st = document.getElementById('backup-st');
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Готовлю...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch('/api/backup');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    const stamp = new Date().toISOString().replace(/[:T]/g,'-').slice(0,19);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `hh-backup-${stamp}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    if (st) { st.textContent = '✅ Скачано'; st.style.color = 'var(--green)'; }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  }
  if (btn) btn.disabled = false;
}

async function backupRestore(input) {
  const st = document.getElementById('backup-st');
  const f = input.files && input.files[0];
  if (!f) return;
  if (!confirm(`Восстановить из ${f.name}? Текущие data/*.json будут перезаписаны.`)) {
    input.value = ''; return;
  }
  if (st) { st.textContent = '⏳ Восстанавливаю...'; st.style.color = 'var(--dim)'; }
  try {
    const text = await f.text();
    let parsed;
    try { parsed = JSON.parse(text); }
    catch(e) { throw new Error('Невалидный JSON: ' + e.message); }
    const res = await fetch('/api/backup', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(parsed)
    });
    const data = await res.json();
    if (data.ok) {
      if (st) {
        st.textContent = `✅ Восстановлено: ${(data.restored||[]).join(', ')}. ${data.warning||''}`;
        st.style.color = 'var(--green)';
      }
      // Подтянем свежий стейт в редактор после restore.
      if (document.getElementById('json-all-ta')) jsonAllLoad(null);
      try { if (State.ws) State.ws.close(); } catch(e) {}
    } else {
      if (st) { st.textContent = '❌ ' + (data.error || JSON.stringify(data.errors||{})); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  }
  input.value = '';
}

async function jsonAccountsSave(btn) {
  const ta = document.getElementById('json-accounts-ta');
  const st = document.getElementById('json-accounts-st');
  let parsed;
  try { parsed = JSON.parse(ta.value); }
  catch(e) { st.textContent = '❌ Невалидный JSON: ' + e.message; st.style.color = 'var(--red)'; return; }
  if (!Array.isArray(parsed)) {
    st.textContent = '❌ Ожидается массив аккаунтов'; st.style.color = 'var(--red)'; return;
  }
  btn.disabled = true;
  try {
    const res = await fetch('/api/raw/accounts', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(parsed)
    });
    const data = await res.json();
    if (data.ok) { st.textContent = `✅ Сохранено (${data.count} аккаунтов)`; st.style.color = 'var(--green)'; }
    else { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
  } catch(e) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  btn.disabled = false;
}

// Update header resume stats
function updateHeaderResumeStats(snap) {
  let totalViewsNew = 0, totalInvNew = 0, totalShows = 0;
  (snap.accounts || []).forEach(a => {
    totalViewsNew += a.resume_views_new || 0;
    totalInvNew += a.resume_invitations_new || 0;
    totalShows += a.resume_shows_7d || 0;
  });
  const hdrEl = document.getElementById('hdr-resume-stats');
  if (hdrEl) {
    hdrEl.style.display = (totalViewsNew > 0 || totalInvNew > 0 || totalShows > 0) ? '' : 'none';
    setText('hdr-views-new', totalViewsNew);
    setText('hdr-inv-new', totalInvNew);
    setText('hdr-shows', totalShows);
  }
}

// ── Questionnaire templates ──────────────────────────────────
function qRenderTemplates(templates) {
  const list = document.getElementById('q-templates-list');
  list.innerHTML = '';
  const previews = State.lastSnapshot?.config?.questionnaire_preset_previews || {};
  (templates || []).forEach((tmpl, i) => {
    const rawAnswer = tmpl.answer || '';
    const preview = previews[rawAnswer] || rawAnswer;
    const row = document.createElement('div');
    row.className = 'q-template-row';
    row.dataset.idx = i;
    row.innerHTML = `
      <button class="q-del" onclick="qDelTemplate(${i})" title="Удалить">✕</button>
      <label>${t('q_keywords_label')} — по ним ищется совпадение с текстом вопроса</label>
      <input type="text" class="q-keywords-input" placeholder="${t('q_keywords_ph')}"
        value="${esc((tmpl.keywords || []).join(', '))}">
      <label>${t('q_answer_label')}</label>
      <textarea class="q-answer-input" rows="3" placeholder="Ваш ответ...">${esc(preview)}</textarea>
    `;
    const answer = row.querySelector('.q-answer-input');
    answer.dataset.rawAnswer = rawAnswer;
    answer.dataset.previewAnswer = preview;
    list.appendChild(row);
  });
}

function qUpdateGenderPreview(snap) {
  const previews = snap?.config?.questionnaire_preset_previews || {};
  document.querySelectorAll('#q-templates-list .q-answer-input').forEach(answer => {
    if (answer.value !== answer.dataset.previewAnswer) return; // user is editing
    const raw = answer.dataset.rawAnswer || '';
    const preview = previews[raw] || raw;
    answer.value = preview;
    answer.dataset.previewAnswer = preview;
  });
  const def = document.getElementById('q-default-answer');
  if (def?.dataset.presetDefault === 'true') {
    def.value = qBuiltinDefaultForGender(snap?.config?.llm_applicant_gender);
  } else if (def && !def._userEdited && snap?.config?.questionnaire_default_answer) {
    def.value = snap.config.questionnaire_default_answer;
  }
}

function qBuiltinDefaultForGender(gender) {
  if (gender === 'male') return 'Готов рассказать подробнее на собеседовании.';
  if (gender === 'neutral') return 'Подробнее расскажу на собеседовании.';
  return 'Готова рассказать подробнее на собеседовании.';
}

// ── Questionnaire presets ─────────────────────────────────────
const Q_PRESETS = {
  universal: {
    default: 'Готова рассказать подробнее на собеседовании.',
    templates: [
      { keywords: ['командировк'],
        answer: 'Да, готова к командировкам.' },
      { keywords: ['переработк', 'сверхурочн', 'задерж'],
        answer: 'Да, готова к переработкам при необходимости.' },
      { keywords: ['ненормированн', 'гибкий график', 'нестандартн'],
        answer: 'Да, рассматриваю.' },
      { keywords: ['вахт'],
        answer: 'Нет, вахтовый метод не рассматриваю.' },
      { keywords: ['ночн смен', 'сменн', 'посменн', '2/2', '3/3'],
        answer: 'Да, рассматриваю сменный график.' },
      { keywords: ['выходн', 'праздник', 'суббот', 'воскресен'],
        answer: 'Да, готова работать в выходные при необходимости.' },
      { keywords: ['почему', 'привлекает', 'хотите работать у нас', 'хотите работать в'],
        answer: 'Меня привлекает стабильная компания, интересные задачи и возможность профессионального роста.' },
      { keywords: ['расскажите о себе', 'опишите себя', 'кто вы'],
        answer: 'Ответственный и целеустремлённый специалист с опытом работы. Быстро обучаюсь, умею работать в команде и самостоятельно. Готова к новым задачам и развитию.' },
      { keywords: ['опыт работ', 'стаж', 'сколько лет'],
        answer: 'Имею опыт работы в данной сфере более 2 лет. Готова рассказать подробнее на собеседовании.' },
      { keywords: ['сильн сторон', 'достоинств', 'преимущест'],
        answer: 'Ответственность, стрессоустойчивость, коммуникабельность и быстрое обучение.' },
      { keywords: ['почему уволил', 'предыдущ', 'прошл место'],
        answer: 'В поиске новых возможностей для профессионального развития.' },
      { keywords: ['зарплат', 'оклад', 'доход', 'вознагражд', 'ожидани', 'желаем'],
        answer: 'От 70 000 рублей. Готова обсудить на собеседовании.' },
      { keywords: ['когда', 'приступить', 'выйти на работу', 'дата выхода', 'готов'],
        answer: 'Готова приступить в течение 2 недель.' },
      { keywords: ['формат работ', 'офис', 'удалённ', 'удален', 'remote', 'гибрид'],
        answer: 'Рассматриваю гибридный и удалённый формат.' },
      { keywords: ['город', 'регион', 'переезд', 'релокац'],
        answer: 'Готова рассмотреть предложение.' },
      { keywords: ['английск', 'english', 'иностранн язык'],
        answer: 'Базовый уровень.' },
      { keywords: ['автомобил', 'машин', 'водительск', 'права кат'],
        answer: 'Нет.' },
      { keywords: ['образован', 'диплом', 'вуз', 'институт', 'университет'],
        answer: 'Высшее.' },
      { keywords: ['обучени', 'курс', 'тренинг'],
        answer: 'Да, готова к обучению и развитию.' },
    ]
  },
  sales: {
    default: 'Готова рассказать подробнее на собеседовании.',
    templates: [
      { keywords: ['командировк'],
        answer: 'Да, готова.' },
      { keywords: ['переработк', 'сверхурочн'],
        answer: 'Да, при необходимости.' },
      { keywords: ['вахт'],
        answer: 'Нет.' },
      { keywords: ['почему', 'привлекает', 'хотите'],
        answer: 'Интересует возможность работать с клиентами, выполнять план и расти в доходе.' },
      { keywords: ['опыт продаж', 'продавал', 'менеджер по продажам'],
        answer: 'Да, есть опыт активных продаж. Умею работать с возражениями и выполнять KPI.' },
      { keywords: ['опыт работ с клиент', 'клиентск'],
        answer: 'Да, есть опыт работы с клиентами: входящие и исходящие звонки, консультации, оформление заказов.' },
      { keywords: ['колл-центр', 'кол центр', 'call center', 'оператор'],
        answer: 'Да, есть опыт работы оператором колл-центра.' },
      { keywords: ['crm', 'срм', '1с', '1c'],
        answer: 'Да, работала с CRM-системами и 1С.' },
      { keywords: ['план', 'kpi', 'ки пи ай', 'выполнени'],
        answer: 'Да, умею работать по плановым показателям и выполняю их.' },
      { keywords: ['стресс', 'конфликт', 'сложн клиент'],
        answer: 'Стрессоустойчива, умею работать со сложными клиентами и находить компромисс.' },
      { keywords: ['зарплат', 'оклад', 'доход', 'ожидани'],
        answer: 'Оклад от 50 000 + % от продаж.' },
      { keywords: ['когда', 'приступить', 'выйти'],
        answer: 'Готова приступить в течение недели.' },
      { keywords: ['формат', 'офис', 'удалённ'],
        answer: 'Рассматриваю офисный и гибридный форматы.' },
      { keywords: ['английск', 'english'],
        answer: 'Базовый.' },
      { keywords: ['обучени', 'тренинг'],
        answer: 'Да, готова к обучению.' },
    ]
  },
  office: {
    default: 'Готова рассказать подробнее на собеседовании.',
    templates: [
      { keywords: ['командировк'],
        answer: 'Нет, командировки не рассматриваю.' },
      { keywords: ['переработк', 'сверхурочн'],
        answer: 'В исключительных случаях готова.' },
      { keywords: ['вахт'],
        answer: 'Нет.' },
      { keywords: ['почему', 'привлекает', 'хотите'],
        answer: 'Привлекает стабильность, официальное оформление и чёткий функционал.' },
      { keywords: ['опыт работ', 'стаж'],
        answer: 'Есть опыт офисной работы: документооборот, работа с оргтехникой, MS Office, координация задач.' },
      { keywords: ['1с', '1c'],
        answer: 'Да, базовый опыт работы в 1С.' },
      { keywords: ['excel', 'word', 'office', 'офис'],
        answer: 'Уверенный пользователь MS Office: Word, Excel, Outlook.' },
      { keywords: ['оргтехник', 'принтер', 'скан'],
        answer: 'Да, умею работать с оргтехникой.' },
      { keywords: ['документооборот', 'делопроизводств'],
        answer: 'Да, есть опыт ведения документооборота и делопроизводства.' },
      { keywords: ['зарплат', 'оклад', 'доход', 'ожидани'],
        answer: 'От 60 000 рублей.' },
      { keywords: ['когда', 'приступить', 'выйти'],
        answer: 'Готова приступить в течение 2 недель.' },
      { keywords: ['формат', 'офис', 'удалённ'],
        answer: 'Предпочтительно офисный или гибридный формат.' },
      { keywords: ['английск', 'english'],
        answer: 'Базовый.' },
      { keywords: ['автомобил', 'права'],
        answer: 'Нет.' },
      { keywords: ['образован'],
        answer: 'Высшее.' },
    ]
  },
  remote: {
    default: 'Готова рассказать подробнее на собеседовании.',
    templates: [
      { keywords: ['командировк'],
        answer: 'Нет, предпочитаю удалённый формат.' },
      { keywords: ['переработк', 'сверхурочн'],
        answer: 'Да, при необходимости готова.' },
      { keywords: ['вахт'],
        answer: 'Нет.' },
      { keywords: ['почему', 'привлекает', 'хотите'],
        answer: 'Привлекает удалённый формат, интересные задачи и возможность развиваться в IT-сфере.' },
      { keywords: ['опыт работ', 'стаж'],
        answer: 'Есть опыт удалённой работы. Умею самостоятельно организовывать рабочий процесс.' },
      { keywords: ['интернет', 'оборудован', 'компьютер', 'пк'],
        answer: 'Да, есть стабильный интернет и необходимое оборудование.' },
      { keywords: ['часовой пояс', 'мск', 'москов'],
        answer: 'Работаю в часовом поясе МСК+0.' },
      { keywords: ['english', 'английск'],
        answer: 'Pre-Intermediate / Базовый.' },
      { keywords: ['python', 'java', 'sql', 'программирован'],
        answer: 'Да, есть базовые знания. Готова развиваться.' },
      { keywords: ['google', 'таблиц', 'notion', 'jira', 'confluence', 'trello'],
        answer: 'Да, работала с Google-сервисами, Notion, Trello.' },
      { keywords: ['зарплат', 'оклад', 'доход', 'ожидани'],
        answer: 'От 70 000 рублей.' },
      { keywords: ['когда', 'приступить', 'выйти'],
        answer: 'Готова приступить в течение недели.' },
      { keywords: ['формат', 'удалённ', 'гибрид'],
        answer: 'Предпочтительно полностью удалённый или гибридный.' },
      { keywords: ['обучени', 'курс'],
        answer: 'Да, готова к обучению за счёт компании.' },
    ]
  }
};

function qLoadPreset(name) {
  const preset = Q_PRESETS[name];
  if (!preset) return;
  if (!confirm(`Загрузить пресет "${name}"? Текущие шаблоны будут заменены.`)) return;
  qRenderTemplates(preset.templates);
  const defEl = document.getElementById('q-default-answer');
  if (defEl) {
    const gender = document.getElementById('cfg-llm-applicant-gender')?.value;
    defEl.value = qBuiltinDefaultForGender(gender);
    defEl._userEdited = true;
    defEl.dataset.presetDefault = 'true';
  }
  const st = document.getElementById('q-status');
  st.textContent = `✅ Пресет загружен (${preset.templates.length} шаблонов). Отредактируй и нажми «Сохранить».`;
  st.style.color = 'var(--yellow)';
  setTimeout(() => { st.textContent = ''; st.style.color = ''; }, 6000);
  document.getElementById('q-templates-list')?.scrollIntoView({behavior:'smooth'});
}

function qAddTemplate() {
  const templates = qReadTemplates();
  templates.push({keywords: [], answer: ''});
  qRenderTemplates(templates);
  // Scroll to new row
  document.getElementById('q-templates-list').lastElementChild?.scrollIntoView({behavior:'smooth'});
}

function qDelTemplate(idx) {
  const templates = qReadTemplates();
  templates.splice(idx, 1);
  qRenderTemplates(templates);
}

function qReadTemplates() {
  const rows = document.querySelectorAll('#q-templates-list .q-template-row');
  const result = [];
  rows.forEach(row => {
    const kw = row.querySelector('.q-keywords-input')?.value || '';
    const field = row.querySelector('.q-answer-input');
    const ans = field?.value || '';
    result.push({
      keywords: kw.split(',').map(s => s.trim()).filter(Boolean),
      answer: ans === field?.dataset.previewAnswer ? field.dataset.rawAnswer : ans
    });
  });
  return result;
}

function qSave() {
  const templates = qReadTemplates();
  const defaultAnswer = document.getElementById('q-default-answer')?.value || '';
  sendCmd({type: 'set_questionnaire', templates, default_answer: defaultAnswer});
  const st = document.getElementById('q-status');
  st.textContent = `✅ Сохранено ${templates.length} шаблонов`;
  setTimeout(() => { st.textContent = ''; }, 3000);
}

function qSyncFromSnapshot(snap) {
  if (!snap || !snap.config) return;
  const templates = snap.config.questionnaire_templates || [];
  const defaultAns = snap.config.questionnaire_default_answer || '';
  qRenderTemplates(templates);
  const el = document.getElementById('q-default-answer');
  if (el && !el._userEdited) el.value = defaultAns;
}

// Mark as user-edited so we don't override on next snapshot
document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('q-default-answer');
  if (el) el.addEventListener('input', () => {
    el._userEdited = true;
    el.dataset.presetDefault = '';
  });
});

// ── Dark confirm dialog ──────────────────────────────────────────
function showConfirm(msg, okLabel = null, cancelLabel = null) {
  if (okLabel === null) okLabel = t('confirm_delete');
  if (cancelLabel === null) cancelLabel = t('confirm_cancel');
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    const box = document.createElement('div');
    box.className = 'confirm-box';
    const p = document.createElement('p');
    p.textContent = msg;
    const btns = document.createElement('div');
    btns.className = 'confirm-btns';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'confirm-cancel';
    cancelBtn.textContent = cancelLabel;
    const okBtn = document.createElement('button');
    okBtn.className = 'confirm-ok';
    okBtn.textContent = okLabel;
    btns.appendChild(cancelBtn);
    btns.appendChild(okBtn);
    box.appendChild(p);
    box.appendChild(btns);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    okBtn.onclick = () => { document.body.removeChild(overlay); resolve(true); };
    cancelBtn.onclick = () => { document.body.removeChild(overlay); resolve(false); };
    overlay.onclick = (e) => { if (e.target === overlay) { document.body.removeChild(overlay); resolve(false); } };
  });
}

// ── Compact card mode ──────────────────────────────────────────
function toggleCompact(idx) {
  if (State.compactCards.has(idx)) State.compactCards.delete(idx);
  else State.compactCards.add(idx);
  const card = document.getElementById('card-' + idx);
  if (!card) return;
  const btn = card.querySelector('.compact-btn');
  if (State.compactCards.has(idx)) {
    card.classList.add('compact');
    if (btn) { btn.textContent = '⬜'; btn.title = 'Развернуть карточку'; }
  } else {
    card.classList.remove('compact');
    if (btn) { btn.textContent = '⬜'; btn.title = 'Свернуть карточку'; }
  }
}

// ── CSV Export ──────────────────────────────────────────────────
function exportCSV(headers, rows, filename) {
  const lines = [
    headers.map(h => '"' + h.replace(/"/g, '""') + '"').join(','),
    ...rows.map(r => r.map(v => '"' + String(v ?? '').replace(/"/g, '""') + '"').join(','))
  ];
  const blob = new Blob(['\uFEFF' + lines.join('\n')], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function exportAppliedCSV() {
  if (!AppliedState.all.length) return;
  const headers = ['Дата', 'Аккаунт', 'ID вакансии', 'Название', 'Компания', 'Зарплата от', 'Зарплата до', 'Ссылка'];
  const rows = AppliedState.all.map(i => [
    i.at ? new Date(i.at).toLocaleString('ru-RU') : '',
    i.account || '',
    i.vacancy_id || '',
    i.title || '',
    i.company || '',
    i.salary_from || '',
    i.salary_to || '',
    i.url || `https://hh.ru/vacancy/${i.vacancy_id}`,
  ]);
  exportCSV(headers, rows, `hh_applied_${new Date().toISOString().slice(0,10)}.csv`);
}

function exportDbCSV() {
  if (!DBState.all.length) return;
  const STATUS_LABELS = {sent: 'Отклик отправлен', test_passed: 'Тест пройден', test_pending: 'Не пройден'};
  const headers = ['Статус', 'Дата', 'ID вакансии', 'Название', 'Компания', 'Аккаунты', 'Ссылка'];
  const rows = DBState.all.map(i => [
    STATUS_LABELS[i.status] || i.status,
    i.at ? new Date(i.at).toLocaleString('ru-RU') : '',
    i.vacancy_id || '',
    i.title || '',
    i.company || '',
    (i.applied_by || []).join('; '),
    `https://hh.ru/vacancy/${i.vacancy_id}`,
  ]);
  exportCSV(headers, rows, `hh_db_${new Date().toISOString().slice(0,10)}.csv`);
}

// ── Keyboard shortcuts ─────────────────────────────────────────
// Значения — data-tab у <div class="tab">. `llm` был добавлен в HTML, но
// пропущен здесь → whitelist в restore-таб-с-localStorage не пропускал `llm`
// → после F5 юзер оказывался на Главной. TAB_KEYS также используется для
// hotkey переключения (1-9,0), llm сейчас без хоткея (закончились цифры).
const TAB_KEYS = {'1':'main','2':'log','3':'applied','4':'tests','5':'db','6':'hh','7':'views','8':'apply','9':'settings','0':'hedi'};
// 'recoh' — динамическая вкладка от feat5_recommendations.js, вставляется
// после DOMContentLoaded. Whitelist обязан её знать, иначе F5 на вкладке
// «Рекомендации» кидает юзера на Главную (аудит 2026-08-17 #29).
const _ALL_TAB_IDS = new Set([...Object.values(TAB_KEYS), 'llm', 'recoh', 'questionnaire-history']);

// ── HH mobile OTP authentication ───────────────────────────
const MOBILE_AUTH_FIELDS = [
  ['app_package', 'APP_PACKAGE'], ['app_version_name', 'APP_VERSION_NAME'],
  ['app_version_code', 'APP_VERSION_CODE'], ['device_model', 'Device model'],
  ['android_release', 'Android release'], ['device_uuid', 'Device UUID'],
  ['user_agent_template', 'DEFAULT_USER_AGENT'], ['base_url', 'API base URL'],
  ['app_client_token', 'APP_CLIENT_TOKEN', true], ['oauth_client_id', 'OAUTH_CLIENT_ID'],
  ['oauth_client_secret', 'OAUTH_CLIENT_SECRET', true],
];
let mobileAuthLoginType = 'email';
let mobileAuthTimer = null;

function mobileAuthType(kind) {
  mobileAuthLoginType = kind;
  const phone = document.getElementById('ma-type-phone');
  const email = document.getElementById('ma-type-email');
  if (!phone || !email) return;
  phone.style.background = kind === 'phone' ? 'var(--cyan)' : 'transparent';
  phone.style.color = kind === 'phone' ? '#000' : 'var(--dim)';
  email.style.background = kind === 'email' ? 'var(--cyan)' : 'transparent';
  email.style.color = kind === 'email' ? '#000' : 'var(--dim)';
  const input = document.getElementById('ma-login');
  input.type = kind === 'email' ? 'email' : 'tel';
  input.placeholder = kind === 'email' ? 'name@example.com' : '+79991234567';
}

function mobileAuthFormValues() {
  const values = {};
  MOBILE_AUTH_FIELDS.forEach(([key]) => {
    const el = document.getElementById('ma-cfg-' + key);
    if (el) values[key] = key === 'app_version_code' ? Number(el.value) : el.value;
  });
  return values;
}

function mobileAuthRenderConfig(data) {
  const grid = document.getElementById('ma-config-grid');
  if (!grid) return;
  grid.innerHTML = '';
  MOBILE_AUTH_FIELDS.forEach(([key, label, secret]) => {
    const box = document.createElement('label');
    box.style.cssText = 'display:grid;gap:3px;color:var(--dim);font-size:11px';
    const source = data.sources?.[key] || 'default';
    box.innerHTML = `<span>${label} <small style="color:var(--yellow)">[${source}]</small></span>`;
    const input = document.createElement('input');
    input.id = 'ma-cfg-' + key;
    input.className = 'apply-input';
    input.type = secret ? 'password' : (key === 'app_version_code' ? 'number' : 'text');
    input.autocomplete = 'off';
    input.value = data.values?.[key] ?? '';
    input.addEventListener('input', mobileAuthPreview);
    box.appendChild(input);
    grid.appendChild(box);
  });
  document.getElementById('ma-user-agent').textContent = data.user_agent || '—';
}

async function mobileAuthLoad() {
  try {
    const [cfgResp, stateResp] = await Promise.all([
      fetch('/api/mobile-auth/settings'), fetch('/api/mobile-auth/status')
    ]);
    const cfg = await cfgResp.json();
    const state = await stateResp.json();
    if (cfg.ok) mobileAuthRenderConfig(cfg);
    if (state.stage === 'code_requested') {
      mobileAuthType(state.login_type || 'phone');
      document.getElementById('ma-code-row').style.display = 'flex';
      document.getElementById('ma-status').textContent = `Код отправлен: ${state.login_masked}`;
      mobileAuthCountdown(Math.max(0, Number(state.retry_after || 0) - Math.floor(Date.now()/1000 - Number(state.requested_at || 0))));
    }
  } catch (e) {
    const st = document.getElementById('ma-config-status');
    if (st) st.textContent = 'Не удалось загрузить настройки авторизации';
  }
  mobileAuthType(mobileAuthLoginType);
}

function mobileAuthCountdown(seconds) {
  if (mobileAuthTimer) clearInterval(mobileAuthTimer);
  const label = document.getElementById('ma-request-timer');
  const button = document.getElementById('ma-request');
  let left = Math.max(0, Number(seconds || 0));
  const tick = () => {
    if (label) label.textContent = left > 0 ? `Повтор через ${left} с` : '';
    if (button) button.disabled = left > 0;
    if (left-- <= 0 && mobileAuthTimer) { clearInterval(mobileAuthTimer); mobileAuthTimer = null; }
  };
  tick();
  if (left >= 0) mobileAuthTimer = setInterval(tick, 1000);
}

function mobileAuthShowError(status, data, fallback) {
  status.textContent = data?.error || fallback;
  status.style.color = 'var(--red)';
  if (data?.captcha_url) {
    const link = document.createElement('a');
    link.href = data.captcha_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.className = 'btn-sm';
    link.style.cssText = 'display:inline-block;margin-left:10px;color:var(--yellow);border-color:var(--yellow)';
    link.textContent = '🧩 Пройти CAPTCHA';
    status.appendChild(link);
  }
}

async function mobileAuthRequestCode(button) {
  const status = document.getElementById('ma-status');
  const login = document.getElementById('ma-login').value.trim();
  if (!login) { status.textContent = 'Введите телефон или email'; status.style.color = 'var(--red)'; return; }
  button.disabled = true; status.textContent = 'Отправка кода…'; status.style.color = 'var(--dim)';
  try {
    const r = await fetch('/api/mobile-auth/request-code', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({login, login_type:mobileAuthLoginType})});
    const d = await r.json();
    if (!d.ok) {
      mobileAuthShowError(status, d, 'Не удалось отправить код');
      button.disabled = false;
      return;
    }
    document.getElementById('ma-code-row').style.display = 'flex';
    status.textContent = `Код отправлен: ${d.login_masked}`; status.style.color = 'var(--green)';
    mobileAuthCountdown(d.can_request_code_again_in || d.retry_after || 0);
  } catch (e) { mobileAuthShowError(status, null, e.message); button.disabled = false; }
}

let MobileAuthLastUserId = '';

async function mobileAuthVerify(button) {
  const status = document.getElementById('ma-status');
  const code = document.getElementById('ma-code').value.trim();
  button.disabled = true; status.textContent = 'Проверка кода и загрузка данных…'; status.style.color = 'var(--dim)';
  try {
    const r = await fetch('/api/mobile-auth/verify', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code})});
    const raw = await r.text();
    let d = {};
    try { d = raw ? JSON.parse(raw) : {}; }
    catch (_) { throw new Error(`Сервер вернул не-JSON ответ (HTTP ${r.status}): ${raw.slice(0, 160) || 'пустой ответ'}`); }
    if (!r.ok) throw new Error(d.error || d.detail || `HTTP ${r.status}`);
    if (!d.ok) {
      mobileAuthShowError(status, d, 'Авторизация не удалась');
      return;
    }
    const who = [d.user?.first_name, d.user?.last_name].filter(Boolean).join(' ');
    MobileAuthLastUserId = String(d.user?.id || '');
    status.textContent = `✅ Авторизация успешна${who ? ': '+who : ''}\nРезюме: ${d.resumes}; вакансии: ${d.vacancies_count}. ${d.browser_session_note}`;
    status.style.color = 'var(--green)'; document.getElementById('ma-code-row').style.display = 'none';
  } catch (e) { mobileAuthShowError(status, null, e.message); }
  finally { button.disabled = false; }
}

async function mobileAuthLogout() {
  await fetch('/api/mobile-auth/logout', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mobile_user_id: MobileAuthLastUserId})
  });
  MobileAuthLastUserId = '';
  document.getElementById('ma-code-row').style.display = 'none';
  document.getElementById('ma-code').value = '';
  document.getElementById('ma-status').textContent = 'Локальное состояние входа очищено';
}

async function mobileAuthPreview() {
  const st = document.getElementById('ma-config-status');
  try {
    const r = await fetch('/api/mobile-auth/settings/validate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({values:mobileAuthFormValues()})});
    const d = await r.json();
    if (d.ok) { document.getElementById('ma-user-agent').textContent = d.user_agent; if (st) st.textContent = ''; }
    else if (st) st.textContent = d.error;
  } catch (_) {}
}

async function mobileAuthSaveSettings(button) {
  const st = document.getElementById('ma-config-status'); button.disabled = true;
  try {
    const r = await fetch('/api/mobile-auth/settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({values:mobileAuthFormValues()})});
    const d = await r.json(); if (!d.ok) throw new Error(d.error || 'Ошибка сохранения');
    mobileAuthRenderConfig(d); st.textContent = '✅ Настройки сохранены и применятся к новым запросам'; st.style.color = 'var(--green)';
  } catch(e) { st.textContent = e.message; st.style.color = 'var(--red)'; }
  finally { button.disabled = false; }
}

async function mobileAuthValidate(button) {
  button.disabled = true; await mobileAuthPreview(); button.disabled = false;
  const st = document.getElementById('ma-config-status');
  if (!st.textContent) { st.textContent = '✅ Настройки корректны; запрос к HH не выполнялся'; st.style.color = 'var(--green)'; }
}

async function mobileAuthNewUuid() {
  const d = await (await fetch('/api/mobile-auth/settings/uuid', {method:'POST'})).json();
  if (d.ok) { document.getElementById('ma-cfg-device_uuid').value = d.device_uuid; mobileAuthPreview(); }
}

async function mobileAuthResetSettings() {
  if (!confirm('Восстановить штатные настройки мобильного клиента?')) return;
  const d = await (await fetch('/api/mobile-auth/settings/reset', {method:'POST'})).json();
  if (d.ok) { mobileAuthRenderConfig(d); document.getElementById('ma-config-status').textContent = 'Значения восстановлены'; }
}

document.addEventListener('DOMContentLoaded', mobileAuthLoad);

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key in TAB_KEYS) {
    const tabEl = document.querySelector(`.tab[data-tab="${TAB_KEYS[e.key]}"]`);
    if (tabEl) tabEl.click();
    return;
  }
  if (e.key === 'p' || e.key === 'P') { sendCmd({type: 'pause_toggle'}); return; }
  if (e.key === '?' || e.key === '/') { toggleShortcutsHelp(); return; }
  if (e.key === 'Escape') { closeShortcutsHelp(); }
});

function toggleShortcutsHelp() {
  if (document.getElementById('shortcuts-overlay')) { closeShortcutsHelp(); return; }
  const el = document.createElement('div');
  el.id = 'shortcuts-overlay';
  el.className = 'shortcuts-overlay';
  el.innerHTML = `
    <div class="shortcuts-box">
      <h3>${t('shortcuts_title')}</h3>
      <table>
        <tr><td>1–9</td><td>${t('shortcuts_tabs')}</td></tr>
        <tr><td>P</td><td>${t('shortcuts_pause')}</td></tr>
        <tr><td>? / /</td><td>${t('shortcuts_help')}</td></tr>
        <tr><td>Esc</td><td>${t('shortcuts_esc')}</td></tr>
      </table>
      <div style="margin-top:14px;text-align:right">
        <button class="confirm-cancel" onclick="closeShortcutsHelp()">${t('btn_close')}</button>
      </div>
    </div>`;
  el.onclick = e => { if (e.target === el) closeShortcutsHelp(); };
  document.body.appendChild(el);
}
function closeShortcutsHelp() {
  const el = document.getElementById('shortcuts-overlay');
  if (el) el.remove();
}

// ── Init ──────────────────────────────────────────────────────
buildSettings();
connect();
// System prompt textarea is populated via syncLlmSettings from
// snapshot.config.llm_system_prompt (server is source of truth). We used to
// inject a hardcoded JS default here, but that raced with the WS sync: if
// the user reloaded the page after saving a custom prompt, this init wrote
// the JS-default into the textarea, then the next autosave (triggered by
// any unrelated field) shipped that default back to disk — silently
// overwriting the saved prompt. Removing the init keeps the textarea empty
// until the WS snapshot arrives (~200ms) which is the actual saved value.
document.getElementById('lang-btn').textContent = lang.toUpperCase();
applyI18n();
// Restore last active tab from localStorage.
// Whitelist check: localStorage controllable, не вставляем сырое значение
// в CSS селектор (kimi-r14-3 #7). Используем _ALL_TAB_IDS вместо
// TAB_KEYS.values() — TAB_KEYS это хоткей-мапа, там нет `llm`/`recoh`.
// Аудит 2026-08-17 #29: 'recoh' — динамическая вкладка (feat5 инжектит на
// DOMContentLoaded), в момент этого блока её ещё нет. Ретраим короткое окно.
function _restoreSavedTab() {
  try {
    const savedTab = localStorage.getItem('hh-tab');
    if (!savedTab || !_ALL_TAB_IDS.has(savedTab)) return true;
    const tabEl = document.querySelector(`.tab[data-tab="${savedTab}"]`);
    if (tabEl) { tabEl.click(); return true; }
  } catch(e) { return true; }
  return false;
}
if (!_restoreSavedTab()) {
  // Дожидаемся регистрации динамических вкладок feature-скриптами.
  let _tries = 0;
  const _tabTimer = setInterval(() => {
    _tries++;
    if (_restoreSavedTab() || _tries > 20) clearInterval(_tabTimer);
  }, 100);
}
// Request browser notification permission
if ('Notification' in window && Notification.permission === 'default') {
  setTimeout(() => Notification.requestPermission(), 3000);
}

// Auto-load unified JSON editor: KAЖДЫЙ раз при открытии details + при возврате
// на вкладку Настройки если редактор уже открыт. Так что после удаления профиля
// на главной редактор покажет свежий стейт без ↻ Обновить.
(() => {
  const el = document.getElementById('json-all-details');
  if (!el) return;
  const triggerLoad = () => {
    const ta = document.getElementById('json-all-ta');
    if (!ta) return;
    if (ta.dataset.dirty === '1') return;  // не затирать ручные правки
    jsonAllLoad(el.querySelector('button'));
  };
  // open/close → refresh при каждом открытии
  el.addEventListener('toggle', function() { if (this.open) triggerLoad(); });
  // user правит → флаг dirty (сбрасывается при load/save)
  const ta = document.getElementById('json-all-ta');
  if (ta) ta.addEventListener('input', () => { ta.dataset.dirty = '1'; });
  if (el.open) triggerLoad();
})();


async function saveTelegramSettings() {
  const result = document.getElementById('tg-result');
  try {
    const values = {telegram_captcha_enabled: document.getElementById('tg-enabled').checked};
    const token = document.getElementById('tg-token').value.trim();
    const chat = document.getElementById('tg-chat').value.trim();
    if (token) values.telegram_bot_token = token;
    if (chat) values.telegram_chat_id = chat;
    for (const [key, value] of Object.entries(values)) {
      const response = await telegramPost('/api/settings', {key, value});
      if (response?.ok === false) throw new Error(response.error);
    }
    document.getElementById('tg-token').value = '';
    document.getElementById('tg-chat').value = '';
    result.textContent = 'Сохранено';
    return true;
  } catch (e) { result.textContent = 'Не удалось сохранить настройки'; return false; }
}

async function testTelegramPhoto() {
  if (!await saveTelegramSettings()) return;
  const result = document.getElementById('tg-result');
  try {
    const response = await telegramPost('/api/telegram/test', {});
    result.textContent = response.ok ? 'Фото отправлено' : response.error;
  } catch (e) { result.textContent = 'Ошибка отправки'; }
}

setInterval(() => {
  const cfg = State.lastSnapshot?.config;
  const status = document.getElementById('tg-status');
  if (!cfg || !status) return;
  status.textContent = !cfg.telegram_bot_token_set ? '⚠ токен не задан' : cfg.telegram_connected ? '🟢 подключён' : '🔴 offline';
  const stats = document.getElementById('captcha-llm-stats');
  const week = cfg.captcha_llm_week || {};
  if (stats) stats.textContent = `За 7 дней: капч ${week.challenges || 0}, решено автоматически — ${week.llm_solved || 0}`
    + ` (автопопыток: ${week.llm_attempts || 0}; остальные — вручную)`;
  const enabled = document.getElementById('tg-enabled');
  if (!enabled.dataset.initialized) {
    enabled.checked = cfg.telegram_captcha_enabled !== false;
    enabled.dataset.initialized = '1';
  }
}, 1000);

async function telegramPost(url, body) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!response.ok) throw new Error('Request failed');
  return response.json();
}


async function saveTelegramAlert(input, key) {
  const result = document.getElementById('tg-alert-result');
  try {
    const response = await telegramPost('/api/settings', {key, value: input.checked});
    if (response.ok === false) throw new Error('Save failed');
    result.textContent = 'Сохранено';
  } catch (e) {
    input.checked = !input.checked;
    result.textContent = 'Не удалось сохранить настройки';
  }
}

async function testTelegramAlerts() {
  const result = document.getElementById('tg-alert-result');
  try {
    const response = await telegramPost('/api/telegram/test', {});
    result.textContent = response.ok ? 'Тест отправлен' : 'Не удалось отправить тест';
  } catch (e) { result.textContent = 'Ошибка отправки'; }
}

setInterval(() => {
  const cfg = State.lastSnapshot?.config;
  if (!cfg) return;
  for (const name of ['interview', 'offer', 'hr_question', 'account_blocked', 'daily_limit']) {
    const input = document.getElementById(`tg-alert-${name}`);
    if (input && !input.dataset.initialized) {
      input.checked = cfg[`tg_alert_${name}_enabled`] ?? (name !== 'daily_limit');
      input.dataset.initialized = '1';
    }
  }
}, 1000);

function syncCaptchaMode(cfg) {
  const mode = document.getElementById('captcha-solve-mode');
  if (!mode || !cfg || mode.dataset.saving === '1' ||
      Date.now() < Number(mode.dataset.syncAfter || 0)) return;
  mode.value = cfg.captcha_llm_enabled === false ? 'manual' : 'local';
  updateCaptchaModeHint(mode.value);
}

function updateCaptchaModeHint(mode) {
  const hint = document.getElementById('captcha-mode-hint');
  if (!hint) return;
  hint.textContent = mode === 'manual'
    ? 'Для новых проверок бот не запускает модель. Введите текст с картинки в карточке аккаунта или в Telegram, если он включён.'
    : 'Для новых проверок локальная модель пробует решить капчу автоматически. При сложной проверке потребуется ручное решение.';
}

async function saveCaptchaMode(input) {
  const enabled = input.value === 'local';
  const resultEl = document.getElementById('captcha-mode-result');
  const previous = State.lastSnapshot?.config?.captcha_llm_enabled === false ? 'manual' : 'local';
  input.dataset.saving = '1';
  input.disabled = true;
  updateCaptchaModeHint(input.value);
  if (resultEl) resultEl.textContent = 'Сохраняю режим…';
  try {
    const result = await telegramPost('/api/settings', {key: 'captcha_llm_enabled', value: enabled});
    if (result.ok === false) throw new Error('Save failed');
    if (State.lastSnapshot?.config) State.lastSnapshot.config.captcha_llm_enabled = enabled;
    input.dataset.syncAfter = String(Date.now() + 3000);
    if (resultEl) resultEl.textContent = '✓ Режим сохранён';
  } catch (e) {
    input.value = previous;
    updateCaptchaModeHint(previous);
    if (resultEl) resultEl.textContent = 'Не удалось сохранить режим';
  } finally {
    input.disabled = false;
    delete input.dataset.saving;
  }
}

async function loadCaptchaModels() {
  const select = document.getElementById('captcha-model-select');
  const installed = document.getElementById('captcha-model-installed');
  if (!select) return;
  try {
    const response = await fetch('/api/captcha/models');
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || 'Не удалось загрузить список');
    select.replaceChildren();
    for (const model of data.models) {
      const option = document.createElement('option');
      option.value = model.name;
      option.textContent = `${model.name === 'default' ? 'Основная (уже загружена)' : model.name} (${(model.size_bytes / 1048576).toFixed(1)} МБ)`;
      select.appendChild(option);
    }
    select.value = data.active;
    const activeModel = data.models.find(model => model.name === data.active);
    if (installed) {
      installed.textContent = activeModel
        ? `✓ Загружена и активна: ${activeModel.name === 'default' ? 'Основная модель' : activeModel.name} (${(activeModel.size_bytes / 1048576).toFixed(1)} МБ). Всего моделей: ${data.models.length}.`
        : '⚠ Активная модель отсутствует. Загрузите и выберите модель.';
    }
  } catch (error) {
    if (installed) installed.textContent = error.message || 'Не удалось проверить загруженные модели';
  }
}

async function selectCaptchaModel() {
  const select = document.getElementById('captcha-model-select');
  const status = document.getElementById('captcha-model-result');
  if (!select?.value) return;
  if (status) status.textContent = 'Проверяю модель…';
  try {
    const response = await fetch('/api/captcha/models/select', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: select.value}),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || 'Не удалось выбрать модель');
    if (State.lastSnapshot?.config) State.lastSnapshot.config.captcha_model_name = data.active;
    if (status) status.textContent = `✓ Активная модель: ${data.active}`;
    await loadCaptchaModels();
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось выбрать модель';
    await loadCaptchaModels();
  }
}

async function uploadCaptchaModel() {
  const name = document.getElementById('captcha-model-name');
  const weights = document.getElementById('captcha-model-weights');
  const charset = document.getElementById('captcha-model-charset');
  const status = document.getElementById('captcha-model-result');
  if (!name?.value.trim() || !weights?.files?.length) {
    if (status) status.textContent = 'Укажите имя и выберите файл весов .pt';
    return;
  }
  const form = new FormData();
  form.append('name', name.value.trim());
  form.append('weights', weights.files[0]);
  if (charset?.files?.length) form.append('charset', charset.files[0]);
  if (status) status.textContent = 'Загружаю и проверяю модель…';
  try {
    const response = await fetch('/api/captcha/models', {method: 'POST', body: form});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || 'Не удалось загрузить модель');
    if (status) status.textContent = `✓ Модель ${data.name} загружена. Выберите её в списке и нажмите «Выбрать модель».`;
    name.value = '';
    weights.value = '';
    if (charset) charset.value = '';
    await loadCaptchaModels();
    document.getElementById('captcha-model-select').value = data.name;
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось загрузить модель';
  }
}


async function saveTelegramStatusInterval(input) {
  if (!input.reportValidity()) return;
  const result = document.getElementById('tg-alert-result');
  try {
    const response = await telegramPost('/api/settings', {key: 'telegram_status_interval_min', value: Number(input.value)});
    if (!response.ok) throw new Error('Save failed');
    document.getElementById('tg-summary-label').textContent = `раз в ${input.value} мин`;
    result.textContent = 'Сохранено';
  } catch (e) { result.textContent = 'Не удалось сохранить настройки'; }
}

(async () => {
  try {
    const response = await fetch('/api/telegram/status-settings');
    if (!response.ok) return;
    const settings = await response.json();
    document.getElementById('tg-summary-enabled').checked = settings.enabled;
    document.getElementById('tg-summary-interval').value = settings.interval_min;
    document.getElementById('tg-summary-label').textContent = `раз в ${settings.interval_min} мин`;
  } catch (e) { /* Keep defaults if offline. */ }
})();

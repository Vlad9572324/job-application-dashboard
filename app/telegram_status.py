"""Periodic Telegram summaries with persisted daily event counters."""
import asyncio
import json
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime
from functools import wraps
from html import escape
import threading
from zoneinfo import ZoneInfo

from app import human_pace, storage, telegram_notify
from app.account_activity import activity_view
from app.config import CONFIG
from app.logging_utils import log_debug

_MSK = ZoneInfo('Europe/Moscow')
_EVENTS_FILE = storage.DATA_DIR / 'telegram_status_events.json'


def install_status_tracking(bot_manager):
    """Observe existing manager log events without changing captcha handling."""
    if hasattr(bot_manager, '_telegram_status_events'):
        return
    events = {'day': datetime.now(_MSK).date(), 'accounts': defaultdict(dict)}
    try:
        saved = json.loads(_EVENTS_FILE.read_text(encoding='utf-8'))
        if saved.get('day') == events['day'].isoformat():
            events['accounts'].update(saved['accounts'])
    except (OSError, ValueError, TypeError, KeyError):
        pass
    lock = threading.Lock()
    bot_manager._telegram_status_events = events
    bot_manager._telegram_status_lock = lock
    original = bot_manager._add_log

    @wraps(original)
    def tracked(acc_short, acc_color, message, level='info', *args, **kwargs):
        original(acc_short, acc_color, message, level, *args, **kwargs)
        if level != 'error' and 'HH запросил капчу' not in message:
            return
        with lock:
            today = datetime.now(_MSK).date()
            if events['day'] != today:
                events.update(day=today, accounts=defaultdict(dict))
            account = events['accounts'][acc_short]
            if 'HH запросил капчу' in message:
                account['captcha_count'] = account.get('captcha_count', 0) + 1
            if level == 'error':
                account['errors_today'] = account.get('errors_today', 0) + 1
                account['last_error'] = message
                account['last_error_at'] = datetime.now(_MSK).isoformat(timespec='seconds')
            try:
                storage._atomic_write_json(_EVENTS_FILE, {
                    'day': today.isoformat(), 'accounts': dict(events['accounts'])})
            except OSError:
                log_debug('telegram status: cannot persist counters')
    bot_manager._add_log = tracked


ERROR_FRESH_SEC = 2 * 3600


def _challenge_pending(acc) -> bool:
    """Капча в файле challenge (источник правды для блокировки записи), даже если флаг не дошёл до state."""
    try:
        from app import captcha
        return bool(acc) and captcha.active(acc)
    except Exception:
        return False


def _fresh_error(stats, now):
    """(текст, ЧЧ:ММ) последней ошибки; старше ERROR_FRESH_SEC не показываем (раньше висела весь день)."""
    message, stamp = stats.get('last_error'), stats.get('last_error_at')
    if not message or not stamp:
        return None, None
    try:
        at = datetime.fromisoformat(stamp)
        age = (now.replace(tzinfo=None) - at.replace(tzinfo=None)).total_seconds()
    except (ValueError, TypeError):
        return None, None
    if age > ERROR_FRESH_SEC:
        return None, None
    return message, at.strftime('%H:%M')


def _captcha_mode(acc):
    try:
        from app import captcha
        record = captcha.current(acc) if acc else {}
    except Exception:
        record = {}
    reason = record.get('local_retry_reason')
    if reason in ('recaptcha', 'missing_state'):
        return ('HH запросил проверку, которую нужно открыть вручную', True, 'captcha_' + reason)
    if record.get('manual_only'):
        if record.get('auto_retry_until') and CONFIG.captcha_llm_enabled:
            return ('Картинка открыта в GUI; фоновые попытки временно приостановлены', False, 'captcha_gui')
        return ('Ожидает ручного прохождения проверки HH', True, 'captcha_manual')
    if CONFIG.captcha_llm_enabled:
        return ('Проверка обрабатывается автоматически локальной моделью', False, 'captcha_auto')
    return ('Ожидает ручного решения капчи', True, 'captcha_manual')


def _next_apply_seconds(acc) -> float | None:
    """Time until this account's next allowed apply, from durable pace storage."""
    try:
        from app import human_pace
        with human_pace._pace_lock:
            data = human_pace._pace_read()
        key = human_pace._pace_key(acc)
        record = data.get(key)
        if record is None:
            return 0.0
        next_at = record.get('next_at') if isinstance(record, dict) else float(record)
        import time as _t
        return max(0.0, float(next_at) - _t.time())
    except Exception:
        return None


def build_status_snapshot(bot_manager) -> dict:
    now = datetime.now(_MSK)
    applied = defaultdict(list)
    storage._load_cache()
    with storage._cache_lock:
        for name, records in (storage._cache_applied or {}).items():
            for record in records.values():
                try:
                    stamp = datetime.fromisoformat(record.get('at', '')).astimezone(_MSK)
                except (ValueError, TypeError):
                    continue
                applied[name].append(stamp)
    with getattr(bot_manager, '_telegram_status_lock', nullcontext()):
        events = getattr(bot_manager, '_telegram_status_events', {})
        counts = {k: dict(v) for k, v in events.get('accounts', {}).items()} if events.get('day') == now.date() else {}
    accounts = []
    errors = 0
    challenge_count = 0
    bot_paused = bool(getattr(bot_manager, 'paused', False) or CONFIG.automation_paused)
    states = list(bot_manager.account_states) + list(getattr(bot_manager, 'temp_states', {}).values())
    for state in states:
        workers = getattr(state, '_workers', None)
        stop_event = getattr(bot_manager, '_stop_event', None)
        stopped = bool((workers is not None and not any(t.is_alive() for t in workers))
                       or (stop_event is not None and stop_event.is_set()))
        # activity_view takes the account's non-reentrant lock itself.
        activity = activity_view(state, global_paused=bot_paused, stopped=stopped)
        with getattr(state, '_state_lock', nullcontext()):
            if getattr(state, '_deleted', False):
                continue
            stats = counts.get(state.short, {})
            stamps = applied[state.name]
            today = sum(stamp.date() == now.date() for stamp in stamps)
            limits = [v for v in (CONFIG.daily_apply_limit, CONFIG.hh_daily_limit) if v > 0]
            limit = min(limits) if limits else 200
            used = max(today, int(getattr(state, 'daily_sent', 0) or 0),
                       int(getattr(state, 'hh_today_applies', 0) or 0))
            remaining = max(0, limit - used)
            reserve = min(max(int(CONFIG.fresh_apply_reserve), 0), limit) if CONFIG.fresh_vacancies_mode else 0
            fresh_only = bool(reserve and 0 < remaining <= reserve)
            fresh_hours = max(1, int(CONFIG.fresh_vacancy_hours)) if CONFIG.fresh_vacancies_mode else None
            phase = activity.get('phase', '')
            observed = bool(getattr(state, 'activity', None))
            detail = activity.get('current') if observed else getattr(state, 'status_detail', '') or None
            next_step = activity.get('next') if observed else None
            wait_reason = ''
            captcha_manual_required = False
            reason = getattr(state, 'paused_reason', None)
            if stopped:
                status = '⏹ остановлен'
                wait_reason = 'stopped'
                detail, next_step = activity.get('current'), activity.get('next')
            elif getattr(state, 'pending_apply', None) or getattr(state, 'pending_applies', None) or reason in ('outcome_unknown', 'message_outcome_unknown'):
                status = '⏸ проверяет результат'
                wait_reason = reason or 'outcome_unknown'
                detail, next_step = activity.get('current'), activity.get('next')
            elif reason == 'challenge' or _challenge_pending(getattr(state, 'acc', None)):
                status = '🚫 ждёт капчу'
                challenge_count += 1
                detail, captcha_manual_required, wait_reason = _captcha_mode(getattr(state, 'acc', None))
                next_step = 'После подтверждения HH проверит ограничения и продолжит отклики'
            elif getattr(state, 'limit_exceeded', False) or reason == 'limit' or getattr(state, 'status', '') == 'limit' or used >= limit:
                status = '🔴 лимит'
                wait_reason = 'limit'
                detail = 'Дневной лимит откликов исчерпан'
                next_step = 'Дождётся обновления дневного лимита и проверит доступность откликов'
            elif bot_paused or getattr(state, 'paused', False) or getattr(state, 'hard_stopped', False) or getattr(state, '_auth_recovery_pending', False):
                status = '⏸ пауза'
                wait_reason = 'global_pause' if bot_paused else reason or 'auth_check'
                detail, next_step = activity.get('current'), activity.get('next')
                if getattr(state, '_auth_recovery_pending', False) and not bot_paused:
                    detail = 'Проверяет авторизацию HH; отклики приостановлены'
            elif human_pace.captcha_cooldown_remaining(state) > 0:
                status = '⏳ пауза после капчи'
                wait_reason = 'captcha_cooldown'
                detail = 'Ожидает завершения паузы после проверки HH'
                next_step = 'Проверит ограничения и возобновит поиск и отклики'
            elif CONFIG.human_mode_enabled and not human_pace.is_active_hour(now=now):
                status = '🌙 ждёт активного времени'
                wait_reason = 'active_hours'
                detail = f'Рабочие часы: {CONFIG.human_active_hours} (МСК)'
                next_step = 'Продолжит работу в активные часы, если остальные ограничения сняты'
            elif fresh_only and ((observed and phase in ('collect', 'filter'))
                                 or (not observed and getattr(state, 'status', '') == 'collecting')):
                status = '🔎 ищет свежие вакансии'
                wait_reason = 'fresh_reserve'
                next_step = 'Откликнется, когда найдёт подходящую свежую вакансию'
            elif fresh_only and ((observed and phase in ('fresh_reserve', 'no_new', 'cycle_wait', 'idle'))
                                 or (not observed and getattr(state, 'status', '') in ('waiting', 'idle'))):
                status = '🆕 ждёт свежие вакансии'
                wait_reason = 'fresh_reserve'
                detail = 'Старые вакансии отложены: остаток лимита сохранён для свежих'
                next_step = 'Продолжает проверять поиск; откликнется на подходящую свежую вакансию'
            elif observed and phase in ('no_new', 'cycle_wait', 'idle'):
                status = '⏳ ждёт следующего поиска'
                wait_reason = phase
            else:
                status = '🟢 работает'
                if observed and phase == 'wait_between_batches':
                    wait_reason = phase
            error_text, error_time = _fresh_error(stats, now)
            vacancy = (' / '.join(filter(None, (getattr(state, 'current_vacancy_title', ''), getattr(state, 'current_vacancy_company', ''))))
                       if status == '🟢 работает' and (not observed or phase in ('apply', 'questionnaire', 'preflight')) else '')
            acc = getattr(state, 'acc', None) or {}
            next_in = None
            if status == '🟢 работает' and observed and phase == 'wait_between_batches':
                # A reserved next_at during an in-flight apply describes the
                # following attempt. Only show the worker's actual wait here.
                try:
                    deadline = datetime.fromisoformat(activity.get('wait_until') or '')
                    if deadline.tzinfo is not None:
                        next_in = max(0.0, (deadline - now).total_seconds())
                except (TypeError, ValueError):
                    pass
            accounts.append(dict(short=state.short, state=status, applied_today=today,
                                 daily_limit=limit, hourly_rate=float(sum(0 <= (now - stamp).total_seconds() < 3600 for stamp in stamps)),
                                 current_vacancy=vacancy or None, last_error=error_text, last_error_time=error_time,
                                 captcha_count=stats.get('captcha_count', 0),
                                 next_apply_sec=next_in,
                                 detail=detail, next_step=next_step, wait_reason=wait_reason,
                                 remaining_today=remaining, daily_used=used,
                                 fresh_only=fresh_only, fresh_hours=fresh_hours, fresh_reserve=reserve,
                                 prefer_hh_signals=bool(CONFIG.prefer_hh_signals),
                                 captcha_manual_required=captcha_manual_required))
            errors += stats.get('errors_today', 0)
    if bot_paused:
        header = '⏸ Бот на паузе'
    elif challenge_count:
        header = f'🚫 Ждём решения капчи ({challenge_count})'
    elif any(a['state'] == '🟢 работает' for a in accounts):
        header = '🟢 Бот работает'
    elif any(a['state'] == '🔎 ищет свежие вакансии' for a in accounts):
        header = '🔎 Бот ищет свежие вакансии'
    elif any(a['state'] == '🆕 ждёт свежие вакансии' for a in accounts):
        header = '🆕 Бот ждёт свежие вакансии'
    elif any(a['state'] == '🌙 ждёт активного времени' for a in accounts):
        header = '🌙 Бот ждёт активного времени'
    elif any(a['state'].startswith('⏳') for a in accounts):
        header = '⏳ Бот ожидает продолжения работы'
    else:
        header = '⏸ Нет активных аккаунтов'
    return {'accounts': accounts, 'header': header,
            'bot_paused': bot_paused, 'challenge_count': challenge_count,
            'totals': {
                'applied_today': sum(a['applied_today'] for a in accounts),
                'captcha_today': sum(a['captcha_count'] for a in accounts), 'errors_today': errors}}


def _format_eta(seconds) -> str:
    if seconds is None:
        return '—'
    seconds = int(round(seconds))
    if seconds <= 0:
        return 'сейчас'
    if seconds < 60:
        return f'{seconds}с'
    if seconds < 3600:
        return f'{seconds // 60}м {seconds % 60:02d}с'
    return f'{seconds // 3600}ч {(seconds % 3600) // 60:02d}м'


def build_status_html(snapshot, previous_snapshot=None) -> str:
    header = snapshot.get('header', '📊 Свод')
    lines = [f'<b>{escape(header)}</b>',
             f'📊 Статус · интервал отчётов: {snapshot.get("interval_min", CONFIG.telegram_status_interval_min)} мин',
             '']
    for account in snapshot['accounts']:
        count, limit = account['applied_today'], account['daily_limit']
        percent = f' ({count / limit:.0%})' if limit else ''
        lines.extend([f'{account["state"]} <b>{escape(str(account["short"]))}</b>',
                      f'⏱ Отклики сегодня: {count}/{limit}{percent}',
                      f'🎯 За последний час: {account["hourly_rate"]:.0f}'])
        if account.get('daily_used', count) > count:
            lines.append(f'Учтено в дневном лимите: {account["daily_used"]}')
        if 'remaining_today' in account:
            lines.append(f'📌 Осталось сегодня: {account["remaining_today"]}')
        if account.get('fresh_only'):
            lines.append(f'🆕 Режим: только свежие вакансии — публикации за последние {account["fresh_hours"]} ч')
            lines.append('Остаток зарезервирован для свежих вакансий; старые отложены.')
        elif account.get('fresh_hours'):
            lines.append(f'🆕 Приоритет свежим публикациям за последние {account["fresh_hours"]} ч; резерв: {account["fresh_reserve"]} откликов')
        if account.get('prefer_hh_signals'):
            lines.append('Приоритет вакансиям с признаками активности работодателя по данным HH')
        if account.get('detail'):
            lines.append(f'Сейчас: {escape(str(account["detail"])[:200])}')
        if account.get('next_step'):
            lines.append(f'Далее: {escape(str(account["next_step"])[:200])}')
        if account['state'] == '🟢 работает' and account.get('next_apply_sec', 0):
            lines.append(f'⏳ Интервал перед отправкой: ещё {_format_eta(account["next_apply_sec"])}')
        if account['state'] == '🚫 ждёт капчу' and account.get('captcha_manual_required'):
            lines.append('🔐 Нужна капча — /captcha для ручного решения')
        if account.get('current_vacancy'):
            lines.append(f'🏢 Сейчас: <i>{escape(str(account["current_vacancy"])[:240])}</i>')
        lines.append(f'🤖 Капч за день: {account["captcha_count"]}')
        if account.get('last_error'):
            when = f' ({account["last_error_time"]})' if account.get('last_error_time') else ''
            lines.append(f'⚠️ {escape(str(account["last_error"]).lstrip("⚠️ ").strip()[:240])}{when}')
        lines.append('')
    total = snapshot['totals']
    lines.append(f'📈 <b>Итого за день</b>: отклики — {total["applied_today"]}, капчи — {total["captcha_today"]}, ошибки — {total["errors_today"]}')
    # send_once truncates at 4000 characters; preserve complete HTML blocks.
    while len('\n'.join(lines)) > 3900 and len(lines) > 3:
        lines.pop(-2)
    return '\n'.join(lines)


def should_send(previous, current) -> bool:
    if previous is None:
        return bool(current['accounts'])
    fields = ('short', 'state', 'applied_today', 'captcha_count', 'last_error',
              'daily_used', 'remaining_today', 'wait_reason', 'fresh_only', 'fresh_hours',
              'fresh_reserve', 'prefer_hh_signals', 'captcha_manual_required')
    signature = lambda snapshot: [tuple(a.get(k) for k in fields) for a in snapshot['accounts']]
    return signature(previous) != signature(current) or any(
        current['totals'].get(k, 0) > previous['totals'].get(k, 0)
        for k in ('captcha_today', 'errors_today'))


async def status_heartbeat(bot_manager, telegram_bot, interval_min):
    """Use send_once's persisted deduplication; telegram_bot is lifecycle context."""
    previous = None
    while True:
        await asyncio.sleep(max(10, min(120, interval_min)) * 60)
        interval_min = CONFIG.telegram_status_interval_min
        if not CONFIG.telegram_status_enabled:
            continue
        try:
            current = await asyncio.to_thread(build_status_snapshot, bot_manager)
            current['interval_min'] = max(10, min(120, interval_min))
            if should_send(previous, current):
                slot = current['interval_min'] * 60
                key = f'status:{slot}:{int(datetime.now().timestamp() // slot)}'
                sent = await asyncio.to_thread(telegram_notify.send_once, key,
                                             build_status_html(current, previous), parse_mode='HTML')
                if sent:
                    previous = current
        except Exception as exc:
            log_debug(f'telegram status: {type(exc).__name__}')

"""
Account-level CRUD and action routes.
"""

import asyncio
import json
import re
import threading
import time
from contextlib import suppress

import requests
from fastapi import APIRouter, Request

from app.logging_utils import log_debug, _is_login_page
from app.user_agent import webview_user_agent
from app.hh_http import HH
from app.config import accounts_data, save_accounts, hh_base
from app.storage import save_browser_sessions
from app.oauth import (
    _obtain_oauth_token, _oauth_touch_resume,
    _oauth_tokens, _oauth_lock, _token_key,
)
from app.llm import generate_llm_questionnaire_answers
from app.questionnaire import get_questionnaire_answer, _parse_questionnaire_rich
from app.hh_client_factory import get_client
from app.hh_resume import (
    parse_hh_lux_ssr,
    _resume_cache,
    _JOB_SEARCH_STATUSES,
)
from app.hh_negotiations import (
    fetch_similar_vacancies,
)
from app.state import AccountState
from app.config import CONFIG
from app.instances import bot


router = APIRouter()

@router.put("/api/account/{idx}/active_resume")
async def api_account_active_resume(idx: int, request: Request):
    """Switch active resume after checking account ownership."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "Некорректный JSON"}
    resume_hash = str(body.get("resume_hash") or "").strip()
    if 0 <= idx < len(bot.account_states):
        acc = bot.account_states[idx].acc
        persistent = accounts_data[idx] if idx < len(accounts_data) else acc
        saver = save_accounts
    else:
        temp_idx = idx - len(bot.account_states)
        if not (0 <= temp_idx < len(bot.temp_sessions)):
            return {"ok": False, "error": "Аккаунт не найден"}
        persistent = bot.temp_sessions[temp_idx]
        acc = bot.temp_states[temp_idx].acc if temp_idx in bot.temp_states else persistent
        saver = lambda: save_browser_sessions(bot.temp_sessions)
    allowed = {str(r.get("hash") or "") for r in persistent.get("all_resumes") or [] if isinstance(r, dict)}
    if not resume_hash or resume_hash not in allowed:
        return {"ok": False, "error": "Резюме не принадлежит аккаунту"}
    try:
        from app import message_quarantine, apply_quarantine
        message_quarantine.bind_account(acc)
        apply_quarantine.bind_account(acc)
    except (ValueError, OSError):
        return {"ok": False, "error": "Не удалось сохранить защитные блокировки перед сменой резюме"}
    persistent["resume_hash"] = resume_hash
    acc["resume_hash"] = resume_hash
    saver()
    return {"ok": True, "resume_hash": resume_hash}


# ============================================================
# COOKIE PARSING HELPERS (shared with sessions.py)
# ============================================================

# Auth cookies нужные для откликов (без трекинговых с + и =)
_AUTH_COOKIE_KEYS = {
    "hhtoken", "_xsrf", "hhul", "crypted_id", "iap.uid",
    "hhrole", "regions", "GMT", "hhuid", "crypted_hhuid",
}


def _parse_cookies_str(raw: str) -> tuple:
    """
    Парсит cURL-запрос, 'Cookie: ...' или просто 'key=val; key2=val2'.
    Возвращает (cookies_dict, raw_cookie_line).
    """
    raw = raw.strip()
    raw_line = ""

    raw = raw.encode().decode('unicode_escape', errors='replace') if '\\u00' in raw else raw

    if raw.startswith("curl "):
        # `\$?` — bash $'...' ANSI-C quoting (Firefox Copy-as-cURL для cookies с спецсимволами).
        m = re.search(r"-H\s+\$?['\"](?:C|c)ookie:\s*([^'\"]+)['\"]", raw, re.DOTALL)
        if not m:
            m = re.search(r"-b\s+\$?['\"]([^'\"]+)['\"]", raw, re.DOTALL)
        if not m:
            m = re.search(r"--cookie\s+\$?['\"]([^'\"]+)['\"]", raw, re.DOTALL)
        if m:
            raw_line = m.group(1).strip()
        else:
            return {}, ""
    elif raw.lower().startswith("cookie:"):
        raw_line = raw[7:].strip()
    else:
        raw_line = raw

    # bash $'...' декодирует \NNN (octal), \xNN, \n и т.д. — повторяем то же.
    # Firefox Copy-as-cURL генерит $'...' когда cookie содержит спецсимволы (например ! → \041).
    if "\\" in raw_line:
        try:
            raw_line = raw_line.encode("utf-8").decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

    cookies: dict = {}
    for part in raw_line.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            # Stripping NUL и control chars (CRLF) — иначе header injection
            # или requests/http.client крашится навсегда на этой сессии (kimi-search-3 #5,#8).
            k = k.strip()
            v = "".join(ch for ch in v.strip() if ch == "\t" or 0x20 <= ord(ch) < 0x7f or ord(ch) >= 0xa0)
            # Если после strip значение пустое — не добавляем,
            # иначе downstream `hhtoken in cookies` проходит, а реально auth-token нет (r10-1 #4,#9).
            if not v:
                continue
            cookies[k] = v

    return cookies, raw_line


# ============================================================
# ACCOUNT TOGGLES
# ============================================================


@router.get('/api/account/{idx}/captcha')
async def api_account_captcha(idx: int):
    from app import captcha
    state = bot._get_apply_state(idx)
    if state is None:
        return {'ok': False, 'error': 'Аккаунт не найден'}
    try:
        record = captcha.current(state.acc)
    except (ValueError, OSError):
        return {'ok': False, 'error': 'Не удалось прочитать данные проверки'}
    if not record:
        return {'ok': False, 'error': 'Ссылка проверки не сохранена. Не снимайте паузу вслепую.'}
    return {'ok': True, 'id': record['id'], 'url': captcha.browser_url(record),
            'has_direct_link': bool(record.get('captcha_url') or record.get('fallback_url'))}


@router.get('/api/account/{idx}/captcha/image')
async def api_account_captcha_image(idx: int):
    coord = getattr(bot, 'telegram_captcha_coordinator', None)
    if coord is None:
        return {'ok': False, 'error': 'Проверка недоступна. Откройте оригинальную ссылку HH.'}
    async with coord._lock:
        return await _captcha_image_locked(idx)


async def _captcha_image_locked(idx: int):
    """Return current captcha image bytes (PNG) for in-UI solving."""
    from app import captcha
    from app.captcha_solver import fetch_captcha_image
    from fastapi.responses import Response as _Resp
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    import secrets
    state = bot._get_apply_state(idx)
    if state is None:
        return {'ok': False, 'error': 'Аккаунт не найден'}
    record = captcha.current(state.acc)
    if not record:
        return {'ok': False, 'error': 'Нет активной капчи'}
    remaining = max(0, int(record.get('local_retry_at', 0) - time.time() + 1))
    if record.get('local_retry_reason') == 'http_429' and remaining:
        return {'ok': False, 'retry_seconds': remaining,
                'error': f'HH ограничил запросы. Следующая попытка через {remaining} сек.'}
    coord = getattr(bot, 'telegram_captcha_coordinator', None)
    cid = record['id']
    # GUI sessions are separate: refreshing here must not replace Telegram's image.
    if not hasattr(coord, 'gui_pending'):
        coord.gui_pending = {}
    url = captcha.browser_url(record)
    if not url:
        return {'ok': False, 'error': 'Ссылка проверки не сохранена. Откройте карточку аккаунта.'}
    # Only a per-attempt redirect is proof, not an arbitrary redirect to HH home.
    backurl = 'https://hh.ru/?manual_captcha_return=' + secrets.token_hex(16)
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != 'backurl']
    query.append(('backurl', backurl))
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    try:
        captcha.claim_manual(state.acc, cid,
                             auto_retry_after=120 if CONFIG.captcha_llm_enabled else None)
        fetch = asyncio.create_task(asyncio.to_thread(fetch_captcha_image, state.acc, url))
        try:
            session, key, image, state_val, backurl = await asyncio.shield(fetch)
        except asyncio.CancelledError:
            def close_fetched(done):
                if not done.cancelled():
                    with suppress(Exception):
                        done.result()[0].close()
            fetch.add_done_callback(close_fetched)
            raise
    except Exception as e:
        return {'ok': False, 'error': f'Не удалось загрузить капчу: {type(e).__name__}'}
    if (getattr(state, '_deleted', False) or captcha.current(state.acc).get('id') != cid
            or bot.telegram_captcha_coordinator is not coord):
        session.close()
        return {'ok': False, 'error': 'Проверка изменилась. Обновите страницу.'}
    captcha.update_challenge_state(state.acc, cid, state_val)
    # Preserve the old usable image/session if replacement fails.
    old = coord.gui_pending.pop(cid, None)
    if old and old.get('session') is not None:
        old['session'].close()
    # Сохраняем в coordinator чтобы submit прошёл в той же session
    if coord:
        coord.gui_pending[cid] = dict(
                                  acc_key=captcha.account_key(state.acc),
                                  captcha_state=state_val, backurl=backurl,
                                  failurl=url, url=url,
                                  created=time.monotonic(), submitted=False,
                                  fails=0, captcha_key=key, session=session,
                                  challenge_url=url, image=image)
    return _Resp(content=image, media_type='image/png',
                 headers={'Cache-Control': 'no-store', 'X-Captcha-Id': cid, 'X-Captcha-Key': key})


@router.post('/api/account/{idx}/captcha/solve')
async def api_account_captcha_solve(idx: int, request: Request):
    coord = getattr(bot, 'telegram_captcha_coordinator', None)
    if coord is None:
        return {'ok': False, 'error': 'Сессия проверки потеряна. Обновите картинку.'}
    async with coord._lock:
        return await _captcha_solve_locked(idx, request)


@router.post('/api/account/{idx}/captcha/solve-local')
async def api_account_captcha_solve_local(idx: int, request: Request):
    """Try the already displayed image with the local model, once."""
    from app import captcha
    from app.captcha_llm import recognize_captcha
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return {'ok': False, 'error': 'Некорректный запрос'}
    if not isinstance(body, dict):
        return {'ok': False, 'error': 'Некорректный запрос'}
    coord = getattr(bot, 'telegram_captcha_coordinator', None)
    if coord is None:
        return {'ok': False, 'error': 'Обработчик капчи недоступен'}
    async with coord._lock:
        state = bot._get_apply_state(idx)
        if state is None or getattr(state, '_deleted', False):
            return {'ok': False, 'error': 'Аккаунт недоступен'}
        record = captcha.current(state.acc)
        cid = record.get('id')
        item = getattr(coord, 'gui_pending', {}).get(cid)
        if (not cid or not item or not item.get('session') or not item.get('captcha_key')
                or body.get('id') != cid or body.get('key') != item['captcha_key']
                or item.get('submitted') or time.monotonic() - item.get('created', 0) > 600):
            return {'ok': False, 'error': 'Откройте свежую картинку капчи'}
        if item.get('local_attempted'):
            return {'ok': False, 'manual_available': True,
                    'error': 'Модель уже проверяла эту картинку. Введите ответ вручную.'}
        item['local_attempted'] = True
        answer = await asyncio.to_thread(recognize_captcha, item.get('image'))
        if (getattr(state, '_deleted', False) or captcha.current(state.acc).get('id') != cid
                or bot.telegram_captcha_coordinator is not coord
                or coord.gui_pending.get(cid) is not item):
            return {'ok': False, 'refresh_needed': True,
                    'error': 'Проверка изменилась. Обновите страницу.'}
        if not answer:
            if CONFIG.captcha_llm_enabled:
                return _queue_local_captcha_retry(state.acc, cid, item, coord,
                                                  {'ok': False, 'reason': 'unsure'})
            return {'ok': False, 'manual_available': True,
                    'error': 'Модель не смогла прочитать картинку. Введите ответ вручную.'}
        result = await _captcha_solve_locked(idx, request, answer_body={**body, 'text': answer},
                                             source='local', auto_resume=True)
        result['answer'] = answer
        if (not result['ok'] and 'auto_retry' not in result and CONFIG.captcha_llm_enabled
                and bot.telegram_captcha_coordinator is coord
                and coord.gui_pending.get(cid) is item and not getattr(state, '_deleted', False)
                and captcha.current(state.acc).get('id') == cid):
            return _queue_local_captcha_retry(state.acc, cid, item, coord, result)
        return result


def _queue_local_captcha_retry(acc, cid, item, coord, result):
    """Release a consumed GUI image and retry only with a fresh image/key."""
    from app import captcha
    from urllib.parse import parse_qs, urlsplit
    reason = result.get('reason', 'unconfirmed_transport')
    attempt = int(captcha.current(acc).get('local_attempts', 0)) + 1
    retry_after = item.get('retry_after', getattr(item.get('session'), 'hh_captcha_retry_after', 0))
    retry_after = retry_after if isinstance(retry_after, (int, float)) else 0
    delay = (max(60, retry_after) if reason == 'http_429' else
             min(60, 5 * 2 ** min(attempt - 1, 4)) if reason == 'isBot' else 30)
    item['submitted'] = True
    # An unreadable image has no submitted POST to close its session for us.
    if reason == 'unsure':
        with suppress(Exception):
            item['session'].close()
    with captcha.LOCK:
        if (not captcha.set_local_retry(acc, cid, delay, reason, attempt)
                or not captcha.release_manual(acc, cid)):
            return {**result, 'auto_retry': False, 'refresh_needed': True,
                    'error': 'Проверка изменилась. Обновите страницу.'}
        record = captcha.current(acc)
        pending = getattr(coord, 'pending', {}).pop(cid, None)
        session = item.get('session')
        if pending and pending.get('session') is not session:
            with suppress(Exception):
                pending.get('session').close()
        if reason == 'isBot' and CONFIG.captcha_llm_enabled and session is not None:
            url = captcha.browser_url(record)
            query = parse_qs(urlsplit(url).query)
            # Transfer only the cookie jar and challenge context. The worker
            # must request a fresh key/image before recognizing another answer.
            coord.pending[cid] = dict(
                acc_key=captcha.account_key(acc), automatic=True, session=session,
                captcha_key=None, captcha_state=query.get('state', [item['captcha_state']])[0],
                backurl=item['backurl'], challenge_url=url, fails=0,
                session_started=item.get('created', time.monotonic()),
                llm_result={'status': 'retry', 'reason': reason,
                            'retry_seconds': delay, 'answer': result.get('answer', '')})
            item['session'] = None
            item['captcha_key'] = None
    if hasattr(coord, '_seen'):
        coord._seen.discard(cid)
    if reason == 'recaptcha':
        return {**result, 'auto_retry': False,
                'error': 'HH запросил reCAPTCHA. Локальная модель читает текстовые картинки; эту проверку нужно открыть на HH.'}
    detail = ('HH ограничил запросы.' if reason == 'http_429' else
              'Модель не смогла прочитать картинку.' if reason == 'unsure' else
              'HH не принял ответ.' if reason == 'isBot' else 'HH не подтвердил результат.')
    return {**result, 'auto_retry': True, 'retry_seconds': delay,
            'error': f'{detail} Локальная модель попробует новую картинку через {int(delay)} сек.'}


async def _captcha_solve_locked(idx: int, request: Request, *, answer_body=None,
                                source='dashboard', auto_resume=False):
    """Submit user's captcha answer from the dashboard. Body: {"text": "..."}"""
    from app import captcha
    from app.captcha_solver import captcha_submit_delay, submit_captcha, verify_manual_completion
    state = bot._get_apply_state(idx)
    if state is None:
        return {'ok': False, 'error': 'Аккаунт не найден'}
    try:
        body = answer_body if answer_body is not None else await request.json()
    except Exception:
        return {'ok': False, 'error': 'bad json'}
    if not isinstance(body, dict) or not isinstance(body.get('text'), str):
        return {'ok': False, 'error': 'Некорректный ответ'}
    text = body['text'].strip()
    if not text or len(text) > 256:
        return {'ok': False, 'error': 'Введите текст с картинки'}
    record = captcha.current(state.acc)
    if not record:
        return {'ok': False, 'error': 'Капча уже решена или отсутствует'}
    coord = getattr(bot, 'telegram_captcha_coordinator', None)
    cid = record['id']
    item = getattr(coord, 'gui_pending', {}).get(cid) if coord else None
    if (not item or item.get('session') is None or not item.get('captcha_key')
            or body.get('id') != cid or body.get('key') != item['captcha_key']
            or item.get('submitted') or time.monotonic() - item.get('created', 0) > 600
            or getattr(state, '_deleted', False)):
        return {'ok': False, 'error': 'Картинка устарела. Обновите её и введите ответ заново.'}
    if source != 'local':
        captcha.claim_manual(state.acc, cid)
    item['submitted'] = True  # Consume before I/O: timeout must never replay a POST.
    local_enabled_at_start = CONFIG.captcha_llm_enabled
    session = item['session']
    item['session'] = None  # A shutdown/refresh must not close an in-flight POST.
    def submit_once(active_session=session):
        result = submit_captcha(active_session, text, item['captcha_key'],
            item['captcha_state'], item['backurl'], item['failurl'], require_confirmation=True)
        if not result[0] and result[1].startswith('unconfirmed'):
            return verify_manual_completion(active_session, item['challenge_url'], item['backurl'])
        return result
    try:
        delay = captcha_submit_delay(session)
        if delay > 0:
            await asyncio.sleep(delay)
        # Settings and challenge ownership may change while the answer waits.
        # Explicit local clicks remain valid with auto-solving already disabled.
        if (getattr(state, '_deleted', False) or captcha.current(state.acc).get('id') != cid
                or bot.telegram_captcha_coordinator is not coord
                or coord.gui_pending.get(cid) is not item
                or time.monotonic() - item.get('created', 0) > 600
                or (source == 'local' and CONFIG.captcha_llm_enabled != local_enabled_at_start)):
            return {'ok': False, 'auto_retry': False, 'refresh_needed': True,
                    'error': 'Проверка или настройки изменились. Загрузите свежую картинку.'}
        try:
            work = asyncio.create_task(asyncio.to_thread(submit_once))
            try:
                ok, reason = await asyncio.shield(work)
            except asyncio.CancelledError:
                # The thread still owns the session until its POST finishes.
                coord.gui_pending.pop(cid, None)
                active_session = session
                def close_submitted(done):
                    with suppress(BaseException):
                        done.exception()
                    with suppress(Exception):
                        active_session.close()
                work.add_done_callback(close_submitted)
                session = None
                raise
        except Exception:
            ok, reason = False, 'unconfirmed_transport'
        item['retry_after'] = getattr(session, 'hh_captcha_retry_after', 0)
        if not ok:
            captcha.update_challenge_state(state.acc, cid,
                getattr(session, 'hh_captcha_next_state', None))
        from app.captcha_journal import record as journal
        sample = None
        if ok:
            from app.captcha_journal import save_sample
            sample = save_sample(item.get('image'), text, source='local' if source == 'local' else 'gui')
        elif source == 'local':
            from app.captcha_journal import save_sample
            sample = save_sample(item.get('image'), text, kind='local-rejected', source='local')
        journal('solve', state.acc, path=source, ok=ok, reason=reason or None, id=cid,
                answer=text, sample=sample,
                diagnostic=getattr(session, 'hh_captcha_diagnostic', None))
        if (getattr(state, '_deleted', False) or captcha.current(state.acc).get('id') != cid
                or bot.telegram_captcha_coordinator is not coord
                or coord.gui_pending.get(cid) is not item):
            return {'ok': False, 'refresh_needed': True,
                    'error': 'Проверка изменилась. Результат старой проверки не используется.'}
        if ok:
            item['confirmed'] = True
            if auto_resume:
                captcha.clear(state.acc, cid)
                coord.gui_pending.pop(cid, None)
                CONFIG.captcha_llm_solved += 1
                await asyncio.to_thread(bot.resume_challenge_account, captcha.account_key(state.acc))
                return {'ok': True, 'confirmed': True, 'id': cid, 'answer': text,
                        'message': 'Капча решена локальной моделью. Отклики возобновляются.'}
            return {'ok': True, 'confirmed': True, 'requires_confirmation': True, 'id': cid,
                    'message': 'HH подтвердил ответ. Отклики на паузе — подтвердите продолжение отдельно.'}
        if reason.startswith('unconfirmed'):
            return {'ok': False, 'unconfirmed': True, 'reason': reason,
                    'refresh_needed': True,
                    'diagnostic': getattr(session, 'hh_captcha_diagnostic', {}),
                    'error': 'HH не дал однозначного подтверждения. Это не означает неверный ответ. Откройте оригинальную проверку HH; пауза сохранена.'}
        message = ('HH не принял ответ. Обновите картинку.' if reason == 'isBot' else
                   'HH запросил другой вид проверки. Откройте оригинальную страницу.' if reason == 'recaptcha' else
                   'HH ограничил запросы. Не повторяйте их сейчас.' if reason == 'http_429' else
                   'Ошибка связи с HH. Результат не подтверждён.')
        result = {'ok': False, 'reason': reason, 'error': message + ' Пауза сохранена.',
                  'refresh_needed': reason != 'http_429'}
        if source == 'local' and CONFIG.captcha_llm_enabled and reason == 'isBot':
            result['answer'] = text
            item['session'] = session
            return _queue_local_captcha_retry(state.acc, cid, item, coord, result)
        return result
    finally:
        # A rejected local answer can transfer ownership to the worker. Every
        # other completed/failed/superseded GUI request closes its session here.
        owner = getattr(coord, 'pending', {}).get(cid, {})
        if session is not None and owner.get('session') is not session:
            with suppress(Exception):
                session.close()
            if item.get('session') is session:
                item['session'] = None


@router.get('/api/captcha/journal')
async def api_captcha_journal(days: int = 7):
    from app.captcha_journal import summary
    return summary(max(1, min(days, 60)))


@router.get('/api/captcha/attempts')
def api_captcha_attempts(limit: int = 20):
    from app.captcha_history import list_attempts
    return {'ok': True, 'attempts': list_attempts(limit)}


@router.get('/api/captcha/samples/{filename}')
def api_captcha_sample(filename: str):
    from app.captcha_history import sample_path
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    try:
        path = sample_path(filename)
    except ValueError:
        raise HTTPException(status_code=404, detail='Образец капчи не найден')
    return FileResponse(path, media_type='image/png', headers={
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/api/account/{idx}/captcha/refresh')
async def api_account_captcha_refresh(idx: int):
    """One read-only API probe; never resumes or sends an application."""
    from app import captcha
    from app.oauth import _oauth_headers, _token_key
    state = bot._get_apply_state(idx)
    if state is None:
        return {'ok': False, 'error': 'Аккаунт не найден'}
    with state._state_lock:
        if state._deleted or not state.paused or state.paused_reason != 'challenge':
            return {'ok': False, 'error': 'Состояние аккаунта изменилось'}
        now = time.monotonic()
        if now < getattr(state, '_captcha_probe_after', 0):
            return {'ok': False, 'error': 'Повторная проверка доступна через 10 секунд'}
        state._captcha_probe_after = now + 10
        expected_id = captcha.current(state.acc).get('id')
    def probe():
        headers = _oauth_headers(state.acc)
        if not headers:
            return {'ok': False, 'error': 'API-токен недоступен. Пауза сохранена.'}
        response = HH.get('https://api.hh.ru/me', headers=headers,
                          cookie_jar_key=_token_key(state.acc) or None, timeout=15)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        with state._state_lock, captcha.LOCK:
            if state._deleted or captcha.current(state.acc).get('id') != expected_id:
                return {'ok': False, 'error': 'Проверка изменилась во время запроса. Обновите карточку.'}
            details = captcha.capture(state.acc, response.status_code, payload)
            replaced = captcha.current(state.acc).get('id') != expected_id
        return {'ok': True, 'probe_status': response.status_code,
                'challenge_received': bool(details), 'challenge_replaced': replaced,
                'message': ('HH выдал новую проверку. Локальная модель обработает её автоматически.'
                            if replaced and CONFIG.captcha_llm_enabled else
                            'Проверка API выполнена без отклика. Пауза сохранена; успешный ответ не подтверждает снятие капчи.')}
    try:
        return await asyncio.to_thread(probe)
    except Exception:
        return {'ok': False, 'error': 'Не удалось проверить API. Пауза сохранена.'}


@router.post('/api/account/{idx}/captcha/continue')
async def api_account_captcha_continue(idx: int, request: Request):
    """Explicit HUMAN confirmation, not server-side proof that CAPTCHA passed."""
    from app import captcha
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return {'ok': False, 'error': 'Некорректный JSON'}
    if not isinstance(body, dict) or body.get('confirmed') is not True:
        return {'ok': False, 'error': 'Подтвердите ручное прохождение проверки HH'}
    state = bot._get_apply_state(idx)
    if state is None:
        return {'ok': False, 'error': 'Аккаунт не найден'}
    with state._state_lock:
        # Капча может быть только в файле (создана другим процессом/до рестарта), а аккаунт в
        # памяти — не на паузе: тогда подтверждение человека всё равно должно её снять.
        challenge_pause = state.paused and state.paused_reason == 'challenge'
        orphan_challenge = not state.paused and not state.paused_reason
        if (state._deleted or not (challenge_pause or orphan_challenge)
                or state.pending_apply or state.pending_applies or state.hard_stopped
                or state.limit_exceeded or state.cookies_expired
                or getattr(state, '_auth_recovery_pending', False)):
            return {'ok': False, 'error': 'Есть другая защитная пауза или состояние изменилось'}
        try:
            record = captcha.current(state.acc)
            if not record or record.get('id') != body.get('id'):
                return {'ok': False, 'error': 'Проверка изменилась. Откройте актуальную ссылку.'}
            if not captcha.browser_url(record):
                return {'ok': False, 'error': 'Нет персональной ссылки: прохождение проверки не подтверждено. Пауза сохранена.'}
            state._auth_recovery_pending = True
            captcha.clear(state.acc, record['id'])
            state.paused = False
            state.paused_reason = ''
            state.consecutive_errors = 0
        except (ValueError, OSError):
            state._auth_recovery_pending = False
            return {'ok': False, 'error': 'Не удалось сохранить подтверждение'}
    try:
        bot._persist_pauses(wait=True)
    except Exception:
        with state._state_lock:
            state.paused = True
            state.paused_reason = 'challenge'
        captcha.hold(state.acc, record)
        return {'ok': False, 'error': 'Ошибка сохранения. Отправки остаются остановленными.'}
    finally:
        state._auth_recovery_pending = False
    from app.captcha_journal import record as journal
    journal('resume', state.acc, path='confirm', id=record.get('id'))
    try:
        tg = getattr(bot, 'telegram_captcha_bot', None)
        if tg is not None:
            short = state.acc.get('short') or state.acc.get('name') or 'аккаунт'
            asyncio.create_task(tg.send_message(
                f'✅ Капча HH пройдена (подтверждено вручную) для {short} — отклики возобновлены'))
    except Exception:
        pass
    return {'ok': True, 'message': 'Продолжение разрешено вами. Если HH снова потребует капчу, отправки остановятся.'}

@router.post("/api/account/{idx}/pause")
async def api_account_pause(idx: int):
    bot.toggle_account_pause(idx)
    if 0 <= idx < len(bot.account_states):
        paused = bot.account_states[idx].paused
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
        paused = s.paused if s else False
    return {"paused": paused}


@router.post("/api/account/{idx}/llm_toggle")
async def api_account_llm_toggle(idx: int):
    bot.toggle_account_llm(idx)
    if 0 <= idx < len(bot.account_states):
        enabled = bot.account_states[idx].llm_enabled
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
        enabled = s.llm_enabled if s else True
    return {"llm_enabled": enabled}


@router.post("/api/account/{idx}/resume_touch")
async def api_resume_touch(idx: int):
    bot.trigger_resume_touch(idx)
    return {"ok": True}


@router.get("/api/account/{idx}/diagnostics")
async def api_account_diagnostics(idx: int):
    """Прогнать диагностику аккаунта: jobSearchStatus, видимость резюме,
    статистика, red flags. Делает один GET на /applicant/resumes — кэширования
    нет, всегда свежие данные.
    """
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    import asyncio as _aio
    client = get_client(acc)  # до executor: выбор клиента синхронный
    data = await _aio.get_event_loop().run_in_executor(None, client.fetch_account_diagnostics)
    data["ok"] = True
    data["available_statuses"] = _JOB_SEARCH_STATUSES
    return data


@router.get("/api/vacancy/{vacancy_id}/similar")
async def api_similar_vacancies(vacancy_id: int, page: int = 0, per_page: int = 20):
    """Похожие вакансии через официальный api.hh.ru без OAuth.
    HH знает что 134438591 → похоже на 36686 других. Дополнительный пул
    для бота + UI «откликнуться к похожим». Кэш 6ч."""
    import asyncio as _aio
    out = await _aio.get_event_loop().run_in_executor(
        None, fetch_similar_vacancies, vacancy_id, page, per_page
    )
    return out


@router.get("/api/account/{idx}/rating_by_vacancy/{vacancy_id}")
async def api_rating_by_vacancy(idx: int, vacancy_id: int):
    """Rating + politeness + HR online через цепочку vacancy_id → employer_id.
    Все шаги кэшированы (7д vac→emp, 24ч emp→rating, 1ч politeness/activity).
    """
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    import asyncio as _aio
    loop = _aio.get_event_loop()
    client = get_client(acc)  # до executor: выбор клиента синхронный

    # Параллельно: vac→emp, vac→HR, neg-метаданные (politeness + activity).
    eid_task   = loop.run_in_executor(None, client.fetch_employer_id_for_vacancy, vacancy_id)
    hr_task    = loop.run_in_executor(None, client.fetch_vacancy_owner_hr_hhid, vacancy_id)
    meta_task  = loop.run_in_executor(None, client.fetch_negotiations_metadata)
    eid, hr_hhid, meta = await _aio.gather(eid_task, hr_task, meta_task)

    if not eid:
        return {"ok": False, "error": "Не удалось определить работодателя"}
    rating = await loop.run_in_executor(None, client.fetch_employer_rating, eid)
    out = {"ok": True}
    if rating:
        out.update(rating)
    politeness = (meta.get("politeness") or {}).get(int(eid))
    if politeness:
        out["politeness"] = politeness
    if hr_hhid:
        activity = (meta.get("activity") or {}).get(int(hr_hhid))
        if activity:
            out["hr_activity"] = activity
            out["hr_hhid"] = hr_hhid
    # Per-topic статус: видел ли HR наш отклик, сколько непрочитанных,
    # last_state (DISCARD/INVITE/RESPONSE), etc.
    topic = (meta.get("topics_by_vid") or {}).get(str(vacancy_id))
    if topic:
        out["topic"] = topic
    if not rating and "politeness" not in out and "hr_activity" not in out and "topic" not in out:
        return {"ok": False, "error": "Ни рейтинга, ни metadata для этого работодателя"}
    return out


@router.get("/api/account/{idx}/employer_rating/{employer_id}")
async def api_employer_rating(idx: int, employer_id: int):
    """Получить рейтинг работодателя по employerId через cookies аккаунта.
    Возвращает {total, recommend_pct, ratings, advantages, reviews_count,
    neg_count, staff_count, status, is_open} или {ok:False} если закрытый.
    """
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    import asyncio as _aio
    client = get_client(acc)  # до executor: выбор клиента синхронный
    rating = await _aio.get_event_loop().run_in_executor(None, client.fetch_employer_rating, employer_id)
    if rating is None:
        return {"ok": False, "error": "Работодатель не имеет отзывов или закрыт"}
    return {"ok": True, **rating}


@router.post("/api/account/{idx}/job_status")
async def api_set_job_status(idx: int, request: Request):
    """Сменить публичный статус поиска работы.
    Body: {"status": "active_search"}. Допустимые значения см. диагностику.
    """
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
    status = str(body.get("status", "")).strip().lower()
    import asyncio as _aio
    client = get_client(acc)  # до executor: выбор клиента синхронный
    result = await _aio.get_event_loop().run_in_executor(None, client.set_job_search_status, status)
    if result.get("ok"):
        # лог в боте для аудита
        state = bot._get_apply_state(idx)
        if state:
            bot._add_log(state.short, state.color,
                         f"🟢 Статус поиска работы изменён → {result.get('label','?')}", "success")
    return result


@router.post("/api/account/{idx}/resume_touch_toggle")
async def api_resume_touch_toggle(idx: int):
    enabled = bot.toggle_resume_touch(idx)
    return {"ok": True, "enabled": enabled}


@router.post("/api/account/{idx}/set_urls")
async def api_set_urls(idx: int, request: Request):
    """Обновить список поисковых URL аккаунта (regular или browser-сессия).
    Если idx стал stale (после удаления/рестарта), пробуем найти аккаунт
    по short/name из body — иначе фронт получает «Аккаунт не найден» и
    юзер вынужден жать F5 (GitHub: «не видит URL поиска»)."""
    body = await request.json()
    urls = [u.strip() for u in body.get("urls", []) if u.strip()]
    url_pages = {}
    for k, v in body.get("url_pages", {}).items():
        try:
            url_pages[k] = int(v) if v else 0
        except (ValueError, TypeError):
            pass
    fallback_short = (body.get("short") or "").strip()
    fallback_name = (body.get("name") or "").strip()

    def _apply_regular(i: int) -> dict:
        bot.account_states[i].acc["urls"] = urls
        bot.account_states[i].acc["url_pages"] = url_pages
        bot.account_states[i].total_urls = len(urls)
        if 0 <= i < len(accounts_data):
            accounts_data[i]["urls"] = urls
            accounts_data[i]["url_pages"] = url_pages
            save_accounts()
        return {"ok": True, "count": len(urls), "matched": "regular", "idx": i}

    def _apply_temp(ti: int) -> dict:
        bot.temp_sessions[ti]["urls"] = urls
        bot.temp_sessions[ti]["url_pages"] = url_pages
        if ti in bot.temp_states:
            bot.temp_states[ti].acc["urls"] = urls
            bot.temp_states[ti].acc["url_pages"] = url_pages
            bot.temp_states[ti].total_urls = len(urls)
        save_browser_sessions(bot.temp_sessions)
        return {"ok": True, "count": len(urls), "matched": "temp", "temp_idx": ti}

    # 1. Strict idx match — regular
    if 0 <= idx < len(bot.account_states):
        return _apply_regular(idx)
    # 2. Strict idx match — temp
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        return _apply_temp(temp_idx)
    # 3. Fallback: match by short/name (frontend snapshot was stale after
    #    a deletion or restart — idx no longer aligns but the card belongs
    #    to a real account).
    if fallback_short or fallback_name:
        for i, state in enumerate(bot.account_states):
            acc = state.acc
            if (fallback_short and acc.get("short") == fallback_short) or \
               (fallback_name and acc.get("name") == fallback_name):
                log_debug(f"set_urls: stale idx={idx} → matched regular[{i}] by short/name")
                return _apply_regular(i)
        for ti, ts in enumerate(bot.temp_sessions):
            if (fallback_short and ts.get("short") == fallback_short) or \
               (fallback_name and ts.get("name") == fallback_name):
                log_debug(f"set_urls: stale idx={idx} → matched temp[{ti}] by short/name")
                return _apply_temp(ti)
    return {
        "ok": False,
        "error": "Аккаунт не найден",
        "hint": "Обнови страницу (Ctrl+F5) — индекс карточки устарел.",
    }


@router.post("/api/account/{idx}/set_letter")
async def api_set_letter(idx: int, request: Request):
    """Обновить письмо аккаунта в памяти."""
    body = await request.json()
    letter = body.get("letter", "")
    if 0 <= idx < len(bot.account_states):
        bot.account_states[idx].acc["letter"] = letter
        if 0 <= idx < len(accounts_data):
            accounts_data[idx]["letter"] = letter
            save_accounts()
        return {"ok": True}
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        bot.temp_sessions[temp_idx]["letter"] = letter
        if temp_idx in bot.temp_states:
            bot.temp_states[temp_idx].acc["letter"] = letter
        save_browser_sessions(bot.temp_sessions)
        return {"ok": True}
    return {"ok": False, "error": "Аккаунт не найден"}


@router.post("/api/account/{idx}/update_cookies")
async def api_update_cookies(idx: int, body: dict):
    """Обновить куки аккаунта в памяти без перезапуска."""
    raw = body.get("cookies", "").strip()
    if not raw:
        return {"ok": False, "error": "Строка cookies пустая"}

    cookies, raw_line = _parse_cookies_str(raw)

    if not cookies:
        return {"ok": False, "error": "Не удалось распознать cookies — вставьте cURL или строку cookie: ..."}
    if "hhtoken" not in cookies:
        return {"ok": False, "error": "Не найден hhtoken"}
    if "_xsrf" not in cookies:
        return {"ok": False, "error": "Не найден _xsrf"}

    if 0 <= idx < len(bot.account_states):
        state = bot.account_states[idx]
        auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
        # Аудит 2026-08-17 #33: раньше replace без _cookies_lock — если
        # фоновый chat/auth worker в этот момент делал compound cookie refresh
        # (get+merge+set), одна из сторон затирала обновление другой.
        with state._cookies_lock:
            state.acc["cookies"] = auth_cookies
            state.acc["_raw_cookie_line"] = raw_line
            state.cookies_expired = False
            # Сбрасываем degraded одновременно — иначе UI ещё цикл (~2 мин)
            # показывает «⚠️ Degraded» с только что обновлёнными куками, и apply
            # без нужды жмётся к OAuth-only пути.
            state.degraded_mode = False
        if 0 <= idx < len(accounts_data):
            accounts_data[idx]["cookies"] = auth_cookies
            save_accounts()
        log_debug(f"update_cookies [{state.name}]: обновлены куки ({len(auth_cookies)} ключей)")
        return {"ok": True, "name": state.name, "keys": list(auth_cookies.keys())}

    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
        bot.temp_sessions[temp_idx]["cookies"] = auth_cookies
        bot.temp_sessions[temp_idx]["_raw_cookie_line"] = raw_line
        if temp_idx in bot.temp_states:
            tstate = bot.temp_states[temp_idx]
            with tstate._cookies_lock:
                tstate.acc["cookies"] = auth_cookies
                tstate.cookies_expired = False
        save_browser_sessions(bot.temp_sessions)
        name = bot.temp_sessions[temp_idx].get("name", f"Браузер #{temp_idx+1}")
        log_debug(f"update_cookies [temp {temp_idx}] {name}: обновлены куки ({len(auth_cookies)} ключей)")
        return {"ok": True, "name": name, "keys": list(auth_cookies.keys())}

    return {"ok": False, "error": "Аккаунт не найден"}


@router.post("/api/account/{idx}/profile")
async def api_account_profile(idx: int, request: Request):
    """Обновить профиль основного аккаунта (name, short, color, resume_hash)."""
    body = await request.json()
    if not (0 <= idx < len(accounts_data)):
        return {"ok": False, "error": "Аккаунт не найден"}
    acc = accounts_data[idx]
    for field in ("name", "short", "color", "resume_hash"):
        if field in body and isinstance(body[field], str) and body[field].strip():
            acc[field] = body[field].strip()
    if 0 <= idx < len(bot.account_states):
        state = bot.account_states[idx]
        state.name = acc.get("name", state.name)
        state.short = acc.get("short", state.short)
        state.color = acc.get("color", state.color)
    save_accounts()
    return {"ok": True}


@router.post("/api/accounts/add")
async def api_account_add(request: Request):
    """Добавить новый основной аккаунт."""
    body = await request.json()
    name = body.get("name", "").strip()
    short = body.get("short", "").strip()
    color = body.get("color", "cyan").strip()
    resume_hash = body.get("resume_hash", "").strip()
    cookies_str = body.get("cookies", "").strip()
    letter = body.get("letter", "").strip()

    if not name or not resume_hash or not cookies_str:
        return {"ok": False, "error": "Требуются: name, resume_hash, cookies"}

    cookies, _ = _parse_cookies_str(cookies_str)
    if not cookies or "hhtoken" not in cookies:
        return {"ok": False, "error": "Не удалось распознать cookies (нужен hhtoken)"}

    final_short = short or (name.split()[0] if name.split() else name)
    # Уникальность short — иначе vacancy_queues пересекаются (kimi-r14-2 #7):
    # два аккаунта с одним short затирают очереди друг друга.
    existing_shorts = {a.get("short", "") for a in accounts_data}
    if final_short in existing_shorts:
        return {"ok": False, "error": f"short='{final_short}' уже используется — выберите уникальное"}

    auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
    acc = {
        "name": name,
        "short": final_short,
        "color": color,
        "resume_hash": resume_hash,
        "letter": letter,
        "cookies": auth_cookies,
        "urls": [],
    }
    accounts_data.append(acc)
    save_accounts()

    state = AccountState(acc)
    bot.account_states.append(state)
    new_idx = len(bot.account_states) - 1
    for target in (bot._run_account_worker, bot._fetch_hh_stats_worker):
        threading.Thread(target=target, args=(new_idx, state), daemon=True).start()

    return {"ok": True, "idx": new_idx, "name": name}


@router.delete("/api/account/{idx}/delete")
async def api_account_delete(idx: int):
    """Удалить основной аккаунт."""
    if not (0 <= idx < len(accounts_data)):
        return {"ok": False, "error": "Аккаунт не найден"}

    if 0 <= idx < len(bot.account_states):
        deleted_state = bot.account_states[idx]
        deleted_state._deleted = True
        deleted_state.paused = True
        ws = getattr(deleted_state, "_ws_client", None)
        if ws:
            try:
                ws.stop()
            except Exception:
                pass

    name = accounts_data[idx].get("name", f"#{idx}")
    short = accounts_data[idx].get("short", "")
    resume_hash = accounts_data[idx].get("resume_hash", "")

    if 0 <= idx < len(bot.account_states):
        bot.account_states.pop(idx)
    # Чистим связанные структуры — иначе остаются висеть в памяти (swarm-11 #3,#6).
    # vacancy_queues keyed by state.short (manager.py:1053), но раньше pop был по name —
    # очередь оставалась висеть когда name != short (kimi-r14-2 #7).
    if short:
        bot.vacancy_queues.pop(short, None)
    bot.vacancy_queues.pop(name, None)  # backward compat для старых записей
    with bot._deque_lock:
        bot.recent_responses = type(bot.recent_responses)(
            (r for r in bot.recent_responses
             if r.get("acc") not in {name, short}),
            maxlen=bot.recent_responses.maxlen,
        )
    if resume_hash:
        from app.oauth import invalidate_oauth_token
        invalidate_oauth_token(resume_hash)
    accounts_data.pop(idx)

    save_accounts()
    bot._add_log("", "", f"\U0001f5d1️ Аккаунт удалён: {name}", "info")
    return {"ok": True}


@router.post("/api/account/{idx}/apply_tests")
async def api_apply_tests(idx: int):
    """Переключить флаг apply_tests для аккаунта/сессии."""
    base = len(bot.account_states)
    if idx < base:
        state = bot.account_states[idx]
        state.apply_tests = not state.apply_tests
        accounts_data[idx]["apply_tests"] = state.apply_tests
        save_accounts()
        return {"ok": True, "apply_tests": state.apply_tests}
    ti = idx - base
    state = bot.temp_states.get(ti)
    if state:
        state.apply_tests = not state.apply_tests
        if 0 <= ti < len(bot.temp_sessions):
            bot.temp_sessions[ti]["apply_tests"] = state.apply_tests
            save_browser_sessions(bot.temp_sessions)
        return {"ok": True, "apply_tests": state.apply_tests}
    return {"ok": False, "error": "Аккаунт не найден"}


@router.post("/api/account/{idx}/safety_toggle")
async def api_safety_toggle(idx: int):
    """Переключить защитный preflight только для выбранного аккаунта."""
    base = len(bot.account_states)
    if 0 <= idx < base:
        state = bot.account_states[idx]
        state.safety_enabled = not state.safety_enabled
        accounts_data[idx]["safety_enabled"] = state.safety_enabled
        save_accounts()
        return {"ok": True, "safety_enabled": state.safety_enabled}
    ti = idx - base
    state = bot.temp_states.get(ti)
    if ti >= 0 and state:
        state.safety_enabled = not state.safety_enabled
        if ti < len(bot.temp_sessions):
            bot.temp_sessions[ti]["safety_enabled"] = state.safety_enabled
            save_browser_sessions(bot.temp_sessions)
        return {"ok": True, "safety_enabled": state.safety_enabled}
    return {"ok": False, "error": "Аккаунт не найден"}


@router.post("/api/account/{idx}/degraded_fallback")
async def api_degraded_fallback(idx: int):
    """Переключить degraded_fallback_enabled — при cookies_expired
    автоматически переходить на OAuth API (default ON)."""
    base = len(bot.account_states)
    if idx < base:
        state = bot.account_states[idx]
        state.degraded_fallback_enabled = not state.degraded_fallback_enabled
        accounts_data[idx]["degraded_fallback_enabled"] = state.degraded_fallback_enabled
        save_accounts()
        return {"ok": True, "degraded_fallback_enabled": state.degraded_fallback_enabled}
    ti = idx - base
    state = bot.temp_states.get(ti)
    if state:
        state.degraded_fallback_enabled = not state.degraded_fallback_enabled
        if 0 <= ti < len(bot.temp_sessions):
            bot.temp_sessions[ti]["degraded_fallback_enabled"] = state.degraded_fallback_enabled
            save_browser_sessions(bot.temp_sessions)
        return {"ok": True, "degraded_fallback_enabled": state.degraded_fallback_enabled}
    # temp session not yet activated — flip in temp_sessions list only
    if 0 <= ti < len(bot.temp_sessions):
        cur = bot.temp_sessions[ti].get("degraded_fallback_enabled", True)
        bot.temp_sessions[ti]["degraded_fallback_enabled"] = not cur
        save_browser_sessions(bot.temp_sessions)
        return {"ok": True, "degraded_fallback_enabled": not cur}
    return {"ok": False, "error": "Аккаунт не найден"}


@router.get("/api/account/{idx}/resume_text")
async def api_resume_text(idx: int):
    """Получить и вернуть текстовое представление резюме (для проверки)."""
    s = None
    if 0 <= idx < len(bot.account_states):
        s = bot.account_states[idx]
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
    if not s:
        return {"ok": False, "error": "Invalid idx"}
    rh = s.acc.get("resume_hash", "")
    _resume_cache.pop(rh, None)
    client = get_client(s.acc)  # до executor: выбор клиента синхронный
    text = await asyncio.get_event_loop().run_in_executor(None, client.fetch_resume)
    return {"ok": True, "resume_hash": rh, "length": len(text), "text": text}


@router.get("/api/account/{idx}/resume_views")
async def api_resume_views(idx: int):
    """История просмотров резюме для аккаунта"""
    s = None
    if 0 <= idx < len(bot.account_states):
        s = bot.account_states[idx]
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
    if s:
        client = get_client(s.acc)  # до executor: выбор клиента синхронный
        if not s.resume_view_history:
            loop = asyncio.get_event_loop()
            history = await loop.run_in_executor(
                None, client.fetch_resume_view_history, 100
            )
            s.resume_view_history = history.get("items", []) if isinstance(history, dict) else history
        if not s.resume_views_7d:
            loop = asyncio.get_event_loop()
            rs = await loop.run_in_executor(None, client.fetch_stats)
            s.resume_views_7d = rs["views"]
            s.resume_views_new = rs["views_new"]
            s.resume_shows_7d = rs["shows"]
            s.resume_invitations_7d = rs["invitations"]
            s.resume_invitations_new = rs["invitations_new"]
            s.resume_next_touch_seconds = rs["next_touch_seconds"]
            s.resume_free_touches = rs["free_touches"]
            s.resume_global_invitations = rs["global_invitations"]
            s.resume_new_invitations_total = rs["new_invitations_total"]
        # Аггрегат за всё время + daily-graph 30 дней — отдельным fetch'ем,
        # кэшируется в state. Бесплатный апсайд для UI: соискатель видит
        # тренд просмотров (пики/провалы) и общий счётчик 18k+.
        if not getattr(s, "resume_views_total", None):
            loop = asyncio.get_event_loop()
            agg = await loop.run_in_executor(None, client.fetch_resume_views_aggregate)
            s.resume_views_total = agg.get("total_all_time", 0)
            s.resume_views_total_new = agg.get("total_new", 0)
            s.resume_views_graph_30d = agg.get("graph_30d", [])
        return {
            "history": s.resume_view_history,
            "stats": {
                "views_7d": s.resume_views_7d,
                "views_new": s.resume_views_new,
                "shows_7d": s.resume_shows_7d,
                "invitations_7d": s.resume_invitations_7d,
                "invitations_new": s.resume_invitations_new,
                "global_invitations": s.resume_global_invitations,
                "new_invitations_total": s.resume_new_invitations_total,
                "next_touch_seconds": s.resume_next_touch_seconds,
                "free_touches": s.resume_free_touches,
                "total_all_time": getattr(s, "resume_views_total", 0),
                "total_new_unseen": getattr(s, "resume_views_total_new", 0),
                "graph_30d": getattr(s, "resume_views_graph_30d", []),
            }
        }
    return {"ok": False, "error": "Invalid idx"}


@router.post("/api/account/{idx}/oauth_token")
async def api_oauth_token(idx: int):
    """Get/refresh OAuth token for account."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, _obtain_oauth_token, acc)
    if token:
        rh = acc.get("resume_hash", "")
        with _oauth_lock:
            info = _oauth_tokens.get(rh, {})
        return {
            "ok": True,
            # Не отдаём ни одного байта токена наружу — 20 chars Bearer-токена
            # достаточно для подтверждения существования + entropy reduction (swarm-7 #2).
            "expires_in": int(info.get("expires_at", 0) - time.time()),
            "has_refresh": bool(info.get("refresh_token")),
        }
    return {"ok": False, "error": "Failed to obtain token"}


@router.get("/api/account/{idx}/oauth_status")
async def api_oauth_status(idx: int):
    """Check OAuth token status."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    rh = acc.get("resume_hash", "")
    with _oauth_lock:
        info = _oauth_tokens.get(rh, {})
    if info:
        remaining = int(info.get("expires_at", 0) - time.time())
        return {
            "has_token": True,
            "expires_in_hours": round(remaining / 3600, 1),
            "has_refresh": bool(info.get("refresh_token")),
        }
    return {"has_token": False}


@router.post("/api/account/{idx}/oauth_touch")
async def api_oauth_touch(idx: int):
    """Touch/publish resume via OAuth API (no captcha)."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(None, _oauth_touch_resume, acc)
    return {"ok": ok, "message": msg}


@router.get("/api/account/{idx}/test_llm_questionnaire")
async def api_test_llm_questionnaire(idx: int, vacancy_id: str = ""):
    """Test LLM questionnaire answering without submitting."""
    if not vacancy_id:
        return {"ok": False, "error": "vacancy_id required"}
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Invalid idx"}
    def _do():
        ua = webview_user_agent()
        r = HH.get(
            f"{hh_base()}/applicant/vacancy_response?vacancyId={vacancy_id}&withoutTest=no",
            headers={"User-Agent": ua, "Accept": "text/html"},
            cookies=acc.get("cookies", {}), cookie_jar_key=_token_key(acc) or None, timeout=15)
        rich = _parse_questionnaire_rich(r.text)
        resume_data = get_client(acc).fetch_resume() if CONFIG.llm_use_resume else {}
        resume_text = (resume_data.get("text", "") if isinstance(resume_data, dict)
                       and "text" in resume_data else json.dumps(resume_data, ensure_ascii=False))
        answers = generate_llm_questionnaire_answers(rich, f"Vacancy {vacancy_id}", "", resume_text)
        result = []
        for q in rich:
            llm_ans = answers.get(q["field"], "")
            result.append({
                "field": q["field"], "type": q["type"], "text": q["text"],
                "options": q.get("options", []),
                "llm_answer": llm_ans,
                "template_answer": get_questionnaire_answer(q["text"]),
            })
        return {"questions": result, "llm_answered": len(answers), "total": len(rich),
                "llm_enabled": CONFIG.llm_enabled, "profiles": len(CONFIG.llm_profiles or [])}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do)


@router.get("/api/account/{idx}/resume_audit")
async def api_resume_audit(idx: int, extra_terms: str = ""):
    """Аудит резюме — анализ видимости для HR."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    extra = [t.strip() for t in (extra_terms or "").split(",") if t.strip()] if extra_terms else []
    loop = asyncio.get_event_loop()
    client = get_client(acc)  # до executor: выбор клиента синхронный
    return await loop.run_in_executor(None, client.analyze_resume, extra)


@router.get("/api/account/{idx}/suggest_urls")
async def api_suggest_urls(idx: int, extra_terms: str = ""):
    """Подсказать URL поисков на основе резюме (title + professionalRole + skills).
    Возвращает [{term, vacancies, seekers, ratio, url}, ...] отсортированный
    по конкуренции (низкая → высокая). Использует кеш аудита если он уже есть.
    Использовать на странице Настройки → Пул URL."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    extra = [t.strip() for t in (extra_terms or "").split(",") if t.strip()] if extra_terms else []
    loop = asyncio.get_event_loop()
    client = get_client(acc)  # до executor: выбор клиента синхронный
    audit = await loop.run_in_executor(None, client.analyze_resume, extra)
    if audit.get("error"):
        return {"ok": False, "error": audit["error"]}
    suggestions = []
    import urllib.parse as _up
    resume_hash = acc.get("resume_hash", "")
    for cmp_item in (audit.get("supply_demand_comparison") or []):
        term = cmp_item.get("term", "").strip()
        if not term:
            continue
        # ?text=...&area=113&order_by=publication_time для свежих
        url = (
            f"{hh_base()}/search/vacancy?text={_up.quote(term)}"
            f"&area=113&order_by=publication_time&items_on_page=20"
        )
        suggestions.append({
            "term": term,
            "url": url,
            "vacancies": cmp_item.get("vacancies", 0),
            "ratio": cmp_item.get("ratio", 0),
        })
    # Если есть resume_hash — добавим вариант "По резюме" первым (приоритет).
    if resume_hash:
        url_resume = (
            f"{hh_base()}/search/vacancy?resume={resume_hash}"
            f"&area=113&order_by=publication_time&items_on_page=20"
        )
        suggestions.insert(0, {
            "term": f"По резюме «{audit.get('title', '?')}»",
            "url": url_resume,
            "vacancies": audit.get("market", {}).get("vacancy_count", 0),
            "ratio": audit.get("market", {}).get("supply_demand_ratio", 0),
        })
    return {
        "ok": True,
        "resume_title": audit.get("title", ""),
        "resume_hash": resume_hash,
        "suggestions": suggestions,
    }


@router.get("/api/account/{idx}/hot_leads")
async def api_hot_leads(idx: int):
    """Possible job offers — горячие лиды, работодатели готовые пригласить."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    try:
        r = HH.get(
            hh_base() + "/shards/applicant/negotiations/possible_job_offers",
            headers={
                "User-Agent": webview_user_agent(),
                "Accept": "application/json",
                "X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""),
                "Referer": hh_base() + "/applicant/negotiations",
            },
            cookies=acc.get("cookies", {}), cookie_jar_key=_token_key(acc) or None, timeout=15,
        )
        if r.status_code != 200:
            return {"offers": [], "error": f"HTTP {r.status_code}"}
        d = r.json()
        offers = []
        for o in d.get("possibleJobOffers", []):
            offers.append({
                "employer": o.get("name", "?"),
                "employer_id": o.get("employerId"),
                "vacancies": o.get("vacancyNames", []),
                "vacancy_id": o.get("vacancyId", ""),
                "has_invitation": o.get("hasInvitationTopic", False),
                "topic_ids": o.get("topicIds", []),
            })
        return {"offers": offers, "total": len(offers)}
    except Exception as e:
        return {"offers": [], "error": str(e)}


@router.get("/api/account/{idx}/remindable")
async def api_remindable(idx: int):
    """Return negotiations where responseReminderState.allowed is True (can send reminder)."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    ua = webview_user_agent()
    try:
        r = HH.get(
            hh_base() + "/applicant/negotiations",
            headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"},
            cookies=acc.get("cookies", {}), cookie_jar_key=_token_key(acc) or None, timeout=15,
        )
        if r.status_code != 200 or _is_login_page(r.text):
            return {"error": "auth_error", "remindable": []}
        ssr = parse_hh_lux_ssr(r.text)
        topic_list = ssr.get("topicList", [])
        remindable = []
        for topic in (topic_list if isinstance(topic_list, list) else []):
            if not isinstance(topic, dict):
                continue
            rrs = topic.get("responseReminderState", {})
            if isinstance(rrs, dict) and rrs.get("allowed"):
                employer = ""
                vacancy = ""
                chat_id = topic.get("chatId", "")
                topic_id = topic.get("topicId", "")
                v_info = topic.get("vacancy", {})
                if isinstance(v_info, dict):
                    vacancy = v_info.get("name", "")
                    emp = v_info.get("company", v_info.get("employer", {}))
                    if isinstance(emp, dict):
                        employer = emp.get("name", "")
                    elif isinstance(emp, str):
                        employer = emp
                remindable.append({
                    "chat_id": str(chat_id),
                    "topic_id": str(topic_id),
                    "employer": employer,
                    "vacancy": vacancy,
                })
        return {"remindable": remindable, "total": len(remindable)}
    except Exception as e:
        return {"error": str(e), "remindable": []}


@router.post("/api/account/{idx}/clone_resume")
async def api_clone_resume(idx: int, request: Request):
    """Clone resume and optionally set title. Body: {title?: "new title"}"""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    try:
        body = await request.json()
    except Exception:
        body = {}
    new_title = body.get("title", "")
    resume_hash = acc.get("resume_hash", "")
    if not resume_hash:
        return {"ok": False, "error": "No resume_hash"}
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    try:
        r = HH.post(
            hh_base() + "/applicant/resumes/clone",
            headers={
                "User-Agent": webview_user_agent(),
                "Accept": "application/json",
                "X-Xsrftoken": xsrf,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://hh.ru",
                "Referer": hh_base() + "/applicant/resumes",
            },
            cookies=acc.get("cookies", {}), cookie_jar_key=_token_key(acc) or None,
            data=f"resume={resume_hash}&_xsrf={xsrf}",
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            new_url = d.get("url", "")
            new_hash = ""
            m = re.search(r'resume=([a-f0-9]+)', new_url)
            if m:
                new_hash = m.group(1)
            if not new_hash:
                return {"ok": True, "new_hash": "", "message": "Склонировано, но hash не получен"}

            ua = webview_user_agent()
            r_orig = HH.get(f"{hh_base()}/resume/{resume_hash}",
                headers={"User-Agent": ua, "Accept": "text/html"},
                cookies=acc.get("cookies", {}), cookie_jar_key=_token_key(acc) or None, timeout=15)
            orig_data = {}
            m_ssr = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>([\s\S]*?)</template>', r_orig.text)
            if m_ssr:
                orig_data = json.loads(m_ssr.group(1)).get("applicantResume", {})

            fields = {}
            if new_title:
                fields["title"] = [{"string": new_title}]
            for copy_field in ("experience", "primaryEducation", "skills", "employment",
                               "workSchedule", "workFormats", "businessTripReadiness",
                               "relocation", "travelTime"):
                val = orig_data.get(copy_field, [])
                if val:
                    fields[copy_field] = val
            if not orig_data.get("salary"):
                fields["salary"] = [{"amount": 100000, "currency": "RUR"}]
            if not any(s.get("string") == "remote" for s in orig_data.get("workSchedule", [])):
                ws = list(orig_data.get("workSchedule", []))
                ws.append({"string": "remote"})
                fields["workSchedule"] = ws
            if not any(s.get("string") == "REMOTE" for s in orig_data.get("workFormats", [])):
                wf = list(orig_data.get("workFormats", []))
                wf.append({"string": "REMOTE"})
                fields["workFormats"] = wf

            edited_count = 0
            client = get_client(acc)
            for field_name, field_data in fields.items():
                res = client.edit_resume_field(new_hash, {field_name: field_data})
                if res.get("ok"):
                    edited_count += 1

            return {
                "ok": True,
                "new_hash": new_hash,
                "edit_url": f"{hh_base()}/resume/edit/{new_hash}/position",
                "fields_copied": edited_count,
                "message": f"Полный клон создан! {edited_count} полей скопировано. Осталось опубликовать на hh.ru",
            }
        else:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/account/{idx}/edit_resume")
async def api_edit_resume(idx: int, request: Request):
    """Edit resume fields via API. Body: {resume_hash, title, salary, skills, professionalRole}"""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}

    resume_hash = body.get("resume_hash") or acc.get("resume_hash", "")
    if not resume_hash:
        return {"ok": False, "error": "No resume_hash"}

    fields = {}
    if "title" in body and body["title"]:
        fields["title"] = [{"string": body["title"]}]
    if "salary" in body:
        try:
            sal = int(body["salary"])
            if sal > 0:
                fields["salary"] = [{"amount": sal, "currency": body.get("currency", "RUR")}]
            else:
                fields["salary"] = []
        except (ValueError, TypeError):
            pass
    if "skills" in body and body["skills"]:
        fields["skills"] = [{"string": body["skills"]}]
    if "professionalRole" in body:
        try:
            fields["professionalRole"] = [{"string": int(body["professionalRole"])}]
        except (ValueError, TypeError):
            pass

    if not fields:
        return {"ok": False, "error": "No fields to update"}

    loop = asyncio.get_event_loop()
    client = get_client(acc)  # до executor: выбор клиента синхронный
    result = await loop.run_in_executor(None, client.edit_resume_field, resume_hash, fields)
    return result


@router.get("/api/account/{idx}/all_resumes")
async def api_all_resumes(idx: int):
    """List all resumes for this account (including clones). Uses HTML page for full data."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    ua = webview_user_agent()
    try:
        r = HH.get(
            hh_base() + "/applicant/resumes",
            headers={"User-Agent": ua, "Accept": "text/html", "Referer": hh_base() + "/"},
            cookies=acc.get("cookies", {}), cookie_jar_key=_token_key(acc) or None, timeout=15,
        )
        if r.status_code in (401, 403) or _is_login_page(r.text):
            return {"resumes": [], "error": "auth_error"}
        if r.status_code != 200:
            return {"resumes": [], "error": f"HTTP {r.status_code}"}
        ssr = parse_hh_lux_ssr(r.text)
        ssr_resumes = ssr.get("applicantResumes", [])
        stats = ssr.get("applicantResumesStatistics", {}).get("resumes", {})

        resumes = []
        for res in ssr_resumes:
            attrs = res.get("_attributes", {})
            rid = str(attrs.get("id", ""))
            rhash = attrs.get("hash", "")
            title_list = res.get("title", [])
            title = title_list[0].get("string", "") if title_list and isinstance(title_list[0], dict) else ""
            percent = attrs.get("percent", 0)
            rs = stats.get(rid, {}).get("statistics", {})
            resumes.append({
                "hash": rhash,
                "title": title or "(без заголовка)",
                "status": attrs.get("status", ""),
                "percent": percent,
                "is_searchable": attrs.get("isSearchable", False),
                "can_publish": attrs.get("canPublishOrUpdate", False),
                "updated": attrs.get("updated"),
                "skills_count": len(res.get("keySkills", [])),
                "experience_count": len(res.get("experience", [])),
                "views_7d": (rs.get("views") or {}).get("count", 0),
                "shows_7d": (rs.get("searchShows") or {}).get("count", 0),
                "edit_url": f"{hh_base()}/resume/edit/{rhash}/position",
            })
        return {"resumes": resumes, "total": len(resumes)}
    except Exception as e:
        return {"resumes": [], "error": str(e)}


# Cache: {url: (timestamp, result)} — TTL 10 min, ограничение размера.
_URL_PREVIEW_CACHE: dict = {}
_URL_PREVIEW_TTL = 600
_URL_PREVIEW_MAX = 200


def _url_preview_compute(url: str, cookies: dict) -> dict:
    """Достать кол-во вакансий + (если возможно) кол-во активных соискателей по URL."""
    import urllib.parse as _up
    ua = webview_user_agent()
    result = {"vacancies": 0, "seekers": 0, "ratio": 0.0}
    # URL приходит от пользователя: hh.ru/hh.kz-хосты гоняем через HH-клиент
    # (HH_PROXY + cookies), не-hh URL — напрямую, HH-прокси к ним не применяем.
    host = (_up.urlparse(url).hostname or "").lower()
    _hh_host = (host in ("hh.ru", "hh.kz")
                or host.endswith(".hh.ru") or host.endswith(".hh.kz"))
    try:
        # 1. Vacancies count — фетчим URL как есть, парсим SSR.
        if _hh_host:
            r = HH.get(url, headers={"User-Agent": ua, "Accept": "text/html"},
                       cookies=cookies, timeout=10)
        else:
            r = requests.get(url, headers={"User-Agent": ua, "Accept": "text/html"},
                             cookies=cookies, timeout=10)
        if r.status_code == 200 and not _is_login_page(r.text):
            from app.hh_resume import parse_hh_lux_ssr
            ssr = parse_hh_lux_ssr(r.text)
            sc = ssr.get("searchCounts", {})
            if isinstance(sc, dict) and sc.get("value"):
                result["vacancies"] = int(sc["value"])
            if not result["vacancies"]:
                m = re.search(r'"found"\s*:\s*(\d+)', r.text[:8000])
                if m:
                    result["vacancies"] = int(m.group(1))

        # 2. Seekers count — только если URL содержит ?text= (для resume= это
        # нельзя посчитать без дополнительной информации о резюме).
        try:
            parsed = _up.urlparse(url)
            qs = dict(_up.parse_qsl(parsed.query))
            text = qs.get("text", "").strip()
            if text and result["vacancies"]:
                r2 = HH.get(
                    f"{hh_base()}/search/applicant?text={_up.quote(text)}&area=113&clusters=true",
                    headers={"User-Agent": ua, "Accept": "application/json,text/html"},
                    cookies=cookies, timeout=10,
                )
                if r2.status_code == 200:
                    try:
                        cj = r2.json()
                    except Exception:
                        cj = {}
                    js_groups = (cj.get("clusters", {}).get("job_search_status", {}) or {}).get("groups", {})
                    for gid, gdata in (js_groups or {}).items():
                        if gid == "active_search" or "актив" in (gdata.get("title", "")).lower():
                            result["seekers"] = int(gdata.get("count", 0))
                            break
        except Exception as e:
            log_debug(f"_url_preview seekers error: {e}")

        if result["vacancies"] > 0 and result["seekers"] > 0:
            result["ratio"] = round(result["seekers"] / result["vacancies"], 1)
    except Exception as e:
        log_debug(f"_url_preview_compute error: {e}")
    return result


@router.get("/api/url_preview")
async def api_url_preview(url: str, idx: int = 0):
    """Возвращает {vacancies, seekers, ratio} для поисковой URL.
    Если URL содержит ?text= — посчитает конкуренцию (как в аудите).
    Без text= — только число вакансий."""
    # Принимаем основной и любые региональные поддомены *.hh.ru/search/
    import re as _re
    if not url or not _re.match(r"^https://(?:[a-z0-9-]+\.)?hh\.ru/search/", url):
        return {"error": "bad url"}
    import time as _t
    import urllib.parse as _up
    now = _t.time()

    # Если URL имеет ?resume=HASH и хеш НЕ принадлежит этому аккаунту —
    # HH вернёт 404, и закешировать 0 нельзя (затрёт работающие результаты
    # у владельца). Возвращаем явный foreign-маркер без кеша.
    try:
        qs_dict = dict(_up.parse_qsl(_up.urlparse(url).query))
        url_resume = qs_dict.get("resume", "").strip()
    except Exception:
        url_resume = ""

    acc = bot._get_apply_acc(idx) if 0 <= idx else None
    cookies = (acc or {}).get("cookies", {}) if acc else {}
    acc_resume = (acc or {}).get("resume_hash", "") if acc else ""
    if url_resume and acc_resume and url_resume != acc_resume:
        return {"vacancies": 0, "seekers": 0, "ratio": 0.0, "foreign_resume": True}

    # Кеш-ключ включает idx, чтобы разные аккаунты не затирали друг друга.
    cache_key = (url, int(idx))
    cached = _URL_PREVIEW_CACHE.get(cache_key)
    if cached and now - cached[0] < _URL_PREVIEW_TTL:
        return {**cached[1], "cached": True}
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _url_preview_compute, url, cookies)
    if len(_URL_PREVIEW_CACHE) > _URL_PREVIEW_MAX:
        oldest = min(_URL_PREVIEW_CACHE.items(), key=lambda kv: kv[1][0])
        _URL_PREVIEW_CACHE.pop(oldest[0], None)
    _URL_PREVIEW_CACHE[cache_key] = (now, data)
    return data


@router.post("/api/account/{idx}/decline_discards")
async def api_decline_discards(idx: int):
    """Авто-отклонение дискардов в переговорах"""
    if 0 <= idx < len(bot.account_states):
        acc = bot.account_states[idx].acc
        client = get_client(acc)  # до executor: выбор клиента синхронный

        def do_decline():
            return client.auto_decline_discards()

        count = await asyncio.get_event_loop().run_in_executor(None, do_decline)
        bot._add_log(
            bot.account_states[idx].short,
            bot.account_states[idx].color,
            f"\U0001f5d1️ Отклонено дискардов: {count}",
            "info",
        )
        return {"declined": count}
    return {"ok": False, "error": "Invalid idx"}


@router.get("/api/negotiations/{idx}")
async def api_negotiations(idx: int):
    s = None
    if 0 <= idx < len(bot.account_states):
        s = bot.account_states[idx]
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
    if s:
        return {
            "interviews": s.hh_interviews,
            "viewed": s.hh_viewed,
            "not_viewed": s.hh_not_viewed,
            "discards": s.hh_discards,
            "interviews_list": s.hh_interviews_list,
            "possible_offers": s.hh_possible_offers,
            "updated": s.hh_stats_updated.isoformat() if s.hh_stats_updated else None,
        }
    return {"ok": False, "error": "Invalid idx"}

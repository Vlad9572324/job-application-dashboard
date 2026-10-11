"""Human-only HH challenge handling; never solves or retries a request."""
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from app.storage import _atomic_write_json

PATH = Path('data/hh_challenges.json')
LOCK = threading.RLock()


def account_key(acc):
    value = acc.get('user_id') or acc.get('resume_hash')
    if not value:
        raise ValueError('Missing account identity')
    return str(value)


def safe_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value) or '\\' in value:
        return ''
    try:
        u = urlsplit(value)
        host = (u.hostname or '').lower()
        if u.scheme != 'https' or not (host == 'hh.ru' or host.endswith('.hh.ru')) or u.username or u.password or u.port not in (None, 443):
            return ''
        return value
    except ValueError:
        return ''


def parse(status, payload):
    if status not in (400, 403) or not isinstance(payload, dict):
        return None
    errors = payload.get('errors', [])
    if not isinstance(errors, list):
        return None
    for error in errors[:30]:
        if isinstance(error, dict) and any(error.get(k) == 'captcha_required' for k in ('type', 'value')):
            return {'captcha_url': safe_url(error.get('captcha_url')),
                    'fallback_url': safe_url(error.get('fallback_url')), 'error_type': 'captcha_required'}
    return None


def _read():
    data = json.loads(PATH.read_text()) if PATH.exists() else {}
    if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
        raise ValueError('Invalid challenge storage')
    return data


def current(acc):
    with LOCK:
        return dict(_read().get(account_key(acc), {}))


def claim_manual(acc, expected_id, *, auto_retry_after=None):
    """Reserve a GUI image; explicit human attempts remain manually owned."""
    with LOCK:
        data = _read()
        record = data.get(account_key(acc))
        if not record or record.get('id') != expected_id:
            raise ValueError('Challenge changed')
        record['manual_only'] = True
        record.pop('auto_retry_until', None)
        if auto_retry_after is not None:
            record['auto_retry_until'] = time.time() + max(0, auto_retry_after)
        _atomic_write_json(PATH, data)


def release_manual(acc, expected_id):
    """Return this challenge to the local worker without clearing the pause."""
    with LOCK:
        data = _read()
        record = data.get(account_key(acc))
        if not record or record.get('id') != expected_id:
            return False
        record.pop('manual_only', None)
        record.pop('auto_retry_until', None)
        _atomic_write_json(PATH, data)
        return True


def set_local_retry(acc, expected_id, delay, reason, attempt):
    """Persist local retry timing so a restart cannot skip HH's cooldown."""
    with LOCK:
        data = _read()
        record = data.get(account_key(acc))
        if not record or record.get('id') != expected_id:
            return False
        record.update(local_retry_at=time.time() + max(0, delay),
                      local_retry_reason=reason, local_attempts=attempt)
        _atomic_write_json(PATH, data)
        return True


def update_challenge_state(acc, expected_id, state):
    """Persist a replacement state from HH without changing challenge ownership."""
    if not isinstance(state, str) or not state.strip() or len(state) > 8192:
        return False
    with LOCK:
        data = _read()
        record = data.get(account_key(acc))
        if not record or record.get('id') != expected_id:
            return False
        changed = False
        for name in ('captcha_url', 'fallback_url'):
            url = safe_url(record.get(name))
            if not url:
                continue
            parts = urlsplit(url)
            query = parse_qsl(parts.query, keep_blank_values=True)
            if not any(k == 'state' for k, _ in query):
                continue
            query = [(k, state if k == 'state' else v) for k, v in query]
            new_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
            if new_url != record[name]:
                record[name] = new_url
                changed = True
        if changed:
            _atomic_write_json(PATH, data)
        return changed


def active(acc):
    try:
        with LOCK:
            data = _read()
            return bool(data) and bool(data.get(account_key(acc)))
    except Exception:
        return True


def _request_context(value):
    """Keep only the target identifiers needed to diagnose a rejected apply."""
    if not isinstance(value, dict) or value.get('operation') != 'apply':
        return None
    vacancy_id = value.get('vacancy_id')
    resume_id = value.get('resume_id')
    if (not isinstance(vacancy_id, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', vacancy_id)
            or not isinstance(resume_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', resume_id)):
        return None
    return {'operation': 'apply', 'vacancy_id': vacancy_id, 'resume_id': resume_id}


def hold(acc, details):
    callback = acc.get('_on_challenge')
    if callable(callback):
        callback()
    new_challenge = False
    with LOCK:
        data = _read()
        key = account_key(acc)
        previous = data.get(key, {})
        urls = {name: safe_url(details.get(name)) for name in ('captcha_url', 'fallback_url')}
        old_url = safe_url(previous.get('captcha_url')) or safe_url(previous.get('fallback_url'))
        new_url = urls['captcha_url'] or urls['fallback_url']
        old_state = next((v for k, v in parse_qsl(urlsplit(old_url).query) if k == 'state'), '')
        new_state = next((v for k, v in parse_qsl(urlsplit(new_url).query) if k == 'state'), '')
        # A newly issued opaque state supersedes every image/session tied to
        # the old ID. URL encoding or backurl changes alone do not do this.
        replaced_state = bool(old_state.strip() and new_state.strip() and old_state != new_state)
        if key not in data or (not old_url and new_url) or replaced_state:
            new_challenge = True
            data[key] = {'id': uuid.uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(),
                         **urls}
        context = _request_context(details.get('request_context'))
        same_challenge = bool(old_state.strip() and old_state == new_state) or bool(
            old_url and old_url == new_url)
        # Preserve the original rejected target. A new challenge may have a
        # different target; a response without a matching URL cannot fill it.
        if (context and (new_challenge or same_challenge)
                and not data[key].get('request_context')):
            data[key]['request_context'] = context
        _atomic_write_json(PATH, data)
        challenge_id = data[key]['id']
    # Log only newly created/replaced challenges, not repeated captures.
    if new_challenge:
        from app.captcha_journal import record
        record('challenge', acc, id=challenge_id, has_url=bool(safe_url(details.get('captcha_url'))),
               source=details.get('source'))
        try:
            from app.instances import bot as _bot
            _bot._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                          '🔐 HH запросил капчу — ожидание ответа (TG/GUI)', 'warning')
        except Exception:
            pass


def capture(acc, status, payload, source=None, *, request_context=None):
    details = parse(status, payload)
    if details is not None:
        details['source'] = source
        # Request context stays in private challenge storage, never the
        # returned error details or public journal.
        hold(acc, {**details, 'request_context': request_context})
    return details


def browser_url(record):
    url = safe_url(record.get('captcha_url'))
    if not url:
        return safe_url(record.get('fallback_url'))
    u = urlsplit(url)
    # Stay on HH after the human check. No callback can auto-resume automation.
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() != 'backurl']
    query.append(('backurl', 'https://hh.ru/'))
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(query), u.fragment))


def clear(acc, expected_id):
    with LOCK:
        data = _read()
        key = account_key(acc)
        if not data.get(key) or data[key].get('id') != expected_id:
            raise ValueError('Challenge changed')
        del data[key]
        _atomic_write_json(PATH, data)

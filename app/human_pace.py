"""Interruptible per-account pacing. Hours are Moscow time: HH and its users live in MSK,
while the container clock is UTC (07-24 UTC used to mean 10:00-03:00 MSK)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
import random
import re
import time
import json
import math
import threading
from pathlib import Path

from app.config import CONFIG
from app.hh_http import HH
from app.logging_utils import log_debug
from app.user_agent import webview_user_agent

# Independent generator: never reseed the process-wide random module.
_rng = random.Random()
_MSK = ZoneInfo('Europe/Moscow')

# Five-second per-account minimum; configured delays can make this slower.
TARGET_APPLIES_PER_HOUR = 720.0
PACE_FILE = Path('data/apply_pace.json')
_pace_lock = threading.RLock()


def _pace_key(acc):
    key = acc.get('user_id') or acc.get('resume_hash')
    if not key:
        raise ValueError('Missing account identity for pacing')
    return str(key)


def _pace_read():
    data = json.loads(PACE_FILE.read_text()) if PACE_FILE.exists() else {}
    def valid_number(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value >= 0)

    def valid_record(value):
        # Legacy records contain only a deadline; honour it until the next slot.
        if valid_number(value):
            return True
        return (isinstance(value, dict) and set(value) == {'reserved_at', 'next_at'}
                and all(valid_number(v) for v in value.values())
                and value['next_at'] >= value['reserved_at'])

    if not isinstance(data, dict) or any(not valid_record(value) for value in data.values()):
        raise ValueError('Invalid pacing storage')
    return data


def uniform_interval():
    """Deterministic load limit, not a human-behaviour simulation."""
    return max(3600 / TARGET_APPLIES_PER_HOUR,
               float(CONFIG.human_apply_delay_min), float(CONFIG.human_apply_delay_max))


def reserve_attempt(acc, now=None, multiplier=1.0):
    """Return remaining wait, or reserve ONE attempt durably before sending.

    A crash can waste a slot but cannot make the next attempt run early.
    Corrupt storage raises rather than silently resetting the limit.
    """
    from app.storage import _atomic_write_json
    now = time.time() if now is None else now
    with _pace_lock:
        data = _pace_read()
        key = _pace_key(acc)
        record = data.get(key, 0)
        interval = uniform_interval() * max(1.0, multiplier)
        deadline = (record['reserved_at'] + interval
                    if isinstance(record, dict) else record)
        remaining = max(0, deadline - now)
        if remaining:
            if isinstance(record, dict) and record['next_at'] != deadline:
                record['next_at'] = deadline
                _atomic_write_json(PACE_FILE, data)
            return remaining
        data[key] = {'reserved_at': now, 'next_at': now + interval}
        _atomic_write_json(PACE_FILE, data)
        return 0

HUMAN_CONFIG_KEYS = (
    'human_mode_enabled', 'human_active_hours',
    'human_apply_delay_min', 'human_apply_delay_max',
    'human_burst_size_min', 'human_burst_size_max',
    'human_burst_pause_min_sec', 'human_burst_pause_max_sec',
    'human_captcha_backoff_hours',
)


def _bounds(low, high, minimum=0):
    # Runtime settings arrive individually; tolerate temporarily reversed bounds.
    return sorted((max(minimum, low), max(minimum, high)))


def is_fast_pace() -> bool:
    """Zero burst pauses select the configured pace without synthetic waits."""
    return CONFIG.human_burst_pause_min_sec == CONFIG.human_burst_pause_max_sec == 0


def random_apply_delay() -> float:
    if is_fast_pace():
        return 0
    if _rng.random() < 0.1:
        return _rng.uniform(30, 60)
    low, high = _bounds(CONFIG.human_apply_delay_min, CONFIG.human_apply_delay_max)
    return low + (high - low) * _rng.betavariate(2, 5)


def random_burst_size() -> int:
    return _rng.randint(*_bounds(CONFIG.human_burst_size_min, CONFIG.human_burst_size_max, 1))


def random_burst_pause() -> float:
    return _rng.uniform(*_bounds(CONFIG.human_burst_pause_min_sec, CONFIG.human_burst_pause_max_sec))


def warm_up_read_vacancy(acc, vacancy_id) -> None:
    """Occasionally open a vacancy in the background, then allow reading time.

    The worker supplies an interruptible wait; standalone callers use sleep.
    Neither the GET result nor a network failure is needed to finish the wait.
    """
    if is_fast_pace() or _rng.random() >= 0.3:
        return
    allowed = acc.get('_mutation_guard', lambda: True)
    if not allowed():
        return
    from app.oauth import _token_key
    cookies = dict(acc.get('cookies') or {})
    jar_key = _token_key(acc)
    if not jar_key:
        return  # Never put an unidentified account's cookies in a shared jar.

    mobile = acc.get('use_oauth') or str(acc.get('mode') or '').lower() in ('oauth', 'mobile')

    def read():
        response = None
        try:
            if allowed() and mobile:
                # What the Android app does when a vacancy card is opened; a desktop
                # web page hit from a mobile-only token is a second, mismatched client.
                from app.hh_mobile_transport import mobile_request
                mobile_request(acc, 'GET', f'/vacancies/{vacancy_id}', timeout=5)
            elif allowed():
                response = HH.get(
                    f'https://hh.ru/vacancy/{vacancy_id}',
                    headers={'User-Agent': webview_user_agent(), 'Accept': 'text/html'},
                    cookies=cookies, cookie_jar_key=jar_key, timeout=5,
                    allow_redirects=False,
                )
        except Exception as exc:
            log_debug(f'human: vacancy warm-up failed ({type(exc).__name__})')
        finally:
            if response is not None:
                response.close()

    threading.Thread(target=read, name='human-vacancy-read', daemon=True).start()
    acc.get('_human_wait', time.sleep)(_rng.uniform(5, 15))


def random_skip_vacancy() -> bool:
    return _rng.random() < 0.05


def long_idle_burst() -> float | None:
    if is_fast_pace():
        return None
    return _rng.uniform(1800, 3600) if _rng.random() < 0.1 else None


def post_captcha_cooldown_sec() -> int:
    return 5 if is_fast_pace() else 1800


def _last_captcha_at(state):
    return max(getattr(state, '_last_captcha_at', 0) or 0,
               getattr(state, 'acc', {}).get('_last_captcha_at', 0) or 0)


def captcha_cooldown_remaining(state) -> float:
    last = _last_captcha_at(state)
    return max(0, last + post_captcha_cooldown_sec() - time.time()) if last else 0


def post_captcha_rate_cut(state) -> float:
    if is_fast_pace():
        return 1.0
    last = _last_captcha_at(state)
    age = time.time() - last
    if not last or age < 0:
        return 1.0
    if age < max(4, CONFIG.human_captcha_backoff_hours) * 3600:
        return 3.0
    return 1.5 if age < 24 * 3600 else 1.0


def account_start_jitter() -> float:
    return 0 if is_fast_pace() else _rng.uniform(0, 300)


def respect_retry_after(headers, default_sec=0) -> int:
    """HTTP delay-seconds or HTTP-date; round up to avoid retrying early."""
    value = next((str(v).strip() for k, v in (headers or {}).items()
                  if str(k).lower() == 'retry-after'), '')
    if re.fullmatch(r'[0-9]+', value):
        return int(value)
    try:
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return max(0, math.ceil(deadline.timestamp() - time.time()))
    except (TypeError, ValueError, OverflowError):
        return default_sec


def parse_active_hours(hours: str) -> tuple[int, int]:
    if not re.fullmatch(r'\d{2}-\d{2}', hours):
        raise ValueError('Active hours must use HH-HH')
    start, end = map(int, hours.split('-'))
    if not (0 <= start <= 23 and 0 <= end <= 24) or start == end:
        raise ValueError('Invalid or empty active window')
    return start, end


def is_active_hour(hours=None, now=None) -> bool:
    try:
        start, end = parse_active_hours(CONFIG.human_active_hours if hours is None else hours)
    except (ValueError, TypeError):
        return False  # Invalid runtime configuration must not enable sending.
    hour = (now or datetime.now(_MSK)).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def interruptible_wait(stop_event, seconds, allowed=lambda: True):
    """Bounded control checks; never resumes or clears protective state."""
    deadline = time.monotonic() + max(0, seconds)
    while not stop_event.is_set():
        if not allowed():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        if stop_event.wait(min(1.0, remaining)):
            return False
    return False


def sleep_until_active_hour(state, stop_event, allowed=lambda: True) -> None:
    while CONFIG.human_mode_enabled and not stop_event.is_set() and not getattr(state, '_deleted', False):
        if getattr(state, 'paused', False) or not allowed():
            return
        now = datetime.now(_MSK)
        if is_active_hour(now=now):
            return
        try:
            start, _ = parse_active_hours(CONFIG.human_active_hours)
            next_start = now.replace(hour=start, minute=0, second=0, microsecond=0)
            if next_start <= now:
                next_start += timedelta(days=1)
            remaining = next_start.timestamp() - now.timestamp()
            state.status_detail = f'Активное окно с {next_start:%H:%M} (МСК)'
        except (ValueError, TypeError):
            remaining = 60
            state.status_detail = 'Некорректные активные часы: нужен формат HH-HH'
        # Recheck settings/deletion each minute while waiting for the next window.
        if not interruptible_wait(stop_event, min(60, max(0, remaining)),
                lambda: CONFIG.human_mode_enabled and not getattr(state, 'paused', False)
                and not getattr(state, '_deleted', False) and allowed()):
            return


def adaptive_backoff_multiplier(state) -> float:
    last = max(getattr(state, '_last_captcha_at', 0) or 0,
               getattr(state, 'acc', {}).get('_last_captcha_at', 0) or 0)
    return 2.0 if last and 0 <= time.time() - last < CONFIG.human_captcha_backoff_hours * 3600 else 1.0


def weekend_variance() -> float:
    if is_fast_pace():
        return 1.0
    return 0.7 if datetime.now(_MSK).weekday() >= 5 else 1.0


def delay_multiplier(state) -> float:
    """0.7 activity means longer delays, not 30% faster requests."""
    if is_fast_pace():
        return 1.0
    return post_captcha_rate_cut(state) / weekend_variance()

"""Read-only history of saved captcha images and the answers submitted for them."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

from app import storage

_NAME = re.compile(r'(\d{8}T\d{6})_(?:(local-rejected|llm-rejected)_)?([\w-]+)\.png')


def _name_parts(name):
    if not isinstance(name, str):
        raise ValueError('Invalid sample name')
    match = _NAME.fullmatch(name)
    if not match:
        raise ValueError('Invalid sample name')
    at = datetime.strptime(match[1], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
    return at, match[2], match[3]


def sample_path(filename):
    """Only regular archived PNG files inside captcha_samples may be served."""
    _name_parts(filename)
    folder = (storage.DATA_DIR / 'captcha_samples').resolve()
    path = folder / filename
    if path.is_symlink() or not path.is_file() or path.resolve().parent != folder:
        raise ValueError('Sample not found')
    return path.resolve()


def _rows(path):
    try:
        with open(path, encoding='utf-8') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def _timestamp(value, fallback):
    try:
        at = datetime.fromisoformat(value)
        return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
    except (ValueError, TypeError):
        return fallback


def _source(value):
    value = {'dashboard': 'gui'}.get(value, value) if isinstance(value, str) else None
    return value if value in ('local', 'llm', 'gui', 'telegram', 'tg_manual') else 'unknown'


def list_attempts(limit=20):
    """Return newest saved attempts, including legacy samples without journal links."""
    limit = max(1, min(int(limit), 100))
    folder = storage.DATA_DIR / 'captcha_samples'
    labels = {row['file']: row for row in _rows(folder / 'labels.jsonl')
              if isinstance(row.get('file'), str)}
    events = {}
    legacy_events = {}
    for row in _rows(storage.DATA_DIR / 'captcha_events.jsonl'):
        if row.get('event') != 'solve':
            continue
        if isinstance(row.get('sample'), str):
            events[row['sample']] = row
        elif (at := _timestamp(row.get('t'), None)) is not None:
            legacy_events.setdefault((int(at.timestamp()), _source(row.get('path'))), []).append(row)

    attempts = []
    for path in folder.glob('*.png'):
        try:
            at, kind, answer = _name_parts(path.name)
            sample_path(path.name)
        except (ValueError, OSError):
            continue
        # The optional numeric suffix only disambiguates equal names in one second.
        answer = re.sub(r'_\d+$', '', answer).replace('-', ' ')
        label = labels.get(path.name, {})
        source = kind.split('-')[0] if kind else _source(label.get('source'))
        event = events.get(path.name)
        linked = event is not None
        if not linked:
            candidates = legacy_events.get((int(at.timestamp()), source), [])
            event = candidates[0] if len(candidates) == 1 else {}
        at = _timestamp(event.get('t') or label.get('t'), at)
        exact_answer = event.get('answer', label.get('answer'))
        if isinstance(exact_answer, str):
            answer = exact_answer
        ok = event.get('ok')
        if not isinstance(ok, bool):
            ok = False if kind else True if label else None
        reason = event.get('reason')
        account = event.get('acc')
        attempts.append({
            'sample': path.name,
            'image_url': '/api/captcha/samples/' + quote(path.name, safe=''),
            'answer': answer,
            'at': at.astimezone(timezone.utc).isoformat(timespec='seconds'),
            'source': _source(event.get('path')) if event.get('path') else source,
            'ok': ok,
            'reason': reason if isinstance(reason, str) else None,
            'account': account if isinstance(account, str) else None,
            'legacy': not linked,
        })
    return sorted(attempts, key=lambda row: (row['at'], row['sample']), reverse=True)[:limit]

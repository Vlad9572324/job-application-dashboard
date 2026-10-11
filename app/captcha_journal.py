"""Append-only captcha journal: when HH challenges, in what context, how solving went.

One JSON line per event in data/captcha_events.jsonl:
- challenge: a new HH challenge was recorded (+ applies in the last 1h/24h, MSK hour)
- solve:     an answer was submitted (path: llm / telegram / tg_manual / dashboard)
- resume:    a human confirmed continuation (dashboard / Telegram button)
Recording never raises: the journal must not affect captcha handling itself.
"""
import json
import statistics
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import storage
from app.logging_utils import log_debug

_MSK = ZoneInfo("Europe/Moscow")
_LOCK = threading.Lock()


def _path():
    return storage.DATA_DIR / "captcha_events.jsonl"


def _apply_stamps(acc_name):
    storage._load_cache()
    with storage._cache_lock:
        records = list(((storage._cache_applied or {}).get(acc_name) or {}).values())
    stamps = []
    for record in records:
        try:
            stamps.append(datetime.fromisoformat(record.get("at", "")).astimezone(timezone.utc))
        except (ValueError, TypeError, AttributeError):
            continue
    return stamps


def _applies_around(acc_name, now):
    try:
        stamps = _apply_stamps(acc_name)
    except Exception:
        return None, None
    return (sum(now - timedelta(hours=1) <= s <= now for s in stamps),
            sum(now - timedelta(hours=24) <= s <= now for s in stamps))




def save_sample(image, answer, kind="", source=""):
    """Keep captchas with their answer to benchmark auto-solvers offline. Never purged.

    kind="" — an answer HH accepted (ground truth, any solver: human or LLM); the exact
    text goes to captcha_samples/labels.jsonl next to the image;
    kind="llm-rejected" — the LLM consensus HH refused (to study its mistakes).
    """
    try:
        text = "-".join("".join(ch for ch in word if ch.isalnum()) for word in str(answer or "").split())[:40]
        if not image or not text:
            return
        folder = storage.DATA_DIR / "captcha_samples"
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        name = f"{now.strftime('%Y%m%dT%H%M%S')}_{kind + '_' if kind else ''}{text}.png"
        with _LOCK:
            target = folder / name
            n = 1
            while target.exists():  # concurrent images must not overwrite each other
                target = folder / name.replace(".png", f"_{n}.png")
                n += 1
            target.write_bytes(image)
            if not kind:
                entry = {"t": now.isoformat(timespec="seconds"), "file": target.name,
                         "answer": str(answer).strip(), "source": source or None}
                with open(folder / "labels.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return target.name
    except Exception as exc:
        log_debug(f"captcha sample: {type(exc).__name__}")


def record(event, acc=None, **fields):
    try:
        now = datetime.now(timezone.utc)
        acc = acc or {}
        entry = {"t": now.isoformat(timespec="seconds"), "msk_hour": now.astimezone(_MSK).hour,
                 "event": event, "acc": str(acc.get("short") or acc.get("name") or "")}
        if event == "challenge":
            entry["applies_1h"], entry["applies_24h"] = _applies_around(acc.get("name", ""), now)
            entry["acc_name"] = str(acc.get("name") or "")
        entry.update({k: v for k, v in fields.items() if v is not None})
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with _LOCK, open(_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:
        log_debug(f"captcha journal: {type(exc).__name__}")


def _load(days):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = []
    try:
        with open(_path(), encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    e["_t"] = datetime.fromisoformat(e["t"])
                except (ValueError, KeyError, TypeError):
                    continue
                if e["_t"] >= since:
                    events.append(e)
    except OSError:
        pass
    return sorted(events, key=lambda e: e["_t"])


_week_cache = {"at": 0.0, "value": None}


def llm_week() -> dict:
    """7-day automatic captcha stats (legacy keys kept for existing clients)."""
    import time
    if _week_cache["value"] is not None and time.monotonic() - _week_cache["at"] < 60:
        return _week_cache["value"]
    events = _load(7)
    llm = [e for e in events if e["event"] == "solve" and e.get("path") in ('llm', 'local')]
    value = {"challenges": sum(e["event"] == "challenge" for e in events),
             "llm_attempts": len(llm), "llm_solved": sum(bool(e.get("ok")) for e in llm)}
    _week_cache.update(at=time.monotonic(), value=value)
    return value


def summary(days=7) -> dict:
    events = _load(days)
    challenges = [e for e in events if e["event"] == "challenge"]
    solves = [e for e in events if e["event"] == "solve"]
    per_day = Counter(e["_t"].astimezone(_MSK).date().isoformat() for e in challenges)
    by_hour = Counter(e.get("msk_hour") for e in challenges)
    a1 = [e["applies_1h"] for e in challenges if isinstance(e.get("applies_1h"), int)]
    a24 = [e["applies_24h"] for e in challenges if isinstance(e.get("applies_24h"), int)]
    paths = defaultdict(lambda: {"attempts": 0, "ok": 0})
    for s in solves:
        p = paths[s.get("path") or "unknown"]
        p["attempts"] += 1
        p["ok"] += bool(s.get("ok"))
    # How long a "successful" solve actually held: time to the next challenge.
    held, quick_return = [], 0
    for s in (s for s in solves if s.get("ok")):
        nxt = next((c for c in challenges if c["_t"] > s["_t"] and c.get("acc") == s.get("acc")), None)
        if nxt:
            gap_min = (nxt["_t"] - s["_t"]).total_seconds() / 60
            held.append(gap_min)
            quick_return += gap_min < 10
    # The KPI that matters: how many applications HH lets through per captcha.
    budget = []
    for prev, cur in zip(challenges, challenges[1:]):
        if prev.get("acc") != cur.get("acc") or not cur.get("acc_name"):
            continue
        stamps = _apply_stamps(cur["acc_name"])
        budget.append(sum(prev["_t"] < s <= cur["_t"] for s in stamps))
    return {
        "days": days,
        "applies_between_challenges": budget,
        "median_applies_between_challenges": statistics.median(budget) if budget else None,
        "challenges": len(challenges),
        "per_day": dict(sorted(per_day.items())),
        "by_msk_hour": dict(sorted(by_hour.items())),
        "median_applies_1h": statistics.median(a1) if a1 else None,
        "median_applies_24h": statistics.median(a24) if a24 else None,
        "solves_by_path": {k: dict(v) for k, v in sorted(paths.items())},
        "median_hours_until_next_challenge": round(statistics.median(held) / 60, 1) if held else None,
        "ok_solves_followed_by_challenge_within_10min": quick_return,
    }


def summary_text(days=7) -> str:
    s = summary(days)
    lines = [f"🔐 Капчи за {days} дн.: {s['challenges']}"]
    if s["per_day"]:
        lines.append("По дням: " + ", ".join(f"{d[5:]}: {n}" for d, n in s["per_day"].items()))
    if s["by_msk_hour"]:
        lines.append("По часам МСК: " + ", ".join(f"{h}ч: {n}" for h, n in s["by_msk_hour"].items()))
    if s["median_applies_1h"] is not None:
        lines.append(f"Откликов перед капчей (медиана): {s['median_applies_1h']}/час, {s['median_applies_24h']}/сутки")
    for path, p in s["solves_by_path"].items():
        lines.append(f"Решение {path}: {p['ok']}/{p['attempts']} приняты HH")
    if s["median_applies_between_challenges"] is not None:
        lines.append(f"Откликов между капчами (медиана): {s['median_applies_between_challenges']} "
                     f"— {s['applies_between_challenges'][-8:]}")
    return "\n".join(lines)

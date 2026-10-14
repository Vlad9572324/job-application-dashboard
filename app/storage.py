"""
Data storage: applied vacancies, tests, interviews, browser sessions.
In-memory cache with async disk persistence.
"""

import json
import copy
import errno
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path


def _atomic_write_json(path: Path, data) -> None:
    """Durable atomic write: tmp → fsync file → replace → fsync dir.

    Аудит 2026-08-17 #2: раньше writers делали open+dump+replace без flush/
    fsync — Python буфер уходил в page cache, потеря питания хоста давала
    старую версию файла или пустой tmp. fsync-цепочка гарантирует, что после
    возврата данные ФИЗИЧЕСКИ на диске.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    dir_fd = None
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError as exc:
                # Unsupported fsync is different from a real disk/write error.
                # Transactional callers must not accept an EIO/ENOSPC as saved.
                if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS):
                    raise
        os.replace(tmp, path)
        # fsync родительского каталога — иначе rename может быть потерян
        # даже если файл сфсинкан.
        directory_flag = getattr(os, "O_DIRECTORY", None)
        if directory_flag is not None:
            try:
                dir_fd = os.open(str(path.parent), directory_flag)
                os.fsync(dir_fd)
            except OSError as exc:
                if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS):
                    raise
    finally:
        if dir_fd is not None:
            try:
                os.close(dir_fd)
            except OSError:
                pass
        # Cleanup осиротевшего tmp если replace не выполнился (raise до него)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass

from app.logging_utils import log_debug
from app.config import hh_base

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True, mode=0o700)
try:
    DATA_DIR.chmod(0o700)
except Exception:
    pass

APPLIED_FILE = DATA_DIR / "applied_vacancies.json"
TESTS_FILE = DATA_DIR / "test_required_vacancies.json"
QUESTIONNAIRE_TRACE_FILE = DATA_DIR / "questionnaire_trace.jsonl"
INTERVIEWS_FILE = DATA_DIR / "interviews.json"
SESSIONS_FILE = DATA_DIR / "browser_sessions.json"

# Единый pool для всех async-сохранений вместо fire-and-forget threading.Thread.
# Без pool каждый upsert/save спавнит новый thread (8MB stack) под нагрузкой растёт без bound (swarm-11 #2).
# Один FIFO-worker сохраняет порядок snapshots: более старое состояние не
# сможет записаться после нового и «откатить» config/accounts на диске.
_save_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="storage-save")

_INTERVIEWS_MAX = 10000
_INTERVIEWS_EVICT = 1000
_APPLIED_MAX = 100000
_APPLIED_EVICT = 1000
EVENTS_FILE = DATA_DIR / "events.jsonl"

def _schedule_save(fn, *, wait: bool = False):
    """Async-save: submit на shared pool вместо нового Thread каждый раз.
    Per-save lock с blocking=False уже защищает от concurrent дублей.

    Round-3 #2: если executor уже shutdown (bot.stop() пошёл, а поздний
    worker всё ещё пытается писать через add_applied) — раньше молча
    дропали запись. Теперь вызываем sync inline как последний шанс:
    данные попадут на диск ДО exit'а процесса.
    """
    try:
        future = _save_executor.submit(fn)
    except RuntimeError:
        if wait:
            return fn()  # A transactional caller must see write failures.
        try:
            fn()  # sync fallback — writer уже atomic, безопасно
        except Exception as e:
            log_debug(f"_schedule_save sync fallback error: {e}")
        return
    if wait:
        return future.result()


# ============================================================
# КЕШ В ПАМЯТИ (избегаем постоянного чтения с диска)
# ============================================================

_cache_applied: dict = None
_cache_tests: dict = None
_cache_interviews: dict = None  # keyed by neg_id
_cache_lock = threading.Lock()
_tmp_cleaned = False  # _cleanup_stale_tmp should run once, not on every _load_cache (kimi-r14-1 #4)


def _cleanup_stale_tmp():
    """Удалить .tmp файлы оставшиеся от прерванной записи (process crash mid-replace).
    Иначе они копятся бесконечно (kimi-r13-2 #6) + ломают save_config ошибкой
    'temp file exists' при попытке tmp.replace() через перезапуск."""
    global _tmp_cleaned
    if _tmp_cleaned:
        return
    _tmp_cleaned = True
    # Включая config.tmp + accounts.tmp + oauth_tokens.tmp — иначе их leak ловится
    # в логе как «save_config error» хотя реальное сохранение проходит (GitHub issue).
    files = [APPLIED_FILE, TESTS_FILE, INTERVIEWS_FILE, SESSIONS_FILE]
    for extra in ("config.json", "accounts.json", "oauth_tokens.json"):
        files.append(DATA_DIR / extra)
    for fpath in files:
        tmp = fpath.with_suffix(".tmp")
        try:
            if tmp.exists():
                tmp.unlink()
                log_debug(f"startup: removed stale {tmp}")
        except (PermissionError, OSError):
            pass


def _load_cache():
    """Загрузить кеш из файлов (один раз при старте)"""
    global _cache_applied, _cache_tests, _cache_interviews
    _cleanup_stale_tmp()
    with _cache_lock:
        if _cache_applied is None:
            if APPLIED_FILE.exists():
                try:
                    with open(APPLIED_FILE, "r", encoding="utf-8") as f:
                        _cache_applied = json.load(f)
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    log_debug(f"⚠️ Ошибка загрузки {APPLIED_FILE}: {e}")
                    _cache_applied = {}
            else:
                _cache_applied = {}
            if not isinstance(_cache_applied, dict):
                _cache_applied = {}
        if _cache_tests is None:
            if TESTS_FILE.exists():
                try:
                    with open(TESTS_FILE, "r", encoding="utf-8") as f:
                        _cache_tests = json.load(f)
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    log_debug(f"⚠️ Ошибка загрузки {TESTS_FILE}: {e}")
                    _cache_tests = {}
            else:
                _cache_tests = {}
            if not isinstance(_cache_tests, dict):
                _cache_tests = {}
        if _cache_interviews is None:
            if INTERVIEWS_FILE.exists():
                try:
                    with open(INTERVIEWS_FILE, "r", encoding="utf-8") as f:
                        _cache_interviews = json.load(f)
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    log_debug(f"⚠️ Ошибка загрузки {INTERVIEWS_FILE}: {e}")
                    _cache_interviews = {}
            else:
                _cache_interviews = {}
            if not isinstance(_cache_interviews, dict):
                _cache_interviews = {}


# Аудит 2026-08-17 #7 #8: раньше save с blocking=False просто дропался, если
# другой save уже шёл — но снапшот того save был сделан ДО mutation, поэтому
# новая запись безвозвратно теряла свой шанс на диск. Ввели dirty-флаги + loop:
# после успешного write ещё раз проверяем dirty под lock; если mutation
# случилась во время write — сохраняем повторно, до конвергенции.
_save_applied_lock = threading.Lock()
_save_tests_lock = threading.Lock()
_save_interviews_lock = threading.Lock()
_applied_dirty = False
_tests_dirty = False
_interviews_dirty = False
# Round-4 #1: монотонный mutation seq (инкрементим на КАЖДОЙ mutation под
# _cache_lock). Writer captureит seq на snapshot; в finally сравнивает
# — если latest > snapshot значит concurrent mutation была, resubmit нужен
# даже после write_failed (иначе dirty застревает до следующей mutation).
_applied_mut_seq = 0
_tests_mut_seq = 0
_interviews_mut_seq = 0
_SEQ_MAP = {
    "_applied_dirty": "_applied_mut_seq",
    "_tests_dirty": "_tests_mut_seq",
    "_interviews_dirty": "_interviews_mut_seq",
}


def _drain_and_write(lock, dirty_name: str, get_cache, path):
    """Общий loop: пока dirty — snapshot → write → повтор.

    Round-2 #7: finally re-submit если внешняя mutation случилась.
    Round-3 #1: разделили write-fail от live-dirty, чтобы не hot-loop
    при постоянной disk-error.
    Round-4 #1: mut_seq различает «наш failed write восстановил dirty»
    от «concurrent add_applied выставил dirty». Без seq после fail'а мы
    suppressили resubmit даже если пришла новая mutation — данные
    застревали в памяти до следующей mutation или shutdown/crash.
    """
    if not lock.acquire(blocking=False):
        return
    resubmit_fn = _RESUBMIT_MAP[dirty_name]
    seq_name = _SEQ_MAP[dirty_name]
    write_failed = False
    seen_seq_when_failed = 0
    try:
        while True:
            with _cache_lock:
                if not globals()[dirty_name]:
                    return
                data = copy.deepcopy(get_cache()) if get_cache() else ({} if isinstance(get_cache(), dict) or get_cache() is None else [])
                globals()[dirty_name] = False
                snap_seq = globals()[seq_name]
            try:
                _atomic_write_json(path, data)
            except Exception as e:
                log_debug(f"_drain_and_write({dirty_name}) error: {e}")
                with _cache_lock:
                    globals()[dirty_name] = True
                write_failed = True
                seen_seq_when_failed = snap_seq
                return
    finally:
        # Round-5 #2: раньше проверяли dirty/seq ДО release — TOCTOU-окно
        # между read и release позволяло mutation'у попасть в него: она
        # инкрементит seq и вызывает _schedule_save, worker падает на
        # blocking=False acquire (наш lock ещё занят), мы принимаем решение
        # по устаревшему latest_seq → resubmit не делаем → mutation навсегда.
        # Fix: сначала release, ЗАТЕМ читаем актуальный seq. Mutation в
        # новом окне между release и read инициирует свой _schedule_save,
        # который теперь спокойно возьмёт lock. Никакой mutation не теряется.
        lock.release()
        with _cache_lock:
            still_dirty = bool(globals()[dirty_name])
            latest_seq = globals()[seq_name]
        # Resubmit если:
        # - dirty без failure = concurrent mutation ждёт (round-2 #7)
        # - dirty после failure но latest_seq > snap = внешняя mutation
        #   была во время нашего fail'а (round-4 #1).
        if still_dirty and (not write_failed or latest_seq > seen_seq_when_failed):
            _schedule_save(resubmit_fn)


def _save_applied_async():
    _drain_and_write(_save_applied_lock, "_applied_dirty",
                     lambda: _cache_applied, APPLIED_FILE)


def _save_tests_async():
    _drain_and_write(_save_tests_lock, "_tests_dirty",
                     lambda: _cache_tests, TESTS_FILE)


def _save_interviews_async():
    _drain_and_write(_save_interviews_lock, "_interviews_dirty",
                     lambda: _cache_interviews, INTERVIEWS_FILE)


# Map dirty-flag → resubmit target. Заполнен ниже, после определения функций.
_RESUBMIT_MAP: dict = {}
_RESUBMIT_MAP["_applied_dirty"] = _save_applied_async
_RESUBMIT_MAP["_tests_dirty"] = _save_tests_async
_RESUBMIT_MAP["_interviews_dirty"] = _save_interviews_async


def upsert_interview(neg_id: str, acc: str, acc_color: str = "",
                     employer: str = "", vacancy_title: str = "",
                     employer_last_msg: str = None, needs_reply: bool = None,
                     llm_reply: str = None, llm_sent: bool = None,
                     chat_not_found: bool = None, chat_status: str = None,
                     replied_msg_id: str = None,
                     vacancy_id: str = ""):
    """Создать или обновить запись об интервью-переговоре."""
    global _interviews_dirty, _interviews_mut_seq
    _load_cache()
    now = datetime.now().isoformat(timespec="seconds")
    with _cache_lock:
        _interviews_dirty = True
        _interviews_mut_seq += 1
        existing = _cache_interviews.get(neg_id, {})
        record = dict(existing)
        record["neg_id"] = neg_id
        if acc:
            record["acc"] = acc
        if acc_color:
            record["acc_color"] = acc_color
        if employer:
            record["employer"] = employer
        if vacancy_title:
            record["vacancy_title"] = vacancy_title
        if vacancy_id:
            record["vacancy_id"] = str(vacancy_id)
        if "first_seen" not in record:
            record["first_seen"] = now
        record["last_seen"] = now
        if employer_last_msg is not None:
            record["employer_last_msg"] = employer_last_msg
            record["employer_last_msg_date"] = now
        if needs_reply is not None:
            record["needs_reply"] = needs_reply
        if llm_reply is not None:
            record["llm_reply"] = llm_reply
            record["llm_reply_date"] = now
        if llm_sent is not None:
            # Never downgrade: once llm_sent=True, keep it
            if not record.get("llm_sent"):
                record["llm_sent"] = llm_sent
        # Persisted dedup key: last msg_id we successfully replied to.
        # Used by LLM loop to skip after restart (in-memory dedup is lost).
        if replied_msg_id:
            record["replied_msg_id"] = str(replied_msg_id)
        if chat_not_found is True:
            record["chat_not_found"] = True  # never reset — chat is permanently closed
        if chat_status is not None:
            record["chat_status"] = chat_status
        # Detect new employer message: if employer_last_msg changed vs what was already replied,
        # allow status to go back to pending_reply so the new message gets handled
        employer_msg_changed = (
            employer_last_msg is not None
            and employer_last_msg != existing.get("employer_last_msg")
            and bool(employer_last_msg)
        )
        # Derive status
        if record.get("chat_not_found"):
            record["status"] = "chat_closed"  # 409: permanently closed, never retried
        elif existing.get("status") == "replied" and not employer_msg_changed:
            # Keep "replied" only if no new employer message arrived
            record["status"] = "replied"
        elif record.get("llm_reply") and not employer_msg_changed:
            record["status"] = "replied" if record.get("llm_sent") else "draft"
        elif record.get("needs_reply") is False:
            record["status"] = "no_reply_needed"
        else:
            record["status"] = "pending_reply"
        _cache_interviews[neg_id] = record
        if len(_cache_interviews) > _INTERVIEWS_MAX:
            protected = {
                nid for nid, r in _cache_interviews.items()
                if r.get("llm_sent") and r.get("replied_msg_id")
            }
            candidates = [
                (r.get("last_seen", ""), nid)
                for nid, r in _cache_interviews.items()
                if nid not in protected
            ]
            candidates.sort()
            for _, nid in candidates[:_INTERVIEWS_EVICT]:
                del _cache_interviews[nid]
    _schedule_save(_save_interviews_async)


def get_no_chat_neg_ids(since: datetime = None) -> set:
    """Return set of neg_ids where chatik permanently returned 409 (chat doesn't exist)."""
    _load_cache()
    since_str = since.isoformat(timespec="seconds") if since else None
    with _cache_lock:
        return {
            nid for nid, r in _cache_interviews.items()
            if r.get("chat_not_found")
            and (not since_str or r.get("last_seen", "") >= since_str)
        }


def get_replied_keys(since: datetime = None) -> set:
    """Persisted LLM dedup: returns {(neg_id, replied_msg_id)} for chats already replied to.
    Used to seed `state.llm_replied_msgs` on startup so we don't re-reply after restart.

    Legacy compat: pre-r1 records have llm_sent=True but no replied_msg_id.
    Backfill with a sentinel `__legacy__` token — это блокирует повторный reply
    на ЛЮБОЙ msg_id для такого neg_id (что важнее, чем точная дедупликация для старых).
    """
    _load_cache()
    since_str = since.isoformat(timespec="seconds") if since else None
    with _cache_lock:
        keys = set()
        for nid, r in _cache_interviews.items():
            if not r.get("llm_sent"):
                continue
            if since_str and r.get("last_seen", "") < since_str:
                continue
            replied_id = r.get("replied_msg_id")
            if replied_id:
                keys.add((str(nid), str(replied_id)))
            else:
                # legacy без replied_msg_id — добавляем sentinel + last_msg_id если есть
                # чтобы новый цикл точно НЕ переотправил.
                keys.add((str(nid), "__legacy__"))
                last_id = r.get("last_msg_id") or r.get("employer_last_msg_id")
                if last_id:
                    keys.add((str(nid), str(last_id)))
        return keys


def get_interviews_list(acc: str = "", limit: int = 2000, status: str = "") -> list:
    """Вернуть список интервью, сортировка: pending_reply first, затем по дате desc."""
    _load_cache()
    with _cache_lock:
        items = list(_cache_interviews.values())
    if acc:
        items = [r for r in items if r.get("acc") == acc]
    if status:
        items = [r for r in items if r.get("status") == status or r.get("chat_status") == status]
    status_order = {"pending_reply": 0, "draft": 1, "replied": 2, "chat_closed": 3, "no_reply_needed": 4}
    # Сначала по дате desc, потом stable sort по статусу — pending всегда первые
    items.sort(key=lambda r: r.get("last_seen", "") or "", reverse=True)
    items.sort(key=lambda r: status_order.get(r.get("status", ""), 9))
    # Если pending переполняют limit — replied/draft вылетали за границу и UI
    # показывал 0 отвеченных при десятках реально отправленных. Гарантируем
    # что все не-pending попадают в выборку: pending clip'ается, остальные
    # добавляются полностью.
    if len(items) > limit and not status:
        head = items[:limit]
        head_ids = {r.get("neg_id") for r in head}
        tail_non_pending = [
            r for r in items[limit:]
            if r.get("status") not in ("pending_reply", None)
            and r.get("neg_id") not in head_ids
        ]
        return head + tail_non_pending
    return items[:limit]


def load_browser_sessions() -> list:
    """Загрузить браузерные сессии из файла."""
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                sessions = json.load(f)
            if not isinstance(sessions, list):
                return []
            from app.session_migration import backup_file, deduplicate_sessions, write_json_atomic
            merged, removed = deduplicate_sessions(sessions)
            if removed:
                backup = backup_file(SESSIONS_FILE)
                write_json_atomic(SESSIONS_FILE, merged)
                log_debug(f"browser sessions migration: merged {removed} duplicate(s); backup={backup}")
            return merged
        except Exception as e:
            # Раньше swallowили silently — пользователь терял ВСЕ сессии без сообщения.
            log_debug(f"⚠️ Не могу прочитать {SESSIONS_FILE}: {type(e).__name__}: {e}")
    return []


_save_sessions_lock = threading.Lock()


def _strip_sensitive_session_fields(s: dict) -> dict:
    """Удалить raw cookie line из сохранённого snapshot — иначе он лежит в
    browser_sessions.json в открытом виде (kimi-search-3 #8)."""
    out = {k: v for k, v in s.items() if k not in (
        "_raw_cookie_line", "raw_cookie_line", "_mutation_guard", "_pinned_resume_id")}
    return out


_sessions_pending_snapshot: list | None = None
_sessions_pending_seq: int = 0        # монотонный счётчик самого свежего pending
_sessions_written_seq: int = 0        # последний seq, который записан на диск
_sessions_pending_lock = threading.Lock()


def save_browser_sessions(sessions: list, *, wait: bool = False):
    """Сохранить браузерные сессии; ``wait`` нужен для transactional flows.

    Аудит round-1 #3: два worker'а в executor могли писать snapshot'ы в
    произвольном порядке — старый затирал свежий. Round-2 #8: deepcopy
    делался ДО pending_lock; A могла закончить deepcopy ПОСЛЕ того как B
    уже записала свой более свежий snapshot, и перезаписать pending старым.
    Fix: монотонный seq в момент захвата pending_lock; writer сравнивает.
    """
    global _sessions_pending_snapshot, _sessions_pending_seq
    target_file = SESSIONS_FILE
    with _sessions_pending_lock:
        # Capture and sequence assignment must be one ordered operation: an
        # older, slow deepcopy must not receive a newer sequence after a
        # transactional receipt-attempt reservation has already been saved.
        snapshot = [_strip_sensitive_session_fields(copy.deepcopy(s)) for s in sessions]
        _sessions_pending_seq += 1
        my_seq = _sessions_pending_seq
        _sessions_pending_snapshot = snapshot
    def _write():
        global _sessions_pending_snapshot, _sessions_pending_seq, _sessions_written_seq
        with _save_sessions_lock:
            while True:
                with _sessions_pending_lock:
                    pending = _sessions_pending_snapshot
                    seq = _sessions_pending_seq
                    if pending is None or seq <= _sessions_written_seq:
                        return
                    _sessions_pending_snapshot = None
                    # Помечаем seq как «в процессе записи» СРАЗУ, чтобы
                    # параллельный save с меньшим seq не мог его откатить.
                    pending_seq = seq
                try:
                    _atomic_write_json(target_file, pending)
                    _restrict_perms(target_file)
                    with _sessions_pending_lock:
                        if pending_seq > _sessions_written_seq:
                            _sessions_written_seq = pending_seq
                except Exception as e:
                    log_debug(f"save_browser_sessions error: {e}")
                    # Восстанавливаем pending если никто не залил свежее.
                    with _sessions_pending_lock:
                        if _sessions_pending_snapshot is None or _sessions_pending_seq < pending_seq:
                            _sessions_pending_snapshot = pending
                            _sessions_pending_seq = pending_seq
                    if wait:
                        raise
                    return
    if wait:
        _write()
    else:
        _schedule_save(_write)


def _restrict_perms(path):
    """0o600 на чувствительные файлы: oauth_tokens, browser_sessions, config, accounts."""
    try:
        import os as _os
        _os.chmod(path, 0o600)
    except Exception:
        pass


def count_applied_on_day(account_name: str, day: str) -> int:
    """Count persisted applications by Moscow day, including legacy local dates."""
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('Europe/Moscow')
    _load_cache()
    with _cache_lock:
        records = list((_cache_applied or {}).get(account_name, {}).values())
    count = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            stamp = datetime.fromisoformat(str(record.get('at', '')))
            # Historical naive timestamps were written in the server's local TZ.
            if stamp.astimezone(zone).date().isoformat() == day:
                count += 1
        except (ValueError, TypeError, OverflowError):
            continue
    return count


def add_applied(account_name: str, vacancy_id: str, info: dict = None, *, confirmed: bool = True):
    global _applied_dirty, _applied_mut_seq
    _load_cache()
    with _cache_lock:
        _applied_dirty = True
        _applied_mut_seq += 1  # round-4 #1: seq для отличия concurrent от fail-restored
        if account_name not in _cache_applied:
            _cache_applied[account_name] = {}
        existing = _cache_applied[account_name].get(vacancy_id, {})
        new_info = info or {}
        # Preserve existing title/company if new info has empty values
        title = new_info.get("title") or existing.get("title", "")
        company = new_info.get("company") or existing.get("company", "")
        _cache_applied[account_name][vacancy_id] = {
            "url": f"{hh_base()}/vacancy/{vacancy_id}",
            "title": title,
            "company": company,
            "salary_from": new_info.get("salary_from") or existing.get("salary_from"),
            "salary_to": new_info.get("salary_to") or existing.get("salary_to"),
            # Discovering an existing application does not date it to today.
            "at": existing.get('at') or (datetime.now().astimezone().isoformat() if confirmed else '')
        }
        total = sum(len(v) for v in _cache_applied.values())
        if total > _APPLIED_MAX:
            candidates = []
            for acc_name, vacancies in _cache_applied.items():
                for vid, item in vacancies.items():
                    candidates.append((item.get("at", ""), acc_name, vid))
            candidates.sort()
            for _, acc_name, vid in candidates[:_APPLIED_EVICT]:
                del _cache_applied[acc_name][vid]
                if not _cache_applied[acc_name]:
                    del _cache_applied[acc_name]
    _schedule_save(_save_applied_async)


def add_test_vacancy(vacancy_id: str, title: str = "", company: str = "",
                     account_name: str = "", resume_hash: str = ""):
    global _tests_dirty, _tests_mut_seq
    _load_cache()
    with _cache_lock:
        if vacancy_id not in _cache_tests:
            _tests_dirty = True
            _tests_mut_seq += 1
            _cache_tests[vacancy_id] = {
                "url": f"{hh_base()}/vacancy/{vacancy_id}",
                "title": title,
                "company": company,
                "account_name": account_name,
                "resume_hash": resume_hash,
                "at": datetime.now().isoformat()
            }
    _schedule_save(_save_tests_async)


def is_applied(account_name: str, vacancy_id: str) -> bool:
    _load_cache()
    with _cache_lock:
        return vacancy_id in _cache_applied.get(account_name, {})


def is_test(vacancy_id: str) -> bool:
    _load_cache()
    with _cache_lock:
        return vacancy_id in _cache_tests


def get_questionnaire_rejection_counts(account_name: str) -> dict[str, int]:
    """Restore confirmed redirects to the form, so restarting cannot retry them forever."""
    counts: dict[str, int] = {}
    if not QUESTIONNAIRE_TRACE_FILE.exists():
        return counts
    try:
        with QUESTIONNAIRE_TRACE_FILE.open(encoding="utf-8") as source:
            for line in source:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if (not isinstance(event, dict) or event.get("account") != account_name
                        or event.get("stage") != "submission_response"):
                    continue
                details = event.get("details") or {}
                if isinstance(details, dict) and details.get("redirect_to_form") is True:
                    vid = str(event.get("vacancy_id") or "")
                    if vid.isdigit():
                        counts[vid] = counts.get(vid, 0) + 1
    except OSError as exc:
        log_debug(f"Questionnaire rejection history unavailable: {type(exc).__name__}")
    return counts


def get_test_vacancy_stats() -> dict:
    """Count unique known test vacancies and unique test vacancies applied to."""
    _load_cache()
    with _cache_lock:
        test_ids = set(_cache_tests or {})
        applied_test_ids = set()
        for vacancies in (_cache_applied or {}).values():
            applied_test_ids.update(test_ids.intersection(vacancies))
    return {"found": len(test_ids), "applied": len(applied_test_ids)}


def get_stats() -> dict:
    _load_cache()
    with _cache_lock:
        applied = _cache_applied or {}
        tests = _cache_tests or {}
    total = sum(len(v) for v in applied.values())
    by_acc = {k: len(v) for k, v in applied.items()}
    return {"total": total, "tests": len(tests), "by_acc": by_acc}


def get_applied_list(limit: int = 300) -> list:
    """Получить список последних откликов"""
    _load_cache()
    with _cache_lock:
        applied = {k: dict(v) for k, v in (_cache_applied or {}).items()}
    all_items = []
    for acc_name, vacancies in applied.items():
        for vid, info in vacancies.items():
            all_items.append({
                "account": acc_name,
                "vacancy_id": vid,
                "url": info.get("url", f"{hh_base()}/vacancy/{vid}"),
                "title": info.get("title", ""),
                "company": info.get("company", ""),
                "salary_from": info.get("salary_from"),
                "salary_to": info.get("salary_to"),
                "at": info.get("at", "")
            })
    all_items.sort(key=lambda x: x.get("at", ""), reverse=True)
    return all_items[:limit]


def get_vacancy_db(limit: int = 3000) -> list:
    """Объединённая база: applied + tests, с полем status per account."""
    _load_cache()
    with _cache_lock:
        tests = dict(_cache_tests or {})
        applied = {k: dict(v) for k, v in (_cache_applied or {}).items()}

    # vacancy_id -> {title, company, url, at, is_test, applied_by: [acc_names]}
    db: dict[str, dict] = {}

    # Сначала заполняем из applied
    for acc_name, vacancies in applied.items():
        for vid, info in vacancies.items():
            if vid not in db:
                db[vid] = {
                    "vacancy_id": vid,
                    "url": info.get("url", f"{hh_base()}/vacancy/{vid}"),
                    "title": info.get("title", ""),
                    "company": info.get("company", ""),
                    "at": info.get("at", ""),
                    "is_test": vid in tests,
                    "applied_by": [],
                }
            db[vid]["applied_by"].append(acc_name)
            # Обновляем title/company если были пустые
            if not db[vid]["title"]:
                db[vid]["title"] = info.get("title", "")
            if not db[vid]["company"]:
                db[vid]["company"] = info.get("company", "")

    # Добавляем тест-вакансии которых нет в applied
    for vid, info in tests.items():
        if vid not in db:
            db[vid] = {
                "vacancy_id": vid,
                "url": info.get("url", f"{hh_base()}/vacancy/{vid}"),
                "title": info.get("title", ""),
                "company": info.get("company", ""),
                "at": info.get("at", ""),
                "is_test": True,
                "applied_by": [],
            }
        else:
            db[vid]["is_test"] = True

    # Определяем статус
    for vid, item in db.items():
        if item["applied_by"] and item["is_test"]:
            item["status"] = "test_passed"   # 📝 тест пройден
        elif item["applied_by"]:
            item["status"] = "sent"           # ✅ откликнулись
        else:
            item["status"] = "test_pending"   # 🧪 тест не пройден

    items = sorted(db.values(), key=lambda x: x.get("at", ""), reverse=True)
    return items[:limit]


def get_test_list(limit: int = 300) -> list:
    """Получить список вакансий с тестами"""
    _load_cache()
    with _cache_lock:
        tests = dict(_cache_tests or {})
        applied = dict(_cache_applied or {})
    # Build reverse lookup: vacancy_id -> list of account_names that applied
    applied_by: dict[str, list[str]] = {}
    for acc_name, vacancies in applied.items():
        for vid in vacancies:
            applied_by.setdefault(vid, []).append(acc_name)
    items = []
    for vid, info in tests.items():
        items.append({
            "vacancy_id": vid,
            "url": info.get("url", f"{hh_base()}/vacancy/{vid}"),
            "title": info.get("title", ""),
            "company": info.get("company", ""),
            "account_name": info.get("account_name", ""),
            "resume_hash": info.get("resume_hash", ""),
            "applied_by": applied_by.get(vid, []),
            "at": info.get("at", "")
        })
    items.sort(key=lambda x: x.get("at", ""), reverse=True)
    return items[:limit]


def record_event(kind: str, **fields):
    """Append one JSON line to events.jsonl (append-only forensics log)."""
    line = {"kind": kind, "ts": datetime.now().isoformat(timespec="seconds")}
    line.update(fields)
    def _write():
        try:
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            log_debug(f"record_event error: {e}")
    _schedule_save(_write)

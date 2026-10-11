"""Watch HH challenges and retry local recognition or deliver manual checks."""
import asyncio
import logging
import math
import time
from urllib.parse import parse_qs, urlsplit

from app import captcha, captcha_journal
from app.config import CONFIG
from app.captcha_llm import recognize_captcha
from app.captcha_solver import (captcha_submit_delay, fetch_captcha_image,
                                refresh_captcha_image, submit_captcha)
from app.telegram_bot import TelegramCaptchaBot

logger = logging.getLogger(__name__)


class CaptchaCoordinator:
    def __init__(self, bot_manager, bot):
        self.manager = bot_manager
        self.bot = bot
        self.pending = {}
        bot_manager.telegram_captcha_coordinator = self
        self._seen = set()
        self._lock = asyncio.Lock()
        bot.resolver = self.resolve

    def account(self, key):
        for state in list(self.manager.account_states) + list(self.manager.temp_states.values()):
            if getattr(state, '_deleted', False):
                continue
            if key in (str(state.acc.get('user_id', '')), str(state.acc.get('resume_hash', ''))):
                return state.acc
        return None

    def close(self, automatic_only=False):
        """Close idle sessions; running attempts temporarily own theirs locally."""
        for cid, item in list(self.pending.items()):
            if not automatic_only or item.get('automatic'):
                self._close_session(item.get('session'))
                item['session'] = None
                self.pending.pop(cid, None)
                self._seen.discard(cid)
                self.bot.forget(cid)
        if not automatic_only:
            gui = getattr(self, 'gui_pending', {})
            for cid, item in list(gui.items()):
                self._close_session(item.get('session'))
                item['session'] = None
                gui.pop(cid, None)

    async def scan(self):
        async with self._lock:
            with captcha.LOCK:
                records = captcha._read()
            active = {record.get('id') for record in records.values()}
            self._seen.intersection_update(active)
            for cid in list(self.pending):
                if cid not in active:
                    item = self.pending.pop(cid, None)
                    self._close_session(item.get('session'))
                    self.bot.forget(cid)
            # GUI entries are human-owned, independent of Telegram images.
            # A completed/replaced/expired challenge must not leak its session.
            gui = getattr(self, 'gui_pending', {})
            for cid, item in list(gui.items()):
                if cid not in active or time.monotonic() - item.get('created', 0) > 600:
                    self._close_session(gui.pop(cid).get('session'))
            for key, record in records.items():
                cid = record.get('id')
                acc = self.account(key)
                if not cid or acc is None:
                    item = self.pending.pop(cid, None)
                    if item:
                        self._close_session(item.get('session'))
                    item = gui.pop(cid, None)
                    if item:
                        self._close_session(item.get('session'))
                    self.bot.forget(cid)
                    continue
                if record.get('manual_only'):
                    lease = record.get('auto_retry_until')
                    if (CONFIG.captcha_llm_enabled and acc is not None
                            and isinstance(lease, (int, float)) and lease <= time.time()):
                        captcha.release_manual(acc, cid)
                        item = self.pending.pop(cid, None)
                        if item:
                            self._close_session(item.get('session'))
                        item = gui.pop(cid, None)
                        if item:
                            self._close_session(item.get('session'))
                        self._seen.discard(cid)
                        self.bot.forget(cid)
                        record = captcha.current(acc)
                        if record.get('id') != cid or record.get('manual_only'):
                            continue
                    else:
                        item = self.pending.pop(cid, None)
                        if item:
                            self._close_session(item.get('session'))
                        self.bot.forget(cid)
                        continue
                if CONFIG.captcha_llm_enabled:
                    await self._scan_local(cid, key, record, acc)
                    continue
                if self.pending.get(cid, {}).get('automatic'):
                    self._close_session(self.pending.pop(cid).get('session'))
                    self._seen.discard(cid)
                if cid in self.pending and acc is not None and not self.pending[cid]['captcha_key']:
                    item = self.pending[cid]
                    if time.monotonic() < item.get('retry_at', 0):
                        continue
                    try:
                        await self.photo(cid, item, acc)
                        item.pop('retry_delay', None)
                        self._seen.add(cid)
                    except Exception as exc:
                        self._schedule_retry(item, exc)
                    continue
                if not cid or cid in self._seen or acc is None:
                    continue
                query = parse_qs(urlsplit(captcha.browser_url(record)).query)
                if not query.get('state'):
                    await self.bot.send_message('Капчу HH нужно решить вручную: ' + captcha.browser_url(record))
                    try:
                        await self.bot.send_browser_option(
                            cid, acc.get('short') or acc.get('name') or 'HH', captcha.browser_url(record))
                    except Exception:
                        pass
                    self._seen.add(cid)
                    continue
                item = dict(acc_key=key, captcha_state=query['state'][0],
                            backurl='https://hh.ru/', failurl=captcha.browser_url(record),
                            url=captcha.browser_url(record), fails=0,
                            captcha_key=None, session=None,
                            challenge_url=record.get('captcha_url', ''))
                self.pending[cid] = item
                try:
                    await self.photo(cid, item, acc)
                except Exception as exc:
                    self._schedule_retry(item, exc)
                    continue
                self._seen.add(cid)

    async def _scan_local(self, cid, key, record, acc):
        item = self.pending.get(cid)
        if not item or not item.get('automatic'):
            if item:
                self._close_session(item.get('session'))
                self.bot.forget(cid)
            item = dict(acc_key=key, automatic=True, captcha_key=None, session=None,
                        fails=0, challenge_url=captcha.browser_url(record))
            self.pending[cid] = item
        reason = record.get('local_retry_reason', '')
        if reason in ('recaptcha', 'missing_state'):
            self._close_session(item.get('session'))
            item['session'] = None
            item['llm_result'] = {'status': 'blocked', 'reason': reason, 'retry_seconds': 0}
            return
        delay = max(0, math.ceil(record.get('local_retry_at', 0) - time.time()))
        if delay:
            item['llm_result'] = {**item.get('llm_result', {}), 'status': 'retry',
                                  'reason': reason, 'retry_seconds': delay}
            return
        item['challenge_url'] = captcha.browser_url(record)
        query = parse_qs(urlsplit(item['challenge_url']).query)
        attempt = int(record.get('local_attempts') or 0) + 1
        if not query.get('state'):
            self._close_session(item.get('session'))
            item['session'] = None
            self._retry_local(cid, item, acc, attempt, 'missing_state', 0)
            return
        item['captcha_state'] = query['state'][0]
        item['llm_result'] = {'status': 'reading', 'retry_seconds': 0}
        await self._local_attempt(cid, item, acc, attempt)

    def _retry_local(self, cid, item, acc, attempt, reason, delay, answer=None):
        captcha.set_local_retry(acc, cid, delay, reason, attempt)
        item['llm_result'] = {'status': 'blocked' if reason in ('recaptcha', 'missing_state') else 'retry',
                              'reason': reason, 'retry_seconds': delay}
        if answer:
            item['llm_result']['answer'] = answer
        item['retry_delay'] = delay
        item['retry_at'] = time.monotonic() + delay
        if reason == 'recaptcha':
            self._log(acc, 'HH запросил reCAPTCHA — откройте проверку вручную', 'warning')
        elif reason != 'missing_state':
            self._log(acc, f'Локальная модель повторит капчу через {delay} сек. ({reason})', 'info')

    @staticmethod
    def _network_delay(attempt):
        return min(600, 30 * 2 ** min(max(0, attempt - 1), 5))

    async def _local_attempt(self, cid, item, acc, attempt):
        # An active thread owns this session until it returns. Keeping it out of
        # pending prevents shutdown/manual cleanup from closing it mid-request.
        session = item.get('session')
        session_reused = session is not None
        item['session'] = None
        keep_session = False
        try:
            if session is None:
                fetch = asyncio.create_task(asyncio.to_thread(fetch_captcha_image, acc, item['challenge_url']))
            else:
                fetch = asyncio.create_task(asyncio.to_thread(
                    refresh_captcha_image, session, item['captcha_state'],
                    item.get('backurl') or 'https://hh.ru/'))
            try:
                session, key, image, state, backurl = await asyncio.shield(fetch)
            except asyncio.CancelledError:
                active_session = session
                def close_fetched(done):
                    fetched_session = active_session
                    try:
                        result = done.result()
                        if fetched_session is None:
                            fetched_session = result[0]
                    except (Exception, asyncio.CancelledError):
                        pass
                    self._close_session(fetched_session)
                fetch.add_done_callback(close_fetched)
                session = None
                raise
            item.update(captcha_key=key, image=image,
                        captcha_state=state or item['captcha_state'],
                        backurl=backurl or 'https://hh.ru/', failurl=item['challenge_url'])
            current = captcha.current(acc)
            if current.get('id') != cid or current.get('manual_only') or not CONFIG.captcha_llm_enabled:
                return
            # The page bootstrap can replace an incoming state. Keep the next
            # image request aligned with that state without replacing the cid.
            captcha.update_challenge_state(acc, cid, item['captcha_state'])
            try:
                answer = await asyncio.to_thread(recognize_captcha, image)
            except Exception:
                answer = None
            if not answer:
                self._retry_local(cid, item, acc, attempt, 'model_unavailable', 30)
                return
            initial_wait_seconds = captcha_submit_delay(session)
            if initial_wait_seconds:
                item['llm_result'] = {'status': 'waiting', 'answer': answer,
                                      'retry_seconds': math.ceil(initial_wait_seconds)}
                await asyncio.sleep(initial_wait_seconds)
            current = captcha.current(acc)
            if (current.get('id') != cid or current.get('manual_only')
                    or not CONFIG.captcha_llm_enabled or self.pending.get(cid) is not item
                    or self.manager.telegram_captcha_coordinator is not self
                    or self.account(item['acc_key']) is not acc):
                return
            item['llm_result'] = {'status': 'submitting', 'answer': answer, 'retry_seconds': 0}
            submit = asyncio.create_task(asyncio.to_thread(
                submit_captcha, session, answer, key, item['captcha_state'],
                item['backurl'], item['failurl'], require_confirmation=True))
            try:
                ok, reason = await asyncio.shield(submit)
            except asyncio.CancelledError:
                active_session = session
                def close_submitted(done):
                    if not done.cancelled():
                        try:
                            done.exception()
                        except Exception:
                            pass
                    self._close_session(active_session)
                submit.add_done_callback(close_submitted)
                session = None
                raise
            if not ok:
                captcha.update_challenge_state(acc, cid, getattr(session, 'hh_captcha_next_state', None))
            sample = (captcha_journal.save_sample(image, answer, source='local') if ok else
                      captcha_journal.save_sample(image, answer, kind='local-rejected', source='local'))
            captcha_journal.record('solve', acc, path='local', ok=ok, reason=reason or None, id=cid,
                                   answer=answer, sample=sample, session_reused=session_reused,
                                   initial_wait_seconds=round(initial_wait_seconds, 3),
                                   diagnostic=getattr(session, 'hh_captcha_diagnostic', None))
            current = captcha.current(acc)
            if current.get('id') != cid or current.get('manual_only'):
                return
            if ok:
                captcha.clear(acc, cid)
                CONFIG.captcha_llm_solved += 1
                self.pending.pop(cid, None)
                self._seen.discard(cid)
                self.bot.forget(cid)
                gui = getattr(self, 'gui_pending', {})
                if cid in gui:
                    self._close_session(gui.pop(cid).get('session'))
                try:
                    await asyncio.to_thread(self.manager.resume_challenge_account, item['acc_key'])
                except Exception:
                    pass
                self._log(acc, f'Капча решена локальной моделью («{answer}») — отклики возобновлены', 'success')
                try:
                    await self.bot.send_message(
                        f'Капча HH решена локальной моделью («{answer}») для '
                        f'{acc.get("short") or acc.get("name") or "аккаунта"} — отклики возобновлены')
                except Exception:
                    logger.warning('TG notification after local captcha solve failed')
                return
            if reason == 'recaptcha':
                delay = 0
            elif reason == 'http_429':
                retry_after = getattr(session, 'hh_captcha_retry_after', 0)
                delay = max(60, math.ceil(retry_after) if isinstance(retry_after, (int, float)) else 0)
            elif reason == 'isBot':
                delay = min(60, 5 * 2 ** min(max(0, attempt - 1), 4))
            else:
                delay = self._network_delay(attempt)
            self._retry_local(cid, item, acc, attempt, reason or 'unconfirmed_response', delay, answer)
            keep_session = reason == 'isBot'
        except Exception as exc:
            retry_after = getattr(exc, 'retry_after', 0)
            is_rate_limit = isinstance(exc, ValueError) and str(exc).endswith('_http_429')
            delay = (max(60, math.ceil(retry_after) if isinstance(retry_after, (int, float)) else 0)
                     if is_rate_limit else self._network_delay(attempt))
            self._retry_local(cid, item, acc, attempt, 'http_429' if is_rate_limit else 'network_error', delay)
            logger.warning('Local captcha attempt failed (%s); retry in %ss', type(exc).__name__, delay)
        finally:
            try:
                current = captcha.current(acc)
            except Exception:
                current = {}
            if (keep_session and session is not None and CONFIG.captcha_llm_enabled
                    and self.pending.get(cid) is item and current.get('id') == cid
                    and not current.get('manual_only')):
                item['session'] = session
            else:
                self._close_session(session)
                item['session'] = None
            item['captcha_key'] = None

    @staticmethod
    def _schedule_retry(item, exc):
        # Every retry is 3 requests to HH's captcha endpoints; a tight loop
        # during a TG/HH outage looks exactly like a bot.
        delay = min(600, max(30, item.get('retry_delay', 15) * 2))
        item['retry_delay'] = delay
        item['retry_at'] = time.monotonic() + delay
        logger.warning('HH captcha delivery failed (%s); retry in %ss', type(exc).__name__, delay)

    async def photo(self, cid, item, acc):
        self._close_session(item.get('session'))
        item['captcha_key'] = None
        item['session'] = None
        session, key, image, state, backurl = await asyncio.to_thread(
            fetch_captcha_image, acc, item['challenge_url'])
        item['captcha_state'] = state or item['captcha_state']
        item['backurl'] = backurl or item['backurl']
        note = ''
        try:
            result = await self.bot.push_challenge(cid, acc.get('short') or acc.get('name') or 'HH', image, note=note)
        except Exception:
            self._close_session(session)
            raise
        if not result:
            self._close_session(session)
            raise RuntimeError('TG bot disabled')
        if not item.get('forwarded'):
            CONFIG.captcha_llm_forwarded += 1
            item['forwarded'] = True
        if not item.get('browser_option_sent'):
            item['browser_option_sent'] = True
            try:
                await self.bot.send_browser_option(
                    cid, acc.get('short') or acc.get('name') or 'HH', item.get('url'))
            except Exception:
                pass
        item['captcha_key'] = key
        item['image'] = image
        item['session'] = session
        try:
            self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                                  '📱 Капча отправлена в Telegram — жду ответа', 'info')
        except Exception:
            pass

    @staticmethod
    def _close_session(session):
        try:
            session.close()
        except Exception:
            pass

    def _log(self, acc, message, level):
        try:
            self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'), message, level)
        except Exception:
            pass

    async def resolve(self, cid, text):
        async with self._lock:
            item = self.pending.get(cid)
            if item is None or item.get('automatic'):
                return
            acc = self.account(item['acc_key'])
            if acc is not None and captcha.current(acc).get('manual_only'):
                await self.bot.send_message('Проверка переведена в ручной режим. Откройте «Нужна капча» в меню и отвечайте на новую картинку.')
                return
            if acc is None or captcha.current(acc).get('id') != cid:
                self.pending.pop(cid, None)
                self.bot.forget(cid)
                return
            if not item['captcha_key']:
                await self.photo(cid, item, acc)
                return
            if item.get('session') is None:
                # session потерялась (например worker перезапустился) — грузим свежую.
                await self.photo(cid, item, acc)
                return
            ok, reason = await asyncio.to_thread(
                submit_captcha, item['session'], text, item['captcha_key'], item['captcha_state'],
                item['backurl'], item['failurl'])
            captcha_journal.record('solve', acc, path='telegram', ok=ok, reason=reason or None, id=cid)
            if ok:
                captcha_journal.save_sample(item.get('image'), text, source='telegram')
            if ok:
                # HH подтвердил через 302 на backurl → снимаем challenge и
                # будим worker'а. GUI-panel скроется через syncAccountCard.
                captcha.clear(acc, cid)
                try:
                    await asyncio.to_thread(self.manager.resume_challenge_account, item['acc_key'])
                except Exception:
                    pass
                self.pending.pop(cid, None)
                # Чистим и GUI-сессию если была параллельно открыта — картинка/session там stale.
                gui = getattr(self, 'gui_pending', None)
                if gui and cid in gui:
                    try:
                        s = gui[cid].get('session')
                        if s is not None:
                            s.close()
                    except Exception:
                        pass
                    gui.pop(cid, None)
                self.bot.forget(cid)
                try:
                    self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                                          '✅ Капча пройдена (Telegram) — отклики возобновлены', 'success')
                except Exception:
                    pass
                await self.bot.send_message('✅ Капча HH решена, отклики возобновлены')
                return
            item['fails'] += 1
            try:
                self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                                      f'❌ Капча не принята HH (попытка {item["fails"]}/3, reason={reason})', 'warning')
            except Exception:
                pass
            # Сообщение в TG что ответ отклонён — иначе юзер видит только
            # новую картинку (editMessageMedia) без объяснения почему.
            try:
                await self.bot.send_message(
                    f'❌ Ответ неверный (попытка {item["fails"]}/3). '
                    f'HH прислал новую капчу — введите ответ ниже.'
                )
            except Exception:
                pass
            if reason == 'recaptcha' or item['fails'] >= 3:
                logger.warning('HH captcha requires manual resolution')
                self.pending.pop(cid, None)
                self.bot.forget(cid)
                try:
                    self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                                          '⚠ Капча усложнилась (reCAPTCHA/3 попытки) — решите вручную по ссылке', 'error')
                except Exception:
                    pass
                await self.bot.send_message('капча HH усложнилась (возможно reCAPTCHA), решите вручную по ссылке: ' + item['url'])
                return
            await self.photo(cid, item, acc)


async def captcha_orchestrator(bot_manager):
    """Reconfigure polling on settings changes; cancel and close HTTP on shutdown."""
    bot = None
    coordinator = None
    signature = None
    try:
        while True:
            current = (CONFIG.telegram_bot_token, CONFIG.telegram_chat_id, CONFIG.telegram_captcha_enabled)
            if current != signature:
                if bot:
                    await bot.stop()
                if coordinator is not None:
                    coordinator.close()
                bot = TelegramCaptchaBot()
                bot_manager.telegram_captcha_bot = bot
                coordinator = CaptchaCoordinator(bot_manager, bot)
                signature = current
                if current[2]:
                    await bot.start()
            if not CONFIG.captcha_llm_enabled:
                coordinator.close(automatic_only=True)
            if CONFIG.captcha_llm_enabled or (current[2] and bot._task):
                try:
                    await coordinator.scan()
                except Exception:
                    logger.warning('HH captcha scan failed; will retry')
            await asyncio.sleep(3)
    finally:
        if coordinator is not None:
            coordinator.close()
        if bot:
            await bot.stop()
        bot_manager.telegram_captcha_bot = None
        bot_manager.telegram_captcha_coordinator = None

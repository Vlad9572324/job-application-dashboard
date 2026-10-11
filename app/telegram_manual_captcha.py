"""Human-only Telegram recovery. No OCR, retries, applications or auto-resume."""
import asyncio
import json
import time
import secrets
import math
from collections import OrderedDict
from contextlib import suppress
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from app import captcha
from app.captcha_solver import fetch_captcha_image, submit_captcha, verify_manual_completion


class ManualCaptchaFlow:
    def __init__(self, manager, bot):
        self.manager, self.bot = manager, bot
        self.lock = asyncio.Lock()
        self.items = {}
        self.cooldown = {}
        self.retired = OrderedDict()

    def _close_item(self, item):
        # A cancelled Telegram poll must not close a requests.Session while its
        # worker thread is still using it. The completion callback closes it.
        task = item.get('in_flight')
        if task is not None and not task.done():
            item['close_requested'] = True
        elif not item.get('closed'):
            item['closed'] = True
            with suppress(Exception):
                item['session'].close()

    def _retire(self, token):
        item = self.items.pop(token)
        self._close_item(item)
        key = (item['chat'], item['mid'])
        self.retired[key] = None
        self.retired.move_to_end(key)
        while len(self.retired) > 256:
            self.retired.popitem(last=False)

    def _prune(self):
        now = time.monotonic()
        for token, item in list(self.items.items()):
            if now - item['created'] > 600:
                self._retire(token)
        self.cooldown = {cid: until for cid, until in self.cooldown.items() if until > now}

    async def _request(self, item, function, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        item['in_flight'] = task
        def finished(done):
            # Consume exceptions even if the Telegram poll was cancelled.
            if not done.cancelled():
                done.exception()
            if item.get('in_flight') is done:
                item.pop('in_flight', None)
            if item.get('close_requested'):
                self._close_item(item)
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    def states(self):
        return list(enumerate(self.manager.account_states)) + [
            (len(self.manager.account_states) + i, s) for i, s in self.manager.temp_states.items()]

    def find(self, cid):
        for idx, state in self.states():
            if not getattr(state, '_deleted', False) and captcha.current(state.acc).get('id') == cid:
                return idx, state
        return None, None

    async def message(self, chat, text, buttons=None):
        fields = {'chat_id': str(chat), 'text': text}
        if buttons:
            fields['reply_markup'] = json.dumps({'inline_keyboard': [[b] for b in buttons]})
        return await self.bot._call('sendMessage', fields)

    def close(self):
        for token in list(self.items):
            self._retire(token)
        self.cooldown.clear()

    async def menu(self, chat):
        async with self.lock:
            return await self._menu(chat)

    async def _menu(self, chat):
        self._prune()
        buttons = []
        for idx, state in self.states():
            if getattr(state, '_deleted', False):
                continue
            record = captcha.current(state.acc)
            if record:
                confirmed = next((token for token, item in self.items.items()
                    if item['cid'] == record['id']
                    and item['status'] == 'confirmed' and time.monotonic() - item['created'] <= 600), None)
                if confirmed:
                    buttons.append({'text': f'✅ Аккаунт {idx + 1}: подтвердить продолжение',
                                    'callback_data': 'mc_resume:' + confirmed})
                    continue
                waiting = next((item for item in self.items.values()
                    if item['cid'] == record['id'] and item['chat'] == str(chat)
                    and item['status'] == 'waiting'), None)
                if waiting:
                    await self.bot._call('sendMessage', {'chat_id': str(chat),
                        'text': f'✍ Аккаунт {idx + 1}: картинка ждёт ответа. '
                                'Выберите «Ответить» на неё и введите символы. Загружать заново не нужно.',
                        'reply_to_message_id': waiting['mid'], 'allow_sending_without_reply': True})
                buttons.append({'text': f'🔐 Аккаунт {idx + 1}: ' + ('новая картинка' if waiting else 'показать капчу'),
                                'callback_data': 'mc_open:' + record['id']})
        await self.message(chat, 'Выберите проверку. Ответ вводится вручную через «Ответить» на новую картинку.'
                           if buttons else 'Активных проверок нет.', buttons)

    async def open(self, chat, cid):
        coordinator = getattr(self.manager, 'telegram_captcha_coordinator', None)
        if coordinator is not None:
            async with coordinator._lock:
                return await self._open(chat, cid)
        return await self._open(chat, cid)

    async def _open(self, chat, cid):
        async with self.lock:
            self._prune()
            _, state = self.find(cid)
            if state is None:
                return await self.message(chat, 'Эта проверка устарела. Откройте меню заново.')
            # A verified shared result belongs to the account, not one chat.
            # Do not replace it with a new image when another member joins.
            confirmed = next((token for token, item in self.items.items()
                              if item['cid'] == cid and item['status'] == 'confirmed'), None)
            if confirmed:
                return await self.message(chat, '✅ Участник уже прошёл проверку: HH подтвердил ответ. '
                    'Отклики ещё на паузе.', [
                    {'text': '▶ Подтверждаю продолжение откликов', 'callback_data': 'mc_resume:' + confirmed}])
            remaining = self.cooldown.get(cid, 0) - time.monotonic()
            if remaining > 0:
                waiting = next((item for item in self.items.values()
                    if item['cid'] == cid and item['chat'] == str(chat)
                    and item['status'] == 'waiting'), None)
                fields = {'chat_id': str(chat), 'text':
                    f'Новую картинку можно запросить через {math.ceil(remaining)} с. '
                    'Это ограничение нашего бота, не блокировка HH. Пауза сохранена.'}
                if waiting:
                    fields['text'] += ' Картинка уже загружена — ответьте на неё через «Ответить».'
                    fields['reply_to_message_id'] = waiting['mid']
                    fields['allow_sending_without_reply'] = True
                else:
                    fields['text'] += ' После ожидания нажмите «Новая картинка» ещё раз.'
                return await self.bot._call('sendMessage', fields)
            self.cooldown[cid] = time.monotonic() + 10
            for token, old in list(self.items.items()):
                if old['cid'] == cid:
                    self._retire(token)
            record = captcha.current(state.acc)
            # Persist ownership: restarts must not hand this human flow to OCR
            # or silently resume an older Telegram request.
            captcha.claim_manual(state.acc, cid)
            url = captcha.browser_url(record)
            if not url:
                return await self.message(chat, 'Ссылка проверки не сохранена. Откройте карточку аккаунта.')
            # A generic redirect to the homepage must not count as proof.
            success_url = 'https://hh.ru/?manual_captcha_return=' + secrets.token_hex(16)
            parts = urlsplit(url)
            query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != 'backurl']
            query.append(('backurl', success_url))
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
            await self.message(chat, 'Загружаю новую картинку. Старые ответы больше не принимаются.')
            session = None
            item = None
            try:
                fetch = asyncio.create_task(asyncio.to_thread(fetch_captcha_image, state.acc, url))
                try:
                    session, key, image, challenge_state, _ = await asyncio.shield(fetch)
                except asyncio.CancelledError:
                    def close_fetched(done):
                        if not done.cancelled():
                            with suppress(Exception):
                                done.result()[0].close()
                    fetch.add_done_callback(close_fetched)
                    raise
                if self.find(cid)[1] is not state:
                    session.close()
                    return await self.message(chat, 'Проверка изменилась. Откройте меню заново.')
                photo = await self.bot._call('sendPhoto', {'chat_id': str(chat),
                    'caption': 'Ответьте на ЭТУ картинку через «Ответить». Отклики остаются на паузе.',
                    'reply_markup': json.dumps({'force_reply': True})}, image)
                token = secrets.token_hex(12)
                item = self.items[token] = dict(cid=cid, chat=str(chat), mid=photo['message_id'],
                    session=session, key=key, state=challenge_state, url=url, image=image,
                    success_url=success_url,
                    created=time.monotonic(), status='waiting')
                # The photo is already usable. Losing this optional help message
                # must not destroy the live session or report a failed download.
                with suppress(Exception):
                    await self.message(chat, 'Если пропустили ввод — вернитесь к этому сообщению. '
                        'При необходимости загрузите новую картинку.', [
                        {'text': '🔄 Новая картинка', 'callback_data': 'mc_open:' + cid},
                        {'text': 'Открыть оригинал HH', 'url': url}])
            except asyncio.CancelledError:
                if session is not None and item is None:
                    with suppress(Exception):
                        session.close()
                raise
            except Exception:
                if session is not None:
                    with suppress(Exception):
                        session.close()
                await self.message(chat, 'Картинку загрузить не удалось. Пауза сохранена.',
                                   [{'text': 'Пройти вручную на HH', 'url': url}])

    async def answer(self, chat, mid, text):
        async with self.lock:
            self._prune()
            match = next(((token, item) for token, item in self.items.items()
                          if item['chat'] == str(chat) and item['mid'] == mid), None)
            if match is None:
                if (str(chat), mid) in self.retired:
                    await self.message(chat, 'Ответ не отправлен: эта картинка уже заменена или устарела. '
                                       'Отправьте /captcha, чтобы открыть текущую проверку.')
                    return True
                return False
            token, item = match
            _, state = self.find(item['cid'])
            if state is None or time.monotonic() - item['created'] > 600 or item['status'] != 'waiting':
                await self.message(chat, 'Ответ не отправлен: картинка устарела или уже обработана. Откройте «Нужна капча» заново.')
                return True
            if not isinstance(text, str) or not text.strip() or len(text.strip()) > 200:
                await self.message(chat, 'Введите только символы с картинки через «Ответить» на неё. '
                                   'Ответ пока не отправлен; эту картинку можно использовать.')
                return True
            text = text.strip()
            item['status'] = 'submitted'  # Never replay, including after a network timeout.
            try:
                ok, reason = await self._request(item, submit_captcha, item['session'], text,
                    item['key'], item['state'], item['success_url'], item['url'], require_confirmation=True)
                if not ok and reason.startswith('unconfirmed'):
                    ok, reason = await self._request(item, verify_manual_completion,
                        item['session'], item['url'], item['success_url'])
            except Exception:
                ok, reason = False, 'unconfirmed_transport'
            if not ok:
                captcha.update_challenge_state(state.acc, item['cid'],
                    getattr(item['session'], 'hh_captcha_next_state', None))
            from app.captcha_journal import record as journal
            journal('solve', state.acc, path='tg_manual', ok=ok, reason=reason or None, id=item['cid'])
            if ok:
                from app.captcha_journal import save_sample
                save_sample(item.get('image'), text, source='tg_manual')
            if self.find(item['cid'])[1] is not state:
                self._retire(token)
                await self.message(chat, 'Проверка аккаунта изменилась во время отправки. '
                                   'Этот результат не снимает паузу. Отправьте /captcha для текущей проверки.')
            elif ok:
                item['status'] = 'confirmed'
                await self.message(chat, '✅ HH подтвердил ответ. Отправки ещё на паузе.',
                    [{'text': '▶ Подтверждаю продолжение откликов', 'callback_data': 'mc_resume:' + token}])
                idx, _ = self.find(item['cid'])
                short = state.acc.get('short') or state.acc.get('name') or f'аккаунт {idx + 1 if idx is not None else ""}'
                try:
                    await self.bot.send_message(
                        f'✅ Капча HH решена (Telegram) для {short} — ожидается подтверждение продолжения')
                except Exception:
                    pass
            else:
                label = ('❌ HH не принял ответ' if reason == 'isBot' else
                         '⚠ HH запросил другой вид проверки' if reason == 'recaptcha' else
                         '⚠ HH ограничил запросы' if reason == 'http_429' else
                         '⚠ Результат неизвестен')
                await self.message(chat, label + '. Пауза сохранена. Повторной отправки ответа не будет.', [
                    {'text': '🔄 Новая картинка', 'callback_data': 'mc_open:' + item['cid']},
                    {'text': 'Пройти на HH', 'url': item['url']}])
            return True

    async def resume(self, chat, token):
        async with self.lock:
            self._prune()
            item = self.items.get(token)
            # Subscriber authorization is enforced by TelegramCaptchaBot.
            # Any subscribed chat can confirm the shared account's continuation.
            if not item or item['status'] != 'confirmed':
                return await self.message(chat, 'Подтверждение устарело. Откройте проверку заново.')
            idx, state = self.find(item['cid'])
            if state is None:
                return await self.message(chat, 'Состояние аккаунта изменилось. Продолжение не выполнено.')
            if time.monotonic() - item['created'] > 600:
                return await self.message(chat, 'Подтверждение старше 10 минут. Откройте проверку заново; пауза сохранена.')
            from app.routes.accounts import api_account_captcha_continue
            class Confirmation:
                async def json(self): return {'confirmed': True, 'id': item['cid']}
            result = await api_account_captcha_continue(idx, Confirmation())
            if result.get('ok'):
                item['status'] = 'resumed'
                self._close_item(item)
            await self.message(chat, (result.get('message') or result.get('error') or 'Нет подтверждения продолжения') +
                (' Глобальная пауза остаётся включённой.' if getattr(self.manager, 'paused', False) else ''))

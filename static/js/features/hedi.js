// HH AI Hedi chat. Depends on State and esc-free DOM rendering from app.js.
const HediState = { idx: null, initialized: false, loading: false, poll: null };

function hediStatus(text, error = false) {
  const el = document.getElementById('hedi-status');
  if (!el) return;
  el.textContent = text;
  el.classList.toggle('error', error);
}

function hediAccounts() {
  const accounts = State.lastSnapshot?.accounts || [];
  const select = document.getElementById('hedi-account');
  if (!select) return;
  const selected = String(HediState.idx ?? select.value ?? '');
  select.replaceChildren(new Option('Выберите аккаунт', ''));
  accounts.forEach(acc => select.add(new Option(acc.name || acc.short || `Аккаунт ${acc.idx + 1}`, String(acc.idx))));
  if (accounts.some(acc => String(acc.idx) === selected)) select.value = selected;
  else if (HediState.idx !== null) {
    HediState.idx = null;
    document.getElementById('hedi-messages')?.replaceChildren();
    hediStatus('Выберите mobile-аккаунт для начала чата.');
  }
}

function initHediTab() {
  hediAccounts();
  if (!HediState.initialized) {
    HediState.initialized = true;
    const input = document.getElementById('hedi-input');
    input?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); hediSendMessage(); }
    });
    HediState.poll = setInterval(() => {
      if (State.currentTab === 'hedi' && HediState.idx !== null) hediLoadHistory(false);
    }, 30000);
  }
  if (HediState.idx === null) {
    const first = (State.lastSnapshot?.accounts || [])[0];
    if (first) { document.getElementById('hedi-account').value = String(first.idx); hediSelectAccount(first.idx); }
  }
}

function hediSelectAccount(idx) {
  if (idx === '' || idx === null || !Number.isInteger(Number(idx))) {
    HediState.idx = null;
    document.getElementById('hedi-messages')?.replaceChildren();
    hediStatus('Выберите mobile-аккаунт для начала чата.');
    return;
  }
  HediState.idx = Number(idx);
  hediLoadHistory(true);
}

function hediTime(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ru-RU', {hour:'2-digit', minute:'2-digit', day:'2-digit', month:'2-digit'});
}

function hediRender(messages) {
  const box = document.getElementById('hedi-messages');
  if (!box) return;
  box.replaceChildren();
  if (!messages.length) {
    const empty = document.createElement('div'); empty.className = 'hedi-empty';
    empty.textContent = 'История пуста. Спросите помощника о подходящих вакансиях.'; box.appendChild(empty); return;
  }
  messages.forEach(msg => {
    const user = msg.sender === 'applicant';
    const row = document.createElement('div'); row.className = `hedi-message ${user ? 'user' : 'bot'}`;
    const avatar = document.createElement('div'); avatar.className = 'hedi-avatar'; avatar.textContent = user ? '👤' : '🤖';
    const bubble = document.createElement('div'); bubble.className = 'hedi-bubble';
    const text = document.createElement('div'); text.textContent = msg.text || '';
    const time = document.createElement('div'); time.className = 'hedi-time'; time.textContent = hediTime(msg.timestamp || msg.created_at);
    bubble.append(text, time); row.append(avatar, bubble); box.appendChild(row);
  });
  box.scrollTop = box.scrollHeight;
}

async function hediLoadHistory(showLoading = true) {
  if (HediState.idx === null || HediState.loading) return;
  HediState.loading = true;
  if (showLoading) hediStatus('Загружаю историю…');
  try {
    let response = await fetch(`/api/account/${HediState.idx}/hedi/history?limit=50`);
    let data = await response.json();
    if (response.status === 409) {
      const started = await fetch(`/api/account/${HediState.idx}/hedi/start`, {method: 'POST'});
      const startData = await started.json();
      if (!started.ok) throw new Error(startData.detail || startData.error || `HTTP ${started.status}`);
      response = await fetch(`/api/account/${HediState.idx}/hedi/history?limit=50`);
      data = await response.json();
    }
    if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
    hediRender(data.messages || []);
    hediStatus('История обновлена');
  } catch (error) { hediStatus(error.message || 'Не удалось загрузить историю', true); }
  finally { HediState.loading = false; }
}

async function hediSendMessage() {
  const input = document.getElementById('hedi-input');
  const button = document.getElementById('hedi-send');
  const text = input?.value.trim() || '';
  if (HediState.idx === null) { hediStatus('Сначала выберите аккаунт.', true); return; }
  if (!text || button.disabled) return;
  button.disabled = true; hediStatus('Отправляю…');
  try {
    const response = await fetch(`/api/account/${HediState.idx}/hedi/send`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({text})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
    input.value = '';
    await hediLoadHistory(false);
    hediStatus('Сообщение отправлено');
  } catch (error) { hediStatus(error.message || 'Не удалось отправить сообщение', true); }
  finally { button.disabled = false; input.focus(); }
}

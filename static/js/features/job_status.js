// ── Job search status (Настройки → 🧭 Карьера → «🟢 Статус поиска работы») ──
// Рендерит контролы в #job-status-root и меняет статус через
// POST /api/account/{idx}/job_status. Данные текущего статуса берутся из
// GET /api/account/{idx}/diagnostics (поля status / status_label /
// available_statuses — см. app/routes/accounts.py + app/hh_resume.py).
// Грузится ПОСЛЕ app.js: использует глобальный State.lastSnapshot и esc().
//
// ВАЖНО: на DOMContentLoaded рендерятся только контролы — сетевых запросов
// нет. Сеть появляется только после того, как в State.lastSnapshot найдутся
// аккаунты (first-fill) или юзер сам сменит аккаунт в <select>.
(() => {
  'use strict';

  const JobStatusState = {
    rendered: false,
    accountsLoaded: false,
    pollTimer: null,
    reqSeq: 0, // монотонный счётчик: при быстром переключении аккаунтов
               // применяем только ответ последнего запроса
    selectionVersion: 0, // diagnostics не должен затирать ручной выбор
  };

  // esc() из app.js; fallback на случай загрузки без него.
  const _esc = (typeof esc === 'function')
    ? esc
    : (s) => String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/`/g, '&#96;');

  function jsEl(id) { return document.getElementById(id); }

  function jsAccounts() {
    return (typeof State !== 'undefined' && State && Array.isArray(State.lastSnapshot?.accounts))
      ? State.lastSnapshot.accounts : [];
  }

  // Строка результата: зелёный ok / красный error. textContent — без XSS.
  function jsResult(text, isError = false) {
    const el = jsEl('job-status-result');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = text ? (isError ? 'var(--red)' : 'var(--green)') : '';
  }

  // Только статическая разметка — без сети.
  function jsRender() {
    const root = jsEl('job-status-root');
    if (!root || JobStatusState.rendered) return;
    JobStatusState.rendered = true;
    root.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:10px;font-size:12px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <label for="job-status-account" style="color:var(--dim)">Аккаунт:</label>
          <select id="job-status-account" class="apply-input"
            style="font-size:12px;padding:4px 8px;min-width:180px"></select>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <span style="color:var(--dim)">Текущий статус:</span>
          <span id="job-status-current" style="font-weight:600">—</span>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <label for="job-status-select" style="color:var(--dim)">Новый статус:</label>
          <select id="job-status-select" class="apply-input" disabled
            style="font-size:12px;padding:4px 8px;min-width:220px"></select>
          <button id="job-status-apply" type="button" class="btn-sm" disabled
            style="font-size:12px;padding:4px 12px">Применить</button>
        </div>
        <div id="job-status-result" style="min-height:16px" aria-live="polite"></div>
      </div>`;
    jsEl('job-status-account')?.addEventListener('change', () => jsLoadDiagnostics());
    jsEl('job-status-select')?.addEventListener('change', () => { JobStatusState.selectionVersion += 1; });
    jsEl('job-status-apply')?.addEventListener('click', jsApply);
  }

  // Заполнить #job-status-account из State.lastSnapshot.accounts.
  // true, если аккаунты нашлись (поллинг после этого останавливается).
  function jsFillAccounts() {
    const select = jsEl('job-status-account');
    if (!select) return false;
    const accounts = jsAccounts();
    if (!accounts.length) {
      select.replaceChildren(new Option('Нет аккаунтов', ''));
      const current = jsEl('job-status-current'); if (current) current.textContent = '—';
      const statuses = jsEl('job-status-select'); if (statuses) { statuses.replaceChildren(); statuses.disabled = true; }
      const apply = jsEl('job-status-apply'); if (apply) apply.disabled = true;
      return false;
    }
    const prev = select.value;
    select.replaceChildren();
    accounts.forEach((acc, i) => {
      const label = acc.name || acc.short || `Аккаунт ${(acc.idx ?? i) + 1}`;
      select.add(new Option(label, String(acc.idx ?? i)));
    });
    if (accounts.some(a => String(a.idx) === prev)) select.value = prev;
    else select.value = String(accounts[0].idx ?? 0);
    return true;
  }

  // Поллинг State.lastSnapshot раз в ~500мс — максимум до первого успеха.
  function jsStartPolling() {
    if (JobStatusState.pollTimer || JobStatusState.accountsLoaded) return;
    JobStatusState.pollTimer = setInterval(() => {
      if (!jsEl('job-status-root')) { // контейнер исчез — поллинг не нужен
        clearInterval(JobStatusState.pollTimer);
        JobStatusState.pollTimer = null;
        return;
      }
      if (jsFillAccounts()) {
        clearInterval(JobStatusState.pollTimer);
        JobStatusState.pollTimer = null;
        JobStatusState.accountsLoaded = true;
        jsLoadDiagnostics(); // первое появление аккаунтов → грузим статус
      }
    }, 500);
  }

  // GET diagnostics → #job-status-current + #job-status-select.
  async function jsLoadDiagnostics() {
    const accSel = jsEl('job-status-account');
    if (!accSel || accSel.value === '') return;
    const idx = accSel.value;
    const seq = ++JobStatusState.reqSeq;
    const selectionVersion = JobStatusState.selectionVersion;
    const currentEl = jsEl('job-status-current');
    const statusSel = jsEl('job-status-select');
    const applyBtn = jsEl('job-status-apply');
    if (currentEl) currentEl.textContent = 'Загрузка…';
    jsResult('');
    try {
      const r = await fetch(`/api/account/${encodeURIComponent(idx)}/diagnostics`);
      let d = {};
      try { d = await r.json(); } catch (_) { /* не-JSON ответ */ }
      if (seq !== JobStatusState.reqSeq) return; // аккаунт уже переключили
      if (!r.ok || d.ok === false) {
        throw new Error(d.error || d.detail || `HTTP ${r.status}`);
      }
      if (currentEl) currentEl.textContent = d.status_label || d.status || '—';
      const avail = (d.available_statuses && typeof d.available_statuses === 'object')
        ? d.available_statuses : {};
      const keys = Object.keys(avail);
      if (statusSel) {
        const desiredStatus = selectionVersion === JobStatusState.selectionVersion
          ? d.status : statusSel.value;
        statusSel.replaceChildren();
        keys.forEach(k => statusSel.add(new Option(avail[k], k)));
        statusSel.disabled = !keys.length;
        if (desiredStatus && keys.includes(desiredStatus)) statusSel.value = desiredStatus;
      }
      if (applyBtn) applyBtn.disabled = !keys.length;
    } catch (e) {
      if (seq !== JobStatusState.reqSeq) return;
      if (currentEl) currentEl.textContent = '—';
      jsResult('❌ ' + (e && e.message ? e.message : 'Не удалось загрузить диагностику'), true);
    }
  }

  // POST /api/account/{idx}/job_status {"status": ...}
  async function jsApply() {
    const accSel = jsEl('job-status-account');
    const statusSel = jsEl('job-status-select');
    const btn = jsEl('job-status-apply');
    const idx = accSel?.value || '';
    const status = statusSel?.value || '';
    if (!idx || !status) { jsResult('❌ Выберите аккаунт и статус', true); return; }
    if (btn) btn.disabled = true;
    try {
      const r = await fetch(`/api/account/${encodeURIComponent(idx)}/job_status`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status}),
      });
      let d = {};
      try { d = await r.json(); } catch (_) { /* не-JSON ответ */ }
      if (!r.ok || d.ok === false) {
        throw new Error(d.error || d.detail || `HTTP ${r.status}`);
      }
      // An older diagnostics request must not overwrite the status just saved.
      JobStatusState.reqSeq += 1;
      const label = d.label || statusSel?.selectedOptions?.[0]?.text || status;
      jsResult('✅ ' + label);
      const cur = jsEl('job-status-current');
      if (cur) cur.textContent = label;
    } catch (e) {
      jsResult('❌ ' + (e && e.message ? e.message : 'Не удалось сменить статус'), true);
    } finally {
      if (btn) btn.disabled = !(statusSel && statusSel.options.length);
    }
  }

  function jsInit() {
    jsRender();
    if (jsFillAccounts()) {
      JobStatusState.accountsLoaded = true;
      jsLoadDiagnostics(); // аккаунты уже были в снапшоте к моменту старта
    } else {
      jsStartPolling();
    }
  }

  window.JobStatusSyncAccounts = jsFillAccounts;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', jsInit, {once: true});
  } else {
    jsInit();
  }
})();

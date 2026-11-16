(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('bank-sheet-data').textContent);
  const storageKey = 'freddy-bank-drafts-v1:' + config.user_id + ':' + config.currency;
  const tabs = document.getElementById('bank-tabs'), root = document.getElementById('bank-sheets');
  const summary = document.getElementById('bank-save-summary');
  let drafts = {};
  try { drafts = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (_) {}
  const states = new Map(), panels = new Map();
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const persist = () => { try { localStorage.setItem(storageKey, JSON.stringify(drafts)); } catch (_) { summary.textContent = 'No se puede conservar el borrador en este dispositivo'; } };
  const moneyLabel = config.money_label;
  const parse = value => {
    const raw = String(value).trim().replace(/ /g, '');
    const pattern = config.currency === 'USD' ? /^[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{1,2})?$/ : /^[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)$/;
    if (!pattern.test(raw)) return null;
    const n = Number(raw.replace(/\./g, '').replace(',', '.'));
    return Number.isFinite(n) && Math.abs(n) <= 9000000000000 ? n : null;
  };
  const fmt = n => Number(n).toLocaleString('es-PY', {maximumFractionDigits: config.currency === 'USD' ? 2 : 0});
  function markColor(input) {
    const n = parse(input.value);
    input.classList.toggle('bank-negative', n !== null && n < 0);
    input.classList.toggle('bank-positive', n !== null && n >= 0 && input.value.trim() !== '');
  }
  function formatAmount(input) {
    const raw = input.value, position = input.selectionStart;
    if (config.currency === 'USD') { markColor(input); return; }
    const count = raw.slice(0, position === null ? raw.length : position).replace(/[^0-9]/g, '').length;
    const n = parse(raw.replace(/\./g, ''));
    if (n !== null && raw.trim() !== '') {
      input.value = n === 0 && raw.trim().startsWith('-') ? '-0' : fmt(n);
      if (document.activeElement === input && position !== null) {
        let index = 0, digits = 0;
        while (index < input.value.length && digits < count) { if (/\d/.test(input.value[index])) digits++; index++; }
        if (count === 0 && input.value.startsWith('-')) index = 1;
        input.setSelectionRange(index, index);
      }
    }
    markColor(input);
  }
  const menu = el('div', 'bank-context-menu'); menu.hidden = true; menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', 'Opciones del movimiento');
  const editOption = el('button', '', 'Editar');
  for (const button of [editOption]) { button.type = 'button'; button.setAttribute('role', 'menuitem'); menu.append(button); }
  document.body.append(menu);
  let selectedAction;
  function closeMenu(restoreFocus = false) {
    const selected = selectedAction; selectedAction = null; menu.hidden = true;
    if (selected) { selected.row.classList.remove('bank-menu-selected'); if (restoreFocus) selected.trigger.focus(); }
  }
  function openMenu(row, trigger, actions, x, y) {
    closeMenu(); selectedAction = {row, trigger, ...actions}; row.classList.add('bank-menu-selected');
    menu.hidden = false;
    menu.style.left = Math.max(8, Math.min(x, window.innerWidth - (menu.offsetWidth || 170) - 8)) + 'px';
    menu.style.top = Math.max(8, Math.min(y, window.innerHeight - (menu.offsetHeight || 100) - 8)) + 'px';
    editOption.focus({preventScroll: true});
  }
  function rowActions(row, actions) {
    const trigger = el('button', 'bank-row-menu', '⋮'); trigger.type = 'button';
    trigger.setAttribute('aria-label', 'Opciones del movimiento'); trigger.setAttribute('aria-haspopup', 'menu');
    trigger.addEventListener('click', () => { const r = trigger.getBoundingClientRect(); openMenu(row, trigger, actions, r.left, r.bottom); });
    row.addEventListener('contextmenu', event => { event.preventDefault(); openMenu(row, trigger, actions, event.clientX, event.clientY); });
    row.addEventListener('keydown', event => {
      if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) { event.preventDefault(); trigger.click(); }
    });
    return trigger;
  }
  editOption.addEventListener('click', () => { const action = selectedAction; closeMenu(); if (action) { action.trigger.focus(); action.edit(); } });
  menu.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); editOption.focus(); }
    if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); }
    if (event.key === 'Tab') closeMenu();
  });
  document.addEventListener('pointerdown', event => { if (!menu.contains(event.target)) closeMenu(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(true); });
  window.addEventListener('scroll', () => closeMenu(), true); window.addEventListener('resize', () => closeMenu());
  function editLegacy(account, original) {
    const entry = account.entries.find(e => e.key === original.key) || original;
    if (!entry.can_edit) return;
    const overlay = el('div', 'bank-edit-overlay'), dialog = el('section', 'bank-edit-dialog');
    dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true');
    const heading = el('h3', '', 'Editar transferencia'); heading.id = 'bank-edit-title'; dialog.setAttribute('aria-labelledby', heading.id);
    const form = el('form'), description = el('input'), amount = el('input'), status = el('p', 'bank-help');
    description.value = entry.description; description.required = true; description.maxLength = 240;
    amount.value = fmt(Number(entry.raw_amount)); amount.required = true; amount.inputMode = config.currency === 'USD' ? 'decimal' : 'numeric';
    const label1 = el('label', '', 'Descripción'), label2 = el('label', '', 'Monto'); label1.append(description); label2.append(amount);
    amount.addEventListener('input', () => formatAmount(amount));
    const footer = el('div', 'bank-edit-buttons'), cancel = el('button', '', 'Cancelar'), submit = el('button', '', 'Guardar cambios');
    cancel.type = 'button'; submit.type = 'submit'; footer.append(cancel, submit); form.append(label1, label2, status, footer);
    dialog.append(heading, form); overlay.append(dialog);
    const previousFocus = document.activeElement;
    function close() { document.removeEventListener('keydown', keyboard); overlay.remove(); if (previousFocus && previousFocus.isConnected) previousFocus.focus(); }
    function keyboard(event) {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
      if (event.key === 'Tab') {
        const targets = [...dialog.querySelectorAll('input,button')].filter(n => !n.disabled), first = targets[0], last = targets[targets.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }
    form.addEventListener('submit', async event => {
      event.preventDefault(); submit.disabled = true;
      try {
        const result = await api({action: 'edit_transfer', account_id: account.id, key: entry.key, version: entry.version, amount: amount.value, description: description.value});
        for (const ledger of result.ledgers) { const target = config.accounts.find(a => a.id === ledger.id); if (target) applyLedger(target, ledger); }
        refreshTransferNames(); close();
      } catch (error) { status.textContent = error.message; }
      finally { submit.disabled = false; }
    });
    cancel.addEventListener('click', close); document.addEventListener('keydown', keyboard); document.body.append(overlay); description.focus();
  }
  function updateSummary() {
    const pending = [...states.values()].filter(s => s.dirty || s.saving).length;
    summary.textContent = pending ? pending + (pending === 1 ? ' fila pendiente' : ' filas pendientes') : 'Todo guardado';
    summary.style.color = pending ? '#92400e' : '#166534';
  }
  function rowData(s) {
    return {action: 'save_row', account_id: s.account.id, key: s.key, version: s.version,
      date: s.date.value, description: s.description.value, amount: s.amount.value};
  }
  function signature(data) { return JSON.stringify([data.date, data.description, data.amount]); }
  function remember(s) {
    drafts[s.key] = rowData(s); persist(); updateSummary();
  }
  function setStatus(s, text, error = false, retry = false) {
    s.message.textContent = text; s.status.classList.toggle('error', error);
    s.retry.hidden = !retry;
  }
  async function api(data) {
    const response = await fetch(config.url, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-Bank-CSRF': config.csrf}, body: JSON.stringify(data)});
    if (response.redirected || !(response.headers.get('Content-Type') || '').includes('application/json')) {
      throw new Error('La sesión venció. Ingresá nuevamente; el borrador se conserva.');
    }
    const result = await response.json();
    if (!response.ok || !result.ok) { const error = new Error(result.error || 'No se pudo guardar.'); error.status = response.status; error.entry = result.entry; throw error; }
    return result;
  }
  function applyLedger(account, data) {
    const p = panels.get(account.id); account.balance = data.balance; account.balance_raw = data.balance_raw;
    p.balance.textContent = moneyLabel + data.balance; p.tabBalance.textContent = moneyLabel + data.balance;
    p.opening.textContent = data.opening; p.monthClosing.textContent = moneyLabel + data.closing;
    account.entries = data.entries;
    for (const [key, row] of p.rows) if (row.classList.contains('bank-legacy')) { row.remove(); p.rows.delete(key); }
    for (const entry of data.entries) {
      if (!p.rows.has(entry.key)) { if (entry.editable) addRow(account, entry); else addLegacy(account, entry); }
      const state = states.get(entry.key);
      if (state && !state.dirty && !state.saving) {
        state.version = entry.version; state.date.value = entry.date; state.description.value = entry.description; state.amount.value = entry.amount; markColor(state.amount);
      }
      const row = p.rows.get(entry.key);
      if (row) row.querySelector('.bank-running').textContent = entry.balance;
    }
    if (document.activeElement !== p.balanceInput) p.balanceInput.value = data.balance;
    const focused = document.activeElement;
    let selection; try { selection = [focused.selectionStart, focused.selectionEnd]; } catch (_) {}
    for (const entry of [...data.entries].reverse()) {
      const row = p.rows.get(entry.key);
      // Mostrar primero el más reciente; cada fila conserva su saldo acumulado.
      if (row) p.body.append(row);
    }
    for (const [key, row] of p.rows) if (!data.entries.some(e => e.key === key)) {
      const state = states.get(key);
      if (!state || (state.version > 0 && !state.dirty && !state.saving)) { row.remove(); p.rows.delete(key); states.delete(key); }
      else p.draftBody.append(row);
    }
    if (focused && focused.isConnected && document.activeElement !== focused) {
      focused.focus({preventScroll: true});
      if (selection && selection[0] !== null) try { focused.setSelectionRange(...selection); } catch (_) {}
    }
  }
  function schedule(s) {
    clearTimeout(s.timer);
    if (s.conflict) return;
    s.timer = setTimeout(() => save(s), 800);
  }
  async function save(s) {
    if (!s.dirty || s.saving || s.conflict) return;
    if (!s.date.value || !s.description.value.trim() || parse(s.amount.value) === null) {
      setStatus(s, 'Completá fecha, descripción y monto. Borrador pendiente.'); return;
    }
    const data = rowData(s), sent = signature(data); s.saving = true; s.attempted = true;
    setStatus(s, 'Guardando…'); updateSummary();
    try {
      const result = await api(data);
      s.version = result.entry.version;
      s.row.classList.remove('bank-draft'); applyLedger(s.account, result.ledger);
      s.dirty = signature(rowData(s)) !== sent;
      if (s.dirty) { remember(s); setStatus(s, 'Cambios pendientes…'); }
      else {
        delete drafts[s.key]; persist(); setStatus(s, 'Guardado');
        if (result.entry.date.slice(0, 7) !== config.month) {
          const panel = panels.get(s.account.id), link = el('a', '', 'Ver movimiento en ' + result.entry.date.slice(0, 7));
          const target = new URL(config.url, window.location.href); target.searchParams.set('month', result.entry.date.slice(0, 7)); link.href = target.href;
          panel.notice.replaceChildren(el('span', '', 'Guardado en otro mes. '), link);
          states.delete(s.key); panel.rows.delete(s.key); s.row.remove();
        }
      }
      const p = panels.get(s.account.id);
      if (![...states.values()].some(other => other.account.id === s.account.id && other.version === 0 && !other.dirty)) addRow(s.account);
    } catch (error) {
      if (error.status === 409) {
        s.conflict = true; s.serverEntry = error.entry; s.resolve.hidden = !error.entry;
      }
      setStatus(s, error.message + (error.status === 409 ? '' : ' Borrador conservado.'), true, !s.conflict);
      if (!error.status) s.timer = setTimeout(() => save(s), 7000);
    } finally {
      s.saving = false; updateSummary();
      if (s.dirty && !s.conflict && signature(rowData(s)) !== sent) schedule(s);
    }
  }
  function transferDetail(account, entry) {
    if (entry.source !== 'Transferencia') return '';
    const receiving = Number(entry.destination_account_id) === account.id;
    const counterpart = config.accounts.find(a => a.id === Number(receiving ? entry.source_account_id : entry.destination_account_id));
    return (receiving ? 'Recibido de ' : 'Enviado a ') + (counterpart ? counterpart.name : 'Cuenta no disponible');
  }
  function refreshTransferNames() {
    for (const account of config.accounts) {
      const p = panels.get(account.id); if (!p) continue;
      const selected = p.destination.value;
      p.destination.replaceChildren();
      for (const other of config.accounts) if (other.id !== account.id) {
        const option = el('option', '', other.name); option.value = other.id; p.destination.append(option);
      }
      if ([...p.destination.options].some(option => option.value === selected)) p.destination.value = selected;
      for (const entry of account.entries) if (entry.source === 'Transferencia') {
        const row = p.rows.get(entry.key), detail = row && row.querySelector('.bank-transfer-detail');
        if (detail) detail.textContent = transferDetail(account, entry);
      }
    }
  }
  function addLegacy(account, entry) {
    const p = panels.get(account.id), row = el('tr', 'bank-legacy'); row.dataset.key = entry.key;
    const description = el('td');
    if (entry.source === 'Transferencia') {
      description.append(el('div', 'bank-transfer-detail', transferDetail(account, entry)), el('div', 'bank-transfer-note', entry.description));
    } else { description.append(document.createTextNode(entry.description), el('small', '', entry.source)); }
    const amount = el('td', 'amount ' + (parse(entry.amount) < 0 ? 'bank-negative' : 'bank-positive'), entry.amount);
    row.append(el('td', '', entry.date), description, amount, el('td', 'bank-running', entry.balance));
    const actions = el('div', 'bank-row-status');
    if (entry.can_edit) actions.append(rowActions(row, {edit: () => editLegacy(account, entry)}));
    else if (entry.detail_url) { const link = el('a', '', 'Ver detalle'); link.href = entry.detail_url; actions.append(link); }
    description.append(actions);
    p.body.append(row); p.rows.set(entry.key, row);
  }
  function addRow(account, entry) {
    const p = panels.get(account.id);
    const key = entry ? entry.key : crypto.randomUUID();
    const row = el('tr', entry ? '' : 'bank-draft'); row.dataset.key = key;
    const dateCell = el('td'), descriptionCell = el('td'), amountCell = el('td'), balanceCell = el('td', 'bank-running', entry ? entry.balance : '—');
    const date = el('input'), description = el('input'), amount = el('input', 'amount');
    date.type = 'date'; date.value = entry ? entry.date : config.today; date.setAttribute('aria-label', 'Fecha');
    description.type = 'text'; description.maxLength = 240; description.setAttribute('aria-label', 'Descripción');
    amount.type = 'text'; amount.inputMode = config.currency === 'USD' ? 'decimal' : 'text'; amount.setAttribute('aria-label', 'Monto');
    description.value = entry ? entry.description : ''; amount.value = entry ? entry.amount : '';
    const status = el('div', 'bank-row-status'), message = el('span', '', entry ? 'Guardado' : '');
    const retry = el('button', '', 'Reintentar'), resolve = el('button', '', 'Usar versión guardada');
    retry.type = resolve.type = 'button'; retry.hidden = resolve.hidden = true;
    status.append(message, retry, resolve); dateCell.append(date); descriptionCell.append(description, status); amountCell.append(amount);
    row.append(dateCell, descriptionCell, amountCell, balanceCell);
    if (entry && entry.version > 0) p.body.append(row); else p.draftBody.prepend(row);
    p.rows.set(key, row);
    const s = {key, account, row, date, description, amount, status, message, retry, resolve, version: entry ? entry.version : 0, dirty: false, saving: false};
    states.set(key, s); markColor(amount);
    for (const input of [date, description, amount]) input.addEventListener('input', () => {
      s.dirty = true; if (input === amount) formatAmount(amount); remember(s); setStatus(s, s.conflict ? 'Conflicto: revisá la versión guardada.' : 'Cambios pendientes…', !!s.conflict); schedule(s);
    });
    amount.addEventListener('blur', () => { const n = parse(amount.value); if (n !== null) { amount.value = fmt(n); markColor(amount); if (s.dirty) { remember(s); schedule(s); } } });
    retry.addEventListener('click', () => save(s));
    resolve.addEventListener('click', () => {
      const saved = s.serverEntry;
      if (!saved) return;
      if (saved.deleted) { states.delete(key); p.rows.delete(key); row.remove(); }
      else { date.value = saved.date; description.value = saved.description; amount.value = saved.amount; s.version = saved.version; markColor(amount); }
      s.conflict = false; s.dirty = false; resolve.hidden = true; delete drafts[key]; persist(); setStatus(s, 'Versión guardada recuperada'); updateSummary();
    });
    s.menu = rowActions(row, {edit: () => { description.focus(); description.select(); }});
    status.append(s.menu);
    return s;
  }
  for (const account of config.accounts) {
    const tab = el('button', 'bank-tab'); tab.type = 'button'; tab.setAttribute('role', 'tab'); tab.id = 'bank-tab-' + account.id;
    const tabName = el('span', '', account.name), tabBalance = el('strong', '', moneyLabel + account.balance); tab.append(tabName, tabBalance); tabs.append(tab);
    const panel = el('section', 'bank-sheet-panel'); panel.id = 'bank-panel-' + account.id; panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', tab.id); tab.setAttribute('aria-controls', panel.id);
    const top = el('div', 'bank-panel-top'), name = el('input', 'bank-name'), balanceBox = el('div', 'bank-current'), balance = el('span', '', moneyLabel + account.balance);
    name.value = account.name; name.maxLength = 100; name.setAttribute('aria-label', 'Nombre del banco'); balanceBox.append(el('small', '', 'Saldo actual'), balance); const closingBox = el('div', 'bank-current'), monthClosing = el('span', '', moneyLabel + account.closing);
    closingBox.append(el('small', '', 'Saldo del mes consultado'), monthClosing);
    top.append(name, balanceBox, closingBox); panel.append(top);
    const wrap = el('div', 'bank-table-wrap'), table = el('table', 'bank-table'), head = el('thead'), hr = el('tr');
    for (const title of ['Fecha', 'Descripción', 'Monto', 'Saldo']) hr.append(el('th', '', title)); head.append(hr); table.append(head);
    const draftBody = el('tbody', 'bank-draft-rows'), body = el('tbody'), openingBody = el('tbody', 'bank-opening-rows'), openingRow = el('tr', 'bank-opening'), opening = el('td', 'bank-running', account.opening);
    openingRow.append(el('td', '', '—'), el('td', '', 'Saldo al inicio del mes'), el('td', '', '—'), opening); openingBody.append(openingRow); table.append(draftBody, body, openingBody); wrap.append(table); panel.append(wrap);
    const bottom = el('div', 'bank-sheet-bottom'), add = el('button', 'bank-add', '+ Agregar fila'); add.type = 'button'; bottom.append(add); const notice = el('div', 'bank-month-notice'); bottom.append(notice); panel.insertBefore(bottom, wrap);
    const options = el('details', 'bank-options'); options.append(el('summary', '', 'Opciones de cuenta'));
    const content = el('div', 'bank-options-content'), adjustment = el('div'), balanceInput = el('input'), balanceStatus = el('span', 'bank-option-status');
    adjustment.append(el('h4', '', 'Corregir saldo actual')); balanceInput.value = account.balance; balanceInput.setAttribute('aria-label', 'Corregir saldo actual'); adjustment.append(balanceInput, balanceStatus); content.append(adjustment);
    // Mantener las transferencias existentes sin opciones separadas de ingreso/egreso.
    const transfer = el('form'); transfer.method = 'post'; transfer.action = config.url; transfer.append(el('h4', '', 'Transferencia entre bancos'));
    for (const [field, value] of [['action', 'transfer'], ['source_account_id', account.id], ['csrf', config.csrf], ['key', crypto.randomUUID()]]) { const input = el('input'); input.type = 'hidden'; input.name = field; input.value = value; transfer.append(input); }
    const destination = el('select'); destination.name = 'destination_account_id'; destination.setAttribute('aria-label', 'Banco de destino');
    for (const other of config.accounts) if (other.id !== account.id) { const option = el('option', '', other.name); option.value = other.id; destination.append(option); }
    const transferAmount = el('input'); transferAmount.name = 'amount'; transferAmount.type = 'text'; transferAmount.inputMode = 'numeric'; transferAmount.required = true; transferAmount.placeholder = 'Monto a transferir';
    transferAmount.addEventListener('input', () => { transferAmount.setCustomValidity(''); formatAmount(transferAmount); });
    transfer.addEventListener('submit', event => {
      const value = parse(transferAmount.value);
      if (value === null || value <= 0) { event.preventDefault(); transferAmount.setCustomValidity('Escribí un monto mayor que cero.'); transferAmount.reportValidity(); }
      else transferAmount.value = fmt(value);
    });
    const transferDescription = el('input'); transferDescription.name = 'description'; transferDescription.placeholder = 'Descripción';
    const transferButton = el('button', '', 'Transferir'); transferButton.type = 'submit'; transfer.append(destination, transferAmount, transferDescription, transferButton); content.append(transfer); options.append(content); panel.append(options); root.append(panel);
    panels.set(account.id, {panel, body, draftBody, rows: new Map(), tab, tabName, tabBalance, balance, monthClosing, notice, opening, balanceInput, destination});
    add.addEventListener('click', () => { const row = addRow(account); row.description.focus(); });
    tab.addEventListener('click', () => {
      for (const [id, p] of panels) { const active = id === account.id; p.panel.hidden = !active; p.tab.setAttribute('aria-selected', String(active)); }
      try { sessionStorage.setItem('freddy-bank-tab', String(account.id)); } catch (_) {}
    });
    let nameTimer, nameSaving = false;
    async function saveName() {
      if (nameSaving || !name.value.trim() || name.value.trim() === account.name) return;
      nameSaving = true;
      try {
        const result = await api({action: 'rename_account', account_id: account.id, name: name.value, expected_name: account.name});
        account.name = result.name; tabName.textContent = result.name; name.title = 'Guardado'; refreshTransferNames();
        if (name.value.trim() !== account.name) nameTimer = setTimeout(saveName, 800);
      } catch (error) { name.title = error.message; summary.textContent = error.message; }
      finally { nameSaving = false; }
    }
    name.addEventListener('input', () => { clearTimeout(nameTimer); nameTimer = setTimeout(saveName, 800); });
    let balanceTimer;
    balanceInput.addEventListener('input', () => {
      clearTimeout(balanceTimer); formatAmount(balanceInput); balanceStatus.textContent = 'Pendiente…';
      balanceTimer = setTimeout(async () => {
        if (parse(balanceInput.value) === null) { balanceStatus.textContent = 'Escribí un saldo entero válido.'; return; }
        try { const result = await api({action: 'set_balance', account_id: account.id, amount: balanceInput.value, expected_balance: account.balance_raw}); applyLedger(account, result.ledger); balanceStatus.textContent = 'Guardado'; }
        catch (error) { balanceStatus.textContent = error.message; }
      }, 1000);
    });
    for (const entry of [...account.entries].reverse()) {
      if (entry.editable) addRow(account, entry);
      else addLegacy(account, entry);
    }
    addRow(account);
  }
  refreshTransferNames();
  // Recuperar borradores sin pisar una modificación guardada desde otro dispositivo.
  for (const [key, draft] of Object.entries(drafts)) {
    const account = config.accounts.find(a => a.id === draft.account_id); if (!account || (draft.date || '').slice(0, 7) !== config.month) continue;
    let s = states.get(key);
    if (!s) s = addRow(account, {key, date: draft.date, description: '', amount: '', version: draft.version || 0, balance: '—'});
    const server = account.entries.find(e => e.key === key);
    s.date.value = draft.date; s.description.value = draft.description; s.amount.value = draft.amount; s.dirty = true;
    if (server && server.date === draft.date && server.description === draft.description.trim() && parse(server.amount) === parse(draft.amount)) {
      s.version = server.version; s.dirty = false; delete drafts[key]; persist(); setStatus(s, 'Guardado');
    } else if ((server && server.version !== draft.version) || (!server && draft.version)) {
      s.conflict = true; s.serverEntry = server || {deleted: true}; s.resolve.hidden = false; setStatus(s, 'Hay otra versión guardada. Revisala antes de continuar.', true);
    } else { s.version = draft.version || 0; setStatus(s, 'Borrador recuperado…'); schedule(s); }
    formatAmount(s.amount);
  }
  let selected; try { selected = sessionStorage.getItem('freddy-bank-tab'); } catch (_) {}
  (panels.get(Number(selected)) || panels.values().next().value).tab.click(); updateSummary();
  window.addEventListener('online', () => { for (const s of states.values()) if (s.dirty && !s.conflict) save(s); });
  window.addEventListener('beforeunload', event => { if ([...states.values()].some(s => s.dirty || s.saving)) { event.preventDefault(); event.returnValue = ''; } });
})();


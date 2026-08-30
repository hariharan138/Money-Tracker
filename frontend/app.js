'use strict';

import './styles.css';
import { apiFetch, hasApiConfiguration } from './api.js';

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(error => console.warn('Service worker registration failed', error));
  });
}

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const API_KEY_STORAGE = 'expenses-api-key';

/** Persist ?key= for Home Screen / PWA launches that open `/` without the query. */
function readStoredApiKey() {
  try {
    return (localStorage.getItem(API_KEY_STORAGE) || '').trim();
  } catch {
    return '';
  }
}

function writeStoredApiKey(key) {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE, key);
    else localStorage.removeItem(API_KEY_STORAGE);
  } catch {
    /* private mode / blocked storage */
  }
}

const params = new URLSearchParams(location.search);
const keyFromUrl = (params.get('key') || '').trim();
if (keyFromUrl) {
  writeStoredApiKey(keyFromUrl);
  // Keep ?key= working, then drop the secret from the address bar so the
  // Home Screen bookmark can safely use start_url `/`.
  params.delete('key');
  const clean = `${location.pathname}${params.toString() ? `?${params}` : ''}${location.hash}`;
  history.replaceState(null, '', clean || '/');
}
let KEY = keyFromUrl || readStoredApiKey();
const INR = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
const icons = {
  food: '🍜', groceries: '🛒', grocery: '🛒', travel: '✈️', cab: '🚕', fuel: '⛽',
  bills: '🧾', rent: '🏠', health: '💊', fitness: '🏋️', entertainment: '🎬',
  shopping: '🛍️', coffee: '☕', education: '📚', gifts: '🎁', expense: '◉',
};

let expenses = [];
const state = { preset: 'all', payment: 'all', q: '', sort: 'newest', chartRange: 'month' };

function dateOf(value) {
  return new Date(/(?:Z|[+-]\d\d:?\d\d)$/i.test(value || '') ? value : `${value}Z`);
}

function dayKey(value) {
  const d = dateOf(value);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function sum(items) {
  return items.reduce((total, item) => total + Number(item.amount || 0), 0);
}

function escapeHtml(value) {
  const node = document.createElement('div');
  node.textContent = value ?? '';
  return node.innerHTML;
}

function range() {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (state.preset === 'today') return today;
  if (state.preset === '7') return new Date(today - 6 * 864e5);
  if (state.preset === '30') return new Date(today - 29 * 864e5);
  if (state.preset === 'month') return new Date(now.getFullYear(), now.getMonth(), 1);
  return null;
}

function filtered() {
  const from = range();
  const query = state.q.trim().toLowerCase();
  const order = {
    newest: (a, b) => dateOf(b.date) - dateOf(a.date),
    oldest: (a, b) => dateOf(a.date) - dateOf(b.date),
    high: (a, b) => b.amount - a.amount,
    low: (a, b) => a.amount - b.amount,
  }[state.sort];

  return expenses.filter(item => {
    if (from && dateOf(item.date) < from) return false;
    if (state.payment !== 'all' && (item.payment_method || '').toLowerCase() !== state.payment) return false;
    return !query || [item.category, item.description, item.notes, item.payment_method].join(' ').toLowerCase().includes(query);
  }).sort(order);
}

function greetingForNow() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning!';
  if (hour < 17) return 'Good afternoon!';
  return 'Good evening!';
}

function formatDayLabel(key) {
  const today = dayKey(new Date());
  const yesterday = dayKey(new Date(Date.now() - 864e5));
  if (key === today) return 'Today';
  if (key === yesterday) return 'Yesterday';
  const [y, m, d] = key.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}

function groupByDate(items) {
  const groups = new Map();
  for (const item of items) {
    const key = dayKey(item.date);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.entries()];
}

function row(item, compact = false) {
  const icon = icons[(item.category || '').trim().toLowerCase()] || '🏷️';
  const time = dateOf(item.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return `<article class="tx${compact ? ' compact' : ''}">
    <div class="icon">${icon}</div>
    <div class="main">
      <div class="name">${escapeHtml(item.category || 'Expense')}</div>
      <div class="desc">${escapeHtml(item.description || item.notes || 'Expense')}</div>
      <div class="meta">${escapeHtml(time)}${item.payment_method ? ` · ${escapeHtml(item.payment_method)}` : ''}</div>
    </div>
    <div class="amount">-${INR.format(item.amount)}</div>
    ${compact ? '' : `<button class="delete" data-delete="${escapeHtml(item.id)}" aria-label="Delete expense">×</button>`}
  </article>`;
}

function chartBuckets() {
  const now = new Date();
  if (state.chartRange === 'week') {
    return [...Array(7)].map((_, index) => {
      const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (6 - index));
      const key = dayKey(day);
      return {
        label: day.toLocaleDateString(undefined, { weekday: 'narrow' }),
        total: sum(expenses.filter(item => dayKey(item.date) === key)),
      };
    });
  }

  if (state.chartRange === 'year') {
    return [...Array(12)].map((_, month) => {
      const total = sum(expenses.filter(item => {
        const d = dateOf(item.date);
        return d.getFullYear() === now.getFullYear() && d.getMonth() === month;
      }));
      return {
        label: new Date(now.getFullYear(), month, 1).toLocaleDateString(undefined, { month: 'narrow' }),
        total,
      };
    });
  }

  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const step = Math.max(1, Math.ceil(daysInMonth / 7));
  const buckets = [];
  for (let start = 1; start <= daysInMonth; start += step) {
    const end = Math.min(daysInMonth, start + step - 1);
    const total = sum(expenses.filter(item => {
      const d = dateOf(item.date);
      const day = d.getDate();
      return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && day >= start && day <= end;
    }));
    buckets.push({ label: String(start), total });
  }
  return buckets;
}

function renderChart() {
  const buckets = chartBuckets();
  const max = Math.max(...buckets.map(b => b.total), 1);
  const w = 320;
  const h = 180;
  const padX = 12;
  const padY = 24;
  const chartH = h - padY * 2;
  const chartW = w - padX * 2;
  const points = buckets.map((bucket, index) => {
    const x = padX + (buckets.length === 1 ? chartW / 2 : (index / (buckets.length - 1)) * chartW);
    const y = padY + chartH - (bucket.total / max) * chartH;
    return { ...bucket, x, y };
  });

  const line = points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const area = `${line} L${points.at(-1).x.toFixed(1)},${(h - padY).toFixed(1)} L${points[0].x.toFixed(1)},${(h - padY).toFixed(1)} Z`;
  const peak = points.reduce((best, p) => (p.total >= best.total ? p : best), points[0]);

  $('#trend').innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Spending chart">
      <defs>
        <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#151922" stop-opacity="0.18"/>
          <stop offset="100%" stop-color="#151922" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path d="${area}" fill="url(#chartFill)"/>
      <path d="${line}" fill="none" stroke="#151922" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="${peak.x}" y1="${padY}" x2="${peak.x}" y2="${h - padY}" stroke="#c9ccd1" stroke-width="1.2" stroke-dasharray="4 4"/>
      <circle cx="${peak.x}" cy="${peak.y}" r="5" fill="#151922"/>
      <circle cx="${peak.x}" cy="${peak.y}" r="2.5" fill="#fff"/>
      <rect x="${Math.min(Math.max(peak.x - 36, 4), w - 76)}" y="${Math.max(peak.y - 28, 4)}" width="72" height="22" rx="8" fill="#151922"/>
      <text class="chart-tooltip" x="${Math.min(Math.max(peak.x - 36, 4) + 36, w - 40)}" y="${Math.max(peak.y - 28, 4) + 15}" text-anchor="middle" fill="#fff">${INR.format(peak.total)}</text>
      ${points.map(p => `<text x="${p.x}" y="${h - 4}" text-anchor="middle" fill="#a0a3a9" font-size="9" font-weight="600">${escapeHtml(p.label)}</text>`).join('')}
    </svg>`;
}

function preferredPayment() {
  const counts = expenses.reduce((acc, item) => {
    const method = (item.payment_method || '').trim() || '—';
    acc[method] = (acc[method] || 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || '—';
}

function connectedUserName() {
  const named = expenses.find(item => (item.user || '').trim())?.user?.trim();
  return named || '';
}

function maskKey(key) {
  if (!key) return '';
  if (key.length <= 8) return '••••••••';
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

function syncProfileKeyUi(message = '', kind = '') {
  const input = $('#apiKeyInput');
  const status = $('#apiKeyStatus');
  if (input && document.activeElement !== input) {
    input.value = KEY;
    input.placeholder = KEY ? 'API key saved on this device' : 'Paste your API key';
  }
  status.textContent = message || (KEY ? `Using ${maskKey(KEY)}` : 'No API key saved yet');
  status.className = `profile-key-status${kind ? ` ${kind}` : ''}`;
}

function updateProfileIdentity() {
  const name = connectedUserName();
  const avatar = $('#profileAvatar');
  const title = $('#profileName');
  const subtitle = $('#profileSubtitle');
  if (!KEY) {
    avatar.textContent = '?';
    title.textContent = 'Not connected';
    subtitle.textContent = 'Paste your API key below to load expenses';
    return;
  }
  if (name) {
    avatar.textContent = name.slice(0, 1).toUpperCase();
    title.textContent = name;
    subtitle.textContent = 'Personal expense tracker';
  } else {
    avatar.textContent = '✓';
    title.textContent = 'Connected';
    subtitle.textContent = 'API key saved on this device';
  }
}

function chartWindowTotal() {
  const now = new Date();
  if (state.chartRange === 'week') {
    const from = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6);
    return sum(expenses.filter(item => dateOf(item.date) >= from));
  }
  if (state.chartRange === 'year') {
    return sum(expenses.filter(item => dateOf(item.date).getFullYear() === now.getFullYear()));
  }
  return sum(expenses.filter(item => {
    const d = dateOf(item.date);
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
  }));
}

function render() {
  const items = filtered();
  const total = sum(items);
  const today = sum(items.filter(item => dayKey(item.date) === dayKey(new Date())));
  const allTotal = sum(expenses);

  $('#greeting').textContent = greetingForNow();
  $('#total').textContent = INR.format(allTotal);
  $('#total-sub').textContent = `${expenses.length} transaction${expenses.length === 1 ? '' : 's'}`;
  $('#stats').innerHTML = `
    <div class="stat"><span class="stat-icon">↗</span><div><small>Today</small><strong>${INR.format(today)}</strong></div></div>
    <div class="stat"><span class="stat-icon">↘</span><div><small>Selected</small><strong>${INR.format(total)}</strong></div></div>`;

  $('#recentPreview').innerHTML = items.length
    ? items.slice(0, 3).map(item => row(item, true)).join('')
    : '<div class="empty">No expenses yet. Tap + to add one.</div>';

  const groups = groupByDate(items);
  $('#list').innerHTML = groups.length
    ? groups.map(([key, groupItems]) => `
        <div class="date-group">
          <div class="date-label">${escapeHtml(formatDayLabel(key))} · ${INR.format(sum(groupItems))}</div>
          ${groupItems.map(item => row(item)).join('')}
        </div>`).join('')
    : '<div class="empty">No expenses match these filters.</div>';

  $('#analyticsTotal').textContent = INR.format(chartWindowTotal());
  $('#analyticsDate').textContent = new Date().toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
  $('#analyticsStats').innerHTML = expenses
    .slice()
    .sort((a, b) => b.amount - a.amount)
    .slice(0, 4)
    .map(item => `
      <div class="top-item">
        <span>${icons[(item.category || '').trim().toLowerCase()] || '🏷️'}</span>
        <div>
          <strong>${escapeHtml(item.category || 'Expense')}</strong>
          <small>${escapeHtml(item.description || 'Expense')}</small>
        </div>
        <b>-${INR.format(item.amount)}</b>
      </div>`).join('') || '<div class="empty">No spending data yet.</div>';

  $('#profileTotal').textContent = INR.format(allTotal);
  $('#profileCount').textContent = String(expenses.length);
  $('#profilePayment').textContent = preferredPayment();
  $('#addDateLabel').textContent = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
  updateProfileIdentity();
  syncProfileKeyUi();

  renderChart();
  updateAddPreview();
}

function showTab(name) {
  $$('[data-panel]').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === name));
  $$('[data-tab]').forEach(button => button.classList.toggle('nav-active', button.dataset.tab === name));
  document.body.classList.toggle('on-add', name === 'add');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (name === 'add') {
    $('#formError').textContent = '';
    setTimeout(() => $('#expenseAmount')?.focus(), 120);
  }
}

function updateAddPreview() {
  const amount = Number($('#expenseAmount')?.value || 0);
  $('#addAmountPreview').textContent = INR.format(amount || 0);
  $('#addPaymentPreview').textContent = $('#expensePayment')?.value || 'UPI';
}

async function load() {
  if (!hasApiConfiguration()) {
    $('#status').textContent = 'Set PRIMARY_API_URL and SECONDARY_API_URL in frontend/.env.local';
    syncProfileKeyUi('Backend URLs are not configured', 'err');
    return false;
  }
  if (!KEY) {
    $('#status').textContent = 'Open Profile and paste your API key';
    expenses = [];
    render();
    syncProfileKeyUi('Paste your API key, then tap Save & load data');
    return false;
  }
  $('#status').textContent = 'Loading expenses…';
  try {
    const response = await apiFetch(`/api/expenses?key=${encodeURIComponent(KEY)}&limit=1000`, { cache: 'no-store' });
    if (response.status === 401) throw new Error('Invalid API key');
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    expenses = (await response.json()).expenses || [];
    render();
    $('#status').textContent = 'Updated just now';
    syncProfileKeyUi(`Connected · ${maskKey(KEY)}`, 'ok');
    return true;
  } catch (error) {
    console.error(error);
    const message = error.message === 'Failed to fetch'
      ? 'Could not reach API — check its URL and CORS_ORIGINS'
      : error.message;
    $('#status').textContent = message;
    syncProfileKeyUi(message, 'err');
    return false;
  }
}

async function saveApiKey() {
  const next = ($('#apiKeyInput').value || '').trim();
  const status = $('#apiKeyStatus');
  if (!next) {
    status.textContent = 'Paste an API key first';
    status.className = 'profile-key-status err';
    return;
  }
  KEY = next;
  writeStoredApiKey(KEY);
  status.textContent = 'Saved. Loading…';
  status.className = 'profile-key-status';
  if (await load()) showTab('dashboard');
}

function clearApiKey() {
  KEY = '';
  expenses = [];
  writeStoredApiKey('');
  $('#apiKeyInput').value = '';
  render();
  $('#status').textContent = 'Open Profile and paste your API key';
  syncProfileKeyUi('API key cleared from this device');
}

async function remove(id) {
  if (!confirm('Delete this expense?')) return;
  const response = await apiFetch(`/api/expenses/${encodeURIComponent(id)}?key=${encodeURIComponent(KEY)}`, { method: 'DELETE' });
  if (response.ok) {
    expenses = expenses.filter(item => item.id !== id);
    render();
  } else {
    alert('Could not delete this expense.');
  }
}

async function saveExpense(event) {
  event.preventDefault();
  const amount = Number($('#expenseAmount').value);
  const description = $('#expenseDescription').value.trim();
  const category = ($('#expenseCategory').value.trim() || 'Expense');
  const paymentMethod = $('#expensePayment').value;
  const error = $('#formError');

  if (!amount || !description) {
    error.textContent = 'Enter an amount and description.';
    return;
  }

  const saveButton = $('#saveExpense');
  saveButton.disabled = true;
  saveButton.textContent = 'Saving…';
  error.textContent = '';

  try {
    const response = await apiFetch(`/api/expenses?key=${encodeURIComponent(KEY)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount, category, description, payment_method: paymentMethod }),
    });
    if (!response.ok) throw new Error('Could not save this expense.');
    $('#expenseForm').reset();
    $('#expenseCategory').value = 'Expense';
    updateAddPreview();
    await load();
    showTab('transactions');
  } catch (err) {
    error.textContent = err.message || 'Could not save this expense.';
  } finally {
    saveButton.disabled = false;
    saveButton.textContent = 'Save expense';
  }
}

$('#refresh').onclick = load;
$('#profileRefresh').onclick = load;
$('#saveApiKey').onclick = saveApiKey;
$('#clearApiKey').onclick = clearApiKey;
$('#apiKeyInput').addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    saveApiKey();
  }
});
$('#expenseForm').onsubmit = saveExpense;
$('#expenseAmount').oninput = updateAddPreview;
$('#expensePayment').onchange = updateAddPreview;

$$('[data-tab]').forEach(button => {
  button.onclick = () => showTab(button.dataset.tab);
});

$$('[data-go]').forEach(button => {
  button.onclick = () => showTab(button.dataset.go);
});

$('#analyticsRange').onclick = event => {
  const button = event.target.closest('[data-range]');
  if (!button) return;
  state.chartRange = button.dataset.range;
  $$('#analyticsRange [data-range]').forEach(item => item.classList.toggle('range-active', item === button));
  render();
};

$('#preset').onchange = event => { state.preset = event.target.value; render(); };
$('#search').oninput = event => { state.q = event.target.value; render(); };
$('#sort').onchange = event => { state.sort = event.target.value; render(); };

$('#payments').onclick = event => {
  const button = event.target.closest('[data-payment]');
  if (!button) return;
  state.payment = button.dataset.payment;
  $$('[data-payment]').forEach(item => item.classList.toggle('active', item === button));
  render();
};

$('#clear').onclick = () => {
  state.preset = 'all';
  state.payment = 'all';
  state.q = '';
  state.sort = 'newest';
  $('#preset').value = 'all';
  $('#search').value = '';
  $('#sort').value = 'newest';
  $$('[data-payment]').forEach(item => item.classList.toggle('active', item.dataset.payment === 'all'));
  render();
};

$('#list').onclick = event => {
  const button = event.target.closest('[data-delete]');
  if (button) remove(button.dataset.delete);
};

render();
syncProfileKeyUi();
if (!KEY) showTab('profile');
load();

'use strict';

import './styles.css';
import { apiFetch, hasApiConfiguration } from './api.js';

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(error => console.warn('Service worker registration failed', error));
  });
}

// Block pinch-zoom / double-tap zoom so the PWA feels like a native app.
document.addEventListener('gesturestart', event => event.preventDefault());
document.addEventListener('dblclick', event => event.preventDefault(), { passive: false });

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
let monthlyLimit = null;
let avatarData = null;
let account = null;   // { username, api_key } once signed in with a password
const state = { preset: 'all', payment: 'all', q: '', sort: 'newest', chartRange: 'month' };

function dateOf(value) {
  if (value instanceof Date) return value;
  if (value == null || value === '') return new Date(NaN);
  const text = String(value);
  // API dates are UTC; strings without a timezone were being treated as UTC via a trailing Z.
  return new Date(/(?:Z|[+-]\d\d:?\d\d)$/i.test(text) ? text : `${text}Z`);
}

/** Local calendar day key (YYYY-MM-DD) for grouping / "today" totals. */
function dayKey(value) {
  const d = value instanceof Date ? value : dateOf(value);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function todayKey() {
  return dayKey(new Date());
}

function sum(items) {
  return items.reduce((total, item) => total + Number(item.amount || 0), 0);
}

function escapeHtml(value) {
  const node = document.createElement('div');
  node.textContent = value ?? '';
  // quotes too: this also fills attributes (data-delete="…")
  return node.innerHTML.replaceAll('"', '&quot;').replaceAll("'", '&#39;');
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
  const today = todayKey();
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

/** Short rupee label that fits the chart badges. */
function compactINR(value) {
  const amount = Number(value) || 0;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(amount % 100000 === 0 ? 0 : 1)}L`;
  if (amount >= 1000) return `₹${(amount / 1000).toFixed(amount % 1000 === 0 ? 0 : 1)}k`;
  return `₹${Math.round(amount)}`;
}

function renderChart() {
  const buckets = chartBuckets();
  if (!buckets.length) {
    $('#trend').innerHTML = '<div class="empty">No spending data yet.</div>';
    return;
  }

  const max = Math.max(...buckets.map(b => b.total), 1);
  const w = 320;
  const h = 200;
  const padX = 18;
  const padTop = 36;
  const padBottom = 28;
  const chartH = h - padTop - padBottom;
  const chartW = w - padX * 2;
  const points = buckets.map((bucket, index) => {
    const x = padX + (buckets.length === 1 ? chartW / 2 : (index / (buckets.length - 1)) * chartW);
    const y = padTop + chartH - (bucket.total / max) * chartH;
    return { ...bucket, x, y };
  });

  const line = points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const area = `${line} L${points.at(-1).x.toFixed(1)},${(h - padBottom).toFixed(1)} L${points[0].x.toFixed(1)},${(h - padBottom).toFixed(1)} Z`;
  const peak = points.reduce((best, p) => (p.total >= best.total ? p : best), points[0]);
  const peakLabel = compactINR(peak.total);
  const peakWidth = Math.max(52, peakLabel.length * 7.2 + 16);
  const peakX = Math.min(Math.max(peak.x - peakWidth / 2, 4), w - peakWidth - 4);
  const peakY = Math.max(peak.y - 30, 4);

  const valueLabels = points
    .filter(p => p.total > 0 && p !== peak)
    .map(p => {
      const label = compactINR(p.total);
      return `<text class="chart-value" x="${p.x.toFixed(1)}" y="${Math.max(p.y - 10, 12).toFixed(1)}" text-anchor="middle">${label}</text>`;
    })
    .join('');

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
      <line x1="${peak.x}" y1="${padTop}" x2="${peak.x}" y2="${h - padBottom}" stroke="#c9ccd1" stroke-width="1.2" stroke-dasharray="4 4"/>
      <circle cx="${peak.x}" cy="${peak.y}" r="5" fill="#151922"/>
      <circle cx="${peak.x}" cy="${peak.y}" r="2.5" fill="#fff"/>
      ${valueLabels}
      <rect x="${peakX}" y="${peakY}" width="${peakWidth}" height="22" rx="8" fill="#151922"/>
      <text class="chart-tooltip" x="${peakX + peakWidth / 2}" y="${peakY + 15}" text-anchor="middle">${peakLabel}</text>
      ${points.map(p => `<text x="${p.x}" y="${h - 6}" text-anchor="middle" fill="#a0a3a9" font-size="9" font-weight="600">${escapeHtml(p.label)}</text>`).join('')}
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
  if (account?.username) return account.username;
  const named = expenses.find(item => (item.user || '').trim())?.user?.trim();
  return named || '';
}

function daysInCurrentMonth() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
}

function spendInSpan(from, to) {
  return sum(expenses.filter(item => {
    const d = dateOf(item.date);
    return !Number.isNaN(d.getTime()) && d >= from && d <= to;
  }));
}

/** Spend so far this calendar month (local). */
function monthSpend() {
  const now = new Date();
  return spendInSpan(new Date(now.getFullYear(), now.getMonth(), 1), new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59, 59));
}

/** Spend so far today (local). */
function todaySpend() {
  const now = new Date();
  return spendInSpan(new Date(now.getFullYear(), now.getMonth(), now.getDate()), now);
}

/** Spend so far this calendar week starting Monday. */
function weekSpend() {
  const now = new Date();
  const day = (now.getDay() + 6) % 7;
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - day);
  return spendInSpan(start, now);
}

function weekStartKey() {
  const now = new Date();
  const day = (now.getDay() + 6) % 7;
  return dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - day));
}

function budgetAlert(monthSpent) {
  if (monthlyLimit == null || monthlyLimit <= 0) return null;
  const ratio = monthSpent / monthlyLimit;
  if (ratio >= 1) {
    return { kind: 'danger', text: `Monthly limit hit — you've spent ${INR.format(monthSpent)} of ${INR.format(monthlyLimit)}.` };
  }
  if (ratio >= 0.8) {
    return { kind: 'warn', text: `Careful — you've used ${Math.round(ratio * 100)}% of your monthly limit.` };
  }
  return null;
}

function budgetBar(label, spent, target, color) {
  const pct = target > 0 ? Math.min(100, (spent / target) * 100) : 0;
  const over = target > 0 && spent > target;
  return `
    <div class="budget-bar">
      <div class="budget-bar-top">
        <span>${label}</span>
        <span class="budget-bar-val ${over ? 'over' : ''}">${INR.format(spent)} <small>/ ${INR.format(target)}</small></span>
      </div>
      <div class="budget-track ${over ? 'over' : ''}"><i style="width:${pct}%;${color ? `background:${color}` : ''}"></i></div>
      <div class="budget-bar-rem">${target > 0 ? (spent > target ? `${INR.format(spent - target)} over` : `${INR.format(target - spent)} left`) : ''}</div>
    </div>`;
}

function renderBudget() {
  const section = $('#budgetSection');
  if (!section) return;
  if (monthlyLimit == null) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  const now = new Date();
  const days = daysInCurrentMonth();
  const dayOfMonth = now.getDate();
  const dayTarget = monthlyLimit / days;
  const weekStart = weekStartKey();
  const weekDayCount = Math.max(1, Math.min(7, Math.floor((now - new Date(weekStart + 'T00:00:00')) / 864e5) + 1));
  const weekTarget = (monthlyLimit / 4.33) * (weekDayCount / 7);

  const spent = { month: monthSpend(), today: todaySpend(), week: weekSpend() };

  const alert = budgetAlert(spent.month);
  const alertEl = $('#budgetAlert');
  if (alert) {
    alertEl.hidden = false;
    alertEl.textContent = alert.text;
    alertEl.className = `budget-alert ${alert.kind}`;
  } else {
    alertEl.hidden = true;
    alertEl.className = 'budget-alert';
  }

  $('#budgetBars').innerHTML =
    budgetBar('This month', spent.month, monthlyLimit, 'var(--orange)') +
    budgetBar('This week', spent.week, weekTarget) +
    budgetBar('Today', spent.today, dayTarget, 'var(--green)');

  $('#budgetSummary').textContent = `${INR.format(monthlyLimit)} limit · ${INR.format(Math.max(0, monthlyLimit - spent.month))} remaining this month`;
}

function openLimitModal() {
  const modal = $('#limitModal');
  const input = $('#limitInput');
  input.value = monthlyLimit == null ? '' : String(monthlyLimit);
  updateLimitPreview();
  modal.hidden = false;
  setTimeout(() => input.focus(), 120);
}

function closeLimitModal() {
  $('#limitModal').hidden = true;
}

function updateLimitPreview() {
  const value = Number($('#limitInput')?.value || 0);
  const el = $('#limitPreview');
  if (!el) return;
  if (!value || value <= 0) {
    el.innerHTML = '<span class="limit-period-muted">Enter an amount to see daily &amp; weekly targets.</span>';
    return;
  }
  const days = daysInCurrentMonth();
  el.innerHTML = `
    <div class="limit-period"><span>Monthly</span><strong>${INR.format(value)}</strong></div>
    <div class="limit-period"><span>Weekly (avg)</span><strong>${INR.format(value / 4.33)}</strong></div>
    <div class="limit-period"><span>Daily (avg)</span><strong>${INR.format(value / days)}</strong></div>`;
}

async function saveLimit() {
  const value = Number($('#limitInput')?.value || 0);
  if (!value || value <= 0) {
    $('#limitInput').focus();
    return;
  }
  if (!KEY) {
    showTab('profile');
    return;
  }
  try {
    const response = await apiFetch('/api/limits', authed({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ monthly_limit: value }),
    }));
    if (!response.ok) throw new Error('Could not save limit');
    monthlyLimit = value;
    closeLimitModal();
    render();
    $('#status').textContent = 'Monthly limit saved';
  } catch (error) {
    console.error(error);
    alert('Could not save your limit. Try again.');
  }
}

async function removeLimitLocal() {
  if (monthlyLimit == null) return;
  if (!KEY) return;
  try {
    const response = await apiFetch('/api/limits', authed({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ monthly_limit: null }),
    }));
    if (!response.ok) throw new Error('Could not remove limit');
    monthlyLimit = null;
    closeLimitModal();
    render();
    $('#status').textContent = 'Monthly limit removed';
  } catch (error) {
    console.error(error);
    alert('Could not remove your limit. Try again.');
  }
}

async function loadLimit() {
  if (!KEY) return;
  try {
    const response = await apiFetch('/api/limits', authed({ cache: 'no-store' }));
    if (!response.ok) return;
    const data = (await response.json()).limit;
    monthlyLimit = data?.monthly_limit ?? null;
    render();
  } catch (error) {
    console.error(error);
  }
}

async function loadProfile() {
  if (!KEY) return;
  try {
    const response = await apiFetch('/api/profile', authed({ cache: 'no-store' }));
    if (!response.ok) return;
    avatarData = (await response.json()).profile?.avatar || null;
    render();
  } catch (error) {
    console.error(error);
  }
}

/** Downscale a picked photo to a ~256px JPEG data URL so it stores cheaply. */
function fileToAvatar(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Could not read image'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('That file is not a valid image'));
      img.onload = () => {
        const MAX = 256;
        const scale = Math.min(1, MAX / Math.max(img.width, img.height));
        const w = Math.max(1, Math.round(img.width * scale));
        const h = Math.max(1, Math.round(img.height * scale));
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        canvas.getContext('2d').drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL('image/jpeg', 0.85));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

async function saveAvatar(file) {
  if (!KEY) {
    showTab('profile');
    syncProfileKeyUi('Save your API key first', 'err');
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    alert('Photo is too large. Pick one under 8 MB.');
    return;
  }
  try {
    const avatar = await fileToAvatar(file);
    const response = await apiFetch('/api/profile', authed({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ avatar }),
    }));
    if (!response.ok) throw new Error('Could not save photo');
    avatarData = avatar;
    render();
    $('#status').textContent = 'Profile photo saved';
  } catch (error) {
    console.error(error);
    alert('Could not save your photo. Try again.');
  }
}

async function removeAvatarPhoto() {
  if (!KEY || !avatarData) return;
  try {
    const response = await apiFetch('/api/profile', authed({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ avatar: null }),
    }));
    if (!response.ok) throw new Error('Could not remove photo');
    avatarData = null;
    render();
    $('#status').textContent = 'Profile photo removed';
  } catch (error) {
    console.error(error);
    alert('Could not remove your photo. Try again.');
  }
}

/** Key goes in a header, never the query string: ?key= lands in server logs
 *  on every poll, forever. The backend accepts both. */
function authed(init = {}) {
  return { ...init, headers: { ...(init.headers || {}), 'X-API-Key': KEY } };
}

function setAuthStatus(message = '', kind = '') {
  const el = $('#authStatus');
  el.textContent = message;
  el.className = `profile-key-status${kind ? ` ${kind}` : ''}`;
}

function syncAuthUi() {
  const signedIn = Boolean(account);
  $('#authForm').hidden = signedIn;
  $('#authAccount').hidden = !signedIn;
  // the paste-a-key box is only for people running on an EXPENSE_USERS key
  $('#apiKeyBox').hidden = signedIn;
  if (signedIn) {
    $('#authWho').textContent = account.username;
    $('#accountKey').value = account.api_key || '';
  }
}

/** Are we on a password account, or just holding an API key? */
async function loadMe() {
  if (!KEY) {
    account = null;
    syncAuthUi();
    return;
  }
  try {
    const response = await apiFetch('/api/auth/me', authed({ cache: 'no-store' }));
    const data = response.ok ? await response.json() : {};
    account = data.account ? { username: data.username, api_key: data.api_key } : null;
  } catch (error) {
    console.error(error);
    account = null;
  }
  render();
}

function authError(status, mode) {
  if (status === 409) return 'That username is taken. Pick another.';
  if (status === 401) return 'Wrong username or password.';
  if (status === 400) {
    return mode === 'register'
      ? 'Username: 3–32 letters, numbers, dot, dash or underscore. Password: 8 characters or more.'
      : 'Check your username and password.';
  }
  return `Could not sign you in (${status}).`;
}

async function doAuth(mode) {
  const username = $('#authUsername').value.trim();
  const password = $('#authPassword').value;
  if (!username || !password) {
    setAuthStatus('Enter a username and password', 'err');
    return;
  }
  setAuthStatus(mode === 'register' ? 'Creating your account…' : 'Logging in…');
  try {
    // POST goes straight to the primary (no failover), so a sleeping Render
    // instance means this waits for the cold start rather than double-posting.
    const response = await apiFetch(`/api/auth/${mode}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) {
      setAuthStatus(authError(response.status, mode), 'err');
      return;
    }
    const data = await response.json();
    KEY = data.token;
    writeStoredApiKey(KEY);
    account = { username: data.username, api_key: data.api_key };
    $('#authPassword').value = '';
    setAuthStatus(`Signed in as ${data.username}`, 'ok');
    if (await load()) showTab('dashboard');
  } catch (error) {
    console.error(error);
    setAuthStatus('Could not reach the server. Try again.', 'err');
  }
}

async function logout() {
  if (KEY) {
    try {
      await apiFetch('/api/auth/logout', authed({ method: 'POST' }));
    } catch (error) {
      console.warn(error);  // the token is going away locally either way
    }
  }
  account = null;
  clearApiKey();
  setAuthStatus('Logged out');
}

async function copyShortcutKey() {
  const key = account?.api_key;
  if (!key) return;
  try {
    await navigator.clipboard.writeText(key);
    setAuthStatus('Shortcut key copied', 'ok');
  } catch {
    // clipboard blocked (http, or no user-gesture): show it instead
    const field = $('#accountKey');
    field.type = 'text';
    field.select();
    setAuthStatus('Copy was blocked — the key is shown above, copy it by hand', 'err');
  }
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

function applyAvatar(el, name, fallback) {
  if (!el) return;
  if (avatarData) {
    el.style.backgroundImage = `url("${avatarData}")`;
    el.style.backgroundSize = 'cover';
    el.style.backgroundPosition = 'center';
    el.textContent = '';
    el.classList.add('has-photo');
  } else {
    el.style.backgroundImage = '';
    el.style.backgroundSize = '';
    el.style.backgroundPosition = '';
    el.textContent = fallback;
    el.classList.remove('has-photo');
  }
}

function updateProfileIdentity() {
  const name = connectedUserName();
  const avatar = $('#profileAvatar');
  const title = $('#profileName');
  const subtitle = $('#profileSubtitle');
  const dashboardName = $('#dashboardName');
  const dashAvatar = $('#dashAvatar');
  const editAvatarLink = $('#editAvatarLink');
  const removeAvatar = $('#removeAvatar');
  const avatarSep = $('.avatar-row-sep');
  const hasPhoto = Boolean(KEY && avatarData);
  if (!KEY) {
    avatar.textContent = '?';
    title.textContent = 'Not connected';
    subtitle.textContent = 'Log in or create an account to load your expenses';
    if (dashboardName) dashboardName.textContent = '';
    applyAvatar(avatar, '', '?');
    applyAvatar(dashAvatar, '', '');
  } else if (name) {
    avatar.textContent = name.slice(0, 1).toUpperCase();
    title.textContent = name;
    subtitle.textContent = 'Personal expense tracker';
    if (dashboardName) dashboardName.textContent = name;
    applyAvatar(avatar, name, name.slice(0, 1).toUpperCase());
    applyAvatar(dashAvatar, name, name.slice(0, 1).toUpperCase());
  } else {
    avatar.textContent = '✓';
    title.textContent = 'Connected';
    subtitle.textContent = 'API key saved on this device';
    if (dashboardName) dashboardName.textContent = 'Expenses';
    applyAvatar(avatar, '', '✓');
    applyAvatar(dashAvatar, '', '✓');
  }
  if (editAvatarLink) editAvatarLink.hidden = !KEY;
  if (removeAvatar) removeAvatar.hidden = !hasPhoto;
  if (avatarSep) avatarSep.hidden = !hasPhoto;
}

/** Is this expense inside the range the Analytics tab is showing? */
function inChartWindow(item) {
  const now = new Date();
  const d = dateOf(item.date);
  if (state.chartRange === 'week') return d >= new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6);
  if (state.chartRange === 'year') return d.getFullYear() === now.getFullYear();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
}

function chartWindowTotal() {
  return sum(expenses.filter(inChartWindow));
}

function render() {
  const items = filtered();
  const total = sum(items);
  // Overview "Today" is always calendar-today spend (all expenses), not filter-dependent.
  const today = sum(expenses.filter(item => dayKey(item.date) === todayKey()));
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
    .filter(inChartWindow)
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
  syncAuthUi();

  renderChart();
  updateAddPreview();
  renderBudget();
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

async function load({ quiet = false } = {}) {
  const reloadBtn = $('#reloadBtn');
  if (!hasApiConfiguration()) {
    $('#status').textContent = 'Set PRIMARY_API_URL and SECONDARY_API_URL in frontend/.env.local';
    syncProfileKeyUi('Backend URLs are not configured', 'err');
    return false;
  }
  if (!KEY) {
    $('#status').textContent = 'Open Profile to log in';
    expenses = [];
    render();
    syncProfileKeyUi('Paste your API key, then tap Save & load data');
    syncAuthUi();
    return false;
  }
  if (!quiet) {
    $('#status').textContent = 'Loading expenses…';
    reloadBtn?.classList.add('is-loading');
  }
  try {
    const response = await apiFetch('/api/expenses?limit=1000', authed({ cache: 'no-store' }));
    if (response.status === 401) throw new Error('Invalid API key');
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    expenses = (await response.json()).expenses || [];
    render();
    $('#status').textContent = 'Updated just now';
    syncProfileKeyUi(`Connected · ${maskKey(KEY)}`, 'ok');
    loadMe();
    loadLimit();
    loadProfile();
    return true;
  } catch (error) {
    console.error(error);
    const message = error.message === 'Failed to fetch'
      ? 'Could not reach API — check its URL and CORS_ORIGINS'
      : error.message;
    if (!quiet) $('#status').textContent = message;
    syncProfileKeyUi(message, 'err');
    return false;
  } finally {
    reloadBtn?.classList.remove('is-loading');
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
  monthlyLimit = null;
  avatarData = null;
  writeStoredApiKey('');
  $('#apiKeyInput').value = '';
  render();
  $('#status').textContent = 'Open Profile and paste your API key';
  syncProfileKeyUi('API key cleared from this device');
}

async function remove(id) {
  if (!confirm('Delete this expense?')) return;
  const response = await apiFetch(`/api/expenses/${encodeURIComponent(id)}`, authed({ method: 'DELETE' }));
  // 404 means it is already gone (e.g. the primary deleted it, then the
  // retried request hit the secondary) — same outcome as a clean delete.
  if (response.ok || response.status === 404) {
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
  if (!KEY) {
    error.textContent = 'Save your API key in Profile first.';
    showTab('profile');
    return;
  }

  const saveButton = $('#saveExpense');
  const tempId = `local-${Date.now()}`;
  const nowIso = new Date().toISOString();
  const optimistic = {
    id: tempId,
    amount,
    category,
    description,
    payment_method: paymentMethod,
    notes: null,
    date: nowIso,
    created_at: nowIso,
    user: connectedUserName() || undefined,
  };

  // Show it in the UI immediately, then upload in the background.
  expenses = [optimistic, ...expenses];
  $('#expenseForm').reset();
  $('#expenseCategory').value = 'Expense';
  updateAddPreview();
  error.textContent = '';
  render();
  showTab('transactions');
  $('#status').textContent = 'Saving…';
  saveButton.disabled = true;
  saveButton.textContent = 'Saving…';

  try {
    const response = await apiFetch('/api/expenses', authed({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount, category, description, payment_method: paymentMethod }),
    }));
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail.includes('ReadableStream') ? 'Could not save this expense. Try again.' : 'Could not save this expense.');
    }
    const created = await response.json().catch(() => ({}));
    if (created.expense_id) {
      expenses = expenses.map(item => (item.id === tempId ? { ...item, id: created.expense_id } : item));
      render();
    }
    $('#status').textContent = 'Expense saved';
    load({ quiet: true }).catch(() => {});
  } catch (err) {
    expenses = expenses.filter(item => item.id !== tempId);
    render();
    showTab('add');
    error.textContent = err.message || 'Could not save this expense.';
    $('#status').textContent = 'Save failed — try again';
  } finally {
    saveButton.disabled = false;
    saveButton.textContent = 'Save expense';
  }
}

$('#reloadBtn').onclick = () => load();
$('#profileRefresh').onclick = () => load();
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
  button.onclick = () => {
    if (suppressTabClick) return;
    showTab(button.dataset.tab);
  };
});

/* —— Liquid-glass navbar: springy horizontal swipe / drag —— */
const NAV_TABS = ['dashboard', 'transactions', 'add', 'analytics', 'profile'];
const nav = $('.bottom-nav');
const SWIPE_THRESHOLD = 60;
let dragState = null;
let suppressTabClick = false;

function activeTabName() {
  const active = $$('[data-tab]').find(button => button.classList.contains('nav-active'));
  return active ? active.dataset.tab : 'dashboard';
}

nav.addEventListener('pointerdown', event => {
  if (event.button != null && event.button !== 0) return;
  dragState = {
    id: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    dx: 0,
    dragging: false,
  };
  try { nav.setPointerCapture(event.pointerId); } catch (_) { /* not supported */ }
});

nav.addEventListener('pointermove', event => {
  if (!dragState || event.pointerId !== dragState.id) return;
  const dx = event.clientX - dragState.startX;
  const dy = event.clientY - dragState.startY;
  // Vertical intent → let the page scroll; don't hijack it.
  if (!dragState.dragging && Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx) * 1.5) {
    dragState = null;
    return;
  }
  dragState.dx = dx;
  if (Math.abs(dx) > 4) dragState.dragging = true;
  // Rubber-band at the edges so it stays liquid instead of flying away.
  const max = Math.min(nav.offsetWidth * 0.35, 110);
  const tx = dx > max ? max + (dx - max) * 0.3 : (dx < -max ? -max - (dx + max) * 0.3 : dx);
  nav.style.transition = 'none';
  nav.style.transform = `translateX(calc(-50% + ${tx}px)) rotate(${tx * 0.02}deg)`;
});

function endNavDrag(event) {
  if (!dragState || event.pointerId !== dragState.id) return;
  const { dx, dragging } = dragState;
  dragState = null;
  // Spring back to centre; the transition does the rest.
  nav.style.transition = '';
  nav.style.transform = 'translateX(-50%)';
  if (!dragging) return;
  suppressTabClick = true;
  const index = NAV_TABS.indexOf(activeTabName());
  const delta = dx > SWIPE_THRESHOLD ? 1 : (dx < -SWIPE_THRESHOLD ? -1 : 0);
  const next = index + delta;
  if (delta !== 0 && next >= 0 && next < NAV_TABS.length) showTab(NAV_TABS[next]);
  setTimeout(() => { suppressTabClick = false; }, 50);
}

nav.addEventListener('pointerup', endNavDrag);
nav.addEventListener('pointercancel', endNavDrag);

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

$('.more').onclick = openLimitModal;
$('#editLimit').onclick = openLimitModal;
$('#saveLimit').onclick = saveLimit;
$('#removeLimit').onclick = removeLimitLocal;
$('#closeLimit').onclick = closeLimitModal;
$('[data-close-limit]').onclick = closeLimitModal;
$('#limitInput').oninput = updateLimitPreview;
$('#limitInput').addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    saveLimit();
  }
});

$('#dashAvatar').onclick = () => showTab('profile');
$('#avatarEdit').onclick = () => $('#avatarInput').click();
$('#editAvatarLink').onclick = () => $('#avatarInput').click();
$('#avatarInput').onchange = event => {
  const file = event.target.files && event.target.files[0];
  if (file) saveAvatar(file);
  event.target.value = '';
};
$('#removeAvatar').onclick = removeAvatarPhoto;
$('#loginBtn').onclick = () => doAuth('login');
$('#registerBtn').onclick = () => doAuth('register');
$('#logoutBtn').onclick = logout;
$('#copyKey').onclick = copyShortcutKey;
$('#authPassword').addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    doAuth('login');
  }
});

render();
syncProfileKeyUi();
if (!KEY) showTab('profile');
load();

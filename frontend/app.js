'use strict';

import './styles.css';
import { apiFetch, hasApiConfiguration } from './api.js';

// Skipped inside the Android/iOS shell: the app shell already ships in the
// APK, and a cached copy would survive app updates and serve the old UI.
if ('serviceWorker' in navigator && !window.Capacitor) {
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
const THEME_STORAGE = 'expenses-theme';

/* —— Theme ——
 * index.html resolves the theme before first paint; this takes over from
 * there. Only an explicit tap is stored: with nothing stored the app keeps
 * following the system, so switching the phone to dark at sunset carries the
 * app with it. */
const THEME_COLOR = { light: '#f5f5f7', dark: '#101317' };

function storedTheme() {
  try {
    const saved = localStorage.getItem(THEME_STORAGE);
    return saved === 'dark' || saved === 'light' ? saved : null;
  } catch {
    return null;
  }
}

function systemTheme() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function activeTheme() {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

function applyTheme(theme, { remember = false } = {}) {
  document.documentElement.dataset.theme = theme;
  // Keeps the iOS status bar and the Android chrome in step with the page.
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[theme]);
  if (remember) {
    try {
      localStorage.setItem(THEME_STORAGE, theme);
    } catch {
      /* private mode: the choice lasts for this session only */
    }
  }
  syncThemeUi();
}

function syncThemeUi() {
  const theme = activeTheme();
  $$('[data-theme-choice]').forEach(button => {
    const chosen = button.dataset.themeChoice === theme;
    button.classList.toggle('active', chosen);
    button.setAttribute('aria-pressed', String(chosen));
  });
}

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

// The manifest's "Add an expense" shortcut opens /?tab=add. Read it here and
// strip it, so a long-press launch lands on the right tab and a later reload
// does not keep forcing it.
const tabFromUrl = (params.get('tab') || '').trim().toLowerCase();
if (tabFromUrl) {
  params.delete('tab');
  const rest = `${location.pathname}${params.toString() ? `?${params}` : ''}${location.hash}`;
  history.replaceState(null, '', rest || '/');
}
const INR = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
/* —— Category icons ——
 * Drawn here rather than fetched: bundled means they render instantly, work
 * offline, and no third party ever learns what you spend on.
 *
 * Three tones, all from the existing palette -- green for what sustains you,
 * amber for what you chose, ink for what you owe. No new hues: the app is
 * deliberately monochrome apart from green and amber.
 *
 * The tone is keyed to the category, so a category looks the same wherever it
 * appears. The disc used to be tinted by row position, which meant the same
 * Food row was a different colour depending on where it landed in the list. */
const ICON_SET = {
  food: ['amber', '<path d="M4 11h16a8 8 0 0 1-8 8 8 8 0 0 1-8-8z"/><path d="M6.5 8.2c0-1.4 1-1.6 1-2.7M10 7.6c0-1.6 1.2-1.9 1.2-3.1M14 8.2c0-1.4 1-1.6 1-2.7"/>'],
  groceries: ['green', '<path d="M3 4h2l2.2 10.4a1.6 1.6 0 0 0 1.6 1.3h7.7a1.6 1.6 0 0 0 1.6-1.2L20 8H6"/><circle cx="9.5" cy="19" r="1.3"/><circle cx="17" cy="19" r="1.3"/>'],
  travel: ['ink', '<path d="M12 3c.85 0 1.5 1.1 1.5 2.4v2.9l6.6 3.8v2l-6.6-2v3.6l2.2 1.6v1.5L12 17.7l-3.7 1.1v-1.5l2.2-1.6v-3.6l-6.6 2v-2l6.6-3.8V5.4C10.5 4.1 11.15 3 12 3z"/>'],
  cab: ['ink', '<path d="M5 16.5h14M6.5 16.5V19a.8.8 0 0 1-.8.8H5a.8.8 0 0 1-.8-.8v-2.5M19.8 16.5V19a.8.8 0 0 1-.8.8h-.7a.8.8 0 0 1-.8-.8v-2.5"/><path d="M4.2 16.5v-4l1.9-4.3a1.4 1.4 0 0 1 1.3-.8h9.2a1.4 1.4 0 0 1 1.3.8l1.9 4.3v4z"/><path d="M6.6 12.4h10.8"/>'],
  fuel: ['ink', '<path d="M5 20.5h9V6a1.5 1.5 0 0 0-1.5-1.5h-6A1.5 1.5 0 0 0 5 6z"/><path d="M5 11.5h9"/><path d="M14 9h2.8a1.2 1.2 0 0 1 1.2 1.2v6.1a1.6 1.6 0 0 0 3.2 0V11l-2-2.4"/>'],
  bills: ['ink', '<path d="M6 3.5h12v17l-2-1.4-2 1.4-2-1.4-2 1.4-2-1.4-2 1.4z"/><path d="M9 8h6M9 12h6"/>'],
  rent: ['ink', '<path d="M3.8 10.3 12 4l8.2 6.3V20a1 1 0 0 1-1 1H4.8a1 1 0 0 1-1-1z"/><path d="M9.6 21v-6.2h4.8V21"/>'],
  health: ['green', '<path d="M12 20.3s-7.4-4.5-7.4-9.6A4.4 4.4 0 0 1 12 7.7a4.4 4.4 0 0 1 7.4 3c0 5.1-7.4 9.6-7.4 9.6z"/><path d="M12 11v4M10 13h4"/>'],
  fitness: ['green', '<path d="M4 9.5v5M7 7.5v9M17 7.5v9M20 9.5v5M7 12h10"/>'],
  entertainment: ['amber', '<rect x="3" y="5" width="18" height="14" rx="2.2"/><path d="M7 5v14M17 5v14M3 12h18M3 8.5h4M3 15.5h4M17 8.5h4M17 15.5h4"/>'],
  shopping: ['amber', '<path d="M5.5 8h13l-1 12.2a1 1 0 0 1-1 .9H7.5a1 1 0 0 1-1-.9z"/><path d="M9 10V6.5a3 3 0 0 1 6 0V10"/>'],
  coffee: ['amber', '<path d="M4.5 8h12v6.5a4.5 4.5 0 0 1-4.5 4.5H9a4.5 4.5 0 0 1-4.5-4.5z"/><path d="M16.5 9.5h1.8a2.6 2.6 0 0 1 0 5.2h-1.8"/><path d="M8 3.4v1.8M12 3.4v1.8"/>'],
  education: ['ink', '<path d="M3.6 6.2A12 12 0 0 1 12 7.6a12 12 0 0 1 8.4-1.4v11A12 12 0 0 0 12 18.6a12 12 0 0 0-8.4-1.4z"/><path d="M12 7.6v11"/>'],
  gifts: ['amber', '<rect x="3.4" y="8.6" width="17.2" height="4.2" rx="1"/><path d="M5 12.8v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7M12 8.6v12.2"/><path d="M12 8.6S10.8 4 8.6 4a2.3 2.3 0 0 0 0 4.6zM12 8.6S13.2 4 15.4 4a2.3 2.3 0 0 1 0 4.6z"/>'],
  expense: ['ink', '<path d="M3.5 8.5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2"/><rect x="3.5" y="8.5" width="17" height="10.5" rx="2"/><path d="M15.4 13.75h2.6"/>'],
};
const ICON_FALLBACK = ['ink', '<path d="M4 11.3V5.4a1.4 1.4 0 0 1 1.4-1.4h5.9a1.4 1.4 0 0 1 1 .4l6.3 6.3a1.4 1.4 0 0 1 0 2l-5.9 5.9a1.4 1.4 0 0 1-2 0L4.4 12.3a1.4 1.4 0 0 1-.4-1z"/><circle cx="8.3" cy="8.3" r="1.2"/>'];

/** Grocery is a common spelling of the same thing. */
const ICON_ALIAS = { grocery: 'groceries', groceries: 'groceries' };

function categoryIcon(category) {
  const name = (category || '').trim().toLowerCase();
  return ICON_SET[ICON_ALIAS[name] || name] || ICON_FALLBACK;
}

/** The tinted disc plus its glyph, used by the list and by Top spending. */
function iconMarkup(category, size = 21) {
  const [tone, path] = categoryIcon(category);
  return `<div class="icon tone-${tone}"><svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg></div>`;
}

let expenses = [];
let monthlyLimit = null;
let avatarData = null;
let account = null;   // { username, api_key } once signed in with a password
let recurring = [];
// Which credential the once-per-login side data (identity, limit, avatar,
// recurring rules) was loaded for. Keeps that data off the 15s poll.
let sideDataKey = null;
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

/** kind: 'ok' (green dot, default), 'muted' (gray, transitional), 'err' (red). */
function setStatus(text, kind = 'ok') {
  $('#statusText').textContent = text;
  $('#status').className = `sync-status ${kind}`;
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
  const icon = iconMarkup(item.category);
  const time = dateOf(item.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  // Expenses logged from the app carry no description; skip the line rather
  // than repeating "Expense" under the category.
  const desc = (item.description || item.notes || '').trim();
  return `<article class="tx${compact ? ' compact' : ''}">
    ${icon}
    <div class="main">
      <div class="name">${escapeHtml(item.category || 'Expense')}</div>
      ${desc ? `<div class="desc">${escapeHtml(desc)}</div>` : ''}
      <div class="meta">${escapeHtml(time)}${item.payment_method ? ` · ${escapeHtml(item.payment_method)}` : ''}${item.recurring_id ? '<span class="tx-repeat" title="From a recurring rule">↻</span>' : ''}</div>
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
          <stop class="chart-fill-stop" offset="0%" stop-opacity="0.18"/>
          <stop class="chart-fill-stop" offset="100%" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path d="${area}" fill="url(#chartFill)"/>
      <path class="chart-line" d="${line}" fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="${peak.x}" y1="${padTop}" x2="${peak.x}" y2="${h - padBottom}" class="chart-guide" stroke-width="1.2" stroke-dasharray="4 4"/>
      <circle class="chart-dot" cx="${peak.x}" cy="${peak.y}" r="5"/>
      <circle class="chart-dot-core" cx="${peak.x}" cy="${peak.y}" r="2.5"/>
      ${valueLabels}
      <rect class="chart-badge" x="${peakX}" y="${peakY}" width="${peakWidth}" height="22" rx="8"/>
      <text class="chart-tooltip" x="${peakX + peakWidth / 2}" y="${peakY + 15}" text-anchor="middle">${peakLabel}</text>
      ${points.map(p => `<text class="chart-axis" x="${p.x}" y="${h - 6}" text-anchor="middle" font-size="9" font-weight="600">${escapeHtml(p.label)}</text>`).join('')}
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

/** Full spend on the previous calendar day (local). */
function yesterdaySpend() {
  const now = new Date();
  const day = now.getDate() - 1;
  return spendInSpan(
    new Date(now.getFullYear(), now.getMonth(), day),
    new Date(now.getFullYear(), now.getMonth(), day, 23, 59, 59, 999),
  );
}

/** Full spend in the previous calendar month (local). */
function lastMonthSpend() {
  const now = new Date();
  return spendInSpan(
    new Date(now.getFullYear(), now.getMonth() - 1, 1),
    new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59, 999),
  );
}

/** "↑ 12% from last month" style delta line, colored by direction. */
function deltaLine(curr, prev, suffix) {
  if (prev <= 0) {
    return curr > 0
      ? `<span class="delta up">↑ New vs ${suffix}</span>`
      : `<span class="delta flat">— 0% ${suffix}</span>`;
  }
  const pct = Math.round(((curr - prev) / prev) * 100);
  if (pct === 0) return `<span class="delta flat">— 0% ${suffix}</span>`;
  return `<span class="delta ${pct > 0 ? 'up' : 'down'}">${pct > 0 ? '↑' : '↓'} ${Math.abs(pct)}% ${suffix}</span>`;
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

const BUDGET_ROW_ICONS = {
  green: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5.5" width="17" height="15" rx="2.5"/><path d="M3.5 9.5h17M8 3.5v3M16 3.5v3"/></svg>',
  orange: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  ink: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 19V11M12 19V5M19 19v-7"/></svg>',
};
const BUDGET_ROW_COLOR = { green: 'var(--green)', orange: 'var(--orange)', ink: 'var(--ink)' };
const BUDGET_ROW_TEXT = { green: 'var(--green)', orange: '#f59e0b', ink: 'var(--ink)' };

function budgetRow(label, spent, target, key) {
  const pct = target > 0 ? Math.min(100, (spent / target) * 100) : 0;
  const over = target > 0 && spent > target;
  const remText = target > 0 ? (over ? `${INR.format(spent - target)} over` : `${INR.format(target - spent)} left`) : '';
  const remColor = over ? 'var(--danger)' : BUDGET_ROW_TEXT[key];
  return `
    <div class="budget-row">
      <div class="budget-row-icon ${key}">${BUDGET_ROW_ICONS[key]}</div>
      <div class="budget-row-main">
        <span class="budget-row-label">${label}</span>
        <div class="budget-track ${over ? 'over' : ''}"><i style="width:${pct}%;${over ? '' : `background:${BUDGET_ROW_COLOR[key]}`}"></i></div>
      </div>
      <div class="budget-row-right">
        <span class="budget-row-amt">${INR.format(spent)} <small>/ ${INR.format(target)}</small></span>
        <span class="budget-row-rem" style="color:${remColor}">${remText}</span>
      </div>
      <svg class="budget-chevron" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>
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

  const remaining = Math.max(0, monthlyLimit - spent.month);
  const usedPct = monthlyLimit > 0 ? Math.min(100, (spent.month / monthlyLimit) * 100) : 0;
  $('#budgetRemaining').textContent = INR.format(remaining);
  $('#budgetSpentFrac').textContent = `${INR.format(spent.month)} / ${INR.format(monthlyLimit)}`;
  $('#budgetSpentBar').style.width = `${usedPct}%`;
  $('#budgetSpentPct').textContent = `${Math.round(usedPct)}% used`;

  $('#budgetBars').innerHTML =
    budgetRow('This week', spent.week, weekTarget, 'green') +
    budgetRow('Today', spent.today, dayTarget, 'orange') +
    budgetRow('This month', spent.month, monthlyLimit, 'ink');
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
    setStatus('Monthly limit saved');
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
    setStatus('Monthly limit removed');
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

const FREQUENCY_LABEL = { daily: 'Every day', weekly: 'Every week', monthly: 'Every month' };

async function loadRecurring() {
  if (!KEY) return;
  try {
    const response = await apiFetch('/api/recurring', authed({ cache: 'no-store' }));
    if (!response.ok) return;
    recurring = (await response.json()).recurring || [];
    renderRecurring();
  } catch (error) {
    console.error(error);
  }
}

/** "Every month · next on 5 Oct", or why it will not run again. */
function recurringWhen(rule) {
  const label = FREQUENCY_LABEL[rule.frequency] || rule.frequency;
  if (!rule.active) return `${label} · paused`;
  if (!rule.next_run) return `${label} · finished`;
  const [y, m, d] = rule.next_run.split('-').map(Number);
  const when = new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return `${label} · next on ${when}`;
}

function renderRecurring() {
  const count = $('#profileRecurringCount');
  if (count) {
    const active = recurring.filter(rule => rule.active).length;
    count.textContent = recurring.length
      ? `${active} active${recurring.length > active ? ` / ${recurring.length}` : ''}`
      : 'None';
  }
  const list = $('#recurringList');
  if (!list) return;
  list.innerHTML = recurring.length
    ? recurring.map(rule => `
        <div class="recurring-item${rule.active ? '' : ' paused'}">
          <div class="recurring-item-name">${escapeHtml(rule.category || 'Expense')}</div>
          <div class="recurring-item-amt">${INR.format(rule.amount)}</div>
          <div class="recurring-item-meta">${escapeHtml(recurringWhen(rule))}${rule.payment_method ? ` · ${escapeHtml(rule.payment_method)}` : ''}</div>
          <div class="recurring-item-actions">
            <button type="button" data-recurring-toggle="${escapeHtml(rule.id)}">${rule.active ? 'Pause' : 'Resume'}</button>
            <button type="button" class="danger" data-recurring-delete="${escapeHtml(rule.id)}">Delete</button>
          </div>
        </div>`).join('')
    : '<div class="empty">No recurring expenses yet.</div>';
}

function openRecurringModal() {
  renderRecurring();
  $('#recurringModal').hidden = false;
  loadRecurring();  // refresh in the background; the list is already drawn
}

function closeRecurringModal() {
  $('#recurringModal').hidden = true;
}

async function toggleRecurring(id) {
  const rule = recurring.find(item => item.id === id);
  if (!rule) return;
  try {
    const response = await apiFetch(`/api/recurring/${encodeURIComponent(id)}`, authed({
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active: !rule.active }),
    }));
    if (!response.ok) throw new Error('Could not update this rule');
    // reload rather than patching local state: next_run is computed server-side
    await loadRecurring();
    // resuming can make occurrences due right away
    load({ quiet: true }).catch(() => {});
    setStatus(rule.active ? 'Recurring expense paused' : 'Recurring expense resumed');
  } catch (error) {
    console.error(error);
    alert('Could not update this recurring expense. Try again.');
  }
}

async function removeRecurring(id) {
  const rule = recurring.find(item => item.id === id);
  if (!rule) return;
  // Deliberately two questions: deleting the rule is not the same as
  // deleting spending that already happened.
  if (!confirm(`Stop the recurring ${rule.category || 'expense'}?`)) return;
  const purge = confirm('Also delete the expenses it already added?\n\nOK = delete them too, Cancel = keep them.');
  try {
    const response = await apiFetch(
      `/api/recurring/${encodeURIComponent(id)}${purge ? '?purge=true' : ''}`,
      authed({ method: 'DELETE' }),
    );
    if (!response.ok && response.status !== 404) throw new Error('Could not delete this rule');
    recurring = recurring.filter(item => item.id !== id);
    renderRecurring();
    if (purge) await load({ quiet: true });
    setStatus('Recurring expense deleted');
  } catch (error) {
    console.error(error);
    alert('Could not delete this recurring expense. Try again.');
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
    setStatus('Profile photo saved');
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
    setStatus('Profile photo removed');
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
  $('#heroDate').textContent = new Date().toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
  $('#stats').innerHTML = `
    <div class="stat"><span class="stat-icon">↗</span><div><small>Today</small><strong>${INR.format(today)}</strong>${deltaLine(today, yesterdaySpend(), 'from yesterday')}</div></div>
    <div class="stat"><span class="stat-icon">↘</span><div><small>Selected</small><strong>${INR.format(total)}</strong>${deltaLine(monthSpend(), lastMonthSpend(), 'from last month')}</div></div>`;

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
        ${iconMarkup(item.category, 19)}
        <div>
          <strong>${escapeHtml(item.category || 'Expense')}</strong>
          <small>${escapeHtml(item.description || item.payment_method || '')}</small>
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
  renderRecurring();
}

function showTab(name) {
  $$('[data-panel]').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === name));
  $$('[data-tab]').forEach(button => button.classList.toggle('nav-active', button.dataset.tab === name));
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

  const repeat = $('#expenseRepeat')?.value || 'none';
  const hint = $('#repeatHint');
  const button = $('#saveExpense');
  if (hint) {
    hint.hidden = repeat === 'none';
    hint.textContent = repeat === 'none'
      ? ''
      : `Saved as a rule — ${(FREQUENCY_LABEL[repeat] || repeat).toLowerCase()}, starting today. Manage it from Profile.`;
  }
  if (button) button.textContent = repeat === 'none' ? 'Save expense' : 'Save recurring expense';
}

async function load({ quiet = false } = {}) {
  if (!hasApiConfiguration()) {
    setStatus('Set PRIMARY_API_URL and SECONDARY_API_URL in frontend/.env.local', 'err');
    syncProfileKeyUi('Backend URLs are not configured', 'err');
    return false;
  }
  if (!KEY) {
    setStatus('Open Profile to log in', 'muted');
    expenses = [];
    render();
    syncProfileKeyUi('Paste your API key, then tap Save & load data');
    syncAuthUi();
    return false;
  }
  if (!quiet) {
    setStatus('Loading expenses…', 'muted');
  }
  try {
    const response = await apiFetch('/api/expenses?limit=1000', authed({ cache: 'no-store' }));
    if (response.status === 401) throw new Error('Invalid API key');
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    expenses = (await response.json()).expenses || [];
    render();
    setStatus('Updated just now');
    syncProfileKeyUi(`Connected · ${maskKey(KEY)}`, 'ok');
    // Only the expense list belongs on the poll. Identity, limit, profile and
    // recurring rules change when *you* change them, and /api/profile carries
    // the avatar inline as a base64 data URL — refetching that every 15s
    // re-downloaded the same photo ~240 times an hour. Loaded once per
    // credential, and again only when something actually changes it.
    if (sideDataKey !== KEY) {
      sideDataKey = KEY;
      loadMe();
      loadLimit();
      loadProfile();
      loadRecurring();
    }
    return true;
  } catch (error) {
    console.error(error);
    const message = error.message === 'Failed to fetch'
      ? 'Could not reach API — check its URL and CORS_ORIGINS'
      : error.message;
    if (!quiet) setStatus(message, 'err');
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
  monthlyLimit = null;
  avatarData = null;
  recurring = [];
  sideDataKey = null;
  writeStoredApiKey('');
  $('#apiKeyInput').value = '';
  render();
  setStatus('Open Profile and paste your API key', 'muted');
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

async function saveRecurringRule({ amount, category, paymentMethod, repeat, saveButton, error }) {
  saveButton.disabled = true;
  saveButton.textContent = 'Saving…';
  setStatus('Saving recurring expense…', 'muted');
  try {
    const response = await apiFetch('/api/recurring', authed({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount, category, payment_method: paymentMethod, frequency: repeat,
      }),
    }));
    if (!response.ok) {
      throw new Error(response.status === 409
        ? 'You have too many recurring expenses.'
        : 'Could not save this recurring expense.');
    }
    const body = await response.json().catch(() => ({}));
    $('#expenseForm').reset();
    $('#expenseCategory').value = 'Expense';
    $('#expenseRepeat').value = 'none';
    updateAddPreview();
    error.textContent = '';
    await loadRecurring();
    await load({ quiet: true });
    showTab('transactions');
    const added = body.created_expenses || 0;
    setStatus(added
      ? `Recurring expense saved · ${added} added`
      : 'Recurring expense saved');
  } catch (err) {
    error.textContent = err.message || 'Could not save this recurring expense.';
    setStatus('Save failed — try again', 'err');
  } finally {
    saveButton.disabled = false;
    updateAddPreview();  // restores the right label for whatever Repeat now says
  }
}

async function saveExpense(event) {
  event.preventDefault();
  const amount = Number($('#expenseAmount').value);
  const category = ($('#expenseCategory').value.trim() || 'Expense');
  const paymentMethod = $('#expensePayment').value;
  const error = $('#formError');

  if (!amount) {
    error.textContent = 'Enter an amount.';
    return;
  }
  if (!KEY) {
    error.textContent = 'Save your API key in Profile first.';
    showTab('profile');
    return;
  }

  const saveButton = $('#saveExpense');
  const repeat = $('#expenseRepeat')?.value || 'none';
  if (repeat !== 'none') {
    // A rule is not an expense: the backend materialises today's occurrence
    // (and any it owes) itself, so there is nothing to show optimistically
    // here — an optimistic row would duplicate the one the reload brings back.
    await saveRecurringRule({ amount, category, paymentMethod, repeat, saveButton, error });
    return;
  }
  const tempId = `local-${Date.now()}`;
  const nowIso = new Date().toISOString();
  const optimistic = {
    id: tempId,
    amount,
    category,
    description: null,
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
  setStatus('Saving…', 'muted');
  saveButton.disabled = true;
  saveButton.textContent = 'Saving…';

  try {
    const response = await apiFetch('/api/expenses', authed({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount, category, payment_method: paymentMethod }),
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
    setStatus('Expense saved');
    load({ quiet: true }).catch(() => {});
  } catch (err) {
    expenses = expenses.filter(item => item.id !== tempId);
    render();
    showTab('add');
    error.textContent = err.message || 'Could not save this expense.';
    setStatus('Save failed — try again', 'err');
  } finally {
    saveButton.disabled = false;
    saveButton.textContent = 'Save expense';
  }
}

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
$('#expenseRepeat').onchange = updateAddPreview;

$('#manageRecurring').onclick = () => {
  if (!KEY) {
    showTab('profile');
    return;
  }
  openRecurringModal();
};
$('#closeRecurring').onclick = closeRecurringModal;
$('[data-close-recurring]').onclick = closeRecurringModal;
$('#recurringList').onclick = event => {
  const toggle = event.target.closest('[data-recurring-toggle]');
  if (toggle) {
    toggleRecurring(toggle.dataset.recurringToggle);
    return;
  }
  const remove = event.target.closest('[data-recurring-delete]');
  if (remove) removeRecurring(remove.dataset.recurringDelete);
};

$$('[data-tab]').forEach(button => {
  button.onclick = () => {
    if (suppressTabClick) return;
    showTab(button.dataset.tab);
  };
});

/* —— Pull to refresh ——
 * Works on every tab, because "is my data current?" is a question you can ask
 * from any of them. Touch only: a mouse has no Reload button any more, but
 * hijacking a downward mouse drag would fight text selection.
 *
 * Only starts when the page is already at the top, so it can never swallow a
 * scroll -- the mistake the nav's swipe handler made.
 *
 * The content moves with the finger and the disc rides in the gap it opens.
 * The first version left the page still and floated a disc over the header:
 * it read as something stuck on top of the app rather than part of it, it
 * jumped 7px on the first frame (the resting and starting positions did not
 * meet), and it spun the icon 288 degrees over a single pull. */
const PULL_TRIGGER_PX = 72;    // past this, releasing reloads
const PULL_MAX_PX = 150;       // the content stops following beyond this
const PULL_START_PX = 6;       // slop, so a tap is not a pull
const PULL_HOLD_PX = 56;       // where the content rests while reloading
const PULL_RESIST = 0.5;       // content follows at half speed: it feels weighted
const pullEl = $('#pullRefresh');
const appEl = $('.app');
let pullState = null;
let refreshing = false;

/** Eased travel for a raw finger distance. The slop is subtracted rather than
 *  measured away, so the content starts from zero with no jump *and* the
 *  distance the trigger compares against stays the true finger distance. Past
 *  PULL_MAX the extra is heavily damped rather than clamped, so it never feels
 *  like it hit a wall. */
function pullTravel(distance) {
  const pulled = Math.max(0, distance - PULL_START_PX);
  const capped = Math.min(pulled, PULL_MAX_PX);
  const overflow = Math.max(0, pulled - PULL_MAX_PX);
  return capped * PULL_RESIST + overflow * 0.08;
}

/** How close this pull is to triggering, 0 to 1. Drives the disc's fade, scale
 *  and turn, so what you see is exactly what releasing will do -- it is the
 *  same number the trigger tests. */
function pullProgress(distance) {
  return Math.min(1, Math.max(0, distance) / PULL_TRIGGER_PX);
}

/** One place that positions both pieces, so they can never disagree. */
function paintPull(travel, { settle = false, progress = null } = {}) {
  pullEl.classList.toggle('settling', settle);
  appEl.classList.toggle('settling', settle);
  appEl.style.transform = travel ? `translateY(${travel.toFixed(1)}px)` : '';
  // The disc rides just above the content edge, so at rest it is exactly
  // off-screen and the first frame of a pull moves it continuously from there.
  const ratio = progress ?? 0;
  pullEl.style.transform =
    `translate(-50%, ${(travel - 44).toFixed(1)}px) scale(${(0.7 + ratio * 0.3).toFixed(3)})`;
  pullEl.style.opacity = ratio.toFixed(3);
  // A half turn by the time it is ready, not three and a half.
  pullEl.style.setProperty('--pull-turn', `${(ratio * 180).toFixed(1)}deg`);
  pullEl.classList.toggle('ready', ratio >= 1);
}

function resetPull({ settle = true } = {}) {
  paintPull(0, { settle, progress: 0 });
}

async function runRefresh() {
  refreshing = true;
  pullEl.classList.add('spinning');
  // Hold the content down while it loads, then let it spring back: the gap is
  // what makes the spinner look like it belongs to the page.
  paintPull(PULL_HOLD_PX, { settle: true, progress: 1 });
  try {
    await load();
  } finally {
    refreshing = false;
    pullEl.classList.remove('spinning', 'ready');
    resetPull();
  }
}

/** A pull can only begin at the very top, outside the nav, with no modal up. */
function canStartPull(target) {
  if (refreshing || window.scrollY > 0) return false;
  if (target.closest('.bottom-nav')) return false;            // that is the tab swipe
  if (target.closest('.modal:not([hidden])')) return false;   // modals scroll themselves
  return true;
}

document.addEventListener('touchstart', event => {
  if (event.touches.length !== 1 || !canStartPull(event.target)) {
    pullState = null;
    return;
  }
  const touch = event.touches[0];
  pullState = { startX: touch.clientX, startY: touch.clientY, dy: 0, active: false };
}, { passive: true });

document.addEventListener('touchmove', event => {
  if (!pullState || event.touches.length !== 1) return;
  const touch = event.touches[0];
  const dy = touch.clientY - pullState.startY;
  const dx = touch.clientX - pullState.startX;

  if (!pullState.active) {
    // Up, sideways, or scrolled away from the top in the meantime: not a pull.
    if (dy < PULL_START_PX || Math.abs(dx) > Math.abs(dy) || window.scrollY > 0) {
      if (dy < 0 || Math.abs(dx) > Math.abs(dy)) pullState = null;
      return;
    }
    pullState.active = true;
  }

  pullState.dy = dy;
  // Stops the page scrolling under the gesture. Needs passive: false.
  if (event.cancelable) event.preventDefault();
  paintPull(pullTravel(dy), { progress: pullProgress(dy) });
}, { passive: false });

function endPull() {
  if (!pullState) return;
  const { active, dy } = pullState;
  pullState = null;
  if (active && dy >= PULL_TRIGGER_PX) runRefresh();
  else resetPull();
}

document.addEventListener('touchend', endPull);
document.addEventListener('touchcancel', endPull);

/* —— Liquid-glass navbar: springy horizontal swipe / drag —— */
const NAV_TABS = ['dashboard', 'transactions', 'add', 'analytics', 'profile'];
const nav = $('.bottom-nav');
const SWIPE_THRESHOLD = 60;
// Movement needed before the gesture commits to an axis. Below this a touch is
// still ambiguous, so committing early is what used to turn a scroll into a
// tab change.
const AXIS_LOCK_PX = 10;
// Horizontal has to genuinely dominate to win the lock; a thumb scrolling down
// always carries some sideways drift.
const AXIS_BIAS = 1.3;
// If the page moved during the gesture it was a scroll, whatever the pointer
// deltas say.
const SCROLL_TOLERANCE_PX = 8;
let dragState = null;
let suppressTabClick = false;

function activeTabName() {
  const active = $$('[data-tab]').find(button => button.classList.contains('nav-active'));
  return active ? active.dataset.tab : 'dashboard';
}

function resetNavPosition() {
  nav.style.transition = '';
  nav.style.transform = 'translateX(-50%)';
}

nav.addEventListener('pointerdown', event => {
  if (event.button != null && event.button !== 0) return;
  dragState = {
    id: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    dx: 0,
    // null until the gesture commits to 'x' (a swipe) or 'y' (a scroll, which
    // we abandon). Deciding once and sticking to it is the whole point.
    axis: null,
    dragging: false,
    // showTab() scrolls to the top, so a swipe misread from a scroll threw the
    // page to the top mid-scroll. Compared again on release.
    scrollY: window.scrollY,
  };
  // Capture is claimed in pointermove, once this is actually a drag -- never
  // here. Capturing on pointerdown retargets the *click* that follows to the
  // capture element, so every tab button's own onclick stopped firing and the
  // bar was dead for any mouse pointer. Touch hid it: a touch pointer is
  // implicitly captured to its own target, so the retarget changed nothing.
});

nav.addEventListener('pointermove', event => {
  if (!dragState || event.pointerId !== dragState.id) return;
  const dx = event.clientX - dragState.startX;
  const dy = event.clientY - dragState.startY;

  // Commit to one axis, once, on the first movement big enough to read — then
  // never reconsider. The old code set `dragging` as soon as |dx| > 4 and only
  // checked for vertical intent while !dragging, so the few pixels of sideways
  // drift at the start of any thumb scroll locked the gesture as a swipe
  // before the vertical test could ever run.
  if (dragState.axis === null) {
    if (Math.max(Math.abs(dx), Math.abs(dy)) < AXIS_LOCK_PX) return;
    if (Math.abs(dx) > Math.abs(dy) * AXIS_BIAS) {
      dragState.axis = 'x';
      dragState.dragging = true;
      // Now that it is a drag, capture so it survives the pointer leaving the
      // bar. A drag ends in a retargeted click, which navigates nothing --
      // and suppressTabClick covers touch, where there is no capture.
      try { nav.setPointerCapture(event.pointerId); } catch (_) { /* unsupported */ }
    } else {
      // Vertical (or ambiguous diagonal) → it's a scroll. Let go of it
      // entirely, and undo any nudge already applied to the bar.
      dragState = null;
      resetNavPosition();
      return;
    }
  }

  dragState.dx = dx;
  // Rubber-band at the edges so it stays liquid instead of flying away.
  const max = Math.min(nav.offsetWidth * 0.35, 110);
  const tx = dx > max ? max + (dx - max) * 0.3 : (dx < -max ? -max - (dx + max) * 0.3 : dx);
  nav.style.transition = 'none';
  nav.style.transform = `translateX(calc(-50% + ${tx}px)) rotate(${tx * 0.02}deg)`;
});

function endNavDrag(event) {
  if (!dragState || event.pointerId !== dragState.id) return;
  const { dx, dragging, scrollY } = dragState;
  dragState = null;
  // Spring back to centre; the transition does the rest.
  resetNavPosition();
  if (!dragging) return;
  // Last line of defence: if the page scrolled while this gesture was in
  // flight, it was a scroll. Navigating now would also scroll to the top.
  if (Math.abs(window.scrollY - scrollY) > SCROLL_TOLERANCE_PX) return;
  suppressTabClick = true;
  const index = NAV_TABS.indexOf(activeTabName());
  // Dragging right reveals what sits to the left, so it goes to the previous
  // tab — the bar was animating one way and navigating the other.
  const delta = dx > SWIPE_THRESHOLD ? -1 : (dx < -SWIPE_THRESHOLD ? 1 : 0);
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

// There is a copy on Transactions and one on Profile; syncThemeUi() already
// paints every [data-theme-choice] there is, so both stay in step on their own.
$$('.theme-toggle').forEach(group => {
  group.onclick = event => {
    const button = event.target.closest('[data-theme-choice]');
    if (button) applyTheme(button.dataset.themeChoice, { remember: true });
  };
});

// Track the system only until the user picks a side, and never afterwards.
window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
  if (!storedTheme()) applyTheme(systemTheme());
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

/* The floating nav would sit on top of whatever field you are typing into, so
   it gets out of the way while the on-screen keyboard is up. Driven by the
   viewport actually shrinking rather than by focus: focusing a field on a
   desktop opens no keyboard, and the Add tab autofocuses its amount box. */
const viewport = window.visualViewport;
if (viewport) {
  const KEYBOARD_MIN_PX = 140;  // taller than any browser chrome that comes and goes
  const syncKeyboardState = () => {
    const hidden = window.innerHeight - viewport.height > KEYBOARD_MIN_PX;
    document.body.classList.toggle('keyboard-open', hidden);
  };
  viewport.addEventListener('resize', syncKeyboardState);
  syncKeyboardState();
}

applyTheme(storedTheme() || systemTheme());

render();
syncProfileKeyUi();
if (!KEY) showTab('profile');
else if (tabFromUrl && NAV_TABS.includes(tabFromUrl)) showTab(tabFromUrl);
load();

// Auto-refresh so expenses added elsewhere (e.g. the Shortcut) show up
// without a manual reload tap. Paused while the tab is hidden, and backs off
// on repeated failures (15s -> 30s -> 60s) so a sleeping/dead API isn't
// polled at full speed forever; resets to 15s on the next success.
const POLL_BASE_MS = 15_000;
const POLL_MAX_MS = 60_000;
let pollDelay = POLL_BASE_MS;
let pollTimer = null;

function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(pollTick, pollDelay);
}

async function pollTick() {
  if (document.visibilityState === 'visible') {
    const ok = await load({ quiet: true });
    pollDelay = ok ? POLL_BASE_MS : Math.min(pollDelay * 2, POLL_MAX_MS);
  }
  schedulePoll();
}

schedulePoll();

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  pollDelay = POLL_BASE_MS; // give it a fresh shot the moment you come back
  load({ quiet: true });
  schedulePoll();
});

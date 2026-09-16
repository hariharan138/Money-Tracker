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
let recurring = [];
// Which credential the once-per-login side data (identity, limit, avatar,
// recurring rules) was loaded for. Keeps that data off the 15s poll.
let sideDataKey = null;
// `month` is the one the whole app is looking at (ALL_MONTHS = no month
// filter). Every tab reads it, so switching month switches the app.
const ALL_MONTHS = 'all';
const state = { preset: 'month', payment: 'all', q: '', sort: 'newest', chartRange: 'days', month: currentMonthKey() };

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

/* —— Months ——————————————————————————————————————————————————————
   One selected month drives every tab. Keys are 'YYYY-MM', which sorts and
   compares correctly as a plain string, so no Date maths is needed to tell
   which of two months came first. */

function monthKeyOf(value) {
  const d = value instanceof Date ? value : dateOf(value);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function currentMonthKey() {
  return monthKeyOf(new Date());
}

/** Local [start, end] of a month key — end is the last millisecond of it. */
function monthBounds(key) {
  const [y, m] = key.split('-').map(Number);
  return [new Date(y, m - 1, 1), new Date(y, m, 0, 23, 59, 59, 999)];
}

function shiftMonthKey(key, delta) {
  const [y, m] = key.split('-').map(Number);
  return monthKeyOf(new Date(y, m - 1 + delta, 1));
}

function monthLabel(key, { short = false } = {}) {
  if (!key || key === ALL_MONTHS) return 'All time';
  const [y, m] = key.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: short ? 'short' : 'long', year: 'numeric' });
}

/** Just the month, for sentences that already carry the year ("in September"). */
function monthName(key) {
  if (!key || key === ALL_MONTHS) return 'all time';
  const [y, m] = key.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long' });
}

function inMonth(item, key = state.month) {
  return key === ALL_MONTHS || monthKeyOf(item.date) === key;
}

/** Everything in the selected month, before any search / payment filter. */
function monthExpenses(key = state.month) {
  return key === ALL_MONTHS ? expenses : expenses.filter(item => inMonth(item, key));
}

/** Months that actually have expenses, newest first; today's is always in. */
function monthsWithData() {
  const keys = new Set(expenses.map(item => monthKeyOf(item.date)).filter(Boolean));
  keys.add(currentMonthKey());
  if (state.month && state.month !== ALL_MONTHS) keys.add(state.month);
  return [...keys].sort().reverse();
}

/** You can step back as far as there is data, and forward no further than now. */
function monthNavBounds() {
  const months = monthsWithData();
  return { oldest: months.at(-1), newest: currentMonthKey() };
}

/** Day-relative presets only mean something when today is inside the window. */
function presetAllowed(preset) {
  return preset === 'month' || state.month === ALL_MONTHS || state.month === currentMonthKey();
}

function setMonth(key) {
  if (state.month === key) return;
  state.month = key;
  if (!presetAllowed(state.preset)) {
    state.preset = 'month';
    const select = $('#preset');
    if (select) select.value = 'month';
  }
  render();
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

/** The date window on screen: the selected month, narrowed by the preset. */
function activeWindow() {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let from = null;
  let to = null;
  if (state.month !== ALL_MONTHS) [from, to] = monthBounds(state.month);
  if (presetAllowed(state.preset)) {
    const starts = { today, 7: new Date(today - 6 * 864e5), 30: new Date(today - 29 * 864e5) };
    const start = starts[state.preset];
    // the later of the two: a preset can only ever narrow the month
    if (start && (!from || start > from)) from = start;
  }
  return { from, to };
}

function matchesQuery(item, query) {
  return !query || [item.category, item.description, item.notes, item.payment_method]
    .join(' ').toLowerCase().includes(query);
}

function filtered() {
  const { from, to } = activeWindow();
  const query = state.q.trim().toLowerCase();
  const order = {
    newest: (a, b) => dateOf(b.date) - dateOf(a.date),
    oldest: (a, b) => dateOf(a.date) - dateOf(b.date),
    high: (a, b) => b.amount - a.amount,
    low: (a, b) => a.amount - b.amount,
  }[state.sort];

  return expenses.filter(item => {
    const d = dateOf(item.date);
    if (from && d < from) return false;
    if (to && d > to) return false;
    if (state.payment !== 'all' && (item.payment_method || '').toLowerCase() !== state.payment) return false;
    return matchesQuery(item, query);
  }).sort(order);
}

/** Totals for whatever the Transactions tab is currently showing. */
function summarise(items) {
  const amounts = items.map(item => Number(item.amount) || 0);
  const total = amounts.reduce((a, b) => a + b, 0);
  const byCategory = [...items.reduce((map, item) => {
    const name = (item.category || 'Expense').trim() || 'Expense';
    map.set(name, (map.get(name) || 0) + (Number(item.amount) || 0));
    return map;
  }, new Map())].sort((a, b) => b[1] - a[1]);
  return {
    total,
    count: items.length,
    average: items.length ? total / items.length : 0,
    largest: amounts.length ? Math.max(...amounts) : 0,
    byCategory,
  };
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
  // Expenses logged from the app carry no description; skip the line rather
  // than repeating "Expense" under the category.
  const desc = (item.description || item.notes || '').trim();
  return `<article class="tx${compact ? ' compact' : ''}">
    <div class="icon">${icon}</div>
    <div class="main">
      <div class="name">${escapeHtml(item.category || 'Expense')}</div>
      ${desc ? `<div class="desc">${escapeHtml(desc)}</div>` : ''}
      <div class="meta">${escapeHtml(time)}${item.payment_method ? ` · ${escapeHtml(item.payment_method)}` : ''}${item.recurring_id ? '<span class="tx-repeat" title="From a recurring rule">↻</span>' : ''}</div>
    </div>
    <div class="amount">-${INR.format(item.amount)}</div>
    ${compact ? '' : `<button class="delete" data-delete="${escapeHtml(item.id)}" aria-label="Delete expense">×</button>`}
  </article>`;
}

/** The month the Insights tab charts; All time falls back to the live one. */
function chartScopeKey() {
  return state.month === ALL_MONTHS ? currentMonthKey() : state.month;
}

function chartScopeLabel() {
  const key = chartScopeKey();
  return state.chartRange === 'year' ? key.split('-')[0] : monthLabel(key);
}

/** Everything inside the window the chart is drawing. */
function chartScopeExpenses() {
  const key = chartScopeKey();
  if (state.chartRange === 'year') {
    const year = Number(key.split('-')[0]);
    return expenses.filter(item => dateOf(item.date).getFullYear() === year);
  }
  return expenses.filter(item => monthKeyOf(item.date) === key);
}

/** Spend per local day, built once per chart instead of once per bucket. */
function totalsByDay() {
  const map = new Map();
  for (const item of expenses) {
    const key = dayKey(item.date);
    if (key) map.set(key, (map.get(key) || 0) + (Number(item.amount) || 0));
  }
  return map;
}

/* Every range is anchored to the selected month: days of it, weeks of it, or
   the twelve months of its year. Nothing here is relative to "now", so a past
   month charts exactly as the live one does. */
function chartBuckets() {
  const key = chartScopeKey();
  const [year, month] = key.split('-').map(Number);
  const today = todayKey();

  if (state.chartRange === 'year') {
    const byMonth = new Map();
    for (const item of expenses) {
      const k = monthKeyOf(item.date);
      if (k) byMonth.set(k, (byMonth.get(k) || 0) + (Number(item.amount) || 0));
    }
    return [...Array(12)].map((_, index) => {
      const date = new Date(year, index, 1);
      return {
        label: date.toLocaleDateString(undefined, { month: 'narrow' }),
        full: date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' }),
        total: byMonth.get(`${year}-${String(index + 1).padStart(2, '0')}`) || 0,
        // the month you are on is highlighted, so the strip doubles as a map
        accent: state.month !== ALL_MONTHS && index === month - 1,
      };
    });
  }

  const byDay = totalsByDay();
  const days = new Date(year, month, 0).getDate();
  const dayKeyFor = day => `${key}-${String(day).padStart(2, '0')}`;
  const dayTotal = day => byDay.get(dayKeyFor(day)) || 0;

  if (state.chartRange === 'weeks') {
    const shortMonth = new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: 'short' });
    const buckets = [];
    for (let start = 1; start <= days; start += 7) {
      const end = Math.min(days, start + 6);
      let total = 0;
      for (let day = start; day <= end; day += 1) total += dayTotal(day);
      buckets.push({
        label: `W${buckets.length + 1}`,
        full: `${start}–${end} ${shortMonth}`,
        total,
        accent: today >= dayKeyFor(start) && today <= dayKeyFor(end),
      });
    }
    return buckets;
  }

  return [...Array(days)].map((_, index) => {
    const day = index + 1;
    return {
      // one label every 5 days: 31 of them overlap into a smudge
      label: day === 1 || day % 5 === 0 ? String(day) : '',
      full: new Date(year, month - 1, day).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }),
      total: dayTotal(day),
      accent: dayKeyFor(day) === today,
    };
  });
}

/** Short rupee label that fits the chart badges. */
function compactINR(value) {
  const amount = Number(value) || 0;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(amount % 100000 === 0 ? 0 : 1)}L`;
  if (amount >= 1000) return `₹${(amount / 1000).toFixed(amount % 1000 === 0 ? 0 : 1)}k`;
  return `₹${Math.round(amount)}`;
}

const CHART = { w: 320, h: 200, padX: 16, padTop: 34, padBottom: 24 };

/* What the drawn chart was drawn from. render() runs on every 15s poll, and
   rebuilding the SVG each time replayed the draw-in animation and threw away
   the point you were inspecting -- the readout snapped back to the peak
   mid-scrub. Redraw only when the numbers actually moved. */
let chartSignature = null;

/* Catmull-Rom control points, so the line curves through every reading rather
   than cornering at it. Control points are clamped to the plot: a low tension
   still overshoots past a spike, and an overshoot below the baseline drew the
   area fill through the axis labels. */
function smoothPath(points, top, bottom) {
  if (!points.length) return '';
  if (points.length === 1) return `M${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`;
  const clamp = y => Math.min(bottom, Math.max(top, y));
  const tension = 0.2;
  let d = `M${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const c1x = p1.x + (p2.x - p0.x) * tension;
    const c1y = clamp(p1.y + (p2.y - p0.y) * tension);
    const c2x = p2.x - (p3.x - p1.x) * tension;
    const c2y = clamp(p2.y - (p3.y - p1.y) * tension);
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
  }
  return d;
}

function renderChart() {
  const wrap = $('#trend');
  const metaEl = $('#chartMeta');
  if (!wrap) return;

  const buckets = chartBuckets();
  const signature = JSON.stringify([
    state.chartRange,
    chartScopeKey(),
    buckets.map(bucket => [bucket.label, bucket.total, Boolean(bucket.accent)]),
  ]);
  if (signature === chartSignature && wrap.firstElementChild) return;
  chartSignature = signature;

  const spent = buckets.reduce((total, bucket) => total + bucket.total, 0);
  if (!buckets.length || spent <= 0) {
    wrap.innerHTML = `<div class="empty">Nothing recorded for ${escapeHtml(chartScopeLabel())}.</div>`;
    if (metaEl) metaEl.textContent = '';
    return;
  }

  const { w, h, padX, padTop, padBottom } = CHART;
  const chartH = h - padTop - padBottom;
  const chartW = w - padX * 2;
  const baseY = h - padBottom;
  const max = Math.max(...buckets.map(bucket => bucket.total));
  const bars = state.chartRange !== 'days';
  const slot = chartW / buckets.length;
  const step = buckets.length > 1 ? chartW / (buckets.length - 1) : 0;

  const points = buckets.map((bucket, index) => ({
    ...bucket,
    index,
    x: bars
      ? padX + slot * (index + 0.5)
      : (buckets.length === 1 ? padX + chartW / 2 : padX + step * index),
    y: baseY - (bucket.total / max) * chartH,
  }));
  const peak = points.reduce((best, point) => (point.total >= best.total ? point : best), points[0]);

  const grid = [0, 0.5, 1]
    .map(t => `<line class="chart-grid" x1="${padX - 4}" y1="${(padTop + chartH * t).toFixed(1)}" x2="${(w - padX + 4).toFixed(1)}" y2="${(padTop + chartH * t).toFixed(1)}"/>`)
    .join('');

  const average = spent / buckets.length;
  const averageY = baseY - (average / max) * chartH;
  const averageLine = `
    <line class="chart-average" x1="${padX - 4}" y1="${averageY.toFixed(1)}" x2="${(w - padX + 4).toFixed(1)}" y2="${averageY.toFixed(1)}"/>
    <text class="chart-average-label" x="${(w - padX + 4).toFixed(1)}" y="${(averageY - 4).toFixed(1)}" text-anchor="end">avg ${compactINR(average)}</text>`;

  let marks;
  if (bars) {
    const barW = Math.max(7, Math.min(26, slot - 8));
    marks = points.map(point => {
      const empty = point.total <= 0;
      const height = empty ? 3 : Math.max(baseY - point.y, 4);
      const y = empty ? baseY - 3 : baseY - height;
      return `<rect class="chart-bar${point.accent ? ' is-accent' : ''}${empty ? ' is-empty' : ''}"
        x="${(point.x - barW / 2).toFixed(1)}" y="${y.toFixed(1)}"
        width="${barW.toFixed(1)}" height="${height.toFixed(1)}"
        rx="${Math.min(barW / 2, 7).toFixed(1)}" style="--i:${point.index}"/>`;
    }).join('');
  } else {
    const line = smoothPath(points, padTop, baseY);
    const area = `${line} L${points.at(-1).x.toFixed(1)},${baseY} L${points[0].x.toFixed(1)},${baseY} Z`;
    const dots = points
      .filter(point => point.total > 0 && (point.accent || point === peak))
      .map(point => `<circle class="chart-dot${point.accent ? ' is-accent' : ''}" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="4"/>`)
      .join('');
    marks = `<path class="chart-area" d="${area}"/>
      <path class="chart-line" d="${line}" pathLength="1"/>
      ${dots}`;
  }

  const axis = points
    .filter(point => point.label)
    .map(point => `<text class="chart-axis${point.accent ? ' is-accent' : ''}" x="${point.x.toFixed(1)}" y="${(h - 5).toFixed(1)}" text-anchor="middle">${escapeHtml(point.label)}</text>`)
    .join('');

  wrap.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Spending for ${escapeHtml(chartScopeLabel())}">
      <defs>
        <linearGradient id="chartArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ffb02e" stop-opacity="0.42"/>
          <stop offset="60%" stop-color="#ffb02e" stop-opacity="0.10"/>
          <stop offset="100%" stop-color="#ffb02e" stop-opacity="0"/>
        </linearGradient>
        <linearGradient id="chartStroke" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#2b3341"/>
          <stop offset="100%" stop-color="#151922"/>
        </linearGradient>
        <linearGradient id="chartBar" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#2b3341"/>
          <stop offset="100%" stop-color="#151922"/>
        </linearGradient>
        <linearGradient id="chartBarAccent" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ffc260"/>
          <stop offset="100%" stop-color="#ffb02e"/>
        </linearGradient>
      </defs>
      ${grid}
      ${averageLine}
      ${marks}
      ${axis}
      <g id="chartCursor" class="chart-cursor"></g>
    </svg>`;

  const svg = wrap.querySelector('svg');

  function cursorMarkup(point) {
    const label = `${point.full} · ${INR.format(point.total)}`;
    const width = Math.max(78, label.length * 5.4 + 20);
    const x = Math.min(Math.max(point.x - width / 2, 2), w - width - 2);
    const top = point.total > 0 ? point.y : baseY;
    const y = Math.max(top - 28, 2);
    return `
      ${bars ? '' : `<line class="chart-cursor-line" x1="${point.x.toFixed(1)}" y1="${(padTop - 6).toFixed(1)}" x2="${point.x.toFixed(1)}" y2="${baseY}"/>
      <circle class="chart-cursor-dot" cx="${point.x.toFixed(1)}" cy="${top.toFixed(1)}" r="5.5"/>
      <circle class="chart-cursor-core" cx="${point.x.toFixed(1)}" cy="${top.toFixed(1)}" r="2.4"/>`}
      <rect class="chart-cursor-chip" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${width.toFixed(1)}" height="22" rx="9"/>
      <text class="chart-tooltip" x="${(x + width / 2).toFixed(1)}" y="${(y + 15).toFixed(1)}" text-anchor="middle">${escapeHtml(label)}</text>`;
  }

  const cursor = svg.querySelector('#chartCursor');
  const showPoint = point => { cursor.innerHTML = cursorMarkup(point); };
  showPoint(peak);   // at rest the chart calls out its own peak

  /* getScreenCTM rather than the bounding box: the SVG is letterboxed inside
     .chart-wrap whenever the card is not exactly 320:200, and a bounding-box
     mapping put the readout on the wrong day near the edges. */
  const localX = event => {
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const origin = svg.createSVGPoint();
    origin.x = event.clientX;
    origin.y = event.clientY;
    return origin.matrixTransform(ctm.inverse()).x;
  };

  const track = event => {
    const x = localX(event);
    if (x == null) return;
    const nearest = points.reduce((best, point) => (Math.abs(point.x - x) < Math.abs(best.x - x) ? point : best), points[0]);
    showPoint(nearest);
  };

  svg.addEventListener('pointerdown', track);
  svg.addEventListener('pointermove', event => {
    // only drag-scrub with a finger; a hovering mouse should track freely
    if (event.pointerType === 'mouse' || event.pressure > 0 || event.buttons) track(event);
  });
  svg.addEventListener('pointerleave', () => showPoint(peak));
  svg.addEventListener('pointercancel', () => showPoint(peak));

  if (metaEl) {
    const per = { days: 'a day', weeks: 'a week', year: 'a month' }[state.chartRange];
    metaEl.innerHTML = `<span><i class="dot-avg"></i>Avg ${escapeHtml(compactINR(average))} ${per}</span>`
      + `<span><i class="dot-peak"></i>Peak ${escapeHtml(compactINR(peak.total))} · ${escapeHtml(peak.full)}</span>`;
  }
}

/** Category totals for the charted window, biggest first. */
function categoryBreakdown() {
  const items = chartScopeExpenses();
  const total = sum(items);
  const map = new Map();
  for (const item of items) {
    const name = (item.category || 'Expense').trim() || 'Expense';
    const entry = map.get(name) || { name, total: 0, count: 0 };
    entry.total += Number(item.amount) || 0;
    entry.count += 1;
    map.set(name, entry);
  }
  return {
    total,
    rows: [...map.values()].sort((a, b) => b.total - a.total),
  };
}

function preferredPayment(items = expenses) {
  const counts = items.reduce((acc, item) => {
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

function daysInMonth(key) {
  const [y, m] = key.split('-').map(Number);
  return new Date(y, m, 0).getDate();
}

function daysInCurrentMonth() {
  return daysInMonth(currentMonthKey());
}

function spendInMonth(key) {
  return sum(monthExpenses(key));
}

function spendInSpan(from, to) {
  return sum(expenses.filter(item => {
    const d = dateOf(item.date);
    return !Number.isNaN(d.getTime()) && d >= from && d <= to;
  }));
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

/** "↑ 12% from last month" style delta line, colored by direction. */
function deltaLine(curr, prev, suffix) {
  if (prev <= 0) {
    // the suffix reads "from August", which needs no "vs" in front of it
    return curr > 0
      ? `<span class="delta up">↑ New ${suffix}</span>`
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
  // The limit is a monthly one, so it is read against the month on screen.
  // "All time" has no month to compare, so it falls back to the live one.
  const key = state.month === ALL_MONTHS ? currentMonthKey() : state.month;
  const live = key === currentMonthKey();
  const days = daysInMonth(key);
  const dayTarget = monthlyLimit / days;
  const weekStart = weekStartKey();
  const weekDayCount = Math.max(1, Math.min(7, Math.floor((now - new Date(weekStart + 'T00:00:00')) / 864e5) + 1));
  const weekTarget = (monthlyLimit / 4.33) * (weekDayCount / 7);

  const spent = { month: spendInMonth(key), today: todaySpend(), week: weekSpend() };

  const alert = live ? budgetAlert(spent.month) : null;
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
  $('#budgetRemainingLabel').textContent = live ? 'Remaining' : `Left in ${monthName(key)}`;
  $('#budgetRemaining').textContent = INR.format(remaining);
  $('#budgetSpentFrac').textContent = `${INR.format(spent.month)} / ${INR.format(monthlyLimit)}`;
  $('#budgetSpentBar').style.width = `${usedPct}%`;
  $('#budgetSpentPct').textContent = `${Math.round(usedPct)}% used`;

  // Today and this week only exist inside the live month; a past one gets the
  // comparison that does make sense there — its daily average against target.
  $('#budgetBars').innerHTML = live
    ? budgetRow('This week', spent.week, weekTarget, 'green')
      + budgetRow('Today', spent.today, dayTarget, 'orange')
      + budgetRow('This month', spent.month, monthlyLimit, 'ink')
    : budgetRow('Daily average', spent.month / days, dayTarget, 'green')
      + budgetRow(monthLabel(key), spent.month, monthlyLimit, 'ink');
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

/* —— The month strip that every tab carries ——————————————————— */

const CHEVRON = dir => `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M${dir < 0 ? '15 6l-6 6 6 6' : '9 6l6 6-6 6'}"/></svg>`;

function renderMonthBars() {
  const bars = $$('[data-month-bar]');
  if (!bars.length) return;
  const key = state.month;
  const isAll = key === ALL_MONTHS;
  const { oldest, newest } = monthNavBounds();
  const items = monthExpenses();
  const html = `
    <button class="month-nav" type="button" data-month-step="-1" ${isAll || key <= oldest ? 'disabled' : ''} aria-label="Previous month">${CHEVRON(-1)}</button>
    <button class="month-current" type="button" data-month-open aria-label="Choose a month">
      <span class="month-name">${escapeHtml(monthLabel(key))}</span>
      <span class="month-amt">${INR.format(sum(items))}</span>
    </button>
    <button class="month-nav" type="button" data-month-step="1" ${isAll || key >= newest ? 'disabled' : ''} aria-label="Next month">${CHEVRON(1)}</button>`;
  bars.forEach(bar => {
    bar.className = `month-bar${isAll ? ' is-all' : ''}`;
    bar.innerHTML = html;
  });
}

function renderMonthList() {
  const list = $('#monthList');
  if (!list) return;
  const option = (key, name, meta, total) => `
    <button class="month-option${state.month === key ? ' is-selected' : ''}" type="button" data-month-pick="${escapeHtml(key)}">
      <span class="month-option-main">
        <b>${escapeHtml(name)}</b>
        <small>${escapeHtml(meta)}</small>
      </span>
      <span class="month-option-total">${INR.format(total)}</span>
    </button>`;
  const months = monthsWithData().map(key => {
    const items = monthExpenses(key);
    return option(key, monthLabel(key), `${items.length} transaction${items.length === 1 ? '' : 's'}`, sum(items));
  }).join('');
  list.innerHTML = months
    + option(ALL_MONTHS, 'All time', `${expenses.length} transaction${expenses.length === 1 ? '' : 's'}`, sum(expenses));
}

function openMonthModal() {
  renderMonthList();
  $('#monthModal').hidden = false;
}

function closeMonthModal() {
  $('#monthModal').hidden = true;
}

/* —— Transactions: the total for whatever is on screen ———————— */

function renderTxSummary(items) {
  const el = $('#txSummary');
  if (!el) return;
  const { total, count, average, largest, byCategory } = summarise(items);
  const query = state.q.trim();
  const scope = state.month === ALL_MONTHS ? 'all time' : monthLabel(state.month);
  const windowLabel = { today: 'today', 7: 'last 7 days', 30: 'last 30 days' }[state.preset];
  const where = windowLabel && presetAllowed(state.preset) ? `${scope} · ${windowLabel}` : scope;

  if (!count) {
    el.innerHTML = `<p class="tx-summary-head"><span>${query ? `No match for “${escapeHtml(query)}”` : 'Nothing here yet'}</span></p>
      <strong>${INR.format(0)}</strong>
      <p class="tx-summary-scope">${escapeHtml(where)}</p>`;
    el.classList.toggle('is-search', Boolean(query));
    return;
  }

  // A search is the case this card exists for: "food" should answer with one
  // number, then show which categories made it up.
  const chips = byCategory.slice(0, 4).map(([name, amount]) => `
    <span class="tx-summary-cat"><i>${icons[name.toLowerCase()] || '🏷️'}</i>${escapeHtml(name)}<b>${INR.format(amount)}</b></span>`).join('');

  el.innerHTML = `
    <p class="tx-summary-head">
      <span>${query ? `Total for “${escapeHtml(query)}”` : 'Total'}</span>
      <em>${escapeHtml(where)}</em>
    </p>
    <strong>${INR.format(total)}</strong>
    <div class="tx-summary-grid">
      <div><small>Transactions</small><b>${count}</b></div>
      <div><small>Average</small><b>${INR.format(average)}</b></div>
      <div><small>Largest</small><b>${INR.format(largest)}</b></div>
    </div>
    ${byCategory.length > 1 ? `<div class="tx-summary-cats">${chips}</div>` : ''}`;
  el.classList.toggle('is-search', Boolean(query));
}

function render() {
  const items = filtered();
  const monthItems = monthExpenses();
  const monthTotal = sum(monthItems);
  const isAll = state.month === ALL_MONTHS;
  const isCurrentMonth = state.month === currentMonthKey();
  // "Today" is always calendar-today spend, never filter-dependent.
  const today = sum(expenses.filter(item => dayKey(item.date) === todayKey()));
  const allTotal = sum(expenses);
  const label = monthLabel(state.month);
  const name = monthName(state.month);

  $('#greeting').textContent = greetingForNow();
  $('#heroLabel').textContent = isAll ? 'TOTAL SPENT' : `SPENT IN ${label.toUpperCase()}`;
  $('#total').textContent = INR.format(monthTotal);
  $('#total-sub').textContent = `${monthItems.length} transaction${monthItems.length === 1 ? '' : 's'}`
    + (isAll ? ' · all time' : '');
  $('#heroDate').textContent = isAll ? 'All time' : monthLabel(state.month, { short: true });

  // The second card compares like with like: today against yesterday while
  // you are on the live month, month against the month before it otherwise.
  const previousKey = isAll ? '' : shiftMonthKey(state.month, -1);
  const previousTotal = previousKey ? spendInMonth(previousKey) : 0;
  const days = isAll ? 0 : daysInMonth(state.month);
  const stats = isAll
    ? [
        ['↗', 'All time', allTotal, ''],
        ['↘', 'Monthly average', monthsWithData().length ? allTotal / monthsWithData().length : 0, ''],
      ]
    : isCurrentMonth
      ? [
          ['↗', 'Today', today, deltaLine(today, yesterdaySpend(), 'from yesterday')],
          ['↘', 'This month', monthTotal, deltaLine(monthTotal, previousTotal, `from ${monthName(previousKey)}`)],
        ]
      : [
          ['↗', `${name} total`, monthTotal, deltaLine(monthTotal, previousTotal, `from ${monthName(previousKey)}`)],
          ['↘', 'Daily average', days ? monthTotal / days : 0, ''],
        ];
  $('#stats').innerHTML = stats.map(([icon, caption, value, delta]) => `
    <div class="stat"><span class="stat-icon">${icon}</span><div><small>${escapeHtml(caption)}</small><strong>${INR.format(value)}</strong>${delta}</div></div>`).join('');

  $('#recentPreview').innerHTML = items.length
    ? items.slice(0, 3).map(item => row(item, true)).join('')
    : `<div class="empty">Nothing in ${escapeHtml(label)} yet. Tap + to add one.</div>`;

  $('#transactionsSub').textContent = isAll ? 'Everything, grouped by date' : `${label} · grouped by date`;
  renderTxSummary(items);

  const groups = groupByDate(items);
  $('#list').innerHTML = groups.length
    ? groups.map(([key, groupItems]) => `
        <div class="date-group">
          <div class="date-label">${escapeHtml(formatDayLabel(key))} · ${INR.format(sum(groupItems))}</div>
          ${groupItems.map(item => row(item)).join('')}
        </div>`).join('')
    : `<div class="empty">No expenses match these filters in ${escapeHtml(label)}.</div>`;

  const breakdown = categoryBreakdown();
  $('#analyticsLabel').textContent = `SPENDING · ${chartScopeLabel().toUpperCase()}`;
  $('#analyticsTotal').textContent = INR.format(breakdown.total);
  $('#analyticsDate').textContent = 'Tap or drag the chart to read a value';
  $('#analyticsBreakdownTitle').textContent = `Where it went · ${chartScopeLabel()}`;
  $('#analyticsStats').innerHTML = breakdown.rows.length
    ? breakdown.rows.slice(0, 6).map(entry => {
        const share = breakdown.total > 0 ? (entry.total / breakdown.total) * 100 : 0;
        return `
      <div class="top-item">
        <span>${icons[entry.name.toLowerCase()] || '🏷️'}</span>
        <div>
          <strong>${escapeHtml(entry.name)}</strong>
          <small>${entry.count} transaction${entry.count === 1 ? '' : 's'} · ${Math.round(share)}%</small>
          <div class="share-track"><i style="width:${share.toFixed(1)}%"></i></div>
        </div>
        <b>${INR.format(entry.total)}</b>
      </div>`;
      }).join('')
    : `<div class="empty">Nothing recorded for ${escapeHtml(chartScopeLabel())}.</div>`;

  $('#profileTotalLabel').textContent = isAll ? 'Total expenses' : `Spent in ${name}`;
  $('#profileCountLabel').textContent = isAll ? 'Transactions recorded' : `Transactions in ${name}`;
  $('#profileTotal').textContent = INR.format(monthTotal);
  $('#profileCount').textContent = String(monthItems.length);
  $('#profilePayment').textContent = preferredPayment(monthItems);
  $('#profileAllTime').textContent = INR.format(allTotal);
  $('#addDateLabel').textContent = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
  $('#addMonthLabel').textContent = `Spent in ${monthName(currentMonthKey())}`;
  $('#addMonthSpend').textContent = INR.format(spendInMonth(currentMonthKey()));

  renderMonthBars();
  if (!$('#monthModal').hidden) renderMonthList();
  syncPresetOptions();
  updateProfileIdentity();
  syncProfileKeyUi();
  syncAuthUi();

  renderChart();
  updateAddPreview();
  renderBudget();
  renderRecurring();
}

/* The preset narrows the selected month, so "Today" and the rolling windows
   are only offered while today is actually inside it. */
function syncPresetOptions() {
  const select = $('#preset');
  if (!select) return;
  const allowed = presetAllowed('today');
  [...select.options].forEach(option => {
    if (option.value !== 'month') option.disabled = !allowed;
  });
  select.options[0].textContent = state.month === ALL_MONTHS ? 'All time' : 'Whole month';
  select.value = state.preset;
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
  const reloadBtn = $('#reloadBtn');
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
    reloadBtn?.classList.add('is-loading');
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
  // It was logged today, so jump to the month that actually contains it
  // rather than leaving the user on a past month it will never appear in.
  if (state.month !== ALL_MONTHS) state.month = currentMonthKey();
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

document.addEventListener('click', event => {
  const step = event.target.closest('[data-month-step]');
  if (step && !step.disabled) {
    setMonth(shiftMonthKey(state.month, Number(step.dataset.monthStep)));
    return;
  }
  if (event.target.closest('[data-month-open]')) {
    openMonthModal();
    return;
  }
  const pick = event.target.closest('[data-month-pick]');
  if (pick) {
    closeMonthModal();
    setMonth(pick.dataset.monthPick);
  }
});

$('#closeMonth').onclick = closeMonthModal;
$('[data-close-month]').onclick = closeMonthModal;

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
  state.preset = 'month';
  state.payment = 'all';
  state.q = '';
  state.sort = 'newest';
  state.month = currentMonthKey();
  $('#preset').value = 'month';
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

render();
syncProfileKeyUi();
if (!KEY) showTab('profile');
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

"""Read-only HTML dashboard of the expenses. Server-rendered shell + client-side
filtering. No key in client code beyond the ?key= the user bookmarked."""
import html
import json
from secrets import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pymongo.asynchronous.collection import AsyncCollection

from ..config import settings
from ..database import get_collection
from .expenses import _to_json

router = APIRouter(tags=["view"])

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Expenses</title>
<link rel="apple-touch-icon" href="/icon-180.png">
<link rel="apple-touch-icon" sizes="167x167" href="/icon-167.png">
<link rel="apple-touch-icon" sizes="152x152" href="/icon-152.png">
<link rel="icon" type="image/png" href="/favicon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Expenses">
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f5f5f7">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#000000">
<style>
  :root { color-scheme: light dark; --bg:#f5f5f7; --card:#fff; --fg:#1c1c1e;
           --muted:#8a8a8e; --line:#e5e5ea; --accent:#0a84ff; --danger:#ff3b30;
           --chip:#e9e9ee; --chip-on:#0a84ff; --chip-on-fg:#fff; --ok:#34c759; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#000; --card:#1c1c1e; --fg:#f5f5f7; --muted:#98989d; --line:#2c2c2e;
            --chip:#2c2c2e; } }
  * { box-sizing:border-box; }
  body { margin:0; padding:0 16px 48px; background:var(--bg); color:var(--fg);
         font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif; }
  main { max-width:640px; margin:0 auto; }
  header.bar { position:sticky; top:0; z-index:10; background:var(--bg);
               display:flex; align-items:center; gap:10px;
               padding:14px 0 10px; border-bottom:1px solid var(--line); margin-bottom:16px; }
  h1 { font-size:26px; margin:0; letter-spacing:-.02em; flex:1; }
  .sub { font-size:12px; color:var(--muted); margin-top:-4px; }
  button, select, input { font:inherit; color:inherit; }
  .btn { border:1px solid var(--line); background:var(--card); border-radius:10px;
         padding:7px 12px; cursor:pointer; }
  .btn:active { transform:scale(.97); }
  .btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  .spin { animation:rot .8s linear infinite; display:inline-block; }
  @keyframes rot { to { transform:rotate(360deg); } }
  .search { width:100%; padding:11px 14px; border-radius:12px; border:1px solid var(--line);
            background:var(--card); margin-bottom:12px; outline:none; }
  .search:focus { border-color:var(--accent); }
  .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }
  .row select, .row input[type=date] { background:var(--card); border:1px solid var(--line);
            border-radius:10px; padding:7px 10px; }
  .chips { display:flex; gap:8px; overflow-x:auto; padding:2px 0 10px; scrollbar-width:none; }
  .chips::-webkit-scrollbar { display:none; }
  .chip { flex:0 0 auto; border:0; background:var(--chip); border-radius:999px;
          padding:6px 13px; cursor:pointer; font-size:14px; white-space:nowrap; }
  .chip[aria-pressed="true"] { background:var(--chip-on); color:var(--chip-on-fg); }
  .stats { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:14px; }
  .stat { background:var(--card); border-radius:12px; padding:10px 12px; }
  .stat b { display:block; font-size:17px; letter-spacing:-.01em;
            font-variant-numeric:tabular-nums; }
  .stat span { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  .hero { background:var(--card); border-radius:14px; padding:16px 18px; margin-bottom:14px; }
  .hero b { display:block; font-size:32px; letter-spacing:-.02em; line-height:1.15; }
  .hero span { color:var(--muted); font-size:13px; }
  .breakdown { background:var(--card); border-radius:14px; padding:12px 16px 14px; margin-bottom:14px; }
  .bd-row { display:grid; grid-template-columns:110px 1fr auto; gap:10px; align-items:center;
            margin:7px 0; font-size:13px; }
  .bar { height:7px; border-radius:99px; background:var(--accent); min-width:2px; }
  .track { background:var(--line); border-radius:99px; height:7px; overflow:hidden; }
  h2.day { font-size:13px; color:var(--muted); font-weight:600; text-transform:uppercase;
           letter-spacing:.05em; margin:20px 2px 8px; display:flex; justify-content:space-between; }
  ul { list-style:none; margin:0; padding:0; background:var(--card); border-radius:14px; }
  li { padding:13px 16px; border-bottom:1px solid var(--line); display:flex; gap:12px;
       align-items:flex-start; }
  li:last-child { border-bottom:0; }
  .left { flex:1; min-width:0; }
  .cat { font-weight:600; }
  .desc { color:var(--muted); font-size:14px; overflow-wrap:anywhere; }
  .amt { font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .meta { color:var(--muted); font-size:12px; margin-top:2px; }
  .tag { display:inline-block; background:var(--bg); border-radius:6px;
         padding:1px 6px; margin-left:6px; }
  .del { border:0; background:none; color:var(--muted); cursor:pointer; font-size:15px;
         padding:4px 6px; border-radius:8px; }
  .del:hover { color:var(--danger); }
  .empty { padding:44px 20px; text-align:center; color:var(--muted);
           background:var(--card); border-radius:14px; }
  .foot { text-align:center; color:var(--muted); font-size:12px; margin-top:24px; }
  label.auto { font-size:13px; color:var(--muted); display:flex; align-items:center; gap:5px; }
</style></head><body><main>
<header class="bar">
  <div style="flex:1">
    <h1>Expenses</h1>
    <div class="sub" id="updated"></div>
  </div>
  <button class="btn primary" id="refresh" title="Refresh (r)">&#8635;</button>
  <button class="btn" id="csv" title="Export filtered CSV">&#8681;</button>
</header>

<input class="search" id="q" type="search" placeholder="Search description, notes, category&#8230;" autocomplete="off">

<div class="row">
  <select id="preset" title="Date range">
    <option value="all">All time</option>
    <option value="today">Today</option>
    <option value="yesterday">Yesterday</option>
    <option value="7">Last 7 days</option>
    <option value="30">Last 30 days</option>
    <option value="month">This month</option>
    <option value="custom">Custom range&#8230;</option>
  </select>
  <input type="date" id="from" hidden aria-label="From date">
  <input type="date" id="to" hidden aria-label="To date">
  <select id="sort" title="Sort order">
    <option value="newest">Newest first</option>
    <option value="oldest">Oldest first</option>
    <option value="high">Amount: high &#8594; low</option>
    <option value="low">Amount: low &#8594; high</option>
  </select>
  <label class="auto"><input type="checkbox" id="autor"> auto 60s</label>
  <button class="btn" id="clear" hidden>Reset</button>
</div>

<div class="chips" id="cats"></div>
<div class="chips" id="pays"></div>

<div class="hero"><b id="total"></b><span id="totalSub"></span></div>
<div class="stats" id="stats"></div>
<div class="breakdown" id="breakdown"></div>

<div id="list"></div>
<div class="foot">&#8984;R / tap &#8635; to refresh &middot; press / to search</div>
</main>
<script id="bootstrap" type="application/json">__BOOTSTRAP__</script>
<script>
'use strict';
const $ = s => document.querySelector(s);
const KEY = new URLSearchParams(location.search).get('key') || '';
const INR = new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'});
const EMOJI = {food:'\u{1F35C}', groceries:'\u{1F6D2}', grocery:'\u{1F6D2}', travel:'\u2708',
  cab:'\u{1F695}', fuel:'\u26FD', bills:'\u{1F9FE}', rent:'\u{1F3E0}', health:'\u{1F48A}',
  fitness:'\u{1F3CB}\uFE0F', entertainment:'\u{1F3AC}', shopping:'\u{1F6CD}\uFE0F',
  coffee:'\u2615', education:'\u{1F4DA}', gifts:'\u{1F381}'};
const emo = c => EMOJI[(c||'').trim().toLowerCase()] || '\u{1F3F7}\uFE0F';

let docs = JSON.parse($('#bootstrap').textContent);
const state = {q:'', cats:new Set(), pays:new Set(), preset:'all',
               from:null, to:null, sort:'newest'};
let lastFetch = new Date();

/* ---------- helpers ---------- */
const dayKey = d => { const x=new Date(d);
  return x.getFullYear()+'-'+String(x.getMonth()+1).padStart(2,'0')+'-'+String(x.getDate()).padStart(2,'0'); };
const startOfDay = d => { const x=new Date(d); x.setHours(0,0,0,0); return x; };
function rangeFor(preset){
  const now = new Date();
  if (preset==='today')   return [startOfDay(now), null];
  if (preset==='yesterday'){const y=startOfDay(now)-864e5; return [new Date(y), new Date(y+86399e3)];}
  if (preset==='7')       return [startOfDay(now)-6*864e5, null];
  if (preset==='30')      return [startOfDay(now)-29*864e5, null];
  if (preset==='month')   {const m=new Date(now.getFullYear(),now.getMonth(),1); return [m,null];}
  if (preset==='custom')  return [state.from?startOfDay(state.from):null,
                                  state.to?(startOfDay(state.to).getTime()+86399e3):null];
  return [null,null];
}
function filtered(){
  const [lo,hi] = rangeFor(state.preset);
  const q = state.q.trim().toLowerCase();
  let arr = docs.filter(d=>{
    const t = d.date ? new Date(d.date).getTime() : 0;
    if (lo && t < lo.getTime()) return false;
    if (hi && t > hi.getTime()) return false;
    if (state.cats.size && !state.cats.has(d.category)) return false;
    if (state.pays.size && !(state.pays.has(d.payment_method||'Cash'))) return false;
    if (q){
      const hay = ((d.category||'')+' '+(d.description||'')+' '+(d.notes||'')+' '
                  +(d.payment_method||'')).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const cmp = {newest:(a,b)=>new Date(b.date)-new Date(a.date),
               oldest:(a,b)=>new Date(a.date)-new Date(b.date),
               high:(a,b)=>b.amount-a.amount, low:(a,b)=>a.amount-b.amount}[state.sort];
  return arr.sort(cmp);
}

/* ---------- render ---------- */
function render(){
  const arr = filtered();
  /* chips */
  chips('#cats', [...new Set(docs.map(d=>d.category))].sort(), state.cats, 'category');
  chips('#pays', [...new Set(docs.map(d=>d.payment_method||'Cash'))].sort(), state.pays, 'payment');
  /* hero */
  const total = arr.reduce((s,d)=>s+d.amount,0);
  $('#total').textContent = INR.format(total);
  const n = arr.length;
  $('#totalSub').textContent = n + ' expense' + (n===1?'':'s')
    + (n!==docs.length ? ' of ' + docs.length : '');
  /* stat cards */
  const now = new Date(), todayK = dayKey(now);
  const today = sum(docs.filter(d=>dayKey(d.date)===todayK));
  const wk = sum(docs.filter(d=>new Date(d.date)>=startOfDay(now)-6*864e5));
  const mo = sum(docs.filter(d=>{const x=new Date(d.date);
      return x.getMonth()===now.getMonth() && x.getFullYear()===now.getFullYear();}));
  const days = new Set(arr.map(d=>dayKey(d.date))).size || 1;
  const topCat = Object.entries(cnt(arr,d=>d.category)).sort((a,b)=>b[1]-a[1])[0];
  const biggest = arr.length ? Math.max(...arr.map(d=>d.amount)) : 0;
  stat([['Today', INR.format(today)], ['Last 7 days', INR.format(wk)],
        ['This month', INR.format(mo)], ['Avg / day', INR.format(total/days)],
        ['Top category', topCat ? topCat[0]+'\u00A0'+emo(topCat[0]) : '\u2013'],
        ['Largest', INR.format(biggest)]]);
  /* breakdown */
  const byCat = Object.entries(cnt(arr,d=>d.category)).sort((a,b)=>b[1]-a[1]).slice(0,5);
  $('#breakdown').innerHTML = total>0 && byCat.length ?
    '<div class="sub" style="margin-bottom:2px">Where it went</div>' + byCat.map(([c,v])=>{
      const p = Math.max(2, Math.round(v/total*100));
      return '<div class="bd-row"><span>'+emo(c)+' '+esc(c)+'</span>'
        +'<span class="track"><span class="bar" style="width:'+p+'%;display:block"></span></span>'
        +'<b>'+INR.format(v)+'</b></div>';}).join('')
    : '';
  /* list grouped by day */
  const groups = new Map();
  for (const d of arr){
    const k = dayKey(d.date);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(d);
  }
  let out = '';
  for (const [k, items] of groups){
    const sub = sum(items);
    out += '<h2 class="day"><span>'+dayLabel(k)+'</span><span>'+INR.format(sub)+'</span></h2>';
    out += '<ul>' + items.map(row).join('') + '</ul>';
  }
  if (!arr.length)
    out = docs.length
      ? '<div class="empty">No expenses match these filters.<br><br>'
        +'<button class="btn" onclick="clearAll()">Show everything</button></div>'
      : '<div class="empty">No expenses yet.<br>Add your first one from the iPhone Shortcut.</div>';
  $('#list').innerHTML = out;
  const active = state.q || state.cats.size || state.pays.size || state.preset!=='all';
  $('#clear').hidden = !active;
}
function sum(a){ return a.reduce((s,d)=>s+d.amount,0); }
function cnt(a,f){ return a.reduce((m,d)=>{const k=f(d)||'\u2013'; m[k]=(m[k]||0)+d.amount; return m;},{}); }
function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }
const ea = s => String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;')
                         .replace(/</g,'&lt;').replace(/>/g,'&gt;');
function stat(pairs){
  $('#stats').innerHTML = pairs.map(([l,v])=>
    '<div class="stat"><span>'+l+'</span><b>'+v+'</b></div>').join('');
}
function chips(sel, values, set, kind){
  $(sel).innerHTML = values.map(v=>
    '<button class="chip" aria-pressed="'+set.has(v)+'" data-kind="'+kind
    +'" data-v="'+ea(v)+'">'+(kind==='category'?emo(v)+' ':'')+esc(v)+'</button>').join('');
}
function dayLabel(k){
  const [y,m,d] = k.split('-').map(Number);
  const dt = new Date(y, m-1, d), now = new Date();
  if (k === dayKey(now)) return 'Today';
  if (k === dayKey(new Date(now-864e5))) return 'Yesterday';
  return dt.toLocaleDateString(undefined, {weekday:'short', day:'numeric', month:'short', year:'numeric'});
}
function row(d){
  const t = d.date ? new Date(d.date).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '';
  const bits = [t];
  if (d.payment_method) bits.push('<span class="tag">'+esc(d.payment_method)+'</span>');
  if (d.notes) bits.push('<span class="tag">'+esc(d.notes)+'</span>');
  const desc = d.description ? '<div class="desc">'+esc(d.description)+'</div>' : '';
  return '<li><div class="left"><div class="cat">'+emo(d.category)+' '+esc(d.category)+'</div>'+desc
    +'<div class="meta">'+bits.join(' ')+'</div></div>'
    +'<div class="amt">'+INR.format(d.amount)+'</div>'
    +'<button class="del" title="Delete" onclick="del(\''+d.id+'\')">\u2715</button></li>';
}

/* ---------- actions ---------- */
document.addEventListener('click', e=>{
  const c = e.target.closest('.chip');
  if (c){
    const set = c.dataset.kind==='category' ? state.cats : state.pays;
    set.has(c.dataset.v) ? set.delete(c.dataset.v) : set.add(c.dataset.v);
    render();
  }
});
window.tog = null;
window.clearAll = ()=>{
  Object.assign(state, {q:'', cats:new Set(), pays:new Set(), preset:'all',
                        from:null, to:null, sort:'newest'});
  $('#q').value=''; $('#from').value=''; $('#to').value='';
  $('#from').hidden = $('#to').hidden = true;
  $('#preset').value='all'; $('#sort').value='newest';
  render();
};
async function refresh(manual=true){
  const b = $('#refresh');
  b.classList.add('spin');
  try{
    const r = await fetch('/api/expenses?key='+encodeURIComponent(KEY)+'&limit=1000',
                          {cache:'no-store'});
    if (r.status === 401) { location.href='/'; return; }
    const j = await r.json();
    docs = j.expenses || [];
    lastFetch = new Date();
    stamp(); render();
  }catch(e){ stamp('offline \u2014 showing saved data'); }
  finally{ b.classList.remove('spin'); if(manual) b.blur(); }
}
window.del = async id=>{
  if (!confirm('Delete this expense?')) return;
  const r = await fetch('/api/expenses/'+id+'?key='+encodeURIComponent(KEY), {method:'DELETE'});
  if (r.ok){ docs = docs.filter(d=>d.id!==id); render(); }
  else alert('Could not delete ('+r.status+')');
};
$('#csv').onclick = ()=>{
  const rows = [['date','amount','category','description','payment_method','notes']]
    .concat(filtered().map(d=>[
      d.date?new Date(d.date).toLocaleString():'', d.amount, d.category,
      d.description||'', d.payment_method||'', d.notes||'']));
  const csv = rows.map(r=>r.map(c=>'"'+String(c).replace(/"/g,'""')+'"').join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {type:'text/csv'}));
  a.download = 'expenses.csv'; a.click(); URL.revokeObjectURL(a.href);
};
$('#refresh').onclick = ()=>refresh();
$('#q').oninput = e=>{ state.q=e.target.value; clearTimeout(window._t);
                       window._t=setTimeout(render,150); };
$('#preset').onchange = e=>{
  state.preset = e.target.value;
  $('#from').hidden = $('#to').hidden = state.preset!=='custom';
  render();
};
$('#from').onchange = e=>{ state.from=e.target.valueAsDate?new Date(e.target.value):null; render(); };
$('#to').onchange   = e=>{ state.to  =e.target.valueAsDate?new Date(e.target.value):null; render(); };
$('#sort').onchange = e=>{ state.sort=e.target.value; render(); };
$('#clear').onclick = clearAll;
document.onkeydown = e=>{
  if (e.key==='/' && document.activeElement!==$('#q')){ e.preventDefault(); $('#q').focus(); }
  if (e.key==='r' && !e.metaKey && !e.ctrlKey
      && document.activeElement!==$('#q') && !/input|select|textarea/i.test(document.activeElement.tagName))
    refresh(false);
};
/* auto-refresh + relative timestamp */
$('#autor').checked = localStorage.getItem('autor')==='1';
setInterval(()=>{ if($('#autor').checked) refresh(false); }, 60000);
$('#autor').onchange = e=>localStorage.setItem('autor', e.target.checked?'1':'0');
setInterval(stamp, 30000);
function stamp(note){
  const s = Math.round((Date.now()-lastFetch.getTime())/1000);
  $('#updated').textContent = note || ('updated '
    + (s<8 ? 'just now' : s<90 ? Math.round(s/10)*10+'s ago'
    : s<3600 ? Math.round(s/60)+'m ago' : Math.round(s/3600)+'h ago'));
}
stamp(); render();
</script></body></html>"""


@router.get("/", response_class=HTMLResponse, summary="View expenses")
async def view_expenses(
    # ponytail: key in the URL (lands in browser history/logs). Swap for a
    # signed session cookie or HTTP Basic if this becomes more than your phone.
    key: str = Query(default="", description="Your SHORTCUT_API_KEY"),
    collection: AsyncCollection = Depends(get_collection),
) -> HTMLResponse:
    if not compare_digest(key, settings.shortcut_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing key")
    docs = await collection.find().sort("date", -1).to_list(500)
    bootstrap = json.dumps(
        [_to_json(d) for d in docs], ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")  # can't break out of the <script> block
    return HTMLResponse(
        PAGE.replace("__BOOTSTRAP__", bootstrap),
        # without this Safari serves the cached page on the reload
        headers={"Cache-Control": "no-store"},
    )

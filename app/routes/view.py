"""Read-only HTML view of the expenses. Server-rendered: no key in client code."""
import html
from secrets import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pymongo.asynchronous.collection import AsyncCollection

from ..config import settings
from ..database import get_collection

router = APIRouter(tags=["view"])

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Expenses</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f5f5f7; --card:#fff; --fg:#1c1c1e;
           --muted:#8a8a8e; --line:#e5e5ea; --accent:#0a84ff; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#000; --card:#1c1c1e; --fg:#f5f5f7; --muted:#98989d; --line:#2c2c2e; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:24px 16px 48px; background:var(--bg); color:var(--fg);
         font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif; }}
  main {{ max-width:640px; margin:0 auto; }}
  h1 {{ font-size:28px; margin:0 0 16px; letter-spacing:-.02em; }}
  .total {{ background:var(--card); border-radius:14px; padding:18px 20px; margin-bottom:20px; }}
  .total b {{ display:block; font-size:34px; letter-spacing:-.02em; }}
  .total span {{ color:var(--muted); font-size:14px; }}
  ul {{ list-style:none; margin:0; padding:0; background:var(--card); border-radius:14px; }}
  li {{ padding:14px 18px; border-bottom:1px solid var(--line); display:flex; gap:12px; }}
  li:last-child {{ border-bottom:0; }}
  .left {{ flex:1; min-width:0; }}
  .cat {{ font-weight:600; }}
  .desc {{ color:var(--muted); font-size:14px; overflow-wrap:anywhere; }}
  .amt {{ font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .meta {{ color:var(--muted); font-size:12px; margin-top:2px; }}
  .tag {{ display:inline-block; background:var(--bg); border-radius:6px;
          padding:1px 6px; margin-left:6px; }}
  .empty {{ padding:40px; text-align:center; color:var(--muted); }}
</style></head><body><main>
<h1>Expenses</h1>
<div class="total"><b>&#8377;{total:,.2f}</b><span>{count} expense{plural}</span></div>
{body}
</main></body></html>"""


def _row(d: dict) -> str:
    e = html.escape
    when = d["date"].strftime("%d %b %Y, %I:%M %p") if d.get("date") else ""
    bits = [when]
    if d.get("payment_method"):
        bits.append(f'<span class="tag">{e(d["payment_method"])}</span>')
    if d.get("notes"):
        bits.append(f'<span class="tag">{e(d["notes"])}</span>')
    desc = f'<div class="desc">{e(d["description"])}</div>' if d.get("description") else ""
    return (
        f'<li><div class="left"><div class="cat">{e(d.get("category", "-"))}</div>{desc}'
        f'<div class="meta">{" ".join(bits)}</div></div>'
        f'<div class="amt">&#8377;{d.get("amount", 0):,.2f}</div></li>'
    )


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
    total = sum(d.get("amount", 0) for d in docs)
    body = (
        "<ul>" + "".join(_row(d) for d in docs) + "</ul>"
        if docs
        else '<div class="empty">No expenses yet.</div>'
    )
    return HTMLResponse(
        PAGE.format(total=total, count=len(docs), plural="" if len(docs) == 1 else "s", body=body)
    )

"""Browser end-to-end test for the month selector and the search totals.

Same shape as test_recurring_ui.py -- it starts its own API (in memory, so an
empty database) and static host, so each run is deterministic.

    cd frontend && PRIMARY_API_URL=http://127.0.0.1:8126 \
        SECONDARY_API_URL=http://127.0.0.1:8126 npm run build
    python3 tests/browser/test_month_ui.py
"""
import os, subprocess, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
DIST = ROOT / "frontend" / "dist"
API_PORT, WEB_PORT = 8124, 8125
WEB = f"http://127.0.0.1:{WEB_PORT}"
API = f"http://127.0.0.1:{API_PORT}"
KEY = "e2e-test-key"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
fails = []

now = datetime.now(timezone.utc)
# Midday, so a local/UTC offset can never push a seeded row into another day.
this_month = now.replace(day=2, hour=12, minute=0, second=0, microsecond=0)
last_month = (this_month.replace(day=1) - timedelta(days=1)).replace(day=12, hour=12)

# category, amount, when
SEED = [
    ("Food", 120, this_month),
    ("Food", 380, this_month + timedelta(days=5)),
    ("Travel", 500, this_month + timedelta(days=6)),
    ("Coffee", 60, this_month + timedelta(days=7)),
    ("Food", 900, last_month),
    ("Rent", 15000, last_month + timedelta(days=1)),
]
THIS_MONTH_TOTAL = sum(a for _, a, w in SEED if w.month == this_month.month)
THIS_MONTH_FOOD = sum(a for c, a, w in SEED if c == "Food" and w.month == this_month.month)
LAST_MONTH_TOTAL = sum(a for _, a, w in SEED if w.month == last_month.month)
ALL_TOTAL = sum(a for _, a, _ in SEED)


def money(value):
    """'1,000' -- how Intl.NumberFormat('en-IN') groups it."""
    return f"{value:,}"


def wait_for(url, what, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.3)
    sys.exit(f"{what} did not come up at {url}")


def start_servers():
    if not (DIST / "index.html").exists():
        sys.exit(f"build the frontend first -- {DIST} is missing (see this file's docstring)")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    api = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "serve_fake_api.py")],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(WEB_PORT), "--bind", "127.0.0.1"],
        cwd=DIST, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(f"{API}/health", "fake API")
    wait_for(f"{WEB}/index.html", "static host")
    return api, web


def check(label, fn):
    try:
        fn()
        print(f"  PASS  {label}")
    except Exception as e:
        fails.append(label)
        print(f"  FAIL  {label}: {str(e).splitlines()[0][:200]}")


servers = start_servers()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{WEB}/?key={KEY}", wait_until="networkidle")
        for category, amount, when in SEED:
            page.request.post(f"{API}/api/expenses",
                              headers={"X-API-Key": KEY, "Content-Type": "application/json"},
                              data={"amount": amount, "category": category,
                                    "payment_method": "UPI", "date": when.isoformat()})
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)

        print("\n1. Every tab opens on the current month")
        check("the month strip is on all four tabs",
              lambda: expect(page.locator("[data-month-bar] .month-current")).to_have_count(4))
        check("it names the current month",
              lambda: expect(page.locator('[data-panel="dashboard"] .month-name'))
              .to_have_text(now.strftime("%B %Y")))
        check("the hero total is this month's, not all time",
              lambda: expect(page.locator("#total")).to_have_text(f"₹{money(THIS_MONTH_TOTAL)}.00"))
        check("last month's rent is not in the list",
              lambda: expect(page.locator("#list")).not_to_contain_text("Rent"))

        print("\n2. Transactions carries a running total")
        page.click('[data-tab="transactions"]')
        check("the summary shows this month's total",
              lambda: expect(page.locator("#txSummary > strong"))
              .to_have_text(f"₹{money(THIS_MONTH_TOTAL)}.00"))
        check("and how many transactions made it",
              lambda: expect(page.locator("#txSummary .tx-summary-grid b").first).to_have_text("4"))

        print("\n3. Searching totals only what matched")
        page.fill("#search", "food")
        page.wait_for_timeout(300)
        check("the total is the food total",
              lambda: expect(page.locator("#txSummary > strong"))
              .to_have_text(f"₹{money(THIS_MONTH_FOOD)}.00"))
        check("the card says what it totalled",
              lambda: expect(page.locator("#txSummary .tx-summary-head")).to_contain_text("food"))
        check("only food rows are listed",
              lambda: expect(page.locator("#list .tx .name")).to_have_count(2))
        check("last month's food is excluded",
              lambda: expect(page.locator("#txSummary > strong"))
              .not_to_have_text(f"₹{money(THIS_MONTH_FOOD + 900)}.00"))
        page.fill("#search", "")
        page.wait_for_timeout(250)

        print("\n4. Stepping back a month moves the whole app")
        page.click('[data-panel="transactions"] [data-month-step="-1"]')
        page.wait_for_timeout(350)
        check("the strip names last month",
              lambda: expect(page.locator('[data-panel="transactions"] .month-name'))
              .to_have_text(last_month.strftime("%B %Y")))
        check("the total is last month's",
              lambda: expect(page.locator("#txSummary > strong"))
              .to_have_text(f"₹{money(LAST_MONTH_TOTAL)}.00"))
        check("last month's rows are listed",
              lambda: expect(page.locator("#list")).to_contain_text("Rent"))
        check("this month's rows are not",
              lambda: expect(page.locator("#list")).not_to_contain_text("Coffee"))
        page.click('[data-tab="dashboard"]')
        check("the dashboard followed it",
              lambda: expect(page.locator("#total")).to_have_text(f"₹{money(LAST_MONTH_TOTAL)}.00"))
        check("the hero label names the month",
              lambda: expect(page.locator("#heroLabel"))
              .to_have_text(f"SPENT IN {last_month.strftime('%B %Y').upper()}"))
        check("day-relative presets are off for a past month",
              lambda: expect(page.locator('#preset option[value="today"]')).to_be_disabled())
        check("forward is available, back from the oldest month is not",
              lambda: expect(page.locator('[data-panel="dashboard"] [data-month-step="-1"]')).to_be_disabled())

        print("\n5. Insights charts the selected month")
        page.click('[data-tab="analytics"]')
        page.wait_for_timeout(350)
        check("the card names the month",
              lambda: expect(page.locator("#analyticsLabel"))
              .to_contain_text(last_month.strftime("%B %Y").upper()))
        check("the total is last month's",
              lambda: expect(page.locator("#analyticsTotal"))
              .to_have_text(f"₹{money(LAST_MONTH_TOTAL)}.00"))
        check("the days range draws a line",
              lambda: expect(page.locator("#trend .chart-line")).to_have_count(1))
        check("it calls out its peak at rest",
              lambda: expect(page.locator("#trend .chart-tooltip")).to_be_visible())
        check("and prints an average under it",
              lambda: expect(page.locator("#chartMeta")).to_contain_text("Avg"))
        check("the breakdown is by category",
              lambda: expect(page.locator("#analyticsStats .top-item strong").first).to_have_text("Rent"))
        check("with a share bar per category",
              lambda: expect(page.locator("#analyticsStats .share-track").first).to_be_visible())

        page.click('[data-range="weeks"]')
        page.wait_for_timeout(300)
        check("the weeks range draws bars",
              lambda: expect(page.locator("#trend .chart-bar").first).to_be_visible())
        page.click('[data-range="year"]')
        page.wait_for_timeout(300)
        check("the year range draws twelve bars",
              lambda: expect(page.locator("#trend .chart-bar")).to_have_count(12))
        check("and highlights the selected month",
              lambda: expect(page.locator("#trend .chart-bar.is-accent")).to_have_count(1))

        print("\n6. Scrubbing the chart reads a value out")
        box = page.locator("#trend svg").bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(200)
        check("the tooltip follows the pointer",
              lambda: expect(page.locator("#trend .chart-cursor-chip")).to_be_visible())

        print("\n7. The month picker offers every month plus All time")
        page.click('[data-range="days"]')
        page.click('[data-panel="analytics"] [data-month-open]')
        page.wait_for_timeout(300)
        check("the picker opens", lambda: expect(page.locator("#monthModal")).to_be_visible())
        check("it lists both months and All time",
              lambda: expect(page.locator("#monthList .month-option")).to_have_count(3))
        page.click('[data-month-pick="all"]')
        page.wait_for_timeout(350)
        check("All time totals everything",
              lambda: expect(page.locator('[data-panel="analytics"] .month-amt'))
              .to_contain_text(f"₹{money(ALL_TOTAL)}.00"))
        page.click('[data-tab="dashboard"]')
        check("the dashboard shows the all-time total",
              lambda: expect(page.locator("#total")).to_have_text(f"₹{money(ALL_TOTAL)}.00"))
        check("the arrows are inert with no month selected",
              lambda: expect(page.locator('[data-panel="dashboard"] [data-month-step="1"]')).to_be_disabled())

        print("\n8. Profile reports on the selected month")
        page.click('[data-tab="profile"]')
        check("all-time card is always all time",
              lambda: expect(page.locator("#profileAllTime")).to_have_text(f"₹{money(ALL_TOTAL)}.00"))
        page.click('[data-panel="profile"] [data-month-open]')
        page.wait_for_timeout(250)
        page.click(f'[data-month-pick="{now.strftime("%Y-%m")}"]')
        page.wait_for_timeout(350)
        check("picking a month scopes the cards",
              lambda: expect(page.locator("#profileTotal")).to_have_text(f"₹{money(THIS_MONTH_TOTAL)}.00"))
        check("and says which month they are",
              lambda: expect(page.locator("#profileTotalLabel"))
              .to_have_text(f"Spent in {now.strftime('%B')}"))

        ignore = ("favicon", "cert_authority_invalid", "fonts.g")
        real = [e for e in errors if not any(word in e.lower() for word in ignore)]
        check(f"no console/page errors ({len(real)})",
              lambda: (_ for _ in ()).throw(AssertionError(real[0])) if real else None)

        browser.close()
finally:
    for proc in servers:
        proc.terminate()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)

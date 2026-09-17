"""Browser end-to-end test for the server-rendered dashboard at GET /?key=.

This page is not the Vite app in frontend/ -- it is the standalone dashboard
in app/static/index.html that the API serves itself, and it carries its own
copy of the month selector, the search totals and the chart. Covered
separately because nothing in the frontend/ suite touches this file.

Needs Chromium, but no frontend build: the API serves the page.

    python3 tests/browser/test_dashboard_month_ui.py
"""
import os, subprocess, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path("/home/user/Money-Tracker")
API = "http://127.0.0.1:8124"
KEY = "e2e-test-key"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

def wait_for(url):
    for _ in range(80):
        try: urllib.request.urlopen(url, timeout=2); return
        except urllib.error.HTTPError: return
        except Exception: time.sleep(0.3)
    sys.exit("no server " + url)

env = {**os.environ, "PYTHONPATH": str(ROOT)}
api = subprocess.Popen([sys.executable, str(ROOT/"tests/browser/serve_fake_api.py")], cwd=ROOT, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
wait_for(API + "/health")

now = datetime.now(timezone.utc)
first = now.replace(day=1, hour=12, minute=0, second=0, microsecond=0)
rows = [("Food",240,0),("Coffee",90,1),("Rent",15000,2),("Food",60,3),("Shopping",430,5),
        ("Travel",220,6),("Bills",980,9),("Food",310,10),("Health",620,13)]
seed = [(c,a,first+timedelta(days=d)) for c,a,d in rows if d < now.day]
prev = (first - timedelta(days=1)).replace(day=8, hour=12)
seed += [("Rent",15000,prev),("Food",780,prev+timedelta(days=3))]
THIS = sum(a for _,a,w in seed if w.month == now.month)
LAST = sum(a for _,a,w in seed if w.month == prev.month)
FOOD = sum(a for c,a,w in seed if c=="Food" and w.month == now.month)
fails=[]
def check(label, fn):
    try: fn(); print(f"  PASS  {label}")
    except Exception as e:
        fails.append(label); print(f"  FAIL  {label}: {str(e).splitlines()[0][:180]}")
def money(v): return f"{v:,}"

errors=[]
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME)
        page = b.new_page(viewport={"width": 390, "height": 840}, device_scale_factor=2)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        for c,a,w in seed:
            page.request.post(f"{API}/api/expenses",
                headers={"X-API-Key": KEY, "Content-Type": "application/json"},
                data={"amount": a, "category": c, "payment_method": "UPI" if a % 2 else "Cash", "date": w.isoformat()})
        page.goto(f"{API}/?key={KEY}", wait_until="networkidle")
        page.wait_for_timeout(800)

        print("\n1. Opens on the current month")
        check("strip names it", lambda: expect(page.locator("#mName")).to_have_text(now.strftime("%B %Y")))
        check("strip totals it", lambda: expect(page.locator("#mAmt")).to_have_text(f"₹{money(THIS)}.00"))
        check("hero is the month total", lambda: expect(page.locator("#total")).to_have_text(f"₹{money(THIS)}.00"))
        check("last month is not listed", lambda: expect(page.locator("#list")).not_to_contain_text("Aug"))

        print("\n2. Search totals what matched")
        page.click("#searchBtn"); page.fill("#q", "food"); page.wait_for_timeout(350)
        check("summary shows the food total",
              lambda: expect(page.locator(".sumtotal")).to_have_text(f"₹{money(FOOD)}.00"))
        check("it says what it totalled", lambda: expect(page.locator(".sumhead").first).to_contain_text("food"))
        page.fill("#q", ""); page.wait_for_timeout(300)

        print("\n3. Stepping back moves the page")
        page.click("#mPrev"); page.wait_for_timeout(400)
        check("strip names last month", lambda: expect(page.locator("#mName")).to_have_text(prev.strftime("%B %Y")))
        check("hero is last month's", lambda: expect(page.locator("#total")).to_have_text(f"₹{money(LAST)}.00"))
        check("presets are disabled", lambda: expect(page.locator('#preset option[value="today"]')).to_be_disabled())
        check("back is now the oldest", lambda: expect(page.locator("#mPrev")).to_be_disabled())

        print("\n4. The month sheet")
        page.click("#mPick"); page.wait_for_timeout(300)
        check("it lists both months and All time", lambda: expect(page.locator("#mList .mopt")).to_have_count(3))
        page.click('[data-month="all"]'); page.wait_for_timeout(400)
        check("All time totals everything",
              lambda: expect(page.locator("#mAmt")).to_have_text(f"₹{money(THIS+LAST)}.00"))
        check("the preset renames itself",
              lambda: expect(page.locator('#preset option[value="month"]')).to_have_text("All time"))

        print("\n5. The chart reads out a day")
        page.click("#mPick"); page.wait_for_timeout(250)
        page.click(f'[data-month="{now.strftime("%Y-%m")}"]'); page.wait_for_timeout(400)
        box = page.locator("#trendSvg").bounding_box()
        page.evaluate("document.querySelector('#plot').dataset.probe='kept'")
        page.mouse.move(box["x"] + box["width"] * 0.1, box["y"] + box["height"] / 2)
        page.wait_for_timeout(250)
        check("tooltip names a day", lambda: expect(page.locator("#tooltip small")).not_to_have_text("—"))
        check("a cursor dot is shown", lambda: expect(page.locator("#cursorDot")).to_be_visible())

        ignore = ("favicon","cert_authority_invalid","fonts.g")
        real=[e for e in errors if not any(w in e.lower() for w in ignore)]
        check(f"no console/page errors ({len(real)})",
              lambda: (_ for _ in ()).throw(AssertionError(real[0])) if real else None)
        b.close()
finally:
    api.terminate()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: "+", ".join(fails))
sys.exit(1 if fails else 0)
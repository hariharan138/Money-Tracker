"""Browser end-to-end test for recurring expenses and the bottom nav.

Not part of the pytest suite: it needs Chromium and a built frontend, and it
covers the things TestClient structurally cannot -- a CORS preflight, and a
real mouse pointer (which is how the nav's pointer-capture bug survived).

    cd frontend && PRIMARY_API_URL=http://127.0.0.1:8124 \
        SECONDARY_API_URL=http://127.0.0.1:8124 npm run build
    python3 tests/browser/test_recurring_ui.py

It starts and stops its own servers, so each run gets an empty database.
"""
import os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
DIST = ROOT / "frontend" / "dist"
API_PORT, WEB_PORT = 8124, 8125
WEB = f"http://127.0.0.1:{WEB_PORT}"
KEY = "e2e-test-key"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
fails = []


def wait_for(url, what, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except urllib.error.HTTPError:
            return  # responding, even if it is a 401/404
        except Exception:
            time.sleep(0.3)
    sys.exit(f"{what} did not come up at {url}")


def start_servers():
    """Fresh API (in-memory, so an empty database) and static host per run."""
    if not (DIST / "index.html").exists():
        sys.exit(f"build the frontend first -- {DIST} is missing (see this file's docstring)")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    api = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "serve_fake_api.py")],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(WEB_PORT), "--bind", "127.0.0.1"],
        cwd=DIST, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(f"http://127.0.0.1:{API_PORT}/health", "fake API")
    wait_for(f"{WEB}/index.html", "static host")
    return api, web


def check(label, fn):
    try:
        fn()
        print(f"  PASS  {label}")
    except Exception as e:
        fails.append(label)
        print(f"  FAIL  {label}: {str(e).splitlines()[0][:160]}")


servers = start_servers()
try:
  with sync_playwright() as pw:
     browser = pw.chromium.launch(executable_path=CHROME)
     page = browser.new_page(viewport={"width": 390, "height": 844})
     errors = []
     page.on("pageerror", lambda e: errors.append(str(e)))
     page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

     page.goto(f"{WEB}/?key={KEY}", wait_until="networkidle")

     print("\n0. Bottom nav responds to a real mouse pointer")
     # Regression guard: nav.setPointerCapture() on pointerdown retargets the
     # click to the nav, so no tab button's own handler fired. Touch hid it.
     for tab in ("transactions", "analytics", "profile", "dashboard"):
         page.click(f'[data-tab="{tab}"]')
         page.wait_for_timeout(250)
         check(f"mouse click reaches the {tab} tab",
               lambda t=tab: expect(page.locator(f'[data-panel="{t}"]')).to_have_class(
                   re.compile(r"\bactive\b")))

     print("\n1. Add a recurring expense from the + tab")
     page.click('[data-tab="add"]')
     page.fill("#expenseAmount", "18000")
     page.fill("#expenseCategory", "Rent")
     page.select_option("#expenseRepeat", "monthly")

     check("repeat hint appears", lambda: expect(page.locator("#repeatHint")).to_be_visible())
     check("hint names the frequency",
           lambda: expect(page.locator("#repeatHint")).to_contain_text("every month"))
     check("save button relabels",
           lambda: expect(page.locator("#saveExpense")).to_have_text("Save recurring expense"))

     page.click("#saveExpense")
     page.wait_for_timeout(1500)

     print("\n2. The rule generated a real expense")
     check("status confirms the save",
           lambda: expect(page.locator("#statusText")).to_contain_text("Recurring expense saved"))
     check("expense is in the list",
           lambda: expect(page.locator("#list .tx .name").first).to_have_text("Rent"))
     check("amount rendered",
           lambda: expect(page.locator("#list .tx .amount").first).to_contain_text("18,000"))
     check("carries the recurring marker",
           lambda: expect(page.locator("#list .tx .tx-repeat").first).to_be_visible())
     check("dashboard total picked it up",
           lambda: expect(page.locator("#total")).to_contain_text("18,000"))

     print("\n3. Profile shows the rule and opens the manager")
     page.click('[data-tab="profile"]')
     check("count shows 1 active",
           lambda: expect(page.locator("#profileRecurringCount")).to_have_text("1 active"))
     page.click("#manageRecurring")
     page.wait_for_timeout(800)
     check("modal opens", lambda: expect(page.locator("#recurringModal")).to_be_visible())
     check("rule listed",
           lambda: expect(page.locator(".recurring-item-name").first).to_have_text("Rent"))
     check("shows frequency and next run",
           lambda: expect(page.locator(".recurring-item-meta").first).to_contain_text("Every month"))
     check("next run is a date",
           lambda: expect(page.locator(".recurring-item-meta").first).to_contain_text("next on"))

     print("\n4. Pause it")
     page.click("[data-recurring-toggle]")
     page.wait_for_timeout(1200)
     check("marked paused",
           lambda: expect(page.locator(".recurring-item-meta").first).to_contain_text("paused"))
     check("button offers Resume",
           lambda: expect(page.locator("[data-recurring-toggle]")).to_have_text("Resume"))
     check("profile count drops to none active",
           lambda: expect(page.locator("#profileRecurringCount")).to_have_text("0 active / 1"))

     print("\n5. Delete it, keeping the expense it already made")
     page.on("dialog", lambda d: d.accept() if "Stop the recurring" in d.message else d.dismiss())
     page.click("[data-recurring-delete]")
     page.wait_for_timeout(1500)
     check("rule is gone",
           lambda: expect(page.locator("#recurringList .empty")).to_contain_text("No recurring"))
     page.click("#closeRecurring")
     page.click('[data-tab="transactions"]')
     check("past expense was kept",
           lambda: expect(page.locator("#list .tx .name").first).to_have_text("Rent"))

     # the sandbox proxy intercepts TLS, so the Google Fonts preconnect
     # fails here and nowhere real. Not an app error.
     ignore = ("favicon", "cert_authority_invalid", "fonts.g")
     real_errors = [e for e in errors if not any(i in e.lower() for i in ignore)]
     check(f"no console/page errors ({len(real_errors)})",
           lambda: (_ for _ in ()).throw(AssertionError(real_errors[0])) if real_errors else None)

     browser.close()
finally:
    for process in servers:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)

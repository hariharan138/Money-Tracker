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


def luminance(css_color):
    """Relative luminance of an rgb()/rgba() string, 0 (black) to 1 (white).
    Used to assert a surface is actually dark rather than eyeballing hexes."""
    nums = [float(n) for n in re.findall(r"[\d.]+", css_color or "")][:3]
    if len(nums) < 3:
        return None
    r, g, b = (n / 255 for n in nums)
    channel = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(fg, bg):
    a, b = luminance(fg), luminance(bg)
    if a is None or b is None:
        return 0
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


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
     print("\n6. Scrolling with a finger on the nav must not navigate")
     # Seed enough rows that the page actually scrolls.
     for n in range(14):
         page.request.post(f"http://127.0.0.1:{API_PORT}/api/expenses",
                           headers={"X-API-Key": KEY, "Content-Type": "application/json"},
                           data={"amount": 10 + n, "category": f"Seed{n}", "payment_method": "UPI"})
     page.reload(wait_until="networkidle")
     page.click('[data-tab="transactions"]')
     page.wait_for_timeout(500)

     scrollable = page.evaluate("document.body.scrollHeight > window.innerHeight + 120")
     check("page is long enough to scroll", lambda: (_ for _ in ()).throw(
         AssertionError("page does not scroll; the rest of this section is vacuous")
     ) if not scrollable else None)

     page.evaluate("window.scrollTo(0, 260)")
     page.wait_for_timeout(400)
     before = page.evaluate("window.scrollY")

     box = page.locator(".bottom-nav").bounding_box()
     start = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

     def drag(to_x, to_y, steps=12):
         page.mouse.move(*start)
         page.mouse.down()
         page.mouse.move(to_x, to_y, steps=steps)
         page.mouse.up()
         page.wait_for_timeout(500)

     def scroll_drag(dy=-220, settle=8, drift=80):
         """A real thumb scroll: the finger lands and drifts a few pixels
         sideways *before* it starts moving down the screen. A straight
         interpolated diagonal does not reproduce the bug, because its very
         first sample is already vertical-dominant."""
         page.mouse.move(*start)
         page.mouse.down()
         page.mouse.move(start[0] + settle, start[1] + 2, steps=2)
         page.mouse.move(start[0] + drift, start[1] + dy, steps=12)
         page.mouse.up()
         page.wait_for_timeout(500)

     # Sideways drift first, then the scroll. The old code committed to
     # "horizontal drag" on that drift and never re-checked, so the release
     # switched tabs and showTab() threw the page to the top.
     scroll_drag()
     check("diagonal scroll did not change tab",
           lambda: expect(page.locator('[data-panel="transactions"]')).to_have_class(
               re.compile(r"\bactive\b")))
     check("diagonal scroll did not jump to the top",
           lambda: (_ for _ in ()).throw(AssertionError(
               f"scrollY went {before} -> {page.evaluate('window.scrollY')}"))
           if page.evaluate("window.scrollY") < before - 20 else None)

     # Straight up: unambiguously a scroll.
     drag(start[0], start[1] - 200)
     check("vertical drag did not change tab",
           lambda: expect(page.locator('[data-panel="transactions"]')).to_have_class(
               re.compile(r"\bactive\b")))

     print("\n7. A real horizontal swipe still works")
     page.click('[data-tab="dashboard"]')
     page.wait_for_timeout(400)
     box = page.locator(".bottom-nav").bounding_box()
     start = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
     drag(start[0] - 110, start[1] + 6)   # swipe left -> next tab
     check("swipe left moves to the next tab",
           lambda: expect(page.locator('[data-panel="transactions"]')).to_have_class(
               re.compile(r"\bactive\b")))
     drag(start[0] + 110, start[1] + 6)   # swipe right -> back
     check("swipe right moves to the previous tab",
           lambda: expect(page.locator('[data-panel="dashboard"]')).to_have_class(
               re.compile(r"\bactive\b")))

     print("\n8. Nav colours match the design (charcoal, not violet)")
     add_bg = page.evaluate(
         "getComputedStyle(document.querySelector('.nav-add')).backgroundColor")
     check("centre button is a flat charcoal disc",
           lambda: (_ for _ in ()).throw(AssertionError(add_bg))
           if add_bg != "rgb(28, 33, 40)" else None)
     active_color = page.evaluate(
         "getComputedStyle(document.querySelector('.nav-item.nav-active')).color")
     check("active tab icon is near-black",
           lambda: (_ for _ in ()).throw(AssertionError(active_color))
           if active_color != "rgb(21, 25, 34)" else None)

     print("\n9. The palette is monochrome apart from income/expense")
     # The reference design uses no violet anywhere, so the token is gone.
     # Checking the token rather than one element guards the whole palette.
     token = page.evaluate(
         "getComputedStyle(document.documentElement).getPropertyValue('--violet').trim()")
     check("the --violet token no longer exists",
           lambda: (_ for _ in ()).throw(AssertionError(f"--violet is back: {token}"))
           if token else None)

     # The budget rows only render with a limit set, so set one.
     page.request.put(f"http://127.0.0.1:{API_PORT}/api/limits",
                      headers={"X-API-Key": KEY, "Content-Type": "application/json"},
                      data={"monthly_limit": 40000})
     page.reload(wait_until="networkidle")
     page.wait_for_timeout(900)
     check("budget section renders with a limit set",
           lambda: expect(page.locator("#budgetSection")).to_be_visible())
     check("the month row is ink, not violet",
           lambda: expect(page.locator(".budget-row-icon.ink")).to_have_count(1))
     month_color = page.evaluate(
         "(el => el ? getComputedStyle(el).color : 'missing')"
         "(document.querySelector('.budget-row-icon.ink'))")
     check("month row icon computes to near-black",
           lambda: (_ for _ in ()).throw(AssertionError(month_color))
           if month_color != "rgb(21, 25, 34)" else None)
     # green and amber survive: they carry meaning in the design
     check("week row keeps its green",
           lambda: expect(page.locator(".budget-row-icon.green")).to_have_count(1))
     check("today row keeps its amber",
           lambda: expect(page.locator(".budget-row-icon.orange")).to_have_count(1))

     print("\n10. The Add tab looks like every other tab")

     def head_style(tab, selector):
         page.click(f'[data-tab="{tab}"]')
         page.wait_for_timeout(400)
         return page.evaluate(
             "sel => { const el = document.querySelector(sel); const s = getComputedStyle(el);"
             " return [s.fontSize, s.fontWeight, s.textAlign]; }", selector)

     other = head_style("transactions", '[data-panel="transactions"] .page-head h1')
     add = head_style("add", '[data-panel="add"] .page-head h1')
     check("Add uses the same h1 as the other tabs",
           lambda: (_ for _ in ()).throw(AssertionError(f"{add} != {other}"))
           if add != other else None)

     other_sub = page.evaluate(
         "getComputedStyle(document.querySelector('[data-panel=\"transactions\"] .page-sub')).textAlign")
     add_sub = page.evaluate(
         "getComputedStyle(document.querySelector('[data-panel=\"add\"] .page-sub')).textAlign")
     check("its subtitle aligns like the others (was centred)",
           lambda: (_ for _ in ()).throw(AssertionError(f"{add_sub} != {other_sub}"))
           if add_sub != other_sub else None)

     # The nav used to be hidden for this whole tab, leaving it the only screen
     # with no navigation.
     check("the bottom nav stays on the Add tab",
           lambda: expect(page.locator(".bottom-nav")).to_be_visible())
     check("the old back-arrow header is gone",
           lambda: expect(page.locator(".add-head, .add-meta")).to_have_count(0))

     save_bg = page.evaluate(
         "getComputedStyle(document.querySelector('#saveExpense')).backgroundImage")
     save_color = page.evaluate(
         "getComputedStyle(document.querySelector('#saveExpense')).backgroundColor")
     check("Save is flat charcoal, not a violet gradient",
           lambda: (_ for _ in ()).throw(AssertionError(f"{save_color} / {save_bg}"))
           if save_color != "rgb(28, 33, 40)" or save_bg != "none" else None)
     action_color = page.evaluate(
         "(page => { document.querySelector('[data-tab=\"profile\"]').click();"
         " return getComputedStyle(document.querySelector('#saveApiKey')).backgroundColor; })()")
     check("it matches the app's other primary buttons",
           lambda: (_ for _ in ()).throw(AssertionError(f"{save_color} != {action_color}"))
           if save_color != action_color else None)

     print("\n11. Dark and light mode")
     page.click('[data-tab="profile"]')
     page.wait_for_timeout(400)
     check("the toggle lives on the Profile tab",
           lambda: expect(page.locator('#themeToggleProfile [data-theme-choice="dark"]')).to_be_visible())

     page.click('[data-theme-choice="dark"]')
     page.wait_for_timeout(600)
     theme = page.evaluate("document.documentElement.dataset.theme")
     check("tapping Dark switches the theme",
           lambda: (_ for _ in ()).throw(AssertionError(theme)) if theme != "dark" else None)

     body_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
     check("the page itself goes dark",
           lambda: (_ for _ in ()).throw(AssertionError(f"{body_bg} lum={luminance(body_bg):.2f}"))
           if luminance(body_bg) > 0.15 else None)

     meta = page.evaluate(
         "document.querySelector('meta[name=\"theme-color\"]').getAttribute('content')")
     check("the browser/status bar colour follows",
           lambda: (_ for _ in ()).throw(AssertionError(meta)) if meta != "#101317" else None)

     # Nothing may be left behind on a light surface. Sampling computed values
     # beats eyeballing: a token missed in one rule shows up here.
     surfaces = page.evaluate("""
       ['body', '.app', '.tx', '.controls input', '.bottom-nav', '.add-form',
        '.profile-card', '.filter-selects select', '.add-summary', '.recurring-list',
        '.modal-card', '.budget', '.stat']
         .map(sel => { const el = document.querySelector(sel);
                       return [sel, el ? getComputedStyle(el).backgroundColor : null]; })
     """)
     stranded = [(sel, bg) for sel, bg in surfaces
                 if bg and luminance(bg) is not None and luminance(bg) > 0.25]
     check(f"no light surfaces stranded in dark ({len(surfaces)} sampled)",
           lambda: (_ for _ in ()).throw(AssertionError(f"still light: {stranded}"))
           if stranded else None)

     # The specific bug class: the chart draws itself in JS, so a hardcoded
     # near-black line would be invisible here.
     page.click('[data-tab="analytics"]')
     page.wait_for_timeout(700)
     line = page.evaluate(
         "(el => el ? getComputedStyle(el).stroke : 'missing')(document.querySelector('.chart-line'))")
     card_bg = page.evaluate("getComputedStyle(document.querySelector('.analytics-card')).backgroundColor")
     ratio = contrast(line, card_bg)
     check(f"the chart line stays visible in dark (contrast {ratio:.1f}:1)",
           lambda: (_ for _ in ()).throw(AssertionError(f"{line} on {card_bg}"))
           if ratio < 3 else None)

     text_ratio = contrast(
         page.evaluate("getComputedStyle(document.querySelector('h1')).color"), body_bg)
     check(f"heading text clears AA in dark ({text_ratio:.1f}:1)",
           lambda: (_ for _ in ()).throw(AssertionError(f"{text_ratio:.2f}:1"))
           if text_ratio < 4.5 else None)

     page.reload(wait_until="networkidle")
     page.wait_for_timeout(800)
     after = page.evaluate("document.documentElement.dataset.theme")
     check("the choice survives a reload",
           lambda: (_ for _ in ()).throw(AssertionError(after)) if after != "dark" else None)

     page.click('[data-tab="profile"]')
     page.wait_for_timeout(400)
     page.click('[data-theme-choice="light"]')
     page.wait_for_timeout(600)
     back = page.evaluate("document.documentElement.dataset.theme")
     light_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
     check("and switches back to light",
           lambda: (_ for _ in ()).throw(AssertionError(f"{back} / {light_bg}"))
           if back != "light" or luminance(light_bg) < 0.8 else None)

     print("\n12. It follows the system until you choose")
     for scheme, expected in (("dark", "dark"), ("light", "light")):
         fresh = browser.new_context(viewport={"width": 390, "height": 844},
                                     color_scheme=scheme)   # no stored choice
         fp = fresh.new_page()
         fp.goto(f"{WEB}/?key={KEY}", wait_until="networkidle")
         fp.wait_for_timeout(500)
         got = fp.evaluate("document.documentElement.dataset.theme")
         check(f"a fresh install on a {scheme} phone starts {expected}",
               lambda g=got, e=expected: (_ for _ in ()).throw(AssertionError(g)) if g != e else None)
         fresh.close()

     # An explicit choice has to beat the system setting, not lose to it.
     fresh = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
     fp = fresh.new_page()
     fp.goto(f"{WEB}/?key={KEY}", wait_until="networkidle")
     fp.evaluate("localStorage.setItem('expenses-theme', 'light')")
     fp.reload(wait_until="networkidle")
     fp.wait_for_timeout(500)
     chosen = fp.evaluate("document.documentElement.dataset.theme")
     check("an explicit choice overrides the system preference",
           lambda: (_ for _ in ()).throw(AssertionError(chosen)) if chosen != "light" else None)
     # ...and it is applied before first paint, so there is no flash.
     flash = fp.evaluate(
         "document.documentElement.dataset.theme === 'light' && !!document.querySelector('script')")
     check("the theme is resolved by an inline script, before paint",
           lambda: (_ for _ in ()).throw(AssertionError("no pre-paint script")) if not flash else None)
     fresh.close()

     print("\n13. The theme control lives only on Profile")
     page.click('[data-tab="profile"]')
     page.wait_for_timeout(500)
     check("Profile has the Appearance control",
           lambda: expect(page.locator('#themeToggleProfile')).to_be_visible())
     # One control, not two: a second copy elsewhere could disagree with it.
     check("there is exactly one theme control",
           lambda: expect(page.locator('.theme-toggle')).to_have_count(1))
     check("the Transactions tab no longer carries one",
           lambda: expect(page.locator('[data-panel="transactions"] .theme-toggle')
                          ).to_have_count(0))

     page.click('#themeToggleProfile [data-theme-choice="dark"]')
     page.wait_for_timeout(600)
     theme_now = page.evaluate("document.documentElement.dataset.theme")
     check("switching from Profile changes the theme",
           lambda: (_ for _ in ()).throw(AssertionError(theme_now))
           if theme_now != "dark" else None)
     check("the chosen option is marked selected",
           lambda: expect(page.locator('#themeToggleProfile [data-theme-choice="dark"]')
                          ).to_have_attribute("aria-pressed", "true"))

     # The Transactions filters must be untouched by the removal.
     page.click('[data-tab="transactions"]')
     page.wait_for_timeout(400)
     for control in ("#search", "#payments", "#preset", "#sort"):
         check(f"Transactions kept its {control} filter",
               lambda c=control: expect(page.locator(c)).to_be_visible())

     page.click('[data-tab="profile"]')
     page.wait_for_timeout(400)
     page.click('#themeToggleProfile [data-theme-choice="light"]')
     page.wait_for_timeout(600)
     check("and switches back",
           lambda: expect(page.locator('#themeToggleProfile [data-theme-choice="light"]')
                          ).to_have_class(re.compile(r"\bactive\b")))

     print("\n14. Pull to refresh, on every tab")
     # Needs a touch-capable context: the gesture is touch-only by design, so
     # Playwright's mouse cannot reach it. Touches go in over CDP.
     touch_ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
     tp = touch_ctx.new_page()
     tp.goto(f"{WEB}/?key={KEY}", wait_until="networkidle")
     tp.wait_for_timeout(600)
     cdp = touch_ctx.new_cdp_session(tp)

     # Count refreshes the gesture actually started, by watching for the
     # spinner only runRefresh() adds. Counting /api/expenses requests instead
     # was wrong: the 15s background poll lands in the same window and reads
     # as a refresh that never happened.
     WATCH_REFRESH = """
       window.__pullRefreshes = 0;
       (() => {
         const el = document.querySelector('#pullRefresh');
         let was = false;
         new MutationObserver(() => {
           const now = el.classList.contains('spinning');
           if (now && !was) window.__pullRefreshes++;
           was = now;
         }).observe(el, { attributes: true, attributeFilter: ['class'] });
       })();
     """
     tp.evaluate(WATCH_REFRESH)

     def touch_drag(dy, start=(195, 150), steps=12, release=True):
         x, y = start
         cdp.send("Input.dispatchTouchEvent",
                  {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
         for i in range(1, steps + 1):
             cdp.send("Input.dispatchTouchEvent",
                      {"type": "touchMove",
                       "touchPoints": [{"x": x, "y": y + dy * i / steps}]})
             tp.wait_for_timeout(16)
         if release:
             cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

     def reloaded_by(action, settle=1400):
         before = tp.evaluate("window.__pullRefreshes")
         action()
         tp.wait_for_timeout(settle)
         return tp.evaluate("window.__pullRefreshes") > before

     for tab in ("dashboard", "transactions", "add", "analytics", "profile"):
         tp.click(f'[data-tab="{tab}"]')
         tp.wait_for_timeout(500)
         tp.evaluate("window.scrollTo(0, 0)")
         got = reloaded_by(lambda: touch_drag(130))
         check(f"pulling down on {tab} reloads",
               lambda g=got, t=tab: (_ for _ in ()).throw(
                   AssertionError(f"no reload on {t}")) if not g else None)

     print("\n15. ...without swallowing anything else")
     tp.click('[data-tab="dashboard"]')
     tp.wait_for_timeout(500)
     tp.evaluate("window.scrollTo(0, 0)")

     # A short tug is not a pull.
     short = reloaded_by(lambda: touch_drag(30))
     check("a short pull does not reload",
           lambda: (_ for _ in ()).throw(AssertionError("reloaded on a 30px tug"))
           if short else None)

     # The disc has to actually show up while dragging.
     touch_drag(120, release=False)
     opacity = tp.evaluate("getComputedStyle(document.querySelector('#pullRefresh')).opacity")
     check(f"the spinner appears while pulling (opacity {opacity})",
           lambda: (_ for _ in ()).throw(AssertionError(opacity)) if float(opacity) < 0.5 else None)
     cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
     tp.wait_for_timeout(1200)

     # Scrolled down, a downward drag is a scroll, not a refresh.
     tp.click('[data-tab="transactions"]')
     tp.wait_for_timeout(400)
     for n in range(14):
         tp.request.post(f"http://127.0.0.1:{API_PORT}/api/expenses",
                         headers={"X-API-Key": KEY, "Content-Type": "application/json"},
                         data={"amount": 5 + n, "category": f"Pull{n}", "payment_method": "UPI"})
     tp.reload(wait_until="networkidle")
     tp.evaluate(WATCH_REFRESH)  # the page was replaced; so was the observer
     tp.click('[data-tab="transactions"]')
     tp.wait_for_timeout(600)
     tp.evaluate("window.scrollTo(0, 300)")
     tp.wait_for_timeout(400)
     mid = reloaded_by(lambda: touch_drag(130, start=(195, 400)))
     check("pulling while scrolled down does not reload",
           lambda: (_ for _ in ()).throw(AssertionError("refreshed mid-scroll")) if mid else None)

     # A downward drag starting on the nav belongs to the tab swipe.
     tp.evaluate("window.scrollTo(0, 0)")
     tp.wait_for_timeout(400)
     nav_box = tp.locator(".bottom-nav").bounding_box()
     on_nav = reloaded_by(lambda: touch_drag(
         120, start=(nav_box["x"] + nav_box["width"] / 2, nav_box["y"] + 20)))
     check("a pull starting on the nav does not reload",
           lambda: (_ for _ in ()).throw(AssertionError("nav drag refreshed")) if on_nav else None)
     print("\n16. How the pull actually moves")
     tp.click('[data-tab="dashboard"]')
     tp.wait_for_timeout(500)
     tp.evaluate("window.scrollTo(0, 0)")

     def app_shift():
         """Vertical translate currently applied to the page content."""
         return tp.evaluate("""
           (() => { const m = getComputedStyle(document.querySelector('.app')).transform;
                    if (!m || m === 'none') return 0;
                    return Math.round(parseFloat(m.split(',')[5])); })()
         """)

     def disc_shift():
         return tp.evaluate("""
           (() => { const m = getComputedStyle(document.querySelector('#pullRefresh')).transform;
                    if (!m || m === 'none') return null;
                    return Math.round(parseFloat(m.split(',')[5])); })()
         """)

     # The content follows the finger -- the disc is part of the page, not a
     # badge floating over the header.
     touch_drag(90, release=False)
     moved = app_shift()
     check(f"the page content moves with the pull ({moved}px)",
           lambda: (_ for _ in ()).throw(AssertionError(f"content did not move: {moved}px"))
           if moved < 20 else None)
     check("the disc travels with it",
           lambda: (_ for _ in ()).throw(AssertionError(str(disc_shift())))
           if disc_shift() is None or disc_shift() <= -44 else None)
     check("past the threshold it signals 'let go'",
           lambda: expect(tp.locator("#pullRefresh")).to_have_class(re.compile(r"\bready\b")))
     cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
     tp.wait_for_timeout(1500)

     # A pull that stops short must not claim to be ready...
     touch_drag(34, release=False)
     small = app_shift()
     check(f"a small pull moves a small amount ({small}px)",
           lambda: (_ for _ in ()).throw(AssertionError(f"{small}px")) if small > 26 else None)
     check("and does not signal 'let go'",
           lambda: expect(tp.locator("#pullRefresh")).not_to_have_class(re.compile(r"\bready\b")))
     cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
     tp.wait_for_timeout(1200)

     # ...and everything returns to exactly where it started.
     check(f"the content springs back to rest ({app_shift()}px)",
           lambda: (_ for _ in ()).throw(AssertionError(f"{app_shift()}px left over"))
           if abs(app_shift()) > 1 else None)
     check("and the disc is hidden again",
           lambda: (_ for _ in ()).throw(AssertionError(
               tp.evaluate("getComputedStyle(document.querySelector('#pullRefresh')).opacity")))
           if float(tp.evaluate(
               "getComputedStyle(document.querySelector('#pullRefresh')).opacity")) > 0.05 else None)

     print("\n17. The Reload button is gone from Home")
     check("no Reload button anywhere",
           lambda: expect(tp.locator("#reloadBtn")).to_have_count(0))
     check("the avatar it sat beside is still there",
           lambda: expect(tp.locator("#dashAvatar")).to_be_visible())
     # Visible is not enough: removing the Reload button's CSS took the
     # avatar's rules with it once, and a square avatar is still "visible".
     avatar = tp.evaluate("""
       (() => { const s = getComputedStyle(document.querySelector('#dashAvatar'));
                return [s.borderRadius, s.width, s.height, s.backgroundImage !== 'none']; })()
     """)
     check(f"and is still a round gradient disc ({avatar[0]}, {avatar[1]})",
           lambda: (_ for _ in ()).throw(AssertionError(str(avatar)))
           if avatar[0] == "0px" or avatar[1] != "40px" or not avatar[3] else None)
     # Profile keeps its own Refresh data button; only Home's went.
     tp.click('[data-tab="profile"]')
     tp.wait_for_timeout(400)
     check("Profile keeps Refresh data",
           lambda: expect(tp.locator("#profileRefresh")).to_be_visible())

     touch_ctx.close()

     print("\n18. Bundled category icons")
     icon_ctx = browser.new_context(viewport={"width": 390, "height": 900})
     ip = icon_ctx.new_page()
     external = []
     ip.on("request", lambda r: external.append(r.url)
           if r.resource_type == "image" and "127.0.0.1" not in r.url else None)
     ip.goto(f"{WEB}/?key={KEY}", wait_until="networkidle")
     for cat in ("Food", "Groceries", "Rent", "Coffee", "Skydiving", "Food"):
         ip.request.post(f"http://127.0.0.1:{API_PORT}/api/expenses",
                         headers={"X-API-Key": KEY, "Content-Type": "application/json"},
                         data={"amount": 150, "category": cat, "payment_method": "UPI"})
     ip.reload(wait_until="networkidle")
     ip.click('[data-tab="transactions"]')
     ip.wait_for_timeout(1200)

     rows = ip.evaluate("""
       [...document.querySelectorAll('#list .tx')].map(tx => {
         const disc = tx.querySelector('.icon');
         return { name: tx.querySelector('.name').textContent.trim(),
                  tone: [...disc.classList].find(c => c.startsWith('tone-')) || null,
                  svg: disc.querySelectorAll('svg').length,
                  text: disc.textContent.trim() };
       })
     """)
     check(f"every row draws an SVG icon ({len(rows)} rows)",
           lambda: (_ for _ in ()).throw(AssertionError(str(rows)))
           if not rows or any(r["svg"] != 1 for r in rows) else None)
     check("the emoji are gone",
           lambda: (_ for _ in ()).throw(AssertionError(
               str([r for r in rows if r["text"]])))
           if any(r["text"] for r in rows) else None)
     check("each disc carries a tone",
           lambda: (_ for _ in ()).throw(AssertionError(str(rows)))
           if any(r["tone"] is None for r in rows) else None)

     # The behaviour that changed: the tone used to come from the row's
     # position (nth-child), so one category looked different depending on
     # where it landed. Two Food rows in different positions prove it does not.
     foods = {r["tone"] for r in rows if r["name"] == "Food"}
     check(f"a category looks the same wherever it appears ({len(foods)} tone)",
           lambda: (_ for _ in ()).throw(AssertionError(f"Food got {foods}"))
           if len(foods) != 1 else None)
     tones = {r["name"]: r["tone"] for r in rows}
     check("known categories get their own tone",
           lambda: (_ for _ in ()).throw(AssertionError(str(tones)))
           if tones.get("Groceries") != "tone-green" or tones.get("Coffee") != "tone-amber"
           else None)
     check("an unknown category still gets an icon, not a blank disc",
           lambda: (_ for _ in ()).throw(AssertionError(str(tones)))
           if tones.get("Skydiving") != "tone-ink" else None)

     # The whole point of bundling: nothing is fetched.
     check(f"no image is fetched from anywhere ({len(external)} external)",
           lambda: (_ for _ in ()).throw(AssertionError(str(external[:3])))
           if external else None)

     # Top spending reuses the same disc rather than a second icon system.
     ip.click('[data-tab="analytics"]')
     ip.wait_for_timeout(700)
     check("Top spending uses the same icons",
           lambda: expect(ip.locator(".top-item .icon svg").first).to_be_attached())

     # Tokens carry the discs into dark mode with no extra palette.
     light_disc = ip.evaluate(
         "getComputedStyle(document.querySelector('#list .icon')).backgroundColor")
     ip.click('[data-tab="profile"]')
     ip.wait_for_timeout(400)
     ip.click('#themeToggleProfile [data-theme-choice="dark"]')
     ip.wait_for_timeout(700)
     dark_disc = ip.evaluate(
         "getComputedStyle(document.querySelector('#list .icon')).backgroundColor")
     check(f"the discs darken with the theme ({light_disc} -> {dark_disc})",
           lambda: (_ for _ in ()).throw(AssertionError(f"{light_disc} == {dark_disc}"))
           if light_disc == dark_disc or luminance(dark_disc) > 0.3 else None)
     icon_ctx.close()

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

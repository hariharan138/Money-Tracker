# Expense API

FastAPI + MongoDB Atlas endpoint for logging expenses from an iPhone Shortcut.

```
main.py                # run this: `python main.py`
app/
├── main.py            # app, lifespan, 400 handler, /health, /ping, icon routes
├── static/
│   └── index.html     # the dashboard page (route injects expenses into it)
│   └── *.png          # app icons (apple-touch-icon + favicon)
├── config.py          # env vars via pydantic-settings
├── database.py        # AsyncMongoClient lifespan + get_collection dependency
├── keepalive.py       # background self-ping so Render's free tier stays awake
├── models/expense.py  # ExpenseIn / ExpenseCreated
├── models/recurring.py # recurring rules + the occurrence calendar maths
├── routes/auth.py     # accounts, login sessions, credential resolution
├── routes/expenses.py # POST/GET/DELETE /api/expenses
├── routes/recurring.py # recurring rules + catch-up materialisation
└── routes/view.py     # GET / -> HTML dashboard
test_api.py            # smoke test, no DB required
tests/browser/         # Chromium end-to-end test (needs a built frontend)
render.yaml            # Render Blueprint: service, env vars, keep-alive
frontend/              # standalone static dashboard, deploy independently
├── index.html
├── app.js
├── api.js              # centralized primary/secondary API failover
├── styles.css
├── package.json
├── .env.example         # backend URL configuration
├── capacitor.config.json # Android shell config
├── resources/icon.png   # source image for launcher icons
└── android/             # generated Capacitor project (see "Android app")
```

## Deploy the frontend separately

The `frontend/` folder is a small Vite static site. It produces a `dist/`
folder that can be deployed to Netlify, Vercel, Cloudflare Pages, GitHub Pages,
or any static host. It does not need a backend process.

1. Deploy the FastAPI API as normal, for example at `https://expenses-api.example.com`.
2. Copy `frontend/.env.example` to `frontend/.env.local` and set
   `PRIMARY_API_URL` and `SECONDARY_API_URL`. In your frontend host, set the
   same build environment variables instead. These are public API origins; do
   not put API keys or other credentials in frontend environment variables.
3. Set `CORS_ORIGINS` on **both** API deployments to your frontend origin, e.g.
   `https://expenses.example.com`. Use commas for multiple origins.
4. Run `cd frontend && npm install && npm run build`, then deploy `frontend/dist`.
5. Open the frontend at `https://expenses.example.com` (no key in the URL),
   **or** once with `/?key=YOUR_API_KEY`.
6. Go to **Profile** and either **Create account** / **Log in** with a
   username and password, or — if you were handed a key instead — paste it in
   the **API key** box and tap **Save & load data**. Either way the credential
   is stored only in this browser’s localStorage.

`?key=` still works: the app saves it and strips it from the address bar so
Home Screen / PWA launches (manifest `start_url: /`) keep working without the
secret in the URL. Treat one-time `/?key=…` links as private.

**iPhone Home Screen:** open the site once with your key (or save it in
Profile), then Share → Add to Home Screen. Do **not** rely on `?key=` in the
Home Screen URL — the saved key in localStorage is what loads your data.

### One month at a time

Every tab carries the same month strip — `‹ September 2026 ›` with that
month's total under it — and they all read the one selection. Stepping back a
month moves the dashboard, the transaction list, the chart and the profile
figures together; tapping the month name opens a picker with every month that
has data (and **All time**, if you want the old behaviour). The app opens on
the current month.

Two things stay anchored to today whatever month you are on, because they
would be meaningless otherwise: the **Today** figure in Overview, and the
**Add** tab, which always logs against today.

On **Transactions**, a card above the list totals exactly what is on screen —
search `food` and it answers with the food total for that month, the number of
transactions, the average and the largest, plus a chip per category when the
search spans more than one. **Insights** charts the selected month by day or
by week, or its whole year by month, and breaks the spend down by category.

## Android app

`frontend/` doubles as a native Android app via Capacitor — the same HTML/CSS/JS
in a WebView shell, no second codebase.

```bash
cd frontend
npm install
npm run build                                  # bakes .env.local into dist/
npx cap sync android
cd android && ./gradlew assembleDebug          # → app/build/outputs/apk/debug/app-debug.apk
```

Install with `adb install -r app-debug.apk`, or copy the APK to the phone and
tap it (needs "install unknown apps" for whatever opens it).

Two things that will bite:

- **JDK 21+ is required.** Capacitor 8 compiles at source level 21, so a system
  JDK 17 dies with `invalid source release: 21`. Android Studio bundles one:
  `export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"`
- **CORS.** The app is served from `https://localhost` inside the WebView, so
  that origin must be in `CORS_ORIGINS` on **both** API deployments, next to the
  web frontend's URL. Without it every request fails and the app looks offline.

The API URL is compiled in at build time, not read at runtime: after changing
`frontend/.env.local` you must `npm run build && npx cap sync android` and
rebuild the APK.

Launcher icons and splash screens are generated from `frontend/resources/icon.png`
with `npx capacitor-assets generate --android`.

For the Play Store, create your own keystore
(`keytool -genkey -v -keystore expenses.keystore -alias expenses -keyalg RSA -validity 10000`),
add a `signingConfigs` block to `android/app/build.gradle`, then `./gradlew bundleRelease`.

## API

### Authentication

Every endpoint below takes one credential, as `X-API-Key: <value>` (or
`?key=<value>` for plain links). Three kinds are accepted:

| Credential | Where it comes from | Expires |
|---|---|---|
| Env key | `SHORTCUT_API_KEY` / `EXPENSE_USERS` | never |
| Session token | `POST /api/auth/login` | 30 days, or on logout |
| Account key | issued at registration, shown in Profile | never |

### `POST /api/auth/register` / `POST /api/auth/login`

Body: `{"username": "alice", "password": "at least 8 chars"}`. Usernames are
lowercased, 3–32 characters of `A-Z a-z 0-9 . _ -`, and unique.

```json
{ "success": true, "token": "…", "expires_at": "2026-10-03T20:16:15+00:00",
  "username": "alice", "api_key": "…" }
```

Use `token` for the browser and `api_key` for the iPhone Shortcut (the phone
can't run a login flow). Passwords are stored as `scrypt` hashes, never in the
clear. `409` means the username is taken, `401` a bad password.

### `POST /api/auth/logout`

Deletes the session behind the supplied token. The account's `api_key` keeps
working, so logging out of the browser never breaks the Shortcut.

### `GET /api/auth/me`

`{"username": "alice", "account": true, "api_key": "…"}`. `account` is `false`
for env-configured users, whose `api_key` comes back `null` — they already
have their key.

### `POST /api/expenses`

Headers: `Content-Type: application/json`, `X-API-Key: <SHORTCUT_API_KEY>`

| field | type | required | notes |
|---|---|---|---|
| `amount` | number | yes | must be `> 0` |
| `category` | string | yes | non-empty |
| `description` | string | no | |
| `date` | ISO-8601 datetime | no | defaults to server time (UTC) |
| `payment_method` | string | no | |
| `notes` | string | no | |

Empty strings are treated as "not provided". The server always adds `created_at`
and Mongo generates the unique `_id` returned as `expense_id`.

**201**
```json
{ "success": true, "message": "Expense added successfully", "expense_id": "66c8..." }
```

| code | when |
|---|---|
| 201 | created |
| 400 | invalid/missing fields, `amount <= 0` |
| 401 | missing or wrong `X-API-Key` |
| 500 | database error |

Interactive docs: `/docs`. Health check: `/health`.

### `GET /api/expenses`

Auth: `X-API-Key` header **or** `?key=` query param (for the browser).

| param | type | notes |
|---|---|---|
| `category` | string | exact match |
| `payment_method` | string | exact match |
| `user` | string | filter to one person (multi-user setups) |
| `q` | string | case-insensitive search over category/description/notes/payment |
| `from`, `to` | ISO datetime | filter on `date` |
| `limit` | int | default 500, max 2000 |

**200**
```json
{ "success": true, "count": 1, "expenses": [ { "id": "66c8…", "amount": 500, … } ] }
```

### `DELETE /api/expenses/{expense_id}`

Same auth. **200** `{ "success": true, "message": "Expense deleted" }`,
**400** bad id, **404** unknown id.

### `GET /api/limits` / `PUT /api/limits`

Per-user monthly spending limit (used by the dashboard budget tracker). Same
auth as expenses.

- `GET /api/limits` → **200** `{ "success": true, "limit": { "user": "Hari", "monthly_limit": 20000, "updated_at": "…" } }`
- `PUT /api/limits` with `{ "monthly_limit": 20000 }` sets it;
  `{ "monthly_limit": null }` removes it. **400** for a negative value.

The dashboard splits that amount into approximate daily/weekly targets and
warns when you get close to or exceed the monthly budget.

### `GET /api/profile` / `PUT /api/profile`

Per-user profile picture, stored in the database as an image data URL. Same
auth as expenses.

- `GET /api/profile` → `{ "success": true, "profile": { "user": "Hari", "avatar": "data:image/…", "updated_at": "…" } }`
- `PUT /api/profile` with `{ "avatar": "data:image/jpeg;base64,…" }` sets the
  photo; `{ "avatar": null }` removes it. **400** if the avatar isn't an
  image data URL.

The dashboard shows the photo next to your name and on the Profile tab.


### `GET /?key=<SHORTCUT_API_KEY>`

Dashboard for your phone (add to Home Screen — it uses `/icon-180.png` as its
icon, page lives in `app/static/index.html`):

- **Refresh button** (+ `r` key), relative "updated x ago" stamp
- **Live data**: polls for new expenses every 15 s and refreshes instantly when
  you switch back to the tab — Shortcut entries appear without tapping anything
- **Filters**: search box, category chips, date presets (defaults to **All
  time**, plus this month / today / 7d / 30d), sort sheet (newest / oldest / amount)
- **Live 7-day trend chart** built from your data, tap a point for that day's total
- **Stats**: today / last 7 days / this month / largest expense
- List grouped by day with daily subtotals
- **Delete** (✕ with confirm)

A wrong or missing key returns `401`. The key itself is never rendered into
the page source — the JS reads it from the URL you bookmarked.

### `GET|POST /api/recurring`, `PATCH|DELETE /api/recurring/{id}`

Rent, subscriptions — anything you would otherwise retype. A rule stores the
intent; the expenses it implies are written into the normal expenses
collection, so recurring spend flows through every filter, total, chart and
budget with no special handling.

```bash
# every month, from today, until further notice
curl -X POST https://YOUR-APP.onrender.com/api/recurring \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"amount": 18000, "category": "Rent", "frequency": "monthly"}'
```

| Field | Notes |
|---|---|
| `amount` | > 0, required |
| `category` | required |
| `frequency` | `daily`, `weekly` or `monthly` |
| `start_date` | defaults to today, and is the **anchor**: a monthly rule starting on the 5th runs on the 5th |
| `end_date` | optional; must not precede `start_date` |
| `payment_method` | optional, `Cash` or `UPI` |

`PATCH` takes any subset — `{"active": false}` pauses a rule — and an omitted
field is left alone rather than nulled. `DELETE` keeps the expenses the rule
already created, because they are spending that really happened; add
`?purge=true` to remove them too.

**When occurrences are created.** On read, not on a timer. Render's free tier
stops the process when idle, so a scheduler inside it would miss exactly the
windows it was meant to cover; instead any read of your expenses first
materialises whatever the rules owe. Points worth knowing:

- A rule anchored on the 31st runs Jan 31, **Feb 28**, Mar 31 — clamped for
  short months, never permanently drifted onto the 28th.
- Occurrences are stored at **noon UTC**, so the intended calendar day
  survives the dashboard grouping by local day either side of UTC.
- A back-dated rule fills in at most 60 occurrences per read and converges
  over the next few, rather than inserting years of history at once.
- Insertion is idempotent: `(recurring_id, occurrence_key)` is a unique index,
  so a 15-second poll, a double tap and a primary/secondary failover cannot
  produce the same expense twice. The database enforces it, not a
  read-then-write that two concurrent requests could both pass.

Generated expenses carry a `recurring_id`; everything logged by hand or by the
Shortcut has `null`. The dashboard marks them with a ↻.

### Meta endpoints

No API key, no database, safe to call from a monitor or a cron:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness. `{"status":"ok"}`. Render's health check path. |
| `GET /ping` | Keep-alive. Resets Render's idle timer and reports the self-pinger's state — see **Keeping the API awake**. `ENABLE_CRONJOB_PING=false` turns it into a 404. |
| `GET /warmup` | Opens the Mongo connection so the first real request doesn't pay for it. |

### Multiple people

Every credential belongs to one person and the data is **strictly isolated**:
the server tags each expense with whoever's credential sent it, and every
read/delete is locked to that user — nobody can see or touch anyone else's
expenses, limit, or profile photo. The main key is `DEFAULT_USER` ("Me" by
default); legacy expenses created before multi-user count as the default
user's.

**The easy way:** send them the frontend URL and let them tap **Create
account** in Profile. Nothing to configure and no redeploy. A registered
username can never collide with an env user's name (that would merge two
people's data), so registration returns `409` if it does.

**The env way**, for the Shortcut-only users who never open the dashboard:

1. Generate a key for them:
   `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Add to the environment (Render → Environment, or `.env` locally):
   ```
   DEFAULT_USER=Hari
   EXPENSE_USERS=Ajay:THE_NEW_KEY,user3:ANOTHER_KEY
   ```
3. Redeploy. On their phone, set up the same Shortcut but with their key as
   the `X-API-Key` header — they'll see only their own dashboard.

### curl

```bash
curl -i -X POST https://YOUR-APP.onrender.com/api/expenses \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_SECRET_KEY" \
  -d '{
    "amount": 500,
    "category": "Food",
    "description": "Dinner",
    "date": "2026-08-23T19:30:00",
    "payment_method": "UPI",
    "notes": "Dinner with friends"
  }'
```

## iPhone Shortcut setup

1. **Ask for Input** (Number) → "Amount"
2. **Ask for Input** (Text) → "Category"   *(or use "Choose from Menu" for fixed categories)*
3. **Ask for Input** (Text) → "Description"
4. Add a **List** action with two items: `Cash` and `UPI`. Immediately after
   it, add **Choose from List** → prompt: "Payment method". This action
   produces the selected value as the **Chosen Item** Magic Variable.
5. **Get Contents of URL**
   - URL: `https://YOUR-APP.onrender.com/api/expenses`
   - Method: **POST**
   - Headers:
     - `Content-Type` → `application/json`
     - `X-API-Key` → `YOUR_SECRET_KEY`
   - Request Body: **JSON**, with these keys (tap the value field and insert the
     Magic Variable from the matching step):

     | Key | Type | Value |
     |---|---|---|
     | `amount` | Number | *Provided Input* (from step 1) |
     | `category` | Text | *Provided Input* (from step 2) |
     | `description` | Text | *Provided Input* (from step 3) |
     | `payment_method` | Text | *Chosen Item* (from step 4 — **not** the Category input) |
     | `notes` | Text | *(optional)* |

   In the `payment_method` value field, the variable preview must read
   **Chosen Item**. If it says *Provided Input*, `Www`, or your category name,
   delete that value and insert **Chosen Item** again from the Magic Variable
   picker.

That body is equivalent to:

```json
{
  "amount": 500,
  "category": "Food",
  "description": "Dinner",
  "payment_method": "UPI",
  "notes": "Dinner with friends"
}
```

Omit `date` and the server timestamps it. To send it explicitly, add a
`date` (Text) key with a **Format Date** action set to a custom format of
`yyyy-MM-dd'T'HH:mm:ss`.

5. Optional: **Show Notification** with the `success` / `message` from the response.

Keep `X-API-Key` only inside the Shortcut — never in a shared link or a webpage.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in MONGODB_URI and SHORTCUT_API_KEY
python main.py
pytest test_api.py        # optional
```

Generate a key: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

### Tests

`pytest test_api.py` needs no database — Mongo is faked in-process.

`tests/browser/` is a separate Chromium end-to-end test, for the two things a
TestClient structurally cannot reach: a real CORS preflight, and a real mouse
pointer. Both have hidden bugs here before — a method missing from
`allow_methods`, and a `setPointerCapture` on the bottom nav that retargeted
every tab click away from its own button (invisible on touch). It starts its
own servers, so each run gets an empty database:

```bash
cd frontend && PRIMARY_API_URL=http://127.0.0.1:8124 \
    SECONDARY_API_URL=http://127.0.0.1:8124 npm run build && cd ..
python3 tests/browser/test_recurring_ui.py
```

The app pings Atlas on startup and refuses to boot on a bad URI — in Atlas,
add your IP (and `0.0.0.0/0` for Render) under **Network Access**.

## Deploy to Render

1. Push this repo to GitHub (`.env` is gitignored — keep it that way).
2. Render → **New → Web Service** → pick the repo.
3. Runtime **Python 3**
   - Build command: `pip install -r requirements.txt`
   - Start command: `python main.py`
   - Health check path: `/health`
4. **Environment → Add Environment Variable**: `MONGODB_URI`, `SHORTCUT_API_KEY`
   (and optionally `MONGODB_DB`, `MONGODB_COLLECTION`). Never commit these.
5. Add `KEEPALIVE_ENABLED=true` — see **Keeping the API awake** below.
6. Deploy, then point the Shortcut at `https://YOUR-APP.onrender.com/api/expenses`.

Or skip steps 2–5: `render.yaml` in this repo is a Blueprint. Render →
**New → Blueprint** → pick the repo, and it creates the service with the
build/start commands, health check path and keep-alive variables already set,
prompting only for the two secrets.

## Keeping the API awake

Render's free tier stops a web service after ~15 minutes with no **inbound**
HTTP request, and the next request then pays a 30–60s cold start. Two
mechanisms ship here, and they are not redundant — each covers what the other
cannot:

| | Holds an awake instance awake | Wakes a stopped instance |
|---|---|---|
| In-process self-ping (`app/keepalive.py`) | yes | **no** |
| External cron hitting `/ping` | yes | **yes** |

The self-ping cannot wake a stopped instance for the obvious reason: a process
that has been stopped pings nothing. So run both. Both are free.

### 1. In-process self-ping

The app pings its own public URL on a timer from a single background task
started in the FastAPI lifespan, after Mongo is confirmed up. The request
leaves the container, reaches Render's router and comes back in, which is what
makes it count as inbound traffic.

```bash
KEEPALIVE_ENABLED=true            # off by default; turn on for deployed instances only
KEEPALIVE_INTERVAL_MINUTES=10     # clamped to 1–14; Render sleeps at 15
KEEPALIVE_PATH=/ping              # use /health if ENABLE_CRONJOB_PING=false
# KEEPALIVE_URL=https://...       # only for a custom domain (see below)
```

`KEEPALIVE_URL` is normally left unset: Render injects `RENDER_EXTERNAL_URL`
and the module falls back to it, so the same config works on a renamed service
or a second instance. Set it only when the public URL differs from Render's
(custom domain, non-Render host).

Design notes, so it stays lightweight and cannot affect the API:

- One `asyncio` task, one `httpx.AsyncClient`, one GET every 10 minutes —
  about 144 requests a day against an endpoint that touches no database.
- Every failure is caught and logged. A keep-alive that can take the process
  down is worse than a sleeping instance, so `ping_once` never raises.
- Each interval is jittered to 85–100% so two instances of the same service
  drift apart instead of pinging in lockstep.
- Interval is clamped to 1–14 minutes: a misconfigured `30` would otherwise
  silently mean "never".
- The task is cancelled and awaited on shutdown, so a deploy never races an
  in-flight ping.
- It never starts locally or in tests — `KEEPALIVE_ENABLED` defaults to false,
  and it refuses to start with no URL rather than looping on failures.

### 2. External cron (this is the part that can wake it)

Free option — [cron-job.org](https://cron-job.org/):

| Setting | Value |
|---|---|
| URL | `https://YOUR-APP.onrender.com/ping` |
| Schedule | `*/4 * * * *` (every 4 minutes) |
| Method | GET |
| Timeout | 30s (allow for a cold start) |

`/ping` needs no API key, touches no database and is sent with
`Cache-Control: no-store` so a cached 200 can't keep answering for a sleeping
instance. On a paid plan, uncomment the `type: cron` service in `render.yaml`
to run the same request on Render instead.

### Verifying it

```bash
curl -s https://YOUR-APP.onrender.com/ping | python3 -m json.tool
```

```json
{
  "status": "awake",
  "timestamp": "2026-09-14T23:01:51.648860+00:00",
  "recommended_external_interval_minutes": 4,
  "keepalive": {
    "enabled": true,
    "running": true,
    "url": "https://YOUR-APP.onrender.com/ping",
    "interval_minutes": 10.0,
    "pings_ok": 4,
    "pings_failed": 0,
    "last_status": 200,
    "last_error": null
  }
}
```

`running: true` with `pings_ok` climbing means the self-ping is working. If
`enabled` is false, `KEEPALIVE_ENABLED` did not reach the process; if `url` is
null, neither `KEEPALIVE_URL` nor `RENDER_EXTERNAL_URL` was set; a `last_error`
of `HTTP 404` means `KEEPALIVE_PATH` is wrong. Render's own logs carry
`keep-alive pinging <url> every N min` on boot.

Even with both layers, the free tier gives no uptime guarantee — a missed
window still means a cold start, so keep the Shortcut's URL timeout generous.
See KEEP_AWAKE_GUIDE.md for paid alternatives.

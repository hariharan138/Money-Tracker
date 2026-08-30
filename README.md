# Expense API

FastAPI + MongoDB Atlas endpoint for logging expenses from an iPhone Shortcut.

```
main.py                # run this: `python main.py`
app/
├── main.py            # app, 400 handler, /health, icon routes
├── static/
│   └── index.html     # the dashboard page (route injects expenses into it)
│   └── *.png          # app icons (apple-touch-icon + favicon)
├── config.py          # env vars via pydantic-settings
├── database.py        # AsyncMongoClient lifespan + get_collection dependency
├── models/expense.py  # ExpenseIn / ExpenseCreated
├── routes/expenses.py # POST/GET/DELETE /api/expenses + key auth
└── routes/view.py     # GET / -> HTML dashboard
test_api.py            # smoke test, no DB required
frontend/              # standalone static dashboard, deploy independently
├── index.html
├── app.js
├── api.js              # centralized primary/secondary API failover
├── styles.css
├── package.json
└── .env.example         # backend URL configuration
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
5. Open the frontend at `https://expenses.example.com` (no key in the URL).
6. Go to **Profile**, paste your API key (`SHORTCUT_API_KEY` or an
   `EXPENSE_USERS` key), and tap **Save & load data**. The key is stored only
   in this browser’s localStorage.

You can still open `/?key=YOUR_API_KEY` once — the app saves it and strips the
key from the address bar. Treat that one-time URL as private.

## API

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

### Multiple people

Every key belongs to one person and the data is **strictly isolated**: the
server tags each expense with whoever's key sent it, and every read/delete is
locked to that user — a key can never see or touch anyone else's expenses.
The main key is `DEFAULT_USER` ("Me" by default); legacy expenses created
before multi-user count as the default user's. To add someone:

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
5. Deploy, then point the Shortcut at `https://YOUR-APP.onrender.com/api/expenses`.

On Render's free tier the service sleeps; the first Shortcut run after idling
may take ~30s. Bump the Shortcut's URL action timeout if it complains.

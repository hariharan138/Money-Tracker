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
```

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
- **Filters**: search box, category chips, date presets (this month / all /
  today / 7d / 30d), sort sheet (newest / oldest / amount)
- **Live 7-day trend chart** built from your data, tap a point for that day's total
- **Stats**: today / last 7 days / this month / largest expense
- List grouped by day with daily subtotals
- **Delete** (✕ with confirm), **CSV export**, Profile sheet with all-time facts

A wrong or missing key returns `401`. The key itself is never rendered into
the page source — the JS reads it from the URL you bookmarked.

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
4. **Get Contents of URL**
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
     | `payment_method` | Text | `UPI` |
     | `notes` | Text | *(optional)* |

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

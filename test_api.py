"""Smoke test: auth, validation, defaults, insert, list, delete. No MongoDB needed."""
import json
import os

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SHORTCUT_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import (  # noqa: E402
    get_collection,
    get_limits_collection,
    get_profiles_collection,
    get_sessions_collection,
    get_users_collection,
)
from app.main import app  # noqa: E402

inserted: list[dict] = []
delete_finds_row = False
last_query: dict = {}
limits_store: list[dict] = []
profiles_store: list[dict] = []


class FakeCollection:
    async def insert_one(self, doc):
        inserted.append(doc)
        return type("R", (), {"inserted_id": "abc123"})()

    def find(self, query=None):
        last_query["value"] = query
        return self

    def sort(self, *a):
        return self

    def limit(self, n):
        return self

    async def to_list(self, n):
        return [
            {
                "_id": "66c8" + "0" * 20,
                "amount": 500.0,
                "category": "Food",
                "description": "Dinner",
                "date": __import__("datetime").datetime(2026, 8, 23, 19, 30),
                "payment_method": "UPI",
                "notes": None,
                "created_at": __import__("datetime").datetime(2026, 8, 23, 19, 30),
            },
            {
                "_id": "66c8" + "1" * 20,
                "amount": 200.0,
                "category": "Transport",
                "description": "Auto",
                "date": __import__("datetime").datetime(2026, 8, 23, 20, 30),
                "payment_method": "Cash",
                "notes": None,
                "created_at": __import__("datetime").datetime(2026, 8, 23, 20, 30),
            }
        ]

    async def delete_one(self, q):
        return type("R", (), {"deleted_count": 1 if delete_finds_row else 0})()


class FakeLimitsCollection:
    async def find_one(self, query):
        for doc in limits_store:
            if doc["user"] == query["user"]:
                return doc
        return None

    async def replace_one(self, filter_, doc, upsert=False):
        for i, existing in enumerate(limits_store):
            if existing["user"] == filter_["user"]:
                limits_store[i] = doc
                return type("R", (), {"upserted_id": None})()
        limits_store.append(doc)
        return type("R", (), {"upserted_id": "x"})()


class FakeProfilesCollection:
    async def find_one(self, query):
        for doc in profiles_store:
            if doc["user"] == query["user"]:
                return doc
        return None

    async def replace_one(self, filter_, doc, upsert=False):
        for i, existing in enumerate(profiles_store):
            if existing["user"] == filter_["user"]:
                profiles_store[i] = doc
                return type("R", (), {"upserted_id": None})()
        profiles_store.append(doc)
        return type("R", (), {"upserted_id": "x"})()


class FakeStore:
    """In-memory stand-in for a Mongo collection: exact-match find_one,
    insert_one with unique-key enforcement, delete_one."""

    def __init__(self, *unique):
        self.docs: list[dict] = []
        self.unique = unique

    def clear(self):
        self.docs.clear()

    async def find_one(self, query):
        return next((d for d in self.docs
                     if all(d.get(k) == v for k, v in query.items())), None)

    async def insert_one(self, doc):
        for field in self.unique:
            if field in doc and any(d.get(field) == doc[field] for d in self.docs):
                raise DuplicateKeyError(f"duplicate {field}")
        self.docs.append(doc)
        return type("R", (), {"inserted_id": "x"})()

    async def delete_one(self, query):
        hit = await self.find_one(query)
        if hit:
            self.docs.remove(hit)
        return type("R", (), {"deleted_count": 1 if hit else 0})()


users_store = FakeStore("username", "api_key")
sessions_store = FakeStore("token")

app.dependency_overrides[get_collection] = lambda: FakeCollection()
app.dependency_overrides[get_users_collection] = lambda: users_store
app.dependency_overrides[get_sessions_collection] = lambda: sessions_store
app.dependency_overrides[get_limits_collection] = lambda: FakeLimitsCollection()
app.dependency_overrides[get_profiles_collection] = lambda: FakeProfilesCollection()
client = TestClient(app)  # lifespan is skipped: get_collection is overridden
HEAD = {"X-API-Key": "test-key"}


def test_missing_or_wrong_key_is_401():
    assert client.post("/api/expenses", json={"amount": 1, "category": "Food"}).status_code == 401
    assert client.post(
        "/api/expenses", json={"amount": 1, "category": "Food"}, headers={"X-API-Key": "nope"}
    ).status_code == 401


def test_invalid_input_is_400():
    for bad in ({"amount": 0, "category": "Food"}, {"amount": -5, "category": "Food"},
                {"amount": 10}, {"amount": 10, "category": "  "},
                {"amount": 10, "category": "Food", "payment_method": "Hh"}):
        assert client.post("/api/expenses", json=bad, headers=HEAD).status_code == 400


def test_payment_method_is_normalised():
    inserted.clear()
    r = client.post(
        "/api/expenses",
        json={"amount": 10, "category": "Food", "payment_method": "upi"},
        headers=HEAD,
    )
    assert r.status_code == 201
    assert inserted[0]["payment_method"] == "UPI"


def test_create_defaults_and_response():
    inserted.clear()
    r = client.post("/api/expenses", json={"amount": "500", "category": "Food", "notes": ""},
                    headers=HEAD)
    assert r.status_code == 201
    assert r.json() == {"success": True, "message": "Expense added successfully",
                        "expense_id": "abc123"}
    doc = inserted[0]
    assert doc["amount"] == 500.0 and doc["notes"] is None
    assert doc["date"] and doc["created_at"]  # both auto-filled


def test_explicit_date_kept():
    inserted.clear()
    client.post("/api/expenses",
                json={"amount": 12, "category": "Food", "date": "2026-08-23T19:30:00"},
                headers=HEAD)
    assert inserted[0]["date"].hour == 19
    # Ensure timezone is UTC
    assert inserted[0]["date"].tzinfo is not None


def test_date_timezone_handling():
    """Test that dates are properly converted to UTC."""
    inserted.clear()
    # Test with naive datetime (should be treated as UTC)
    client.post("/api/expenses",
                json={"amount": 15, "category": "Food", "date": "2026-08-23T19:30:00"},
                headers=HEAD)
    assert inserted[0]["date"].tzinfo is not None
    assert inserted[0]["date"].hour == 19  # Hour should be preserved
    
    # Test with empty date (should default to current UTC time)
    inserted.clear()
    client.post("/api/expenses",
                json={"amount": 20, "category": "Food", "date": ""},
                headers=HEAD)
    assert inserted[0]["date"].tzinfo is not None
    assert inserted[0]["created_at"].tzinfo is not None


def test_list_expenses_auth_and_shape():
    assert client.get("/api/expenses").status_code == 401
    r = client.get("/api/expenses?key=test-key")          # query key works for browsers
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["count"] == 2
    e = body["expenses"][0]
    assert set(e) == {"id", "amount", "category", "description", "date",
                      "payment_method", "notes", "created_at", "user"}
    assert e["amount"] == 500.0 and e["date"].startswith("2026-08-23T19:30")
    assert e["user"] == settings.default_user


def test_list_filters_build_query():
    client.get("/api/expenses?key=test-key&category=Food&q=dinner&from=2026-08-01&to=2026-08-31")
    q = last_query["value"]
    assert q["category"] == "Food"
    assert q["date"]["$gte"].day == 1 and q["date"]["$lte"].month == 8
    assert "$or" in q


def test_search_keeps_the_user_scope():
    """Regression: the text search used to write query["$or"], overwriting the
    ownership clause, so searching as the default user returned everyone's rows."""
    client.get("/api/expenses?key=test-key")
    assert "user" in last_query["value"]
    client.get("/api/expenses?key=test-key&q=dinner")
    assert "user" in last_query["value"], "search dropped the ownership filter"


def test_to_filter_includes_the_whole_end_day():
    client.get("/api/expenses?key=test-key&to=2026-08-31")
    end = last_query["value"]["date"]["$lte"]
    assert (end.day, end.hour, end.minute) == (31, 23, 59)


def test_junk_key_is_401_not_500():
    # compare_digest raises on non-ASCII str; ?key= accepts any unicode
    assert client.get("/api/expenses?key=caf%C3%A9").status_code == 401


def test_delete_validation_and_flow():
    assert client.delete("/api/expenses/not-an-id?key=test-key").status_code == 400
    oid = "66c800000000000000000000"
    assert client.delete(f"/api/expenses/{oid}?key=test-key").status_code == 404  # not found
    global delete_finds_row
    delete_finds_row = True
    r = client.delete(f"/api/expenses/{oid}?key=test-key")
    assert r.status_code == 200 and r.json() == {"success": True, "message": "Expense deleted"}
    delete_finds_row = False


def test_view_page_renders_dashboard():
    r = client.get("/?key=test-key")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert '<link rel="apple-touch-icon" href="/icon-180.png">' in html
    assert 'id="refresh"' in html
    assert "test-key" not in html  # the secret itself is never rendered into the source
    for feat in ('apple-touch-icon" href="/icon-180.png', 'id="preset"',
                 'id="stats"', 'id="sortSheet"', 'buildChart', "Delete this expense",
                 "startPolling"):
        assert feat in html, feat
    assert "profileSheet" not in html and "nav-icon" not in html  # navbar removed
    assert 'id="paymentMethods"' in html  # Cash / UPI payment method filter
    assert 'filter-labels' not in html  # Filter labels removed
    bootstrap = html.split('type="application/json">')[1].split("</script>")[0]
    docs = json.loads(bootstrap.replace("<\\/", "</"))
    assert len(docs) == 2  # Two fake expenses in test data
    assert docs[0]["category"] == "Food"
    assert client.get("/").status_code == 401  # no key -> 401


def test_cors_allows_the_browser_to_post():
    """The dashboard adds expenses with POST; it was missing from allow_methods."""
    from app.main import _cors_origins

    origin = _cors_origins[0] if _cors_origins else None
    if origin is None:
        return  # CORS not configured in this environment
    for method in ("GET", "POST", "PUT", "DELETE"):
        r = client.options("/api/expenses", headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type,x-api-key",
        })
        assert r.status_code == 200, f"{method}: {r.text}"


def test_icons_served():
    for name in ("icon-180.png", "icon-167.png", "icon-152.png", "favicon.png"):
        r = client.get(f"/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_multi_user_isolation():
    from app.config import all_users

    orig_default, orig_extra = settings.default_user, settings.expense_users
    settings.default_user = "Hari"
    settings.expense_users = "Wife:wife-secret-key"
    try:
        assert all_users() == {"test-key": "Hari", "wife-secret-key": "Wife"}
        inserted.clear()
        assert client.post("/api/expenses", json={"amount": 5, "category": "Food"},
                           headers={"X-API-Key": "wife-secret-key"}).status_code == 201
        assert client.post("/api/expenses", json={"amount": 7, "category": "Food"},
                           headers=HEAD).status_code == 201
        assert [d["user"] for d in inserted] == ["Wife", "Hari"]
        # listing is FORCED to the caller's own docs — ?user= can't override
        last_query["value"] = {}  # Clear instead of clear() method
        client.get("/api/expenses?key=wife-secret-key")
        assert last_query["value"] == {"user": "Wife"}
    finally:
        settings.expense_users = orig_extra
        settings.default_user = orig_default
    assert client.get("/api/expenses?key=wrong-user-key").status_code == 401


def test_view_scoped_to_owner_only():
    settings.expense_users = "Wife:wife-secret-key"
    try:
        # Hari (default user) also sees legacy docs without a user field
        last_query.clear()
        r = client.get("/?key=test-key")
        assert r.status_code == 200
        # one `user` key, not $or — see user_scope(); null covers legacy docs
        # that have no `user` field at all
        assert last_query["value"] == {"user": {"$in": ["Hari", None]}}
        # Wife's page is hard-locked to her docs
        last_query.clear()
        r = client.get("/?key=wife-secret-key")
        assert r.status_code == 200 and last_query["value"] == {"user": "Wife"}
        assert 'id="users"' not in r.text  # no cross-user UI
    finally:
        settings.expense_users = ""
    assert client.get("/?key=nope").status_code == 401


def test_delete_is_scoped_to_owner():
    # the delete_one filter must carry the user clause, so one person can
    # never remove another person's document even with a valid id
    filters = []
    orig = FakeCollection.delete_one

    async def spy(self, q):
        filters.append(q)
        return type("R", (), {"deleted_count": 1 if "user" in q else 0})()

    FakeCollection.delete_one = spy
    try:
        settings.expense_users = "Wife:wife-secret-key"
        oid = "66c800000000000000000000"
        r = client.delete(f"/api/expenses/{oid}?key=wife-secret-key")
        assert r.status_code == 200 and filters[-1]["user"] == "Wife"
    finally:
        FakeCollection.delete_one = orig
        settings.expense_users = ""


def test_limits_get_put_remove():
    limits_store.clear()
    # not set yet -> null limit
    r = client.get("/api/limits", headers=HEAD)
    assert r.status_code == 200 and r.json()["limit"]["monthly_limit"] is None

    # set a limit
    r = client.put("/api/limits", headers=HEAD, json={"monthly_limit": 20000})
    assert r.status_code == 200 and r.json()["limit"]["monthly_limit"] == 20000
    r = client.get("/api/limits", headers=HEAD)
    assert r.json()["limit"]["monthly_limit"] == 20000

    # stored under the caller's user name
    assert limits_store and limits_store[0]["user"] == settings.default_user

    # remove it
    r = client.put("/api/limits", headers=HEAD, json={"monthly_limit": None})
    assert r.status_code == 200 and r.json()["limit"]["monthly_limit"] is None

    # rejection: negative/zero limit and missing auth (0 divided by zero on the dashboard)
    assert client.put("/api/limits", headers=HEAD, json={"monthly_limit": -5}).status_code == 400
    assert client.put("/api/limits", headers=HEAD, json={"monthly_limit": 0}).status_code == 400
    assert client.get("/api/limits").status_code == 401


def test_profile_avatar_get_put_remove():
    profiles_store.clear()
    # not set yet -> null avatar
    r = client.get("/api/profile", headers=HEAD)
    assert r.status_code == 200 and r.json()["profile"]["avatar"] is None

    # store a data-URL avatar
    avatar = "data:image/jpeg;base64,/9j/4AAQ=="
    r = client.put("/api/profile", headers=HEAD, json={"avatar": avatar})
    assert r.status_code == 200 and r.json()["profile"]["avatar"] == avatar
    r = client.get("/api/profile", headers=HEAD)
    assert r.json()["profile"]["avatar"] == avatar
    assert profiles_store and profiles_store[0]["user"] == settings.default_user

    # remove it
    r = client.put("/api/profile", headers=HEAD, json={"avatar": None})
    assert r.status_code == 200 and r.json()["profile"]["avatar"] is None

    # reject non-image payloads and missing auth
    assert client.put("/api/profile", headers=HEAD, json={"avatar": "https://example.com/pic.jpg"}).status_code == 400
    assert client.get("/api/profile").status_code == 401



# ---------------------------------------------------------------- accounts


def register(username="alice", password="correct-horse"):
    users_store.clear()
    sessions_store.clear()
    return client.post("/api/auth/register",
                       json={"username": username, "password": password})


def test_register_returns_a_session_and_a_shortcut_key():
    r = register()
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice"
    assert body["token"] and body["api_key"]
    assert body["token"] != body["api_key"]
    # the password is never stored in the clear
    stored = users_store.docs[0]["password_hash"]
    assert stored.startswith("scrypt$") and "correct-horse" not in stored


def test_register_rejects_duplicates_and_weak_passwords():
    register()
    assert client.post("/api/auth/register",
                       json={"username": "Alice", "password": "another-one"}
                       ).status_code == 409  # same name, different case
    assert client.post("/api/auth/register",
                       json={"username": "bob", "password": "short"}
                       ).status_code == 400
    assert client.post("/api/auth/register",
                       json={"username": "b b", "password": "correct-horse"}
                       ).status_code == 400


def test_register_cannot_hijack_an_env_users_name():
    """The username is what expenses are scoped by, so reusing an env user's
    name would hand the new account that person's existing data."""
    users_store.clear()
    orig = settings.expense_users
    settings.expense_users = "Wife:wife-secret-key"
    try:
        for name in ("wife", "WIFE", settings.default_user.lower()):
            r = client.post("/api/auth/register",
                            json={"username": name, "password": "correct-horse"})
            assert r.status_code == 409, name
    finally:
        settings.expense_users = orig


def test_login_flow_and_wrong_password():
    register()
    assert client.post("/api/auth/login",
                       json={"username": "alice", "password": "wrong-password"}
                       ).status_code == 401
    assert client.post("/api/auth/login",
                       json={"username": "nobody", "password": "correct-horse"}
                       ).status_code == 401
    r = client.post("/api/auth/login",
                    json={"username": "ALICE", "password": "correct-horse"})
    assert r.status_code == 200 and r.json()["token"]


def test_session_token_and_account_key_both_authenticate():
    body = register().json()
    for credential in (body["token"], body["api_key"]):
        r = client.get("/api/expenses", headers={"X-API-Key": credential})
        assert r.status_code == 200
        assert last_query["value"] == {"user": "alice"}  # scoped to the account


def test_expired_session_is_rejected():
    from datetime import timedelta

    from app.models.expense import utcnow

    token = register().json()["token"]
    assert client.get("/api/expenses", headers={"X-API-Key": token}).status_code == 200
    # Mongo's TTL reaper lags by up to a minute, so expiry is checked in code
    sessions_store.docs[0]["expires_at"] = utcnow() - timedelta(seconds=1)
    assert client.get("/api/expenses", headers={"X-API-Key": token}).status_code == 401


def test_logout_kills_the_token_but_not_the_shortcut_key():
    body = register().json()
    token, api_key = body["token"], body["api_key"]
    assert client.post("/api/auth/logout", headers={"X-API-Key": token}).status_code == 200
    assert client.get("/api/expenses", headers={"X-API-Key": token}).status_code == 401
    # the phone keeps working; logging out of the browser is not a lockout
    assert client.get("/api/expenses", headers={"X-API-Key": api_key}).status_code == 200


def test_me_distinguishes_accounts_from_env_users():
    body = register().json()
    mine = client.get("/api/auth/me", headers={"X-API-Key": body["token"]}).json()
    assert mine == {"success": True, "username": "alice", "account": True,
                    "api_key": body["api_key"]}
    env = client.get("/api/auth/me", headers=HEAD).json()
    assert env["account"] is False and env["api_key"] is None
    assert env["username"] == settings.default_user
    assert client.get("/api/auth/me").status_code == 401


def test_account_expenses_are_scoped_to_the_account():
    token = register().json()["token"]
    inserted.clear()
    assert client.post("/api/expenses", json={"amount": 9, "category": "Food"},
                       headers={"X-API-Key": token}).status_code == 201
    assert inserted[0]["user"] == "alice"
    client.delete("/api/expenses/66c800000000000000000000",
                  headers={"X-API-Key": token})

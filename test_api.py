"""Smoke test: auth, validation, defaults, insert, list, delete. No MongoDB needed."""
import json
import os

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SHORTCUT_API_KEY", "test-key")
# Set before app.main is imported, because the CORS middleware is installed at
# import time. Without it the preflight test below silently no-ops -- which is
# how a missing allow_methods entry reached a browser twice.
os.environ.setdefault("CORS_ORIGINS", "https://dashboard.example.com")

from bson import ObjectId  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import (  # noqa: E402
    get_collection,
    get_limits_collection,
    get_profiles_collection,
    get_recurring_collection,
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


class FakeMongo:
    """In-memory collection with the slice of the driver the recurring code
    uses: exact-match queries, a composite unique index, find/to_list,
    find_one_and_update, update_one, delete_one/delete_many.

    The unique index is modelled because it is load-bearing — it is what stops
    two concurrent catch-ups both inserting the same occurrence.
    """

    def __init__(self, *unique_together):
        self.docs: list[dict] = []
        self.unique_together = unique_together

    def clear(self):
        self.docs.clear()

    @staticmethod
    def _matches(doc, query):
        """Exact match, plus the $in that user_scope() emits for the default
        user (it has to match both the name and a missing/null user field).
        Other operators are not modelled — no code path under test uses them.
        """
        for key, want in (query or {}).items():
            have = doc.get(key)
            if isinstance(want, dict):
                if "$in" in want:
                    if have not in want["$in"]:
                        return False
                else:
                    raise AssertionError(f"FakeMongo cannot match {key}: {want}")
            elif have != want:
                return False
        return True

    def _find(self, query):
        return [d for d in self.docs if self._matches(d, query)]

    async def find_one(self, query):
        hits = self._find(query)
        return hits[0] if hits else None

    def find(self, query=None):
        self._pending = self._find(query)
        return self

    async def to_list(self, n=None):
        return list(self._pending[:n] if n else self._pending)

    async def count_documents(self, query):
        return len(self._find(query))

    def sort(self, field, direction=1):
        self._pending = sorted(
            self._pending,
            key=lambda d: (d.get(field) is None, d.get(field)),
            reverse=direction < 0,
        )
        return self

    def limit(self, n):
        self._pending = self._pending[:n]
        return self

    async def insert_one(self, doc):
        if self.unique_together and all(f in doc for f in self.unique_together):
            key = tuple(doc[f] for f in self.unique_together)
            if any(tuple(d.get(f) for f in self.unique_together) == key for d in self.docs):
                raise DuplicateKeyError(f"duplicate {self.unique_together}")
        # a real ObjectId, because the routes round-trip it through
        # ObjectId(str(id)) and a fake string id would 400 on every lookup
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return type("R", (), {"inserted_id": doc["_id"]})()

    async def update_one(self, query, update):
        hit = await self.find_one(query)
        if hit:
            hit.update(update.get("$set", {}))
        return type("R", (), {"modified_count": 1 if hit else 0})()

    async def find_one_and_update(self, query, update, return_document=True):
        hit = await self.find_one(query)
        if hit:
            hit.update(update.get("$set", {}))
        return hit

    async def delete_one(self, query):
        hit = await self.find_one(query)
        if hit:
            self.docs.remove(hit)
        return type("R", (), {"deleted_count": 1 if hit else 0})()

    async def delete_many(self, query):
        hits = self._find(query)
        for doc in hits:
            self.docs.remove(doc)
        return type("R", (), {"deleted_count": len(hits)})()


users_store = FakeStore("username", "api_key")
sessions_store = FakeStore("token")
# Empty by default, so catch_up is a no-op for every test that isn't about
# recurring rules.
recurring_store = FakeMongo()

app.dependency_overrides[get_collection] = lambda: FakeCollection()
app.dependency_overrides[get_users_collection] = lambda: users_store
app.dependency_overrides[get_sessions_collection] = lambda: sessions_store
app.dependency_overrides[get_limits_collection] = lambda: FakeLimitsCollection()
app.dependency_overrides[get_profiles_collection] = lambda: FakeProfilesCollection()
app.dependency_overrides[get_recurring_collection] = lambda: recurring_store
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
                      "payment_method", "notes", "created_at", "user",
                      "recurring_id"}
    # null on everything logged by hand; set only on generated occurrences
    assert e["recurring_id"] is None
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

    assert _cors_origins, "CORS_ORIGINS must be set for this test to mean anything"
    origin = _cors_origins[0]
    # PATCH included: pausing a recurring rule needs it, and a method absent
    # from allow_methods fails the preflight before the route is ever reached.
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
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
    # default_user is set explicitly: this used to depend on the value
    # test_multi_user_isolation leaked, so it broke the moment that test
    # started restoring it.
    orig_default, settings.default_user = settings.default_user, "Hari"
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
        settings.default_user = orig_default
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
    orig_users, orig_default = settings.expense_users, settings.default_user
    # a default_user of 3+ characters: the stock "Me" is too short to register
    # at all (Credentials enforces min_length=3), so it would 400 on input
    # validation and never reach the collision check this test is about.
    settings.expense_users = "Wife:wife-secret-key"
    settings.default_user = "Hari"
    try:
        for name in ("wife", "WIFE", settings.default_user.lower()):
            r = client.post("/api/auth/register",
                            json={"username": name, "password": "correct-horse"})
            assert r.status_code == 409, name
    finally:
        settings.expense_users, settings.default_user = orig_users, orig_default


def test_register_rejects_a_name_too_short_to_own_expenses():
    """The gap the test above used to fall into: a DEFAULT_USER shorter than
    Credentials allows can never be registered, so it needs no collision
    check — but it must be a clean 400, not a 500."""
    users_store.clear()
    orig = settings.default_user
    settings.default_user = "Me"
    try:
        r = client.post("/api/auth/register",
                        json={"username": "Me", "password": "correct-horse"})
        assert r.status_code == 400
    finally:
        settings.default_user = orig


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


# ---------------------------------------------------------------- keep-alive
# The keep-alive task itself never starts here: `client` is built without a
# `with` block, so the lifespan (and keepalive.start()) is skipped entirely.


def test_ping_reports_keepalive_state():
    r = client.get("/ping")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awake" and body["timestamp"]
    assert body["recommended_external_interval_minutes"] == settings.cronjob_ping_interval_minutes
    # disabled by default, and no lifespan ran, so nothing is running
    assert body["keepalive"] == {
        "enabled": False, "running": False, "url": None, "interval_minutes": None,
        "pings_ok": 0, "pings_failed": 0, "last_status": None, "last_error": None,
    }


def test_ping_can_be_switched_off():
    orig = settings.enable_cronjob_ping
    settings.enable_cronjob_ping = False
    try:
        assert client.get("/ping").status_code == 404
    finally:
        settings.enable_cronjob_ping = orig
    assert client.get("/ping").status_code == 200


def test_ping_needs_no_key_and_is_never_cached():
    """An external cron cannot hold a secret, and a cached 200 would keep
    answering while the instance slept."""
    r = client.get("/ping")
    assert r.status_code == 200  # no X-API-Key sent
    assert "no-store" in r.headers["cache-control"]
    assert "no-store" in client.get("/health").headers["cache-control"]


def test_keepalive_url_falls_back_to_render_and_normalises():
    from app import keepalive as ka

    orig_url, orig_path = settings.keepalive_url, settings.keepalive_path
    orig_env = os.environ.get(ka.RENDER_URL_ENV)
    try:
        # nothing configured anywhere -> nothing to ping
        settings.keepalive_url = ""
        os.environ.pop(ka.RENDER_URL_ENV, None)
        assert ka.target_url() == ""

        # Render's injected URL is used when KEEPALIVE_URL is unset
        os.environ[ka.RENDER_URL_ENV] = "https://expenses-api.onrender.com"
        assert ka.target_url() == "https://expenses-api.onrender.com/ping"

        # an explicit URL wins, a trailing slash does not double up, and a
        # bare host gets https://
        settings.keepalive_url = "https://custom.example.com/"
        assert ka.target_url() == "https://custom.example.com/ping"
        settings.keepalive_url = "bare-host.example.com"
        assert ka.target_url() == "https://bare-host.example.com/ping"

        settings.keepalive_path = "health"  # missing leading slash
        assert ka.target_url() == "https://bare-host.example.com/health"
        settings.keepalive_path = "   "  # blank falls back to /ping
        assert ka.target_url() == "https://bare-host.example.com/ping"
    finally:
        settings.keepalive_url, settings.keepalive_path = orig_url, orig_path
        os.environ.pop(ka.RENDER_URL_ENV, None)
        if orig_env is not None:
            os.environ[ka.RENDER_URL_ENV] = orig_env


def test_keepalive_interval_is_clamped_below_render_sleep():
    """15 minutes is when Render sleeps, so the interval must stay under it —
    a misconfigured 30 must not silently mean 'never'."""
    from app import keepalive as ka

    orig = settings.keepalive_interval_minutes
    try:
        for wanted, expected_minutes in ((10, 10), (30, 14), (0, 1), (-5, 1), (14, 14)):
            settings.keepalive_interval_minutes = wanted
            assert ka.interval_seconds() == expected_minutes * 60, wanted
    finally:
        settings.keepalive_interval_minutes = orig


class FakePinger:
    """Stands in for httpx.AsyncClient.get."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.urls: list[str] = []

    async def get(self, url, headers=None):
        self.urls.append(url)
        outcome = self.outcomes.pop(0) if self.outcomes else 200
        if isinstance(outcome, Exception):
            raise outcome
        return type("R", (), {"status_code": outcome, "is_success": 200 <= outcome < 300})()


def test_keepalive_counts_outcomes_and_never_raises():
    """A keep-alive that can take the process down is worse than a sleeping
    instance, so every failure has to stay inside ping_once."""
    import asyncio

    from app.keepalive import KeepAlive

    ka = KeepAlive()
    ka.url = "https://expenses-api.onrender.com/ping"
    pinger = FakePinger(200, 500, ConnectionError("dns"), 200)

    assert asyncio.run(ka.ping_once(pinger)) is True
    assert (ka.pings_ok, ka.pings_failed, ka.last_status, ka.last_error) == (1, 0, 200, None)

    # a 5xx still reached Render's router, so it still counted as traffic
    assert asyncio.run(ka.ping_once(pinger)) is False
    assert (ka.pings_ok, ka.pings_failed, ka.last_status, ka.last_error) == (1, 1, 500, "HTTP 500")

    # a transport failure is recorded by type, not by message
    assert asyncio.run(ka.ping_once(pinger)) is False
    assert (ka.pings_ok, ka.pings_failed, ka.last_status, ka.last_error) == (1, 2, None, "ConnectionError")

    # and it recovers
    assert asyncio.run(ka.ping_once(pinger)) is True
    assert (ka.pings_ok, ka.pings_failed, ka.last_error) == (2, 2, None)
    assert pinger.urls == [ka.url] * 4


def test_keepalive_does_not_start_when_disabled_or_unconfigured():
    from app import keepalive as ka

    orig_enabled, orig_url = settings.keepalive_enabled, settings.keepalive_url
    orig_env = os.environ.pop(ka.RENDER_URL_ENV, None)
    try:
        instance = ka.KeepAlive()

        settings.keepalive_enabled = False
        instance.start()
        assert not instance.running and instance.status()["enabled"] is False

        # enabled but with no URL anywhere: warn and stay off rather than
        # spin a task that can only ever fail
        settings.keepalive_enabled = True
        settings.keepalive_url = ""
        instance.start()
        assert not instance.running
    finally:
        settings.keepalive_enabled, settings.keepalive_url = orig_enabled, orig_url
        if orig_env is not None:
            os.environ[ka.RENDER_URL_ENV] = orig_env


def test_keepalive_runs_and_stops_with_the_app_lifespan():
    """The real lifespan path: the self-ping task starts on boot and is
    cancelled on shutdown. Mongo is stubbed out; what is under test is the
    wiring in app/main.py, not the network."""
    import asyncio
    import contextlib

    from app import keepalive as ka
    from app import main as app_main

    orig_enabled, orig_url = settings.keepalive_enabled, settings.keepalive_url
    orig_interval = settings.keepalive_interval_minutes
    settings.keepalive_enabled = True
    settings.keepalive_url = "https://expenses-api.onrender.com"
    settings.keepalive_interval_minutes = 10

    @contextlib.asynccontextmanager
    async def fake_db_lifespan(_app):
        yield  # no Mongo in this test

    async def scenario():
        orig_db = app_main.db_lifespan
        app_main.db_lifespan = fake_db_lifespan
        try:
            async with app_main.lifespan(app_main.app):
                assert ka.keepalive.running
                assert ka.keepalive.url == "https://expenses-api.onrender.com/ping"
                assert ka.keepalive.interval_s == 600
                assert ka.keepalive.status()["interval_minutes"] == 10
                # the loop is parked in its first sleep; prove the ping it will
                # make works against the URL the wiring resolved
                assert await ka.keepalive.ping_once(FakePinger(200)) is True
            # lifespan exited -> the task is cancelled, not orphaned
            assert not ka.keepalive.running
        finally:
            app_main.db_lifespan = orig_db

    try:
        asyncio.run(scenario())
    finally:
        settings.keepalive_enabled = orig_enabled
        settings.keepalive_url = orig_url
        settings.keepalive_interval_minutes = orig_interval
        ka.keepalive.pings_ok = ka.keepalive.pings_failed = 0
        ka.keepalive.last_status = ka.keepalive.last_error = None
        ka.keepalive.url = ""
        ka.keepalive.interval_s = 0.0


# ------------------------------------------------------------------ recurring
# The calendar maths is pure, so it is tested directly; the endpoints are
# tested through the app with an in-memory collection that models the unique
# index the idempotency guarantee depends on.


def test_occurrences_daily_weekly_and_monthly():
    from datetime import date as D

    from app.models.recurring import occurrences

    assert occurrences("daily", D(2026, 3, 1), D(2026, 3, 4)) == [
        D(2026, 3, 1), D(2026, 3, 2), D(2026, 3, 3), D(2026, 3, 4)]
    assert occurrences("weekly", D(2026, 3, 2), D(2026, 3, 24)) == [
        D(2026, 3, 2), D(2026, 3, 9), D(2026, 3, 16), D(2026, 3, 23)]
    assert occurrences("monthly", D(2026, 1, 5), D(2026, 4, 1)) == [
        D(2026, 1, 5), D(2026, 2, 5), D(2026, 3, 5)]
    # nothing is due before the rule starts
    assert occurrences("daily", D(2026, 3, 10), D(2026, 3, 1)) == []


def test_monthly_rule_anchored_past_the_end_of_short_months():
    """A rule set on the 31st must not drift permanently onto the 28th: it is
    clamped for February and returns to the 31st afterwards."""
    from datetime import date as D

    from app.models.recurring import occurrences

    assert occurrences("monthly", D(2026, 1, 31), D(2026, 5, 1)) == [
        D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)]
    # and a leap year gets the 29th
    assert occurrences("monthly", D(2028, 1, 31), D(2028, 3, 1)) == [
        D(2028, 1, 31), D(2028, 2, 29)]


def test_occurrences_respects_after_end_and_cap():
    from datetime import date as D

    from app.models.recurring import occurrences

    # `after` is the last date already materialised, so it is excluded
    assert occurrences("daily", D(2026, 3, 1), D(2026, 3, 5), after=D(2026, 3, 3)) == [
        D(2026, 3, 4), D(2026, 3, 5)]
    # the rule's own end date wins over the window
    assert occurrences("daily", D(2026, 3, 1), D(2026, 3, 9), end=D(2026, 3, 3)) == [
        D(2026, 3, 1), D(2026, 3, 2), D(2026, 3, 3)]
    # a back-dated rule fills in a window at a time instead of thousands at once
    assert occurrences("daily", D(2020, 1, 1), D(2026, 1, 1), cap=5) == [
        D(2020, 1, 1), D(2020, 1, 2), D(2020, 1, 3), D(2020, 1, 4), D(2020, 1, 5)]


def test_occurrence_is_stored_at_noon_utc():
    """Midnight UTC would land on the previous local day for anyone west of
    UTC, and the dashboard groups by local day."""
    from datetime import date as D

    from app.models.recurring import as_datetime

    stamp = as_datetime(D(2026, 3, 9))
    assert (stamp.hour, stamp.tzinfo) == (12, __import__("datetime").timezone.utc)
    assert stamp.date() == D(2026, 3, 9)


class recurring_env:
    """Swap in a realistic expenses collection (with the composite unique
    index) for the duration of a recurring test, then put the default back."""

    def __enter__(self):
        self.expenses = FakeMongo("recurring_id", "occurrence_key")
        recurring_store.clear()
        app.dependency_overrides[get_collection] = lambda: self.expenses
        return self.expenses

    def __exit__(self, *exc):
        app.dependency_overrides[get_collection] = lambda: FakeCollection()
        recurring_store.clear()
        return False


def days_ago(n):
    from datetime import timedelta

    from app.models.recurring import today_utc

    return (today_utc() - timedelta(days=n)).isoformat()


def test_creating_a_rule_backfills_from_its_start_date():
    with recurring_env() as expenses:
        r = client.post("/api/recurring", headers=HEAD, json={
            "amount": 50, "category": "Coffee", "frequency": "daily",
            "payment_method": "upi", "start_date": days_ago(3),
        })
        assert r.status_code == 201, r.text
        body = r.json()
        # today plus the three days before it
        assert body["created_expenses"] == 4
        assert body["recurring"]["frequency"] == "daily"
        assert body["recurring"]["active"] is True
        assert body["recurring"]["payment_method"] == "UPI"  # normalised

        assert len(expenses.docs) == 4
        one = expenses.docs[0]
        assert one["amount"] == 50
        assert (one["category"], one["user"]) == ("Coffee", settings.default_user)
        # every generated expense is linked and stamped for the unique index
        assert str(one["recurring_id"]) == body["recurring"]["id"]
        assert one["occurrence_key"] == days_ago(3)
        assert one["date"].hour == 12


def test_catch_up_is_idempotent_under_repeated_reads():
    """The dashboard polls every 15s and can fail over between two backends
    writing to one database, so the same occurrence gets attempted again and
    again. The unique index, not a read-then-write, is what makes that safe."""
    with recurring_env() as expenses:
        client.post("/api/recurring", headers=HEAD, json={
            "amount": 18000, "category": "Rent", "frequency": "daily",
            "start_date": days_ago(2),
        })
        assert len(expenses.docs) == 3

        # simulate the cursor never advancing (a failed update_one, or a
        # concurrent request that read the rule before it moved)
        for rule in recurring_store.docs:
            rule["last_occurrence"] = None
        for _ in range(3):
            assert client.get("/api/expenses", headers=HEAD).status_code == 200
        assert len(expenses.docs) == 3, "catch-up duplicated occurrences"


def test_a_paused_rule_stops_generating():
    with recurring_env() as expenses:
        rule_id = client.post("/api/recurring", headers=HEAD, json={
            "amount": 10, "category": "Tea", "frequency": "daily",
            "start_date": days_ago(1),
        }).json()["recurring"]["id"]
        assert len(expenses.docs) == 2

        r = client.patch(f"/api/recurring/{rule_id}", headers=HEAD, json={"active": False})
        assert r.status_code == 200
        assert r.json()["recurring"]["active"] is False
        assert r.json()["recurring"]["next_run"] is None
        # the amount and category survived a partial update
        assert r.json()["recurring"]["amount"] == 10
        assert r.json()["recurring"]["category"] == "Tea"

        for rule in recurring_store.docs:
            rule["last_occurrence"] = None  # would regenerate if it were active
        client.get("/api/expenses", headers=HEAD)
        assert len(expenses.docs) == 2


def test_rules_are_scoped_to_their_owner():
    orig = settings.expense_users
    settings.expense_users = "Wife:wife-secret-key"
    try:
        with recurring_env():
            mine = client.post("/api/recurring", headers=HEAD, json={
                "amount": 99, "category": "Gym", "frequency": "monthly",
            }).json()["recurring"]["id"]

            wife = {"X-API-Key": "wife-secret-key"}
            assert client.get("/api/recurring", headers=wife).json()["count"] == 0
            # another user's rule is a 404, not a 403: its existence is not leaked
            assert client.patch(f"/api/recurring/{mine}", headers=wife,
                                json={"active": False}).status_code == 404
            assert client.delete(f"/api/recurring/{mine}", headers=wife).status_code == 404
            # still mine, still untouched
            assert client.get("/api/recurring", headers=HEAD).json()["count"] == 1
            assert client.get("/api/recurring", headers=HEAD
                              ).json()["recurring"][0]["active"] is True
    finally:
        settings.expense_users = orig


def test_deleting_a_rule_keeps_past_expenses_unless_purged():
    with recurring_env() as expenses:
        rule_id = client.post("/api/recurring", headers=HEAD, json={
            "amount": 500, "category": "Bills", "frequency": "daily",
            "start_date": days_ago(2),
        }).json()["recurring"]["id"]
        assert len(expenses.docs) == 3

        # past occurrences are spending that really happened: they stay
        r = client.delete(f"/api/recurring/{rule_id}", headers=HEAD)
        assert r.status_code == 200 and r.json()["deleted_expenses"] == 0
        assert len(expenses.docs) == 3
        assert client.delete(f"/api/recurring/{rule_id}", headers=HEAD).status_code == 404

    with recurring_env() as expenses:
        rule_id = client.post("/api/recurring", headers=HEAD, json={
            "amount": 500, "category": "Bills", "frequency": "daily",
            "start_date": days_ago(2),
        }).json()["recurring"]["id"]
        r = client.delete(f"/api/recurring/{rule_id}?purge=true", headers=HEAD)
        assert r.status_code == 200 and r.json()["deleted_expenses"] == 3
        assert expenses.docs == []


def test_recurring_validation_and_auth():
    with recurring_env():
        assert client.post("/api/recurring", json={
            "amount": 5, "category": "Food", "frequency": "daily"}).status_code == 401
        for bad in (
            {"amount": 0, "category": "Food", "frequency": "daily"},
            {"amount": 5, "category": "  ", "frequency": "daily"},
            {"amount": 5, "category": "Food", "frequency": "fortnightly"},
            {"amount": 5, "category": "Food"},
            {"amount": 5, "category": "Food", "frequency": "daily",
             "payment_method": "Cheque"},
            # an end date before the start date
            {"amount": 5, "category": "Food", "frequency": "daily",
             "start_date": "2026-03-10", "end_date": "2026-03-01"},
        ):
            assert client.post("/api/recurring", headers=HEAD, json=bad).status_code == 400, bad
        assert client.patch("/api/recurring/not-an-id", headers=HEAD,
                            json={"active": False}).status_code == 400
        # an empty patch is refused rather than silently touching updated_at
        rule_id = client.post("/api/recurring", headers=HEAD, json={
            "amount": 5, "category": "Food", "frequency": "daily"}).json()["recurring"]["id"]
        assert client.patch(f"/api/recurring/{rule_id}", headers=HEAD,
                            json={}).status_code == 400


def test_an_ended_rule_backfills_only_to_its_end_date():
    with recurring_env() as expenses:
        body = client.post("/api/recurring", headers=HEAD, json={
            "amount": 20, "category": "Snacks", "frequency": "daily",
            "start_date": days_ago(5), "end_date": days_ago(3),
        }).json()
        assert body["created_expenses"] == 3  # days 5, 4, 3 ago
        assert body["recurring"]["next_run"] is None
        assert sorted(d["occurrence_key"] for d in expenses.docs) == sorted(
            [days_ago(5), days_ago(4), days_ago(3)])


def test_generated_expenses_flow_through_the_normal_list_endpoint():
    """The whole point of materialising: recurring spend needs no special
    case in filtering, totals or the UI."""
    with recurring_env():
        client.post("/api/recurring", headers=HEAD, json={
            "amount": 250, "category": "Netflix", "frequency": "daily",
            "payment_method": "upi", "start_date": days_ago(1),
        })
        body = client.get("/api/expenses", headers=HEAD).json()
        assert body["count"] == 2
        assert {e["category"] for e in body["expenses"]} == {"Netflix"}
        assert all(e["recurring_id"] for e in body["expenses"])
        assert all(e["payment_method"] == "UPI" for e in body["expenses"])
        # and the payment filter reaches them like any other expense
        assert client.get("/api/expenses?payment_method=UPI", headers=HEAD
                          ).json()["count"] == 2

"""Smoke test: auth, validation, defaults, insert, list, delete. No MongoDB needed."""
import json
import os

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SHORTCUT_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import get_collection  # noqa: E402
from app.main import app  # noqa: E402

inserted: list[dict] = []
delete_finds_row = False
last_query: dict = {}


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


app.dependency_overrides[get_collection] = lambda: FakeCollection()
client = TestClient(app)  # lifespan is skipped: get_collection is overridden
HEAD = {"X-API-Key": "test-key"}


def test_missing_or_wrong_key_is_401():
    assert client.post("/api/expenses", json={"amount": 1, "category": "Food"}).status_code == 401
    assert client.post(
        "/api/expenses", json={"amount": 1, "category": "Food"}, headers={"X-API-Key": "nope"}
    ).status_code == 401


def test_invalid_input_is_400():
    for bad in ({"amount": 0, "category": "Food"}, {"amount": -5, "category": "Food"},
                {"amount": 10}, {"amount": 10, "category": "  "}):
        assert client.post("/api/expenses", json=bad, headers=HEAD).status_code == 400


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
    assert 'id="paymentMethods"' not in html  # Payment method filters removed
    assert 'filter-labels' not in html  # Filter labels removed
    bootstrap = html.split('type="application/json">')[1].split("</script>")[0]
    docs = json.loads(bootstrap.replace("<\\/", "</"))
    assert len(docs) == 2  # Two fake expenses in test data
    assert docs[0]["category"] == "Food"
    assert client.get("/").status_code == 401  # no key -> 401


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
        scope = last_query["value"]
        assert {"user": "Hari"} in scope["$or"]
        assert {"user": {"$exists": False}} in scope["$or"]
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

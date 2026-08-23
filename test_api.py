"""Smoke test: auth, validation, defaults, insert, list, delete. No MongoDB needed."""
import json
import os

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SHORTCUT_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

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


def test_list_expenses_auth_and_shape():
    assert client.get("/api/expenses").status_code == 401
    r = client.get("/api/expenses?key=test-key")          # query key works for browsers
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["count"] == 1
    e = body["expenses"][0]
    assert set(e) == {"id", "amount", "category", "description", "date",
                      "payment_method", "notes", "created_at", "user"}
    assert e["amount"] == 500.0 and e["date"].startswith("2026-08-23T19:30")
    assert e["user"] == "Me"


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
    for feat in ('apple-touch-icon" href="/icon-180.png', 'id="cats"', 'id="preset"',
                 'id="stats"', 'id="sortSheet"', 'buildChart', "Delete this expense",
                 "setInterval(poll"):
        assert feat in html, feat
    assert "profileSheet" not in html and "nav-icon" not in html  # navbar removed
    bootstrap = html.split('type="application/json">')[1].split("</script>")[0]
    doc = json.loads(bootstrap.replace("<\\/", "</"))
    assert doc[0]["category"] == "Food"
    assert client.get("/").status_code == 401  # no key -> 401


def test_icons_served():
    for name in ("icon-180.png", "icon-167.png", "icon-152.png", "favicon.png"):
        r = client.get(f"/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_multi_user_keys_tag_and_filter():
    from app.config import all_users, settings

    settings.expense_users = "Wife:wife-secret-key"
    settings.default_user = "Hari"
    try:
        assert all_users() == {"test-key": "Hari", "wife-secret-key": "Wife"}
        inserted.clear()
        assert client.post("/api/expenses", json={"amount": 5, "category": "Food"},
                           headers={"X-API-Key": "wife-secret-key"}).status_code == 201
        assert client.post("/api/expenses", json={"amount": 7, "category": "Food"},
                           headers=HEAD).status_code == 201
        assert [d["user"] for d in inserted] == ["Wife", "Hari"]
        last_query.clear()
        # resolve_user runs before get_collection; reuse dependency override chain
        client.get("/api/expenses?key=wife-secret-key&user=Wife")
    finally:
        settings.expense_users = ""
        settings.default_user = "Me"
    assert last_query["value"] == {"user": "Wife"}
    assert client.get("/api/expenses?key=wrong-user-key").status_code == 401

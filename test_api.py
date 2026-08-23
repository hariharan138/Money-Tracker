"""Smoke test: auth, validation, defaults, insert. No MongoDB needed."""
import os

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("SHORTCUT_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import get_collection  # noqa: E402
from app.main import app  # noqa: E402

inserted: list[dict] = []


class FakeCollection:
    async def insert_one(self, doc):
        inserted.append(doc)
        return type("R", (), {"inserted_id": "abc123"})()


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

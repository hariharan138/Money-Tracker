import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from .config import settings

log = logging.getLogger(__name__)
_client: AsyncMongoClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """One client for the whole process; pymongo pools connections internally.
    Optimized for faster cold starts on Render.com free tier."""
    global _client
    try:
        # Fail fast on a bad URI, but give a real query room to finish: at
        # 3000ms any Atlas free-tier query slower than 3s was killed mid-flight.
        _client = AsyncMongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=20000,
        )
        await _client.admin.command("ping")  # fail fast on bad URI / IP allowlist
        log.info("connected to MongoDB")
        await _ensure_indexes(_client[settings.mongodb_db])
    except Exception as e:
        log.error(f"Failed to connect to MongoDB: {e}")
        raise
    yield
    await _client.close()


async def _ensure_indexes(db) -> None:
    """Uniqueness for accounts, expiry for sessions, and a lookup index on
    every collection that is queried by user. Logged rather than fatal: a
    missing index must not take the whole API down on boot."""
    try:
        await db["users"].create_index("username", unique=True)
        await db["users"].create_index("api_key", unique=True)
        await db["sessions"].create_index("token", unique=True)
        # Mongo deletes a session once expires_at is in the past
        await db["sessions"].create_index("expires_at", expireAfterSeconds=0)

        # Every expense query is find({user}).sort("date", -1), so the
        # compound index serves the filter and the sort in one go and keeps
        # the dashboard off a collection scan as rows accumulate.
        await db[settings.mongodb_collection].create_index([("user", 1), ("date", -1)])
        # Both of these are read on every dashboard load, one document each.
        await db["spending_limits"].create_index("user")
        await db["profiles"].create_index("user")

        # Recurring rules are listed per user, and filtered to the active ones
        # on the catch-up path.
        await db["recurring"].create_index([("user", 1), ("active", 1)])
        # The Notes page lists newest-first, same shape as the expense query.
        await db["notes"].create_index([("user", 1), ("updated_at", -1)])
        # The idempotency guarantee for materialisation: one expense per rule
        # per occurrence date, enforced by the database rather than by a
        # read-then-write that two concurrent polls could both pass. Sparse,
        # so the expenses that carry no occurrence_key are not indexed.
        await db[settings.mongodb_collection].create_index(
            [("recurring_id", 1), ("occurrence_key", 1)], unique=True, sparse=True
        )
    except Exception:
        log.exception("could not create indexes; accounts may allow duplicates")


def get_collection() -> AsyncCollection:
    """FastAPI dependency — overridable in tests."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db][settings.mongodb_collection]


def get_limits_collection() -> AsyncCollection:
    """FastAPI dependency for per-user spending limits."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db]["spending_limits"]


def get_profiles_collection() -> AsyncCollection:
    """FastAPI dependency for per-user profile pictures."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db]["profiles"]


def get_users_collection() -> AsyncCollection:
    """FastAPI dependency for username/password accounts."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db]["users"]


def get_recurring_collection() -> AsyncCollection:
    """FastAPI dependency for recurring expense rules."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db]["recurring"]


def get_sessions_collection() -> AsyncCollection:
    """FastAPI dependency for login sessions (TTL-expired by Mongo)."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db]["sessions"]


def get_notes_collection() -> AsyncCollection:
    """FastAPI dependency for the Notes page (text + inline image data URLs)."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db]["notes"]

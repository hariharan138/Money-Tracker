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
    """Uniqueness for accounts, and expiry for sessions. Logged rather than
    fatal: a missing index must not take the whole API down on boot."""
    try:
        await db["users"].create_index("username", unique=True)
        await db["users"].create_index("api_key", unique=True)
        await db["sessions"].create_index("token", unique=True)
        # Mongo deletes a session once expires_at is in the past
        await db["sessions"].create_index("expires_at", expireAfterSeconds=0)
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


def get_sessions_collection() -> AsyncCollection:
    """FastAPI dependency for login sessions (TTL-expired by Mongo)."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db]["sessions"]

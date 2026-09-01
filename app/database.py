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
        # Faster timeout for cold starts (3 seconds instead of 5)
        _client = AsyncMongoClient(
            settings.mongodb_uri, 
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
            socketTimeoutMS=3000
        )
        await _client.admin.command("ping")  # fail fast on bad URI / IP allowlist
        log.info("connected to MongoDB")
    except Exception as e:
        log.error(f"Failed to connect to MongoDB: {e}")
        raise
    yield
    await _client.close()


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

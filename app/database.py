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
    """One client for the whole process; pymongo pools connections internally."""
    global _client
    _client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    await _client.admin.command("ping")  # fail fast on bad URI / IP allowlist
    log.info("connected to MongoDB")
    yield
    await _client.close()


def get_collection() -> AsyncCollection:
    """FastAPI dependency — overridable in tests."""
    assert _client is not None, "lifespan did not run"
    return _client[settings.mongodb_db][settings.mongodb_collection]

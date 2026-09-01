import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import PyMongoError

from ..config import settings
from ..database import get_collection, get_limits_collection
from .expenses import resolve_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["limits"])


class LimitIn(BaseModel):
    monthly_limit: float | None = Field(default=None, ge=0)


def _to_json(d: dict) -> dict:
    limit = d.get("monthly_limit")
    return {
        "user": d.get("user") or settings.default_user,
        "monthly_limit": float(limit) if limit is not None else None,
        "updated_at": d.get("updated_at").isoformat() if d.get("updated_at") else None,
    }


@router.get("/limits", summary="Get MY monthly spending limit")
async def get_limits(
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_limits_collection),
) -> dict:
    try:
        doc = await collection.find_one({"user": user})
    except PyMongoError:
        log.exception("get limits failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return {"success": True, "limit": _to_json(doc) if doc else {"user": user, "monthly_limit": None, "updated_at": None}}


@router.put("/limits", summary="Set MY monthly spending limit")
async def set_limits(
    payload: LimitIn = Body(...),
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_limits_collection),
) -> dict:
    now = datetime.now(timezone.utc)
    doc = {"user": user, "monthly_limit": payload.monthly_limit, "updated_at": now}
    try:
        await collection.replace_one(
            {"user": user},
            doc,
            upsert=True,
        )
    except PyMongoError:
        log.exception("set limits failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return {"success": True, "limit": _to_json(doc)}

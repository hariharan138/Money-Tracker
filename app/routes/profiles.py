import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import PyMongoError

from ..config import settings
from ..database import get_profiles_collection
from .expenses import resolve_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["profiles"])

# Cap a stored avatar at ~6 MB of base64 text (fits comfortably under Mongo's
# 16 MB document limit while leaving room for the rest of the doc).
MAX_AVATAR_CHARS = 6_000_000


class ProfileIn(BaseModel):
    avatar: str | None = Field(default=None, max_length=MAX_AVATAR_CHARS)


def _to_json(d: dict) -> dict:
    return {
        "user": d.get("user") or settings.default_user,
        "avatar": d.get("avatar"),
        "updated_at": d.get("updated_at").isoformat() if d.get("updated_at") else None,
    }


@router.get("/profile", summary="Get MY profile")
async def get_profile(
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_profiles_collection),
) -> dict:
    try:
        doc = await collection.find_one({"user": user})
    except PyMongoError:
        log.exception("get profile failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if doc:
        return {"success": True, "profile": _to_json(doc)}
    return {"success": True, "profile": {"user": user, "avatar": None, "updated_at": None}}


@router.put("/profile", summary="Set MY profile picture")
async def set_profile(
    payload: ProfileIn = Body(...),
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_profiles_collection),
) -> dict:
    avatar = payload.avatar
    if avatar is not None and not avatar.startswith("data:image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Avatar must be an image data URL")
    now = datetime.now(timezone.utc)
    doc = {"user": user, "avatar": avatar, "updated_at": now}
    try:
        await collection.replace_one({"user": user}, doc, upsert=True)
    except PyMongoError:
        log.exception("set profile failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return {"success": True, "profile": _to_json(doc)}
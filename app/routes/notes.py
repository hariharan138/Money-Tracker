import logging

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Body, Depends, HTTPException, status
from pymongo import ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import PyMongoError

from ..database import get_notes_collection
from ..models.note import NoteIn, utcnow
from .expenses import resolve_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["notes"])

# How much of the second-and-later lines shows in the list, so that response
# stays small even with a hundred notes on it.
PREVIEW_LEN = 140


def _object_id(note_id: str) -> ObjectId:
    try:
        return ObjectId(note_id)
    except (InvalidId, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid note id")


def _title_and_preview(text: str) -> tuple[str, str]:
    """First non-blank line is the title (like iOS Notes styles it larger);
    the rest, flattened to one line, is the list preview."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "New Note", ""
    title = lines[0][:80]
    preview = " ".join(lines[1:])[:PREVIEW_LEN]
    return title, preview


def _summary(d: dict) -> dict:
    """List shape: no `images` array, just a single thumbnail -- a note with
    a photo you never open again shouldn't cost a full-resolution re-download
    of every image it holds on every list refresh."""
    title, preview = _title_and_preview(d.get("text") or "")
    images = d.get("images") or []
    return {
        "id": str(d["_id"]),
        "title": title,
        "preview": preview,
        "image_count": len(images),
        "thumbnail": images[0] if images else None,
        "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
        "updated_at": d["updated_at"].isoformat() if d.get("updated_at") else None,
    }


def _full(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "text": d.get("text") or "",
        "images": d.get("images") or [],
        "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
        "updated_at": d["updated_at"].isoformat() if d.get("updated_at") else None,
    }


@router.get("/notes", summary="List MY notes")
async def list_notes(
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_notes_collection),
) -> dict:
    try:
        docs = await collection.find({"user": user}).sort("updated_at", -1).to_list(500)
    except PyMongoError:
        log.exception("list notes failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return {"success": True, "notes": [_summary(d) for d in docs]}


@router.get("/notes/{note_id}", summary="Get one of MY notes")
async def get_note(
    note_id: str,
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_notes_collection),
) -> dict:
    try:
        doc = await collection.find_one({"_id": _object_id(note_id), "user": user})
    except PyMongoError:
        log.exception("get note failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    return {"success": True, "note": _full(doc)}


@router.post("/notes", status_code=status.HTTP_201_CREATED, summary="Create a note")
async def create_note(
    payload: NoteIn = Body(...),
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_notes_collection),
) -> dict:
    now = utcnow()
    doc = {"user": user, "text": payload.text, "images": payload.images, "created_at": now, "updated_at": now}
    try:
        result = await collection.insert_one(doc)
    except PyMongoError:
        log.exception("create note failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    doc["_id"] = result.inserted_id
    return {"success": True, "note": _full(doc)}


@router.put("/notes/{note_id}", summary="Update one of MY notes")
async def update_note(
    note_id: str,
    payload: NoteIn = Body(...),
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_notes_collection),
) -> dict:
    try:
        doc = await collection.find_one_and_update(
            {"_id": _object_id(note_id), "user": user},
            {"$set": {"text": payload.text, "images": payload.images, "updated_at": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError:
        log.exception("update note failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    return {"success": True, "note": _full(doc)}


@router.delete("/notes/{note_id}", summary="Delete one of MY notes")
async def delete_note(
    note_id: str,
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_notes_collection),
) -> dict:
    try:
        result = await collection.delete_one({"_id": _object_id(note_id), "user": user})
    except PyMongoError:
        log.exception("delete note failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    return {"success": True, "message": "Note deleted"}

import json
import logging
import re
from datetime import datetime
from secrets import compare_digest

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status, Response
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import PyMongoError

from ..config import all_users, settings
from ..database import get_collection
from ..models.expense import ExpenseCreated, ExpenseIn, ensure_utc, utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["expenses"])


def resolve_user(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    # browsers can't set headers on a plain link, so the view passes ?key=
    key: str = Query(default=""),
) -> str:
    """Any valid key authenticates; returns the display name it belongs to."""
    supplied = x_api_key if x_api_key else key
    if supplied:
        for api_key, name in all_users().items():
            if compare_digest(supplied, api_key):
                return name
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")


# keep the old name working as a plain gate where the user isn't needed
require_api_key = resolve_user


def user_scope(user: str) -> dict:
    """Every query is locked to one person's documents. Legacy docs created
    before multi-user existed belong to the default user."""
    if user == settings.default_user:
        return {"$or": [{"user": user}, {"user": None}, {"user": {"$exists": False}}]}
    return {"user": user}


def _to_json(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "amount": d.get("amount", 0),
        "category": d.get("category", ""),
        "description": d.get("description"),
        "date": d["date"].isoformat() if d.get("date") else None,
        "payment_method": d.get("payment_method"),
        "notes": d.get("notes"),
        "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
        "user": d.get("user") or settings.default_user,
    }


@router.post(
    "/expenses",
    status_code=status.HTTP_201_CREATED,
    response_model=ExpenseCreated,
    summary="Add an expense",
)
async def create_expense(
    expense: ExpenseIn,
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_collection),
) -> ExpenseCreated:
    doc = expense.model_dump()
    doc["created_at"] = utcnow()
    doc["user"] = user  # who logged it, from the key they used
    # Ensure date is stored in UTC
    if doc.get("date"):
        doc["date"] = ensure_utc(doc["date"])
    try:
        result = await collection.insert_one(doc)  # Mongo generates the unique _id
    except PyMongoError:
        log.exception("insert failed")  # log server-side; never leak the URI to the client
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return ExpenseCreated(expense_id=str(result.inserted_id))


@router.get("/expenses", summary="List MY expenses")
async def list_expenses(
    category: str | None = Query(default=None, max_length=100),
    payment_method: str | None = Query(default=None, max_length=100),
    q: str | None = Query(default=None, max_length=200, description="Search text"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=2000),
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_collection),
) -> Response:
    # a key can only ever read its own expenses; no ?user= override exists
    query: dict = user_scope(user)
    if category:
        query["category"] = category
    if payment_method:
        query["payment_method"] = payment_method
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [
            {"description": rx},
            {"notes": rx},
            {"category": rx},
            {"payment_method": rx},
        ]
    if date_from is not None or date_to is not None:
        rng: dict = {}
        if date_from is not None:
            rng["$gte"] = date_from
        if date_to is not None:
            rng["$lte"] = date_to
        query["date"] = rng
    try:
        docs = await collection.find(query).sort("date", -1).limit(limit).to_list(limit)
    except PyMongoError:
        log.exception("list failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return Response(
        content=json.dumps({"success": True, "count": len(docs), "expenses": [_to_json(d) for d in docs]}),
        media_type="application/json",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@router.delete("/expenses/{expense_id}", summary="Delete one of MY expenses")
async def delete_expense(
    expense_id: str,
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_collection),
) -> dict:
    try:
        oid = ObjectId(expense_id)
    except (InvalidId, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid expense id")
    try:
        # ownership check baked into the delete itself: 404 for other people's docs
        result = await collection.delete_one({"_id": oid, **user_scope(user)})
    except PyMongoError:
        log.exception("delete failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    return {"success": True, "message": "Expense deleted"}

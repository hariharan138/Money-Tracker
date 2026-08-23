import logging
import re
from datetime import datetime
from secrets import compare_digest

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import PyMongoError

from ..config import settings
from ..database import get_collection
from ..models.expense import ExpenseCreated, ExpenseIn, utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["expenses"])


def require_api_key(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    # browsers can't set headers on a plain link, so the view passes ?key=
    key: str = Query(default=""),
) -> None:
    supplied = x_api_key if x_api_key else key
    if not supplied or not compare_digest(supplied, settings.shortcut_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")


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
    }


@router.post(
    "/expenses",
    status_code=status.HTTP_201_CREATED,
    response_model=ExpenseCreated,
    dependencies=[Depends(require_api_key)],
    summary="Add an expense",
)
async def create_expense(
    expense: ExpenseIn,
    collection: AsyncCollection = Depends(get_collection),
) -> ExpenseCreated:
    doc = expense.model_dump()
    doc["created_at"] = utcnow()
    try:
        result = await collection.insert_one(doc)  # Mongo generates the unique _id
    except PyMongoError:
        log.exception("insert failed")  # log server-side; never leak the URI to the client
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return ExpenseCreated(expense_id=str(result.inserted_id))


@router.get("/expenses", summary="List expenses (filterable)")
async def list_expenses(
    category: str | None = Query(default=None, max_length=100),
    payment_method: str | None = Query(default=None, max_length=100),
    q: str | None = Query(default=None, max_length=200, description="Search text"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=2000),
    _: None = Depends(require_api_key),
    collection: AsyncCollection = Depends(get_collection),
) -> dict:
    query: dict = {}
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
    return {"success": True, "count": len(docs), "expenses": [_to_json(d) for d in docs]}


@router.delete("/expenses/{expense_id}", summary="Delete an expense")
async def delete_expense(
    expense_id: str,
    _: None = Depends(require_api_key),
    collection: AsyncCollection = Depends(get_collection),
) -> dict:
    try:
        oid = ObjectId(expense_id)
    except (InvalidId, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid expense id")
    try:
        result = await collection.delete_one({"_id": oid})
    except PyMongoError:
        log.exception("delete failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    return {"success": True, "message": "Expense deleted"}

import logging
from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import PyMongoError

from ..config import settings
from ..database import get_collection
from ..models.expense import ExpenseCreated, ExpenseIn, utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["expenses"])


def require_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    if not compare_digest(x_api_key, settings.shortcut_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")


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

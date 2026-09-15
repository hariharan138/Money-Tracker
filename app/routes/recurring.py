"""Recurring expense rules: rent, subscriptions, anything retyped every month.

A rule never renders itself. The catch-up below writes real documents into the
expenses collection, so recurring spend flows through every existing filter,
total, chart and budget with no special-casing anywhere else.

Materialisation is pulled, not pushed: it runs when the owner's expenses are
read. Render's free tier stops the process when idle, so a scheduler inside it
would silently miss exactly the windows it was meant to cover — and the
keep-alive cannot be relied on to hold the instance up forever either. Pulling
means a rule catches up the moment anyone looks, which is when it matters.
"""
import logging
from datetime import date, datetime

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..database import get_collection, get_recurring_collection
from ..models.expense import utcnow
from ..models.recurring import (
    RecurringIn,
    RecurringUpdate,
    as_datetime,
    occurrence_key,
    occurrences,
    today_utc,
)
from .auth import resolve_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["recurring"])

# One person's rules, bounded so a runaway account cannot make every dashboard
# load unbounded work.
MAX_RULES = 100

# Fields copied verbatim from a rule onto each expense it generates.
_COPIED = ("amount", "category", "description", "payment_method", "notes")


def _as_date(value) -> date | None:
    """Mongo hands back datetimes; the calendar maths works in dates."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _next_run(rule: dict) -> date | None:
    """The date this rule fires next, for the UI. None once it has ended."""
    if not rule.get("active", True):
        return None
    start = _as_date(rule.get("start_date"))
    if start is None:
        return None
    end = _as_date(rule.get("end_date"))
    last = _as_date(rule.get("last_occurrence"))
    # look one window ahead of today rather than behind it
    horizon = date.fromordinal(today_utc().toordinal() + 366)
    upcoming = occurrences(
        rule.get("frequency", "monthly"), start, horizon,
        after=last or date.fromordinal(today_utc().toordinal() - 1),
        end=end, cap=1,
    )
    return upcoming[0] if upcoming else None


def _to_json(rule: dict) -> dict:
    next_run = _next_run(rule)
    return {
        "id": str(rule["_id"]),
        "amount": rule.get("amount", 0),
        "category": rule.get("category", ""),
        "description": rule.get("description"),
        "payment_method": rule.get("payment_method"),
        "notes": rule.get("notes"),
        "frequency": rule.get("frequency", "monthly"),
        "start_date": d.isoformat() if (d := _as_date(rule.get("start_date"))) else None,
        "end_date": d.isoformat() if (d := _as_date(rule.get("end_date"))) else None,
        "last_occurrence": d.isoformat() if (d := _as_date(rule.get("last_occurrence"))) else None,
        "next_run": next_run.isoformat() if next_run else None,
        "active": bool(rule.get("active", True)),
    }


async def _materialise(
    rule: dict, until: date, rules: AsyncCollection, expenses: AsyncCollection
) -> int:
    """Insert the occurrences this rule owes up to `until`. Returns how many
    were created."""
    start = _as_date(rule.get("start_date"))
    if start is None:
        return 0
    due = occurrences(
        rule.get("frequency", "monthly"), start, until,
        after=_as_date(rule.get("last_occurrence")),
        end=_as_date(rule.get("end_date")),
    )
    if not due:
        return 0

    created = 0
    done: date | None = None
    for day in due:
        doc = {key: rule.get(key) for key in _COPIED}
        doc.update(
            date=as_datetime(day),
            created_at=utcnow(),
            user=rule["user"],
            recurring_id=rule["_id"],
            # unique-indexed with recurring_id: the database, not a
            # read-then-write, is what stops a double insert
            occurrence_key=occurrence_key(day),
        )
        try:
            await expenses.insert_one(doc)
            created += 1
        except DuplicateKeyError:
            pass  # a concurrent read already materialised this one
        except PyMongoError:
            log.exception("recurring: could not insert occurrence %s", day)
            break  # leave last_occurrence short so the next read retries
        done = day

    if done is not None:
        try:
            await rules.update_one(
                {"_id": rule["_id"]},
                {"$set": {"last_occurrence": as_datetime(done), "updated_at": utcnow()}},
            )
        except PyMongoError:
            # The expenses exist; the cursor did not move. The unique index
            # makes the retry harmless.
            log.exception("recurring: could not advance last_occurrence")
    return created


async def catch_up(user: str, rules: AsyncCollection, expenses: AsyncCollection) -> int:
    """Bring one user's recurring expenses up to date. Never raises: a broken
    rule must not stop someone reading the expenses they already have."""
    try:
        rule_docs = await rules.find({"user": user, "active": True}).to_list(MAX_RULES)
    except PyMongoError:
        log.exception("recurring: could not read rules")
        return 0

    today = today_utc()
    created = 0
    for rule in rule_docs:
        try:
            created += await _materialise(rule, today, rules, expenses)
        except Exception:  # one malformed rule shouldn't take the others down
            log.exception("recurring: rule %s failed to materialise", rule.get("_id"))
    if created:
        log.info("recurring: created %s expense(s) for %s", created, user)
    return created


@router.get("/recurring", summary="List MY recurring rules")
async def list_recurring(
    user: str = Depends(resolve_user),
    rules: AsyncCollection = Depends(get_recurring_collection),
) -> dict:
    try:
        docs = await rules.find({"user": user}).to_list(MAX_RULES)
    except PyMongoError:
        log.exception("list recurring failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    # active first, then soonest
    docs.sort(key=lambda d: (not d.get("active", True), str(_as_date(d.get("start_date")))))
    return {"success": True, "count": len(docs), "recurring": [_to_json(d) for d in docs]}


@router.post("/recurring", status_code=status.HTTP_201_CREATED, summary="Add a recurring rule")
async def create_recurring(
    payload: RecurringIn = Body(...),
    user: str = Depends(resolve_user),
    rules: AsyncCollection = Depends(get_recurring_collection),
    expenses: AsyncCollection = Depends(get_collection),
) -> dict:
    try:
        count = await rules.count_documents({"user": user})
    except PyMongoError:
        log.exception("create recurring failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if count >= MAX_RULES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"You already have {MAX_RULES} recurring rules"
        )

    rule = payload.model_dump()
    # pymongo cannot encode a bare date
    rule["start_date"] = as_datetime(payload.start_date)
    rule["end_date"] = as_datetime(payload.end_date) if payload.end_date else None
    rule.update(user=user, active=True, last_occurrence=None, created_at=utcnow())
    try:
        result = await rules.insert_one(rule)
    except PyMongoError:
        log.exception("create recurring failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")

    # Run it straight away, so a rule starting today shows its first expense
    # without waiting for the next poll.
    rule["_id"] = result.inserted_id
    created = await _materialise(rule, today_utc(), rules, expenses)
    fresh = await rules.find_one({"_id": result.inserted_id}) or rule
    return {"success": True, "created_expenses": created, "recurring": _to_json(fresh)}


@router.patch("/recurring/{rule_id}", summary="Update one of MY recurring rules")
async def update_recurring(
    rule_id: str,
    payload: RecurringUpdate = Body(...),
    user: str = Depends(resolve_user),
    rules: AsyncCollection = Depends(get_recurring_collection),
) -> dict:
    try:
        oid = ObjectId(rule_id)
    except (InvalidId, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid recurring id")

    # exclude_unset, so omitting a field leaves it alone instead of nulling it
    changes = payload.model_dump(exclude_unset=True)
    if "end_date" in changes:
        changes["end_date"] = as_datetime(changes["end_date"]) if changes["end_date"] else None
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    changes["updated_at"] = utcnow()

    try:
        # ownership is part of the filter: another user's rule is a 404
        updated = await rules.find_one_and_update(
            {"_id": oid, "user": user}, {"$set": changes}, return_document=True
        )
    except PyMongoError:
        log.exception("update recurring failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recurring rule not found")
    return {"success": True, "recurring": _to_json(updated)}


@router.delete("/recurring/{rule_id}", summary="Delete one of MY recurring rules")
async def delete_recurring(
    rule_id: str,
    purge: bool = Query(
        default=False,
        description="Also delete the expenses this rule already created",
    ),
    user: str = Depends(resolve_user),
    rules: AsyncCollection = Depends(get_recurring_collection),
    expenses: AsyncCollection = Depends(get_collection),
) -> dict:
    try:
        oid = ObjectId(rule_id)
    except (InvalidId, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid recurring id")
    try:
        result = await rules.delete_one({"_id": oid, "user": user})
    except PyMongoError:
        log.exception("delete recurring failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recurring rule not found")

    # Past occurrences are real spending that really happened, so they stay
    # by default. Deleting them is opt-in.
    removed = 0
    if purge:
        try:
            purged = await expenses.delete_many({"recurring_id": oid, "user": user})
            removed = purged.deleted_count
        except PyMongoError:
            log.exception("purge recurring expenses failed")
    return {
        "success": True,
        "message": "Recurring rule deleted",
        "deleted_expenses": removed,
    }

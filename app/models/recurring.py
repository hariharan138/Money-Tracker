"""Recurring expense rules, and the calendar maths that turns one into dates.

A rule stores *intent* ("₹18,000 rent, monthly, from the 5th"); the expenses
it implies are written into the normal expenses collection by the catch-up in
routes/recurring.py, so every existing query, filter, total and chart sees
them with no special-casing.

The date generation lives here, separate from Mongo, because it is the part
with the edge cases worth testing directly: a monthly rule anchored on the
31st, a rule whose start date is months in the past, a rule that ended.
"""
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Frequency = Literal["daily", "weekly", "monthly"]

# One catch-up run materialises at most this many occurrences per rule. A rule
# back-dated two years would otherwise insert 730 documents inside a single
# dashboard load; instead it fills in a window at a time and converges over
# the next few loads.
MAX_CATCHUP = 60

# Occurrences are written at noon UTC, not midnight. The dashboard groups by
# *local* calendar day, so a midnight-UTC timestamp would show up on the
# previous day for anyone west of UTC. Noon keeps the intended date intact
# either side of UTC.
OCCURRENCE_HOUR = 12


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def as_datetime(day: date) -> datetime:
    """The timestamp an occurrence on `day` is stored with."""
    return datetime.combine(day, time(OCCURRENCE_HOUR), tzinfo=timezone.utc)


def occurrence_key(day: date) -> str:
    """Stable per-rule identity for one occurrence, unique-indexed alongside
    recurring_id so two concurrent catch-ups cannot both insert it."""
    return day.isoformat()


def _add_months(anchor: date, months: int) -> date:
    """Shift by whole months, keeping the anchor day where the target month is
    long enough. A rule anchored on the 31st runs Jan 31, Feb 28, Mar 31 —
    clamped, never drifted permanently to the 28th."""
    index = anchor.year * 12 + (anchor.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(anchor.day, monthrange(year, month)[1]))


def occurrences(
    frequency: Frequency,
    start: date,
    until: date,
    *,
    after: date | None = None,
    end: date | None = None,
    cap: int = MAX_CATCHUP,
) -> list[date]:
    """Dates a rule fires on, in order, within (after, until].

    `after` is the last date already materialised, so it is excluded; `end` is
    the rule's own optional last day. Returns at most `cap` dates — the caller
    records the last one and picks up from there next time.
    """
    if end is not None and end < until:
        until = end
    if until < start:
        return []

    due: list[date] = []
    step = 0
    while len(due) < cap:
        if frequency == "daily":
            day = start + timedelta(days=step)
        elif frequency == "weekly":
            day = start + timedelta(weeks=step)
        else:
            day = _add_months(start, step)
        step += 1
        if day > until:
            break
        if after is None or day > after:
            due.append(day)
    return due


class RecurringIn(BaseModel):
    """What the dashboard posts to create a rule."""

    amount: float = Field(gt=0)
    category: str = Field(min_length=1, max_length=100)
    frequency: Frequency
    description: str | None = Field(default=None, max_length=500)
    payment_method: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    # Also the anchor: a monthly rule starting on the 5th runs on the 5th.
    start_date: date = Field(default_factory=today_utc)
    end_date: date | None = None

    @field_validator("category", "description", "payment_method", "notes", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        return v.strip() or None if isinstance(v, str) else v

    @field_validator("payment_method")
    @classmethod
    def _normalise_payment_method(cls, v):
        """Same two methods the one-off expense form offers."""
        if v is None:
            return None
        methods = {"cash": "Cash", "upi": "UPI"}
        try:
            return methods[v.lower()]
        except (AttributeError, KeyError):
            raise ValueError("payment_method must be Cash or UPI")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _blank_date_to_none(cls, v):
        # the dashboard sends "" for an untouched date input
        return None if v in ("", None) else v

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class RecurringUpdate(BaseModel):
    """Every field optional: the UI edits one thing at a time (usually just
    pausing a rule), and an absent field must mean "leave it alone" rather
    than "set it to null"."""

    amount: float | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    frequency: Frequency | None = None
    active: bool | None = None
    end_date: date | None = None

    @field_validator("end_date", mode="before")
    @classmethod
    def _blank_date_to_none(cls, v):
        return None if v in ("", None) else v

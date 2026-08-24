from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is in UTC timezone."""
    if dt.tzinfo is None:
        # Assume naive datetimes are UTC
        return dt.replace(tzinfo=timezone.utc)
    # Convert to UTC if it has a different timezone
    return dt.astimezone(timezone.utc)


class ExpenseIn(BaseModel):
    """What the Shortcut posts."""

    amount: float = Field(gt=0, description="Must be greater than 0")
    category: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    date: datetime = Field(default_factory=utcnow, description="Defaults to server time")
    payment_method: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("date", mode="before")
    @classmethod
    def _date_or_now(cls, v):
        # Shortcuts sends "" or null when a Magic Variable is empty.
        if v in (None, ""):
            return utcnow()
        # Ensure the date is in UTC
        if isinstance(v, datetime):
            return ensure_utc(v)
        # If it's a string, parse it and ensure UTC
        try:
            parsed = datetime.fromisoformat(v.replace('Z', '+00:00'))
            return ensure_utc(parsed)
        except (ValueError, AttributeError):
            return utcnow()

    @field_validator("category", "description", "payment_method", "notes", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        return v.strip() or None if isinstance(v, str) else v


class ExpenseCreated(BaseModel):
    success: bool = True
    message: str = "Expense added successfully"
    expense_id: str

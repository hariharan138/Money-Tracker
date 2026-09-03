"""Username + password accounts, stored in Mongo, living alongside the
env-configured API keys the iPhone Shortcut already uses.

No new dependencies: hashlib.scrypt is the stdlib password KDF, and a session
is just a random token with a TTL index on its expiry.
"""
import hashlib
import logging
import secrets
from datetime import timedelta, timezone
from secrets import compare_digest

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..config import all_users
from ..database import get_sessions_collection, get_users_collection
from ..models.expense import utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_DAYS = 30
# RFC 7914 §2's interactive-login parameters (~25ms, ~16 MB per hash).
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = str(stored).split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    except ValueError:
        return False
    return compare_digest(actual.hex(), digest_hex)


# Hashed on a wrong username too, so "no such user" and "wrong password" cost
# the same and can't be told apart by timing.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class Credentials(BaseModel):
    # the username is also the value every expense is scoped by, so keep it to
    # characters that read back cleanly in the UI
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)


def _normalise(username: str) -> str:
    """Stored and compared lowercase, so Hari and hari can't become two people
    who then also can't see each other's expenses."""
    return username.strip().lower()


def _fresh(session: dict) -> bool:
    """The TTL index reaps expired sessions roughly once a minute, so a token
    can outlive its expiry by up to that long unless it's checked here too."""
    expires = session.get("expires_at")
    if expires is None:
        return False
    if expires.tzinfo is None:  # pymongo hands back naive UTC
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > utcnow()


async def _issue_session(sessions: AsyncCollection, account: dict) -> dict:
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(days=SESSION_DAYS)
    await sessions.insert_one(
        {"token": token, "username": account["username"], "expires_at": expires}
    )
    return {
        "success": True,
        "token": token,
        "expires_at": expires.isoformat(),
        "username": account["username"],
        # the account's own Shortcut key: the phone can't run a login flow
        "api_key": account["api_key"],
    }


async def resolve_user(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    # browsers can't set headers on a plain link, so the view passes ?key=
    key: str = Query(default=""),
    users: AsyncCollection = Depends(get_users_collection),
    sessions: AsyncCollection = Depends(get_sessions_collection),
) -> str:
    """Any valid credential authenticates; returns the name it scopes to.

    Three kinds, cheapest first: an env-configured Shortcut key, a login
    session token, or a registered account's own API key."""
    supplied = x_api_key if x_api_key else key
    if supplied:
        # compare on bytes: compare_digest raises on non-ASCII str, which would
        # turn a junk key into a 500 instead of a clean 401.
        candidate = supplied.encode()
        for api_key, name in all_users().items():
            if compare_digest(candidate, api_key.encode()):
                return name
        try:
            session = await sessions.find_one({"token": supplied})
            if session and _fresh(session):
                return session["username"]
            account = await users.find_one({"api_key": supplied})
            if account:
                return account["username"]
        except PyMongoError:
            log.exception("credential lookup failed")
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database error")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="Create an account")
async def register(
    payload: Credentials = Body(...),
    users: AsyncCollection = Depends(get_users_collection),
    sessions: AsyncCollection = Depends(get_sessions_collection),
) -> dict:
    username = _normalise(payload.username)
    # Expenses are scoped by this exact string, so an account that reuses an
    # env user's name would silently share that person's data.
    if username in {name.lower() for name in all_users().values()}:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken")
    account = {
        "username": username,
        "password_hash": hash_password(payload.password),
        "api_key": secrets.token_urlsafe(32),
        "created_at": utcnow(),
    }
    try:
        await users.insert_one(account)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken")
    except PyMongoError:
        log.exception("register failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return await _issue_session(sessions, account)


@router.post("/login", summary="Log in")
async def login(
    payload: Credentials = Body(...),
    users: AsyncCollection = Depends(get_users_collection),
    sessions: AsyncCollection = Depends(get_sessions_collection),
) -> dict:
    try:
        account = await users.find_one({"username": _normalise(payload.username)})
    except PyMongoError:
        log.exception("login failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    stored = account["password_hash"] if account else _DUMMY_HASH
    # ponytail: no attempt throttling. scrypt caps this at ~40 guesses/sec per
    # core, but there are two Render instances and no shared counter — add a
    # Mongo-backed attempt log here if this ever faces the open internet.
    if not verify_password(payload.password, stored) or account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    return await _issue_session(sessions, account)


@router.post("/logout", summary="End this session")
async def logout(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    key: str = Query(default=""),
    sessions: AsyncCollection = Depends(get_sessions_collection),
) -> dict:
    supplied = x_api_key if x_api_key else key
    if supplied:
        try:
            await sessions.delete_one({"token": supplied})
        except PyMongoError:
            log.exception("logout failed")
    # never 404: the caller wanted the token gone and it is
    return {"success": True, "message": "Logged out"}


@router.get("/me", summary="Who am I, and what key does my Shortcut need")
async def me(
    user: str = Depends(resolve_user),
    users: AsyncCollection = Depends(get_users_collection),
) -> dict:
    try:
        account = await users.find_one({"username": user})
    except PyMongoError:
        log.exception("me failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")
    return {
        "success": True,
        "username": user,
        # env-configured users have no account row; they already hold their key
        "account": account is not None,
        "api_key": account["api_key"] if account else None,
    }

"""HTML dashboard of the expenses. The page lives in app/static/index.html;
this route injects your expenses as JSON into it (the __BOOTSTRAP__ marker)
and serves the result. All filtering/rendering happens client-side."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pymongo.asynchronous.collection import AsyncCollection

from ..config import settings
from ..database import get_collection, get_recurring_collection
from .expenses import _to_json, resolve_user, user_scope
from .recurring import catch_up

router = APIRouter(tags=["view"])

INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


@router.get("/", summary="View MY expenses")
async def view_expenses(
    # any valid user key opens the dashboard — but only that user's expenses
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_collection),
    rules: AsyncCollection = Depends(get_recurring_collection),
) -> Response:
    # same catch-up as GET /api/expenses, so the legacy dashboard does not
    # show a stale picture that the app would then fill in
    await catch_up(user, rules, collection)
    docs = await collection.find(user_scope(user)).sort("date", -1).to_list(500)
    bootstrap = json.dumps(
        [_to_json(d) for d in docs], ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")  # can't break out of the <script> block
    # re-read each request: tweak index.html and just refresh, no restart needed
    html_content = INDEX.read_text(encoding="utf-8")
    html_content = html_content.replace("__BOOTSTRAP__", bootstrap)
    # Inject environment-specific poll interval
    poll_interval = settings.frontend_poll_interval_ms
    html_content = html_content.replace(
        "let pollInterval=300000;", 
        f"let pollInterval={poll_interval};"
    )
    return Response(
        content=html_content,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

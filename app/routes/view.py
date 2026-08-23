"""HTML dashboard of the expenses. The page lives in app/static/index.html;
this route injects your expenses as JSON into it (the __BOOTSTRAP__ marker)
and serves the result. All filtering/rendering happens client-side."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pymongo.asynchronous.collection import AsyncCollection

from ..config import settings
from ..database import get_collection
from .expenses import _to_json, resolve_user, user_scope

router = APIRouter(tags=["view"])

INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


@router.get("/", response_class=HTMLResponse, summary="View MY expenses")
async def view_expenses(
    # any valid user key opens the dashboard — but only that user's expenses
    user: str = Depends(resolve_user),
    collection: AsyncCollection = Depends(get_collection),
) -> HTMLResponse:
    docs = await collection.find(user_scope(user)).sort("date", -1).to_list(500)
    bootstrap = json.dumps(
        [_to_json(d) for d in docs], ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")  # can't break out of the <script> block
    # re-read each request: tweak index.html and just refresh, no restart needed
    return HTMLResponse(
        INDEX.read_text(encoding="utf-8").replace("__BOOTSTRAP__", bootstrap),
        # without this Safari serves the cached page on the reload
        headers={"Cache-Control": "no-store"},
    )

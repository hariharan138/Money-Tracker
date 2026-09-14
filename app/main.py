import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from .database import lifespan as db_lifespan
from .keepalive import keepalive
from .routes.auth import router as auth_router
from .routes.expenses import router
from .routes.limits import router as limits_router
from .routes.profiles import router as profiles_router
from .routes.view import router as view_router
from .config import cors_origins, settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Mongo first, then the self-pinger: there is no point holding an
    instance awake that could not serve a request anyway. The keep-alive is
    stopped on the way out so shutdown never races an in-flight ping."""
    async with db_lifespan(app):
        keepalive.start()
        try:
            yield
        finally:
            await keepalive.stop()


# Log environment on startup
if settings.environment == "production":
    logging.info("Running in PRODUCTION mode - optimized for Render.com")
else:
    logging.info("Running in DEVELOPMENT mode")

app = FastAPI(
    title="Expense API",
    description="Minimal expense logger for the iPhone Shortcuts app.",
    version="1.0.0",
    lifespan=lifespan,
    # Optimize for faster cold starts on Render.com
    docs_url=None,  # Disable automatic docs to speed up startup
    redoc_url=None,  # Disable ReDoc to speed up startup
)

# The dashboard can be deployed as a static site on a different domain.  Keep
# this opt-in so an API isn't unintentionally exposed to every browser origin.
_cors_origins = cors_origins()
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

app.include_router(auth_router)
app.include_router(router)
app.include_router(limits_router)
app.include_router(profiles_router)
app.include_router(view_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """FastAPI defaults to 422; the spec (and Shortcuts) want a plain 400."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"success": False, "message": "Invalid input", "errors": jsonable_encoder(exc.errors())},
    )


@app.get("/health", tags=["meta"])
async def health():
    """Lightweight health check for monitoring and load balancers.
    Returns minimal JSON with no caching to ensure fresh status."""
    return Response(
        content='{"status":"ok"}',
        media_type="application/json",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Response-Time": "fast"
        }
    )


@app.get("/ping", tags=["meta"])
async def ping():
    """Keep-alive endpoint. Hitting it is the whole point: any inbound request
    resets Render's 15-minute idle timer, so this one is deliberately cheap —
    no database, no disk, no auth.

    Two callers are expected, and running both is the reliable setup:
      - the in-process keep-alive (KEEPALIVE_ENABLED), which holds an awake
        instance awake but cannot wake a stopped one;
      - an external pinger (cronjob.org, a Render Cron Job, an uptime monitor)
        on `*/<CRONJOB_PING_INTERVAL_MINUTES> * * * *`, which can.

    The response reports the self-pinger's state so a deploy can be verified
    with one curl. Disable the route with ENABLE_CRONJOB_PING=false.
    """
    if not settings.enable_cronjob_ping:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ping endpoint disabled")
    body = {
        "status": "awake",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # what an external cron should be set to, so the value is discoverable
        # from the deployed service instead of only from the docs
        "recommended_external_interval_minutes": settings.cronjob_ping_interval_minutes,
        "keepalive": keepalive.status(),
    }
    return Response(
        content=json.dumps(body),
        media_type="application/json",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/warmup", tags=["meta"])
async def warmup():
    """Warmup endpoint to trigger cold start before user requests.
    Call this immediately after the /ping endpoint to ensure database is ready.
    This helps reduce perceived cold start time for users."""
    try:
        # Trigger database connection to warm it up
        from .database import get_collection
        collection = get_collection()
        # Just check connection with a simple count
        await collection.estimated_document_count()
        return Response(
            content='{"status":"warmed","ready":true}',
            media_type="application/json",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    except Exception:
        # never echo the exception: pymongo puts the Atlas hostnames (and this
        # endpoint needs no API key) straight into its error messages.
        logging.exception("warmup failed")
        return Response(
            content='{"status":"warming","ready":false}',
            media_type="application/json",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )


_STATIC = Path(__file__).parent / "static"

@app.get("/icon-180.png", include_in_schema=False, tags=["meta"])
async def icon_180() -> FileResponse:
    return FileResponse(_STATIC / "icon-180.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400, immutable"})

@app.get("/icon-167.png", include_in_schema=False, tags=["meta"])
async def icon_167() -> FileResponse:
    return FileResponse(_STATIC / "icon-167.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400, immutable"})

@app.get("/icon-152.png", include_in_schema=False, tags=["meta"])
async def icon_152() -> FileResponse:
    return FileResponse(_STATIC / "icon-152.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400, immutable"})

@app.get("/favicon.png", include_in_schema=False, tags=["meta"])
async def favicon() -> FileResponse:
    return FileResponse(_STATIC / "favicon.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400, immutable"})

@app.get("/index.html", include_in_schema=False, tags=["meta"])
async def static_index() -> FileResponse:
    """Serve the static index.html for direct access without authentication.
    This is useful for health checks and basic endpoint verification."""
    return FileResponse(_STATIC / "index.html", media_type="text/html",
                        headers={"Cache-Control": "public, max-age=60"})

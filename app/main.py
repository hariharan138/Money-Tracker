import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response

from .database import lifespan
from .routes.expenses import router
from .routes.view import router as view_router
from .config import settings

logging.basicConfig(level=logging.INFO)

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
app.include_router(router)
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
    """Lightweight keep-alive endpoint for cronjob.org to prevent Render.com sleep.
    
    CRONJOB.ORG SETUP:
    - URL: https://your-app.onrender.com/ping
    - Schedule: Every 4 minutes (cron: */4 * * * *)
    - This keeps the server awake by pinging before the 15-minute timeout
    
    Only enabled in production via ENABLE_CRONJOB_PING setting."""
    if not settings.enable_cronjob_ping:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ping endpoint disabled")
    return Response(
        content=f'{{"status":"awake","timestamp":"{datetime.now(timezone.utc).isoformat()}"}}',
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
    except Exception as e:
        return Response(
            content=f'{{"status":"warming","ready":false,"error":"{str(e)}"}}',
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

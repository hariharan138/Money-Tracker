import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .database import lifespan
from .routes.expenses import router
from .routes.view import router as view_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Expense API",
    description="Minimal expense logger for the iPhone Shortcuts app.",
    version="1.0.0",
    lifespan=lifespan,
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
    return {"status": "ok"}

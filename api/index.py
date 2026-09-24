"""Vercel serverless entrypoint.

Vercel's Python runtime looks for a module-level ASGI/WSGI object named
`app` in every file under `api/` and wraps it as a serverless function.
`vercel.json` rewrites every path to this function, so the FastAPI app
below (unchanged) handles routing exactly as it does under `uvicorn`.
"""
from app.main import app  # noqa: F401

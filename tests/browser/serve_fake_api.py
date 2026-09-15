"""Run the real API with in-memory collections, for browser end-to-end tests."""
import os

os.environ.update(
    MONGODB_URI="mongodb://localhost:27017",
    SHORTCUT_API_KEY="e2e-test-key",
    DEFAULT_USER="Hari",
    CORS_ORIGINS="http://127.0.0.1:8125",
)

import contextlib, uvicorn                                   # noqa: E402
# Importing test_api installs its in-memory dependency overrides on the app.
from test_api import FakeMongo                                # noqa: E402
from app import main as app_main                              # noqa: E402
from app.database import (                                    # noqa: E402
    get_collection, get_limits_collection, get_profiles_collection,
    get_recurring_collection,
)

# One instance each, created here rather than inside the lambdas: a
# `lambda: FakeMongo()` builds a fresh empty collection per request, so a
# write lands in a throwaway and every read comes back empty.
expenses = FakeMongo("recurring_id", "occurrence_key")
rules = FakeMongo()
limits = FakeMongo()
profiles = FakeMongo()
app_main.app.dependency_overrides[get_collection] = lambda: expenses
app_main.app.dependency_overrides[get_recurring_collection] = lambda: rules
app_main.app.dependency_overrides[get_limits_collection] = lambda: limits
app_main.app.dependency_overrides[get_profiles_collection] = lambda: profiles


@contextlib.asynccontextmanager
async def no_mongo(_app):
    yield


app_main.db_lifespan = no_mongo
uvicorn.run(app_main.app, host="127.0.0.1", port=8124, log_level="warning")

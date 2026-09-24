"""Self-ping keep-alive for Render's free tier.

Render spins a free web service down after ~15 minutes with no *inbound* HTTP
traffic.  A request the process makes to its own public URL leaves the
container, reaches Render's router and comes back in, so it counts as inbound
traffic and holds the spin-down timer open.

The limit of the trick, stated plainly: a process that has already been
stopped cannot ping anything.  Self-pinging keeps an awake instance awake; only
an outside caller (cronjob.org, a Render Cron Job, another host) can *wake* a
sleeping one.  Run both — see KEEP_AWAKE_GUIDE.md — they cover each other's gap
and neither costs anything.

Everything here is opt-in (KEEPALIVE_ENABLED) and runs in one background task
that owns nothing the request path touches, so a failing ping can only ever
produce a log line.
"""
import asyncio
import logging
import os
import random

import httpx

from .config import settings

log = logging.getLogger(__name__)

# Render injects this: the service's own public https URL, e.g.
# "https://expenses-api.onrender.com".  It means a Render deploy needs no
# KEEPALIVE_URL of its own.
RENDER_URL_ENV = "RENDER_EXTERNAL_URL"

# Render's spin-down window.  Pinging at or past it is a coin flip, so the
# configured interval is clamped below it.
SPIN_DOWN_MINUTES = 15
MIN_INTERVAL_MINUTES = 1.0
MAX_INTERVAL_MINUTES = 14.0

# Generous: the point is to survive a slow cold start, not to be quick.
REQUEST_TIMEOUT_S = 30.0
# Each interval is spent between 85% and 100% of the way through, so two
# instances of the same service drift apart instead of pinging in lockstep.
_JITTER = (0.85, 1.0)


def target_url() -> str:
    """Absolute URL to ping, or "" when there is nothing to ping.

    KEEPALIVE_URL wins; otherwise Render's own RENDER_EXTERNAL_URL is used, so
    the common deploy needs no extra configuration.
    """
    base = (settings.keepalive_url or os.getenv(RENDER_URL_ENV, "")).strip()
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"  # Render sets a bare host in some runtimes
    path = settings.keepalive_path.strip() or "/ping"
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def interval_seconds() -> float:
    """The configured interval, clamped to something that actually works."""
    wanted = float(settings.keepalive_interval_minutes)
    clamped = min(max(wanted, MIN_INTERVAL_MINUTES), MAX_INTERVAL_MINUTES)
    if clamped != wanted:
        log.warning(
            "KEEPALIVE_INTERVAL_MINUTES=%s is outside 1-%s (Render sleeps at %s); using %s",
            wanted, MAX_INTERVAL_MINUTES, SPIN_DOWN_MINUTES, clamped,
        )
    return clamped * 60.0


class KeepAlive:
    """Owns the background self-ping task and the counters /ping reports."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self.url = ""
        self.interval_s = 0.0
        self.pings_ok = 0
        self.pings_failed = 0
        self.last_status: int | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        """Small enough to inline in /ping's response on every call."""
        return {
            "enabled": settings.keepalive_enabled,
            "running": self.running,
            "url": self.url or None,
            "interval_minutes": round(self.interval_s / 60, 2) if self.interval_s else None,
            "pings_ok": self.pings_ok,
            "pings_failed": self.pings_failed,
            "last_status": self.last_status,
            "last_error": self.last_error,
        }

    async def ping_once(self, client: httpx.AsyncClient) -> bool:
        """One self-ping.  Swallows every failure: a keep-alive that can take
        the process down with it is worse than a sleeping instance."""
        try:
            response = await client.get(
                self.url, headers={"User-Agent": "expense-api-keepalive"}
            )
        except Exception as exc:  # httpx raises a whole family; none is fatal here
            self.pings_failed += 1
            self.last_status = None
            self.last_error = type(exc).__name__
            log.warning("keep-alive ping failed: %s", self.last_error)
            return False
        self.last_status = response.status_code
        if response.is_success:
            self.pings_ok += 1
            self.last_error = None
            log.debug("keep-alive ping ok (%s)", response.status_code)
            return True
        # A non-2xx still reached the router, so it still counted as traffic —
        # worth a warning (a 404 means KEEPALIVE_PATH is wrong) but not alarm.
        self.pings_failed += 1
        self.last_error = f"HTTP {response.status_code}"
        log.warning("keep-alive ping returned %s for %s", response.status_code, self.url)
        return False

    async def _loop(self) -> None:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_S, follow_redirects=True
        ) as client:
            while True:
                # Sleep first: this deploy just proved the instance is awake.
                await asyncio.sleep(self.interval_s * random.uniform(*_JITTER))
                await self.ping_once(client)

    def start(self) -> None:
        """Called from the app lifespan once Mongo is known to be up."""
        if os.getenv("VERCEL"):
            # Serverless: there's no 15-minute spin-down to fight, and a
            # background task can't outlive the request that started it
            # once the function suspends, so it would just leak a warning.
            log.info("keep-alive off (running on Vercel; nothing to keep alive)")
            return
        if not settings.keepalive_enabled:
            log.info("keep-alive off (set KEEPALIVE_ENABLED=true to self-ping)")
            return
        self.url = target_url()
        if not self.url:
            log.warning(
                "keep-alive on but no target: set KEEPALIVE_URL, or deploy on "
                "Render, which sets %s for you", RENDER_URL_ENV,
            )
            return
        if not settings.enable_cronjob_ping and settings.keepalive_path.strip("/") == "ping":
            log.warning(
                "keep-alive targets /ping but ENABLE_CRONJOB_PING is false, so "
                "every ping will 404; set KEEPALIVE_PATH=/health instead"
            )
        self.interval_s = interval_seconds()
        self._task = asyncio.create_task(self._loop(), name="keepalive")
        log.info(
            "keep-alive pinging %s every %.1f min", self.url, self.interval_s / 60
        )

    async def stop(self) -> None:
        """Cancel the task and wait for it, so shutdown doesn't race the ping."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        log.info("keep-alive stopped after %s ok / %s failed", self.pings_ok, self.pings_failed)


keepalive = KeepAlive()

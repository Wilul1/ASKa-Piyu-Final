"""Simple in-process rate limiter for public QA asks.

Per-process only — does not share state across uvicorn/gunicorn workers.
Nginx (Compose ``full`` profile) remains the preferred edge limiter; these
limits are the safety net when the API is exposed directly.

Guests are capped more tightly than signed-in users so anonymous Ask cannot
be used continuously against the LLM.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request

from app.models.db_models import User
from app.services.client_ip import client_ip

_HITS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = Lock()

# Signed-in users: align with deploy/nginx.conf QA zone (~30/min).
AUTH_LIMIT = 30
AUTH_WINDOW_SECONDS = 60

# Guests: a few trial questions, then sign in. Burst + hourly.
GUEST_SHORT_LIMIT = 5
GUEST_SHORT_WINDOW_SECONDS = 15 * 60
GUEST_HOUR_LIMIT = 10
GUEST_HOUR_WINDOW_SECONDS = 60 * 60

DEFAULT_WINDOW_SECONDS = 60
# Legacy aliases used by knowledge_base browse limiter.
ANON_LIMIT = GUEST_SHORT_LIMIT

GUEST_LIMIT_DETAIL = (
    "Guest question limit reached. Sign in to keep asking, "
    "or wait a bit and try again."
)
AUTH_LIMIT_DETAIL = "Too many questions. Please wait a moment and try again."
NETWORK_LIMIT_DETAIL = (
    "Too many questions from this network. Please wait a moment and try again."
)


def check_qa_rate_limit(
    key: str,
    *,
    limit: int | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    authenticated: bool = False,
    record: bool = True,
) -> bool:
    """Return True if the request is allowed, False if rate-limited.

    Anonymous callers get a tighter default limit than logged-in users.
    """
    resolved_limit = AUTH_LIMIT if authenticated else ANON_LIMIT
    if limit is not None:
        resolved_limit = limit
    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        bucket = _HITS[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= resolved_limit:
            return False
        if record:
            bucket.append(now)
        return True


def enforce_qa_rate_limit(request: Request, user: User | None) -> None:
    """Per-user (when signed in) and per-IP limits so Ask stays bounded."""
    ip = client_ip(request)
    if user is not None:
        if not check_qa_rate_limit(
            f"user:{user.id}",
            authenticated=True,
            limit=AUTH_LIMIT,
            window_seconds=AUTH_WINDOW_SECONDS,
        ):
            raise HTTPException(status_code=429, detail=AUTH_LIMIT_DETAIL)
        if not check_qa_rate_limit(
            f"ip:{ip}",
            authenticated=True,
            limit=AUTH_LIMIT,
            window_seconds=AUTH_WINDOW_SECONDS,
        ):
            raise HTTPException(status_code=429, detail=NETWORK_LIMIT_DETAIL)
        return

    short_key = f"guest:{ip}:short"
    hour_key = f"guest:{ip}:hour"
    short_ok = check_qa_rate_limit(
        short_key,
        limit=GUEST_SHORT_LIMIT,
        window_seconds=GUEST_SHORT_WINDOW_SECONDS,
        record=False,
    )
    hour_ok = check_qa_rate_limit(
        hour_key,
        limit=GUEST_HOUR_LIMIT,
        window_seconds=GUEST_HOUR_WINDOW_SECONDS,
        record=False,
    )
    if not short_ok or not hour_ok:
        raise HTTPException(
            status_code=429,
            detail=GUEST_LIMIT_DETAIL,
            headers={"Retry-After": str(GUEST_SHORT_WINDOW_SECONDS)},
        )
    check_qa_rate_limit(
        short_key,
        limit=GUEST_SHORT_LIMIT,
        window_seconds=GUEST_SHORT_WINDOW_SECONDS,
    )
    check_qa_rate_limit(
        hour_key,
        limit=GUEST_HOUR_LIMIT,
        window_seconds=GUEST_HOUR_WINDOW_SECONDS,
    )


def reset_qa_rate_limits() -> None:
    """Test helper."""
    with _LOCK:
        _HITS.clear()

"""Simple in-process rate limiter for public QA asks.

Per-process only — does not share state across uvicorn/gunicorn workers.
Nginx (Compose ``full`` profile) remains the preferred edge limiter; these
limits are the safety net when the API is exposed directly.
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

# Align with deploy/nginx.conf QA zone (~30/min) as a safety net without nginx.
AUTH_LIMIT = 30
ANON_LIMIT = 15
DEFAULT_WINDOW_SECONDS = 60


def check_qa_rate_limit(
    key: str,
    *,
    limit: int | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    authenticated: bool = False,
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
        bucket.append(now)
        return True


def enforce_qa_rate_limit(request: Request, user: User | None) -> None:
    """Per-user (when signed in) and per-IP limits so Ask stays bounded."""
    ip = client_ip(request)
    if user is not None:
        if not check_qa_rate_limit(f"user:{user.id}", authenticated=True):
            raise HTTPException(
                status_code=429,
                detail="Too many questions. Please wait a moment and try again.",
            )
        if not check_qa_rate_limit(f"ip:{ip}", authenticated=True):
            raise HTTPException(
                status_code=429,
                detail="Too many questions from this network. Please wait a moment and try again.",
            )
        return
    if not check_qa_rate_limit(f"ip:{ip}", authenticated=False):
        raise HTTPException(
            status_code=429,
            detail="Too many questions from this network. Please wait a moment and try again.",
        )


def reset_qa_rate_limits() -> None:
    """Test helper."""
    with _LOCK:
        _HITS.clear()

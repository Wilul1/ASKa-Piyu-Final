"""Simple in-process rate limiter for public ticket triage."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

# IP/key -> timestamps of recent hits
_HITS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = Lock()

DEFAULT_LIMIT = 30
DEFAULT_WINDOW_SECONDS = 60


def check_triage_rate_limit(
    key: str,
    *,
    limit: int = DEFAULT_LIMIT,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        bucket = _HITS[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def reset_triage_rate_limits() -> None:
    """Test helper."""
    with _LOCK:
        _HITS.clear()

"""In-process rate limiter for /auth/login and /auth/signup.

Limits are per-process memory. Behind multiple workers, also enforce limits at
the reverse proxy / gateway.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

_HITS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = Lock()

# Match deploy/nginx.conf auth zone (~5/min) so direct uvicorn still resists spray.
LOGIN_LIMIT = 5
SIGNUP_LIMIT = 5
DEFAULT_WINDOW_SECONDS = 60


def check_auth_rate_limit(
    key: str,
    *,
    limit: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> bool:
    """Return True if allowed, False if rate-limited."""
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


def reset_auth_rate_limits() -> None:
    """Test helper."""
    with _LOCK:
        _HITS.clear()

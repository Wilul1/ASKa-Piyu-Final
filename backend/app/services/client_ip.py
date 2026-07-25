"""Resolve client IP for in-app rate limits (works with or without nginx)."""

from __future__ import annotations

from fastapi import Request

from app.config import settings


def client_ip(request: Request) -> str:
    """Return the best-effort client IP for rate-limit keys.

    When ``ASKA_TRUST_PROXY`` is true (Compose nginx / campus reverse proxy),
    honor ``X-Forwarded-For`` / ``X-Real-IP``. Otherwise use the direct peer
    only — never trust spoofable forwarded headers on a publicly exposed API.
    """
    if bool(getattr(settings, "trust_proxy", False)):
        forwarded = (request.headers.get("x-forwarded-for") or "").strip()
        if forwarded:
            # Left-most is the original client when proxies append correctly.
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip

    if request.client and request.client.host:
        return request.client.host
    return "unknown"

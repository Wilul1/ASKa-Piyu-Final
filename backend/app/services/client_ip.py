"""Resolve client IP for in-app rate limits (works with or without nginx)."""

from __future__ import annotations

from fastapi import Request

from app.config import settings


def client_ip(request: Request) -> str:
    """Return the best-effort client IP for rate-limit keys.

    When ``ASKA_TRUST_PROXY`` is true (Compose nginx / campus reverse proxy),
    prefer ``X-Real-IP`` (set by nginx to ``$remote_addr``). Do **not** use the
    left-most ``X-Forwarded-For`` entry — clients can spoof that and bypass
    per-IP rate limits. Fall back to the right-most XFF hop (added by the
    immediate proxy) only when ``X-Real-IP`` is absent.

    When trust_proxy is false, use the direct peer only — never trust
    spoofable forwarded headers on a publicly exposed API.
    """
    if bool(getattr(settings, "trust_proxy", False)):
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip
        forwarded = (request.headers.get("x-forwarded-for") or "").strip()
        if forwarded:
            # Right-most hop is what a correctly configured proxy appends.
            hops = [part.strip() for part in forwarded.split(",") if part.strip()]
            if hops:
                return hops[-1]

    if request.client and request.client.host:
        return request.client.host
    return "unknown"

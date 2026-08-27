from types import SimpleNamespace

from fastapi import HTTPException

from app.services.qa_rate_limit import (
    AUTH_LIMIT,
    GUEST_HOUR_LIMIT,
    GUEST_LIMIT_DETAIL,
    GUEST_SHORT_LIMIT,
    check_qa_rate_limit,
    enforce_qa_rate_limit,
    reset_qa_rate_limits,
)


class _DummyRequest:
    def __init__(self, ip: str = "203.0.113.10") -> None:
        self.headers = {"x-forwarded-for": ip}
        self.client = SimpleNamespace(host=ip)


def test_guest_ask_is_blocked_after_short_window_quota():
    reset_qa_rate_limits()
    request = _DummyRequest()
    for _ in range(GUEST_SHORT_LIMIT):
        enforce_qa_rate_limit(request, None)
    try:
        enforce_qa_rate_limit(request, None)
        raise AssertionError("expected 429")
    except HTTPException as exc:
        assert exc.status_code == 429
        assert "Sign in" in str(exc.detail)


def test_guest_hourly_quota_is_enforced_even_if_short_window_would_allow():
    reset_qa_rate_limits()
    request = _DummyRequest("203.0.113.22")
    for _ in range(GUEST_HOUR_LIMIT):
        assert check_qa_rate_limit(
            "guest:203.0.113.22:hour",
            limit=GUEST_HOUR_LIMIT,
            window_seconds=3600,
        )
    try:
        enforce_qa_rate_limit(request, None)
        raise AssertionError("expected 429")
    except HTTPException as exc:
        assert exc.status_code == 429
        assert exc.detail == GUEST_LIMIT_DETAIL


def test_signed_in_user_keeps_higher_ask_quota():
    reset_qa_rate_limits()
    request = _DummyRequest("203.0.113.30")
    user = SimpleNamespace(id="student-1")
    for _ in range(GUEST_SHORT_LIMIT + 1):
        enforce_qa_rate_limit(request, user)
    assert check_qa_rate_limit(
        "user:student-1",
        authenticated=True,
        limit=AUTH_LIMIT,
        window_seconds=60,
        record=False,
    )

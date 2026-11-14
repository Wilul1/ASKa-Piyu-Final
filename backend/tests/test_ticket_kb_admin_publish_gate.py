"""Admin publication safety for incomplete ticket-derived KB drafts.

Covers both publish paths independently:
- PATCH /admin/kb/articles/{id} with publish_status=True
- POST /admin/kb/articles/{id}/publish
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import PublishedArticle
from app.services.ticket_knowledge import _COMPLETION_MARKER
from tests.db_helpers import cleanup_all_published_articles

client = TestClient(app)
ADMIN_HEADERS = {"x-admin-key": "test-admin-key"}

_COMPLETE_BODY = (
    "Full-time faculty generally carry eighteen units per semester unless an "
    "overload is approved by the campus director per the Faculty Manual."
)
_INCOMPLETE_MSG = "requires staff completion"


@pytest.fixture(autouse=True)
def _admin_key_and_cleanup(monkeypatch):
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.settings.admin_api_key",
        "test-admin-key",
    )

    def _fake_index(session, article):
        article.rag_indexed = True
        article.rag_document_id = f"faq:{article.id}"
        article.chunk_count = 1
        session.add(article)
        return 1

    monkeypatch.setattr(
        "app.services.article_rag_indexer.index_published_article",
        _fake_index,
    )
    cleanup_all_published_articles()
    yield
    cleanup_all_published_articles()


def _create_article(
    *,
    title: str,
    content: str,
    kb_origin: str = "ticket_resolution",
    source_ticket_id: str | None = None,
    needs_manual_completion: bool = False,
    published: bool = False,
) -> str:
    session = get_session_factory()()
    try:
        art = PublishedArticle(
            title=title,
            slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
            category="Faculty Policies",
            content=content,
            published=published,
            kb_origin=kb_origin,
            source_ticket_id=source_ticket_id,
            needs_manual_completion=needs_manual_completion,
            audience="both",
        )
        session.add(art)
        session.commit()
        return art.id
    finally:
        session.close()


def _get_article(article_id: str) -> PublishedArticle:
    session = get_session_factory()()
    try:
        art = session.get(PublishedArticle, article_id)
        assert art is not None
        session.expunge(art)
        return art
    finally:
        session.close()


def _complete_article(article_id: str) -> None:
    """Simulate staff finishing the draft and clearing both completion signals."""
    session = get_session_factory()()
    try:
        art = session.get(PublishedArticle, article_id)
        assert art is not None
        art.content = _COMPLETE_BODY
        art.needs_manual_completion = False
        session.add(art)
        session.commit()
    finally:
        session.close()


def _publish_dedicated(article_id: str):
    return client.post(
        f"/admin/kb/articles/{article_id}/publish",
        headers=ADMIN_HEADERS,
    )


def _publish_via_update(article_id: str, **extra):
    return client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=ADMIN_HEADERS,
        json={"publish_status": True, **extra},
    )


# --- A–C: incomplete ticket drafts stay publishable (warning-only) ---


@pytest.mark.parametrize("via", ["update", "publish"])
def test_a_flag_true_no_marker_allows_publication(via: str):
    article_id = _create_article(
        title="Ticket Draft Flag Only",
        content=_COMPLETE_BODY,
        needs_manual_completion=True,
    )
    response = (
        _publish_via_update(article_id)
        if via == "update"
        else _publish_dedicated(article_id)
    )
    assert response.status_code == 200, response.text
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False


@pytest.mark.parametrize("via", ["update", "publish"])
def test_b_marker_present_flag_false_allows_publication(via: str):
    article_id = _create_article(
        title="Ticket Draft Marker Only",
        content=f"{_COMPLETE_BODY}\n\n{_COMPLETION_MARKER}",
        needs_manual_completion=False,
    )
    response = (
        _publish_via_update(article_id)
        if via == "update"
        else _publish_dedicated(article_id)
    )
    assert response.status_code == 200, response.text
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False


@pytest.mark.parametrize("via", ["update", "publish"])
def test_c_flag_and_marker_allow_publication(via: str):
    article_id = _create_article(
        title="Ticket Draft Both Signals",
        content=f"Partial answer with enough reusable text for staff review.\n\n{_COMPLETION_MARKER}",
        needs_manual_completion=True,
    )
    response = (
        _publish_via_update(article_id)
        if via == "update"
        else _publish_dedicated(article_id)
    )
    assert response.status_code == 200, response.text
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False


# --- D–E: completed ticket drafts publish successfully ---


def test_d_completed_ticket_draft_publishes_via_update():
    article_id = _create_article(
        title="Ticket Draft Ready Update",
        content=f"{_COMPLETION_MARKER}",
        needs_manual_completion=True,
    )
    _complete_article(article_id)
    response = _publish_via_update(article_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is True
    assert body["kb_origin"] == "ticket_resolution"
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False
    assert _COMPLETION_MARKER not in (art.content or "")


def test_e_completed_ticket_draft_publishes_via_dedicated_publish():
    article_id = _create_article(
        title="Ticket Draft Ready Publish",
        content=f"{_COMPLETION_MARKER}",
        needs_manual_completion=True,
    )
    _complete_article(article_id)
    response = _publish_dedicated(article_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is True
    assert body["success"] is True
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False
    assert _COMPLETION_MARKER not in (art.content or "")


# --- F: non-ticket articles unchanged ---


@pytest.mark.parametrize("via", ["update", "publish"])
def test_f_non_ticket_article_publication_unchanged(via: str):
    article_id = _create_article(
        title="Ordinary Handbook FAQ",
        content=_COMPLETE_BODY,
        kb_origin="document",
        needs_manual_completion=False,
    )
    response = (
        _publish_via_update(article_id)
        if via == "update"
        else _publish_dedicated(article_id)
    )
    assert response.status_code == 200, response.text
    assert _get_article(article_id).published is True


def test_f_non_ticket_with_needs_review_placeholder_still_blocked():
    """Existing content-gate behavior for document articles must remain enforced."""
    article_id = _create_article(
        title="Document Needs Review",
        content="See [NEEDS REVIEW] for fee schedule details.",
        kb_origin="document",
        needs_manual_completion=False,
    )
    response = _publish_dedicated(article_id)
    assert response.status_code == 400, response.text
    assert "[NEEDS REVIEW]" in response.json()["detail"]
    assert _get_article(article_id).published is False


# --- G: draft updates without publishing remain allowed ---


def test_g_ordinary_ticket_draft_update_without_publishing_allowed():
    article_id = _create_article(
        title="Ticket Draft Edit Only",
        content=f"Stub.\n\n{_COMPLETION_MARKER}",
        needs_manual_completion=True,
    )
    new_body = f"Edited incomplete draft.\n\n{_COMPLETION_MARKER}"
    response = client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=ADMIN_HEADERS,
        json={"content": new_body, "title": "Ticket Draft Edit Only Revised"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is False
    art = _get_article(article_id)
    assert art.published is False
    assert art.needs_manual_completion is True
    assert _COMPLETION_MARKER in (art.content or "")
    assert "Edited incomplete draft" in (art.content or "")


def test_g_staff_edit_clears_stuck_incomplete_flags_when_body_is_complete():
    article_id = _create_article(
        title="Good Moral Certificate Draft",
        content=(
            "## Needs staff completion\n\n"
            "- Staff recorded a status update that does not complete the "
            "reusable Knowledge Base answer.\n\n"
            f"{_COMPLETION_MARKER}"
        ),
        needs_manual_completion=True,
    )
    session = get_session_factory()()
    try:
        art = session.get(PublishedArticle, article_id)
        art.generation_notes = "unresolved_status"
        session.add(art)
        session.commit()
    finally:
        session.close()

    completed_body = (
        "## Overview\n\n"
        "To request a Good Moral Certificate from OSAS, follow the steps below.\n\n"
        "## Requirements\n\n"
        "- Present your valid school ID and complete the OSAS request form.\n\n"
        "## Procedure\n\n"
        "1. Go to OSAS and request a Good Moral Certificate.\n"
        "2. Pay the applicable fee at the Cashier if assessed, then return the receipt.\n"
        "3. Claim the certificate on the release date given by OSAS staff.\n\n"
        "## Where to go\n\n"
        "Office of Student Affairs"
    )
    response = client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=ADMIN_HEADERS,
        json={
            "content": completed_body,
            "summary": "How to request a Good Moral Certificate from OSAS.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is False
    assert body["needs_manual_completion"] is False
    assert body.get("generation_notes") in (None, "")
    art = _get_article(article_id)
    assert art.needs_manual_completion is False
    assert art.generation_notes in (None, "")
    assert _COMPLETION_MARKER not in (art.content or "")


# --- H: existing publication validation still enforced ---


@pytest.mark.parametrize("via", ["update", "publish"])
def test_h_existing_empty_content_gate_still_enforced_on_ticket_drafts(via: str):
    article_id = _create_article(
        title="Ticket Draft Empty Body",
        content="   ",
        needs_manual_completion=False,
    )
    # Clear flag so only the pre-existing empty-content gate should fire.
    session = get_session_factory()()
    try:
        art = session.get(PublishedArticle, article_id)
        art.content = "   "
        art.needs_manual_completion = False
        session.add(art)
        session.commit()
    finally:
        session.close()

    response = (
        _publish_via_update(article_id)
        if via == "update"
        else _publish_dedicated(article_id)
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "empty" in detail.casefold()
    assert _get_article(article_id).published is False


@pytest.mark.parametrize("via", ["update", "publish"])
def test_h_existing_needs_review_placeholder_still_enforced(via: str):
    article_id = _create_article(
        title="Ticket Draft Needs Review Token",
        content="Office hours are [NEEDS REVIEW] pending registrar confirmation.",
        needs_manual_completion=False,
    )
    response = (
        _publish_via_update(article_id)
        if via == "update"
        else _publish_dedicated(article_id)
    )
    assert response.status_code == 400, response.text
    assert "[NEEDS REVIEW]" in response.json()["detail"]
    assert _get_article(article_id).published is False


# --- Bulk publish path ---


def _bulk_publish_existing(article_id: str, *, content: str | None = None):
    payload: dict = {
        "existing_article_id": article_id,
        "planner_bucket": "recommended",
        "needs_review": False,
    }
    if content is not None:
        payload["content"] = content
    return client.post(
        "/admin/kb/articles/bulk-publish",
        headers=ADMIN_HEADERS,
        json={"articles": [payload]},
    )


def test_bulk_flag_true_no_marker_allows_publication():
    article_id = _create_article(
        title="Bulk Ticket Flag Only",
        content=_COMPLETE_BODY,
        needs_manual_completion=True,
    )
    response = _bulk_publish_existing(article_id, content=_COMPLETE_BODY)
    assert response.status_code == 200, response.text
    item = response.json()["results"][0]
    assert item["success"] is True
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False


def test_bulk_marker_present_flag_false_allows_publication():
    article_id = _create_article(
        title="Bulk Ticket Marker Only",
        content=f"{_COMPLETE_BODY}\n\n{_COMPLETION_MARKER}",
        needs_manual_completion=False,
    )
    response = _bulk_publish_existing(
        article_id,
        content=f"{_COMPLETE_BODY}\n\n{_COMPLETION_MARKER}",
    )
    assert response.status_code == 200, response.text
    item = response.json()["results"][0]
    assert item["success"] is True
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False


def test_bulk_completed_ticket_draft_publishes():
    article_id = _create_article(
        title="Bulk Ticket Ready",
        content=f"{_COMPLETION_MARKER}",
        needs_manual_completion=True,
    )
    _complete_article(article_id)
    response = _bulk_publish_existing(article_id, content=_COMPLETE_BODY)
    assert response.status_code == 200, response.text
    item = response.json()["results"][0]
    assert item["success"] is True
    assert item["published"] is True
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False
    assert _COMPLETION_MARKER not in (art.content or "")


def test_bulk_non_ticket_article_publication_unchanged():
    article_id = _create_article(
        title="Bulk Ordinary Handbook FAQ",
        content=_COMPLETE_BODY,
        kb_origin="document",
        needs_manual_completion=False,
    )
    response = _bulk_publish_existing(article_id, content=_COMPLETE_BODY)
    assert response.status_code == 200, response.text
    item = response.json()["results"][0]
    assert item["success"] is True
    assert item["published"] is True
    assert _get_article(article_id).published is True


# --- Staff completion workflow (convert-to-article → admin publish) ---


def test_staff_convert_edit_clears_completion_then_admin_publish_succeeds(monkeypatch):
    """UI path: Update KB Draft → POST /tickets/{id}/convert-to-article with content.

    That service clears ``needs_manual_completion`` when staff supplies body text
    and persists the edited content (marker removed if staff deleted it). Admin
    publish must then succeed.
    """
    from datetime import datetime, timezone

    from app.models.db_models import Office, Ticket, TicketReply, User
    from app.services.passwords import hash_password
    from app.services.ticket_knowledge import (
        convert_ticket_to_draft_article,
        generate_article_from_resolved_ticket,
    )

    session = get_session_factory()()
    try:
        office_suffix = uuid.uuid4().hex[:8]
        office = Office(
            id=f"office-pubgate-{office_suffix}",
            name=f"Registrar PubGate {office_suffix}",
            description="Registrar",
        )
        session.add(office)
        session.flush()
        student = User(
            id=f"user-pg-stu-{office_suffix}",
            email=f"pg-stu-{office_suffix}@lspu.test",
            password_hash=hash_password("password123"),
            full_name="PG Student",
            role="student",
            student_id=f"2026-pg-{office_suffix}",
        )
        staff = User(
            id=f"user-pg-staff-{office_suffix}",
            email=f"pg-staff-{office_suffix}@lspu.test",
            password_hash=hash_password("password123"),
            full_name="PG Staff",
            role="office",
            office_id=office.id,
        )
        session.add_all([student, staff])
        session.flush()
        now = datetime.now(timezone.utc)
        ticket_id = f"TKT-PG-{uuid.uuid4().hex[:8].upper()}"
        ticket = Ticket(
            id=ticket_id,
            user_id=student.id,
            original_question="What is the deadline for adding a subject?",
            description="Need add/drop deadline",
            category="Registrar",
            assigned_office_id=office.id,
            assigned_office=office.name,
            priority="Medium",
            status="Resolved",
            kb_conversion_status="none",
            created_at=now,
            updated_at=now,
            resolved_at=now,
        )
        session.add(ticket)
        session.flush()
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=staff.id,
                sender_role=staff.role,
                sender_name=staff.full_name,
                message="I will check and get back to you later this week.",
                created_at=now,
            )
        )
        session.commit()

        generated = generate_article_from_resolved_ticket(
            session, ticket_id=ticket.id, actor=staff
        )
        assert generated["needs_manual_completion"] is True
        assert _COMPLETION_MARKER in (generated.get("content") or "")

        completed = convert_ticket_to_draft_article(
            session,
            ticket_id=ticket.id,
            actor=staff,
            content=(
                "Adding a subject is allowed during the first two weeks of classes. "
                "File the add/drop form at the Registrar and have your adviser sign it."
            ),
        )
        assert completed["needs_manual_completion"] is False
        assert _COMPLETION_MARKER not in (completed.get("content") or "")
        article_id = completed["article_id"]
    finally:
        session.close()

    response = _publish_dedicated(article_id)
    assert response.status_code == 200, response.text
    assert response.json()["published"] is True
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False
    assert _COMPLETION_MARKER not in (art.content or "")


# --- convert-to-article publish=true gate (A–F) ---


def _seed_convert_ticket(
    *,
    staff_message: str,
    question: str = "What is the deadline for adding a subject?",
) -> tuple[str, dict[str, str], str]:
    """Create a resolved ticket + staff user; return (ticket_id, auth_headers, staff_id)."""
    from datetime import datetime, timezone

    from app.models.db_models import Office, Ticket, TicketReply, User
    from app.services.auth import create_access_token
    from app.services.passwords import hash_password

    session = get_session_factory()()
    try:
        suffix = uuid.uuid4().hex[:8]
        office = Office(
            id=f"office-cvt-{suffix}",
            name=f"Registrar Convert {suffix}",
            description="Registrar",
        )
        session.add(office)
        session.flush()
        student = User(
            id=f"user-cvt-stu-{suffix}",
            email=f"cvt-stu-{suffix}@lspu.test",
            password_hash=hash_password("password123"),
            full_name="Convert Student",
            role="student",
            student_id=f"2026-cvt-{suffix}",
        )
        staff = User(
            id=f"user-cvt-staff-{suffix}",
            email=f"cvt-staff-{suffix}@lspu.test",
            password_hash=hash_password("password123"),
            full_name="Convert Staff",
            role="office",
            office_id=office.id,
        )
        session.add_all([student, staff])
        session.flush()
        now = datetime.now(timezone.utc)
        ticket_id = f"TKT-CVT-{suffix.upper()}"
        ticket = Ticket(
            id=ticket_id,
            user_id=student.id,
            original_question=question,
            description=question,
            category="Registrar",
            assigned_office_id=office.id,
            assigned_office=office.name,
            priority="Medium",
            status="Resolved",
            kb_conversion_status="none",
            created_at=now,
            updated_at=now,
            resolved_at=now,
        )
        session.add(ticket)
        session.flush()
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=staff.id,
                sender_role=staff.role,
                sender_name=staff.full_name,
                message=staff_message,
                created_at=now,
            )
        )
        session.commit()
        headers = {"Authorization": f"Bearer {create_access_token(staff)}"}
        return ticket_id, headers, staff.id
    finally:
        session.close()


def _convert_publish(ticket_id: str, headers: dict[str, str], **json_body):
    return client.post(
        f"/tickets/{ticket_id}/convert-to-article",
        headers=headers,
        json=json_body,
    )


def test_convert_publish_a_flag_true_no_marker_allowed():
    """keep_generation_flags path: incomplete generation + long body can still publish."""
    from app.models.db_models import User
    from app.services.ticket_knowledge import convert_ticket_to_draft_article

    ticket_id, _headers, staff_id = _seed_convert_ticket(
        staff_message="I will check and get back to you later this week.",
    )
    session = get_session_factory()()
    try:
        staff = session.get(User, staff_id)
        assert staff is not None
        payload = convert_ticket_to_draft_article(
            session,
            ticket_id=ticket_id,
            actor=staff,
            content=_COMPLETE_BODY,
            publish=True,
            keep_generation_flags=True,
        )
        assert payload["published"] is True
        art = (
            session.query(PublishedArticle)
            .filter(PublishedArticle.source_ticket_id == ticket_id)
            .one()
        )
        assert art.published is True
        assert art.needs_manual_completion is False
    finally:
        session.close()


def test_convert_publish_b_marker_present_flag_false_allowed():
    ticket_id, headers, _staff_id = _seed_convert_ticket(
        staff_message="I will check and get back to you later this week.",
    )
    response = _convert_publish(
        ticket_id,
        headers,
        title="Add/drop deadline",
        content=f"{_COMPLETE_BODY}\n\n{_COMPLETION_MARKER}",
        publish=True,
    )
    assert response.status_code == 200, response.text
    session = get_session_factory()()
    try:
        art = (
            session.query(PublishedArticle)
            .filter(PublishedArticle.source_ticket_id == ticket_id)
            .one()
        )
        assert art.published is True
        assert art.needs_manual_completion is False
    finally:
        session.close()


def test_convert_publish_c_flag_and_marker_allowed():
    ticket_id, headers, _staff_id = _seed_convert_ticket(
        staff_message="I will check and get back to you later this week.",
    )
    # Omit content so generation keeps needs_manual_completion and the marker.
    response = _convert_publish(
        ticket_id,
        headers,
        title="Add/drop deadline incomplete",
        publish=True,
    )
    assert response.status_code == 200, response.text
    session = get_session_factory()()
    try:
        art = (
            session.query(PublishedArticle)
            .filter(PublishedArticle.source_ticket_id == ticket_id)
            .one()
        )
        assert art.published is True
        assert art.needs_manual_completion is False
    finally:
        session.close()


def test_convert_publish_d_both_cleared_publishes():
    ticket_id, headers, _staff_id = _seed_convert_ticket(
        staff_message=(
            "Adding a subject is allowed during the first two weeks of classes. "
            "File the add/drop form at the Registrar and have your adviser sign it."
        ),
    )
    response = _convert_publish(
        ticket_id,
        headers,
        title="Add/drop deadline complete",
        content=(
            "Adding a subject is allowed during the first two weeks of classes. "
            "File the add/drop form at the Registrar and have your adviser sign it."
        ),
        publish=True,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is True
    assert body["needs_manual_completion"] is False
    assert _COMPLETION_MARKER not in (body.get("content") or "")
    session = get_session_factory()()
    try:
        art = (
            session.query(PublishedArticle)
            .filter(PublishedArticle.source_ticket_id == ticket_id)
            .one()
        )
        assert art.published is True
        assert art.needs_manual_completion is False
    finally:
        session.close()


def test_convert_publish_e_publish_false_draft_edit_still_works():
    ticket_id, headers, _staff_id = _seed_convert_ticket(
        staff_message="I will check and get back to you later this week.",
    )
    response = _convert_publish(
        ticket_id,
        headers,
        title="Add/drop draft only",
        content=f"Partial draft still incomplete.\n\n{_COMPLETION_MARKER}",
        publish=False,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is False
    assert body["kb_conversion_status"] in {"draft", "needs_review"}
    session = get_session_factory()()
    try:
        art = (
            session.query(PublishedArticle)
            .filter(PublishedArticle.source_ticket_id == ticket_id)
            .one()
        )
        assert art.published is False
        assert _COMPLETION_MARKER in (art.content or "")
    finally:
        session.close()


def test_convert_publish_f_non_ticket_admin_publish_unchanged():
    """Convert is ticket-only; non-ticket admin publication must stay unaffected."""
    article_id = _create_article(
        title="Non-ticket Convert Gate Control",
        content=_COMPLETE_BODY,
        kb_origin="document",
        needs_manual_completion=False,
    )
    response = _publish_dedicated(article_id)
    assert response.status_code == 200, response.text
    assert _get_article(article_id).published is True


# --- POST /admin/kb/articles update_existing_id + publish_status ---


def _create_update_existing(
    article_id: str,
    *,
    title: str,
    content: str,
    publish_status: bool,
    omit_ticket_fields: bool = True,
    **extra,
):
    payload = {
        "title": title,
        "category": "Faculty Policies",
        "content": content,
        "publish_status": publish_status,
        "update_existing_id": article_id,
        **extra,
    }
    # Explicitly omit source_ticket_id / kb_origin unless caller adds them.
    if not omit_ticket_fields:
        pass
    return client.post("/admin/kb/articles", headers=ADMIN_HEADERS, json=payload)


def _assert_draft_unchanged(
    article_id: str,
    *,
    content: str,
    needs_manual_completion: bool,
    title: str | None = None,
):
    art = _get_article(article_id)
    assert art.published is False
    assert art.needs_manual_completion is needs_manual_completion
    assert (art.content or "") == content
    if title is not None:
        assert art.title == title


def test_create_update_existing_a_flag_true_no_marker_allowed():
    article_id = _create_article(
        title="Create Update Flag Only",
        content=_COMPLETE_BODY,
        needs_manual_completion=True,
    )
    response = _create_update_existing(
        article_id,
        title="Create Update Flag Only Published",
        content=_COMPLETE_BODY,
        publish_status=True,
    )
    assert response.status_code == 200, response.text
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False
    assert art.title == "Create Update Flag Only Published"


def test_create_update_existing_b_marker_present_flag_false_allowed():
    original_content = f"{_COMPLETE_BODY}\n\n{_COMPLETION_MARKER}"
    article_id = _create_article(
        title="Create Update Marker Only",
        content=original_content,
        needs_manual_completion=False,
    )
    response = _create_update_existing(
        article_id,
        title="Create Update Marker Only Published",
        content=original_content,
        publish_status=True,
    )
    assert response.status_code == 200, response.text
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False


def test_create_update_existing_c_both_present_allowed():
    original_content = f"Partial answer with reusable office steps for staff.\n\n{_COMPLETION_MARKER}"
    article_id = _create_article(
        title="Create Update Both Signals",
        content=original_content,
        needs_manual_completion=True,
    )
    response = _create_update_existing(
        article_id,
        title="Create Update Both Signals Published",
        content=original_content,
        publish_status=True,
    )
    assert response.status_code == 200, response.text
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False


def test_create_update_existing_d_both_cleared_publishes():
    article_id = _create_article(
        title="Create Update Ready",
        content=f"{_COMPLETION_MARKER}",
        needs_manual_completion=True,
    )
    _complete_article(article_id)
    response = _create_update_existing(
        article_id,
        title="Create Update Ready Published",
        content=_COMPLETE_BODY,
        publish_status=True,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is True
    assert body["id"] == article_id
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False
    assert _COMPLETION_MARKER not in (art.content or "")
    assert art.title == "Create Update Ready Published"


def test_create_update_existing_e_publish_false_draft_update_allowed():
    article_id = _create_article(
        title="Create Update Draft Edit",
        content=f"Stub.\n\n{_COMPLETION_MARKER}",
        needs_manual_completion=True,
    )
    new_body = f"Edited incomplete draft via create-update.\n\n{_COMPLETION_MARKER}"
    response = _create_update_existing(
        article_id,
        title="Create Update Draft Edit Revised",
        content=new_body,
        publish_status=False,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is False
    art = _get_article(article_id)
    assert art.published is False
    assert art.needs_manual_completion is True
    assert "Edited incomplete draft via create-update" in (art.content or "")
    assert _COMPLETION_MARKER in (art.content or "")


def test_create_update_existing_f_non_ticket_publish_unchanged():
    article_id = _create_article(
        title="Create Update Non-ticket",
        content=_COMPLETE_BODY,
        kb_origin="document",
        needs_manual_completion=False,
    )
    response = _create_update_existing(
        article_id,
        title="Create Update Non-ticket Published",
        content=_COMPLETE_BODY,
        publish_status=True,
    )
    assert response.status_code == 200, response.text
    assert response.json()["published"] is True
    assert _get_article(article_id).published is True


def test_create_update_existing_g_detects_persisted_ticket_identity_without_request_fields():
    """Ticket identity must come from the existing row, not the request body."""
    article_id = _create_article(
        title="Create Update Persisted Identity",
        content=_COMPLETE_BODY,
        kb_origin="ticket_resolution",
        source_ticket_id=None,
        needs_manual_completion=True,
    )
    # Request intentionally omits source_ticket_id / kb_origin.
    response = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "Must Not Overwrite",
            "category": "Faculty Policies",
            "content": _COMPLETE_BODY,
            "publish_status": True,
            "update_existing_id": article_id,
        },
    )
    assert response.status_code == 200, response.text
    art = _get_article(article_id)
    assert art.published is True
    assert art.needs_manual_completion is False
    assert art.kb_origin == "ticket_resolution"

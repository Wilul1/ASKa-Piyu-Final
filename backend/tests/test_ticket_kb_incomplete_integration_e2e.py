"""Local end-to-end: incomplete ticket draft → admin API fields → complete → publish.

Sanitized fixtures only. No production writes. No Chroma (indexer mocked).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import Office, PublishedArticle, Ticket, TicketReply, User
from app.services.passwords import hash_password
from app.services.ticket_knowledge import (
    _COMPLETION_MARKER,
    convert_ticket_to_draft_article,
    generate_article_from_resolved_ticket,
)
from tests.db_helpers import cleanup_all_published_articles

client = TestClient(app)
ADMIN_HEADERS = {"x-admin-key": "test-admin-key"}


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


def _seed_ack_referral_ticket(session: Session) -> tuple[Ticket, User]:
    suffix = uuid.uuid4().hex[:8]
    office = Office(
        id=f"office-int-{suffix}",
        name=f"Registrar Integration {suffix}",
        description="Registrar",
    )
    session.add(office)
    session.flush()
    student = User(
        id=f"user-int-stu-{suffix}",
        email=f"int-stu-{suffix}@lspu.test",
        password_hash=hash_password("password123"),
        full_name="Integration Student",
        role="student",
        student_id=f"2026-INT-{suffix}",
    )
    staff = User(
        id=f"user-int-staff-{suffix}",
        email=f"int-staff-{suffix}@lspu.test",
        password_hash=hash_password("password123"),
        full_name="Integration Staff",
        role="office",
        office_id=office.id,
    )
    session.add_all([student, staff])
    session.flush()
    now = datetime.now(timezone.utc)
    ticket = Ticket(
        id=f"TKT-INT-{suffix.upper()}",
        user_id=student.id,
        original_question="How do I request a Certificate of Enrollment?",
        description="Need COE requirements and where to submit.",
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
            message=(
                "Thank you for contacting the Registrar's Office. "
                "Please check the university's current requirements with the office. "
                "You're welcome!"
            ),
            created_at=now,
        )
    )
    session.commit()
    return ticket, staff


def test_incomplete_ack_referral_workflow_api_and_completion():
    session = get_session_factory()()
    try:
        ticket, staff = _seed_ack_referral_ticket(session)

        # A–B: generate incomplete draft from acknowledgements + generic referral.
        generated = generate_article_from_resolved_ticket(
            session, ticket_id=ticket.id, actor=staff
        )
        assert generated["published"] is False
        assert generated["needs_manual_completion"] is True
        assert generated["kb_conversion_status"] == "needs_review"
        assert _COMPLETION_MARKER in (generated.get("content") or "")
        article_id = generated["article_id"]
        assert generated.get("generation_notes")
    finally:
        session.close()

    # C–D: Article Library / detail API expose completion fields.
    detail = client.get(f"/admin/kb/articles/{article_id}", headers=ADMIN_HEADERS)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["needs_manual_completion"] is True
    assert body.get("generation_notes")
    assert body["published"] is False
    assert body.get("source_ticket_id")

    listing = client.get("/admin/kb/articles", headers=ADMIN_HEADERS)
    assert listing.status_code == 200, listing.text
    match = next((row for row in listing.json() if row["id"] == article_id), None)
    assert match is not None
    assert match["needs_manual_completion"] is True
    assert match.get("generation_notes")

    # E: Save Draft remains allowed while incomplete.
    draft_save = client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=ADMIN_HEADERS,
        json={
            "content": f"{body['content']}\n\n(Staff saved draft notes.)",
            "publish_status": False,
        },
    )
    assert draft_save.status_code == 200, draft_save.text
    saved = draft_save.json()
    assert saved["published"] is False
    assert saved["needs_manual_completion"] is True

    # F: publication rejected while incomplete.
    publish = client.post(
        f"/admin/kb/articles/{article_id}/publish", headers=ADMIN_HEADERS
    )
    assert publish.status_code == 400, publish.text
    assert "completion" in publish.text.casefold() or "staff" in publish.text.casefold()

    patch_publish = client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=ADMIN_HEADERS,
        json={"publish_status": True},
    )
    assert patch_publish.status_code == 400, patch_publish.text

    # G–I: supported staff completion clears flags; publish then succeeds.
    session = get_session_factory()()
    try:
        ticket = session.get(Ticket, body["source_ticket_id"])
        staff = session.get(User, ticket.user_id)  # wrong — need office staff
        # Reload staff by office assignment on ticket replies.
        from app.models.db_models import TicketReply as TR

        reply = (
            session.query(TR)
            .filter(TR.ticket_id == ticket.id, TR.sender_role == "office")
            .first()
        )
        assert reply is not None
        staff = session.get(User, reply.sender_id)
        assert staff is not None
        completed = convert_ticket_to_draft_article(
            session,
            ticket_id=ticket.id,
            actor=staff,
            content=(
                "Submit the Certificate of Enrollment request form at the Registrar "
                "window, bring a valid ID, and pay the assessment fee at the cashier. "
                "Release is the next working day."
            ),
        )
        assert completed["needs_manual_completion"] is False
        assert _COMPLETION_MARKER not in (completed.get("content") or "")
        assert completed["published"] is False
    finally:
        session.close()

    refreshed = client.get(f"/admin/kb/articles/{article_id}", headers=ADMIN_HEADERS)
    assert refreshed.status_code == 200, refreshed.text
    done = refreshed.json()
    assert done["needs_manual_completion"] is False
    assert done["published"] is False
    assert _COMPLETION_MARKER not in (done.get("content") or "")

    publish_ok = client.post(
        f"/admin/kb/articles/{article_id}/publish", headers=ADMIN_HEADERS
    )
    assert publish_ok.status_code == 200, publish_ok.text
    assert publish_ok.json().get("published") is True

    # J: ordinary non-ticket article unaffected.
    session = get_session_factory()()
    try:
        ordinary = PublishedArticle(
            title=f"Campus library hours {uuid.uuid4().hex[:6]}",
            slug=f"campus-library-hours-{uuid.uuid4().hex[:8]}",
            category="General Information",
            content="The main library is open Monday to Friday, 8:00 AM to 5:00 PM.",
            published=False,
            kb_origin="document",
            needs_manual_completion=False,
            generation_notes=None,
            audience="both",
        )
        session.add(ordinary)
        session.commit()
        ordinary_id = ordinary.id
    finally:
        session.close()

    ordinary_resp = client.get(
        f"/admin/kb/articles/{ordinary_id}", headers=ADMIN_HEADERS
    )
    assert ordinary_resp.status_code == 200, ordinary_resp.text
    ordinary_body = ordinary_resp.json()
    assert ordinary_body["needs_manual_completion"] is False
    assert ordinary_body.get("generation_notes") in (None, "")
    assert ordinary_body.get("source_ticket_id") in (None, "")
    ordinary_publish = client.post(
        f"/admin/kb/articles/{ordinary_id}/publish", headers=ADMIN_HEADERS
    )
    assert ordinary_publish.status_code == 200, ordinary_publish.text

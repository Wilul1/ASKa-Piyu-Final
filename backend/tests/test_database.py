from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import initialize_database, safe_database_error, safe_database_url
from app.models.db_models import Office, Ticket, TicketReply, User
from app.services.passwords import hash_password, verify_password


def test_database_models_create_required_tables():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)

    tables = set(inspect(engine).get_table_names())

    assert {"users", "offices", "tickets", "ticket_replies"}.issubset(tables)


def test_ticket_foundation_models_can_persist_relationships():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)

    with Session(engine) as session:
        office = Office(name="Registrar", description=None)
        user = User(
            email="student@example.edu",
            password_hash=hash_password("correct horse battery staple"),
            full_name="Piyu Student",
            role="student",
            student_id="2026-0001",
        )
        ticket = Ticket(
            user=user,
            original_question="How can I request a copy of my TOR?",
            description="I need it for scholarship application.",
            category="Student Records",
            assigned_office="Registrar",
            priority="Medium",
            status="Open",
            confidence_score=0.75,
            source_from_chatbot=True,
        )
        reply = TicketReply(
            ticket=ticket,
            sender=user,
            sender_role="student",
            sender_name="Piyu Student",
            message="Thank you.",
        )
        session.add_all([office, user, ticket, reply])
        session.commit()

        stored_ticket = session.query(Ticket).one()

        assert stored_ticket.user.email == "student@example.edu"
        assert stored_ticket.replies[0].message == "Thank you."
        assert verify_password("correct horse battery staple", user.password_hash)
        assert not verify_password("wrong password", user.password_hash)


def test_safe_database_url_hides_password():
    safe_url = safe_database_url("postgresql+psycopg://postgres:secret-password@localhost:5432/aska_piyu")

    assert safe_url == "postgresql+psycopg://postgres:***@localhost:5432/aska_piyu"
    assert "secret-password" not in safe_url


def test_safe_database_error_hides_configured_url_password(monkeypatch):
    database_url = "postgresql+psycopg://postgres:secret-password@localhost:5432/aska_piyu"
    monkeypatch.setattr("app.db.session.settings.database_url", database_url)

    detail = safe_database_error(RuntimeError(f"Connection failed for {database_url}"))

    assert "secret-password" not in detail
    assert "postgres:***" in detail

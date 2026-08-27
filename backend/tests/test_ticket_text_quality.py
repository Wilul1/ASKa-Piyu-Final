from app.services.ticket_text_quality import (
    validate_ticket_description,
    validate_ticket_subject,
)
import pytest


def test_accepts_clear_subject_and_description():
    assert validate_ticket_subject("How can I request my TOR?")
    assert validate_ticket_description(
        "I need it for scholarship application next month."
    )


def test_rejects_keyboard_smash_description():
    with pytest.raises(ValueError, match="words|readable|characters"):
        validate_ticket_description("SIHOFDDOASFNacfcxc mjhisc k x")


def test_rejects_short_or_empty_description():
    with pytest.raises(ValueError, match="20 characters"):
        validate_ticket_description("")
    with pytest.raises(ValueError, match="20 characters"):
        validate_ticket_description("See attached")


def test_rejects_tiny_subject():
    with pytest.raises(ValueError, match="8 characters|two real words"):
        validate_ticket_subject("Help")

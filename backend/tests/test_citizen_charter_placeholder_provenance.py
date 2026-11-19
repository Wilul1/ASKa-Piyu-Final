"""Phase 6.7: placeholder-provenance tests for
citizen_charter_services.resolve_display_or_not_specified and its
propagation into build_chunks_from_charter_v2_services's chunk metadata.

Covers the exact ambiguity this phase fixes: generated "Not specified"
placeholders must be distinguishable from genuine source text that happens
to read "Not specified" (or similar), without changing any existing
caller's displayed text.
"""
from __future__ import annotations

import json

from app.services.citizen_charter_services import (
    _display_or_not_specified,
    build_charter_article_body,
    resolve_display_or_not_specified,
)
from app.services.knowledge_document_types import build_chunks_from_charter_v2_services


def test_genuine_source_text_literally_reading_not_specified_is_not_a_placeholder():
    text, was_placeholder = resolve_display_or_not_specified("Not specified")
    assert text == "Not specified"
    assert was_placeholder is False


def test_empty_value_produces_generated_placeholder():
    text, was_placeholder = resolve_display_or_not_specified("")
    assert text == "Not specified"
    assert was_placeholder is True


def test_none_value_produces_generated_placeholder():
    text, was_placeholder = resolve_display_or_not_specified(None)
    assert text == "Not specified"
    assert was_placeholder is True


def test_genuine_other_source_text_is_not_a_placeholder():
    text, was_placeholder = resolve_display_or_not_specified("Office of the Registrar")
    assert text == "Office of the Registrar"
    assert was_placeholder is False


def test_whitespace_only_value_is_a_generated_placeholder():
    text, was_placeholder = resolve_display_or_not_specified("   \n\t  ")
    assert text == "Not specified"
    assert was_placeholder is True


def test_display_or_not_specified_wrapper_unchanged_for_existing_callers():
    # The thin string-only wrapper every existing call site uses must keep
    # returning exactly the same text as before this phase, for both cases.
    assert _display_or_not_specified("Not specified") == "Not specified"
    assert _display_or_not_specified("") == "Not specified"
    assert _display_or_not_specified("Registrar") == "Registrar"


def test_build_charter_article_body_display_text_is_unaffected():
    # Same inputs, same rendered article text as before this phase --
    # resolve_display_or_not_specified is a pure refactor of the
    # generation point, not a behavior change to what's displayed.
    body = build_charter_article_body(
        title="ID Validation",
        service={"office": "Registrar", "who_may_avail": "Not specified", "total_processing_time": ""},
        source_document="c.pdf",
    )
    assert "Office / Division\nRegistrar" in body
    assert "Who May Avail\nNot specified" in body
    assert "Total Processing Time\nNot specified" in body


# ---------------------------------------------------------------------------
# Propagation into real Charter chunk metadata
# (build_chunks_from_charter_v2_services -- the actual indexing path).
# ---------------------------------------------------------------------------


def test_all_placeholder_service_flags_every_tracked_field():
    services = [{"service_title": "Units: 18", "office": "", "who_may_avail": None, "total_processing_time": ""}]
    chunks = build_chunks_from_charter_v2_services(services, title="Charter", source_document="c.pdf")
    flagged = json.loads(chunks[0].metadata["placeholder_fields"])
    assert set(flagged) == {"office", "who_may_avail", "total_processing_time"}


def test_mixed_real_and_placeholder_fields_flags_only_the_empty_ones():
    services = [{
        "service_title": "ID Validation",
        "office": "Registrar",
        "who_may_avail": "",
        "total_processing_time": "3 days",
    }]
    chunks = build_chunks_from_charter_v2_services(services, title="Charter", source_document="c.pdf")
    flagged = json.loads(chunks[0].metadata["placeholder_fields"])
    assert flagged == ["who_may_avail"]


def test_genuine_not_specified_source_text_is_never_flagged_as_placeholder():
    services = [{
        "service_title": "ID Validation",
        "office": "Registrar",
        "who_may_avail": "Not specified",  # literal source text, not generated
        "total_processing_time": "3 days",
    }]
    chunks = build_chunks_from_charter_v2_services(services, title="Charter", source_document="c.pdf")
    assert "placeholder_fields" not in chunks[0].metadata


def test_fully_populated_service_has_no_placeholder_fields_key_at_all():
    services = [{
        "service_title": "ID Validation",
        "office": "Registrar",
        "who_may_avail": "Any student",
        "total_processing_time": "3 days",
    }]
    chunks = build_chunks_from_charter_v2_services(services, title="Charter", source_document="c.pdf")
    assert "placeholder_fields" not in chunks[0].metadata

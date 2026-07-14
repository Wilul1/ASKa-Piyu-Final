"""Phase C integration tests: Citizen's Charter Extraction V2 wired into the
extraction/preview pipeline and Generate Articles.

These tests exercise the wiring added on top of the standalone V2 extractor
(`test_citizen_charter_extractor_v2.py`, Phase B): the preview pipeline
storing `charter_v2_services`, and Generate Articles preferring V2
structured services over the old flat-text fallback.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

from app.services.admin.article_candidate_generator import (
    generate_candidates_from_preview,
)
from app.services.admin.knowledge_base_pipeline import extract_document_preview
from app.services.citizen_charter_extractor_v2 import extract_citizen_charter_services_v2
from app.services.document_ingestion import DocumentType
from app.utils.pdf.pymupdf_extractor import PageExtraction
from tests.test_citizen_charter_extractor_v2 import _build_id_validation_words_v2


_ID_VALIDATION_CHARTER_TEXT = """
Citizen's Charter

4. ID Validation
Office or Division: Office of the Student Affairs and Services
Classification: Simple
Type of Transaction: G2C - Government to Citizen
Who May Avail: All
"""


def _id_validation_page() -> PageExtraction:
    return PageExtraction(
        page_number=1,
        text="",
        method="digital",
        words=_build_id_validation_words_v2(),
        geometry_scale=1.0,
    )


def _id_validation_v2_service_dict() -> dict:
    services = extract_citizen_charter_services_v2([_id_validation_page()])
    assert len(services) == 1
    return asdict(services[0])


def _extraction_with_pdf_pages():
    return SimpleNamespace(
        document_type=DocumentType.PDF,
        extracted_text=_ID_VALIDATION_CHARTER_TEXT,
        cleaned_text=_ID_VALIDATION_CHARTER_TEXT,
        raw_extracted_text=_ID_VALIDATION_CHARTER_TEXT,
        page_count=1,
        extraction_method="digital",
        structured=None,
        pdf_pages=[_id_validation_page()],
    )


@patch("app.services.admin.knowledge_base_pipeline.knowledge_base_statistics")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_extraction_preview_stores_charter_v2_services_when_pdf_pages_exist(
    mock_ingest,
    mock_statistics,
):
    mock_ingest.return_value = _extraction_with_pdf_pages()
    mock_statistics.return_value = {
        "documents_indexed": 0,
        "total_chunks_indexed": 0,
        "embedding_model": "ChromaDB default embedding function",
        "vector_store": "ChromaDB",
        "last_indexed_document": None,
    }

    result = extract_document_preview(
        b"%PDF",
        filename="citizen-charter.pdf",
        content_type="application/pdf",
    )

    assert result["document_profile"] == "citizen_charter"
    services = result["charter_v2_services"]
    assert isinstance(services, list) and len(services) == 1
    assert services[0]["service_title"] == "ID Validation"
    assert services[0]["extraction_quality"] == "clean"
    assert result["charter_v2_detected_count"] == 1
    assert result["charter_v2_clean_count"] == 1
    assert result["charter_v2_needs_review_count"] == 0
    assert result["charter_v2_low_quality_count"] == 0
    assert result["charter_v2_rag_only_count"] == 0
    # No raw word/geometry boxes should leak into the Flutter-facing payload.
    assert "words" not in services[0].get("parser_debug", {})
    diagnostics = result["charter_v2_diagnostics"]
    assert diagnostics["v2_attempted"] is True
    assert diagnostics["pdf_pages_available"] is True
    assert diagnostics["pdf_pages_count"] == 1
    assert diagnostics["pages_with_words_count"] == 1
    assert diagnostics["total_words_count"] > 0
    assert diagnostics["preview_has_charter_v2_services"] is True
    assert diagnostics["preview_charter_v2_services_count"] == 1
    assert diagnostics["fallback_reason"] is None


@patch("app.services.admin.knowledge_base_pipeline.knowledge_base_statistics")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_extraction_preview_v2_payload_empty_when_no_pdf_pages(
    mock_ingest,
    mock_statistics,
):
    extraction = _extraction_with_pdf_pages()
    extraction.pdf_pages = None
    mock_ingest.return_value = extraction
    mock_statistics.return_value = {
        "documents_indexed": 0,
        "total_chunks_indexed": 0,
        "embedding_model": "ChromaDB default embedding function",
        "vector_store": "ChromaDB",
        "last_indexed_document": None,
    }

    result = extract_document_preview(
        b"%PDF",
        filename="citizen-charter.pdf",
        content_type="application/pdf",
    )

    assert result["charter_v2_services"] == []
    assert result["charter_v2_detected_count"] == 0
    diagnostics = result["charter_v2_diagnostics"]
    assert diagnostics["v2_attempted"] is False
    assert diagnostics["pdf_pages_available"] is False
    assert diagnostics["fallback_reason"] == "pdf_pages_missing_from_ingestion_result"


def _preview_with_v2_service(extra_flat_text: str = "") -> dict:
    v2_service = _id_validation_v2_service_dict()
    # Flat text that would produce a *different* (wrong) result if the old
    # V1 flat-text rebuild ran instead of using the V2 structured service —
    # proves Generate Articles prefers V2 when both are present.
    flat_text = extra_flat_text or (
        "5. Government to Citizen\n"
        "Office or Division: [NEEDS REVIEW]\n"
    )
    return {
        "document_type": "citizen_charter",
        "document_profile": "citizen_charter",
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "review_text": flat_text,
        "charter_v2_services": [v2_service],
        "charter_v2_detected_count": 1,
        "charter_v2_clean_count": 1,
        "charter_v2_needs_review_count": 0,
        "charter_v2_low_quality_count": 0,
        "charter_v2_rag_only_count": 0,
        "charter_v2_diagnostics": {
            "v2_attempted": True,
            "pdf_pages_available": True,
            "pdf_pages_count": 1,
            "pages_with_words_count": 1,
            "total_words_count": 50,
            "preview_has_charter_v2_services": True,
            "preview_charter_v2_services_count": 1,
            "v2_error_message": None,
            "fallback_reason": None,
        },
        "knowledge_units": [],
    }


def test_generate_articles_uses_v2_service_for_id_validation_article_body(monkeypatch):
    # Office matching normally comes from a DB-seeded office_aliases table
    # (see scripts/seed_office_aliases.py); stub it here so this test can
    # verify the full Recommended-bucket routing end to end.
    monkeypatch.setattr(
        "app.services.office_matcher.load_office_aliases",
        lambda db: [
            {
                "alias": "Office of the Student Affairs and Services",
                "weight": 1.3,
                "office_id": "osas-1",
                "office_name": "Office of the Student Affairs and Services",
                "service_category": "Student Services",
            },
        ],
    )
    preview = _preview_with_v2_service()
    result = generate_candidates_from_preview(preview, filename="citizen-charter.pdf")

    candidates = result.get("all_candidates") or []
    by_title = {item.get("title"): item for item in candidates}
    assert "ID Validation" in by_title
    item = by_title["ID Validation"]

    assert item["parser_used"] == "citizen_charter_extractor_v2"
    assert item["formatter_used"] == "build_charter_article_body"
    assert item.get("document_type") == "citizen_charter"

    content = str(item.get("content") or "")
    assert "Office of the Student Affairs and Services" in content
    assert "Certificate of Registration" in content
    assert "Student ID" in content
    assert "4 minutes" in content
    assert "[NEEDS REVIEW]" not in content
    # The flat-text fallback seed ("5. Government to Citizen" fragment
    # heading) must never leak in; only V2's genuine transaction_type value
    # ("G2C - Government to Citizen") should appear.
    assert "5. Government to Citizen" not in content

    # Clean + student-facing V2 service should reach Recommended.
    assert item["final_bucket"] == "recommended"
    assert item["publish_allowed"] is True


def test_generate_articles_carries_parser_debug_into_metadata():
    preview = _preview_with_v2_service()
    result = generate_candidates_from_preview(preview, filename="citizen-charter.pdf")

    candidates = result.get("all_candidates") or []
    item = next(c for c in candidates if c.get("title") == "ID Validation")

    # The saved-article metadata block is embedded in the preview content
    # (see admin_article_models.dart '----EXTRACTED METADATA----' parsing).
    content = str(item.get("content") or "")
    marker = "----EXTRACTED METADATA----"
    assert marker in content
    meta = json.loads(content.split(marker, 1)[1].strip())

    assert meta["parser_used"] == "citizen_charter_extractor_v2"
    assert meta["formatter_used"] == "build_charter_article_body"
    debug = meta.get("parser_debug")
    assert debug
    assert debug["extraction_quality"] == "clean"
    assert debug["parser_strategy_used"] == "geometry_words_v2"
    assert debug["detected_service_title"] == "ID Validation"
    assert meta["extraction_quality"] == "clean"
    assert meta["parser_strategy_used"] == "geometry_words_v2"
    assert meta["table_extraction_method"] == "requirements_and_steps_tables"


def test_rag_only_v2_service_never_becomes_recommended_or_needs_review():
    v2_service = _id_validation_v2_service_dict()
    v2_service["service_title"] = "Some Placeholder Service"
    v2_service["office_division"] = "[NEEDS REVIEW]"
    v2_service["classification"] = "[NEEDS REVIEW]"
    v2_service["who_may_avail"] = "[NEEDS REVIEW]"
    v2_service["requirements"] = []
    v2_service["steps"] = []
    v2_service["total_processing_time"] = "[NEEDS REVIEW]"
    v2_service["extraction_quality"] = "rag_only"
    v2_service["extraction_quality_reason"] = "placeholder_only_body"

    preview = {
        "document_type": "citizen_charter",
        "document_profile": "citizen_charter",
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "review_text": "",
        "charter_v2_services": [v2_service],
        "charter_v2_detected_count": 1,
        "charter_v2_clean_count": 0,
        "charter_v2_needs_review_count": 0,
        "charter_v2_low_quality_count": 0,
        "charter_v2_rag_only_count": 1,
        "knowledge_units": [],
    }
    result = generate_candidates_from_preview(preview, filename="citizen-charter.pdf")

    recommended_titles = {c.get("title") for c in result.get("recommended_candidates") or []}
    needs_review_titles = {c.get("title") for c in result.get("needs_review_candidates") or []}
    assert "Some Placeholder Service" not in recommended_titles
    assert "Some Placeholder Service" not in needs_review_titles

    all_candidates = result.get("all_candidates") or []
    placeholder = next(
        (c for c in all_candidates if c.get("title") == "Some Placeholder Service"), None
    )
    if placeholder is not None:
        assert placeholder["final_bucket"] in {"low_quality", "rag_only"}
        assert placeholder["publish_allowed"] is False


def test_fallback_path_only_runs_when_v2_returns_zero_usable_services():
    """When charter_v2_services is empty, Generate Articles must fall back to
    the old flat-text rebuild (still gated by the existing strict bucket
    rules) instead of silently producing zero candidates."""
    flat_text = (
        "4. ID Validation\n"
        "Office or Division: OSAS\n"
        "Classification: Simple\n"
        "Who May Avail: Students\n"
        "Checklist of Requirements | Where to Secure\n"
        "COR | Registrar\n"
        "CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE\n"
        "Present COR | Validate ID | None | 5 minutes | Staff\n"
        "TOTAL: 5 minutes\n"
    )
    preview = {
        "document_type": "citizen_charter",
        "document_profile": "citizen_charter",
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "review_text": flat_text,
        "charter_v2_services": [],
        "charter_v2_detected_count": 0,
        "charter_v2_clean_count": 0,
        "charter_v2_needs_review_count": 0,
        "charter_v2_low_quality_count": 0,
        "charter_v2_rag_only_count": 0,
        "knowledge_units": [],
    }
    result = generate_candidates_from_preview(preview, filename="citizen-charter.pdf")

    candidates = result.get("all_candidates") or []
    by_title = {item.get("title"): item for item in candidates}
    assert "ID Validation" in by_title
    item = by_title["ID Validation"]
    # No usable V2 services: falls back to the old V1 flat-text parser.
    assert item["parser_used"] == "citizen_charter_service_parser"

    report = result.get("charter_report") or {}
    assert report.get("v2_used") is False
    assert report.get("v2_fallback_used") is True
    assert report.get("v2_services_detected") == 0


def test_charter_report_includes_v2_fields_when_v2_used():
    preview = _preview_with_v2_service()
    result = generate_candidates_from_preview(preview, filename="citizen-charter.pdf")

    report = result.get("charter_report") or {}
    assert report.get("parser_used") == "citizen_charter_extractor_v2"
    assert report.get("v2_used") is True
    assert report.get("v2_fallback_used") is False
    assert report.get("v2_services_detected") == 1
    assert report.get("v2_clean_count") == 1
    assert report.get("v2_parser_strategy_counts", {}).get("geometry_words_v2") == 1
    assert report.get("v2_attempted") is True
    assert report.get("pdf_pages_available") is True
    assert report.get("generate_received_charter_v2_services_count") == 1
    assert report.get("fallback_reason") in (None, "")


def test_v1_fallback_restricted_when_v2_attempted_and_zero_services():
    """V2 attempted + zero services must not produce Needs Review from V1 fragments."""
    flat_text = (
        "5. Government to Citizen\n"
        "Office or Division: [NEEDS REVIEW]\n"
        "Classification: Simple\n"
        "Who May Avail: All\n"
        "4. ID Validation\n"
        "Office or Division: OSAS\n"
        "Classification: Simple\n"
        "Who May Avail: Students\n"
        "Checklist of Requirements | Where to Secure\n"
        "COR | Registrar\n"
        "CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE\n"
        "Present COR | Validate ID | None | 5 minutes | Staff\n"
        "TOTAL: 5 minutes\n"
    )
    preview = {
        "document_type": "citizen_charter",
        "document_profile": "citizen_charter",
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "review_text": flat_text,
        "charter_v2_services": [],
        "charter_v2_detected_count": 0,
        "charter_v2_diagnostics": {
            "v2_attempted": True,
            "pdf_pages_available": True,
            "pdf_pages_count": 3,
            "pages_with_words_count": 3,
            "total_words_count": 900,
            "preview_has_charter_v2_services": False,
            "preview_charter_v2_services_count": 0,
            "fallback_reason": "v2_returned_zero_services",
            "page_geometry_debug": [
                {
                    "page_number": 1,
                    "word_count": 300,
                    "first_20_rows": ["4. ID Validation", "Office / Division: OSAS"],
                    "detected_headings": ["4. ID Validation"],
                }
            ],
        },
        "knowledge_units": [],
    }
    result = generate_candidates_from_preview(preview, filename="citizen-charter.pdf")
    report = result.get("charter_report") or {}
    assert report.get("v2_used") is False
    assert report.get("v2_fallback_used") is True
    assert report.get("v2_attempted") is True
    assert report.get("fallback_reason") == "v2_returned_zero_services"
    assert report.get("generate_received_charter_v2_services_count") == 0

    recommended = result.get("recommended_candidates") or []
    needs_review = result.get("needs_review_candidates") or []
    assert recommended == []
    # Fragment / V1 fallback must not appear as normal Needs Review service articles.
    needs_titles = {c.get("title") for c in needs_review}
    assert "Government to Citizen" not in needs_titles

    for item in result.get("all_candidates") or []:
        assert item.get("final_bucket") in {"low_quality", "rag_only"}
        assert item.get("publish_allowed") is False


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.extract_document_preview")
def test_extract_api_forwards_charter_v2_services(mock_extract):
    """Regression: ExtractDocumentResponse must not strip charter_v2_services."""
    from fastapi.testclient import TestClient

    from app.main import app

    mock_extract.return_value = {
        "document_type": "citizen_charter",
        "document_profile": "citizen_charter",
        "admin_selected_document_type": None,
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "raw_text": "raw",
        "cleaned_text": "clean",
        "review_text": "review",
        "extracted_text": "review",
        "page_count": 1,
        "extraction_method": "digital",
        "structuring_method": "deterministic",
        "pipeline_stages": [
            {"key": "extract", "label": "OCR/PDF extraction", "status": "completed", "detail": "digital"},
            {"key": "clean", "label": "Automatic cleaning", "status": "completed", "detail": None},
            {"key": "structure", "label": "LLM structuring", "status": "completed", "detail": "deterministic"},
            {"key": "review", "label": "Admin review/edit", "status": "needs_review", "detail": None},
            {"key": "index", "label": "Index to ChromaDB", "status": "waiting", "detail": None},
        ],
        "structured": {"fields": [], "formatted_text": "review"},
        "diagnostic_report": None,
        "validation_report": None,
        "detected_document_type": {
            "document_type": "citizen_charter",
            "reason": "test",
            "scores": {},
            "manual_override": False,
        },
        "knowledge_units": [],
        "chunk_preview": [],
        "kb_statistics": None,
        "charter_v2_services": [
            {
                "service_title": "ID Validation",
                "office_division": "OSAS",
                "extraction_quality": "clean",
                "parser_debug": {"parser_strategy_used": "geometry_words_v2"},
            }
        ],
        "charter_v2_detected_count": 1,
        "charter_v2_clean_count": 1,
        "charter_v2_needs_review_count": 0,
        "charter_v2_low_quality_count": 0,
        "charter_v2_rag_only_count": 0,
        "charter_v2_diagnostics": {
            "v2_attempted": True,
            "pdf_pages_available": True,
            "pdf_pages_count": 1,
            "pages_with_words_count": 1,
            "total_words_count": 40,
            "preview_has_charter_v2_services": True,
            "preview_charter_v2_services_count": 1,
        },
    }
    client = TestClient(app)
    response = client.post(
        "/admin/knowledge-base/extract",
        headers={"X-Admin-Key": "test-admin-key"},
        files={"file": ("citizen-charter.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["document_profile"] == "citizen_charter"
    assert data["charter_v2_detected_count"] == 1
    assert data["charter_v2_services"][0]["service_title"] == "ID Validation"
    assert data["charter_v2_diagnostics"]["v2_attempted"] is True
    assert data["charter_v2_diagnostics"]["pdf_pages_available"] is True


def test_v2_detected_office_appears_in_final_article_body_without_alias_match(monkeypatch):
    """Regression: metadata.office must not be wiped when office_aliases misses."""
    monkeypatch.setattr(
        "app.services.office_matcher.load_office_aliases",
        lambda db: [],
    )
    v2_service = _id_validation_v2_service_dict()
    # Simulate Internal Audit Unit style: detected office present, no alias match.
    v2_service["office_division"] = "Internal Audit Unit"
    v2_service["parser_debug"] = dict(v2_service.get("parser_debug") or {})
    v2_service["parser_debug"]["detected_office"] = "Internal Audit Unit"

    preview = _preview_with_v2_service()
    preview["charter_v2_services"] = [v2_service]
    result = generate_candidates_from_preview(preview, filename="citizen-charter.pdf")

    item = next(c for c in (result.get("all_candidates") or []) if c.get("title") == "ID Validation")
    content = str(item.get("content") or "")
    assert "Office / Division\nInternal Audit Unit" in content
    assert "Office / Division\nNot specified" not in content
    marker = "----EXTRACTED METADATA----"
    assert marker in content
    meta = json.loads(content.split(marker, 1)[1].strip())
    debug = meta.get("parser_debug") or {}
    assert debug.get("detected_office") == "Internal Audit Unit"


def test_charter_v2_service_to_fields_prefers_detected_office():
    from app.services.citizen_charter_services import (
        build_charter_article_body,
        charter_v2_service_to_fields,
    )

    fields = charter_v2_service_to_fields(
        {
            "service_title": "Audit Clearance",
            "office_division": "[NEEDS REVIEW]",
            "who_may_avail": "All",
            "requirements": [],
            "steps": [
                {
                    "client_step": "Submit request",
                    "agency_action": "Review request",
                    "fees": "None",
                    "processing_time": "1 day",
                    "person_responsible": "Auditor",
                }
            ],
            "parser_debug": {"detected_office": "Internal Audit Unit"},
        }
    )
    assert fields["office"] == "Internal Audit Unit"
    body = build_charter_article_body(
        title="Audit Clearance",
        service=fields,
        source_document="charter.pdf",
    )
    assert "Office / Division\nInternal Audit Unit" in body
    assert "Office / Division\nNot specified" not in body

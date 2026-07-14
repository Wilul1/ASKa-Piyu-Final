"""Tests for Citizen's Charter Extract & Structure V2 renderer."""

from __future__ import annotations

from app.services.citizen_charter_extraction_renderer import (
    build_extraction_priority_diagnostics,
    finalize_charter_v2_service_for_extraction,
    render_charter_v2_service_block,
    render_citizen_charter_v2_extraction_text,
)
from app.services.citizen_charter_extractor_v2 import (
    _split_time_and_person_cells,
    extract_citizen_charter_services_v2,
)
from app.utils.pdf.pymupdf_extractor import PageExtraction
from tests.test_citizen_charter_extractor_v2 import (
    _build_id_validation_fragmented_geometry_words,
    _build_id_validation_words_v2,
)


def _id_validation_v2_service_dict() -> dict:
    page = PageExtraction(
        page_number=1,
        text="",
        method="digital",
        words=_build_id_validation_words_v2(),
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    assert services
    from dataclasses import asdict

    return asdict(services[0])


def test_extraction_renderer_uses_v2_structured_services_not_flattened_fragments():
    service = _id_validation_v2_service_dict()
    text = render_citizen_charter_v2_extraction_text([service])
    assert "Service: ID Validation" in text
    assert "Office: Office of the Student Affairs and Services" in text
    assert "Who May Avail: All" in text
    assert "Certificate of Registration" in text
    assert "Registrar" in text
    assert "Present the Certificate of Registration" in text
    assert "Evaluate the" in text
    assert "Accept the validated ID" in text
    assert "Total Processing Time: 4 minutes" in text
    # Must not look like old flattened fragment dump.
    assert "Client Step: Present the\n" not in text
    assert "Client Step: Certificate of\n" not in text
    assert "Client Step: Evaluate the\n" not in text
    assert "Client Step: Services\n" not in text
    assert "Priority Service Extraction Diagnostics" in text


def test_id_validation_extraction_output_has_exactly_three_complete_steps():
    page = PageExtraction(
        page_number=1,
        text="",
        method="digital",
        words=_build_id_validation_fragmented_geometry_words(),
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    from dataclasses import asdict

    service = asdict(services[0])
    rendered = render_charter_v2_service_block(service)
    assert rendered.count("Client Step:") == 3
    assert "Present the Certificate of Registration" in rendered
    assert "Evaluate the" in rendered
    assert "Services" in rendered
    assert "Accept the validated ID" in rendered
    assert "Total Processing Time: 4 minutes" in rendered
    assert "[NEEDS REVIEW]" not in rendered.split("Steps:")[1].split("Total Processing Time:")[0]


def test_blank_checklist_renders_proper_sentence_in_extraction():
    service = {
        "service_title": "Blank Checklist Service",
        "office_division": "Records Management Office",
        "classification": "Simple",
        "transaction_type": "G2C",
        "who_may_avail": "Students",
        "checklist_blank": True,
        "requirements": [],
        "steps": [
            {
                "client_step": "Submit request",
                "agency_action": "Process request",
                "fees": "None",
                "processing_time": "5 minutes",
                "person_responsible": "Records Staff",
            }
        ],
        "total_processing_time": "5 minutes",
        "extraction_quality": "clean",
    }
    text = render_charter_v2_service_block(service)
    assert "No additional requirements specified in the Citizen's Charter." in text
    assert "Requirement: [NEEDS REVIEW]" not in text


def test_records_management_time_person_split_in_extraction():
    ptime, person = _split_time_and_person_cells("5mins Records", "Officer/Staff")
    assert ptime.lower().startswith("5")
    assert "Records" not in ptime
    assert "Records" in person
    assert "Officer" in person

    ptime2, person2 = _split_time_and_person_cells("18 Minutes Director/", "Chairperson")
    assert "18" in ptime2 and "Director" not in ptime2
    assert "Director" in person2 and "Chairperson" in person2

    ptime3, person3 = _split_time_and_person_cells("Program 30 mins", "Head/faculty In-charge")
    assert "30" in ptime3
    assert "Program" not in ptime3
    assert person3.startswith("Program")
    assert "Head" in person3


def test_requirement_pair_repair_nstp_registrar_dean():
    finalized = finalize_charter_v2_service_for_extraction(
        {
            "service_title": "Sample",
            "office_division": "NSTP Office",
            "who_may_avail": "Students",
            "requirements": [
                {"requirement": "NSTP Form NSTP Office", "where_to_secure": "[NEEDS REVIEW]"},
                {
                    "requirement": "Dropping Form Registrar's Office",
                    "where_to_secure": "[NEEDS REVIEW]",
                },
                {
                    "requirement": "RL for the conduct of General Orientation Dean's Office",
                    "where_to_secure": "[NEEDS REVIEW]",
                },
            ],
            "steps": [
                {
                    "client_step": "Submit",
                    "agency_action": "Receive",
                    "fees": "None",
                    "processing_time": "1 minute",
                    "person_responsible": "Staff",
                }
            ],
            "total_processing_time": "1 minute",
        }
    )
    reqs = {item["requirement"]: item["where_to_secure"] for item in finalized["requirements"]}
    assert reqs["NSTP Form"] == "NSTP Office"
    assert reqs["Dropping Form"] == "Registrar's Office"
    assert reqs["RL for the conduct of General Orientation"] == "Dean's Office"


def test_priority_diagnostics_appear_in_extraction_txt():
    service = _id_validation_v2_service_dict()
    text = render_citizen_charter_v2_extraction_text([service])
    assert "Priority Service Extraction Diagnostics" in text
    assert "ID Validation" in text
    assert "found: yes" in text
    diagnostics = build_extraction_priority_diagnostics([service])
    id_row = next(item for item in diagnostics if item["title"] == "ID Validation")
    assert id_row["found"] is True
    assert id_row["office_detected"] is True
    assert id_row["complete_step_count"] == 3
    assert id_row["total_processing_time_detected"] is True


def test_clean_status_cannot_contain_structural_blockers():
    from app.services.citizen_charter_extraction_renderer import classify_extraction_issues

    service = {
        "service_title": "Broken Clean Service",
        "office_division": "Office A",
        "who_may_avail": "All",
        "requirements": [{"requirement": "Form", "where_to_secure": "[NEEDS REVIEW]"}],
        "steps": [
            {
                "client_step": "Submit",
                "agency_action": "Receive",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "Staff",
            },
            {
                "client_step": "Claim",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
        ],
        "total_processing_time": "1 minute",
        "extraction_quality": "clean",
        "extraction_quality_reason": "meets_clean_requirements",
    }
    finalized = finalize_charter_v2_service_for_extraction(service)
    blockers, warnings = classify_extraction_issues(finalized)
    assert "incomplete_requirement_pair" in warnings
    assert "partial_incomplete_steps" in warnings
    assert finalized["extraction_quality"] == "clean"
    assert "incomplete_requirement_pair" not in (finalized.get("extraction_blockers") or [])
    rendered = render_charter_v2_service_block(service)
    assert "Extraction Status: clean" in rendered
    assert "Extraction Warnings:" in rendered
    assert "Main Blockers: incomplete_requirement_pair" not in rendered

    structural = {
        **service,
        "office_division": "[NEEDS REVIEW]",
        "extraction_quality": "clean",
    }
    finalized2 = finalize_charter_v2_service_for_extraction(structural)
    assert "missing_office" in (finalized2.get("extraction_blockers") or [])
    assert finalized2["extraction_quality"] != "clean"


def test_priority_diagnostics_prefer_merged_service_not_placeholder():
    placeholder = {
        "service_title": "ID Validation",
        "office_division": "[NEEDS REVIEW]",
        "who_may_avail": "[NEEDS REVIEW]",
        "requirements": [],
        "steps": [],
        "total_processing_time": "[NEEDS REVIEW]",
        "extraction_quality": "rag_only",
        "parser_debug": {"detected_service_title": "ID Validation"},
    }
    merged = {
        "service_title": "ID Validation",
        "office_division": "Office of the Student Affairs and Services",
        "who_may_avail": "All",
        "requirements": [
            {"requirement": "Certificate of Registration", "where_to_secure": "Registrar's Office"},
            {"requirement": "Student ID", "where_to_secure": "Business Affairs Office"},
        ],
        "steps": [
            {
                "client_step": "Present the Certificate of Registration.",
                "agency_action": "Check Certificate of Registration.",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "OSAS Director/Chairperson/Staff",
            },
            {
                "client_step": "Evaluate the Services rendered by OSAS.",
                "agency_action": "Issue Evaluation Form.",
                "fees": "None",
                "processing_time": "2 minutes",
                "person_responsible": "OSAS Director/Chairperson/Staff",
            },
            {
                "client_step": "Accept the validated",
                "agency_action": "Release validated ID.",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "OSAS Director/Chairperson/Staff",
            },
            {
                "client_step": "ID.",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
        ],
        "total_processing_time": "4 minutes",
        "extraction_quality": "needs_review",
        "parser_debug": {
            "detected_service_title": "ID Validation",
            "merge": "title_bound_to_structured_block",
            "title_bound_to_structured_block": True,
        },
    }
    diagnostics = build_extraction_priority_diagnostics([placeholder, merged])
    id_row = next(item for item in diagnostics if item["title"] == "ID Validation")
    assert id_row["found"] is True
    assert id_row["office_detected"] is True
    assert id_row["requirements_count"] == 2
    assert id_row["complete_step_count"] == 3
    assert id_row["total_processing_time_detected"] is True
    assert id_row["extraction_status"] != "rag_only"
    assert id_row.get("merge") == "title_bound_to_structured_block"

    finalized = finalize_charter_v2_service_for_extraction(merged)
    assert len(finalized["steps"]) == 3
    assert finalized["steps"][2]["client_step"] == "Accept the validated ID."


def test_requirement_pair_repair_registrar_business_affairs_in_renderer():
    finalized = finalize_charter_v2_service_for_extraction(
        {
            "service_title": "ID Validation",
            "office_division": "OSAS",
            "who_may_avail": "All",
            "requirements": [
                {
                    "requirement": "⎯ Certificate of Registration Registrar’s",
                    "where_to_secure": "Office",
                },
                {"requirement": "⎯ Student ID Business", "where_to_secure": "Affairs Office"},
            ],
            "steps": [
                {
                    "client_step": "Present ID",
                    "agency_action": "Validate",
                    "fees": "None",
                    "processing_time": "1 minute",
                    "person_responsible": "OSAS Director/Clientele/Chairperson/Staff",
                }
            ],
            "total_processing_time": "1 minute",
            "extraction_quality": "clean",
        }
    )
    reqs = {r["requirement"]: r["where_to_secure"] for r in finalized["requirements"]}
    assert reqs["Certificate of Registration"] == "Registrar’s Office"
    assert reqs["Student ID"] == "Business Affairs Office"
    assert finalized["steps"][0]["person_responsible"] == "OSAS Director/Chairperson/Staff"


def test_extract_document_preview_prefers_v2_structured_extraction_text(monkeypatch):
    from app.services.admin import knowledge_base_pipeline as pipeline
    from app.utils.pdf.pymupdf_extractor import PageExtraction

    class _FakeIngest:
        extracted_text = "Office: Broken\nClient Step: Present the\nClient Step: Certificate of"
        cleaned_text = extracted_text
        page_count = 1
        extraction_method = "digital"
        structured = None
        pdf_pages = [
            PageExtraction(
                page_number=1,
                text="",
                method="digital",
                words=_build_id_validation_words_v2(),
                geometry_scale=1.0,
            )
        ]

    class _FakeReview:
        raw_text = "raw"
        cleaned_text = _FakeIngest.cleaned_text
        review_text = _FakeIngest.extracted_text
        structuring_method = "structured_document_parser"

    monkeypatch.setattr(pipeline, "ingest_document", lambda *args, **kwargs: _FakeIngest())
    monkeypatch.setattr(pipeline, "prepare_review_document", lambda result: _FakeReview())
    monkeypatch.setattr(
        pipeline,
        "_detect_kb_document_type",
        lambda *args, **kwargs: type(
            "D",
            (),
            {
                "document_type": pipeline.KnowledgeDocumentType.PROCEDURE,
                "reason": "test",
                "scores": {},
                "manual_override": False,
            },
        )(),
    )
    monkeypatch.setattr(
        pipeline,
        "_quality_payload",
        lambda *args, **kwargs: ([], [], [], {"ok": True}),
    )
    monkeypatch.setattr(pipeline, "knowledge_base_statistics", lambda: {})
    monkeypatch.setattr(
        "app.services.structured_document_parser.classify_document_type",
        lambda text: "citizen_charter",
    )

    payload = pipeline.extract_document_preview(b"%PDF-fake", filename="citizen-charter.pdf")
    review = payload["review_text"]
    assert "Service: ID Validation" in review
    assert "Present the Certificate of Registration" in review
    assert review.count("Client Step:") >= 3
    assert "Client Step: Present the\n" not in review
    assert payload["structuring_method"] == "citizen_charter_extractor_v2"
    assert payload["charter_v2_services"]
    assert payload["extraction_priority_diagnostics"]

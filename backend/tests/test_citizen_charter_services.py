"""Citizen's Charter service extraction and article routing tests."""

from app.services.citizen_charter_services import (
    build_charter_article_body,
    build_charter_generation_report,
    classify_charter_audience,
    classify_charter_candidate_bucket,
    has_mixed_charter_services,
    is_artifact_charter_title,
    is_noise_service_title,
    is_valid_charter_service_block,
    map_charter_category,
    merge_charter_services,
    score_charter_service_completeness,
    strip_service_part_suffix,
)
from app.services.knowledge_document_types import (
    KnowledgeDocumentType,
    build_typed_chunks,
    detect_knowledge_document_type,
    normalize_knowledge_document_type,
)
from app.services.structured_document_parser import (
    classify_document_type,
    parse_structured_document,
)


_SAMPLE_CHARTER = """
Citizen's Charter

ID Validation - Part 1
Office or Division: Office of Student Affairs
Classification: Simple
Type of Transaction: G2C
Who May Avail: Students and alumni
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
Certificate of Registration | Registrar's Office
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Present the Certificate of Registration. | Check Certificate of Registration. | None | 1 minute | OSAS Staff

ID Validation - Part 2
Office or Division: Office of Student Affairs
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Receive validated ID. | Release validated ID. | None | 2 minutes | OSAS Staff
TOTAL: 3 minutes

Issuance of Good Moral Certificate
Office or Division: Guidance and Counseling
Classification: Simple
Who May Avail: Students and alumni
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
Request form | Guidance Office
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit request form. | Evaluate records. | None | 10 minutes | Guidance Counselor
TOTAL: 10 minutes

Abstract of Quotationto Approving Officials
Office or Division: Procurement
Classification: Simple
Who May Avail: Permanent employees
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
Purchase request | Supply Office
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit purchase request. | Review quotation. | None | 1 day | Procurement Staff

Classification: Simple - Part 1
Office or Division: Internal Audit
Who May Avail: Employees
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit documents. | Audit documents. | None | 1 day | Auditor

Vision
Provide quality education.

Service Pledge
We commit to serve.
"""


def test_detects_citizen_charter_document_type():
    assert classify_document_type(_SAMPLE_CHARTER) == "citizen_charter"
    detection = detect_knowledge_document_type(_SAMPLE_CHARTER)
    assert detection.document_type == KnowledgeDocumentType.PROCEDURE
    assert normalize_knowledge_document_type("citizen_charter") == KnowledgeDocumentType.PROCEDURE


def test_parses_one_article_per_service_and_merges_parts():
    parsed = parse_structured_document(_SAMPLE_CHARTER)
    assert parsed["document_type"] == "citizen_charter"
    titles = [item["service"] for item in parsed["services"]]
    assert "ID Validation" in titles
    assert "Issuance of Good Moral Certificate" in titles
    assert all("Part" not in title for title in titles)
    assert all(not is_noise_service_title(title) for title in titles)
    assert "Abstract of Quotationto Approving Officials" not in titles
    assert "Classification: Simple - Part 1" not in titles

    id_validation = next(item for item in parsed["services"] if item["service"] == "ID Validation")
    assert id_validation["who_may_avail"]
    assert id_validation["requirements"]
    assert len(id_validation["steps"]) >= 2


def test_noise_and_merge_helpers():
    assert is_noise_service_title("Abstract of Quotationto Approving Officials")
    assert is_noise_service_title("Official Receipt")
    assert is_noise_service_title("Official Receipt >")
    assert is_noise_service_title("NEXUS SYSTEM")
    assert is_noise_service_title("NEXUS SYSTEM - Part 1")
    assert is_noise_service_title("NEXUS SYSTEM - Part 2")
    assert is_noise_service_title("NEXUS SYSTEM - Part 3")
    assert is_noise_service_title("Classification")
    assert is_noise_service_title("Validation")
    assert is_noise_service_title("Classification: Simple - Part 1")
    assert is_noise_service_title("Classification: Academic - Part 2")
    assert is_noise_service_title("Board of Regents > Classification")
    assert is_noise_service_title("Page 12")
    assert is_noise_service_title("Table continued")
    assert strip_service_part_suffix("ID Validation - Part 1") == "ID Validation"
    assert (
        strip_service_part_suffix(
            "System Information Registration/Modification (Manual Process) - Part 3"
        )
        == "System Information Registration/Modification (Manual Process)"
    )
    merged = merge_charter_services(
        [
            {
                "service": "Dropping of Subjects - Part 1",
                "office": "Registrar",
                "who_may_avail": "Students",
                "requirements": [{"requirement": "Form", "where_to_secure": "Registrar"}],
                "steps": [{"client_step": "Submit form", "agency_action": "Receive form"}],
                "total_processing_time": "[NEEDS REVIEW]",
            },
            {
                "service": "Dropping of Subjects - Part 2",
                "office": "Registrar",
                "who_may_avail": "Students",
                "requirements": [],
                "steps": [{"client_step": "Pay fee", "agency_action": "Issue receipt"}],
                "total_processing_time": "15 minutes",
            },
            {
                "service": "System Information Registration/Modification (Manual Process) - Part 1",
                "office": "MIS",
                "who_may_avail": "Students",
                "classification": "Simple",
                "requirements": [{"requirement": "Request form", "where_to_secure": "MIS"}],
                "steps": [{"client_step": "Submit request", "agency_action": "Receive request"}],
            },
            {
                "service": "System Information Registration/Modification (Manual Process) - Part 2",
                "office": "MIS",
                "steps": [{"client_step": "Wait for update", "agency_action": "Update record"}],
            },
            {
                "service": "System Information Registration/Modification (Manual Process) - Part 3",
                "office": "MIS Office",
                "steps": [{"client_step": "Receive confirmation", "agency_action": "Release slip"}],
                "total_processing_time": "1 day",
            },
            {
                "service": "Board of Regents > Classification",
                "office": "Board",
                "requirements": [],
                "steps": [],
            },
            {
                "service": "NEXUS SYSTEM - Part 2",
                "office": "ICT",
                "requirements": [],
                "steps": [],
            },
        ]
    )
    titles = [item["service"] for item in merged]
    assert "Dropping of Subjects" in titles
    assert "System Information Registration/Modification (Manual Process)" in titles
    assert all("Part" not in title for title in titles)
    assert "Board of Regents > Classification" not in titles
    assert "NEXUS SYSTEM" not in titles
    dropping = next(item for item in merged if item["service"] == "Dropping of Subjects")
    assert len(dropping["steps"]) == 2
    system_info = next(
        item
        for item in merged
        if item["service"] == "System Information Registration/Modification (Manual Process)"
    )
    assert len(system_info["steps"]) == 3
    assert int(system_info["charter_parts_merged"]) == 3


def test_completeness_and_candidate_bucket():
    complete = {
        "service": "ID Validation",
        "office": "Student Affairs",
        "classification": "Simple",
        "who_may_avail": "Students",
        "transaction_type": "G2C – Government to Citizen",
        "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
        "steps": [
            {
                "client_step": "Present COR",
                "agency_action": "Validate ID",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "Staff",
            }
        ],
        "total_processing_time": "1 minute",
    }
    assert score_charter_service_completeness(complete) >= 5
    assert (
        classify_charter_candidate_bucket(
            title="ID Validation",
            service=complete,
            audience="student_facing",
        )
        == "recommended"
    )

    incomplete = {
        "service": "Fragment Service",
        "office": "[NEEDS REVIEW]",
        "requirements": [],
        "steps": [],
    }
    assert score_charter_service_completeness(incomplete, title="Fragment Service") < 3
    assert (
        classify_charter_candidate_bucket(title="Fragment Service", service=incomplete)
        == "low_quality"
    )
    assert classify_charter_candidate_bucket(title="NEXUS SYSTEM", service=complete) == "rag_only"
    assert classify_charter_candidate_bucket(title="Classification: Academic", service=complete) == "rag_only"
    assert classify_charter_candidate_bucket(title="Official Receipt", service=complete) == "rag_only"
    assert classify_charter_candidate_bucket(title="Validation", service=complete) == "rag_only"
    assert (
        classify_charter_candidate_bucket(
            title="Purchase Request Processing",
            service={
                **complete,
                "service": "Purchase Request Processing",
                "who_may_avail": "Permanent employees",
                "office": "Procurement Unit",
            },
            audience="internal",
            text="BAC procurement workflow for permanent employees",
        )
        == "needs_review"
    )


def test_decide_charter_bucket_routes_student_internal_and_low_quality():
    from app.services.citizen_charter_services import decide_charter_bucket

    complete = {
        "office": "OSAS",
        "classification": "Simple",
        "who_may_avail": "Students",
        "transaction_type": "G2C – Government to Citizen",
        "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
        "steps": [
            {
                "client_step": "Present COR",
                "agency_action": "Validate ID",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "Staff",
            }
        ],
        "total_processing_time": "1 minute",
    }
    body = build_charter_article_body(title="ID Validation", service=complete, source_document="c.pdf")
    recommended = decide_charter_bucket(
        title="ID Validation",
        service=complete,
        text=body,
        formatter_used="build_charter_article_body",
        parser_used="citizen_charter_service_parser",
    )
    assert recommended["bucket"] == "recommended"
    assert recommended["bucket_reason"] == "clean_student_facing_service"
    assert recommended["student_facing_score"] >= 1
    assert recommended["blocking_review_flags"] == []

    # Fake header residue must not unlock Recommended.
    messy = {
        **complete,
        "office": "or Division",
        "steps": [
            {
                "client_step": "BE",
                "agency_action": "TIME",
                "responsible_personnel": "RESPONSIBLE",
            }
        ],
    }
    messy_decision = decide_charter_bucket(
        title="ID Validation",
        service=messy,
        text=body,
        formatter_used="build_charter_article_body",
        parser_used="citizen_charter_service_parser",
    )
    assert messy_decision["bucket"] in {"needs_review", "low_quality"}

    internal = decide_charter_bucket(
        title="Purchase Request Processing",
        service={
            **complete,
            "office": "Procurement Unit",
            "who_may_avail": "Permanent employees",
            "transaction_type": "G2G – Government to Government",
            "service": "Purchase Request Processing",
        },
        text="BAC procurement workflow for permanent employees",
        formatter_used="build_charter_article_body",
        parser_used="citizen_charter_service_parser",
    )
    assert internal["bucket"] == "needs_review"
    assert internal["bucket_reason"] == "internal_admin_heavy"

    mixed = decide_charter_bucket(
        title="ID Validation",
        service=complete,
        text=(
            "4. ID Validation\nOffice or Division: OSAS\n"
            "5. Issuance of Good Moral Certificate\nOffice or Division: Guidance\n"
        ),
    )
    assert mixed["bucket"] == "low_quality"

    truncated = decide_charter_bucket(
        title="Modification (Manual Process)",
        service=complete,
        text=body,
    )
    assert truncated["bucket"] == "low_quality"
    assert truncated["bucket_reason"] == "truncated_charter_title"


def test_charter_recommendation_gate_ignores_handbook_noise_flags():
    from app.services.admin.article_candidate_generator import (
        _finalize_planner_buckets,
        _passes_charter_recommendation_gate,
    )

    body = build_charter_article_body(
        title="Counseling",
        service={
            "office": "Guidance Office",
            "who_may_avail": "Students",
            "classification": "Simple",
            "requirements": [{"requirement": "Appointment", "where_to_secure": "Guidance"}],
            "steps": [
                {
                    "client_step": "Attend session",
                    "agency_action": "Provide counseling",
                    "fees": "None",
                    "processing_time": "30 minutes",
                    "person_responsible": "Counselor",
                }
            ],
            "total_processing_time": "30 minutes",
            "total_fees": "None",
        },
        source_document="charter.pdf",
    )
    item = {
        "title": "Counseling",
        "planner_bucket": "pending",
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "document_type": "citizen_charter",
        "article_type": "service_procedure",
        "formatter_used": "build_charter_article_body",
        "parser_used": "citizen_charter_service_parser",
        "charter_audience": "student_facing",
        "charter_candidate_bucket": "recommended",
        "student_facing_score": 2,
        "internal_admin_score": 0,
        "quality_score": 4.5,
        "category_confidence": 0.4,
        "student_usefulness_score": 0.0,
        "needs_review": False,
        "office": "Guidance Office",
        "who_may_avail": "Students",
        "classification": "Simple",
        "requirements": [{"requirement": "Appointment", "where_to_secure": "Guidance"}],
        "steps": [
            {
                "client_step": "Attend session",
                "agency_action": "Provide counseling",
                "fees": "None",
                "processing_time": "30 minutes",
                "person_responsible": "Counselor",
            }
        ],
        "total_processing_time": "30 minutes",
        "total_fees": "None",
        "semantic_validation_passed": True,
        "final_body_validation_passed": True,
        "parser_debug": {"detected_requirements": [], "detected_step_rows": []},
        "review_reason": ["title_too_long", "uncertain_office", "title_from_body"],
        "content": body,
        "summary": "This article explains Counseling for students.",
    }
    assert _passes_charter_recommendation_gate(item) is True
    recommended, needs_review, _ = _finalize_planner_buckets([item])
    assert len(recommended) == 1
    assert recommended[0]["final_bucket"] == "recommended"
    assert recommended[0]["planner_bucket"] == "recommended"
    assert recommended[0]["publish_allowed"] is True
    assert "uncertain_office" not in (recommended[0].get("review_reason") or [])
    assert len(needs_review) == 0


def test_incomplete_and_fragment_charter_candidates_never_enter_recommended():
    from app.services.admin.article_candidate_generator import _finalize_planner_buckets
    from app.services.citizen_charter_services import is_charter_field_label_or_fragment_title

    assert is_charter_field_label_or_fragment_title("Fees: [NEEDS REVIEW]")
    assert is_charter_field_label_or_fragment_title("Processing Time: 10 minutes")
    assert is_charter_field_label_or_fragment_title("er Agencies")
    assert is_charter_field_label_or_fragment_title("NSTP Office")
    assert is_charter_field_label_or_fragment_title("Registration. Registration.")

    incomplete = {
        "title": "ID Validation",
        "planner_bucket": "pending",
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "document_type": "citizen_charter",
        "article_type": "service_procedure",
        "formatter_used": "build_charter_article_body",
        "parser_used": "citizen_charter_service_parser",
        "charter_candidate_bucket": "needs_review",
        "charter_audience": "student_facing",
        "bucket_reason": "incomplete_structured_fields",
        "review_reason": ["incomplete_structured_fields", "table_row_fragment"],
        "quality_score": 5.0,
        "content": "Overview\nIncomplete\n\nOffice / Division\nNot specified\n\nWho May Avail\nNot specified",
        "summary": "Incomplete service.",
        "office": None,
        "needs_review": True,
    }
    fragment = {
        "title": "Fees: [NEEDS REVIEW]",
        "planner_bucket": "pending",
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "document_type": "citizen_charter",
        "article_type": "service_procedure",
        "formatter_used": "build_charter_article_body",
        "parser_used": "citizen_charter_service_parser",
        "charter_candidate_bucket": "needs_review",
        "review_reason": ["incomplete_structured_fields", "table_row_fragment"],
        "quality_score": 3.0,
        "content": "Overview\nFees fragment",
        "summary": "Fees fragment",
        "needs_review": True,
    }
    recommended, needs_review, _ = _finalize_planner_buckets([incomplete, fragment])
    assert recommended == []
    buckets = {item["title"]: item["final_bucket"] for item in needs_review + [incomplete, fragment]}
    assert incomplete["final_bucket"] in {"needs_review", "low_quality"}
    assert fragment["final_bucket"] == "low_quality"
    assert incomplete.get("publish_allowed") is False
    assert fragment.get("publish_allowed") is False
    assert buckets  # sanity


def test_charter_generation_report_shape():
    report = build_charter_generation_report(
        detected_service_blocks=20,
        merged_split_services=3,
        recommended_services=5,
        needs_review_services=4,
        low_quality_artifacts=6,
        rag_only_references=2,
        rejected_artifact_headings=7,
        rejected_mixed_service_blocks=2,
        rejected_incomplete_blocks=3,
        valid_service_blocks=9,
        document_profile="citizen_charter",
        parser_used="citizen_charter_service_parser",
        review_text_length=12000,
        knowledge_units_count=247,
        generated_article_candidates=14,
    )
    assert report["total_detected_service_blocks"] == 20
    assert report["merged_split_services"] == 3
    assert report["recommended_services"] == 5
    assert report["needs_review_services"] == 4
    assert report["low_quality_artifacts_dropped"] == 6
    assert report["rag_only_references"] == 2
    assert report["rejected_artifact_headings"] == 7
    assert report["rejected_mixed_service_blocks"] == 2
    assert report["rejected_incomplete_blocks"] == 3
    assert report["valid_service_blocks"] == 9
    assert report["document_profile"] == "citizen_charter"
    assert report["parser_used"] == "citizen_charter_service_parser"
    assert report["review_text_length"] == 12000
    assert report["knowledge_units_count"] == 247
    assert report["generated_article_candidates"] == 14


def test_soft_validity_gate_and_noisy_parent_path():
    from app.services.citizen_charter_services import (
        collect_charter_parser_text,
        should_reject_charter_article_candidate,
    )

    # Soft gate: office + who + requirements + total (classification optional).
    assert is_valid_charter_service_block(
        title="ID Validation",
        service={
            "office": "OSAS",
            "who_may_avail": "Students",
            "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
            "steps": [],
            "total_processing_time": "5 minutes",
        },
    )
    # Soft gate via OCR text signals when structured fields are thin.
    assert is_valid_charter_service_block(
        title="Counseling",
        service={"office": "Guidance"},
        text=(
            "Office or Division: Guidance\n"
            "Classification: Simple\n"
            "Who May Avail: Students\n"
            "Checklist of Requirements\nRequest form\n"
            "CLIENT STEPS\nSubmit request\n"
            "Processing Time: 30 minutes\nTOTAL: 30 minutes"
        ),
    )
    # Noisy parent path must not reject a clean service title.
    assert not should_reject_charter_article_candidate(
        title="ID Validation",
        source_section="Abstract of Quotationto Approving Officials > 4. ID Validation",
        parent_topic="Abstract of Quotationto Approving Officials",
    )
    assert should_reject_charter_article_candidate(
        title="Classification: Academic",
        source_section="Abstract of Quotationto Approving Officials > Classification: Academic",
    )

    # Parser input fallbacks: empty review_text → cleaned_text.
    text = collect_charter_parser_text(
        {
            "review_text": "",
            "cleaned_text": "x" * 100,
            "knowledge_units": [],
        }
    )
    assert len(text) >= 80


def test_procedure_chunks_build_student_facing_charter_articles():
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.PROCEDURE,
        extraction=object(),
        index_text=_SAMPLE_CHARTER,
        title="citizen-charter.pdf",
        source_document="citizen-charter.pdf",
    )
    titles = [chunk.metadata.get("title") for chunk in chunks]
    assert "ID Validation" in titles
    assert "Issuance of Good Moral Certificate" in titles
    assert all("Part" not in str(title) for title in titles)
    assert "Abstract of Quotationto Approving Officials" not in titles

    id_chunk = next(chunk for chunk in chunks if chunk.metadata.get("title") == "ID Validation")
    assert id_chunk.metadata["source_type"] == "Citizen's Charter"
    assert id_chunk.metadata["parser_document_type"] == "citizen_charter"
    assert id_chunk.metadata["document_type"] == "citizen_charter"
    assert id_chunk.metadata["article_type"] == "service_procedure"
    assert id_chunk.metadata["formatter_used"] == "build_charter_article_body"
    assert id_chunk.metadata["parser_used"] == "citizen_charter_service_parser"
    assert "Overview" in id_chunk.text
    assert "Office / Division" in id_chunk.text
    assert "Who May Avail" in id_chunk.text
    assert "Requirements" in id_chunk.text
    assert "Where to Secure" in id_chunk.text
    assert "Client Step:" in id_chunk.text
    assert "Agency Action:" in id_chunk.text
    assert "Source Information" in id_chunk.text
    assert "Document:" in id_chunk.text
    assert "Service: ID Validation" in id_chunk.text
    assert "Page:" in id_chunk.text
    assert id_chunk.metadata["charter_audience"] == "student_facing"


def test_audience_and_category_routing_without_hardcoded_offices():
    assert (
        classify_charter_audience(
            office="Procurement Unit",
            who_may_avail="Permanent employees",
            title="Purchase Request Processing",
            text="Internal audit and procurement workflow",
        )
        == "internal"
    )
    assert (
        classify_charter_audience(
            office="Registrar Frontline",
            who_may_avail="Students and applicants",
            title="Enrollment Advising",
            text="Student enrollment advising steps",
        )
        == "student_facing"
    )
    assert map_charter_category(
        office="Cashier Window",
        title="Payment of School Fees",
        text="Pay tuition and miscellaneous fees",
    ) == "Payments and Fees"
    assert map_charter_category(
        office="Guidance Front Desk",
        title="Issuance of Good Moral Certificate",
        text="Guidance counseling certificate",
    ) == "Guidance and Counseling"


def test_build_charter_article_body_structure():
    body = build_charter_article_body(
        title="ID Validation",
        service={
            "office": "Office of the Student Affairs and Services",
            "who_may_avail": "All",
            "document_title": "Citizen's Charter 2026, 1st Edition",
            "page": 18,
            "requirements": [
                {
                    "requirement": "Certificate of Registration",
                    "where_to_secure": "Registrar's Office",
                },
                {
                    "requirement": "Student ID",
                    "where_to_secure": "Business Affairs Office",
                },
            ],
            "steps": [
                {
                    "client_step": "CLIENT STEPS",
                    "agency_action": "AGENCY ACTIONS",
                    "fees": "FEES TO BE PAID",
                    "processing_time": "PROCESSING TIME",
                    "person_responsible": "PERSON RESPONSIBLE",
                },
                {
                    "client_step": "Present the Certificate of Registration.",
                    "agency_action": "Check Certificate of Registration.",
                    "fees": "None",
                    "processing_time": "1 minute",
                    "person_responsible": "OSAS Director/Chairperson/Staff",
                },
                {
                    "client_step": "Evaluate the services rendered by OSAS.",
                    "agency_action": "Issue Evaluation Form.",
                    "fees": "None",
                    "processing_time": "2 minutes",
                    "person_responsible": "OSAS Director/Chairperson/Staff",
                },
                {
                    "client_step": "Accept the validated ID.",
                    "agency_action": "Release validated ID.",
                    "fees": "None",
                    "processing_time": "1 minute",
                    "person_responsible": "OSAS Director/Chairperson/Staff",
                },
            ],
            "total_processing_time": "4 minutes",
        },
        source_document="citizen-charter.pdf",
    )
    assert body.startswith("Overview\nThis service provides assistance for ID Validation.")
    assert "Office / Division\nOffice of the Student Affairs and Services" in body
    assert "Who May Avail\nAll" in body
    assert "- Requirement: Certificate of Registration" in body
    assert "  Where to Secure: Registrar's Office" in body
    assert "- Requirement: Student ID" in body
    assert "1. Client Step: Present the Certificate of Registration." in body
    assert "   Agency Action: Check Certificate of Registration." in body
    assert "   Fees: None" in body
    assert "   Processing Time: 1 minute" in body
    assert "   Person Responsible: OSAS Director/Chairperson/Staff" in body
    assert "2. Client Step: Evaluate the services rendered by OSAS." in body
    assert "3. Client Step: Accept the validated ID." in body
    assert "CLIENT STEPS" not in body
    assert "NEXUS SYSTEM" not in body
    assert "\nFees\nNone\n" in body
    assert "Total Processing Time\n4 minutes" in body
    assert "Source Information" in body
    assert "Document: Citizen's Charter 2026, 1st Edition" in body
    assert "Service: ID Validation" in body
    assert "Office: Office of the Student Affairs and Services" in body
    assert "Page: 18" in body


def test_charter_fees_summary_and_paid_fee():
    body = build_charter_article_body(
        title="Processing of Student ID",
        service={
            "office": "Business Affairs Office",
            "who_may_avail": "Students",
            "requirements": [{"requirement": "Request form", "where_to_secure": "BAO"}],
            "steps": [
                {
                    "client_step": "Pay ID fee.",
                    "agency_action": "Issue official receipt.",
                    "fees": "Php 100.00",
                    "processing_time": "5 minutes",
                    "person_responsible": "Cashier",
                }
            ],
            "total_processing_time": "5 minutes",
            "page": "Not specified",
        },
        source_document="charter.pdf",
    )
    assert "   Fees: Php 100.00" in body
    assert "\nFees\nPhp 100.00\n" in body
    assert "Page: Not specified" in body


def test_format_article_content_preserves_charter_structure():
    from app.services.article_content_formatter import format_article_content

    source = build_charter_article_body(
        title="Counseling",
        service={
            "office": "Guidance Office",
            "who_may_avail": "Students",
            "requirements": [{"requirement": "Appointment slip", "where_to_secure": "Guidance"}],
            "steps": [
                {
                    "client_step": "Attend counseling session.",
                    "agency_action": "Provide counseling.",
                    "fees": "None",
                    "processing_time": "30 minutes",
                    "person_responsible": "Guidance Counselor",
                }
            ],
            "total_processing_time": "30 minutes",
        },
        source_document="charter.pdf",
    )
    formatted = format_article_content(
        "Counseling",
        "procedure",
        source,
        metadata={"parser_document_type": "citizen_charter", "source_type": "Citizen's Charter"},
    )
    assert formatted.content_pattern == "citizen_charter_service"
    assert "Office / Division" in formatted.display_content
    assert "Where to Secure:" in formatted.display_content
    assert "Client Step:" in formatted.display_content
    assert formatted.display_content == source


def test_planner_routes_charter_student_internal_and_reference():
    from app.services.admin.article_planner import classify_unit_for_articles

    student = classify_unit_for_articles(
        {
            "title": "ID Validation",
            "content": "Students present Certificate of Registration for ID validation.",
            "office": "Office of Student Affairs",
            "metadata": {
                "document_type": "procedure",
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
                "charter_audience": "student_facing",
                "suggested_category": "Student Services",
                "charter_candidate_bucket": "recommended",
                "who_may_avail": "Students and alumni",
                "extracted_requirements": [
                    {"requirement": "Certificate of Registration", "where_to_secure": "Registrar"}
                ],
                "extracted_steps": [
                    {
                        "client_step": "Present COR",
                        "agency_action": "Validate ID",
                        "processing_time": "1 minute",
                        "person_responsible": "OSAS Staff",
                    }
                ],
            },
        }
    )
    assert student["article_eligible"] is True
    assert student["article_type"] == "procedure"
    assert student["charter_audience"] == "student_facing"

    internal = classify_unit_for_articles(
        {
            "title": "Purchase Request Processing",
            "content": "Permanent employees submit procurement documents for BAC review.",
            "office": "Procurement Unit",
            "metadata": {
                "document_type": "procedure",
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
                "charter_audience": "internal",
                "charter_candidate_bucket": "needs_review",
                "who_may_avail": "Permanent employees",
                "extracted_requirements": [
                    {"requirement": "Purchase request", "where_to_secure": "Supply"}
                ],
                "extracted_steps": [
                    {
                        "client_step": "Submit request",
                        "agency_action": "Review request",
                        "processing_time": "1 day",
                        "person_responsible": "BAC Staff",
                    }
                ],
            },
        }
    )
    assert internal["article_eligible"] is True
    assert internal["article_type"] == "procedure"
    assert internal["charter_audience"] == "internal"

    reference = classify_unit_for_articles(
        {
            "title": "Service Pledge",
            "content": "We commit to serve every client with integrity.",
            "metadata": {
                "document_type": "procedure",
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
            },
        }
    )
    assert reference["article_eligible"] is False
    assert reference["planner_bucket"] == "rag_only"

    noise = classify_unit_for_articles(
        {
            "title": "Abstract of Quotationto Approving Officials",
            "content": "Procurement quotation abstract table fragment.",
            "metadata": {
                "document_type": "procedure",
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
            },
        }
    )
    assert noise["article_eligible"] is False
    assert noise["planner_bucket"] == "rag_only"


_MULTI_SERVICE_CHARTER = """
Citizen's Charter

4. ID Validation
This service validates student identification cards.
Office or Division: Office of the Student Affairs and Services
Classification: Simple
Type of Transaction: G2C
Who May Avail: All
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
Certificate of Registration | Registrar's Office
Student ID | Business Affairs Office
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Present the Certificate of Registration. | Check Certificate of Registration. | None | 1 minute | OSAS Staff
Accept the validated ID. | Release validated ID. | None | 1 minute | OSAS Staff
TOTAL: 4 minutes

5. Issuance of Good Moral Certificate (Undergraduate)
Office or Division: Guidance and Counseling
Classification: Simple
Who May Avail: Students
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
Request form | Guidance Office
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit request form. | Evaluate records. | None | 10 minutes | Guidance Counselor
TOTAL: 10 minutes

6. Student Admission Interview
Office or Division: College Dean
Classification: Complex
Who May Avail: Student-applicants
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
Application form | Admissions
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Attend interview. | Conduct interview. | None | 30 minutes | Dean
TOTAL: 30 minutes

7. Deployment of OJT
Office or Division: College Dean
Classification: Complex
Who May Avail: Students
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
OJT form | College
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit OJT form. | Endorse student. | None | 1 day | Coordinator
TOTAL: 1 day

8. Dropping of Subjects
Office or Division: Registrar
Classification: Simple
Who May Avail: Students
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
Dropping form | Registrar
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit dropping form. | Process request. | None | 15 minutes | Registrar Staff
TOTAL: 15 minutes

4. System Information Registration/Modification (Manual Process)
Office or Division: MIS
Classification: Complex
Who May Avail: Students
CHECKLIST OF REQUIREMENTS | WHERE TO SECURE
Request form | MIS
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit request. | Update record. | None | 1 day | MIS Staff
TOTAL: 1 day

Classification: Academic
Office or Division: Internal
Who May Avail: Employees
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit. | Review. | None | 1 day | Staff

NEXUS SYSTEM
Office or Division: ICT
Who May Avail: Employees
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Login. | Grant access. | None | 5 minutes | ICT Staff
"""


def test_charter_service_boundaries_do_not_overlap():
    parsed = parse_structured_document(_MULTI_SERVICE_CHARTER)
    assert parsed["document_type"] == "citizen_charter"
    titles = [item["service"] for item in parsed["services"]]
    assert "ID Validation" in titles
    assert "Issuance of Good Moral Certificate (Undergraduate)" in titles
    assert "Student Admission Interview" in titles
    assert "Dropping of Subjects" in titles
    assert "System Information Registration/Modification (Manual Process)" in titles
    assert "Classification: Academic" not in titles
    assert "NEXUS SYSTEM" not in titles
    assert all(not is_artifact_charter_title(title) for title in titles)

    id_service = next(item for item in parsed["services"] if item["service"] == "ID Validation")
    id_blob = " ".join(
        [
            str(id_service.get("service")),
            " ".join(str(r.get("requirement")) for r in id_service.get("requirements") or []),
            " ".join(
                f"{s.get('client_step')} {s.get('agency_action')}"
                for s in id_service.get("steps") or []
            ),
        ]
    ).casefold()
    assert "good moral" not in id_blob
    assert "scholarship" not in id_blob
    assert "research" not in id_blob

    interview = next(
        item for item in parsed["services"] if item["service"] == "Student Admission Interview"
    )
    interview_blob = " ".join(
        [
            str(interview.get("service")),
            " ".join(
                f"{s.get('client_step')} {s.get('agency_action')}"
                for s in interview.get("steps") or []
            ),
        ]
    ).casefold()
    assert "deployment of ojt" not in interview_blob
    assert "dropping of subjects" not in interview_blob
    assert "enrollment advising" not in interview_blob

    system_info = next(
        item
        for item in parsed["services"]
        if item["service"] == "System Information Registration/Modification (Manual Process)"
    )
    assert "Modification (Manual Process)" != system_info["service"]
    system_blob = str(system_info).casefold()
    assert "international affairs" not in system_blob


def test_charter_chunks_keep_one_service_per_article_body():
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.PROCEDURE,
        extraction=object(),
        index_text=_MULTI_SERVICE_CHARTER,
        title="citizen-charter.pdf",
        source_document="citizen-charter.pdf",
    )
    by_title = {chunk.metadata.get("title"): chunk.text for chunk in chunks}
    assert "Classification: Academic" not in by_title
    assert "NEXUS SYSTEM" not in by_title
    assert "Validation" not in by_title
    assert "Modification (Manual Process)" not in by_title

    id_body = by_title["ID Validation"]
    assert "Overview" in id_body
    assert "Client Step:" in id_body
    assert "Good Moral Certificate" not in id_body
    assert "Scholarship" not in id_body
    assert "Research" not in id_body
    assert "Process\n" not in id_body or "Client Step:" in id_body
    assert "Key Points" not in id_body
    assert "Eligibility / Conditions" not in id_body

    interview_body = by_title["Student Admission Interview"]
    assert "Deployment of OJT" not in interview_body
    assert "Dropping of Subjects" not in interview_body
    assert "Enrollment Advising" not in interview_body

    system_body = by_title["System Information Registration/Modification (Manual Process)"]
    assert "International Affairs" not in system_body


def test_mixed_charter_services_detection():
    mixed_text = (
        "4. ID Validation\nOffice or Division: OSAS\n"
        "5. Issuance of Good Moral Certificate\nOffice or Division: Guidance\n"
    )
    assert has_mixed_charter_services(title="ID Validation", text=mixed_text) is True
    assert has_mixed_charter_services(
        title="ID Validation",
        text="Overview\nThis service provides assistance for ID Validation.\n\nOffice / Division\nOSAS",
    ) is False
    assert is_valid_charter_service_block(
        title="ID Validation",
        service={
            "office": "OSAS",
            "classification": "Simple",
            "who_may_avail": "All",
            "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
            "steps": [{"client_step": "Present COR", "agency_action": "Check"}],
            "total_processing_time": "4 minutes",
        },
    )
    assert not is_valid_charter_service_block(
        title="Classification: Simple",
        service={
            "office": "OSAS",
            "classification": "Simple",
            "who_may_avail": "All",
            "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
            "steps": [{"client_step": "Present COR", "agency_action": "Check"}],
        },
    )


def test_generate_preview_uses_charter_profile_not_handbook_policy():
    from app.services.admin.article_candidate_generator import generate_candidates_from_preview

    sample = """
4. ID Validation
Office or Division: OSAS
Classification: Simple
Who May Avail: Students
Checklist of Requirements | Where to Secure
COR | Registrar
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Present COR | Validate ID | None | 5 minutes | Staff
TOTAL: 5 minutes

5. Issuance of Good Moral Certificate
Office or Division: Guidance
Classification: Simple
Who May Avail: Students
Checklist of Requirements | Where to Secure
Request form | Guidance
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
Submit form | Issue certificate | None | 10 minutes | Counselor
TOTAL: 10 minutes
"""
    # Simulate leaked handbook_policy units that still contain charter text.
    preview = {
        "document_type": "handbook_policy",
        "document_profile": "citizen_charter",
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
        "review_text": sample,
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": "ID Validation",
                "content": sample,
                "metadata": {"document_type": "handbook_policy"},
            }
        ],
    }
    result = generate_candidates_from_preview(preview, filename="citizen-charter.pdf")
    candidates = result.get("all_candidates") or []
    if not candidates:
        candidates = (
            list(result.get("recommended_candidates") or [])
            + list(result.get("needs_review_candidates") or [])
            + list(result.get("low_confidence_candidates") or [])
        )
    by_title = {item.get("title"): item for item in candidates}
    assert "ID Validation" in by_title
    id_item = by_title["ID Validation"]
    assert id_item.get("document_type") == "citizen_charter"
    content = str(id_item.get("content") or "")
    assert "Good Moral Certificate" not in content
    assert "Overview" in content
    assert "Office / Division" in content
    assert "----EXTRACTED METADATA----" in content
    import json

    meta = json.loads(content.split("----EXTRACTED METADATA----", 1)[1].strip())
    assert meta.get("document_type") == "citizen_charter"
    assert meta.get("formatter_used") == "build_charter_article_body"
    assert meta.get("parser_used") == "citizen_charter_service_parser"
    assert meta.get("document_type") != "handbook_policy"

def test_charter_body_required_sections():
    from app.services.citizen_charter_services import (
        build_charter_article_body,
        charter_body_has_required_sections,
        charter_path_has_artifact,
        should_reject_charter_article_candidate,
    )

    body = build_charter_article_body(
        title="ID Validation",
        service={
            "office": "OSAS",
            "who_may_avail": "Students",
            "classification": "Simple",
            "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
            "steps": [{"client_step": "Present COR", "agency_action": "Validate"}],
            "total_processing_time": "5 minutes",
        },
        source_document="citizen-charter.pdf",
    )
    assert charter_body_has_required_sections(body)
    assert not charter_body_has_required_sections("Overview\nSomething")

    assert is_artifact_charter_title("Classification: Academic")
    assert is_artifact_charter_title("4. Classification: Academic")
    assert is_artifact_charter_title("Classification: Simple")
    assert is_artifact_charter_title("NEXUS SYSTEM")
    assert is_artifact_charter_title("Official Receipt")
    assert is_artifact_charter_title("Validation")
    assert is_artifact_charter_title("Prepare")
    assert is_artifact_charter_title("BAC Sec will")
    assert is_artifact_charter_title("Checking of supporting documents")
    assert not is_artifact_charter_title("Classification of Students Based on Admission")
    assert not is_artifact_charter_title("ID Validation")

    assert charter_path_has_artifact(
        "Abstract of Quotationto Approving Officials > Classification: Academic"
    )
    assert should_reject_charter_article_candidate(
        title="Classification: Academic",
        source_section="Abstract of Quotationto Approving Officials > Classification: Academic",
    )
    assert should_reject_charter_article_candidate(
        title="NEXUS SYSTEM",
        source_section="Abstract of Quotationto Approving Officials > NEXUS SYSTEM",
    )
    assert should_reject_charter_article_candidate(
        title="BAC Sec will",
        source_section="Official Receipt > 1.8 > BAC Sec will",
    )
    assert should_reject_charter_article_candidate(
        title="Classification: Simple",
        source_section="Board of Regents > Classification: Simple",
    )
    assert not should_reject_charter_article_candidate(
        title="ID Validation",
        source_section="Student Services > ID Validation",
    )
    assert not should_reject_charter_article_candidate(
        title="ID Validation",
        source_section="Abstract of Quotationto Approving Officials > 4. ID Validation",
        parent_topic="Abstract of Quotationto Approving Officials",
    )


def test_finalize_demotes_charter_artifacts_from_publishable_buckets():
    from app.services.admin.article_candidate_generator import _finalize_planner_buckets

    id_body = build_charter_article_body(
        title="ID Validation",
        service={
            "office": "OSAS",
            "who_may_avail": "Students",
            "classification": "Simple",
            "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
            "steps": [
                {
                    "client_step": "Present COR",
                    "agency_action": "Validate",
                    "fees": "None",
                    "processing_time": "5 minutes",
                    "person_responsible": "OSAS Staff",
                }
            ],
            "total_processing_time": "5 minutes",
            "total_fees": "None",
        },
        source_document="citizen-charter.pdf",
    )
    previews = [
        {
            "title": "ID Validation",
            "planner_bucket": "recommended",
            "charter_candidate_bucket": "recommended",
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "source_section": "Student Services > ID Validation",
            "office": "OSAS",
            "who_may_avail": "Students",
            "classification": "Simple",
            "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
            "steps": [
                {
                    "client_step": "Present COR",
                    "agency_action": "Validate",
                    "fees": "None",
                    "processing_time": "5 minutes",
                    "person_responsible": "OSAS Staff",
                }
            ],
            "total_processing_time": "5 minutes",
            "total_fees": "None",
            "quality_score": 9.0,
            "category_confidence": 0.9,
            "student_usefulness_score": 2.0,
            "student_facing_score": 2,
            "internal_admin_score": 0,
            "charter_audience": "student_facing",
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "formatter_used": "build_charter_article_body",
            "parser_used": "citizen_charter_service_parser",
            "summary": "This article explains how students complete ID Validation.",
            "content": id_body,
            "review_reason": [],
            "needs_review": False,
            "semantic_validation_passed": True,
            "final_body_validation_passed": True,
            "parser_debug": {"detected_requirements": [], "detected_step_rows": []},
        },
        {
            "title": "Classification: Academic",
            "planner_bucket": "recommended",
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "source_section": "Abstract > Classification: Academic",
            "review_reason": [],
        },
        {
            "title": "NEXUS SYSTEM",
            "planner_bucket": "consolidated_parent",
            "consolidated_parent": True,
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "source_section": "NEXUS SYSTEM",
            "review_reason": [],
        },
        {
            "title": "Official Receipt",
            "planner_bucket": "consolidated_parent",
            "consolidated_parent": True,
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "source_section": "Official Receipt",
            "review_reason": [],
        },
        {
            "title": "Classification: Simple",
            "planner_bucket": "needs_review",
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "source_section": "Board of Regents > Classification: Simple",
            "review_reason": [],
        },
    ]
    recommended, needs_review, consolidated = _finalize_planner_buckets(previews)
    titles_rec = {item["title"] for item in recommended}
    titles_con = {item["title"] for item in consolidated}
    titles_nr = {item["title"] for item in needs_review}
    assert "ID Validation" in titles_rec
    assert "Classification: Academic" not in titles_rec
    assert "NEXUS SYSTEM" not in titles_con
    assert "Official Receipt" not in titles_con
    assert "Classification: Simple" not in titles_nr
    low = [item for item in previews if item.get("planner_bucket") == "low_quality"]
    assert {item["title"] for item in low} >= {
        "Classification: Academic",
        "NEXUS SYSTEM",
        "Official Receipt",
        "Classification: Simple",
    }


def test_charter_blueprints_skip_artifact_consolidation():
    from app.services.admin.article_planner import build_article_blueprints

    def _unit(title: str, parent: str = "Classification") -> dict:
        return {
            "title": title,
            "canonical_topic": title,
            "parent_topic": parent,
            "article_eligible": True,
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "source_section": f"{parent} > {title}",
            "hierarchy_path": f"{parent} > {title}",
            "metadata": {
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
            },
        }

    units = [
        _unit("Classification: Simple"),
        _unit("Classification: Complex"),
        _unit("Classification: Academic"),
        {
            "title": "ID Validation",
            "canonical_topic": "ID Validation",
            "parent_topic": "Student Services",
            "article_eligible": True,
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "source_section": "Student Services > ID Validation",
            "hierarchy_path": "Student Services > ID Validation",
            "metadata": {
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
            },
        },
    ]
    blueprints = build_article_blueprints(units)
    titles = {bp.get("canonical_topic") or bp.get("title") for bp in blueprints}
    assert "Classification" not in titles
    assert "Classification: Simple" not in titles
    assert "Classification: Academic" not in titles
    assert any("ID Validation" in (t or "") for t in titles)


def test_recommended_blocked_if_final_body_has_not_specified():
    from app.services.citizen_charter_services import (
        build_charter_article_body,
        decide_charter_bucket,
    )

    incomplete = {
        "office": "OSAS",
        "classification": "Simple",
        "who_may_avail": "Students",
        "transaction_type": "G2C",
        "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
        "steps": [
            {
                "client_step": "Present COR",
                "agency_action": "Validate ID",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "[NEEDS REVIEW]",
            }
        ],
        "total_processing_time": "1 minute",
    }
    body = build_charter_article_body(title="ID Validation", service=incomplete, source_document="c.pdf")
    assert "Person Responsible: Not specified" in body
    decision = decide_charter_bucket(
        title="ID Validation",
        service=incomplete,
        text=body,
        formatter_used="build_charter_article_body",
        parser_used="citizen_charter_extractor_v2",
    )
    assert decision["bucket"] != "recommended"
    assert decision["bucket"] in {"needs_review", "low_quality"}


def test_recommended_blocked_if_total_processing_time_not_specified():
    from app.services.citizen_charter_services import (
        build_charter_article_body,
        decide_charter_bucket,
    )

    service = {
        "office": "OSAS",
        "classification": "Simple",
        "who_may_avail": "All",
        "transaction_type": "G2C – Government to Citizen",
        "requirements": [{"requirement": "COR", "where_to_secure": "Registrar"}],
        "steps": [
            {
                "client_step": "Present COR",
                "agency_action": "Validate ID",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "Staff",
            }
        ],
        "total_processing_time": "[NEEDS REVIEW]",
    }
    body = build_charter_article_body(title="ID Validation", service=service, source_document="c.pdf")
    assert "Total Processing Time\nNot specified" in body
    decision = decide_charter_bucket(
        title="ID Validation",
        service=service,
        text=body,
        formatter_used="build_charter_article_body",
        parser_used="citizen_charter_extractor_v2",
    )
    assert decision["bucket"] != "recommended"


def test_blank_checklist_outputs_no_additional_requirements_line():
    from app.services.citizen_charter_services import (
        _BLANK_REQUIREMENTS_LINE,
        build_charter_article_body,
        decide_charter_bucket,
    )

    service = {
        "office": "Records Management Office",
        "classification": "Simple",
        "who_may_avail": "Students",
        "transaction_type": "G2C – Government to Citizen",
        "checklist_blank": True,
        "requirements": [],
        "steps": [
            {
                "client_step": "Submit request",
                "agency_action": "Receive request",
                "fees": "None",
                "processing_time": "5 minutes",
                "person_responsible": "Records Staff",
            }
        ],
        "total_processing_time": "5 minutes",
    }
    body = build_charter_article_body(
        title="Records Request",
        service=service,
        source_document="charter.pdf",
    )
    assert _BLANK_REQUIREMENTS_LINE in body
    assert "Requirement: Not specified" not in body
    decision = decide_charter_bucket(
        title="Records Request",
        service=service,
        text=body,
        formatter_used="build_charter_article_body",
        parser_used="citizen_charter_extractor_v2",
    )
    assert decision["bucket"] == "recommended"


def test_blank_checklist_incomplete_steps_not_recommended():
    from app.services.citizen_charter_services import (
        build_charter_article_body,
        decide_charter_bucket,
    )

    service = {
        "office": "Records Management Office",
        "classification": "Simple",
        "who_may_avail": "Students",
        "transaction_type": "G2C",
        "checklist_blank": True,
        "requirements": [],
        "steps": [
            {
                "client_step": "Submit request",
                "agency_action": "Receive request",
                "fees": "None",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "Records Staff",
            }
        ],
        "total_processing_time": "5 minutes",
    }
    body = build_charter_article_body(
        title="Records Request",
        service=service,
        source_document="charter.pdf",
    )
    decision = decide_charter_bucket(
        title="Records Request",
        service=service,
        text=body,
        formatter_used="build_charter_article_body",
        parser_used="citizen_charter_extractor_v2",
    )
    assert decision["bucket"] != "recommended"


def test_g2g_internal_services_are_not_student_facing():
    from app.services.citizen_charter_services import classify_charter_audience

    audience = classify_charter_audience(
        office="Internal Audit Unit",
        who_may_avail="End-users / Offices",
        title="Internal Audit Clearance",
        transaction_type="G2G – Government to Government",
    )
    assert audience == "internal"

    g2c = classify_charter_audience(
        office="Office of the Student Affairs and Services",
        who_may_avail="All",
        title="ID Validation",
        transaction_type="G2C – Government to Citizen",
    )
    assert g2c == "student_facing"


def test_semestral_clearances_renders_all_detected_steps():
    from app.services.citizen_charter_services import (
        build_charter_article_body,
        decide_charter_bucket,
    )

    steps = [
        {
            "client_step": "Present the semestral clearance to OSAS.",
            "agency_action": "Checks/evaluates the student obligation.",
            "fees": "None",
            "processing_time": "1 minute",
            "person_responsible": "OSAS Director/Chairperson/Staff",
        },
        {
            "client_step": "Wait for evaluation.",
            "agency_action": "Evaluate and annotate clearance.",
            "fees": "None",
            "processing_time": "1 minute",
            "person_responsible": "OSAS Director/Chairperson/Staff",
        },
        {
            "client_step": "Receive signed clearance.",
            "agency_action": "Release signed clearance.",
            "fees": "None",
            "processing_time": "1 minute",
            "person_responsible": "OSAS Director/Chairperson/Staff",
        },
    ]
    service = {
        "office": "Office of the Student Affairs and Services",
        "who_may_avail": "Students",
        "transaction_type": "G2C – Government to Citizen",
        "requirements": [{"requirement": "Semestral Clearance", "where_to_secure": "OSAS"}],
        # Contaminated `steps` must not win over clean detected_step_rows.
        "steps": steps[:2],
        "total_fees": "None",
        "total_processing_time": "3 minutes",
        "parser_debug": {"detected_step_rows": steps},
    }
    body = build_charter_article_body(
        title="Signing of Semestral Clearances",
        service=service,
        source_document="charter.pdf",
    )
    assert body.count("Client Step:") == 3
    assert "Present the semestral clearance to OSAS." in body
    assert "Receive signed clearance." in body
    decision = decide_charter_bucket(
        title="Signing of Semestral Clearances",
        service=service,
        text=body,
        audience="student_facing",
        formatter_used="build_charter_article_body",
        parser_used="citizen_charter_extractor_v2",
    )
    assert decision["bucket"] == "recommended"


def test_blank_checklist_none_na_renders_sentence_not_not_specified():
    from app.services.citizen_charter_services import (
        _BLANK_REQUIREMENTS_LINE,
        build_charter_article_body,
    )

    service = {
        "office": "University Clinic",
        "who_may_avail": "Students",
        "transaction_type": "G2C",
        "checklist_blank": False,
        "requirements": [
            {"requirement": "None", "where_to_secure": "N/A"},
            {"requirement": "N/A", "where_to_secure": "None"},
        ],
        "steps": [
            {
                "client_step": "Proceed to the clinic.",
                "agency_action": "Provide medical/dental service.",
                "fees": "None",
                "processing_time": "15 minutes",
                "person_responsible": "Clinic Staff",
            }
        ],
        "total_fees": "None",
        "total_processing_time": "15 minutes",
        "parser_debug": {
            "detected_requirements": [],
            "checklist_blank": True,
            "table_extraction_method": "requirements_and_steps_tables",
        },
    }
    body = build_charter_article_body(
        title="Routine medical and dental services",
        service=service,
        source_document="charter.pdf",
    )
    assert _BLANK_REQUIREMENTS_LINE in body
    assert "Requirement: Not specified" not in body
    assert "Where to Secure: Not specified" not in body


def test_routine_medical_not_forced_internal_by_g2g_or_admin_office():
    from app.services.citizen_charter_services import classify_charter_audience

    audience = classify_charter_audience(
        office="University Health Services / Clinic",
        who_may_avail="Students and personnel",
        title="Routine medical and dental services",
        category="Health Services",
        transaction_type="G2G – Government to Government",
    )
    assert audience == "student_facing"

    library = classify_charter_audience(
        office="University Library",
        who_may_avail="Students",
        title="Library Circulation Service",
        transaction_type="G2G",
    )
    assert library == "student_facing"


def test_hard_internal_services_stay_internal():
    from app.services.citizen_charter_services import classify_charter_audience

    for title, office in (
        ("Procurement of Supplies", "Procurement Unit"),
        ("BAC Resolution Processing", "Bids and Awards Committee"),
        ("ISO Internal Audit", "Internal Audit Unit"),
        ("Quality Assurance Document Review", "Quality Assurance Office"),
        ("Supply and Property Issuance", "Supply and Property Unit"),
        ("Legal services for university officials", "Legal Office"),
        ("HR employee records update", "Human Resource Management Office"),
    ):
        assert (
            classify_charter_audience(
                office=office,
                who_may_avail="End-users / Offices",
                title=title,
                transaction_type="G2G – Government to Government",
            )
            == "internal"
        )
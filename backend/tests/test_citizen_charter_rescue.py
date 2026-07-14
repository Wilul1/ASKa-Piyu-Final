"""Tests for Citizen's Charter rescue / repair pipeline."""

from __future__ import annotations

import re

from app.services.admin.article_candidate_generator import _passes_charter_recommendation_gate
from app.services.citizen_charter_rescue import (
    rescue_charter_v2_service,
    summarize_rescue_results,
    validate_charter_candidate_for_recommended,
)
from app.services.citizen_charter_services import build_charter_generation_report


def _broken_id_validation_service() -> dict:
    """ID Validation with split wraps + personnel mixed into processing time."""
    return {
        "service_title": "ID Validation",
        "office_division": "Office of the Student Affairs and Services",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "All",
        "checklist_blank": False,
        "requirements": [
            {
                "requirement": "Certificate of Registration Registrar's Office",
                "where_to_secure": "[NEEDS REVIEW]",
            },
            {
                "requirement": "Student ID",
                "where_to_secure": "Business Affairs Office",
            },
        ],
        "steps": [
            {
                "client_step": "Present the",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Certificate of",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Registration.",
                "agency_action": "Check Certificate of Registration.",
                "fees": "None",
                "processing_time": "1 minute OSAS Director/Chairperson/Staff",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Evaluate the",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Services",
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
        "total_fees": "None",
        "total_processing_time": "[NEEDS REVIEW]",
        "extraction_quality": "low_quality",
        "extraction_quality_reason": "excessive_not_specified_fields",
        "parser_debug": {
            "detected_office": "Office of the Student Affairs and Services",
            "cleaned_service_block": (
                "4. ID Validation\n"
                "Office / Division: Office of the Student Affairs and Services\n"
                "TOTAL: None 4 minutes\n"
            ),
            "table_extraction_method": "requirements_and_steps_tables",
            "detected_requirements": [
                {"requirement": "[NEEDS REVIEW]", "where_to_secure": "[NEEDS REVIEW]"}
            ],
            "detected_step_rows": [{"client_step": "Present the"}],
        },
    }


def test_needs_review_service_promoted_after_successful_repair():
    rescued = rescue_charter_v2_service(_broken_id_validation_service())
    assert rescued["rescue_attempted"] is True
    assert rescued["original_bucket"] in {"needs_review", "low_quality"}
    assert rescued["repaired_bucket"] == "recommended"
    assert rescued["rescue_successful"] is True
    assert rescued["semantic_validation_passed"] is True
    assert rescued["final_body_validation_passed"] is True
    assert len(rescued["service_fields"]["steps"]) == 3
    assert "Not specified" not in rescued["content"].split("Source Information")[0]
    assert "[NEEDS REVIEW]" not in rescued["content"]
    # Stale OCR placeholders must not remain in synced parser_debug detected_* fields.
    assert not any(
        "[NEEDS REVIEW]" in str(item)
        for item in (rescued["service"]["parser_debug"].get("detected_requirements") or [])
    )


def test_id_validation_rescued_only_with_three_complete_steps():
    rescued = rescue_charter_v2_service(_broken_id_validation_service())
    steps = rescued["service_fields"]["steps"]
    assert len(steps) == 3
    assert "Present the Certificate" in steps[0]["client_step"]
    assert "Check Certificate of Registration." in steps[0]["agency_action"]
    assert steps[0]["person_responsible"].startswith("OSAS")
    assert "Evaluate the" in steps[1]["client_step"]
    assert steps[2]["client_step"].startswith("Accept the validated ID")
    assert rescued["service_fields"]["total_processing_time"] == "4 minutes"
    assert rescued["repaired_bucket"] == "recommended"
    assert rescued["low_quality_rescue_attempted"] is True


def test_low_quality_valid_service_repaired_into_needs_review_or_recommended():
    service = {
        "service_title": "Enrollment Advising",
        "office_division": "College of Arts and Sciences",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Students",
        "requirements": [
            {
                "requirement": "Registration Form College Registrar's Office",
                "where_to_secure": "[NEEDS REVIEW]",
            }
        ],
        "steps": [
            {
                "client_step": "Present registration form",
                "agency_action": "Advise on subjects",
                "fees": "None",
                "processing_time": "10 minutes Adviser",
                "person_responsible": "[NEEDS REVIEW]",
            }
        ],
        "total_processing_time": "10 minutes",
        "total_fees": "None",
        "extraction_quality": "low_quality",
        "extraction_quality_reason": "excessive_not_specified_fields",
        "parser_debug": {"detected_office": "College of Arts and Sciences"},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["rescue_attempted"] is True
    assert rescued["repaired_bucket"] in {"recommended", "needs_review"}
    assert rescued["original_bucket"] in {"low_quality", "needs_review"}
    assert "repaired_requirement_office_suffix" in rescued["repair_actions_applied"]
    assert "repaired_processing_time_personnel_split" in rescued["repair_actions_applied"]


def test_internal_heavy_service_cannot_be_promoted_even_after_repair():
    service = {
        "service_title": "Purchase Request Processing",
        "office_division": "Procurement Unit",
        "classification": "Complex",
        "transaction_type": "G2G – Government to Government",
        "who_may_avail": "Permanent employees",
        "requirements": [{"requirement": "Purchase Request", "where_to_secure": "End-user"}],
        "steps": [
            {
                "client_step": "Submit PR",
                "agency_action": "Evaluate PR",
                "fees": "None",
                "processing_time": "1 day",
                "person_responsible": "BAC Secretariat",
            }
        ],
        "total_processing_time": "1 day",
        "total_fees": "None",
        "extraction_quality": "needs_review",
        "parser_debug": {"detected_office": "Procurement Unit"},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["audience"] == "internal"
    assert rescued["repaired_bucket"] != "recommended"
    assert rescued["repaired_bucket"] in {"needs_review", "rag_only", "low_quality"}
    assert "downgraded_internal_audience" in rescued["repair_actions_applied"]
    assert rescued["rescue_successful"] is False


def test_processing_of_student_id_rescued_only_if_all_step_fields_complete():
    incomplete = {
        "service_title": "Processing of Student ID",
        "office_division": "Business Affairs Office",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Students",
        "requirements": [{"requirement": "Request form", "where_to_secure": "BAO"}],
        "steps": [
            {
                "client_step": "Pay ID fee",
                "agency_action": "Issue official receipt",
                "fees": "Php 100.00",
                "processing_time": "5 minutes",
                "person_responsible": "[NEEDS REVIEW]",
            }
        ],
        "total_processing_time": "5 minutes",
        "extraction_quality": "needs_review",
        "parser_debug": {"detected_office": "Business Affairs Office"},
    }
    rescued = rescue_charter_v2_service(incomplete)
    assert rescued["repaired_bucket"] != "recommended"
    assert rescued["rescue_successful"] is False
    assert "incomplete_step_row" in rescued["remaining_blockers"] or not rescued[
        "semantic_validation_passed"
    ]

    complete = dict(incomplete)
    complete["steps"] = [
        {
            "client_step": "Pay ID fee",
            "agency_action": "Issue official receipt",
            "fees": "Php 100.00",
            "processing_time": "5 minutes",
            "person_responsible": "Cashier",
        }
    ]
    rescued_ok = rescue_charter_v2_service(complete)
    assert rescued_ok["repaired_bucket"] == "recommended"
    assert rescued_ok["semantic_validation_passed"] is True
    assert rescued_ok["rescue_successful"] is True


def test_good_moral_certificate_stays_needs_review_if_payment_rows_broken():
    service = {
        "service_title": "Issuance of Good Moral Certificate",
        "office_division": "Office of the Student Affairs and Services",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Students / Alumni",
        "requirements": [{"requirement": "Request form", "where_to_secure": "OSAS"}],
        "steps": [
            {
                "client_step": "Pay certification fee",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "Php 50.00 Official Receipt",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Claim certificate",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
        ],
        "total_processing_time": "[NEEDS REVIEW]",
        "extraction_quality": "low_quality",
        "parser_debug": {"detected_office": "Office of the Student Affairs and Services"},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["repaired_bucket"] != "recommended"
    assert rescued["repaired_bucket"] in {"needs_review", "low_quality"}
    assert rescued["needs_review_reasons"] or rescued["remaining_blockers"]
    assert rescued["rescue_successful"] is False


def test_recommended_with_parser_debug_needs_review_is_downgraded():
    candidate = {
        "title": "Authenticated Documents",
        "content": (
            "Overview\nService for authenticated documents.\n\n"
            "Office / Division\nRegistrar's Office\n\n"
            "Who May Avail\nStudents\n\n"
            "Requirements\n- Requirement: Request form\n  Where to Secure: Registrar's Office\n\n"
            "Steps\n1. Client Step: Submit request\n   Agency Action: Receive request\n"
            "   Fees: None\n   Processing Time: 5 minutes\n   Person Responsible: Registrar Staff\n\n"
            "Fees\nNone\n\nTotal Processing Time\n5 minutes\n\nSource Information\nDoc"
        ),
        "office": "Registrar's Office",
        "who_may_avail": "Students",
        "charter_audience": "student_facing",
        "requirements": [{"requirement": "Request form", "where_to_secure": "Registrar's Office"}],
        "steps": [
            {
                "client_step": "Submit request",
                "agency_action": "Receive request",
                "fees": "None",
                "processing_time": "5 minutes",
                "person_responsible": "Registrar Staff",
            }
        ],
        "total_processing_time": "5 minutes",
        "total_fees": "None",
        "parser_debug": {
            "detected_requirements": [
                {"requirement": "[NEEDS REVIEW]", "where_to_secure": "[NEEDS REVIEW]"}
            ]
        },
        "formatter_used": "build_charter_article_body",
        "parser_used": "citizen_charter_extractor_v2",
        "charter_candidate_bucket": "recommended",
        "document_type": "citizen_charter",
        "quality_score": 4.0,
    }
    ok, blockers = validate_charter_candidate_for_recommended(candidate)
    assert ok is False
    assert "detected_requirements_contain_needs_review" in blockers
    assert _passes_charter_recommendation_gate(candidate) is False


def test_recommended_with_fees_on_the_is_downgraded():
    candidate = {
        "title": "Authenticated Documents",
        "content": (
            "Overview\nService.\n\nOffice / Division\nRegistrar's Office\n\nWho May Avail\nStudents\n\n"
            "Requirements\n- Requirement: Form\n  Where to Secure: Registrar's Office\n\n"
            "Steps\n1. Client Step: Submit\n   Agency Action: Receive\n   Fees: None\n"
            "   Processing Time: 5 minutes\n   Person Responsible: Staff\n\n"
            "Fees\non the\n\nTotal Processing Time\n5 minutes\n\nSource Information\nDoc"
        ),
        "office": "Registrar's Office",
        "who_may_avail": "Students",
        "charter_audience": "student_facing",
        "requirements": [{"requirement": "Form", "where_to_secure": "Registrar's Office"}],
        "steps": [
            {
                "client_step": "Submit",
                "agency_action": "Receive",
                "fees": "None",
                "processing_time": "5 minutes",
                "person_responsible": "Staff",
            }
        ],
        "total_processing_time": "5 minutes",
        "total_fees": "on the",
        "parser_debug": {"detected_requirements": [], "detected_step_rows": []},
        "formatter_used": "build_charter_article_body",
        "parser_used": "citizen_charter_extractor_v2",
        "charter_candidate_bucket": "recommended",
        "document_type": "citizen_charter",
        "quality_score": 4.0,
    }
    ok, blockers = validate_charter_candidate_for_recommended(candidate)
    assert ok is False
    assert "invalid_total_fees" in blockers


def test_processing_time_director_slash_repaired_or_downgraded():
    service = {
        "service_title": "Certificate of completion with serial number",
        "office_division": "NSTP Office",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Students",
        "requirements": [
            {"requirement": "NSTP Form NSTP", "where_to_secure": "Office"},
        ],
        "steps": [
            {
                "client_step": "Submit NSTP form",
                "agency_action": "Verify serial number",
                "fees": "None",
                "processing_time": "18 Minutes Director/",
                "person_responsible": "Chairperson",
            }
        ],
        "total_processing_time": "18 Minutes",
        "total_fees": "None",
        "extraction_quality": "needs_review",
        "parser_debug": {"detected_office": "NSTP Office"},
    }
    rescued = rescue_charter_v2_service(service)
    req = rescued["service_fields"]["requirements"][0]
    step = rescued["service_fields"]["steps"][0]
    assert req["requirement"] == "NSTP Form"
    assert req["where_to_secure"] == "NSTP Office"
    assert step["processing_time"].lower().startswith("18 minute")
    assert "Director" in step["person_responsible"]
    assert "Chairperson" in step["person_responsible"]
    assert "Director/" not in step["processing_time"]
    if rescued["repaired_bucket"] == "recommended":
        assert rescued["semantic_validation_passed"] is True
        assert rescued["rescue_successful"] is True
    else:
        assert rescued["repaired_bucket"] == "needs_review"


def test_dropping_of_subjects_requirement_office_split():
    service = {
        "service_title": "Dropping of Subjects",
        "office_division": "Registrar's Office",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Students",
        "requirements": [
            {"requirement": "Dropping Form Registrar's", "where_to_secure": "Office"},
        ],
        "steps": [
            {
                "client_step": "Submit dropping form",
                "agency_action": "Process dropping",
                "fees": "None",
                "processing_time": "5 Minutes Dean/Associate",
                "person_responsible": "[NEEDS REVIEW]",
            }
        ],
        "total_processing_time": "5 minutes",
        "total_fees": "None",
        "extraction_quality": "needs_review",
        "parser_debug": {},
    }
    rescued = rescue_charter_v2_service(service)
    req = rescued["service_fields"]["requirements"][0]
    step = rescued["service_fields"]["steps"][0]
    assert req["requirement"] == "Dropping Form"
    assert "Registrar" in req["where_to_secure"]
    assert step["processing_time"].lower().startswith("5 minute")
    assert "Dean" in step["person_responsible"]


def test_rescue_successful_false_if_repaired_fields_not_used_in_body():
    """If structured fields remain incomplete, rescue_successful stays false."""
    service = {
        "service_title": "Library Circulation Service",
        "office_division": "Library",
        "classification": "Simple",
        "transaction_type": "G2C",
        "who_may_avail": "Students",
        "requirements": [{"requirement": "Library Card", "where_to_secure": "Library"}],
        "steps": [
            {
                "client_step": "Borrow book",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "None",
                "processing_time": "2 minutes",
                "person_responsible": "Librarian",
            }
        ],
        "total_processing_time": "2 minutes",
        "extraction_quality": "low_quality",
        "parser_debug": {},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["rescue_attempted"] is True
    assert rescued["rescue_successful"] is False
    assert rescued["remaining_blockers"]


def test_low_quality_public_service_shows_remaining_blockers_when_repair_fails():
    service = {
        "service_title": "Scholarship and Financial Assistance",
        "office_division": "OSAS",
        "classification": "Complex",
        "transaction_type": "G2C",
        "who_may_avail": "Students",
        "requirements": [{"requirement": "Application form", "where_to_secure": "[NEEDS REVIEW]"}],
        "steps": [
            {
                "client_step": "Submit application",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            }
        ],
        "total_processing_time": "[NEEDS REVIEW]",
        "extraction_quality": "low_quality",
        "parser_debug": {"detected_office": "OSAS"},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["low_quality_rescue_attempted"] is True
    assert rescued["rescue_successful"] is False
    assert rescued["remaining_blockers"]
    assert rescued["repaired_bucket"] != "recommended"


def test_report_includes_rescue_attempted_and_successful_counts():
    results = [
        rescue_charter_v2_service(_broken_id_validation_service()),
        rescue_charter_v2_service(
            {
                "service_title": "Purchase Request Processing",
                "office_division": "Procurement Unit",
                "classification": "Complex",
                "transaction_type": "G2G",
                "who_may_avail": "Employees",
                "requirements": [],
                "steps": [],
                "extraction_quality": "rag_only",
                "parser_debug": {},
            }
        ),
    ]
    summary = summarize_rescue_results(results)
    assert summary["rescue_attempted"] >= 1
    assert summary["rescue_successful"] >= 1
    assert summary["promoted_to_recommended_after_repair"] >= 1
    assert "repaired_but_not_promoted" in summary
    assert "repair_failed" in summary
    assert "semantic_validation_failed" in summary
    assert "recommended_blocked_by_semantic_validation" in summary
    assert "low_quality_rescue_attempted" in summary
    assert "low_quality_rescue_successful" in summary
    assert "low_quality_repair_attempted" in summary
    assert "low_quality_repair_changed_fields" in summary
    assert "low_quality_rescued_to_needs_review" in summary
    assert "low_quality_rescued_to_recommended" in summary
    assert "low_quality_repair_failed" in summary
    assert "priority_service_diagnostics" in summary
    assert summary["low_quality_rescue_successful"] == (
        summary["low_quality_rescued_to_needs_review"]
        + summary["low_quality_rescued_to_recommended"]
    )

    report = build_charter_generation_report(
        detected_service_blocks=2,
        merged_split_services=0,
        recommended_services=1,
        needs_review_services=1,
        low_quality_artifacts=0,
        rag_only_references=0,
        rescue_attempted=summary["rescue_attempted"],
        rescue_successful=summary["rescue_successful"],
        promoted_to_recommended_after_repair=summary["promoted_to_recommended_after_repair"],
        true_low_quality_fragments=summary["true_low_quality_fragments"],
        repaired_but_not_promoted=summary["repaired_but_not_promoted"],
        repair_failed=summary["repair_failed"],
        semantic_validation_failed=summary["semantic_validation_failed"],
        recommended_blocked_by_semantic_validation=summary[
            "recommended_blocked_by_semantic_validation"
        ],
        low_quality_rescue_attempted=summary["low_quality_rescue_attempted"],
        low_quality_rescue_successful=summary["low_quality_rescue_successful"],
        low_quality_repair_attempted=summary["low_quality_repair_attempted"],
        low_quality_repair_changed_fields=summary["low_quality_repair_changed_fields"],
        low_quality_rescued_to_needs_review=summary["low_quality_rescued_to_needs_review"],
        low_quality_rescued_to_recommended=summary["low_quality_rescued_to_recommended"],
        low_quality_repair_failed=summary["low_quality_repair_failed"],
        priority_service_diagnostics=summary["priority_service_diagnostics"],
        final_recommended_count=1,
    )
    assert report["rescue_attempted"] == summary["rescue_attempted"]
    assert report["rescue_successful"] == summary["rescue_successful"]
    assert report["promoted_to_recommended_after_repair"] >= 1
    assert report["recommended_services"] == report["final_recommended_count"] == 1
    assert report["low_quality_rescue_attempted"] == summary["low_quality_rescue_attempted"]
    assert report["priority_service_diagnostics"]
    id_diag = next(
        item for item in report["priority_service_diagnostics"] if item["title"] == "ID Validation"
    )
    assert id_diag["found"] is True
    assert id_diag["rescue_successful"] is True
    assert "remaining_blockers" in id_diag
    assert "missing_fields" in id_diag
    assert "row_merge_failure_reason" in id_diag


def _fragmented_id_validation_osas_wraps() -> dict:
    """ID Validation with Certificate-of wraps and OSAS Director/ + Chairperson/Staff crumbs."""
    return {
        "service_title": "ID Validation",
        "office_division": "Office of the Student Affairs and Services",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "All",
        "checklist_blank": False,
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
                "client_step": "Present the",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Certificate of",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Registration.",
                "agency_action": "Check Certificate of Registration.",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "OSAS Director/",
            },
            {
                "client_step": "Chairperson/Staff",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Evaluate the",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Services rendered by OSAS",
                "agency_action": "Issue Evaluation Form.",
                "fees": "None",
                "processing_time": "2 minutes",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "[NEEDS REVIEW]",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "OSAS Director/",
            },
            {
                "client_step": "Chairperson/Staff",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
            {
                "client_step": "Accept the validated ID.",
                "agency_action": "Release validated ID.",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "OSAS Director/",
            },
            {
                "client_step": "Chairperson/Staff",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            },
        ],
        "total_fees": "None",
        "total_processing_time": "4 minutes",
        "extraction_quality": "low_quality",
        "extraction_quality_reason": "excessive_not_specified_fields",
        "parser_debug": {
            "detected_office": "Office of the Student Affairs and Services",
            "cleaned_service_block": (
                "4. ID Validation\n"
                "Office / Division: Office of the Student Affairs and Services\n"
                "TOTAL: None 4 minutes\n"
            ),
            "table_extraction_method": "requirements_and_steps_tables",
        },
    }


def test_id_validation_osas_wraps_merge_into_three_complete_steps():
    rescued = rescue_charter_v2_service(_fragmented_id_validation_osas_wraps())
    steps = rescued["service_fields"]["steps"]
    assert len(steps) == 3
    assert steps[0]["client_step"].startswith("Present the Certificate of Registration")
    assert steps[0]["agency_action"] == "Check Certificate of Registration."
    assert steps[0]["person_responsible"] == "OSAS Director/Chairperson/Staff"
    assert "Evaluate the Services rendered by OSAS" in steps[1]["client_step"]
    assert steps[1]["agency_action"] == "Issue Evaluation Form."
    assert steps[1]["person_responsible"] == "OSAS Director/Chairperson/Staff"
    assert steps[2]["client_step"].startswith("Accept the validated ID")
    assert steps[2]["person_responsible"] == "OSAS Director/Chairperson/Staff"
    assert rescued["service_fields"]["total_processing_time"] == "4 minutes"
    assert rescued["final_body_validation_passed"] is True


def test_lspu_entrance_examination_not_left_low_quality_when_table_complete():
    service = {
        "service_title": "LSPU Entrance Examination",
        "office_division": "Admissions Office",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Incoming students",
        "requirements": [
            {"requirement": "Application Form", "where_to_secure": "Admissions Office"},
        ],
        "steps": [
            {
                "client_step": "Submit application form",
                "agency_action": "Receive and check form",
                "fees": "None",
                "processing_time": "10 minutes",
                "person_responsible": "Admissions Officer",
            },
            {
                "client_step": "Take entrance examination",
                "agency_action": "Administer exam",
                "fees": "None",
                "processing_time": "2 hours",
                "person_responsible": "Proctor",
            },
        ],
        "total_fees": "None",
        "total_processing_time": "2 hours and 10 minutes",
        "extraction_quality": "low_quality",
        "extraction_quality_reason": "excessive_not_specified_fields",
        "parser_debug": {"detected_office": "Admissions Office"},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["repaired_bucket"] != "low_quality"
    assert rescued["repaired_bucket"] in {"recommended", "needs_review"}


def test_library_services_na_fees_normalized_to_none():
    service = {
        "service_title": "Library Circulation Service",
        "office_division": "University Library",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Students",
        "requirements": [
            {"requirement": "Valid Student ID", "where_to_secure": "Client"},
        ],
        "steps": [
            {
                "client_step": "Present ID and borrow materials",
                "agency_action": "Record borrowed items",
                "fees": "N/A",
                "processing_time": "5 minutes",
                "person_responsible": "Librarian",
            }
        ],
        "total_fees": "N/A",
        "total_processing_time": "5 minutes",
        "extraction_quality": "needs_review",
        "parser_debug": {"detected_office": "University Library"},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["service_fields"]["steps"][0]["fees"] == "None"
    assert rescued["service_fields"]["total_fees"] == "None"
    assert "N/A" not in rescued["content"].split("Source Information")[0]


def test_low_quality_rescue_successful_only_when_bucket_improves():
    still_broken = {
        "service_title": "Scholarship and Financial Assistance",
        "office_division": "OSAS",
        "classification": "Complex",
        "transaction_type": "G2C",
        "who_may_avail": "Students",
        "requirements": [
            {"requirement": "Application form", "where_to_secure": "[NEEDS REVIEW]"},
        ],
        "steps": [
            {
                "client_step": "Submit application",
                "agency_action": "[NEEDS REVIEW]",
                "fees": "[NEEDS REVIEW]",
                "processing_time": "[NEEDS REVIEW]",
                "person_responsible": "[NEEDS REVIEW]",
            }
        ],
        "total_processing_time": "[NEEDS REVIEW]",
        "extraction_quality": "low_quality",
        "parser_debug": {"detected_office": "OSAS"},
    }
    rescued = rescue_charter_v2_service(still_broken)
    assert rescued["low_quality_repair_attempted"] is True
    if rescued["repaired_bucket"] == "low_quality":
        assert rescued["low_quality_rescue_successful"] is False
        assert rescued["low_quality_repair_failed"] is True
    else:
        assert rescued["low_quality_rescue_successful"] is True
        assert rescued["repaired_bucket"] in {"needs_review", "recommended"}

    improved = rescue_charter_v2_service(_broken_id_validation_service())
    assert improved["original_bucket"] == "low_quality" or improved["low_quality_repair_attempted"]
    if improved["original_bucket"] == "low_quality":
        assert improved["repaired_bucket"] != "low_quality"
        assert improved["low_quality_rescue_successful"] is True
        assert improved["low_quality_rescued_to_recommended"] or improved[
            "low_quality_rescued_to_needs_review"
        ]


def test_records_management_5mins_records_officer_staff_split():
    service = {
        "service_title": "Authentication of Documents",
        "office_division": "Records Management Office",
        "classification": "Simple",
        "transaction_type": "G2C",
        "who_may_avail": "Students",
        "checklist_blank": True,
        "requirements": [],
        "steps": [
            {
                "client_step": "Submit documents for authentication",
                "agency_action": "Authenticate documents",
                "fees": "None",
                "processing_time": "5mins Records",
                "person_responsible": "Officer, Staff",
            }
        ],
        "total_fees": "None",
        "total_processing_time": "5 minutes",
        "extraction_quality": "needs_review",
        "parser_debug": {"detected_office": "Records Management Office", "checklist_blank": True},
    }
    rescued = rescue_charter_v2_service(service)
    step = rescued["service_fields"]["steps"][0]
    assert step["processing_time"].lower().startswith("5")
    assert "Records" not in step["processing_time"]
    assert "Records Officer, Staff" == step["person_responsible"] or (
        "Records" in step["person_responsible"] and "Officer" in step["person_responsible"]
    )
    assert "Requirement: Not specified" not in rescued["content"]
    assert "No additional requirements specified in the Citizen's Charter." in rescued["content"]


def test_priority_visual_debug_present_when_geometry_steps_empty_reason_tracked():
    from app.services.citizen_charter_extractor_v2 import extract_citizen_charter_services_v2
    from tests.test_citizen_charter_extractor_v2 import _build_id_validation_fragmented_geometry_words
    from app.utils.pdf.pymupdf_extractor import PageExtraction

    page = PageExtraction(
        page_number=1,
        text="",
        method="digital",
        words=_build_id_validation_fragmented_geometry_words(),
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    assert services
    debug = services[0].parser_debug
    assert "visual_table_debug" in debug
    assert "steps_table" in debug["visual_table_debug"]
    assert "column_boundaries" in debug["visual_table_debug"]["steps_table"]
    assert "visual_rows" in debug["visual_table_debug"]["steps_table"]
    rescued = rescue_charter_v2_service(
        {
            "service_title": services[0].service_title,
            "office_division": services[0].office_division,
            "classification": services[0].classification,
            "transaction_type": services[0].transaction_type,
            "who_may_avail": services[0].who_may_avail,
            "requirements": [
                {"requirement": r.requirement, "where_to_secure": r.where_to_secure}
                for r in services[0].requirements
            ],
            "steps": [
                {
                    "client_step": s.client_step,
                    "agency_action": s.agency_action,
                    "fees": s.fees,
                    "processing_time": s.processing_time,
                    "person_responsible": s.person_responsible,
                }
                for s in services[0].steps
            ],
            "total_fees": services[0].total_fees,
            "total_processing_time": services[0].total_processing_time,
            "checklist_blank": services[0].checklist_blank,
            "extraction_quality": services[0].extraction_quality,
            "parser_debug": debug,
        }
    )
    assert rescued["repaired_bucket"] != "rag_only"
    assert len(rescued["service_fields"]["steps"]) == 3
    results = [
        rescue_charter_v2_service(_broken_id_validation_service()),
        rescue_charter_v2_service(
            {
                "service_title": "Library Reference Assistance",
                "office_division": "University Library",
                "classification": "Simple",
                "transaction_type": "G2C",
                "who_may_avail": "Students",
                "requirements": [{"requirement": "Valid ID", "where_to_secure": "Client"}],
                "steps": [
                    {
                        "client_step": "Ask for reference help",
                        "agency_action": "Provide reference assistance",
                        "fees": "N/A",
                        "processing_time": "10 minutes",
                        "person_responsible": "Reference Librarian",
                    }
                ],
                "total_fees": "N/A",
                "total_processing_time": "10 minutes",
                "extraction_quality": "low_quality",
                "parser_debug": {},
            }
        ),
    ]
    summary = summarize_rescue_results(results)
    diagnostics = summary["priority_service_diagnostics"]
    assert isinstance(diagnostics, list)
    assert any(item["title"] == "ID Validation" and item["found"] for item in diagnostics)
    assert any(
        item["title"] == "Library Reference Assistance" and item["found"] for item in diagnostics
    )
    report = build_charter_generation_report(
        detected_service_blocks=2,
        merged_split_services=0,
        recommended_services=1,
        needs_review_services=1,
        low_quality_artifacts=0,
        rag_only_references=0,
        priority_service_diagnostics=diagnostics,
        final_recommended_count=1,
    )
    assert report["priority_service_diagnostics"] == diagnostics


def _complete_osas_step(client: str, agency: str, *, minutes: str = "1 minute") -> dict:
    return {
        "client_step": client,
        "agency_action": agency,
        "fees": "None",
        "processing_time": minutes,
        "person_responsible": "OSAS Director/Chairperson/Staff",
    }


def test_recommended_blocked_when_rendered_steps_fewer_than_detected():
    from app.services.citizen_charter_services import build_charter_article_body

    steps = [
        _complete_osas_step(
            "Present the semestral clearance to OSAS.",
            "Checks/evaluates the student obligation.",
        ),
        _complete_osas_step("Wait for evaluation.", "Evaluate clearance."),
        _complete_osas_step("Receive signed clearance.", "Release signed clearance."),
    ]
    # Contaminated first step still in detected rows, body only has 2 clean steps.
    body = build_charter_article_body(
        title="Signing of Semestral Clearances",
        service={
            "office": "Office of the Student Affairs and Services",
            "who_may_avail": "Students",
            "requirements": [{"requirement": "Clearance Form", "where_to_secure": "OSAS"}],
            "steps": steps[1:],
            "total_fees": "None",
            "total_processing_time": "3 minutes",
        },
        source_document="charter.pdf",
    )
    candidate = {
        "title": "Signing of Semestral Clearances",
        "content": body,
        "office": "Office of the Student Affairs and Services",
        "who_may_avail": "Students",
        "requirements": [{"requirement": "Clearance Form", "where_to_secure": "OSAS"}],
        "steps": steps[1:],
        "total_fees": "None",
        "total_processing_time": "3 minutes",
        "charter_audience": "student_facing",
        "parser_debug": {"detected_step_rows": steps},
    }
    ok, blockers = validate_charter_candidate_for_recommended(candidate)
    assert ok is False
    assert "rendered_steps_fewer_than_detected" in blockers
    assert _passes_charter_recommendation_gate(
        {
            **candidate,
            "charter_candidate_bucket": "recommended",
            "formatter_used": "build_charter_article_body",
            "parser_used": "citizen_charter_extractor_v2",
            "quality_score": 8.0,
            "student_facing_score": 2.0,
            "internal_admin_score": 0.0,
        }
    ) is False


def test_recommended_blocked_when_total_fees_contains_needs_review():
    from app.services.citizen_charter_services import build_charter_article_body

    steps = [
        _complete_osas_step("Present COR.", "Check COR."),
        _complete_osas_step("Evaluate services.", "Issue form.", minutes="2 minutes"),
        _complete_osas_step("Accept validated ID.", "Release ID."),
    ]
    body = build_charter_article_body(
        title="ID Validation",
        service={
            "office": "Office of the Student Affairs and Services",
            "who_may_avail": "All",
            "requirements": [
                {"requirement": "Certificate of Registration", "where_to_secure": "Registrar's Office"},
                {"requirement": "Student ID", "where_to_secure": "Business Affairs Office"},
            ],
            "steps": steps,
            "total_fees": "[NEEDS REVIEW]",
            "total_processing_time": "4 minutes",
        },
        source_document="charter.pdf",
    )
    # Force Fees section text when summarize falls back.
    if "Fees\nNone" in body:
        body = body.replace("Fees\nNone", "Fees\n[NEEDS REVIEW]", 1)
    candidate = {
        "title": "ID Validation",
        "content": body,
        "office": "Office of the Student Affairs and Services",
        "who_may_avail": "All",
        "requirements": [
            {"requirement": "Certificate of Registration", "where_to_secure": "Registrar's Office"},
            {"requirement": "Student ID", "where_to_secure": "Business Affairs Office"},
        ],
        "steps": steps,
        "total_fees": "[NEEDS REVIEW]",
        "total_processing_time": "4 minutes",
        "charter_audience": "student_facing",
        "parser_debug": {"detected_step_rows": steps},
    }
    ok, blockers = validate_charter_candidate_for_recommended(candidate)
    assert ok is False
    assert "invalid_total_fees" in blockers


def test_recommended_blocked_when_rescue_successful_false_but_bucket_recommended():
    from app.services.citizen_charter_services import build_charter_article_body

    steps = [
        _complete_osas_step("Present COR.", "Check COR."),
        _complete_osas_step("Evaluate services.", "Issue form.", minutes="2 minutes"),
        _complete_osas_step("Accept validated ID.", "Release ID."),
    ]
    body = build_charter_article_body(
        title="ID Validation",
        service={
            "office": "Office of the Student Affairs and Services",
            "who_may_avail": "All",
            "requirements": [
                {"requirement": "Certificate of Registration", "where_to_secure": "Registrar's Office"}
            ],
            "steps": steps,
            "total_fees": "None",
            "total_processing_time": "4 minutes",
        },
        source_document="charter.pdf",
    )
    candidate = {
        "title": "ID Validation",
        "content": body,
        "office": "Office of the Student Affairs and Services",
        "who_may_avail": "All",
        "requirements": [
            {"requirement": "Certificate of Registration", "where_to_secure": "Registrar's Office"}
        ],
        "steps": steps,
        "total_fees": "None",
        "total_processing_time": "4 minutes",
        "charter_audience": "student_facing",
        "charter_candidate_bucket": "recommended",
        "repaired_bucket": "recommended",
        "fields_changed": True,
        "rescue_successful": False,
        "body_uses_repaired_fields": False,
        "repair_actions_applied": ["cleaned_fee_value"],
        "parser_debug": {
            "detected_step_rows": steps,
            "rescue": {
                "fields_changed": True,
                "rescue_successful": False,
                "body_uses_repaired_fields": False,
                "repaired_bucket": "recommended",
                "repair_actions_applied": ["cleaned_fee_value"],
            },
        },
    }
    ok, blockers = validate_charter_candidate_for_recommended(candidate)
    assert ok is False
    assert "rescue_not_successful_for_recommended" in blockers
    assert "body_missing_repaired_fields" in blockers


def test_semestral_clearances_header_crumbs_render_three_steps_or_needs_review():
    from app.services.citizen_charter_services import build_charter_article_body

    contaminated = {
        "service_title": "Signing of Semestral Clearances",
        "office_division": "Office of the Student Affairs and Services",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Students",
        "requirements": [{"requirement": "Semestral Clearance", "where_to_secure": "OSAS"}],
        "steps": [
            {
                "client_step": "Present the semestral clearance to OSAS.",
                "agency_action": "Checks/evaluates the student obligation before signing.",
                "fees": "BE PAID None",
                "processing_time": "TIME 1 minute",
                "person_responsible": "TIME RESPONSIBLE OSAS Director/Staff",
            },
            _complete_osas_step(
                "Wait while OSAS completes the evaluation.",
                "Evaluate and annotate clearance.",
                minutes="2 minutes",
            ),
            _complete_osas_step(
                "Receive the signed semestral clearance.",
                "Release signed clearance.",
            ),
        ],
        "total_fees": "None",
        "total_processing_time": "4 minutes",
        "extraction_quality": "needs_review",
        "parser_debug": {},
    }
    rescued = rescue_charter_v2_service(contaminated)
    fields = rescued["service_fields"]
    steps = fields["steps"]
    assert len(steps) == 3
    assert steps[0]["fees"] == "None"
    assert steps[0]["processing_time"] == "1 minute"
    assert "OSAS Director" in steps[0]["person_responsible"]
    assert "TIME" not in steps[0]["person_responsible"]
    body = rescued["content"] or build_charter_article_body(
        title=rescued["title"],
        service=fields,
        source_document="charter.pdf",
    )
    rendered = len(re.findall(r"(?im)^\d+\.\s*Client Step:", body))
    if rescued["repaired_bucket"] == "recommended":
        assert rendered == 3
        assert rescued["rescue_successful"] is True
        assert "[NEEDS REVIEW]" not in body.split("Source Information")[0]
    else:
        assert rescued["repaired_bucket"] in {"needs_review", "low_quality"}
        assert rendered == 3 or "rendered_steps_fewer_than_detected" in (
            rescued.get("remaining_blockers") or []
        )


def test_id_validation_becomes_recommended_with_three_rendered_steps_after_crumb_cleanup():
    from app.services.citizen_charter_services import build_charter_article_body

    service = {
        "service_title": "ID Validation",
        "office_division": "Office of the Student Affairs and Services",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "All",
        "requirements": [
            {"requirement": "Certificate of Registration", "where_to_secure": "Registrar's Office"},
            {"requirement": "Student ID", "where_to_secure": "Business Affairs Office"},
        ],
        "steps": [
            {
                "client_step": "Present the Certificate of Registration.",
                "agency_action": "Check Certificate of Registration.",
                "fees": "BE PAID None",
                "processing_time": "TIME 1 minute",
                "person_responsible": "TIME RESPONSIBLE OSAS Director/Staff",
            },
            {
                "client_step": "Evaluate the Services rendered by OSAS.",
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
        "total_fees": "None",
        "total_processing_time": "4 minutes",
        "extraction_quality": "needs_review",
        "parser_debug": {},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["repaired_bucket"] == "recommended"
    assert rescued["semantic_validation_passed"] is True
    assert rescued["final_body_validation_passed"] is True
    body = rescued["content"]
    assert body.count("Client Step:") == 3
    assert "Fees: None" in body
    assert "Person Responsible: OSAS Director/Chairperson/Staff" in body
    assert "BE PAID" not in body
    assert "TIME RESPONSIBLE" not in body
    assert "Total Processing Time\n4 minutes" in body
    assert _passes_charter_recommendation_gate(
        {
            "title": rescued["title"],
            "content": body,
            "office": rescued["service_fields"]["office"],
            "who_may_avail": rescued["service_fields"]["who_may_avail"],
            "requirements": rescued["service_fields"]["requirements"],
            "steps": rescued["service_fields"]["steps"],
            "total_fees": rescued["service_fields"]["total_fees"],
            "total_processing_time": rescued["service_fields"]["total_processing_time"],
            "charter_audience": "student_facing",
            "charter_candidate_bucket": "recommended",
            "formatter_used": "build_charter_article_body",
            "parser_used": "citizen_charter_extractor_v2",
            "quality_score": 8.0,
            "student_facing_score": 3.0,
            "internal_admin_score": 0.0,
            "semantic_validation_passed": True,
            "final_body_validation_passed": True,
            "parser_debug": rescued["service"].get("parser_debug")
            if isinstance(rescued.get("service"), dict)
            else {},
        }
    ) is True


def test_priority_coverage_matrix_includes_all_priority_services():
    from app.services.citizen_charter_rescue import (
        _PRIORITY_DIAGNOSTIC_TITLES,
        build_priority_rescue_diagnostics,
    )

    results = [
        {
            "title": "ID Validation",
            "content": "1. Client Step: Present COR.\n2. Client Step: Wait.\n3. Client Step: Accept ID.",
            "repaired_bucket": "recommended",
            "original_bucket": "needs_review",
            "rescue_attempted": True,
            "rescue_successful": True,
            "remaining_blockers": [],
            "missing_fields": [],
            "extraction_quality": "clean",
            "service_fields": {
                "requirements": [
                    {"requirement": "COR", "where_to_secure": "Registrar"},
                    {"requirement": "Student ID", "where_to_secure": "BAO"},
                ],
                "steps": [
                    {"client_step": "Present COR", "agency_action": "Check"},
                    {"client_step": "Wait", "agency_action": "Issue form"},
                    {"client_step": "Accept ID", "agency_action": "Release"},
                ],
                "total_processing_time": "4 minutes",
                "parser_debug": {
                    "detected_requirements": [
                        {"requirement": "COR", "where_to_secure": "Registrar"},
                        {"requirement": "Student ID", "where_to_secure": "BAO"},
                    ],
                    "detected_step_rows": [
                        {"client_step": "Present COR", "agency_action": "Check"},
                        {"client_step": "Wait", "agency_action": "Issue form"},
                        {"client_step": "Accept ID", "agency_action": "Release"},
                    ],
                },
            },
            "service": {
                "extraction_quality": "clean",
                "parser_debug": {
                    "detected_requirements": [
                        {"requirement": "COR", "where_to_secure": "Registrar"},
                        {"requirement": "Student ID", "where_to_secure": "BAO"},
                    ],
                    "detected_step_rows": [
                        {"client_step": "Present COR", "agency_action": "Check"},
                        {"client_step": "Wait", "agency_action": "Issue form"},
                        {"client_step": "Accept ID", "agency_action": "Release"},
                    ],
                },
            },
        },
        {
            "title": "Procurement of Office Supplies",
            "content": "1. Client Step: Submit PR.",
            "repaired_bucket": "needs_review",
            "remaining_blockers": ["audience_not_student_facing"],
            "missing_fields": [],
            "service_fields": {"steps": [], "requirements": []},
            "service": {},
        },
    ]
    diagnostics = build_priority_rescue_diagnostics(results)
    titles = [item["title"] for item in diagnostics]
    assert set(titles) == set(_PRIORITY_DIAGNOSTIC_TITLES)
    assert len(diagnostics) == len(_PRIORITY_DIAGNOSTIC_TITLES)

    id_row = next(item for item in diagnostics if item["title"] == "ID Validation")
    assert id_row["found"] is True
    assert id_row["extraction_status"] == "clean"
    assert id_row["final_bucket"] == "recommended"
    assert id_row["publish_allowed"] is True
    assert id_row["detected_requirements_count"] == 2
    assert id_row["detected_step_count"] == 3
    assert id_row["rendered_step_count"] == 3
    assert id_row["total_processing_time_detected"] is True
    assert id_row["next_action"] == "ready_for_publish_review"

    missing = next(
        item for item in diagnostics if item["title"] == "Signing of Semestral Clearances"
    )
    assert missing["found"] is False
    assert missing["extraction_status"] == "not_found"
    assert missing["publish_allowed"] is False
    assert missing["next_action"] == "extract_or_detect_service"
    assert "found" in missing and "blockers" in missing and "next_action" in missing


def test_priority_student_service_not_downgraded_internal_by_g2g():
    service = {
        "service_title": "Routine medical and dental services",
        "office_division": "University Clinic",
        "classification": "Simple",
        "transaction_type": "G2G – Government to Government",
        "who_may_avail": "Students",
        "checklist_blank": True,
        "requirements": [],
        "steps": [
            {
                "client_step": "Proceed to the clinic for consultation.",
                "agency_action": "Provide medical or dental service.",
                "fees": "None",
                "processing_time": "15 minutes",
                "person_responsible": "Clinic Nurse/Dentist",
            }
        ],
        "total_fees": "None",
        "total_processing_time": "15 minutes",
        "extraction_quality": "clean",
        "parser_debug": {
            "detected_requirements": [],
            "detected_step_rows": [
                {
                    "client_step": "Proceed to the clinic for consultation.",
                    "agency_action": "Provide medical or dental service.",
                    "fees": "None",
                    "processing_time": "15 minutes",
                    "person_responsible": "Clinic Nurse/Dentist",
                }
            ],
            "checklist_blank": True,
        },
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["audience"] == "student_facing"
    assert rescued["repaired_bucket"] in {"recommended", "needs_review"}
    assert rescued["repaired_bucket"] != "rag_only"
    assert "No additional requirements specified in the Citizen's Charter." in rescued["content"]


def test_internal_procurement_stays_needs_review_or_rag_only():
    service = {
        "service_title": "Procurement of Supplies and Equipment",
        "office_division": "Procurement Unit",
        "classification": "Complex",
        "transaction_type": "G2G – Government to Government",
        "who_may_avail": "End-users / Offices",
        "requirements": [
            {"requirement": "Purchase Request", "where_to_secure": "End-user"}
        ],
        "steps": [
            {
                "client_step": "Submit purchase request.",
                "agency_action": "Process procurement documents.",
                "fees": "None",
                "processing_time": "3 days",
                "person_responsible": "Procurement Officer",
            }
        ],
        "total_fees": "None",
        "total_processing_time": "3 days",
        "extraction_quality": "clean",
        "parser_debug": {},
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["audience"] == "internal"
    assert rescued["repaired_bucket"] in {"needs_review", "rag_only", "low_quality"}
    assert rescued["repaired_bucket"] != "recommended"

def test_semestral_clearances_remain_recommended_after_repair():
    service = {
        "service_title": "Signing of Semestral Clearances",
        "office_division": "Office of the Student Affairs and Services",
        "classification": "Simple",
        "transaction_type": "G2C – Government to Citizen",
        "who_may_avail": "Graduating Students",
        "requirements": [{"requirement": "Semestral Clearance", "where_to_secure": "OSAS"}],
        "steps": [
            _complete_osas_step(
                "Present the semestral clearance to OSAS.",
                "Checks/evaluates the student obligation.",
            ),
            _complete_osas_step("Wait for evaluation.", "Evaluate clearance."),
            _complete_osas_step("Receive signed clearance.", "Release signed clearance."),
        ],
        "total_fees": "None",
        "total_processing_time": "3 minutes",
        "extraction_quality": "clean",
        "parser_debug": {
            "detected_step_rows": [
                _complete_osas_step(
                    "Present the semestral clearance to OSAS.",
                    "Checks/evaluates the student obligation.",
                ),
                _complete_osas_step("Wait for evaluation.", "Evaluate clearance."),
                _complete_osas_step("Receive signed clearance.", "Release signed clearance."),
            ]
        },
    }
    rescued = rescue_charter_v2_service(service)
    assert rescued["repaired_bucket"] == "recommended"
    assert rescued["content"].count("Client Step:") == 3


def test_routine_medical_blank_checklist_no_incomplete_requirement_pair():
    from app.services.citizen_charter_rescue import _semantic_validation_passed

    service_fields = {
        "office": "University Clinic",
        "who_may_avail": "Students",
        "checklist_blank": True,
        "requirements": [{"requirement": "None", "where_to_secure": "N/A"}],
        "steps": [
            {
                "client_step": "Proceed to the clinic.",
                "agency_action": "Provide medical or dental service.",
                "fees": "None",
                "processing_time": "2-3 mins",
                "person_responsible": "Clinic Staff",
            }
        ],
        "total_fees": "None",
        "total_processing_time": "2-3 mins",
    }
    body = (
        "Overview\nThis service provides assistance for Routine medical and dental services.\n\n"
        "Office / Division\nUniversity Clinic\n\nWho May Avail\nStudents\n\n"
        "Requirements\nNo additional requirements specified in the Citizen's Charter.\n\n"
        "Steps\n1. Client Step: Proceed to the clinic.\n   Agency Action: Provide medical or dental service.\n"
        "   Fees: None\n   Processing Time: 2-3 mins\n   Person Responsible: Clinic Staff\n\n"
        "Fees\nNone\n\nTotal Processing Time\n2-3 mins\n\nSource Information\nDocument: c.pdf\n"
        "Service: Routine medical and dental services\nOffice: University Clinic\nPage: Not specified"
    )
    ok, blockers = _semantic_validation_passed(
        title="Routine medical and dental services",
        service_fields=service_fields,
        body=body,
        audience="student_facing",
        parser_debug={"checklist_blank": True, "detected_requirements": []},
    )
    assert "incomplete_requirement_pair" not in blockers

    rescued = rescue_charter_v2_service(
        {
            "service_title": "Routine medical and dental services",
            "office_division": "University Clinic",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "Students",
            "checklist_blank": True,
            "requirements": [{"requirement": "None", "where_to_secure": "N/A"}],
            "steps": [
                {
                    "client_step": "Write name, course, year and section.",
                    "agency_action": "Receive student information.",
                    "fees": "None",
                    "processing_time": "1 minute",
                    "person_responsible": "Clinic Staff",
                },
                {
                    "client_step": "Undergo consultation.",
                    "agency_action": "Provide medical or dental service.",
                    "fees": "None",
                    "processing_time": "2-3 mins University",
                    "person_responsible": "Clinic Staff",
                },
                {
                    "client_step": "Sign in the logbook.",
                    "agency_action": "Record the transaction.",
                    "fees": "None",
                    "processing_time": "1 minute",
                    "person_responsible": "Clinic Staff",
                },
            ],
            "total_fees": "None",
            "total_processing_time": "4-5 mins",
            "extraction_quality": "needs_review",
            "parser_debug": {
                "checklist_blank": True,
                "detected_requirements": [],
                "detected_step_rows": [
                    {
                        "client_step": "Write name, course, year and section.",
                        "agency_action": "Receive student information.",
                        "fees": "None",
                        "processing_time": "1 minute",
                        "person_responsible": "Clinic Staff",
                    },
                    {
                        "client_step": "Undergo consultation.",
                        "agency_action": "Provide medical or dental service.",
                        "fees": "None",
                        "processing_time": "2-3 mins University",
                        "person_responsible": "Clinic Staff",
                    },
                    {
                        "client_step": "Sign in the logbook.",
                        "agency_action": "Record the transaction.",
                        "fees": "None",
                        "processing_time": "1 minute",
                        "person_responsible": "Clinic Staff",
                    },
                ],
            },
        }
    )
    assert "incomplete_requirement_pair" not in rescued["remaining_blockers"]
    assert "University" not in rescued["service_fields"]["steps"][1]["processing_time"]
    assert rescued["required_step_count_met"] is True
    assert rescued["repaired_bucket"] == "recommended"


def test_lspu_entrance_exam_repairs_requirement_pairs_and_time_person():
    from app.services.citizen_charter_rescue import (
        _repair_requirement_pairs,
        _split_processing_and_personnel,
    )

    reqs, actions = _repair_requirement_pairs(
        [
            {"requirement": "Online application form", "where_to_secure": "[NEEDS REVIEW]"},
            {
                "requirement": "Certified True Copy (Report Card and/or TOR)",
                "where_to_secure": "",
            },
        ]
    )
    assert any(a.startswith("inferred") for a in actions)
    by_req = {r["requirement"]: r["where_to_secure"] for r in reqs}
    assert by_req["Online application form"] == "LSPU Online Admission"
    assert by_req["Certified True Copy (Report Card and/or TOR)"] == "Client"

    proc, person, split_actions = _split_processing_and_personnel(
        "1 and ½ hours Guidance Staff and Interns", ""
    )
    assert "repaired_processing_time_personnel_split" in split_actions
    assert "1 and 1/2 hours" in proc.replace("½", "1/2")
    assert "Guidance" in person
    assert "Interns" in person

    rescued = rescue_charter_v2_service(
        {
            "service_title": "LSPU Entrance Examination",
            "office_division": "Guidance Office",
            "classification": "Complex",
            "transaction_type": "G2C",
            "who_may_avail": "Applicants",
            "requirements": [
                {"requirement": "Online application form", "where_to_secure": "[NEEDS REVIEW]"},
                {
                    "requirement": "Certified True Copy (Report Card and/or TOR)",
                    "where_to_secure": "[NEEDS REVIEW]",
                },
            ],
            "steps": [
                {
                    "client_step": "Take the entrance examination.",
                    "agency_action": "Administer and score the examination.",
                    "fees": "None",
                    "processing_time": "1 and ½ hours Guidance",
                    "person_responsible": "Staff and Interns",
                }
            ],
            "total_fees": "None",
            "total_processing_time": "[NEEDS REVIEW]",
            "extraction_quality": "low_quality",
            "parser_debug": {},
        }
    )
    assert rescued["repaired_bucket"] != "low_quality"
    assert rescued["repaired_bucket"] in {"recommended", "needs_review"}
    step = rescued["service_fields"]["steps"][0]
    assert "Guidance" not in str(step["processing_time"])
    assert "Guidance" in str(step["person_responsible"]) or "Staff" in str(
        step["person_responsible"]
    )
    assert rescued["service_fields"]["total_processing_time"] not in {
        "[NEEDS REVIEW]",
        None,
        "",
    }


def test_student_admission_interview_not_low_quality_when_structurally_usable():
    rescued = rescue_charter_v2_service(
        {
            "service_title": "Student Admission Interview",
            "office_division": "Admissions Office",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "Applicants",
            "requirements": [
                {"requirement": "Form 138 / TOR", "where_to_secure": ""},
                {"requirement": "Certificate of Good Moral Character", "where_to_secure": ""},
                {"requirement": "Birth Certificate", "where_to_secure": ""},
                {"requirement": "Marriage Certificate", "where_to_secure": ""},
                {"requirement": "2x2 picture", "where_to_secure": ""},
            ],
            "steps": [
                {
                    "client_step": "Attend the admission interview.",
                    "agency_action": "Conduct interview and evaluate documents.",
                    "fees": "None",
                    "processing_time": "30 minutes",
                    "person_responsible": "RESPONSIBLE Admissions Staff",
                }
            ],
            "total_fees": "None",
            "total_processing_time": "30 minutes",
            "extraction_quality": "low_quality",
            "parser_debug": {},
        }
    )
    assert rescued["audience"] == "student_facing"
    assert rescued["repaired_bucket"] != "low_quality"
    reqs = {
        r["requirement"]: r["where_to_secure"] for r in rescued["service_fields"]["requirements"]
    }
    assert reqs["Form 138 / TOR"] == "SHS / Previous HEI"
    assert reqs["Birth Certificate"] == "PSA"
    assert reqs["2x2 picture"] == "Client"


def test_library_service_needs_review_when_fee_incomplete():
    rescued = rescue_charter_v2_service(
        {
            "service_title": "Library Circulation Service",
            "office_division": "University Library",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "Students",
            "requirements": [
                {"requirement": "LSPU ID / Borrower's Card", "where_to_secure": ""}
            ],
            "steps": [
                {
                    "client_step": "Present borrower's card.",
                    "agency_action": "Issue borrowed materials.",
                    "fees": "2 pesos per",
                    "processing_time": "5 minutes",
                    "person_responsible": "[NEEDS REVIEW]",
                }
            ],
            "total_fees": "2 pesos per",
            "total_processing_time": "5 minutes",
            "extraction_quality": "needs_review",
            "parser_debug": {},
        }
    )
    assert rescued["audience"] == "student_facing"
    assert rescued["repaired_bucket"] in {"needs_review", "low_quality"}
    assert rescued["repaired_bucket"] != "recommended"


def test_internal_iso_qa_bac_hr_stay_non_recommended():
    for title, office in (
        ("ISO Internal Audit", "Internal Audit Unit"),
        ("Quality Assurance Document Control", "Quality Assurance Office"),
        ("BAC Resolution Preparation", "Bids and Awards Committee"),
        ("HR employee records update", "Human Resource Management Office"),
        ("Procurement of Supplies", "Procurement Unit"),
    ):
        rescued = rescue_charter_v2_service(
            {
                "service_title": title,
                "office_division": office,
                "classification": "Complex",
                "transaction_type": "G2G",
                "who_may_avail": "End-users / Offices",
                "requirements": [
                    {"requirement": "Request Form", "where_to_secure": "End-user"}
                ],
                "steps": [
                    {
                        "client_step": "Submit request.",
                        "agency_action": "Process request.",
                        "fees": "None",
                        "processing_time": "1 day",
                        "person_responsible": "Officer",
                    }
                ],
                "total_fees": "None",
                "total_processing_time": "1 day",
                "extraction_quality": "clean",
                "parser_debug": {},
            }
        )
        assert rescued["repaired_bucket"] != "recommended", title
        assert rescued["audience"] == "internal", title


def test_split_glued_requirement_where_pairs():
    from app.services.citizen_charter_rescue import _split_glued_requirement_where

    cases = [
        ("LSPU ID BAO", "", "LSPU ID", "Business Affairs Office"),
        ("COR Registrar", "", "Certificate of Registration", "Registrar's Office"),
        ("Student ID Client/Student", "", "Student ID", "Client/Student"),
        (
            "Online application form LSPU Online Admission",
            "",
            "Online application form",
            "LSPU Online Admission",
        ),
        (
            "Certified True Copy Report Card and/or TOR Client",
            "",
            "Certified True Copy of Report Card and/or TOR",
            "Client",
        ),
    ]
    for req, where, expected_req, expected_where in cases:
        got_req, got_where, actions = _split_glued_requirement_where(req, where)
        assert got_req == expected_req, req
        assert got_where == expected_where, req
        assert "split_glued_requirement_where" in actions


def test_public_priority_signals_exclude_internals():
    from app.services.citizen_charter_rescue import is_public_priority_charter_service

    assert is_public_priority_charter_service(
        title="ID Validation",
        office="OSAS",
        who_may_avail="All",
        transaction_type="G2C",
    )
    assert is_public_priority_charter_service(
        title="Library Circulation Service",
        office="University Library",
        who_may_avail="Students / Outside Researchers",
        transaction_type="G2C",
    )
    for title, office in (
        ("ISO Internal Audit Process", "Internal Audit Unit"),
        ("Recognition Process", "Board Secretary"),
        ("Reports for External Agency Requests", "Planning Office"),
        ("Legal Consultation", "Legal Office"),
        ("Preventive Maintenance", "Physical Plant"),
        ("Procurement of Office Supplies", "Procurement Unit"),
    ):
        assert not is_public_priority_charter_service(
            title=title,
            office=office,
            who_may_avail="Offices / End-users",
            transaction_type="G2G",
        ), title


def _complete_steps(n: int = 3, minutes: int = 1) -> list[dict]:
    steps = []
    for i in range(1, n + 1):
        steps.append(
            {
                "client_step": f"Complete client step {i}.",
                "agency_action": f"Complete agency action {i}.",
                "fees": "None",
                "processing_time": f"{minutes} minute" if minutes == 1 else f"{minutes} minutes",
                "person_responsible": "Staff",
            }
        )
    return steps


def test_public_priority_repair_recovers_clearance_total_and_recommends():
    for title in (
        "Signing of Semestral Clearances",
        "Signing of General Clearances",
    ):
        steps = _complete_steps(4, 1)
        rescued = rescue_charter_v2_service(
            {
                "service_title": title,
                "office_division": "OSAS",
                "classification": "Simple",
                "transaction_type": "G2C",
                "who_may_avail": "Graduating Students",
                "requirements": [
                    {"requirement": "Semestral Clearance", "where_to_secure": "OSAS"}
                ],
                "steps": steps,
                "total_fees": "None",
                "total_processing_time": "[NEEDS REVIEW]",
                "extraction_quality": "clean",
                "parser_debug": {
                    "detected_requirements": [
                        {"requirement": "Semestral Clearance", "where_to_secure": "OSAS"}
                    ],
                    "detected_step_rows": steps,
                },
            }
        )
        assert rescued["public_priority_service"] is True, title
        assert rescued["service_fields"]["total_processing_time"] == "4 minutes", title
        assert rescued["repaired_bucket"] == "recommended", title
        assert "[NEEDS REVIEW]" not in rescued["content"].split("Source Information", 1)[0]
        assert "Not specified" not in rescued["content"].split("Source Information", 1)[0]


def test_public_priority_entrance_exam_preserves_compound_total():
    steps = _complete_steps(3, 1)
    rescued = rescue_charter_v2_service(
        {
            "service_title": "LSPU Entrance Examination",
            "office_division": "Admission Office",
            "classification": "Complex",
            "transaction_type": "G2C",
            "who_may_avail": "Student-applicants",
            "requirements": [
                {
                    "requirement": "Online application form LSPU Online Admission",
                    "where_to_secure": "",
                }
            ],
            "steps": steps,
            "total_fees": "None",
            "total_processing_time": "[NEEDS REVIEW]",
            "extraction_quality": "clean",
            "parser_debug": {
                "cleaned_service_block": (
                    "TOTAL: None | 1–3 days, 1 hour and 45 minutes"
                ),
                "detected_requirements": [
                    {
                        "requirement": "Online application form LSPU Online Admission",
                        "where_to_secure": "",
                    }
                ],
                "detected_step_rows": steps,
            },
        }
    )
    assert rescued["public_priority_service"] is True
    assert rescued["service_fields"]["total_processing_time"] == (
        "1–3 days, 1 hour and 45 minutes"
    )
    reqs = rescued["service_fields"]["requirements"]
    assert reqs[0]["requirement"] == "Online application form"
    assert reqs[0]["where_to_secure"] == "LSPU Online Admission"
    assert rescued["repaired_bucket"] in {"recommended", "needs_review"}
    assert rescued["repaired_bucket"] != "low_quality"


def test_public_priority_rebuilds_body_from_detected_fields():
    steps = _complete_steps(3, 2)
    rescued = rescue_charter_v2_service(
        {
            "service_title": "Assessment of Fees",
            "office_division": "Accounting Office",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "Students",
            "requirements": [
                {"requirement": "COR Registrar", "where_to_secure": ""},
                {"requirement": "Student ID Client/Student", "where_to_secure": ""},
            ],
            "steps": [
                {
                    "client_step": "Present documents.",
                    "agency_action": "[NEEDS REVIEW]",
                    "fees": "None",
                    "processing_time": "2 minutes",
                    "person_responsible": "Staff",
                }
            ],
            "total_fees": "None",
            "total_processing_time": "[NEEDS REVIEW]",
            "extraction_quality": "clean",
            "parser_debug": {
                "detected_requirements": [
                    {"requirement": "COR Registrar", "where_to_secure": ""},
                    {"requirement": "Student ID Client/Student", "where_to_secure": ""},
                ],
                "detected_step_rows": steps,
            },
        }
    )
    assert rescued["public_priority_service"] is True
    assert rescued["public_priority_repaired"] is True
    body = rescued["content"].split("Source Information", 1)[0]
    assert "Certificate of Registration" in body
    assert "Registrar" in body
    assert "Student ID" in body
    assert "Client/Student" in body
    assert rescued["service_fields"]["total_processing_time"] == "6 minutes"
    assert rescued["repaired_bucket"] in {"recommended", "needs_review"}
    assert rescued["repaired_bucket"] != "low_quality"


def test_public_priority_minor_issues_stay_needs_review_not_low_quality():
    rescued = rescue_charter_v2_service(
        {
            "service_title": "Routine Medical and Dental Services",
            "office_division": "University Health Service",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "Students",
            "requirements": [],
            "checklist_blank": True,
            "steps": [
                {
                    "client_step": "Present Student ID.",
                    "agency_action": "Provide consultation.",
                    "fees": "None",
                    "processing_time": "15 minutes",
                    "person_responsible": "Nurse / Dentist",
                }
            ],
            "total_fees": "None",
            "total_processing_time": "[NEEDS REVIEW]",
            "extraction_quality": "needs_review",
            "parser_debug": {
                "detected_step_rows": [
                    {
                        "client_step": "Present Student ID.",
                        "agency_action": "Provide consultation.",
                        "fees": "None",
                        "processing_time": "15 minutes",
                        "person_responsible": "Nurse / Dentist",
                    }
                ],
            },
        }
    )
    assert rescued["public_priority_service"] is True
    assert rescued["repaired_bucket"] != "low_quality"
    assert rescued["repaired_bucket"] in {"recommended", "needs_review"}


def test_public_priority_summary_chips_and_diagnostics_sort():
    from app.services.citizen_charter_rescue import summarize_rescue_results
    from app.services.citizen_charter_services import build_charter_generation_report

    good = rescue_charter_v2_service(
        {
            "service_title": "ID Validation",
            "office_division": "OSAS",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "All",
            "requirements": [
                {"requirement": "COR", "where_to_secure": "Registrar"},
                {"requirement": "Student ID", "where_to_secure": "BAO"},
            ],
            "steps": _complete_steps(3, 1),
            "total_fees": "None",
            "total_processing_time": "3 minutes",
            "extraction_quality": "clean",
            "parser_debug": {"detected_step_rows": _complete_steps(3, 1)},
        }
    )
    internal = rescue_charter_v2_service(
        {
            "service_title": "ISO Internal Audit Process",
            "office_division": "Internal Audit Unit",
            "classification": "Complex",
            "transaction_type": "G2G",
            "who_may_avail": "Offices",
            "requirements": [{"requirement": "Memo", "where_to_secure": "IAU"}],
            "steps": _complete_steps(2, 1),
            "total_fees": "None",
            "total_processing_time": "2 minutes",
            "extraction_quality": "clean",
            "parser_debug": {},
        }
    )
    summary = summarize_rescue_results([good, internal])
    assert summary["public_priority_found"] >= 1
    assert summary["public_priority_recommended"] >= 1
    assert summary["public_priority_low_quality"] == 0
    assert good["public_priority_service"] is True
    assert internal["public_priority_service"] is False
    assert internal["repaired_bucket"] != "recommended"

    report = build_charter_generation_report(
        detected_service_blocks=2,
        merged_split_services=0,
        recommended_services=1,
        needs_review_services=1,
        low_quality_artifacts=0,
        rag_only_references=0,
        public_priority_found=summary["public_priority_found"],
        public_priority_recommended=summary["public_priority_recommended"],
        public_priority_needs_review=summary["public_priority_needs_review"],
        public_priority_low_quality=summary["public_priority_low_quality"],
        public_priority_repaired=summary["public_priority_repaired"],
        public_priority_blocked_by_article_body=summary[
            "public_priority_blocked_by_article_body"
        ],
        priority_service_diagnostics=summary["priority_service_diagnostics"],
    )
    assert report["public_priority_found"] == summary["public_priority_found"]
    id_row = next(
        item
        for item in report["priority_service_diagnostics"]
        if item["title"] == "ID Validation"
    )
    assert "body_has_needs_review" in id_row
    assert "detected_requirement_count" in id_row
    assert id_row["is_public_priority"] is True
    # Public priority found rows sort ahead of not-found placeholders.
    titles = [item["title"] for item in report["priority_service_diagnostics"]]
    assert titles[0] == "ID Validation" or titles.index("ID Validation") == 0 or (
        next(i for i, t in enumerate(titles) if t == "ID Validation")
        <= next(
            i
            for i, item in enumerate(report["priority_service_diagnostics"])
            if item.get("found") is False
        )
    )
    found_titles = [
        item["title"]
        for item in report["priority_service_diagnostics"]
        if item.get("found")
    ]
    assert found_titles and found_titles[0] == "ID Validation"


def test_routine_medical_requires_three_steps_for_recommended():
    two_steps = [
        {
            "client_step": "Write name, course, year and section.",
            "agency_action": "Receive student information.",
            "fees": "None",
            "processing_time": "1 minute",
            "person_responsible": "Nurse",
        },
        {
            "client_step": "Undergo consultation.",
            "agency_action": "Provide medical or dental consultation.",
            "fees": "None",
            "processing_time": "10 minutes",
            "person_responsible": "Physician / Dentist",
        },
    ]
    rescued = rescue_charter_v2_service(
        {
            "service_title": "Routine Medical and Dental Services",
            "office_division": "University Health Service",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "Students",
            "requirements": [],
            "checklist_blank": True,
            "steps": two_steps,
            "total_fees": "None",
            "total_processing_time": "11 minutes",
            "extraction_quality": "clean",
            "parser_debug": {"detected_step_rows": two_steps, "checklist_blank": True},
        }
    )
    assert rescued["repaired_bucket"] != "recommended"
    assert rescued["required_step_count_met"] is False
    assert any("required_step_count" in b for b in rescued["remaining_blockers"])

    three_steps = two_steps + [
        {
            "client_step": "Sign in the logbook.",
            "agency_action": "Record the transaction.",
            "fees": "None",
            "processing_time": "1 minute",
            "person_responsible": "Nurse",
        }
    ]
    rescued_ok = rescue_charter_v2_service(
        {
            "service_title": "Routine Medical and Dental Services",
            "office_division": "University Health Service",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "Students",
            "requirements": [],
            "checklist_blank": True,
            "steps": three_steps,
            "total_fees": "None",
            "total_processing_time": "12 minutes",
            "extraction_quality": "clean",
            "parser_debug": {"detected_step_rows": three_steps, "checklist_blank": True},
        }
    )
    assert rescued_ok["required_step_count_met"] is True
    assert rescued_ok["repaired_bucket"] == "recommended"


def test_public_priority_rebuilds_body_when_placeholders_block_bucket():
    steps = _complete_steps(3, 2)
    rescued = rescue_charter_v2_service(
        {
            "service_title": "Releasing of Clearance",
            "office_division": "Registrar's Office",
            "classification": "Simple",
            "transaction_type": "G2C",
            "who_may_avail": "Students",
            "requirements": [
                {"requirement": "COR", "where_to_secure": ""},
                {"requirement": "Student ID", "where_to_secure": ""},
            ],
            "steps": [
                {
                    "client_step": "Present COR.",
                    "agency_action": "[NEEDS REVIEW]",
                    "fees": "None",
                    "processing_time": "2 minutes",
                    "person_responsible": "Staff",
                }
            ],
            "total_fees": "None",
            "total_processing_time": "[NEEDS REVIEW]",
            "extraction_quality": "clean",
            "parser_debug": {
                "detected_requirements": [
                    {"requirement": "COR", "where_to_secure": ""},
                    {"requirement": "Student ID", "where_to_secure": ""},
                ],
                "detected_step_rows": steps,
            },
        }
    )
    assert rescued["public_priority_service"] is True
    assert rescued["body_rebuilt_from_detected_fields"] is True
    assert rescued["article_body_status"] in {"clean", "has_not_specified", "has_needs_review"}
    body_main = rescued["content"].split("Source Information", 1)[0]
    assert "Certificate of Registration" in body_main or "COR" in body_main
    assert rescued["repaired_bucket"] != "low_quality"

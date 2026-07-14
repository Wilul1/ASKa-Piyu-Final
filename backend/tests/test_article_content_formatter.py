import json

from app.services.admin.article_candidate_generator import (
    detect_mixed_article_scope,
    generate_candidates_from_preview,
)
from app.services.article_content_formatter import (
    build_clean_overview,
    extract_embedded_article_metadata,
    format_article_content,
    merge_article_content_update,
    strip_embedded_article_metadata,
)

COUNSELING_PROCESS_SOURCE = (
    "This phase focuses on the counseling process per se. "
    "The process may include the following: "
    "3.1. Conference consultation with the client, parent/guardian, and institution personnel. "
    "3.2. Follow-up If the counseling process is still open or the goal has not been achieved, "
    "the counselor updates the client's status. This may require another appointment. "
    "3.3. Referral The counselor may refer the client to other professionals or experts "
    "who can help with the concern. "
    "The Code of Ethics for Registered and Licensed Guidance Counselors is considered "
    "in the virtual counseling process."
)

POLICY_SOURCE = (
    "The Modified Grading Policy During the pandemic, shall be observed: "
    "4.1. The university will continue using the numerical grading system. "
    "4.2. Additional rules apply to all students."
)

REQUIREMENT_SOURCE = (
    "Applicants must submit the following requirements:\n"
    "1. Birth certificate\n"
    "2. Transcript of records\n"
    "Submit completed forms to the registrar before the deadline."
)

PLAIN_SOURCE = (
    "Students may visit the office during regular business hours for general inquiries "
    "about campus services and student support resources."
)

COMPREHENSIVE_EXAM_SOURCE = (
    "Comprehensive Examination Requirement. "
    "1. The student must have finished all academic courses and must have no incomplete grades. "
    "2. The student academic records must be evaluated by the Registrar and endorsed to the Dean of Graduate Studies. "
    "3. Clearance from the accounting office must be secured. "
    "4. An application form with the required documents must be submitted to the Office of the Graduate Studies."
)

UNDERGRAD_GRADUATION_SOURCE = (
    "Undergraduate Graduation Requirements include the following: "
    "1. Tree planting requirement must be completed. "
    "2. Clearance requirement must be secured from concerned offices. "
    "3. Residency requirement must be satisfied. "
    "4. Graduation ceremony attendance is required unless excused."
)

FACE_TO_FACE_SOURCE = (
    "Operationalizing Limited Face-to-Face Classes may include the following: "
    "1. Not all students are automatically allowed. "
    "2. Students doing OJT or Practicum inside the campus. "
    "3. Students who cannot do online learning because they do not have personal gadgets or internet connection. "
    "4. Students living in accredited dormitories/private dormitories near the campus. "
    "5. Students taking laboratory subjects where required skills cannot be learned online or offline. "
    "6. If conditions change, the university may revise the list. "
    "7. Below are additional reminders for campuses."
)

VALIDATION_SOURCE = (
    "Validation Requirements: "
    "2.1. A holder of a degree who transfers or registers in this University shall be given credits "
    "for equivalent courses taken without need for validating them, but such credits shall not exceed "
    "50 percent of the total number of credits required for graduation. "
    "2.2. A student transferring from any recognized institution and who possesses an Associate course "
    "or its equivalent of 72 units of work may be enrolled without validation of subjects sought for advanced credits. "
    "2.3. A student transferring from another College/University within LSPU System who has earned units "
    "in a program leading to the course to be pursued within the University will be given credits for "
    "equivalent courses without validating them."
)

ROLE_SOURCE = (
    "Mental Health Services Workgroup responsibilities:\n"
    "A. Campus Directors / Administrators - oversee campus implementation and coordination.\n"
    "B. Academic Heads / OSA Director and Chairpersons - support referral and monitoring of students.\n"
    "C. Guidance Counselors - provide counseling and escalate concerns when needed."
)

INLINE_ROLE_SOURCE = (
    "The workgroup responsibilities are as follows: "
    "A. Campus Directors / Administrators - oversee campus implementation - coordinate with offices. "
    "B. Academic Heads / OSA Director and Chairpersons - support referral - monitor student concerns. "
    "C. Guidance Counselors - provide counseling - escalate concerns when needed."
)

BROAD_ADMISSION_SOURCE = (
    "Admission is open to all students under the university admission policy. "
    "The institution observes non-discrimination regardless of sex or religion. "
    "Foreign students may apply under separate rules. "
    "An admission test or entrance examination may be required. "
    "A qualifying examination may also be administered. "
    "An interview or screening may be part of the process. "
    "Applicants must meet the general weighted average required by the college. "
    "Enrollment and registration follow the academic calendar."
)

MESSY_OCR_TITLE = "or submitted"


def test_overview_avoids_repeated_title_type_phrases():
    admission = build_clean_overview("Admission Requirements", "requirement", "requirement_list")
    assert "requirements for Admission Requirements" not in admission
    assert "admission requirements" in admission.lower()
    assert "related conditions for students" in admission.lower()

    counseling = build_clean_overview("Counseling Process", "procedure", "procedure_steps")
    assert "process for Counseling Process" not in counseling
    assert "counseling process" in counseling.lower()

    policy = build_clean_overview("Modified Grading Policy", "policy", "policy_clauses")
    assert "policy on Modified Grading Policy" not in policy
    assert "modified grading policy" in policy.lower()

    exam = build_clean_overview(
        "Comprehensive Examination Requirement",
        "requirement",
        "requirement_list",
    )
    assert "requirements for Comprehensive Examination Requirement" not in exam
    assert "comprehensive examination" in exam.lower()


def test_counseling_process_formats_overview_process_and_notes():
    formatted = format_article_content(
        "Counseling Process",
        "procedure",
        COUNSELING_PROCESS_SOURCE,
        summary="Short counseling summary.",
    )

    assert "Overview" in formatted.display_content
    assert "Process" in formatted.display_content
    assert "Important Notes" in formatted.display_content
    assert "1. Conference" in formatted.display_content
    assert "2. Follow-up" in formatted.display_content
    assert "3. Referral" in formatted.display_content
    assert "Step " not in formatted.display_content
    assert "process for Counseling Process" not in formatted.display_content
    assert formatted.official_source_excerpt == COUNSELING_PROCESS_SOURCE
    assert any("Process" in section["heading"] for section in formatted.sections)


def test_numbered_clauses_become_separate_process_items():
    formatted = format_article_content(
        "Counseling Process",
        "procedure",
        COUNSELING_PROCESS_SOURCE,
    )

    process_section = next(
        section for section in formatted.sections if "Process" in section["heading"]
    )
    assert "Conference" in process_section["body"]
    assert "Follow-up" in process_section["body"]
    assert "Referral" in process_section["body"]


def test_policy_articles_use_key_points_not_process_steps():
    formatted = format_article_content(
        "Modified Grading Policy",
        "policy",
        POLICY_SOURCE,
    )

    assert "Key Points" in formatted.display_content
    assert "Process" not in formatted.display_content
    assert "4.1" in formatted.display_content
    assert "4.2" in formatted.display_content


def test_requirement_articles_show_requirements_section():
    formatted = format_article_content(
        "Admission Requirements",
        "requirement",
        REQUIREMENT_SOURCE,
    )

    assert "Requirements" in formatted.display_content
    assert "Birth certificate" in formatted.display_content
    assert "Transcript of records" in formatted.display_content
    assert "Instructions / How to Submit" in formatted.display_content
    assert "Step " not in formatted.display_content


def test_plain_content_is_not_over_formatted():
    formatted = format_article_content(
        "Student Services",
        "information",
        PLAIN_SOURCE,
    )

    assert "Process" not in formatted.display_content
    assert "Key Points" not in formatted.display_content
    assert PLAIN_SOURCE in formatted.display_content
    assert formatted.official_source_excerpt == PLAIN_SOURCE


def test_comprehensive_exam_no_duplicate_overview_or_broken_notes():
    formatted = format_article_content(
        "Comprehensive Examination Requirement",
        "requirement",
        COMPREHENSIVE_EXAM_SOURCE,
    )

    assert "Overview" in formatted.display_content
    assert "This article explains the requirements" in formatted.display_content
    assert "requirements for Comprehensive Examination Requirement" not in formatted.display_content
    assert "Requirements" in formatted.display_content
    assert "finished all academic courses" in formatted.display_content
    # Overview must not dump the full requirement list.
    overview = next(section for section in formatted.sections if section["heading"] == "Overview")
    assert "finished all academic courses" not in overview["body"]
    notes_sections = [
        section for section in formatted.sections if section["heading"] in {"Notes", "Important Notes"}
    ]
    for section in notes_sections:
        assert "finished all academic courses" not in section["body"]
    instruction_sections = [
        section
        for section in formatted.sections
        if section["heading"] == "Instructions / How to Submit"
    ]
    assert instruction_sections == []


def test_undergraduate_graduation_no_duplicate_overview_and_notes():
    formatted = format_article_content(
        "Undergraduate Graduation Requirements",
        "requirement",
        UNDERGRAD_GRADUATION_SOURCE,
    )

    assert "Requirements" in formatted.display_content
    overview = next(section for section in formatted.sections if section["heading"] == "Overview")
    assert overview["body"].startswith("This article explains the undergraduate graduation requirements")
    assert "Tree planting" not in overview["body"]
    assert "Clearance" not in overview["body"]
    assert "requirements for Undergraduate Graduation Requirements" not in overview["body"]
    assert "Tree planting requirement" in formatted.display_content
    assert "Clearance requirement" in formatted.display_content
    notes_sections = [
        section for section in formatted.sections if section["heading"] in {"Notes", "Important Notes"}
    ]
    for section in notes_sections:
        assert "Tree planting" not in section["body"]


def test_face_to_face_uses_eligibility_not_fake_process_steps():
    formatted = format_article_content(
        "Operationalizing Limited Face-to-Face Classes",
        "policy",
        FACE_TO_FACE_SOURCE,
    )

    assert "Eligibility / Conditions" in formatted.display_content
    assert "Process" not in formatted.display_content
    assert "1. Not\n" not in formatted.display_content
    assert "2. Students\n" not in formatted.display_content
    assert "Students doing OJT" in formatted.display_content
    assert "Step " not in formatted.display_content
    overview = next(section for section in formatted.sections if section["heading"] == "Overview")
    assert "conditions for" in overview["body"].lower()
    assert "Operationalizing Limited Face-to-Face Classes" not in overview["body"] or "conditions" in overview["body"].lower()


def test_broad_mixed_article_is_needs_review():
    candidate = {
        "title": "Campus Entry Rules",
        "content": BROAD_ADMISSION_SOURCE,
        "source_sections": [
            "Admissions > Policy",
            "Admissions > Foreign Students",
            "Admissions > Entrance Exam",
            "Admissions > Interview",
            "Admissions > Enrollment",
        ],
        "student_intents": ["requirements", "policy", "how_to"],
        "document_type": "requirement",
        "article_type": "requirement",
    }
    assert detect_mixed_article_scope(candidate) is True

    preview = {
        "knowledge_units": [
            {
                "unit_index": 1,
                "title": "Campus Entry Rules",
                "content": BROAD_ADMISSION_SOURCE,
                "content_type": "document_chunk",
                "hierarchy_path": "Admissions > Policy",
                "word_count": 160,
                "status": "OK",
                "metadata": {"section_heading": "Campus Entry Rules"},
            }
        ],
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    candidates = result["all_candidates"] or result["needs_review_candidates"] or result["recommended_candidates"]
    assert candidates
    candidate_result = candidates[0]
    assert candidate_result.get("planner_bucket") != "recommended"
    reasons = candidate_result.get("review_reason") or []
    assert "mixed_article_scope" in reasons
    assert "should be reviewed before publishing" in (candidate_result.get("summary") or "").lower()


def test_validation_requirements_keep_numbering_without_step_prefix():
    formatted = format_article_content(
        "Validation Requirements",
        "requirement",
        VALIDATION_SOURCE,
    )

    assert "Requirements" in formatted.display_content
    assert "2.1." in formatted.display_content
    assert "2.2." in formatted.display_content
    assert "Step 2.1" not in formatted.display_content
    assert "Step 2.2" not in formatted.display_content
    assert "requirements for Validation Requirements" not in formatted.display_content
    notes_sections = [
        section for section in formatted.sections if section["heading"] in {"Notes", "Important Notes"}
    ]
    for section in notes_sections:
        assert "holder of a degree" not in section["body"]


def test_role_responsibility_list_formatting():
    formatted = format_article_content(
        "Mental Health Services Workgroup",
        "information",
        ROLE_SOURCE,
    )

    assert "Roles and Responsibilities" in formatted.display_content
    assert "Campus Directors / Administrators" in formatted.display_content
    assert "Academic Heads / OSA Director and Chairpersons" in formatted.display_content
    assert formatted.content_pattern == "role_responsibility_list"
    assert "internal_facing" in formatted.formatting_notes


def test_inline_role_responsibility_list_formatting():
    formatted = format_article_content(
        "Mental Health Services Workgroup",
        "information",
        INLINE_ROLE_SOURCE,
    )

    assert "Roles and Responsibilities" in formatted.display_content
    assert "1. Campus Directors / Administrators" in formatted.display_content
    assert "2. Academic Heads / OSA Director and Chairpersons" in formatted.display_content
    assert "- oversee campus implementation" in formatted.display_content
    assert formatted.content_pattern == "role_responsibility_list"


def test_internal_role_article_is_needs_review_not_recommended():
    preview = {
        "knowledge_units": [
            {
                "unit_index": 1,
                "title": "Mental Health Services Workgroup",
                "content": INLINE_ROLE_SOURCE,
                "content_type": "document_chunk",
                "hierarchy_path": "Services > Workgroup",
                "word_count": 120,
                "status": "OK",
                "metadata": {"section_heading": "Mental Health Services Workgroup"},
            }
        ],
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    candidates = result["all_candidates"] or result["needs_review_candidates"] or result["recommended_candidates"]
    assert candidates
    candidate = candidates[0]
    assert candidate.get("planner_bucket") != "recommended"
    assert candidate.get("needs_review") is True or candidate.get("planner_bucket") in {
        "needs_review",
        "low_quality",
        "rag_only",
    }
    reasons = candidate.get("review_reason") or []
    metadata = extract_embedded_article_metadata(candidate.get("content") or "")
    assert "internal_role_list" in reasons or metadata.get("content_pattern") == "role_responsibility_list"
    assert "Roles and Responsibilities" in (candidate.get("content") or "")
    assert "should be reviewed before publishing" in (candidate.get("summary") or "").lower()
    assert "internal roles and responsibilities" in (candidate.get("summary") or "").lower()


def test_messy_ocr_titles_flagged_for_cleanup():
    formatted = format_article_content(
        MESSY_OCR_TITLE,
        "information",
        "Capable of providing incomplete OCR fragment text for review only.",
    )
    assert formatted.content_pattern in {"messy_ocr", "messy_fragments"}
    assert "needs_cleanup" in formatted.formatting_notes


def test_fragment_labels_do_not_become_step_titles():
    formatted = format_article_content(
        "Limited Campus Access",
        "policy",
        FACE_TO_FACE_SOURCE,
    )
    for bad in ("1. Not", "2. Students", "6. If", "7. Below"):
        assert f"{bad}\n" not in formatted.display_content + "\n"


def test_preview_candidate_preserves_official_source_excerpt_in_metadata():
    preview = {
        "knowledge_units": [
            {
                "unit_index": 1,
                "title": "Counseling Process",
                "content": COUNSELING_PROCESS_SOURCE,
                "content_type": "document_chunk",
                "hierarchy_path": "Counseling > Process",
                "word_count": 120,
                "status": "OK",
                "metadata": {"section_heading": "Counseling Process"},
            }
        ],
        "structured": {"formatted_text": "Counseling"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    candidates = result["all_candidates"] or result["recommended_candidates"]
    assert candidates

    content = candidates[0]["content"]
    assert "Overview" in content
    metadata = extract_embedded_article_metadata(content)
    assert metadata.get("official_source_excerpt")
    assert "3.1" in metadata["official_source_excerpt"]
    assert strip_embedded_article_metadata(content) != metadata["official_source_excerpt"]


def test_merge_article_content_update_preserves_metadata_excerpt():
    original = (
        "Overview\nFormatted body.\n\n----EXTRACTED METADATA----\n"
        + json.dumps({"official_source_excerpt": COUNSELING_PROCESS_SOURCE})
    )
    updated = merge_article_content_update(original, "Overview\nEdited student-friendly body.")
    metadata = extract_embedded_article_metadata(updated)

    assert "Edited student-friendly body." in updated
    assert metadata["official_source_excerpt"] == COUNSELING_PROCESS_SOURCE
    assert "3.1" in metadata["official_source_excerpt"]


def test_generate_preview_remains_preview_only():
    preview = {
        "knowledge_units": [
            {
                "unit_index": 1,
                "title": "Counseling Process",
                "content": COUNSELING_PROCESS_SOURCE,
                "content_type": "document_chunk",
                "hierarchy_path": "Counseling",
                "word_count": 120,
                "status": "OK",
                "metadata": {},
            }
        ],
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["save_mode"] == "preview_only"
    assert result["preview_count"] >= 1
    from app.models.db_models import PublishedArticle
    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).filter(PublishedArticle.title == "Counseling Process").all()
        assert rows == []
    finally:
        session.close()

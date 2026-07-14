import pytest

from app.services.admin.article_candidate_generator import (
    _passes_recommendation_gate,
    generate_candidates_from_preview,
)
from app.db.session import get_session_factory
from app.models.db_models import PublishedArticle
from tests.db_helpers import cleanup_all_published_articles


@pytest.fixture(autouse=True)
def _deterministic_taxonomy_classification(monkeypatch):
    """Article-candidate tests must not depend on Groq LLM classification."""
    monkeypatch.setattr(
        "app.services.knowledge_taxonomy.settings.groq_api_key",
        None,
    )


def _cleanup_all():
    cleanup_all_published_articles()


_RECOMMENDABLE_TITLES = (
    "Admission Requirements",
    "Grading System",
    "School Uniforms",
    "Graduation Requirements",
    "Leave of Absence",
    "Academic Load and Changes",
    "Registration Changes Policy",
    "Guidance and Counseling Services",
)


def _good_unit(index: int, title: str | None = None) -> dict:
    base = _RECOMMENDABLE_TITLES[index % len(_RECOMMENDABLE_TITLES)]
    title = title or f"{base} Section {index}"
    return {
        "unit_index": index,
        "title": title,
        "content": (
            f"{title} student requirements and procedure. "
            "Students must submit documents and follow the steps for enrollment. "
            "How to complete the request and where fees or forms are needed. "
        )
        * 6,
        "content_type": "document_chunk",
        "hierarchy_path": f"{title} Topics > {title}",
        "word_count": 120,
        "status": "OK",
        "metadata": {"section_heading": title, "document_type": "information"},
    }


def test_generic_weak_headings_filtered():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Overview", "content": "Short note.", "content_type": "document_chunk", "hierarchy_path": "1", "word_count": 3, "status": "OK", "metadata": {}},
            {"unit_index": 1, "title": "Notes", "content": "Another short note.", "content_type": "document_chunk", "hierarchy_path": "2", "word_count": 4, "status": "OK", "metadata": {}},
        ],
        "structured": {"formatted_text": "Overview"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["created_count"] == 0
    assert result["rag_only_count"] >= 1 or result["skipped_low_quality_count"] >= 1
    _cleanup_all()


def test_sentence_like_titles_are_skipped():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "This section describes how to apply for leave when documents are incomplete and students still need clarification about campus procedures before deadlines", "content": "Detailed steps are explained here." * 5, "content_type": "document_chunk", "hierarchy_path": "1", "word_count": 40, "status": "OK", "metadata": {}},
        ],
        "structured": {"formatted_text": "This section describes how to apply"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["created_count"] == 0
    assert result["rag_only_count"] >= 1 or result["skipped_low_quality_count"] >= 1
    _cleanup_all()


def test_incomplete_titles_are_skipped():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Every student accumulat", "content": "Incomplete OCR fragment with little useful meaning.", "content_type": "document_chunk", "hierarchy_path": "1", "word_count": 12, "status": "OK", "metadata": {}},
        ],
        "structured": {"formatted_text": "Every student accumulat"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["created_count"] == 0
    assert result["rag_only_count"] >= 1 or result["skipped_low_quality_count"] >= 1
    _cleanup_all()


def test_person_name_titles_are_skipped():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "GREG R. REYES, Director, Admission and Registrarship", "content": "Administrative signature block only.", "content_type": "document_chunk", "hierarchy_path": "1", "word_count": 10, "status": "OK", "metadata": {}},
        ],
        "structured": {"formatted_text": "GREG R. REYES, Director, Admission and Registrarship"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["created_count"] == 0
    assert result["rag_only_count"] >= 1 or result["skipped_low_quality_count"] >= 1
    _cleanup_all()


def test_meaningful_policy_title_kept():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Student Discipline Policy", "content": "Policy details and penalties. This is a long informative section with more than fifty words to be considered useful." * 2, "content_type": "document_chunk", "hierarchy_path": "Policies > Discipline", "word_count": 120, "status": "OK", "metadata": {"section_heading": "Student Discipline Policy"}},
        ],
        "structured": {"formatted_text": "Student Discipline Policy"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["created_count"] >= 1
    assert result["skipped_low_quality_count"] == 0
    assert result["needs_review_count"] >= 1
    assert result["recommended_candidates"] == [] or all(not item.get("needs_review") for item in result["recommended_candidates"])
    _cleanup_all()


def test_clean_heading_like_title_kept():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Admission Requirements", "content": "Students must submit the following documents and complete the listed steps before enrollment." * 2, "content_type": "document_chunk", "hierarchy_path": "Admissions > Requirements", "word_count": 70, "status": "OK", "metadata": {"section_heading": "Admission Requirements"}},
        ],
        "structured": {"formatted_text": "Admission Requirements"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["created_count"] >= 1
    assert result["skipped_low_quality_count"] == 0
    assert result["recommended_count"] >= 1
    assert result["recommended_candidates"][0]["title"] == "Admission Requirements"
    _cleanup_all()


def test_duplicate_candidates_skipped():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Form B", "content": "Content B is sufficiently long to be kept. Students must submit form requirements and follow the procedure." * 5, "content_type": "document_chunk", "hierarchy_path": "Forms > B", "word_count": 80, "status": "OK", "metadata": {"document_type": "form"}},
        ],
        "structured": {"formatted_text": "Form B"},
    }
    first = generate_candidates_from_preview(preview, filename="form.pdf", save_mode="save_drafts")
    second = generate_candidates_from_preview(preview, filename="form.pdf", save_mode="save_drafts")
    assert first["created_count"] >= 1
    assert second["skipped_duplicate_count"] >= 1
    _cleanup_all()


def test_max_candidates_limits_recommended_batch_only():
    _cleanup_all()
    units = [_good_unit(i) for i in range(120)]
    preview = {"knowledge_units": units, "structured": {"formatted_text": "Many topics"}}
    result = generate_candidates_from_preview(preview, filename="big.pdf", max_candidates=25)
    assert result["total_detected"] == 120
    assert result["blueprint_count"] >= 1
    assert result["preview_count"] <= 120
    assert result["recommended_count"] <= 25
    assert result["created_count"] == result["preview_count"]
    assert result["saved_count"] == 0
    assert len(result["recommended_candidates"]) == result["recommended_count"]
    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).filter(PublishedArticle.source_filename == "big.pdf").all()
        assert rows == []
    finally:
        session.close()
    _cleanup_all()


def test_generate_without_max_candidates_does_not_cap_recommended():
    _cleanup_all()
    units = [_good_unit(i) for i in range(40)]
    preview = {"knowledge_units": units, "structured": {"formatted_text": "Many topics"}}
    uncapped = generate_candidates_from_preview(preview, filename="uncapped.pdf")
    capped = generate_candidates_from_preview(preview, filename="capped.pdf", max_candidates=5)
    assert uncapped["recommended_count"] >= capped["recommended_count"]
    assert capped["recommended_count"] <= 5
    assert uncapped["preview_count"] == capped["preview_count"]
    assert uncapped["coverage"]
    assert uncapped["rag_only_count"] == capped["rag_only_count"]
    _cleanup_all()


def test_max_candidates_does_not_remove_source_chunks():
    units = [_good_unit(i, f"Chunk Topic {i}") for i in range(10)]
    preview = {"knowledge_units": units, "structured": {"formatted_text": "Chunk topics"}}
    before_units = list(preview["knowledge_units"])
    generate_candidates_from_preview(preview, filename="chunks.pdf", max_candidates=3)
    assert len(preview["knowledge_units"]) == len(before_units)
    assert preview["knowledge_units"] == before_units


def test_low_quality_candidates_are_not_published_publicly():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Overview", "content": "Short note.", "content_type": "document_chunk", "hierarchy_path": "1", "word_count": 3, "status": "OK", "metadata": {}},
        ],
        "structured": {"formatted_text": "Overview"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["created_count"] == 0
    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).filter(PublishedArticle.source_filename == "handbook.pdf").all()
        assert rows == []
        published_rows = session.query(PublishedArticle).filter(PublishedArticle.published == True).all()
        assert all(row.title != "Overview" for row in published_rows)
    finally:
        session.close()
    _cleanup_all()


def test_admin_can_still_inspect_source_chunks_after_candidate_limit():
    units = [
        _good_unit(i, f"{_RECOMMENDABLE_TITLES[i % len(_RECOMMENDABLE_TITLES)]} Inspect {i}")
        for i in range(6)
    ]
    preview = {"knowledge_units": units, "structured": {"formatted_text": "Inspect topics"}}
    result = generate_candidates_from_preview(preview, filename="inspect.pdf", max_candidates=2)
    assert result["recommended_count"] == 2
    assert result["total_detected"] == 6
    for unit in preview["knowledge_units"]:
        assert unit["content"]
        assert unit["title"]
        assert "Inspect" in unit["title"]


def test_requirement_and_procedure_still_work():
    _cleanup_all()
    preview_req = {
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": "Application Form",
                "content": (
                    "Document Type: Requirement / Form Document\n"
                    "Requirement Title: Application Form\n"
                    "Requirements:\n- ID\n- Photo\n"
                    "Students must submit requirements before enrollment.\n"
                )
                * 2,
                "content_type": "document_chunk",
                "hierarchy_path": "Forms > Application Form",
                "word_count": 60,
                "status": "OK",
                "metadata": {"document_type": "requirement", "form_options": "[]"},
            },
        ],
        "structured": {"formatted_text": "Application Form"},
    }
    res_req = generate_candidates_from_preview(preview_req, filename="form.pdf")
    assert res_req["created_count"] >= 1
    assert res_req["preview_count"] >= 1

    preview_proc = {
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": "Tuition Payment Procedure",
                "content": (
                    "Procedure Title: Tuition Payment\n"
                    "How to pay tuition online.\n"
                    "Requirements:\n- OR\nSteps:\n1. Pay online\n2. Submit receipt\n"
                )
                * 2,
                "content_type": "document_chunk",
                "hierarchy_path": "Procedures > Tuition Payment",
                "word_count": 100,
                "status": "OK",
                "metadata": {"document_type": "procedure"},
            },
        ],
        "structured": {"formatted_text": "Tuition Payment Procedure"},
    }
    res_proc = generate_candidates_from_preview(preview_proc, filename="proc.pdf")
    assert res_proc["created_count"] >= 1
    assert res_proc["preview_count"] >= 1
    _cleanup_all()


def _mixed_quality_preview() -> dict:
    return {
        "knowledge_units": [
            _good_unit(0, "Admission Requirements"),
            {"unit_index": 1, "title": "Appendix A", "content": "Appendix content with enough words to remain saveable as a draft article candidate." * 3, "content_type": "document_chunk", "hierarchy_path": "Appendices", "word_count": 80, "status": "OK", "metadata": {}},
            {"unit_index": 2, "title": "First Action", "content": "Action step content with enough words to remain saveable as a draft article candidate." * 3, "content_type": "document_chunk", "hierarchy_path": "Actions", "word_count": 80, "status": "OK", "metadata": {}},
            {"unit_index": 3, "title": "Monitor/evaluate student activities using institutional procedures", "content": "Long procedural row content with enough words to remain saveable as a draft article candidate." * 2, "content_type": "document_chunk", "hierarchy_path": "Rows", "word_count": 80, "status": "OK", "metadata": {}},
            {"unit_index": 4, "title": "GREG R. REYES, Director, Admission and Registrarship", "content": "Administrative signature block only with some extra words." * 2, "content_type": "document_chunk", "hierarchy_path": "Signatories", "word_count": 20, "status": "OK", "metadata": {}},
        ],
        "structured": {"formatted_text": "Mixed quality"},
    }


def test_appendix_only_titles_are_not_recommended():
    _cleanup_all()
    result = generate_candidates_from_preview(_mixed_quality_preview(), filename="handbook.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "Appendix A" not in recommended_titles
    assert "Admission Requirements" in recommended_titles
    _cleanup_all()


def test_action_step_titles_are_not_recommended():
    _cleanup_all()
    result = generate_candidates_from_preview(_mixed_quality_preview(), filename="handbook.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "First Action" not in recommended_titles
    _cleanup_all()


def test_sentence_like_titles_are_not_recommended():
    _cleanup_all()
    result = generate_candidates_from_preview(_mixed_quality_preview(), filename="handbook.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "Monitor/evaluate student activities using institutional procedures" not in recommended_titles
    _cleanup_all()


def test_incomplete_ocr_fragments_are_not_recommended():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Every student accumulat", "content": "Incomplete OCR fragment with enough words to remain saveable as a draft article candidate." * 3, "content_type": "document_chunk", "hierarchy_path": "1", "word_count": 40, "status": "OK", "metadata": {}},
            _good_unit(1, "Grading System"),
        ],
        "structured": {"formatted_text": "Mixed"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "Every student accumulat" not in recommended_titles
    assert "Grading System" in recommended_titles
    _cleanup_all()


def test_person_or_position_titles_are_not_recommended():
    _cleanup_all()
    result = generate_candidates_from_preview(_mixed_quality_preview(), filename="handbook.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "GREG R. REYES, Director, Admission and Registrarship" not in recommended_titles
    _cleanup_all()


def test_clean_heading_like_titles_are_recommended():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            _good_unit(0, "Graduation Requirements"),
            _good_unit(1, "Leave of Absence"),
        ],
        "structured": {"formatted_text": "Clean headings"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf", max_candidates=10)
    recommended_titles = [item["title"] for item in result["recommended_candidates"]]
    assert "Graduation Requirements" in recommended_titles
    assert "Leave of Absence" in recommended_titles
    _cleanup_all()


def test_overflow_candidates_remain_counted_without_auto_save():
    _cleanup_all()
    units = [_good_unit(i) for i in range(5)]
    preview = {"knowledge_units": units, "structured": {"formatted_text": "Overflow topics"}}
    result = generate_candidates_from_preview(preview, filename="overflow.pdf", max_candidates=2)
    assert result["total_detected"] == 5
    assert result["preview_count"] >= 2
    assert result["saved_count"] == 0
    assert result["recommended_count"] <= 2
    assert result["preview_count"] >= result["recommended_count"]
    assert (
        result["recommended_count"]
        + result["needs_review_count"]
        + result["consolidated_parent_count"]
        <= result["preview_count"]
    )
    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).filter(PublishedArticle.source_filename == "overflow.pdf").all()
        assert rows == []
    finally:
        session.close()
    _cleanup_all()


def test_public_kb_hides_draft_and_overflow_candidates():
    _cleanup_all()
    session = get_session_factory()()
    try:
        session.add(
            PublishedArticle(
                title="Draft Topic",
                slug="draft-topic",
                category="General Information",
                content="Draft body",
                published=False,
            )
        )
        session.add(
            PublishedArticle(
                title="Published Topic",
                slug="published-topic",
                category="General Information",
                content="Published body",
                published=True,
            )
        )
        session.commit()
        draft_titles = {row.title for row in session.query(PublishedArticle).filter(PublishedArticle.published == False).all()}
        public_titles = {row.title for row in session.query(PublishedArticle).filter(PublishedArticle.published == True).all()}
        for title in draft_titles:
            assert title not in public_titles
    finally:
        session.close()
    _cleanup_all()


def test_recommended_candidates_never_include_needs_review():
    _cleanup_all()
    units = [_good_unit(i) for i in range(8)] + [
        {"unit_index": 100, "title": "BOARD OF Regents", "content": "Board background content saved as draft." * 10, "content_type": "document_chunk", "hierarchy_path": "Board", "word_count": 80, "status": "OK", "metadata": {}},
    ]
    preview = {"knowledge_units": units, "structured": {"formatted_text": "Mixed"}}
    result = generate_candidates_from_preview(preview, filename="strict.pdf", max_candidates=10)
    for item in result["recommended_candidates"]:
        assert item.get("needs_review") is False
        assert not item.get("review_reason")
    _cleanup_all()


def test_recommended_candidates_never_include_review_reasons():
    _cleanup_all()
    result = generate_candidates_from_preview(_mixed_quality_preview(), filename="handbook.pdf", max_candidates=10)
    for item in result["recommended_candidates"]:
        assert item.get("review_reason") in (None, [])
        assert item.get("needs_review") is False
    _cleanup_all()


def test_low_category_confidence_candidates_are_not_recommended():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Student Discipline Policy", "content": "Policy details and penalties. This is a long informative section with more than fifty words to be considered useful." * 2, "content_type": "document_chunk", "hierarchy_path": "Policies > Discipline", "word_count": 120, "status": "OK", "metadata": {"section_heading": "Student Discipline Policy"}},
            _good_unit(1, "Admission Requirements"),
        ],
        "structured": {"formatted_text": "Confidence mix"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "Student Discipline Policy" not in recommended_titles
    assert "Admission Requirements" in recommended_titles
    assert any(item["title"] == "Student Discipline Policy" for item in result["needs_review_candidates"])
    _cleanup_all()


def test_administrative_background_titles_are_not_recommended():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            _good_unit(0, "Admission Requirements"),
            {"unit_index": 1, "title": "Message OF THE University President", "content": "Administrative message content with enough words to remain saveable as a draft article candidate." * 3, "content_type": "document_chunk", "hierarchy_path": "Foreword", "word_count": 80, "status": "OK", "metadata": {}},
            {"unit_index": 2, "title": "BOARD OF Regents", "content": "Board composition content with enough words to remain saveable as a draft article candidate." * 3, "content_type": "document_chunk", "hierarchy_path": "Board", "word_count": 80, "status": "OK", "metadata": {}},
            {"unit_index": 3, "title": "General Behavior", "content": "Behavior section content with enough words to remain saveable as a draft article candidate." * 3, "content_type": "document_chunk", "hierarchy_path": "Conduct", "word_count": 80, "status": "OK", "metadata": {}},
        ],
        "structured": {"formatted_text": "Admin mix"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "Admission Requirements" in recommended_titles
    assert "Message OF THE University President" not in recommended_titles
    assert "BOARD OF Regents" not in recommended_titles
    assert "General Behavior" not in recommended_titles
    _cleanup_all()


def test_useful_uncertain_titles_go_to_needs_review_candidates():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {"unit_index": 0, "title": "Student Discipline Policy", "content": "Policy details and penalties. This is a long informative section with more than fifty words to be considered useful." * 2, "content_type": "document_chunk", "hierarchy_path": "Policies > Discipline", "word_count": 120, "status": "OK", "metadata": {"section_heading": "Student Discipline Policy"}},
        ],
        "structured": {"formatted_text": "Student Discipline Policy"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    assert result["recommended_count"] == 0
    assert any(item["title"] == "Student Discipline Policy" for item in result["needs_review_candidates"])
    _cleanup_all()


def _gate_failure_preview() -> dict:
    return {
        "knowledge_units": [
            _good_unit(0, "Admission Requirements"),
            {"unit_index": 1, "title": "Leading, instigating and par", "content": "Discipline content with enough words to remain saveable as a draft article candidate." * 4, "content_type": "document_chunk", "hierarchy_path": "Conduct", "word_count": 80, "status": "OK", "metadata": {"section_heading": "Leading, instigating and par"}},
            {"unit_index": 2, "title": "Non-regular Admission", "content": "Admission content with enough words to remain saveable as a draft article candidate." * 4, "content_type": "document_chunk", "hierarchy_path": "Admissions", "word_count": 80, "status": "OK", "metadata": {"section_heading": "Non-regular Admission"}},
            {"unit_index": 3, "title": "Messages in between sessions", "content": "Administrative content with enough words to remain saveable as a draft article candidate." * 4, "content_type": "document_chunk", "hierarchy_path": "Messages", "word_count": 80, "status": "OK", "metadata": {}},
            {"unit_index": 4, "title": "Submission Policy", "content": "Submission policy content with enough words to remain saveable as a draft article candidate." * 4, "content_type": "document_chunk", "hierarchy_path": "Policies", "word_count": 80, "status": "OK", "metadata": {"section_heading": "Submission Policy"}},
        ],
        "structured": {"formatted_text": "Gate failures"},
    }


def test_recommended_information_candidates_meet_quality_threshold():
    _cleanup_all()
    result = generate_candidates_from_preview(_gate_failure_preview(), filename="gate-quality.pdf", max_candidates=10)
    for item in result["recommended_candidates"]:
        doc_type = str(item.get("document_type") or "information").lower()
        if doc_type in {"information", "handbook", "handbook_policy", "policy", "manual", "memo", "memorandum", "general_information"}:
            assert float(item["quality_score"]) >= 7.0
    _cleanup_all()


def test_recommended_candidates_meet_usefulness_threshold():
    _cleanup_all()
    result = generate_candidates_from_preview(_gate_failure_preview(), filename="gate-usefulness.pdf", max_candidates=10)
    for item in result["recommended_candidates"]:
        assert float(item["student_usefulness_score"]) >= 0
    _cleanup_all()


def test_recommended_information_candidates_meet_confidence_threshold():
    _cleanup_all()
    result = generate_candidates_from_preview(_gate_failure_preview(), filename="gate-confidence.pdf", max_candidates=10)
    for item in result["recommended_candidates"]:
        doc_type = str(item.get("document_type") or "information").lower()
        if doc_type in {"information", "handbook", "handbook_policy", "policy", "manual", "memo", "memorandum", "general_information"}:
            assert float(item["category_confidence"]) >= 0.45
    _cleanup_all()


def test_reported_invalid_titles_are_not_recommended():
    _cleanup_all()
    result = generate_candidates_from_preview(_gate_failure_preview(), filename="gate-invalid.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "Admission Requirements" in recommended_titles
    assert "Leading, instigating and par" not in recommended_titles
    assert "Non-regular Admission" not in recommended_titles
    assert "Messages in between sessions" not in recommended_titles
    assert "Submission Policy" not in recommended_titles
    _cleanup_all()


def test_failed_gate_candidates_move_to_overflow_or_needs_review():
    _cleanup_all()
    result = generate_candidates_from_preview(_gate_failure_preview(), filename="gate-buckets.pdf", max_candidates=10)
    moved = {
        item["title"]
        for item in result["overflow_candidates"] + result["needs_review_candidates"] + result["low_confidence_candidates"]
    }
    # Incomplete OCR titles are RAG-only (not article blueprints); messages are hard-negative RAG-only.
    assert "Leading, instigating and par" not in {
        item["title"] for item in result["recommended_candidates"]
    }
    assert "Messages in between sessions" not in {
        item["title"] for item in result["recommended_candidates"]
    }
    assert result["rag_only_count"] >= 1 or "Submission Policy" in moved
    _cleanup_all()


def test_handbook_policy_candidate_below_quality_not_recommended():
    saved = {
        "title": "Leading, instigating and par",
        "document_type": "handbook_policy",
        "quality_score": 6.75,
        "category_confidence": 0.625,
        "student_usefulness_score": 1.5,
        "needs_review": False,
        "review_reason": [],
    }
    assert _passes_recommendation_gate(saved) is False


def test_information_candidate_below_quality_not_recommended():
    saved = {
        "title": "General Topic",
        "document_type": "information",
        "quality_score": 6.9,
        "category_confidence": 0.8,
        "student_usefulness_score": 1.5,
        "needs_review": False,
        "review_reason": [],
    }
    assert _passes_recommendation_gate(saved) is False


def test_handbook_policy_candidate_can_be_recommended_when_clean():
    saved = {
        "title": "Admission Requirements",
        "document_type": "handbook_policy",
        "article_type": "requirement",
        "quality_score": 8.5,
        "category_confidence": 0.812,
        "student_usefulness_score": 1.5,
        "needs_review": False,
        "review_reason": [],
        "summary": "This article explains the requirements and related instructions for Admission Requirements.",
        "content": "Students must submit admission requirements and enrollment documents.",
    }
    assert _passes_recommendation_gate(saved) is True


def test_borderline_confidence_moves_to_needs_review_bucket():
    saved = {
        "title": "Admission Requirements",
        "document_type": "requirement",
        "article_type": "requirement",
        "quality_score": 8.0,
        "category_confidence": 0.55,
        "student_usefulness_score": 1.5,
        "needs_review": False,
        "review_reason": [],
        "summary": "This article explains the requirements and related instructions for Admission Requirements.",
        "content": "Students must submit admission requirements and enrollment documents.",
    }
    assert _passes_recommendation_gate(saved) is False


def test_handbook_policy_weak_candidate_moves_out_of_recommended():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": "Leading, instigating and par",
                "content": "Discipline content with enough words to remain saveable as a draft article candidate." * 4,
                "content_type": "document_chunk",
                "hierarchy_path": "Conduct",
                "word_count": 80,
                "status": "OK",
                "metadata": {"section_heading": "Leading, instigating and par", "document_type": "handbook_policy"},
            },
            _good_unit(1, "Admission Requirements"),
        ],
        "structured": {"formatted_text": "Handbook policy gate"},
    }
    result = generate_candidates_from_preview(preview, filename="handbook-policy-gate.pdf", max_candidates=10)
    recommended_titles = {item["title"] for item in result["recommended_candidates"]}
    assert "Leading, instigating and par" not in recommended_titles
    assert "Admission Requirements" in recommended_titles
    assert result["rag_only_count"] >= 1
    _cleanup_all()

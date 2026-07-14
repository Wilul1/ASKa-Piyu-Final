import pytest

from app.services.admin.article_candidate_generator import (
    generate_candidates_from_preview,
    group_candidates_for_review,
    resolve_candidate_group,
)


@pytest.fixture(autouse=True)
def _deterministic_taxonomy_classification(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_taxonomy.settings.groq_api_key",
        None,
    )


def _multi_office_preview() -> dict:
    return {
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": "TOR Request",
                "content": (
                    "Students may request a transcript of records. "
                    "Requirements include a request form and ID. "
                    "How to submit the procedure at the records counter. "
                )
                * 3,
                "content_type": "document_chunk",
                "hierarchy_path": "Records > TOR",
                "word_count": 80,
                "status": "OK",
                "metadata": {"document_type": "requirement"},
            },
            {
                "unit_index": 1,
                "title": "Password Reset",
                "content": (
                    "Students may request password reset assistance. "
                    "How to complete the procedure and which form is needed. "
                )
                * 3,
                "content_type": "document_chunk",
                "hierarchy_path": "Tech Support > Password Reset",
                "word_count": 80,
                "status": "OK",
                "metadata": {"document_type": "procedure"},
            },
            {
                "unit_index": 2,
                "title": "Excuse Slip",
                "content": (
                    "Students may secure an excuse slip through student affairs services. "
                    "Requirements and procedure for attendance documentation. "
                )
                * 3,
                "content_type": "document_chunk",
                "hierarchy_path": "Student Services > Excuse Slip",
                "word_count": 80,
                "status": "OK",
                "metadata": {"document_type": "information"},
            },
        ],
        "structured": {"formatted_text": "Grouped services"},
    }


def test_grouped_candidates_include_all_preview_candidates_not_only_recommended():
    result = generate_candidates_from_preview(
        _multi_office_preview(),
        filename="grouped.pdf",
        max_candidates=1,
    )
    assert result["recommended_count"] == 1
    assert len(result["all_candidates"]) == result["preview_count"]
    assert len(result["grouped_candidates"]) >= 2
    grouped_total = sum(group["total_count"] for group in result["grouped_candidates"])
    assert grouped_total == len(result["all_candidates"])


def test_candidates_group_by_office_only_with_high_confidence_alias():
    candidate = {
        "title": "TOR Request",
        "category": "Records and Documents",
        "office": "Registrar",
        "office_match_confidence": 0.9,
        "service_category": "Student Records",
        "source_section": "Registrar > TOR",
        "content": "Registrar office transcript request process.",
    }
    group_name, group_type = resolve_candidate_group(candidate)
    assert group_name == "Registrar"
    assert group_type == "office"


def test_candidates_do_not_use_office_label_without_alias_confidence():
    candidate = {
        "title": "TOR Request",
        "category": "Records and Documents",
        "office": "Registrar",  # metadata only — not from office_aliases
        "source_section": "Registrar > TOR",
        "content": "Students may request a transcript of records.",
    }
    group_name, group_type = resolve_candidate_group(candidate)
    assert group_type != "office"
    assert group_name  # falls back to service/category/section


def test_candidates_fall_back_to_category_when_office_missing():
    candidate = {
        "title": "Excuse Slip",
        "category": "Student Services",
        "source_section": "Student Services > Excuse Slip",
        "content": "Students may secure an excuse slip from student affairs.",
    }
    group_name, group_type = resolve_candidate_group(candidate)
    assert group_name
    assert group_type in {"service_category", "category", "source_section"}


def test_grouped_candidates_include_counts():
    groups = group_candidates_for_review(
        [
            {
                "id": "preview-1",
                "title": "TOR Request",
                "category": "Records and Documents",
                "office": "Registrar",
                "quality_score": 8.0,
                "category_confidence": 0.8,
                "student_usefulness_score": 1.0,
                "needs_review": False,
                "review_reason": [],
                "document_type": "requirement",
            },
            {
                "id": "preview-2",
                "title": "Overview",
                "category": "General Information",
                "quality_score": 1.0,
                "category_confidence": 0.2,
                "student_usefulness_score": -1.0,
                "needs_review": True,
                "review_reason": ["content_too_short"],
                "document_type": "information",
            },
        ]
    )
    assert groups
    assert groups[0]["total_count"] >= 1
    assert "recommended_count" in groups[0]
    assert "needs_review_count" in groups[0]

import pytest

from app.services.admin.article_planner import (
    build_article_blueprints,
    build_coverage_report,
    classify_unit_for_articles,
    ensure_unit_indexes,
    plan_articles_from_units,
    stable_preview_id,
)
from app.services.admin.article_candidate_generator import (
    generate_candidates_from_preview,
    resolve_candidate_group,
)
from app.services.office_matcher import OfficeMatch, match_office_from_text


@pytest.fixture(autouse=True)
def _deterministic_taxonomy_classification(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_taxonomy.settings.groq_api_key",
        None,
    )


def _units_many_topics() -> list[dict]:
    units = []
    # Admission cluster
    for i in range(4):
        units.append(
            {
                "title": f"Admission Requirement {i+1}",
                "content": "Students must submit requirements for admission and enrollment. "
                * 4,
                "hierarchy_path": "Admissions > Admission Requirements",
                "status": "OK",
                "metadata": {"document_type": "requirement"},
            }
        )
    # Curricular offerings cluster (should consolidate)
    for college in ("College A", "College B", "College C", "College D"):
        units.append(
            {
                "title": f"Curricular Offerings - {college}",
                "content": f"Programs and curricular offerings for {college}. "
                "Students may review majors under this college. " * 3,
                "hierarchy_path": f"Programs > Curricular Offerings > {college}",
                "status": "OK",
                "metadata": {"document_type": "information"},
            }
        )
    # Procedure action fragments (not article eligible alone)
    for step in ("First Action", "Second Action", "Third Action"):
        units.append(
            {
                "title": step,
                "content": "Major disciplinary actions proceed through sequential steps. " * 3,
                "hierarchy_path": "Student Conduct > Major Disciplinary Actions",
                "status": "OK",
                "metadata": {"document_type": "procedure"},
            }
        )
    # Hard negative
    units.append(
        {
            "title": "Foreword",
            "content": "A message from leadership. " * 5,
            "hierarchy_path": "Front Matter > Foreword",
            "status": "OK",
            "metadata": {},
        }
    )
    # Appendix-only
    units.append(
        {
            "title": "Appendix J",
            "content": "This appendix contains supplemental material. " * 4,
            "hierarchy_path": "Appendices > Appendix J",
            "status": "OK",
            "metadata": {},
        }
    )
    return units


def test_ensure_unit_indexes_via_enumerate():
    units = ensure_unit_indexes([{"title": "A"}, {"title": "B"}])
    assert [unit["unit_index"] for unit in units] == [0, 1]


def test_foreword_and_appendix_are_rag_only_not_article_eligible():
    tagged = [classify_unit_for_articles(unit) for unit in ensure_unit_indexes(_units_many_topics())]
    by_title = {unit["title"]: unit for unit in tagged}
    assert by_title["Foreword"]["rag_indexable"] is True
    assert by_title["Foreword"]["article_eligible"] is False
    assert by_title["Appendix J"]["article_eligible"] is False
    # Action fragments stay RAG-only individually but merge into parent procedure blueprints.
    assert by_title["First Action"]["article_eligible"] is False


def test_blueprints_consolidate_instead_of_one_per_chunk():
    plan = plan_articles_from_units(_units_many_topics(), db=None)
    assert plan["article_eligible_count"] < len(plan["tagged_units"])
    assert len(plan["blueprints"]) < plan["article_eligible_count"] or len(plan["blueprints"]) <= 12
    # curricular offerings should consolidate under parent
    titles = {bp["canonical_topic"] for bp in plan["blueprints"]}
    assert any("Curricular Offerings" in title for title in titles) or any(
        bp.get("consolidated_parent") for bp in plan["blueprints"]
    )


def test_generate_from_blueprints_not_every_chunk(monkeypatch):
    preview = {"knowledge_units": _units_many_topics() * 8}  # inflate toward large handbook
    result = generate_candidates_from_preview(preview, filename="handbook.pdf", max_candidates=80)
    assert result["total_detected"] == len(preview["knowledge_units"])
    # Fewer candidates than knowledge units
    assert result["preview_count"] < result["total_detected"]
    assert result["preview_count"] <= 90
    assert "coverage" in result
    assert isinstance(result["coverage"], list)
    assert result["saved_count"] == 0


def test_coverage_includes_rag_only_and_generated_statuses():
    plan = plan_articles_from_units(_units_many_topics(), db=None)
    coverage = build_coverage_report(plan["tagged_units"], plan["blueprints"], [])
    statuses = {item["status"] for item in coverage}
    assert "rag_only" in statuses or "needs_cleanup" in statuses


def test_resolve_group_office_only_with_high_confidence_alias(monkeypatch):
    monkeypatch.setattr(
        "app.services.admin.article_candidate_generator.match_office_from_text",
        lambda text, db: OfficeMatch(
            office_id="1",
            office_name="Registrar",
            service_category="Student Records",
            matched_alias="Registrar",
            weight=1.2,
            confidence=0.9,
        ),
    )
    name, group_type = resolve_candidate_group(
        {"title": "Transcript request", "content": "Students may request TOR."},
        db=object(),
    )
    assert name == "Registrar"
    assert group_type == "office"


def test_resolve_group_not_office_without_alias_match(monkeypatch):
    monkeypatch.setattr(
        "app.services.admin.article_candidate_generator.match_office_from_text",
        lambda text, db: None,
    )
    name, group_type = resolve_candidate_group(
        {
            "title": "Admission Requirements",
            "category": "Admissions",
            "source_section": "Admissions > Requirements",
        },
        db=None,
    )
    assert group_type != "office"


def test_blueprint_ids_are_stable_sha1():
    first = build_article_blueprints(
        [classify_unit_for_articles(unit) for unit in ensure_unit_indexes(_units_many_topics())]
    )
    second = build_article_blueprints(
        [classify_unit_for_articles(unit) for unit in ensure_unit_indexes(_units_many_topics())]
    )
    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert all(len(item["id"]) == 40 for item in first)


def test_match_office_from_text_without_db_returns_none():
    assert match_office_from_text("Registrar transcript", None) is None


def test_match_office_from_text_uses_alias_weights(monkeypatch):
    monkeypatch.setattr(
        "app.services.office_matcher.load_office_aliases",
        lambda db: [
            {
                "alias": "Office of the Registrar",
                "weight": 1.3,
                "office_id": "reg-1",
                "office_name": "Registrar",
                "service_category": "Student Records",
            },
            {
                "alias": "ICT",
                "weight": 1.0,
                "office_id": "ict-1",
                "office_name": "ICT Office",
                "service_category": "Technology Services",
            },
        ],
    )
    match = match_office_from_text(
        "Students request TOR at the Office of the Registrar.",
        db=object(),
    )
    assert match is not None
    assert match.office_name == "Registrar"
    assert match.confidence >= 0.72


def test_match_office_from_text_rejects_ambiguous(monkeypatch):
    monkeypatch.setattr(
        "app.services.office_matcher.load_office_aliases",
        lambda db: [
            {
                "alias": "Student Affairs",
                "weight": 1.1,
                "office_id": "osas-1",
                "office_name": "Office of Student Affairs",
                "service_category": "Student Services",
            },
            {
                "alias": "Student Services",
                "weight": 1.1,
                "office_id": "svc-1",
                "office_name": "Student Services Office",
                "service_category": "Student Services",
            },
        ],
    )
    match = match_office_from_text(
        "Contact Student Affairs and Student Services for support.",
        db=object(),
    )
    assert match is None


def test_planner_does_not_hardcode_office_names():
    import inspect
    from app.services.admin import article_planner
    from app.services import office_matcher

    for module in (article_planner, office_matcher):
        source = inspect.getsource(module)
        for banned in ("ICT Office", "OSAS", "Guidance Office"):
            assert banned not in source


def test_list_of_programs_is_not_hard_negative():
    tagged = classify_unit_for_articles(
        {
            "title": "List of Programs",
            "content": "List of programs and curricular offerings for undergraduate students. "
            "Students may review majors and requirements for each program.",
            "hierarchy_path": "Programs > List of Programs",
            "status": "OK",
            "metadata": {"document_type": "information"},
        }
    )
    assert tagged["article_eligible"] is True
    assert tagged["planner_bucket"] == "article_eligible"


def test_duplicate_admission_requirements_merge_into_one_blueprint():
    units = [
        {
            "title": f"Admission Requirement {i + 1}",
            "content": "Students must submit requirements for admission and enrollment. " * 4,
            "hierarchy_path": "Admissions > Admission Requirements",
            "status": "OK",
            "metadata": {"document_type": "requirement"},
        }
        for i in range(4)
    ]
    plan = plan_articles_from_units(units, db=None)
    admission_blueprints = [
        bp
        for bp in plan["blueprints"]
        if "admission requirement" in bp["canonical_topic"].lower()
    ]
    assert len(admission_blueprints) == 1
    assert admission_blueprints[0]["unit_count"] == 4


def test_curricular_offerings_merge_into_parent_article():
    units = [
        {
            "title": f"Curricular Offerings - College {label}",
            "content": "Programs and curricular offerings. Students may review majors. " * 3,
            "hierarchy_path": f"Programs > Curricular Offerings > College {label}",
            "status": "OK",
            "metadata": {"document_type": "information"},
        }
        for label in ("A", "B", "C", "D")
    ]
    plan = plan_articles_from_units(units, db=None)
    assert any(
        "Curricular Offerings" in bp["canonical_topic"]
        and int(bp.get("unit_count") or 0) >= 4
        for bp in plan["blueprints"]
    )


def test_procedure_action_fragments_merge_into_parent_procedure():
    units = [
        {
            "title": step,
            "content": "Major disciplinary actions proceed through sequential steps and procedures. " * 3,
            "hierarchy_path": "Student Conduct > Major Disciplinary Actions",
            "status": "OK",
            "metadata": {"document_type": "procedure"},
        }
        for step in ("First Action", "Second Action", "Third Action")
    ]
    plan = plan_articles_from_units(units, db=None)
    assert len(plan["blueprints"]) == 1
    assert plan["blueprints"][0]["canonical_topic"] == "Major Disciplinary Actions"
    assert plan["blueprints"][0]["unit_count"] == 3
    assert plan["blueprints"][0]["article_type"] == "procedure"


def test_ocr_fragments_go_to_rag_only_or_low_quality():
    preview = {
        "knowledge_units": [
            {
                "title": "Every student accumulat",
                "content": "Incomplete OCR fragment with little useful meaning.",
                "hierarchy_path": "Policies > Attendance",
                "status": "OK",
                "metadata": {},
            },
            {
                "title": "Overview",
                "content": "Short note.",
                "hierarchy_path": "General > Overview",
                "status": "OK",
                "metadata": {},
            },
        ],
        "structured": {"formatted_text": "OCR fragments"},
    }
    result = generate_candidates_from_preview(preview, filename="ocr.pdf")
    assert result["preview_count"] == 0
    assert result["rag_only_count"] >= 1
    assert result["coverage"]


def test_coverage_report_includes_needs_review_status():
    candidates = [
        {
            "parent_topic": "Admissions",
            "canonical_topic": "Admission Requirements",
            "title": "Admission Requirements",
            "needs_review": True,
            "planner_bucket": "needs_review",
        }
    ]
    blueprints = [
        {
            "parent_topic": "Admissions",
            "canonical_topic": "Admission Requirements",
            "unit_count": 2,
            "consolidated_parent": False,
            "id": "abc",
        }
    ]
    coverage = build_coverage_report([], blueprints, candidates)
    assert any(item["status"] == "needs_review" for item in coverage)


def test_stable_preview_ids_use_sha1_from_blueprint():
    blueprint_id = "deadbeef" * 5
    first = stable_preview_id(blueprint_id)
    second = stable_preview_id(blueprint_id)
    assert first == second
    assert first.startswith("preview-")
    assert len(first) == len("preview-") + 40


def test_sec_generic_title_not_used_as_consolidated_parent():
    units = [
        {
            "title": f"Clause {index + 1}",
            "content": "Students must follow grading rules and academic requirements. " * 4,
            "hierarchy_path": f"Grading System > Sec. 1 > Clause {index + 1}",
            "status": "OK",
            "metadata": {"document_type": "policy"},
        }
        for index in range(4)
    ]
    plan = plan_articles_from_units(units, db=None)
    titles = {bp["canonical_topic"] for bp in plan["blueprints"]}
    assert "Sec. 1" not in titles
    assert any("Grading System" in title for title in titles)


def test_generic_title_resolves_to_meaningful_parent_topic():
    from app.services.admin.article_planner import resolve_student_facing_title

    resolved, replaced = resolve_student_facing_title(
        "Sec. 1",
        "General Behavior > Sec. 1",
    )
    assert replaced is True
    assert resolved == "General Behavior"


def test_rag_only_coverage_includes_source_section():
    tagged = [
        {
            "article_eligible": False,
            "parent_topic": "Front Matter",
            "canonical_topic": "Foreword",
            "source_section": "Front Matter > Foreword",
            "hierarchy_path": "Front Matter > Foreword",
        }
    ]
    coverage = build_coverage_report(tagged, [], [])
    assert coverage
    assert coverage[0]["status"] == "rag_only"
    assert coverage[0]["source_section"] == "Front Matter > Foreword"
    assert coverage[0]["reason"] == "RAG-only"


def test_numeric_only_titles_are_generic():
    from app.services.admin.article_planner import is_generic_article_title, is_numeric_only_title

    assert is_numeric_only_title("1.1")
    assert is_numeric_only_title("4.2")
    assert is_numeric_only_title("7.6.3.1")
    assert is_generic_article_title("1.1")


def test_numeric_only_title_resolves_to_parent_or_low_quality():
    from app.services.admin.article_planner import resolve_student_facing_title

    resolved, replaced = resolve_student_facing_title("1.1", "Academic Policies > 1.1")
    assert replaced is True
    assert resolved == "Academic Policies"

    preview = {
        "knowledge_units": [
            {
                "title": "4.2",
                "content": "Policy details without a meaningful parent heading. " * 12,
                "hierarchy_path": "4.2",
                "status": "OK",
                "metadata": {"document_type": "policy"},
            }
        ]
    }
    result = generate_candidates_from_preview(preview, filename="handbook.pdf")
    for candidate in result["all_candidates"]:
        assert candidate.get("planner_bucket") == "low_quality"
        assert candidate.get("planner_bucket") not in {
            "recommended",
            "consolidated_parent",
            "needs_review",
        }


def test_broad_incoherent_parent_not_consolidated():
    specs = [
        ("Funding Support", "Graduate fellowship and funding guidelines.", "requirement"),
        ("Counseling Services", "Counseling and wellness support.", "information"),
        ("Thesis Guidelines", "Thesis submission procedure and formatting steps.", "procedure"),
        ("Scholarship Programs", "Scholarship application form and eligibility.", "form"),
        ("Graduation Clearance", "Graduation requirements and clearance process.", "requirement"),
    ]
    units = [
        {
            "title": title,
            "content": content * 6,
            "hierarchy_path": f"Graduate Studies > {title}",
            "status": "OK",
            "metadata": {"document_type": doc_type},
        }
        for title, content, doc_type in specs
    ]
    plan = plan_articles_from_units(units, db=None)
    consolidated = [
        bp
        for bp in plan["blueprints"]
        if bp.get("consolidated_parent") and bp.get("canonical_topic") == "Graduate Studies"
    ]
    assert consolidated == []


def test_coherent_graduation_requirements_stays_consolidated():
    units = [
        {
            "title": f"Graduation Requirement Part {index + 1}",
            "content": "Students must meet graduation requirements before clearance. " * 6,
            "hierarchy_path": f"Graduation Requirements > Part {index + 1}",
            "status": "OK",
            "metadata": {"document_type": "requirement"},
        }
        for index in range(4)
    ]
    plan = plan_articles_from_units(units, db=None)
    consolidated = [
        bp
        for bp in plan["blueprints"]
        if bp.get("consolidated_parent")
        and "graduation requirement" in bp.get("canonical_topic", "").lower()
    ]
    assert consolidated
    assert consolidated[0]["unit_count"] >= 4


def test_merged_preview_exposes_source_sections_list():
    units = [
        {
            "title": f"Admission Requirement {index + 1}",
            "content": "Students must submit requirements for admission and enrollment. " * 5,
            "hierarchy_path": f"Admissions > Admission Requirements > Item {index + 1}",
            "status": "OK",
            "metadata": {"document_type": "requirement"},
        }
        for index in range(4)
    ]
    result = generate_candidates_from_preview({"knowledge_units": units}, filename="handbook.pdf")
    merged = [
        candidate
        for candidate in result["all_candidates"]
        if int(candidate.get("merged_unit_count") or 0) >= 3
    ]
    assert merged
    sample = merged[0]
    sections = sample.get("source_sections") or []
    assert len(sections) >= 3
    assert ";" not in (sample.get("source_section") or "")


def test_modified_grading_policy_is_policy_not_requirement():
    from app.services.admin.article_planner import classify_unit_for_articles

    unit = {
        "title": "Modified Grading Policy",
        "content": (
            "Students who fail to meet retention standards shall follow modified grading rules "
            "and academic conditions described in this policy."
        )
        * 8,
        "hierarchy_path": "Academic Policies > Modified Grading Policy",
        "status": "OK",
        "metadata": {"document_type": "handbook_policy"},
    }
    tagged = classify_unit_for_articles(unit)
    assert tagged["article_type"] == "policy"

    result = generate_candidates_from_preview({"knowledge_units": [unit]}, filename="handbook.pdf")
    candidates = result.get("all_candidates") or []
    assert candidates
    sample = candidates[0]
    assert sample.get("article_type") == "policy"
    summary = (sample.get("summary") or "").lower()
    for foreign in ("counseling", "referral", "face-to-face", "face to face"):
        assert foreign not in summary


def test_basic_requirements_is_requirement_not_form():
    from app.services.admin.article_planner import classify_unit_for_articles

    unit = {
        "title": "Basic Requirements",
        "content": "Students must submit the following requirements for enrollment and registration." * 8,
        "hierarchy_path": "Admissions > Basic Requirements",
        "status": "OK",
        "metadata": {"document_type": "requirement"},
    }
    tagged = classify_unit_for_articles(unit)
    assert tagged["article_type"] == "requirement"


def test_duplicate_curricular_offerings_are_disambiguated():
    units = []
    for root in ("Undergraduate Programs", "Graduate Programs"):
        for label in ("College A", "College B", "College C"):
            units.append(
                {
                    "title": "Curricular Offerings",
                    "content": "Programs and curricular offerings. Students may review majors. " * 4,
                    "hierarchy_path": f"{root} > Curricular Offerings > {label}",
                    "status": "OK",
                    "metadata": {"document_type": "information"},
                }
            )
    plan = plan_articles_from_units(units, db=None)
    offering_titles = [
        bp["canonical_topic"]
        for bp in plan["blueprints"]
        if "curricular offering" in bp["canonical_topic"].lower()
    ]
    assert len(offering_titles) >= 2
    assert len(offering_titles) == len(set(offering_titles))


def test_recommended_not_padded_to_max_candidates():
    units = [
        {
            "title": f"Admission Requirement {index + 1}",
            "content": "Students must submit requirements for admission and enrollment procedures." * 6,
            "hierarchy_path": f"Admissions > Admission Requirements > Item {index + 1}",
            "status": "OK",
            "metadata": {"document_type": "requirement"},
        }
        for index in range(30)
    ]
    result = generate_candidates_from_preview(
        {"knowledge_units": units},
        filename="handbook.pdf",
        max_candidates=80,
    )
    assert result["recommended_count"] <= 80
    recommended_buckets = [
        item.get("planner_bucket")
        for item in result["all_candidates"]
        if item.get("planner_bucket") == "recommended"
    ]
    assert len(recommended_buckets) == result["recommended_count"]
    assert result["coverage_counts"]["generated"] == result["recommended_count"]

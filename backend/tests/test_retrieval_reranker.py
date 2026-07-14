from typing import Any

from app.services.chroma_store import RetrievedChunk
from app.services.retrieval_reranker import expand_query, prepare_retrieval_query, rerank_chunks


def chunk(title: str, text: str, score: float = 0.7, metadata: dict[str, Any] | None = None) -> RetrievedChunk:
    chunk_metadata = {"section": title}
    if metadata:
        chunk_metadata.update(metadata)
    return RetrievedChunk(
        document_id=title.lower().replace(" ", "-"),
        title="Student Handbook",
        source_filename="handbook.pdf",
        chunk_index=0,
        text=text,
        relevance_score=score,
        original_score=score,
        metadata=chunk_metadata,
    )


def titles_for(query: str, chunks: list[RetrievedChunk]) -> list[str]:
    return [result.metadata["section"] for result in rerank_chunks(query, chunks)]


def test_generic_dismissal_ranks_academic_policy_above_honorable_dismissal():
    results = titles_for(
        "What is the dismissal policy?",
        [
            chunk("Honorable Dismissal", "Students may request honorable dismissal for voluntary withdrawal.", 0.9),
            chunk("Retention Policies - Dismissal", "Academic dismissal applies after failed units and scholastic delinquency.", 0.74),
        ],
    )

    assert results[0] == "Retention Policies - Dismissal"


def test_honorable_dismissal_query_can_rank_honorable_dismissal_first():
    results = titles_for(
        "How do I request honorable dismissal or transfer credentials?",
        [
            chunk("Retention Policies - Dismissal", "Academic dismissal applies after failed units.", 0.76),
            chunk("Honorable Dismissal", "Honorable dismissal and transfer credential requests are filed with the registrar.", 0.74),
        ],
    )

    assert results[0] == "Honorable Dismissal"


def test_failing_many_subjects_retrieves_academic_consequences_in_top_three():
    ranked = titles_for(
        "What are the consequences of failing many subjects?",
        [
            chunk("Uniform Policy", "Students shall wear the prescribed uniform.", 0.82),
            chunk("Scholastic Delinquency", "Students with failed academic units may receive warning or probation.", 0.68),
            chunk("Dismissal", "Dismissal may be imposed for serious academic deficiency.", 0.66),
            chunk("Dropped", "A student may be dropped after continued scholastic delinquency.", 0.64),
        ],
    )

    assert any(title in ranked[:3] for title in {"Scholastic Delinquency", "Dismissal", "Dropped"})


def test_failing_75_percent_units_ranks_dismissal_top_one():
    ranked = titles_for(
        "What happens if I fail 75% of my units?",
        [
            chunk("Probation", "Students may be placed under academic probation after failed academic units.", 0.8),
            chunk("Dismissal", "A student who fails 75% of academic units may be dismissed.", 0.72),
        ],
    )

    assert ranked[0] == "Dismissal"


def test_undergraduate_ccs_programs_rank_above_graduate_ccs_programs():
    ranked = titles_for(
        "What programs are offered by the College of Computer Studies in undergraduate studies?",
        [
            chunk("College of Computer Studies - Graduate Studies", "Graduate Studies: MS Information Technology, PhD Computer Science.", 0.82),
            chunk(
                "College of Computer Studies - Undergraduate Programs",
                "Undergraduate Programs: BS Computer Science, BS Information System, BS Information Technology.",
                0.72,
            ),
        ],
    )

    assert ranked[0] == "College of Computer Studies - Undergraduate Programs"


def test_bs_information_technology_campus_query_ranks_all_campuses_top_one():
    ranked = titles_for(
        "Which campuses offer BS Information Technology?",
        [
            chunk("Graduate Programs", "MS Information Technology is offered in Main Campus.", 0.8),
            chunk(
                "College of Computer Studies - Undergraduate Programs",
                "BS Information Technology. Campuses: All Campuses.",
                0.7,
            ),
        ],
    )

    assert ranked[0] == "College of Computer Studies - Undergraduate Programs"


def test_absent_due_to_illness_ranks_attendance_policy_top_one():
    ranked = titles_for(
        "I was absent due to illness. What should I do?",
        [
            chunk("Clinic Services", "The clinic provides first aid services.", 0.82),
            chunk("Attendance Policy", "For absence due to illness, submit an excuse slip and medical certificate to OSAS.", 0.7),
        ],
    )

    assert ranked[0] == "Attendance Policy"


def test_attendance_query_penalizes_offenses_ojt_and_appendices():
    ranked = rerank_chunks(
        "What should I do about attendance after being absent due to illness?",
        [
            chunk(
                "Non-wearing of ID",
                "Minor offense: non-wearing of identification card is subject to sanction.",
                0.91,
                metadata={"chapter": "Student Discipline", "article": "Minor Offenses", "content_type": "disciplinary_rule"},
            ),
            chunk(
                "OJT Procedures",
                "OJT procedure steps and process flow for trainees.",
                0.88,
                metadata={"chapter": "Student Internship", "section": "OJT Procedures", "content_type": "procedure"},
            ),
            chunk(
                "Appendix A",
                "Appendix form template for office routing.",
                0.86,
                metadata={"appendix": "Appendix A", "content_type": "form_template"},
            ),
            chunk(
                "Attendance Policy",
                "For absence due to illness, submit an excuse slip and medical certificate to OSAS.",
                0.72,
                metadata={"chapter": "Undergraduate Academic Policies", "article": "Attendance"},
            ),
        ],
    )

    assert ranked[0].metadata["section"] == "Attendance Policy"
    assert any("boost_path_domain_match:attendance" in reason for reason in ranked[0].rerank_reasons)
    noisy_reasons = {result.metadata["section"]: result.rerank_reasons for result in ranked[1:]}
    assert "penalty_disciplinary_offense_out_of_domain" in noisy_reasons["Non-wearing of ID"]
    assert "penalty_unrelated_procedure" in noisy_reasons["OJT Procedures"]
    assert "penalty_unrelated_appendix" in noisy_reasons["Appendix A"]


def test_scholastic_delinquency_penalizes_awards_and_major_offenses():
    ranked = titles_for(
        "What is scholastic delinquency under retention policies?",
        [
            chunk("Academic Awards", "Awards and honors are granted to students with excellent grades.", 0.9),
            chunk("Major Offenses", "Major offenses and disciplinary sanctions are handled by the discipline board.", 0.87),
            chunk(
                "Scholastic Delinquency",
                "Retention Policies define scholastic delinquency, warning, probation, dropped status, and dismissal.",
                0.71,
                metadata={"chapter": "Undergraduate Academic Policies", "article": "Retention Policies"},
            ),
        ],
    )

    assert ranked[0] == "Scholastic Delinquency"


def test_ccs_curricular_query_without_graduate_terms_suppresses_graduate_offerings():
    ranked = titles_for(
        "What curricular offerings are available in the College of Computer Studies?",
        [
            chunk(
                "College of Computer Studies - Graduate Studies",
                "Graduate Studies: MS Information Technology, PhD Computer Science.",
                0.9,
                metadata={"chapter": "Curricular Offerings", "section": "College of Computer Studies > Graduate Studies"},
            ),
            chunk(
                "College of Computer Studies - Undergraduate Programs",
                "Undergraduate Programs: BS Computer Science, BS Information System, BS Information Technology.",
                0.7,
                metadata={"chapter": "Curricular Offerings", "section": "College of Computer Studies > Undergraduate Programs"},
            ),
        ],
    )

    assert ranked[0] == "College of Computer Studies > Undergraduate Programs"


def test_engineering_program_query_boosts_matching_curricular_path():
    ranked = titles_for(
        "What engineering programs are offered?",
        [
            chunk("Academic Awards", "Awards and honors are granted to students with excellent grades.", 0.86),
            chunk(
                "College of Computer Studies - Undergraduate Programs",
                "Undergraduate Programs: BS Computer Science and BS Information Technology.",
                0.82,
                metadata={"chapter": "Curricular Offerings", "section": "College of Computer Studies > Undergraduate Programs"},
            ),
            chunk(
                "College of Engineering - Undergraduate Programs",
                "Undergraduate Programs: BS Civil Engineering, BS Electrical Engineering, and BS Mechanical Engineering.",
                0.74,
                metadata={"chapter": "Curricular Offerings", "section": "College of Engineering > Undergraduate Programs"},
            ),
        ],
    )

    assert ranked[0] == "College of Engineering > Undergraduate Programs"


def test_curricular_query_penalizes_same_domain_student_services_noise():
    ranked = rerank_chunks(
        "What curricular offerings are available in the College of Computer Studies?",
        [
            chunk("Student Services", "Student Services include counseling, registrar assistance, admission support, and Tele-Web access.", 0.96),
            chunk("Counseling Services", "Counseling and guidance services are available to students.", 0.94),
            chunk("Admission Office", "Admission requirements are processed before enrollment.", 0.93),
            chunk("Registrar", "The registrar maintains academic records and Tele-Web registration.", 0.92),
            chunk(
                "College of Computer Studies - Undergraduate Programs",
                "Undergraduate Programs: BS Computer Science, BS Information System, BS Information Technology.",
                0.72,
                metadata={"chapter": "Curricular Offerings", "section": "College of Computer Studies > Undergraduate Programs"},
            ),
        ],
    )

    scores = {result.metadata["section"]: result.reranked_score for result in ranked}
    target_score = scores["College of Computer Studies > Undergraduate Programs"]

    assert ranked[0].metadata["section"] == "College of Computer Studies > Undergraduate Programs"
    assert scores["Student Services"] < target_score
    assert scores["Counseling Services"] < target_score
    assert scores["Admission Office"] < target_score
    assert scores["Registrar"] < target_score


def test_attendance_query_penalizes_registrar_and_graduation_noise():
    ranked = rerank_chunks(
        "I was absent due to illness. How do I file an excuse slip?",
        [
            chunk("Registrar Visitation", "Registrar visitation schedules are handled during enrollment.", 0.96),
            chunk("Petition Subject", "A petition subject is requested for special enrollment cases.", 0.94),
            chunk("Academic Load", "Academic load limits apply to regular and irregular students.", 0.93),
            chunk("Graduation", "Graduation clearance is required for candidates for graduation.", 0.92),
            chunk(
                "Attendance Policy",
                "For absence due to illness, submit an excuse slip and medical certificate to OSAS.",
                0.7,
                metadata={"chapter": "Undergraduate Academic Policies", "article": "Attendance"},
            ),
        ],
    )

    scores = {result.metadata["section"]: result.reranked_score for result in ranked}
    target_score = scores["Attendance Policy"]

    assert ranked[0].metadata["section"] == "Attendance Policy"
    assert scores["Registrar Visitation"] < target_score
    assert scores["Petition Subject"] < target_score
    assert scores["Academic Load"] < target_score
    assert scores["Graduation"] < target_score


def test_retention_query_penalizes_grade_removal_and_grading_noise():
    ranked = rerank_chunks(
        "What is scholastic delinquency under retention policies?",
        [
            chunk("Academic Awards", "Awards and honors are granted to students with excellent grades.", 0.96),
            chunk("INC Policy", "INC or incomplete grades must be completed within the prescribed period.", 0.95),
            chunk("4.00 Removal Policy", "The 4.00 removal policy explains grade removal requirements.", 0.94),
            chunk("Grading System", "The grading system defines numerical grades and marks.", 0.93),
            chunk(
                "Scholastic Delinquency",
                "Retention Policies define scholastic delinquency, warning, probation, dropped status, and dismissal.",
                0.71,
                metadata={"chapter": "Undergraduate Academic Policies", "article": "Retention Policies"},
            ),
        ],
    )

    scores = {result.metadata["section"]: result.reranked_score for result in ranked}
    target_score = scores["Scholastic Delinquency"]

    assert ranked[0].metadata["section"] == "Scholastic Delinquency"
    assert scores["Academic Awards"] < target_score
    assert scores["INC Policy"] < target_score
    assert scores["4.00 Removal Policy"] < target_score
    assert scores["Grading System"] < target_score


def test_query_expansion_adds_expected_academic_terms():
    expanded = expand_query("Can I continue my course if I am failing many subjects?")

    assert "scholastic delinquency" in expanded
    assert "failed academic units" in expanded


def test_when_was_lspu_built_expands_to_historical_development():
    prepared = prepare_retrieval_query("When was LSPU built?")

    assert prepared.normalized_query == prepared.normalized_query.lower()
    assert "lspu historical development" in prepared.expanded_query
    assert "established" in prepared.expanded_query
    assert "1952" in prepared.expanded_query
    assert "lspu_historical_development_built" in prepared.matched_expansion_rules


def test_when_is_lspu_built_ranks_historical_development():
    ranked = titles_for(
        expand_query("when is lspu built?"),
        [
            chunk("Campus Buildings", "New campus buildings were constructed for students.", 0.9),
            chunk("LSPU Historical Development", "LSPU was initially established in 1952 as a provincial high school.", 0.72),
        ],
    )

    assert ranked[0] == "LSPU Historical Development"


def test_who_is_president_of_lspu_ranks_administrative_officials():
    prepared = prepare_retrieval_query("Who is the President of LSPU?")

    assert "administrative_officials_president" in prepared.matched_expansion_rules
    assert "administrative officials" in prepared.expanded_query

    ranked = titles_for(
        prepared.expanded_query,
        [
            chunk("Student Council", "The student council president leads student government activities.", 0.9),
            chunk("Administrative Officials", "DR. MARIO R. BRIONES University President", 0.72),
        ],
    )

    assert ranked[0] == "Administrative Officials"


def test_who_is_university_president_ranks_administrative_officials():
    prepared = prepare_retrieval_query("Who is the University President?")

    assert "administrative_officials_president" in prepared.matched_expansion_rules
    assert "administrative officials" in prepared.expanded_query

    ranked = titles_for(
        prepared.expanded_query,
        [
            chunk("Foreword", "A message from the office of the university.", 0.86),
            chunk("Administrative Officials", "DR. MARIO R. BRIONES University President", 0.72),
        ],
    )

    assert ranked[0] == "Administrative Officials"


def test_external_president_queries_do_not_trigger_administrative_officials_expansion():
    queries = [
        "Who is the president of the Philippines?",
        "Who is the President of the United States?",
        "President Marcos",
        "President of Google",
    ]

    for query in queries:
        prepared = prepare_retrieval_query(query)
        assert "administrative_officials_president" not in prepared.matched_expansion_rules
        assert "administrative officials" not in prepared.normalized_query
        assert "administrative officials" not in prepared.expanded_query
        assert query in prepared.expanded_query


def test_external_president_query_does_not_boost_administrative_officials():
    ranked = rerank_chunks(
        expand_query("Who is the president of the Philippines?"),
        [
            chunk("Administrative Officials", "DR. MARIO R. BRIONES University President", 0.72),
            chunk("Philippine Government", "This external government reference is not part of the LSPU handbook.", 0.71),
        ],
    )

    officials = next(result for result in ranked if result.metadata["section"] == "Administrative Officials")
    assert "boost_path_domain_match:officials" not in officials.rerank_reasons


def test_existing_natural_queries_still_rank_expected_chunks():
    cases = [
        (
            "What is scholastic delinquency?",
            "Scholastic Delinquency",
            [
                chunk("Academic Awards", "Awards and honors are granted to students with excellent grades.", 0.9),
                chunk("Scholastic Delinquency", "Warning, probation, and dismissal may apply for failed academic units.", 0.72),
            ],
        ),
        (
            "Where can I get an excuse slip?",
            "Attendance Policy",
            [
                chunk("Registrar", "The registrar maintains academic records.", 0.88),
                chunk("Attendance Policy", "Students may secure an excuse slip from OSAS or the Guidance Office.", 0.72),
            ],
        ),
        (
            "What programs does CCS offer?",
            "College of Computer Studies > Undergraduate Programs",
            [
                chunk("Student Services", "Student services include counseling and registrar assistance.", 0.9),
                chunk(
                    "College of Computer Studies - Undergraduate Programs",
                    "BS Computer Science, BS Information System, and BS Information Technology.",
                    0.72,
                    metadata={"chapter": "Curricular Offerings", "section": "College of Computer Studies > Undergraduate Programs"},
                ),
            ],
        ),
        (
            "What engineering programs are offered?",
            "College of Engineering > Undergraduate Programs",
            [
                chunk("Academic Awards", "Awards and honors are granted to students.", 0.9),
                chunk(
                    "College of Engineering - Undergraduate Programs",
                    "BS Civil Engineering, BS Electrical Engineering, and BS Mechanical Engineering.",
                    0.72,
                    metadata={"chapter": "Curricular Offerings", "section": "College of Engineering > Undergraduate Programs"},
                ),
            ],
        ),
    ]

    for query, expected_title, chunks in cases:
        assert titles_for(expand_query(query), chunks)[0] == expected_title


def test_validate_id_query_ranks_charter_id_validation_above_handbook_subject_validation():
    ranked = rerank_chunks(
        expand_query("How do I validate my ID?"),
        [
            RetrievedChunk(
                document_id="legacy-handbook",
                title="Student Handbook",
                source_filename="Student_Handbook.pdf",
                chunk_index=0,
                text="Validation of subjects is done every semester after enrollment assessment.",
                relevance_score=0.91,
                original_score=0.91,
                metadata={
                    "section": "Validation of Subjects",
                    "source_section": "Validation of Subjects",
                    "document_type": "handbook",
                    "page_number": 44,
                },
            ),
            RetrievedChunk(
                document_id="form-noise",
                title="Requirement: Clearance, Request Form Accounting",
                source_filename="form.pdf",
                chunk_index=2,
                text="Form Preview and Related Services for clearance.",
                relevance_score=0.93,
                original_score=0.93,
                metadata={
                    "title": "Requirement: Clearance, Request Form Accounting",
                    "article_type": "requirement_form",
                    "document_type": "requirement",
                    "extraction_status": "rag_only",
                },
            ),
            RetrievedChunk(
                document_id="charter-ready",
                title="ID Validation",
                source_filename="Citizens_Charter_2026.pdf",
                chunk_index=1,
                text=(
                    "Service: ID Validation\n"
                    "Office / Division: Office of the Student Affairs and Services\n"
                    "Present a valid school ID for validation."
                ),
                relevance_score=0.74,
                original_score=0.74,
                metadata={
                    "title": "ID Validation",
                    "source_section": "ID Validation",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "office": "Office of the Student Affairs and Services",
                    "page_number": 18,
                },
            ),
        ],
    )

    assert ranked[0].metadata["source_section"] == "ID Validation"
    assert any("boost_identity_service_title" in reason for reason in (ranked[0].rerank_reasons or []))


def test_citation_ready_chunk_preferred_when_scores_similar(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    from app.db.session import initialize_database
    from app.services.document_storage import persist_uploaded_document

    initialize_database()
    ready_id = "ready-citation-doc"
    persist_uploaded_document(
        b"%PDF-1.4 ready",
        document_id=ready_id,
        filename="Citizens_Charter_2026.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter 2026",
    )
    ranked = rerank_chunks(
        "student services overview",
        [
            RetrievedChunk(
                document_id="orphan-legacy",
                title="Student Handbook",
                source_filename="handbook.pdf",
                chunk_index=0,
                text="Student services overview and campus support offices.",
                relevance_score=0.8,
                original_score=0.8,
                metadata={"section": "Student Services", "page_number": 10},
            ),
            RetrievedChunk(
                document_id=ready_id,
                title="Citizen’s Charter",
                source_filename="Citizens_Charter_2026.pdf",
                chunk_index=1,
                text="Student services overview and campus support offices.",
                relevance_score=0.8,
                original_score=0.8,
                metadata={
                    "section": "Student Services",
                    "page_number": 10,
                    "document_id": ready_id,
                },
            ),
        ],
    )
    assert ranked[0].document_id == ready_id
    assert any("boost_level2_citation_ready" in reason for reason in (ranked[0].rerank_reasons or []))

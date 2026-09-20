from typing import Any

from app.services.chroma_store import RetrievedChunk
from app.services.retrieval_reranker import (
    MAX_HEURISTIC_DELTA_MAGNITUDE,
    _apply_heuristic_delta_cap,
    expand_query,
    is_faculty_restricted_query,
    prepare_retrieval_query,
    rerank_chunks,
)


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


def test_haircut_policy_query_ranks_hair_style_above_generic_named_policies():
    """Regression: 'X policy?' must not near-exact-match every '* Policy' title."""
    ranked = titles_for(
        "What is the haircut policy?",
        [
            chunk(
                "University Policy on On-the-job Training (OJT)/Practicum/ Internship",
                "OJT and internship policies for partner agencies.",
                0.83,
            ),
            chunk(
                "Substitution Policy",
                "Students may request subject substitution under academic load rules.",
                0.82,
            ),
            chunk(
                "Policy on Grades of 4 and 5",
                "Grade of 4 is conditional and grade of 5 is failing.",
                0.81,
            ),
            chunk(
                "Hair Style/Hair-cut",
                "The following are prohibited: colored hair and fixie crop hairstyles.",
                0.84,
                metadata={"section": "Hair Style/Hair-cut", "hierarchy_path": "Norms and Decorum > Hair Style/Hair-cut"},
            ),
            chunk(
                "Departure from approved hair-cut below",
                "2x3 for freshmen and 1x2 barbers cut for upper years.",
                0.85,
                metadata={
                    "section": "Departure from approved hair-cut below",
                    "hierarchy_path": "Norms and Decorum > Departure from approved hair-cut below",
                },
            ),
        ],
    )

    assert ranked[0] in {
        "Hair Style/Hair-cut",
        "Departure from approved hair-cut below",
    }
    assert "Substitution Policy" not in ranked[:2]


def test_generic_policy_word_does_not_near_exact_match_unrelated_policy_titles():
    from app.services.retrieval_reranker import (
        _intent_phrases,
        _normalize,
        _service_title_similarity_boost,
    )

    phrases = _intent_phrases(_normalize("What is the haircut policy?"))
    assert "policy" not in phrases
    assert "haircut" in phrases

    reasons: list[str] = []
    boost = _service_title_similarity_boost(
        phrases,
        _normalize("Substitution Policy"),
        reasons,
    )
    assert boost == 0.0


def test_dress_code_query_expands_to_norms_and_grooming_terms():
    prepared = prepare_retrieval_query("What is the haircut policy?")
    assert "dress_code_grooming" in prepared.matched_expansion_rules
    assert "hair style" in prepared.expanded_query.lower()
    assert "norms and decorum" in prepared.expanded_query.lower()


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


def test_warning_probation_continue_query_ranks_scholastic_delinquency_above_dropped():
    ranked = titles_for(
        "I'm already struggling in one semester. At what point does LSPU only warn me, put me on probation, or stop me from continuing?",
        [
            chunk(
                "Dropped",
                "Any student dropped from one college/school shall not be admitted to another course in LSPU, unless in the evaluation of the Dean, the student's aptitude and interest may qualify him/her to another field of study.",
                0.9,
            ),
            chunk(
                "Scholastic Delinquency",
                "Warning. At the end of the semester, a student who fails 25% to 49% of the total number of academic units. Probation. A student who fails 50% to 74% of registered units. A student who fails 75% or more may be dropped from the college.",
                0.72,
            ),
            chunk(
                "Retention Requirement",
                "After admission, the student must maintain good moral character and the required GWA.",
                0.7,
            ),
        ],
    )
    assert ranked[0] == "Scholastic Delinquency"


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


def test_leave_of_absence_query_does_not_expand_to_excuse_slip():
    prepared = prepare_retrieval_query("How do I apply for a Leave of Absence (LOA)?")
    expanded = prepared.expanded_query.casefold()
    assert "leave_of_absence" in prepared.matched_expansion_rules
    assert "attendance_excuse_slip" not in prepared.matched_expansion_rules
    assert "excuse slip" not in expanded
    assert "leave of absence" in expanded


def test_leave_of_absence_query_ranks_loa_above_attendance():
    ranked = titles_for(
        "How do I apply for a Leave of Absence (LOA)?",
        [
            chunk(
                "Policy",
                "A student absent from classes for unavoidable cause must obtain an excuse slip from OSAS or the Guidance Office.",
                0.91,
                metadata={"section": "Sec. 1 > Policy", "chapter": "Attendance"},
            ),
            chunk(
                "Leave of Absence (LOA)",
                "A student who intends to interrupt enrollment must file a written request for leave of absence with the Registrar, subject to approval of the Dean.",
                0.62,
                metadata={"section": "Leave of Absence (LOA)"},
            ),
        ],
    )
    assert ranked[0] == "Leave of Absence (LOA)"


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


def test_enrollment_office_question_ranks_enrollment_above_assessment_of_fees():
    results = titles_for(
        "which office is responsible for enrollment process?",
        [
            chunk(
                "Assessment of Fees",
                "Assessment of Fees verifies enrolment stub and registration form with Accounting.",
                0.92,
                metadata={
                    "section": "Assessment of Fees",
                    "title": "Assessment of Fees",
                    "source_section": "Assessment of Fees",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "office": "Accounting",
                },
            ),
            chunk(
                "Enrollment",
                "Enrollment is handled by the Office of the Registrar for all eligible students.",
                0.78,
                metadata={
                    "section": "Enrollment",
                    "title": "Enrollment",
                    "source_section": "Enrollment",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "office": "Office of the Registrar",
                },
            ),
            chunk(
                "IP Registration Process",
                "IP Registration Process is handled by Registrar staff for online registration.",
                0.9,
                metadata={
                    "section": "IP Registration Process",
                    "title": "IP Registration Process",
                    "source_section": "IP Registration Process",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "office": "Registrar",
                },
            ),
        ],
    )

    assert results[0] == "Enrollment"


def test_which_office_question_does_not_use_service_step_fallback():
    from app.services.qa.conversational_fallback import detect_fallback_intent, format_conversational_fallback

    chunk = RetrievedChunk(
        document_id="ip",
        title="IP Registration Process",
        source_filename="charter.pdf",
        chunk_index=0,
        text="Office / Division\nRegistrar\n\nSteps\n1. Client Step: Register online.",
        relevance_score=0.9,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": "IP Registration Process",
            "source_section": "IP Registration Process",
            "office": "Registrar",
        },
    )
    enrollment = RetrievedChunk(
        document_id="enroll",
        title="Enrollment",
        source_filename="charter.pdf",
        chunk_index=1,
        text="Office / Division\nOffice of the Registrar\n\nWho May Avail\nAll eligible students",
        relevance_score=0.8,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": "Enrollment",
            "source_section": "Enrollment",
            "office": "Office of the Registrar",
        },
    )
    question = "Which office is responsible for the enrollment process?"
    assert detect_fallback_intent(question, [chunk, enrollment]) == "policy"
    answer = format_conversational_fallback(question, [chunk, enrollment])
    assert "To complete" not in answer
    assert "Office of the Registrar" in answer or "Registrar" in answer
    assert "Enrollment" in answer


def test_prefer_service_chunks_puts_enrollment_before_fee_assessment():
    from app.services.qa.service_answer_formatter import prefer_service_chunks

    fee = RetrievedChunk(
        document_id="fee",
        title="Assessment of Fees",
        source_filename="charter.pdf",
        chunk_index=0,
        text="Assessment of Fees steps...",
        relevance_score=0.95,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": "Assessment of Fees",
            "source_section": "Assessment of Fees",
            "office": "Accounting",
            "extracted_steps": '[{"client_step":"Submit stub"}]',
        },
    )
    enrollment = RetrievedChunk(
        document_id="enroll",
        title="Enrollment",
        source_filename="charter.pdf",
        chunk_index=1,
        text="Enrollment Office / Division Office of the Registrar",
        relevance_score=0.8,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": "Enrollment",
            "source_section": "Enrollment",
            "office": "Office of the Registrar",
            "extracted_steps": '[{"client_step":"Submit enrollment slip"}]',
        },
    )
    ordered = prefer_service_chunks([fee, enrollment], question="which office is responsible for enrollment process?")
    assert ordered[0].title == "Enrollment"


def test_prefer_service_chunks_keeps_vision_above_charter_services():
    from app.services.qa.service_answer_formatter import prefer_service_chunks

    vision = RetrievedChunk(
        document_id="hb",
        title="VISION",
        source_filename="handbook.pdf",
        chunk_index=0,
        text="VISION LSPU as a center of technology...",
        relevance_score=0.92,
        reranked_score=0.92,
        metadata={
            "document_type": "student_handbook",
            "source_section": "VISION",
            "section": "VISION",
        },
    )
    service = RetrievedChunk(
        document_id="cc",
        title="LSPU Entrance Examination",
        source_filename="charter.pdf",
        chunk_index=1,
        text="Entrance examination requirements...",
        relevance_score=0.7,
        reranked_score=0.7,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "LSPU Entrance Examination",
            "office": "Admissions",
            "extracted_steps": '[{"client_step":"Apply online"}]',
        },
    )
    ordered = prefer_service_chunks(
        [vision, service],
        question="What is LSPU's vision?",
    )
    assert ordered[0].title == "VISION"


def test_teaching_load_ranks_faculty_manual_above_student_course_load():
    ranked = titles_for(
        "How is teaching load assigned at LSPU?",
        [
            chunk(
                "Course Load",
                "Course Load Graduate Studies Article 5 Course Load and Requirements.",
                0.9,
                metadata={
                    "section": "Course Load",
                    "source_filename": "LSPU Student Handbook.pdf",
                    "source_section": "Sec. 1 > Course Load",
                },
            ),
            chunk(
                "Teaching Load Assignment",
                "The Dean assigns teaching loads aligned with faculty specialization. Time allotment for teaching loads shall be observed.",
                0.72,
                metadata={
                    "section": "Teaching Load Assignment",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                    "source_section": "D. Teaching Load Assignment",
                },
            ),
        ],
    )
    assert ranked[0] == "Teaching Load Assignment"


def test_faculty_grading_ranks_grading_sheets_above_student_rectification():
    ranked = titles_for(
        "What are the faculty grading policies?",
        [
            chunk(
                "Change/Rectification of Grades Period",
                "Students may request change or rectification of grades within the prescribed period.",
                0.9,
                metadata={
                    "section": "Change/Rectification of Grades Period",
                    "source_filename": "LSPU Student Handbook.pdf",
                },
            ),
            chunk(
                "Grading Sheets and Other Academic Records",
                "Faculty shall submit grading sheets and other academic records through proper channels.",
                0.7,
                metadata={
                    "section": "Grading Sheets and Other Academic Records",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                },
            ),
        ],
    )
    assert ranked[0] == "Grading Sheets and Other Academic Records"


def test_shift_to_bs_program_ranks_shifting_of_course_above_dropped():
    ranked = titles_for(
        "Can I shift to another BS program if I failed more than six units this semester?",
        [
            chunk(
                "Dropped",
                "A student may be dropped after continued scholastic delinquency and failed academic units.",
                0.88,
            ),
            chunk(
                "Scholastic Delinquency",
                "Students with failed academic units may receive warning, probation, or dismissal.",
                0.84,
            ),
            chunk(
                "Shifting of Course",
                "Students from other courses can shift to any BS Program provided there is no failure of greater than six (6) units during the semester.",
                0.62,
                metadata={
                    "section": "Shifting of Course",
                    "source_filename": "LSPU Student Handbook.pdf",
                    "source_section": "2.10. Shifting of Course",
                },
            ),
        ],
    )
    assert ranked[0] == "Shifting of Course"


def test_shift_program_query_expands_to_shifting_not_scholastic_delinquency():
    prepared = prepare_retrieval_query(
        "Can I shift to another BS program if I failed more than six units this semester?"
    )
    expanded = prepared.expanded_query.casefold()
    assert "shifting of course" in expanded
    assert "shifting_of_course" in prepared.matched_expansion_rules
    assert "scholastic_delinquency_failed_units" not in prepared.matched_expansion_rules
    assert "undergraduate programs" not in expanded


def test_faculty_25_percent_grade_change_ranks_rectification_above_grading_sheets():
    ranked = titles_for(
        "If more than 25 percent of a class needs a grade change, what approval process is required?",
        [
            chunk(
                "Grading Sheets and Other Academic Records",
                "Faculty shall submit grading sheets and other academic records through proper channels.",
                0.86,
                metadata={
                    "section": "Grading Sheets and Other Academic Records",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                },
            ),
            chunk(
                "Change/Rectification of Grades",
                "If the number of students affected is twenty-five percent (25%) and above the class, "
                "the faculty must seek approval of the University President for an Academic Council Meeting.",
                0.64,
                metadata={
                    "section": "Change/Rectification of Grades",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                    "source_section": "J. Change/Rectification of Grades",
                },
            ),
        ],
    )
    assert ranked[0] == "Change/Rectification of Grades"


def test_faculty_25_percent_query_ranks_submission_of_grades_when_body_has_rectification():
    ranked = titles_for(
        "If more than 25 percent of a class needs a grade change, what approval process is required?",
        [
            chunk(
                "Grading Sheets and Other Academic Records",
                "Faculty shall submit grading sheets and other academic records through proper channels.",
                0.86,
                metadata={
                    "section": "Grading Sheets and Other Academic Records",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                },
            ),
            chunk(
                "Submission of Grades",
                "J. Change/Rectification of Grades. If the number of students affected is twenty-five percent "
                "(25%) and above the class, seek approval of the University President for an Academic Council Meeting.",
                0.61,
                metadata={
                    "section": "Submission of Grades",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                },
            ),
        ],
    )
    assert ranked[0] == "Submission of Grades"


def test_faculty_grade_change_query_expands_to_rectification_and_academic_council():
    prepared = prepare_retrieval_query(
        "If more than 25 percent of a class needs a grade change, what approval process is required?"
    )
    expanded = prepared.expanded_query.casefold()
    assert "rectification" in expanded
    assert "academic council" in expanded
    assert "faculty_grade_rectification" in prepared.matched_expansion_rules
    assert "faculty_grading_policies" not in prepared.matched_expansion_rules
    assert "submission of grades" in expanded


def test_faculty_responsibilities_ranks_commitment_above_chairperson_designation():
    ranked = titles_for(
        "What are the responsibilities of faculty members?",
        [
            chunk(
                "Regular Faculty Designated as Chairperson",
                "Regular Faculty Designated as Chairperson B. Faculty Attendance and Absences > 1.2 > Regular Faculty Designated as Chairperson Research = 10 hrs",
                0.88,
                metadata={
                    "section": "Regular Faculty Designated as Chairperson",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                    "source_section": "1.2 > Regular Faculty Designated as Chairperson",
                },
            ),
            chunk(
                "Commitment of the LSPU Faculty",
                "Teaching is a personal commitment of oneself to others. The Code of Ethics guides faculty responsibilities.",
                0.7,
                metadata={
                    "section": "Commitment of the LSPU Faculty",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                    "source_section": "III. Commitment of the LSPU Faculty",
                },
            ),
        ],
    )
    assert ranked[0] == "Commitment of the LSPU Faculty"


def test_faculty_teaching_load_query_expands_toward_faculty_manual():
    prepared = prepare_retrieval_query("How is teaching load assigned at LSPU?")
    expanded = prepared.expanded_query.casefold()
    assert "teaching load" in expanded
    assert "faculty manual" in expanded


def test_dismiss_class_early_expands_to_faculty_manual_not_academic_dismissal():
    prepared = prepare_retrieval_query("Can I dismiss my class earlier than the official time?")
    expanded = prepared.expanded_query.casefold()
    assert "faculty_class_dismiss_time" in prepared.matched_expansion_rules
    assert "faculty manual" in expanded
    assert "shall not be allowed to dismiss" in expanded
    assert "scholastic delinquency" not in expanded
    assert "academic dismissal" not in expanded


def test_dismiss_class_early_ranks_faculty_attendance_above_student_attendance():
    ranked = titles_for(
        "Can I dismiss my class earlier than the official time?",
        [
            chunk(
                "Attendance",
                "Students who are absent should submit an excuse slip to OSAS.",
                0.9,
                metadata={
                    "section": "Attendance",
                    "source_filename": "LSPU Student Handbook.pdf",
                    "source_section": "Attendance",
                },
            ),
            chunk(
                "Faculty Attendance and Absences",
                "Faculty member shall not be allowed to dismiss his/her classes earlier than the official time.",
                0.62,
                metadata={
                    "section": "Faculty Attendance and Absences",
                    "source_filename": "LSPU Faculty Manual 2020.pdf",
                    "document_type": "faculty_manual",
                    "source_section": "B. Faculty Attendance and Absences",
                },
            ),
        ],
    )
    assert ranked[0] == "Faculty Attendance and Absences"


def test_heuristic_delta_cap_bounds_runaway_positive_stacking():
    """A pathological pile-up of boosts must not fully drown out semantic score."""
    reasons: list[str] = []
    final_score = _apply_heuristic_delta_cap(original=0.5, score=50.0, reasons=reasons)

    assert final_score == 0.5 + MAX_HEURISTIC_DELTA_MAGNITUDE
    assert any(reason.startswith("clamped_heuristic_delta:") for reason in reasons)


def test_heuristic_delta_cap_bounds_runaway_negative_stacking():
    reasons: list[str] = []
    final_score = _apply_heuristic_delta_cap(original=0.5, score=-50.0, reasons=reasons)

    assert final_score == 0.5 - MAX_HEURISTIC_DELTA_MAGNITUDE
    assert any(reason.startswith("clamped_heuristic_delta:") for reason in reasons)


def test_heuristic_delta_cap_is_a_noop_within_normal_range():
    """Every currently-observed rule combination in this test module and the
    retrieval benchmark stays well under the cap, so normal scoring is untouched."""
    reasons: list[str] = []
    final_score = _apply_heuristic_delta_cap(original=0.7, score=0.7 + 3.4, reasons=reasons)

    assert final_score == 0.7 + 3.4
    assert reasons == []


def test_leading_ow_typo_still_retrieves_honorable_dismissal():
    prepared = prepare_retrieval_query("ow do I request honorable dismissal?")
    expanded = prepared.expanded_query.casefold()
    assert expanded.startswith("how ") or "how do i request honorable dismissal" in expanded
    assert "honorable dismissal" in expanded
    assert "registrar" in expanded


def test_maximum_residence_query_ranks_residence_rule_first():
    ranked = titles_for(
        "What is the maximum residence rule?",
        [
            chunk("Dormitory Residence", "Students living outside campus may leave for face-to-face classes.", 0.88),
            chunk(
                "Maximum Residence Rule",
                "A student must finish the requirements within a period of actual residence equivalent to 1.5 times the normal length prescribed for the course.",
                0.62,
            ),
        ],
    )
    assert ranked[0] == "Maximum Residence Rule"


def test_tor_cost_query_expands_without_peso_amounts():
    prepared = prepare_retrieval_query("How much does a transcript of records cost?")
    expanded = prepared.expanded_query.casefold()
    assert "transcript of records" in expanded
    assert "per page" in expanded
    assert "p75" not in expanded
    assert "75.00" not in expanded
    assert "p150" not in expanded


def test_tuition_refund_query_expands_without_percent_values():
    prepared = prepare_retrieval_query(
        "If I withdraw after paying enrollment fees, how much of my tuition is refunded?"
    )
    expanded = prepared.expanded_query.casefold()
    assert "refunding of fees" in expanded
    assert "seventy-five percent" not in expanded
    assert "fifty percent" not in expanded
    assert "75%" not in expanded
    assert "50%" not in expanded


def test_maximum_residence_query_expands_without_duration_literal():
    prepared = prepare_retrieval_query("What is the maximum residence rule?")
    expanded = prepared.expanded_query.casefold()
    assert "maximum residence rule" in expanded
    assert "actual residence" in expanded
    assert "1.5" not in expanded
    assert "times the normal length" not in expanded


def test_dean_instruction_load_and_campaign_questions_are_faculty_restricted():
    assert is_faculty_restricted_query(
        "How many instruction hours does a regular faculty member have in the weekly load?"
    )
    assert is_faculty_restricted_query(
        "If I am designated as dean, how does my weekly instruction load change?"
    )
    assert is_faculty_restricted_query("Can I use class time to campaign for a political party?")


# --- Phase 1 context-selection fix: false-positive domain penalties --------
# (penalty_disciplinary_offense_out_of_domain misfiring on a routine "check
# disciplinary records" verification step; penalty_awards_out_of_domain
# misfiring on "honor" matching inside "Honorable Dismissal") and the Good
# Moral Certificate query-expansion rule (previously injecting every
# requester category regardless of what the user actually asked).


def test_good_moral_certificate_not_falsely_penalized_as_disciplinary_content():
    """A routine 'check disciplinary records' verification step -- present on
    all three real Good Moral Certificate service cards -- must not itself
    flag the whole chunk as disciplinary-policy content."""
    ranked = rerank_chunks(
        "I'm an LSPU alumnus and I need a Good Moral Certificate, what do I need to bring?",
        [
            chunk(
                "Issuance of Good Moral Certificate (LSPU Alumni)",
                "Requirement: Transcript of Record. Agency Action: Receive and check submitted "
                "documents. Check disciplinary records. Preparation of Good Moral Certificate.",
                0.88,
                metadata={"chapter": "Citizen's Charter", "content_type": "service_card"},
            ),
        ],
    )
    assert "penalty_disciplinary_offense_out_of_domain" not in ranked[0].rerank_reasons


def test_genuine_disciplinary_offense_content_still_penalized_out_of_domain():
    """A real disciplinary-policy chunk (offense classification, sanctions) --
    not merely a routine records-check mention -- must still be penalized
    when the query is off-domain. Same fixture as the pre-existing
    'Non-wearing of ID' regression test, kept here as an explicit Phase 1
    negative control."""
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
                "Attendance Policy",
                "For absence due to illness, submit an excuse slip and medical certificate to OSAS.",
                0.72,
                metadata={"chapter": "Undergraduate Academic Policies", "article": "Attendance"},
            ),
        ],
    )
    noisy = next(r for r in ranked if r.metadata["section"] == "Non-wearing of ID")
    assert "penalty_disciplinary_offense_out_of_domain" in noisy.rerank_reasons


def test_refunding_of_fees_not_falsely_penalized_as_awards_content():
    """'honor' must not match as a substring inside 'Honorable Dismissal' --
    a withdrawal/transfer status with no connection to awards or honors."""
    ranked = rerank_chunks(
        "If I'm granted a Leave of Absence during the third week of classes, what percentage of "
        "my paid fees will be refunded?",
        [
            chunk(
                "Refunding of Fees",
                "A student who has paid the enrolment fees and who is granted Honorable Dismissal/"
                "Transfer Credentials or Leave of Absence (LOA) is entitled to a refund of their "
                "fees: 75% within the first week, 50% within the second to fourth week, no refund "
                "after the fourth week.",
                0.87,
                metadata={"chapter": "Undergraduate Academic Policies", "article": "Registration"},
            ),
        ],
    )
    assert "penalty_awards_out_of_domain" not in ranked[0].rerank_reasons


def test_genuine_awards_content_still_penalized_out_of_domain():
    """A real awards/honors/recognition chunk must still be penalized when
    the query is off-domain -- the word-boundary fix must not blind the
    penalty to genuine occurrences of 'award'/'honor'."""
    ranked = rerank_chunks(
        "What is scholastic delinquency under retention policies?",
        [
            chunk(
                "Academic Awards",
                "Awards and honors are granted to students with excellent grades and recognition.",
                0.9,
            ),
            chunk(
                "Scholastic Delinquency",
                "Retention Policies define scholastic delinquency, warning, probation, dropped status, and dismissal.",
                0.71,
                metadata={"chapter": "Undergraduate Academic Policies", "article": "Retention Policies"},
            ),
        ],
    )
    noisy = next(r for r in ranked if r.metadata["section"] == "Academic Awards")
    assert "penalty_awards_out_of_domain" in noisy.rerank_reasons


def test_good_moral_alumni_intent_does_not_inject_undergraduate():
    prepared = prepare_retrieval_query(
        "I'm an LSPU alumnus and I need a Good Moral Certificate, what do I need to bring?"
    )
    expanded = prepared.expanded_query.casefold()
    assert "good_moral_certificate_alumni" in prepared.matched_expansion_rules
    assert "undergraduate" not in expanded
    assert "alumni" in expanded or "alumnus" in expanded


def test_good_moral_alumni_paraphrase_still_matches_alumni_rule():
    prepared = prepare_retrieval_query(
        "I already graduated from LSPU -- how do I get a certificate of good moral character?"
    )
    assert "good_moral_certificate_alumni" in prepared.matched_expansion_rules
    assert "undergraduate" not in prepared.expanded_query.casefold()


def test_good_moral_transferee_intent_does_not_inject_other_categories():
    prepared = prepare_retrieval_query(
        "As a transferee, what do I need for a good moral certificate?"
    )
    expanded = prepared.expanded_query.casefold()
    assert "good_moral_certificate_transferee" in prepared.matched_expansion_rules
    assert "transferee" in expanded
    assert "undergraduate" not in expanded
    assert "alumnus" not in expanded and "alumni" not in expanded


def test_good_moral_undergraduate_intent_does_not_inject_other_categories():
    prepared = prepare_retrieval_query(
        "As a currently enrolled undergraduate student, how do I request a good moral certificate?"
    )
    expanded = prepared.expanded_query.casefold()
    assert "good_moral_certificate_undergraduate" in prepared.matched_expansion_rules
    assert "undergraduate" in expanded
    assert "transferee" not in expanded
    assert "alumnus" not in expanded and "alumni" not in expanded


def test_good_moral_generic_intent_preserves_recall_across_all_variants():
    """No requester category stated -- must still expand toward all three
    variants so a genuinely ambiguous question keeps its recall."""
    prepared = prepare_retrieval_query("How do I get a Good Moral Certificate?")
    expanded = prepared.expanded_query.casefold()
    assert "good_moral_certificate_generic" in prepared.matched_expansion_rules
    assert "undergraduate" in expanded
    assert "alumnus" in expanded
    assert "transferee" in expanded


def test_fg_j1_alumni_good_moral_chunk_no_longer_receives_false_penalty():
    """Direct reranker-level regression test for the fg_j1 Fresh Gold
    failure: the Alumni variant, scored against an explicit alumni query,
    must not carry the disciplinary false-positive that previously caused
    it to be vetoed during context selection."""
    ranked = rerank_chunks(
        "I'm an LSPU alumnus and I need a Good Moral Certificate, what do I need to bring?",
        [
            chunk(
                "Issuance of Good Moral Certificate (LSPU Alumni)",
                "Requirement: Transcript of Record (TOR). Agency Action: Receive and check "
                "submitted documents. Check disciplinary records. Preparation of Good Moral "
                "Certificate. Fees: None.",
                0.88,
                metadata={"chapter": "Citizen's Charter"},
            ),
            chunk(
                "Issuance of Good Moral Certificate (Undergraduate)",
                "Requirement: Certificate of Registration. Agency Action: Receive and check "
                "submitted documents. Check disciplinary records. Preparation of Good Moral "
                "Certificate. Fees: None.",
                0.87,
                metadata={"chapter": "Citizen's Charter"},
            ),
        ],
    )
    reasons_by_section = {r.metadata["section"]: r.rerank_reasons for r in ranked}
    assert "penalty_disciplinary_offense_out_of_domain" not in reasons_by_section[
        "Issuance of Good Moral Certificate (LSPU Alumni)"
    ]
    assert "penalty_disciplinary_offense_out_of_domain" not in reasons_by_section[
        "Issuance of Good Moral Certificate (Undergraduate)"
    ]


def test_fg_a1_refunding_of_fees_chunk_no_longer_receives_false_penalty():
    """Direct reranker-level regression test for the fg_a1 Fresh Gold
    failure."""
    ranked = rerank_chunks(
        "If I'm granted a Leave of Absence during the third week of classes, what percentage of "
        "my paid fees will be refunded?",
        [
            chunk(
                "Refunding of Fees",
                "A student who has paid the enrolment fees and who is granted Honorable "
                "Dismissal/Transfer Credentials or Leave of Absence (LOA) is entitled to a "
                "refund of their fees: 75% within the first week, 50% within the second to "
                "fourth week, no refund after the fourth week.",
                0.87,
                metadata={"chapter": "Undergraduate Academic Policies", "article": "Registration"},
            ),
        ],
    )
    assert "penalty_awards_out_of_domain" not in ranked[0].rerank_reasons
    assert not is_faculty_restricted_query("What is the maximum residence rule?")


def test_generic_policy_title_penalty_ignores_ancestor_chapter_label():
    """A chunk's OWN title decides whether it is a generic "* Policy" wrapper,
    not the chapter/article label it happens to be filed under.

    ``cec01713::34`` ("Classifications of Students") is specifically titled
    and answers "How many units ... Junior student?" from its own body text,
    but it is filed under the "Undergraduate Academic Policies" chapter. That
    ancestor label alone must not trigger
    ``penalty_generic_policy_title_without_topic`` -- doing so wrongly
    penalized this and 94 other similarly-filed chunks (fg_c2 investigation).
    """
    ranked = rerank_chunks(
        "How many units do I need to have earned to be classified as a Junior student?",
        [
            chunk(
                "Classifications of Students",
                "Junior. A student who has earned fifty to seventy-five percent (50%-75%) "
                "of the total units required in the entire course.",
                0.89,
                metadata={"chapter": "Undergraduate Academic Policies"},
            ),
        ],
    )
    assert "penalty_generic_policy_title_without_topic" not in ranked[0].rerank_reasons
    assert "boost_distinctive_content_terms:units,earned,junior" in ranked[0].rerank_reasons


def test_generic_policy_title_penalty_still_applies_to_own_generic_title():
    """A chunk that is ITSELF generically titled (no ancestor chapter needed)
    must still receive the penalty -- the fix narrows the signal source, it
    does not remove the check.
    """
    ranked = rerank_chunks(
        "What is the haircut policy?",
        [
            chunk(
                "Attendance Policy",
                "A brief mention of haircut grooming standards appears in a footnote here.",
                0.7,
            ),
        ],
    )
    assert "penalty_generic_policy_title_without_topic" in ranked[0].rerank_reasons

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

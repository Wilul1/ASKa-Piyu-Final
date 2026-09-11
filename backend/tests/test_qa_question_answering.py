from unittest.mock import patch

import pytest

from app.services.chroma_store import RetrievedChunk
from app.services.qa.groq_answer_service import GroqAnswerError
from app.services.qa.question_answering import (
    PROGRAM_COLLECTION,
    FACULTY_SIGNIN_ANSWER,
    FINAL_CONTEXT_CHUNKS,
    GREETING_ANSWER,
    GREETING_QUESTION,
    OUT_OF_SCOPE_ANSWER,
    RAW_RETRIEVAL_CANDIDATES,
    _confidence_for,
    answer_qa_question,
    detect_collection_intent,
    detect_broad_query,
    format_retrieved_context,
    is_greeting_query,
)


def chunk(
    title: str,
    text: str,
    *,
    score: float = 0.86,
    page: int = 46,
    path: tuple[str, str, str] | None = None,
    reasons: list[str] | None = None,
) -> RetrievedChunk:
    chapter, article, section = path or ("Student Handbook", "Academic Policies", title)
    return RetrievedChunk(
        document_id=title.lower().replace(" ", "-"),
        title="LSPU Student Handbook",
        source_filename="handbook.pdf",
        chunk_index=0,
        text=text,
        relevance_score=score,
        original_score=score - 0.08,
        reranked_score=score,
        rerank_reasons=reasons or ["test_match"],
        metadata={
            "chapter": chapter,
            "article": article,
            "section": section,
            "page_start": page,
            "audience": "both",
        },
    )


class FakeStore:
    chunk_count = 485

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls = []
        self.chunk_count = max(len(chunks), 1)

    def search(
        self,
        question: str,
        *,
        top_k: int | None = None,
        raw_k: int | None = None,
        user_role: str | None = None,
    ):
        self.calls.append(
            {"question": question, "top_k": top_k, "raw_k": raw_k, "user_role": user_role}
        )
        return self.chunks

    def list_chunks(self):
        items = []
        for chunk in self.chunks:
            metadata = dict(chunk.metadata or {})
            metadata.setdefault("document_id", chunk.document_id)
            metadata.setdefault("source_filename", chunk.source_filename)
            metadata.setdefault("chunk_index", chunk.chunk_index)
            items.append(
                {
                    "id": f"{chunk.document_id}::{chunk.chunk_index}",
                    "text": chunk.text,
                    "metadata": metadata,
                }
            )
        return items


def run_question(question: str, chunks: list[RetrievedChunk], *, user_role: str | None = None):
    store = FakeStore(chunks)
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value="Follow the cited policy in the retrieved context.",
        ) as mock_generate,
    ):
        result = answer_qa_question(question, user_role=user_role)
    return result, store, mock_generate


def test_faculty_manual_question_as_guest_asks_to_sign_in():
    result, store, mock_generate = run_question(
        "How many instruction hours does a regular faculty member have in the weekly load?",
        [chunk("Course Load", "Graduate studies maximum load is nine units per semester.")],
    )
    assert result.answer == FACULTY_SIGNIN_ANSWER
    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert "faculty manual" not in result.answer.casefold()
    assert "sign in" not in result.answer.casefold()
    assert store.calls == []
    mock_generate.assert_not_called()


def test_dean_instruction_load_as_guest_asks_to_sign_in():
    result, store, mock_generate = run_question(
        "If I am designated as dean, how does my weekly instruction load change?",
        [chunk("Course Load", "A student's maximum load is nine (9) units per semester.")],
    )
    assert result.answer == FACULTY_SIGNIN_ANSWER
    assert store.calls == []
    mock_generate.assert_not_called()


def test_dismiss_class_early_as_student_asks_to_sign_in_for_faculty_manual():
    result, store, mock_generate = run_question(
        "Can I dismiss my class earlier than the official time?",
        [chunk("Attendance Policy", "Students should submit an excuse slip.")],
    )
    assert result.answer == FACULTY_SIGNIN_ANSWER
    assert store.calls == []
    mock_generate.assert_not_called()


def test_dismiss_class_early_as_faculty_uses_faculty_manual_context():
    faculty_rule = RetrievedChunk(
        document_id="faculty-attendance",
        title="LSPU Faculty Manual 2020",
        source_filename="LSPU Faculty Manual 2020.pdf",
        chunk_index=0,
        text=(
            "Faculty member shall not be allowed to dismiss his/her classes "
            "earlier than the official time."
        ),
        relevance_score=0.81,
        original_score=0.73,
        reranked_score=0.81,
        rerank_reasons=["boost_faculty_dismiss_class_rule"],
        metadata={
            "chapter": "University Policies",
            "article": "Faculty Attendance and Absences",
            "section": "Faculty Attendance and Absences",
            "page_start": 10,
            "audience": "faculty",
            "document_type": "faculty_manual",
            "source_filename": "LSPU Faculty Manual 2020.pdf",
        },
    )
    result, store, mock_generate = run_question(
        "Can I dismiss my class earlier than the official time?",
        [faculty_rule],
        user_role="faculty",
    )
    assert result.answer != FACULTY_SIGNIN_ANSWER
    assert store.calls
    assert store.calls[0]["user_role"] == "faculty"
    assert "not be allowed to dismiss" in mock_generate.call_args.kwargs["context"]


def test_qa_absence_due_to_illness_uses_attendance_context():
    result, store, mock_generate = run_question(
        "I was absent due to illness. What should I do?",
        [
            chunk(
                "Attendance Policy",
                "For absence due to illness, a student should submit an excuse slip and medical certificate to OSAS.",
            )
        ],
    )

    assert store.calls[0]["top_k"] == FINAL_CONTEXT_CHUNKS
    assert store.calls[0]["raw_k"] == RAW_RETRIEVAL_CANDIDATES
    assert "Title: Attendance Policy" in mock_generate.call_args.kwargs["context"]
    assert result.sources[0]["title"] == "Attendance Policy"
    assert result.confidence in {"high", "medium"}


def test_qa_validate_id_typed_procedure_answer_does_not_crash_on_source_label_fallback():
    """Typed procedure answers call _source_label(..., fallback=...); must not TypeError."""
    procedure_chunk = RetrievedChunk(
        document_id="charter-doc",
        title="ID Validation",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=0,
        text=(
            "Overview\nThis service provides assistance for ID Validation.\n\n"
            "Office / Division\nOffice of the Student Affairs and Services\n\n"
            "Requirements\n"
            "- Requirement: Certificate of Registration\n"
            "- Requirement: Student ID\n\n"
            "Steps\n"
            "1. Client Step: Present the Certificate of Registration.\n"
            "   Agency Action: Check Certificate of Registration.\n"
            "2. Client Step: Evaluate the services rendered by OSAS.\n"
            "3. Client Step: Accept the validated ID.\n\n"
            "Fees\nNone\n\n"
            "Total Processing Time\n4 minutes\n\n"
            "Page: 18"
        ),
        relevance_score=0.93,
        original_score=0.8,
        reranked_score=0.93,
        rerank_reasons=["boost_identity_service_title"],
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "document_id": "charter-doc",
            "title": "ID Validation",
            "source_section": "ID Validation",
            "source_document": "Citizens_Charter_2026.pdf",
            "source_filename": "Citizens_Charter_2026.pdf",
            "office": "Office of the Student Affairs and Services",
            "page_number": 18,
            "audience": "both",
        },
    )
    noise = RetrievedChunk(
        document_id="form-doc",
        title="Requirement: Clearance, Request Form Accounting",
        source_filename="form.pdf",
        chunk_index=1,
        text="Form Preview: x\nRelated Services: Accounting",
        relevance_score=0.96,
        original_score=0.9,
        reranked_score=0.96,
        rerank_reasons=["semantic_similarity"],
        metadata={
            "document_type": "requirement",
            "article_type": "requirement_form",
            "title": "Requirement: Clearance, Request Form Accounting",
            "extraction_status": "rag_only",
            "audience": "both",
        },
    )
    store = FakeStore([noise, procedure_chunk])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
    ):
        result = answer_qa_question("How do I validate my ID?")

    # How-tos prefer Groq; on failure, typed procedure formatter is used.
    assert result.fallback_used is True
    assert "ID Validation" in result.answer or "validate" in result.answer.lower()
    assert "Certificate of Registration" in result.answer
    assert "Student ID" in result.answer
    assert "Office of the Student Affairs and Services" in result.answer
    assert "4 minutes" in result.answer
    assert "Form Preview" not in result.answer
    assert "Requirement: Clearance" not in result.answer
    assert result.sources
    assert result.sources[0]["source_section"] == "ID Validation"
    assert result.sources[0]["page_number"] == 18


def test_qa_shifting_course_uses_shifting_policy_context():
    result, _, mock_generate = run_question(
        "How do I shift course?",
        [
            chunk(
                "Shifting of Course",
                "A student must secure approval and submit the shifting form to the Office of the Registrar.",
                page=52,
            )
        ],
    )

    assert "Shifting of Course" in mock_generate.call_args.kwargs["context"]
    assert result.sources[0]["page"] == 52


def test_qa_dismissal_policy_uses_academic_dismissal_context():
    result, _, _ = run_question(
        "What is the dismissal policy?",
        [
            chunk(
                "Retention Policies - Dismissal",
                "Academic dismissal may apply under retention policies after scholastic delinquency.",
            ),
            chunk(
                "Honorable Dismissal",
                "Honorable dismissal concerns voluntary withdrawal and transfer credential requests.",
                score=0.55,
            ),
        ],
    )

    assert result.retrieved_chunks[0]["title"] == "Retention Policies - Dismissal"
    assert result.retrieved_chunks[0]["reranked_score"] > result.retrieved_chunks[1]["reranked_score"]


def test_qa_failing_many_subjects_uses_scholastic_delinquency_context():
    result, _, mock_generate = run_question(
        "What are the consequences of failing many subjects?",
        [
            chunk(
                "Scholastic Delinquency",
                "Failed academic units may result in warning, probation, dismissal, or being dropped.",
            )
        ],
    )

    assert "Scholastic Delinquency" in mock_generate.call_args.kwargs["context"]
    assert result.sources[0]["title"] == "Scholastic Delinquency"


def test_qa_undergraduate_ccs_programs_uses_program_context():
    result, _, mock_generate = run_question(
        "What programs are offered by the College of Computer Studies in undergraduate studies?",
        [
            chunk(
                "College of Computer Studies - Undergraduate Programs",
                "Programs: BS Computer Science, BS Information System, BS Information Technology. Campuses: All Campuses.",
                path=("Curricular Offerings", "College of Computer Studies", "Undergraduate Programs"),
            )
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "BS Computer Science" in context
    assert result.sources[0]["path"] == "Curricular Offerings > College of Computer Studies > Undergraduate Programs"


def test_qa_graduation_requirements_uses_graduation_context():
    result, _, mock_generate = run_question(
        "What are the graduation requirements?",
        [
            chunk(
                "Graduation Requirements",
                "Candidates for graduation must satisfy curricular requirements and clearance obligations.",
                page=88,
            )
        ],
    )

    assert "Graduation Requirements" in mock_generate.call_args.kwargs["context"]
    assert result.sources[0]["page"] == 88


@pytest.mark.parametrize(
    ("question", "title", "text", "path_tail"),
    [
        (
            "Who is the university president?",
            "Administrative Officials",
            "DR. MARIO R. BRIONES is listed as University President.",
            "Administrative Officials",
        ),
        (
            "How do I enroll?",
            "Enrollment Procedure",
            "Enrollment requires registration, assessment of fees, and confirmation through the registrar.",
            "Enrollment Procedure",
        ),
        (
            "Where can I get a TOR?",
            "Transcript of Records",
            "Students may request a Transcript of Records or TOR from the Registrar.",
            "Transcript of Records",
        ),
        (
            "What services does the Guidance Office provide?",
            "Guidance Services",
            "Guidance services include counseling, referrals, and student support.",
            "Guidance Services",
        ),
    ],
)
def test_common_student_questions_select_matching_context(question: str, title: str, text: str, path_tail: str):
    result, _, mock_generate = run_question(
        question,
        [
            chunk(
                title,
                text,
                score=0.9,
                path=("Student Handbook", title, path_tail),
                reasons=["test_match"],
            )
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    assert text in context
    assert result.sources[0]["title"] == path_tail
    assert result.selected_context_count == 1


def test_ccs_programs_do_not_return_student_development_services_source():
    result, _, mock_generate = run_question(
        "What programs are offered by the College of Computer Studies?",
        [
            chunk(
                "College of Computer Studies - Undergraduate Programs",
                "Programs: BS Computer Science, BS Information System, BS Information Technology.",
                score=0.88,
                path=("Curricular Offerings", "College of Computer Studies", "Undergraduate Programs"),
                reasons=["boost_path_domain_match:curricular", "boost_curricular_path_match:computer_studies"],
            ),
            chunk(
                "Student Development Services",
                "Student Development Services include counseling, admission assistance, registrar services, and Tele-Web.",
                score=0.83,
                path=("Student Services", "Student Development Services", "Services"),
                reasons=["penalty_unrequested_student_services", "penalty_unrequested_counseling"],
            ),
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "BS Computer Science" in context
    assert "Student Development Services include" not in context
    assert [source["title"] for source in result.sources] == ["College of Computer Studies"]
    assert result.retrieved_chunks[0]["selected_for_context"] is True
    assert len(result.retrieved_chunks) == 1


def test_engineering_programs_keep_engineering_curricular_chunk():
    result, _, mock_generate = run_question(
        "What engineering programs are offered?",
        [
            chunk(
                "College of Engineering - Undergraduate Programs",
                "Programs: BS Civil Engineering, BS Electrical Engineering, and BS Mechanical Engineering.",
                score=0.87,
                path=("Curricular Offerings", "College of Engineering", "Undergraduate Programs"),
                reasons=["boost_path_domain_match:curricular", "boost_curricular_path_match:engineering"],
            ),
            chunk(
                "College of Computer Studies - Undergraduate Programs",
                "Programs: BS Computer Science and BS Information Technology.",
                score=0.7,
                path=("Curricular Offerings", "College of Computer Studies", "Undergraduate Programs"),
                reasons=["boost_path_domain_match:curricular"],
            ),
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "BS Civil Engineering" in context
    assert result.sources[0]["path"] == "Curricular Offerings > College of Engineering > Undergraduate Programs"


def test_excuse_slip_context_excludes_ojt_and_id_offense_noise():
    result, _, mock_generate = run_question(
        "I was absent due to illness. How do I file an excuse slip?",
        [
            chunk(
                "Attendance Policy",
                "For absence due to illness, submit an excuse slip and medical certificate to OSAS.",
                score=0.89,
                path=("Undergraduate Academic Policies", "Attendance", "Attendance Policy"),
                reasons=["attendance_policy_match", "boost_path_domain_match:attendance"],
            ),
            chunk(
                "Appendix J",
                "Excuse Slip form for absences due to illness.",
                score=0.78,
                path=("Appendices", "Appendix J", "Excuse Slip"),
                reasons=["attendance_policy_match", "penalty_unrelated_appendix"],
            ),
            chunk(
                "OJT Procedures",
                "OJT procedure steps and process flow for trainees.",
                score=0.74,
                path=("Student Internship", "OJT", "OJT Procedures"),
                reasons=["penalty_unrelated_procedure"],
            ),
            chunk(
                "Non-wearing of ID",
                "Minor offense: non-wearing of identification card is subject to sanction.",
                score=0.73,
                path=("Student Discipline", "Minor Offenses", "Non-wearing of ID"),
                reasons=["penalty_disciplinary_offense_out_of_domain"],
            ),
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    source_titles = [source["title"] for source in result.sources]
    assert "Attendance Policy" in context
    assert "Excuse Slip form" in context
    assert "OJT procedure" not in context
    assert "non-wearing" not in context
    assert source_titles == ["Attendance Policy", "Excuse Slip"]


def test_scholastic_delinquency_context_excludes_foreword_awards_and_offenses():
    result, _, mock_generate = run_question(
        "What is scholastic delinquency under retention policies?",
        [
            chunk(
                "Scholastic Delinquency",
                "Retention Policies define scholastic delinquency, warning, probation, dropped status, and dismissal.",
                score=0.9,
                path=("Undergraduate Academic Policies", "Retention Policies", "Scholastic Delinquency"),
                reasons=["academic_policy_match", "boost_path_domain_match:retention"],
            ),
            chunk(
                "Retention Policies - Probation",
                "A student may be placed under probation under the retention policies.",
                score=0.8,
                path=("Undergraduate Academic Policies", "Retention Policies", "Probation"),
                reasons=["academic_policy_match", "boost_path_domain_match:retention"],
            ),
            chunk(
                "Foreword",
                "This handbook introduces the institution and its ideals.",
                score=0.79,
                path=("Student Handbook", "Foreword", "Foreword"),
                reasons=["semantic_similarity"],
            ),
            chunk(
                "Academic Awards",
                "Awards and honors are granted to students with excellent grades.",
                score=0.76,
                path=("Student Awards", "Awards", "Academic Awards"),
                reasons=["penalty_awards_out_of_domain", "penalty_retention_awards_noise"],
            ),
            chunk(
                "Major Offenses",
                "Major offenses and disciplinary sanctions are handled by the discipline board.",
                score=0.75,
                path=("Student Discipline", "Major Offenses", "Major Offenses"),
                reasons=["penalty_disciplinary_offense_out_of_domain"],
            ),
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    source_titles = [source["title"] for source in result.sources]
    assert "scholastic delinquency" in context
    assert "probation under the retention policies" in context
    assert "introduces the institution" not in context
    assert "Awards and honors" not in context
    assert "disciplinary sanctions" not in context
    assert source_titles == ["Scholastic Delinquency", "Probation"]


def test_scholastic_delinquency_question_sends_policy_context_and_returns_answer():
    policy_text = (
        "The University Academic Council shall promulgate rules and guidelines governing scholastic delinquency, "
        "subject to the approval of the Board of Regents, and to the following minimum standards: "
        "Warning applies when a student fails 25% to 49% of registered academic units. "
        "Probation applies when a student fails 50% to 74% of registered academic units."
    )
    store = FakeStore(
        [
            chunk(
                "Scholastic Delinquency",
                policy_text,
                score=0.91,
                path=("Undergraduate Academic Policies", "Retention Policies", "Scholastic Delinquency"),
                reasons=["academic_policy_match", "boost_path_domain_match:retention"],
            )
        ]
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        assert question == "What is scholastic delinquency?"
        assert "Content:\n" in context
        assert "The University Academic Council shall promulgate rules and guidelines" in context
        assert "Probation applies when a student fails 50% to 74%" in context
        return (
            "Scholastic delinquency is governed by University Academic Council rules and minimum standards. "
            "The policy includes warning for failing 25% to 49% of registered units and probation for failing "
            "50% to 74% of registered units."
        )

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", side_effect=generate_from_context),
    ):
        result = answer_qa_question("What is scholastic delinquency?")

    assert "do not contain enough information" not in result.answer.lower()
    assert "warning for failing 25% to 49%" in result.answer
    assert result.sources[0]["title"] == "Scholastic Delinquency"
    assert result.retrieved_chunks[0]["selected_for_context"] is True


@pytest.mark.parametrize(
    "question",
    [
        "What is scholastic delinquency?",
        "What happens if I fail 75% of my units?",
        "What is retention policy?",
        "What are the warning and probation rules?",
    ],
)
def test_academic_policy_questions_generate_helpful_grounded_answers(question: str):
    policy_text = (
        "The University Academic Council shall promulgate rules and guidelines governing scholastic delinquency, "
        "subject to the approval of the Board of Regents, and to the following minimum standards: "
        "Warning applies when a student fails 25% to 49% of registered academic units. "
        "Probation applies when a student fails 50% to 74% of registered academic units. "
        "Dismissal from the College may apply when a student fails more than 75% of registered academic units."
    )
    store = FakeStore(
        [
            chunk(
                "Scholastic Delinquency",
                policy_text,
                score=0.91,
                path=("Undergraduate Academic Policies", "Retention Policies", "Scholastic Delinquency"),
                reasons=["academic_policy_match", "boost_path_domain_match:retention"],
            )
        ]
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        assert "Warning applies when a student fails 25% to 49%" in context
        assert "Probation applies when a student fails 50% to 74%" in context
        assert "Dismissal from the College may apply when a student fails more than 75%" in context
        return (
            "Based on the handbook, scholastic delinquency refers to poor academic performance measured by "
            "failed academic units. Under this policy, failing 25% to 49% leads to warning, 50% to 74% "
            "leads to probation, and more than 75% may lead to dismissal from the College."
        )

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", side_effect=generate_from_context),
    ):
        result = answer_qa_question(question)

    assert "do not contain enough information" not in result.answer.lower()
    assert "does not provide a direct definition" not in result.answer.lower()
    assert "source:" not in result.answer.lower()
    assert "sources:" not in result.answer.lower()
    assert "failing 25% to 49%" in result.answer
    assert "50% to 74%" in result.answer
    assert "more than 75%" in result.answer
    assert result.sources[0]["title"] == "Scholastic Delinquency"


def test_graduation_requirements_can_keep_multiple_relevant_chunks():
    result, _, mock_generate = run_question(
        "What are the graduation requirements and clearance procedures?",
        [
            chunk(
                "Graduation Requirements",
                "Candidates for graduation must satisfy all curricular requirements.",
                score=0.9,
                page=88,
                path=("Undergraduate Academic Policies", "Graduation", "Graduation Requirements"),
                reasons=["boost_path_domain_match:graduation"],
            ),
            chunk(
                "Graduation Clearance",
                "Graduation clearance must be completed before commencement.",
                score=0.84,
                page=89,
                path=("Undergraduate Academic Policies", "Graduation", "Graduation Clearance"),
                reasons=["boost_path_domain_match:graduation"],
            ),
            chunk(
                "Application for Graduation",
                "Application for graduation is filed before the deadline.",
                score=0.8,
                page=90,
                path=("Undergraduate Academic Policies", "Graduation", "Application for Graduation"),
                reasons=["boost_path_domain_match:graduation"],
            ),
            chunk(
                "Graduation Ceremony",
                "Commencement and graduation ceremony instructions are announced by the college.",
                score=0.77,
                page=91,
                path=("Undergraduate Academic Policies", "Graduation", "Graduation Ceremony"),
                reasons=["boost_path_domain_match:graduation"],
            ),
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "Graduation Requirements" in context
    assert "Graduation Clearance" in context
    assert "Application for Graduation" in context
    assert len(result.sources) == 1
    assert result.sources[0]["matching_sections"] == 3


def broad_chunks() -> list[RetrievedChunk]:
    return [
        chunk(
            "College of Computer Studies - Undergraduate Programs",
            "Programs: BS Computer Science, BS Information System, BS Information Technology. Campuses: All Campuses.",
            score=0.92,
            page=10,
            path=("Curricular Offerings", "College of Computer Studies", "Undergraduate Programs"),
            reasons=["boost_path_domain_match:curricular", "test_match"],
        ),
        chunk(
            "College of Computer Studies - BSCS",
            "BSCS means Bachelor of Science in Computer Science.",
            score=0.89,
            page=11,
            path=("Curricular Offerings", "College of Computer Studies", "BSCS"),
            reasons=["boost_path_domain_match:curricular", "test_match"],
        ),
        chunk(
            "College of Engineering - Undergraduate Programs",
            "Programs: BS Civil Engineering, BS Computer Engineering, BS Electrical Engineering.",
            score=0.88,
            page=12,
            path=("Curricular Offerings", "College of Engineering", "Undergraduate Programs"),
            reasons=["boost_path_domain_match:curricular", "test_match"],
        ),
        chunk(
            "College of Agriculture - Undergraduate Programs",
            "Programs: BS Agriculture, BS Agribusiness, BS Food Technology.",
            score=0.86,
            page=13,
            path=("Curricular Offerings", "College of Agriculture", "Undergraduate Programs"),
            reasons=["boost_path_domain_match:curricular", "test_match"],
        ),
        chunk(
            "Foreword",
            "This handbook introduces the institution and its ideals.",
            score=0.82,
            page=1,
            path=("Student Handbook", "Foreword", "Foreword"),
            reasons=["semantic_similarity"],
        ),
    ]


@pytest.mark.parametrize(
    "question",
    [
        "What programs are offered by the university?",
        "List all programs.",
    ],
)
def test_broad_program_questions_select_multiple_curricular_sources(question: str):
    result, store, mock_generate = run_question(question, broad_chunks())

    context = mock_generate.call_args.kwargs["context"]
    source_paths = [source["path"] for source in result.sources]

    assert store.calls == []
    assert mock_generate.call_args.kwargs["broad_mode"] is True
    assert "BS Computer Science" in context
    assert "BS Civil Engineering" in context
    assert "BS Agriculture" in context
    assert "This handbook introduces" not in context
    assert any("College of Computer Studies" in path for path in source_paths)
    assert any("College of Engineering" in path for path in source_paths)
    assert any("College of Agriculture" in path for path in source_paths)
    assert len([path for path in source_paths if "College of Computer Studies" in path]) == 1
    assert result.broad_query is True
    assert result.detected_intent == PROGRAM_COLLECTION
    assert result.collection_mode is True
    assert result.selected_context_count == 4
    assert result.confidence == "high"


@pytest.mark.parametrize(
    "question",
    [
        "What programs are offered by the university?",
        "List all degree programs.",
        "What courses does LSPU offer?",
    ],
)
def test_program_collection_context_groups_programs_by_college(question: str):
    chunks = broad_chunks() + [
        chunk(
            "College of Engineering - Duplicate Programs",
            "Programs: Engineering, BS Civil Engineering, BS Mechanical Engineering",
            score=0.84,
            page=14,
            path=("Curricular Offerings", "College of Engineering", "Duplicate Programs"),
            reasons=["boost_path_domain_match:curricular", "test_match"],
        )
    ]

    result, _, mock_generate = run_question(question, chunks)

    context = mock_generate.call_args.kwargs["context"]
    assert "Collection Intent: PROGRAM_COLLECTION" in context
    assert "College: College of Computer Studies" in context
    assert "- BS Computer Science" in context
    assert "- BS Information Technology" in context
    assert "College: College of Engineering" in context
    assert "- BS Civil Engineering" in context
    assert "- BS Mechanical Engineering" in context
    assert "College: College of Agriculture" in context
    assert "- BS Agriculture" in context
    assert "\n- Engineering\n" not in context
    assert context.count("- BS Civil Engineering") == 1
    assert result.detected_intent == PROGRAM_COLLECTION
    assert result.collection_mode is True


def test_program_collection_context_can_be_scoped_to_ccs():
    result, _, mock_generate = run_question("What programs does CCS offer?", broad_chunks())

    context = mock_generate.call_args.kwargs["context"]
    assert "College: College of Computer Studies" in context
    assert "- BS Computer Science" in context
    assert "College: College of Engineering" not in context
    assert "College: College of Agriculture" not in context


def campus_program_chunks() -> list[RetrievedChunk]:
    return [
        chunk(
            "College of Engineering - Sta Cruz Programs",
            "Programs: BS Civil Engineering, BS Mechanical Engineering. Campuses: Sta. Cruz",
            score=0.9,
            page=20,
            path=("Curricular Offerings", "College of Engineering", "Sta Cruz Programs"),
            reasons=["test_match"],
        ),
        chunk(
            "College of Computer Studies - All Campus Programs",
            "Programs: BS Computer Science, BS Information Technology. Campuses: All Campuses",
            score=0.88,
            page=21,
            path=("Curricular Offerings", "College of Computer Studies", "All Campus Programs"),
            reasons=["test_match"],
        ),
        chunk(
            "College of Agriculture - Siniloan Programs",
            "Programs: BS Agriculture, BS Food Technology. Campuses: Siniloan",
            score=0.86,
            page=22,
            path=("Curricular Offerings", "College of Agriculture", "Siniloan Programs"),
            reasons=["test_match"],
        ),
        chunk(
            "College of Business - San Pablo Programs",
            "Programs: BS Accountancy, BS Business Administration. Campuses: San Pablo City",
            score=0.84,
            page=23,
            path=("Curricular Offerings", "College of Business Management and Accountancy", "San Pablo Programs"),
            reasons=["test_match"],
        ),
        chunk(
            "College of Teacher Education - Missing Campus",
            "Programs: Bachelor of Elementary Education",
            score=0.82,
            page=24,
            path=("Curricular Offerings", "College of Teacher Education", "Missing Campus"),
            reasons=["test_match"],
        ),
    ]


def test_program_collection_scopes_to_college_of_engineering():
    result, _, mock_generate = run_question(
        "What programs does the College of Engineering offer?",
        campus_program_chunks(),
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "College: College of Engineering" in context
    assert "- BS Civil Engineering" in context
    assert "- BS Mechanical Engineering" in context
    assert "College: College of Computer Studies" not in context
    assert "College: College of Agriculture" not in context
    assert result.program_scope["detected_college_scope"] == "college of engineering"
    assert result.program_scope["scope_filter_applied"] is True


def test_program_collection_scopes_to_sta_cruz_and_all_campuses():
    result, _, mock_generate = run_question(
        "What programs are offered in Sta. Cruz?",
        campus_program_chunks(),
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "College: College of Engineering" in context
    assert "- BS Civil Engineering" in context
    assert "College: College of Computer Studies" in context
    assert "- BS Computer Science" in context
    assert "College: College of Agriculture" not in context
    assert "College of Business Management and Accountancy" not in context
    assert "Bachelor of Elementary Education" not in context
    assert result.program_scope["detected_campus_scope"] == "sta. cruz"
    assert result.program_scope["chunks_before_scope_filter"] == 5
    assert result.program_scope["chunks_after_scope_filter"] == 2
    assert result.program_scope["excluded_scope_reasons"]


def test_program_collection_scopes_to_siniloan_and_all_campuses():
    result, _, mock_generate = run_question(
        "What programs are offered in Siniloan?",
        campus_program_chunks(),
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "College: College of Agriculture" in context
    assert "- BS Agriculture" in context
    assert "College: College of Computer Studies" in context
    assert "- BS Information Technology" in context
    assert "College: College of Engineering" not in context
    assert "San Pablo" not in context
    assert result.program_scope["detected_campus_scope"] == "siniloan"
    assert result.program_scope["chunks_after_scope_filter"] == 2


def test_specific_program_questions_use_normal_qa_retrieval():
    result, store, mock_generate = run_question(
        "What is BSCS?",
        [
            chunk(
                "College of Computer Studies > BSCS",
                "BSCS means Bachelor of Science in Computer Science.",
                score=0.9,
                path=("Curricular Offerings", "College of Computer Studies", "BSCS"),
                reasons=["test_match"],
            )
        ],
    )

    assert store.calls[0]["top_k"] == FINAL_CONTEXT_CHUNKS
    assert store.calls[0]["raw_k"] == RAW_RETRIEVAL_CANDIDATES
    assert mock_generate.call_args.kwargs.get("broad_mode") is False
    assert result.collection_mode is False


def test_broad_colleges_question_selects_more_than_one_college():
    result, _, mock_generate = run_question("What colleges are available?", broad_chunks())

    context = mock_generate.call_args.kwargs["context"]
    assert "College of Computer Studies" in context
    assert "College of Engineering" in context
    assert "College of Agriculture" in context
    assert result.broad_query is True


def test_broad_services_question_prioritizes_student_service_sources():
    result, store, mock_generate = run_question(
        "What services does OSAS provide?",
        [
            chunk(
                "OSAS Services",
                "OSAS provides student welfare services, guidance referrals, and student activity support.",
                score=0.91,
                path=("Student Services", "Office of Student Affairs and Services", "OSAS Services"),
                reasons=["test_match"],
            ),
            chunk(
                "Guidance Services",
                "Guidance services include counseling and student support referrals.",
                score=0.86,
                path=("Student Services", "Guidance Office", "Guidance Services"),
                reasons=["test_match"],
            ),
            chunk(
                "Registrar Services",
                "The registrar maintains student records and registration documents.",
                score=0.81,
                path=("Student Services", "Registrar", "Registrar Services"),
                reasons=["test_match"],
            ),
            chunk(
                "Major Offenses",
                "Major offenses and disciplinary sanctions are handled by the discipline board.",
                score=0.78,
                path=("Student Discipline", "Major Offenses", "Major Offenses"),
                reasons=["penalty_disciplinary_offense_out_of_domain"],
            ),
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    assert store.calls == []
    assert "OSAS provides student welfare services" in context
    assert "Guidance services include counseling" in context
    assert "registrar maintains student records" in context
    assert "disciplinary sanctions" not in context
    assert result.broad_query is True
    assert result.confidence == "high"


def test_broad_scholarships_question_prioritizes_scholarship_sources():
    result, _, mock_generate = run_question(
        "What scholarships are available?",
        [
            chunk(
                "Scholarship Grants",
                "Scholarship grants are available to qualified students who meet grade and documentary requirements.",
                score=0.91,
                path=("Student Services", "Scholarship", "Scholarship Grants"),
                reasons=["test_match"],
            ),
            chunk(
                "Financial Assistance",
                "Financial assistance and grants may be coordinated through OSAS.",
                score=0.86,
                path=("Student Services", "Scholarship", "Financial Assistance"),
                reasons=["test_match"],
            ),
            chunk(
                "Academic Awards",
                "Awards and honors are granted to students with excellent grades.",
                score=0.83,
                path=("Student Awards", "Awards", "Academic Awards"),
                reasons=["penalty_awards_out_of_domain"],
            ),
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "Scholarship grants are available" in context
    assert "Financial assistance and grants" in context
    assert "Awards and honors" not in context
    assert result.broad_query is True
    assert result.confidence in {"high", "medium"}


def test_broad_offices_question_selects_multiple_office_sources():
    result, _, mock_generate = run_question(
        "What offices are in the handbook?",
        [
            chunk(
                "Registrar Office",
                "The Registrar Office maintains academic records.",
                score=0.9,
                path=("Student Services", "Registrar", "Registrar Office"),
                reasons=["test_match"],
            ),
            chunk(
                "Guidance Office",
                "The Guidance Office provides counseling services.",
                score=0.86,
                path=("Student Services", "Guidance Office", "Guidance Office"),
                reasons=["test_match"],
            ),
            chunk(
                "OSAS",
                "The Office of Student Affairs and Services supports student welfare.",
                score=0.84,
                path=("Student Services", "OSAS", "OSAS"),
                reasons=["test_match"],
            ),
        ],
    )

    context = mock_generate.call_args.kwargs["context"]
    assert "Registrar Office maintains academic records" in context
    assert "Guidance Office provides counseling services" in context
    assert "Office of Student Affairs and Services" in context
    assert result.broad_query is True


@pytest.mark.parametrize(
    "question",
    [
        "What programs are offered by the university?",
        "List all programs.",
        "What colleges are available?",
        "What services does OSAS provide?",
        "What scholarships are available?",
        "What offices are in the handbook?",
        "What requirements are needed for graduation?",
    ],
)
def test_broad_query_detection_positive_cases(question: str):
    broad, reason = detect_broad_query(question)

    assert broad is True
    assert reason


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("What programs are offered?", "PROGRAM_COLLECTION"),
        ("What scholarships are available?", "SCHOLARSHIP_COLLECTION"),
        ("What offices are there?", "OFFICE_COLLECTION"),
        ("What services does OSAS provide?", "SERVICE_COLLECTION"),
        ("What requirements are needed for graduation?", "REQUIREMENT_COLLECTION"),
    ],
)
def test_collection_intent_detection(question: str, intent: str):
    assert detect_collection_intent(question) == intent


@pytest.mark.parametrize(
    "question",
    [
        "What is scholastic delinquency?",
        "Where can I get an excuse slip?",
        "Who is the University President?",
        "What happens if I fail 75% of my units?",
    ],
)
def test_specific_queries_do_not_trigger_broad_mode(question: str):
    result, store, mock_generate = run_question(
        question,
        [
            chunk(
                "Scholastic Delinquency",
                "Warning, probation, and dismissal may apply for failed academic units.",
                score=0.9,
                path=("Undergraduate Academic Policies", "Retention Policies", "Scholastic Delinquency"),
                reasons=["academic_policy_match", "test_match"],
            )
        ],
    )

    assert store.calls[0]["top_k"] == FINAL_CONTEXT_CHUNKS
    assert store.calls[0]["raw_k"] == RAW_RETRIEVAL_CANDIDATES
    assert mock_generate.call_args.kwargs.get("broad_mode") is False
    assert result.broad_query is False


def test_qa_groq_failure_returns_graceful_response_with_debug_chunks():
    store = FakeStore([chunk("Attendance Policy", "Submit an excuse slip for absence due to illness.")])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
    ):
        result = answer_qa_question("I was absent due to illness. What should I do?")

    assert result.confidence == "medium"
    assert result.fallback_used is True
    assert result.fallback_reason == "timeout"
    assert "AI answer service is temporarily busy" not in result.answer
    assert "Groq answer generation timed out" not in result.answer
    assert "excuse slip" in result.answer.lower() or "illness" in result.answer.lower()
    assert result.sources
    assert result.retrieved_chunks[0]["boost_reasons"] == ["test_match"]


@pytest.mark.parametrize(
    ("question", "title", "body_needle"),
    [
        (
            "excuse slip",
            "How do I get an excuse slip if I missed class because I was sick",
            "medical certificate",
        ),
        (
            "good moral",
            "Certificate of Good Moral Character",
            "Guidance Office",
        ),
        (
            "student id",
            "Student ID Validation",
            "Certificate of Registration",
        ),
    ],
)
def test_short_topic_query_answers_matching_faq_instead_of_clarifying(
    question: str, title: str, body_needle: str
):
    """Bare topic phrases should use the title-matched FAQ, not 'which part do you need?'."""
    store = FakeStore(
        [
            chunk(
                title,
                f"{body_needle}: follow the campus procedure described in this article.",
                score=0.88,
                reasons=["boost_exact_service_title:topic", "attendance_policy_match"],
            )
        ]
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
    ):
        result = answer_qa_question(question)

    assert "I can help with related topics" not in result.answer
    assert "which part do you need" not in result.answer.casefold()
    assert body_needle.casefold() in result.answer.casefold()


def test_short_topic_query_still_clarifies_when_titles_do_not_match():
    store = FakeStore(
        [
            chunk(
                "Certificate of Good Moral Character",
                "Request good moral from Guidance.",
                score=0.7,
                reasons=["semantic_similarity"],
            )
        ]
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
    ):
        result = answer_qa_question("excuse slip")

    # No title match for excuse slip → keep clarification / weak-evidence behavior.
    assert (
        "I can help with related topics" in result.answer
        or "more specific question" in result.answer.casefold()
        or "good moral" in result.answer.casefold()
    )


@pytest.mark.parametrize(
    ("error_message", "fallback_reason"),
    [
        ("Groq answer generation failed: 429 rate_limit_exceeded", "rate_limited"),
        ("Groq answer generation timed out.", "timeout"),
        ("Groq API key is not configured.", "service_unavailable"),
    ],
)
def test_groq_recoverable_errors_use_extractive_fallback(error_message: str, fallback_reason: str):
    store = FakeStore(
        [
            chunk(
                "Excuse Slip",
                "Students who were absent due to illness should secure an excuse slip with supporting documents.",
                score=0.9,
                path=("Academic Policies", "Attendance", "Excuse Slip"),
                reasons=["attendance_policy_match", "boost_path_domain_match:attendance"],
            )
        ]
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", side_effect=GroqAnswerError(error_message)),
    ):
        result = answer_qa_question("Where can I get an excuse slip?")

    assert result.fallback_used is True
    assert result.fallback_reason == fallback_reason
    assert "AI answer service is temporarily busy" not in result.answer
    assert "rate_limit_exceeded" not in result.answer
    assert "Groq" not in result.answer
    assert "secure an excuse slip" in result.answer or "Excuse Slip" in result.answer
    assert result.sources[0]["title"] == "Excuse Slip"


def test_groq_fallback_without_relevant_chunks_returns_handbook_missing_message():
    store = FakeStore([])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", side_effect=GroqAnswerError("429 rate_limit_exceeded")),
    ):
        result = answer_qa_question("Where can I get an excuse slip?")

    assert result.fallback_used is False
    assert result.answer == OUT_OF_SCOPE_ANSWER


def test_out_of_scope_presidential_question_returns_low_confidence():
    store = FakeStore(
        [
            chunk(
                "Administrative Officials",
                "DR. MARIO R. BRIONES University President",
                score=0.9,
                path=("Student Handbook", "University Officials", "Administrative Officials"),
                reasons=["semantic_similarity"],
            )
        ]
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        assert question == "Who is the president of the Philippines?"
        return (
            "The retrieved context does not contain information about the president of the Philippines. "
            "I can only answer based on the indexed ASKa-Piyu university documents."
        )

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", side_effect=generate_from_context),
    ):
        result = answer_qa_question("Who is the president of the Philippines?")

    assert result.confidence == "low"
    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert result.sources == []
    assert result.out_of_scope_detected is True
    assert "administrative_officials_president" not in result.matched_expansion_rules


@pytest.mark.parametrize(
    ("question", "model_answer"),
    [
        (
            "Who is the President of the Philippines?",
            (
                "The retrieved context does not contain information about the President of the Philippines. "
                "It lists university Administrative Officials and the Supreme Student Council."
            ),
        ),
        (
            "President Marcos",
            (
                "President Marcos is not mentioned in the retrieved context. "
                "The available section is Administrative Officials."
            ),
        ),
        (
            "Capital of Japan",
            (
                "There is no direct information about the capital of Japan. "
                "The retrieved chunks discuss SSC officers."
            ),
        ),
        (
            "Weather today",
            (
                "This question is outside the scope of the handbook and there is insufficient information. "
                "The context is about Administrative Officials."
            ),
        ),
    ],
)
def test_out_of_scope_answers_do_not_summarize_unrelated_retrieved_chunks(question: str, model_answer: str):
    store = FakeStore(
        [
            chunk(
                "Administrative Officials",
                "DR. MARIO R. BRIONES University President",
                score=0.9,
                path=("Student Handbook", "University Officials", "Administrative Officials"),
                reasons=["semantic_similarity"],
            ),
            chunk(
                "Supreme Student Council",
                "The Supreme Student Council is the highest student governing body.",
                score=0.84,
                path=("Student Handbook", "Student Organizations", "Supreme Student Council"),
                reasons=["semantic_similarity"],
            ),
        ]
    )

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", return_value=model_answer),
    ):
        result = answer_qa_question(question)

    assert result.confidence == "low"
    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert "Administrative Officials" not in result.answer
    assert "Supreme Student Council" not in result.answer
    assert "SSC" not in result.answer
    assert result.sources == []
    assert result.out_of_scope_detected is True


def test_out_of_scope_presidential_question_low_confidence_for_missing_info_answer():
    retrieved = [chunk("Administrative Officials", "DR. MARIO R. BRIONES University President", score=0.91)]

    confidence = _confidence_for(
        retrieved,
        retrieved,
        "The indexed documents do not have enough information to answer President Marcos.",
        "President Marcos",
    )

    assert confidence == "low"


def test_qa_context_format_includes_title_path_page_and_content():
    context = format_retrieved_context(
        [
            chunk(
                "Attendance Policy",
                "Students must submit an excuse slip.",
                page=46,
                path=("Undergraduate Academic Policies", "Attendance", "Attendance Policy"),
            )
        ]
    )

    assert "Title: Attendance Policy" in context
    assert "Path: Undergraduate Academic Policies > Attendance > Attendance Policy" in context
    assert "Page: 46" in context
    assert "Content:\nStudents must submit an excuse slip." in context


def test_factual_charter_fee_question_uses_groq_not_typed_dump():
    """Fees / who-may-avail style FAQs must reach Groq instead of step templates."""
    from app.services.qa.question_answering import NORMAL_QA, detect_collection_intent
    from app.services.qa.service_answer_formatter import is_service_howto_query

    enrollment = RetrievedChunk(
        document_id="charter-enrollment",
        title="Enrollment",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=0,
        text=(
            "Office / Division\nOffice of the Registrar\n\n"
            "Who May Avail\nAll eligible clients/students\n\n"
            "Requirements\n"
            "- Enrollment slip\n"
            "- Original good moral certificate\n\n"
            "Fees\nNone\n\n"
            "Total Processing Time\n20 minutes\n"
        ),
        relevance_score=0.94,
        original_score=0.9,
        reranked_score=0.94,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": "Enrollment",
            "office": "Office of the Registrar",
            "who_may_avail": "All eligible clients/students",
            "total_processing_time": "20 minutes",
            "page_number": 12,
            "audience": "both",
        },
    )

    assert is_service_howto_query("How long is the total enrollment processing time?") is False
    assert detect_collection_intent("Which office is responsible for the enrollment process?") == NORMAL_QA
    assert (
        detect_collection_intent("What are the enrollment requirements for a new college student?")
        == NORMAL_QA
    )

    result, _, mock_generate = run_question(
        "How long is the total enrollment processing time stated in the Citizen’s Charter?",
        [enrollment],
    )

    assert mock_generate.call_count == 1
    context = mock_generate.call_args.kwargs["context"]
    assert "20 minutes" in context
    assert "Office: Office of the Registrar" in context or "Office of the Registrar" in context
    assert "To complete Enrollment, follow the steps below." not in result.answer


def test_which_office_question_is_not_office_collection():
    from app.services.qa.question_answering import NORMAL_QA, detect_collection_intent

    assert detect_collection_intent("Which office is responsible for the enrollment process?") == NORMAL_QA
    assert detect_collection_intent("What offices are there?") == "OFFICE_COLLECTION"


def test_faculty_policy_questions_use_normal_qa_not_policy_collection():
    from app.services.qa.question_answering import NORMAL_QA, POLICY_COLLECTION, detect_collection_intent

    assert detect_collection_intent("What are the faculty grading policies?") == NORMAL_QA
    assert detect_collection_intent("What are the responsibilities of faculty members?") == NORMAL_QA
    assert detect_collection_intent("What are the student policies?") == POLICY_COLLECTION


def test_who_may_avail_enrollment_recovers_from_charter_metadata():
    from app.services.qa.groq_answer_service import GroqAnswerError

    enrollment = RetrievedChunk(
        document_id="enroll",
        title="Enrollment",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=0,
        text=(
            "Office / Division\nOffice of the Registrar\n\n"
            "Who May Avail\nAll eligible clients/students\n\n"
            "Requirements\n- Enrollment slip\n"
        ),
        relevance_score=0.91,
        original_score=0.85,
        reranked_score=0.91,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": "Enrollment",
            "source_section": "Enrollment",
            "office": "Office of the Registrar",
            "who_may_avail": "All eligible clients/students",
            "page_number": 12,
            "audience": "both",
        },
    )
    store = FakeStore([enrollment])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
    ):
        result = answer_qa_question("Who may avail of the enrollment")

    assert "do not contain enough information" not in result.answer.lower()
    assert "All eligible clients/students" in result.answer
    assert "Enrollment" in result.answer
    assert result.confidence in {"medium", "high"}


def test_old_student_enrollment_documents_recovers_requirements():
    from app.services.qa.groq_answer_service import GroqAnswerError

    visitation = RetrievedChunk(
        document_id="handbook",
        title="Registrar Visitation",
        source_filename="LSPU Student Handbook.pdf",
        chunk_index=0,
        text="8.1.3 Registrar Visitation procedures for campus visits.",
        relevance_score=0.93,
        original_score=0.9,
        reranked_score=0.93,
        metadata={
            "section": "8.1.3 > Registrar Visitation",
            "title": "Registrar Visitation",
            "office": "Registrar",
            "page_number": 37,
            "audience": "both",
        },
    )
    enrollment = RetrievedChunk(
        document_id="enroll",
        title="Enrollment",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=1,
        text=(
            "Office / Division\nOffice of the Registrar\n\n"
            "Requirements\n"
            "- For new college students: Enrollment slip, good moral certificate\n"
            "- For old students: Clearance, student ID, and evaluation of grades\n"
            "- For transferees: TOR and Certificate of Transfer\n"
        ),
        relevance_score=0.8,
        original_score=0.75,
        reranked_score=0.8,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": "Enrollment",
            "source_section": "Enrollment",
            "office": "Office of the Registrar",
            "extracted_requirements": (
                '["Enrollment slip", "Clearance", "student ID", "evaluation of grades"]'
            ),
            "page_number": 10,
            "audience": "both",
        },
    )
    store = FakeStore([visitation, enrollment])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
    ):
        result = answer_qa_question(
            "What documents are required from old students during enrollment?"
        )

    assert "responsible office" not in result.answer.lower()
    assert "Registrar Visitation" not in result.answer
    assert "Clearance" in result.answer or "student ID" in result.answer
    assert "Enrollment" in result.answer


def test_tor_fee_and_office_prefers_charter_fees_over_handbook_office():
    annual_report = RetrievedChunk(
        document_id="annual-report",
        title="LSPU Student Handbook",
        source_filename="handbook.pdf",
        chunk_index=0,
        text="1.2.3.1 Annual report per school year on the implementation. Office: Registrar",
        relevance_score=0.95,
        original_score=0.9,
        reranked_score=0.95,
        metadata={
            "document_type": "student_handbook",
            "source_section": "1.2.3.1 > Annual report per school year on the implementation",
            "office": "Registrar",
            "page_number": 127,
            "audience": "both",
        },
    )
    tor = RetrievedChunk(
        document_id="tor-service",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=1,
        text=(
            "Issuance of Transcript of Records (TOR)\n"
            "Office / Division\nOffice of the Registrar\n"
            "Fees\nUndergraduate: P75.00/page; Graduate: P150/page\n"
        ),
        relevance_score=0.7,
        original_score=0.65,
        reranked_score=0.7,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Issuance of Transcript of Records (TOR)",
            "office": "Office of the Registrar",
            "total_fees": "Undergraduate: P75.00/page; Graduate: P150/page",
            "page_number": 40,
            "audience": "both",
        },
    )
    store = FakeStore([annual_report, tor])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value=(
                "The office responsible for 1.2.3.1 > Annual report per school year "
                "on the implementation is Registrar, according to the LSPU Student Handbook."
            ),
        ),
    ):
        result = answer_qa_question(
            "How much is TOR [Transcript of Records] per page for undergrad vs graduate, and which office?"
        )

    answer = result.answer.lower()
    assert "p75" in answer or "75" in answer
    assert "p150" in answer or "150" in answer
    assert "registrar" in answer
    assert "annual report" not in answer


def test_diploma_second_copy_fee_ignores_exam_chunks():
    exam = RetrievedChunk(
        document_id="exam",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=0,
        text="Open to all Clients. Regular comprehensive examination schedule.",
        relevance_score=0.92,
        original_score=0.9,
        reranked_score=0.92,
        metadata={
            "document_type": "citizen_charter",
            "source_section": "Open to all Clients",
            "page_number": 82,
            "audience": "both",
        },
    )
    diploma = RetrievedChunk(
        document_id="diploma",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=1,
        text="Issuance of Diploma\nFees\nSecond copy of diploma: P100.00",
        relevance_score=0.6,
        original_score=0.55,
        reranked_score=0.6,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Issuance of Diploma",
            "office": "Office of the Registrar",
            "total_fees": "Second copy of diploma: P100.00",
            "page_number": 45,
            "audience": "both",
        },
    )
    store = FakeStore([exam, diploma])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value=(
                "For Regular comprehensive examination, examinees must follow the posted schedule."
            ),
        ),
    ):
        result = answer_qa_question(
            "What is the fee for a second copy of a diploma according to the Citizen's Charter?"
        )

    answer = result.answer.lower()
    assert "100" in answer or "p100" in answer
    assert "diploma" in answer
    assert "comprehensive examination" not in answer


def test_diploma_fee_ignores_assessment_of_fees_card():
    assessment = RetrievedChunk(
        document_id="assessment",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=0,
        text="Assessment of Fees\nFees\nP10931",
        relevance_score=0.95,
        original_score=0.9,
        reranked_score=0.95,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Assessment of Fees",
            "office": "Office of the Registrar",
            "total_fees": "P10931",
            "page_number": 18,
            "audience": "both",
        },
    )
    tor_with_diploma_fee = RetrievedChunk(
        document_id="tor",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=1,
        text=(
            "Issuance of Transcript of Records (TOR)\n"
            "Fees\nUndergraduate: P75.00/page; Graduate: P150/page; "
            "Second copy of diploma: P100.00"
        ),
        relevance_score=0.55,
        original_score=0.5,
        reranked_score=0.55,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Issuance of Transcript of Records (TOR)",
            "office": "Office of the Registrar",
            "total_fees": (
                "Undergraduate: P75.00/page; Graduate: P150/page; "
                "Second copy of diploma: P100.00"
            ),
            "page_number": 40,
            "audience": "both",
        },
    )
    store = FakeStore([assessment, tor_with_diploma_fee])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value="The listed fee for Assessment of Fees is P10931 (Citizen Charter).",
        ),
    ):
        result = answer_qa_question(
            "What is the fee for a second copy of a diploma according to the Citizen's Charter?"
        )

    answer = result.answer.lower()
    assert "100" in answer or "p100" in answer
    assert "assessment of fees" not in answer
    assert "10931" not in answer


def test_diploma_fee_recovery_beats_wrong_groq_answer():
    tor = RetrievedChunk(
        document_id="tor",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=0,
        text="Issuance of Transcript of Records\nFees\nSecond copy of diploma: P100.00",
        relevance_score=0.9,
        original_score=0.85,
        reranked_score=0.9,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Issuance of Transcript of Records/Transfer Credentials",
            "office": "Office of the Registrar",
            "total_fees": (
                "Undergraduate: P75.00/page; Graduate: P150/page; "
                "Second copy of diploma: P100.00"
            ),
            "page_number": 40,
            "audience": "both",
        },
    )
    ctc = RetrievedChunk(
        document_id="ctc",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=1,
        text="Issuance of Certified True Copy\nFees\nNone",
        relevance_score=0.88,
        original_score=0.8,
        reranked_score=0.88,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Issuance of Certified True Copy",
            "total_fees": "None",
            "page_number": 74,
            "audience": "both",
        },
    )
    store = FakeStore([ctc, tor])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value=(
                "To complete Issuance of Certified True Copy, follow the steps below.\n"
                "Fees: None\nPage: 74"
            ),
        ),
    ):
        result = answer_qa_question(
            "What is the fee for a second copy of a diploma according to the Citizen's Charter?"
        )

    answer = result.answer.lower()
    assert "100" in answer or "p100" in answer
    assert "certified true copy" not in answer
    assert "fees: none" not in answer


# --- Phase 5: the structured fee/office recovery override must not fire when
# the LLM answer is already correct, just phrased differently (stylistic
# difference), only when it is genuinely missing/wrong. ---


def test_prefer_structured_fee_recovery_does_not_override_correct_differently_worded_answer():
    from app.services.qa.question_answering import _prefer_structured_fee_recovery

    recovered = "The listed fee for the second copy of a diploma is P100.00 (Citizen's Charter)."
    correct_llm_answer = (
        "Getting a second copy of your diploma costs P100.00, based on the Citizen's Charter."
    )

    assert _prefer_structured_fee_recovery(
        "What is the fee for a second copy of a diploma?",
        recovered,
        correct_llm_answer,
    ) is False


def test_prefer_structured_fee_recovery_does_not_override_correct_answer_with_decimal_amount():
    """A correct answer written with a decimal amount but no literal 'P' prefix
    (e.g. copy-pasted from a table) must still be recognized as already correct."""
    from app.services.qa.question_answering import _prefer_structured_fee_recovery

    recovered = "The listed fee for the second copy of a diploma is P100.00 (Citizen's Charter)."
    correct_llm_answer = "The fee for a second copy of your diploma is 100.00 pesos."

    assert _prefer_structured_fee_recovery(
        "What is the fee for a second copy of a diploma?",
        recovered,
        correct_llm_answer,
    ) is False


def test_prefer_structured_fee_recovery_does_not_override_bare_integer_amount_with_no_currency_symbol():
    """Correct answer stated as a bare number (no decimal, no "P" prefix) is
    still a real amount, not missing information -- must not be overridden."""
    from app.services.qa.question_answering import _prefer_structured_fee_recovery

    recovered = "The listed fee for the second copy of a diploma is P100.00 (Citizen's Charter)."
    correct_llm_answer = "The fee for a second copy of your diploma is 100 pesos."

    assert _prefer_structured_fee_recovery(
        "What is the fee for a second copy of a diploma?",
        recovered,
        correct_llm_answer,
    ) is False


def test_prefer_structured_fee_recovery_fires_when_llm_answer_has_no_amount_at_all():
    """Genuinely missing information (no amount anywhere in the LLM answer) must
    still trigger the recovery, distinguishing "wrong/missing" from "stylistic"."""
    from app.services.qa.question_answering import _prefer_structured_fee_recovery

    recovered = "The listed fee for the second copy of a diploma is P100.00 (Citizen's Charter)."
    vague_llm_answer = "Please proceed to the Registrar's office to request a second copy of your diploma."

    assert _prefer_structured_fee_recovery(
        "What is the fee for a second copy of a diploma?",
        recovered,
        vague_llm_answer,
    ) is True


def test_prefer_structured_fee_recovery_fires_when_llm_names_wrong_service():
    from app.services.qa.question_answering import _prefer_structured_fee_recovery

    recovered = "The listed fee for the second copy of a diploma is P100.00 (Citizen's Charter)."
    wrong_service_answer = "The listed fee for Assessment of Fees is P10931 (Citizen Charter)."

    assert _prefer_structured_fee_recovery(
        "What is the fee for a second copy of a diploma?",
        recovered,
        wrong_service_answer,
    ) is True


def test_should_prefer_recovered_factual_does_not_override_complete_office_answer():
    """A fully-formed office answer that also names required documents/fees is
    not an "office-only dump" and must not be treated as needing recovery."""
    from app.services.qa.question_answering import _should_prefer_recovered_factual

    complete_answer = (
        "The Office of the Registrar handles diploma requests. The required documents are "
        "your clearance and a valid ID, and the listed fee is P100.00."
    )

    assert _should_prefer_recovered_factual(
        "What documents are required and which office handles diploma requests?",
        complete_answer,
    ) is False


def test_should_prefer_recovered_factual_overrides_bare_office_only_dump():
    from app.services.qa.question_answering import _should_prefer_recovered_factual

    office_only_answer = "The responsible office is the Office of the Registrar."

    assert _should_prefer_recovered_factual(
        "What documents are required and which office handles diploma requests?",
        office_only_answer,
    ) is True


def test_diploma_fee_recovery_does_not_override_correct_groq_answer_with_different_phrasing():
    """End-to-end: when Groq already answers correctly (right amount, right
    service) in its own words, the structured recovery override must not
    clobber it with the templated sentence."""
    tor = RetrievedChunk(
        document_id="tor",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=0,
        text="Issuance of Transcript of Records\nFees\nSecond copy of diploma: P100.00",
        relevance_score=0.9,
        original_score=0.85,
        reranked_score=0.9,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Issuance of Transcript of Records/Transfer Credentials",
            "office": "Office of the Registrar",
            "total_fees": (
                "Undergraduate: P75.00/page; Graduate: P150/page; "
                "Second copy of diploma: P100.00"
            ),
            "page_number": 40,
            "audience": "both",
        },
    )
    store = FakeStore([tor])
    correct_llm_answer = (
        "Getting a second copy of your diploma will cost P100.00, per the Citizen's Charter."
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value=correct_llm_answer,
        ),
    ):
        result = answer_qa_question(
            "What is the fee for a second copy of a diploma according to the Citizen's Charter?"
        )

    assert result.answer.strip() == correct_llm_answer


@pytest.mark.parametrize(
    "question",
    ("hi", "Hi!", "hello", "hey", "good morning", "thanks", "thank you", "how are you"),
)
def test_greeting_query_detection(question: str):
    assert is_greeting_query(question)


@pytest.mark.parametrize(
    "question",
    (
        "hi how do i enroll",
        "what is the haircut policy",
        "hello where is the registrar",
    ),
)
def test_real_questions_are_not_greetings(question: str):
    assert not is_greeting_query(question)


def test_greeting_skips_retrieval_and_sources():
    store = type("Store", (), {"chunk_count": 99, "search": lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not search"))})()
    with patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store):
        result = answer_qa_question("hi")
    assert result.detected_intent == GREETING_QUESTION
    assert result.answer == GREETING_ANSWER
    assert result.sources == []
    assert result.retrieved_chunks == []
    assert result.confidence == "high"


def test_fee_recovery_does_not_borrow_unrelated_library_fee_for_good_moral_cost():
    """BUG-001: cost follow-ups must not answer with an unrelated fee card."""
    from app.services.chroma_store import RetrievedChunk
    from app.services.qa.question_answering import _recover_factual_charter_answer

    library = RetrievedChunk(
        document_id="doc-1",
        title="Library Reference Assistance",
        source_filename="charter.pdf",
        chunk_index=0,
        text="Fees: None\nOffice / Division: Library",
        relevance_score=0.99,
        metadata={
            "source_section": "Library Reference Assistance",
            "total_fees": "None",
            "office": "Library",
            "document_type": "citizen_charter_service",
        },
    )
    good_moral = RetrievedChunk(
        document_id="doc-1",
        title="Issuance of Good Moral Certificate (Undergraduate)",
        source_filename="charter.pdf",
        chunk_index=1,
        text="Issuance of Good Moral Certificate. Fees are not listed in this section.",
        relevance_score=0.55,
        metadata={
            "source_section": "Issuance of Good Moral Certificate (Undergraduate)",
            "office": "Office of the Student Affairs and Services",
            "document_type": "citizen_charter_service",
        },
    )
    question = (
        "How much does it cost? regarding How do I get a Good Moral Certificate?"
    )
    recovered = _recover_factual_charter_answer(
        question,
        [library, good_moral],
        sources=[{"title": "Citizen Charter", "path": "charter.pdf"}],
    )
    assert recovered is None


def test_prefer_structured_fee_recovery_does_not_override_missing_fee_with_unrelated_service():
    from app.services.qa.question_answering import _prefer_structured_fee_recovery

    recovered = "The listed fee for Library Reference Assistance is None (Citizen Charter)."
    llm = (
        "The available Good Moral Certificate sources do not specify the cost "
        "or listed fee for this service."
    )
    assert (
        _prefer_structured_fee_recovery(
            "How much does it cost? regarding How do I get a Good Moral Certificate?",
            recovered,
            llm,
        )
        is False
    )


def test_should_prefer_recovered_factual_does_not_force_override_when_sources_lack_fee():
    from app.services.qa.question_answering import _should_prefer_recovered_factual

    llm = (
        "Based on the retrieved Good Moral Certificate materials, the sources "
        "do not specify the cost for this service."
    )
    assert (
        _should_prefer_recovered_factual(
            "How much does it cost? regarding How do I get a Good Moral Certificate?",
            llm,
        )
        is False
    )


def test_fee_recovery_does_not_borrow_tor_fees_via_certificate_substring():
    """Whole-token overlap only — 'certificate' must not match 'Certifications'."""
    from app.services.chroma_store import RetrievedChunk
    from app.services.qa.question_answering import _recover_factual_charter_answer

    tor = RetrievedChunk(
        document_id="doc-1",
        title="Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV",
        source_filename="charter.pdf",
        chunk_index=0,
        text="Fees Undergraduate: P75.00/page",
        relevance_score=0.99,
        metadata={
            "source_section": (
                "Issuance of Transcript of Records/Transfer Credentials/"
                "Certifications/CAV/Authenticated Documents"
            ),
            "total_fees": "Undergraduate: P75.00/page; Second copy of diploma: P100.00",
            "document_type": "citizen_charter_service",
        },
    )
    good_moral = RetrievedChunk(
        document_id="doc-1",
        title="Issuance of Good Moral Certificate (Undergraduate)",
        source_filename="charter.pdf",
        chunk_index=1,
        text="Issuance of Good Moral Certificate. No fee listed.",
        relevance_score=0.6,
        metadata={
            "source_section": "Issuance of Good Moral Certificate (Undergraduate)",
            "document_type": "citizen_charter_service",
        },
    )
    recovered = _recover_factual_charter_answer(
        "How much does it cost? regarding How do I get a Good Moral Certificate?",
        [tor, good_moral],
        sources=[{"title": "Citizen Charter", "path": "charter.pdf"}],
    )
    assert recovered is None


def test_fee_usable_rejects_none_placeholder_values():
    from app.services.qa.question_answering import _fee_usable_for_question

    assert (
        _fee_usable_for_question(
            "None",
            "Library Reference Assistance",
            "how much does it cost regarding good moral certificate",
        )
        is None
    )
    assert (
        _fee_usable_for_question(
            "N/A",
            "Library Reference Assistance",
            "how much does it cost regarding good moral certificate",
        )
        is None
    )


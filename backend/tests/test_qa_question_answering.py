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
    _CLASSIFICATION_FALLBACK_NOTICE,
    _SUPPORT_ABS_FLOOR,
    _SUPPORT_MIN_SIGNALS,
    _SUPPORT_REL_FLOOR,
    _answer_claims,
    _chunk_merge_key,
    _chunk_search_text,
    _citation_support_score,
    _confidence_for,
    _display_sources_for_answer,
    _grounding_tokens,
    _raw_citation_id,
    _retrieved_debug,
    _detected_query_domain,
    _select_supporting_context,
    _sources_from_chunks,
    answer_qa_question,
    detect_collection_intent,
    detect_broad_query,
    format_retrieved_context,
    is_greeting_query,
    select_context_chunks,
)
from app.services.knowledge_taxonomy import ClassificationResult


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


def _echo_context_answer(*, context: str = "", **_kwargs) -> str:
    """Default mock "LLM" answer: faithfully echoes the retrieved context.

    Tests that only care about *retrieval* (which chunks made it into
    ``selected_context`` / the generation context) use this default so the
    citation-selection step in ``answer_qa_question`` — which narrows
    ``sources`` to whatever the *generated answer* actually supports — finds
    every retrieved chunk supported (the "answer" literally contains each
    chunk's own text), matching this suite's long-standing assumption that
    ``result.sources`` mirrors ``selected_context``. Tests that specifically
    exercise citation *precision* (a generated answer that only covers some
    of the retrieved chunks) pass their own ``generate_from_context``/
    ``side_effect`` instead — see the ``test_citation_*`` tests below.
    """
    return context or "Follow the cited policy in the retrieved context."


def run_question(question: str, chunks: list[RetrievedChunk], *, user_role: str | None = None):
    store = FakeStore(chunks)
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=_echo_context_answer,
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
    # "medium", not "high", since the Phase 2 confidence-gating fix
    # (question_answering._query_taxonomy_labels): the real classify_question()
    # confidence for this generic phrasing is ~0.25-0.31 (embedding-similarity
    # fallback, no strong rule-based keyword match), below LOW_CONFIDENCE_
    # THRESHOLD, so query_domain is now None and _confidence_for's broad-query
    # "high" tier (which needs domain_match_count >= 2) can no longer be
    # reached here -- the correct, retrieved, cited context is unaffected
    # (all source/context assertions above still hold); only the displayed
    # confidence label changed, and arguably more honestly reflects the
    # classifier's genuine uncertainty for this generic wording.
    assert result.confidence == "medium"


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
    # "medium", not "high" -- same Phase 2 dependency as
    # test_broad_program_questions_select_multiple_curricular_sources above:
    # the real classify_question() confidence for "What services does OSAS
    # provide?" is ~0.27 (embedding-similarity fallback), below
    # LOW_CONFIDENCE_THRESHOLD, so query_domain is None and the broad-query
    # "high" tier (domain_match_count >= 3) is unreachable. Context selection
    # itself is unaffected -- all three correct sources are still selected
    # and the disciplinary chunk is still excluded, per the assertions above.
    assert result.confidence == "medium"


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


# ---------------------------------------------------------------------------
# Citation grounding / source precision
#
# ``answer_qa_question`` retrieves broadly (recall) but must display only
# the citations that materially support the *generated answer* — retrieval
# membership alone is not enough. These tests exercise
# ``_select_supporting_context`` / ``_display_sources_for_answer`` end to
# end through ``answer_qa_question``, using several unrelated domains
# (transfer credit, grade correction, latin honors, grading-sheet
# procedure) so the behavior is proven generic, not keyed to any one
# question or document.
# ---------------------------------------------------------------------------


def test_citation_precision_excludes_ambiguous_keyword_distractor():
    """The reported production case: a broad, multi-clause question pulls in
    the correct Student Handbook evidence alongside Citizen's Charter chunks
    that merely share the word "validation" with the question — those must
    not survive as displayed citations even though retrieval surfaced them."""
    validation_requirements = chunk(
        "Validation Requirements",
        "Holders of a degree who transfer or register in this University may be "
        "given credit for equivalent courses taken without validation, provided "
        "that credits earned without validation shall not exceed 50% of the total "
        "credits required for graduation in the curriculum.",
        score=0.9,
        path=("Undergraduate Academic Policies", "Admission", "Validation Requirements"),
        reasons=["academic_policy_match"],
    )
    transferring = chunk(
        "Transferring",
        "A student who wishes to transfer to this University must submit an "
        "honorable dismissal and transcript of records to the Registrar for "
        "evaluation of previous academic units before enrollment.",
        score=0.86,
        path=("Undergraduate Academic Policies", "Admission", "Transferring"),
        reasons=["academic_policy_match"],
    )
    id_validation = chunk(
        "ID Validation",
        "This service covers validation of student identification cards. "
        "Requirements: Certificate of Registration, one recent photo. "
        "Processing time: 15 minutes at the Registrar's window.",
        score=0.83,
        path=("Citizen's Charter", "Student Services", "ID Validation"),
        reasons=["semantic_similarity"],
    )
    tech_precommercialization = chunk(
        "Technology Pre-Commercialization",
        "This service assists inventors in preparing technology for "
        "commercialization, including IP assessment and investor matching "
        "through the Technology Business Incubator.",
        score=0.81,
        path=("Citizen's Charter", "Research Services", "Technology Pre-Commercialization"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return (
            "Holders of a degree who transfer or register in LSPU may receive "
            "credit for equivalent courses without validation, but the credits "
            "cannot exceed 50 percent of the total credits required for "
            "graduation."
        )

    store = FakeStore(
        [validation_requirements, transferring, id_validation, tech_precommercialization]
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "I'm transferring to LSPU with a previous degree. How much of my "
            "previous coursework can be credited without validation?"
        )

    titles = [source["title"] for source in result.sources]
    assert "ID Validation" not in titles
    assert "Technology Pre-Commercialization" not in titles
    assert "Validation Requirements" in titles
    # Strongest supporting source first.
    assert result.sources[0]["title"] == "Validation Requirements"


def test_citation_precision_keeps_multiple_sources_for_a_multi_rule_answer():
    """A different domain (grade correction) with two distinct rules, each
    grounded in a different chunk — both must survive; the fix must not
    collapse a legitimately multi-source answer down to one citation."""
    approval_rule = chunk(
        "Grade Correction Approval",
        "Any correction of grades affecting 30% or more of a class requires "
        "prior written approval from the Dean of the College before the "
        "correction may be presented at an Academic Council meeting for "
        "ratification.",
        score=0.88,
        path=("Faculty Manual", "Grading", "Grade Correction Approval"),
        reasons=["faculty_policy_match"],
    )
    deadline_rule = chunk(
        "Grading Sheet Deadlines",
        "A corrected grading sheet must be submitted to the Registrar within "
        "15 days of the original grade submission deadline, together with "
        "the Dean's approval memorandum.",
        score=0.85,
        path=("Faculty Manual", "Grading", "Grading Sheet Deadlines"),
        reasons=["faculty_policy_match"],
    )
    unrelated_leave_policy = chunk(
        "Faculty Leave Application",
        "Faculty members applying for sabbatical leave must file Form 21-A "
        "with the Human Resources Office at least two months before the "
        "intended leave date.",
        score=0.79,
        path=("Faculty Manual", "Leave", "Faculty Leave Application"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return (
            "A faculty member correcting grades for 30% or more of a class "
            "must first secure written approval from the Dean and then "
            "present the correction at an Academic Council meeting; the "
            "corrected grading sheet must then be submitted to the Registrar "
            "within 15 days of the original submission deadline."
        )

    store = FakeStore([approval_rule, deadline_rule, unrelated_leave_policy])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "A faculty member needs to correct grades for 30% of a class. "
            "Explain the complete approval process, including who must "
            "approve it, whether an Academic Council meeting is required, "
            "and every deadline stated in the policy.",
            user_role="faculty",
        )

    titles = {source["title"] for source in result.sources}
    assert "Grade Correction Approval" in titles
    assert "Grading Sheet Deadlines" in titles
    assert "Faculty Leave Application" not in titles


def test_citation_precision_excludes_distractor_sharing_important_keywords():
    """A retrieved chunk shares substantial vocabulary with the question
    ("general weighted average") but documents a different procedure
    (academic probation, not Latin honors) — it must not be cited just
    because the terms overlap."""
    latin_honors = chunk(
        "Latin Honors",
        "Graduating students are awarded Latin honors as follows: summa cum "
        "laude, general weighted average of 1.20 to 1.45; magna cum laude, "
        "1.46 to 1.75; cum laude, 1.76 to 2.00.",
        score=0.9,
        path=("Undergraduate Academic Policies", "Graduation", "Latin Honors"),
        reasons=["academic_policy_match"],
    )
    academic_probation = chunk(
        "Academic Probation",
        "A student whose general weighted average falls to 3.00 or below in "
        "a given semester shall be placed on academic probation and must "
        "consult the Program Chair regarding an improvement plan.",
        score=0.82,
        path=("Undergraduate Academic Policies", "Retention", "Academic Probation"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return (
            "Summa cum laude requires a general weighted average of 1.20 to "
            "1.45; magna cum laude requires 1.46 to 1.75; and cum laude "
            "requires 1.76 to 2.00."
        )

    store = FakeStore([latin_honors, academic_probation])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "What are the grade ranges for summa cum laude, magna cum laude, "
            "and cum laude?"
        )

    titles = [source["title"] for source in result.sources]
    # The classification rewrite replaces the numeric answer with a generic
    # template. The Latin Honors source that caused that response must still
    # be displayed; the distractor must not.
    assert _CLASSIFICATION_FALLBACK_NOTICE in result.answer
    assert "Latin Honors" in titles
    assert "Academic Probation" not in titles


def test_citation_precision_dedupes_near_duplicate_chunks_from_same_section():
    """Two retrieval hits landing on the same document/section/page must not
    both appear as separate citations for the same evidence."""
    text = (
        "Faculty must submit two copies of the completed grading sheet to "
        "the Office of the Registrar within five (5) days after the end of "
        "the examination period."
    )
    first_hit = chunk(
        "Grading Sheet Submission",
        text,
        score=0.9,
        page=61,
        path=("Faculty Manual", "Grading", "Grading Sheet Submission"),
        reasons=["faculty_policy_match"],
    )
    duplicate_hit = chunk(
        "Grading Sheet Submission",
        text,
        score=0.88,
        page=61,
        path=("Faculty Manual", "Grading", "Grading Sheet Submission"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return (
            "Faculty must submit two copies of the grading sheet to the "
            "Registrar within 5 days after the examination period ends."
        )

    store = FakeStore([first_hit, duplicate_hit])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "How many copies of the grading sheet must faculty submit, and "
            "within how many days?",
            user_role="faculty",
        )

    assert len(result.sources) == 1
    assert result.sources[0]["title"] == "Grading Sheet Submission"


def test_citation_precision_keeps_weaker_source_for_a_different_claim():
    """Claim A can be supported much more strongly than claim B. Source B
    must still be cited when it materially supports claim B, even if its
    score against the whole answer is well below 0.45 times source A's.
    An unrelated source stays excluded. This is not a fixed top-N."""
    protocol = chunk(
        "Alpha Protocol",
        "The alpha protocol requires immediate dean written approval, "
        "academic council ratification, curriculum committee endorsement, "
        "department chair concurrence, registrar notation, student "
        "notification, and transcript annotation within 30 days of the "
        "college board meeting.",
        score=0.95,
        path=("Policy Manual", "Governance", "Alpha Protocol"),
    )
    reserves = chunk(
        "Library Reserves",
        "Library reserves expire after 7 days.",
        score=0.7,
        path=("Policy Manual", "Library", "Library Reserves"),
    )
    cafeteria = chunk(
        "Cafeteria Tickets",
        "Cafeteria meal tickets are sold at the cashier window beside the "
        "student lounge.",
        score=0.66,
        path=("Campus Services", "Dining", "Cafeteria Tickets"),
    )
    answer = (
        "The alpha protocol requires immediate dean written approval, "
        "academic council ratification, curriculum committee endorsement, "
        "department chair concurrence, registrar notation, student "
        "notification, and transcript annotation within 30 days of the "
        "college board meeting. Library reserves expire after 7 days."
    )

    selected = _select_supporting_context([protocol, reserves, cafeteria], answer)
    selected_titles = {item.metadata["section"] for item in selected}
    assert "Alpha Protocol" in selected_titles
    assert "Library Reserves" in selected_titles
    assert "Cafeteria Tickets" not in selected_titles
    # Prove the global winner-wise floor would have discarded reserves.
    # The claim-wise pass is what keeps it.
    answer_words, answer_numbers = _grounding_tokens(answer)
    idf = {token: 1.0 for token in answer_words}
    protocol_score = _citation_support_score(
        answer_words,
        answer_numbers,
        *_grounding_tokens(_chunk_search_text(protocol)),
        idf,
    )
    reserves_score = _citation_support_score(
        answer_words,
        answer_numbers,
        *_grounding_tokens(_chunk_search_text(reserves)),
        idf,
    )
    assert reserves_score < _SUPPORT_REL_FLOOR * protocol_score

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return answer

    store = FakeStore([protocol, reserves, cafeteria])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "Explain the alpha protocol requirements and how long library reserves last."
        )

    titles = [source["title"] for source in result.sources]
    assert "Alpha Protocol" in titles
    assert "Library Reserves" in titles
    assert "Cafeteria Tickets" not in titles
    assert titles[0] == "Alpha Protocol"


def test_citation_precision_no_fabricated_source_for_degraded_answer():
    """When the generated answer is a generic "I don't have information"
    reply with no real connection to what was retrieved, no citation is
    attached just so the UI has something to show."""
    unrelated_chunk = chunk(
        "ID Validation",
        "This service covers validation of student identification cards. "
        "Requirements: Certificate of Registration, one recent photo.",
        score=0.7,
        path=("Citizen's Charter", "Student Services", "ID Validation"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return (
            "I do not have enough information in the knowledge base to "
            "answer that question. Please contact the relevant office."
        )

    store = FakeStore([unrelated_chunk])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question("What is the deadline for filing an appeal?")

    assert result.sources == []


# ---------------------------------------------------------------------------
# Production-failure regressions (real production report, 2026-09-17)
#
# The tests above used short, clean 2-4 candidate fixtures and passed while
# real production citations still leaked irrelevant chunks. Root cause: the
# per-turn IDF pool is small (production retrieves ~5-9 chunks per
# question), so a term that is genuinely common across the whole knowledge
# base can look locally "rare" within just that pool and score as though it
# were distinctive; a long real institutional chunk (a full Citizen's
# Charter / Faculty Manual entry, not a 2-3 sentence snippet) only needs to
# incidentally contain a couple of such terms to clear the old score floors.
# A second, independent bug in the claim splitter (it split on every ``.``,
# including the decimal point inside "1.20") fragmented numeric-range
# answers into spurious short "claims" whose own low top-score silently
# loosened the per-claim relative floor for everything scored against them.
#
# These tests widen the candidate pool to production-realistic size (5-8)
# and use production-realistic chunk length, to actually exercise both
# failure modes instead of re-testing the same short fixtures.
#
# Text provenance, stated explicitly per source below:
#   REAL        — copied verbatim from the fixtures already committed above
#                  in this file (the only chunk text tied to the production
#                  report's document titles that is available locally).
#   CONSTRUCTED — the production report supplies only a document title and
#                  page number for these distractors; no chunk body text is
#                  available in this repository, in saved production
#                  evidence, or in logs. Per instruction, that text is not
#                  invented as a claim about what production actually
#                  contains — it is a generic institutional-boilerplate
#                  sentence (the same shape as this file's own "ID
#                  Validation"/"Technology Pre-Commercialization" fixtures)
#                  built only to test the *mechanism* (generic-term/length
#                  driven false positives), not to assert real wording.
# ---------------------------------------------------------------------------


def test_citation_precision_production_repro_transfer_credit_full_candidate_pool():
    """TEST A (production). The reported 8-chunk retrieval pool for the
    transfer-credit question, including a second "ID Validation" hit (the
    production report listed it twice) and additional weak Student
    Handbook/Citizen's Charter neighbors. Only the true supporting evidence
    should be displayed."""
    validation_requirements = chunk(
        "Validation Requirements",
        "Holders of a degree who transfer or register in this University may be "
        "given credit for equivalent courses taken without validation, provided "
        "that credits earned without validation shall not exceed 50% of the total "
        "credits required for graduation in the curriculum.",
        score=0.9,
        page=32,
        path=("Undergraduate Academic Policies", "Admission", "Validation Requirements"),
        reasons=["academic_policy_match"],
    )
    # CONSTRUCTED — title/page from the production report ("Crediting of
    # Subjects", Citizen's Charter p.95, reported "RELEVANT to process").
    crediting_of_subjects = chunk(
        "Crediting of Subjects",
        "This service processes the request of a transferee or second-course "
        "student for crediting of subjects taken in a previous school. "
        "Requirements: Transcript of Records, course syllabi. Office: "
        "Registrar. Processing time: 3 working days.",
        score=0.87,
        page=95,
        path=("Citizen's Charter", "Student Services", "Crediting of Subjects"),
        reasons=["semantic_similarity"],
    )
    # CONSTRUCTED — title/page from the production report ("Validation of
    # Subjects", Student Handbook p.31, reported "WEAK").
    validation_of_subjects = chunk(
        "Validation of Subjects",
        "A student who fails to enroll for one academic year or more must have "
        "previously earned academic units validated by the appropriate "
        "department before those units may again be counted toward the "
        "curriculum requirements.",
        score=0.84,
        page=31,
        path=("Undergraduate Academic Policies", "Admission", "Validation of Subjects"),
        reasons=["semantic_similarity"],
    )
    transferring = chunk(
        "Transferring",
        "A student who wishes to transfer to this University must submit an "
        "honorable dismissal and transcript of records to the Registrar for "
        "evaluation of previous academic units before enrollment.",
        score=0.86,
        page=27,
        path=("Undergraduate Academic Policies", "Admission", "Transferring"),
        reasons=["academic_policy_match"],
    )
    id_validation_1 = chunk(
        "ID Validation",
        "This service covers validation of student identification cards. "
        "Requirements: Certificate of Registration, one recent photo. "
        "Processing time: 15 minutes at the Registrar's window.",
        score=0.83,
        path=("Citizen's Charter", "Student Services", "ID Validation"),
        reasons=["semantic_similarity"],
    )
    # CONSTRUCTED — title/page from the production report ("Enrollment",
    # Citizen's Charter p.10, reported "WEAK").
    enrollment = chunk(
        "Enrollment",
        "This service processes the enrollment of new, continuing, and "
        "transferee students each semester. Requirements: Certificate of "
        "Registration form, valid identification. Office: Registrar. "
        "Processing time: 10 minutes per student.",
        score=0.8,
        page=10,
        path=("Citizen's Charter", "Student Services", "Enrollment"),
        reasons=["semantic_similarity"],
    )
    # Production reported a second "ID Validation" hit at p.27.
    id_validation_2 = chunk(
        "ID Validation",
        "This service covers validation of student identification cards. "
        "Requirements: Certificate of Registration, one recent photo. "
        "Processing time: 15 minutes at the Registrar's window.",
        score=0.79,
        page=27,
        path=("Citizen's Charter", "Student Services", "ID Validation"),
        reasons=["semantic_similarity"],
    )
    tech_precommercialization = chunk(
        "Technology Pre-Commercialization",
        "This service assists inventors in preparing technology for "
        "commercialization, including IP assessment and investor matching "
        "through the Technology Business Incubator.",
        score=0.78,
        path=("Citizen's Charter", "Research Services", "Technology Pre-Commercialization"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return (
            "Holders of a degree who transfer or register in LSPU may receive "
            "credit for equivalent courses without validation, but the credits "
            "earned without validation cannot exceed 50% of the total credits "
            "required for graduation in that curriculum. This 50% cap applies "
            "specifically to the degree-holder crediting rule, not to every "
            "transferee."
        )

    store = FakeStore(
        [
            validation_requirements,
            crediting_of_subjects,
            validation_of_subjects,
            transferring,
            id_validation_1,
            enrollment,
            id_validation_2,
            tech_precommercialization,
        ]
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "I'm transferring to LSPU with a previous degree. How much of my "
            "previous coursework can be credited without validation?"
        )

    titles = [source["title"] for source in result.sources]
    assert "ID Validation" not in titles
    assert "Technology Pre-Commercialization" not in titles
    assert "Validation Requirements" in titles


def test_citation_precision_production_repro_latin_honors_graduate_studies_distractor():
    """TEST C (production). Real production grade ranges (1.00-1.20 /
    1.21-1.45 / 1.46-1.75). A decimal-heavy numeric-range answer must not be
    shattered by claim splitting into fragments that loosen the relative
    floor, and a Graduate-Studies-scoped "Academic Awards Criteria" chunk
    that happens to state the same-shaped ranges is deliberately included
    here as a plausible near-duplicate rather than asserted to be wrong —
    the regression this proves is that "Completion of INC/Removal" (a
    same-pool distractor with no numeric or topical relation to Latin
    honors) is excluded."""
    undergrad_grading = chunk(
        "Undergraduate Grading System",
        "The University uses a numerical grading system ranging from 1.00 "
        "(highest) to 5.00 (lowest), with 3.00 as the minimum passing grade "
        "for undergraduate courses.",
        score=0.85,
        page=40,
        path=("Undergraduate Academic Policies", "Grading", "Undergraduate Grading System"),
        reasons=["academic_policy_match"],
    )
    grading_system_p42 = chunk(
        "Grading System",
        "Final grades are computed as the weighted average of class standing "
        "and examination results, rounded to the nearest hundredth, and "
        "recorded on the official grading sheet.",
        score=0.83,
        page=42,
        path=("Undergraduate Academic Policies", "Grading", "Grading System"),
        reasons=["academic_policy_match"],
    )
    academic_awards_criteria = chunk(
        "Academic Awards Criteria",
        "Graduate students who complete their program with a general "
        "weighted average of 1.00 to 1.20 are awarded academic distinction; "
        "1.21 to 1.45 receive high distinction; 1.46 to 1.75 receive "
        "distinction, subject to residency and no failing or dropped grade.",
        score=0.9,
        page=98,
        path=("Graduate Studies", "Awards", "Academic Awards Criteria"),
        reasons=["semantic_similarity"],
    )
    completion_of_inc = chunk(
        "Completion of INC/Removal",
        "This service processes a student's request for completion or removal "
        "of an incomplete (INC) grade. Requirements: Application for Removal of "
        "INC form, instructor's assessment. Office: Registrar. Processing time: "
        "3 business days.",
        score=0.7,
        page=94,
        path=("Citizen's Charter", "Student Services", "Completion of INC/Removal"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return (
            "Summa cum laude requires a general weighted average of 1.00 to "
            "1.20; magna cum laude requires 1.21 to 1.45; and cum laude "
            "requires 1.46 to 1.75."
        )

    store = FakeStore(
        [undergrad_grading, grading_system_p42, academic_awards_criteria, completion_of_inc]
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "What are the grade ranges for summa cum laude, magna cum laude, "
            "and cum laude?"
        )

    titles = {source["title"] for source in result.sources}
    # Strengthened (Issue 3): the honors/awards source that actually states
    # the ranges must survive, not just "the distractor is gone."
    assert "Academic Awards Criteria" in titles
    assert "Completion of INC/Removal" not in titles


def test_citation_precision_production_repro_grading_sheet_submission():
    """TEST D (production). "Two copies... Dean/Associate Dean... then
    Registrar... within ten days" must keep the sources that actually state
    that procedure and exclude the unrelated INC-removal and
    references/resources chunks the production report showed surviving."""
    grading_sheets_part1 = chunk(
        "Grading Sheets Part 1",
        "Faculty members must prepare two copies of the grading sheet: one "
        "for the Office of the Dean or Associate Dean and one for the "
        "Registrar, both bearing the faculty member's original signature.",
        score=0.88,
        page=26,
        path=("Faculty Manual", "Grading", "Grading Sheets Part 1"),
        reasons=["faculty_policy_match"],
    )
    submission_of_grades = chunk(
        "Submission of Grades",
        "Signed grading sheets must be submitted to the Registrar within ten "
        "(10) days after the scheduled final examination for the term, after "
        "review and approval by the Dean or Associate Dean.",
        score=0.9,
        page=44,
        path=("Faculty Manual", "Grading", "Submission of Grades"),
        reasons=["faculty_policy_match"],
    )
    grading_sheets_part2 = chunk(
        "Grading Sheets Part 2",
        "Grading sheets returned for correction by the Registrar's office "
        "must be resubmitted with the required attachments within the term.",
        score=0.72,
        page=26,
        path=("Faculty Manual", "Grading", "Grading Sheets Part 2"),
        reasons=["faculty_policy_match"],
    )
    completion_of_inc = chunk(
        "Completion of INC/Removal",
        "This service processes a student's request for completion or removal "
        "of an incomplete (INC) grade. Requirements: Application for Removal of "
        "INC form, instructor's assessment. Office: Registrar. Processing time: "
        "3 business days.",
        score=0.68,
        page=94,
        path=("Citizen's Charter", "Student Services", "Completion of INC/Removal"),
        reasons=["semantic_similarity"],
    )
    references_and_resources = chunk(
        "References and Resources",
        "This section lists reference materials, contact directories, and "
        "external links maintained by the University for student and faculty "
        "use, including office hours and hotline numbers.",
        score=0.6,
        page=92,
        path=("Citizen's Charter", "Appendix", "References and Resources"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return (
            "Faculty must submit two copies of the completed grading sheet: "
            "after review and approval by the Dean or Associate Dean, both "
            "copies go to the Registrar, within ten days after the scheduled "
            "final examination."
        )

    store = FakeStore(
        [
            grading_sheets_part1,
            submission_of_grades,
            grading_sheets_part2,
            completion_of_inc,
            references_and_resources,
        ]
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "How many copies of the grading sheet must faculty submit, who "
            "approves it, and within how many days after the final "
            "examination must it reach the Registrar?",
            user_role="faculty",
        )

    titles = {source["title"] for source in result.sources}
    # Strengthened (Issue 3): BOTH the copies-source and the submission/
    # deadline-source must survive -- the answer states facts from both
    # ("two copies... Dean/Associate Dean" is Grading Sheets Part 1; "within
    # ten days... to the Registrar" is Submission of Grades), so a fix that
    # only keeps one of the two claims' evidence is still incomplete.
    assert "Grading Sheets Part 1" in titles
    assert "Submission of Grades" in titles
    assert "Completion of INC/Removal" not in titles
    assert "References and Resources" not in titles


def test_citation_precision_production_repro_paraphrased_numeric_claim():
    """ISSUE 1 (review finding). A legitimate LLM paraphrase of "credits
    without validation cannot exceed 50% of total credits required for
    graduation" as "half of the units needed to graduate" must not lose its
    citation just because it shares almost no wording with the source --
    that is ordinary paraphrasing, not evidence the source is unrelated.
    Uses the same 8-candidate transfer-credit pool as the TEST A repro
    above so the fix is proven in a production-realistic, noisy pool, not
    a clean 1-candidate toy case."""
    validation_requirements = chunk(
        "Validation Requirements",
        "Holders of a degree who transfer or register in this University may be "
        "given credit for equivalent courses taken without validation, provided "
        "that credits earned without validation shall not exceed 50% of the total "
        "credits required for graduation in the curriculum.",
        score=0.9,
        page=32,
        path=("Undergraduate Academic Policies", "Admission", "Validation Requirements"),
        reasons=["academic_policy_match"],
    )
    crediting_of_subjects = chunk(
        "Crediting of Subjects",
        "This service processes the request of a transferee or second-course "
        "student for crediting of subjects taken in a previous school. "
        "Requirements: Transcript of Records, course syllabi. Office: "
        "Registrar. Processing time: 3 working days.",
        score=0.87,
        page=95,
        path=("Citizen's Charter", "Student Services", "Crediting of Subjects"),
        reasons=["semantic_similarity"],
    )
    validation_of_subjects = chunk(
        "Validation of Subjects",
        "A student who fails to enroll for one academic year or more must have "
        "previously earned academic units validated by the appropriate "
        "department before those units may again be counted toward the "
        "curriculum requirements.",
        score=0.84,
        page=31,
        path=("Undergraduate Academic Policies", "Admission", "Validation of Subjects"),
        reasons=["semantic_similarity"],
    )
    transferring = chunk(
        "Transferring",
        "A student who wishes to transfer to this University must submit an "
        "honorable dismissal and transcript of records to the Registrar for "
        "evaluation of previous academic units before enrollment.",
        score=0.86,
        page=27,
        path=("Undergraduate Academic Policies", "Admission", "Transferring"),
        reasons=["academic_policy_match"],
    )
    id_validation = chunk(
        "ID Validation",
        "This service covers validation of student identification cards. "
        "Requirements: Certificate of Registration, one recent photo. "
        "Processing time: 15 minutes at the Registrar's window.",
        score=0.83,
        path=("Citizen's Charter", "Student Services", "ID Validation"),
        reasons=["semantic_similarity"],
    )
    enrollment = chunk(
        "Enrollment",
        "This service processes the enrollment of new, continuing, and "
        "transferee students each semester. Requirements: Certificate of "
        "Registration form, valid identification. Office: Registrar. "
        "Processing time: 10 minutes per student.",
        score=0.8,
        page=10,
        path=("Citizen's Charter", "Student Services", "Enrollment"),
        reasons=["semantic_similarity"],
    )
    tech_precommercialization = chunk(
        "Technology Pre-Commercialization",
        "This service assists inventors in preparing technology for "
        "commercialization, including IP assessment and investor matching "
        "through the Technology Business Incubator.",
        score=0.78,
        path=("Citizen's Charter", "Research Services", "Technology Pre-Commercialization"),
        reasons=["semantic_similarity"],
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        # Deliberately shares almost no wording with the source: no
        # "validation", "credits", "50%", "graduation" -- just the
        # paraphrased meaning, the way an LLM commonly restates a numeric
        # rule in plain language for a student.
        return (
            "If you hold a prior degree, roughly half of the units you "
            "still need before graduating can be waived without further "
            "validation of your past coursework."
        )

    store = FakeStore(
        [
            validation_requirements,
            crediting_of_subjects,
            validation_of_subjects,
            transferring,
            id_validation,
            enrollment,
            tech_precommercialization,
        ]
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(
            "I'm transferring to LSPU with a previous degree. How much of my "
            "previous coursework can be credited without validation?"
        )

    titles = {source["title"] for source in result.sources}
    assert "Validation Requirements" in titles
    # Precision must hold too: a heavily-paraphrased claim being rescued
    # must not also rescue every same-topic distractor along with it.
    assert "Technology Pre-Commercialization" not in titles


def test_answer_claims_splits_two_sentences_after_a_day_count():
    """ISSUE 2, second required case: a non-decimal number followed by a
    real sentence boundary must also split normally."""
    claims = _answer_claims("Submit within 10 days. Copies must be signed by the Dean.")
    assert len(claims) == 2
    assert "10 days" in claims[0]
    assert "Copies" in claims[1]


# ---------------------------------------------------------------------------
# Citation debug sink / generation usage sink instrumentation (Stage 1
# baseline infrastructure for Citation Grounding V2 -- see
# benchmarks/citation_grounding_benchmark.json and
# scripts/citation_grounding_baseline.py).
#
# ``citation_debug_sink`` and ``generation_usage_sink`` are optional,
# keyword-only, default-``None`` parameters threaded through
# ``answer_qa_question`` -> ``_display_sources_for_answer`` ->
# ``_select_supporting_context``, and through ``generate_groq_answer``
# (tested separately in test_groq_answer_service.py). Every test below
# proves the instrumentation is purely observational: passing it never
# changes what is selected/returned, and omitting it (every production
# call site, and every test above this section) behaves exactly as before
# this instrumentation was added.
# ---------------------------------------------------------------------------


def test_select_supporting_context_debug_sink_none_matches_pre_instrumentation_behavior():
    """Baseline regression: with no debug_sink (every existing call site's
    signature), selection is unchanged from before this parameter existed."""
    protocol = chunk(
        "Alpha Protocol",
        "The alpha protocol requires immediate dean written approval and "
        "registrar notation within 30 days of the college board meeting.",
        score=0.95,
        path=("Policy Manual", "Governance", "Alpha Protocol"),
    )
    unrelated = chunk(
        "Cafeteria Tickets",
        "Cafeteria meal tickets are sold at the cashier window.",
        score=0.66,
        path=("Campus Services", "Dining", "Cafeteria Tickets"),
    )
    answer = (
        "The alpha protocol requires immediate dean written approval and "
        "registrar notation within 30 days of the college board meeting."
    )

    selected = _select_supporting_context([protocol, unrelated], answer)
    titles = {item.metadata["section"] for item in selected}
    assert "Alpha Protocol" in titles
    assert "Cafeteria Tickets" not in titles


def test_select_supporting_context_debug_sink_does_not_change_selection():
    """Passing a debug_sink list must select exactly the same chunks, in the
    same order, as passing none -- proving the instrumentation is read-only
    and cannot influence which citations are shown."""
    protocol = chunk(
        "Alpha Protocol",
        "The alpha protocol requires immediate dean written approval, "
        "academic council ratification, curriculum committee endorsement, "
        "department chair concurrence, registrar notation, student "
        "notification, and transcript annotation within 30 days of the "
        "college board meeting.",
        score=0.95,
        path=("Policy Manual", "Governance", "Alpha Protocol"),
    )
    reserves = chunk(
        "Library Reserves",
        "Library reserves expire after 7 days.",
        score=0.7,
        path=("Policy Manual", "Library", "Library Reserves"),
    )
    cafeteria = chunk(
        "Cafeteria Tickets",
        "Cafeteria meal tickets are sold at the cashier window beside the "
        "student lounge.",
        score=0.66,
        path=("Campus Services", "Dining", "Cafeteria Tickets"),
    )
    answer = (
        "The alpha protocol requires immediate dean written approval, "
        "academic council ratification, curriculum committee endorsement, "
        "department chair concurrence, registrar notation, student "
        "notification, and transcript annotation within 30 days of the "
        "college board meeting. Library reserves expire after 7 days."
    )
    candidates = [protocol, reserves, cafeteria]

    without_sink = _select_supporting_context(candidates, answer)
    debug_sink: list[dict] = []
    with_sink = _select_supporting_context(candidates, answer, debug_sink=debug_sink)

    assert [id(c) for c in with_sink] == [id(c) for c in without_sink]
    assert debug_sink, "debug_sink must be populated when supplied"


def test_select_supporting_context_debug_sink_records_expected_fields():
    """Each debug row exposes the same score/signal information the
    selection logic itself computes for that (claim-or-answer, chunk) pair,
    for offline diagnosis -- not a re-derivation or approximation. This must
    reflect the *reverted* (54975af) scoring signals only: no coverage or
    text_weight fields, since those belonged to the abandoned coverage-floor
    experiment and are not part of production citation selection."""
    fee_chunk = chunk(
        "Transcript of Records",
        "Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        score=0.9,
        path=("Citizen's Charter", "Registrar", "Transcript of Records"),
    )
    answer = "The Transcript of Records fee is PHP 100.00 per page."

    debug_sink: list[dict] = []
    _select_supporting_context([fee_chunk], answer, debug_sink=debug_sink)

    assert debug_sink
    row = debug_sink[0]
    assert set(row.keys()) == {
        "claim_text",
        "chunk_id",
        "citation_id",
        "shared_words",
        "shared_numbers",
        "score",
        "min_signals_met",
        "abs_floor_met",
    }
    assert row["chunk_id"] == _chunk_merge_key(fee_chunk)
    # citation_id is a distinct, additional field -- same canonical identity
    # semantics as a displayed source's citation_id (see _raw_citation_id),
    # not a rename/replacement of the existing chunk_id merge key above.
    assert row["citation_id"] == _raw_citation_id(fee_chunk, 1)
    assert row["citation_id"] != row["chunk_id"]
    assert row["claim_text"] == answer
    assert row["score"] > 0
    assert row["abs_floor_met"] == (row["score"] >= _SUPPORT_ABS_FLOOR)
    assert row["min_signals_met"] == (
        (len(row["shared_words"]) + len(row["shared_numbers"])) >= _SUPPORT_MIN_SIGNALS
    )


def test_select_supporting_context_debug_sink_covers_full_answer_and_each_claim_pass():
    """The debug sink must reflect both scoring passes the selector actually
    runs: once against the whole answer, then once per claim -- so a claim
    that only a weaker source supports is visible in the log, not just the
    winning full-answer pass."""
    protocol = chunk(
        "Alpha Protocol",
        "The alpha protocol requires immediate dean written approval, "
        "academic council ratification, curriculum committee endorsement, "
        "department chair concurrence, registrar notation, student "
        "notification, and transcript annotation within 30 days of the "
        "college board meeting.",
        score=0.95,
        path=("Policy Manual", "Governance", "Alpha Protocol"),
    )
    reserves = chunk(
        "Library Reserves",
        "Library reserves expire after 7 days.",
        score=0.7,
        path=("Policy Manual", "Library", "Library Reserves"),
    )
    answer = (
        "The alpha protocol requires immediate dean written approval, "
        "academic council ratification, curriculum committee endorsement, "
        "department chair concurrence, registrar notation, student "
        "notification, and transcript annotation within 30 days of the "
        "college board meeting. Library reserves expire after 7 days."
    )
    claims = _answer_claims(answer)

    debug_sink: list[dict] = []
    _select_supporting_context([protocol, reserves], answer, debug_sink=debug_sink)

    claim_texts = {row["claim_text"] for row in debug_sink}
    assert answer in claim_texts
    assert all(claim in claim_texts for claim in claims)
    # 2 candidates scored on the full-answer pass + 2 candidates per claim.
    assert len(debug_sink) == 2 * (1 + len(claims))


def test_display_sources_for_answer_forwards_debug_sink_without_changing_sources():
    """``_display_sources_for_answer`` must pass debug_sink straight through
    to ``_select_supporting_context`` and still return the identical
    ``sources`` payload it would return without it."""
    fee_chunk = chunk(
        "Transcript of Records",
        "Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        score=0.9,
        path=("Citizen's Charter", "Registrar", "Transcript of Records"),
    )
    answer = "The Transcript of Records fee is PHP 100.00 per page."

    without_sink = _display_sources_for_answer([fee_chunk], answer)
    debug_sink: list[dict] = []
    with_sink = _display_sources_for_answer([fee_chunk], answer, debug_sink=debug_sink)

    assert with_sink == without_sink
    assert debug_sink


def test_display_sources_for_answer_debug_sink_default_omitted_is_safe():
    """Every existing call site in ``answer_qa_question`` calls
    ``_display_sources_for_answer`` without ``debug_sink`` before this
    instrumentation existed -- confirm the omitted default is exactly
    ``None`` and causes no error."""
    fee_chunk = chunk(
        "Transcript of Records",
        "Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        score=0.9,
        path=("Citizen's Charter", "Registrar", "Transcript of Records"),
    )
    result = _display_sources_for_answer(
        [fee_chunk],
        "The Transcript of Records fee is PHP 100.00 per page.",
        merge_articles=False,
    )
    assert result and result[0]["title"] == "Transcript of Records"


def test_answer_qa_question_accepts_citation_debug_sink_and_generation_usage_sink():
    """End-to-end proof (through the real, unmocked
    ``_select_supporting_context``/``_display_sources_for_answer`` seams,
    with only the store and the Groq call itself faked) that the two new
    keyword-only parameters are accepted, populate observationally, and
    leave the returned ``QAResult`` identical to a call that omits them."""
    fee_chunk = chunk(
        "Transcript of Records",
        "Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        score=0.9,
        path=("Citizen's Charter", "Registrar", "Transcript of Records"),
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return "The Transcript of Records fee is PHP 100.00 per page."

    store = FakeStore([fee_chunk])
    question = "How much is the fee for a Transcript of Records?"
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        baseline = answer_qa_question(question)

        debug_sink: list[dict] = []
        usage_sink: dict = {}
        instrumented = answer_qa_question(
            question,
            citation_debug_sink=debug_sink,
            generation_usage_sink=usage_sink,
        )

    assert instrumented.answer == baseline.answer
    assert instrumented.sources == baseline.sources
    assert instrumented.confidence == baseline.confidence
    assert debug_sink, "citation_debug_sink must be populated for a real answer path"
    # generate_from_context above is a plain test side_effect, not the real
    # generate_groq_answer, so it never touches generation_usage_sink --
    # usage_sink's own population and graceful-degradation behavior against
    # the real function is tested in test_groq_answer_service.py.
    assert usage_sink == {}


def test_answer_qa_question_signature_declares_sinks_keyword_only_default_none():
    """Guards the exact contract the approved Stage 1+2 specification
    requires: both new parameters are keyword-only and default to ``None``,
    so every existing caller (including qa.py's route, which does not pass
    them) is unaffected."""
    import inspect

    sig = inspect.signature(answer_qa_question)
    for name in (
        "citation_debug_sink",
        "generation_usage_sink",
        "answer_rewrite_sink",
        "generation_context_sink",
    ):
        param = sig.parameters[name]
        assert param.kind == inspect.Parameter.KEYWORD_ONLY
        assert param.default is None


# ---------------------------------------------------------------------------
# Fresh Gold Benchmark Capture -- capture-infrastructure-only instrumentation
# (``answer_rewrite_sink``, ``citation_id``/``audience`` on retrieved-chunk
# debug rows, ``citation_id`` on citation-selector debug rows). Every test
# below proves this instrumentation is purely observational: passing it
# never changes what is selected/returned/retrieved, and a broken sink can
# never break the real answer.
# ---------------------------------------------------------------------------


def _fee_pipeline_setup():
    """Shared fixture for the answer_rewrite_sink tests below: a single
    chunk and a Groq stub whose generated text is stable, simple prose that
    never triggers the table-inversion or classification-template rewrite
    paths -- so evidence_bearing_answer is byte-identical to the generated
    text and the other two rewrite flags are reliably False."""
    fee_chunk = chunk(
        "Transcript of Records",
        "Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        score=0.9,
        path=("Citizen's Charter", "Registrar", "Transcript of Records"),
    )

    def generate_from_context(*, question: str, context: str, **kwargs) -> str:
        return "The Transcript of Records fee is PHP 100.00 per page."

    store = FakeStore([fee_chunk])
    question = "How much is the fee for a Transcript of Records?"
    return fee_chunk, generate_from_context, store, question


def test_answer_rewrite_sink_omitted_behaves_like_pre_instrumentation():
    """Every existing call site (including this whole test file, and
    qa.py's route) omits answer_rewrite_sink entirely. A normal successful
    answer path must behave exactly as it did before this parameter
    existed -- no error, ordinary QAResult."""
    fee_chunk, generate_from_context, store, question = _fee_pipeline_setup()
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(question)

    assert result.answer == "The Transcript of Records fee is PHP 100.00 per page."


def test_answer_rewrite_sink_enabled_returns_identical_qa_result_and_records_real_values():
    """Passing answer_rewrite_sink must be purely observational: the
    returned QAResult is identical to a call that omits it, and the sink is
    populated with the real pipeline values for a genuine generated
    answer -- not approximated or re-derived."""
    fee_chunk, generate_from_context, store, question = _fee_pipeline_setup()
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        baseline = answer_qa_question(question)

        rewrite_sink: dict = {}
        instrumented = answer_qa_question(question, answer_rewrite_sink=rewrite_sink)

    assert instrumented.answer == baseline.answer
    assert instrumented.sources == baseline.sources
    assert instrumented.confidence == baseline.confidence
    assert rewrite_sink == {
        "evidence_bearing_answer": "The Transcript of Records fee is PHP 100.00 per page.",
        "table_inversion_corrected": False,
        "classification_template_applied": False,
        "used_recovered": False,
    }


class _RaisingSink(dict):
    """A sink whose writes always raise, to prove instrumentation failure
    can never propagate into the real answer path."""

    def __setitem__(self, key, value):
        raise RuntimeError("boom: broken instrumentation")


def test_answer_rewrite_sink_failure_does_not_break_the_answer():
    fee_chunk, generate_from_context, store, question = _fee_pipeline_setup()
    broken_sink = _RaisingSink()
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=generate_from_context,
        ),
    ):
        result = answer_qa_question(question, answer_rewrite_sink=broken_sink)

    assert result.answer == "The Transcript of Records fee is PHP 100.00 per page."


def test_retrieved_debug_citation_id_matches_displayed_source_identity_formula():
    """_retrieved_debug's citation_id must use the same canonical identity
    formula as a displayed source's citation_id (metadata chunk_id, else
    document_id::chunk_index) -- proven here for a chunk whose document_id
    and source_filename match no real row (so resolve_citation_document's
    Postgres/filename fallback finds nothing and never substitutes a
    resolved document_id -- see _raw_citation_id's own documented caveat
    that the two are only guaranteed identical in that no-remap case), so
    the two identities must be byte-identical."""
    unresolvable_chunk = RetrievedChunk(
        document_id="no-such-document-fixture-0f3a9c",
        title="LSPU Student Handbook",
        source_filename="no-such-file-fixture-0f3a9c.pdf",
        chunk_index=1,
        text="Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        relevance_score=0.9,
        original_score=0.82,
        reranked_score=0.9,
        rerank_reasons=["test_match"],
        metadata={
            "chapter": "Citizen's Charter",
            "article": "Registrar",
            "section": "Transcript of Records",
            "page_start": 46,
            "audience": "both",
        },
    )

    debug_rows = _retrieved_debug([unresolvable_chunk])
    sources = _sources_from_chunks([unresolvable_chunk])

    assert debug_rows[0]["citation_id"] == sources[0]["citation_id"]
    assert debug_rows[0]["citation_id"] == _raw_citation_id(unresolvable_chunk, 1)
    assert debug_rows[0]["citation_id"] == "no-such-document-fixture-0f3a9c::1"


def test_retrieved_debug_audience_passthrough_without_changing_retrieval():
    """audience metadata is copied through to retrieved_chunks debug rows
    exactly as stored -- never substituted with "student" or any other
    default. Uses role="office" (which bypasses filter_chunks_for_audience
    entirely, per article_rag_indexer.filter_chunks_for_audience) so both a
    faculty-tagged and an untagged chunk are retrieved regardless of their
    audience tag, isolating "is audience copied correctly" from "did
    retrieval filtering change" -- both chunks below must still both be
    retrieved, proving this debug field addition does not alter retrieval."""
    faculty_tagged = chunk(
        "Faculty Load Policy",
        "Faculty members carry a maximum load per semester as defined by policy.",
        score=0.9,
        path=("Faculty Manual", "Workload", "Faculty Load Policy"),
    )
    faculty_tagged.metadata["audience"] = "faculty"
    untagged = chunk(
        "Legacy Notice",
        "Legacy notices remain posted for one academic year.",
        score=0.7,
        path=("Handbook", "General", "Legacy Notice"),
    )
    del untagged.metadata["audience"]

    result, store, _mock_generate = run_question(
        "What is the faculty load policy and the legacy notice rule?",
        [faculty_tagged, untagged],
        user_role="office",
    )

    debug_by_doc = {row["document_id"]: row for row in result.retrieved_chunks}
    assert set(debug_by_doc) == {"faculty-load-policy", "legacy-notice"}
    assert debug_by_doc["faculty-load-policy"]["audience"] == "faculty"
    assert debug_by_doc["legacy-notice"]["audience"] is None


# ---------------------------------------------------------------------------
# Fresh Gold Benchmark Capture, Stage 4 -- generation_context_sink and
# rewrite_stage_observed honesty. RETRIEVED CONTEXT != DISPLAYED CITATIONS
# != FINAL GENERATION CONTEXT: generation_context_sink must capture the
# exact final selected_context chunks AFTER _restore_missing_facet_context
# and _prefer_active_topic_context have both already run, never the
# earlier selected_for_context flags on retrieved_chunks debug rows.
# ---------------------------------------------------------------------------


def test_generation_context_sink_signature_keyword_only_default_none():
    import inspect

    sig = inspect.signature(answer_qa_question)
    param = sig.parameters["generation_context_sink"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


def test_generation_context_sink_not_reached_for_greeting():
    """A branch that never calls generate_groq_answer must record
    generation_invoked: False with an explicit status, never a silently
    empty/ambiguous sink and never a fabricated chunk list."""
    sink: dict = {}
    result = answer_qa_question("Hello!", generation_context_sink=sink)
    assert result.answer  # sanity: greeting path actually answered
    assert sink["generation_invoked"] is False
    assert sink["generation_succeeded"] is False
    assert sink["status"] == "not_reached:greeting_short_circuit"
    assert sink["final_context_chunks"] == []


def test_generation_context_sink_not_reached_for_out_of_scope():
    """The out-of-scope check runs AFTER get_knowledge_base_store() is
    called (store.chunk_count is checked first) -- the store must be
    patched here or this would hit a real Chroma connection."""
    sink: dict = {}
    store = FakeStore([])
    with patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store):
        answer_qa_question("Who is the president of the Philippines?", generation_context_sink=sink)
    assert sink["generation_invoked"] is False
    assert sink["status"] == "not_reached:out_of_scope_short_circuit"
    assert sink["final_context_chunks"] == []


def test_generation_context_sink_not_invoked_for_typed_answer_path():
    """A typed/templated answer never calls generation at all -- the sink
    must say so explicitly, not silently omit the fact.

    Stage 5 fix: the previous version of this test relied on a specific
    chunk/question fixture reliably tripping the real ``use_typed_now``
    heuristic (``bool(typed_answer) and not is_service_howto_query(...)``),
    which proved unstable and made the test self-skip rather than exercise
    the branch. Per the Stage 5 instruction, this now directly controls
    the two decision points that heuristic depends on --
    ``_typed_answer_from_context`` and ``is_service_howto_query`` -- so the
    EXISTING ``use_typed_now`` branch in ``answer_qa_question`` is forced
    deterministically, without changing what that branch itself does or
    touching any production selection/classification behavior."""
    fee_chunk = chunk(
        "Transcript of Records",
        "Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        score=0.9,
        path=("Citizen's Charter", "Registrar", "Transcript of Records"),
    )
    store = FakeStore([fee_chunk])
    sink: dict = {}
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering._typed_answer_from_context",
            return_value="Typed answer: fee is PHP 100.00 per page.",
        ),
        patch("app.services.qa.question_answering.is_service_howto_query", return_value=False),
        patch("app.services.qa.question_answering.generate_groq_answer") as mock_generate,
    ):
        result = answer_qa_question(
            "How much is the fee for a Transcript of Records?",
            generation_context_sink=sink,
        )

    mock_generate.assert_not_called()
    assert result.answer == "Typed answer: fee is PHP 100.00 per page."
    assert sink["generation_invoked"] is False
    assert sink["generation_succeeded"] is False
    assert sink["status"] == "not_invoked:typed_answer_used_instead_of_generation"
    assert sink["final_context_chunks"] == []


def test_generation_context_sink_invoked_and_succeeded_matches_selected_context():
    """The success path's sink must reflect the real, final selected_context
    -- safe metadata only, never chunk body text.

    Uses an unresolvable document_id/source_filename (not the ``chunk()``
    helper's default ``handbook.pdf``, which a real fixture row in this
    test environment's document store resolves and REMAPS -- see
    ``_raw_citation_id``'s own documented no-DB-resolution caveat) so the
    sink's un-resolved citation_id and the displayed source's resolved one
    are guaranteed to coincide for this equality assertion, rather than
    incidentally exercising the documented divergence case."""
    fee_chunk = RetrievedChunk(
        document_id="no-such-document-fixture-5f2b8e",
        title="LSPU Student Handbook",
        source_filename="no-such-file-fixture-5f2b8e.pdf",
        chunk_index=1,
        text="Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        relevance_score=0.9,
        original_score=0.82,
        reranked_score=0.9,
        rerank_reasons=["test_match"],
        metadata={
            "chapter": "Citizen's Charter",
            "article": "Registrar",
            "section": "Transcript of Records",
            "page_start": 46,
            "audience": "both",
        },
    )
    store = FakeStore([fee_chunk])
    sink: dict = {}
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value="The Transcript of Records fee is PHP 100.00 per page.",
        ),
    ):
        result = answer_qa_question(
            "How much is the fee for a Transcript of Records?",
            generation_context_sink=sink,
        )

    assert sink["generation_invoked"] is True
    assert sink["generation_succeeded"] is True
    assert sink["status"] == "invoked_and_succeeded:generation_answer_used"
    assert len(sink["final_context_chunks"]) == 1
    final_chunk = sink["final_context_chunks"][0]
    assert final_chunk["citation_id"] == _raw_citation_id(fee_chunk, 1)
    assert final_chunk["document_id"] == "no-such-document-fixture-5f2b8e"
    assert final_chunk["audience"] == "both"
    # Safe metadata only -- never chunk body text.
    assert "content_preview" not in final_chunk
    assert "text" not in final_chunk
    # Matches what was actually displayed for this simple, single-chunk case.
    assert {s["citation_id"] for s in result.sources} == {final_chunk["citation_id"]}


def test_generation_context_sink_recovery_answer_used_status_when_used_recovered():
    """Stage 5 item 4 fix: when the SUCCESS path's real ``used_recovered``
    is True (the offline charter recovery replaced the generated text as
    the displayed answer), the sink's status must say so explicitly --
    "recovery_answer_used" -- never the "generation_answer_used" label,
    which would overstate that the generated text is what the user was
    shown. Forces the real ``used_recovered`` path deterministically by
    mocking ``_recover_factual_charter_answer`` /
    ``_indicates_missing_information`` (the same two decision points the
    production code itself reads), never by changing answer
    selection/recovery behavior."""
    fee_chunk = chunk(
        "Transcript of Records",
        "Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        score=0.9,
        path=("Citizen's Charter", "Registrar", "Transcript of Records"),
    )
    store = FakeStore([fee_chunk])
    sink: dict = {}
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value="A generated answer that will be overridden by recovery.",
        ),
        patch(
            "app.services.qa.question_answering._recover_factual_charter_answer",
            return_value="Recovered answer: PHP 100.00 per page at the Cashier.",
        ),
        patch(
            "app.services.qa.question_answering._indicates_missing_information",
            return_value=True,
        ),
    ):
        result = answer_qa_question(
            "How much is the fee for a Transcript of Records?",
            generation_context_sink=sink,
        )

    assert result.answer == "Recovered answer: PHP 100.00 per page at the Cashier."
    assert sink["generation_invoked"] is True
    assert sink["generation_succeeded"] is True
    assert sink["status"] == "invoked_and_succeeded:recovery_answer_used"


def test_generation_context_sink_invoked_but_failed_records_context_sent_to_failed_call():
    """A GroqAnswerError still recorded invoked=True (the call really was
    attempted with this context) but succeeded=False (the displayed answer
    did not come from it) -- the two must never be conflated."""
    fee_chunk = chunk(
        "Transcript of Records",
        "Transcript of Records. Fees: PHP 100.00 per page, paid at the Cashier.",
        score=0.9,
        path=("Citizen's Charter", "Registrar", "Transcript of Records"),
    )
    store = FakeStore([fee_chunk])
    sink: dict = {}
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("503 service unavailable"),
        ),
    ):
        answer_qa_question(
            "How much is the fee for a Transcript of Records?",
            generation_context_sink=sink,
        )

    assert sink["generation_invoked"] is True
    assert sink["generation_succeeded"] is False
    assert sink["status"] == "invoked_but_failed:conversational_or_recovered_fallback_used"
    assert len(sink["final_context_chunks"]) == 1
    assert sink["final_context_chunks"][0]["citation_id"] == _raw_citation_id(fee_chunk, 1)


def test_generation_context_sink_failure_does_not_break_the_answer():
    """Mirrors the answer_rewrite_sink failure-safety test: a broken sink
    must never propagate into the real answer."""

    class _RaisingDict(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("boom: broken generation_context_sink")

    result = answer_qa_question("Hello!", generation_context_sink=_RaisingDict())
    assert result.answer == GREETING_ANSWER


def test_answer_rewrite_sink_stays_empty_when_branch_never_reaches_rewrite_stage():
    """Stage 4 item 7: an empty answer_rewrite_sink after a branch that
    never reaches _record_answer_rewrite (e.g. greeting) must stay
    genuinely empty -- never populated with (possibly misleading) False
    values that would look identical to 'the rewrite stage ran and
    nothing happened'. A capture script reading this must be able to tell
    the two apart by checking `bool(sink)`."""
    sink: dict = {}
    answer_qa_question("Hello!", answer_rewrite_sink=sink)
    assert sink == {}


# --- Stage 4 item 9: proof that generation_context_sink reflects
# selected_context strictly AFTER both _restore_missing_facet_context and
# _prefer_active_topic_context have run -------------------------------------


def test_generation_context_sink_recorded_after_both_context_mutation_calls_source_order():
    """Structural guard: every generation-invoked _record_generation_context
    call site must appear, in source order, AFTER both
    _restore_missing_facet_context and _prefer_active_topic_context --
    proving by construction that the sink can never reflect a pre-mutation
    selected_context, regardless of which specific fixture a behavioral
    test happens to exercise."""
    import inspect

    source = inspect.getsource(answer_qa_question)
    restore_idx = source.index("_restore_missing_facet_context(")
    prefer_idx = source.index("_prefer_active_topic_context(selected_context, active_topic)")
    assert restore_idx > 0 and prefer_idx > restore_idx

    invoked_status_markers = [
        'status="invoked_but_failed:typed_answer_fallback_used_after_groq_error"',
        'status="invoked_but_failed:conversational_or_recovered_fallback_used"',
        # Stage 5 item 4: the success path's status is now a conditional
        # expression on real used_recovered state, not a single literal --
        # both of its branch strings must still appear after both mutations.
        '"invoked_and_succeeded:recovery_answer_used"',
        '"invoked_and_succeeded:generation_answer_used"',
    ]
    for marker in invoked_status_markers:
        marker_idx = source.index(marker)
        assert marker_idx > restore_idx, marker
        assert marker_idx > prefer_idx, marker


def test_generation_context_sink_reflects_active_topic_narrowing_for_slot_followup():
    """Behavioral proof: for a slot follow-up ("How much does it cost?")
    whose active topic is set by conversation history, the final
    generation context must reflect ONLY the chunk _prefer_active_topic_
    context actually kept for that topic -- not every retrieved chunk."""
    tor = RetrievedChunk(
        document_id="tor-service",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=1,
        text=(
            "Issuance of Transcript of Records (TOR)\n"
            "Office / Division\nOffice of the Registrar\n"
            "Fees\nUndergraduate: P75.00/page\n"
        ),
        relevance_score=0.9,
        original_score=0.85,
        reranked_score=0.9,
        rerank_reasons=["test"],
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Issuance of Transcript of Records (TOR)",
            "office": "Office of the Registrar",
            "total_fees": "Undergraduate: P75.00/page",
            "page_number": 40,
            "audience": "both",
        },
    )
    distractor = RetrievedChunk(
        document_id="cafeteria",
        title="Citizen Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=2,
        text="Cafeteria Tickets\nOffice / Division\nCafeteria Office\nFees\nP10.00 per meal ticket\n",
        relevance_score=0.88,
        original_score=0.8,
        reranked_score=0.88,
        rerank_reasons=["test"],
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "source_section": "Cafeteria Tickets",
            "office": "Cafeteria Office",
            "total_fees": "P10.00 per meal ticket",
            "page_number": 55,
            "audience": "both",
        },
    )
    store = FakeStore([tor, distractor])
    history = [
        {"role": "user", "content": "Tell me about Transcript of Records."},
        {
            "role": "assistant",
            "content": "The Transcript of Records (TOR) is handled by the Office of the Registrar.",
        },
    ]
    sink: dict = {}
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value="It costs P75.00 per page.",
        ),
    ):
        result = answer_qa_question(
            "How much does it cost?",
            history=history,
            generation_context_sink=sink,
        )

    assert sink["generation_invoked"] is True
    final_ids = {c["document_id"] for c in sink["final_context_chunks"]}
    # The active-topic-matching TOR chunk must be present, and the
    # unrelated cafeteria distractor must not be -- proving the sink
    # reflects real post-active-topic-filtering context, not an unfiltered
    # dump of everything retrieved.
    assert "tor-service" in final_ids
    assert "cafeteria" not in final_ids
    # (Displayed sources' document_id is not compared here: a real fixture
    # row for this test environment's "Laguna State Polytechnic
    # University-CC_2026-1st Edition.pdf" filename resolves/remaps the
    # displayed document_id via app.services.document_storage, per
    # _raw_citation_id's own documented no-DB-resolution divergence caveat
    # -- irrelevant to what this test actually proves, which is the
    # active-topic narrowing itself, above.)


# --- Phase 1 context-selection fix: select_context_chunks's rank-1 exemption
# from the strong-penalty veto must not be the ONLY route a legitimate,
# well-scored, non-penalized chunk has to survive -- regression coverage for
# the fg_j1/fg_a1 Fresh Gold failures at the selection layer itself (the
# reranker-level false-positive fix is covered separately in
# tests/test_retrieval_reranker.py).


def test_select_context_chunks_keeps_close_scoring_sibling_without_strong_penalty():
    """Mirrors fg_j1's post-fix shape: three near-duplicate chunks close in
    score, none carrying a strong-penalty rerank reason. Before the Phase 1
    reranker fix, the Alumni/Transferee siblings here would have carried
    penalty_disciplinary_offense_out_of_domain and been vetoed by the rank-1
    exemption despite otherwise qualifying via keep_close_to_rank_1; with
    that false penalty absent (as constructed here), all three must survive."""
    undergrad = chunk(
        "Good Moral (Undergraduate)", "Certificate of Registration required.", score=3.42,
        reasons=["title_path_keyword_match", "boost_exact_service_title:good moral"],
    )
    alumni = chunk(
        "Good Moral (Alumni)", "Transcript of Record required.", score=3.11,
        reasons=["title_path_keyword_match", "boost_exact_service_title:good moral"],
    )
    transferee = chunk(
        "Good Moral (Transferee)", "Certificate of Transfer required.", score=3.34,
        reasons=["title_path_keyword_match", "boost_exact_service_title:good moral"],
    )
    selected, _ = select_context_chunks(
        "I'm an LSPU alumnus and I need a Good Moral Certificate, what do I need to bring?",
        [undergrad, transferee, alumni],
    )
    selected_titles = {c.metadata["section"] for c in selected}
    assert "Good Moral (Alumni)" in selected_titles


def test_select_context_chunks_drops_sibling_when_strong_penalty_present_and_not_rank_1():
    """Negative control: the rank-1 exemption's veto must still function
    normally for a chunk that legitimately carries a strong penalty and is
    not rank 1 -- Phase 1 narrowed WHEN the penalty fires, not whether the
    veto itself still applies once it does."""
    rank1 = chunk(
        "Attendance Policy", "Submit an excuse slip for absence.", score=3.5,
        reasons=["keep_rank_1", "keep_close_to_rank_1"],
    )
    penalized_sibling = chunk(
        "Non-wearing of ID", "Minor offense: non-wearing of identification card is subject to sanction.",
        score=3.3, reasons=["keep_close_to_rank_1", "penalty_disciplinary_offense_out_of_domain"],
    )
    selected, decisions = select_context_chunks(
        "What should I do about attendance after being absent due to illness?",
        [rank1, penalized_sibling],
    )
    selected_titles = {c.metadata["section"] for c in selected}
    assert "Non-wearing of ID" not in selected_titles
    kept, reasons = decisions[id(penalized_sibling)]
    assert kept is False


# --- Phase 2 context-selection fix: a low-confidence classify_question()
# guess must not become an authoritative query_domain for context-selection
# boosting. Gated in _query_taxonomy_labels (question_answering.py), the
# sole caller of classify_question() used for that purpose -- classify_
# question() itself is unchanged and still returns its full diagnostic
# result (confidence/method included) for any other caller.


def _fake_classification(category, subcategory, confidence, method="rule"):
    return ClassificationResult(
        category=category, subcategory=subcategory, office="Registrar",
        confidence=confidence, method=method, keywords=(),
    )


def test_low_confidence_embedding_fallback_does_not_set_query_domain():
    with patch(
        "app.services.qa.question_answering.classify_question",
        return_value=_fake_classification("Student Services", "Student Welfare", 0.28, "embedding_similarity"),
    ):
        domain = _detected_query_domain("how many units do i need to be classified as a junior student")
    assert domain is None


def test_high_confidence_rule_classification_still_sets_query_domain():
    with patch(
        "app.services.qa.question_answering.classify_question",
        return_value=_fake_classification("Student Records", "Good Moral", 0.98, "rule"),
    ):
        domain = _detected_query_domain("good moral certificate alumni")
    assert domain == "Student Records"


def test_confidence_exactly_at_threshold_is_accepted():
    from app.services.knowledge_taxonomy import LOW_CONFIDENCE_THRESHOLD

    with patch(
        "app.services.qa.question_answering.classify_question",
        return_value=_fake_classification("Academic Policies", "Registration", LOW_CONFIDENCE_THRESHOLD, "rule"),
    ):
        domain = _detected_query_domain("some question")
    assert domain == "Academic Policies"


def test_confidence_just_below_threshold_is_rejected():
    from app.services.knowledge_taxonomy import LOW_CONFIDENCE_THRESHOLD

    with patch(
        "app.services.qa.question_answering.classify_question",
        return_value=_fake_classification("Academic Policies", "Registration", LOW_CONFIDENCE_THRESHOLD - 0.001, "rule"),
    ):
        domain = _detected_query_domain("some question")
    assert domain is None


def test_no_domain_path_does_not_crash_context_selection():
    """A rejected/absent query_domain must flow safely through the whole
    selection loop -- no keep_same_domain reason should ever be produced,
    and selection must complete normally rather than raising."""
    with patch(
        "app.services.qa.question_answering.classify_question",
        return_value=_fake_classification("Student Services", "Student Welfare", 0.28, "embedding_similarity"),
    ):
        gold = chunk(
            "Classifications of Students", "Junior = 50%-75% of units earned.", score=1.26,
            reasons=["boost_distinctive_content_terms:units,earned,junior"],
        )
        irrelevant_but_domain_tagged = chunk(
            "Graduate internship rule", "Consult and assist student interns in revolving problems.", score=1.47,
            reasons=["keep_close_to_rank_1"],
        )
        selected, decisions = select_context_chunks(
            "how many units do i need to be classified as a junior student",
            [irrelevant_but_domain_tagged, gold],
        )
    for _kept, reasons in decisions.values():
        assert not any(r.startswith("keep_same_domain") for r in reasons)


def test_fg_c2_gold_chunk_survives_context_selection_with_real_classifier():
    """End-to-end regression anchor using the REAL classify_question() (not
    mocked) for the exact Fresh Gold fg_c2 question -- pins the observed
    0.28-confidence embedding-similarity misclassification and confirms the
    gate suppresses it in the live classifier, not just a mocked one."""
    from app.services.knowledge_taxonomy import classify_question

    q = "How many units do I need to have earned to be classified as a Junior student?"
    real_result = classify_question(q.casefold())
    assert real_result.confidence < 0.45  # pins the documented low-confidence finding
    domain = _detected_query_domain(q.casefold())
    assert domain is None


def test_fg_k1_and_fg_j1_and_fg_e1_real_classifications_behave_as_expected():
    """Regression anchors for the three named controls: fg_k1's real
    classification is also low-confidence and must now be suppressed too
    (its earlier success never depended on the domain boost); fg_j1 and
    fg_e1's real classifications are high-confidence and must be
    preserved."""
    cases = {
        "fg_k1 (low confidence, gate suppresses)": (
            "What percentage of total units must I have completed to be considered a Sophomore instead of a Freshman?",
            False,
        ),
        "fg_j1 (high confidence, gate preserves)": (
            "I'm an LSPU alumnus and I need a Good Moral Certificate, what do I need to bring?",
            True,
        ),
        "fg_e1 (high confidence, gate preserves)": (
            "What do I need to submit to the Budget Office to get funding approved for a request letter from my student organization?",
            True,
        ),
    }
    for label, (question, expect_domain) in cases.items():
        domain = _detected_query_domain(question.casefold())
        if expect_domain:
            assert domain is not None, label
        else:
            assert domain is None, label

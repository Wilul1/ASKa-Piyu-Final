from unittest.mock import patch

import pytest

from app.services.chroma_store import RetrievedChunk
from app.services.qa.groq_answer_service import GroqAnswerError
from app.services.qa.question_answering import (
    PROGRAM_COLLECTION,
    OUT_OF_SCOPE_ANSWER,
    _confidence_for,
    answer_qa_question,
    detect_collection_intent,
    detect_broad_query,
    format_retrieved_context,
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
        },
    )


class FakeStore:
    chunk_count = 485

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls = []

    def search(self, question: str, *, top_k: int | None = None, raw_k: int | None = None):
        self.calls.append({"question": question, "top_k": top_k, "raw_k": raw_k})
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


def run_question(question: str, chunks: list[RetrievedChunk]):
    store = FakeStore(chunks)
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value="Follow the cited policy in the retrieved context.",
        ) as mock_generate,
    ):
        result = answer_qa_question(question)
    return result, store, mock_generate


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

    assert store.calls[0]["top_k"] == 5
    assert store.calls[0]["raw_k"] == 10
    assert "Title: Attendance Policy" in mock_generate.call_args.kwargs["context"]
    assert result.sources[0]["title"] == "Attendance Policy"
    assert result.confidence in {"high", "medium"}


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

    def generate_from_context(*, question: str, context: str) -> str:
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

    def generate_from_context(*, question: str, context: str) -> str:
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

    assert store.calls[0]["top_k"] == 5
    assert store.calls[0]["raw_k"] == 10
    assert "broad_mode" not in mock_generate.call_args.kwargs
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

    assert store.calls[0]["top_k"] == 5
    assert store.calls[0]["raw_k"] == 10
    assert "broad_mode" not in mock_generate.call_args.kwargs
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
    assert "AI answer service is temporarily busy" in result.answer
    assert "Groq answer generation timed out" not in result.answer
    assert result.sources
    assert result.retrieved_chunks[0]["boost_reasons"] == ["test_match"]


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
    assert "AI answer service is temporarily busy" in result.answer
    assert "rate_limit_exceeded" not in result.answer
    assert "Groq" not in result.answer
    assert "secure an excuse slip" in result.answer
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

    def generate_from_context(*, question: str, context: str) -> str:
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

"""Conversational fallback when the LLM is unavailable."""

from __future__ import annotations

from unittest.mock import patch

from app.services.chroma_store import RetrievedChunk
from app.services.qa.conversational_fallback import (
    detect_fallback_intent,
    format_conversational_fallback,
    parse_officials_from_text,
)
from app.services.qa.groq_answer_service import GroqAnswerError
from app.services.qa.question_answering import answer_qa_question


OFFICIALS_TEXT = """
Administrative Officials
Administrative Officials
DR. MARIO R. BRIONES University President
DR. EDEN C. CALLO Vice President for Academic Affairs
ENGR. BELTRAN P. PEDRIGAL, MSA Vice President for Administration
DR. ROBERT C. AGATEP Vice President for Research Development and Extension
"""


def _chunk(
    title: str,
    text: str,
    *,
    score: float = 0.9,
    document_type: str = "handbook_policy",
    article_type: str = "policy",
    page: int = 12,
) -> RetrievedChunk:
    return RetrievedChunk(
        document_id="handbook-doc",
        title="LSPU Student Handbook",
        source_filename="LSPU_Student_Handbook.pdf",
        chunk_index=0,
        text=text,
        relevance_score=score,
        original_score=score,
        reranked_score=score,
        metadata={
            "document_id": "handbook-doc",
            "title": title,
            "source_section": title,
            "section": title,
            "document_type": document_type,
            "article_type": article_type,
            "page_number": page,
            "source_filename": "LSPU_Student_Handbook.pdf",
            "audience": "both",
        },
    )


class _Store:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.chunk_count = len(chunks)

    def search(self, question, *, top_k=None, raw_k=None):
        return self.chunks

    def list_chunks(self):
        return []


def test_parse_officials_from_administrative_officials_text():
    pairs = parse_officials_from_text(OFFICIALS_TEXT)
    assert len(pairs) >= 3
    names = " ".join(name for name, _ in pairs).casefold()
    positions = " ".join(pos for _, pos in pairs).casefold()
    assert "briones" in names
    assert "university president" in positions
    assert "callo" in names
    assert "academic" in positions


def test_detect_fallback_intent():
    assert detect_fallback_intent("Who is the university president?") == "person"
    assert detect_fallback_intent("Who are the administrative officials?") == "person"
    assert detect_fallback_intent("How do I validate my ID?") == "service"
    assert detect_fallback_intent("What is the dismissal policy?") == "policy"
    assert detect_fallback_intent("officials") == "clarification"


def test_format_president_only_not_full_list():
    answer = format_conversational_fallback(
        "Who is the university president?",
        [_chunk("Administrative Officials", OFFICIALS_TEXT)],
        [{"title": "Administrative Officials", "page_number": 12}],
        confidence="medium",
    )
    assert "AI answer service is temporarily busy" not in answer
    assert "Mario" in answer or "BRIONES" in answer.upper() or "Briones" in answer
    assert "President" in answer
    assert "Vice President for Academic Affairs" not in answer
    assert answer.count("\n- ") <= 1


def test_format_full_officials_list_clean_bullets():
    answer = format_conversational_fallback(
        "Who are the administrative officials?",
        [_chunk("Administrative Officials", OFFICIALS_TEXT)],
        [{"title": "Administrative Officials"}],
        confidence="medium",
    )
    assert "AI answer service is temporarily busy" not in answer
    assert "Here are the administrative officials" in answer
    assert "—" in answer or "-" in answer
    assert "University President" in answer
    # Not a raw OCR dump of the whole block as one paragraph.
    assert "Administrative Officials\nAdministrative Officials\nDR." not in answer
    bullet_count = sum(1 for line in answer.splitlines() if line.strip().startswith("-"))
    assert 3 <= bullet_count <= 6


def test_llm_failure_officials_returns_conversational_answer_with_sources():
    store = _Store([_chunk("Administrative Officials", OFFICIALS_TEXT, score=0.9)])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
    ):
        result = answer_qa_question("Who are the administrative officials?")

    assert result.fallback_used is True
    assert "AI answer service is temporarily busy" not in result.answer
    assert "administrative officials" in result.answer.casefold()
    assert "Briones" in result.answer or "BRIONES" in result.answer.upper()
    assert result.sources
    assert result.sources[0].get("source_section") == "Administrative Officials" or (
        result.sources[0].get("title") in {"Administrative Officials", "LSPU Student Handbook"}
    )


def test_llm_failure_president_query_returns_only_president():
    store = _Store([_chunk("Administrative Officials", OFFICIALS_TEXT, score=0.91)])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("429 rate_limit_exceeded"),
        ),
    ):
        result = answer_qa_question("Who is the university president?")

    assert "AI answer service is temporarily busy" not in result.answer
    assert "President" in result.answer
    assert "Vice President for Academic Affairs" not in result.answer
    assert result.sources


def test_llm_failure_service_question_uses_service_formatter():
    service = _chunk(
        "ID Validation",
        (
            "Overview\nThis service provides assistance for ID Validation.\n\n"
            "Office / Division\nOffice of the Student Affairs and Services\n\n"
            "Requirements\n"
            "- Requirement: Certificate of Registration\n"
            "- Requirement: Student ID\n\n"
            "Steps\n"
            "1. Client Step: Present the Certificate of Registration.\n"
            "2. Client Step: Accept the validated ID.\n\n"
            "Fees\nNone\n\n"
            "Total Processing Time\n4 minutes\n"
        ),
        document_type="citizen_charter",
        article_type="service_procedure",
        page=18,
        score=0.93,
    )
    store = _Store([service])
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
    ):
        result = answer_qa_question("How do I validate my ID?")

    # Typed procedure path usually wins before Groq; either way answer must be clean.
    assert "AI answer service is temporarily busy" not in result.answer
    assert "Requirements:" in result.answer or "Certificate of Registration" in result.answer
    assert "Steps:" in result.answer or "Present the Certificate" in result.answer
    assert result.sources
    assert result.sources[0].get("page_number") in {18, "18"} or result.sources[0].get("page") in {
        18,
        "18",
    }


def test_faculty_policy_fallback_prefers_faculty_manual_and_clean_label():
    student = RetrievedChunk(
        document_id="sh",
        title="Student Handbook",
        source_filename="LSPU Student Handbook.pdf",
        chunk_index=0,
        text="Course Load Graduate Studies > Article 5 > Course Load and Requirements.",
        relevance_score=0.9,
        metadata={
            "section": "Course Load",
            "source_section": "Sec. 1 > Course Load",
            "source_filename": "LSPU Student Handbook.pdf",
            "page_number": 56,
        },
    )
    faculty = RetrievedChunk(
        document_id="fm",
        title="Faculty Manual",
        source_filename="LSPU Faculty Manual 2020.pdf",
        chunk_index=1,
        text=(
            "Teaching Load Assignment. The Dean / Associate Dean of the College are "
            "responsible in the preparation and assignment of teaching loads."
        ),
        relevance_score=0.75,
        metadata={
            "section": "Teaching Load Assignment",
            "source_section": "D. Teaching Load Assignment",
            "source_filename": "LSPU Faculty Manual 2020.pdf",
            "page_number": 22,
        },
    )
    answer = format_conversational_fallback(
        "How is teaching load assigned at LSPU?",
        [student, faculty],
    )
    assert "Dean" in answer or "teaching loads" in answer.casefold()
    assert "I found information under" not in answer
    assert "Open the cited source" not in answer
    assert "Based on" not in answer
    assert "See the cited source" not in answer


def test_faculty_responsibilities_fallback_skips_breadcrumb_heading_noise():
    noisy = RetrievedChunk(
        document_id="noise",
        title="Faculty Manual",
        source_filename="LSPU Faculty Manual 2020.pdf",
        chunk_index=0,
        text=(
            "Regular Faculty Designated as Chairperson B. Faculty Attendance and Absences "
            "> 1.2 > Regular Faculty Designated as Chairperson"
        ),
        relevance_score=0.9,
        metadata={
            "section": "Regular Faculty Designated as Chairperson",
            "source_section": "1.2 > Regular Faculty Designated as Chairperson",
            "source_filename": "LSPU Faculty Manual 2020.pdf",
        },
    )
    commitment = RetrievedChunk(
        document_id="commit",
        title="Faculty Manual",
        source_filename="LSPU Faculty Manual 2020.pdf",
        chunk_index=1,
        text=(
            "Teaching is a personal commitment of oneself to others with the intention "
            "to fulfill these obligations to satisfaction."
        ),
        relevance_score=0.8,
        metadata={
            "section": "Commitment of the LSPU Faculty",
            "source_section": "III. Commitment of the LSPU Faculty",
            "source_filename": "LSPU Faculty Manual 2020.pdf",
        },
    )
    answer = format_conversational_fallback(
        "What are the responsibilities of faculty members?",
        [noisy, commitment],
    )
    assert "personal commitment" in answer.casefold()
    assert "I found information under" not in answer
    assert "Open the cited source" not in answer
    assert " > " not in answer


def test_policy_fallback_answers_directly_without_pointer_phrasing():
    chunk = RetrievedChunk(
        document_id="ret",
        title="Retention",
        source_filename="LSPU Student Handbook.pdf",
        chunk_index=0,
        text=(
            "A student who fails 75% of the total number of academic units enrolled "
            "in a semester shall be dismissed from the university."
        ),
        relevance_score=0.9,
        metadata={"section": "Dismissal", "source_filename": "LSPU Student Handbook.pdf"},
    )
    answer = format_conversational_fallback("What is the dismissal policy?", [chunk])
    assert "dismissed" in answer.casefold()
    assert "I found information under" not in answer
    assert "Open the cited source" not in answer
    assert "See the cited source" not in answer
    assert not answer.casefold().startswith("based on")


def test_policy_fallback_skips_unrelated_charter_overview_for_any_definition():
    """Offline answers must not dump charter Overview boilerplate for handbook FAQs."""
    overview = RetrievedChunk(
        document_id="cc",
        title="Research Program/Project Implementation of LSPU Funded",
        source_filename="charter.pdf",
        chunk_index=0,
        text=(
            "Overview\n"
            "This service provides assistance for Research Program/Project Implementation of LSPU Funded.\n"
            "Office / Division Not specified\n"
            "Who May Avail Not specified"
        ),
        relevance_score=0.95,
        metadata={
            "article_type": "service_procedure",
            "document_type": "citizen_charter",
            "source_section": "Research Program/Project Implementation of LSPU Funded",
        },
    )
    vision = RetrievedChunk(
        document_id="hb",
        title="VISION",
        source_filename="LSPU Student Handbook.pdf",
        chunk_index=1,
        text=(
            "VISION\n"
            "LSPU as a center of technology-mediated instruction and innovation "
            "in agriculture and other disciplines."
        ),
        relevance_score=0.8,
        metadata={
            "section": "VISION",
            "source_section": "VISION",
            "document_type": "student_handbook",
        },
    )
    answer = format_conversational_fallback(
        "What is LSPU's vision?",
        [overview, vision],
    )
    assert "center of technology" in answer.casefold() or "vision" in answer.casefold()
    assert "this service provides assistance" not in answer.casefold()
    assert "research program" not in answer.casefold()


def test_office_fallback_ranks_by_topic_overlap_not_hardcoded_service():
    board = RetrievedChunk(
        document_id="a",
        title="III. OFFICE OF THE UNIVERSITY BOARD SECRETARY",
        source_filename="charter.pdf",
        chunk_index=0,
        text="Office / Division: Office of the University Board Secretary",
        relevance_score=0.9,
        metadata={
            "article_type": "service_procedure",
            "source_section": "III. OFFICE OF THE UNIVERSITY BOARD SECRETARY",
            "office": "Office of the University Board Secretary",
        },
    )
    enrollment = RetrievedChunk(
        document_id="b",
        title="Enrollment",
        source_filename="charter.pdf",
        chunk_index=1,
        text="Office / Division: Office of the Registrar",
        relevance_score=0.7,
        metadata={
            "article_type": "service_procedure",
            "source_section": "Enrollment",
            "office": "Office of the Registrar",
        },
    )
    answer = format_conversational_fallback(
        "Which office handles that regarding How do I enroll at LSPU?",
        [board, enrollment],
    )
    assert "registrar" in answer.casefold()
    assert "board secretary" not in answer.casefold()

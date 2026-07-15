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

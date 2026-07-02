"""Generate student-facing answers from retrieved knowledge-base chunks."""

from __future__ import annotations

from app.config import settings
from app.services.chroma_store import RetrievedChunk


def generate_answer(question: str, contexts: list[RetrievedChunk]) -> str:
    if not contexts:
        return (
            "I could not find relevant information in the knowledge base for your question. "
            "Please contact the support office or try rephrasing your question."
        )

    if settings.openai_api_key:
        return _generate_with_openai(question, contexts)

    return _generate_extractive_answer(question, contexts)


def _generate_extractive_answer(question: str, contexts: list[RetrievedChunk]) -> str:
    """Template-based answer when no LLM API key is configured."""
    lines = [
        "Based on official institutional documents in the knowledge base:",
        "",
    ]
    for i, ctx in enumerate(contexts[:3], start=1):
        lines.append(f"{i}. **{ctx.title}** — {ctx.text.strip()}")
        lines.append("")

    lines.append(f"In summary, regarding your question — *{question.strip()}* — ")
    lines.append(
        "the policies and procedures above are the most relevant references. "
        "For case-specific guidance, submit a support ticket."
    )
    return "\n".join(lines)


def _generate_with_openai(question: str, contexts: list[RetrievedChunk]) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install openai package to use LLM answers.") from exc

    context_block = "\n\n---\n\n".join(
        f"[{c.title} | chunk {c.chunk_index}]\n{c.text}" for c in contexts
    )
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are ASKa-Piyu, a university student support assistant. "
                    "Answer only using the provided institutional document excerpts. "
                    "If the excerpts do not contain the answer, say so clearly."
                ),
            },
            {
                "role": "user",
                "content": f"Context:\n{context_block}\n\nQuestion: {question}",
            },
        ],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()

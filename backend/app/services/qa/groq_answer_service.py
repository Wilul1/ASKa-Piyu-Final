"""Groq-backed answer generation for the production ASKa-Piyu QA endpoint."""

from __future__ import annotations

import logging
import re

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


ASKA_PIYU_SYSTEM_PROMPT = """
You are ASKa-Piyu, an LSPU student support assistant.
Use ONLY the retrieved context provided by the system.
Never invent policies, requirements, offices, programs, campuses, dates, amounts, or procedures.
Be concise, helpful, student-friendly, and grounded in the handbook.
Answer the question directly first, then add brief explanation only when useful.
If a retrieved title, path, or content provides policy rules, conditions, standards, thresholds, consequences, or procedures related to the question, answer using those details.
If the handbook does not directly define a term, say that briefly, then summarize what the related policy section says.
Do not say the context lacks a direct definition when the policy section clearly explains the concept through rules, conditions, standards, or procedures.
You may give a short plain-language explanation as long as every factual detail is grounded in the retrieved context.
Do not start every answer with phrases like "Based on the handbook" or "In simple terms"; use them only when they genuinely improve clarity.
Prefer bullet points for rules, requirements, steps, lists, thresholds, conditions, or consequences.
Say the indexed documents do not contain enough information only when the retrieved context is truly unrelated or lacks policy details that answer the question.
For procedure questions such as how, steps, process, or requirements, produce numbered steps.
For program, office, service, scholarship, or campus questions, clearly separate items by category, college, office, or source section when possible.
Do not include "Source:" or "Sources:" lines in the answer text; sources are returned separately by the API.
""".strip()


BROAD_ANSWER_INSTRUCTIONS = """
Broad/list-style or collection question mode:
- Produce a structured summary grouped by category, college, office, service area, or source section when possible.
- For program collections, format the answer as College Name, then bullet the programs under that college. Never flatten all programs into one list.
- Be concise but complete across the retrieved context.
- Deduplicate repeated items.
- Do not invent missing programs, offices, services, scholarships, requirements, campuses, dates, or procedures.
- If the retrieved context appears partial, say the handbook may not contain the full list.
- Keep sources out of the answer text; the API returns them separately.
""".strip()


class GroqAnswerError(RuntimeError):
    pass


def generate_groq_answer(*, question: str, context: str, broad_mode: bool = False) -> str:
    if not settings.groq_api_key:
        raise GroqAnswerError("Groq API key is not configured.")

    messages = build_groq_messages(question=question, context=context, broad_mode=broad_mode)
    logger.debug("Groq QA context for question %r:\n%s", question.strip(), context)
    logger.debug("Groq QA final messages for question %r: %r", question.strip(), messages)

    try:
        with httpx.Client(timeout=settings.groq_timeout_seconds) as client:
            response = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.groq_model,
                    "temperature": 0.1,
                    "messages": messages,
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise GroqAnswerError("Groq answer generation timed out.") from exc
    except httpx.HTTPError as exc:
        raise GroqAnswerError(f"Groq answer generation failed: {exc}") from exc

    try:
        payload = response.json()
        answer = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GroqAnswerError("Groq returned an unexpected response.") from exc

    cleaned = format_groq_answer(answer)
    if not cleaned:
        raise GroqAnswerError("Groq returned an empty answer.")
    return cleaned


def format_groq_answer(answer: str) -> str:
    cleaned_lines: list[str] = []
    for line in str(answer or "").splitlines():
        if re.match(r"^\s*sources?\s*:", line, flags=re.I):
            continue
        cleaned_lines.append(line.rstrip())
    cleaned = "\n".join(cleaned_lines).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def build_groq_messages(*, question: str, context: str, broad_mode: bool = False) -> list[dict[str, str]]:
    system_prompt = ASKA_PIYU_SYSTEM_PROMPT
    if broad_mode:
        system_prompt = f"{system_prompt}\n\n{BROAD_ANSWER_INSTRUCTIONS}"
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": _build_user_prompt(question=question, context=context, broad_mode=broad_mode),
        },
    ]


def _build_user_prompt(*, question: str, context: str, broad_mode: bool = False) -> str:
    broad_check = ""
    if broad_mode:
        broad_check = (
            "- This is a broad/list-style question. Group the answer by category, college, office, or source section when possible.\n"
            "- If the context contains PROGRAM_COLLECTION outline blocks, preserve each College heading and list only its programs underneath.\n"
            "- Use all relevant retrieved chunks, remove duplicates, and avoid inventing items not present in context.\n"
            "- If only a partial list is supported by the context, state that briefly.\n"
        )
    return (
        "Retrieved context:\n\n"
        f"{context}\n\n"
        "Answering check:\n"
        "- First identify whether any retrieved Title, Path, or Content directly matches the question intent.\n"
        "- Treat related policy rules, conditions, standards, thresholds, consequences, and procedures as enough context to answer.\n"
        "- Answer directly first; keep the answer short unless the question asks for details.\n"
        "- If the section explains the concept through policy details, give a short student-friendly explanation grounded in those details.\n"
        "- If there is no direct definition, say that briefly and then summarize the related policy rules.\n"
        "- Do not say there is no direct definition when the retrieved policy details already explain the concept.\n"
        "- Use bullet points for thresholds, requirements, procedures, and lists.\n"
        f"{broad_check}"
        "- Do not include Source or Sources lines in the answer text.\n"
        "- Use the insufficient-information response only when no retrieved policy details answer the question.\n\n"
        f"Question: {question.strip()}"
    )

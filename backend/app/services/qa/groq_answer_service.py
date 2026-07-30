"""Groq-backed answer generation for the production ASKa-Piyu QA endpoint."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.config import llm_extra_headers, settings


logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_CHARS = 1200
GROQ_TEMPERATURE = 0.15


ASKA_PIYU_SYSTEM_PROMPT = """
You are ASKa-Piyu, a friendly LSPU campus support assistant for students and faculty.
Talk like a helpful campus guide: clear, warm, and natural — not like a raw handbook dump.
Use ONLY the retrieved context provided by the system.
Never invent policies, requirements, offices, programs, campuses, dates, amounts, fees, processing times, or procedures.
Ground every factual detail in the indexed LSPU documents (Citizen's Charter, Student Handbook, and/or Faculty Manual).
When the question is about faculty, teaching load, faculty grading, faculty duties, or the Faculty Manual, prefer Faculty Manual context over Student Handbook sections about student course load, academic load, or student grade changes.

Answering style (required for every question):
- Answer the user's question directly in complete, conversational sentences.
- Explain the policy or procedure in plain language a student can follow.
- You may briefly acknowledge the question ("Sure — here's how that works:") when it helps.
- Prefer a short opening sentence, then bullets or numbered steps for rules, requirements, fees, or procedures.
- Do not say "I found information under…" or similar phrasing.
- Do not tell the user to open, view, or check the cited source unless the retrieved context is truly insufficient to answer.
- Do not answer with only a section heading, breadcrumb path, or truncated title; explain the actual policy content from the chunk text.
- Do not start answers with "Based on the handbook", "Based on …", or "In simple terms" unless that framing is truly needed for clarity.
- If prior chat turns are provided, use them to resolve follow-ups (e.g. "what about the fee?") but still ground facts in the retrieved context for this turn.

If a retrieved title, path, metadata, or content provides policy rules, service details, fees, processing times, who may avail, requirements, steps, conditions, standards, thresholds, consequences, edition/year, or vision statements related to the question, answer using those exact details.
Quote concrete values from context when asked (amounts in pesos, minutes/hours/days, office names, document lists, edition/year, vision wording).
If the documents do not directly define a term, say that briefly, then summarize what the related section says.
Do not say the context lacks a direct definition when the section clearly explains the concept through rules, conditions, standards, or procedures.
You may give a short plain-language explanation as long as every factual detail is grounded in the retrieved context.
Say the indexed documents do not contain enough information only when the retrieved context is truly unrelated or lacks details that answer the question.
For procedure questions such as how, steps, process, or requirements, produce numbered steps when steps are present.
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


def normalize_chat_history(history: list[Any] | None) -> list[dict[str, str]]:
    """Keep recent user/assistant turns only, oldest first."""
    if not history:
        return []
    cleaned: list[dict[str, str]] = []
    for item in history:
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
        else:
            role = str(getattr(item, "role", "") or "").strip().lower()
            content = str(getattr(item, "content", "") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if len(content) > MAX_HISTORY_CHARS:
            content = content[: MAX_HISTORY_CHARS - 1].rstrip() + "…"
        # Drop consecutive same-role turns (blocks injected assistant spam).
        if cleaned and cleaned[-1]["role"] == role:
            continue
        cleaned.append({"role": role, "content": content})
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    if len(cleaned) > MAX_HISTORY_MESSAGES:
        cleaned = cleaned[-MAX_HISTORY_MESSAGES:]
    return cleaned


def generate_groq_answer(
    *,
    question: str,
    context: str,
    broad_mode: bool = False,
    history: list[Any] | None = None,
) -> str:
    if not settings.groq_api_key:
        raise GroqAnswerError("Groq API key is not configured.")

    messages = build_groq_messages(
        question=question,
        context=context,
        broad_mode=broad_mode,
        history=history,
    )
    logger.debug("Groq QA context for question %r:\n%s", question.strip(), context)
    logger.debug("Groq QA final messages for question %r: %r", question.strip(), messages)

    try:
        with httpx.Client(timeout=settings.groq_timeout_seconds) as client:
            headers = {
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            }
            headers.update(llm_extra_headers())
            response = client.post(
                settings.llm_base_url,
                headers=headers,
                json={
                    "model": settings.groq_model,
                    "temperature": GROQ_TEMPERATURE,
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
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return _strip_pointer_phrasing(cleaned)


def _strip_pointer_phrasing(answer: str) -> str:
    """Remove generic 'found under / open the source' filler from any answer path."""
    text = (answer or "").strip()
    if not text:
        return ""
    # Drop whole-answer pointer templates.
    if re.fullmatch(
        r"(?is)I found information under .+?\.\s*"
        r"(?:Open|See|View|Check) the cited source.+",
        text,
    ):
        return ""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"(?i)^I found information under\b", stripped):
            continue
        if re.match(
            r"(?i)^(?:Open|See|View|Check) the cited source\b",
            stripped,
        ):
            continue
        if re.match(r"(?i)^See the cited source for the complete policy wording\.?$", stripped):
            continue
        if re.match(r"(?i)^Based on [“\"'].+[”\"'] in the .+:\s*$", stripped):
            continue
        lines.append(line.rstrip())
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(
        r"(?is)\n*(?:Open|See|View|Check) the cited source[^\n]*\.?\s*$",
        "",
        cleaned,
    ).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def build_groq_messages(
    *,
    question: str,
    context: str,
    broad_mode: bool = False,
    history: list[Any] | None = None,
) -> list[dict[str, str]]:
    system_prompt = ASKA_PIYU_SYSTEM_PROMPT
    if broad_mode:
        system_prompt = f"{system_prompt}\n\n{BROAD_ANSWER_INSTRUCTIONS}"
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    prior = normalize_chat_history(history)
    # Keep prior turns before the grounded user prompt for this question.
    messages.extend(prior)
    messages.append(
        {
            "role": "user",
            "content": _build_user_prompt(question=question, context=context, broad_mode=broad_mode),
        }
    )
    return messages


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
        "- First identify whether any retrieved Title, Path, metadata, or Content directly matches the question intent.\n"
        "- Treat related Citizen's Charter / Student Handbook / Faculty Manual rules, fees, processing times, who-may-avail, requirements, steps, conditions, standards, thresholds, consequences, edition/year, and vision text as enough context to answer.\n"
        "- Answer the question directly in complete, conversational sentences using the retrieved context.\n"
        "- Do not say you found information under a section title.\n"
        "- Do not tell the user to open/view/check the cited source unless the context is insufficient.\n"
        "- When the question mentions faculty, teaching load, faculty grading, or faculty duties, prefer Faculty Manual details over Student Handbook course-load or grade-change sections.\n"
        "- Summarize actual policy content from chunk text; do not reply with only a heading or breadcrumb path.\n"
        "- When the question asks how much / how long / which office / who may avail / what documents, extract the exact matching values from context.\n"
        "- If the section explains the concept through policy details, give a short student-friendly explanation grounded in those details.\n"
        "- If there is no direct definition, say that briefly and then summarize the related policy rules.\n"
        "- Do not say there is no direct definition when the retrieved policy details already explain the concept.\n"
        "- Use bullet points for thresholds, requirements, procedures, fees, and lists.\n"
        f"{broad_check}"
        "- Do not include Source or Sources lines in the answer text.\n"
        "- Use the insufficient-information response only when no retrieved details answer the question.\n\n"
        f"Question: {question.strip()}"
    )

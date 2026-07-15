"""Conversational answers when the LLM is unavailable but retrieval succeeded.

Answers are built only from retrieved chunk text/metadata — never hardcoded
officials or handbook facts.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from app.services.chroma_store import RetrievedChunk
from app.services.qa.service_answer_formatter import (
    format_service_procedure_answer,
    is_artifact_or_requirement_form_chunk,
    is_service_howto_query,
    is_service_procedure_chunk,
)

logger = logging.getLogger(__name__)

FallbackIntent = Literal["person", "service", "policy", "clarification"]

_POSITION_TOKENS = (
    "university president",
    "vice president",
    "campus director",
    "dean",
    "director",
    "registrar",
    "chancellor",
    "board of regents",
    "secretary",
    "treasurer",
    "officer",
)
_PERSON_QUERY = re.compile(
    r"\b(?:who\s+is|who\s+are|who's|whos|name\s+of|list\s+of|"
    r"administrative\s+officials?|university\s+officials?|"
    r"president|vice\s+president|vp\s+for|dean|director)\b",
    re.I,
)
_LIST_QUERY = re.compile(
    r"\b(?:who\s+are|list|all|full\s+list|administrative\s+officials?|"
    r"university\s+officials?|officials)\b",
    re.I,
)
_POLICY_QUERY = re.compile(
    r"\b(?:policy|policies|rule|rules|allowed|prohibited|required|"
    r"guideline|regulation|retention|dismissal|probation|"
    r"what\s+happens\s+if|may\s+i|can\s+i|is\s+it\s+allowed)\b",
    re.I,
)
_VAGUE_QUERY = re.compile(
    r"^(?:what(?:'s|\s+is)?\s+this|tell\s+me\s+more|info|information|"
    r"help|officials?|about\s+this|details?)\??$",
    re.I,
)
_PRESIDENT_QUERY = re.compile(r"\b(?:university\s+)?president\b", re.I)
_VP_QUERY = re.compile(
    r"\b(?:vice\s+president|vp)\b.*\b(academic|administration|research|extension|finance)\b|"
    r"\b(academic|administration|research|extension|finance).*\b(?:vice\s+president|vp)\b",
    re.I,
)


def detect_fallback_intent(question: str, chunks: list[RetrievedChunk] | None = None) -> FallbackIntent:
    text = (question or "").strip()
    if not text:
        return "clarification"
    if is_service_howto_query(text):
        return "service"
    if _POLICY_QUERY.search(text) and not _PERSON_QUERY.search(text):
        return "policy"
    if _PERSON_QUERY.search(text):
        return "person"
    if _VAGUE_QUERY.match(text):
        return "clarification"
    # If top chunk looks like a service procedure and question is process-ish, prefer service.
    if chunks:
        top = chunks[0]
        if is_service_procedure_chunk(top) and not is_artifact_or_requirement_form_chunk(top):
            if re.search(r"\b(?:how|step|process|avail|apply|request|validate)\b", text, re.I):
                return "service"
    if len(text.split()) <= 4 and not re.search(r"[.?]", text):
        return "clarification"
    return "policy"


def format_conversational_fallback(
    question: str,
    chunks: list[RetrievedChunk],
    sources: list[dict[str, Any]] | None = None,
    *,
    confidence: str = "medium",
) -> str:
    """Build a student-facing answer from retrieved chunks without LLM copy."""
    usable = [
        chunk
        for chunk in chunks
        if chunk and (chunk.text or "").strip() and not is_artifact_or_requirement_form_chunk(chunk)
    ]
    if not usable:
        usable = [chunk for chunk in chunks if chunk and (chunk.text or "").strip()]
    if not usable:
        return ""

    intent = detect_fallback_intent(question, usable)
    logger.debug("Conversational fallback intent=%s question=%r", intent, question)

    if intent == "service":
        for chunk in usable:
            if is_service_procedure_chunk(chunk) and not is_artifact_or_requirement_form_chunk(chunk):
                answer = format_service_procedure_answer(chunk, sources, busy_fallback=False)
                return _maybe_low_confidence_preface(answer, confidence)

    if intent == "person":
        answer = _format_person_answer(question, usable, sources)
        if answer:
            return _maybe_low_confidence_preface(answer, confidence)

    if intent == "clarification":
        answer = _format_clarification(question, usable)
        if answer:
            return answer

    # Policy / default short explanation.
    answer = _format_policy_answer(question, usable, sources)
    return _maybe_low_confidence_preface(answer, confidence)


def parse_officials_from_text(text: str) -> list[tuple[str, str]]:
    """Extract (name, position) pairs from an Administrative Officials-like passage."""
    if not text or not text.strip():
        return []

    cleaned = _normalize_officials_text(text)
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Pattern: Name — Position / Name - Position
    for match in re.finditer(
        r"(?im)^\s*((?:Dr\.?|Atty\.?|Engr?\.?|Prof\.?|Mr\.?|Ms\.?|Mrs\.?)?\s*"
        r"[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,5})"
        r"\s*[—\-:|]\s*"
        r"([A-Za-z][A-Za-z /,&()\-]{3,80})\s*$",
        cleaned,
    ):
        name = _clean_name(match.group(1))
        position = _clean_position(match.group(2))
        key = f"{name}|{position}".casefold()
        if name and position and key not in seen:
            pairs.append((name, position))
            seen.add(key)

    # Pattern: NAME Title Words (all-caps name then title case / words)
    for match in re.finditer(
        r"(?m)\b((?:DR\.?|ATTY\.?|ENG(?:R)?\.?|PROF\.?|MR\.?|MS\.?|MRS\.?)?\s*"
        r"[A-Z][A-Z.'\-]+(?:\s+[A-Z][A-Z.'\-]+){1,5})\s+"
        r"((?:University\s+)?President|"
        r"Vice\s+President(?:\s+for\s+[A-Za-z ]+)?|"
        r"Campus\s+Director|"
        r"Dean(?:\s+of\s+[A-Za-z ]+)?|"
        r"Director(?:\s+of\s+[A-Za-z ]+)?|"
        r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,6})\b",
        cleaned,
    ):
        name = _clean_name(match.group(1))
        position = _clean_position(match.group(2))
        key = f"{name}|{position}".casefold()
        if name and position and _looks_like_position(position) and key not in seen:
            pairs.append((name, position))
            seen.add(key)

    # Inline: "Dr. X is listed as University President"
    for match in re.finditer(
        r"(?i)\b((?:Dr\.?|Atty\.?|Engr?\.?|Prof\.?)\s+[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,4})"
        r"\s+(?:is\s+listed\s+as|serves\s+as|as)\s+"
        r"([A-Za-z][A-Za-z /,&\-]{3,80})",
        cleaned,
    ):
        name = _clean_name(match.group(1))
        position = _clean_position(match.group(2).rstrip("."))
        key = f"{name}|{position}".casefold()
        if name and position and key not in seen:
            pairs.append((name, position))
            seen.add(key)

    return pairs[:20]


def _format_person_answer(
    question: str,
    chunks: list[RetrievedChunk],
    sources: list[dict[str, Any]] | None,
) -> str:
    chunk = _best_officials_chunk(chunks) or chunks[0]
    title = _section_title(chunk)
    source_label = _handbook_source_label(chunk, sources)
    officials = parse_officials_from_text(chunk.text or "")
    # Also scan sibling chunks for more officials when asking for a list.
    if _LIST_QUERY.search(question) and len(officials) < 2:
        for other in chunks[1:4]:
            for pair in parse_officials_from_text(other.text or ""):
                if pair not in officials:
                    officials.append(pair)

    wants_list = bool(_LIST_QUERY.search(question)) and not (
        _PRESIDENT_QUERY.search(question) and not re.search(r"\bwho\s+are\b", question, re.I)
    )
    # "Who is the university president?" is singular.
    if _PRESIDENT_QUERY.search(question) and not re.search(r"\bwho\s+are\b", question, re.I):
        wants_list = False

    if officials and not wants_list:
        targeted = _select_official_for_question(question, officials)
        if targeted:
            name, position = targeted
            return (
                f"According to the {source_label}, the {position} listed is {name}."
            )

    if officials and wants_list:
        lines = [
            f"Here are the administrative officials listed in the {source_label}:",
            "",
        ]
        limit = 12 if re.search(r"\b(?:all|full\s+list|complete)\b", question, re.I) else 6
        for name, position in officials[:limit]:
            lines.append(f"- {name} — {position}")
        if len(officials) > limit:
            lines.append(f"- …and {len(officials) - limit} more in the cited source.")
        return "\n".join(lines)

    if officials:
        name, position = officials[0]
        return f"According to the {source_label}, the {position} listed is {name}."

    # Low parse confidence: short summary, no dump.
    summary = _short_summary(chunk.text or "", limit=180)
    section = title or "related section"
    if summary:
        return (
            f"I found the “{section}” section in the {source_label}. "
            f"Key detail: {summary} "
            "Open the cited source for the full list of names and positions."
        )
    return (
        f"I found the “{section}” section in the {source_label}. "
        "Open the cited source for the listed names and positions."
    )


def _format_policy_answer(
    question: str,
    chunks: list[RetrievedChunk],
    sources: list[dict[str, Any]] | None,
) -> str:
    chunk = chunks[0]
    title = _section_title(chunk) or "this policy"
    source_label = _handbook_source_label(chunk, sources)
    detail = _short_summary(chunk.text or "", limit=220)
    if not detail:
        return (
            f"I found information under “{title}” in the {source_label}. "
            "Open the cited source for the full policy details."
        )
    return (
        f"Based on “{title}” in the {source_label}:\n\n"
        f"{detail}\n\n"
        "See the cited source for the complete policy wording."
    )


def _format_clarification(question: str, chunks: list[RetrievedChunk]) -> str:
    titles = []
    for chunk in chunks[:3]:
        title = _section_title(chunk)
        if title and title not in titles:
            titles.append(title)
    topic = titles[0] if titles else "that topic"
    if any("official" in t.casefold() for t in titles) or "official" in (question or "").casefold():
        return (
            "I found information related to administrative officials. "
            "Are you asking for the University President, the Vice Presidents, "
            "or the full list of officials?"
        )
    options = ", ".join(f"“{t}”" for t in titles[:3]) if titles else f"“{topic}”"
    return (
        f"I found related handbook material ({options}). "
        "Could you tell me which part you need — a specific person, a policy rule, "
        "or steps for a campus service?"
    )


def _select_official_for_question(
    question: str,
    officials: list[tuple[str, str]],
) -> tuple[str, str] | None:
    q = question.casefold()
    if _PRESIDENT_QUERY.search(question) and "vice" not in q:
        for name, position in officials:
            if "president" in position.casefold() and "vice" not in position.casefold():
                return name, position
    vp = _VP_QUERY.search(question)
    if vp:
        focus = (vp.group(1) or vp.group(2) or "").casefold()
        for name, position in officials:
            pos = position.casefold()
            if "vice" in pos and focus and focus in pos:
                return name, position
        for name, position in officials:
            if "vice" in position.casefold():
                return name, position
    # Fuzzy: any position word from the question
    for name, position in officials:
        pos_tokens = [t for t in re.split(r"\W+", position.casefold()) if len(t) > 3]
        if pos_tokens and sum(1 for t in pos_tokens if t in q) >= min(2, len(pos_tokens)):
            return name, position
    return None


def _best_officials_chunk(chunks: list[RetrievedChunk]) -> RetrievedChunk | None:
    for chunk in chunks:
        title = _section_title(chunk).casefold()
        text = (chunk.text or "").casefold()
        if "administrative official" in title or "university official" in title:
            return chunk
        if "university president" in text or "administrative official" in text:
            return chunk
    return None


def _normalize_officials_text(text: str) -> str:
    # Collapse OCR noise and repeated section titles.
    lines: list[str] = []
    seen_titles = 0
    for raw in text.replace("\r", "\n").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if re.fullmatch(r"(?i)administrative\s+officials?", line):
            seen_titles += 1
            if seen_titles > 1:
                continue
        lines.append(line)
    joined = "\n".join(lines)
    # Split glued "BRIONES University President" style when already on one line —
    # leave as-is; regex handles it.
    return joined


def _clean_name(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip(" -—|:"))
    if not text:
        return ""
    # Title-case all-caps names while keeping Dr./Engr. prefixes.
    if text.isupper() or sum(1 for c in text if c.isupper()) > len(text) * 0.6:
        parts = text.split()
        fixed: list[str] = []
        for part in parts:
            if re.fullmatch(r"(?i)dr\.?|atty\.?|engr?\.?|prof\.?|mr\.?|ms\.?|mrs\.?", part):
                token = part if part.endswith(".") else f"{part.rstrip('.').title()}."
                # Normalize Engr.
                if token.lower().startswith("eng"):
                    token = "Engr."
                elif token.lower().startswith("dr"):
                    token = "Dr."
                elif token.lower().startswith("atty"):
                    token = "Atty."
                elif token.lower().startswith("prof"):
                    token = "Prof."
                fixed.append(token)
            else:
                fixed.append(part.title() if part.isupper() or part.islower() else part)
        text = " ".join(fixed)
    return text


def _clean_position(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip(" -—|:."))
    text = re.sub(r"\s+", " ", text)
    return text


def _looks_like_position(value: str) -> bool:
    lowered = value.casefold()
    if any(token in lowered for token in _POSITION_TOKENS):
        return True
    return bool(re.search(r"\b(?:president|director|dean|vice)\b", lowered))


def _section_title(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    for key in ("source_section", "canonical_topic", "section", "article", "title"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return (chunk.title or "").strip()


def _handbook_source_label(
    chunk: RetrievedChunk,
    sources: list[dict[str, Any]] | None,
) -> str:
    metadata = chunk.metadata or {}
    filename = str(
        metadata.get("source_filename")
        or metadata.get("source_document")
        or chunk.source_filename
        or ""
    ).strip()
    if filename:
        stem = re.sub(r"\.pdf$", "", filename, flags=re.I)
        if "handbook" in stem.casefold() or "lspu" in stem.casefold():
            return "LSPU Student Handbook"
        return stem
    if sources:
        label = str(sources[0].get("source_label") or sources[0].get("title") or "").strip()
        if label:
            if "handbook" in label.casefold():
                return "LSPU Student Handbook"
            return label
    return "LSPU Student Handbook"


def _short_summary(text: str, *, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    # Drop leading repeated title lines.
    cleaned = re.sub(r"(?i)^(administrative\s+officials\s*)+", "", cleaned).strip()
    if not cleaned:
        return ""
    # Prefer first sentence-like span.
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    summary = parts[0] if parts else cleaned
    if len(summary) < 40 and len(parts) > 1:
        summary = f"{parts[0]} {parts[1]}".strip()
    if len(summary) > limit:
        trimmed = summary[: limit - 1].rsplit(" ", 1)[0]
        summary = f"{trimmed}…"
    return summary


def _maybe_low_confidence_preface(answer: str, confidence: str) -> str:
    if confidence != "low" or not answer:
        return answer
    preface = (
        "I found a related section, but it may not fully answer your question.\n\n"
    )
    if "submit a ticket" in answer.casefold():
        return preface + answer
    return (
        preface
        + answer
        + "\n\nIf this does not match what you need, you can submit a support ticket."
    )

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
    format_requirements_detail_answer,
    format_service_procedure_answer,
    is_artifact_or_requirement_form_chunk,
    is_factual_service_detail_query,
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
    # Office/fee/time FAQs must not fall into the step-dump "service" path.
    if is_factual_service_detail_query(text):
        return "policy"
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
            if re.search(r"\b(?:how do|how can|how to|steps to|procedure for)\b", text, re.I):
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

    if is_factual_service_detail_query(question):
        office_answer = _format_office_or_detail_answer(question, usable, sources)
        if office_answer:
            return _maybe_low_confidence_preface(_sanitize_direct_answer(office_answer), confidence)

    if intent == "service":
        for chunk in usable:
            if is_service_procedure_chunk(chunk) and not is_artifact_or_requirement_form_chunk(chunk):
                answer = format_service_procedure_answer(chunk, sources, busy_fallback=False)
                return _maybe_low_confidence_preface(_sanitize_direct_answer(answer), confidence)

    if intent == "person":
        answer = _format_person_answer(question, usable, sources)
        if answer:
            return _maybe_low_confidence_preface(_sanitize_direct_answer(answer), confidence)

    if intent == "clarification":
        answer = _format_clarification(question, usable)
        if answer:
            return _sanitize_direct_answer(answer)

    # Policy / default short explanation.
    answer = _format_policy_answer(question, usable, sources)
    return _maybe_low_confidence_preface(_sanitize_direct_answer(answer), confidence)


def _sanitize_direct_answer(answer: str) -> str:
    from app.services.qa.groq_answer_service import _strip_pointer_phrasing

    return _strip_pointer_phrasing(answer)


def _format_office_or_detail_answer(
    question: str,
    chunks: list[RetrievedChunk],
    sources: list[dict[str, Any]] | None,
) -> str:
    """Short factual answer from metadata/text when Groq is unavailable."""
    normalized = re.sub(r"\s+", " ", (question or "").casefold()).strip()
    ranked = sorted(
        chunks,
        key=lambda chunk: _office_detail_rank(chunk, normalized),
    )
    chunk = ranked[0]
    metadata = chunk.metadata or {}
    office = str(
        metadata.get("office")
        or metadata.get("responsible_office")
        or metadata.get("office_or_division")
        or ""
    ).strip()
    if not office:
        match = re.search(
            r"(?im)^(?:Office\s*/\s*Division|Office)\s*[:\-]?\s*(.+)$",
            chunk.text or "",
        )
        if match:
            office = match.group(1).strip()
    title = str(
        metadata.get("source_section")
        or metadata.get("canonical_topic")
        or metadata.get("title")
        or chunk.title
        or "this service"
    ).strip()
    source_label = _handbook_source_label(chunk, sources)

    asks_fee = bool(re.search(r"\b(?:how much|fee|fees|cost)\b", normalized))
    asks_office = bool(
        re.search(r"\b(?:which office|what office|who handles|responsible|in charge)\b", normalized)
    )

    if re.search(r"\b(?:who may|who can avail|who can)\b", normalized):
        who = str(metadata.get("who_may_avail") or "").strip()
        if not who:
            match = re.search(
                r"(?im)^(?:Who May Avail(?: of the Service)?|Clientele)\s*[:\-]?\s*(.+)$",
                chunk.text or "",
            )
            if match:
                who = match.group(1).strip()
        if who:
            return f"{who} may avail of {title}, according to the {source_label}."
    if re.search(r"\b(?:how long|processing time)\b", normalized):
        time_value = str(metadata.get("total_processing_time") or "").strip()
        if not time_value:
            match = re.search(r"(?im)^Total Processing Time\s*[:\-]?\s*(.+)$", chunk.text or "")
            if match:
                time_value = match.group(1).strip()
        if time_value:
            return f"The total processing time for {title} is {time_value} ({source_label})."

    fee = ""
    if asks_fee:
        raw_fee = str(metadata.get("total_fees") or metadata.get("fees") or "").strip()
        if not raw_fee:
            match = re.search(r"(?im)^(?:Fees|Fee|Total Fees)\s*[:\-]?\s*(.+)$", chunk.text or "")
            if match:
                raw_fee = match.group(1).strip()
        from app.services.qa.question_answering import _fee_usable_for_question, _fee_answer_title

        fee = _fee_usable_for_question(raw_fee, title, normalized) or ""

    if asks_fee and asks_office and fee:
        answer_title = _fee_answer_title(title, fee, normalized)
        if office:
            return (
                f"For {answer_title}, the listed fee is {fee}. "
                f"The responsible office is {office}, according to the {source_label}."
            )
        return f"The listed fee for {answer_title} is {fee} ({source_label})."
    if asks_fee and fee:
        answer_title = _fee_answer_title(title, fee, normalized)
        return f"The listed fee for {answer_title} is {fee} ({source_label})."
    if asks_office and office and not asks_fee:
        return (
            f"The office responsible for {title} is {office}, "
            f"according to the {source_label}."
        )
    if re.search(
        r"\b(?:what documents|what additional|what must|documents? (?:are )?required|"
        r"requirements? (?:for|from|needed)|what (?:are|is) the (?:requirement|requirements|document|documents))\b",
        normalized,
    ):
        for candidate in ranked:
            answer = format_requirements_detail_answer(question, candidate, sources)
            if answer:
                return answer
    # Do not invent an office answer for unrelated factual questions.
    return ""


def _office_detail_rank(chunk: RetrievedChunk, normalized_question: str) -> tuple[int, int, float]:
    """Lower tuple is better — prefer title/topic overlap with the asked subject."""
    title = " ".join(
        str(value or "")
        for value in (
            (chunk.metadata or {}).get("source_section"),
            (chunk.metadata or {}).get("canonical_topic"),
            (chunk.metadata or {}).get("title"),
            chunk.title,
        )
    ).casefold()
    stop = {
        "what", "which", "who", "how", "when", "where", "the", "a", "an", "is", "are",
        "for", "of", "to", "in", "on", "office", "handles", "responsible", "process",
        "service", "regarding", "prior", "question", "context", "that", "this", "it",
    }
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", normalized_question)
        if token not in stop and len(token) >= 3
    }
    overlap = sum(1 for token in tokens if token in title)
    # Demote TOC-style office headings with no topic overlap.
    toc_penalty = 0
    if re.search(r"^\s*(?:[ivx]+\.|[0-9]+\.)\s+office\b", title) and overlap == 0:
        toc_penalty = 4
    score = float(chunk.reranked_score if chunk.reranked_score is not None else chunk.relevance_score or 0.0)
    return (-overlap, toc_penalty, -score)


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
            lines.append(f"- …and {len(officials) - limit} more listed in the retrieved documents.")
        return "\n".join(lines)

    if officials:
        name, position = officials[0]
        return f"According to the {source_label}, the {position} listed is {name}."

    # Low parse confidence: explain from available text, no pointer phrasing.
    summary = _policy_explanation_text(chunk.text or "", title=title or "", limit=220)
    if summary:
        return _ensure_complete_sentences(summary)
    return (
        "The retrieved documents do not list clear official names for that question. "
        "If you need help, you can submit a support ticket."
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
            "Are you asking for the University President, the Vice Presidents, "
            "or the full list of administrative officials?"
        )
    options = ", ".join(f"“{t}”" for t in titles[:3]) if titles else f"“{topic}”"
    return (
        f"I can help with related topics ({options}). "
        "Which part do you need — a specific person, a policy rule, "
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
    label_candidates = [
        filename,
        str(metadata.get("source_label") or ""),
        str(metadata.get("doc_source_label") or ""),
    ]
    if sources:
        label_candidates.append(str(sources[0].get("source_label") or sources[0].get("title") or ""))

    for candidate in label_candidates:
        resolved = _resolve_handbook_display_name(candidate)
        if resolved:
            return resolved

    return "LSPU documents"


def _resolve_handbook_display_name(raw: str) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    stem = re.sub(r"\.pdf$", "", value, flags=re.I)
    stem = stem.replace("_", " ").replace("-", " ").strip()
    lowered = stem.casefold()
    if "faculty manual" in lowered or ("faculty" in lowered and "manual" in lowered):
        return "LSPU Faculty Manual"
    if "student handbook" in lowered:
        return "LSPU Student Handbook"
    if "citizen" in lowered and "charter" in lowered:
        return stem
    if "handbook" in lowered and "faculty" not in lowered:
        return "LSPU Student Handbook"
    return stem or None


def _section_title(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    for key in ("source_section", "canonical_topic", "section", "article", "title"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return _clean_section_title(value)
    return _clean_section_title((chunk.title or "").strip())


def _clean_section_title(value: str) -> str:
    cleaned = (value or "").strip()
    if " > " in cleaned:
        parts = [part.strip() for part in cleaned.split(">") if part.strip()]
        if parts:
            cleaned = parts[-1]
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _format_policy_answer(
    question: str,
    chunks: list[RetrievedChunk],
    sources: list[dict[str, Any]] | None,
) -> str:
    """Answer directly from retrieved policy text; never use pointer-only phrasing."""
    ordered = _ordered_policy_chunks(question, chunks)
    explanation = ""
    for candidate in ordered[:5]:
        title = _section_title(candidate) or ""
        detail = _policy_explanation_text(candidate.text or "", title=title, limit=420)
        if detail and not _looks_like_heading_only_detail(detail, title):
            explanation = detail
            break

    if explanation:
        return _ensure_complete_sentences(explanation)

    return (
        "The retrieved documents do not contain enough detail to answer that question completely. "
        "If you need help, you can submit a support ticket."
    )


def _ordered_policy_chunks(question: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    best = _best_policy_chunk(question, chunks)
    if not best:
        return list(chunks)
    ordered = [best]
    for chunk in chunks:
        if chunk is not best and chunk not in ordered:
            ordered.append(chunk)
    return ordered


def _policy_explanation_text(text: str, *, title: str = "", limit: int = 420) -> str:
    cleaned = _strip_breadcrumb_noise(text)
    cleaned = _strip_charter_overview_boilerplate(cleaned)
    if title:
        # Drop a leading repeated title line.
        cleaned = re.sub(
            rf"(?is)^\s*{re.escape(title)}\s*[:.\-]?\s*",
            "",
            cleaned,
        ).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    usable: list[str] = []
    total = 0
    for part in parts:
        sentence = part.strip()
        if not sentence:
            continue
        if _looks_like_heading_only_detail(sentence, title):
            continue
        if _is_charter_overview_sentence(sentence):
            continue
        if " > " in sentence and len(sentence) < 120:
            continue
        usable.append(sentence)
        total += len(sentence) + 1
        if total >= limit or len(usable) >= 3:
            break
    summary = " ".join(usable).strip()
    if not summary:
        summary = _short_summary(cleaned, limit=limit)
    if len(summary) > limit:
        trimmed = summary[: limit - 1].rsplit(" ", 1)[0]
        summary = f"{trimmed}…"
    return summary


def _strip_charter_overview_boilerplate(text: str) -> str:
    cleaned = (text or "").replace("\r", "\n")
    lines: list[str] = []
    for raw in cleaned.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if _is_charter_overview_sentence(line):
            continue
        if re.match(r"(?i)^(office\s*/\s*division|who may avail|requirements)\s*:?\s*(not specified)?$", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _is_charter_overview_sentence(sentence: str) -> bool:
    text = re.sub(r"\s+", " ", (sentence or "").strip())
    if not text:
        return True
    if re.match(r"(?i)^overview\b", text):
        return True
    if re.match(r"(?i)^this service provides assistance for\b", text):
        return True
    if re.match(r"(?i)^(not specified|n/?a)\b", text):
        return True
    return False


def _strip_breadcrumb_noise(text: str) -> str:
    cleaned = (text or "").replace("\r", "\n")
    lines: list[str] = []
    for raw in cleaned.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if " > " in line and len(line) < 160 and not re.search(r"[.!?]", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _ensure_complete_sentences(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    if cleaned.endswith(("…", ".", "!", "?")):
        return cleaned
    # Soft wrap incomplete extracts into a readable sentence.
    return f"{cleaned}."


def _best_policy_chunk(
    question: str,
    chunks: list[RetrievedChunk],
) -> RetrievedChunk | None:
    if not chunks:
        return None

    def _score(chunk: RetrievedChunk) -> float:
        meta = chunk.metadata or {}
        blob = " ".join(
            [
                str(meta.get("source_filename") or ""),
                str(meta.get("source_document") or ""),
                str(meta.get("source_section") or ""),
                str(meta.get("title") or ""),
                str(meta.get("section") or ""),
                str(meta.get("canonical_topic") or ""),
                chunk.title or "",
                (chunk.text or "")[:400],
            ]
        ).casefold()
        q = (question or "").casefold()
        score = float(
            chunk.reranked_score
            if chunk.reranked_score is not None
            else chunk.relevance_score or 0.0
        )
        stop = {
            "what", "which", "who", "how", "when", "where", "why", "the", "a", "an",
            "is", "are", "for", "of", "to", "in", "on", "at", "by", "with", "from",
            "about", "that", "this", "it", "lspu", "university", "regarding",
            "prior", "question", "context", "please", "tell",
        }
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", q)
            if token not in stop and len(token) >= 3
        }
        if tokens:
            score += 0.4 * sum(1 for token in tokens if token in blob)
        # Unrelated charter "Overview / This service provides assistance…" dumps
        # should not win definition/policy questions.
        if is_service_procedure_chunk(chunk) and not is_service_howto_query(question):
            first_line = ""
            if chunk.text:
                lines = chunk.text.splitlines()
                first_line = lines[0] if lines else chunk.text[:160]
            if _is_charter_overview_sentence(first_line):
                score -= 0.9
            elif re.search(r"(?i)this service provides assistance for", chunk.text or ""):
                score -= 0.7
            if tokens and not any(token in blob for token in tokens):
                score -= 0.5
        faculty_query = any(
            token in q
            for token in ("faculty", "teaching load", "professor", "instructor", "grading sheets")
        )
        if faculty_query:
            if "faculty manual" in blob:
                score += 0.4
            if "student handbook" in blob:
                score -= 0.25
            if "teaching load" in q and ("course load" in blob or "academic load" in blob):
                score -= 0.35
            if "teaching load" in q and ("teaching load" in blob or "time allotment" in blob):
                score += 0.35
            if "grading" in q and "grading sheets" in blob:
                score += 0.35
            if "grading" in q and "rectification" in blob:
                score -= 0.3
            if "responsibilit" in q and "designated as" in blob:
                score -= 0.35
            if "responsibilit" in q and ("commitment" in blob or "code of ethics" in blob):
                score += 0.35
        return score

    return max(chunks, key=_score)


def _looks_like_heading_only_detail(detail: str, title: str) -> bool:
    cleaned = re.sub(r"\s+", " ", (detail or "").strip())
    if not cleaned:
        return True
    if " > " in cleaned:
        return True
    if title and cleaned.casefold().startswith(title.casefold()) and len(cleaned) < len(title) + 40:
        return True
    return len(cleaned) < 48 and cleaned.count(" ") < 6


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
        "This may only partially answer your question.\n\n"
    )
    if "submit a ticket" in answer.casefold():
        return preface + answer
    return (
        preface
        + answer
        + "\n\nIf this does not match what you need, you can submit a support ticket."
    )

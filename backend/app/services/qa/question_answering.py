"""Production ASKa-Piyu RAG orchestration."""

from __future__ import annotations

import logging
import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.chroma_store import RetrievedChunk, get_knowledge_base_store
from app.services.qa.conversational_fallback import format_conversational_fallback
from app.services.qa.groq_answer_service import GroqAnswerError, generate_groq_answer
from app.services.knowledge_taxonomy import classify_question
from app.services.retrieval_reranker import is_faculty_restricted_query, prepare_retrieval_query
from app.services.qa.service_answer_formatter import (
    format_requirements_detail_answer,
    format_service_procedure_answer,
    is_artifact_or_requirement_form_chunk,
    is_factual_service_detail_query,
    is_form_or_requirement_query,
    is_service_howto_query,
    is_service_procedure_chunk,
    prefer_service_chunks,
)
logger = logging.getLogger(__name__)


class EmptyKnowledgeBaseError(ValueError):
    """Raised when the knowledge base has no indexed chunks to search."""


FINAL_CONTEXT_CHUNKS = 7
RAW_RETRIEVAL_CANDIDATES = 40
DEFAULT_CONTEXT_CHUNKS = 7
FACTUAL_CONTEXT_CHUNKS = 8
BROAD_RETRIEVAL_CANDIDATES = 40
BROAD_CONTEXT_CHUNKS = 15
COLLECTION_CONTEXT_GROUPS = 15
PREVIEW_CHARS = 700
MISSING_INFO_PHRASES = (
    "do not contain enough information",
    "does not contain enough information",
    "do not contain information",
    "does not contain information",
    "not contain enough information",
    "not contain information",
    "do not have enough information",
    "does not have enough information",
    "do not have information",
    "does not have information",
    "could not find",
    "cannot answer",
    "can't answer",
    "no direct information",
    "not mentioned",
    "not provided in the retrieved context",
    "outside the scope",
    "insufficient information",
)
OUT_OF_SCOPE_ANSWER = (
    "The indexed LSPU documents (Citizen's Charter / student handbook) "
    "do not contain enough information about this topic."
)
FACULTY_OUT_OF_SCOPE_ANSWER = (
    "The indexed LSPU Faculty Manual and related documents do not contain "
    "enough information about this topic."
)
# Students/guests must not be told a Faculty Manual exists or which topics it covers.
FACULTY_SIGNIN_ANSWER = OUT_OF_SCOPE_ANSWER


def _out_of_scope_answer_for_role(user_role: str | None) -> str:
    if (user_role or "").strip().lower() == "faculty":
        return FACULTY_OUT_OF_SCOPE_ANSWER
    return OUT_OF_SCOPE_ANSWER


NORMAL_QA = "NORMAL_QA"
DEFINITION_QUESTION = "DEFINITION_QUESTION"
PROCEDURE_QUESTION = "PROCEDURE_QUESTION"
REQUIREMENT_QUESTION = "REQUIREMENT_QUESTION"
OFFICE_SERVICE_QUESTION = "OFFICE_SERVICE_QUESTION"
OUT_OF_SCOPE_QUESTION = "OUT_OF_SCOPE"
GREETING_QUESTION = "GREETING"
GREETING_ANSWER = "Hello! How can I assist you today?"
PROGRAM_COLLECTION = "PROGRAM_COLLECTION"
OFFICE_COLLECTION = "OFFICE_COLLECTION"
SERVICE_COLLECTION = "SERVICE_COLLECTION"
SCHOLARSHIP_COLLECTION = "SCHOLARSHIP_COLLECTION"
REQUIREMENT_COLLECTION = "REQUIREMENT_COLLECTION"
POLICY_COLLECTION = "POLICY_COLLECTION"


@dataclass
class QAResult:
    answer: str
    sources: list[dict[str, Any]]
    confidence: str
    retrieved_chunks: list[dict[str, Any]]
    normalized_query: str = ""
    expanded_query: str = ""
    matched_expansion_rules: list[str] | None = None
    broad_query: bool = False
    broad_query_reason: str | None = None
    selected_context_count: int | None = None
    grouped_context_summary: list[dict[str, Any]] | None = None
    detected_intent: str = NORMAL_QA
    collection_mode: bool = False
    collection_articles: list[str] | None = None
    collection_chunk_count: int | None = None
    group_count: int | None = None
    program_scope: dict[str, Any] | None = None
    ticket_routing: dict[str, Any] | None = None
    query_expansions_used: list[str] | None = None
    rerank_reasons: list[dict[str, Any]] | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    out_of_scope_detected: bool = False


def answer_qa_question(
    question: str,
    *,
    user_role: str | None = None,
    history: list[Any] | None = None,
) -> QAResult:
    cleaned_question = question.strip()
    chat_history = list(history or [])
    # Greetings / thanks are not KB questions — never retrieve or cite sources.
    if is_greeting_query(cleaned_question):
        return QAResult(
            answer=GREETING_ANSWER,
            sources=[],
            confidence="high",
            retrieved_chunks=[],
            normalized_query=_normalize(cleaned_question),
            expanded_query=_normalize(cleaned_question),
            matched_expansion_rules=[],
            broad_query=False,
            broad_query_reason=None,
            selected_context_count=0,
            detected_intent=GREETING_QUESTION,
            collection_mode=False,
            ticket_routing=_ticket_routing_for_question(cleaned_question),
            query_expansions_used=[],
            rerank_reasons=[],
            fallback_used=False,
            fallback_reason="greeting",
            out_of_scope_detected=False,
        )

    retrieval_question = resolve_followup_question(cleaned_question, chat_history)
    prepared_query = prepare_retrieval_query(retrieval_question)
    ticket_routing = _ticket_routing_for_question(cleaned_question)
    qa_intent = detect_question_intent(cleaned_question)
    out_of_scope = qa_intent == OUT_OF_SCOPE_QUESTION
    collection_intent = detect_collection_intent(retrieval_question)
    collection_mode = collection_intent != NORMAL_QA
    detected_intent = collection_intent if collection_mode else qa_intent
    broad_query, broad_reason = detect_broad_query(retrieval_question)
    broad_query = broad_query or collection_mode
    if collection_mode and broad_reason is None:
        broad_reason = collection_intent.lower()
    store = get_knowledge_base_store()
    if store.chunk_count == 0:
        raise EmptyKnowledgeBaseError(
            "Knowledge base is empty. An administrator must ingest documents first."
        )

    if out_of_scope:
        return QAResult(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence="low",
            retrieved_chunks=[],
            normalized_query=prepared_query.normalized_query,
            expanded_query=prepared_query.expanded_query,
            matched_expansion_rules=prepared_query.matched_expansion_rules,
            broad_query=False,
            broad_query_reason=None,
            selected_context_count=0,
            detected_intent=detected_intent,
            collection_mode=False,
            ticket_routing=ticket_routing,
            query_expansions_used=prepared_query.matched_expansion_rules,
            rerank_reasons=[],
            fallback_used=False,
            fallback_reason=None,
            out_of_scope_detected=True,
        )

    role = (user_role or "student").strip().lower()
    if is_faculty_restricted_query(prepared_query.normalized_query) and role not in {
        "faculty",
        "office",
        "admin",
    }:
        return QAResult(
            answer=FACULTY_SIGNIN_ANSWER,
            sources=[],
            confidence="low",
            retrieved_chunks=[],
            normalized_query=prepared_query.normalized_query,
            expanded_query=prepared_query.expanded_query,
            matched_expansion_rules=prepared_query.matched_expansion_rules,
            broad_query=False,
            broad_query_reason=None,
            selected_context_count=0,
            detected_intent=detected_intent,
            collection_mode=False,
            ticket_routing=ticket_routing,
            query_expansions_used=prepared_query.matched_expansion_rules,
            rerank_reasons=[],
            fallback_used=False,
            fallback_reason="faculty_topic_hidden_from_role",
            out_of_scope_detected=True,
        )

    program_scope: dict[str, Any] | None = None
    if collection_mode and hasattr(store, "list_chunks"):
        retrieved = collect_intent_chunks(store, collection_intent)
        retrieved = _apply_audience_filter(retrieved, user_role)
        selected_context, context_filter, program_scope = select_collection_context_chunks(
            retrieval_question,
            retrieved,
            collection_intent,
        )
    else:
        retrieval_variants = _retrieval_query_variants(retrieval_question, prepared_query)
        retrieved = _multi_query_retrieve(
            store,
            retrieval_variants,
            top_k=BROAD_RETRIEVAL_CANDIDATES if broad_query else FINAL_CONTEXT_CHUNKS,
            raw_k=BROAD_RETRIEVAL_CANDIDATES if broad_query else RAW_RETRIEVAL_CANDIDATES,
            user_role=user_role,
        )
        retrieved = prefer_service_chunks(retrieved, question=retrieval_question)
        retrieved = _apply_audience_filter(retrieved, user_role)
        selected_context, context_filter = select_context_chunks(
            retrieval_question,
            retrieved,
            broad_query=broad_query,
        )
    context = (
        format_collection_context(selected_context, retrieval_question, collection_intent)
        if collection_mode
        else format_retrieved_context(selected_context)
    )
    sources = _sources_from_chunks(selected_context, merge_articles=collection_mode)
    retrieved_debug = _retrieved_debug(retrieved, context_filter)
    grouped_summary = _grouped_context_summary(selected_context) if broad_query else None
    collection_articles = [item["group"] for item in grouped_summary or []]

    if not retrieved:
        return QAResult(
            answer=_out_of_scope_answer_for_role(user_role),
            sources=[],
            confidence="low",
            retrieved_chunks=[],
            normalized_query=prepared_query.normalized_query,
            expanded_query=prepared_query.expanded_query,
            matched_expansion_rules=prepared_query.matched_expansion_rules,
            broad_query=broad_query,
            broad_query_reason=broad_reason,
            selected_context_count=0,
            grouped_context_summary=[] if broad_query else None,
            detected_intent=detected_intent,
            collection_mode=collection_mode,
            collection_articles=[] if collection_mode else None,
            collection_chunk_count=0 if collection_mode else None,
            group_count=0 if collection_mode else None,
            program_scope=program_scope,
            ticket_routing=ticket_routing,
            query_expansions_used=prepared_query.matched_expansion_rules,
            rerank_reasons=_rerank_reasons_summary(retrieved),
            fallback_used=False,
            fallback_reason=None,
            out_of_scope_detected=False,
        )

    retrieval_quality = _retrieval_quality(
        retrieval_question,
        retrieved,
        selected_context,
        broad_query=broad_query,
        collection_mode=collection_mode,
    )
    if retrieval_quality["should_clarify"]:
        answer = format_conversational_fallback(
            question=cleaned_question,
            context=context,
            sources=sources,
            confidence="low",
            style_hint="clarify",
            reason="retrieval_evidence_weak",
        )
        return QAResult(
            answer=answer,
            sources=sources,
            confidence="low",
            retrieved_chunks=retrieved_debug,
            normalized_query=prepared_query.normalized_query,
            expanded_query=prepared_query.expanded_query,
            matched_expansion_rules=prepared_query.matched_expansion_rules,
            broad_query=broad_query,
            broad_query_reason=broad_reason,
            selected_context_count=len(selected_context),
            grouped_context_summary=grouped_summary,
            detected_intent=detected_intent,
            collection_mode=collection_mode,
            collection_articles=collection_articles if collection_mode else None,
            collection_chunk_count=len(retrieved) if collection_mode else None,
            group_count=len(grouped_summary or []) if collection_mode else None,
            program_scope=program_scope,
            ticket_routing=ticket_routing,
            query_expansions_used=prepared_query.matched_expansion_rules,
            rerank_reasons=_rerank_reasons_summary(retrieved),
            fallback_used=True,
            fallback_reason=retrieval_quality["reason"],
            out_of_scope_detected=False,
        )

    # Follow-up expansion is used for retrieval AND offline extractors so pronouns
    # like "that" resolve for any prior topic — not only when Groq is available.
    extractor_question = answer_question_for_extractors(
        cleaned_question,
        retrieval_question,
    )
    typed_answer = _typed_answer_from_context(
        selected_context,
        sources,
        question=extractor_question,
    )
    # Prefer Groq for how-tos; keep form/requirement cards as immediate typed answers.
    use_typed_now = bool(typed_answer) and not is_service_howto_query(extractor_question)
    if use_typed_now:
        typed_document_type = _kb_document_type(selected_context[0].metadata if selected_context else {})
        return QAResult(
            answer=typed_answer,
            sources=sources,
            confidence=_confidence_for(
                retrieved,
                selected_context,
                typed_answer,
                cleaned_question,
                broad_query=broad_query,
                collection_mode=collection_mode,
            ),
            retrieved_chunks=retrieved_debug,
            normalized_query=prepared_query.normalized_query,
            expanded_query=prepared_query.expanded_query,
            matched_expansion_rules=prepared_query.matched_expansion_rules,
            broad_query=broad_query,
            broad_query_reason=broad_reason,
            selected_context_count=len(selected_context),
            grouped_context_summary=grouped_summary,
            detected_intent=typed_document_type.upper() if typed_document_type else detected_intent,
            collection_mode=collection_mode,
            collection_articles=collection_articles if collection_mode else None,
            collection_chunk_count=len(retrieved) if collection_mode else None,
            group_count=len(grouped_summary or []) if collection_mode else None,
            program_scope=program_scope,
            ticket_routing=ticket_routing,
            query_expansions_used=prepared_query.matched_expansion_rules,
            rerank_reasons=_rerank_reasons_summary(retrieved),
            fallback_used=False,
            fallback_reason=None,
            out_of_scope_detected=False,
        )

    try:
        answer = generate_groq_answer(
            question=cleaned_question,
            context=context,
            broad_mode=broad_query,
            history=chat_history,
        )
    except GroqAnswerError as exc:
        logger.warning(
            "LLM answer generation unavailable; using conversational fallback. reason=%s",
            str(exc),
        )
        # How-to templates are a solid fallback when Groq is unavailable.
        if typed_answer and is_service_howto_query(extractor_question):
            return QAResult(
                answer=typed_answer,
                sources=sources,
                confidence=_confidence_for(
                    retrieved,
                    selected_context,
                    typed_answer,
                    extractor_question,
                    broad_query=broad_query,
                    collection_mode=collection_mode,
                ),
                retrieved_chunks=retrieved_debug,
                normalized_query=prepared_query.normalized_query,
                expanded_query=prepared_query.expanded_query,
                matched_expansion_rules=prepared_query.matched_expansion_rules,
                broad_query=broad_query,
                broad_query_reason=broad_reason,
                selected_context_count=len(selected_context),
                grouped_context_summary=grouped_summary,
                detected_intent=detected_intent,
                collection_mode=collection_mode,
                collection_articles=collection_articles if collection_mode else None,
                collection_chunk_count=len(retrieved) if collection_mode else None,
                group_count=len(grouped_summary or []) if collection_mode else None,
                program_scope=program_scope,
                ticket_routing=ticket_routing,
                query_expansions_used=prepared_query.matched_expansion_rules,
                rerank_reasons=_rerank_reasons_summary(retrieved),
                fallback_used=True,
                fallback_reason=_safe_fallback_reason(str(exc)),
                out_of_scope_detected=False,
            )
        fallback_answer, fallback_confidence, fallback_sources = _fallback_answer_from_context(
            selected_context,
            sources,
            question=extractor_question,
            reason=str(exc),
        )
        recovered = _recover_factual_charter_answer(
            extractor_question,
            retrieved or selected_context,
            sources,
        )
        if recovered and (
            not fallback_answer.strip()
            or fallback_answer == OUT_OF_SCOPE_ANSWER
            or _indicates_missing_information(fallback_answer)
            or _should_prefer_recovered_factual(extractor_question, fallback_answer)
            or _prefer_structured_fee_recovery(extractor_question, recovered, fallback_answer)
        ):
            fallback_answer = recovered
            fallback_confidence = "medium"
        return QAResult(
            answer=fallback_answer,
            sources=fallback_sources,
            confidence=fallback_confidence,
            retrieved_chunks=retrieved_debug,
            normalized_query=prepared_query.normalized_query,
            expanded_query=prepared_query.expanded_query,
            matched_expansion_rules=prepared_query.matched_expansion_rules,
            broad_query=broad_query,
            broad_query_reason=broad_reason,
            selected_context_count=len(selected_context),
            grouped_context_summary=grouped_summary,
            detected_intent=detected_intent,
            collection_mode=collection_mode,
            collection_articles=collection_articles if collection_mode else None,
            collection_chunk_count=len(retrieved) if collection_mode else None,
            group_count=len(grouped_summary or []) if collection_mode else None,
            program_scope=program_scope,
            ticket_routing=ticket_routing,
            query_expansions_used=prepared_query.matched_expansion_rules,
            rerank_reasons=_rerank_reasons_summary(retrieved),
            fallback_used=True,
            fallback_reason=_safe_fallback_reason(str(exc)),
            out_of_scope_detected=False,
        )

    confidence = _confidence_for(
        retrieved,
        selected_context,
        answer,
        extractor_question,
        broad_query=broad_query,
        collection_mode=collection_mode,
    )
    final_answer = _student_facing_answer(answer, confidence, user_role=user_role)
    recovered = _recover_factual_charter_answer(
        extractor_question,
        retrieved or selected_context,
        sources,
    )
    if recovered and (
        final_answer == OUT_OF_SCOPE_ANSWER
        or _indicates_missing_information(final_answer)
        or _indicates_missing_information(answer)
        or _should_prefer_recovered_factual(extractor_question, final_answer)
        or _prefer_structured_fee_recovery(extractor_question, recovered, final_answer)
    ):
        final_answer = recovered
        confidence = "medium" if confidence == "low" else confidence

    return QAResult(
        answer=final_answer,
        sources=sources,
        confidence=confidence,
        retrieved_chunks=retrieved_debug,
        normalized_query=prepared_query.normalized_query,
        expanded_query=prepared_query.expanded_query,
        matched_expansion_rules=prepared_query.matched_expansion_rules,
        broad_query=broad_query,
        broad_query_reason=broad_reason,
        selected_context_count=len(selected_context),
        grouped_context_summary=grouped_summary,
        detected_intent=detected_intent,
        collection_mode=collection_mode,
        collection_articles=collection_articles if collection_mode else None,
        collection_chunk_count=len(retrieved) if collection_mode else None,
        group_count=len(grouped_summary or []) if collection_mode else None,
        program_scope=program_scope,
        ticket_routing=ticket_routing,
        query_expansions_used=prepared_query.matched_expansion_rules,
        rerank_reasons=_rerank_reasons_summary(retrieved),
        fallback_used=False,
        fallback_reason=None,
        out_of_scope_detected=False,
    )


def resolve_followup_question(question: str, history: list[Any] | None) -> str:
    """Expand follow-ups with prior topic for better retrieval (any subject).

    Uses the last user question and, when helpful, topic anchors from the last
    assistant answer so pronouns like "that" / "it" resolve without hardcoding
    specific services.
    """
    cleaned = (question or "").strip()
    if not cleaned or not history:
        return cleaned

    last_user, last_assistant = _last_history_turns(history)
    if not last_user and not last_assistant:
        return cleaned

    normalized = cleaned.casefold()
    followup_prefix = bool(
        re.match(
            r"^(what about|how about|how much|how long|and the|the fee|the office|"
            r"which office|what office|who handles|who is responsible|same for|"
            r"for that|that one|and for|also|what if|and then|then what)\b",
            normalized,
        )
    )
    # "it"/"this"/"those"/"them"/"there"/"same" are almost always anaphoric
    # (referring back to the prior turn). "that" is ambiguous in English: it can
    # be the same kind of backward reference ("what about that?"), or a
    # grammatical relative pronoun inside an otherwise self-contained sentence
    # ("show me the section THAT explains scholarship requirements") — the
    # latter must not be treated as a follow-up cue, or any standalone question
    # that happens to contain "that" gets its retrieval corrupted with an
    # unrelated prior topic. Relative-clause "that" almost always appears after
    # the sentence's subject has already been introduced, so only treat "that"
    # as a follow-up cue when it shows up very early (demonstrative use, e.g.
    # "That one", "Is that required?").
    unanchored_pronoun = bool(re.search(r"\b(?:this|it|those|them|there|same)\b", normalized))
    that_match = re.search(r"\bthat\b", normalized)
    demonstrative_that = bool(that_match) and len(normalized[: that_match.start()].split()) <= 3
    has_pronoun = unanchored_pronoun or demonstrative_that
    content_tokens = _content_tokens(normalized)
    # Standalone if the question already names a concrete topic (2+ content words)
    # and has no follow-up cues.
    standalone = (
        len(content_tokens) >= 2
        and not followup_prefix
        and not has_pronoun
        and len(cleaned.split()) > 6
    )
    short_followup = len(cleaned.split()) <= 8 and not standalone
    if not (followup_prefix or has_pronoun or short_followup):
        return cleaned

    topic = _topic_anchor_from_history(last_user, last_assistant)
    if not topic:
        return cleaned
    return f"{cleaned}\n\n(Prior question context: {topic})"


def _last_history_turns(history: list[Any]) -> tuple[str, str]:
    last_user = ""
    last_assistant = ""
    for item in reversed(list(history)):
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
        else:
            role = str(getattr(item, "role", "") or "").strip().lower()
            content = str(getattr(item, "content", "") or "").strip()
        if not content:
            continue
        if role == "assistant" and not last_assistant:
            last_assistant = content
        elif role == "user" and not last_user:
            last_user = content
        if last_user and last_assistant:
            break
    return last_user, last_assistant


def _content_tokens(text: str) -> set[str]:
    stop = {
        "what", "which", "who", "how", "when", "where", "why", "the", "a", "an",
        "is", "are", "was", "were", "do", "does", "did", "can", "could", "would",
        "should", "for", "of", "to", "in", "on", "at", "by", "with", "from",
        "about", "that", "this", "it", "those", "them", "there", "same", "also",
        "and", "or", "my", "me", "i", "you", "your", "please", "tell", "need",
        "want", "office", "handles", "responsible", "process", "service",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").casefold())
        if token not in stop and len(token) >= 3
    }


def _topic_anchor_from_history(last_user: str, last_assistant: str) -> str:
    """Build a topic string from prior turns — not tied to one FAQ."""
    parts: list[str] = []
    if last_user:
        parts.append(last_user.strip()[:240])
    if last_assistant:
        extracted = _extract_topic_phrases(last_assistant)
        for phrase in extracted:
            if phrase and phrase.casefold() not in " ".join(parts).casefold():
                parts.append(phrase)
    joined = " | ".join(parts).strip()
    return joined[:400]


def _extract_topic_phrases(assistant_text: str) -> list[str]:
    text = (assistant_text or "").strip()
    if not text:
        return []
    phrases: list[str] = []
    patterns = (
        r"(?i)responsible for\s+(.+?)\s+is\s+",
        r"(?i)may avail of\s+(.+?),",
        r"(?i)(?:fee|processing time)\s+for\s+(.+?)\s+is\s+",
        r"(?i)assistance for\s+(.+?)(?:\.|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            phrase = re.sub(r"\s+", " ", match.group(1)).strip(" .:;-")
            if 3 <= len(phrase) <= 120:
                phrases.append(phrase)
    # First short line often carries the service/section title from templates.
    first_line = re.sub(r"\s+", " ", text.splitlines()[0]).strip()
    if 8 <= len(first_line) <= 90 and not first_line.lower().startswith(
        ("sure", "here", "the retrieved", "this may", "overview")
    ):
        phrases.append(first_line)
    # Dedupe preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for phrase in phrases:
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(phrase)
    return unique[:3]


def answer_question_for_extractors(cleaned_question: str, retrieval_question: str) -> str:
    """Flatten follow-up expansion so offline extractors see the prior topic."""
    cleaned = (cleaned_question or "").strip()
    retrieval = (retrieval_question or "").strip()
    if not retrieval or retrieval == cleaned:
        return cleaned
    match = re.search(
        r"\(Prior question context:\s*(.+?)\)\s*$",
        retrieval,
        flags=re.S,
    )
    if not match:
        return cleaned
    prior = re.sub(r"\s+", " ", match.group(1)).strip()
    if not prior:
        return cleaned
    return f"{cleaned} regarding {prior}"


def _ticket_routing_for_question(question: str) -> dict[str, Any]:
    classification = classify_question(question)
    return {
        "category": classification.category,
        "subcategory": classification.subcategory,
        "office": classification.office,
        "responsible_office": classification.office,
        "confidence": classification.confidence,
        "method": classification.method,
    }


def _apply_audience_filter(chunks: list[RetrievedChunk], user_role: str | None) -> list[RetrievedChunk]:
    from app.services.article_rag_indexer import (
        filter_chunks_for_audience,
        filter_unpublished_faq_chunks,
    )

    return filter_chunks_for_audience(
        filter_unpublished_faq_chunks(chunks),
        user_role,
    )


def detect_collection_intent(question: str) -> str:
    """Detect list-style collection questions only.

    Specific charter/service FAQs (which office, fees, requirements for one
    named service) must stay on the normal RAG + Groq path.
    """
    normalized = _normalize(question)
    if _is_specific_query(normalized):
        return NORMAL_QA

    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    listish = _contains_any(
        normalized,
        (
            "list",
            "all",
            "available",
            "what are the",
            "what are",
            "are there",
            "categories",
            "types",
            "what requirements",
            "what documents",
            "what services",
            "what offices",
            "what programs",
            "what scholarships",
            "what courses",
            "what colleges",
        ),
    )

    if listish and _contains_any(
        normalized,
        ("scholarship", "scholarships", "financial assistance", "grant", "grants", "aid"),
    ):
        return SCHOLARSHIP_COLLECTION
    if listish and (
        _contains_any(normalized, ("student service", "student services", "guidance service", "health service"))
        or (
            _contains_any(normalized, ("service", "services"))
            and _contains_any(normalized, ("osas", "student", "available", "provide", "provided"))
        )
    ):
        return SERVICE_COLLECTION
    if (
        _contains_any(normalized, ("offices", "departments"))
        or (
            listish
            and _contains_any(normalized, ("office", "department"))
            and not _contains_any(
                normalized,
                ("which office", "what office", "responsible", "handles", "in charge"),
            )
        )
    ):
        return OFFICE_COLLECTION
    if listish and _contains_any(
        normalized,
        ("requirement", "requirements", "documents", "clearance", "forms", "checklist"),
    ):
        # Named service + requirements is a normal FAQ, not a collection sweep.
        if _has_named_service_anchor(normalized):
            return NORMAL_QA
        return REQUIREMENT_COLLECTION
    if _contains_any(normalized, ("policy", "policies", "rules", "guidelines")) and listish:
        # Faculty-specific policy questions should use normal RAG, not a broad policy sweep.
        if _contains_any(
            normalized,
            ("faculty", "teaching load", "professor", "instructor", "grading sheets"),
        ):
            return NORMAL_QA
        return POLICY_COLLECTION
    program_signals = tokens & {"program", "programs", "course", "courses", "degree", "degrees", "college", "colleges", "offered"}
    if (program_signals or _contains_any(normalized, ("curricular offering", "curricular offerings"))) and (
        listish or _contains_any(normalized, ("offered", "offerings"))
    ):
        return PROGRAM_COLLECTION
    return NORMAL_QA


def detect_question_intent(question: str) -> str:
    normalized = _normalize(question)
    if is_greeting_query(question):
        return GREETING_QUESTION
    if _is_out_of_scope_query(normalized):
        return OUT_OF_SCOPE_QUESTION
    if _contains_any(normalized, ("how do i", "how can i", "where can i get", "steps", "process", "procedure", "file an", "get an excuse slip")):
        return PROCEDURE_QUESTION
    if _contains_any(normalized, ("requirement", "requirements", "needed for", "documents", "what do i need")):
        return REQUIREMENT_QUESTION
    if _contains_any(normalized, ("where can i", "who handles", "which office", "what office", "registrar", "guidance office", "counseling", "tor")):
        return OFFICE_SERVICE_QUESTION
    if _contains_any(normalized, ("what is", "what does", "define", "meaning of", "scholastic delinquency", "retention")):
        return DEFINITION_QUESTION
    return NORMAL_QA


_GREETING_RE = re.compile(
    r"^(?:"
    r"hi+|hello|hey+|yo|howdy|greetings|"
    r"good\s*(?:morning|afternoon|evening|day)|"
    r"(?:what'?s|whats)\s*up|sup|"
    r"how\s+are\s+you(?:\s+doing)?|"
    r"thanks?(?:\s+you)?(?:\s+a\s+lot)?|thank\s+you(?:\s+so\s+much)?|"
    r"ok(?:ay)?|bye|goodbye|see\s+you(?:\s+later)?"
    r")"
    r"(?:\s*[!.]*)?$",
    re.I,
)


def is_greeting_query(question: str) -> bool:
    """True for short social chat that must not run handbook retrieval."""
    text = (question or "").strip()
    if not text or len(text) > 48:
        return False
    return bool(_GREETING_RE.match(text))


def detect_broad_query(question: str) -> tuple[bool, str | None]:
    normalized = _normalize(question)
    if _is_specific_query(normalized):
        return False, None

    phrase_triggers = (
        "what are the requirements",
        "what are the types",
        "what are the categories",
        "what programs",
        "what courses",
        "what colleges",
        "what services",
        "what offices",
        "what scholarships",
        "what requirements",
        "what services",
        "what offices",
        "list all",
        "all programs",
        "all courses",
        "all colleges",
        "all offices",
        "all services",
        "programs offered",
        "courses offered",
        "offered by the university",
    )
    if _contains_any(normalized, phrase_triggers):
        return True, "broad_list_phrase"

    broad_terms = {
        "all",
        "list",
        "available",
        "offered",
        "programs",
        "courses",
        "colleges",
        "offices",
        "services",
        "scholarships",
        "requirements",
        "types",
        "categories",
    }
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    if len(tokens & broad_terms) >= 2:
        return True, "multiple_broad_terms"
    return False, None


def select_context_chunks(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    broad_query: bool = False,
) -> tuple[list[RetrievedChunk], dict[int, tuple[bool, list[str]]]]:
    if not chunks:
        return [], {}

    normalized_query = _normalize(question)
    query_domain = _detected_query_domain(normalized_query)
    if broad_query:
        limit = BROAD_CONTEXT_CHUNKS
    elif _is_factual_charter_query(normalized_query) or _is_broad_context_query(normalized_query):
        limit = FACTUAL_CONTEXT_CHUNKS
    else:
        limit = DEFAULT_CONTEXT_CHUNKS
    top_score = _chunk_score(chunks[0])
    selected: list[RetrievedChunk] = []
    decisions: dict[int, tuple[bool, list[str]]] = {}
    seen_groups: set[str] = set()

    for rank, chunk in enumerate(chunks, start=1):
        reasons = _context_filter_reasons(
            chunk=chunk,
            normalized_query=normalized_query,
            query_domain=query_domain,
            top_score=top_score,
            rank=rank,
            broad_query=broad_query,
        )
        group_key = _context_group_key(chunk, normalized_query)
        duplicate_group = broad_query and group_key in seen_groups
        keep = (rank == 1 and not broad_query) or (len(selected) < limit and any(reason.startswith("keep_") for reason in reasons))
        if broad_query:
            keep = len(selected) < limit and any(reason.startswith("keep_") for reason in reasons)
            if duplicate_group:
                keep = False
                reasons.append("drop_duplicate_context_group")
        if rank != 1 and _has_strong_penalty(chunk):
            keep = False
        if is_service_howto_query(normalized_query) and is_artifact_or_requirement_form_chunk(chunk):
            keep = False
            reasons.append("drop_requirement_form_artifact_for_service_query")
        if broad_query and _looks_like_noise(chunk):
            keep = False
        if keep and len(selected) >= limit:
            keep = False
            reasons.append("drop_context_limit")
        if keep:
            selected.append(chunk)
            seen_groups.add(group_key)
        elif not any(reason.startswith("drop_") for reason in reasons):
            reasons.append("drop_weak_context_match")
        decisions[id(chunk)] = (keep, reasons)

    return selected, decisions


def collect_intent_chunks(store, intent: str) -> list[RetrievedChunk]:
    chunks: list[RetrievedChunk] = []
    seen_ids: set[str] = set()
    for raw_chunk in store.list_chunks():
        metadata = dict(raw_chunk.get("metadata") or {})
        text = str(raw_chunk.get("text") or "")
        chunk_id = str(raw_chunk.get("id") or "")
        if not text or chunk_id in seen_ids:
            continue
        if not _raw_chunk_matches_collection_intent(chunk_id, text, metadata, intent):
            continue
        seen_ids.add(chunk_id)
        chunks.append(_retrieved_from_raw_chunk(raw_chunk, intent))
    chunks.sort(key=lambda chunk: (_collection_sort_key(chunk), _page_number(chunk.metadata or {}) or 9999, chunk.chunk_index))
    return chunks


def select_collection_context_chunks(
    question: str,
    chunks: list[RetrievedChunk],
    intent: str,
) -> tuple[list[RetrievedChunk], dict[int, tuple[bool, list[str]]], dict[str, Any] | None]:
    selected: list[RetrievedChunk] = []
    decisions: dict[int, tuple[bool, list[str]]] = {}
    seen_titles: set[str] = set()
    seen_groups: set[str] = set()

    normalized_query = _normalize(question)
    program_scope = _program_scope_from_query(normalized_query) if intent == PROGRAM_COLLECTION else None
    requested_college = (program_scope or {}).get("detected_college_scope")
    requested_campus = (program_scope or {}).get("detected_campus_scope")
    excluded_scope_reasons: list[dict[str, Any]] = []
    ordered_chunks = sorted(
        chunks,
        key=lambda chunk: (
            -_collection_query_score(chunk, normalized_query),
            _collection_sort_key(chunk),
            _page_number(chunk.metadata or {}) or 9999,
            chunk.chunk_index,
        ),
    )

    for rank, chunk in enumerate(ordered_chunks, start=1):
        reasons = [f"collection_intent:{intent}"]
        group_key = _collection_group_key(chunk, intent)
        title_key = _normalize(f"{group_key}|{_display_title(chunk)}")
        keep = True
        if requested_college and not _chunk_matches_requested_college(chunk, requested_college):
            keep = False
            reasons.append("drop_unrequested_college")
            excluded_scope_reasons.append(
                {
                    "title": _display_title(chunk),
                    "reason": "college_scope_mismatch",
                    "scope": requested_college,
                }
            )
        if requested_campus and not _chunk_matches_requested_campus(chunk, requested_campus):
            keep = False
            reasons.append("drop_unrequested_campus")
            excluded_scope_reasons.append(
                {
                    "title": _display_title(chunk),
                    "reason": "campus_scope_mismatch_or_missing",
                    "scope": requested_campus,
                }
            )
        if _looks_like_noise(chunk):
            keep = False
            reasons.append("drop_collection_noise")
        if title_key in seen_titles:
            keep = False
            reasons.append("drop_duplicate_title")
        if keep and len(selected) >= COLLECTION_CONTEXT_GROUPS:
            keep = False
            reasons.append("drop_collection_context_limit")
        if keep:
            selected.append(chunk)
            seen_titles.add(title_key)
            seen_groups.add(group_key)
            reasons.append("keep_collection_match")
        elif not any(reason.startswith("drop_") for reason in reasons):
            reasons.append("drop_collection_unselected")
        decisions[id(chunk)] = (keep, reasons)

    if program_scope is not None:
        program_scope["scope_filter_applied"] = bool(requested_college or requested_campus)
        program_scope["chunks_before_scope_filter"] = len(chunks)
        program_scope["chunks_after_scope_filter"] = len(selected)
        program_scope["excluded_scope_reasons"] = excluded_scope_reasons

    return selected, decisions, program_scope


def format_retrieved_context(chunks: list[RetrievedChunk]) -> str:
    blocks: list[str] = []
    for chunk in chunks:
        metadata = chunk.metadata or {}
        title = _display_title(chunk)
        path = _hierarchy_path(metadata) or title
        page = _page_label(metadata)
        meta_lines = _charter_metadata_context_lines(metadata)
        blocks.append(
            "\n".join(
                [
                    f"Title: {title}",
                    f"Path: {path}",
                    f"Page: {page}",
                    *meta_lines,
                    "",
                    "Content:",
                    chunk.text.strip(),
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def format_collection_context(chunks: list[RetrievedChunk], question: str, intent: str = NORMAL_QA) -> str:
    if intent == PROGRAM_COLLECTION:
        return format_program_collection_context(chunks)

    grouped: dict[str, list[RetrievedChunk]] = {}
    normalized_query = _normalize(question)
    for chunk in chunks:
        group = _collection_display_group(chunk, _detected_query_domain(normalized_query))
        grouped.setdefault(group, []).append(chunk)

    blocks: list[str] = []
    for group, group_chunks in grouped.items():
        lines = [f"Group: {group}"]
        for chunk in group_chunks:
            metadata = chunk.metadata or {}
            lines.extend(
                [
                    "",
                    f"Title: {_display_title(chunk)}",
                    f"Path: {_hierarchy_path(metadata) or _display_title(chunk)}",
                    f"Page: {_page_label(metadata)}",
                    "Content:",
                    chunk.text.strip(),
                ]
            )
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def format_program_collection_context(chunks: list[RetrievedChunk]) -> str:
    outline = _program_collection_outline(chunks)
    blocks: list[str] = [
        "Collection Intent: PROGRAM_COLLECTION",
        "Answer format: group programs under their College or Academic Unit. Do not output a flat program list.",
        "Only list programs shown below. Omit any college with no listed programs.",
        "",
    ]
    for group in outline:
        blocks.append(f"College: {group['college']}")
        blocks.append("Programs:")
        for program in group["programs"]:
            blocks.append(f"- {program}")
        pages = group.get("pages") or []
        if pages:
            blocks.append(f"Pages: {_page_range_label(pages)}")
        blocks.append("")
    return "\n".join(blocks).strip()


def _confidence_for(
    retrieved_chunks: list[RetrievedChunk],
    selected_chunks: list[RetrievedChunk],
    answer: str,
    question: str,
    *,
    broad_query: bool = False,
    collection_mode: bool = False,
) -> str:
    if not retrieved_chunks or not selected_chunks:
        return "low"
    normalized_answer = answer.lower()
    if any(phrase in normalized_answer for phrase in MISSING_INFO_PHRASES):
        return "low"

    top_score = _chunk_score(retrieved_chunks[0])
    domain = _detected_query_domain(_normalize(question))
    has_domain_match = any(_chunk_matches_domain(chunk, domain) for chunk in selected_chunks) if domain else True
    domain_match_count = sum(1 for chunk in selected_chunks if _chunk_matches_domain(chunk, domain)) if domain else len(selected_chunks)
    has_positive_signal = any(_positive_reasons(chunk) for chunk in selected_chunks)
    noisy_selected = any(_has_strong_penalty(chunk) for chunk in selected_chunks[1:])

    if broad_query:
        if collection_mode:
            if len(selected_chunks) >= 3 and domain_match_count >= 2 and not noisy_selected:
                return "high"
            if len(selected_chunks) >= 2 and not noisy_selected:
                return "medium"
            return "low"
        if len(selected_chunks) >= 3 and domain_match_count >= 3 and has_positive_signal and not noisy_selected:
            return "high"
        if len(selected_chunks) >= 2 and domain_match_count >= 1 and not noisy_selected:
            return "medium"
        return "low"

    if top_score >= 0.82 and has_domain_match and has_positive_signal and not noisy_selected:
        return "high"
    if top_score >= 0.58 and not noisy_selected:
        return "medium"
    return "low"


def _retrieval_query_variants(question: str, prepared_query: Any) -> list[str]:
    variants = [question, prepared_query.normalized_query, prepared_query.expanded_query]
    seen: set[str] = set()
    deduped: list[str] = []
    for value in variants:
        candidate = str(value or "").strip()
        if not candidate:
            continue
        folded = _normalize_ascii(_normalize(candidate))
        if folded in seen:
            continue
        seen.add(folded)
        deduped.append(candidate)
    return deduped


def _multi_query_retrieve(
    store: Any,
    queries: list[str],
    *,
    top_k: int,
    raw_k: int,
) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    for query in queries:
        results = store.search(query, top_k=top_k, raw_k=raw_k)
        for chunk in results:
            key = _chunk_merge_key(chunk)
            existing = merged.get(key)
            if existing is None or _chunk_score(chunk) > _chunk_score(existing):
                merged[key] = chunk
    return sorted(merged.values(), key=_chunk_score, reverse=True)


def _chunk_merge_key(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    identifier = str(chunk.chunk_id or metadata.get("chunk_id") or "").strip()
    if identifier:
        return f"id:{identifier}"
    document_id = str(chunk.document_id or metadata.get("document_id") or "").strip()
    page = str(metadata.get("page") or metadata.get("page_label") or "").strip()
    title = _normalize_ascii(_normalize(str(chunk.title or metadata.get("title") or "")))
    preview = _normalize_ascii(_normalize(str(chunk.text or "")))[:160]
    return f"doc:{document_id}|p:{page}|t:{title}|x:{preview}"


def _retrieval_quality(
    question: str,
    retrieved: list[RetrievedChunk],
    selected: list[RetrievedChunk],
    *,
    broad_query: bool,
    collection_mode: bool,
) -> dict[str, Any]:
    if not retrieved or not selected:
        return {"should_clarify": True, "reason": "no_retrieval_context"}
    if broad_query or collection_mode:
        return {"should_clarify": False, "reason": "broad_or_collection_mode"}

    top = _chunk_score(retrieved[0])
    second = _chunk_score(retrieved[1]) if len(retrieved) > 1 else 0.0
    margin = top - second
    normalized_q = _normalize(question)
    domain = _detected_query_domain(normalized_q)
    domain_match_count = sum(1 for chunk in selected if _chunk_matches_domain(chunk, domain)) if domain else len(selected)
    positive_count = sum(1 for chunk in selected if _positive_reasons(chunk))
    noisy_count = sum(1 for chunk in selected if _has_strong_penalty(chunk))

    too_short_or_noisy = len(_meaningful_tokens(normalized_q)) <= 3
    weak_top_score = top < 0.54
    weak_margin = len(retrieved) > 1 and margin < 0.03 and top < 0.62
    weak_alignment = domain_match_count == 0 or positive_count == 0
    noisy_context = noisy_count >= max(1, len(selected) // 2)

    should_clarify = bool(
        weak_top_score
        or weak_margin
        or weak_alignment
        or noisy_context
        or (too_short_or_noisy and (weak_top_score or weak_alignment))
    )
    if should_clarify:
        return {"should_clarify": True, "reason": "weak_or_inconsistent_retrieval_evidence"}
    return {"should_clarify": False, "reason": "retrieval_evidence_sufficient"}


def _student_facing_answer(
    answer: str,
    confidence: str,
    *,
    user_role: str | None = None,
) -> str:
    from app.services.qa.groq_answer_service import _strip_pointer_phrasing

    cleaned = _strip_pointer_phrasing(_strip_source_lines(answer))
    # Only collapse to the stock OOS line when the reply is basically a refusal —
    # keep partial useful answers that also mention missing details.
    if (
        confidence == "low"
        and _indicates_missing_information(cleaned)
        and _is_mostly_missing_info_reply(cleaned)
    ):
        return _out_of_scope_answer_for_role(user_role)
    return cleaned


def _is_mostly_missing_info_reply(answer: str) -> bool:
    text = (answer or "").strip()
    if not text:
        return True
    if re.search(r"(?m)^\s*(?:[-*•]|\d+\.)\s+\S", text):
        return False
    if len(text) > 280:
        return False
    return True


def _should_prefer_recovered_factual(question: str, answer: str) -> bool:
    """Replace wrong office-only dumps when the user asked for documents/fees/etc."""
    normalized_q = _normalize(question)
    normalized_a = _normalize(answer)
    if not answer.strip():
        return True
    asks_documents = bool(
        re.search(
            r"\b(?:document|documents|requirement|requirements|what must|what additional)\b",
            normalized_q,
        )
    )
    asks_who = bool(re.search(r"\b(?:who may|who can avail)\b", normalized_q))
    asks_fee = bool(re.search(r"\b(?:how much|fee|fees|cost)\b", normalized_q))
    asks_time = bool(re.search(r"\b(?:how long|processing time)\b", normalized_q))
    office_only = bool(
        re.search(
            r"\b(?:responsible office|office responsible)\b",
            normalized_a,
        )
        and not re.search(
            r"\b(?:required|requirement|document|fee|fees|listed fee|processing time|who may|p\d)\b",
            normalized_a,
        )
    )
    if asks_documents and office_only:
        return True
    if asks_who and office_only:
        return True
    if asks_fee and office_only:
        return True
    if asks_time and office_only:
        return True
    # Fee questions answered with unrelated exam/handbook schedule text.
    if asks_fee and re.search(
        r"\b(?:comprehensive examination|examination schedule|annual report|"
        r"assessment of fees|certified true copy)\b",
        normalized_a,
    ):
        return True
    if asks_fee and re.search(
        r"\b(?:do not specify|does not specify|not specify the cost|do not contain)\b",
        normalized_a,
    ):
        return True
    return False


def _prefer_structured_fee_recovery(question: str, recovered: str, llm_answer: str) -> bool:
    """Prefer metadata fee recovery when the LLM names the wrong service or omits amounts."""
    normalized_q = _normalize(question)
    if not re.search(r"\b(?:how much|fee|fees|cost)\b", normalized_q):
        return False
    recovered_n = _normalize(recovered)
    if "listed fee" not in recovered_n:
        return False
    llm_n = _normalize(llm_answer or "")
    if not llm_n.strip():
        return True
    if re.search(r"\b(?:fees?:\s*none|fee:\s*none|not specified|do not specify|does not specify)\b", llm_n):
        return True
    if re.search(
        r"\b(?:assessment of fees|certified true copy|comprehensive examination)\b",
        llm_n,
    ):
        return True
    if "diploma" in normalized_q and "diploma" in recovered_n and "diploma" not in llm_n:
        return True
    # If the LLM cites *some* number at all (e.g. "100 pesos" instead of
    # "P100.00"), trust it rather than overriding on formatting/style alone —
    # only override when the answer has no amount whatsoever.
    if re.search(r"(?i)\bp\s*\d|\d+\.\d{2}", recovered) and not re.search(r"\d", llm_answer or ""):
        return True
    return False


def _recover_factual_charter_answer(
    question: str,
    chunks: list[RetrievedChunk],
    sources: list[dict[str, Any]],
) -> str | None:
    """Extract office / who-may-avail / fee / time from charter chunks when LLM misses."""
    if not chunks or not is_factual_service_detail_query(question):
        return None
    normalized = _normalize(question)
    asks_fee = bool(re.search(r"\b(?:how much|fee|fees|cost)\b", normalized))
    asks_office = bool(
        re.search(r"\b(?:which office|what office|who handles|responsible|in charge)\b", normalized)
    )
    ranked = sorted(
        chunks,
        key=lambda chunk: _charter_recovery_rank(chunk, normalized, prefer_fees=asks_fee),
    )
    for chunk in ranked:
        metadata = chunk.metadata or {}
        title = (
            _meta_text(metadata, "source_section")
            or _meta_text(metadata, "canonical_topic")
            or _meta_text(metadata, "title")
            or _display_title(chunk)
            or "this service"
        )
        source_label = _source_label(
            sources,
            fallback=_meta_text(metadata, "source_label")
            or _meta_text(metadata, "source_document")
            or chunk.source_filename,
        )

        if re.search(r"\b(?:who may|who can avail|who can)\b", normalized):
            who = _meta_text(metadata, "who_may_avail") or _extract_labeled_line(
                chunk.text or "",
                ("Who May Avail", "Who May Avail of the Service", "Clientele"),
            )
            if who:
                return (
                    f"{who} may avail of {title}, according to the {source_label}."
                )

        if re.search(r"\b(?:how long|processing time)\b", normalized):
            time_value = _meta_text(metadata, "total_processing_time") or _extract_labeled_line(
                chunk.text or "",
                ("Total Processing Time",),
            )
            if time_value:
                return f"The total processing time for {title} is {time_value} ({source_label})."

        fee = None
        office = None
        if asks_fee:
            raw_fee = (
                _meta_text(metadata, "total_fees")
                or _meta_text(metadata, "fees")
                or _extract_labeled_line(chunk.text or "", ("Fees", "Fee", "Total Fees"))
                or _extract_tor_fees_from_text(chunk.text or "", normalized)
            )
            fee = _fee_usable_for_question(raw_fee, title, normalized)
        if asks_office:
            office = (
                _meta_text(metadata, "office")
                or _meta_text(metadata, "responsible_office")
                or _extract_labeled_line(chunk.text or "", ("Office / Division", "Office"))
            )

        # Fee+office in one question: never answer office-only first.
        if asks_fee and asks_office and fee:
            answer_title = _fee_answer_title(title, fee, normalized)
            if office:
                return (
                    f"For {answer_title}, the listed fee is {fee}. "
                    f"The responsible office is {office} ({source_label})."
                )
            return f"The listed fee for {answer_title} is {fee} ({source_label})."

        if asks_fee and fee:
            answer_title = _fee_answer_title(title, fee, normalized)
            return f"The listed fee for {answer_title} is {fee} ({source_label})."

        if asks_office and office and not asks_fee:
            return f"The office responsible for {title} is {office} ({source_label})."

        if re.search(
            r"\b(?:what documents|what additional|what must|documents? (?:are )?required|"
            r"requirements? (?:for|from|needed)|what (?:are|is) the (?:requirement|requirements|document|documents))\b",
            normalized,
        ):
            answer = format_requirements_detail_answer(question, chunk, sources)
            if answer:
                return answer
    return None


def _charter_recovery_rank(
    chunk: RetrievedChunk,
    normalized_question: str,
    *,
    prefer_fees: bool = False,
) -> tuple[int, float, int]:
    metadata = chunk.metadata or {}
    title = _normalize(
        " ".join(
            str(value or "")
            for value in (
                metadata.get("source_section"),
                metadata.get("canonical_topic"),
                metadata.get("title"),
                chunk.title,
            )
        )
    )
    score = -_chunk_score(chunk)
    has_fees = 0 if (
        _meta_text(metadata, "total_fees")
        or _meta_text(metadata, "fees")
        or _extract_labeled_line(chunk.text or "", ("Fees", "Fee", "Total Fees"))
    ) else 1
    fee_priority = has_fees if prefer_fees else 0

    if "enroll" in normalized_question:
        if (
            "ip registration" in title
            or "assessment of fee" in title
            or "visitation" in title
            or "article 3" in title
        ):
            return (3, fee_priority, score)
        if "enrollment" in title or "enrolment" in title:
            return (0, fee_priority, score)
        if "registration" in title and "enrollment" not in title:
            return (3, fee_priority, score)
        return (1, fee_priority, score)

    if re.search(r"\b(?:tor|transcript)\b", normalized_question):
        if re.search(r"\b(?:transcript of records|issuance of transcript|\btor\b)\b", title):
            return (0, fee_priority, score)
        if "annual report" in title or "certificate of completion" in title or "article 3" in title:
            return (3, fee_priority, score)
        return (2, fee_priority, score)

    if "diploma" in normalized_question:
        fee_blob = _normalize(
            str(metadata.get("total_fees") or metadata.get("fees") or "")
            + " "
            + (chunk.text or "")[:500]
        )
        if "diploma" in title or "diploma" in fee_blob:
            return (0, 0 if prefer_fees else fee_priority, score)
        if (
            "assessment of fee" in title
            or "examination" in title
            or "open to all clients" in title
            or "faculty clearance" in title
            or "crediting of subject" in title
            or "program accreditation" in title
            or "certified true copy" in title
        ):
            return (3, fee_priority, score)
        return (2, fee_priority, score)

    return (1, fee_priority, score)


def _fee_usable_for_question(fee: str | None, title: str, normalized_question: str) -> str | None:
    """Accept fees only when they belong to the asked service (not Assessment of Fees noise)."""
    if not fee:
        return None
    title_n = _normalize(title)
    fee_n = _normalize(fee)

    if "assessment of fee" in title_n and not re.search(
        r"\b(?:assessment of fees?|enrol(?:l)?ment fee)\b",
        normalized_question,
    ):
        return None

    if "diploma" in normalized_question:
        specialized = _specialize_fee_line(fee, ("second copy of diploma", "diploma"))
        if specialized:
            return specialized
        if "diploma" in title_n:
            return fee.strip()
        return None

    if re.search(r"\b(?:tor|transcript)\b", normalized_question):
        if re.search(r"\b(?:transcript|tor|credential)\b", title_n) or "per page" in fee_n:
            return fee.strip()
        if "assessment of fee" in title_n:
            return None

    return fee.strip()


def _specialize_fee_line(fee: str, preferred_labels: tuple[str, ...]) -> str | None:
    parts = [part.strip() for part in re.split(r"\s*;\s*", fee or "") if part.strip()]
    for label in preferred_labels:
        label_n = _normalize(label)
        for part in parts:
            part_n = _normalize(part)
            if label_n in part_n and re.search(r"(?i)\bp\s*\d|\d", part):
                return part
    return None


def _fee_answer_title(title: str, fee: str, normalized_question: str) -> str:
    if "diploma" in normalized_question and "diploma" in _normalize(fee):
        if "second copy" in _normalize(fee):
            return "a second copy of a diploma"
        return "diploma"
    return title


def _extract_tor_fees_from_text(text: str, normalized_question: str) -> str | None:
    """Pull per-page TOR amounts out of flattened Citizen's Charter tables."""
    if not re.search(r"\b(?:tor|transcript)\b", normalized_question):
        return None
    blob = re.sub(r"\s+", " ", text or "")
    match = re.search(
        r"undergrad(?:uate)?(?:\s+students?)?\s*(P\s*\d+(?:\.\d{2})?\s*/\s*page)"
        r".{0,80}graduate(?:\s+students?)?\s*(P\s*\d+(?:\.\d{2})?\s*/\s*page)",
        blob,
        flags=re.I | re.S,
    )
    if match:
        return f"Undergraduate {match.group(1).strip()}; Graduate {match.group(2).strip()}"
    undergrad = re.search(r"undergrad(?:uate)?(?:\s+students?)?\s*(P\s*\d+(?:\.\d{2})?\s*/\s*page)", blob, flags=re.I)
    if undergrad:
        return undergrad.group(0).strip()
    return None


def _extract_labeled_line(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(
            rf"(?im)^{re.escape(label)}\s*[:\-]?\s*(.+)$",
            text or "",
        )
        if match:
            value = match.group(1).strip()
            if value and value.lower() not in {"not specified", "none", "n/a", "[needs review]"}:
                return value
    # Also accept inline "Who May Avail: Students"
    for label in labels:
        match = re.search(
            rf"(?is){re.escape(label)}\s*[:\-]\s*([^\n]+)",
            text or "",
        )
        if match:
            value = match.group(1).strip()
            if value and value.lower() not in {"not specified", "none", "n/a", "[needs review]"}:
                return value
    return ""


def _indicates_missing_information(answer: str) -> bool:
    normalized_answer = answer.lower()
    return any(phrase in normalized_answer for phrase in MISSING_INFO_PHRASES)


def _fallback_answer_from_context(
    selected_context: list[RetrievedChunk],
    sources: list[dict[str, Any]],
    *,
    question: str = "",
    reason: str = "",
) -> tuple[str, str, list[dict[str, Any]]]:
    """Conversational extractive answer when the LLM is unavailable.

    ``reason`` is for logs/debug only — never shown to students.
    """
    if reason:
        logger.info("Building conversational fallback (llm_reason=%s)", reason)

    relevant = [chunk for chunk in selected_context if not _has_strong_penalty(chunk)]
    if not relevant:
        return OUT_OF_SCOPE_ANSWER, "low", []

    top_score = max(_chunk_score(chunk) for chunk in relevant)
    confidence = "medium" if top_score >= 0.72 else "low"

    answer = format_conversational_fallback(
        question,
        relevant,
        sources,
        confidence=confidence,
    )
    if not answer.strip():
        return OUT_OF_SCOPE_ANSWER, "low", []

    # Never expose internal LLM/service status in the student answer.
    if re.search(r"ai answer service is temporarily busy", answer, re.I):
        answer = re.sub(
            r"(?i)the\s+ai\s+answer\s+service\s+is\s+temporarily\s+busy\.?\s*",
            "",
            answer,
        ).strip()

    return answer, confidence, sources


def _typed_answer_from_context(
    selected_context: list[RetrievedChunk],
    sources: list[dict[str, Any]],
    *,
    question: str = "",
) -> str | None:
    """Return a deterministic answer only for clear how-to / form intents.

    Factual charter questions (fees, times, who may avail, vision, edition,
    which office, document lists) must reach Groq so answers match the asked
    detail instead of a generic step dump.
    """
    if not selected_context:
        return None

    form_intent = is_form_or_requirement_query(question)
    howto_intent = is_service_howto_query(question)
    # Empty question keeps legacy typed path for unit tests / callers.
    allow_typed_procedure = howto_intent or not str(question or "").strip()
    if is_factual_service_detail_query(question):
        allow_typed_procedure = False

    top = selected_context[0]
    metadata = top.metadata or {}
    document_type = _kb_document_type(metadata)

    # Only dump form/requirement cards when the user asked about a form.
    if form_intent and (
        document_type == "requirement" or is_artifact_or_requirement_form_chunk(top)
    ):
        return _requirement_answer(top, sources)

    if not allow_typed_procedure:
        return None

    # Prefer a complete Citizen Charter / service procedure chunk for how-tos.
    for chunk in selected_context:
        if is_artifact_or_requirement_form_chunk(chunk) and not form_intent:
            continue
        if is_service_procedure_chunk(chunk):
            return format_service_procedure_answer(chunk, sources)

    if document_type == "procedure":
        return format_service_procedure_answer(top, sources)

    return None


def _procedure_answer(chunk: RetrievedChunk, sources: list[dict[str, Any]]) -> str:
    """Backward-compatible wrapper; prefer the conversational service formatter."""
    return format_service_procedure_answer(chunk, sources)


def _requirement_answer(chunk: RetrievedChunk, sources: list[dict[str, Any]]) -> str:
    metadata = chunk.metadata or {}
    title = _meta_text(metadata, "title") or _display_title(chunk)
    requirements = _json_list(metadata.get("extracted_requirements"))
    related_services = _json_list(metadata.get("related_services"))
    how_to_fill_out = _json_list(metadata.get("how_to_fill_out"))
    preview = _meta_text(metadata, "preview_file_path")
    lines = [
        title,
        "",
        "Summary:",
        _meta_text(metadata, "summary") or _extract_label(chunk.text, "Summary") or "Use this form for the documented requirement.",
        "",
        "Requirements:",
    ]
    if requirements:
        lines.extend(f"- {item}" for item in requirements)
    else:
        lines.append("- Not specified")
    lines.extend(["", "How to Fill Out:"])
    if how_to_fill_out:
        lines.extend(f"- {item}" for item in how_to_fill_out)
    else:
        lines.append("- Fill in the required requester information.")
    lines.extend(["", "Form Preview:", preview or "Preview is not available."])
    lines.extend(["", "Related Services:"])
    if related_services:
        lines.extend(f"- {item}" for item in related_services)
    else:
        lines.append("- Not specified")
    lines.extend(["", "Source:", _source_label(sources, fallback=_meta_text(metadata, "source_document") or chunk.source_filename)])
    return "\n".join(lines).strip()


def _kb_document_type(metadata: dict[str, Any]) -> str:
    value = str((metadata or {}).get("document_type") or "").strip().lower()
    return value if value in {"information", "procedure", "requirement"} else "information"


def _json_list(value: Any) -> list[Any]:
    parsed = _json_value(value)
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: Any) -> dict[str, Any]:
    parsed = _json_value(value)
    return parsed if isinstance(parsed, dict) else {}


def _json_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _meta_text(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    return str(value).strip() if value is not None and str(value).strip() else ""


def _procedure_summary(metadata: dict[str, Any], title: str) -> str:
    office = _meta_text(metadata, "office")
    who = _meta_text(metadata, "who_may_avail")
    if office and who:
        return f"{title} is handled by {office} for {who}."
    if office:
        return f"{title} is handled by {office}."
    return f"{title} is a documented service procedure."


def _office_or_responsible(metadata: dict[str, Any], text: str) -> str:
    office = _meta_text(metadata, "office")
    responsible = _extract_label(text, "Person Responsible") or _extract_label(text, "Responsible Personnel")
    if office and responsible:
        return f"{office}; {responsible}"
    return office or responsible or "Not specified"


def _extract_label(text: str, label: str) -> str:
    pattern = rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+)$"
    match = re.search(pattern, text or "")
    return match.group(1).strip() if match else ""


def _numbered_lines_from_text(text: str) -> list[str]:
    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if re.match(r"^\d+\.\s+", stripped):
            lines.append(stripped)
    return lines or ["1. See the cited source for the documented steps."]


def _source_label(sources: list[dict[str, Any]], *, fallback: str | None = None) -> str:
    """Build a human-readable source line for extractive/fallback answers."""
    safe_fallback = (fallback or "").strip() or "Source document"
    if not sources:
        return safe_fallback
    source = sources[0]
    # Prefer Level-2 citation label when present.
    citation_label = str(source.get("source_label") or "").strip()
    if citation_label:
        page = source.get("page_range") or source.get("page_number") or source.get("page")
        if page:
            return f"{citation_label} > page {page}"
        return citation_label
    parts = [str(source.get("title") or "").strip(), str(source.get("path") or "").strip()]
    page = source.get("page_range") or source.get("page_number") or source.get("page")
    if page:
        parts.append(f"page {page}")
    return " > ".join(part for part in parts if part) or safe_fallback


def _extractive_excerpt(text: str, limit: int = 520) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    sentence_end = cleaned.rfind(".", 0, limit)
    if sentence_end >= 180:
        return cleaned[: sentence_end + 1]
    return f"{cleaned[:limit].rstrip()}..."


def _safe_fallback_reason(reason: str) -> str:
    normalized = _normalize(reason)
    if "429" in normalized or "rate" in normalized:
        return "rate_limited"
    if "timeout" in normalized or "timed out" in normalized:
        return "timeout"
    if "not configured" in normalized or "unavailable" in normalized:
        return "service_unavailable"
    return "generation_error"


def _rerank_reasons_summary(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    return [
        {
            "rank": index,
            "title": _display_title(chunk),
            "reranked_score": chunk.reranked_score if chunk.reranked_score is not None else chunk.relevance_score,
            "reasons": chunk.rerank_reasons or [],
        }
        for index, chunk in enumerate(chunks, start=1)
    ]


def _strip_source_lines(answer: str) -> str:
    lines = [
        line.rstrip()
        for line in str(answer or "").splitlines()
        if not re.match(r"^\s*sources?\s*:", line, flags=re.I)
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _sources_from_chunks(chunks: list[RetrievedChunk], *, merge_articles: bool = False) -> list[dict[str, Any]]:
    from app.services.document_storage import resolve_citation_document, source_page_url, source_view_url

    def _citation_fields(
        *,
        document_id: str | None,
        page: int | None,
        metadata: dict[str, Any],
        chunk: RetrievedChunk,
        index: int,
    ) -> dict[str, Any]:
        source_filename = str(
            chunk.source_filename or metadata.get("source_filename") or ""
        ).strip() or None
        ready_row = resolve_citation_document(
            document_id,
            source_filename=source_filename,
        )
        pdf_ready = ready_row is not None
        # Prefer the Postgres source_documents.id so /documents/{id}/source works
        # even when Chroma still carries a stale ingest UUID.
        resolved_document_id = ready_row.id if ready_row is not None else document_id
        resolved_page = page or _page_number(metadata, chunk.text)
        page_end = _page_end_number(metadata, resolved_page)
        section = _source_section(metadata) or _hierarchy_path(metadata) or None
        # Prefer the service/article title for section crop (cleaner than hierarchy path).
        section_for_clip = (
            str(metadata.get("title") or metadata.get("source_section") or section or "")
            .strip()
            or None
        )
        # Charter services often continue onto the next page. Soft-extend by one
        # page when end is unknown; section crop removes the following service.
        if (
            page_end is not None
            and resolved_page is not None
            and page_end == resolved_page
            and section_for_clip
        ):
            page_end = resolved_page + 1
        elif page_end is None and resolved_page is not None and section_for_clip:
            page_end = resolved_page + 1
        view_url = (
            source_view_url(resolved_document_id, resolved_page)
            if pdf_ready and resolved_document_id
            else None
        )
        page_url = (
            source_page_url(
                resolved_document_id,
                resolved_page,
                page_end=page_end,
                section=section_for_clip,
            )
            if pdf_ready and resolved_document_id and resolved_page
            else None
        )
        note = None if pdf_ready else (
            "PDF source unavailable. Re-index this document to enable PDF viewing."
        )
        page_range = None
        if resolved_page is not None:
            if page_end is not None and page_end != resolved_page:
                page_range = f"{resolved_page}-{page_end}"
            else:
                page_range = str(resolved_page)
        return {
            "page": resolved_page,
            "page_number": resolved_page,
            "page_end": page_end,
            "page_range": page_range,
            "citation_id": str(
                metadata.get("chunk_id")
                or f"{resolved_document_id or 'doc'}::{chunk.chunk_index or index}"
            ),
            "document_id": resolved_document_id,
            "source_filename": source_filename,
            "source_section": section,
            "source_excerpt": str(metadata.get("source_excerpt") or "").strip()
            or _text_preview(chunk.text),
            "source_label": _citation_source_label(metadata, source_filename),
            "source_view_url": view_url,
            "source_page_url": page_url,
            "pdf_available": pdf_ready,
            "citation_note": note,
        }

    if not merge_articles:
        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int | None]] = set()
        for index, chunk in enumerate(chunks, start=1):
            metadata = chunk.metadata or {}
            page = _page_number(metadata)
            document_id = str(chunk.document_id or metadata.get("document_id") or "").strip() or None
            item = {
                "title": _display_title(chunk),
                "path": _hierarchy_path(metadata),
                **_citation_fields(
                    document_id=document_id,
                    page=page,
                    metadata=metadata,
                    chunk=chunk,
                    index=index,
                ),
            }
            key = (item["title"], item["path"], item["page"])
            if key in seen:
                continue
            seen.add(key)
            sources.append(item)
        return sources

    grouped: dict[str, dict[str, Any]] = {}
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata or {}
        path = _hierarchy_path(metadata)
        article = str(metadata.get("article") or "").strip()
        title = _display_clean_hierarchy_label(article) if article else _display_title(chunk)
        key = _normalize(f"{title}|{article or path}")
        page = _page_number(metadata)
        document_id = str(chunk.document_id or metadata.get("document_id") or "").strip() or None
        existing = grouped.get(key)
        if existing:
            pages = existing.setdefault("_pages", set())
            if page is not None:
                pages.add(page)
            existing["_matching_sections"] = int(existing.get("_matching_sections") or 1) + 1
            if existing.get("page") is None or (page is not None and page < existing["page"]):
                existing["page"] = page
                existing["page_number"] = page
                fields = _citation_fields(
                    document_id=document_id,
                    page=page,
                    metadata=metadata,
                    chunk=chunk,
                    index=index,
                )
                existing["source_view_url"] = fields["source_view_url"]
                existing["pdf_available"] = fields["pdf_available"]
                existing["citation_note"] = fields["citation_note"]
            continue
        item = {
            "title": title,
            "path": path,
            **_citation_fields(
                document_id=document_id,
                page=page,
                metadata=metadata,
                chunk=chunk,
                index=index,
            ),
            "_matching_sections": 1,
            "_pages": {page} if page is not None else set(),
        }
        # Prefer source_section from explicit section when merging.
        item["source_section"] = _source_section(metadata) or path or None
        grouped[key] = item
    sources = []
    for item in grouped.values():
        pages = sorted(item.pop("_pages", set()))
        matching_sections = int(item.pop("_matching_sections", 1))
        if matching_sections > 1:
            item["matching_sections"] = matching_sections
        if len(pages) > 1:
            item["page_range"] = f"{pages[0]}-{pages[-1]}"
            item["page"] = pages[0]
            item["page_number"] = pages[0]
            item["page_end"] = pages[-1]
            document_id = item.get("document_id")
            section = item.get("title") or item.get("source_section")
            if document_id and pages[0]:
                from app.services.document_storage import source_page_url

                item["source_page_url"] = source_page_url(
                    document_id,
                    pages[0],
                    page_end=pages[-1],
                    section=section,
                )
        sources.append(item)
    return sources


def _citations_from_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        citation_id = str(source.get("citation_id") or f"citation-{index}")
        citations.append(
            {
                "citation_id": citation_id,
                "document_id": source.get("document_id"),
                "source_filename": source.get("source_filename"),
                "source_section": source.get("source_section") or source.get("path"),
                "page_number": source.get("page_number")
                if source.get("page_number") is not None
                else source.get("page"),
                "source_excerpt": source.get("source_excerpt"),
                "source_view_url": source.get("source_view_url"),
                "source_page_url": source.get("source_page_url"),
                "source_label": source.get("source_label"),
                "title": source.get("title"),
                "path": source.get("path"),
                "pdf_available": source.get("pdf_available"),
                "citation_note": source.get("citation_note"),
                "bbox": source.get("bbox"),
                "page_width": source.get("page_width"),
                "page_height": source.get("page_height"),
                "text_position": source.get("text_position"),
            }
        )
    return citations


def _source_section(metadata: dict[str, Any]) -> str:
    for key in (
        "source_section",
        "section_heading",
        "section",
        "article",
        "canonical_topic",
        "title",
    ):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _citation_source_label(
    metadata: dict[str, Any],
    source_filename: str | None = None,
    *,
    fallback: str | None = None,
) -> str:
    """Resolve a display label for Level-2 citation cards."""
    for key in ("source_label", "doc_source_label", "source_title"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    if source_filename:
        stem = Path(source_filename).stem.replace("_", " ").replace("-", " ").strip()
        if stem:
            return stem
        return source_filename
    safe_fallback = (fallback or "").strip()
    return safe_fallback or "Source document"


def _retrieved_debug(
    chunks: list[RetrievedChunk],
    context_filter: dict[int, tuple[bool, list[str]]] | None = None,
) -> list[dict[str, Any]]:
    debug: list[dict[str, Any]] = []
    for rank, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata or {}
        selected_for_context, filter_reasons = (context_filter or {}).get(id(chunk), (False, []))
        debug.append(
            {
                "rank": rank,
                "title": _display_title(chunk),
                "path": _hierarchy_path(metadata),
                "page": _page_number(metadata),
                "content_preview": _text_preview(chunk.text),
                "original_score": chunk.original_score if chunk.original_score is not None else chunk.relevance_score,
                "reranked_score": chunk.reranked_score if chunk.reranked_score is not None else chunk.relevance_score,
                "boost_reasons": chunk.rerank_reasons or [],
                "selected_for_context": selected_for_context,
                "context_filter_reasons": filter_reasons,
                "document_id": chunk.document_id,
                "source_filename": chunk.source_filename,
                "chunk_index": chunk.chunk_index,
            }
        )
    return debug


def _program_collection_outline(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    by_college: dict[str, dict[str, Any]] = {}

    for chunk in chunks:
        metadata = chunk.metadata or {}
        college = _first_matching_path_part(metadata, "college")
        if not college:
            continue
        college_key = _normalize(college)
        group = by_college.get(college_key)
        if group is None:
            group = {"college": college, "programs": [], "_program_keys": set(), "pages": []}
            by_college[college_key] = group
            groups.append(group)

        page = _page_number(metadata)
        if page is not None and page not in group["pages"]:
            group["pages"].append(page)

        for program in _extract_program_names(chunk.text):
            program_key = _normalize(program)
            if program_key in group["_program_keys"]:
                continue
            group["_program_keys"].add(program_key)
            group["programs"].append(program)

    output: list[dict[str, Any]] = []
    for group in groups:
        if not group["programs"]:
            continue
        group.pop("_program_keys", None)
        output.append(group)
    return output


def _extract_program_names(text: str) -> list[str]:
    candidates: list[str] = []
    cleaned = (text or "").replace("\r", "\n")
    for line in cleaned.splitlines():
        stripped = line.strip(" \t-*•")
        if not stripped:
            continue
        if re.match(r"^(?:programs?|courses?|degrees?)\s*:", stripped, flags=re.I):
            stripped = re.sub(r"^(?:programs?|courses?|degrees?)\s*:\s*", "", stripped, flags=re.I)
        if _line_is_program_candidate(stripped):
            candidates.extend(_split_program_candidates(stripped))

    if not candidates:
        match = re.search(r"\bPrograms?\s*:\s*(.+)", cleaned, flags=re.I | re.S)
        if match:
            candidates.extend(_split_program_candidates(match.group(1)))

    programs: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        program = _clean_program_name(candidate)
        if not program or _is_generic_program_label(program):
            continue
        key = _normalize(program)
        if key in seen:
            continue
        seen.add(key)
        programs.append(program)
    return programs


def _line_is_program_candidate(line: str) -> bool:
    return bool(
        re.search(
            r"\b(?:B\.?S\.?|Bachelor|Master|Doctor|PhD|M\.?S\.?|M\.?A\.?|AB|BEED|BSED)\b",
            line,
            flags=re.I,
        )
    )


def _split_program_candidates(text: str) -> list[str]:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    collapsed = re.sub(r"\b(?:Campuses?|Campus)\s*:\s*.*$", "", collapsed, flags=re.I).strip()
    parts = re.split(r"\s*(?:,|;|\band\b|\n)\s*", collapsed)
    return [part for part in parts if part.strip()]


def _clean_program_name(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip(" .:-")
    cleaned = re.sub(r"^(?:programs?|courses?|degrees?)\s*:\s*", "", cleaned, flags=re.I)
    return cleaned


def _is_generic_program_label(value: str) -> bool:
    normalized = _normalize(value)
    generic = {
        "engineering",
        "computer studies",
        "agriculture",
        "business",
        "education",
        "arts and sciences",
        "arts sciences",
        "undergraduate programs",
        "graduate studies",
        "programs",
        "courses",
    }
    if normalized in generic:
        return True
    return bool(re.fullmatch(r"(?:college|department|campus|programs?)\s+of\s+.+", normalized))


def _page_range_label(pages: list[int]) -> str:
    sorted_pages = sorted(set(pages))
    if not sorted_pages:
        return "Not specified"
    if len(sorted_pages) == 1:
        return str(sorted_pages[0])
    return f"{sorted_pages[0]}-{sorted_pages[-1]}"


def _raw_chunk_matches_collection_intent(chunk_id: str, text: str, metadata: dict[str, Any], intent: str) -> bool:
    haystack = _normalize(
        " ".join(
            [
                chunk_id,
                text,
                *[str(metadata.get(key) or "") for key in ("title", "chapter", "article", "section", "appendix", "category", "doc_category", "source_filename", "content_type")],
            ]
        )
    )
    terms = {
        PROGRAM_COLLECTION: (
            "curricular offerings",
            "college",
            "programs",
            "program",
            "campuses",
            "undergraduate programs",
            "graduate studies",
            "degree",
            "course",
        ),
        OFFICE_COLLECTION: (
            "office",
            "registrar",
            "accounting",
            "guidance",
            "admissions",
            "admission",
            "cashier",
            "osas",
            "library",
            "department",
        ),
        SERVICE_COLLECTION: (
            "student services",
            "institutional student programs",
            "guidance",
            "library",
            "health",
            "counseling",
            "service",
            "services",
            "osas",
        ),
        SCHOLARSHIP_COLLECTION: (
            "scholarship",
            "financial assistance",
            "grant",
            "grants",
            "aid",
            "osas",
        ),
        REQUIREMENT_COLLECTION: (
            "requirements",
            "requirement",
            "checklist",
            "forms",
            "form",
            "documents",
            "document",
            "application",
            "clearance",
        ),
        POLICY_COLLECTION: (
            "policy",
            "policies",
            "rules",
            "guidelines",
            "academic policies",
            "student policies",
        ),
    }
    return _contains_any(haystack, terms.get(intent, ()))


def _retrieved_from_raw_chunk(raw_chunk: dict[str, Any], intent: str) -> RetrievedChunk:
    metadata = dict(raw_chunk.get("metadata") or {})
    chunk_id = str(raw_chunk.get("id") or "")
    document_id = str(metadata.get("document_id") or chunk_id.split("::", 1)[0] or "")
    chunk_index = _chunk_index_from_id(chunk_id, metadata)
    return RetrievedChunk(
        document_id=document_id,
        title=str(metadata.get("title") or "LSPU Handbook"),
        source_filename=str(metadata.get("source_filename") or ""),
        chunk_index=chunk_index,
        text=str(raw_chunk.get("text") or ""),
        relevance_score=1.0,
        original_score=1.0,
        reranked_score=1.0,
        rerank_reasons=[f"collection_intent:{intent}"],
        metadata=metadata,
    )


def _chunk_index_from_id(chunk_id: str, metadata: dict[str, Any]) -> int:
    value = metadata.get("chunk_index")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    tail = chunk_id.rsplit("::", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _collection_sort_key(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    return _normalize(
        " > ".join(
            str(metadata.get(key) or "")
            for key in ("chapter", "article", "section")
            if metadata.get(key)
        )
    )


def _collection_query_score(chunk: RetrievedChunk, normalized_query: str) -> int:
    haystack = _chunk_search_text(chunk)
    score = 0
    for token in _meaningful_tokens(normalized_query):
        if token in haystack:
            score += 2
    college_terms = (
        "computer studies",
        "engineering",
        "agriculture",
        "business",
        "education",
        "arts",
        "law",
        "nursing",
        "hospitality",
    )
    for term in college_terms:
        if term in normalized_query and term in haystack:
            score += 6
    return score


def _program_scope_from_query(normalized_query: str) -> dict[str, Any]:
    return {
        "detected_college_scope": _program_query_college_filter(normalized_query),
        "detected_campus_scope": _program_query_campus_filter(normalized_query),
        "scope_filter_applied": False,
        "chunks_before_scope_filter": 0,
        "chunks_after_scope_filter": 0,
        "excluded_scope_reasons": [],
    }


def _program_query_college_filter(normalized_query: str) -> str | None:
    aliases = {
        "college of engineering": ("college of engineering", "engineering"),
        "college of computer studies": ("college of computer studies", "ccs", "computer studies"),
        "college of agriculture": ("college of agriculture", "agriculture"),
        "college of arts and sciences": ("college of arts and sciences", "arts and sciences", "cas"),
        "college of teacher education": ("college of teacher education", "teacher education", "cte", "education"),
        "college of business management and accountancy": (
            "college of business management and accountancy",
            "business management and accountancy",
            "business",
            "accountancy",
            "cbma",
        ),
        "college of law": ("college of law", "law"),
    }
    for college, terms in aliases.items():
        if any(_query_contains_scope_term(normalized_query, term) for term in terms):
            return college
    return None


def _program_query_campus_filter(normalized_query: str) -> str | None:
    campuses = {
        "sta. cruz": ("sta. cruz", "sta cruz", "santa cruz"),
        "siniloan": ("siniloan",),
        "san pablo city": ("san pablo city", "san pablo"),
        "los banos": ("los banos", "los baños"),
        "all campuses": ("all campuses",),
    }
    for campus, terms in campuses.items():
        if any(_query_contains_scope_term(normalized_query, term) for term in terms):
            return campus
    return None


def _query_contains_scope_term(normalized_query: str, term: str) -> bool:
    normalized_term = _normalize_ascii(term)
    normalized_query_ascii = _normalize_ascii(normalized_query)
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized_query_ascii))


def _chunk_matches_requested_college(chunk: RetrievedChunk, requested_college: str) -> bool:
    haystack = _program_scope_haystack(chunk)
    requested = _normalize_ascii(requested_college)
    if _fuzzy_scope_match(haystack, requested):
        return True
    college_tail = requested.replace("college of ", "")
    if _fuzzy_scope_match(haystack, college_tail):
        return True
    tokens = [token for token in re.findall(r"[a-z0-9]+", college_tail) if token not in {"and", "of"}]
    return bool(tokens) and all(token in haystack for token in tokens)


def _chunk_matches_requested_campus(chunk: RetrievedChunk, requested_campus: str) -> bool:
    haystack = _program_scope_haystack(chunk)
    if _fuzzy_scope_match(haystack, "all campuses"):
        return True
    campus_aliases = {
        "sta. cruz": ("sta cruz", "sta. cruz", "santa cruz"),
        "siniloan": ("siniloan",),
        "san pablo city": ("san pablo city", "san pablo"),
        "los banos": ("los banos", "los baños"),
        "all campuses": ("all campuses",),
    }
    aliases = campus_aliases.get(requested_campus, (requested_campus,))
    return any(_fuzzy_scope_match(haystack, _normalize_ascii(alias)) for alias in aliases)


def _program_scope_haystack(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    values = [
        _display_title(chunk),
        _hierarchy_path(metadata),
        chunk.title,
        chunk.source_filename,
        chunk.text,
    ]
    values.extend(str(metadata.get(key) or "") for key in metadata)
    return _normalize_ascii(" ".join(values))


def _fuzzy_scope_match(haystack: str, needle: str) -> bool:
    normalized_needle = _normalize_ascii(needle)
    if not normalized_needle:
        return False
    if normalized_needle in haystack:
        return True
    tokens = [token for token in re.findall(r"[a-z0-9]+", normalized_needle) if token not in {"college", "of", "and", "the"}]
    return bool(tokens) and all(token in haystack for token in tokens)


def _normalize_ascii(text: str) -> str:
    normalized = _normalize(text).replace("ñ", "n")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _collection_group_key(chunk: RetrievedChunk, intent: str) -> str:
    metadata = chunk.metadata or {}
    if intent == PROGRAM_COLLECTION:
        college = _first_matching_path_part(metadata, "college")
        if college:
            return f"college:{_normalize(college)}"
    article = str(metadata.get("article") or "").strip()
    if article:
        return f"article:{_normalize(article)}"
    section = str(metadata.get("section") or "").strip()
    if section:
        return f"section:{_normalize(section)}"
    return f"{chunk.document_id}:{chunk.chunk_index}"


def _collection_display_group(chunk: RetrievedChunk, domain: str | None) -> str:
    metadata = chunk.metadata or {}
    if domain == "curricular":
        college = _first_matching_path_part(metadata, "college")
        if college:
            return college
    article = str(metadata.get("article") or "").strip()
    if article:
        return _display_clean_hierarchy_label(article)
    chapter = str(metadata.get("chapter") or "").strip()
    if chapter:
        return _display_clean_hierarchy_label(chapter)
    return _display_title(chunk)


def _display_title(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    for key in (
        "source_section",
        "canonical_topic",
        "procedure_title",
        "title",
        "section",
        "article",
        "chapter",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = _display_clean_hierarchy_label(value)
            if cleaned.lower().startswith("requirement:"):
                continue
            return cleaned
    return chunk.title or "Untitled"


def _display_clean_hierarchy_label(value: str) -> str:
    cleaned = value.strip()
    # Drop extraction breadcrumb scaffolding: "Parent > Child > Leaf" → leaf.
    if " > " in cleaned:
        parts = [part.strip() for part in cleaned.split(">") if part.strip()]
        if len(parts) >= 2:
            leaf = parts[-1]
            first = parts[0]
            if not re.match(
                r"^(chapter|article|sec\.?|section|appendix)\s+[\w.-]+",
                first,
                flags=re.I,
            ):
                cleaned = leaf
            else:
                cleaned = cleaned.split(">", 1)[-1].strip()
    # Drop trailing mid-word truncation markers often left by PDF extractors.
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _hierarchy_path(metadata: dict[str, Any]) -> str:
    parts = [
        str(metadata.get(key))
        for key in ("chapter", "article", "section", "appendix", "source_section", "title")
        if metadata.get(key)
    ]
    # Prefer a compact path; drop duplicates while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        key = part.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(part)
    return " > ".join(unique)


def _page_number(metadata: dict[str, Any], text: str | None = None) -> int | None:
    page = metadata.get("page_number") or metadata.get("page_start") or metadata.get("page")
    if isinstance(page, int):
        return page
    if isinstance(page, str) and page.isdigit():
        return int(page)
    if text:
        match = re.search(r"(?im)^\s*Page:\s*(\d+)\s*$", text)
        if match:
            return int(match.group(1))
    return None


def _page_end_number(metadata: dict[str, Any], page_start: int | None) -> int | None:
    end = metadata.get("page_end")
    if isinstance(end, str) and end.isdigit():
        end = int(end)
    if isinstance(end, int) and end > 0:
        if page_start is None or end >= page_start:
            return end
    return page_start


def _page_label(metadata: dict[str, Any]) -> str:
    start = _page_number(metadata)
    end = metadata.get("page_end")
    if isinstance(end, str) and end.isdigit():
        end = int(end)
    if start is None:
        return "Not specified"
    if isinstance(end, int) and end != start:
        return f"{start}-{end}"
    return str(start)


def _text_preview(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= PREVIEW_CHARS:
        return cleaned
    return f"{cleaned[:PREVIEW_CHARS].rstrip()}..."


def _context_filter_reasons(
    *,
    chunk: RetrievedChunk,
    normalized_query: str,
    query_domain: str | None,
    top_score: float,
    rank: int,
    broad_query: bool = False,
) -> list[str]:
    reasons: list[str] = []
    score = _chunk_score(chunk)
    if rank == 1:
        reasons.append("keep_rank_1")
    if top_score - score <= 0.08 and score >= 0.55:
        reasons.append("keep_close_to_rank_1")
    if query_domain and _chunk_matches_domain(chunk, query_domain):
        reasons.append(f"keep_same_domain:{query_domain}")
    if _title_path_matches_query_intent(chunk, normalized_query):
        reasons.append("keep_title_path_intent_match")
    if _positive_reasons(chunk) and not _has_strong_penalty(chunk):
        reasons.append("keep_positive_boost_without_strong_penalty")
    if broad_query and query_domain and _broad_chunk_matches_domain(chunk, query_domain):
        reasons.append(f"keep_broad_domain:{query_domain}")
    if broad_query and top_score - score <= 0.22 and score >= 0.55 and not _looks_like_noise(chunk):
        reasons.append("keep_broad_relevant_score_window")
    if _has_strong_penalty(chunk):
        reasons.append("drop_strong_penalty")
    if broad_query and _looks_like_noise(chunk):
        reasons.append("drop_broad_noise")
    return reasons


def _chunk_score(chunk: RetrievedChunk) -> float:
    return float(chunk.reranked_score if chunk.reranked_score is not None else chunk.relevance_score)


def _positive_reasons(chunk: RetrievedChunk) -> list[str]:
    return [
        reason
        for reason in (chunk.rerank_reasons or [])
        if reason.startswith("boost_") or reason.endswith("_match") or reason.endswith("_policy")
    ]


def _has_strong_penalty(chunk: RetrievedChunk) -> bool:
    strong_markers = (
        "penalty_unrequested_",
        "penalty_disciplinary",
        "penalty_unrelated_procedure",
        "penalty_awards",
        "penalty_retention_awards",
        "penalty_sample_document",
    )
    return any(reason.startswith(strong_markers) for reason in (chunk.rerank_reasons or []))


def _detected_query_domain(normalized_query: str) -> str | None:
    domain_terms = {
        "attendance": ("attendance", "absent", "absence", "excuse", "medical certificate", "illness"),
        "shifting": ("shift", "shifting"),
        "retention": ("retention", "scholastic delinquency", "probation", "dismissal", "dropped", "failed units"),
        "graduation": ("graduation", "graduate requirements", "candidate for graduation", "clearance", "diploma"),
        "curricular": ("curricular", "program", "course offering", "campus offer", "offered by", "college of"),
        "services": ("services", "osas", "office", "offices", "guidance", "registrar", "student services"),
        "scholarships": ("scholarship", "scholarships", "financial assistance", "grants"),
        "enrollment": ("enroll", "enrollment", "registration", "how do i enroll"),
        "records": ("tor", "transcript", "copy of grades", "student records", "certificate of registration"),
        "counseling": ("counseling", "counselling", "guidance office", "who handles counseling"),
    }
    for domain, terms in domain_terms.items():
        if _contains_any(normalized_query, terms):
            return domain
    return None


def _chunk_matches_domain(chunk: RetrievedChunk, domain: str | None) -> bool:
    if not domain:
        return False
    domain_terms = {
        "attendance": ("attendance", "excuse slip", "medical certificate", "absence", "osas"),
        "shifting": ("shifting of course", "shifting", "shift"),
        "retention": ("retention", "scholastic delinquency", "probation", "dismissal", "dropped"),
        "graduation": ("graduation", "candidate for graduation", "clearance", "diploma"),
        "curricular": ("curricular offerings", "undergraduate programs", "graduate studies", "programs", "college of"),
        "services": ("services", "office", "guidance", "osas", "registrar", "student services"),
        "scholarships": ("scholarship", "financial assistance", "grants", "osas"),
        "enrollment": ("enrollment", "registration", "registrar", "assessment of fees"),
        "records": ("transcript of records", "tor", "student records", "registrar", "copy of grades"),
        "counseling": ("guidance", "counseling", "counselling", "guidance office", "student services"),
    }
    return _contains_any(_chunk_search_text(chunk), domain_terms[domain])


def _broad_chunk_matches_domain(chunk: RetrievedChunk, domain: str | None) -> bool:
    if not domain:
        return False
    domain_terms = {
        "curricular": ("curricular offerings", "college", "programs", "campuses", "undergraduate programs", "graduate studies"),
        "services": ("services", "office", "guidance", "osas", "registrar", "student services"),
        "scholarships": ("scholarship", "financial assistance", "grants", "osas"),
        "graduation": ("graduation requirements", "candidate for graduation", "clearance", "requirements"),
        "enrollment": ("enrollment", "registration", "registrar"),
        "records": ("transcript of records", "tor", "student records", "registrar"),
        "counseling": ("guidance", "counseling", "guidance office"),
    }
    return _contains_any(_chunk_search_text(chunk), domain_terms.get(domain, ()))


def _title_path_matches_query_intent(chunk: RetrievedChunk, normalized_query: str) -> bool:
    title_path = _normalize(f"{_display_title(chunk)} {_hierarchy_path(chunk.metadata or {})}")
    query_tokens = _meaningful_tokens(normalized_query)
    if not query_tokens:
        return False
    matches = sum(1 for token in query_tokens if token in title_path)
    return matches >= 2 or (matches >= 1 and _chunk_score(chunk) >= 0.72)


def _is_broad_context_query(normalized_query: str) -> bool:
    return _contains_any(
        normalized_query,
        ("graduation requirements", "requirements", "procedure", "procedures", "process", "steps"),
    )


def _has_named_service_anchor(normalized_query: str) -> bool:
    """True when the question targets one known campus service/topic."""
    return _contains_any(
        normalized_query,
        (
            "enrollment",
            "enroll",
            "transcript",
            "tor",
            "good moral",
            "id validation",
            "student id",
            "scholarship",
            "financial assistance",
            "library reference",
            "entrance exam",
            "entrance examination",
            "dropping",
            "drop a subject",
            "drop subject",
            "ojt",
            "on-the-job",
            "statement of account",
            "web posting",
            "icts",
            "certified true copy",
            "citizen",
            "charter",
            "edition",
            "inc",
            "removal",
        ),
    )


def _is_factual_detail_cue(normalized_query: str) -> bool:
    return _contains_any(
        normalized_query,
        (
            "how much",
            "how long",
            "how many",
            "fee",
            "fees",
            "cost",
            "price",
            "processing time",
            "who may",
            "who can avail",
            "which office",
            "what office",
            "responsible",
            "what documents",
            "what additional",
            "what must",
            "what edition",
            "what year",
            "vision",
            "per page",
            "per unit",
            "requirements for",
            "requirement for",
            "documents required",
            "documents may be required",
        ),
    )


def _is_factual_charter_query(normalized_query: str) -> bool:
    """Fees, times, who-may-avail, edition, and similar detail questions."""
    return _is_factual_detail_cue(normalized_query)


def _charter_metadata_context_lines(metadata: dict[str, Any]) -> list[str]:
    """Surface structured charter fields in Groq context when present."""
    lines: list[str] = []
    mapping = (
        ("office", "Office"),
        ("who_may_avail", "Who May Avail"),
        ("total_processing_time", "Total Processing Time"),
        ("total_fees", "Fees"),
        ("source_label", "Source Label"),
        ("document_edition", "Document Edition"),
        ("charter_edition", "Charter Edition"),
        ("extraction_quality", "Extraction Quality"),
    )
    for key, label in mapping:
        value = str(metadata.get(key) or "").strip()
        if value and value.lower() not in {"none", "null", "n/a", "[needs review]"}:
            lines.append(f"{label}: {value}")
    for key, label in (
        ("extracted_requirements", "Structured Requirements"),
        ("extracted_steps", "Structured Steps"),
    ):
        raw = metadata.get(key)
        if not raw:
            continue
        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=True)
        text = text.strip()
        if text and text not in {"[]", "{}", "null"}:
            lines.append(f"{label}: {text[:1200]}")
    return lines


def _is_specific_query(normalized_query: str) -> bool:
    specific_patterns = (
        r"\bwhat is scholastic delinquency\b",
        r"\bwhere can i get an excuse slip\b",
        r"\bwho is (?:the )?(?:university )?president\b",
        r"\bwhat happens if i fail\b",
        r"\bwarning and probation rules\b",
        r"\bshift(?:ing)? (?:of )?course\b",
        r"\bshift course\b",
        r"\bshift(?:ing)?\b.*\b(?:course|program)\b",
        r"\b25\s*(?:percent|%)\b.*\b(?:class|grade)\b",
        r"\bfail\s+75\s*%\b",
        r"\b75\s*%\s+of my units\b",
        r"\bwhat edition\b",
        r"\bcitizen(?:'s)? charter\b",
        r"\bhow much (?:is|are|does)\b",
        r"\btranscript of records cost\b",
        r"\bmaximum residence\b",
        r"\bhonorable dismissal\b",
        r"\brefund\b",
        r"\bhow long (?:is|does|should)\b",
        r"\bwhich office\b",
        r"\bwho may avail\b",
    )
    if any(re.search(pattern, normalized_query) for pattern in specific_patterns):
        return True
    # Named service + detail cue => normal RAG, not collection sweep.
    if _has_named_service_anchor(normalized_query) and _is_factual_detail_cue(normalized_query):
        return True
    return False


def _is_out_of_scope_query(normalized_query: str) -> bool:
    if _contains_any(
        normalized_query,
        (
            "president of the philippines",
            "president philippines",
            "president marcos",
            "weather today",
            "weather forecast",
            "capital of japan",
            "capital city of japan",
        ),
    ):
        return True
    external_terms = (
        "philippines",
        "japan",
        "weather",
        "forecast",
        "google",
        "microsoft",
        "openai",
        "united states",
    )
    handbook_terms = (
        "lspu",
        "university",
        "handbook",
        "charter",
        "citizen",
        "student",
        "registrar",
        "admission",
        "graduation",
        "scholastic",
        "retention",
        "tor",
        "transcript",
        "program",
        "scholarship",
        "guidance",
        "enrollment",
        "library",
        "osas",
        "vision",
        "edition",
    )
    return _contains_any(normalized_query, external_terms) and not _contains_any(normalized_query, handbook_terms)


def _looks_like_noise(chunk: RetrievedChunk) -> bool:
    noise_terms = (
        "foreword",
        "prayer",
        "table of contents",
        "contents",
        "award",
        "awards",
        "honors",
        "major offense",
        "minor offense",
        "offenses",
        "disciplinary",
        "sample",
        "dummy",
    )
    content_type = _normalize(str((chunk.metadata or {}).get("content_type") or ""))
    return _contains_any(_chunk_search_text(chunk), noise_terms) or content_type in {
        "disciplinary_rule",
        "offense",
    }


def _context_group_key(chunk: RetrievedChunk, normalized_query: str) -> str:
    metadata = chunk.metadata or {}
    domain = _detected_query_domain(normalized_query)
    if domain == "curricular":
        college = _first_matching_path_part(metadata, "college")
        if college:
            return f"college:{_normalize(college)}"
    if domain in {"services", "scholarships", "graduation"}:
        section = str(metadata.get("section") or "").strip()
        if section:
            return f"section:{_normalize(section)}"
    for key in ("article", "section", "chapter"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{_normalize(value)}"
    return f"{chunk.document_id}:{chunk.chunk_index}"


def _first_matching_path_part(metadata: dict[str, Any], text: str) -> str:
    for key in ("chapter", "article", "section", "appendix"):
        value = metadata.get(key)
        if not isinstance(value, str):
            continue
        for part in value.split(">"):
            if text in _normalize(part):
                return part.strip()
    return ""


def _grouped_context_summary(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        metadata = chunk.metadata or {}
        group = _first_matching_path_part(metadata, "college") or str(metadata.get("article") or metadata.get("chapter") or _display_title(chunk))
        key = _normalize(group)
        item = grouped.setdefault(
            key,
            {
                "group": group,
                "chunk_count": 0,
                "titles": [],
            },
        )
        item["chunk_count"] += 1
        title = _display_title(chunk)
        if title not in item["titles"]:
            item["titles"].append(title)
    return list(grouped.values())


def _chunk_search_text(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    return _normalize(f"{_display_title(chunk)} {_hierarchy_path(metadata)} {chunk.text}")


def _meaningful_tokens(text: str) -> set[str]:
    stop_words = {
        "what",
        "which",
        "should",
        "about",
        "after",
        "with",
        "from",
        "that",
        "this",
        "available",
        "offered",
        "under",
    }
    return {token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 4 and token not in stop_words}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    return any(_normalize(term) in normalized for term in terms)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

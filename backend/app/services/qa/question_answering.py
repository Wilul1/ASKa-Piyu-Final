"""Production ASKa-Piyu RAG orchestration."""

from __future__ import annotations

import logging
import math
import re
import json
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple, Sequence

from app.config import settings
from app.services.chroma_store import RetrievedChunk, get_knowledge_base_store
from app.services.qa.conversational_fallback import (
    format_conversational_fallback,
    query_matches_retrieval_title,
)
from app.services.qa.groq_answer_service import GroqAnswerError, generate_groq_answer
from app.services.qa.multi_facet import (
    EMPTY_EVIDENCE,
    FacetCoverage,
    FacetEvidence,
    QuestionFacet,
    analyze_facet_coverage,
    build_cross_article_notes,
    build_facet_evidence,
    build_grounding_notes,
    combine_grounding_notes,
    distinct_source_articles,
    facet_recovery_keys,
    facet_retrieval_queries,
    partition_off_topic,
    split_question_facets,
)
from app.services.knowledge_taxonomy import (
    DEFAULT_CATEGORY,
    DEFAULT_SUBCATEGORY,
    GENERIC_SERVICE_NAME_TOKENS,
    LOW_CONFIDENCE_THRESHOLD,
    classify_question,
    has_distinctive_token,
    load_taxonomy,
    taxonomy_service_names_in_text,
    validate_active_service_identity,
)
from app.services.retrieval_reranker import (
    GENERIC_INTENT_TOKENS,
    NON_TOPICAL_RERANK_REASONS,
    is_faculty_restricted_query,
    prepare_retrieval_query,
    taxonomy_service_title_match,
)
from app.services.qa.service_answer_formatter import (
    format_requirements_detail_answer,
    format_service_procedure_answer,
    is_artifact_or_requirement_form_chunk,
    is_factual_service_detail_query,
    is_form_or_requirement_query,
    is_service_howto_query,
    is_service_procedure_chunk,
    prefer_service_chunks,
    _has_usable_service_fields,
)
logger = logging.getLogger(__name__)


class EmptyKnowledgeBaseError(ValueError):
    """Raised when the knowledge base has no indexed chunks to search."""


FINAL_CONTEXT_CHUNKS = 7
RAW_RETRIEVAL_CANDIDATES = 40
# Marks context added to cover a question topic top-k dropped.
FACET_RECOVERY_REASON = "facet_recovery"
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
    # Set only when citation_verification_mode is "async_shadow"/"async_llm":
    # "verifying" (a background verification job's inputs were frozen and
    # handed to the caller via async_verification_sink -- the caller is
    # responsible for actually scheduling the job) or
    # "verification_unavailable" (nothing to verify -- zero claims or zero
    # candidates, the same fail-closed condition the synchronous modes
    # already detect, just known before any job would be created). None for
    # every other mode -- existing lexical/shadow/llm behavior is unchanged.
    citation_status: str | None = None
    # Machine-readable, taxonomy-validated service identity for this turn —
    # `None` when no specific service applies (greeting, out-of-scope, vague
    # clarification, broad/collection question). A client may store this and
    # echo it back on the next call as `client_active_service` so a slot-only
    # follow-up's active service does not depend on scanning assistant prose.
    active_service: str | None = None


def _record_answer_rewrite(
    sink: dict[str, Any] | None,
    *,
    evidence_bearing_answer: str | None,
    table_inversion_corrected: bool,
    classification_template_applied: bool,
    used_recovered: bool,
) -> None:
    """Observationally record answer-rewrite diagnostics for offline capture.

    Mirrors ``generation_usage_sink``'s existing contract: purely additive,
    never read back by ``answer_qa_question`` itself (so it cannot influence
    the answer), and any failure while recording must never propagate and
    change what is actually returned to the caller.
    """
    if sink is None:
        return
    try:
        sink["evidence_bearing_answer"] = evidence_bearing_answer or None
        sink["table_inversion_corrected"] = bool(table_inversion_corrected)
        sink["classification_template_applied"] = bool(classification_template_applied)
        sink["used_recovered"] = bool(used_recovered)
    except Exception:
        logger.debug("answer_rewrite_sink: failed to record diagnostics", exc_info=True)


def _record_generation_context(
    sink: dict[str, Any] | None,
    *,
    generation_invoked: bool,
    generation_succeeded: bool,
    status: str,
    chunks: list[RetrievedChunk] | None = None,
) -> None:
    """Observationally record the exact final chunks passed as the
    ``context`` argument to ``generate_groq_answer``.

    There is exactly one ``generate_groq_answer`` call site in this module
    (verified by inspection, not assumed -- see
    ``scripts/citation_grounding_capture.py``'s module docstring for the
    trace). ``chunks`` must always be the fully-finalized
    ``selected_context`` -- i.e. captured strictly AFTER both
    ``_restore_missing_facet_context`` and (when applicable)
    ``_prefer_active_topic_context`` have already run -- never the earlier
    ``selected_for_context`` flags recorded on ``retrieved_chunks`` debug
    rows, which reflect an intermediate selection stage that predates both
    of those mutations and is therefore not authoritative for what
    generation actually received.

    ``generation_invoked`` is true whenever ``generate_groq_answer`` was
    actually called for this request; ``generation_succeeded`` additionally
    distinguishes whether that specific call is what the *displayed*
    answer is based on. A call that raised (Groq unavailable, etc.) is
    invoked=True, succeeded=False, and this still records the context that
    was genuinely passed as that call's argument (an honest historical
    fact), not the same claim as "this context produced the answer shown."
    A branch that never calls generation at all (greeting, out-of-scope,
    typed-answer, etc.) is invoked=False with an explicit ``status``
    string and an empty ``final_context_chunks`` -- never a backfilled or
    invented context for a call that never happened.
    """
    if sink is None:
        return
    try:
        sink["generation_invoked"] = bool(generation_invoked)
        sink["generation_succeeded"] = bool(generation_succeeded)
        sink["status"] = status
        if not chunks:
            sink["final_context_chunks"] = []
        else:
            sink["final_context_chunks"] = [
                {
                    "citation_id": _raw_citation_id(chunk, index),
                    "chunk_merge_key": _chunk_merge_key(chunk),
                    "document_id": chunk.document_id or (chunk.metadata or {}).get("document_id"),
                    "chunk_index": chunk.chunk_index,
                    "title": _display_title(chunk),
                    "path": _hierarchy_path(chunk.metadata or {}),
                    "audience": (chunk.metadata or {}).get("audience"),
                }
                for index, chunk in enumerate(chunks, start=1)
            ]
    except Exception:
        logger.debug("generation_context_sink: failed to record diagnostics", exc_info=True)


def answer_qa_question(
    question: str,
    *,
    user_role: str | None = None,
    history: list[Any] | None = None,
    client_active_service: str | None = None,
    citation_debug_sink: list[dict[str, Any]] | None = None,
    generation_usage_sink: dict[str, Any] | None = None,
    answer_rewrite_sink: dict[str, Any] | None = None,
    generation_context_sink: dict[str, Any] | None = None,
    citation_v2_sink: dict[str, Any] | None = None,
    async_verification_sink: dict[str, Any] | None = None,
) -> QAResult:
    cleaned_question = question.strip()
    chat_history = list(history or [])
    # An arbitrary client-supplied value is never trusted directly — only a
    # value that matches a real taxonomy service is used at all, so a
    # stale/removed/spoofed client value cannot steer retrieval.
    validated_client_service = validate_active_service_identity(client_active_service)
    # Greetings / thanks are not KB questions — never retrieve or cite sources.
    if is_greeting_query(cleaned_question):
        _record_generation_context(
            generation_context_sink,
            generation_invoked=False,
            generation_succeeded=False,
            status="not_reached:greeting_short_circuit",
        )
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

    retrieval_question = resolve_followup_question(
        cleaned_question, chat_history, client_active_service=validated_client_service
    )
    active_topic = resolve_turn_active_topic(
        cleaned_question, chat_history, client_active_service=validated_client_service
    )
    # On an explicit service switch ("Now tell me about TOR." after a
    # Dropping conversation), the prior turns' raw text is a *previous*
    # service's own procedural steps/fees, sitting right in the model's
    # recent context alongside this turn's (correct) new-service evidence.
    # Instruction-level framing alone ("outrank stale wording") was not
    # reliably enough to stop that prior text from bleeding into the
    # generated answer, so the prior turns are left out of the generation
    # prompt entirely for this one turn — retrieval/topic resolution above
    # still use the full history unchanged, and once this turn's own
    # (new-service) reply exists, ordinary slot follow-ups resume seeing
    # history normally, preserving continuity within the new topic.
    generation_history = [] if _is_topic_setting_turn(cleaned_question) else chat_history
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
        _record_generation_context(
            generation_context_sink,
            generation_invoked=False,
            generation_succeeded=False,
            status="not_reached:out_of_scope_short_circuit",
        )
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
        _record_generation_context(
            generation_context_sink,
            generation_invoked=False,
            generation_succeeded=False,
            status="not_reached:faculty_topic_hidden_from_role",
        )
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

    if _is_underspecified_question(cleaned_question) and not _has_real_active_topic(active_topic):
        _record_generation_context(
            generation_context_sink,
            generation_invoked=False,
            generation_succeeded=False,
            status="not_reached:underspecified_without_active_topic",
        )
        return QAResult(
            answer=(
                "Which university service or topic are you asking about? "
                "Name the process, office, or document so I can look it up."
            ),
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
            fallback_used=True,
            fallback_reason="underspecified_without_active_topic",
            out_of_scope_detected=False,
        )

    program_scope: dict[str, Any] | None = None
    question_facets: list[QuestionFacet] = []
    facet_evidence: FacetEvidence = EMPTY_EVIDENCE
    if collection_mode and hasattr(store, "list_chunks"):
        retrieved = collect_intent_chunks(store, collection_intent)
        retrieved = _apply_audience_filter(retrieved, role)
        selected_context, context_filter, program_scope = select_collection_context_chunks(
            retrieval_question,
            retrieved,
            collection_intent,
        )
    else:
        retrieval_variants = _retrieval_query_variants(retrieval_question, prepared_query)
        # Bundled questions ("OJT, but I have an INC and unpaid fees") lose their
        # weaker parts to top-k. Retrieve for each part on its own as well, and
        # remember what each part found so coverage can be judged from that.
        question_facets = split_question_facets(retrieval_question)
        retrieval_variants.extend(
            facet_retrieval_queries(question_facets, existing=retrieval_variants)
        )
        if _is_slot_followup_question(cleaned_question) and active_topic:
            # A slot follow-up's resolved retrieval text mixes the active
            # service with the attribute being asked for ("What are the
            # requirements?" + the service name) into one combined string.
            # Also retrieve using the service identity alone, so a
            # dedicated, undiluted pass toward the active service can
            # surface it even when the combined text's own embedding drifts
            # toward the generic attribute wording — the same "retrieve each
            # part separately" pattern already used for bundled-question
            # facets above, applied to conversational topic identity instead
            # of intra-question facets.
            topic_query = _canonical_service_name(active_topic)
            if topic_query and topic_query not in retrieval_variants:
                retrieval_variants.append(topic_query)
        retrieved, retrieved_by_query = _multi_query_retrieve(
            store,
            retrieval_variants,
            top_k=BROAD_RETRIEVAL_CANDIDATES if broad_query else FINAL_CONTEXT_CHUNKS,
            raw_k=BROAD_RETRIEVAL_CANDIDATES if broad_query else RAW_RETRIEVAL_CANDIDATES,
            user_role=role,
        )
        facet_evidence = build_facet_evidence(
            retrieved_by_query,
            question_facets,
            baseline_query=retrieval_question,
        )
        retrieved = prefer_service_chunks(retrieved, question=retrieval_question)
        retrieved = _apply_audience_filter(retrieved, role)
        if _is_slot_followup_question(cleaned_question) and active_topic:
            retrieved = _prefer_active_topic_context(retrieved, active_topic)
        # Sections that no part of the question retrieved must not lead the
        # context just because their wording scores well.
        on_topic, off_topic = partition_off_topic(
            question_facets,
            retrieved,
            facet_evidence,
            key_of=_chunk_merge_key,
        )
        selected_context, context_filter = select_context_chunks(
            retrieval_question,
            on_topic + off_topic,
            broad_query=broad_query,
        )
        selected_context = _restore_missing_facet_context(
            retrieval_question,
            question_facets,
            selected_context,
            retrieved,
            facet_evidence,
        )
    # Slot follow-ups must not keep prior-topic chunks that confuse answer wording.
    if (
        not collection_mode
        and _is_slot_followup_question(cleaned_question)
        and active_topic
    ):
        selected_context = _prefer_active_topic_context(selected_context, active_topic)
    # Which parts of the question the final context can actually answer.
    facet_coverage = (
        FacetCoverage()
        if collection_mode
        else analyze_facet_coverage(
            retrieval_question,
            question_facets,
            selected_context,
            facet_evidence,
            key_of=_chunk_merge_key,
            heading_of=_chunk_heading,
        )
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
    active_service_for_response = _active_service_for_response(active_topic, selected_context)

    if not retrieved:
        _record_generation_context(
            generation_context_sink,
            generation_invoked=False,
            generation_succeeded=False,
            status="not_reached:empty_retrieval",
        )
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
        active_topic=active_topic,
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
        _record_generation_context(
            generation_context_sink,
            generation_invoked=False,
            generation_succeeded=False,
            status="not_reached:retrieval_quality_should_clarify",
        )
        return QAResult(
            answer=answer,
            # Evidence was judged too weak/inconsistent to answer from (that is
            # exactly why this branch asks the user to clarify instead) — the
            # candidate chunks may still be named as an example inside the
            # clarifying text above, but must not also be handed back as
            # citations, or a stale prior-topic chunk that merely survived
            # retrieval looks like relevant, cited evidence for a question it
            # was never actually evidence for.
            sources=[],
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
        _record_generation_context(
            generation_context_sink,
            generation_invoked=False,
            generation_succeeded=False,
            status="not_invoked:typed_answer_used_instead_of_generation",
        )
        return QAResult(
            answer=typed_answer,
            sources=_display_sources_for_answer(
                selected_context, typed_answer, merge_articles=collection_mode,
                debug_sink=citation_debug_sink, citation_v2_sink=citation_v2_sink,
                async_verification_sink=async_verification_sink,
            ),
            citation_status=_citation_status_after_sources(async_verification_sink),
            confidence=_confidence_for(
                retrieved,
                selected_context,
                typed_answer,
                cleaned_question,
                broad_query=broad_query,
                collection_mode=collection_mode,
                facet_coverage=facet_coverage,
                active_topic=active_topic,
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
            active_service=active_service_for_response,
        )

    table_inversion_corrected = False
    classification_template_applied = False
    evidence_bearing_answer = ""
    try:
        article_labels = distinct_source_articles(
            selected_context,
            article_of=_chunk_article_label,
        )
        grounding_notes = combine_grounding_notes(
            build_grounding_notes(facet_coverage),
            build_cross_article_notes(article_labels),
        )
        # Only pass usage_sink at all when instrumentation was actually
        # requested. A test (or any other caller) that patches/fakes
        # generate_groq_answer with the pre-instrumentation signature (no
        # usage_sink parameter, no **kwargs) must keep working unmodified
        # when generation_usage_sink is left at its default of None.
        _generation_kwargs: dict[str, Any] = {}
        if generation_usage_sink is not None:
            _generation_kwargs["usage_sink"] = generation_usage_sink
        answer = generate_groq_answer(
            question=extractor_question,
            context=context,
            broad_mode=broad_query,
            history=generation_history,
            grounding_notes=grounding_notes,
            active_topic=active_topic,
            **_generation_kwargs,
        )
        # Capture the evidence-bearing generated wording before any
        # presentation rewrite. A later classification notice replaces that
        # wording with a generic template that no longer shares the source's
        # facts; citations must still be scored against this text.
        evidence_bearing_answer = answer
        table_records = _structured_table_records_from_text(context)
        if table_records and (
            _answer_contradicts_table_records(answer, table_records)
            or _answer_synthesizes_unsupported_range(answer, table_records)
            or _answer_has_unverifiable_mixed_status_claim(answer, table_records)
        ):
            answer = _table_records_evidence_answer(table_records)
            table_inversion_corrected = True
        elif (
            not table_records
            and _is_global_classification_query(cleaned_question)
            and not _evidence_states_single_global_rule(context)
        ):
            # No structured rows at all (a derived FAQ's bullet/prose
            # rendering that the row parser conservatively declined to
            # interpret, most notably), and the user explicitly asked for a
            # global classification/range/boundary rule the evidence does
            # not clearly state as a single statement. Activation depends
            # only on the fixed user question and the evidence's own shape
            # — never on the model's generated wording — and the same
            # ``context`` already handed to generation, never a second
            # retrieval or an unselected chunk.
            answer = _apply_conservative_classification_reply(answer)
            table_inversion_corrected = True
            classification_template_applied = True
    except GroqAnswerError as exc:
        logger.warning(
            "LLM answer generation unavailable; using conversational fallback. reason=%s",
            str(exc),
        )
        # How-to templates are a solid fallback when Groq is unavailable.
        if typed_answer and is_service_howto_query(extractor_question):
            _record_generation_context(
                generation_context_sink,
                generation_invoked=True,
                generation_succeeded=False,
                status="invoked_but_failed:typed_answer_fallback_used_after_groq_error",
                chunks=selected_context,
            )
            return QAResult(
                answer=typed_answer,
                sources=_display_sources_for_answer(
                    selected_context, typed_answer, merge_articles=collection_mode,
                    debug_sink=citation_debug_sink, citation_v2_sink=citation_v2_sink,
                    async_verification_sink=async_verification_sink,
                ),
                citation_status=_citation_status_after_sources(async_verification_sink),
                confidence=_confidence_for(
                    retrieved,
                    selected_context,
                    typed_answer,
                    extractor_question,
                    broad_query=broad_query,
                    collection_mode=collection_mode,
                    facet_coverage=facet_coverage,
                    active_topic=active_topic,
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
                active_service=active_service_for_response,
            )
        fallback_answer, fallback_confidence, _fallback_sources_unused = _fallback_answer_from_context(
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
        used_recovered = bool(recovered) and (
            not fallback_answer.strip()
            or fallback_answer == OUT_OF_SCOPE_ANSWER
            or _indicates_missing_information(fallback_answer)
            or _should_prefer_recovered_factual(extractor_question, fallback_answer)
            or _prefer_structured_fee_recovery(extractor_question, recovered, fallback_answer)
        )
        if used_recovered:
            fallback_answer = recovered
            fallback_confidence = "medium"
        # `recovered` may draw on the broader retrieval set (see
        # `_recover_factual_charter_answer` above), not only the narrower
        # generation context, so citations match whichever pool actually
        # produced the returned answer text.
        fallback_citation_context = (
            list(retrieved or selected_context) if used_recovered else selected_context
        )
        _record_answer_rewrite(
            answer_rewrite_sink,
            evidence_bearing_answer=evidence_bearing_answer,
            table_inversion_corrected=table_inversion_corrected,
            classification_template_applied=classification_template_applied,
            used_recovered=used_recovered,
        )
        _record_generation_context(
            generation_context_sink,
            generation_invoked=True,
            generation_succeeded=False,
            status="invoked_but_failed:conversational_or_recovered_fallback_used",
            chunks=selected_context,
        )
        return QAResult(
            answer=fallback_answer,
            sources=_display_sources_for_answer(
                fallback_citation_context, fallback_answer, merge_articles=collection_mode,
                debug_sink=citation_debug_sink, citation_v2_sink=citation_v2_sink,
                async_verification_sink=async_verification_sink,
            ),
            citation_status=_citation_status_after_sources(async_verification_sink),
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
            active_service=active_service_for_response,
        )

    confidence = _confidence_for(
        retrieved,
        selected_context,
        answer,
        extractor_question,
        broad_query=broad_query,
        collection_mode=collection_mode,
        facet_coverage=facet_coverage,
        active_topic=active_topic,
    )
    if table_inversion_corrected:
        # The model's own reading of a labeled-value table (grade scale, fee
        # schedule, etc.) was self-contradictory and had to be replaced with
        # a plain restatement of the rows. That restatement is trustworthy as
        # a *listing*, but we no longer have a verified interpretation of it
        # to be confident about — "high" would claim more certainty than a
        # generation the system just had to correct actually earned.
        confidence = "medium" if confidence == "high" else confidence
    final_answer = _student_facing_answer(answer, confidence, user_role=user_role)
    recovered = _recover_factual_charter_answer(
        extractor_question,
        retrieved or selected_context,
        sources,
    )
    used_recovered = bool(recovered) and (
        final_answer == OUT_OF_SCOPE_ANSWER
        or _indicates_missing_information(final_answer)
        or _indicates_missing_information(answer)
        or _should_prefer_recovered_factual(extractor_question, final_answer)
        or _prefer_structured_fee_recovery(extractor_question, recovered, final_answer)
    )
    if used_recovered:
        final_answer = recovered
        confidence = "medium" if confidence == "low" else confidence
    # `recovered` may draw on the broader retrieval set (see
    # `_recover_factual_charter_answer` above), not only the narrower
    # generation context, so citations match whichever pool actually
    # produced the returned answer text.
    citation_context = list(retrieved or selected_context) if used_recovered else selected_context
    # A classification notice is a presentation rewrite of an evidence-bearing
    # answer, not a new source of facts. Score citations against the wording
    # that actually used the retrieved evidence. Recovery and table restatement
    # already *are* the evidence, so they keep scoring the displayed text.
    # Never invent a source: the candidate pool is still selected/retrieved only.
    citation_evidence = None
    if (
        classification_template_applied
        and not used_recovered
        and (evidence_bearing_answer or "").strip()
        and evidence_bearing_answer.strip() != (final_answer or "").strip()
    ):
        citation_evidence = evidence_bearing_answer

    _record_answer_rewrite(
        answer_rewrite_sink,
        evidence_bearing_answer=evidence_bearing_answer,
        table_inversion_corrected=table_inversion_corrected,
        classification_template_applied=classification_template_applied,
        used_recovered=used_recovered,
    )
    _record_generation_context(
        generation_context_sink,
        generation_invoked=True,
        generation_succeeded=True,
        # Real pipeline state (`used_recovered`, already computed above),
        # never inferred: when the offline charter recovery replaced the
        # generated text as the displayed answer, "generation_answer_used"
        # would overstate what actually happened -- the generated text was
        # produced (generation_succeeded=True, a real call did complete),
        # but the RECOVERED text is what the user was shown, not it.
        status=(
            "invoked_and_succeeded:recovery_answer_used"
            if used_recovered
            else "invoked_and_succeeded:generation_answer_used"
        ),
        chunks=selected_context,
    )
    return QAResult(
        answer=final_answer,
        sources=_display_sources_for_answer(
            citation_context,
            final_answer,
            evidence_text=citation_evidence,
            merge_articles=collection_mode,
            debug_sink=citation_debug_sink,
            citation_v2_sink=citation_v2_sink,
            async_verification_sink=async_verification_sink,
        ),
        citation_status=_citation_status_after_sources(async_verification_sink),
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
        active_service=active_service_for_response,
    )


def resolve_followup_question(
    question: str,
    history: list[Any] | None,
    *,
    client_active_service: str | None = None,
) -> str:
    """Expand follow-ups with the *active* conversational topic.

    Active topic = the latest substantive topic-setting user turn (explicit
    service questions and topic switches), skipping slot follow-ups such as
    "how much does it cost?". Older topics before a switch are ignored so
    Topic A → Topic B → follow-up resolves against B only.
    """
    cleaned = (question or "").strip()
    if not cleaned:
        return cleaned

    # Explicit / short topic-setting turns must not inherit the prior topic,
    # including on the first turn (empty history). Expand short taxonomy labels
    # (e.g. TOR) to their canonical service phrase so retrieval targets the KB
    # service, not an unrelated acronym collision.
    if _is_topic_setting_turn(cleaned):
        return _canonical_service_retrieval_phrase(cleaned) or cleaned

    if not history:
        names = _canonical_service_names_in_text(cleaned)
        if names:
            return f"{cleaned}\n\n(Service: {', '.join(names)})"
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
    # and has no follow-up cues — this is an explicit topic switch / new topic.
    standalone = (
        len(content_tokens) >= 2
        and not followup_prefix
        and not has_pronoun
        and len(cleaned.split()) > 6
    )
    # A short question that already names its own service/subject stands on
    # its own even under the 8-word bar ("Who won the latest NBA game?" is 6
    # words but fully self-contained) — without this guard, the word-count
    # heuristic alone misclassified it as a follow-up and grafted the prior
    # turn's active service onto it, dragging stale institutional context
    # into a clearly unrelated new question purely because it was short.
    short_followup = (
        len(cleaned.split()) <= 8
        and not standalone
        and not _question_names_a_service_or_subject(cleaned)
    )
    if not (followup_prefix or has_pronoun or short_followup or _is_slot_followup_question(cleaned)):
        return cleaned

    topic = resolve_active_topic(
        history, fallback_user=last_user, client_active_service=client_active_service
    )
    if not topic:
        return cleaned
    return f"{cleaned}\n\n(Prior question context: {topic})"


def resolve_turn_active_topic(
    question: str,
    history: list[Any] | None,
    *,
    client_active_service: str | None = None,
) -> str:
    """Active topic for the current turn: current message if topic-setting, else history.

    ``client_active_service`` must already be validated by the caller (see
    ``knowledge_taxonomy.validate_active_service_identity``) — an explicit
    topic-setting/new-service question in ``question`` itself always takes
    precedence over it (a real topic switch must replace a stale client-
    carried value, never the other way around).
    """
    cleaned = (question or "").strip()
    if cleaned and not _is_underspecified_question(cleaned):
        if (
            _is_topic_setting_turn(cleaned)
            or len(_content_tokens(cleaned)) >= 2
            or _is_known_service_label(cleaned)
        ):
            # Prefer canonical taxonomy phrasing for grounding/identity matching.
            return (_canonical_service_retrieval_phrase(cleaned) or cleaned)[:240]
    return resolve_active_topic(
        history, fallback_user=cleaned, client_active_service=client_active_service
    )


def _usable_topic_label(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned or _is_underspecified_question(cleaned):
        return ""
    return cleaned[:240]


def resolve_active_topic(
    history: list[Any] | None,
    *,
    fallback_user: str = "",
    client_active_service: str | None = None,
) -> str:
    """Return the active conversational topic/service identity from history.

    Walks user turns newest-first and returns the latest *substantive*
    topic-setting message. Slot follow-ups and vague requests are skipped.
    An explicit topic switch ("Now tell me about TOR.") replaces any older
    topic, including short/acronym service labels present in taxonomy metadata.

    A client may only forward a bounded recent window of the conversation
    (e.g. the last few turns), which can drop the original topic-setting
    question entirely while every *user* turn still in the window is a slot
    follow-up ("What documents do I need?", "Which office handles that?").
    When that happens, the active service is reconstructed from the
    assistant's own past replies that name a taxonomy service —
    deterministic answers already restate the resolved service by name even
    when the user's own wording was generic, so this recovers the topic from
    conversational content already present, independent of how many raw
    messages the window held.

    Scanning assistant prose for a corroborated service name is a fallback
    of last resort, not a trustworthy source of truth: a real reply can
    legitimately mention a prerequisite, related, previous, or next service
    in passing, and no amount of counting/recency heuristics over free-form
    text can fully rule that out. When the caller has a ``client_active_service``
    — a service identity this backend itself returned on an earlier turn in
    *this* conversation, carried by the client and already validated by the
    caller against the taxonomy before being passed in here — that
    machine-readable value is preferred over scanning assistant prose at
    all. Prose-scanning remains only for clients that do
    not yet carry that state (backward compatibility), and even then only
    trusts a service *corroborated* by at least two scanned replies — a
    single, possibly-incidental mention must not silently replace the
    running topic. When neither a validated client value nor a corroborated
    prose match exists, no topic is reconstructed at all; the caller's
    existing "no active topic" handling (clarify rather than guess) applies
    instead — a safe clarification is preferable to a confidently wrong
    office.
    """
    if not history:
        return _usable_topic_label(fallback_user)
    for content in reversed(_history_user_turns(history)):
        if _is_underspecified_question(content):
            continue
        tokens = _content_tokens(content)
        # A deliberate switch/short label (explicit phrasing, or a bare
        # known taxonomy label) is a high-confidence signal that always
        # wins here, canonicalized or not. An ordinary sentence that merely
        # clears the 2-token bar is the same low-confidence prose the
        # docstring above says a validated ``client_active_service`` should
        # take priority over — it only wins on its own, uncanonicalized
        # wording when no validated client state exists to defer to.
        high_confidence_label = _is_topic_setting_turn(content) or (
            len(tokens) == 1 and _is_known_service_label(content)
        )
        if high_confidence_label or len(tokens) >= 2:
            canonical = _canonical_service_retrieval_phrase(content)
            if canonical:
                return canonical[:240]
            if not high_confidence_label and client_active_service:
                return client_active_service[:240]
            return content.strip()[:240]
    if client_active_service:
        return client_active_service[:240]
    primary_names: list[str] = []
    for content in reversed(_history_assistant_turns(history)):
        names = _canonical_service_names_in_text(content)
        if names:
            primary_names.append(names[0])
    if primary_names:
        occurrence_counts: dict[str, int] = {}
        for name in primary_names:
            occurrence_counts[name] = occurrence_counts.get(name, 0) + 1
        newest_candidate = primary_names[0]
        if occurrence_counts[newest_candidate] >= 2:
            return newest_candidate[:240]
    return _usable_topic_label(fallback_user)


_TOPIC_SETTING_PREFIX = re.compile(
    r"(?is)^(?:(?:ok|okay|alright|please|now)[,!]?\s+)*"
    r"(?:(?:can\s+you|could\s+you)\s+)?"
    r"(?:tell\s+me\s+(?:more\s+)?about|what\s+about|how\s+about|"
    r"switch\s+to|go\s+back\s+to|let'?s\s+talk\s+about|"
    r"i\s+(?:want|need)\s+to\s+know\s+about|regarding|about)\s+"
)


def _strip_topic_setting_wrapper(text: str) -> str:
    cleaned = (text or "").strip()
    match = _TOPIC_SETTING_PREFIX.match(cleaned)
    if match:
        return cleaned[match.end() :].strip(" ?.!,;:\"'")
    return cleaned.strip(" ?.!,;:\"'")


def _is_explicit_topic_setting(text: str) -> bool:
    return bool(_TOPIC_SETTING_PREFIX.match((text or "").strip()))


def _is_topic_setting_turn(text: str) -> bool:
    """True for explicit switches and short/acronym service labels from KB metadata."""
    cleaned = (text or "").strip()
    if not cleaned or _is_underspecified_question(cleaned):
        return False
    if _is_explicit_topic_setting(cleaned):
        return True
    if len(cleaned.split()) <= 6 and _is_known_service_label(cleaned):
        return True
    return False


@lru_cache(maxsize=1)
def _service_vocab_sets() -> tuple[frozenset[str], frozenset[str]]:
    """Phrases and single-token labels derived from taxonomy (+ expansion triggers)."""
    phrases: set[str] = set()
    singles: set[str] = set()

    def _add_phrase(raw: str, *, require_distinctive: bool = False) -> None:
        phrase = re.sub(r"\s+", " ", (raw or "").casefold()).strip()
        if not phrase or len(phrase) < 2:
            return
        # Taxonomy names/keywords built entirely from generic bucket words
        # ("Certificates", "Requests", "Application Forms") must not count as
        # a known service label just because the bare word appears — same
        # exclusion `taxonomy_service_matches_in_text` applies, reused here
        # rather than re-deciding "generic" a third way.
        if require_distinctive and not has_distinctive_token(phrase, GENERIC_SERVICE_NAME_TOKENS):
            return
        phrases.add(phrase)
        if " " not in phrase:
            singles.add(phrase)

    for cat in load_taxonomy():
        _add_phrase(cat.name, require_distinctive=True)
        for sub in cat.subcategories:
            _add_phrase(sub.name, require_distinctive=True)
            for keyword in sub.keywords:
                _add_phrase(keyword, require_distinctive=True)

    # Read-only vocabulary enrichment from existing expansion triggers (do not edit rules).
    # Not taxonomy-derived, so the generic-service exclusion above does not apply here.
    try:
        from app.services.retrieval_reranker import QUERY_EXPANSION_RULES

        for rule in QUERY_EXPANSION_RULES:
            for term in rule.trigger_terms:
                _add_phrase(term)
    except Exception:  # pragma: no cover - defensive import guard
        logger.debug("service vocab: expansion triggers unavailable", exc_info=True)

    return frozenset(phrases), frozenset(singles)


@lru_cache(maxsize=1)
def _service_alias_token_map() -> dict[str, frozenset[str]]:
    """Map primary service labels to sibling tokens from the same subcategory.

    Only single-token keywords and subcategory-name tokens are anchors. Tokens
    that merely appear inside a multi-word phrase (e.g. ``enrollment`` inside
    ``graduate enrollment``) must not pull unrelated sibling services.
    """
    mapping: dict[str, set[str]] = {}
    alias_stop = {
        "of", "the", "and", "or", "for", "to", "in", "on", "a", "an", "at", "by",
        "with", "from", "per", "as", "is", "are", "be", "this", "that", "into",
    }

    def _tokens(raw: str) -> set[str]:
        return {
            tok
            for tok in re.findall(r"[a-z0-9]+", (raw or "").casefold())
            if len(tok) >= 2 and tok not in alias_stop
        }

    for cat in load_taxonomy():
        for sub in cat.subcategories:
            phrases = (sub.name, *sub.keywords)
            group: set[str] = set()
            for phrase in phrases:
                group |= _tokens(phrase)
            if not group:
                continue
            anchors = set(_tokens(sub.name))
            for phrase in sub.keywords:
                normalized = re.sub(r"\s+", " ", phrase.casefold()).strip()
                if normalized and " " not in normalized and normalized not in alias_stop:
                    anchors.add(normalized)
            for anchor in anchors:
                mapping.setdefault(anchor, set()).update(group)

    return {key: frozenset(values) for key, values in mapping.items()}


def _is_known_service_label(text: str) -> bool:
    """True when residual text matches taxonomy / metadata service labels."""
    residual = _strip_topic_setting_wrapper(text)
    normalized = re.sub(r"\s+", " ", residual.casefold()).strip(" ?.!,;:\"'")
    if not normalized:
        return False
    normalized = re.sub(r"^(?:the|my|a|an|our)\s+", "", normalized).strip()
    if not normalized or len(normalized.split()) > 8:
        return False
    phrases, singles = _service_vocab_sets()
    if normalized in phrases or normalized in singles:
        return True
    # Compact acronyms / short titles that appear as whole-token taxonomy keywords.
    if " " not in normalized and normalized in singles:
        return True
    return False


def _canonical_service_retrieval_phrase(text: str) -> str | None:
    """Map a short/acronym topic label to its taxonomy subcategory retrieval phrase.

    Derived only from knowledge-base taxonomy metadata (subcategory names +
    keywords). Exact keyword/name matches win so labels like ``TOR`` resolve to
    Transcript of Records rather than unrelated ``Terms of Reference`` hits.
    """
    residual = _strip_topic_setting_wrapper(text)
    normalized = re.sub(r"\s+", " ", residual.casefold()).strip(" ?.!,;:\"'")
    normalized = re.sub(r"^(?:the|my|a|an|our)\s+", "", normalized).strip()
    if not normalized:
        return None

    exact_keyword: str | None = None
    exact_name: str | None = None
    for cat in load_taxonomy():
        for sub in cat.subcategories:
            name_cf = sub.name.casefold().strip()
            if normalized == name_cf and has_distinctive_token(name_cf, GENERIC_SERVICE_NAME_TOKENS):
                exact_name = sub.name
            for keyword in sub.keywords:
                kw_cf = keyword.casefold().strip()
                if normalized == kw_cf and has_distinctive_token(kw_cf, GENERIC_SERVICE_NAME_TOKENS):
                    # Keep both canonical service title and the matched label.
                    exact_keyword = f"{sub.name} ({keyword})"
                    break
            if exact_keyword:
                break
        if exact_keyword:
            break
    if exact_keyword:
        return exact_keyword
    if exact_name:
        return exact_name
    return None


def _canonical_service_name(phrase: str) -> str:
    """Strip a parenthetical alias, leaving the taxonomy service title."""
    return re.sub(r"\s*\([^)]*\)\s*", " ", phrase or "").strip()


def _active_service_for_response(
    active_topic: str | None,
    selected_context: list[RetrievedChunk] | None = None,
) -> str | None:
    """The machine-readable ``active_service`` value for the API response.

    Always a real, validated taxonomy service name, or ``None`` — never the
    raw ``active_topic`` fallback string, which is frequently a full
    sentence ("How do I enroll as a new student?") rather than a clean
    canonical name.

    A resolved ``active_topic`` that is *already* an exact, validated
    taxonomy name is unambiguous by construction — it can only get there via
    an explicit switch, a known short label, or an already-validated
    ``client_active_service`` (see ``resolve_active_topic``) — so it is
    trusted directly and is never second-guessed against retrieved
    evidence. A validated, server-confirmed service identity is the whole
    point of the client-carried round trip; letting a single imperfectly
    ranked top chunk override it on a vague slot follow-up (the exact case
    that mechanism exists for) would silently discard the higher-confidence
    signal.

    Otherwise grounded in the *actually selected evidence* — the top
    selected chunk's own title/canonical topic — rather than re-parsing the
    (often ambiguous) ``active_topic`` question text: a chunk's identity is
    unambiguous, while a full sentence can name more than one plausible
    taxonomy service (e.g. "new student" also matches "Freshmen", not only
    "Registration"), and picking the wrong one here would defeat the point
    of a client echoing it back later. Falls back to the resolved
    ``active_topic`` string only when no selected evidence is available
    (e.g. a template answer path with no chunk in scope). A client must
    only ever be handed back something this backend would also accept and
    trust on the next turn.
    """
    if active_topic:
        exact = validate_active_service_identity(_canonical_service_name(active_topic))
        if exact:
            return exact
    if selected_context:
        top = selected_context[0]
        metadata = top.metadata or {}
        title = str(
            metadata.get("canonical_topic")
            or metadata.get("source_section")
            or metadata.get("title")
            or top.title
            or ""
        ).strip()
        if title:
            names = _canonical_service_names_in_text(title)
            if names:
                return names[0]
    if not active_topic:
        return None
    names = _canonical_service_names_in_text(active_topic)
    return names[0] if names else None


def _canonical_service_names_in_text(text: str) -> list[str]:
    """Taxonomy service titles mentioned in *text* as whole tokens or phrases.

    Used so acronyms such as TOR expand to ``Transcript of Records`` for
    overlap/ranking without a one-off ``if question == "TOR"`` branch.
    """
    residual = _strip_topic_setting_wrapper(text)
    normalized = re.sub(r"\s+", " ", residual.casefold()).strip(" ?.!,;:\"'")
    if not normalized:
        return []

    names: list[str] = []
    exact = _canonical_service_retrieval_phrase(text)
    if exact:
        names.append(_canonical_service_name(exact))

    names.extend(
        taxonomy_service_names_in_text(
            normalized,
            exclude_tokens=_GENERIC_TOPIC_TOKENS | _SLOT_ATTRIBUTE_TOKENS | GENERIC_INTENT_TOKENS,
        )
    )
    return list(dict.fromkeys(name for name in names if name))



# Reuses the taxonomy module's shared generic-word set (see
# GENERIC_SERVICE_NAME_TOKENS) rather than keeping a second, independently
# maintained copy that could drift out of sync with the reranker's own use
# of the same exclusion.
_GENERIC_TOPIC_TOKENS = GENERIC_SERVICE_NAME_TOKENS


def _expand_topic_identity_tokens(topic_tokens: set[str]) -> set[str]:
    """Expand short/acronym topic tokens using taxonomy sibling aliases."""
    if not topic_tokens:
        return set()
    expanded = set(topic_tokens)
    _, singles = _service_vocab_sets()
    alias_map = _service_alias_token_map()
    for token in topic_tokens:
        # Only expand exact single-token taxonomy labels (tor, cor, clearance, …).
        if token in singles:
            expanded.update(
                alias
                for alias in alias_map.get(token, ())
                if alias not in _GENERIC_TOPIC_TOKENS
            )
    return expanded


def _prefer_active_topic_context(
    chunks: list[RetrievedChunk],
    active_topic: str,
) -> list[RetrievedChunk]:
    """Keep evidence that matches the active service when any such chunk exists.

    Slot follow-ups (requirements/cost/where/time) prefer charter/procedure
    cards with usable service fields over policy clauses that only share the
    service name.
    """
    # Pass raw topic tokens; matching expands aliases once internally.
    topic_tokens = _fee_topic_tokens(active_topic) | _content_tokens(active_topic)
    if not chunks or not topic_tokens:
        return chunks
    matching = [
        chunk
        for chunk in chunks
        if _service_matches_active_topic(_chunk_service_title(chunk), topic_tokens)
    ]
    if not matching:
        return chunks
    usable = [
        chunk
        for chunk in matching
        if _has_usable_service_fields(chunk) or is_service_procedure_chunk(chunk)
    ]
    if not usable:
        return matching
    usable.sort(
        key=lambda chunk: (
            0 if _has_usable_service_fields(chunk) else 1,
            0 if is_service_procedure_chunk(chunk) else 1,
        )
    )
    return usable


# Words that name the *attribute* a student is asking for rather than the thing
# it belongs to: "how much", "the requirements", "which office". On their own they
# identify no subject.
_SLOT_ATTRIBUTE_TOKENS = frozenset(
    {
        "much", "cost", "fee", "fees", "long", "submit", "requirement",
        "requirements", "document", "documents", "office", "handles",
        "responsible", "take", "need", "required", "where", "saan",
    }
)

_VAGUE_REQUEST_RE = re.compile(
    r"^(?:help|please\s+help(?:\s+me)?|can\s+you\s+help(?:\s+me)?|"
    r"i\s+need\s+help|what\s+can\s+you\s+do)\s*[?.!]*$",
    re.I,
)


def _is_vague_request(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    return bool(cleaned) and bool(_VAGUE_REQUEST_RE.match(cleaned))


def _is_underspecified_question(text: str) -> bool:
    """True for slot-only or vague requests that do not name a service/topic."""
    return _is_vague_request(text) or _is_slot_followup_question(text)


def _has_real_active_topic(active_topic: str | None) -> bool:
    topic = (active_topic or "").strip()
    return bool(topic) and not _is_underspecified_question(topic)


def _question_names_a_service_or_subject(text: str) -> bool:
    """True when the wording already identifies a service or distinctive subject."""
    if _canonical_service_names_in_text(text) or _is_known_service_label(text):
        return True
    residual = _strip_topic_setting_wrapper(text)
    if residual and residual != (text or "").strip() and (
        _canonical_service_names_in_text(residual) or _is_known_service_label(residual)
    ):
        return True
    return bool(_distinctive_subject_tokens(text))


def _is_slot_followup_question(text: str) -> bool:
    """True for anaphoric slot questions that need a prior substantive topic.

    "How much does it cost?" is a slot. "How much does a Good Moral Certificate
    cost?" already names a service and is not slot-only.
    """
    normalized = re.sub(r"\s+", " ", (text or "").strip().casefold())
    if not normalized:
        return False
    # "What about TOR?" / "How about Enrollment?" are topic switches, not slots.
    if re.match(r"^(?:what about|how about)\b", normalized):
        residual = _strip_topic_setting_wrapper(text)
        residual_tokens = _content_tokens(residual)
        if residual and (
            _is_known_service_label(residual)
            or (residual_tokens and not residual_tokens <= _SLOT_ATTRIBUTE_TOKENS)
        ):
            return False
        return True
    if _question_names_a_service_or_subject(text):
        return False
    if re.match(
        r"^(?:how much|how long|and the|the fee|the office|"
        r"which office|what office|who handles|who is responsible|same for|"
        r"for that|that one|and for|also|what if|and then|then what)\b",
        normalized,
    ):
        return True
    if re.match(
        r"^(?:what are the requirements?|where do i submit(?: them| it)?|"
        r"how long does it take|what does it cost|how much is it|"
        r"what(?:'s| is) the fee|where can i submit|"
        r"what documents? (?:do i need|are required)|"
        r"who (?:handles|processes) (?:it|that|this))\b",
        normalized,
    ):
        return True
    tokens = _content_tokens(normalized)
    if len(normalized.split()) <= 8 and tokens and tokens <= _SLOT_ATTRIBUTE_TOKENS:
        return True
    return False


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


def _history_user_turns(history: list[Any]) -> list[str]:
    turns: list[str] = []
    for item in history:
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
        else:
            role = str(getattr(item, "role", "") or "").strip().lower()
            content = str(getattr(item, "content", "") or "").strip()
        if role == "user" and content:
            turns.append(content)
    return turns


def _history_assistant_turns(history: list[Any]) -> list[str]:
    turns: list[str] = []
    for item in history:
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
        else:
            role = str(getattr(item, "role", "") or "").strip().lower()
            content = str(getattr(item, "content", "") or "").strip()
        if role == "assistant" and content:
            turns.append(content)
    return turns


def _last_substantive_user_topic(history: list[Any], fallback_user: str) -> str:
    """Prefer the latest contentful user question, skipping slot follow-ups."""
    return resolve_active_topic(history, fallback_user=fallback_user)


def _content_tokens(text: str) -> set[str]:
    stop = {
        "what", "which", "who", "how", "when", "where", "why", "the", "a", "an",
        "is", "are", "was", "were", "do", "does", "did", "can", "could", "would",
        "should", "for", "of", "to", "in", "on", "at", "by", "with", "from",
        "about", "that", "this", "it", "those", "them", "there", "same", "also",
        "and", "or", "my", "me", "i", "you", "your", "please", "tell", "need",
        "want", "office", "handles", "responsible", "process", "service",
        "now", "regarding",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").casefold())
        if token not in stop and len(token) >= 3
    }


def _chunks_overlap_question_tokens(
    question: str,
    chunks: list[RetrievedChunk],
) -> bool:
    """True when a content token from the question appears in retrieved text/title.

    Used as a scale-free alignment signal so a named subject (president, diploma,
    enrollment) is not treated as unaligned just because unit fixtures omit
    rerank reasons.
    """
    tokens = _content_tokens(question) - _SLOT_ATTRIBUTE_TOKENS - _GENERIC_TOPIC_TOKENS
    if not tokens or not chunks:
        return False
    for chunk in chunks:
        metadata = chunk.metadata or {}
        blob = _normalize(
            " ".join(
                str(value or "")
                for value in (
                    metadata.get("source_section"),
                    metadata.get("canonical_topic"),
                    metadata.get("title"),
                    chunk.title,
                    (chunk.text or "")[:800],
                )
            )
        )
        if any(token in blob for token in tokens):
            return True
    return False


def _topic_anchor_from_history(
    history: list[Any],
    last_user: str,
    last_assistant: str,
) -> str:
    """Active topic only — do not mix older assistant service titles into context."""
    del last_assistant  # retained for call-site compatibility
    return resolve_active_topic(history, fallback_user=last_user)


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
        r"(?i)(?:related to|regarding|about)\s+(?:the\s+)?(.+?)(?:\.|,|$)",
        r"(?i)#\s*(.+?)$",
        r"(?i)\*\*(.+?)\*\*",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.M)
        if match:
            phrase = re.sub(r"\s+", " ", match.group(1)).strip(" .:;-#*")
            if 3 <= len(phrase) <= 120 and not _is_slot_followup_question(phrase):
                phrases.append(phrase)
    # Service-style titles (e.g. "Good Moral Certificate", "Transcript of Records").
    for match in re.finditer(
        r"\b([A-Z][A-Za-z0-9/'/-]*(?:\s+[A-Z][A-Za-z0-9/'/-]*){1,6})\b",
        text,
    ):
        phrase = re.sub(r"\s+", " ", match.group(1)).strip()
        if 8 <= len(phrase) <= 90 and not phrase.lower().startswith(
            ("based on", "according to", "the office", "office of")
        ):
            phrases.append(phrase)
    # First short line often carries the service/section title from templates.
    first_line = re.sub(r"\s+", " ", text.splitlines()[0]).strip().lstrip("# ").strip()
    if 8 <= len(first_line) <= 90 and not first_line.lower().startswith(
        ("sure", "here", "the retrieved", "this may", "overview", "based on", "i've", "i have")
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
        keep = rank == 1 or (
            len(selected) < limit and any(reason.startswith("keep_") for reason in reasons)
        )
        if broad_query:
            if duplicate_group and rank != 1:
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
        content = _format_structured_tables(_redact_extraction_artifacts(chunk.text.strip()))
        blocks.append(
            "\n".join(
                [
                    f"Title: {title}",
                    f"Path: {path}",
                    f"Page: {page}",
                    *meta_lines,
                    "",
                    "Content:",
                    content,
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
                    # Same per-chunk structured-table normalization
                    # ``format_retrieved_context`` already applies — a
                    # collection-style question (requirements/policy/
                    # scholarship/service/office listings) can retrieve a
                    # chunk containing a status table exactly as easily as a
                    # normal-QA one, and without this the post-generation
                    # audit's table parser would find zero rows in the same
                    # text a direct parse of the chunk succeeds on, since it
                    # only ever reads rows out of the "Structured table"
                    # marker this formatting step inserts.
                    _format_structured_tables(_redact_extraction_artifacts(chunk.text.strip())),
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
    facet_coverage: FacetCoverage | None = None,
    active_topic: str | None = None,
) -> str:
    if not retrieved_chunks or not selected_chunks:
        return "low"
    normalized_answer = answer.lower()
    if any(phrase in normalized_answer for phrase in MISSING_INFO_PHRASES):
        return "low"

    domain = _detected_query_domain(_normalize(question))
    taxonomy_available = bool(domain) and _chunks_carry_taxonomy(selected_chunks)
    if taxonomy_available:
        has_domain_match = any(_chunk_matches_domain(chunk, domain) for chunk in selected_chunks)
        domain_match_count = sum(1 for chunk in selected_chunks if _chunk_matches_domain(chunk, domain))
    elif domain:
        # Query has a taxonomy label but selected chunks lack ingest metadata
        # (common in unit fixtures). Soft-match the label against title/path/text
        # instead of inventing another keyword table or auto-passing every case.
        has_domain_match = any(_soft_domain_text_match(chunk, domain) for chunk in selected_chunks)
        domain_match_count = sum(
            1 for chunk in selected_chunks if _soft_domain_text_match(chunk, domain)
        )
    else:
        has_domain_match = False
        domain_match_count = 0
    has_positive_signal = any(_positive_reasons(chunk) for chunk in selected_chunks)
    # Topic-coverage context is deliberate, so its ranking penalty is not noise.
    ranked_selection = [chunk for chunk in selected_chunks if not _is_facet_recovered(chunk)]
    noisy_selected = any(_has_strong_penalty(chunk) for chunk in (ranked_selection or selected_chunks)[1:])

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

    # Confidence used to hinge on ``top_score >= 0.82`` / ``>= 0.58``. Those
    # thresholds were written for cosine similarity but are applied to the
    # post-rerank ranking score, whose production range is ~1.0 to ~4.7 — so
    # every answer cleared both and confidence collapsed onto the remaining
    # conditions. It is now graded on whether the evidence is aligned with a
    # question we can actually pin down, which holds on any score scale.
    if not _question_identifies_a_subject(
        question, retrieved_chunks, selected_chunks, active_topic=active_topic
    ):
        return "low"
    title_anchored = query_matches_retrieval_title(
        question, selected_chunks
    ) or query_matches_retrieval_title(question, retrieved_chunks)
    text_anchored = _chunks_overlap_question_tokens(
        question, selected_chunks
    ) or _chunks_overlap_question_tokens(question, retrieved_chunks)
    distinctive = _distinctive_subject_tokens(question)
    distinctive_in_evidence = _chunks_contain_tokens(
        distinctive, selected_chunks
    ) or _chunks_contain_tokens(distinctive, retrieved_chunks)
    domain_grounded = bool(
        domain
        and has_domain_match
        and distinctive
        and _domain_shares_distinctive_tokens(domain, distinctive)
    )
    # HIGH requires the question's own distinctive tokens to appear in evidence
    # or in the taxonomy domain label. A weak classify("… policy") hit must not
    # upgrade unrelated handbook chunks to high confidence.
    strong_aligned = bool(
        (title_anchored and (not distinctive or distinctive_in_evidence))
        or domain_grounded
    )
    # A single narrow chunk's title/text can share literal wording with a
    # *compound* question (title_anchored) while only ever answering one of
    # several distinct parts — this is exactly what taxonomy domain-matching
    # used to guard against (chunk category/subcategory vs. the question's
    # classified category), before that check was replaced by title/text
    # anchoring. Requiring the classified domain to also match — whenever the
    # question actually classifies into one — keeps that guard for HIGH
    # without reintroducing an absolute score threshold: a question with no
    # detected domain at all is unaffected (``domain`` is falsy).
    domain_consistent = (not domain) or has_domain_match
    if (
        strong_aligned
        and has_positive_signal
        and not noisy_selected
        and domain_consistent
        and _authoritative_evidence_present(question, selected_chunks)
    ):
        return _capped_for_facet_gap("high", facet_coverage)
    if (strong_aligned or text_anchored or has_positive_signal) and not noisy_selected:
        return _capped_for_facet_gap("medium", facet_coverage)
    return "low"


# Mirrors the exclude_tokens already used by ``_canonical_service_names_in_text``
# so the "is a service named at all" gate and the "does this chunk's title
# match that service" check below cannot disagree about what counts as generic.
_SERVICE_EVIDENCE_EXCLUDE_TOKENS = (
    GENERIC_SERVICE_NAME_TOKENS | _SLOT_ATTRIBUTE_TOKENS | GENERIC_INTENT_TOKENS
)


def _authoritative_evidence_present(question: str, chunks: list[RetrievedChunk]) -> bool:
    """For a factual/how-to service question, is the *named service's own
    record* in evidence — not merely a chunk that mentions the same topic?

    Topical overlap (a handbook policy clause that happens to share a
    service's name) is not the same as having that service's actual
    Citizen's Charter/service-procedure card. Confidence must not go "high"
    on the former when the question asks a service-specific fact (fee,
    office, requirements, processing time) and only the latter can ground it.
    Questions that do not name a specific taxonomy service, or are not
    fact-seeking about one, are unaffected — this only tightens the case
    Cursor's diagnosis flagged.

    Reuses :func:`taxonomy_service_title_match` (the same identity rule
    ``_service_identity_boost`` uses in the reranker) instead of an
    independent name/title token-overlap check, so a service reached only
    through a keyword alias — "enrollment" under the "Registration"
    subcategory, "dropping" under "Withdrawal" — is not silently rejected
    just because its bare canonical name shares no word with the real card
    title, and a card that merely shares one common institutional word with
    the canonical name (e.g. a hypothetical "IP Registration Process" for an
    enrollment question) is not wrongly accepted either.
    """
    if not (is_factual_service_detail_query(question) or is_service_howto_query(question)):
        return True
    names = _canonical_service_names_in_text(question)
    if not names:
        return True
    normalized_question = _normalize(question)
    for chunk in chunks:
        if not is_service_procedure_chunk(chunk):
            continue
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
        if taxonomy_service_title_match(
            normalized_question, title, exclude_tokens=_SERVICE_EVIDENCE_EXCLUDE_TOKENS
        ):
            return True
    return False


def _is_facet_recovered(chunk: RetrievedChunk) -> bool:
    return FACET_RECOVERY_REASON in (chunk.rerank_reasons or [])


_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def _capped_for_facet_gap(confidence: str, coverage: FacetCoverage | None) -> str:
    """Hold confidence down when the evidence is incomplete or off-topic."""
    if coverage is None:
        return confidence

    ceiling = "high"
    if coverage.has_gap:
        # An unanswered topic means the answer is partial by construction.
        ceiling = "low" if len(coverage.uncovered) >= 2 else "medium"
    if coverage.off_topic_lead:
        # The answer is built on a section about something else entirely.
        ceiling = _lower_of(ceiling, "low")
    if coverage.conflict_question:
        # Naming a winning source the documents never rank is inference.
        ceiling = _lower_of(ceiling, "medium")
    if coverage.precedence_question and coverage.is_multi_facet:
        ceiling = _lower_of(ceiling, "medium")
    return _lower_of(confidence, ceiling)


def _lower_of(first: str, second: str) -> str:
    return first if _CONFIDENCE_ORDER[first] <= _CONFIDENCE_ORDER[second] else second


def _restore_missing_facet_context(
    question: str,
    facets: list[QuestionFacet],
    selected: list[RetrievedChunk],
    retrieved: list[RetrievedChunk],
    evidence: FacetEvidence,
) -> list[RetrievedChunk]:
    """Add back the best section for any part of the question the context dropped."""
    coverage = analyze_facet_coverage(
        question,
        facets,
        selected,
        evidence,
        key_of=_chunk_merge_key,
    )
    if not coverage.has_gap:
        return selected

    selected_keys = {_chunk_merge_key(chunk) for chunk in selected}
    wanted = facet_recovery_keys(coverage, evidence, exclude=selected_keys)
    if not wanted:
        return selected

    by_key = {_chunk_merge_key(chunk): chunk for chunk in retrieved}
    # Tag them: these are kept to cover a part of the question, so their ranking
    # penalties must not later be read as noisy context.
    tagged = [
        replace(
            by_key[key],
            rerank_reasons=[*(by_key[key].rerank_reasons or []), FACET_RECOVERY_REASON],
        )
        for key in wanted
        if key in by_key
    ]
    return selected + tagged


def _chunk_heading(chunk: RetrievedChunk) -> str:
    """The heading a chunk was extracted under, for naming it in generator notes."""
    metadata = chunk.metadata or {}
    for key in ("source_section", "canonical_topic", "procedure_title", "section", "title"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(chunk.title or "").strip()


def _chunk_article_label(chunk: RetrievedChunk) -> str:
    """Document article breadcrumb from ingest metadata, if present."""
    metadata = chunk.metadata or {}
    article = metadata.get("article")
    if isinstance(article, str) and article.strip():
        return article.strip()
    return ""


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
    user_role: str | None = None,
) -> tuple[list[RetrievedChunk], dict[str, list[str]]]:
    """Retrieve for every query, keeping what each one found on its own.

    The per-query result lists are how a bundled question later proves that a
    given section belongs to a given part of it.
    """
    merged: dict[str, RetrievedChunk] = {}
    by_query: dict[str, list[str]] = {}
    for query in queries:
        results = store.search(query, top_k=top_k, raw_k=raw_k, user_role=user_role)
        keys: list[str] = []
        for chunk in results:
            key = _chunk_merge_key(chunk)
            keys.append(key)
            existing = merged.get(key)
            if existing is None or _chunk_score(chunk) > _chunk_score(existing):
                merged[key] = chunk
        by_query[query] = keys
    return sorted(merged.values(), key=_chunk_score, reverse=True), by_query


def _chunk_merge_key(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    identifier = str(
        getattr(chunk, "chunk_id", None) or metadata.get("chunk_id") or ""
    ).strip()
    if identifier:
        return f"id:{identifier}"
    document_id = str(chunk.document_id or metadata.get("document_id") or "").strip()
    page = str(metadata.get("page") or metadata.get("page_label") or "").strip()
    title = _normalize_ascii(_normalize(str(chunk.title or metadata.get("title") or "")))
    preview = _normalize_ascii(_normalize(str(chunk.text or "")))[:160]
    return f"doc:{document_id}|p:{page}|t:{title}|x:{preview}"


def _raw_citation_id(chunk: RetrievedChunk, index: int) -> str:
    """Canonical ``citation_id`` for a chunk, without any DB/PDF resolution.

    Mirrors ``_sources_from_chunks``'s ``_citation_fields`` identity formula
    (``metadata.get("chunk_id")`` when present, else
    ``f"{document_id}::{chunk_index}"``), but always uses the chunk's own raw
    ``document_id`` -- never the Postgres-resolved id ``_citation_fields`` may
    substitute for a re-indexed document -- so this stays cheap and
    side-effect-free for debug/capture instrumentation (no DB/PDF lookups).
    It therefore matches the displayed citation_id in the common case (no
    Postgres remap), but callers must treat it as the retrieval-time
    identity, not a guaranteed stand-in for the resolved display identity.
    """
    metadata = chunk.metadata or {}
    chunk_id = metadata.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    document_id = chunk.document_id or metadata.get("document_id") or "doc"
    chunk_index = chunk.chunk_index or index
    return f"{document_id}::{chunk_index}"


def _retrieval_quality(
    question: str,
    retrieved: list[RetrievedChunk],
    selected: list[RetrievedChunk],
    *,
    broad_query: bool,
    collection_mode: bool,
    active_topic: str | None = None,
) -> dict[str, Any]:
    if not retrieved or not selected:
        return {"should_clarify": True, "reason": "no_retrieval_context"}
    if broad_query or collection_mode:
        return {"should_clarify": False, "reason": "broad_or_collection_mode"}

    normalized_q = _normalize(question)
    domain = _detected_query_domain(normalized_q)
    if domain and _chunks_carry_taxonomy(selected):
        domain_match_count = sum(1 for chunk in selected if _chunk_matches_domain(chunk, domain))
    elif domain:
        domain_match_count = sum(1 for chunk in selected if _soft_domain_text_match(chunk, domain))
    else:
        # No taxonomy label for the question: do not treat every retrieved
        # section as domain-aligned. Underspecified/nonsense queries must not
        # inherit confidence from arbitrary charter cards.
        domain_match_count = 0
    positive_count = sum(1 for chunk in selected if _positive_reasons(chunk))
    noisy_count = sum(1 for chunk in selected if _has_strong_penalty(chunk))

    noisy_context = noisy_count >= max(1, len(selected) // 2)
    # Title/section alignment (short topics or fuller questions that name the topic)
    # is sufficient grounding — do not force clarification just because the phrase
    # is short or lacks generic boost_* reasons.
    title_anchored = query_matches_retrieval_title(
        question, selected
    ) or query_matches_retrieval_title(question, retrieved)
    text_anchored = _chunks_overlap_question_tokens(question, selected)
    # The three gates that used to live here — top < 0.54, a margin gate below
    # 0.62, and an alignment gate below 0.68 — were written for the 0-1 cosine
    # scale that ``relevance_score`` carries before reranking. After reranking it
    # carries the unbounded rerank priority instead (production: ~1.0 to ~4.7),
    # so all three were unreachable. Their intent was an absolute "is this good
    # evidence?" floor, which neither score can express: cosine puts relevant and
    # unrelated chunks alike in ~0.79-0.91, and the rerank scale shifts with the
    # topic. The intent is carried instead by two scale-free questions — do we
    # know what is being asked about, and did retrieval find topical support?
    if not _question_identifies_a_subject(
        question, retrieved, selected, active_topic=active_topic
    ):
        return {"should_clarify": True, "reason": "question_identifies_no_subject"}
    weak_alignment = (
        domain_match_count == 0
        and not title_anchored
        and not text_anchored
        and _reranker_found_no_topical_support(selected)
    )

    if noisy_context or weak_alignment:
        return {"should_clarify": True, "reason": "weak_or_inconsistent_retrieval_evidence"}
    return {"should_clarify": False, "reason": "retrieval_evidence_sufficient"}


def _reranker_found_no_topical_support(chunks: list[RetrievedChunk]) -> bool:
    """True when no selected chunk has a subject-level rerank reason.

    Hygiene boosts (page number, citation-ready, valid source metadata) fire on
    every well-formed chunk and do not count.
    """
    return not any(_positive_reasons(chunk) for chunk in chunks)


def _question_identifies_a_subject(
    question: str,
    retrieved: list[RetrievedChunk],
    selected: list[RetrievedChunk],
    *,
    active_topic: str | None = None,
) -> bool:
    """Do we know *what* the student is asking about?

    Deliberately reads no similarity or rerank score: neither carries an
    absolute notion of relevance (see :class:`RetrievedChunk`), so "we have no
    idea what this question is about" has to be answered from the question, the
    conversation and the taxonomy instead.

    A question identifies a subject when the conversation has an active topic,
    when it anchors onto a retrieved section title, or when its own wording
    contributes subject tokens — words left over once the attribute being asked
    for ("how much", "the requirements", "which office") is removed. "How much
    is the fee for a Transcript of Records?" keeps ``transcript``/``records``;
    "How much does it cost?" keeps nothing, and neither does a bare "help".
    """
    if _has_real_active_topic(active_topic):
        return True
    normalized = _normalize(question)
    if not normalized or _is_underspecified_question(question):
        return False
    distinctive = _distinctive_subject_tokens(normalized)
    names = _canonical_service_names_in_text(question)
    if names:
        return True
    if _is_known_service_label(question):
        return True
    in_evidence = _chunks_contain_tokens(distinctive, selected) or _chunks_contain_tokens(
        distinctive, retrieved
    )
    domain = _detected_query_domain(normalized)
    domain_grounded = bool(
        domain and distinctive and _domain_shares_distinctive_tokens(domain, distinctive)
    )
    # Leftover words that never appear in retrieved titles/text are not a campus subject.
    if distinctive and not in_evidence and not domain_grounded:
        return False
    title_anchored = query_matches_retrieval_title(
        question, selected
    ) or query_matches_retrieval_title(question, retrieved)
    if title_anchored and (not distinctive or in_evidence):
        return True
    if domain_grounded:
        return True
    return False


def _distinctive_subject_tokens(text: str) -> set[str]:
    return {
        token
        for token in (
            _content_tokens(text) - _SLOT_ATTRIBUTE_TOKENS - _GENERIC_TOPIC_TOKENS
        )
        if token not in GENERIC_INTENT_TOKENS
    }


def _chunks_contain_tokens(tokens: set[str], chunks: list[RetrievedChunk]) -> bool:
    if not tokens or not chunks:
        return False
    for chunk in chunks:
        blob = _normalize(
            " ".join(
                str(value or "")
                for value in (
                    (chunk.metadata or {}).get("source_section"),
                    (chunk.metadata or {}).get("canonical_topic"),
                    (chunk.metadata or {}).get("title"),
                    chunk.title,
                    (chunk.text or "")[:400],
                )
            )
        )
        if any(token in blob for token in tokens):
            return True
    return False


def _domain_shares_distinctive_tokens(domain: str, distinctive: set[str]) -> bool:
    domain_tokens = set(re.findall(r"[a-z0-9]+", _normalize(domain)))
    if distinctive & domain_tokens:
        return True
    for token in distinctive:
        for domain_token in domain_tokens:
            if len(token) >= 4 and len(domain_token) >= 4 and (
                token.startswith(domain_token) or domain_token.startswith(token)
            ):
                return True
    return False


def _student_facing_answer(
    answer: str,
    confidence: str,
    *,
    user_role: str | None = None,
) -> str:
    from app.services.qa.groq_answer_service import _strip_pointer_phrasing

    cleaned = _redact_extraction_artifacts(
        _strip_pointer_phrasing(_strip_source_lines(answer))
    )
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
    # Do NOT override a grounded "sources do not specify the fee" answer with an
    # unrelated fee-bearing chunk — recovery must find a topic-matched fee first.
    return False


def _prefer_structured_fee_recovery(question: str, recovered: str, llm_answer: str) -> bool:
    """Prefer metadata fee recovery when the LLM names the wrong service or omits amounts."""
    normalized_q = _normalize(question)
    if not re.search(r"\b(?:how much|fee|fees|cost)\b", normalized_q):
        return False
    recovered_n = _normalize(recovered)
    if "listed fee" not in recovered_n:
        return False
    # Recovered title must overlap the asked topic when the question carries one.
    recovered_title_match = re.search(
        r"listed fee for (.+?) is ",
        recovered_n,
    )
    recovered_title = recovered_title_match.group(1) if recovered_title_match else ""
    topic_tokens = _fee_topic_tokens(normalized_q)
    if topic_tokens and _title_topic_overlap(recovered_title, topic_tokens) == 0:
        return False
    llm_n = _normalize(llm_answer or "")
    if not llm_n.strip():
        return True
    # If the model already says the sources lack a fee, keep that unless recovery
    # is clearly about the same topic *and* provides a concrete amount.
    if re.search(
        r"\b(?:fees?:\s*none|fee:\s*none|not specified|do not specify|does not specify|"
        r"do not contain|does not contain|no fee|not provide the fee)\b",
        llm_n,
    ):
        if not re.search(r"(?i)\bp\s*\d|\d+\.\d{2}", recovered):
            return False
        if topic_tokens and _title_topic_overlap(recovered_title, topic_tokens) == 0:
            return False
        # Topic-matched concrete fee may still replace a vague "not specified".
        return _title_topic_overlap(recovered_title, topic_tokens) > 0 if topic_tokens else False
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


def _fee_topic_tokens(normalized_question: str) -> set[str]:
    """Content tokens that identify the service being asked about (not fee slots)."""
    stop = {
        "much", "cost", "fee", "fees", "long", "submit", "requirement", "requirements",
        "document", "documents", "regarding", "prior", "question", "context", "listed",
        "processing", "time", "take", "need", "required", "office", "handles",
        "responsible", "avail", "service", "services",
    }
    return {token for token in _content_tokens(normalized_question) if token not in stop}


def _title_topic_overlap(title: str, topic_tokens: set[str]) -> int:
    title_n = _normalize(title)
    if not title_n or not topic_tokens:
        return 0
    title_words = set(re.findall(r"[a-z0-9]+", title_n))
    return sum(1 for token in topic_tokens if _token_matches_any(token, title_words))


def _token_matches_any(token: str, words: set[str]) -> bool:
    if token in words:
        return True
    return any(_inflection_compatible(token, word) for word in words)


def _inflection_compatible(left: str, right: str) -> bool:
    """Match enroll↔enrollment / drop↔dropping without nested-noun false friends.

    Rejects certificate↔certifications (suffix ``ions`` is not a simple
    inflection of the shorter form).
    """
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < 4:
        return False
    inflections = {
        "ment", "ments", "ing", "ings", "ed", "er", "ers", "ion", "tions", "ation",
        "ations", "es", "s",
    }
    if longer.startswith(shorter) and longer[len(shorter) :] in inflections:
        return True
    # Consonant doubling: drop -> dropping / dropped
    if longer.startswith(shorter + shorter[-1]) and longer[len(shorter) + 1 :] in {
        "ing",
        "ed",
        "er",
    }:
        return True
    return False


def _service_matches_active_topic(service_title: str, topic_tokens: set[str]) -> bool:
    """True when a charter/service title is identity-compatible with the active topic.

    Fee/time/requirements recovery must use this gate — loose fee-blob token
    overlap is not enough (that let Enrollment fees answer Good Moral costs).
    Short acronyms (e.g. TOR) expand via taxonomy aliases before matching.
    """
    if not topic_tokens:
        return False
    expanded = _expand_topic_identity_tokens(topic_tokens)
    discriminative = {token for token in expanded if token not in _GENERIC_TOPIC_TOKENS}
    if discriminative and _title_topic_overlap(service_title, discriminative) > 0:
        return True
    core = {token for token in topic_tokens if token not in _GENERIC_TOPIC_TOKENS}
    return bool(core) and _title_topic_overlap(service_title, core) > 0


def _chunk_service_title(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    return (
        _meta_text(metadata, "source_section")
        or _meta_text(metadata, "canonical_topic")
        or _meta_text(metadata, "procedure_title")
        or _meta_text(metadata, "title")
        or _display_title(chunk)
        or ""
    )


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
        re.search(
            r"\b(?:which office|what office|who handles|responsible|in charge|"
            r"where|saan|kukuha|makakakuha|submit)\b",
            normalized,
        )
    )
    topic_tokens = _fee_topic_tokens(normalized)
    # Fee answers require an active service identity. Bare "how much does it cost?"
    # must not invent a random charter fee card.
    if asks_fee and not topic_tokens:
        return None
    ranked = sorted(
        chunks,
        key=lambda chunk: _charter_recovery_rank(
            chunk,
            normalized,
            prefer_fees=asks_fee,
            topic_tokens=topic_tokens,
        ),
    )
    for chunk in ranked:
        metadata = chunk.metadata or {}
        title = _chunk_service_title(chunk) or "this service"
        source_label = _source_label(
            sources,
            fallback=_meta_text(metadata, "source_label")
            or _meta_text(metadata, "source_document")
            or chunk.source_filename,
        )

        if re.search(r"\b(?:who may|who can avail|who can)\b", normalized):
            if topic_tokens and not _service_matches_active_topic(title, topic_tokens):
                continue
            who = _meta_text(metadata, "who_may_avail") or _extract_labeled_line(
                chunk.text or "",
                ("Who May Avail", "Who May Avail of the Service", "Clientele"),
            )
            if who:
                return (
                    f"{who} may avail of {title}, according to the {source_label}."
                )

        if re.search(r"\b(?:how long|processing time)\b", normalized):
            if topic_tokens and not _service_matches_active_topic(title, topic_tokens):
                continue
            time_value = _meta_text(metadata, "total_processing_time") or _extract_labeled_line(
                chunk.text or "",
                ("Total Processing Time",),
            )
            if time_value:
                return f"The total processing time for {title} is {time_value} ({source_label})."

        fee = None
        office = None
        if asks_fee:
            # Hard identity gate: fee cards from other services are never usable,
            # even when their fee text happens to share a token with the topic.
            if not _service_matches_active_topic(title, topic_tokens):
                # Diploma amounts may live on a TOR/certifications card when the
                # question explicitly asks about diploma fees.
                if not (
                    "diploma" in normalized
                    and "diploma" in _normalize(
                        str(metadata.get("total_fees") or metadata.get("fees") or "")
                        + " "
                        + (chunk.text or "")[:500]
                    )
                ):
                    continue
            raw_fee = (
                _meta_text(metadata, "total_fees")
                or _meta_text(metadata, "fees")
                or _extract_labeled_line(chunk.text or "", ("Fees", "Fee", "Total Fees"))
                or _extract_tor_fees_from_text(chunk.text or "", normalized)
            )
            fee = _fee_usable_for_question(raw_fee, title, normalized)
        if asks_office:
            if topic_tokens and not _service_matches_active_topic(title, topic_tokens):
                continue
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

        if asks_fee:
            reply = _fee_unclear_or_zero_answer(title, raw_fee, fee, normalized, source_label)
            if reply:
                return reply

        if asks_office and office and not asks_fee:
            return f"The office responsible for {title} is {office} ({source_label})."

        if re.search(
            r"\b(?:what documents|what additional|what must|documents? (?:are )?required|"
            r"requirements? (?:for|from|needed)|what (?:are|is) the (?:requirement|requirements|document|documents))\b",
            normalized,
        ):
            if topic_tokens and not _service_matches_active_topic(title, topic_tokens):
                continue
            answer = format_requirements_detail_answer(question, chunk, sources)
            if answer:
                return answer
    return None


def _charter_recovery_rank(
    chunk: RetrievedChunk,
    normalized_question: str,
    *,
    prefer_fees: bool = False,
    topic_tokens: set[str] | None = None,
) -> tuple[int, int, int, float]:
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
    tokens = topic_tokens if topic_tokens is not None else _fee_topic_tokens(normalized_question)
    # Higher overlap sorts first (negate for ascending key).
    overlap_rank = -_title_topic_overlap(title, tokens) if tokens else 0

    if "enroll" in normalized_question:
        if (
            "ip registration" in title
            or "assessment of fee" in title
            or "visitation" in title
            or "article 3" in title
        ):
            return (3, overlap_rank, fee_priority, score)
        if "enrollment" in title or "enrolment" in title:
            return (0, overlap_rank, fee_priority, score)
        if "registration" in title and "enrollment" not in title:
            return (3, overlap_rank, fee_priority, score)
        return (1, overlap_rank, fee_priority, score)

    if re.search(r"\b(?:tor|transcript)\b", normalized_question):
        if re.search(r"\b(?:transcript of records|issuance of transcript|\btor\b)\b", title):
            return (0, overlap_rank, fee_priority, score)
        if "annual report" in title or "certificate of completion" in title or "article 3" in title:
            return (3, overlap_rank, fee_priority, score)
        return (2, overlap_rank, fee_priority, score)

    if "diploma" in normalized_question:
        fee_blob = _normalize(
            str(metadata.get("total_fees") or metadata.get("fees") or "")
            + " "
            + (chunk.text or "")[:500]
        )
        if "diploma" in title or "diploma" in fee_blob:
            return (0, overlap_rank, 0 if prefer_fees else fee_priority, score)
        if (
            "assessment of fee" in title
            or "examination" in title
            or "open to all clients" in title
            or "faculty clearance" in title
            or "crediting of subject" in title
            or "program accreditation" in title
            or "certified true copy" in title
        ):
            return (3, overlap_rank, fee_priority, score)
        return (2, overlap_rank, fee_priority, score)

    # Default: topic overlap first, then fee metadata, then retrieval score.
    # Incompatible services sort last so identity-gated recovery never prefers them.
    if tokens and _title_topic_overlap(title, tokens) == 0:
        return (4, overlap_rank, fee_priority, score)
    return (1, overlap_rank, fee_priority, score)


_UNSPECIFIED_FEE_VALUES = frozenset(
    {
        "none",
        "n/a",
        "na",
        "null",
        "-",
        "--",
        "nil",
        "[needs review]",
        "needs review",
        "not specified",
        "not applicable",
    }
)
_DOCUMENTED_ZERO_FEE_VALUES = frozenset(
    {"none", "no fee", "no fees", "free", "walang bayad", "0", "0.00", "p0", "p0.00"}
)


def _documented_zero_fee(fee: str | None) -> bool:
    """True when the source explicitly records that no fee is charged."""
    return _normalize(fee or "") in _DOCUMENTED_ZERO_FEE_VALUES


def _fee_unclear_or_zero_answer(
    title: str,
    raw_fee: str | None,
    fee: str | None,
    normalized_question: str,
    source_label: str,
) -> str | None:
    """Reply for an asks-fee question whose source has no *usable* fee value.

    Distinguishes "the source explicitly says there is no fee" from "the
    source's fee field could not be parsed" so neither is misreported as the
    other. Shared by the LLM-answer factual-recovery path and the
    conversational (no-LLM) fallback path so the two do not drift apart.
    """
    answer_title = _fee_answer_title(title, raw_fee or "", normalized_question)
    if _documented_zero_fee(raw_fee):
        return f"There is no listed fee for {answer_title} ({source_label})."
    if raw_fee and not fee:
        return f"The cited source does not clearly specify a fee for {answer_title}."
    return None


def _looks_like_fee_amount(fee: str | None) -> bool:
    """True for a currency-like amount, not an extraction fragment such as ``form. 3``."""
    text = (fee or "").strip()
    if not text or _normalize(text) in _UNSPECIFIED_FEE_VALUES:
        return False
    if _documented_zero_fee(text):
        return False
    if re.search(r"(?i)\bform\.?\s*\d+", text):
        return False
    if re.search(r"(?i)\b(?:php|peso|pesos)\b.*\d", text):
        return True
    # Isolated P### page markers (P137) are not currency. Require a decimal,
    # /page, or per-unit so page codes cannot be quoted as fees.
    if re.search(
        r"(?i)(?:^|[^\w])(?:php|p)\s*\d+(?:\.\d{2}|\s*/\s*page|\s*per\b|,)",
        text,
    ):
        return True
    if re.search(r"\d+\.\d{2}", text):
        return True
    return False


def _redact_extraction_artifacts(text: str) -> str:
    """Keep uncertain parser leftovers from being quoted as student-facing facts."""
    cleaned = re.sub(r"\[NEEDS REVIEW\]", "not specified in the source", text or "", flags=re.I)
    cleaned = re.sub(
        r"(?im)^(Fees|Fee|Total Fees)\s*:\s*(?:form\.?\s*\d+|[-–—]\s*\d+)\s*$",
        r"\1: not clearly specified in the source",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\bform\.?\s*\d+\b",
        "a value that is not clearly specified in the source",
        cleaned,
    )
    # Page-like P### tokens without a currency unit or /page qualifier.
    cleaned = re.sub(
        r"(?i)(?<![A-Za-z0-9])P\s*(\d{3,})(?!\.\d|/\s*page|\s*per\b)",
        "a source page marker that is not a listed fee",
        cleaned,
    )
    return cleaned


_RANGE_THEN_STATUS = re.compile(
    r"^(?P<range>\d+(?:\.\d+)?\s*(?:[-–]\s*\d+(?:\.\d+)?|and\s+(?:below|above)))\s+"
    r"(?P<status>[A-Za-z][A-Za-z /-]*)$",
    re.I,
)
_IDENTIFIER_CELL = re.compile(r"^(?:\d+\.\d{2}|[A-Z]{2,6})$")
_RANGE_CELL = re.compile(
    r"\d+\s*[-–]\s*\d+|\d+\s+and\s+(?:below|above)|\bpercent\b|\b%\b",
    re.I,
)
_NEGATIVE_STATUS = re.compile(
    r"\b(?:fail(?:ed|ure)?|conditional|incomplete|dropped|unsatisfactory)\b",
    re.I,
)
_PASSING_CLAIM = re.compile(r"\b(?:pass(?:es|ing|ed)?|successful)\b", re.I)
_FAILING_CLAIM = re.compile(r"\bfail(?:s|ing|ed)?\b", re.I)
_AND_ABOVE_CLAIM = re.compile(
    r"(\d+(?:\.\d+)?|[A-Za-z]{2,6})\s+and\s+above",
    re.I,
)
# A range phrased as a single open-ended boundary ("69 and below", "80 or
# above") states only its own edge number literally. A generated answer may
# instead name the *adjacent* number on the other side of that boundary
# ("70 and higher", "above 69") without ever repeating the row's own number,
# so that boundary and its direction are captured separately to derive the
# adjacent complement value on demand.
_RANGE_AT_OR_BELOW = re.compile(r"(\d+(?:\.\d+)?)\s*(?:and|or)\s*below\b", re.I)
_RANGE_AT_OR_ABOVE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:and|or)\s*above\b", re.I)
# Direction words a sentence uses when it means "greater than" / "less than"
# a number, regardless of whether that exact number was ever printed in the
# source table row (e.g. "70 and higher" for a row that only ever says "69").
_ABOVE_DIRECTION = re.compile(
    r"\b(?:above|over|greater\s+than|more\s+than|higher\s+than|exceeds?)\b"
    r"|\band\s+(?:up|higher|above)\b|\bor\s+(?:more|higher|above)\b",
    re.I,
)
_BELOW_DIRECTION = re.compile(
    r"\b(?:below|under|less\s+than|lower\s+than|at\s+most)\b"
    r"|\band\s+(?:down|lower|below)\b|\bor\s+(?:less|lower|below)\b",
    re.I,
)
# A claim that one row's status implicitly defines every *other*, unlisted
# row ("every other score passes") is the same complement-inference error as
# inverting a single boundary number, just phrased without any number at
# all. Kept to one sentence (no period in between) so an unrelated mention
# elsewhere in a long answer cannot coincidentally trip it.
_RESIDUAL_COMPLEMENT_CLAIM = re.compile(
    r"\b(?:every\s+other|any\s+other|all\s+other|everything\s+else|anything\s+else|the\s+rest)\b"
    r"[^.!?]{0,60}?\b(?:pass(?:es|ing|ed)?|fail(?:s|ing|ed)?|successful|unsatisfactory)\b",
    re.I,
)


def _split_fused_range_status(cell: str) -> list[str]:
    text = (cell or "").strip()
    match = _RANGE_THEN_STATUS.match(text)
    if match:
        return [match.group("range").strip(), match.group("status").strip()]
    loose = re.match(
        r"^(?P<range>\d.+\b(?:and\s+(?:below|above)|[-–]\s*\d+))\s+"
        r"(?P<status>[A-Za-z][A-Za-z /-]*)\s*$",
        text,
        flags=re.I,
    )
    if loose:
        return [loose.group("range").strip(), loose.group("status").strip()]
    return [text] if text else []


def _infer_table_cell_role(cell: str) -> str:
    text = (cell or "").strip()
    if _IDENTIFIER_CELL.match(text):
        return "Identifier"
    if _RANGE_CELL.search(text):
        return "Range"
    if re.search(r"[A-Za-z]", text):
        return "Status"
    return "Value"


def _table_record_from_row(row: list[str], header: list[str] | None) -> dict[str, str]:
    """One table row as a record, keyed both by the source's own header labels
    (if any) and by generic, shape-inferred roles (Identifier/Range/Status/Value).

    A header naming its columns "Tier Code" / "Score Range" / "Rating" (or any
    other institution-specific wording) describes the same *kind* of row as
    one with no header at all — the role tags are always computed from each
    cell's own shape so downstream code that reasons about value-to-status
    association (``_answer_contradicts_table_records``) has a table-agnostic
    place to read from, never tied to a particular table's own column-naming
    choices. A header-provided value for the same role name (rare, but
    possible if a header literally reads "Status") is left as authoritative;
    role-inference only fills in roles the header did not already supply.
    """
    cells: list[str] = []
    for cell in row:
        cells.extend(_split_fused_range_status(cell.strip()) if cell.strip() else [])
    record: dict[str, str] = {"raw": " — ".join(cells)}
    if header and len(header) == len(row):
        for label, value in zip(header, row):
            if value:
                record[label.strip() or "Value"] = value
    last_index = len(cells) - 1
    for index, cell in enumerate(cells):
        role = _infer_table_cell_role(cell)
        # A cell whose own shape is ambiguous (no digits, so neither a
        # numeric Identifier nor a Range) falls back to "Status" purely
        # because it contains letters — correct for a table's *trailing*
        # cell, but wrong for a *non-numeric key* in an earlier position
        # (e.g. a bullet row like "Complete — Approved" or "Tier A —
        # Certified", where the key itself is a plain word or short
        # phrase, not a number or code). The row's own position resolves
        # the ambiguity generically, with no institution-specific wording:
        # the last cell is always the outcome label, and an earlier
        # ambiguous cell is the row's own key when no numeric Identifier or
        # Range has already claimed that role.
        if role == "Status" and index != last_index and "Identifier" not in record and "Range" not in record:
            role = "Identifier"
        record.setdefault(role, cell)
        if role == "Status":
            record["Status"] = cell
    return record


def _format_table_record_line(record: dict[str, str]) -> str:
    order = ("Identifier", "Range", "Status", "Value")
    parts = [
        f"{key}: {record[key]}"
        for key in order
        if record.get(key)
    ]
    extra = [
        f"{key}: {value}"
        for key, value in record.items()
        if key not in {*order, "raw"} and value
    ]
    return "- " + " — ".join(parts or extra or [record.get("raw") or ""])


# --- Flattened-table normalization -----------------------------------------
#
# Everything above this line already parses a pipe-delimited row correctly
# once it exists. What real PDF/OCR-extracted institutional documents do not
# reliably produce is the pipe itself: a table's columns routinely survive
# extraction as plain whitespace, a range's own dash gets lost and leaves two
# bare numbers side by side, a "below/above N" cell gets phrased with the
# comparison word *before* its number instead of after, and a single row can
# even land as several consecutive short lines (one field per line). The
# helpers below rewrite each of those shapes into the same pipe-delimited
# form the parsing above already understands, so the fallback that depends on
# seeing rows does not depend on which of these extraction shapes a given
# source document happened to produce. None of this inspects or rewrites a
# *generated answer* — it only prepares retrieved source text before the
# audit reads it, so it cannot loosen how a claim in the model's own answer
# gets checked.
_COMPARISON_WORD_THEN_NUMBER = re.compile(
    r"\b(?:below|under)\s+(\d+(?:\.\d+)?)\b|\b(?:above|over)\s+(\d+(?:\.\d+)?)\b",
    re.I,
)


def _normalize_comparison_word_order(line: str) -> str:
    """Rewrite "below N"/"above N" (comparison word before its number) to the
    "N and below"/"N and above" shape every other range parser in this module
    already recognizes — a source table cell reading "Below 70" states the
    exact same boundary as one reading "70 and below", just word-first.
    """

    def _replace(match: re.Match[str]) -> str:
        below_value, above_value = match.groups()
        if below_value is not None:
            return f"{below_value} and below"
        return f"{above_value} and above"

    return _COMPARISON_WORD_THEN_NUMBER.sub(_replace, line)


# A line is only ever considered a candidate flattened-table row when it
# *starts* with a bare identifier-shaped token (a plain or decimal number, or
# a short all-caps code) — the same leading shape every pipe-delimited fixture
# already uses for its Identifier column. This alone rules out the vast
# majority of ordinary prose (a sentence starting mid-clause, a heading, a
# paragraph). What remains is guarded further below.
_BARE_LEADING_IDENTIFIER = re.compile(r"^(\d+(?:\.\d+)?|[A-Z]{2,6})[ \t]+(\S.*)$")
# The remainder after that identifier must *itself* immediately continue in a
# range-like shape (a bare number, a dash-range, or an already-normalized
# "N and below/above") for the line to be treated as tabular at all. An
# ordinary sentence that merely happens to start with a number ("3 out of 5
# students attended orientation") almost never continues this way — its next
# token is a word, not another number — so this second gate is what keeps
# prose from being mistaken for a table row.
_REMAINDER_STARTS_LIKE_RANGE = re.compile(
    r"^\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\b"
    r"|^\d+(?:\.\d+)?\s*(?:and|or)\s*(?:below|above)\b",
    re.I,
)
_BARE_IDENTIFIER_ONLY = re.compile(r"^(?:\d+(?:\.\d+)?|[A-Z]{2,6})$")
_BARE_RANGE_ONLY = re.compile(
    r"^\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?$"
    r"|^\d+(?:\.\d+)?\s*(?:and|or)\s*(?:below|above)$",
    re.I,
)
_BARE_STATUS_ONLY = re.compile(r"^[A-Za-z][A-Za-z /-]*$")


def _merge_identifier_range_status_lines(lines: list[str]) -> list[str]:
    """Fold a bare Identifier / Range / (optional) Status split across
    consecutive short lines back into one row, mirroring how the same three
    values would read if a document's table had kept its columns on one
    line. Only lines that are *exactly* one bare value (nothing else) are
    ever folded, so this cannot accidentally swallow ordinary paragraph
    text that merely starts with a short line.
    """
    merged: list[str] = []
    index = 0
    total = len(lines)
    while index < total:
        current = lines[index].strip()
        if _BARE_IDENTIFIER_ONLY.match(current) and index + 1 < total:
            next_line = lines[index + 1].strip()
            if _BARE_RANGE_ONLY.match(next_line):
                parts = [current, next_line]
                consumed = 2
                if index + 2 < total:
                    third = lines[index + 2].strip()
                    if third and "|" not in third and _BARE_STATUS_ONLY.match(third):
                        parts.append(third)
                        consumed = 3
                merged.append(" ".join(parts))
                index += consumed
                continue
        merged.append(lines[index])
        index += 1
    return merged


def _split_flattened_row_remainder(remainder: str) -> list[str]:
    """The text after a flattened row's leading identifier, as one or more
    pipe-ready cells.

    Columns separated by two or more spaces (common when a PDF extractor
    preserves original column alignment) split cleanly. A range whose own
    separator was lost in extraction, leaving two bare numbers side by side
    ("90 100"), is rejoined with a dash before anything else runs, so the
    existing fused range/status splitter (which already understands "90-100
    Excellent") can take it from there unchanged. Anything else is left as
    one cell for that same fused splitter to decompose.
    """
    remainder = remainder.strip()
    multi_space_cells = [cell.strip() for cell in re.split(r"[ \t]{2,}", remainder) if cell.strip()]
    if len(multi_space_cells) >= 2:
        return multi_space_cells
    two_bare_numbers = re.match(
        r"^(\d+(?:\.\d+)?)[ \t]+(\d+(?:\.\d+)?)([ \t]+.*)?$", remainder
    )
    if two_bare_numbers:
        lo, hi, trailing = two_bare_numbers.groups()
        remainder = f"{lo}-{hi}{trailing or ''}"
    return [remainder] if remainder else []


def _normalize_flattened_table_lines(text: str) -> str:
    """Rewrite recognizable non-pipe-delimited table rows into pipe-delimited
    ones, so the existing (unchanged) pipe-based parsing below can see them.
    Lines that already contain a pipe, or that do not look like tabular data
    at all, pass through untouched.
    """
    lines = [_normalize_comparison_word_order(line) for line in (text or "").splitlines()]
    lines = _merge_identifier_range_status_lines(lines)
    rewritten: list[str] = []
    for line in lines:
        if "|" in line:
            rewritten.append(line)
            continue
        match = _BARE_LEADING_IDENTIFIER.match(line.strip())
        if not match:
            rewritten.append(line)
            continue
        identifier, remainder = match.groups()
        if not _REMAINDER_STARTS_LIKE_RANGE.match(remainder):
            rewritten.append(line)
            continue
        cells = _split_flattened_row_remainder(remainder)
        if not cells:
            rewritten.append(line)
            continue
        rewritten.append(" | ".join([identifier, *cells]))
    return "\n".join(rewritten)


def _format_structured_tables(text: str) -> str:
    """Rewrite pipe-delimited institutional tables so each row stays associated.

    Flattened rows are easy for a model to read backwards (treating a failing
    range as a passing threshold). Each row is one record with inferred
    Identifier / Range / Status roles when no header is present. No
    institutional facts are invented. A source table whose columns did not
    survive extraction as literal pipes is normalized to the same shape
    first (see ``_normalize_flattened_table_lines``) so this still applies.
    """
    lines = _normalize_flattened_table_lines(text).splitlines()
    out: list[str] = []
    pending: list[str] = []

    def _flush() -> None:
        if len(pending) < 2:
            out.extend(pending)
            pending.clear()
            return
        parsed = [[cell.strip() for cell in row.split("|")] for row in pending]
        header: list[str] | None = None
        first = parsed[0]
        remaining = parsed[1:]
        first_has_digit = any(re.search(r"\d", cell) for cell in first)
        remaining_has_digit = any(
            any(re.search(r"\d", cell) for cell in row) for row in remaining
        )
        if first and not first_has_digit and remaining_has_digit:
            # The rest of the table carries a numeric Identifier/Range, and
            # this row alone does not -- a text header, not a data row.
            # (A table with *no* numeric column at all -- a purely
            # categorical bullet list like "Complete -- Approved" -- takes
            # the other branch below and keeps every row as data instead;
            # a digit-based check has nothing to compare against there.)
            header = first
            # A multi-page extraction often repeats the header partway
            # through a table. Any later row with no digit in any cell is,
            # by the same test used to recognize the header above, not a
            # data row either.
            data_rows = [row for row in remaining if any(re.search(r"\d", cell) for cell in row)]
        else:
            data_rows = parsed
        out.append(
            "Structured table (each row is one record; Identifier, Range, and "
            "Status on a row belong only to that row):"
        )
        has_status = False
        for row in data_rows:
            record = _table_record_from_row(row, header)
            if record.get("Status"):
                has_status = True
            out.append(_format_table_record_line(record))
        if has_status:
            out.append(
                "Table semantics: a Status/interpretation label is authoritative "
                "for its own Identifier and Range only. Do not assume a larger "
                "identifier means 'above' or a better outcome. Do not write "
                "'X and above' unless those words appear in a cell. A row "
                "labeled Failed, Conditional, Incomplete, or Dropped is not a "
                "passing or successful outcome."
            )
        pending.clear()

    for line in lines:
        if "|" in line:
            pending.append(line)
        elif not line.strip() and pending:
            # A blank spacer line between rows (a plausible PDF-extraction
            # artifact) must not split one table into several isolated,
            # too-short-to-recognize groups.
            continue
        else:
            _flush()
            out.append(line)
    _flush()
    return "\n".join(out)


def _structured_table_records_from_text(text: str) -> list[dict[str, str]]:
    """Parse Identifier/Range/Status records from formatted table context."""
    records: list[dict[str, str]] = []
    in_table = False
    for line in (text or "").splitlines():
        if line.startswith("Structured table"):
            in_table = True
            continue
        if in_table and line.startswith("- "):
            record: dict[str, str] = {"raw": line[2:]}
            for part in line[2:].split(" — "):
                if ": " in part:
                    key, value = part.split(": ", 1)
                    record[key.strip()] = value.strip()
            records.append(record)
            continue
        if in_table and line and not line.startswith("- "):
            in_table = False
    return records


def _record_boundary_numbers(record: dict[str, str]) -> set[str]:
    """Numeric tokens appearing in a record's own Identifier/Range values."""
    text = " ".join(
        str(record.get(key) or "") for key in ("Identifier", "Range")
    )
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def _format_boundary_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def _record_range_threshold(record: dict[str, str]) -> tuple[float, str] | None:
    """A record's own Range/Identifier as a single open-ended threshold.

    Only rows phrased as "N and/or below" or "N and/or above" state just one
    of their own edge numbers literally (a closed band like "60-74" already
    states both of its own edges, so it needs no derived complement). Returns
    ``(boundary, direction)`` with direction ``"at_or_below"`` or
    ``"at_or_above"``, or ``None`` when the row is not phrased as an
    open-ended threshold.
    """
    text = " ".join(str(record.get(key) or "") for key in ("Range", "Identifier"))
    match = _RANGE_AT_OR_BELOW.search(text)
    if match:
        return float(match.group(1)), "at_or_below"
    match = _RANGE_AT_OR_ABOVE.search(text)
    if match:
        return float(match.group(1)), "at_or_above"
    return None


def _record_status_polarity(status: str | None) -> str | None:
    if not status or not status.strip():
        return None
    return "negative" if _NEGATIVE_STATUS.search(status) else "positive"


def _authorized_complement_numbers(records: list[dict[str, str]]) -> set[str]:
    """Boundary numbers a generated answer may pair with the *opposite*
    passing/failing claim because another record's own threshold explicitly
    states that exact complement immediately adjacent to it (e.g. an
    explicit "70 and above = Passing" row beside "69 and below = Failed").
    Two rows that already partition the same threshold this way are an
    explicit textual statement of both sides, not an invented inference.
    """
    thresholds: list[tuple[float, str, str]] = []
    for record in records:
        threshold = _record_range_threshold(record)
        polarity = _record_status_polarity(record.get("Status"))
        if threshold and polarity:
            thresholds.append((threshold[0], threshold[1], polarity))
    authorized: set[str] = set()
    for boundary, direction, polarity in thresholds:
        adjacent = boundary + 1 if direction == "at_or_below" else boundary - 1
        opposite_polarity = "positive" if polarity == "negative" else "negative"
        opposite_direction = "at_or_above" if direction == "at_or_below" else "at_or_below"
        for other_boundary, other_direction, other_polarity in thresholds:
            if (
                other_polarity == opposite_polarity
                and other_direction == opposite_direction
                and abs(other_boundary - adjacent) < 1e-9
            ):
                authorized.add(_format_boundary_number(boundary))
                authorized.add(_format_boundary_number(adjacent))
    return authorized


def _answer_contradicts_table_records(answer: str, records: list[dict[str, str]]) -> bool:
    """True when a generated answer inverts a table row's status or invents 'and above'.

    A negative-status row is identified by *either* of its own value markers
    — the row's Identifier (e.g. a GPA-style code) or its Range (e.g. a
    percentage band) — since a generated answer may restate the row using
    whichever value it reads as more natural (a real, reproduced failure:
    "a range of 70-74 is passing" slipped past a check that only looked for
    the Identifier "4.00").

    Matching is at *two* levels, both tied to the same one record so this
    never becomes a cross-record lookup: the literal marker string (for
    non-numeric codes like "INC"), and the record's own *numbers* extracted
    from those markers. The number-level match is what closes a real,
    reproduced gap: a generated answer paraphrasing "69 and below" down to
    just "above 69" (or "70 and higher") never reproduces the captured
    marker string verbatim, so whole-string matching alone missed it, even
    though the number "69"/"70" is still literally the row's own boundary.

    A third level closes the gap where the paraphrase names the *adjacent*
    number instead ("70 and higher" for a row that only ever prints "69"),
    which is not one of the record's own numbers at all: that adjacent value
    is derived from the row's own open-ended boundary and only counted when
    the sentence also uses "above"/"greater than"/"and higher"-style
    direction language, so an unrelated mention of that number elsewhere
    cannot false-positive. A boundary (its own number or the derived
    adjacent one) that another record's own row explicitly assigns the
    opposite, correct status is treated as authorized — two rows that
    already state both sides of a threshold are an explicit textual
    statement, not an invented inference, and summarizing both is allowed.
    Separately, a claim that one row's status defines *every other* row
    ("every other score passes") is the same complement error with no
    number involved at all, so it is caught on its own.
    """
    if not answer or not records:
        return False
    evidence = " ".join(
        f"{record.get('Identifier', '')} {record.get('Range', '')} {record.get('Status', '')} {record.get('raw', '')}"
        for record in records
    ).casefold()
    if _AND_ABOVE_CLAIM.search(answer) and "and above" not in evidence:
        return True
    if _RESIDUAL_COMPLEMENT_CLAIM.search(answer) and not _RESIDUAL_COMPLEMENT_CLAIM.search(evidence):
        return True

    authorized = _authorized_complement_numbers(records)
    sentences = re.split(r"(?<=[.!?])\s+", answer)

    for record in records:
        status = record.get("Status") or ""
        if not _NEGATIVE_STATUS.search(status):
            continue
        markers = [
            value.strip()
            for value in (record.get("Identifier"), record.get("Range"))
            if value and value.strip()
        ]
        record_numbers = _record_boundary_numbers(record)
        threshold = _record_range_threshold(record)
        complement_number = (
            _format_boundary_number(threshold[0] + 1)
            if threshold and threshold[1] == "at_or_below"
            else None
        )
        if not markers and not record_numbers and not complement_number:
            continue
        for sentence in sentences:
            literal_hit = any(marker in sentence for marker in markers)
            sentence_numbers = set(re.findall(r"\d+(?:\.\d+)?", sentence))
            numeric_hit = bool(record_numbers & sentence_numbers)
            complement_hit = bool(
                complement_number
                and complement_number in sentence_numbers
                and _ABOVE_DIRECTION.search(sentence)
            )
            if not (literal_hit or numeric_hit or complement_hit):
                continue
            matched_numbers = (record_numbers & sentence_numbers) | (
                {complement_number} if complement_hit else set()
            )
            if matched_numbers and matched_numbers <= authorized:
                continue
            # Copying the status word ("Conditional Failure is passing") is still
            # an inversion of that row.
            if _PASSING_CLAIM.search(sentence):
                return True
    # Symmetric case: claiming a row with an explicit, non-negative status
    # (e.g. "Good", "Satisfactory") "fails" is the same inversion in the
    # other direction. Only applies to rows whose status is actually present
    # and is not itself a negative label — an unlabeled row's meaning is not
    # asserted either way, so it is not used as evidence here.
    for record in records:
        status = record.get("Status") or ""
        if not status.strip() or _NEGATIVE_STATUS.search(status):
            continue
        markers = [
            value.strip()
            for value in (record.get("Identifier"), record.get("Range"))
            if value and value.strip()
        ]
        record_numbers = _record_boundary_numbers(record)
        threshold = _record_range_threshold(record)
        complement_number = (
            _format_boundary_number(threshold[0] - 1)
            if threshold and threshold[1] == "at_or_above"
            else None
        )
        if not markers and not record_numbers and not complement_number:
            continue
        for sentence in sentences:
            literal_hit = any(marker in sentence for marker in markers)
            sentence_numbers = set(re.findall(r"\d+(?:\.\d+)?", sentence))
            numeric_hit = bool(record_numbers & sentence_numbers)
            complement_hit = bool(
                complement_number
                and complement_number in sentence_numbers
                and _BELOW_DIRECTION.search(sentence)
            )
            if not (literal_hit or numeric_hit or complement_hit):
                continue
            matched_numbers = (record_numbers & sentence_numbers) | (
                {complement_number} if complement_hit else set()
            )
            if matched_numbers and matched_numbers <= authorized:
                continue
            if _FAILING_CLAIM.search(sentence):
                return True
    return False


# A merged multi-row range/category claim ("75 to 100 is Passing", "90 and
# above is Excellent", "between 60 and 100 is Certified"). Distinct from the
# single-row complement inference above: this is several *separately*
# grounded rows synthesized into one broader rule the table never states as
# a unit. Domain-agnostic on purpose — it matches whatever literal Status
# text a record actually carries (Certified, Eligible, Excellent, Standard
# Fee, ...), never a fixed vocabulary of pass/fail words.
_BOUNDED_RANGE_CLAIM = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|–|to|through)\s*(\d+(?:\.\d+)?)",
    re.I,
)
_BOUNDED_BETWEEN_CLAIM = re.compile(
    r"\bbetween\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)\b",
    re.I,
)
# Two different phrasings of an open-ended claim carry different inclusivity
# at the number they name: "N and above"/"N or higher"/"at or above N" all
# name their own *inclusive* edge N directly, exactly like a source row
# phrased "N and above" would. "above N"/"greater than N" instead name the
# *excluded* edge — the boundary itself is not part of the claimed span.
# Earlier code converted that exclusion into a synthetic "N + 1" inclusive
# edge, which silently assumed every axis is an integer-step grid; a
# fractional-step axis (e.g. grade points spaced 0.25 apart) made that
# guess land on a number that is not any real row's edge at all, so the
# claim was checked against nothing and passed unexamined. The excluded
# edge is now carried through as-is (`lo_exclusive`/`hi_exclusive`) and
# resolved later against the source's own actual boundary values — never a
# hardcoded step. A negative lookbehind keeps "at or above"/"at or below"
# from also matching the strict pattern for the same number.
_AT_OR_ABOVE_RANGE_CLAIM = re.compile(
    r"\bat\s+or\s+above\s+(\d+(?:\.\d+)?)",
    re.I,
)
_AT_OR_BELOW_RANGE_CLAIM = re.compile(
    r"\bat\s+or\s+below\s+(\d+(?:\.\d+)?)",
    re.I,
)
_UP_TO_RANGE_CLAIM = re.compile(
    r"\bup\s+to\s+(\d+(?:\.\d+)?)",
    re.I,
)
_FROM_UPWARD_RANGE_CLAIM = re.compile(
    r"\bfrom\s+(\d+(?:\.\d+)?)\s+upward\b",
    re.I,
)
_STRICT_ABOVE_RANGE_CLAIM = re.compile(
    r"\b(?<!at or )(?:above|over|greater\s+than|more\s+than|higher\s+than|exceeds?)\s+(\d+(?:\.\d+)?)",
    re.I,
)
_INCLUSIVE_ABOVE_RANGE_CLAIM = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:and|or)\s*(?:up|higher|above|more|greater)\b",
    re.I,
)
_STRICT_BELOW_RANGE_CLAIM = re.compile(
    r"\b(?<!at or )(?:below|under|less\s+than|lower\s+than)\s+(\d+(?:\.\d+)?)",
    re.I,
)
_INCLUSIVE_BELOW_RANGE_CLAIM = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:and|or)\s*(?:down|lower|below|less)\b",
    re.I,
)


def _record_interval(record: dict[str, str]) -> tuple[float, float] | None:
    """A record's own Range/Identifier as a numeric interval, when it states one.

    Reuses the existing open-ended threshold parser for "N and/or
    below/above" rows, and additionally recognizes a plain closed band like
    "60-74". A non-numeric identifier (a code such as "INC") yields no
    interval and is simply excluded from range-merge reasoning — it can
    still carry a Status label, just never a numeric span.
    """
    threshold = _record_range_threshold(record)
    if threshold:
        boundary, direction = threshold
        if direction == "at_or_below":
            return (float("-inf"), boundary)
        return (boundary, float("inf"))
    text = " ".join(str(record.get(key) or "") for key in ("Range", "Identifier"))
    match = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", text)
    if match:
        lo, hi = float(match.group(1)), float(match.group(2))
        return (min(lo, hi), max(lo, hi))
    return None


def _distinct_status_labels(records: list[dict[str, str]]) -> list[str]:
    """Each record's own literal Status text, longest first.

    Longest-first ordering lets a more specific label (e.g. "Conditional
    Failure") win over a shorter, coincidentally-contained word when
    matching an answer sentence against the table's own vocabulary.
    """
    seen: set[str] = set()
    labels: list[str] = []
    for record in records:
        status = (record.get("Status") or "").strip()
        if status and status.casefold() not in seen:
            seen.add(status.casefold())
            labels.append(status)
    labels.sort(key=len, reverse=True)
    return labels


def _literal_status_key(status: str | None) -> str | None:
    text = (status or "").strip()
    return text.casefold() or None


def _polarity_status_key(status: str | None) -> str | None:
    """The row's outcome polarity ("positive"/"negative"), reusing the same
    generic English pass/fail vocabulary already used for the single-row
    complement check above — never an institution-specific word list. This
    is a second, parallel grouping key alongside the row's own literal
    Status text: a claim phrased with generic words ("passing", "failing")
    rather than the table's own label ("Certified", "Satisfactory") still
    needs *some* per-row key to check merged claims against, and polarity is
    the only domain-general stand-in for "good outcome" / "bad outcome".
    """
    return _record_status_polarity(status)


def _authorized_spans_by_key(
    records: list[dict[str, str]],
    key_fn,
) -> list[tuple[float, float, str]]:
    """Maximal same-key numeric spans (range axis) a merged claim may cite as
    grounded, keyed by whatever ``key_fn`` extracts from each record's own
    Status text — its literal label, or its generic pass/fail polarity.

    Consecutive records (sorted by their own lower bound) are folded into
    one span only while every one of them maps to the *same* key and each
    next record's own lower bound picks up where the previous one's upper
    bound left off (allowing a difference of at most 1, the usual off-by-one
    style of adjacent integer bands like "84" then "85", as well as scales
    that touch exactly). A record with a different key, an unresolvable key
    (blank Status under the literal key, or a Status with no clear polarity
    under the polarity key), or a numeric gap breaks the run — that row's
    own range is never silently folded into a neighboring broader claim. An
    explicit row that already states the combined rule as its own single
    row (e.g. a table listing both granular tiers and a summary "75 and
    above = Passing" row) becomes its own directly-supported span the same
    way — no separate "explicit text" special case is needed.
    """
    entries = sorted(
        (
            (interval[0], interval[1], key_fn(record.get("Status")))
            for record in records
            if (interval := _record_interval(record)) is not None
        ),
        key=lambda entry: entry[0],
    )
    spans: list[tuple[float, float, str]] = []
    index = 0
    total = len(entries)
    while index < total:
        lo, hi, key = entries[index]
        if not key:
            index += 1
            continue
        run_lo, run_hi = lo, hi
        next_index = index + 1
        while next_index < total:
            next_lo, next_hi, next_key = entries[next_index]
            if next_key != key or next_lo - run_hi > 1 + 1e-9:
                break
            run_hi = max(run_hi, next_hi)
            next_index += 1
        spans.append((run_lo, run_hi, key))
        index = next_index
    return spans


def _authorized_range_spans(records: list[dict[str, str]]) -> list[tuple[float, float, str]]:
    return _authorized_spans_by_key(records, _literal_status_key)


def _record_identifier_value(record: dict[str, str]) -> float | None:
    """A record's own Identifier as a bare numeric code point (e.g. a grade
    point "4.00"), distinct from its Range. Only a *pure* number counts — a
    non-numeric code ("INC") is not a point on this axis at all. Kept apart
    from ``_record_interval`` (the Range axis) because some domains carry
    two independent numeric axes on the same row (a grade-point identifier
    *and* a percentage range), moving in opposite directions of "better" —
    conflating them onto one number line is exactly what let a claim like
    "4.00 and above" (a grade-point code, where larger means *worse*) get
    silently checked against percentage-range evidence instead, or against
    nothing at all.
    """
    text = (record.get("Identifier") or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    return None


def _identifier_axis_points(
    records: list[dict[str, str]],
) -> list[tuple[float, str | None]]:
    return [
        (value, record.get("Status"))
        for record in records
        if (value := _record_identifier_value(record)) is not None
    ]


def _axis_bounds(values: list[float]) -> tuple[float, float] | None:
    finite = [v for v in values if v not in (float("inf"), float("-inf"))]
    return (min(finite), max(finite)) if finite else None


def _claim_targets_axis(lo: float, hi: float, bounds: tuple[float, float] | None) -> bool:
    """Whether a claim's own finite boundary number(s) plausibly belong to
    this axis at all, so a claim is only ever checked against an axis its
    own numbers could realistically be describing — a grade-point claim
    like "4.00 and above" should never be evaluated against a 0-100
    percentage axis just because 4.00 is technically less than 100.
    """
    if bounds is None:
        return False
    axis_lo, axis_hi = bounds
    points = [value for value in (lo, hi) if value not in (float("inf"), float("-inf"))]
    if not points:
        return False
    margin = max(1.0, (axis_hi - axis_lo) * 0.05)
    return all(axis_lo - margin <= point <= axis_hi + margin for point in points)


def _identifier_axis_supports(
    lo: float,
    hi: float,
    lo_exclusive: bool,
    hi_exclusive: bool,
    key_value: str,
    points: list[tuple[float, str | None]],
    key_fn,
) -> bool | None:
    """Whether every identifier-axis point inside a claimed span agrees with
    the claimed key. Identifier codes are a *discrete* list the source
    itself defines (whatever codes it happens to use), not a continuous
    scale — so unlike the Range axis there is no "gap tolerance" to reason
    about: every point the claim's span actually covers must agree, full
    stop. Returns ``None`` (no verdict) when nothing on this axis falls
    inside the claimed span at all, rather than treating an empty axis as
    either grounded or contradicted.

    An excluded edge (a claim phrased "above N"/"below N") is compared with
    a strict inequality against each point's *actual* value instead of
    guessing a shifted number — correct regardless of whether the axis
    happens to step by whole numbers, quarters, or any other spacing.
    """
    covered = [
        (value, status)
        for value, status in points
        if (value > lo + 1e-9 if lo_exclusive else value >= lo - 1e-9)
        and (value < hi - 1e-9 if hi_exclusive else value <= hi + 1e-9)
    ]
    if not covered:
        return None
    for _, status in covered:
        if key_fn(status) != key_value:
            return False
    return True


def _range_claim_is_authorized(
    lo: float, hi: float, label: str, spans: list[tuple[float, float, str]]
) -> bool:
    for span_lo, span_hi, span_label in spans:
        if span_label != label:
            continue
        if lo == float("-inf"):
            if span_lo == float("-inf") and hi <= span_hi + 1e-9:
                return True
            continue
        if hi == float("inf"):
            if span_hi == float("inf") and lo >= span_lo - 1e-9:
                return True
            continue
        if lo >= span_lo - 1e-9 and hi <= span_hi + 1e-9:
            return True
    return False


def _extract_range_claims(sentence: str) -> list[tuple[float, float, bool, bool]]:
    """Numeric spans a clause claims, as ``(lo, hi, lo_exclusive, hi_exclusive)``.

    ``lo_exclusive``/``hi_exclusive`` mark an edge the clause names but does
    not itself include (an "above N"/"below N" phrasing) — the boundary is
    carried through literally rather than shifted by a guessed step, so it
    can later be checked against whichever real values the source actually
    defines on that axis.
    """
    claims: list[tuple[float, float, bool, bool]] = []
    for match in _BOUNDED_RANGE_CLAIM.finditer(sentence):
        lo, hi = float(match.group(1)), float(match.group(2))
        claims.append((min(lo, hi), max(lo, hi), False, False))
    for match in _BOUNDED_BETWEEN_CLAIM.finditer(sentence):
        lo, hi = float(match.group(1)), float(match.group(2))
        claims.append((min(lo, hi), max(lo, hi), False, False))
    for match in _AT_OR_ABOVE_RANGE_CLAIM.finditer(sentence):
        claims.append((float(match.group(1)), float("inf"), False, False))
    for match in _AT_OR_BELOW_RANGE_CLAIM.finditer(sentence):
        claims.append((float("-inf"), float(match.group(1)), False, False))
    for match in _STRICT_ABOVE_RANGE_CLAIM.finditer(sentence):
        claims.append((float(match.group(1)), float("inf"), True, False))
    for match in _INCLUSIVE_ABOVE_RANGE_CLAIM.finditer(sentence):
        claims.append((float(match.group(1)), float("inf"), False, False))
    for match in _STRICT_BELOW_RANGE_CLAIM.finditer(sentence):
        claims.append((float("-inf"), float(match.group(1)), False, True))
    for match in _INCLUSIVE_BELOW_RANGE_CLAIM.finditer(sentence):
        claims.append((float("-inf"), float(match.group(1)), False, False))
    for match in _UP_TO_RANGE_CLAIM.finditer(sentence):
        claims.append((float("-inf"), float(match.group(1)), False, False))
    for match in _FROM_UPWARD_RANGE_CLAIM.finditer(sentence):
        claims.append((float(match.group(1)), float("inf"), False, False))
    return claims


def _nearest_value_above(boundary: float, values: set[float]) -> float | None:
    candidates = [value for value in values if value > boundary + 1e-9]
    return min(candidates) if candidates else None


def _nearest_value_below(boundary: float, values: set[float]) -> float | None:
    candidates = [value for value in values if value < boundary - 1e-9]
    return max(candidates) if candidates else None


def _resolve_exclusive_edges(
    lo: float,
    hi: float,
    lo_exclusive: bool,
    hi_exclusive: bool,
    boundary_values: set[float],
) -> tuple[float, float] | None:
    """Turn an excluded edge into the source's own next real boundary value
    on that side, so an "above N"/"below N" claim is compared against
    whatever the table's rows actually define next — never a hardcoded
    step. Returns ``None`` when an excluded, finite edge has no real
    boundary beyond it to resolve against: the interval span check this
    feeds has nothing concrete to authorize the claim against, so it is
    left unauthorized on this axis (a separate, direct point-by-point check
    still covers the identifier axis for exactly this edge).
    """
    resolved_lo = lo
    if lo_exclusive and lo not in (float("-inf"), float("inf")):
        snapped = _nearest_value_above(lo, boundary_values)
        if snapped is None:
            return None
        resolved_lo = snapped
    resolved_hi = hi
    if hi_exclusive and hi not in (float("-inf"), float("inf")):
        snapped = _nearest_value_below(hi, boundary_values)
        if snapped is None:
            return None
        resolved_hi = snapped
    return (resolved_lo, resolved_hi)


def _sentence_claimed_label(sentence: str, labels: list[str]) -> str | None:
    folded = sentence.casefold()
    for label in labels:
        if re.search(rf"\b{re.escape(label.casefold())}\b", folded):
            return label.casefold()
    return None


def _sentence_claimed_status(
    sentence: str, labels: list[str]
) -> tuple[str, str] | None:
    """The status a clause is claiming, as ``(kind, value)``.

    Tries the table's own literal vocabulary first (``kind="literal"``) —
    the more specific, domain-accurate match whenever the answer actually
    echoes the source's own wording (e.g. "Certified", "Conditional
    Failure"). Falls back to the same generic English pass/fail polarity
    words the single-row complement check already uses (``kind="polarity"``,
    value ``"positive"``/``"negative"``) only when no literal label matched
    — this is what lets a claim phrased as "...represent passing outcomes"
    be checked at all against a table whose own Status column never once
    spells out the word "passing" (e.g. it only ever says "Excellent",
    "Conditional Failure", "Failed"), which is exactly the shape that let
    the reported live answer escape a literal-label-only checker.
    """
    label = _sentence_claimed_label(sentence, labels)
    if label:
        return ("literal", label)
    if _PASSING_CLAIM.search(sentence):
        return ("positive", "positive")
    if _FAILING_CLAIM.search(sentence):
        return ("negative", "negative")
    return None


def _claim_is_supported(
    lo: float,
    hi: float,
    lo_exclusive: bool,
    hi_exclusive: bool,
    claimed: tuple[str, str],
    records: list[dict[str, str]],
    range_bounds: tuple[float, float] | None,
    range_boundary_values: set[float],
    identifier_points: list[tuple[float, str | None]],
    identifier_bounds: tuple[float, float] | None,
) -> bool:
    """Whether a single claimed span+status is grounded on *every* axis its
    own numbers plausibly belong to.

    A claim is checked on the Range axis (a table's percentage/score bands)
    and, independently, on the Identifier axis (a table's own numeric codes,
    e.g. grade points) whenever its numbers are plausibly that axis's — a
    row can carry both at once, moving in opposite directions of "better",
    and a claim naming one axis's numbers must never be silently validated
    against the other axis's (unrelated) evidence. A claim not plausibly
    describing either axis has nothing to check it against and is left
    alone (not this function's concern).
    """
    kind, value = claimed
    key_fn = _literal_status_key if kind == "literal" else _polarity_status_key
    supported = True
    if _claim_targets_axis(lo, hi, range_bounds):
        resolved = _resolve_exclusive_edges(lo, hi, lo_exclusive, hi_exclusive, range_boundary_values)
        if resolved is None:
            supported = False
        else:
            spans = _authorized_spans_by_key(records, key_fn)
            if not _range_claim_is_authorized(resolved[0], resolved[1], value, spans):
                supported = False
    if _claim_targets_axis(lo, hi, identifier_bounds):
        result = _identifier_axis_supports(
            lo, hi, lo_exclusive, hi_exclusive, value, identifier_points, key_fn
        )
        if result is False:
            supported = False
    return supported


class _RecordAxisContext(NamedTuple):
    range_bounds: tuple[float, float] | None
    range_boundary_values: set[float]
    identifier_points: list[tuple[float, str | None]]
    identifier_bounds: tuple[float, float] | None


def _record_axis_context(records: list[dict[str, str]]) -> _RecordAxisContext:
    """Precompute the Range- and Identifier-axis facts every clause check
    below needs, once per answer rather than once per clause."""
    range_boundary_values = {
        bound
        for record in records
        if (interval := _record_interval(record)) is not None
        for bound in interval
        if bound not in (float("inf"), float("-inf"))
    }
    range_bounds = _axis_bounds(
        [
            bound
            for record in records
            if (interval := _record_interval(record)) is not None
            for bound in interval
        ]
    )
    identifier_points = _identifier_axis_points(records)
    identifier_bounds = _axis_bounds([value for value, _ in identifier_points])
    return _RecordAxisContext(
        range_bounds, range_boundary_values, identifier_points, identifier_bounds
    )


def _answer_clauses(answer: str) -> list[str]:
    """Split a generated answer into clauses for per-claim scrutiny.

    A single sentence often lists more than one row ("80-100 is Certified,
    and 50-64 is also Certified, but 65-79 is Probationary") — splitting
    further on comma/semicolon clause boundaries pairs each range mention
    with the status actually next to it, instead of one status winning for
    the whole sentence and being checked against every range in it.
    """
    sentences = re.split(r"(?<=[.!?])\s+", answer)
    return [
        clause
        for sentence in sentences
        for clause in re.split(r"[,;]\s*", sentence)
        if clause.strip()
    ]


def _answer_synthesizes_unsupported_range(answer: str, records: list[dict[str, str]]) -> bool:
    """True when the answer merges several individually-grounded rows into a
    broader global range/boundary/category claim no single row (or explicit
    combined row) actually states.

    Distinct from ``_answer_contradicts_table_records``: that function
    catches a *single* row's own boundary or status being inverted or
    paraphrased into its complement. This one catches an answer that is
    locally accurate about each row it touches but *synthesizes a new,
    broader rule* by summarizing multiple neighboring rows together — a
    merge that is only ever legitimate when the rows being merged share the
    exact same status (their own literal label, or the same generic
    pass/fail polarity when the claim uses that vocabulary instead) with no
    gap and no differing/unlabeled row between them, or when the source
    itself already states the merged rule as one row.
    """
    if not answer or not records:
        return False
    labels = _distinct_status_labels(records)
    if not labels:
        return False
    axis = _record_axis_context(records)
    for clause in _answer_clauses(answer):
        claimed = _sentence_claimed_status(clause, labels)
        if not claimed:
            continue
        for lo, hi, lo_exclusive, hi_exclusive in _extract_range_claims(clause):
            if not _claim_is_supported(
                lo,
                hi,
                lo_exclusive,
                hi_exclusive,
                claimed,
                records,
                axis.range_bounds,
                axis.range_boundary_values,
                axis.identifier_points,
                axis.identifier_bounds,
            ):
                return True
    return False


def _table_has_mixed_statuses(records: list[dict[str, str]]) -> bool:
    """True when the structured evidence carries more than one distinct
    Status label. A single-status table has nothing for a generated answer
    to get wrong by generalizing across rows, so it needs no extra
    scrutiny beyond the checks above.
    """
    statuses = {
        key for record in records if (key := _literal_status_key(record.get("Status")))
    }
    return len(statuses) > 1


def _clause_status_claim_is_grounded(
    clause: str,
    claimed: tuple[str, str],
    records: list[dict[str, str]],
    axis: _RecordAxisContext,
) -> bool:
    """Whether a clause's status claim is *affirmatively* verifiable as
    grounded, using whichever numeric span it names.

    A recognized comparison phrasing ("above N", "N and below", "at or
    above N", ...) is resolved exactly as in
    ``_answer_synthesizes_unsupported_range``. Any other phrasing — a
    wording this module has never been taught, and never will finish being
    taught, since English has no fixed list of ways to say "greater than" —
    is not silently passed through: the plain numbers the clause itself
    contains are taken as the span at stake (one number as the exact point
    it names, two or more as the closed interval between the smallest and
    largest actually written down), and checked the same way every
    recognized phrasing is. A clause with no number at all can still be
    grounded when it names exactly one record's own non-numeric key
    verbatim (e.g. "Tier A", "Complete" — a structured bullet/list row's
    identifier is not always a number); anything less specific than that
    has nothing to verify it against and is denied — the policy this
    function serves only ever runs when the source already carries more
    than one status, so an unanchored status claim in that shape can never
    be told apart from an invented one.
    """
    range_claims = _extract_range_claims(clause)
    if range_claims:
        return all(
            _claim_is_supported(
                lo,
                hi,
                lo_exclusive,
                hi_exclusive,
                claimed,
                records,
                axis.range_bounds,
                axis.range_boundary_values,
                axis.identifier_points,
                axis.identifier_bounds,
            )
            for lo, hi, lo_exclusive, hi_exclusive in range_claims
        )
    numbers = {float(match) for match in re.findall(r"\d+(?:\.\d+)?", clause)}
    if numbers:
        lo, hi = min(numbers), max(numbers)
        return _claim_is_supported(
            lo,
            hi,
            False,
            False,
            claimed,
            records,
            axis.range_bounds,
            axis.range_boundary_values,
            axis.identifier_points,
            axis.identifier_bounds,
        )
    return _clause_matches_exactly_one_non_numeric_record(clause, claimed, records)


def _clause_matches_exactly_one_non_numeric_record(
    clause: str, claimed: tuple[str, str], records: list[dict[str, str]]
) -> bool:
    """Whether a number-free clause is anchored to exactly one record via
    that record's own non-numeric Identifier or Range text appearing
    verbatim (e.g. "Tier A is Certified" naming the "Tier A" row directly).
    A structured bullet/list row's own key is not always a number — a
    request-processing or certification list keys its rows by a plain word
    or short phrase instead — so this is the same "found a specific,
    single row and checked its own status" grounding as the numeric axis
    checks above, just for a non-numeric key. A clause naming zero or more
    than one record's key is left unanchored (denied), the same as a
    clause with no number at all.
    """
    kind, value = claimed
    key_fn = _literal_status_key if kind == "literal" else _polarity_status_key
    candidates = [
        (marker, record)
        for record in records
        for marker in (record.get("Identifier"), record.get("Range"))
        if marker and marker in clause
    ]
    if not candidates:
        return False
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
    longest_marker, longest_record = candidates[0]
    # A shorter matched marker that is itself a substring of the longest
    # one is not a second, independent record reference — it is only a
    # fragment of the more specific match already found (e.g. "Tier A"
    # inside an explicit combined row's own "Tier A and Tier B"). Only a
    # marker that is genuinely separate from the longest match counts as
    # ambiguity.
    distinct_records = {
        id(record) for marker, record in candidates if marker not in longest_marker
    }
    distinct_records.add(id(longest_record))
    if len(distinct_records) != 1:
        return False
    return key_fn(longest_record.get("Status")) == value


def _answer_has_unverifiable_mixed_status_claim(
    answer: str, records: list[dict[str, str]]
) -> bool:
    """Policy-level guard for mixed-status structured evidence: once a table
    carries more than one distinct Status, no sentence may assert a status
    for a region of it unless that assertion can be *affirmatively*
    checked against the source's own rows.

    This is deliberately not another entry in the comparison-phrase list
    above. ``_answer_synthesizes_unsupported_range`` and
    ``_answer_contradicts_table_records`` each only ever fire once a
    generated sentence matches a *recognized* pattern and that pattern is
    then proven wrong — a sentence using a phrasing neither one recognizes
    is silently let through by both, which is exactly the shape of every
    live escape reported so far: a new paraphrase of the same unsupported
    "global passing rule" that happened not to match any pattern yet on
    file. Rather than adding still another pattern each time a new one
    surfaces, this function inverts the default for this one high-risk
    evidence shape (mixed statuses, no row stating an explicit combined
    rule): a status claim must be *proven grounded*, via a recognized
    phrasing or, failing that, via the plain numbers the sentence itself
    contains, or it is treated as an unsupported synthesis regardless of
    how it is worded. An explicit combined-rule row is not a separate case
    to special-case here — it is simply one more row a claim can be
    grounded against, exactly like any granular one.
    """
    if not answer or not records or not _table_has_mixed_statuses(records):
        return False
    labels = _distinct_status_labels(records)
    if not labels:
        return False
    axis = _record_axis_context(records)
    for clause in _answer_clauses(answer):
        claimed = _sentence_claimed_status(clause, labels)
        if not claimed:
            continue
        if not _clause_status_claim_is_grounded(clause, claimed, records, axis):
            return True
    return False


# --- Query-intent global-classification safety guard ------------------------
#
# The checks above all depend on the retrieved evidence parsing into
# structured rows (``table_records``) — a derived FAQ article can state the
# exact same facts as free prose or an unlabeled bullet list the row parser
# conservatively declines to interpret as a table, leaving nothing for those
# checks to work with. A prior version of this guard tried to close that gap
# by pattern-matching the *generated answer's* wording for a comparison
# shape ("above N", "N and above", ...) and verifying it against the
# evidence phrase by phrase. That approach failed in two directions at once:
# it still missed paraphrases no pattern was written for ("70+", an
# enumerated "1.00 ... and 4.00 are passing"), and it could fire on an
# unrelated, correct procedural answer merely because the model happened to
# generate broad wording ("All students ...") — because activation depended
# on the model's own unpredictable output.
#
# This version activates on something stable instead: the user's own
# question, decided before generation ever runs, never the model's wording.
# A question that explicitly asks for a global classification/range/
# boundary rule ("what score is considered eligible", "which tiers count as
# certified", "what is the passing grade") is structurally different from a
# procedural/service question ("how do I enroll", "what documents do I
# need") — and that structural difference is what gates this guard, not any
# word the model later chooses to use. Once gated, the decision is made
# purely from the evidence's own shape (does it state exactly one
# comparison/range statement, or none/several — see
# ``_evidence_states_single_global_rule``), never from the generated
# answer's specific claim. Enforcement is deliberately blunt: when the
# evidence does not clearly state one rule, no numeral in the generated
# answer is trusted for this question, regardless of what it says or how it
# says it — sidestepping the whack-a-mole of chasing individual paraphrases
# entirely, rather than trying to catch each new one.
_CLASSIFICATION_NOUN = (
    r"range|score|grade|amount|value|tier|tiers|level|levels|category|categories|"
    r"threshold|boundary|cutoff|criterion|criteria|classification|status"
)
_CLASSIFICATION_INTENT_PATTERNS = [
    # "what/which ... <noun> ... is/are considered/classified as/categorized as"
    re.compile(
        rf"\b(?:what|which)\b[^?.!]{{0,40}}\b(?:{_CLASSIFICATION_NOUN})\b[^?.!]{{0,40}}"
        rf"\b(?:is|are)\s+(?:considered|classified\s+as|categorized\s+as)\b",
        re.I,
    ),
    # "what/which ... <noun> ... counts/count/qualifies/qualify as"
    re.compile(
        rf"\b(?:what|which)\b[^?.!]{{0,40}}\b(?:{_CLASSIFICATION_NOUN})\b[^?.!]{{0,40}}"
        rf"\b(?:counts?|qualif(?:y|ies))\s+as\b",
        re.I,
    ),
    # "what/which ... <noun> ... requires/triggers/needs/warrants"
    re.compile(
        rf"\b(?:what|which)\b[^?.!]{{0,40}}\b(?:{_CLASSIFICATION_NOUN})\b[^?.!]{{0,40}}"
        rf"\b(?:requires?|triggers?|needs?|warrants?)\b",
        re.I,
    ),
    # "what is/are the <adjective> <noun>" (covers "what is the passing grade")
    re.compile(
        rf"\bwhat\s+(?:is|are)\s+the\s+\S+\s+(?:{_CLASSIFICATION_NOUN})\b", re.I
    ),
    # "what is/are the <noun>" (no adjective — "what is the boundary")
    re.compile(rf"\bwhat\s+(?:is|are)\s+the\s+(?:{_CLASSIFICATION_NOUN})\b", re.I),
    # minimum/maximum ... <noun>/qualify
    re.compile(
        rf"\b(?:minimum|maximum)\b[^?.!]{{0,40}}\b(?:{_CLASSIFICATION_NOUN}|qualify|qualifies|qualifying)\b",
        re.I,
    ),
    re.compile(r"\bwhat\s+counts\s+as\b", re.I),
    re.compile(r"\bwhat\s+is\s+considered\b", re.I),
    re.compile(r"\bwhat\s+qualifies\s+as\b", re.I),
]


def _is_global_classification_query(question: str) -> bool:
    """Whether the user's own question explicitly asks for a global
    classification/range/boundary rule, as opposed to a procedural/service
    question — decided only from the fixed, pre-generation question text,
    never from anything the model later generates.
    """
    text = question or ""
    return any(pattern.search(text) for pattern in _CLASSIFICATION_INTENT_PATTERNS)


_EVIDENCE_RANGE_STATEMENT_PATTERNS = [
    re.compile(r"\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?"),
    re.compile(r"\bat\s+or\s+above\s+\d+(?:\.\d+)?", re.I),
    re.compile(r"\bat\s+or\s+below\s+\d+(?:\.\d+)?", re.I),
    re.compile(
        r"\b(?:above|over|after|greater\s+than|more\s+than|higher\s+than|exceeds?)\s+\d+(?:\.\d+)?",
        re.I,
    ),
    re.compile(
        r"\b(?:below|under|before|less\s+than|lower\s+than)\s+\d+(?:\.\d+)?", re.I
    ),
    re.compile(r"\d+(?:\.\d+)?\s*(?:and|or)\s*(?:up|higher|above|more|greater)\b", re.I),
    re.compile(r"\d+(?:\.\d+)?\s*(?:and|or)\s*(?:down|lower|below|less)\b", re.I),
    re.compile(r"\bbetween\s+\d+(?:\.\d+)?\s+and\s+\d+(?:\.\d+)?\b", re.I),
    re.compile(r"\bup\s+to\s+\d+(?:\.\d+)?", re.I),
]


def _count_evidence_range_statements(evidence_text: str) -> int:
    """How many distinct comparison/range-shaped statements the raw
    evidence text contains — a purely quantitative count, never an attempt
    to parse or "understand" whatever table/bullet/prose structure the
    evidence happens to use. Zero means no boundary is stated at all;
    exactly one means the evidence states a single, clean global rule;
    two or more means multiple individual bands/categories are listed
    (a grading scale, a fee schedule, a deadline table, ...) with no single
    unifying statement. A source whose evidence states only one such
    statement and nothing else counts as an explicit combined rule; a
    source that states an explicit rule *alongside* its own granular
    breakdown still counts as multiple here and is treated the same as an
    unstated rule — a deliberately conservative simplification, favoring a
    safe generic notice over trying to distinguish "the one true summary
    statement" from "one row among several" by inspecting structure.
    """
    return sum(len(pattern.findall(evidence_text)) for pattern in _EVIDENCE_RANGE_STATEMENT_PATTERNS)


def _evidence_states_single_global_rule(evidence_text: str) -> bool:
    return _count_evidence_range_statements(evidence_text) == 1


_CLASSIFICATION_FALLBACK_NOTICE = (
    "The available source lists individual categories/ranges, but it does "
    "not explicitly state a single overall boundary for that "
    "classification."
)


# A plain word-presence check (no capturing, no boundary extraction, no
# exclusivity tracking) — used only to decide *whether to remove a
# sentence wholesale*, never to determine what it specifically claims or
# to verify it against evidence. A category-coded boundary ("Tier B and
# above") names no number at all, so the digit check alone would miss it.
_COMPARATIVE_WORD_PRESENCE = re.compile(
    r"\b(?:above|below|over|under|between|through|exceeds?|"
    r"at\s+least|at\s+most|and\s+above|and\s+below|or\s+more|or\s+less|"
    r"or\s+higher|or\s+lower|up\s+to|greater\s+than|less\s+than|"
    r"higher\s+than|lower\s+than)\b",
    re.I,
)


def _sentence_makes_numeric_or_comparative_claim(sentence: str) -> bool:
    return bool(re.search(r"\d", sentence)) or bool(_COMPARATIVE_WORD_PRESENCE.search(sentence))


def _apply_conservative_classification_reply(answer: str) -> str:
    """Strip every sentence in ``answer`` that names a number or uses any
    comparative wording at all, and append the deterministic notice. This
    is deliberately blunt rather than trying to identify and remove only
    the specific unsupported phrase: any such sentence, in an answer to a
    global-classification question this guard has already decided the
    evidence does not clearly settle, is untrustworthy regardless of how
    it is worded ("above 69", "70+", an enumerated "1.00 ... and 4.00",
    "Tier B and above"), so none is preserved. A sentence with neither a
    number nor comparative wording (routinely true of unrelated grounded
    content, e.g. a computation-method explanation) is always kept.
    """
    if not answer:
        return _CLASSIFICATION_FALLBACK_NOTICE
    sentences = re.split(r"(?<=[.!?])\s+", answer)
    kept = [
        sentence for sentence in sentences if not _sentence_makes_numeric_or_comparative_claim(sentence)
    ]
    remaining = " ".join(part.strip() for part in kept if part.strip()).strip()
    if remaining:
        return f"{remaining} {_CLASSIFICATION_FALLBACK_NOTICE}"
    return _CLASSIFICATION_FALLBACK_NOTICE


def _table_records_evidence_answer(records: list[dict[str, str]]) -> str:
    """Student-facing summary that only restates table records from evidence."""
    lines = [
        "The retrieved table lists these records. Status labels apply only to "
        "the identifier and range on the same row:",
        "",
    ]
    for record in records:
        ident = record.get("Identifier") or ""
        range_text = record.get("Range") or ""
        status = record.get("Status") or ""
        parts = [part for part in (ident, range_text, status) if part]
        if parts:
            lines.append(f"- {' — '.join(parts)}")
    lines.append(
        "The source does not state a passing threshold in those words. "
        "Do not treat a larger identifier as 'above' or as a passing outcome."
    )
    return "\n".join(lines)


def _fee_usable_for_question(fee: str | None, title: str, normalized_question: str) -> str | None:
    """Accept fees only when they belong to the asked service (not Assessment of Fees noise)."""
    if not fee:
        return None
    title_n = _normalize(title)
    fee_n = _normalize(fee)
    if fee_n in _UNSPECIFIED_FEE_VALUES or not _looks_like_fee_amount(fee):
        return None

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

    confidence = (
        "medium"
        if (
            any(_positive_reasons(chunk) for chunk in relevant)
            or query_matches_retrieval_title(question, relevant)
            or _chunks_overlap_question_tokens(question, relevant)
        )
        else "low"
    )

    answer = format_conversational_fallback(
        question,
        relevant,
        sources,
        confidence=confidence,
    )
    if not answer.strip():
        return OUT_OF_SCOPE_ANSWER, "low", []
    answer = _redact_extraction_artifacts(answer)

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


# --- User-facing citation selection ----------------------------------------
#
# ``selected_context`` (and the ``sources`` built from it above, at the top
# of ``answer_qa_question``) is *retrieval* output: every chunk broad-enough
# retrieval judged worth handing to generation as context. That breadth is
# intentional and must stay — recall matters for generation, and this file
# does not change retrieval, reranking, or how many chunks are retrieved.
#
# But it means the naive `sources=sources` returned to the API is every
# retrieved/selected chunk, regardless of whether the *generated answer*
# actually drew on it. A broad or multi-part question can legitimately
# retrieve several chunks that merely share the question's own wording
# ("validation" pulling in an identity-card "ID Validation" Citizen's
# Charter entry alongside the actual academic-validation Student Handbook
# rule) without any of them contributing evidence to the final answer text.
# Those still-irrelevant chunks must never reach the student as a citation.
#
# The functions below add exactly that missing step — select display
# citations from the chunks that materially support the *answer that was
# actually generated*, not from retrieval membership alone — without
# touching retrieval, reranking, embeddings, or Chroma. A citation is never
# fabricated: every candidate here already went through retrieval (it is a
# member of ``selected_context`` / ``retrieved``), so this only narrows an
# existing, already-retrieved set.
#
# "Materially support" is judged generically (never keyed to this project's
# specific documents/questions): a chunk must share at least two distinctive
# terms/numbers with the answer text, weighted by how *rare* that term is
# across this turn's own retrieved candidates. A term nearly every candidate
# shares (typically the query's own vocabulary, e.g. "validation" here) is
# thereby automatically discounted, while terms concentrated in the answer's
# actual supporting evidence (e.g. "degree", "equivalent", "50", "graduation")
# dominate the score. This generalizes across topics because the weighting is
# recomputed per question from that question's own candidate pool — nothing
# about "validation", "50%", or any other project-specific term is hardcoded.

_SUPPORT_MIN_SIGNALS = 2
"""Minimum shared distinctive word/number tokens before a chunk is even
considered supporting evidence. A single shared term — however rare — is
keyword overlap, not material support (see module note above)."""

_SUPPORT_ABS_FLOOR = 1.5
"""Minimum weighted support score, independent of any other candidate's
score, below which nothing is treated as supporting evidence at all. Guards
the no-support case: if even the best-matching retrieved chunk barely
overlaps the answer, no citation is shown rather than attaching a weak one."""

_SUPPORT_REL_FLOOR = 0.45
"""Within one claim, a chunk must reach at least this fraction of that
claim's strongest supporting score to also be displayed. Applied per claim,
not across the whole answer: a source that materially supports a different
claim is not dropped merely because another claim's source scored higher.
A straggler on the *same* claim, far weaker than that claim's best evidence,
is still dropped."""

_NUMBER_TOKEN_WEIGHT = 2.0
"""A shared number (a percentage, a day count, a grade-range boundary...) is
unusually specific evidence, so it is weighted above an average word term."""

_NUMBER_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?%?")


def _grounding_tokens(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """Distinctive word tokens and standalone numbers used for citation grounding."""
    normalized = _normalize(text or "")
    return frozenset(_meaningful_tokens(normalized)), frozenset(_NUMBER_TOKEN_RE.findall(normalized))


def _citation_support_score(
    answer_words: frozenset[str],
    answer_numbers: frozenset[str],
    chunk_words: frozenset[str],
    chunk_numbers: frozenset[str],
    idf: dict[str, float],
) -> float:
    """How strongly one chunk's own wording supports the answer's wording.

    Returns 0.0 (never a "weak but nonzero" score) when fewer than
    ``_SUPPORT_MIN_SIGNALS`` distinctive terms are shared — keyword overlap
    alone is explicitly not sufficient evidence.
    """
    shared_words = answer_words & chunk_words
    shared_numbers = answer_numbers & chunk_numbers
    if (len(shared_words) + len(shared_numbers)) < _SUPPORT_MIN_SIGNALS:
        return 0.0
    word_score = sum(idf.get(token, 1.0) for token in shared_words)
    number_score = len(shared_numbers) * _NUMBER_TOKEN_WEIGHT
    return word_score + number_score


_CLAIM_SPLIT_RE = re.compile(r"[.!;?\n]+")


def _answer_claims(answer: str) -> list[str]:
    """Split an answer into claim-sized spans for citation scoring.

    A global relative floor compares every chunk to the single strongest
    overlap with the whole answer. That drops a source that clearly supports
    a different, shorter claim whenever another claim overlaps much more.
    Sentence and clause boundaries are the smallest stable split that does
    not hardcode topics. Fragments too short to be evidence are ignored;
    the full answer is always scored separately so a single-claim reply
    behaves as before.
    """
    claims: list[str] = []
    for part in _CLAIM_SPLIT_RE.split(answer or ""):
        claim = part.strip()
        if not claim or claim == (answer or "").strip():
            continue
        words, numbers = _grounding_tokens(claim)
        if len(words) + len(numbers) < _SUPPORT_MIN_SIGNALS:
            continue
        claims.append(claim)
    return claims


def _select_supporting_context(
    candidates: list[RetrievedChunk],
    answer: str,
    *,
    debug_sink: list[dict[str, Any]] | None = None,
) -> list[RetrievedChunk]:
    """Narrow already-retrieved ``candidates`` to what materially supports ``answer``.

    Every chunk this can return was already retrieved and available to the
    answer-generation pipeline — this step only decides which of those
    already-available candidates are grounded enough in the answer text to
    be shown as a citation. It never introduces a chunk that was not a
    candidate, and never fabricates one. Ordered strongest-evidence-first.
    Returns ``[]`` when nothing in ``candidates`` materially supports
    ``answer`` (e.g. a generic/degraded reply) rather than attaching an
    unrelated source just so the UI has something to show.

    Support is claim-wise. The relative floor still drops a same-claim
    straggler, but a chunk that meets the absolute floor for a different
    claim is kept even when its score against the whole answer is below
    ``_SUPPORT_REL_FLOOR`` times the strongest other source.
    """
    if not candidates or not (answer or "").strip():
        return []

    per_chunk: list[tuple[RetrievedChunk, frozenset[str], frozenset[str], str]] = []
    doc_freq: dict[str, int] = {}
    for position, chunk in enumerate(candidates, start=1):
        words, numbers = _grounding_tokens(_chunk_search_text(chunk))
        per_chunk.append((chunk, words, numbers, _raw_citation_id(chunk, position)))
        for token in words:
            doc_freq[token] = doc_freq.get(token, 0) + 1

    # Classic IDF over this turn's own candidate pool: a term nearly every
    # candidate shares (usually the query's own vocabulary) is discounted; a
    # term concentrated in only a few candidates carries real signal.
    total = len(candidates)
    idf = {
        token: math.log((total + 1) / (freq + 1)) + 1.0
        for token, freq in doc_freq.items()
    }

    def _scored(text: str) -> list[tuple[float, RetrievedChunk]]:
        words, numbers = _grounding_tokens(text)
        if not words and not numbers:
            return []
        scored: list[tuple[float, RetrievedChunk]] = []
        for chunk, chunk_words, chunk_numbers, citation_id in per_chunk:
            score = _citation_support_score(words, numbers, chunk_words, chunk_numbers, idf)
            if debug_sink is not None:
                # Observational only: records the same score this loop
                # already computes for every (claim-or-answer, chunk) pair,
                # purely for offline diagnosis. Never read back by this
                # function and never influences `scored`/selection below —
                # this append happens unconditionally, before the `score > 0`
                # branch, and `scored`/`score` are never mutated here.
                shared_words = words & chunk_words
                shared_numbers = numbers & chunk_numbers
                debug_sink.append({
                    "claim_text": text,
                    # `chunk_id` (the existing merge key) is kept as-is,
                    # unrenamed -- `citation_id` is a distinct, additional
                    # field using the same canonical identity semantics as
                    # displayed sources (see `_raw_citation_id`), not a
                    # replacement for it.
                    "chunk_id": _chunk_merge_key(chunk),
                    "citation_id": citation_id,
                    "shared_words": sorted(shared_words),
                    "shared_numbers": sorted(shared_numbers),
                    "score": score,
                    "min_signals_met": (len(shared_words) + len(shared_numbers)) >= _SUPPORT_MIN_SIGNALS,
                    "abs_floor_met": score >= _SUPPORT_ABS_FLOOR,
                })
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored

    def _above_floor(scored: list[tuple[float, RetrievedChunk]]) -> list[tuple[float, RetrievedChunk]]:
        if not scored:
            return []
        top_score = scored[0][0]
        if top_score < _SUPPORT_ABS_FLOOR:
            return []
        threshold = max(_SUPPORT_ABS_FLOOR, top_score * _SUPPORT_REL_FLOOR)
        return [(score, chunk) for score, chunk in scored if score >= threshold]

    best: dict[int, tuple[float, RetrievedChunk]] = {}

    def _consider(pairs: list[tuple[float, RetrievedChunk]]) -> None:
        for score, chunk in pairs:
            key = id(chunk)
            previous = best.get(key)
            if previous is None or score > previous[0]:
                best[key] = (score, chunk)

    # Full-answer pass preserves single-claim behavior, including the
    # relative floor against the strongest overall overlap.
    _consider(_above_floor(_scored(answer)))
    # Claim pass keeps a weaker source that is the (or a) material support
    # for a different claim, which the global relative floor would drop.
    for claim in _answer_claims(answer):
        _consider(_above_floor(_scored(claim)))

    if not best:
        return []
    ordered = sorted(best.values(), key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in ordered]


def _citation_status_after_sources(async_verification_sink: dict[str, Any] | None) -> str | None:
    """The QAResult.citation_status matching what ``_display_sources_for_answer``
    just did with ``async_verification_sink`` (called AFTER that, relying on
    the sink having already been populated in-place by this same call site).
    None for every mode except "async_shadow"/"async_llm"."""
    mode = (settings.citation_verification_mode or "lexical").strip().lower()
    if mode not in ("async_shadow", "async_llm"):
        return None
    return "verifying" if async_verification_sink else "verification_unavailable"


def _display_sources_for_answer(
    candidates: list[RetrievedChunk],
    answer: str,
    *,
    merge_articles: bool = False,
    evidence_text: str | None = None,
    debug_sink: list[dict[str, Any]] | None = None,
    citation_v2_sink: dict[str, Any] | None = None,
    async_verification_sink: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the user-facing ``sources``/``citations`` list for ``answer``.

    Unlike ``_sources_from_chunks(selected_context, ...)`` (every retrieved
    chunk), this returns only chunks that materially support the answer,
    deduplicated and ordered strongest-first by ``_sources_from_chunks``'s
    existing (unchanged) formatting/dedup logic.

    ``evidence_text``, when set, is the pre-rewrite generated answer. A
    presentation template can erase the wording that overlapped the source;
    V1's lexical selector is scored against that evidence instead of the
    template. Candidates are still only already-retrieved chunks.

    ``settings.citation_verification_mode`` controls whether Citation V2
    (semantic, claim-level verification -- see
    ``app.services.qa.citation_verification``) participates:

    - "lexical" (default): V1 only, unchanged -- V2 is not even imported.
    - "shadow": V1 still decides what is displayed; V2 also runs (against
      the FINAL ``answer`` text, never ``evidence_text``) purely for
      diagnostics, recorded into ``citation_v2_sink`` when provided.
    - "llm": V2 decides what is displayed. Any V2 failure (timeout,
      malformed output, hallucinated id, etc.) displays zero citations --
      it never falls back to V1's lexical selection.
    - "async_shadow" / "async_llm": same decision rules as "shadow" / "llm"
      respectively, but the verifier is never called inline here. The exact
      inputs a synchronous call would have used (extracted claims implied by
      ``answer``, and the frozen candidate snapshot) are handed to the
      caller via ``async_verification_sink`` so it can be scheduled outside
      this request's critical path -- see
      ``app.services.qa.citation_verification_jobs``. "async_llm" returns
      zero citations immediately and always -- V1's guesses are never shown
      even transiently while verification is pending.
    """
    grounding = (evidence_text or "").strip() or answer
    v1_supporting = _select_supporting_context(candidates, grounding, debug_sink=debug_sink)

    mode = (settings.citation_verification_mode or "lexical").strip().lower()
    if mode not in ("lexical", "shadow", "llm", "async_shadow", "async_llm"):
        mode = "lexical"
    if mode == "lexical":
        return _sources_from_chunks(v1_supporting, merge_articles=merge_articles)

    from app.services.qa.citation_verification import CandidateEvidence, extract_claims, verify_citations

    v2_candidates = [
        CandidateEvidence(
            citation_id=_raw_citation_id(chunk, index),
            title=str(chunk.title or (chunk.metadata or {}).get("title") or ""),
            source_section=_source_section(chunk.metadata or {}) or None,
            source_filename=chunk.source_filename,
            text=chunk.text or "",
        )
        for index, chunk in enumerate(candidates, start=1)
    ]

    if mode in ("async_shadow", "async_llm"):
        claims = extract_claims(answer)
        if async_verification_sink is not None and claims and v2_candidates:
            async_verification_sink.update(
                {"mode": mode, "answer": answer, "candidates": v2_candidates}
            )
        if mode == "async_shadow":
            return _sources_from_chunks(v1_supporting, merge_articles=merge_articles)
        return []

    outcome = verify_citations(answer=answer, candidates=v2_candidates, mode=mode)

    if citation_v2_sink is not None:
        citation_v2_sink.update(
            {
                "mode": outcome.mode,
                "claims": [{"claim_id": c.claim_id, "text": c.text} for c in outcome.claims],
                "candidate_citation_ids": outcome.candidate_citation_ids,
                "verifier_invoked": outcome.verifier_invoked,
                "verifier_succeeded": outcome.verifier_succeeded,
                "failure_reason": outcome.failure_reason,
                "per_claim_verified_ids": outcome.per_claim_verified_ids,
                "verified_citation_ids": outcome.verified_citation_ids,
                "v1_displayed_citation_ids": [
                    _raw_citation_id(chunk, index)
                    for index, chunk in enumerate(v1_supporting, start=1)
                ],
                "latency_ms": outcome.latency_ms,
                "usage": outcome.usage,
            }
        )

    if mode == "shadow":
        return _sources_from_chunks(v1_supporting, merge_articles=merge_articles)

    # mode == "llm": display ONLY V2-verified citations. A failed/empty
    # outcome yields verified_citation_ids == [] -> zero citations, by
    # construction -- never a fallback to v1_supporting.
    id_to_chunk = {
        _raw_citation_id(chunk, index): chunk for index, chunk in enumerate(candidates, start=1)
    }
    verified_chunks = [
        id_to_chunk[cid] for cid in outcome.verified_citation_ids if cid in id_to_chunk
    ]
    return _sources_from_chunks(verified_chunks, merge_articles=merge_articles)


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
                "citation_id": _raw_citation_id(chunk, rank),
                # True only when metadata["chunk_id"] was actually stamped
                # on this chunk -- False means citation_id fell back to
                # `document_id::chunk_index`, which is not guaranteed
                # stable/unique across re-ingests or when chunk_index==0
                # collides with _raw_citation_id's own `chunk_index or
                # index` fallback substitution. Purely diagnostic -- never
                # read by production selection/formatting, only by capture
                # tooling deciding whether a candidate's identity is solid
                # enough for quantitative gold-label evaluation.
                "citation_id_stamped": bool(metadata.get("chunk_id")),
                # Raw passthrough only -- never substitute a missing/None/
                # malformed value with "student" or any other default here.
                # Production retrieval filtering (chroma_where_for_audience /
                # filter_chunks_for_audience) already ran before this debug
                # row is built; this field is purely observational and must
                # not normalize the value, so a capture script can see
                # exactly what was (or was not) on the chunk's own metadata.
                "audience": metadata.get("audience"),
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
    if _taxonomy_family_is(domain, "Programs & Curricular Offerings"):
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
    cleaned = _redact_extraction_artifacts(re.sub(r"\s+", " ", (text or "").strip()))
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
    # Relative-to-leader window only. The companion `score >= 0.55` floor was a
    # cosine-scale absolute quality test and is unreachable on the post-rerank
    # ranking score this reads, so dropping it changes nothing; keeping it would
    # only imply a quality guarantee that is not there.
    if top_score - score <= _near_best_score_window(top_score):
        reasons.append("keep_close_to_rank_1")
    if query_domain and _chunk_matches_domain(chunk, query_domain):
        reasons.append(f"keep_same_domain:{query_domain}")
    if _title_path_matches_query_intent(chunk, normalized_query):
        reasons.append("keep_title_path_intent_match")
    if _positive_reasons(chunk) and not _has_strong_penalty(chunk):
        reasons.append("keep_positive_boost_without_strong_penalty")
    if broad_query and query_domain and _broad_chunk_matches_domain(chunk, query_domain):
        reasons.append(f"keep_broad_domain:{query_domain}")
    if broad_query and top_score - score <= 0.22 and not _looks_like_noise(chunk):
        reasons.append("keep_broad_relevant_score_window")
    if _has_strong_penalty(chunk):
        reasons.append("drop_strong_penalty")
    if broad_query and _looks_like_noise(chunk):
        reasons.append("drop_broad_noise")
    return reasons


def _near_best_score_window(top_score: float) -> float:
    """How close a later chunk must be to rank-1 to count as the same cluster.

    On the cosine scale (≤1) this is the original 0.08 absolute window. After
    reranking, scores run ~1.0–4.7, so the same 0.08 would split a flat cluster
    of correct sections (measured 2.17–2.24). Use 15% of the leader there.
    """
    if top_score > 1.0:
        return max(0.12, 0.15 * float(top_score))
    return 0.08


def _chunk_score(chunk: RetrievedChunk) -> float:
    return float(chunk.rerank_score)


def _positive_reasons(chunk: RetrievedChunk) -> list[str]:
    """Rerank reasons that say this chunk is about the question's subject.

    Provenance/citation-hygiene boosts are excluded: they fire on every
    well-formed chunk, so counting them made every result set look aligned.
    """
    return [
        reason
        for reason in (chunk.rerank_reasons or [])
        if (reason.startswith("boost_") or reason.endswith("_match") or reason.endswith("_policy"))
        and reason not in NON_TOPICAL_RERANK_REASONS
    ]


def _has_strong_penalty(chunk: RetrievedChunk) -> bool:
    """True when the reranker judged this chunk to be off-domain noise.

    ``penalty_unrelated_procedure`` is deliberately absent: it fires whenever a
    non-how-to question meets a chunk containing procedural wording, which is
    every Citizen's Charter service card. For "How much is the fee for a
    Transcript of Records?" it lands on five of the top seven chunks including
    the correct TOR service card at rank 1, so treating it as noise pushed
    correctly-answered fee questions into the clarification template. It remains
    a ranking penalty inside the reranker.
    """
    strong_markers = (
        "penalty_unrequested_",
        "penalty_disciplinary",
        "penalty_awards",
        "penalty_retention_awards",
        "penalty_sample_document",
    )
    return any(reason.startswith(strong_markers) for reason in (chunk.rerank_reasons or []))


def _detected_query_domain(normalized_query: str) -> str | None:
    """Return the taxonomy category for this question (same labels as chunk metadata).

    Uses ``classify_question`` / ``knowledge_base_categories.json`` — the same
    labels written onto Chroma chunks at ingest — instead of a parallel keyword
    table in this module. Category (not subcategory) is the domain family used
    for context keep/confidence, matching the coarse grain of the old maps.
    """
    category, subcategory = _query_taxonomy_labels(normalized_query)
    return category or subcategory


def _query_taxonomy_labels(question: str) -> tuple[str | None, str | None]:
    """The query's taxonomy domain, gated to only what's trustworthy enough
    to steer context selection -- this is the sole caller of
    ``classify_question`` for that purpose (via ``_detected_query_domain``);
    any other caller that wants the raw diagnostic classification (including
    its confidence/method) should call ``classify_question`` directly, which
    this gate never touches.

    Below ``LOW_CONFIDENCE_THRESHOLD`` -- the same boundary
    ``classify_chunk`` already uses to decide a classification is reliable
    enough to use without further (LLM) verification -- a low-confidence
    guess (typically the embedding-similarity fallback firing on a question
    with no real rule-based keyword match) must not be treated as an
    authoritative domain. Returning ``None, None`` here is the existing
    "no domain" contract ``_detected_query_domain`` already handles for the
    default/unclassified case; an uncertain guess is treated the same way
    as no classification at all, never coerced into a specific domain.
    """
    result = classify_question(question)
    if (
        result.category == DEFAULT_CATEGORY
        and result.subcategory == DEFAULT_SUBCATEGORY
    ):
        return None, None
    if result.confidence < LOW_CONFIDENCE_THRESHOLD:
        return None, None
    category = str(result.category or "").strip() or None
    subcategory = str(result.subcategory or "").strip() or None
    if subcategory == DEFAULT_SUBCATEGORY:
        subcategory = None
    return category, subcategory


def _chunk_taxonomy_labels(chunk: RetrievedChunk) -> tuple[str, str]:
    metadata = chunk.metadata or {}
    category = str(metadata.get("category") or "").strip()
    subcategory = str(metadata.get("subcategory") or "").strip()
    return category, subcategory


def _chunks_carry_taxonomy(chunks: Sequence[RetrievedChunk] | list[RetrievedChunk]) -> bool:
    return any(any(_chunk_taxonomy_labels(chunk)) for chunk in chunks)


def _chunk_matches_domain(chunk: RetrievedChunk, domain: str | None) -> bool:
    """True when the chunk's ingested category/subcategory matches the query label."""
    if not domain:
        return False
    category, subcategory = _chunk_taxonomy_labels(chunk)
    if not category and not subcategory:
        return False
    needle = _normalize(domain)
    return _normalize(subcategory) == needle or _normalize(category) == needle


def _soft_domain_text_match(chunk: RetrievedChunk, domain: str) -> bool:
    """Fallback when fixtures omit taxonomy metadata: label (or a phrase from it) in text."""
    hay = _chunk_search_text(chunk)
    needle = _normalize(domain)
    if needle and needle in hay:
        return True
    parent = _parent_category_for_label(domain)
    parent_needle = _normalize(parent or "")
    if parent_needle and parent_needle in hay:
        return True
    # "Programs & Curricular Offerings" should still match path text that only
    # says "Curricular Offerings" — use trailing multi-word phrases from the label.
    parts = [part for part in re.split(r"[&/]|\s+", domain) if part.strip()]
    for index in range(len(parts)):
        phrase = _normalize(" ".join(parts[index:]))
        if len(phrase) >= 8 and phrase in hay:
            return True
    return False


def _broad_chunk_matches_domain(chunk: RetrievedChunk, domain: str | None) -> bool:
    """Broader keep signal: chunk shares the query's taxonomy category family."""
    if not domain:
        return False
    category, subcategory = _chunk_taxonomy_labels(chunk)
    if not category and not subcategory:
        return False
    needle = _normalize(domain)
    if _normalize(subcategory) == needle or _normalize(category) == needle:
        return True
    parent = _parent_category_for_label(domain)
    return bool(parent and _normalize(category) == _normalize(parent))


def _parent_category_for_label(label: str) -> str | None:
    """Look up the category that owns this taxonomy label (category or subcategory)."""
    from app.services.knowledge_taxonomy import load_taxonomy

    needle = _normalize(label)
    if not needle:
        return None
    for category in load_taxonomy():
        if _normalize(category.name) == needle:
            return category.name
        for subcategory in category.subcategories:
            if _normalize(subcategory.name) == needle:
                return category.name
    return None


def _taxonomy_family_is(domain: str | None, category_name: str) -> bool:
    if not domain:
        return False
    parent = _parent_category_for_label(domain) or domain
    return _normalize(parent) == _normalize(category_name)

def _title_path_matches_query_intent(chunk: RetrievedChunk, normalized_query: str) -> bool:
    title_path = _normalize(f"{_display_title(chunk)} {_hierarchy_path(chunk.metadata or {})}")
    query_tokens = _meaningful_tokens(normalized_query)
    if not query_tokens:
        return False
    matches = [token for token in query_tokens if token in title_path]
    # One shared token is enough only when it is distinctive. The previous
    # `_chunk_score(chunk) >= 0.72` companion test read the post-rerank ranking
    # score, which clears 0.72 for essentially every chunk in production, so a
    # single generic word such as "document" was accepted as intent alignment.
    return len(matches) >= 2 or any(token not in _GENERIC_TOPIC_TOKENS for token in matches)


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
        if not value:
            continue
        if key == "total_fees":
            if _documented_zero_fee(value):
                lines.append(f"{label}: None")
            elif _looks_like_fee_amount(value):
                lines.append(f"{label}: {value}")
            continue
        if value.lower() not in {"none", "null", "n/a", "[needs review]"}:
            lines.append(f"{label}: {_redact_extraction_artifacts(value)}")
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
            lines.append(f"{label}: {_redact_extraction_artifacts(text[:1200])}")
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
    if _taxonomy_family_is(domain, "Programs & Curricular Offerings"):
        college = _first_matching_path_part(metadata, "college")
        if college:
            return f"college:{_normalize(college)}"
    if (
        _taxonomy_family_is(domain, "Student Services")
        or _taxonomy_family_is(domain, "Scholarships & Financial Policies")
        or _taxonomy_family_is(domain, "Academic Policies")
    ):
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

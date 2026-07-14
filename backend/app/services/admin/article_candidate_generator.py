from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict
from typing import Any

from app.services.admin.article_planner import (
    build_coverage_report,
    is_generic_article_title,
    is_numeric_only_title,
    plan_articles_from_units,
    resolve_student_facing_title,
    stable_preview_id,
)
from app.services.admin.knowledge_base_pipeline import extract_document_preview
from app.services.article_content_formatter import (
    extract_embedded_article_metadata,
    format_article_content,
)
from app.services.article_text import (
    build_article_summary,
    clean_article_content_for_display,
    is_generic_only_summary,
    summary_has_foreign_topic_terms,
    _trim_summary_length,
)
from app.services.citizen_charter_services import (
    CHARTER_BLOCKING_REVIEW_FLAGS,
    CHARTER_NON_BLOCKING_REVIEW_FLAGS,
    build_charter_article_body,
    build_charter_generation_report,
    charter_blocks_publish,
    charter_blocking_review_flags,
    charter_body_has_required_sections,
    charter_v2_service_to_fields,
    classify_charter_audience,
    classify_charter_candidate_bucket,
    collect_charter_parser_text,
    decide_charter_bucket,
    decide_charter_bucket_for_v2,
    has_mixed_charter_services,
    is_artifact_charter_title,
    is_charter_field_label_or_fragment_title,
    is_charter_or_service_process_unit,
    is_noise_service_title,
    is_valid_charter_service_block,
    looks_like_truncated_charter_title,
    map_charter_category,
    resolve_preview_document_profile,
    score_charter_service_completeness,
    should_reject_charter_article_candidate,
)
from app.services.knowledge_taxonomy import classify_chunk, load_taxonomy
from app.services.office_matcher import match_office_from_text
from app.db.session import get_session_factory
from app.models.db_models import PublishedArticle

logger = logging.getLogger(__name__)


def _is_unpublishable_title(title: str | None) -> bool:
    normalized = re.sub(r"\s+", " ", str(title or "").strip())
    if not normalized:
        return True
    return is_generic_article_title(normalized) or is_numeric_only_title(normalized)


def _safe_json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        try:
            return json.dumps(str(value))
        except Exception:
            return None


def _candidate_from_unit(unit: dict, filename: str | None = None) -> dict:
    metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
    title = (unit.get("title") or metadata.get("section_heading") or "").strip()
    title = re.sub(r"\s+", " ", title)[:255]
    content = clean_article_content_for_display(str(unit.get("content") or "").strip())
    source_section = unit.get("hierarchy_path") or metadata.get("section_heading") or None
    # Prefer high-confidence office_aliases matches for publish labels.
    # For Citizen's Charter, keep extracted Office/Division so article bodies are
    # not rebuilt as "Not specified" when aliases have no match.
    office = unit.get("office") if unit.get("office_match_confidence") is not None else None
    parser_kind = str(
        metadata.get("parser_document_type") or unit.get("parser_document_type") or ""
    ).strip().lower()
    is_charter = parser_kind in {"citizen_charter", "service_process"} or str(
        metadata.get("source_type") or unit.get("source_type") or ""
    ) in {"Citizen's Charter", "Service Process"}
    extracted_office = (
        metadata.get("extracted_office")
        or metadata.get("office_division")
        or metadata.get("office")
        or unit.get("office")
    )
    if not office and is_charter:
        office = extracted_office
    document_type = metadata.get("document_type") or unit.get("document_type") or None
    summary = build_article_summary(
        content,
        title=title or None,
        document_type=document_type,
    )
    chunk_index = unit.get("unit_index")

    # Try to read JSON encoded metadata if present
    def _load_json_field(key: str):
        v = metadata.get(key)
        if not v:
            return None
        try:
            return json.loads(v) if isinstance(v, str) else v
        except Exception:
            return None

    requirements = _load_json_field("extracted_requirements")
    steps = _load_json_field("extracted_steps")
    options_or_services = _load_json_field("form_options") or _load_json_field("options_or_services")
    related_articles = _load_json_field("related_services")

    return {
        "title": title or "Untitled",
        "content": content,
        "summary": summary,
        "source_filename": filename,
        "source_section": source_section,
        "office": office,
        "extracted_office": extracted_office,
        "document_type": document_type,
        "requirements": requirements,
        "steps": steps,
        "options_or_services": options_or_services,
        "related_articles": related_articles,
        "chunk_index": chunk_index,
        "parser_document_type": metadata.get("parser_document_type") or unit.get("parser_document_type"),
        "source_type": metadata.get("source_type") or unit.get("source_type"),
        "document_profile": metadata.get("document_profile") or unit.get("document_profile"),
        "parser_used": metadata.get("parser_used") or unit.get("parser_used"),
        "formatter_used": metadata.get("formatter_used") or unit.get("formatter_used"),
        "charter_audience": metadata.get("charter_audience")
        or unit.get("charter_audience"),
        "suggested_category": metadata.get("suggested_category")
        or unit.get("suggested_category"),
        "charter_candidate_bucket": metadata.get("charter_candidate_bucket")
        or unit.get("charter_candidate_bucket"),
        "charter_completeness": metadata.get("charter_completeness")
        or unit.get("charter_completeness"),
        "charter_parts_merged": metadata.get("charter_parts_merged")
        or unit.get("charter_parts_merged"),
        "who_may_avail": metadata.get("who_may_avail") or unit.get("who_may_avail"),
        "classification": metadata.get("classification") or unit.get("classification"),
        "total_processing_time": metadata.get("total_processing_time")
        or unit.get("total_processing_time"),
        "total_fees": metadata.get("total_fees") or unit.get("total_fees"),
        "parser_debug": metadata.get("parser_debug") or unit.get("parser_debug"),
        "needs_review_hint": unit.get("needs_review_hint") or metadata.get("needs_review_hint"),
        "extraction_quality": metadata.get("extraction_quality") or unit.get("extraction_quality"),
        "extraction_quality_reason": metadata.get("extraction_quality_reason")
        or unit.get("extraction_quality_reason"),
        "parser_strategy_used": metadata.get("parser_strategy_used") or unit.get("parser_strategy_used"),
        "table_extraction_method": metadata.get("table_extraction_method")
        or unit.get("table_extraction_method"),
        "page_start": metadata.get("page_start") or unit.get("page_start"),
        "page_end": metadata.get("page_end") or unit.get("page_end"),
        "original_bucket": metadata.get("original_bucket") or unit.get("original_bucket"),
        "repaired_bucket": metadata.get("repaired_bucket") or unit.get("repaired_bucket"),
        "rescue_attempted": metadata.get("rescue_attempted", unit.get("rescue_attempted")),
        "rescue_successful": metadata.get("rescue_successful", unit.get("rescue_successful")),
        "rescue_reasons": metadata.get("rescue_reasons") or unit.get("rescue_reasons") or [],
        "repair_actions_applied": metadata.get("repair_actions_applied")
        or unit.get("repair_actions_applied")
        or [],
        "remaining_blockers": metadata.get("remaining_blockers")
        or unit.get("remaining_blockers")
        or [],
        "semantic_validation_passed": metadata.get("semantic_validation_passed")
        or unit.get("semantic_validation_passed"),
        "needs_review_reasons": metadata.get("needs_review_reasons")
        or unit.get("needs_review_reasons")
        or [],
        "metadata": metadata,
    }


def _candidate_classification_text(candidate: dict) -> str:
    """Ground taxonomy classification in title, summary, and a brief content excerpt."""
    title = (candidate.get("title") or "").strip()
    summary = (candidate.get("summary") or "").strip()
    content = clean_article_content_for_display(candidate.get("content") or "")
    if content:
        excerpt = _trim_summary_length(content, max_chars=240)
        return f"{title}\n{summary}\n{excerpt}".strip()
    if summary:
        return f"{title}\n{summary}".strip()
    return title


def _looks_like_appendix_only_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if not normalized:
        return False
    return bool(re.fullmatch(r"(?i)appendix\s+(?:[a-z]|[ivxlc]+|\d+)$", normalized))


def _looks_like_action_step_fragment(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if not normalized:
        return False
    if re.fullmatch(
        r"(?i)(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)\s+(?:action|step|phase|stage)$",
        normalized,
    ):
        return True
    return bool(re.fullmatch(r"(?i)(?:action|step|phase|stage)\s+\d+$", normalized))


def _looks_like_table_row_fragment(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if not normalized:
        return False
    if is_charter_field_label_or_fragment_title(normalized):
        return True
    if re.search(r"\w/\w", normalized):
        return True
    words = normalized.split()
    if words and words[0][:1].islower():
        return True
    if len(words) >= 7 and re.search(
        r"\b(?:monitor|evaluate|accomplish|submit|complete|ensure|perform|conduct|implement|prepare|secure|obtain|file|fill|using)\b",
        normalized,
        flags=re.I,
    ):
        return True
    return False


def _canonical_final_bucket(item: dict) -> str:
    """Resolve one display/publish bucket. Priority: final → charter → planner → fallback."""
    for key in ("final_bucket", "charter_candidate_bucket", "planner_bucket"):
        value = str(item.get(key) or "").strip().lower()
        if value in {
            "recommended",
            "needs_review",
            "low_quality",
            "rag_only",
            "consolidated_parent",
        }:
            return value
    if bool(item.get("needs_review")):
        return "needs_review"
    if bool(item.get("consolidated_parent")):
        return "consolidated_parent"
    return "needs_review"


def _apply_final_bucket(
    item: dict,
    bucket: str,
    *,
    raw_bucket: str | None = None,
    corrected: bool = False,
) -> None:
    """Stamp canonical bucket fields used by UI grouping and publish safety."""
    previous = str(item.get("final_bucket") or item.get("planner_bucket") or "").strip().lower()
    item["raw_bucket"] = raw_bucket or item.get("raw_bucket") or previous or "pending"
    item["final_bucket"] = bucket
    item["planner_bucket"] = bucket
    item["ui_group_bucket"] = bucket
    publish_allowed = bucket in {"recommended", "consolidated_parent"}
    # Low Quality may be saved as a manual review draft only (never published from this bucket).
    save_draft_allowed = bucket in {
        "recommended",
        "consolidated_parent",
        "needs_review",
        "low_quality",
    }
    reasons = [str(r) for r in (item.get("review_reason") or [])]
    blocking = list(
        item.get("blocking_review_flags")
        or charter_blocking_review_flags(reasons)
    )
    if any(
        flag in reasons or flag in blocking
        for flag in ("incomplete_structured_fields", "table_row_fragment")
    ):
        publish_allowed = False
    item["publish_allowed"] = publish_allowed
    item["save_draft_allowed"] = save_draft_allowed
    item["blocking_review_flags"] = blocking
    charter_bucket = str(item.get("charter_candidate_bucket") or "").strip().lower()
    consistent = True
    if charter_bucket and charter_bucket != bucket and _is_charter_preview(item):
        # Charter routing wins; mismatch means UI/planner was wrong.
        consistent = False
    item["bucket_consistency_check"] = "ok" if consistent and not corrected else "corrected"
    if corrected or (previous and previous not in {"", "pending"} and previous != bucket):
        item["_bucket_mismatch_corrected"] = True
    item["needs_review"] = bucket == "needs_review"
    _preserve_published_match_flags(item)


def _title_is_sentence(title: str) -> bool:
    if not title:
        return False
    normalized = re.sub(r"\s+", " ", title).strip()
    words = normalized.split()
    if len(words) < 3:
        return False
    if normalized.endswith((".", ";", ":")):
        return True
    if len(words) > 8:
        return True
    if title[0].islower():
        return True
    if re.search(r"\b(is|are|was|were|has|have|do|does|did|will|shall|should|must|can|may|apply|provide|assist|make|conduct|publicize|monitor|evaluate|accomplish|using)\b", normalized, flags=re.I):
        return True
    return False


def _ends_with_hanging_word(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if not normalized:
        return False
    words = normalized.split()
    if not words:
        return False
    last_word = re.sub(r"[^A-Za-z]+$", "", words[-1]).lower()
    return last_word in {"on", "to", "with", "from", "by", "and", "or", "provide", "provided", "provides", "concerned"}


def _looks_like_person_or_position_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if not normalized or "," not in normalized:
        return False
    prefix, suffix = [part.strip() for part in normalized.split(",", 1)]
    prefix_words = prefix.split()
    suffix_lower = suffix.lower()
    name_like_prefix = bool(
        2 <= len(prefix_words) <= 4
        and all(re.fullmatch(r"[A-Z][a-zA-Z'.-]*|[A-Z]\.", word) for word in prefix_words)
    )
    position_like_suffix = bool(
        re.search(r"\b(director|coordinator|registrar|dean|officer|head|chair|chief|instructor|faculty|adviser|advisor|manager|supervisor|president)\b", suffix_lower)
        or re.search(r"\b(admission|registrarship|student affairs|guidance|finance|cashier|hr|human resources|ict)\b", suffix_lower)
    )
    return bool(name_like_prefix and position_like_suffix)


def _looks_incomplete_ocr_fragment(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if not normalized:
        return True
    words = normalized.split()
    if len(words) <= 1:
        return True
    if re.search(r"\bEvery student accumulat$", normalized, flags=re.I):
        return True
    if _ends_with_hanging_word(normalized):
        return True
    if re.search(r"\b(?:and|or|to|with|from|by|of|for|in|on)$", normalized, flags=re.I):
        return True
    if len(words) >= 3 and re.search(r"\b(?:the|a|an)$", normalized, flags=re.I):
        return True
    return False


def _heading_like_score(title: str) -> float:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    words = normalized.split()
    if not normalized:
        return -2.0
    score = 0.0
    if 2 <= len(words) <= 6:
        score += 2.0
    elif len(words) == 1:
        score -= 1.0
    else:
        score -= 0.5
    if all(word[:1].isupper() or word.isupper() for word in words if word):
        score += 1.0
    if _title_is_sentence(normalized):
        score -= 2.0
    if _ends_with_hanging_word(normalized):
        score -= 2.0
    if _looks_like_person_or_position_title(normalized):
        score -= 2.5
    if _looks_incomplete_ocr_fragment(normalized):
        score -= 2.0
    if _looks_like_appendix_only_title(normalized):
        score -= 2.5
    if _looks_like_action_step_fragment(normalized):
        score -= 2.5
    if _looks_like_table_row_fragment(normalized):
        score -= 2.5
    if re.search(r"[,:;]$", normalized):
        score -= 1.0
    return score


def _looks_generic(title: str) -> bool:
    if not title:
        return True
    generic_tokens = ["introduction", "overview", "note", "notes", "content", "section", "page"]
    lower = title.strip().lower()
    if lower in generic_tokens:
        return True
    if len(lower.split()) <= 2 and not any(c.isalpha() for c in lower):
        return True
    if re.fullmatch(r"[0-9ivxivxlcdm\-]+", lower):
        return True
    return False


def _looks_like_administrative_background_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if not normalized:
        return False
    lower = normalized.lower()
    if re.search(
        r"\b(?:foreword|preface|messages?|greeting|mission|vision|mandate|background|organizational structure|owner information|quality policy|committee|commission|council|officials?)\b",
        lower,
    ):
        return True
    if re.search(r"\b(?:board|regents?)\b", lower):
        return True
    if re.search(r"\b(?:president|chancellor|rector)\b", lower) and re.search(r"\b(?:message|greeting|foreword)\b", lower):
        return True
    return False


def _looks_like_vague_section_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title or "").strip()
    if not normalized:
        return False
    words = normalized.split()
    if len(words) <= 2 and words[0].lower() in {
        "other",
        "general",
        "drug",
        "alcohol",
        "substance",
        "various",
        "miscellaneous",
    }:
        return True
    if len(words) == 2 and words[0].lower() == "general":
        return True
    return False


def _has_irregular_title_casing(title: str) -> bool:
    words = re.sub(r"\s+", " ", title or "").strip().split()
    if len(words) < 3:
        return False
    upper_words = [word for word in words if word.isupper() and len(word) > 2]
    title_words = [word for word in words if word[:1].isupper() and not word.isupper()]
    if len(upper_words) >= 2 and len(title_words) >= 1:
        return True
    inner = words[1:-1] if len(words) > 2 else []
    inner_caps = [word for word in inner if word.isupper() and len(word) > 3]
    return len(inner_caps) >= 2


def _term_in_text(term: str, text: str) -> bool:
    return bool(re.search(rf"\b{re.escape(term)}\b", text, flags=re.I))


def _student_usefulness_score(title: str, category: str | None, doc_type: str) -> float:
    text = f"{title} {category or ''}".lower()
    score = 0.0
    boost_terms = (
        "admission",
        "registration",
        "grading",
        "attendance",
        "academic",
        "student service",
        "guidance",
        "counseling",
        "scholarship",
        "graduation",
        "requirement",
        "form",
        "procedure",
        "enrollment",
        "transcript",
        "leave of absence",
        "deferment",
        "dismissal",
        "uniform",
        "discipline",
        "honorable",
        "counseling process",
        "copy of grades",
        "load",
        "policy",
        "services",
    )
    penalty_terms = (
        "foreword",
        "preface",
        "messages",
        "message",
        "board",
        "regent",
        "committee",
        "mission",
        "vision",
        "president",
        "owner information",
        "quality policy",
        "organizational",
        "background",
        "official",
        "offense",
        "behavior",
    )
    for term in boost_terms:
        if _term_in_text(term, text):
            score += 1.5
    for term in penalty_terms:
        if _term_in_text(term, text):
            score -= 2.0
    if _looks_like_administrative_background_title(title):
        score -= 3.0
    if _looks_like_vague_section_title(title):
        score -= 2.5
    if doc_type in {"requirement", "procedure"}:
        score += 2.0
    return score


def _score_candidate(candidate: dict, unit: dict, classification_confidence: float) -> tuple[float, list[str]]:
    reasons: list[str] = []
    title = (candidate.get("title") or "").strip()
    content = (candidate.get("content") or "").strip()
    title_len = len(title.split())
    content_len = len(content.split())
    metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
    doc_type = str(candidate.get("document_type") or metadata.get("document_type") or "information").strip().lower()

    score = _heading_like_score(title)

    # title signals
    if 2 <= title_len <= 6:
        score += 1.5
    elif title_len == 1:
        score -= 1.0
        reasons.append("title_too_short")
    elif title_len > 6:
        score -= 0.5
        reasons.append("title_too_long")
    if _title_is_sentence(title):
        reasons.append("title_looks_sentence")
        score -= 2.5
    if _ends_with_hanging_word(title):
        reasons.append("title_ends_with_hanging_word")
        score -= 2.5
    if _looks_generic(title):
        reasons.append("title_looks_generic")
        score -= 1.5
    if _looks_like_person_or_position_title(title):
        reasons.append("person_or_position_title")
        score -= 3.0
    if _looks_incomplete_ocr_fragment(title):
        reasons.append("title_incomplete_ocr_fragment")
        score -= 3.0
    if _looks_like_appendix_only_title(title):
        reasons.append("appendix_only_title")
        score -= 3.0
    if _looks_like_action_step_fragment(title):
        reasons.append("action_step_fragment")
        score -= 3.0
    if _looks_like_table_row_fragment(title):
        reasons.append("table_row_fragment")
        score -= 3.0
    if _looks_like_administrative_background_title(title):
        reasons.append("administrative_background_title")
        score -= 3.0
    if _looks_like_vague_section_title(title):
        reasons.append("vague_section_title")
        score -= 2.5
    if _has_irregular_title_casing(title):
        reasons.append("irregular_title_casing")
        score -= 2.5

    # content signals
    if content_len >= 50:
        score += 3.0
    elif content_len >= 20:
        score += 1.0
    elif doc_type not in {"requirement", "procedure"}:
        reasons.append("content_too_short")
        score -= 1.0

    if doc_type == "information":
        has_heading_metadata = bool(
            metadata.get("section")
            or metadata.get("article")
            or metadata.get("chapter")
            or metadata.get("section_heading")
        )
        if title_len <= 2 and content_len < 35 and not has_heading_metadata:
            score -= 2.0
            reasons.append("information_title_weak")
        if _looks_like_person_or_position_title(title) or _looks_incomplete_ocr_fragment(title):
            score -= 1.5

    # heading-derived title preferred
    if metadata.get("section") or metadata.get("article") or metadata.get("chapter") or metadata.get("section_heading"):
        score += 1.0
    elif doc_type not in {"requirement", "procedure"}:
        reasons.append("title_from_body")

    # category confidence
    score += float(classification_confidence or 0.0) * 2.0
    if classification_confidence < 0.45 and doc_type not in {"requirement", "procedure"}:
        reasons.append("low_category_confidence")

    usefulness = _student_usefulness_score(title, None, doc_type)
    score += min(2.0, usefulness * 0.25)
    if usefulness < 0 and doc_type == "information":
        reasons.append("low_student_usefulness")
        score -= 1.5

    # normalize
    quality = max(-8.0, min(12.0, score))
    return quality, reasons


def _merge_small_candidates(candidates: list[dict]) -> list[dict]:
    # group by source_section (hierarchy path) and merge if multiple small candidates
    grouped = defaultdict(list)
    for c in candidates:
        key = c.get("source_section") or c.get("title")[:40]
        grouped[key].append(c)

    merged: list[dict] = []
    for key, items in grouped.items():
        if len(items) > 1 and sum(len((it.get("content") or "").split()) for it in items) < 300:
            # merge into one
            titles = [it.get("title") for it in items if it.get("title")]
            merged_title = titles[0] if titles else (key or "Untitled")
            merged_content = "\n\n".join(
                clean_article_content_for_display(it.get("content") or "") for it in items
            )
            merged_summary = build_article_summary(
                merged_content,
                title=merged_title,
                document_type=items[0].get("document_type"),
            )
            merged.append({
                "title": merged_title,
                "content": merged_content,
                "summary": merged_summary,
                "source_section": key,
                "office": items[0].get("office"),
                "source_filename": items[0].get("source_filename"),
                "document_type": items[0].get("document_type"),
            })
        else:
            merged.extend(items)
    return merged


def _candidate_needs_review(quality: float, confidence: float, reasons: list[str], doc_type: str = "information") -> bool:
    if reasons:
        return True
    if doc_type in {"requirement", "procedure"}:
        return quality < 2.0
    return quality < 2.0 or confidence < 0.55


def _is_saveable_candidate(candidate: dict, quality: float) -> bool:
    doc_type = str(candidate.get("document_type") or "information").strip().lower()
    if doc_type == "information":
        return quality >= 3.0
    return True


_SEVERE_RECOMMENDATION_REASONS = frozenset({
    "title_looks_sentence",
    "title_too_long",
    "title_incomplete_ocr_fragment",
    "content_too_short",
    "low_category_confidence",
    "person_or_position_title",
    "appendix_only_title",
    "action_step_fragment",
    "table_row_fragment",
    "title_ends_with_hanging_word",
    "title_looks_generic",
    "information_title_weak",
    "title_from_body",
    "administrative_background_title",
    "vague_section_title",
    "irregular_title_casing",
    "low_student_usefulness",
    "mixed_article_scope",
    "internal_role_list",
    "messy_content_pattern",
})

# Generic topic clusters used to detect overly broad/mixed candidates.
_TOPIC_CLUSTER_PATTERNS: dict[str, tuple[str, ...]] = {
    "admission_policy": ("admission policy", "admission is", "open admission", "admitted to"),
    "non_discrimination": ("non-discrimination", "non discrimination", "shall not discriminate", "regardless of sex", "regardless of gender"),
    "foreign_students": ("foreign student", "international student", "alien student"),
    "admission_test": ("admission test", "entrance examination", "entrance exam", "admission examination"),
    "qualifying_exam": ("qualifying examination", "qualifying exam"),
    "interview_screening": ("interview", "screening"),
    "academic_qualification": ("general weighted average", " gwa ", "grade requirement", "weighted average"),
    "enrollment_registration": ("enrollment", "registration", "enroll in", "register for"),
    "transfer_validation": ("transfer student", "transferee", "validation of", "advanced credit"),
    "graduation": ("graduation requirement", "before graduation", "graduate from"),
    "clearance": ("clearance requirement", "secure clearance", "clearance from"),
    "residency": ("residency requirement", "residence requirement"),
    "tree_planting": ("tree planting",),
    "ceremony_attendance": ("graduation ceremony", "commencement", "attendance is required"),
    "counseling_process": ("counseling process", "follow-up", "referral"),
    "health_crisis": ("mental health", "crisis", "health risk", "workgroup"),
}


def _matched_topic_clusters(*texts: str) -> set[str]:
    haystack = " ".join(str(text or "") for text in texts).lower()
    if not haystack.strip():
        return set()
    matched: set[str] = set()
    for cluster, patterns in _TOPIC_CLUSTER_PATTERNS.items():
        if any(pattern in haystack for pattern in patterns):
            matched.add(cluster)
    return matched


def _distinct_source_leaves(sections: list[str] | None) -> set[str]:
    leaves: set[str] = set()
    for section in sections or []:
        parts = [part.strip().lower() for part in re.split(r"[>/|]", str(section or "")) if part.strip()]
        if parts:
            leaves.add(parts[-1])
    return leaves


def detect_mixed_article_scope(candidate: dict) -> bool:
    """Return True when one candidate mixes too many unrelated subtopics."""
    title = str(candidate.get("title") or "")
    content = str(candidate.get("content") or "")
    if "----EXTRACTED METADATA----" in content:
        content = content.split("----EXTRACTED METADATA----", 1)[0]
    source_sections = list(candidate.get("source_sections") or [])
    if not source_sections and candidate.get("source_section"):
        source_sections = [str(candidate.get("source_section"))]
    intents = {
        str(intent).strip().lower()
        for intent in (candidate.get("student_intents") or [])
        if str(intent).strip()
    }
    clusters = _matched_topic_clusters(title, content, " ".join(source_sections))
    leaves = _distinct_source_leaves(source_sections)

    numbered_roots = set(
        re.findall(r"(?<!\d)(\d+)(?:\.\d+)*\.\s+(?=[A-Za-z\"'(])", content)
    )

    if len(clusters) >= 3:
        return True
    if len(leaves) >= 4 and len(clusters) >= 3:
        return True
    if len(source_sections) >= 4 and len(clusters) >= 3:
        return True
    if len(numbered_roots) >= 5 and len(clusters) >= 3:
        return True
    # Multiple intents alone are not enough; require clear multi-topic content.
    if len(intents) >= 3 and len(clusters) >= 3 and (
        len(source_sections) >= 3 or len(numbered_roots) >= 4 or len(leaves) >= 3
    ):
        return True
    return False


_MIXED_SCOPE_SUMMARY = (
    "This article contains multiple related policies or requirements from the "
    "uploaded source document and should be reviewed before publishing."
)
_INTERNAL_ROLE_SUMMARY = (
    "This article describes internal roles and responsibilities from the "
    "uploaded source document and should be reviewed before publishing."
)


_INFORMATION_LIKE_DOC_TYPES = frozenset({
    "information",
    "handbook",
    "handbook_policy",
    "policy",
    "manual",
    "memo",
    "memorandum",
    "general_information",
})

_REQUIREMENT_LIKE_DOC_TYPES = frozenset({
    "requirement",
    "form",
})

_PROCEDURE_LIKE_DOC_TYPES = frozenset({
    "procedure",
    "how_to",
})

_UNCERTAIN_ARTICLE_TYPES = frozenset({
    "",
    "not_article",
    "unknown",
})


def _is_information_like_doc_type(doc_type: str | None) -> bool:
    normalized = str(doc_type or "information").strip().lower() or "information"
    return normalized in _INFORMATION_LIKE_DOC_TYPES


def _is_charter_preview(item: dict) -> bool:
    return (
        is_charter_or_service_process_unit(item)
        or str(item.get("parser_document_type") or "").lower() in {"citizen_charter", "service_process"}
        or str(item.get("source_type") or "") in {"Citizen's Charter", "Service Process"}
        or str(item.get("document_type") or "").lower() in {"citizen_charter", "service_process"}
        or str(item.get("document_profile") or "").lower() in {"citizen_charter", "service_process"}
        or str(item.get("formatter_used") or "") == "build_charter_article_body"
        or str(item.get("parser_used") or "")
        in {"citizen_charter_service_parser", "citizen_charter_extractor_v2"}
        or str(item.get("article_type") or "").lower() == "service_procedure"
    )


def _filled_office(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text not in {"[NEEDS REVIEW]", "Not specified", "None"}


def _filter_charter_review_reasons(reasons: list[str] | None) -> list[str]:
    """Keep charter blocking + audience routing flags; drop handbook-noise flags."""
    kept: list[str] = []
    for reason in reasons or []:
        key = str(reason or "").strip()
        if not key:
            continue
        if key in CHARTER_NON_BLOCKING_REVIEW_FLAGS:
            continue
        if key in CHARTER_BLOCKING_REVIEW_FLAGS or key in {
            "internal_admin_service",
            "ambiguous_service_audience",
            "charter_needs_review",
            "uncertain_audience",
            "internal_admin_heavy",
        }:
            kept.append(key)
    return kept


def _passes_charter_recommendation_gate(saved: dict) -> bool:
    """Citizen's Charter gate — do not reuse handbook policy thresholds."""
    title = str(saved.get("title") or "").strip()
    if not title or is_artifact_charter_title(title) or looks_like_truncated_charter_title(title):
        return False
    if is_charter_field_label_or_fragment_title(title):
        return False
    if _is_unpublishable_title(title):
        return False

    charter_bucket = str(saved.get("charter_candidate_bucket") or "").strip().lower()
    if charter_bucket and charter_bucket != "recommended":
        return False

    reasons = list(saved.get("review_reason") or [])
    if "incomplete_structured_fields" in reasons or "table_row_fragment" in reasons:
        return False
    if charter_blocking_review_flags(reasons):
        return False
    if charter_blocks_publish(reasons):
        return False

    audience = str(saved.get("charter_audience") or "").strip().lower()
    student_score = float(saved.get("student_facing_score") or 0.0)
    internal_score = float(saved.get("internal_admin_score") or 0.0)
    if audience == "internal" or internal_score > student_score:
        return False
    if audience == "ambiguous" and student_score <= 0:
        return False

    raw_content = str(saved.get("content") or "")
    if "----EXTRACTED METADATA----" in raw_content:
        raw_content = raw_content.split("----EXTRACTED METADATA----", 1)[0]
    if has_mixed_charter_services(title=title, text=raw_content):
        return False
    if raw_content and not charter_body_has_required_sections(raw_content):
        return False

    # Reject all-Not-specified / empty structured bodies.
    if not _charter_body_has_usable_fields(raw_content, saved):
        return False

    # Final semantic + body validation for every Recommended candidate.
    from app.services.citizen_charter_rescue import validate_charter_candidate_for_recommended
    from app.services.citizen_charter_services import charter_body_has_blocking_placeholders

    if charter_body_has_blocking_placeholders(raw_content):
        return False
    semantic_ok, _blockers = validate_charter_candidate_for_recommended(saved)
    if not semantic_ok:
        return False
    if saved.get("semantic_validation_passed") is False:
        return False
    if saved.get("final_body_validation_passed") is False:
        return False

    formatter = str(saved.get("formatter_used") or "").strip()
    parser = str(saved.get("parser_used") or "").strip()
    meta = {}
    try:
        meta = extract_embedded_article_metadata(str(saved.get("content") or ""))
    except Exception:
        meta = {}
    formatter = formatter or str(meta.get("formatter_used") or "")
    parser = parser or str(meta.get("parser_used") or "")
    if formatter and formatter != "build_charter_article_body":
        return False
    if parser and parser not in {"citizen_charter_service_parser", "citizen_charter_extractor_v2"}:
        return False
    if not formatter or not parser:
        # Charter Recommended requires explicit formatter/parser markers.
        return False

    # Soft quality floor only — never require handbook 7.0/7.5 thresholds.
    quality = float(saved.get("quality_score") or 0.0)
    if quality < 1.5:
        return False
    return True


def _charter_body_has_usable_fields(content: str, saved: dict | None = None) -> bool:
    """True when office + who/classification + requirements or real steps are present."""
    data = saved or {}
    office = str(data.get("office") or "").strip()
    who = str(data.get("who_may_avail") or "").strip()
    classification = str(data.get("classification") or "").strip()
    blob = content or ""

    def _present(value: str) -> bool:
        text = (value or "").strip()
        return bool(text) and text not in {"[NEEDS REVIEW]", "Not specified", "None", "or Division"}

    if not _present(office):
        office_match = re.search(r"(?im)^Office\s*/?\s*Division\s*\n\s*(.+)$", blob)
        office = office_match.group(1).strip() if office_match else ""
    if not _present(who):
        who_match = re.search(r"(?im)^Who May Avail\s*\n\s*(.+)$", blob)
        who = who_match.group(1).strip() if who_match else ""
    if not _present(classification):
        class_match = re.search(r"(?im)^Classification\s*\n\s*(.+)$", blob)
        classification = class_match.group(1).strip() if class_match else ""

    req_section = re.search(
        r"(?is)^Requirements?\s*\n(.+?)(?=^Steps\s*$|^Fees\s*$|^Total Processing Time\s*$|\Z)",
        blob,
        flags=re.M,
    )
    req_body = req_section.group(1).strip() if req_section else ""
    has_reqs = bool(data.get("requirements")) or (
        bool(req_body)
        and "not specified" not in req_body.casefold()
        and "[needs review]" not in req_body.casefold()
    )
    has_steps = bool(data.get("steps")) or bool(
        re.search(r"(?im)^(?:\d+\.\s*)?Client Step:", blob)
    )
    if not _present(office):
        return False
    if not (_present(who) or _present(classification)):
        return False
    if not has_steps:
        return False
    if not (has_reqs or has_steps):
        return False
    return True


def _passes_recommendation_gate(saved: dict) -> bool:
    """Final strict gate applied before a candidate lands in Recommended."""
    if _is_charter_preview(saved):
        return _passes_charter_recommendation_gate(saved)

    if bool(saved.get("needs_review")):
        return False
    reasons = saved.get("review_reason") or []
    if reasons:
        return False

    title = str(saved.get("title") or "").strip()
    if not title or _is_unpublishable_title(title):
        return False

    article_type = str(
        saved.get("article_type") or saved.get("document_type") or "information"
    ).strip().lower()
    if article_type in _UNCERTAIN_ARTICLE_TYPES:
        return False

    quality = float(saved.get("quality_score") or 0.0)
    confidence = float(saved.get("category_confidence") or 0.0)
    usefulness = float(saved.get("student_usefulness_score") or 0.0)
    doc_type = str(saved.get("document_type") or article_type or "information").strip().lower()

    if usefulness <= 0:
        return False
    if confidence < 0.60:
        return False

    if doc_type in _REQUIREMENT_LIKE_DOC_TYPES or article_type in _REQUIREMENT_LIKE_DOC_TYPES:
        min_quality = 7.0
    elif doc_type in _PROCEDURE_LIKE_DOC_TYPES or article_type in _PROCEDURE_LIKE_DOC_TYPES:
        min_quality = 7.0
    else:
        min_quality = 7.5

    if quality < min_quality:
        return False

    summary = str(saved.get("summary") or "").strip()
    if not summary or is_generic_only_summary(summary, title=title):
        return False

    raw_content = str(saved.get("content") or "")
    metadata = extract_embedded_article_metadata(raw_content)
    if "----EXTRACTED METADATA----" in raw_content:
        raw_content = raw_content.split("----EXTRACTED METADATA----", 1)[0]
    content = clean_article_content_for_display(raw_content)
    # Ground foreign-term checks in the official source excerpt, not the formatted body.
    grounded_content = str(metadata.get("official_source_excerpt") or content)
    if summary_has_foreign_topic_terms(
        summary,
        title=title,
        content=grounded_content,
        source_sections=saved.get("source_sections") or metadata.get("source_sections") or [],
    ):
        return False

    return True


def _finalize_planner_buckets(
    preview_candidates: list[dict],
    *,
    max_candidates: int | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Assign final planner buckets; optionally cap Recommended for dev/testing."""
    for item in preview_candidates:
        raw_bucket = str(item.get("planner_bucket") or item.get("raw_bucket") or "pending").strip().lower()
        item["raw_bucket"] = raw_bucket

        if _is_charter_artifact_preview(item) or is_charter_field_label_or_fragment_title(
            str(item.get("title") or "")
        ):
            reasons = list(item.get("review_reason") or [])
            flag = (
                "field_label_title"
                if is_charter_field_label_or_fragment_title(str(item.get("title") or ""))
                else "charter_artifact_title"
            )
            if flag not in reasons:
                reasons.append(flag)
            if "table_row_fragment" not in reasons and _looks_like_table_row_fragment(
                str(item.get("title") or "")
            ):
                reasons.append("table_row_fragment")
            item["review_reason"] = reasons
            item["charter_candidate_bucket"] = item.get("charter_candidate_bucket") or "low_quality"
            item["bucket_reason"] = item.get("bucket_reason") or flag
            _apply_final_bucket(item, "low_quality", raw_bucket=raw_bucket, corrected=True)
            continue

        if _is_charter_preview(item):
            charter_bucket = str(item.get("charter_candidate_bucket") or "").strip().lower()
            reasons = list(item.get("review_reason") or [])
            # Never promote incomplete / fragment charter candidates into Recommended.
            if any(
                flag in reasons
                for flag in (
                    "incomplete_structured_fields",
                    "table_row_fragment",
                    "incomplete_step_rows",
                    "field_label_title",
                )
            ):
                target = "low_quality" if "table_row_fragment" in reasons or "field_label_title" in reasons else "needs_review"
                if charter_bucket in {"low_quality", "rag_only"}:
                    target = charter_bucket
                _apply_final_bucket(
                    item,
                    target,
                    raw_bucket=raw_bucket,
                    corrected=raw_bucket not in {target, "pending", ""},
                )
                item["bucket_reason"] = item.get("bucket_reason") or reasons[0]
                continue

            if charter_bucket == "recommended" and _passes_charter_recommendation_gate(item):
                item["bucket_reason"] = item.get("bucket_reason") or "clean_student_facing_service"
                item["review_reason"] = _filter_charter_review_reasons(item.get("review_reason"))
                _apply_final_bucket(
                    item,
                    "recommended",
                    raw_bucket=raw_bucket,
                    corrected=raw_bucket not in {"recommended", "pending", ""},
                )
                continue
            if charter_bucket == "recommended" and not _passes_charter_recommendation_gate(item):
                # Already-Recommended malformed candidates must be downgraded.
                from app.services.citizen_charter_rescue import (
                    validate_charter_candidate_for_recommended,
                )

                _ok, blockers = validate_charter_candidate_for_recommended(item)
                reasons = list(item.get("review_reason") or [])
                for flag in blockers or ["semantic_validation_failed"]:
                    if flag not in reasons:
                        reasons.append(flag)
                item["review_reason"] = reasons
                item["remaining_blockers"] = list(blockers)
                item["semantic_validation_passed"] = False
                item["final_body_validation_passed"] = False
                item["charter_candidate_bucket"] = "needs_review"
                item["bucket_reason"] = "semantic_validation_failed"
                _apply_final_bucket(
                    item,
                    "needs_review",
                    raw_bucket=raw_bucket,
                    corrected=True,
                )
                continue
            if charter_bucket in {"low_quality", "rag_only"} or looks_like_truncated_charter_title(
                str(item.get("title") or "")
            ):
                target = charter_bucket if charter_bucket in {"low_quality", "rag_only"} else "low_quality"
                _apply_final_bucket(
                    item,
                    target,
                    raw_bucket=raw_bucket,
                    corrected=raw_bucket not in {target, "pending", ""},
                )
                item["bucket_reason"] = item.get("bucket_reason") or "incomplete_charter_service"
                continue
            if charter_bucket == "needs_review":
                _apply_final_bucket(
                    item,
                    "needs_review",
                    raw_bucket=raw_bucket,
                    corrected=raw_bucket not in {"needs_review", "pending", ""},
                )
                item["bucket_reason"] = item.get("bucket_reason") or (
                    "internal_admin_heavy"
                    if str(item.get("charter_audience") or "") == "internal"
                    else "uncertain_audience"
                )
                reasons = list(item.get("review_reason") or [])
                if item["bucket_reason"] not in reasons:
                    reasons.append(item["bucket_reason"])
                item["review_reason"] = _filter_charter_review_reasons(reasons) or reasons
                continue
            # No explicit charter bucket: only Recommended when gate passes.
            if _passes_charter_recommendation_gate(item):
                item["charter_candidate_bucket"] = "recommended"
                item["bucket_reason"] = item.get("bucket_reason") or "clean_student_facing_service"
                item["review_reason"] = _filter_charter_review_reasons(item.get("review_reason"))
                _apply_final_bucket(item, "recommended", raw_bucket=raw_bucket, corrected=True)
                continue
            _apply_final_bucket(item, "needs_review", raw_bucket=raw_bucket, corrected=True)
            item["bucket_reason"] = item.get("bucket_reason") or "uncertain_audience"
            continue

        bucket = str(item.get("planner_bucket") or "").strip().lower()
        if bucket in {"low_quality", "consolidated_parent", "rag_only"}:
            if bucket == "consolidated_parent" and _is_charter_artifact_preview(item):
                _apply_final_bucket(item, "low_quality", raw_bucket=raw_bucket, corrected=True)
                continue
            _apply_final_bucket(item, bucket, raw_bucket=raw_bucket)
            continue

        if _passes_recommendation_gate(item):
            _apply_final_bucket(item, "recommended", raw_bucket=raw_bucket)
            continue
        reasons = list(item.get("review_reason") or [])
        if "borderline_recommendation" not in reasons:
            reasons.append("borderline_recommendation")
        item["review_reason"] = reasons
        _apply_final_bucket(item, "needs_review", raw_bucket=raw_bucket)

    recommended = [
        item
        for item in preview_candidates
        if item.get("final_bucket") == "recommended" and not _is_charter_artifact_preview(item)
    ]
    recommended.sort(key=_recommendation_sort_key, reverse=True)

    if max_candidates is not None and max_candidates > 0 and len(recommended) > max_candidates:
        for item in recommended[max_candidates:]:
            reasons = list(item.get("review_reason") or [])
            if "recommended_cap_exceeded" not in reasons:
                reasons.append("recommended_cap_exceeded")
            item["review_reason"] = reasons
            item["bucket_reason"] = "recommended_cap_exceeded"
            _apply_final_bucket(item, "needs_review", raw_bucket=item.get("raw_bucket"), corrected=True)
        recommended = recommended[:max_candidates]

    needs_review = [
        item
        for item in preview_candidates
        if item.get("final_bucket") == "needs_review" and not _is_charter_artifact_preview(item)
    ]
    consolidated = [
        item
        for item in preview_candidates
        if item.get("final_bucket") == "consolidated_parent" and not _is_charter_artifact_preview(item)
    ]
    return recommended, needs_review, consolidated


def _is_charter_artifact_preview(item: dict) -> bool:
    """True when a preview must never sit in Recommended / Consolidated / Needs Review."""
    if not (
        is_charter_or_service_process_unit(item)
        or str(item.get("parser_document_type") or "").lower() in {"citizen_charter", "service_process"}
        or str(item.get("source_type") or "") in {"Citizen's Charter", "Service Process"}
    ):
        # Still reject obvious artifact titles even if metadata is thin.
        title = str(item.get("title") or "")
        if is_artifact_charter_title(title):
            return True
        return False
    reasons = [str(r) for r in (item.get("review_reason") or [])]
    if charter_blocks_publish(reasons):
        return True
    return should_reject_charter_article_candidate(
        title=str(item.get("title") or ""),
        source_section=str(item.get("source_section") or ""),
        parent_topic=str(item.get("parent_topic") or ""),
        hierarchy_path=str(item.get("source_section") or ""),
        office=str(item.get("office") or ""),
        who_may_avail=str(item.get("who_may_avail") or ""),
    )


def _recommendation_sort_key(saved: dict) -> tuple[float, float, float, str]:
    usefulness = float(saved.get("student_usefulness_score") or 0.0)
    return (
        usefulness,
        float(saved.get("quality_score") or 0.0),
        float(saved.get("category_confidence") or 0.0),
        saved.get("title") or "",
    )


def _candidate_summary(candidate: dict, *, quality: float, confidence: float, needs_review: bool, reasons: list[str], article_id: str | None = None, category: str | None = None) -> dict:
    doc_type = str(candidate.get("document_type") or "information")
    summary = {
        "title": candidate.get("title"),
        "quality_score": quality,
        "category_confidence": confidence,
        "student_usefulness_score": _student_usefulness_score(candidate.get("title") or "", category, doc_type),
        "needs_review": needs_review,
        "review_reason": reasons,
        "source_section": candidate.get("source_section"),
        "document_type": candidate.get("document_type"),
        "source_filename": candidate.get("source_filename"),
        "office": candidate.get("office"),
    }
    if category is not None:
        summary["category"] = category
    if article_id is not None:
        summary["id"] = article_id
    return summary


def _build_saved_article_fields(
    candidate: dict,
    *,
    quality: float,
    confidence: float,
    needs_review: bool,
    reasons: list[str],
    category: str | None = None,
) -> dict[str, Any]:
    title = candidate.get("title") or "Untitled"
    raw_content = clean_article_content_for_display(candidate.get("content") or "")
    review_reasons = list(reasons)
    if detect_mixed_article_scope(candidate) and "mixed_article_scope" not in review_reasons:
        review_reasons.append("mixed_article_scope")
        needs_review = True

    summary = build_article_summary(
        raw_content,
        candidate.get("summary"),
        title=title,
        document_type=str(candidate.get("document_type") or "information"),
        consolidated_parent=bool(candidate.get("consolidated_parent")),
        source_sections=list(candidate.get("source_sections") or []),
        article_type=str(candidate.get("article_type") or candidate.get("document_type") or "information"),
    )
    resolved_category = category or (
        classify_chunk(_candidate_classification_text({
            "title": title,
            "summary": summary,
            "content": raw_content,
        }), title=title).category or "General Information"
    )
    preferred = str(candidate.get("_preferred_category") or candidate.get("suggested_category") or "").strip()
    if preferred:
        resolved_category = preferred
    usefulness = _student_usefulness_score(
        title,
        resolved_category,
        str(candidate.get("document_type") or "information"),
    )
    article_type = str(candidate.get("article_type") or candidate.get("document_type") or "information")
    is_charter = (
        str(candidate.get("parser_document_type") or "").lower() in {"citizen_charter", "service_process"}
        or str(candidate.get("source_type") or "") in {"Citizen's Charter", "Service Process"}
        or str(candidate.get("document_type") or "").lower() in {"citizen_charter", "service_process"}
        or str(candidate.get("document_profile") or "").lower() in {"citizen_charter", "service_process"}
        or is_charter_or_service_process_unit(candidate)
    )
    if is_charter:
        # Never use the generic handbook formatter for Citizen's Charter.
        reqs = candidate.get("requirements") or []
        steps = candidate.get("steps") or []
        if isinstance(reqs, str):
            try:
                reqs = json.loads(reqs)
            except Exception:
                reqs = []
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except Exception:
                steps = []
        charter_body = build_charter_article_body(
            title=title,
            service={
                "office": candidate.get("office")
                or candidate.get("extracted_office")
                or (candidate.get("metadata") or {}).get("extracted_office")
                or (candidate.get("metadata") or {}).get("office_division")
                or (candidate.get("metadata") or {}).get("office"),
                "who_may_avail": candidate.get("who_may_avail")
                or (candidate.get("metadata") or {}).get("who_may_avail"),
                "classification": candidate.get("classification")
                or (candidate.get("metadata") or {}).get("classification"),
                "requirements": reqs,
                "steps": steps,
                "total_processing_time": candidate.get("total_processing_time")
                or (candidate.get("metadata") or {}).get("total_processing_time"),
                "total_fees": candidate.get("total_fees")
                or (candidate.get("metadata") or {}).get("total_fees"),
                "page": candidate.get("page") or (candidate.get("metadata") or {}).get("page"),
                "document_title": candidate.get("document_title")
                or (candidate.get("metadata") or {}).get("document_title"),
                "checklist_blank": bool(
                    candidate.get("checklist_blank")
                    or (candidate.get("metadata") or {}).get("checklist_blank")
                ),
                "parser_debug": candidate.get("parser_debug")
                or (candidate.get("metadata") or {}).get("parser_debug")
                or {},
            },
            source_document=str(
                candidate.get("source_filename")
                or (candidate.get("metadata") or {}).get("source_document")
                or ""
            ),
        )
        if has_mixed_charter_services(title=title, text=charter_body):
            if "mixed_charter_services" not in review_reasons:
                review_reasons.append("mixed_charter_services")
            needs_review = False
        if not charter_body_has_required_sections(charter_body):
            if "invalid_charter_service_block" not in review_reasons:
                review_reasons.append("invalid_charter_service_block")
            needs_review = False
        content_pattern = "citizen_charter_service"
        document_type = "citizen_charter"
        article_type = "service_procedure"
        parser_debug = candidate.get("parser_debug") or (candidate.get("metadata") or {}).get(
            "parser_debug"
        )
        is_v2 = str(candidate.get("parser_used") or "") == "citizen_charter_extractor_v2"
        meta = {
            "document_type": document_type,
            "document_profile": "citizen_charter",
            "article_type": article_type,
            "source_section": candidate.get("source_section"),
            "source_sections": candidate.get("source_sections") or [],
            "source_filename": candidate.get("source_filename"),
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "parser_used": (
                "citizen_charter_extractor_v2" if is_v2 else "citizen_charter_service_parser"
            ),
            "formatter_used": "build_charter_article_body",
            "detected_document_type": candidate.get("detected_document_type") or "citizen_charter",
            "admin_selected_document_type": candidate.get("admin_selected_document_type"),
            "official_source_excerpt": charter_body,
            "content_sections": [],
            "content_formatting_notes": ["citizen_charter_structure"],
            "content_pattern": content_pattern,
            "category_confidence": confidence,
            "quality_score": quality,
            "student_usefulness_score": usefulness,
            "needs_review": needs_review,
            "review_reason": review_reasons,
            "planner_bucket": candidate.get("planner_bucket"),
            "bucket_reason": candidate.get("bucket_reason"),
            "charter_audience": candidate.get("charter_audience"),
            "charter_candidate_bucket": candidate.get("charter_candidate_bucket"),
            "student_facing_score": candidate.get("student_facing_score"),
            "internal_admin_score": candidate.get("internal_admin_score"),
            "blocking_review_flags": list(
                candidate.get("blocking_review_flags")
                or charter_blocking_review_flags(review_reasons)
            ),
            "total_fees": candidate.get("total_fees")
            or (candidate.get("metadata") or {}).get("total_fees"),
            "parser_debug": parser_debug,
            "extraction_quality": candidate.get("extraction_quality"),
            "extraction_quality_reason": candidate.get("extraction_quality_reason"),
            "parser_strategy_used": candidate.get("parser_strategy_used"),
            "table_extraction_method": candidate.get("table_extraction_method"),
            "page_start": candidate.get("page_start"),
            "page_end": candidate.get("page_end"),
        }
        meta_block = "\n\n----EXTRACTED METADATA----\n" + json.dumps(meta, ensure_ascii=False, indent=2)
        return {
            "title": title,
            "category": resolved_category,
            "summary": summary,
            "content": charter_body + meta_block,
            "office": candidate.get("office"),
            "source_filename": candidate.get("source_filename"),
            "source_section": candidate.get("source_section"),
            "document_type": document_type,
            "quality_score": quality,
            "category_confidence": confidence,
            "student_usefulness_score": usefulness,
            "needs_review": needs_review,
            "review_reason": review_reasons,
        }

    formatted = format_article_content(
        title,
        article_type,
        raw_content,
        summary=summary,
        metadata={
            "document_type": candidate.get("document_type"),
            "article_type": article_type,
            "office": candidate.get("office"),
            "source_section": candidate.get("source_section"),
            "source_sections": candidate.get("source_sections") or [],
            "source_filename": candidate.get("source_filename"),
            "parser_document_type": candidate.get("parser_document_type"),
            "source_type": candidate.get("source_type"),
            "formatter_used": "generic_policy_formatter",
            "parser_used": candidate.get("parser_used") or "generic_handbook_parser",
        },
    )
    content_pattern = str(getattr(formatted, "content_pattern", "") or "")
    if content_pattern in {"messy_ocr", "messy_fragments"} and "messy_content_pattern" not in review_reasons:
        review_reasons.append("messy_content_pattern")
        needs_review = True
    if content_pattern == "role_responsibility_list" and "internal_role_list" not in review_reasons:
        # Role/responsibility lists are often admin-facing; keep reviewable.
        review_reasons.append("internal_role_list")
        needs_review = True
    if "internal_facing" in (formatted.formatting_notes or []) and "internal_role_list" not in review_reasons:
        review_reasons.append("internal_role_list")
        needs_review = True

    if "internal_role_list" in review_reasons:
        summary = _INTERNAL_ROLE_SUMMARY
    elif "mixed_article_scope" in review_reasons:
        summary = _MIXED_SCOPE_SUMMARY

    meta = {
        "document_type": candidate.get("document_type"),
        "article_type": article_type,
        "source_section": candidate.get("source_section"),
        "source_sections": candidate.get("source_sections") or [],
        "source_filename": candidate.get("source_filename"),
        "parser_document_type": candidate.get("parser_document_type"),
        "source_type": candidate.get("source_type"),
        "parser_used": candidate.get("parser_used") or "generic_handbook_parser",
        "formatter_used": "generic_policy_formatter",
        "detected_document_type": candidate.get("detected_document_type"),
        "admin_selected_document_type": candidate.get("admin_selected_document_type"),
        "official_source_excerpt": formatted.official_source_excerpt,
        "content_sections": formatted.sections,
        "content_formatting_notes": formatted.formatting_notes,
        "content_pattern": content_pattern,
        "category_confidence": confidence,
        "quality_score": quality,
        "student_usefulness_score": usefulness,
        "needs_review": needs_review,
        "review_reason": review_reasons,
    }
    meta_block = "\n\n----EXTRACTED METADATA----\n" + json.dumps(meta, ensure_ascii=False, indent=2)
    return {
        "title": title,
        "category": resolved_category,
        "summary": summary,
        "content": formatted.display_content + meta_block,
        "office": candidate.get("office"),
        "source_filename": candidate.get("source_filename"),
        "source_section": candidate.get("source_section"),
        "document_type": candidate.get("document_type"),
        "quality_score": quality,
        "category_confidence": confidence,
        "student_usefulness_score": usefulness,
        "needs_review": needs_review,
        "review_reason": review_reasons,
    }


def _normalize_office_name(value: str | None) -> str | None:
    office = str(value or "").strip()
    if not office:
        return None
    lowered = office.lower()
    if lowered in {"unknown", "not specified", "n/a", "none"}:
        return None
    if "needs review" in lowered:
        return None
    return office


def _taxonomy_parent_category(name: str | None) -> str | None:
    cleaned = str(name or "").strip()
    if not cleaned:
        return None
    for category in load_taxonomy():
        if category.name.lower() == cleaned.lower():
            return category.name
        for subcategory in category.subcategories:
            if subcategory.name.lower() == cleaned.lower():
                return category.name
    return None


def _source_section_parent(source_section: str | None) -> str | None:
    text = str(source_section or "").strip()
    if not text:
        return None
    for separator in (" > ", " / ", " | ", ">"):
        if separator in text:
            parent = text.split(separator, 1)[0].strip()
            if parent:
                return parent
    return text


def _candidate_review_text(candidate: dict) -> str:
    return " ".join(
        part
        for part in (
            candidate.get("title"),
            candidate.get("summary"),
            candidate.get("content"),
            candidate.get("source_section"),
            candidate.get("category"),
        )
        if part
    ).lower()


def _office_match_for_candidate(candidate: dict, db=None) -> tuple[str | None, str | None, float | None]:
    """Return (office_name, service_category, confidence) only from office_aliases."""
    existing_confidence = candidate.get("office_match_confidence")
    existing_office = _normalize_office_name(candidate.get("office"))
    if existing_office and existing_confidence is not None and float(existing_confidence) >= 0.72:
        return existing_office, candidate.get("service_category"), float(existing_confidence)

    haystack = _candidate_review_text(candidate)
    match = match_office_from_text(haystack, db)
    if match is None:
        return None, None, None
    return match.office_name, match.service_category, match.confidence


def resolve_candidate_group(candidate: dict, db=None) -> tuple[str, str]:
    """Group by confirmed office_aliases match first; never invent Office groups."""
    office, service_from_office, confidence = _office_match_for_candidate(candidate, db=db)
    if office and confidence is not None and confidence >= 0.72:
        return office, "office"

    if service_from_office:
        return str(service_from_office), "service_category"

    service_category = candidate.get("service_category") or _taxonomy_parent_category(candidate.get("category"))
    if service_category:
        return str(service_category), "service_category"

    category = str(candidate.get("category") or "").strip()
    if category:
        return category, "category"

    section_parent = _source_section_parent(candidate.get("source_section"))
    if section_parent:
        return section_parent, "source_section"

    return "Uncategorized", "uncategorized"


def _group_sort_key(group: dict) -> tuple[int, str]:
    priority = {
        "office": 0,
        "service_category": 1,
        "category": 2,
        "source_section": 3,
        "uncategorized": 4,
    }
    group_type = str(group.get("group_type") or "uncategorized")
    return (priority.get(group_type, 5), str(group.get("group_name") or "").lower())


def group_candidates_for_review(candidates: list[dict], db=None) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for candidate in candidates:
        enriched = dict(candidate)
        group_name, group_type = resolve_candidate_group(enriched, db=db)
        enriched["group_name"] = group_name
        enriched["group_type"] = group_type
        grouped[(group_name, group_type)].append(enriched)

    groups: list[dict] = []
    for (group_name, group_type), items in grouped.items():
        recommended_count = sum(1 for item in items if _passes_recommendation_gate(item))
        needs_review_count = sum(1 for item in items if bool(item.get("needs_review")))
        low_confidence_count = sum(
            1
            for item in items
            if not _passes_recommendation_gate(item)
            and not bool(item.get("needs_review"))
        )
        duplicate_count = sum(
            1
            for item in items
            if "duplicate_existing" in (item.get("review_reason") or [])
        )
        groups.append(
            {
                "group_name": group_name,
                "group_type": group_type,
                "total_count": len(items),
                "recommended_count": recommended_count,
                "needs_review_count": needs_review_count,
                "low_confidence_count": low_confidence_count,
                "duplicate_count": duplicate_count,
                "candidates": items,
            }
        )
    groups.sort(key=_group_sort_key)
    return groups


def _resolve_planner_bucket(
    candidate: dict,
    *,
    quality: float,
    needs_review: bool,
    reasons: list[str],
) -> str:
    title = candidate.get("title") or ""
    if _is_unpublishable_title(title) or is_charter_field_label_or_fragment_title(title):
        return "low_quality"
    if not _is_saveable_candidate(candidate, quality):
        return "low_quality"
    # Preserve explicit charter routing — never collapse to pending.
    if _is_charter_preview(candidate):
        charter_bucket = str(candidate.get("charter_candidate_bucket") or "").strip().lower()
        if charter_bucket in {"recommended", "needs_review", "low_quality", "rag_only"}:
            return charter_bucket
        existing = str(candidate.get("planner_bucket") or "").strip().lower()
        if existing in {"recommended", "needs_review", "low_quality", "rag_only", "consolidated_parent"}:
            return existing
        return "needs_review" if needs_review else "pending"
    if candidate.get("consolidated_parent") and candidate.get("merge_coherent", True):
        return "consolidated_parent"
    existing = str(candidate.get("planner_bucket") or "").strip().lower()
    if existing in {"recommended", "needs_review", "low_quality", "rag_only", "consolidated_parent"}:
        return existing
    return "pending"


def _candidate_preview_dict(
    candidate: dict,
    *,
    quality: float,
    confidence: float,
    needs_review: bool,
    reasons: list[str],
    preview_id: str,
    category: str | None = None,
    db=None,
) -> dict[str, Any]:
    fields = _build_saved_article_fields(
        candidate,
        quality=quality,
        confidence=confidence,
        needs_review=needs_review,
        reasons=reasons,
        category=category,
    )
    planner_bucket = candidate.get("planner_bucket") or _resolve_planner_bucket(
        candidate,
        quality=quality,
        needs_review=needs_review,
        reasons=reasons,
    )
    if planner_bucket == "low_quality":
        needs_review = False
    preview = {
        "id": preview_id,
        "preview_id": preview_id,
        "is_preview": True,
        "title": fields["title"],
        "category": fields["category"],
        "summary": fields["summary"],
        "content": fields["content"],
        "office": fields["office"] or candidate.get("office"),
        "source_filename": fields["source_filename"],
        "source_section": fields["source_section"] or candidate.get("source_section"),
        "source_sections": candidate.get("source_sections") or [],
        "document_type": fields["document_type"],
        "article_type": candidate.get("article_type") or fields["document_type"],
        "parent_topic": candidate.get("parent_topic"),
        "canonical_topic": candidate.get("canonical_topic") or fields["title"],
        "merged_unit_count": int(candidate.get("merged_unit_count") or 1),
        "consolidated_parent": bool(candidate.get("consolidated_parent")),
        "merge_coherent": bool(candidate.get("merge_coherent", True)),
        "blueprint_id": candidate.get("blueprint_id"),
        "service_category": candidate.get("service_category"),
        "office_match_confidence": candidate.get("office_match_confidence"),
        "planner_bucket": planner_bucket,
        "final_bucket": candidate.get("final_bucket") or planner_bucket,
        "raw_bucket": candidate.get("raw_bucket") or planner_bucket,
        "ui_group_bucket": candidate.get("ui_group_bucket")
        or candidate.get("final_bucket")
        or planner_bucket,
        "publish_allowed": candidate.get("publish_allowed"),
        "save_draft_allowed": candidate.get("save_draft_allowed"),
        "bucket_consistency_check": candidate.get("bucket_consistency_check") or "pending",
        "quality_score": fields["quality_score"],
        "category_confidence": fields["category_confidence"],
        "student_usefulness_score": fields["student_usefulness_score"],
        "needs_review": needs_review,
        "review_reason": fields["review_reason"],
        "charter_audience": candidate.get("charter_audience"),
        "charter_candidate_bucket": candidate.get("charter_candidate_bucket"),
        "bucket_reason": candidate.get("bucket_reason") or fields.get("bucket_reason"),
        "student_facing_score": candidate.get("student_facing_score"),
        "internal_admin_score": candidate.get("internal_admin_score"),
        "blocking_review_flags": list(
            candidate.get("blocking_review_flags")
            or charter_blocking_review_flags(fields.get("review_reason"))
        ),
        "parser_used": candidate.get("parser_used") or "citizen_charter_service_parser"
        if _is_charter_preview(candidate)
        else candidate.get("parser_used"),
        "formatter_used": candidate.get("formatter_used") or "build_charter_article_body"
        if _is_charter_preview(candidate)
        else candidate.get("formatter_used"),
        "document_profile": candidate.get("document_profile")
        or ("citizen_charter" if _is_charter_preview(candidate) else None),
        "original_bucket": candidate.get("original_bucket"),
        "repaired_bucket": candidate.get("repaired_bucket"),
        "rescue_attempted": candidate.get("rescue_attempted"),
        "rescue_successful": candidate.get("rescue_successful"),
        "rescue_reasons": list(candidate.get("rescue_reasons") or []),
        "repair_actions_applied": list(candidate.get("repair_actions_applied") or []),
        "remaining_blockers": list(candidate.get("remaining_blockers") or []),
        "semantic_validation_passed": candidate.get("semantic_validation_passed"),
        "final_body_validation_passed": candidate.get("final_body_validation_passed"),
        "needs_review_reasons": list(candidate.get("needs_review_reasons") or []),
        # Persist repaired structured fields so final Recommended gate can re-validate.
        "who_may_avail": candidate.get("who_may_avail"),
        "classification": candidate.get("classification"),
        "transaction_type": candidate.get("transaction_type"),
        "requirements": candidate.get("requirements") or [],
        "steps": candidate.get("steps") or [],
        "total_processing_time": candidate.get("total_processing_time"),
        "total_fees": candidate.get("total_fees"),
        "checklist_blank": candidate.get("checklist_blank"),
        "parser_debug": candidate.get("parser_debug")
        or (candidate.get("metadata") or {}).get("parser_debug"),
        "parser_document_type": candidate.get("parser_document_type"),
        "source_type": candidate.get("source_type"),
    }
    # Surface clear Needs Review reasons from rescue blockers when present.
    if preview.get("final_bucket") == "needs_review" or planner_bucket == "needs_review":
        merged_reasons = list(preview.get("review_reason") or [])
        for reason in preview.get("needs_review_reasons") or []:
            if reason and reason not in merged_reasons:
                merged_reasons.append(reason)
        for reason in preview.get("remaining_blockers") or []:
            if reason and reason not in merged_reasons:
                merged_reasons.append(reason)
        preview["review_reason"] = merged_reasons
        preview["needs_review_reasons"] = merged_reasons
    if preview.get("publish_allowed") is None:
        preview["publish_allowed"] = planner_bucket in {"recommended", "consolidated_parent"}
    if preview.get("save_draft_allowed") is None:
        preview["save_draft_allowed"] = planner_bucket in {
            "recommended",
            "consolidated_parent",
            "needs_review",
            "low_quality",
        }
    group_name, group_type = resolve_candidate_group(preview, db=db)
    preview["group_name"] = group_name
    preview["group_type"] = group_type
    return _annotate_existing_article_match(preview, db=db)


def _normalize_match_title(title: str | None) -> str:
    text = str(title or "").strip()
    text = re.sub(r"^\d{1,3}[\.\)]\s*", "", text).strip(" -–—:")
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _normalize_match_filename(filename: str | None) -> str:
    """Basename-only comparison so path / casing differences do not miss matches."""
    text = str(filename or "").strip().replace("\\", "/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text.casefold()


def _article_match_metadata(article: PublishedArticle) -> dict[str, Any]:
    meta = extract_embedded_article_metadata(article.content)
    return meta if isinstance(meta, dict) else {}


def find_similar_article(session, *, title: str, source_filename: str | None = None) -> PublishedArticle | None:
    query = session.query(PublishedArticle).filter(PublishedArticle.title == title)
    if source_filename:
        query = query.filter(PublishedArticle.source_filename == source_filename)
    exact = query.first()
    if exact is not None:
        return exact
    # Fallback: normalized title within the same source file.
    return find_matching_published_article(
        session,
        title=title,
        source_filename=source_filename,
    )


def find_matching_published_article(
    session,
    *,
    title: str,
    source_filename: str | None = None,
    source_section: str | None = None,
    document_type: str | None = None,
    article_type: str | None = None,
) -> PublishedArticle | None:
    """Match a generated candidate to a saved article using stable keys.

    Preferred Citizen's Charter keys (ordered):
    1. source_filename + source_section + article_type
    2. source_filename + normalized service title
    Also accepts exact normalized title across the library when filenames drift.
    """
    if session is None:
        return None
    want_title = _normalize_match_title(title)
    want_section = _normalize_match_title(source_section)
    want_doc = str(document_type or "").strip().casefold()
    want_art = str(article_type or "").strip().casefold()
    want_file = _normalize_match_filename(source_filename)
    is_charter = want_doc in {"citizen_charter", "service_process"} or want_art in {
        "service_procedure",
        "citizen_charter",
    }

    rows = session.query(PublishedArticle).all()
    if want_file:
        same_file = [
            row
            for row in rows
            if _normalize_match_filename(row.source_filename) == want_file
        ]
        # Prefer same-file rows; keep full library as fallback for basename drift.
        candidate_rows = same_file or rows
    else:
        candidate_rows = rows

    # 1) Explicit charter short-circuits (ordered).
    if is_charter and want_file:
        for row in candidate_rows:
            if _normalize_match_filename(row.source_filename) != want_file:
                continue
            meta = _article_match_metadata(row)
            row_section = _normalize_match_title(
                meta.get("source_section") or meta.get("canonical_topic")
            )
            row_art = str(meta.get("article_type") or "").strip().casefold()
            if (
                want_section
                and row_section
                and want_section == row_section
                and (not want_art or not row_art or want_art == row_art)
            ):
                return row
        for row in candidate_rows:
            if _normalize_match_filename(row.source_filename) != want_file:
                continue
            if want_title and _normalize_match_title(row.title) == want_title:
                return row
            meta = _article_match_metadata(row)
            row_section = _normalize_match_title(
                meta.get("source_section") or meta.get("canonical_topic")
            )
            if want_title and row_section == want_title:
                return row

    # 1b) Normalized source_section + normalized title fallback (filename optional).
    if is_charter and want_title and want_section:
        for row in rows:
            meta = _article_match_metadata(row)
            row_title = _normalize_match_title(row.title)
            row_section = _normalize_match_title(
                meta.get("source_section") or meta.get("canonical_topic")
            )
            if row_title == want_title and row_section == want_section:
                return row
            if row_title == want_title and row_section == want_title:
                return row
            if row_section == want_title and _normalize_match_title(row.title) == want_section:
                return row

    # 2) Scored fallback (title / section / type / file).
    best: PublishedArticle | None = None
    best_score = -1
    for row in candidate_rows:
        meta = _article_match_metadata(row)
        row_title = _normalize_match_title(row.title)
        row_section = _normalize_match_title(
            meta.get("source_section") or meta.get("canonical_topic")
        )
        row_doc = str(meta.get("document_type") or "").strip().casefold()
        row_art = str(meta.get("article_type") or "").strip().casefold()
        row_file = _normalize_match_filename(row.source_filename)
        score = 0
        if want_title and row_title == want_title:
            score += 8
        elif want_title and row_section == want_title:
            score += 8
        elif want_title and (want_title in row_title or row_title in want_title):
            score += 4
        if want_file and row_file == want_file:
            score += 3
        if want_section and row_section and want_section == row_section:
            score += 5
        if want_art and row_art and want_art == row_art:
            score += 2
        if want_doc and row_doc and want_doc == row_doc:
            score += 1
        # Same-file + fuzzy title is enough for charter regenerate.
        if is_charter and want_file and row_file == want_file and want_title and score >= 7:
            score = max(score, 8)
        if score > best_score:
            best_score = score
            best = row

    if best is None or best_score < 8:
        # Final library-wide normalized title match (filename can differ after rename).
        if want_title:
            for row in rows:
                if _normalize_match_title(row.title) == want_title:
                    if want_doc:
                        meta = _article_match_metadata(row)
                        row_doc = str(meta.get("document_type") or "").strip().casefold()
                        if row_doc and row_doc != want_doc and not is_charter:
                            continue
                    return row
        return None
    return best


def _annotate_existing_article_match(preview: dict[str, Any], db=None) -> dict[str, Any]:
    """Attach existing published/draft article ids so regenerate does not look unsaved."""
    if db is None:
        return preview
    match = find_matching_published_article(
        db,
        title=str(preview.get("title") or ""),
        source_filename=preview.get("source_filename"),
        source_section=preview.get("source_section") or preview.get("canonical_topic"),
        document_type=preview.get("document_type") or preview.get("document_profile"),
        article_type=preview.get("article_type"),
    )
    if match is None:
        preview.setdefault("existing_article_id", None)
        preview.setdefault("existing_published", False)
        preview.setdefault("already_published", False)
        preview.setdefault("existing_match_reason", None)
        preview.setdefault("publish_safety_state", "unsaved")
        return preview
    reason = "source_filename+normalized_title"
    meta = _article_match_metadata(match)
    if _normalize_match_title(preview.get("source_section")) and _normalize_match_title(
        meta.get("source_section") or meta.get("canonical_topic")
    ) == _normalize_match_title(preview.get("source_section")):
        reason = "source_filename+source_section+article_type"
    preview["existing_article_id"] = match.id
    preview["existing_published"] = bool(match.published)
    preview["already_published"] = bool(match.published)
    preview["existing_match_reason"] = reason
    preview["existing_article"] = {
        "id": match.id,
        "title": match.title,
        "published": bool(match.published),
        "source_filename": match.source_filename,
        "category": match.category,
        "office": match.office,
    }
    if match.published:
        preview["publish_allowed"] = False
        preview["publish_safety_state"] = "published"
    else:
        preview["publish_safety_state"] = "draft"
    return preview


def _preserve_published_match_flags(item: dict[str, Any]) -> None:
    """Keep Already Published / Update Existing after bucket finalize."""
    if item.get("already_published") or item.get("existing_published"):
        item["publish_allowed"] = False
        item["already_published"] = True
        item["existing_published"] = True
        item["publish_safety_state"] = "published"
    elif item.get("existing_article_id") and not item.get("existing_published"):
        item["publish_safety_state"] = "draft"
    else:
        item.setdefault("publish_safety_state", "unsaved")

def _create_draft_article(session, candidate: dict, *, quality: float, confidence: float, needs_review: bool, reasons: list[str]) -> PublishedArticle:
    fields = _build_saved_article_fields(
        candidate,
        quality=quality,
        confidence=confidence,
        needs_review=needs_review,
        reasons=reasons,
    )
    art = PublishedArticle(
        title=fields["title"],
        slug=(fields["title"].lower().replace(" ", "-")[:250]),
        category=fields["category"],
        subcategory=None,
        path=None,
        summary=fields["summary"],
        content=fields["content"],
        office=fields["office"],
        source_filename=fields["source_filename"],
        chunk_count=None,
        published=False,
    )
    session.add(art)
    session.commit()
    session.refresh(art)
    return art


def _rebuild_charter_units_from_preview(
    preview: dict,
    *,
    filename: str | None,
    profile: dict,
) -> list[dict]:
    """Rebuild Citizen's Charter knowledge units from review text / typed chunks."""
    from app.services.knowledge_document_types import (
        KnowledgeDocumentType,
        build_typed_chunks,
    )

    review_text = collect_charter_parser_text(preview, profile)
    profile["review_text"] = review_text
    if not review_text:
        return []

    source_document = filename or str(preview.get("source_filename") or "citizen-charter.pdf")
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.PROCEDURE,
        extraction=object(),
        index_text=review_text,
        title=source_document,
        source_document=source_document,
    )
    if not chunks:
        return []

    units: list[dict] = []
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        # Skip non-charter fallback information chunks from empty procedure parses.
        parser_kind = str(metadata.get("parser_document_type") or "").lower()
        if parser_kind and parser_kind not in {"citizen_charter", "service_process", "procedure"}:
            continue
        if not parser_kind and str(metadata.get("document_type") or "").lower() not in {
            "citizen_charter",
            "procedure",
            "service_process",
        }:
            # Information-chunk fallback — ignore for charter rebuild.
            if "extracted_requirements" not in metadata and "extracted_steps" not in metadata:
                continue
        metadata.setdefault("document_profile", "citizen_charter")
        metadata.setdefault("parser_document_type", "citizen_charter")
        metadata.setdefault("source_type", "Citizen's Charter")
        metadata.setdefault("document_type", "citizen_charter")
        metadata.setdefault("article_type", "service_procedure")
        metadata.setdefault("parser_used", "citizen_charter_service_parser")
        metadata.setdefault("formatter_used", "build_charter_article_body")
        if profile.get("admin_selected_document_type"):
            metadata["admin_selected_document_type"] = profile.get("admin_selected_document_type")
        if profile.get("detected_document_type"):
            metadata["detected_document_type"] = profile.get("detected_document_type")
        units.append(
            {
                "unit_index": chunk.chunk_index,
                "title": metadata.get("title") or metadata.get("section_heading") or "Untitled",
                "content": chunk.text,
                "content_type": "procedure",
                "hierarchy_path": metadata.get("section_heading") or metadata.get("title"),
                "metadata": metadata,
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
                "document_type": "citizen_charter",
                "document_profile": "citizen_charter",
                "article_eligible": True,
            }
        )
    return units


def _restrict_v1_fallback_units_to_diagnostic(units: list[dict], *, reason: str) -> list[dict]:
    """When V2 was attempted but produced zero usable services, V1 flat-text
    rebuild may still run for retrieval/debug — but must never surface as
    normal Recommended / Needs Review service article previews.
    """
    restricted: list[dict] = []
    for unit in units:
        item = dict(unit)
        metadata = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
        title = str(item.get("title") or metadata.get("title") or "").strip()
        # Fragments / artifacts → RAG-only; other incomplete V1 blocks → Low Quality.
        if (
            is_artifact_charter_title(title)
            or is_charter_field_label_or_fragment_title(title)
            or is_noise_service_title(title)
            or looks_like_truncated_charter_title(title)
        ):
            bucket = "rag_only"
            eligible = False
        else:
            bucket = "low_quality"
            eligible = True
        metadata["charter_candidate_bucket"] = bucket
        metadata["bucket_reason"] = reason
        metadata["v2_fallback_restricted"] = True
        metadata["parser_used"] = metadata.get("parser_used") or "citizen_charter_service_parser"
        item["metadata"] = metadata
        item["charter_candidate_bucket"] = bucket
        item["article_eligible"] = eligible
        item["needs_review_hint"] = reason
        restricted.append(item)
    return restricted


def _build_charter_units_from_v2_services(
    preview: dict,
    *,
    filename: str | None,
    profile: dict,
) -> list[dict]:
    """Build Citizen's Charter knowledge units directly from Citizen's Charter
    Extraction V2 structured services (``preview['charter_v2_services']``).

    When V2 output is available this replaces the old flat-text rebuild
    (``_rebuild_charter_units_from_preview``) entirely — Generate Articles
    must prefer V2 structured services over ``collect_charter_parser_text``.

    Mirrors the exact knowledge-unit / metadata shape the V1 charter pipeline
    already produces (``knowledge_document_types._procedure_chunks``) so the
    existing, already-tested Article Planner routing
    (``classify_unit_for_articles`` / ``classify_charter_candidate_bucket``)
    keeps working unchanged for V2-sourced units.

    Before bucket assignment, each service runs through the Citizen's Charter
    rescue/repair pipeline so valid student-facing procedures can be promoted
    without loosening Recommended gates.
    """
    from app.services.citizen_charter_rescue import (
        rescue_charter_v2_service,
        summarize_rescue_results,
    )

    v2_services = preview.get("charter_v2_services")
    if not isinstance(v2_services, list) or not v2_services:
        return []

    source_document = filename or str(preview.get("source_filename") or "citizen-charter.pdf")
    units: list[dict] = []
    rescue_results: list[dict] = []
    for index, service in enumerate(v2_services):
        if not isinstance(service, dict):
            continue
        if not str(service.get("service_title") or "").strip():
            continue

        rescued = rescue_charter_v2_service(service, source_document=source_document)
        rescue_results.append(rescued)

        service_title = str(rescued.get("title") or "").strip()
        if not service_title:
            continue

        service_fields = dict(rescued.get("service_fields") or {})
        extraction_quality = str(rescued.get("extraction_quality") or "low_quality").strip().lower()
        extraction_quality_reason = str(rescued.get("extraction_quality_reason") or "")
        repaired_service = rescued.get("service") if isinstance(rescued.get("service"), dict) else service
        parser_debug = (
            repaired_service.get("parser_debug")
            if isinstance(repaired_service.get("parser_debug"), dict)
            else {}
        )
        content = str(rescued.get("content") or "")
        audience = str(rescued.get("audience") or "ambiguous")
        category = str(rescued.get("category") or "Student Services")
        decision = dict(rescued.get("decision") or {})
        charter_bucket = str(rescued.get("repaired_bucket") or decision.get("bucket") or "needs_review")
        completeness = score_charter_service_completeness(
            {**service_fields, "service": service_title}
        )

        metadata = {
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": service_title,
            "procedure_title": service_title,
            "office": service_fields.get("office"),
            "extracted_office": service_fields.get("office"),
            "office_division": repaired_service.get("office_division") or service_fields.get("office"),
            "who_may_avail": service_fields.get("who_may_avail"),
            "classification": service_fields.get("classification"),
            "transaction_type": service_fields.get("transaction_type"),
            "checklist_blank": bool(
                repaired_service.get("checklist_blank") or service_fields.get("checklist_blank")
            ),
            "extracted_requirements": json.dumps(service_fields.get("requirements") or []),
            "extracted_steps": json.dumps(service_fields.get("steps") or []),
            "total_processing_time": service_fields.get("total_processing_time"),
            "total_fees": service_fields.get("total_fees"),
            "parser_debug": parser_debug,
            "source_document": source_document,
            "section_heading": service_title,
            "source_type": "Citizen's Charter",
            "parser_document_type": "citizen_charter",
            "document_profile": "citizen_charter",
            "parser_used": "citizen_charter_extractor_v2",
            "formatter_used": "build_charter_article_body",
            "detected_document_type": "citizen_charter",
            "charter_audience": decision.get("charter_audience") or audience,
            "suggested_category": category,
            "charter_completeness": completeness,
            "charter_candidate_bucket": charter_bucket,
            "bucket_reason": rescued.get("bucket_reason") or decision.get("bucket_reason"),
            "extraction_quality": extraction_quality,
            "extraction_quality_reason": extraction_quality_reason,
            "parser_strategy_used": parser_debug.get("parser_strategy_used"),
            "table_extraction_method": parser_debug.get("table_extraction_method"),
            "page_start": repaired_service.get("page_start"),
            "page_end": repaired_service.get("page_end"),
            "original_bucket": rescued.get("original_bucket"),
            "repaired_bucket": rescued.get("repaired_bucket"),
            "rescue_attempted": bool(rescued.get("rescue_attempted")),
            "rescue_successful": bool(rescued.get("rescue_successful")),
            "rescue_reasons": list(rescued.get("rescue_reasons") or []),
            "repair_actions_applied": list(rescued.get("repair_actions_applied") or []),
            "remaining_blockers": list(rescued.get("remaining_blockers") or []),
            "semantic_validation_passed": bool(rescued.get("semantic_validation_passed")),
            "final_body_validation_passed": bool(rescued.get("final_body_validation_passed")),
            "needs_review_reasons": list(rescued.get("needs_review_reasons") or []),
            "low_quality_rescue_attempted": bool(rescued.get("low_quality_repair_attempted")),
            "low_quality_rescue_successful": bool(rescued.get("low_quality_rescue_successful")),
            "missing_fields": list(rescued.get("missing_fields") or []),
            "row_merge_failure_reason": rescued.get("row_merge_failure_reason"),
        }
        if profile.get("admin_selected_document_type"):
            metadata["admin_selected_document_type"] = profile.get("admin_selected_document_type")
        if profile.get("detected_document_type"):
            metadata["detected_document_type"] = profile.get("detected_document_type")

        units.append(
            {
                "unit_index": index,
                "title": service_title,
                "content": content,
                "content_type": "procedure",
                "hierarchy_path": service_title,
                "metadata": metadata,
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
                "document_type": "citizen_charter",
                "document_profile": "citizen_charter",
                "charter_candidate_bucket": charter_bucket,
                "article_eligible": charter_bucket != "rag_only",
                "rescue_attempted": bool(rescued.get("rescue_attempted")),
                "rescue_successful": bool(rescued.get("rescue_successful")),
            }
        )

    preview["_charter_rescue_summary"] = summarize_rescue_results(rescue_results)
    preview["_charter_rescue_results"] = rescue_results
    return units


def _ensure_public_priority_candidates_visible(
    *,
    all_candidates: list[dict],
    working_preview: dict,
    filename: str | None,
    db=None,
) -> list[dict]:
    """Guarantee Priority Coverage found/recommended|needs_review|low_quality rows have cards."""
    diagnostics = []
    summary = working_preview.get("_charter_rescue_summary")
    if isinstance(summary, dict):
        diagnostics = list(summary.get("priority_service_diagnostics") or [])
    rescue_results = working_preview.get("_charter_rescue_results")
    if not isinstance(rescue_results, list):
        rescue_results = []
    by_title = {
        _normalize_match_title(item.get("title")): item
        for item in all_candidates
        if item.get("title")
    }
    rescue_by_title = {
        _normalize_match_title(item.get("title")): item
        for item in rescue_results
        if isinstance(item, dict) and item.get("title")
    }
    added: list[dict] = []
    for diag in diagnostics:
        if not isinstance(diag, dict) or not diag.get("found"):
            continue
        bucket = str(diag.get("final_bucket") or "").strip().lower()
        if bucket not in {"recommended", "needs_review", "low_quality"}:
            continue
        title = str(diag.get("title") or "").strip()
        key = _normalize_match_title(title)
        if not key or key in by_title:
            continue
        rescued = rescue_by_title.get(key)
        if rescued is None:
            # Alias lookup (ID Processing ↔ Processing of Student ID).
            for rtitle, ritem in rescue_by_title.items():
                if key in rtitle or rtitle in key:
                    rescued = ritem
                    break
        if rescued is None:
            continue
        cand = {
            "title": rescued.get("title") or title,
            "content": rescued.get("content") or "",
            "summary": "",
            "source_filename": filename or working_preview.get("source_filename"),
            "source_section": rescued.get("title") or title,
            "office": (rescued.get("service_fields") or {}).get("office"),
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "document_profile": "citizen_charter",
            "parser_used": "citizen_charter_extractor_v2",
            "formatter_used": "build_charter_article_body",
            "charter_candidate_bucket": bucket,
            "planner_bucket": bucket,
            "who_may_avail": (rescued.get("service_fields") or {}).get("who_may_avail"),
            "classification": (rescued.get("service_fields") or {}).get("classification"),
            "requirements": (rescued.get("service_fields") or {}).get("requirements") or [],
            "steps": (rescued.get("service_fields") or {}).get("steps") or [],
            "total_processing_time": (rescued.get("service_fields") or {}).get(
                "total_processing_time"
            ),
            "total_fees": (rescued.get("service_fields") or {}).get("total_fees"),
            "checklist_blank": bool((rescued.get("service_fields") or {}).get("checklist_blank")),
            "parser_debug": ((rescued.get("service") or {}).get("parser_debug") or {}),
            "original_bucket": rescued.get("original_bucket"),
            "repaired_bucket": rescued.get("repaired_bucket"),
            "rescue_attempted": rescued.get("rescue_attempted"),
            "rescue_successful": rescued.get("rescue_successful"),
            "rescue_reasons": list(rescued.get("rescue_reasons") or []),
            "repair_actions_applied": list(rescued.get("repair_actions_applied") or []),
            "remaining_blockers": list(rescued.get("remaining_blockers") or []),
            "semantic_validation_passed": rescued.get("semantic_validation_passed"),
            "final_body_validation_passed": rescued.get("final_body_validation_passed"),
            "needs_review_reasons": list(rescued.get("needs_review_reasons") or []),
            "charter_audience": rescued.get("audience"),
            "suggested_category": rescued.get("category"),
            "_preferred_category": rescued.get("category"),
            "public_priority_service": True,
            "blueprint_id": f"priority-visible:{key}",
        }
        preview_id = stable_preview_id(cand.get("blueprint_id"), fallback_key=key)
        item = _candidate_preview_dict(
            cand,
            quality=7.0 if bucket == "recommended" else 5.0,
            confidence=0.8,
            needs_review=bucket == "needs_review",
            reasons=list(rescued.get("needs_review_reasons") or rescued.get("remaining_blockers") or []),
            preview_id=preview_id,
            category=rescued.get("category") or "Student Services",
            db=db,
        )
        _apply_final_bucket(item, bucket, raw_bucket=bucket)
        by_title[key] = item
        added.append(item)
    if added:
        return list(all_candidates) + added
    return all_candidates


def _stamp_charter_profile_on_units(
    units: list[dict],
    profile: dict,
    *,
    min_signals: int = 2,
) -> list[dict]:
    """Stamp charter profile onto units that look like service blocks.

    Avoid promoting every handbook fragment into a charter candidate when rebuild
    cannot parse services — keep only blocks with service-structure signals.
    """
    stamped: list[dict] = []
    for unit in units:
        title = str(unit.get("title") or "")
        content = str(unit.get("content") or "")
        if is_artifact_charter_title(title):
            continue
        if min_signals > 0 and not looks_like_service_unit(title, content, min_signals=min_signals):
            continue
        item = dict(unit)
        metadata = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
        metadata.update(
            {
                "document_profile": "citizen_charter",
                "parser_document_type": "citizen_charter",
                "source_type": "Citizen's Charter",
                "document_type": "citizen_charter",
                "article_type": metadata.get("article_type") or "service_procedure",
                "parser_used": "citizen_charter_service_parser",
                "formatter_used": "build_charter_article_body",
                "detected_document_type": profile.get("detected_document_type") or "citizen_charter",
            }
        )
        if profile.get("admin_selected_document_type"):
            metadata["admin_selected_document_type"] = profile.get("admin_selected_document_type")
        item["metadata"] = metadata
        item["parser_document_type"] = "citizen_charter"
        item["source_type"] = "Citizen's Charter"
        item["document_type"] = "citizen_charter"
        item["document_profile"] = "citizen_charter"
        stamped.append(item)
    return stamped


def looks_like_service_unit(title: str, content: str, *, min_signals: int = 2) -> bool:
    blob = f"{title}\n{content}"
    if is_artifact_charter_title(title):
        return False
    signals = 0
    for pattern in (
        r"\bOffice\s*(?:or)?\s*/?\s*Division\b",
        r"\bWho\s+May\s+Avail\b",
        r"\bClassification\s*:",
        r"\bCLIENT\s+STEPS\b",
        r"\bChecklist\s+of\s+Requirements\b",
        r"\bProcessing\s+Time\b",
        r"\bPerson\s+Responsible\b",
        r"\bWhere\s+to\s+Secure\b",
    ):
        if re.search(pattern, blob, flags=re.I):
            signals += 1
    return signals >= max(1, int(min_signals))


def generate_candidates_from_preview(
    preview: dict,
    *,
    filename: str | None = None,
    max_candidates: int | None = None,
    save_mode: str = "preview_only",
) -> dict:
    """Generate article candidate previews from topic blueprints.

    ``save_mode=preview_only`` (default) returns unsaved preview candidates only.
    ``save_mode=save_drafts`` persists saveable candidates as unpublished drafts.
    Source knowledge_units in the preview are never modified or deleted.
    Candidates are generated from Article Planner blueprints, not one-per-chunk.
    """
    save_mode = (save_mode or "preview_only").strip().lower()
    persist_drafts = save_mode == "save_drafts"

    session_factory = get_session_factory()
    # Always open a read session for office_aliases matching when possible.
    session = None
    try:
        session = session_factory()
    except Exception:
        session = None

    write_session = session if persist_drafts else None
    recommended_candidates: list[dict] = []
    needs_review_candidates: list[dict] = []
    low_confidence_candidates: list[dict] = []
    skipped_duplicates: list[dict] = []
    overflow_candidates: list[dict] = []
    preview_candidates: list[dict] = []
    consolidated_parent_candidates: list[dict] = []
    saved_count = 0
    try:
        working_preview = dict(preview or {})
        profile = resolve_preview_document_profile(working_preview)
        parser_text = collect_charter_parser_text(working_preview, profile)
        profile["review_text"] = parser_text
        source_units = list(working_preview.get("knowledge_units") or [])
        original_unit_count = len(source_units)
        rebuilt_unit_count = 0
        charter_v2_used = False
        charter_v2_fallback_used = False
        charter_v2_fallback_reason: str | None = None
        generate_received_v2_count = 0
        if profile.get("is_charter"):
            # Citizen's Charter Extraction V2 structured services win over the
            # old flat-text rebuild whenever they are available — never plan
            # Citizen's Charter with handbook_policy units either way.
            incoming_v2 = working_preview.get("charter_v2_services")
            generate_received_v2_count = (
                len(incoming_v2) if isinstance(incoming_v2, list) else 0
            )
            preview_diagnostics = (
                working_preview.get("charter_v2_diagnostics")
                if isinstance(working_preview.get("charter_v2_diagnostics"), dict)
                else {}
            )
            v2_units = _build_charter_units_from_v2_services(
                working_preview,
                filename=filename,
                profile=profile,
            )
            if v2_units:
                source_units = v2_units
                rebuilt_unit_count = len(v2_units)
                charter_v2_used = True
                charter_v2_fallback_reason = None
            else:
                charter_v2_fallback_used = True
                # Prefer extract-time diagnostics; otherwise explain empty preview payload.
                charter_v2_fallback_reason = (
                    str(preview_diagnostics.get("fallback_reason") or "").strip()
                    or (
                        "preview_missing_charter_v2_services"
                        if generate_received_v2_count == 0
                        else "v2_services_present_but_unusable"
                    )
                )
                # If extract already ran V2 (pdf_pages present / v2_attempted) and
                # got zero services, V1 flat-text must not create Needs Review
                # article previews from fragments — diagnostic Low Quality /
                # RAG-only only.
                restrict_v1 = bool(preview_diagnostics.get("v2_attempted")) or (
                    bool(preview_diagnostics.get("pdf_pages_available"))
                    and generate_received_v2_count == 0
                )
                rebuilt = _rebuild_charter_units_from_preview(
                    working_preview,
                    filename=filename,
                    profile=profile,
                )
                if rebuilt and any(
                    str((unit.get("metadata") or {}).get("parser_document_type") or "").lower()
                    == "citizen_charter"
                    for unit in rebuilt
                ):
                    source_units = rebuilt
                    rebuilt_unit_count = len(rebuilt)
                else:
                    # Prefer service-looking units; never wipe to empty when text exists.
                    stamped = _stamp_charter_profile_on_units(source_units, profile, min_signals=2)
                    if not stamped:
                        stamped = _stamp_charter_profile_on_units(source_units, profile, min_signals=1)
                    if not stamped and source_units:
                        stamped = _stamp_charter_profile_on_units(source_units, profile, min_signals=0)
                    source_units = stamped
                    rebuilt_unit_count = 0
                if restrict_v1 and source_units:
                    source_units = _restrict_v1_fallback_units_to_diagnostic(
                        source_units,
                        reason=charter_v2_fallback_reason or "v2_fallback_restricted",
                    )
            working_preview["knowledge_units"] = source_units
            working_preview["charter_v2_used"] = charter_v2_used
            working_preview["charter_v2_fallback_used"] = charter_v2_fallback_used
            working_preview["document_profile"] = "citizen_charter"
            working_preview["document_type"] = "citizen_charter"
            working_preview["parser_document_type"] = "citizen_charter"
            working_preview["source_type"] = "Citizen's Charter"
            working_preview["review_text"] = parser_text
            # Keep generate-time diagnostics for the charter report.
            merged_diagnostics = dict(preview_diagnostics)
            merged_diagnostics["generate_received_charter_v2_services_count"] = generate_received_v2_count
            merged_diagnostics["preview_has_charter_v2_services"] = generate_received_v2_count > 0
            merged_diagnostics["preview_charter_v2_services_count"] = int(
                working_preview.get("charter_v2_detected_count") or generate_received_v2_count or 0
            )
            if charter_v2_fallback_reason:
                merged_diagnostics["fallback_reason"] = charter_v2_fallback_reason
            working_preview["charter_v2_diagnostics"] = merged_diagnostics
        charter_parser_used_value = (
            "citizen_charter_extractor_v2" if charter_v2_used else "citizen_charter_service_parser"
        )

        plan = plan_articles_from_units(source_units, db=session)
        tagged_units = plan["tagged_units"]
        blueprints = plan["blueprints"]
        seeds = plan["blueprint_seeds"]

        scored: list[tuple[dict, float, float, list[str]]] = []
        charter_artifact_rejects: list[str] = []
        charter_mixed_rejects: list[str] = []
        charter_fragment_rejects: list[str] = []
        for seed in seeds:
            candidate = _candidate_from_unit(seed, filename=filename)
            resolved_title, _ = resolve_student_facing_title(
                seed.get("canonical_topic") or seed.get("title") or candidate.get("title"),
                seed.get("hierarchy_path") or candidate.get("source_section"),
            )
            candidate["title"] = resolved_title
            # Carry planner metadata onto the candidate used for scoring/previews.
            candidate["article_type"] = seed.get("article_type") or candidate.get("document_type")
            candidate["parent_topic"] = seed.get("parent_topic")
            candidate["canonical_topic"] = resolved_title
            candidate["merged_unit_count"] = seed.get("merged_unit_count") or 1
            candidate["consolidated_parent"] = bool(seed.get("consolidated_parent"))
            candidate["merge_coherent"] = bool(seed.get("merge_coherent", True))
            candidate["source_sections"] = list(seed.get("source_sections") or [])
            if not candidate["source_sections"] and candidate.get("source_section"):
                candidate["source_sections"] = [str(candidate["source_section"])]
            candidate["blueprint_id"] = seed.get("blueprint_id")
            candidate["service_category"] = seed.get("service_category")
            # Preserve charter/extracted office; only clear when we will replace
            # from a confirmed office_aliases match.
            seed_meta_early = seed.get("metadata") if isinstance(seed.get("metadata"), dict) else {}
            charter_like = (
                profile.get("is_charter")
                or str(seed.get("parser_document_type") or "").lower()
                in {"citizen_charter", "service_process"}
                or str(seed.get("source_type") or "") in {"Citizen's Charter", "Service Process"}
            )
            if seed.get("office") and seed.get("office_match_confidence") is not None:
                candidate["office"] = seed.get("office")
                candidate["office_match_confidence"] = float(seed["office_match_confidence"])
            elif charter_like:
                candidate["office"] = (
                    candidate.get("office")
                    or seed.get("office")
                    or seed_meta_early.get("extracted_office")
                    or seed_meta_early.get("office_division")
                    or seed_meta_early.get("office")
                )
            else:
                candidate["office"] = None
                candidate.pop("office_match_confidence", None)
            candidate["student_intents"] = seed.get("student_intents") or []
            candidate["charter_audience"] = seed.get("charter_audience") or candidate.get(
                "charter_audience"
            )
            candidate["suggested_category"] = seed.get("suggested_category") or candidate.get(
                "suggested_category"
            )
            candidate["charter_candidate_bucket"] = seed.get("charter_candidate_bucket") or candidate.get(
                "charter_candidate_bucket"
            )
            candidate["charter_completeness"] = seed.get("charter_completeness") or candidate.get(
                "charter_completeness"
            )
            candidate["parser_document_type"] = seed.get("parser_document_type") or candidate.get(
                "parser_document_type"
            )
            candidate["source_type"] = seed.get("source_type") or candidate.get("source_type")
            candidate["needs_review_hint"] = seed.get("needs_review_hint") or candidate.get(
                "needs_review_hint"
            )
            for rescue_key in (
                "original_bucket",
                "repaired_bucket",
                "rescue_attempted",
                "rescue_successful",
                "rescue_reasons",
                "repair_actions_applied",
                "remaining_blockers",
                "semantic_validation_passed",
                "final_body_validation_passed",
                "needs_review_reasons",
                "low_quality_rescue_attempted",
                "low_quality_rescue_successful",
            ):
                if seed.get(rescue_key) is not None:
                    candidate[rescue_key] = seed.get(rescue_key)
                elif (seed.get("metadata") or {}).get(rescue_key) is not None:
                    candidate[rescue_key] = (seed.get("metadata") or {}).get(rescue_key)
            # Persist repaired structured fields onto the candidate for body rebuild.
            seed_meta = seed.get("metadata") if isinstance(seed.get("metadata"), dict) else {}
            for field_key, meta_key in (
                ("requirements", "extracted_requirements"),
                ("steps", "extracted_steps"),
                ("total_processing_time", "total_processing_time"),
                ("total_fees", "total_fees"),
                ("who_may_avail", "who_may_avail"),
                ("classification", "classification"),
                ("parser_debug", "parser_debug"),
            ):
                if candidate.get(field_key) is None and seed_meta.get(meta_key) is not None:
                    candidate[field_key] = seed_meta.get(meta_key)
                if candidate.get(field_key) is None and seed.get(field_key) is not None:
                    candidate[field_key] = seed.get(field_key)
            if profile.get("is_charter"):
                candidate["document_type"] = "citizen_charter"
                candidate["article_type"] = "service_procedure"
                candidate["parser_document_type"] = "citizen_charter"
                candidate["source_type"] = "Citizen's Charter"
                candidate["document_profile"] = "citizen_charter"
                candidate["parser_used"] = (
                    "citizen_charter_extractor_v2"
                    if charter_v2_used
                    else "citizen_charter_service_parser"
                )
                candidate["formatter_used"] = "build_charter_article_body"
                candidate["detected_document_type"] = profile.get("detected_document_type")
                candidate["admin_selected_document_type"] = profile.get(
                    "admin_selected_document_type"
                )

            classification = classify_chunk(
                _candidate_classification_text(candidate),
                title=candidate.get("title"),
            )
            confidence = float(classification.confidence or 0.0)
            quality, reasons = _score_candidate(candidate, seed, confidence)
            if _is_unpublishable_title(resolved_title):
                reasons.append("generic_title_unresolved")
            if candidate.get("consolidated_parent") and not candidate.get("merge_coherent", True):
                candidate["consolidated_parent"] = False
                reasons.append("incoherent_parent_merge")
            if int(candidate.get("merged_unit_count") or 1) >= 3 and candidate.get("merge_coherent", True):
                quality += 0.5

            title_text = str(candidate.get("title") or resolved_title or "")
            # Drop obvious artifacts even when charter metadata is missing.
            if is_artifact_charter_title(title_text) or should_reject_charter_article_candidate(
                title=title_text,
                source_section=str(candidate.get("source_section") or ""),
                parent_topic=str(candidate.get("parent_topic") or seed.get("parent_topic") or ""),
                hierarchy_path=str(
                    candidate.get("source_section") or seed.get("hierarchy_path") or ""
                ),
            ):
                # Only hard-skip when charter profile OR the title itself is an artifact label.
                is_charter_meta = (
                    profile.get("is_charter")
                    or str(candidate.get("parser_document_type") or "").lower()
                    in {"citizen_charter", "service_process"}
                    or str(candidate.get("source_type") or "")
                    in {"Citizen's Charter", "Service Process"}
                    or is_charter_or_service_process_unit(candidate)
                    or is_charter_or_service_process_unit(seed)
                )
                if is_charter_meta or is_artifact_charter_title(title_text):
                    charter_artifact_rejects.append(title_text)
                    continue

            # Citizen's Charter routing: student-facing vs internal/admin services.
            is_charter = bool(profile.get("is_charter")) or (
                str(candidate.get("parser_document_type") or "").lower() == "citizen_charter"
                or str(candidate.get("source_type") or "") == "Citizen's Charter"
                or is_charter_or_service_process_unit(candidate)
                or is_charter_or_service_process_unit(seed)
            )
            if is_charter:
                # Hard-drop artifact titles / artifact source paths before any preview bucket.
                if should_reject_charter_article_candidate(
                    title=title_text,
                    source_section=str(candidate.get("source_section") or ""),
                    parent_topic=str(candidate.get("parent_topic") or seed.get("parent_topic") or ""),
                    hierarchy_path=str(
                        candidate.get("source_section") or seed.get("hierarchy_path") or ""
                    ),
                    office=str(candidate.get("office") or ""),
                    who_may_avail=str(candidate.get("who_may_avail") or ""),
                ):
                    charter_artifact_rejects.append(title_text)
                    continue
                if is_artifact_charter_title(title_text):
                    charter_artifact_rejects.append(title_text)
                    continue
                if is_charter_field_label_or_fragment_title(title_text):
                    # Suppress table-row / OCR crumbs as separate article candidates.
                    charter_fragment_rejects.append(title_text)
                    continue
                # Consolidated parents that are artifact groups never become publishable.
                if candidate.get("consolidated_parent") and should_reject_charter_article_candidate(
                    title=title_text,
                    source_section=str(candidate.get("source_section") or ""),
                    parent_topic=str(candidate.get("parent_topic") or ""),
                ):
                    candidate["consolidated_parent"] = False
                    charter_artifact_rejects.append(title_text)
                    continue

                service_fields = {
                    "office": candidate.get("office")
                    or (candidate.get("metadata") or {}).get("extracted_office")
                    or (candidate.get("metadata") or {}).get("office_division")
                    or (candidate.get("metadata") or {}).get("office")
                    or (
                        (candidate.get("parser_debug") or {}).get("detected_office")
                        if isinstance(candidate.get("parser_debug"), dict)
                        else None
                    )
                    or (
                        ((candidate.get("metadata") or {}).get("parser_debug") or {}).get(
                            "detected_office"
                        )
                        if isinstance((candidate.get("metadata") or {}).get("parser_debug"), dict)
                        else None
                    )
                    or seed.get("office"),
                    "who_may_avail": candidate.get("who_may_avail")
                    or (candidate.get("metadata") or {}).get("who_may_avail"),
                    "classification": candidate.get("classification")
                    or (candidate.get("metadata") or {}).get("classification"),
                    "transaction_type": candidate.get("transaction_type")
                    or (candidate.get("metadata") or {}).get("transaction_type"),
                    "checklist_blank": bool(
                        candidate.get("checklist_blank")
                        or (candidate.get("metadata") or {}).get("checklist_blank")
                    ),
                    "requirements": candidate.get("requirements")
                    or (candidate.get("metadata") or {}).get("extracted_requirements")
                    or [],
                    "steps": candidate.get("steps")
                    or (candidate.get("metadata") or {}).get("extracted_steps")
                    or [],
                    "total_processing_time": candidate.get("total_processing_time")
                    or (candidate.get("metadata") or {}).get("total_processing_time"),
                    "total_fees": candidate.get("total_fees")
                    or (candidate.get("metadata") or {}).get("total_fees"),
                    "page": candidate.get("page") or (candidate.get("metadata") or {}).get("page"),
                    "document_title": candidate.get("document_title")
                    or (candidate.get("metadata") or {}).get("document_title"),
                    "parser_debug": candidate.get("parser_debug")
                    or (candidate.get("metadata") or {}).get("parser_debug")
                    or {},
                }
                # Never pass placeholder office into the student-facing body.
                if str(service_fields.get("office") or "").strip() in {
                    "",
                    "[NEEDS REVIEW]",
                    "Not specified",
                }:
                    service_fields["office"] = None
                if isinstance(service_fields["requirements"], str):
                    try:
                        service_fields["requirements"] = json.loads(service_fields["requirements"])
                    except Exception:
                        service_fields["requirements"] = []
                if isinstance(service_fields["steps"], str):
                    try:
                        service_fields["steps"] = json.loads(service_fields["steps"])
                    except Exception:
                        service_fields["steps"] = []

                # Rebuild body only from structured service fields — never handbook formatter.
                candidate["content"] = build_charter_article_body(
                    title=title_text,
                    service=service_fields,
                    source_document=str(candidate.get("source_filename") or filename or ""),
                )
                candidate["official_source_excerpt"] = candidate["content"]
                candidate["document_type"] = "citizen_charter"
                candidate["article_type"] = "service_procedure"
                candidate["parser_document_type"] = "citizen_charter"
                candidate["source_type"] = "Citizen's Charter"
                candidate["formatter_used"] = "build_charter_article_body"
                candidate["parser_used"] = (
                    "citizen_charter_extractor_v2"
                    if charter_v2_used
                    else "citizen_charter_service_parser"
                )
                candidate["requirements"] = service_fields.get("requirements") or []
                candidate["steps"] = service_fields.get("steps") or []
                candidate["who_may_avail"] = service_fields.get("who_may_avail")
                candidate["classification"] = service_fields.get("classification")
                candidate["total_processing_time"] = service_fields.get("total_processing_time")
                candidate["total_fees"] = service_fields.get("total_fees")
                candidate["parser_debug"] = (
                    candidate.get("parser_debug")
                    or (candidate.get("metadata") or {}).get("parser_debug")
                )
                # Prefer extracted office text for routing even when office_aliases has no match.
                if _filled_office(service_fields.get("office")) and not candidate.get("office"):
                    candidate["office"] = service_fields.get("office")

                # Re-validate after body rebuild so repaired fields actually gate Recommended.
                from app.services.citizen_charter_rescue import (
                    validate_charter_candidate_for_recommended,
                )

                semantic_ok, semantic_blockers = validate_charter_candidate_for_recommended(
                    {
                        **candidate,
                        "requirements": service_fields.get("requirements") or [],
                        "steps": service_fields.get("steps") or [],
                        "content": candidate.get("content"),
                        "parser_debug": candidate.get("parser_debug"),
                    }
                )
                candidate["semantic_validation_passed"] = semantic_ok
                candidate["final_body_validation_passed"] = semantic_ok
                if semantic_blockers:
                    candidate["remaining_blockers"] = list(semantic_blockers)
                    for flag in semantic_blockers:
                        if flag not in reasons:
                            reasons.append(flag)
                if not semantic_ok:
                    prior_bucket = str(
                        candidate.get("charter_candidate_bucket")
                        or seed.get("charter_candidate_bucket")
                        or "needs_review"
                    ).strip().lower()
                    if prior_bucket == "recommended":
                        candidate["charter_candidate_bucket"] = "needs_review"
                        candidate["bucket_reason"] = "semantic_validation_failed"

                mixed = has_mixed_charter_services(
                    title=title_text,
                    text=str(candidate.get("content") or ""),
                )
                # Only inspect raw seed when structured fields were empty (fallback path).
                if not service_fields.get("requirements") and not service_fields.get("steps"):
                    mixed = mixed or has_mixed_charter_services(
                        title=title_text,
                        text=str(seed.get("content") or ""),
                    )
                if mixed:
                    reasons.append("mixed_charter_services")
                    charter_mixed_rejects.append(title_text)
                    quality = min(quality, 2.0)
                if not charter_body_has_required_sections(str(candidate.get("content") or "")):
                    reasons.append("invalid_charter_service_block")
                    quality = min(quality, 2.0)
                if looks_like_truncated_charter_title(title_text):
                    reasons.append("truncated_charter_title")
                    quality = min(quality, 2.0)

                suggested = str(candidate.get("suggested_category") or "").strip()
                if suggested:
                    candidate["_preferred_category"] = suggested
                    confidence = max(confidence, 0.78)
                if confidence < 0.35:
                    reasons.append("low_category_confidence_severe")

                # Drop handbook-noise reasons that incorrectly force Needs Review.
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in CHARTER_NON_BLOCKING_REVIEW_FLAGS
                ]

                if charter_v2_used:
                    decision = decide_charter_bucket_for_v2(
                        title=title_text,
                        service=service_fields,
                        audience=str(candidate.get("charter_audience") or "").strip().lower() or None,
                        text=str(candidate.get("content") or ""),
                        category=suggested or None,
                        review_reasons=reasons,
                        extraction_quality=str(candidate.get("extraction_quality") or "needs_review"),
                    )
                else:
                    decision = decide_charter_bucket(
                        title=title_text,
                        service=service_fields,
                        audience=str(candidate.get("charter_audience") or "").strip().lower() or None,
                        text=str(candidate.get("content") or ""),
                        category=suggested or None,
                        review_reasons=reasons,
                        formatter_used="build_charter_article_body",
                        parser_used="citizen_charter_service_parser",
                    )
                charter_bucket = str(decision.get("bucket") or "needs_review")
                # V1 fallback after a failed V2 attempt must stay diagnostic-only.
                seed_meta = seed.get("metadata") if isinstance(seed.get("metadata"), dict) else {}
                cand_meta = (
                    candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
                )
                if seed_meta.get("v2_fallback_restricted") or cand_meta.get("v2_fallback_restricted"):
                    prior = str(
                        seed.get("charter_candidate_bucket")
                        or seed_meta.get("charter_candidate_bucket")
                        or cand_meta.get("charter_candidate_bucket")
                        or "low_quality"
                    ).strip().lower()
                    if prior not in {"low_quality", "rag_only"}:
                        prior = "low_quality"
                    if charter_bucket in {"recommended", "needs_review", "consolidated_parent"}:
                        charter_bucket = prior
                        decision = dict(decision)
                        decision["bucket"] = prior
                        decision["bucket_reason"] = (
                            seed_meta.get("bucket_reason")
                            or cand_meta.get("bucket_reason")
                            or "v2_fallback_restricted"
                        )
                candidate["charter_candidate_bucket"] = charter_bucket
                candidate["charter_audience"] = decision.get("charter_audience")
                candidate["student_facing_score"] = decision.get("student_facing_score") or 0
                candidate["internal_admin_score"] = decision.get("internal_admin_score") or 0
                candidate["bucket_reason"] = decision.get("bucket_reason")
                candidate["blocking_review_flags"] = list(decision.get("blocking_review_flags") or [])
                for flag in candidate["blocking_review_flags"]:
                    if flag not in reasons:
                        reasons.append(flag)
                if charter_bucket == "recommended":
                    reasons = _filter_charter_review_reasons(reasons)
                elif charter_bucket == "needs_review":
                    reason_key = str(decision.get("bucket_reason") or "uncertain_audience")
                    if reason_key == "internal_admin_heavy":
                        if "internal_admin_service" not in reasons:
                            reasons.append("internal_admin_service")
                    elif reason_key not in reasons:
                        reasons.append(reason_key)
                elif charter_bucket == "low_quality":
                    if "incomplete_charter_service" not in reasons and "mixed_charter_services" not in reasons:
                        if "invalid_charter_service_block" not in reasons:
                            reasons.append(str(decision.get("bucket_reason") or "incomplete_charter_service"))
                # uncertain_office is informational only for charter (non-blocking).
                office_text = service_fields.get("office") or candidate.get("office")
                if not _filled_office(office_text) and "uncertain_office" not in reasons:
                    reasons.append("uncertain_office")
                if candidate.get("steps") or "Client Step:" in str(candidate.get("content") or ""):
                    quality += 1.0
                if charter_bucket in {"low_quality", "rag_only"}:
                    quality = min(quality, 2.4)
                # Soft boost so clean charter services clear the soft quality floor.
                if charter_bucket == "recommended":
                    quality = max(quality, 4.0)

            scored.append((candidate, confidence, quality, reasons))

        scored.sort(key=lambda item: item[2], reverse=True)

        for cand, conf, quality, reasons in scored:
            title = cand.get("title") or ""
            preferred = str(cand.get("_preferred_category") or "").strip()
            category = preferred or (
                classify_chunk(
                    _candidate_classification_text(cand),
                    title=title,
                ).category
                or "General Information"
            )
            is_charter = _is_charter_preview(cand)
            if is_charter:
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in CHARTER_NON_BLOCKING_REVIEW_FLAGS
                    or reason == "uncertain_office"
                ]
                charter_bucket = str(cand.get("charter_candidate_bucket") or "").strip().lower()
                needs_review = charter_bucket == "needs_review"
                # uncertain_office alone must not force Needs Review for clean student services.
                if needs_review and set(reasons) <= {"uncertain_office"} and charter_bucket == "recommended":
                    needs_review = False
            else:
                needs_review = _candidate_needs_review(
                    quality,
                    conf,
                    reasons,
                    doc_type=str(cand.get("document_type") or "information"),
                )
            if is_charter and any(
                reason in reasons
                for reason in (
                    "internal_admin_service",
                    "ambiguous_service_audience",
                    "charter_needs_review",
                    "internal_admin_heavy",
                    "uncertain_audience",
                )
            ):
                needs_review = True
            if any(
                reason in reasons
                for reason in (
                    "incomplete_charter_service",
                    "charter_artifact_title",
                    "mixed_charter_services",
                    "invalid_charter_service_block",
                    "truncated_charter_title",
                    "missing_required_charter_fields",
                )
            ):
                cand["planner_bucket"] = "low_quality"
                needs_review = False
                preview_id = stable_preview_id(
                    cand.get("blueprint_id"),
                    fallback_key=str(cand.get("title") or ""),
                )
                low_confidence_candidates.append(
                    _candidate_preview_dict(
                        cand,
                        quality=quality,
                        confidence=conf,
                        needs_review=needs_review,
                        reasons=reasons,
                        preview_id=preview_id,
                        category=category,
                        db=session,
                    )
                )
                continue
            if is_charter and str(cand.get("charter_candidate_bucket") or "") == "recommended":
                cand["planner_bucket"] = "recommended"
                needs_review = False
            elif is_charter and str(cand.get("charter_candidate_bucket") or "") == "needs_review":
                cand["planner_bucket"] = "needs_review"
                needs_review = True
            if not _is_saveable_candidate(cand, quality) or _is_unpublishable_title(title):
                cand["planner_bucket"] = "low_quality"
                needs_review = False
                preview_id = stable_preview_id(
                    cand.get("blueprint_id"),
                    fallback_key=str(cand.get("title") or ""),
                )
                low_confidence_candidates.append(
                    _candidate_preview_dict(
                        cand,
                        quality=quality,
                        confidence=conf,
                        needs_review=needs_review,
                        reasons=reasons,
                        preview_id=preview_id,
                        category=category,
                        db=session,
                    )
                )
                continue

            if persist_drafts:
                if write_session is None:
                    continue
                if find_similar_article(
                    write_session,
                    title=title,
                    source_filename=cand.get("source_filename"),
                ) is not None:
                    skipped_duplicates.append(
                        _candidate_summary(
                            cand,
                            quality=quality,
                            confidence=conf,
                            needs_review=False,
                            reasons=["duplicate_existing"],
                            category=category,
                        )
                    )
                    continue

                art = _create_draft_article(
                    write_session,
                    cand,
                    quality=quality,
                    confidence=conf,
                    needs_review=needs_review,
                    reasons=reasons,
                )
                saved = _candidate_summary(
                    cand,
                    quality=quality,
                    confidence=conf,
                    needs_review=needs_review,
                    reasons=reasons,
                    article_id=art.id,
                    category=art.category,
                )
                saved["category"] = art.category
                saved["parent_topic"] = cand.get("parent_topic")
                saved["canonical_topic"] = cand.get("canonical_topic")
                saved["merged_unit_count"] = cand.get("merged_unit_count") or 1
                saved["article_type"] = cand.get("article_type")
                saved["planner_bucket"] = _resolve_planner_bucket(
                    cand,
                    quality=quality,
                    needs_review=needs_review,
                    reasons=reasons,
                )
                preview_candidates.append(saved)
                saved_count += 1
            else:
                cand["planner_bucket"] = _resolve_planner_bucket(
                    cand,
                    quality=quality,
                    needs_review=needs_review,
                    reasons=reasons,
                )
                if cand["planner_bucket"] == "low_quality":
                    needs_review = False
                preview_id = stable_preview_id(
                    cand.get("blueprint_id"),
                    fallback_key=str(cand.get("title") or ""),
                )
                item = _candidate_preview_dict(
                    cand,
                    quality=quality,
                    confidence=conf,
                    needs_review=needs_review,
                    reasons=reasons,
                    preview_id=preview_id,
                    category=category,
                    db=session,
                )
                preview_candidates.append(item)

        recommended_candidates, needs_review_candidates, consolidated_parent_candidates = (
            _finalize_planner_buckets(preview_candidates, max_candidates=max_candidates)
        )
        # Re-apply published-match flags after finalize so Already Published sticks.
        for item in preview_candidates:
            if item.get("existing_article_id") or item.get("already_published"):
                _preserve_published_match_flags(item)
            else:
                _annotate_existing_article_match(item, db=session)
        recommended_ids = {item.get("id") for item in recommended_candidates}
        overflow_candidates = [
            item
            for item in preview_candidates
            if item.get("id") not in recommended_ids
            and item.get("planner_bucket") not in {"consolidated_parent", "low_quality", "needs_review"}
        ]

        all_candidates = list(preview_candidates) + list(low_confidence_candidates)
        for item in all_candidates:
            if not item.get("final_bucket"):
                target = _canonical_final_bucket(item)
                _apply_final_bucket(
                    item,
                    target,
                    raw_bucket=str(item.get("raw_bucket") or item.get("planner_bucket") or "pending"),
                )
        if profile.get("is_charter") or working_preview.get("_charter_rescue_results"):
            all_candidates = _ensure_public_priority_candidates_visible(
                all_candidates=all_candidates,
                working_preview=working_preview,
                filename=filename,
                db=session,
            )
            # Re-annotate matches for any newly injected priority cards.
            for item in all_candidates:
                if item.get("existing_article_id") or item.get("already_published"):
                    _preserve_published_match_flags(item)
                else:
                    _annotate_existing_article_match(item, db=session)
        grouped_candidates = group_candidates_for_review(all_candidates, db=session)
        coverage = build_coverage_report(tagged_units, blueprints, preview_candidates)
        coverage_counts = {
            "generated": sum(1 for item in coverage if item.get("status") == "generated"),
            "merged_parent": sum(1 for item in coverage if item.get("status") == "merged_parent"),
            "needs_review": sum(1 for item in coverage if item.get("status") == "needs_review"),
            "needs_cleanup": sum(1 for item in coverage if item.get("status") == "needs_cleanup"),
            "rag_only": sum(1 for item in coverage if item.get("status") == "rag_only"),
        }

        charter_units = [
            unit
            for unit in tagged_units
            if str(unit.get("parser_document_type") or (unit.get("metadata") or {}).get("parser_document_type") or "")
            .lower()
            == "citizen_charter"
            or str(unit.get("source_type") or (unit.get("metadata") or {}).get("source_type") or "")
            == "Citizen's Charter"
        ]
        charter_report = None
        if charter_units:
            meta0 = charter_units[0].get("metadata") or {}
            dropped_noise = max(
                int((unit.get("metadata") or {}).get("charter_dropped_noise") or unit.get("charter_dropped_noise") or 0)
                for unit in charter_units
            )
            merged_from_meta = max(
                int((unit.get("metadata") or {}).get("charter_merged_splits") or unit.get("charter_merged_splits") or 0)
                for unit in charter_units
            )
            merged_split = merged_from_meta or sum(
                max(
                    0,
                    int(
                        (unit.get("metadata") or {}).get("charter_parts_merged")
                        or unit.get("charter_parts_merged")
                        or 1
                    )
                    - 1,
                )
                for unit in charter_units
            )
            detected = int(meta0.get("charter_detected_blocks") or 0) or (
                len(charter_units) + merged_split + dropped_noise
            )
            low_quality_artifacts = dropped_noise + sum(
                1
                for unit in charter_units
                if str(
                    unit.get("charter_candidate_bucket")
                    or (unit.get("metadata") or {}).get("charter_candidate_bucket")
                    or ""
                )
                == "low_quality"
                or str(unit.get("needs_review_hint") or "") == "incomplete_charter_service"
                or is_noise_service_title(str(unit.get("title") or ""))
            )
            rejected_artifacts = len(charter_artifact_rejects) + sum(
                1
                for unit in charter_units
                if is_artifact_charter_title(str(unit.get("title") or ""))
            )
            rejected_mixed = len(charter_mixed_rejects) + sum(
                1
                for unit in charter_units
                if str(unit.get("needs_review_hint") or "") == "mixed_charter_services"
                or has_mixed_charter_services(
                    title=str(unit.get("title") or ""),
                    text=str(unit.get("content") or ""),
                )
            )
            rag_only_refs = sum(
                1
                for unit in charter_units
                if str(unit.get("planner_bucket") or "") == "rag_only"
                or str(
                    unit.get("charter_candidate_bucket")
                    or (unit.get("metadata") or {}).get("charter_candidate_bucket")
                    or ""
                )
                == "rag_only"
            )
            # Recommended / needs-review counts for charter titles only.
            charter_titles = {
                str(unit.get("title") or "").strip().casefold()
                for unit in charter_units
                if str(unit.get("title") or "").strip()
            }

            def _is_charter_candidate(item: dict) -> bool:
                title = str(item.get("title") or "").strip().casefold()
                return (
                    str(item.get("parser_document_type") or "").lower() == "citizen_charter"
                    or str(item.get("source_type") or "") == "Citizen's Charter"
                    or title in charter_titles
                )

            # Keep report Recommended aligned with UI Recommended Articles section.
            recommended_charter = len(recommended_candidates)
            needs_review_charter = sum(
                1
                for item in all_candidates
                if item.get("final_bucket") == "needs_review"
                and not _is_charter_artifact_preview(item)
            )
            low_quality_charter = sum(
                1
                for item in all_candidates
                if item.get("final_bucket") == "low_quality"
            )
            rag_only_charter = sum(
                1
                for item in all_candidates
                if item.get("final_bucket") == "rag_only"
            ) + rag_only_refs
            valid_blocks = recommended_charter + needs_review_charter + low_quality_charter
            rejected_incomplete = sum(
                1
                for unit in tagged_units
                if str(unit.get("needs_review_hint") or "") == "incomplete_charter_service"
                or str(
                    unit.get("charter_candidate_bucket")
                    or (unit.get("metadata") or {}).get("charter_candidate_bucket")
                    or ""
                )
                == "low_quality"
            )
            mismatch_corrected = sum(
                1 for item in all_candidates if item.get("_bucket_mismatch_corrected")
            )
            blocked_publish = sum(
                1
                for item in all_candidates
                if _is_charter_candidate(item) and not item.get("publish_allowed", False)
            )

            v2_service_list = working_preview.get("charter_v2_services")
            v2_service_list = v2_service_list if isinstance(v2_service_list, list) else []
            v2_parser_strategy_counts: dict[str, int] = {}
            for v2_service in v2_service_list:
                if not isinstance(v2_service, dict):
                    continue
                strategy = str(
                    (v2_service.get("parser_debug") or {}).get("parser_strategy_used") or ""
                ).strip()
                if strategy:
                    v2_parser_strategy_counts[strategy] = v2_parser_strategy_counts.get(strategy, 0) + 1

            rescue_summary = (
                working_preview.get("_charter_rescue_summary")
                if isinstance(working_preview.get("_charter_rescue_summary"), dict)
                else {}
            )
            charter_report = build_charter_generation_report(
                detected_service_blocks=detected if detected else rebuilt_unit_count or len(charter_units),
                merged_split_services=merged_split,
                recommended_services=recommended_charter,
                needs_review_services=needs_review_charter,
                low_quality_artifacts=low_quality_charter,
                rag_only_references=rag_only_charter,
                rejected_artifact_headings=rejected_artifacts,
                rejected_mixed_service_blocks=rejected_mixed,
                rejected_incomplete_blocks=rejected_incomplete,
                valid_service_blocks=valid_blocks,
                document_profile=str(profile.get("document_profile") or "citizen_charter"),
                parser_used=(
                    "citizen_charter_extractor_v2"
                    if charter_v2_used
                    else "citizen_charter_service_parser"
                ),
                review_text_length=len(parser_text or ""),
                knowledge_units_count=original_unit_count,
                generated_article_candidates=len(all_candidates),
                final_recommended_count=recommended_charter,
                final_needs_review_count=needs_review_charter,
                final_low_quality_count=low_quality_charter,
                final_rag_only_count=rag_only_charter,
                rejected_fragment_title_count=len(charter_fragment_rejects),
                bucket_mismatch_corrected_count=mismatch_corrected,
                candidates_blocked_from_publish=blocked_publish,
                v2_used=charter_v2_used,
                v2_services_detected=int(working_preview.get("charter_v2_detected_count") or 0),
                v2_clean_count=int(working_preview.get("charter_v2_clean_count") or 0),
                v2_needs_review_count=int(working_preview.get("charter_v2_needs_review_count") or 0),
                v2_low_quality_count=int(working_preview.get("charter_v2_low_quality_count") or 0),
                v2_rag_only_count=int(working_preview.get("charter_v2_rag_only_count") or 0),
                v2_fallback_used=charter_v2_fallback_used,
                v2_parser_strategy_counts=v2_parser_strategy_counts,
                v2_attempted=bool(
                    (working_preview.get("charter_v2_diagnostics") or {}).get("v2_attempted")
                ),
                pdf_pages_available=bool(
                    (working_preview.get("charter_v2_diagnostics") or {}).get("pdf_pages_available")
                ),
                pdf_pages_count=int(
                    (working_preview.get("charter_v2_diagnostics") or {}).get("pdf_pages_count") or 0
                ),
                pages_with_words_count=int(
                    (working_preview.get("charter_v2_diagnostics") or {}).get(
                        "pages_with_words_count"
                    )
                    or 0
                ),
                total_words_count=int(
                    (working_preview.get("charter_v2_diagnostics") or {}).get("total_words_count")
                    or 0
                ),
                preview_has_charter_v2_services=bool(
                    (working_preview.get("charter_v2_diagnostics") or {}).get(
                        "preview_has_charter_v2_services"
                    )
                ),
                preview_charter_v2_services_count=int(
                    (working_preview.get("charter_v2_diagnostics") or {}).get(
                        "preview_charter_v2_services_count"
                    )
                    or working_preview.get("charter_v2_detected_count")
                    or 0
                ),
                generate_received_charter_v2_services_count=int(
                    (working_preview.get("charter_v2_diagnostics") or {}).get(
                        "generate_received_charter_v2_services_count"
                    )
                    or 0
                ),
                v2_error_message=(
                    (working_preview.get("charter_v2_diagnostics") or {}).get("v2_error_message")
                ),
                fallback_reason=(
                    (working_preview.get("charter_v2_diagnostics") or {}).get("fallback_reason")
                    or charter_v2_fallback_reason
                ),
                rescue_attempted=int(rescue_summary.get("rescue_attempted") or 0),
                rescue_successful=int(rescue_summary.get("rescue_successful") or 0),
                promoted_to_recommended_after_repair=int(
                    rescue_summary.get("promoted_to_recommended_after_repair") or 0
                ),
                downgraded_after_semantic_validation=int(
                    rescue_summary.get("downgraded_after_semantic_validation") or 0
                ),
                internal_services_kept_as_needs_review_or_rag_only=int(
                    rescue_summary.get("internal_services_kept_as_needs_review_or_rag_only") or 0
                ),
                true_low_quality_fragments=int(
                    rescue_summary.get("true_low_quality_fragments") or 0
                ),
                repaired_but_not_promoted=int(
                    rescue_summary.get("repaired_but_not_promoted") or 0
                ),
                repair_failed=int(rescue_summary.get("repair_failed") or 0),
                semantic_validation_failed=int(
                    rescue_summary.get("semantic_validation_failed") or 0
                ),
                recommended_blocked_by_semantic_validation=int(
                    rescue_summary.get("recommended_blocked_by_semantic_validation") or 0
                ),
                low_quality_rescue_attempted=int(
                    rescue_summary.get("low_quality_repair_attempted")
                    or rescue_summary.get("low_quality_rescue_attempted")
                    or 0
                ),
                low_quality_rescue_successful=int(
                    rescue_summary.get("low_quality_rescue_successful") or 0
                ),
                low_quality_repair_attempted=int(
                    rescue_summary.get("low_quality_repair_attempted")
                    or rescue_summary.get("low_quality_rescue_attempted")
                    or 0
                ),
                low_quality_repair_changed_fields=int(
                    rescue_summary.get("low_quality_repair_changed_fields") or 0
                ),
                low_quality_rescued_to_needs_review=int(
                    rescue_summary.get("low_quality_rescued_to_needs_review") or 0
                ),
                low_quality_rescued_to_recommended=int(
                    rescue_summary.get("low_quality_rescued_to_recommended") or 0
                ),
                low_quality_repair_failed=int(
                    rescue_summary.get("low_quality_repair_failed") or 0
                ),
                public_priority_found=int(rescue_summary.get("public_priority_found") or 0),
                public_priority_recommended=int(
                    rescue_summary.get("public_priority_recommended") or 0
                ),
                public_priority_needs_review=int(
                    rescue_summary.get("public_priority_needs_review") or 0
                ),
                public_priority_low_quality=int(
                    rescue_summary.get("public_priority_low_quality") or 0
                ),
                public_priority_repaired=int(
                    rescue_summary.get("public_priority_repaired") or 0
                ),
                public_priority_blocked_by_article_body=int(
                    rescue_summary.get("public_priority_blocked_by_article_body") or 0
                ),
                priority_service_diagnostics=list(
                    rescue_summary.get("priority_service_diagnostics") or []
                ),
            )

        return {
            "total_detected": len(tagged_units),
            "blueprint_count": len(blueprints),
            "article_eligible_count": plan["article_eligible_count"],
            "rag_only_count": plan["rag_only_count"],
            "recommended_count": len(recommended_candidates),
            "overflow_count": len(overflow_candidates),
            "skipped_low_quality_count": len(low_confidence_candidates),
            "skipped_duplicate_count": len(skipped_duplicates),
            "needs_review_count": len(needs_review_candidates),
            "consolidated_parent_count": len(consolidated_parent_candidates),
            "recommended_candidates": recommended_candidates,
            "needs_review_candidates": needs_review_candidates,
            "low_confidence_candidates": low_confidence_candidates,
            "consolidated_parent_candidates": consolidated_parent_candidates,
            "skipped_duplicates": skipped_duplicates,
            "overflow_candidates": overflow_candidates,
            "all_candidates": all_candidates,
            "grouped_candidates": grouped_candidates,
            "coverage": coverage,
            "coverage_counts": coverage_counts,
            "charter_report": charter_report,
            "blueprints": blueprints,
            "created_count": len(preview_candidates),
            "preview_count": len(all_candidates),
            "saved_count": saved_count,
            "save_mode": save_mode,
            "skipped_duplicate": len(skipped_duplicates),
            "skipped": len(skipped_duplicates),
            "skipped_low_quality": len(low_confidence_candidates),
            "created": recommended_candidates,
        }
    finally:
        if session is not None:
            session.close()


def generate_candidates_from_upload(file_bytes: bytes, *, filename: str | None = None, document_type: str | None = None, preview_file_path: str | None = None, max_candidates: int | None = None, save_mode: str = "preview_only") -> dict:
    preview = extract_document_preview(file_bytes, filename=filename, document_type=document_type, preview_file_path=preview_file_path)
    return generate_candidates_from_preview(preview, filename=filename, max_candidates=max_candidates, save_mode=save_mode)

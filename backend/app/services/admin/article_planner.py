"""Article Planner: tag knowledge units, build topic blueprints, coverage.

Knowledge units remain for RAG. Article candidates are generated from
blueprints (parent_topic + canonical_topic), not from every chunk.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.services.office_matcher import match_office_from_text
from app.services.citizen_charter_services import (
    classify_charter_candidate_bucket,
    classify_charter_audience,
    has_mixed_charter_services,
    is_artifact_charter_title,
    is_charter_or_service_process_unit,
    is_charter_reference_section,
    is_noise_service_title,
    should_reject_charter_article_candidate,
    _coerce_list_field,
)

_HARD_NEGATIVE_PATTERNS = (
    r"\bforeword\b",
    r"\bpreface\b",
    r"\bprayer\b",
    r"\btable of contents\b",
    r"\bcontents\b",
    r"\bmessage from the\b",
    r"\b(?:board of )?(?:regents|trustees)\b",
    r"\buniversity officials?\b",
    r"\badministrative officials?\b",
    r"\borganizational structure\b",
    r"\bmember(?:s)?\b.*\b(?:board|committee)\b",
)

_INTENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "requirements": (r"\brequirement(?:s)?\b", r"\bmust submit\b", r"\bneeded\b", r"\beligib"),
    "how_to": (r"\bhow to\b", r"\bprocedure\b", r"\bsteps?\b", r"\bprocess\b"),
    "where_to_go": (r"\boffice of\b", r"\bdepartment\b", r"\bproceed to\b", r"\breport to\b", r"\bgo to\b"),
    "deadline": (r"\bdeadline\b", r"\bon or before\b", r"\bno later than\b", r"\bwithin\b"),
    "fee": (r"\bfee(?:s)?\b", r"\bpayment\b", r"\bpayable\b"),
    "policy": (r"\bpolic(?:y|ies)\b", r"\bshall\b", r"\bmust not\b"),
    "consequence": (r"\bwarning\b", r"\bsanction\b", r"\bpenalty\b", r"\bconsequence\b", r"\bdismissal\b"),
    "form_needed": (r"\bform\b", r"\bapplication form\b", r"\bslip\b"),
    "troubleshooting": (r"\berror\b", r"\bproblem\b", r"\btroubleshoot", r"\bcannot\b", r"\bunable to\b"),
}

_MIN_MERGED_UNITS_FOR_PARENT = 3
_MAX_COHERENT_CHILD_TOPICS = 4
_MAX_COHERENT_ARTICLE_TYPES = 2
_MAX_COHERENT_SOURCE_ROOTS = 3
_MAX_COHERENT_ARTICLE_NUMBERS = 2


def _article_number_roots(parts: list[str]) -> set[str]:
    roots: set[str] = set()
    for part in parts:
        match = re.search(r"(?i)(?:article|sec\.?|section)\s*(\d+)", part)
        if match:
            roots.add(match.group(1))
        elif is_numeric_only_title(part):
            roots.add(part.split(".", 1)[0])
    return roots


def assess_parent_merge_coherence(units: list[dict]) -> dict[str, Any]:
    """Return whether merged units form a coherent publish-ready parent article."""
    if len(units) < _MIN_MERGED_UNITS_FOR_PARENT:
        return {"coherent": True, "reasons": [], "coverage_only": False}

    article_types = {
        str(unit.get("article_type") or "information").strip().lower()
        for unit in units
        if unit.get("article_type")
    }
    article_types.discard("information")
    article_types.discard("not_article")

    canonical_topics = {
        _normalize_title_key(unit.get("canonical_topic") or unit.get("title"))
        for unit in units
    }
    canonical_topics.discard("")

    source_roots: set[str] = set()
    article_numbers: set[str] = set()
    for unit in units:
        path = unit.get("hierarchy_path") or unit.get("source_section") or ""
        parts = _hierarchy_parts(path)
        if parts:
            root = parts[0]
            if not is_generic_article_title(root):
                source_roots.add(_normalize_title_key(root))
        article_numbers.update(_article_number_roots(parts))

    reasons: list[str] = []
    if len(canonical_topics) > _MAX_COHERENT_CHILD_TOPICS:
        reasons.append("diverse_child_topics")
    if len(article_types) > _MAX_COHERENT_ARTICLE_TYPES:
        reasons.append("diverse_article_categories")
    if len(source_roots) > _MAX_COHERENT_SOURCE_ROOTS:
        reasons.append("unrelated_source_paths")
    if len(article_numbers) > _MAX_COHERENT_ARTICLE_NUMBERS:
        reasons.append("many_article_numbers")

    coherent = not reasons
    return {
        "coherent": coherent,
        "reasons": reasons,
        "coverage_only": not coherent,
    }


def _sha1_id(*parts: str) -> str:
    key = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def stable_preview_id(blueprint_id: str | None, *, fallback_key: str = "") -> str:
    """Stable preview candidate id derived from blueprint SHA1, never Python hash()."""
    if blueprint_id:
        return f"preview-{_sha1_id('preview', blueprint_id)}"
    if fallback_key:
        return f"preview-{_sha1_id('preview-fallback', fallback_key)}"
    return f"preview-{_sha1_id('preview-ephemeral', fallback_key or 'unknown')}"


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _unit_text(unit: dict) -> str:
    return " ".join(
        part
        for part in (
            unit.get("title"),
            unit.get("content"),
            unit.get("hierarchy_path"),
        )
        if part
    )


def ensure_unit_indexes(units: list[dict] | None) -> list[dict]:
    """Return copies with stable ``unit_index`` via enumerate()."""
    return [{**dict(unit), "unit_index": idx} for idx, unit in enumerate(units or [])]


def _looks_like_long_sentence_title(title: str) -> bool:
    words = _normalize_space(title).split()
    return len(words) > 18 or len(title) > 140


def _looks_like_action_fragment(title: str) -> bool:
    normalized = _normalize_space(title)
    if re.fullmatch(
        r"(?i)(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)\s+(?:action|step|phase|stage)$",
        normalized,
    ):
        return True
    return bool(re.fullmatch(r"(?i)(?:action|step|phase|stage)\s+\d+$", normalized))


def _normalize_title_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalize_space(value).lower()).strip()


def _title_belongs_to_section(title: str, section: str) -> bool:
    title_key = _normalize_title_key(title)
    section_key = _normalize_title_key(section)
    if not title_key or not section_key:
        return False
    if title_key == section_key:
        return True
    if title_key.startswith(section_key) or section_key.startswith(title_key):
        return True
    title_tokens = title_key.split()
    section_tokens = section_key.split()
    if len(section_tokens) >= 2 and set(section_tokens).issubset(set(title_tokens)):
        return True
    # Singular/plural variants: requirement vs requirements
    title_stem = title_key.rstrip("s")
    section_stem = section_key.rstrip("s")
    return title_stem == section_stem or title_stem.startswith(section_stem) or section_stem.startswith(title_stem)


def _looks_like_curricular_offering(title: str, hierarchy_path: str | None = None) -> bool:
    text = f"{title} {hierarchy_path or ''}".lower()
    return "curricular offering" in text or "program offering" in text


def _looks_like_appendix_only(title: str) -> bool:
    return bool(re.fullmatch(r"(?i)appendix\s+(?:[a-z]|[ivxlc]+|\d+)$", _normalize_space(title)))


def _is_mergeable_fragment(unit: dict) -> bool:
    """Units that should roll into a parent blueprint instead of standalone articles."""
    title = _normalize_space(unit.get("title"))
    if _looks_like_action_fragment(title):
        return True
    if _looks_like_appendix_only(title):
        path = _normalize_space(unit.get("hierarchy_path"))
        parts = [part.strip() for part in re.split(r"\s*>\s*|\s*/\s*|\s*\|\s*", path) if part.strip()]
        return len(parts) >= 2
    return False


def _looks_like_person_or_position_title(title: str) -> bool:
    normalized = _normalize_space(title)
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
        re.search(
            r"\b(director|coordinator|dean|officer|head|chair|chief|instructor|faculty|adviser|advisor|manager|supervisor|president)\b",
            suffix_lower,
        )
    )
    return bool(name_like_prefix and position_like_suffix)


def _looks_like_incomplete_title(title: str) -> bool:
    normalized = _normalize_space(title)
    if not normalized:
        return True
    if re.search(r"\b(?:accumulat|leading, instigating and par)\b", normalized, flags=re.I):
        return True
    if re.search(r"\b(?:and|or|to|with|from|by|of|for|in|on)$", normalized, flags=re.I):
        return True
    return False


def _looks_like_generic_weak_title(title: str) -> bool:
    normalized = _normalize_space(title).lower()
    return normalized in {
        "overview",
        "notes",
        "note",
        "introduction",
        "general information",
        "miscellaneous",
        "other",
        "description",
        "policy",
        "definition",
        "general",
    }


_GENERIC_TITLE_PATTERNS = (
    r"^sec\.?\s*\d+(?:\.\d+)?(?:\s|$)",
    r"^section\s+\d+(?:\.\d+)?(?:\s|$)",
    r"^article\s+\d+(?:\.\d+)?(?:\s|$)",
    r"^part\s+\d+(?:\.\d+)?(?:\s|$)",
    r"^chapter\s+\d+(?:\.\d+)?(?:\s|$)",
    r"^appendix\s+(?:[a-z]|[ivxlc]+|\d+)$",
)


def is_generic_article_title(title: str | None) -> bool:
    """True for section labels that are not student-facing article titles."""
    normalized = _normalize_space(title)
    if not normalized:
        return True
    if _looks_like_generic_weak_title(normalized):
        return True
    if _looks_like_action_fragment(normalized):
        return True
    if _looks_like_appendix_only(normalized):
        return True
    if is_numeric_only_title(normalized):
        return True
    lower = normalized.lower()
    for pattern in _GENERIC_TITLE_PATTERNS:
        if re.match(pattern, lower, flags=re.I):
            return True
    if re.fullmatch(r"(?i)(?:sec\.?|section|article|part|chapter)\s+\d+(?:\.\d+)?", lower):
        return True
    return False


def is_numeric_only_title(title: str | None) -> bool:
    """True when the title is only a numeric section label such as 1.1 or 7.6.3.1."""
    normalized = _normalize_space(title)
    if not normalized:
        return False
    return bool(re.fullmatch(r"\d+(?:\.\d+)*\.?", normalized))


def _hierarchy_parts(hierarchy_path: str | None) -> list[str]:
    path = _normalize_space(hierarchy_path)
    if not path:
        return []
    return [part.strip() for part in re.split(r"\s*>\s*|\s*/\s*|\s*\|\s*", path) if part.strip()]


def meaningful_topic_from_hierarchy(
    hierarchy_path: str | None,
    *,
    skip_title: str | None = None,
) -> str | None:
    """Pick the nearest non-generic heading from a hierarchy path."""
    skip_key = _normalize_title_key(skip_title)
    for part in reversed(_hierarchy_parts(hierarchy_path)):
        if skip_key and _normalize_title_key(part) == skip_key:
            continue
        if not is_generic_article_title(part):
            return part
    return None


def resolve_student_facing_title(
    title: str | None,
    hierarchy_path: str | None = None,
) -> tuple[str, bool]:
    """Return a student-facing title, using hierarchy when the raw title is generic."""
    normalized = _normalize_space(title)
    if normalized and not is_generic_article_title(normalized):
        return normalized, False
    replacement = meaningful_topic_from_hierarchy(hierarchy_path, skip_title=normalized)
    if replacement:
        return replacement, True
    return normalized or "General Information", False


def _detect_intents(text: str) -> list[str]:
    intents: list[str] = []
    lowered = text.lower()
    for intent, patterns in _INTENT_PATTERNS.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            intents.append(intent)
    return intents


def _detect_article_type(text: str, intents: list[str], *, title: str = "") -> str:
    """Classify article type using title signals first, then body context."""
    title_type = _title_signals_article_type(title)
    if title_type:
        return title_type

    lowered = text.lower()
    if "faq" in lowered or "frequently asked" in lowered:
        return "faq"
    if _content_has_form_fields(text) and re.search(r"\bform\b", lowered):
        return "form"
    if "how_to" in intents or re.search(r"\b(?:procedure|process|steps?|how to)\b", lowered):
        return "procedure"
    if re.search(r"\b(?:requirements?|documents?|checklist|application)\b", (title or "").lower()):
        return "requirement"
    if "requirements" in intents and re.search(
        r"\b(?:must submit|submit the following|required documents?|checklist)\b",
        lowered,
    ):
        return "requirement"
    if "policy" in intents or re.search(r"\bpolic(?:y|ies)\b", lowered):
        return "policy"
    if intents:
        return "information"
    return "not_article"


def _title_signals_article_type(title: str | None) -> str | None:
    normalized = _normalize_space(title)
    if not normalized:
        return None
    lower = normalized.lower()

    if re.search(r"\b(?:procedure|process|steps?|how to)\b", lower):
        return "procedure"
    if re.search(
        r"\b(?:requirements?|documents?|checklist|application)\b",
        lower,
    ):
        if re.search(r"\b(?:application form|request form|registration form)\b", lower):
            return "form"
        return "requirement"
    if re.search(
        r"\b(?:policy|policies|rules?|guidelines?|system|classification|offenses?|conduct|retention|grading)\b",
        lower,
    ):
        return "policy"
    if re.search(r"\b(?:offerings?|programs?|list of)\b", lower):
        return "information"
    if re.search(r"\bform\b", lower) and re.search(r"\b(?:application|request|registration)\b", lower):
        return "form"
    return None


def _content_has_form_fields(text: str) -> bool:
    lowered = text.lower()
    field_markers = (
        r"\bfield(?:s)?\s*:",
        r"\bfill(?:\s+out|\s+in)\b",
        r"\bapplication form\b",
        r"\brequest form\b",
        r"\bname\s*:\s*_",
        r"\bsignature\s*:",
        r"\bdate\s*:\s*_",
    )
    hits = sum(1 for pattern in field_markers if re.search(pattern, lowered))
    return hits >= 2


def _is_hard_negative(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in _HARD_NEGATIVE_PATTERNS)


def _extraction_marks_invalid(unit: dict) -> bool:
    status = str(unit.get("status") or "OK").strip().upper()
    if status in {"INVALID", "ERROR", "FAILED"}:
        return True
    reasons = unit.get("suspicious_reasons")
    if isinstance(reasons, list):
        joined = " ".join(str(item) for item in reasons).lower()
        if "invalid" in joined or "empty_content" in joined:
            return True
    return False


def parent_topic_from_unit(unit: dict) -> str:
    parts = _hierarchy_parts(unit.get("hierarchy_path"))
    non_generic = [part for part in parts if not is_generic_article_title(part)]
    if len(non_generic) >= 2:
        return non_generic[-2]
    if non_generic:
        return non_generic[0]
    if len(parts) >= 2:
        return parts[-2]
    if parts:
        return parts[0]
    return "General"


def canonical_topic_from_unit(unit: dict) -> str:
    title = _normalize_space(unit.get("title"))
    path = _normalize_space(unit.get("hierarchy_path"))
    parts = _hierarchy_parts(path)
    leaf = parts[-1] if parts else ""

    if is_generic_article_title(title):
        replacement = meaningful_topic_from_hierarchy(path, skip_title=title)
        if replacement:
            return replacement

    if _looks_like_action_fragment(title):
        if len(parts) >= 2:
            section = parts[-1]
            if not is_generic_article_title(section):
                return section
            replacement = meaningful_topic_from_hierarchy(path, skip_title=title)
            if replacement:
                return replacement
        return leaf or "Procedure"

    if _looks_like_appendix_only(title) and len(parts) >= 2:
        parent = parts[-2]
        if not is_generic_article_title(parent):
            return parent

    if leaf and _title_belongs_to_section(title, leaf):
        if not is_generic_article_title(leaf):
            return leaf

    if _looks_like_curricular_offering(title, path) and len(parts) >= 2:
        for part in reversed(parts):
            if "curricular offering" in part.lower() or "program offering" in part.lower():
                return part

    if title and not is_generic_article_title(title):
        return title
    replacement = meaningful_topic_from_hierarchy(path, skip_title=title)
    if replacement:
        return replacement
    if leaf and not is_generic_article_title(leaf):
        return leaf
    return "General Information"


def classify_unit_for_articles(unit: dict, db: Session | None = None) -> dict:
    """Tag one knowledge unit for RAG + article eligibility.

    Does not hardcode office names. Office is set only via office_aliases match.
    """
    tagged = dict(unit)
    text = _unit_text(tagged)
    title = _normalize_space(tagged.get("title"))

    rag_indexable = not _extraction_marks_invalid(tagged)
    tagged["rag_indexable"] = rag_indexable
    tagged["parent_topic"] = parent_topic_from_unit(tagged)
    tagged["canonical_topic"] = canonical_topic_from_unit(tagged)
    tagged["source_section"] = tagged.get("hierarchy_path") or tagged.get("title")

    if is_generic_article_title(title) and is_generic_article_title(tagged["canonical_topic"]):
        tagged["article_eligible"] = False
        tagged["article_type"] = "not_article"
        tagged["student_intents"] = []
        tagged["planner_bucket"] = "rag_only"
        tagged["rag_indexable"] = rag_indexable
        return tagged

    office_match = match_office_from_text(text, db)
    if office_match is not None:
        tagged["office"] = office_match.office_name
        tagged["office_match_confidence"] = office_match.confidence
        tagged["office_matched_alias"] = office_match.matched_alias
        tagged["service_category"] = office_match.service_category
    else:
        # Keep charter extracted Office/Division for article bodies; do not treat
        # missing office_aliases match as wiping the extracted office.
        metadata_for_office = tagged.get("metadata") if isinstance(tagged.get("metadata"), dict) else {}
        parser_kind_early = str(
            metadata_for_office.get("parser_document_type") or tagged.get("parser_document_type") or ""
        ).strip().lower()
        is_charter_early = parser_kind_early in {
            "citizen_charter",
            "service_process",
        } or str(metadata_for_office.get("source_type") or tagged.get("source_type") or "") in {
            "Citizen's Charter",
            "Service Process",
        }
        if is_charter_early:
            tagged["office"] = (
                metadata_for_office.get("extracted_office")
                or metadata_for_office.get("office_division")
                or metadata_for_office.get("office")
                or tagged.get("office")
            )
            tagged["office_match_confidence"] = None
            tagged["office_matched_alias"] = None
            tagged["service_category"] = metadata_for_office.get("suggested_category")
        else:
            tagged["office"] = None
            tagged["office_match_confidence"] = None
            tagged["office_matched_alias"] = None
            tagged["service_category"] = None

    if not rag_indexable:
        tagged["article_eligible"] = False
        tagged["article_type"] = "not_article"
        tagged["student_intents"] = []
        tagged["planner_bucket"] = "invalid"
        return tagged

    if (
        _is_hard_negative(text)
        or _looks_like_long_sentence_title(title)
        or _looks_like_action_fragment(title)
        or _looks_like_appendix_only(title)
        or _looks_like_person_or_position_title(title)
        or _looks_like_incomplete_title(title)
        or _looks_like_generic_weak_title(title)
    ):
        tagged["article_eligible"] = False
        tagged["article_type"] = "not_article"
        tagged["student_intents"] = []
        tagged["planner_bucket"] = "rag_only"
        return tagged

    intents = _detect_intents(text)
    article_type = _detect_article_type(text, intents, title=title)
    # Explicit document_type from extraction can establish eligibility when intents are thin.
    metadata = tagged.get("metadata") if isinstance(tagged.get("metadata"), dict) else {}
    doc_type = str(
        metadata.get("document_type")
        if metadata
        else tagged.get("document_type") or ""
    ).strip().lower()
    parser_kind = str(metadata.get("parser_document_type") or "").strip().lower()
    charter_audience = str(metadata.get("charter_audience") or "").strip().lower()

    # Hard-drop known charter/table artifact titles (safe across document profiles).
    # Does not match handbook headings like "Classification of Students…".
    if is_artifact_charter_title(title):
        tagged["article_eligible"] = False
        tagged["article_type"] = "not_article"
        tagged["student_intents"] = []
        tagged["planner_bucket"] = "rag_only"
        tagged["charter_candidate_bucket"] = "rag_only"
        tagged["needs_review_hint"] = "charter_artifact_title"
        return tagged

    if parser_kind == "citizen_charter" or metadata.get("source_type") == "Citizen's Charter":
        if is_charter_reference_section(title, text):
            tagged["article_eligible"] = False
            tagged["article_type"] = "not_article"
            tagged["student_intents"] = []
            tagged["planner_bucket"] = "rag_only"
            tagged["charter_candidate_bucket"] = "rag_only"
            return tagged
        if is_noise_service_title(title) or is_artifact_charter_title(title):
            tagged["article_eligible"] = False
            tagged["article_type"] = "not_article"
            tagged["student_intents"] = []
            tagged["planner_bucket"] = "rag_only"
            tagged["charter_candidate_bucket"] = "rag_only"
            return tagged
        if should_reject_charter_article_candidate(
            title=title,
            source_section=str(tagged.get("source_section") or tagged.get("hierarchy_path") or ""),
            parent_topic=str(tagged.get("parent_topic") or ""),
            hierarchy_path=str(tagged.get("hierarchy_path") or ""),
            office=str(tagged.get("office") or metadata.get("office") or ""),
            who_may_avail=str(metadata.get("who_may_avail") or ""),
        ):
            tagged["article_eligible"] = False
            tagged["article_type"] = "not_article"
            tagged["student_intents"] = []
            tagged["planner_bucket"] = "rag_only"
            tagged["charter_candidate_bucket"] = "rag_only"
            tagged["needs_review_hint"] = "charter_artifact_title"
            return tagged
        if has_mixed_charter_services(title=title, text=text):
            # Mixed blocks become Low Quality candidates — not silent RAG-only drops.
            tagged["student_intents"] = intents or ["how_to"]
            tagged["article_type"] = "procedure"
            tagged["article_eligible"] = True
            tagged["planner_bucket"] = "article_eligible"
            tagged["charter_candidate_bucket"] = "low_quality"
            tagged["needs_review_hint"] = "mixed_charter_services"
            return tagged

        charter_bucket = str(metadata.get("charter_candidate_bucket") or "").strip().lower()
        service_fields = {
            "office": tagged.get("office") or metadata.get("office"),
            "who_may_avail": metadata.get("who_may_avail"),
            "classification": metadata.get("classification"),
            "requirements": _coerce_list_field(metadata.get("extracted_requirements")),
            "steps": _coerce_list_field(metadata.get("extracted_steps")),
            "total_processing_time": metadata.get("total_processing_time"),
        }
        if not charter_bucket:
            charter_bucket = classify_charter_candidate_bucket(
                title=title,
                service=service_fields,
                audience=charter_audience,
                text=text,
            )
        tagged["charter_candidate_bucket"] = charter_bucket
        if charter_bucket == "rag_only":
            tagged["article_eligible"] = False
            tagged["article_type"] = "not_article"
            tagged["student_intents"] = []
            tagged["planner_bucket"] = "rag_only"
            return tagged
        # low_quality / needs_review / recommended all stay article-eligible so
        # Generate Articles can surface Low Quality candidates instead of 0 blueprints.
        article_type = "procedure"
        intents = intents or ["how_to"]
        tagged["student_intents"] = intents
        tagged["article_type"] = "procedure"
        tagged["article_eligible"] = True
        tagged["planner_bucket"] = "article_eligible"
        if not tagged.get("office"):
            tagged["needs_review_hint"] = "uncertain_office"
        if charter_bucket == "low_quality":
            tagged["needs_review_hint"] = tagged.get("needs_review_hint") or "incomplete_charter_service"
        if charter_audience == "internal" or charter_bucket == "needs_review":
            tagged["charter_audience"] = charter_audience or "internal"
            if charter_bucket == "needs_review":
                tagged["needs_review_hint"] = tagged.get("needs_review_hint") or "charter_needs_review"
            return tagged
        tagged["charter_audience"] = charter_audience or "student_facing"
        if metadata.get("suggested_category"):
            tagged["suggested_category"] = metadata.get("suggested_category")
        return tagged

    if not intents and doc_type in {"requirement", "procedure", "form", "how_to", "faq"}:
        intents = ["requirements" if doc_type == "requirement" else "how_to"]
        article_type = doc_type if doc_type != "how_to" else "how_to"
    eligible = (bool(intents) or doc_type in {"requirement", "procedure", "form", "faq"}) and article_type != "not_article"
    if not eligible and _looks_like_curricular_offering(title, tagged.get("hierarchy_path")):
        eligible = True
        article_type = "information"
        if "requirements" not in intents:
            intents = intents or ["requirements"]
    tagged["student_intents"] = intents
    tagged["article_type"] = article_type if eligible else "not_article"
    tagged["article_eligible"] = eligible
    tagged["planner_bucket"] = "article_eligible" if eligible else "rag_only"
    return tagged


def _prefer_parent_key(units: list[dict]) -> tuple[str, str]:
    """When many similar children share a parent, collapse to parent-level topic."""
    parent = _normalize_space(units[0].get("parent_topic")) or "General"
    canonicals = {_normalize_space(unit.get("canonical_topic")) for unit in units}
    if len(units) >= _MIN_MERGED_UNITS_FOR_PARENT and len(canonicals) >= 2:
        # Prefer parent blueprint for broad repeated sections.
        return parent, parent
    canonical = _normalize_space(units[0].get("canonical_topic")) or "General Information"
    return parent, canonical


def _fragment_blueprint_key(unit: dict) -> tuple[str, str]:
    parent = _normalize_space(unit.get("parent_topic")) or parent_topic_from_unit(unit)
    canonical = _normalize_space(unit.get("canonical_topic")) or canonical_topic_from_unit(unit)
    return parent, canonical


def build_article_blueprints(tagged_units: list[dict]) -> list[dict]:
    """Group eligible units into blueprints keyed by parent + canonical topic."""
    # Citizen's Charter / Service Process: article candidates come only from charter units.
    charter_units = [unit for unit in tagged_units if is_charter_or_service_process_unit(unit)]
    working_units = charter_units if charter_units else tagged_units

    eligible = [unit for unit in working_units if unit.get("article_eligible")]
    fragments = [
        unit
        for unit in working_units
        if not unit.get("article_eligible") and _is_mergeable_fragment(unit)
    ]

    # Attach mergeable fragments (action steps, nested appendices) to parent blueprints.
    # Never reattach Citizen's Charter artifact fragments into article blueprints.
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for unit in eligible:
        if is_charter_or_service_process_unit(unit) and should_reject_charter_article_candidate(
            title=str(unit.get("title") or unit.get("canonical_topic") or ""),
            source_section=str(unit.get("source_section") or unit.get("hierarchy_path") or ""),
            parent_topic=str(unit.get("parent_topic") or ""),
            hierarchy_path=str(unit.get("hierarchy_path") or ""),
        ):
            continue
        key = (
            _normalize_space(unit.get("parent_topic")) or "General",
            _normalize_space(unit.get("canonical_topic")) or "General Information",
        )
        by_key[key].append(unit)
    for unit in fragments:
        if is_charter_or_service_process_unit(unit) and should_reject_charter_article_candidate(
            title=str(unit.get("title") or unit.get("canonical_topic") or ""),
            source_section=str(unit.get("source_section") or unit.get("hierarchy_path") or ""),
            parent_topic=str(unit.get("parent_topic") or ""),
            hierarchy_path=str(unit.get("hierarchy_path") or ""),
        ):
            continue
        by_key[_fragment_blueprint_key(unit)].append(unit)

    # Merge duplicate normalized canonical titles under the same parent.
    merged_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    canonical_alias: dict[tuple[str, str], tuple[str, str]] = {}
    for (parent, canonical), units in by_key.items():
        norm = _normalize_title_key(canonical)
        alias_key = (parent, norm)
        if alias_key not in canonical_alias:
            canonical_alias[alias_key] = (parent, canonical)
        merged_by_key[canonical_alias[alias_key]].extend(units)

    by_parent: dict[str, list[tuple[str, str, list[dict]]]] = defaultdict(list)
    for (parent, canonical), units in merged_by_key.items():
        by_parent[parent].append((parent, canonical, units))

    blueprints: list[dict] = []
    for parent, groups in by_parent.items():
        parent_units = [unit for _, _, units in groups for unit in units]
        by_canonical = {canonical: units for _, canonical, units in groups}

        if len(by_canonical) >= _MIN_MERGED_UNITS_FOR_PARENT and len(parent_units) >= _MIN_MERGED_UNITS_FOR_PARENT:
            sample_path = parent_units[0].get("hierarchy_path") or parent_units[0].get("source_section")
            resolved_parent, _ = resolve_student_facing_title(parent, sample_path)
            charter_parent = any(is_charter_or_service_process_unit(unit) for unit in parent_units)
            # Never consolidate Citizen's Charter artifact groups.
            skip_consolidate = False
            if charter_parent and should_reject_charter_article_candidate(
                title=resolved_parent,
                source_section=str(sample_path or ""),
                parent_topic=resolved_parent,
                hierarchy_path=str(sample_path or ""),
            ):
                skip_consolidate = True
            elif charter_parent and any(
                should_reject_charter_article_candidate(
                    title=str(unit.get("title") or unit.get("canonical_topic") or ""),
                    source_section=str(unit.get("source_section") or unit.get("hierarchy_path") or ""),
                    parent_topic=str(unit.get("parent_topic") or resolved_parent),
                    hierarchy_path=str(unit.get("hierarchy_path") or ""),
                )
                for unit in parent_units
            ):
                skip_consolidate = True
            coherence = assess_parent_merge_coherence(parent_units)
            top_roots = {
                _hierarchy_parts(unit.get("hierarchy_path") or unit.get("source_section") or "")[0]
                for unit in parent_units
                if _hierarchy_parts(unit.get("hierarchy_path") or unit.get("source_section") or "")
            }
            if len(top_roots) > 1:
                coherence = {"coherent": False, "reasons": ["multiple_program_roots"], "coverage_only": True}
            if (
                not skip_consolidate
                and not is_generic_article_title(resolved_parent)
                and coherence["coherent"]
            ):
                blueprint_id = _sha1_id("blueprint", resolved_parent, resolved_parent)
                blueprints.append(
                    _blueprint_dict(
                        blueprint_id=blueprint_id,
                        parent_topic=resolved_parent,
                        canonical_topic=resolved_parent,
                        units=parent_units,
                        consolidated_parent=True,
                        merge_coherent=True,
                    )
                )
                continue

        for canonical, units in by_canonical.items():
            root_groups: dict[str, list[dict]] = defaultdict(list)
            for unit in units:
                parts = _hierarchy_parts(unit.get("hierarchy_path") or unit.get("source_section"))
                root = parts[0] if parts else parent
                root_groups[root].append(unit)
            unit_groups = list(root_groups.values()) if len(root_groups) > 1 else [units]

            for group_units in unit_groups:
                sample_path = group_units[0].get("hierarchy_path") or group_units[0].get("source_section")
                parent_topic, canonical_topic = _prefer_parent_key(group_units)
                parent_topic, _ = resolve_student_facing_title(parent_topic, sample_path)
                canonical_topic, _ = resolve_student_facing_title(canonical_topic, sample_path)
                if len(root_groups) > 1:
                    scope = _scope_label_from_source_sections(
                        [
                            str(unit.get("source_section") or unit.get("hierarchy_path") or "")
                            for unit in group_units
                        ]
                    )
                    if scope and not canonical_topic.lower().startswith(scope.lower()):
                        canonical_topic = f"{scope} {canonical_topic}".strip()
                if is_generic_article_title(canonical_topic) or is_numeric_only_title(canonical_topic):
                    continue
                if any(is_charter_or_service_process_unit(unit) for unit in group_units):
                    if should_reject_charter_article_candidate(
                        title=canonical_topic,
                        source_section=str(sample_path or ""),
                        parent_topic=parent_topic,
                        hierarchy_path=str(sample_path or ""),
                    ):
                        continue
                consolidated = (
                    len(group_units) >= _MIN_MERGED_UNITS_FOR_PARENT
                    and not is_generic_article_title(parent_topic)
                )
                merge_coherent = True
                if consolidated:
                    coherence = assess_parent_merge_coherence(group_units)
                    merge_coherent = coherence["coherent"]
                    consolidated = merge_coherent
                if consolidated and any(is_charter_or_service_process_unit(unit) for unit in group_units):
                    if should_reject_charter_article_candidate(
                        title=canonical_topic,
                        source_section=str(sample_path or ""),
                        parent_topic=parent_topic,
                    ):
                        consolidated = False
                blueprint_id = _sha1_id("blueprint", parent_topic, canonical_topic)
                blueprints.append(
                    _blueprint_dict(
                        blueprint_id=blueprint_id,
                        parent_topic=parent_topic,
                        canonical_topic=canonical_topic,
                        units=group_units,
                        consolidated_parent=consolidated,
                        merge_coherent=merge_coherent,
                    )
                )

    # De-dupe by blueprint id (parent collapse can collide with child keys).
    unique: dict[str, dict] = {}
    for blueprint in blueprints:
        existing = unique.get(blueprint["id"])
        if existing is None or blueprint["unit_count"] > existing["unit_count"]:
            unique[blueprint["id"]] = blueprint
    return _disambiguate_blueprint_titles(
        sorted(unique.values(), key=lambda item: (-item["unit_count"], item["canonical_topic"].lower()))
    )


def _choose_article_type(units: list[dict], *, canonical_topic: str = "") -> str:
    title_type = _title_signals_article_type(canonical_topic)
    if title_type:
        return title_type

    counts = Counter(str(unit.get("article_type") or "information") for unit in units)
    for preferred in ("procedure", "policy", "requirement", "form", "how_to", "faq", "information"):
        if counts.get(preferred, 0) > 0:
            return preferred
    for unit in units:
        metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
        doc_type = str(metadata.get("document_type") or unit.get("document_type") or "").lower()
        if doc_type in {"procedure", "requirement", "form", "how_to", "faq", "policy"}:
            return doc_type
        text = _unit_text(unit).lower()
        if re.search(r"\b(?:procedure|process|steps?)\b", text):
            return "procedure"
    return "information"


def _scope_label_from_source_sections(sections: list[str]) -> str | None:
    roots: list[str] = []
    for section in sections:
        parts = _hierarchy_parts(section)
        if parts:
            roots.append(parts[0])
    if not roots:
        return None

    joined = " | ".join(roots).lower()
    if "undergraduate" in joined:
        return "Undergraduate"
    if "graduate" in joined and "undergraduate" not in joined:
        return "Graduate"
    if any("program" in root.lower() for root in roots):
        return "Programs and"

    unique_roots = sorted({_normalize_title_key(root) for root in roots if root})
    if len(unique_roots) <= 1:
        return None
    # Use the shortest distinguishing root token as a scope prefix.
    shortest = min(roots, key=lambda value: len(value))
    if shortest and not is_generic_article_title(shortest):
        return shortest
    return None


def _disambiguate_blueprint_titles(blueprints: list[dict]) -> list[dict]:
    """Rename duplicate canonical titles using meaningful source-root scope."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for blueprint in blueprints:
        key = _normalize_title_key(blueprint.get("canonical_topic"))
        grouped[key].append(blueprint)

    for group in grouped.values():
        if len(group) < 2:
            continue
        for blueprint in group:
            scope = _scope_label_from_source_sections(blueprint.get("source_sections") or [])
            if not scope:
                continue
            title = _normalize_space(blueprint.get("canonical_topic"))
            if title.lower().startswith(scope.lower()):
                continue
            disambiguated = f"{scope} {title}".strip()
            blueprint["canonical_topic"] = disambiguated
            if _normalize_title_key(blueprint.get("parent_topic")) == _normalize_title_key(title):
                blueprint["parent_topic"] = disambiguated
            blueprint["id"] = _sha1_id(
                "blueprint",
                blueprint.get("parent_topic") or disambiguated,
                disambiguated,
            )
    return blueprints


def _blueprint_dict(
    *,
    blueprint_id: str,
    parent_topic: str,
    canonical_topic: str,
    units: list[dict],
    consolidated_parent: bool,
    merge_coherent: bool = True,
) -> dict:
    offices = [unit.get("office") for unit in units if unit.get("office")]
    service_categories = [
        unit.get("service_category") for unit in units if unit.get("service_category")
    ]
    confidences = [
        float(unit["office_match_confidence"])
        for unit in units
        if unit.get("office") and unit.get("office_match_confidence") is not None
    ]
    office = offices[0] if len(set(offices)) == 1 else None
    service_category = service_categories[0] if len(set(service_categories)) == 1 else None
    office_match_confidence = min(confidences) if office and confidences else None
    charter_audiences = [
        str(unit.get("charter_audience") or (unit.get("metadata") or {}).get("charter_audience") or "")
        .strip()
        .lower()
        for unit in units
        if unit.get("charter_audience")
        or (isinstance(unit.get("metadata"), dict) and unit.get("metadata", {}).get("charter_audience"))
    ]
    suggested_categories = [
        str(unit.get("suggested_category") or (unit.get("metadata") or {}).get("suggested_category") or "").strip()
        for unit in units
        if unit.get("suggested_category")
        or (isinstance(unit.get("metadata"), dict) and unit.get("metadata", {}).get("suggested_category"))
    ]
    parser_kinds = [
        str((unit.get("metadata") or {}).get("parser_document_type") or "").strip().lower()
        for unit in units
        if isinstance(unit.get("metadata"), dict)
        and unit.get("metadata", {}).get("parser_document_type")
    ]
    return {
        "id": blueprint_id,
        "parent_topic": parent_topic,
        "canonical_topic": canonical_topic,
        "article_type": _choose_article_type(units, canonical_topic=canonical_topic),
        "office": office,
        "office_match_confidence": office_match_confidence,
        "service_category": service_category,
        "source_sections": sorted(
            {
                str(unit.get("source_section") or unit.get("hierarchy_path") or "")
                for unit in units
                if unit.get("source_section") or unit.get("hierarchy_path")
            }
        ),
        "unit_indices": [int(unit.get("unit_index")) for unit in units if unit.get("unit_index") is not None],
        "unit_count": len(units),
        "consolidated_parent": consolidated_parent,
        "merge_coherent": merge_coherent,
        "coverage_only": consolidated_parent and not merge_coherent,
        "student_intents": sorted(
            {
                intent
                for unit in units
                for intent in (unit.get("student_intents") or [])
            }
        ),
        "charter_audience": charter_audiences[0] if len(set(charter_audiences)) == 1 else (
            "internal" if "internal" in charter_audiences else (charter_audiences[0] if charter_audiences else None)
        ),
        "suggested_category": suggested_categories[0] if len(set(suggested_categories)) == 1 else (
            suggested_categories[0] if suggested_categories else None
        ),
        "charter_candidate_bucket": next(
            (
                str(unit.get("charter_candidate_bucket") or (unit.get("metadata") or {}).get("charter_candidate_bucket") or "").strip()
                for unit in units
                if str(unit.get("charter_candidate_bucket") or (unit.get("metadata") or {}).get("charter_candidate_bucket") or "").strip()
            ),
            None,
        ),
        "parser_document_type": "citizen_charter" if "citizen_charter" in parser_kinds else None,
        "source_type": "Citizen's Charter" if "citizen_charter" in parser_kinds else None,
        "needs_review_hint": next(
            (
                unit.get("needs_review_hint")
                for unit in units
                if unit.get("needs_review_hint")
            ),
            None,
        ),
    }


def merge_blueprint_units(blueprint: dict, units_by_index: dict[int, dict]) -> dict:
    """Merge knowledge units for one blueprint into a synthetic candidate seed."""
    merged_units = [
        units_by_index[idx]
        for idx in blueprint.get("unit_indices") or []
        if idx in units_by_index
    ]
    content_parts = [
        _normalize_space(unit.get("content"))
        for unit in merged_units
        if _normalize_space(unit.get("content"))
    ]
    title = blueprint.get("canonical_topic") or "Untitled"
    source_sections = list(blueprint.get("source_sections") or [])
    sample_path = merged_units[0].get("hierarchy_path") if merged_units else ""
    title, _ = resolve_student_facing_title(title, sample_path or (source_sections[0] if source_sections else None))
    primary_section = source_sections[0] if len(source_sections) == 1 else (blueprint.get("parent_topic") or title)
    primary_meta = merged_units[0].get("metadata") if merged_units and isinstance(merged_units[0].get("metadata"), dict) else {}
    document_type = (
        primary_meta.get("document_type")
        or blueprint.get("article_type")
        or "information"
    )
    return {
        "title": title,
        "content": "\n\n".join(content_parts),
        "hierarchy_path": primary_section,
        "source_section": primary_section,
        "source_sections": source_sections,
        "article_type": blueprint.get("article_type") or "information",
        "document_type": document_type,
        "parent_topic": blueprint.get("parent_topic"),
        "canonical_topic": blueprint.get("canonical_topic"),
        "office": blueprint.get("office"),
        "office_match_confidence": blueprint.get("office_match_confidence"),
        "service_category": blueprint.get("service_category"),
        "merged_unit_count": len(merged_units),
        "consolidated_parent": bool(blueprint.get("consolidated_parent")),
        "merge_coherent": bool(blueprint.get("merge_coherent", True)),
        "blueprint_id": blueprint.get("id"),
        "unit_index": None,
        "student_intents": blueprint.get("student_intents") or [],
        "charter_audience": blueprint.get("charter_audience"),
        "suggested_category": blueprint.get("suggested_category"),
        "charter_candidate_bucket": blueprint.get("charter_candidate_bucket"),
        "parser_document_type": blueprint.get("parser_document_type"),
        "source_type": blueprint.get("source_type"),
        "needs_review_hint": blueprint.get("needs_review_hint"),
        "metadata": {
            **primary_meta,
            "document_type": document_type,
            # Keep extracted office for article bodies even when office_aliases
            # did not confirm a publishable office label on the blueprint.
            "office": blueprint.get("office") or primary_meta.get("office"),
            "extracted_office": primary_meta.get("extracted_office")
            or primary_meta.get("office_division")
            or primary_meta.get("office"),
            "office_division": primary_meta.get("office_division")
            or primary_meta.get("extracted_office")
            or primary_meta.get("office"),
            "section_heading": title,
            "parser_document_type": blueprint.get("parser_document_type")
            or primary_meta.get("parser_document_type"),
            "source_type": blueprint.get("source_type") or primary_meta.get("source_type"),
            "charter_audience": blueprint.get("charter_audience")
            or primary_meta.get("charter_audience"),
            "suggested_category": blueprint.get("suggested_category")
            or primary_meta.get("suggested_category"),
            "charter_candidate_bucket": blueprint.get("charter_candidate_bucket")
            or primary_meta.get("charter_candidate_bucket"),
        },
    }


def build_coverage_report(
    tagged_units: list[dict],
    blueprints: list[dict],
    candidates: list[dict],
) -> list[dict]:
    """Coverage statuses: generated | merged_parent | needs_review | needs_cleanup | rag_only."""
    candidate_topics = {
        (
            _normalize_space(item.get("parent_topic")),
            _normalize_space(item.get("canonical_topic") or item.get("title")),
        ): item
        for item in candidates
    }
    coverage: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()

    for blueprint in blueprints:
        key = (
            _normalize_space(blueprint.get("parent_topic")),
            _normalize_space(blueprint.get("canonical_topic")),
        )
        seen_keys.add(key)
        matched = candidate_topics.get(key)
        status = "needs_cleanup"
        if matched is not None:
            bucket = str(matched.get("planner_bucket") or "").strip().lower()
            if bucket == "consolidated_parent" or (
                blueprint.get("consolidated_parent")
                and int(blueprint.get("unit_count") or 0) >= _MIN_MERGED_UNITS_FOR_PARENT
            ):
                status = "merged_parent"
            elif bucket == "low_quality":
                status = "needs_cleanup"
            elif bucket == "needs_review":
                status = "needs_review"
            elif bucket == "recommended":
                status = "generated"
            elif matched.get("needs_review"):
                status = "needs_review"
            else:
                status = "generated"
        coverage.append(
            {
                "parent_topic": blueprint.get("parent_topic"),
                "canonical_topic": blueprint.get("canonical_topic"),
                "unit_count": blueprint.get("unit_count"),
                "status": status,
                "blueprint_id": blueprint.get("id"),
            }
        )

    # RAG-only topics from ineligible units not covered by blueprints.
    rag_groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "source_sections": set()}
    )
    for unit in tagged_units:
        if unit.get("article_eligible"):
            continue
        key = (
            _normalize_space(unit.get("parent_topic")),
            _normalize_space(unit.get("canonical_topic")),
        )
        if key in seen_keys:
            continue
        rag_groups[key]["count"] += 1
        section = str(unit.get("source_section") or unit.get("hierarchy_path") or "").strip()
        if section:
            rag_groups[key]["source_sections"].add(section)
    for (parent, canonical), payload in sorted(rag_groups.items()):
        sections = sorted(payload["source_sections"])
        coverage.append(
            {
                "parent_topic": parent or "General",
                "canonical_topic": canonical or "General Information",
                "unit_count": payload["count"],
                "status": "rag_only",
                "blueprint_id": None,
                "source_section": sections[0] if sections else None,
                "reason": "RAG-only",
            }
        )
    return coverage


def plan_articles_from_units(
    units: list[dict] | None,
    *,
    db: Session | None = None,
) -> dict[str, Any]:
    indexed = ensure_unit_indexes(units)
    tagged = [classify_unit_for_articles(unit, db=db) for unit in indexed]
    blueprints = build_article_blueprints(tagged)
    units_by_index = {int(unit["unit_index"]): unit for unit in tagged}
    seeds = [merge_blueprint_units(blueprint, units_by_index) for blueprint in blueprints]
    return {
        "tagged_units": tagged,
        "blueprints": blueprints,
        "blueprint_seeds": seeds,
        "units_by_index": units_by_index,
        "article_eligible_count": sum(1 for unit in tagged if unit.get("article_eligible")),
        "rag_only_count": sum(
            1
            for unit in tagged
            if unit.get("rag_indexable") and not unit.get("article_eligible")
        ),
    }

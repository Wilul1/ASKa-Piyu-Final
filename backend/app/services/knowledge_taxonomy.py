"""Config-driven KB category classification and ticket routing metadata.

This is the CANONICAL taxonomy: it drives Chroma retrieval-boosting
(`retrieval_reranker.category_metadata_boost`), ticket auto-routing/office
assignment (`ticketing.py`), and the student-facing `/kb/categories` browser.
`classify_chunk()` writes the `category`/`subcategory`/`office` metadata keys
on every indexed chunk, including Citizen's Charter-derived ones.

NOTE ON TAXONOMY DIVERGENCE (intentional, not a bug): Citizen's Charter
services are ALSO labeled by a second, deliberately separate ruleset —
`citizen_charter_services.map_charter_category()` / `_CATEGORY_RULES` — which
writes a flatter, service-shaped `suggested_category` value used only for
charter article drafting and admin grouping. A charter-derived chunk will
therefore carry both `suggested_category` (charter rules) and
`category`/`subcategory` (this module) side by side; that is expected. Do not
merge the two vocabularies. Anything that needs a value for retrieval,
ticket routing, or the KB category browser should read `category`/
`subcategory` from this module, never `suggested_category`.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.config import llm_extra_headers, settings
from app.services.chunking import DocumentChunk


DEFAULT_CATEGORY = "General"
DEFAULT_SUBCATEGORY = "General"
DEFAULT_OFFICE = "Student Affairs and Services"
LOW_CONFIDENCE_THRESHOLD = 0.45
RULE_CONFIDENCE_THRESHOLD = 0.72


@dataclass(frozen=True)
class SubcategoryConfig:
    name: str
    office: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class CategoryConfig:
    name: str
    keywords: tuple[str, ...]
    subcategories: tuple[SubcategoryConfig, ...]


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    subcategory: str
    office: str
    confidence: float
    method: str
    keywords: tuple[str, ...]


def classify_chunk(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    title: str | None = None,
    allow_llm: bool = True,
) -> ClassificationResult:
    """Classify one chunk using rules, taxonomy similarity, then optional LLM fallback.

    ``allow_llm=False`` skips Groq. Article candidate generation must use this
    because one LLM call per unit (often twice) times out large handbooks.
    """
    haystack = _classification_text(text, metadata=metadata, title=title)
    rule_result = _rule_based_classification(haystack)
    if rule_result.confidence >= RULE_CONFIDENCE_THRESHOLD:
        return rule_result

    similarity_result = _taxonomy_similarity_classification(haystack)
    best = similarity_result if similarity_result.confidence > rule_result.confidence else rule_result
    if best.confidence >= LOW_CONFIDENCE_THRESHOLD or not allow_llm:
        return best

    llm_result = _llm_classification(haystack)
    if llm_result is not None and llm_result.confidence >= best.confidence:
        return llm_result
    return best


def classify_question(question: str) -> ClassificationResult:
    """Classify a student question for retrieval boosts and ticket routing.

    Rules + taxonomy similarity only — never the LLM. ``/qa/ask`` already makes
    one chat-completions call for the answer; a second free-tier LLM call for
    ticket routing routinely queues long enough to trip the Flutter timeout.
    Chunk ingest still uses ``classify_chunk`` (optional LLM fallback).
    """
    haystack = _classification_text(question, metadata=None, title=None)
    rule_result = _rule_based_classification(haystack)
    if rule_result.confidence >= RULE_CONFIDENCE_THRESHOLD:
        return rule_result
    similarity_result = _taxonomy_similarity_classification(haystack)
    if similarity_result.confidence > rule_result.confidence:
        return similarity_result
    return rule_result


def enrich_chunks_with_category_metadata(
    chunks: list[DocumentChunk],
    *,
    title: str | None = None,
    source_document: str | None = None,
) -> list[DocumentChunk]:
    enriched: list[DocumentChunk] = []
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        classification = classify_chunk(chunk.text, metadata=metadata, title=title)
        page = _page_number(metadata)
        campus = _campus_value(metadata)
        keywords = _metadata_keywords(metadata, classification)
        existing_office = _clean_existing_office(metadata.get("office")) or _clean_existing_office(
            metadata.get("responsible_office")
        )
        doc_type = str(
            metadata.get("document_type") or metadata.get("parser_document_type") or ""
        ).lower()
        article_type = str(metadata.get("article_type") or "").lower()
        is_charter_service = (
            doc_type in {"citizen_charter", "procedure", "service_process"}
            or article_type == "service_procedure"
        )
        # Never overwrite an extracted Citizen's Charter office with taxonomy guesses.
        if is_charter_service and existing_office:
            office = existing_office
            responsible_office = existing_office
        else:
            office = existing_office or classification.office
            responsible_office = existing_office or classification.office
        metadata.update(
            {
                "category": classification.category,
                "subcategory": classification.subcategory,
                "office": office,
                "responsible_office": responsible_office,
                "source_document": source_document or title or str(metadata.get("source_title") or ""),
                "classification_method": classification.method,
                "classification_confidence": round(classification.confidence, 3),
                "keywords": json.dumps(keywords),
            }
        )
        if page is not None:
            metadata["page"] = page
        if campus:
            metadata["campus"] = campus
        enriched.append(
            DocumentChunk(
                text=chunk.text,
                chunk_index=chunk.chunk_index,
                char_start=chunk.char_start,
                metadata=metadata,
            )
        )
    return enriched


def category_metadata_boost(query: str, metadata: dict[str, Any]) -> tuple[float, list[str]]:
    classification = classify_question(query)
    score = 0.0
    reasons: list[str] = []
    category = _normalize(str(metadata.get("category") or ""))
    subcategory = _normalize(str(metadata.get("subcategory") or ""))
    if category and category == _normalize(classification.category):
        score += 0.16
        reasons.append("metadata_category_match")
    if subcategory and subcategory == _normalize(classification.subcategory):
        score += 0.24
        reasons.append("metadata_subcategory_match")
    return score, reasons


# Words too generic, on their own, to identify a specific taxonomy service —
# shared by the QA layer (topic/conversation resolution) and the reranker
# (upstream service-identity boosting) so neither can drift out of sync with
# the other about what counts as "naming a service". A handful of taxonomy
# subcategories are themselves named after bare generic nouns (e.g.
# "Certificates", "Requests", "Application Forms") specifically to bucket
# miscellaneous form/document FAQs — without this exclusion, a completely
# vague question like "I want to make a request" would be treated as if it
# named a specific service.
GENERIC_SERVICE_NAME_TOKENS = frozenset(
    {
        "student",
        "students",
        "form",
        "forms",
        "request",
        "requests",
        "certificate",
        "certificates",
        "certification",
        "certifications",
        "issuance",
        "service",
        "services",
        "office",
        "document",
        "documents",
        "application",
        "applications",
        "official",
        "academic",
    }
)


def has_distinctive_token(phrase: str, exclude_tokens: frozenset[str]) -> bool:
    """True when at least one word of ``phrase`` is not a generic/excluded word.

    A taxonomy name or keyword built entirely from generic words (the bare
    subcategory name "Certificates", or a keyword like "application form")
    must not count as naming a service just because every one of its words
    happens to appear in the text — the text still has to contain at least
    one *distinctive* word from that name/keyword. Public: shared by every
    place that needs the same "is this phrase generic-only" test (taxonomy
    matching here, plus exact-label matching in the QA layer) so there is
    exactly one definition of "generic" to keep in sync, not several.
    """
    words = re.findall(r"[a-z0-9]+", phrase)
    return any(word not in exclude_tokens for word in words) if words else False


def _phrase_tokens(phrase: str, exclude_tokens: frozenset[str]) -> frozenset[str]:
    """Distinctive (len>=3, non-generic) tokens of one name/keyword phrase."""
    return frozenset(
        token
        for token in re.findall(r"[a-z0-9]+", phrase)
        if len(token) >= 3 and token not in exclude_tokens
    )


@dataclass(frozen=True)
class TaxonomyServiceMatch:
    """A taxonomy service identified in text, distinguishing *how* it was found.

    ``identity_tokens`` — the canonical name's own distinctive tokens, unioned
    with the distinctive tokens of every keyword alias that also matched.
    Used where more identity signal only ever helps (e.g. a ranking boost's
    magnitude): the service reached only through an alias (e.g. "enrollment"
    reached via the "Registration" subcategory) still carries "registration"
    here too, in case some other card is titled with the canonical name
    itself.

    ``literal_tokens`` — distinctive tokens of only the name/keyword phrase(s)
    that literally, verbatim matched the text. For a service reached only
    through an alias, this is the alias's own tokens, *not* the canonical
    name's (the canonical name never actually appeared in the text). This is
    the stronger signal: a title sharing a *literal* query word is reliable
    evidence; a title sharing only the broader, never-said canonical name is
    not, on its own — see ``taxonomy_service_title_match`` in
    ``retrieval_reranker`` for why that distinction matters.
    """

    name: str
    identity_tokens: frozenset[str]
    literal_tokens: frozenset[str]


def taxonomy_service_matches_in_text(
    normalized_text: str,
    *,
    exclude_tokens: frozenset[str] = GENERIC_SERVICE_NAME_TOKENS,
) -> list[TaxonomyServiceMatch]:
    """Taxonomy services named in ``normalized_text``, with the tokens that identified each.

    Single source of truth for "which existing taxonomy service does this
    text name, and through which of its words" — used both to resolve
    conversational topic identity (QA layer) and to judge whether a chunk's
    title is that service's own authoritative record (retrieval layer AND QA
    layer), so all three cannot silently disagree about what counts as a
    named service or how strongly. ``exclude_tokens`` gates every name and
    keyword match — one built entirely from generic words (see
    :data:`GENERIC_SERVICE_NAME_TOKENS`) is not a real service identification,
    however exactly it matches the text.
    """
    if not normalized_text:
        return []
    tokens = set(re.findall(r"[a-z0-9]+", normalized_text))
    order: list[str] = []
    identity: dict[str, set[str]] = {}
    literal: dict[str, set[str]] = {}

    def _record(name: str, *, identity_add: frozenset[str], literal_add: frozenset[str]) -> None:
        if name not in identity:
            order.append(name)
            identity[name] = set()
            literal[name] = set()
        identity[name] |= identity_add
        literal[name] |= literal_add

    for category in load_taxonomy():
        for subcategory in category.subcategories:
            name_cf = subcategory.name.casefold().strip()
            name_tokens = _phrase_tokens(name_cf, exclude_tokens)
            name_hit = bool(
                name_tokens and re.search(rf"\b{re.escape(name_cf)}\b", normalized_text)
            )
            keyword_hit_tokens: set[str] = set()
            for keyword in subcategory.keywords:
                kw_cf = keyword.casefold().strip()
                if not kw_cf:
                    continue
                kw_tokens = _phrase_tokens(kw_cf, exclude_tokens)
                if not kw_tokens:
                    continue
                hit = (
                    re.search(rf"\b{re.escape(kw_cf)}\b", normalized_text)
                    if " " in kw_cf
                    else kw_cf in tokens
                )
                if hit:
                    keyword_hit_tokens |= kw_tokens
            if not (name_hit or keyword_hit_tokens):
                continue
            # identity_tokens always carries the canonical name's tokens (the
            # existing production comparison always used the canonical name);
            # literal_tokens carries only what the text actually said.
            literal_add = (name_tokens if name_hit else frozenset()) | frozenset(keyword_hit_tokens)
            identity_add = name_tokens | frozenset(keyword_hit_tokens)
            _record(subcategory.name, identity_add=identity_add, literal_add=literal_add)

    return [
        TaxonomyServiceMatch(
            name=name,
            identity_tokens=frozenset(identity[name]),
            literal_tokens=frozenset(literal[name]),
        )
        for name in order
    ]


def taxonomy_service_names_in_text(
    normalized_text: str,
    *,
    exclude_tokens: frozenset[str] = GENERIC_SERVICE_NAME_TOKENS,
) -> list[str]:
    """Back-compat view of :func:`taxonomy_service_matches_in_text`: names only.

    Existing callers that only need "which services are named" (not the
    matched alias detail) keep working unchanged.
    """
    return [
        match.name
        for match in taxonomy_service_matches_in_text(normalized_text, exclude_tokens=exclude_tokens)
    ]


@lru_cache(maxsize=1)
def _canonical_service_name_map() -> dict[str, str]:
    """Casefolded taxonomy subcategory name -> its canonical spelling.

    Used to validate a client-supplied active-service identity against the
    same vocabulary this backend itself would ever produce.
    """
    return {
        subcategory.name.casefold().strip(): subcategory.name
        for category in load_taxonomy()
        for subcategory in category.subcategories
    }


def validate_active_service_identity(value: str | None) -> str | None:
    """A client-supplied "active service" value, or ``None`` if untrustworthy.

    A client (e.g. the Flutter app) may echo back a service identity this
    backend returned on an earlier turn. That value must never be trusted
    blindly — it is arbitrary client input — so it is only accepted when it
    exactly matches a real taxonomy subcategory name. Anything else
    (garbage, a stale/removed service, a spoofed value) is rejected here and
    the caller falls back to its own resolution instead of retrieving for a
    service that was never validated.
    """
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    if not cleaned or len(cleaned) > 240:
        return None
    return _canonical_service_name_map().get(cleaned.casefold())


def knowledge_base_taxonomy() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for category in load_taxonomy():
        items.append(
            {
                "name": category.name,
                "keywords": list(category.keywords),
                "subcategories": [
                    {
                        "name": subcategory.name,
                        "office": subcategory.office,
                        "keywords": list(subcategory.keywords),
                    }
                    for subcategory in category.subcategories
                ],
            }
        )
    return items


def decode_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(decoded, list):
        return [str(item) for item in decoded if str(item).strip()]
    return []


@lru_cache(maxsize=1)
def load_taxonomy() -> tuple[CategoryConfig, ...]:
    path = Path(settings.kb_categories_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    data = json.loads(path.read_text(encoding="utf-8"))
    categories: list[CategoryConfig] = []
    for raw_category in data.get("categories", []):
        subcategories = tuple(
            SubcategoryConfig(
                name=str(raw_subcategory.get("name") or "").strip(),
                office=str(raw_subcategory.get("office") or DEFAULT_OFFICE).strip() or DEFAULT_OFFICE,
                keywords=tuple(str(item).strip() for item in raw_subcategory.get("keywords", []) if str(item).strip()),
            )
            for raw_subcategory in raw_category.get("subcategories", [])
        )
        categories.append(
            CategoryConfig(
                name=str(raw_category.get("name") or "").strip(),
                keywords=tuple(str(item).strip() for item in raw_category.get("keywords", []) if str(item).strip()),
                subcategories=subcategories,
            )
        )
    return tuple(category for category in categories if category.name and category.subcategories)


def _rule_based_classification(text: str) -> ClassificationResult:
    best: tuple[float, CategoryConfig | None, SubcategoryConfig | None, list[str]] = (0.0, None, None, [])
    for category in load_taxonomy():
        category_hits = _matched_keywords(text, category.keywords)
        for subcategory in category.subcategories:
            sub_hits = _matched_keywords(text, subcategory.keywords)
            score = (len(sub_hits) * 2.5) + len(category_hits)
            exact_name_bonus = 3.0 if _normalize(subcategory.name) in text else 0.0
            category_name_bonus = 1.0 if _normalize(category.name) in text else 0.0
            score += exact_name_bonus + category_name_bonus
            if score > best[0]:
                best = (score, category, subcategory, [*subcategory.keywords[:3], *sub_hits, *category_hits])

    score, category, subcategory, keywords = best
    if category is None or subcategory is None:
        return _fallback_result("rule", 0.0)
    confidence = min(0.98, score / 8.0)
    return ClassificationResult(
        category=category.name,
        subcategory=subcategory.name,
        office=subcategory.office,
        confidence=round(confidence, 3),
        method="rule",
        keywords=tuple(_dedupe(keywords)[:8]),
    )


def _taxonomy_similarity_classification(text: str) -> ClassificationResult:
    text_vector = _term_vector(text)
    best: tuple[float, CategoryConfig | None, SubcategoryConfig | None] = (0.0, None, None)
    for category in load_taxonomy():
        for subcategory in category.subcategories:
            descriptor = " ".join([category.name, subcategory.name, *category.keywords, *subcategory.keywords])
            similarity = _cosine(text_vector, _term_vector(_normalize(descriptor)))
            if similarity > best[0]:
                best = (similarity, category, subcategory)

    similarity, category, subcategory = best
    if category is None or subcategory is None:
        return _fallback_result("similarity", 0.0)
    return ClassificationResult(
        category=category.name,
        subcategory=subcategory.name,
        office=subcategory.office,
        confidence=round(min(0.7, similarity), 3),
        method="embedding_similarity",
        keywords=tuple(_dedupe([*subcategory.keywords[:5], *category.keywords[:3]])),
    )


def _llm_classification(text: str) -> ClassificationResult | None:
    if not settings.groq_api_key:
        return None
    taxonomy = [
        {
            "category": category.name,
            "subcategories": [
                {"name": subcategory.name, "office": subcategory.office}
                for subcategory in category.subcategories
            ],
        }
        for category in load_taxonomy()
    ]
    prompt = (
        "Classify this university knowledge-base chunk into exactly one taxonomy entry. "
        "Return only JSON with category, subcategory, office, confidence, and keywords.\n\n"
        f"Taxonomy:\n{json.dumps(taxonomy)}\n\nChunk:\n{text[:3500]}"
    )
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
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": "You classify chunks for ticket routing. Use only the provided taxonomy."},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            payload = json.loads(_extract_json_object(content))
    except Exception:
        return None

    category_name = str(payload.get("category") or "")
    subcategory_name = str(payload.get("subcategory") or "")
    category, subcategory = _find_taxonomy_entry(category_name, subcategory_name)
    if category is None or subcategory is None:
        return None
    confidence = payload.get("confidence")
    confidence_value = float(confidence) if isinstance(confidence, (int, float)) else 0.5
    raw_keywords = payload.get("keywords") if isinstance(payload.get("keywords"), list) else []
    return ClassificationResult(
        category=category.name,
        subcategory=subcategory.name,
        office=subcategory.office,
        confidence=round(max(0.0, min(0.95, confidence_value)), 3),
        method="llm",
        keywords=tuple(_dedupe([str(item) for item in raw_keywords] + list(subcategory.keywords[:4]))),
    )


def _find_taxonomy_entry(category_name: str, subcategory_name: str) -> tuple[CategoryConfig | None, SubcategoryConfig | None]:
    normalized_category = _normalize(category_name)
    normalized_subcategory = _normalize(subcategory_name)
    for category in load_taxonomy():
        if _normalize(category.name) != normalized_category:
            continue
        for subcategory in category.subcategories:
            if _normalize(subcategory.name) == normalized_subcategory:
                return category, subcategory
    return None, None


def _fallback_result(method: str, confidence: float) -> ClassificationResult:
    return ClassificationResult(
        category=DEFAULT_CATEGORY,
        subcategory=DEFAULT_SUBCATEGORY,
        office=DEFAULT_OFFICE,
        confidence=confidence,
        method=method,
        keywords=(),
    )


def _classification_text(text: str, *, metadata: dict[str, Any] | None, title: str | None) -> str:
    metadata = metadata or {}
    values = [
        str(title or ""),
        text,
        *[
            str(metadata.get(key) or "")
            for key in (
                "title",
                "path",
                "hierarchy_path",
                "chapter",
                "article",
                "section",
                "appendix",
                "service",
                "office",
                "responsible_office",
                "content_type",
                "source_title",
                "source_document",
                "source_filename",
                "document_id",
                "keywords",
            )
        ],
    ]
    return _normalize(" ".join(values))


def _matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if _normalize(keyword) in text]


def _term_vector(text: str) -> dict[str, int]:
    vector: dict[str, int] = {}
    for token in re.findall(r"[a-z0-9]+", text):
        if len(token) < 3:
            continue
        vector[token] = vector.get(token, 0) + 1
    return vector


def _cosine(left: dict[str, int], right: dict[str, int]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _metadata_keywords(metadata: dict[str, Any], classification: ClassificationResult) -> list[str]:
    existing = decode_keywords(metadata.get("keywords"))
    return _dedupe([*existing, *classification.keywords, classification.category, classification.subcategory])


def _clean_existing_office(value: Any) -> str:
    office = str(value or "").strip()
    if not office or "needs review" in office.lower():
        return ""
    return office


def _campus_value(metadata: dict[str, Any]) -> str:
    for key in ("campus", "campuses"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            return ", ".join(str(item) for item in value if str(item).strip())
    return "All Campuses"


def _page_number(metadata: dict[str, Any]) -> int | None:
    page = metadata.get("page") or metadata.get("page_start")
    if isinstance(page, int):
        return page
    if isinstance(page, str) and page.isdigit():
        return int(page)
    return None


def _extract_json_object(value: str) -> str:
    match = re.search(r"\{.*\}", value or "", flags=re.S)
    return match.group(0) if match else "{}"


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        key = _normalize(cleaned)
        if cleaned and key not in seen:
            output.append(cleaned)
            seen.add(key)
    return output


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()

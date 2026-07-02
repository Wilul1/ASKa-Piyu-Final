from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

from fastapi import APIRouter, HTTPException, Query

from app.services.chroma_store import RetrievedChunk, get_knowledge_base_store
from app.services.knowledge_taxonomy import (
    classify_question,
    decode_keywords,
    knowledge_base_taxonomy,
)
from app.services.retrieval_reranker import prepare_retrieval_query

router = APIRouter(prefix="/kb", tags=["Knowledge Base Browser"])
MAX_SECTIONS_BEFORE_SPLIT = 5

POPULAR_TERMS = (
    "Excuse Slip",
    "Enrollment",
    "Scholastic Delinquency",
    "Retention Policy",
    "Curricular Offerings",
    "Graduation Requirements",
    "Administrative Officials",
)


@dataclass(frozen=True)
class ArticleIdentity:
    article_title: str
    article_key: str
    section_title: str
    display_path: str
    aliases: tuple[str, ...]
    grouping_reason: str
    category: str
    parent_title: str


@router.get("/articles", summary="List indexed knowledge base articles")
async def list_articles(
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    debug: bool = Query(default=False),
) -> dict[str, Any]:
    store = _store()
    if q and q.strip():
        filtered = _semantic_article_search(
            store,
            q=q.strip(),
            category=category,
            limit=limit,
            offset=offset,
        )
    else:
        raw_chunks = store.list_chunks()
        articles = (
            _focused_article_groups(raw_chunks)
            if _has_classified_chunks(raw_chunks)
            else [_article_summary(chunk) for chunk in raw_chunks]
        )
        filtered = _filter_articles(articles, q=None, category=category)
    displayed = _prepare_article_display(filtered, q=q or "")
    if not debug:
        displayed = [_without_identity_debug(item) for item in displayed]
    return {
        "items": displayed[offset : offset + limit],
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "suggestions": _search_suggestions(q or "") if q and not filtered else [],
    }


@router.get("/articles/{article_id:path}", summary="Read one indexed knowledge base article")
async def get_article(article_id: str) -> dict[str, Any]:
    if article_id.startswith("kb:"):
        article = _configured_article_detail(article_id)
        if article is None:
            raise HTTPException(status_code=404, detail="Article not found")
        return article
    if article_id.startswith("topic:"):
        article = _focused_article_detail(article_id)
        if article is None:
            raise HTTPException(status_code=404, detail="Article not found")
        return article
    if _looks_like_article_key(article_id):
        article = _focused_article_detail(article_id)
        if article is None:
            raise HTTPException(status_code=404, detail="Article not found")
        return article
    chunk = _store().get_chunk(article_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return _article_detail(chunk)


@router.get("/categories", summary="List indexed knowledge base categories")
async def list_categories() -> dict[str, Any]:
    chunks = _store().list_chunks()
    if not _has_classified_chunks(chunks):
        return _legacy_categories(chunks)
    counts = _subcategory_counts(chunks)
    items = []
    for category in knowledge_base_taxonomy():
        subcategories = []
        article_count = 0
        for subcategory in category["subcategories"]:
            key = (_normalize(category["name"]), _normalize(subcategory["name"]))
            count = counts.get(key, 0)
            article_count += count
            subcategories.append(
                {
                    "name": subcategory["name"],
                    "office": subcategory["office"],
                    "article_count": count,
                    "id": _configured_article_id(category["name"], subcategory["name"]),
                }
            )
        items.append(
            {
                "name": category["name"],
                "article_count": article_count,
                "sample_article_titles": [item["name"] for item in subcategories[:4]],
                "subcategories": subcategories,
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/classify", summary="Classify a question for support routing")
async def classify_for_routing(q: str = Query(..., min_length=3)) -> dict[str, Any]:
    result = classify_question(q)
    return {
        "category": result.category,
        "subcategory": result.subcategory,
        "office": result.office,
        "responsible_office": result.office,
        "confidence": result.confidence,
        "method": result.method,
        "keywords": list(result.keywords),
    }


@router.get("/popular", summary="List common knowledge base topics")
async def popular_articles() -> dict[str, Any]:
    articles = [_article_summary(chunk) for chunk in _store().list_chunks()]
    popular: list[dict[str, Any]] = []
    seen: set[str] = set()

    for term in POPULAR_TERMS:
        term_key = _normalize(term)
        match = next(
            (
                article
                for article in articles
                if article["id"] not in seen
                and term_key in _normalize(
                    f"{article['title']} {article['path']} {article['content_preview']}"
                )
            ),
            None,
        )
        if match:
            popular.append(match)
            seen.add(match["id"])
        else:
            popular.append(
                {
                    "id": f"topic:{term_key.replace(' ', '-')}",
                    "title": term,
                    "path": term,
                    "category": _category_from_path(term),
                    "page": None,
                    "source_filename": "",
                    "content_preview": "Search the Knowledge Base for this common topic.",
                    "article_type": "topic",
                }
            )

    return {"items": popular, "total": len(popular)}


def _store():
    return get_knowledge_base_store()


ARTICLE_IDENTITY_RULES: tuple[dict[str, Any], ...] = (
    {
        "title": "Transcript of Records",
        "aliases": ("tor", "transcript", "official transcript", "transcript of records"),
        "category": "Student Records",
    },
    {
        "title": "Excuse Slip",
        "aliases": ("excuse slip", "excuse letter"),
        "category": "Academic Policies",
        "parent": "Attendance",
    },
    {
        "title": "Scholastic Delinquency",
        "aliases": ("scholastic delinquency", "failed units", "delinquency", "probation", "warning"),
        "category": "Academic Policies",
        "parent": "Retention",
    },
    {
        "title": "Good Moral",
        "aliases": ("good moral", "good moral certificate", "moral certificate"),
        "category": "Student Records",
    },
    {
        "title": "College of Engineering Programs",
        "aliases": ("engineering program", "engineering courses", "college of engineering", "engineering"),
        "category": "Programs & Curricular Offerings",
    },
    {
        "title": "College of Computer Studies Programs",
        "aliases": ("ccs program", "computer studies", "computer science", "bscs", "bsit", "bsis", "college of computer studies"),
        "category": "Programs & Curricular Offerings",
    },
    {
        "title": "Student Portal Account Recovery",
        "aliases": ("portal", "portal password", "account recovery", "login problem", "student portal"),
        "category": "Technical Support",
        "parent": "Student Portal",
    },
    {
        "title": "Guidance Counseling",
        "aliases": ("guidance", "counseling", "counselling", "counselor"),
        "category": "Student Services",
    },
)


def derive_article_identity(
    chunk_metadata: dict[str, Any],
    chunk_text: str,
    query: str | None = None,
) -> ArticleIdentity:
    metadata = dict(chunk_metadata or {})
    hierarchy_path = _hierarchy_path(metadata)
    raw_title = str(metadata.get("title") or "").strip()
    display_title = _display_title(metadata) or raw_title
    category = _category_from_metadata(metadata, hierarchy_path, display_title)
    parent = _parent_topic_from_metadata(metadata, category)
    leaf = _leaf_topic_from_metadata(metadata)
    normalized_query = _normalize_ascii(query or "")
    haystack = _normalize_ascii(
        " ".join(
            [
                chunk_text,
                hierarchy_path,
                raw_title,
                display_title,
                category,
                parent,
                leaf,
                str(metadata.get("keywords") or ""),
                str(metadata.get("source_document") or ""),
                str(metadata.get("source_filename") or ""),
            ]
        )
    )

    broad_title = _broad_identity_title(category, parent, normalized_query)
    matched_aliases: tuple[str, ...] = ()
    grouping_reason = "hierarchy_leaf"
    if broad_title:
        article_title = broad_title
        parent = ""
        grouping_reason = "broad_parent_query"
    else:
        rule = _matching_identity_rule(
            category,
            haystack,
            normalized_query,
            exact_candidates=(leaf, parent, raw_title, display_title),
        )
        if rule is not None:
            article_title = str(rule["title"])
            category = str(rule.get("category") or category)
            parent = str(rule.get("parent") or parent)
            matched_aliases = tuple(
                alias
                for alias in rule["aliases"]
                if _normalize_ascii(alias) in haystack or _normalize_ascii(alias) in normalized_query
            )
            grouping_reason = "alias_rule"
        else:
            article_title = _best_specific_title(
                leaf=leaf,
                parent=parent,
                raw_title=raw_title,
                category=category,
            )

    article_title = _program_topic_title({"category": category, "subcategory": parent}, article_title)
    if not parent or _normalize_ascii(parent) == _normalize_ascii(article_title):
        parent = _parent_topic_from_path_without_title(hierarchy_path, category, article_title)

    display_path = _identity_display_path(category, parent, article_title)
    article_key = f"{_slug_value(category)}:{_slug_value(article_title)}"
    section_title = _section_title_for_identity(leaf, article_title)
    return ArticleIdentity(
        article_title=article_title,
        article_key=article_key,
        section_title=section_title,
        display_path=display_path,
        aliases=matched_aliases,
        grouping_reason=grouping_reason,
        category=category,
        parent_title=parent,
    )


def _matching_identity_rule(
    category: str,
    haystack: str,
    normalized_query: str,
    *,
    exact_candidates: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    exact_values = {_normalize_ascii(candidate) for candidate in exact_candidates if candidate}
    for rule in ARTICLE_IDENTITY_RULES:
        aliases = tuple(_normalize_ascii(alias) for alias in rule["aliases"])
        if not normalized_query:
            if any(alias and alias in exact_values for alias in aliases):
                return rule
            continue
        if any(_alias_rule_matches(alias, haystack, normalized_query) for alias in aliases):
            return rule
    return None


def _alias_rule_matches(alias: str, haystack: str, normalized_query: str) -> bool:
    if not alias:
        return False
    if alias in haystack:
        return True
    if alias not in normalized_query:
        return False
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", alias)
        if token not in {"program", "programs", "policy", "policies", "student"}
    ]
    return bool(tokens) and any(token in haystack for token in tokens)


def _broad_identity_title(category: str, parent: str, normalized_query: str) -> str:
    if normalized_query in {"retention", "retention policy", "retention policies"} and _normalize_ascii(parent) == "retention":
        return "Retention Policies"
    if normalized_query == "attendance" and _normalize_ascii(parent) == "attendance":
        return "Attendance"
    if normalized_query in {"admission", "admissions"} and "admission" in _normalize_ascii(category):
        return "Admissions"
    return ""


def _best_specific_title(*, leaf: str, parent: str, raw_title: str, category: str) -> str:
    for candidate in (leaf, raw_title, parent, category):
        cleaned = _clean_path_label(candidate)
        if _usable_article_title(cleaned):
            return cleaned
    return category or "General"


def _usable_article_title(value: str) -> bool:
    normalized = _normalize_ascii(value)
    if not normalized or normalized in {"student handbook", "general"}:
        return False
    if len(normalized) > 90:
        return False
    return True


def _parent_topic_from_metadata(metadata: dict[str, Any], category: str) -> str:
    subcategory = str(metadata.get("subcategory") or "").strip()
    if subcategory:
        return _clean_path_label(subcategory)
    article = str(metadata.get("article") or "").strip()
    if article:
        parent = _clean_path_label(_hierarchy_leaf_label(article))
        if _normalize_ascii(parent) != _normalize_ascii(category):
            return parent
    return ""


def _leaf_topic_from_metadata(metadata: dict[str, Any]) -> str:
    for key in ("section", "article", "chapter", "appendix", "hierarchy_path", "path"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return _clean_path_label(_hierarchy_leaf_label(value))
    return _clean_path_label(str(metadata.get("title") or ""))


def _parent_topic_from_path_without_title(path: str, category: str, article_title: str) -> str:
    parts = [_clean_path_label(part) for part in _path_parts(path)]
    cleaned = [
        part
        for part in parts
        if part
        and _normalize_ascii(part) != _normalize_ascii(category)
        and not _path_part_repeats_title(part, _normalize_ascii(article_title))
    ]
    return cleaned[-1] if cleaned else ""


def _identity_display_path(category: str, parent: str, article_title: str) -> str:
    parts = [category]
    if parent and _normalize_ascii(parent) != _normalize_ascii(category):
        parts.append(parent)
    return _display_path_without_title(parts, article_title)


def _section_title_for_identity(leaf: str, article_title: str) -> str:
    if not leaf or _path_part_repeats_title(leaf, _normalize_ascii(article_title)):
        return ""
    return leaf


def _filter_articles(
    articles: list[dict[str, Any]],
    *,
    q: str | None,
    category: str | None,
) -> list[dict[str, Any]]:
    filtered = articles
    if q and q.strip():
        query = _normalize(q)
        filtered = [
            article
            for article in filtered
            if query
            in _normalize(
                f"{article['title']} {article['path']} {article['source_filename']} "
                f"{article['content_preview']} {article.get('article_type') or ''}"
            )
        ]
    if category and category.strip():
        category_key = _normalize(category)
        filtered = [
            article
            for article in filtered
            if _normalize(article["category"]) == category_key
        ]
    return filtered


def _semantic_article_search(
    store,
    *,
    q: str,
    category: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    search_k = min(max(limit + offset + 30, 60), 100)
    expanded_query = _kb_search_query(q)
    chunks = store.search(expanded_query, top_k=search_k, raw_k=search_k)
    chunks = _relevant_retrieved_chunks(chunks)
    if category and category.strip():
        category_key = _normalize(category)
        chunks = [
            chunk
            for chunk in chunks
            if _normalize(_category_for_retrieved_chunk(chunk)) == category_key
        ]
    articles = _rank_articles_for_query(_group_retrieved_chunks(chunks, query=q), q)
    if articles:
        return articles
    return _keyword_article_search(store, q=q, category=category)


def _kb_search_query(query: str) -> str:
    prepared = prepare_retrieval_query(query)
    expansions = _kb_search_expansions(query)
    return " ".join(_dedupe([prepared.expanded_query, *expansions]))


def _kb_search_expansions(query: str) -> list[str]:
    normalized = _normalize_ascii(query)
    expansions: list[str] = []
    rules: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
        (
            ("engineering program", "engineering programs"),
            (
                "engineering",
                "program",
                "programs",
                "curricular offerings",
                "college of engineering",
                "engineering programs",
                "undergraduate programs",
            ),
        ),
        (
            ("ccs program", "computer studies program", "computer studies"),
            (
                "college of computer studies",
                "computer studies programs",
                "bs computer science",
                "bs information technology",
                "bs information system",
                "curricular offerings",
            ),
        ),
        (
            ("computer science", "bscs"),
            (
                "bs computer science",
                "bachelor of science in computer science",
                "college of computer studies",
                "computer studies programs",
            ),
        ),
        (("enrollment", "enroll"), ("admissions", "enrollment", "registration")),
        (("freshman", "freshmen"), ("admissions", "freshmen", "admission requirements")),
        (("transferee", "transferees"), ("admissions", "transferees", "transfer credentials")),
        (("excuse slip",), ("academic policies", "attendance", "excuse slip")),
        (("absent", "absence"), ("academic policies", "attendance", "absence", "excuse slip")),
        (("tor",), ("student records", "transcript of records", "registrar")),
        (("good moral",), ("student records", "good moral", "certificate")),
        (("scholarship", "scholarships"), ("scholarships", "financial policies", "grant")),
        (("guidance",), ("student services", "guidance", "guidance office")),
        (("counseling", "counselling"), ("student services", "counseling", "guidance")),
        (
            ("portal password", "student portal password", "account recovery", "forgot password"),
            ("technical support", "student portal", "account recovery", "password"),
        ),
    )
    for triggers, terms in rules:
        if any(trigger in normalized for trigger in triggers):
            expansions.extend(terms)
    return expansions


def _keyword_article_search(store, *, q: str, category: str | None) -> list[dict[str, Any]]:
    chunks = store.list_chunks()
    if category and category.strip():
        category_key = _normalize(category)
        chunks = [
            chunk
            for chunk in chunks
            if _normalize(_article_summary(chunk)["category"]) == category_key
        ]
    query_terms = _meaningful_search_terms(_kb_search_query(q))
    if not query_terms:
        return []
    matched = [
        chunk
        for chunk in chunks
        if _chunk_matches_terms(chunk, query_terms)
    ]
    return _rank_articles_for_query(_focused_article_groups(matched, query=q), q) if matched else []


def _rank_articles_for_query(articles: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    query_terms = _meaningful_search_terms(query)
    normalized_query = _normalize_ascii(query)

    def score(article: dict[str, Any]) -> tuple[int, float]:
        haystack = _normalize_ascii(
            " ".join(
                [
                    str(article.get("title") or ""),
                    str(article.get("path") or ""),
                    str(article.get("category") or ""),
                    str(article.get("subcategory") or ""),
                    " ".join(str(item) for item in article.get("keywords") or []),
                ]
            )
        )
        exact = 8 if normalized_query and normalized_query in haystack else 0
        overlap = sum(1 for term in query_terms if term in haystack)
        relevance = float(article.get("relevance_score") or 0)
        return exact + overlap, relevance

    return sorted(articles, key=score, reverse=True)


def _prepare_article_display(articles: list[dict[str, Any]], *, q: str) -> list[dict[str, Any]]:
    return [_display_article_for_query(article, q) for article in articles]


def _without_identity_debug(article: dict[str, Any]) -> dict[str, Any]:
    item = dict(article)
    for key in (
        "article_key",
        "derived_article_title",
        "derived_section_title",
        "matched_aliases",
        "grouping_reason",
    ):
        item.pop(key, None)
    return item


def _display_article_for_query(article: dict[str, Any], query: str) -> dict[str, Any]:
    item = dict(article)
    normalized_query = _normalize_ascii(query)
    path_parts = _path_parts(str(item.get("path") or ""))
    title = str(item.get("title") or "").strip()

    broad_title = _broad_parent_title(item, normalized_query)
    if broad_title:
        item["title"] = broad_title
        path_parts = path_parts[:1]
    elif title:
        item["title"] = title

    item["path"] = _display_path_without_title(path_parts, str(item.get("title") or ""))
    return item


def _matched_leaf_title(path_parts: list[str], normalized_query: str) -> str:
    if not normalized_query:
        return ""
    aliases = _query_title_aliases(normalized_query)
    for part in reversed(path_parts):
        candidate = _clean_path_label(part)
        normalized_candidate = _normalize_ascii(candidate)
        if not normalized_candidate:
            continue
        if normalized_candidate in aliases or any(alias and alias in normalized_candidate for alias in aliases):
            return candidate
    return ""


def _query_title_aliases(normalized_query: str) -> set[str]:
    aliases = {normalized_query}
    if normalized_query == "tor":
        aliases.add("transcript of records")
    if "portal" in normalized_query and "password" in normalized_query:
        aliases.update({"account recovery", "student portal account recovery", "student portal password"})
    if "engineering" in normalized_query and "program" in normalized_query:
        aliases.add("college of engineering")
        aliases.add("college of engineering programs")
    if "ccs" in normalized_query:
        aliases.add("college of computer studies")
        aliases.add("college of computer studies programs")
    return aliases


def _broad_parent_title(article: dict[str, Any], normalized_query: str) -> str:
    subcategory = str(article.get("subcategory") or "")
    if normalized_query in {"retention", "retention policy", "retention policies"} and _normalize_ascii(subcategory) == "retention":
        return "Retention Policies"
    return ""


def _display_path_without_title(path_parts: list[str], title: str) -> str:
    normalized_title = _normalize_ascii(title)
    kept = [_clean_path_label(part) for part in path_parts]
    while kept and _path_part_repeats_title(kept[-1], normalized_title):
        kept = kept[:-1]
    return " • ".join(part for part in kept if part)


def _path_part_repeats_title(path_part: str, normalized_title: str) -> bool:
    normalized_part = _normalize_ascii(path_part)
    return normalized_part == normalized_title or f"{normalized_part} programs" == normalized_title


def _path_parts(path: str) -> list[str]:
    return [part.strip() for part in re.split(r">|•|â€¢", path) if part.strip()]


def _clean_path_label(value: str) -> str:
    return re.sub(
        r"^(chapter|article|sec\.?|section|appendix)\s*[\w.-]*\s*",
        "",
        value,
        flags=re.I,
    ).strip(" :-")


def _chunk_matches_terms(chunk: dict[str, Any], terms: set[str]) -> bool:
    metadata = dict(chunk.get("metadata") or {})
    summary = _article_summary(chunk)
    haystack = _normalize_ascii(
        " ".join(
            [
                str(chunk.get("text") or ""),
                summary.get("title", ""),
                summary.get("path", ""),
                summary.get("category", ""),
                summary.get("subcategory", ""),
                str(metadata.get("keywords") or ""),
                str(metadata.get("section") or ""),
                str(metadata.get("article") or ""),
                str(metadata.get("chapter") or ""),
                str(metadata.get("responsible_office") or ""),
            ]
        )
    )
    return any(term in haystack for term in terms)


def _meaningful_search_terms(query: str) -> set[str]:
    stop = {"the", "and", "for", "with", "program", "programs", "article", "articles"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize_ascii(query))
        if len(token) >= 3 and token not in stop
    }


def _search_suggestions(query: str) -> list[str]:
    normalized = _normalize_ascii(query)
    if "engineering" in normalized:
        return ["College of Engineering Programs", "Programs & Curricular Offerings", "Undergraduate Programs"]
    if "ccs" in normalized or "computer" in normalized:
        return ["College of Computer Studies Programs", "BS Computer Science", "BS Information Technology"]
    if "excuse" in normalized or "absent" in normalized:
        return ["Excuse Slip", "Attendance"]
    if "tor" in normalized or "transcript" in normalized:
        return ["Transcript of Records", "Student Records"]
    if "portal" in normalized or "password" in normalized:
        return ["Student Portal", "Account Recovery", "Technical Support"]
    return ["Programs & Curricular Offerings", "Academic Policies", "Student Services"]


def _relevant_retrieved_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    if not chunks:
        return []
    top_score = max(float(chunk.relevance_score or 0) for chunk in chunks)
    cutoff = max(0.2, top_score - 0.45)
    return [chunk for chunk in chunks if float(chunk.relevance_score or 0) >= cutoff]


def _group_retrieved_chunks(chunks: list[RetrievedChunk], *, query: str | None = None) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        identity = derive_article_identity(metadata, chunk.text, query=query)
        group_key = identity.article_key
        summary = _article_summary(_chunk_dict_from_retrieved(chunk), query=query)
        score = chunk.reranked_score if chunk.reranked_score is not None else chunk.relevance_score
        section_key = _section_key(metadata, summary)

        if group_key not in grouped:
            if group_key.startswith("topic:"):
                summary["id"] = group_key
                summary["chunk_id"] = ""
            grouped[group_key] = {
                **summary,
                "relevance_score": score,
                "matching_sections": 0,
                "_sections": set(),
            }
            order.append(group_key)

        item = grouped[group_key]
        if score > float(item.get("relevance_score") or 0):
            item.update(summary)
            item["id"] = group_key
            item["chunk_id"] = ""
            item["relevance_score"] = score
        item["_sections"].add(section_key)
        item["matching_sections"] = len(item["_sections"])

    results = [grouped[key] for key in order]
    results.sort(key=lambda item: float(item.get("relevance_score") or 0), reverse=True)
    for item in results:
        item.pop("_sections", None)
    return results


def _chunk_dict_from_retrieved(chunk: RetrievedChunk) -> dict[str, Any]:
    return {
        "id": f"{chunk.document_id}::{chunk.chunk_index}",
        "text": chunk.text,
        "metadata": dict(chunk.metadata or {}),
    }


def _article_group_key(chunk: RetrievedChunk) -> str:
    metadata = dict(chunk.metadata or {})
    category = str(metadata.get("category") or "").strip()
    subcategory = str(metadata.get("subcategory") or "").strip()
    if category and subcategory:
        return _configured_article_id(category, subcategory)
    document_id = str(metadata.get("document_id") or chunk.document_id or "")
    article = str(metadata.get("article") or "").strip()
    if article:
        return f"{document_id}|article:{_normalize(article)}"
    title = str(metadata.get("title") or chunk.title or "").strip()
    source = str(metadata.get("source_filename") or chunk.source_filename or "").strip()
    return f"{document_id}|title:{_normalize(title)}|source:{_normalize(source)}"


def _section_key(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    for key in ("section", "article", "chapter", "appendix"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize(value)
    return _normalize(str(summary.get("title") or summary.get("id") or ""))


def _category_for_retrieved_chunk(chunk: RetrievedChunk) -> str:
    metadata = dict(chunk.metadata or {})
    path = _hierarchy_path(metadata)
    title = _display_title(metadata) or str(metadata.get("title") or chunk.title or "Untitled")
    return _category_from_metadata(metadata, path, title)


def _article_summary(chunk: dict[str, Any], *, query: str | None = None) -> dict[str, Any]:
    metadata = dict(chunk.get("metadata") or {})
    text = str(chunk.get("text") or "")
    identity = derive_article_identity(metadata, text, query=query)
    title = identity.article_title
    category = identity.category
    subcategory = str(metadata.get("subcategory") or "").strip()
    return {
        "id": identity.article_key,
        "chunk_id": str(chunk.get("id") or ""),
        "title": title,
        "path": identity.display_path,
        "category": category,
        "subcategory": subcategory,
        "article_key": identity.article_key,
        "derived_article_title": identity.article_title,
        "derived_section_title": identity.section_title,
        "matched_aliases": list(identity.aliases),
        "grouping_reason": identity.grouping_reason,
        "office": str(metadata.get("responsible_office") or metadata.get("office") or ""),
        "page": _page_number(metadata),
        "page_range": _page_range([metadata]),
        "source_document": _source_document(metadata),
        "source_filename": str(metadata.get("source_filename") or ""),
        "content_preview": _text_preview(text),
        "article_type": _article_type(metadata),
        "keywords": decode_keywords(metadata.get("keywords")),
    }


def _article_detail(chunk: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(chunk.get("metadata") or {})
    summary = _article_summary(chunk)
    return {
        **summary,
        "content": str(chunk.get("text") or ""),
        "text": str(chunk.get("text") or ""),
        "metadata": metadata,
    }


def _configured_article_groups(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for category in knowledge_base_taxonomy():
        for subcategory in category["subcategories"]:
            key = (_normalize(category["name"]), _normalize(subcategory["name"]))
            groups[key] = {
                "id": _configured_article_id(category["name"], subcategory["name"]),
                "chunk_id": "",
                "title": subcategory["name"],
                "path": f"{category['name']} > {subcategory['name']}",
                "category": category["name"],
                "subcategory": subcategory["name"],
                "office": subcategory["office"],
                "page": None,
                "source_filename": "",
                "content_preview": "Relevant indexed chunks will appear here once matching documents are ingested.",
                "article_type": "category_article",
                "matching_sections": 0,
                "keywords": subcategory.get("keywords") or [],
            }
    for chunk in chunks:
        article = _article_summary(chunk)
        key = (_normalize(article["category"]), _normalize(article.get("subcategory") or article["title"]))
        if key not in groups:
            groups[key] = {
                **article,
                "id": _configured_article_id(article["category"], article.get("subcategory") or article["title"]),
                "matching_sections": 0,
            }
        group = groups[key]
        group["matching_sections"] = int(group.get("matching_sections") or 0) + 1
        if article["content_preview"] and not group["content_preview"].startswith("Relevant indexed chunks"):
            continue
        group.update(
            {
                "chunk_id": article["chunk_id"],
                "page": article["page"],
                "source_filename": article["source_filename"],
                "content_preview": article["content_preview"],
                "article_type": article["article_type"],
            }
        )
    return sorted(groups.values(), key=lambda item: (_normalize(item["category"]), _normalize(item["title"])))


def _focused_article_groups(chunks: list[dict[str, Any]], *, query: str | None = None) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        metadata = dict(chunk.get("metadata") or {})
        identity = derive_article_identity(metadata, str(chunk.get("text") or ""), query=query)
        group_id = identity.article_key
        article = _article_summary(chunk, query=query)
        section_key = _section_key(metadata, article)
        if group_id not in groups:
            groups[group_id] = {
                **article,
                "id": group_id,
                "chunk_id": "",
                "matching_sections": 0,
                "_sections": set(),
                "_metadata_items": [],
            }
        group = groups[group_id]
        group["_sections"].add(section_key)
        group["_metadata_items"].append(metadata)
        group["matching_sections"] = len(group["_sections"])
        group["page_range"] = _page_range(group["_metadata_items"])
        if group.get("page") is None and article.get("page") is not None:
            group["page"] = article["page"]
        if not group.get("source_document") and article.get("source_document"):
            group["source_document"] = article["source_document"]
        if not group.get("source_filename") and article.get("source_filename"):
            group["source_filename"] = article["source_filename"]
        if not group.get("content_preview") and article.get("content_preview"):
            group["content_preview"] = article["content_preview"]

    for group in groups.values():
        group.pop("_sections", None)
        group.pop("_metadata_items", None)
    return sorted(groups.values(), key=lambda item: (_normalize(item["category"]), _normalize(item["title"])))


def _has_classified_chunks(chunks: list[dict[str, Any]]) -> bool:
    for chunk in chunks:
        metadata = dict(chunk.get("metadata") or {})
        if metadata.get("category") and metadata.get("subcategory"):
            return True
    return False


def _legacy_categories(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        article = _article_summary(chunk)
        grouped.setdefault(article["category"], []).append(article)

    items = []
    for name, articles in grouped.items():
        sample_titles = []
        for article in articles:
            if article["title"] not in sample_titles:
                sample_titles.append(article["title"])
            if len(sample_titles) == 4:
                break
        items.append(
            {
                "name": name,
                "article_count": len(articles),
                "sample_article_titles": sample_titles,
            }
        )

    items.sort(key=lambda item: (-item["article_count"], item["name"].lower()))
    return {"items": items, "total": len(items)}


def _configured_article_detail(article_id: str) -> dict[str, Any] | None:
    parsed = _parse_configured_article_id(article_id)
    if parsed is None:
        return None
    category, subcategory = parsed
    matching = [
        chunk
        for chunk in _store().list_chunks()
        if _normalize(str((chunk.get("metadata") or {}).get("category") or "")) == _normalize(category)
        and _normalize(str((chunk.get("metadata") or {}).get("subcategory") or "")) == _normalize(subcategory)
    ]
    configured = _configured_article_lookup(category, subcategory)
    if configured is None and not matching:
        return None
    office = (configured or {}).get("office") or _first_metadata_value(matching, "responsible_office", "office")
    content_blocks = []
    metadata_items = []
    for chunk in matching:
        metadata = dict(chunk.get("metadata") or {})
        title = _display_title(metadata) or str(metadata.get("title") or subcategory)
        page = _page_number(metadata)
        header = title if page is None else f"{title}\nPage: {page}"
        content_blocks.append(f"{header}\n\n{str(chunk.get('text') or '').strip()}")
        metadata_items.append(metadata)
    content = "\n\n---\n\n".join(block for block in content_blocks if block.strip())
    if not content:
        content = "No indexed chunks are available for this article yet."
    return {
        "id": article_id,
        "chunk_id": "",
        "title": subcategory,
        "path": f"{category} > {subcategory}",
        "category": category,
        "subcategory": subcategory,
        "office": office,
        "page": _page_number(metadata_items[0]) if metadata_items else None,
        "source_filename": _first_metadata_value(matching, "source_filename"),
        "content_preview": _text_preview(content),
        "article_type": "category_article",
        "matching_sections": len(matching),
        "content": content,
        "text": content,
        "metadata": {
            "category": category,
            "subcategory": subcategory,
            "office": office,
            "responsible_office": office,
            "chunk_count": len(matching),
        },
    }


def _focused_article_detail(article_id: str) -> dict[str, Any] | None:
    parsed = _parse_focused_article_id(article_id)
    if parsed is None:
        return None
    target_key = article_id if _looks_like_article_key(article_id) else f"{parsed[0]}:{parsed[2]}"
    chunks = _store().list_chunks()
    matching = [
        chunk
        for chunk in chunks
        if derive_article_identity(
            dict(chunk.get("metadata") or {}),
            str(chunk.get("text") or ""),
            query=None,
        ).article_key
        == target_key
    ]
    if not matching:
        return None

    summary = _focused_article_groups(matching)[0]
    content_blocks: list[str] = []
    metadata_items: list[dict[str, Any]] = []
    for chunk in matching:
        metadata = dict(chunk.get("metadata") or {})
        metadata_items.append(metadata)
        title = _display_title(metadata) or summary["title"]
        page = _page_number(metadata)
        header = title if page is None else f"{title}\nPage: {page}"
        content_blocks.append(f"{header}\n\n{str(chunk.get('text') or '').strip()}")
    content = "\n\n---\n\n".join(block for block in content_blocks if block.strip())
    category = str(summary.get("category") or parsed[0])
    subcategory = str(summary.get("subcategory") or parsed[1])
    return {
        **summary,
        "content": content,
        "text": content,
        "page_range": _page_range(metadata_items),
        "metadata": {
            "category": category,
            "subcategory": subcategory,
            "topic": summary["title"],
            "office": summary.get("office") or "",
            "responsible_office": summary.get("office") or "",
            "chunk_count": len(matching),
            "source_document": summary.get("source_document") or "",
            "page_range": _page_range(metadata_items),
        },
        "related_articles": _related_focused_articles(
            chunks,
            current_id=article_id,
            category=category,
            subcategory=subcategory,
        ),
    }


def _configured_article_lookup(category_name: str, subcategory_name: str) -> dict[str, Any] | None:
    for category in knowledge_base_taxonomy():
        if _normalize(category["name"]) != _normalize(category_name):
            continue
        for subcategory in category["subcategories"]:
            if _normalize(subcategory["name"]) == _normalize(subcategory_name):
                return subcategory
    return None


def _subcategory_counts(chunks: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for chunk in chunks:
        metadata = dict(chunk.get("metadata") or {})
        category = str(metadata.get("category") or "").strip()
        subcategory = str(metadata.get("subcategory") or "").strip()
        if category and subcategory:
            key = (_normalize(category), _normalize(subcategory))
            counts[key] = counts.get(key, 0) + 1
    return counts


def _configured_article_id(category: str, subcategory: str) -> str:
    return f"kb:{quote(category, safe='')}::{quote(subcategory, safe='')}"


def _focused_article_id(category: str, subcategory: str, topic: str) -> str:
    return f"topic:{_slug_value(category)}::{_slug_value(subcategory)}::{_slug_value(topic)}"


def _focused_article_id_from_metadata(metadata: dict[str, Any], *, fallback_chunk_id: str) -> str:
    return derive_article_identity(metadata, "", query=None).article_key


def _parse_configured_article_id(article_id: str) -> tuple[str, str] | None:
    if not article_id.startswith("kb:") or "::" not in article_id:
        return None
    category, subcategory = article_id[3:].split("::", 1)
    return unquote(category), unquote(subcategory)


def _parse_focused_article_id(article_id: str) -> tuple[str, str, str] | None:
    if _looks_like_article_key(article_id):
        category, title = article_id.split(":", 1)
        return category, "", title
    if not article_id.startswith("topic:") or article_id.count("::") != 2:
        return None
    category, subcategory, topic = article_id[6:].split("::", 2)
    return unquote(category), unquote(subcategory), unquote(topic)


def _looks_like_article_key(article_id: str) -> bool:
    return (
        ":" in article_id
        and "::" not in article_id
        and not article_id.startswith("kb:")
        and not article_id.startswith("topic:")
    )


def _focused_topic_title(metadata: dict[str, Any]) -> str:
    section = str(metadata.get("section") or "").strip()
    if section:
        title = _hierarchy_leaf_label(section)
        return _program_topic_title(metadata, title)
    path = str(metadata.get("hierarchy_path") or metadata.get("path") or "").strip()
    if path:
        title = _hierarchy_leaf_label(path)
        return _program_topic_title(metadata, title)
    article = str(metadata.get("article") or "").strip()
    if article:
        title = _hierarchy_leaf_label(article)
        return _program_topic_title(metadata, title)
    title = str(metadata.get("title") or "").strip()
    return _program_topic_title(metadata, title)


def _program_topic_title(metadata: dict[str, Any], title: str) -> str:
    cleaned = title.strip()
    category = str(metadata.get("category") or "")
    subcategory = str(metadata.get("subcategory") or "")
    if _normalize(category) != _normalize("Programs & Curricular Offerings"):
        return cleaned
    if _normalize(cleaned) == _normalize(subcategory) and _normalize("college of") in _normalize(cleaned):
        return f"{cleaned} Programs"
    return cleaned


def _focused_article_path(category: str, subcategory: str, title: str) -> str:
    parts = [category, subcategory]
    if _normalize(title) not in {_normalize(category), _normalize(subcategory)}:
        parts.append(title)
    return " > ".join(part for part in parts if part)


def _slug_value(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalize(value)).strip("-")
    return slug or "untitled"


def _related_focused_articles(
    chunks: list[dict[str, Any]],
    *,
    current_id: str,
    category: str,
    subcategory: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    related = []
    for article in _focused_article_groups(chunks):
        if article["id"] == current_id:
            continue
        if _normalize(article["category"]) != _normalize(category):
            continue
        if subcategory and _normalize(article.get("subcategory") or "") != _normalize(subcategory):
            continue
        related.append(
            {
                "id": article["id"],
                "title": article["title"],
                "category": article["category"],
                "subcategory": article.get("subcategory") or "",
                "page": article.get("page"),
                "page_range": article.get("page_range"),
            }
        )
        if len(related) == limit:
            break
    return related


def _first_metadata_value(chunks: list[dict[str, Any]], *keys: str) -> str:
    for chunk in chunks:
        metadata = dict(chunk.get("metadata") or {})
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _display_title(metadata: dict[str, Any]) -> str:
    for key in ("section", "article", "chapter", "appendix"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return _display_hierarchy_label(value)
    return ""


def _display_hierarchy_label(value: str) -> str:
    cleaned = value.strip()
    first_part = cleaned.split(">", 1)[0].strip()
    if ">" in cleaned and not re.match(
        r"^(chapter|article|sec\.?|section|appendix)\s+[\w.-]+",
        first_part,
        flags=re.I,
    ):
        return cleaned
    return cleaned.split(">", 1)[-1].strip()


def _hierarchy_leaf_label(value: str) -> str:
    cleaned = value.strip()
    leaf = cleaned.split(">")[-1].strip()
    return re.sub(
        r"^(chapter|article|sec\.?|section|appendix)\s*[\w.-]*\s*",
        "",
        leaf,
        flags=re.I,
    ).strip(" :-") or leaf


def _hierarchy_path(metadata: dict[str, Any]) -> str:
    parts = [
        str(metadata.get(key))
        for key in ("chapter", "article", "section", "appendix")
        if metadata.get(key)
    ]
    return " > ".join(parts)


def _category_from_metadata(metadata: dict[str, Any], path: str, title: str) -> str:
    for key in ("category", "chapter", "article", "doc_category"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return _category_from_path(value)
    return _category_from_path(path or title)


def _category_from_path(path: str) -> str:
    parts = [part.strip() for part in path.split(">") if part.strip()]
    for part in parts:
        cleaned = re.sub(
            r"^(chapter|article|sec\.?|section)\s*[\w.-]*\s*",
            "",
            part,
            flags=re.I,
        ).strip(" :-")
        if cleaned and not cleaned.isdigit():
            return cleaned
    return parts[0] if parts else "General"


def _page_number(metadata: dict[str, Any]) -> int | None:
    page = metadata.get("page_start") or metadata.get("page")
    if isinstance(page, int):
        return page
    if isinstance(page, str) and page.isdigit():
        return int(page)
    return None


def _page_range(metadata_items: list[dict[str, Any]]) -> str | None:
    pages = sorted({page for metadata in metadata_items if (page := _page_number(metadata)) is not None})
    if not pages:
        return None
    if len(pages) == 1:
        return str(pages[0])
    return f"{pages[0]}-{pages[-1]}"


def _source_document(metadata: dict[str, Any]) -> str:
    for key in ("source_document", "source_title", "title", "source_filename"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _article_type(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("content_type") or metadata.get("chunk_type") or metadata.get("document_type")
    return str(value) if value else None


def _text_preview(text: str, limit: int = 260) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def _normalize_ascii(value: str) -> str:
    normalized = _normalize(value).replace("ñ", "n")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        key = _normalize_ascii(cleaned)
        if cleaned and key not in seen:
            output.append(cleaned)
            seen.add(key)
    return output

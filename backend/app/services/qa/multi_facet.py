"""Grounding for multi-part questions, judged by retrieval rather than word lists.

Hard student questions bundle several unrelated procedures into one sentence
("I want OJT next term, but I still have an incomplete subject and unpaid
fees"). Plain top-k retrieval answers whichever part scores highest and drops
the rest, so the generator fills the gap by stretching an unrelated section --
for example explaining an INC with the scholastic-delinquency thresholds.

Nothing here knows what a campus topic is. A question is split into the parts
the student actually wrote, each part is put to the retriever on its own, and a
part counts as answered only when a section that ranked for *that part* survives
into the final context. The indexed documents therefore decide every judgement:
which sections belong to which part of the question, which parts went unanswered,
and which selected sections answer nothing that was asked. Publish new articles
and this improves with them, because the retriever sees them immediately.

Callers use this to widen retrieval, to hold confidence down when a part went
unanswered, and to tell the generator what it must not invent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

# How far down a part's own result list still counts as "this section is about
# that part of the question".
FACET_EVIDENCE_DEPTH = 3
# Sections that rank this highly for the whole question are never treated as
# foreign, even when no single part claims them.
BASELINE_EVIDENCE_DEPTH = 3
MAX_QUESTION_FACETS = 4
MIN_FACET_CONTENT_TOKENS = 2
MIN_CONTENT_TOKEN_LENGTH = 3

# Sentence ends and the conjunctions English uses to bolt separate asks together.
# Language-level, like the stopword set below; neither encodes campus policy.
_SENTENCE_SPLIT_RE = re.compile(r"[.;?!]+")
_COORDINATION_SPLIT_RE = re.compile(
    r",\s*(?:but|and|also|plus|then|while|however|though|although)\s+"
    r"|\s+(?:but|however|whereas|while)\s+",
    re.IGNORECASE,
)
_CONJUNCTION_SPLIT_RE = re.compile(r"\s+and\s+|\s*&\s*", re.IGNORECASE)

_CONTENT_STOPWORDS = frozenset(
    {
        "what", "which", "who", "whom", "how", "when", "where", "why", "the",
        "and", "but", "for", "of", "to", "in", "on", "at", "by", "with", "from",
        "about", "that", "this", "these", "those", "them", "there", "then",
        "also", "still", "just", "very", "much", "many", "some", "any", "all",
        "are", "was", "were", "been", "being", "have", "has", "had", "does",
        "did", "can", "could", "would", "should", "shall", "will", "may",
        "might", "must", "not", "you", "your", "yours", "our", "ours", "my",
        "mine", "me", "our", "please", "tell", "need", "want", "get", "got",
        "give", "said", "say", "says", "into", "out", "if", "because", "since",
        "while", "after", "before", "during", "than", "too", "now", "next",
        "last", "first", "one", "two", "other", "another", "same", "such",
        "like", "want", "wanted", "going", "goes", "still", "yet", "already",
    }
)


@dataclass(frozen=True)
class QuestionFacet:
    """One part of the question, in the student's own words."""

    key: str
    label: str
    retrieval_query: str


@dataclass(frozen=True)
class FacetEvidence:
    """Which retrieved sections ranked for which part of the question."""

    by_facet: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    baseline: tuple[str, ...] = ()

    def ranked_for(self, facet_key: str) -> tuple[str, ...]:
        return self.by_facet.get(facet_key, ())

    def claimed_keys(self) -> set[str]:
        """Every section some part of the question ranked for."""
        claimed: set[str] = set()
        for keys in self.by_facet.values():
            claimed.update(keys)
        return claimed

    def anchored_keys(self) -> set[str]:
        """Sections claimed by a part, or strong hits for the whole question."""
        return self.claimed_keys() | set(self.baseline)


EMPTY_EVIDENCE = FacetEvidence()


@dataclass(frozen=True)
class FacetCoverage:
    facets: tuple[QuestionFacet, ...] = ()
    covered: tuple[QuestionFacet, ...] = ()
    uncovered: tuple[QuestionFacet, ...] = ()
    precedence_question: bool = False
    conflict_question: bool = False
    # Headings of selected sections that answer nothing the question asked.
    off_topic: tuple[str, ...] = ()
    # True when the highest-ranked selected section is one of those.
    off_topic_lead: bool = False

    @property
    def is_multi_facet(self) -> bool:
        return len(self.facets) >= 2

    @property
    def has_gap(self) -> bool:
        return bool(self.uncovered) and self.is_multi_facet


_CONFLICT_PATTERNS: tuple[str, ...] = (
    r"\bdisagree(?:s|d|ment)?\b",
    r"\bconflict(?:s|ing)?\b",
    r"\bcontradict(?:s|ing|ory)?\b",
    r"\binconsistent\b",
    r"\bdo(?:es)?\s+not\s+match\b",
    r"\bdiffers?\b",
    r"\bsays?\s+something\s+different\b",
    r"\bwhich\s+one\s+(?:should|do)\s+(?:i|we|students?)\s+follow\b",
    r"\bwhich\s+(?:should|do)\s+(?:i|we|students?)\s+follow\b",
    r"\bwhich\s+(?:one\s+)?is\s+correct\b",
    r"\bversus\b",
    r"\bvs\.?\b",
)

_PRECEDENCE_PATTERNS: tuple[str, ...] = (
    r"\bfails?\s+first\b",
    r"\bcomes?\s+first\b",
    r"\b(?:which|what|who)\b[^?]{0,60}\bfirst\b",
    r"\bdo\s+first\b",
    r"\bwhat\s+order\b",
    r"\bwhich\s+order\b",
    r"\bcorrect\s+order\b",
    r"\bin\s+what\s+sequence\b",
    r"\bpriority\b",
    r"\bprioriti[sz]e\b",
    r"\bprecedence\b",
    r"\bwhich\s+(?:one\s+)?wins\b",
    r"\bwhich\s+(?:policy|rule|requirement)\s+(?:applies|governs|overrides)\b",
    r"\boverrides?\b",
    r"\bblocks?\s+(?:me|the|my)\b",
    r"\bbefore\s+the\s+other\b",
)


def split_question_facets(question: str) -> list[QuestionFacet]:
    """Break the question into the separate asks it contains.

    Only sentence boundaries and coordinating conjunctions are used, so the
    parts are the student's own wording. A split is kept only when every piece
    still carries enough words to retrieve on; "academic, clearance, or
    deployment" therefore stays whole instead of shattering into single words.
    """
    clauses: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(question or ""):
        for clause in _COORDINATION_SPLIT_RE.split(sentence):
            clauses.extend(_split_on_conjunction(clause))

    facets: list[QuestionFacet] = []
    seen: set[frozenset[str]] = set()
    for clause in clauses:
        label = _collapse(clause)
        tokens = _content_tokens(label)
        if len(tokens) < MIN_FACET_CONTENT_TOKENS:
            continue
        signature = frozenset(tokens)
        if signature in seen:
            continue
        seen.add(signature)
        facets.append(
            QuestionFacet(key=_slug(label), label=label, retrieval_query=label)
        )
        if len(facets) >= MAX_QUESTION_FACETS:
            break
    return facets


def facet_retrieval_queries(
    facets: Sequence[QuestionFacet],
    *,
    existing: Iterable[str] | None = None,
    limit: int = MAX_QUESTION_FACETS,
) -> list[str]:
    """Sub-queries that give every part of the question its own retrieval."""
    if len(facets) < 2:
        return []
    seen = {_collapse(value).lower() for value in (existing or [])}
    queries: list[str] = []
    for facet in facets[:limit]:
        folded = facet.retrieval_query.lower()
        if folded in seen:
            continue
        seen.add(folded)
        queries.append(facet.retrieval_query)
    return queries


def build_facet_evidence(
    by_query: Mapping[str, Sequence[str]],
    facets: Sequence[QuestionFacet],
    *,
    baseline_query: str | None = None,
    depth: int = FACET_EVIDENCE_DEPTH,
) -> FacetEvidence:
    """Record which sections each part of the question actually retrieved."""
    if len(facets) < 2:
        return EMPTY_EVIDENCE
    by_facet: dict[str, tuple[str, ...]] = {}
    for facet in facets:
        ranked = by_query.get(facet.retrieval_query) or ()
        if ranked:
            by_facet[facet.key] = tuple(ranked[:depth])
    baseline = tuple((by_query.get(baseline_query or "") or ())[:BASELINE_EVIDENCE_DEPTH])
    return FacetEvidence(by_facet=by_facet, baseline=baseline)


def partition_off_topic(
    facets: Sequence[QuestionFacet],
    chunks: Sequence[Any],
    evidence: FacetEvidence,
    *,
    key_of: Callable[[Any], str],
) -> tuple[list[Any], list[Any]]:
    """Demote candidates that no part of the question retrieved.

    Retrieval for "which requirement fails first" ranks Scholastic Delinquency
    highest on wording alone, even though the student never asked about failing
    grades. Sections that no part of the question found -- and that are not
    strong hits for the whole question -- go last instead of leading.
    """
    if len(facets) < 2:
        return list(chunks), []
    anchored = evidence.anchored_keys()
    if not anchored:
        return list(chunks), []
    on_topic: list[Any] = []
    off_topic: list[Any] = []
    for chunk in chunks:
        (on_topic if key_of(chunk) in anchored else off_topic).append(chunk)
    return on_topic, off_topic


def analyze_facet_coverage(
    question: str,
    facets: Sequence[QuestionFacet],
    selected_chunks: Sequence[Any],
    evidence: FacetEvidence,
    *,
    key_of: Callable[[Any], str],
    heading_of: Callable[[Any], str] | None = None,
) -> FacetCoverage:
    """Check which parts of the question the final context can actually answer."""
    selected_keys = [key_of(chunk) for chunk in selected_chunks]
    selected_set = set(selected_keys)

    # A single-part question is retrieved for as a whole, so there is no per-part
    # evidence to judge and nothing may be reported as unanswered.
    covered: list[QuestionFacet] = []
    uncovered: list[QuestionFacet] = []
    if len(facets) >= 2:
        for facet in facets:
            ranked = evidence.ranked_for(facet.key)
            if ranked and selected_set.intersection(ranked):
                covered.append(facet)
            else:
                uncovered.append(facet)

    off_topic: list[str] = []
    off_topic_lead = False
    if len(facets) >= 2:
        anchored = evidence.anchored_keys()
        claimed = evidence.claimed_keys()
        for index, chunk in enumerate(selected_chunks):
            key = selected_keys[index]
            if key in claimed or key in anchored:
                continue
            if index == 0:
                off_topic_lead = True
            heading = (heading_of(chunk) if heading_of else "") or ""
            if heading and heading not in off_topic:
                off_topic.append(heading)

    return FacetCoverage(
        facets=tuple(facets),
        covered=tuple(covered),
        uncovered=tuple(uncovered),
        precedence_question=is_precedence_question(question),
        conflict_question=is_conflict_question(question),
        off_topic=tuple(off_topic),
        off_topic_lead=off_topic_lead,
    )


def facet_recovery_keys(
    coverage: FacetCoverage,
    evidence: FacetEvidence,
    *,
    exclude: set[str] | None = None,
    limit: int = 2,
) -> list[str]:
    """Best-ranked section for each unanswered part, so no part is dropped."""
    if not coverage.is_multi_facet or not coverage.uncovered:
        return []
    taken = set(exclude or ())
    keys: list[str] = []
    for facet in coverage.uncovered:
        if len(keys) >= limit:
            break
        for key in evidence.ranked_for(facet.key):
            if key in taken:
                continue
            taken.add(key)
            keys.append(key)
            break
    return keys


def is_precedence_question(question: str) -> bool:
    """True when the question asks which requirement ranks or fails first."""
    normalized = _collapse(question).lower()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _PRECEDENCE_PATTERNS)


def is_conflict_question(question: str) -> bool:
    """True when the student is asking which of two disagreeing sources to follow."""
    normalized = _collapse(question).lower()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _CONFLICT_PATTERNS)


def build_grounding_notes(coverage: FacetCoverage) -> str:
    """Extra generator instructions for multi-part, ordering, and conflict questions."""
    if (
        not coverage.is_multi_facet
        and not coverage.precedence_question
        and not coverage.conflict_question
        and not coverage.off_topic_lead
    ):
        return ""

    lines: list[str] = []
    if coverage.is_multi_facet:
        parts = "; ".join(f'"{facet.label}"' for facet in coverage.facets)
        lines.append(
            f"- This question asks about several separate things ({parts}). "
            "Answer each one from the retrieved section that is actually about it, "
            "instead of merging them into a single rule."
        )
        lines.append(
            "- Do not explain one of them using a section written about a different "
            "process. A section states what it governs; if no retrieved section "
            "governs one of these, treat it as unanswered rather than borrowing "
            "another section's rules."
        )
    if coverage.precedence_question:
        lines.append(
            "- The user asks which requirement comes or fails first. State plainly that the "
            "documents do not rank these requirements unless a retrieved section explicitly "
            "defines that order, then explain each requirement and the office that handles it. "
            "Never invent a sequence, priority, or prerequisite that the context does not state."
        )
    if coverage.conflict_question:
        lines.append(
            "- The user is asking which of two disagreeing sources to follow. Do not declare a "
            "winner unless a retrieved section states which document governs. Say that the indexed "
            "documents do not settle the conflict, quote what each retrieved source actually says, "
            "and tell the user to confirm with the office that owns the process."
        )
    if coverage.off_topic:
        strayed = "; ".join(coverage.off_topic)
        lines.append(
            f"- Some retrieved sections answer nothing the user asked ({strayed}). "
            "Ignore them unless they directly answer the question; do not build the answer around them."
        )
    if coverage.has_gap:
        missing = "; ".join(f'"{facet.label}"' for facet in coverage.uncovered)
        lines.append(
            f"- Nothing in the retrieved context is about: {missing}. Say that this is not covered "
            "by the indexed documents and point the user to the responsible office instead of guessing."
        )
    return "\n".join(lines)


def distinct_source_articles(
    chunks: Sequence[Any],
    *,
    article_of: Callable[[Any], str],
) -> tuple[str, ...]:
    """Distinct article breadcrumbs present in the selected context."""
    labels: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        label = _collapse(article_of(chunk) or "")
        if not label:
            continue
        # Identity is the leading "Article N ..." segment when present.
        identity = label.split(">", 1)[0].strip()
        key = identity.casefold()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
    return tuple(labels)


def build_cross_article_notes(articles: Sequence[str]) -> str:
    """Warn the generator when selected sections come from different articles.

    Article labels are read from chunk metadata written at ingest. Nothing here
    names a campus office or asserts which article governs a process.
    """
    if len(articles) < 2:
        return ""
    listed = "; ".join(articles)
    return (
        f"- The retrieved context includes sections from different document articles ({listed}). "
        "Treat each article as its own process. Do not merge their steps, offices, or "
        "requirements into one procedure unless a retrieved section explicitly links them."
    )


def combine_grounding_notes(*parts: str) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _split_on_conjunction(clause: str) -> list[str]:
    """Split "an incomplete subject and unpaid fees", keep "academic or fees" whole."""
    pieces = [piece for piece in _CONJUNCTION_SPLIT_RE.split(clause) if piece.strip()]
    if len(pieces) < 2:
        return [clause]
    if all(len(_content_tokens(piece)) >= MIN_FACET_CONTENT_TOKENS for piece in pieces):
        return pieces
    return [clause]


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9.]*", (text or "").casefold())
        if len(token) >= MIN_CONTENT_TOKEN_LENGTH and token not in _CONTENT_STOPWORDS
    }


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip(" \t\n\r-–—,:;")).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:80]

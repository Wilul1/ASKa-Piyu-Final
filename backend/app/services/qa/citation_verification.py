"""Citation Grounding V2 -- semantic, claim-level evidence verification.

RETRIEVED CONTEXT != DISPLAYED CITATIONS. Citation V1 (the existing
``_select_supporting_context`` in ``question_answering.py``) decides what
to display using keyword/number-overlap scoring against already-retrieved
candidates. That scorer cannot tell a chunk that actually establishes a
claim from one that merely shares vocabulary, a number, an office, or a
title with it -- the Fresh Gold V1 baseline demonstrated concrete failures
of exactly that kind (an irrelevant same-office citation displayed next to
a correct answer; a near-duplicate service variant's citation displayed and
used as if it answered a different variant's question).

This module replaces that decision -- for callers that opt in via
``citation_verification_mode`` -- with a single batched LLM call that
checks ENTAILMENT ("does this specific chunk establish this specific
claim?"), never mere relevance, over a fixed, deterministic allowlist of
citation_ids taken only from chunks already retrieved and authorized for
this request. It never performs a fresh Chroma query and never receives
any chunk the caller did not already authorize.

FAIL-CLOSED CONTRACT (mandatory): ``verify_citations`` never raises. Any
failure -- timeout, network error, non-2xx, malformed JSON, a schema
violation, an unknown claim_id, a hallucinated citation_id -- is caught
internally and produces a result with ``verified_citation_ids == []``.
The caller's answer text is never regenerated and never blocked because of
a verification failure; only the displayed-citations list is affected.

LIMITATION (documented, not fixed here): this module can only judge
whether evidence already made available to the generator actually supports
what the final answer says. It cannot invent better evidence the generator
never saw, and it cannot correct a wrong answer caused by retrieval or
context selection choosing the wrong near-duplicate chunk upstream. If the
generator was only ever given chunk A and asserted something based on it,
V2 can confirm or deny that A supports that specific claim -- it cannot
substitute in chunk B just because B would have been the right evidence.
That class of fix belongs to a later, separate context-selection phase.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import llm_extra_headers, settings

logger = logging.getLogger(__name__)


class CitationVerificationError(RuntimeError):
    """Internal-only: always caught inside ``verify_citations`` and turned
    into a fail-closed result. Never escapes this module.

    ``diagnostics``, when provided, is a small, bounded, JSON-safe dict of
    STRUCTURAL facts only (counts/categories/booleans -- see
    ``_build_malformed_json_diagnostics``) -- never raw provider content,
    never document/question/answer text. Currently only set for
    ``malformed_json`` failures; every other raise site leaves it ``None``.

    ``provider_diagnostics``, when provided, is a separate, equally small
    and bounded dict describing a provider/transport-layer failure (see
    ``_build_provider_diagnostics``) -- an HTTP status integer and a fixed
    ``provider_error_kind`` string, never a response body, error message,
    or raw exception text. Only set at provider-facing raise sites in
    ``_call_verifier``; every other raise site leaves it ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        diagnostics: dict[str, Any] | None = None,
        provider_diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
        self.provider_diagnostics = provider_diagnostics


# --- claim extraction (deterministic, no LLM call) --------------------------

# Unlike question_answering.py's ``_answer_claims`` (which splits on every
# ``.``), this protects decimal numbers ("P75.00", "3.5") from being cut in
# half by only splitting on '.', '!', '?', ';' when NOT flanked by digits on
# both sides; '\n' always splits.
_CLAIM_SPLIT_RE = re.compile(r"(?<!\d)[.!?;](?!\d)|\n+")
_MIN_CLAIM_CHARS = 4
# Soft ceiling so qualifier propagation cannot inflate a claim into a
# paragraph-sized blob. Prefers dropping the prepend over truncating facts.
_MAX_CLAIM_CHARS = 600
_MAX_QUALIFIER_CHARS = 120

# Conservative, deterministic filter for spans that do not assert a
# checkable fact -- greetings, transition phrases, explicit "not found"
# language, and generic advice to contact an office. Matched against the
# span with any leading markdown bullet/bold decoration stripped, anchored
# at the start so a real factual clause appended after one of these openers
# is not silently swallowed by a match on the whole (longer) span -- the
# splitter already isolates clauses, so in practice each matched span is
# just the opener itself.
_NON_FACTUAL_RE = re.compile(
    r"^(?:"
    r"sure|okay|ok|hi|hello|welcome to lspu"
    r"|here'?s how [^.]*?works?"
    r"|i'?d love to help\b.*"
    r"|i (?:couldn'?t|could not|don'?t|do not) (?:find|see|have)\b.*"
    r"|(?:the )?(?:indexed )?(?:lspu )?documents(?: i have access to)? "
    r"(?:don'?t|do not) (?:contain|cover|specify|state|give|describe)\b.*"
    r"|(?:the )?retrieved (?:lspu )?documents(?: for this turn)? "
    r"(?:don'?t|do not) contain\b.*"
    r"|if you (?:need|have)\b.*"
    r"|(?:you can|feel free to|i'?d be happy to)\b.*"
    r"|in short\b.*|to summarize\b.*|so,? (?:in short|bottom line)\b.*"
    r"|one (?:note|thing to keep in mind)\b.*"
    r"|for more information\b.*"
    r")\s*$",
    re.I,
)
_LEADING_DECORATION_RE = re.compile(r"^[\s\-\*•]+")
# Single-marker list prefix only ("- ", "* ", "• ") -- never raw "**"/"__".
_BULLET_PREFIX_RE = re.compile(r"^([\-\*•]\s+)")
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+")
# Whole-span balanced emphasis. Trailing ":" may sit inside or just after close.
_BOLD_WRAPPER_RE = re.compile(r"^\*\*(.+?)\*\*:?\s*$")
_UNDERSCORE_WRAPPER_RE = re.compile(r"^__(.+?)__:?\s*$")
# Structural "section label" shapes -- not a domain taxonomy. Used only to
# decide whether a short span is context for following bullets/clauses.
_HEADING_LIKE_MAX_CHARS = 80
# Finite / obligation verbs that mark a span as a factual clause rather than
# a bare section title ("Course Substitution" vs "The fee is None").
_FACT_CLAUSE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|must|shall|will|can|may|should|"
    r"requires?|required|need(?:s|ed)?|takes?|taken|costs?|"
    r"includes?|included|submit(?:s|ted)?|provide[sd]?|pay(?:s|ed|ment)?|"
    r"issued?|handled?|applies|applied|allowed|entitled|"
    r"get|gets|got|bring|brings|brought|receive[sd]?|have|has|had)\b",
    re.I,
)
# Ordinary prose openers -- bare section titles are labels, not sentences.
_SENTENCE_OPENER_RE = re.compile(
    r"^(?:you|we|i|they|he|she|it|the|a|an|as|if|when|while|"
    r"after|before|during|to|please|there|this|that|these|those|"
    r"here|also|then|so|because|since|although|though)\b",
    re.I,
)
# True section breaks / neutral epilogues. Never become semantic qualifiers;
# as standalone headings they CLEAR any stale audience/procedure qualifier.
_GENERIC_CLEAR_CONTEXT_RE = re.compile(
    r"^(?:"
    r"additional(?:\s+information|\s+context|\s+details)?"
    r"|more information"
    r"|summary|overview|process overview"
    r"|related(?:\s+policy|\s+policies|\s+context)?"
    r")\s*$",
    re.I,
)
# Nested informational scaffolds inside an audience/procedure block. Never
# become semantic qualifiers themselves and never enter claim text, but they
# PRESERVE the active qualifier (Requirements/Steps under Alumni, etc.).
# Notes / Important / Reminder are treated the same: they typically annotate
# the current procedure rather than starting an unrelated section.
_GENERIC_PRESERVE_CONTEXT_RE = re.compile(
    r"^(?:"
    r"key points(?:\s+to\s+remember)?"
    r"|important(?:\s+clarification|\s+notes?)?"
    r"|notes?|details|next steps|steps|procedure"
    r"|form required|key requirements(?:\s*&\s*process)?"
    r"|required documents|requirements|process"
    r"|clarification|reminder"
    r")\s*$",
    re.I,
)
# Lightweight person-category cues. Kept small and grammatical ("for X" /
# "as a/an X" / short heading that IS the category) -- not an LSPU catalog.
_AUDIENCE_CUE_RE = re.compile(
    r"(?:"
    r"\b(?:for|as)\s+(?:an?\s+|the\s+)?"
    r"(?:lspu\s+)?"
    r"(?:alumni|alumnus|alumna|undergraduate|graduate|transferee|"
    r"faculty|student|applicant|staff|employee)s?\b"
    r"|\b(?:alumni|alumnus|alumna|undergraduate|graduate|transferee|"
    r"faculty|applicant)s?\b"
    r")",
    re.I,
)


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str


def _unwrap_balanced_emphasis(text: str) -> str:
    """Unwrap a whole-span ``**…**`` / ``__…__`` wrapper; leave bullets alone."""
    cleaned = (text or "").strip()
    for pattern in (_BOLD_WRAPPER_RE, _UNDERSCORE_WRAPPER_RE):
        m = pattern.match(cleaned)
        if m:
            return m.group(1).strip()
    return cleaned


def _strip_markdown_label(text: str) -> str:
    """Normalize a heading/label for qualifier use: drop #, **…**, trailing :."""
    cleaned = (text or "").strip()
    cleaned = _MARKDOWN_HEADING_RE.sub("", cleaned).strip()
    cleaned = _unwrap_balanced_emphasis(cleaned)
    cleaned = cleaned.strip().rstrip(":").strip()
    return cleaned


def _normalize_for_claim_classify(text: str) -> str:
    """Prepare a split span for heading/non-factual classification.

    Order matters: unwrap balanced Markdown emphasis *before* stripping list
    markers so ``**Heading**`` is not mangled into ``Heading**`` by a greedy
    leading-``*`` strip. Single-marker bullets (``* item``) remain bullets.
    """
    cleaned = (text or "").strip()
    cleaned = _MARKDOWN_HEADING_RE.sub("", cleaned).strip()
    cleaned = _unwrap_balanced_emphasis(cleaned)
    cleaned = _BULLET_PREFIX_RE.sub("", cleaned).strip()
    # Legacy multi-marker strip for leftover decorative runs (not ``**``).
    cleaned = _LEADING_DECORATION_RE.sub("", cleaned).strip()
    return cleaned


def _is_clause_shaped(text: str) -> bool:
    """True when a span looks like a factual sentence/clause, not a label."""
    t = (text or "").strip()
    if not t:
        return False
    if re.search(r"[.!?]", t):
        return True
    if _FACT_CLAUSE_RE.search(t) or _SENTENCE_OPENER_RE.match(t):
        return True
    return False


def _is_bare_section_title(text: str) -> bool:
    """Short non-clause label (e.g. ``Course Substitution``, ``ID Validation``)."""
    t = (text or "").strip()
    if not t or len(t) > _HEADING_LIKE_MAX_CHARS:
        return False
    if ":" in t or re.search(r"[.!?]", t):
        return False
    if _is_clause_shaped(t):
        return False
    return 1 <= len(t.split()) <= 10


def _is_heading_like(classify_as: str) -> bool:
    """Structural section-label detector (markdown / bold / colon / bare title).

    ``classify_as`` should already be emphasis-unwrapped when possible. Bold
    wrappers that still arrive here are accepted only when their *inner*
    text is label-shaped -- ``**TOR is required.**`` stays a fact.
    """
    text = (classify_as or "").strip()
    if not text or len(text) > _HEADING_LIKE_MAX_CHARS:
        return False
    if _MARKDOWN_HEADING_RE.match(text):
        inner = _MARKDOWN_HEADING_RE.sub("", text).strip()
        return bool(inner) and not _is_clause_shaped(inner)
    for pattern in (_BOLD_WRAPPER_RE, _UNDERSCORE_WRAPPER_RE):
        m = pattern.match(text)
        if m:
            inner = m.group(1).strip().rstrip(":").strip()
            if _is_clause_shaped(inner):
                return False
            return bool(inner) and (
                _is_bare_section_title(inner)
                or (":" not in m.group(1) and not _is_clause_shaped(inner))
            )
    bare = text.rstrip(":").strip() if text.endswith(":") else text
    if text.endswith(":") and "." not in text and not _is_clause_shaped(bare):
        return True
    # Bare section title on its own line (e.g. "Course Substitution",
    # "Issuance of Good Moral Certificate (Alumni)"). Reject clause-shaped
    # spans so ordinary facts are never swallowed as context.
    return _is_bare_section_title(text)


def _is_generic_context_label(label: str) -> bool:
    """True for any layout label that must not become a semantic qualifier."""
    cleaned = (label or "").strip()
    return bool(
        _GENERIC_CLEAR_CONTEXT_RE.match(cleaned)
        or _GENERIC_PRESERVE_CONTEXT_RE.match(cleaned)
    )


def _clears_active_semantic_context(label: str) -> bool:
    """True for neutral section breaks that end stale audience/procedure scope."""
    return bool(_GENERIC_CLEAR_CONTEXT_RE.match((label or "").strip()))


def _is_semantic_context_label(label: str) -> bool:
    """True when a heading-like label carries audience/procedure identity.

    Generic layout labels (both clear-break and nested-scaffold) are rejected
    as qualifiers. Audience cues always qualify. Other short non-generic
    headings (e.g. "Course Substitution", "Shifting", "ID Validation")
    qualify structurally so near-duplicate procedure sections reset context
    without a domain taxonomy.
    """
    cleaned = _strip_markdown_label(label)
    if not cleaned or _is_generic_context_label(cleaned):
        return False
    if _AUDIENCE_CUE_RE.search(cleaned):
        return True
    # Non-generic short heading with at least one content word.
    return bool(re.search(r"[A-Za-z]{3,}", cleaned))


def _context_only_span(classify_as: str) -> bool:
    """Heading/label with no attached factual clause -- use as context only."""
    if not _is_heading_like(classify_as):
        return False
    # A heading-like span that still embeds a clause after a colon on the
    # same line ("For Alumni: TOR is required") is NOT context-only.
    stripped = _strip_markdown_label(classify_as)
    raw = (classify_as or "").strip()
    if ":" in raw.rstrip(":"):
        # e.g. "Fee: None" is a fact, not a section label.
        after = raw.split(":", 1)[1].strip()
        after = _unwrap_balanced_emphasis(after)
        if after and not _is_heading_like(after) and len(after) >= _MIN_CLAIM_CHARS:
            return False
    # Pure labels / markdown headings (bool -- never return a Match object).
    return bool(
        _MARKDOWN_HEADING_RE.match(raw)
        or _BOLD_WRAPPER_RE.match(raw)
        or _UNDERSCORE_WRAPPER_RE.match(raw)
        or raw.endswith(":")
        or (len(stripped) <= _HEADING_LIKE_MAX_CHARS and "." not in stripped)
    )


def _prepend_qualifier(claim_text: str, qualifier: str | None) -> str:
    """Attach active section context when the claim does not already carry it.

    Preserves a leading bullet marker. Skips prepend when the result would
    exceed ``_MAX_CLAIM_CHARS`` (keeps the atomic fact, drops the qualifier).
    """
    if not qualifier:
        return claim_text
    q = qualifier.strip()
    if not q or len(q) > _MAX_QUALIFIER_CHARS:
        return claim_text
    bullet = ""
    body = claim_text
    m = _BULLET_PREFIX_RE.match(claim_text or "")
    if m:
        bullet = m.group(1)
        body = claim_text[m.end() :]
    body_cf = (body or "").casefold()
    q_cf = q.casefold()
    # Already scoped at the start (avoid "Alumni: For Alumni: …"). Do NOT use
    # a bare substring check -- "Shifting" appears inside "shifting form".
    if body_cf.startswith(q_cf) and (
        len(body_cf) == len(q_cf)
        or not body_cf[len(q_cf)].isalnum()
    ):
        return claim_text
    candidate = f"{bullet}{q}: {body}".strip()
    if len(candidate) > _MAX_CLAIM_CHARS:
        return claim_text
    return candidate


def _claim_surface_text(original: str, classify_as: str) -> str:
    """Emit claim text without leftover ``**`` / ``__`` from Markdown splits.

    Preserves a leading list marker. Uses the classification-normalized body
    when the span was emphasis-wrapped or left with an orphan opener after
    ``.``/``!``/``?`` splitting (e.g. ``**TOR is required.**`` → ``**TOR is required``).
    """
    text = original or ""
    m = _BULLET_PREFIX_RE.match(text)
    bullet = m.group(1) if m else ""
    raw_body = text[m.end() :] if m else text
    raw_stripped = raw_body.strip()
    if (
        _BOLD_WRAPPER_RE.match(raw_stripped)
        or _UNDERSCORE_WRAPPER_RE.match(raw_stripped)
        or raw_stripped.startswith("**")
        or raw_stripped.startswith("__")
    ):
        return f"{bullet}{classify_as}".strip()
    return text.strip()


def extract_claims(answer: str) -> list[Claim]:
    """Split the FINAL answer into atomic, claim-sized spans.

    Conservative by design: a span is dropped only when it is too short to
    be a checkable fact or clearly matches a non-factual pattern (greeting,
    transition, "not found" language, generic advice). A wrongly-kept
    conversational span costs nothing but one unnecessary verifier lookup
    (it will correctly end up with zero supporting citations either way);
    a wrongly-dropped factual span is the failure mode worth avoiding, so
    the patterns above are deliberately narrow and anchored.

    Qualifier propagation (Fresh Gold near-duplicate finding): when a
    heading/lead establishes audience or procedure identity, that minimum
    context is prepended to following atomic claims until a new semantic
    section replaces it. Generic layout headings never become qualifiers and
    never appear in claim text. Nested scaffolds (Requirements, Steps,
    Procedure, Notes, …) preserve the active qualifier; true section breaks
    (Additional Information, Summary, …) clear it. Propagation never merges
    unrelated procedures into one claim and never copies the whole answer.
    """
    claims: list[Claim] = []
    index = 0
    active_qualifier: str | None = None
    for part in _CLAIM_SPLIT_RE.split(answer or ""):
        text = part.strip()
        if len(text) < _MIN_CLAIM_CHARS:
            continue
        # Emphasis unwrap before bullet strip -- see _normalize_for_claim_classify.
        classify_as = _normalize_for_claim_classify(text)
        if _NON_FACTUAL_RE.match(classify_as):
            continue

        # Section labels: update / preserve / clear context; never emit as claims.
        if _context_only_span(classify_as):
            label = _strip_markdown_label(classify_as)
            if _is_semantic_context_label(label):
                active_qualifier = label[:_MAX_QUALIFIER_CHARS]
            elif _clears_active_semantic_context(label):
                # Neutral epilogue ("Additional Information", "Summary").
                active_qualifier = None
            # else: nested scaffold ("Requirements", "Steps", …) -- preserve.
            continue

        claim_body = _claim_surface_text(text, classify_as)
        claim_text = _prepend_qualifier(claim_body, active_qualifier)
        if len(claim_text) < _MIN_CLAIM_CHARS:
            continue
        index += 1
        claims.append(Claim(claim_id=f"c{index}", text=claim_text))
    return claims


# --- candidate evidence ------------------------------------------------------


@dataclass(frozen=True)
class CandidateEvidence:
    """One already-retrieved, already-authorized chunk the verifier may cite.

    Callers must build this list only from chunks already authorized for
    the current request (the same ``candidates`` V1's own selector uses) --
    this module performs no authorization of its own and trusts the caller
    on that boundary, exactly as ``_select_supporting_context`` already does.
    """

    citation_id: str
    title: str
    source_section: str | None
    source_filename: str | None
    text: str


_MAX_EVIDENCE_CHARS = 700


# --- verifier outcome ---------------------------------------------------------


@dataclass
class VerificationOutcome:
    mode: str
    claims: list[Claim] = field(default_factory=list)
    candidate_citation_ids: list[str] = field(default_factory=list)
    verifier_invoked: bool = False
    verifier_succeeded: bool = False
    failure_reason: str | None = None
    per_claim_verified_ids: dict[str, list[str]] = field(default_factory=dict)
    verified_citation_ids: list[str] = field(default_factory=list)
    latency_ms: float | None = None
    usage: dict[str, Any] | None = None
    # Bounded, privacy-safe structural facts about a malformed_json failure
    # (counts/categories/booleans -- never raw content). None for every
    # other outcome, including success. See CitationVerificationError's own
    # docstring and _build_malformed_json_diagnostics.
    failure_diagnostics: dict[str, Any] | None = None
    # Bounded, privacy-safe facts about a provider/transport-layer failure
    # (provider_error_kind + http_status only). None for every other
    # outcome, including success and malformed_json. See
    # CitationVerificationError's own docstring and
    # _build_provider_diagnostics.
    provider_diagnostics: dict[str, Any] | None = None


def build_per_claim_supporting_ids_diagnostic(
    outcome: VerificationOutcome,
    *,
    allowlist: set[str] | None = None,
) -> list[list[str]]:
    """Privacy-safe claim_index → allowlisted real citation_ids (diagnostics).

    Each outer list index is the claim order in ``outcome.claims`` (0-based).
    Inner lists are real CandidateEvidence citation_ids already accepted by
    ``_parse_and_validate`` (alias→real + allowlist), re-filtered here for
    defense in depth. Never includes claim text, evidence text, question,
    answer, provider content, or call-local S1/S2 aliases.

    On verifier failure ``outcome.per_claim_verified_ids`` is empty; this
    returns ``[]`` (no claim rows) so callers cannot mistake a failed
    response for "every claim unsupported."
    """
    if not outcome.verifier_succeeded:
        return []
    allowed = (
        set(allowlist)
        if allowlist is not None
        else set(outcome.candidate_citation_ids or [])
    )
    rows: list[list[str]] = []
    for claim in outcome.claims:
        raw_ids = outcome.per_claim_verified_ids.get(claim.claim_id, [])
        clean: list[str] = []
        seen: set[str] = set()
        for cid in raw_ids:
            if not isinstance(cid, str) or cid not in allowed:
                continue
            if cid in seen:
                continue
            seen.add(cid)
            clean.append(cid)
        rows.append(clean)
    return rows


# --- verifier prompt ----------------------------------------------------------

_VERIFIER_SYSTEM_PROMPT = """
You are a strict evidence-verification system for a citation grounding
pipeline. You are given a final answer already shown to a user, split into
atomic claims, and a fixed list of candidate evidence chunks that were
already retrieved and available when that answer was generated.

Your ONLY job: for each claim, decide which candidate chunks (if any)
actually ENTAIL / DIRECTLY ESTABLISH that specific claim's factual
content. You are checking support, not relevance.

A chunk does NOT support a claim merely because it:
- shares keywords or vocabulary with the claim
- contains the same number as the claim
- belongs to the same office/department as the claim's topic
- has a similar or overlapping title
- concerns the same broad topic or procedure family
- was ranked highly during retrieval
- was used somewhere in generating the answer

Many candidate chunks describe near-duplicate procedures that must be told
apart precisely, by:
- which category of person the chunk applies to (e.g. undergraduate vs.
  alumnus vs. transferee; student vs. faculty)
- which specific office or division actually issues or handles it
- which specific procedure or service it is, not just the same broad
  service family
- the policy's actual scope and conditions
- timing or deadline windows
- what a shared number actually measures -- a percentage, a unit count, a
  day count, and a peso amount are never interchangeable even when the
  digits match

If a claim is not clearly and specifically established by a candidate
chunk's own text, do not include that chunk for that claim, even if it is
the closest available option. It is correct and expected for a claim to
end up with zero supporting citation_ids.

Only use citation_ids that appear in the candidate list below. Never
invent, guess, abbreviate, or modify a citation_id.

Respond with ONLY a single JSON object, no prose, no markdown fences,
matching exactly this shape:

{"claims": [{"claim_id": "<id>", "supporting_citation_ids": ["<id>", ...]}]}

Include exactly one entry per claim_id you were given. Use an empty list
when no candidate supports that claim.
""".strip()

# --- citation aliases --------------------------------------------------------

# Real citation_id values are long, compound, provider-facing identifiers
# (e.g. "30875c07-409e-45ea-989e-3315a85608c1::58" or
# "faq:bf4a12ed-78c9-4f8e-8264-03ffe577f888::1") that a model must reproduce
# character-for-character to be trusted. Asking for exact reproduction of a
# long punctuation-heavy token is an avoidable, confirmed reliability risk
# (see citation_v2_verifier_id_integrity_investigation.json) -- claim_ids
# already avoid this by being short server-generated aliases ("c1", "c2",
# ...); citation_ids did not. These S1/S2/... aliases give citation_ids the
# same property: short, low-entropy, call-local tokens the model only has to
# SELECT, never transcribe. Built fresh for every verify_citations call, in
# candidate order, from the exact authoritative `candidates` list supplied
# for that call -- never persisted, never reused across calls, never exposed
# outside this module.
def _build_citation_aliases(candidates: list[CandidateEvidence]) -> list[str]:
    return [f"S{i}" for i in range(1, len(candidates) + 1)]


# --- verifier response schema (per-call, enum-constrained) -------------------

# Requests the provider constrain its OWN generation to this exact shape
# AND to only the alias/claim_id values that are actually valid for this one
# call (OpenRouter's documented response_format=json_schema "enum" support --
# verified against the currently configured model's own listed accepted
# parameters, per the investigation this change is based on). Defense in
# depth, not a trust boundary: _parse_and_validate() below still
# independently re-validates every field from scratch regardless of whether
# the provider actually honored this constraint -- this can only IMPROVE the
# odds of getting a valid response, it never substitutes for or weakens that
# validation. If the configured provider/model combination does not actually
# support this (contrary to what it lists), OpenRouter's own documented
# behavior is to fail the request with an HTTP error -- which the existing
# httpx.HTTPError handler below already maps to failure_category=
# "provider_error", not a new/unhandled failure shape.
def _build_verifier_response_schema(
    claim_ids: list[str], citation_aliases: list[str]
) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "citation_verification_claims",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim_id": {"type": "string", "enum": claim_ids},
                                "supporting_citation_ids": {
                                    "type": "array",
                                    "items": {"type": "string", "enum": citation_aliases},
                                },
                            },
                            "required": ["claim_id", "supporting_citation_ids"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["claims"],
                "additionalProperties": False,
            },
        },
    }


def _build_verifier_messages(
    claims: list[Claim], candidates: list[CandidateEvidence], citation_aliases: list[str]
) -> list[dict[str, str]]:
    claims_payload = [{"claim_id": c.claim_id, "text": c.text} for c in claims]
    candidates_payload = [
        {
            "citation_id": alias,
            "title": c.title,
            "source_section": c.source_section,
            "source_filename": c.source_filename,
            "text": (c.text or "")[:_MAX_EVIDENCE_CHARS],
        }
        for alias, c in zip(citation_aliases, candidates)
    ]
    user_content = (
        "CLAIMS:\n"
        + json.dumps(claims_payload, ensure_ascii=False, indent=2)
        + "\n\nCANDIDATE EVIDENCE (allowlist -- use only these citation_ids):\n"
        + json.dumps(candidates_payload, ensure_ascii=False, indent=2)
    )
    return [
        {"role": "system", "content": _VERIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _build_provider_diagnostics(
    *,
    kind: str,
    http_status: int | None = None,
    provider_error_code: str | None = None,
    provider_error_type: str | None = None,
) -> dict[str, Any]:
    """Bounded, JSON-safe facts about a provider/transport-layer failure --
    a fixed ``provider_error_kind`` string (``"http_status"`` / ``"timeout"``
    / ``"transport"`` / ``"not_configured"``), and, only for
    ``"http_status"``, the exact HTTP status code plus two OpenRouter-
    documented machine-readable fields (see
    https://openrouter.ai/docs/api_reference/errors-and-debugging):
    ``error.metadata.provider_code`` (the upstream provider's own error
    code) and ``error.metadata.error_type`` (OpenRouter's own canonical,
    cross-provider-stable error category). Never a response body, the
    human-readable ``error.message``, or raw exception text -- these two
    fields plus the status code are the documented, bounded, machine-
    readable surface OpenRouter itself designates for programmatic error
    handling.
    """
    return {
        "provider_error_kind": kind,
        "http_status": http_status,
        "provider_error_code": provider_error_code,
        "provider_error_type": provider_error_type,
    }


_MAX_PROVIDER_ERROR_FIELD_LENGTH = 100


def _extract_openrouter_error_fields(response: httpx.Response) -> tuple[str | None, str | None]:
    """Best-effort, privacy-safe extraction of OpenRouter's own documented
    machine-readable error fields, ``error.metadata.error_type`` and
    ``error.metadata.provider_code``, from a non-2xx JSON error body.

    Deliberately narrow: reads ONLY these two specific, named, documented
    keys -- never ``error.message`` (explicitly documented as human-
    readable), never any other key inside ``error.metadata`` (which the
    schema allows to hold arbitrary provider-supplied data, e.g. a
    guardrail block's ``patterns`` list), and never the response body as a
    whole. Each extracted value is also type- and length-bounded before
    use, so a provider returning something unexpected (wrong type,
    oversized string) safely yields ``None`` rather than being trusted or
    truncated-and-kept.

    Any failure at any step -- non-JSON body, unexpected shape, wrong
    types -- returns ``(None, None)``. This function must never raise;
    diagnostic parsing must never affect verification behavior.
    """
    try:
        body = response.json()
        if not isinstance(body, dict):
            return None, None
        error = body.get("error")
        if not isinstance(error, dict):
            return None, None
        metadata = error.get("metadata")
        if not isinstance(metadata, dict):
            return None, None

        error_type = metadata.get("error_type")
        if not isinstance(error_type, str) or not (0 < len(error_type) <= _MAX_PROVIDER_ERROR_FIELD_LENGTH):
            error_type = None

        provider_code = metadata.get("provider_code")
        if not isinstance(provider_code, str) or not (
            0 < len(provider_code) <= _MAX_PROVIDER_ERROR_FIELD_LENGTH
        ):
            provider_code = None

        return error_type, provider_code
    except Exception:  # noqa: BLE001 -- diagnostic parsing must never break verification
        return None, None


def _call_verifier(
    messages: list[dict[str, str]], response_schema: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """One batched httpx call. Raises CitationVerificationError on any
    provider-level failure. Never called for lexical mode or when there are
    no claims/candidates -- callers gate that before reaching here.

    Uses ``settings.citation_verifier_model`` when set (non-None, non-empty)
    so verification can run a different model from answer generation;
    otherwise falls back to ``settings.groq_model`` (today's behavior,
    unchanged when the new setting is left unset). Base URL, API key, and
    timeout are always the shared groq_* settings -- this module does not
    separate provider/base URL/API key, only the model.
    """
    if not settings.groq_api_key:
        raise CitationVerificationError(
            "provider_not_configured",
            provider_diagnostics=_build_provider_diagnostics(kind="not_configured"),
        )

    verifier_model = settings.citation_verifier_model or settings.groq_model

    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }
    headers.update(llm_extra_headers())

    try:
        with httpx.Client(timeout=settings.groq_timeout_seconds) as client:
            response = client.post(
                settings.llm_base_url,
                headers=headers,
                json={
                    "model": verifier_model,
                    "temperature": 0.0,
                    "messages": messages,
                    "response_format": response_schema,
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise CitationVerificationError(
            f"provider_timeout: {exc}",
            provider_diagnostics=_build_provider_diagnostics(kind="timeout"),
        ) from exc
    except httpx.HTTPStatusError as exc:
        error_type, provider_code = _extract_openrouter_error_fields(exc.response)
        raise CitationVerificationError(
            f"provider_error: {exc}",
            provider_diagnostics=_build_provider_diagnostics(
                kind="http_status",
                http_status=exc.response.status_code,
                provider_error_code=provider_code,
                provider_error_type=error_type,
            ),
        ) from exc
    except httpx.HTTPError as exc:
        raise CitationVerificationError(
            f"provider_error: {exc}",
            provider_diagnostics=_build_provider_diagnostics(kind="transport"),
        ) from exc

    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise CitationVerificationError(f"unexpected_response_shape: {exc}") from exc

    # Content-shape guard: the OpenAI-compatible contract this module relies
    # on assumes message.content is a plain string, but nothing upstream
    # enforces that -- a None (e.g. a refusal/empty completion) or a
    # structured content-parts list (documented for some multimodal/tool
    # paths on OpenAI-compatible APIs) would otherwise reach
    # _parse_and_validate and fail with a raw, uncategorized AttributeError
    # on `.strip()`. Reusing "unexpected_response_shape" here (same prefix
    # as the envelope-shape check just above, mapped to the existing
    # response_shape_error telemetry category in citation_verification_jobs
    # .py) keeps this a clean, already-bounded category instead of an
    # unexpected_error/internal_error catch-all -- no new module touched, no
    # stringification or "recovery" of the unexpected shape attempted.
    if content is None or not isinstance(content, str):
        raise CitationVerificationError(
            f"unexpected_response_shape: content is {type(content).__name__}, expected str"
        )

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    return content, usage


def _extract_first_json_object(text: str) -> str | None:
    """Deterministic, JSON-aware scan for the first COMPLETE top-level JSON
    object in ``text`` -- replaces a prior greedy ``\\{.*\\}`` regex that
    matched from the first ``{`` to the LAST ``}`` anywhere in the text.
    That greedy approach silently corrupted otherwise-valid JSON into
    invalid JSON whenever trailing prose contained a stray ``}``, or when
    the response contained more than one JSON object -- both would merge
    unrelated text into the parsed span (see
    citation_v2_malformed_json_investigation.json).

    Tracks brace depth while ignoring braces inside JSON string literals
    (respecting backslash-escaping), so nested objects/arrays and braces
    embedded in string values never confuse the scan. Returns exactly the
    substring from the first ``{`` to its own matching ``}`` -- nothing
    before, nothing after, and never a second object. Returns ``None`` if
    there is no ``{`` at all, or the object never closes (truncated) --
    both cases are left for the caller's ``json.loads`` to reject as
    ``malformed_json``; this function never repairs, invents a missing
    brace, or accepts anything as JSON on its own.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None  # never closed -- truncated; let json.loads reject it


# --- privacy-safe malformed_json diagnostics ----------------------------------
#
# Bounded, structural-only telemetry for a malformed_json failure -- never
# the raw text, never json.JSONDecodeError.doc, never surrounding
# characters, never an exact character position, never a real citation id
# or alias, never question/answer/claim/candidate text. Every value below
# is either a count bucketed into a small fixed set, a boolean, or one of a
# small fixed category-name enum -- see citation_v2_malformed_json_
# investigation.json (the read-only investigation this responds to) for why
# this exists: two real production malformed_json events left no way to
# tell what class of malformed response occurred, even after ruling out the
# parser's own prior fragility.

_CONTENT_LENGTH_BUCKETS: tuple[tuple[int, str], ...] = (
    (0, "empty"),
    (100, "1_100"),
    (500, "101_500"),
    (1000, "501_1000"),
    (2000, "1001_2000"),
    (5000, "2001_5000"),
)


def _bucket_content_length(length: int) -> str:
    if length == 0:
        return "empty"
    for ceiling, bucket in _CONTENT_LENGTH_BUCKETS[1:]:
        if length <= ceiling:
            return bucket
    return "over_5000"


_POSITION_BUCKET_CEILINGS: tuple[tuple[float, str], ...] = (
    (0.05, "start"),
    (0.35, "early"),
    (0.65, "middle"),
    (0.95, "late"),
)


def _bucket_error_position(pos: int, length: int) -> str:
    if length <= 0:
        return "start"
    ratio = max(0.0, min(1.0, pos / length))
    for ceiling, bucket in _POSITION_BUCKET_CEILINGS:
        if ratio <= ceiling:
            return bucket
    return "end"


def _json_error_category(exc: BaseException) -> str:
    """Classifies a JSON parse failure into one of a small, fixed set of
    bounded category names, by READING (never logging or returning)
    ``exc.msg``. json.JSONDecodeError.msg is normally one of a handful of
    fixed English phrases (e.g. "Expecting value"), but for a couple of
    error kinds (invalid escape / invalid control character) CPython
    interpolates the single offending character into that string -- this
    function only ever inspects that text to pick a category; the fixed
    category name it RETURNS never contains any part of ``msg`` or
    ``str(exc)``, so no content can leak through this path regardless of
    what ``msg`` happens to contain for a given error.
    """
    if not isinstance(exc, json.JSONDecodeError):
        return "other_json_decode_error"
    msg = exc.msg
    if msg.startswith("Unterminated string"):
        return "unterminated_string"
    if msg.startswith("Expecting property name"):
        return "expecting_property_name"
    if msg.startswith("Expecting value"):
        return "expecting_value"
    if msg.startswith("Expecting") and "delimiter" in msg:
        return "expecting_delimiter"
    if msg.startswith("Extra data"):
        return "extra_data"
    if "escape" in msg.lower():
        return "invalid_escape"
    return "other_json_decode_error"


def _build_malformed_json_diagnostics(
    text: str, complete_object_found: bool, exc: BaseException
) -> dict[str, Any]:
    """Bounded, JSON-safe structural facts about one malformed_json failure.
    ``text`` is exactly what was handed to the failing ``json.loads`` call
    (the extracted first-object substring when extraction succeeded,
    otherwise the original stripped content) -- never included in the
    returned dict itself, only its length (bucketed) and whether it
    contains a literal '{' at all.
    """
    length = len(text)
    has_open_brace = "{" in text
    pos = getattr(exc, "pos", None)
    position_bucket = _bucket_error_position(pos, length) if isinstance(pos, int) else None
    return {
        "content_length_bucket": _bucket_content_length(length),
        "complete_top_level_object_found": complete_object_found,
        "incomplete_top_level_object": (not complete_object_found) and has_open_brace,
        "json_error_category": _json_error_category(exc),
        "json_error_position_bucket": position_bucket,
        "error_near_end": position_bucket in ("late", "end") if position_bucket else None,
    }


def _parse_and_validate(
    raw_text: str,
    claim_ids: set[str],
    alias_to_real: dict[str, str],
    allowlist: set[str],
) -> dict[str, list[str]]:
    """Strict parse + schema/type/alias validation, then deterministic
    alias -> real citation_id mapping.

    The verifier only ever sees short, call-local citation aliases (S1, S2,
    ... -- see _build_citation_aliases), never the real citation_id values,
    so every supporting_citation_ids entry is validated against the alias
    set first. An alias not in ``alias_to_real`` fails closed exactly like
    an unknown claim_id -- it is never guessed, fuzzy-matched, normalized,
    truncated, or repaired. Once an alias is accepted, it is mapped to its
    real citation_id, and that real id is independently re-checked against
    ``allowlist`` (the original CandidateEvidence.citation_id set) before
    being trusted -- defense in depth, not a shortcut: this module never
    relies on the alias map alone to prove an id was authorized.

    Any violation anywhere in the payload raises, discarding the WHOLE
    result -- per the "malformed output must not partially pass"
    requirement, a defect in one claim's entry invalidates the entire
    verifier response, not just that entry.
    """
    text = (raw_text or "").strip()
    extracted = _extract_first_json_object(text)
    complete_object_found = extracted is not None
    if extracted is not None:
        text = extracted
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        diagnostics = _build_malformed_json_diagnostics(text, complete_object_found, exc)
        raise CitationVerificationError(f"malformed_json: {exc}", diagnostics=diagnostics) from exc

    if not isinstance(parsed, dict):
        raise CitationVerificationError("schema_violation: root is not an object")
    claims_field = parsed.get("claims")
    if not isinstance(claims_field, list):
        raise CitationVerificationError("schema_violation: 'claims' is not a list")

    result: dict[str, list[str]] = {}
    seen_claim_ids: set[str] = set()
    for entry in claims_field:
        if not isinstance(entry, dict):
            raise CitationVerificationError("schema_violation: claim entry is not an object")
        claim_id = entry.get("claim_id")
        if not isinstance(claim_id, str) or claim_id not in claim_ids:
            raise CitationVerificationError(f"unknown_claim_id: {claim_id!r}")
        if claim_id in seen_claim_ids:
            raise CitationVerificationError(f"duplicate_claim_id: {claim_id!r}")
        seen_claim_ids.add(claim_id)

        ids_field = entry.get("supporting_citation_ids")
        if not isinstance(ids_field, list):
            raise CitationVerificationError(
                f"schema_violation: supporting_citation_ids not a list for {claim_id!r}"
            )
        clean_ids: list[str] = []
        seen_aliases_for_claim: set[str] = set()
        for alias in ids_field:
            if not isinstance(alias, str):
                raise CitationVerificationError(
                    f"schema_violation: non-string citation id for {claim_id!r}"
                )
            if alias not in alias_to_real:
                raise CitationVerificationError(f"hallucinated_citation_id: {alias!r}")
            if alias in seen_aliases_for_claim:
                raise CitationVerificationError(
                    f"duplicate_citation_id: {alias!r} for {claim_id!r}"
                )
            seen_aliases_for_claim.add(alias)
            real_id = alias_to_real[alias]
            if real_id not in allowlist:
                raise CitationVerificationError(f"hallucinated_citation_id: {alias!r}")
            clean_ids.append(real_id)
        result[claim_id] = clean_ids

    # A claim_id the verifier omitted entirely is treated as "found no
    # support" (empty list), not an error -- the verifier is allowed to
    # legitimately find zero evidence for a claim.
    for claim_id in claim_ids:
        result.setdefault(claim_id, [])
    return result


def verify_citations(
    *, answer: str, candidates: list[CandidateEvidence], mode: str
) -> VerificationOutcome:
    """Top-level entry point. NEVER raises.

    ``mode == "lexical"``: returns immediately with claims extracted (for
    observability only) and no verifier call -- callers in lexical mode
    should generally not call this at all, but it is safe to call.

    ``mode in ("shadow", "llm")``: extracts claims from ``answer`` (the
    FINAL displayed text, never the pre-rewrite/generation text); if there
    are zero claims or zero candidates, the verifier is not invoked at all
    (nothing to check, or nothing to check it against) and the result is
    fail-closed (``verified_citation_ids == []``) by construction, not by
    error. Otherwise makes exactly one batched verifier call and validates
    its output strictly; any failure anywhere produces a fail-closed result
    with ``verifier_succeeded=False`` and a ``failure_reason``.
    """
    claims = extract_claims(answer)
    outcome = VerificationOutcome(
        mode=mode,
        claims=claims,
        candidate_citation_ids=[c.citation_id for c in candidates],
    )

    if mode not in ("shadow", "llm"):
        return outcome

    if not claims:
        outcome.failure_reason = "zero_claims"
        return outcome
    if not candidates:
        outcome.failure_reason = "zero_candidates"
        return outcome

    outcome.verifier_invoked = True
    try:
        citation_aliases = _build_citation_aliases(candidates)
        alias_to_real = dict(zip(citation_aliases, (c.citation_id for c in candidates)))
        claim_ids_list = [c.claim_id for c in claims]

        messages = _build_verifier_messages(claims, candidates, citation_aliases)
        response_schema = _build_verifier_response_schema(claim_ids_list, citation_aliases)
        started = time.perf_counter()
        raw_text, usage = _call_verifier(messages, response_schema)
        outcome.latency_ms = (time.perf_counter() - started) * 1000.0
        outcome.usage = usage

        allowlist = {c.citation_id for c in candidates}
        claim_ids = set(claim_ids_list)
        per_claim = _parse_and_validate(raw_text, claim_ids, alias_to_real, allowlist)

        outcome.per_claim_verified_ids = per_claim
        seen: set[str] = set()
        ordered_ids: list[str] = []
        supporting_ids = {cid for ids in per_claim.values() for cid in ids}
        for candidate in candidates:  # preserve candidate order, deterministic
            if candidate.citation_id in supporting_ids and candidate.citation_id not in seen:
                ordered_ids.append(candidate.citation_id)
                seen.add(candidate.citation_id)
        outcome.verified_citation_ids = ordered_ids
        outcome.verifier_succeeded = True
    except CitationVerificationError as exc:
        outcome.failure_reason = str(exc)
        outcome.verifier_succeeded = False
        outcome.verified_citation_ids = []
        outcome.per_claim_verified_ids = {}
        outcome.failure_diagnostics = exc.diagnostics
        outcome.provider_diagnostics = exc.provider_diagnostics
    except Exception as exc:  # noqa: BLE001 -- fail-closed against literally anything
        logger.warning(
            "citation_verification: unexpected error, failing closed", exc_info=True
        )
        outcome.failure_reason = f"unexpected_error:{type(exc).__name__}"
        outcome.verifier_succeeded = False
        outcome.verified_citation_ids = []
        outcome.per_claim_verified_ids = {}

    return outcome

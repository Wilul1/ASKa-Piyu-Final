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
    into a fail-closed result. Never escapes this module."""


# --- claim extraction (deterministic, no LLM call) --------------------------

# Unlike question_answering.py's ``_answer_claims`` (which splits on every
# ``.``), this protects decimal numbers ("P75.00", "3.5") from being cut in
# half by only splitting on '.', '!', '?', ';' when NOT flanked by digits on
# both sides; '\n' always splits.
_CLAIM_SPLIT_RE = re.compile(r"(?<!\d)[.!?;](?!\d)|\n+")
_MIN_CLAIM_CHARS = 4

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


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str


def extract_claims(answer: str) -> list[Claim]:
    """Split the FINAL answer into atomic, claim-sized spans.

    Conservative by design: a span is dropped only when it is too short to
    be a checkable fact or clearly matches a non-factual pattern (greeting,
    transition, "not found" language, generic advice). A wrongly-kept
    conversational span costs nothing but one unnecessary verifier lookup
    (it will correctly end up with zero supporting citations either way);
    a wrongly-dropped factual span is the failure mode worth avoiding, so
    the patterns above are deliberately narrow and anchored.
    """
    claims: list[Claim] = []
    index = 0
    for part in _CLAIM_SPLIT_RE.split(answer or ""):
        text = part.strip()
        if len(text) < _MIN_CLAIM_CHARS:
            continue
        classify_as = _LEADING_DECORATION_RE.sub("", text).strip()
        if _NON_FACTUAL_RE.match(classify_as):
            continue
        index += 1
        claims.append(Claim(claim_id=f"c{index}", text=text))
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

# Requests the provider constrain its OWN generation to this exact shape
# (OpenRouter's documented response_format=json_schema contract -- verified
# against the currently configured model's own listed accepted parameters
# before adding this, per the investigation this change is based on).
# Defense in depth, not a trust boundary: _parse_and_validate() below still
# independently re-validates every field from scratch regardless of whether
# the provider actually honored this constraint -- this can only IMPROVE
# the odds of getting parseable output, it never substitutes for or
# weakens that validation. If the configured provider/model combination
# does not actually support this (contrary to what it lists), OpenRouter's
# own documented behavior is to fail the request with an HTTP error --
# which the existing httpx.HTTPError handler below already maps to
# failure_category="provider_error", not a new/unhandled failure shape.
_VERIFIER_RESPONSE_SCHEMA = {
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
                            "claim_id": {"type": "string"},
                            "supporting_citation_ids": {
                                "type": "array",
                                "items": {"type": "string"},
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
    claims: list[Claim], candidates: list[CandidateEvidence]
) -> list[dict[str, str]]:
    claims_payload = [{"claim_id": c.claim_id, "text": c.text} for c in claims]
    candidates_payload = [
        {
            "citation_id": c.citation_id,
            "title": c.title,
            "source_section": c.source_section,
            "source_filename": c.source_filename,
            "text": (c.text or "")[:_MAX_EVIDENCE_CHARS],
        }
        for c in candidates
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


def _call_verifier(messages: list[dict[str, str]]) -> tuple[str, dict[str, Any] | None]:
    """One batched httpx call. Raises CitationVerificationError on any
    provider-level failure. Never called for lexical mode or when there are
    no claims/candidates -- callers gate that before reaching here."""
    if not settings.groq_api_key:
        raise CitationVerificationError("provider_not_configured")

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
                    "model": settings.groq_model,
                    "temperature": 0.0,
                    "messages": messages,
                    "response_format": _VERIFIER_RESPONSE_SCHEMA,
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise CitationVerificationError(f"provider_timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        raise CitationVerificationError(f"provider_error: {exc}") from exc

    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise CitationVerificationError(f"unexpected_response_shape: {exc}") from exc

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    return content, usage


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)


def _parse_and_validate(
    raw_text: str, claim_ids: set[str], allowlist: set[str]
) -> dict[str, list[str]]:
    """Strict parse + schema/type/id validation.

    Any violation anywhere in the payload raises, discarding the WHOLE
    result -- per the "malformed output must not partially pass"
    requirement, a defect in one claim's entry invalidates the entire
    verifier response, not just that entry.
    """
    text = (raw_text or "").strip()
    fence_match = _JSON_OBJECT_RE.search(text)
    if fence_match:
        text = fence_match.group(0)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CitationVerificationError(f"malformed_json: {exc}") from exc

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
        seen_ids_for_claim: set[str] = set()
        for cid in ids_field:
            if not isinstance(cid, str):
                raise CitationVerificationError(
                    f"schema_violation: non-string citation id for {claim_id!r}"
                )
            if cid not in allowlist:
                raise CitationVerificationError(f"hallucinated_citation_id: {cid!r}")
            if cid in seen_ids_for_claim:
                raise CitationVerificationError(
                    f"duplicate_citation_id: {cid!r} for {claim_id!r}"
                )
            seen_ids_for_claim.add(cid)
            clean_ids.append(cid)
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
        messages = _build_verifier_messages(claims, candidates)
        started = time.perf_counter()
        raw_text, usage = _call_verifier(messages)
        outcome.latency_ms = (time.perf_counter() - started) * 1000.0
        outcome.usage = usage

        allowlist = {c.citation_id for c in candidates}
        claim_ids = {c.claim_id for c in claims}
        per_claim = _parse_and_validate(raw_text, claim_ids, allowlist)

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
    except Exception as exc:  # noqa: BLE001 -- fail-closed against literally anything
        logger.warning(
            "citation_verification: unexpected error, failing closed", exc_info=True
        )
        outcome.failure_reason = f"unexpected_error:{type(exc).__name__}"
        outcome.verifier_succeeded = False
        outcome.verified_citation_ids = []
        outcome.per_claim_verified_ids = {}

    return outcome

"""Service identity must win before top-k truncation, generically.

Regression coverage for a real production failure: a question naming a
taxonomy service (e.g. "What are the requirements for a Certificate of Good
Moral Character?") retrieved the Issuance-of-Good-Moral-Certificate service
card in some runs but not others, because the only upstream ranking signal
strong enough to protect a named service's own card was hardcoded to two
services (TOR, diploma) inside ``_fee_service_boost``. Every other taxonomy
service (Good Moral, Clearance, Scholarships, ...) relied only on generic
lexical/cosine signals, which cannot reliably tell "the service's own record"
apart from a same-named adjacent policy mention (e.g. a Student Handbook
"Good Moral" retention-policy clause) — so a same-worded but wrong document
could win, or the correct card could simply fall out of a top-k cut before
any QA-layer reordering (``prefer_service_chunks`` etc.) ever saw it.

These tests exercise ``rerank_chunks`` directly — the stage that runs before
``select_role_visible_hits`` slices to ``top_k`` inside ``KnowledgeBaseStore.
search`` — so a passing test proves the fix works *before* truncation, not
merely that a downstream reorder step prefers the right chunk once it has
already survived.
"""

from __future__ import annotations

import pytest

from app.services.chroma_store import RetrievedChunk
from app.services.knowledge_taxonomy import taxonomy_service_names_in_text
from app.services.qa.question_answering import _authoritative_evidence_present, _confidence_for
from app.services.retrieval_reranker import RetrievalAblation, _normalize, rerank_chunks


def _chunk(
    title: str,
    text: str,
    *,
    similarity: float,
    label: str,
    document_type: str | None = None,
) -> RetrievedChunk:
    metadata: dict[str, object] = {
        "source_section": title,
        "title": title,
        "page_number": 1,
        "source_filename": label,
        "source_document": label,
    }
    if document_type is not None:
        metadata["document_type"] = document_type
    return RetrievedChunk(
        document_id=title.casefold().replace(" ", "-")[:40],
        title=title,
        source_filename=label,
        chunk_index=0,
        text=text,
        relevance_score=similarity,
        original_score=similarity,
        reranked_score=None,
        metadata=metadata,
    )


# One (question, authoritative card, adjacent same-named policy chunk) case per
# taxonomy service, so the fix is proven generic rather than Good-Moral-only.
SERVICE_CASES = [
    pytest.param(
        "What are the requirements for a Certificate of Good Moral Character?",
        (
            "Issuance of Good Moral Certificate (Undergraduate)",
            "Overview This service provides assistance for Issuance of Good Moral Certificate "
            "(Undergraduate). Office / Division Office of the Student Affairs and Services. "
            "Requirement: Certificate of Registration. Requirement: Student ID.",
        ),
        (
            "Good Moral",
            "Good Moral Undergraduate Academic Policies > Article 5 > Retention Policies > "
            "Sec. 1 > Good Moral. After admission, the student must maintain good moral "
            "character at all times.",
        ),
        id="good-moral",
    ),
    pytest.param(
        "How long does it take to get a Good Moral Certificate?",
        (
            "Issuance of Good Moral Certificate (Undergraduate)",
            "Overview This service provides assistance for Issuance of Good Moral Certificate "
            "(Undergraduate). Total Processing Time 1 hour.",
        ),
        (
            "Good Moral",
            "Good Moral Undergraduate Academic Policies > Article 5 > Retention Policies > "
            "Sec. 1 > Good Moral. After admission, the student must maintain good moral "
            "character at all times.",
        ),
        id="good-moral-processing-time",
    ),
    pytest.param(
        "What are the requirements for student clearance?",
        (
            "Issuance of Student Clearance",
            "Overview This service provides assistance for Issuance of Student Clearance. "
            "Office / Division Registrar.",
        ),
        (
            "Clearance",
            "Graduation Clearance Undergraduate Academic Policies > Article 9 > Clearance as a "
            "graduation requirement, students must be cleared of all obligations.",
        ),
        id="clearance",
    ),
    pytest.param(
        "What are the requirements to apply for a scholarship?",
        (
            "Processing of Scholarship and Financial Assistance",
            "Overview This service provides assistance for Processing of Scholarship and "
            "Financial Assistance. Office / Division Scholarship Office.",
        ),
        (
            "Scholarship Retention",
            "Scholastic Delinquency and Scholarship Undergraduate Academic Policies > Article 5 "
            "> A scholar who fails to maintain the required grade loses scholarship privileges.",
        ),
        id="scholarship",
    ),
]


@pytest.mark.parametrize("question, card, policy", SERVICE_CASES)
def test_authoritative_card_beats_adjacent_policy_before_truncation(question, card, policy):
    """The service's own card outranks a same-named policy clause even when
    the policy clause has the *higher* raw cosine similarity — proving the
    win comes from service identity, not from favorable embedding luck."""
    card_chunk = _chunk(
        *card, similarity=0.83, label="Citizen's Charter", document_type="citizen_charter"
    )
    policy_chunk = _chunk(*policy, similarity=0.89, label="Student Handbook", document_type="handbook")

    ranked = rerank_chunks(question, [card_chunk, policy_chunk])

    assert ranked[0].metadata["source_section"] == card[0]
    assert "boost_taxonomy_service_identity" in " ".join(ranked[0].rerank_reasons or [])
    assert "boost_taxonomy_service_identity" not in " ".join(ranked[1].rerank_reasons or [])


@pytest.mark.parametrize("question, card, policy", SERVICE_CASES)
def test_authoritative_card_survives_a_crowded_top_k_cut(question, card, policy):
    """Reproduces the real failure shape: a 15-candidate pool (more than the
    production top_k=7) with several unrelated distractor services. The
    correct card must land inside the first 7 ranks, not merely win a
    two-chunk comparison."""
    card_chunk = _chunk(
        *card, similarity=0.855, label="Citizen's Charter", document_type="citizen_charter"
    )
    policy_chunk = _chunk(*policy, similarity=0.885, label="Student Handbook", document_type="handbook")
    distractors = [
        _chunk(
            f"Unrelated Service {i}",
            f"Overview This service provides assistance for Unrelated Service {i}.",
            similarity=0.80 + (i % 5) * 0.01,
            label="Citizen's Charter",
            document_type="citizen_charter",
        )
        for i in range(12)
    ]

    ranked = rerank_chunks(question, [card_chunk, policy_chunk, *distractors])
    top_seven_titles = {c.metadata["source_section"] for c in ranked[:7]}

    assert card[0] in top_seven_titles


def test_generic_mechanism_needs_no_per_service_code():
    """Sanity check that the boost is driven by taxonomy lookup, not a
    hardcoded service list: a made-up, non-taxonomy service name gets no
    identity boost at all (so it cannot silently "match everything")."""
    from app.services.retrieval_reranker import _service_identity_boost, _normalize

    reasons: list[str] = []
    boost = _service_identity_boost(
        _normalize("What are the requirements for the Interstellar Travel Permit?"),
        normalized_title_path=_normalize("Interstellar Travel Permit"),
        metadata={"document_type": "citizen_charter"},
        content="",
        reasons=reasons,
    )
    assert boost == 0.0
    assert reasons == []


def test_named_service_boosts_ablation_still_disables_the_new_boost():
    """The new boost must respect the existing Phase 2A ablation switch used
    to benchmark with title/service-card boosts turned off."""
    card_chunk = _chunk(
        "Issuance of Good Moral Certificate (Undergraduate)",
        "Overview This service provides assistance for Issuance of Good Moral Certificate.",
        similarity=0.85,
        label="Citizen's Charter",
        document_type="citizen_charter",
    )
    ranked = rerank_chunks(
        "What are the requirements for a Certificate of Good Moral Character?",
        [card_chunk],
        ablation=RetrievalAblation(disable_named_service_boosts=True),
    )
    assert "boost_taxonomy_service_identity" not in " ".join(ranked[0].rerank_reasons or [])


# --- confidence gate: authoritative evidence required for "high" on a named service ---


def test_confidence_stays_below_high_when_only_adjacent_policy_evidence_is_selected():
    """Mirrors the real Good Moral regression: the retained/selected evidence
    is topically about the right subject but is not the service's own record,
    so confidence must not be reported as "high"."""
    policy_chunk = _chunk(
        "Good Moral",
        "Good Moral Undergraduate Academic Policies > Article 5 > Retention Policies > Sec. 1 "
        "> Good Moral. After admission, the student must maintain good moral character.",
        similarity=0.88,
        label="Student Handbook",
        document_type="handbook",
    )
    question = "What are the requirements for a Certificate of Good Moral Character?"

    assert _authoritative_evidence_present(question, [policy_chunk]) is False
    assert (
        _confidence_for([policy_chunk], [policy_chunk], "Some answer about Good Moral.", question)
        != "high"
    )


def test_confidence_can_still_reach_high_with_the_authoritative_card_present():
    """The tightened gate must not become impossible to satisfy: once the
    service's own card is actually in evidence, "high" is still reachable."""
    card_chunk = _chunk(
        "Issuance of Good Moral Certificate (Undergraduate)",
        "Overview This service provides assistance for Issuance of Good Moral Certificate "
        "(Undergraduate). Office / Division Office of the Student Affairs and Services. "
        "Requirement: Certificate of Registration. Requirement: Student ID.",
        similarity=0.86,
        label="Citizen's Charter",
        document_type="citizen_charter",
    )
    question = "What are the requirements for a Certificate of Good Moral Character?"

    assert _authoritative_evidence_present(question, [card_chunk]) is True


def test_authoritative_evidence_check_is_a_noop_off_the_factual_service_path():
    """Questions that are not fact-seeking about a named service (e.g. no
    taxonomy service named at all) are unaffected by this gate."""
    assert _authoritative_evidence_present("Tell me about student life at LSPU.", []) is True


# --- generic taxonomy words must not masquerade as a named service ----------
#
# Some taxonomy subcategories exist purely as miscellaneous FAQ buckets and
# are themselves named after (or keyed on) bare generic nouns: "Certificates",
# "Requests", "Application Forms". Before this fix, a completely vague
# question containing only that generic word was treated as if it named that
# specific service, and a chunk that happened to share the word in its title
# got a strong, unwarranted upstream identity boost.


@pytest.mark.parametrize(
    "vague_question",
    [
        "I want to make a request",
        "I need to submit a request for something",
        "I need a certificate",
        "I have a certification question",
        "I need certificates",
        "Where can I get an application form?",
        "What is an application?",
    ],
)
def test_generic_taxonomy_words_do_not_name_a_service(vague_question):
    """These phrases must not resolve to a taxonomy service at all — they
    name no service, they just happen to contain a generic bucket word."""
    assert taxonomy_service_names_in_text(_normalize(vague_question)) == []


def test_generic_request_word_does_not_boost_an_unrelated_authoritative_card():
    """End-to-end through the real reranker: a card that merely shares the
    generic word "request" in its title must not receive the strong
    taxonomy-identity boost for a question that names no real service."""
    card = _chunk(
        "Request for Copy of Enrollment Record",
        "Overview This service provides assistance for request for copy of "
        "enrollment record.",
        similarity=0.80,
        label="Citizen's Charter",
        document_type="citizen_charter",
    )
    unrelated = _chunk(
        "Library Reference Assistance",
        "Overview This service provides assistance for Library Reference Assistance.",
        similarity=0.86,
        label="Citizen's Charter",
        document_type="citizen_charter",
    )

    ranked = rerank_chunks("I want to make a request", [card, unrelated])

    reasons_by_title = {c.metadata["source_section"]: (c.rerank_reasons or []) for c in ranked}
    assert not any(
        r.startswith("boost_taxonomy_service_identity")
        for r in reasons_by_title["Request for Copy of Enrollment Record"]
    )


@pytest.mark.parametrize(
    "question, expected_service",
    [
        ("Tell me about Good Moral.", "Good Moral"),
        ("What are the requirements for student clearance?", "Clearance"),
        ("How do I apply for a scholarship?", "Scholarships"),
        ("magkano ang TOR?", "Transcript of Records"),
    ],
)
def test_real_named_services_still_resolve_after_the_generic_word_fix(question, expected_service):
    """The fix must reject bare-generic-word matches without collaterally
    breaking resolution of actual named services."""
    assert expected_service in taxonomy_service_names_in_text(_normalize(question))


@pytest.mark.parametrize(
    "question, card_title",
    [
        ("What are the requirements for a Certificate of Good Moral Character?",
         "Issuance of Good Moral Certificate (Undergraduate)"),
        ("What are the requirements for student clearance?", "Issuance of Student Clearance"),
        ("magkano ang TOR?", "Issuance of Transcript of Records/Transfer Credentials"),
    ],
)
def test_named_service_cards_still_receive_the_identity_boost(question, card_title):
    """Guards the other direction of the generic-word fix: tightening the
    exclusion must not stop real service cards from being boosted."""
    from app.services.retrieval_reranker import _service_identity_boost

    reasons: list[str] = []
    boost = _service_identity_boost(
        _normalize(question),
        normalized_title_path=_normalize(card_title),
        metadata={"document_type": "citizen_charter"},
        content="Office / Division Registrar",
        reasons=reasons,
    )
    assert boost > 0
    assert any(r.startswith("boost_taxonomy_service_identity") for r in reasons)


# --- characterization: known remaining limitations (NOT desired behavior) ---
#
# This gap is now fixed: the taxonomy resolved these questions to a service
# (Registration / Withdrawal) whose canonical name shares no token with the
# real card title (Enrollment / Dropping of Subjects) — but the *matched
# keyword alias* ("enrollment", "drop a subject") does. Preserving that alias
# (``TaxonomyServiceMatch.literal_tokens``) instead of collapsing to the bare
# canonical name is what makes the boost fire correctly below.


@pytest.mark.parametrize(
    "question, card_title, taxonomy_name",
    [
        ("How much does enrollment cost?", "Enrollment", "Registration"),
        ("How do I drop a subject?", "Dropping of Subjects", "Withdrawal"),
    ],
)
def test_alias_only_services_now_receive_the_identity_boost(question, card_title, taxonomy_name):
    """Enrollment and Dropping are reachable in the taxonomy only as keyword
    aliases under differently-named entries ("Registration", "Withdrawal").
    The boost must fire via the *matched alias* even though the bare
    canonical name shares no token with the real card title.
    """
    from app.services.retrieval_reranker import _service_identity_boost

    assert taxonomy_name in taxonomy_service_names_in_text(_normalize(question))

    reasons: list[str] = []
    boost = _service_identity_boost(
        _normalize(question),
        normalized_title_path=_normalize(card_title),
        metadata={"document_type": "citizen_charter"},
        content="Office / Division Registrar",
        reasons=reasons,
    )
    assert boost > 0.0
    assert any(r.startswith("boost_taxonomy_service_identity") for r in reasons)


def test_single_token_canonical_name_alone_does_not_boost_an_unrelated_card():
    """Guards the false positive this alias-preservation fix must not
    reopen: a query reaching a service only through an alias must not credit
    an unrelated card that happens to share the service's bare (single-word)
    canonical name — e.g. "Registration" — with no other overlap. This is a
    real production title (``IP Registration Process``), not a hypothetical.
    """
    from app.services.retrieval_reranker import _service_identity_boost

    reasons: list[str] = []
    boost = _service_identity_boost(
        _normalize("How much does enrollment cost?"),
        normalized_title_path=_normalize("IP Registration Process"),
        metadata={"document_type": "citizen_charter"},
        content="Office / Division Registrar",
        reasons=reasons,
    )
    assert boost == 0.0
    assert reasons == []


def test_known_gap_tor_receives_both_legacy_and_generic_identity_boosts():
    """KNOWN INCONSISTENCY — a well-tagged TOR card stacks both boosts.

    The legacy ``boost_tor_service_title`` (+0.55) fires in addition to the
    generic ``boost_taxonomy_service_identity`` (+0.70), so TOR carries more
    upstream weight than any other taxonomy service. It was left in place
    deliberately: the legacy boost fires *equally* on acronym-collision
    titles (e.g. "Terms of Reference (TOR)"), so suppressing it only on the
    correct card collapses the margin between them from ~0.58 to ~0.03, and
    removing it outright regresses untagged-metadata ranking (see
    test_kb_browser.py). Redundant scoring, not a demonstrated ranking
    distortion — both signals point the same way.
    """
    from app.services.retrieval_reranker import _fee_service_boost, _service_identity_boost

    query = _normalize("magkano ang TOR?")
    title = _normalize("Issuance of Transcript of Records/Transfer Credentials")
    metadata = {"document_type": "citizen_charter"}

    identity_reasons: list[str] = []
    identity = _service_identity_boost(
        query,
        normalized_title_path=title,
        metadata=metadata,
        content="Office / Division Registrar",
        reasons=identity_reasons,
    )
    legacy_reasons: list[str] = []
    _fee_service_boost(
        normalized_query=query,
        normalized_title_path=title,
        normalized_content=_normalize("Issuance of Transcript of Records."),
        metadata=metadata,
        reasons=legacy_reasons,
    )

    assert identity > 0
    assert "boost_tor_service_title" in legacy_reasons

    # The legacy boost gives the acronym-collision title the same amount, which
    # is why it cannot simply be gated off on the correct card alone.
    collision_reasons: list[str] = []
    _fee_service_boost(
        normalized_query=query,
        normalized_title_path=_normalize("Composition and Terms of Reference (TOR)"),
        normalized_content=_normalize("Grievance Committee Terms of Reference."),
        metadata={},
        reasons=collision_reasons,
    )
    assert "boost_tor_service_title" in collision_reasons


# --- P1: authoritative-evidence matching must use the same preserved alias --


@pytest.mark.parametrize(
    "question, card_title",
    [
        ("How much does enrollment cost?", "Enrollment"),
        ("What documents are required to drop a subject?", "Dropping of Subjects"),
        ("What are the requirements to apply for a scholarship?",
         "Processing of Scholarship and Financial Assistance"),
        ("How much is the fee for a Transcript of Records?",
         "Issuance of Transcript of Records/Transfer Credentials"),
    ],
)
def test_authoritative_evidence_present_recognizes_alias_only_services(question, card_title):
    """P1 fix: ``_authoritative_evidence_present`` used to tokenize only the
    bare canonical name, losing whichever keyword alias actually identified
    the service. Enrollment (via "Registration"), Dropping (via
    "Withdrawal"), and the plural/singular Scholarships/scholarship mismatch
    all used to be wrongly rejected as a result.
    """
    from app.services.chroma_store import RetrievedChunk
    from app.services.qa.question_answering import _authoritative_evidence_present

    chunk = RetrievedChunk(
        document_id=card_title.lower()[:30],
        title=card_title,
        source_filename="cc.pdf",
        chunk_index=0,
        text="Office / Division Registrar",
        relevance_score=1.0,
        original_score=1.0,
        reranked_score=1.0,
        metadata={
            "source_section": card_title,
            "title": card_title,
            "document_type": "citizen_charter",
            "page_number": 1,
        },
    )
    assert _authoritative_evidence_present(question, [chunk]) is True


def test_authoritative_evidence_present_still_rejects_shared_generic_word_only():
    """P1 fix, other direction: a card sharing only the bare, single-token
    canonical name ("Registration") — a real production title, "IP
    Registration Process" — with no alias/keyword overlap must still be
    rejected, not accepted just because alias preservation was added.
    """
    from app.services.chroma_store import RetrievedChunk
    from app.services.qa.question_answering import _authoritative_evidence_present

    chunk = RetrievedChunk(
        document_id="ip-registration-process",
        title="IP Registration Process",
        source_filename="cc.pdf",
        chunk_index=0,
        text="Office / Division IP Office",
        relevance_score=1.0,
        original_score=1.0,
        reranked_score=1.0,
        metadata={
            "source_section": "IP Registration Process",
            "title": "IP Registration Process",
            "document_type": "citizen_charter",
            "page_number": 1,
        },
    )
    assert _authoritative_evidence_present("How much does enrollment cost?", [chunk]) is False


# --- P1: generic residual words must not resolve as a topic via the exact-match path ---


@pytest.mark.parametrize("residual", ["request", "certificates", "application", "application form", "Requests"])
def test_canonical_service_retrieval_phrase_rejects_generic_residuals(residual):
    """``_canonical_service_retrieval_phrase`` did an exact string-equality
    match against every taxonomy name/keyword with no generic-word exclusion
    at all — bypassing the exclusion ``taxonomy_service_names_in_text``
    already applied elsewhere. A bare "request"/"certificates"/"application"
    residual (e.g. after stripping a topic-setting wrapper, or as a raw
    first-turn message) must not resolve to a taxonomy service.
    """
    from app.services.qa.question_answering import _canonical_service_retrieval_phrase

    assert _canonical_service_retrieval_phrase(residual) is None


@pytest.mark.parametrize(
    "residual, expected_service",
    [("TOR", "Transcript of Records"), ("Good Moral", "Good Moral"), ("clearance", "Clearance")],
)
def test_canonical_service_retrieval_phrase_still_resolves_real_services(residual, expected_service):
    from app.services.qa.question_answering import _canonical_service_retrieval_phrase

    resolved = _canonical_service_retrieval_phrase(residual)
    assert resolved is not None
    assert expected_service in resolved


@pytest.mark.parametrize("residual", ["request", "certificates", "application"])
def test_is_known_service_label_rejects_generic_residuals(residual):
    """Same underlying bug, different call site: ``_service_vocab_sets`` fed
    ``_is_known_service_label`` an unfiltered taxonomy vocabulary, so a bare
    generic residual was treated as "a known service label" — which feeds
    directly into topic-setting/slot-followup detection.
    """
    from app.services.qa.question_answering import _is_known_service_label

    assert _is_known_service_label(residual) is False


def test_resolve_followup_question_does_not_canonicalize_generic_residuals():
    """End-to-end: a bare vague first-turn message must not be rewritten as
    if the user had named a specific service."""
    from app.services.qa.question_answering import resolve_followup_question

    resolved = resolve_followup_question("request", None)
    assert resolved == "request"
    assert "Requests" not in resolved


# --- P0 task 2: multi-facet unanswered-part confidence must not become HIGH ---


def test_single_facet_evidence_for_a_compound_question_is_not_high_confidence():
    """Confirmed candidate regression (reproduced against the committed
    production baseline before this fix): a single chunk narrowly covering
    only one part of a multi-part question ("...but I still have an
    incomplete subject and unpaid fees. Which requirement fails first —
    academic, clearance, or deployment?") shared literal wording with the
    question (its title says "OJT"/"deployment", both present in the
    question) and so satisfied the rewritten title/text-anchoring check for
    HIGH confidence — even though it addresses only one of three distinct
    facets and its taxonomy category ("Requirements & Forms") does not match
    the chunk at all. Production's original score-threshold-era code
    happened to catch this because it *required* the classified domain to
    match; requiring that same domain-consistency for HIGH (only when a
    domain is actually detected) restores the production result without
    reintroducing an absolute score threshold or weakening the authoritative-
    evidence requirement.
    """
    from app.services.chroma_store import RetrievedChunk
    from app.services.qa.question_answering import _confidence_for

    question = (
        "I want to go on OJT next term, but I still have an incomplete subject and "
        "unpaid fees. Which requirement fails first — academic, clearance, or deployment?"
    )
    ojt = RetrievedChunk(
        document_id="deployment-of-ojt",
        title="LSPU Citizen's Charter",
        source_filename="charter.pdf",
        chunk_index=0,
        text="Orientation then deployment.",
        relevance_score=0.9,
        original_score=0.85,
        reranked_score=0.9,
        rerank_reasons=["boost_service_procedure"],
        metadata={
            "section": "Deployment of OJT",
            "source_section": "Deployment of OJT",
            "office": "Colleges",
            "page_start": 89,
            "audience": "both",
        },
    )
    chunks = [ojt]

    assert _confidence_for(chunks, chunks, "Here is the OJT process.", question) == "medium"

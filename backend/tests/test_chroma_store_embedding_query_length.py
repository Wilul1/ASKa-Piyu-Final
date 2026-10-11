"""Regression tests for the EC2 embedding service's HTTP 422 failure on
bundled, multi-topic questions.

A multi-topic question can get expanded twice: once when the top-level
question is prepared, again inside Store.search() when that already-
expanded text is re-run through prepare_retrieval_query() as one of
several retrieval variants (see question_answering._multi_query_retrieve).
This compounds expansion terms past the embedding service's 2000-character
input limit, which the service rejects with HTTP 422, surfacing to the
client as a 500 via RemoteEmbeddingError.

No real network calls: the embedding HTTP call is mocked to mirror the
EC2 service's own known validation rules (empty/whitespace/over-2000-char
text -> 422; otherwise 200).
"""

from unittest.mock import MagicMock, patch

from app.services.chroma_store import EMBEDDING_QUERY_MAX_CHARS, _clamp_embedding_query_text
from app.services.embeddings import LocalEC2EmbeddingFunction, RemoteEmbeddingError
from app.services.qa.multi_facet import facet_retrieval_queries, split_question_facets
from app.services.qa.question_answering import _retrieval_query_variants
from app.services.retrieval_reranker import prepare_retrieval_query


def _fake_embedding_post(url, headers=None, json=None, timeout=None):
    """Mirrors the real EC2 service's /embed/query validation rules."""
    resp = MagicMock()
    texts = json["texts"]
    if any((not t) or (not t.strip()) or len(t) > EMBEDDING_QUERY_MAX_CHARS for t in texts):
        resp.status_code = 422
    else:
        resp.status_code = 200
    resp.json.return_value = {"vectors": [[0.0] * 384 for _ in texts], "dimension": 384}
    return resp


def _call_embed_query(text: str) -> tuple[bool, str]:
    ef = LocalEC2EmbeddingFunction(
        base_url="https://example-embedding.test",
        token="dummy-test-token-not-real",
        timeout_seconds=15.0,
    )
    with patch("httpx.post", side_effect=_fake_embedding_post):
        try:
            ef.embed_query([text])
            return True, "200"
        except RemoteEmbeddingError as exc:
            return False, str(exc)


def _retrieval_variants_for(question: str) -> list[str]:
    """Mirrors the variant-building logic in answer_qa_question."""
    top_prepared = prepare_retrieval_query(question)
    variants = _retrieval_query_variants(question, top_prepared)
    facets = split_question_facets(question)
    variants.extend(facet_retrieval_queries(facets, existing=variants))
    return variants


def _embedding_text_for_variant(variant: str) -> str:
    """Mirrors exactly what Store.search() sends, post-fix."""
    prepared = prepare_retrieval_query(variant.strip())
    return _clamp_embedding_query_text(prepared.expanded_query)


# --- Direct unit tests of the clamp helper ---


def test_clamp_is_noop_for_text_under_limit():
    text = "TOR cost per page requirements registrar"
    assert _clamp_embedding_query_text(text) == text


def test_clamp_is_noop_for_text_exactly_at_limit():
    text = "a" * EMBEDDING_QUERY_MAX_CHARS
    assert _clamp_embedding_query_text(text) == text


def test_clamp_truncates_over_limit_text_on_word_boundary():
    long_text = "original question text " + ("expansion term " * 200)
    assert len(long_text) > EMBEDDING_QUERY_MAX_CHARS

    clamped = _clamp_embedding_query_text(long_text)

    assert len(clamped) <= EMBEDDING_QUERY_MAX_CHARS
    assert clamped  # never empty
    assert clamped.strip() == clamped  # never whitespace-padded
    # Preserves the original question (it's the prefix of the expanded text).
    assert long_text.startswith(clamped.rstrip())
    # Word-boundary cut: the original text continues with a space right
    # after the clamped prefix, never mid-token.
    assert long_text[len(clamped) : len(clamped) + 1] in (" ", "")


def test_clamp_never_returns_empty_for_non_empty_overlength_single_token():
    # Pathological case: no spaces at all within the first max_chars.
    long_token = "x" * (EMBEDDING_QUERY_MAX_CHARS + 500)
    clamped = _clamp_embedding_query_text(long_token)
    assert clamped  # must still be non-empty
    assert len(clamped) <= EMBEDDING_QUERY_MAX_CHARS


# --- Reproduction of the production failure, through the real pipeline ---


def test_two_topic_question_reproduces_overlength_variant_before_relying_on_clamp():
    """Confirms the underlying double-expansion mechanism still produces an
    over-limit string pre-clamp, so this test would fail loudly if the
    expansion logic changes enough to stop reproducing the original bug
    (rather than silently passing for an unrelated reason)."""
    question = (
        "What is the TOR cost per page for undergraduate versus graduate students, "
        "and what is the Landbank LinkBiz transaction fee?"
    )
    variants = _retrieval_variants_for(question)

    pre_clamp_lengths = [
        len(prepare_retrieval_query(v.strip()).expanded_query) for v in variants
    ]
    assert any(length > EMBEDDING_QUERY_MAX_CHARS for length in pre_clamp_lengths), (
        "expected at least one retrieval variant to exceed the embedding "
        "service's character limit before clamping, reproducing the "
        "original production failure mechanism"
    )


def test_two_topic_question_embedding_text_stays_within_limit_after_fix():
    question = (
        "What is the TOR cost per page for undergraduate versus graduate students, "
        "and what is the Landbank LinkBiz transaction fee?"
    )
    variants = _retrieval_variants_for(question)
    assert len(variants) >= 2  # multi-topic question should produce multiple variants

    for variant in variants:
        embedding_text = _embedding_text_for_variant(variant)
        assert len(embedding_text) <= EMBEDDING_QUERY_MAX_CHARS
        assert embedding_text.strip() != ""


def test_two_topic_question_embedding_call_succeeds_after_fix():
    question = (
        "What is the TOR cost per page for undergraduate versus graduate students, "
        "and what is the Landbank LinkBiz transaction fee?"
    )
    variants = _retrieval_variants_for(question)

    for variant in variants:
        embedding_text = _embedding_text_for_variant(variant)
        ok, detail = _call_embed_query(embedding_text)
        assert ok, f"expected 200 after clamping, got: {detail}"


# --- Normal (single-topic, already-under-limit) query: behavior unchanged ---


def test_single_topic_question_unaffected_by_clamp():
    question = "What is the TOR cost per page for undergraduate students?"
    variants = _retrieval_variants_for(question)

    for variant in variants:
        prepared = prepare_retrieval_query(variant.strip())
        pre_clamp = prepared.expanded_query
        post_clamp = _clamp_embedding_query_text(pre_clamp)

        assert len(pre_clamp) <= EMBEDDING_QUERY_MAX_CHARS, (
            "sanity check: this single-topic question's variants were not "
            "expected to exceed the limit even before clamping"
        )
        # No-op: clamping an already-valid string must not alter it.
        assert post_clamp == pre_clamp

        ok, detail = _call_embed_query(post_clamp)
        assert ok, f"expected 200 for an already-valid single-topic query, got: {detail}"

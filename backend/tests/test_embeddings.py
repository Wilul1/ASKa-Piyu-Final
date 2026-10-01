"""Unit tests for the embedding backends (local + Hugging Face remote).

No real model download and no live network calls — the local backend mocks
``sentence_transformers.SentenceTransformer``; the remote backend mocks
``httpx.post``.
"""

import logging
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

from app.services.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EXPECTED_EMBEDDING_DIMENSION,
    E5EmbeddingFunction,
    HFRemoteEmbeddingFunction,
    RemoteEmbeddingError,
    current_embedding_model_label,
    get_embedding_function,
)


def _fake_sentence_transformer_module():
    """Patch target for `from sentence_transformers import SentenceTransformer`."""
    fake_model = MagicMock()
    fake_model.encode.side_effect = lambda texts, **_: np.zeros((len(texts), 4))
    fake_constructor = MagicMock(return_value=fake_model)
    return fake_constructor, fake_model


def test_call_prefixes_documents_with_passage():
    fake_constructor, fake_model = _fake_sentence_transformer_module()
    ef = E5EmbeddingFunction(model_name="fake-model")

    with patch("sentence_transformers.SentenceTransformer", fake_constructor):
        result = ef(["Enrollment requires a signed form."])

    fake_constructor.assert_called_once_with("fake-model", device="cpu")
    call_args = fake_model.encode.call_args
    assert call_args.args[0] == ["passage: Enrollment requires a signed form."]
    assert call_args.kwargs.get("normalize_embeddings") is True
    assert len(result) == 1
    assert len(result[0]) == 4


def test_embed_query_prefixes_with_query_not_passage():
    fake_constructor, fake_model = _fake_sentence_transformer_module()
    ef = E5EmbeddingFunction(model_name="fake-model")

    with patch("sentence_transformers.SentenceTransformer", fake_constructor):
        ef.embed_query(["How do I enroll?"])

    call_args = fake_model.encode.call_args
    assert call_args.args[0] == ["query: How do I enroll?"]


def test_model_is_lazy_loaded_once():
    fake_constructor, _fake_model = _fake_sentence_transformer_module()
    ef = E5EmbeddingFunction(model_name="fake-model")

    with patch("sentence_transformers.SentenceTransformer", fake_constructor):
        ef(["first call"])
        ef.embed_query(["second call"])

    fake_constructor.assert_called_once()


def test_defaults_to_configured_multilingual_model():
    ef = E5EmbeddingFunction()
    assert ef.get_config()["model_name"] == DEFAULT_EMBEDDING_MODEL


def test_build_from_config_round_trip():
    ef = E5EmbeddingFunction(model_name="custom-model", device="cpu")
    rebuilt = E5EmbeddingFunction.build_from_config(ef.get_config())
    assert rebuilt.get_config() == ef.get_config()


@patch("app.services.embeddings.settings.env", "production")
def test_label_reports_configured_model_outside_tests():
    assert "sentence-transformers" in current_embedding_model_label()


@patch("app.services.embeddings.settings.env", "test")
def test_label_reports_default_during_tests():
    assert "test environment" in current_embedding_model_label()


# --- Backend selection / dispatcher -----------------------------------------


def test_embedding_backend_defaults_to_local():
    """The Settings field's own declared default — independent of whatever
    is in any .env file — proves local is the real default."""
    from app.config import Settings

    assert Settings.model_fields["embedding_backend"].default == "local"


def test_get_embedding_function_returns_local_by_default():
    get_embedding_function.cache_clear()
    try:
        with patch("app.services.embeddings.settings.embedding_backend", "local"):
            ef = get_embedding_function()
        assert isinstance(ef, E5EmbeddingFunction)
    finally:
        get_embedding_function.cache_clear()


def test_get_embedding_function_returns_remote_when_configured():
    get_embedding_function.cache_clear()
    try:
        with patch("app.services.embeddings.settings.embedding_backend", "huggingface"):
            ef = get_embedding_function()
        assert isinstance(ef, HFRemoteEmbeddingFunction)
    finally:
        get_embedding_function.cache_clear()


def test_get_embedding_function_backend_name_is_case_insensitive():
    get_embedding_function.cache_clear()
    try:
        with patch("app.services.embeddings.settings.embedding_backend", "HuggingFace"):
            ef = get_embedding_function()
        assert isinstance(ef, HFRemoteEmbeddingFunction)
    finally:
        get_embedding_function.cache_clear()


def test_local_backend_does_not_require_sentence_transformers_import_at_construction():
    """Constructing E5EmbeddingFunction must not itself import sentence_transformers
    (only actually encoding does) — unchanged behavior, re-asserted here
    alongside the new remote-backend equivalent below."""
    ef = E5EmbeddingFunction(model_name="fake-model")
    assert ef._model is None  # lazy: nothing loaded yet


# --- Remote (Hugging Face) backend ------------------------------------------


def _fake_hf_response(vectors):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = vectors
    return response


FAKE_TOKEN = "hf_fakeTokenForTestingOnlyDoNotUseThis123456"


def test_hf_backend_passage_prefix_and_no_double_prefix():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    fake_vector = [0.1] * EXPECTED_EMBEDDING_DIMENSION
    with patch("httpx.post", return_value=_fake_hf_response([fake_vector])) as mock_post:
        result = ef(["Enrollment requires a signed form."])

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["inputs"] == ["passage: Enrollment requires a signed form."]
    # No double-prefixing: must not contain "passage: passage: ".
    assert "passage: passage:" not in sent_payload["inputs"][0]
    assert len(result) == 1
    assert len(result[0]) == EXPECTED_EMBEDDING_DIMENSION


def test_hf_backend_query_prefix_not_passage():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    fake_vector = [0.2] * EXPECTED_EMBEDDING_DIMENSION
    with patch("httpx.post", return_value=_fake_hf_response([fake_vector])) as mock_post:
        ef.embed_query(["How do I enroll?"])

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["inputs"] == ["query: How do I enroll?"]
    assert "passage:" not in sent_payload["inputs"][0]
    assert "query: query:" not in sent_payload["inputs"][0]


def test_hf_backend_uses_bearer_auth_header_and_https_router_url():
    ef = HFRemoteEmbeddingFunction(model_name="intfloat/multilingual-e5-small", token=FAKE_TOKEN)
    fake_vector = [0.0] * EXPECTED_EMBEDDING_DIMENSION
    with patch("httpx.post", return_value=_fake_hf_response([fake_vector])) as mock_post:
        ef.embed_query(["warmup"])

    call = mock_post.call_args
    url = call.args[0] if call.args else call.kwargs.get("url")
    assert url.startswith("https://")
    assert "intfloat/multilingual-e5-small" in url
    assert call.kwargs["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_hf_backend_enforces_configured_timeout():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN, timeout_seconds=3.5)
    fake_vector = [0.0] * EXPECTED_EMBEDDING_DIMENSION
    with patch("httpx.post", return_value=_fake_hf_response([fake_vector])) as mock_post:
        ef.embed_query(["warmup"])

    assert mock_post.call_args.kwargs["timeout"] == 3.5


def test_hf_backend_rejects_wrong_dimension():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    wrong_dim_vector = [0.1] * (EXPECTED_EMBEDDING_DIMENSION - 1)
    with patch("httpx.post", return_value=_fake_hf_response([wrong_dim_vector])):
        with pytest.raises(RemoteEmbeddingError, match="dimension"):
            ef.embed_query(["test"])


def test_hf_backend_rejects_non_finite_values():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    bad_vector = [float("nan")] + [0.1] * (EXPECTED_EMBEDDING_DIMENSION - 1)
    with patch("httpx.post", return_value=_fake_hf_response([bad_vector])):
        with pytest.raises(RemoteEmbeddingError, match="non-finite"):
            ef.embed_query(["test"])


def test_hf_backend_rejects_malformed_response_shape():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    # Not a list of vectors at all -- e.g. a dict error payload or nested
    # token-level embeddings instead of pooled sentence embeddings.
    with patch("httpx.post", return_value=_fake_hf_response({"error": "model loading"})):
        with pytest.raises(RemoteEmbeddingError, match="unexpected"):
            ef.embed_query(["test"])


def test_hf_backend_rejects_wrong_vector_count():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    one_vector = [[0.1] * EXPECTED_EMBEDDING_DIMENSION]
    with patch("httpx.post", return_value=_fake_hf_response(one_vector)):
        with pytest.raises(RemoteEmbeddingError, match="unexpected"):
            ef(["doc one", "doc two"])  # two inputs, one vector returned


def test_hf_backend_rejects_invalid_json():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("not json")
    with patch("httpx.post", return_value=response):
        with pytest.raises(RemoteEmbeddingError, match="JSON"):
            ef.embed_query(["test"])


def test_hf_backend_raises_on_non_200_status():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    response = MagicMock()
    response.status_code = 503
    with patch("httpx.post", return_value=response):
        with pytest.raises(RemoteEmbeddingError, match="503"):
            ef.embed_query(["test"])


def test_hf_backend_raises_on_timeout():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN, timeout_seconds=5.0)
    with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(RemoteEmbeddingError, match="timed out"):
            ef.embed_query(["test"])


def test_hf_backend_raises_on_transport_error():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
        with pytest.raises(RemoteEmbeddingError):
            ef.embed_query(["test"])


def test_hf_backend_without_token_raises_before_any_network_call():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=None)
    with patch("httpx.post") as mock_post:
        with pytest.raises(RemoteEmbeddingError, match="ASKA_HF_TOKEN"):
            ef.embed_query(["test"])
    mock_post.assert_not_called()


def test_hf_backend_token_never_appears_in_exception_message(caplog):
    """Covers every failure path we can trigger without a live network call:
    the fake token string must never surface in the raised exception's
    message or in any log record."""
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN, timeout_seconds=1.0)

    caught: list[Exception] = []
    with caplog.at_level(logging.DEBUG):
        with patch("httpx.post", side_effect=httpx.TimeoutException("timed out, request=<...Authorization...>")):
            try:
                ef.embed_query(["test"])
            except RemoteEmbeddingError as exc:
                caught.append(exc)
                logger = logging.getLogger("app.services.embeddings")
                logger.exception("embedding warm-up failed")

    assert len(caught) == 1
    assert FAKE_TOKEN not in str(caught[0])
    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()
        if record.exc_text:
            assert FAKE_TOKEN not in record.exc_text


def test_hf_backend_token_never_in_get_config():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    config = ef.get_config()
    assert FAKE_TOKEN not in str(config)
    assert "token" not in config


def test_hf_backend_build_from_config_round_trip_without_token():
    ef = HFRemoteEmbeddingFunction(model_name="custom-remote-model", token=FAKE_TOKEN)
    rebuilt = HFRemoteEmbeddingFunction.build_from_config(ef.get_config())
    assert rebuilt.get_config() == ef.get_config()
    # Token is not part of config and is not carried over by build_from_config;
    # the rebuilt instance falls back to settings.hf_token (None by default here).
    assert rebuilt._token is None


def test_hf_backend_does_not_instantiate_sentence_transformer():
    """The whole point of the remote backend: it must never touch
    sentence-transformers/torch, not even transitively."""
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    fake_vector = [0.0] * EXPECTED_EMBEDDING_DIMENSION
    fake_st_constructor = MagicMock()
    with patch("sentence_transformers.SentenceTransformer", fake_st_constructor):
        with patch("httpx.post", return_value=_fake_hf_response([fake_vector])):
            ef(["doc"])
            ef.embed_query(["query"])
    fake_st_constructor.assert_not_called()


def test_hf_backend_empty_input_short_circuits_without_network_call():
    ef = HFRemoteEmbeddingFunction(model_name="fake-model", token=FAKE_TOKEN)
    with patch("httpx.post") as mock_post:
        assert ef([]) == []
        assert ef.embed_query([]) == []
    mock_post.assert_not_called()

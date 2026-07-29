"""Unit tests for the local E5 embedding function (no real model download)."""

from unittest.mock import MagicMock, patch

import numpy as np

from app.services.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    E5EmbeddingFunction,
    current_embedding_model_label,
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

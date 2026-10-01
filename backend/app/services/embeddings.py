"""Embedding functions for ChromaDB retrieval accuracy.

Chroma's bundled default embedding function (a generic MiniLM ONNX model) has
no fine-tuning for LSPU's documents or for the mix of English/Tagalog/Taglish
phrasing students actually use. This module wraps a multilingual E5 model
instead, via either of two interchangeable backends:

- ``E5EmbeddingFunction`` (default): runs sentence-transformers/torch
  in-process (local backend).
- ``HFRemoteEmbeddingFunction``: calls Hugging Face's hosted inference
  router for the same model, so the calling process never imports
  sentence-transformers/torch at all. Selected via ``ASKA_EMBEDDING_BACKEND=
  huggingface``; proven numerically equivalent to the local model in a
  manual compatibility check (cosine similarity ~1.0, max absolute element
  difference ~1e-7 across synthetic query/passage pairs — see
  ``scripts/compare_hf_embeddings.py``). Hugging Face does not let us pin an
  exact model revision for the hosted router, so the local backend remains
  the default and must stay fully available; switching is an explicit,
  reversible opt-in.

E5 models are trained for *asymmetric* retrieval: passages and queries need
different prefixes ("passage: " / "query: ") to get the accuracy the model
was tuned for, so both backends implement ``embed_query`` separately from
``__call__`` (Chroma calls ``embed_query`` for ``collection.query()`` and
``__call__`` for ``collection.add()``), with identical prefix semantics —
this is what keeps vectors from either backend in the same embedding space.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
# intfloat/multilingual-e5-small's sentence-embedding dimension — verified
# directly from the model (config.json hidden_size, SentenceTransformer's
# own get_sentence_embedding_dimension(), and an actual encoded vector's
# real length all agree: 384). Used to reject a malformed/unexpected remote
# response rather than silently feeding Chroma a vector from a different
# space.
EXPECTED_EMBEDDING_DIMENSION = 384
# Hugging Face's unified Inference Providers router. feature-extraction is
# the task type for sentence/token embeddings.
HF_ROUTER_BASE_URL = "https://router.huggingface.co/hf-inference/models"


class E5EmbeddingFunction:
    """Chroma-compatible embedding function wrapping a local sentence-transformers E5 model."""

    def __init__(self, model_name: str | None = None, device: str | None = None) -> None:
        self._model_name = model_name or settings.embedding_model_name or DEFAULT_EMBEDDING_MODEL
        self._device = device or settings.embedding_device or "cpu"
        self._model: Any = None

    def _get_model(self) -> Any:
        # Lazy-loaded so importing this module (or constructing the store) never
        # requires downloading/loading the model unless it's actually used.
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device=self._device)
        return self._model

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Embed documents/passages for indexing (``collection.add``)."""
        return self._encode([f"passage: {text}" for text in input])

    def embed_query(self, input: list[str]) -> list[list[float]]:
        """Embed a search query (``collection.query``). E5 wants a different prefix than passages."""
        return self._encode([f"query: {text}" for text in input])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    @staticmethod
    def name() -> str:
        return "aska_piyu_e5_local"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self._model_name, "device": self._device}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "E5EmbeddingFunction":
        return E5EmbeddingFunction(
            model_name=config.get("model_name"),
            device=config.get("device"),
        )


class RemoteEmbeddingError(RuntimeError):
    """Any Hugging Face remote-embedding failure. Messages are always static/
    generic — never interpolate the token, a raw provider response body, or
    an upstream exception's own string, so the token can never reach a log
    or an API error response through this path."""


def _validate_and_extract_vectors(payload: Any, *, expected_count: int) -> list[list[float]]:
    """Validate a Hugging Face feature-extraction response shape and reject
    anything malformed/non-finite rather than silently feeding Chroma bad
    vectors."""
    if not isinstance(payload, list) or len(payload) != expected_count:
        raise RemoteEmbeddingError(
            "Hugging Face embedding response shape was unexpected "
            f"(expected a list of {expected_count} vector(s))."
        )
    vectors: list[list[float]] = []
    for row in payload:
        if not isinstance(row, list) or len(row) != EXPECTED_EMBEDDING_DIMENSION:
            raise RemoteEmbeddingError(
                "Hugging Face embedding response contained a vector with an "
                f"unexpected dimension (expected {EXPECTED_EMBEDDING_DIMENSION})."
            )
        vector: list[float] = []
        for value in row:
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise RemoteEmbeddingError(
                    "Hugging Face embedding response contained a non-numeric value."
                ) from None
            if not math.isfinite(number):
                raise RemoteEmbeddingError(
                    "Hugging Face embedding response contained a non-finite value."
                )
            vector.append(number)
        vectors.append(vector)
    return vectors


class HFRemoteEmbeddingFunction:
    """Chroma-compatible embedding function calling Hugging Face's hosted
    inference router instead of loading sentence-transformers/torch
    in-process. See module docstring for the compatibility rationale.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._model_name = model_name or settings.hf_embedding_model or DEFAULT_EMBEDDING_MODEL
        # Explicit None (not falsy-empty-string) check: an empty string is a
        # deliberate "no token configured" signal, not "use the default".
        self._token = token if token is not None else settings.hf_token
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.hf_embedding_timeout_seconds
        )

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Embed documents/passages for indexing (``collection.add``)."""
        return self._encode([f"passage: {text}" for text in input])

    def embed_query(self, input: list[str]) -> list[list[float]]:
        """Embed a search query (``collection.query``). Same prefix semantics as the local backend."""
        return self._encode([f"query: {text}" for text in input])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._token:
            raise RemoteEmbeddingError(
                "ASKA_HF_TOKEN is not configured; the Hugging Face embedding "
                "backend cannot be used."
            )

        import httpx

        url = f"{HF_ROUTER_BASE_URL}/{self._model_name}/pipeline/feature-extraction"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                url,
                headers=headers,
                json={"inputs": texts},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException:
            # Deliberately not `from exc` / not interpolating str(exc): a
            # timeout exception's repr can include the request (and its
            # Authorization header) depending on the underlying transport.
            raise RemoteEmbeddingError(
                f"Hugging Face embedding request timed out after {self._timeout_seconds}s."
            ) from None
        except httpx.HTTPError:
            raise RemoteEmbeddingError(
                "Hugging Face embedding request failed (network/transport error)."
            ) from None

        if response.status_code != 200:
            # Status code only -- never the response body (could echo back
            # request details on some provider error paths) and never
            # response.request (carries the Authorization header).
            raise RemoteEmbeddingError(
                f"Hugging Face embedding request failed with HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError:
            raise RemoteEmbeddingError(
                "Hugging Face embedding response was not valid JSON."
            ) from None

        # Compatibility check already proved the hosted router returns
        # vectors in the same (already L2-normalized) space as the local
        # model for this model — do not renormalize or otherwise alter
        # numerically compatible output here.
        vectors = _validate_and_extract_vectors(payload, expected_count=len(texts))
        # Chroma's Cloud/FastAPI query path calls .tolist() on each query
        # embedding (chromadb/api/fastapi.py's convert_np_embeddings_to_list),
        # which assumes ndarray elements; plain python lists raise
        # AttributeError there. The local backend's PersistentClient path
        # does not hit that function, which is why only the remote backend
        # needs this conversion.
        import numpy as np

        return [np.asarray(vector, dtype=np.float32) for vector in vectors]

    @staticmethod
    def name() -> str:
        return "aska_piyu_e5_huggingface_remote"

    def get_config(self) -> dict[str, Any]:
        # Never include the token: Chroma persists this config to disk
        # alongside the collection.
        return {"model_name": self._model_name}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "HFRemoteEmbeddingFunction":
        # No token in config by design (see get_config) -- __init__ falls
        # back to settings.hf_token from the environment.
        return HFRemoteEmbeddingFunction(model_name=config.get("model_name"))


@lru_cache(maxsize=1)
def get_embedding_function() -> Any:
    """The single chokepoint Chroma calls through (see chroma_store.py).

    Backend is selected by ``ASKA_EMBEDDING_BACKEND`` (default "local" —
    existing behavior is unchanged unless this is explicitly set).
    """
    backend = (settings.embedding_backend or "local").strip().lower()
    if backend == "huggingface":
        return HFRemoteEmbeddingFunction()
    return E5EmbeddingFunction()


def current_embedding_model_label() -> str:
    """Human-readable label for admin statistics; reflects env=test fallback."""
    if settings.env == "test":
        return "ChromaDB default embedding function (test environment)"
    backend = (settings.embedding_backend or "local").strip().lower()
    if backend == "huggingface":
        return f"Hugging Face remote: {settings.hf_embedding_model or DEFAULT_EMBEDDING_MODEL}"
    return f"sentence-transformers: {settings.embedding_model_name or DEFAULT_EMBEDDING_MODEL}"

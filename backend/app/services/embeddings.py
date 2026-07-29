"""Local sentence-embedding function for ChromaDB retrieval accuracy.

Chroma's bundled default embedding function (a generic MiniLM ONNX model) has
no fine-tuning for LSPU's documents or for the mix of English/Tagalog/Taglish
phrasing students actually use. This module wraps a local multilingual E5
sentence-transformer instead.

E5 models are trained for *asymmetric* retrieval: passages and queries need
different prefixes ("passage: " / "query: ") to get the accuracy the model
was tuned for, so this implements ``embed_query`` separately from ``__call__``
(Chroma calls ``embed_query`` for ``collection.query()`` and ``__call__`` for
``collection.add()``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import settings

DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"


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


@lru_cache(maxsize=1)
def get_embedding_function() -> E5EmbeddingFunction:
    return E5EmbeddingFunction()


def current_embedding_model_label() -> str:
    """Human-readable label for admin statistics; reflects env=test fallback."""
    if settings.env == "test":
        return "ChromaDB default embedding function (test environment)"
    return f"sentence-transformers: {settings.embedding_model_name or DEFAULT_EMBEDDING_MODEL}"

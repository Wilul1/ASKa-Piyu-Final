"""Availability guard for document ingestion/extraction/rebuild.

The lightweight Heroku web image (``Dockerfile.heroku-web`` +
``requirements-web.txt``) intentionally omits ``easyocr``/
``sentence-transformers`` (and the ``torch``/``torchvision`` they'd
otherwise pull in). Admin ingestion/extraction/rebuild are the only runtime
paths that touch those packages (see ``document_ingestion.py``,
``easyocr_engine.py``) -- every other feature (auth, KB browsing,
chatbot/RAG, citations, tickets) never imports them at all.

``find_spec`` only checks whether a package is installed; it does not import
it (so this check is cheap and never itself loads OCR weights or a
sentence-transformers model) -- the same lazy-import discipline the rest of
this codebase already relies on for these two packages.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec

_REQUIRED_PACKAGES = ("easyocr", "sentence_transformers")


@lru_cache(maxsize=1)
def ingestion_available() -> bool:
    return all(find_spec(pkg) is not None for pkg in _REQUIRED_PACKAGES)


INGESTION_UNAVAILABLE_MESSAGE = (
    "Document ingestion/extraction/rebuild is not available in this runtime "
    "(OCR/local-embedding dependencies are not installed here). Use the full "
    "local/Docker environment for admin ingestion."
)

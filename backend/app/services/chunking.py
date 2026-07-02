"""Chunking utilities for ASKa-Piyu knowledge-base indexing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DocumentChunk:
    text: str
    chunk_index: int
    char_start: int
    metadata: dict[str, Any] | None = None


def chunks_from_structured_document(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for svc in parsed.get("services", []):
        office = svc.get("office", "[NEEDS REVIEW]")
        service = svc.get("service", "[NEEDS REVIEW]")
        base_meta = {
            "office": office,
            "service": service,
            "classification": svc.get("classification", "[NEEDS REVIEW]"),
            "transaction_type": svc.get("transaction_type", "[NEEDS REVIEW]"),
        }
        req_lines = []
        for r in svc.get("requirements", []):
            req_lines.append(f"- {r.get('requirement')} (Where to secure: {r.get('where_to_secure')})")
        if req_lines:
            chunks.append({
                "text": f"Service: {service}\nOffice: {office}\nRequirements:\n" + "\n".join(req_lines),
                "metadata": {**base_meta, "chunk_type": "requirements"},
            })
        step_lines = []
        for i, st in enumerate(svc.get("steps", []), 1):
            step_lines.append(
                f"{i}. {st.get('client_step')} - {st.get('agency_action')} "
                f"Fees: {st.get('fees')}. Processing time: {st.get('processing_time')}. "
                f"Responsible personnel: {st.get('responsible_personnel')}."
            )
        if step_lines:
            chunks.append({
                "text": f"Service: {service}\nOffice: {office}\nProcedure Steps:\n" + "\n".join(step_lines),
                "metadata": {**base_meta, "chunk_type": "steps"},
            })
        chunks.append({
            "text": f"Service: {service}\nOffice: {office}\nTotal Processing Time: {svc.get('total_processing_time')}",
            "metadata": {**base_meta, "chunk_type": "processing_time"},
        })
    return chunks


def chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    if not text:
        return []
    text = text.strip()
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def create_chunks(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    return chunk_text(text, max_chars=max_chars, overlap=overlap)

def chunk_document_text(
    text: str,
    chunk_size: int = 900,
    chunk_overlap: int = 120
) -> list[DocumentChunk]:
    """
    Compatibility wrapper for knowledge_base_pipeline.py.

    Splits plain cleaned document text into overlapping chunks
    for embeddings and ChromaDB indexing.
    """
    if not text.strip():
        return []

    text = text.strip()
    chunks: list[DocumentChunk] = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text_value = text[start:end].strip()
        if chunk_text_value:
            chunks.append(
                DocumentChunk(
                    text=chunk_text_value,
                    chunk_index=len(chunks),
                    char_start=start,
                )
            )

        if end >= len(text):
            break
        start = max(0, end - chunk_overlap)

    return chunks

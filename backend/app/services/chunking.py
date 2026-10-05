"""Chunking utilities for ASKa-Piyu knowledge-base indexing."""
from __future__ import annotations

import bisect
import re
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

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_BOUNDARY_RE = re.compile(r"\s+")


def _safe_break_points(block: str) -> list[int]:
    """Character offsets where it is safe to start/end a slice of
    ``block`` -- i.e. never inside a word. Always includes 0 and
    len(block). Prefers sentence-ending boundaries; if the block has none
    at all (e.g. one long run-on sentence with no terminal punctuation),
    falls back to every whitespace-delimited word boundary instead, so a
    slice still never cuts a word even without real sentence punctuation.
    """
    points = {0, len(block)}
    for match in _SENTENCE_BOUNDARY_RE.finditer(block):
        points.add(match.end())
    if len(points) <= 2:
        for match in _WORD_BOUNDARY_RE.finditer(block):
            points.add(match.end())
    return sorted(points)


def _slice_oversized_block(
    block: str,
    block_start: int,
    chunks: list[DocumentChunk],
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """Fallback for a single block (paragraph, or the whole text when it
    has no paragraph breaks at all) that on its own still exceeds
    chunk_size. Prefers sentence boundaries, then whole-word boundaries --
    a chunk boundary is never intentionally placed inside a word. Plain
    character-count slicing is now reachable only for a single token
    that is itself longer than chunk_size (e.g. a URL or OCR garbage
    run), which real document text essentially never contains.
    """
    break_points = _safe_break_points(block)
    n = len(block)

    if len(break_points) <= 2:
        # No sentence or word boundary found at all -- nothing safe to
        # break on (a single unbroken token longer than chunk_size).
        start = 0
        while start < n:
            end = min(start + chunk_size, n)
            piece = block[start:end].strip()
            if piece:
                chunks.append(
                    DocumentChunk(text=piece, chunk_index=len(chunks), char_start=block_start + start)
                )
            if end >= n:
                break
            start = max(0, end - chunk_overlap)
        return

    start = 0
    while start < n:
        limit = start + chunk_size
        idx = bisect.bisect_right(break_points, limit) - 1
        end = break_points[idx] if idx >= 0 and break_points[idx] > start else None
        if end is None:
            # The very next safe break point already exceeds chunk_size
            # on its own (one very long sentence/word) -- take it anyway
            # rather than cut mid-word.
            next_idx = bisect.bisect_right(break_points, start)
            end = break_points[next_idx] if next_idx < len(break_points) else n

        piece = block[start:end].strip()
        if piece:
            chunks.append(
                DocumentChunk(text=piece, chunk_index=len(chunks), char_start=block_start + start)
            )
        if end >= n:
            break

        # Snap the overlap start back to the nearest safe break point at
        # or before (end - chunk_overlap), so the next slice also begins
        # cleanly rather than mid-word.
        target = max(start, end - chunk_overlap)
        snap_idx = bisect.bisect_right(break_points, target) - 1
        snapped = break_points[snap_idx] if snap_idx >= 0 else start
        start = snapped if snapped > start else end


def chunk_document_text(
    text: str,
    chunk_size: int = 900,
    chunk_overlap: int = 120,
) -> list[DocumentChunk]:
    """
    Compatibility wrapper for knowledge_base_pipeline.py.

    Splits plain cleaned document text into overlapping chunks for
    embeddings and ChromaDB indexing. Packs whole blank-line-separated
    paragraphs into each chunk so a boundary lands *between* paragraphs
    rather than mid-sentence/mid-thought wherever the text has paragraph
    structure (most cleaned document text does). Only a single paragraph
    (or an entire unbroken block with no paragraph breaks) that alone
    exceeds chunk_size still falls back to a character-count slice.
    """
    if not text.strip():
        return []

    text = text.strip()
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[DocumentChunk] = []
    current = ""
    current_start = 0
    cursor = 0

    for raw_paragraph in paragraphs:
        paragraph = raw_paragraph.strip()
        idx = text.find(raw_paragraph, cursor)
        if idx == -1:
            idx = cursor
        cursor = idx + len(raw_paragraph)

        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= chunk_size:
            if not current:
                current_start = idx
            current = candidate
            continue

        overlap_tail = current[-chunk_overlap:] if (current and chunk_overlap) else ""
        if current:
            chunks.append(DocumentChunk(text=current, chunk_index=len(chunks), char_start=current_start))
            current = ""

        if len(paragraph) <= chunk_size:
            if overlap_tail:
                current = f"{overlap_tail}\n\n{paragraph}"
                current_start = max(0, idx - len(overlap_tail) - 2)
            else:
                current = paragraph
                current_start = idx
        else:
            block = f"{overlap_tail}\n\n{paragraph}" if overlap_tail else paragraph
            block_start = max(0, idx - len(overlap_tail) - 2) if overlap_tail else idx
            _slice_oversized_block(block, block_start, chunks, chunk_size, chunk_overlap)
            current_start = idx + len(paragraph)

    if current:
        chunks.append(DocumentChunk(text=current, chunk_index=len(chunks), char_start=current_start))

    return chunks

"""Global, content-aware chunking engine for the common structured
representation.

Stage 4A, Implementation Task 1 scope only: this module is standalone and
is not called from any live ingestion path, any adapter, or any other
existing module. It consumes :class:`~.types.DocumentRecord`/
:class:`~.types.StructuralUnit` and produces
:class:`app.services.chunking.DocumentChunk` -- the existing, unchanged
four-field type -- so that wiring this into the live pipeline later (a
separate, not-yet-approved task) requires no change to
``chroma_store.py::add_document_chunks`` or the ``DocumentChunk`` contract
itself.

Reuses ``app.services.chunking``'s existing boundary-safe primitives
(``_safe_suffix``, ``_slice_oversized_block``, ``_safe_break_points``) and
``chunk_document_text`` itself for ``ParagraphContent`` -- these are not
duplicated or rewritten; no change to any of them was needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.services.chunking import (
    DocumentChunk,
    _slice_oversized_block,
    chunk_document_text,
)

from .types import (
    DocumentRecord,
    FormContent,
    ListContent,
    ParagraphContent,
    ProcedureContent,
    StructuralUnit,
    TableContent,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ChunkPiece:
    """An un-indexed candidate chunk, local to one StructuralUnit.
    chunk_document_record assigns the real, document-wide chunk_index
    only after every unit's pieces have been collected -- see module
    docstring and the Chroma ID-uniqueness requirement
    (chroma_store.py:307, f"{document_id}::{chunk.chunk_index}")."""

    text: str
    char_start: int
    unit: StructuralUnit
    structured_fields_subset: dict[str, Any] = field(default_factory=dict)
    split_notice: str | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def chunk_document_record(
    document: DocumentRecord,
    *,
    target_chars: int = 1200,
    max_chars: int = 1800,
    overlap_chars: int = 150,
    on_empty_unit: Callable[[StructuralUnit], None] | None = None,
) -> list[DocumentChunk]:
    """Chunk every unit in ``document``, in source order, and return a
    flat ``list[DocumentChunk]`` with document-wide-unique ``chunk_index``
    values. Never mutates ``document`` or any of its units."""
    pieces: list[_ChunkPiece] = []
    for unit in sorted(document.units, key=lambda u: u.source_order):
        if not _unit_has_indexable_content(unit):
            logger.warning(
                "chunk_document_record: unit %r in document %r produced no chunks (empty content)",
                unit.unit_id,
                document.document_id,
            )
            if on_empty_unit is not None:
                on_empty_unit(unit)
            continue
        pieces.extend(
            _chunk_structural_unit(
                unit, target_chars=target_chars, max_chars=max_chars, overlap_chars=overlap_chars
            )
        )

    return [
        DocumentChunk(
            text=piece.text,
            chunk_index=index,
            char_start=piece.char_start,
            metadata=_build_metadata(document, piece),
        )
        for index, piece in enumerate(pieces)
    ]


def _unit_has_indexable_content(unit: StructuralUnit) -> bool:
    content = unit.content
    if isinstance(content, (ParagraphContent, FormContent)):
        return bool(content.text.strip())
    if isinstance(content, ListContent):
        return bool(content.items)
    if isinstance(content, TableContent):
        return bool(content.rows)
    if isinstance(content, ProcedureContent):
        return bool(content.steps)
    return bool(content.text.strip())


# ---------------------------------------------------------------------------
# Per-unit dispatch
# ---------------------------------------------------------------------------


def _chunk_structural_unit(
    unit: StructuralUnit, *, target_chars: int, max_chars: int, overlap_chars: int
) -> list[_ChunkPiece]:
    content = unit.content
    if isinstance(content, ParagraphContent):
        return _chunk_paragraph(
            unit, content, target_chars=target_chars, max_chars=max_chars, overlap_chars=overlap_chars
        )
    if isinstance(content, ListContent):
        return _chunk_list(unit, content, target_chars=target_chars, max_chars=max_chars)
    if isinstance(content, TableContent):
        return _chunk_table(unit, content, target_chars=target_chars, max_chars=max_chars)
    if isinstance(content, ProcedureContent):
        return _chunk_procedure(unit, content, target_chars=target_chars, max_chars=max_chars)
    if isinstance(content, FormContent):
        return _chunk_form(unit, content, target_chars=target_chars, max_chars=max_chars)
    raise TypeError(f"Unhandled content type: {type(content)!r}")  # unreachable: closed Pydantic union


# ---------------------------------------------------------------------------
# ParagraphContent -- reuses chunk_document_text directly, unmodified.
# ---------------------------------------------------------------------------


def _chunk_paragraph(
    unit: StructuralUnit, content: ParagraphContent, *, target_chars: int, max_chars: int, overlap_chars: int
) -> list[_ChunkPiece]:
    """Delegates packing/overlap entirely to the existing
    chunk_document_text (unchanged). That function's own overlap step
    (chunking.py:228-239) prepends a _safe_suffix-selected tail to the
    next paragraph with no size check on the combined result -- on
    sparse-sentence-boundary text this can make _safe_suffix return a
    tail far larger than chunk_overlap, pushing the resulting chunk past
    max_chars (confirmed empirically, Stage 4A chunker review). Any such
    oversized result is caught here and re-split via the same
    _fallback_split_element/_slice_oversized_block path already used for
    oversized list items/table rows/procedure steps/forms -- no new
    splitting logic, and a no-op for the normal case where overlap
    inflation stays within max_chars."""
    raw_chunks = chunk_document_text(content.text, chunk_size=target_chars, chunk_overlap=overlap_chars)
    pieces: list[_ChunkPiece] = []
    for c in raw_chunks:
        if len(c.text) <= max_chars:
            pieces.append(_ChunkPiece(text=c.text, char_start=c.char_start, unit=unit))
            continue
        element = _AtomicElement(rendered_text=c.text, char_start=c.char_start, source_index=0)
        pieces.extend(_fallback_split_element(element, unit, max_chars=max_chars, structured_subset=None))
    return pieces


# ---------------------------------------------------------------------------
# Shared atomic-element packing, used by List/Table/Procedure.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AtomicElement:
    """One list item / table row / procedure step, pre-rendered to text,
    with its own position in the unit's full rendered text and the index
    of the source item (used to slice structured_fields precisely)."""

    rendered_text: str
    char_start: int
    source_index: int


def _pack_atomic_elements(
    elements: list[_AtomicElement],
    unit: StructuralUnit,
    *,
    target_chars: int,
    max_chars: int,
    separator: str = "\n",
    piece_prefix: Callable[[int], str] | None = None,
    structured_subset: Callable[[list[int]], dict[str, Any]] | None = None,
) -> list[_ChunkPiece]:
    """Greedy packing: grow the current piece by whole elements while the
    result (including any repeated ``piece_prefix``, e.g. table headers)
    stays within ``max_chars``; a single oversized element falls back to
    safe text-splitting. ``target_chars`` is advisory (packing stops
    trying to add more once it's comfortably past target AND adding the
    next element would exceed max_chars); ``max_chars`` is the hard limit
    this function never knowingly exceeds for a non-fallback piece.
    """
    pieces: list[_ChunkPiece] = []
    current: list[_AtomicElement] = []
    piece_index = 0

    def flush() -> None:
        nonlocal current, piece_index
        if not current:
            return
        prefix = piece_prefix(piece_index) if piece_prefix else ""
        body = separator.join(e.rendered_text for e in current)
        text = f"{prefix}{body}" if prefix else body
        indices = [e.source_index for e in current]
        pieces.append(
            _ChunkPiece(
                text=text,
                char_start=current[0].char_start,
                unit=unit,
                structured_fields_subset=structured_subset(indices) if structured_subset else {},
            )
        )
        piece_index += 1
        current = []

    for element in elements:
        prefix_len = len(piece_prefix(piece_index)) if piece_prefix else 0
        candidate_body = separator.join([*(e.rendered_text for e in current), element.rendered_text])
        candidate_len = prefix_len + len(candidate_body)

        if not current:
            if candidate_len > max_chars:
                # This single element alone (plus prefix) exceeds the max --
                # oversized-atomic fallback, never split arbitrarily by
                # character count without boundary awareness.
                pieces.extend(
                    _fallback_split_element(element, unit, max_chars=max_chars, structured_subset=structured_subset)
                )
                continue
            current.append(element)
            continue

        if candidate_len <= max_chars:
            current.append(element)
            current_len = prefix_len + len(separator.join(e.rendered_text for e in current))
            if current_len >= target_chars:
                flush()
            continue

        flush()
        # retry this element against a fresh, empty piece
        prefix_len = len(piece_prefix(piece_index)) if piece_prefix else 0
        if prefix_len + len(element.rendered_text) > max_chars:
            pieces.extend(
                _fallback_split_element(element, unit, max_chars=max_chars, structured_subset=structured_subset)
            )
        else:
            current.append(element)

    flush()
    return pieces


def _locate_element_in_rendered_text(
    content_text: str, search_text: str, cursor: int, fallback_rendered: str
) -> tuple[str, int, int]:
    """Finds ``search_text`` inside ``content_text`` starting at
    ``cursor`` and returns the FULL LINE containing it -- so whatever
    prefix/suffix ``content_text`` already has around it (e.g. a "- "
    bullet the adapter rendered, confirmed in ``adapters.py``'s
    ``ListContent``/``ProcedureContent`` construction) is preserved
    verbatim, rather than independently re-synthesized. This is how the
    agreed contract ("char_start is relative to the owning unit's
    rendered content.text") is actually satisfied for List/Procedure
    content, not merely documented as a limitation.

    Falls back to ``fallback_rendered`` at ``cursor`` when
    ``search_text`` can't be located at all -- mirroring
    ``chunk_document_text``'s own find-with-fallback pattern for
    paragraphs (``chunking.py:216-219``) -- so a future producer whose
    ``content.text`` doesn't actually contain each item's text verbatim
    degrades gracefully instead of crashing.

    Returns ``(rendered_text, char_start, next_cursor)``.
    """
    if not search_text:
        return fallback_rendered, cursor, cursor + len(fallback_rendered) + 1
    start = content_text.find(search_text, cursor)
    if start == -1:
        return fallback_rendered, cursor, cursor + len(fallback_rendered) + 1
    line_start = content_text.rfind("\n", 0, start) + 1
    end_of_search_text = start + len(search_text)
    next_newline = content_text.find("\n", end_of_search_text)
    line_end = next_newline if next_newline != -1 else len(content_text)
    return content_text[line_start:line_end], line_start, line_end


def _fallback_split_element(
    element: _AtomicElement,
    unit: StructuralUnit,
    *,
    max_chars: int,
    structured_subset: Callable[[list[int]], dict[str, Any]] | None,
) -> list[_ChunkPiece]:
    """A single atomic element (list item / table row / procedure step)
    that alone exceeds max_chars. Reuses chunk_document_text's own
    oversized-block fallback (_slice_oversized_block) via a throwaway
    list -- not duplicated -- then re-wraps the results as _ChunkPiece
    with a split_notice and corrected, element-relative char_start."""
    raw_chunks: list[DocumentChunk] = []
    _slice_oversized_block(element.rendered_text, element.char_start, raw_chunks, max_chars, 0)
    total = len(raw_chunks)
    subset = structured_subset([element.source_index]) if structured_subset else {}
    return [
        _ChunkPiece(
            text=c.text,
            char_start=c.char_start,
            unit=unit,
            structured_fields_subset=subset,
            split_notice=f"part {i + 1} of {total}: atomic element exceeded max_chars, split at a safe boundary",
        )
        for i, c in enumerate(raw_chunks)
    ]


# ---------------------------------------------------------------------------
# ListContent
# ---------------------------------------------------------------------------


def _chunk_list(
    unit: StructuralUnit, content: ListContent, *, target_chars: int, max_chars: int
) -> list[_ChunkPiece]:
    elements: list[_AtomicElement] = []
    cursor = 0
    for index, item in enumerate(content.items):
        fallback = f"{item.ordinal}. {item.text}" if item.ordinal else item.text
        rendered, char_start, cursor = _locate_element_in_rendered_text(content.text, item.text, cursor, fallback)
        elements.append(_AtomicElement(rendered_text=rendered, char_start=char_start, source_index=index))
    return _pack_atomic_elements(elements, unit, target_chars=target_chars, max_chars=max_chars)


# ---------------------------------------------------------------------------
# TableContent -- repeated headers count toward max_chars.
# ---------------------------------------------------------------------------


def _chunk_table(
    unit: StructuralUnit, content: TableContent, *, target_chars: int, max_chars: int
) -> list[_ChunkPiece]:
    header_line = " | ".join(content.headers) + "\n" if content.headers else ""
    # Repeat headers on every piece, including the first -- a table
    # chunk should always be self-describing. The prefix is the same
    # regardless of piece index, so no per-index logic is needed.
    piece_prefix = (lambda _piece_index: header_line) if header_line else None

    elements: list[_AtomicElement] = []
    cursor = len(header_line)
    for index, row in enumerate(content.rows):
        rendered = " | ".join(cell.text for cell in row)
        elements.append(_AtomicElement(rendered_text=rendered, char_start=cursor, source_index=index))
        cursor += len(rendered) + 1

    return _pack_atomic_elements(
        elements,
        unit,
        target_chars=target_chars,
        max_chars=max_chars,
        piece_prefix=piece_prefix,
    )


# ---------------------------------------------------------------------------
# ProcedureContent -- never separates client_step from agency_action.
# ---------------------------------------------------------------------------


def _chunk_procedure(
    unit: StructuralUnit, content: ProcedureContent, *, target_chars: int, max_chars: int
) -> list[_ChunkPiece]:
    elements: list[_AtomicElement] = []
    cursor = 0
    for index, step in enumerate(content.steps):
        search_text = f"{step.client_step} -> {step.agency_action}"
        prefix = f"{step.ordinal}. " if step.ordinal else ""
        fallback = f"{prefix}{search_text}"
        rendered, char_start, cursor = _locate_element_in_rendered_text(content.text, search_text, cursor, fallback)
        elements.append(_AtomicElement(rendered_text=rendered, char_start=char_start, source_index=index))

    def structured_subset(indices: list[int]) -> dict[str, Any]:
        steps = [content.steps[i] for i in indices]
        return {
            "extracted_steps": [
                {
                    "ordinal": s.ordinal,
                    "client_step": s.client_step,
                    "agency_action": s.agency_action,
                    "fee": s.fee,
                    "processing_time": s.processing_time,
                    "person_responsible": s.person_responsible,
                }
                for s in steps
            ]
        }

    return _pack_atomic_elements(
        elements, unit, target_chars=target_chars, max_chars=max_chars, structured_subset=structured_subset
    )


# ---------------------------------------------------------------------------
# FormContent -- whole-form default; atomic fallback only, per spec.
# Reliable field-to-requirement grouping is not attempted here: no real
# document in this project has ever exercised more than one logical group
# per form (confirmed in prior investigation phases), so inventing a
# grouping rule now would have no real evidence to validate it against.
# ---------------------------------------------------------------------------


def _chunk_form(
    unit: StructuralUnit, content: FormContent, *, target_chars: int, max_chars: int
) -> list[_ChunkPiece]:
    full_subset = dict(unit.structured_fields)
    if len(content.text) <= max_chars:
        return [_ChunkPiece(text=content.text, char_start=0, unit=unit, structured_fields_subset=full_subset)]

    element = _AtomicElement(rendered_text=content.text, char_start=0, source_index=0)
    return _fallback_split_element(
        element, unit, max_chars=max_chars, structured_subset=lambda _indices: full_subset
    )


# ---------------------------------------------------------------------------
# Metadata construction
# ---------------------------------------------------------------------------


def _build_metadata(document: DocumentRecord, piece: _ChunkPiece) -> dict[str, Any]:
    unit = piece.unit
    metadata: dict[str, Any] = {
        "document_id": document.document_id,
        "source_filename": document.source_filename,
        "unit_id": unit.unit_id,
        "title": unit.title,
        "hierarchy_path": list(unit.hierarchy_path),
        "content_type": unit.content_type,
        "structural_type": unit.structural_type,
        "page_start": unit.page_start,
        "page_end": unit.page_end,
    }
    if unit.hierarchy_path:
        # Safe minimal derivation: _enrich_chunk_citation_metadata
        # (chroma_store.py:1069-1079) is an OR-fallback chain needing
        # only ONE non-empty value among source_section/section_heading/
        # section/article/canonical_topic -- the last, most specific
        # hierarchy_path element satisfies that without guessing which
        # original field (chapter/article/section) each position was,
        # which cannot be done reliably from today's filtered list (see
        # Stage 4A specification). Separate, correctly-labeled
        # chapter/article/section/appendix keys are populated here too,
        # read from searchable_fields -- harmlessly absent today since
        # the adapter fix that would populate them is a separate,
        # not-yet-approved task.
        metadata["section"] = unit.hierarchy_path[-1]
    for key in ("chapter", "article", "section", "appendix"):
        value = unit.searchable_fields.get(key)
        if value is not None:
            metadata[key] = value
    for key, value in unit.searchable_fields.items():
        metadata.setdefault(key, value)
    for key, value in piece.structured_fields_subset.items():
        metadata[key] = value
    if piece.split_notice:
        metadata["split_notice"] = piece.split_notice
    return metadata

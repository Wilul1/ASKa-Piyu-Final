"""Conversion adapters from each existing producer's current output into the
common structured representation (:mod:`.types`).

Stage 1 scope only: these functions READ existing producer objects/dicts and
build :class:`~.types.DocumentRecord`/:class:`~.types.StructuralUnit` values.
None of them modify their source producer, none of them are called from any
live ingestion path, and none of them decide chunk boundaries -- that is
explicitly out of scope until the global chunker stage.

Each adapter takes the document-level identity facts (``document_id``,
``source_filename``, classification) as explicit parameters rather than
inventing them, since the existing per-producer objects do not carry that
information themselves.
"""
from __future__ import annotations

import json
from typing import Any

from app.services.chunking import DocumentChunk
from app.services.handbook_policy_processor import HandbookPolicyDocument

from .types import (
    DocumentRecord,
    ExtractionDiagnostics,
    FormContent,
    ListContent,
    ListItem,
    ParagraphContent,
    ProcedureContent,
    ProcedureStep,
    RecognitionDiagnostics,
    StructuralUnit,
)


def _page_diagnostics(page_start: int | None, page_end: int | None) -> ExtractionDiagnostics:
    return ExtractionDiagnostics(page_info_unavailable=page_start is None and page_end is None)


def _non_empty(*values: Any) -> list[str]:
    return [str(v) for v in values if v]


# ---------------------------------------------------------------------------
# 1. Handbook units (HandbookKnowledgeUnit, via HandbookPolicyDocument)
# ---------------------------------------------------------------------------


def adapt_handbook_document(
    document: HandbookPolicyDocument,
    *,
    document_id: str,
) -> DocumentRecord:
    """``HandbookPolicyDocument.units`` already carries a true page-range
    and real chapter/article/section hierarchy (confirmed in
    ``handbook_policy_processor.py``); neither is recomputed here, only
    carried through."""
    units: list[StructuralUnit] = []
    for index, unit in enumerate(document.units):
        metadata = dict(unit.metadata)
        hierarchy_path = _non_empty(
            metadata.get("chapter"), metadata.get("article"),
            metadata.get("section"), metadata.get("appendix"),
        )
        page_start = metadata.get("page_start")
        page_end = metadata.get("page_end")
        # Individually-tagged chapter/article/section/appendix, read from
        # the ORIGINAL metadata before hierarchy_path's own filtering --
        # hierarchy_path drops None entries before building its list, so
        # position within it cannot be trusted to mean "chapter" vs.
        # "article" vs. "section" once any level is sparse (confirmed
        # real example: Faculty Manual unit_91 has chapter+section but no
        # article, making hierarchy_path's index 1 actually "section").
        # A key is added only when its original value is non-None --
        # never inferred, never reconstructed from hierarchy_path.
        searchable_fields: dict[str, Any] = {}
        for key in ("chapter", "article", "section", "appendix"):
            value = metadata.get(key)
            if value is not None:
                searchable_fields[key] = value
        units.append(
            StructuralUnit(
                unit_id=f"handbook:{index}",
                source_order=index,
                title=unit.title or None,
                # unit.article_text (not unit.content) -- the live Handbook
                # chunk-building path embeds the title+breadcrumb-prefixed
                # article_text as the chunk's actual indexed/embedded text,
                # not the bare body. Using unit.content here would silently
                # drop that prefix from what Chroma actually stores and
                # retrieves, even though title/hierarchy_path are also
                # kept as separate structured fields below.
                content=ParagraphContent(text=unit.article_text),
                structural_type="paragraph",
                content_type=str(metadata.get("content_type") or "policy"),
                hierarchy_path=hierarchy_path,
                page_start=page_start,
                page_end=page_end,
                extraction_diagnostics=_page_diagnostics(page_start, page_end),
                recognition_diagnostics=RecognitionDiagnostics(),
                searchable_fields=searchable_fields,
            )
        )
    return DocumentRecord(
        document_id=document_id,
        source_filename=document.source_title,
        classification="information",
        source_metadata={"doc_no": document.doc_no} if document.doc_no else {},
        units=units,
    )


# ---------------------------------------------------------------------------
# 2. Citizen's Charter V2 services (dicts shaped like CharterServiceV2)
# ---------------------------------------------------------------------------


def adapt_charter_v2_services(
    services: list[dict[str, Any]],
    *,
    document_id: str,
    source_filename: str,
) -> DocumentRecord:
    """``citizen_charter_extractor_v2.py::CharterServiceV2`` has real
    ``page_start``/``page_end: int | None`` fields -- carried through as
    genuine values when present, never estimated when absent. (This is
    more page information than earlier review phases of this project
    attributed to the Charter path; that finding was about chunk metadata
    built later in ``knowledge_document_types.py``, not about this
    dataclass itself -- noted here rather than silently reconciled.)"""
    units: list[StructuralUnit] = []
    for index, service in enumerate(services):
        if not isinstance(service, dict):
            continue
        title = service.get("service_title") or service.get("service") or service.get("title")
        office = service.get("office_division") or service.get("office")
        steps = service.get("steps") or []
        requirements = service.get("requirements") or []

        content: ParagraphContent | ListContent | ProcedureContent
        if steps:
            content = ProcedureContent(
                text="\n".join(
                    f"{s.get('client_step', '')} -> {s.get('agency_action', '')}" for s in steps
                ),
                steps=[
                    ProcedureStep(
                        client_step=str(s.get("client_step") or ""),
                        agency_action=str(s.get("agency_action") or ""),
                        fee=s.get("fees"),
                        processing_time=s.get("processing_time"),
                        person_responsible=s.get("person_responsible"),
                    )
                    for s in steps
                ],
            )
        elif requirements:
            content = ListContent(
                text="\n".join(
                    f"- {r.get('requirement', '')} (Where to secure: {r.get('where_to_secure', '')})"
                    for r in requirements
                ),
                items=[
                    ListItem(text=f"{r.get('requirement', '')} (Where to secure: {r.get('where_to_secure', '')})")
                    for r in requirements
                ],
                ordered=False,
            )
        else:
            content = ParagraphContent(text=str(title or ""))

        searchable: dict[str, Any] = {}
        if office:
            searchable["office"] = str(office)
        if service.get("who_may_avail"):
            searchable["who_may_avail"] = str(service["who_may_avail"])
        if service.get("classification"):
            searchable["classification"] = str(service["classification"])

        structured: dict[str, Any] = {}
        if requirements:
            structured["extracted_requirements"] = requirements
        if steps:
            structured["extracted_steps"] = steps

        page_start = service.get("page_start")
        page_end = service.get("page_end")
        units.append(
            StructuralUnit(
                unit_id=f"charter_v2:{index}",
                source_order=index,
                title=str(title) if title else None,
                content=content,
                structural_type="service",
                content_type="service_procedure",
                page_start=page_start,
                page_end=page_end,
                extraction_diagnostics=_page_diagnostics(page_start, page_end),
                recognition_diagnostics=RecognitionDiagnostics(),
                searchable_fields=searchable,
                structured_fields=structured,
            )
        )
    return DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification="procedure",
        units=units,
    )


# ---------------------------------------------------------------------------
# 3. ServiceRecord (structured_document_parser.py, PROCEDURE path)
# ---------------------------------------------------------------------------


def adapt_service_records(
    records: list[dict[str, Any]],
    *,
    document_id: str,
    source_filename: str,
) -> DocumentRecord:
    """Takes the actual live shape produced by
    ``structured_document_parser.py::parse_structured_document(text)
    ["services"]`` -- confirmed by reading that function's return
    statement to be ``[ServiceRecord(...).to_dict() for ...]``, i.e.
    plain dicts, not ``ServiceRecord`` instances (the dataclass itself is
    never what callers actually hold downstream). ``ServiceRecord.to_dict()``
    has no page field at all (confirmed by reading the dataclass) --
    ``page_start``/``page_end`` are therefore always ``None`` here, never
    estimated."""
    units: list[StructuralUnit] = []
    for index, record in enumerate(records):
        steps = record.get("steps") or []
        requirements = record.get("requirements") or []
        service_title = record.get("service") or ""

        content: ParagraphContent | ListContent | ProcedureContent
        if steps:
            content = ProcedureContent(
                text="\n".join(f"{s.get('client_step', '')} -> {s.get('agency_action', '')}" for s in steps),
                steps=[
                    ProcedureStep(
                        client_step=str(s.get("client_step") or ""),
                        agency_action=str(s.get("agency_action") or ""),
                        fee=s.get("fees"),
                        processing_time=s.get("processing_time"),
                        person_responsible=s.get("responsible_personnel"),
                    )
                    for s in steps
                ],
            )
        elif requirements:
            content = ListContent(
                text="\n".join(
                    f"- {r.get('requirement', '')} (Where to secure: {r.get('where_to_secure', '')})"
                    for r in requirements
                ),
                items=[
                    ListItem(text=f"{r.get('requirement', '')} (Where to secure: {r.get('where_to_secure', '')})")
                    for r in requirements
                ],
                ordered=False,
            )
        else:
            content = ParagraphContent(text=service_title)

        structured: dict[str, Any] = {}
        if requirements:
            structured["extracted_requirements"] = requirements
        if steps:
            structured["extracted_steps"] = steps

        units.append(
            StructuralUnit(
                unit_id=f"procedure:{index}",
                source_order=index,
                title=service_title or None,
                content=content,
                structural_type="service",
                content_type="service_procedure",
                page_start=None,
                page_end=None,
                extraction_diagnostics=ExtractionDiagnostics(page_info_unavailable=True),
                recognition_diagnostics=RecognitionDiagnostics(),
                searchable_fields={
                    k: v
                    for k, v in {
                        "office": record.get("office"),
                        "who_may_avail": record.get("who_may_avail"),
                        "classification": record.get("classification"),
                    }.items()
                    if v
                },
                structured_fields=structured,
            )
        )
    return DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification="procedure",
        units=units,
    )


# ---------------------------------------------------------------------------
# 4. FormRecord (structured_document_parser.py, REQUIREMENT path)
# ---------------------------------------------------------------------------


def adapt_form_record(
    record: dict[str, Any],
    *,
    document_id: str,
    source_filename: str,
) -> DocumentRecord:
    """Takes the actual live shape produced by
    ``structured_document_parser.py::parse_form_document(text)["form"]``
    -- confirmed by reading that function's return statement to be
    ``FormRecord(...).to_dict()``, a plain dict, not a ``FormRecord``
    instance.

    ``_requirement_chunks`` always produces exactly one chunk per
    document today (confirmed: ``parse_form_document`` has no multi-form
    detection at all); this adapter preserves that -- one
    ``StructuralUnit`` per form -- and does not attempt to change or
    work around that limitation, per this task's scope."""
    structured: dict[str, Any] = {}
    if record.get("requirements"):
        structured["extracted_requirements"] = record["requirements"]
    if record.get("options"):
        structured["form_options"] = record["options"]
    if record.get("related_services"):
        structured["related_services"] = record["related_services"]
    if record.get("how_to_fill_out"):
        structured["how_to_fill_out"] = record["how_to_fill_out"]

    title = record.get("form_title") or record.get("form_name")
    unit = StructuralUnit(
        unit_id="requirement:0",
        source_order=0,
        title=title or None,
        content=FormContent(text=str(title or ""), field_names=list(record.get("fields") or [])),
        structural_type="form",
        content_type="requirement",
        page_start=None,
        page_end=None,
        extraction_diagnostics=ExtractionDiagnostics(page_info_unavailable=True),
        recognition_diagnostics=RecognitionDiagnostics(),
        searchable_fields={
            k: v
            for k, v in {
                "office": record.get("office"),
                "form_code": record.get("form_code"),
            }.items()
            if v
        },
        structured_fields=structured,
    )
    return DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification="requirement",
        units=[unit],
    )


# ---------------------------------------------------------------------------
# 5. Generic chunk_document_text() output
# ---------------------------------------------------------------------------


def adapt_generic_chunks(
    chunks: list[DocumentChunk],
    *,
    document_id: str,
    source_filename: str,
) -> DocumentRecord:
    """``chunk_document_text()`` itself sets no metadata at all (every
    chunk's ``metadata`` is ``None`` from this function directly) -- no
    title, page range, or hierarchy exists to carry through at this
    layer, so every such field is honestly left ``None``/empty rather
    than invented."""
    units: list[StructuralUnit] = []
    for chunk in chunks:
        units.append(
            StructuralUnit(
                unit_id=f"generic:{chunk.chunk_index}",
                source_order=chunk.chunk_index,
                title=None,
                content=ParagraphContent(text=chunk.text),
                structural_type="paragraph",
                content_type="information",
                page_start=None,
                page_end=None,
                extraction_diagnostics=ExtractionDiagnostics(page_info_unavailable=True),
                recognition_diagnostics=RecognitionDiagnostics(),
            )
        )
    return DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification="information",
        units=units,
    )


# ---------------------------------------------------------------------------
# 6. Generic raw text, pre-chunking -- for the global-chunker integration.
# Unlike adapt_generic_chunks above (kept, unmodified, for old-vs-new
# equivalence testing against chunk_document_text's existing output),
# this adapter never chunks anything itself: it wraps raw_text as ONE
# unit, so chunk_document_record is the only thing that ever splits it.
# ---------------------------------------------------------------------------


def adapt_generic_text(
    raw_text: str,
    *,
    document_id: str,
    source_filename: str,
) -> DocumentRecord:
    """Wraps ``raw_text`` as a single ``ParagraphContent`` unit, verbatim
    -- no stripping, normalization, splitting, or chunking. Produces
    exactly one ``StructuralUnit`` regardless of ``raw_text``'s length,
    including when it is empty or whitespace-only (``chunk_document_record``'s
    own existing empty-unit handling -- confirmed, ``chunker.py``'s
    ``_unit_has_indexable_content`` -- already covers that case
    correctly without any special-casing needed here)."""
    return DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification="information",
        units=[
            StructuralUnit(
                unit_id="generic:0",
                source_order=0,
                title=None,
                content=ParagraphContent(text=raw_text),
                structural_type="paragraph",
                content_type="information",
                page_start=None,
                page_end=None,
                extraction_diagnostics=ExtractionDiagnostics(page_info_unavailable=True),
                recognition_diagnostics=RecognitionDiagnostics(),
            )
        ],
    )


# ---------------------------------------------------------------------------
# 7. Already-built, already-filtered chunks (from _procedure_chunks,
# _requirement_chunks, or build_chunks_from_charter_v2_services) -- for
# global-chunker integration where the recognition/filtering logic that
# produced them is fused into private helpers this package cannot reach
# or reproduce. This adapter re-wraps each existing chunk as one
# StructuralUnit, verbatim, so chunk_document_record is used only for
# its oversized-unit fallback-split behavior, never to re-decide a
# boundary the original producer already decided. chunk.chunk_index/
# char_start are intentionally dropped -- chunk_document_record
# reassigns both globally across the whole document. Every other
# existing metadata key (document_type, source_document, title,
# page_number, office, section_heading, etc.) is carried through via
# searchable_fields, NOT structured_fields -- confirmed by direct
# inspection of chunker.py: _build_metadata only ever reads
# piece.structured_fields_subset (set solely by _chunk_form's own
# unit.structured_fields passthrough), while _chunk_paragraph -- the
# handler ParagraphContent units here always go through -- never
# populates it, so anything placed in structured_fields here would be
# silently dropped. unit.searchable_fields, by contrast, is read
# directly off the unit and carried through unconditionally for every
# content type (confirmed empirically: office/page_number were lost
# via structured_fields, preserved via searchable_fields).
# ---------------------------------------------------------------------------


def adapt_prebuilt_chunks(
    chunks: list[DocumentChunk],
    *,
    document_id: str,
    source_filename: str,
    classification: str,
) -> DocumentRecord:
    """Wraps each already-built ``DocumentChunk`` as one ``StructuralUnit``,
    verbatim. Does not re-filter, re-normalize, or re-decide any boundary
    the original producer already decided."""
    units: list[StructuralUnit] = []
    for index, chunk in enumerate(chunks):
        metadata = dict(chunk.metadata or {})
        title = metadata.pop("title", None)
        searchable_fields: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                searchable_fields[key] = value
            else:
                # Legacy producers JSON-encode every list/dict value before
                # putting it in chunk metadata (confirmed in
                # knowledge_document_types.py) -- nothing reaches this
                # branch today, but any future non-scalar value is encoded
                # the same way rather than silently dropped.
                searchable_fields[key] = json.dumps(value)
        units.append(
            StructuralUnit(
                unit_id=f"{classification}:{index}",
                source_order=index,
                title=title,
                content=ParagraphContent(text=chunk.text),
                structural_type="paragraph",
                content_type=classification,
                extraction_diagnostics=ExtractionDiagnostics(page_info_unavailable=True),
                recognition_diagnostics=RecognitionDiagnostics(),
                searchable_fields=searchable_fields,
            )
        )
    return DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification=classification,
        units=units,
    )

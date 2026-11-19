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
import math
from typing import Any

from app.services.chunking import DocumentChunk
from app.services.handbook_policy_processor import HandbookPolicyDocument

from .types import (
    DocumentRecord,
    EvidenceOrigin,
    ExtractionDiagnostics,
    FormContent,
    ListContent,
    ListItem,
    PageGeometry,
    ParagraphContent,
    ProcedureContent,
    ProcedureStep,
    RecognitionDiagnostics,
    SpatialRegion,
    SpatialRegionType,
    StructuralUnit,
)


def _page_diagnostics(page_start: int | None, page_end: int | None) -> ExtractionDiagnostics:
    return ExtractionDiagnostics(page_info_unavailable=page_start is None and page_end is None)


# ---------------------------------------------------------------------------
# Spatial evidence propagation (Phase 6.21): converts already-computed page
# geometry (PageExtraction.words / .table_regions, or the duck-typed
# LightweightPageExtraction equivalent -- both expose the same attribute
# names, confirmed by direct comparison of the two dataclasses) into the
# shared PageGeometry/SpatialRegion contract. Pure, read-only conversion:
# does not alter, re-rank, or re-interpret anything it reads, and does not
# decide any extraction/candidate outcome -- only existing geometry already
# sitting on the page object is carried forward. Works unchanged for either
# page type via duck typing (getattr), since neither declares a shared base
# class and this function must not force one just to add an isinstance
# check.
# ---------------------------------------------------------------------------


def build_page_geometry(page: Any) -> PageGeometry:
    """Build one page's spatial evidence from an already-extracted page
    object (``PageExtraction`` or ``LightweightPageExtraction``-shaped).

    Text, region IDs, reading order, and source provenance are copied from
    extraction. Bounding boxes on the returned ``PageGeometry`` are in
    canonical PDF-point space relative to the original page rectangle:

    * digital boxes already in that space are preserved exactly when
      source coordinate dimensions equal the PDF page dimensions
    * OCR boxes are mapped with independent X/Y scale
      ``x_pdf = x * page_width / coordinate_width`` (same for Y) only
      when extraction recorded explicit compatible preconditions
    * ``geometry_scale`` is provenance only and is never the transform
    * missing OCR metadata means unknown, not compatible -- boxes are
      withheld (``bbox=None``) rather than defaulted to rotation 0

    The source ``page`` object and its native bbox dicts are not mutated.
    CELL boxes stay ``None`` -- this function does not invent them.
    """
    page_number = getattr(page, "page_number", None)
    words = getattr(page, "words", None) or []
    table_regions = getattr(page, "table_regions", None) or []
    width, width_invalid = _read_dimension(getattr(page, "page_width", None))
    height, height_invalid = _read_dimension(getattr(page, "page_height", None))
    source_coordinate_width, coord_width_invalid = _read_dimension(
        getattr(page, "coordinate_width", None)
    )
    source_coordinate_height, coord_height_invalid = _read_dimension(
        getattr(page, "coordinate_height", None)
    )
    geometry_scale = _optional_float(getattr(page, "geometry_scale", None))
    rotation, rotation_invalid = _read_optional_int(getattr(page, "rotation", None))

    mapping = _coordinate_mapping(
        page,
        width=width,
        height=height,
        coordinate_width=source_coordinate_width,
        coordinate_height=source_coordinate_height,
        invalid_dimensions=any(
            (width_invalid, height_invalid, coord_width_invalid, coord_height_invalid)
        ),
        rotation=rotation,
        rotation_invalid=rotation_invalid,
        geometry_scale=geometry_scale,
    )

    regions: list[SpatialRegion] = []
    for order, word in enumerate(words):
        try:
            native_bbox = (
                float(word["x0"]), float(word["y0"]),
                float(word["x1"]), float(word["y1"]),
            )
        except (KeyError, TypeError, ValueError):
            native_bbox = None
        regions.append(
            SpatialRegion(
                region_id=f"p{page_number}:word:{order}",
                page_number=page_number,
                region_type=SpatialRegionType.WORD,
                text=str(word.get("text", "")) if isinstance(word, dict) else str(word),
                bbox=_map_bbox(native_bbox, mapping),
                reading_order_index=order,
            )
        )

    for table_index, table in enumerate(table_regions):
        if not isinstance(table, dict):
            continue
        raw_bbox = table.get("bbox")
        try:
            native_bbox = (
                tuple(float(v) for v in raw_bbox) if raw_bbox and len(raw_bbox) == 4 else None
            )
        except (TypeError, ValueError):
            native_bbox = None
        rows = table.get("rows") or []
        table_region_id = f"p{page_number}:table:{table_index}"
        regions.append(
            SpatialRegion(
                region_id=table_region_id,
                page_number=page_number,
                region_type=SpatialRegionType.TABLE,
                text="\n".join(" | ".join(row) for row in rows),
                bbox=_map_bbox(native_bbox, mapping),
            )
        )
        for row_index, row in enumerate(rows):
            for column_index, cell_text in enumerate(row):
                # No per-cell bbox: _extract_table_regions only captures
                # the table's own overall bbox, not individual cell boxes
                # (confirmed by reading pymupdf_extractor.py directly) --
                # left None rather than guessed from row/column position.
                regions.append(
                    SpatialRegion(
                        region_id=f"{table_region_id}:cell:{row_index}:{column_index}",
                        page_number=page_number,
                        region_type=SpatialRegionType.CELL,
                        text=str(cell_text),
                        row=row_index,
                        column=column_index,
                    )
                )

    return PageGeometry(
        page_number=page_number,
        width=width if not width_invalid else None,
        height=height if not height_invalid else None,
        rotation=rotation if rotation is not None else 0,
        geometry_scale=geometry_scale,
        coordinate_width=mapping.output_coordinate_width,
        coordinate_height=mapping.output_coordinate_height,
        regions=regions,
    )


def _optional_float(value: Any) -> float | None:
    """Copy a numeric extraction field, or ``None`` when it is absent/unusable.

    Does not invent a substitute (no bbox-derived page size, no default
    scale). Invalid values stay unknown rather than becoming ``0.0``.
    """
    parsed, invalid = _read_dimension(value, allow_non_positive=True)
    if invalid:
        return None
    return parsed


def _read_dimension(
    value: Any, *, allow_non_positive: bool = False
) -> tuple[float | None, bool]:
    """Parse a dimension field.

    Returns ``(parsed, invalid)``. ``invalid`` is True when a value was
    supplied but is not a usable finite number. Missing values are
    ``(None, False)`` -- unknown, not invented.
    """
    if value is None:
        return None, False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None, True
    if not math.isfinite(parsed):
        return None, True
    if not allow_non_positive and parsed <= 0:
        return parsed, True
    return parsed, False


def _read_optional_int(value: Any) -> tuple[int | None, bool]:
    """Parse an optional integer field.

    Missing ``None`` is ``(None, False)`` -- unknown, not zero.
    Unparseable values are ``(None, True)``.
    """
    if value is None:
        return None, False
    try:
        return int(value), False
    except (TypeError, ValueError):
        return None, True


def _finite_positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


class _CoordinateMapping:
    """How native extraction boxes become canonical PDF-point boxes."""

    __slots__ = (
        "mode",
        "scale_x",
        "scale_y",
        "output_coordinate_width",
        "output_coordinate_height",
    )

    def __init__(
        self,
        mode: str,
        *,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        output_coordinate_width: float | None = None,
        output_coordinate_height: float | None = None,
    ) -> None:
        self.mode = mode
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.output_coordinate_width = output_coordinate_width
        self.output_coordinate_height = output_coordinate_height


def _boxes_already_pdf_points(page: Any, geometry_scale: float | None) -> bool:
    """True when native boxes are already in PDF-point space.

    Digital extraction and the lightweight handbook path never emit OCR
    pixels. OCR pages (``method=="ocr"``) and duck-typed pages whose
    ``geometry_scale`` is a non-unit zoom are treated as source-native
    and must be mapped or withheld -- never passed through as canonical.
    """
    method = getattr(page, "method", None)
    if method == "ocr":
        return False
    if method == "digital":
        return True
    if geometry_scale is not None and geometry_scale != 1.0:
        return False
    return True


def _axis_aligned_uniform_scale(
    src_w: float,
    src_h: float,
    dst_w: float,
    dst_h: float,
    *,
    pixel_tolerance: float = 1.0,
) -> bool:
    """True when ``dst`` is an axis-aligned uniform scale of ``src``.

    One-pixel tolerance covers pixmap integer rounding and LANCZOS
    ``round()``. An axis swap or anisotropic stretch fails.
    """
    if not all(_finite_positive(value) for value in (src_w, src_h, dst_w, dst_h)):
        return False
    predicted_h = dst_w * src_h / src_w
    if abs(predicted_h - dst_h) <= pixel_tolerance:
        return True
    predicted_w = dst_h * src_w / src_h
    return abs(predicted_w - dst_w) <= pixel_tolerance


def _ocr_preconditions_established(
    page: Any,
    *,
    width: float | None,
    height: float | None,
    coordinate_width: float | None,
    coordinate_height: float | None,
    rotation: int | None,
    rotation_invalid: bool,
) -> bool:
    """OCR pixels may be mapped into ``page.rect`` PDF points only when
    extraction recorded explicit compatible provenance.

    Verified PyMuPDF 1.27 contract used here: ``get_text("words")`` and
    ``get_pixmap(clip=None)`` share ``page.rect`` space. ``page.rect`` is
    origin-shifted to the visible top-left even when CropBox is offset, so
    a recorded origin of ``(0, 0)`` plus a full-page axis-aligned raster
    of that rectangle is sufficient. Non-zero rotation and non-zero origin
    are unsupported by this scale-only mapping.
    """
    if rotation_invalid or rotation is None:
        return False
    if rotation % 360 != 0:
        return False

    origin_x, origin_x_invalid = _read_dimension(
        getattr(page, "page_origin_x", None), allow_non_positive=True
    )
    origin_y, origin_y_invalid = _read_dimension(
        getattr(page, "page_origin_y", None), allow_non_positive=True
    )
    if origin_x_invalid or origin_y_invalid:
        return False
    if origin_x is None or origin_y is None:
        return False
    if origin_x != 0.0 or origin_y != 0.0:
        return False

    raster_width, raster_w_invalid = _read_dimension(getattr(page, "raster_width", None))
    raster_height, raster_h_invalid = _read_dimension(getattr(page, "raster_height", None))
    if raster_w_invalid or raster_h_invalid:
        return False
    if not _finite_positive(raster_width) or not _finite_positive(raster_height):
        return False
    if not all(
        _finite_positive(value)
        for value in (width, height, coordinate_width, coordinate_height)
    ):
        return False
    if not _axis_aligned_uniform_scale(width, height, raster_width, raster_height):
        return False
    if not _axis_aligned_uniform_scale(
        raster_width, raster_height, coordinate_width, coordinate_height
    ):
        return False
    return True


def _coordinate_mapping(
    page: Any,
    *,
    width: float | None,
    height: float | None,
    coordinate_width: float | None,
    coordinate_height: float | None,
    invalid_dimensions: bool,
    rotation: int | None,
    rotation_invalid: bool,
    geometry_scale: float | None,
) -> _CoordinateMapping:
    if invalid_dimensions:
        return _CoordinateMapping("withhold")

    can_scale = all(
        _finite_positive(value)
        for value in (width, height, coordinate_width, coordinate_height)
    )
    digital = _boxes_already_pdf_points(page, geometry_scale)
    if not digital:
        if not _ocr_preconditions_established(
            page,
            width=width,
            height=height,
            coordinate_width=coordinate_width,
            coordinate_height=coordinate_height,
            rotation=rotation,
            rotation_invalid=rotation_invalid,
        ):
            return _CoordinateMapping("withhold")
        if can_scale and coordinate_width == width and coordinate_height == height:
            return _CoordinateMapping(
                "identity",
                output_coordinate_width=width,
                output_coordinate_height=height,
            )
        if can_scale:
            return _CoordinateMapping(
                "scale",
                scale_x=width / coordinate_width,  # type: ignore[operator]
                scale_y=height / coordinate_height,  # type: ignore[operator]
                output_coordinate_width=width,
                output_coordinate_height=height,
            )
        return _CoordinateMapping("withhold")

    if can_scale and coordinate_width == width and coordinate_height == height:
        return _CoordinateMapping(
            "identity",
            output_coordinate_width=width,
            output_coordinate_height=height,
        )
    return _CoordinateMapping(
        "passthrough",
        output_coordinate_width=coordinate_width,
        output_coordinate_height=coordinate_height,
    )


def _map_bbox(
    bbox: tuple[float, float, float, float] | None,
    mapping: _CoordinateMapping,
) -> tuple[float, float, float, float] | None:
    if bbox is None or mapping.mode == "withhold":
        return None
    if mapping.mode in ("identity", "passthrough"):
        return bbox
    x0, y0, x1, y1 = bbox
    return (
        x0 * mapping.scale_x,
        y0 * mapping.scale_y,
        x1 * mapping.scale_x,
        y1 * mapping.scale_y,
    )


def build_page_geometries(pages: list[Any] | None) -> list[PageGeometry]:
    """Build spatial evidence for every page in ``pages`` (or ``[]`` when
    ``pages`` is ``None``/empty -- callers that don't have raw pages
    available keep working identically, since every existing adapter
    signature below defaults this to ``None``)."""
    if not pages:
        return []
    return [build_page_geometry(page) for page in pages]


def _non_empty(*values: Any) -> list[str]:
    return [str(v) for v in values if v]


# ---------------------------------------------------------------------------
# 1. Handbook units (HandbookKnowledgeUnit, via HandbookPolicyDocument)
# ---------------------------------------------------------------------------


def adapt_handbook_document(
    document: HandbookPolicyDocument,
    *,
    document_id: str,
    pages: list[Any] | None = None,
) -> DocumentRecord:
    """``HandbookPolicyDocument.units`` already carries a true page-range
    and real chapter/article/section hierarchy (confirmed in
    ``handbook_policy_processor.py``); neither is recomputed here, only
    carried through.

    ``pages`` (Phase 6.21, optional, default ``None``): the raw
    ``PageExtraction``/``LightweightPageExtraction`` list this document was
    built from, if the caller has it available. Purely additive -- every
    existing caller that omits it gets byte-identical output to before this
    parameter existed; passing it only attaches spatial evidence
    (``DocumentRecord.page_geometries``), it never changes which units are
    built or how."""
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
                # Explicitly known, not a legacy default: article_text is
                # extracted directly from the source PDF, never model-
                # inferred. (Which heading it's grouped under can involve
                # genuine reconstruction heuristics upstream in
                # handbook_policy_processor.py -- that uncertainty belongs
                # to recognition_diagnostics, not this field, and is not
                # newly exposed here; out of this task's scope.)
                evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
            )
        )
    return DocumentRecord(
        document_id=document_id,
        source_filename=document.source_title,
        classification="information",
        source_metadata={"doc_no": document.doc_no} if document.doc_no else {},
        units=units,
        page_geometries=build_page_geometries(pages),
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
    pages: list[Any] | None = None,
) -> DocumentRecord:
    """Wraps ``raw_text`` as a single ``ParagraphContent`` unit, verbatim
    -- no stripping, normalization, splitting, or chunking. Produces
    exactly one ``StructuralUnit`` regardless of ``raw_text``'s length,
    including when it is empty or whitespace-only (``chunk_document_record``'s
    own existing empty-unit handling -- confirmed, ``chunker.py``'s
    ``_unit_has_indexable_content`` -- already covers that case
    correctly without any special-casing needed here).

    ``pages`` (Phase 6.21, optional, default ``None``): see
    ``adapt_handbook_document`` -- same additive, zero-behavior-change-
    when-omitted contract."""
    return DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification="information",
        page_geometries=build_page_geometries(pages),
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
                # Verbatim, not reconstructed or inferred: wrapped as-is,
                # no stripping/normalization/splitting (see module docstring).
                evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
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
    pages: list[Any] | None = None,
) -> DocumentRecord:
    """Wraps each already-built ``DocumentChunk`` as one ``StructuralUnit``,
    verbatim. Does not re-filter, re-normalize, or re-decide any boundary
    the original producer already decided.

    ``pages`` (Phase 6.21, optional, default ``None``): see
    ``adapt_handbook_document`` -- same additive, zero-behavior-change-
    when-omitted contract. This is the adapter Citizen's Charter's real
    production path uses (via ``_quality_payload_from_charter_v2_services``
    in ``knowledge_base_pipeline.py``); that call site does not pass
    ``pages`` today, so Charter candidate output is unaffected by this
    parameter's mere existence."""
    units: list[StructuralUnit] = []
    for index, chunk in enumerate(chunks):
        metadata = dict(chunk.metadata or {})
        title = metadata.pop("title", None)
        # Carried through onto the structural fields below (not popped --
        # left in `metadata` so they're ALSO copied into searchable_fields
        # by the generic loop just like every other scalar key, preserving
        # existing searchable_fields/metadata shape exactly as before this
        # fix). Read with .get, never invented: a legacy producer that
        # never had a page number leaves both None here, same as before.
        page_start = metadata.get("page_start")
        page_end = metadata.get("page_end")
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
                page_start=page_start,
                page_end=page_end,
                extraction_diagnostics=_page_diagnostics(page_start, page_end),
                recognition_diagnostics=RecognitionDiagnostics(),
                searchable_fields=searchable_fields,
                # The wrapped chunk.text is already-rendered deterministic
                # text from a legacy producer (_procedure_chunks /
                # _requirement_chunks) -- verbatim, not model-inferred.
                evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
            )
        )
    return DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification=classification,
        units=units,
        page_geometries=build_page_geometries(pages),
    )

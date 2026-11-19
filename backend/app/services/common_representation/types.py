"""Representation types for the approved common PDF structured representation.

Target architecture (Stage 1 implements only the types in this module and
the adapters in :mod:`.adapters`):

    PDF extraction -> structure recognition -> common structured
    representation -> one global chunking engine -> shared validation
    -> Chroma ingestion

``DocumentRecord``/``StructuralUnit`` and the diagnostics/relation types
follow this project's existing ``app/services/`` convention of plain
``@dataclass`` types (confirmed against ``chunking.py::DocumentChunk``,
``handbook_policy_processor.py::HandbookKnowledgeUnit``, and
``knowledge_document_types.py::KnowledgeDocumentTypeDetection`` -- none of
which use Pydantic). The content model is the one deliberate exception,
built as a Pydantic ``Literal``-tagged discriminated union per the
approved design; this introduces no new dependency, since Pydantic is
already installed and used elsewhere in this project (``app/models/
schemas.py``, ``app/config.py``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

# ---------------------------------------------------------------------------
# Evidence origin: where a piece of extracted content actually came from.
# Defined before the content model so TableCell can reference it directly
# (no forward-reference/string-annotation resolution needed).
#
# ``None`` (the default everywhere this appears) means "not classified" --
# it is NOT an assertion that content is verbatim, reconstructed, or
# anything else. Existing/legacy units built before this field existed are
# correctly represented by ``None``, never retroactively asserted to be
# ``VERBATIM_SOURCE`` (that would be an unsupported claim about data this
# field never evaluated). Only a NEW producer that genuinely knows a given
# piece of content's origin should set this explicitly.
# ---------------------------------------------------------------------------


class EvidenceOrigin(str, Enum):
    VERBATIM_SOURCE = "verbatim_source"
    LAYOUT_RECONSTRUCTED = "layout_reconstructed"
    MODEL_INFERRED = "model_inferred"
    MISSING = "missing"


def effective_evidence_origin(
    cell_origin: "EvidenceOrigin | None", unit_origin: "EvidenceOrigin | None"
) -> "EvidenceOrigin | None":
    """The origin that actually applies to one piece of content: a more
    specific origin (e.g. a table cell's own) always wins over a less
    specific unit-level fallback -- never the reverse. Returns ``None``
    (unclassified) only when neither level has been set."""
    return cell_origin if cell_origin is not None else unit_origin


# ---------------------------------------------------------------------------
# Content model: Pydantic Literal-tagged discriminated union.
# ---------------------------------------------------------------------------


class ListItem(BaseModel):
    text: str
    ordinal: str | None = None


class TableCell(BaseModel):
    text: str
    row: int
    column: int
    is_header: bool = False
    # Optional, unset by default (``None``) -- see ``EvidenceOrigin`` above.
    # A cell built by a NEW producer that genuinely knows this cell's
    # origin should set it explicitly; ``None`` means "not classified",
    # never an assertion that the cell is verbatim.
    evidence_origin: EvidenceOrigin | None = None


class ProcedureStep(BaseModel):
    client_step: str
    agency_action: str
    ordinal: str | None = None
    fee: str | None = None
    processing_time: str | None = None
    person_responsible: str | None = None


class ParagraphContent(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    text: str


class ListContent(BaseModel):
    kind: Literal["list"] = "list"
    text: str
    items: list[ListItem] = Field(default_factory=list)
    ordered: bool = False


class TableContent(BaseModel):
    kind: Literal["table"] = "table"
    text: str
    headers: list[str] = Field(default_factory=list)
    rows: list[list[TableCell]] = Field(default_factory=list)


class ProcedureContent(BaseModel):
    kind: Literal["procedure"] = "procedure"
    text: str
    steps: list[ProcedureStep] = Field(default_factory=list)


class FormContent(BaseModel):
    kind: Literal["form"] = "form"
    text: str
    field_names: list[str] = Field(default_factory=list)


ContentModel = Annotated[
    Union[ParagraphContent, ListContent, TableContent, ProcedureContent, FormContent],
    Field(discriminator="kind"),
]
"""Use with ``TypeAdapter(ContentModel)`` to validate/parse a tagged dict
back into the correct variant -- see ``content_model_adapter`` below."""

content_model_adapter: TypeAdapter[
    ParagraphContent | ListContent | TableContent | ProcedureContent | FormContent
] = TypeAdapter(ContentModel)

AnyContent = Union[ParagraphContent, ListContent, TableContent, ProcedureContent, FormContent]


# ---------------------------------------------------------------------------
# Diagnostics: tri-state (True = checked, issue found; False = checked,
# clean; None = not checked / unavailable for this document type).
# Extraction and recognition concerns are kept as separate dataclasses.
# ---------------------------------------------------------------------------


class Completeness(str, Enum):
    """Describes the EXTRACTION PROCESS's own success for a unit -- did we
    get everything we tried to get. Independent of ``content_absent_in_source``
    below, which describes the SOURCE document instead; both can legitimately
    be unknown/unset at once (e.g. an unreadable page: you don't even know
    whether it had a requirements section to look for)."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass
class ExtractionDiagnostics:
    broken_words_detected: bool | None = None
    joined_words_detected: bool | None = None
    page_info_unavailable: bool | None = None
    ocr_fallback_used: bool | None = None
    # Default UNKNOWN, not COMPLETE -- an extraction path that never
    # evaluates completeness must not silently assert success.
    completeness: Completeness = Completeness.UNKNOWN
    # True: source assessed, content genuinely absent (not a defect).
    # False: source assessed, content exists.
    # None (default): source presence has not been established.
    content_absent_in_source: bool | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class RecognitionDiagnostics:
    uncertain_heading: bool | None = None
    hierarchy_may_be_inherited_incorrectly: bool | None = None
    possible_unrelated_content_merged: bool | None = None
    uncertain_boundary: bool | None = None
    uncertain_table_structure: bool | None = None
    notes: list[str] = field(default_factory=list)


class DiagnosticDisposition(str, Enum):
    """Shared-validation disposition a diagnostic flag maps to. Stage 1
    only defines this mapping for later stages to consume -- it does not
    implement a validation gate."""

    INFORMATIONAL = "informational"
    REVIEW_REQUIRED = "review_required"
    BLOCKING = "blocking"


DIAGNOSTIC_DISPOSITIONS: dict[str, DiagnosticDisposition] = {
    "extraction.broken_words_detected": DiagnosticDisposition.REVIEW_REQUIRED,
    "extraction.joined_words_detected": DiagnosticDisposition.REVIEW_REQUIRED,
    "extraction.page_info_unavailable": DiagnosticDisposition.INFORMATIONAL,
    "extraction.ocr_fallback_used": DiagnosticDisposition.INFORMATIONAL,
    "recognition.uncertain_heading": DiagnosticDisposition.REVIEW_REQUIRED,
    "recognition.hierarchy_may_be_inherited_incorrectly": DiagnosticDisposition.REVIEW_REQUIRED,
    "recognition.possible_unrelated_content_merged": DiagnosticDisposition.BLOCKING,
    "recognition.uncertain_boundary": DiagnosticDisposition.BLOCKING,
    "recognition.uncertain_table_structure": DiagnosticDisposition.REVIEW_REQUIRED,
}


# ---------------------------------------------------------------------------
# Spatial evidence: page-level geometry already computed by PDF extraction
# (PageExtraction.words / .table_regions, or the duck-typed
# LightweightPageExtraction equivalent) but currently discarded once
# _flatten_pages()-style code collapses it into plain linear text. These
# types only PRESERVE and CARRY that already-extracted geometry forward --
# they do not reconstruct relationships themselves (see SpatialAssociation
# below) and no current adapter populates StructuralUnit.spatial_associations
# with a real heading-to-table/label-to-value association yet; that
# reconstruction work is an explicitly separate, later phase. A document or
# unit with no spatial evidence is unaffected: every field here is additive
# with a safe empty/None default, and absence must never be read as
# evidence that the underlying content is itself absent or defective.
# ---------------------------------------------------------------------------


class SpatialRegionType(str, Enum):
    WORD = "word"
    BLOCK = "block"
    TABLE = "table"
    CELL = "cell"


@dataclass(frozen=True)
class SpatialRegion:
    """One extracted, page-located piece of source evidence. Mirrors exactly
    what PyMuPDF already returns (word bounding boxes; a table's own bbox;
    one table cell's row/column position and text) -- never a fabricated
    or inferred geometry. ``bbox`` and ``row``/``column`` are optional
    because the project's existing table extraction
    (``pymupdf_extractor.py::_extract_table_regions``) only captures a
    table's own overall bbox today, not per-cell bounding boxes -- a CELL
    region therefore has real ``row``/``column``/``text`` but ``bbox=None``,
    which is an honest gap, not a bug to paper over with a guessed box."""

    region_id: str
    page_number: int
    region_type: SpatialRegionType
    text: str
    bbox: tuple[float, float, float, float] | None = None
    row: int | None = None
    column: int | None = None
    reading_order_index: int | None = None


@dataclass(frozen=True)
class PageGeometry:
    """Document/page-level spatial evidence, referenced by
    ``StructuralUnit``/``SpatialAssociation`` rather than duplicated into
    every unit (see ``DocumentRecord.page_geometries``).

    ``width``/``height`` are the source PDF page rectangle in PDF points
    when extraction supplied them (``page.rect``). They stay ``None`` when
    the producer did not capture dimensions -- never estimated from word
    boxes, never hardcoded per document.

    ``geometry_scale`` is copied from the extraction object and is **not**
    applied to region coordinates. It is the PDF rendering zoom for OCR
    pages (``settings.pdf_ocr_zoom``) and ``1.0`` for digital PDF points.
    It is not by itself a complete OCR-to-PDF conversion factor: the
    winning EasyOCR image may have been resized after rendering.

    ``coordinate_width`` / ``coordinate_height`` are the dimensions of the
    space containing stored region ``bbox`` values after
    ``build_page_geometry``:

    * when normalization succeeds, they equal ``width`` / ``height``
      (canonical PDF points of the original page rectangle)
    * ``None`` -- unknown, or geometry was withheld because it could not
      be mapped safely; do not invent a size from word boxes or zoom

    ``build_page_geometry`` applies a full-page axis-aligned mapping
    (independent X/Y scale) to OCR boxes only when extraction recorded
    explicit compatible provenance: rotation ``0``, page-rectangle origin
    ``(0, 0)``, an original pixmap that is an axis-aligned full-page
    raster of that rectangle, and a winning OCR image that remains a
    uniform axis-aligned scale of that pixmap. Missing metadata is
    unknown, not compatible.

        x_pdf = x_region * width / coordinate_width
        y_pdf = y_region * height / coordinate_height

    Identity digital pages (source coordinate dimensions already equal
    to the PDF page) keep boxes unchanged. ``geometry_scale`` is never
    the transform factor. Direct construction of this dataclass still
    accepts omitted fields as ``None`` (see ``EvidenceOrigin`` above)."""

    page_number: int
    width: float | None = None
    height: float | None = None
    rotation: int = 0
    regions: list[SpatialRegion] = field(default_factory=list)
    geometry_scale: float | None = None
    coordinate_width: float | None = None
    coordinate_height: float | None = None


class SpatialRelationKind(str, Enum):
    HEADING_TO_TABLE = "heading_to_table"
    LABEL_TO_VALUE = "label_to_value"
    CONTINUATION = "continuation"
    SAME_ROW = "same_row"
    PAGE_FURNITURE = "page_furniture"
    OTHER = "other"


@dataclass(frozen=True)
class SpatialAssociation:
    """Evidence of a relationship between two or more spatial regions --
    e.g. a heading region and the table region(s) it may govern. This is
    evidence only: nothing in this project reads a ``SpatialAssociation``
    as automatic permission to merge, reassign, or reinterpret content: no
    current code constructs one from proximity alone, and none will until
    a later, separate reconstruction phase explicitly implements that
    logic. ``origin`` deliberately reuses the existing ``EvidenceOrigin``
    enum (``LAYOUT_RECONSTRUCTED`` standing in for "deterministic
    geometric", ``MISSING`` for "unresolved") rather than introducing a
    near-duplicate enum, per this module's own reuse-existing-types
    convention.

    ``confidence`` is an ordinal count-ratio of named checks the producing
    reconstruction function evaluated, or -- when that function uses an
    all-or-nothing acceptance policy -- ``1.0`` meaning every required
    check passed. It is not a calibrated probability of correctness and
    must not be read as "100% likely correct" unless independently
    calibrated against labeled outcomes. ``None`` means the producer did
    not assign a score (typically an unresolved ``MISSING`` association).
    ``note`` is explanatory only and is never the identity of the
    association."""

    association_id: str
    region_ids: list[str]
    kind: SpatialRelationKind
    origin: EvidenceOrigin
    confidence: float | None = None
    note: str | None = None


# ---------------------------------------------------------------------------
# Relationships: additive context only. No relation kind authorizes
# merging two units into one chunk or deciding a chunk boundary.
# ---------------------------------------------------------------------------


class RelationKind(str, Enum):
    PARENT_CHILD = "parent_child"
    CONTINUES_NUMBERING = "continues_numbering"
    BELONGS_TO_SECTION = "belongs_to_section"
    RELATED_PROCEDURE_STEP = "related_procedure_step"
    RELATED_FORM_OR_SERVICE = "related_form_or_service"


@dataclass(frozen=True)
class UnitRelation:
    kind: RelationKind
    target_unit_id: str
    note: str | None = None


# ---------------------------------------------------------------------------
# StructuralUnit / DocumentRecord
# ---------------------------------------------------------------------------


@dataclass
class StructuralUnit:
    unit_id: str
    source_order: int
    title: str | None
    content: AnyContent
    structural_type: str
    content_type: str
    hierarchy_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    extraction_diagnostics: ExtractionDiagnostics = field(default_factory=ExtractionDiagnostics)
    recognition_diagnostics: RecognitionDiagnostics = field(default_factory=RecognitionDiagnostics)
    relations: list[UnitRelation] = field(default_factory=list)
    # Additive, same discipline as `relations` above: empty by default,
    # never authorizes a merge/reassignment by itself. No current adapter
    # populates this with a real association yet -- see the module-level
    # comment above SpatialRegion for why that reconstruction work is
    # deliberately out of scope here.
    spatial_associations: list[SpatialAssociation] = field(default_factory=list)
    searchable_fields: dict[str, str | int | float | bool] = field(default_factory=dict)
    # Unit-level fallback only -- used where finer-grained origin has no
    # home (Paragraph/List/Form content). A TableCell's own evidence_origin
    # (more specific) must never be overwritten by this fallback when both
    # are present; see effective_evidence_origin() above. None (default)
    # means unclassified, same convention as TableCell.evidence_origin --
    # never defaulted to VERBATIM_SOURCE for legacy/unevaluated units.
    evidence_origin: EvidenceOrigin | None = None
    # Deliberately Any-valued: existing producers' nested fields are not
    # uniformly shaped (ServiceRecord/CharterServiceV2 requirements/steps
    # are list[dict]; FormRecord's requirements/fields/related_services are
    # list[str]; FormRecord.options is dict[str, list[str]]). Forcing one
    # shape here would misrepresent real source data.
    #
    # Placeholder provenance convention (optional): a producer that knows
    # one or more of ITS OWN keys in this dict (or in searchable_fields) was
    # generated as a placeholder rather than extracted from the source may
    # record those key names as a list under PLACEHOLDER_FIELDS_KEY (see
    # below). Absence of this key means "not evaluated for placeholder
    # status", never "confirmed genuine". A generated placeholder must
    # never be treated as source evidence by anything that reads this.
    structured_fields: dict[str, Any] = field(default_factory=dict)


PLACEHOLDER_FIELDS_KEY = "__placeholder_fields"
"""``structured_fields``/``searchable_fields`` key convention: maps to
``list[str]`` of field names (from either dict) whose value was generated
as a placeholder (e.g. because the underlying source field was empty) --
never genuine source text, even when the generated text happens to read
identically to text the source could plausibly contain verbatim."""


@dataclass
class DocumentRecord:
    document_id: str
    source_filename: str
    classification: str
    classification_reason: str | None = None
    classification_scores: dict[str, int] | None = None
    classification_manual_override: bool = False
    source_metadata: dict[str, str] = field(default_factory=dict)
    units: list[StructuralUnit] = field(default_factory=list)
    # Document-level spatial evidence (see PageGeometry above), referenced
    # by page_number rather than duplicated per unit. Empty by default --
    # a document built without raw pages available (every existing live
    # call site, today) is unaffected and behaves exactly as before this
    # field existed.
    page_geometries: list[PageGeometry] = field(default_factory=list)

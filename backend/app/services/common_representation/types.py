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


@dataclass
class ExtractionDiagnostics:
    broken_words_detected: bool | None = None
    joined_words_detected: bool | None = None
    page_info_unavailable: bool | None = None
    ocr_fallback_used: bool | None = None
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
    searchable_fields: dict[str, str | int | float | bool] = field(default_factory=dict)
    # Deliberately Any-valued: existing producers' nested fields are not
    # uniformly shaped (ServiceRecord/CharterServiceV2 requirements/steps
    # are list[dict]; FormRecord's requirements/fields/related_services are
    # list[str]; FormRecord.options is dict[str, list[str]]). Forcing one
    # shape here would misrepresent real source data.
    structured_fields: dict[str, Any] = field(default_factory=dict)


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

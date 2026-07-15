from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.services.knowledge_document_types import (
    KnowledgeDocumentType,
    KnowledgeDocumentTypeName,
    coerce_document_type_name,
    to_base_document_type,
)


class ErrorResponse(BaseModel):
    status: str = "error"
    detail: str


class DocumentFieldSchema(BaseModel):
    """Dynamic field — any label the parser detects."""

    label: str
    field_type: str = Field(..., description="'text' or 'list'")
    value: str | None = None
    items: list[str] | None = None


class StructuredDocumentSchema(BaseModel):
    fields: list[DocumentFieldSchema]
    formatted_text: str


class PipelineStageSchema(BaseModel):
    key: str
    label: str
    status: str
    detail: str | None = None


class KnowledgeValidationReportSchema(BaseModel):
    document_type: str
    total_knowledge_units: int
    total_chunks: int
    average_chunk_words: float
    largest_chunk_words: int
    smallest_chunk_words: int
    missing_metadata_count: int
    toc_like_units_count: int
    empty_units_count: int
    suspicious_units_count: int
    oversized_chunks_count: int
    known_campuses: list[str] = Field(default_factory=list)
    unique_campus_names: list[str] = Field(default_factory=list)
    unique_program_campus_values: list[str] = Field(default_factory=list)
    invalid_campus_values: list[dict] = Field(default_factory=list)
    remaining_ocr_word_splits: list[dict] = Field(default_factory=list)
    status: str


class DocumentTypeDetectionSchema(BaseModel):
    """Detected knowledge document typing for admin extract/ingest.

    ``document_type`` is the specific type (e.g. handbook_policy).
    ``base_document_type`` is the broad chunking category (information /
    procedure / requirement). Types are shared with
    ``KnowledgeDocumentTypeName`` so schema and detector cannot drift.
    """

    document_type: KnowledgeDocumentTypeName
    base_document_type: KnowledgeDocumentType = KnowledgeDocumentType.INFORMATION
    reason: str
    scores: dict[str, int] = Field(default_factory=dict)
    manual_override: bool = False
    admin_selected_document_type: str | None = None
    parser_kind: str | None = None

    @field_validator("document_type", mode="before")
    @classmethod
    def _coerce_document_type(cls, value: Any) -> Any:
        if isinstance(value, KnowledgeDocumentTypeName):
            return value
        return coerce_document_type_name(None if value is None else str(value))

    @field_validator("base_document_type", mode="before")
    @classmethod
    def _coerce_base_document_type(cls, value: Any) -> Any:
        if value is None or value == "":
            return KnowledgeDocumentType.INFORMATION
        if isinstance(value, KnowledgeDocumentType):
            return value
        return to_base_document_type(str(value))


class KnowledgeUnitSchema(BaseModel):
    unit_index: int
    title: str
    content: str
    content_type: str
    hierarchy_path: str
    word_count: int
    page_start: int | None = None
    page_end: int | None = None
    status: str
    suspicious_reasons: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ChunkPreviewSchema(BaseModel):
    chunk_index: int
    title: str
    word_count: int
    hierarchy_path: str
    page_start: int | None = None
    page_end: int | None = None
    content_preview: str
    content: str | None = None
    metadata: dict = Field(default_factory=dict)


class KnowledgeBaseStatisticsSchema(BaseModel):
    documents_indexed: int
    total_chunks_indexed: int
    embedding_model: str
    vector_store: str
    last_indexed_document: dict | None = None
    error: str | None = None
    citation_ready_documents: int | None = None
    citation_reindex_required: int | None = None
    chunks_missing_document_id: int | None = None
    document_type_counts: dict[str, int] = Field(default_factory=dict)
    article_type_counts: dict[str, int] = Field(default_factory=dict)
    indexed_documents: list[dict[str, Any]] = Field(default_factory=list)


# --- Admin: knowledge base creation (OCR → ChromaDB) ---


class ExtractDocumentResponse(BaseModel):
    """Preview extraction only; does not update ChromaDB."""

    status: str = "success"
    flow: str = "admin_extraction"
    document_type: str
    document_profile: str | None = None
    admin_selected_document_type: str | None = None
    parser_document_type: str | None = None
    source_type: str | None = None
    raw_text: str = Field(..., description="Raw OCR/PDF extraction before final review")
    cleaned_text: str = Field(..., description="Deterministically cleaned extraction")
    review_text: str = Field(..., description="Draft text admin should review before indexing")
    extracted_text: str = Field(..., description="Backward-compatible alias for review_text")
    page_count: int
    extraction_method: str
    structuring_method: str
    pipeline_stages: list[PipelineStageSchema]
    structured: StructuredDocumentSchema
    diagnostic_report: dict | None = None
    validation_report: KnowledgeValidationReportSchema | None = None
    detected_document_type: DocumentTypeDetectionSchema | None = None
    knowledge_units: list[KnowledgeUnitSchema] = Field(default_factory=list)
    chunk_preview: list[ChunkPreviewSchema] = Field(default_factory=list)
    kb_statistics: KnowledgeBaseStatisticsSchema | None = None
    # Citizen's Charter Extraction V2 (compact — no raw word geometry).
    charter_v2_services: list[dict[str, Any]] = Field(default_factory=list)
    charter_v2_detected_count: int = 0
    charter_v2_clean_count: int = 0
    charter_v2_needs_review_count: int = 0
    charter_v2_low_quality_count: int = 0
    charter_v2_rag_only_count: int = 0
    charter_v2_diagnostics: dict[str, Any] = Field(default_factory=dict)


class IngestKnowledgeBaseResponse(BaseModel):
    """Full admin pipeline: extract → clean → chunk → embed → ChromaDB."""

    status: str = "success"
    flow: str = "admin_knowledge_base_ingest"
    document_id: str
    document_type: str
    source_filename: str
    title: str
    chunks_indexed: int
    page_count: int
    extraction_method: str
    structuring_method: str
    pipeline_stages: list[PipelineStageSchema]
    extracted_text_preview: str
    structured: StructuredDocumentSchema
    diagnostic_report: dict | None = None
    validation_report: KnowledgeValidationReportSchema | None = None
    detected_document_type: DocumentTypeDetectionSchema | None = None
    knowledge_units: list[KnowledgeUnitSchema] = Field(default_factory=list)
    chunk_preview: list[ChunkPreviewSchema] = Field(default_factory=list)
    kb_statistics: KnowledgeBaseStatisticsSchema | None = None


class RetrievalTestRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)


class RetrievalTestChunkSchema(BaseModel):
    rank: int
    title: str
    similarity_score: float
    original_score: float | None = None
    reranked_score: float | None = None
    boost_reasons: list[str] = Field(default_factory=list)
    hierarchy_path: str
    page_start: int | None = None
    page_end: int | None = None
    content_preview: str
    content: str


class RetrievalTestResponse(BaseModel):
    status: str = "success"
    flow: str = "admin_retrieval_test"
    question: str
    top_k: int
    results: list[RetrievalTestChunkSchema]
    kb_statistics: KnowledgeBaseStatisticsSchema | None = None


# --- Student: question answering (ChromaDB search only) ---


class AskQuestionRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


class SourceChunk(BaseModel):
    document_id: str
    title: str
    source_filename: str
    chunk_index: int
    snippet: str
    relevance_score: float


class AskQuestionResponse(BaseModel):
    status: str = "success"
    flow: str = "student_question"
    question: str
    answer: str
    sources: list[SourceChunk]


# --- Production QA chatbot ---


class QAAskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    debug: bool = False


class QASourceSchema(BaseModel):
    title: str
    path: str
    page: int | None = None
    page_range: str | None = None
    matching_sections: int | None = None
    # Level-2 citation grounding
    citation_id: str | None = None
    document_id: str | None = None
    source_filename: str | None = None
    source_section: str | None = None
    page_number: int | None = None
    source_excerpt: str | None = None
    source_view_url: str | None = None
    source_page_url: str | None = None
    source_label: str | None = None
    pdf_available: bool | None = None
    citation_note: str | None = None


class QACitationSchema(BaseModel):
    citation_id: str
    document_id: str | None = None
    source_filename: str | None = None
    source_section: str | None = None
    page_number: int | None = None
    source_excerpt: str | None = None
    source_view_url: str | None = None
    source_page_url: str | None = None
    source_label: str | None = None
    title: str | None = None
    path: str | None = None
    pdf_available: bool | None = None
    citation_note: str | None = None
    # Level-3 ready (optional / usually null for Level 2)
    bbox: list[float] | None = None
    page_width: float | None = None
    page_height: float | None = None
    text_position: dict[str, Any] | None = None


class QARetrievedChunkSchema(BaseModel):
    rank: int
    title: str
    path: str
    page: int | None = None
    content_preview: str
    original_score: float
    reranked_score: float
    boost_reasons: list[str] = Field(default_factory=list)
    selected_for_context: bool = False
    context_filter_reasons: list[str] = Field(default_factory=list)
    document_id: str
    source_filename: str
    chunk_index: int


class QAAskResponse(BaseModel):
    answer: str
    sources: list[QASourceSchema] = Field(default_factory=list)
    citations: list[QACitationSchema] = Field(default_factory=list)
    confidence: str = Field(..., pattern="^(high|medium|low)$")
    retrieved_chunks: list[QARetrievedChunkSchema] | None = None
    normalized_query: str | None = None
    expanded_query: str | None = None
    matched_expansion_rules: list[str] | None = None
    broad_query: bool | None = None
    broad_query_reason: str | None = None
    selected_context_count: int | None = None
    grouped_context_summary: list[dict] | None = None
    detected_intent: str | None = None
    collection_mode: bool | None = None
    collection_articles: list[str] | None = None
    collection_chunk_count: int | None = None
    group_count: int | None = None
    program_scope: dict | None = None
    query_expansions_used: list[str] | None = None
    rerank_reasons: list[dict] | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    out_of_scope_detected: bool | None = None
    ticket_routing: dict | None = None


class DocumentSourceMetaSchema(BaseModel):
    document_id: str
    original_filename: str
    stored_file_path: str | None = None
    document_type: str | None = None
    source_label: str | None = None
    version: str | None = None
    edition: str | None = None
    content_type: str | None = None
    byte_size: int | None = None
    page_count: int | None = None
    page_number: int | None = None
    page_width: float | None = None
    page_height: float | None = None
    uploaded_at: str | None = None
    source_view_url: str
    source_page_url: str | None = None
    open_fragment: str | None = None


# --- Smart ticketing ---


TicketStatus = Literal["Open", "In Progress", "Resolved", "Closed"]
TicketPriority = Literal["Urgent", "High", "Medium", "Low"]
TicketSenderRole = Literal["student", "office", "admin"]


class TicketTriageSchema(BaseModel):
    category: str
    assigned_office: str
    assigned_office_id: str | None = None
    priority: TicketPriority
    confidence: float
    method: str
    suggested_office_confirmed: bool = False


class OfficeSummarySchema(BaseModel):
    id: str
    name: str
    service_category: str | None = None


class OfficeListResponse(BaseModel):
    items: list[OfficeSummarySchema]
    total: int


class TicketAuditEventSchema(BaseModel):
    id: str
    ticket_id: str
    actor_id: str | None = None
    actor_role: str
    action: str
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    created_at: str


class NotificationSchema(BaseModel):
    id: str
    ticket_id: str | None = None
    type: str
    title: str
    body: str
    is_read: bool
    created_at: str


class NotificationListResponse(BaseModel):
    items: list[NotificationSchema]
    total: int
    unread_count: int


class TicketMessageSchema(BaseModel):
    id: str
    ticket_id: str
    sender_id: str
    sender_role: TicketSenderRole
    sender_name: str
    message: str
    created_at: str


class TicketCreatedBySchema(BaseModel):
    user_id: str
    full_name: str
    email: str | None = None


class TicketAttachmentSchema(BaseModel):
    id: str
    ticket_id: str
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_by_id: str
    created_at: str
    download_url: str


class TicketSchema(BaseModel):
    id: str
    ticket_id: str
    user_id: str
    user_name: str
    user_email: str | None = None
    original_question: str
    description: str
    category: str
    assigned_office_id: str | None = None
    assigned_office: str
    assigned_office_name: str
    priority: TicketPriority
    status: TicketStatus
    confidence_score: float | None = None
    source_from_chatbot: bool = False
    created_by: TicketCreatedBySchema
    created_at: str
    updated_at: str
    resolved_at: str | None = None
    closed_at: str | None = None
    latest_reply_preview: str | None = None
    replies_count: int = 0
    messages: list[TicketMessageSchema] = Field(default_factory=list)
    attachments: list[TicketAttachmentSchema] = Field(default_factory=list)


class CreateTicketRequest(BaseModel):
    original_question: str = Field(..., min_length=3, max_length=2000)
    description: str = Field("", max_length=4000)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    source_from_chatbot: bool = False
    preferred_office_id: str | None = Field(default=None, min_length=2, max_length=36)
    preferred_office: str | None = Field(default=None, min_length=2, max_length=120)
    preferred_priority: TicketPriority | None = None


class UpdateTicketRequest(BaseModel):
    status: TicketStatus | None = None
    assigned_office: str | None = Field(default=None, min_length=2, max_length=120)
    assigned_office_id: str | None = Field(default=None, min_length=2, max_length=36)
    category: str | None = Field(default=None, min_length=2, max_length=120)
    priority: TicketPriority | None = None


class AddTicketReplyRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class TicketListResponse(BaseModel):
    items: list[TicketSchema]
    total: int


class TicketStatisticsResponse(BaseModel):
    total: int
    open: int
    in_progress: int
    resolved: int
    closed: int
    by_office: dict[str, int] = Field(default_factory=dict)


# --- Authentication ---


UserRole = Literal["student", "office", "admin"]


class UserSchema(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    office_id: str | None = None
    office_name: str | None = None
    student_id: str | None = None
    created_at: str
    updated_at: str


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=256)
    full_name: str = Field(..., min_length=1, max_length=255)
    role: UserRole = "student"
    student_id: str | None = Field(default=None, max_length=80)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address.")
        return email

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("student_id")
    @classmethod
    def normalize_student_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        student_id = value.strip()
        return student_id or None


class CreateOfficeAccountRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=256)
    full_name: str = Field(..., min_length=1, max_length=255)
    office_id: str | None = Field(default=None, min_length=2, max_length=36)
    office_name: str | None = Field(default=None, min_length=2, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address.")
        return email

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return " ".join(value.split())


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserSchema


class UserListResponse(BaseModel):
    items: list[UserSchema]
    total: int


# --- Admin: PublishedArticle management ---


class AdminPublishedArticleCreate(BaseModel):
    title: str
    category: str
    document_type: str | None = None
    source_document: str | None = None
    source_section: str | None = None
    office: str | None = None
    summary: str | None = None
    content: str | None = None
    requirements: list[str] | None = None
    steps: list[str] | None = None
    options_or_services: list[str] | None = None
    related_articles: list[str] | None = None
    chunk_ids: list[str] | None = None
    publish_status: bool = False
    needs_review: bool = False
    planner_bucket: str | None = None
    category_confidence: float | None = None
    preview_file_path: str | None = None
    update_existing_id: str | None = None
    force_create: bool = False


class AdminPublishedArticleUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    document_type: str | None = None
    source_document: str | None = None
    source_section: str | None = None
    office: str | None = None
    summary: str | None = None
    content: str | None = None
    requirements: list[str] | None = None
    steps: list[str] | None = None
    options_or_services: list[str] | None = None
    related_articles: list[str] | None = None
    chunk_ids: list[str] | None = None
    publish_status: bool | None = None
    needs_review: bool | None = None
    category_confidence: float | None = None
    preview_file_path: str | None = None


class AdminPublishedArticleSchema(BaseModel):
    id: str
    title: str
    slug: str | None = None
    category: str
    subcategory: str | None = None
    path: str | None = None
    summary: str | None = None
    content: str | None = None
    office: str | None = None
    source_filename: str | None = None
    chunk_count: int | None = None
    published: bool
    published_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    persistence_table: str = "published_articles"
    persistence_debug: dict[str, Any] | None = None
    source_section: str | None = None
    article_type: str | None = None
    document_type: str | None = None


class AdminBulkArticleItem(BaseModel):
    """One candidate or saved article for bulk draft/publish."""

    preview_id: str | None = None
    existing_article_id: str | None = None
    title: str | None = None
    category: str | None = None
    document_type: str | None = None
    source_document: str | None = None
    source_section: str | None = None
    office: str | None = None
    summary: str | None = None
    content: str | None = None
    publish_status: bool = False
    needs_review: bool = False
    planner_bucket: str | None = None
    force_create: bool = False
    update_existing_id: str | None = None


class AdminBulkArticlesRequest(BaseModel):
    articles: list[AdminBulkArticleItem]


class AdminBulkArticleResultItem(BaseModel):
    preview_id: str | None = None
    success: bool
    id: str | None = None
    title: str | None = None
    published: bool | None = None
    error: str | None = None
    code: str | None = None
    existing: dict[str, Any] | None = None


class AdminBulkArticlesResponse(BaseModel):
    success_count: int
    failure_count: int
    results: list[AdminBulkArticleResultItem]


class AdminBulkIdsRequest(BaseModel):
    """Bulk action by existing published_articles ids."""

    article_ids: list[str]


class GenerateArticleCandidatesFromPreviewRequest(BaseModel):
    preview: dict[str, Any]
    filename: str | None = None
    max_candidates: int | None = None
    save_mode: str = "preview_only"
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


# --- Admin: knowledge base creation (OCR → ChromaDB) ---


class ExtractDocumentResponse(BaseModel):
    """Preview extraction only; does not update ChromaDB."""

    status: str = "success"
    flow: str = "admin_extraction"
    document_type: str
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
    knowledge_units: list[KnowledgeUnitSchema] = Field(default_factory=list)
    chunk_preview: list[ChunkPreviewSchema] = Field(default_factory=list)
    kb_statistics: KnowledgeBaseStatisticsSchema | None = None


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


# --- Smart ticketing ---


TicketStatus = Literal["Open", "In Progress", "Resolved", "Closed"]
TicketPriority = Literal["High", "Medium", "Low"]
TicketSenderRole = Literal["student", "office", "admin"]


class TicketTriageSchema(BaseModel):
    category: str
    assigned_office: str
    priority: TicketPriority
    confidence: float
    method: str


class TicketMessageSchema(BaseModel):
    id: str
    ticket_id: str
    sender_id: str
    sender_role: TicketSenderRole
    sender_name: str
    message: str
    created_at: str


class TicketSchema(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_email: str | None = None
    original_question: str
    description: str
    category: str
    assigned_office: str
    priority: TicketPriority
    status: TicketStatus
    confidence_score: float | None = None
    source_from_chatbot: bool = False
    created_at: str
    updated_at: str
    resolved_at: str | None = None
    closed_at: str | None = None
    messages: list[TicketMessageSchema] = Field(default_factory=list)


class CreateTicketRequest(BaseModel):
    original_question: str = Field(..., min_length=3, max_length=2000)
    description: str = Field("", max_length=4000)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    source_from_chatbot: bool = False


class UpdateTicketRequest(BaseModel):
    status: TicketStatus | None = None
    assigned_office: str | None = Field(default=None, min_length=2, max_length=120)
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

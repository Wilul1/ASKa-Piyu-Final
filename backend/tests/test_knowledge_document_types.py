from app.services.chroma_store import RetrievedChunk
from app.services.knowledge_document_types import (
    KnowledgeDocumentType,
    build_typed_chunks,
    detect_knowledge_document_type,
)
from app.services.qa.question_answering import _kb_document_type, _typed_answer_from_context
from pathlib import Path


def test_detects_requirement_from_generic_form_signals():
    detection = detect_knowledge_document_type(
        """
        User Access Application Form
        Requester Name: __________________
        Type of Request: [ ] New Account [ ] Reset Password [ ] Activate Account
        Signature: __________________
        """
    )

    assert detection.document_type == KnowledgeDocumentType.REQUIREMENT
    assert detection.manual_override is False


def test_detects_procedure_from_citizen_charter_signals():
    detection = detect_knowledge_document_type(
        """
        Office or Division: Guidance and Counseling
        Service: College Entrance Test
        Who May Avail: Student-applicants
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | RESPONSIBLE PERSON
        Submit application | Receive application | N/A | 15 minutes | Guidance Staff
        """
    )

    assert detection.document_type == KnowledgeDocumentType.PROCEDURE


def test_manual_document_type_overrides_auto_detection():
    detection = detect_knowledge_document_type(
        "Application Form Requester Name Signature",
        manual_document_type="information",
    )

    assert detection.document_type == KnowledgeDocumentType.INFORMATION
    assert detection.manual_override is True


def test_requirement_chunks_use_extracted_metadata_without_sample_name_rules():
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.REQUIREMENT,
        extraction=object(),
        index_text="""
        Network Access Request Form
        Office: ICT Office
        Name: __________________
        Type of Request: [ ] Create Access [ ] Reset Access
        Signature: __________________
        """,
        title="uploaded.pdf",
        source_document="uploaded.pdf",
        preview_file_path="previews/uploaded.png",
    )

    metadata = chunks[0].metadata or {}
    assert metadata["document_type"] == "requirement"
    assert "Network Access Request Form" in metadata["title"]
    assert "previews/uploaded.png" == metadata["preview_file_path"]
    assert "Reset Access" in chunks[0].text


def test_requirement_chunk_related_services_come_only_from_options():
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.REQUIREMENT,
        extraction=object(),
        index_text="""
        Document Request Form
        Name: __________________
        Contact Number: ________
        Type of Request: [ ] Certification [ ] Transcript
        """,
        title="request.pdf",
        source_document="request.pdf",
    )

    metadata = chunks[0].metadata or {}

    assert metadata["document_type"] == "requirement"
    assert metadata["extracted_requirements"] == '["Name", "Contact Number", "Type of Request"]'
    assert metadata["related_services"] == '["Certification", "Transcript"]'


def test_requirement_chunk_has_no_related_services_without_options():
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.REQUIREMENT,
        extraction=object(),
        index_text="""
        Clearance Request Form
        Name: __________________
        Date: __________________
        """,
        title="clearance.pdf",
        source_document="clearance.pdf",
    )

    metadata = chunks[0].metadata or {}

    assert metadata["related_services"] == "[]"


def test_requirement_chunk_excludes_raw_extraction_from_searchable_text_and_metadata():
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.REQUIREMENT,
        extraction=object(),
        index_text="""
        Document Type:
          Requirement / Form Document

        Basic Information:
          - Form Title: Student Records Request Form
          - Office: Registrar
          - Office Detection Source: extracted_from_document
          - Form Code: LSPU-REG-SF-100
          - Revision: REV. 0
          - Date: August 2016
        Fields / Required Information:
          - Name
          - Contact Number
        Options / Services:
          - Transcript
        Generated Requirements:
          - Name
          - Contact Number
        How to Fill Out:
          - Fill in the required requester information.
          - Select the applicable service option if available.
          - Submit the completed form to the indicated office.
        Related Services:
          - Transcript
        Raw Extraction:
        NOISY_OCR_SHOULD_NOT_BE_INDEXED
        Name | Contact number
        """,
        title="records.pdf",
        source_document="records.pdf",
        preview_file_path="previews/records.png",
    )

    chunk = chunks[0]
    metadata = chunk.metadata or {}
    metadata_blob = " ".join(str(value) for value in metadata.values())

    assert "NOISY_OCR_SHOULD_NOT_BE_INDEXED" not in chunk.text
    assert "Raw Extraction" not in chunk.text
    assert "NOISY_OCR_SHOULD_NOT_BE_INDEXED" not in metadata_blob
    assert metadata["raw_extraction_available"] is True
    assert metadata["source_document"] == "records.pdf"
    assert metadata["preview_file_path"] == "previews/records.png"


def test_requirement_chunk_indexes_clean_structured_requirement_fields():
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.REQUIREMENT,
        extraction=object(),
        index_text="""
        Document Type:
          Requirement / Form Document
        Basic Information:
          - Form Title: Student Records Request Form
          - Office: Registrar
          - Form Code: LSPU-REG-SF-100
          - Revision: REV. 0
          - Date: August 2016
        Generated Requirements:
          - Name
          - Contact Number
        Options / Services:
          - Transcript
        How to Fill Out:
          - Fill in the required requester information.
        Related Services:
          - Transcript
        """,
        title="records.pdf",
        source_document="records.pdf",
        preview_file_path="previews/records.png",
    )

    text = chunks[0].text
    metadata = chunks[0].metadata or {}

    assert "Document Type: Requirement / Form Document" in text
    assert "Requirement Title: Student Records Request Form" in text
    assert "Form Code: LSPU-REG-SF-100" in text
    assert "- Name" in text
    assert "- Contact Number" in text
    assert "- Transcript" in text
    assert metadata["form_title"] == "Student Records Request Form"
    assert metadata["form_code"] == "LSPU-REG-SF-100"
    assert metadata["raw_extraction_available"] is False


def test_how_to_fill_out_metadata_uses_generic_instructions_only():
    chunks = build_typed_chunks(
        kb_document_type=KnowledgeDocumentType.REQUIREMENT,
        extraction=object(),
        index_text="""
        Assistance Request Form
        Name: __________________
        Description: ___________
        Signature: _____________
        Services Requested: [ ] Advising
        """,
        title="assistance.pdf",
        source_document="assistance.pdf",
    )

    metadata = chunks[0].metadata or {}

    assert metadata["how_to_fill_out"] == (
        '["Fill in the required requester information.", '
        '"Select the applicable service option if available.", '
        '"Provide a description if the form includes a description field.", '
        '"Sign the form if a signature field is present.", '
        '"Submit the completed form to the indicated office."]'
    )
    assert "Advising" not in metadata["how_to_fill_out"]


def test_no_hardcoded_ict_service_options_in_runtime_code():
    runtime_files = [
        path
        for path in (Path(__file__).parents[1] / "app").rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    for forbidden in (
        "Network Assistance",
        "Software Installation",
        "Reset Password",
        "Activate Account",
        "Deactivate Account",
        "Video Coverage",
    ):
        assert forbidden not in runtime_text


def test_procedure_answer_uses_structured_metadata():
    chunk = RetrievedChunk(
        document_id="doc-1",
        title="Entrance Test",
        source_filename="procedure.pdf",
        chunk_index=0,
        text="Procedure Title: Entrance Test",
        relevance_score=0.9,
        metadata={
            "document_type": "procedure",
            "procedure_title": "Entrance Test",
            "office": "Guidance Office",
            "extracted_requirements": '["Application form"]',
            "extracted_steps": '[{"client_step":"Submit application","processing_time":"15 minutes"}]',
            "total_processing_time": "15 minutes",
            "source_document": "procedure.pdf",
        },
    )

    answer = _typed_answer_from_context(
        [chunk],
        [{"title": "Entrance Test", "path": "Procedure", "page": 2}],
        question="How do I take the entrance test?",
    )

    assert "Steps:" in answer
    assert "Submit application" in answer
    assert "Guidance Office" in answer
    assert "Source:" in answer
    assert "Form Preview" not in answer
    assert "Summary:" not in answer


def test_requirement_answer_includes_preview_and_related_services():
    chunk = RetrievedChunk(
        document_id="doc-1",
        title="Access Form",
        source_filename="form.pdf",
        chunk_index=0,
        text="Requirement Title: Access Form",
        relevance_score=0.9,
        metadata={
            "document_type": "requirement",
            "title": "Access Form",
            "summary": "Use Access Form for account requests.",
            "extracted_requirements": '["Name", "Username"]',
            "form_options": '{"type_of_request":["Reset Password"]}',
            "related_services": '["Reset Password"]',
            "how_to_fill_out": '["Fill in the required requester information."]',
            "preview_file_path": "previews/form.png",
        },
    )

    answer = _typed_answer_from_context(
        [chunk],
        [{"title": "Access Form", "path": "Requirement"}],
        question="How do I fill out the access form?",
    )

    assert "Form Preview:" in answer
    assert "previews/form.png" in answer
    assert "Reset Password" in answer


def test_service_query_does_not_use_requirement_form_dump():
    requirement = RetrievedChunk(
        document_id="form-1",
        title="Requirement: Clearance, Request Form Accounting",
        source_filename="form.pdf",
        chunk_index=0,
        text="Form Preview: previews/form.png\nRelated Services: Accounting",
        relevance_score=0.95,
        metadata={
            "document_type": "requirement",
            "article_type": "requirement_form",
            "title": "Requirement: Clearance, Request Form Accounting",
            "extracted_requirements": '["Clearance"]',
            "related_services": '["Accounting"]',
            "preview_file_path": "previews/form.png",
        },
    )
    charter = RetrievedChunk(
        document_id="charter-1",
        title="ID Validation",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=1,
        text=(
            "Overview\nThis service provides assistance for ID Validation.\n\n"
            "Office / Division\nOffice of the Student Affairs and Services\n\n"
            "Requirements\n"
            "- Requirement: Certificate of Registration\n"
            "  Where to Secure: Registrar's Office\n"
            "- Requirement: Student ID\n"
            "  Where to Secure: Business Affairs Office\n\n"
            "Steps\n"
            "1. Client Step: Present the Certificate of Registration.\n"
            "   Agency Action: Check Certificate of Registration.\n"
            "   Fees: None\n"
            "   Processing Time: 1 minute\n\n"
            "2. Client Step: Evaluate the services rendered by OSAS.\n"
            "   Agency Action: Issue Evaluation Form.\n"
            "   Fees: None\n"
            "   Processing Time: 2 minutes\n\n"
            "3. Client Step: Accept the validated ID.\n"
            "   Agency Action: Release validated ID.\n"
            "   Fees: None\n"
            "   Processing Time: 1 minute\n\n"
            "Fees\nNone\n\n"
            "Total Processing Time\n4 minutes\n\n"
            "Source Information\n"
            "Document: Citizen's Charter 2026\n"
            "Service: ID Validation\n"
            "Office: Office of the Student Affairs and Services\n"
            "Page: 18"
        ),
        relevance_score=0.8,
        metadata={
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": "ID Validation",
            "source_section": "ID Validation",
            "office": "Office of the Student Affairs and Services",
            "source_label": "Citizen’s Charter 2026",
            "page_number": 18,
        },
    )

    answer = _typed_answer_from_context(
        [requirement, charter],
        [{"title": "ID Validation", "source_section": "ID Validation", "page": 18}],
        question="How do I validate my ID?",
    )
    assert answer is not None
    assert "Certificate of Registration" in answer
    assert "Student ID" in answer
    assert "Office of the Student Affairs and Services" in answer
    assert "4 minutes" in answer
    assert "Fee: None" in answer
    assert "Form Preview" not in answer
    assert "Requirement: Clearance" not in answer
    assert "Related Services" not in answer


def test_procedure_answer_accepts_source_label_fallback_when_sources_empty():
    """Regression: duplicate _source_label overwrote fallback= support and crashed QA."""
    from app.services.qa.question_answering import _source_label

    assert _source_label([], fallback="Citizens_Charter.pdf") == "Citizens_Charter.pdf"
    assert _source_label([], fallback=None) == "Source document"
    assert _source_label([], fallback="") == "Source document"

    chunk = RetrievedChunk(
        document_id="charter-1",
        title="ID Validation",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=0,
        text="1. Present school ID\n2. Wait for validation stamp",
        relevance_score=0.95,
        metadata={
            "document_type": "procedure",
            "procedure_title": "ID Validation",
            "office": "Office of the Student Affairs and Services",
            "source_document": "Citizens_Charter_2026.pdf",
            "extracted_steps": '[{"client_step":"Present school ID"}]',
        },
    )
    answer = _typed_answer_from_context([chunk], [])
    assert answer is not None
    assert "ID Validation" in answer
    assert "Source:" in answer
    assert "Present school ID" in answer
    assert "Office of the Student Affairs and Services" in answer


def test_requirement_answer_does_not_show_raw_extraction_metadata():
    chunk = RetrievedChunk(
        document_id="doc-1",
        title="Access Form",
        source_filename="form.pdf",
        chunk_index=0,
        text="Requirement Title: Access Form\nSource: form.pdf",
        relevance_score=0.9,
        metadata={
            "document_type": "requirement",
            "title": "Access Form",
            "summary": "Use Access Form for account requests.",
            "extracted_requirements": '["Name"]',
            "related_services": "[]",
            "how_to_fill_out": '["Fill in the required requester information."]',
            "preview_file_path": "previews/form.png",
            "raw_extraction_available": True,
        },
    )

    answer = _typed_answer_from_context(
        [chunk],
        [{"title": "Access Form", "path": "Requirement"}],
        question="How do I fill out the access form?",
    )

    assert "Raw Extraction" not in answer
    assert "raw_extraction_available" not in answer


def test_missing_document_type_defaults_to_information():
    assert _kb_document_type({}) == "information"

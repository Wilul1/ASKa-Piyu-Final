from app.services.dynamic_document_analyzer import analyze_document_structure, format_dynamic_document


def test_detects_handbook_policy_hierarchy():
    text = """
    Student Handbook
    Chapter 1 General Policies
    Section 1.1 Admission
    Students must comply with university rules.
    """

    doc = analyze_document_structure(text)

    assert doc.document_kind == "handbook_policy"
    assert doc.sections
    assert doc.sections[0].level.lower().startswith("chapter")


def test_detects_memo_metadata_from_document_values():
    text = """
    Memorandum
    Date: June 10, 2026
    To: Campus Directors
    From: Office of Student Affairs
    Subject: Enrollment Schedule
    """

    doc = analyze_document_structure(text)

    assert doc.document_kind == "memo"
    assert doc.metadata["Date"] == "June 10, 2026"
    assert doc.metadata["Recipient"] == "Campus Directors"
    assert doc.metadata["Sender"] == "Office of Student Affairs"


def test_detects_form_tables_without_fixed_values():
    text = """
    Request Form
    Name | Student Number | Date
    Ana Reyes | 2024-0001 | June 10, 2026
    """

    doc = analyze_document_structure(text)

    assert doc.document_kind == "form"
    assert doc.tables[0].headers == ["Name", "Student Number", "Date"]
    assert doc.tables[0].rows[0][0] == "Ana Reyes"


def test_format_falls_back_when_structure_uncertain():
    text = "random OCR text without useful structure"
    doc = analyze_document_structure(text)

    assert format_dynamic_document(doc, text) == text

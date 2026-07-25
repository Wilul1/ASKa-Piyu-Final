from app.services.text_cleaner import (
    clean_extracted_text,
    clean_rag_extraction_text,
    split_into_chunks,
)


def test_removes_extra_spaces():
    raw = "Hello   world\n\nTest   line"
    assert "Hello world" in clean_extracted_text(raw)


def test_fixes_hyphenated_line_breaks():
    raw = "Institu-\ntional policy"
    assert "Institutional policy" in clean_extracted_text(raw)


def test_repairs_high_confidence_ocr_word_splits():
    raw = (
        "The ap plicant submitted com pleted requirements after psy chological readi ness screening. "
        "The Uni versity has lim ited slots follow ing the firsttime orientation at the cam pus."
    )
    cleaned = clean_extracted_text(raw)
    assert "applicant" in cleaned
    assert "completed" in cleaned
    assert "psychological readiness" in cleaned
    assert "University" in cleaned
    assert "limited" in cleaned
    assert "following" in cleaned
    assert "first time" in cleaned
    assert "firsttime" not in cleaned
    assert "campus" in cleaned


def test_strips_repeated_headers():
    pages = [
        "UNIVERSITY HEADER\nBody one\nFooter 1",
        "UNIVERSITY HEADER\nBody two\nFooter 1",
        "UNIVERSITY HEADER\nBody three\nFooter 1",
    ]
    raw = "\n\n".join(pages)
    cleaned = clean_extracted_text(raw, page_texts=pages)
    assert "UNIVERSITY HEADER" not in cleaned
    assert "Body one" in cleaned


def test_preserves_section_titles():
    raw = "SECTION I\n\nGeneral provisions apply."
    cleaned = clean_extracted_text(raw)
    assert "SECTION I" in cleaned


def test_split_into_chunks():
    text = "Para one.\n\nPara two.\n\nPara three."
    chunks = split_into_chunks(text, max_chars=30, overlap=5)
    assert len(chunks) >= 2
    assert all("text" in c for c in chunks)


def test_normalizes_university_form_ocr_headers():
    raw = """
    Office Division Guidance and Counseling
    Classification: | Simple
    Type | G2C
    Transaction
    Who CHECKUISTOE REQUIRET Wel | Student-applicants I7o | UNERE To SECURE
    EcKLESL OF REQUIREMENS | WHERE TO SECURE
    """

    cleaned = clean_extracted_text(raw)

    assert "Office or Division: Guidance and Counseling" in cleaned
    assert "Classification: Simple" in cleaned
    assert "Transaction Type: G2C" in cleaned
    assert "Who May Avail:" in cleaned
    assert "Checklist of Requirements" in cleaned
    assert "Where to Secure" in cleaned


def test_normalizes_obvious_icts_form_ocr_noise():
    raw = """
    Republic of the Philippincs
    Laguna #tatc Polptcchnic Univcrsity
    ICTSERVICES
    College of Computer Studies and Tochnoloay
    Form Code: LSPU ICTS 5F-0O2
    Alternate: SF-OO1
    """

    cleaned = clean_extracted_text(raw)

    assert "Philippines" in cleaned
    assert "State Polytechnic University" in cleaned
    assert "ICTSERVICES" in cleaned
    assert "Technology" in cleaned
    assert "LSPU-ICTS-SF-002" in cleaned
    assert "SF-001" in cleaned


def test_rag_cleaner_repairs_inline_hyphen_breaks():
    raw = (
        "document appertain- ing to the FACULTY of the LAGUNA STATE POLYTECH- NIC "
        "UNIVERSITY with added func- tions after re- accreditation."
    )
    cleaned = clean_rag_extraction_text(raw)
    assert "appertaining" in cleaned
    assert "POLYTECHNIC" in cleaned
    assert "functions" in cleaned
    assert "reaccreditation" in cleaned
    assert "appertain- ing" not in cleaned


def test_rag_cleaner_removes_toc_and_page_artifacts():
    raw = """
Foreword

Participation in Faculty Meetings ... V. The Conduct of Performance Appraisal VIII. Program on Awards

---

Page: 3

Part 2

I. General Information

Body under general information.

BOARD OF Regents

HON. LILIAN A. DE LAS LLAGAS CHED Commissioner HON. MARIO R. BRIONES LSPU President MRS. MARICEL S. CRUCILLO Board Secretary V
"""
    cleaned = clean_rag_extraction_text(raw)
    assert "Participation in Faculty Meetings" not in cleaned
    assert "---" not in cleaned
    assert "Page: 3" not in cleaned
    assert "Part 2" not in cleaned
    assert "I. General Information" in cleaned
    assert "Body under general information." in cleaned
    assert "LILIAN A. DE LAS LLAGAS" in cleaned
    assert "MARIO R. BRIONES" in cleaned


def test_rag_cleaner_removes_duplicate_labels_and_fragment_headings():
    raw = """
II. Historical Development of LSPU - Part 1

II. Historical Development of LSPU > II. Historical Development of LSPU

Historical body text remains.

III. Commitment of the Faculty

II. Historical Development of LSPU - Part 2

II. Historical Development of LSPU > II. Historical Development of LSPU

1. Teaching is a personal commitment of oneself to others.

This means, s/he shall:

Refrain From Making Derogatory Remarks About A Col

II. Historical Development of LSPU > 1.2.1 > Refrain From Making Derogatory Remarks About A Col

league or the school system in general;

Regular Faculty Designated as Vice President Campus Director

B. Faculty Attendance and Absences > 1.4 > Regular Faculty Designated as Vice President Campus Director

1.4. workload rules apply.
"""
    cleaned = clean_rag_extraction_text(raw)
    assert "Teaching is a personal commitment" in cleaned
    assert "colleague or the school system" in cleaned
    assert "1.2.1." in cleaned
    assert "Refrain From Making Derogatory Remarks About A Col" not in cleaned
    assert " > " not in cleaned
    assert cleaned.count("II. Historical Development of LSPU") == 1
    assert "1.4. Regular Faculty Designated as Vice President Campus Director" in cleaned
    assert cleaned.count("Regular Faculty Designated as Vice President Campus Director") == 1
    assert "1.4. workload rules apply." in cleaned

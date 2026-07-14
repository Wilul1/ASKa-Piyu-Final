from app.services.text_cleaner import clean_extracted_text, split_into_chunks


def test_removes_extra_spaces():
    raw = "Hello   world\n\nTest   line"
    assert "Hello world" in clean_extracted_text(raw)


def test_fixes_hyphenated_line_breaks():
    raw = "Institu-\ntional policy"
    assert clean_extracted_text(raw) == "Institutional policy"


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

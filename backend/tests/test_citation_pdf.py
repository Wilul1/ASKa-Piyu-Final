"""Citation PDF page-range + section crop."""

from __future__ import annotations

import fitz

from app.services.citation_pdf import extract_citation_pages_pdf
from app.services.document_storage import source_page_url


def _make_charter_like_pdf(tmp_path):
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "4. ID Validation")
    page1.insert_text((72, 110), "Present Certificate of Registration for ID check.")
    page1.insert_text((72, 150), "Accept the validated ID.")
    page1.insert_text((72, 220), "5. Issuance of Good Moral Certificate (Undergraduate)")
    page1.insert_text((72, 260), "Office of the Student Affairs and Services")
    page1.insert_text((72, 300), "Who may avail: All")
    page1.insert_text((72, 340), "Step 1 Present the Certificate of Registration.")

    page2 = doc.new_page()
    page2.insert_text((72, 72), "Step 2 Payment of fees.")
    page2.insert_text((72, 110), "Step 3 Submit documents and release certificate.")
    page2.insert_text((72, 200), "6. Scholarship Application")
    page2.insert_text((72, 240), "This is a different service and must be cropped away.")

    path = tmp_path / "charter.pdf"
    doc.save(path)
    doc.close()
    return path


def _make_dropping_like_pdf(tmp_path):
    """Dropping ends mid-page; next service continues on soft-extended page 2."""
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "7. Adding of Subjects")
    page1.insert_text((72, 110), "Prior service leftover text.")
    page1.insert_text((72, 180), "8. Dropping of Subjects")
    page1.insert_text((72, 220), "Fill out the dropping form.")
    page1.insert_text((72, 260), "TOTAL FEES")
    page1.insert_text((72, 290), "P30.00 / unit")
    page1.insert_text((72, 360), "9. Enrollment Advising")
    page1.insert_text((72, 400), "Advising steps start here.")

    page2 = doc.new_page()
    page2.insert_text((72, 72), "9. Enrollment Advising")
    page2.insert_text((72, 120), "Continuation of advising — must not appear.")

    path = tmp_path / "dropping.pdf"
    doc.save(path)
    doc.close()
    return path


def test_extract_single_page_without_section(tmp_path):
    path = _make_charter_like_pdf(tmp_path)
    raw = extract_citation_pages_pdf(path, page_start=1)
    opened = fitz.open(stream=raw, filetype="pdf")
    try:
        assert opened.page_count == 1
        text = opened[0].get_text()
        assert "ID Validation" in text
        assert "Good Moral" in text
    finally:
        opened.close()


def test_extract_section_drops_previous_and_next_service(tmp_path):
    path = _make_charter_like_pdf(tmp_path)
    raw = extract_citation_pages_pdf(
        path,
        page_start=1,
        page_end=2,
        section_title="Issuance of Good Moral Certificate (Undergraduate)",
    )
    opened = fitz.open(stream=raw, filetype="pdf")
    try:
        assert opened.page_count == 2
        first = opened[0].get_text()
        second = opened[1].get_text()
        assert "Good Moral" in first
        assert "ID Validation" not in first
        assert "Accept the validated ID" not in first
        assert "Payment of fees" in second or "release certificate" in second.lower()
        assert "Scholarship Application" not in second
    finally:
        opened.close()


def test_extract_crops_next_service_on_first_page_and_omits_bleed_page(tmp_path):
    path = _make_dropping_like_pdf(tmp_path)
    raw = extract_citation_pages_pdf(
        path,
        page_start=1,
        page_end=2,
        section_title="Dropping of Subjects",
    )
    opened = fitz.open(stream=raw, filetype="pdf")
    try:
        assert opened.page_count == 1
        text = opened[0].get_text()
        assert "Dropping of Subjects" in text
        assert "TOTAL FEES" in text
        assert "Adding of Subjects" not in text
        assert "Enrollment Advising" not in text
    finally:
        opened.close()


def test_source_page_url_includes_end_and_section():
    url = source_page_url(
        "doc-1",
        27,
        page_end=28,
        section="Issuance of Good Moral Certificate (Undergraduate)",
    )
    assert url is not None
    assert url.startswith("/documents/doc-1/source/page/27?")
    assert "end=28" in url
    assert "section=" in url
    assert "Good" in url or "Moral" in url or "%20" in url

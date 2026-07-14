from app.services.article_text import (

    build_article_summary,

    clean_article_content_for_display,

)





def test_clean_article_content_fixes_ocr_hyphen_spacing():

    raw = "Students must follow the regula- tion on attendance.\n4.1 Late arrivals are recorded."

    cleaned = clean_article_content_for_display(raw)

    assert "regulation" in cleaned

    assert "regula- tion" not in cleaned

    assert "4.1 Late arrivals are recorded." in cleaned





def test_clean_article_content_fixes_line_break_hyphenation():

    raw = "The univer-\nsity policy applies to all students."

    cleaned = clean_article_content_for_display(raw)

    assert cleaned == "The university policy applies to all students."





def test_build_article_summary_is_shorter_than_content():

    content = (

        "Students must submit complete admission documents before the deadline. "

        "Late submissions may not be processed. Contact the registrar for assistance."

    )

    summary = build_article_summary(content)

    assert summary

    assert len(summary) < len(content)

    assert summary.count(".") <= 2





def test_build_article_summary_does_not_duplicate_content():

    content = (

        "Students must submit complete admission documents before the deadline. "

        "Late submissions may not be processed."

    )

    summary = build_article_summary(content, existing_summary=content)

    assert summary != content

    assert len(summary) < len(content)





def test_build_article_summary_strips_numbered_policy_prefix():

    content = (

        "4.1 Retention standards apply to all enrolled students. "

        "4.2 Probationary status requires academic counseling."

    )

    summary = build_article_summary(content, title="Retention Standards")

    assert summary

    assert not summary.startswith("4.1")

    assert "4.1" not in summary

    assert "Retention Standards" in summary





def test_build_article_summary_keeps_distinct_existing_summary():

    content = "Step one: gather documents. Step two: submit online."

    summary = build_article_summary(content, existing_summary="Quick overview of admission steps.")

    assert summary == "Quick overview of admission steps."





def test_build_article_summary_counseling_process_is_student_friendly():

    title = "Counseling Process"

    content = (

        "This phase focuses on the counseling process per se. "

        "The process does not differ from a face-to-face counseling session. "

        "Virtual counseling sessions use video conference technology. "

        "Students may receive follow-up after consultation. "

        "Referral to other offices may be recommended when needed."

    )

    summary = build_article_summary(content, title=title, document_type="procedure")

    opening = "This phase focuses on the counseling process per se."



    assert summary

    assert opening not in summary

    assert "per se" not in summary.lower()

    assert summary.count(".") <= 2

    assert len(summary) < len(content)

    assert "Counseling Process" in summary

    assert "follow-up" in summary.lower()

    assert "referral" in summary.lower()

    assert "virtual counseling" in summary.lower() or "face-to-face counseling" in summary.lower()





def test_build_article_summary_includes_key_concepts_from_content():

    content = (

        "Applicants must complete the admission form and submit required documents. "

        "Deadlines apply for eligibility review and document submission."

    )

    summary = build_article_summary(

        content,

        title="Admission Form",

        document_type="requirement",

    )

    assert summary

    lowered = summary.lower()

    assert "admission form" in lowered

    assert any(term in lowered for term in ("requirements", "documents", "deadlines"))


def test_build_article_summary_services_title_uses_grammatical_wording():
    title = "Guidance and Counseling Services"
    content = (
        "Guidance and counseling services include individual and group counseling. "
        "Case conference may be done when needed. "
        "Students may be refer if necessary to counseling professors. "
        "Follow-up counselee with cases is part of the service."
    )
    summary = build_article_summary(content, title=title, document_type="procedure")
    lowered = summary.lower()

    assert "services works" not in lowered
    assert "follow-up counselee with cases" not in lowered
    assert "case conference may" not in lowered
    assert "refer if necessary" not in lowered
    assert "support provided" in lowered or "services" in lowered
    assert "case conferences" in lowered
    assert summary.count(".") <= 2


def test_build_article_summary_multidisciplinary_referral_note_is_natural():
    title = "Guidance and Counseling Services"
    content = (
        "Guidance and counseling services include individual and group counseling. "
        "Case conference may be done when needed. "
        "Follow-up counselee with cases and refer if necessary to multidisciplinary team "
        "of specialists to ensure that special needs of students are met."
    )
    summary = build_article_summary(content, title=title, document_type="procedure")
    lowered = summary.lower()

    assert "referrals when needed to multidisciplinary team" not in lowered
    assert "a multidisciplinary team" in lowered
    assert "students may be referred" in lowered or "referrals to a multidisciplinary team" in lowered
    assert summary.count(".") <= 2
    assert len(summary) < len(content)


def test_build_article_summary_avoids_covered_in_source_document_fallback():
    content = "General information about campus services and student support resources."
    summary = build_article_summary(
        content,
        title="Student Services",
        document_type="information",
    )
    assert "covered in the source document" not in summary.lower()
    assert "Student Services" in summary



def test_build_article_summary_consolidated_parent_uses_overview_fallback():
    content = "Funding details. Counseling notes. Thesis steps. Scholarship forms. " * 20
    summary = build_article_summary(
        content,
        title="Graduate Studies",
        document_type="information",
        consolidated_parent=True,
    )
    assert summary.startswith("This article provides an overview of Graduate Studies")
    assert "based on the uploaded source document" in summary


def test_grading_policy_summary_rejects_counseling_contamination():
    content = (
        "Students who fail retention standards shall follow modified grading rules and grade computation. "
        "The policy defines conditions for academic standing and grade adjustments."
    ) * 4
    summary = build_article_summary(
        content,
        title="Modified Grading Policy",
        document_type="policy",
        article_type="policy",
    )
    lowered = summary.lower()
    assert "counseling" not in lowered
    assert "face-to-face" not in lowered
    assert "referral" not in lowered
    assert "modified grading policy" in lowered


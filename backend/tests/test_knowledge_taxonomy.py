import pytest

from app.services.knowledge_taxonomy import (
    classify_chunk,
    classify_question,
    knowledge_base_taxonomy,
    load_taxonomy,
)


@pytest.mark.parametrize(
    ("title", "text", "metadata", "expected_category"),
    [
        (
            "Admission Requirements",
            "Applicants must submit all admission requirements before enrollment.",
            {"chapter": "Chapter 3 > Admission", "source_filename": "student-handbook.pdf"},
            "Admissions",
        ),
        (
            "Transferee Student",
            "A transferee student must present transfer credentials and meet admission rules.",
            {"article": "Classification of Students Based on Admission"},
            "Admissions",
        ),
        (
            "Attendance",
            "Attendance rules cover absences, tardiness, and excuse slips.",
            {"chapter": "Undergraduate Academic Policies"},
            "Academic Policies",
        ),
        (
            "Scholastic Delinquency",
            "Students under scholastic delinquency are subject to retention policies.",
            {"article": "Article 1 > Retention"},
            "Academic Policies",
        ),
        (
            "Transcript of Records",
            "Students may request an official transcript of records from the Registrar.",
            {"office": "Registrar"},
            "Student Records",
        ),
        (
            "Scholarship",
            "Scholarship grants and financial assistance are available to qualified students.",
            {"office": "Scholarship Office"},
            "Scholarships & Financial Policies",
        ),
        (
            "Curricular Offerings",
            "The College of Computer Studies offers BS Computer Science and BS Information Technology programs.",
            {"chapter": "Chapter 3 > Curricular Offerings"},
            "Programs & Curricular Offerings",
        ),
        (
            "Guidance and Counseling",
            "Guidance and counseling services support student welfare and mental health.",
            {"office": "Guidance Office"},
            "Student Services",
        ),
        (
            "Administrative Officials",
            "The handbook lists administrative officials and members of the Board of Regents.",
            {"section": "Administrative Officials"},
            "Administrative Information",
        ),
        (
            "Student Portal / LMS",
            "Students who cannot login to the student portal or LMS may request account recovery.",
            {"office": "ICT Office"},
            "Technical Support",
        ),
        (
            "Clearance and Certificate Requests",
            "Use the clearance form for clearance and certificate requests.",
            {"path": "Requirements and Forms > Clearance"},
            "Requirements & Forms",
        ),
    ],
)
def test_classifies_handbook_chunks_into_student_friendly_categories(
    title,
    text,
    metadata,
    expected_category,
):
    result = classify_chunk(text, title=title, metadata=metadata)

    assert result.category == expected_category
    assert result.subcategory != "General"


def test_taxonomy_exposes_student_friendly_categories_without_academic_services():
    names = [category["name"] for category in knowledge_base_taxonomy()]

    assert names == [
        "Admissions",
        "Academic Policies",
        "Student Records",
        "Scholarships & Financial Policies",
        "Graduate Studies",
        "Student Services",
        "Programs & Curricular Offerings",
        "Administrative Information",
        "Technical Support",
        "Requirements & Forms",
    ]
    assert "Academic Services" not in names


def test_cashier_payment_methods_not_routed_to_cas_via_cas_substring():
    """Regression: keyword 'cas' must not match inside 'cashier'."""
    load_taxonomy.cache_clear()
    result = classify_question(
        "What payment methods does the Cashier Unit accept? "
        "Good day. I would like to know which payment methods are accepted "
        "at the Cashier Unit. Thank you."
    )
    assert result.office == "Cashier"
    assert "Arts and Sciences" not in result.office
    assert result.category == "Scholarships & Financial Policies"
    assert result.subcategory == "Tuition Policies"


def test_cas_acronym_still_routes_to_college_of_arts_and_sciences():
    """Whole-word 'CAS' should still identify College of Arts and Sciences."""
    load_taxonomy.cache_clear()
    result = classify_question(
        "What undergraduate programs does CAS offer under the College of Arts and Sciences?"
    )
    assert result.office == "College of Arts and Sciences"
    assert result.category == "Programs & Curricular Offerings"


def test_generic_request_words_are_not_confident_registrar_hits():
    load_taxonomy.cache_clear()
    result = classify_question("Please help with my request")
    assert result.confidence < 0.45 or result.office != "Registrar"


def test_certificate_of_enrollment_classifies_to_registrar():
    load_taxonomy.cache_clear()
    result = classify_question(
        "I need a Certificate of Enrollment from the Registrar for scholarship."
    )
    assert result.office == "Registrar"
    assert result.confidence >= 0.45

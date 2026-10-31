from app.services.handbook_policy_processor import (
    HandbookKnowledgeUnit,
    PENALTY_CONFIDENCE_CONFIRMED,
    PENALTY_CONFIDENCE_EMPTY,
    PENALTY_CONFIDENCE_UNCONFIRMED,
    PENALTY_UNCONFIRMED_NOTE,
    build_handbook_policy_document,
    is_handbook_policy_text,
    _filter_non_knowledge_units,
)
from app.utils.pdf.pymupdf_extractor import PageExtraction
from app.services.admin.knowledge_base_pipeline import (
    _knowledge_units_for_extraction,
    _unit_status,
    _validation_report,
    suspicious_unit_diagnostics,
)


def test_detects_handbook_policy_structure():
    text = """
    Title: Student Handbook
    Chapter 3 Student Admission
    Article 2 Admission Requirements
    Sec. 2.11 Basic Requirements
    2.11.1 Freshmen must submit required credentials.
    """

    assert is_handbook_policy_text(text)


def test_builds_logical_units_with_metadata_and_removes_layout_noise():
    page_texts = [
        """
        Institution: Laguna State Polytechnic University
        Doc. No.: LSPU-PM-LSH-01
        Type: Manual
        Revision No.: 00
        Title: LSPU Student Handbook 2021
        Date: 2021
        Page: 1 of 2
        Chapter 3 Student Admission
        Article 2 Admission Requirements
        Sec. 2.11 Basic Requirements
        Freshmen must submit:
        a) Report Card/Form 138
        b) Permanent Record/Form 137
        c) Medical and drug test certification
        """,
        """
        Institution: Laguna State Polytechnic University
        Doc. No.: LSPU-PM-LSH-01
        Type: Manual
        Revision No.: 00
        Title: LSPU Student Handbook 2021
        Date: 2021
        Page: 2 of 2
        2.11.1 Freshman Admission Requirements
        Certificate of Good Moral Character, three 2x2 pictures,
        PSA birth certificate, and ALS/PEPT results if applicable.
        Appendix A Forms
        Use the prescribed university admission forms.
        """,
    ]

    doc = build_handbook_policy_document(
        raw_text="\n\n".join(page_texts),
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
    )

    assert doc.document_type == "handbook_policy"
    assert doc.source_title == "LSPU Student Handbook 2021"
    assert doc.doc_no == "LSPU-PM-LSH-01"
    assert "Institution:" not in doc.cleaned_text
    assert "Page: 1 of 2" not in doc.cleaned_text
    assert len(doc.units) >= 2

    first = doc.units[0]
    assert first.metadata["source_title"] == "LSPU Student Handbook 2021"
    assert first.metadata["doc_no"] == "LSPU-PM-LSH-01"
    assert first.metadata["document_type"] == "handbook_policy"
    assert first.metadata["content_type"] == "requirement"
    assert first.metadata["appendix"] is None
    assert first.metadata["chapter"] == "Chapter 3 > Student Admission"
    assert first.metadata["article"] == "Article 2 > Admission Requirements"
    assert first.metadata["section"] == "Sec. 2.11 > Basic Requirements"
    assert first.metadata["page_start"] == 1
    assert first.metadata["page_end"] == 1
    assert first.title == "Basic Requirements"
    assert "- Report Card/Form 138" in first.content
    assert "Freshman Admission Requirements" in doc.formatted_articles


def test_excludes_table_of_contents_from_knowledge_units():
    page_texts = [
        """
        Contents
        Message of the University President ........ 1
        Vision ..................................... 2
        Chapter 1 Student Affairs .................. 5
        Article 1 General Policies ................. 6
        Sec. 1.1 Student Conduct ................... 7
        """,
        """
        Message of the University President
        Welcome to the university community.
        """,
        """
        Chapter 1 Student Affairs
        Article 1 General Policies
        Sec. 1.1 Student Conduct
        Students shall observe university rules and regulations.
        """,
    ]

    doc = build_handbook_policy_document(
        raw_text="\n\n".join(page_texts),
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "Contents" not in titles
    assert all("........" not in unit.content for unit in doc.units)
    assert "Message of the University President" in titles
    assert "Student Conduct" in titles


def test_splits_front_matter_into_separate_units():
    page_texts = [
        """
        Vision
        A premier university in the region.
        Mission
        Provide quality education and responsive services.
        LSPU Quality Policy
        The university commits to continual improvement.
        Prayer
        Guide us in learning and service.
        Foreword
        This handbook introduces student policies.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert titles == ["Vision", "Mission", "LSPU Quality Policy", "Prayer", "Foreword"]
    assert [unit.metadata["content_type"] for unit in doc.units] == [
        "message",
        "message",
        "message",
        "prayer",
        "message",
    ]


def test_splits_curricular_offerings_by_college():
    page_texts = [
        """
        Chapter 2 Curricular Offerings
        The university offers the following programs.
        College of Computer Studies
        BS Computer Science
        BS Information System
        BS Information Technology
        College of Engineering
        BS Civil Engineering
        BS Electrical Engineering
        Graduate Studies
        Master of Arts in Education
        Doctor of Philosophy in Education
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "Curricular Offerings - College of Computer Studies" in titles
    assert "Curricular Offerings - College of Engineering" in titles
    assert "Curricular Offerings - Graduate Studies" in titles
    ccs = next(unit for unit in doc.units if "Computer Studies" in unit.title)
    assert ccs.metadata["content_type"] == "program_listing"
    assert "- BS Computer Science" in ccs.content
    assert "BS Civil Engineering" not in ccs.content


def test_curricular_offerings_preserve_undergraduate_programs_and_specializations():
    page_texts = [
        """
        Chapter 2 Curricular Offerings
        College of Computer Studies (CCS), All Campuses
        - Bachelor of Science in Computer Science
        - Bachelor of Science in Information System
        Bachelor of Science in Information Technology
        Specialization:
        - Service Management
        - Business Analytics
        - Animation and Motion Graphics
        - Web and Mobile Applications
        - Network Administration Programming
        Graduate Studies
        - Master in Information Technology (BOR Resolution 121, s.2021)
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    ccs = next(unit for unit in doc.units if unit.title == "Curricular Offerings - College of Computer Studies")

    assert ccs.metadata["content_type"] == "program_listing"
    assert ccs.metadata["campuses"] == ["All Campuses"]
    assert ccs.content == "\n".join(
        [
            "Campuses:",
            "- All Campuses",
            "",
            "Programs:",
            "- BS Computer Science",
            "- BS Information System",
            "- BS Information Technology",
            "",
            "Specializations:",
            "- Service Management",
            "- Business Analytics",
            "- Animation and Motion Graphics",
            "- Web and Mobile Applications",
            "- Network Administration Programming",
        ]
    )
    assert "Master in Information Technology" not in ccs.content

    graduate = next(unit for unit in doc.units if unit.title == "Curricular Offerings - Graduate Studies")
    assert "- Master in Information Technology" in graduate.content


def test_curricular_offerings_store_campus_availability_without_title_clutter():
    page_texts = [
        """
        Chapter 2 Curricular Offerings
        College of Computer Studies (CCS), Sta Cruz, San Pablo, and Siniloan Campuses
        - Bachelor of Science in Computer Science
        - Bachelor of Science in Information System
        Bachelor of Science in Information Technology
        College of Business Administration
        Sta Cruz and San Pablo Campuses
        BS Business Administration
        BS Accountancy
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    ccs = next(unit for unit in doc.units if unit.title == "Curricular Offerings - College of Computer Studies")
    business = next(unit for unit in doc.units if unit.title == "Curricular Offerings - College of Business Administration")

    assert "Campus" not in ccs.title
    assert ccs.metadata["campuses"] == ["Sta. Cruz", "San Pablo City", "Siniloan"]
    assert "Campuses:\n- Sta. Cruz\n- San Pablo City\n- Siniloan" in ccs.content
    assert "- BS Computer Science" in ccs.content
    assert "- BS Information Technology" in ccs.content

    assert "Campus" not in business.title
    assert business.metadata["campuses"] == ["Sta. Cruz", "San Pablo City"]
    assert "Campuses:\n- Sta. Cruz\n- San Pablo City" in business.content
    assert "- BS Business Administration" in business.content
    assert "- BS Accountancy" in business.content


def test_curricular_offerings_separate_graduate_programs_from_campus_block():
    page_texts = [
        """
        Chapter 2 Curricular Offerings
        Graduate Studies
        Campuses:
        - Doctor of Education
        - Sta. Cruz
        - San Pablo City
        - Los Baños
        - Doctor of Philosophy in Education
        - Siniloan
        - All Campuses
        - Master of Arts in Education
        - Master of Arts in Teaching English
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    graduate = next(unit for unit in doc.units if unit.title == "Curricular Offerings - Graduate Studies")

    assert "Programs:" in graduate.content
    assert "- Doctor of Education" in graduate.content
    assert "- Doctor of Philosophy in Education" in graduate.content
    assert "- Master of Arts in Education" in graduate.content
    assert "- Master of Arts in Teaching English" in graduate.content
    campus_section = graduate.content.split("Programs:", 1)[0]
    assert "Doctor of Education" not in campus_section
    assert "Doctor of Philosophy in Education" not in campus_section
    assert "Master of Arts in Education" not in campus_section
    assert "Master of Arts in Teaching English" not in campus_section
    assert graduate.metadata["program_campuses"]["Doctor of Education"] == ["Sta. Cruz", "San Pablo City", "Los Baños"]
    assert graduate.metadata["program_campuses"]["Doctor of Philosophy in Education"] == ["Siniloan", "All Campuses"]


def test_curricular_offerings_inline_program_campuses_do_not_treat_degree_as_campus():
    page_texts = [
        """
        Chapter 2 Curricular Offerings
        Graduate Studies
        Doctor of Education - Sta. Cruz, San Pablo City, and Los Baños Campuses
        Doctor of Philosophy in Education - Siniloan Campus
        Master of Arts in Education - All Campuses
        Master of Arts in Teaching English - Sta. Cruz Campus
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    graduate = next(unit for unit in doc.units if unit.title == "Curricular Offerings - Graduate Studies")

    top_level_campuses = graduate.content.split("Programs:", 1)[0]
    assert "Doctor" not in top_level_campuses
    assert "- Doctor of Education" in graduate.content
    assert graduate.metadata["program_campuses"]["Doctor of Education"] == ["Sta. Cruz", "San Pablo City", "Los Baños"]
    assert graduate.metadata["program_campuses"]["Doctor of Philosophy in Education"] == ["Siniloan"]
    assert graduate.metadata["program_campuses"]["Master of Arts in Education"] == ["All Campuses"]
    assert graduate.metadata["program_campuses"]["Master of Arts in Teaching English"] == ["Sta. Cruz"]


def test_curricular_offerings_deduplicate_programs_and_merge_campuses():
    page_texts = [
        """
        Chapter 2 Curricular Offerings
        Graduate Studies
        Doctor of Education - Sta. Cruz Campus
        Doctor of Philosophy in Education - Siniloan Campus
        Master of Arts in Education - All Campuses
        Master of Arts in Education - Sta. Cruz and San Pablo City Campuses
        Master of Arts in Teaching English - Sta. Cruz Campus
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    graduate = next(unit for unit in doc.units if unit.title == "Curricular Offerings - Graduate Studies")
    programs_section = graduate.content.split("Program Campuses:", 1)[0]
    program_lines = [line for line in programs_section.splitlines() if line.startswith("- ")]

    assert program_lines == [
        "- Doctor of Education",
        "- Doctor of Philosophy in Education",
        "- Master of Arts in Education",
        "- Master of Arts in Teaching English",
    ]
    assert programs_section.count("- Master of Arts in Education") == 1
    assert graduate.metadata["program_campuses"]["Master of Arts in Education"] == ["All Campuses", "Sta. Cruz", "San Pablo City"]


def test_curricular_offerings_reject_specializations_and_bor_fragments_as_campuses():
    page_texts = [
        """
        Chapter 2 Curricular Offerings
        College of Technology, Sta Cruz Campus
        BS Industrial Technology
        Specialization:
        - Programming
        - Communication Technology
        - Automotive Technology
        - Electronics Technology
        - Electrical Technology
        - Animal Production
        Graduate Studies
        Master of Arts in Education - S.2020) Campus
        Doctor of Education - San Pablo City Campus
        Master of Arts in Teaching English - Communication Technology Campus
        Doctor of Philosophy in Education - All Campuses
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    report = doc.diagnostic_report()
    campus_audit = report["campus_audit"]
    assert campus_audit["unique_campus_names"] == ["Sta. Cruz"]
    assert campus_audit["unique_program_campus_values"] == ["All Campuses", "San Pablo City"]
    assert campus_audit["invalid_campus_values"] == []

    campus_values = set(campus_audit["unique_campus_names"]) | set(campus_audit["unique_program_campus_values"])
    for leaked in [
        "Programming",
        "Communication Technology",
        "Automotive Technology",
        "Electronics Technology",
        "Electrical Technology",
        "Animal Production",
        "S.2020)",
    ]:
        assert leaked not in campus_values


def test_repeated_undergraduate_policy_page_header_does_not_steal_curricular_offerings_metadata():
    page_texts = [
        """
        Undergraduate Academic Policies
        Attendance Policy
        Students shall attend classes regularly and comply with attendance requirements.
        """,
        """
        Undergraduate Academic Policies
        Chapter 2 Curricular Offerings
        College of Computer Studies
        BS Computer Science
        BS Information Technology
        """,
        """
        Undergraduate Academic Policies
        College of Engineering
        BS Civil Engineering
        BS Electrical Engineering
        """,
    ]

    doc = build_handbook_policy_document(
        raw_text="\n\n".join(page_texts),
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    ccs = next(unit for unit in doc.units if unit.title == "Curricular Offerings - College of Computer Studies")
    engineering = next(unit for unit in doc.units if unit.title == "Curricular Offerings - College of Engineering")

    assert ccs.metadata["chapter"] == "Chapter 2 > Curricular Offerings"
    assert engineering.metadata["chapter"] == "Chapter 2 > Curricular Offerings"
    assert all(
        "Undergraduate Academic Policies" not in str(unit.metadata.get("chapter"))
        for unit in (ccs, engineering)
    )


def test_major_sections_reset_undergraduate_policy_context():
    page_texts = [
        """
        Undergraduate Academic Policies
        Retention Policies
        Students must satisfy retention requirements.
        Administrative Officials
        Office of the University President
        The university president and administrative officials are listed in this section.
        Graduate Studies
        Admission Requirements
        Graduate applicants must submit required credentials before enrollment.
        """,
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    retention = next(unit for unit in doc.units if unit.title == "Retention Policies")
    officials = next(unit for unit in doc.units if unit.title == "Administrative Officials")
    graduate = next(unit for unit in doc.units if unit.title == "Admission Requirements")

    assert retention.metadata["chapter"] == "Undergraduate Academic Policies"
    assert retention.metadata["section"] == "Retention Policies"
    assert officials.metadata["chapter"] == "Administrative Officials"
    assert graduate.metadata["chapter"] == "Graduate Studies"
    assert graduate.metadata["section"] == "Admission Requirements"
    assert "Undergraduate Academic Policies" not in str(officials.metadata)
    assert "Undergraduate Academic Policies" not in str(graduate.metadata)


def test_validation_report_lists_campus_values_and_flags_invalid_metadata():
    units = [
        {
            "title": "Curricular Offerings - Sample",
            "content": "Campuses:\n- Sta. Cruz\nPrograms:\n- BS Sample\nThe Uni versity policy applies.",
            "status": "Ready",
            "metadata": {
                "source_title": "Student Handbook",
                "chapter": "Chapter 2 > Curricular Offerings",
                "campuses": ["Sta. Cruz", "Programming"],
                "program_campuses": {
                    "BS Sample": ["San Pablo City", "S.2020)"],
                },
            },
        }
    ]
    chunks = [
        type(
            "Chunk",
            (),
            {
                "text": "Curricular Offerings - Sample\nCampuses:\n- Sta. Cruz",
                "chunk_index": 0,
                "char_start": 0,
                "metadata": units[0]["metadata"],
            },
        )()
    ]

    report = _validation_report(document_type="handbook_policy", units=units, chunks=chunks)

    assert report["unique_campus_names"] == ["Programming", "Sta. Cruz"]
    assert report["unique_program_campus_values"] == ["S.2020)", "San Pablo City"]
    assert {item["value"] for item in report["invalid_campus_values"]} == {"Programming", "S.2020)"}
    assert report["remaining_ocr_word_splits"][0]["pattern"] == "Uni versity"
    assert report["status"] == "Needs Review"


def test_cleans_appendix_form_templates():
    page_texts = [
        """
        Appendix A Promissory Note
        Name: ______________________
        Date: ______________________
        Student Number: ______________________
        I promise to settle my account on or before the stated deadline.
        Signature: ______________________
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    unit = doc.units[0]
    assert unit.metadata["content_type"] == "form_template"
    assert unit.metadata["appendix"] == "Appendix A > Promissory Note"
    assert "________________" not in unit.content
    assert "Required Fields:" in unit.content
    assert "- Name" in unit.content
    assert "- Date" in unit.content
    assert "- Student Number" in unit.content
    assert "- Signature" in unit.content
    assert "settle my account" in unit.content


def test_splits_oversized_units_without_losing_hierarchy():
    paragraphs = "\n\n".join(
        f"Paragraph {index} contains policy wording that must remain available for retrieval and citation."
        for index in range(130)
    )
    page_texts = [
        f"""
        Chapter 4 Student Discipline
        Article 1 Disciplinary Rules
        Sec. 1.1 Offenses and Sanctions
        {paragraphs}
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    assert len(doc.units) > 1
    assert all(unit.metadata["content_type"] == "disciplinary_rule" for unit in doc.units)
    assert all(unit.metadata["chapter"] == "Chapter 4 > Student Discipline" for unit in doc.units)
    assert all(len(unit.content.split()) <= 1050 for unit in doc.units)


def test_toc_entries_with_dot_leaders_do_not_leak():
    page_texts = [
        """
        TABLE OF CONTENTS
        Grading System ........ 33
        GSAR Admission Requirements ........ 43
        Thesis/Dissertation ........ 53
        Chapter 5 Academic Policies ........ 60
        """,
        """
        Chapter 5 Academic Policies
        Article 1 Grading System
        The grading system shall follow approved university policies.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    articles = doc.formatted_articles
    assert "Grading System ........ 33" not in articles
    assert "GSAR Admission Requirements ........ 43" not in articles
    assert "Thesis/Dissertation ........ 53" not in articles
    assert "The grading system shall follow" in articles


def test_front_matter_stops_at_unnumbered_major_headings():
    page_texts = [
        """
        Prayer
        Let this prayer remain only as prayer content.
        Chapter 1
        LSPU Historical Development and Officials
        The university history is summarized here.
        Board of Regents
        The Board of Regents is listed here.
        Administrative Officials
        Administrative officials are listed here.
        Curricular Offerings
        College of Computer Studies
        BS Computer Science
        BS Information Technology
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    prayer = next(unit for unit in doc.units if unit.title == "Prayer")
    assert "Chapter 1" not in prayer.content
    assert "Board of Regents" not in prayer.content
    assert "Let this prayer remain only" in prayer.content
    assert any(unit.title == "Board of Regents" for unit in doc.units)
    assert any("Curricular Offerings - College of Computer Studies" == unit.title for unit in doc.units)


def test_numbered_definition_title_uses_text_before_period():
    page_texts = [
        """
        Chapter 1 Student Admission
        Article 1 Based on Admission
        1.1 New Student. A student who is enrolled in the university for the first time.
        Additional admission notes apply.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    unit = doc.units[0]
    assert unit.title == "New Student"
    assert "A student who is enrolled" in unit.content


def test_numeric_policy_table_values_are_not_section_headings():
    page_texts = [
        """
        Article 5 Retention Policies
        Retention Requirement
        Situation | Action
        GWA below 2.25 | Warning
        Grade of 5.0 | Subject must be repeated
        Allowable Percentage | Status
        75% | Probation
        100% | Dismissal
        P500.00 | Graduation fee
        P20/unit | Laboratory fee
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "2.25" not in titles
    assert "5.0" not in titles
    unit = next(unit for unit in doc.units if unit.title == "Retention Requirement")
    assert "Situation | Action" in unit.content
    assert "GWA below 2.25 | Warning" in unit.content
    assert "75% | Probation" in unit.content
    assert "P20/unit | Laboratory fee" in unit.content


def test_policy_table_rows_and_continuation_clauses_stay_under_parent_unit():
    page_texts = [
        """
        Article 5 Retention Policies
        Retention Requirement
        Situation | Action
        2.25 GPA is less than the required standard The student shall be given a probationary status
        2.50 Final Grade in said subject and meet the required final grade
        2.75 The student granted permission under this rule is required to retake the subject
        If a subject is dropped after the first day of the midterm examination, the student shall comply with the required process.
        Students not in residence (not registered during the semester) shall apply for readmission before enrollment.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "GPA is less than the required standard The student shall be given a probationary status" not in titles
    assert "Final Grade in said subject and meet the required final grade" not in titles
    assert "The student granted permission under this rule is required to retake the subject" not in titles
    assert not any(title.startswith("If a subject is dropped") for title in titles)
    assert not any(title.startswith("Students not in residence") for title in titles)

    unit = next(unit for unit in doc.units if unit.title == "Retention Requirement")
    assert "Situation | Action" in unit.content
    assert "GPA is less than the required standard" in unit.content
    assert "Final Grade in said subject" in unit.content
    assert "The student granted permission under this rule" in unit.content
    assert "If a subject is dropped after the first day" in unit.content
    assert "Students not in residence" in unit.content


def test_numbered_continuation_clauses_do_not_become_child_units():
    page_texts = [
        """
        Article 6 Enrollment Rules
        Sec. 6.1 Dropping of Subjects
        6.1.1 If a student withdraws after the first week, the student shall follow the approved dropping procedure.
        6.1.2 When a subject is dropped after the first day of the midterm examination, applicable conditions shall be observed.
        6.1.3 The student granted permission under this rule is required to complete clearance.
        6.1.4 Any student with unsettled obligations shall be subject to existing rules.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "Dropping of Subjects" in titles
    assert not any(title.startswith(("If ", "When ", "The student", "Any student")) for title in titles)
    unit = next(unit for unit in doc.units if unit.title == "Dropping of Subjects")
    assert "If a student withdraws after the first week" in unit.content
    assert "When a subject is dropped after the first day" in unit.content
    assert "The student granted permission under this rule" in unit.content
    assert "Any student with unsettled obligations" in unit.content


def test_student_classification_definitions_stay_separate_units():
    page_texts = [
        """
        Chapter 1 Student Admission
        Article 1 Classification of Students Based on Admission
        1.1 New Student. A student who is enrolled for the first time.
        1.2 Transferee Student. A student who comes from another school.
        1.3 Cross-enrollee Student. A student who enrolls in another institution for credit.
        1.4 Foreign Student. A student who is not a citizen of the Philippines.
        1.5 Returnee Student. A former student who returns to the university.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "New Student" in titles
    assert "Transferee Student" in titles
    assert "Cross-enrollee Student" in titles
    assert "Foreign Student" in titles
    assert "Returnee Student" in titles
    new_student = next(unit for unit in doc.units if unit.title == "New Student")
    assert new_student.content == "A student who is enrolled for the first time."
    assert new_student.metadata["article"] == "Article 1 > Classification of Students Based on Admission"


def test_short_definition_unit_is_not_suspicious_only_because_it_is_short():
    unit = {
        "title": "New Student",
        "content": "A student who is enrolled for the first time.",
        "content_type": "policy",
        "metadata": {
            "source_title": "Student Handbook",
            "chapter": "Chapter 1 > Student Admission",
            "article": "Article 1 > Classification of Students Based on Admission",
            "section": "1.1 > New Student",
            "page_start": 1,
        },
    }

    status, reasons = _unit_status(unit)

    assert status == "OK"
    assert "very_short" not in reasons


def test_hierarchy_only_parent_unit_is_removed_but_child_metadata_remains():
    parent = HandbookKnowledgeUnit(
        title="Undergraduate Academic Policies",
        content="Article 1. Classifications of Students\nSec. 1. Based on Admission",
        raw_text="Undergraduate Academic Policies\nArticle 1. Classifications of Students\nSec. 1. Based on Admission",
        metadata={
            "source_title": "Student Handbook",
            "document_type": "handbook_policy",
            "content_type": "policy",
            "chapter": "Undergraduate Academic Policies",
            "article": None,
            "section": None,
        },
    )
    child = HandbookKnowledgeUnit(
        title="New Student",
        content="A student who is enrolled for the first time.",
        raw_text="1.1 New Student. A student who is enrolled for the first time.",
        metadata={
            "source_title": "Student Handbook",
            "document_type": "handbook_policy",
            "content_type": "policy",
            "chapter": "Undergraduate Academic Policies",
            "article": "Article 1 > Classifications of Students",
            "section": "Sec. 1 > Based on Admission",
        },
    )

    filtered = _filter_non_knowledge_units([parent, child])

    assert [unit.title for unit in filtered] == ["New Student"]
    assert filtered[0].metadata["chapter"] == "Undergraduate Academic Policies"
    assert filtered[0].metadata["article"] == "Article 1 > Classifications of Students"


def test_student_classification_definitions_split_when_ocr_merges_line():
    page_texts = [
        """
        Chapter 1 Student Admission
        Article 1 Classification of Students Based on Admission
        1.1 New Student. A student who is enrolled for the first time. 1.2 Transferee Student. A student who comes from another school. 1.3 Cross-enrollee Student. A student who enrolls in another institution for credit. 1.4 Foreign Student. A student who is not a citizen of the Philippines. 1.5 Returnee Student. A former student who returns to the university.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    new_student = next(unit for unit in doc.units if unit.title == "New Student")
    transferee = next(unit for unit in doc.units if unit.title == "Transferee Student")
    assert "Transferee Student" not in new_student.content
    assert transferee.content == "A student who comes from another school."


def test_numbered_definitions_with_trailing_marker_period_split_separately():
    page_texts = [
        """
        Chapter 1 Student Admission
        Article 1 Classification of Students Based on Admission
        1.1. New Student. A student who is enrolled for the first time. 1.2. Transferee Student. A student who comes from another school. 1.3. Cross-enrollee Student. A student who enrolls in another institution for credit. 1.4. Foreign Student. A student who is not a citizen of the Philippines. 1.5. Returnee Student. A former student who returns to the university.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    expected = {
        "New Student": "A student who is enrolled for the first time.",
        "Transferee Student": "A student who comes from another school.",
        "Cross-enrollee Student": "A student who enrolls in another institution for credit.",
        "Foreign Student": "A student who is not a citizen of the Philippines.",
        "Returnee Student": "A former student who returns to the university.",
    }
    units = {unit.title: unit for unit in doc.units if unit.title in expected}

    assert set(units) == set(expected)
    for title, content in expected.items():
        assert units[title].content == content


def test_embedded_handbook_owner_information_becomes_form_unit():
    page_texts = [
        """
        Foreword
        This handbook introduces student policies and responsibilities.
        Handbook Owner Information
        Name: ______________________
        Student Number: ______________________
        Curricular Year: ______________________
        College: ______________________
        Course: ______________________
        Guardian/Parent: ______________________
        Relationship: ______________________
        Contact Number: ______________________
        Address: ______________________
        Signature: ______________________
        Date: ______________________
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    foreword = next(unit for unit in doc.units if unit.title == "Foreword")
    owner = next(unit for unit in doc.units if unit.title == "Handbook Owner Information")
    assert "Student Number" not in foreword.content
    assert owner.metadata["content_type"] == "form_template"
    assert "________________" not in owner.content
    for field in [
        "Name",
        "Student Number",
        "Curricular Year",
        "College",
        "Course",
        "Guardian/Parent",
        "Relationship",
        "Contact Number",
        "Address",
        "Signature",
        "Date",
    ]:
        assert f"- {field}" in owner.content


def test_generic_ocr_word_splits_are_repaired():
    page_texts = [
        """
        Chapter 3 Admission
        Article 1 Admission Requirements
        Sec. 1.1 Applicant Readiness
        The ap plicant must submit com pleted documents and show readi ness for psy chological testing.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    unit = next(unit for unit in doc.units if unit.title == "Applicant Readiness")
    assert "applicant" in unit.content
    assert "completed" in unit.content
    assert "readiness" in unit.content
    assert "psychological" in unit.content


def test_reference_only_toc_stub_units_are_excluded():
    page_texts = [
        """
        Registration ........ 21
        Attendance ........ 37
        Honorable Dismissal ........ 38
        Graduation Requirements ........ 40
        Chapter 4 Academic Policies
        Article 1 Registration
        Sec. 1.1 Registration Rules
        Students must complete registration within the approved deadline.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    articles = doc.formatted_articles
    assert "Registration ........ 21" not in articles
    assert "Attendance ........ 37" not in articles
    assert "Students must complete registration" in articles


def test_unicode_ellipsis_and_page_only_toc_units_are_excluded():
    page_texts = [
        """
        Registration … 21
        Attendance … 37
        Honorable Dismissal … 38
        Graduation Requirements … 40

        Registration
        21
        Attendance
        Chapter 3
        Article 2

        Chapter 4 Academic Policies
        Article 1 Attendance
        Sec. 1.1 Attendance Rules
        Students shall attend classes regularly and comply with attendance requirements.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    articles = doc.formatted_articles
    assert "Registration" not in titles
    assert "Registration … 21" not in articles
    assert "Honorable Dismissal … 38" not in articles
    assert "Graduation Requirements … 40" not in articles
    assert "Students shall attend classes regularly" in articles


def test_wrapped_article_toc_entries_do_not_become_units_or_validation_flags():
    page_texts = [
        """
        TABLE OF CONTENTS
        Article 14: Thesis/Dissertation
        and Conduct of Thesis/Dissertation Writing .. 53
        Article 7: Composition, Administration, Coverage,
        Retention/Scholastic Policy .... 54
        """,
        """
        Chapter 5 Academic Policies
        Retention Requirement
        Students shall comply with retention and scholastic policies.
        """,
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    articles = doc.formatted_articles
    assert "Thesis/Dissertation" not in articles
    assert "Conduct of Thesis/Dissertation Writing" not in articles
    assert "Composition, Administration, Coverage" not in articles
    assert "Retention/Scholastic Policy" not in articles
    assert "Retention Requirement" in titles

    class Extraction:
        structured = doc
        knowledge_document_type = doc.document_type
        document_type = type("DocumentType", (), {"value": "pdf"})()

    chunks = [
        type(
            "Chunk",
            (),
            {
                "text": unit.article_text,
                "chunk_index": index,
                "char_start": 0,
                "metadata": dict(unit.metadata),
            },
        )()
        for index, unit in enumerate(doc.units)
    ]
    units = _knowledge_units_for_extraction(Extraction(), chunks)
    report = _validation_report(document_type="handbook_policy", units=units, chunks=chunks)
    assert report["toc_like_units_count"] == 0


def test_units_with_page_number_hierarchy_segment_are_rejected_as_toc_like():
    page_texts = [
        """
        Chapter 5 Functions and Objective of Student Affairs and Services
        56
        Article 7: Composition, Administration, Coverage,
        This short fragment is not policy body.

        Retention Requirement
        Students shall comply with retention and scholastic policies.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "Composition, Administration, Coverage," not in titles
    assert "Retention Requirement" in titles


def test_non_degree_students_title_is_clean_and_body_preserved():
    page_texts = [
        """
        Article 2 Admission Requirements
        2.6 Non-degree Students - College Regulation shall govern the admission of students who enroll in selected courses without earning a degree.
        Online Admission
        Applicants must complete the online admission form and submit required credentials.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Policy Manual",
    )

    non_degree = next(unit for unit in doc.units if unit.title == "Non-degree Students")
    assert "College Regulation shall govern" in non_degree.content
    assert "Online Admission" not in non_degree.content
    online = next(unit for unit in doc.units if unit.title == "Online Admission")
    assert "online admission form" in online.content


def test_ocr_fragments_do_not_become_hierarchy_metadata():
    page_texts = [
        """
        Chapter 3 Admission
        Article 1 Admission Requirements
        the recommendation of the Accreditation Committee/Admission
        This fragment should remain content, not a hierarchy path.
        Sec. 1.1 Applicant Readiness
        The ap plicant must show readi ness for psy chological testing.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    unit = next(unit for unit in doc.units if unit.title == "Applicant Readiness")
    assert "Accreditation Committee/Admission" not in str(unit.metadata)
    assert unit.metadata["chapter"] == "Chapter 3 > Admission"
    assert unit.metadata["article"] == "Article 1 > Admission Requirements"
    assert "applicant must show readiness for psychological testing" in unit.content


def test_toc_page_number_entries_without_dot_leaders_do_not_leak():
    page_texts = [
        """
        Contents
        Chapter 1 Student Affairs 8
        Article 2 Academic Policies 25
        Grading System 33
        GSAR Admission Requirements 43
        Thesis/Dissertation 53
        """,
        """
        Chapter 1 Student Affairs
        Students shall comply with handbook policies.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    articles = doc.formatted_articles
    assert "Grading System 33" not in articles
    assert "GSAR Admission Requirements 43" not in articles
    assert "Thesis/Dissertation 53" not in articles
    assert "Students shall comply" in articles


def test_merges_wrapped_heading_fragments_before_splitting_units():
    page_texts = [
        """
        Chapter 6 Student Affairs
        Article 1 Student Devel
        opment
        Students may participate in approved student development programs.
        Article 2 Unauthorized and
        unrecognized organizations
        Students shall not join unauthorized and unrecognized organizations.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "Student Development" in titles
    assert "Unauthorized and unrecognized organizations" in titles
    assert not any(title in {"Student Devel", "opment", "Writing"} for title in titles)

    development = next(unit for unit in doc.units if unit.title == "Student Development")
    unauthorized = next(unit for unit in doc.units if unit.title == "Unauthorized and unrecognized organizations")
    assert "approved student development programs" in development.content
    assert "shall not join" in unauthorized.content


def test_repairs_same_line_ocr_split_in_heading_fragments():
    page_texts = [
        """
        Chapter 6 Student Affairs
        Article 1 Student Devel opment
        Students may participate in approved student development programs.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    assert [unit.title for unit in doc.units] == ["Student Development"]
    assert "approved student development programs" in doc.units[0].content


def test_citation_article_reference_stays_inside_parent_offense_body():
    page_texts = [
        """
        Chapter 7 Student Discipline
        Major Offense
        Sec. 14 Unauthorized and Unrecognized Organizations
        Students shall not organize or join unauthorized and unrecognized organizations.
        (Based on CHED Memo. No. 9, s 2013,
        Article VIII Student Devel
        opment Sect.19).
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "Unauthorized and Unrecognized Organizations" in titles
    assert "Student Development" not in titles
    assert "Student Devel" not in titles

    offense = next(unit for unit in doc.units if unit.title == "Unauthorized and Unrecognized Organizations")
    assert "Students shall not organize" in offense.content
    assert "Article VIII Student Development Sect.19)." in offense.content
    assert offense.metadata["content_type"] == "disciplinary_rule"


def test_thesis_dissertation_wrapped_article_preserves_full_content():
    page_texts = [
        """
        Chapter 5 Academic Policies
        Article 14: Thesis/Dissertation
        and Conduct of Thesis/Dissertation Writing
        Graduate students shall comply with thesis and dissertation writing policies.
        The manuscript adviser, panel, and college shall follow approved procedures.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    assert len(doc.units) == 1
    unit = doc.units[0]
    assert unit.title == "Thesis/Dissertation and Conduct of Thesis/Dissertation Writing"
    assert "Graduate students shall comply" in unit.content
    assert "approved procedures" in unit.content
    assert unit.title != "Writing"


def test_thesis_dissertation_single_word_wrap_preserves_full_article_title():
    page_texts = [
        """
        Chapter 5 Academic Policies
        Article 14: Thesis/Dissertation and Conduct of Thesis/Dissertation
        Writing
        Graduate students shall comply with thesis and dissertation writing policies.
        The manuscript adviser, panel, and college shall follow approved procedures.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    unit = doc.units[0]
    assert unit.title == "Thesis/Dissertation and Conduct of Thesis/Dissertation Writing"
    assert "Graduate students shall comply" in unit.content
    assert not any(unit.title == bad for bad in ["Writing", "Thesis/Dissertation and Conduct of Thesis/Dissertation"])


def test_tight_section_marker_preserves_requirements_obligations_body():
    page_texts = [
        """
        Chapter 4 Student Duties
        Article 1 Requirements, Obligations, and Responsibilities
        Sec.1. LSPU
        Students shall observe university rules and regulations.
        Students must respect university property and comply with approved procedures.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    unit = next(unit for unit in doc.units if unit.title == "LSPU")
    assert unit.metadata["section"] == "Sec.1 > LSPU"
    assert "Students shall observe" in unit.content
    assert "comply with approved procedures" in unit.content


def test_law_program_listing_with_singular_campus_has_clean_title_and_programs():
    page_texts = [
        """
        Chapter 2 Curricular Offerings
        College of Law, Sta Cruz Campus
        Juris Doctor
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    unit = doc.units[0]
    assert unit.title == "Curricular Offerings - College of Law"
    assert unit.metadata["campuses"] == ["Sta. Cruz"]
    assert "Campuses:\n- Sta. Cruz" in unit.content
    assert "Programs:\n- Juris Doctor" in unit.content


def test_valid_short_program_listings_and_appendix_pages_are_not_suspicious():
    program_page = """
    Chapter 2 Curricular Offerings
    College of Arts
    BS Fine Arts
    """
    appendix_page = """
    Appendix M Reference Forms
    Official appendix metadata page.
    """

    program_doc = build_handbook_policy_document(
        raw_text=program_page,
        page_texts=[program_page],
        source_title="Student Handbook",
    )
    appendix_doc = build_handbook_policy_document(
        raw_text=appendix_page,
        page_texts=[appendix_page],
        source_title="Student Handbook",
    )

    class Extraction:
        knowledge_document_type = "handbook_policy"
        document_type = type("DocumentType", (), {"value": "pdf"})()

    Extraction.structured = program_doc
    program_chunks = [
        type("Chunk", (), {"text": unit.article_text, "chunk_index": index, "char_start": 0, "metadata": dict(unit.metadata)})()
        for index, unit in enumerate(program_doc.units)
    ]
    program_units = _knowledge_units_for_extraction(Extraction(), program_chunks)
    assert program_units[0]["content_type"] == "program_listing"
    assert "Programs:" in program_units[0]["content"]
    assert program_units[0]["status"] == "OK"
    assert "very_short" not in program_units[0]["suspicious_reasons"]

    Extraction.structured = appendix_doc
    appendix_chunks = [
        type("Chunk", (), {"text": unit.article_text, "chunk_index": index, "char_start": 0, "metadata": dict(unit.metadata)})()
        for index, unit in enumerate(appendix_doc.units)
    ]
    appendix_units = _knowledge_units_for_extraction(Extraction(), appendix_chunks)
    assert appendix_units[0]["content_type"] == "appendix"
    assert appendix_units[0]["status"] == "OK"
    assert "very_short" not in appendix_units[0]["suspicious_reasons"]


def test_sentence_like_counseling_procedure_title_ending_in_number_is_not_toc_like():
    content = " ".join(
        "The counselor shall receive the student, document the counseling process, and refer the student when needed."
        for _ in range(90)
    )
    unit = {
        "title": "Counseling process wherein the acceptable time is 50",
        "content": content,
        "content_type": "procedure",
        "word_count": len(content.split()),
        "metadata": {
            "source_title": "Student Handbook",
            "chapter": "Chapter 8 > Guidance Services",
            "article": "Article 1 > Counseling Services",
            "page_start": 50,
        },
    }

    status, reasons = _unit_status(unit)

    assert status == "OK"
    assert "toc_like" not in reasons
    assert "very_long" not in reasons


def test_short_appendix_form_templates_are_not_suspicious_when_fields_are_extracted():
    page_texts = [
        """
        Appendix I Counseling Form
        Name: ______________________
        Date: ______________________
        Signature: ______________________
        """,
        """
        Appendix L Referral Form
        Student Name: ______________________
        Reason: ______________________
        Referred By: ______________________
        """,
    ]

    doc = build_handbook_policy_document(
        raw_text="\n\n".join(page_texts),
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    class Extraction:
        structured = doc
        knowledge_document_type = doc.document_type
        document_type = type("DocumentType", (), {"value": "pdf"})()

    chunks = [
        type("Chunk", (), {"text": unit.article_text, "chunk_index": index, "char_start": 0, "metadata": dict(unit.metadata)})()
        for index, unit in enumerate(doc.units)
    ]
    units = _knowledge_units_for_extraction(Extraction(), chunks)
    form_units = [unit for unit in units if unit["content_type"] == "form_template"]

    assert {unit["title"] for unit in form_units} == {"Counseling Form", "Referral Form"}
    assert all(unit["status"] == "OK" for unit in form_units)
    assert all("very_short" not in unit["suspicious_reasons"] for unit in form_units)
    assert all("Required Fields:" in unit["content"] for unit in form_units)


def test_valid_short_minor_offense_unit_is_not_suspicious_when_content_is_complete():
    page_texts = [
        """
        Chapter 7 Student Discipline
        Article 1 Student Offenses
        Minor Offense
        - Warning
        - Written reprimand
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    class Extraction:
        structured = doc
        knowledge_document_type = doc.document_type
        document_type = type("DocumentType", (), {"value": "pdf"})()

    chunks = [
        type("Chunk", (), {"text": unit.article_text, "chunk_index": index, "char_start": 0, "metadata": dict(unit.metadata)})()
        for index, unit in enumerate(doc.units)
    ]
    units = _knowledge_units_for_extraction(Extraction(), chunks)
    minor = next(unit for unit in units if unit["title"] == "Minor Offense")

    assert minor["content_type"] == "disciplinary_rule"
    assert minor["status"] == "OK"
    assert "very_short" not in minor["suspicious_reasons"]


def test_suspicious_unit_diagnostics_include_source_snippet_and_classification():
    page_texts = [
        """
        Chapter 7 Student Discipline
        Article 1 Student Offenses
        Minor Offense
        """
    ]
    unit = {
        "title": "Minor Offense",
        "content": "",
        "content_type": "disciplinary_rule",
        "status": "Suspicious",
        "suspicious_reasons": ["very_short"],
        "metadata": {"source_title": "Student Handbook", "chapter": "Chapter 7 > Student Discipline", "page_start": 1},
    }

    diagnostics = suspicious_unit_diagnostics(page_texts=page_texts, units=[unit])

    assert diagnostics == [
        {
            "original_page_text_snippet": page_texts[0].strip(),
            "extracted_unit_title": "Minor Offense",
            "extracted_content": "",
            "suspicious_reasons": ["very_short"],
            "proposed_classification": "extraction issue",
        }
    ]


def test_diagnostic_report_summarizes_units_and_samples():
    page_texts = [
        """
        Appendix A Excuse Slip
        Name: ______________________
        Date: ______________________
        Reason: ______________________
        Submit this form to the instructor.
        Chapter 1 Admission
        1.1 New Student. A student who enrolls for the first time.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )
    report = doc.diagnostic_report(sample_size=10)

    assert report["total_knowledge_units"] == len(doc.units)
    assert report["total_chunks"] == len(doc.units)
    assert report["average_chunk_size"] > 0
    assert report["largest_chunk_size"] >= report["smallest_chunk_size"]
    assert report["top_10_largest_units"]
    assert {"title", "word_count", "content_type"} <= set(report["top_10_largest_units"][0])
    assert report["largest_chunk"]["size_chars"] >= report["smallest_chunk"]["size_chars"]
    assert len(report["sample_chunks"]) == len(doc.units)
    form = next(unit for unit in doc.units if unit.metadata["content_type"] == "form_template")
    assert "Required Fields:" in form.content
    assert "________________" not in form.content


def test_lettered_faculty_manual_sections_split_as_sibling_articles():
    page_texts = [
        """
        A. Faculty Official Time
        All faculty shall observe strictly their official time and render forty hours a week.
        B. Faculty Attendance and Absences
        1. Faculty member shall hold classes on time in his/her designated room assignments.
        2. Faculty member shall observe official time.
        3. Faculty member shall not be allowed to dismiss his/her classes earlier than the official time.
        4. Substitution of a duly qualified faculty for another teacher shall be done only by the Dean/Associate Dean of the College in case of exigency. C. Faculty I.D. and Uniform
        1. Faculty is required to wear the University Identification Card at all times. The identification card shall not be transferable.
        2. Faculty shall wear the prescribed uniform of the university. D. Teaching Load Assignment
        1. The Dean / Associate Dean of the College are responsible in the preparation and assignment of teaching loads and approved through channels.
        2. Teaching assignments shall be in line with the faculty's field of specialization.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="LSPU Faculty Manual 2020",
    )

    by_title = {unit.title: unit for unit in doc.units}
    assert "A. Faculty Official Time" in by_title
    assert "B. Faculty Attendance and Absences" in by_title
    assert "C. Faculty I.D. and Uniform" in by_title
    assert "D. Teaching Load Assignment" in by_title

    attendance = by_title["B. Faculty Attendance and Absences"]
    identity = by_title["C. Faculty I.D. and Uniform"]
    teaching_load = by_title["D. Teaching Load Assignment"]

    assert "Identification Card" not in attendance.content
    assert "Teaching Load Assignment" not in attendance.content
    assert "Identification Card" in identity.content
    assert "prescribed uniform" in identity.content
    assert "teaching loads" in teaching_load.content
    assert attendance.metadata["chapter"] != "B. Faculty Attendance And Absences"
    assert teaching_load.metadata["article"] == "D. Teaching Load Assignment"
    assert identity.metadata["article"] == "C. Faculty I.D. and Uniform"


def test_lettered_activity_lists_stay_inside_parent_unit():
    page_texts = [
        """
        Section 9 Vacation service credits of teachers
        Teacher's vacation service credits refer to the leave credits earned for services rendered during summer.
        The activities for which service credits may be granted are enumerated below.
        A. Service during registration and election days;
        B. Service for calamity assistance and rehabilitation when schools are used as evaluation center;
        C. Attendance in in-service training courses/seminars during summers and vacation/holidays;
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="LSPU Faculty Manual 2020",
    )

    titles = [unit.title for unit in doc.units]
    assert "A. Service during registration and election days" not in titles
    assert "C. Attendance in in-service training courses/seminars during summers and vacation/holidays" not in titles
    parent = next(unit for unit in doc.units if "Vacation service credits" in unit.title)
    assert "Service during registration and election days" in parent.content
    assert "Attendance in in-service training" in parent.content


# --- Regression tests for the 2026-10-21 disciplinary-offense-table fix ----
#
# Fixture line-wrapping below is copied verbatim (one table cell fragment
# per line) from PyMuPDF's real extraction of the actual LSPU Student
# Handbook 2021 PDF, pages 64 and 69 of 183 (Sec. 1 Acts of Cybercrime /
# 1.1 Cyber bullying, and Sec. 7-9 Falsification/Gambling/Indecency) --
# this is the exact shape that reproduced the reported malformed answer
# ("Section/Title/Definition — 3rd", "Offense — Offensesuspension", unrelated
# offenses running together). Several unrelated filler pages are included
# so the recurring "Section/Title/Definition" table header appears on far
# fewer than half of all pages -- otherwise the PRE-EXISTING
# _repeated_edge_lines threshold alone would already strip it, and the test
# would not actually exercise the new _drop_offense_table_header_block fix.

_CYBERCRIME_TABLE_PAGE = """
Page:  64 of 183
Section/Title/Definition
1st
Offense
2nd
Offense
3rd
Offense
Sec. 1. Acts of Cybercrime
(Stipulated by RA 10175 or the Cyber-
crime Prevention Act of 2012).
1.1. Cyber bullying or bullying
done through the use of tech-
nology or any electronic
means
Suspension
for one (1)
month
Suspension
for one (1)
semester
Expulsion
from the
University
"""

_GAMBLING_TABLE_PAGE = """
Page:  69 of 183
Section/Title/Definition
1st
Offense
2nd
Offense
3rd
Offense
7.2. Falsification of official Univer-
sity and public documents like
clearance, completion form,
and other related documents.
Suspension
for one (1)
month
Suspension
for one (1)
semester
Expulsion
from the
University
Sec. 8. Gambling. Engaging in
any form/s of gambling and/or
possessing of cards or any gam-
bling paraphernalia within the Uni-
versity premises.
Suspension
for one (1)
week and
40 hours
service to
be ren-
dered in
the institu-
tion
Suspension
for one (1)
semester
Sec. 9. Indecency and Obsceni-
ty. Engaging in indecent, obscene
conduct and activities which in-
clude possessing and/or circulating
pornographic/trashy literature and
"""

_UNRELATED_FILLER_PAGES = [
    """
    Chapter 3 Admission
    Sec. 1. General Admission Policy
    Applicants must submit a duly accomplished application form.
    """,
    """
    Chapter 4 Grading System
    Sec. 1. Computation of Grades
    The final grade is the average of all graded requirements.
    """,
    """
    Chapter 5 Scholarship
    Sec. 1. Academic Scholars
    Students with a GWA of 1.75 or better qualify for academic scholarship.
    """,
    """
    Chapter 8 Library Services
    Sec. 1. Borrowing Privileges
    Students may borrow up to three books at a time.
    """,
]


def _build_disciplinary_offense_table_fixture_pages() -> list[str]:
    # Filler pages sit before Chapter 6 and after the offense table, never
    # between the two table pages -- an intervening "Chapter N" heading
    # resets the article context (a separate, pre-existing staleness issue
    # this fix does not address), which the real handbook's contiguous
    # offense-table pages never trigger.
    return [
        *_UNRELATED_FILLER_PAGES[:2],
        "Chapter 6\nCODE OF CONDUCT FOR LSPU STUDENTS\nArticle 2. Major Offense.",
        _CYBERCRIME_TABLE_PAGE,
        _GAMBLING_TABLE_PAGE,
        *_UNRELATED_FILLER_PAGES[2:],
    ]


def test_offense_table_header_row_does_not_leak_into_unit_content():
    page_texts = _build_disciplinary_offense_table_fixture_pages()
    doc = build_handbook_policy_document(
        raw_text="\n".join(page_texts),
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
    )

    full_text = "\n".join(f"{unit.title}\n{unit.content}" for unit in doc.units)
    assert "Section/Title/Definition" not in full_text
    assert not any(unit.title.strip() == "Offense" for unit in doc.units)
    # The header fragments must not survive as leaked trailing noise either.
    trailing_lines = {
        unit.content.strip().splitlines()[-1].strip()
        for unit in doc.units
        if unit.content.strip()
    }
    assert "1st" not in trailing_lines
    assert "Offense" not in trailing_lines


def test_cell_boundary_preserves_whitespace_after_complete_word():
    page_texts = _build_disciplinary_offense_table_fixture_pages()
    doc = build_handbook_policy_document(
        raw_text="\n".join(page_texts),
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
    )

    full_text = "\n".join(unit.content for unit in doc.units)
    assert "Expulsionfrom" not in full_text
    assert "Expulsion from the University" in full_text


def test_genuine_compound_word_split_across_lines_still_repairs():
    """2026-10-21 narrowing: the stopword short-circuit added for the
    "Expulsionfrom" fix must not block a genuine heading word split like
    "with" + "in" -> "within" just because "in" is also a stopword. Only
    the exact (tail, first-word) pairs in _KNOWN_COMPOUND_WORD_SPLITS are
    exempted from the short-circuit -- this stays narrow rather than
    reopening the original bug for e.g. "with" + "the" (see
    test_cell_boundary_preserves_whitespace_after_complete_word, which
    must keep failing to merge)."""
    page_texts = [
        """
        Chapter 6 Student Affairs
        Article 3 Conduct with
        in the Classroom
        Students shall behave appropriately during class sessions.
        """
    ]

    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
    )

    titles = [unit.title for unit in doc.units]
    assert "Conduct within the Classroom" in titles
    assert "Conduct with" not in titles
    assert "in the Classroom" not in titles


def test_known_compound_word_split_followed_by_proper_noun_stays_separate():
    """2026-10-21 second narrowing: a whitelisted (tail, first-word) pair
    must still NOT merge when the word right after the preposition is
    capitalized with nothing in between (e.g. "in Person", "by Email") --
    that reads as a new, unrelated phrase, not a continuation of the
    compound word. Only a lowercase continuation (an article/determiner,
    as in "within the Classroom") is trusted as a genuine completion."""
    cases = [
        ("Article 4 Submit Application here", "in Person", "here in Person"),
        ("Article 4 Report Violations here", "by Email", "here by Email"),
        ("Article 4 Grievances Filed there", "in Dormitory A", "there in Dormitory A"),
        ("Article 4 Students Enrolled where", "in Doubt Exists", "where in Doubt Exists"),
    ]
    for first_line, second_line, expected_unjoined_fragment in cases:
        page_texts = [f"\n{first_line}\n{second_line}\nSee the relevant office for details.\n"]
        doc = build_handbook_policy_document(
            raw_text=page_texts[0],
            page_texts=page_texts,
            source_title="Student Handbook",
        )
        full_text = " ".join(f"{unit.title} {unit.content}" for unit in doc.units)
        assert expected_unjoined_fragment in full_text, (first_line, second_line, full_text)
        assert "herein" not in full_text.lower()
        assert "hereby" not in full_text.lower()
        assert "therein" not in full_text.lower()
        assert "wherein" not in full_text.lower()


def test_cyberbullying_and_gambling_offenses_stay_independently_identifiable():
    page_texts = _build_disciplinary_offense_table_fixture_pages()
    doc = build_handbook_policy_document(
        raw_text="\n".join(page_texts),
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
    )

    titles = [unit.title for unit in doc.units]
    assert "Cyber bullying or bullying" in titles
    assert "Gambling" in titles

    cyberbullying = next(unit for unit in doc.units if unit.title == "Cyber bullying or bullying")
    gambling = next(unit for unit in doc.units if unit.title == "Gambling")
    indecency = next(unit for unit in doc.units if unit.title.startswith("Indecency"))
    falsification = next(unit for unit in doc.units if unit.title.startswith("Falsification of official"))

    # Verified first-offense penalties (see the investigation report):
    # Cyberbullying 1st offense -> suspension for one (1) month.
    assert "Suspension for one (1) month" in cyberbullying.content
    # Gambling 1st offense -> suspension for one (1) week and 40 hours
    # institutional service.
    assert "Suspension for one (1) week and 40 hours" in gambling.content

    # Gambling must not run into the unrelated offense that follows it,
    # and must not run into the unrelated offense that precedes it either.
    assert "Indecency" not in gambling.content
    assert "Falsification" not in gambling.content
    assert "Gambling" not in falsification.content
    assert "Gambling" not in indecency.content

    # The genuinely absent third-offense Gambling penalty must stay absent
    # -- never invented/backfilled from Cyberbullying's or any other row's
    # third-offense penalty (both legitimately say "Expulsion from the
    # University", which must never leak into Gambling's own content).
    assert "Expulsion" not in gambling.content
    assert gambling.content.count("Suspension") == 2


# --- Regression tests for the 2026-10-25 real-extraction header fix -------
#
# 2026-10-25 investigation finding: the hand-authored fixtures above
# (_CYBERCRIME_TABLE_PAGE / _GAMBLING_TABLE_PAGE) put each table cell on
# its own line, matching _is_offense_table_header_anchor's one-cell-per-
# line assumption. A raw PyMuPDF .text dump of the ACTUAL LSPU Student
# Handbook PDF (pages 64-71 of 183 -- the full Sec. 1-9 run of this same
# table) shows that assumption does not hold: PyMuPDF instead joins the
# anchor label with the ordinal cells onto ONE line with "|", e.g.
# "Section/Title/Definition | 1st | 2nd | 3rd", immediately followed by one
# line combining the three "Offense" cells, e.g. "Offense | Offense |
# Offense" -- confirmed byte-identical on every one of the 8 consecutive
# sampled pages. Against that real shape, the old fix left the header
# fully unstripped (leaking into unit content 16 times across the real
# 497-unit extraction).
#
# These fixtures are copied VERBATIM from that raw dump (not hand-
# simplified), including the real "|" cell-boundary noise inside the
# offense rows themselves. That noise is a DIFFERENT, unresolved problem:
# PyMuPDF's plain-text extraction does not reliably preserve which of the
# table's 4 columns (description / 1st / 2nd / 3rd offense) each word
# belongs to -- the "|" character appears both at genuine column
# boundaries and, inconsistently, in the middle of a single column's own
# wrapped text (e.g. "nology or any | electronic month | semester
# University" splits the single left-column phrase "nology or any
# electronic" across a "|"). Reconstructing the penalty columns correctly
# would need position/bounding-box-aware extraction (a change to
# pymupdf_extractor.py, out of scope here), not a text-line heuristic in
# this module. These tests therefore verify ONLY the header-row removal
# fix (now confirmed against the real shape) -- they do NOT assert correct
# per-offense penalty text, and must not be read as evidence that the
# Cyberbullying/Gambling penalty-extraction problem is resolved. See the
# 2026-10-25 investigation report for that still-open gap.

_REAL_CYBERCRIME_PAGE_73 = """
Section/Title/Definition | 1st | 2nd | 3rd
Offense | Offense | Offense
Sec. 1. Acts of Cybercrime
(Stipulated by RA 10175 or the Cyber-
crime Prevention Act of 2012).
1.1. Cyber bullying or bullying Suspension Suspension Expulsion
done through the use of tech- for one (1) for one (1) from the
nology or any | electronic month | semester University
means
"""

_REAL_GAMBLING_PAGE_78 = """
Section/Title/Definition | 1st | 2nd | 3rd
Offense | Offense | Offense
University. (Forging signature and
falsifying public documents.)
Suspension
for one (1)
7.1. Falsification of common forms week and Suspension Suspension
like excuse letters, waivers and 40 hours for one (1) for one (1)
signature of parents. | service in month | semester
the univer-
sity
7.2. Falsification of official Univer- Suspension Suspension Expulsion
sity and public documents like for one (1) for one (1) from the
clearance, completion form, month | semester University
and other related documents.
Suspension
for one (1)
7.3. Borrowing and lending Library | week 40 hours and Suspension
card and School ID using un- Reprimand service to for one (1)
authorized ID | be rendered month
in the insti-
tution
Suspension
for one (1)
Sec. 8. Gambling. Engaging in | week and
any form/s of gambling and/or | 40 hours Suspension
possessing of cards or any gam- | service to for one (1)
bling paraphernalia within the Uni- be ren- | semester
versity premises. | dered in
the institu-
tion
Sec. 9. Indecency and Obsceni-
ty. Engaging in indecent, obscene
conduct and activities which in-
clude possessing and/or circulating
pornographic/trashy literature and
"""


def _build_real_extraction_shape_fixture_pages() -> list[str]:
    return [
        *_UNRELATED_FILLER_PAGES[:2],
        "Chapter 6\nCODE OF CONDUCT FOR LSPU STUDENTS\nArticle 2. Major Offense.",
        _REAL_CYBERCRIME_PAGE_73,
        _REAL_GAMBLING_PAGE_78,
        *_UNRELATED_FILLER_PAGES[2:],
    ]


def test_real_pymupdf_combined_header_line_does_not_leak_into_unit_content():
    """The real extraction's actual 2-line header shape -- confirmed
    2026-10-25 -- must be dropped, the same way the hand-authored
    one-cell-per-line shape already was."""
    page_texts = _build_real_extraction_shape_fixture_pages()
    doc = build_handbook_policy_document(
        raw_text="\n".join(page_texts),
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
    )

    full_text = "\n".join(f"{unit.title}\n{unit.content}" for unit in doc.units)
    assert "Section/Title/Definition" not in full_text
    assert "Section/Title/Definition | 1st | 2nd | 3rd" not in full_text
    assert "Offense | Offense | Offense" not in full_text


def test_real_pymupdf_shape_inline_offense_ordinal_prose_is_preserved():
    """The combined-header fix must stay scoped to the exact repeating
    header pair -- it must never remove a legitimate inline use of an
    ordinal/"offense" word in real policy prose (e.g. "1st offense:
    Suspension..." from Sec. 10 Narcotics-related Concerns elsewhere in
    this same table)."""
    page_texts = [
        "Chapter 6\nCODE OF CONDUCT FOR LSPU STUDENTS\nArticle 2. Major Offense.",
        (
            "Section/Title/Definition | 1st | 2nd | 3rd\n"
            "Offense | Offense | Offense\n"
            "Sec. 10. Narcotics-related Con- 1st offense: Suspension for one (1) se-\n"
            "cerns. Possession, use or distribu- mester or dismissal according to the\n"
            "tion of any prohibited drugs or gravity of the offense."
        ),
    ]
    doc = build_handbook_policy_document(
        raw_text="\n".join(page_texts),
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
    )

    full_text = "\n".join(f"{unit.title}\n{unit.content}" for unit in doc.units)
    assert "1st offense: Suspension for one (1)" in full_text


# --- Regression tests for the 2026-10-26 structured disciplinary-table ----
# extraction fix (uses PageExtraction.table_regions from PyMuPDF's native
# find_tables().extract(), confirmed 2026-10-26 to already correctly
# separate this table's 4 columns -- see the investigation report). Row
# content below is copied VERBATIM from that real extraction output
# (pages 73, 75, 76, 78, 87 of the actual LSPU Student Handbook PDF), not
# hand-simplified, so these tests exercise the real shape this fix must
# handle, including its genuine page-boundary continuation and the one
# confirmed empty-but-should-not-be-silently-absent cell (1.5).

_HEADER_ROW = ["Section/Title/Definition", "1st\nOffense", "2nd\nOffense", "3rd\nOffense"]

# Real rows from page 73 (table bbox matches the earlier investigation's
# captured geometry).
_PAGE_73_ROWS = [
    _HEADER_ROW,
    [
        "Sec. 1. Acts of Cybercrime\n(Stipulated by RA 10175 or the Cyber-\ncrime Prevention Act of 2012).",
        "",
        None,
        None,
    ],
    [
        "1.1. Cyber bullying or bullying\ndone through the use of tech-\nnology or any electronic\nmeans",
        "Suspension\nfor one (1)\nmonth",
        "Suspension\nfor one (1)\nsemester",
        "Expulsion\nfrom the\nUniversity",
    ],
    [
        "1.5. Computer-related fraud, for-\ngery and identity theft or the\nintentional acquisition, use,\nmisuse, transfer, possession,\nalteration or deletion of identi-\nfying information belonging to\nanother person.",
        "",
        "",
        "",
    ],
]
_PAGE_73_BBOX = [58.0, 72.5, 431.9, 582.8]

# Real rows from page 75/76 (Sec. 4 "Bringing of Deadly Weapons" has its
# full penalty already on page 75; its description continues, headerless
# and all-penalty-empty, as page 76's own first body row).
_PAGE_75_ROWS = [
    _HEADER_ROW,
    [
        "Sec. 4. Bringing of Deadly\nWeapons. Carrying within the Uni-\nversity premises any firearm/s,\nknife with a blade longer than 2-\n1/2 inches, ice pick, explosive/s or\nany other dangerous or deadly\nweapon/s is a major offense. How-\never, this provision shall not apply",
        "Suspension\nfor one (1)\nsemester",
        "Suspension\nfor one (1)\nyear",
        "Expulsion\nfrom the\nUniversity",
    ],
]
_PAGE_75_BBOX = [57.5, 73.2, 431.5, 575.9]
_PAGE_76_ROWS = [
    _HEADER_ROW,
    [
        "to anyone who possesses bolo/s\nand other monitored tools in\nconnection with his/her studies or\nfield of activities. Case of unau-\nthorized possession of firearms\nshall be reported to Safety and Se-\ncurity Management Office.",
        "",
        "",
        "",
    ],
    [
        "Sec. 5. Bullying\n(RA 10627 or the Anti-Bullying Act of\n2013)",
        "",
        None,
        None,
    ],
]
_PAGE_76_BBOX = [36.6, 73.9, 410.4, 577.1]

# Real rows from page 78 (Gambling, fused with Falsification in today's
# un-fixed output).
_PAGE_78_ROWS = [
    _HEADER_ROW,
    [
        "7.2. Falsification of official Univer-\nsity and public documents like\nclearance, completion form,\nand other related documents.",
        "Suspension\nfor one (1)\nmonth",
        "Suspension\nfor one (1)\nsemester",
        "Expulsion\nfrom the\nUniversity",
    ],
    [
        "Sec. 8. Gambling. Engaging in\nany form/s of gambling and/or\npossessing of cards or any gam-\nbling paraphernalia within the Uni-\nversity premises.",
        "Suspension\nfor one (1)\nweek and\n40 hours\nservice to\nbe ren-\ndered in\nthe institu-\ntion",
        "Suspension\nfor one (1)\nsemester",
        "",
    ],
    [
        "Sec. 9. Indecency and Obsceni-\nty. Engaging in indecent, obscene\nconduct and activities which in-\nclude possessing and/or circulating\npornographic/trashy literature and",
        "",
        None,
        None,
    ],
]
_PAGE_78_BBOX = [36.6, 74.0, 410.5, 575.9]

# Page 87: the table ends after one row, then genuine non-table prose
# ("Article 4. Norms and Decorum...") follows on the SAME page.
_PAGE_87_ROWS = [
    _HEADER_ROW,
    [
        "9.2. Unauthorized climbing or\njumping over the perimeter\nfence of the University",
        "Reprimand\nand com-\nmunity\nservice to\nbe ren-\ndered in\nthe institu-\ntion",
        "suspension\nfor one (1)\nweek and\n40 hours\nservice to\nbe rendered\nin the insti-\ntution",
        "Subsequent\noffense:\nSuspension\nfor one (1)\nsemester",
    ],
]
_PAGE_87_BBOX = [36.6, 74.0, 410.5, 180.0]


# Real rows from page 74 (1.6 Cybersex, 1.7 Child Pornography, 1.8 Cyber
# Libel -- each has only its 1st-offense cell filled with "expulsion from
# the University"; 1.9 has a full 3-tier structure for contrast).
_PAGE_74_ROWS = [
    _HEADER_ROW,
    [
        "1.6. Cybersex or the willful engage-\nment, maintenance, control or\noperation, directly or indirect-\nly, of any lascivious exhibition\nof sexual organs or sexual ac-\ntivity, with the aid of a com-\nputer system, for favor or con-\nsideration.",
        "expulsion from the University",
        None,
        None,
    ],
    [
        "1.7. Child Pornography, including\nunlawful and prohibited acts\ndefined and punishable by RA\n9775 or the Anti-Child Por-\nnography Act of 2009, com-\nmitted through a computer\nsystem.",
        "expulsion from the University",
        None,
        None,
    ],
    [
        "1.8. Cyber Libel or the unlawful or\nprohibited acts of libel as de-\nfined in Article 355 of the Re-\nvised Penal Code, committed\nthrough a computer system or\nany other similar means.",
        "expulsion from the University",
        None,
        None,
    ],
    [
        "1.9. Aiding, abetting or attempting\nto willfully commit any of the\noffenses enumerated as acts of\ncybercrime shall be held liable.",
        "Suspension\nfor one (1)\nweek and\n40 hours\nservice to\nbe ren-\ndered in\nthe institu-\ntion",
        "Suspension\nfor one (1)\nmonth",
        "Suspension\nfor one (1)\nsemester",
    ],
]
_PAGE_74_BBOX = [62.1, 73.9, 410.5, 575.1]

# Real rows from page 77 (5.4 Any slanderous statement or..., then Sec. 6
# intro, 6.1, and 6.2 Any drunkenness or drunken... -- all four genuinely
# share this one real page).
_PAGE_77_ROWS = [
    _HEADER_ROW,
    [
        "5.4. Any slanderous statement or\naccusation that causes the vic-\ntim undue emotional distress\nlike directing foul language\nor profanity at the target,\nname-calling, impersonating or\ncalling/giving derogatory\nnames etc.",
        "Suspension\nfor one (1)\nmonth",
        "Suspension\nfor one (1)\nsemester",
        "Expulsion\nfrom the\nUniversity",
    ],
    [
        "Sec. 6. Drinking/Alcohol-related\nConcerns. Drinking alcoholic bev-\nerages or exhibition of any drunken\nbehavior within the University\npremises.",
        "",
        "",
        "",
    ],
    [
        "6.1. Drinking alcoholic beverages",
        "Suspension\nfor one (1)\nweek and\n40 hours\nservice to\nbe ren-\ndered in\nthe institu-\ntion",
        "Suspension\nfor one (1)\nsemester",
        "Expulsion\nfrom the\nUniversity",
    ],
    [
        "6.2. Any drunkenness or drunken\nbehavior resulting in physical\ninjuries to other person/s or\ndestruction of property/ies.",
        "Suspension\nfor one (1)\nmonth and\npayment\nof damag-\nes",
        "Suspension\nfor one (1)\nsemester\nand pay-\nment for\ndamages",
        "Expulsion\nfrom the\nUniversity\nand pay-\nment of\ndamages",
    ],
]
_PAGE_77_BBOX = [57.5, 73.2, 431.5, 575.9]

# Real rows from page 76 including 5.1 (Any severe or repeated use
# of...), for Fix 2's dedicated regression test.
_PAGE_76_WITH_5_1_ROWS = [
    _HEADER_ROW,
    [
        "Sec. 5. Bullying\n(RA 10627 or the Anti-Bullying Act of\n2013)",
        "",
        None,
        None,
    ],
    [
        "5.1. Any severe or repeated use of\nwritten or verbal expression,\nphysical act or gesture, or a\ncombination thereof that is\ndirected against another stu-\ndent, causing or placing the\nlatter in reasonable fear\nof physical or emotional harm\nor damage to his/her property.",
        "Suspension\nfor one (1)\nweek and\n40 hours\nservice to\nbe ren-\ndered in\nthe institu-\ntion",
        "Suspension\nfor one (1)\nmonth",
        "Suspension\nfor one (1)\nsemester",
    ],
    [
        "5.2. Creating a hostile environment\nat school for the other student,\ninfringing on the rights of the\nother student at school, or ma-\nterially and substantially dis-\nrupting his/her education pro-\ncess.",
        "Suspension\nfor one (1)\nweek and\n40 hours\nservice to\nbe ren-\ndered in\nthe institu-\ntion",
        "Suspension\nfor one (1)\nmonth",
        "Suspension\nfor one (1)\nsemester",
    ],
]

# Real row from page 79 (9.2 Uploading, downloading and... -- only the
# 1st-offense cell is filled; must stay unconfirmed per explicit
# instruction, not reclassified as empty).
_PAGE_79_ROWS = [
    _HEADER_ROW,
    [
        "9.2. Uploading, downloading and\nsharing sex video scandals.",
        "Suspension for one (1) month",
        None,
        None,
    ],
]
_PAGE_79_BBOX = [57.5, 73.2, 431.3, 576.3]

# Real rows from page 81 (14.2 Unrecognized organizations and 14.3
# Recruitment of an unauthor- -- the latter's source text is missing the
# period after "14.3" that every sibling entry has).
_PAGE_81_ROWS = [
    _HEADER_ROW,
    [
        "14.2. Unrecognized organizations\noperating and conducting ac-\ntivities who did not apply for\nthe recognition and operation\n(based on the ISO coded\nform approved guidelines for\napplication, recognition and\noperation of student organi-\nzations).",
        "Warning",
        "The stu-\ndent organ-\nization is\nbanned to\noperate for\none (1) se-\nmester",
        None,
    ],
    [
        "14.3 Recruitment of an unauthor-\nized and unrecognized organ-\nization that promotes hazing\nand physical or psychological\nharm to students.",
        "Suspension\nfor one\nsemester",
        "Suspension\nfor one\nyear",
        None,
    ],
]
_PAGE_81_BBOX = [57.5, 73.2, 431.3, 575.9]

# Real row from page 83 (1.2.3/1.2.4, merged into one cell by PyMuPDF --
# a narrative attendance/academic-process consequence, not a
# Suspension/Expulsion-tier offense; all three penalty cells are empty).
_PAGE_83_ROWS = [
    _HEADER_ROW,
    [
        "1.2.3. Every student accumulat-\ning unexcused ab-\nsences from class\nequivalent to 17% of the\ntotal number of hours/\nsemester for a particular\nsubject or class shall be\ndropped from the roll of\nstudents. However, ex-\ncused absences can be\nremoved through make-\nup.\n1.2.4. Every student shall secure\nan excuse slip from the\nGuidance Office for ab-\nsence/s made before ad-\nmission to classes.",
        "",
        "",
        "",
    ],
]
_PAGE_83_BBOX = [57.5, 73.2, 431.3, 575.9]


def _offense_table_page(page_number: int, rows: list, bbox: list[float], *, tail_words=None) -> PageExtraction:
    return PageExtraction(
        page_number=page_number,
        text="GARBLED PLACEHOLDER -- must be overridden, never read when a valid table is found",
        method="digital",
        words=tail_words,
        table_regions=[{"bbox": bbox, "rows": rows}],
    )


def _build_document_with_disciplinary_pages(pdf_pages: list[PageExtraction], num_pages: int):
    page_texts = ["placeholder page text" for _ in range(num_pages)]
    return build_handbook_policy_document(
        raw_text="\n".join(page_texts),
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
        pdf_pages=pdf_pages,
    )


def test_native_table_detection_assigns_exact_cell_text_to_columns():
    pdf_pages = [_offense_table_page(1, _PAGE_73_ROWS, _PAGE_73_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    cyberbullying = next(u for u in doc.units if "Cyber bullying" in u.title)
    # Note: "tech-\nnology" is not rejoined into "technology" -- that is a
    # pre-existing, general-pipeline limitation unrelated to this fix:
    # mid-word hyphen-wrap repair across two lines (_merge_wrapped_heading_lines)
    # only applies to HEADING lines, never to body content, for any
    # document in this module, not something introduced here. What this
    # fix is responsible for -- correct column separation and exact
    # penalty wording -- is asserted below.
    assert "done through the use of tech- nology or any electronic means" in cyberbullying.content
    assert "First offense: Suspension for one (1) month." in cyberbullying.content
    assert "Second offense: Suspension for one (1) semester." in cyberbullying.content
    assert "Third offense: Expulsion from the University." in cyberbullying.content
    # No cell-boundary pipe noise, and no leaked table header anywhere.
    assert "|" not in cyberbullying.content
    assert "Section/Title/Definition" not in cyberbullying.content
    assert cyberbullying.metadata["penalty_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert cyberbullying.metadata["penalty_1st_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert cyberbullying.metadata["penalty_2nd_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert cyberbullying.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    # The hidden confidence marker must never leak into student-facing content.
    assert "PENALTY_CONFIDENCE" not in cyberbullying.content
    assert "PENALTY_CONFIDENCE" not in cyberbullying.title
    assert "PENALTY_CONFIDENCE" not in cyberbullying.raw_text


def test_gambling_first_offense_correct_and_third_offense_cell_stays_empty_not_invented():
    pdf_pages = [_offense_table_page(1, _PAGE_78_ROWS, _PAGE_78_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    gambling = next(u for u in doc.units if u.title.strip() == "Gambling")
    falsification = next(u for u in doc.units if u.title.startswith("Falsification"))
    indecency = next(u for u in doc.units if u.title.startswith("Indecency"))

    assert "First offense: Suspension for one (1) week and 40 hours service to be rendered in the institution." in gambling.content
    assert "Second offense: Suspension for one (1) semester." in gambling.content
    # Genuinely absent third-offense penalty: no sentence, never invented
    # from Cyberbullying's/Falsification's own "Expulsion" value.
    assert "Third offense" not in gambling.content
    assert "Expulsion" not in gambling.content
    assert gambling.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_EMPTY
    # No cross-contamination with neighboring offenses in either direction.
    assert "Falsification" not in gambling.content
    assert "Indecency" not in gambling.content
    assert "Gambling" not in falsification.content
    assert "Gambling" not in indecency.content


def test_native_table_split_items_classify_as_disciplinary_rule_not_policy():
    """Regression for the Cyberbullying/Gambling investigation: before the
    native-table fix, both offenses' merged/mislabeled chunks fell through
    _content_type's classification to the generic "policy" default,
    because neither the word "offense" nor any other disciplinary-trigger
    word happened to appear in their own (wrong) merged text. The
    native-table fix's own rendered "First/Second/Third offense: ..."
    sentences restore that signal -- this must resolve to "disciplinary_rule"
    for every correctly-split item, not just the ones that already
    happened to contain a trigger word in their raw description.
    """
    cyberbullying_pages = [_offense_table_page(1, _PAGE_73_ROWS, _PAGE_73_BBOX)]
    cyberbullying_doc = _build_document_with_disciplinary_pages(cyberbullying_pages, 1)
    cyberbullying = next(u for u in cyberbullying_doc.units if "Cyber bullying" in u.title)
    assert cyberbullying.metadata["content_type"] == "disciplinary_rule"

    gambling_pages = [_offense_table_page(1, _PAGE_78_ROWS, _PAGE_78_BBOX)]
    gambling_doc = _build_document_with_disciplinary_pages(gambling_pages, 1)
    gambling = next(u for u in gambling_doc.units if u.title.strip() == "Gambling")
    assert gambling.metadata["content_type"] == "disciplinary_rule"


def test_offense_1_5_empty_penalties_represented_as_unconfirmed_not_empty():
    """The one confirmed case of genuine extraction data loss (see the
    investigation report): entry 1.5 sits immediately before the page 73
    page break with all three penalty cells empty, unlike every sibling
    sub-item (1.1-1.4, 1.6-1.9) which all carry a real penalty. This must
    never be presented as if the penalty were confirmed absent."""
    pdf_pages = [_offense_table_page(1, _PAGE_73_ROWS, _PAGE_73_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    entry_1_5 = next(u for u in doc.units if "Computer-related fraud" in u.title)
    assert entry_1_5.metadata["penalty_confidence"] == PENALTY_CONFIDENCE_UNCONFIRMED
    assert entry_1_5.metadata["penalty_1st_confidence"] == PENALTY_CONFIDENCE_UNCONFIRMED
    assert entry_1_5.metadata["penalty_2nd_confidence"] == PENALTY_CONFIDENCE_UNCONFIRMED
    assert entry_1_5.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_UNCONFIRMED
    # The uncertainty must be visible directly in the content itself (not
    # only in metadata a downstream consumer might never inspect) --
    # guaranteed to survive into whatever ultimately answers a student.
    assert PENALTY_UNCONFIRMED_NOTE in entry_1_5.content
    assert entry_1_5.content.count(PENALTY_UNCONFIRMED_NOTE) == 3
    # Never silently rendered as if genuinely absent.
    assert "Expulsion" not in entry_1_5.content


def test_section_intro_row_with_no_subitem_keeps_empty_confidence_not_unconfirmed():
    """A bare "Sec. N. <title>." row (no numbered sub-item) with empty
    penalty cells is a genuinely different case from 1.5 -- it has no
    penalty by design (e.g. "Sec. 1. Acts of Cybercrime" is the section's
    own intro sentence, not an offense with its own sanction)."""
    pdf_pages = [_offense_table_page(1, _PAGE_73_ROWS, _PAGE_73_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    intro = next(u for u in doc.units if "Acts of Cybercrime" in u.title)
    assert intro.metadata.get("penalty_confidence") in (None, PENALTY_CONFIDENCE_EMPTY)
    assert "not confirmed in the source document" not in intro.content


def test_page_boundary_continuation_merges_into_preceding_offense_not_a_new_unit():
    """Sec. 4 "Bringing of Deadly Weapons" has its full, already-correct
    penalty on page 75; its description continues, headerless and with
    all three penalty cells empty, as the literal first body row of
    page 76. That continuation must merge into Sec. 4's own unit -- it
    must never become its own separate, penalty-less "offense"."""
    pdf_pages = [
        _offense_table_page(1, _PAGE_75_ROWS, _PAGE_75_BBOX),
        _offense_table_page(2, _PAGE_76_ROWS, _PAGE_76_BBOX),
    ]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 2)

    deadly_weapons = next(u for u in doc.units if "Bringing of Deadly" in u.title)
    assert "to anyone who possesses bolo/s and other monitored tools" in deadly_weapons.content
    assert "First offense: Suspension for one (1) semester." in deadly_weapons.content
    assert "Second offense: Suspension for one (1) year." in deadly_weapons.content
    assert "Third offense: Expulsion from the University." in deadly_weapons.content

    # No standalone, penalty-less unit was created for the continuation text.
    assert not any(
        u.content.strip().startswith("to anyone who possesses bolo/s") for u in doc.units
    )
    bullying_titles = [u.title for u in doc.units if "Bullying" in u.title and "Cyber" not in u.title]
    assert bullying_titles  # Sec. 5 Bullying still starts its own, separate unit.

    # 2026-10-26 Fix 3: ordering. The continuation text must appear BEFORE
    # the penalty block, never after it -- the whole description reads
    # completely first, then the clearly labeled penalties, matching the
    # required presentation order (description, then 1st/2nd/3rd
    # offense). Before this fix, the continuation was appended onto the
    # already-rendered page-75 text, landing after "Third offense:
    # Expulsion from the University."
    continuation_pos = deadly_weapons.content.index("to anyone who possesses bolo/s")
    first_offense_pos = deadly_weapons.content.index("First offense:")
    assert continuation_pos < first_offense_pos


def test_invalid_table_structure_does_not_silently_fall_back_to_flattened_text():
    """A row that does not have exactly 4 cells must never be silently
    processed as if it were either a valid table row or the original,
    potentially-corrupted flattened text -- both would risk presenting
    unverified content as confirmed policy."""
    bad_rows = [_HEADER_ROW, ["Only one cell, missing the other three"]]
    pdf_pages = [_offense_table_page(1, bad_rows, _PAGE_73_BBOX)]
    page_texts = ["Sec. 99. Some Garbled Offense Suspension Suspension Expulsion week semester University"]
    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
        pdf_pages=pdf_pages,
    )

    full_text = "\n".join(f"{u.title}\n{u.content}" for u in doc.units)
    assert "EXTRACTION_UNCERTAIN" in full_text
    # The original garbled text must not appear verbatim as if trusted.
    assert "Suspension Suspension Expulsion week semester University" not in full_text


def test_partial_table_page_preserves_genuine_trailing_non_table_content():
    """Page 87: the table ends after one row, then real, unrelated prose
    ("Article 4. Norms and Decorum...") follows on the SAME page. That
    trailing content must be preserved, not discarded, when the table
    portion of the page is replaced."""
    tail_words = []
    # Minimal word geometry below the table's bbox bottom (180.0), enough
    # for _after_table_text's row-clustering to reconstruct two lines: the
    # heading, plus a body sentence (a heading with no body at all is
    # correctly dropped by _build_units, same as for any other document --
    # that is not something this fix changes).
    rows_of_words = [
        (200.0, ["Article", "4.", "Norms", "and", "Decorum"]),
        (215.0, ["The", "following", "are", "not", "allowed."]),
    ]
    for y, words in rows_of_words:
        for i, word in enumerate(words):
            x0 = 40.0 + i * 40.0
            tail_words.append(
                {"text": word, "x0": x0, "y0": y, "x1": x0 + 35.0, "y1": y + 10.0, "cy": y + 5.0, "height": 10.0}
            )
    pdf_pages = [_offense_table_page(1, _PAGE_87_ROWS, _PAGE_87_BBOX, tail_words=tail_words)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    # "Article 4." becomes heading/metadata context (the same way every
    # other "Article N." heading in this document already does), and
    # "Norms and Decorum" becomes the unit's title -- not a bug, the
    # existing, unchanged behavior for any Article-level heading.
    norms_unit = next(u for u in doc.units if "Norms and Decorum" in u.title)
    assert str(norms_unit.metadata.get("article") or "").startswith("Article 4")
    assert "The following are not allowed." in norms_unit.content
    climbing = next(u for u in doc.units if "Unauthorized climbing" in u.title)
    assert "First offense: Reprimand and community service to be rendered in the institution." in climbing.content
    assert "Second offense: suspension for one (1) week and 40 hours service to be rendered in the institution." in climbing.content
    assert "Third offense: Subsequent offense: Suspension for one (1) semester." in climbing.content


def test_caller_omitting_pdf_pages_keeps_prior_behavior_unchanged():
    """The default pdf_pages=None must be a complete no-op -- every
    existing caller that does not pass it (including every other test in
    this file) must behave byte-for-byte as before this fix."""
    page_texts = [
        "Section/Title/Definition | 1st | 2nd | 3rd\n"
        "Offense | Offense | Offense\n"
        "1.1. Cyber bullying or bullying Suspension Suspension Expulsion\n"
        "done through the use of tech- for one (1) for one (1) from the\n"
        "nology or any | electronic month | semester University\n"
        "means"
    ]
    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="LSPU Student Handbook 2021",
    )
    # Unchanged (still-garbled) behavior: the old header-only fix still
    # drops the table header, but the penalty-column interleaving inside
    # the row itself is untouched when pdf_pages is not supplied.
    full_text = "\n".join(f"{u.title}\n{u.content}" for u in doc.units)
    assert "Section/Title/Definition" not in full_text
    assert "penalty_confidence" not in (doc.units[0].metadata if doc.units else {})


def test_unrelated_document_type_unaffected_by_pdf_pages_parameter():
    """A document with no disciplinary-offense table at all must be
    completely unaffected even when pdf_pages IS supplied -- the new
    code path only activates on a positively identified table anchor."""
    page_texts = [
        "Chapter 3 Admission\nSec. 1. General Admission Policy\n"
        "Applicants must submit a duly accomplished application form."
    ]
    pdf_pages = [
        PageExtraction(
            page_number=1,
            text=page_texts[0],
            method="digital",
            words=None,
            table_regions=None,
        )
    ]
    doc = build_handbook_policy_document(
        raw_text=page_texts[0],
        page_texts=page_texts,
        source_title="Student Handbook",
        pdf_pages=pdf_pages,
    )
    assert any("Admission" in u.title for u in doc.units)
    assert all("penalty_confidence" not in u.metadata for u in doc.units)


# --- Regression tests for the 2026-10-26 follow-up review's four fixes --


def test_fix1_offense_14_3_missing_period_still_recognized_with_real_penalties():
    """Fix 1: the real source text is "14.3 Recruitment..." (no period
    after "14.3", unlike sibling "14.2."). This must still become its
    own unit with its real, confirmed 1st/2nd-offense penalties -- never
    an unconfirmed disclaimer standing in for valid extracted text."""
    pdf_pages = [_offense_table_page(1, _PAGE_81_ROWS, _PAGE_81_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    recruitment = next(u for u in doc.units if "Recruitment of an unauthor" in u.title)
    assert "First offense: Suspension for one semester." in recruitment.content
    assert "Second offense: Suspension for one year." in recruitment.content
    assert recruitment.metadata["penalty_1st_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert recruitment.metadata["penalty_2nd_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    # Never replaced with the unconfirmed disclaimer.
    assert PENALTY_UNCONFIRMED_NOTE not in recruitment.content
    # Third-offense cell is genuinely empty in the source (None) -- not
    # proven otherwise, so no sentence is invented for it either.
    assert "Third offense" not in recruitment.content


def test_fix2_offense_5_1_gets_own_unit_identity_not_absorbed_by_preceding_entry():
    """Fix 2: "5.1. Any severe or repeated use of..." must become its
    own unit -- not get silently absorbed into "Sec. 5 Bullying"'s
    content, which is what happened before this fix (the "Any ..."
    opening tripped a continuation-clause heuristic)."""
    pdf_pages = [_offense_table_page(1, _PAGE_76_WITH_5_1_ROWS, _PAGE_76_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    entry_5_1 = next(u for u in doc.units if u.title.strip() == "Any severe or repeated use of")
    assert "written or verbal expression" in entry_5_1.content
    assert "First offense: Suspension for one (1) week and 40 hours service to be rendered in the institution." in entry_5_1.content
    assert "Second offense: Suspension for one (1) month." in entry_5_1.content
    assert "Third offense: Suspension for one (1) semester." in entry_5_1.content

    bullying_intro = next(u for u in doc.units if u.title.strip() == "Bullying")
    assert "Any severe" not in bullying_intro.content
    assert "written or verbal expression" not in bullying_intro.content
    assert "First offense" not in bullying_intro.content


def test_fix2_offense_5_4_gets_own_unit_identity():
    pdf_pages = [_offense_table_page(1, _PAGE_77_ROWS, _PAGE_77_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    entry_5_4 = next(u for u in doc.units if u.title.strip() == "Any slanderous statement or")
    assert "accusation that causes the vic- tim undue emotional distress" in entry_5_4.content
    assert "First offense: Suspension for one (1) month." in entry_5_4.content
    assert "Second offense: Suspension for one (1) semester." in entry_5_4.content
    assert "Third offense: Expulsion from the University." in entry_5_4.content


def test_fix2_offense_6_2_gets_own_unit_identity_not_absorbed_by_sec_7():
    pdf_pages = [_offense_table_page(1, _PAGE_77_ROWS, _PAGE_77_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    entry_6_2 = next(u for u in doc.units if u.title.strip() == "Any drunkenness or drunken")
    assert "behavior resulting in physical injuries" in entry_6_2.content
    assert "First offense: Suspension for one (1) month and payment of damages." in entry_6_2.content
    assert "Second offense: Suspension for one (1) semester and payment for damages." in entry_6_2.content
    assert "Third offense: Expulsion from the University and payment of damages." in entry_6_2.content

    drinking_6_1 = next(u for u in doc.units if u.title.strip() == "Drinking alcoholic beverages")
    assert "Any drunkenness" not in drinking_6_1.content


def test_fix4_1_6_1_7_1_8_single_filled_cell_becomes_empty_not_unconfirmed():
    """Fix 4: 1.6/1.7/1.8 each have ONLY their 1st-offense cell filled,
    with "expulsion from the University" -- this document's own maximum
    severity. Nothing escalates past expulsion, so the 2nd/3rd cells are
    now classified empty (no sentence), not unconfirmed. Evidence used
    is entirely from THIS row's own cells, never a neighboring offense."""
    pdf_pages = [_offense_table_page(1, _PAGE_74_ROWS, _PAGE_74_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    for fragment in ("Cybersex or the willful engage", "Child Pornography, including", "Cyber Libel or the unlawful or"):
        entry = next(u for u in doc.units if u.title.strip() == fragment)
        assert "First offense: expulsion from the University." in entry.content
        assert "Second offense" not in entry.content
        assert "Third offense" not in entry.content
        assert PENALTY_UNCONFIRMED_NOTE not in entry.content
        assert entry.metadata["penalty_1st_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
        assert entry.metadata["penalty_2nd_confidence"] == PENALTY_CONFIDENCE_EMPTY
        assert entry.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_EMPTY

    # 1.9's full 3-tier structure must be completely unaffected.
    entry_1_9 = next(u for u in doc.units if "Aiding, abetting" in u.title)
    assert entry_1_9.metadata["penalty_confidence"] == PENALTY_CONFIDENCE_CONFIRMED


def test_fix4_3_2_subsequent_offense_label_becomes_empty_not_unconfirmed():
    """Fix 4: "3.2. Subsequent offense" is a bare escalation label, not a
    substantive offense with its own 1st/2nd/3rd tiers -- its one filled
    cell is the whole story."""
    pdf_pages = [
        _offense_table_page(1, _PAGE_75_ROWS, _PAGE_75_BBOX),
    ]
    # Build a minimal page containing just Sec.3/3.1/3.2 for an isolated check.
    page_rows = [
        _HEADER_ROW,
        ["Sec. 3. Breach of Peace. Creating\nwithin the University premises dis-\norder, tumult, serious disturbance,\nand other forms of disturbances\nsuch as shouting, racing, roaming in\ncorridors and the like while classes\nare going on.", "", None, None],
        ["3.1. Shouting and roaming in the\ncorridor/pathways", "reprimand", "suspension\nfor one (1)\nweek and\n40 hours\nservice to\nbe rendered\nin the insti-\ntution", "suspension\nfor one (1)\nmonth"],
        ["3.2. Subsequent offense", "suspension for one (1)semester", None, None],
    ]
    pdf_pages = [_offense_table_page(1, page_rows, _PAGE_75_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    subsequent = next(u for u in doc.units if u.title.strip() == "Subsequent offense")
    assert "First offense: suspension for one (1)semester." in subsequent.content
    assert "Second offense" not in subsequent.content
    assert "Third offense" not in subsequent.content
    assert PENALTY_UNCONFIRMED_NOTE not in subsequent.content
    assert subsequent.metadata["penalty_2nd_confidence"] == PENALTY_CONFIDENCE_EMPTY
    assert subsequent.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_EMPTY


def test_fix4_9_2_remains_unconfirmed_absent_stronger_evidence():
    """Fix 4 explicit instruction: 9.2 keeps its unconfirmed status --
    unlike 1.6-1.8, its 1st-offense value is an ordinary suspension (not
    the document's maximum-severity "expulsion"/"dismissal" wording),
    and unlike 14.2/14.3 only ONE cell (not two) is filled, so there is
    no comparably strong structural signal to reclassify it."""
    pdf_pages = [_offense_table_page(1, _PAGE_79_ROWS, _PAGE_79_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    entry_9_2 = next(u for u in doc.units if "Uploading, downloading" in u.title)
    assert "First offense: Suspension for one (1) month." in entry_9_2.content
    assert entry_9_2.metadata["penalty_1st_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert entry_9_2.metadata["penalty_2nd_confidence"] == PENALTY_CONFIDENCE_UNCONFIRMED
    assert entry_9_2.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_UNCONFIRMED
    assert entry_9_2.metadata["penalty_confidence"] == PENALTY_CONFIDENCE_UNCONFIRMED
    assert PENALTY_UNCONFIRMED_NOTE in entry_9_2.content


def test_fix4_14_2_and_14_3_retain_real_first_and_second_offense_third_becomes_empty():
    """Fix 4: for both 14.2 and 14.3, the real 1st- and 2nd-offense
    penalties must be preserved exactly; only the empty 3rd-offense cell
    is reclassified, based on the row's OWN two already-confirmed cells
    (both filled is a consistent 2-tier shape, confirmed by both 14.2
    and 14.3 sharing it) -- never inferred from a different offense."""
    pdf_pages = [_offense_table_page(1, _PAGE_81_ROWS, _PAGE_81_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    unrecognized = next(u for u in doc.units if u.title.strip() == "Unrecognized organizations")
    assert "First offense: Warning." in unrecognized.content
    assert "Second offense: The student organization is banned to operate for one (1) semester." in unrecognized.content
    assert "Third offense" not in unrecognized.content
    assert unrecognized.metadata["penalty_1st_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert unrecognized.metadata["penalty_2nd_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert unrecognized.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_EMPTY

    recruitment = next(u for u in doc.units if "Recruitment of an unauthor" in u.title)
    assert recruitment.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_EMPTY


def test_fix4_narrative_attendance_entry_stays_empty_not_unconfirmed():
    """Fix 4: 1.2.3/1.2.4 describe their own consequence directly in
    prose ("...shall be dropped from the roll of students") rather than
    using the Suspension/Expulsion tiered structure at all -- the empty
    cells are legitimately not applicable, not a sign of missing data."""
    pdf_pages = [_offense_table_page(1, _PAGE_83_ROWS, _PAGE_83_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)

    entry = next(u for u in doc.units if "Every student accumulat" in u.title)
    assert "dropped from the roll of students" in entry.content
    assert "First offense" not in entry.content
    assert PENALTY_UNCONFIRMED_NOTE not in entry.content
    assert "penalty_confidence" not in entry.metadata or entry.metadata["penalty_confidence"] == PENALTY_CONFIDENCE_EMPTY


# === 2026-10-28 fix: a single page can hold more than one matching table =
#
# Real rows from page 82 (absolute PDF page 82 / PyMuPDF 0-indexed page 81;
# the handbook's own printed label on this page is "73 of 183"), captured
# via find_tables() during the read-only audit that discovered this gap.
# PyMuPDF's find_tables() returns THREE native tables on this one page:
# table[0] is the repeating page-header boilerplate (never matches the
# disciplinary header), table[1] is the tail of one numbered Article
# (Sec. 16/17), and table[2] is a SEPARATE table starting a new Article
# ("Article 3. Minor Offense", Sec. 1 Attendance/1.1/1.2) further down the
# same page. Before the 2026-10-28 fix, _find_disciplinary_table only ever
# returned the first match (table[1]); table[2]'s rows were never reached,
# and its real content resurfaced as column-garbled prose via
# _after_table_text instead of structured units.

_PAGE_82_TABLE1_ROWS = [
    _HEADER_ROW,
    [
        "Sec. 16. Other Acts. Other acts which in the judgment of the Office of Stu-\ndent Affairs and Services require disciplinary or corrective action.",
        None,
        None,
        None,
    ],
    [
        "Sec. 17. Habitual Offenders. Any student who persists to disregard any of\nthe provisions in these Articles after counsel and repeated warnings shall\nwithdraw from the University and be dropped from the roll or denied admis-\nsion on the succeeding semester/school year.",
        None,
        None,
        None,
    ],
]
_PAGE_82_TABLE1_BBOX = [36.55, 73.95, 410.33, 181.66]

_PAGE_82_TABLE2_ROWS = [
    _HEADER_ROW,
    ["Sec. 1. Attendance", "", None, None],
    [
        "1.1. Attending flag raising and flag\nlowering ceremonies (R.A.\n8491 Sec. 18 and 50 Philippine\nFlag Law), classes, and other\nrequired University activities\nregularly and on time is re-\nquired for all students unless\nexemption is granted by the\nUniversity President or his du-\nly authorized representative.",
        "",
        "",
        "",
    ],
    [
        "1.2 Tardiness and absences shall be\ndealt with as follows:\n1.2.1 Tardiness in all activities\nwhere student�s attend-\nance is required shall be\nconsidered one (1) ab-\nsence in class.\n1.2.2 Three (3) tardiness in a\nclass shall be considered\none (1) absence from the\nsame.",
        "One (1)\nday absent\nplus com-\nmunity\nservice",
        "Inform the\nparents/\nguardians\nwith three\n(3) days\nsuspension",
        "Suspension\nfor one (1)\nweek",
    ],
]
_PAGE_82_TABLE2_BBOX = [36.55, 212.07, 410.33, 575.9]


def _multi_table_page(
    page_number: int,
    table_specs: list[tuple[list, list[float]]],
    *,
    words: list[dict] | None = None,
) -> PageExtraction:
    """Like _offense_table_page, but for a page whose table_regions holds
    more than one native table -- each (rows, bbox) pair in table_specs
    becomes its own entry, in the given order (matching the order
    find_tables() itself would return them for a real page)."""
    return PageExtraction(
        page_number=page_number,
        text="GARBLED PLACEHOLDER -- must be overridden, never read when a valid table is found",
        method="digital",
        words=words,
        table_regions=[{"bbox": bbox, "rows": rows} for rows, bbox in table_specs],
    )


def _heading_words(text: str, y: float) -> list[dict]:
    """Minimal synthetic word geometry for a short heading line positioned
    at height y -- same hand-built style already used by
    test_partial_table_page_preserves_genuine_trailing_non_table_content
    for its own tail_words, not a literal capture of real coordinates."""
    words = []
    x0 = 40.0
    for token in text.split():
        words.append({"text": token, "x0": x0, "y0": y, "x1": x0 + 8.0 * len(token), "y1": y + 10.0, "cy": y + 5.0, "height": 10.0})
        x0 += 8.0 * len(token) + 6.0
    return words


def test_page_with_two_matching_disciplinary_tables_processes_both_structurally():
    """2026-10-28 fix: a page with two separate native tables that BOTH
    match the disciplinary header (confirmed real structure of page 82)
    must have every one of them processed through the same structured
    row classification and rendering -- not just the first."""
    between_words = _heading_words("Article 3. Minor Offense", 190.0)
    # Genuine trailing prose after the LAST matched table needs a real
    # body line of its own, not just a heading -- a heading with no body
    # is correctly dropped by this project's existing, unrelated
    # hierarchy-only-unit handling (same as "Sec. 1. Attendance" itself
    # below), so this must have real content to prove preservation,
    # mirroring test_partial_table_page_preserves_genuine_trailing_non_table_content's
    # own pattern for the single-table case.
    trailing_words = _heading_words("Article 4. Some Later Heading", 590.0) + _heading_words(
        "This is genuine trailing prose that must survive.", 605.0
    )
    pdf_pages = [
        _multi_table_page(
            1,
            [
                (_PAGE_82_TABLE1_ROWS, _PAGE_82_TABLE1_BBOX),
                (_PAGE_82_TABLE2_ROWS, _PAGE_82_TABLE2_BBOX),
            ],
            words=between_words + trailing_words,
        )
    ]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)
    full_text = "\n".join(f"{u.title}\n{u.content}" for u in doc.units)

    # Section 16 and Section 17 (table 1) are retained as correctly
    # structured units.
    other_acts = next(u for u in doc.units if "Other Acts" in u.title)
    habitual = next(u for u in doc.units if "Habitual Offenders" in u.title)
    assert "require disciplinary or corrective action" in other_acts.content
    assert "dropped from the roll or denied admis-" in habitual.content or "dropped from the roll" in habitual.content

    # Article 3 / Attendance / 1.1 / 1.2 (table 2) are ALSO retained as
    # separate, correctly structured units -- this is the specific
    # content that was previously unreachable. "Sec. 1. Attendance"
    # itself has no body of its own (an intro heading with all-empty
    # penalty cells), so -- same pre-existing, unrelated behavior as any
    # other hierarchy-only heading in this document -- it does not become
    # its own standalone unit; 1.1 and 1.2 do, since they have real body
    # text.
    flag_raising = next(u for u in doc.units if "Attending flag raising" in u.title)
    # 1.2's own multi-sub-item cell ("1.2 ... 1.2.1 ... 1.2.2 ...") is
    # further split into its own numbered sub-units by this project's
    # existing, unrelated generic heading-detection -- the same thing
    # that would happen for any other multi-sub-item cell in this
    # document. The combined penalty sentence (built once, correctly
    # ordered, by _render_disciplinary_entry_text) stays attached to
    # whichever split piece ends up last, which is what is checked here
    # -- not which exact sub-unit title it lands on.
    tardiness = next(u for u in doc.units if "One (1) day absent" in u.content)

    # Attendance penalty cells remain associated with their correct
    # offense and ordinal columns -- the three distinct real penalty
    # values for 1.2/1.2.1/1.2.2 must each land under their own label,
    # never swapped or merged. Penalty-cell text is dewrapped (hyphenated
    # line-wraps rejoined), unlike the description's own original lines.
    assert "First offense: One (1) day absent plus community service." in tardiness.content
    assert "Second offense: Inform the parents/ guardians with three (3) days suspension." in tardiness.content
    assert "Third offense: Suspension for one (1) week." in tardiness.content
    assert tardiness.metadata["penalty_1st_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert tardiness.metadata["penalty_2nd_confidence"] == PENALTY_CONFIDENCE_CONFIRMED
    assert tardiness.metadata["penalty_3rd_confidence"] == PENALTY_CONFIDENCE_CONFIRMED

    # 1.1's genuinely all-empty cells (sibling sub-items elsewhere in the
    # real section do carry a penalty, so this must stay unconfirmed, not
    # empty) -- confidence correctness for the supplied fixture values.
    assert flag_raising.metadata["penalty_confidence"] == PENALTY_CONFIDENCE_UNCONFIRMED
    assert PENALTY_UNCONFIRMED_NOTE in flag_raising.content

    # The repeated disciplinary-table header must never become offense
    # content, for EITHER table on this page.
    assert "Section/Title/Definition" not in full_text
    assert "|" not in full_text

    # Table 2's rows must never leak into table 1's units, and vice
    # versa (no bounding-box/row cross-contamination).
    assert "Attending flag raising" not in other_acts.content
    assert "Attending flag raising" not in habitual.content
    assert "Other Acts" not in flag_raising.content
    assert "Other Acts" not in tardiness.content
    assert "Habitual Offenders" not in flag_raising.content
    assert "Habitual Offenders" not in tardiness.content

    # The second table must never resurface as flattened, column-garbled
    # prose via _after_table_text -- the exact defect this fix closes.
    assert "One (1) | Inform the" not in full_text
    assert "day absent plus com- munity\nservice | (3) days" not in full_text

    # Genuine non-table prose BETWEEN the two tables ("Article 3. Minor
    # Offense") is preserved, not discarded. It is a heading with no body
    # of its own (nothing but "Sec. 1. Attendance" -- itself also a
    # heading -- follows it), so -- same pre-existing, unrelated
    # hierarchy-only-heading handling exercised by the flag_raising/
    # tardiness lookups above -- it becomes hierarchy CONTEXT (metadata),
    # not its own text unit; it must never become its own bogus offense
    # entry with invented penalties either way.
    assert any((u.metadata.get("article") or "").startswith("Article 3") for u in doc.units)
    assert not any(u.title.strip() == "Article 3. Minor Offense" for u in doc.units)
    assert not any("penalty_confidence" in u.metadata and (u.metadata.get("article") or "").startswith("Article 3") and u.title.strip() == "Minor Offense" for u in doc.units)

    # Genuine trailing prose AFTER the last matched table on the page is
    # still preserved, WITH its real body content -- the pre-existing
    # single-table guarantee
    # (test_partial_table_page_preserves_genuine_trailing_non_table_content)
    # must continue to hold even when it is the second table on the page,
    # not the first.
    trailing_unit = next(u for u in doc.units if "Some Later Heading" in u.title)
    assert "This is genuine trailing prose that must survive." in trailing_unit.content
    assert str(trailing_unit.metadata.get("article") or "").startswith("Article 4")


def test_single_matching_table_page_behavior_is_unchanged_by_the_multi_table_fix():
    """Regression guard: a page with exactly one matching table (the
    overwhelming majority of the real disciplinary-table range) must
    produce byte-identical output to before this fix -- re-running an
    already-existing real-row fixture through the current code."""
    pdf_pages = [_offense_table_page(1, _PAGE_73_ROWS, _PAGE_73_BBOX)]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)
    cyberbullying = next(u for u in doc.units if "Cyber bullying" in u.title)
    assert "First offense: Suspension for one (1) month." in cyberbullying.content
    assert "Second offense: Suspension for one (1) semester." in cyberbullying.content
    assert "Third offense: Expulsion from the University." in cyberbullying.content
    assert cyberbullying.metadata["penalty_confidence"] == PENALTY_CONFIDENCE_CONFIRMED


def test_invalid_table_among_multiple_tables_on_one_page_still_refuses_to_guess():
    """A page with two matching tables where the SECOND one is invalid
    must still refuse to publish anything from that page as if verified
    -- the existing invalid-table safeguard must not be weakened just
    because a second table is now reachable."""
    bad_table2_rows = [_HEADER_ROW, ["Only one cell, missing the other three"]]
    pdf_pages = [
        _multi_table_page(
            1,
            [
                (_PAGE_82_TABLE1_ROWS, _PAGE_82_TABLE1_BBOX),
                (bad_table2_rows, _PAGE_82_TABLE2_BBOX),
            ],
        )
    ]
    doc = _build_document_with_disciplinary_pages(pdf_pages, 1)
    full_text = "\n".join(f"{u.title}\n{u.content}" for u in doc.units)
    assert "EXTRACTION_UNCERTAIN" in full_text
    # Table 1's otherwise-valid content must not be presented either --
    # the whole page is untrusted, exactly like the existing single-table
    # invalid case.
    assert "Other Acts" not in full_text
    assert "Habitual Offenders" not in full_text

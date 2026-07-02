from app.services.handbook_policy_processor import (
    HandbookKnowledgeUnit,
    build_handbook_policy_document,
    is_handbook_policy_text,
    _filter_non_knowledge_units,
)
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

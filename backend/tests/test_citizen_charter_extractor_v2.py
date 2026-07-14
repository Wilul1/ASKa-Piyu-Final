"""Tests for the standalone Citizen's Charter Extraction V2 module (Phase B).

Phase B is intentionally isolated: these tests exercise
`citizen_charter_extractor_v2` directly and do not touch Generate Articles,
structured_document_parser, knowledge units, the public KB, or ChromaDB.
"""

from __future__ import annotations

from app.services.citizen_charter_extractor_v2 import (
    NEEDS_REVIEW,
    PARSER_STRATEGY_GEOMETRY,
    PARSER_STRATEGY_TEXT_FALLBACK,
    RequirementV2,
    StepV2,
    _is_fake_row,
    _line_is_heading_candidate,
    _looks_like_field_or_fragment_line,
    _merge_wrapped_rows,
    _score_extraction_quality,
    _split_total_line,
    extract_citizen_charter_services_v2,
)
from app.utils.pdf.pymupdf_extractor import PageExtraction


def _word(text: str, x0: float, y0: float, x1: float, y1: float) -> dict:
    return {
        "text": text,
        "x0": float(x0),
        "y0": float(y0),
        "x1": float(x1),
        "y1": float(y1),
        "cy": (float(y0) + float(y1)) / 2,
        "height": max(1.0, float(y1) - float(y0)),
    }


def _row(y: float, cells: list[tuple[str, float, float]]) -> list[dict]:
    """Build word boxes for one visual row. cells = [(text, x0, x1), ...]."""
    return [_word(text, x0, y, x1, y + 20) for text, x0, x1 in cells]


def _build_id_validation_words_v2() -> list[dict]:
    """Careful column-anchored word grid for the ID Validation fixture.

    Column x-ranges are derived from the steps header row gaps:
      client_step  : x0 < 180
      agency_action: 180 <= x0 < 380
      fees         : 380 <= x0 < 490
      processing_time: 490 <= x0 < 665
      person_responsible: x0 >= 665
    """
    words: list[dict] = []

    words += _row(20, [("4.", 50, 70), ("ID", 80, 110), ("Validation", 115, 200)])

    words += _row(
        60,
        [
            ("Office", 50, 90),
            ("/", 95, 105),
            ("Division:", 110, 180),
            ("Office", 400, 440),
            ("of", 445, 465),
            ("the", 470, 495),
            ("Student", 500, 560),
            ("Affairs", 565, 620),
            ("and", 625, 655),
            ("Services", 660, 730),
        ],
    )
    words += _row(100, [("Classification:", 50, 180), ("Simple", 400, 460)])
    words += _row(
        140,
        [
            ("Transaction", 50, 120),
            ("Type:", 125, 180),
            ("G2C", 400, 430),
            ("\u2013", 435, 445),
            ("Government", 450, 530),
            ("to", 535, 550),
            ("Citizen", 555, 610),
        ],
    )
    words += _row(180, [("Who", 50, 80), ("May", 85, 115), ("Avail:", 120, 170), ("All", 400, 420)])

    words += _row(
        220,
        [
            ("Checklist", 50, 120),
            ("of", 125, 140),
            ("Requirements", 145, 240),
            ("Where", 400, 440),
            ("to", 445, 460),
            ("Secure", 465, 520),
        ],
    )
    words += _row(
        250,
        [
            ("Certificate", 50, 140),
            ("of", 145, 160),
            ("Registration", 165, 260),
            ("Registrar's", 400, 470),
            ("Office", 475, 530),
        ],
    )
    words += _row(
        280,
        [
            ("Student", 50, 110),
            ("ID", 115, 135),
            ("Business", 400, 460),
            ("Affairs", 465, 520),
            ("Office", 525, 580),
        ],
    )

    words += _row(
        320,
        [
            ("Client", 50, 90),
            ("Step", 95, 130),
            ("Agency", 230, 280),
            ("Action", 285, 340),
            ("Fees", 420, 460),
            ("Processing", 520, 590),
            ("Time", 595, 630),
            ("Person", 700, 750),
            ("Responsible", 755, 840),
        ],
    )

    words += _row(
        360,
        [
            ("Present", 50, 65),
            ("the", 70, 85),
            ("Certificate", 90, 105),
            ("of", 110, 120),
            ("Registration.", 125, 140),
            ("Check", 200, 215),
            ("Certificate", 220, 235),
            ("of", 240, 250),
            ("Registration.", 255, 270),
            ("None", 400, 430),
            ("1", 500, 505),
            ("minute", 515, 555),
            ("OSAS", 680, 710),
            ("Director/Chairperson/Staff", 715, 900),
        ],
    )
    words += _row(
        400,
        [
            ("Evaluate", 50, 65),
            ("the", 70, 85),
            ("services", 90, 105),
            ("rendered", 110, 125),
            ("by", 130, 140),
            ("OSAS.", 145, 160),
            ("Issue", 200, 215),
            ("Evaluation", 220, 250),
            ("Form.", 255, 280),
            ("None", 400, 430),
            ("2", 500, 505),
            ("minutes", 515, 560),
            ("OSAS", 680, 710),
            ("Director/Chairperson/Staff", 715, 900),
        ],
    )
    words += _row(
        440,
        [
            ("Accept", 50, 65),
            ("the", 70, 85),
            ("validated", 90, 110),
            ("ID.", 115, 130),
            ("Release", 200, 220),
            ("validated", 225, 245),
            ("ID.", 250, 265),
            ("None", 400, 430),
            ("1", 500, 505),
            ("minute", 515, 555),
            ("OSAS", 680, 710),
            ("Director/Chairperson/Staff", 715, 900),
        ],
    )

    words += _row(480, [("TOTAL:", 50, 100), ("None", 110, 150), ("4", 160, 175), ("minutes", 180, 235)])

    return words


def _id_validation_page() -> PageExtraction:
    return PageExtraction(
        page_number=1,
        text="",
        method="digital",
        words=_build_id_validation_words_v2(),
        geometry_scale=1.0,
    )


def test_id_validation_extraction_matches_target_output():
    services = extract_citizen_charter_services_v2([_id_validation_page()])
    assert len(services) == 1
    service = services[0]

    assert service.service_title == "ID Validation"
    assert service.office_division == "Office of the Student Affairs and Services"
    assert service.classification == "Simple"
    assert service.transaction_type == "G2C \u2013 Government to Citizen"
    assert service.who_may_avail == "All"

    assert len(service.requirements) == 2
    assert service.requirements[0] == RequirementV2(
        requirement="Certificate of Registration", where_to_secure="Registrar's Office"
    )
    assert service.requirements[1] == RequirementV2(
        requirement="Student ID", where_to_secure="Business Affairs Office"
    )

    assert len(service.steps) == 3
    step1, step2, step3 = service.steps
    assert step1.client_step == "Present the Certificate of Registration."
    assert step1.agency_action == "Check Certificate of Registration."
    assert step1.fees == "None"
    assert step1.processing_time == "1 minute"
    assert step1.person_responsible == "OSAS Director/Chairperson/Staff"

    assert step2.client_step == "Evaluate the services rendered by OSAS."
    assert step2.agency_action == "Issue Evaluation Form."
    assert step2.processing_time == "2 minutes"

    assert step3.client_step == "Accept the validated ID."
    assert step3.agency_action == "Release validated ID."
    assert step3.processing_time == "1 minute"

    assert service.total_fees == "None"
    assert service.total_processing_time == "4 minutes"

    assert service.extraction_quality == "clean"
    assert service.page_start == 1
    assert service.page_end == 1

    debug = service.parser_debug
    assert debug["parser_strategy_used"] == PARSER_STRATEGY_GEOMETRY
    assert debug["table_extraction_method"] == "requirements_and_steps_tables"
    assert debug["detected_service_title"] == "ID Validation"
    assert len(debug["detected_requirements"]) == 2
    assert debug["detected_step_row_count"] == 3
    assert isinstance(debug["detected_step_rows"], list)
    assert len(debug["detected_step_rows"]) == 3
    assert debug["extraction_quality"] == "clean"


def test_fragment_titles_are_rejected_as_service_headings():
    junk_titles = [
        "DS REVIEW]",
        "Interview of reference",
        "ID or Registration Cards/",
        "Government to Citizen",
        "Once approved, the client prepares the document for application, including",
    ]
    for title in junk_titles:
        assert _looks_like_field_or_fragment_line(title) is True

    # Also confirm the good title stays valid.
    assert _looks_like_field_or_fragment_line("ID Validation") is False


def test_fragment_headings_do_not_split_the_real_service_block():
    lines = [
        {"page": 1, "text": "1. DS REVIEW]", "words": None, "strategy": PARSER_STRATEGY_TEXT_FALLBACK},
        {
            "page": 1,
            "text": "2. Interview of reference",
            "words": None,
            "strategy": PARSER_STRATEGY_TEXT_FALLBACK,
        },
        {
            "page": 1,
            "text": "3. ID or Registration Cards/",
            "words": None,
            "strategy": PARSER_STRATEGY_TEXT_FALLBACK,
        },
        {"page": 1, "text": "4. Government to Citizen", "words": None, "strategy": PARSER_STRATEGY_TEXT_FALLBACK},
        {
            "page": 1,
            "text": "5. Once approved, the client prepares the document for application, including",
            "words": None,
            "strategy": PARSER_STRATEGY_TEXT_FALLBACK,
        },
        {"page": 1, "text": "6. ID Validation", "words": None, "strategy": PARSER_STRATEGY_TEXT_FALLBACK},
        {
            "page": 1,
            "text": "Office / Division: Office of the Student Affairs and Services",
            "words": None,
            "strategy": PARSER_STRATEGY_TEXT_FALLBACK,
        },
        {"page": 1, "text": "Classification: Simple", "words": None, "strategy": PARSER_STRATEGY_TEXT_FALLBACK},
        {
            "page": 1,
            "text": "Type of Transaction: G2C – Government to Citizen",
            "words": None,
            "strategy": PARSER_STRATEGY_TEXT_FALLBACK,
        },
        {"page": 1, "text": "Who May Avail: All", "words": None, "strategy": PARSER_STRATEGY_TEXT_FALLBACK},
        {
            "page": 1,
            "text": "Checklist of Requirements | Where to Secure",
            "words": None,
            "strategy": PARSER_STRATEGY_TEXT_FALLBACK,
        },
        {"page": 1, "text": "TOTAL: None 1 minute", "words": None, "strategy": PARSER_STRATEGY_TEXT_FALLBACK},
    ]

    for idx in range(5):
        assert _line_is_heading_candidate(idx, lines) is None
    assert _line_is_heading_candidate(5, lines) == "ID Validation"


def test_fake_header_remnant_rows_are_rejected():
    assert _is_fake_row(("BE", "TIME", "RESPONSIBLE", "PAID", "FEES")) is True
    assert _is_fake_row(("CLIENT STEPS", "AGENCY ACTIONS", "", "", "PERSON RESPONSIBLE")) is True
    assert _is_fake_row(("", "", "", "", "")) is True
    assert _is_fake_row(("Present the ID", "Verify the ID", "None", "1 minute", "Staff")) is False


def test_fake_step_row_dropped_from_extraction_and_captured_in_rejected_fragments():
    words = _build_id_validation_words_v2()
    # Insert a fake header-remnant row between step 1 and step 2.
    fake_row = _row(
        380,
        [
            ("BE", 200, 220),
            ("TIME", 500, 520),
            ("RESPONSIBLE", 680, 730),
        ],
    )
    page = PageExtraction(
        page_number=1, text="", method="digital", words=[*words, *fake_row], geometry_scale=1.0
    )

    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    service = services[0]

    # The fake row must not appear as a 4th step.
    assert len(service.steps) == 3
    assert all("BE" not in step.agency_action for step in service.steps)


def test_requirements_and_steps_are_not_confused():
    services = extract_citizen_charter_services_v2([_id_validation_page()])
    service = services[0]

    requirement_texts = {item.requirement for item in service.requirements}
    step_client_texts = {step.client_step for step in service.steps}

    assert "Certificate of Registration" in requirement_texts
    assert "Student ID" in requirement_texts
    assert not requirement_texts & step_client_texts

    step_agency_texts = {step.agency_action for step in service.steps}
    assert "Check Certificate of Registration." in step_agency_texts
    assert "Present the Certificate of Registration." not in requirement_texts


def test_total_line_fee_and_time_split():
    assert _split_total_line("None | 4 minutes") == ("None", "4 minutes")
    assert _split_total_line("P30.00/unit 25 minutes") == ("P30.00/unit", "25 minutes")
    assert _split_total_line("1-3 days, 1 hr and 45 minutes")[1] == "1-3 days, 1 hr and 45 minutes"


def test_placeholder_only_service_is_low_quality_or_rag_only():
    quality, reason = _score_extraction_quality(
        service_title="Some Service",
        office_division=NEEDS_REVIEW,
        classification=NEEDS_REVIEW,
        transaction_type=NEEDS_REVIEW,
        who_may_avail=NEEDS_REVIEW,
        requirements=[],
        steps=[],
        total_processing_time=NEEDS_REVIEW,
    )
    assert quality == "rag_only"
    assert reason == "placeholder_only_body"

    quality2, reason2 = _score_extraction_quality(
        service_title="Some Service",
        office_division="Office of the Registrar",
        classification=NEEDS_REVIEW,
        transaction_type=NEEDS_REVIEW,
        who_may_avail=NEEDS_REVIEW,
        requirements=[],
        steps=[],
        total_processing_time=NEEDS_REVIEW,
    )
    assert quality2 == "low_quality"
    assert reason2 == "no_requirements_or_steps"


def test_fallback_strategy_used_when_words_are_missing():
    text = "\n".join(
        [
            "4. Simple Renewal",
            "Office / Division: Office of the Registrar",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who May Avail: All",
            "Checklist of Requirements | Where to Secure",
            "Valid ID | Client",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "Present ID | Verify ID | None | 1 minute | Registrar Staff",
            "TOTAL: None 1 minute",
        ]
    )
    page = PageExtraction(page_number=1, text=text, method="digital", words=None, geometry_scale=1.0)

    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    service = services[0]

    assert service.parser_debug["parser_strategy_used"] == PARSER_STRATEGY_TEXT_FALLBACK
    assert service.service_title == "Simple Renewal"
    assert service.office_division == "Office of the Registrar"
    assert service.classification == "Simple"
    assert service.who_may_avail == "All"
    assert len(service.requirements) == 1
    assert service.requirements[0].requirement == "Valid ID"
    assert service.requirements[0].where_to_secure == "Client"
    assert len(service.steps) == 1
    assert service.steps[0].client_step == "Present ID"
    assert service.steps[0].agency_action == "Verify ID"
    assert service.total_processing_time == "1 minute"
    assert service.extraction_quality == "clean"


def test_merge_wrapped_rows_combines_multiline_step_into_one_logical_row():
    rows = [
        ["Present the", "", "", "", ""],
        ["Certificate of Registration.", "", "", "", ""],
        ["", "Check Certificate of Registration.", "None", "1 minute", "OSAS Staff"],
        ["Evaluate the services.", "", "", "", ""],
        ["", "Issue Evaluation Form.", "None", "2 minutes", "OSAS Staff"],
    ]
    merged = _merge_wrapped_rows(rows, primary_idx=[0, 1], secondary_idx=[2, 3, 4])
    assert merged == [
        [
            "Present the Certificate of Registration.",
            "Check Certificate of Registration.",
            "None",
            "1 minute",
            "OSAS Staff",
        ],
        ["Evaluate the services.", "Issue Evaluation Form.", "None", "2 minutes", "OSAS Staff"],
    ]


def test_merge_wrapped_rows_ignores_page_number_secondary_and_keeps_fragments_together():
    """Real-PDF failure mode: page crumbs in fee column must not split wraps."""
    rows = [
        ["Present the", "", "19", "", ""],
        ["Certificate of", "", "", "", ""],
        ["Registration.", "Check Certificate of Registration.", "None", "1 minute", "OSAS Staff"],
        ["Evaluate the", "", "", "", ""],
        ["Services rendered by OSAS.", "Issue Evaluation Form.", "None", "2 minutes", "OSAS Staff"],
        ["Accept the validated ID.", "Release validated ID.", "None", "1 minute", "OSAS Staff"],
    ]
    merged = _merge_wrapped_rows(rows, primary_idx=[0, 1], secondary_idx=[2, 3, 4])
    assert len(merged) == 3
    assert merged[0][0] == "Present the Certificate of Registration."
    assert merged[0][1] == "Check Certificate of Registration."
    assert merged[0][2] == "None"
    assert merged[1][0] == "Evaluate the Services rendered by OSAS."
    assert merged[2][0] == "Accept the validated ID."


def test_id_validation_geometry_fixture_merges_into_exactly_three_complete_steps():
    services = extract_citizen_charter_services_v2([_id_validation_page()])
    assert len(services) == 1
    service = services[0]
    assert service.service_title == "ID Validation"
    assert len(service.steps) == 3
    assert service.steps[0].client_step.startswith("Present the Certificate")
    assert "Check Certificate of Registration." in service.steps[0].agency_action
    assert service.steps[1].client_step.startswith("Evaluate the")
    assert "Issue Evaluation Form." in service.steps[1].agency_action
    assert service.steps[2].client_step.startswith("Accept the validated ID")
    assert "Release validated ID." in service.steps[2].agency_action
    assert all(step.fees == "None" for step in service.steps)
    assert service.total_processing_time == "4 minutes"
    assert service.extraction_quality == "clean"


def test_step_v2_requires_all_fields_for_completeness_check():
    complete = StepV2(
        client_step="Do X",
        agency_action="Check X",
        fees="None",
        processing_time="1 minute",
        person_responsible="Staff",
    )
    quality, _reason = _score_extraction_quality(
        service_title="Sample Service",
        office_division="Office A",
        classification="Simple",
        transaction_type=NEEDS_REVIEW,
        who_may_avail="All",
        requirements=[RequirementV2(requirement="Req A", where_to_secure="Office A")],
        steps=[complete],
        total_processing_time="1 minute",
    )
    assert quality == "clean"


def test_clean_quality_rejects_missing_office_even_if_other_fields_exist():
    quality, reason = _score_extraction_quality(
        service_title="ID Validation",
        office_division=NEEDS_REVIEW,
        classification="Simple",
        transaction_type="G2C",
        who_may_avail="All",
        requirements=[RequirementV2(requirement="Student ID", where_to_secure="BAO")],
        steps=[
            StepV2(
                client_step="Present ID",
                agency_action="Validate ID",
                fees="None",
                processing_time="1 minute",
                person_responsible="Staff",
            )
        ],
        total_processing_time="1 minute",
    )
    assert quality == "needs_review"
    assert reason == "missing_office_division"


def test_clean_quality_rejects_mostly_not_specified_steps():
    quality, reason = _score_extraction_quality(
        service_title="Broken Service",
        office_division="Internal Audit Unit",
        classification="Simple",
        transaction_type="G2C",
        who_may_avail="All",
        requirements=[RequirementV2(requirement="Form", where_to_secure="Office")],
        steps=[
            StepV2(
                client_step="Submit form",
                agency_action=NEEDS_REVIEW,
                fees=NEEDS_REVIEW,
                processing_time=NEEDS_REVIEW,
                person_responsible=NEEDS_REVIEW,
            ),
            StepV2(
                client_step="Wait",
                agency_action=NEEDS_REVIEW,
                fees=NEEDS_REVIEW,
                processing_time=NEEDS_REVIEW,
                person_responsible=NEEDS_REVIEW,
            ),
            StepV2(
                client_step="Claim",
                agency_action="Release",
                fees="None",
                processing_time="1 minute",
                person_responsible="Staff",
            ),
        ],
        total_processing_time="1 minute",
    )
    assert quality == "needs_review"
    assert reason in {
        "excessive_not_specified_fields",
        "no_complete_step_row",
    }


def test_page_number_is_not_parsed_as_fee():
    from app.services.citizen_charter_extractor_v2 import _normalize_fee, _looks_like_page_number_fee

    assert _looks_like_page_number_fee("42") is True
    assert _looks_like_page_number_fee("page 12") is True
    assert _looks_like_page_number_fee("None") is False
    assert _looks_like_page_number_fee("P30.00") is False
    assert _normalize_fee("42") == NEEDS_REVIEW
    assert _normalize_fee("P30.00") == "P30.00"

    quality, reason = _score_extraction_quality(
        service_title="Fee Crumb Service",
        office_division="Office A",
        classification="Simple",
        transaction_type="G2C",
        who_may_avail="All",
        requirements=[RequirementV2(requirement="ID", where_to_secure="Client")],
        steps=[
            StepV2(
                client_step="Present ID",
                agency_action="Check ID",
                fees=NEEDS_REVIEW,
                processing_time="1 minute",
                person_responsible="Staff",
            )
        ],
        total_processing_time="1 minute",
        page_number_fee_hits=1,
    )
    assert quality == "needs_review"
    assert reason == "page_number_used_as_fee"


def test_table_row_fragments_do_not_inflate_service_count():
    """Numbered client-step rows and office-only crumbs must not become services."""
    text = "\n".join(
        [
            "4. ID Validation",
            "Office / Division: Office of the Student Affairs and Services",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who May Avail: All",
            "Checklist of Requirements | Where to Secure",
            "Certificate of Registration | Registrar's Office",
            "Student ID | Business Affairs Office",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "1. Present the Certificate of Registration. | Check Certificate of Registration. | None | 1 minute | OSAS Staff",
            "2. Evaluate the services rendered by OSAS. | Issue Evaluation Form. | None | 2 minutes | OSAS Staff",
            "3. Accept the validated ID. | Release validated ID. | None | 1 minute | OSAS Staff",
            "TOTAL: None 4 minutes",
            "Internal Audit Unit",
            "5. Present the",
            "Check Certificate of Registration.",
            "42",
        ]
    )
    page = PageExtraction(page_number=1, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    service = services[0]
    assert service.service_title == "ID Validation"
    assert len(service.steps) == 3
    assert service.extraction_quality == "clean"
    rejected = " ".join(service.parser_debug.get("rejected_fragments") or [])
    assert "Present the Certificate of Registration" not in rejected
    assert "Evaluate the services rendered by OSAS" not in rejected
    assert "Accept the validated ID" not in rejected


def test_id_validation_rows_stay_on_id_validation_not_other_service_rejects():
    """Two real services: ID Validation steps must not leak into the other service's rejects."""
    text = "\n".join(
        [
            "3. Campus Clearance",
            "Office / Division: Office of the Registrar",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who May Avail: Graduating Students",
            "Checklist of Requirements | Where to Secure",
            "Clearance Form | Registrar's Office",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "Submit clearance form | Receive and check form | None | 5 minutes | Registrar Staff",
            "TOTAL: None 5 minutes",
            "4. ID Validation",
            "Office / Division: Office of the Student Affairs and Services",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who May Avail: All",
            "Checklist of Requirements | Where to Secure",
            "Certificate of Registration | Registrar's Office",
            "Student ID | Business Affairs Office",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "Present the Certificate of Registration. | Check Certificate of Registration. | None | 1 minute | OSAS Director/Chairperson/Staff",
            "Evaluate the services rendered by OSAS. | Issue Evaluation Form. | None | 2 minutes | OSAS Director/Chairperson/Staff",
            "Accept the validated ID. | Release validated ID. | None | 1 minute | OSAS Director/Chairperson/Staff",
            "TOTAL: None 4 minutes",
        ]
    )
    page = PageExtraction(page_number=1, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 2
    by_title = {s.service_title: s for s in services}
    assert "ID Validation" in by_title
    assert "Campus Clearance" in by_title

    id_service = by_title["ID Validation"]
    clearance = by_title["Campus Clearance"]
    assert id_service.extraction_quality == "clean"
    assert id_service.office_division == "Office of the Student Affairs and Services"
    assert len(id_service.steps) == 3
    assert id_service.steps[0].client_step.startswith("Present the Certificate")
    assert id_service.total_processing_time == "4 minutes"

    clearance_rejects = " ".join(clearance.parser_debug.get("rejected_fragments") or [])
    assert "Present the" not in clearance_rejects
    assert "Evaluate the" not in clearance_rejects
    assert "Accept the validated" not in clearance_rejects
    assert "Check Certificate" not in clearance_rejects


def test_rejected_fragments_are_scoped_to_current_service_only():
    text = "\n".join(
        [
            "1. First Service",
            "Office / Division: Office A",
            "Classification: Simple",
            "Type of Transaction: G2C",
            "Who May Avail: All",
            "Checklist of Requirements | Where to Secure",
            "Form A | Office A",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "Do A | Check A | None | 1 minute | Staff A",
            "TOTAL: None 1 minute",
            "2. Second Service",
            "Office / Division: Office B",
            "Classification: Simple",
            "Type of Transaction: G2C",
            "Who May Avail: All",
            "Checklist of Requirements | Where to Secure",
            "Form B | Office B",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "Do B | Check B | None | 2 minutes | Staff B",
            "TOTAL: None 2 minutes",
        ]
    )
    page = PageExtraction(page_number=1, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 2
    first_rejects = services[0].parser_debug.get("rejected_fragments") or []
    second_rejects = services[1].parser_debug.get("rejected_fragments") or []
    # Document-wide numbered crumbs from the other service must not appear.
    assert all("Second Service" not in str(item) for item in first_rejects)
    assert all("First Service" not in str(item) for item in second_rejects)
    assert all("Do B" not in str(item) for item in first_rejects)
    assert all("Do A" not in str(item) for item in second_rejects)


def _build_id_validation_fragmented_geometry_words() -> list[dict]:
    """Real-PDF failure mode: client wraps and personnel crumbs on separate Y rows."""
    words: list[dict] = []
    words += _row(20, [("4.", 50, 70), ("ID", 80, 110), ("Validation", 115, 200)])
    words += _row(
        60,
        [
            ("Office", 50, 90),
            ("/", 95, 105),
            ("Division:", 110, 180),
            ("Office", 400, 440),
            ("of", 445, 465),
            ("the", 470, 495),
            ("Student", 500, 560),
            ("Affairs", 565, 620),
            ("and", 625, 655),
            ("Services", 660, 730),
        ],
    )
    words += _row(100, [("Classification:", 50, 180), ("Simple", 400, 460)])
    words += _row(
        140,
        [
            ("Transaction", 50, 120),
            ("Type:", 125, 180),
            ("G2C", 400, 430),
            ("\u2013", 435, 445),
            ("Government", 450, 530),
            ("to", 535, 550),
            ("Citizen", 555, 610),
        ],
    )
    words += _row(180, [("Who", 50, 80), ("May", 85, 115), ("Avail:", 120, 170), ("All", 400, 420)])
    words += _row(
        220,
        [
            ("Checklist", 50, 120),
            ("of", 125, 140),
            ("Requirements", 145, 240),
            ("Where", 400, 440),
            ("to", 445, 460),
            ("Secure", 465, 520),
        ],
    )
    words += _row(
        250,
        [
            ("Certificate", 50, 140),
            ("of", 145, 160),
            ("Registration", 165, 260),
            ("Registrar's", 400, 470),
            ("Office", 475, 530),
        ],
    )
    words += _row(
        280,
        [
            ("Student", 50, 110),
            ("ID", 115, 135),
            ("Business", 400, 460),
            ("Affairs", 465, 520),
            ("Office", 525, 580),
        ],
    )
    words += _row(
        320,
        [
            ("Client", 50, 90),
            ("Step", 95, 130),
            ("Agency", 230, 280),
            ("Action", 285, 340),
            ("Fees", 420, 460),
            ("Processing", 520, 590),
            ("Time", 595, 630),
            ("Person", 700, 750),
            ("Responsible", 755, 840),
        ],
    )
    # Fragmented visual rows (separate Y bands).
    words += _row(350, [("Present", 50, 100), ("the", 105, 130)])
    words += _row(365, [("Certificate", 50, 130), ("of", 135, 155)])
    words += _row(
        385,
        [
            ("Registration.", 50, 140),
            ("Check", 200, 235),
            ("Certificate", 240, 310),
            ("of", 315, 330),
            ("Registration.", 335, 410),
            ("None", 430, 460),
            ("1", 520, 530),
            ("minute", 535, 580),
            ("OSAS", 700, 740),
            ("Director/", 745, 810),
        ],
    )
    words += _row(400, [("Chairperson/Staff", 700, 860)])
    words += _row(420, [("Evaluate", 50, 110), ("the", 115, 140)])
    words += _row(
        435,
        [
            ("Services", 50, 95),
            ("rendered", 100, 145),
            ("by", 150, 165),
            ("OSAS.", 168, 179),
        ],
    )
    words += _row(
        455,
        [
            ("Issue", 230, 270),
            ("Evaluation", 275, 345),
            ("Form.", 350, 395),
            ("None", 430, 460),
            ("2", 520, 530),
            ("minutes", 535, 590),
            ("OSAS", 700, 740),
            ("Director/Chairperson/Staff", 745, 920),
        ],
    )
    words += _row(
        480,
        [
            ("Accept", 50, 90),
            ("the", 95, 120),
            ("validated", 125, 170),
            ("ID.", 172, 179),
        ],
    )
    words += _row(
        495,
        [
            ("Release", 230, 280),
            ("validated", 285, 345),
            ("ID.", 350, 380),
            ("None", 430, 460),
            ("1", 520, 530),
            ("minute", 535, 580),
            ("OSAS", 700, 740),
            ("Director/Chairperson/Staff", 745, 920),
        ],
    )
    words += _row(530, [("TOTAL:", 50, 100), ("None", 110, 150), ("4", 160, 175), ("minutes", 180, 235)])
    return words


def test_id_validation_fragmented_geometry_produces_three_complete_steps():
    page = PageExtraction(
        page_number=2,
        text="",
        method="digital",
        words=_build_id_validation_fragmented_geometry_words(),
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    service = services[0]
    assert service.service_title == "ID Validation"
    assert "Student Affairs" in service.office_division
    assert service.who_may_avail == "All"
    assert len(service.requirements) == 2
    assert len(service.steps) == 3
    assert service.steps[0].client_step.startswith("Present the Certificate of Registration")
    assert "Check Certificate of Registration." in service.steps[0].agency_action
    assert "OSAS Director/Chairperson/Staff" in service.steps[0].person_responsible
    assert "Evaluate the" in service.steps[1].client_step
    assert "Services" in service.steps[1].client_step
    assert "OSAS" in service.steps[1].client_step
    assert "Issue Evaluation Form." in service.steps[1].agency_action
    assert service.steps[2].client_step.startswith("Accept the validated ID")
    assert service.total_processing_time == "4 minutes"
    assert service.extraction_quality in {"clean", "needs_review"}
    assert service.extraction_quality != "rag_only"
    debug = service.parser_debug
    assert "visual_table_debug" in debug
    assert debug["visual_table_debug"]["page_start"] == 2
    assert debug["no_step_rows_reason"] is None
    assert isinstance(debug["detected_step_rows"], list)
    assert len(debug["detected_step_rows"]) == 3


def test_geometry_continuation_appends_to_correct_column():
    from app.services.citizen_charter_extractor_v2 import _merge_geometry_column_continuations

    rows = [
        ["Present the", "", "", "", ""],
        ["Certificate of", "", "", "", ""],
        ["Registration.", "Check Certificate of Registration.", "None", "1 minute", "OSAS Director/"],
        ["", "", "", "", "Chairperson/Staff"],
        ["Evaluate the", "", "", "", ""],
        ["Services rendered by OSAS", "Issue Evaluation Form.", "None", "2 minutes", "OSAS Director/Chairperson/Staff"],
        ["Accept the validated ID.", "Release validated ID.", "None", "1 minute", "OSAS Director/Chairperson/Staff"],
    ]
    merged = _merge_geometry_column_continuations(rows)
    assert len(merged) == 3
    assert merged[0][0].startswith("Present the Certificate of Registration")
    assert merged[0][4] == "OSAS Director/Chairperson/Staff"
    assert "Evaluate the Services rendered by OSAS" in merged[1][0]
    assert merged[2][0].startswith("Accept the validated ID")


def test_records_management_time_person_split_at_geometry():
    from app.services.citizen_charter_extractor_v2 import _split_time_and_person_cells

    ptime, person = _split_time_and_person_cells("5mins Records", "Officer, Staff")
    assert ptime.lower().startswith("5min")
    assert person == "Records Officer, Staff"


def test_blank_checklist_geometry_sets_checklist_blank_true():
    words: list[dict] = []
    words += _row(20, [("1.", 50, 70), ("Blank", 80, 130), ("Checklist", 135, 210), ("Service", 215, 280)])
    words += _row(
        60,
        [
            ("Office", 50, 90),
            ("/", 95, 105),
            ("Division:", 110, 180),
            ("Records", 400, 460),
            ("Management", 465, 560),
            ("Office", 565, 620),
        ],
    )
    words += _row(100, [("Classification:", 50, 180), ("Simple", 400, 460)])
    words += _row(140, [("Transaction", 50, 120), ("Type:", 125, 180), ("G2C", 400, 430)])
    words += _row(180, [("Who", 50, 80), ("May", 85, 115), ("Avail:", 120, 170), ("Students", 400, 470)])
    words += _row(
        220,
        [
            ("Checklist", 50, 120),
            ("of", 125, 140),
            ("Requirements", 145, 240),
            ("Where", 400, 440),
            ("to", 445, 460),
            ("Secure", 465, 520),
        ],
    )
    words += _row(250, [("None", 50, 90), ("N/A", 400, 430)])
    words += _row(
        300,
        [
            ("Client", 50, 90),
            ("Step", 95, 130),
            ("Agency", 230, 280),
            ("Action", 285, 340),
            ("Fees", 420, 460),
            ("Processing", 520, 590),
            ("Time", 595, 630),
            ("Person", 700, 750),
            ("Responsible", 755, 840),
        ],
    )
    words += _row(
        340,
        [
            ("Submit", 50, 100),
            ("request", 105, 160),
            ("Receive", 230, 280),
            ("request", 285, 340),
            ("None", 420, 460),
            ("5", 520, 530),
            ("mins", 535, 570),
            ("Records", 575, 640),
            ("Officer,", 700, 760),
            ("Staff", 765, 810),
        ],
    )
    words += _row(380, [("TOTAL:", 50, 100), ("None", 110, 150), ("5", 160, 175), ("mins", 180, 220)])
    page = PageExtraction(
        page_number=1,
        text="",
        method="digital",
        words=words,
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    service = services[0]
    assert service.checklist_blank is True
    assert service.requirements == []
    assert len(service.steps) == 1
    assert service.steps[0].processing_time.lower().startswith("5")
    assert "Records" in service.steps[0].person_responsible
    assert "Officer" in service.steps[0].person_responsible

    from app.services.citizen_charter_services import build_charter_article_body, charter_v2_service_to_fields

    fields = charter_v2_service_to_fields(
        {
            "service_title": service.service_title,
            "office_division": service.office_division,
            "who_may_avail": service.who_may_avail,
            "requirements": [],
            "steps": [
                {
                    "client_step": service.steps[0].client_step,
                    "agency_action": service.steps[0].agency_action,
                    "fees": service.steps[0].fees,
                    "processing_time": service.steps[0].processing_time,
                    "person_responsible": service.steps[0].person_responsible,
                }
            ],
            "total_processing_time": service.total_processing_time,
            "total_fees": service.total_fees,
            "checklist_blank": True,
            "page_start": 1,
        }
    )
    body = build_charter_article_body(
        title=service.service_title,
        service=fields,
        source_document="charter.pdf",
    )
    assert "No additional requirements specified in the Citizen's Charter." in body
    assert "Requirement: Not specified" not in body


def _id_validation_numbered_heading_plus_description_text() -> str:
    return "\n".join(
        [
            "4. ID Validation",
            "This process provides description and series of steps for assisting the students "
            "specifically in the validation of ID.",
            "Office or Division: Office of the Student Affairs and Services",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who may avail: All",
            "Checklist of Requirements | Where to Secure",
            "⎯ Certificate of Registration Registrar’s | Office",
            "⎯ Student ID Business | Affairs Office",
            "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
            "1. Present the Certificate of Registration. | Check Certificate of Registration. | None | 1 minute | OSAS Director/",
            "Clientele",
            "2. Evaluate the Services rendered by OSAS. | Issue Evaluation Form. | None | 2 minutes | OSAS Director/",
            "3. Accept the validated | Release validated ID. | None | 1 minute | OSAS Director/",
            "ID.",
            "Chairperson/ Staff",
            "TOTAL: None 4 minutes",
        ]
    )


def test_numbered_heading_plus_generic_description_binds_to_one_service():
    page = PageExtraction(
        page_number=1,
        text=_id_validation_numbered_heading_plus_description_text(),
        method="digital",
        words=None,
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    service = services[0]
    assert service.service_title == "ID Validation"
    assert "Student Affairs" in service.office_division
    assert service.who_may_avail == "All"
    assert len(service.requirements) == 2
    assert service.requirements[0].requirement == "Certificate of Registration"
    assert "Registrar" in service.requirements[0].where_to_secure
    assert service.requirements[1].requirement == "Student ID"
    assert service.requirements[1].where_to_secure == "Business Affairs Office"
    assert len(service.steps) == 3
    assert service.steps[2].client_step == "Accept the validated ID."
    assert "Clientele" not in service.steps[0].person_responsible
    assert "Chairperson" in service.steps[0].person_responsible or "Chairperson" in (
        service.steps[2].person_responsible
    )
    assert service.extraction_quality != "rag_only"
    assert service.parser_debug.get("merge") == "title_bound_to_structured_block" or (
        service.service_title == "ID Validation"
    )


def test_generic_description_does_not_become_title_when_numbered_heading_exists():
    from app.services.citizen_charter_extractor_v2 import _looks_like_generic_description_title

    assert _looks_like_generic_description_title(
        "This process provides description and series of steps for assisting the students"
    )
    assert _looks_like_field_or_fragment_line(
        "This process provides description and series of steps for assisting the students"
    )
    assert _looks_like_field_or_fragment_line("This service provides counseling support")
    assert _looks_like_field_or_fragment_line("Provision of services to students")

    text = "\n".join(
        [
            "5. Issuance of Good Moral Certificate",
            "This service provides description and series of steps for assisting the students.",
            "Office or Division: Office of the Student Affairs and Services",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who may avail: All",
            "Checklist of Requirements | Where to Secure",
            "Request Form | OSAS",
            "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
            "Submit request | Receive request | None | 5 minutes | OSAS Staff",
            "TOTAL: None 5 minutes",
        ]
    )
    page = PageExtraction(page_number=1, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    assert services[0].service_title == "Issuance of Good Moral Certificate"
    assert "This service provides" not in services[0].service_title


def test_no_placeholder_rag_only_duplicate_when_structured_block_follows():
    page = PageExtraction(
        page_number=1,
        text=_id_validation_numbered_heading_plus_description_text(),
        method="digital",
        words=None,
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert titles.count("ID Validation") == 1
    assert not any(s.extraction_quality == "rag_only" for s in services)
    assert all(
        not s.service_title.lower().startswith("this process provides") for s in services
    )


def test_accept_the_validated_plus_id_merges_into_one_client_step():
    from app.services.citizen_charter_extractor_v2 import _merge_geometry_column_continuations

    merged = _merge_geometry_column_continuations(
        [
            ["Present the Certificate of Registration.", "Check.", "None", "1 minute", "OSAS Director/"],
            ["", "", "", "", "Chairperson/Staff"],
            ["Evaluate the Services rendered by OSAS.", "Issue Evaluation Form.", "None", "2 minutes", "OSAS Director/Chairperson/Staff"],
            ["Accept the validated", "Release validated ID.", "None", "1 minute", "OSAS Director/"],
            ["ID.", "", "", "", ""],
            ["", "", "", "", "Chairperson/Staff"],
        ]
    )
    assert len(merged) == 3
    assert merged[2][0] == "Accept the validated ID."
    assert "Chairperson" in merged[2][4]


def test_requirement_repair_registrar_and_business_affairs():
    from app.services.citizen_charter_extractor_v2 import _repair_requirement_where_pair

    req, where = _repair_requirement_where_pair(
        "⎯ Certificate of Registration Registrar’s", "Office"
    )
    assert req == "Certificate of Registration"
    assert where == "Registrar’s Office"

    req2, where2 = _repair_requirement_where_pair("⎯ Student ID Business", "Affairs Office")
    assert req2 == "Student ID"
    assert where2 == "Business Affairs Office"


def test_header_crumb_cleanup_for_fee_time_person():
    from app.services.citizen_charter_extractor_v2 import (
        _finalize_step_cells,
        _normalize_fee,
        _normalize_osas_personnel,
        _strip_table_header_crumbs,
    )

    assert _normalize_fee("BE PAID None") == "None"
    assert _strip_table_header_crumbs("TIME 1 minute") == "1 minute"
    assert _strip_table_header_crumbs("RESPONSIBLE OSAS Director/Staff") == "OSAS Director/Staff"
    assert (
        _strip_table_header_crumbs("TIME RESPONSIBLE OSAS Director/Staff")
        == "OSAS Director/Staff"
    )
    assert (
        _normalize_osas_personnel("OSAS Director/Staff", context="OSAS")
        == "OSAS Director/Chairperson/Staff"
    )
    assert (
        _normalize_osas_personnel("OSAS Director/Chairperson/ Staff", context="OSAS")
        == "OSAS Director/Chairperson/Staff"
    )

    _c, _a, fees, ptime, person = _finalize_step_cells(
        client="Present the Certificate of Registration.",
        agency="Check Certificate of Registration.",
        fees="BE PAID None",
        ptime="TIME 1 minute",
        responsible="TIME RESPONSIBLE OSAS Director/Staff",
        context="Office of the Student Affairs and Services",
    )
    assert fees == "None"
    assert ptime == "1 minute"
    assert person == "OSAS Director/Chairperson/Staff"


def test_id_validation_contaminated_header_crumbs_clean_to_three_steps():
    text = "\n".join(
        [
            "4. ID Validation",
            "Office or Division: Office of the Student Affairs and Services",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who may avail: All",
            "Checklist of Requirements | Where to Secure",
            "Certificate of Registration | Registrar's Office",
            "Student ID | Business Affairs Office",
            "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
            "Present the Certificate of Registration. | Check Certificate of Registration. | BE PAID None | TIME 1 minute | TIME RESPONSIBLE OSAS Director/Staff",
            "Evaluate the Services rendered by OSAS. | Issue Evaluation Form. | None | 2 minutes | OSAS Director/Chairperson/Staff",
            "Accept the validated ID. | Release validated ID. | None | 1 minute | OSAS Director/Chairperson/Staff",
            "TOTAL: None 4 minutes",
        ]
    )
    page = PageExtraction(page_number=1, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    service = services[0]
    assert len(service.steps) == 3
    assert service.steps[0].fees == "None"
    assert service.steps[0].processing_time == "1 minute"
    assert service.steps[0].person_responsible == "OSAS Director/Chairperson/Staff"
    assert service.extraction_quality in {"clean", "needs_review"}
    assert "[NEEDS REVIEW]" not in service.steps[0].fees
    assert "TIME" not in service.steps[0].person_responsible
    assert "RESPONSIBLE" not in service.steps[0].person_responsible

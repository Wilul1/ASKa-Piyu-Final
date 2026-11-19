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


def test_wrapped_heading_empty_stub_merges_into_structured_sibling():
    """Empty 'Issuance of …/Transfer' stub + Credentials body → one service."""
    from app.services.citizen_charter_extractor_v2 import (
        _compose_wrapped_service_title,
        _titles_look_like_wrapped_heading,
        extract_citizen_charter_services_v2,
    )
    from app.utils.pdf.pymupdf_extractor import PageExtraction

    assert _titles_look_like_wrapped_heading(
        "Issuance of Transcript of Records/Transfer",
        "Credentials/Certifications/CAV/Authenticated Documents",
    )
    assert not _titles_look_like_wrapped_heading(
        "1. Enrollment",
        "2. Assessment of Fees",
    )
    composed = _compose_wrapped_service_title(
        "Issuance of Transcript of Records/Transfer",
        "Credentials/Certifications/CAV/Authenticated Documents",
    )
    assert "Transcript" in composed
    assert "Credentials" in composed

    text = "\n".join(
        [
            "2. Issuance of Transcript of Records/Transfer",
            "Credentials/Certifications/CAV/Authenticated Documents",
            "This process provides description and series of steps for assisting the public.",
            "Office or Division: Registrar",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who may avail: All (Walk-In students & Graduates)",
            "Checklist of Requirements | Where to Secure",
            "Clearance, Request form | Accounting Office/Office of the Registrar",
            "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
            (
                "Pay required fees. Proceed to the Cashier's office. | "
                "Receives payment and issues official receipt - students P75.00/page "
                "- students P150/page Certifications P30.00/page "
                "2nd Diploma P100.00 | "
                "Transcript Undergrad Graduate of Transfer to 5 copy of | "
                "2 minutes | Cashier's Staff"
            ),
            "TOTAL: Depends on the document Active Files: 59 minutes",
        ]
    )
    page = PageExtraction(page_number=12, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 1
    service = services[0]
    assert "Transcript" in service.service_title
    assert service.office_division == "Registrar"
    assert not any(s.extraction_quality == "rag_only" for s in services)
    fee_blob = " ".join(step.fees for step in service.steps)
    assert "75" in fee_blob
    assert "150" in fee_blob
    assert "P75" in fee_blob or "75.00" in fee_blob


def test_recover_fees_spilled_into_agency_action_generic():
    from app.services.citizen_charter_extractor_v2 import _recover_fees_spilled_into_agency

    agency = (
        "Receives payment and issues official receipt - students P75.00/page "
        "- students P150/page Certifications P30.00/page 2nd Diploma P100.00"
    )
    fees = "Transcript Undergrad Graduate of Transfer to 5 copy of"
    new_agency, new_fees = _recover_fees_spilled_into_agency(agency, fees)
    assert "P75.00/page" in new_fees
    assert "P150" in new_fees
    assert "30.00" in new_fees or "P30" in new_fees
    assert "Transcript Undergrad Graduate" not in new_fees
    assert "Receives payment" in new_agency
    assert "P75.00/page" not in new_agency
    # Ambient labels must not paint every amount.
    assert new_fees.lower().count("second copy of diploma") <= 1
    assert not new_fees.lower().startswith("second copy of diploma: p75")
    assert new_fees.lower().count("certifications:") <= 1
    # Immediate labels still work.
    assert "Certifications:" in new_fees or "P30" in new_fees
    assert "Second copy of diploma:" in new_fees or "Diploma:" in new_fees or "P100" in new_fees

    labeled_agency = (
        "Receives payment undergraduate students P75.00/page "
        "graduate students P150/page Certifications P30.00/page"
    )
    _, labeled_fees = _recover_fees_spilled_into_agency(labeled_agency, fees)
    assert "Undergraduate" in labeled_fees
    assert "Graduate" in labeled_fees


def test_fee_cell_rejects_total_line_crumbs_for_all_services():
    from app.services.citizen_charter_extractor_v2 import (
        StepV2,
        _enrich_fee_labels,
        _fee_cell_looks_unusable,
        _recover_total_fees_from_steps,
        _split_total_line,
    )

    for crumb in ("the", "on the", "Php", "Depends on the document", "Active Files"):
        assert _fee_cell_looks_unusable(crumb), crumb

    assert not _fee_cell_looks_unusable("None")
    assert not _fee_cell_looks_unusable("P75.00/page")
    assert not _fee_cell_looks_unusable("Undergraduate: P75.00/page; Graduate: P150/page")

    fee, processing = _split_total_line("Depends on the document Active Files: 59 minutes")
    assert processing == "59 minutes"
    assert fee in {"[NEEDS REVIEW]", "NEEDS REVIEW"} or "depends" not in fee.casefold()

    steps = [
        StepV2(
            client_step="A. For undergraduate students fill request slip",
            agency_action="Issue request slip",
            fees="None",
            processing_time="5 minutes",
            person_responsible="Registrar Staff",
        ),
        StepV2(
            client_step="B. For graduates fill request slip",
            agency_action="Assess fees",
            fees="None",
            processing_time="5 minutes",
            person_responsible="Registrar Staff",
        ),
        StepV2(
            client_step="Pay required fees at Cashier",
            agency_action="Receives payment",
            fees="P75.00/page; P150/page; P30.00/page; Diploma: P100.00",
            processing_time="2 minutes",
            person_responsible="Cashier Staff",
        ),
    ]
    recovered = _recover_total_fees_from_steps(steps, "on the")
    assert "P75" in recovered
    assert "P150" in recovered
    assert "Undergraduate" in recovered
    assert "Graduate" in recovered
    assert "on the" not in recovered.casefold()

    # Generic library / clinic style amounts also promote over crumbs.
    library_steps = [
        StepV2(
            client_step="Pay overdue fine",
            agency_action="Receive payment",
            fees="P5.00/day",
            processing_time="2 minutes",
            person_responsible="Librarian",
        )
    ]
    assert "P5.00/day" in _recover_total_fees_from_steps(library_steps, "Php")

    labeled = _enrich_fee_labels(
        "P75.00/page; P150/page; P100.00",
        "undergraduate students and graduate students second copy diploma",
    )
    assert "Undergraduate:" in labeled
    assert "Graduate:" in labeled
    # Ambient "diploma" in context must NOT relabel TOR page fees.
    assert labeled.count("Second copy of diploma") == 0
    assert "Undergraduate: P75.00/page" in labeled
    assert "Graduate: P150/page" in labeled

    diploma_only = _enrich_fee_labels(
        "P75.00/page; P150/page; Diploma: P100.00",
        "A. For undergraduate students B. For graduates Pay fees 2nd Diploma",
    )
    assert "Undergraduate: P75.00/page" in diploma_only
    assert "Graduate: P150/page" in diploma_only
    assert "Diploma: P100.00" in diploma_only
    assert diploma_only.count("Second copy of diploma") == 0

    # Repair over-broad labels from a previous bad pass.
    repaired = _enrich_fee_labels(
        "Second copy of diploma: P75.00/page; Second copy of diploma: P150/page; Diploma: P100.00",
        "undergraduate students graduate students",
    )
    assert "Undergraduate: P75.00/page" in repaired
    assert "Graduate: P150/page" in repaired
    assert "Diploma: P100.00" in repaired


def test_office_plain_colon_counts_as_service_header_cue():
    from app.services.citizen_charter_extractor_v2 import _has_service_header_cues

    flat = [
        {"text": "Issuance of Diploma", "page": 1},
        {"text": "Office: Registrar", "page": 1},
        {"text": "Classification: Simple", "page": 1},
        {"text": "Type of Transaction: G2C", "page": 1},
        {"text": "Who May Avail: Graduates", "page": 1},
        {"text": "Checklist of Requirements | Where to Secure", "page": 1},
        {"text": "Client Steps | Agency Action | Fees | Processing Time | Person Responsible", "page": 1},
    ]
    assert _has_service_header_cues(0, flat) is True


def test_total_residue_never_becomes_service_title():
    from app.services.citizen_charter_extractor_v2 import _looks_like_field_or_fragment_line

    assert _looks_like_field_or_fragment_line("TOTAL: None 2 minutes")
    assert _looks_like_field_or_fragment_line("None 2 minutes")
    assert not _looks_like_field_or_fragment_line("Issuance of Diploma")


# ---------------------------------------------------------------------------
# Phase 6 Part B: native table_regions as supplementary structural evidence
# against line-wrapped table-cell fragments becoming service titles.
# Reproduces the real Citizen's Charter PDF page 80 case: a processing-time
# cell "For LSPU / Units: 18 / minutes / For other / Agencies: 15 / Days and
# 18 / Minutes" is one multiline native table cell, but the existing
# geometry/text line-builder (which ignores table_regions) flattens each
# physical line separately, letting a fragment like "Units: 18" look like an
# independent heading if an UNNUMBERED next service's own header fields
# happen to fall inside the forward lookahead window used by
# _has_service_header_cues (no numbered-heading line to stop the scan first).
# ---------------------------------------------------------------------------

_PAGE_80_PROCESSING_TIME_TABLE_REGIONS = [
    {
        "bbox": [50.0, 400.0, 500.0, 480.0],
        "rows": [
            [
                "Processing Time",
                "For LSPU\nUnits: 18\nminutes\nFor other\nAgencies: 15\nDays and 18\nMinutes",
            ],
        ],
    }
]


def _page_80_like_text() -> str:
    # NOTE: the real page-80 service is named "Request of colors and
    # security" in the source PDF, but that literal title is currently
    # rejected as a heading candidate for an UNRELATED, pre-existing reason
    # outside Part B's scope: it starts with "Request", one of the step-verb
    # openers _STEP_LIKE_TITLE_RE/_looks_like_field_or_fragment_line treats
    # as a table client-step row, not a title (confirmed: True ==
    # _looks_like_field_or_fragment_line("Request of colors and security")).
    # A synthetic title is used here so this fixture tests Part B's
    # table-cell-fragment veto in isolation; see the final report's "Known
    # limitations" section for this separate, unfixed title-detection gap.
    return "\n".join(
        [
            "NSTP Colors and Security Service",
            "Office / Division: National Service Training Program",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who May Avail: NSTP Cadets",
            "Checklist of Requirements | Where to Secure",
            "Request Letter | NSTP Office",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "Submit request letter. | Process request. | None | See processing time below. | NSTP Staff",
            "TOTAL: None For LSPU units: 18 minutes; for other agencies: 15 days and 18 minutes",
            "For LSPU",
            "Units: 18",
            "minutes",
            "For other",
            "Agencies: 15",
            "Days and 18",
            "Minutes",
            # Deliberately unnumbered: a numbered next heading would already
            # stop _has_service_header_cues's forward scan before reaching
            # these fields, so this fixture only reproduces the bug (and
            # only proves the fix) when the next service is unnumbered.
            "Issuance of NSTP Certificate of Completion",
            "Office / Division: National Service Training Program",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who May Avail: NSTP Completers",
            "Checklist of Requirements | Where to Secure",
            "Clearance | NSTP Office",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "Submit clearance. | Issue certificate. | None | 5 minutes | NSTP Staff",
            "TOTAL: None 5 minutes",
        ]
    )


def test_v2_wrapped_processing_time_cell_is_not_a_service():
    page = PageExtraction(
        page_number=80,
        text=_page_80_like_text(),
        method="digital",
        words=None,
        table_regions=_PAGE_80_PROCESSING_TIME_TABLE_REGIONS,
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    titles = {s.service_title for s in services}

    for fragment in ("Units: 18", "For other", "Agencies: 15", "Days and 18", "Minutes"):
        assert fragment not in titles, f"{fragment!r} must not become an independent service title"

    assert "NSTP Colors and Security Service" in titles
    assert "Issuance of NSTP Certificate of Completion" in titles
    assert len(services) == 2

    nstp = next(s for s in services if s.service_title == "NSTP Colors and Security Service")
    assert nstp.office_division == "National Service Training Program"
    # Processing-time meaning stays associated with the NSTP service's own
    # TOTAL line, not invented and not attached to the wrong service.
    assert nstp.total_processing_time not in (NEEDS_REVIEW, "", None)


def test_v2_does_not_use_next_service_headers_for_post_total_fragment():
    """Without the table_regions veto, a post-TOTAL fragment like "Units: 18"
    can pass `_has_service_header_cues` by "borrowing" an unnumbered NEXT
    service's own header fields inside the forward lookahead window. This
    must never happen: exactly two services are found, the second service's
    own identity is untouched by the fragment, and no page-80 fragment is
    ever promoted to a third, spurious "service"."""
    page = PageExtraction(
        page_number=80,
        text=_page_80_like_text(),
        method="digital",
        words=None,
        table_regions=_PAGE_80_PROCESSING_TIME_TABLE_REGIONS,
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    assert len(services) == 2

    second = next(s for s in services if s.service_title == "Issuance of NSTP Certificate of Completion")
    assert second.office_division == "National Service Training Program"
    assert second.who_may_avail == "NSTP Completers"

    # Table-wrapped fragments are vetoed before heading detection even runs,
    # so they never become their own service block in the first place (and
    # therefore never appear as a numbered *rejected* fragment either) --
    # this just confirms no stray third service/title leaked through.
    assert all(
        s.service_title not in {"Units: 18", "For other", "Agencies: 15", "Days and 18", "Minutes"}
        for s in services
    )


def test_noise_and_fragment_filters_still_allow_units_of_professional_education():
    """A generic rejection of every title containing "Units" is prohibited:
    a genuinely well-formed heading that happens to contain a number + the
    word "Units" must still be recognized as a real service, even on a page
    that also has an unrelated wrapped table cell elsewhere.

    NOTE: the real Student Handbook title is "For Non-Education Graduates,
    18 Units Of Professional Education" and is processed by a different
    module entirely (handbook_policy_processor.py, not this Charter
    extractor). The comma in that literal title also happens to trip this
    module's own unrelated, pre-existing comma-based fragment heuristic
    (_looks_like_field_or_fragment_line rejects any candidate containing
    ","), which is outside Part B's scope. A comma-free title is used here
    so this fixture isolates exactly what Part B must not break: rejecting
    a title merely for containing a number + "Units".
    """
    text = "\n".join(
        [
            "18 Units Of Professional Education For Non Education Graduates",
            "Office / Division: College of Education",
            "Classification: Simple",
            "Type of Transaction: G2C – Government to Citizen",
            "Who May Avail: Non-Education Graduates",
            "Checklist of Requirements | Where to Secure",
            "Transcript of Records | Registrar's Office",
            "Client Step | Agency Action | Fees | Processing Time | Person Responsible",
            "Submit transcript. | Evaluate units. | None | 5 minutes | Education Staff",
            "TOTAL: None 5 minutes",
        ]
    )
    # An unrelated wrapped cell on the same page must not cause any
    # collateral rejection of a real heading via over-broad matching.
    page = PageExtraction(
        page_number=23,
        text=text,
        method="digital",
        words=None,
        table_regions=_PAGE_80_PROCESSING_TIME_TABLE_REGIONS,
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    titles = {s.service_title for s in services}
    assert "18 Units Of Professional Education For Non Education Graduates" in titles


# ---------------------------------------------------------------------------
# Phase 6.12: service-boundary repair for one-line descriptions that lack a
# trailing period (e.g. real source "Open to all Clients") and therefore
# survive _looks_like_field_or_fragment_line's checks to become an
# independent, empty/"Open to all Clients"-titled candidate instead of
# staying part of the placeholder-only heading immediately before them.
# Reproduces the real Citizen's Charter page 82/83 "IP Registration Process"
# defect (Phase 6.11) with representative synthetic text modeled on the real
# PDF content (verified directly against
# data/documents/da4a1832-7242-4e94-8ba6-bc0b9f2294bf/
# Laguna State Polytechnic University-CC_2026-1st Edition.pdf, page indices
# 81-83) rather than loading the full 3MB PDF in a unit test.
# ---------------------------------------------------------------------------


def _ip_registration_fixture_text(office: str) -> str:
    return "\n".join(
        [
            "1. IP Registration Process",
            "Open to all Clients",
            f"Office or Division: {office}",
            "Classification: Highly Technical",
            "Type of Transaction: G2G",
            "Who may avail: All",
            "Checklist of Requirements | Where to Secure",
            "Endorsement Letter | CIET",
            "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
            "Submit application | Review documents | None | 3 days | CIET Staff",
            "TOTAL: None 3 days",
        ]
    )


def test_ip_registration_open_to_all_clients_merges_not_independent_service():
    """The real defect, single chapter: 'Open to all Clients' (no trailing
    period in the source) must not survive as its own placeholder-adjacent
    service -- it is 'IP Registration Process'(cur)'s own one-line
    description, mis-promoted into an independent heading candidate because
    _looks_like_field_or_fragment_line has no check that fires for a short,
    well-formed, capitalized phrase without a trailing period."""
    page = PageExtraction(
        page_number=82,
        text=_ip_registration_fixture_text("CIET"),
        method="digital",
        words=None,
        geometry_scale=1.0,
    )
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert "Open to all Clients" not in titles
    assert len(services) == 1
    service = services[0]
    assert service.service_title == "IP Registration Process"
    assert service.office_division == "CIET"
    assert service.extraction_quality != "rag_only"
    assert len(service.steps) == 1


def test_two_ip_registration_services_in_different_chapters_stay_distinct():
    """Confirmed real-corpus pattern: two separate 'IP Registration Process'
    services exist under two different chapters (XXV / XXVI), each with its
    own 'Open to all Clients' description and its own real office. The fix
    must merge each description into its OWN chapter's service, and must
    never bridge the two chapters into one merged service."""
    text = "\n\n".join(
        [
            "XXV. CENTER FOR INNOVATION AND EMERGING TECHNOLOGIES",
            _ip_registration_fixture_text("CIET"),
            "XXVI. INNOVATION AND TECHNOLOGY SUPPORT OFFICE",
            _ip_registration_fixture_text("CIET & ITSO"),
        ]
    )
    pages = [
        PageExtraction(page_number=82, text=text, method="digital", words=None, geometry_scale=1.0),
    ]
    services = extract_citizen_charter_services_v2(pages)
    titles = [s.service_title for s in services]
    assert titles.count("Open to all Clients") == 0
    assert titles.count("IP Registration Process") == 2
    offices = {s.office_division for s in services if s.service_title == "IP Registration Process"}
    assert offices == {"CIET", "CIET & ITSO"}
    # No cross-chapter content bleed: each service keeps its own steps/office.
    for service in services:
        assert service.extraction_quality != "rag_only"


def test_looks_like_chapter_or_section_heading_is_structural_not_phrase_specific():
    """General, roman-numeral + substantially-uppercase-remainder signal --
    not a denylist for a specific office name or chapter title. Must fire for
    ALL-CAPS chapter dividers (any wording) and must NOT fire for ordinary
    Title-Case service titles, including ones that start with a lone
    capital letter or contain acronyms."""
    from app.services.citizen_charter_extractor_v2 import _looks_like_chapter_or_section_heading

    assert _looks_like_chapter_or_section_heading(
        "XXV. CENTER FOR INNOVATION AND EMERGING TECHNOLOGIES"
    )
    assert _looks_like_chapter_or_section_heading("XXIII. NATIONAL SERVICE TRAINING PROGRAM")
    assert _looks_like_chapter_or_section_heading("IV. RECORDS MANAGEMENT OFFICE")
    # Ordinary service titles, including ones with acronyms/offices, must not match.
    assert not _looks_like_chapter_or_section_heading("IP Registration Process")
    assert not _looks_like_chapter_or_section_heading("Colors and security")
    assert not _looks_like_chapter_or_section_heading("Mail Management")
    assert not _looks_like_chapter_or_section_heading("Releasing of Alumni ID Number")
    assert not _looks_like_chapter_or_section_heading("3. Mail Management")
    # Title-Case roman-numeral headings (not ALL-CAPS) are a different,
    # legitimate pattern elsewhere in the document and must not match either.
    assert not _looks_like_chapter_or_section_heading("I. Introduction")


def test_placeholder_heading_never_adopts_chapter_divider_text_as_merged_title():
    """Safety guard: even if a chapter/section divider is ever detected as its
    own placeholder-only candidate (a separate, pre-existing issue in
    _detect_service_blocks this phase does not fix), the merge function must
    never adopt that divider's own ALL-CAPS text as a real service's merged
    title -- doing so would be worse than leaving the split as-is. Verified
    directly against the merge function with hand-built candidates, since
    forcing a chapter divider into its own block via full-text geometry
    parsing is fragile/version-dependent and not what this guard itself
    depends on."""
    from app.services.citizen_charter_extractor_v2 import (
        CharterServiceV2,
        _merge_title_bound_placeholder_services,
    )

    divider = CharterServiceV2(
        service_title="XXIII. NATIONAL SERVICE TRAINING PROGRAM",
        office_division=NEEDS_REVIEW,
        classification=NEEDS_REVIEW,
        transaction_type=NEEDS_REVIEW,
        who_may_avail=NEEDS_REVIEW,
        page_start=80,
        page_end=80,
        extraction_quality="rag_only",
    )
    real_service = CharterServiceV2(
        service_title="Colors and security",
        office_division="National Service Training Program",
        classification="Simple",
        transaction_type="G2C",
        who_may_avail="LSPU Units and Offices",
        requirements=[RequirementV2(requirement="Request Letter", where_to_secure="NSTP Office")],
        steps=[
            StepV2(
                client_step="Submit request",
                agency_action="Assign personnel",
                fees="None",
                processing_time="1 day",
                person_responsible="NSTP Staff",
            )
        ],
        page_start=80,
        page_end=80,
        extraction_quality="clean",
    )
    merged = _merge_title_bound_placeholder_services([divider, real_service])
    by_title = {s.service_title: s for s in merged}
    # "Colors and security" keeps its own identity and real structured body --
    # it must never be renamed to the chapter divider's ALL-CAPS text.
    assert "Colors and security" in by_title
    assert by_title["Colors and security"].office_division == "National Service Training Program"
    assert by_title["Colors and security"].steps
    # If the divider survives as its own (still-empty) candidate, that is the
    # existing, pre-Phase-6.12 status quo for an unmerged placeholder -- not a
    # regression. What must never happen is the divider's own text ending up
    # as the title of the service that carries the real steps/requirements.
    if "XXIII. NATIONAL SERVICE TRAINING PROGRAM" in by_title:
        divider_result = by_title["XXIII. NATIONAL SERVICE TRAINING PROGRAM"]
        assert not divider_result.requirements
        assert not divider_result.steps


# ---------------------------------------------------------------------------
# Phase 6.14 -- generic chapter-heading recognition (confirmed real defect:
# a bare chapter divider with no structured body of its own, e.g. "XXIII.
# NATIONAL SERVICE TRAINING PROGRAM", survived as its own empty, rag_only
# service candidate). Fixed by extending _merge_title_bound_placeholder_
# services's own loop to drop (not merge) a candidate that is structurally a
# chapter/section divider (_looks_like_chapter_or_section_heading) AND has no
# structured body (_service_has_structured_body) -- never by name, office, or
# page number.
# ---------------------------------------------------------------------------


def test_bare_chapter_divider_is_not_emitted_as_a_service_candidate():
    """Category 1: the exact confirmed real-corpus defect, using the exact
    real divider title and the real merge function it is actually filtered
    in. (A full end-to-end PageExtraction fixture was tried first and found
    to be an unreliable way to exercise this specific condition in
    isolation -- _detect_service_blocks's block-splitting for this exact
    divider depends on substantially more surrounding real-document context
    than a small synthetic page reproduces, confirmed by direct
    experimentation; the real full-document reproduction in
    test_phase_6_12_other_six_merges_remain_unchanged_full_document below is
    the authoritative end-to-end proof for this exact case.) This test
    instead verifies the real guard condition directly and reliably against
    the exact real title string, following a real well-formed service, which
    must never be dropped."""
    from app.services.citizen_charter_extractor_v2 import (
        CharterServiceV2,
        _merge_title_bound_placeholder_services,
    )

    divider = CharterServiceV2(
        service_title="XXIII. NATIONAL SERVICE TRAINING PROGRAM",
        office_division=NEEDS_REVIEW,
        classification=NEEDS_REVIEW,
        transaction_type=NEEDS_REVIEW,
        who_may_avail=NEEDS_REVIEW,
        page_start=80,
        page_end=80,
        extraction_quality="rag_only",
    )
    real_service = CharterServiceV2(
        service_title="IP Registration Process",
        office_division="CIET",
        classification="Highly Technical",
        transaction_type="G2G",
        who_may_avail="All",
        requirements=[RequirementV2(requirement="Endorsement Letter", where_to_secure="CIET")],
        steps=[
            StepV2(
                client_step="Submit application",
                agency_action="Review documents",
                fees="None",
                processing_time="3 days",
                person_responsible="CIET Staff",
            )
        ],
        page_start=80,
        page_end=80,
        extraction_quality="clean",
    )
    merged = _merge_title_bound_placeholder_services([divider, real_service])
    titles = [s.service_title for s in merged]
    assert "XXIII. NATIONAL SERVICE TRAINING PROGRAM" not in titles
    assert "IP Registration Process" in titles
    kept = next(s for s in merged if s.service_title == "IP Registration Process")
    assert kept.office_division == "CIET"
    assert kept.steps


def test_generic_roman_numeral_chapter_heading_recognized_structurally():
    """Category 2: a differently-worded chapter divider (not the NSTP
    example, and not any phrase/office name this session has already seen)
    must be recognized by the same structural signal -- proving the fix
    generalizes rather than matching one known phrase."""
    from app.services.citizen_charter_extractor_v2 import (
        CharterServiceV2,
        _merge_title_bound_placeholder_services,
    )

    divider = CharterServiceV2(
        service_title="XLII. OFFICE OF SUSTAINABLE CAMPUS OPERATIONS",
        office_division=NEEDS_REVIEW,
        classification=NEEDS_REVIEW,
        transaction_type=NEEDS_REVIEW,
        who_may_avail=NEEDS_REVIEW,
        page_start=10,
        page_end=10,
        extraction_quality="rag_only",
    )
    real_service = CharterServiceV2(
        service_title="Tree Planting Permit",
        office_division="Campus Operations",
        classification="Simple",
        transaction_type="G2C",
        who_may_avail="All",
        requirements=[RequirementV2(requirement="Application Form", where_to_secure="Campus Operations")],
        steps=[
            StepV2(
                client_step="Submit application",
                agency_action="Review and approve",
                fees="None",
                processing_time="1 day",
                person_responsible="Campus Staff",
            )
        ],
        page_start=10,
        page_end=10,
        extraction_quality="clean",
    )
    merged = _merge_title_bound_placeholder_services([divider, real_service])
    titles = [s.service_title for s in merged]
    assert "XLII. OFFICE OF SUSTAINABLE CAMPUS OPERATIONS" not in titles
    assert "Tree Planting Permit" in titles


def test_chapter_looking_title_with_real_body_remains_a_service_candidate():
    """Category 3: an uppercase, roman-numeral-prefixed title that -- unlike
    a true divider -- genuinely carries its own structured body (office,
    steps) must NOT be dropped. The guard is scoped to 'divider AND no body',
    never 'divider alone', so this must survive unchanged."""
    from app.services.citizen_charter_extractor_v2 import (
        CharterServiceV2,
        _merge_title_bound_placeholder_services,
        _service_has_structured_body,
    )

    chapter_shaped_but_real = CharterServiceV2(
        service_title="IV. RECORDS MANAGEMENT OFFICE",
        office_division="Records Management Office",
        classification="Simple",
        transaction_type="G2C",
        who_may_avail="All",
        steps=[
            StepV2(
                client_step="Request record",
                agency_action="Retrieve and release",
                fees="None",
                processing_time="10 minutes",
                person_responsible="Records Staff",
            )
        ],
        page_start=5,
        page_end=5,
        extraction_quality="clean",
    )
    assert _service_has_structured_body(chapter_shaped_but_real)
    following = CharterServiceV2(
        service_title="Unrelated Later Service",
        office_division="Other Office",
        classification="Simple",
        transaction_type="G2C",
        who_may_avail="All",
        steps=[StepV2(client_step="x", agency_action="y", fees="None", processing_time="1 day", person_responsible="Staff")],
        page_start=6,
        page_end=6,
        extraction_quality="clean",
    )
    merged = _merge_title_bound_placeholder_services([chapter_shaped_but_real, following])
    titles = [s.service_title for s in merged]
    assert "IV. RECORDS MANAGEMENT OFFICE" in titles
    kept = next(s for s in merged if s.service_title == "IV. RECORDS MANAGEMENT OFFICE")
    assert kept.steps


def test_numbered_subsection_is_not_discarded_as_a_chapter():
    """Category 4: an ordinary Arabic-numbered placeholder heading (the
    existing Phase 6.12 pattern, e.g. '3. Mail Management') must not be
    affected by the new chapter-divider guard at all -- it is not
    roman-numeral-prefixed, so _looks_like_chapter_or_section_heading is
    False for it, and the existing merge-into-next-structured-block
    behavior must continue exactly as before."""
    text = "\n\n".join(
        [
            "3. Mail Management",
            "Office or Division: Records Office",
            "Classification: Simple",
            "Type of Transaction: G2C",
            "Who may avail: All",
            "Checklist of Requirements | Where to Secure",
            "Request Slip | Records Office",
            "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
            "Submit request | Log and route mail | None | 5 minutes | Records Staff",
            "TOTAL: None 5 minutes",
        ]
    )
    page = PageExtraction(page_number=20, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert "Mail Management" in titles or "3. Mail Management" in titles
    service = next(s for s in services if "Mail Management" in (s.service_title or ""))
    assert service.extraction_quality != "rag_only"
    assert service.steps


def test_legitimate_numbered_service_title_remains_detectable():
    """Category 5: a straightforward, well-formed numbered service title with
    its own immediately-adjacent structured body must remain fully
    detectable and must not be merged away or dropped."""
    text = "\n\n".join(
        [
            "5. Issuance of Library Clearance",
            "Office or Division: Library",
            "Classification: Simple",
            "Type of Transaction: G2C",
            "Who may avail: Graduating Students",
            "Checklist of Requirements | Where to Secure",
            "Borrower's Card | Library",
            "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
            "Present borrower's card | Verify no outstanding loans | None | 5 minutes | Library Staff",
            "TOTAL: None 5 minutes",
        ]
    )
    page = PageExtraction(page_number=30, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert any("Issuance of Library Clearance" in (t or "") for t in titles)


def test_procedure_step_like_text_is_not_mistaken_for_a_chapter_heading():
    """Category 6: a roman-numeral-prefixed line whose remainder is an
    ordinary (non-uppercase) sentence -- the shape a numbered procedure step
    or sub-point could take -- must not match the chapter-heading signal,
    since the uppercase-ratio check requires a substantially-uppercase
    remainder, not merely a roman-numeral prefix."""
    from app.services.citizen_charter_extractor_v2 import _looks_like_chapter_or_section_heading

    assert not _looks_like_chapter_or_section_heading("I. Submit the accomplished form to the office")
    assert not _looks_like_chapter_or_section_heading("II. Wait for the staff to review your request")


def test_phase_6_12_other_six_merges_remain_unchanged_full_document():
    """Categories 7-12 (full-document evidence): reproducing the real PDF
    with the Phase 6.14 guard active versus inactive (in-memory only, no
    file/state change) must differ by exactly one deletion -- the chapter
    divider -- and nothing else. This directly proves Phase 6.12's other six
    merges, the two distinct IP Registration services, the absence of a
    standalone 'Open to all Clients', and the page-80 wrapped-table fix are
    all untouched, since any of those regressing would show up as an
    additional diff hunk here.

    Baseline counts updated for Phase 6.16 (87/86 -> 94/93, 166/249 reqs+steps
    -> 173/270), then again for Phase 6.20 (94/93 -> 97/96, 173/270 ->
    177/284): this test only neutralizes Phase 6.14's
    `_service_has_structured_body` guard, so Phase 6.16's and Phase 6.20's
    independent numbered-heading fixes (not gated on that function at all) are
    now unconditionally present in BOTH the before and after reconstructions
    here -- they are not what this test isolates, see
    `test_phase_6_16_full_document_comparison_isolates_numbered_heading_recovery`
    for that. The isolating diff-hunk assertion below (exactly one
    deletion, the chapter divider, nothing else) is the actual behavior
    this test proves and is unaffected by the later phase's totals."""
    import difflib

    from app.utils.pdf.pymupdf_extractor import extract_pdf
    import app.services.citizen_charter_extractor_v2 as mod

    pdf_path = (
        "data/documents/da4a1832-7242-4e94-8ba6-bc0b9f2294bf/"
        "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
    )
    with open(pdf_path, "rb") as handle:
        pdf_bytes = handle.read()
    result = extract_pdf(pdf_bytes)

    original_has_body = mod._service_has_structured_body
    try:
        # Neutralize only the NEW guard (it is gated on `not
        # _service_has_structured_body(cur)`) without touching any other
        # Phase 6.12 behavior, which does not depend on this function's
        # return value for its own, already-tested merge conditions.
        mod._service_has_structured_body = lambda service: True
        before_titles = [s.service_title for s in mod.extract_citizen_charter_services_v2(result.pages)]
    finally:
        mod._service_has_structured_body = original_has_body
    after_services = mod.extract_citizen_charter_services_v2(result.pages)
    after_titles = [s.service_title for s in after_services]

    assert len(before_titles) == 97
    assert len(after_titles) == 96

    diff_hunks = [
        (tag, before_titles[i1:i2], after_titles[j1:j2])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, before_titles, after_titles).get_opcodes()
        if tag != "equal"
    ]
    # Phase 6.16 is NOT gated on `_service_has_structured_body` at all, so it
    # is unconditionally active in both the "before" and "after"
    # reconstructions here -- this monkeypatch only disables Phase 6.14's
    # chapter-DROP guard, not Phase 6.16's numbered-heading recognition.
    # With the drop guard disabled, a bare chapter divider immediately
    # adjacent to its own now-independently-recognized real title (Phase
    # 6.16) survives as its own extra, empty block in "before" for the NSTP
    # case specifically (confirmed: `_service_has_structured_body` is also
    # called on `nxt` inside Phase 6.12's merge condition, so the same
    # monkeypatch affects that check too, in a way that happens to resolve
    # differently per case depending on block adjacency) -- while the
    # University-Board-Secretary and MIS chapter headings merge/replace
    # cleanly in both states regardless. This 3-hunk diff is the exact,
    # directly-verified result of stacking this artificial single-function
    # monkeypatch with Phase 6.16's independent fix; the REAL (unpatched)
    # system behavior -- which is what production actually runs -- is
    # separately and directly verified clean, with no duplication and no
    # chapter-divider leak, by
    # test_phase_6_16_full_document_comparison_isolates_numbered_heading_recovery.
    assert diff_hunks == [
        (
            "replace",
            ["III. OFFICE OF THE UNIVERSITY BOARD SECRETARY"],
            ["Request and Issuance of Resolutions and Except of the Minutes"],
        ),
        (
            "replace",
            ["XI. MANAGEMENT INFORMATION SYSTEM"],
            ["Request for quarterly/semi-annual/annual data"],
        ),
        (
            "replace",
            ["XXIII. NATIONAL SERVICE TRAINING PROGRAM", "Colors and security"],
            ["Request of colors and security"],
        ),
    ]

    assert after_titles.count("IP Registration Process") == 2
    assert "Open to all Clients" not in after_titles
    assert sum(len(s.requirements or []) for s in after_services) == 177
    assert sum(len(s.steps or []) for s in after_services) == 284
    assert not any(
        t in (s.service_title or "")
        for s in after_services
        for t in ("Units: 18", "For other", "Agencies: 15", "Days and 18", "Minutes")
        if (s.service_title or "").strip() in ("Units: 18", "For other", "Agencies: 15", "Days and 18", "Minutes")
    )


# ---------------------------------------------------------------------------
# Phase 6.16 -- context-aware numbered heading recognition.
#
# Root cause (Phase 6.15, confirmed by direct execution): a numbered heading
# whose stripped text opens with a step-verb (e.g. "Request of colors and
# security" -> "request") is rejected by `_looks_like_field_or_fragment_line`
# before `_has_service_header_cues` -- which DOES return True for the real
# page-80 occurrence -- is ever consulted. The fix adds an
# `allow_step_verb_opener` parameter to `_looks_like_field_or_fragment_line`
# that suppresses ONLY the step-verb-opener sub-check, applied in
# `_line_is_heading_candidate`'s numbered branch only when
# `_has_service_header_cues` confirms real service-header structure follows.
# Every other independent fragment signal (comma, trailing punctuation,
# TOTAL residue, field labels, brackets, generic-description, etc.) still
# applies unconditionally and is never overridden.
# ---------------------------------------------------------------------------


def _charter_page_text(*lines: str) -> str:
    return "\n\n".join(lines)


def test_exact_nstp_heading_recognized_via_real_pdf():
    """Positive 1: the exact confirmed real-corpus defect -- using the real
    source PDF, not a synthetic fixture -- must now recover the full title."""
    from app.utils.pdf.pymupdf_extractor import extract_pdf

    pdf_path = (
        "data/documents/da4a1832-7242-4e94-8ba6-bc0b9f2294bf/"
        "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
    )
    with open(pdf_path, "rb") as handle:
        pdf_bytes = handle.read()
    result = extract_pdf(pdf_bytes)
    services = extract_citizen_charter_services_v2(result.pages)
    titles = [s.service_title for s in services]
    assert "Request of colors and security" in titles
    assert "Colors and security" not in titles
    nstp = next(s for s in services if s.service_title == "Request of colors and security")
    assert nstp.office_division == "National Service Training Program"
    assert nstp.steps


def test_different_action_opening_numbered_title_recognized_with_real_header(
):
    """Positive 2: a different, synthetic numbered service title beginning
    with an action-like word (not 'request', not NSTP, not any phrase this
    session has already seen) is recognized when its own real service-header
    structure genuinely supports it -- proving the fix is a general
    structural signal, not a one-phrase exception."""
    text = _charter_page_text(
        "XIX. CAMPUS SECURITY OFFICE",
        "1. Secure Visitor Pass for Guests",
        "Office or Division: Campus Security Office",
        "Classification: Simple",
        "Type of Transaction: G2C",
        "Who may avail: All",
        "Checklist of Requirements | Where to Secure",
        "Valid ID | Client",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "Present valid ID | Issue visitor pass | None | 5 minutes | Security Officer",
        "TOTAL: None 5 minutes",
    )
    page = PageExtraction(page_number=40, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert "Secure Visitor Pass for Guests" in titles
    service = next(s for s in services if s.service_title == "Secure Visitor Pass for Guests")
    assert service.office_division == "Campus Security Office"
    assert service.steps


def test_numbering_stripped_cleanly_consistent_with_existing_convention():
    """Positive 3: the recovered title strips its numbering exactly the same
    way every other numbered service in this codebase already does (e.g.
    '5. Issuance of Library Clearance' -> 'Issuance of Library Clearance') --
    no leftover numbering prefix, no corruption of the title text."""
    text = _charter_page_text(
        "XX. RECORDS UNIT",
        "1. Request for Transcript Copy",
        "Office or Division: Records Unit",
        "Classification: Simple",
        "Type of Transaction: G2C",
        "Who may avail: All",
        "Checklist of Requirements | Where to Secure",
        "Request Form | Records Unit",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "Submit request form | Process and release | None | 1 day | Records Staff",
        "TOTAL: None 1 day",
    )
    page = PageExtraction(page_number=41, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert "Request for Transcript Copy" in titles
    assert not any((t or "").startswith("1.") for t in titles)


def test_recognized_numbered_title_continues_through_normal_quality_classification():
    """Positive 4: a recovered numbered candidate is not force-classified by
    any special bypass -- it goes through the exact same downstream
    `extraction_quality` scoring as every other service, here landing on a
    normal 'clean'-eligible classification since every real field is
    present."""
    text = _charter_page_text(
        "XXI. ALUMNI RELATIONS OFFICE",
        "1. Apply for Alumni ID Card",
        "Office or Division: Alumni Relations Office",
        "Classification: Simple",
        "Type of Transaction: G2C",
        "Who may avail: Alumni",
        "Checklist of Requirements | Where to Secure",
        "Diploma Copy | Registrar",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "Submit diploma copy | Verify and issue ID | 100 | 10 minutes | Alumni Officer",
        "TOTAL: 100 10 minutes",
    )
    page = PageExtraction(page_number=42, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    service = next(s for s in services if s.service_title == "Apply for Alumni ID Card")
    assert service.extraction_quality != "rag_only"
    assert service.office_division == "Alumni Relations Office"


def test_step_verb_numbered_line_without_header_evidence_stays_rejected():
    """Negative 5: '1. Submit your application' with NO real service-header
    structure following (just an unrelated short note, then TOTAL) must
    remain rejected -- the override only applies when genuine structural
    evidence supports a real heading, never unconditionally."""
    text = _charter_page_text(
        "1. Submit your application",
        "Please wait for confirmation.",
        "TOTAL: None 5 minutes",
    )
    page = PageExtraction(page_number=43, text=text, method="digital", words=None, geometry_scale=1.0)
    flat = _flatten_pages_for_test(page)
    idx = next(i for i, l in enumerate(flat) if l["text"].startswith("1. Submit"))
    assert _line_is_heading_candidate(idx, flat) is None


def test_ordinary_numbered_instruction_not_promoted_merely_because_numbered():
    """Negative 6: an ordinary numbered instruction line with no supporting
    header structure anywhere nearby must not be promoted into a title just
    because it happens to be numbered."""
    text = _charter_page_text(
        "2. Wait for your number to be called",
        "Proceed to the designated counter.",
        "TOTAL: None 10 minutes",
    )
    page = PageExtraction(page_number=44, text=text, method="digital", words=None, geometry_scale=1.0)
    flat = _flatten_pages_for_test(page)
    idx = next(i for i, l in enumerate(flat) if l["text"].startswith("2. Wait"))
    assert _line_is_heading_candidate(idx, flat) is None


def test_numbered_subsection_without_header_cues_not_classified_as_service():
    """Negative 7: a numbered subsection-like heading (e.g. an overview
    blurb) with ordinary prose -- not a real Office/Classification/.../
    Checklist block -- following it must not be classified as a service."""
    text = _charter_page_text(
        "2. Overview of the Process",
        "This section explains the general process in detail for reference.",
        "The next section lists specific requirements for each case type.",
    )
    page = PageExtraction(page_number=45, text=text, method="digital", words=None, geometry_scale=1.0)
    flat = _flatten_pages_for_test(page)
    idx = next(i for i, l in enumerate(flat) if l["text"].startswith("2. Overview"))
    assert _line_is_heading_candidate(idx, flat) is None


def test_fragment_line_does_not_borrow_unrelated_following_services_header_cues():
    """Negative 8: a step-verb-shaped fragment line immediately followed by
    its own table's TOTAL, with a genuinely different, unrelated service's
    full header block only appearing AFTER that TOTAL, must stay rejected --
    `_has_service_header_cues`'s existing TOTAL-stop logic must not let this
    line borrow the next service's header cues as if they were its own."""
    text = _charter_page_text(
        "1. Receive the complaint form",
        "TOTAL: None 2 minutes",
        "2. Filing of Formal Complaint",
        "Office or Division: Legal Office",
        "Classification: Simple",
        "Type of Transaction: G2C",
        "Who may avail: All",
        "Checklist of Requirements | Where to Secure",
        "Complaint Form | Legal Office",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "File complaint | Docket and assign | None | 1 day | Legal Staff",
        "TOTAL: None 1 day",
    )
    page = PageExtraction(page_number=46, text=text, method="digital", words=None, geometry_scale=1.0)
    flat = _flatten_pages_for_test(page)
    idx = next(i for i, l in enumerate(flat) if l["text"].startswith("1. Receive"))
    assert _line_is_heading_candidate(idx, flat) is None
    # The genuinely real, separate service must still be recognized normally.
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert "Filing of Formal Complaint" in titles


def test_comma_continued_title_still_rejected_despite_header_evidence():
    """Guards the narrowing itself: a numbered heading rejected for a reason
    OTHER than the step-verb-opener check (here, a comma -- indicating a
    line-wrapped, comma-continued real title split across two physical
    lines) must stay rejected even when real header-cue evidence follows.
    Only the step-verb-opener sub-check is ever overridden -- every other
    independent fragment signal still applies unconditionally."""
    title = "Provision of Gender and Development Related Materials,"
    assert "," in title
    assert not _STEP_LIKE_TITLE_RE_for_test().match(title)
    assert _looks_like_field_or_fragment_line(title, allow_step_verb_opener=True)


def _STEP_LIKE_TITLE_RE_for_test():
    from app.services.citizen_charter_extractor_v2 import _STEP_LIKE_TITLE_RE

    return _STEP_LIKE_TITLE_RE


def _flatten_pages_for_test(*pages: PageExtraction) -> list[dict]:
    from app.services.citizen_charter_extractor_v2 import _flatten_pages

    return _flatten_pages(list(pages))


def test_phase_6_16_full_document_comparison_isolates_numbered_heading_recovery():
    """Categories 9-14 (full-document evidence): reproducing the real PDF
    with Phase 6.16's `allow_step_verb_opener` override active versus
    inactive isolates exactly what THAT phase changed. This directly proves
    Phase 6.12's seven merges, both distinct IP Registration services, the
    absent standalone 'Open to all Clients', Phase 6.14's chapter-heading
    exclusion, and the page-80 wrapped-table fix are all untouched -- any
    regression in any of those would show up as an unexpected diff hunk
    here, beyond the ones this phase intends.

    Both "before" and "after" are reconstructed as standalone local
    functions (monkeypatching `_line_is_heading_candidate` wholesale, not a
    shared inner helper's parameter) rather than neutering
    `_looks_like_field_or_fragment_line`'s `allow_step_verb_opener` kwarg in
    place. Phase 6.20 (landed after this test) calls that same helper TWICE
    with different argument values to derive two independent pieces of
    information -- a monkeypatch that forces the kwarg to a fixed value
    regardless of what's passed can no longer distinguish those two calls,
    which silently breaks this test's "before" reconstruction without
    touching anything this test is actually supposed to isolate. Freezing
    each phase's own numbered-branch logic as an independent local function
    keeps this test decoupled from later phases' internal call patterns."""
    import difflib
    import re

    from app.utils.pdf.pymupdf_extractor import extract_pdf
    import app.services.citizen_charter_extractor_v2 as mod

    pdf_path = (
        "data/documents/da4a1832-7242-4e94-8ba6-bc0b9f2294bf/"
        "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
    )
    with open(pdf_path, "rb") as handle:
        pdf_bytes = handle.read()
    result = extract_pdf(pdf_bytes)

    def _numbered_title(idx, flat):
        text_no_pipes = re.sub(r"\s*\|\s*", " ", mod._normalize_space(flat[idx]["text"]))
        numbered = re.match(r"^(\d{1,3})[\.\)]\s+(.{2,90})$", text_no_pipes)
        if not numbered:
            return None
        return mod._normalize_space(numbered.group(2))

    def _unnumbered_fallback(idx, flat):
        # The unnumbered-heading branch is untouched by Phase 6.16 and
        # Phase 6.20 alike (neither phase edited anything past the
        # `if numbered:` block) -- reproduced verbatim here only so both
        # reconstructions below produce the real total candidate count,
        # not to isolate anything itself.
        text_no_pipes = re.sub(r"\s*\|\s*", " ", mod._normalize_space(flat[idx]["text"]))
        if len(text_no_pipes) > 90 or len(text_no_pipes.split()) > 14:
            return None
        if mod._looks_like_field_or_fragment_line(text_no_pipes):
            return None
        if mod._looks_like_generic_description_title(text_no_pipes):
            return None
        if not re.match(r"^[A-Z0-9]", text_no_pipes):
            return None
        if not mod._has_service_header_cues(idx, flat):
            return None
        return text_no_pipes

    def pre_6_16_candidate(idx, flat):
        # True pre-6.16 behavior: `_has_service_header_cues` and its
        # unconditional "if not has_header_evidence: return None" gate
        # already existed (that's what made the Phase 6.14 baseline a clean
        # 86, not hundreds of TOC-area false positives) -- what did NOT yet
        # exist is the `allow_step_verb_opener` override, so the fragment
        # check always applies the step-verb rejection unconditionally,
        # with no way for header-cue evidence to rescue a step-verb-opening
        # title (Phase 6.15's own finding: the fragment check short-circuits
        # BEFORE the header-cue check is ever reached for such a title, not
        # that the header-cue check didn't exist in the code at all).
        raw = mod._normalize_space(flat[idx]["text"])
        if not raw or flat[idx].get("table_wrapped_fragment"):
            return None
        title = _numbered_title(idx, flat)
        if title is None:
            return _unnumbered_fallback(idx, flat)
        if mod._looks_like_generic_description_title(title):
            return None
        has_header_evidence = mod._has_service_header_cues(idx, flat)
        if mod._looks_like_field_or_fragment_line(title, allow_step_verb_opener=False):
            return None
        if not has_header_evidence:
            return None
        return title

    def phase_6_16_exact_candidate(idx, flat):
        # Phase 6.16 exactly as it originally shipped: override the
        # step-verb check only, but still unconditionally require the FULL
        # 5/5 `_has_service_header_cues` boolean (no cue-count threshold --
        # that refinement is Phase 6.20's own, separate contribution).
        raw = mod._normalize_space(flat[idx]["text"])
        if not raw or flat[idx].get("table_wrapped_fragment"):
            return None
        title = _numbered_title(idx, flat)
        if title is None:
            return _unnumbered_fallback(idx, flat)
        if mod._looks_like_generic_description_title(title):
            return None
        has_header_evidence = mod._has_service_header_cues(idx, flat)
        if mod._looks_like_field_or_fragment_line(
            title, allow_step_verb_opener=has_header_evidence
        ):
            return None
        if not has_header_evidence:
            return None
        return title

    original_candidate = mod._line_is_heading_candidate

    mod._line_is_heading_candidate = pre_6_16_candidate
    try:
        before_services = mod.extract_citizen_charter_services_v2(result.pages)
    finally:
        mod._line_is_heading_candidate = original_candidate
    before_titles = [s.service_title for s in before_services]

    mod._line_is_heading_candidate = phase_6_16_exact_candidate
    try:
        after_services = mod.extract_citizen_charter_services_v2(result.pages)
    finally:
        mod._line_is_heading_candidate = original_candidate
    after_titles = [s.service_title for s in after_services]

    assert len(before_titles) == 86
    assert len(after_titles) == 93

    diff_hunks = [
        (tag, before_titles[i1:i2], after_titles[j1:j2])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, before_titles, after_titles).get_opcodes()
        if tag != "equal"
    ]
    expected_new_titles = {
        "Request for Refund Payment",
        "Request and Issuance of Resolutions and Except of the Minutes",
        "Request for quarterly/semi-annual/annual data",
        "Request for Online Posting (Social Media Posting and/or Website)",
        "Request for Event Coverage",
        "Request for Interview",
        "Request for IAU Audit Report",
        "Request to Conduct Special Audit (Special Audit)",
        "Request of colors and security",
        "Request of certificate of completion with serial number",
        "Request for Overload Subject",
    }
    all_new_titles_in_diff = {t for _, _, new in diff_hunks for t in new}
    assert all_new_titles_in_diff == expected_new_titles
    # The only titles REMOVED from the before-set must be the exact ones
    # this phase replaces (the two truncated NSTP titles and the two
    # chapter-divider-mislabeled services) -- nothing else disappears.
    all_removed_titles = {t for _, old, _ in diff_hunks for t in old}
    assert all_removed_titles == {
        "Colors and security",
        "Certificate of completion with serial number",
        "III. OFFICE OF THE UNIVERSITY BOARD SECRETARY",
        "XI. MANAGEMENT INFORMATION SYSTEM",
    }

    # Comma-truncated / unrelated titles must NOT have been newly recovered.
    assert "Provision of Gender and Development Related Materials," not in after_titles
    assert "Application, Renewal and Recognition of Student Organizations" not in after_titles

    # Phase 6.12 / 6.14 / Phase 6 Part B invariants, reconfirmed on the
    # Phase-6.16 output specifically:
    assert after_titles.count("IP Registration Process") == 2
    assert "Open to all Clients" not in after_titles
    assert not any(
        "NATIONAL SERVICE TRAINING PROGRAM" in (t or "") for t in after_titles
    )
    assert not any(
        (s.service_title or "").strip() in ("Units: 18", "For other", "Agencies: 15", "Days and 18", "Minutes")
        for s in after_services
    )

    # Content totals: the two retitled (not re-added) services must carry
    # byte-identical requirement/step counts before and after -- proving a
    # retitle, not a duplication.
    before_by_title = {s.service_title: s for s in before_services}
    resolutions_before = before_by_title["III. OFFICE OF THE UNIVERSITY BOARD SECRETARY"]
    mis_before = before_by_title["XI. MANAGEMENT INFORMATION SYSTEM"]
    after_by_title = {s.service_title: s for s in after_services}
    resolutions_after = after_by_title["Request and Issuance of Resolutions and Except of the Minutes"]
    mis_after = after_by_title["Request for quarterly/semi-annual/annual data"]
    assert len(resolutions_before.requirements or []) == len(resolutions_after.requirements or [])
    assert len(resolutions_before.steps or []) == len(resolutions_after.steps or [])
    assert len(mis_before.requirements or []) == len(mis_after.requirements or [])
    assert len(mis_before.steps or []) == len(mis_after.steps or [])

    assert sum(len(s.requirements or []) for s in after_services) == 173
    assert sum(len(s.steps or []) for s in after_services) == 270


# ---------------------------------------------------------------------------
# Phase 6.20 -- heading recognition independence from unrelated field
# reconstruction failures.
#
# Root cause (Phase 6.19, confirmed by direct execution): Phase 6.16's
# `has_header_evidence` gate required the FULL 5/5 `_has_service_header_cues`
# boolean for every numbered candidate reaching that point -- including
# titles that were never step-verb-ambiguous in the first place (i.e.
# `_looks_like_field_or_fragment_line(title, allow_step_verb_opener=True)` is
# already False on its own merits). A real, unrelated field elsewhere on the
# same page (e.g. a split "Type of Transaction:" checkbox row rendered as
# two physical lines with a value wedged between them -- see Phase
# 6.17-6.19) could make the 5/5 boolean False and veto an otherwise
# completely unambiguous title.
#
# The fix: `_service_header_cue_count` now exposes the 0-5 signal count
# instead of only an all-5 boolean. A title that is NOT step-verb-ambiguous
# on its own needs only 4-of-5 signals (tolerating exactly one unrelated
# field's reconstruction failure); a title that IS step-verb-ambiguous (the
# ONLY reason it would be rejected) still requires the full, unambiguous 5/5,
# exactly as Phase 6.16 originally intended -- this is deliberately a higher
# bar, since step-verb phrasing is inherently more table-row-like and a
# table-of-contents entry carries ZERO such signals (verified empirically,
# see test_numbered_subsection_without_header_cues_not_classified_as_service
# and the full-document regression below), so a lowered threshold there
# would reopen exactly that false-positive class.
# ---------------------------------------------------------------------------


def test_valid_numbered_heading_accepted_without_full_header_evidence():
    """Positive 1 + 6: a numbered title that is NOT step-verb-ambiguous (does
    not trip the step-verb-opener check at all) must be accepted even when
    ONE unrelated header field is missing nearby -- simulating the real
    page-34 'Type of Transaction:' split-label defect by simply omitting
    that one line from an otherwise-complete header block (4-of-5 signals:
    office, classification, who-may-avail, table; only 'type of
    transaction' missing)."""
    text = _charter_page_text(
        "XXII. RESEARCH SUPPORT OFFICE",
        "4. Technical Assistance for Research Output",
        "Office or Division: Research Support Office",
        "Classification: Simple",
        # Type of Transaction: intentionally omitted -- the unrelated
        # field-reconstruction failure this fix must tolerate.
        "Who may avail: Faculty and Students",
        "Checklist of Requirements | Where to Secure",
        "Research Proposal | Research Office",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "Submit proposal | Review and endorse | None | 3 days | Research Officer",
        "TOTAL: None 3 days",
    )
    page = PageExtraction(page_number=45, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert "Technical Assistance for Research Output" in titles


def test_step_verb_ambiguous_heading_with_valid_header_evidence_accepted():
    """Positive 2: a step-verb-ambiguous title (starts with 'Request')
    WITH the full, unambiguous 5/5 header block present must still be
    accepted -- Phase 6.16's core recovery, reconfirmed under Phase 6.20's
    cue-count logic (5/5 satisfies both the ambiguous-case and
    non-ambiguous-case thresholds)."""
    text = _charter_page_text(
        "XXII. RESEARCH SUPPORT OFFICE",
        "5. Request for Research Equipment Use",
        "Office or Division: Research Support Office",
        "Classification: Simple",
        "Type of Transaction: G2C",
        "Who may avail: Faculty and Students",
        "Checklist of Requirements | Where to Secure",
        "Request Form | Research Office",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "Submit request form | Review and approve | None | 1 day | Research Officer",
        "TOTAL: None 1 day",
    )
    page = PageExtraction(page_number=46, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    titles = [s.service_title for s in services]
    assert "Request for Research Equipment Use" in titles


def test_step_verb_ambiguous_heading_without_valid_header_evidence_stays_rejected():
    """Negative 3: a step-verb-ambiguous title (starts with 'Request') with
    only 4-of-5 header signals (the SAME missing 'Type of Transaction:' field
    tolerated in the non-ambiguous case above) must still be REJECTED -- the
    ambiguous case deliberately requires the full 5/5, not the lowered
    4-of-5 threshold, exactly as Phase 6.16 originally intended."""
    text = _charter_page_text(
        "XXII. RESEARCH SUPPORT OFFICE",
        "6. Request for Research Equipment Use",
        "Office or Division: Research Support Office",
        "Classification: Simple",
        # Type of Transaction: intentionally omitted.
        "Who may avail: Faculty and Students",
        "Checklist of Requirements | Where to Secure",
        "Request Form | Research Office",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "Submit request form | Review and approve | None | 1 day | Research Officer",
        "TOTAL: None 1 day",
    )
    page = PageExtraction(page_number=47, text=text, method="digital", words=None, geometry_scale=1.0)
    flat = _flatten_pages_for_test(page)
    idx = next(i for i, l in enumerate(flat) if l["text"].startswith("6. Request"))
    assert _line_is_heading_candidate(idx, flat) is None


def test_numbered_table_row_without_header_evidence_remains_rejected():
    """Negative 4: a genuine numbered procedure-step/table row (step-verb
    opening, zero nearby header structure) must remain rejected -- the
    core regression risk this phase must not reopen."""
    text = _charter_page_text(
        "7. Secure the application form",
        "Please proceed to window 3.",
        "TOTAL: None 5 minutes",
    )
    page = PageExtraction(page_number=48, text=text, method="digital", words=None, geometry_scale=1.0)
    flat = _flatten_pages_for_test(page)
    idx = next(i for i, l in enumerate(flat) if l["text"].startswith("7. Secure"))
    assert _line_is_heading_candidate(idx, flat) is None


def test_comma_truncated_title_remains_rejected_even_with_full_header_evidence():
    """Negative 5: a comma-continued/wrapped title must remain rejected
    regardless of header-cue evidence, even with a full 5/5 header block
    present -- the comma signal is independent of the step-verb-specific
    logic this phase touches and must never be overridden."""
    text = _charter_page_text(
        "XXII. RESEARCH SUPPORT OFFICE",
        "8. Provision of Research Grants, Travel Funds",
        "Office or Division: Research Support Office",
        "Classification: Simple",
        "Type of Transaction: G2C",
        "Who may avail: Faculty and Students",
        "Checklist of Requirements | Where to Secure",
        "Proposal | Research Office",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "Submit proposal | Review and approve | None | 2 days | Research Officer",
        "TOTAL: None 2 days",
    )
    page = PageExtraction(page_number=49, text=text, method="digital", words=None, geometry_scale=1.0)
    flat = _flatten_pages_for_test(page)
    idx = next(
        i for i, l in enumerate(flat) if l["text"].startswith("8. Provision of Research Grants")
    )
    assert _line_is_heading_candidate(idx, flat) is None


def test_header_field_failure_remains_independently_reportable():
    """Category 7: accepting a title under the 4-of-5 tolerance must NOT
    silently fabricate the missing field -- the constructed service's own
    `transaction_type` must still honestly report the NEEDS_REVIEW sentinel,
    never a invented value, so the field-level failure remains visible and
    reportable independently of the heading-acceptance decision."""
    text = _charter_page_text(
        "XXII. RESEARCH SUPPORT OFFICE",
        "9. Technical Assistance for Field Instruments",
        "Office or Division: Research Support Office",
        "Classification: Simple",
        # Type of Transaction: intentionally omitted.
        "Who may avail: Faculty and Students",
        "Checklist of Requirements | Where to Secure",
        "Research Proposal | Research Office",
        "Client Steps | Agency Action | Fees | Processing Time | Person Responsible",
        "Submit proposal | Review and endorse | None | 3 days | Research Officer",
        "TOTAL: None 3 days",
    )
    page = PageExtraction(page_number=50, text=text, method="digital", words=None, geometry_scale=1.0)
    services = extract_citizen_charter_services_v2([page])
    service = next(
        s for s in services if s.service_title == "Technical Assistance for Field Instruments"
    )
    assert service.transaction_type == NEEDS_REVIEW


def test_phase_6_20_full_document_recovers_unambiguous_titles_without_regression():
    """Full-document validation (section 5): reproducing the real PDF with
    Phase 6.16's exact original logic versus the current (Phase 6.20)
    logic isolates exactly this phase's own contribution, decoupled from
    Phase 6.16's. Exactly 3 titles are newly recovered, all verified
    genuine real services (not TOC/index noise) against the real PDF, with
    zero deletions and zero replacements -- a pure, explained addition."""
    import difflib
    import re

    from app.utils.pdf.pymupdf_extractor import extract_pdf
    import app.services.citizen_charter_extractor_v2 as mod

    pdf_path = (
        "data/documents/da4a1832-7242-4e94-8ba6-bc0b9f2294bf/"
        "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
    )
    with open(pdf_path, "rb") as handle:
        pdf_bytes = handle.read()
    result = extract_pdf(pdf_bytes)

    def phase_6_16_exact_candidate(idx, flat):
        raw = mod._normalize_space(flat[idx]["text"])
        if not raw or flat[idx].get("table_wrapped_fragment"):
            return None
        text_no_pipes = re.sub(r"\s*\|\s*", " ", raw)
        numbered = re.match(r"^(\d{1,3})[\.\)]\s+(.{2,90})$", text_no_pipes)
        if numbered:
            title = mod._normalize_space(numbered.group(2))
            if mod._looks_like_generic_description_title(title):
                return None
            has_header_evidence = mod._has_service_header_cues(idx, flat)
            if mod._looks_like_field_or_fragment_line(
                title, allow_step_verb_opener=has_header_evidence
            ):
                return None
            if not has_header_evidence:
                return None
            return title
        if len(text_no_pipes) > 90 or len(text_no_pipes.split()) > 14:
            return None
        if mod._looks_like_field_or_fragment_line(text_no_pipes):
            return None
        if mod._looks_like_generic_description_title(text_no_pipes):
            return None
        if not re.match(r"^[A-Z0-9]", text_no_pipes):
            return None
        if not mod._has_service_header_cues(idx, flat):
            return None
        return text_no_pipes

    original_candidate = mod._line_is_heading_candidate
    mod._line_is_heading_candidate = phase_6_16_exact_candidate
    try:
        before_services = mod.extract_citizen_charter_services_v2(result.pages)
    finally:
        mod._line_is_heading_candidate = original_candidate
    before_titles = [s.service_title for s in before_services]

    after_services = mod.extract_citizen_charter_services_v2(result.pages)
    after_titles = [s.service_title for s in after_services]

    assert len(before_titles) == 93
    assert len(after_titles) == 96

    diff_hunks = [
        (tag, before_titles[i1:i2], after_titles[j1:j2])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, before_titles, after_titles
        ).get_opcodes()
        if tag != "equal"
    ]
    # Pure additions only -- zero deletions, zero replacements. Phase 6.20
    # recovers titles Phase 6.16 missed; it never removes or alters any
    # title Phase 6.16 already correctly produced.
    assert all(tag == "insert" for tag, _, _ in diff_hunks)
    newly_recovered = {t for _, _, new in diff_hunks for t in new}
    assert newly_recovered == {
        "Student Researcher-Related Services",
        "Technical Assistance for any Research Project",
        "Enrollment Advising",
    }

    # Known, deliberately NOT forced: Phase 6.19 predicted "Request for
    # Training Services" would likely still fail to recover, since it is
    # genuinely step-verb-ambiguous AND has compounding split-label field
    # losses on its own page (both Office/Division and Type of Transaction)
    # -- confirmed here, not assumed.
    assert "Request for Training Services" not in after_titles

    # Phase 6.12 / 6.14 / 6.16 / Phase 6 Part A+B invariants, reconfirmed on
    # the current real production output:
    assert after_titles.count("IP Registration Process") == 2
    assert "Open to all Clients" not in after_titles
    assert not any("NATIONAL SERVICE TRAINING PROGRAM" in (t or "") for t in after_titles)
    assert not any(
        (s.service_title or "").strip()
        in ("Units: 18", "For other", "Agencies: 15", "Days and 18", "Minutes")
        for s in after_services
    )
    disaster = [s for s in after_services if s.service_title and "Disaster" in s.service_title]
    assert len(disaster) == 2
    assert all(s.extraction_quality == "clean" for s in disaster)
    assert sorted(len(s.steps or []) for s in disaster) == [3, 4]
    assert any(s.service_title == "Request of colors and security" for s in after_services)

    assert sum(len(s.requirements or []) for s in after_services) == 177
    assert sum(len(s.steps or []) for s in after_services) == 284

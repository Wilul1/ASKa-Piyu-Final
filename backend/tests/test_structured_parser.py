from app.services.structured_document_parser import (
    build_structured_document,
    classify_document_type,
    format_structured_document,
    parse_structured_document,
)

SAMPLE_OCR = """
--- Page 1 ---
Guidance Office LSPU Entrance Test
Service: LSPU Entrance Tesling
Office: Guidance and Couns?eling Office
Requirements: LOnline Application; Certlied True Copy of Report Card
Steps: 1 Orientation on Entrance Exam Process 2 Examination Monitoring 3 Release of Results
Processing Time: 1-3 Days
Handled By: Guidance Staff
"""


def test_parses_service_card_fields():
    doc = build_structured_document(SAMPLE_OCR)
    labels = [f.label for f in doc.fields]
    assert "Service" in labels
    assert "Office" in labels
    assert "Requirements" in labels
    assert "Steps" in labels

    service = next(f for f in doc.fields if f.label == "Service")
    assert "Entrance" in (service.value or "")

    reqs = next(f for f in doc.fields if f.label == "Requirements")
    assert reqs.field_type == "list"
    assert len(reqs.items) >= 1


def test_formatted_text_has_labels():
    doc = build_structured_document(SAMPLE_OCR)
    assert "Service:" in doc.formatted_text
    assert "Office:" in doc.formatted_text
    assert "Classification:" in doc.formatted_text
    assert "Transaction Type:" in doc.formatted_text
    assert "Who May Avail:" in doc.formatted_text


def test_removes_table_headers_from_noisy_steps():
    noisy = """
    Service: LSPU Entrance Test (LSPU College Entrance Test) Testing
    Office: LSPU Entrance Test Testing
    Requirements: ITo UNERE To SECURE LOnline application LSPU Online Admission Certlied True Copy (IRepont Card andlor Client TOR FEES PROCESSING PERSON CLIENT
    Steps:
    1. AGENCY TO BE TIME RESPONSIBLE ACTIONS PAID Orientation Inform the clients NIA 15 minutes Guidance Staff about the college entrance examination
    2. AGENCY TO BE TIME RESPONSIBLE ACTIONS PAID Endorsement Received the minutes Guidance Staff referral
    8. fiica or
    9. AGENCY TO BE TIME RESPONSIBLE ACTIONS PAID Endorsement, Received the minutes Guidance Staff referral walk-in clients Scheduling of client
    """

    doc = build_structured_document(noisy)
    steps = next(field for field in doc.fields if field.label == "Steps")

    assert len(steps.items) == 3
    assert all("AGENCY TO BE TIME" not in item for item in steps.items)
    assert all("fiica" not in item.lower() for item in steps.items)
    assert "Online application" in doc.formatted_text


def test_charter_pipe_table_drops_header_fragments_and_fixes_office():
    sample = """
4. ID Validation
Office or Division | Office of the Student Affairs and Services
Classification: Simple
Who May Avail: All
Checklist of Requirements | Where to Secure
Certificate of Registration | Registrar Office
Student ID | Business Affairs Office
CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
BE | TIME | RESPONSIBLE
1. Present the Certificate of Registration. | Check Certificate of Registration. | None | 1 minute | OSAS Director/Chairperson/Staff
2. Evaluate the services rendered by OSAS. | Issue Evaluation Form. | None | 2 minutes | OSAS Director/Chairperson/Staff
3. Accept the validated ID. | Release validated ID. | None | 1 minute | OSAS Director/Chairperson/Staff
TOTAL: None | 4 minutes
"""
    parsed = parse_structured_document(sample)
    assert parsed["document_type"] == "citizen_charter"
    service = parsed["services"][0]
    assert service["service"] == "ID Validation"
    assert service["office"] == "Office of the Student Affairs and Services"
    assert service["office"] != "or Division"
    assert service["total_processing_time"] == "4 minutes"
    assert service["total_fees"] == "None"
    assert len(service["requirements"]) == 2
    assert service["requirements"][0]["requirement"] == "Certificate of Registration"
    assert len(service["steps"]) == 3
    assert all(
        "BE" not in (step.get("client_step") or "")
        and "TIME" not in (step.get("agency_action") or "")
        and "RESPONSIBLE" != (step.get("responsible_personnel") or "")
        for step in service["steps"]
    )
    assert service["steps"][0]["client_step"].startswith("Present the Certificate")
    assert service["parser_debug"]["rejected_fake_steps"] >= 1
    assert service["parser_debug"]["requirement_pairs_detected"] == 2
    assert service["parser_debug"]["total_line_detected"] is True


def test_charter_rejects_page_number_and_fragment_titles():
    from app.services.structured_document_parser import _clean_service_title

    assert _clean_service_title("72") == ""
    assert _clean_service_title("00") == ""
    assert _clean_service_title("equipment") == ""
    assert _clean_service_title("Services") == ""
    assert _clean_service_title("4. LSPU Entrance Examination") == "LSPU Entrance Examination"
    assert _clean_service_title("Use of Library Facilities and Equipment") == (
        "Use of Library Facilities and Equipment"
    )


def test_formats_university_service_template():
    doc = build_structured_document(
        """
        Office or Division: Guidance Office
        Service: College Entrance Test
        Classification: Simple
        Transaction Type: G2C
        Who May Avail: Incoming students
        CHECKLIST OF REQUIREMENTS WHERE TO SECURE
        Requirements: Online application; Certified True Copy of Report Card
        CLIENT STEPS AGENCY ACTIONS FEES TO BE PAID PROCESSING TIME RESPONSIBLE PERSONNEL
        Steps: 1. Submit application 2. Take examination
        Processing Time: 1-3 days
        Responsible Personnel: Guidance Staff
        """
    )

    assert doc.formatted_text.startswith("Office: Guidance Office")
    assert "Service: College Entrance Test" in doc.formatted_text
    assert "Requirements:\n  - Requirement: Online application" in doc.formatted_text
    assert "Where to Secure:" in doc.formatted_text
    assert "Steps:\n  1. Client Step: Submit application" in doc.formatted_text
    assert "Agency Action:" in doc.formatted_text
    assert "Fees:" in doc.formatted_text
    assert "Responsible Personnel: Guidance Staff" in doc.formatted_text
    assert "Total Processing Time: 1-3 days" in doc.formatted_text
    assert "CLIENT STEPS" not in doc.formatted_text


def test_marks_unclear_ocr_words_for_review():
    doc = build_structured_document("Office: Registrar Ser?ice: Transcript Request")

    assert "[NEEDS REVIEW]" in doc.formatted_text


def test_missing_template_values_need_review():
    doc = build_structured_document("Service: Transcript Request")

    assert "Office: [NEEDS REVIEW]" in doc.formatted_text
    assert "Classification: [NEEDS REVIEW]" in doc.formatted_text
    assert "  - Requirement: [NEEDS REVIEW]" in doc.formatted_text
    assert "Agency Action: [NEEDS REVIEW]" in doc.formatted_text
    assert "Total Processing Time: [NEEDS REVIEW]" in doc.formatted_text


def test_parses_pipe_delimited_university_form_tables():
    doc = build_structured_document(
        """
        LSPU Entrance Test (LSPU College Entrance Test)
        Office Division Guidance and Counseling
        Classification: | Simple
        Type | G2C
        Transaction
        Who CHECKUISTOE REQUIRET Wel | Student-applicants I7o | UNERE To SECURE
        Checklist of Requirements | Where to Secure
        Online application | LSPU Online Admission
        Certified True Copy (Report Card and/or TOR) | Client
        CLIENT STEPS | AGENCY | FEES TO BE PROCESSING TIME | RESPONSIBLE PERSON
        ACTIONS | PAID
        Orientation | Inform the clients N/A | 15 minutes | Guidance Staff
        about the college entrance examination
        Examination | Monitoring during the examination | N/A | 1 and 1/2 hours | Guidance Staff and interns
        Examination result | Issuance of the official result to examinees | N/A | 1-3 days | Guidance Staff
        Total: 1-3 days, 1 hr and 45 minutes
        """
    )

    text = doc.formatted_text

    assert "Office: Guidance and Counseling" in text
    assert "Classification: Simple" in text
    assert "Transaction Type: G2C" in text
    assert "Who May Avail: Student-applicants" in text
    assert "Requirement: Online application" in text
    assert "Where to Secure: LSPU Online Admission" in text
    assert "Client Step: Orientation" in text
    assert "Agency Action: Inform the clients about the college entrance examination" in text
    assert "Fees: N/A" in text
    assert "Processing Time: 15 minutes" in text
    assert "Responsible Personnel: Guidance Staff" in text
    assert "Total Processing Time: 1-3 days, 1 hr and 45 minutes" in text


def test_infers_appraisal_service_title_dynamically():
    doc = build_structured_document(
        """
        2. Appraisal
        Administration and interpretation of appraisal
        Office or Division Guidance and Counseling
        Classification: | Simple
        Type Transaction: | G2G G2C
        Who | Students Faculty, Non- Teaching Job Applicants
        Checklist of Requirements | Where to Secure
        Data Privacy Consent | Client
        Identification Card | Guidance and Counseling
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | RESPONSIBLE PERSON
        Endorsement | Received the endorsement | N/A | minutes | Guidance personnel
        Total: 3 days
        """
    )

    text = doc.formatted_text

    assert "Service: Appraisal" in text
    assert "Who May Avail: Students Faculty, Non- Teaching Job Applicants" in text
    assert "Requirement: Data Privacy Consent" in text
    assert "Where to Secure: Client" in text


def test_infers_counseling_service_title_dynamically():
    doc = build_structured_document(
        """
        Counseling
        Facilitation of counseling service.
        Office or Division Guidance and Counseling
        Classification | Simple
        Type Transaction: | G2G G2C
        Who May Avail: Students
        Checklist of Requirements | Where to Secure
        Data Privacy Consent | Client
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | RESPONSIBLE PERSON
        Counseling proper | Administration and conduct of counseling | N/A | 1-2 hours | Guidance Counselor
        Total: 1-2 hours and 17 minutes
        """
    )

    assert "Service: Counseling" in doc.formatted_text


def test_splits_merged_processing_time_and_responsible_personnel():
    doc = build_structured_document(
        """
        Appraisal
        Office or Division Guidance and Counseling
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID PROCESSING TIME | RESPONSIBLE PERSON
        Endorsement | Received the | minutes Guidance personnelllllll
        Total: 3 days
        """
    )

    text = doc.formatted_text

    assert "Processing Time: minutes" in text
    assert "Responsible Personnel: Guidance personnel" in text


def test_continuation_rows_do_not_become_separate_client_steps():
    doc = build_structured_document(
        """
        Appraisal
        Office or Division Guidance and Counseling
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID PROCESSING TIME | RESPONSIBLE PERSON
        Endorsement | Received the | minutes Guidance personnel
        referral; walk-in | endorsement, referral, walk-in clients. Scheduling client:
        Administration of | Prepare the testing | hours Guidance personnel
        proper) | booklet and answer sheet
        Total: 3 days
        """
    )

    steps = next(field for field in doc.fields if field.label == "Steps")

    assert len(steps.items) == 2
    assert "Endorsement referral; walk-in" in steps.items[0]
    assert "Administration of proper)" in steps.items[1]


def test_guidance_rows_extract_time_personnel_and_fees_without_hardcoded_values():
    doc = build_structured_document(
        """
        2. Appraisal
        Administration and interpretation of appraisal
        Office or Division Guidance and Counseling
        Classification: | Simple
        Type Transaction: | G2G G2C
        Who | Students Faculty, Non- Teaching Job Applicants
        Checklist of Requirements | Where to Secure
        Data Privacy Consent | Client
        Identification Card | Guidance and Counseling
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | RESPONSIBLE PERSON
        Endorsement | Received the endorsement, referral, walk-in clients. Scheduling client | n/a | 5 minutes | Guidance personnel
        Administration of Appraisal (Examination proper) | Prepare the testing materials booklet and answer sheet | N/A | 4 hours | Guidance personnel
        Appraisal Interpretation | Interpretation of tests. Preparation of report | N/A | 1-3 days | Guidance personnel Guidance Counselor
        Total: 3 days
        """
    )

    text = doc.formatted_text

    assert "Requirement: Data Privacy Consent" in text
    assert "Where to Secure: Client" in text
    assert "Fees: N/A" in text
    assert "Processing Time: 5 minutes" in text
    assert "Processing Time: 4 hours" in text
    assert "Responsible Personnel: Guidance personnel" in text
    assert "Agency Action: Received the endorsement, referral, walk-in clients. Scheduling client" in text
    assert "Agency Action: Prepare the testing materials booklet and answer sheet" in text


def test_guidance_wrapped_rows_are_reconstructed_before_extraction():
    doc = build_structured_document(
        """
        Counseling
        Office or Division Guidance and Counseling
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | RESPONSIBLE PERSON
        Counseling briefing | Completion of data privacy consent | N/A | 2 minutes | Guidance Staff
        and student inventory form
        Counseling proper | Administration and conduct of counseling | N/A | 1-2 hours | Guidance Counselor
        Total: 1-2 hours and 17 minutes
        """
    )

    steps = next(field for field in doc.fields if field.label == "Steps")
    text = doc.formatted_text

    assert len(steps.items) == 2
    assert "Agency Action: Completion of data privacy consent and student inventory form" in text
    assert "Processing Time: 2 minutes" in text
    assert "Responsible Personnel: Guidance Staff" in text


def test_latest_guidance_output_recovers_requirement_rows_without_scanning_steps():
    doc = build_structured_document(
        """
        LSPU Entrance Test
        Office Division Guidance and Counseling
        Checklist of Requirements
        Online application | LSPU Online Admission
        Certified True Copy of Report Card and/or TOR | Client
        CLIENT STEPS | AGENCY | FEES TO BE PROCESSING TIME | RESPONSIBLE PERSON
        Orientation | Inform the clients N/A | 15 minutes | Guidance Staff
        """
    )

    text = doc.formatted_text

    assert "Requirement: Online application" in text
    assert "Where to Secure: LSPU Online Admission" in text
    assert "Requirement: Certified True Copy of Report Card and/or TOR" in text
    assert "Where to Secure: Client" in text
    assert "Requirement: Orientation" not in text


def test_latest_guidance_rows_remove_leading_time_and_personnel_from_agency_action():
    doc = build_structured_document(
        """
        Counseling
        Office or Division Guidance and Counseling
        Who malyavaiE
        Students
        CLIENT STEPS | AGENCY ACTIONS | FEES To BE PROCESSING TIME | RESPONSIBLE PERSON
        Counseling briefing | 15 minutes Guidance Staff privacy consent and student inventory form | N/A
        Counseling proper | 1-2 hours Guidance Counselor conduct of counseling | n/a
        Total: 1-2 hours and 17 minutes
        """
    )

    text = doc.formatted_text

    assert "Who May Avail: Students" in text
    assert "Processing Time: 15 minutes" in text
    assert "Responsible Personnel: Guidance Staff" in text
    assert "Agency Action: privacy consent and student inventory form" in text
    assert "Processing Time: 1-2 hours" in text
    assert "Responsible Personnel: Guidance Counselor" in text
    assert "Agency Action: conduct of counseling" in text
    assert "Fees: N/A" in text


def test_latest_guidance_preserves_numbered_time_when_cell_has_unit_only():
    doc = build_structured_document(
        """
        Appraisal
        Office or Division Guidance and Counseling
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID PROCESSING TIME | RESPONSIBLE PERSON
        Administration of Appraisal | Prepare testing materials | N/A | 4 hours Guidance personnel
        Briefing | Inform client | N/A | 5 minutes Guidance Staff
        """
    )

    text = doc.formatted_text

    assert "Processing Time: 4 hours" in text
    assert "Processing Time: 5 minutes" in text


def test_requirement_recovery_ignores_client_step_rows():
    parsed = parse_structured_document(
        """
        Office or Division Student Affairs
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | RESPONSIBLE PERSON
        Orientation | Inform the clients | N/A | 15 minutes | Staff
        Total: 15 minutes
        """
    )

    reqs = parsed["services"][0]["requirements"]
    assert reqs == [{"requirement": "[NEEDS REVIEW]", "where_to_secure": "[NEEDS REVIEW]"}]


def test_requirement_recovery_does_not_parse_handbook_tables():
    parsed = parse_structured_document(
        """
        Chapter 3 Student Discipline
        Violation | Sanction
        Late ID | Warning
        Section 3.1 General Rules
        """
    )

    reqs = parsed["services"][0]["requirements"]
    assert reqs == [{"requirement": "[NEEDS REVIEW]", "where_to_secure": "[NEEDS REVIEW]"}]


def test_requirement_recovery_does_not_parse_memo_tables():
    parsed = parse_structured_document(
        """
        Memorandum
        Date: June 10, 2026
        To | From
        Campus Directors | Student Affairs
        Subject: Enrollment Schedule
        """
    )

    reqs = parsed["services"][0]["requirements"]
    assert reqs == [{"requirement": "[NEEDS REVIEW]", "where_to_secure": "[NEEDS REVIEW]"}]


def test_who_recovery_stops_before_requirements():
    parsed = parse_structured_document(
        """
        Office or Division Student Affairs
        Service: Sample Service
        Who May Avail
        Students and Faculty
        Checklist of Requirements | Where to Secure
        Valid ID | Client
        """
    )

    assert parsed["services"][0]["who_may_avail"] == "Students and Faculty"


def test_numbered_time_does_not_use_section_or_page_numbers():
    doc = build_structured_document(
        """
        Office or Division Student Affairs
        CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID PROCESSING TIME | RESPONSIBLE PERSON
        Read policy | See Section 4 hours of operation | N/A | hours Staff
        """
    )

    text = doc.formatted_text
    assert "Processing Time: hours" in text
    assert "Processing Time: 4 hours" not in text


def test_parses_cropped_user_access_form_without_citizen_charter_fields():
    parsed = parse_structured_document(
        """
        Republic of the Philippines
        Laguna State Polytechnic University
        ICT SERVICES
        User Access and Password Application Form
        Form Code: LSPU ICTS 5F-0O2
        REV. 0
        Date: 10 August 2016

        Name: ______________________
        College/Office: _____________
        Date: ______________________
        Type of account: [ ] Email [ ] My Account [ ] WiFi [ ] Intranet [ ] Others
        Type of request: [ ] New Account [ ] Reset Password [ ] Activate Account [ ] Deactivate Account [ ] Others
        User Name: _________________
        Description: _______________
        Requestor Signature: ________
        Approved: __________________
        """
    )

    form = parsed["form"]

    assert parsed["document_type"] == "requirement"
    assert form["office"] == "ICT Services"
    assert form["office_detection_source"] == "extracted_from_document"
    assert form["form_name"] == "User Access and Password Application Form"
    assert form["form_code"] == "LSPU-ICTS-SF-002"
    assert form["revision"] == "REV. 0"
    assert form["date"] == "10 August 2016"
    assert "Name" in form["fields"]
    assert "Client Steps" not in form["fields"]
    assert "Processing Time" not in form["fields"]
    assert form["options"]["type_of_account"] == ["Email", "My Account", "Wifi", "Intranet", "Others"]
    assert form["options"]["type_of_request"] == [
        "New Account",
        "Reset Password",
        "Activate Account",
        "Deactivate Account",
        "Others",
    ]


def test_user_access_form_uses_header_title_and_strict_code_without_option_fields():
    parsed = parse_structured_document(
        """
        INFORMATION AND COMMUNICATION TECHNOLOGY SERVICES
        USER ACCESS AND PASSWORD
        APPLICATION FORM

        NAME: __________________________
        COLLEGE/OFFICE: ________________
        DATE: __________________________
        TYPE OF ACCOUNT: [ ] Email [ ] My Account [ ] WiFi [ ] Intranet [ ] Others
        TYPE OF REQUEST: [ ] New Account [ ] Reset Password [ ] Activate Account [ ] Deactivate Account [ ] Others
        USER NAME: _____________________
        DESCRIPTION: ___________________
        REQUESTOR SIGNATURE: ___________
        APPROVED: ______________________

        ICT Servicing Staff ICTS Copy LSPU ICTS SF 002
        """
    )

    form = parsed["form"]

    assert form["office"] == "Information and Communication Technology Services"
    assert form["office_detection_source"] == "extracted_from_document"
    assert form["form_name"] == "User Access and Password Application Form"
    assert form["form_code"] == "LSPU-ICTS-SF-002"
    assert form["fields"] == [
        "Name",
        "College/Office",
        "Date",
        "Type of Account",
        "Type of Request",
        "User Name",
        "Description",
        "Requestor Signature",
        "Approved",
    ]
    assert form["options"]["type_of_account"] == ["Email", "My Account", "Wifi", "Intranet", "Others"]
    assert form["options"]["type_of_request"] == [
        "New Account",
        "Reset Password",
        "Activate Account",
        "Deactivate Account",
        "Others",
    ]
    assert "Email" not in form["fields"]
    assert "ICT Servicing Staff" not in form["sections"]


def test_form_title_office_and_field_labels_are_not_sections():
    parsed = parse_structured_document(
        """
        INFORMATION AND COMMUNICATION TECHNOLOGY SERVICES
        USER ACCESS AND PASSWORD
        APPLICATION FORM

        NAME: __________________________
        COLLEGE/OFFICE: ________________
        DATE: __________________________
        TYPE OF ACCOUNT: [ ] Email [ ] WiFi

        APPROVAL
        APPROVED: ______________________
        LSPU ICTS SF 002
        """
    )

    form = parsed["form"]

    assert form["office"] == "Information and Communication Technology Services"
    assert form["office_detection_source"] == "extracted_from_document"
    assert form["form_name"] == "User Access and Password Application Form"
    assert form["sections"] == ["Approval"]
    assert "Information and Communication Technology Services" not in form["sections"]
    assert "User Access and Password" not in form["sections"]
    assert "Application Form" not in form["sections"]
    assert "Name" not in form["sections"]
    assert "Date" not in form["sections"]
    assert "College/Office" not in form["sections"]


def test_parses_request_for_ict_services_form_generically():
    parsed = parse_structured_document(
        """
        Information and Communications Technology Office
        Request for ICT Services Form
        Document Code: LSPU-ICTS-SF-001
        Revision: REV. 1
        Date: August 12, 2024

        Requested by: __________________
        College/Office: ________________
        Service requested: [ ] Repair [ ] Network Assistance [ ] Software Installation [ ] Others
        Description: ___________________
        Approved by: ___________________
        """
    )

    form = parsed["form"]

    assert parsed["document_type"] == "requirement"
    assert form["form_name"] == "Request for ICT Services Form"
    assert form["form_code"] == "LSPU-ICTS-SF-001"
    assert "Requested By" in form["fields"]
    assert "College/Office" in form["fields"]
    assert form["options"]["service_requested"] == [
        "Repair",
        "Network Assistance",
        "Software Installation",
        "Others",
    ]


def test_duplicate_form_copies_trigger_crop_warning():
    one_copy = """
    User Access and Password Application Form
    Form Code: LSPU-ICTS-SF-002
    Name: ______________________
    Type of account: [ ] Email [ ] WiFi
    """
    parsed = parse_structured_document("\n".join([one_copy, one_copy, one_copy, one_copy]))

    assert parsed["document_type"] == "requirement"
    assert parsed["form"]["warnings"] == [
        "Multiple identical form copies detected. Please crop or split before OCR."
    ]


def test_form_classification_prevents_citizen_charter_parsing():
    doc = build_structured_document(
        """
        User Access and Password Application Form
        LSPU ICTS 5F-002
        Name: ______________________
        Type of request: [ ] New Account [ ] Reset Password
        """
    )

    labels = [field.label for field in doc.fields]

    assert "Form Name" in labels
    assert "Client Steps" not in doc.formatted_text
    assert "Checklist of Requirements" not in doc.formatted_text


def test_form_code_normalization_works_during_classification():
    parsed = parse_structured_document(
        """
        Request Form
        Form Code: LSPU ICTS 5F-0O1
        Applicant Name: _______________
        """
    )

    assert classify_document_type("Request Form\nLSPU ICTS 5F-0O1\nApplicant Name: ___") == "form"
    assert parsed["form"]["form_code"] == "LSPU-ICTS-SF-001"


def test_parses_noisy_icts_technical_assistance_request_form():
    parsed = parse_structured_document(
        """
        icts TEcHNICAL AssISTANcE Request Form
        Form Code: LSPU ICTS SF 022

        rEQuESTERINFORMATION
        Requester Name: __________________
        College/Office: __________________
        Contact Number: __________________

        EVENT INFORMATION
        Event Title: _____________________
        Date Needed: _____________________

        Type of service requested:
        [ ] phoro Video Coverage
        [ ] Interner Connecion
        [ ] Visuai Preecnudlion support
        [ ] Encading

        SERVICE ASSESSMENT
        Rating: __________________________
        Comments: ________________________
        """
    )

    form = parsed["form"]

    assert parsed["document_type"] == "requirement"
    assert form["form_name"] == "Icts Technical Assistance Request Form"
    assert form["form_code"] == "LSPU-ICTS-SF-022"
    assert "Requester Information" in form["sections"]
    assert "Event Information" in form["sections"]
    assert "Service Assessment" in form["sections"]
    assert "Requester Name" in form["fields"]
    assert "College/Office" in form["fields"]
    assert form["options"]["type_of_service_requested"] == [
        "Phoro Video Coverage",
        "Interner Connecion",
        "Visuai Preecnudlion Support",
        "Encading",
    ]


def test_noisy_technical_assistance_form_ignores_headers_footer_roles_and_option_fields():
    parsed = parse_structured_document(
        """
        Republic of the Philippincs
        Province of Laguna
        Prowincu Ollaruna ICTS Technical Assistance Request Form

        Nomo: ______________________
        Collcec/Omcc; ______________
        Duic: ______________________
        Dale; ______________________
        Venve: _____________________
        Fma: _______________________

        Scnvices Needed:
        [ ] phoro Video Coverage
        [ ] Interner Connecion
        [ ] Visuai Preecnudlion support
        [ ] Encading
        [ ] Others

        Requested By: ______________
        Acceivcd By: _______________
        Approved Dy: _______________
        ICT, Sarvicing Staff
        ICTS Director /Chjirpurson: ______________
        Printod Mume 5 Enatute
        Signature Over Printed Name
        Director: __________________
        Chairperson: _______________
        Head of Office: ____________
        Authorized Representative: _

        LSPU-ICTS-SF-022 | Acv | August 2016
        """
    )

    form = parsed["form"]

    assert form["form_name"] == "ICTS Technical Assistance Request Form"
    assert form["form_code"] == "LSPU-ICTS-SF-022"
    assert form["revision"] == "REV. 0"
    assert form["date"] == "August 2016"
    assert "Services Needed" not in form["fields"]
    assert form["options"]["services_needed"] == [
        "Phoro Video Coverage",
        "Interner Connecion",
        "Visuai Preecnudlion Support",
        "Encading",
        "Others",
    ]
    assert "Name" in form["fields"]
    assert "College/Office" in form["fields"]
    assert "Date" in form["fields"]
    assert "Dale" not in form["fields"]
    assert "Venue" in form["fields"]
    assert "Time" in form["fields"]
    assert "Requested By" in form["fields"]
    assert "Received By" in form["fields"]
    assert "Approved By" in form["fields"]
    assert "ICT Servicing Staff" not in form["fields"]
    assert "ICTS Director / Chairperson" not in form["fields"]
    assert "ICT, Servicing Staff" not in form["fields"]
    assert "ICTS Director /Chairperson" not in form["fields"]
    assert "Printed Name & Signature" not in form["fields"]
    assert "Signature Over Printed Name" not in form["fields"]
    assert "Director" not in form["fields"]
    assert "Chairperson" not in form["fields"]
    assert "Head of Office" not in form["fields"]
    assert "Authorized Representative" not in form["fields"]
    assert "LSPU-ICTS-SF-022" not in form["fields"]
    assert "REV. 0" not in form["fields"]
    assert "August 2016" not in form["fields"]


def test_noisy_services_table_stops_before_role_and_free_text_fields():
    parsed = parse_structured_document(
        """
        INFORMATION AND COMMUNICATIONS TECHNOLOGY SERVICES
        icts TEcHNICAL AssISTANcE Request Form
        rEQuESTERINFORMATION
        Name | Contact number
        Collcec/omcc; | Date
        EVENT INFORMATION
        Venue:
        DAle; | Time
        Services Needed: | phoro Video Coverage | Interner Connecion
        Visuai Preecnudlion support | Encading
        Orhers (Plesse Specilyl;
        Wcma Netded;
        Requested by: | acceivcd by: | Approved By:
        Printed Name & Signature | ICT, Servicing Staff | ICTS Director /chJirpurson
        SERVICE ASSESSMENT
        LSPU-ICTS-SF-022 | Acv | August 2016
        """
    )

    form = parsed["form"]

    assert form["options_or_services"] == [
        "Phoro Video Coverage",
        "Interner Connecion",
        "Visuai Preecnudlion Support",
        "Encading",
        "Orhers (plesse Specilyl",
    ]
    assert "Wcma Netded" not in form["options_or_services"]
    assert "Acceivcd By" not in form["options_or_services"]
    assert "Approved By" not in form["options_or_services"]


def test_generic_strong_form_signals_route_to_form_parser_without_icts_title():
    parsed = parse_structured_document(
        """
        Facilities Management Office
        Facilities Maintenance Request
        LSPU-FMO-SF-123

        Requester Information
        Name: ______________________
        Department: ________________

        Service Report
        Services Needed:
        [ ] Electrical Repair
        [ ] Plumbing
        [ ] Carpentry

        Compliance Acknowledgement
        Requested By: ______________
        Approved By: _______________
        """
    )

    form = parsed["form"]

    assert classify_document_type(parsed["cleaned_text"]) == "form"
    assert parsed["document_type"] == "requirement"
    assert form["form_name"] == "Facilities Maintenance Request"
    assert form["form_code"] == "LSPU-FMO-SF-123"
    assert "Requester Information" in form["sections"]
    assert "Service Report" in form["sections"]
    assert "Compliance Acknowledgement" in form["sections"]
    assert "Name" in form["fields"]
    assert "Requested By" in form["fields"]
    assert "Approved By" in form["fields"]
    assert form["options"]["services_needed"] == ["Electrical Repair", "Plumbing", "Carpentry"]


def test_noisy_request_for_ict_services_omits_garbage_fields_and_recovers_sections():
    parsed = parse_structured_document(
        """
        Request for ICT Services
        LSPU-ICTS-SF-001
        Aukust 2016

        rEQuESTERINFORMATION
        Requester Name: _______________
        College/Office: _______________
        Contact Number: _______________
        @@@ }} [' 9Qx7zzzz: _________
        X7QTRPPLK: _________________

        icT 9ervicE 9 REQVESTED
        [ ] Network Assistance
        [ ] Computer Repair

        SERVICE REPORT
        Item Received: _______________
        Date Received: _______________
        Description of the Problem: __
        Assigned ICTS Personnel: _____
        Expected Finish Date/Time: ___
        Endorsement: ________________
        Signature: _________________
        """
    )

    form = parsed["form"]

    assert parsed["document_type"] == "requirement"
    assert form["office"] == "[NEEDS REVIEW]"
    assert form["office_detection_source"] == "unknown"
    assert form["date"] == "August 2016"
    assert "Requester Information" in form["sections"]
    assert "Ict Services Requested" in form["sections"]
    assert "Service Report" in form["sections"]
    assert "Requester Name" in form["fields"]
    assert "College/Office" in form["fields"]
    assert "Contact Number" in form["fields"]
    assert "Item Received" in form["fields"]
    assert "Date Received" in form["fields"]
    assert "Description of the Problem" in form["fields"]
    assert "Assigned ICTS Personnel" in form["fields"]
    assert "Expected Finish Date/Time" in form["fields"]
    assert "Endorsement" in form["fields"]
    assert "Signature" in form["fields"]
    assert not any("@" in field or "}" in field or "[" in field for field in form["fields"])
    assert "X7qtrpplk" not in form["fields"]


def test_service_report_section_recovers_with_trailing_text_or_qualifiers():
    parsed = parse_structured_document(
        """
        Maintenance Request Form
        LSPU-FMO-SF-124

        SERVICE REPORT (to be filled out by staff)
        Item Received: _______________

        SERVICE REPORT:
        Date Received: ______________

        SERVICE REPORT
        Endorsement: ________________

        SERVICE REPORT - ICTS
        Signature: _________________
        """
    )

    assert parsed["document_type"] == "requirement"
    assert parsed["form"]["sections"] == ["Service Report"]


def test_form_maps_to_requirement_with_requirement_display_metadata():
    parsed = parse_structured_document(
        """
        Records Office
        Document Request Form
        Form Code: LSPU-REC-SF-010
        Name: __________________
        Contact Number: ________
        Date: __________________
        """
    )

    form = parsed["form"]

    assert parsed["document_type"] == "requirement"
    assert parsed["display_document_type"] == "Requirement / Form Document"
    assert form["document_type"] == "requirement"
    assert form["display_document_type"] == "Requirement / Form Document"
    assert form["form_title"] == "Document Request Form"


def test_options_requirements_related_services_and_instructions_are_dynamic():
    parsed = parse_structured_document(
        """
        Student Services Office
        Student Assistance Request Form

        Requester Information
        Name: __________________
        Contact Number: ________
        Description: ___________
        Signature: _____________

        Services Requested:
        Please check applicable
        Counseling
        Peer Support
        Referral
        """
    )

    form = parsed["form"]

    assert form["options_or_services"] == ["Counseling", "Peer Support", "Referral"]
    assert form["requirements"] == ["Name", "Contact Number", "Description", "Signature"]
    assert form["related_services"] == ["Counseling", "Peer Support", "Referral"]
    assert form["how_to_fill_out"] == [
        "Fill in the required requester information.",
        "Select the applicable service option if available.",
        "Provide a description if the form includes a description field.",
        "Sign the form if a signature field is present.",
        "Submit the completed form to the indicated office.",
    ]


def test_options_and_related_services_are_empty_when_not_in_document():
    parsed = parse_structured_document(
        """
        Clearance Request Form
        Name: __________________
        College/Office: ________
        Date: __________________
        """
    )

    form = parsed["form"]

    assert form["options_or_services"] == []
    assert form["related_services"] == []


def test_unknown_office_stays_unknown_when_not_found():
    parsed = parse_structured_document(
        """
        Generic Request Form
        Name: __________________
        Date: __________________
        """
    )

    assert parsed["form"]["office"] == "[NEEDS REVIEW]"
    assert parsed["form"]["office_detection_source"] == "unknown"


def test_formatted_requirement_preview_excludes_raw_extraction_text():
    parsed = parse_structured_document(
        """
        Records Office
        Document Request Form
        Name: __________________
        Type of Request: [ ] Transcript
        """
    )

    preview = format_structured_document(parsed)
    doc = build_structured_document("Document Request Form\nName: __________________")
    labels = [field.label for field in doc.fields]

    assert "Raw Extraction" not in preview
    assert "Document Request Form" in preview
    assert "Raw Extraction" not in labels
    assert parsed["form"]["raw_extracted_text"]

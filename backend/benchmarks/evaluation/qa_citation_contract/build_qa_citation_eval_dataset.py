"""Build and validate the live qa_citation_eval_dataset.json from the locked extract.

Stage 3.1B authoring helper. Does not execute the chatbot or judges.
Every excerpt is checked as a verbatim substring of the locked extract text
before the Stage 2 loader runs.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.qa_citation_dataset import (  # noqa: E402
    EXPERIMENT_FAMILY,
    LOCKED_CORPUS_CHUNK_COUNT,
    LOCKED_CORPUS_COLLECTION,
    LOCKED_CORPUS_EXTRACT_ARTIFACT,
    LOCKED_CORPUS_PATH,
    LOCKED_IDENTITY_DIGEST,
    LOCKED_METADATA_TEXT_DIGEST,
    faculty_scope_violations,
    load_locked_extract_index,
    load_qa_citation_dataset,
    locked_extract_path,
)

DATASET_VERSION = "2026-11-09-v1"
GENERATION_MODEL = "cursor-grok-4.6"
GENERATION_PROMPT_VERSION = "qac-gen-v1-stage3.1b-20261109"
LIVE_DATASET_PATH = BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_eval_dataset.json"
AUDIT_PATH = (
    BACKEND_ROOT
    / "benchmarks"
    / "evaluation"
    / "qa_citation_eval_dataset.generation_audit.json"
)

CHARTER = "da4a1832-7242-4e94-8ba6-bc0b9f2294bf"
HANDBOOK = "cec01713-c1ba-4061-9404-ffaa1d8e70dd"

REJECTED_CANDIDATES = [
    {
        "candidate": "What is the teaching load of a regular faculty member?",
        "status": "rejected_faculty_audience",
        "reason": "Faculty-as-audience. Loader would reject faculty-member / teaching-load phrasing.",
    },
    {
        "candidate": "What is the campus Wi-Fi password?",
        "status": "kept_as_insufficient_evidence",
        "reason": "No wifi password in the extract. Not converted into an invented answer.",
    },
    {
        "candidate": "What does Brand New Article say about admissions?",
        "status": "rejected_placeholder",
        "reason": "FAQ placeholder text ('Brand New Article / Summary / Body'), not a university policy.",
    },
    {
        "candidate": "How much is library circulation, 2 pesos per what?",
        "status": "rejected_incomplete_charter_line",
        "reason": "Charter fee line is truncated ('2 pesos per'). Do not invent the unit.",
    },
    {
        "candidate": "What is the lost-ID replacement fee?",
        "status": "kept_as_insufficient_evidence",
        "reason": "No lost-ID replacement procedure or fee in the extract.",
    },
]


def _page(meta: dict) -> int | None:
    for key in ("page_number", "page", "page_start"):
        value = meta.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def main() -> int:
    extract = json.loads(locked_extract_path().read_text(encoding="utf-8"))
    by_id = {row["chunk_id"]: row for row in extract["records"]}
    index = load_locked_extract_index()

    def span(chunk_id: str, excerpt: str) -> dict:
        record = by_id.get(chunk_id)
        if record is None:
            raise SystemExit(f"chunk not in extract: {chunk_id}")
        text = record.get("text") or ""
        cleaned = excerpt.strip()
        if cleaned not in text:
            raise SystemExit(
                f"excerpt not in {chunk_id}: {cleaned!r}\n--- record starts ---\n{text[:300]!r}"
            )
        meta = record.get("metadata") or {}
        item = {
            "chunk_id": chunk_id,
            "document_id": str(
                meta.get("document_id") or index.by_chunk_id[chunk_id].document_id
            ),
            "source_filename": meta.get("source_filename"),
            "title": meta.get("title"),
            "source_section": meta.get("source_section") or meta.get("section"),
            "excerpt": cleaned,
        }
        page = _page(meta)
        if page is not None:
            item["page"] = page
        return item

    def labeled(
        *,
        case_id: str,
        question: str,
        category: str,
        difficulty: str,
        reference_answer: str,
        chunks: list[tuple[str, str]],
        reviewer_notes: str,
    ) -> dict:
        evidence = [span(chunk_id, excerpt) for chunk_id, excerpt in chunks]
        document_ids = list(dict.fromkeys(item["document_id"] for item in evidence))
        return {
            "case_id": case_id,
            "question": question,
            "category": category,
            "case_type": "labeled_student_support",
            "audience": "student",
            "difficulty": difficulty,
            "labeling_status": "labeled",
            "reference_answer": reference_answer,
            "supporting_document_ids": document_ids,
            "supporting_chunk_ids": list(dict.fromkeys(item["chunk_id"] for item in evidence)),
            "reference_evidence": evidence,
            "generation_model": GENERATION_MODEL,
            "generation_prompt_version": GENERATION_PROMPT_VERSION,
            "reviewer_notes": reviewer_notes,
        }

    def insufficient(*, case_id: str, question: str, category: str, reviewer_notes: str) -> dict:
        return {
            "case_id": case_id,
            "question": question,
            "category": category,
            "case_type": "insufficient_evidence",
            "audience": "student",
            "difficulty": "insufficient_evidence",
            "labeling_status": "labeled",
            "reference_answer": None,
            "supporting_document_ids": [],
            "supporting_chunk_ids": [],
            "reference_evidence": [],
            "generation_model": GENERATION_MODEL,
            "generation_prompt_version": GENERATION_PROMPT_VERSION,
            "reviewer_notes": reviewer_notes,
        }

    cases = [
        labeled(
            case_id="qac_001_tor_undergrad_fee",
            question="How much does a Transcript of Records cost per page if I am an undergraduate student?",
            category="Student Records",
            difficulty="easy",
            reference_answer=(
                "The Citizen's Charter lists undergraduate Transcript of Records at P75.00 per page."
            ),
            chunks=[(f"{CHARTER}::1", "Undergraduate: P75.00/page; Graduate: P150/page")],
            reviewer_notes=(
                "Single-chunk fee lookup. Do not treat P30.00/page, P137, or the diploma "
                "line as the undergraduate TOR rate."
            ),
        ),
        labeled(
            case_id="qac_002_enrollment_office",
            question="Which office handles enrollment assistance at LSPU?",
            category="Enrollment and Registration",
            difficulty="easy",
            reference_answer="The Citizen's Charter Enrollment service is under the Registrar.",
            chunks=[(f"{CHARTER}::0", "Office / Division\nRegistrar")],
            reviewer_notes="Office identity from the Enrollment card.",
        ),
        labeled(
            case_id="qac_003_id_validation_requirements",
            question="What documents do I need to have my student ID validated?",
            category="University Forms and Documentary Requirements",
            difficulty="easy",
            reference_answer=(
                "ID Validation is done by the Office of the Student Affairs and Services. "
                "Requirements are a Certificate of Registration from the Registrar’s Office "
                "and a Student ID from the Business Affairs Office."
            ),
            chunks=[
                (
                    f"{CHARTER}::14",
                    "Office / Division\nOffice of the Student Affairs and Services\n\nWho May Avail\nAll\n\nRequirements\n- Requirement: Certificate of Registration\n  Where to Secure: Registrar’s Office\n- Requirement: Student ID\n  Where to Secure: Business Affairs Office",
                )
            ],
            reviewer_notes="Both documentary requirements are on the OSAS ID Validation card.",
        ),
        labeled(
            case_id="qac_004_clinic_walkin_fee",
            question="Do I have to pay for routine medical and dental services at the university clinic?",
            category="Student Services",
            difficulty="easy",
            reference_answer=(
                "The Citizen's Charter Routine Medical and Dental Services card is under "
                "University Health Service, who may avail is All, and Fees are listed as None."
            ),
            chunks=[
                (
                    f"{CHARTER}::8",
                    "Office / Division\nUniversity Health Service\n\nWho May Avail\nAll",
                )
            ],
            reviewer_notes=(
                "The same card also states Fees None and Total Processing Time 10-38 minutes. "
                "The excerpt used here is the office and who-may-avail block; the Fees None "
                "line is in the same record and is cited in the reference answer only because "
                "it is present on that card. Expand excerpt to include Fees None."
            ),
        ),
        labeled(
            case_id="qac_005_accounting_clearance",
            question="What happens when I request a clearance from Accounting?",
            category="Fees and Payment",
            difficulty="easy",
            reference_answer=(
                "Releasing of Clearance is an Accounting service. The student presents an ID "
                "so the student number can be verified. If there are unsettled accounts, the "
                "student must settle them at the Cashier's Office. If there is no outstanding "
                "balance, clearance is issued. The listed fee is None."
            ),
            chunks=[
                (
                    f"{CHARTER}::3",
                    "Office / Division\nAccounting",
                ),
                (
                    f"{CHARTER}::3",
                    "Checks if the Student have unsettled accounts in the system, require them to settle accounts in the Cashier's Office. • If the Student have no outstanding balance in the system, clearance will be issued.",
                ),
                (
                    f"{CHARTER}::3",
                    "Fees\nNone",
                ),
            ],
            reviewer_notes="Do not invent a clearance fee; the card lists Fees None.",
        ),
        labeled(
            case_id="qac_006_grade_excellent",
            question="What percentage range is a grade of 1.00, and how is it described?",
            category="Academic Policies",
            difficulty="easy",
            reference_answer="In the Student Handbook grading system, 1.00 is 99-100 and is described as Excellent.",
            chunks=[(f"{HANDBOOK}::91", "1.00 | 99-100 | Excellent")],
            reviewer_notes="Exact table row. Do not infer other grade labels that the table leaves blank.",
        ),
        labeled(
            case_id="qac_007_cross_enrollee",
            question="What is a cross-enrollee student?",
            category="Enrollment and Registration",
            difficulty="easy",
            reference_answer=(
                "A cross-enrollee is a student currently enrolled in another campus or school "
                "who is permitted to enroll in the university to earn credit units, or the reverse."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::31",
                    "A student currently enrolled in another campus/school is permitted to enroll in the university to earn credit units or vice versa.",
                )
            ],
            reviewer_notes="Definition-only case. Do not add application steps that this chunk does not state.",
        ),
        labeled(
            case_id="qac_008_latin_cum_laude",
            question="What final grade range is needed for cum laude in a degree course?",
            category="Academic Policies",
            difficulty="easy",
            reference_answer=(
                "For a degree course, cum laude is listed as a final grade of 1.46 to 1.75. "
                "The same table lists summa cum laude as 1.00 to 1.20 and magna cum laude as "
                "1.21 to 1.45."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::274",
                    "Summa cum laude | 1.00 to 1.20\nMagna cum laude | 1.21 to 1.45\nCum laude | 1.46 to 1.75",
                )
            ],
            reviewer_notes="Degree-course row only. Non-degree honors use different award names on the same card.",
        ),
        labeled(
            case_id="qac_009_counseling_office",
            question="Which office provides counseling, and can I walk in?",
            category="Student Services",
            difficulty="easy",
            reference_answer=(
                "Counseling is a Guidance and Counseling service. Client steps include "
                "endorsement, referral, or walk-in. Requirements listed are Data Privacy "
                "Consent and a Client Identification Card. Total processing time is 1-2 hours."
            ),
            chunks=[
                (
                    f"{CHARTER}::80",
                    "Office / Division\nGuidance and Counseling",
                )
            ],
            reviewer_notes="Walk-in is named in the first client step of the same card.",
        ),
        labeled(
            case_id="qac_010_honorable_dismissal_meaning",
            question="What is Honorable Dismissal?",
            category="Student Records",
            difficulty="easy",
            reference_answer=(
                "Honorable Dismissal is voluntary withdrawal from the college or university "
                "with the consent of the Registrar."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::117",
                    "Honorable Dismissal is voluntary with drawal from the college/university with the consent of the Registrar.",
                )
            ],
            reviewer_notes="Short definition chunk. Petition and readmission rules are a later case.",
        ),
        labeled(
            case_id="qac_011_tor_fee_levels",
            question="How much are TOR pages for undergraduate versus graduate students, and what is the fee for a second copy of a diploma?",
            category="Fees and Payment",
            difficulty="medium",
            reference_answer=(
                "The Citizen's Charter fee line for issuance of Transcript of Records, transfer "
                "credentials, certifications, CAV, and authenticated documents lists "
                "undergraduate at P75.00 per page, graduate at P150 per page, and a second "
                "copy of a diploma at P100.00. The same line also lists P30.00/page and P137 "
                "without naming those two amounts to a specific document type in the summary."
            ),
            chunks=[
                (
                    f"{CHARTER}::1",
                    "Undergraduate: P75.00/page; Graduate: P150/page; P30.00/page; P137; Second copy of diploma: P100.00",
                )
            ],
            reviewer_notes=(
                "Do not assign P30.00/page or P137 to TOR, CAV, or certification; the summary "
                "does not label those two amounts."
            ),
        ),
        labeled(
            case_id="qac_012_good_moral_by_status",
            question="What document do I present for a Good Moral certificate if I am still an undergraduate, an alumnus, or a transferee?",
            category="University Forms and Documentary Requirements",
            difficulty="medium",
            reference_answer=(
                "All three Good Moral services are under the Office of the Student Affairs and "
                "Services. An undergraduate presents a Certificate of Registration from the "
                "Registrar’s Office and a Student ID. An alumnus presents a Transcript of Record "
                "from the Registrar’s Office and a Student ID; the steps also allow original "
                "Transcript of Records, Diploma, or Alumni ID. A transferee presents a "
                "Certificate of Transfer from the Registrar’s Office and a Student ID."
            ),
            chunks=[
                (
                    f"{CHARTER}::15",
                    "Office / Division\nOffice of the Student Affairs and Services",
                ),
                (
                    f"{CHARTER}::15",
                    "- Requirement: Certificate of Registration\n  Where to Secure: Registrar’s Office\n- Requirement: Student ID\n  Where to Secure: Business Affairs Office",
                ),
                (
                    f"{CHARTER}::16",
                    "- Requirement: Transcript of Record (TOR)\n  Where to Secure: Registrar’s Office\n- Requirement: Student ID\n  Where to Secure: Business Affairs Office",
                ),
                (
                    f"{CHARTER}::16",
                    "Transcript of Records, Diploma or Alumni ID.",
                ),
                (
                    f"{CHARTER}::17",
                    "- Requirement: Certificate of Transfer\n  Where to Secure: Registrar’s Office\n- Requirement: Student ID\n  Where to Secure: Business Affairs Office",
                ),
            ],
            reviewer_notes=(
                "Three Charter cards. Alumni steps also mention Diploma or Alumni ID; keep "
                "that as an additional listed option, not a replacement for the requirements list."
            ),
        ),
        labeled(
            case_id="qac_013_shifting_conditions",
            question="Can I shift to another BS program, and what conditions apply?",
            category="Academic Policies",
            difficulty="medium",
            reference_answer=(
                "Students from other courses can shift to any BS program in the university if "
                "they have no failure greater than six (6) units during the semester, no failure "
                "in the course or major-related subjects stated in the retention policy of the "
                "BS program curriculum, and a filled-out shifting form from the Office of the Registrar."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::43",
                    "Students from other courses can shift to any BS Program within the university provided that the following condi- tions are met:",
                ),
                (
                    f"{HANDBOOK}::43",
                    "2.10.1. No failure of greater than six (6) units during the semester.",
                ),
            ],
            reviewer_notes="Same chunk twice is redundant; use one excerpt covering all three conditions.",
        ),
        labeled(
            case_id="qac_014_refund_schedule",
            question="If I already paid enrolment fees and I am granted Honorable Dismissal or a Leave of Absence, how much of those fees can be refunded?",
            category="Fees and Payment",
            difficulty="medium",
            reference_answer=(
                "A student who paid enrolment fees and is granted Honorable Dismissal/Transfer "
                "Credentials or Leave of Absence is entitled to a refund of fees except "
                "matriculation or registration fee: 75% within the week from the opening of "
                "classes; 50% from the second to the fourth week; and no refund after the "
                "fourth week from the opening of classes."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::52",
                    "3.1. seventy-five percent (75%): within the week from the opening of classes\n3.2. fifty percent (50%): within the period from the second to the fourth week\n3.3. No refund: after the fourth week from the opening of classes",
                )
            ],
            reviewer_notes="Does not cover laboratory or miscellaneous non-refund rules; those are a later multi-chunk case.",
        ),
        labeled(
            case_id="qac_015_scholastic_warning_probation",
            question="When is a student given a warning versus placed on probation for failed units?",
            category="Academic Policies",
            difficulty="medium",
            reference_answer=(
                "At the end of the semester, a student who fails 25% to 49% of the total "
                "academic units registered shall be warned by the Dean and advised to improve "
                "performance. A student who fails 50% to 74% of the total academic units "
                "registered shall be placed on probation for the succeeding semester, and the "
                "Dean shall reduce the load accordingly. Probation may be lifted upon passing "
                "all subjects carried during the probation term."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::66",
                    "4.1. Warning. At the end of the semester, A student who fails 25% to 49% of the total academic units he registered shall be warned by the Dean and advised to improve his/her performance.",
                )
            ],
            reviewer_notes="Probation text is in the same chunk; include it in the excerpt.",
        ),
        labeled(
            case_id="qac_016_overload_limit",
            question="Can I take more than the normal academic load, and what is the maximum overload?",
            category="Academic Policies",
            difficulty="medium",
            reference_answer=(
                "No student is allowed to take more than the normal load during the term or "
                "semester. Only a graduating student with an academic record better than the "
                "average may apply with the Vice-President for Academic Affairs for an overload "
                "of not more than six (6) units or two (2) subjects."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::76",
                    "No student is allowed to take more than the normal load during the term/semester. Only a graduating student with an aca- demic record better than the average may apply for consideration with the Vice-President for Academic Affairs for an overload of not more than six (6) units or (2 subjects).",
                )
            ],
            reviewer_notes="Do not apply the graduate nine-unit maximum from a different article to this undergraduate load rule.",
        ),
        labeled(
            case_id="qac_017_uniform_schedule",
            question="When should I wear the university t-shirt, the department shirt, and the P.E. uniform?",
            category="Student Services",
            difficulty="medium",
            reference_answer=(
                "P.E. uniforms shall be worn only during P.E. classes; students wearing a P.E. "
                "uniform will not be allowed to enter academic classes. The university t-shirt "
                "shall be worn every Wednesday, and the department shirt every Friday. Blue "
                "jeans or maong trousers following the dress code are acceptable. The prescribed "
                "uniform shall be worn in all classroom sessions, with proper field or laboratory "
                "attire as prescribed for those activities."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::246",
                    "1.2. P.E. uniforms shall be worn only during P.E. classes. Students wearing P.E. uniform will not be allowed to enter academic classes.\n1.3. University t-shirt shall be worn every Wednesday while department shirt shall be worn every Friday.",
                )
            ],
            reviewer_notes="The prohibited-attire list is not in this chunk after the colon; do not invent items.",
        ),
        labeled(
            case_id="qac_018_scholarship_requirements",
            question="What documents are listed for processing scholarship and financial assistance?",
            category="Scholarships and Financial Assistance",
            difficulty="medium",
            reference_answer=(
                "Processing of Scholarship and Financial Assistance is under the Scholarship "
                "and Financial Assistance Unit. Listed requirements include an application form "
                "from the Scholarship and Financial Assistance Office/SFA, a CHED application "
                "form, a certified true copy of grades, a certified true copy of the Certificate "
                "of Registration, financial documents from DSWD and BIR, a notarized certificate "
                "of no employment, and a copy of ID with three specimen signatures. Who may avail "
                "is ALL, and the listed fee is None."
            ),
            chunks=[
                (
                    f"{CHARTER}::18",
                    "Office / Division\nScholarship and Financial Assistance Unit\n\nWho May Avail\nALL",
                )
            ],
            reviewer_notes="Requirements list is on the same card; keep the excerpt covering the requirement block.",
        ),
        labeled(
            case_id="qac_019_free_higher_education",
            question="Are bachelor's degree students exempt from paying tuition and other school fees?",
            category="Fees and Payment",
            difficulty="medium",
            reference_answer=(
                "The Student Handbook Free Higher Education paragraph states that students who "
                "enroll in a course leading to a bachelor’s degree in the University shall be "
                "exempt from paying tuition and other school fees for units enrolled in, in "
                "connection with the Universal Access to Quality Tertiary Education Act of 2017 "
                "or UniFAST. Students are eligible for those benefits provided they qualify "
                "under the admission and retention policies of the University."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::35",
                    "Universal Access to Quality Tertiary Education Act of 2017 or Unified Financial Assistance System for Tertiary Education Act, or UniFAST",
                ),
                (
                    f"{HANDBOOK}::35",
                    "shall be exempt from paying tuition and other school fees for units enrolled in.",
                ),
                (
                    f"{HANDBOOK}::35",
                    "Students are eligible to receive the benefits stipulated in 1.2. provided that they qualify the admission and re- tention policies of the University.",
                ),
            ],
            reviewer_notes=(
                "Do not quote the accommodation-capacity sentence. Do not resolve the garbled "
                "statute numbering in this chunk against RA 10931 on the Assessment of Fees card."
            ),
        ),
        labeled(
            case_id="qac_020_transferee_documents",
            question="What documents does the Student Handbook list for student transferees?",
            category="Admissions",
            difficulty="medium",
            reference_answer=(
                "Student transferees are listed as needing transfer credential or honorable "
                "dismissal from the last school attended; transcript of records or academic "
                "records for evaluation; physical, medical, and drug testing examinations "
                "certified by a government physician; a certificate of good moral character "
                "from the last school attended; three latest 2x2 pictures; and a photocopy of "
                "an authenticated PSA birth certificate, or marriage certificate for married "
                "female students. Other program-specific requirements may be added, and the "
                "student shoulders payment for tests done in an outside facility."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::45",
                    "- Transfer Credential/Honorable Dismissal from the schoollast attended",
                )
            ],
            reviewer_notes="Use a longer excerpt covering the bullet list from the same chunk.",
        ),
        labeled(
            case_id="qac_021_student_id_processing_office",
            question="Where is a student ID processed, and who may avail of that service?",
            category="Student Services",
            difficulty="easy",
            reference_answer=(
                "Processing of Student ID is under the Business Affairs Office. Who may avail "
                "is Students, Employees and Alumni. A COR from the Registrar is listed as a "
                "requirement. The listed fee is None and total processing time is 4 minutes."
            ),
            chunks=[
                (
                    f"{CHARTER}::7",
                    "Office / Division\nBusiness Affairs Office\n\nWho May Avail\nStudents, Employees and Alumni",
                ),
                (
                    f"{CHARTER}::7",
                    "- Requirement: COR Registrar",
                ),
                (
                    f"{CHARTER}::7",
                    "Fees\nNone\n\nTotal Processing Time\n4 minutes",
                ),
            ],
            reviewer_notes="This is student ID processing, not ID validation at OSAS.",
        ),
        labeled(
            case_id="qac_022_unscheduled_subject",
            question="I am an irregular student. How do I request an unscheduled subject to be offered?",
            category="Enrollment and Registration",
            difficulty="medium",
            reference_answer=(
                "Offering of Unscheduled Subject/s is a Colleges service for irregular students. "
                "Requirements are a request letter and a copy of evaluation of grades from the "
                "Registrar. The student submits the letter and evaluation, the request is "
                "verified and forwarded for approval, and the student is informed whether the "
                "subject has been offered. After that, the student proceeds to enrolment or "
                "adding of the subject. The listed fee is None and total processing time is "
                "30 minutes."
            ),
            chunks=[
                (
                    f"{CHARTER}::91",
                    "Who May Avail\nIrregular Students",
                )
            ],
            reviewer_notes="Do not name approvers beyond what the card states. Adding of subject is the next client step on the same card.",
        ),
        labeled(
            case_id="qac_023_refund_and_nonrefundable_fees",
            question="If I withdraw after paying enrolment fees, which fees can be refunded and which cannot?",
            category="Fees and Payment",
            difficulty="hard",
            reference_answer=(
                "If enrollment fees were paid and Honorable Dismissal/Transfer Credentials or "
                "Leave of Absence is granted, fees except matriculation or registration fee "
                "follow the 75% / 50% / no-refund schedule by week from the opening of classes. "
                "Separately, laboratory fees will not be refunded after one week from the opening "
                "of classes where a voluntary change is made from one course to another, and no "
                "refund for registration, library, and miscellaneous fees will be made to any "
                "student who withdraws anytime after registration."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::52",
                    "A student who has paid the enrolment fees and who is granted Honorable Dismissal/Transfer Credentials or Leave of Absence (LOA) is entitled to a refund of their fees, except matricula- tion or registration fee, in accordance with the following schedule:",
                ),
                (
                    f"{HANDBOOK}::53",
                    "Laboratory fees will not be refunded after one week from the opening of classes where voluntary change is made from one course to another. No refund for registration, library, and mis- cellaneous fees will be made to any student who withdraws any- time after registration.",
                ),
            ],
            reviewer_notes="Two handbook sections. Do not collapse them into a single percentage.",
        ),
        labeled(
            case_id="qac_024_retention_warning_to_dismissal",
            question="What happens if I fail a large share of my enrolled units — warning, probation, or dismissal?",
            category="Academic Policies",
            difficulty="hard",
            reference_answer=(
                "Failing 25% to 49% of registered academic units brings a warning from the Dean. "
                "Failing 50% to 74% places the student on probation for the succeeding semester "
                "with a reduced load. Failing more than 75% of total academic units enrolled "
                "subjects the student to dismissal from the College, except that an incomplete "
                "grade is not included in the computation of earned units, and this dismissal "
                "rule shall not apply to students who receive final grades in only nine academic units."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::66",
                    "4.1. Warning. At the end of the semester, A student who fails 25% to 49% of the total academic units he registered shall be warned by the Dean and advised to improve his/her performance.\n4.2. Probation. At the end of the semester, A student fails 50% to 74% of the total academic units in which he registered shall be placed on probation for the succeeding semester, and the Dean con- cerned shall reduce his/her load accordingly.",
                ),
                (
                    f"{HANDBOOK}::67",
                    "Any student who fails in more than seventy-five percent (75%) of the total academic units enrolled shall be subject for dis- missal from the College; provided that an incomplete grade shall not be included in the computation of earned units; provided fur- ther, that this shall not apply to students who receive final grades in only nine academic units.",
                ),
            ],
            reviewer_notes="Needs both the delinquency chunk and the dismissal chunk.",
        ),
        labeled(
            case_id="qac_025_four_point_zero_and_inc",
            question="How can a grade of 4.00 be removed, and what happens if an INC is not completed on time?",
            category="Academic Policies",
            difficulty="hard",
            reference_answer=(
                "A grade of 4.00 may be removed by repeating the subject or by re-examination. "
                "The highest grade obtainable upon re-examination is 3.00; failing the removal "
                "examination gives 5.00. Only one removal examination is allowed and it must be "
                "taken within one academic year or the grade becomes 5.00. If the subject is a "
                "prerequisite for the next semester, removal must be accomplished before the next "
                "enrolment. The removal fee is P20 per unit. A special removal examination may "
                "be given upon the College Dean's written-petition approval and is charged P100 "
                "per unit. If INC is not completed within the prescribed period of one year, it "
                "is automatically changed to 5.0."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::101",
                    "A grade of “4.00” may be removed by re peating the subject or by re-examination. The highest grade a stu- dent must obtain upon re-examination is “3.00”. If the removal examination is failed, a student is given a grade of “5.00”.",
                ),
                (
                    f"{HANDBOOK}::101",
                    "5.4. INC and Automatic “5”. If not completed within the prescribed peri- od (one year), a grade of “incomplete” will automatically be changed to “5.0”.",
                ),
                (
                    f"{HANDBOOK}::101",
                    "5.5. Removal Fee. The removal fee is P20 per unit. (BOR Reso.1046, s.2012)",
                ),
                (
                    f"{HANDBOOK}::104",
                    "A fee of P100 per unit is charged for this removal.",
                ),
            ],
            reviewer_notes=(
                "101 already contains the P20 removal fee. 104 adds the P100 special-removal fee. "
                "Do not treat P20 and P100 as the same fee."
            ),
        ),
        labeled(
            case_id="qac_026_graduation_requirements",
            question="What residency, tree-planting, clearance, and ceremony rules apply before I can graduate?",
            category="Academic Policies",
            difficulty="hard",
            reference_answer=(
                "No student shall be recommended for graduation with property or financial "
                "accountabilities. A student must have completed at least 50% of the academic "
                "units or hours required for graduation and been in residence at least two years "
                "in this university, one of which must be the senior year. A student must have "
                "individually planted a minimum of ten seedlings per year in areas determined by "
                "the college; tree planting in times of pandemic shall be deferred. All candidates "
                "for graduation must attend the commencement exercises. The Registrar issues a "
                "List of Candidates for Graduation at the start of the first semester of the "
                "academic year when the students would graduate."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::126",
                    "Tree Planting: A student must have individually planted a minimum of ten (10) seedlings per year in areas determined by their respective college.",
                ),
                (
                    f"{HANDBOOK}::126",
                    "Residency: No student shall graduate from the University until completion of at least fifty percent (50%) of the total number of academic units or hours required for graduation, and must have been in resi- dence for at least two (2) years in this university, one of which must be that of the senior year.",
                ),
                (
                    f"{HANDBOOK}::75",
                    "the Office of the Registrar issues a List of Candidates for Gradu- ation for evaluation in case of deficiencies in grades and other university requirements at the start of the first semester of the academic year when the students would graduate.",
                ),
            ],
            reviewer_notes="Clearance and ceremony sentences are on the same graduation-requirements chunk as tree planting and residency.",
        ),
        labeled(
            case_id="qac_027_graduate_loa",
            question="If I am a graduate student, how long can a Leave of Absence last and what if I do not file one?",
            category="Academic Policies",
            difficulty="medium",
            reference_answer=(
                "A graduate student who intends to take a leave of absence must accomplish a "
                "Leave of Absence form stating the reason and the length of time. The length of "
                "time for LOA should not exceed two (2) years and is considered part of the "
                "residency. An extension beyond the prescribed maximum residency requires one "
                "penalty subject for every year of the extension. Failure to submit a LOA would "
                "mean absence without official leave (AWOL) and would affect tracking of "
                "academic records."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::179",
                    "The length of time for LOA, which should not exceed two (2) years, is considered a part of the residency.",
                )
            ],
            reviewer_notes="This article is under Graduate Studies. Do not apply the two-year cap to undergraduate LOA without a matching undergraduate rule.",
        ),
        labeled(
            case_id="qac_028_honorable_dismissal_petition",
            question="How do I apply for Honorable Dismissal, and can I be readmitted afterward?",
            category="Student Records",
            difficulty="hard",
            reference_answer=(
                "A student of good standing who wants to withdraw shall present a written "
                "petition to the Registrar signed by the parent or guardian. If granted, the "
                "student is given Honorable Dismissal. All indebtedness to the university must "
                "be settled before the statement is issued. A student granted Honorable Dismissal "
                "may not be readmitted in the university. A student who leaves because of "
                "suspension, dropping, or expulsion due to disciplinary action is not entitled "
                "to Honorable Dismissal."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::118",
                    "Honorable Dismissal Petition: A student of good standing who de sires to withdraw from the college/university shall present a written petition to the Registrar signed by the parent/s or guardian/s. If the petition is granted, the student shall be given Honorable Dismissal.",
                ),
                (
                    f"{HANDBOOK}::118",
                    "A student granted an honorable dismissal may not be readmitted in the university.",
                ),
            ],
            reviewer_notes="Same chunk can supply both excerpts; keep both because they answer distinct parts of the question.",
        ),
        labeled(
            case_id="qac_029_absence_drop_threshold_conflict",
            question="After how many absences will I be dropped from a class?",
            category="Academic Policies",
            difficulty="conflict",
            reference_answer=(
                "The Student Handbook contains two different numeric thresholds. The "
                "undergraduate Absence section says a student accumulating unexcused absences "
                "equivalent to twenty percent (25%) of the total number of hours per day session "
                "for a particular subject shall be dropped from that subject, and time lost due "
                "to late enrolment counts as absence. The Dropping section says students shall "
                "be dropped if they have an accumulated absence of at least 25% of the total "
                "number of class hours in a semester. The graduate Attendance policy says "
                "absences equivalent to twenty percent (20%) of the total number of hour per "
                "day session for a particular subject shall cause the student to be dropped. "
                "The corpus therefore does not present a single consistent percentage for all students."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::107",
                    "A student accumulating unexcused absences from class, equivalent to twenty percent (25%) of the total number of hours per day session for a particular subject, shall be dropped from the roll of students for the particular subject or class, as the case may be.",
                ),
                (
                    f"{HANDBOOK}::81",
                    "Students shall be dropped if they have an accumulated absence of at least 25% of the total number of class hours in a semester.",
                ),
                (
                    f"{HANDBOOK}::162",
                    "A student accumulating absences from class which is equivalent to twenty percent (20%) of the total number of hour per day session for a partic- ular subject shall be dropped from the roll of students for the particular subject or class.",
                ),
            ],
            reviewer_notes=(
                "Genuine corpus conflict, including an internal wording clash of 'twenty percent "
                "(25%)' on the undergraduate absence card versus 20% on the graduate attendance "
                "card. The reference answer reports both figures and does not pick a winner."
            ),
        ),
        labeled(
            case_id="qac_030_library_reference_who",
            question="Who may use library reference assistance, and what ID is required?",
            category="Student Services",
            difficulty="easy",
            reference_answer=(
                "Library Reference Assistance is a Library service. Who may avail is Students, "
                "Faculty, Outside Researchers. The listed requirement is an LSPU ID. The listed "
                "fee is None and total processing time is 10 minutes."
            ),
            chunks=[
                (
                    f"{CHARTER}::9",
                    "Who May Avail\nStudents, Faculty, Outside Researchers",
                )
            ],
            reviewer_notes=(
                "Student question about a student-available service. The who-may-avail line "
                "includes Faculty as one listed client group on the Charter card; the intended "
                "audience of this case remains a student."
            ),
        ),
        labeled(
            case_id="qac_031_graduate_max_load",
            question="What is the maximum course load for a graduate student in a regular semester?",
            category="Academic Policies",
            difficulty="easy",
            reference_answer=(
                "Under Graduate Studies course load rules, a student’s maximum load is nine (9) "
                "units per semester and not more than six (6) units if the subject has a "
                "laboratory during the summer weekend session."
            ),
            chunks=[
                (
                    f"{HANDBOOK}::154",
                    "A student’s maximum load is nine (9) units per semester and not more than six (6) units if the subject has a laboratory during the summer weekend session.",
                )
            ],
            reviewer_notes="Do not apply this nine-unit cap to undergraduate normal load.",
        ),
        labeled(
            case_id="qac_032_enrollment_old_students_portal",
            question="As a returning college student, how do I enlist subjects and get my Certificate of Registration?",
            category="Enrollment and Registration",
            difficulty="medium",
            reference_answer=(
                "On the Enrollment card, old college students and old GSAR students log in to "
                "the Student Web Portal and enlist the subjects to be enrolled. New and old "
                "college students log in to the student portal to view the Certificate of "
                "Registration; the Registrar’s staff issues the COR. College students who are "
                "not qualified for Free Higher Education, and some other listed groups, proceed "
                "to the Office of the Registrar to claim the COR. Total processing time on the "
                "card is 20 minutes."
            ),
            chunks=[
                (
                    f"{CHARTER}::0",
                    "Students, Old GSAR Students: Login to the Student Web Portal and enlists the subjects to be enrolled.",
                )
            ],
            reviewer_notes="New-student hard-copy path is a different step on the same card; this question is for returning college students.",
        ),
        insufficient(
            case_id="qac_033_wifi_password",
            question="What is the campus Wi-Fi password for students?",
            category="Student Services",
            reviewer_notes=(
                "The extract has no wifi password. A wifi mention exists only in remote-learning "
                "context, not as a credential or access procedure."
            ),
        ),
        insufficient(
            case_id="qac_034_campus_shuttle",
            question="Does the campus shuttle run on Sundays for students living in off-campus dorms?",
            category="Student Services",
            reviewer_notes=(
                "No shuttle schedule exists in the extract. Student Housing text only refers to "
                "a list of acceptable student dormitories and that housing should be safe, clean, "
                "affordable, and conducive to learning."
            ),
        ),
        insufficient(
            case_id="qac_035_lost_id_fee",
            question="How much does it cost to replace a lost student ID?",
            category="Fees and Payment",
            reviewer_notes=(
                "ID processing and ID validation cards exist, but the extract does not state a "
                "lost-ID replacement procedure or replacement fee."
            ),
        ),
        insufficient(
            case_id="qac_036_library_hours",
            question="What time does the university library open and close on weekdays?",
            category="Student Services",
            reviewer_notes=(
                "Library reference and circulation services are documented, but opening and "
                "closing hours are not."
            ),
        ),
    ]

    # Repair cases whose first-pass excerpts were placeholders for longer spans.
    repaired = []
    skip_ids = {
        "qac_004_clinic_walkin_fee",
        "qac_009_counseling_office",
        "qac_013_shifting_conditions",
        "qac_015_scholastic_warning_probation",
        "qac_018_scholarship_requirements",
        "qac_020_transferee_documents",
        "qac_022_unscheduled_subject",
        "qac_026_graduation_requirements",
        "qac_027_graduate_loa",
        "qac_030_library_reference_who",
        "qac_032_enrollment_old_students_portal",
    }
    for case in cases:
        if case["case_id"] not in skip_ids:
            repaired.append(case)

    repaired.extend(
        [
            labeled(
                case_id="qac_004_clinic_walkin_fee",
                question="Do I have to pay for routine medical and dental services at the university clinic?",
                category="Student Services",
                difficulty="easy",
                reference_answer=(
                    "The Citizen's Charter Routine Medical and Dental Services card is under "
                    "University Health Service. Who may avail is All. Fees are listed as None. "
                    "Total processing time is 10-38 minutes."
                ),
                chunks=[
                    (
                        f"{CHARTER}::8",
                        "Office / Division\nUniversity Health Service\n\nWho May Avail\nAll",
                    ),
                    (
                        f"{CHARTER}::8",
                        "Fees\nNone\n\nTotal Processing Time\n10-38 minutes",
                    ),
                ],
                reviewer_notes="Office, who-may-avail, fee, and processing time are on the University Health Service card.",
            ),
            labeled(
                case_id="qac_009_counseling_office",
                question="Which office provides counseling, and can I walk in?",
                category="Student Services",
                difficulty="easy",
                reference_answer=(
                    "Counseling is under Guidance and Counseling. Client steps include "
                    "endorsement, referral, or walk-in. Requirements listed are Data Privacy "
                    "Consent and a Client Identification Card. Total processing time is 1-2 hours."
                ),
                chunks=[
                    (
                        f"{CHARTER}::80",
                        "Office / Division\nGuidance and Counseling",
                    ),
                    (
                        f"{CHARTER}::80",
                        "1. Client Step: Endorsement, referral, walk-in",
                    ),
                    (
                        f"{CHARTER}::80",
                        "- Requirement: Data Privacy Consent Client Identification Card Guidance",
                    ),
                    (
                        f"{CHARTER}::80",
                        "Total Processing Time\n1-2 hours",
                    ),
                ],
                reviewer_notes="Office, walk-in, requirements, and total time are on the Counseling card.",
            ),
            labeled(
                case_id="qac_013_shifting_conditions",
                question="Can I shift to another BS program, and what conditions apply?",
                category="Academic Policies",
                difficulty="medium",
                reference_answer=(
                    "Students from other courses can shift to any BS program in the university if "
                    "they have no failure greater than six (6) units during the semester, no failure "
                    "in the course or major-related subjects stated in the retention policy of the "
                    "BS program curriculum, and a filled-out shifting form from the Office of the Registrar."
                ),
                chunks=[
                    (
                        f"{HANDBOOK}::43",
                        "2.10.1. No failure of greater than six (6) units during the semester.\n2.10.2. No failure in the course/major-related subjects stated in the retention policy of any BS in the respective program curricu- lum.\n2.10.3 A filled out shifting form from the Office of the Registrar",
                    )
                ],
                reviewer_notes="All three numbered conditions are in one handbook chunk.",
            ),
            labeled(
                case_id="qac_015_scholastic_warning_probation",
                question="When is a student given a warning versus placed on probation for failed units?",
                category="Academic Policies",
                difficulty="medium",
                reference_answer=(
                    "At the end of the semester, a student who fails 25% to 49% of the total "
                    "academic units registered shall be warned by the Dean and advised to improve "
                    "performance. A student who fails 50% to 74% of the total academic units "
                    "registered shall be placed on probation for the succeeding semester, and the "
                    "Dean shall reduce the load accordingly. Probation may be lifted upon passing "
                    "all subjects carried during the probation term."
                ),
                chunks=[
                    (
                        f"{HANDBOOK}::66",
                        "4.1. Warning. At the end of the semester, A student who fails 25% to 49% of the total academic units he registered shall be warned by the Dean and advised to improve his/her performance.\n4.2. Probation. At the end of the semester, A student fails 50% to 74% of the total academic units in which he registered shall be placed on probation for the succeeding semester, and the Dean con- cerned shall reduce his/her load accordingly. A student's proba- tion status may be lifted upon passing all the subjects carried dur- ing the term s/he is in probation period.",
                    )
                ],
                reviewer_notes="Warning and probation are one section; dismissal is a separate case.",
            ),
            labeled(
                case_id="qac_018_scholarship_requirements",
                question="What documents are listed for processing scholarship and financial assistance?",
                category="Scholarships and Financial Assistance",
                difficulty="medium",
                reference_answer=(
                    "Processing of Scholarship and Financial Assistance is under the Scholarship "
                    "and Financial Assistance Unit, who may avail is ALL, and the listed fee is "
                    "None. Listed requirements include an application form for scholarship and "
                    "financial assistance, a CHED application form, a certified true copy of grades, "
                    "a certified true copy of the Certificate of Registration, financial documents "
                    "from DSWD and BIR, a notarized certificate of no employment, and a copy of ID "
                    "with three specimen signatures."
                ),
                chunks=[
                    (
                        f"{CHARTER}::18",
                        "Office / Division\nScholarship and Financial Assistance Unit\n\nWho May Avail\nALL",
                    ),
                    (
                        f"{CHARTER}::18",
                        "- Requirement: Application Form for Scholarship and Financial Scholarship",
                    ),
                    (
                        f"{CHARTER}::18",
                        "- Requirement: Assistance Page Application Form (CHED Form) CHED",
                    ),
                    (
                        f"{CHARTER}::18",
                        "- Requirement: Assistance Certified True Copy of Grades Registrar",
                    ),
                    (
                        f"{CHARTER}::18",
                        "- Requirement: Certified True Copy of Certificate of Registration Registrar Financial Documents DSWD",
                    ),
                    (
                        f"{CHARTER}::18",
                        "- Requirement: Notarized Certificate of No Employment and No Law Scholarship",
                    ),
                    (
                        f"{CHARTER}::18",
                        "- Requirement: Copy of ID with 3 specimen/Signature BAO",
                    ),
                    (
                        f"{CHARTER}::18",
                        "Fees\nNone",
                    ),
                ],
                reviewer_notes="Requirement lines are OCR-broken on the Charter card; the reference answer does not invent missing form names beyond those lines.",
            ),
            labeled(
                case_id="qac_020_transferee_documents",
                question="What documents does the Student Handbook list for student transferees?",
                category="Admissions",
                difficulty="medium",
                reference_answer=(
                    "Student transferees are listed as needing transfer credential or honorable "
                    "dismissal from the last school attended; transcript of records or academic "
                    "records for evaluation; physical, medical, and drug testing examinations "
                    "certified by a government physician; a certificate of good moral character "
                    "from the last school attended; three latest 2x2 pictures; and a photocopy of "
                    "an authenticated PSA birth certificate, or marriage certificate for married "
                    "female students. Other program-specific requirements may be added, and the "
                    "student shoulders payment for tests done in an outside facility."
                ),
                chunks=[
                    (
                        f"{HANDBOOK}::45",
                        "- Transfer Credential/Honorable Dismissal from the schoollast attended\n- Transcript of Records or a copy of Academic Records for\nevaluation purposes\n- physical, medical, and drug testing examinations certified\nby a government physician, certifying the applicant’s fitness\nto do University work\n- Certificate of Good Moral Character (the last school at-\ntended)\n- three (3) latest 2x2 pictures",
                    )
                ],
                reviewer_notes="PSA birth/marriage lines follow on the same chunk.",
            ),
            labeled(
                case_id="qac_022_unscheduled_subject",
                question="I am an irregular student. How do I request an unscheduled subject to be offered?",
                category="Enrollment and Registration",
                difficulty="medium",
                reference_answer=(
                    "Offering of Unscheduled Subject/s is a Colleges service for irregular students. "
                    "Requirements are a request letter and a copy of evaluation of grades from the "
                    "Registrar. The student submits those documents; the request is verified and "
                    "forwarded for approval; then the student is informed whether the subject has "
                    "been offered and proceeds to enrolment or adding of the subject. The listed "
                    "fee is None and total processing time is 30 minutes."
                ),
                chunks=[
                    (
                        f"{CHARTER}::91",
                        "Who May Avail\nIrregular Students\n\nRequirements\n- Requirement: Request Letter Client Copy of Evaluation of Grades Registrar",
                    ),
                    (
                        f"{CHARTER}::91",
                        "2. Client Step: Proceeds to enrolment/ adding of subject",
                    ),
                    (
                        f"{CHARTER}::91",
                        "Fees\nNone\n\nTotal Processing Time\n30 minutes",
                    ),
                ],
                reviewer_notes="Adding of subject is the next client step on the same card.",
            ),
            labeled(
                case_id="qac_026_graduation_requirements",
                question="What residency, tree-planting, clearance, and ceremony rules apply before I can graduate?",
                category="Academic Policies",
                difficulty="hard",
                reference_answer=(
                    "No student shall be recommended for graduation if with property and financial "
                    "accountabilities. A student must complete at least 50% of the academic units "
                    "or hours required for graduation and have been in residence at least two years "
                    "in this university, one of which must be the senior year. A student must have "
                    "individually planted a minimum of ten seedlings per year in areas determined by "
                    "the college; tree planting in times of pandemic shall be deferred. All candidates "
                    "for graduation must attend the commencement exercises. The Registrar issues a "
                    "List of Candidates for Graduation at the start of the first semester of the "
                    "academic year when the students would graduate."
                ),
                chunks=[
                    (
                        f"{HANDBOOK}::126",
                        "Clearance: No student shall be recommended for graduation if with property and financial accountabilities.\nResidency: No student shall graduate from the University until completion of at least fifty percent (50%) of the total number of academic units or hours required for graduation, and must have been in resi- dence for at least two (2) years in this university, one of which must be that of the senior year.\nGraduation Ceremony Attendance: All candidates for graduation must attend the commencement exercises.",
                    ),
                    (
                        f"{HANDBOOK}::126",
                        "A student must have individually planted a minimum of ten (10) seedlings per year in areas determined by their respective college.",
                    ),
                    (
                        f"{HANDBOOK}::126",
                        "2.1. Tree Planting in times of pandemic shall be deferred.",
                    ),
                    (
                        f"{HANDBOOK}::75",
                        "the Office of the Registrar issues a List of Candidates for Gradu- ation for evaluation in case of deficiencies in grades and other university requirements at the start of the first semester of the academic year when the students would graduate.",
                    ),
                ],
                reviewer_notes="Tree planting and residency/clearance/ceremony are the same graduation chunk; candidates list is a second chunk.",
            ),
            labeled(
                case_id="qac_027_graduate_loa",
                question="If I am a graduate student, how long can a Leave of Absence last and what if I do not file one?",
                category="Academic Policies",
                difficulty="medium",
                reference_answer=(
                    "A graduate student who intends to take a leave of absence must accomplish a "
                    "Leave of Absence form stating the reason and the length of time. The length of "
                    "time for LOA should not exceed two (2) years and is considered part of the "
                    "residency. An extension beyond the prescribed maximum residency requires one "
                    "penalty subject for every year of the extension. Failure to submit a LOA would "
                    "mean absence without official leave (AWOL)."
                ),
                chunks=[
                    (
                        f"{HANDBOOK}::179",
                        "The length of time for LOA, which should not exceed two (2) years, is considered a part of the residency. Should there be an extension beyond the prescribed max- imum residency, the student shall take one (1) penalty subject (additional course not yet taken) for every year of the extension. Failure to submit a LOA would mean absence without official leave (AWOL)",
                    )
                ],
                reviewer_notes="Graduate Studies article. Do not apply the two-year cap to undergraduate LOA.",
            ),
            labeled(
                case_id="qac_030_library_reference_who",
                question="Who may use library reference assistance, and what ID is required?",
                category="Student Services",
                difficulty="easy",
                reference_answer=(
                    "Library Reference Assistance is a Library service. Who may avail is Students, "
                    "Faculty, Outside Researchers. The listed requirement is an LSPU ID. The listed "
                    "fee is None and total processing time is 10 minutes."
                ),
                chunks=[
                    (
                        f"{CHARTER}::9",
                        "Who May Avail\nStudents, Faculty, Outside Researchers\n\nRequirements\n- Requirement: LSPU ID BAO",
                    ),
                    (
                        f"{CHARTER}::9",
                        "Fees\nNone\n\nTotal Processing Time\n10 minutes",
                    ),
                ],
                reviewer_notes=(
                    "Student inquiry about a student-available library service. The Charter "
                    "who-may-avail line lists students among the listed client groups."
                ),
            ),
            labeled(
                case_id="qac_032_enrollment_old_students_portal",
                question="As a returning college student, how do I enlist subjects and get my Certificate of Registration?",
                category="Enrollment and Registration",
                difficulty="medium",
                reference_answer=(
                    "On the Enrollment card, old college students log in to the Student Web Portal "
                    "and enlist subjects. New and old college students log in to the student portal "
                    "to view the Certificate of Registration, and Registrar’s staff issues the COR. "
                    "College students who are not qualified for Free Higher Education, and some "
                    "other listed groups, proceed to the Office of the Registrar to claim the COR."
                ),
                chunks=[
                    (
                        f"{CHARTER}::0",
                        "Students, Old GSAR Students: Login to the Student Web Portal and enlists the subjects to be enrolled.",
                    ),
                    (
                        f"{CHARTER}::0",
                        "New/old college students: Log in to student portal to view the Certificate of Registration",
                    ),
                    (
                        f"{CHARTER}::0",
                        "Agency Action: Issues certificate of registration (COR)",
                    ),
                    (
                        f"{CHARTER}::0",
                        "For College Students who are not qualified to Free Higher Education, students with enrolled RLE subjects, Opt-out, CTP/Foreign,GSA R Students: Proceeds to the Office of the Registrar to claim the Certificate of Registration (COR)",
                    ),
                ],
                reviewer_notes="Portal enlistment and COR viewing are on the Enrollment card.",
            ),
        ]
    )

    # Restore original order by case_id number.
    repaired.sort(key=lambda case: case["case_id"])

    faculty_blocked = []
    for case in repaired:
        for field in ("case_id", "question", "category", "reviewer_notes"):
            hits = faculty_scope_violations(str(case.get(field) or ""))
            if hits:
                faculty_blocked.append((case["case_id"], field, hits))
    if faculty_blocked:
        raise SystemExit(f"faculty-scope violations before loader: {faculty_blocked}")

    questions = [re.sub(r"\s+", " ", case["question"].strip().lower()) for case in repaired]
    if len(questions) != len(set(questions)):
        raise SystemExit("duplicate normalized questions")

    payload = {
        "dataset_version": DATASET_VERSION,
        "experiment_family": EXPERIMENT_FAMILY,
        "annotation_method": "ai_assisted_grounded_generation",
        "judge_source_for_later_scoring": "ai_evaluator",
        "evaluation_ready": True,
        "notes": (
            "Live qa_citation_v1 dataset. Cases were AI-assisted from the locked 691-chunk "
            "extract and then evidence-checked against that extract (verbatim excerpt "
            "membership and chunk IDs). Reference answers are not human-verified. "
            "AI-generated candidates that could not be grounded were rejected or kept as "
            "insufficient-evidence. See qa_citation_eval_dataset.generation_audit.json."
        ),
        "corpus": {
            "path": LOCKED_CORPUS_PATH,
            "collection": LOCKED_CORPUS_COLLECTION,
            "expected_chunk_count": LOCKED_CORPUS_CHUNK_COUNT,
            "extract_artifact": LOCKED_CORPUS_EXTRACT_ARTIFACT,
            "identity_digest": LOCKED_IDENTITY_DIGEST,
            "metadata_text_digest": LOCKED_METADATA_TEXT_DIGEST,
        },
        "generation": {
            "model": GENERATION_MODEL,
            "prompt_version": GENERATION_PROMPT_VERSION,
        },
        "cases": repaired,
    }

    LIVE_DATASET_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    dataset = load_qa_citation_dataset(LIVE_DATASET_PATH)

    categories = Counter(case.category for case in dataset.cases)
    difficulties = Counter(case.difficulty for case in dataset.cases)
    types = Counter(case.case_type for case in dataset.cases)

    audit = {
        "dataset_path": str(LIVE_DATASET_PATH.relative_to(BACKEND_ROOT.parent)).replace("\\", "/"),
        "dataset_version": DATASET_VERSION,
        "generation_model": GENERATION_MODEL,
        "generation_prompt_version": GENERATION_PROMPT_VERSION,
        "annotation_method": "ai_assisted_grounded_generation",
        "human_verified": False,
        "source_corpus": {
            "extract_artifact": LOCKED_CORPUS_EXTRACT_ARTIFACT,
            "identity_digest": LOCKED_IDENTITY_DIGEST,
            "metadata_text_digest": LOCKED_METADATA_TEXT_DIGEST,
            "evaluation_path": LOCKED_CORPUS_PATH,
            "evaluation_collection": LOCKED_CORPUS_COLLECTION,
        },
        "final_case_count": dataset.total_count,
        "case_type_counts": dict(types),
        "category_counts": dict(categories),
        "difficulty_counts": dict(difficulties),
        "rejected_or_reclassified_candidates": REJECTED_CANDIDATES,
        "notes": (
            "Candidates were drafted while inspecting locked extract titles and text, "
            "then each kept case was checked for chunk membership and verbatim excerpts. "
            "This audit file is not a live evaluation dataset and must not be loaded by "
            "the Stage 2 loader as qa_citation_eval_dataset.json."
        ),
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {LIVE_DATASET_PATH}")
    print(f"wrote {AUDIT_PATH}")
    print("total", dataset.total_count)
    print("types", dict(types))
    print("categories", dict(categories))
    print("difficulties", dict(difficulties))
    print("dataset_json_sha256", dataset.dataset_json_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

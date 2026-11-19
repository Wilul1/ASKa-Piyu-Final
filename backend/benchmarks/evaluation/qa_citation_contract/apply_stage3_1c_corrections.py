"""Stage 3.1C — apply the 18 audited dataset corrections.

Read-only against the locked extract. Does not run the chatbot or judges.
Original 2026-11-09-v1 bytes are copied aside before the live file is rewritten.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]
EVAL_DIR = BACKEND_DIR / "benchmarks" / "evaluation"
LIVE_DATASET = EVAL_DIR / "qa_citation_eval_dataset.json"
PRESERVED_DATASET = EVAL_DIR / "qa_citation_eval_dataset.2026-11-09-v1.json"
GENERATION_AUDIT = EVAL_DIR / "qa_citation_eval_dataset.generation_audit.json"
PRESERVED_GENERATION_AUDIT = (
    EVAL_DIR / "qa_citation_eval_dataset.generation_audit.2026-11-09-v1.json"
)
CORRECTION_AUDIT = EVAL_DIR / "qa_citation_eval_dataset.correction_audit.json"
EXTRACT_PATH = (
    BACKEND_DIR / "benchmarks" / "results" / "chroma_record_extraction_20261104T104214Z.json"
)

ORIGINAL_VERSION = "2026-11-09-v1"
REVISED_VERSION = "2026-11-09-v1.1"
CORRECTED_CASE_IDS = {
    "qac_004_clinic_walkin_fee",
    "qac_005_accounting_clearance",
    "qac_008_latin_cum_laude",
    "qac_009_counseling_office",
    "qac_014_refund_schedule",
    "qac_017_uniform_schedule",
    "qac_018_scholarship_requirements",
    "qac_019_free_higher_education",
    "qac_020_transferee_documents",
    "qac_021_student_id_processing_office",
    "qac_022_unscheduled_subject",
    "qac_023_refund_and_nonrefundable_fees",
    "qac_025_four_point_zero_and_inc",
    "qac_027_graduate_loa",
    "qac_028_honorable_dismissal_petition",
    "qac_029_absence_drop_threshold_conflict",
    "qac_030_library_reference_who",
    "qac_032_enrollment_old_students_portal",
}


def load_extract_texts() -> dict[str, str]:
    extract = json.loads(EXTRACT_PATH.read_text(encoding="utf-8"))
    return {record["chunk_id"]: record.get("text") or "" for record in extract["records"]}


def slice_excerpt(text: str, start: str, end: str) -> str:
    start_at = text.index(start)
    end_at = text.index(end, start_at)
    excerpt = text[start_at : end_at + len(end)]
    if excerpt not in text:
        raise SystemExit(f"slice is not a contiguous substring: {start!r} .. {end!r}")
    return excerpt


def clone_span(case: dict, chunk_id: str, excerpt: str) -> dict:
    template = next(span for span in case["reference_evidence"] if span["chunk_id"] == chunk_id)
    span = deepcopy(template)
    span["excerpt"] = excerpt
    return span


def main() -> None:
    live_bytes = LIVE_DATASET.read_bytes()
    live_payload = json.loads(live_bytes.decode("utf-8"))
    if not PRESERVED_DATASET.exists():
        if live_payload.get("dataset_version") != ORIGINAL_VERSION:
            raise SystemExit("no preserved v1 copy, and live dataset is not 2026-11-09-v1")
        PRESERVED_DATASET.write_bytes(live_bytes)
    original_bytes = PRESERVED_DATASET.read_bytes()
    original_sha256 = hashlib.sha256(original_bytes).hexdigest()
    payload = json.loads(original_bytes.decode("utf-8"))
    if payload["dataset_version"] != ORIGINAL_VERSION:
        raise SystemExit(f"preserved original is not {ORIGINAL_VERSION}")

    if not PRESERVED_GENERATION_AUDIT.exists():
        PRESERVED_GENERATION_AUDIT.write_bytes(GENERATION_AUDIT.read_bytes())

    texts = load_extract_texts()
    cases_by_id = {case["case_id"]: case for case in payload["cases"]}
    changelog: list[dict] = []

    def record_change(case_id: str, groups: list[str], reason: str, old: dict, new: dict) -> None:
        changelog.append(
            {
                "case_id": case_id,
                "correction_groups": groups,
                "reason": reason,
                "supporting_chunk_ids": new["supporting_chunk_ids"],
                "old_reference_answer": old["reference_answer"],
                "new_reference_answer": new["reference_answer"],
                "old_excerpts": [span["excerpt"] for span in old["reference_evidence"]],
                "new_excerpts": [span["excerpt"] for span in new["reference_evidence"]],
                "old_reviewer_notes": old.get("reviewer_notes"),
                "new_reviewer_notes": new.get("reviewer_notes"),
                "question_unchanged": old["question"] == new["question"],
                "category_unchanged": old["category"] == new["category"],
                "difficulty_unchanged": old["difficulty"] == new["difficulty"],
                "supporting_chunk_ids_unchanged": old["supporting_chunk_ids"]
                == new["supporting_chunk_ids"],
            }
        )

    def apply_case(case_id: str, groups: list[str], reason: str, mutator) -> None:
        case = cases_by_id[case_id]
        old = deepcopy(case)
        mutator(case)
        if case["supporting_chunk_ids"] != old["supporting_chunk_ids"]:
            raise SystemExit(f"{case_id}: supporting_chunk_ids changed")
        if case["question"] != old["question"] or case["category"] != old["category"] or case["difficulty"] != old["difficulty"]:
            raise SystemExit(f"{case_id}: question/category/difficulty changed")
        for span in case["reference_evidence"]:
            text = texts[span["chunk_id"]]
            if span["excerpt"] not in text:
                raise SystemExit(f"{case_id}: excerpt not in {span['chunk_id']}")
            if span["chunk_id"] not in case["supporting_chunk_ids"]:
                raise SystemExit(f"{case_id}: excerpt uses uncited chunk {span['chunk_id']}")
        record_change(case_id, groups, reason, old, case)

    # --- Trim gold to the question ---
    apply_case(
        "qac_004_clinic_walkin_fee",
        ["trim_gold"],
        "Question asks only whether routine clinic services require payment. Drop office, who-may-avail, and processing time from the gold.",
        lambda case: (
            case.update(
                {
                    "reference_answer": (
                        "The Citizen's Charter Routine Medical and Dental Services card lists Fees as None."
                    ),
                    "reviewer_notes": (
                        "Stage 3.1C: gold trimmed to the fee question. Office, who-may-avail, and "
                        "processing time remain on the same card but are not part of the reference answer."
                    ),
                    "reference_evidence": [
                        clone_span(case, case["supporting_chunk_ids"][0], slice_excerpt(texts[case["supporting_chunk_ids"][0]], "Fees\nNone", "Fees\nNone")),
                    ],
                }
            )
        ),
    )

    apply_case(
        "qac_008_latin_cum_laude",
        ["trim_gold"],
        "Question asks only the cum laude range for a degree course. Sibling honors stay in the excerpt as table context but are removed from the gold.",
        lambda case: case.update(
            {
                "reference_answer": (
                    "For a degree course, cum laude is listed as a final grade of 1.46 to 1.75."
                ),
                "reviewer_notes": (
                    "Stage 3.1C: gold trimmed to the asked cum laude range. The same table also lists "
                    "summa cum laude and magna cum laude, and non-degree honors use different award names."
                ),
            }
        ),
    )

    apply_case(
        "qac_009_counseling_office",
        ["trim_gold"],
        "Question asks which office provides counseling and whether walk-in is possible. Drop requirements and processing time from the gold.",
        lambda case: case.update(
            {
                "reference_answer": (
                    "Counseling is under Guidance and Counseling. Client steps include endorsement, referral, or walk-in."
                ),
                "reviewer_notes": (
                    "Stage 3.1C: gold trimmed to office and walk-in. Requirements and total processing "
                    "time are on the same card but are not part of the reference answer."
                ),
                "reference_evidence": [
                    clone_span(
                        case,
                        case["supporting_chunk_ids"][0],
                        slice_excerpt(texts[case["supporting_chunk_ids"][0]], "Office / Division\nGuidance and Counseling", "Office / Division\nGuidance and Counseling"),
                    ),
                    clone_span(
                        case,
                        case["supporting_chunk_ids"][0],
                        slice_excerpt(
                            texts[case["supporting_chunk_ids"][0]],
                            "1. Client Step: Endorsement, referral, walk-in",
                            "1. Client Step: Endorsement, referral, walk-in",
                        ),
                    ),
                ],
            }
        ),
    )

    apply_case(
        "qac_021_student_id_processing_office",
        ["trim_gold"],
        "Question asks where a student ID is processed and who may avail. Drop COR, fee, and processing time from the gold.",
        lambda case: case.update(
            {
                "reference_answer": (
                    "Processing of Student ID is under the Business Affairs Office. Who may avail is Students, Employees and Alumni."
                ),
                "reviewer_notes": (
                    "Stage 3.1C: gold trimmed to office and who-may-avail. This is student ID processing, "
                    "not ID validation at OSAS."
                ),
                "reference_evidence": [
                    clone_span(
                        case,
                        case["supporting_chunk_ids"][0],
                        slice_excerpt(
                            texts[case["supporting_chunk_ids"][0]],
                            "Office / Division\nBusiness Affairs Office\n\nWho May Avail\nStudents, Employees and Alumni",
                            "Office / Division\nBusiness Affairs Office\n\nWho May Avail\nStudents, Employees and Alumni",
                        ),
                    ),
                ],
            }
        ),
    )

    apply_case(
        "qac_030_library_reference_who",
        ["trim_gold"],
        "Question asks who may use library reference assistance and what ID is required. Drop fee and processing time from the gold.",
        lambda case: case.update(
            {
                "reference_answer": (
                    "Library Reference Assistance is a Library service. Who may avail is Students, Faculty, Outside Researchers. The listed requirement is an LSPU ID."
                ),
                "reviewer_notes": (
                    "Stage 3.1C: gold trimmed to who-may-avail and the listed ID. Student inquiry about a "
                    "student-available library service whose Charter client list also names other groups."
                ),
                    "reference_evidence": [
                        clone_span(
                        case,
                        case["supporting_chunk_ids"][0],
                        slice_excerpt(
                            texts[case["supporting_chunk_ids"][0]],
                            "Office / Division\nLibrary\n\nWho May Avail\nStudents, Faculty, Outside Researchers\n\nRequirements\n- Requirement: LSPU ID BAO",
                            "Office / Division\nLibrary\n\nWho May Avail\nStudents, Faculty, Outside Researchers\n\nRequirements\n- Requirement: LSPU ID BAO",
                        ),
                    ),
                ],
            }
        ),
    )

    # --- Expand excerpts from already-cited chunks ---
    apply_case(
        "qac_005_accounting_clearance",
        ["expand_excerpts"],
        "Gold already states ID presentation; add the requirement and client-step sentences from the cited clearance chunk.",
        lambda case: case.update(
            {
                "reviewer_notes": (
                    "Stage 3.1C: added ID-verification excerpts from the already-cited Accounting "
                    "clearance chunk. Do not invent a clearance fee; the card lists Fees None."
                ),
                "reference_evidence": case["reference_evidence"][:1]
                + [
                    clone_span(
                        case,
                        case["supporting_chunk_ids"][0],
                        slice_excerpt(
                            texts[case["supporting_chunk_ids"][0]],
                            "- Requirement: Student ID for Student Number Verification Client/Student",
                            "- Requirement: Student ID for Student Number Verification Client/Student",
                        ),
                    ),
                    clone_span(
                        case,
                        case["supporting_chunk_ids"][0],
                        slice_excerpt(
                            texts[case["supporting_chunk_ids"][0]],
                            "Student to present his/her ID for verification of student number in the system",
                            "Student to present his/her ID for verification of student number in the system",
                        ),
                    ),
                ]
                + case["reference_evidence"][1:],
            }
        ),
    )

    apply_case(
        "qac_014_refund_schedule",
        ["expand_excerpts"],
        "Gold includes the HD/LOA entitlement and the matriculation/registration exception; excerpt that lead-in from the cited refund chunk.",
        lambda case: case.update(
            {
                "reviewer_notes": (
                    "Stage 3.1C: added the entitlement/exception sentence from the already-cited "
                    "refund chunk. Does not cover laboratory or miscellaneous non-refund rules."
                ),
                "reference_evidence": [
                    clone_span(
                        case,
                        case["supporting_chunk_ids"][0],
                        slice_excerpt(
                            texts[case["supporting_chunk_ids"][0]],
                            "A student who has paid the enrolment fees and who is granted Honorable Dismissal/Transfer Credentials or Leave of Absence (LOA) is entitled to a refund of their fees, except matricula- tion or registration fee, in accordance with the following schedule:",
                            "A student who has paid the enrolment fees and who is granted Honorable Dismissal/Transfer Credentials or Leave of Absence (LOA) is entitled to a refund of their fees, except matricula- tion or registration fee, in accordance with the following schedule:",
                        ),
                    ),
                    *case["reference_evidence"],
                ],
            }
        ),
    )

    def mutate_017(case: dict) -> None:
        chunk_id = case["supporting_chunk_ids"][0]
        text = texts[chunk_id]
        case["reviewer_notes"] = (
            "Stage 3.1C: excerpts expanded to cover the prescribed-uniform and jeans sentences "
            "already used in the gold. The prohibited-attire list after the colon is incomplete in "
            "this chunk; do not invent items."
        )
        case["reference_evidence"] = [
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "1.1. The prescribed uniform shall be worn in all classroom sessions and the proper field/laboratory attire or work clothes for the field/ laboratory activities and/or as prescribed by the instructor/ profes- sors-in-charge.",
                    "1.1. The prescribed uniform shall be worn in all classroom sessions and the proper field/laboratory attire or work clothes for the field/ laboratory activities and/or as prescribed by the instructor/ profes- sors-in-charge.",
                ),
            ),
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "1.2. P.E. uniforms shall be worn only during P.E. classes. Students wearing P.E. uniform will not be allowed to enter academic classes.\n1.3. University t-shirt shall be worn every Wednesday while department shirt shall be worn every Friday. Blue jeans and/or maong trouser (pants) following the dress code will be acceptable.",
                    "1.2. P.E. uniforms shall be worn only during P.E. classes. Students wearing P.E. uniform will not be allowed to enter academic classes.\n1.3. University t-shirt shall be worn every Wednesday while department shirt shall be worn every Friday. Blue jeans and/or maong trouser (pants) following the dress code will be acceptable.",
                ),
            ),
        ]

    apply_case(
        "qac_017_uniform_schedule",
        ["expand_excerpts"],
        "Gold already includes 1.1 and jeans; excerpt those sentences from the already-cited uniforms chunk.",
        mutate_017,
    )

    def mutate_020(case: dict) -> None:
        chunk_id = case["supporting_chunk_ids"][0]
        text = texts[chunk_id]
        case["reviewer_notes"] = (
            "Stage 3.1C: excerpt extended through the PSA birth/marriage line and 2.13 extras "
            "already used in the gold."
        )
        case["reference_evidence"] = [
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "- Transfer Credential/Honorable Dismissal from the schoollast attended",
                    "for testing done in an outside facility.",
                ),
            ),
        ]

    apply_case(
        "qac_020_transferee_documents",
        ["expand_excerpts"],
        "Gold includes PSA birth/marriage and other-requirement lines that follow on the same cited chunk; extend the excerpt.",
        mutate_020,
    )

    def mutate_022(case: dict) -> None:
        chunk_id = case["supporting_chunk_ids"][0]
        text = texts[chunk_id]
        case["reviewer_notes"] = (
            "Stage 3.1C: added the submit/verify/forward/inform sentences from the already-cited "
            "unscheduled-subject card."
        )
        case["reference_evidence"] = [
            clone_span(
                case,
                chunk_id,
                slice_excerpt(text, "Office / Division\nColleges", "Office / Division\nColleges"),
            ),
            case["reference_evidence"][0],
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "Submits letter request for the offering of unscheduled subject/s and copy of evaluation of grades from the Office of the Registrar to the Office of the",
                    "Submits letter request for the offering of unscheduled subject/s and copy of evaluation of grades from the Office of the Registrar to the Office of the",
                ),
            ),
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "Receives the letter request and verifies the need for the offering of unscheduled subject/s Forward request to the Office of the Registrar Forwards the request to the OVPAA for approval Informs the student requested has been offered (or not) upon receipt of approves request",
                    "Receives the letter request and verifies the need for the offering of unscheduled subject/s Forward request to the Office of the Registrar Forwards the request to the OVPAA for approval Informs the student requested has been offered (or not) upon receipt of approves request",
                ),
            ),
            *case["reference_evidence"][1:],
        ]

    apply_case(
        "qac_022_unscheduled_subject",
        ["expand_excerpts"],
        "Gold describes verification, forwarding, and informing the student; excerpt those agency-action sentences from the cited card.",
        mutate_022,
    )

    def mutate_023(case: dict) -> None:
        chunk_52 = "cec01713-c1ba-4061-9404-ffaa1d8e70dd::52"
        case["reviewer_notes"] = (
            "Stage 3.1C: added the 75%/50%/no-refund schedule from the already-cited refund chunk. "
            "Two handbook sections; do not collapse them into a single percentage."
        )
        case["reference_evidence"] = [
            case["reference_evidence"][0],
            clone_span(
                case,
                chunk_52,
                slice_excerpt(
                    texts[chunk_52],
                    "3.1. seventy-five percent (75%): within the week from the opening of classes\n3.2. fifty percent (50%): within the period from the second to the fourth week\n3.3. No refund: after the fourth week from the opening of classes",
                    "3.1. seventy-five percent (75%): within the week from the opening of classes\n3.2. fifty percent (50%): within the period from the second to the fourth week\n3.3. No refund: after the fourth week from the opening of classes",
                ),
            ),
            case["reference_evidence"][1],
        ]

    apply_case(
        "qac_023_refund_and_nonrefundable_fees",
        ["expand_excerpts"],
        "Gold restates the 75/50/none schedule; excerpt those numbered lines from already-cited chunk ::52.",
        mutate_023,
    )

    def mutate_025(case: dict) -> None:
        chunk_101 = "cec01713-c1ba-4061-9404-ffaa1d8e70dd::101"
        chunk_104 = "cec01713-c1ba-4061-9404-ffaa1d8e70dd::104"
        text_101 = texts[chunk_101]
        text_104 = texts[chunk_104]
        case["reference_answer"] = (
            "A grade of 4.00 may be removed by repeating the subject or by re-examination. "
            "The highest grade a student must obtain upon re-examination is 3.00. If the removal "
            "examination is failed, a student is given a grade of 5.00. Section 5.3.1 as stored says "
            "a student is allowed only one (1) removal examination, which must be taken within one (1) "
            "academic year from the removed within the prescribed period, it will be automatically "
            "changed to 5.00. That 5.3.1 sentence is OCR-broken and is not rewritten into a cleaner rule. "
            "If the subject for removal of grade is a pre-requisite for the succeeding semester, it must "
            "be accomplished before the next enrolment, superseding the one-year time frame stipulated in "
            "5.3.1. The removal fee is P20 per unit. Special removal examination may also be given upon "
            "approval of a written petition from the College Dean; a fee of P100 per unit is charged for "
            "this removal. If INC is not completed within the prescribed period (one year), a grade of "
            "incomplete will automatically be changed to 5.0."
        )
        case["reviewer_notes"] = (
            "Stage 3.1C: excerpts expanded for 5.3.1, 5.3.2, and the special-removal Dean-petition "
            "sentence. Gold keeps the stored 5.3.1 wording instead of reconstructing it. P20 and P100 "
            "remain distinct fees."
        )
        case["reference_evidence"] = [
            case["reference_evidence"][0],
            clone_span(
                case,
                chunk_101,
                _excerpt_531(text_101),
            ),
            clone_span(
                case,
                chunk_101,
                slice_excerpt(
                    text_101,
                    "5.3.2. If the subject for removal of grade is a pre-requisite for the succeeding semester, it must be accomplished before the next enrolment, superseding the one-year time frame stipulated in\n5.3.1.",
                    "5.3.2. If the subject for removal of grade is a pre-requisite for the succeeding semester, it must be accomplished before the next enrolment, superseding the one-year time frame stipulated in\n5.3.1.",
                ),
            ),
            case["reference_evidence"][1],
            case["reference_evidence"][2],
            clone_span(
                case,
                chunk_104,
                slice_excerpt(
                    text_104,
                    "5.2.3. Special removal examination may also be given upon approval of a written petition from the College Dean. A fee of P100 per unit is charged for this removal.",
                    "5.2.3. Special removal examination may also be given upon approval of a written petition from the College Dean. A fee of P100 per unit is charged for this removal.",
                ),
            ),
        ]

    apply_case(
        "qac_025_four_point_zero_and_inc",
        ["expand_excerpts", "preserve_ocr_ambiguity"],
        "Add 5.3.1/5.3.2 and the full special-removal sentence; keep 5.3.1 as stored OCR rather than smoothing it into a clean one-year rule.",
        mutate_025,
    )

    def mutate_027(case: dict) -> None:
        chunk_id = case["supporting_chunk_ids"][0]
        text = texts[chunk_id]
        case["reviewer_notes"] = (
            "Stage 3.1C: excerpt expanded to include the LOA-form sentence from the already-cited "
            "graduate LOA chunk. Do not apply the two-year cap to undergraduate LOA."
        )
        case["reference_evidence"] = [
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "A graduate student who intends to take a leave of absence must accomplish a Leave of Absence (LOA) form, indi- cating the reason for the request and the length of time for the absence. The length of time for LOA, which should not exceed two (2) years, is considered a part of the residency. Should there be an extension beyond the prescribed max- imum residency, the student shall take one (1) penalty subject (additional course not yet taken) for every year of the extension. Failure to submit a LOA would mean absence without official leave (AWOL)",
                    "A graduate student who intends to take a leave of absence must accomplish a Leave of Absence (LOA) form, indi- cating the reason for the request and the length of time for the absence. The length of time for LOA, which should not exceed two (2) years, is considered a part of the residency. Should there be an extension beyond the prescribed max- imum residency, the student shall take one (1) penalty subject (additional course not yet taken) for every year of the extension. Failure to submit a LOA would mean absence without official leave (AWOL)",
                ),
            ),
        ]

    apply_case(
        "qac_027_graduate_loa",
        ["expand_excerpts"],
        "Gold already requires the LOA form; excerpt that sentence from the cited graduate LOA chunk.",
        mutate_027,
    )

    def mutate_028(case: dict) -> None:
        chunk_id = case["supporting_chunk_ids"][0]
        text = texts[chunk_id]
        case["reviewer_notes"] = (
            "Stage 3.1C: added indebtedness and disciplinary-exclusion sentences from the "
            "already-cited Honorable Dismissal chunk."
        )
        case["reference_evidence"] = [
            case["reference_evidence"][0],
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "Honorable Dismissal Policy: All indebtedness to the university must be settled before a statement of Honorable Dismissal will be issued.",
                    "Honorable Dismissal Policy: All indebtedness to the university must be settled before a statement of Honorable Dismissal will be issued.",
                ),
            ),
            case["reference_evidence"][1],
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "Non-granting of Honorable Dismissal: A student who leaves the university for the reason of suspension, dropping or expulsion due to disciplinary action/s shall not be entitled to Honorable Dismissal.",
                    "Non-granting of Honorable Dismissal: A student who leaves the university for the reason of suspension, dropping or expulsion due to disciplinary action/s shall not be entitled to Honorable Dismissal.",
                ),
            ),
        ]

    apply_case(
        "qac_028_honorable_dismissal_petition",
        ["expand_excerpts"],
        "Gold already states debt settlement and disciplinary exclusion; excerpt those sentences from the cited HD chunk.",
        mutate_028,
    )

    # --- OCR / ambiguity ---
    apply_case(
        "qac_018_scholarship_requirements",
        ["preserve_ocr_ambiguity"],
        "Stop reconstructing OCR-broken scholarship requirement labels into clean document names.",
        lambda case: case.update(
            {
                "reference_answer": (
                    "Processing of Scholarship and Financial Assistance is under the Scholarship and "
                    "Financial Assistance Unit, who may avail is ALL, and the listed fee is None. The "
                    "stored requirement lines are OCR-broken and are not reconstructed here. As stored "
                    "they read: Application Form for Scholarship and Financial Scholarship; Assistance "
                    "Page Application Form (CHED Form) CHED; Assistance Certified True Copy of Grades "
                    "Registrar; Certified True Copy of Certificate of Registration Registrar Financial "
                    "Documents DSWD (where to secure: and BIR Office); Notarized Certificate of No "
                    "Employment and No Law Scholarship; and Copy of ID with 3 specimen/Signature BAO."
                ),
                "reviewer_notes": (
                    "Stage 3.1C: gold quotes the stored OCR-broken requirement lines instead of "
                    "cleaning them into separate form names."
                ),
                "reference_evidence": [
                    *case["reference_evidence"][:4],
                    clone_span(
                        case,
                        case["supporting_chunk_ids"][0],
                        slice_excerpt(
                            texts[case["supporting_chunk_ids"][0]],
                            "- Requirement: Certified True Copy of Certificate of Registration Registrar Financial Documents DSWD\n  Where to Secure: and BIR Office",
                            "- Requirement: Certified True Copy of Certificate of Registration Registrar Financial Documents DSWD\n  Where to Secure: and BIR Office",
                        ),
                    ),
                    *case["reference_evidence"][5:],
                ],
            }
        ),
    )

    def mutate_019(case: dict) -> None:
        chunk_id = case["supporting_chunk_ids"][0]
        text = texts[chunk_id]
        case["reference_answer"] = (
            "The stored Free Higher Education paragraph says all students who are either currently "
            "enrolled at the time of the affectivity of the Universal Access to Quality Tertiary "
            "Education Act of 2017 or Unified Financial Assistance System for Tertiary Education Act, "
            "or UniFAST (Republic Act No. 10687. shall enroll at any time after that in a course "
            "leading to a bachelor's degree in the University shall be exempt from paying tuition and "
            "other school fees for units enrolled in. That sentence is OCR-broken, including the "
            "statute numbering and the join between currently enrolled and shall enroll at any time "
            "after that, so the corpus does not establish a single clean eligibility rule. Students "
            "are eligible to receive the benefits stipulated in 1.2. provided that they qualify the "
            "admission and re- tention policies of the University."
        )
        case["reviewer_notes"] = (
            "Stage 3.1C: gold preserves the garbled Free Higher Education sentence instead of "
            "smoothing it. Do not resolve the stored RA numbering against RA 10931."
        )
        case["reference_evidence"] = [
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "Free Higher Education: All students who are either currently enrolled at the time of the affectivity of the Universal Access to Quality Tertiary Education Act of 2017 or Unified Financial Assistance System for Tertiary Education Act, or UniFAST (Republic Act No.\n10687. shall enroll at any time after that in a course leading to a bachelor",
                    "shall be exempt from paying tuition and other school fees for units enrolled in.",
                ),
            ),
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "Students are eligible to receive the benefits stipulated in 1.2. provided that they qualify the admission and re- tention policies of the University.",
                    "Students are eligible to receive the benefits stipulated in 1.2. provided that they qualify the admission and re- tention policies of the University.",
                ),
            ),
        ]

    apply_case(
        "qac_019_free_higher_education",
        ["preserve_ocr_ambiguity"],
        "Preserve the garbled currently-enrolled / shall-enroll-after dual wording and stored RA numbering.",
        mutate_019,
    )

    def mutate_029(case: dict) -> None:
        chunk_107 = "cec01713-c1ba-4061-9404-ffaa1d8e70dd::107"
        chunk_81 = "cec01713-c1ba-4061-9404-ffaa1d8e70dd::81"
        chunk_162 = "cec01713-c1ba-4061-9404-ffaa1d8e70dd::162"
        case["reference_answer"] = (
            "The Student Handbook does not state one absence-drop threshold that applies to every student. "
            "The undergraduate Attendance / Absence section says a student accumulating unexcused absences "
            "equivalent to twenty percent (25%) of the total number of hours per day session for a "
            "particular subject shall be dropped from that subject or class. That sentence writes the words "
            "twenty percent next to (25%). Time lost due to late enrolment is treated as absence. "
            "The undergraduate Dropping section says students shall be dropped if they have an accumulated "
            "absence of at least 25% of the total number of class hours in a semester. That is a semester "
            "class-hours measure, not the same wording as the per-day-session Absence section. "
            "The graduate Attendance policy says a student accumulating absences equivalent to twenty percent "
            "(20%) of the total number of hour per day session for a particular subject shall be dropped "
            "from that subject or class. That rule is in the Graduate Studies attendance article. "
            "These passages are different sections and, for the graduate card, a different student population. "
            "The corpus does not say which statement supersedes another."
        )
        case["reviewer_notes"] = (
            "Stage 3.1C: gold reports three distinct stored passages (undergraduate day-session wording "
            "clash, undergraduate semester-hours dropping, graduate 20%) and does not treat them as two "
            "competing thresholds for the same student group."
        )
        case["reference_evidence"] = [
            clone_span(
                case,
                chunk_107,
                slice_excerpt(
                    texts[chunk_107],
                    "A student accumulating unexcused absences from class, equivalent to twenty percent (25%) of the total number of hours per day session for a particular subject, shall be dropped from the roll of students for the particular subject or class, as the case may be. Time lost due to late enrolment shall be considered as a time lost by absence.",
                    "A student accumulating unexcused absences from class, equivalent to twenty percent (25%) of the total number of hours per day session for a particular subject, shall be dropped from the roll of students for the particular subject or class, as the case may be. Time lost due to late enrolment shall be considered as a time lost by absence.",
                ),
            ),
            clone_span(
                case,
                chunk_81,
                slice_excerpt(
                    texts[chunk_81],
                    "Students shall be dropped if they have an accumulated absence of at least 25% of the total number of class hours in a semester.",
                    "Students shall be dropped if they have an accumulated absence of at least 25% of the total number of class hours in a semester.",
                ),
            ),
            clone_span(
                case,
                chunk_162,
                slice_excerpt(
                    texts[chunk_162],
                    "A student accumulating absences from class which is equivalent to twenty percent (20%) of the total number of hour per day session for a partic- ular subject shall be dropped from the roll of students for the particular subject or class.",
                    "A student accumulating absences from class which is equivalent to twenty percent (20%) of the total number of hour per day session for a partic- ular subject shall be dropped from the roll of students for the particular subject or class.",
                ),
            ),
        ]

    apply_case(
        "qac_029_absence_drop_threshold_conflict",
        ["preserve_ocr_ambiguity"],
        "Reframe gold as three context-distinct stored passages, including the internal twenty percent (25%) wording, without picking a winner.",
        mutate_029,
    )

    def mutate_032(case: dict) -> None:
        chunk_id = case["supporting_chunk_ids"][0]
        text = texts[chunk_id]
        case["reference_answer"] = (
            "The Enrollment card is OCR-broken across numbered steps. One stored client-step fragment "
            "ends All old College and the next begins Students, Old GSAR Students: Login to the Student "
            "Web Portal and enlists the subjects to be enrolled. The stored text does not cleanly establish "
            "that returning college students, as a labeled group, enlist on the portal. Separately, "
            "New/old college students: Log in to student portal to view the Certificate of Registration, "
            "and the card lists Issues certificate of registration (COR). Another stored line says "
            "college students who are not qualified for Free Higher Education, and other listed groups "
            "including GSA R Students, proceed to the Office of the Registrar to claim the COR."
        )
        case["reviewer_notes"] = (
            "Stage 3.1C: gold keeps the split Enrollment OCR lines instead of joining All old College "
            "with Students, Old GSAR Students into a returning-college portal-enlistment rule."
        )
        case["reference_evidence"] = [
            clone_span(
                case,
                chunk_id,
                slice_excerpt(
                    text,
                    "Preenrolment form from the Dean's Office. All old College",
                    "Preenrolment form from the Dean's Office. All old College",
                ),
            ),
            *case["reference_evidence"],
        ]

    apply_case(
        "qac_032_enrollment_old_students_portal",
        ["preserve_ocr_ambiguity"],
        "Do not join OCR-split Enrollment steps into a claim that returning college students enlist on the portal.",
        mutate_032,
    )

    unchanged = [case["case_id"] for case in payload["cases"] if case["case_id"] not in CORRECTED_CASE_IDS]
    if set(item["case_id"] for item in changelog) != CORRECTED_CASE_IDS:
        raise SystemExit(f"changelog mismatch: {sorted(item['case_id'] for item in changelog)}")
    if len(unchanged) != 18:
        raise SystemExit(f"expected 18 unchanged cases, got {len(unchanged)}: {unchanged}")

    payload["dataset_version"] = REVISED_VERSION
    payload["notes"] = (
        "Revision of 2026-11-09-v1 after the Stage 3.1B independent audit. Eighteen cases were "
        "corrected (trim gold to the question, expand excerpts from already-cited chunks, or preserve "
        "stored OCR/ambiguity). Original v1 is preserved at "
        "qa_citation_eval_dataset.2026-11-09-v1.json. Generation provenance is unchanged "
        "(cursor-grok-4.6 / qac-gen-v1-stage3.1b-20261109). Reference answers are not human-verified. "
        "See qa_citation_eval_dataset.correction_audit.json and the original generation audit."
    )

    body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    live_bytes = body.replace("\n", "\r\n").encode("utf-8")
    LIVE_DATASET.write_bytes(live_bytes)
    new_sha256 = hashlib.sha256(live_bytes).hexdigest()

    audit = {
        "stage": "3.1C",
        "original_dataset_version": ORIGINAL_VERSION,
        "corrected_dataset_version": REVISED_VERSION,
        "original_dataset_path": "backend/benchmarks/evaluation/qa_citation_eval_dataset.2026-11-09-v1.json",
        "live_dataset_path": "backend/benchmarks/evaluation/qa_citation_eval_dataset.json",
        "original_generation_audit_path": "backend/benchmarks/evaluation/qa_citation_eval_dataset.generation_audit.json",
        "preserved_generation_audit_path": "backend/benchmarks/evaluation/qa_citation_eval_dataset.generation_audit.2026-11-09-v1.json",
        "original_dataset_sha256": original_sha256,
        "corrected_dataset_sha256": new_sha256,
        "annotation_method": "ai_assisted_grounded_generation",
        "human_verified": False,
        "generation_provenance_retained": True,
        "generation_model": payload["generation"]["model"],
        "generation_prompt_version": payload["generation"]["prompt_version"],
        "cases_corrected": sorted(CORRECTED_CASE_IDS),
        "cases_unchanged": unchanged,
        "insufficient_evidence_cases_untouched": True,
        "supporting_chunks_added": False,
        "changelog": changelog,
        "notes": (
            "Targeted corrections after Stage 3.1B DO NOT APPROVE. Loader membership is not semantic "
            "correctness. Gold remains AI-assisted and not human-verified."
        ),
    }
    audit_body = json.dumps(audit, indent=2, ensure_ascii=False) + "\n"
    CORRECTION_AUDIT.write_bytes(audit_body.replace("\n", "\r\n").encode("utf-8"))
    print(f"original_sha256 {original_sha256}")
    print(f"corrected_sha256 {new_sha256}")
    print(f"corrected_cases {len(changelog)}")
    print(f"unchanged {len(unchanged)}")


def _excerpt_531(text: str) -> str:
    start = text.index("5.3.1. A student is allowed only one (1) removal examination")
    end_marker = "5.3.2."
    end = text.index(end_marker, start)
    excerpt = text[start:end].rstrip("\n")
    if excerpt not in text:
        raise SystemExit("5.3.1 excerpt not contiguous")
    return excerpt


if __name__ == "__main__":
    main()

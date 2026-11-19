"""AI Reviewer 1 labels. Independent of Reviewer 2. Not human-reviewed."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
inp = json.loads((OUT / "annotator_input.json").read_text(encoding="utf-8"))
by_id = {c["case_id"]: c for c in inp["cases"]}
valid = set(inp["valid_true_labels"]) | {"MARK_FOR_REVIEW"}

# label, evidence_sufficient, justification, evidence
R1 = {
    "cls_q_rag_benchmark_01": ("Transcript of Records", True, "Asks TOR copy fee.", "How much does it cost to get a copy of my Transcript of Records?"),
    "cls_q_rag_benchmark_02": ("Graduation", True, "Asks diploma (graduation credential) second-copy fee, not TOR.", "fee for a second copy of my diploma"),
    "cls_q_rag_benchmark_03": ("Registration", True, "Enrollment office is registration/enrollment.", "Which office handles student enrollment?"),
    "cls_q_rag_benchmark_04": ("Withdrawal", True, "Dropping a subject is withdrawal/dropping.", "How much does it cost to drop a subject?"),
    "cls_q_rag_benchmark_05": ("Library", True, "Library circulation overdue fee.", "library circulation service if my book is overdue"),
    "cls_q_rag_benchmark_06": ("Entrance Examination", True, "Entrance exam duration including orientation.", "How long does the LSPU entrance examination take"),
    "cls_q_rag_benchmark_07": ("MARK_FOR_REVIEW", False, "Student ID validation is not course Validation; no ID-card subcategory.", "process for validating my student ID"),
    "cls_q_rag_benchmark_08": ("Retention", True, "Failing >75% of units is scholastic delinquency/retention.", "if I fail more than 75% of my units"),
    "cls_q_rag_benchmark_09": ("MARK_FOR_REVIEW", False, "Faculty teaching load is faculty-manual HR, not a student subcategory.", "How is faculty teaching load determined?"),
    "cls_q_rag_benchmark_10": ("MARK_FOR_REVIEW", False, "Faculty member duties are not Administrative Officials (officer list).", "responsibilities of an LSPU faculty member"),
    "cls_q_rag_benchmark_11": ("Honorable Dismissal", True, "Asks definition of honorable dismissal.", "What is honorable dismissal for a student?"),
    "cls_q_rag_benchmark_12": ("Administrative Officials", True, "Asks current university president.", "Who is the current LSPU president?"),
    "cls_q_cg_gate3_grading_gwa": ("Grading System", True, "Passing grade and GWA computation.", "passing grade and how is GWA computed"),
    "cls_q_cg_cert_final_enroll_t0": ("Registration", True, "How to enroll is registration.", "How do I enroll?"),
    "cls_q_cg_cert_final_switch_tor_followup": ("Transcript of Records", True, "Follow-up about TOR.", "Now tell me about TOR."),
    "cls_q_cg_cert_final_oos_stale": ("MARK_FOR_REVIEW", False, "National politics; out of LSPU taxonomy.", "Who is the president of the Philippines?"),
    "cls_q_cg_cert_final_good_moral_fee": ("Good Moral", True, "Good Moral Certificate fee.", "How much does a Good Moral Certificate cost?"),
    "cls_q_cg_val_active_service_enroll_t0": ("Registration", True, "Enrolling as a new student is still enrollment/registration.", "How do I enroll as a new student at LSPU?"),
    "cls_q_cg_merged_chat_institutional_identity": ("MARK_FOR_REVIEW", False, "What is LSPU is institutional identity; VMG would be a stretch.", "What is Laguna State Polytechnic University?"),
    "cls_q_cg_merged_chat_drop_subject_no_evidence": ("Withdrawal", True, "Dropping a subject and late-drop grade effects.", "How do I drop a subject and what happens to my grades if I drop late?"),
    "cls_q_cg_merged_chat_scholarship_surprising_top_source": ("Scholarships", True, "How to apply for a scholarship.", "How do I apply for a scholarship at LSPU?"),
    "cls_q_cg_merged_chat_request_tor": ("Transcript of Records", True, "Requesting TOR.", "How do I request a Transcript of Records?"),
    "cls_q_cg_grade_correction_full_candidate_pool_repro": ("Grading System", True, "Faculty grade-correction approval is still grading policy.", "correct grades for 30% of a class"),
    "cls_q_fg_a1_refund_schedule_exact": ("Fee Refunds", True, "LOA week-3 refund percentage.", "percentage of my paid fees will be refunded"),
    "cls_q_fg_a2_coe_fee_exact": ("Certificates", True, "Certificate of Employment fee and time.", "Certificate of Employment"),
    "cls_q_fg_b1_grade_correction_paraphrase": ("Grading System", True, "Student dispute window after grades release.", "how many days do I have to formally dispute it after grades come out"),
    "cls_q_fg_b2_validation_paraphrase": ("Validation", True, "Prior degree / whether to retake vs credit is validation/crediting.", "bachelor's degree from another school ... retake subjects I already passed"),
    "cls_q_fg_c1_fifty_percent_refund_trap": ("Fee Refunds", True, "Withdraw week-3 fee refund percent.", "percentage of fees do I get back if I withdraw"),
    "cls_q_fg_c2_junior_standing_trap": ("MARK_FOR_REVIEW", False, "Class standing (Junior) has no taxonomy subcategory; Freshmen is admissions.", "classified as a Junior student"),
    "cls_q_fg_d1_transcript_vs_enrollment_office": ("Transcript of Records", True, "TOR requirements and fee.", "request my Transcript of Records, and is there a fee"),
    "cls_q_fg_d2_oup_vs_ocd_request_letter": ("Requests", True, "Submitting a request letter for presidential approval.", "submit a request letter to the Office of the University President"),
    "cls_q_fg_e1_request_letter_vocabulary_collision": ("Student Organizations", True, "Student organization funding via Budget Office.", "request letter from my student organization"),
    "cls_q_fg_e2_application_vocabulary_collision": ("Requests", True, "Form to substitute one course subject for another.", "substitute one of my course subjects for another"),
    "cls_q_fg_f1_validation_multiclaim_singlesource": ("Validation", True, "Skip validation for equivalent subjects and cap.", "skip validation for equivalent subjects"),
    "cls_q_fg_g1_multiclaim_multisource": ("Validation", True, "Transfer credit validation grade requirement and cap.", "credits to validate ... cap on how many credits"),
    "cls_q_fg_h1_partially_unsupported": ("Validation", True, "Subject validation fee and processing days.", "fee for subject validation"),
    "cls_q_fg_j1_good_moral_near_duplicate": ("Good Moral", True, "Alumnus Good Moral Certificate requirements.", "Good Moral Certificate — what do I need to bring"),
    "cls_q_fg_k1_class_standing_percentage_range": ("MARK_FOR_REVIEW", False, "Sophomore vs Freshman unit standing is not the Freshmen admissions class.", "considered a Sophomore instead of a Freshman"),
    "cls_q_fg_l1_refund_deadline_window": ("Fee Refunds", True, "Last week to withdraw and still get any refund.", "withdraw to get any refund at all"),
    "cls_q_fg_m1_crediting_approval_chain": ("Validation", True, "Who approves crediting of previous subjects on transfer.", "previous subjects get credited when I transfer"),
    "cls_q_fg_n1_out_of_scope_recipe": ("MARK_FOR_REVIEW", False, "Cooking recipe is out of scope.", "recipe for adobo"),
    "cls_q_fg_n2_out_of_scope_unrelated_school": ("MARK_FOR_REVIEW", False, "University of the Philippines admissions, not LSPU.", "admission requirements at the University of the Philippines"),
    "cls_q_fg_o1_role_student_baseline": ("MARK_FOR_REVIEW", False, "Asks both retention and good moral in one question; do not force one class.", "retention/good moral standard"),
    "cls_q_fg_o2_role_faculty_substitution": ("MARK_FOR_REVIEW", False, "Substitute instructor is faculty operations, not a student class.", "arrange a substitute instructor"),
    "cls_q_pilot_pilot_p1_previous_degree_transfer_credit": ("Validation", True, "How much prior coursework can be credited without validation.", "credited without validation"),
    "cls_q_pilot_pilot_p2_grade_correction_after_30_days": ("Grading System", True, "Grade correction after 30 days.", "correction of a grade after more than 30 days"),
    "cls_q_pilot_pilot_p3_paraphrased_transfer_credit": ("Validation", True, "Cap on equivalent subjects without validation exams.", "count toward my new program without taking validation exams"),
    "cls_q_pilot_pilot_p4_multiple_policy_facts": ("Validation", True, "Degree-holder transfer: credit without validation and maximum amount.", "credited without validation and the maximum amount"),
    "cls_q_pilot_pilot_p5_out_of_scope_mars": ("MARK_FOR_REVIEW", False, "Weather on Mars is out of scope.", "weather on Mars"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__1": ("Transcript of Records", True, "Charter service for issuance of TOR/transfer credentials/certifications.", "Issuance of Transcript of Records/Transfer Credentials/Certifications"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__0": ("Registration", True, "Charter Enrollment service at Registrar.", "This service provides assistance for Enrollment."),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__82": ("Withdrawal", True, "Dropping grades policy after dropping a subject.", "If a subject is dropped after the first day of the midterm"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__97": ("Withdrawal", True, "Charter Dropping of Subjects service.", "assistance for Dropping of Subjects"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__10": ("Library", True, "Library Circulation Service.", "assistance for Library Circulation Service"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__78": ("Entrance Examination", True, "LSPU Entrance Examination service.", "assistance for LSPU Entrance Examination"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__14": ("MARK_FOR_REVIEW", False, "ID Validation is ID-card service, not course Validation.", "assistance for ID Validation"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__66": ("Retention", True, "Scholastic delinquency under Retention Policies.", "Article 5 > Retention Policies > Sec. 4 > Scholastic Delinquency"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__69": ("Retention", True, "Disqualification exemption under Retention Policies.", "Retention Policies > Sec. 7 > Disqualification Exemption"),
    "cls_c_97e32a29-fa86-458c-9fe9-dba48f9605ce__14": ("MARK_FOR_REVIEW", False, "Faculty official time; no faculty-HR subcategory.", "All faculty shall: 1. observe strictly their official time"),
    "cls_c_97e32a29-fa86-458c-9fe9-dba48f9605ce__15": ("MARK_FOR_REVIEW", False, "Faculty attendance/absences; not student Attendance.", "Faculty member shall hold classes on time"),
    "cls_c_97e32a29-fa86-458c-9fe9-dba48f9605ce__16": ("MARK_FOR_REVIEW", False, "Faculty vertical alignment policy; not student taxonomy.", "Internal Policy on Vertical Alignment of Faculty"),
    "cls_c_97e32a29-fa86-458c-9fe9-dba48f9605ce__7": ("MARK_FOR_REVIEW", False, "Historical founding narrative is not VMG or officials.", "initially estab- lished in 1952 as a provincial"),
    "cls_c_97e32a29-fa86-458c-9fe9-dba48f9605ce__8": ("MARK_FOR_REVIEW", False, "Teaching-as-commitment prose is not a student class.", "Teaching is a personal commitment of oneself to others"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__117": ("Honorable Dismissal", True, "Defines honorable dismissal.", "Honorable Dismissal is voluntary with drawal from the college/university"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__118": ("Honorable Dismissal", True, "Honorable dismissal petition procedure.", "Honorable Dismissal Petition: A student of good standing"),
    "cls_c_97e32a29-fa86-458c-9fe9-dba48f9605ce__6": ("Administrative Officials", True, "Lists university president and VPs.", "DR. MARIO R. BRIONES University President"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__10": ("Administrative Officials", True, "Lists university president and VPs.", "DR. MARIO R. BRIONES University President"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__123": ("MARK_FOR_REVIEW", False, "Thesis approval-sheet signatories; no thesis subcategory.", "signing in the approval sheet: adviser, panel members"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__290": ("MARK_FOR_REVIEW", False, "Non-academic awards criteria; no awards subcategory.", "Non-academic Awards ... Criteria for Evaluation"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__452": ("Health Services", True, "Health and safety protocols when on campus.", "Health and safety protocols shall strictly be implemented"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__136": ("Graduate Programs", True, "Graduate Studies goals/objectives.", "Graduate Studies and Applied Research Goals and Objectives"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__478": ("Counseling", True, "Mental health services policy scope.", "The mental health services policy applies to students"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__49": ("MARK_FOR_REVIEW", False, "Employee official travel is staff HR, not student taxonomy.", "Facilitation of Employees’ Official Travels"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__155": ("Graduate Policies", True, "Graduate course-load/requirements table.", "Graduate Studies > Article 5 > Course Load and Requirements"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__207": ("Foreign Students", True, "Assist foreign students with government coordination.", "Assist foreign students with proper coordination"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__37": ("Admission Requirements", True, "IB diploma / foreign-student admission requirements.", "Admission Requirements > ... IBE (International Baccalaureate Diploma)"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__151": ("Registration", True, "Change of matriculation form is an enrollment change.", "change in matriculation ... form for change of ma"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__160": ("Graduate Policies", True, "Graduate residence requirements and time limit.", "Residence Requirements and Time Limit"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__167": ("Graduate Policies", True, "Graduate comprehensive examination fee.", "comprehensive examination fee is P1,000.00 for master’s"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__138": ("College of Agriculture", True, "Curricular offerings of College of Agriculture.", "Curricular Offerings - College of Agriculture ... Doctor of Philosophy in Agriculture"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__18": ("Undergraduate Programs", True, "BS Nutrition/Food Tech; no Nutrition college in taxonomy.", "BS Nutrition and Dietetics ... BS Food Technology"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__26": ("Graduate Programs", True, "MS Fisheries offerings; no Fisheries college in taxonomy.", "Master of Science in Fisheries major in Aquaculture"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__328": ("MARK_FOR_REVIEW", False, "Title medals/certificates but body is laboratory-specimen text; insufficient.", "Laboratory: It refers to a private or government facility that is capa ble of testing a specimen"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__488": ("MARK_FOR_REVIEW", False, "Garbled Appendix L form fields; cannot assign a class.", "I choose to decline - Daughter At This Time"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__39": ("MARK_FOR_REVIEW", False, "Building maintenance job orders; no facilities subcategory.", "Maintenance of Buildings and Facilities (Job Order Request)"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__111": ("Scholarships", True, "Scholarship grants article.", "Scholarship grants and all other forms of financial assistance"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__114": ("Scholarships", True, "SCUAA medalist full scholarship/training allowance.", "Full Scholarship/Training Allowance: SCUAA medalists"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__200": ("Scholarships", True, "Disseminate scholarship requirements to students.", "Disseminate information to students regarding the requirements"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__45": ("Transferees", True, "Admission requirements for student transferees.", "Student Transferees ... Transfer Credential/Honorable Dismissal"),
    "cls_c_da4a1832-7242-4e94-8ba6-bc0b9f2294bf__17": ("Good Moral", True, "Issuance of Good Moral Certificate (Transferee).", "Issuance of Good Moral Certificate (Transferee)"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__233": ("Student Welfare", True, "Major offense vandalism/destruction of property.", "Vandalism or Destruc tion of Public Properties"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__378": ("MARK_FOR_REVIEW", False, "Student-intern personality development; no internship class.", "Encourages student interns to develop their personality"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__464": ("Counseling", True, "Identification of mental health concerns.", "Anxiety Disorders (e.g., Generalized Anxiety Disorder"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__212": ("Student Welfare", True, "Major offenses including cybercrime/cyberbullying.", "Acts of Cybercrime ... Cyber bullying or bullying"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__425": ("LMS", True, "Flexible learning delivery mode.", "LSPU Flexible Learning Delivery ... Target Delivery Mode"),
    "cls_c_cec01713-c1ba-4061-9404-ffaa1d8e70dd__428": ("LMS", True, "Self-paced learning module for flexible learning.", "adopt the Self-Paced Learning Module (SLM)"),
}

missing = [cid for cid in by_id if cid not in R1]
extra = [cid for cid in R1 if cid not in by_id]
if missing or extra:
    raise SystemExit(f"missing={missing} extra={extra}")

cases = []
for cid, spec in R1.items():
    label, ok, just, ev = spec
    if label not in valid:
        raise SystemExit(f"invalid label {label!r} for {cid}")
    cases.append(
        {
            "case_id": cid,
            "component": by_id[cid]["component"],
            "label": label,
            "evidence_sufficient": ok,
            "justification": just,
            "evidence": ev,
        }
    )

payload = {
    "reviewer_id": "AI-R1",
    "reviewer_type": "AI",
    "annotation_method": "independent_ai_annotation",
    "note": "Not human-reviewed. Same-session Grok pass; Reviewer 2 is a separate agent.",
    "cases": cases,
}
(OUT / "reviewer1_annotations.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
mfr = sum(1 for c in cases if c["label"] == "MARK_FOR_REVIEW")
okn = sum(1 for c in cases if c["evidence_sufficient"])
print(f"wrote {len(cases)} r1 marks={mfr} sufficient={okn}")


if __name__ == "__main__":
    pass

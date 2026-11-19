"""Generate the QA-only live evaluation Word document."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent / "ASKa-Piyu_QA_Evaluation_Documentation.docx"
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
HEADER_FILL = "1F3A5F"
ALT_FILL = "EEF2F6"
PASS_FILL = "E6F4EA"
PARTIAL_FILL = "FFF8E6"
FAIL_FILL = "FDECEC"
ROLE_FILL = "EEF4FB"
CAPTION_GRAY = RGBColor(0x44, 0x44, 0x44)


def set_run_font(run, *, name="Times New Roman", size=12, bold=False, italic=False, color=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def add_page_number(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)
    set_run_font(run, size=10, color=NAVY)


def add_toc_field(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = r' TOC \o "1-3" \h \z \u '
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(sep)
    hint = paragraph.add_run(
        "Right-click this field in Microsoft Word and choose Update Field to refresh the table of contents."
    )
    set_run_font(hint, size=11, italic=True, color=RGBColor(0x55, 0x55, 0x55))
    run._r.append(end)


def shade_cell(cell, fill):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def set_cell_border(cell, color="B0B8C1"):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        tcBorders.append(el)
    tcPr.append(tcBorders)


def cell_text(cell, text, *, bold=False, size=10, color=None, align=WD_ALIGN_PARAGRAPH.LEFT):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    set_run_font(run, size=size, bold=bold, color=color)
    set_cell_border(cell)


def cap(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(12)
    run = p.add_run(text)
    set_run_font(run, size=10, italic=True, color=CAPTION_GRAY)
    return p


def add_table(doc, headers, rows, fills=None, caption=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for i, header in enumerate(headers):
        cell_text(table.rows[0].cells[i], header, bold=True, size=10, color=RGBColor(255, 255, 255))
        shade_cell(table.rows[0].cells[i], HEADER_FILL)
    for r, row in enumerate(rows):
        fill = (fills[r] if fills else None) or (ALT_FILL if r % 2 else "FFFFFF")
        for c, value in enumerate(row):
            cell_text(table.rows[r + 1].cells[c], value, size=10)
            shade_cell(table.rows[r + 1].cells[c], fill)
    if caption:
        cap(doc, caption)
    else:
        doc.add_paragraph()
    return table


def heading(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        set_run_font(run, size={1: 16, 2: 13, 3: 12}.get(level, 12), bold=True, color=NAVY)
    return p


def body(doc, text, *, italic=False, bold=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run(text)
    set_run_font(run, size=12, italic=italic, bold=bold)
    return p


def bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    if p.runs:
        p.runs[0].text = text
        set_run_font(p.runs[0], size=12)
    else:
        run = p.add_run(text)
        set_run_font(run, size=12)
    p.paragraph_format.space_after = Pt(3)
    return p


def flowchart(doc, lines, caption):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.rows[0].cells[0]
    cell.text = ""
    shade_cell(cell, "F7F9FC")
    set_cell_border(cell, color="1F3A5F")
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run("\n".join(lines))
    set_run_font(run, name="Consolas", size=9, color=NAVY)
    cap(doc, caption)


def configure_styles(doc):
    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    for level, size in ((1, 16), (2, 13), (3, 12)):
        style = styles[f"Heading {level}"]
        style.font.name = "Times New Roman"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = NAVY
        style.paragraph_format.space_before = Pt(16 if level == 1 else 12)
        style.paragraph_format.space_after = Pt(8)


def page_break(doc):
    p = doc.add_paragraph()
    run = p.add_run()
    run.add_break(WD_BREAK.PAGE)


def build():
    doc = Document()
    configure_styles(doc)
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)

    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    left = fp.add_run("ASKa-Piyu QA Evaluation  ·  Page ")
    set_run_font(left, size=10, color=NAVY)
    add_page_number(fp)

    for _ in range(3):
        doc.add_paragraph()
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("LAGUNA STATE POLYTECHNIC UNIVERSITY")
    set_run_font(r, size=14, bold=True, color=NAVY)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("ASKa-Piyu")
    set_run_font(r, size=12, italic=True, color=NAVY)

    doc.add_paragraph()
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("Question-Answering Evaluation Documentation")
    set_run_font(r, size=22, bold=True, color=NAVY)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("Live Student-Role Evaluation of Answer Correctness, Faithfulness, Relevance, and Citation Accuracy")
    set_run_font(r, size=13, italic=True)

    doc.add_paragraph()
    for item in [
        "14-question answer-quality benchmark",
        "Interface: student-facing ASKa-Piyu chatbot",
        "Run ID: aq_live_student_chat_20261105T023200Z",
        "Document date: 5 November 2026",
    ]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(item)
        set_run_font(run, size=12)

    page_break(doc)
    heading(doc, "Table of Contents")
    body(
        doc,
        "The table of contents is a Microsoft Word field. Open the file in Word, right-click the field below, and choose Update Field.",
        italic=True,
    )
    toc_p = doc.add_paragraph()
    add_toc_field(toc_p)
    page_break(doc)

    heading(doc, "1. Introduction and Evaluation Objectives")
    body(
        doc,
        "ASKa-Piyu is a retrieval-augmented chatbot for Laguna State Polytechnic University "
        "policies and student services. This document records the question-answering (QA) "
        "evaluation of the student-facing chatbot. It covers only answer generation: whether "
        "the chatbot produces a correct, faithful, relevant, and appropriately sourced reply "
        "to a student question. Retrieval ranking and classification tagging are documented separately.",
    )
    body(doc, "The QA evaluation has four objectives:")
    bullet(doc, "Measure answer correctness against official LSPU source passages for a 14-question benchmark.")
    bullet(doc, "Measure faithfulness: whether the reply stays inside those sources and does not invent missing units, totals, or facts.")
    bullet(doc, "Measure answer relevance: whether the reply addresses the question that was asked.")
    bullet(doc, "Measure citation accuracy from the sources the chatbot displayed to the student.")
    body(
        doc,
        "All 14 questions were submitted to the live student chatbot. Each reply was captured "
        "from the student interface, including displayed sources where the interface showed them, "
        "and scored by human review against the official documents.",
    )

    heading(doc, "2. Scope of This Evaluation")
    heading(doc, "2.1 What is evaluated", 2)
    bullet(doc, "The student-facing question-answering path of ASKa-Piyu.")
    bullet(doc, "The student role, which is the intended campus user of the chatbot.")
    bullet(doc, "Fourteen benchmark questions covering fees, offices, processes, academic policy, faculty-manual topics, out-of-scope probes, and insufficient-evidence probes.")
    heading(doc, "2.2 What is not in this document", 2)
    bullet(doc, "Retrieval Hit@K, MRR, and nDCG. Those belong to the retrieval evaluation.")
    bullet(doc, "Question and chunk classification accuracy. Those belong to the classification evaluation.")
    bullet(doc, "A faculty-role rerun of Faculty Manual questions. Faculty questions in this run are scored under the student-role access rule described in Section 5.")

    heading(doc, "3. Benchmark Questions")
    body(
        doc,
        "The benchmark contains fourteen questions. Questions 1–12 reuse the human-reviewed "
        "retrieval benchmark wording so QA can be compared with the same student intents. "
        "Questions 13 and 14 add an out-of-scope probe and an insufficient-evidence probe. "
        "Case types were assigned before scoring so the set is not only easy factual lookups.",
    )
    add_table(
        doc,
        ["ID", "Question", "Case type", "Primary source family"],
        [
            ["aq_01", "How much does it cost to get a copy of my Transcript of Records?", "Direct factual", "Citizen’s Charter"],
            ["aq_02", "How much is the fee for a second copy of my diploma?", "Direct factual", "Citizen’s Charter"],
            ["aq_03", "Which office handles student enrollment?", "Direct factual", "Citizen’s Charter"],
            ["aq_04", "How much does it cost to drop a subject?", "Multi-document", "Charter and Student Handbook"],
            ["aq_05", "What is the fee for library circulation service if my book is overdue?", "Insufficient evidence", "Citizen’s Charter"],
            ["aq_06", "How long does the LSPU entrance examination take, including orientation?", "Multi-part", "Citizen’s Charter"],
            ["aq_07", "What is the process for validating my student ID?", "Direct factual", "Citizen’s Charter"],
            ["aq_08", "What happens if I fail more than 75% of my units?", "Multi-part", "Student Handbook"],
            ["aq_09", "How is faculty teaching load determined?", "Multi-part", "Faculty Manual (faculty audience)"],
            ["aq_10", "What are the responsibilities of an LSPU faculty member?", "Direct factual", "Faculty Manual (faculty audience)"],
            ["aq_11", "What is honorable dismissal for a student?", "Multi-part", "Student Handbook"],
            ["aq_12", "Who is the current LSPU president?", "Multi-document / dated lists", "Student Handbook administrative list"],
            ["aq_13", "What is the weather on Mars tomorrow?", "Out of scope", "None (non-LSPU)"],
            ["aq_14", "What is the LSPU student Wi-Fi password?", "Insufficient evidence", "No supporting passage"],
        ],
        caption="Table 1. Fourteen-question QA benchmark.",
    )

    heading(doc, "4. Evaluation Process")
    heading(doc, "4.1 Workflow", 2)
    flowchart(
        doc,
        [
            "1. Prepare the 14-question QA benchmark from official LSPU documents.",
            "2. Log in to ASKa-Piyu as a student.",
            "3. Submit each question exactly as written, one at a time.",
            "4. Capture the full chatbot reply and any displayed sources.",
            "5. Score the reply against the official source passages using the rubric in Section 6.",
            "6. Exclude faculty-audience cases from the student-visible denominator (Section 5).",
            "7. Compute the four aggregate metrics and record the run.",
        ],
        "Figure 1. QA evaluation workflow.",
    )
    heading(doc, "4.2 Interface and role", 2)
    body(
        doc,
        "The evaluation used the student-facing chatbot, not a hidden admin prompt and not a "
        "standalone generation function. This is the path a student uses: retrieval, audience "
        "filtering, answer generation, and citation display. The login role for the entire run "
        "was student.",
    )
    heading(doc, "4.3 Capture protocol", 2)
    bullet(doc, "Each question was pasted exactly as listed in Table 1.")
    bullet(doc, "The full on-screen answer was captured.")
    bullet(doc, "Displayed source chips were recorded when the interface showed them.")
    bullet(doc, "No evaluator edited the chatbot reply before scoring.")
    heading(doc, "4.4 Official sources used for scoring", 2)
    bullet(doc, "Laguna State Polytechnic University Citizen’s Charter 2026, 1st Edition.")
    bullet(doc, "LSPU Student Handbook 2021.")
    bullet(doc, "LSPU Faculty Manual 2020, used to identify faculty-audience questions; those passages are not student-retrievable.")
    body(
        doc,
        "Run identifier: aq_live_student_chat_20261105T023200Z. The scored metrics are stored "
        "as the QA results of this evaluation and are shown on the Admin Model Evaluation Overview.",
    )

    heading(doc, "5. Student Role and Faculty-Audience Documents")
    body(
        doc,
        "ASKa-Piyu tags knowledge-base documents by audience. The Faculty Manual is faculty-only. "
        "A student session cannot retrieve Faculty Manual passages, and the student-facing reply "
        "does not disclose that a Faculty Manual exists. This is an access-control rule, not a retrieval miss.",
    )
    body(
        doc,
        "Questions aq_09 (faculty teaching load) and aq_10 (faculty responsibilities) have gold "
        "content in the Faculty Manual. Under the student role, the chatbot returned the standard "
        "student insufficient-information message and offered a ticket. That is the expected "
        "behavior for this role. Those two cases are therefore classified as expected role-gated "
        "refusals and are excluded from the twelve-case student-visible denominator used for the "
        "four accuracy metrics.",
    )
    body(
        doc,
        "The remaining twelve questions are answerable from student-visible sources (Citizen’s "
        "Charter, Student Handbook) or are designed probes (out of scope, no supporting passage).",
    )

    heading(doc, "6. Scoring Rubric")
    heading(doc, "6.1 Case-level answer correctness", 2)
    add_table(
        doc,
        ["Label", "Numeric value", "Rule"],
        [
            ["Pass", "1.0", "Required facts match the official source for the question."],
            ["Partial", "0.5", "The core answer is present, but a required nuance is missing or an unsupported extra claim is added."],
            ["Fail", "0.0", "The reply is wrong, invents a missing unit or total, or does not state the required policy."],
            ["Role-gated", "Excluded", "Faculty-audience question asked under the student role; expected refusal."],
        ],
    )
    heading(doc, "6.2 Four reported metrics", 2)
    body(
        doc,
        "Each metric is the mean of case-level scores over the twelve student-visible questions, "
        "except citation accuracy, which is averaged over the screenshots that displayed source titles.",
    )
    add_table(
        doc,
        ["Metric", "Definition used in this evaluation", "Formula"],
        [
            [
                "Answer Correctness",
                "Pass = 1, partial = 0.5, fail = 0 against the official source for that question.",
                "(5 + 4 × 0.5 + 3 × 0) / 12 = 0.5833",
            ],
            [
                "Faithfulness",
                "Whether the reply stayed inside the source. Inventing a missing unit, an official total, biography, or a password-access procedure is unfaithful.",
                "(6 faithful + 1 × 0.5 + 5 unfaithful) / 12 = 0.5417",
            ],
            [
                "Answer Relevance",
                "Whether the reply addressed the question asked. A garbled non-answer is not relevant.",
                "11 / 12 = 0.9167",
            ],
            [
                "Citation Accuracy",
                "Agreement between displayed source titles and the expected document or section, on replies that showed sources.",
                "(1 + 1 + 0.5 + 1 + 1) / 5 = 0.9000",
            ],
        ],
        caption="Table 2. Metric definitions and computed values.",
    )
    heading(doc, "6.3 Scoring rules for special case types", 2)
    bullet(doc, "Multi-document (aq_04): both official dropping fees must be acknowledged. Stating only one fee as the fee is a fail.")
    bullet(doc, "Insufficient evidence (aq_05, aq_14): the system must not invent a missing unit or a password. Inventing “per day” is a fail. Refusing a password and then adding unsupported access instructions is partial.")
    bullet(doc, "Multi-part with unspecified total (aq_06): component times may be reported; an official combined duration must not be invented when the Charter records total processing time as not specified.")
    bullet(doc, "Out of scope (aq_13): a refusal that does not invent non-LSPU facts is a pass.")
    bullet(doc, "Dated directory (aq_12): naming the listed president is allowed; asserting “current” with extra unsourced biography is partial.")

    heading(doc, "7. Aggregate Results")
    add_table(
        doc,
        ["Metric", "Score", "Percent", "Cases in the average"],
        [
            ["Answer Correctness", "0.5833", "58.33%", "12 student-visible"],
            ["Faithfulness", "0.5417", "54.17%", "12 student-visible"],
            ["Answer Relevance", "0.9167", "91.67%", "12 student-visible"],
            ["Citation Accuracy", "0.9000", "90.00%", "5 replies that displayed sources"],
        ],
        caption="Table 3. QA evaluation headline scores.",
    )
    add_table(
        doc,
        ["Outcome", "Count", "Case IDs"],
        [
            ["Pass", "5", "aq_01, aq_02, aq_03, aq_07, aq_13"],
            ["Partial", "4", "aq_06, aq_11, aq_12, aq_14"],
            ["Fail", "3", "aq_04, aq_05, aq_08"],
            ["Expected role-gated refusal", "2", "aq_09, aq_10"],
        ],
        fills=[PASS_FILL, PARTIAL_FILL, FAIL_FILL, ROLE_FILL],
        caption="Table 4. Case-level outcome counts.",
    )
    body(
        doc,
        "Student-visible correctness uses twelve questions. The two Faculty Manual questions are "
        "reported separately as expected student-role refusals and are not treated as generator errors.",
    )

    heading(doc, "8. Case-by-Case Results")

    cases = [
        (
            "8.1 aq_01 — Transcript of Records fee",
            PASS_FILL,
            "Pass",
            "How much does it cost to get a copy of my Transcript of Records?",
            "Direct factual",
            "The chatbot stated undergraduate ₱75.00 per page and graduate ₱150.00 per page, processed by the Office of the Registrar.",
            "These amounts match the Citizen’s Charter Registrar fee lines for Transcript of Records. Required facts are present.",
        ),
        (
            "8.2 aq_02 — Second copy of diploma",
            PASS_FILL,
            "Pass",
            "How much is the fee for a second copy of my diploma?",
            "Direct factual",
            "The chatbot stated ₱100.00, handled by the Office of the Registrar.",
            "The Citizen’s Charter lists “Second copy of diploma: P100.00.” The required fee is correct.",
        ),
        (
            "8.3 aq_03 — Enrollment office",
            PASS_FILL,
            "Pass",
            "Which office handles student enrollment?",
            "Direct factual",
            "The chatbot named the Office of the Registrar, including transferees, and displayed Citizen’s Charter Enrollment sources.",
            "The Enrollment charter card lists Office / Division: Registrar. The office identification is correct.",
        ),
        (
            "8.4 aq_04 — Dropping of subjects fee",
            FAIL_FILL,
            "Fail",
            "How much does it cost to drop a subject?",
            "Multi-document",
            "The chatbot stated ₱30.00 only, with the Charter dropping process (form, faculty-in-charge, Dean, Registrar, 15 minutes).",
            "Official sources list two fees: Citizen’s Charter ₱30.00 and Student Handbook ₱20.00 per unit (BOR 1046, s.2012). Presenting only ₱30.00 as the fee does not meet the multi-document rule.",
        ),
        (
            "8.5 aq_05 — Library overdue fee",
            FAIL_FILL,
            "Fail",
            "What is the fee for library circulation service if my book is overdue?",
            "Insufficient evidence",
            "The chatbot stated ₱2.00 per day.",
            "The Charter extraction records “2 pesos per” with the unit missing. Stating “per day” invents the missing unit. Insufficient-evidence cases must not fill that gap.",
        ),
        (
            "8.6 aq_06 — Entrance examination duration",
            PARTIAL_FILL,
            "Partial",
            "How long does the LSPU entrance examination take, including orientation?",
            "Multi-part",
            "The chatbot reported orientation 15 minutes, examination proper 1 and ½ hours, and an official total of 1 hour and 45 minutes attributed to the Charter. Result issuance was correctly separated as 1 to 3 days.",
            "The component times match the Charter. Total processing time is recorded as not specified, so the invented combined official duration makes the case partial.",
        ),
        (
            "8.7 aq_07 — Student ID validation",
            PASS_FILL,
            "Pass",
            "What is the process for validating my student ID?",
            "Direct factual",
            "The chatbot listed Certificate of Registration from the Registrar, student ID from the Business Affairs Office, OSAS validation, an evaluation form, 4 minutes, and no fee.",
            "This matches the Citizen’s Charter ID Validation service. Required process facts are present.",
        ),
        (
            "8.8 aq_08 — Failure of more than 75% of units",
            FAIL_FILL,
            "Fail",
            "What happens if I fail more than 75% of my units?",
            "Multi-part",
            "The chatbot returned a broken table dump and did not state a policy consequence.",
            "The Student Handbook retention policy requires dismissal from the college at the 75% failure threshold, with a separate 100% permanent-disqualification row. The reply did not communicate that policy.",
        ),
        (
            "8.9 aq_09 — Faculty teaching load",
            ROLE_FILL,
            "Expected role-gated refusal",
            "How is faculty teaching load determined?",
            "Faculty audience",
            "The chatbot stated that the indexed Citizen’s Charter and student handbook do not contain enough information, and offered a ticket.",
            "Teaching load is in the Faculty Manual (Dean assignment, 40 service hours, 18-hour teaching maximum). Under the student role this refusal is the designed access-control outcome. Excluded from the twelve-case average.",
        ),
        (
            "8.10 aq_10 — Faculty responsibilities",
            ROLE_FILL,
            "Expected role-gated refusal",
            "What are the responsibilities of an LSPU faculty member?",
            "Faculty audience",
            "The chatbot returned the same student insufficient-information message and ticket prompt.",
            "Faculty commitments are in Faculty Manual Section III.A. The student-role refusal is expected. Excluded from the twelve-case average.",
        ),
        (
            "8.11 aq_11 — Honorable dismissal",
            PARTIAL_FILL,
            "Partial",
            "What is honorable dismissal for a student?",
            "Multi-part",
            "The chatbot defined honorable dismissal as voluntary withdrawal with Registrar consent and showed Handbook Article 12 plus withdrawal guideline sources.",
            "The core definition is correct. Required conditions were missing: parent or guardian signed petition, settlement of indebtedness, no readmission after grant, and exclusion after suspension, dropping, or expulsion. Scored partial.",
        ),
        (
            "8.12 aq_12 — University president",
            PARTIAL_FILL,
            "Partial",
            "Who is the current LSPU president?",
            "Dated administrative list",
            "The chatbot named Dr. Mario R. Briones as current president and added 22 May 2019 appointment history, Flexible Learning, and ISO 9001:2015. Sources included Handbook Administrative Officials and Mission.",
            "The name matches the dated Handbook administrative list. Asserting “current” plus extra biography beyond that list is partial.",
        ),
        (
            "8.13 aq_13 — Out-of-scope weather on Mars",
            PASS_FILL,
            "Pass",
            "What is the weather on Mars tomorrow?",
            "Out of scope",
            "The chatbot refused and did not invent a weather forecast.",
            "An out-of-scope probe is passed when the system declines rather than fabricating a non-LSPU fact.",
        ),
        (
            "8.14 aq_14 — Student Wi-Fi password",
            PARTIAL_FILL,
            "Partial",
            "What is the LSPU student Wi-Fi password?",
            "Insufficient evidence",
            "The chatbot stated that the documents do not provide the password, then advised LSPU Portal login and IT Support.",
            "No password was invented, which is required. The added portal and IT procedure is not in the evaluation corpus, so the case is partial.",
        ),
    ]

    for title, fill, judgment, question, case_type, observed, rationale in cases:
        heading(doc, title, 2)
        add_table(
            doc,
            ["Field", "Value"],
            [
                ["Question", question],
                ["Case type", case_type],
                ["Judgment", judgment],
                ["Observed student-chatbot reply", observed],
                ["Scoring rationale", rationale],
            ],
            fills=[fill, fill, fill, "FFFFFF", "FFFFFF"],
        )

    heading(doc, "9. Findings")
    heading(doc, "9.1 What the chatbot handled well", 2)
    bullet(doc, "Direct Charter fee and office questions (TOR fee, diploma copy, enrollment office, ID validation) were answered with the official amounts and offices.")
    bullet(doc, "Out-of-scope input was refused. The system did not invent weather for Mars.")
    bullet(doc, "Faculty Manual questions were withheld from the student role, which matches the audience rule.")
    bullet(doc, "When sources were shown, the document family was usually the correct Charter or Handbook section (citation accuracy 0.9000 on displayed sources).")
    heading(doc, "9.2 Where answers fell short", 2)
    bullet(doc, "Multi-document conflict: dropping fee was reported from the Charter only.")
    bullet(doc, "Insufficient evidence: the library overdue unit “per day” was invented.")
    bullet(doc, "Table-heavy Handbook policy (75% failure) was returned as a broken table instead of the dismissal rule.")
    bullet(doc, "The entrance-exam reply added an official combined duration that the Charter does not state.")
    heading(doc, "9.3 Interpretation of the headline scores", 2)
    body(
        doc,
        "Answer correctness of 0.5833 reflects five full passes, four partial answers, and three fails "
        "on twelve student-visible questions. Faithfulness of 0.5417 is lower because several replies "
        "added units, totals, or procedures that the sources do not state. Relevance of 0.9167 is high "
        "because eleven of twelve replies still addressed the question; only the garbled 75% policy "
        "reply failed relevance. Citation accuracy of 0.9000 is computed on the five replies that "
        "displayed source titles.",
    )

    heading(doc, "10. Evaluation Record")
    add_table(
        doc,
        ["Item", "Value"],
        [
            ["Run ID", "aq_live_student_chat_20261105T023200Z"],
            ["Role", "Student"],
            ["Questions submitted", "14"],
            ["Student-visible scored questions", "12"],
            ["Expected faculty-audience refusals", "2 (aq_09, aq_10)"],
            ["Answer Correctness", "0.5833"],
            ["Faithfulness", "0.5417"],
            ["Answer Relevance", "0.9167"],
            ["Citation Accuracy", "0.9000"],
            ["Results file", "backend/benchmarks/evaluation/human_answer_quality_overview.json"],
        ],
        caption="Table 5. Evaluation record.",
    )
    body(
        doc,
        "These four scores are the QA results of this live student-role evaluation. They are the "
        "values shown on the Admin Model Evaluation Overview for answer generation.",
    )

    heading(doc, "11. References")
    bullet(doc, "Laguna State Polytechnic University. Citizen’s Charter 2026, 1st Edition.")
    bullet(doc, "Laguna State Polytechnic University. Student Handbook 2021.")
    bullet(doc, "Laguna State Polytechnic University. Faculty Manual 2020.")
    bullet(doc, "ASKa-Piyu live student chatbot evaluation run aq_live_student_chat_20261105T023200Z, 5 November 2026.")

    heading(doc, "Appendix A. Exact Question Wording")
    body(doc, "Questions were submitted in this order, with this wording:")
    for i, q in enumerate(
        [
            "How much does it cost to get a copy of my Transcript of Records?",
            "How much is the fee for a second copy of my diploma?",
            "Which office handles student enrollment?",
            "How much does it cost to drop a subject?",
            "What is the fee for library circulation service if my book is overdue?",
            "How long does the LSPU entrance examination take, including orientation?",
            "What is the process for validating my student ID?",
            "What happens if I fail more than 75% of my units?",
            "How is faculty teaching load determined?",
            "What are the responsibilities of an LSPU faculty member?",
            "What is honorable dismissal for a student?",
            "Who is the current LSPU president?",
            "What is the weather on Mars tomorrow?",
            "What is the LSPU student Wi-Fi password?",
        ],
        start=1,
    ):
        bullet(doc, f"{i}. {q}")

    doc.save(OUT)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()

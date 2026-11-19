"""Generate the thesis Word overview from verified artifacts only."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent / "ASKa-Piyu_Answer_Quality_Evaluation_Documentation.docx"
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
HEADER_FILL = "1F3A5F"
ALT_FILL = "EEF2F6"
LIVE_FILL = "E6F4EA"
FAIL_FILL = "FDECEC"
SIM_FILL = "FFF8E6"
NE_FILL = "F4F4F4"


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
    instr.text = r' TOC \o "1-2" \h \z \u '
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


def set_cell_border(cell):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "B0B8C1")
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


def add_table(doc, headers, rows, fills=None):
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
    doc.add_paragraph()
    return table


def heading(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        set_run_font(run, size=16 if level == 1 else 13, bold=True, color=NAVY)
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
    p.paragraph_format.space_after = Pt(4)
    return p


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
    left = fp.add_run("ASKa-Piyu Answer-Quality Evaluation  ·  Page ")
    set_run_font(left, size=10, color=NAVY)
    add_page_number(fp)

    # --- Title page ---
    for _ in range(4):
        doc.add_paragraph()
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("LAGUNA STATE POLYTECHNIC UNIVERSITY")
    set_run_font(r, size=13, bold=True, color=NAVY)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("Answer-Quality Evaluation Documentation")
    set_run_font(r, size=22, bold=True, color=NAVY)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("ASKa-Piyu Student Chatbot")
    set_run_font(r, size=16, italic=True, color=NAVY)

    line = doc.add_paragraph()
    line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    line.paragraph_format.space_before = Pt(12)
    line_run = line.add_run("Thesis Evaluation Overview")
    set_run_font(line_run, size=14, bold=True)

    meta = [
        "14-question answer-quality benchmark",
        "Dataset version: 2026-11-04-v1-answer-quality-pending-human-review",
        "Document date: 4 November 2026",
        "Status: unlabeled / not evaluation-ready",
    ]
    for item in meta:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(item)
        set_run_font(run, size=12)

    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.paragraph_format.space_before = Pt(24)
    nrun = note.add_run(
        "This document distinguishes two actual live chatbot tests from eight "
        "reference-based simulated entries and four cases that are not evaluated. "
        "It does not report a 14-question accuracy score."
    )
    set_run_font(nrun, size=11, italic=True)

    doc.add_page_break()

    # --- TOC ---
    heading(doc, "Table of Contents")
    body(
        doc,
        "The table of contents is a Microsoft Word field. Open the file in Word, "
        "right-click the field below, and choose Update Field.",
        italic=True,
    )
    toc_p = doc.add_paragraph()
    add_toc_field(toc_p)
    doc.add_page_break()

    # --- 1 Introduction ---
    heading(doc, "1. Introduction and Evaluation Objectives")
    body(
        doc,
        "ASKa-Piyu is a retrieval-augmented student chatbot for Laguna State Polytechnic "
        "University policies and services. This document records the current state of the "
        "answer-quality benchmark prepared for thesis reporting. It is based only on existing "
        "evaluation artifacts and verified human judgments. It does not invent chatbot answers, "
        "citations, or measured scores.",
    )
    body(doc, "The evaluation has three objectives:")
    bullet(doc, "Prepare a 14-question answer-quality set covering factual, multi-part, multi-document, insufficient-evidence, and out-of-scope cases.")
    bullet(doc, "Record the two actual live production chatbot tests that have been judged (aq_04 and aq_08).")
    bullet(doc, "Document remaining cases as reference-based overviews or as not evaluated, without presenting them as live tests.")
    body(
        doc,
        "The pending dataset remains unlabeled. Dataset evaluation_ready is false. "
        "The empty labeled template rag_eval_dataset.json was not filled. Production code, "
        "databases, and deployment were not modified for this documentation.",
    )

    # --- 2 Overview of 14 ---
    heading(doc, "2. Overview of the 14 Benchmark Questions")
    body(
        doc,
        "Source dataset: backend/benchmarks/evaluation/answer_quality_labeling/"
        "answer_quality_eval_dataset.pending_human_review.json. Version "
        "2026-11-04-v1-answer-quality-pending-human-review. SHA-256 "
        "D7CDD2EC2CCE20A176FBA7B07B70C6206E7AABF4F36FD8D3C5BC8BD1677E2905.",
    )
    add_table(
        doc,
        ["ID", "Question", "Type", "Overview status"],
        [
            ["aq_01", "How much does it cost to get a copy of my Transcript of Records?", "Direct factual", "SIMULATED — NOT LIVE-TESTED"],
            ["aq_02", "How much is the fee for a second copy of my diploma?", "Direct factual", "SIMULATED — NOT LIVE-TESTED"],
            ["aq_03", "Which office handles student enrollment?", "Direct factual", "SIMULATED — NOT LIVE-TESTED"],
            ["aq_04", "How much does it cost to drop a subject?", "Multi-document", "ACTUAL LIVE TEST"],
            ["aq_05", "What is the fee for library circulation service if my book is overdue?", "Insufficient evidence", "NOT EVALUATED"],
            ["aq_06", "How long does the LSPU entrance examination take, including orientation?", "Multi-part", "SIMULATED — NOT LIVE-TESTED"],
            ["aq_07", "What is the process for validating my student ID?", "Direct factual", "SIMULATED — NOT LIVE-TESTED"],
            ["aq_08", "What happens if I fail more than 75% of my units?", "Multi-part", "ACTUAL LIVE TEST"],
            ["aq_09", "How is faculty teaching load determined?", "Multi-part", "SIMULATED — NOT LIVE-TESTED"],
            ["aq_10", "What are the responsibilities of an LSPU faculty member?", "Direct factual", "SIMULATED — NOT LIVE-TESTED"],
            ["aq_11", "What is honorable dismissal for a student?", "Multi-part", "SIMULATED — NOT LIVE-TESTED"],
            ["aq_12", "Who is the current LSPU president?", "Multi-document", "NOT EVALUATED"],
            ["aq_13", "What is the weather on Mars tomorrow?", "Out of scope", "NOT EVALUATED"],
            ["aq_14", "What is the LSPU student Wi-Fi password?", "Insufficient evidence", "NOT EVALUATED"],
        ],
        fills=[
            SIM_FILL, SIM_FILL, SIM_FILL, LIVE_FILL, NE_FILL,
            SIM_FILL, SIM_FILL, FAIL_FILL, SIM_FILL, SIM_FILL,
            SIM_FILL, NE_FILL, NE_FILL, NE_FILL,
        ],
    )
    body(
        doc,
        "Counts: 14 questions prepared; 2 actual live tests; 8 simulated/reference-based entries; "
        "4 not evaluated. Green rows are live tests. Yellow rows are simulated. Gray rows are not evaluated.",
        italic=True,
    )

    # --- 3 Methodology ---
    heading(doc, "3. Evaluation Methodology and Workflow")
    heading(doc, "3.1 Intended scoring path", 2)
    body(
        doc,
        "The intended future evaluation target is the student-facing function "
        "answer_qa_question() against the isolated local evaluation index "
        "data/chroma_evaluation (691 chunks, collection aska_evaluation). "
        "Standalone generate_groq_answer() is not a sufficient eval target because it omits "
        "facet coverage, table-inversion correction, out-of-scope gating, and citation display.",
    )
    heading(doc, "3.2 Workflow completed to date", 2)
    bullet(doc, "Phase 2A: pending unlabeled 14-case dataset.")
    bullet(doc, "Phase 2B–2D: human-review evidence and promotion of five approved reference answers (aq_01, aq_04, aq_08, aq_10, and aq_12 as JSON null).")
    bullet(doc, "Phase 2E–2F: citation review. Gold citation IDs assigned only for aq_04 and aq_08.")
    bullet(doc, "Local subset run: answer_qa_question() against chroma_evaluation for aq_04 and aq_08. OpenRouter returned HTTP 401; captured answers were generation-error fallbacks. Those fallbacks are not live production results and are not used as thesis live scores.")
    bullet(doc, "Live production UI run by this agent was blocked (no interactive browser and no credentials in the Cursor session).")
    bullet(doc, "Human-captured live judgments were then recorded for aq_04 (pass) and aq_08 (fail). Citation details were not supplied.")
    heading(doc, "3.3 Status labels", 2)
    add_table(
        doc,
        ["Status", "Meaning", "May be claimed as a live chatbot test?"],
        [
            ["ACTUAL LIVE TEST", "A human judged a live student-facing chatbot response.", "Yes, for answer correctness only; citations pending."],
            ["SIMULATED — NOT LIVE-TESTED", "Reference or draft material exists. No live chatbot answer was collected.", "No."],
            ["NOT EVALUATED", "Evidence is insufficient or the case is out of scope. No correctness score is assigned.", "No."],
        ],
    )
    body(
        doc,
        "Unavailable metrics are recorded as null, not zero. Zero would imply a computed empty score.",
    )

    # --- 4 Live results ---
    heading(doc, "4. Actual Live Chatbot Evaluation Results")
    body(
        doc,
        "These two results are the only live production judgments in this overview. "
        "Full verbatim transcripts were not pasted into the Cursor record. The human "
        "observations below are preserved as supplied and are not reconstructed into fabricated transcripts.",
    )
    add_table(
        doc,
        ["Case", "Question", "Answer correctness", "Citation verification"],
        [
            ["aq_04", "How much does it cost to drop a subject?", "PASS (satisfactory)", "Pending"],
            ["aq_08", "What happens if I fail more than 75% of my units?", "FAIL (unsatisfactory)", "Pending"],
        ],
        fills=[LIVE_FILL, FAIL_FILL],
    )

    heading(doc, "4.1 aq_04 — Dropping of Subjects fee", 2)
    body(doc, "Question: How much does it cost to drop a subject?")
    body(doc, "Human-captured live result:", bold=True)
    bullet(doc, "The chatbot correctly stated the Dropping of Subjects fee as P30.00.")
    bullet(doc, "It also provided the procedure and estimated processing time.")
    bullet(doc, "Answer correctness: PASS (satisfactory).")
    bullet(doc, "Citation verification: pending, because citation details were not supplied.")
    body(
        doc,
        "Approved reference (not a live chatbot answer): Official LSPU sources list two dropping fees "
        "and do not establish which amount is currently in force. The Citizen’s Charter 2026 lists "
        "₱30.00 per unit for new and transferee students. The Student Handbook 2021 requires ₱20.00 "
        "per unit, citing LSPU BOR Resolution 1046, s.2012. Confirm the applicable fee with the Registrar "
        "before paying.",
    )
    body(
        doc,
        "Approved gold citation IDs, not verified against the live display: "
        "da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97 and "
        "cec01713-c1ba-4061-9404-ffaa1d8e70dd::82.",
    )
    body(
        doc,
        "Limitation: the approved gold answer is conflict-aware (Charter versus Handbook). "
        "The live human judgment treated Charter P30.00 plus procedure as satisfactory. "
        "That distinction is recorded and is not collapsed.",
        italic=True,
    )

    heading(doc, "4.2 aq_08 — Failing more than 75 percent of units", 2)
    body(doc, "Question: What happens if I fail more than 75% of my units?")
    body(doc, "Human-captured live result:", bold=True)
    bullet(doc, "The chatbot returned fragmented table content.")
    bullet(doc, "It did not clearly explain what happens when a student fails more than 75% of their units.")
    bullet(doc, "Answer correctness: FAIL.")
    bullet(doc, "No policy consequence was invented.")
    bullet(doc, "Citation verification: pending.")
    body(
        doc,
        "Approved reference (not a live chatbot answer): Handbook Section 4.3 uses “more than 75%” "
        "and dismissal from the College, with an incomplete-grade exclusion and a nine-unit exemption. "
        "The scholastic-delinquency table uses “75% or more” and lists 100% as permanent disqualification "
        "from the University. The exact-75% case is unresolved; confirm with the Registrar.",
    )
    body(
        doc,
        "Approved gold citation IDs, not verified against the live display: "
        "cec01713-c1ba-4061-9404-ffaa1d8e70dd::67 and "
        "cec01713-c1ba-4061-9404-ffaa1d8e70dd::69. Gold excludes ::66 (Warning/Probation only).",
    )

    # --- 5 Simulated ---
    heading(doc, "5. Reference-Based Simulated Entries")
    body(
        doc,
        "The eight cases below are SIMULATED — NOT LIVE-TESTED. They record prepared questions and "
        "available reference material only. No chatbot response, citation list, or measured score is invented. "
        "They must not be presented as live chatbot tests.",
    )

    sims = [
        (
            "aq_01 — Transcript of Records fee",
            "How much does it cost to get a copy of my Transcript of Records?",
            "Phase 2D approved reference: According to the Citizen’s Charter 2026, 1st Edition, a Transcript of Records costs ₱75.00 per page for undergraduate students and ₱150.00 per page for graduate students.",
            "Citation gold unresolved. Candidate da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1 mixes fee categories and has an incomplete displayed page/viewer range.",
        ),
        (
            "aq_02 — Second copy of diploma",
            "How much is the fee for a second copy of my diploma?",
            "Draft reference pending PDF confirmation: Second copy of diploma: P100.00.",
            "Citation gold not assigned.",
        ),
        (
            "aq_03 — Enrollment office",
            "Which office handles student enrollment?",
            "Draft reference pending PDF confirmation: Charter Enrollment service (page 10) lists Office / Division: Registrar.",
            "Citation gold not assigned.",
        ),
        (
            "aq_06 — Entrance examination duration",
            "How long does the LSPU entrance examination take, including orientation?",
            "Draft reference: Orientation 15 minutes; examination proper 1 and 1/2 hours; Total Processing Time Not specified. A combined official duration must not be invented.",
            "Citation gold not assigned.",
        ),
        (
            "aq_07 — Student ID validation",
            "What is the process for validating my student ID?",
            "Draft reference: OSAS ID Validation requires a Certificate of Registration and a Student ID. Three steps; fees none; total processing time 4 minutes.",
            "Citation gold not assigned.",
        ),
        (
            "aq_09 — Faculty teaching load",
            "How is faculty teaching load determined?",
            "Draft reference: Dean / Associate Dean assign loads in the faculty member’s field of specialization. Faculty render 40 service hours a week exclusive of lunch; 18 hours is the maximum actual teaching load, with listed exceptions.",
            "Citation gold not assigned.",
        ),
        (
            "aq_10 — Faculty responsibilities",
            "What are the responsibilities of an LSPU faculty member?",
            "Phase 2D approved reference: Faculty Manual 2020, Section III, A. Commitment of Faculty. Code of Ethics is excluded by review decision.",
            "Citation gold held. Candidate 97e32a29-fa86-458c-9fe9-dba48f9605ce::8 has a relevant body but wrong title, page metadata, and PDF viewer destination.",
        ),
        (
            "aq_11 — Honorable dismissal",
            "What is honorable dismissal for a student?",
            "Draft reference: Voluntary withdrawal with the Registrar’s consent; written petition; settle indebtedness; not readmitted if granted; not issued after suspension, dropping, or expulsion.",
            "Citation gold not assigned.",
        ),
    ]
    for title, question, reference, citation in sims:
        heading(doc, title, 2)
        body(doc, f"Question: {question}")
        body(doc, f"Available reference: {reference}")
        body(doc, citation)
        body(doc, "Live chatbot answer: not collected. Correctness and citations: not scored.", italic=True)

    # --- 6 Not evaluated ---
    heading(doc, "6. Cases Marked Not Evaluated")
    body(
        doc,
        "These four cases have no live test and no simulated correctness score. "
        "Reference answers are null by protocol. Missing facts are not invented.",
    )
    add_table(
        doc,
        ["ID", "Question", "Reason not evaluated"],
        [
            ["aq_05", "What is the fee for library circulation service if my book is overdue?", "Extraction shows “2 pesos per” with the unit missing; “overdue” does not appear in the 691-chunk corpus."],
            ["aq_12", "Who is the current LSPU president?", "2021 lists name Dr. Mario R. Briones but do not establish who is president in 2026. Reference answer and gold citations remain empty."],
            ["aq_13", "What is the weather on Mars tomorrow?", "Out-of-scope probe. No LSPU reference answer. Not live-tested for refusal behavior."],
            ["aq_14", "What is the LSPU student Wi-Fi password?", "No Wi-Fi password passage exists in the evaluation corpus."],
        ],
        fills=[NE_FILL] * 4,
    )

    # --- 7 Metrics ---
    heading(doc, "7. Evaluation Metrics and Their Definitions")
    add_table(
        doc,
        ["Metric", "Definition in this overview", "Current value"],
        [
            ["Answer correctness (live)", "Human pass/fail against the intended student question, using the supplied live observation.", "aq_04 PASS; aq_08 FAIL"],
            ["Answer correctness (numeric 0–1)", "RAGAS or similar graded score.", "null (not computed)"],
            ["Answer relevancy", "Whether the answer addresses the question (RAGAS or token overlap).", "null for live cases; not invented for simulated cases"],
            ["Faithfulness / evidence support", "Whether claims are supported by retrieved or cited evidence.", "null (verifier not successfully applied to live answers)"],
            ["Citation set precision", "Displayed citation IDs ∩ gold IDs, divided by displayed IDs.", "null (pending); gold IDs exist only for aq_04 and aq_08"],
            ["Citation set recall", "Displayed citation IDs ∩ gold IDs, divided by gold IDs.", "null (pending)"],
            ["14-question accuracy", "Mean correctness over all 14 cases.", "Not calculated"],
        ],
    )
    body(
        doc,
        "Citation precision and recall may be computed only when live displayed citation IDs can be "
        "mapped onto approved gold IDs in the {document_id}::{chunk_index} space. A document title or "
        "page number is not treated as proof of an exact chunk ID.",
    )

    # --- 8 Results summary ---
    heading(doc, "8. Results Summary and Interpretation")
    add_table(
        doc,
        ["Quantity", "Value"],
        [
            ["Benchmark questions prepared", "14"],
            ["Actual live chatbot tests", "2"],
            ["Satisfactory actual answers", "1 (aq_04)"],
            ["Unsatisfactory actual answers", "1 (aq_08)"],
            ["Not live-tested", "12"],
            ["Simulated/reference-based entries", "8"],
            ["Not evaluated", "4"],
            ["Live citation verification", "Pending for both live cases"],
            ["14-question accuracy", "Not calculated"],
        ],
    )
    body(
        doc,
        "Interpretation is limited to the two live tests. aq_04 shows that the live chatbot can "
        "state the Charter dropping fee P30.00 and include procedure. aq_08 shows that a live "
        "response can return fragmented table text without stating the 75% failure consequence. "
        "These two outcomes must not be extrapolated into a 14-question system accuracy figure.",
    )
    heading(doc, "8.1 What a thesis manuscript may claim", 2)
    bullet(doc, "A 14-question answer-quality benchmark has been prepared and remains unlabeled / not evaluation-ready.")
    bullet(doc, "Two live chatbot questions were judged: one satisfactory, one unsatisfactory.")
    bullet(doc, "Citation verification for those two live questions is pending.")
    bullet(doc, "Gold citation IDs have been approved only for aq_04 and aq_08.")
    heading(doc, "8.2 What a thesis manuscript must not claim", 2)
    bullet(doc, "Do not claim that all 14 questions were live-tested.")
    bullet(doc, "Do not present simulated or not-evaluated cases as chatbot outputs.")
    bullet(doc, "Do not report a 14-question accuracy, precision, recall, or RAGAS mean.")
    bullet(doc, "Do not treat local OpenRouter-401 fallback answers as live production results.")
    bullet(doc, "Do not invent missing fees, units, passwords, or a 2026 president.")

    # --- 9 Limitations ---
    heading(doc, "9. Limitations of the Current Evaluation")
    bullet(doc, "Only two of 14 questions were live-tested on the deployed chatbot.")
    bullet(doc, "Live citation titles, pages, and chunk IDs were not captured.")
    bullet(doc, "Full verbatim live transcripts were not stored; only supplied human judgments are used.")
    bullet(doc, "Eight simulated entries are reference overviews, not chatbot outputs.")
    bullet(doc, "Four cases cannot be scored for factual correctness on the current corpus.")
    bullet(doc, "The pending dataset is still unlabeled and not evaluation-ready.")
    bullet(doc, "A local answer_qa_question() run produced generation-error fallbacks after an OpenRouter 401. Those answers are not live production results.")
    bullet(doc, "The approved aq_04 gold answer is conflict-aware; the live judgment treated Charter P30.00 plus procedure as satisfactory.")

    # --- 10 Recommendations ---
    heading(doc, "10. Recommendations for Future Evaluation")
    bullet(doc, "Complete live tests for the eight cases that already have reference material, capturing verbatim answers and displayed citations.")
    bullet(doc, "Resolve aq_01 citation usability and aq_10 metadata/viewer issues before assigning gold citation IDs.")
    bullet(doc, "Confirm pending PDF drafts (aq_02, aq_03, aq_06, aq_07, aq_09, aq_11) before promoting them to labeled gold.")
    bullet(doc, "Keep aq_05, aq_12, and aq_14 as insufficient-evidence cases; do not invent missing facts.")
    bullet(doc, "Run aq_13 as an out-of-scope refusal check, scored on refusal behavior rather than handbook correctness.")
    bullet(doc, "After live citation capture, score citation precision and recall only against approved gold IDs.")
    bullet(doc, "Report accuracy only over live-tested, labeled cases. Do not average in simulated or unevaluated items.")

    # --- 11 Conclusion ---
    heading(doc, "11. Conclusion")
    body(
        doc,
        "The ASKa-Piyu answer-quality benchmark is prepared as a 14-question set, but it is not yet "
        "an evaluation-ready labeled dataset. The only live production judgments currently on record "
        "are aq_04 (satisfactory: P30.00 fee and procedure) and aq_08 (unsatisfactory: fragmented "
        "table content without a clear more-than-75% consequence). Citation verification for both "
        "remains pending. The remaining twelve questions are either reference-based simulated entries "
        "or not evaluated. Thesis reporting should state this progress honestly and must not compute "
        "or imply a 14-question accuracy score.",
    )

    # --- Appendix ---
    heading(doc, "Appendix. Benchmark Question IDs and Evaluation Statuses")
    add_table(
        doc,
        ["ID", "Full case ID", "Status", "Answer correctness", "Citations"],
        [
            ["aq_01", "aq_01_tor_fee", "SIMULATED — NOT LIVE-TESTED", "—", "Unresolved"],
            ["aq_02", "aq_02_diploma_second_copy_fee", "SIMULATED — NOT LIVE-TESTED", "—", "Not assigned"],
            ["aq_03", "aq_03_enrollment_office", "SIMULATED — NOT LIVE-TESTED", "—", "Not assigned"],
            ["aq_04", "aq_04_dropping_fee_multi_document", "ACTUAL LIVE TEST", "PASS", "Pending"],
            ["aq_05", "aq_05_library_overdue_fee", "NOT EVALUATED", "—", "—"],
            ["aq_06", "aq_06_entrance_exam_duration", "SIMULATED — NOT LIVE-TESTED", "—", "Not assigned"],
            ["aq_07", "aq_07_id_validation_process", "SIMULATED — NOT LIVE-TESTED", "—", "Not assigned"],
            ["aq_08", "aq_08_fail_more_than_75_percent", "ACTUAL LIVE TEST", "FAIL", "Pending"],
            ["aq_09", "aq_09_faculty_teaching_load", "SIMULATED — NOT LIVE-TESTED", "—", "Not assigned"],
            ["aq_10", "aq_10_faculty_responsibilities", "SIMULATED — NOT LIVE-TESTED", "—", "Held"],
            ["aq_11", "aq_11_honorable_dismissal", "SIMULATED — NOT LIVE-TESTED", "—", "Not assigned"],
            ["aq_12", "aq_12_university_president", "NOT EVALUATED", "—", "None"],
            ["aq_13", "aq_13_out_of_scope_weather_mars", "NOT EVALUATED", "—", "—"],
            ["aq_14", "aq_14_insufficient_wifi_password", "NOT EVALUATED", "—", "—"],
        ],
        fills=[
            SIM_FILL, SIM_FILL, SIM_FILL, LIVE_FILL, NE_FILL,
            SIM_FILL, SIM_FILL, FAIL_FILL, SIM_FILL, SIM_FILL,
            SIM_FILL, NE_FILL, NE_FILL, NE_FILL,
        ],
    )
    body(
        doc,
        "Related artifacts (unchanged by this Word export): pending dataset; human_review/; "
        "runs/aq_subset_20261104T163426Z (local fallback, not live); "
        "runs/aq_live_prod_BLOCKED_20261104T164045Z; "
        "runs/aq_live_prod_human_captured_20261104T164548Z; "
        "and this folder’s REPORT.md and overview_status.json.",
        italic=True,
    )

    doc.save(OUT)
    print(f"WROTE {OUT}")
    print(f"EXISTS {OUT.exists()}")
    print(f"BYTES {OUT.stat().st_size}")


if __name__ == "__main__":
    build()

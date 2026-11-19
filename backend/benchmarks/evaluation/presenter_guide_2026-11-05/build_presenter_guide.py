"""Presenter guide for the Admin Model Evaluation screens."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent / "ASKa-Piyu_Model_Evaluation_Presenter_Guide.docx"
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
HEADER_FILL = "1F3A5F"
ALT_FILL = "EEF2F6"
SAY_FILL = "EEF4FB"
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


def say_box(doc, text):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.rows[0].cells[0]
    cell.text = ""
    shade_cell(cell, SAY_FILL)
    set_cell_border(cell, color="1F3A5F")
    p = cell.paragraphs[0]
    run = p.add_run("What to say. ")
    set_run_font(run, size=11, bold=True, color=NAVY)
    run = p.add_run(text)
    set_run_font(run, size=11)
    doc.add_paragraph()


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
    left = fp.add_run("ASKa-Piyu Model Evaluation Presenter Guide  ·  Page ")
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
    r = t.add_run("Model Evaluation Presenter Guide")
    set_run_font(r, size=22, bold=True, color=NAVY)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("How to explain the process, the data, and the metrics on each evaluation screen")
    set_run_font(r, size=13, italic=True)

    doc.add_paragraph()
    for item in [
        "Screens: Overview, Model Inventory, Component Results, Comparison, Confusion Matrices",
        "Run: 131ba7a4-2fa2-475d-8d6e-ccc36044733c",
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

    heading(doc, "1. How to Open the Presentation")
    body(
        doc,
        "Start from Admin → Model Evaluation. Tell the panel you evaluated three chatbot skills, "
        "not one overall percentage. Walk the tabs in this order: Overview, Model Inventory, "
        "Component Results, Comparison, Confusion Matrices.",
    )
    say_box(
        doc,
        "We evaluated ASKa-Piyu in three parts: retrieval (does it find the right pages), "
        "classification (does it tag the right category), and question answering (does the "
        "student-facing answer match the official documents). Each part has its own labeled data and metrics.",
    )
    add_table(
        doc,
        ["Skill", "What we measured", "Data used", "Headline number"],
        [
            [
                "Retrieval",
                "Did a relevant page land in the top 5 results?",
                "12 human-reviewed questions with relevant page IDs",
                "Hit@5 = 91.67% after reranking",
            ],
            [
                "Classification",
                "Did the system assign the agreed subcategory?",
                "65 dual-agreement labels (37 questions, 28 chunks) from a 96-candidate pool",
                "Questions 70.27%; chunks 64.29%",
            ],
            [
                "Question answering",
                "Correctness, faithfulness, relevance, and displayed sources",
                "14 live student-chatbot questions; 12 student-visible scored; 2 faculty-audience refusals",
                "Correctness 0.5833 (58.33%)",
            ],
        ],
        caption="Table 1. The three evaluation tracks.",
    )

    heading(doc, "2. The Process We Followed")
    heading(doc, "2.1 Retrieval", 2)
    bullet(doc, "Prepared 12 student questions from the RAG benchmark (q1–q12).")
    bullet(doc, "A human reviewed which handbook or charter pages are relevant for each question.")
    bullet(doc, "Ran evaluation against the isolated evaluation corpus (not the live production index as the scoring index).")
    bullet(doc, "Measured embedding-only ranking, then the same candidates after the rule-based reranker.")
    heading(doc, "2.2 Classification", 2)
    bullet(doc, "Collected 96 real candidates: 49 questions and 47 chunks.")
    bullet(doc, "Two independent annotation passes assigned taxonomy subcategories.")
    bullet(doc, "Only dual-agreement, evidence-sufficient rows were promoted: 65 cases (37 question, 28 chunk).")
    bullet(doc, "31 candidates were held out (disagreement, out of scope, or insufficient evidence).")
    bullet(doc, "Scored classify_question and classify_chunk against those 65 labels. Confusion matrices were saved for those components.")
    heading(doc, "2.3 Question answering", 2)
    bullet(doc, "Used a 14-question answer-quality set covering fees, offices, processes, academic policy, faculty-manual topics, out-of-scope, and insufficient-evidence probes.")
    bullet(doc, "Logged in as a student and submitted each question exactly as written.")
    bullet(doc, "Captured the on-screen answer and displayed sources.")
    bullet(doc, "Scored against official Citizen’s Charter and Student Handbook passages.")
    bullet(doc, "Faculty Manual questions (teaching load, faculty responsibilities) are faculty-audience only. Under the student role those two replies are expected refusals and are excluded from the 12-case student-visible average.")

    heading(doc, "3. Overview Tab")
    body(
        doc,
        "This is the summary slide. Stay here first. The three colored tiles are the headlines. "
        "The white panels underneath unpack retrieval, classification, and QA.",
    )
    heading(doc, "3.1 The three tiles", 2)
    add_table(
        doc,
        ["Tile", "Number on screen", "Plain meaning"],
        [
            ["Document retrieval", "91.67%", "For 11 of 12 labeled questions, a relevant page was in the top 5 after reranking."],
            ["Category tagging", "70.27%", "Question classifier accuracy on 37 labeled student questions."],
            ["Answer quality", "58.33%", "Human-scored answer correctness on 12 student-visible live chatbot answers."],
        ],
        caption="Table 2. Overview headline tiles.",
    )
    say_box(
        doc,
        "At a glance: retrieval is strongest at 91.67 percent Hit@5. Question classification is 70.27 percent. "
        "Student-facing answer correctness is 58.33 percent. Those are three different tests, so we do not average them into one score.",
    )
    heading(doc, "3.2 Retrieval panel", 2)
    body(doc, "K is 5: a hit means a relevant page appeared in the top five results.")
    add_table(
        doc,
        ["Metric", "Value", "How to explain it"],
        [
            ["Hit@K", "0.9167 (91.67%)", "Share of questions with at least one relevant page in the top 5."],
            ["MRR", "0.8125", "Mean reciprocal rank. Higher means the first relevant page appeared nearer the top."],
            ["nDCG@K", "0.7812", "Graded ranking quality: whether the best pages were ranked first, not only present."],
            ["Cases", "12", "Labeled retrieval questions in this run."],
        ],
    )
    heading(doc, "3.3 Classification panel", 2)
    add_table(
        doc,
        ["Card", "Accuracy", "Macro F1", "Cases"],
        [
            ["Student questions", "70.27%", "0.5064", "37"],
            ["Document chunks", "64.29%", "0.5345", "28"],
        ],
    )
    bullet(doc, "Accuracy is overall percent correct.")
    bullet(doc, "Macro F1 averages F1 across subcategories equally, so rare labels count as much as common ones. That is why F1 is lower than accuracy.")
    bullet(doc, "65 scored in this run = 37 + 28. Labeling pool = 96. Held out = 31.")
    bullet(doc, "Chunk tagging with LLM fallback on and off produced the same score on this run, so only one chunk result is shown.")
    say_box(
        doc,
        "We did not score all 96 candidates. We scored the 65 where both annotation passes agreed. "
        "The other 31 stay held out so disagreements do not enter the accuracy number.",
    )
    heading(doc, "3.4 Answer generation panel", 2)
    add_table(
        doc,
        ["Card", "Score", "What it means"],
        [
            ["Answer Correctness", "0.5833", "Pass = 1, partial = 0.5, fail = 0 on 12 student-visible questions (5 pass, 4 partial, 3 fail)."],
            ["Faithfulness", "0.5417", "Did the answer invent fees, totals, or facts not in the sources?"],
            ["Answer Relevance", "0.9167", "Did the answer address the question? 11 of 12 did."],
            ["Citation Accuracy", "0.9000", "Right document title on replies that showed sources."],
        ],
        caption="Table 3. QA metric cards on Overview.",
    )
    say_box(
        doc,
        "QA was scored from live student chatbot answers, not from a separate hidden prompt. "
        "Two Faculty Manual questions are excluded because a student account cannot retrieve faculty-only documents. "
        "That is access control, not a failed search.",
    )

    heading(doc, "4. Model Inventory Tab")
    body(
        doc,
        "Use this tab to name the pieces of the pipeline. You are not reporting scores here. "
        "You are showing that evaluation covers the real components of the chatbot.",
    )
    add_table(
        doc,
        ["Component on screen", "What it does", "What to call it"],
        [
            ["embedding_retrieval", "Finds similar handbook and charter chunks with multilingual-e5-small embeddings.", "The retriever."],
            ["reranker", "Reorders those candidates with rule-based query expansion and boosting. Not a second trained model.", "The reranker."],
            ["classify_chunk", "Tags a document passage with a taxonomy subcategory. Optional LLM fallback.", "Chunk classifier."],
            ["classify_question", "Tags a student question. Rules and similarity only; it never calls an LLM.", "Question classifier."],
            ["answer_generation_llm", "Writes the student-facing answer from retrieved context.", "The answer generator."],
            ["citation_verifier_llm", "Checks displayed citations against retrieved evidence.", "The citation verifier."],
        ],
        caption="Table 4. Model Inventory talking points.",
    )
    say_box(
        doc,
        "Retrieval uses an embedding model plus a rule-based reranker. Question classification never calls an LLM. "
        "Chunk classification may use an LLM fallback. Answer generation is the student-facing language model.",
    )

    heading(doc, "5. Component Results Tab")
    body(
        doc,
        "This is the raw score sheet for the selected run. Each card is one component: status, model name, "
        "how many labeled cases were used, and every saved metric. Open View case-level results when someone "
        "asks to see a single prediction.",
    )
    heading(doc, "5.1 What you will point to", 2)
    bullet(doc, "classify_question: 37 cases, accuracy 0.7027, macro F1 0.5064.")
    bullet(doc, "classify_chunk (LLM on) and classify_chunk (LLM off): 28 cases each, accuracy 0.6429, macro F1 0.5345.")
    bullet(doc, "Reranker and embedding_retrieval: Hit@K, MRR, nDCG, precision, recall for the 12 retrieval questions.")
    bullet(doc, "answer_generation_llm: the four QA scores from the live student evaluation (12 cases).")
    heading(doc, "5.2 How to explain a case-level row", 2)
    body(
        doc,
        "Each row shows predicted label, expected (gold) label, and correct true or false. "
        "Example from the chunk classifier: a Scholarships gold row predicted as Registration is a miss; "
        "Honorable Dismissal predicted as Honorable Dismissal is a hit.",
    )
    say_box(
        doc,
        "Component Results is the detailed ledger. Overview is the summary. If you want one wrong example, "
        "I can open a case where predicted and expected differ.",
    )
    heading(doc, "5.3 Words to use for metric pills", 2)
    add_table(
        doc,
        ["Name on screen", "Say this"],
        [
            ["accuracy", "Percent of cases whose predicted label matches the gold label."],
            ["macro_f1", "F1 averaged equally across labels, so rare categories are not ignored."],
            ["macro_precision / macro_recall", "Average precision and recall across labels."],
            ["weighted_f1", "F1 weighted by how many cases each label has."],
            ["case_count", "How many labeled cases this component scored."],
            ["Unlabeled excluded", "Cases with no gold label are skipped; they are not counted as wrong."],
        ],
    )

    heading(doc, "6. Comparison Tab")
    body(
        doc,
        "This tab is for before-and-after retrieval and for a second look at classification. "
        "The important story is embedding-only versus reranked, on the same 12 questions and the same corpus.",
    )
    heading(doc, "6.1 Retrieval comparator", 2)
    add_table(
        doc,
        ["Metric", "Embedding-only", "Reranked", "What the gap means"],
        [
            ["Hit@K", "0.8333", "0.9167", "Reranking lifted hits in the top 5 from 10/12 to 11/12."],
            ["MRR", "0.6875", "0.8125", "The first relevant page moved higher in the list."],
            ["nDCG@K", "0.6871", "0.7812", "The ranking of the best pages improved, not only presence."],
            ["Precision@K", "0.2500", "0.2333", "Share of the top 5 that are relevant. Can stay similar when Hit@K rises."],
            ["Recall@K", "0.8056", "0.8056", "Share of all relevant pages recovered in the top 5. Same in this run."],
        ],
        caption="Table 5. Embedding-only versus reranked retrieval.",
    )
    body(
        doc,
        "Blue bars are embedding-only. Maroon bars are reranked. Both rankings come from one search per question: "
        "raw similarity order versus the reranked order of the same candidate pool. That is why the delta is the "
        "reranker’s contribution, not a second corpus.",
    )
    say_box(
        doc,
        "On the same 12 labeled questions, adding the reranker raised Hit@5 from 83.33 percent to 91.67 percent "
        "and raised MRR from 0.69 to 0.81. Recall in the top 5 stayed 0.81, so we recovered the same relevant pages "
        "but ranked them better.",
    )
    heading(doc, "6.2 Classification block on Comparison", 2)
    body(
        doc,
        "The same 70.27 percent / 64.29 percent cards appear here, plus per-classifier tables and the question "
        "confusion matrix. Use Overview for the headline and Comparison when you want retrieval and classification side by side.",
    )

    heading(doc, "7. Confusion Matrices Tab")
    body(
        doc,
        "Confusion matrices apply only to classification. They do not apply to retrieval Hit@K or to QA scores. "
        "There is one matrix for classify_question and one for each classify_chunk mode.",
    )
    heading(doc, "7.1 How to read the grid", 2)
    bullet(doc, "Rows are the true (gold) label.")
    bullet(doc, "Columns are the predicted label.")
    bullet(doc, "The diagonal is correct. Darker cells have higher counts.")
    bullet(doc, "A number off the diagonal is a confusion: gold was A, the system said B.")
    heading(doc, "7.2 What to show", 2)
    body(
        doc,
        "For questions, 37 cases are spread across many subcategories. Several labels have support 0 or 1, "
        "which is why macro F1 is 0.5064 even though accuracy is 70.27 percent. Point to a high-support diagonal "
        "(for example Grading System 3, or Good Moral 2) as a clean hit, then to an off-diagonal as an error.",
    )
    body(
        doc,
        "The per-subcategory table lists precision, recall, F1, and support. Support is how many gold cases that "
        "label had. A label with support 0 cannot have a meaningful F1; a label with support 1 is a single example.",
    )
    say_box(
        doc,
        "Rows are truth, columns are prediction. Correct answers sit on the diagonal. Accuracy looks at every case equally. "
        "Macro F1 looks at each subcategory equally, so rare labels pull F1 down. That is expected with 37 questions across many offices and services.",
    )
    heading(doc, "7.3 Chunk matrix", 2)
    body(
        doc,
        "The chunk matrix uses 28 labeled passages. Example: Administrative Officials 2 on the diagonal is two correct "
        "administrative-official chunks. A Counseling row with a Board of Regents column is a mis-tag. Walk one miss "
        "if asked; do not read every cell aloud.",
    )

    heading(doc, "8. Suggested Walkthrough (about 5–7 minutes)")
    bullet(doc, "Overview (2 minutes): three tiles, then Hit@5 91.67 percent, then 70.27 / 64.29, then QA 0.5833.")
    bullet(doc, "Model Inventory (30 seconds): retriever, reranker, two classifiers, answer generator.")
    bullet(doc, "Component Results (1 minute): open classify_question, mention 37 cases, open one case list if asked.")
    bullet(doc, "Comparison (1–2 minutes): blue versus maroon bars; reranker lifts Hit@K and MRR.")
    bullet(doc, "Confusion Matrices (1 minute): rows = gold, columns = predicted, diagonal = correct; mention support and macro F1.")
    say_box(
        doc,
        "If they ask for one number only: retrieval Hit@5 is 91.67 percent on 12 labeled questions. "
        "If they ask why QA is lower: live answers were scored for required facts, invented units, and missing multi-document fees, which is stricter than retrieval hits.",
    )

    heading(doc, "9. If They Ask Follow-up Questions")
    add_table(
        doc,
        ["Question", "Answer"],
        [
            ["Why not one overall accuracy?", "The three tests use different gold sets and different rules. Combining them would hide retrieval strength and QA strictness."],
            ["Why 12 retrieval questions?", "Those 12 have human-reviewed relevant pages. That is the labeled retrieval set for this run."],
            ["Why 65 classification cases, not 96?", "96 were candidates. 65 had dual-agreement labels. 31 were held out so unstable labels are not scored."],
            ["Why is F1 lower than accuracy?", "Accuracy counts every case once. Macro F1 averages labels equally, including rare offices with one example."],
            ["Why two faculty questions excluded?", "Faculty Manual is faculty-audience. A student session is not allowed to retrieve it. The refusal is expected."],
            ["Did the reranker use a second model?", "No. It is rule-based reordering of the same embedding candidates."],
            ["What is K?", "Five. Hit@K means a relevant page appeared somewhere in the top five."],
        ],
        caption="Table 6. Short answers for likely questions.",
    )

    heading(doc, "10. Numbers Card (keep this visible)")
    add_table(
        doc,
        ["Item", "Value"],
        [
            ["Run ID", "131ba7a4-2fa2-475d-8d6e-ccc36044733c"],
            ["Retrieval questions", "12"],
            ["Retrieval Hit@5 embedding-only", "0.8333"],
            ["Retrieval Hit@5 reranked", "0.9167"],
            ["Retrieval MRR reranked", "0.8125"],
            ["Retrieval nDCG@5 reranked", "0.7812"],
            ["Question classification accuracy / F1 / cases", "70.27% / 0.5064 / 37"],
            ["Chunk classification accuracy / F1 / cases", "64.29% / 0.5345 / 28"],
            ["Classification pool / scored / held out", "96 / 65 / 31"],
            ["QA live questions", "14 (12 scored, 2 role-gated)"],
            ["QA correctness / faithfulness / relevance / citation", "0.5833 / 0.5417 / 0.9167 / 0.9000"],
        ],
        caption="Table 7. Numbers to keep beside you while presenting.",
    )

    heading(doc, "11. Related Documents")
    bullet(doc, "Retrieval, classification, and earlier overview: ASKa-Piyu Comprehensive Evaluation Documentation.")
    bullet(doc, "QA process and per-question scores: ASKa-Piyu_QA_Evaluation_Documentation.docx.")
    bullet(doc, "QA metric file: backend/benchmarks/evaluation/human_answer_quality_overview.json.")

    doc.save(OUT)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()

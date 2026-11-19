"""Thesis-ready evaluation metrics correctness review (Word)."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent / "ASKa-Piyu_Evaluation_Metrics_Correctness_Review.docx"
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
HEADER_FILL = "1F3A5F"
ALT_FILL = "EEF2F6"
OK_FILL = "E6F4EA"
WARN_FILL = "FFF8E6"
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
    left = fp.add_run("ASKa-Piyu Evaluation Metrics Correctness Review  ·  Page ")
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
    r = t.add_run("Evaluation Metrics Correctness Review")
    set_run_font(r, size=22, bold=True, color=NAVY)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run(
        "Independent verification of retrieval, classification, and question-answering metrics"
    )
    set_run_font(r, size=13, italic=True)

    doc.add_paragraph()
    for item in [
        "Local evaluation run 131ba7a4-2fa2-475d-8d6e-ccc36044733c",
        "Independent recalculation: metrics_correctness_review_2026-11-05",
        "Original datasets and predictions were not modified",
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

    heading(doc, "1. Evaluation objectives")
    body(
        doc,
        "ASKa-Piyu is a retrieval-augmented chatbot for Laguna State Polytechnic University "
        "policies and student services. The Model Evaluation system measures three pipeline "
        "stages separately: retrieval of relevant chunks, classification of questions and "
        "document chunks into taxonomy subcategories, and question-answering quality.",
    )
    body(doc, "This review answers four questions:")
    bullet(doc, "Which files, scripts, datasets, and functions actually produced the reported numbers?")
    bullet(doc, "Do the reported numerators, denominators, and formulas match the code?")
    bullet(doc, "Can each headline metric be recalculated from the original labels and stored predictions?")
    bullet(
        doc,
        "Were any QA scores constructed or adjusted in a way that would mislead a thesis reader?",
    )
    body(
        doc,
        "This document does not change original datasets, original predictions, or dashboard numbers. "
        "Independent recalculation is stored separately in verification_results.json.",
    )

    heading(doc, "2. What was executed versus what was recalculated")
    body(
        doc,
        "A metric function that exists in code is not the same thing as a completed evaluation. "
        "The following distinction is used throughout this document.",
    )
    add_table(
        doc,
        ["Component", "Genuine executed evaluation", "This review"],
        [
            [
                "Retrieval (embedding and reranked)",
                "Yes. store.search() was run on the isolated 691-chunk chroma_evaluation index. Rankings and metrics were persisted.",
                "Recalculated Hit@5, MRR, Precision@5, Recall@5, nDCG@5 from stored rankings plus gold relevant_ids.",
            ],
            [
                "Question classifier",
                "Yes. classify_question() was run on 37 labeled cases.",
                "Recalculated accuracy, macro F1, and the confusion matrix from stored y_true / y_pred.",
            ],
            [
                "Chunk classifier",
                "Yes. classify_chunk() was run on 28 labeled cases, twice (LLM on and LLM off).",
                "Same recalculation. LLM-on and LLM-off predictions are identical (see limitations).",
            ],
            [
                "Automated RAG / RAGAS / citation verifier",
                "Not evaluable. rag_eval_dataset.json has cases = []. citation_verifier_llm status is not_evaluable.",
                "Confirmed empty. No automated faithfulness/citation numbers were invented.",
            ],
            [
                "Live student QA overlay",
                "Yes. Fourteen live student-chatbot screenshots were judged by a human on 5 November 2026.",
                "Recalculated the four overlay scores from per_case_metrics.json and the documented formulas.",
            ],
        ],
        caption="Table 1. Executed evaluations versus independent recalculation.",
    )

    heading(doc, "3. Datasets used")
    heading(doc, "3.1 Retrieval", 2)
    body(
        doc,
        "File: backend/benchmarks/evaluation/retrieval_relevance_dataset.json. "
        "Version 2026-11-04-v2-human-reviewed-rag-benchmark-q1-q12. "
        "SHA-256 b48a0961c7c18d8224fac28b3b0a23ec3713be52f720a33ab569ace91022d0b5. "
        "Twelve labeled queries, zero unlabeled rows, no duplicate query_id values.",
    )
    body(
        doc,
        "Preparation: the twelve questions come from scripts/rag_benchmark.py. A human reviewed "
        "candidate chunks from the 691-record extraction artifact "
        "(chroma_record_extraction_20261104T104214Z.json) and assigned graded_relevance "
        "(3 = highly relevant, 2 = supporting, 1 = partial or superseded, 0 = omitted). "
        "relevant_ids contains only grades greater than zero. Labels are human-reviewed, not "
        "model-generated. Two notes document source issues rather than silent label edits: "
        "rag_benchmark_04 records a real Charter ₱30 versus Handbook ₱20/unit conflict; "
        "rag_benchmark_05 grades the library-fee chunk as 1 because the extraction is truncated "
        "at “2 pesos per”.",
    )
    body(
        doc,
        "Independence: retrieval gold is chunk identity, not a classifier label and not a "
        "reference answer. The labels were not copied into classification_eval_dataset.json "
        "as true_label. The evaluation corpus is the isolated chroma_evaluation / aska_evaluation "
        "index, not production Chroma.",
    )

    heading(doc, "3.2 Classification", 2)
    body(
        doc,
        "File: backend/benchmarks/evaluation/classification_eval_dataset.json. "
        "Version 2026-11-04-v2-independent-ai-annotation-dual-agreement. "
        "SHA-256 1ea33759366ea55a4f8f1c6d3a1560582a1d256b6b213a2c436dd581afecf2e3. "
        "Sixty-five labeled cases (37 classify_question, 28 classify_chunk), no unlabeled rows "
        "inside the file, no duplicate case_id values.",
    )
    body(
        doc,
        "Preparation: 96 real candidates (49 questions, 47 chunks) were drawn from project files "
        "and the Chroma extraction. Two independent AI annotators (Grok in this session; a separate "
        "Grok 4.7 pass) wrote reviewer1_annotations.json and reviewer2_annotations.json. "
        "promote_agreed_labels.py promoted a row only when both assigned the same taxonomy "
        "subcategory, both set evidence_sufficient=true, and neither used MARK_FOR_REVIEW. "
        "Thirty-one candidates were held out (disagreement, out-of-scope, or insufficient evidence) "
        "and do not appear in the eval JSON. Methodology: classification_labeling/ANNOTATION_METHODOLOGY.md.",
    )
    body(
        doc,
        "Independence from the production classifier: true_label is the dual-AI subcategory, not "
        "the live index metadata stamp. Provenance notes in the JSON state that retrieval relevant_ids "
        "are not classification labels. The production functions classify_question and classify_chunk "
        "were not used to write true_label. The limitation is different: both annotators are language "
        "models, so dual agreement is not human gold.",
    )

    heading(doc, "3.3 Question answering", 2)
    body(
        doc,
        "The labeled RAG template backend/benchmarks/evaluation/rag_eval_dataset.json remains empty "
        "(version 2026-11-04-v1-empty-template, cases = []). Automated answer_correctness, faithfulness, "
        "and citation-set metrics from evaluation_service.evaluate_rag_components() were therefore "
        "not computed.",
    )
    body(
        doc,
        "The questions used for live scoring sit in "
        "answer_quality_eval_dataset.pending_human_review.json, which is still evaluation_ready=false "
        "and labeling_status=unlabeled. Question text for aq_01–aq_12 is reused from the retrieval "
        "dataset. aq_13 (out-of-scope weather on Mars) and aq_14 (Wi-Fi password) were added as "
        "behavior cases. Proposed reference answers were drafted from the 691-chunk extraction "
        "before the live screenshots were scored. They were not promoted into rag_eval_dataset.json.",
    )
    body(
        doc,
        "The scored evidence is answer_quality_labeling/runs/aq_live_student_chat_20261105T023200Z/ "
        "(per_case_metrics.json, overview_metrics.json, REPORT.md). The four Overview numbers are "
        "copied into human_answer_quality_overview.json and re-applied onto each local evaluation "
        "run by app.services.evaluation.human_rag_overview so that Run Evaluation cannot blank the cards.",
    )

    heading(doc, "4. Code path and symbols y_true, y_pred, and y_hat", 1)
    heading(doc, "4.1 Orchestration", 2)
    body(
        doc,
        "app.services.evaluation.evaluation_service.run_evaluation() is the only module in the "
        "evaluation package that calls live components. It loads the three JSON datasets, runs "
        "classification, retrieval, and RAG, and returns ComponentEvaluationResult objects. "
        "persistence.py writes those objects to PostgreSQL. The Admin Overview reads the latest "
        "completed run.",
    )
    flowchart(
        doc,
        [
            "classification_eval_dataset.json",
            "        |",
            "        v",
            "evaluate_classify_question / evaluate_classify_chunk",
            "        |  y_true = case['true_label']",
            "        |  y_pred = classify_*(text).subcategory",
            "        v",
            "evaluate_classification(y_true, y_pred)",
            "build_confusion_matrix(y_true, y_pred)",
            "",
            "retrieval_relevance_dataset.json  +  chroma_evaluation (691 chunks)",
            "        |",
            "        v",
            "store.search(query, top_k=20)  -> embedding order and reranked order",
            "evaluate_retrieval(results, k=5)",
            "",
            "rag_eval_dataset.json  (empty)",
            "        |",
            "        v",
            "evaluate_rag_components -> NOT_EVALUABLE",
            "human_rag_overview.apply_human_rag_overview_to_run()",
        ],
        "Figure 1. Evaluation data flow for the reported dashboard run.",
    )

    heading(doc, "4.2 What y_hat is in this project", 2)
    body(
        doc,
        "The evaluation code does not define a variable named y_hat. In standard notation ŷ "
        "(written y_hat) is the model’s predicted label. In this repository that value is y_pred.",
    )
    add_table(
        doc,
        ["Symbol", "In ASKa-Piyu", "Meaning"],
        [
            [
                "y_true",
                "case['true_label'] (classification); relevant_ids / graded_relevance (retrieval)",
                "Ground truth used for scoring.",
            ],
            [
                "y_pred",
                "classify_chunk(...).subcategory or classify_question(...).subcategory; ranked chunk ids for retrieval",
                "The system prediction. This is ŷ.",
            ],
            [
                "y_hat",
                "Not used",
                "Literature name for the same quantity as y_pred. No separate vector exists.",
            ],
        ],
        caption="Table 2. Ground truth and prediction symbols.",
    )
    body(
        doc,
        "Classification comparison is exact string equality: correct = (y_pred == y_true). "
        "There is no probability cutoff at metric time. Invalid or missing predictions cannot "
        "silently become a fabricated 0.0 in the metric modules: empty y_true raises EmptyDatasetError; "
        "mismatched lengths raise ValueError; unlabeled dataset rows are counted as skipped and excluded.",
    )
    body(
        doc,
        "The classifier itself does use confidence thresholds, but they select the internal method, "
        "not the accuracy denominator. RULE_CONFIDENCE_THRESHOLD = 0.72 keeps a rule-based subcategory "
        "without consulting embedding similarity. LOW_CONFIDENCE_THRESHOLD = 0.45 skips optional LLM "
        "fallback for classify_chunk. classify_question never calls an LLM. After a subcategory string "
        "is chosen, evaluate_classification receives that string as y_pred.",
    )

    heading(doc, "5. Metric definitions and calculation process", 1)
    heading(doc, "5.1 Classification", 2)
    body(doc, "Implemented in app.services.evaluation.classification_metrics.evaluate_classification.")
    bullet(doc, "Accuracy = (number of cases with y_true == y_pred) / N.")
    bullet(doc, "Per class, one-versus-rest: precision = TP / (TP+FP), recall = TP / (TP+FN), F1 = harmonic mean. Zero denominator returns 0.0.")
    bullet(doc, "Macro F1 is the unweighted mean of per-class F1, including labels that appear only in y_pred (support 0). Those extra labels pull macro F1 down.")
    bullet(doc, "The function rounds per-class precision/recall/F1 to four decimals, then averages those rounded values, then rounds the macro again. Independent recalculation used the same rounding.")
    body(
        doc,
        "Confusion matrices are built only for classification (confusion_matrix.build_confusion_matrix). "
        "Retrieval Hit@K and QA scores are not classification and have no confusion matrix.",
    )
    body(
        doc,
        "Independent count: question classifier 26 of 37 exact matches (0.7027). Chunk classifier "
        "18 of 28 exact matches (0.6429). Case ids in the persisted run align with the dataset order. "
        "The confusion-matrix diagonal equals the number of exact matches.",
    )

    heading(doc, "5.2 Retrieval", 2)
    body(doc, "Implemented in app.services.evaluation.retrieval_metrics.evaluate_retrieval with k = 5.")
    bullet(doc, "Hit@K = 1 if at least one gold id appears in the top K, else 0; then average over queries.")
    bullet(doc, "MRR = average of 1/rank of the first gold id, or 0 if none is retrieved.")
    bullet(doc, "Precision@K = |gold ∩ top-K| / K.")
    bullet(doc, "Recall@K = |gold ∩ top-K| / |gold|.")
    bullet(
        doc,
        "nDCG@K uses graded_relevance when present. DCG = Σ grade(d_i) / log2(i+1). IDCG uses the "
        "ideal descending grades. Binary grade 1.0 is used only when graded_relevance is omitted; "
        "this dataset always supplies grades.",
    )
    body(
        doc,
        "Both rankings come from one store.search() call per query. Embedding-only order is the same "
        "candidate pool sorted by vector_similarity. Reranked order is the rule-based reranker output. "
        "That is an ablation of ranking, not a second embedding model.",
    )
    body(
        doc,
        "Independent count: embedding Hit@5 = 10/12 = 0.8333 (misses rag_benchmark_03 enrollment office "
        "and rag_benchmark_10 faculty responsibilities). Reranked Hit@5 = 11/12 = 0.9167 (still misses "
        "rag_benchmark_10). Recall@5 is 0.8056 for both because the reranker does not recover additional "
        "gold ids on average; it mainly improves rank of gold already in the pool (MRR 0.6875 → 0.8125).",
    )

    heading(doc, "5.3 Question answering (human overlay, not RAGAS)", 2)
    body(
        doc,
        "The production aggregator aggregate_rag_metrics() averages non-null per-case floats and was "
        "not the source of the Overview cards. The live QA scores use pass = 1.0, partial = 0.5, "
        "fail = 0.0, and exclude the two faculty-role questions.",
    )
    bullet(doc, "Answer correctness = (5×1.0 + 4×0.5 + 3×0.0) / 12 = 7.0 / 12 = 0.5833.")
    bullet(doc, "Faithfulness = (6 faithful + 1×0.5 mixed + 5 unfaithful) / 12 = 6.5 / 12 = 0.5417.")
    bullet(doc, "Answer relevancy = 11/12 = 0.9167 (only aq_08, the garbled 75% table, did not address the question).")
    bullet(doc, "Citation title match = (1+1+0.5+1+1) / 5 = 0.9000 on the five screenshots that showed source chips. This is not gold chunk-id citation_set_precision.")

    heading(doc, "6. Independent verification results", 1)
    body(
        doc,
        "Script: backend/benchmarks/evaluation/metrics_correctness_review_2026-11-05/verify_evaluation_metrics.py. "
        "Output: verification_results.json. The script reads the original files, recomputes every "
        "headline metric from first principles, and does not overwrite originals or re-query models.",
    )
    ok = [OK_FILL] * 18
    add_table(
        doc,
        ["Evaluation", "Reported", "Independently calculated", "Status"],
        [
            ["QA answer_correctness", "0.5833", "0.5833", "Verified"],
            ["QA faithfulness", "0.5417", "0.5417", "Verified"],
            ["QA answer_relevancy", "0.9167", "0.9167", "Verified"],
            ["QA citation title match (n=5)", "0.9000", "0.9000", "Verified"],
            ["Retrieval embedding Hit@5", "0.8333", "0.8333", "Verified"],
            ["Retrieval embedding MRR", "0.6875", "0.6875", "Verified"],
            ["Retrieval embedding nDCG@5", "0.6871", "0.6871", "Verified"],
            ["Retrieval embedding Precision@5", "0.2500", "0.2500", "Verified"],
            ["Retrieval embedding Recall@5", "0.8056", "0.8056", "Verified"],
            ["Retrieval reranked Hit@5", "0.9167", "0.9167", "Verified"],
            ["Retrieval reranked MRR", "0.8125", "0.8125", "Verified"],
            ["Retrieval reranked nDCG@5", "0.7812", "0.7812", "Verified"],
            ["Retrieval reranked Precision@5", "0.2333", "0.2333", "Verified"],
            ["Retrieval reranked Recall@5", "0.8056", "0.8056", "Verified"],
            ["Classifier questions accuracy", "0.7027", "0.7027", "Verified"],
            ["Classifier questions macro F1", "0.5064", "0.5064", "Verified"],
            ["Classifier chunks accuracy", "0.6429", "0.6429", "Verified"],
            ["Classifier chunks macro F1", "0.5345", "0.5345", "Verified"],
        ],
        fills=ok,
        caption="Table 3. Independent recalculation of every headline metric. No numeric discrepancy.",
    )

    heading(doc, "7. QA accuracy concern — honest finding", 1)
    body(
        doc,
        "The concern was that QA accuracy may have been artificially influenced by how questions "
        "or expected answers were prepared. The evidence does not show fabricated percentages. "
        "It does show a different, and disclosable, methodological issue: the Overview QA cards "
        "are a human overlay, not an automated labeled RAG evaluation.",
    )
    heading(doc, "7.1 What is genuine", 2)
    bullet(doc, "Fourteen live student-role answers were captured as screenshots and judged case by case.")
    bullet(doc, "Five pass, four partial, and three fail were recorded. The score was not rewritten toward 1.0.")
    bullet(doc, "aq_04, aq_05, and aq_08 were failed. Partial credit was used where the answer was incomplete or mixed, not where it was wrong.")
    bullet(doc, "rag_eval_dataset.json was not backfilled with labels derived from the model output.")
    bullet(doc, "The pending answer-quality file remains unlabeled and evaluation_ready=false.")
    bullet(doc, "The arithmetic of the four overlay metrics reproduces exactly.")

    heading(doc, "7.2 What must not be claimed", 2)
    bullet(doc, "These four numbers are not RAGAS scores.")
    bullet(doc, "They are not computed by evaluate_rag_components() against labeled gold_citation_ids.")
    bullet(doc, "Citation 0.9000 is document-title match on five screenshots, not chunk-id set precision.")
    bullet(doc, "The scorer was not a blinded independent human gold process. Judgments were made after seeing the live answers, using the pending proposed answers as a guide.")
    bullet(doc, "aq_01–aq_12 reuse the retrieval benchmark questions. That is a known-answer set with labeled relevant chunks, not a random student log sample.")

    heading(doc, "7.3 Scoring choices that change the headline if disclosed differently", 2)
    add_table(
        doc,
        ["Choice actually used", "Alternative", "Correctness"],
        [
            ["Partial = 0.5 (reported)", "Count partial as fail", "0.5833 → 0.4167"],
            ["Include out-of-scope Mars refusal as pass", "Exclude aq_13 from the denominator", "0.5833 → 0.5455"],
            ["Exclude two faculty questions as role-gated", "Count them as fail", "Would lower the score; exclusion is the designed student-role behavior"],
        ],
        fills=[WARN_FILL, WARN_FILL, WARN_FILL],
        caption="Table 4. Methodological choices that affect QA correctness. These are disclosures, not evidence that the stored 0.5833 was edited.",
    )
    body(
        doc,
        "The Overview cards persist because human_rag_overview.py copies the four human values onto "
        "each new local run. That is overlay persistence, not a change of the underlying judgments. "
        "A thesis reader should be told that clicking Run Evaluation re-runs retrieval and "
        "classification, leaves rag_eval_dataset.json empty, and then reapplies the same human QA overlay.",
    )

    heading(doc, "8. Retrieval and classifier integrity (separate from QA)", 1)
    body(
        doc,
        "Retrieval and classification were not treated as manipulated by default. The stored "
        "predictions recalculate to the reported metrics. Dataset rows align with case_results. "
        "No duplicate ids were found.",
    )
    body(
        doc,
        "Classification limitations that must still be stated: labels are dual-AI agreement, not "
        "human gold; 31 of 96 candidates have no approved label; class support is imbalanced; "
        "macro F1 includes predicted labels with support 0 (five extra labels on questions, three "
        "on chunks), which lowers macro F1 relative to accuracy. Chunk LLM-on and LLM-off scores "
        "are identical because the local Groq/OpenRouter call returned 401 Unauthorized, so both "
        "modes fell back to rules plus similarity. That is an environment limitation, not a finding "
        "that the LLM adds nothing.",
    )
    body(
        doc,
        "Retrieval limitation: Precision@5 is low (0.25 embedding, 0.2333 reranked) because K = 5 "
        "and most queries have only one or two gold ids. Hit@5 and MRR are the appropriate headline "
        "metrics for “was the right chunk found.” nDCG uses the 1–3 human grades.",
    )

    heading(doc, "9. Other evaluation machinery that is not in the thesis headlines", 1)
    bullet(
        doc,
        "citation_verifier_llm: not_evaluable on this run, reason “no labeled cases in rag_eval_dataset.json”.",
    )
    bullet(
        doc,
        "performance_metrics.py (latency, success rate, tokens): implemented and unit-tested; not a headline thesis table for this run.",
    )
    bullet(
        doc,
        "citation_grounding_benchmark.json and related capture scripts: a separate unlabeled citation-grounding workflow. Those cases were not promoted into rag_eval_dataset.json and are not the Overview citation card.",
    )
    bullet(
        doc,
        "Unit tests that were written and that exercise the formulas (not the 12-query live index): "
        "test_evaluation_classification_metrics.py, test_evaluation_confusion_matrix.py, "
        "test_evaluation_retrieval_metrics.py, test_evaluation_rag_metrics.py.",
    )

    heading(doc, "10. Limitations and required thesis wording", 1)
    body(doc, "Recommended wording:")
    bullet(
        doc,
        "Retrieval was evaluated on 12 human-reviewed queries against an isolated 691-chunk index. Embedding Hit@5 = 0.8333; reranked Hit@5 = 0.9167. These figures were independently recalculated from stored rankings.",
    )
    bullet(
        doc,
        "Classification accuracy (questions 0.7027, chunks 0.6429) uses dual independent AI labels, not human gold. Macro F1 is lower because the label set is imbalanced and includes predicted classes with zero support.",
    )
    bullet(
        doc,
        "Question-answering Overview scores are human judgments of 12 student-visible live answers (plus two expected faculty-role refusals). They are not RAGAS and not computed from rag_eval_dataset.json. Answer correctness = 0.5833 with partial credit.",
    )
    bullet(
        doc,
        "Do not describe the four QA cards as automated LLM-as-judge metrics, and do not describe classification confusion matrices as human-validated.",
    )

    heading(doc, "11. Files referenced", 1)
    add_table(
        doc,
        ["Role", "Path"],
        [
            ["Reported headlines", "benchmarks/evaluation/results_json/evaluation_results.json"],
            ["Full persisted run", "benchmarks/evaluation/results_json/evaluation_run_131ba7a4-2fa2-475d-8d6e-ccc36044733c.json"],
            ["Retrieval gold", "benchmarks/evaluation/retrieval_relevance_dataset.json"],
            ["Classification gold", "benchmarks/evaluation/classification_eval_dataset.json"],
            ["Empty RAG template", "benchmarks/evaluation/rag_eval_dataset.json"],
            ["QA overlay", "benchmarks/evaluation/human_answer_quality_overview.json"],
            ["QA per-case judgments", "benchmarks/evaluation/answer_quality_labeling/runs/aq_live_student_chat_20261105T023200Z/per_case_metrics.json"],
            ["Pending unlabeled AQ set", "benchmarks/evaluation/answer_quality_labeling/answer_quality_eval_dataset.pending_human_review.json"],
            ["Metric implementations", "app/services/evaluation/{classification,retrieval,rag,confusion_matrix}_metrics.py and evaluation_service.py"],
            ["This verification", "benchmarks/evaluation/metrics_correctness_review_2026-11-05/"],
        ],
        caption="Table 5. Original evidence files. None of these originals were modified by this review.",
    )

    heading(doc, "12. Conclusion", 1)
    body(
        doc,
        "Every headline number on the local evaluation dashboard recalculates from the original "
        "labels and stored predictions. There is no arithmetic discrepancy. Retrieval and "
        "classification were genuinely executed. Automated RAG evaluation was not executed because "
        "the labeled RAG file is empty. The QA cards are a documented human overlay of live "
        "student answers. The QA percentages were not cooked; they must still be described as "
        "human scores on a known-answer set with partial credit, not as RAGAS accuracy.",
    )

    doc.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()

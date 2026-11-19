"""Generate the comprehensive ASKa-Piyu evaluation Word document.

Documentation only. Reads existing artifacts; does not modify datasets,
runs, production code, or deployment.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent / "ASKa-Piyu_Comprehensive_Evaluation_Documentation.docx"
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
HEADER_FILL = "1F3A5F"
ALT_FILL = "EEF2F6"
LIVE_FILL = "E6F4EA"
FAIL_FILL = "FDECEC"
REF_FILL = "EEF4FB"
NS_FILL = "F4F4F4"
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


def cell_text(cell, text, *, bold=False, size=10, color=None, align=WD_ALIGN_PARAGRAPH.LEFT, font="Times New Roman"):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    set_run_font(run, name=font, size=size, bold=bold, color=color)
    set_cell_border(cell)


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


def cap(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(12)
    run = p.add_run(text)
    set_run_font(run, size=10, italic=True, color=CAPTION_GRAY)
    return p


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


def title_page(doc):
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
    r = t.add_run("Comprehensive Evaluation Documentation")
    set_run_font(r, size=22, bold=True, color=NAVY)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("Retrieval, Classification, and Question-Answering Evaluation of the Student-Facing RAG Chatbot")
    set_run_font(r, size=13, italic=True)

    doc.add_paragraph()
    meta = [
        "Document type: Technical evaluation reference for the thesis manuscript",
        "Prepared: 5 November 2026",
        "Scope: Local evaluation artifacts, isolated evaluation corpus, and recorded live observations",
        "Status: Documentation of completed evaluation work; not a claim of production-wide accuracy",
    ]
    for line in meta:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(line)
        set_run_font(r, size=11)

    doc.add_paragraph()
    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = note.add_run(
        "This document reports only results that exist in evaluation artifacts. "
        "Unavailable metrics are stated as unavailable. Live chatbot outputs are distinguished "
        "from reference-based case reviews. No overall system accuracy is computed across "
        "unequal evaluation populations."
    )
    set_run_font(r, size=11, italic=True, color=CAPTION_GRAY)
    page_break(doc)


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

    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = hp.add_run("ASKa-Piyu Comprehensive Evaluation Documentation")
    set_run_font(hr, size=9, italic=True, color=NAVY)

    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = fp.add_run("ASKa-Piyu  ·  Thesis Evaluation Reference  ·  Page ")
    set_run_font(fr, size=10, color=NAVY)
    add_page_number(fp)

    title_page(doc)

    heading(doc, "Table of Contents", 1)
    body(
        doc,
        "The table of contents is a Word field. After opening the file, right-click it and choose Update Field, then Update entire table.",
        italic=True,
    )
    toc_p = doc.add_paragraph()
    add_toc_field(toc_p)
    page_break(doc)

    chapter_1(doc)
    chapter_2(doc)
    chapter_3(doc)
    chapter_4(doc)
    chapter_5(doc)
    chapter_6(doc)
    chapter_7(doc)
    chapter_8(doc)
    chapter_9(doc)
    chapter_10(doc)
    chapter_11(doc)
    chapter_12(doc)
    appendix_a(doc)
    appendix_b(doc)
    appendix_c(doc)

    doc.save(str(OUT))
    print(f"WROTE {OUT}")
    print(f"EXISTS {OUT.exists()}")
    print(f"BYTES {OUT.stat().st_size}")


def chapter_1(doc):
    heading(doc, "1. Introduction and Evaluation Objectives", 1)
    body(
        doc,
        "ASKa-Piyu is a retrieval-augmented generation (RAG) chatbot for Laguna State Polytechnic University "
        "students. A student question is classified, relevant handbook and Citizen’s Charter passages are retrieved "
        "from ChromaDB, and a student-facing answer is generated with citations. Evaluation therefore cannot rest on "
        "a single accuracy number. Retrieval, classification, and answer generation fail in different ways and must "
        "be measured separately.",
    )
    heading(doc, "1.1 Purpose of this document", 2)
    body(
        doc,
        "This document is a technical reference for the thesis manuscript writer. It explains what was evaluated, "
        "why each dataset exists, how the evaluation code works, which metrics were actually computed, and which "
        "claims the current evidence can and cannot support.",
    )
    heading(doc, "1.2 Evaluation objectives", 2)
    bullet(doc, "Measure whether the retriever returns human-labeled relevant chunks for university-service questions.")
    bullet(doc, "Measure whether question and chunk classifiers assign taxonomy subcategories consistent with the evaluation labels.")
    bullet(doc, "Prepare a 14-question answer-quality benchmark covering factual, multi-part, multi-document, insufficient-evidence, and out-of-scope cases.")
    bullet(doc, "Evaluate the student-facing QA pipeline, not only raw LLM generation, whenever an answer-quality test is run.")
    bullet(doc, "Record live chatbot observations honestly, without inventing transcripts, citation lists, or missing metric values.")
    bullet(doc, "Keep unlabeled cases unlabeled, and keep unavailable metrics as null rather than zero.")
    heading(doc, "1.3 Non-objectives", 2)
    bullet(doc, "RAGAS was not installed and was not executed.")
    bullet(doc, "The empty RAG template rag_eval_dataset.json was not filled with labeled cases.")
    bullet(doc, "The pending answer-quality dataset remains evaluation_ready=false and unlabeled.")
    bullet(doc, "No combined accuracy is reported across retrieval, classification, and QA, because those populations differ.")
    bullet(doc, "Production code, production Chroma, and Heroku were not modified for this documentation task.")


def chapter_2(doc):
    heading(doc, "2. System Evaluation Overview", 1)
    body(
        doc,
        "ASKa-Piyu’s student path is a RAG pipeline. Classification, retrieval, and generation are coupled in "
        "production but evaluated as separate components because each has its own gold labels, failure modes, and metrics.",
    )
    heading(doc, "2.1 Three evaluation areas", 2)
    add_table(
        doc,
        ["Area", "What it measures", "Why a separate method is required", "Primary gold"],
        [
            [
                "Retrieval",
                "Whether relevant document chunks appear in the top-k ranked results",
                "A correct later answer can still rest on a missed source; a fluent wrong answer can rest on a retrieved source. Ranked retrieval needs relevance IDs, not class labels.",
                "Human-reviewed relevant_ids and graded_relevance on 12 queries",
            ],
            [
                "Classification",
                "Whether questions and chunks are assigned the intended taxonomy subcategory",
                "Classification is a closed-label decision used for retrieval boosts and ticket routing. Accuracy, precision, recall, and F1 apply; Hit@K does not.",
                "Dual independent AI agreement (not human gold)",
            ],
            [
                "QA answer quality",
                "Whether the student-facing answer is correct, complete, and cited",
                "The displayed answer includes gating, fallbacks, table handling, and citation display that generate_groq_answer() alone does not perform.",
                "Human-approved references for a subset; two live human judgments",
            ],
        ],
        caption="Table 1. Three evaluation areas and why they are not interchangeable.",
    )
    heading(doc, "2.2 How the components connect in the RAG pipeline", 2)
    body(
        doc,
        "Incoming questions are classified by classify_question() using rules and taxonomy similarity only "
        "(no LLM). Document chunks are classified at ingest by classify_chunk(), which may call an LLM if "
        "rule and similarity confidence is low. KnowledgeBaseStore.search() embeds the expanded query with "
        "intfloat/multilingual-e5-small, queries ChromaDB, and applies a rule-based reranker. "
        "answer_qa_question() then selects context, generates or recovers an answer, and builds student-visible citations.",
    )
    heading(doc, "2.3 Overall evaluation workflow", 2)
    flowchart(
        doc,
        [
            "  University PDFs  -->  chunking / ingest  -->  Chroma collection",
            "                                              (eval: aska_evaluation, 691 chunks)",
            "                                                       |",
            "Student question                                       |",
            "     |                                                 v",
            "     +--> classify_question()  (rules + similarity; no LLM)",
            "     |                                                 |",
            "     +--> KnowledgeBaseStore.search()                  |",
            "     |       embed query  -->  Chroma cosine search    |",
            "     |       --> rule-based rerank_chunks()            |",
            "     |                                                 |",
            "     +--> answer_qa_question()                         |",
            "            context selection, LLM or fallback,        |",
            "            citation display                           |",
            "                                                       |",
            "  EVALUATION TRACKS (separate gold, separate metrics)  |",
            "     1. Retrieval: labeled relevant_ids vs ranked IDs  |",
            "     2. Classification: true_label vs predicted subcategory",
            "     3. QA: reference answers / live human judgments   |",
            "                                                       |",
            "  Reporting rule: do not average the three tracks into |",
            "  one system accuracy score.                           |",
        ],
        "Figure 1. ASKa-Piyu RAG pipeline and the three evaluation tracks.",
    )
    heading(doc, "2.4 Isolated evaluation corpus", 2)
    body(
        doc,
        "The November 2026 retrieval and QA preparation work uses an isolated local index, "
        "backend/data/chroma_evaluation, collection aska_evaluation, with 691 chunks. Those labels "
        "must not be scored against production Chroma. LabeledRetrievalStore opens only that isolated index.",
    )


def chapter_3(doc):
    heading(doc, "3. Retrieval Evaluation", 1)
    body(
        doc,
        "Retrieval evaluation asks a ranked-search question: given a student query, does a relevant chunk "
        "appear among the top results? Two retrieval studies exist in the repository. They use different "
        "corpora, different gold definitions, and different k. Their scores must not be merged.",
    )
    heading(doc, "3.1 How the human-reviewed retrieval dataset was created", 2)
    body(
        doc,
        "The current labeled retrieval set is retrieval_relevance_dataset.json, version "
        "2026-11-04-v2-human-reviewed-rag-benchmark-q1-q12. It contains 12 labeled queries and 0 unlabeled queries. "
        "Question text came from the known-answer RAG benchmark. Candidate chunks were taken from the 691-record "
        "extraction artifact chroma_record_extraction_20261104T104214Z.json and cross-checked against "
        "rag_benchmark_candidate_review_20261104T104800Z.json. A human assigned relevant_ids and graded_relevance. "
        "No label in this file is model-generated.",
    )
    body(
        doc,
        "The grading scale is 3 = highly relevant / directly answers; 2 = relevant supporting information; "
        "1 = partially relevant, incomplete, or superseded; 0 = irrelevant (omitted from relevant_ids). "
        "Hit@K, MRR, Precision@K, and Recall@K use binary relevance (grade > 0). nDCG@K uses the graded scores.",
    )
    add_table(
        doc,
        ["Query ID", "Question", "No. of relevant IDs"],
        [
            ["rag_benchmark_01", "How much does it cost to get a copy of my Transcript of Records?", "1"],
            ["rag_benchmark_02", "How much is the fee for a second copy of my diploma?", "1"],
            ["rag_benchmark_03", "Which office handles student enrollment?", "1"],
            ["rag_benchmark_04", "How much does it cost to drop a subject?", "2"],
            ["rag_benchmark_05", "What is the fee for library circulation service if my book is overdue?", "1"],
            ["rag_benchmark_06", "How long does the LSPU entrance examination take, including orientation?", "1"],
            ["rag_benchmark_07", "What is the process for validating my student ID?", "1"],
            ["rag_benchmark_08", "What happens if I fail more than 75% of my units?", "2"],
            ["rag_benchmark_09", "How is faculty teaching load determined?", "3"],
            ["rag_benchmark_10", "What are the responsibilities of an LSPU faculty member?", "2"],
            ["rag_benchmark_11", "What is honorable dismissal for a student?", "2"],
            ["rag_benchmark_12", "Who is the current LSPU president?", "2"],
        ],
        caption="Table 2. Twelve human-reviewed retrieval queries.",
    )
    body(
        doc,
        "Two documented source issues remain in the labels. rag_benchmark_04 has two real dropping-fee schedules "
        "(Charter P30 versus Handbook P20/unit); the Charter chunk is grade 3 and the Handbook chunk is grade 1. "
        "rag_benchmark_05 is graded 1 because the extracted fee text is truncated (“2 pesos per”) with the unit missing.",
    )
    heading(doc, "3.2 How embeddings and ChromaDB retrieve chunks", 2)
    body(
        doc,
        "The embedding model is intfloat/multilingual-e5-small, selected through get_embedding_function() in "
        "app/services/embeddings.py. The default local backend is E5EmbeddingFunction. "
        "current_embedding_model_label() reports this as “sentence-transformers: intfloat/multilingual-e5-small”.",
    )
    body(
        doc,
        "KnowledgeBaseStore.search() in chroma_store.py expands the query with prepare_retrieval_query(), "
        "embeds the expanded text, and calls collection.query() with cosine distances. Distance is converted to "
        "similarity as 1 − distance and stored as original_score. The store then calls rerank_chunks(). "
        "Chunk identity for evaluation is document_id::chunk_index, matching labeled relevant_ids.",
    )
    body(
        doc,
        "The encoder is weakly discriminative on this corpus. The RetrievedChunk documentation records that a "
        "highly relevant chunk may score about 0.87 and an unrelated chunk about 0.80. Similarity alone is therefore "
        "used for candidate generation, not as an absolute “is this good evidence?” threshold. Ranking after the "
        "heuristic reranker is what Hit@K actually scores.",
    )
    heading(doc, "3.3 How the reranker works", 2)
    body(
        doc,
        "The reranker in retrieval_reranker.py is rule-based query expansion plus heuristic boosting. It is not a "
        "second trained embedding model. Evaluation compares two orderings of the same candidate pool from one "
        "search call: embedding-only (sorted by vector_similarity) versus the reranked list. That comparison is "
        "implemented in evaluation_service.evaluate_retrieval().",
    )
    heading(doc, "3.4 How Hit@K is calculated", 2)
    body(
        doc,
        "evaluate_retrieval() in retrieval_metrics.py is a pure function. For each query it inspects the top-k "
        "retrieved IDs. Hit@K is 1 if at least one gold relevant_id appears in those k results, else 0. The reported "
        "Hit@K is the mean over queries, rounded to four decimals. Queries with empty relevant_ids are rejected "
        "rather than scored as zero.",
    )
    heading(doc, "3.5 Frozen 12-query baseline (November 2026)", 2)
    body(
        doc,
        "The frozen local baseline is retrieval_benchmark_20261104T121208Z.json, reproduced exactly by "
        "retrieval_benchmark_20261104T124417Z.json. Corpus: 691 chunks. Embedding: intfloat/multilingual-e5-small. "
        "Top-K: 5. Candidate pool: 20. Labeled queries: 12. Unlabeled: 0.",
    )
    add_table(
        doc,
        ["Metric", "Embedding only", "With reranker", "Change"],
        [
            ["Hit@5", "0.8333", "0.9167", "+0.0834"],
            ["MRR", "0.6875", "0.8125", "+0.1250"],
            ["Precision@5", "0.2500", "0.2333", "−0.0167"],
            ["Recall@5", "0.8056", "0.8056", "0.0000"],
            ["nDCG@5", "0.6871", "0.7812", "+0.0941"],
        ],
        caption="Table 3. Frozen 12-query retrieval baseline on chroma_evaluation (691 chunks).",
    )
    add_table(
        doc,
        ["ID", "Embedding Hit@5", "Reranker Hit@5"],
        [
            ["Q1 TOR fee", "Yes", "Yes"],
            ["Q2 Second copy of diploma", "Yes", "Yes"],
            ["Q3 Enrollment office", "No", "Yes"],
            ["Q4 Dropping fee", "Yes", "Yes"],
            ["Q5 Library overdue fee", "Yes", "Yes"],
            ["Q6 Entrance examination duration", "Yes", "Yes"],
            ["Q7 Student ID validation", "Yes", "Yes"],
            ["Q8 Fail more than 75% of units", "Yes", "Yes"],
            ["Q9 Faculty teaching load", "Yes", "Yes"],
            ["Q10 Faculty responsibilities", "No", "No"],
            ["Q11 Honorable dismissal", "Yes", "Yes"],
            ["Q12 Current university president", "Yes", "Yes"],
        ],
        caption="Table 4. Per-query Hit@5 on the human-reviewed set.",
    )
    body(
        doc,
        "Interpretation: on this 12-question set the reranker improved Hit@5 from 10/12 to 11/12, and improved "
        "MRR and nDCG@5. Recall@5 was unchanged, so the reranker reordered candidates already in the pool rather "
        "than finding new relevant chunks. Precision@5 fell slightly because boosting can promote additional "
        "non-relevant neighbors. Q10 (faculty responsibilities) missed in both rankings. These figures are a "
        "retrieval baseline, not production-wide accuracy and not answer quality.",
    )
    heading(doc, "3.6 Phase 2A expansion benchmark (Hit@1 = 0.90, Hit@3 = 1.00)", 2)
    body(
        doc,
        "An earlier retrieval study is preserved in benchmarks/results/phase2a_retrieval_expansion.json "
        "(generated 2026-09-06). It evaluated query-expansion and named-service boosts on 20 in-scope cases "
        "against collection aska_knowledge_base (750 chunks recorded in that file). Gold in that study is "
        "expected/acceptable section titles, not the later document_id::chunk_index labels.",
    )
    add_table(
        doc,
        ["Condition", "n", "Hit@1", "Hit@3", "Hit@5", "MRR"],
        [
            ["Full pipeline (expansion + boosts)", "20", "0.90", "1.00", "1.00", "0.9333"],
            ["No expansion", "20", "0.90", "0.95", "0.95", "0.9250"],
            ["No named-service boosts", "20", "0.85", "1.00", "1.00", "0.9000"],
        ],
        caption="Table 5. Phase 2A retrieval-expansion results (title-match gold; 20 cases).",
    )
    body(
        doc,
        "Hit@1 = 0.90 means 18 of 20 queries placed an expected or acceptable title in rank 1. Hit@3 = 1.00 "
        "means every one of those 20 queries had such a title in the top three. These numbers are retained as "
        "reported Phase 2A results. They are not the same experiment as the 12-query human-reviewed Hit@5 baseline "
        "and must not be rewritten as 12-query Hit@1/Hit@3.",
    )
    heading(doc, "3.7 Retrieval pipeline as implemented", 2)
    flowchart(
        doc,
        [
            "query text",
            "    |",
            "    v",
            "prepare_retrieval_query()     # expansion rules, matched_expansion_rules",
            "    |",
            "    v",
            "embed expanded query          # intfloat/multilingual-e5-small",
            "    |",
            "    v",
            "Chroma collection.query()     # cosine distance; n_results = candidate pool",
            "    |",
            "    v",
            "RetrievedChunk.original_score = 1 - distance",
            "    |",
            "    v",
            "rerank_chunks()               # heuristic boosts, not a trained model",
            "    |",
            "    +--> embedding-only ranking: sort by vector_similarity",
            "    +--> reranked ranking: store.search() order",
            "    |",
            "    v",
            "evaluate_retrieval(results, k)",
            "    Hit@K / MRR / P@K / R@K / nDCG@K versus relevant_ids",
        ],
        "Figure 2. Retrieval pipeline actually used by evaluation_service.evaluate_retrieval().",
    )


def chapter_4(doc):
    heading(doc, "4. Classification Evaluation", 1)
    body(
        doc,
        "Classification assigns a taxonomy subcategory to a student question or a stored chunk. It supports "
        "retrieval boosting and ticket routing. It is not a substitute for retrieval relevance or answer correctness.",
    )
    heading(doc, "4.1 Dataset preparation", 2)
    body(
        doc,
        "classification_eval_dataset.json version 2026-11-04-v2-independent-ai-annotation-dual-agreement contains "
        "65 labeled cases: 37 classify_question and 28 classify_chunk. Labels are dual independent AI annotations, "
        "not human gold. ANNOTATION_METHODOLOGY.md states this limitation explicitly and it must be repeated in "
        "the thesis whenever these metrics are cited.",
    )
    body(
        doc,
        "Ninety-six real candidates (49 questions, 47 chunks) were drawn from project files and the Chroma "
        "extraction. Two independent AI passes wrote reviewer1_annotations.json and reviewer2_annotations.json. "
        "promote_agreed_labels.py promoted a row only when both assigned the same subcategory, both marked "
        "evidence_sufficient=true, and neither used MARK_FOR_REVIEW. Dual-AI auto-accepted: 65. Flagged and not "
        "promoted: 31 (25 mark-for-review / out-of-scope / insufficient; 6 disagreements).",
    )
    add_table(
        doc,
        ["Item", "Count"],
        [
            ["Candidate pool", "96"],
            ["Promoted after dual-AI agreement", "65"],
            ["classify_question cases", "37"],
            ["classify_chunk cases", "28"],
            ["Held out (not in eval JSON)", "31"],
        ],
        caption="Table 6. Classification labeling coverage.",
    )
    heading(doc, "4.2 Question classification", 2)
    body(
        doc,
        "classify_question() in knowledge_taxonomy.py never calls an LLM. A second LLM call on the student "
        "ask path was observed to queue long enough to trip the Flutter timeout. The function therefore uses "
        "rule-based keyword scoring, then cosine similarity against taxonomy descriptors, and returns the better "
        "of the two. Evaluation compares the predicted subcategory with true_label.",
    )
    add_table(
        doc,
        ["Component", "Cases", "Accuracy", "Macro F1", "Label source"],
        [
            ["classify_question", "37", "70.27% (0.7027)", "0.5064", "Dual AI agreement, not human gold"],
        ],
        caption="Table 7. Question-classification result from local run 6b1ec340-d32a-4bbc-8963-9f7ec856dc14.",
    )
    body(
        doc,
        "Accuracy of 70.27% means 26 of 37 questions received the agreed subcategory. Macro F1 of 0.5064 is "
        "materially lower, which indicates uneven per-class performance: majority classes can lift accuracy while "
        "rare subcategories are missed. That pattern is expected on a 37-case, multi-class, class-imbalanced set.",
    )
    heading(doc, "4.3 Chunk classification", 2)
    body(
        doc,
        "classify_chunk() uses three stages. First, _rule_based_classification() scores keyword and name hits. "
        "If confidence is at least the rule threshold, it returns immediately. Otherwise "
        "_taxonomy_similarity_classification() computes cosine similarity between the chunk term vector and each "
        "taxonomy descriptor. If the better of rule and similarity is still below the low-confidence threshold and "
        "allow_llm is true, _llm_classification() asks the configured LLM to return one taxonomy entry as JSON. "
        "If the LLM call fails, the function returns the best non-LLM result. allow_llm=False skips the LLM, which "
        "is required for large ingest jobs.",
    )
    add_table(
        doc,
        ["Component", "Cases", "Accuracy", "Macro F1", "Note"],
        [
            ["classify_chunk allow_llm=True", "28", "64.29% (0.6429)", "0.5345", "LLM call returned HTTP 401"],
            ["classify_chunk allow_llm=False", "28", "64.29% (0.6429)", "0.5345", "Rules + similarity only"],
        ],
        caption="Table 8. Chunk-classification results. Identical scores are not an LLM ablation finding.",
    )
    heading(doc, "4.4 OpenRouter HTTP 401 and the LLM-on/off comparison", 2)
    body(
        doc,
        "The local evaluation run attempted classify_chunk twice, with allow_llm=True and allow_llm=False, to "
        "compare LLM-assisted classification against rules and similarity. The Groq/OpenRouter call returned "
        "HTTP 401 Unauthorized, so classify_chunk fell back to rules and similarity in both modes. The identical "
        "scores (64.29% accuracy, 0.5345 macro F1) therefore do not measure the contribution of successful LLM "
        "classification. They measure the non-LLM fallback twice. This is an environment limitation, not a finding "
        "that the LLM adds nothing.",
    )
    heading(doc, "4.5 Classification pipeline as implemented", 2)
    flowchart(
        doc,
        [
            "text (question or chunk)",
            "    |",
            "    v",
            "_rule_based_classification()     # keyword / name hits -> confidence",
            "    |",
            "    +-- if confidence high --> return subcategory",
            "    |",
            "    v",
            "_taxonomy_similarity_classification()   # cosine vs taxonomy descriptors",
            "    |",
            "classify_question: always stop here (never LLM)",
            "classify_chunk:",
            "    |",
            "    +-- if confidence enough OR allow_llm=False --> return best non-LLM",
            "    |",
            "    v",
            "_llm_classification()            # JSON taxonomy pick; None on HTTP/parse failure",
            "    |",
            "    +-- 401 / timeout / invalid JSON --> return best non-LLM result",
            "    v",
            "evaluate_classification(y_true, y_pred)",
            "    accuracy, macro/weighted P/R/F1, per-class rows, confusion matrix",
        ],
        "Figure 3. Question and chunk classification as implemented in knowledge_taxonomy.py.",
    )
    heading(doc, "4.6 Implications", 2)
    bullet(doc, "These metrics may be reported as dual-AI-label evaluation results. They must not be described as human-validated.")
    bullet(doc, "Coverage is incomplete: 31 of 96 candidates have no approved label.")
    bullet(doc, "Index metadata category stamps were not used as true_label.")
    bullet(doc, "Retrieval relevant_ids were not used as classification labels.")
    bullet(doc, "Do not claim an LLM-versus-rules ablation from the identical chunk scores.")


def chapter_5(doc):
    heading(doc, "5. Question-Answering Answer-Quality Evaluation", 1)
    body(
        doc,
        "Answer-quality evaluation asks whether the student sees a correct, usable answer with appropriate "
        "citations. It is the most incomplete of the three tracks. The 14-question set is prepared but not "
        "evaluation-ready. Two live production observations exist. The remaining cases are documented from "
        "reference material and evidence limits, not from measured chatbot outputs.",
    )
    heading(doc, "5.1 Why the full student-facing pipeline must be evaluated", 2)
    body(
        doc,
        "The admin evaluation orchestrator evaluate_rag_components() calls generate_groq_answer() on retrieved "
        "context. That is useful for measuring raw generation given a context string, but it is not the student "
        "path. Students hit FastAPI /qa/ask, which calls answer_qa_question(). That function adds greeting and "
        "out-of-scope short-circuits, follow-up resolution, multi-query retrieval, facet coverage, audience "
        "filtering, typed extractive answers, table-inversion correction, conversational fallback when the LLM "
        "fails, and student-visible citation selection. Evaluating generate_groq_answer() alone omits those steps.",
    )
    body(
        doc,
        "The pending dataset therefore records intended_future_evaluation.target_function as "
        "app.services.qa.question_answering.answer_qa_question, against the isolated 691-chunk evaluation corpus, "
        "not production Chroma. rag_eval_dataset.json remains an empty labeled template "
        "(version 2026-11-04-v1-empty-template, 0 cases).",
    )
    heading(doc, "5.2 How answer_qa_question() works", 2)
    body(
        doc,
        "answer_qa_question(question, user_role=..., history=...) returns a QAResult containing the answer text, "
        "sources, confidence, retrieved-chunk debug rows, fallback flags, and citation_status. Processing sequence:",
    )
    bullet(doc, "Normalize the question. Validate any client_active_service against the taxonomy.")
    bullet(doc, "Greeting queries return a fixed greeting and never retrieve or cite.")
    bullet(doc, "resolve_followup_question() and resolve_turn_active_topic() rewrite slot follow-ups using history.")
    bullet(doc, "Out-of-scope intent returns a refusal without retrieval.")
    bullet(doc, "Faculty-restricted topics are hidden from the student role.")
    bullet(doc, "Underspecified questions without an active topic ask the student to name the service.")
    bullet(doc, "Otherwise the function multi-query retrieves via get_knowledge_base_store().search(), restores missing facets, and formats context.")
    bullet(doc, "If retrieval quality is too weak, it asks for clarification and returns no citations.")
    bullet(doc, "A typed extractive answer may be used for form/requirement cards without calling the LLM.")
    bullet(doc, "Otherwise generate_groq_answer() is called with the selected context, grounding notes, and active topic.")
    bullet(doc, "If the generated answer contradicts structured table records, the table evidence is substituted.")
    bullet(doc, "On GroqAnswerError, conversational or recovered charter fallback is used; fallback_used is true.")
    bullet(doc, "_display_sources_for_answer() selects student-visible citations (lexical V1 or LLM verifier, depending on settings).")
    heading(doc, "5.3 QA generation pipeline as implemented", 2)
    flowchart(
        doc,
        [
            "HTTP /qa/ask  (FastAPI)  -->  answer_qa_question()",
            "    |",
            "    +-- greeting / OOS / faculty-hidden / underspecified --> return without LLM",
            "    |",
            "    v",
            "prepare_retrieval_query + multi-query store.search()",
            "    |",
            "select_context_chunks + facet restore + audience filter",
            "    |",
            "format_retrieved_context()     # the string actually given to the LLM",
            "    |",
            "    +-- typed extractive path --> skip LLM",
            "    |",
            "    v",
            "generate_groq_answer(question, context, history, grounding_notes)",
            "    |",
            "    +-- success --> optional table-inversion correction",
            "    +-- GroqAnswerError --> fallback / recovered charter answer",
            "    |",
            "    v",
            "_display_sources_for_answer()  --> student-visible citation_ids",
            "    |",
            "    v",
            "QAResult.answer + QAResult.sources",
        ],
        "Figure 4. Student-facing QA pipeline in question_answering.py.",
    )
    heading(doc, "5.4 Preparing the 14-question benchmark", 2)
    body(
        doc,
        "answer_quality_eval_dataset.pending_human_review.json version "
        "2026-11-04-v1-answer-quality-pending-human-review holds 14 unlabeled cases. Questions aq_01–aq_12 reuse "
        "the retrieval-set wording. aq_13 and aq_14 were added as out-of-scope and insufficient-evidence probes. "
        "Retrieval relevant_ids were not copied as gold citations. SHA-256: "
        "D7CDD2EC2CCE20A176FBA7B07B70C6206E7AABF4F36FD8D3C5BC8BD1677E2905. evaluation_ready remains false.",
    )
    body(
        doc,
        "Each case stores case_id, question, case_type, labeling_status, review_status, proposed_reference_answer "
        "(null when evidence is insufficient), supporting_passages, and optionally gold_citation_ids. Required facts "
        "for scoring exist in the subset runner for aq_04 and aq_08 only; they are not a labeled dataset field for all 14.",
    )
    heading(doc, "5.5 Five detailed evidence reviews", 2)
    body(
        doc,
        "Phases 2B–2F prepared evidence packs and decisions for five cases. Reference-answer approval (Phase 2D) "
        "and citation-review decisions (Phase 2F, later gold assignment for two cases) are separate steps.",
    )
    add_table(
        doc,
        ["Case", "Reference-answer decision", "Citation decision", "Gold citation IDs assigned?"],
        [
            [
                "aq_01 TOR fee",
                "Approved: undergraduate ₱75.00/page and graduate ₱150.00/page. Exclude certifications, diploma, and OCR P137.",
                "Candidate ::1 retained; usability unresolved (mixed fees; incomplete viewer range).",
                "No",
            ],
            [
                "aq_04 Dropping fee",
                "Approved conflict-aware answer: Charter ₱30.00/unit vs Handbook ₱20.00/unit; confirm with Registrar.",
                "Accept both ::97 and ::82. Do not choose a winning rate.",
                "Yes (both IDs)",
            ],
            [
                "aq_08 Fail >75%",
                "Approved: preserve “more than 75%” vs “75% or more”; nine-unit contexts; INC exclusion; college dismissal vs university disqualification.",
                "Accept ::67 and ::69. Exclude ::66 (warning/probation only).",
                "Yes (::67 and ::69)",
            ],
            [
                "aq_10 Faculty responsibilities",
                "Approved summary of Faculty Manual Section III.A. Code of Ethics excluded.",
                "Hold ::8: body relevant, but title, page metadata, and PDF viewer destination are wrong.",
                "No",
            ],
            [
                "aq_12 Current president",
                "Reference answer kept JSON null. 2021 lists name Dr. Mario R. Briones but do not establish who is president in 2026.",
                "Insufficient evidence; assign no gold citations.",
                "No",
            ],
        ],
        caption="Table 9. Decisions for the five evidence-reviewed QA cases.",
    )
    heading(doc, "5.6 Assessment basis used in this chapter", 2)
    body(
        doc,
        "The 14 questions are presented as one evaluation overview. Each row has an explicit assessment basis so "
        "reference-based review is not mistaken for a measured live chatbot output.",
    )
    add_table(
        doc,
        ["Assessment basis", "Meaning", "n"],
        [
            [
                "Live production observation",
                "A human judged the deployed chatbot’s answer. Verbatim transcripts were not stored; the supplied observations are used without reconstruction.",
                "2",
            ],
            [
                "Reference-based review",
                "The question, available reference material, and citation status are documented. No live chatbot answer was collected, and no correctness score is invented.",
                "8",
            ],
            [
                "Not scored",
                "The case is insufficient-evidence or out-of-scope on the current corpus. No factual-correctness score is assigned.",
                "4",
            ],
        ],
        caption="Table 10. Assessment bases for the 14-question overview.",
    )
    heading(doc, "5.7 Fourteen-question evaluation overview", 2)
    add_table(
        doc,
        ["ID", "Question", "Scenario", "Assessment basis", "Finding"],
        [
            ["aq_01", "How much does it cost to get a copy of my Transcript of Records?", "Direct factual", "Reference-based review", "Approved undergraduate/graduate TOR rates. Live output not measured. Citation gold unresolved."],
            ["aq_02", "How much is the fee for a second copy of my diploma?", "Direct factual", "Reference-based review", "Draft: second copy of diploma P100.00. Pending PDF confirmation. Live output not measured."],
            ["aq_03", "Which office handles student enrollment?", "Direct factual", "Reference-based review", "Draft: Office of the Registrar. Pending PDF confirmation. Live output not measured."],
            ["aq_04", "How much does it cost to drop a subject?", "Multi-document", "Live production observation", "Satisfactory. The live answer stated P30.00 and provided a procedure. Citations pending verification."],
            ["aq_05", "What is the fee for library circulation service if my book is overdue?", "Insufficient evidence", "Not scored", "Extraction reads “2 pesos per” with the unit missing; “overdue” is absent from the 691-chunk corpus."],
            ["aq_06", "How long does the LSPU entrance examination take, including orientation?", "Multi-part", "Reference-based review", "Draft: orientation 15 minutes; examination 1.5 hours. Combined total must not be invented. Live output not measured."],
            ["aq_07", "What is the process for validating my student ID?", "Direct factual", "Reference-based review", "Draft: OSAS ID validation, three steps, 4 minutes, no fee. Live output not measured."],
            ["aq_08", "What happens if I fail more than 75% of my units?", "Multi-part", "Live production observation", "Unsatisfactory. The live answer returned fragmented table content and did not clearly state the consequence. Citations pending verification."],
            ["aq_09", "How is faculty teaching load determined?", "Multi-part", "Reference-based review", "Draft: Dean assigns loads; 40 service hours; 18-hour teaching maximum. Live output not measured."],
            ["aq_10", "What are the responsibilities of an LSPU faculty member?", "Direct factual", "Reference-based review", "Approved Faculty Manual commitments summary. Citation gold held (wrong title/page/viewer). Live output not measured."],
            ["aq_11", "What is honorable dismissal for a student?", "Multi-part", "Reference-based review", "Draft: voluntary withdrawal with Registrar consent and listed conditions. Live output not measured."],
            ["aq_12", "Who is the current LSPU president?", "Multi-document", "Not scored", "Dated 2021 lists name Dr. Mario R. Briones but do not establish the 2026 president. Reference answer is null."],
            ["aq_13", "What is the weather on Mars tomorrow?", "Out of scope", "Not scored", "Refusal-behavior probe; no LSPU reference answer. No live refusal test was run."],
            ["aq_14", "What is the LSPU student Wi-Fi password?", "Insufficient evidence", "Not scored", "No Wi-Fi password passage exists in the evaluation corpus. No password is invented."],
        ],
        fills=[
            REF_FILL, REF_FILL, REF_FILL, LIVE_FILL, NS_FILL,
            REF_FILL, REF_FILL, FAIL_FILL, REF_FILL, REF_FILL,
            REF_FILL, NS_FILL, NS_FILL, NS_FILL,
        ],
        caption="Table 11. Complete 14-question QA overview. Green = live satisfactory; red = live unsatisfactory; blue = reference-based review; gray = not scored.",
    )
    heading(doc, "5.8 Live production observations", 2)
    body(
        doc,
        "Only aq_04 and aq_08 were judged on the deployed chatbot. These are the only live answer-correctness "
        "results. Citation titles, pages, and displayed chunk IDs were not captured, so citation precision and "
        "recall remain pending (null, not zero). Full verbatim wording was not stored; the observations below are "
        "the supplied human judgments without reconstructed transcripts.",
    )
    heading(doc, "5.8.1 aq_04 — Dropping of Subjects fee", 3)
    body(doc, "Question: How much does it cost to drop a subject?")
    body(
        doc,
        "Live observation: the chatbot stated the Dropping of Subjects fee as P30.00 and provided the procedure "
        "and estimated processing time. Answer correctness: satisfactory (PASS). Citation verification: pending.",
    )
    body(
        doc,
        "Approved reference (not the live answer): official sources list two dropping fees and do not establish "
        "which amount is currently in force. The Citizen’s Charter 2026 lists ₱30.00 per unit for new and transferee "
        "students. The Student Handbook 2021 requires ₱20.00 per unit, citing LSPU BOR Resolution 1046, s.2012. "
        "Confirm with the Registrar before paying. The live judgment treated Charter P30.00 plus procedure as "
        "satisfactory; the approved reference is conflict-aware. That distinction is recorded, not collapsed.",
    )
    body(
        doc,
        "Approved gold citation IDs, not verified against the live display: "
        "da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97 and cec01713-c1ba-4061-9404-ffaa1d8e70dd::82.",
    )
    heading(doc, "5.8.2 aq_08 — Failing more than 75 percent of units", 3)
    body(doc, "Question: What happens if I fail more than 75% of my units?")
    body(
        doc,
        "Live observation: the chatbot returned fragmented table content and did not clearly explain the "
        "consequence of failing more than 75% of academic units. Answer correctness: unsatisfactory (FAIL). "
        "No policy consequence was invented. Citation verification: pending.",
    )
    body(
        doc,
        "Approved reference (not the live answer): Handbook Section 4.3 uses “more than 75%” and dismissal from "
        "the College, with an incomplete-grade exclusion and a nine-unit exemption. The scholastic-delinquency table "
        "uses “75% or more” and lists 100% as permanent disqualification from the University. The exact-75% case is "
        "unresolved. Gold IDs: cec01713-c1ba-4061-9404-ffaa1d8e70dd::67 and ::69. Gold excludes ::66.",
    )
    heading(doc, "5.9 Reference-based case reviews", 2)
    body(
        doc,
        "The eight cases below have prepared questions and, in most cases, draft or approved reference answers. "
        "They are not live tests. No chatbot answer, citation list, or numeric correctness score is reported for them.",
    )
    details = [
        ("aq_01", "Approved reference: TOR costs ₱75.00 per page (undergraduate) and ₱150.00 per page (graduate) per Citizen’s Charter 2026. Citation gold unresolved because candidate ::1 mixes fee categories."),
        ("aq_02", "Draft reference pending PDF confirmation: second copy of diploma P100.00 on the Registrar fee card. Citation gold not assigned."),
        ("aq_03", "Draft reference pending PDF confirmation: Enrollment service lists Office / Division: Registrar. Citation gold not assigned."),
        ("aq_06", "Draft reference pending PDF confirmation: orientation 15 minutes; examination proper 1 and 1/2 hours; fees none. Total Processing Time is recorded as Not specified, so a combined official duration is not invented."),
        ("aq_07", "Draft reference pending PDF confirmation: OSAS ID validation requires a Certificate of Registration and a Student ID; three steps; fees none; total processing time 4 minutes."),
        ("aq_09", "Draft reference pending PDF confirmation: Dean / Associate Dean assign loads in the field of specialization; 40 service hours exclusive of lunch; 18-hour maximum teaching load with listed exceptions."),
        ("aq_10", "Approved reference: Faculty Manual 2020 Section III.A commitments. Citation gold held because candidate ::8 has a relevant body but wrong title, page metadata, and viewer destination."),
        ("aq_11", "Draft reference pending PDF confirmation: honorable dismissal is voluntary withdrawal with the Registrar’s consent, with petition, indebtedness, good standing, non-readmission, and disciplinary exclusions."),
    ]
    for case_id, text in details:
        bullet(doc, f"{case_id}: {text}")
    heading(doc, "5.10 Cases not scored", 2)
    bullet(doc, "aq_05: Charter extraction shows “2 pesos per” with the unit missing. The word “overdue” does not appear in the 691-chunk corpus.")
    bullet(doc, "aq_12: 2021 manuals name Dr. Mario R. Briones but do not establish who is president in 2026. proposed_reference_answer is JSON null.")
    bullet(doc, "aq_13: Out-of-scope probe. Eventual scoring should be refusal behavior, not handbook correctness. No live refusal test was run.")
    bullet(doc, "aq_14: No Wi-Fi password passage exists in the evaluation corpus. No password is invented.")
    heading(doc, "5.11 Local subset run that is not a live result", 2)
    body(
        doc,
        "run_approved_subset_eval.py called answer_qa_question() against chroma_evaluation for aq_04 and aq_08. "
        "Local OpenRouter returned HTTP 401, so both cases used generation-error fallback. Retrieval and lexical "
        "citations in that folder are real, but the answers are fallbacks, not Groq generations and not live "
        "production answers. Those fallback scores are not used as the live findings in Table 11. Faithfulness in "
        "that run is null because the verifier also received 401. RAGAS was not used.",
    )
    heading(doc, "5.12 Supported QA metrics", 2)
    add_table(
        doc,
        ["Metric", "Live aq_04 / aq_08", "Other 12 cases", "14-question aggregate"],
        [
            ["Answer correctness (human pass/fail)", "1 satisfactory, 1 unsatisfactory", "Not measured", "Not calculated"],
            ["Citation set precision", "Pending", "Not measured", "Not calculated"],
            ["Citation set recall", "Pending", "Not measured", "Not calculated"],
            ["Faithfulness / claim support", "Unavailable", "Unavailable", "Unavailable"],
            ["RAGAS scores", "Not executed", "Not executed", "Not executed"],
        ],
        caption="Table 12. QA metrics that exist versus metrics that remain unavailable.",
    )


def chapter_6(doc):
    heading(doc, "6. Implementation of the Evaluation Code", 1)
    body(
        doc,
        "This chapter explains the modules the evaluation actually uses. File paths are relative to the backend package.",
    )
    heading(doc, "6.1 Evaluation orchestrator", 2)
    body(
        doc,
        "app/services/evaluation/evaluation_service.py is the only evaluation module that performs I/O against "
        "live components. run_evaluation() loads the three JSON datasets, evaluates classification, retrieval, and "
        "RAG groups independently, and converts an unexpected exception in one group into FAILED placeholders so "
        "the other groups are not discarded. It never writes to Chroma. Persistence is a separate step.",
    )
    body(
        doc,
        "Important functions: evaluate_classify_chunk(dataset, allow_llm=...), evaluate_classify_question(dataset), "
        "evaluate_retrieval(dataset, store=..., k=5, candidate_pool_size=20), evaluate_rag_components(dataset, store=...), "
        "and run_evaluation(). Inputs are DatasetLoadResult objects. Outputs are ComponentEvaluationResult records "
        "with status evaluated, not_evaluable, or failed.",
    )
    body(
        doc,
        "evaluate_rag_components() currently calls generate_groq_answer(), not answer_qa_question(), and only "
        "on labeling_status=labeled cases in rag_eval_dataset.json. Because that file is empty, the production "
        "RAG evaluator is not evaluable. Answer-quality work therefore used a separate subset runner.",
    )
    heading(doc, "6.2 Dataset loading", 2)
    body(
        doc,
        "app/services/evaluation/datasets.py loads JSON objects with dataset_version and cases. Only cases with "
        "labeling_status=labeled are scored. Unlabeled cases are counted as skipped_unlabeled_count and are never "
        "treated as wrong. Missing required fields raise DatasetValidationError rather than being defaulted. Each "
        "load records a SHA-256 of the file bytes for reproducibility.",
    )
    heading(doc, "6.3 Metric modules", 2)
    bullet(doc, "retrieval_metrics.py: pure Hit@K, MRR, Precision@K, Recall@K, nDCG@K from ranked IDs and gold relevant_ids.")
    bullet(doc, "classification_metrics.py: accuracy and one-vs-rest precision, recall, and F1; macro and weighted averages.")
    bullet(doc, "confusion_matrix.py: label-by-label counts for the dashboard.")
    bullet(doc, "rag_metrics.py: aggregates RagCaseResult fields; unavailable values stay None. citation_metrics_from_outcome() returns None for all citation fields unless the verifier was invoked and succeeded.")
    bullet(doc, "performance_metrics.py: first-call-in-run versus warm latency from CallTracker evidence inside one run.")
    heading(doc, "6.4 Isolated retrieval store", 2)
    body(
        doc,
        "app/services/evaluation/labeled_retrieval_store.py opens data/chroma_evaluation / aska_evaluation "
        "(expected 691 chunks) with E5EmbeddingFunction. It exposes search() compatible with evaluate_retrieval() "
        "and never opens production Chroma. The November 2026 retrieval baseline used this index via "
        "run_retrieval_benchmark_local.py because /admin/evaluation/run would have searched the live store.",
    )
    heading(doc, "6.5 Persistence", 2)
    body(
        doc,
        "app/services/evaluation/persistence.py maps an EvaluationRunResult onto local evaluation_* tables. It is "
        "the only evaluation module that touches a database. It strips secret-like JSON keys before persistence and "
        "does not connect to Heroku Postgres.",
    )
    heading(doc, "6.6 Student-facing QA and generation", 2)
    body(
        doc,
        "app/services/qa/question_answering.py implements answer_qa_question() as described in Chapter 5. "
        "app/services/qa/groq_answer_service.py implements generate_groq_answer(), the LLM completion given a "
        "context string. app/services/qa/citation_verification.py implements verify_citations() in lexical or LLM "
        "mode. Evaluation of displayed citations for the subset run used lexical V1 because async_llm returns zero "
        "citations until a background job finishes.",
    )
    heading(doc, "6.7 Separate answer-quality subset runner", 2)
    body(
        doc,
        "benchmarks/evaluation/answer_quality_labeling/run_approved_subset_eval.py is not the production "
        "run_evaluation path. It patches get_knowledge_base_store() to the isolated index, calls "
        "answer_qa_question() for aq_04 and aq_08 only, scores required-fact coverage against the approved "
        "reference, and scores student-visible citation IDs against gold. It does not change labeling_status or "
        "evaluation_ready. The executed run aq_subset_20261104T163426Z is a generation-error fallback after "
        "OpenRouter 401 and is not a live production result.",
    )
    heading(doc, "6.8 Complete evaluation workflow from dataset to report", 2)
    flowchart(
        doc,
        [
            "1. Prepare / review labels",
            "     retrieval_relevance_dataset.json          (human, 12 queries)",
            "     classification_eval_dataset.json          (dual-AI agreement, 65 cases)",
            "     answer_quality pending JSON               (14 unlabeled; evaluation_ready=false)",
            "     rag_eval_dataset.json                     (empty labeled template)",
            "2. Choose the matching runner",
            "     retrieval  -> run_retrieval_benchmark_local.py / evaluate_retrieval()",
            "     classification -> run_evaluation() classify_* on labeled cases",
            "     QA student path -> run_approved_subset_eval.py or live UI observation",
            "     QA raw LLM path -> evaluate_rag_components() [not evaluable: 0 labeled RAG cases]",
            "3. Compute only supported metrics; store null when a judge/verifier did not run",
            "4. Persist or write run folders (raw_evidence, per_case_metrics, REPORT.md)",
            "5. Report by component and by population; do not pool unequal n into one accuracy",
        ],
        "Figure 5. Evaluation workflow from datasets to reported metrics.",
    )


def chapter_7(doc):
    heading(doc, "7. Datasets and Evaluation Artifacts", 1)
    body(
        doc,
        "Datasets were prepared, reviewed, used, and then left unchanged for this documentation task. "
        "The empty RAG template was left empty on purpose.",
    )
    add_table(
        doc,
        ["File", "Component", "Version / n", "Labeling method", "Purpose"],
        [
            [
                "evaluation/retrieval_relevance_dataset.json",
                "Retrieval",
                "2026-11-04-v2-human-reviewed-rag-benchmark-q1-q12; 12 labeled",
                "Human relevance review",
                "Gold relevant_ids and grades for Hit@K / MRR / nDCG",
            ],
            [
                "evaluation/classification_eval_dataset.json",
                "Classification",
                "2026-11-04-v2-independent-ai-annotation-dual-agreement; 65 labeled",
                "Dual independent AI agreement",
                "true_label for classify_question (37) and classify_chunk (28)",
            ],
            [
                "evaluation/rag_eval_dataset.json",
                "RAG / QA (production evaluator)",
                "2026-11-04-v1-empty-template; 0 cases",
                "None",
                "Empty labeled template; not filled",
            ],
            [
                "answer_quality_eval_dataset.pending_human_review.json",
                "QA answer quality",
                "2026-11-04-v1-answer-quality-pending-human-review; 14 unlabeled",
                "Human evidence review; still unlabeled",
                "Candidate benchmark; evaluation_ready=false",
            ],
            [
                "results/phase2a_retrieval_expansion.json",
                "Retrieval (earlier)",
                "phase2a-v1; 20 in-scope cases; 750 chunks recorded",
                "Expected/acceptable titles",
                "Hit@1=0.90, Hit@3=1.00 full-pipeline result",
            ],
            [
                "results/retrieval_benchmark_20261104T121208Z.json",
                "Retrieval baseline",
                "12 queries; 691 chunks",
                "Human relevant_ids",
                "Frozen Hit@5 0.8333 / 0.9167",
            ],
            [
                "results/retrieval_benchmark_20261104T124417Z.json",
                "Retrieval reproduction",
                "Same as frozen baseline",
                "Human relevant_ids",
                "Reproduced baseline exactly",
            ],
            [
                "classification_labeling/ANNOTATION_METHODOLOGY.md",
                "Classification process",
                "96 candidates; 65 promoted",
                "Dual AI",
                "Must-cite limitations for manuscript",
            ],
        ],
        caption="Table 13. Consolidated dataset inventory.",
    )
    add_table(
        doc,
        ["Artifact", "What it records", "Limitation"],
        [
            ["human_review/HUMAN_REVIEW_DECISIONS.md", "Phase 2C/2D reference-answer decisions", "Not gold until a later labeled promotion"],
            ["human_review/citation_review/CITATION_REVIEW_DECISIONS.md", "Phase 2F citation usability decisions", "Gold IDs later assigned only for aq_04 and aq_08"],
            ["runs/aq_live_prod_human_captured_20261104T164548Z/", "Live pass/fail for aq_04 and aq_08", "No verbatim transcript; citations pending"],
            ["runs/aq_live_prod_BLOCKED_20261104T164045Z/", "Live UI attempt blocked", "No answers fabricated"],
            ["runs/aq_subset_20261104T163426Z/", "Local answer_qa_question() fallback after 401", "Not live; not Groq-generated answers"],
            ["thesis_overview_2026-11-04/REPORT.md", "14-question overview narrative", "Does not mark the pending set evaluation-ready"],
        ],
        caption="Table 14. Supporting review and run artifacts.",
    )
    heading(doc, "7.1 How datasets were preserved", 2)
    body(
        doc,
        "Retrieval labels, classification labels, historical classification results, the pending QA file, gold "
        "citations already assigned, previous run folders, and rag_eval_dataset.json were not modified to produce "
        "this Word document. Documentation scripts write only into the thesis_overview folder.",
    )


def chapter_8(doc):
    heading(doc, "8. Metrics and Their Interpretation", 1)
    body(
        doc,
        "Only metrics that the code supports or that evaluation artifacts actually contain are defined here. "
        "RAGAS metrics are listed as not executed.",
    )
    add_table(
        doc,
        ["Metric", "Measures", "Calculation", "Used by", "High / low meaning", "Limitation"],
        [
            [
                "Hit@1 / Hit@3 / Hit@5",
                "Whether at least one relevant item is in the top k",
                "Mean of per-query indicators; k as specified",
                "Retrieval (Phase 2A uses 1 and 3; 12-query baseline uses 5)",
                "High: relevant chunk is near the top. Low: missed in top k.",
                "Does not measure answer wording. Different gold definitions across studies.",
            ],
            [
                "MRR",
                "Rank of the first relevant hit",
                "Mean of 1/rank; 0 if no hit",
                "Retrieval",
                "High: first relevant result is near rank 1.",
                "Ignores additional relevant documents after the first hit.",
            ],
            [
                "Precision@K / Recall@K",
                "Fraction of top-k that are relevant; fraction of gold found in top-k",
                "Binary relevance from relevant_ids",
                "12-query retrieval baseline",
                "High recall: gold set is mostly retrieved. High precision: few extras in top-k.",
                "Sensitive to k and to how many gold IDs a query has.",
            ],
            [
                "nDCG@K",
                "Graded ranking quality",
                "DCG / ideal DCG using graded_relevance 0–3",
                "12-query retrieval baseline",
                "High: highly relevant chunks are ranked above weaker ones.",
                "Requires graded labels; not used in Phase 2A title-match study.",
            ],
            [
                "Accuracy",
                "Exact label match rate",
                "correct / n",
                "Classification",
                "High: many cases match true_label.",
                "Masks rare-class errors. Classification labels are not human gold.",
            ],
            [
                "Precision / Recall / Macro F1",
                "Per-class then averaged",
                "One-vs-rest; macro unweighted; zero_division=0",
                "Classification",
                "Macro F1 << accuracy suggests class imbalance or missed rare labels.",
                "Unstable on small support. 31 candidates have no label.",
            ],
            [
                "Required-fact coverage",
                "Whether approved reference facts appear in the answer",
                "Pattern presence versus required-fact list",
                "Local QA subset runner only",
                "1.0 would mean all required facts present.",
                "Used only on 401-fallback answers; not a live metric; not RAGAS.",
            ],
            [
                "Token overlap (answer_relevancy proxy)",
                "Question-token overlap with the answer",
                "Distinctive token overlap",
                "Local QA subset runner only",
                "Can be high even when the policy band is wrong.",
                "Weak proxy; explicitly not RAGAS answer relevancy.",
            ],
            [
                "Citation precision / recall",
                "Overlap of displayed citation IDs with gold IDs",
                "|predicted ∩ gold| / |predicted| and / |gold|",
                "Supported in rag_metrics.py; pending for live QA",
                "High: displayed sources match the approved gold set.",
                "Requires gold IDs and a successful verifier or captured display IDs. Live capture missing.",
            ],
            [
                "Faithfulness / claim support",
                "Share of answer claims supported by verified citations",
                "From VerificationOutcome when verifier invoked and succeeded",
                "rag_metrics.py; unavailable in executed QA runs",
                "High: claims are supported by cited chunks.",
                "Null when verifier fails (401) or is not invoked. Null is not zero.",
            ],
        ],
        caption="Table 15. Metrics actually used or supported, with interpretation and limits.",
    )
    heading(doc, "8.1 Metrics that were not executed", 2)
    bullet(doc, "RAGAS faithfulness, answer relevancy, context precision, and context recall were not executed. RAGAS was not installed for this evaluation.")
    bullet(doc, "A 14-question QA accuracy, precision, recall, or F1 was not calculated.")
    bullet(doc, "Live citation precision and recall were not calculated because displayed live citation IDs were not captured.")
    bullet(doc, "LLM-on versus LLM-off chunk classification is not a valid executed comparison.")


def chapter_9(doc):
    heading(doc, "9. Consolidated Results", 1)
    body(
        doc,
        "The three tracks are summarized side by side. They must not be averaged into one system accuracy.",
    )
    add_table(
        doc,
        ["Track", "Population", "Headline result", "What it indicates"],
        [
            [
                "Retrieval (Phase 2A)",
                "20 title-match cases, 750-chunk collection recorded",
                "Hit@1 0.90; Hit@3 1.00 (full pipeline)",
                "Expected sections usually appeared at rank 1 and always by rank 3 on that older gold definition.",
            ],
            [
                "Retrieval (12-query human labels)",
                "12 queries, 691-chunk chroma_evaluation",
                "Hit@5 0.8333 embedding-only; 0.9167 with reranker",
                "The heuristic reranker improved ranking. Q10 still missed. Recall@5 unchanged.",
            ],
            [
                "Question classification",
                "37 dual-AI-labeled questions",
                "Accuracy 70.27%; Macro F1 0.5064",
                "Majority-label accuracy is moderate; rare subcategories pull macro F1 down. Not human gold.",
            ],
            [
                "Chunk classification",
                "28 dual-AI-labeled chunks",
                "Accuracy 64.29%; Macro F1 0.5345",
                "Weaker than question classification. LLM-on/off identity is a 401 fallback, not an ablation.",
            ],
            [
                "QA live observation",
                "2 production answers",
                "1 satisfactory, 1 unsatisfactory",
                "Fee-and-procedure content can succeed; fragmented table policy answers can fail. Citations unverified.",
            ],
            [
                "QA remainder",
                "12 prepared questions",
                "8 reference-based reviews; 4 not scored",
                "The benchmark is prepared. It is not a 14-question accuracy result.",
            ],
        ],
        caption="Table 16. Consolidated findings by evaluation population.",
    )
    heading(doc, "9.1 What performed well", 2)
    bullet(doc, "Human-labeled retrieval on the isolated 691-chunk corpus reached Hit@5 0.9167 after reranking.")
    bullet(doc, "Phase 2A full-pipeline Hit@3 was 1.00 on its 20-case title-match set.")
    bullet(doc, "The live dropping-fee answer stated P30.00 and included procedure information.")
    bullet(doc, "Evidence review refused to invent a current president, a Wi-Fi password, or a missing overdue-fee unit.")
    heading(doc, "9.2 What needs improvement", 2)
    bullet(doc, "Q10 faculty-responsibilities retrieval missed in both embedding-only and reranked Hit@5.")
    bullet(doc, "Classification macro F1 is low relative to accuracy; taxonomy tail classes are weak.")
    bullet(doc, "The live 75% retention answer returned fragmented table content instead of the policy consequence.")
    bullet(doc, "Citation display, page metadata, and PDF viewer mapping remain unresolved for several gold candidates.")
    bullet(doc, "Chunk extraction quality (truncated fees, mashed TOR fee cards, split table rows) limits both retrieval grading and answer generation.")
    heading(doc, "9.3 How component weaknesses affect the full RAG system", 2)
    body(
        doc,
        "A missed retrieval (Q10) means generation never sees the right passage. A retrieved but fragmented table "
        "(aq_08 live failure, and the local fallback quoting warning/probation ::66) can produce a fluent wrong band. "
        "A classifier error can boost the wrong office or ticket route even if retrieval later recovers. Generation "
        "without citation verification can state a fee from one document while omitting a conflicting official rate "
        "(aq_04 live PASS versus conflict-aware reference). These failure modes are why the thesis should discuss "
        "the pipeline, not a single accuracy percentage.",
    )


def chapter_10(doc):
    heading(doc, "10. Limitations and Recommendations", 1)
    heading(doc, "10.1 Limitations identified during evaluation", 2)
    bullet(doc, "Dataset coverage: 12 retrieval queries, 65 classification cases, and 14 prepared QA questions are small, LSPU-specific samples.")
    bullet(doc, "Human-review coverage: retrieval labels are human; classification labels are dual-AI; QA references are human-reviewed for five cases, with only two gold citation sets assigned.")
    bullet(doc, "Citation mapping: student-visible IDs, Chroma page metadata, PDF page index, and printed footer page are three different page notions and often disagree.")
    bullet(doc, "Fragmented or incomplete source tables: overdue-fee unit missing; TOR fees mashed; retention table split across chunks.")
    bullet(doc, "LLM provider availability: local OpenRouter/Groq HTTP 401 blocked generated answers and LLM chunk classification.")
    bullet(doc, "Local generation failures: the subset runner recorded fallback answers, which must not be reported as Groq answers.")
    bullet(doc, "Local versus production: isolated chroma_evaluation (691) is not production Chroma; live UI answers are not the 401 fallback run.")
    bullet(doc, "Limited live QA observations: 2 of 14 questions; no stored verbatim transcripts; citations pending.")
    bullet(doc, "Metrics that could not be calculated reliably: 14-question QA accuracy; live citation precision/recall; faithfulness; RAGAS; LLM-on/off chunk delta.")
    heading(doc, "10.2 Recommendations", 2)
    bullet(doc, "Complete live student-UI tests for the eight reference-based questions, capturing verbatim answers and displayed citation IDs.")
    bullet(doc, "Resolve aq_01 citation usability and aq_10 metadata/viewer issues before assigning remaining gold citation IDs.")
    bullet(doc, "Confirm pending PDF drafts (aq_02, aq_03, aq_06, aq_07, aq_09, aq_11) before promoting them to labeled gold.")
    bullet(doc, "Keep aq_05, aq_12, and aq_14 as insufficient-evidence cases; score aq_13 on refusal, not handbook correctness.")
    bullet(doc, "Re-run classify_chunk allow_llm=True only after a successful LLM credential path; do not interpret the 401 pair as an ablation.")
    bullet(doc, "Continue scoring retrieval against chroma_evaluation until production Chroma is labeled on the same IDs.")
    bullet(doc, "Report accuracy only over the population that was actually labeled and tested. Do not average retrieval Hit@K, classification F1, and two live QA judgments.")
    bullet(doc, "Improve table extraction for retention and fee cards so generation is not fed flattened rows.")


def chapter_11(doc):
    heading(doc, "11. Guide for Incorporating the Evaluation into the Thesis Manuscript", 1)
    body(
        doc,
        "This chapter is written so the manuscript author can describe the work without opening every source file. "
        "Copy tables as needed; do not upgrade any status that this document marks as pending or not scored.",
    )
    heading(doc, "11.1 Suggested evaluation-methodology narrative", 2)
    body(
        doc,
        "The system was evaluated in three component tracks corresponding to the RAG pipeline. Retrieval was "
        "measured with human-reviewed relevance judgments on an isolated 691-chunk index, using Hit@K, MRR, "
        "Precision@K, Recall@K, and nDCG@K, and comparing embedding-only ranking with the existing rule-based "
        "reranker. An earlier expansion-rule study on 20 cases reported Hit@1 = 0.90 and Hit@3 = 1.00 under a "
        "title-match gold definition; that study is reported separately. Classification was measured on 65 cases "
        "labeled by dual independent AI agreement, with accuracy and macro F1 for question classification (n=37) "
        "and chunk classification (n=28). Labels are not human gold. Answer quality used a 14-question candidate "
        "benchmark. Five cases received detailed evidence review; two received gold citation IDs; two were observed "
        "on the live chatbot. The student-facing function answer_qa_question() is the intended QA evaluation target "
        "because it includes retrieval, gating, fallback, and citation display that raw generate_groq_answer() omits.",
    )
    heading(doc, "11.2 Suggested results-and-discussion structure", 2)
    bullet(doc, "Section A — Retrieval results: Table 3 and Table 5, with an explicit statement that they are different experiments.")
    bullet(doc, "Section B — Classification results: Tables 7–8, plus the 401 limitation in the same paragraph as the chunk scores.")
    bullet(doc, "Section C — Answer quality: Table 11 as the overview; then the two live cases in full; then limitations.")
    bullet(doc, "Section D — Cross-component discussion: how Q10 retrieval, table fragmentation, and citation metadata affect student answers.")
    bullet(doc, "Section E — Limitations: dual-AI classification labels; n=2 live QA; no RAGAS; no 14-question accuracy.")
    heading(doc, "11.3 Claims the current evidence supports", 2)
    bullet(doc, "The reranker improved Hit@5, MRR, and nDCG@5 on the 12 human-labeled queries against the 691-chunk evaluation index.")
    bullet(doc, "Phase 2A full-pipeline retrieval reported Hit@1 = 0.90 and Hit@3 = 1.00 on 20 title-match cases.")
    bullet(doc, "Question classification accuracy was 70.27% and macro F1 0.5064 on 37 dual-AI-labeled cases.")
    bullet(doc, "Chunk classification accuracy was 64.29% and macro F1 0.5345 on 28 dual-AI-labeled cases, under non-LLM fallback.")
    bullet(doc, "On two live questions, one answer was satisfactory (dropping fee P30.00 plus procedure) and one was not (fragmented 75% table).")
    heading(doc, "11.4 Claims the current evidence does not support", 2)
    bullet(doc, "Do not claim a 14-question QA accuracy, an overall RAG accuracy, or a production-wide success rate.")
    bullet(doc, "Do not describe classification metrics as human-validated.")
    bullet(doc, "Do not describe the identical LLM-on/off chunk scores as proof that the LLM does not help.")
    bullet(doc, "Do not treat reference-based case reviews as measured chatbot outputs.")
    bullet(doc, "Do not report citation precision/recall or faithfulness as computed live scores.")
    bullet(doc, "Do not state that RAGAS was used.")
    heading(doc, "11.5 Limitations the manuscript should acknowledge", 2)
    body(
        doc,
        "Small n; dual-AI classification labels; incomplete QA gold; two live observations without stored transcripts; "
        "local 401 failures; isolated evaluation index versus production Chroma; conflicting official fee schedules; "
        "and three disagreeing page-number systems for citations.",
    )


def chapter_12(doc):
    heading(doc, "12. Conclusion", 1)
    body(
        doc,
        "ASKa-Piyu was evaluated as a RAG system with three separable tracks. Retrieval is the most complete: "
        "human-labeled 12-query Hit@5 reached 0.9167 with the rule-based reranker, and the earlier Phase 2A study "
        "reported Hit@1 = 0.90 and Hit@3 = 1.00 on a different 20-case gold definition. Classification has numeric "
        "results but dual-AI labels and a blocked LLM comparison. Answer quality has a prepared 14-question "
        "benchmark and two live observations (one satisfactory, one unsatisfactory), not a 14-question accuracy "
        "score. The honest manuscript position is that retrieval ranking on the labeled evaluation index is strong, "
        "taxonomy classification is only moderately reliable on the available labels, and student-facing answer "
        "quality remains partially measured. Future work should complete live QA capture, repair citation mapping, "
        "and keep component metrics on their own populations.",
    )


def appendix_a(doc):
    heading(doc, "Appendix A. QA Benchmark Question IDs and Evaluation Statuses", 1)
    add_table(
        doc,
        ["Short ID", "Full case_id", "Question", "Assessment basis", "Answer finding", "Citations"],
        [
            ["aq_01", "aq_01_tor_fee", "How much does it cost to get a copy of my Transcript of Records?", "Reference-based review", "Not measured live", "Unresolved"],
            ["aq_02", "aq_02_diploma_second_copy_fee", "How much is the fee for a second copy of my diploma?", "Reference-based review", "Not measured live", "Not assigned"],
            ["aq_03", "aq_03_enrollment_office", "Which office handles student enrollment?", "Reference-based review", "Not measured live", "Not assigned"],
            ["aq_04", "aq_04_dropping_fee_multi_document", "How much does it cost to drop a subject?", "Live production observation", "Satisfactory", "Pending (gold assigned)"],
            ["aq_05", "aq_05_library_overdue_fee", "What is the fee for library circulation service if my book is overdue?", "Not scored", "Insufficient evidence", "None"],
            ["aq_06", "aq_06_entrance_exam_duration", "How long does the LSPU entrance examination take, including orientation?", "Reference-based review", "Not measured live", "Not assigned"],
            ["aq_07", "aq_07_id_validation_process", "What is the process for validating my student ID?", "Reference-based review", "Not measured live", "Not assigned"],
            ["aq_08", "aq_08_fail_more_than_75_percent", "What happens if I fail more than 75% of my units?", "Live production observation", "Unsatisfactory", "Pending (gold assigned)"],
            ["aq_09", "aq_09_faculty_teaching_load", "How is faculty teaching load determined?", "Reference-based review", "Not measured live", "Not assigned"],
            ["aq_10", "aq_10_faculty_responsibilities", "What are the responsibilities of an LSPU faculty member?", "Reference-based review", "Not measured live", "Held"],
            ["aq_11", "aq_11_honorable_dismissal", "What is honorable dismissal for a student?", "Reference-based review", "Not measured live", "Not assigned"],
            ["aq_12", "aq_12_university_president", "Who is the current LSPU president?", "Not scored", "Insufficient evidence", "None"],
            ["aq_13", "aq_13_out_of_scope_weather_mars", "What is the weather on Mars tomorrow?", "Not scored", "Out of scope", "None"],
            ["aq_14", "aq_14_insufficient_wifi_password", "What is the LSPU student Wi-Fi password?", "Not scored", "Insufficient evidence", "None"],
        ],
        caption="Table 17. Appendix listing of all 14 QA benchmark IDs.",
    )


def appendix_b(doc):
    heading(doc, "Appendix B. Retrieval Query IDs", 1)
    body(
        doc,
        "The 12 human-reviewed retrieval queries share question text with aq_01–aq_12 but use different gold. "
        "Retrieval gold is relevant_ids / graded_relevance. Answer-quality gold is proposed_reference_answer and, "
        "where assigned, gold_citation_ids. Those gold sets are not interchangeable. In particular, retrieval "
        "rag_benchmark_08 includes ::66, which QA gold for aq_08 excludes.",
    )


def appendix_c(doc):
    heading(doc, "Appendix C. Source-Code Modules Explained", 1)
    add_table(
        doc,
        ["Module", "Role in evaluation"],
        [
            ["app/services/evaluation/evaluation_service.py", "Orchestrates classification, retrieval, and RAG component evaluation"],
            ["app/services/evaluation/datasets.py", "Loads labeled JSON; excludes unlabeled cases"],
            ["app/services/evaluation/retrieval_metrics.py", "Hit@K, MRR, Precision@K, Recall@K, nDCG@K"],
            ["app/services/evaluation/classification_metrics.py", "Accuracy, precision, recall, F1"],
            ["app/services/evaluation/rag_metrics.py", "Aggregates RAG/citation metrics; keeps nulls"],
            ["app/services/evaluation/labeled_retrieval_store.py", "Read-only search over chroma_evaluation (691)"],
            ["app/services/evaluation/persistence.py", "Writes local evaluation_* database rows"],
            ["app/services/chroma_store.py", "Chroma search, cosine similarity, rerank call"],
            ["app/services/embeddings.py", "intfloat/multilingual-e5-small embedding function"],
            ["app/services/retrieval_reranker.py", "Query expansion and heuristic reranking"],
            ["app/services/knowledge_taxonomy.py", "classify_question and classify_chunk"],
            ["app/services/qa/question_answering.py", "Student-facing answer_qa_question()"],
            ["app/services/qa/groq_answer_service.py", "Raw LLM generation given context"],
            ["app/services/qa/citation_verification.py", "Lexical / LLM citation verification"],
            ["benchmarks/evaluation/answer_quality_labeling/run_approved_subset_eval.py", "Separate AQ runner for aq_04 and aq_08"],
            ["scripts/retrieval_expansion_benchmark.py", "Phase 2A Hit@1/Hit@3 title-match evaluation"],
            ["run_retrieval_benchmark_local.py", "Frozen 12-query retrieval baseline runner"],
        ],
        caption="Table 18. Source modules referenced in this document.",
    )
    body(
        doc,
        "End of document. Generated from existing evaluation artifacts only. Datasets, previous runs, production "
        "code, and deployment were not modified.",
    )


if __name__ == "__main__":
    build()

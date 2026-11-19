"""Collect real classification-labeling candidates. Never writes true_label.

Run from backend/:  python benchmarks/evaluation/classification_labeling/build_candidate_sheets.py
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

BACKEND = Path(__file__).resolve().parents[3]
EVAL_DIR = BACKEND / "benchmarks" / "evaluation"
OUT = Path(__file__).resolve().parent
TAXONOMY_PATH = BACKEND / "app" / "knowledge_base_categories.json"
CHROMA_EXTRACT = BACKEND / "benchmarks" / "results" / "chroma_record_extraction_20261104T104214Z.json"
RETRIEVAL_DATASET = EVAL_DIR / "retrieval_relevance_dataset.json"
CLASSIFICATION_DATASET = EVAL_DIR / "classification_eval_dataset.json"

MIN_CHUNK_CHARS = 120
STRATIFIED_PER_CATEGORY = 3
PLACEHOLDER_TEXT_RE = re.compile(r"^\s*Brand New Article\b", re.I)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_q(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def taxonomy_rows(payload: dict) -> list[dict]:
    rows = []
    for category in payload["categories"]:
        for sub in category["subcategories"]:
            rows.append(
                {
                    "category": category["name"],
                    "subcategory": sub["name"],
                    "office": sub["office"],
                    "valid_true_label": sub["name"],
                    "note": (
                        "true_label MUST be this subcategory string. "
                        "classify_question/classify_chunk both return ClassificationResult.subcategory."
                    ),
                }
            )
    return rows


def collect_questions() -> list[dict]:
    seen: dict[str, dict] = {}

    def add(*, case_id: str, text: str, provenance: str, source_file: str, notes: str = "") -> None:
        key = _norm_q(text)
        if not key:
            return
        if key in seen:
            seen[key]["additional_sources"].append(f"{source_file} ({case_id})")
            return
        seen[key] = {
            "case_id": case_id,
            "text": text.strip(),
            "provenance": provenance,
            "source_file": source_file,
            "additional_sources": [],
            "notes": notes,
            "component": "classify_question",
            "labeling_status": "unlabeled",
            "true_label": None,
            "review_status": "pending_human_review",
        }

    retrieval = _load(RETRIEVAL_DATASET)
    for case in retrieval["cases"]:
        add(
            case_id=f"cls_q_{case['query_id']}",
            text=case["query"],
            provenance=(
                f"retrieval_relevance_dataset.json query_id={case['query_id']}. "
                "Retrieval relevance labels are NOT classification ground truth."
            ),
            source_file="backend/benchmarks/evaluation/retrieval_relevance_dataset.json",
            notes="Independent classification review required; do not copy relevant_ids.",
        )

    cg = _load(BACKEND / "benchmarks" / "citation_grounding_benchmark.json")
    for case in cg["cases"]:
        add(
            case_id=f"cls_q_cg_{case['id']}",
            text=case["question"],
            provenance=f"citation_grounding_benchmark.json id={case['id']} source_file={case.get('source_file')}",
            source_file="backend/benchmarks/citation_grounding_benchmark.json",
            notes=case.get("source_label") or "",
        )

    fg = _load(BACKEND / "benchmarks" / "citation_grounding_fresh_gold_validation_cases.json")
    for case in fg["cases"]:
        add(
            case_id=f"cls_q_{case['case_id']}",
            text=case["question"],
            provenance=(
                f"citation_grounding_fresh_gold_validation_cases.json case_id={case['case_id']} "
                f"section={case.get('expected_document_section')}"
            ),
            source_file="backend/benchmarks/citation_grounding_fresh_gold_validation_cases.json",
            notes=case.get("why_this_case_exists") or "",
        )

    pilot = _load(BACKEND / "benchmarks" / "citation_grounding_pilot_cases.json")
    for case in pilot["cases"]:
        add(
            case_id=f"cls_q_pilot_{case.get('id', case.get('case_id', 'unknown'))}",
            text=case["question"],
            provenance=f"citation_grounding_pilot_cases.json id={case.get('id') or case.get('case_id')}",
            source_file="backend/benchmarks/citation_grounding_pilot_cases.json",
            notes="Pilot case; some items are out-of-scope probes. Mark MARK_FOR_REVIEW if no taxonomy class fits.",
        )

    return list(seen.values())


def _chunk_lookup() -> dict[str, dict]:
    extract = _load(CHROMA_EXTRACT)
    by_id = {}
    for rec in extract["records"]:
        cid = rec.get("chunk_id") or (rec.get("metadata") or {}).get("chunk_id")
        if cid:
            by_id[str(cid)] = rec
    return by_id


def collect_chunks() -> list[dict]:
    by_id = _chunk_lookup()
    selected: dict[str, dict] = {}

    def accept(rec: dict, *, provenance: str, notes: str) -> None:
        cid = str(rec.get("chunk_id") or rec.get("metadata", {}).get("chunk_id") or "")
        if not cid or cid in selected:
            return
        text = (rec.get("text") or "").strip()
        if len(text) < MIN_CHUNK_CHARS:
            return
        if PLACEHOLDER_TEXT_RE.search(text):
            return
        meta = rec.get("metadata") or {}
        selected[cid] = {
            "case_id": f"cls_c_{cid.replace(':', '_')}",
            "chunk_id": cid,
            "text": text,
            "document_id": str(meta.get("document_id") or ""),
            "source_filename": str(meta.get("source_filename") or ""),
            "title": str(meta.get("title") or meta.get("canonical_topic") or ""),
            "index_metadata_category": str(meta.get("category") or ""),
            "index_metadata_subcategory": str(meta.get("subcategory") or ""),
            "index_metadata_office": str(meta.get("office") or meta.get("doc_office") or ""),
            "provenance": provenance,
            "source_file": "backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json",
            "notes": notes,
            "component": "classify_chunk",
            "labeling_status": "unlabeled",
            "true_label": None,
            "review_status": "pending_human_review",
        }

    retrieval = _load(RETRIEVAL_DATASET)
    cited = []
    for case in retrieval["cases"]:
        for cid in case.get("relevant_ids") or []:
            cited.append((str(cid), case["query_id"]))
    for cid, qid in cited:
        rec = by_id.get(cid)
        if rec is None:
            continue
        accept(
            rec,
            provenance=(
                f"Chunk {cid} is a retrieval relevant_id for {qid}. "
                "That retrieval grade is NOT a classification label."
            ),
            notes="Include because this is real KB text already in the 12-q retrieval set.",
        )

    buckets: dict[str, list] = defaultdict(list)
    for rec in by_id.values():
        text = (rec.get("text") or "").strip()
        if len(text) < MIN_CHUNK_CHARS or PLACEHOLDER_TEXT_RE.search(text):
            continue
        cat = str((rec.get("metadata") or {}).get("category") or "UNSTAMPED")
        buckets[cat].append(rec)

    for cat, recs in sorted(buckets.items(), key=lambda kv: kv[0].lower()):
        # Stable order by chunk_id; take spaced samples so we are not only the first N of one doc.
        recs = sorted(recs, key=lambda r: str(r.get("chunk_id") or ""))
        step = max(1, len(recs) // (STRATIFIED_PER_CATEGORY + 1))
        picked = recs[step :: step][:STRATIFIED_PER_CATEGORY]
        if len(picked) < STRATIFIED_PER_CATEGORY:
            picked = recs[:STRATIFIED_PER_CATEGORY]
        for rec in picked:
            accept(
                rec,
                provenance=(
                    f"Stratified sample from chroma_record_extraction (691 records), "
                    f"organized by index metadata category={cat!r}. "
                    "Index category/subcategory is a stamp from ingestion, NOT ground truth."
                ),
                notes="Do not copy index_metadata_subcategory into true_label.",
            )

    return list(selected.values())


def _style_header(ws, row: int, cols: int) -> None:
    fill = PatternFill("solid", fgColor="4A0A0E")
    font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    for col in range(1, cols + 1):
        cell = ws.cell(row, col)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def _body_font():
    return Font(name="Arial", size=10)


def _write_instructions(ws, *, kind: str, n_cases: int, n_labels: int) -> None:
    ws.sheet_properties.tabColor = "D4A017"
    title = Font(name="Arial", bold=True, size=16, color="4A0A0E")
    body = Font(name="Arial", size=11)
    ws["A1"] = "ASKa-Piyu classification labeling sheet — CANDIDATES ONLY"
    ws["A1"].font = title
    ws.merge_cells("A1:G1")
    lines = [
        "",
        f"Kind: {kind}",
        f"Candidate rows on the Candidates sheet: {n_cases}",
        f"Valid true_label values (taxonomy subcategories): {n_labels}  — see Taxonomy sheet",
        "",
        "HOW TO LABEL",
        "1. Read Original text. Decide the taxonomy SUBCATEGORY that a human would assign.",
        "2. Enter that exact subcategory string in Reviewer 1 true_label (dropdown).",
        "3. If the text is ambiguous, out of scope, or unsupported, choose MARK_FOR_REVIEW. Do not guess.",
        "4. A second reviewer fills Reviewer 2 independently (do not copy Reviewer 1).",
        "5. If the two reviewers disagree, record both labels and fill Adjudicated true_label after discussion.",
        "6. Set Review status to approved only after a human (or adjudicator) has confirmed the label.",
        "",
        "FORBIDDEN",
        "- Do not copy classifier predictions into true_label.",
        "- Do not copy retrieval relevant_ids, index metadata category, filename, or keywords into true_label.",
        "- Do not invent handbook text or student questions.",
        "- Do not mark labeling_status=labeled in the eval JSON until approved.",
        "",
        "EVALUATOR CONTRACT (actual code)",
        "classify_question(text).subcategory  and  classify_chunk(text, allow_llm=True|False).subcategory",
        "are scored against true_label. Both LLM-on and LLM-off chunk runs use the SAME labeled classify_chunk cases.",
        "Accuracy / macro F1 / confusion matrix appear on the dashboard only after labeled cases exist.",
        "",
        "EXAMPLE FORMAT (not a real labeled case — do not copy into Candidates):",
        "case_id = cls_q_example_format",
        "original_text = <verbatim question from a project file>",
        "true_label = Registration     (must match Taxonomy!subcategory exactly)",
        "review_status = pending_human_review until a person approves it",
        "",
        f"Built: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "Cells to edit: Reviewer 1/2 true_label, status, notes; Adjudicated true_label; Review status.",
    ]
    for i, line in enumerate(lines, start=2):
        ws[f"A{i}"] = line
        ws[f"A{i}"].font = Font(name="Arial", bold=True, size=11) if line.isupper() or line.startswith("HOW") or line.startswith("FORBIDDEN") or line.startswith("EVALUATOR") or line.startswith("EXAMPLE") else body
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=7)
    ws.column_dimensions["A"].width = 110


def _add_table(ws, name: str, n_rows: int, n_cols: int) -> None:
    if n_rows < 1:
        return
    ref = f"A1:{get_column_letter(n_cols)}{n_rows + 1}"
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(table)


def write_question_workbook(questions: list[dict], tax_rows: list[dict]) -> Path:
    wb = Workbook()
    inst = wb.active
    inst.title = "Instructions"
    labels = sorted({r["subcategory"] for r in tax_rows})
    _write_instructions(inst, kind="classify_question", n_cases=len(questions), n_labels=len(labels))

    tax = wb.create_sheet("Taxonomy")
    tax_headers = ["category", "subcategory", "office", "valid_true_label", "note"]
    tax.append(tax_headers)
    for r in tax_rows:
        tax.append([r[h] for h in tax_headers])
    _style_header(tax, 1, len(tax_headers))
    for cell in tax["B"][1:]:
        cell.font = Font(name="Arial", size=10)
    _add_table(tax, "QuestionTaxonomy", len(tax_rows), len(tax_headers))
    for i, w in enumerate([28, 32, 28, 32, 70], 1):
        tax.column_dimensions[get_column_letter(i)].width = w

    cand = wb.create_sheet("Candidates")
    headers = [
        "case_id",
        "original_text",
        "provenance",
        "source_file",
        "additional_sources",
        "component",
        "reviewer_1_true_label",
        "reviewer_1_status",
        "reviewer_1_notes",
        "reviewer_2_true_label",
        "reviewer_2_status",
        "reviewer_2_notes",
        "adjudicated_true_label",
        "review_status",
        "system_prediction_do_not_copy",
        "collector_notes",
    ]
    cand.append(headers)
    _style_header(cand, 1, len(headers))
    wrap = Alignment(wrap_text=True, vertical="top")
    body = _body_font()
    pending_fill = PatternFill("solid", fgColor="FFF4E5")
    lock_fill = PatternFill("solid", fgColor="F3F4F6")
    edit_fill = PatternFill("solid", fgColor="E8F5E9")
    for q in questions:
        row = [
            q["case_id"],
            q["text"],
            q["provenance"],
            q["source_file"],
            "; ".join(q["additional_sources"]),
            q["component"],
            "",
            "pending",
            "",
            "",
            "pending",
            "",
            "",
            q["review_status"],
            "",
            q["notes"],
        ]
        cand.append(row)
    for r in range(2, len(questions) + 2):
        for c in range(1, len(headers) + 1):
            cell = cand.cell(r, c)
            cell.font = body
            cell.alignment = wrap
        for c in (7, 8, 9, 10, 11, 12, 13, 14):
            cand.cell(r, c).fill = edit_fill
        cand.cell(r, 15).fill = lock_fill
        cand.cell(r, 14).fill = pending_fill
    cand.freeze_panes = "A2"
    cand.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(questions) + 1}"
    widths = [28, 55, 40, 40, 30, 20, 28, 16, 28, 28, 16, 28, 28, 24, 28, 40]
    for i, w in enumerate(widths, 1):
        cand.column_dimensions[get_column_letter(i)].width = w
    cand.row_dimensions[1].height = 32
    for r in range(2, len(questions) + 2):
        cand.row_dimensions[r].height = 48

    # Dropdowns: taxonomy subcategories + MARK_FOR_REVIEW. Hidden list sheet for DV.
    lists = wb.create_sheet("_lists")
    lists["A1"] = "label"
    for i, name in enumerate(labels + ["MARK_FOR_REVIEW"], start=2):
        lists[f"A{i}"] = name
        lists[f"A{i}"].font = body
    lists.sheet_state = "hidden"
    last = 1 + len(labels) + 1
    dv_label = DataValidation(type="list", formula1=f"_lists!$A$2:$A${last}", allow_blank=True)
    dv_label.error = "Pick a Taxonomy subcategory or MARK_FOR_REVIEW"
    dv_label.errorTitle = "Invalid true_label"
    dv_status = DataValidation(
        type="list",
        formula1='"pending,approved,disagreement,mark_for_review"',
        allow_blank=True,
    )
    dv_review = DataValidation(
        type="list",
        formula1='"pending_human_review,approved,mark_for_review,disagreement"',
        allow_blank=True,
    )
    cand.add_data_validation(dv_label)
    cand.add_data_validation(dv_status)
    cand.add_data_validation(dv_review)
    end = len(questions) + 1
    dv_label.add(f"G2:G{end}")
    dv_label.add(f"J2:J{end}")
    dv_label.add(f"M2:M{end}")
    dv_status.add(f"H2:H{end}")
    dv_status.add(f"K2:K{end}")
    dv_review.add(f"N2:N{end}")

    counts = wb.create_sheet("Progress")
    counts["A1"] = "Metric"
    counts["B1"] = "Value"
    _style_header(counts, 1, 2)
    counts["A2"] = "Candidate questions"
    counts["B2"] = f"=COUNTA(Candidates!A2:A{end})"
    counts["A3"] = "Reviewer 1 labels filled"
    counts["B3"] = f'=COUNTA(Candidates!G2:G{end})'
    counts["A4"] = "Reviewer 2 labels filled"
    counts["B4"] = f'=COUNTA(Candidates!J2:J{end})'
    counts["A5"] = "Adjudicated labels filled"
    counts["B5"] = f'=COUNTA(Candidates!M2:M{end})'
    counts["A6"] = "Rows marked approved"
    counts["B6"] = f'=COUNTIF(Candidates!N2:N{end},"approved")'
    counts["A7"] = "Still pending human review"
    counts["B7"] = f'=COUNTIF(Candidates!N2:N{end},"pending_human_review")'
    counts["A8"] = "Ready for eval JSON? (must be 0 until humans finish)"
    counts["B8"] = '=IF(B6=B2,"YES — promote approved rows only","NO — do not treat as labeled")'
    for r in range(2, 9):
        counts[f"A{r}"].font = body
        counts[f"B{r}"].font = Font(name="Arial", bold=True, size=11)
    counts.column_dimensions["A"].width = 55
    counts.column_dimensions["B"].width = 42

    path = OUT / "classification_question_labeling.xlsx"
    wb.save(path)
    return path


def write_chunk_workbook(chunks: list[dict], tax_rows: list[dict]) -> Path:
    wb = Workbook()
    inst = wb.active
    inst.title = "Instructions"
    labels = sorted({r["subcategory"] for r in tax_rows})
    _write_instructions(inst, kind="classify_chunk (allow_llm True and False share these cases)", n_cases=len(chunks), n_labels=len(labels))

    tax = wb.create_sheet("Taxonomy")
    tax_headers = ["category", "subcategory", "office", "valid_true_label", "note"]
    tax.append(tax_headers)
    for r in tax_rows:
        tax.append([r[h] for h in tax_headers])
    _style_header(tax, 1, len(tax_headers))
    _add_table(tax, "ChunkTaxonomy", len(tax_rows), len(tax_headers))
    for i, w in enumerate([28, 32, 28, 32, 70], 1):
        tax.column_dimensions[get_column_letter(i)].width = w

    cand = wb.create_sheet("Candidates")
    headers = [
        "case_id",
        "chunk_id",
        "document_id",
        "source_filename",
        "title",
        "original_text",
        "provenance",
        "index_metadata_category_HINT_ONLY",
        "index_metadata_subcategory_HINT_ONLY",
        "index_metadata_office_HINT_ONLY",
        "component",
        "reviewer_1_true_label",
        "reviewer_1_status",
        "reviewer_1_notes",
        "reviewer_2_true_label",
        "reviewer_2_status",
        "reviewer_2_notes",
        "adjudicated_true_label",
        "review_status",
        "system_prediction_do_not_copy",
        "collector_notes",
    ]
    cand.append(headers)
    _style_header(cand, 1, len(headers))
    wrap = Alignment(wrap_text=True, vertical="top")
    body = _body_font()
    pending_fill = PatternFill("solid", fgColor="FFF4E5")
    lock_fill = PatternFill("solid", fgColor="F3F4F6")
    edit_fill = PatternFill("solid", fgColor="E8F5E9")
    warn_fill = PatternFill("solid", fgColor="FCE4EC")
    excel_limit = 32000
    for ch in chunks:
        text = ch["text"]
        shown = text if len(text) <= excel_limit else text[:excel_limit] + "\n[TRUNCATED IN SHEET — full text in chunk_candidates.json]"
        cand.append(
            [
                ch["case_id"],
                ch["chunk_id"],
                ch["document_id"],
                ch["source_filename"],
                ch["title"],
                shown,
                ch["provenance"],
                ch["index_metadata_category"],
                ch["index_metadata_subcategory"],
                ch["index_metadata_office"],
                ch["component"],
                "",
                "pending",
                "",
                "",
                "pending",
                "",
                "",
                ch["review_status"],
                "",
                ch["notes"],
            ]
        )
    for r in range(2, len(chunks) + 2):
        for c in range(1, len(headers) + 1):
            cell = cand.cell(r, c)
            cell.font = body
            cell.alignment = wrap
        for c in (12, 13, 14, 15, 16, 17, 18, 19):
            cand.cell(r, c).fill = edit_fill
        cand.cell(r, 8).fill = warn_fill
        cand.cell(r, 9).fill = warn_fill
        cand.cell(r, 10).fill = warn_fill
        cand.cell(r, 20).fill = lock_fill
        cand.cell(r, 19).fill = pending_fill
    cand.freeze_panes = "A2"
    cand.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(chunks) + 1}"
    for i, w in enumerate([28, 36, 28, 22, 28, 55, 40, 24, 28, 22, 16, 26, 14, 24, 26, 14, 24, 26, 22, 26, 36], 1):
        cand.column_dimensions[get_column_letter(i)].width = w
    cand.row_dimensions[1].height = 36
    for r in range(2, len(chunks) + 2):
        cand.row_dimensions[r].height = 64

    lists = wb.create_sheet("_lists")
    lists["A1"] = "label"
    for i, name in enumerate(labels + ["MARK_FOR_REVIEW"], start=2):
        lists[f"A{i}"] = name
        lists[f"A{i}"].font = body
    lists.sheet_state = "hidden"
    last = 1 + len(labels) + 1
    dv_label = DataValidation(type="list", formula1=f"_lists!$A$2:$A${last}", allow_blank=True)
    dv_status = DataValidation(type="list", formula1='"pending,approved,disagreement,mark_for_review"', allow_blank=True)
    dv_review = DataValidation(
        type="list", formula1='"pending_human_review,approved,mark_for_review,disagreement"', allow_blank=True
    )
    cand.add_data_validation(dv_label)
    cand.add_data_validation(dv_status)
    cand.add_data_validation(dv_review)
    end = len(chunks) + 1
    dv_label.add(f"L2:L{end}")
    dv_label.add(f"O2:O{end}")
    dv_label.add(f"R2:R{end}")
    dv_status.add(f"M2:M{end}")
    dv_status.add(f"P2:P{end}")
    dv_review.add(f"S2:S{end}")

    counts = wb.create_sheet("Progress")
    counts["A1"] = "Metric"
    counts["B1"] = "Value"
    _style_header(counts, 1, 2)
    counts["A2"] = "Candidate chunks"
    counts["B2"] = f"=COUNTA(Candidates!A2:A{end})"
    counts["A3"] = "Reviewer 1 labels filled"
    counts["B3"] = f'=COUNTA(Candidates!L2:L{end})'
    counts["A4"] = "Reviewer 2 labels filled"
    counts["B4"] = f'=COUNTA(Candidates!O2:O{end})'
    counts["A5"] = "Adjudicated labels filled"
    counts["B5"] = f'=COUNTA(Candidates!R2:R{end})'
    counts["A6"] = "Rows marked approved"
    counts["B6"] = f'=COUNTIF(Candidates!S2:S{end},"approved")'
    counts["A7"] = "Still pending human review"
    counts["B7"] = f'=COUNTIF(Candidates!S2:S{end},"pending_human_review")'
    counts["A8"] = "Ready for eval JSON?"
    counts["B8"] = '=IF(B6=B2,"YES — promote approved rows only","NO — do not treat as labeled")'
    for r in range(2, 9):
        counts[f"A{r}"].font = body
        counts[f"B{r}"].font = Font(name="Arial", bold=True, size=11)
    counts.column_dimensions["A"].width = 55
    counts.column_dimensions["B"].width = 42

    path = OUT / "classification_chunk_labeling.xlsx"
    wb.save(path)
    return path


def write_report(questions: list[dict], chunks: list[dict], tax_rows: list[dict]) -> Path:
    cats = sorted({r["category"] for r in tax_rows})
    subs = sorted({r["subcategory"] for r in tax_rows})
    q_files = sorted({q["source_file"] for q in questions})
    chunk_docs = sorted({c["document_id"] for c in chunks if c["document_id"]})
    path = OUT / "VALIDATION_AND_STATUS.md"
    path.write_text(
        f"""# Classification evaluation dataset — candidate collection status

**Date:** {datetime.now(timezone.utc).strftime("%Y-%m-%d")}
**Status:** CANDIDATES COLLECTED — **not labeled**. Phase 6 evaluation was **not** run.

Human approval is still required. No case in this folder is ground truth.

## Phase 1 findings (actual implementation)

- Taxonomy file: `backend/app/knowledge_base_categories.json` ({len(cats)} categories, {len(subs)} subcategories).
- `classify_question` and `classify_chunk` both return `ClassificationResult.subcategory` (not the parent category).
- Evaluation (`evaluate_classify_question` / `evaluate_classify_chunk`) compares `true_label` to `.subcategory`.
- One JSON file (`classification_eval_dataset.json`) holds both components; cases are split by `"component": "classify_question"` or `"classify_chunk"`.
- `classify_chunk(allow_llm=True)` and `classify_chunk(allow_llm=False)` share the **same** labeled chunk cases and are scored independently.
- Labeled cases require: `case_id`, `text`, `true_label`, `component`, `labeling_status=labeled`.
- Unlabeled cases are counted and excluded; they never become false negatives.
- Dashboard Accuracy / macro F1 / confusion heatmap appear only after labeled classification cases exist.
- Retrieval 12-question labels were not modified.

## Phase 2 collection

### Questions ({len(questions)} unique after de-duplication)

Sources:

{chr(10).join(f"- `{f}`" for f in q_files)}

The 12 retrieval queries are included as classification *candidates* only. Their `relevant_ids` / graded relevance are not classification labels.

Some captured questions are out-of-scope probes (e.g. recipes, other universities, national politics). Reviewers should use `MARK_FOR_REVIEW` rather than force a campus subcategory.

### Chunks ({len(chunks)} unique)

Source index: `chroma_record_extraction_20261104T104214Z.json` (691 records, local extraction artifact).

- All chunks cited as retrieval `relevant_ids` for the 12-q set (that exist in the extract, length ≥ {MIN_CHUNK_CHARS}, not placeholder).
- Plus a stratified sample of up to {STRATIFIED_PER_CATEGORY} chunks per **index** metadata category (organizing hint only).
- Placeholder FAQ “Brand New Article” rows were excluded.
- Pink columns on the chunk sheet (`index_metadata_*_HINT_ONLY`) are ingestion stamps. **Do not copy them into true_label.**

Document IDs represented: {len(chunk_docs)}.

## Phase 3–4 — not complete

- `true_label` is null on every candidate.
- `classification_eval_dataset.json` remains the empty v1 template (`cases: []`). A copy is in this folder.
- Do not promote rows into the eval JSON until Review status is `approved` and `true_label` is a Taxonomy subcategory (never `MARK_FOR_REVIEW`).

## Phase 5 validation of *candidates* (not of a labeled set)

| Check | Result |
|---|---|
| Every candidate has provenance | Yes |
| Every candidate `true_label` empty | Yes |
| No `labeling_status=labeled` written | Yes |
| Question vs chunk component assignment | Yes (`classify_question` / `classify_chunk`) |
| Duplicate question text collapsed | Yes (extras listed in `additional_sources`) |
| Duplicate chunk_id collapsed | Yes |
| Each class has enough labeled examples | **N/A — zero labeled cases** |
| Dataset represents all university questions | **Do not claim this.** Candidate pool is small and source-biased (benchmarks + one 691-chunk extract). |

## Phase 6

Not run. Reporting Accuracy / F1 / confusion matrices now would be fabricated.

After humans finish:

1. Copy only approved rows into `classification_eval_dataset.json` with `labeling_status: "labeled"`.
2. Keep a version bump (do not overwrite the empty template without this folder’s backup).
3. Click **Run Evaluation** on the local admin dashboard.
4. Confirm classify_question plus both classify_chunk variants show `evaluated`.
""",
        encoding="utf-8",
    )
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tax_payload = _load(TAXONOMY_PATH)
    tax_rows = taxonomy_rows(tax_payload)
    questions = collect_questions()
    chunks = collect_chunks()

    (OUT / "taxonomy_reference.json").write_text(
        json.dumps(
            {
                "source": "backend/app/knowledge_base_categories.json",
                "true_label_is": "subcategory name",
                "categories": tax_payload["categories"],
                "valid_true_labels": sorted({r["subcategory"] for r in tax_rows}),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "question_candidates.json").write_text(
        json.dumps(
            {
                "status": "candidates_unlabeled",
                "labeling_status_of_all_cases": "unlabeled",
                "true_label": None,
                "count": len(questions),
                "cases": questions,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "chunk_candidates.json").write_text(
        json.dumps(
            {
                "status": "candidates_unlabeled",
                "labeling_status_of_all_cases": "unlabeled",
                "true_label": None,
                "count": len(chunks),
                "chroma_extract": str(CHROMA_EXTRACT.relative_to(BACKEND.parent)).replace("\\", "/"),
                "cases": chunks,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    backup = OUT / "classification_eval_dataset.empty-template.backup.json"
    backup.write_text(CLASSIFICATION_DATASET.read_text(encoding="utf-8"), encoding="utf-8")

    q_xlsx = write_question_workbook(questions, tax_rows)
    c_xlsx = write_chunk_workbook(chunks, tax_rows)
    report = write_report(questions, chunks, tax_rows)
    print(f"questions={len(questions)} chunks={len(chunks)} subcategories={len({r['subcategory'] for r in tax_rows})}")
    print(q_xlsx)
    print(c_xlsx)
    print(report)


if __name__ == "__main__":
    main()

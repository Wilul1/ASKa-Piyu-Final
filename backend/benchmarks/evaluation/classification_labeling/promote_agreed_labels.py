"""Promote dual-AI agreements into classification_eval_dataset.json.

Never describes labels as human-reviewed.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
EVAL_DIR = OUT.parent
DATASET = EVAL_DIR / "classification_eval_dataset.json"
TAX = json.loads((OUT / "taxonomy_reference.json").read_text(encoding="utf-8"))
VALID = set(TAX["valid_true_labels"])
Q = {c["case_id"]: c for c in json.loads((OUT / "question_candidates.json").read_text(encoding="utf-8"))["cases"]}
C = {c["case_id"]: c for c in json.loads((OUT / "chunk_candidates.json").read_text(encoding="utf-8"))["cases"]}
SRC = {**Q, **C}


def load_reviewer(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {c["case_id"]: c for c in payload["cases"]}


def main() -> None:
    r1 = load_reviewer(OUT / "reviewer1_annotations.json")
    r2 = load_reviewer(OUT / "reviewer2_annotations.json")
    ids = sorted(set(r1) | set(r2) | set(SRC))
    rows = []
    promoted = []
    for case_id in ids:
        a = r1.get(case_id)
        b = r2.get(case_id)
        src = SRC.get(case_id) or {}
        rec = {
            "case_id": case_id,
            "component": src.get("component") or (a or b or {}).get("component"),
            "text": src.get("text"),
            "annotation_method": "independent_ai_annotation",
            "reviewer_1_type": "AI",
            "reviewer_2_type": "AI",
            "reviewer_1": a,
            "reviewer_2": b,
        }
        if a is None or b is None:
            rec.update(agreement_status="missing_reviewer", adjudication_status="needs_manual_adjudication", approved=False)
            rows.append(rec)
            continue
        l1, l2 = a["label"], b["label"]
        ok1, ok2 = bool(a.get("evidence_sufficient")), bool(b.get("evidence_sufficient"))
        if l1 == "MARK_FOR_REVIEW" or l2 == "MARK_FOR_REVIEW":
            rec.update(
                agreement_status="mark_for_review" if l1 == l2 else "disagreement",
                adjudication_status="needs_manual_adjudication",
                approved=False,
                reason="one or both reviewers marked insufficient/OOS/ambiguous",
            )
            rows.append(rec)
            continue
        if l1 not in VALID or l2 not in VALID:
            rec.update(agreement_status="invalid_label", adjudication_status="needs_manual_adjudication", approved=False)
            rows.append(rec)
            continue
        if l1 != l2:
            rec.update(
                agreement_status="disagreement",
                adjudication_status="needs_manual_adjudication",
                approved=False,
                reason="reviewers chose different subcategories",
            )
            rows.append(rec)
            continue
        if not (ok1 and ok2):
            rec.update(
                agreement_status="agree_insufficient_evidence",
                adjudication_status="needs_manual_adjudication",
                approved=False,
                reason="labels match but one or both evidence_sufficient=false",
            )
            rows.append(rec)
            continue
        rec.update(
            agreement_status="agree",
            adjudication_status="auto_accepted_dual_ai_agreement",
            approved=True,
            true_label=l1,
        )
        rows.append(rec)
        promoted.append(
            {
                "case_id": case_id,
                "text": src["text"],
                "true_label": l1,
                "component": src["component"],
                "labeling_status": "labeled",
                "annotation_method": "independent_ai_annotation",
                "reviewer_1_type": "AI",
                "reviewer_2_type": "AI",
                "adjudication_status": "auto_accepted_dual_ai_agreement",
                "reviewer_1_justification": a.get("justification"),
                "reviewer_2_justification": b.get("justification"),
                "reviewer_1_evidence": a.get("evidence"),
                "reviewer_2_evidence": b.get("evidence"),
                "provenance": src.get("provenance"),
                "source_file": src.get("source_file"),
                "chunk_id": src.get("chunk_id"),
            }
        )

    (OUT / "agreement_adjudication.json").write_text(
        json.dumps(
            {
                "annotation_method": "independent_ai_annotation",
                "reviewer_1_type": "AI",
                "reviewer_2_type": "AI",
                "not_human_reviewed": True,
                "approval_rule": (
                    "Auto-accept only when both AI reviewers assign the same taxonomy "
                    "subcategory, both evidence_sufficient=true, and neither used MARK_FOR_REVIEW."
                ),
                "counts": {
                    "total_candidates": len(rows),
                    "approved": sum(1 for r in rows if r.get("approved")),
                    "by_status": dict(Counter(r["agreement_status"] for r in rows)),
                    "promoted_by_component": dict(Counter(p["component"] for p in promoted)),
                    "promoted_by_label": dict(Counter(p["true_label"] for p in promoted)),
                },
                "cases": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if DATASET.exists():
        shutil.copy(DATASET, OUT / f"classification_eval_dataset.pre_ai_promote_{stamp}.json")

    payload = {
        "dataset_version": "2026-11-04-v2-independent-ai-annotation-dual-agreement",
        "notes": (
            "NOT human-reviewed and NOT human-validated. Labels are dual independent AI "
            "annotations (annotation_method=independent_ai_annotation). A case is included "
            "only when both AI reviewers agreed on the same taxonomy subcategory with "
            "evidence_sufficient=true. Disagreements, MARK_FOR_REVIEW, and insufficient-evidence "
            "rows were not promoted. Do not describe these metrics as human gold labels."
        ),
        "annotation_method": "independent_ai_annotation",
        "reviewer_1_type": "AI",
        "reviewer_2_type": "AI",
        "cases": promoted,
    }
    DATASET.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("approved", len(promoted), "of", len(rows))
    print("by_component", dict(Counter(p["component"] for p in promoted)))
    print("by_status", dict(Counter(r["agreement_status"] for r in rows)))


if __name__ == "__main__":
    main()

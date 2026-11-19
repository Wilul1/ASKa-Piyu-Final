"""Tests for the Stage 1 Citation Grounding V2 baseline infrastructure:

* ``scripts/citation_grounding_baseline.py``'s pure metric-computation
  helpers (``_layer_a_for_case``, ``_redundancy_for_case``) and its
  history-dependent-case exclusion logic (``run_case``) -- these never call
  ``answer_qa_question`` for the exclusion path, and only exercise the pure
  functions that turn a benchmark case into a metric otherwise (the real,
  Chroma/Groq/Postgres-backed end-to-end path is exercised in
  test_qa_question_answering.py's citation-debug-sink tests instead).
* ``benchmarks/citation_grounding_benchmark.json`` itself -- guards the
  honesty invariant this whole stage depends on: no case may claim adjudicated
  gold labels it does not actually have, and no history-dependent case may be
  silently treated as reproducible standalone.

Note: "Unsupported Claim Rate" has no tests here because it is not computed
by this Stage 1 baseline at all (see the script's module docstring and
``labeling_methodology.unsupported_claim_rate_definition`` in the benchmark
file) -- it depended on an experimental, never-committed claim splitter and
coverage-floor concept that were not part of reviewed production code and
have since been reverted. There is nothing to test because there is no
longer any such function (``_row_cleared_both_floors`` /
``_unsupported_claim_stats`` have been removed, not merely disabled).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from scripts.citation_grounding_baseline import (
    DATASET_PATH,
    NOT_APPLICABLE_V1,
    NOT_COMPUTED_NO_GOLD,
    _layer_a_for_case,
    _redundancy_for_case,
    run_case,
)


# --- _layer_a_for_case -------------------------------------------------------
#
# These tests guard the null-vs-empty-gold distinction explicitly: `None`
# means "not adjudicated yet, ground truth unknown" and must be excluded from
# measured evaluation, while `[]` means "adjudicated: no supporting source
# exists" and is a valid, scorable outcome (either a correct abstention or a
# set of false-positive citations depending on what was shown). A plain
# `if not gold:` check would incorrectly merge these two cases.


def test_layer_a_for_case_unlabeled_gold_is_none_is_excluded_not_scored():
    """gold_supporting_chunk_ids is None => unadjudicated/unknown. Must be
    excluded from measured evaluation, not silently scored as though it
    were an adjudicated empty-gold case."""
    case = {"labeling": {"gold_supporting_chunk_ids": None}}

    layer_a = _layer_a_for_case(case, displayed_ids=["doc-a", "doc-b"])

    assert layer_a["status"] == "excluded_unlabeled"
    assert layer_a["precision"] == NOT_COMPUTED_NO_GOLD
    assert layer_a["recall"] == NOT_COMPUTED_NO_GOLD
    # No numeric true_positive/gold_count/shown_count for an excluded case --
    # there is nothing to average, so nothing should look averageable.
    assert "true_positive" not in layer_a


def test_layer_a_for_case_adjudicated_empty_gold_and_nothing_shown_is_correct_abstention():
    """gold_supporting_chunk_ids == [] (adjudicated: no supporting source
    exists) and V1 displayed zero citations => correct abstention. This
    must be a distinct status from 'excluded_unlabeled', and from a
    numeric-precision 'scored' case, since both denominators are zero."""
    case = {"labeling": {"gold_supporting_chunk_ids": []}}

    layer_a = _layer_a_for_case(case, displayed_ids=[])

    assert layer_a["status"] == "correct_abstention"
    assert layer_a["precision"] is None
    assert layer_a["recall"] is None
    assert layer_a["gold_count"] == 0
    assert layer_a["shown_count"] == 0


def test_layer_a_for_case_adjudicated_empty_gold_but_citations_shown_is_false_positive():
    """gold_supporting_chunk_ids == [] (adjudicated: no supporting source
    exists) but V1 displayed citations anyway => every displayed citation
    is a false positive by definition. Distinct from both
    'excluded_unlabeled' and 'correct_abstention'."""
    case = {"labeling": {"gold_supporting_chunk_ids": []}}

    layer_a = _layer_a_for_case(case, displayed_ids=["doc-a", "doc-b"])

    assert layer_a["status"] == "false_positive_citations"
    assert layer_a["precision"] == 0.0
    assert layer_a["recall"] is None
    assert layer_a["gold_count"] == 0
    assert layer_a["shown_count"] == 2


def test_layer_a_for_case_computes_precision_recall_when_gold_present():
    case = {"labeling": {"gold_supporting_chunk_ids": ["doc-a", "doc-c"]}}

    layer_a = _layer_a_for_case(case, displayed_ids=["doc-a", "doc-b"])

    # 1 of 2 shown is gold (precision 0.5); 1 of 2 gold was shown (recall 0.5).
    assert layer_a["status"] == "scored"
    assert layer_a["precision"] == 0.5
    assert layer_a["recall"] == 0.5
    assert layer_a["true_positive"] == 1
    assert layer_a["gold_count"] == 2
    assert layer_a["shown_count"] == 2


def test_layer_a_for_case_perfect_match():
    case = {"labeling": {"gold_supporting_chunk_ids": ["doc-a", "doc-b"]}}

    layer_a = _layer_a_for_case(case, displayed_ids=["doc-b", "doc-a"])

    assert layer_a["status"] == "scored"
    assert layer_a["precision"] == 1.0
    assert layer_a["recall"] == 1.0


def test_layer_a_for_case_nonempty_gold_but_nothing_shown_precision_is_none():
    """Non-empty gold with zero shown citations: recall is a real 0.0 (all
    gold was missed), but precision (true_positive / shown_count) has a
    zero denominator and must be reported as None, never fabricated."""
    case = {"labeling": {"gold_supporting_chunk_ids": ["doc-a"]}}

    layer_a = _layer_a_for_case(case, displayed_ids=[])

    assert layer_a["status"] == "scored"
    assert layer_a["precision"] is None
    assert layer_a["recall"] == 0.0


# --- _redundancy_for_case -----------------------------------------------------


def test_redundancy_not_computed_without_equivalence_groups():
    case = {"labeling": {"evidence_equivalence_groups": None}}

    redundancy = _redundancy_for_case(case, displayed_ids=["doc-a", "doc-b"])

    assert redundancy["redundancy_rate"] == NOT_COMPUTED_NO_GOLD


def test_redundancy_computed_from_equivalence_groups_does_not_penalize_correct_duplicates():
    """Two displayed citations that are the SAME equivalence group (e.g. two
    chunks of the same underlying policy) are redundancy, not a precision
    error -- this is the corrected design from the Stage 1+2 review (must
    not punish correct citations as false positives)."""
    case = {
        "labeling": {
            "evidence_equivalence_groups": [["doc-a", "doc-a2"], ["doc-c"]]
        }
    }

    redundancy = _redundancy_for_case(case, displayed_ids=["doc-a", "doc-a2", "doc-c"])

    # doc-a and doc-a2 are the same equivalence group -> 1 redundant extra.
    assert redundancy["redundant_extra_citations"] == 1
    assert redundancy["redundancy_rate"] == 1 / 3


def test_redundancy_computed_from_equivalence_groups_no_duplicates():
    case = {
        "labeling": {
            "evidence_equivalence_groups": [["doc-a"], ["doc-b"]]
        }
    }

    redundancy = _redundancy_for_case(case, displayed_ids=["doc-a", "doc-b"])

    assert redundancy["redundant_extra_citations"] == 0
    assert redundancy["redundancy_rate"] == 0.0


# --- run_case: citation identity + history-dependent exclusion --------------


def test_run_case_uses_citation_id_not_document_id_for_displayed_ids():
    """Source-level guard for the identity fix: run_case must read
    ``citation_id`` off each ``result.sources`` entry, not the coarser
    ``document_id``, which is shared across multiple distinct chunks of the
    same source document and would silently collapse them. This is checked
    by inspecting run_case's own source rather than by mocking the full
    Chroma/Groq pipeline (exercised end to end elsewhere)."""
    source = inspect.getsource(run_case)
    assert 'source.get("citation_id")' in source
    assert 'source.get("document_id")' not in source


def test_run_case_excludes_non_reproducible_standalone_case_without_calling_pipeline():
    """A case marked reproducible_standalone: false (e.g. a follow-up
    question whose required conversation history is not captured in this
    benchmark file) must be excluded from executable evaluation -- not
    replayed as a context-free standalone question and scored as if that
    were the real captured turn."""
    case = {
        "id": "some_followup",
        "question": "Now tell me about TOR.",
        "reproducible_standalone": False,
        "reproducible_standalone_note": "needs history this file doesn't have",
    }

    row = run_case(case)

    assert row["excluded"] is True
    assert row["id"] == "some_followup"
    assert "history this file doesn't have" in row["exclusion_reason"]
    # No pipeline fields should be present -- the pipeline was never called.
    assert "layer_a" not in row
    assert "displayed_citation_ids" not in row


def test_run_case_defaults_reproducible_standalone_to_true_when_absent():
    """A case with no reproducible_standalone key at all must NOT be treated
    as excluded -- absence means "ordinary, standalone-reproducible case",
    matching every case in the benchmark file except the TOR follow-up."""
    source = inspect.getsource(run_case)
    assert 'case.get("reproducible_standalone", True)' in source


# --- benchmark file honesty invariants --------------------------------------


def _load_benchmark() -> dict:
    return json.loads(Path(DATASET_PATH).read_text(encoding="utf-8"))


def test_benchmark_file_exists_and_has_seeded_cases():
    benchmark = _load_benchmark()
    assert benchmark["cases"], "benchmark must have at least one seeded case"


def test_benchmark_file_has_required_fields_per_case():
    benchmark = _load_benchmark()
    required = {
        "id",
        "source_file",
        "question",
        "question_is_verbatim_capture",
        "user_role",
        "labeling",
        "layer_a_applicable",
        "layer_b_applicable",
    }
    for case in benchmark["cases"]:
        missing = required - set(case.keys())
        assert not missing, f"case {case.get('id')} missing fields: {missing}"


def test_benchmark_file_has_no_fabricated_gold_labels_yet():
    """Guards the core honesty requirement for this stage: since no case has
    actually been through the two-labeler-plus-adjudication process, every
    case's gold_supporting_chunk_ids and evidence_equivalence_groups must be
    null, and its labeling status must say so plainly. This test is meant
    to start FAILING the day someone genuinely adjudicates a case -- at
    which point it (and this comment) should be updated for that case, not
    treated as a regression to silence."""
    benchmark = _load_benchmark()
    for case in benchmark["cases"]:
        labeling = case["labeling"]
        assert labeling["status"] == "unlabeled_pending_adjudication", case["id"]
        assert labeling["gold_supporting_chunk_ids"] is None, case["id"]
        assert labeling["evidence_equivalence_groups"] is None, case["id"]


def test_benchmark_file_layer_b_always_not_applicable_for_v1():
    benchmark = _load_benchmark()
    for case in benchmark["cases"]:
        assert case["layer_b_applicable"] is False, case["id"]
        assert case["layer_b_note"]


def test_run_case_layer_b_status_constant_is_not_applicable_for_v1():
    """The baseline script's own per-case Layer B status (set in run_case,
    not exercised here since it needs the real pipeline) must use this
    exact constant, not a locally re-typed string that could silently drift."""
    assert NOT_APPLICABLE_V1 == "not_applicable_v1_lexical_baseline"


def test_benchmark_file_ids_are_unique():
    benchmark = _load_benchmark()
    ids = [case["id"] for case in benchmark["cases"]]
    assert len(ids) == len(set(ids))


def test_benchmark_file_followup_case_is_marked_non_reproducible_standalone():
    """The one is_followup case whose captured dump does not include the
    conversation history needed to replay it (cert_final_switch_tor_followup,
    'Now tell me about TOR.') must be explicitly marked
    reproducible_standalone: false with a reason, not silently left to be
    replayed as a context-free standalone question."""
    benchmark = _load_benchmark()
    followups = [case for case in benchmark["cases"] if case.get("is_followup")]
    assert followups, "expected at least one is_followup case in the benchmark"
    for case in followups:
        assert case.get("reproducible_standalone") is False, case["id"]
        assert case.get("reproducible_standalone_note"), case["id"]


def test_benchmark_file_non_followup_cases_are_reproducible_standalone_by_default():
    """Every ordinary (non-follow-up) case must NOT carry a
    reproducible_standalone: false marker -- that marker is reserved for
    genuinely history-dependent cases, not applied indiscriminately."""
    benchmark = _load_benchmark()
    for case in benchmark["cases"]:
        if not case.get("is_followup"):
            assert case.get("reproducible_standalone", True) is True, case["id"]

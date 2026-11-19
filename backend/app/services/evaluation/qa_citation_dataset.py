"""QA/citation evaluation dataset loader and validation (Stage 2).

Additive module for experiment family ``qa_citation_v1``. It does not
execute the chatbot, call a judge, or touch classification / retrieval /
``rag_eval_dataset.json``.

Live datasets are student-facing university services only. Faculty-as-audience
cases are rejected. Example artifacts (``example_only`` /
``not_an_evaluation_result`` / ``*.example.json``) are never loaded as
evaluation cases.

Corpus identity is the locked extract artifact's ``identity_digest`` and
``metadata_text_digest``. The dataset JSON sha256 is a different hash and
is never treated as the corpus digest.

Membership of labeled supporting chunk IDs is checked against that local
extract file. This is structural/textual consistency, not semantic
entailment of the reference answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

EXPERIMENT_FAMILY = "qa_citation_v1"
ANNOTATION_METHOD = "ai_assisted_grounded_generation"
JUDGE_SOURCE = "ai_evaluator"

CASE_TYPE_LABELED_STUDENT_SUPPORT = "labeled_student_support"
CASE_TYPE_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
CASE_TYPES = frozenset(
    {CASE_TYPE_LABELED_STUDENT_SUPPORT, CASE_TYPE_INSUFFICIENT_EVIDENCE}
)

LABELING_LABELED = "labeled"
LABELING_UNLABELED = "unlabeled"
LABELING_STATUSES = frozenset({LABELING_LABELED, LABELING_UNLABELED})

LIVE_DIFFICULTIES = frozenset(
    {"easy", "medium", "hard", "conflict", "insufficient_evidence"}
)
LABELED_STUDENT_SUPPORT_DIFFICULTIES = frozenset({"easy", "medium", "hard", "conflict"})
INSUFFICIENT_EVIDENCE_DIFFICULTIES = frozenset({"insufficient_evidence"})

LOCKED_CORPUS_PATH = "backend/data/chroma_evaluation"
LOCKED_CORPUS_COLLECTION = "aska_evaluation"
LOCKED_CORPUS_CHUNK_COUNT = 691
LOCKED_CORPUS_EXTRACT_ARTIFACT = (
    "backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json"
)
LOCKED_IDENTITY_DIGEST = "fcb324dad73c41684e771defec0a36937ddde014df858c3f020aaf914774c85b"
LOCKED_METADATA_TEXT_DIGEST = "7cec45b38d017d17f4f7b39abf3dc2d52a4f6f832b179ea2b70c37c6086262d7"
LOCKED_SOURCE_COLLECTION_AS_RECORDED = "aska_knowledge_base"

# Excerpt rule: after strip(), the excerpt must be a contiguous substring of
# the extract record's ``text``. No case-folding, whitespace collapsing, or
# semantic matching. This does not prove the reference answer is correct.
EXCERPT_MATCH_RULE = "verbatim_contiguous_substring_of_extract_record_text"

SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_BACKEND_ROOT = Path(__file__).resolve().parents[3]

CORPUS_PROVENANCE = {
    "source_extraction_artifact": LOCKED_CORPUS_EXTRACT_ARTIFACT,
    "source_collection_as_recorded_in_extract": LOCKED_SOURCE_COLLECTION_AS_RECORDED,
    "source_sqlite_as_recorded_in_extract": (
        "extract.source.path records the machine-local sqlite that was read "
        "on 2026-11-04 (chroma.sqlite3 / aska_knowledge_base). That path is "
        "not rewritten here."
    ),
    "evaluation_chroma_path": LOCKED_CORPUS_PATH,
    "evaluation_collection": LOCKED_CORPUS_COLLECTION,
    "locked_chunk_count": LOCKED_CORPUS_CHUNK_COUNT,
    "identity_digest": LOCKED_IDENTITY_DIGEST,
    "metadata_text_digest": LOCKED_METADATA_TEXT_DIGEST,
    "limitation": (
        "Stage 2 treats the extract JSON as the authoritative membership "
        "snapshot. It does not open Chroma. Matching expected_chunk_count=691 "
        "on chroma_evaluation/aska_evaluation is the intended evaluation "
        "store for later execution, but this loader does not prove those "
        "Chroma bytes equal the extract. Dataset corpus identity is the two "
        "extract digests, not an assumed Chroma equality."
    ),
}

_FACULTY_AUDIENCE_PATTERNS = (
    re.compile(r"\bfaculty\s+member", re.IGNORECASE),
    re.compile(r"\bfaculty\s+manual", re.IGNORECASE),
    re.compile(r"\bfaculty\s+handbook", re.IGNORECASE),
    re.compile(r"\bfaculty\s+responsibilit", re.IGNORECASE),
    re.compile(r"\bfaculty\s+portal", re.IGNORECASE),
    re.compile(r"\bfaculty\s+login", re.IGNORECASE),
    re.compile(r"\bfaculty\s+affairs", re.IGNORECASE),
    re.compile(r"\bfor\s+faculty\b", re.IGNORECASE),
    re.compile(r"\bintended\s+for\s+faculty\b", re.IGNORECASE),
    re.compile(r"\bteaching\s+load\b", re.IGNORECASE),
)

_STUDENT_ACADEMIC_UNIT_EXEMPTIONS = (
    re.compile(r"faculty\s*/\s*college", re.IGNORECASE),
    re.compile(r"college\s*/\s*faculty", re.IGNORECASE),
    re.compile(r"faculty\s+or\s+college", re.IGNORECASE),
    re.compile(r"college\s+or\s+faculty", re.IGNORECASE),
    re.compile(r"which\s+faculty\b", re.IGNORECASE),
    re.compile(r"what\s+faculty\b", re.IGNORECASE),
    re.compile(r"\bfaculty\s+of\b", re.IGNORECASE),
)

_FACULTY_WORD = re.compile(r"\bfaculty\b", re.IGNORECASE)

_ALLOWED_DATASET_KEYS = frozenset(
    {
        "dataset_version",
        "experiment_family",
        "annotation_method",
        "judge_source_for_later_scoring",
        "notes",
        "evaluation_ready",
        "corpus",
        "generation",
        "cases",
        "example_only",
        "not_an_evaluation_result",
    }
)

_ALLOWED_CASE_KEYS = frozenset(
    {
        "case_id",
        "question",
        "category",
        "case_type",
        "audience",
        "difficulty",
        "labeling_status",
        "reference_answer",
        "supporting_document_ids",
        "supporting_chunk_ids",
        "reference_evidence",
        "generation_model",
        "generation_prompt_version",
        "reviewer_notes",
    }
)

_ALLOWED_EVIDENCE_KEYS = frozenset(
    {
        "chunk_id",
        "document_id",
        "source_filename",
        "title",
        "source_section",
        "page",
        "excerpt",
    }
)

_ALLOWED_CORPUS_KEYS = frozenset(
    {
        "path",
        "collection",
        "expected_chunk_count",
        "extract_artifact",
        "identity_digest",
        "metadata_text_digest",
    }
)


class QaCitationDatasetError(ValueError):
    """Malformed dataset structure or a case that violates the Stage 2 contract."""


@dataclass(frozen=True)
class ExtractChunkRecord:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str


@dataclass(frozen=True)
class LockedExtractIndex:
    identity_digest: str
    metadata_text_digest: str
    record_count: int
    source_path_as_recorded: str
    source_collection_as_recorded: str
    by_chunk_id: dict[str, ExtractChunkRecord]


@dataclass(frozen=True)
class CorpusSnapshot:
    path: str
    collection: str
    expected_chunk_count: int
    extract_artifact: str
    identity_digest: str
    metadata_text_digest: str
    source_path_as_recorded: str
    source_collection_as_recorded: str


@dataclass(frozen=True)
class ReferenceEvidence:
    chunk_id: str
    document_id: str
    excerpt: str
    source_filename: str | None = None
    title: str | None = None
    source_section: str | None = None
    page: int | None = None


@dataclass(frozen=True)
class QaCitationCase:
    case_id: str
    question: str
    category: str
    difficulty: str
    case_type: str
    labeling_status: str
    reference_answer: str | None
    supporting_document_ids: tuple[str, ...]
    supporting_chunk_ids: tuple[str, ...]
    reference_evidence: tuple[ReferenceEvidence, ...]
    generation_model: str
    generation_prompt_version: str
    reviewer_notes: str | None = None
    audience: str | None = None


@dataclass(frozen=True)
class QaCitationDataset:
    dataset_version: str
    experiment_family: str
    annotation_method: str
    judge_source_for_later_scoring: str
    corpus: CorpusSnapshot
    generation_model: str
    generation_prompt_version: str
    labeled_cases: tuple[QaCitationCase, ...]
    unlabeled_cases: tuple[QaCitationCase, ...]
    unlabeled_count: int
    total_count: int
    # Original dataset order, labeled and unlabeled together. Capture must
    # iterate this sequence so unlabeled cases are not dropped.
    cases: tuple[QaCitationCase, ...]
    # sha256 of the dataset JSON bytes -- not the corpus identity digest.
    dataset_json_sha256: str
    source_path: str
    notes: str | None = None
    evaluation_ready: bool | None = None

    @property
    def sha256(self) -> str:
        """Dataset JSON hash. Prefer ``dataset_json_sha256`` in new code."""
        return self.dataset_json_sha256


def parse_citation_id(value: str) -> tuple[str, int]:
    """Split ``document_id::chunk_index`` on the final ``::``, like production ``rsplit('::', 1)``."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise QaCitationDatasetError(
            f"Malformed citation identifier {value!r}: expected document_id::chunk_index "
            "with a final '::' separator and a non-negative integer index."
        )
    if any(ch.isspace() for ch in value):
        raise QaCitationDatasetError(
            f"Malformed citation identifier {value!r}: whitespace is not allowed."
        )
    if "::" not in value:
        raise QaCitationDatasetError(
            f"Malformed citation identifier {value!r}: missing final '::' separator."
        )
    document_id, index_part = value.rsplit("::", 1)
    if not is_valid_document_id(document_id):
        raise QaCitationDatasetError(
            f"Malformed citation identifier {value!r}: document_id {document_id!r} is invalid."
        )
    if not index_part.isdigit() or index_part != str(int(index_part)):
        raise QaCitationDatasetError(
            f"Malformed citation identifier {value!r}: chunk index must be a base-10 "
            "integer with no sign and no leading zeros."
        )
    return document_id, int(index_part)


def is_valid_citation_id(value: str) -> bool:
    try:
        parse_citation_id(value)
    except QaCitationDatasetError:
        return False
    return True


def is_valid_document_id(value: str) -> bool:
    return bool(
        isinstance(value, str)
        and value
        and value == value.strip()
        and not any(ch.isspace() for ch in value)
        and "::" not in value
    )


def faculty_scope_violations(text: str) -> tuple[str, ...]:
    """Return faculty-as-audience markers. Student college/faculty unit phrasing is exempt."""
    if not text:
        return ()
    hits: list[str] = []
    for pattern in _FACULTY_AUDIENCE_PATTERNS:
        if pattern.search(text) and pattern.pattern not in hits:
            hits.append(pattern.pattern)
    masked = text
    for pattern in _STUDENT_ACADEMIC_UNIT_EXEMPTIONS:
        masked = pattern.sub(lambda match: " " * len(match.group(0)), masked)
    if _FACULTY_WORD.search(masked) and r"\bfaculty\b" not in hits:
        hits.append(r"\bfaculty\b")
    return tuple(hits)


def is_example_artifact(payload: Mapping[str, Any] | None, path: str | Path | None = None) -> bool:
    """True when the payload or filename is a contract example, not live data."""
    if path is not None:
        name = Path(path).name.lower()
        if name.endswith(".example.json") or ".example." in name:
            return True
    if not isinstance(payload, Mapping):
        return False
    if payload.get("example_only") is True:
        return True
    if payload.get("not_an_evaluation_result") is True:
        return True
    return False


def locked_extract_path() -> Path:
    return _BACKEND_ROOT / "benchmarks" / "results" / "chroma_record_extraction_20261104T104214Z.json"


@lru_cache(maxsize=1)
def load_locked_extract_index() -> LockedExtractIndex:
    """Load the locked extract JSON. Does not open Chroma."""
    path = locked_extract_path()
    if not path.is_file():
        raise QaCitationDatasetError(
            f"Locked extract artifact not found: {path}. Membership and digest "
            "comparison require this local file."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QaCitationDatasetError(f"Locked extract artifact {path} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise QaCitationDatasetError(f"Locked extract artifact {path} must be a JSON object.")
    validation = payload.get("validation")
    if not isinstance(validation, dict):
        raise QaCitationDatasetError(f"Locked extract artifact {path} is missing validation metadata.")
    identity = validation.get("identity_digest")
    metadata_digest = validation.get("metadata_text_digest")
    record_count = validation.get("record_count")
    if identity != LOCKED_IDENTITY_DIGEST or metadata_digest != LOCKED_METADATA_TEXT_DIGEST:
        raise QaCitationDatasetError(
            f"Locked extract artifact {path} digest mismatch: identity_digest={identity!r}, "
            f"metadata_text_digest={metadata_digest!r}. Expected "
            f"{LOCKED_IDENTITY_DIGEST} / {LOCKED_METADATA_TEXT_DIGEST}."
        )
    if record_count != LOCKED_CORPUS_CHUNK_COUNT:
        raise QaCitationDatasetError(
            f"Locked extract artifact {path} record_count is {record_count!r}, "
            f"expected {LOCKED_CORPUS_CHUNK_COUNT}."
        )
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    records = payload.get("records")
    if not isinstance(records, list):
        raise QaCitationDatasetError(f"Locked extract artifact {path} is missing a records list.")
    by_chunk_id: dict[str, ExtractChunkRecord] = {}
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise QaCitationDatasetError(f"Locked extract artifact {path} records[{index}] is not an object.")
        chunk_id = raw.get("chunk_id")
        try:
            document_id, chunk_index = parse_citation_id(chunk_id if isinstance(chunk_id, str) else "")
        except QaCitationDatasetError as exc:
            raise QaCitationDatasetError(
                f"Locked extract artifact {path} records[{index}] has an unparsable chunk_id {chunk_id!r}."
            ) from exc
        text = raw.get("text")
        if not isinstance(text, str):
            raise QaCitationDatasetError(
                f"Locked extract artifact {path} records[{index}] ({chunk_id}) is missing text."
            )
        by_chunk_id[chunk_id] = ExtractChunkRecord(
            chunk_id=chunk_id,
            document_id=document_id,
            chunk_index=chunk_index,
            text=text,
        )
    if len(by_chunk_id) != LOCKED_CORPUS_CHUNK_COUNT:
        raise QaCitationDatasetError(
            f"Locked extract artifact {path} indexed {len(by_chunk_id)} unique chunk_ids, "
            f"expected {LOCKED_CORPUS_CHUNK_COUNT}."
        )
    return LockedExtractIndex(
        identity_digest=identity,
        metadata_text_digest=metadata_digest,
        record_count=int(record_count),
        source_path_as_recorded=str(source.get("path") or ""),
        source_collection_as_recorded=str(source.get("collection_name") or ""),
        by_chunk_id=by_chunk_id,
    )


def load_qa_citation_dataset(path: str | Path) -> QaCitationDataset:
    """Load and validate a future live ``qa_citation_eval_dataset.json``."""
    path = Path(path)
    if is_example_artifact(None, path):
        raise QaCitationDatasetError(
            f"Refusing to load example artifact as a live QA/citation dataset: {path}. "
            "Contract examples remain example_only and are not evaluation data."
        )
    if not path.exists():
        raise QaCitationDatasetError(f"QA/citation dataset file not found: {path}")
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QaCitationDatasetError(
            f"QA/citation dataset file {path} is not valid JSON: {exc}"
        ) from exc
    return validate_qa_citation_payload(
        payload,
        source_path=str(path),
        dataset_json_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def validate_qa_citation_payload(
    payload: Any,
    *,
    source_path: str = "<memory>",
    dataset_json_sha256: str = "",
    sha256: str = "",
) -> QaCitationDataset:
    """Validate an in-memory dataset object. Same rules as the file loader."""
    json_hash = dataset_json_sha256 or sha256
    if is_example_artifact(payload if isinstance(payload, Mapping) else None, source_path):
        raise QaCitationDatasetError(
            f"Refusing to load example artifact as a live QA/citation dataset: {source_path}. "
            "Set example_only/not_an_evaluation_result only on contract examples, "
            "which must never be treated as evaluation cases."
        )
    if not isinstance(payload, dict):
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path} must be a JSON object at the top level, "
            f"got {type(payload).__name__}."
        )

    unknown_keys = sorted(set(payload) - _ALLOWED_DATASET_KEYS)
    if unknown_keys:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path} has unsupported top-level field(s) "
            f"{unknown_keys}. Unknown fields are rejected rather than ignored."
        )

    dataset_version = _require_non_empty_string(
        payload.get("dataset_version"),
        field="dataset_version",
        where=source_path,
    )
    experiment_family = payload.get("experiment_family")
    if experiment_family != EXPERIMENT_FAMILY:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: experiment_family must be "
            f"{EXPERIMENT_FAMILY!r}, got {experiment_family!r}."
        )
    annotation_method = payload.get("annotation_method")
    if annotation_method != ANNOTATION_METHOD:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: annotation_method must be "
            f"{ANNOTATION_METHOD!r}, got {annotation_method!r}."
        )
    judge_source = payload.get("judge_source_for_later_scoring")
    if judge_source != JUDGE_SOURCE:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: judge_source_for_later_scoring must be "
            f"{JUDGE_SOURCE!r}, got {judge_source!r}."
        )

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: notes must be a string when present."
        )
    evaluation_ready = payload.get("evaluation_ready")
    if evaluation_ready is not None and not isinstance(evaluation_ready, bool):
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: evaluation_ready must be a boolean when present."
        )

    extract_index = load_locked_extract_index()
    corpus = _validate_corpus(payload.get("corpus"), source_path, extract_index)
    generation_model, generation_prompt_version = _validate_generation(
        payload.get("generation"), source_path
    )

    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path} must have a top-level 'cases' list, "
            f"got {type(cases).__name__}."
        )

    parsed: list[QaCitationCase] = []
    seen_ids: dict[str, int] = {}
    for index, raw_case in enumerate(cases):
        case = _validate_case(
            raw_case, index=index, source_path=source_path, extract_index=extract_index
        )
        previous = seen_ids.get(case.case_id)
        if previous is not None:
            raise QaCitationDatasetError(
                f"QA/citation dataset {source_path}: duplicate case_id {case.case_id!r} "
                f"at index {index} (first seen at index {previous})."
            )
        seen_ids[case.case_id] = index
        parsed.append(case)

    labeled = tuple(case for case in parsed if case.labeling_status == LABELING_LABELED)
    unlabeled = tuple(case for case in parsed if case.labeling_status == LABELING_UNLABELED)
    return QaCitationDataset(
        dataset_version=dataset_version,
        experiment_family=EXPERIMENT_FAMILY,
        annotation_method=ANNOTATION_METHOD,
        judge_source_for_later_scoring=JUDGE_SOURCE,
        corpus=corpus,
        generation_model=generation_model,
        generation_prompt_version=generation_prompt_version,
        labeled_cases=labeled,
        unlabeled_cases=unlabeled,
        unlabeled_count=len(unlabeled),
        total_count=len(parsed),
        cases=tuple(parsed),
        dataset_json_sha256=json_hash,
        source_path=source_path,
        notes=notes,
        evaluation_ready=evaluation_ready,
    )


def _validate_digest(value: Any, *, field: str, source_path: str) -> str:
    if not isinstance(value, str) or not SHA256_HEX_PATTERN.fullmatch(value):
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus.{field} must be a 64-character "
            f"lowercase hex sha256 digest, got {value!r}. Values are not coerced."
        )
    return value


def _validate_corpus(raw: Any, source_path: str, extract_index: LockedExtractIndex) -> CorpusSnapshot:
    if not isinstance(raw, dict):
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus must be an object describing "
            "the locked evaluation snapshot. Got "
            f"{type(raw).__name__}."
        )
    unknown = sorted(set(raw) - _ALLOWED_CORPUS_KEYS)
    if unknown:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus has unsupported field(s) {unknown}. "
            "Optional hash/snapshot_id strings are not accepted; use identity_digest and "
            "metadata_text_digest from the locked extract."
        )
    for required in (
        "path",
        "collection",
        "expected_chunk_count",
        "extract_artifact",
        "identity_digest",
        "metadata_text_digest",
    ):
        if required not in raw:
            raise QaCitationDatasetError(
                f"QA/citation dataset {source_path}: corpus.{required} is required. "
                "identity_digest and metadata_text_digest are the corpus identity; "
                "they are not the dataset JSON sha256."
            )
    path = raw.get("path")
    collection = raw.get("collection")
    chunk_count = raw.get("expected_chunk_count")
    extract = raw.get("extract_artifact")
    if path != LOCKED_CORPUS_PATH:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus.path must be {LOCKED_CORPUS_PATH!r} "
            f"(intended evaluation Chroma path), got {path!r}."
        )
    if collection != LOCKED_CORPUS_COLLECTION:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus.collection must be "
            f"{LOCKED_CORPUS_COLLECTION!r}, got {collection!r}."
        )
    if chunk_count != LOCKED_CORPUS_CHUNK_COUNT:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus.expected_chunk_count must be "
            f"{LOCKED_CORPUS_CHUNK_COUNT} (locked snapshot size), got {chunk_count!r}. "
            "The count is not coerced from strings or other types."
        )
    if extract != LOCKED_CORPUS_EXTRACT_ARTIFACT:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus.extract_artifact must be "
            f"{LOCKED_CORPUS_EXTRACT_ARTIFACT!r}, got {extract!r}."
        )
    identity = _validate_digest(raw.get("identity_digest"), field="identity_digest", source_path=source_path)
    metadata_digest = _validate_digest(
        raw.get("metadata_text_digest"), field="metadata_text_digest", source_path=source_path
    )
    if identity != LOCKED_IDENTITY_DIGEST:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus.identity_digest does not match the "
            f"locked extract identity_digest {LOCKED_IDENTITY_DIGEST}."
        )
    if metadata_digest != LOCKED_METADATA_TEXT_DIGEST:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus.metadata_text_digest does not match the "
            f"locked extract metadata_text_digest {LOCKED_METADATA_TEXT_DIGEST}."
        )
    if identity != extract_index.identity_digest or metadata_digest != extract_index.metadata_text_digest:
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: corpus digests do not match the extract "
            "artifact on disk. Dataset JSON sha256 is not a substitute for these digests."
        )
    return CorpusSnapshot(
        path=LOCKED_CORPUS_PATH,
        collection=LOCKED_CORPUS_COLLECTION,
        expected_chunk_count=LOCKED_CORPUS_CHUNK_COUNT,
        extract_artifact=LOCKED_CORPUS_EXTRACT_ARTIFACT,
        identity_digest=LOCKED_IDENTITY_DIGEST,
        metadata_text_digest=LOCKED_METADATA_TEXT_DIGEST,
        source_path_as_recorded=extract_index.source_path_as_recorded,
        source_collection_as_recorded=extract_index.source_collection_as_recorded,
    )


def _validate_generation(raw: Any, source_path: str) -> tuple[str, str]:
    if not isinstance(raw, dict):
        raise QaCitationDatasetError(
            f"QA/citation dataset {source_path}: generation must be an object with "
            f"model and prompt_version. Got {type(raw).__name__}."
        )
    model = _require_non_empty_string(
        raw.get("model"), field="generation.model", where=source_path
    )
    prompt_version = _require_non_empty_string(
        raw.get("prompt_version"), field="generation.prompt_version", where=source_path
    )
    return model, prompt_version


def _validate_case(
    raw: Any,
    *,
    index: int,
    source_path: str,
    extract_index: LockedExtractIndex,
) -> QaCitationCase:
    where = f"{source_path}, case index {index}"
    if not isinstance(raw, dict):
        raise QaCitationDatasetError(f"{where}: case must be a JSON object, got {type(raw).__name__}.")
    unknown = sorted(set(raw) - _ALLOWED_CASE_KEYS)
    if unknown:
        raise QaCitationDatasetError(
            f"{where}: unsupported field(s) {unknown}. Unknown fields are rejected."
        )

    case_id = _require_non_empty_string(raw.get("case_id"), field="case_id", where=where)
    question = _require_non_empty_string(raw.get("question"), field="question", where=where)
    category = _require_non_empty_string(raw.get("category"), field="category", where=where)
    difficulty = _require_non_empty_string(raw.get("difficulty"), field="difficulty", where=where)
    case_type = raw.get("case_type")
    if case_type not in CASE_TYPES:
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): case_type must be one of "
            f"{sorted(CASE_TYPES)!r}, got {case_type!r}. "
            "Live datasets are student-support or in-scope insufficient-evidence only."
        )
    labeling_status = str(raw.get("labeling_status") or "").strip().lower()
    if labeling_status not in LABELING_STATUSES:
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): labeling_status must be one of "
            f"{sorted(LABELING_STATUSES)!r}, got {raw.get('labeling_status')!r}."
        )
    generation_model = _require_non_empty_string(
        raw.get("generation_model"), field="generation_model", where=where
    )
    generation_prompt_version = _require_non_empty_string(
        raw.get("generation_prompt_version"), field="generation_prompt_version", where=where
    )

    audience = raw.get("audience")
    if audience is not None:
        if audience != "student":
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): audience must be the exact string 'student' "
                f"when present, got {audience!r}. Values are not coerced."
            )

    reviewer_notes = raw.get("reviewer_notes")
    if reviewer_notes is not None and not isinstance(reviewer_notes, str):
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): reviewer_notes must be a string when present."
        )

    faculty_fields = {
        "case_id": case_id,
        "question": question,
        "category": category,
        "reviewer_notes": reviewer_notes or "",
    }
    faculty_hits: list[str] = []
    for field_name, text in faculty_fields.items():
        hits = faculty_scope_violations(text)
        if hits:
            faculty_hits.append(f"{field_name} matches {list(hits)}")
    if faculty_hits:
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): faculty-related case rejected. "
            "Evaluation scope is student-facing university services only "
            f"(faculty as intended audience, not a student asking about a college/faculty). "
            f"{'; '.join(faculty_hits)}."
        )

    if difficulty not in LIVE_DIFFICULTIES:
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): difficulty {difficulty!r} is not allowed. "
            f"Live difficulties are {sorted(LIVE_DIFFICULTIES)!r}."
        )

    if case_type == CASE_TYPE_LABELED_STUDENT_SUPPORT:
        if difficulty not in LABELED_STUDENT_SUPPORT_DIFFICULTIES:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): labeled_student_support difficulty must be "
                f"one of {sorted(LABELED_STUDENT_SUPPORT_DIFFICULTIES)!r}, got {difficulty!r}."
            )
    else:
        if difficulty not in INSUFFICIENT_EVIDENCE_DIFFICULTIES:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): insufficient_evidence difficulty must be "
                f"'insufficient_evidence', got {difficulty!r}."
            )

    document_ids = _validate_document_ids(
        raw.get("supporting_document_ids"), where=where, case_id=case_id
    )
    chunk_ids = _validate_chunk_ids(
        raw.get("supporting_chunk_ids"), where=where, case_id=case_id
    )
    evidence = _validate_evidence(
        raw.get("reference_evidence"), where=where, case_id=case_id
    )
    reference_answer = raw.get("reference_answer")
    if reference_answer is not None and not isinstance(reference_answer, str):
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): reference_answer must be a string or null, "
            f"got {type(reference_answer).__name__}."
        )
    if isinstance(reference_answer, str) and not reference_answer.strip():
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): reference_answer must not be empty or whitespace. "
            "Use null only for insufficient_evidence cases."
        )
    if isinstance(reference_answer, str):
        reference_answer = reference_answer.strip()

    if case_type == CASE_TYPE_INSUFFICIENT_EVIDENCE:
        if reference_answer is not None:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): insufficient_evidence cases must have "
                "reference_answer=null; a reference answer is not allowed."
            )
        if document_ids or chunk_ids or evidence:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): insufficient_evidence cases must not "
                "include supporting document/chunk ids or reference_evidence, including "
                "when unlabeled."
            )
    elif labeling_status == LABELING_LABELED:
        if reference_answer is None:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): labeled_student_support cases must have "
                "a non-null grounded reference_answer."
            )
        if not document_ids or not chunk_ids or not evidence:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): labeled_student_support cases must include "
                "grounded reference evidence (non-empty supporting_document_ids, "
                "supporting_chunk_ids, and reference_evidence). Missing evidence is rejected."
            )
        _assert_evidence_matches_ids(
            document_ids, chunk_ids, evidence, where=where, case_id=case_id
        )
        _assert_extract_membership(
            document_ids,
            chunk_ids,
            evidence,
            extract_index=extract_index,
            where=where,
            case_id=case_id,
        )
    elif document_ids or chunk_ids or evidence:
        _assert_evidence_matches_ids(
            document_ids, chunk_ids, evidence, where=where, case_id=case_id
        )
        _assert_extract_membership(
            document_ids,
            chunk_ids,
            evidence,
            extract_index=extract_index,
            where=where,
            case_id=case_id,
        )

    return QaCitationCase(
        case_id=case_id,
        question=question,
        category=category,
        difficulty=difficulty,
        case_type=case_type,
        labeling_status=labeling_status,
        reference_answer=reference_answer,
        supporting_document_ids=document_ids,
        supporting_chunk_ids=chunk_ids,
        reference_evidence=evidence,
        generation_model=generation_model,
        generation_prompt_version=generation_prompt_version,
        reviewer_notes=reviewer_notes,
        audience=audience,
    )


def _validate_document_ids(raw: Any, *, where: str, case_id: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): supporting_document_ids must be a list."
        )
    ids: list[str] = []
    for index, item in enumerate(raw):
        if not is_valid_document_id(item if isinstance(item, str) else ""):
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): malformed document identifier at "
                f"supporting_document_ids[{index}]: {item!r}."
            )
        ids.append(item)
    return tuple(ids)


def _validate_chunk_ids(raw: Any, *, where: str, case_id: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): supporting_chunk_ids must be a list."
        )
    ids: list[str] = []
    for index, item in enumerate(raw):
        try:
            parse_citation_id(item if isinstance(item, str) else "")
        except QaCitationDatasetError as exc:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): malformed chunk identifier at "
                f"supporting_chunk_ids[{index}]: {item!r}."
            ) from exc
        ids.append(item)
    return tuple(ids)


def _validate_evidence(raw: Any, *, where: str, case_id: str) -> tuple[ReferenceEvidence, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): reference_evidence must be a list."
        )
    spans: list[ReferenceEvidence] = []
    for index, item in enumerate(raw):
        loc = f"{where} (case_id={case_id!r}), reference_evidence[{index}]"
        if not isinstance(item, dict):
            raise QaCitationDatasetError(f"{loc}: must be an object.")
        unknown = sorted(set(item) - _ALLOWED_EVIDENCE_KEYS)
        if unknown:
            raise QaCitationDatasetError(f"{loc}: unsupported field(s) {unknown}.")
        chunk_id = item.get("chunk_id")
        document_id = item.get("document_id")
        excerpt = item.get("excerpt")
        try:
            parsed_document_id, _parsed_index = parse_citation_id(
                chunk_id if isinstance(chunk_id, str) else ""
            )
        except QaCitationDatasetError as exc:
            raise QaCitationDatasetError(
                f"{loc}: malformed chunk identifier {chunk_id!r}."
            ) from exc
        if not is_valid_document_id(document_id if isinstance(document_id, str) else ""):
            raise QaCitationDatasetError(
                f"{loc}: malformed document identifier {document_id!r}."
            )
        if parsed_document_id != document_id:
            raise QaCitationDatasetError(
                f"{loc}: chunk_id {chunk_id!r} does not belong to document_id {document_id!r}."
            )
        if not isinstance(excerpt, str) or not excerpt.strip():
            raise QaCitationDatasetError(
                f"{loc}: excerpt must be a non-empty string (grounded evidence is required)."
            )
        page = item.get("page")
        if page is not None and not (isinstance(page, int) and not isinstance(page, bool) and page >= 0):
            raise QaCitationDatasetError(
                f"{loc}: page must be a non-negative integer or null, got {page!r}."
            )
        for optional in ("source_filename", "title", "source_section"):
            value = item.get(optional)
            if value is not None and not isinstance(value, str):
                raise QaCitationDatasetError(f"{loc}: {optional} must be a string when present.")
        spans.append(
            ReferenceEvidence(
                chunk_id=chunk_id,
                document_id=document_id,
                excerpt=excerpt.strip(),
                source_filename=item.get("source_filename"),
                title=item.get("title"),
                source_section=item.get("source_section"),
                page=page,
            )
        )
    return tuple(spans)


def _assert_evidence_matches_ids(
    document_ids: Sequence[str],
    chunk_ids: Sequence[str],
    evidence: Sequence[ReferenceEvidence],
    *,
    where: str,
    case_id: str,
) -> None:
    evidence_docs = {span.document_id for span in evidence}
    evidence_chunks = {span.chunk_id for span in evidence}
    missing_docs = [doc_id for doc_id in document_ids if doc_id not in evidence_docs]
    missing_chunks = [chunk_id for chunk_id in chunk_ids if chunk_id not in evidence_chunks]
    if missing_docs or missing_chunks:
        raise QaCitationDatasetError(
            f"{where} (case_id={case_id!r}): supporting ids must appear in reference_evidence "
            f"(missing document_ids={missing_docs}, missing chunk_ids={missing_chunks})."
        )


def _assert_extract_membership(
    document_ids: Sequence[str],
    chunk_ids: Sequence[str],
    evidence: Sequence[ReferenceEvidence],
    *,
    extract_index: LockedExtractIndex,
    where: str,
    case_id: str,
) -> None:
    for chunk_id in chunk_ids:
        record = extract_index.by_chunk_id.get(chunk_id)
        if record is None:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): supporting_chunk_id {chunk_id!r} is not in "
                "the locked extract snapshot. Syntactically valid IDs that are missing from "
                "the extract are rejected."
            )
        parsed_document_id, parsed_index = parse_citation_id(chunk_id)
        if parsed_document_id != record.document_id or parsed_index != record.chunk_index:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): {chunk_id!r} does not match the extract "
                f"record identity {record.document_id!r}::{record.chunk_index}."
            )
    for span in evidence:
        record = extract_index.by_chunk_id.get(span.chunk_id)
        if record is None:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): reference_evidence chunk_id {span.chunk_id!r} "
                "is not in the locked extract snapshot."
            )
        if span.document_id != record.document_id:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): reference_evidence document_id "
                f"{span.document_id!r} does not match extract record document_id "
                f"{record.document_id!r} for {span.chunk_id!r}."
            )
        _parsed_document_id, parsed_index = parse_citation_id(span.chunk_id)
        if parsed_index != record.chunk_index:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): chunk index in {span.chunk_id!r} does not "
                f"match extract record chunk_index {record.chunk_index}."
            )
        if span.excerpt not in record.text:
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): excerpt is not a verbatim contiguous "
                f"substring of extract record text for {span.chunk_id!r} "
                f"(rule={EXCERPT_MATCH_RULE}). This check is textual membership, not "
                "semantic correctness of the reference answer."
            )
    for document_id in document_ids:
        if not any(extract_index.by_chunk_id[chunk_id].document_id == document_id for chunk_id in chunk_ids):
            raise QaCitationDatasetError(
                f"{where} (case_id={case_id!r}): supporting_document_id {document_id!r} "
                "does not match any supporting extract chunk."
            )


def _require_non_empty_string(value: Any, *, field: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QaCitationDatasetError(
            f"{where}: {field} must be a non-empty string, got {value!r}."
        )
    return value.strip()

"""Stage 3.1 evaluation-corpus identity.

Stage 2 locked corpus identity to the extract artifact's
``identity_digest`` and ``metadata_text_digest``. Matching
``chroma_evaluation`` / ``aska_evaluation`` chunk *count* 691 is not
enough. This module opens that evaluation sqlite read-only, reuses the
reviewed recovery extract/digest functions, and compares IDs, identity
metadata, and text to the locked extract.

It does not execute the chatbot, call a judge, or write to Chroma.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.evaluation.qa_citation_dataset import (
    LOCKED_CORPUS_CHUNK_COUNT,
    LOCKED_CORPUS_COLLECTION,
    LOCKED_CORPUS_EXTRACT_ARTIFACT,
    LOCKED_CORPUS_PATH,
    LOCKED_IDENTITY_DIGEST,
    LOCKED_METADATA_TEXT_DIGEST,
    LOCKED_SOURCE_COLLECTION_AS_RECORDED,
    locked_extract_path,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.chroma_sqlite_recovery import (  # noqa: E402
    compute_identity_digest,
    compute_records_digest,
    discover_metadata_segment_id,
    extract_records,
    open_source_readonly,
    sha256_of_file,
)

EVALUATION_CHROMA_DIR = _BACKEND_ROOT / "data" / "chroma_evaluation"
EVALUATION_SQLITE_PATH = EVALUATION_CHROMA_DIR / "chroma.sqlite3"
EVALUATION_COLLECTION = LOCKED_CORPUS_COLLECTION
PRODUCTION_CHROMA_DIR = _BACKEND_ROOT / "data" / "chroma"


class CorpusIdentityError(ValueError):
    """The evaluation Chroma store does not correspond to the locked extract."""


@dataclass(frozen=True)
class EvaluationCorpusIdentity:
    verified_at: str
    evaluation_path: str
    evaluation_collection: str
    evaluation_sqlite_sha256: str
    evaluation_record_count: int
    evaluation_exclusion_count: int
    evaluation_identity_digest: str
    evaluation_metadata_text_digest: str
    extract_artifact: str
    extract_identity_digest: str
    extract_metadata_text_digest: str
    extract_record_count: int
    extract_source_path_as_recorded: str
    extract_source_collection_as_recorded: str
    extract_source_sqlite_sha256: str
    identity_digest_matches: bool
    metadata_text_digest_matches: bool
    embedding_id_set_equal: bool
    text_exact_match_count: int
    text_mismatch_count: int
    document_id_mismatch_count: int
    metadata_chunk_id_mismatch_count: int
    chunk_index_mismatch_count: int
    sqlite_file_hash_equals_extract_source: bool
    corresponds: bool
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluation_chroma_dir() -> Path:
    return EVALUATION_CHROMA_DIR


def verify_evaluation_corpus(*, persist_report_path: Path | None = None) -> EvaluationCorpusIdentity:
    """Prove ``chroma_evaluation`` / ``aska_evaluation`` equals the locked extract.

    Uses read-only sqlite extraction. A matching count of 691 is required
    but not sufficient: both locked digests, the embedding/chunk ID set,
    verbatim text, and identity metadata must match.
    """
    if not EVALUATION_SQLITE_PATH.is_file():
        raise CorpusIdentityError(
            f"Evaluation Chroma sqlite not found: {EVALUATION_SQLITE_PATH}. "
            "Cannot establish corpus correspondence."
        )
    if EVALUATION_CHROMA_DIR.resolve() == PRODUCTION_CHROMA_DIR.resolve():
        raise CorpusIdentityError(
            "Evaluation Chroma path resolved to production Chroma. Refusing."
        )

    extract_path = locked_extract_path()
    if not extract_path.is_file():
        raise CorpusIdentityError(f"Locked extract artifact not found: {extract_path}")

    extract = json.loads(extract_path.read_text(encoding="utf-8"))
    validation = extract.get("validation") or {}
    source = extract.get("source") or {}
    extract_identity = str(validation.get("identity_digest") or "")
    extract_meta_text = str(validation.get("metadata_text_digest") or "")
    if extract_identity != LOCKED_IDENTITY_DIGEST:
        raise CorpusIdentityError(
            "Locked extract file identity_digest does not match Stage 2 lock. "
            f"file={extract_identity} locked={LOCKED_IDENTITY_DIGEST}"
        )
    if extract_meta_text != LOCKED_METADATA_TEXT_DIGEST:
        raise CorpusIdentityError(
            "Locked extract file metadata_text_digest does not match Stage 2 lock. "
            f"file={extract_meta_text} locked={LOCKED_METADATA_TEXT_DIGEST}"
        )

    eval_sqlite_sha256 = sha256_of_file(EVALUATION_SQLITE_PATH)
    extract_source_sha256 = str(source.get("sha256_before") or "")

    conn = open_source_readonly(EVALUATION_SQLITE_PATH)
    try:
        collections = [row[0] for row in conn.execute("SELECT name FROM collections")]
        if EVALUATION_COLLECTION not in collections:
            raise CorpusIdentityError(
                f"Evaluation sqlite collections {collections!r} do not include "
                f"{EVALUATION_COLLECTION!r}."
            )
        segment_id = discover_metadata_segment_id(conn, EVALUATION_COLLECTION)
        records, exclusions = extract_records(conn, segment_id=segment_id)
    finally:
        conn.close()

    eval_identity = compute_identity_digest(records)
    eval_meta_text = compute_records_digest(records)
    extract_records_json = extract.get("records") or []
    extract_ids = [str(row.get("chunk_id") or "") for row in extract_records_json]
    eval_ids = [record.embedding_id for record in records]
    extract_id_set = set(extract_ids)
    eval_id_set = set(eval_ids)

    extract_by_id = {str(row.get("chunk_id") or ""): row for row in extract_records_json}
    eval_by_id = {record.embedding_id: record for record in records}
    shared = extract_id_set & eval_id_set
    text_match = 0
    text_mismatch = 0
    document_mismatch = 0
    chunk_id_mismatch = 0
    chunk_index_mismatch = 0
    for chunk_id in shared:
        extract_row = extract_by_id[chunk_id]
        eval_row = eval_by_id[chunk_id]
        extract_meta = extract_row.get("metadata") or {}
        if extract_row.get("text") == eval_row.text:
            text_match += 1
        else:
            text_mismatch += 1
        if str(extract_meta.get("document_id")) != str(eval_row.metadata.get("document_id")):
            document_mismatch += 1
        if str(extract_meta.get("chunk_id")) != str(eval_row.metadata.get("chunk_id")):
            chunk_id_mismatch += 1
        if extract_meta.get("chunk_index") != eval_row.metadata.get("chunk_index"):
            chunk_index_mismatch += 1

    identity_matches = eval_identity == LOCKED_IDENTITY_DIGEST
    meta_text_matches = eval_meta_text == LOCKED_METADATA_TEXT_DIGEST
    id_set_equal = extract_id_set == eval_id_set
    corresponds = (
        len(records) == LOCKED_CORPUS_CHUNK_COUNT
        and len(exclusions) == 0
        and int(validation.get("record_count") or 0) == LOCKED_CORPUS_CHUNK_COUNT
        and identity_matches
        and meta_text_matches
        and id_set_equal
        and len(extract_ids) == LOCKED_CORPUS_CHUNK_COUNT
        and len(eval_ids) == LOCKED_CORPUS_CHUNK_COUNT
        and len(extract_id_set) == LOCKED_CORPUS_CHUNK_COUNT
        and len(eval_id_set) == LOCKED_CORPUS_CHUNK_COUNT
        and text_mismatch == 0
        and text_match == LOCKED_CORPUS_CHUNK_COUNT
        and document_mismatch == 0
        and chunk_id_mismatch == 0
        and chunk_index_mismatch == 0
        and str(source.get("collection_name") or "") == LOCKED_SOURCE_COLLECTION_AS_RECORDED
    )

    limitations = (
        "Evaluation sqlite file bytes differ from the extract source sqlite "
        f"({EVALUATION_SQLITE_PATH.name} vs recorded "
        f"{source.get('path')}). Collection names also differ "
        f"({EVALUATION_COLLECTION} vs {LOCKED_SOURCE_COLLECTION_AS_RECORDED}). "
        "Correspondence is the recovered records (embedding/chunk IDs, "
        "identity metadata, verbatim text) and the two locked digests, not "
        "byte-identity of the sqlite files.",
        "Vectors/HNSW binary files are not hashed. Identity uses the same "
        "sqlite metadata+text extraction as the locked artifact.",
    )

    identity = EvaluationCorpusIdentity(
        verified_at=datetime.now(timezone.utc).isoformat(),
        evaluation_path=LOCKED_CORPUS_PATH,
        evaluation_collection=EVALUATION_COLLECTION,
        evaluation_sqlite_sha256=eval_sqlite_sha256,
        evaluation_record_count=len(records),
        evaluation_exclusion_count=len(exclusions),
        evaluation_identity_digest=eval_identity,
        evaluation_metadata_text_digest=eval_meta_text,
        extract_artifact=LOCKED_CORPUS_EXTRACT_ARTIFACT,
        extract_identity_digest=extract_identity,
        extract_metadata_text_digest=extract_meta_text,
        extract_record_count=int(validation.get("record_count") or 0),
        extract_source_path_as_recorded=str(source.get("path") or ""),
        extract_source_collection_as_recorded=str(source.get("collection_name") or ""),
        extract_source_sqlite_sha256=extract_source_sha256,
        identity_digest_matches=identity_matches,
        metadata_text_digest_matches=meta_text_matches,
        embedding_id_set_equal=id_set_equal,
        text_exact_match_count=text_match,
        text_mismatch_count=text_mismatch,
        document_id_mismatch_count=document_mismatch,
        metadata_chunk_id_mismatch_count=chunk_id_mismatch,
        chunk_index_mismatch_count=chunk_index_mismatch,
        sqlite_file_hash_equals_extract_source=eval_sqlite_sha256 == extract_source_sha256,
        corresponds=corresponds,
        limitations=limitations,
    )

    if persist_report_path is not None:
        persist_report_path.parent.mkdir(parents=True, exist_ok=True)
        persist_report_path.write_text(
            json.dumps(identity.as_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if not corresponds:
        raise CorpusIdentityError(
            "Evaluation Chroma does not correspond to the locked extract. "
            f"count={len(records)} identity_match={identity_matches} "
            f"metadata_text_match={meta_text_matches} id_set_equal={id_set_equal} "
            f"text_mismatch={text_mismatch} document_id_mismatch={document_mismatch} "
            f"chunk_id_mismatch={chunk_id_mismatch} "
            f"chunk_index_mismatch={chunk_index_mismatch}. "
            "Do not execute the QA answer-capture benchmark."
        )
    return identity

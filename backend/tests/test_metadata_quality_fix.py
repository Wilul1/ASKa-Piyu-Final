"""Focused tests for the 2026-10-05 metadata-quality fix (title selection
+ office/responsible_office classification), triggered by real v29
production Extract-only exports showing e.g. "PRAYER" -> College of
Agriculture, "I. General Information" -> College of Agriculture, and
historical-development prose -> Graduate Studies Office / Office of the
President, purely because those offices/colleges/programs were MENTIONED
in passing, not because the content is actually governed by them.

Extraction, text cleaning, TOC removal, header/footer removal, chunk
boundaries, and overlap behavior are explicitly FROZEN and untouched by
this fix -- nothing here imports or exercises remove_toc_blocks,
_strip_repeated_headers_footers, chunk_document_text's boundary logic,
or _safe_suffix. Only:
  - app.services.admin.digital_ingestion._attach_section_headings /
    _heading_offsets (title selection: which heading governs a chunk)
  - app.services.admin.knowledge_base_pipeline.is_trustworthy_title_heading
    / _title_from_chunk (title selection: fallback/validation)
  - app.services.knowledge_taxonomy.enrich_chunks_with_category_metadata
    / _office_assignment_has_ownership_evidence (office classification,
    ingestion-only -- classify_chunk/classify_question, shared with live
    ticket routing, are never modified or called with different inputs
    here)

Safety: never touches a real Chroma client, never makes a real HTTP call.
All fixtures are synthetic/generic; no real manual content is copied.
"""

from __future__ import annotations

from unittest.mock import patch

from app.services.admin.digital_ingestion import build_chunks_with_pages
from app.services.admin.knowledge_base_pipeline import (
    _title_from_chunk,
    is_trustworthy_title_heading,
)
from app.services.chroma_store import KnowledgeBaseStore
from app.services.chunking import DocumentChunk
from app.services.knowledge_taxonomy import (
    UNASSIGNED_OFFICE,
    enrich_chunks_with_category_metadata,
)


def make_fake_store():
    class FakeChromaCollection:
        def __init__(self):
            self._records: dict[str, dict] = {}
            self.add_call_count = 0
            self.delete_call_count = 0

        def add(self, *, ids, documents, metadatas):
            self.add_call_count += 1
            for _id, meta in zip(ids, metadatas):
                self._records[_id] = meta

        def get(self, where=None, include=None, limit=None, offset=0, ids=None):
            return {"ids": [], "metadatas": []}

        def delete(self, *, ids):
            self.delete_call_count += 1

        def count(self):
            return len(self._records)

    collection = FakeChromaCollection()
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection
    return store, collection


# --- 1/3/4: generic institutional prose does not borrow a mentioned ------
#            office/college/program's identity


def test_prayer_text_merely_mentioning_agriculture_stays_unassigned():
    chunks = [
        DocumentChunk(
            text=(
                "Grant me wisdom and patience as I grow in knowledge, much like the "
                "fields of agriculture our founders once cultivated with their own "
                "hands, so that I may harvest understanding throughout my studies."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "PRAYER"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Handbook", source_document="handbook_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == UNASSIGNED_OFFICE
    assert enriched[0].metadata["responsible_office"] == UNASSIGNED_OFFICE


def test_historical_prose_mentioning_college_of_agriculture_stays_unassigned():
    chunks = [
        DocumentChunk(
            text=(
                "In 1957, the school was converted into Baybay Agricultural and "
                "Vocational School, later becoming the Baybay National College of "
                "Agriculture and Technology, before its eventual integration into "
                "the present-day university system under a new charter."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "II. Historical Development"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Manual", source_document="manual_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == UNASSIGNED_OFFICE
    assert enriched[0].metadata["responsible_office"] == UNASSIGNED_OFFICE


def test_historical_prose_mentioning_graduate_programs_stays_unassigned():
    chunks = [
        DocumentChunk(
            text=(
                "The institution later expanded its curricular offerings, launching "
                "its first graduate programs and awarding its first master's degrees "
                "as part of a broader push toward university status during that decade."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "Historical Development"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Manual", source_document="manual_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == UNASSIGNED_OFFICE
    assert enriched[0].metadata["responsible_office"] == UNASSIGNED_OFFICE


def test_generic_history_mentioning_a_president_stays_unassigned():
    chunks = [
        DocumentChunk(
            text=(
                "Under the leadership of its third president, the university opened "
                "several satellite campuses and signed cooperation agreements with "
                "partner institutions abroad during a period of rapid expansion."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "Historical Development"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Manual", source_document="manual_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == UNASSIGNED_OFFICE
    assert enriched[0].metadata["responsible_office"] == UNASSIGNED_OFFICE


def test_campus_description_does_not_become_college_ownership():
    chunks = [
        DocumentChunk(
            text=(
                "This campus offers a wide range of curricular programs across "
                "several colleges, including Engineering, Nursing, Hospitality "
                "Management, and Agriculture, serving a diverse student population."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "I. General Information"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Manual", source_document="manual_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == UNASSIGNED_OFFICE


# --- 5/6/7: explicit responsibility evidence CAN still assign an office --


def test_explicit_osas_responsibility_language_assigns_osas():
    chunks = [
        DocumentChunk(
            text=(
                "Any case of student discipline or welfare concern shall be handled "
                "by the Office of Student Affairs and Services, which shall "
                "investigate the matter and recommend appropriate action."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "Student Discipline"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Handbook", source_document="handbook_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == "Office of Student Affairs"


def test_explicit_registrar_responsibility_language_assigns_registrar():
    chunks = [
        DocumentChunk(
            text=(
                "Requests for enrollment validation and subject registration shall "
                "be processed by the Registrar, who shall verify each student's "
                "academic load before approving the registration."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "Registration Procedure"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Handbook", source_document="handbook_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == "Registrar"


def test_explicit_guidance_responsibility_language_assigns_guidance_office():
    chunks = [
        DocumentChunk(
            text=(
                "Admission examinations and career guidance interviews shall be "
                "administered by the Guidance Office, which shall also provide "
                "counseling referrals for students in need of further assistance."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "Admission Requirements"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Handbook", source_document="handbook_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == "Guidance Office"


def test_heading_authoritatively_naming_the_office_still_assigns_it():
    """An authoritative structural heading that IS the service/office
    name (not merely a passing mention in body prose) is still strong
    enough evidence on its own, even without explicit "shall be
    processed by" language in the body text."""
    chunks = [
        DocumentChunk(
            text=(
                "Interested students may avail of career guidance sessions and "
                "individual counseling appointments scheduled throughout the term."
            ),
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "Guidance Services"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Handbook", source_document="handbook_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == "Guidance Office"


# --- 8: ambiguous content becomes Unassigned --------------------------------


def test_ambiguous_content_with_no_office_evidence_stays_unassigned():
    chunks = [
        DocumentChunk(
            text="Xqzvyk flarnum trebozit wobbleplex zyntharon quibberfluxx.",
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Handbook", source_document="handbook_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == UNASSIGNED_OFFICE


def test_explicit_office_metadata_upstream_is_never_overwritten():
    chunks = [
        DocumentChunk(
            text="Any text at all -- the office was already explicitly set upstream.",
            chunk_index=0,
            char_start=0,
            metadata={"office": "Registrar", "document_type": "information"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Handbook", source_document="handbook_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == "Registrar"


# --- 9/10/11: title selection ------------------------------------------------


def test_real_structural_headings_remain_trustworthy_titles():
    for heading in [
        "I. General Information",
        "XI. Grievance Machinery",
        "Article 6. Procedure for Major Disciplinary Actions",
        "II. Historical Development of LSPU",
        "Faculty Official Time",
        "Grading System",
    ]:
        assert is_trustworthy_title_heading(heading), f"should remain valid: {heading!r}"


def test_sentence_overlap_fragments_are_not_promoted_as_titles():
    for fragment in [
        "2. Teaching as a commitment recognizes the centrality of the learner in the",
        "3. The professor /instructor shall share with parents the responsibility of",
        "1.1. Accept his/her responsibility to maintain a professional level of",
        "1.3. Integrate individual goal with those of the strategic development",
    ]:
        assert not is_trustworthy_title_heading(fragment), f"should be rejected: {fragment!r}"


def test_honorific_prefixed_names_are_not_promoted_as_titles():
    for name_line in [
        "HON. JULIAN A. LAPITAN",
        "Dr. Nestor M. De Vera",
        "Atty. Maria Santos",
    ]:
        assert not is_trustworthy_title_heading(name_line), f"should be rejected: {name_line!r}"


def test_numbered_body_clause_never_becomes_section_heading_in_a_real_chunk():
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        page_texts = [
            "A. Commitment of Faculty\n\n"
            "1. Teaching is a personal commitment of oneself to others.\n\n"
            "2. Teaching as a commitment recognizes the centrality of the "
            "learner in the educational process and adjusts to his or her "
            "needs and concerns.\n\n"
            "3. The professor shall share with parents the responsibility "
            "of ensuring the proper growth and development of the learner "
            "throughout the entire academic year.\n"
        ]
        chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=200, chunk_overlap=20, title="T", source_filename="clause_test.pdf"
        )
    assert chunks
    for chunk in chunks:
        heading = chunk.metadata.get("section_heading")
        assert heading != "2. Teaching as a commitment recognizes the centrality of the learner in the"
        assert heading != "3. The professor shall share with parents the responsibility of"


def test_letterhead_address_block_is_never_promoted_as_a_title():
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        page_texts = [
            "Example State Polytechnic University (ESPU)\n"
            "Province of Example\n"
            "Regular Campuses:\n"
            "ESPU-Main Campus\n"
            "Extension/Satellite Campuses:\n"
            "ESPU-North Campus\n"
            "ESPU-South Campus\n"
            "ESPU-West Pilot Extension Classes\n\n"
            "Grievance Machinery\n\n"
            "Any faculty member who believes a decision was unfair may file a "
            "written grievance with the designated committee within fifteen "
            "working days of the event giving rise to the complaint itself.\n"
        ]
        chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=300, chunk_overlap=30, title="T", source_filename="letterhead_test.pdf"
        )
    assert chunks
    for chunk in chunks:
        heading = chunk.metadata.get("section_heading")
        assert heading not in {
            "Example State Polytechnic University (ESPU)",
            "Province of Example",
            "Regular Campuses:",
            "ESPU-Main Campus",
            "Extension/Satellite Campuses:",
            "ESPU-North Campus",
            "ESPU-South Campus",
            "ESPU-West Pilot Extension Classes",
        }


def test_compound_chapter_article_heading_still_governs_its_chunk():
    """A legitimate 2-3 line compound heading (Chapter marker + title,
    immediately followed by an Article marker) must NOT be mistaken for
    a letterhead/roster dense run just because its lines are packed
    tightly together too."""
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        page_texts = [
            "Chapter 3\n"
            "Undergraduate Academic Policies\n\n"
            "Article 1. Classifications of Students\n\n"
            "Every enrolled student is classified as regular or irregular "
            "depending on the number and sequence of units taken each term "
            "relative to the officially prescribed curriculum.\n"
        ]
        chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=300, chunk_overlap=30, title="T", source_filename="compound_heading_test.pdf"
        )
    assert chunks
    for chunk in chunks:
        assert chunk.metadata.get("section_heading") == "Article 1. Classifications of Students"


def test_chunk_spanning_into_next_section_adopts_the_later_heading():
    """When a short section's trailing content is packed into the same
    chunk as the START of the next section, the chunk's title must
    reflect whichever heading governs MOST of its own text -- not
    whatever heading merely preceded the chunk's starting offset."""
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        page_texts = [
            "PRAYER\n\n"
            "In You I trust, always.\n\n"
            "Chapter 1\n"
            "Historical Development and Officials\n\n"
            "Historical Development\n\n"
            "The university was initially established as a provincial "
            "secondary school and has since grown into a multi-campus "
            "state institution serving thousands of students each year.\n"
        ]
        chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=260, chunk_overlap=20, title="T", source_filename="span_test.pdf"
        )
    assert chunks
    # the LAST chunk (containing the bulk of the historical narrative)
    # must be governed by "Historical Development", never "PRAYER"
    last_chunk = chunks[-1]
    assert "university was initially established" in last_chunk.text
    assert last_chunk.metadata.get("section_heading") != "PRAYER"


# --- 12: extraction/chunk text is never touched by this fix ----------------


def test_metadata_enrichment_never_changes_chunk_text():
    original_text = "Some representative policy text that must remain byte-identical."
    chunks = [
        DocumentChunk(
            text=original_text,
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information", "section_heading": "Some Heading"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="T", source_document="t.pdf", allow_llm=False
    )
    assert enriched[0].text == original_text


# --- ticket-routing (classify_question) is completely untouched ------------


def test_classify_question_still_uses_best_guess_behavior_unchanged():
    """classify_question (live student ticket routing) must NEVER go
    through the new ownership-evidence gate -- that gate only exists
    inside enrich_chunks_with_category_metadata (ingestion-time)."""
    from app.services.knowledge_taxonomy import classify_question

    result = classify_question("How do I get my Transcript of Records?")
    # best-guess behavior unchanged: a real, specific question about a
    # named service still resolves to a specific office, not Unassigned.
    assert result.office != UNASSIGNED_OFFICE
    assert result.office == "Registrar"

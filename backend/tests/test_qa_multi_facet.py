"""Multi-part question grounding: question parts, retrieval evidence, guardrails."""

from unittest.mock import patch

from app.services.chroma_store import RetrievedChunk
from app.services.qa.groq_answer_service import ASKA_PIYU_SYSTEM_PROMPT, build_groq_messages
from app.services.qa.multi_facet import (
    FacetEvidence,
    analyze_facet_coverage,
    build_cross_article_notes,
    build_facet_evidence,
    build_grounding_notes,
    distinct_source_articles,
    facet_recovery_keys,
    facet_retrieval_queries,
    is_conflict_question,
    is_precedence_question,
    partition_off_topic,
    split_question_facets,
)
from app.services.qa.service_answer_formatter import (
    _steps_from_metadata,
    _steps_from_text,
)
from app.services.qa.question_answering import (
    FACET_RECOVERY_REASON,
    _capped_for_facet_gap,
    _chunk_heading,
    _chunk_merge_key,
    _confidence_for,
    _restore_missing_facet_context,
    answer_qa_question,
)

OJT_QUESTION = (
    "I want to go on OJT next term, but I still have an incomplete subject and "
    "unpaid fees. Which requirement fails first — academic, clearance, or deployment?"
)

CONFLICT_QUESTION = (
    "The handbook and the office FAQ disagree about late registration. Which should I follow?"
)


def kb_chunk(
    section: str,
    text: str,
    *,
    score: float = 0.86,
    office: str = "Colleges",
) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=section.lower().replace(" ", "-"),
        title="LSPU Citizen's Charter",
        source_filename="charter.pdf",
        chunk_index=0,
        text=text,
        relevance_score=score,
        original_score=score - 0.05,
        reranked_score=score,
        rerank_reasons=["boost_service_procedure"],
        metadata={
            "section": section,
            "source_section": section,
            "office": office,
            "page_start": 89,
            "audience": "both",
        },
    )


def evidence_for(question, facets, found, *, baseline=()):
    """Evidence as the pipeline builds it: what each part of the question retrieved."""
    by_query = {
        facet.retrieval_query: [_chunk_merge_key(chunk) for chunk in found.get(index, [])]
        for index, facet in enumerate(facets)
    }
    by_query[question] = [_chunk_merge_key(chunk) for chunk in baseline]
    return build_facet_evidence(by_query, facets, baseline_query=question)


def coverage_for(question, found, *, selected, baseline=()):
    facets = split_question_facets(question)
    evidence = evidence_for(question, facets, found, baseline=baseline)
    return facets, evidence, analyze_facet_coverage(
        question,
        facets,
        selected,
        evidence,
        key_of=_chunk_merge_key,
        heading_of=_chunk_heading,
    )


# --- splitting the question into the parts the student wrote -----------------


def test_bundled_question_splits_into_the_parts_the_student_wrote():
    labels = [facet.label for facet in split_question_facets(OJT_QUESTION)]

    assert "I want to go on OJT next term" in labels
    assert "I still have an incomplete subject" in labels
    assert "unpaid fees" in labels


def test_a_list_of_options_is_not_shattered_into_single_words():
    """"academic, clearance, or deployment" is one ask, not three."""
    labels = [facet.label for facet in split_question_facets(OJT_QUESTION)]

    assert any("academic, clearance, or deployment" in label for label in labels)
    assert "clearance" not in labels


def test_single_topic_question_has_one_part_and_no_subqueries():
    facets = split_question_facets("Where can I get an excuse slip if I was absent?")

    assert len(facets) == 1
    assert facet_retrieval_queries(facets) == []


def test_subqueries_ask_the_retriever_about_each_part_separately():
    facets = split_question_facets(OJT_QUESTION)

    queries = facet_retrieval_queries(facets)

    assert "unpaid fees" in queries
    assert "I still have an incomplete subject" in queries


def test_subqueries_skip_variants_the_pipeline_already_retrieves():
    facets = split_question_facets(OJT_QUESTION)

    queries = facet_retrieval_queries(facets, existing=[facets[0].retrieval_query])

    assert facets[0].retrieval_query not in queries


# --- Filipino multi-facet splitting (comma-anchored "at") --------------------
#
# Confirmed gap (v46 retrieval/context-assembly audit): split_question_facets
# only recognized English coordinating conjunctions, so an equivalent
# Filipino multi-part question never activated facet_retrieval_queries/
# build_facet_evidence/partition_off_topic/analyze_facet_coverage at all --
# it silently fell back to plain top-k retrieval for the whole bundled
# question. Fixed by adding Filipino "at" ("and") to the SAME comma-anchored
# _COORDINATION_SPLIT_RE boundary English's own comma+conjunction forms
# already use -- not to the bare, no-comma conjunction splitter, since bare
# "at" is also an ordinary English preposition ("meet at the registrar").


TOR_FEE_QUESTION_FILIPINO = (
    "Ano ang requirements para sa TOR sa bawat pahina, at magkano ang bayad?"
)

FILIPINO_CONDITIONAL_QUESTION = (
    "Kung transferee ako, ano ang requirements para sa clearance, "
    "at ilang araw ang processing time?"
)


def test_filipino_multi_part_question_splits_into_two_facets():
    """Task example A: TOR requirements and the fee are independently
    answerable parts, exactly like the existing English TOR-plus-fee case."""
    facets = split_question_facets(TOR_FEE_QUESTION_FILIPINO)
    labels = [facet.label for facet in facets]

    assert len(facets) == 2
    assert any("requirements" in label and "TOR" in label for label in labels)
    assert any("magkano ang bayad" in label for label in labels)


def test_filipino_conditional_question_separates_condition_from_second_ask():
    """Task example B: a kung-clause attached to the first ask must not be
    stripped or lost, and the second, independently-answerable item (the
    processing time) must still be recognized as its own facet."""
    facets = split_question_facets(FILIPINO_CONDITIONAL_QUESTION)
    labels = [facet.label for facet in facets]

    assert len(facets) == 2
    # The conditional relationship is preserved verbatim, not stripped.
    assert any(label.startswith("Kung transferee ako") for label in labels)
    assert any("clearance" in label for label in labels)
    assert any("processing time" in label for label in labels)


def test_english_multi_part_question_splitting_is_unchanged():
    """Task example C: the existing English TOR-plus-fee fixture must split
    exactly as before -- no regression from the Filipino addition."""
    from tests.test_qa_facet_coverage_caveats import TOR_FEE_QUESTION

    facets = split_question_facets(TOR_FEE_QUESTION)
    labels = [facet.label for facet in facets]

    assert len(facets) == 2
    assert any("TOR fee per page" in label for label in labels)
    assert any("Landbank LinkBiz processing fee" in label for label in labels)


def test_filipino_question_with_at_and_kung_but_one_real_ask_is_not_split():
    """Task example D: 'at' and 'kung' both appear, but there is only one
    thing being asked (how to validate/replace a lost ID) -- no comma
    precedes 'at', so this must stay a single facet, not fragment into
    meaningless pieces."""
    facets = split_question_facets(
        "Kung nawala ang aking ID, paano ko ito ma-validate at ma-replace agad?"
    )

    assert len(facets) == 1


def test_filipino_conditional_without_comma_before_at_is_not_split():
    """A second ordinary single-part case: 'kung ... at ...' with no comma
    before 'at' is an accepted, documented limitation -- left intact rather
    than guessed at, per the task's explicit preference."""
    facets = split_question_facets("Pwede ba mag-enroll kung may balance at walang clearance?")

    assert len(facets) == 1


def test_english_question_with_bare_at_preposition_is_not_split():
    """Regression guard: bare (comma-less) 'at' must never trigger a split,
    even though it is now a recognized Filipino conjunction at the
    comma-anchored boundary -- 'at' is also an ordinary English preposition."""
    facets = split_question_facets("What are the office hours at the registrar and library?")

    assert len(facets) == 1


# --- comma-less Filipino "at", gated on a following WH-question word -------
#
# Confirmed limitation from the read-only follow-up review: the
# comma-anchored fix above does not help a comma-less Filipino "at"
# ("...TOR at magkano ang bayad?" with no comma). This narrow extension
# splits ONLY when the word immediately after "at" is a fixed Filipino
# WH-question word, so the second piece is self-evidently its own question
# -- not a blanket "split every bare at" rule (ruled out by the review's
# own example 5: "Pwede ba pumasok ... at mag-submit ...?" would have lost
# its "Pwede ba" interrogative framing on the second piece).


def test_comma_less_filipino_at_splits_when_followed_by_a_question_word():
    """Positive case 1: 'magkano' immediately follows bare 'at'."""
    facets = split_question_facets("Ano ang requirements para sa TOR at magkano ang bayad?")
    labels = [facet.label for facet in facets]

    assert len(facets) == 2
    assert any(label == "Ano ang requirements para sa TOR" for label in labels)
    assert any(label == "magkano ang bayad" for label in labels)


def test_comma_less_filipino_at_preserves_kung_clause_on_first_facet():
    """Positive case 2: 'ilang' immediately follows bare 'at'; the leading
    'kung transferee ako' condition must stay attached to the first facet,
    not be stripped or relocated."""
    facets = split_question_facets(
        "Ano ang requirements kung transferee ako at ilang araw ang processing?"
    )
    labels = [facet.label for facet in facets]

    assert len(facets) == 2
    assert any(label == "Ano ang requirements kung transferee ako" for label in labels)
    assert any(label.startswith("ilang araw ang processing") for label in labels)


def test_comma_less_filipino_at_splits_before_saan():
    """Positive case 3: two meaningful facets, the second beginning 'saan'."""
    facets = split_question_facets("Ano ang kailangan kong dalhin at saan ko ito isusumite?")
    labels = [facet.label for facet in facets]

    assert len(facets) == 2
    assert any(label.startswith("saan") for label in labels)


def test_comma_anchored_filipino_at_example_is_unchanged_by_the_extension():
    """Preserve case 4: the existing comma-anchored example must still
    produce exactly the same two facets as before this extension."""
    facets = split_question_facets(TOR_FEE_QUESTION_FILIPINO)
    labels = [facet.label for facet in facets]

    assert len(facets) == 2
    assert "Ano ang requirements para sa TOR sa bawat pahina" in labels
    assert "magkano ang bayad" in labels


def test_comma_less_filipino_at_before_non_question_word_is_not_split():
    """Negative case 5: 'mag-submit' is a verb, not a supported question
    word -- splitting here would strip the 'Pwede ba' interrogative framing
    from the second piece, so this must stay one facet."""
    facets = split_question_facets(
        "Pwede ba pumasok sa school at mag-submit ng requirements sa registrar?"
    )

    assert len(facets) == 1


def test_comma_less_filipino_at_before_walang_is_still_not_split():
    """Negative case 6 (already covered by
    test_filipino_conditional_without_comma_before_at_is_not_split above,
    re-asserted here under this extension's own section for clarity):
    'walang' is not a supported question word, and 'kung' is never a split
    trigger -- this must remain one facet."""
    facets = split_question_facets("Pwede ba mag-enroll kung may balance at walang clearance?")

    assert len(facets) == 1


def test_english_and_conjunction_still_splits_unaffected_by_filipino_at_rule():
    """Negative/regression case 7: this sentence's only split boundary is
    the pre-existing bare English 'and' -- confirms the new Filipino rule
    does not interfere with, replace, or duplicate existing English
    splitting, and that 'at' here (an English preposition) plays no part
    in it."""
    facets = split_question_facets("Meet at the registrar and ask about the TOR fee.")
    labels = [facet.label for facet in facets]

    assert len(facets) == 2
    assert "Meet at the registrar" in labels
    assert "ask about the TOR fee" in labels


def test_filipino_question_word_as_a_substring_does_not_falsely_trigger():
    """'sinuman' ('whoever/anyone') starts with 'sino' but is not the word
    'sino' -- the word-boundary requirement must reject it."""
    facets = split_question_facets(
        "Pwede ba pumunta sa opisina at sinuman doon ang pwede kong lapitan?"
    )

    assert len(facets) == 1


def test_question_word_not_immediately_after_at_does_not_trigger():
    """'ano' appears later in the sentence, but the word right after 'at'
    is 'kumustahin' (a verb) -- the rule must only look at what immediately
    follows 'at', not scan the rest of the clause for a question word."""
    facets = split_question_facets("Pwede ba pumunta at kumustahin kung ano ang kalagayan?")

    assert len(facets) == 1


# --- edge cases: punctuation, repetition, empty/trivial fragments -----------


def test_empty_and_whitespace_only_questions_do_not_crash():
    assert split_question_facets("") == []
    assert split_question_facets("   ") == []


def test_leading_comma_conjunction_with_only_trivial_content_yields_no_facets():
    """',  at ano pa?' ('and what else?') has no real content on either
    side -- must not produce an empty-label or whitespace-only facet."""
    facets = split_question_facets(", at ano pa?")

    assert facets == []


def test_repeated_conjunctions_never_crash_or_produce_empty_or_duplicate_facets():
    for question in (
        "Ano ang requirements, at, at magkano ang bayad?",
        "at magkano ang bayad, at ano ang requirements?",
        "Magkano ang bayad, at, at, at magkano pa?",
    ):
        facets = split_question_facets(question)
        labels = [facet.label for facet in facets]

        assert all(label.strip() for label in labels)  # no empty/whitespace-only labels
        assert len(labels) == len(set(labels))  # no duplicates


# --- coverage judged by what each part retrieved -----------------------------


def test_filipino_multi_part_question_activates_the_facet_pipeline_downstream():
    """Downstream integration (task F): a genuinely multi-part Filipino
    question must not just split into two facet objects -- the existing
    evidence-combination machinery (build_facet_evidence/partition_off_topic/
    analyze_facet_coverage) must actually ENGAGE for it, exactly as it
    already does for the equivalent English question, and each part's own
    retrieved evidence (including its source metadata) must be what
    determines coverage -- not merely that the splitter returned two
    strings."""
    tor_requirements = kb_chunk(
        "TOR Requirements", "Submit a request form to the Registrar's Office for a TOR.",
    )
    tor_fee = kb_chunk(
        "TOR Fees", "The TOR fee is PHP 20.00 per page for undergraduate students.",
    )
    facets = split_question_facets(TOR_FEE_QUESTION_FILIPINO)
    assert len(facets) == 2  # the pipeline precondition this test actually exercises

    facets, evidence, coverage = coverage_for(
        TOR_FEE_QUESTION_FILIPINO,
        {0: [tor_requirements], 1: [tor_fee]},
        selected=[tor_requirements, tor_fee],
    )

    # build_facet_evidence actually recorded per-facet evidence (not EMPTY_EVIDENCE).
    assert evidence.ranked_for(facets[0].key)
    assert evidence.ranked_for(facets[1].key)

    # analyze_facet_coverage actually judged both parts as covered, using
    # each part's own evidence -- the real activation this fix restores.
    assert coverage.is_multi_facet
    assert not coverage.has_gap
    assert {facet.label for facet in coverage.covered} == {
        facets[0].label, facets[1].label,
    }

    # partition_off_topic engages too: an unrelated chunk that neither part
    # retrieved, and that is not a strong hit for the whole question, is
    # demoted rather than leading -- source metadata (the section/office
    # used as the merge key) is what partition_off_topic and
    # analyze_facet_coverage both key off of throughout.
    unrelated = kb_chunk("Scholastic Delinquency", "Academic probation thresholds.")
    on_topic, off_topic = partition_off_topic(
        facets, [unrelated, tor_requirements, tor_fee], evidence, key_of=_chunk_merge_key,
    )
    assert unrelated in off_topic
    assert tor_requirements in on_topic and tor_fee in on_topic


def test_comma_less_filipino_split_activates_the_facet_pipeline_downstream():
    """Downstream integration for THIS extension specifically: the
    comma-less 'at magkano' split must not just produce two facet labels --
    it must drive real per-facet evidence, per-facet coverage, and
    off-topic demotion using chunk source metadata, the same as the
    comma-anchored case already proven above. Does not infer success from
    the split output alone."""
    comma_less_question = "Ano ang requirements para sa TOR at magkano ang bayad?"
    tor_requirements = kb_chunk(
        "TOR Requirements", "Submit a request form to the Registrar's Office for a TOR.",
    )
    tor_fee = kb_chunk(
        "TOR Fees", "The TOR fee is PHP 20.00 per page for undergraduate students.",
    )
    facets = split_question_facets(comma_less_question)
    assert len(facets) == 2  # precondition this test exercises, not assumes

    facets, evidence, coverage = coverage_for(
        comma_less_question,
        {0: [tor_requirements], 1: [tor_fee]},
        selected=[tor_requirements, tor_fee],
    )

    assert evidence.ranked_for(facets[0].key)
    assert evidence.ranked_for(facets[1].key)
    assert coverage.is_multi_facet
    assert not coverage.has_gap
    assert {facet.label for facet in coverage.covered} == {facets[0].label, facets[1].label}

    unrelated = kb_chunk("Scholastic Delinquency", "Academic probation thresholds.")
    on_topic, off_topic = partition_off_topic(
        facets, [unrelated, tor_requirements, tor_fee], evidence, key_of=_chunk_merge_key,
    )
    assert unrelated in off_topic
    assert tor_requirements in on_topic and tor_fee in on_topic


def test_a_part_is_answered_only_when_its_own_result_survives_into_context():
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, then deployment.")
    fees = kb_chunk("Assessment of Fees", "Accounting assesses school fees.", office="Accounting")
    facets = split_question_facets(OJT_QUESTION)

    _, _, coverage = coverage_for(OJT_QUESTION, {0: [ojt], 2: [fees]}, selected=[ojt])

    assert coverage.is_multi_facet
    assert coverage.has_gap
    assert "unpaid fees" in {facet.label for facet in coverage.uncovered}
    assert "I want to go on OJT next term" in {facet.label for facet in coverage.covered}
    assert len(facets) >= 2


def test_no_gap_when_every_part_kept_one_of_its_own_results():
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, then deployment.")
    inc = kb_chunk("Completion of INC", "The teacher submits the completion grade.")
    fees = kb_chunk("Assessment of Fees", "Accounting assesses school fees.", office="Accounting")
    rank = kb_chunk("Retention Requirement", "A student must keep the minimum average.")
    selected = [ojt, inc, fees, rank]

    _, _, coverage = coverage_for(
        OJT_QUESTION,
        {0: [ojt], 1: [inc], 2: [fees], 3: [rank]},
        selected=selected,
    )

    assert not coverage.has_gap
    assert coverage.off_topic == ()


def test_a_section_no_part_of_the_question_found_is_reported_as_off_topic():
    delinquency = kb_chunk("Scholastic Delinquency", "Probation applies at 50% of units failed.")
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, then deployment.")

    _, _, coverage = coverage_for(
        OJT_QUESTION,
        {0: [ojt]},
        selected=[delinquency, ojt],
    )

    assert coverage.off_topic_lead
    assert "Scholastic Delinquency" in coverage.off_topic


def test_a_strong_hit_for_the_whole_question_is_not_called_off_topic():
    """The full question is itself evidence; only sections nothing found are foreign."""
    overview = kb_chunk("Student Internship Overview", "Internship covers OJT and its requirements.")
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, then deployment.")

    _, _, coverage = coverage_for(
        OJT_QUESTION,
        {0: [ojt]},
        selected=[overview, ojt],
        baseline=[overview],
    )

    assert not coverage.off_topic_lead
    assert coverage.off_topic == ()


# --- putting a dropped part back ---------------------------------------------


def test_recovery_names_the_best_result_of_the_part_that_was_dropped():
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, then deployment.")
    fees = kb_chunk("Assessment of Fees", "Accounting assesses school fees.", office="Accounting")

    _, evidence, coverage = coverage_for(OJT_QUESTION, {0: [ojt], 2: [fees]}, selected=[ojt])
    keys = facet_recovery_keys(coverage, evidence, exclude={_chunk_merge_key(ojt)})

    assert keys == [_chunk_merge_key(fees)]


def test_dropped_part_is_added_back_and_marked_as_deliberate_context():
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, then deployment.", score=0.9)
    fees = kb_chunk("Assessment of Fees", "Accounting assesses school fees.", office="Accounting")
    fees.rerank_reasons = ["penalty_off_topic"]
    facets = split_question_facets(OJT_QUESTION)
    evidence = evidence_for(OJT_QUESTION, facets, {0: [ojt], 2: [fees]})

    repaired = _restore_missing_facet_context(
        OJT_QUESTION, facets, [ojt], [ojt, fees], evidence
    )

    assert len(repaired) == 2
    assert any(FACET_RECOVERY_REASON in (chunk.rerank_reasons or []) for chunk in repaired)
    # The retrieved chunk itself is left alone.
    assert fees.rerank_reasons == ["penalty_off_topic"]


def test_recovered_context_is_not_counted_as_noise():
    """Coverage context is added on purpose; its ranking penalty is not noise."""
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, deployment.", score=0.9)
    fees = kb_chunk("Assessment of Fees", "Accounting assesses school fees.", office="Accounting")
    fees.rerank_reasons = ["penalty_off_topic"]
    facets = split_question_facets(OJT_QUESTION)
    evidence = evidence_for(OJT_QUESTION, facets, {0: [ojt], 2: [fees]})

    repaired = _restore_missing_facet_context(
        OJT_QUESTION, facets, [ojt], [ojt, fees], evidence
    )

    assert _confidence_for(repaired, repaired, "answer", OJT_QUESTION) != "low"


# --- demoting sections no part of the question found -------------------------


def test_a_section_no_part_retrieved_is_demoted_below_the_ones_that_were():
    delinquency = kb_chunk("Scholastic Delinquency", "Probation at 50% of units failed.", score=0.95)
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, deployment.", score=0.7)
    fees = kb_chunk("Assessment of Fees", "Accounting assesses fees.", score=0.68, office="Accounting")
    facets = split_question_facets(OJT_QUESTION)
    evidence = evidence_for(OJT_QUESTION, facets, {0: [ojt], 2: [fees]})

    on_topic, off_topic = partition_off_topic(
        facets, [delinquency, ojt, fees], evidence, key_of=_chunk_merge_key
    )

    assert off_topic == [delinquency]
    assert on_topic == [ojt, fees]
    assert (on_topic + off_topic)[-1] is delinquency


def test_single_part_question_keeps_its_original_ranking():
    chunks = [kb_chunk("Scholastic Delinquency", "Probation at 50%."), kb_chunk("Excuse Slip", "From OSAS.")]
    facets = split_question_facets("Where can I get an excuse slip?")

    on_topic, off_topic = partition_off_topic(
        facets, chunks, FacetEvidence(), key_of=_chunk_merge_key
    )

    assert on_topic == chunks
    assert off_topic == []


# --- generator instructions ---------------------------------------------------


def test_precedence_and_conflict_phrasing_are_flagged():
    assert is_precedence_question(OJT_QUESTION)
    assert is_precedence_question("What is the correct order of clearance steps?")
    assert not is_precedence_question("How much is the completion fee?")
    assert is_conflict_question(CONFLICT_QUESTION)
    assert is_conflict_question("My adviser says something different from the handbook.")
    assert not is_conflict_question("How much is the late registration fine?")


def test_notes_forbid_inventing_an_order_and_name_the_unanswered_part():
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, deployment.")
    fees = kb_chunk("Assessment of Fees", "Accounting assesses fees.", office="Accounting")

    _, _, coverage = coverage_for(OJT_QUESTION, {0: [ojt], 2: [fees]}, selected=[ojt])
    notes = build_grounding_notes(coverage)

    assert "do not rank" in notes.lower()
    assert "unpaid fees" in notes
    assert "not covered" in notes.lower()


def test_notes_never_assert_policy_of_their_own():
    """Guardrails may describe how to answer, never what campus rules say."""
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, deployment.")

    _, _, coverage = coverage_for(OJT_QUESTION, {0: [ojt]}, selected=[ojt])
    notes = build_grounding_notes(coverage).lower()

    for claim in ("scholastic delinquency", "failed subject", "retention rule", "grade average"):
        assert claim not in notes


def test_cross_article_notes_use_metadata_not_office_names():
    dismissal = kb_chunk("Honorable Dismissal", "consent of the Registrar")
    dismissal.metadata["article"] = "Article 12 > Honorable Dismissal"
    withdrawal = kb_chunk("Withdrawal Guidelines", "written petition to the Dean")
    withdrawal.metadata["article"] = "Article 9 > Withdrawal from the University"
    chunks = [dismissal, withdrawal]
    articles = distinct_source_articles(
        chunks,
        article_of=lambda chunk: str((chunk.metadata or {}).get("article") or ""),
    )
    notes = build_cross_article_notes(articles).lower()
    assert "article 12" in notes
    assert "article 9" in notes
    assert "do not merge" in notes
    assert "dean" not in notes
    assert "registrar" not in notes
    assert build_cross_article_notes(articles[:1]) == ""


def test_system_prompt_states_no_campus_policy_of_its_own():
    prompt = ASKA_PIYU_SYSTEM_PROMPT.lower()

    for claim in ("scholastic delinquency", "failed subject", "retention rule", "grade average"):
        assert claim not in prompt


def test_prompts_name_no_office_and_quote_no_policy_value():
    """The prompt may say how to answer; the documents say who and how much."""
    messages = build_groq_messages(question="Who handles this?", context="Some section.")
    blob = " ".join(message["content"] for message in messages).lower()

    for office in ("registrar", "dean", "osas", "cashier", "clinic"):
        assert office not in blob, f"prompt names the {office} office"
    for value in ("75%", "80%", "50%", "2.00"):
        assert value not in blob, f"prompt quotes the policy value {value}"


def test_steps_never_attribute_an_office_the_charter_did_not_name():
    """A step whose agency action names no office must not gain one."""
    metadata = {
        "steps": [{"client_step": "Submit the form.", "agency_action": "Verify the entries."}]
    }
    text = "1. Client Step: Submit the form.\nAgency Action: Verify the entries.\n"

    from_metadata = _steps_from_metadata(metadata)
    from_text = _steps_from_text(text)

    assert from_metadata == ["Submit the form", "Verify the entries"]
    assert from_text == ["Submit the form", "Verify the entries"]
    assert not any("osas" in step.lower() for step in from_metadata + from_text)


def test_conflict_notes_refuse_to_crown_a_winner():
    late = kb_chunk("Late Registration", "Late registrants pay a fine of P500.00.")

    _, _, coverage = coverage_for(CONFLICT_QUESTION, {0: [late]}, selected=[late])
    notes = build_grounding_notes(coverage)

    assert "do not declare a winner" in notes.lower()
    assert "confirm with the office" in notes.lower()


def test_a_one_part_question_is_never_reported_as_unanswered():
    """One part means no per-part evidence exists, so nothing may be called missing."""
    late = kb_chunk("Late Registration", "Late registrants pay a fine of P500.00.")

    facets, _, coverage = coverage_for(CONFLICT_QUESTION, {0: [late]}, selected=[late])

    assert len(facets) == 1
    assert coverage.uncovered == ()
    assert "not covered" not in build_grounding_notes(coverage).lower()


def test_no_grounding_notes_for_a_plain_single_part_question():
    slip = kb_chunk("Excuse Slip", "Get the excuse slip from OSAS or the Guidance Office.")

    _, _, coverage = coverage_for(
        "Where can I get an excuse slip?", {0: [slip]}, selected=[slip]
    )

    assert build_grounding_notes(coverage) == ""


def test_grounding_notes_reach_the_generator_prompt():
    messages = build_groq_messages(
        question=OJT_QUESTION,
        context="Deployment of OJT: orientation, documents, deployment.",
        grounding_notes="- Do not invent an order between requirements.",
    )

    prompt = messages[-1]["content"]
    assert "This question needs extra care:" in prompt
    assert "Do not invent an order between requirements." in prompt


def test_prompt_stays_clean_without_grounding_notes():
    messages = build_groq_messages(question="How much is a COG?", context="COG costs P50.")

    assert "This question needs extra care:" not in messages[-1]["content"]


# --- confidence ----------------------------------------------------------------


def test_confidence_drops_when_a_part_goes_unanswered():
    ojt = kb_chunk("Deployment of OJT", "Orientation then deployment.", score=0.9)
    fees = kb_chunk("Assessment of Fees", "Accounting assesses fees.", office="Accounting")
    chunks = [ojt]

    _, _, coverage = coverage_for(OJT_QUESTION, {0: [ojt], 2: [fees]}, selected=chunks)

    assert _confidence_for(chunks, chunks, "Here is the OJT process.", OJT_QUESTION) == "medium"
    assert (
        _confidence_for(
            chunks, chunks, "Here is the OJT process.", OJT_QUESTION, facet_coverage=coverage
        )
        == "low"
    )


def test_a_ranking_question_never_reaches_high_confidence():
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, deployment.", score=0.9)
    inc = kb_chunk("Completion of INC", "The teacher submits the completion grade.")
    fees = kb_chunk("Assessment of Fees", "Accounting assesses fees.", office="Accounting")
    rank = kb_chunk("Retention Requirement", "A student must keep the minimum average.")
    selected = [ojt, inc, fees, rank]

    _, _, coverage = coverage_for(
        OJT_QUESTION, {0: [ojt], 1: [inc], 2: [fees], 3: [rank]}, selected=selected
    )

    assert not coverage.has_gap
    # Policy defines no order, so a "which fails first" answer stays short of high.
    assert _confidence_for(selected, selected, "answer", OJT_QUESTION, facet_coverage=coverage) == "medium"


def test_conflict_question_cannot_be_high_confidence():
    late = kb_chunk("Late Registration", "Late registrants pay a fine of P500.00.", score=0.95)

    _, _, coverage = coverage_for(CONFLICT_QUESTION, {0: [late]}, selected=[late])

    assert coverage.conflict_question
    assert _capped_for_facet_gap("high", coverage) == "medium"


def test_answer_built_on_a_section_nothing_asked_for_is_low_confidence():
    delinquency = kb_chunk("Scholastic Delinquency", "Probation at 50% of units failed.", score=0.95)
    ojt = kb_chunk("Deployment of OJT", "Orientation, documents, deployment.")
    selected = [delinquency]

    _, _, coverage = coverage_for(OJT_QUESTION, {0: [ojt]}, selected=selected)

    assert coverage.off_topic_lead
    assert (
        _confidence_for(selected, selected, "answer", OJT_QUESTION, facet_coverage=coverage) == "low"
    )


def test_cap_never_raises_an_already_low_grade():
    slip = kb_chunk("Excuse Slip", "Get it from OSAS or the Guidance Office.")

    _, _, coverage = coverage_for("Where can I get an excuse slip?", {0: [slip]}, selected=[slip])

    assert _capped_for_facet_gap("low", coverage) == "low"
    assert _capped_for_facet_gap("high", coverage) == "high"


# --- end to end ----------------------------------------------------------------


def test_bundled_question_retrieves_every_part_and_stays_cautious():
    library = {
        "Deployment of OJT": "General orientation, OJT documents, then deployment to the host.",
        "Completion of INC": "Pay the completion fee, then the teacher submits the grade.",
        "Assessment of Fees": "Accounting assesses school fees based on enrolled units.",
        "Scholastic Delinquency": "Probation applies at 50% of units failed.",
    }
    chunks = {
        section: kb_chunk(section, text, score=0.88)
        for section, text in library.items()
    }

    class FakeStore:
        """Word-overlap stand-in for the retriever, so each part finds its own section."""

        chunk_count = len(chunks)

        def __init__(self):
            self.queries = []

        def search(self, question, *, top_k=None, raw_k=None, user_role=None):
            self.queries.append(question)
            words = set(question.lower().split())
            hits = [
                chunk
                for section, chunk in chunks.items()
                if words & set(f"{section} {library[section]}".lower().split())
            ]
            return hits or list(chunks.values())

    store = FakeStore()
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value="The documents do not rank these requirements.",
        ) as generate,
    ):
        result = answer_qa_question(OJT_QUESTION, user_role="student")

    assert "unpaid fees" in store.queries
    assert "I still have an incomplete subject" in store.queries
    notes = generate.call_args.kwargs["grounding_notes"]
    assert "do not rank" in notes.lower()
    assert result.confidence in {"low", "medium"}

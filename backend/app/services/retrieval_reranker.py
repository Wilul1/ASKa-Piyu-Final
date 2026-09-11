"""Query expansion and lightweight reranking for handbook retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.services.chroma_store import RetrievedChunk
from app.services.knowledge_taxonomy import category_metadata_boost


ACADEMIC_TERMS = (
    "retention policy",
    "retention policies",
    "scholastic delinquency",
    "warning",
    "probation",
    "dismissal",
    "dropped",
    "failed academic units",
    "academic dismissal",
)
HONORABLE_TERMS = ("honorable dismissal", "voluntary withdrawal", "withdraw", "transfer credential")
ATTENDANCE_TERMS = ("attendance", "excuse slip", "medical certificate", "osas", "guidance office")
RETENTION_TERMS = ("retention", "retention policies", "scholastic delinquency", "probation", "dismissal", "dropped")
GRADUATION_TERMS = ("graduation", "graduate requirements", "candidate for graduation", "clearance")
PROGRAM_TERMS = ("curricular offerings", "programs", "campuses", "college of")
ENROLLMENT_TERMS = ("enrollment", "enroll", "enrolment", "office of the registrar")
FEE_ASSESSMENT_TERMS = ("assessment of fees", "assessment of fee", "enrolment stub", "enrollment stub")
RELATED_REGISTRATION_NOISE = (
    "ip registration",
    "system information registration",
    "registration/modification",
    "registration modification",
)
RECORD_TERMS = ("transcript of records", "tor", "student records", "registrar", "certificate of registration")
COUNSELING_TERMS = ("guidance", "counseling", "counselling", "guidance office", "student welfare")
REQUIREMENT_TERMS = ("requirements", "graduation requirements", "documentary requirements", "clearance", "application form")
UNDERGRAD_TERMS = ("undergraduate", "bachelor", "bs", "b.s.", "college")
GRADUATE_TERMS = ("graduate", "master", "doctorate", "phd", "ma", "ms")
SAMPLE_TERMS = ("sample", "test document", "dummy", "lorem ipsum")
DISCIPLINARY_TERMS = (
    "disciplinary",
    "discipline",
    "major offense",
    "major offenses",
    "minor offense",
    "minor offenses",
    "non-wearing",
    "non wearing",
    "identification card",
    "uniform",
    "sanction",
)
# Generic student phrasing that should never alone decide a title match.
# "What is the X policy?" otherwise near-exact-matches every "* Policy" title.
GENERIC_INTENT_TOKENS = frozenset(
    {
        "policy",
        "policies",
        "rule",
        "rules",
        "guideline",
        "guidelines",
        "regulation",
        "regulations",
        "procedure",
        "procedures",
        "process",
        "requirement",
        "requirements",
        "information",
        "student",
        "students",
        "university",
        "lspu",
        "manual",
        "handbook",
        "section",
        "article",
        "chapter",
        "office",
        "campus",
        "about",
        "related",
        "regarding",
        "concerning",
        "based",
        "according",
        "please",
        "help",
        "need",
        "know",
        "tell",
        "explain",
        "define",
        "definition",
        "means",
        "meaning",
    }
)
DRESS_CODE_TERMS = (
    "haircut",
    "hair cut",
    "hair-cut",
    "hair style",
    "hairstyle",
    "grooming",
    "dress code",
    "school uniform",
    "norms and decorum",
    "tattoo",
    "earrings",
    "approved hair-cut",
    "fixie crop",
)
PROCEDURAL_TERMS = ("ojt", "on-the-job", "on the job", "procedure", "procedures", "process flow")
APPENDIX_TERMS = ("appendix", "appendices", "form template")
AWARD_TERMS = ("award", "awards", "honor", "honors", "medal", "recognition")
FACULTY_AUDIENCE_TERMS = (
    "faculty",
    "faculty member",
    "faculty members",
    "professor",
    "instructor",
    "teaching load",
    "faculty load",
    "faculty manual",
    "workload",
)
TEACHING_LOAD_TERMS = (
    "teaching load",
    "faculty teaching load",
    "faculty load",
    "time allotment",
    "teaching loads",
    "load assignment",
    "workload",
    "instruction hours",
    "instruction load",
)
ACADEMIC_FREEDOM_TERMS = (
    "academic freedom",
    "indoctrination",
    "classroom cannot be used",
)
STUDENT_COURSE_LOAD_TERMS = (
    "course load",
    "academic load",
    "graduate studies course load",
    "undergraduate academic load",
)
FACULTY_GRADING_TERMS = (
    "grading sheets",
    "faculty grading",
    "submission of grades",
    "academic records",
    "grades",
)
STUDENT_GRADE_CHANGE_TERMS = (
    "change/rectification of grades",
    "rectification of grades",
    "change of grade",
    "grade rectification",
)
SHIFTING_TERMS = (
    "shifting of course",
    "shifting form",
    "shift to another",
)
FACULTY_GRADE_CHANGE_TERMS = (
    "change/rectification of grades",
    "rectification of grades",
    "academic council",
    "twenty-five percent",
    "twenty five percent",
    "submission of grades",
)
FACULTY_RESPONSIBILITY_TERMS = (
    "commitment of the lspu faculty",
    "commitment of faculty",
    "code of ethics",
    "duties of faculty",
    "faculty responsibilities",
    "responsibilities of faculty",
)
NARROW_FACULTY_ROLE_TERMS = (
    "designated as chairperson",
    "designated as dean",
    "designated as associate dean",
    "designated as vice president",
    "regular faculty designated",
)
DOMAIN_PATH_TERMS = {
    "attendance": ("attendance",),
    "retention": ("retention policies", "retention", "scholastic delinquency"),
    "graduation": ("graduation requirements", "graduation"),
    "curricular": ("curricular offerings",),
    "history": ("historical development", "history"),
    "officials": ("administrative officials", "university president"),
    "enrollment": ("enrollment", "registration"),
    "records": ("transcript of records", "student records", "registrar"),
    "counseling": ("guidance", "counseling", "student services"),
    "shifting": ("shifting of course", "shifting"),
    "residence": ("maximum residence", "maximum residence rule"),
    "refund": ("refunding of fees", "refund"),
}


@dataclass(frozen=True)
class QueryExpansionRule:
    name: str
    trigger_terms: tuple[str, ...]
    expansion_terms: tuple[str, ...]
    match_all: bool = False
    required_any_terms: tuple[str, ...] = ()
    blocked_terms: tuple[str, ...] = ()


UNIVERSITY_OFFICIAL_CONTEXT_TERMS = (
    "lspu",
    "university",
    "administrative officials",
    "university officials",
    "vice president",
    "academic affairs",
    "administration",
    "research development",
)
EXTERNAL_PRESIDENT_TERMS = (
    "philippines",
    "united states",
    "usa",
    "japan",
    "google",
    "microsoft",
    "facebook",
    "openai",
    "apple",
    "marcos",
    "duterte",
    "aquino",
)


@dataclass(frozen=True)
class PreparedRetrievalQuery:
    original_query: str
    normalized_query: str
    expanded_query: str
    matched_expansion_rules: list[str]


@dataclass(frozen=True)
class RetrievalAblation:
    """Benchmark-only retrieval switches. Production callers leave this unset."""

    disable_query_expansion: bool = False
    disable_expansion_rules: frozenset[str] = frozenset()
    disable_named_service_boosts: bool = False


# Title/service-card boosts isolated for ablation mode D. General domain/keyword
# overlap boosts are intentionally left on so this mode is not "embeddings only".
_NAMED_SERVICE_BOOST_REASON_PREFIXES: tuple[str, ...] = (
    "boost_exact_service_title",
    "boost_near_exact_service_title",
    "boost_service_title_similarity",
    "boost_tor_service_title",
    "boost_diploma_service_title",
    "boost_primary_enrollment_service_title",
    "boost_identity_service_title",
    "boost_honorable_dismissal_title",
    "boost_maximum_residence_rule",
    "boost_leave_of_absence_title",
    "boost_enrollment_office_responsibility_title",
    "boost_tor_per_page_fee_text",
    "boost_office_query_title_token_overlap",
)


def _named_service_boosts_enabled(ablation: RetrievalAblation | None) -> bool:
    return not (ablation and ablation.disable_named_service_boosts)


QUERY_EXPANSION_RULES = (
    QueryExpansionRule(
        name="lspu_historical_development_built",
        trigger_terms=("built", "established", "founded", "created", "history", "historical"),
        expansion_terms=("lspu historical development", "established", "founded", "created", "1952"),
    ),
    QueryExpansionRule(
        name="lspu_historical_development_when_built",
        trigger_terms=("lspu", "built"),
        expansion_terms=("lspu historical development", "established", "1952"),
        match_all=True,
    ),
    QueryExpansionRule(
        name="administrative_officials_president",
        trigger_terms=("president", "university president", "president of lspu"),
        expansion_terms=("administrative officials", "university president", "DR. MARIO R. BRIONES"),
        required_any_terms=UNIVERSITY_OFFICIAL_CONTEXT_TERMS,
        blocked_terms=EXTERNAL_PRESIDENT_TERMS,
    ),
    QueryExpansionRule(
        name="attendance_excuse_slip",
        trigger_terms=("excuse slip", "excuse", "absent", "absence", "attendance", "illness", "medical"),
        expansion_terms=ATTENDANCE_TERMS,
        blocked_terms=("leave of absence",),
    ),
    QueryExpansionRule(
        name="leave_of_absence",
        trigger_terms=("leave of absence",),
        expansion_terms=(
            "leave of absence",
            "loa",
            "registrar",
            "written request",
            "academic policies",
        ),
    ),
    QueryExpansionRule(
        name="scholastic_delinquency_failed_units",
        trigger_terms=("failed units", "failing", "failed", "fail", "many subjects", "probation", "dismissal"),
        expansion_terms=("scholastic delinquency", "warning", "probation", "dismissal", "failed academic units"),
        blocked_terms=("shift", "shifting"),
    ),
    QueryExpansionRule(
        name="shifting_of_course",
        trigger_terms=("shift", "shifting", "shift course", "change course", "another bs program"),
        expansion_terms=(
            "shifting of course",
            "registrar",
            "shifting form",
            "admission requirements",
            "no failure of greater than six (6) units",
        ),
        required_any_terms=("shift", "shifting"),
        blocked_terms=("night shift", "work shift"),
    ),
    QueryExpansionRule(
        name="curricular_offerings_programs",
        trigger_terms=("programs offered", "program offered", "programs", "offered", "course offerings", "curricular"),
        expansion_terms=PROGRAM_TERMS,
    ),
    QueryExpansionRule(
        name="enrollment_procedure",
        trigger_terms=("how do i enroll", "enroll", "enrollment", "enrolment"),
        expansion_terms=(
            "enrollment",
            "office of the registrar",
            "who may avail",
            "citizen charter",
        ),
        blocked_terms=("assessment of fees", "ip registration"),
    ),
    QueryExpansionRule(
        name="enrollment_responsible_office",
        trigger_terms=("which office", "what office", "responsible", "handles"),
        expansion_terms=("office of the registrar", "enrollment", "citizen charter"),
        required_any_terms=("enroll", "enrollment", "enrolment"),
    ),
    QueryExpansionRule(
        name="who_may_avail_service",
        trigger_terms=("who may avail", "who can avail", "who may", "who can"),
        expansion_terms=("who may avail", "clientele", "eligible", "citizen charter"),
    ),
    QueryExpansionRule(
        name="enrollment_who_may_avail",
        trigger_terms=("who may", "who can", "avail"),
        expansion_terms=("enrollment", "who may avail", "office of the registrar", "citizen charter"),
        required_any_terms=("enroll", "enrollment", "enrolment"),
    ),
    QueryExpansionRule(
        name="student_records_tor",
        trigger_terms=("tor", "transcript", "transcript of records"),
        expansion_terms=RECORD_TERMS,
    ),
    QueryExpansionRule(
        name="guidance_counseling_services",
        trigger_terms=("counseling", "counselling", "guidance office", "who handles counseling"),
        expansion_terms=COUNSELING_TERMS,
    ),
    QueryExpansionRule(
        name="graduation_requirements",
        trigger_terms=("graduation requirements", "requirements for graduation"),
        expansion_terms=REQUIREMENT_TERMS,
    ),
    QueryExpansionRule(
        name="student_id_validation_service",
        trigger_terms=("validate my id", "validate id", "id validation", "student id", "school id"),
        expansion_terms=(
            "id validation",
            "processing of student id",
            "student identification card",
            "citizen charter",
            "office of the student affairs and services",
            "osas",
        ),
    ),
    QueryExpansionRule(
        name="citizens_charter_edition_vision",
        trigger_terms=("edition", "vision", "asean polytechnic", "1st edition", "2026 edition"),
        expansion_terms=(
            "citizen's charter",
            "2026",
            "1st edition",
            "vision",
            "ASEAN Polytechnic University by 2030",
        ),
        required_any_terms=("citizen", "charter", "lspu", "vision", "edition"),
        blocked_terms=("how much", "fee", "fees", "cost", "diploma", "tor", "transcript", "which office"),
    ),
    QueryExpansionRule(
        name="good_moral_certificate",
        trigger_terms=("good moral", "good moral certificate", "certificate of good moral"),
        expansion_terms=(
            "issuance of good moral certificate",
            "undergraduate",
            "alumnus",
            "office of the student affairs",
            "citizen charter",
        ),
    ),
    QueryExpansionRule(
        name="tor_fees_and_certifications",
        trigger_terms=("tor", "transcript", "transcript of records", "cav", "copy of grades", "certificate of transfer"),
        expansion_terms=(
            "transcript of records",
            "issuance of transcript of records",
            "registrar",
            "per page",
            "undergraduate",
            "graduate",
            "certification",
            "citizen charter",
        ),
    ),
    QueryExpansionRule(
        name="maximum_residence_rule",
        trigger_terms=("maximum residence", "residence rule", "maximum residency"),
        expansion_terms=(
            "maximum residence rule",
            "actual residence",
        ),
    ),
    QueryExpansionRule(
        name="tuition_fee_refund",
        trigger_terms=("refund", "tuition refund", "withdraw after paying", "refunded"),
        expansion_terms=(
            "refunding of fees",
            "opening of classes",
            "honorable dismissal",
            "leave of absence",
        ),
        required_any_terms=("refund", "withdraw", "withdrawal", "tuition"),
    ),
    QueryExpansionRule(
        name="honorable_dismissal_petition",
        trigger_terms=("honorable dismissal", "honourable dismissal"),
        expansion_terms=(
            "honorable dismissal",
            "written petition to the registrar",
            "parent or guardian",
            "voluntary withdrawal",
        ),
    ),
    QueryExpansionRule(
        name="faculty_academic_freedom",
        trigger_terms=("academic freedom", "political party", "campaign", "indoctrination"),
        expansion_terms=(
            "academic freedom",
            "faculty manual",
            "classroom cannot be used as a venue for indoctrination",
        ),
        required_any_terms=("academic freedom", "campaign", "political", "indoctrination", "classroom"),
    ),
    QueryExpansionRule(
        name="diploma_second_copy_fees",
        trigger_terms=("diploma", "second copy of diploma", "duplicate diploma"),
        expansion_terms=(
            "second copy of diploma",
            "issuance of diploma",
            "transcript of records",
            "registrar",
            "citizen charter",
            "fees",
        ),
        blocked_terms=("comprehensive examination", "examination schedule"),
    ),
    QueryExpansionRule(
        name="faculty_class_dismiss_time",
        trigger_terms=(
            "dismiss my class",
            "dismiss class",
            "dismiss classes",
            "earlier than the official time",
            "earlier than official time",
        ),
        expansion_terms=(
            "faculty attendance and absences",
            "shall not be allowed to dismiss",
            "classes earlier than the official time",
            "faculty manual",
            "official time",
        ),
        required_any_terms=("dismiss", "official time"),
        blocked_terms=("honorable dismissal", "excuse slip", "scholastic delinquency"),
    ),
    QueryExpansionRule(
        name="faculty_teaching_load",
        trigger_terms=("teaching load", "faculty load", "faculty teaching", "workload"),
        expansion_terms=(
            "teaching load",
            "faculty teaching load",
            "faculty workload",
            "time allotment",
            "load assignment",
            "faculty manual",
            "teaching loads and other assignment",
        ),
        required_any_terms=("teaching", "faculty", "workload", "assigned", "assignment"),
        blocked_terms=("course load", "academic load"),
    ),
    QueryExpansionRule(
        name="faculty_grading_policies",
        trigger_terms=("faculty grading", "grading policies", "grading sheets", "faculty grades"),
        expansion_terms=(
            "grading sheets",
            "faculty grading",
            "academic records",
            "submission of grades",
            "faculty manual",
        ),
        required_any_terms=("faculty", "grading", "grades", "grade"),
        blocked_terms=("grade change", "rectification", "25 percent", "25%"),
    ),
    QueryExpansionRule(
        name="faculty_grade_rectification",
        trigger_terms=(
            "grade change",
            "rectification of grades",
            "change of grades",
            "25 percent of a class",
            "25% of a class",
        ),
        expansion_terms=(
            "change/rectification of grades",
            "rectification of grades",
            "academic council",
            "faculty manual",
            "submission of grades",
        ),
    ),
    QueryExpansionRule(
        name="faculty_responsibilities",
        trigger_terms=(
            "faculty responsibilities",
            "responsibilities of faculty",
            "duties of faculty",
            "faculty members",
            "commitment of faculty",
        ),
        expansion_terms=(
            "commitment of the lspu faculty",
            "code of ethics",
            "duties of faculty",
            "faculty responsibilities",
            "faculty manual",
        ),
        required_any_terms=("faculty", "professor", "instructor"),
    ),
    QueryExpansionRule(
        name="scholarship_financial_assistance",
        trigger_terms=("scholarship", "financial assistance", "grant", "grants"),
        expansion_terms=(
            "processing of scholarship and financial assistance",
            "application form",
            "certified copy of grades",
            "citizen charter",
        ),
    ),
    QueryExpansionRule(
        name="library_reference_assistance",
        trigger_terms=("library", "reference assistance", "library reference"),
        expansion_terms=(
            "library reference assistance",
            "lspu id",
            "outside researchers",
            "citizen charter",
        ),
    ),
    QueryExpansionRule(
        name="dropping_of_subjects",
        trigger_terms=("dropping", "drop a subject", "drop subject", "drop subjects"),
        expansion_terms=(
            "dropping of subjects",
            "registrar",
            "per unit",
            "faculty-in-charge",
            "dean",
            "citizen charter",
        ),
    ),
    QueryExpansionRule(
        name="ojt_deployment",
        trigger_terms=("ojt", "on-the-job", "on the job", "deployment"),
        expansion_terms=(
            "ojt deployment",
            "host training establishment",
            "orientation",
            "citizen charter",
        ),
    ),
    QueryExpansionRule(
        name="statement_of_account",
        trigger_terms=("statement of account", "payment history", "balance", "soa"),
        expansion_terms=(
            "statement of account",
            "accounting",
            "student id",
            "citizen charter",
        ),
    ),
    QueryExpansionRule(
        name="entrance_examination",
        trigger_terms=("entrance exam", "entrance examination", "admission test"),
        expansion_terms=(
            "lspu entrance examination",
            "guidance and counseling",
            "report card",
            "citizen charter",
        ),
    ),
    QueryExpansionRule(
        name="dress_code_grooming",
        trigger_terms=(
            "haircut",
            "hair cut",
            "hair-cut",
            "hair style",
            "hairstyle",
            "grooming",
            "dress code",
            "school uniform",
            "uniform policy",
            "tattoo",
            "earrings",
            "norms and decorum",
            "fixie",
            "barber",
        ),
        expansion_terms=DRESS_CODE_TERMS,
    ),
)


def expand_query(query: str) -> str:
    """Append retrieval-oriented synonyms for broad natural language questions."""
    return prepare_retrieval_query(query).expanded_query


def prepare_retrieval_query(
    query: str,
    *,
    ablation: RetrievalAblation | None = None,
) -> PreparedRetrievalQuery:
    """Normalize natural student phrasing while preserving the original query."""
    original = _repair_common_query_typos(query.strip())
    normalized = _normalize(original)
    expansions: list[str] = []
    matched_rules: list[str] = []
    disabled_rules = ablation.disable_expansion_rules if ablation else frozenset()
    skip_all_expansion = bool(ablation and ablation.disable_query_expansion)

    if not skip_all_expansion:
        for rule in QUERY_EXPANSION_RULES:
            if rule.name in disabled_rules:
                continue
            if _rule_matches(normalized, rule):
                expansions.extend(rule.expansion_terms)
                matched_rules.append(rule.name)

        if _matches(normalized, r"\bfail(?:ed|ing)?\b", r"\bmany subjects?\b", r"\bcontinue (?:my )?course\b") and not _is_shifting_query(
            normalized
        ):
            expansions.extend(ACADEMIC_TERMS)
        if "probation" in normalized:
            expansions.extend(("scholastic delinquency", "retention policy", "warning", "probation"))
        if _is_academic_dismissal_query(normalized):
            expansions.extend(("retention policy", "academic dismissal", "scholastic delinquency"))
        if _is_honorable_dismissal_query(normalized):
            expansions.extend(("honorable dismissal", "voluntary withdrawal", "registrar"))
        if _is_identity_document_query(normalized):
            expansions.extend(
                (
                    "id validation",
                    "processing of student id",
                    "student identification card",
                    "citizen charter",
                    "office of the student affairs and services",
                )
            )
        if _is_leave_of_absence_query(normalized):
            expansions.extend(
                (
                    "leave of absence",
                    "loa",
                    "registrar",
                    "written request",
                    "academic policies",
                )
            )
        elif _matches(normalized, r"\babsen[tc]\b", r"\billness\b", r"\bexcuse\b", r"\bmedical\b"):
            expansions.extend(ATTENDANCE_TERMS)
        if _is_shifting_query(normalized):
            expansions.extend(("shifting of course", "registrar", "shifting form", "admission requirements"))
        if _matches(normalized, r"\bundergraduate\b", r"\bbachelor\b", r"\bbs\b", r"\bb\.s\.\b") and not _is_shifting_query(
            normalized
        ):
            expansions.extend(("undergraduate programs", "curricular offerings", "bachelor", "BS"))
        if _matches(normalized, r"\bgraduate\b", r"\bmaster\b", r"\bdoctorate\b", r"\bphd\b", r"\bma\b", r"\bms\b"):
            expansions.extend(("graduate studies", "master", "doctorate", "PhD", "MA", "MS"))
        if _matches(normalized, r"\bcollege\b.*\bprogram", r"\bcampus(?:es)?\b.*\boffer", r"\boffer(?:ed|s)?\b.*\bprogram"):
            expansions.extend(PROGRAM_TERMS)
        if _is_teaching_load_query(normalized):
            expansions.extend(TEACHING_LOAD_TERMS)
            expansions.append("faculty manual")
        if _is_academic_freedom_query(normalized):
            expansions.extend(ACADEMIC_FREEDOM_TERMS)
            expansions.append("faculty manual")
        if _is_maximum_residence_query(normalized):
            expansions.extend(("maximum residence rule", "actual residence"))
        if _is_tuition_refund_query(normalized):
            expansions.extend(
                (
                    "refunding of fees",
                    "opening of classes",
                )
            )
        if _is_faculty_grade_change_query(normalized):
            expansions.extend(FACULTY_GRADE_CHANGE_TERMS)
            expansions.append("faculty manual")
        elif _is_faculty_grading_query(normalized):
            expansions.extend(FACULTY_GRADING_TERMS)
            expansions.append("faculty manual")
        if _is_faculty_responsibilities_query(normalized):
            expansions.extend(FACULTY_RESPONSIBILITY_TERMS)
            expansions.append("faculty manual")

    unique = _dedupe(expansions)
    normalized_for_retrieval = (
        normalized if skip_all_expansion else _normalize_student_phrasing(normalized, unique)
    )
    expanded = _dedupe([original, normalized_for_retrieval, *unique])
    return PreparedRetrievalQuery(
        original_query=original,
        normalized_query=normalized_for_retrieval,
        expanded_query=" ".join(item for item in expanded if item).strip(),
        matched_expansion_rules=matched_rules,
    )


# Ceiling on the cumulative heuristic adjustment (sum of every score += / -=
# rule below) applied to a single chunk, relative to its original semantic
# (cosine) score. This does not change behavior for any currently-known query
# pattern (observed legitimate deltas across the test suite and the retrieval
# benchmark top out around +/-3.4), but it stops an unanticipated combination
# of rules - e.g. triggered by newly-indexed Faculty Manual phrasing - from
# fully drowning out genuine semantic similarity with an unbounded score.
MAX_HEURISTIC_DELTA_MAGNITUDE = 4.0


def _apply_heuristic_delta_cap(original: float, score: float, reasons: list[str]) -> float:
    """Clamp the cumulative heuristic adjustment to +/-MAX_HEURISTIC_DELTA_MAGNITUDE.

    Returns the final (possibly clamped) score and records a reason when
    clamping actually changed the outcome, so it stays visible for debugging.
    """
    heuristic_delta = score - original
    clamped_delta = max(
        -MAX_HEURISTIC_DELTA_MAGNITUDE,
        min(MAX_HEURISTIC_DELTA_MAGNITUDE, heuristic_delta),
    )
    if clamped_delta != heuristic_delta:
        reasons.append(f"clamped_heuristic_delta:{heuristic_delta:.2f}->{clamped_delta:.2f}")
    return original + clamped_delta


def rerank_chunks(
    query: str,
    chunks: Iterable[RetrievedChunk],
    *,
    ablation: RetrievalAblation | None = None,
) -> list[RetrievedChunk]:
    normalized_query = _normalize(query)
    profile = _query_profile(normalized_query)
    intent_phrases = _intent_phrases(normalized_query)
    citation_ready_cache: dict[str, bool] = {}
    reranked: list[RetrievedChunk] = []
    named_boosts = _named_service_boosts_enabled(ablation)

    for chunk in chunks:
        original = chunk.original_score if chunk.original_score is not None else chunk.relevance_score
        score = float(original)
        reasons: list[str] = []
        metadata = chunk.metadata or {}
        title = _chunk_service_title(chunk, metadata)
        path = _metadata_path(metadata)
        metadata_labels = " ".join(
            str(metadata.get(key) or "")
            for key in (
                "category",
                "subcategory",
                "office",
                "responsible_office",
                "source_document",
                "source_filename",
                "document_type",
                "article_type",
                "source_type",
                "parser_document_type",
            )
        )
        content = f"{title} {path} {metadata_labels} {chunk.text}"
        normalized_content = _normalize(content)
        normalized_title_path = _normalize(f"{title} {path} {metadata_labels}")
        metadata_content_type = _normalize(str(metadata.get("content_type") or ""))

        score += _keyword_overlap_boost(normalized_query, normalized_title_path, reasons)
        if named_boosts:
            score += _service_title_similarity_boost(intent_phrases, normalized_title_path, reasons)
        score += _distinctive_term_boost(
            normalized_query,
            normalized_title_path,
            normalized_content,
            reasons,
        )

        domain = _detected_domain(profile)
        if domain:
            score += _path_domain_boost(domain, normalized_title_path, reasons)
        if profile["curricular"]:
            score += _specific_curricular_path_boost(normalized_query, normalized_title_path, reasons)

        if profile["academic_risk"] and _contains_any(normalized_content, ACADEMIC_TERMS):
            score += 0.22
            reasons.append("academic_policy_match")
        if profile["failing_many"] and _contains_any(normalized_content, ("scholastic delinquency", "probation", "dismissal", "dropped", "retention")):
            score += 0.18
            reasons.append("failing_subjects_policy")
        if profile.get("delinquency_thresholds"):
            if "scholastic delinquency" in normalized_title_path:
                score += 0.48
                reasons.append("boost_scholastic_delinquency_thresholds")
            if _contains_any(normalized_content, ("25%", "25 %", "fails 25")) and "warning" in normalized_content:
                score += 0.18
                reasons.append("boost_warning_threshold_text")
            if (
                "dropped" in normalized_title_path
                and "scholastic delinquency" not in normalized_title_path
                and _contains_any(
                    normalized_content,
                    ("shall not be admitted", "not be admitted to another"),
                )
            ):
                score -= 0.5
                reasons.append("penalty_dropped_transfer_rule_for_threshold_query")
        if profile.get("shifting"):
            if _contains_any(normalized_title_path, SHIFTING_TERMS) or "shifting of course" in normalized_content:
                score += 0.45
                reasons.append("boost_shifting_of_course")
            if _contains_any(
                normalized_title_path, ("dropped", "scholastic delinquency", "dismissal")
            ) and not _contains_any(normalized_title_path, SHIFTING_TERMS):
                score -= 0.52
                reasons.append("penalty_dropped_for_shifting_query")
        if profile["fail_75"] and "dismiss" in normalized_content and "honorable dismissal" not in normalized_content:
            score += 0.32
            reasons.append("failed_units_dismissal")
        if profile["honorable"] and _contains_any(normalized_content, HONORABLE_TERMS):
            score += 0.28
            reasons.append("honorable_dismissal_match")
            if named_boosts and "honorable dismissal" in normalized_title_path:
                score += 0.35
                reasons.append("boost_honorable_dismissal_title")
            if _contains_any(normalized_title_path, ("dropping of subjects", "drop a course")):
                score -= 0.4
                reasons.append("penalty_dropping_subjects_for_honorable_dismissal")
        if profile.get("residence") and _contains_any(
            normalized_title_path, ("maximum residence", "residence rule")
        ):
            if named_boosts:
                score += 0.5
                reasons.append("boost_maximum_residence_rule")
            else:
                score += 0.18
                reasons.append("residence_policy_match")
        if profile.get("refund") and _contains_any(
            normalized_content, ("refunding of fees", "seventy-five percent", "75%", "opening of classes")
        ):
            score += 0.4
            reasons.append("boost_tuition_refund_schedule")
        if profile.get("academic_freedom") and _contains_any(
            normalized_content, ACADEMIC_FREEDOM_TERMS
        ):
            score += 0.45
            reasons.append("boost_academic_freedom_section")
        if profile["attendance"] and _contains_any(normalized_content, ATTENDANCE_TERMS):
            score += 0.28
            reasons.append("attendance_policy_match")
        if profile.get("leave_of_absence"):
            if named_boosts and _contains_any(normalized_title_path, ("leave of absence",)):
                score += 0.55
                reasons.append("boost_leave_of_absence_title")
            elif _contains_any(normalized_title_path, ("leave of absence",)):
                score += 0.2
                reasons.append("leave_of_absence_match")
            if _contains_any(normalized_title_path, ("attendance", "excuse slip")):
                score -= 0.45
                reasons.append("penalty_attendance_for_leave_of_absence_query")
        if profile["enrollment"] and _contains_any(normalized_content, ENROLLMENT_TERMS):
            score += 0.24
            reasons.append("enrollment_procedure_match")
            # Prefer the Enrollment service card over Assessment of Fees.
            if named_boosts and _title_is_primary_enrollment_service(normalized_title_path):
                score += 0.45
                reasons.append("boost_primary_enrollment_service_title")
            if _contains_any(normalized_title_path, FEE_ASSESSMENT_TERMS) and not _title_is_primary_enrollment_service(
                normalized_title_path
            ):
                score -= 0.35
                reasons.append("penalty_fee_assessment_for_enrollment_query")
        if profile["office_responsibility"]:
            if named_boosts:
                score += _office_responsibility_boost(
                    normalized_query=normalized_query,
                    normalized_title_path=normalized_title_path,
                    metadata=metadata,
                    reasons=reasons,
                )
        if profile["records"] and _contains_any(normalized_content, RECORD_TERMS):
            score += 0.28
            reasons.append("student_records_match")
        if named_boosts:
            score += _fee_service_boost(
                normalized_query=normalized_query,
                normalized_title_path=normalized_title_path,
                normalized_content=normalized_content,
                metadata=metadata,
                reasons=reasons,
            )
        if profile["counseling"] and _contains_any(normalized_content, COUNSELING_TERMS):
            score += 0.26
            reasons.append("office_service_match")
        if profile["requirements"] and _contains_any(normalized_content, REQUIREMENT_TERMS):
            score += 0.24
            reasons.append("requirements_match")
        if profile["programs"] and _contains_any(normalized_content, PROGRAM_TERMS):
            score += 0.16
            reasons.append("curricular_offerings_match")
        if profile["undergraduate"] and _is_undergraduate_chunk(normalized_content, metadata):
            score += 0.32
            reasons.append("boost_undergraduate_curricular_match")
        if profile["graduate"] and _is_graduate_chunk(normalized_content):
            score += 0.25
            reasons.append("graduate_match")
        if profile["bs_it"] and _contains_any(normalized_content, ("bs information technology", "bachelor of science in information technology")):
            score += 0.26
            reasons.append("bs_it_match")
        if profile["campus_offer"] and _contains_any(normalized_content, ("all campuses", "campuses: all", "campus: all")):
            score += 0.2
            reasons.append("campus_availability_match")
        if named_boosts:
            score += _identity_document_service_boost(
                profile=profile,
                normalized_title_path=normalized_title_path,
                metadata=metadata,
                reasons=reasons,
            )
        score += _service_vs_form_boost(
            profile=profile,
            normalized_query=normalized_query,
            normalized_title_path=normalized_title_path,
            metadata=metadata,
            reasons=reasons,
        )
        metadata_score, metadata_reasons = category_metadata_boost(normalized_query, metadata)
        if metadata_score:
            score += metadata_score
            reasons.extend(metadata_reasons)
        if _has_valid_source_metadata(metadata):
            score += 0.04
            reasons.append("boost_valid_source_metadata")
        score += _citation_grounding_boost(
            chunk=chunk,
            metadata=metadata,
            cache=citation_ready_cache,
            reasons=reasons,
        )
        if profile["external_topic"] and _contains_any(normalized_title_path, ("administrative officials", "university president", "board of regents")):
            score -= 0.85
            reasons.append("penalty_external_topic_admin_title")

        score += _faculty_audience_rerank_delta(
            profile=profile,
            normalized_title_path=normalized_title_path,
            normalized_content=normalized_content,
            metadata=metadata,
            reasons=reasons,
        )

        if profile["academic_risk"] and "honorable dismissal" in normalized_content and not profile["honorable"]:
            score -= 0.35
            reasons.append("penalty_honorable_not_academic")
        if profile["curricular"] and not profile["graduate"] and _is_graduate_chunk(normalized_content):
            score -= 0.65
            reasons.append("penalty_graduate_offering_not_requested")
        if profile["undergraduate"] and _is_graduate_chunk(normalized_content):
            score -= 0.48
            reasons.append("penalty_graduate_for_undergraduate_query")
        if profile["graduate"] and _is_undergraduate_chunk(normalized_content, metadata):
            score -= 0.28
            reasons.append("penalty_undergraduate_for_graduate_query")
        score += _domain_noise_penalty(
            profile=profile,
            normalized_query=normalized_query,
            normalized_content=normalized_content,
            normalized_title_path=normalized_title_path,
            content_type=metadata_content_type,
            reasons=reasons,
        )
        if _contains_any(normalized_content, SAMPLE_TERMS):
            score -= 0.4
            reasons.append("penalty_sample_document")

        final_score = _apply_heuristic_delta_cap(original, score, reasons)

        chunk.original_score = round(original, 4)
        chunk.reranked_score = round(final_score, 4)
        chunk.relevance_score = chunk.reranked_score
        chunk.rerank_reasons = reasons or ["semantic_similarity"]
        reranked.append(chunk)

    return sorted(
        reranked,
        key=lambda item: (
            item.reranked_score or item.relevance_score,
            1 if _chunk_is_citation_ready(item, citation_ready_cache) else 0,
        ),
        reverse=True,
    )


def _query_profile(normalized_query: str) -> dict[str, bool]:
    shifting = _is_shifting_query(normalized_query)
    honorable = _is_honorable_dismissal_query(normalized_query)
    undergraduate = (not shifting) and _matches(
        normalized_query, r"\bundergraduate\b", r"\bbachelor\b", r"\bbs\b", r"\bb\.s\.\b"
    )
    graduate = _matches(normalized_query, r"\bgraduate\b", r"\bmaster\b", r"\bdoctorate\b", r"\bphd\b", r"\bma\b", r"\bms\b")
    failing = _matches(normalized_query, r"\bfail(?:ed|ing)?\b", r"\bmany subjects?\b", r"\b75\s*%", r"\bfailed units?\b")
    attendance = (not _is_leave_of_absence_query(normalized_query)) and _matches(
        normalized_query, r"\battendance\b", r"\babsen[tc]\b", r"\billness\b", r"\bexcuse\b", r"\bmedical\b"
    )
    enrollment = _matches(normalized_query, r"\benroll(?:ment)?\b", r"\benrolment\b", r"\bhow do i enroll\b")
    records = _matches(normalized_query, r"\btor\b", r"\btranscript\b", r"\bcopy of grades\b", r"\bgood moral\b", r"\bcertificate of registration\b")
    counseling = _matches(normalized_query, r"\bcounsel(?:ing|ling)\b", r"\bguidance\b", r"\bwho handles counseling\b")
    requirements = _matches(normalized_query, r"\brequirements?\b", r"\bdocuments?\b", r"\bwhat do i need\b")
    graduation = _matches(
        normalized_query,
        r"\bgraduat(?:e|es|ed|ing|ion)\b",
        r"\bclearance\b",
        r"\bcommencement\b",
    ) or (
        "diploma" in normalized_query
        and not re.search(r"\b(?:fee|fees|cost|how much|second copy)\b", normalized_query)
    )
    curricular = (not shifting) and _matches(
        normalized_query,
        r"\bcurricular\b",
        r"\bprogram",
        r"\bcourse offerings?\b",
        r"\bcampus(?:es)?\b.*\boffer",
        r"\boffer(?:ed|s)?\b.*\bprogram",
    )
    academic_risk = (not honorable) and (not shifting) and (
        failing
        or "probation" in normalized_query
        or "retention" in normalized_query
        or "scholastic delinquency" in normalized_query
        or "dismissal" in normalized_query
    )
    delinquency_thresholds = (not honorable) and (not shifting) and (
        "scholastic delinquency" in normalized_query
        or (
            "probation" in normalized_query
            and _contains_any(normalized_query, ("warning", "warn me", "warn"))
        )
        or (
            "probation" in normalized_query
            and _contains_any(normalized_query, ("continuing", "stop me", "keep going"))
        )
    )
    identity_document = _is_identity_document_query(normalized_query)
    service_howto = identity_document or _matches(
        normalized_query,
        r"\bhow (?:do|can|to)\b",
        r"\bwhere (?:do|can|to)\b",
        r"\bsteps?\b",
        r"\bprocedure\b",
        r"\bprocess\b",
    )
    return {
        "academic_risk": academic_risk,
        "delinquency_thresholds": delinquency_thresholds,
        "retention": academic_risk or "retention" in normalized_query or "scholastic delinquency" in normalized_query,
        "failing_many": (not shifting) and (failing or "continue course" in normalized_query),
        "fail_75": bool(re.search(r"\b75\s*%", normalized_query)) and "fail" in normalized_query,
        "honorable": honorable,
        "shifting": shifting,
        "attendance": attendance,
        "leave_of_absence": _is_leave_of_absence_query(normalized_query),
        "enrollment": enrollment,
        "records": records,
        "counseling": counseling,
        "requirements": requirements,
        "graduation": graduation and not graduate,
        "curricular": curricular,
        "programs": curricular,
        "undergraduate": undergraduate or (curricular and not graduate),
        "graduate": graduate and not undergraduate,
        "awards": _matches(normalized_query, r"\bawards?\b", r"\bhonou?rs?\b", r"\brecognition\b"),
        "bs_it": _matches(normalized_query, r"\bbs information technology\b", r"\bbsit\b", r"\binformation technology\b"),
        "campus_offer": _matches(normalized_query, r"\bcampus(?:es)?\b", r"\boffer(?:ed|s)?\b"),
        "history": _matches(normalized_query, r"\bhistorical development\b", r"\bestablish(?:ed)?\b", r"\bfounded\b", r"\bbuilt\b"),
        "officials": _is_university_officials_query(normalized_query),
        "external_topic": _contains_any(normalized_query, EXTERNAL_PRESIDENT_TERMS)
        or _matches(normalized_query, r"\bweather\b", r"\bcapital of japan\b"),
        "identity_document": identity_document,
        "service_howto": service_howto,
        "form_requirement": _is_form_requirement_query(normalized_query),
        "office_responsibility": _matches(
            normalized_query,
            r"\bwhich office\b",
            r"\bwhat office\b",
            r"\bwho handles\b",
            r"\bresponsible (?:for|office)\b",
            r"\bin charge of\b",
        ),
        "faculty": _is_faculty_audience_query(normalized_query),
        "teaching_load": _is_teaching_load_query(normalized_query),
        "faculty_grading": _is_faculty_grading_query(normalized_query),
        "faculty_grade_change": _is_faculty_grade_change_query(normalized_query),
        "faculty_responsibilities": _is_faculty_responsibilities_query(normalized_query),
        "faculty_class_time": _is_faculty_class_time_query(normalized_query),
        "academic_freedom": _is_academic_freedom_query(normalized_query),
        "residence": _is_maximum_residence_query(normalized_query),
        "refund": _is_tuition_refund_query(normalized_query),
    }


def _is_form_requirement_query(normalized_query: str) -> bool:
    return bool(
        re.search(
            r"\b(?:form|fill out|how to fill|application form|request form|"
            r"checklist of requirements)\b",
            normalized_query,
        )
    )


def _detected_domain(profile: dict[str, bool]) -> str | None:
    for domain in (
        "attendance",
        "shifting",
        "residence",
        "refund",
        "retention",
        "graduation",
        "curricular",
        "history",
        "officials",
        "enrollment",
        "records",
        "counseling",
    ):
        if profile.get(domain):
            return domain
    return None


def _title_is_primary_enrollment_service(normalized_title_path: str) -> bool:
    """True for the Enrollment service itself, not Assessment of Fees / IP Registration."""
    if _contains_any(normalized_title_path, FEE_ASSESSMENT_TERMS):
        return False
    if _contains_any(normalized_title_path, RELATED_REGISTRATION_NOISE):
        return False
    title_tokens = set(re.findall(r"[a-z0-9]+", normalized_title_path))
    if "enrollment" not in title_tokens and "enrolment" not in title_tokens:
        return False
    # Reject titles that are mostly about another registration workflow.
    if "registration" in title_tokens and "enrollment" not in title_tokens and "enrolment" not in title_tokens:
        return False
    return True


def _office_responsibility_boost(
    *,
    normalized_query: str,
    normalized_title_path: str,
    metadata: dict,
    reasons: list[str],
) -> float:
    """Boost the service card that owns the asked process for which-office questions."""
    boost = 0.0
    office = _normalize(
        str(metadata.get("office") or metadata.get("responsible_office") or metadata.get("office_or_division") or "")
    )
    if _matches(normalized_query, r"\benroll(?:ment)?\b", r"\benrolment\b"):
        if _title_is_primary_enrollment_service(normalized_title_path):
            boost += 0.65
            reasons.append("boost_enrollment_office_responsibility_title")
        if _title_is_primary_enrollment_service(normalized_title_path) and _contains_any(
            office, ("registrar", "office of the registrar")
        ):
            boost += 0.3
            reasons.append("boost_registrar_office_metadata")
        if _contains_any(normalized_title_path, FEE_ASSESSMENT_TERMS):
            boost -= 0.45
            reasons.append("penalty_fee_assessment_for_office_question")
        if _contains_any(normalized_title_path, RELATED_REGISTRATION_NOISE):
            boost -= 0.5
            reasons.append("penalty_related_registration_for_enrollment_office_question")
    # Generic: exact service token overlap between query and title.
    query_tokens = set(re.findall(r"[a-z0-9]+", normalized_query)) - {
        "which",
        "what",
        "office",
        "is",
        "are",
        "the",
        "for",
        "of",
        "a",
        "an",
        "to",
        "in",
        "responsible",
        "process",
        "service",
        "who",
        "handles",
        "charge",
    }
    title_tokens = set(re.findall(r"[a-z0-9]+", normalized_title_path))
    overlap = query_tokens & title_tokens
    if len(overlap) >= 1 and any(len(token) >= 5 for token in overlap):
        boost += 0.18
        reasons.append("boost_office_query_title_token_overlap")
    if office and office not in {"none", "not specified", "[needs review]"}:
        boost += 0.08
        reasons.append("boost_has_office_metadata")
    return boost


def _chunk_service_title(chunk: RetrievedChunk, metadata: dict) -> str:
    for key in (
        "source_section",
        "section_heading",
        "canonical_topic",
        "service_title",
        "section",
        "article",
        "title",
        "chapter",
    ):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return str(chunk.title or "").strip()


def _metadata_path(metadata: dict) -> str:
    return " ".join(
        str(metadata.get(key) or "")
        for key in (
            "chapter",
            "article",
            "section",
            "appendix",
            "source_section",
            "section_heading",
            "title",
            "canonical_topic",
            "hierarchy_path",
            "office",
            "responsible_office",
        )
    )


def _has_valid_source_metadata(metadata: dict) -> bool:
    page = metadata.get("page_number") or metadata.get("page_start") or metadata.get("page")
    has_page = isinstance(page, int) or (isinstance(page, str) and page.isdigit())
    has_source = any(
        str(metadata.get(key) or "").strip()
        for key in ("source_filename", "source_document", "source_title", "document_id")
    )
    return has_page and has_source


def _is_identity_document_query(normalized_query: str) -> bool:
    has_id = bool(
        re.search(
            r"\b(?:student\s+|school\s+)?ids?\b|\bidentification\s+card\b|\bid\s+card\b",
            normalized_query,
        )
    )
    if not has_id:
        return False
    if _contains_any(
        normalized_query,
        (
            "id validation",
            "validate id",
            "validate my id",
            "validation of id",
            "student id",
            "school id",
            "processing of student id",
            "process student id",
            "id processing",
        ),
    ):
        return True
    return bool(
        re.search(
            r"\b(?:validat\w*|process(?:ing)?|renew(?:al)?|replac\w*|issu\w*)\b",
            normalized_query,
        )
    )


def _intent_phrases(normalized_query: str) -> list[str]:
    stop = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "how",
        "what",
        "where",
        "when",
        "who",
        "can",
        "i",
        "my",
        "me",
        "please",
        "for",
        "to",
        "of",
        "and",
        "or",
        "in",
        "on",
        "at",
    }
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalized_query)
        if token not in stop and len(token) >= 2
    ]
    phrases = list(tokens)
    for size in (2, 3):
        for index in range(len(tokens) - size + 1):
            phrases.append(" ".join(tokens[index : index + size]))
    # Drop lone generic tokens like "policy" so they cannot near-exact-match
    # every handbook title that happens to include that word.
    return _dedupe(
        [
            phrase
            for phrase in phrases
            if not (
                " " not in phrase
                and phrase in GENERIC_INTENT_TOKENS
            )
        ]
    )


def _service_title_similarity_boost(intent_phrases: list[str], normalized_title_path: str, reasons: list[str]) -> float:
    if not intent_phrases or not normalized_title_path:
        return 0.0
    best = 0.0
    best_phrase = ""
    for phrase in intent_phrases:
        if len(phrase) < 3:
            continue
        similarity = _phrase_title_similarity(phrase, normalized_title_path)
        if similarity > best:
            best = similarity
            best_phrase = phrase
    if best >= 0.95:
        reasons.append(f"boost_exact_service_title:{best_phrase}")
        return 0.5
    if best >= 0.8:
        reasons.append(f"boost_near_exact_service_title:{best_phrase}")
        return 0.38
    if best >= 0.55:
        reasons.append(f"boost_service_title_similarity:{best_phrase}")
        return 0.2
    return 0.0


def _phrase_title_similarity(phrase: str, title_path: str) -> float:
    title_folded = _lexical_token_set(title_path)
    phrase_tokens = [token for token in phrase.split() if token]
    if not phrase_tokens:
        return 0.0

    distinctive = [
        token
        for token in phrase_tokens
        if token not in GENERIC_INTENT_TOKENS and len(token) >= 4
    ]
    # Phrases like "haircut policy" must match the distinctive topic token(s),
    # not only the generic word "policy".
    if distinctive and not all(_token_matches_folded(token, title_folded) for token in distinctive):
        return 0.0

    if phrase == title_path:
        return 1.0
    if phrase in title_path:
        return 1.0 if len(phrase_tokens) >= 2 else 0.82

    overlap = sum(1 for token in phrase_tokens if _token_matches_folded(token, title_folded))
    ratio = overlap / len(phrase_tokens)
    if ratio == 1.0 and len(phrase_tokens) >= 2:
        return 0.92
    if ratio >= 0.67 and len(phrase_tokens) >= 2:
        return 0.7
    if ratio >= 0.5 and (not distinctive or all(_token_matches_folded(token, title_folded) for token in distinctive)):
        return 0.55
    return 0.0


def _lexical_token_set(text: str) -> set[str]:
    """Tokens plus adjacent joins so hair-cut / hair cut ↔ haircut."""
    tokens = re.findall(r"[a-z0-9]+", _normalize(text))
    folded = set(tokens)
    for index in range(len(tokens) - 1):
        folded.add(tokens[index] + tokens[index + 1])
    return folded


def _token_matches_folded(token: str, folded: set[str]) -> bool:
    if not token:
        return False
    if token in folded:
        return True
    # Allow "haircut" to match {"hair", "cut"} via join already in folded.
    return False


def _distinctive_query_tokens(normalized_query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", normalized_query)
    distinctive = [
        token
        for token in tokens
        if len(token) >= 4 and token not in GENERIC_INTENT_TOKENS
    ]
    # Also keep joined bigrams from the query itself (hair + cut → haircut).
    joined: list[str] = []
    for index in range(len(tokens) - 1):
        left, right = tokens[index], tokens[index + 1]
        if left in GENERIC_INTENT_TOKENS and right in GENERIC_INTENT_TOKENS:
            continue
        compound = left + right
        if len(compound) >= 6:
            joined.append(compound)
    return _dedupe([*distinctive, *joined])


def _distinctive_term_boost(
    normalized_query: str,
    normalized_title_path: str,
    normalized_content: str,
    reasons: list[str],
) -> float:
    """Boost chunks that carry the query's distinctive topic words.

    Prevents generic wrappers like "policy"/"guidelines" from drowning out the
    actual subject (haircut, tattoo, shifting, etc.) after semantic retrieval.
    """
    distinctive = _distinctive_query_tokens(normalized_query)
    if not distinctive:
        return 0.0

    title_folded = _lexical_token_set(normalized_title_path)
    content_folded = _lexical_token_set(normalized_content)
    title_hits = [token for token in distinctive if _token_matches_folded(token, title_folded)]
    content_hits = [
        token
        for token in distinctive
        if _token_matches_folded(token, content_folded)
    ]
    if not title_hits and not content_hits:
        return 0.0

    boost = 0.0
    if title_hits:
        boost += min(0.55, 0.28 * len(title_hits))
        reasons.append(f"boost_distinctive_title_terms:{','.join(title_hits[:4])}")
    elif content_hits:
        boost += min(0.36, 0.18 * len(content_hits))
        reasons.append(f"boost_distinctive_content_terms:{','.join(content_hits[:4])}")

    # Soft penalty when the title is a generic "* Policy" page and none of the
    # distinctive query terms appear there — common failure for "X policy?".
    title_tokens = set(re.findall(r"[a-z0-9]+", normalized_title_path))
    if (
        distinctive
        and not title_hits
        and ("policy" in title_tokens or "policies" in title_tokens)
        and not any(_token_matches_folded(token, title_folded) for token in distinctive)
    ):
        boost -= 0.22
        reasons.append("penalty_generic_policy_title_without_topic")

    return boost

def _identity_document_service_boost(
    *,
    profile: dict[str, bool],
    normalized_title_path: str,
    metadata: dict,
    reasons: list[str],
) -> float:
    if not profile.get("identity_document"):
        return 0.0

    boost = 0.0
    doc_type = _normalize(
        str(
            metadata.get("document_type")
            or metadata.get("parser_document_type")
            or metadata.get("source_document_type")
            or ""
        )
    )
    article_type = _normalize(str(metadata.get("article_type") or metadata.get("content_type") or ""))
    office = _normalize(
        str(metadata.get("office") or metadata.get("responsible_office") or metadata.get("office_or_division") or "")
    )
    source_type = _normalize(str(metadata.get("source_type") or ""))

    if _is_identity_service_title(normalized_title_path):
        boost += 0.42
        reasons.append("boost_identity_service_title")
    if doc_type in {"citizen_charter", "procedure"} or "citizen" in source_type:
        boost += 0.3
        reasons.append("boost_citizen_charter_document_type")
    if article_type in {"service_procedure", "procedure"}:
        boost += 0.22
        reasons.append("boost_service_procedure_article_type")
    if _contains_any(office, ("student affairs", "osas", "office of the student affairs and services")):
        boost += 0.14
        reasons.append("boost_student_affairs_office")
    if _is_academic_subject_validation_title(normalized_title_path):
        boost -= 0.55
        reasons.append("penalty_subject_validation_for_id_query")
    elif "validation" in normalized_title_path and not _contains_any(
        normalized_title_path, ("id", "identification")
    ):
        boost -= 0.35
        reasons.append("penalty_non_id_validation_for_id_query")
    return boost


def _service_vs_form_boost(
    *,
    profile: dict[str, bool],
    normalized_query: str,
    normalized_title_path: str,
    metadata: dict,
    reasons: list[str],
) -> float:
    """Boost complete service procedures; penalize form/artifact chunks for howto queries."""
    if profile.get("form_requirement"):
        return 0.0
    if not (profile.get("service_howto") or profile.get("identity_document") or profile.get("requirements")):
        # Still dampen bare requirement-form titles for general service-looking queries.
        if not _matches(normalized_query, r"\bhow\b", r"\bwhere\b", r"\bavail\b", r"\bapply\b"):
            return 0.0

    article_type = _normalize(str(metadata.get("article_type") or metadata.get("content_type") or ""))
    extraction_status = _normalize(str(metadata.get("extraction_status") or ""))
    doc_type = _normalize(
        str(metadata.get("document_type") or metadata.get("parser_document_type") or "")
    )
    boost = 0.0

    if doc_type in {"citizen_charter", "procedure"} or article_type in {"service_procedure", "procedure"}:
        boost += 0.2
        reasons.append("boost_service_procedure_priority")
    if article_type in {"requirement_form", "requirement", "form"} or extraction_status == "rag_only":
        boost -= 0.55
        reasons.append("penalty_requirement_form_for_service_query")
    if normalized_title_path.startswith("requirement:"):
        boost -= 0.6
        reasons.append("penalty_requirement_title_prefix")
    if "needs review" in normalized_title_path or "[needs review]" in normalized_title_path:
        boost -= 0.5
        reasons.append("penalty_needs_review_placeholder")
    if _contains_any(
        normalized_title_path,
        (
            "abstract of quotation",
            "approving officials",
            "nexus system",
            "client steps",
            "agency actions",
        ),
    ):
        boost -= 0.45
        reasons.append("penalty_artifact_like_title")
    return boost


def _fee_service_boost(
    *,
    normalized_query: str,
    normalized_title_path: str,
    normalized_content: str,
    metadata: dict,
    reasons: list[str],
) -> float:
    """Prefer Citizen Charter fee cards for TOR / diploma / how-much questions."""
    asks_fee = bool(
        re.search(r"\b(?:how much|fee|fees|cost|per page)\b", normalized_query)
    )
    asks_tor = bool(re.search(r"\b(?:tor|transcript)\b", normalized_query))
    asks_diploma = "diploma" in normalized_query
    if not (asks_fee or asks_tor or asks_diploma):
        return 0.0

    boost = 0.0
    total_fees = str(metadata.get("total_fees") or metadata.get("fees") or "").strip()
    doc_type = _normalize(
        str(metadata.get("document_type") or metadata.get("parser_document_type") or "")
    )
    source_type = _normalize(str(metadata.get("source_type") or ""))
    is_charter = doc_type in {"citizen_charter", "procedure"} or "citizen" in source_type
    fee_text = _normalize(f"{total_fees} {normalized_content}")

    if asks_tor:
        if re.search(r"\b(?:transcript of records|issuance of transcript|\btor\b)\b", normalized_title_path):
            boost += 0.55
            reasons.append("boost_tor_service_title")
        elif _contains_any(
            normalized_title_path,
            ("annual report", "certificate of completion", "article 3 > registration"),
        ):
            boost -= 0.45
            reasons.append("penalty_non_tor_handbook_for_tor_query")
        if asks_fee and _contains_any(fee_text, ("p75", "75.00/page", "p150", "150/page")):
            boost += 0.55
            reasons.append("boost_tor_per_page_fee_text")

    if asks_diploma:
        fee_blob = _normalize(total_fees)
        if "diploma" in normalized_title_path or "diploma" in fee_blob:
            boost += 0.6
            reasons.append("boost_diploma_service_title")
        elif _contains_any(
            normalized_title_path,
            (
                "assessment of fees",
                "assessment of fee",
                "comprehensive examination",
                "examination fee",
                "open to all clients",
                "photocopy of examination",
                "faculty clearance",
                "crediting of subjects",
                "program accreditation",
                "certified true copy",
                "issuance of certified true copy",
            ),
        ):
            boost -= 0.65
            reasons.append("penalty_non_diploma_chunk_for_diploma_query")
        # Don't let any random fee card win diploma questions.
        if asks_fee and total_fees and "diploma" not in fee_blob and "diploma" not in normalized_title_path:
            return boost

    if asks_fee and total_fees and not (asks_diploma and "diploma" not in _normalize(total_fees) and "diploma" not in normalized_title_path):
        # When the query already names a service topic (or carries prior-context
        # tokens), only boost fee cards that overlap that topic — otherwise
        # generic "how much does it cost?" follow-ups promote unrelated fees.
        topic_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", normalized_query)
            if len(token) >= 3
            and token
            not in {
                "how", "much", "does", "the", "cost", "fee", "fees", "for", "and",
                "what", "about", "prior", "question", "context", "regarding",
                "long", "take", "please", "tell",
            }
        }
        if topic_tokens and not any(token in normalized_title_path for token in topic_tokens):
            return boost
        boost += 0.35
        reasons.append("boost_chunk_with_total_fees")
    if asks_fee and is_charter and total_fees and not (
        asks_diploma and "diploma" not in _normalize(total_fees) and "diploma" not in normalized_title_path
    ):
        topic_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", normalized_query)
            if len(token) >= 3
            and token
            not in {
                "how", "much", "does", "the", "cost", "fee", "fees", "for", "and",
                "what", "about", "prior", "question", "context", "regarding",
                "long", "take", "please", "tell",
            }
        }
        if topic_tokens and not any(token in normalized_title_path for token in topic_tokens):
            return boost
        boost += 0.2
        reasons.append("boost_charter_fee_metadata")
    return boost


def _is_identity_service_title(title_path: str) -> bool:
    has_id = _contains_any(title_path, ("id", "identification"))
    has_action = any(
        token in title_path
        for token in ("validat", "process", "issu", "renew", "replac")
    )
    return has_id and has_action


def _is_academic_subject_validation_title(title_path: str) -> bool:
    if "validation of subject" in title_path or "other validation case" in title_path:
        return True
    return "validation" in title_path and "subject" in title_path and "id" not in title_path


def _citation_grounding_boost(
    *,
    chunk: RetrievedChunk,
    metadata: dict,
    cache: dict[str, bool],
    reasons: list[str],
) -> float:
    document_id = str(chunk.document_id or metadata.get("document_id") or "").strip()
    page = metadata.get("page_number") or metadata.get("page_start") or metadata.get("page")
    has_page = isinstance(page, int) or (isinstance(page, str) and str(page).isdigit())
    if not document_id:
        reasons.append("penalty_missing_document_id")
        return -0.08
    ready = _chunk_is_citation_ready(chunk, cache)
    delta = 0.0
    if has_page:
        delta += 0.05
        reasons.append("boost_has_page_number")
    if ready:
        delta += 0.14
        reasons.append("boost_level2_citation_ready")
    else:
        delta -= 0.1
        reasons.append("penalty_orphan_or_missing_source_document")
    return delta


def _chunk_is_citation_ready(chunk: RetrievedChunk, cache: dict[str, bool]) -> bool:
    metadata = chunk.metadata or {}
    document_id = str(chunk.document_id or metadata.get("document_id") or "").strip()
    source_filename = str(
        chunk.source_filename or metadata.get("source_filename") or ""
    ).strip()
    cache_key = f"{document_id}|{source_filename}"
    if not document_id and not source_filename:
        return False
    if cache_key not in cache:
        try:
            from app.services.document_storage import resolve_citation_document

            cache[cache_key] = (
                resolve_citation_document(
                    document_id or None,
                    source_filename=source_filename or None,
                )
                is not None
            )
        except Exception:
            cache[cache_key] = False
    return bool(cache[cache_key])


def _path_domain_boost(domain: str, title_path: str, reasons: list[str]) -> float:
    if _contains_any(title_path, DOMAIN_PATH_TERMS[domain]):
        reasons.append(f"boost_path_domain_match:{domain}")
        return 0.3
    return 0.0


def _rule_matches(normalized_query: str, rule: QueryExpansionRule) -> bool:
    normalized_terms = tuple(_normalize(term) for term in rule.trigger_terms)
    if rule.match_all:
        triggered = all(term in normalized_query for term in normalized_terms)
    else:
        triggered = _contains_any(normalized_query, normalized_terms)
    if not triggered:
        return False
    if rule.blocked_terms and _contains_any(normalized_query, rule.blocked_terms):
        return False
    if rule.required_any_terms and not _contains_any(normalized_query, rule.required_any_terms):
        return False
    return True


def _normalize_student_phrasing(normalized_query: str, expansions: Iterable[str]) -> str:
    cleaned_query = _normalize_noisy_student_query(normalized_query)
    terms = list(expansions)
    if "when is lspu built" in cleaned_query or "when was lspu built" in cleaned_query:
        terms.extend(("lspu historical development", "established", "1952"))
    if _is_university_officials_query(cleaned_query):
        terms.extend(("administrative officials", "university president"))
    if "built" in cleaned_query:
        terms.extend(("established", "founded", "created", "historical development"))
    cleaned = _remove_minor_grammar_noise(cleaned_query)
    return " ".join(_dedupe([cleaned, *terms]))


def _normalize_noisy_student_query(text: str) -> str:
    normalized = _normalize_ascii(_normalize(text))
    normalized = re.sub(r"[^\w\s.%]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return ""

    typo_map = {
        "enrol": "enroll",
        "enrolment": "enrollment",
        "enrollmentt": "enrollment",
        "enrolement": "enrollment",
        "enrollmnt": "enrollment",
        "admisson": "admission",
        "admisison": "admission",
        "admissionn": "admission",
        "req": "requirements",
        "reqs": "requirements",
        "docs": "documents",
        "docu": "document",
        "sched": "schedule",
        "regis": "registrar",
        "registrat": "registrar",
        "regstrar": "registrar",
        "tuision": "tuition",
        "miscfee": "miscellaneous fee",
        "bayad": "fee",
        "magkano": "how much",
        "ano": "what",
        "pano": "how",
        "paano": "how",
        "kelan": "when",
        "san": "where",
        "saan": "where",
        "pwede": "can",
        "pwd": "can",
        "di": "not",
        "d": "not",
    }
    phrase_map = {
        r"\bpno\b": "paano",
        r"\bpa no\b": "paano",
        r"\bmag enroll\b": "enroll",
        r"\bmag enrol\b": "enroll",
        r"\bmag enroll\b": "enroll",
        r"\bhow to enroll\b": "enrollment procedure",
    }

    for pattern, replacement in phrase_map.items():
        normalized = re.sub(pattern, replacement, normalized)

    tokens = []
    for token in normalized.split():
        token = re.sub(r"(.)\1{2,}", r"\1\1", token)
        token = typo_map.get(token, token)
        if len(token) >= 7 and token.endswith("mentt"):
            token = token[:-1]
        tokens.append(token)
    normalized = " ".join(tokens)
    normalized = re.sub(r"\b(?:pls|pls\.|po)\b", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _remove_minor_grammar_noise(text: str) -> str:
    noise = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "can",
        "i",
        "my",
        "please",
    }
    tokens = re.findall(r"[a-z0-9.%]+", text)
    return " ".join(token for token in tokens if token not in noise)


def _is_university_officials_query(normalized_query: str) -> bool:
    if _contains_any(normalized_query, EXTERNAL_PRESIDENT_TERMS):
        return False
    if not _contains_any(normalized_query, ("president", "officials", "administration", "academic affairs", "research development")):
        return False
    return _contains_any(normalized_query, UNIVERSITY_OFFICIAL_CONTEXT_TERMS)


def _specific_curricular_path_boost(query: str, title_path: str, reasons: list[str]) -> float:
    boosts = (
        ("engineering", ("engineering",)),
        ("computer_studies", ("computer studies", "ccs", "information technology", "computer science")),
        ("business", ("business administration", "business")),
        ("education", ("education",)),
        ("arts_sciences", ("arts and sciences", "arts sciences")),
        ("agriculture", ("agriculture",)),
    )
    for label, terms in boosts:
        if _contains_any(query, terms) and _contains_any(title_path, terms):
            reasons.append(f"boost_curricular_path_match:{label}")
            return 0.22
    return 0.0


def _domain_noise_penalty(
    *,
    profile: dict[str, bool],
    normalized_query: str,
    normalized_content: str,
    normalized_title_path: str,
    content_type: str,
    reasons: list[str],
) -> float:
    if not (
        profile["attendance"]
        or profile["retention"]
        or profile["graduation"]
        or profile["curricular"]
        or profile["records"]
        or profile["enrollment"]
        or profile["counseling"]
    ):
        return 0.0

    penalty = 0.0
    if _contains_any(normalized_content, DISCIPLINARY_TERMS) or content_type in {"disciplinary_rule", "offense"}:
        # Identity-document service answers often mention ID cards; do not treat as disciplinary noise.
        if not (
            profile.get("identity_document")
            and _contains_any(normalized_content, ("identification card", "id validation", "student id"))
        ):
            penalty -= 0.55
            reasons.append("penalty_disciplinary_offense_out_of_domain")
    if _contains_any(normalized_title_path, APPENDIX_TERMS) or "appendix" in content_type:
        penalty -= 0.45
        reasons.append("penalty_unrelated_appendix")
    if (
        not profile.get("identity_document")
        and not profile.get("service_howto")
        and (_contains_any(normalized_content, PROCEDURAL_TERMS) or "procedure" in content_type)
    ):
        penalty -= 0.4
        reasons.append("penalty_unrelated_procedure")
    if not profile["awards"] and _contains_any(normalized_content, AWARD_TERMS):
        penalty -= 0.35
        reasons.append("penalty_awards_out_of_domain")
    if profile["curricular"]:
        penalty += _penalize_unrequested_terms(
            normalized_query,
            normalized_content,
            (
                ("student_services", ("student services",)),
                ("counseling", ("counseling", "guidance counseling")),
                ("admission", ("admission", "admissions")),
                ("registrar", ("registrar",)),
                ("tele_web", ("tele-web", "tele web", "teleweb")),
            ),
            reasons,
            amount=0.55,
        )
    if profile["attendance"]:
        penalty += _penalize_unrequested_terms(
            normalized_query,
            normalized_content,
            (
                ("registrar_visitation", ("registrar visitation",)),
                ("petition_subject", ("petition subject", "petitioned subject")),
                ("academic_load", ("academic load",)),
                ("graduation", ("graduation", "candidate for graduation")),
            ),
            reasons,
            amount=0.55,
        )
    if profile["records"]:
        penalty += _penalize_unrequested_terms(
            normalized_query,
            normalized_content,
            (
                ("administrative_officials", ("administrative officials", "university president")),
                ("student_services", ("student services", "student welfare")),
            ),
            reasons,
            amount=0.45,
        )
    if profile["retention"]:
        if not profile["awards"] and _contains_any(normalized_content, AWARD_TERMS):
            penalty -= 0.35
            reasons.append("penalty_retention_awards_noise")
        if not _is_grade_removal_query(normalized_query):
            penalty += _penalize_unrequested_terms(
                normalized_query,
                normalized_content,
                (
                    ("inc", ("inc", "incomplete")),
                    ("grade_removal", ("4.00 removal", "4.00 removal policy", "removal policy")),
                    ("grading_system", ("grading system",)),
                ),
                reasons,
                amount=0.5,
            )
    return penalty


def _penalize_unrequested_terms(
    query: str,
    content: str,
    term_groups: Iterable[tuple[str, Iterable[str]]],
    reasons: list[str],
    *,
    amount: float,
) -> float:
    penalty = 0.0
    for label, terms in term_groups:
        normalized_terms = tuple(_normalize(term) for term in terms)
        if not _contains_any(content, normalized_terms) or _contains_any(query, normalized_terms):
            continue
        penalty -= amount
        reasons.append(f"penalty_unrequested_{label}")
    return penalty


def _is_grade_removal_query(normalized_query: str) -> bool:
    return _contains_any(
        normalized_query,
        ("4.00", "4 00", "grade removal", "removal policy", "remove a grade", "inc", "incomplete", "completion grade"),
    )


def _keyword_overlap_boost(query: str, title_path: str, reasons: list[str]) -> float:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", query)
        if len(token) >= 4 and token not in GENERIC_INTENT_TOKENS
    }
    if not tokens:
        return 0.0
    title_folded = _lexical_token_set(title_path)
    matched = [token for token in tokens if _token_matches_folded(token, title_folded)]
    if not matched:
        return 0.0
    boost = min(0.22, 0.055 * len(matched))
    reasons.append("title_path_keyword_match")
    return boost


def _is_leave_of_absence_query(normalized_query: str) -> bool:
    if "leave of absence" in normalized_query:
        return True
    return bool(re.search(r"\bloa\b", normalized_query))


def _is_faculty_audience_query(normalized_query: str) -> bool:
    return _contains_any(normalized_query, FACULTY_AUDIENCE_TERMS) or _matches(
        normalized_query,
        r"\bfaculty\b",
        r"\bprofessor\b",
        r"\binstructor\b",
        r"\bteaching load\b",
    )


def _is_teaching_load_query(normalized_query: str) -> bool:
    return _matches(
        normalized_query,
        r"\bteaching load\b",
        r"\bfaculty load\b",
        r"\bfaculty\b.*\b(?:load|workload|assigned|assignment|instruction)\b",
        r"\b(?:load|workload)\b.*\bfaculty\b",
        r"\bhow is teaching load\b",
        r"\binstruction hours?\b",
        r"\binstruction load\b",
        r"\bweekly (?:instruction |teaching )?load\b",
        r"\bdesignated as dean\b",
        r"\bdean\b.*\binstruction\b",
        r"\bregular faculty\b.*\b(?:hour|load|instruction)\b",
    )


def _is_academic_freedom_query(normalized_query: str) -> bool:
    return _matches(
        normalized_query,
        r"\bacademic freedom\b",
        r"\bindoctrination\b",
        r"\bcampaign\b.*\bpolitical\b",
        r"\bpolitical party\b",
        r"\bclass(?:room)? time\b.*\bcampaign\b",
    )


def _is_maximum_residence_query(normalized_query: str) -> bool:
    return _matches(
        normalized_query,
        r"\bmaximum residence\b",
        r"\bresidence rule\b",
        r"\bmaximum residency\b",
    )


def _is_tuition_refund_query(normalized_query: str) -> bool:
    return _matches(
        normalized_query,
        r"\brefund\b",
        r"\brefunded\b",
        r"\bwithdraw\b.*\b(?:tuition|enrollment fees|enrolment fees|paid)\b",
    )


def is_faculty_restricted_query(query: str) -> bool:
    """True when the answer lives in the Faculty Manual, not student-facing KB."""
    normalized = _normalize(query)
    return (
        _is_teaching_load_query(normalized)
        or _is_academic_freedom_query(normalized)
        or _is_faculty_grading_query(normalized)
        or _is_faculty_grade_change_query(normalized)
        or _is_faculty_responsibilities_query(normalized)
        or _is_faculty_class_time_query(normalized)
    )


def _repair_common_query_typos(query: str) -> str:
    """Fix the most common first-word typos so retrieval still hits policy titles."""
    text = (query or "").strip()
    text = re.sub(r"^(?:ow|hw|hwo|ho)\b", "How", text, flags=re.I)
    text = re.sub(r"^(?:wat|wht|waht)\b", "What", text, flags=re.I)
    text = re.sub(r"^(?:wnere|wher)\b", "Where", text, flags=re.I)
    return text


def _is_faculty_grading_query(normalized_query: str) -> bool:
    if _is_faculty_grade_change_query(normalized_query):
        return False
    if not _matches(normalized_query, r"\bgrad(?:e|es|ing)\b"):
        return False
    return _is_faculty_audience_query(normalized_query) or _matches(
        normalized_query,
        r"\bgrading sheets?\b",
        r"\bfaculty grading\b",
    )


def _is_shifting_query(normalized_query: str) -> bool:
    if not _matches(normalized_query, r"\bshift(?:ing)?\b"):
        return False
    return _matches(
        normalized_query,
        r"\bcourse\b",
        r"\bprogram\b",
        r"\bbs\b",
        r"\bb\.s\.\b",
        r"\bmajor\b",
        r"\banother\b",
    )


def _is_faculty_grade_change_query(normalized_query: str) -> bool:
    if not _matches(normalized_query, r"\bgrad(?:e|es|ing)\b"):
        return False
    return _matches(
        normalized_query,
        r"\brectification\b",
        r"\bgrade change\b",
        r"\bchange of grades?\b",
        r"\bchange/rectification\b",
        r"\b25\s*(?:percent|%)\b.*\bclass\b",
        r"\bclass\b.*\b25\s*(?:percent|%)\b",
    )


def _is_faculty_class_time_query(normalized_query: str) -> bool:
    return _matches(
        normalized_query,
        r"\bdismiss(?: my)? class",
        r"\bdismiss(?:ing)? class(?:es)?\b",
        r"\bearlier than (?:the )?official time\b",
        r"\bhold classes on time\b",
    )


def _is_faculty_responsibilities_query(normalized_query: str) -> bool:
    return _matches(
        normalized_query,
        r"\bresponsibilit(?:y|ies) of faculty\b",
        r"\bfaculty responsibilit",
        r"\bduties of faculty\b",
        r"\bfaculty (?:member|members)?\b.*\bresponsibilit",
        r"\bresponsibilit(?:y|ies)\b.*\bfaculty\b",
    )


def _chunk_looks_like_faculty_manual(
    normalized_title_path: str,
    metadata: dict | None = None,
) -> bool:
    if _contains_any(
        normalized_title_path,
        ("faculty manual", "lspu faculty", "faculty_manual"),
    ) or bool(re.search(r"\bfaculty manual\b", normalized_title_path)):
        return True
    meta = metadata or {}
    filename = _normalize(str(meta.get("source_filename") or ""))
    doc_type = _normalize(str(meta.get("document_type") or meta.get("article_type") or ""))
    return "faculty manual" in filename or doc_type == "faculty_manual"


def _chunk_looks_like_student_handbook(
    normalized_title_path: str,
    metadata: dict | None = None,
) -> bool:
    if _chunk_looks_like_faculty_manual(normalized_title_path, metadata):
        return False
    filename = _normalize(str((metadata or {}).get("source_filename") or ""))
    if "faculty manual" in filename:
        return False
    return _contains_any(
        normalized_title_path,
        ("student handbook", "lspu student handbook", "handbook"),
    ) or "student handbook" in filename


def _faculty_audience_rerank_delta(
    *,
    profile: dict[str, bool],
    normalized_title_path: str,
    normalized_content: str,
    metadata: dict | None,
    reasons: list[str],
) -> float:
    """Boost Faculty Manual / faculty policy chunks; demote student-homonym collisions."""
    if not (
        profile.get("faculty")
        or profile.get("teaching_load")
        or profile.get("faculty_grading")
        or profile.get("faculty_grade_change")
        or profile.get("faculty_responsibilities")
        or profile.get("faculty_class_time")
        or profile.get("academic_freedom")
    ):
        return 0.0

    delta = 0.0
    if _chunk_looks_like_faculty_manual(normalized_title_path, metadata):
        delta += 0.38
        reasons.append("boost_faculty_manual_for_faculty_query")
    elif _chunk_looks_like_student_handbook(normalized_title_path, metadata):
        delta -= 0.32
        reasons.append("penalty_student_handbook_for_faculty_query")

    if profile.get("teaching_load"):
        if _contains_any(normalized_title_path, TEACHING_LOAD_TERMS) or _contains_any(
            normalized_content, ("time allotment for teaching", "teaching load assignment")
        ):
            delta += 0.42
            reasons.append("boost_teaching_load_section")
        if _contains_any(normalized_title_path, STUDENT_COURSE_LOAD_TERMS) and not _contains_any(
            normalized_title_path, TEACHING_LOAD_TERMS
        ):
            delta -= 0.55
            reasons.append("penalty_student_course_load_for_teaching_load_query")

    if profile.get("academic_freedom"):
        if _contains_any(normalized_content, ACADEMIC_FREEDOM_TERMS):
            delta += 0.42
            reasons.append("boost_academic_freedom_faculty_manual")
        if _contains_any(normalized_title_path, STUDENT_COURSE_LOAD_TERMS):
            delta -= 0.4
            reasons.append("penalty_student_load_for_academic_freedom")

    if profile.get("faculty_grading"):
        if _contains_any(normalized_title_path, FACULTY_GRADING_TERMS) or "grading sheets" in normalized_content:
            delta += 0.4
            reasons.append("boost_faculty_grading_section")
        if _contains_any(normalized_title_path, STUDENT_GRADE_CHANGE_TERMS):
            delta -= 0.45
            reasons.append("penalty_student_grade_rectification_for_faculty_grading")

    if profile.get("faculty_grade_change"):
        if _contains_any(normalized_title_path, STUDENT_GRADE_CHANGE_TERMS) or "rectification" in normalized_title_path:
            delta += 0.48
            reasons.append("boost_faculty_grade_rectification")
        if _contains_any(normalized_content, FACULTY_GRADE_CHANGE_TERMS):
            delta += 0.2
            reasons.append("boost_faculty_grade_change_threshold")
        if "submission of grades" in normalized_title_path and _contains_any(
            normalized_content, ("twenty-five percent", "rectification", "academic council")
        ):
            delta += 0.42
            reasons.append("boost_submission_of_grades_rectification_body")
        if _contains_any(normalized_title_path, ("grading sheets",)) and "rectification" not in normalized_title_path:
            delta -= 0.3
            reasons.append("penalty_grading_sheets_for_grade_change_query")
        if _chunk_looks_like_student_handbook(normalized_title_path, metadata) and _contains_any(
            normalized_title_path, STUDENT_GRADE_CHANGE_TERMS
        ):
            delta -= 0.35
            reasons.append("penalty_student_handbook_rectification_for_faculty_change")

    if profile.get("faculty_responsibilities"):
        if _contains_any(normalized_title_path, FACULTY_RESPONSIBILITY_TERMS) or _contains_any(
            normalized_content, ("commitment of oneself", "code of ethics")
        ):
            delta += 0.4
            reasons.append("boost_faculty_responsibility_section")
        if _contains_any(normalized_title_path, NARROW_FACULTY_ROLE_TERMS):
            delta -= 0.48
            reasons.append("penalty_narrow_faculty_role_for_broad_responsibilities")

    if profile.get("faculty_class_time"):
        if _contains_any(normalized_content, ("shall not be allowed to dismiss", "earlier than the official time")):
            delta += 0.48
            reasons.append("boost_faculty_dismiss_class_rule")
        if _chunk_looks_like_student_handbook(normalized_title_path, metadata) and _contains_any(
            normalized_title_path, ("attendance", "excuse slip")
        ):
            delta -= 0.5
            reasons.append("penalty_student_attendance_for_faculty_class_time")

    return delta


def _is_academic_dismissal_query(normalized_query: str) -> bool:
    if _is_faculty_class_time_query(normalized_query):
        return False
    return "dismiss" in normalized_query and not _is_honorable_dismissal_query(normalized_query)


def _is_honorable_dismissal_query(normalized_query: str) -> bool:
    return _contains_any(normalized_query, HONORABLE_TERMS)


def _is_undergraduate_chunk(normalized_content: str, metadata: dict | None = None) -> bool:
    content_type = _normalize(str((metadata or {}).get("content_type") or ""))
    return content_type == "program_listing" and not _is_graduate_chunk(normalized_content) or _contains_any(
        normalized_content,
        ("undergraduate", "bachelor", "bs computer", "bs information", "bsit", "bscs"),
    )


def _is_graduate_chunk(normalized_content: str) -> bool:
    return _contains_any(normalized_content, ("graduate studies", "master", "doctorate")) or bool(
        re.search(r"\b(?:ph\.?d|m\.?a|m\.?s)\b", normalized_content)
    )


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(_normalize(term) in text for term in terms)


def _matches(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def _normalize(text: str) -> str:
    cleaned = (text or "").lower()
    cleaned = re.sub(r"[-_/]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_ascii(text: str) -> str:
    """Lowercase + strip accents/punctuation for noisy student query cleanup."""
    normalized = _normalize(text).replace("ñ", "n")
    normalized = re.sub(r"[^a-z0-9.]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            output.append(value)
            seen.add(key)
    return output

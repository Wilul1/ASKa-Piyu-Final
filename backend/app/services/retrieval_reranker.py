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
ENROLLMENT_TERMS = ("enrollment", "enroll", "registration", "assessment of fees", "registrar")
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
PROCEDURAL_TERMS = ("ojt", "on-the-job", "on the job", "procedure", "procedures", "process flow")
APPENDIX_TERMS = ("appendix", "appendices", "form template")
AWARD_TERMS = ("award", "awards", "honor", "honors", "medal", "recognition")
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
    ),
    QueryExpansionRule(
        name="scholastic_delinquency_failed_units",
        trigger_terms=("failed units", "failing", "failed", "fail", "many subjects", "probation", "dismissal"),
        expansion_terms=("scholastic delinquency", "warning", "probation", "dismissal", "failed academic units"),
    ),
    QueryExpansionRule(
        name="curricular_offerings_programs",
        trigger_terms=("programs offered", "program offered", "programs", "offered", "course offerings", "curricular"),
        expansion_terms=PROGRAM_TERMS,
    ),
    QueryExpansionRule(
        name="enrollment_procedure",
        trigger_terms=("how do i enroll", "enroll", "enrollment", "registration"),
        expansion_terms=ENROLLMENT_TERMS,
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
)


def expand_query(query: str) -> str:
    """Append retrieval-oriented synonyms for broad natural language questions."""
    return prepare_retrieval_query(query).expanded_query


def prepare_retrieval_query(query: str) -> PreparedRetrievalQuery:
    """Normalize natural student phrasing while preserving the original query."""
    original = query.strip()
    normalized = _normalize(query)
    expansions: list[str] = []
    matched_rules: list[str] = []

    for rule in QUERY_EXPANSION_RULES:
        if _rule_matches(normalized, rule):
            expansions.extend(rule.expansion_terms)
            matched_rules.append(rule.name)

    if _matches(normalized, r"\bfail(?:ed|ing)?\b", r"\bmany subjects?\b", r"\bcontinue (?:my )?course\b"):
        expansions.extend(ACADEMIC_TERMS)
    if "probation" in normalized:
        expansions.extend(("scholastic delinquency", "retention policy", "warning", "probation"))
    if _is_academic_dismissal_query(normalized):
        expansions.extend(("retention policy", "academic dismissal", "scholastic delinquency"))
    if _is_honorable_dismissal_query(normalized):
        expansions.extend(("honorable dismissal", "voluntary withdrawal", "registrar"))
    if _matches(normalized, r"\babsen[tc]\b", r"\billness\b", r"\bexcuse\b", r"\bmedical\b"):
        expansions.extend(ATTENDANCE_TERMS)
    if _matches(normalized, r"\bshift(?:ing)?\b.*\bcourse\b", r"\bchange\b.*\bcourse\b"):
        expansions.extend(("shifting of course", "registrar", "shifting form", "admission requirements"))
    if _matches(normalized, r"\bundergraduate\b", r"\bbachelor\b", r"\bbs\b", r"\bb\.s\.\b"):
        expansions.extend(("undergraduate programs", "curricular offerings", "bachelor", "BS"))
    if _matches(normalized, r"\bgraduate\b", r"\bmaster\b", r"\bdoctorate\b", r"\bphd\b", r"\bma\b", r"\bms\b"):
        expansions.extend(("graduate studies", "master", "doctorate", "PhD", "MA", "MS"))
    if _matches(normalized, r"\bcollege\b.*\bprogram", r"\bcampus(?:es)?\b.*\boffer", r"\boffer(?:ed|s)?\b.*\bprogram"):
        expansions.extend(PROGRAM_TERMS)

    unique = _dedupe(expansions)
    normalized_for_retrieval = _normalize_student_phrasing(normalized, unique)
    expanded = _dedupe([original, normalized_for_retrieval, *unique])
    return PreparedRetrievalQuery(
        original_query=original,
        normalized_query=normalized_for_retrieval,
        expanded_query=" ".join(item for item in expanded if item).strip(),
        matched_expansion_rules=matched_rules,
    )


def rerank_chunks(query: str, chunks: Iterable[RetrievedChunk]) -> list[RetrievedChunk]:
    normalized_query = _normalize(query)
    profile = _query_profile(normalized_query)
    reranked: list[RetrievedChunk] = []

    for chunk in chunks:
        original = chunk.original_score if chunk.original_score is not None else chunk.relevance_score
        score = float(original)
        reasons: list[str] = []
        metadata = chunk.metadata or {}
        title = str(metadata.get("section") or metadata.get("article") or metadata.get("chapter") or chunk.title or "")
        path = _metadata_path(metadata)
        metadata_labels = " ".join(
            str(metadata.get(key) or "")
            for key in ("category", "subcategory", "office", "responsible_office", "source_document", "source_filename")
        )
        content = f"{title} {path} {metadata_labels} {chunk.text}"
        normalized_content = _normalize(content)
        normalized_title_path = _normalize(f"{title} {path} {metadata_labels}")
        metadata_content_type = _normalize(str(metadata.get("content_type") or ""))

        score += _keyword_overlap_boost(normalized_query, normalized_title_path, reasons)

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
        if profile["fail_75"] and "dismiss" in normalized_content and "honorable dismissal" not in normalized_content:
            score += 0.32
            reasons.append("failed_units_dismissal")
        if profile["honorable"] and _contains_any(normalized_content, HONORABLE_TERMS):
            score += 0.28
            reasons.append("honorable_dismissal_match")
        if profile["attendance"] and _contains_any(normalized_content, ATTENDANCE_TERMS):
            score += 0.28
            reasons.append("attendance_policy_match")
        if profile["enrollment"] and _contains_any(normalized_content, ENROLLMENT_TERMS):
            score += 0.24
            reasons.append("enrollment_procedure_match")
        if profile["records"] and _contains_any(normalized_content, RECORD_TERMS):
            score += 0.28
            reasons.append("student_records_match")
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
        metadata_score, metadata_reasons = category_metadata_boost(normalized_query, metadata)
        if metadata_score:
            score += metadata_score
            reasons.extend(metadata_reasons)
        if _has_valid_source_metadata(metadata):
            score += 0.04
            reasons.append("boost_valid_source_metadata")
        if profile["external_topic"] and _contains_any(normalized_title_path, ("administrative officials", "university president", "board of regents")):
            score -= 0.85
            reasons.append("penalty_external_topic_admin_title")

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

        chunk.original_score = round(original, 4)
        chunk.reranked_score = round(score, 4)
        chunk.relevance_score = chunk.reranked_score
        chunk.rerank_reasons = reasons or ["semantic_similarity"]
        reranked.append(chunk)

    return sorted(reranked, key=lambda item: (item.reranked_score or item.relevance_score), reverse=True)


def _query_profile(normalized_query: str) -> dict[str, bool]:
    honorable = _is_honorable_dismissal_query(normalized_query)
    undergraduate = _matches(normalized_query, r"\bundergraduate\b", r"\bbachelor\b", r"\bbs\b", r"\bb\.s\.\b")
    graduate = _matches(normalized_query, r"\bgraduate\b", r"\bmaster\b", r"\bdoctorate\b", r"\bphd\b", r"\bma\b", r"\bms\b")
    failing = _matches(normalized_query, r"\bfail(?:ed|ing)?\b", r"\bmany subjects?\b", r"\b75\s*%", r"\bfailed units?\b")
    attendance = _matches(normalized_query, r"\battendance\b", r"\babsen[tc]\b", r"\billness\b", r"\bexcuse\b", r"\bmedical\b")
    enrollment = _matches(normalized_query, r"\benroll(?:ment)?\b", r"\bregistration\b", r"\bhow do i enroll\b")
    records = _matches(normalized_query, r"\btor\b", r"\btranscript\b", r"\bcopy of grades\b", r"\bgood moral\b", r"\bcertificate of registration\b")
    counseling = _matches(normalized_query, r"\bcounsel(?:ing|ling)\b", r"\bguidance\b", r"\bwho handles counseling\b")
    requirements = _matches(normalized_query, r"\brequirements?\b", r"\bdocuments?\b", r"\bwhat do i need\b")
    graduation = _matches(normalized_query, r"\bgraduat(?:e|es|ed|ing|ion)\b", r"\bclearance\b", r"\bdiploma\b", r"\bcommencement\b")
    curricular = _matches(
        normalized_query,
        r"\bcurricular\b",
        r"\bprogram",
        r"\bcourse offerings?\b",
        r"\bcampus(?:es)?\b.*\boffer",
        r"\boffer(?:ed|s)?\b.*\bprogram",
    )
    academic_risk = not honorable and (
        failing
        or "probation" in normalized_query
        or "retention" in normalized_query
        or "scholastic delinquency" in normalized_query
        or "dismissal" in normalized_query
    )
    return {
        "academic_risk": academic_risk,
        "retention": academic_risk or "retention" in normalized_query or "scholastic delinquency" in normalized_query,
        "failing_many": failing or "continue course" in normalized_query,
        "fail_75": bool(re.search(r"\b75\s*%", normalized_query)) and "fail" in normalized_query,
        "honorable": honorable,
        "attendance": attendance,
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
    }


def _detected_domain(profile: dict[str, bool]) -> str | None:
    for domain in ("attendance", "retention", "graduation", "curricular", "history", "officials", "enrollment", "records", "counseling"):
        if profile.get(domain):
            return domain
    return None


def _metadata_path(metadata: dict) -> str:
    return " ".join(str(metadata.get(key) or "") for key in ("chapter", "article", "section", "appendix"))


def _has_valid_source_metadata(metadata: dict) -> bool:
    page = metadata.get("page_start") or metadata.get("page")
    has_page = isinstance(page, int) or (isinstance(page, str) and page.isdigit())
    has_source = any(str(metadata.get(key) or "").strip() for key in ("source_filename", "source_document", "source_title"))
    return has_page and has_source


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
    terms = list(expansions)
    if "when is lspu built" in normalized_query or "when was lspu built" in normalized_query:
        terms.extend(("lspu historical development", "established", "1952"))
    if _is_university_officials_query(normalized_query):
        terms.extend(("administrative officials", "university president"))
    if "built" in normalized_query:
        terms.extend(("established", "founded", "created", "historical development"))
    cleaned = _remove_minor_grammar_noise(normalized_query)
    return " ".join(_dedupe([cleaned, *terms]))


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
        penalty -= 0.55
        reasons.append("penalty_disciplinary_offense_out_of_domain")
    if _contains_any(normalized_title_path, APPENDIX_TERMS) or "appendix" in content_type:
        penalty -= 0.45
        reasons.append("penalty_unrelated_appendix")
    if _contains_any(normalized_content, PROCEDURAL_TERMS) or "procedure" in content_type:
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
    tokens = {token for token in re.findall(r"[a-z0-9]+", query) if len(token) >= 4}
    if not tokens:
        return 0.0
    matched = [token for token in tokens if token in title_path]
    if not matched:
        return 0.0
    boost = min(0.18, 0.045 * len(matched))
    reasons.append("title_path_keyword_match")
    return boost


def _is_academic_dismissal_query(normalized_query: str) -> bool:
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
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            output.append(value)
            seen.add(key)
    return output

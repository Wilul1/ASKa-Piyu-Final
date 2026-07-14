"""Generic article summary and display-text cleanup for admin review."""
from __future__ import annotations

import re

_SUMMARY_MAX_SENTENCES = 2
_SUMMARY_TARGET_MAX_CHARS = 350

_NUMBERED_CLAUSE_PREFIX = re.compile(
    r"^\s*(?:\d+(?:\.\d+)+|\d+[\.\)]|[ivxlc]+\.|[a-z]\))\s+",
    re.IGNORECASE,
)

# Longest phrases first so multi-word concepts are captured before fragments.
_CONCEPT_PHRASES: tuple[tuple[str, str], ...] = (
    ("face-to-face counseling", "face-to-face counseling"),
    ("face to face counseling", "face-to-face counseling"),
    ("virtual counseling", "virtual counseling"),
    ("admission requirements", "admission requirements"),
    ("follow-up", "follow-up"),
    ("follow up", "follow-up"),
    ("case conference", "case conferences"),
    ("face-to-face", "face-to-face counseling"),
    ("face to face", "face-to-face counseling"),
    ("consultation", "consultation"),
    ("conference", "conference"),
    ("referral", "referral"),
    ("requirements", "requirements"),
    ("requirement", "requirements"),
    ("procedure", "procedure"),
    ("submission", "submission"),
    ("deadline", "deadlines"),
    ("eligibility", "eligibility"),
    ("documents", "documents"),
    ("services", "services"),
    ("policy", "policy"),
    ("process", "process"),
    ("steps", "steps"),
)

_PROCEDURE_CONCEPT_PRIORITY = (
    "referral",
    "follow-up",
    "consultation",
    "process",
    "steps",
    "procedure",
    "virtual counseling",
    "face-to-face counseling",
    "conference",
    "services",
)

_PROCEDURE_SIGNALS = (
    "process",
    "procedure",
    "steps",
    "step",
    "follow-up",
    "follow up",
    "referral",
    "consultation",
    "how to",
    "session",
)

_REQUIREMENT_SIGNALS = (
    "form",
    "requirement",
    "requirements",
    "submit",
    "document",
    "deadline",
    "eligibility",
    "fill out",
    "application",
)

_COUNSELING_TERMS = (
    "counseling",
    "counselling",
    "counselee",
    "face-to-face",
    "face to face",
    "referral",
    "multidisciplinary",
    "consultation",
    "virtual counseling",
)

_GENERIC_SUMMARY_MARKERS = (
    "based on the uploaded source document",
    "explains the main steps students should follow",
    "the information students need to provide",
)

_AWKWARD_PHRASE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bper se\b", re.IGNORECASE), ""),
    (re.compile(r"\bherein\b", re.IGNORECASE), ""),
    (re.compile(r"\baforementioned\b", re.IGNORECASE), "the"),
    (re.compile(r"\bthereof\b", re.IGNORECASE), ""),
    (
        re.compile(r"\bfollow-?up counselee(?: with cases)?\b", re.IGNORECASE),
        "follow-up assistance",
    ),
    (re.compile(r"\bcase conference\b", re.IGNORECASE), "case conferences"),
    (
        re.compile(
            r"\brefer(?:red)? if necessary to (?:a )?multidisciplinary team(?: of specialists)?\b",
            re.IGNORECASE,
        ),
        "students may be referred to a multidisciplinary team when needed",
    ),
    (
        re.compile(
            r"\breferrals when needed to (?:a )?multidisciplinary team(?: of specialists)?\b",
            re.IGNORECASE,
        ),
        "referrals to a multidisciplinary team when needed",
    ),
    (re.compile(r"\brefer(?:red)? if necessary\b", re.IGNORECASE), "referral when needed"),
    (re.compile(r"\s{2,}"), " "),
)

_INCOMPLETE_SUPPLEMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\breferrals when needed to\b", re.IGNORECASE),
    re.compile(r"\bwhen needed to (?:a )?multidisciplinary\b", re.IGNORECASE),
    re.compile(r"\breferral when needed to\b", re.IGNORECASE),
)


def clean_article_content_for_display(text: str) -> str:
    """Apply conservative OCR/display cleanup without rewriting policy meaning."""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"([A-Za-z])-\n([A-Za-z])", r"\1\2", text)
    text = re.sub(r"([a-z])-\s+([a-z]{2,})", r"\1\2", text, flags=re.IGNORECASE)

    lines: list[str] = []
    for line in text.splitlines():
        lines.append(re.sub(r"[ \t]+", " ", line).strip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", normalized)
    return [part.strip() for part in parts if part.strip()]


def _strip_leading_numbered_clause(text: str) -> str:
    stripped = text.strip()
    while stripped:
        updated = _NUMBERED_CLAUSE_PREFIX.sub("", stripped, count=1)
        if updated == stripped:
            break
        stripped = updated.strip()
    return stripped


def _trim_summary_length(text: str, *, max_chars: int = _SUMMARY_TARGET_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    last_stop = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    if last_stop >= max_chars // 3:
        return truncated[: last_stop + 1].strip()

    trimmed = truncated.rsplit(" ", 1)[0].strip()
    return trimmed if trimmed else truncated.strip()


def _normalize_compare_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _summaries_overlap(summary: str, content: str) -> bool:
    norm_summary = _normalize_compare_text(summary)
    norm_content = _normalize_compare_text(content)
    if not norm_summary or not norm_content:
        return False
    if norm_summary == norm_content:
        return True
    if norm_content.startswith(norm_summary) and len(norm_summary) >= len(norm_content) * 0.6:
        return True
    if norm_summary.startswith(norm_content[: min(len(norm_content), 240)]):
        return True
    return False


def _simplify_awkward_phrases(text: str) -> str:
    updated = text.strip()
    for pattern, replacement in _AWKWARD_PHRASE_REPLACEMENTS:
        updated = pattern.sub(replacement, updated)
    updated = re.sub(r"\s+([,.;])", r"\1", updated)
    updated = re.sub(r"\s{2,}", " ", updated)
    return updated.strip(" ,;")


def _polish_supplement_clause(text: str) -> str:
    updated = _simplify_awkward_phrases(text)
    updated = re.sub(
        r"\breferrals when needed to (?:a )?multidisciplinary team(?: of specialists)?\b",
        "referrals to a multidisciplinary team when needed",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"\brefer(?:red)? if necessary to (?:a )?multidisciplinary team(?: of specialists)?\b",
        "students may be referred to a multidisciplinary team when needed",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"\b(?<!a )multidisciplinary team\b",
        "a multidisciplinary team",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"\ba a multidisciplinary team\b",
        "a multidisciplinary team",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(r"\s{2,}", " ", updated)
    return updated.strip(" ,;")


def _is_incomplete_supplement(clause: str) -> bool:
    normalized = clause.strip()
    if not normalized:
        return True
    if any(pattern.search(normalized) for pattern in _INCOMPLETE_SUPPLEMENT_PATTERNS):
        return True
    if re.search(r"\bto ensure\b", normalized, re.IGNORECASE) and "referral" in normalized.lower():
        return True
    return False


def _wrap_supplement_clause(clause: str) -> str | None:
    polished = _polish_supplement_clause(clause)
    if not polished or _is_incomplete_supplement(polished):
        return None
    if polished.lower().startswith("students "):
        return f"It also notes that {polished}."
    first_char = polished[0].lower() + polished[1:] if len(polished) > 1 else polished.lower()
    return f"It also notes that {first_char}."


def _format_concept_list(concepts: list[str]) -> str:
    if not concepts:
        return ""
    if len(concepts) == 1:
        return concepts[0]
    if len(concepts) == 2:
        return f"{concepts[0]} and {concepts[1]}"
    return ", ".join(concepts[:-1]) + f", and {concepts[-1]}"


def _title_summary_phrase(title_clean: str, kind: str) -> str:
    lowered = title_clean.lower()
    if lowered.endswith("services") or lowered.endswith("service"):
        return "explains the support provided to students"
    if lowered.endswith("process"):
        return "explains the process"
    if lowered.endswith("policy"):
        return "explains the policy"
    if lowered.endswith("procedure"):
        return "explains the procedure"
    if kind == "requirement":
        return "describes the requirements and information students need"
    if kind == "procedure":
        return "explains the steps students should follow"
    return f"explains {lowered}"


def _extract_key_concepts(content: str, *, title: str | None = None) -> list[str]:
    lower = content.lower()
    title_lower = (title or "").lower()
    found: list[str] = []
    seen: set[str] = set()
    for phrase, label in _CONCEPT_PHRASES:
        if phrase not in lower:
            continue
        if label in seen:
            continue
        if any(term in label.lower() for term in _COUNSELING_TERMS):
            if not any(term in title_lower or term in lower for term in _COUNSELING_TERMS):
                continue
        found.append(label)
        seen.add(label)
    if "case conferences" in seen and "conference" in seen:
        found = [concept for concept in found if concept != "conference"]
    return found


def _prioritize_concepts(concepts: list[str], kind: str) -> list[str]:
    if kind != "procedure":
        return concepts

    ordered: list[str] = []
    remaining = list(concepts)
    for preferred in _PROCEDURE_CONCEPT_PRIORITY:
        for concept in list(remaining):
            if concept == preferred or preferred in concept:
                ordered.append(concept)
                remaining.remove(concept)
    ordered.extend(remaining)
    return ordered


def _detect_article_kind(content: str, document_type: str | None = None, *, title: str | None = None) -> str:
    title_type = None
    title_clean = (title or "").strip().lower()
    if title_clean:
        if re.search(r"\b(?:policy|policies|rules?|guidelines?|system|classification|offenses?|conduct|retention|grading)\b", title_clean):
            title_type = "policy"
        elif re.search(r"\b(?:requirements?|documents?|checklist|application)\b", title_clean):
            title_type = "requirement"
        elif re.search(r"\b(?:procedure|process|steps?|how to)\b", title_clean):
            title_type = "procedure"

    doc_type = (document_type or "").strip().lower()
    if title_type:
        return title_type
    if doc_type in {"requirement", "procedure", "policy"}:
        return doc_type
    if doc_type in {"handbook_policy"}:
        return "policy"
    if doc_type in {"information"}:
        return "information"

    lower = content.lower()
    if "policy" in lower and ("shall" in lower or "must" in lower or "students" in lower):
        return "policy"
    requirement_score = sum(1 for signal in _REQUIREMENT_SIGNALS if signal in lower)
    procedure_score = sum(1 for signal in _PROCEDURE_SIGNALS if signal in lower)
    if requirement_score >= 2 or ("form" in lower and "requirement" in lower):
        return "requirement"
    if procedure_score >= 1:
        return "procedure"
    return "information"


def _grounded_reference_text(
    *,
    title: str | None,
    content: str,
    source_sections: list[str] | None = None,
) -> str:
    parts = [title or "", content or ""]
    if source_sections:
        parts.extend(source_sections)
    return _normalize_compare_text(" ".join(parts))


def _term_in_grounded_text(term: str, grounded: str) -> bool:
    return term.lower() in grounded


def _summary_term_groups() -> dict[str, tuple[str, ...]]:
    return {
        "counseling": _COUNSELING_TERMS,
        "grading": ("grading", "grade point", "gpa", "retention", "delinquency"),
        "admission": ("admission", "enrollment", "entrant"),
        "graduation": ("graduation", "commencement", "clearance"),
        "scholarship": ("scholarship", "financial aid", "grant"),
    }


def summary_has_foreign_topic_terms(
    summary: str,
    *,
    title: str | None,
    content: str,
    source_sections: list[str] | None = None,
) -> bool:
    grounded = _grounded_reference_text(
        title=title,
        content=content,
        source_sections=source_sections,
    )
    summary_lower = _normalize_compare_text(summary)
    if not summary_lower:
        return False

    title_lower = _normalize_compare_text(title or "")
    for group, terms in _summary_term_groups().items():
        title_in_group = any(term in title_lower for term in terms)
        summary_mentions = [term for term in terms if term in summary_lower]
        if not summary_mentions:
            continue
        if title_in_group:
            continue
        if any(_term_in_grounded_text(term, grounded) for term in summary_mentions):
            continue
        return True
    return False


def is_generic_only_summary(summary: str, *, title: str | None = None) -> bool:
    normalized = _normalize_compare_text(summary)
    if not normalized:
        return True
    title_clean = _normalize_compare_text(title or "")
    if title_clean and title_clean in normalized and len(normalized.split()) <= 18:
        marker_hits = sum(1 for marker in _GENERIC_SUMMARY_MARKERS if marker in normalized)
        return marker_hits >= 1
    return False


def safe_article_summary_fallback(title: str | None, article_kind: str | None = None) -> str:
    title_clean = re.sub(r"\s+", " ", (title or "").strip()) or "this topic"
    kind = (article_kind or "information").strip().lower()
    if kind == "policy":
        return (
            f"This article explains the policy on {title_clean} "
            "and the conditions students should be aware of."
        )
    if kind == "requirement":
        return f"This article explains the requirements and related instructions for {title_clean}."
    if kind == "procedure":
        return f"This article explains the process for {title_clean} based on the uploaded source document."
    return f"This article provides information about {title_clean} based on the uploaded source document."


def _sentence_mentions_concepts(sentence: str, concepts: list[str]) -> int:
    lower = sentence.lower()
    return sum(1 for concept in concepts if concept.lower() in lower)


def _too_similar_to_opening(summary: str, content: str) -> bool:
    sentences = _split_sentences(content)
    if not sentences:
        return False
    opening = _normalize_compare_text(_strip_leading_numbered_clause(sentences[0]))
    norm_summary = _normalize_compare_text(summary)
    if not opening or not norm_summary:
        return False
    if opening in norm_summary or norm_summary in opening:
        return True
    opening_words = set(opening.split())
    summary_words = set(norm_summary.split())
    if not opening_words:
        return False
    overlap = len(opening_words & summary_words) / len(opening_words)
    return overlap >= 0.72


def _compose_comparison_note(content: str) -> str | None:
    lower = content.lower()
    has_virtual = "virtual" in lower and "counsel" in lower
    has_face = "face-to-face" in lower or "face to face" in lower
    has_similarity = any(
        phrase in lower
        for phrase in (
            "does not differ",
            "no different",
            "similar principles",
            "same principles",
            "same as",
            "similar to",
        )
    )
    if has_virtual and has_face and has_similarity:
        return (
            "It also notes that virtual counseling follows similar principles "
            "to face-to-face counseling."
        )
    return None


def _compose_referral_note(content: str) -> str | None:
    lower = content.lower()
    has_team = "multidisciplinary team" in lower or (
        "multidisciplinary" in lower and "team" in lower
    )
    has_referral = any(
        phrase in lower
        for phrase in ("refer", "referral", "referred", "refer if necessary")
    )
    if not (has_team and has_referral):
        return None

    if "specialist" in lower or "special needs" in lower:
        return (
            "It also notes that students may be referred to a multidisciplinary team "
            "of specialists when additional support is needed."
        )
    return (
        "It also notes that students may be referred to a multidisciplinary team "
        "when additional support is needed."
    )


def _pick_supplement_sentence(content: str, concepts: list[str], used_concepts: list[str]) -> str | None:
    comparison = _compose_comparison_note(content)
    if comparison:
        return comparison

    referral = _compose_referral_note(content)
    if referral:
        return referral

    sentences = _split_sentences(content)
    best: tuple[int, str] | None = None
    for sentence in sentences[1:]:
        cleaned = _polish_supplement_clause(_strip_leading_numbered_clause(sentence))
        if len(cleaned) < 35 or len(cleaned) > 220:
            continue
        if _NUMBERED_CLAUSE_PREFIX.search(cleaned):
            continue
        if _is_incomplete_supplement(cleaned):
            continue
        mention_count = _sentence_mentions_concepts(cleaned, concepts)
        if mention_count == 0:
            continue
        score = mention_count * 10 + min(len(cleaned), 160)
        if best is None or score > best[0]:
            best = (score, cleaned)

    if best:
        adapted = _trim_summary_length(best[1], max_chars=180).rstrip(".")
        wrapped = _wrap_supplement_clause(adapted)
        if wrapped:
            return wrapped

    remaining = [concept for concept in concepts if concept not in used_concepts]
    if remaining:
        return f"It also covers {_format_concept_list(remaining[:3])}."
    return None


def _is_composed_supplement(supplement: str) -> bool:
    lowered = supplement.lower()
    return (
        "students may be referred to a multidisciplinary team" in lowered
        or "virtual counseling follows similar principles" in lowered
    )


def _ensure_shorter_than_content(summary: str, content: str) -> str:
    if not summary or not content:
        return summary
    if len(summary) < len(content):
        return summary

    sentences = _split_sentences(summary)
    if len(sentences) >= 2:
        budget = max(80, len(content) - len(sentences[1]) - 6)
        trimmed_first = _trim_summary_length(sentences[0], max_chars=budget)
        if not trimmed_first.endswith((".", "!", "?")):
            clause_parts = trimmed_first.rsplit(", and ", 1)
            if len(clause_parts) == 2 and len(clause_parts[0]) >= 60:
                trimmed_first = f"{clause_parts[0]}."
            else:
                trimmed_first = trimmed_first.rstrip(",; ") + "."
        combined = f"{trimmed_first} {sentences[1]}".strip()
        if combined and len(combined) < len(content):
            return combined

    if sentences:
        one_sentence = _trim_summary_length(
            sentences[0],
            max_chars=max(80, len(content) - 5),
        )
        if one_sentence and len(one_sentence) < len(content):
            return one_sentence

    return _trim_summary_length(summary, max_chars=max(80, len(content) - 5))


def _build_student_friendly_summary(
    content: str,
    *,
    title: str | None = None,
    document_type: str | None = None,
) -> str:
    title_clean = re.sub(r"\s+", " ", (title or "").strip())
    kind = _detect_article_kind(content, document_type, title=title)
    concepts = _prioritize_concepts(_extract_key_concepts(content, title=title), kind)
    article_ref = f"The {title_clean} article" if title_clean else "This article"
    topic_phrase = _title_summary_phrase(title_clean, kind) if title_clean else "explains the main topic"

    composed_supplement = None
    if any(term in title_clean.lower() for term in _COUNSELING_TERMS) or any(
        term in content.lower() for term in _COUNSELING_TERMS
    ):
        composed_supplement = _compose_comparison_note(content) or _compose_referral_note(content)
    primary_concepts = concepts[:2 if composed_supplement else 4]
    used_concepts = list(primary_concepts)

    if kind == "requirement":
        if primary_concepts:
            first = (
                f"{article_ref} {topic_phrase} and "
                f"the key requirements involved, including {_format_concept_list(primary_concepts)}."
            )
        else:
            first = (
                f"{article_ref} {topic_phrase} and "
                "the information students need to provide."
            )
    elif kind == "procedure":
        if primary_concepts:
            first = (
                f"{article_ref} {topic_phrase}, including "
                f"{_format_concept_list(primary_concepts)}."
            )
        else:
            first = (
                f"{article_ref} explains the main steps students should follow "
                "based on the source document."
            )
    elif primary_concepts:
        first = (
            f"{article_ref} {topic_phrase} and what students can learn about "
            f"{_format_concept_list(primary_concepts[:3])}."
        )
    elif title_clean:
        if kind == "requirement":
            first = (
                f"This article explains the requirements and related instructions for {title_clean}."
            )
        elif kind == "procedure":
            first = (
                f"This article explains the requirements and related instructions for {title_clean}."
            )
        elif kind == "policy":
            first = (
                f"This article explains the policy on {title_clean} "
                "and the conditions students should be aware of."
            )
        else:
            first = (
                f"This article provides information about {title_clean} "
                "based on the uploaded source document."
            )
    else:
        first = "This article provides information based on the uploaded source document."

    sentences = [_simplify_awkward_phrases(first)]
    supplement = _pick_supplement_sentence(content, concepts, used_concepts)
    if supplement and len(sentences) < _SUMMARY_MAX_SENTENCES and (
        _is_composed_supplement(supplement)
        or len(sentences[0]) + len(supplement) + 1 < len(content)
    ):
        sentences.append(_simplify_awkward_phrases(supplement))

    summary = " ".join(sentences[:_SUMMARY_MAX_SENTENCES]).strip()
    summary = _trim_summary_length(summary)
    if _too_similar_to_opening(summary, content):
        if kind == "procedure" and primary_concepts:
            summary = _trim_summary_length(
                f"{article_ref} {topic_phrase}, including "
                f"{_format_concept_list(primary_concepts)}."
            )
        elif title_clean:
            summary = _trim_summary_length(
                f"This article provides information about {title_clean} "
                "based on the uploaded source document."
            )
    return _ensure_shorter_than_content(summary, content)


def _extractive_summary(content: str) -> str:
    sentences = _split_sentences(content)
    picked: list[str] = []
    for sentence in sentences:
        candidate = _strip_leading_numbered_clause(sentence)
        if not candidate:
            continue
        if len(candidate) < 12 and not picked:
            continue
        picked.append(candidate)
        if len(picked) >= _SUMMARY_MAX_SENTENCES:
            break

    if not picked:
        first_line = content.split("\n", 1)[0].strip() if content else ""
        first_line = _strip_leading_numbered_clause(first_line)
        if first_line:
            picked = [first_line]

    summary = " ".join(picked[:_SUMMARY_MAX_SENTENCES]).strip()
    return _ensure_shorter_than_content(_trim_summary_length(summary), content)


def build_article_summary(
    content: str,
    existing_summary: str | None = None,
    *,
    title: str | None = None,
    document_type: str | None = None,
    consolidated_parent: bool = False,
    source_sections: list[str] | None = None,
    article_type: str | None = None,
) -> str:
    """Build a short, student-friendly, source-grounded summary from article content."""
    cleaned_content = clean_article_content_for_display((content or "").strip())
    existing = (existing_summary or "").strip()
    kind = article_type or _detect_article_kind(
        cleaned_content,
        document_type,
        title=title,
    )

    if consolidated_parent and title and title.strip():
        overview = (
            f"This article provides an overview of {title.strip()} "
            "based on the uploaded source document."
        )
        if not cleaned_content:
            return overview
        if len(cleaned_content) > 400:
            return overview

    if not cleaned_content and not existing:
        return safe_article_summary_fallback(title, kind)

    if existing and cleaned_content and not _summaries_overlap(existing, cleaned_content):
        sentences = _split_sentences(existing)
        if len(sentences) > _SUMMARY_MAX_SENTENCES:
            existing = " ".join(sentences[:_SUMMARY_MAX_SENTENCES])
        existing = _strip_leading_numbered_clause(existing)
        if existing:
            return _trim_summary_length(existing)

    if cleaned_content:
        summary = _build_student_friendly_summary(
            cleaned_content,
            title=title,
            document_type=document_type or article_type,
        )
        if not summary or _summaries_overlap(summary, cleaned_content):
            summary = _extractive_summary(cleaned_content)
    else:
        sentences = _split_sentences(existing)
        summary = _trim_summary_length(
            _strip_leading_numbered_clause(" ".join(sentences[:_SUMMARY_MAX_SENTENCES]).strip())
        )

    if cleaned_content and _normalize_compare_text(summary) == _normalize_compare_text(cleaned_content):
        summary = _build_student_friendly_summary(
            cleaned_content,
            title=title,
            document_type=document_type or article_type,
        ) or _extractive_summary(cleaned_content)

    if cleaned_content and _too_similar_to_opening(summary, cleaned_content):
        rebuilt = _build_student_friendly_summary(
            cleaned_content,
            title=title,
            document_type=document_type or article_type,
        )
        if rebuilt:
            summary = rebuilt

    if summary_has_foreign_topic_terms(
        summary,
        title=title,
        content=cleaned_content,
        source_sections=source_sections,
    ) or is_generic_only_summary(summary, title=title):
        summary = safe_article_summary_fallback(title, kind)

    return _ensure_shorter_than_content(summary, cleaned_content)

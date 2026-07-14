"""Format extracted article text into structured student-friendly display content."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.article_text import clean_article_content_for_display

_METADATA_MARKER = "----EXTRACTED METADATA----"

_NUMBERED_CLAUSE_INLINE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)*)\.\s+(?=[A-Za-z\"'(])",
)

_PREPOSITION_START = frozenset({
    "of",
    "for",
    "to",
    "from",
    "with",
    "in",
    "on",
    "at",
    "by",
    "as",
    "and",
    "or",
})

_NUMBERED_LINE = re.compile(
    r"^\s*(\d+(?:\.\d+)*)\.?\s+(.+)$",
)

_LETTERED_ROLE_LINE = re.compile(
    r"^\s*([A-Z])\.\s+(.+?)(?:\s*[–—\-:]\s*(.+))?$",
)

_BULLET_LINE = re.compile(
    r"^\s*(?:[-*•]|\u2022)\s+(.+)$",
)

_ACTION_VERBS = frozenset({
    "submit",
    "proceed",
    "fill",
    "request",
    "present",
    "pay",
    "claim",
    "receive",
    "wait",
    "encode",
    "validate",
    "issue",
    "approve",
    "accomplish",
    "upload",
    "download",
    "contact",
    "schedule",
    "secure",
    "provide",
    "sign",
    "attach",
    "obtain",
    "consult",
    "refer",
    "update",
    "follow",
    "attend",
    "complete",
    "apply",
    "register",
    "enroll",
})

_FRAGMENT_LABELS = frozenset({
    "not",
    "students",
    "student",
    "if",
    "below",
    "shall",
    "may",
    "provided",
    "wherein",
    "or",
    "said",
    "must",
    "can",
    "with",
    "without",
    "in",
    "on",
    "the",
    "a",
    "an",
    "and",
    "or submitted",
    "capable",
})

_ELIGIBILITY_SIGNALS = (
    "eligible",
    "eligibility",
    "allowed",
    "may attend",
    "may join",
    "limited to",
    "only students",
    "students who",
    "students doing",
    "students living",
    "students taking",
    "cannot do",
    "condition",
    "conditions",
    "restriction",
    "restrictions",
    "exception",
    "exceptions",
    "limitation",
    "limitations",
    "permitted",
    "who may",
    "who can",
    "qualifies",
    "qualify",
    "face-to-face",
    "face to face",
)

_ELIGIBILITY_TITLE_SIGNALS = (
    "eligib",
    "condition",
    "conditions",
    "limited",
    "face-to-face",
    "face to face",
    "who may",
    "who can",
    "allowed",
    "permitted",
    "restriction",
)

_REQUIREMENT_NOUN_PHRASE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9\s/'-]{1,50}?\s+requirements?)\b",
    re.IGNORECASE,
)

_REQUIREMENT_SIGNALS = (
    "requirement",
    "requirements",
    "must have",
    "must be",
    "must submit",
    "shall submit",
    "required",
    "clearance",
    "documents",
    "validation",
)

_POLICY_SIGNALS = (
    "shall",
    "policy",
    "policies",
    "must not",
    "prohibited",
    "observed",
    "pursuant",
)

_ROLE_SIGNALS = (
    "responsibilities",
    "responsibility",
    "campus directors",
    "administrators",
    "academic heads",
    "chairpersons",
    "workgroup",
    "committee",
    "team",
)

_IMPORTANT_NOTE_SIGNALS = (
    "code of ethics",
    "important",
    "note that",
    "reminder",
    "considered in",
    "same grounds",
    "highly considered",
)

_INTERNAL_ROLE_SIGNALS = (
    "workgroup",
    "committee",
    "task force",
    "administrators",
    "campus directors",
    "academic heads",
    "chairpersons",
    "coordination",
    "implementation",
    "health risk",
    "crisis",
    "responsibilities",
)

_TITLE_TYPE_SUFFIXES = (
    ("requirements", "requirement"),
    ("requirement", "requirement"),
    ("procedures", "procedure"),
    ("procedure", "procedure"),
    ("processes", "process"),
    ("process", "process"),
    ("policies", "policy"),
    ("policy", "policy"),
    ("guidelines", "guideline"),
    ("guideline", "guideline"),
    ("services", "service"),
    ("service", "service"),
)

_INLINE_LETTERED_ROLE = re.compile(
    r"(?:(?<=^)|(?<=[\s.]))([A-Z])\.\s+"
    r"([^–—\-:]{3,120}?)\s*[–—\-:]\s*",
)

_SECTION_HEADERS = frozenset({
    "overview",
    "process",
    "process / steps",
    "important notes",
    "requirements",
    "instructions / how to submit",
    "instructions",
    "how to submit",
    "notes",
    "key points",
    "important reminders",
    "eligibility / conditions",
    "roles and responsibilities",
    "purpose",
    "when to use",
    "how to fill out",
    "related service / office",
    "source",
})


@dataclass
class FormattedArticleContent:
    display_content: str
    official_source_excerpt: str
    sections: list[dict[str, str]] = field(default_factory=list)
    formatting_notes: list[str] = field(default_factory=list)
    content_pattern: str = "overview_only"


def strip_embedded_article_metadata(content: str | None) -> str:
    """Return student-facing article body without embedded metadata block."""
    text = str(content or "")
    if _METADATA_MARKER in text:
        text = text.split(_METADATA_MARKER, 1)[0]
    return clean_article_content_for_display(text.strip())


def extract_embedded_article_metadata(content: str | None) -> dict[str, Any]:
    """Parse the JSON metadata block appended to saved article content."""
    text = str(content or "")
    if _METADATA_MARKER not in text:
        return {}
    meta_text = text.split(_METADATA_MARKER, 1)[1].strip()
    if not meta_text:
        return {}
    try:
        import json

        decoded = json.loads(meta_text)
        if isinstance(decoded, dict):
            return decoded
    except Exception:
        return {}
    return {}


def merge_article_content_update(
    existing_content: str | None,
    updated_body: str | None,
) -> str:
    """Preserve embedded metadata (including official_source_excerpt) when admins edit body text."""
    body = clean_article_content_for_display(updated_body or "")
    metadata = extract_embedded_article_metadata(existing_content)
    if not metadata:
        return body
    import json

    meta_block = f"\n\n{_METADATA_MARKER}\n" + json.dumps(metadata, ensure_ascii=False, indent=2)
    return f"{body}{meta_block}"


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", normalized)
    return [part.strip() for part in parts if part.strip()]


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _normalize_key(value: str | None) -> str:
    return _normalize_text(value).lower()


def _normalize_article_type(article_type: str | None, metadata: dict[str, Any] | None = None) -> str:
    value = str(article_type or "").strip().lower()
    if not value and metadata:
        value = str(metadata.get("document_type") or metadata.get("article_type") or "").strip().lower()
    if value in {"how_to"}:
        return "procedure"
    if value in {"handbook_policy"}:
        return "policy"
    return value or "information"


def _is_fragment_label(label: str | None) -> bool:
    cleaned = _normalize_key(label).rstrip(".,;:")
    if not cleaned:
        return True
    if cleaned in _FRAGMENT_LABELS:
        return True
    if len(cleaned.split()) == 1 and len(cleaned) <= 3:
        return True
    if cleaned.startswith("or ") and len(cleaned.split()) <= 3:
        return True
    return False


def _item_full_text(number: str, label: str, body: str) -> str:
    parts = [part for part in (label, body) if part]
    if not parts:
        return ""
    return _normalize_text(" ".join(parts))


def _split_label_body(chunk: str) -> tuple[str, str]:
    cleaned = _normalize_text(chunk)
    if not cleaned:
        return "", ""
    dash = re.match(r"^([^–—:]{1,80}?)\s*[–—:]\s*(.+)$", cleaned)
    if dash:
        label = dash.group(1).strip()
        body = dash.group(2).strip()
        if _is_fragment_label(label):
            return "", cleaned
        return label, body

    words = cleaned.split(None, 1)
    if len(words) == 2 and len(words[0]) <= 40 and words[0][:1].isupper():
        label = words[0].rstrip(".")
        body = words[1].strip()
        if _is_fragment_label(label):
            return "", cleaned
        first_body_word = body.split(None, 1)[0] if body else ""
        if first_body_word.lower().rstrip(".,;:") in _PREPOSITION_START:
            return "", cleaned
        if first_body_word[:1].islower() and len(body.split()) == 1:
            combined = f"{label} {body}".strip()
            if _is_fragment_label(combined):
                return "", cleaned
            return combined, ""
        # Named process/requirement labels (Conference, Follow-up, Referral).
        if not _is_fragment_label(label) and len(label.split()) <= 3 and len(label) <= 40:
            if body[:1].islower():
                return label, body
            # Allow Title-Case sentence starts after a short noun label.
            if len(body.split()) >= 4:
                return label, body
        return "", cleaned
    return "", cleaned


def _split_inline_numbered_clauses(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    matches = list(_NUMBERED_CLAUSE_INLINE.finditer(text))
    if len(matches) < 2:
        return text.strip(), []

    # Prefer hierarchical clauses (3.1, 2.2) when mixed with simple numbers.
    hierarchical = [match for match in matches if "." in match.group(1)]
    if len(hierarchical) >= 2:
        matches = hierarchical
    else:
        # Keep simple 1. 2. 3. lists only when enough candidates exist.
        simple = [match for match in matches if "." not in match.group(1)]
        if len(simple) < 2:
            return text.strip(), []
        matches = simple

    preamble = text[: matches[0].start()].strip()
    preamble = re.sub(r"[:\s]+$", "", preamble)
    items: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        number = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label, body = _split_label_body(text[start:end].strip())
        items.append((number, label, body))
    return preamble, items


def _split_line_numbered_items(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return "", []

    preamble_lines: list[str] = []
    trailing_lines: list[str] = []
    items: list[tuple[str, str, str]] = []
    current_number = ""
    current_label = ""
    current_body: list[str] = []
    in_list = False

    def flush_item() -> None:
        nonlocal current_number, current_label, current_body
        if current_number:
            items.append(
                (
                    current_number,
                    current_label,
                    " ".join(current_body).strip(),
                )
            )
        current_number = ""
        current_label = ""
        current_body = []

    for line in lines:
        match = _NUMBERED_LINE.match(line)
        if match:
            flush_item()
            in_list = True
            current_number = match.group(1)
            label, body = _split_label_body(match.group(2))
            current_label = label
            if body:
                current_body.append(body)
            elif not label:
                current_body.append(match.group(2).strip())
            continue
        if current_number:
            # Continue current item only for clearly wrapped lines.
            if line[:1].islower() or line.startswith(("(", "[", "-", "–", "—")):
                current_body.append(line)
            elif not current_body and not current_label:
                current_body.append(line)
            else:
                flush_item()
                trailing_lines.append(line)
            continue
        if in_list:
            trailing_lines.append(line)
        else:
            preamble_lines.append(line)

    flush_item()
    if len(items) < 2:
        return text.strip(), []
    preamble = "\n".join(preamble_lines + trailing_lines).strip()
    return preamble, items


def _extract_numbered_items(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    line_preamble, line_items = _split_line_numbered_items(text)
    if line_items:
        return line_preamble, line_items
    return _split_inline_numbered_clauses(text)


def _extract_bullet_items(text: str) -> tuple[str, list[str]]:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return "", []

    preamble_lines: list[str] = []
    bullets: list[str] = []
    for line in lines:
        match = _BULLET_LINE.match(line)
        if match:
            bullets.append(match.group(1).strip())
        elif not bullets:
            preamble_lines.append(line)
        else:
            bullets[-1] = f"{bullets[-1]} {line}".strip()
    if len(bullets) < 2:
        return text.strip(), []
    return "\n".join(preamble_lines).strip(), bullets


def _extract_role_items(text: str) -> list[tuple[str, list[str]]]:
    line_roles = _extract_line_role_items(text)
    if len(line_roles) >= 2:
        return line_roles
    return _extract_inline_role_items(text)


def _extract_line_role_items(text: str) -> list[tuple[str, list[str]]]:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    roles: list[tuple[str, list[str]]] = []
    current_role = ""
    current_items: list[str] = []

    def flush() -> None:
        nonlocal current_role, current_items
        if current_role:
            roles.append((current_role, list(current_items)))
        current_role = ""
        current_items = []

    for line in lines:
        lettered = _LETTERED_ROLE_LINE.match(line)
        if lettered:
            flush()
            role = (lettered.group(2) or "").strip()
            detail = (lettered.group(3) or "").strip()
            current_role = role
            if detail:
                current_items.extend(_split_responsibility_parts(detail))
            continue
        dash = re.match(r"^([^–—\-]{3,90}?)\s*[–—\-]\s*(.+)$", line)
        if dash and any(
            signal in dash.group(1).lower()
            for signal in ("director", "head", "chair", "admin", "officer", "dean", "registrar", "counselor")
        ):
            flush()
            current_role = dash.group(1).strip()
            current_items.extend(_split_responsibility_parts(dash.group(2).strip()))
            continue
        bullet = _BULLET_LINE.match(line)
        if current_role and bullet:
            current_items.extend(_split_responsibility_parts(bullet.group(1).strip()))
            continue
        if current_role and line:
            current_items.extend(_split_responsibility_parts(line))
    flush()
    if len(roles) < 2:
        return []
    return roles


def _split_responsibility_parts(text: str) -> list[str]:
    cleaned = _normalize_text(text).strip(" .;")
    if not cleaned:
        return []
    parts = re.split(r"\s*[–—\-]\s*", cleaned)
    expanded: list[str] = []
    for part in parts:
        part = part.strip(" .;")
        if not part:
            continue
        if ". " in part and len(part) > 80:
            expanded.extend(sentence.strip(" .;") for sentence in _split_sentences(part) if sentence.strip())
        else:
            expanded.append(part)
    return [item for item in expanded if item]


def _extract_inline_role_items(text: str) -> list[tuple[str, list[str]]]:
    normalized = _normalize_text(text)
    matches = list(_INLINE_LETTERED_ROLE.finditer(normalized))
    if len(matches) < 2:
        return []

    roles: list[tuple[str, list[str]]] = []
    for index, match in enumerate(matches):
        role = _normalize_text(match.group(2))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        body = normalized[start:end].strip(" .;")
        # Stop before the next lettered marker residue.
        body = re.sub(r"\s+[A-Z]\.\s*$", "", body).strip(" .;")
        responsibilities = _split_responsibility_parts(body)
        if role:
            roles.append((role, responsibilities or ([body] if body else [])))
    return roles if len(roles) >= 2 else []


def _looks_internal_role_article(title: str, source: str, roles: list[tuple[str, list[str]]]) -> bool:
    if not roles:
        return False
    haystack = f"{title} {source}".lower()
    student_facing = any(
        token in haystack
        for token in ("students may", "student may", "how to request", "how to apply", "students can request")
    )
    internal_hits = sum(1 for signal in _INTERNAL_ROLE_SIGNALS if signal in haystack)
    if student_facing and internal_hits == 0:
        return False
    return internal_hits >= 1 or len(roles) >= 2


def _contains_action_verb(text: str) -> bool:
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    return any(token in _ACTION_VERBS for token in tokens)


def _looks_like_named_process_step(label: str, body: str) -> bool:
    if not label or _is_fragment_label(label):
        return False
    words = label.split()
    if len(words) > 4:
        return False
    if label[:1].isupper() and (body or _contains_action_verb(f"{label} {body}")):
        return True
    return False


def _classify_numbered_list(
    items: list[tuple[str, str, str]],
    *,
    title: str,
    article_type: str,
    source: str,
) -> str:
    if not items:
        return "notes"

    full_texts = [_item_full_text(number, label, body) for number, label, body in items]
    fragment_count = sum(1 for number, label, body in items if _is_fragment_label(label) and len(_item_full_text(number, label, body).split()) <= 4)
    if fragment_count >= max(2, len(items) // 2):
        return "messy_fragments"

    action_count = 0
    named_step_count = 0
    eligibility_count = 0
    requirement_count = 0
    policy_count = 0

    for number, label, body in items:
        text = _item_full_text(number, label, body)
        lower = text.lower()
        if _looks_like_named_process_step(label, body) or _contains_action_verb(text):
            action_count += 1
        if _looks_like_named_process_step(label, body):
            named_step_count += 1
        if any(signal in lower for signal in _ELIGIBILITY_SIGNALS):
            eligibility_count += 1
        if any(signal in lower for signal in _REQUIREMENT_SIGNALS):
            requirement_count += 1
        if any(signal in lower for signal in _POLICY_SIGNALS):
            policy_count += 1

    title_lower = title.lower()
    source_lower = source.lower()
    total = max(len(items), 1)

    # Title/type signals outrank named-step heuristics.
    if any(token in title_lower for token in ("requirement", "requirements", "validation")):
        return "requirements"
    if article_type == "requirement":
        return "requirements"
    if any(token in title_lower for token in _ELIGIBILITY_TITLE_SIGNALS) or eligibility_count / total >= 0.4:
        return "eligibility_conditions"
    if named_step_count >= 2 and named_step_count / total >= 0.5:
        return "true_procedure_steps"
    if action_count / total >= 0.6 and article_type == "procedure":
        return "true_procedure_steps"
    if requirement_count / total >= 0.5:
        return "requirements"
    if "policy" in title_lower or policy_count / total >= 0.5:
        return "policy_clauses"
    if any(signal in source_lower for signal in _ELIGIBILITY_SIGNALS) and action_count / total < 0.4:
        return "eligibility_conditions"
    if article_type == "procedure" and action_count / total < 0.4:
        return "key_points"
    return "key_points"


def _detect_content_pattern(
    title: str,
    article_type: str,
    source: str,
    items: list[tuple[str, str, str]],
    roles: list[tuple[str, list[str]]],
    clause_class: str,
) -> str:
    title_lower = title.lower().strip()
    source_lower = source.lower()

    if roles:
        return "role_responsibility_list"
    if clause_class == "messy_fragments":
        return "messy_fragments"
    if re.match(r"^\d+(?:\.\d+)*\.?$", title_lower):
        return "messy_ocr"
    if len(title_lower.split()) <= 2 and title_lower in _FRAGMENT_LABELS:
        return "messy_ocr"
    if title_lower.startswith("or ") or title_lower.startswith("capable of"):
        return "messy_ocr"
    if clause_class == "true_procedure_steps":
        return "procedure_steps"
    if clause_class == "requirements":
        if any(signal in source_lower for signal in _POLICY_SIGNALS) and "requirement" not in title_lower:
            return "mixed_policy_requirement"
        return "requirement_list"
    if clause_class == "eligibility_conditions":
        return "eligibility_conditions"
    if clause_class == "policy_clauses":
        return "policy_clauses"
    if items:
        return "key_points"
    if any(signal in source_lower for signal in _ROLE_SIGNALS) and "responsib" in source_lower:
        return "role_responsibility_list"
    return "overview_only"


def _split_title_concept(title: str) -> tuple[str, str | None, str]:
    """Return (topic_phrase, type_kind, full_lower_title) using generic suffix rules."""
    clean = _normalize_text(title)
    lower = clean.lower()
    for suffix, kind in _TITLE_TYPE_SUFFIXES:
        if lower == suffix:
            return suffix, kind, lower
        if lower.endswith(f" {suffix}"):
            topic = clean[: -len(suffix)].strip(" -–—:")
            return topic, kind, lower
    return clean, None, lower


def build_clean_overview(
    title: str,
    article_type: str,
    detected_pattern: str,
) -> str:
    """Build a short overview that avoids awkward repeated title/type phrasing."""
    topic, kind, lower = _split_title_concept(title)
    topic_phrase = _normalize_text(topic).lower() if topic else ""
    article_type = (article_type or "").strip().lower()
    pattern = (detected_pattern or "").strip().lower()

    if pattern == "eligibility_conditions" or any(token in lower for token in _ELIGIBILITY_TITLE_SIGNALS):
        focus = topic_phrase or lower
        focus = re.sub(
            r"^(operationalizing|implementing|guidelines?\s+(?:on|for)|policy\s+on)\s+",
            "",
            focus,
            flags=re.IGNORECASE,
        ).strip() or focus
        return f"This article explains the conditions for {focus}."

    if (
        pattern in {"requirement_list", "mixed_policy_requirement"}
        or article_type == "requirement"
        or kind == "requirement"
        or "requirement" in lower
    ):
        if topic_phrase and any(token in topic_phrase for token in ("examination", "exam", "test", "assessment")):
            return f"This article explains the requirements for taking the {topic_phrase}."
        if topic_phrase and kind == "requirement":
            return (
                f"This article explains the {topic_phrase} requirements "
                "and related conditions for students."
            )
        if topic_phrase:
            return (
                f"This article explains the requirements related to {topic_phrase} "
                "based on the uploaded source document."
            )
        return "This article explains the requirements based on the uploaded source document."

    if (
        pattern == "procedure_steps"
        or article_type == "procedure"
        or kind in {"process", "procedure"}
        or lower.endswith("process")
        or lower.endswith("procedure")
    ):
        if topic_phrase and kind in {"process", "procedure"}:
            return f"This article explains the {topic_phrase} process and related support actions."
        focus = topic_phrase or lower
        return f"This article explains the {focus} and related support actions."

    if pattern == "role_responsibility_list":
        focus = _normalize_text(title) or "this topic"
        return f"This article provides information about {focus} and its responsibilities."

    if article_type == "policy" or kind == "policy" or "policy" in lower:
        if topic_phrase and kind == "policy":
            return (
                f"This article explains the {topic_phrase} policy "
                "and the conditions students should be aware of."
            )
        focus = topic_phrase or lower
        return f"This article explains the policy on {focus} and the conditions students should be aware of."

    if article_type == "form":
        focus = topic_phrase or lower
        return f"This article explains how to complete {focus}."

    focus = _normalize_text(title) or "this topic"
    return f"This article provides information about {focus} based on the uploaded source document."


def _generated_overview(title: str, article_type: str, content_pattern: str) -> str:
    return build_clean_overview(title, article_type, content_pattern)


def _texts_overlap(left: str, right: str, *, threshold: float = 0.72) -> bool:
    a = _normalize_key(left)
    b = _normalize_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        shorter = a if len(a) <= len(b) else b
        # A substantial clause contained in another section is a duplicate.
        if len(shorter) >= 40 or len(shorter.split()) >= 8:
            return True
        longer = b if shorter is a else a
        if len(shorter) / max(len(longer), 1) >= threshold:
            return True
    a_words = set(a.split())
    b_words = set(b.split())
    if not a_words or not b_words:
        return False
    overlap = len(a_words & b_words) / max(len(a_words), len(b_words))
    return overlap >= threshold


def _is_duplicate_section_text(text: str, excluded: list[str], item_texts: list[str] | None = None) -> bool:
    candidate = _normalize_text(text)
    if not candidate:
        return True
    for other in excluded:
        if other and _texts_overlap(candidate, other, threshold=0.55):
            return True
    for item in item_texts or []:
        if item and _texts_overlap(candidate, item, threshold=0.55):
            return True
    return False


def _dedupe_text_against(text: str, excluded: list[str]) -> str:
    kept: list[str] = []
    for sentence in _split_sentences(text):
        if any(_texts_overlap(sentence, other) for other in excluded if other):
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


def _collect_important_notes(text: str, *, exclude: list[str] | None = None) -> str:
    excluded = list(exclude or [])
    picked: list[str] = []
    for sentence in _split_sentences(text):
        normalized = _normalize_text(sentence)
        lower = normalized.lower()
        if any(_texts_overlap(normalized, other) for other in excluded if other):
            continue
        if any(signal in lower for signal in _IMPORTANT_NOTE_SIGNALS):
            picked.append(normalized)
    return " ".join(picked).strip()


def _render_clause_items(
    heading: str,
    items: list[tuple[str, str, str]],
    *,
    style: str,
) -> tuple[str, dict[str, str]]:
    """Render numbered clauses without inventing Step titles."""
    lines = [heading]
    body_lines: list[str] = []

    for index, (number, label, body) in enumerate(items, start=1):
        full = _item_full_text(number, label, body)
        if not full:
            continue

        if style == "process":
            # Only use short noun labels for true process steps.
            if label and not _is_fragment_label(label) and len(label.split()) <= 4:
                lines.append(f"{index}. {label}")
                body_lines.append(f"{index}. {label}")
                if body:
                    lines.append(body)
                    body_lines.append(body)
            else:
                lines.append(f"{index}. {full}")
                body_lines.append(f"{index}. {full}")
        elif style == "requirements":
            # Preserve original numbering when hierarchical (2.1, 2.2).
            # Prefer compact requirement labels when the clause is clearly "X requirement ...".
            display_number = number if "." in number else str(index)
            display_text = full
            phrase_match = _REQUIREMENT_NOUN_PHRASE.search(full)
            if phrase_match:
                phrase = _normalize_text(phrase_match.group(1))
                if (
                    len(phrase.split()) <= 6
                    and _normalize_key(full).startswith(_normalize_key(phrase)[:24])
                ):
                    display_text = phrase
            elif "attendance" in full.lower() and ("ceremony" in full.lower() or "commencement" in full.lower()):
                display_text = "Graduation ceremony attendance"
            lines.append(f"{display_number}. {display_text}")
            body_lines.append(f"{display_number}. {display_text}")
        else:
            display_number = number if "." in number else str(index)
            lines.append(f"{display_number}. {full}")
            body_lines.append(f"{display_number}. {full}")
        lines.append("")

    return "\n".join(lines).strip(), {
        "heading": heading,
        "body": "\n".join(body_lines).strip(),
    }


def _render_bullet_section(heading: str, bullets: list[str]) -> tuple[str, dict[str, str]]:
    lines = [heading, *[f"- {item}" for item in bullets]]
    return "\n".join(lines).strip(), {
        "heading": heading,
        "body": "\n".join(f"- {item}" for item in bullets).strip(),
    }


def _render_roles_section(roles: list[tuple[str, list[str]]]) -> tuple[str, dict[str, str]]:
    lines = ["Roles and Responsibilities"]
    body_lines: list[str] = []
    for index, (role, responsibilities) in enumerate(roles, start=1):
        lines.append(f"{index}. {role}")
        body_lines.append(f"{index}. {role}")
        for item in responsibilities:
            cleaned = _normalize_text(item)
            if not cleaned:
                continue
            lines.append(f"- {cleaned}")
            body_lines.append(f"- {cleaned}")
        lines.append("")
    return "\n".join(lines).strip(), {
        "heading": "Roles and Responsibilities",
        "body": "\n".join(body_lines).strip(),
    }


def _build_sections(
    *,
    overview: str,
    detail_heading: str | None,
    detail_block: str | None,
    detail_section: dict[str, str] | None,
    instructions: str = "",
    notes: str = "",
    notes_heading: str = "Important Notes",
    item_texts: list[str] | None = None,
) -> FormattedArticleContent:
    lines = ["Overview", overview, ""]
    sections: list[dict[str, str]] = [{"heading": "Overview", "body": overview}]
    excluded = [overview]
    detail_items = list(item_texts or [])

    if detail_heading and detail_block and detail_section:
        lines.extend([detail_block, ""])
        sections.append(detail_section)
        excluded.append(detail_section.get("body", ""))

    if instructions and not _is_duplicate_section_text(instructions, excluded, detail_items):
        cleaned_instructions = _dedupe_text_against(instructions, excluded + detail_items)
        if cleaned_instructions and not _is_duplicate_section_text(
            cleaned_instructions, excluded, detail_items
        ):
            lines.extend(["Instructions / How to Submit", cleaned_instructions, ""])
            sections.append({"heading": "Instructions / How to Submit", "body": cleaned_instructions})
            excluded.append(cleaned_instructions)

    if notes:
        cleaned_notes = _dedupe_text_against(notes, excluded + detail_items)
        if cleaned_notes and not _is_duplicate_section_text(cleaned_notes, excluded, detail_items):
            lines.extend([notes_heading, cleaned_notes])
            sections.append({"heading": notes_heading, "body": cleaned_notes})

    return FormattedArticleContent(
        display_content="\n".join(lines).strip(),
        official_source_excerpt="",
        sections=sections,
        formatting_notes=[],
    )


def _extract_requirement_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for match in _REQUIREMENT_NOUN_PHRASE.finditer(text or ""):
        phrase = _normalize_text(match.group(1))
        key = phrase.lower()
        if len(phrase.split()) < 2 or key in seen:
            continue
        if key in {"the requirements", "following requirements", "these requirements"}:
            continue
        seen.add(key)
        phrases.append(phrase)
    # Ceremony/attendance style clauses without the word "requirement".
    for sentence in _split_sentences(text):
        lower = sentence.lower()
        if "attendance" in lower and ("ceremony" in lower or "commencement" in lower):
            phrase = "Graduation ceremony attendance"
            if phrase.lower() not in seen:
                seen.add(phrase.lower())
                phrases.append(phrase)
    return phrases


def _structured_fallback_from_sentences(
    title: str,
    article_type: str,
    source: str,
    content_pattern: str,
) -> FormattedArticleContent | None:
    overview = _generated_overview(title, article_type, content_pattern)
    requirement_phrases = _extract_requirement_phrases(source)
    if (
        article_type == "requirement"
        or content_pattern in {"requirement_list", "mixed_policy_requirement"}
        or "requirement" in title.lower()
    ) and len(requirement_phrases) >= 2:
        block, section = _render_bullet_section("Requirements", requirement_phrases)
        notes = _collect_important_notes(source, exclude=[overview, section["body"]])
        result = _build_sections(
            overview=overview,
            detail_heading="Requirements",
            detail_block=block,
            detail_section=section,
            notes=notes,
            item_texts=requirement_phrases,
        )
        result.official_source_excerpt = source
        result.formatting_notes = ["requirement_phrases", content_pattern]
        result.content_pattern = "requirement_list"
        return result

    sentences = _split_sentences(source)
    if len(sentences) < 2:
        return None

    heading = "Key Points"
    if content_pattern == "eligibility_conditions" or any(
        token in title.lower() for token in _ELIGIBILITY_TITLE_SIGNALS
    ):
        heading = "Eligibility / Conditions"
        content_pattern = "eligibility_conditions"
        overview = _generated_overview(title, article_type, content_pattern)
    elif article_type == "requirement" or "requirement" in title.lower():
        heading = "Requirements"
        content_pattern = "requirement_list"

    # Keep overview short; put remaining sentences under the detail heading.
    bullets = [sentence for sentence in sentences if not _texts_overlap(sentence, overview, threshold=0.8)]
    if len(bullets) < 2:
        return None
    block, section = _render_bullet_section(heading, bullets[:8])
    notes = _collect_important_notes(source, exclude=[overview, section["body"]])
    result = _build_sections(
        overview=overview,
        detail_heading=heading,
        detail_block=block,
        detail_section=section,
        notes=notes,
        item_texts=bullets[:8],
        notes_heading="Important Notes" if heading != "Key Points" else "Important Reminders",
    )
    result.official_source_excerpt = source
    result.formatting_notes = ["sentence_sections", content_pattern]
    result.content_pattern = content_pattern
    return result


def _paragraph_only(title: str, source: str, article_type: str, content_pattern: str) -> FormattedArticleContent:
    structured = _structured_fallback_from_sentences(title, article_type, source, content_pattern)
    if structured is not None:
        structured.formatting_notes = list(structured.formatting_notes) + ["paragraph_structured"]
        return structured

    overview = _generated_overview(title, article_type, content_pattern)
    # Never dump unlabeled source under Overview; keep a labeled Details section.
    return FormattedArticleContent(
        display_content=f"Overview\n{overview}\n\nDetails\n{source}".strip(),
        official_source_excerpt=source,
        sections=[
            {"heading": "Overview", "body": overview},
            {"heading": "Details", "body": source},
        ],
        formatting_notes=["paragraph_only"],
        content_pattern=content_pattern,
    )


def _peel_trailing_notes_from_items(
    items: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], str]:
    if not items:
        return items, ""
    number, label, body = items[-1]
    sentences = _split_sentences(body)
    if len(sentences) < 2:
        return items, ""

    kept: list[str] = []
    notes: list[str] = []
    for sentence in sentences:
        lower = sentence.lower()
        if kept and any(signal in lower for signal in _IMPORTANT_NOTE_SIGNALS):
            notes.append(sentence)
        else:
            kept.append(sentence)
    if not notes:
        return items, ""
    updated = list(items)
    updated[-1] = (number, label, " ".join(kept).strip())
    return updated, " ".join(notes).strip()


def _format_with_detected_pattern(
    title: str,
    article_type: str,
    source: str,
    summary: str | None,
) -> FormattedArticleContent:
    roles = _extract_role_items(source)
    preamble, items = _extract_numbered_items(source)
    trailing_notes = ""
    if items:
        items, trailing_notes = _peel_trailing_notes_from_items(items)
    bullet_preamble, bullets = _extract_bullet_items(source)
    clause_class = _classify_numbered_list(
        items,
        title=title,
        article_type=article_type,
        source=source,
    )
    content_pattern = _detect_content_pattern(
        title,
        article_type,
        source,
        items,
        roles,
        clause_class,
    )

    overview = _generated_overview(title, article_type, content_pattern)
    # Prefer short generated overview; never dump full source into Overview.
    if summary and len(_normalize_text(summary)) <= 220 and not _texts_overlap(summary, source, threshold=0.85):
        # Keep generated overview for structure consistency; summary stays separate in UI.
        pass

    if content_pattern in {"messy_ocr", "messy_fragments"}:
        result = _paragraph_only(title, source, article_type, content_pattern)
        result.formatting_notes = [content_pattern, "needs_cleanup"]
        return result

    if content_pattern == "role_responsibility_list" and roles:
        block, section = _render_roles_section(roles)
        notes = _collect_important_notes(source, exclude=[overview, section["body"]])
        result = _build_sections(
            overview=overview,
            detail_heading="Roles and Responsibilities",
            detail_block=block,
            detail_section=section,
            notes=notes,
        )
        result.official_source_excerpt = source
        notes_flags = ["role_responsibility_list"]
        if _looks_internal_role_article(title, source, roles):
            notes_flags.append("internal_facing")
        result.formatting_notes = notes_flags
        result.content_pattern = content_pattern
        return result

    if items:
        if clause_class == "true_procedure_steps":
            heading = "Process"
            style = "process"
            notes_heading = "Important Notes"
        elif clause_class == "requirements":
            heading = "Requirements"
            style = "requirements"
            notes_heading = "Important Notes"
        elif clause_class == "eligibility_conditions":
            heading = "Eligibility / Conditions"
            style = "conditions"
            notes_heading = "Important Notes"
        elif clause_class == "policy_clauses":
            heading = "Key Points"
            style = "key_points"
            notes_heading = "Important Reminders"
        else:
            heading = "Key Points"
            style = "key_points"
            notes_heading = "Important Reminders"

        block, section = _render_clause_items(heading, items, style=style)
        item_texts = [_item_full_text(number, label, body) for number, label, body in items]
        excluded = [overview, section["body"], preamble, *item_texts]

        instructions = ""
        if clause_class == "requirements" or article_type == "requirement":
            for sentence in _split_sentences(source):
                lower = sentence.lower()
                if any(token in lower for token in ("submit", "how to", "fill out", "deadline", "application form")):
                    if _is_duplicate_section_text(sentence, excluded, item_texts):
                        continue
                    instructions = f"{instructions} {sentence}".strip()

        notes = _collect_important_notes(source, exclude=excluded + [instructions])
        if trailing_notes:
            notes = f"{notes} {trailing_notes}".strip()
        result = _build_sections(
            overview=overview,
            detail_heading=heading,
            detail_block=block,
            detail_section=section,
            instructions=instructions,
            notes=notes,
            notes_heading=notes_heading,
            item_texts=item_texts,
        )
        result.official_source_excerpt = source
        result.formatting_notes = [content_pattern, clause_class]
        result.content_pattern = content_pattern
        return result

    if bullets:
        heading = "Requirements" if article_type == "requirement" else "Key Points"
        if content_pattern == "eligibility_conditions":
            heading = "Eligibility / Conditions"
        block, section = _render_bullet_section(heading, bullets)
        notes = _collect_important_notes(source, exclude=[overview, section["body"], bullet_preamble])
        result = _build_sections(
            overview=overview,
            detail_heading=heading,
            detail_block=block,
            detail_section=section,
            notes=notes,
            notes_heading="Important Notes" if heading != "Key Points" else "Important Reminders",
            item_texts=bullets,
        )
        result.official_source_excerpt = source
        result.formatting_notes = [content_pattern, "bullet_list"]
        result.content_pattern = content_pattern
        return result

    structured = _structured_fallback_from_sentences(title, article_type, source, content_pattern)
    if structured is not None:
        return structured

    # No clear list structure: short overview + labeled details (never unlabeled dump).
    result = FormattedArticleContent(
        display_content=f"Overview\n{overview}\n\nDetails\n{source}".strip(),
        official_source_excerpt=source,
        sections=[
            {"heading": "Overview", "body": overview},
            {"heading": "Details", "body": source},
        ],
        formatting_notes=["overview_only", "paragraph_spacing"],
        content_pattern="overview_only",
    )
    return result


def _format_form(
    title: str,
    source: str,
    summary: str | None,
    metadata: dict[str, Any] | None,
) -> FormattedArticleContent:
    meta = metadata or {}
    overview = _generated_overview(title, "form", "overview_only")
    lines = ["Purpose", overview, ""]
    sections: list[dict[str, str]] = [{"heading": "Purpose", "body": overview}]

    when_to_use = ""
    lower = source.lower()
    if any(token in lower for token in ("when to", "use this form", "apply for", "request")):
        when_to_use = " ".join(
            sentence
            for sentence in _split_sentences(source)
            if any(token in sentence.lower() for token in ("when to", "use this form", "apply for", "request"))
        ).strip()
    if when_to_use and not _texts_overlap(when_to_use, overview):
        lines.extend(["When to Use", when_to_use, ""])
        sections.append({"heading": "When to Use", "body": when_to_use})

    fill_out = " ".join(
        sentence
        for sentence in _split_sentences(source)
        if any(token in sentence.lower() for token in ("fill out", "complete the form", "submit", "provide"))
    ).strip()
    if fill_out and not _texts_overlap(fill_out, overview):
        lines.extend(["How to Fill Out", fill_out, ""])
        sections.append({"heading": "How to Fill Out", "body": fill_out})

    fields = meta.get("form_fields") or meta.get("fields")
    if isinstance(fields, list) and fields:
        field_lines = "\n".join(f"- {str(field).strip()}" for field in fields if str(field).strip())
        if field_lines:
            lines.extend(["How to Fill Out", field_lines, ""])
            sections.append({"heading": "How to Fill Out", "body": field_lines})

    office = str(meta.get("office") or "").strip()
    if office:
        lines.extend(["Related Service / Office", office])
        sections.append({"heading": "Related Service / Office", "body": office})

    return FormattedArticleContent(
        display_content="\n".join(lines).strip(),
        official_source_excerpt=source,
        sections=sections,
        formatting_notes=["form_sections"],
        content_pattern="overview_only",
    )


def _preserve_charter_display_content(content: str) -> str:
    """Keep charter indentation; only strip embedded metadata and normalize newlines."""
    text = str(content or "")
    if _METADATA_MARKER in text:
        text = text.split(_METADATA_MARKER, 1)[0]
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _looks_like_citizen_charter_article(content: str) -> bool:
    """Detect already-formatted Citizen's Charter service articles."""
    text = content or ""
    return (
        "Office / Division" in text
        and "Who May Avail" in text
        and "Client Step:" in text
        and "Source Information" in text
        and "Total Processing Time" in text
    )


def format_article_content(
    title: str,
    article_type: str,
    content: str,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> FormattedArticleContent:
    """Build structured student-facing article content while preserving source excerpt."""
    meta = metadata or {}
    parser_kind = str(meta.get("parser_document_type") or "").strip().lower()
    source_type = str(meta.get("source_type") or "").strip()
    raw_text = str(content or "")
    if (
        parser_kind == "citizen_charter"
        or source_type == "Citizen's Charter"
        or _looks_like_citizen_charter_article(raw_text)
    ):
        preserved = _preserve_charter_display_content(raw_text)
        if not preserved:
            return FormattedArticleContent(
                display_content="",
                official_source_excerpt="",
                sections=[],
                formatting_notes=["empty_source"],
                content_pattern="overview_only",
            )
        return FormattedArticleContent(
            display_content=preserved,
            official_source_excerpt=preserved,
            sections=[],
            formatting_notes=["citizen_charter_structure"],
            content_pattern="citizen_charter_service",
        )

    cleaned_source = clean_article_content_for_display(content or "")
    if not cleaned_source:
        return FormattedArticleContent(
            display_content="",
            official_source_excerpt="",
            sections=[],
            formatting_notes=["empty_source"],
            content_pattern="overview_only",
        )

    normalized_type = _normalize_article_type(article_type, metadata)
    if normalized_type == "form":
        return _format_form(title, cleaned_source, summary, metadata)

    return _format_with_detected_pattern(title, normalized_type, cleaned_source, summary)

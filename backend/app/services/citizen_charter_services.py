"""Citizen's Charter service helpers.

Generic ARTA-style charter parsing support. Does not hardcode institution-specific
office or service names. Office labels for publishing still come from office_aliases.
"""

from __future__ import annotations

import re
from typing import Any

_NEEDS_REVIEW = "[NEEDS REVIEW]"

# Generic noise / artifact titles that must not become public article candidates.
_NOISE_TITLE_PATTERNS = (
    r"^abstract\s+of\s+quotation",
    r"^official\s+receipt\b",
    r"^classification$",
    r"^classification\s*:\s*.+",
    r"^validation$",
    r"^nexus\s+system(?:\s*[-–—:]\s*part\s*\d+)?$",
    r"^board\s+of\s+regents\b",
    r"^board\s+secretary",
    r"^bac\s+sec\b",
    r"^checking\s+of\s+supporting",
    r"^prepare$",
    r"^list\s+of\s+services\b",
    r"^mandate\b",
    r"^vision\b",
    r"^mission\b",
    r"^service\s+pledge\b",
    r"^citizen'?s\s+charter\b",
    r"^republic\s+of\s+the\s+philippines\b",
    r"^feedback\s+and\s+complaints?\b",
    r"^contact\s+information\b",
    r"^page\s+\d+\b",
    r"^table\s+(?:of\s+contents|continued|continuation)\b",
    r"^continued\b",
    r"^continuation\b",
    r"^pledge\b",
    r"^total\b",
    r"^fees?\s*(?:to\s+be\s+paid)?\s*:",
    r"^fees?\s+to\s+be\s+paid\b",
    r"^where\s+to\s+secure\b",
    r"^checklist\s+of\s+requirements\b",
    r"^client\s+steps?\b",
    r"^agency\s+actions?\b",
    r"^person\s+responsible\b",
    r"^processing\s+time\s*:",
    r"^transaction\s+type\s*:",
    r"^requirement\s*:",
    r"^client\s+step\s*:",
    r"^agency\s+action\s*:",
    r"^who\s+may\s+avail\s*:",
    r"^office\s*(?:/|or)?\s*division\s*:",
    r"^\[needs\s+review\]",
    r"^simple$",
    r"^complex$",
    r"^highly\s+technical$",
    r"^academic$",
    r"^procurement\s+plan\b",
    r"^annual\s+procurement\s+plan\b",
    r"\b\[needs\s+review\]\b",
)

# OCR / table crumbs that are never standalone service titles.
_FRAGMENT_TITLE_PATTERNS = (
    r"^er\s+agencies\b",
    r"^irs\s+office\b",
    r"^ent\s*:\s*",
    r"^ees\s*:\s*",
    r"^propriate\s+",
    r"^ementing\s+",
    r"^l\s*:\s*",
    r"^registration\.?\s*registration\.?$",
    r"^[a-z]{1,3}\s*:\s*",
    r"^[a-z]{2,12}\s+(?:office|agencies|attachments|none)\b",
)

_PUBLISH_BLOCKING_REVIEW_FLAGS = frozenset({
    "mixed_charter_services",
    "administrative_background_title",
    "title_too_short",
    "title_incomplete_ocr_fragment",
    "artifact_title",
    "charter_artifact_title",
    "invalid_charter_service_block",
    "incomplete_charter_service",
    "missing_required_charter_fields",
    "unsafe_to_publish",
    "truncated_charter_title",
    "incomplete_structured_fields",
    "incomplete_step_rows",
    "table_row_fragment",
    "field_label_title",
    "office_only_title",
    "form_code_only_title",
})

# Flags that must block Recommended (Low Quality or Needs Review depending on severity).
CHARTER_BLOCKING_REVIEW_FLAGS = frozenset({
    *_PUBLISH_BLOCKING_REVIEW_FLAGS,
    "low_category_confidence_severe",
})

# Informational only — must NOT force Needs Review / block Recommended alone.
CHARTER_NON_BLOCKING_REVIEW_FLAGS = frozenset({
    "uncertain_office",
    "title_too_long",
    "title_looks_sentence",
    "title_ends_with_hanging_word",
    "title_looks_generic",
    "irregular_title_casing",
    "title_from_body",
    "low_category_confidence",
    "borderline_recommendation",
    "recommended_cap_exceeded",
    "charter_rebuilt_from_review_text",
})

# Cover / reference sections → RAG-only, not public articles.
_REFERENCE_SECTION_PATTERNS = (
    r"\bmandate\b",
    r"\bvision\b",
    r"\bmission\b",
    r"\bservice\s+pledge\b",
    r"\blist\s+of\s+services\b",
    r"\bfront\s+line\s+services?\b",
    r"\bexternal\s+services?\b",
    r"\binternal\s+services?\b",
    r"\borganizational\s+structure\b",
    r"\bdirectory\b",
)

# Generic internal/admin function signals (not institution office names).
_INTERNAL_AUDIENCE_PATTERNS = (
    r"\bprocurement\b",
    r"\bbidding\b|\bbids?\s+and\s+awards?\b|\bbac\b",
    r"\binternal\s+audit\b|\biau\b",
    r"\baudit\s+(?:office|services?|unit)\b",
    r"\blegal\s+(?:office|services?|affairs?|unit)\b",
    r"\bhuman\s+resource|\bhr\s+(?:office|services?|mo|records?)\b",
    r"\bemployee\s+records?\b",
    r"\bquality\s+assurance\b|\bqa\s+(?:office|unit|services?)\b",
    r"\bsupply\s+(?:and\s+)?property\b",
    r"\bproperty\s+management\b",
    r"\bsupply\s+(?:office|unit|section)\b",
    r"\bproject\s+management\b",
    r"\bplanning\s+and\s+development\b",
    r"\bgeneral\s+services?\b",
    r"\bresearch\s+(?:and\s+)?extension\b",
    r"\bresearch\s+project\b|\bextension\s+project\b",
    r"\bextension\s+services?\b",
    r"\bemployee[- ]only\b|\bemployees?\s+only\b",
    r"\bend[- ]users?\b|\bendusers?\b",
    r"\bpermanent\s+employee\b",
    r"\bplantilla\b",
    r"\bboard\s+secretary\b",
    r"\bsuppliers?\b|\bcontractors?\b",
    r"\bgovernment\s+to\s+government\b|\bg2g\b",
    r"\bpresident\s+approval\b|\bcampus\s+director\s+approval\b",
    r"\bcurriculum\s+review\b",
    r"\binstructional\s+materials?\s+evaluation\b",
    r"\binternal\s+academic\b",
    r"\bvehicle\s+request\b",
    r"\bbuilding\s+(?:maintenance|request)\b",
)

# Generic student/client-facing audience and service signals.
_STUDENT_AUDIENCE_PATTERNS = (
    r"\bstudents?\b",
    r"\bapplicants?\b",
    r"\balumni\b",
    r"\benrollees?\b",
    r"\bvisitors?\b",
    r"\bparents?\b",
    r"\bguardians?\b",
    r"\bgeneral\s+(?:public|clients?)\b",
    r"\bgovernment\s+to\s+citizen\b|\bg2c\b",
    r"\bclients?\b",
)

_STUDENT_SERVICE_TITLE_PATTERNS = (
    r"\bid\s+validation\b",
    r"\bstudent\s+id\b|\bprocessing\s+of\s+student\s+id\b|\bid\s+processing\b",
    r"\bgood\s+moral\b",
    r"\bentrance\s+exam",
    r"\benrollment\b|\benrollment\s+advis",
    r"\bdropping\b",
    r"\binc\b|\bremoval\b",
    r"\bscholarship\b|\bfinancial\s+assistance\b",
    r"\blibrary\b",
    r"\bmedical\b|\bdental\b|\broutine\s+medical\b",
    r"\bcounsel",
    r"\bappraisal\b",
    r"\balumni\s+id\b|\byearbook\b",
    r"\boverload\b|\bunscheduled\s+subject",
    r"\bcrediting\b|\badmission\s+interview\b|\bstudent\s+admission\b",
    r"\bsystem\s+information\s+registration",
    r"\bweb\s+posting\b|\bonline\s+posting\b",
    r"\bgrades?\b|\btranscript\b|\bcertificat",
    r"\bevent\s+coverage\b|\brequest\s+for\s+event\b",
    r"\bsigning\s+of\s+(?:general|semestral)\s+clearances?\b|\bclearances?\b",
    r"\bassessment\s+of\s+fees\b",
    r"\breleasing\s+of\s+clearance\b",
    r"\bauthentication\s+of\s+documents?\b|\bauthenticated\s+documents?\b",
    r"\buse\s+of\s+library\b",
)

# Titles that should remain student-facing even when transaction type includes G2G
# or the office is administrative (health/library/fees/clearance/etc.).
_PRIORITY_STUDENT_FACING_TITLE_PATTERNS = (
    r"\bid\s+validation\b",
    r"\bsigning\s+of\s+(?:general|semestral)\s+clearances?\b",
    r"\bissuance\s+of\s+good\s+moral\b|\bgood\s+moral\b",
    r"\blspu\s+entrance\b|\bentrance\s+examination\b",
    r"\bstudent\s+admission\s+interview\b|\badmission\s+interview\b",
    r"\bprocessing\s+of\s+student\s+id\b|\bid\s+processing\b",
    r"\bassessment\s+of\s+fees\b",
    r"\breleasing\s+of\s+clearance\b",
    r"\benrollment\b",
    r"\bauthentication\s+of\s+documents?\b|\bauthenticated\s+documents?\b",
    r"\blibrary\s+circulation\b",
    r"\blibrary\s+reference\b",
    r"\buse\s+of\s+library\b",
    r"\broutine\s+medical\b|\bmedical\s+and\s+dental\b|\bdental\s+services?\b",
    r"\bscholarship\b|\bfinancial\s+assistance\b",
    r"\bsystem\s+information\s+registration",
)

_HARD_INTERNAL_TITLE_PATTERNS = (
    r"\bprocurement\b",
    r"\bbids?\s+and\s+awards?\b|\bbac\b",
    r"\binternal\s+audit\b|\biso\s+internal\b",
    r"\bquality\s+assurance\b",
    r"\bsupply(?:\s+and\s+property)?\b|\bproperty\s+management\b",
    r"\bproject\s+management\b",
    r"\blegal\s+(?:services?|office|affairs?)\b",
    r"\bhuman\s+resource|\bhr\s+(?:office|mo|records?|employee)\b",
    r"\btravel\s+authority\b|\binternal\s+travel\b",
    r"\bemployee[- ]only\b|\bemployee\s+records?\b",
)

# Category mapping from generic service/office wording → student-friendly categories.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Admissions", (r"\badmission", r"\bentrance\s+exam", r"\benrollment\s+advis", r"\bnew\s+student")),
    ("Student Records", (r"\bregistrar", r"\btranscript", r"\bdiploma", r"\bcertificat", r"\bgood\s+moral", r"\binc\b", r"\bremoval", r"\bdropping", r"\brecords?\s+management")),
    ("Payments and Fees", (r"\bcashier", r"\bpayment", r"\bfees?\b", r"\baccounting", r"\breceipt")),
    ("Scholarships", (r"\bscholarship", r"\bfinancial\s+assistance")),
    ("Guidance and Counseling", (r"\bguidance", r"\bcounsel")),
    ("ICT Services", (r"\bict", r"\bportal", r"\bsystem\s+information", r"\bnetwork", r"\bemail\s+account")),
    ("Library Services", (r"\blibrary", r"\bborrow")),
    ("Health Services", (r"\bhealth\s+service", r"\bclinic", r"\bmedical", r"\bdental")),
    ("Alumni Services", (r"\balumni",)),
    ("College Services", (r"\bcollege\b", r"\bdean\b", r"\bdepartment\b")),
    ("Student Services", (r"\bosas\b", r"\bstudent\s+affairs", r"\bstudent\s+id", r"\bbusiness\s+affairs")),
    ("Administrative Services", (r"\badministrat", r"\binformation\s+office", r"\bpublic\s+information")),
)


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_service_part_suffix(title: str) -> str:
    """Remove trailing ' - Part N' / '(Part N)' so split pages can merge."""
    cleaned = _normalize_space(title)
    cleaned = re.sub(r"\s*[-–—:]\s*part\s*\d+\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*\(\s*part\s*\d+\s*\)\s*$", "", cleaned, flags=re.I)
    return cleaned.strip(" -–—:")


def normalize_service_merge_key(title: str) -> str:
    cleaned = strip_service_part_suffix(title).casefold()
    cleaned = re.sub(r"[^\w\s/]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_office_key(office: str | None) -> str:
    cleaned = _normalize_space(office).casefold()
    if not cleaned or cleaned == _NEEDS_REVIEW.casefold():
        return ""
    cleaned = re.sub(r"[^\w\s]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _offices_compatible(left: str | None, right: str | None) -> bool:
    a = _normalize_office_key(left)
    b = _normalize_office_key(right)
    if not a or not b:
        return True
    if a == b:
        return True
    return a in b or b in a


def is_noise_service_title(title: str) -> bool:
    cleaned = _normalize_space(title)
    if not cleaned or cleaned == _NEEDS_REVIEW:
        return True
    if len(cleaned) > 100 or "|" in cleaned:
        return True
    # Strip charter numbering / path leaf prefixes before pattern checks.
    cleaned = re.sub(r"^\d{1,3}[\.\)]\s*", "", cleaned).strip(" -–—:")
    cleaned = strip_service_part_suffix(cleaned)
    if ">" in cleaned:
        cleaned = cleaned.split(">")[-1].strip(" -–—:")
    lower = cleaned.casefold().rstrip(" >:-")
    for pattern in _NOISE_TITLE_PATTERNS:
        if re.search(pattern, lower, flags=re.I):
            return True
    for pattern in _FRAGMENT_TITLE_PATTERNS:
        if re.search(pattern, lower, flags=re.I):
            return True
    if is_charter_field_label_or_fragment_title(cleaned):
        return True
    if re.search(r"\bclassification\b", lower) and re.search(r"\bpart\s*\d+\b", lower):
        return True
    if ">" in _normalize_space(title) and re.search(
        r"\b(?:classification|abstract|official\s+receipt|nexus\s+system|board\s+of\s+regents)\b",
        _normalize_space(title).casefold(),
    ):
        return True
    if re.fullmatch(r"classification(?:\s*:\s*.+)?", lower):
        return True
    if re.fullmatch(r"nexus\s+system(?:\s*[-–—:]\s*part\s*\d+)?", lower):
        return True
    if re.fullmatch(r"official\s+receipt(?:\s*>.*)?", lower):
        return True
    if re.fullmatch(r"abstract\s+of\s+quotation.*", lower):
        return True
    # Bare fragment labels / table continuation crumbs.
    if re.fullmatch(r"\d{1,4}", lower):
        return True
    if re.fullmatch(
        r"(?:equipment|exit|services?|and technical staff|technical staff|staff|page)",
        lower,
    ):
        return True
    if len(cleaned.split()) <= 2 and re.search(
        r"^(?:part\s*\d+|table|continued?|fragment|header|footer|page)$",
        lower,
        flags=re.I,
    ):
        return True
    return False


def is_charter_field_label_or_fragment_title(title: str) -> bool:
    """True for table field labels, OCR crumbs, office-only, or form-code-only titles."""
    cleaned = _normalize_space(title)
    if not cleaned:
        return True
    cleaned = re.sub(r"^\d{1,3}[\.\)]\s*", "", cleaned).strip(" -–—:")
    if ">" in cleaned:
        cleaned = cleaned.split(">")[-1].strip(" -–—:")
    lower = cleaned.casefold()
    if "[needs review]" in lower:
        return True
    if re.match(
        r"^(?:fees?|processing\s+time|transaction\s+type|requirement|client\s+step|"
        r"agency\s+action|person\s+responsible|who\s+may\s+avail|office\s*(?:/|or)?\s*division|"
        r"classification|total(?:\s+processing\s+time)?)\s*:",
        lower,
    ):
        return True
    for pattern in _FRAGMENT_TITLE_PATTERNS:
        if re.search(pattern, lower, flags=re.I):
            return True
    # Office-name-only without a service verb/noun.
    if re.fullmatch(
        r"[a-z0-9 .&\-/]{2,40}\s+(?:office|division|unit|section|department)\b",
        lower,
    ) and not re.search(
        r"\b(?:validation|processing|issuance|request|application|enrollment|advis|"
        r"counsel|dropping|completion|circulation|assessment|appraisal|admission)\b",
        lower,
    ):
        return True
    # Form code only, e.g. O-SF-011: Patent Application Form without charter structure.
    if re.match(r"^[a-z]{1,3}-?[a-z]{0,3}-?\d{2,4}\s*:", lower):
        return True
    # Repeated word crumb: "Registration. Registration."
    words = re.findall(r"[a-z0-9]+", lower)
    if len(words) == 2 and words[0] == words[1] and len(words[0]) <= 20:
        return True
    # Leading lowercase OCR crumb (er Agencies / propriate attachments).
    if cleaned[:1].islower() and len(cleaned.split()) <= 4:
        return True
    return False


def is_artifact_charter_title(title: str) -> bool:
    """Hard reject titles that must never become article previews."""
    return is_noise_service_title(title)


def _path_segments(path: str | None) -> list[str]:
    text = _normalize_space(path)
    if not text:
        return []
    return [part.strip(" >:-") for part in re.split(r"\s*>\s*", text) if part.strip(" >:-")]


def charter_path_has_artifact(path: str | None) -> bool:
    """True when any hierarchy/source-section segment is an artifact label."""
    return any(is_artifact_charter_title(part) for part in _path_segments(path))


def is_charter_or_service_process_unit(unit: dict[str, Any] | None) -> bool:
    """Detect Citizen's Charter / Service Process profile from unit metadata."""
    if not isinstance(unit, dict):
        return False
    metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
    parser_kind = str(
        unit.get("parser_document_type") or metadata.get("parser_document_type") or ""
    ).strip().lower()
    source_type = str(unit.get("source_type") or metadata.get("source_type") or "").strip()
    source_type_l = source_type.casefold()
    document_type = str(
        unit.get("document_type") or metadata.get("document_type") or ""
    ).strip().lower()
    document_profile = str(
        unit.get("document_profile") or metadata.get("document_profile") or ""
    ).strip().lower()
    return (
        parser_kind in {"citizen_charter", "service_process"}
        or document_type in {"citizen_charter", "service_process"}
        or document_profile in {"citizen_charter", "service_process"}
        or source_type in {"Citizen's Charter", "Service Process"}
        or "citizen" in source_type_l and "charter" in source_type_l
        or "service process" in source_type_l
    )


def looks_like_citizen_charter_text(text: str) -> bool:
    """Structural charter signals — not filename-based."""
    blob = text or ""
    signals = [
        r"\bOffice\s*(?:or)?\s*Division\b",
        r"\bWho\s+May\s+Avail\b",
        r"\bChecklist\s+of\s+Requirements\b",
        r"\bWhere\s+to\s+Secure\b",
        r"\bCLIENT\s+STEPS\b",
        r"\bAgency\s+Actions\b",
        r"\bProcessing\s+Time\b",
        r"\bPerson\s+Responsible|Responsible\s+Person",
        r"\bClassification\s*:",
    ]
    return sum(1 for pattern in signals if re.search(pattern, blob, flags=re.I)) >= 4


def charter_body_has_required_sections(text: str) -> bool:
    """True when body follows the fixed Citizen's Charter article structure."""
    blob = text or ""
    required = (
        r"(?m)^Overview\s*$",
        r"(?m)^Office\s*/\s*Division\s*$",
        r"(?m)^Who\s+May\s+Avail\s*$",
        r"(?m)^Requirements\s*$",
        r"(?m)^Steps\s*$",
        r"(?m)^Fees\s*$",
        r"(?m)^Total\s+Processing\s+Time\s*$",
        r"(?m)^Source\s+Information\s*$",
    )
    return all(re.search(pattern, blob, flags=re.I) for pattern in required)


_BLANK_REQUIREMENTS_LINE = "No additional requirements specified in the Citizen's Charter."


def charter_body_has_blocking_placeholders(text: str) -> bool:
    """True when the student-facing body still contains placeholder gaps.

    Source Information (including Page) is excluded so a missing page number
    alone does not block Recommended.
    """
    blob = text or ""
    if not blob.strip():
        return True
    main = re.split(r"(?m)^Source\s+Information\s*$", blob, maxsplit=1)[0]
    if _NEEDS_REVIEW in main:
        return True
    if re.search(r"\bNot specified\b", main, flags=re.I):
        return True
    return False


def resolve_preview_document_profile(preview: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve Citizen's Charter / Service Process profile from preview payload.

    Priority: admin-selected → extraction metadata → structural detection.
    """
    preview = preview if isinstance(preview, dict) else {}
    detected = preview.get("detected_document_type")
    admin_selected = preview.get("admin_selected_document_type")
    if admin_selected is None and isinstance(detected, dict):
        admin_selected = detected.get("admin_selected_document_type")

    detected_type = ""
    if isinstance(detected, dict):
        detected_type = str(detected.get("document_type") or "").strip().lower()
    elif isinstance(detected, str):
        detected_type = detected.strip().lower()

    top_type = str(preview.get("document_type") or preview.get("document_profile") or "").strip().lower()
    parser_type = str(preview.get("parser_document_type") or "").strip().lower()
    source_type = str(preview.get("source_type") or "").strip()

    units = preview.get("knowledge_units") or []
    unit_charter = any(is_charter_or_service_process_unit(unit) for unit in units if isinstance(unit, dict))

    review_text = collect_charter_parser_text(preview, {
        "review_text": preview.get("review_text"),
    })
    # Keep earlier explicit fields preferred when already resolved.
    if not review_text:
        review_text = str(
            preview.get("review_text")
            or preview.get("extracted_text")
            or preview.get("cleaned_text")
            or ""
        )

    structural = looks_like_citizen_charter_text(review_text) or parsed_kind_is_charter(review_text)
    admin_l = str(admin_selected or "").strip().lower().replace(" ", "_")
    admin_charter = admin_l in {
        "citizen_charter",
        "citizens_charter",
        "charter",
        "procedure",
        "service_process",
        "service-process",
    }

    is_charter = False
    if admin_charter and (structural or unit_charter or parser_type == "citizen_charter"):
        is_charter = True
    elif parser_type in {"citizen_charter", "service_process"} or unit_charter:
        is_charter = True
    elif top_type in {"citizen_charter", "service_process"}:
        is_charter = True
    elif detected_type in {"citizen_charter", "service_process"}:
        is_charter = True
    elif detected_type == "procedure" and structural:
        is_charter = True
    elif structural:
        is_charter = True

    profile = "citizen_charter" if is_charter else (top_type or detected_type or "unknown")
    return {
        "document_profile": profile,
        "is_charter": is_charter,
        "admin_selected_document_type": admin_selected,
        "detected_document_type": detected_type or top_type or None,
        "source_type": source_type or ("Citizen's Charter" if is_charter else None),
        "parser_document_type": "citizen_charter" if is_charter else (parser_type or None),
        "review_text": review_text,
    }


def parsed_kind_is_charter(text: str) -> bool:
    try:
        from app.services.structured_document_parser import classify_document_type

        return classify_document_type(text) == "citizen_charter"
    except Exception:
        return looks_like_citizen_charter_text(text)


def should_reject_charter_article_candidate(
    *,
    title: str | None = None,
    source_section: str | None = None,
    parent_topic: str | None = None,
    hierarchy_path: str | None = None,
    office: str | None = None,
    who_may_avail: str | None = None,
    require_service_fields: bool = False,
) -> bool:
    """Reject artifact / incomplete charter candidates from publishable buckets.

    Noisy parent paths (e.g. Abstract of Quotation… > ID Validation) do NOT
    reject a clean service title. Only reject when the title itself is an artifact,
    or when the leaf path segment is an artifact title.
    """
    resolved_title = strip_service_part_suffix(_normalize_space(title))
    resolved_title = re.sub(r"^\d{1,3}[\.\)]\s*", "", resolved_title).strip(" -–—:")
    if is_artifact_charter_title(resolved_title):
        return True

    # Parent topic alone is not enough to reject a clean service title.
    if parent_topic and is_artifact_charter_title(parent_topic):
        parent_key = normalize_service_merge_key(parent_topic)
        title_key = normalize_service_merge_key(resolved_title)
        if parent_key and title_key and parent_key == title_key:
            return True

    path = source_section or hierarchy_path or ""
    segments = _path_segments(path)
    if segments:
        leaf = segments[-1]
        leaf_clean = re.sub(r"^\d{1,3}[\.\)]\s*", "", leaf).strip(" -–—:")
        if is_artifact_charter_title(leaf_clean):
            # Leaf is the artifact (e.g. … > Classification: Academic).
            return True
        # Noisy ancestors are OK when the leaf/title is a clean service name.

    if resolved_title and ">" in resolved_title:
        leaf = _path_segments(resolved_title)[-1] if _path_segments(resolved_title) else resolved_title
        if is_artifact_charter_title(leaf):
            return True

    if require_service_fields:
        if not _filled(office) or not _filled(who_may_avail):
            return True
    return False


def _coerce_list_field(value: Any) -> list[Any]:
    import json

    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def is_valid_charter_service_block(
    *,
    title: str,
    service: dict[str, Any] | None = None,
    text: str = "",
) -> bool:
    """Minimum gate for a usable Citizen's Charter service article.

    Accept when the block has a clean title plus enough service signals for
    OCR-imperfect tables. Do not require every field to be perfect.
    """
    if is_artifact_charter_title(title):
        return False
    if re.fullmatch(r"\d{1,4}", _normalize_space(title)):
        return False
    if has_mixed_charter_services(title=title, text=text):
        return False

    data = dict(service or {})
    data["requirements"] = _coerce_list_field(data.get("requirements"))
    data["steps"] = _coerce_list_field(data.get("steps"))

    has_office = _filled(data.get("office"))
    has_classification = _filled(data.get("classification"))
    has_who = _filled(data.get("who_may_avail"))
    has_reqs_or_steps = _has_procedure_content(data) or _has_real_charter_steps(data.get("steps") or [])
    has_total = _filled(data.get("total_processing_time"))
    steps = [
        item
        for item in (data.get("steps") or [])
        if isinstance(item, dict)
        and not _is_table_header_step(item)
        and (
            _filled(item.get("client_step"))
            or _filled(item.get("agency_action"))
        )
    ]
    has_processing = has_total or any(_filled(item.get("processing_time")) for item in steps)

    # Text-only fallback: OCR body still shows charter structure.
    text_l = (text or "").casefold()
    text_office = bool(re.search(r"\boffice\s*(?:or)?\s*/?\s*division\b", text_l))
    text_who_or_class = bool(
        re.search(r"\bwho\s+may\s+avail\b", text_l)
        or re.search(r"\bclassification\s*:", text_l)
    )
    text_procedure = bool(
        re.search(r"\bchecklist\s+of\s+requirements\b|\bclient\s+steps?\b|\brequirement:", text_l)
    )
    text_time = bool(re.search(r"\bprocessing\s+time\b|\btotal\b", text_l))

    if not _filled(title):
        return False
    if not (has_office or text_office):
        return False
    if not (has_who or has_classification or text_who_or_class):
        return False
    if not (has_reqs_or_steps or text_procedure):
        return False
    if not (steps or has_processing or text_time):
        return False
    return True


def collect_charter_parser_text(preview: dict[str, Any] | None = None, profile: dict[str, Any] | None = None) -> str:
    """Best available text for Citizen's Charter service-block parsing."""
    preview = preview if isinstance(preview, dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    candidates = [
        profile.get("review_text"),
        preview.get("review_text"),
        preview.get("extracted_text"),
        preview.get("cleaned_text"),
        (preview.get("structured") or {}).get("formatted_text")
        if isinstance(preview.get("structured"), dict)
        else None,
    ]
    for value in candidates:
        text = str(value or "").strip()
        if len(text) >= 80:
            return text

    units = preview.get("knowledge_units") or []
    joined = "\n\n".join(
        str(unit.get("content") or "").strip()
        for unit in units
        if isinstance(unit, dict) and str(unit.get("content") or "").strip()
    ).strip()
    if joined:
        return joined

    chunks = preview.get("chunk_preview") or []
    joined_chunks = "\n\n".join(
        str(chunk.get("content") or chunk.get("content_preview") or "").strip()
        for chunk in chunks
        if isinstance(chunk, dict)
        and str(chunk.get("content") or chunk.get("content_preview") or "").strip()
    ).strip()
    return joined_chunks


def charter_blocks_publish(reasons: list[str] | None = None) -> bool:
    """True when review flags must block Publish / bulk publish."""
    return any(str(reason or "").strip() in _PUBLISH_BLOCKING_REVIEW_FLAGS for reason in (reasons or []))


_FIELD_LINE_RE = re.compile(
    r"(?i)^\s*(?:overview|office\s*/\s*division|who may avail|requirements?|steps?|"
    r"fees?|total processing time|source information|document:|service:|office:|page:|"
    r"client step:|agency action:|processing time:|person responsible:|where to secure:|"
    r"- requirement:)"
)


def find_charter_service_headings(text: str) -> list[str]:
    """Detect distinct service-like headings inside a body (for mixed-block checks)."""
    found: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?m)^\s*(\d{1,3}[\.\)]\s+)?([^\n|]{3,90})\s*$", text or ""):
        raw = _normalize_space(match.group(2))
        if not raw or _FIELD_LINE_RE.match(raw):
            continue
        # Numbered charter headings are strong signals; plain lines must look title-like.
        numbered = bool(match.group(1))
        if not numbered:
            if raw.endswith("."):
                continue
            if len(raw.split()) < 3 or len(raw.split()) > 12:
                continue
            if not re.match(r"^[A-Z]", raw):
                continue
        title = strip_service_part_suffix(re.sub(r"^\d+[\.\)]\s*", "", raw).strip(" -–—:"))
        if not title or is_noise_service_title(title):
            continue
        if re.search(
            r"\b(Office|Classification|Who May Avail|Checklist|CLIENT STEPS|Agency Actions|"
            r"Type of Transaction|Transaction Type|This service provides)\b",
            title,
            flags=re.I,
        ):
            continue
        key = normalize_service_merge_key(title)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(title)
    return found


def has_mixed_charter_services(*, title: str, text: str) -> bool:
    """True when body contains 2+ unrelated service headings."""
    primary = normalize_service_merge_key(strip_service_part_suffix(title or ""))
    headings = find_charter_service_headings(text or "")
    if len(headings) >= 2:
        keys = [normalize_service_merge_key(item) for item in headings]
        unrelated = [
            key
            for key in keys
            if key
            and key != primary
            and primary not in key
            and key not in primary
        ]
        if len(set(unrelated)) >= 1:
            return True
    # Raw overlapping windows often repeat Office or Division labels.
    office_hits = len(re.findall(r"\bOffice\s*(?:or)?\s*Division\s*:", text or "", flags=re.I))
    if office_hits >= 2:
        numbered_heads = len(re.findall(r"(?m)^\s*\d{1,3}[\.\)]\s+[A-Z].{2,80}\s*$", text or ""))
        return numbered_heads >= 2
    return False


def is_charter_reference_section(title: str, text: str = "") -> bool:
    blob = f"{title}\n{text}".casefold()
    if any(re.search(pattern, blob, flags=re.I) for pattern in _REFERENCE_SECTION_PATTERNS):
        # Still a real service if it has client steps / checklist body.
        if re.search(r"\bclient\s+steps\b", blob, flags=re.I) and re.search(
            r"\bchecklist\s+of\s+requirements\b|\bagency\s+actions\b",
            blob,
            flags=re.I,
        ):
            return False
        return True
    return False


def is_priority_student_facing_title(title: str | None) -> bool:
    cleaned = strip_service_part_suffix(_normalize_space(title))
    cleaned = re.sub(r"^\d{1,3}[\.\)]\s*", "", cleaned).strip(" -–—:")
    if not cleaned:
        return False
    return any(
        re.search(pattern, cleaned, flags=re.I) for pattern in _PRIORITY_STUDENT_FACING_TITLE_PATTERNS
    )


def is_hard_internal_charter_title(title: str | None, office: str | None = None) -> bool:
    blob = " ".join(
        part
        for part in (title, office)
        if part and str(part).strip() and str(part).strip() != _NEEDS_REVIEW
    )
    if not blob:
        return False
    return any(re.search(pattern, blob, flags=re.I) for pattern in _HARD_INTERNAL_TITLE_PATTERNS)


def classify_charter_audience(
    *,
    office: str | None = None,
    who_may_avail: str | None = None,
    title: str | None = None,
    text: str | None = None,
    category: str | None = None,
    transaction_type: str | None = None,
) -> str:
    """Return student_facing | internal | ambiguous."""
    scores = score_charter_audience_signals(
        office=office,
        who_may_avail=who_may_avail,
        title=title,
        text=text,
        category=category,
        transaction_type=transaction_type,
    )
    student = int(scores["student_facing_score"])
    internal = int(scores["internal_admin_score"])
    txn = (transaction_type or "").casefold()
    who = (who_may_avail or "").casefold()

    # Priority student-facing services should not be forced internal by G2G alone
    # or because the delivering office is administrative (clinic, library, cashier).
    if is_priority_student_facing_title(title) and not is_hard_internal_charter_title(title, office):
        if re.search(
            r"\b(?:students?|applicants?|alumni|enrollees?|clients?|visitors?)\b",
            who,
            flags=re.I,
        ) or student >= 1 or is_priority_student_facing_title(title):
            return "student_facing"

    if is_hard_internal_charter_title(title, office) and not is_priority_student_facing_title(title):
        return "internal"

    if re.search(r"\bg2g\b|government\s+to\s+government", txn, flags=re.I):
        # G2G alone is not enough when the title is a known student service.
        if not is_priority_student_facing_title(title):
            return "internal"
    if re.search(r"\bg2c\b|government\s+to\s+citizen", txn, flags=re.I) and internal <= student + 1:
        # Prefer public/student-facing when G2C unless internal signals dominate.
        if internal > student + 1:
            return "internal"
        return "student_facing"
    if student <= 0 and internal <= 0:
        return "ambiguous"
    if student > internal:
        return "student_facing"
    if internal > student:
        return "internal"
    if re.search(
        r"\b(?:students?|applicants?|alumni|enrollees?|visitors?)\b", who, flags=re.I
    ):
        return "student_facing"
    if re.search(
        r"\b(?:employee|employees?|procurement|audit|bac|plantilla|end[- ]?users?|"
        r"suppliers?|offices?)\b",
        who,
        flags=re.I,
    ):
        return "internal"
    return "ambiguous"


def score_charter_audience_signals(
    *,
    office: str | None = None,
    who_may_avail: str | None = None,
    title: str | None = None,
    text: str | None = None,
    category: str | None = None,
    transaction_type: str | None = None,
) -> dict[str, int]:
    """Count student-facing vs internal/admin signals for routing debug."""
    blob = " ".join(
        part
        for part in (office, who_may_avail, title, text, category, transaction_type)
        if part and str(part).strip() and str(part).strip() != _NEEDS_REVIEW
    ).casefold()
    title_blob = " ".join(
        part
        for part in (title, category)
        if part and str(part).strip() and str(part).strip() != _NEEDS_REVIEW
    ).casefold()
    student = sum(1 for pattern in _STUDENT_AUDIENCE_PATTERNS if re.search(pattern, blob, flags=re.I))
    student += sum(
        1 for pattern in _STUDENT_SERVICE_TITLE_PATTERNS if re.search(pattern, title_blob or blob, flags=re.I)
    )
    if is_priority_student_facing_title(title):
        student += 3
    internal = sum(1 for pattern in _INTERNAL_AUDIENCE_PATTERNS if re.search(pattern, blob, flags=re.I))
    if is_hard_internal_charter_title(title, office) and not is_priority_student_facing_title(title):
        internal += 3
    txn = (transaction_type or "").casefold()
    if re.search(r"\bg2c\b|government\s+to\s+citizen", txn, flags=re.I):
        student += 2
    if re.search(r"\bg2g\b|government\s+to\s+government", txn, flags=re.I):
        # Do not overweight G2G against known student-facing titles.
        if not is_priority_student_facing_title(title):
            internal += 2
    if re.search(r"\bg2b\b|government\s+to\s+business", txn, flags=re.I):
        internal += 1
    return {
        "student_facing_score": int(student),
        "internal_admin_score": int(internal),
    }


def looks_like_truncated_charter_title(title: str | None) -> bool:
    """Detect truncated OCR titles that lost an important prefix."""
    cleaned = strip_service_part_suffix(_normalize_space(title))
    cleaned = re.sub(r"^\d{1,3}[\.\)]\s*", "", cleaned).strip(" -–—:")
    if not cleaned:
        return True
    # e.g. "Modification (Manual Process)" missing "System Information Registration/"
    if re.match(
        r"^(?:modification|registration|processing|issuance|request|completion)\s*\(",
        cleaned,
        flags=re.I,
    ):
        return True
    if re.match(r"^(?:manual\s+process|online\s+system)\b", cleaned, flags=re.I):
        return True
    return False


def charter_blocking_review_flags(reasons: list[str] | None = None) -> list[str]:
    return [
        str(reason)
        for reason in (reasons or [])
        if str(reason or "").strip() in CHARTER_BLOCKING_REVIEW_FLAGS
    ]


def decide_charter_bucket(
    *,
    title: str,
    service: dict[str, Any] | None = None,
    audience: str | None = None,
    text: str = "",
    category: str | None = None,
    review_reasons: list[str] | None = None,
    formatter_used: str | None = None,
    parser_used: str | None = None,
) -> dict[str, Any]:
    """Decide Recommended / Needs Review / Low Quality / RAG-only for a charter service."""
    data = dict(service or {})
    reasons = [str(r) for r in (review_reasons or []) if str(r or "").strip()]
    scores = score_charter_audience_signals(
        office=data.get("office"),
        who_may_avail=data.get("who_may_avail"),
        title=title,
        text=text,
        category=category,
        transaction_type=data.get("transaction_type"),
    )
    resolved_audience = (audience or "").strip().lower() or classify_charter_audience(
        office=data.get("office"),
        who_may_avail=data.get("who_may_avail"),
        title=title,
        text=text,
        category=category,
        transaction_type=data.get("transaction_type"),
    )

    if looks_like_truncated_charter_title(title):
        return {
            "bucket": "low_quality",
            "bucket_reason": "truncated_charter_title",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["truncated_charter_title"],
        }

    if is_artifact_charter_title(title) or is_charter_reference_section(title, text):
        return {
            "bucket": "rag_only",
            "bucket_reason": "charter_artifact_or_reference",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["charter_artifact_title"],
        }

    if is_charter_field_label_or_fragment_title(title):
        return {
            "bucket": "low_quality",
            "bucket_reason": "field_label_title",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["field_label_title"],
        }

    if has_mixed_charter_services(title=title, text=text):
        return {
            "bucket": "low_quality",
            "bucket_reason": "mixed_charter_services",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["mixed_charter_services"],
        }

    body_ok = True
    looks_formatted = bool(re.search(r"(?m)^Overview\s*$", text or ""))
    if looks_formatted:
        body_ok = charter_body_has_required_sections(text)

    if looks_formatted and charter_body_has_blocking_placeholders(text):
        return {
            "bucket": "needs_review",
            "bucket_reason": "body_has_not_specified_placeholders",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["incomplete_structured_fields"],
        }

    if not is_valid_charter_service_block(title=title, service=data, text=text) or not body_ok:
        flag = "invalid_charter_service_block" if not body_ok else "incomplete_charter_service"
        return {
            "bucket": "low_quality",
            "bucket_reason": flag,
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": [flag],
        }

    blocking = charter_blocking_review_flags(reasons)
    if blocking:
        severe_low = any(
            flag in {
                "mixed_charter_services",
                "invalid_charter_service_block",
                "incomplete_charter_service",
                "artifact_title",
                "charter_artifact_title",
                "title_incomplete_ocr_fragment",
                "administrative_background_title",
                "truncated_charter_title",
                "missing_required_charter_fields",
                "unsafe_to_publish",
            }
            for flag in blocking
        )
        return {
            "bucket": "low_quality" if severe_low else "needs_review",
            "bucket_reason": blocking[0],
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": blocking,
        }

    if resolved_audience == "internal" or scores["internal_admin_score"] > scores["student_facing_score"]:
        return {
            "bucket": "needs_review",
            "bucket_reason": "internal_admin_heavy",
            "charter_audience": "internal",
            **scores,
            "blocking_review_flags": [],
        }

    if resolved_audience == "ambiguous" and scores["student_facing_score"] <= 0:
        return {
            "bucket": "needs_review",
            "bucket_reason": "uncertain_audience",
            "charter_audience": "ambiguous",
            **scores,
            "blocking_review_flags": [],
        }

    # Clean + student/public-facing → Recommended (charter-specific gate; no handbook thresholds).
    parser_ok = not parser_used or parser_used in {"citizen_charter_service_parser", "citizen_charter_extractor_v2"}
    formatter_ok = not formatter_used or formatter_used == "build_charter_article_body"
    if not parser_ok or not formatter_ok:
        return {
            "bucket": "needs_review",
            "bucket_reason": "unexpected_charter_formatter",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": [],
        }

    # Require clean structured fields before Recommended.
    office_ok = _filled(data.get("office"))
    who_ok = _filled(data.get("who_may_avail")) or _filled(data.get("classification"))
    has_real_steps = _has_real_charter_steps(data.get("steps") or [])
    has_complete_step = _has_complete_charter_step(data.get("steps") or [])
    checklist_blank = bool(data.get("checklist_blank"))
    has_reqs = _has_procedure_content({"requirements": data.get("requirements") or []}) or checklist_blank
    has_total = _filled(data.get("total_processing_time"))
    all_steps_complete = has_real_steps and _all_charter_steps_complete(data.get("steps") or [])
    uncertain_with_incomplete = "uncertain_office" in reasons and (not office_ok)
    if uncertain_with_incomplete or not office_ok or not who_ok or not (has_reqs or has_real_steps):
        return {
            "bucket": "needs_review",
            "bucket_reason": "incomplete_structured_fields",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["incomplete_structured_fields"],
        }
    if checklist_blank and not all_steps_complete:
        return {
            "bucket": "needs_review",
            "bucket_reason": "blank_checklist_incomplete_steps",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["incomplete_step_rows"],
        }
    if not has_real_steps:
        return {
            "bucket": "needs_review",
            "bucket_reason": "incomplete_structured_fields",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["incomplete_structured_fields"],
        }
    if not has_total:
        return {
            "bucket": "needs_review",
            "bucket_reason": "missing_total_processing_time",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["incomplete_structured_fields"],
        }
    if not (has_complete_step or (has_real_steps and has_total and all_steps_complete)):
        return {
            "bucket": "needs_review",
            "bucket_reason": "incomplete_step_rows",
            "charter_audience": resolved_audience,
            **scores,
            "blocking_review_flags": ["incomplete_step_rows"],
        }

    return {
        "bucket": "recommended",
        "bucket_reason": "clean_student_facing_service",
        "charter_audience": "student_facing",
        **scores,
        "blocking_review_flags": [],
    }


def classify_charter_candidate_bucket(
    *,
    title: str,
    service: dict[str, Any] | None = None,
    audience: str | None = None,
    text: str = "",
    category: str | None = None,
) -> str:
    """Return recommended | needs_review | low_quality | rag_only for charter services."""
    decision = decide_charter_bucket(
        title=title,
        service=service,
        audience=audience,
        text=text,
        category=category,
    )
    return str(decision["bucket"])


_V2_QUALITY_BUCKET_FLOOR: dict[str, tuple[str, ...]] = {
    "needs_review": ("needs_review", "low_quality", "rag_only"),
    "low_quality": ("low_quality", "rag_only"),
    "rag_only": ("rag_only",),
}


def charter_v2_service_to_fields(service: dict[str, Any] | None) -> dict[str, Any]:
    """Adapt a compact Citizen's Charter Extraction V2 service dict into the
    same service-fields shape used by ``build_charter_article_body`` /
    ``decide_charter_bucket`` / ``is_valid_charter_service_block`` (V1).

    V2 (``citizen_charter_extractor_v2.CharterServiceV2``) and V1 already use
    matching requirement/step field names (requirement/where_to_secure,
    client_step/agency_action/fees/processing_time/person_responsible); the
    only rename needed is office_division -> office.

    Prefer ``office_division``, then ``extracted_office``, then
    ``parser_debug.detected_office`` so article bodies keep the detected
    office even when office_aliases matching left publish ``office`` empty.
    """
    data = dict(service or {})
    debug = data.get("parser_debug") if isinstance(data.get("parser_debug"), dict) else {}

    def _prefer_office(*values: Any) -> str | None:
        for value in values:
            text = str(value or "").strip()
            if text and text not in {_NEEDS_REVIEW, "Not specified"}:
                return text
        return None

    office = _prefer_office(
        data.get("office_division"),
        data.get("extracted_office"),
        data.get("office"),
        debug.get("detected_office"),
    )
    requirements: list[dict[str, Any]] = []
    for item in data.get("requirements") or []:
        if isinstance(item, dict):
            requirements.append(
                {
                    "requirement": item.get("requirement"),
                    "where_to_secure": item.get("where_to_secure"),
                }
            )
    steps: list[dict[str, Any]] = []
    for item in data.get("steps") or []:
        if isinstance(item, dict):
            steps.append(
                {
                    "client_step": item.get("client_step"),
                    "agency_action": item.get("agency_action"),
                    "fees": item.get("fees"),
                    "processing_time": item.get("processing_time"),
                    "person_responsible": item.get("person_responsible"),
                }
            )
    return {
        "office": office,
        "who_may_avail": data.get("who_may_avail"),
        "classification": data.get("classification"),
        "transaction_type": data.get("transaction_type"),
        "requirements": requirements,
        "steps": steps,
        "total_processing_time": data.get("total_processing_time"),
        "total_fees": data.get("total_fees"),
        "page": data.get("page_start"),
        "checklist_blank": bool(data.get("checklist_blank")),
        "parser_debug": debug,
    }


def decide_charter_bucket_for_v2(
    *,
    title: str,
    service: dict[str, Any] | None = None,
    audience: str | None = None,
    text: str = "",
    category: str | None = None,
    review_reasons: list[str] | None = None,
    extraction_quality: str = "clean",
) -> dict[str, Any]:
    """Decide Recommended / Needs Review / Low Quality / RAG-only for a
    Citizen's Charter Extraction V2 service.

    Reuses the same ``decide_charter_bucket`` gate V1 relies on (never
    loosened), then applies V2's own ``extraction_quality`` as a floor so
    natural gating can only make the outcome stricter — never better — than
    what the V2 extractor already flagged (e.g. a V2 ``rag_only``/placeholder
    service can never reach Recommended or Needs Review).
    """
    decision = dict(
        decide_charter_bucket(
            title=title,
            service=service,
            audience=audience,
            text=text,
            category=category,
            review_reasons=review_reasons,
            formatter_used="build_charter_article_body",
            parser_used="citizen_charter_extractor_v2",
        )
    )
    allowed = _V2_QUALITY_BUCKET_FLOOR.get(str(extraction_quality or "").strip().lower())
    if allowed and decision.get("bucket") not in allowed:
        decision["bucket"] = allowed[0]
        decision["bucket_reason"] = f"charter_v2_{extraction_quality}"
        blocking = list(decision.get("blocking_review_flags") or [])
        if allowed[0] == "low_quality" and "incomplete_charter_service" not in blocking:
            blocking.append("incomplete_charter_service")
        decision["blocking_review_flags"] = blocking
    return decision


def map_charter_category(
    *,
    office: str | None = None,
    title: str | None = None,
    text: str | None = None,
    service_category: str | None = None,
) -> str:
    """Map to a student-friendly category using generic wording (no hardcoded offices)."""
    preferred = _normalize_space(service_category)
    if preferred and preferred.casefold() not in {"general", "general information", "other", "misc"}:
        for category, _ in _CATEGORY_RULES:
            if preferred.casefold() == category.casefold():
                return category
        if len(preferred.split()) <= 4:
            return preferred

    office_blob = _normalize_space(office).casefold()
    if office_blob and office_blob != _NEEDS_REVIEW.casefold():
        for category, patterns in _CATEGORY_RULES:
            if any(re.search(pattern, office_blob, flags=re.I) for pattern in patterns):
                return category

    blob = " ".join(
        part
        for part in (title, text)
        if part and str(part).strip() and str(part).strip() != _NEEDS_REVIEW
    ).casefold()
    for category, patterns in _CATEGORY_RULES:
        if any(re.search(pattern, blob, flags=re.I) for pattern in patterns):
            return category
    return "Student Services"


def _filled(value: Any) -> bool:
    text = _normalize_space(value)
    if not text or text == _NEEDS_REVIEW or text.casefold() == "not specified":
        return False
    # Reject Office/Division label remnants.
    if text.casefold() in {
        "or division",
        "division",
        "office",
        "office or division",
        "office / division",
        "office/division",
    }:
        return False
    return True


def _has_real_charter_steps(steps: list[Any]) -> bool:
    real = 0
    for item in steps:
        if not isinstance(item, dict):
            continue
        if _is_table_header_step(item):
            continue
        client = _normalize_space(item.get("client_step"))
        agency = _normalize_space(item.get("agency_action"))
        processing = _normalize_space(item.get("processing_time"))
        responsible = _normalize_space(
            item.get("person_responsible") or item.get("responsible_personnel")
        )
        if client in {"", _NEEDS_REVIEW} and agency in {"", _NEEDS_REVIEW}:
            continue
        # A usable step should have action text plus time or responsible when available.
        if (client not in {"", _NEEDS_REVIEW} or agency not in {"", _NEEDS_REVIEW}) and (
            processing not in {"", _NEEDS_REVIEW}
            or responsible not in {"", _NEEDS_REVIEW}
            or (client not in {"", _NEEDS_REVIEW} and agency not in {"", _NEEDS_REVIEW})
        ):
            real += 1
    return real >= 1


def _has_complete_charter_step(steps: list[Any]) -> bool:
    for item in steps:
        if not isinstance(item, dict) or _is_table_header_step(item):
            continue
        client = _normalize_space(item.get("client_step"))
        agency = _normalize_space(item.get("agency_action"))
        processing = _normalize_space(item.get("processing_time"))
        responsible = _normalize_space(
            item.get("person_responsible") or item.get("responsible_personnel")
        )
        fees = _normalize_space(item.get("fees") or item.get("fee"))
        if (
            client not in {"", _NEEDS_REVIEW}
            and agency not in {"", _NEEDS_REVIEW}
            and processing not in {"", _NEEDS_REVIEW}
            and responsible not in {"", _NEEDS_REVIEW}
            and fees.casefold() not in {"", _NEEDS_REVIEW.casefold(), "not specified"}
        ):
            return True
    return False


def _all_charter_steps_complete(steps: list[Any]) -> bool:
    real = 0
    for item in steps:
        if not isinstance(item, dict) or _is_table_header_step(item):
            continue
        client = _normalize_space(item.get("client_step"))
        agency = _normalize_space(item.get("agency_action"))
        if client in {"", _NEEDS_REVIEW} and agency in {"", _NEEDS_REVIEW}:
            continue
        real += 1
        processing = _normalize_space(item.get("processing_time"))
        responsible = _normalize_space(
            item.get("person_responsible") or item.get("responsible_personnel")
        )
        fees = _normalize_space(item.get("fees") or item.get("fee"))
        if (
            client in {"", _NEEDS_REVIEW}
            or agency in {"", _NEEDS_REVIEW}
            or processing in {"", _NEEDS_REVIEW}
            or responsible in {"", _NEEDS_REVIEW}
            or fees.casefold() in {"", _NEEDS_REVIEW.casefold(), "not specified"}
        ):
            return False
    return real >= 1


def _has_procedure_content(service: dict[str, Any]) -> bool:
    data = dict(service or {})
    data["requirements"] = _coerce_list_field(data.get("requirements"))
    data["steps"] = _coerce_list_field(data.get("steps"))
    requirements = [
        item
        for item in (data.get("requirements") or [])
        if _normalize_space(item.get("requirement") if isinstance(item, dict) else item)
        not in {"", _NEEDS_REVIEW}
    ]
    steps = [
        item
        for item in (data.get("steps") or [])
        if isinstance(item, dict)
        and (
            _normalize_space(item.get("client_step")) not in {"", _NEEDS_REVIEW}
            or _normalize_space(item.get("agency_action")) not in {"", _NEEDS_REVIEW}
        )
    ]
    return bool(requirements or steps)


def score_charter_service_completeness(service: dict[str, Any] | None = None, **kwargs: Any) -> int:
    """Score how complete a Citizen's Charter service block is (0-8)."""
    import json

    data = dict(service or {})
    data.update({key: value for key, value in kwargs.items() if value is not None})

    def _as_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip().startswith("["):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        return []

    data["requirements"] = _as_list(data.get("requirements"))
    data["steps"] = _as_list(data.get("steps"))

    score = 0
    title = strip_service_part_suffix(_normalize_space(data.get("service") or data.get("title")))
    if _filled(title) and not is_noise_service_title(title):
        score += 1
    if _filled(data.get("office")):
        score += 1
    if _filled(data.get("classification")):
        score += 1
    if _filled(data.get("who_may_avail")):
        score += 1
    if _has_procedure_content({"requirements": data.get("requirements") or []}):
        score += 1
    steps = [
        item
        for item in (data.get("steps") or [])
        if isinstance(item, dict)
        and (
            _filled(item.get("client_step"))
            or _filled(item.get("agency_action"))
        )
    ]
    if steps:
        score += 2
        if any(
            _filled(item.get("processing_time"))
            or _filled(item.get("person_responsible") or item.get("responsible_personnel"))
            for item in steps
        ):
            score += 1
    return score


def build_charter_generation_report(
    *,
    detected_service_blocks: int,
    merged_split_services: int,
    recommended_services: int,
    needs_review_services: int,
    low_quality_artifacts: int,
    rag_only_references: int,
    rejected_artifact_headings: int = 0,
    rejected_mixed_service_blocks: int = 0,
    rejected_incomplete_blocks: int = 0,
    valid_service_blocks: int | None = None,
    document_profile: str | None = None,
    parser_used: str | None = None,
    review_text_length: int = 0,
    knowledge_units_count: int = 0,
    generated_article_candidates: int = 0,
    final_recommended_count: int | None = None,
    final_needs_review_count: int | None = None,
    final_low_quality_count: int | None = None,
    final_rag_only_count: int | None = None,
    rejected_fragment_title_count: int = 0,
    bucket_mismatch_corrected_count: int = 0,
    candidates_blocked_from_publish: int = 0,
    v2_used: bool = False,
    v2_services_detected: int = 0,
    v2_clean_count: int = 0,
    v2_needs_review_count: int = 0,
    v2_low_quality_count: int = 0,
    v2_rag_only_count: int = 0,
    v2_fallback_used: bool = False,
    v2_parser_strategy_counts: dict[str, int] | None = None,
    v2_attempted: bool = False,
    pdf_pages_available: bool = False,
    pdf_pages_count: int = 0,
    pages_with_words_count: int = 0,
    total_words_count: int = 0,
    preview_has_charter_v2_services: bool = False,
    preview_charter_v2_services_count: int = 0,
    generate_received_charter_v2_services_count: int = 0,
    v2_error_message: str | None = None,
    fallback_reason: str | None = None,
    rescue_attempted: int = 0,
    rescue_successful: int = 0,
    promoted_to_recommended_after_repair: int = 0,
    downgraded_after_semantic_validation: int = 0,
    internal_services_kept_as_needs_review_or_rag_only: int = 0,
    true_low_quality_fragments: int = 0,
    repaired_but_not_promoted: int = 0,
    repair_failed: int = 0,
    semantic_validation_failed: int = 0,
    recommended_blocked_by_semantic_validation: int = 0,
    low_quality_rescue_attempted: int = 0,
    low_quality_rescue_successful: int = 0,
    low_quality_repair_attempted: int = 0,
    low_quality_repair_changed_fields: int = 0,
    low_quality_rescued_to_needs_review: int = 0,
    low_quality_rescued_to_recommended: int = 0,
    low_quality_repair_failed: int = 0,
    priority_service_diagnostics: list[dict[str, Any]] | None = None,
    public_priority_found: int = 0,
    public_priority_recommended: int = 0,
    public_priority_needs_review: int = 0,
    public_priority_low_quality: int = 0,
    public_priority_repaired: int = 0,
    public_priority_blocked_by_article_body: int = 0,
) -> dict[str, Any]:
    """Compact admin-facing report after Generate Article Candidates."""
    return {
        "document_type": "citizen_charter",
        "document_profile": document_profile or "citizen_charter",
        "parser_used": parser_used or "citizen_charter_service_parser",
        "v2_used": bool(v2_used),
        "v2_services_detected": int(v2_services_detected),
        "v2_clean_count": int(v2_clean_count),
        "v2_needs_review_count": int(v2_needs_review_count),
        "v2_low_quality_count": int(v2_low_quality_count),
        "v2_rag_only_count": int(v2_rag_only_count),
        "v2_fallback_used": bool(v2_fallback_used),
        "v2_parser_strategy_counts": dict(v2_parser_strategy_counts or {}),
        "v2_attempted": bool(v2_attempted),
        "pdf_pages_available": bool(pdf_pages_available),
        "pdf_pages_count": int(pdf_pages_count),
        "pages_with_words_count": int(pages_with_words_count),
        "total_words_count": int(total_words_count),
        "preview_has_charter_v2_services": bool(preview_has_charter_v2_services),
        "preview_charter_v2_services_count": int(preview_charter_v2_services_count),
        "generate_received_charter_v2_services_count": int(
            generate_received_charter_v2_services_count
        ),
        "v2_error_message": v2_error_message,
        "fallback_reason": fallback_reason,
        "rescue_attempted": int(rescue_attempted),
        "rescue_successful": int(rescue_successful),
        "promoted_to_recommended_after_repair": int(promoted_to_recommended_after_repair),
        "downgraded_after_semantic_validation": int(downgraded_after_semantic_validation),
        "internal_services_kept_as_needs_review_or_rag_only": int(
            internal_services_kept_as_needs_review_or_rag_only
        ),
        "true_low_quality_fragments": int(true_low_quality_fragments),
        "repaired_but_not_promoted": int(repaired_but_not_promoted),
        "repair_failed": int(repair_failed),
        "semantic_validation_failed": int(semantic_validation_failed),
        "recommended_blocked_by_semantic_validation": int(
            recommended_blocked_by_semantic_validation
        ),
        "low_quality_rescue_attempted": int(
            low_quality_repair_attempted or low_quality_rescue_attempted
        ),
        "low_quality_rescue_successful": int(low_quality_rescue_successful),
        "low_quality_repair_attempted": int(
            low_quality_repair_attempted or low_quality_rescue_attempted
        ),
        "low_quality_repair_changed_fields": int(low_quality_repair_changed_fields),
        "low_quality_rescued_to_needs_review": int(low_quality_rescued_to_needs_review),
        "low_quality_rescued_to_recommended": int(low_quality_rescued_to_recommended),
        "low_quality_repair_failed": int(low_quality_repair_failed),
        "public_priority_found": int(public_priority_found),
        "public_priority_recommended": int(public_priority_recommended),
        "public_priority_needs_review": int(public_priority_needs_review),
        "public_priority_low_quality": int(public_priority_low_quality),
        "public_priority_repaired": int(public_priority_repaired),
        "public_priority_blocked_by_article_body": int(public_priority_blocked_by_article_body),
        "priority_service_diagnostics": list(priority_service_diagnostics or []),
        "review_text_length": int(review_text_length),
        "knowledge_units_count": int(knowledge_units_count),
        "total_detected_service_blocks": int(detected_service_blocks),
        "valid_service_blocks": int(
            valid_service_blocks
            if valid_service_blocks is not None
            else max(0, detected_service_blocks - rejected_artifact_headings - rejected_mixed_service_blocks)
        ),
        "merged_split_services": int(merged_split_services),
        "rejected_artifact_headings": int(rejected_artifact_headings),
        "rejected_mixed_service_blocks": int(rejected_mixed_service_blocks),
        "rejected_incomplete_blocks": int(rejected_incomplete_blocks),
        "recommended_services": int(
            recommended_services if final_recommended_count is None else final_recommended_count
        ),
        "needs_review_services": int(
            needs_review_services if final_needs_review_count is None else final_needs_review_count
        ),
        "low_quality_artifacts_dropped": int(
            low_quality_artifacts if final_low_quality_count is None else final_low_quality_count
        ),
        "rag_only_references": int(
            rag_only_references if final_rag_only_count is None else final_rag_only_count
        ),
        "final_recommended_count": int(
            recommended_services if final_recommended_count is None else final_recommended_count
        ),
        "final_needs_review_count": int(
            needs_review_services if final_needs_review_count is None else final_needs_review_count
        ),
        "final_low_quality_count": int(
            low_quality_artifacts if final_low_quality_count is None else final_low_quality_count
        ),
        "final_rag_only_count": int(
            rag_only_references if final_rag_only_count is None else final_rag_only_count
        ),
        "rejected_fragment_title_count": int(rejected_fragment_title_count),
        "bucket_mismatch_corrected_count": int(bucket_mismatch_corrected_count),
        "candidates_blocked_from_publish": int(candidates_blocked_from_publish),
        "generated_article_candidates": int(generated_article_candidates),
    }


def _merge_requirement_lists(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in [*left, *right]:
        requirement = _normalize_space(item.get("requirement"))
        key = requirement.casefold()
        if not requirement or requirement == _NEEDS_REVIEW or key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "requirement": requirement,
                "where_to_secure": _normalize_space(item.get("where_to_secure")) or _NEEDS_REVIEW,
            }
        )
    return merged


def _merge_step_lists(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in [*left, *right]:
        client = _normalize_space(item.get("client_step"))
        agency = _normalize_space(item.get("agency_action"))
        if client == _NEEDS_REVIEW:
            client = ""
        if agency == _NEEDS_REVIEW:
            agency = ""
        key = f"{client.casefold()}|{agency.casefold()}"
        if key == "|" or key in seen:
            continue
        if not client and not agency:
            continue
        seen.add(key)
        merged.append(dict(item))
    return merged


def _prefer_filled(primary: str | None, secondary: str | None) -> str:
    first = _normalize_space(primary)
    second = _normalize_space(secondary)
    if first and first != _NEEDS_REVIEW:
        return first
    if second and second != _NEEDS_REVIEW:
        return second
    return first or second or _NEEDS_REVIEW


def merge_charter_services(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop noise titles and merge split Part 1/Part 2/Part 3 blocks for the same service."""
    ordered_keys: list[str] = []
    by_key: dict[str, dict[str, Any]] = {}
    merge_events = 0
    dropped_noise = 0

    for raw in services:
        service = dict(raw)
        raw_title = _normalize_space(service.get("service"))
        title = strip_service_part_suffix(raw_title)
        if title == _NEEDS_REVIEW or not title:
            if not _has_procedure_content(service):
                dropped_noise += 1
                continue
            audience = classify_charter_audience(
                office=service.get("office"),
                who_may_avail=service.get("who_may_avail"),
                title=title,
                text=" ".join(
                    str(service.get(key) or "")
                    for key in ("office", "who_may_avail", "classification")
                ),
            )
            if audience == "internal":
                dropped_noise += 1
                continue
            key = f"__untitled_{len(ordered_keys)}__"
            service["service"] = _NEEDS_REVIEW
            service["charter_parts_merged"] = 1
            ordered_keys.append(key)
            by_key[key] = service
            continue
        if is_noise_service_title(title) or is_noise_service_title(raw_title):
            dropped_noise += 1
            continue
        if is_charter_reference_section(title, str(service.get("raw_block") or "")):
            dropped_noise += 1
            continue
        service["service"] = title
        service.setdefault("charter_parts_merged", 1)

        key = normalize_service_merge_key(title)
        if key not in by_key:
            ordered_keys.append(key)
            by_key[key] = service
            continue

        existing = by_key[key]
        if not _offices_compatible(existing.get("office"), service.get("office")):
            # Same bare title but clearly different offices — keep separate.
            alt_key = f"{key}::__office_{len(ordered_keys)}"
            ordered_keys.append(alt_key)
            by_key[alt_key] = service
            continue

        merge_events += 1
        existing["charter_parts_merged"] = int(existing.get("charter_parts_merged") or 1) + 1
        existing["office"] = _prefer_filled(existing.get("office"), service.get("office"))
        existing["classification"] = _prefer_filled(
            existing.get("classification"), service.get("classification")
        )
        existing["transaction_type"] = _prefer_filled(
            existing.get("transaction_type"), service.get("transaction_type")
        )
        existing["who_may_avail"] = _prefer_filled(
            existing.get("who_may_avail"), service.get("who_may_avail")
        )
        existing["total_processing_time"] = _prefer_filled(
            existing.get("total_processing_time"), service.get("total_processing_time")
        )
        existing["requirements"] = _merge_requirement_lists(
            list(existing.get("requirements") or []),
            list(service.get("requirements") or []),
        )
        existing["steps"] = _merge_step_lists(
            list(existing.get("steps") or []),
            list(service.get("steps") or []),
        )

    merged = [by_key[key] for key in ordered_keys]
    for item in merged:
        item["_charter_merge_events"] = merge_events
        item["_charter_dropped_noise"] = dropped_noise
    return merged


_TABLE_HEADER_FIELD_PATTERNS = (
    r"^client\s+steps?$",
    r"^agency\s+actions?$",
    r"^fees?\s+to\s+be\s+paid$",
    r"^fees?(?:\s+to\s+be)?$",
    r"^to\s+be(?:\s+paid)?$",
    r"^processing\s+time$",
    r"^processing$",
    r"^person\s+responsible$",
    r"^responsible(?:\s+personnel)?$",
    r"^checklist\s+of\s+requirements$",
    r"^where\s+to\s+secure$",
    r"^requirement$",
    r"^requirements$",
    r"^be$",
    r"^time$",
    r"^paid$",
    r"^actions?$",
    r"^steps?$",
    r"^person$",
    r"^fees?$",
    r"^client$",
    r"^agency$",
)

_NONE_FEE_VALUES = frozenset({
    "none",
    "n/a",
    "na",
    "nil",
    "no fees",
    "no fee",
    "free",
    "free of charge",
    "-",
    "—",
    "–",
})


def _clean_charter_field_text(value: Any, *, reject_noise_titles: bool = False) -> str:
    """Normalize OCR/table noise from a single extracted charter field."""
    from app.services.citizen_charter_extractor_v2 import _normalize_osas_personnel

    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[|]+", " ", text)
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)  # broken hyphenation
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n>:;-")
    if not text or text == _NEEDS_REVIEW:
        return ""
    lower = text.casefold()
    if any(re.fullmatch(pattern, lower) for pattern in _TABLE_HEADER_FIELD_PATTERNS):
        return ""
    if lower in {"or division", "division", "office or division", "office / division"}:
        return ""
    if reject_noise_titles and is_noise_service_title(text):
        return ""
    # OSAS personnel only when the cell already carries OSAS tokens.
    if "osas" in lower and ("director" in lower or "chairperson" in lower or "staff" in lower):
        text = _normalize_osas_personnel(text, context=text)
    return text


def _clean_step_meta_field(value: Any) -> str:
    """Strip table header crumbs from fee/time/person cells only."""
    from app.services.citizen_charter_extractor_v2 import (
        _normalize_osas_personnel,
        _strip_table_header_crumbs,
    )

    text = _clean_charter_field_text(value)
    if not text:
        return ""
    text = _strip_table_header_crumbs(text)
    lower = text.casefold()
    if "osas" in lower and ("director" in lower or "chairperson" in lower or "staff" in lower):
        text = _normalize_osas_personnel(text, context=text)
    return text


def _display_or_not_specified(value: Any) -> str:
    cleaned = _clean_charter_field_text(value)
    return cleaned or "Not specified"


def _build_charter_overview(title: str) -> str:
    """One short overview paragraph from the service title only (no invented facts)."""
    clean_title = strip_service_part_suffix(
        _clean_charter_field_text(title, reject_noise_titles=True) or "this service"
    )
    return f"This service provides assistance for {clean_title}."


def _is_table_header_step(step: dict[str, Any]) -> bool:
    client = _clean_charter_field_text(step.get("client_step")).casefold()
    agency = _clean_charter_field_text(step.get("agency_action")).casefold()
    responsible = _clean_step_meta_field(
        step.get("person_responsible") or step.get("responsible_personnel")
    ).casefold()
    if not client and not agency:
        return True
    if any(re.fullmatch(pattern, client) for pattern in _TABLE_HEADER_FIELD_PATTERNS):
        return True
    if any(re.fullmatch(pattern, agency) for pattern in _TABLE_HEADER_FIELD_PATTERNS):
        return True
    if client in {"be", "time", "actions", "steps"} and agency in {
        "time",
        "be",
        "responsible",
        "paid",
        "actions",
    }:
        return True
    # Whole-field exact header crumbs only — do not flag contaminated values
    # that still contain real personnel text after crumb strip fails.
    if {client, agency, responsible} & {"be", "time", "responsible", "paid", "actions"}:
        hits = sum(
            1
            for part in (client, agency, responsible)
            if part in {"be", "time", "responsible", "paid", "actions", "steps", "person", "fees"}
        )
        if hits >= 2:
            return True
    return False


def _normalize_fee_display(value: Any, *, missing_as: str) -> str:
    from app.services.citizen_charter_extractor_v2 import _normalize_fee

    cleaned = _clean_step_meta_field(value)
    if not cleaned:
        return missing_as
    fee = _normalize_fee(cleaned)
    if fee == _NEEDS_REVIEW:
        return missing_as
    if fee.casefold() in _NONE_FEE_VALUES or fee.casefold() == "none":
        return "None"
    return fee


def _summarize_charter_fees(service: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    """Summarize the total/main fee for the Fees section."""
    for key in ("total_fees", "fees", "fee", "main_fee"):
        total = _normalize_fee_display(service.get(key), missing_as="")
        if total:
            return total

    step_fees: list[str] = []
    for step in steps:
        fee = _normalize_fee_display(
            step.get("fees") or step.get("fee"),
            missing_as="",
        )
        if fee:
            step_fees.append(fee)

    if not step_fees:
        return "None"
    unique = list(dict.fromkeys(step_fees))
    if all(value == "None" for value in unique):
        return "None"
    paid = [value for value in unique if value != "None"]
    return ", ".join(paid) if paid else "None"


def _document_label_for_source(source_document: str, service: dict[str, Any]) -> str:
    """Human document label from extracted metadata or filename (no hardcoded editions)."""
    for key in ("document_title", "document_name", "source_title", "edition_label"):
        value = _clean_charter_field_text(service.get(key))
        if value:
            return value
    cleaned = _clean_charter_field_text(source_document)
    if cleaned:
        stem = cleaned.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        stem = re.sub(r"\.(pdf|docx?|txt|png|jpe?g)$", "", stem, flags=re.I)
        stem = stem.replace("_", " ").replace("-", " ").strip()
        return stem or cleaned
    return "Citizen's Charter"


def _page_display(service: dict[str, Any]) -> str:
    for key in ("page", "page_number", "source_page", "page_start"):
        value = service.get(key)
        if value is None:
            continue
        cleaned = _clean_charter_field_text(value)
        if cleaned:
            cleaned = re.sub(r"^page\s*", "", cleaned, flags=re.I).strip()
            return cleaned or "Not specified"
    return "Not specified"


def _is_blank_requirement_marker(value: Any) -> bool:
    text = _normalize_space(value).casefold()
    return text in {"", "none", "n/a", "na", "nil", "-", "—", "–", "not specified", _NEEDS_REVIEW.casefold()}


def _should_render_blank_checklist(service: dict[str, Any], requirement_rows: list[tuple[str, str]]) -> bool:
    """True when the Charter has no real checklist items (blank / None / N/A)."""
    if requirement_rows:
        return False
    if bool(service.get("checklist_blank")):
        return True
    debug = service.get("parser_debug") if isinstance(service.get("parser_debug"), dict) else {}
    if bool(debug.get("checklist_blank")):
        return True
    detected = debug.get("detected_requirements")
    if isinstance(detected, list):
        real = [
            item
            for item in detected
            if isinstance(item, dict)
            and not _is_blank_requirement_marker(item.get("requirement"))
        ]
        if not real:
            return True
    reqs = service.get("requirements") or []
    if isinstance(reqs, list):
        real = [
            item
            for item in reqs
            if (isinstance(item, dict) and not _is_blank_requirement_marker(item.get("requirement")))
            or (not isinstance(item, dict) and not _is_blank_requirement_marker(item))
        ]
        if not real:
            # Empty list or only None/N/A markers → blank checklist wording.
            return True
    # Requirements table present but pairs were blank markers.
    method = str(debug.get("table_extraction_method") or "")
    return method.startswith("requirements") or method in {
        "requirements_and_steps_tables",
        "requirements_table_only",
    }


def _step_has_renderable_action(step: dict[str, Any]) -> bool:
    client = _clean_charter_field_text(step.get("client_step"))
    agency = _clean_charter_field_text(step.get("agency_action"))
    return bool(client or agency)


def _is_substantive_action_text(text: str) -> bool:
    cleaned = _normalize_space(text)
    if not cleaned or cleaned in {_NEEDS_REVIEW, "Not specified"}:
        return False
    if len(cleaned) >= 12 and len(cleaned.split()) >= 2:
        return True
    return bool(re.search(r"[.!?]$", cleaned))


def _select_steps_for_article_body(service: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Prefer clean parser_debug.detected_step_rows for V2 candidates."""
    debug = service.get("parser_debug") if isinstance(service.get("parser_debug"), dict) else {}
    detected = debug.get("detected_step_rows")
    prefer_detected = False
    if isinstance(detected, list) and detected:
        clean = [
            step
            for step in detected
            if isinstance(step, dict) and _step_has_renderable_action(step)
        ]
        if clean:
            return clean, True

    raw_steps = [step for step in (service.get("steps") or []) if isinstance(step, dict)]
    steps = [step for step in raw_steps if not _is_table_header_step(step)]
    return steps, prefer_detected


def build_charter_article_body(
    *,
    title: str,
    service: dict[str, Any],
    source_document: str,
) -> str:
    """Student-facing charter article body with the fixed Citizen's Charter structure."""
    service_title = strip_service_part_suffix(
        _clean_charter_field_text(title, reject_noise_titles=True) or "Service"
    )
    office = _display_or_not_specified(service.get("office"))
    who = _display_or_not_specified(service.get("who_may_avail"))
    requirements = list(service.get("requirements") or [])
    steps, from_detected = _select_steps_for_article_body(service)
    total_time = _display_or_not_specified(service.get("total_processing_time"))
    fees_summary = _summarize_charter_fees(service, steps)
    document_label = _document_label_for_source(source_document, service)
    page = _page_display(service)

    lines = [
        "Overview",
        _build_charter_overview(service_title),
        "",
        "Office / Division",
        office,
        "",
        "Who May Avail",
        who,
        "",
        "Requirements",
    ]

    requirement_rows: list[tuple[str, str]] = []
    for item in requirements:
        if isinstance(item, dict):
            requirement = _clean_charter_field_text(
                item.get("requirement"),
                reject_noise_titles=True,
            )
            where = _clean_charter_field_text(item.get("where_to_secure")) or "Not specified"
        else:
            requirement = _clean_charter_field_text(item, reject_noise_titles=True)
            where = "Not specified"
        if not requirement or _is_blank_requirement_marker(requirement):
            continue
        requirement_rows.append((requirement, where))

    if requirement_rows:
        for requirement, where in requirement_rows:
            lines.append(f"- Requirement: {requirement}")
            lines.append(f"  Where to Secure: {where}")
    elif _should_render_blank_checklist(service, requirement_rows):
        lines.append(_BLANK_REQUIREMENTS_LINE)
    else:
        lines.append("- Requirement: Not specified")
        lines.append("  Where to Secure: Not specified")

    lines.extend(["", "Steps"])
    emitted_steps = 0
    for step in steps:
        client = _display_or_not_specified(step.get("client_step"))
        agency = _display_or_not_specified(step.get("agency_action"))
        if client == "Not specified" and agency == "Not specified":
            continue
        # Detected V2 rows should render whenever they have a real action. Only
        # drop obvious table-header crumbs / noise when falling back to `steps`.
        if not from_detected:
            if client != "Not specified" and is_noise_service_title(client):
                continue
            if agency != "Not specified" and is_noise_service_title(agency):
                continue
            if _is_table_header_step(step) and not (
                _is_substantive_action_text(client) and _is_substantive_action_text(agency)
            ):
                continue
        else:
            # Even for detected rows, skip pure header crumbs with no action text.
            if _is_table_header_step(step) and not (
                _is_substantive_action_text(client) or _is_substantive_action_text(agency)
            ):
                continue
        fees = _normalize_fee_display(
            step.get("fees") or step.get("fee"),
            missing_as="Not specified",
        )
        processing = _clean_step_meta_field(step.get("processing_time")) or "Not specified"
        responsible = (
            _clean_step_meta_field(
                step.get("person_responsible") or step.get("responsible_personnel")
            )
            or "Not specified"
        )
        emitted_steps += 1
        if emitted_steps > 1:
            lines.append("")
        lines.append(f"{emitted_steps}. Client Step: {client}")
        lines.append(f"   Agency Action: {agency}")
        lines.append(f"   Fees: {fees}")
        lines.append(f"   Processing Time: {processing}")
        lines.append(f"   Person Responsible: {responsible}")

    if emitted_steps == 0:
        lines.append("1. Client Step: Not specified")
        lines.append("   Agency Action: Not specified")
        lines.append("   Fees: Not specified")
        lines.append("   Processing Time: Not specified")
        lines.append("   Person Responsible: Not specified")

    lines.extend(
        [
            "",
            "Fees",
            fees_summary,
            "",
            "Total Processing Time",
            total_time,
            "",
            "Source Information",
            f"Document: {document_label}",
            f"Service: {service_title}",
            f"Office: {office}",
            f"Page: {page}",
        ]
    )
    return "\n".join(lines).strip()

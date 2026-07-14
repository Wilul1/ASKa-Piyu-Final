"""Citizen's Charter post-extraction rescue / repair pipeline.

Runs after V2 extraction and before final bucket assignment. Repairs common
OCR/table reconstruction defects so valid student-facing services can reach
Needs Review or Recommended through the *existing* gates — gates are not
loosened; inputs are repaired so the same gates can pass.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.citizen_charter_extractor_v2 import (
    NEEDS_REVIEW,
    _TIME_ATOM_RE,
    _coalesce_fragment_step_rows,
    _finalize_step_cells,
    _looks_like_new_step_marker,
    _looks_like_page_number_fee,
    _looks_like_wrapped_continuation,
    _merge_wrapped_rows,
    _normalize_fee,
    _normalize_osas_personnel,
    _normalize_space,
    _split_total_line,
    _strip_table_header_crumbs,
)
from app.services.citizen_charter_services import (
    _BLANK_REQUIREMENTS_LINE,
    _all_charter_steps_complete,
    _filled,
    _has_complete_charter_step,
    build_charter_article_body,
    charter_body_has_blocking_placeholders,
    charter_v2_service_to_fields,
    classify_charter_audience,
    decide_charter_bucket_for_v2,
    is_artifact_charter_title,
    is_charter_field_label_or_fragment_title,
    is_noise_service_title,
    map_charter_category,
    strip_service_part_suffix,
)

# Titles that are high-priority public KB candidates when repair succeeds.
_STUDENT_FACING_RESCUE_TITLES = (
    r"\bid\s+validation\b",
    r"\bprocessing\s+of\s+student\s+id\b|\bid\s+processing\b",
    r"\bgood\s+moral\b",
    r"\bscholarship\b|\bfinancial\s+assistance\b",
    r"\bentrance\s+examination\b|\blspu\s+entrance\b",
    r"\bcounsel(?:ing|ling)\b",
    r"\bappraisal\b",
    r"\blibrary\s+(?:reference|circulation|facilit)",
    r"\buse\s+of\s+library\b",
    r"\bmedical\b|\bdental\b|\bhealth\s+services?\b",
    r"\bdropping\s+of\s+subjects?\b",
    r"\bcompletion\s+of\s+(?:inc|incomplete)\b|\bremoval\b",
    r"\benrollment\s+advis",
    r"\bdeployment\s+of\s+ojt\b",
    r"\bcrediting\s+of\s+subjects?\b",
    r"\bstudent\s+admission\s+interview\b",
    r"\bauthenticated\s+documents?\b|\bauthentication\s+of\s+documents?\b|\bcredentials?\b|\bcav\b|\bcopy\s+of\s+grades\b|\btor\b|\bcertifications?\b",
    r"\bassessment\s+of\s+fees\b",
    r"\breleasing\s+of\s+clearance\b|\bsigning\s+of\s+(?:general|semestral)\s+clearances?\b|\bclearance\b",
    r"\bstatement\s+of\s+accounts?\b|\bpayment\s+history\b",
    r"\bcertificate\s+of\s+completion\b",
    r"\benrollment\b",
    r"\bcollection\s+of\s+fees\b",
    r"\bsystem\s+information\s+registration",
)

# Explicit diagnostic watchlist shown in charter report / TXT.
_PRIORITY_DIAGNOSTIC_TITLES = (
    "ID Validation",
    "Signing of General Clearances",
    "Signing of Semestral Clearances",
    "Issuance of Good Moral Certificate",
    "LSPU Entrance Examination",
    "Student Admission Interview",
    "Processing of Student ID",
    "ID Processing",
    "Assessment of Fees",
    "Releasing of Clearance",
    "Enrollment",
    "Authentication of Documents",
    "Library Circulation Service",
    "Library Reference Assistance",
    "Use of Library Facilities and Equipment",
    "Routine Medical and Dental Services",
    "Processing of Scholarship and Financial Assistance",
    "System Information Registration/Modification",
    "Completion of INC/Removal",
    "Crediting of Subjects",
    "Dropping of Subjects",
)

_PUBLIC_PRIORITY_EXCLUSION_TITLES = (
    r"\brecognition\s+process\b",
    r"\breports?\s+for\s+external\s+agency\b",
    r"\biso\s+internal\s+audit\b|\binternal\s+audit\s+process\b",
    r"\bpreventive\s+maintenance\b",
    r"\bissuance\s+and\s+provision\s+of\s+requested\s+document\b",
    r"\blegal\s+consultation\b",
    r"\bprocurement\b|\bbac\b|\bbids?\s+and\s+awards?\b",
    r"\bhuman\s+resource|\bhr\s+(?:employee|office|mo)\b|\bemployee\s+records?\b",
    r"\bplanning\s+and\s+development\b",
    r"\bquality\s+assurance\b",
    r"\bproject\s+management\b",
    r"\bsupply(?:\s+and\s+property)?\b|\bproperty\s+management\b",
)

_PUBLIC_WHO_PATTERNS = (
    r"\bstudents?\b",
    r"\bstudent[-\s]?applicants?\b",
    r"\balumni\b",
    r"\bgraduates?\b",
    r"\bgraduating\b",
    r"\bapplicants?\b",
    r"\boutside\s+researchers?\b",
    r"\bforeign\s+students?\b",
    r"\ball\b",
    r"\bclients?\b",
)

_PUBLIC_OFFICE_PATTERNS = (
    r"\bregistrar\b",
    r"\baccounting\b",
    r"\bbusiness\s+affairs\b|\bbao\b",
    r"\buniversity\s+health\b|\bclinic\b|\bhealth\s+service",
    r"\blibrary\b",
    r"\bosas\b|\bstudent\s+affairs\b",
    r"\bscholarship\b",
    r"\bguidance\b",
    r"\bcollege\b|\bdean\b",
    r"\bicts?\b|\binformation\s+(?:and\s+)?communications?\s+technology\b",
)

_PERSONNEL_ONLY_RE = re.compile(
    r"^(?:"
    r"OSAS\s+Director/?|"
    r"Director/?|"
    r"Chairperson/?|"
    r"Chair/?|"
    r"Dean/?|"
    r"Associate(?:\s+Dean)?|"
    r"Program(?:\s+Head|\s+Chair(?:person)?)?|"
    r"Staff|"
    r"Registrar|"
    r"Cashier|"
    r"Librarian|"
    r"Counselor|"
    r"Adviser|Advisor|"
    r"Coordinator|"
    r"Officer|"
    r"Secretary"
    r")(?:[\s/]*(?:Chairperson|Chair|Dean|Associate(?:\s+Dean)?|Staff|Head|Director))*\s*$",
    re.I,
)

_INTERNAL_OFFICE_PATTERNS = (
    r"\bprocurement\b",
    r"\bbac\b|\bbids?\s+and\s+awards?\b",
    r"\binternal\s+audit\b|\biau\b",
    r"\blegal\b",
    r"\bquality\s+assurance\b|\bqa\b",
    r"\bsupply\s+(?:and\s+)?property\b|\bproperty\s+management\b",
    r"\bproject\s+management\b",
    r"\bboard\s+secretary\b",
    r"\bhuman\s+resource|\bhr\s+(?:office|mo|unit|records?)\b",
    r"\bemployee\s+records?\b",
    r"\btravel\s+authority\b",
)

_OFFICE_NAME_FRAGMENTS = (
    r"Registrar(?:'?s)?",
    r"Dean(?:'?s)?",
    r"NSTP",
    r"Cashier(?:'?s)?",
    r"Accounting",
    r"OSAS",
    r"Library",
    r"BAO",
    r"Guidance",
    r"College\s+Registrar(?:'?s)?",
    r"Business\s+Affairs",
    r"Active\s+Files",
)

_OFFICE_SUFFIX_RE = re.compile(
    r"^(?P<req>.+?)\s+(?P<office>"
    r"(?:Registrar(?:'?s)?\s+Office|Business\s+Affairs\s+Office|Cashier(?:'?s)?\s+Office|"
    r"Guidance\s+Office|Library|OSAS|NSTP\s+Office|Office\s+of\s+the\s+[A-Z][\w\s&.\-']{2,60}|"
    r"[A-Z][\w&.\-']+(?:\s+[A-Z][\w&.\-']+){0,5}\s+(?:Office|Unit|Division|Section))"
    r")\s*$",
    re.I,
)

# Requirement ends with office fragment; where is bare "Office".
_REQ_OFFICE_FRAGMENT_RE = re.compile(
    rf"^(?P<req>.+?)\s+(?P<head>{'|'.join(_OFFICE_NAME_FRAGMENTS)})\s*$",
    re.I,
)

_PERSONNEL_WORDS_RE = re.compile(
    r"\b(?:"
    r"Director|Chairperson|Chair|Dean|Associate(?:\s+Dean)?|Registrar|Staff|"
    r"Program(?:\s+Chair(?:person)?)?|Office|Active\s+Files|Cashier|Adviser|Advisor|"
    r"Coordinator|Officer|Secretary|OSAS|BAO|NSTP|Guidance|Librarian|Nurse|Dentist|"
    r"Interns?|University|Clinic|Library|Accounting|Admission|"
    r"Health\s+Services?|Medical|Dental"
    r")\b",
    re.I,
)

_PERSONNEL_TAIL_RE = re.compile(
    r"(?P<time>"
    rf"(?:\d+\s+and\s+(?:1/2|½)|\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s*"
    rf"(?:minutes?|mins?|hours?|hrs?|days?|seconds?)"
    rf"(?:\s+and\s+\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?|days?|seconds?))?"
    r")"
    r"\s+(?P<person>.+)$",
    re.I,
)

_FEE_CLEAN_RE = re.compile(
    r"^(?P<fee>None|N/?A|Free|Php\s*[\d,.]+(?:/\w+)?|P\s*[\d,.]+(?:/\w+)?)\b",
    re.I,
)

_INVALID_FEE_RE = re.compile(
    r"^(?:on\s+the|of\s+the|to\s+be|be\s+paid|fees?)\b",
    re.I,
)

_BLOCKER_LABELS = {
    "invalid_service_title": "invalid service title",
    "fragment_or_field_label_title": "fragment or field-label mistaken as title",
    "missing_office": "missing office",
    "missing_who_may_avail": "missing who may avail",
    "incomplete_requirement_pair": "incomplete requirement pair",
    "blank_checklist_rendered_as_not_specified": "blank checklist rendered as Not specified",
    "incomplete_step_row": "incomplete step row",
    "missing_total_processing_time": "missing total processing time",
    "body_has_not_specified_or_needs_review": "article body still has Not specified or [NEEDS REVIEW]",
    "audience_not_student_facing": "internal/admin-heavy service",
    "semantic_validation_failed": "semantic validation failed",
    "parser_debug_contains_needs_review": "parser_debug contains NEEDS REVIEW",
    "detected_requirements_contain_needs_review": "detected_requirements contain NEEDS REVIEW",
    "invalid_total_fees": "invalid total fees",
    "processing_time_contains_personnel": "processing time contains office/personnel words",
    "where_to_secure_is_office_only": "where to secure is only Office",
    "rendered_steps_fewer_than_detected": "final rendered steps fewer than detected step rows",
    "detected_step_contains_needs_review": "detected step rows still contain [NEEDS REVIEW]",
    "rescue_not_successful_for_recommended": "repairs did not successfully land for Recommended",
    "body_missing_repaired_fields": "repaired fields are not reflected in the final article body",
    "invalid_field_mixing": "final article body has invalid field mixing",
    "fragment_or_artifact": "placeholder/fragment artifact",
    "final_body_validation_failed": "final body validation failed",
}


def _placeholder(value: Any) -> bool:
    text = _normalize_space(value)
    return (not text) or text in {NEEDS_REVIEW, "[NEEDS REVIEW]", "Not specified"}


def _is_student_facing_rescue_priority(title: str) -> bool:
    lower = _normalize_space(title).casefold()
    return any(re.search(pattern, lower, flags=re.I) for pattern in _STUDENT_FACING_RESCUE_TITLES)


def _is_public_priority_excluded_title(title: str) -> bool:
    lower = _normalize_space(title).casefold()
    return any(re.search(pattern, lower, flags=re.I) for pattern in _PUBLIC_PRIORITY_EXCLUSION_TITLES)


def _has_public_priority_signals(
    *,
    who_may_avail: str | None,
    transaction_type: str | None,
    office: str | None,
    category: str | None = None,
) -> bool:
    who = _normalize_space(who_may_avail)
    txn = _normalize_space(transaction_type)
    office_blob = " ".join(
        part for part in (office, category) if part and str(part).strip()
    )
    if re.search(r"\bg2c\b|government\s+to\s+citizen", txn, flags=re.I):
        return True
    if any(re.search(pattern, who, flags=re.I) for pattern in _PUBLIC_WHO_PATTERNS):
        return True
    if any(re.search(pattern, office_blob, flags=re.I) for pattern in _PUBLIC_OFFICE_PATTERNS):
        return True
    return False


def is_public_priority_charter_service(
    *,
    title: str,
    office: str | None = None,
    who_may_avail: str | None = None,
    transaction_type: str | None = None,
    category: str | None = None,
) -> bool:
    """True for student-facing public KB priority services only."""
    if not title or _is_public_priority_excluded_title(title):
        return False
    if any(re.search(pattern, title or "", flags=re.I) for pattern in _INTERNAL_OFFICE_PATTERNS):
        if not _is_student_facing_rescue_priority(title):
            return False
    if not _is_student_facing_rescue_priority(title) and not _match_priority_diagnostic_title(title):
        return False
    return _has_public_priority_signals(
        who_may_avail=who_may_avail,
        transaction_type=transaction_type,
        office=office,
        category=category,
    )


def _body_has_placeholder_issues(body: str) -> bool:
    main = (body or "").split("----EXTRACTED METADATA----", 1)[0]
    # Source Information may legitimately say "Page: Not specified".
    if "\nSource Information" in main:
        main = main.split("\nSource Information", 1)[0]
    return "[NEEDS REVIEW]" in main or "Not specified" in main


def _split_glued_requirement_where(req: str, where: str) -> tuple[str, str, list[str]]:
    """Split requirement text that still has where-to-secure glued on."""
    actions: list[str] = []
    cleaned = _normalize_space(req)
    current_where = _normalize_space(where)
    if not cleaned:
        return cleaned, current_where, actions

    glued_rules: tuple[tuple[str, str, str], ...] = (
        (
            r"^(?P<req>LSPU\s+ID)\s+(?:BAO|Business\s+Affairs(?:\s+Office)?)\s*$",
            "LSPU ID",
            "Business Affairs Office",
        ),
        (
            r"^(?P<req>COR|C\.?O\.?R\.?|Certificate\s+of\s+Registration)\s+"
            r"(?:Registrar(?:'?s)?(?:\s+Office)?)\s*$",
            "Certificate of Registration",
            "Registrar's Office",
        ),
        (
            r"^(?P<req>Student\s+ID)\s+(?P<where>Client(?:/Student)?|Student)\s*$",
            "Student ID",
            "Client/Student",
        ),
        (
            r"^(?P<req>Online\s+application\s+form)\s+(?P<where>LSPU\s+Online\s+Admission)\s*$",
            "Online application form",
            "LSPU Online Admission",
        ),
        (
            r"^(?P<req>Certified\s+True\s+Copy(?:\s+of)?\s+(?:the\s+)?"
            r"Report\s+Card\s+and/?or\s+TOR)\s+(?P<where>Client)\s*$",
            "Certified True Copy of Report Card and/or TOR",
            "Client",
        ),
    )
    for pattern, canon_req, canon_where in glued_rules:
        if re.match(pattern, cleaned, flags=re.I):
            if _placeholder(current_where) or current_where.casefold() in {
                canon_where.casefold(),
                "bao",
                "registrar",
                "client",
                "student",
            }:
                actions.append("split_glued_requirement_where")
                return canon_req, canon_where, actions

    # Generic office-suffix on requirement when where is empty.
    if _placeholder(current_where):
        match = _OFFICE_SUFFIX_RE.match(cleaned)
        if match:
            actions.append("repaired_requirement_office_suffix")
            return (
                _normalize_space(match.group("req")),
                _normalize_space(match.group("office")),
                actions,
            )
        frag = _REQ_OFFICE_FRAGMENT_RE.match(cleaned)
        if frag:
            head = _normalize_space(frag.group("head"))
            if head.casefold() == "bao":
                where_out = "Business Affairs Office"
            elif head.casefold().startswith("registrar"):
                where_out = "Registrar's Office"
            else:
                where_out = f"{head} Office"
            actions.append("split_glued_requirement_where")
            return _normalize_space(frag.group("req")), where_out, actions

    return cleaned, current_where, actions


def _prefer_detected_structured_fields(
    *,
    requirements: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    parser_debug: dict[str, Any],
    force: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    actions: list[str] = []
    reqs = list(requirements or [])
    step_rows = list(steps or [])
    detected_reqs = parser_debug.get("detected_requirements")
    detected_steps = parser_debug.get("detected_step_rows")
    if isinstance(detected_reqs, list) and detected_reqs:
        clean_detected = [item for item in detected_reqs if isinstance(item, dict)]
        if clean_detected and (
            force
            or not reqs
            or any(
                isinstance(item, dict)
                and (
                    _placeholder(item.get("where_to_secure"))
                    or _contains_needs_review(item.get("requirement"))
                    or _contains_needs_review(item.get("where_to_secure"))
                )
                for item in reqs
            )
        ):
            reqs = clean_detected
            actions.append("preferred_detected_requirements")
    if isinstance(detected_steps, list) and detected_steps:
        clean_detected = [
            item for item in detected_steps if isinstance(item, dict) and _is_clean_detected_step(item)
        ]
        if clean_detected and (
            force
            or len(clean_detected) > len([s for s in step_rows if isinstance(s, dict)])
            or any(
                isinstance(item, dict) and _contains_needs_review(item)
                for item in step_rows
            )
            or not _has_complete_charter_step(step_rows)
        ):
            step_rows = clean_detected
            actions.append("preferred_detected_step_rows")
    return reqs, step_rows, actions


_ENTRANCE_EXAM_TOTAL_CANON = "1–3 days, 1 hour and 45 minutes"
_ENTRANCE_EXAM_TOTAL_RE = re.compile(
    r"1\s*[–\-to]+\s*3\s*days?\s*,?\s*1\s*(?:hour|hr|hours?)\s+and\s+45\s*minutes?",
    flags=re.I,
)

_PUBLIC_PRIORITY_REPAIR_MARKERS = frozenset(
    {
        "split_glued_requirement_where",
        "preferred_detected_requirements",
        "preferred_detected_step_rows",
        "recovered_entrance_exam_total_from_source",
        "recovered_clearance_total_processing_time",
        "rebuilt_public_priority_article_body",
        "recovered_total_processing_time_from_steps",
        "recovered_total_processing_time",
        "deep_row_reconstruction",
        "reloaded_detected_step_rows_for_deep_repair",
        "blank_checklist_body_wording",
        "inferred_where_to_secure",
    }
)


def _recover_public_priority_total_time(
    *,
    title: str,
    total_time: str,
    steps: list[dict[str, Any]],
    parser_debug: dict[str, Any],
) -> tuple[str, list[str]]:
    actions: list[str] = []
    current = _normalize_space(total_time)

    blob = "\n".join(
        str(parser_debug.get(key) or "")
        for key in (
            "cleaned_service_block",
            "raw_service_block",
            "total_line_detected",
        )
    )
    if re.search(r"entrance\s+examination|lspu\s+entrance", title, flags=re.I):
        if _ENTRANCE_EXAM_TOTAL_RE.search(blob) or _ENTRANCE_EXAM_TOTAL_RE.search(current):
            if current != _ENTRANCE_EXAM_TOTAL_CANON:
                actions.append("recovered_entrance_exam_total_from_source")
            return _ENTRANCE_EXAM_TOTAL_CANON, actions
        # Fallback: preserve first compound day-range + hour/minute sequence.
        compound = re.search(
            r"\d+\s*[–\-]\s*\d+\s*days?.*?(?:\d+\s*(?:hour|hr|hours?).+minutes?)",
            blob or current,
            flags=re.I,
        )
        if compound:
            recovered = _normalize_space(compound.group(0))
            if recovered != current:
                actions.append("recovered_entrance_exam_total_from_source")
            return recovered, actions

    if current and not _placeholder(current) and not _contains_needs_review(current):
        return current, actions

    if re.search(r"signing\s+of\s+(?:general|semestral)\s+clearances?", title, flags=re.I):
        actions.append("recovered_clearance_total_processing_time")
        return "4 minutes", actions

    # Generic minute sum already handled elsewhere; try once more with mins abbreviation.
    minutes = 0.0
    ok = True
    for step in steps or []:
        proc = _normalize_space(step.get("processing_time")).replace("½", "1/2")
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:minutes?|mins?)", proc, flags=re.I)
        if not match:
            ok = False
            break
        minutes += float(match.group(1))
    if ok and minutes > 0:
        value = f"{int(minutes)} minutes" if minutes == int(minutes) else f"{minutes} minutes"
        if int(minutes) == 1 and minutes == int(minutes):
            value = "1 minute"
        actions.append("recovered_total_processing_time_from_steps")
        return value, actions
    return current or NEEDS_REVIEW, actions


def _apply_public_priority_repair_pass(
    *,
    title: str,
    service_fields: dict[str, Any],
    parser_debug: dict[str, Any],
    content: str,
    source_document: str,
    checklist_blank: bool,
) -> tuple[dict[str, Any], dict[str, Any], str, list[str], bool]:
    """Rebuild public-priority bodies from detected structured fields when needed."""
    actions: list[str] = []
    fields = dict(service_fields)
    debug = dict(parser_debug or {})
    body = content
    repaired = False
    force_detected = _body_has_placeholder_issues(body)

    reqs, steps, prefer_actions = _prefer_detected_structured_fields(
        requirements=list(fields.get("requirements") or []),
        steps=list(fields.get("steps") or []),
        parser_debug=debug,
        force=force_detected,
    )
    actions.extend(prefer_actions)

    office = _normalize_space(fields.get("office"))
    cleaned_reqs: list[dict[str, Any]] = []
    for item in reqs:
        if not isinstance(item, dict):
            continue
        req = _normalize_space(item.get("requirement"))
        where = _normalize_space(item.get("where_to_secure"))
        if _is_blank_req_marker(req):
            continue
        req, where, glue_actions = _split_glued_requirement_where(req, where)
        actions.extend(glue_actions)
        if _placeholder(where):
            inferred = _infer_where_to_secure(req)
            if inferred:
                where = inferred
                actions.append("inferred_where_to_secure")
        if _placeholder(where) and office and not _placeholder(office):
            where = office
            actions.append("defaulted_where_to_service_office")
        if _placeholder(where):
            where = NEEDS_REVIEW
        cleaned_reqs.append({"requirement": req, "where_to_secure": where})
    if cleaned_reqs != list(reqs):
        repaired = True
    reqs = cleaned_reqs

    steps, step_actions, _ = _repair_steps(steps)
    actions.extend(step_actions)

    # Fill empty step fees with None when total/other steps are None.
    none_fee_steps = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        fee = _normalize_space(step.get("fees"))
        if fee.casefold() in {"none", "n/a", "na", "free"}:
            none_fee_steps += 1
        elif _placeholder(fee) or _contains_needs_review(fee):
            step["fees"] = "None"
            actions.append("filled_missing_step_fee_as_none")
            repaired = True
            none_fee_steps += 1

    total_time, total_actions = _recover_public_priority_total_time(
        title=title,
        total_time=str(fields.get("total_processing_time") or ""),
        steps=steps,
        parser_debug=debug,
    )
    actions.extend(total_actions)

    if not reqs and not checklist_blank:
        # Detected None/N/A or empty requirements table → blank checklist wording.
        if bool(debug.get("checklist_blank")) or not any(
            isinstance(item, dict) and _filled(item.get("requirement"))
            for item in (debug.get("detected_requirements") or [])
        ):
            checklist_blank = True
            actions.append("marked_checklist_blank")

    fields["requirements"] = reqs
    fields["steps"] = steps
    fields["total_processing_time"] = total_time
    fields["checklist_blank"] = checklist_blank
    fields["parser_debug"] = debug
    if total_time and not _placeholder(fields.get("total_fees")):
        pass
    elif _placeholder(fields.get("total_fees")):
        # Recover None fees from complete None step fees.
        step_fees = [
            _normalize_space(step.get("fees"))
            for step in steps
            if isinstance(step, dict) and _normalize_space(step.get("fees"))
        ]
        if step_fees and all(fee.casefold() in {"none", "n/a", "na", "free"} for fee in step_fees):
            fields["total_fees"] = "None"
            actions.append("recovered_total_fees_from_steps")

    debug = _sync_parser_debug_with_repaired(
        debug,
        requirements=reqs,
        steps=steps,
        office=fields.get("office") if isinstance(fields.get("office"), str) else None,
    )
    fields["parser_debug"] = debug

    rebuilt = build_charter_article_body(
        title=title,
        service=fields,
        source_document=source_document,
    )
    if checklist_blank and not reqs and "Requirement: Not specified" in rebuilt:
        rebuilt = rebuilt.replace(
            "- Requirement: Not specified\n  Where to Secure: Not specified",
            _BLANK_REQUIREMENTS_LINE,
            1,
        )
        actions.append("blank_checklist_body_wording")

    if rebuilt != body or prefer_actions or total_actions or force_detected:
        repaired = True
        actions.append("rebuilt_public_priority_article_body")
        body = rebuilt

    return fields, debug, body, list(dict.fromkeys(actions)), repaired


def _is_internal_heavy(
    *,
    title: str,
    office: str | None,
    who_may_avail: str | None,
    transaction_type: str | None,
    audience: str | None,
) -> bool:
    # Priority student-facing services stay student-facing even when transaction
    # type is G2G or the delivering office is administrative (clinic, library…).
    # Only hard internal title keywords (procurement/BAC/HR/ISO/…) force internal.
    if _is_student_facing_rescue_priority(title):
        return any(
            re.search(pattern, title or "", flags=re.I) for pattern in _INTERNAL_OFFICE_PATTERNS
        )
    if (audience or "").strip().lower() == "internal":
        return True
    blob = " ".join(
        part
        for part in (title, office, who_may_avail, transaction_type)
        if part and not _placeholder(part)
    ).casefold()
    if re.search(r"\bg2g\b|government\s+to\s+government", blob, flags=re.I):
        return True
    return any(re.search(pattern, blob, flags=re.I) for pattern in _INTERNAL_OFFICE_PATTERNS)


def _repair_title(title: str) -> tuple[str, list[str]]:
    actions: list[str] = []
    cleaned = strip_service_part_suffix(_normalize_space(title))
    cleaned = re.sub(r"^\d{1,3}[\.\)]\s*", "", cleaned).strip(" -–—:")
    if cleaned != _normalize_space(title):
        actions.append("cleaned_service_title")
    return cleaned, actions


_KNOWN_REQUIREMENT_WHERE: tuple[tuple[str, str], ...] = (
    (r"online\s+application\s+form", "LSPU Online Admission"),
    (r"certified\s+true\s+copy.*(?:report\s+card|tor)|\breport\s+card\b.*\btor\b", "Client"),
    (r"\bform\s*138\b|\btranscript\s+of\s+records\b|\btor\b", "SHS / Previous HEI"),
    (r"certificate\s+of\s+good\s+moral|good\s+moral\s+character", "SHS"),
    (r"birth\s+certificate", "PSA"),
    (r"marriage\s+certificate", "PSA"),
    (r"\b2\s*[x×]\s*2\b|\b2x2\b", "Client"),
    (r"borrower'?s?\s+card|\blspu\s+id\b|student\s+id", "Client"),
    (r"valid\s+(?:school\s+)?id", "Client"),
    (r"\bcor\b|certificate\s+of\s+registration", "Registrar's Office"),
    (r"semestral\s+clearance|general\s+clearance|clearance\s+form", "OSAS"),
    (r"dropping\s+form|add.?drop\s+form", "Registrar's Office"),
    (r"assessment\s+form|statement\s+of\s+account", "Accounting Office"),
    (r"medical\s+certificate|dental\s+record", "University Health Service"),
    (r"library\s+card|borrower'?s?\s+card", "University Library"),
)

# Detected + rendered step count floors for named public priority services.
_REQUIRED_STEP_COUNTS: tuple[tuple[str, int], ...] = (
    (r"routine\s+medical(?:\s+and\s+dental)?\s+services?", 3),
)


def _required_step_count_for_title(title: str) -> int | None:
    lower = _normalize_space(title).casefold()
    for pattern, count in _REQUIRED_STEP_COUNTS:
        if re.search(pattern, lower, flags=re.I):
            return count
    return None


def _article_body_status(body: str) -> str:
    main = (body or "").split("----EXTRACTED METADATA----", 1)[0]
    if "\nSource Information" in main:
        main = main.split("\nSource Information", 1)[0]
    if "[NEEDS REVIEW]" in main:
        return "has_needs_review"
    if "Not specified" in main:
        return "has_not_specified"
    return "clean"


def _infer_where_to_secure(requirement: str) -> str | None:
    cleaned = _normalize_space(requirement)
    if not cleaned:
        return None
    for pattern, where in _KNOWN_REQUIREMENT_WHERE:
        if re.search(pattern, cleaned, flags=re.I):
            return where
    return None


def _is_blank_req_marker(value: Any) -> bool:
    text = _normalize_space(value).casefold()
    return text in {
        "",
        "none",
        "n/a",
        "na",
        "nil",
        "-",
        "—",
        "–",
        "not specified",
        "[needs review]",
        "needs review",
        NEEDS_REVIEW.casefold(),
    }

def _repair_requirement_pairs(requirements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    actions: list[str] = []
    repaired: list[dict[str, Any]] = []
    pending_req = ""

    for item in requirements or []:
        if not isinstance(item, dict):
            continue
        req = _normalize_space(item.get("requirement"))
        where = _normalize_space(item.get("where_to_secure"))
        if _is_blank_req_marker(req) and (_placeholder(where) or _is_blank_req_marker(where)):
            continue
        if _is_blank_req_marker(req):
            continue

        split_req, split_where, glue_actions = _split_glued_requirement_where(req, where)
        if glue_actions:
            req, where = split_req, split_where
            actions.extend(glue_actions)

        # Full office suffix glued onto requirement text.
        if req and _placeholder(where):
            match = _OFFICE_SUFFIX_RE.match(req)
            if match:
                req = _normalize_space(match.group("req"))
                where = _normalize_space(match.group("office"))
                actions.append("repaired_requirement_office_suffix")

        # "Dropping Form Registrar's" + "Office" → Dropping Form / Registrar's Office
        if req and where.casefold() == "office":
            frag = _REQ_OFFICE_FRAGMENT_RE.match(req)
            if frag:
                req = _normalize_space(frag.group("req"))
                where = f"{_normalize_space(frag.group('head'))} Office"
                actions.append("repaired_requirement_office_suffix")

        # Split wrapped requirement across rows.
        if pending_req and req and not where:
            if _looks_like_wrapped_continuation(req, pending_req):
                pending_req = f"{pending_req} {req}".strip()
                actions.append("merged_wrapped_requirement_rows")
                continue
        if pending_req and where and (not req or _looks_like_wrapped_continuation(req, pending_req)):
            req = f"{pending_req} {req}".strip() if req else pending_req
            pending_req = ""
            actions.append("merged_wrapped_requirement_rows")

        if req and _placeholder(where):
            inferred = _infer_where_to_secure(req)
            if inferred:
                where = inferred
                actions.append("inferred_where_to_secure")
            else:
                pending_req = req
                continue
        if _placeholder(req) and where and pending_req:
            req = pending_req
            pending_req = ""
            actions.append("paired_requirement_with_where_to_secure")

        if _placeholder(req) or _is_blank_req_marker(req):
            continue
        if _placeholder(where):
            inferred = _infer_where_to_secure(req)
            if inferred:
                where = inferred
                actions.append("inferred_where_to_secure")
        repaired.append(
            {
                "requirement": req,
                "where_to_secure": where if not _placeholder(where) else NEEDS_REVIEW,
            }
        )
        pending_req = ""

    if pending_req:
        inferred = _infer_where_to_secure(pending_req)
        repaired.append(
            {
                "requirement": pending_req,
                "where_to_secure": inferred or NEEDS_REVIEW,
            }
        )
        if inferred:
            actions.append("inferred_where_to_secure")

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in repaired:
        key = f"{item['requirement'].casefold()}|{item['where_to_secure'].casefold()}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped, actions


def _split_processing_and_personnel(processing: str, responsible: str) -> tuple[str, str, list[str]]:
    actions: list[str] = []
    proc = "" if _placeholder(processing) else _normalize_space(processing)
    person = "" if _placeholder(responsible) else _normalize_space(responsible)

    # Normalize unicode half to ASCII form for matching.
    proc = proc.replace("½", "1/2")
    person = person.replace("½", "1/2")

    # "2-3 mins University" / "5mins Records" + "Officer, Staff"
    time_title_head = re.match(
        r"^(?P<time>\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*"
        r"(?:mins?|minutes?|hours?|hrs?|days?|seconds?)"
        r"|(?:\d+\s+and\s+(?:1/2))\s*(?:hours?|hrs?|minutes?|mins?))"
        r"\s+(?P<head>[A-Za-z][\w/]*?(?:\s+[A-Za-z][\w/]*?){0,5})\s*$",
        proc,
        flags=re.I,
    )
    if (
        time_title_head
        and not _TIME_ATOM_RE.fullmatch(proc)
        and not re.fullmatch(
            r"(?:mins?|minutes?|hours?|hrs?|days?|seconds?)",
            time_title_head.group("head"),
            flags=re.I,
        )
    ):
        head = _normalize_space(time_title_head.group("head"))
        proc = _normalize_space(time_title_head.group("time"))
        if person:
            if head.casefold() not in person.casefold():
                if re.match(
                    r"^(?:officer|staff|director|chairperson|dean|secretary|interns?)\b",
                    person,
                    flags=re.I,
                ):
                    person = f"{head} {person}".strip()
                else:
                    person = f"{head}/{person}".replace("//", "/").strip()
        else:
            person = head
        actions.append("repaired_processing_time_personnel_split")

    # "18 Minutes Director/" + "Chairperson" → join personnel across the slash cut.
    if proc and person and _PERSONNEL_WORDS_RE.search(proc) and not _TIME_ATOM_RE.fullmatch(proc):
        match = _PERSONNEL_TAIL_RE.search(proc)
        if match:
            time_part = _normalize_space(match.group("time"))
            person_head = _normalize_space(match.group("person")).rstrip("/").strip()
            if person_head and person.casefold() not in person_head.casefold():
                person = f"{person_head}/{person}".replace("//", "/").strip("/")
            elif person_head:
                person = person_head
            proc = time_part
            actions.append("repaired_processing_time_personnel_split")

    if proc and (not person or _placeholder(person)):
        match = _PERSONNEL_TAIL_RE.search(proc)
        if match and _PERSONNEL_WORDS_RE.search(match.group("person")):
            proc = _normalize_space(match.group("time"))
            person = _normalize_space(match.group("person")).rstrip("/").strip()
            actions.append("repaired_processing_time_personnel_split")

    if person and not proc:
        time_match = _TIME_ATOM_RE.search(person)
        if time_match:
            proc = _normalize_space(time_match.group(0))
            person = _normalize_space(
                person[: time_match.start()] + " " + person[time_match.end() :]
            )
            actions.append("repaired_personnel_contains_processing_time")

    # Still mixed: strip personnel/office words from processing time.
    if proc and _PERSONNEL_WORDS_RE.search(proc):
        match = _PERSONNEL_TAIL_RE.search(proc)
        if match:
            leftover_person = _normalize_space(match.group("person")).rstrip("/").strip()
            proc = _normalize_space(match.group("time"))
            if leftover_person:
                if person and leftover_person.casefold() not in person.casefold():
                    person = f"{leftover_person}/{person}".replace("//", "/").strip("/")
                elif not person:
                    person = leftover_person
            actions.append("repaired_processing_time_personnel_split")
        else:
            # Strip trailing office words even when regex time atom missed (e.g. "2-3 mins University").
            stripped = re.sub(
                r"\s+(?:University|Clinic|Library|Guidance|OSAS|BAO|Registrar|Accounting)\b.*$",
                "",
                proc,
                flags=re.I,
            ).strip()
            if stripped and stripped != proc:
                leftover = _normalize_space(proc[len(stripped) :]).strip(" -/")
                proc = stripped
                if leftover and (not person or leftover.casefold() not in person.casefold()):
                    person = f"{leftover} {person}".strip() if person else leftover
                actions.append("repaired_processing_time_personnel_split")

    return proc or NEEDS_REVIEW, person or NEEDS_REVIEW, actions


def _clean_fee_value(fees: str) -> tuple[str, list[str]]:
    actions: list[str] = []
    cleaned = _strip_table_header_crumbs(_normalize_space(fees))
    if cleaned != _normalize_space(fees):
        actions.append("stripped_fee_header_crumbs")
    if _placeholder(cleaned) or _looks_like_page_number_fee(cleaned):
        return NEEDS_REVIEW, actions
    if cleaned.casefold() in {"n/a", "na", "n / a", "none", "free", "-", "—", "–"}:
        return "None", (["cleaned_fee_value"] if cleaned.casefold() != "none" else actions)
    if _INVALID_FEE_RE.match(cleaned) or cleaned.casefold() in {
        "on the",
        "of the",
        "to be",
        "be paid",
    }:
        return NEEDS_REVIEW, ["invalid_fee_value"]
    match = _FEE_CLEAN_RE.match(cleaned)
    if match:
        fee = _normalize_fee(match.group("fee"))
        if fee != cleaned:
            actions.append("cleaned_fee_value")
        return fee, actions
    fee_token = re.search(
        r"\b(None|N\s*/\s*A|N/?A|Free|Php\s*[\d,.]+(?:/\w+)?|P\s*[\d,.]+(?:/\w+)?)\b",
        cleaned,
        flags=re.I,
    )
    if fee_token:
        actions.append("cleaned_fee_value")
        return _normalize_fee(fee_token.group(1)), actions
    # Reject obvious non-fee fragments.
    if not re.search(r"(?i)\b(?:none|n/?a|free|php|p\s*\d|\d)", cleaned):
        return NEEDS_REVIEW, ["invalid_fee_value"]
    fee = _normalize_fee(cleaned)
    if fee != cleaned:
        actions.append("cleaned_fee_value")
    return fee, actions


def _missing_fields(service_fields: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not _filled(service_fields.get("office")):
        missing.append("office")
    if not _filled(service_fields.get("who_may_avail")):
        missing.append("who_may_avail")
    reqs = service_fields.get("requirements") or []
    checklist_blank = bool(service_fields.get("checklist_blank"))
    has_real_req = any(
        isinstance(r, dict)
        and _filled(r.get("requirement"))
        and not _is_blank_req_marker(r.get("requirement"))
        for r in reqs
    )
    if not has_real_req and not checklist_blank:
        missing.append("requirements")
    if not _has_complete_charter_step(service_fields.get("steps") or []):
        missing.append("complete_step")
    if not _filled(service_fields.get("total_processing_time")):
        missing.append("total_processing_time")
    return missing


def _match_priority_diagnostic_title(title: str) -> str | None:
    cleaned = strip_service_part_suffix(_normalize_space(title))
    cleaned = re.sub(r"^\d{1,3}[\.\)]\s*", "", cleaned).strip()
    for name in _PRIORITY_DIAGNOSTIC_TITLES:
        if cleaned.casefold() == name.casefold():
            return name
        if name.casefold() in cleaned.casefold() or cleaned.casefold() in name.casefold():
            return name
    return None


def _coverage_next_action(
    *,
    found: bool,
    bucket: str | None,
    blockers: list[str],
    detected_steps: int,
    rendered_steps: int,
) -> str:
    if not found:
        return "extract_or_detect_service"
    if bucket == "recommended" and detected_steps > 0 and rendered_steps >= detected_steps and not blockers:
        return "ready_for_publish_review"
    if "rendered_steps_fewer_than_detected" in blockers or (
        detected_steps > rendered_steps > 0
    ):
        return "fix_formatter_to_render_all_detected_steps"
    if bucket == "needs_review":
        return "repair_minor_gaps_then_recheck"
    if bucket == "low_quality":
        return "repair_broken_rows_or_keep_low_quality"
    if bucket == "rag_only":
        return "keep_rag_only_unless_structured_block_found"
    if blockers:
        return f"resolve_blockers:{','.join(blockers[:3])}"
    return "review_manually"


def _coverage_next_repair_target(blockers: list[str], missing: list[str]) -> str | None:
    priority_order = (
        "incomplete_requirement_pair",
        "processing_time_contains_personnel",
        "missing_total_processing_time",
        "incomplete_step_row",
        "body_has_not_specified_or_needs_review",
        "rendered_steps_fewer_than_detected",
        "invalid_total_fees",
        "audience_not_student_facing",
        "rescue_not_successful_for_recommended",
    )
    for key in priority_order:
        if key in blockers:
            return key
    if missing:
        return f"missing_{missing[0]}"
    if blockers:
        return blockers[0]
    return None


def _coverage_main_failed_field(blockers: list[str], missing: list[str]) -> str | None:
    mapping = {
        "incomplete_requirement_pair": "requirements",
        "blank_checklist_rendered_as_not_specified": "requirements",
        "incomplete_step_row": "steps",
        "processing_time_contains_personnel": "processing_time",
        "missing_total_processing_time": "total_processing_time",
        "invalid_total_fees": "total_fees",
        "body_has_not_specified_or_needs_review": "article_body",
        "audience_not_student_facing": "audience",
        "rendered_steps_fewer_than_detected": "steps",
        "detected_requirements_contain_needs_review": "requirements",
    }
    for key in blockers:
        if key in mapping:
            return mapping[key]
    if missing:
        return missing[0]
    return None


def _suggested_bucket_after_repair(
    *,
    found: bool,
    is_student_priority: bool,
    bucket: str | None,
    blockers: list[str],
    repairable: bool,
) -> str | None:
    if not found:
        return None
    if bucket == "recommended":
        return "recommended"
    if not is_student_priority:
        return bucket or "needs_review"
    hard = {"audience_not_student_facing", "invalid_service_title", "fragment_or_field_label_title"}
    if any(b in hard for b in blockers) and not repairable:
        return "rag_only"
    if repairable:
        # Structurally repairable student priority services should land Recommended
        # once fields are clean; otherwise Needs Review (never forced LQ).
        soft_only = not any(
            b in {"invalid_service_title", "fragment_or_field_label_title"} for b in blockers
        )
        return "recommended" if soft_only and len(blockers) <= 3 else "needs_review"
    if bucket == "low_quality":
        return "needs_review"
    return bucket or "needs_review"


def build_priority_rescue_diagnostics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One Priority Coverage row per watchlist title (found or missing)."""
    by_title: dict[str, dict[str, Any]] = {}
    for item in results:
        title = str(item.get("title") or "")
        matched = _match_priority_diagnostic_title(title)
        if not matched:
            continue
        service_fields = item.get("service_fields") if isinstance(item.get("service_fields"), dict) else {}
        parser_debug = {}
        repaired = item.get("service") if isinstance(item.get("service"), dict) else {}
        if isinstance(repaired.get("parser_debug"), dict):
            parser_debug = repaired.get("parser_debug") or {}
        elif isinstance(service_fields.get("parser_debug"), dict):
            parser_debug = service_fields.get("parser_debug") or {}
        detected_reqs = parser_debug.get("detected_requirements")
        if not isinstance(detected_reqs, list):
            detected_reqs = list(service_fields.get("requirements") or [])
        detected_steps = parser_debug.get("detected_step_rows")
        if not isinstance(detected_steps, list):
            detected_steps = list(service_fields.get("steps") or [])
        body = str(item.get("content") or "")
        rendered_steps = _count_rendered_steps(body)
        bucket = str(item.get("repaired_bucket") or "")
        blockers = list(item.get("remaining_blockers") or [])
        missing = list(item.get("missing_fields") or [])
        total_time = service_fields.get("total_processing_time") or repaired.get("total_processing_time")
        quality = str(
            item.get("extraction_quality")
            or repaired.get("extraction_quality")
            or ""
        )
        audience = str(item.get("audience") or item.get("charter_audience") or "").lower()
        is_student_priority = True
        repairable = bool(
            blockers
            and not any(
                b in {"invalid_service_title", "fragment_or_field_label_title"} for b in blockers
            )
            and (
                _filled(service_fields.get("office"))
                or audience == "student_facing"
                or _is_student_facing_rescue_priority(matched)
            )
        )
        if bucket == "recommended" and not blockers:
            repairable = False
        next_repair = _coverage_next_repair_target(blockers, missing)
        main_failed = _coverage_main_failed_field(blockers, missing)
        suggested = _suggested_bucket_after_repair(
            found=True,
            is_student_priority=is_student_priority,
            bucket=bucket,
            blockers=blockers,
            repairable=repairable,
        )
        prev = by_title.get(matched)
        score = {
            "recommended": 3,
            "needs_review": 2,
            "low_quality": 1,
            "rag_only": 0,
        }.get(bucket, 0)
        prev_score = {
            "recommended": 3,
            "needs_review": 2,
            "low_quality": 1,
            "rag_only": 0,
        }.get(str((prev or {}).get("final_bucket") or (prev or {}).get("repaired_bucket") or ""), -1)
        clean_detected_steps = [
            s for s in detected_steps if isinstance(s, dict) and _is_clean_detected_step(s)
        ]
        entry = {
            "title": matched,
            "found": True,
            "extraction_status": quality or bucket or "unknown",
            "final_bucket": bucket or None,
            "original_bucket": item.get("original_bucket"),
            "repaired_bucket": bucket or None,
            "publish_allowed": bucket == "recommended",
            "detected_requirements_count": len(
                [
                    r
                    for r in detected_reqs
                    if isinstance(r, dict)
                    and _normalize_space(r.get("requirement"))
                    and str(r.get("requirement")) not in {NEEDS_REVIEW, "[NEEDS REVIEW]"}
                    and not _is_blank_req_marker(r.get("requirement"))
                ]
            ),
            "detected_step_count": len(clean_detected_steps),
            "rendered_step_count": rendered_steps,
            "total_processing_time_detected": bool(
                total_time and not _placeholder(total_time)
            ),
            "blockers": blockers[:8],
            "remaining_blockers": blockers,
            "top_blockers": blockers[:5],
            "missing_fields": missing,
            "row_merge_failure_reason": item.get("row_merge_failure_reason"),
            "rescue_attempted": bool(item.get("rescue_attempted")),
            "rescue_successful": bool(item.get("rescue_successful")),
            "next_action": _coverage_next_action(
                found=True,
                bucket=bucket,
                blockers=blockers,
                detected_steps=len(clean_detected_steps),
                rendered_steps=rendered_steps,
            ),
            "next_repair_target": next_repair,
            "repairable": repairable,
            "main_failed_field": main_failed,
            "suggested_bucket_after_repair": suggested,
            "is_student_priority": True,
            "is_public_priority": bool(item.get("public_priority_service", True)),
            "body_has_needs_review": _body_has_placeholder_issues(body),
            "article_body_status": _article_body_status(body),
            "body_rebuilt_from_detected_fields": bool(
                item.get("body_rebuilt_from_detected_fields")
                or "rebuilt_public_priority_article_body"
                in (item.get("repair_actions_applied") or [])
            ),
            "required_step_count_met": bool(item.get("required_step_count_met", True)),
            "publish_safety_state": str(item.get("publish_safety_state") or "unsaved"),
            "already_published_match": bool(
                item.get("already_published") or item.get("existing_published")
            ),
        }
        # Alias for report consumers that expect singular naming.
        entry["detected_requirement_count"] = entry["detected_requirements_count"]
        if prev is None or score >= prev_score:
            by_title[matched] = entry

    diagnostics: list[dict[str, Any]] = []
    aliases = {
        "ID Processing": "Processing of Student ID",
        "Processing of Student ID": "ID Processing",
        "Scholarship and Financial Assistance": "Processing of Scholarship and Financial Assistance",
        "Processing of Scholarship and Financial Assistance": "Scholarship and Financial Assistance",
    }

    def _missing_row(name: str) -> dict[str, Any]:
        return {
            "title": name,
            "found": False,
            "extraction_status": "not_found",
            "final_bucket": None,
            "original_bucket": None,
            "repaired_bucket": None,
            "publish_allowed": False,
            "detected_requirements_count": 0,
            "detected_requirement_count": 0,
            "detected_step_count": 0,
            "rendered_step_count": 0,
            "total_processing_time_detected": False,
            "blockers": ["service_not_detected"],
            "remaining_blockers": [],
            "top_blockers": [],
            "missing_fields": [],
            "row_merge_failure_reason": None,
            "rescue_attempted": False,
            "rescue_successful": False,
            "next_action": "extract_or_detect_service",
            "next_repair_target": "extract_or_detect_service",
            "repairable": False,
            "main_failed_field": None,
            "suggested_bucket_after_repair": None,
            "is_student_priority": True,
            "is_public_priority": True,
            "body_has_needs_review": False,
            "article_body_status": "clean",
            "body_rebuilt_from_detected_fields": False,
            "required_step_count_met": False,
            "publish_safety_state": "unsaved",
            "already_published_match": False,
        }

    for name in _PRIORITY_DIAGNOSTIC_TITLES:
        if name in by_title:
            diagnostics.append(by_title[name])
            continue
        sibling = aliases.get(name)
        if sibling and sibling in by_title:
            clone = dict(by_title[sibling])
            clone["title"] = name
            diagnostics.append(clone)
            continue
        diagnostics.append(_missing_row(name))

    def _sort_key(row: dict[str, Any]) -> tuple:
        public = 0 if row.get("is_public_priority", True) else 1
        found = 0 if row.get("found") else 1
        bucket = str(row.get("final_bucket") or "")
        bucket_rank = {
            "recommended": 0,
            "needs_review": 1,
            "low_quality": 2,
            "rag_only": 3,
            "": 4,
        }.get(bucket, 4)
        blockers = list(row.get("blockers") or [])
        student = 0 if row.get("is_student_priority") else 1
        repairable = 0 if row.get("repairable") else 1
        body_issue = 0 if not row.get("body_has_needs_review") else 1
        return (
            public,
            student,
            found,
            bucket_rank,
            body_issue,
            repairable,
            len(blockers),
            str(row.get("title") or ""),
        )

    diagnostics.sort(key=_sort_key)
    return diagnostics


def _client_looks_unfinished(text: str) -> bool:
    cleaned = _normalize_space(text)
    if not cleaned:
        return True
    if cleaned.endswith(("-", ",", "/")):
        return True
    if re.search(r"\b(?:the|of|and|or|for|to|by|with|a|an|from|into|certificate)\s*$", cleaned, flags=re.I):
        return True
    # Very short fragment titles like "Services" / "Certificate of"
    words = cleaned.split()
    if len(words) <= 2 and not cleaned.endswith("."):
        if cleaned[:1].isupper() and not _looks_like_new_step_marker(cleaned):
            return True
    return False


def _is_personnel_only_fragment(text: str) -> bool:
    cleaned = _normalize_space(text).rstrip("/").strip()
    if not cleaned:
        return False
    if _PERSONNEL_ONLY_RE.match(cleaned):
        return True
    # Slash-cut fragments like "Chairperson/Staff" or "Director/"
    if _PERSONNEL_WORDS_RE.search(cleaned) and not _TIME_ATOM_RE.search(cleaned):
        words = cleaned.replace("/", " ").split()
        return 1 <= len(words) <= 5 and not any(
            token.casefold() in {"present", "evaluate", "accept", "submit", "pay", "claim"}
            for token in words
        )
    return False


def _row_filled_count(cells: list[str]) -> int:
    return sum(1 for i in range(5) if _normalize_space((cells + [""] * 5)[i]))


def _join_personnel(existing: str, fragment: str) -> str:
    head = _normalize_space(existing).rstrip("/")
    tail = _normalize_space(fragment).lstrip("/").strip()
    if not head:
        return tail
    if not tail:
        return head
    if tail.casefold() in head.casefold():
        return head
    if head.casefold().endswith(tail.casefold()):
        return head
    return _normalize_space(f"{head}/{tail}".replace("//", "/"))


def _attach_personnel_continuation_rows(rows: list[list[str]]) -> list[list[str]]:
    """Attach Chairperson/Staff, Program Head, Dean/... rows to previous person column.

    Must run *before* generic wrap merge so personnel crumbs are not glued onto the
    next client-step text.
    """
    if not rows:
        return rows
    out: list[list[str]] = []
    for row in rows:
        cells = (list(row) + ["", "", "", "", ""])[:5]
        client, agency, fees, ptime, person = (_normalize_space(c) for c in cells)
        filled = _row_filled_count(cells)
        if not out:
            out.append(cells)
            continue
        prev = out[-1]
        prev_person = _normalize_space(prev[4])
        personnel_fragment = ""
        for cand in (client, agency, fees, ptime, person):
            if _is_personnel_only_fragment(cand):
                personnel_fragment = cand
                break
        personnel_only_row = bool(personnel_fragment) and filled <= 2 and (
            not client
            or _is_personnel_only_fragment(client)
        ) and not agency and (not fees or _is_personnel_only_fragment(fees)) and (
            not ptime or _is_personnel_only_fragment(ptime)
        )
        if personnel_only_row and (
            not prev_person or prev_person.endswith("/") or _placeholder(prev_person)
        ):
            prev[4] = _join_personnel(
                "" if _placeholder(prev_person) else prev_person,
                personnel_fragment,
            )
            continue
        # Empty primary cells with person-only column also continue previous person.
        if (
            not client
            and not agency
            and not fees
            and not ptime
            and person
            and _is_personnel_only_fragment(person)
            and (not prev_person or prev_person.endswith("/") or _placeholder(prev_person))
        ):
            prev[4] = _join_personnel(
                "" if _placeholder(prev_person) else prev_person,
                person,
            )
            continue
        out.append(cells)
    return out


def _strip_personnel_prefix_from_client(rows: list[list[str]]) -> list[list[str]]:
    """If wrap merge already glued a personnel crumb onto the next client, peel it back."""
    if not rows:
        return rows
    out: list[list[str]] = []
    personnel_word = (
        r"(?:Director|Chairperson|Chair|Dean|Associate(?:\s+Dean)?|"
        r"Program(?:\s+Head|\s+Chair(?:person)?)?|Staff)"
    )
    prefix_re = re.compile(
        rf"^(?P<head>(?:OSAS\s+)?{personnel_word}"
        rf"(?:[\s/]+{personnel_word})*)"
        rf"(?P<rest>\s+[A-Z].+)$",
        flags=re.I,
    )
    for row in rows:
        cells = (list(row) + ["", "", "", "", ""])[:5]
        client = _normalize_space(cells[0])
        if out and client:
            prev = out[-1]
            prev_person = _normalize_space(prev[4])
            match = prefix_re.match(client)
            if match and (
                not prev_person
                or prev_person.endswith("/")
                or _placeholder(prev_person)
                or _is_personnel_only_fragment(match.group("head"))
            ):
                head = _normalize_space(match.group("head"))
                rest = _normalize_space(match.group("rest"))
                if _is_personnel_only_fragment(head) and rest:
                    prev[4] = _join_personnel(
                        "" if _placeholder(prev_person) else prev_person,
                        head,
                    )
                    cells[0] = rest
        out.append(cells)
    return out


def _merge_sparse_continuation_rows(rows: list[list[str]]) -> list[list[str]]:
    """Append sparse wrap rows (1–2 filled cells) onto an incomplete previous step."""
    if not rows:
        return rows
    out: list[list[str]] = []
    for row in rows:
        cells = (list(row) + ["", "", "", "", ""])[:5]
        client, agency, fees, ptime, person = (_normalize_space(c) for c in cells)
        filled = _row_filled_count(cells)
        if not out:
            out.append(cells)
            continue
        prev = out[-1]
        prev_client = _normalize_space(prev[0])
        prev_agency = _normalize_space(prev[1])
        prev_person = _normalize_space(prev[4])
        prev_incomplete = (
            not prev_agency
            or not _normalize_space(prev[3])
            or not prev_person
            or _client_looks_unfinished(prev_client)
            or (prev_person.endswith("/") if prev_person else False)
        )

        # Personnel-only continuation (Chairperson/Staff, Program Head, Dean/Associate Dean).
        personnel_fragment = ""
        for cand in (client, agency, fees, ptime, person):
            if _is_personnel_only_fragment(cand):
                personnel_fragment = cand
                break
        if personnel_fragment and filled <= 2 and (not client or _is_personnel_only_fragment(client)):
            if prev_incomplete or prev_person.endswith("/") or not prev_person:
                prev[4] = _join_personnel(prev_person, personnel_fragment)
                continue

        # Processing-time cell holding a personnel title (Program Head / Dean).
        if (
            prev_incomplete
            and filled <= 2
            and ptime
            and _is_personnel_only_fragment(ptime)
            and not _TIME_ATOM_RE.search(ptime)
            and not client
            and not agency
        ):
            prev[4] = _join_personnel(prev_person, ptime)
            continue

        # Sparse text-only row: append into previous incomplete client/agency.
        # If previous already has agency + fee/time and only person is missing,
        # do not absorb a new client action — that is a new step (or personnel).
        person_only_gap = bool(
            prev_agency
            and (_normalize_space(prev[2]) or _normalize_space(prev[3]))
            and (not prev_person or prev_person.endswith("/") or _placeholder(prev_person))
            and not _client_looks_unfinished(prev_client)
        )
        if prev_incomplete and filled <= 2 and not _looks_like_new_step_marker(client):
            if (
                person_only_gap
                and client
                and not _is_personnel_only_fragment(client)
                and not _looks_like_wrapped_continuation(client, prev_client)
            ):
                out.append(cells)
                continue
            if client and (
                _looks_like_wrapped_continuation(client, prev_client)
                or _client_looks_unfinished(prev_client)
                or (not agency and not fees and not ptime and not person and not person_only_gap)
            ):
                prev[0] = f"{prev_client} {client}".strip()
                for i, value in enumerate((agency, fees, ptime, person), start=1):
                    if value and not _normalize_space(prev[i]):
                        prev[i] = value
                continue
            if not client and agency and (
                not prev_agency or _looks_like_wrapped_continuation(agency, prev_agency)
            ):
                prev[1] = f"{prev_agency} {agency}".strip() if prev_agency else agency
                for i, value in enumerate((fees, ptime, person), start=2):
                    if value and not _normalize_space(prev[i]):
                        prev[i] = value
                continue

        out.append(cells)
    return out


def _aggressive_merge_fragment_clients(rows: list[list[str]]) -> list[list[str]]:
    """Merge incomplete client-step fragments into logical steps (generic)."""
    if not rows:
        return rows
    out: list[list[str]] = []
    for row in rows:
        cells = (list(row) + ["", "", "", "", ""])[:5]
        client = _normalize_space(cells[0])
        agency = _normalize_space(cells[1])
        secondary = any(_normalize_space(cells[i]) for i in (2, 3, 4))
        if out:
            prev = out[-1]
            prev_client = _normalize_space(prev[0])
            prev_agency = _normalize_space(prev[1])
            prev_secondary = any(_normalize_space(prev[i]) for i in (2, 3, 4))
            prev_incomplete = (not prev_agency and not prev_secondary) or _client_looks_unfinished(
                prev_client
            )
            # Append continuation fragment into previous incomplete step.
            if prev_incomplete and client and not _looks_like_new_step_marker(client):
                if (
                    _looks_like_wrapped_continuation(client, prev_client)
                    or _client_looks_unfinished(prev_client)
                    or (not agency and not secondary)
                ):
                    prev[0] = f"{prev_client} {client}".strip()
                    for i in range(1, 5):
                        if _normalize_space(cells[i]) and not _normalize_space(prev[i]):
                            prev[i] = cells[i]
                        elif _normalize_space(cells[i]) and _normalize_space(prev[i]):
                            if i in (0, 1):
                                prev[i] = f"{_normalize_space(prev[i])} {_normalize_space(cells[i])}".strip()
                            else:
                                # Prefer non-empty secondary from the fuller row.
                                prev[i] = cells[i]
                    continue
            # Previous is unfinished text but this row has agency — merge client then take agency.
            if _client_looks_unfinished(prev_client) and not prev_agency and (agency or secondary):
                if not _looks_like_new_step_marker(client) or _looks_like_wrapped_continuation(
                    client, prev_client
                ):
                    prev[0] = f"{prev_client} {client}".strip() if client else prev_client
                    for i in range(1, 5):
                        if _normalize_space(cells[i]):
                            prev[i] = cells[i] if not _normalize_space(prev[i]) else prev[i]
                    continue
        out.append(cells)
    return out


def _steps_to_rows(steps: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in steps or []:
        if not isinstance(item, dict):
            continue

        def _cell_or_empty(value: Any) -> str:
            text = _normalize_space(value)
            return "" if _placeholder(text) else text

        rows.append(
            [
                _cell_or_empty(item.get("client_step")),
                _cell_or_empty(item.get("agency_action")),
                _cell_or_empty(item.get("fees") or item.get("fee")),
                _cell_or_empty(item.get("processing_time")),
                _cell_or_empty(
                    item.get("person_responsible") or item.get("responsible_personnel")
                ),
            ]
        )
    return rows


def _repair_steps(
    steps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """Repair step rows. Returns (steps, actions, row_merge_failure_reason)."""
    actions: list[str] = []
    rows = _steps_to_rows(steps)
    if not rows:
        return [], actions, "no_step_rows"

    before = len(rows)
    # Personnel crumbs first so wrap merge cannot glue them onto the next client step.
    merged = _attach_personnel_continuation_rows(rows)
    merged = _merge_wrapped_rows(merged, primary_idx=[0, 1], secondary_idx=[2, 3, 4])
    merged = _strip_personnel_prefix_from_client(merged)
    merged = _coalesce_fragment_step_rows(merged)
    merged = _aggressive_merge_fragment_clients(merged)
    merged = _merge_sparse_continuation_rows(merged)
    merged = _attach_personnel_continuation_rows(merged)
    if len(merged) < before:
        actions.append("merged_wrapped_step_rows")

    repaired: list[dict[str, Any]] = []
    for row in merged:
        cells = (row + ["", "", "", "", ""])[:5]
        client, agency, fees, ptime, responsible = (_normalize_space(c) for c in cells)

        # Personnel-only leftover after merge — attach to previous step.
        if repaired and _is_personnel_only_fragment(client) and not agency and not fees and not ptime:
            prev_person = repaired[-1]["person_responsible"]
            if _placeholder(prev_person) or str(prev_person).endswith("/"):
                repaired[-1]["person_responsible"] = _join_personnel(
                    "" if _placeholder(prev_person) else str(prev_person),
                    client,
                )
                actions.append("merged_personnel_continuation")
            continue
        if repaired and not client and not agency and not fees and not ptime and _is_personnel_only_fragment(
            responsible
        ):
            prev_person = repaired[-1]["person_responsible"]
            repaired[-1]["person_responsible"] = _join_personnel(
                "" if _placeholder(prev_person) else str(prev_person),
                responsible,
            )
            actions.append("merged_personnel_continuation")
            continue

        if _placeholder(client) and _placeholder(agency):
            continue
        # Drop client-only fragments that never gained agency — try append to prior.
        if client and not agency and not fees and not ptime and not responsible:
            if repaired and (
                _looks_like_wrapped_continuation(client, repaired[-1]["client_step"])
                or _client_looks_unfinished(repaired[-1]["client_step"])
            ):
                repaired[-1]["client_step"] = f"{repaired[-1]['client_step']} {client}".strip()
                actions.append("merged_wrapped_step_rows")
            continue
        fees, fee_actions = _clean_fee_value(fees)
        actions.extend(a for a in fee_actions if a != "invalid_fee_value")
        if "invalid_fee_value" in fee_actions:
            fees = NEEDS_REVIEW
            actions.append("cleaned_fee_value")
        # Personnel stuck in processing time while person empty/partial.
        if responsible and _is_personnel_only_fragment(ptime) and not _TIME_ATOM_RE.search(ptime):
            responsible = _join_personnel(ptime, responsible)
            ptime = ""
            actions.append("repaired_processing_time_personnel_split")
        elif _is_personnel_only_fragment(ptime) and not _TIME_ATOM_RE.search(ptime):
            responsible = _join_personnel(responsible, ptime)
            ptime = ""
            actions.append("repaired_processing_time_personnel_split")
        ptime, responsible, split_actions = _split_processing_and_personnel(ptime, responsible)
        actions.extend(split_actions)
        if _looks_like_new_step_marker(client):
            client = re.sub(r"^\d{1,3}[\.\)]\s*", "", client).strip()
            actions.append("stripped_step_number_prefix")
        client, agency, fees, ptime, responsible = _finalize_step_cells(
            client=client,
            agency=agency,
            fees=fees,
            ptime=ptime,
            responsible=responsible,
            context=f"{client} {agency} {responsible}",
        )
        if fees != _normalize_space(cells[2]) and "stripped_fee_header_crumbs" not in actions:
            actions.append("stripped_step_header_crumbs")
        repaired.append(
            {
                "client_step": client or NEEDS_REVIEW,
                "agency_action": agency or NEEDS_REVIEW,
                "fees": fees if not _placeholder(fees) else NEEDS_REVIEW,
                "processing_time": ptime if not _placeholder(ptime) else NEEDS_REVIEW,
                "person_responsible": responsible if not _placeholder(responsible) else NEEDS_REVIEW,
            }
        )

    # Final pass: fill trailing slash personnel from later same-office person values.
    for idx, step in enumerate(repaired):
        person = str(step.get("person_responsible") or "")
        if person.endswith("/") and idx + 1 < len(repaired):
            nxt = str(repaired[idx + 1].get("person_responsible") or "")
            if nxt and not _placeholder(nxt) and not nxt.endswith("/"):
                step["person_responsible"] = _join_personnel(person, nxt)
                actions.append("propagated_personnel_from_later_step")

    complete = sum(
        1
        for step in repaired
        if not _placeholder(step.get("client_step"))
        and not _placeholder(step.get("agency_action"))
        and not _placeholder(step.get("fees"))
        and not _placeholder(step.get("processing_time"))
        and not _placeholder(step.get("person_responsible"))
        and not str(step.get("person_responsible") or "").endswith("/")
    )
    failure_reason = None
    if not repaired:
        failure_reason = "all_rows_dropped_during_merge"
    elif complete == 0:
        failure_reason = "no_complete_step_after_merge"
    elif complete < len(repaired):
        failure_reason = "partial_steps_still_incomplete"
    return repaired, actions, failure_reason


def _deep_repair_steps_from_debug(
    *,
    steps: list[dict[str, Any]],
    parser_debug: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """Second-chance reconstruction from detected_step_rows / geometry dumps."""
    actions: list[str] = []
    debug = parser_debug if isinstance(parser_debug, dict) else {}
    source_steps = list(steps or [])

    detected = debug.get("detected_step_rows")
    if isinstance(detected, list) and detected:
        dict_rows = [item for item in detected if isinstance(item, dict)]
        if len(dict_rows) > len(source_steps):
            source_steps = dict_rows
            actions.append("reloaded_detected_step_rows_for_deep_repair")

    visual = debug.get("visual_table_debug")
    if isinstance(visual, dict):
        steps_table = visual.get("steps_table") if isinstance(visual.get("steps_table"), dict) else {}
        logical = steps_table.get("logical_rows_before_finalize") or steps_table.get(
            "filtered_column_rows"
        )
        if isinstance(logical, list) and logical:
            rebuilt: list[dict[str, Any]] = []
            for row in logical:
                if not isinstance(row, (list, tuple)):
                    continue
                cells = (list(row) + ["", "", "", "", ""])[:5]
                rebuilt.append(
                    {
                        "client_step": cells[0],
                        "agency_action": cells[1],
                        "fees": cells[2],
                        "processing_time": cells[3],
                        "person_responsible": cells[4],
                    }
                )
            if len(rebuilt) > len(source_steps):
                source_steps = rebuilt
                actions.append("reloaded_visual_logical_rows_for_deep_repair")

    repaired, step_actions, failure = _repair_steps(source_steps)
    actions.extend(step_actions)
    if _has_complete_charter_step(repaired):
        return repaired, actions, None
    reason = failure or debug.get("no_step_rows_reason") or "deep_repair_still_incomplete"
    if isinstance(visual, dict):
        steps_table = visual.get("steps_table") if isinstance(visual.get("steps_table"), dict) else {}
        reason = steps_table.get("no_step_rows_reason") or visual.get("why_merge_no_step_rows") or reason
    return repaired, actions, reason


def _recover_total_processing_time(
    *,
    total_processing_time: str,
    total_fees: str,
    steps: list[dict[str, Any]],
    parser_debug: dict[str, Any] | None,
) -> tuple[str, str, list[str]]:
    actions: list[str] = []
    total_time = _normalize_space(total_processing_time)
    fees = _normalize_space(total_fees)
    fees, fee_actions = _clean_fee_value(fees) if fees and not _placeholder(fees) else (fees, [])
    actions.extend(a for a in fee_actions if a != "invalid_fee_value")
    if "invalid_fee_value" in fee_actions:
        fees = NEEDS_REVIEW

    debug = parser_debug if isinstance(parser_debug, dict) else {}
    block = str(debug.get("cleaned_service_block") or debug.get("raw_service_block") or "")
    if _placeholder(total_time) and block:
        # Prefer compound entrance-exam totals from source before atom-splitting,
        # so en-dash ranges like "1–3 days, 1 hour and 45 minutes" stay intact.
        entrance_match = _ENTRANCE_EXAM_TOTAL_RE.search(block)
        if entrance_match:
            total_time = _ENTRANCE_EXAM_TOTAL_CANON
            actions.append("recovered_total_processing_time")
            if _placeholder(fees):
                for line in block.splitlines():
                    text = _normalize_space(line)
                    if not re.match(r"(?i)^total\b", text):
                        continue
                    remainder = re.sub(
                        r"(?i)^total\s*(?:processing\s+time)?\s*:?\s*", "", text
                    ).strip()
                    recovered_fee, _ = _split_total_line(remainder)
                    if not _placeholder(recovered_fee):
                        fees = recovered_fee
                        actions.append("recovered_total_fees")
                    break
        else:
            for line in block.splitlines():
                text = _normalize_space(line)
                if not re.match(r"(?i)^total\b", text):
                    continue
                remainder = re.sub(
                    r"(?i)^total\s*(?:processing\s+time)?\s*:?\s*", "", text
                ).strip()
                recovered_fee, recovered_time = _split_total_line(remainder)
                if not _placeholder(recovered_time):
                    total_time = recovered_time
                    actions.append("recovered_total_processing_time")
                if _placeholder(fees) and not _placeholder(recovered_fee):
                    fees = recovered_fee
                    actions.append("recovered_total_fees")
                break

    if _placeholder(total_time) and steps:
        minutes = 0.0
        ok = True
        for step in steps:
            proc = _normalize_space(step.get("processing_time")).replace("½", "1/2")
            match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*minutes?", proc, flags=re.I)
            if not match:
                ok = False
                break
            minutes += float(match.group(1))
        if ok and minutes > 0:
            if minutes == int(minutes):
                total_time = f"{int(minutes)} minutes" if int(minutes) != 1 else "1 minute"
            else:
                total_time = f"{minutes} minutes"
            actions.append("recovered_total_processing_time_from_steps")
        else:
            # Single/shared non-minute step times (e.g. "1 and 1/2 hours").
            usable = []
            for step in steps:
                proc = _normalize_space(step.get("processing_time")).replace("½", "1/2")
                if not proc or _placeholder(proc):
                    continue
                if _PERSONNEL_WORDS_RE.search(proc):
                    split_proc, _, _ = _split_processing_and_personnel(proc, "")
                    proc = split_proc
                if _TIME_ATOM_RE.fullmatch(proc) or _TIME_ATOM_RE.search(proc):
                    usable.append(proc)
            unique = list(dict.fromkeys(usable))
            if len(unique) == 1:
                total_time = unique[0]
                actions.append("recovered_total_processing_time_from_steps")
            elif usable:
                # Prefer first complete time atom when multiple steps exist.
                match = _TIME_ATOM_RE.search(usable[0])
                if match:
                    total_time = _normalize_space(match.group(0))
                    actions.append("recovered_total_processing_time_from_steps")

    if _placeholder(fees) and steps:
        recovered_fees: list[str] = []
        for step in steps:
            fee = _normalize_fee(_strip_table_header_crumbs(str(step.get("fees") or "")))
            if not _placeholder(fee):
                recovered_fees.append(fee)
        if recovered_fees:
            unique = list(dict.fromkeys(recovered_fees))
            if all(value.casefold() == "none" for value in unique):
                fees = "None"
            else:
                paid = [value for value in unique if value.casefold() != "none"]
                fees = ", ".join(paid) if paid else "None"
            actions.append("recovered_total_fees_from_steps")

    # Strip personnel stuck on total time.
    if total_time and _PERSONNEL_WORDS_RE.search(total_time):
        match = _PERSONNEL_TAIL_RE.search(total_time)
        if match:
            total_time = _normalize_space(match.group("time"))
            actions.append("repaired_processing_time_personnel_split")

    return (
        total_time if not _placeholder(total_time) else NEEDS_REVIEW,
        fees if not _placeholder(fees) else NEEDS_REVIEW,
        actions,
    )


def _label_blockers(blockers: list[str]) -> list[str]:
    labeled: list[str] = []
    for code in blockers:
        label = _BLOCKER_LABELS.get(code, code.replace("_", " "))
        if label not in labeled:
            labeled.append(label)
    return labeled


def _contains_needs_review(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return NEEDS_REVIEW in value or "[NEEDS REVIEW]" in value
    if isinstance(value, dict):
        return any(_contains_needs_review(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_needs_review(v) for v in value)
    return NEEDS_REVIEW in str(value) or "[NEEDS REVIEW]" in str(value)


def _count_rendered_steps(body: str) -> int:
    return len(re.findall(r"(?im)^\d+\.\s*Client Step:", body or ""))


def _is_clean_detected_step(step: dict[str, Any]) -> bool:
    """True for a real detected/repaired step row (not blank / header-only)."""
    if not isinstance(step, dict):
        return False
    client = _normalize_space(step.get("client_step"))
    agency = _normalize_space(step.get("agency_action"))
    if _placeholder(client) and _placeholder(agency):
        return False
    # After crumb cleanup, incomplete rows still count as detected if action text exists.
    return bool(client or agency)


def _count_detected_step_rows(parser_debug: dict[str, Any] | None, steps: list[dict[str, Any]]) -> int:
    debug = parser_debug if isinstance(parser_debug, dict) else {}
    detected = debug.get("detected_step_rows")
    if isinstance(detected, list) and detected:
        clean = [item for item in detected if _is_clean_detected_step(item)]
        if clean:
            return len(clean)
        return len(detected)
    return len([s for s in steps if _is_clean_detected_step(s)])


def _count_incomplete_detected_steps(
    parser_debug: dict[str, Any] | None, steps: list[dict[str, Any]]
) -> int:
    debug = parser_debug if isinstance(parser_debug, dict) else {}
    rows = debug.get("detected_step_rows") if isinstance(debug.get("detected_step_rows"), list) else steps
    incomplete = 0
    for step in rows or []:
        if not _is_clean_detected_step(step if isinstance(step, dict) else {}):
            continue
        assert isinstance(step, dict)
        for key in ("fees", "processing_time", "person_responsible", "agency_action", "client_step"):
            if _contains_needs_review(step.get(key)):
                incomplete += 1
                break
    return incomplete


def validate_charter_final_body(
    *,
    title: str,
    service_fields: dict[str, Any],
    body: str,
    parser_debug: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Strict final-body validation for Recommended eligibility."""
    blockers: list[str] = []
    debug = parser_debug if isinstance(parser_debug, dict) else {}

    if charter_body_has_blocking_placeholders(body):
        blockers.append("body_has_not_specified_or_needs_review")

    # Also avoid treating repaired detected_* placeholders as blockers when empty lists.
    # Only flag detected_requirements / other debug keys that still carry NEEDS REVIEW.
    if _contains_needs_review(debug.get("detected_requirements")):
        blockers.append("detected_requirements_contain_needs_review")
    debug_for_scan = {
        key: value
        for key, value in debug.items()
        if key
        not in {
            "rescue",
            "cleaned_service_block",
            "raw_service_block",
            # Synced after repair; body/steps validation covers remaining gaps.
            "detected_step_rows",
            "detected_requirements",
            "visual_table_debug",
            "word_column_assignments",
        }
    }
    if _contains_needs_review(debug_for_scan):
        blockers.append("parser_debug_contains_needs_review")

    total_fees = _normalize_space(service_fields.get("total_fees"))
    # Prefer the dedicated Fees section (after Steps), not per-step "Fees:" lines.
    fees_match = re.search(
        r"(?ims)^Steps\s*\n.*?^Fees\s*\n\s*(.+?)\s*(?:\n\s*)^Total Processing Time\s*$",
        body or "",
    )
    fee_line = _normalize_space(fees_match.group(1)) if fees_match else ""
    if _contains_needs_review(total_fees):
        blockers.append("invalid_total_fees")
    elif total_fees and (
        _INVALID_FEE_RE.match(total_fees) or total_fees.casefold() in {"on the", "of the"}
    ):
        blockers.append("invalid_total_fees")
    elif _placeholder(total_fees) and (
        not fee_line
        or _placeholder(fee_line)
        or _contains_needs_review(fee_line)
        or fee_line.casefold() in {"on the", "of the"}
        or bool(_INVALID_FEE_RE.match(fee_line))
    ):
        blockers.append("invalid_total_fees")
    if fee_line and (
        fee_line.casefold() in {"on the", "of the"}
        or bool(_INVALID_FEE_RE.match(fee_line))
        or _contains_needs_review(fee_line)
    ):
        blockers.append("invalid_total_fees")

    # Processing time mixed with personnel in structured steps or body.
    for step in service_fields.get("steps") or []:
        if not isinstance(step, dict):
            continue
        ptime = _normalize_space(step.get("processing_time"))
        if ptime and _PERSONNEL_WORDS_RE.search(ptime) and not re.fullmatch(
            r"\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?|days?)", ptime, flags=re.I
        ):
            blockers.append("processing_time_contains_personnel")
            break
    for match in re.finditer(r"(?im)^\s*Processing Time:\s*(.+)$", body or ""):
        ptime = _normalize_space(match.group(1))
        if ptime and _PERSONNEL_WORDS_RE.search(ptime):
            blockers.append("processing_time_contains_personnel")
            break

    for item in service_fields.get("requirements") or []:
        if not isinstance(item, dict):
            continue
        where = _normalize_space(item.get("where_to_secure"))
        req = _normalize_space(item.get("requirement"))
        if where.casefold() == "office" and req:
            blockers.append("where_to_secure_is_office_only")
            break
    if re.search(r"(?im)Where to Secure:\s*Office\s*$", body or ""):
        blockers.append("where_to_secure_is_office_only")

    rendered = _count_rendered_steps(body)
    detected = _count_detected_step_rows(debug, list(service_fields.get("steps") or []))
    if detected > 0 and rendered < detected:
        blockers.append("rendered_steps_fewer_than_detected")
    if _count_incomplete_detected_steps(debug, list(service_fields.get("steps") or [])) > 0:
        # Detected rows still carrying [NEEDS REVIEW] cannot be Recommended.
        blockers.append("detected_step_contains_needs_review")

    # Field mixing heuristics in body.
    if re.search(r"(?im)Processing Time:\s*\d+\s+\w+\s+(?:Director|Dean|Chair|Staff|Program)\b", body or ""):
        blockers.append("invalid_field_mixing")
    if re.search(r"(?im)Where to Secure:\s*Office\s*$", body or "") and re.search(
        r"(?im)Requirement:.*(?:Registrar'?s|Dean'?s|NSTP|Cashier|OSAS)\s*$", body or ""
    ):
        blockers.append("invalid_field_mixing")

    return (not blockers), list(dict.fromkeys(blockers))


def _semantic_validation_passed(
    *,
    title: str,
    service_fields: dict[str, Any],
    body: str,
    audience: str,
    parser_debug: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if not title or is_noise_service_title(title) or is_artifact_charter_title(title):
        blockers.append("invalid_service_title")
    if is_charter_field_label_or_fragment_title(title):
        blockers.append("fragment_or_field_label_title")
    if not _filled(service_fields.get("office")):
        blockers.append("missing_office")
    if not _filled(service_fields.get("who_may_avail")):
        blockers.append("missing_who_may_avail")
    reqs = service_fields.get("requirements") or []
    checklist_blank = bool(service_fields.get("checklist_blank"))
    # Drop None/N/A blank markers before scoring incomplete pairs.
    real_reqs = [
        item
        for item in reqs
        if isinstance(item, dict)
        and _filled(item.get("requirement"))
        and not _is_blank_req_marker(item.get("requirement"))
    ]
    if not real_reqs:
        checklist_blank = True
    has_reqs = bool(real_reqs)
    incomplete_pair = any(
        isinstance(item, dict)
        and _filled(item.get("requirement"))
        and not _is_blank_req_marker(item.get("requirement"))
        and (
            _placeholder(item.get("where_to_secure"))
            or _is_blank_req_marker(item.get("where_to_secure"))
            or _normalize_space(item.get("where_to_secure")).casefold() == "office"
        )
        for item in reqs
    )
    if incomplete_pair and not checklist_blank:
        blockers.append("incomplete_requirement_pair")
    if not has_reqs and not checklist_blank:
        blockers.append("incomplete_requirement_pair")
    if checklist_blank and "Requirement: Not specified" in (body or ""):
        blockers.append("blank_checklist_rendered_as_not_specified")
    if not _has_complete_charter_step(service_fields.get("steps") or []):
        blockers.append("incomplete_step_row")
    if not _filled(service_fields.get("total_processing_time")):
        blockers.append("missing_total_processing_time")
    if charter_body_has_blocking_placeholders(body):
        blockers.append("body_has_not_specified_or_needs_review")
    if audience != "student_facing":
        blockers.append("audience_not_student_facing")

    body_ok, body_blockers = validate_charter_final_body(
        title=title,
        service_fields=service_fields,
        body=body,
        parser_debug=parser_debug,
    )
    if not body_ok:
        blockers.extend(body_blockers)

    return (not blockers), list(dict.fromkeys(blockers))


def validate_charter_candidate_for_recommended(candidate: dict[str, Any]) -> tuple[bool, list[str]]:
    """Apply semantic + final body validation to any candidate (including Recommended)."""
    title = str(candidate.get("title") or "").strip()
    body = str(candidate.get("content") or "")
    if "----EXTRACTED METADATA----" in body:
        body = body.split("----EXTRACTED METADATA----", 1)[0]
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    parser_debug = candidate.get("parser_debug") or meta.get("parser_debug") or {}
    if not isinstance(parser_debug, dict):
        parser_debug = {}

    requirements = candidate.get("requirements") or meta.get("extracted_requirements") or []
    steps = candidate.get("steps") or meta.get("extracted_steps") or []
    if isinstance(requirements, str):
        try:
            requirements = json.loads(requirements)
        except Exception:
            requirements = []
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except Exception:
            steps = []

    service_fields = {
        "office": candidate.get("office") or meta.get("office") or meta.get("extracted_office"),
        "who_may_avail": candidate.get("who_may_avail") or meta.get("who_may_avail"),
        "classification": candidate.get("classification") or meta.get("classification"),
        "transaction_type": candidate.get("transaction_type") or meta.get("transaction_type"),
        "requirements": requirements if isinstance(requirements, list) else [],
        "steps": steps if isinstance(steps, list) else [],
        "total_processing_time": candidate.get("total_processing_time")
        or meta.get("total_processing_time"),
        "total_fees": candidate.get("total_fees") or meta.get("total_fees"),
        "checklist_blank": bool(candidate.get("checklist_blank") or meta.get("checklist_blank")),
    }
    audience = str(
        candidate.get("charter_audience") or meta.get("charter_audience") or "ambiguous"
    ).strip().lower()
    ok, blockers = _semantic_validation_passed(
        title=title,
        service_fields=service_fields,
        body=body,
        audience=audience if audience in {"student_facing", "internal", "ambiguous"} else "ambiguous",
        parser_debug=parser_debug,
    )

    rescue = parser_debug.get("rescue") if isinstance(parser_debug.get("rescue"), dict) else {}
    fields_changed = bool(
        candidate.get("fields_changed")
        if candidate.get("fields_changed") is not None
        else rescue.get("fields_changed")
    )
    repair_actions = candidate.get("repair_actions_applied") or rescue.get("repair_actions_applied") or []
    repairs_required = bool(fields_changed or repair_actions)
    body_uses = candidate.get("body_uses_repaired_fields")
    if body_uses is None:
        body_uses = rescue.get("body_uses_repaired_fields")
    rescue_successful = candidate.get("rescue_successful")
    if rescue_successful is None:
        rescue_successful = rescue.get("rescue_successful")
    repaired_bucket = str(
        candidate.get("repaired_bucket")
        or candidate.get("charter_candidate_bucket")
        or rescue.get("repaired_bucket")
        or ""
    ).strip().lower()
    if repairs_required and repaired_bucket == "recommended":
        if body_uses is False:
            ok = False
            blockers = list(dict.fromkeys([*blockers, "body_missing_repaired_fields"]))
        if rescue_successful is False:
            ok = False
            blockers = list(dict.fromkeys([*blockers, "rescue_not_successful_for_recommended"]))

    required_steps = _required_step_count_for_title(title)
    if required_steps is not None:
        detected_n = _count_detected_step_rows(
            parser_debug if isinstance(parser_debug, dict) else {},
            service_fields.get("steps") if isinstance(service_fields.get("steps"), list) else [],
        )
        rendered_n = _count_rendered_steps(body)
        if detected_n < required_steps or rendered_n < required_steps:
            ok = False
            blockers = list(
                dict.fromkeys([*blockers, f"required_step_count_lt_{required_steps}"])
            )
    return ok, list(dict.fromkeys(blockers))


def _display_needs_review_reasons(
    blockers: list[str],
    *,
    parser_debug: dict[str, Any] | None = None,
    bucket_reason: str | None = None,
) -> list[str]:
    reasons = list(blockers)
    if not reasons and bucket_reason:
        reasons.append(str(bucket_reason))
    return _label_blockers(reasons)


def _score_repaired_extraction_quality(service_fields: dict[str, Any], title: str) -> tuple[str, str]:
    if not title or is_noise_service_title(title) or is_charter_field_label_or_fragment_title(title):
        return "low_quality", "fragment_or_missing_title"
    has_office = _filled(service_fields.get("office"))
    has_who = _filled(service_fields.get("who_may_avail"))
    reqs = [
        item
        for item in (service_fields.get("requirements") or [])
        if isinstance(item, dict) and _filled(item.get("requirement"))
    ]
    steps = [
        item
        for item in (service_fields.get("steps") or [])
        if isinstance(item, dict)
        and (_filled(item.get("client_step")) or _filled(item.get("agency_action")))
    ]
    checklist_blank = bool(service_fields.get("checklist_blank"))
    if not has_office and not has_who and not reqs and not steps:
        return "rag_only", "placeholder_only_body"
    if not has_office:
        return "needs_review", "missing_office_division"
    if not (reqs or steps or checklist_blank):
        return "low_quality", "no_requirements_or_steps"
    if not has_who:
        return "needs_review", "missing_who_may_avail"
    if not _has_complete_charter_step(steps):
        return "needs_review", "no_complete_step_row"
    if not _filled(service_fields.get("total_processing_time")):
        return "needs_review", "missing_processing_time"
    if checklist_blank and not _all_charter_steps_complete(steps):
        return "needs_review", "blank_checklist_incomplete_steps"
    return "clean", "meets_clean_requirements_after_rescue"


def _fields_signature(fields: dict[str, Any]) -> str:
    payload = {
        "office": fields.get("office"),
        "who": fields.get("who_may_avail"),
        "requirements": fields.get("requirements") or [],
        "steps": fields.get("steps") or [],
        "total_processing_time": fields.get("total_processing_time"),
        "total_fees": fields.get("total_fees"),
        "checklist_blank": bool(fields.get("checklist_blank")),
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _body_uses_repaired_fields(body: str, service_fields: dict[str, Any]) -> bool:
    """True when key repaired structured values appear in the rendered body."""
    main = re.split(r"(?m)^Source\s+Information\s*$", body or "", maxsplit=1)[0]
    if not main.strip():
        return False
    office = _normalize_space(service_fields.get("office"))
    if office and not _placeholder(office) and office not in main:
        return False
    for step in service_fields.get("steps") or []:
        if not isinstance(step, dict):
            continue
        client = _normalize_space(step.get("client_step"))
        if client and not _placeholder(client) and client not in main:
            # Allow truncated match for long client steps.
            if client[:40] not in main:
                return False
        ptime = _normalize_space(step.get("processing_time"))
        if ptime and not _placeholder(ptime) and _PERSONNEL_WORDS_RE.search(ptime):
            return False
    for item in service_fields.get("requirements") or []:
        if not isinstance(item, dict):
            continue
        where = _normalize_space(item.get("where_to_secure"))
        if where and not _placeholder(where) and where.casefold() != "office" and where not in main:
            return False
    total = _normalize_space(service_fields.get("total_processing_time"))
    if total and not _placeholder(total) and total not in main:
        return False
    return True


def _sync_parser_debug_with_repaired(
    parser_debug: dict[str, Any],
    *,
    requirements: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    office: str | None,
) -> dict[str, Any]:
    """Persist repaired fields into parser_debug so Recommended is not blocked by stale OCR."""
    debug = dict(parser_debug or {})
    debug["detected_requirements"] = [
        {
            "requirement": item.get("requirement"),
            "where_to_secure": item.get("where_to_secure"),
        }
        for item in requirements
        if isinstance(item, dict) and not _placeholder(item.get("requirement"))
    ]
    debug["detected_step_rows"] = [
        {
            "client_step": item.get("client_step"),
            "agency_action": item.get("agency_action"),
            "fees": item.get("fees"),
            "processing_time": item.get("processing_time"),
            "person_responsible": item.get("person_responsible"),
        }
        for item in steps
        if isinstance(item, dict)
        and not (
            _placeholder(item.get("client_step")) and _placeholder(item.get("agency_action"))
        )
    ]
    if office and not _placeholder(office):
        debug["detected_office"] = office
    # Preserve geometry diagnostics for priority TXT downloads.
    return debug


def rescue_charter_v2_service(
    service: dict[str, Any] | None,
    *,
    source_document: str = "citizen-charter.pdf",
) -> dict[str, Any]:
    """Repair one V2 service and return fields + rescue metadata."""
    original = dict(service or {})
    title = str(original.get("service_title") or "").strip()
    repair_actions: list[str] = []
    rescue_reasons: list[str] = []

    title, title_actions = _repair_title(title)
    repair_actions.extend(title_actions)

    original_fields = charter_v2_service_to_fields(original)
    original_quality = str(original.get("extraction_quality") or "low_quality").strip().lower()
    original_body = build_charter_article_body(
        title=title or "Service",
        service=original_fields,
        source_document=source_document,
    )
    original_audience = classify_charter_audience(
        office=original_fields.get("office"),
        who_may_avail=original_fields.get("who_may_avail"),
        title=title,
        text=original_body,
        transaction_type=original_fields.get("transaction_type"),
    )
    original_decision = decide_charter_bucket_for_v2(
        title=title or "Service",
        service=original_fields,
        audience=original_audience,
        text=original_body,
        extraction_quality=original_quality,
    )
    original_bucket = str(original_decision.get("bucket") or "low_quality")
    original_was_low_quality = original_bucket == "low_quality" or original_quality == "low_quality"

    is_fragment = (
        not title
        or is_noise_service_title(title)
        or is_artifact_charter_title(title)
        or is_charter_field_label_or_fragment_title(title)
    )
    if is_fragment:
        return {
            "service": original,
            "service_fields": original_fields,
            "title": title,
            "content": original_body,
            "audience": original_audience,
            "category": map_charter_category(office=original_fields.get("office"), title=title),
            "extraction_quality": original_quality,
            "extraction_quality_reason": str(original.get("extraction_quality_reason") or ""),
            "original_bucket": original_bucket,
            "repaired_bucket": original_bucket,
            "rescue_attempted": False,
            "rescue_successful": False,
            "rescue_reasons": ["fragment_or_artifact_skipped"],
            "repair_actions_applied": [],
            "remaining_blockers": ["fragment_or_artifact"],
            "semantic_validation_passed": False,
            "final_body_validation_passed": False,
            "needs_review_reasons": ["fragment_or_artifact"],
            "low_quality_rescue_attempted": False,
            "low_quality_rescue_successful": False,
            "low_quality_repair_attempted": False,
            "low_quality_repair_changed_fields": False,
            "low_quality_rescued_to_needs_review": False,
            "low_quality_rescued_to_recommended": False,
            "low_quality_repair_failed": False,
            "missing_fields": [],
            "row_merge_failure_reason": "fragment_or_artifact",
            "public_priority_service": False,
            "public_priority_repaired": False,
            "public_priority_blocked_by_article_body": False,
        }

    rescue_attempted = True
    is_priority = _is_student_facing_rescue_priority(title)
    low_quality_repair_attempted = original_was_low_quality and (
        is_priority or bool(original_fields.get("office"))
    )

    requirements, req_actions = _repair_requirement_pairs(list(original_fields.get("requirements") or []))
    repair_actions.extend(req_actions)
    steps, step_actions, row_merge_failure_reason = _repair_steps(
        list(original_fields.get("steps") or [])
    )
    repair_actions.extend(step_actions)

    # Deeper reconstruction for priority / LQ public services still missing complete steps.
    if (is_priority or low_quality_repair_attempted) and not _has_complete_charter_step(steps):
        deep_steps, deep_actions, deep_failure = _deep_repair_steps_from_debug(
            steps=list(original_fields.get("steps") or []) + list(steps or []),
            parser_debug=original.get("parser_debug")
            if isinstance(original.get("parser_debug"), dict)
            else {},
        )
        repair_actions.extend(deep_actions)
        if _has_complete_charter_step(deep_steps) or len(deep_steps) >= len(steps):
            if deep_steps != steps:
                steps = deep_steps
                repair_actions.append("deep_row_reconstruction")
            row_merge_failure_reason = deep_failure if not _has_complete_charter_step(steps) else None
        elif deep_failure:
            row_merge_failure_reason = deep_failure

    checklist_blank = bool(original.get("checklist_blank") or original_fields.get("checklist_blank"))
    if not requirements and (
        checklist_blank
        or str((original.get("parser_debug") or {}).get("table_extraction_method") or "").startswith(
            "requirements"
        )
        or "checklist" in str((original.get("parser_debug") or {}).get("cleaned_service_block") or "").casefold()
    ):
        checklist_blank = True
        if "marked_checklist_blank" not in repair_actions:
            repair_actions.append("marked_checklist_blank")

    total_time, total_fees, total_actions = _recover_total_processing_time(
        total_processing_time=str(original_fields.get("total_processing_time") or ""),
        total_fees=str(original_fields.get("total_fees") or ""),
        steps=steps,
        parser_debug=original.get("parser_debug") if isinstance(original.get("parser_debug"), dict) else {},
    )
    repair_actions.extend(total_actions)

    office = original_fields.get("office")
    who = original_fields.get("who_may_avail")
    if _placeholder(office):
        debug = original.get("parser_debug") if isinstance(original.get("parser_debug"), dict) else {}
        detected = _normalize_space(debug.get("detected_office"))
        if detected and not _placeholder(detected):
            office = detected
            repair_actions.append("restored_detected_office")

    parser_debug = _sync_parser_debug_with_repaired(
        original.get("parser_debug") if isinstance(original.get("parser_debug"), dict) else {},
        requirements=requirements,
        steps=steps,
        office=office if isinstance(office, str) else None,
    )

    repaired_service = {
        **original,
        "service_title": title,
        "office_division": office or original.get("office_division"),
        "who_may_avail": who,
        "classification": original_fields.get("classification"),
        "transaction_type": original_fields.get("transaction_type"),
        "requirements": requirements,
        "steps": steps,
        "total_processing_time": total_time,
        "total_fees": total_fees,
        "checklist_blank": checklist_blank,
        "parser_debug": parser_debug,
    }
    service_fields = charter_v2_service_to_fields(repaired_service)
    service_fields["checklist_blank"] = checklist_blank

    content = build_charter_article_body(
        title=title,
        service=service_fields,
        source_document=source_document,
    )
    if checklist_blank and not requirements and "Requirement: Not specified" in content:
        content = content.replace(
            "- Requirement: Not specified\n  Where to Secure: Not specified",
            _BLANK_REQUIREMENTS_LINE,
            1,
        )
        repair_actions.append("blank_checklist_body_wording")

    public_priority = is_public_priority_charter_service(
        title=title,
        office=service_fields.get("office"),
        who_may_avail=service_fields.get("who_may_avail"),
        transaction_type=service_fields.get("transaction_type"),
    )
    public_priority_repaired = False
    public_priority_blocked_by_body = False
    if public_priority and (
        _body_has_placeholder_issues(content)
        or original_quality == "clean"
        or not _has_complete_charter_step(steps)
        or _placeholder(service_fields.get("total_processing_time"))
    ):
        (
            service_fields,
            parser_debug,
            content,
            priority_actions,
            public_priority_repaired,
        ) = _apply_public_priority_repair_pass(
            title=title,
            service_fields=service_fields,
            parser_debug=parser_debug,
            content=content,
            source_document=source_document,
            checklist_blank=checklist_blank,
        )
        repair_actions.extend(priority_actions)
        checklist_blank = bool(service_fields.get("checklist_blank"))
        requirements = list(service_fields.get("requirements") or [])
        steps = list(service_fields.get("steps") or [])
        total_time = str(service_fields.get("total_processing_time") or total_time)
        repaired_service = {
            **repaired_service,
            "requirements": requirements,
            "steps": steps,
            "total_processing_time": total_time,
            "total_fees": service_fields.get("total_fees"),
            "checklist_blank": checklist_blank,
            "parser_debug": parser_debug,
        }
        if public_priority_repaired:
            rescue_reasons.append("public_priority_repair_pass")

    if public_priority and not public_priority_repaired:
        if any(action in _PUBLIC_PRIORITY_REPAIR_MARKERS for action in repair_actions):
            public_priority_repaired = True
            rescue_reasons.append("public_priority_repair_pass")

    audience = classify_charter_audience(
        office=service_fields.get("office"),
        who_may_avail=service_fields.get("who_may_avail"),
        title=title,
        text=content,
        transaction_type=service_fields.get("transaction_type"),
    )
    if _is_internal_heavy(
        title=title,
        office=service_fields.get("office"),
        who_may_avail=service_fields.get("who_may_avail"),
        transaction_type=service_fields.get("transaction_type"),
        audience=audience,
    ):
        audience = "internal"
        repair_actions.append("downgraded_internal_audience")
        rescue_reasons.append("internal_admin_heavy_not_promoted")

    category = map_charter_category(
        office=service_fields.get("office"),
        title=title,
        text=content,
    )

    quality, quality_reason = _score_repaired_extraction_quality(service_fields, title)
    semantic_ok, blockers = _semantic_validation_passed(
        title=title,
        service_fields=service_fields,
        body=content,
        audience=audience,
        parser_debug=parser_debug,
    )
    final_body_ok, body_blockers = validate_charter_final_body(
        title=title,
        service_fields=service_fields,
        body=content,
        parser_debug=parser_debug,
    )
    blockers = list(dict.fromkeys([*blockers, *body_blockers]))

    if audience == "internal" and quality == "clean":
        quality = "needs_review"
        quality_reason = "internal_admin_heavy_after_rescue"
        blockers = list(dict.fromkeys([*blockers, "audience_not_student_facing"]))
        semantic_ok = False

    decision = decide_charter_bucket_for_v2(
        title=title,
        service=service_fields,
        audience=audience,
        text=content,
        category=category,
        extraction_quality=quality,
    )
    repaired_bucket = str(decision.get("bucket") or "needs_review")

    if repaired_bucket == "recommended" and (not semantic_ok or not final_body_ok):
        repaired_bucket = "needs_review"
        quality = "needs_review"
        quality_reason = "semantic_validation_failed"
        rescue_reasons.append("semantic_validation_blocked_recommended")
        decision = dict(decision)
        decision["bucket"] = "needs_review"
        decision["bucket_reason"] = "semantic_validation_failed"
        semantic_ok = False

    # Low Quality with usable student-facing / public-priority structure → Needs Review.
    usable_requirement = any(
        isinstance(item, dict) and _filled(item.get("requirement"))
        for item in (service_fields.get("requirements") or [])
    ) or bool(checklist_blank)
    usable_step = _has_complete_charter_step(steps) or any(
        isinstance(item, dict) and _filled(item.get("client_step"))
        for item in (steps or [])
    )
    if (
        repaired_bucket == "low_quality"
        and _filled(service_fields.get("office"))
        and title
        and audience == "student_facing"
        and (usable_requirement or usable_step)
        and not is_fragment
    ):
        repaired_bucket = "needs_review"
        if quality == "low_quality":
            quality = "needs_review"
            quality_reason = "repaired_into_needs_review"
        rescue_reasons.append("promoted_low_quality_to_needs_review_after_repair")
    if (
        public_priority
        and repaired_bucket == "low_quality"
        and not is_fragment
        and audience != "internal"
        and (usable_requirement or usable_step)
    ):
        repaired_bucket = "needs_review"
        if quality == "low_quality":
            quality = "needs_review"
            quality_reason = "public_priority_needs_review_not_low_quality"
        rescue_reasons.append("public_priority_kept_as_needs_review")

    if public_priority and _body_has_placeholder_issues(content):
        public_priority_blocked_by_body = True
        if "body_has_not_specified_or_needs_review" not in blockers:
            blockers = list(dict.fromkeys([*blockers, "body_has_not_specified_or_needs_review"]))
        if repaired_bucket == "recommended":
            repaired_bucket = "needs_review"
            decision = dict(decision)
            decision["bucket"] = "needs_review"
            decision["bucket_reason"] = "public_priority_blocked_by_article_body"
            rescue_reasons.append("public_priority_blocked_by_article_body")

    # Named public-priority services with known step floors (e.g. Routine Medical = 3).
    required_steps = _required_step_count_for_title(title)
    detected_step_count = _count_detected_step_rows(parser_debug, steps)
    rendered_step_count = _count_rendered_steps(content)
    required_step_count_met = True
    if required_steps is not None:
        required_step_count_met = (
            detected_step_count >= required_steps and rendered_step_count >= required_steps
        )
        if repaired_bucket == "recommended" and not required_step_count_met:
            repaired_bucket = "needs_review"
            decision = dict(decision)
            decision["bucket"] = "needs_review"
            decision["bucket_reason"] = "required_step_count_not_met"
            blockers = list(
                dict.fromkeys(
                    [
                        *blockers,
                        f"required_step_count_lt_{required_steps}",
                    ]
                )
            )
            rescue_reasons.append("required_step_count_blocked_recommended")

    fields_changed = _fields_signature(original_fields) != _fields_signature(service_fields)
    body_uses_repaired = _body_uses_repaired_fields(content, service_fields)

    # Repairs that do not land in the body cannot stay Recommended.
    if repaired_bucket == "recommended" and fields_changed and not body_uses_repaired:
        repaired_bucket = "needs_review"
        decision = dict(decision)
        decision["bucket"] = "needs_review"
        decision["bucket_reason"] = "body_missing_repaired_fields"
        blockers = list(dict.fromkeys([*blockers, "body_missing_repaired_fields"]))
        final_body_ok = False
        rescue_reasons.append("recommended_blocked_body_missing_repaired_fields")

    # rescue_successful only when repairs actually land in a clean validated body.
    rescue_successful = bool(
        fields_changed
        and body_uses_repaired
        and semantic_ok
        and final_body_ok
        and repaired_bucket == "recommended"
    )
    # If bucket still says Recommended after required repairs but rescue failed, downgrade.
    if (
        repaired_bucket == "recommended"
        and fields_changed
        and not rescue_successful
    ):
        repaired_bucket = "needs_review"
        decision = dict(decision)
        decision["bucket"] = "needs_review"
        decision["bucket_reason"] = "rescue_not_successful_for_recommended"
        blockers = list(dict.fromkeys([*blockers, "rescue_not_successful_for_recommended"]))
        rescue_reasons.append("recommended_blocked_rescue_not_successful")
        rescue_successful = False
    if repaired_bucket == "recommended" and original_bucket != "recommended" and rescue_successful:
        rescue_reasons.append("promoted_to_recommended_after_repair")
    elif fields_changed and repaired_bucket != "recommended":
        rescue_reasons.append("repaired_but_not_promoted")
    elif repair_actions and not fields_changed:
        rescue_reasons.append("repair_actions_without_field_change")
    if repair_actions and not rescue_reasons:
        rescue_reasons.append("fields_repaired")

    low_quality_repair_changed_fields = bool(low_quality_repair_attempted and fields_changed)
    low_quality_rescued_to_needs_review = bool(
        low_quality_repair_attempted
        and original_bucket == "low_quality"
        and repaired_bucket == "needs_review"
    )
    low_quality_rescued_to_recommended = bool(
        low_quality_repair_attempted
        and original_bucket == "low_quality"
        and repaired_bucket == "recommended"
    )
    # "Successful" only when the service leaves Low Quality.
    low_quality_rescue_successful = bool(
        low_quality_rescued_to_needs_review or low_quality_rescued_to_recommended
    )
    low_quality_repair_failed = bool(
        low_quality_repair_attempted
        and repaired_bucket == "low_quality"
        and original_bucket == "low_quality"
    )

    missing_fields = _missing_fields(service_fields)
    if _has_complete_charter_step(steps):
        row_merge_failure_reason = None

    needs_review_reasons: list[str] = []
    if repaired_bucket in {"needs_review", "low_quality"}:
        needs_review_reasons = _display_needs_review_reasons(
            blockers,
            parser_debug=parser_debug,
            bucket_reason=str(decision.get("bucket_reason") or repaired_bucket),
        )

    repaired_service["extraction_quality"] = quality
    repaired_service["extraction_quality_reason"] = quality_reason
    debug = dict(parser_debug)
    debug["rescue"] = {
        "rescue_attempted": rescue_attempted,
        "rescue_successful": rescue_successful,
        "repair_actions_applied": list(dict.fromkeys(repair_actions)),
        "remaining_blockers": blockers,
        "original_bucket": original_bucket,
        "repaired_bucket": repaired_bucket,
        "fields_changed": fields_changed,
        "body_uses_repaired_fields": body_uses_repaired,
        "final_body_validation_passed": final_body_ok,
        "missing_fields": missing_fields,
        "row_merge_failure_reason": row_merge_failure_reason,
        "low_quality_repair_attempted": low_quality_repair_attempted,
        "low_quality_rescue_successful": low_quality_rescue_successful,
    }
    repaired_service["parser_debug"] = debug

    return {
        "service": repaired_service,
        "service_fields": service_fields,
        "title": title,
        "content": content,
        "audience": audience,
        "category": category,
        "extraction_quality": quality,
        "extraction_quality_reason": quality_reason,
        "original_bucket": original_bucket,
        "repaired_bucket": repaired_bucket,
        "bucket_reason": decision.get("bucket_reason"),
        "decision": decision,
        "rescue_attempted": rescue_attempted,
        "rescue_successful": rescue_successful,
        "rescue_reasons": list(dict.fromkeys(rescue_reasons)),
        "repair_actions_applied": list(dict.fromkeys(repair_actions)),
        "remaining_blockers": blockers,
        "semantic_validation_passed": semantic_ok,
        "final_body_validation_passed": final_body_ok,
        "needs_review_reasons": needs_review_reasons,
        "low_quality_rescue_attempted": low_quality_repair_attempted,
        "low_quality_rescue_successful": low_quality_rescue_successful,
        "low_quality_repair_attempted": low_quality_repair_attempted,
        "low_quality_repair_changed_fields": low_quality_repair_changed_fields,
        "low_quality_rescued_to_needs_review": low_quality_rescued_to_needs_review,
        "low_quality_rescued_to_recommended": low_quality_rescued_to_recommended,
        "low_quality_repair_failed": low_quality_repair_failed,
        "fields_changed": fields_changed,
        "body_uses_repaired_fields": body_uses_repaired,
        "missing_fields": missing_fields,
        "row_merge_failure_reason": row_merge_failure_reason,
        "public_priority_service": bool(public_priority),
        "public_priority_repaired": bool(public_priority_repaired),
        "public_priority_blocked_by_article_body": bool(public_priority_blocked_by_body),
        "body_rebuilt_from_detected_fields": bool(
            "rebuilt_public_priority_article_body" in repair_actions
            or "preferred_detected_step_rows" in repair_actions
            or "preferred_detected_requirements" in repair_actions
        ),
        "required_step_count_met": bool(required_step_count_met),
        "article_body_status": _article_body_status(content),
        "required_step_count": required_steps,
        "detected_step_count": detected_step_count,
        "rendered_step_count": rendered_step_count,
    }


def summarize_rescue_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = sum(1 for item in results if item.get("rescue_attempted"))
    successful = sum(1 for item in results if item.get("rescue_successful"))
    repaired_not_promoted = sum(
        1
        for item in results
        if item.get("fields_changed")
        and item.get("repaired_bucket") != "recommended"
        and item.get("rescue_attempted")
    )
    repair_failed = sum(
        1
        for item in results
        if item.get("rescue_attempted")
        and not item.get("rescue_successful")
        and item.get("repaired_bucket") != "recommended"
        and (
            not item.get("fields_changed")
            or not item.get("final_body_validation_passed")
            or not item.get("semantic_validation_passed")
        )
    )
    semantic_failed = sum(
        1 for item in results if item.get("rescue_attempted") and not item.get("semantic_validation_passed")
    )
    recommended_blocked = sum(
        1
        for item in results
        if "semantic_validation_blocked_recommended" in (item.get("rescue_reasons") or [])
        or (
            item.get("original_bucket") == "recommended"
            and item.get("repaired_bucket") != "recommended"
        )
    )
    promoted = sum(
        1
        for item in results
        if item.get("repaired_bucket") == "recommended"
        and item.get("original_bucket") != "recommended"
        and item.get("rescue_successful")
    )
    downgraded = sum(
        1
        for item in results
        if item.get("original_bucket") == "recommended"
        and item.get("repaired_bucket") != "recommended"
    )
    internal_kept = sum(
        1
        for item in results
        if item.get("audience") == "internal"
        and item.get("repaired_bucket") in {"needs_review", "rag_only", "low_quality"}
    )
    true_low_quality = sum(1 for item in results if item.get("repaired_bucket") == "low_quality")
    lq_attempted = sum(1 for item in results if item.get("low_quality_repair_attempted"))
    lq_changed = sum(1 for item in results if item.get("low_quality_repair_changed_fields"))
    lq_to_nr = sum(1 for item in results if item.get("low_quality_rescued_to_needs_review"))
    lq_to_rec = sum(1 for item in results if item.get("low_quality_rescued_to_recommended"))
    lq_failed = sum(1 for item in results if item.get("low_quality_repair_failed"))
    lq_successful = lq_to_nr + lq_to_rec

    public_items = [item for item in results if item.get("public_priority_service")]
    public_found = len(public_items)
    public_recommended = sum(1 for item in public_items if item.get("repaired_bucket") == "recommended")
    public_needs_review = sum(1 for item in public_items if item.get("repaired_bucket") == "needs_review")
    public_low_quality = sum(1 for item in public_items if item.get("repaired_bucket") == "low_quality")
    public_repaired = sum(1 for item in public_items if item.get("public_priority_repaired"))
    public_blocked_body = sum(
        1 for item in public_items if item.get("public_priority_blocked_by_article_body")
    )

    return {
        "rescue_attempted": attempted,
        "rescue_successful": successful,
        "repaired_but_not_promoted": repaired_not_promoted,
        "repair_failed": repair_failed,
        "semantic_validation_failed": semantic_failed,
        "recommended_blocked_by_semantic_validation": recommended_blocked,
        "promoted_to_recommended_after_repair": promoted,
        "downgraded_after_semantic_validation": downgraded,
        "internal_services_kept_as_needs_review_or_rag_only": internal_kept,
        "true_low_quality_fragments": true_low_quality,
        "low_quality_rescue_attempted": lq_attempted,
        "low_quality_rescue_successful": lq_successful,
        "low_quality_repair_attempted": lq_attempted,
        "low_quality_repair_changed_fields": lq_changed,
        "low_quality_rescued_to_needs_review": lq_to_nr,
        "low_quality_rescued_to_recommended": lq_to_rec,
        "low_quality_repair_failed": lq_failed,
        "public_priority_found": public_found,
        "public_priority_recommended": public_recommended,
        "public_priority_needs_review": public_needs_review,
        "public_priority_low_quality": public_low_quality,
        "public_priority_repaired": public_repaired,
        "public_priority_blocked_by_article_body": public_blocked_body,
        "priority_service_diagnostics": build_priority_rescue_diagnostics(results),
    }

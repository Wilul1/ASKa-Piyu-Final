"""Render Citizen's Charter Extract & Structure preview from V2 services.

The Full Extraction Result / downloadable extraction TXT for citizen_charter
(and service_process) profiles must come from geometry-first V2 structured
services — not the older flattened text parser.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.citizen_charter_extractor_v2 import (
    NEEDS_REVIEW,
    _normalize_space,
    _split_time_and_person_cells,
)
from app.services.citizen_charter_services import _BLANK_REQUIREMENTS_LINE

_OFFICE_SUFFIX_RE = re.compile(
    r"^(?P<req>.+)\s+(?P<office>"
    r"(?:Registrar(?:['’]?s)?\s+Office|Business\s+Affairs\s+Office|Cashier(?:['’]?s)?\s+Office|"
    r"Guidance\s+Office|Library|OSAS|NSTP\s+Office|Dean(?:['’]?s)?\s+Office|"
    r"Office\s+of\s+the\s+[A-Z][\w\s&.\-']{2,60}|"
    r"[A-Z][\w&.\-']+(?:\s+[A-Z][\w&.\-']+){0,3}\s+(?:Office|Unit|Division|Section))"
    r")\s*$",
    re.I,
)

_REQ_OFFICE_FRAGMENT_RE = re.compile(
    r"^(?P<req>.+?)\s+(?P<head>"
    r"Registrar(?:['’]?s)?|Dean(?:['’]?s)?|NSTP|Cashier(?:['’]?s)?|Accounting|OSAS|Library|BAO|"
    r"Guidance|College\s+Registrar(?:['’]?s)?|Business\s+Affairs|Active\s+Files"
    r")\s*$",
    re.I,
)

_STRUCTURAL_BLOCKERS = frozenset(
    {
        "missing_office",
        "missing_who_may_avail",
        "missing_requirements",
        "no_step_rows",
        "no_complete_step",
        "missing_total_processing_time",
    }
)

_EXTRACTION_WARNINGS = frozenset(
    {
        "incomplete_requirement_pair",
        "partial_incomplete_steps",
    }
)

_PRIORITY_EXTRACTION_TITLES = (
    "ID Validation",
    "Processing of Student ID",
    "ID Processing",
    "LSPU Entrance Examination",
    "Assessment of Fees",
    "Library Circulation Service",
    "Library Reference Assistance",
    "Issuance of Good Moral Certificate",
    "Good Moral Certificate",
    "Scholarship and Financial Assistance",
)


def _placeholder(value: Any) -> bool:
    text = _normalize_space(value)
    return (not text) or text in {NEEDS_REVIEW, "[NEEDS REVIEW]", "Not specified"}


def _display(value: Any) -> str:
    text = _normalize_space(value)
    if _placeholder(text):
        return NEEDS_REVIEW
    return text


def _match_priority_title(title: str) -> str | None:
    cleaned = re.sub(r"^\d{1,3}[\.\)]\s*", "", _normalize_space(title)).strip()
    lower = cleaned.casefold()
    for name in _PRIORITY_EXTRACTION_TITLES:
        if name.casefold() == lower or name.casefold() in lower or lower in name.casefold():
            if name in {"ID Processing", "Processing of Student ID"}:
                return "Processing of Student ID"
            if name in {"Good Moral Certificate", "Issuance of Good Moral Certificate"}:
                return "Issuance of Good Moral Certificate"
            return name
    return None


def _repair_requirement_pair(requirement: str, where: str) -> tuple[str, str]:
    req = re.sub(r"^[\s\-–—⎯•●▪◦‣]+", "", _normalize_space(requirement)).strip()
    secure = _normalize_space(where)
    if req and _placeholder(secure):
        match = _OFFICE_SUFFIX_RE.match(req)
        if match:
            return _normalize_space(match.group("req")), _normalize_space(match.group("office"))
    if req and secure.casefold() == "office":
        frag = _REQ_OFFICE_FRAGMENT_RE.match(req)
        if frag:
            return (
                _normalize_space(frag.group("req")),
                f"{_normalize_space(frag.group('head'))} Office",
            )
    if req and re.search(r"\bBusiness\s*$", req, flags=re.I) and re.match(
        r"^Affairs\s+Office$", secure, flags=re.I
    ):
        return re.sub(r"\s+Business\s*$", "", req, flags=re.I).strip(), "Business Affairs Office"
    return req, secure


def _repair_time_person(ptime: str, person: str) -> tuple[str, str]:
    cleaned_time, cleaned_person = _split_time_and_person_cells(ptime, person)
    cleaned_person = re.sub(r"(?i)(?:^|/)\s*clientele\s*(?=/|$)", "/", cleaned_person)
    cleaned_person = cleaned_person.strip("/ ").strip()
    cleaned_person = re.sub(r"/{2,}", "/", cleaned_person)
    return cleaned_time, _normalize_space(cleaned_person)


def finalize_charter_v2_service_for_extraction(service: dict[str, Any]) -> dict[str, Any]:
    """Light extraction-time cleanup (no bucket / publish / rescue gates)."""
    out = dict(service or {})
    requirements: list[dict[str, Any]] = []
    for item in out.get("requirements") or []:
        if not isinstance(item, dict):
            continue
        req, where = _repair_requirement_pair(
            str(item.get("requirement") or ""),
            str(item.get("where_to_secure") or ""),
        )
        if _placeholder(req):
            continue
        if req.casefold() in {"none", "n/a", "na", "-", "—", "–", "nil"}:
            continue
        requirements.append(
            {
                "requirement": req,
                "where_to_secure": where if not _placeholder(where) else NEEDS_REVIEW,
            }
        )

    checklist_blank = bool(out.get("checklist_blank"))
    if not requirements and (
        checklist_blank
        or str((out.get("parser_debug") or {}).get("table_extraction_method") or "").startswith(
            "requirements"
        )
    ):
        checklist_blank = True

    steps: list[dict[str, Any]] = []
    for item in out.get("steps") or []:
        if not isinstance(item, dict):
            continue
        client = _normalize_space(item.get("client_step"))
        agency = _normalize_space(item.get("agency_action"))
        fees = _normalize_space(item.get("fees"))
        ptime = _normalize_space(item.get("processing_time"))
        person = _normalize_space(item.get("person_responsible"))
        ptime, person = _repair_time_person(ptime, person)
        if _placeholder(client) and _placeholder(agency):
            continue
        steps.append(
            {
                "client_step": client or NEEDS_REVIEW,
                "agency_action": agency or NEEDS_REVIEW,
                "fees": fees if not _placeholder(fees) else NEEDS_REVIEW,
                "processing_time": ptime if not _placeholder(ptime) else NEEDS_REVIEW,
                "person_responsible": person if not _placeholder(person) else NEEDS_REVIEW,
            }
        )

    # Merge OCR-split trailing client tokens: "Accept the validated" + "ID."
    merged_steps: list[dict[str, Any]] = []
    for step in steps:
        client = _normalize_space(step.get("client_step"))
        if merged_steps and _should_merge_client_continuation(
            client, _normalize_space(merged_steps[-1].get("client_step"))
        ):
            prev = merged_steps[-1]
            prev["client_step"] = f"{prev['client_step']} {client}".strip()
            for key in ("agency_action", "fees", "processing_time", "person_responsible"):
                if _placeholder(prev.get(key)) and not _placeholder(step.get(key)):
                    prev[key] = step[key]
            continue
        merged_steps.append(dict(step))

    out["requirements"] = requirements
    out["steps"] = merged_steps
    out["checklist_blank"] = checklist_blank
    blockers, warnings = classify_extraction_issues(out)
    out["extraction_blockers"] = blockers
    out["extraction_warnings"] = warnings
    quality = _normalize_space(out.get("extraction_quality")) or "low_quality"
    if blockers and quality == "clean":
        out["extraction_quality"] = "needs_review"
        out["extraction_quality_reason"] = (
            _normalize_space(out.get("extraction_quality_reason")) or "structural_blockers_present"
        )
        if out["extraction_quality_reason"] == "meets_clean_requirements":
            out["extraction_quality_reason"] = "structural_blockers_present"
    return out


def _should_merge_client_continuation(current: str, previous: str) -> bool:
    cur = _normalize_space(current)
    prev = _normalize_space(previous)
    if not cur or not prev or prev.endswith("."):
        return False
    if re.match(r"^\d{1,3}[\.\)]\s+", cur):
        return False
    # Require an explicit unfinished cue (not "any short line without a period").
    unfinished = bool(
        prev.endswith(("-", ",", "/"))
        or re.search(
            r"\b(?:the|of|and|or|for|to|by|with|a|an|from|into|certificate|validated|"
            r"filled(?:\s+out)?|accomplished|signed|completed|issued|required|"
            r"submitted|accepted|rendered|evaluated)\s*$",
            prev,
            flags=re.I,
        )
    )
    if not unfinished:
        return False
    words = cur.split()
    if len(words) > 1:
        return False
    if cur[:1].islower():
        return True
    return bool(re.fullmatch(r"[A-Za-z][\w'-]{0,24}\.?", cur))


def finalize_charter_v2_services_for_extraction(
    services: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    return [
        finalize_charter_v2_service_for_extraction(item)
        for item in (services or [])
        if isinstance(item, dict)
    ]


def _complete_step_count(steps: list[dict[str, Any]]) -> int:
    count = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        if (
            not _placeholder(step.get("client_step"))
            and not _placeholder(step.get("agency_action"))
            and not _placeholder(step.get("fees"))
            and not _placeholder(step.get("processing_time"))
            and not _placeholder(step.get("person_responsible"))
            and not str(step.get("person_responsible") or "").endswith("/")
        ):
            count += 1
    return count


def _service_issue_codes(service: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if _placeholder(service.get("office_division") or service.get("office")):
        issues.append("missing_office")
    if _placeholder(service.get("who_may_avail")):
        issues.append("missing_who_may_avail")
    reqs = service.get("requirements") or []
    if not reqs and not bool(service.get("checklist_blank")):
        issues.append("missing_requirements")
    incomplete_req = any(
        isinstance(r, dict)
        and not _placeholder(r.get("requirement"))
        and _placeholder(r.get("where_to_secure"))
        for r in reqs
    )
    if incomplete_req:
        issues.append("incomplete_requirement_pair")
    steps = [s for s in (service.get("steps") or []) if isinstance(s, dict)]
    complete = _complete_step_count(steps)
    if not steps:
        issues.append("no_step_rows")
    elif complete == 0:
        issues.append("no_complete_step")
    elif complete < len(steps):
        issues.append("partial_incomplete_steps")
    if _placeholder(service.get("total_processing_time")):
        issues.append("missing_total_processing_time")
    return issues


def classify_extraction_issues(service: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Split structural blockers from minor warnings.

    Only blockers prevent Extraction Status: clean.
    """
    codes = _service_issue_codes(service)
    blockers = [c for c in codes if c in _STRUCTURAL_BLOCKERS]
    warnings = [c for c in codes if c in _EXTRACTION_WARNINGS]
    # Any unexpected codes default to blockers so we never hide structural problems.
    for code in codes:
        if code not in _STRUCTURAL_BLOCKERS and code not in _EXTRACTION_WARNINGS:
            blockers.append(code)
    return blockers, warnings


def _service_blockers(service: dict[str, Any]) -> list[str]:
    """Backward-compatible: structural blockers only (warnings excluded)."""
    blockers, _warnings = classify_extraction_issues(service)
    return blockers


def build_extraction_priority_diagnostics(
    services: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    by_title: dict[str, dict[str, Any]] = {}
    for service in services or []:
        if not isinstance(service, dict):
            continue
        finalized = finalize_charter_v2_service_for_extraction(service)
        title = str(finalized.get("service_title") or "")
        matched = _match_priority_title(title)
        if not matched:
            # Placeholder "ID Validation" may coexist with a wrongly titled structured
            # sibling; still prefer matching known priority names in parser_debug.
            debug_title = str((finalized.get("parser_debug") or {}).get("detected_service_title") or "")
            matched = _match_priority_title(debug_title)
        if not matched:
            continue
        steps = [s for s in (finalized.get("steps") or []) if isinstance(s, dict)]
        reqs = [r for r in (finalized.get("requirements") or []) if isinstance(r, dict)]
        blockers = list(finalized.get("extraction_blockers") or _service_blockers(finalized))
        quality = str(finalized.get("extraction_quality") or "low_quality")
        merge_flag = None
        debug = finalized.get("parser_debug") or {}
        if isinstance(debug, dict):
            if debug.get("title_bound_to_structured_block") or debug.get("merge") == (
                "title_bound_to_structured_block"
            ):
                merge_flag = "title_bound_to_structured_block"
        entry = {
            "title": matched,
            "found": True,
            "office_detected": not _placeholder(
                finalized.get("office_division") or finalized.get("office")
            ),
            "requirements_count": len(reqs),
            "complete_step_count": _complete_step_count(steps),
            "total_processing_time_detected": not _placeholder(
                finalized.get("total_processing_time")
            ),
            "extraction_status": quality,
            "main_blockers": blockers[:6],
            "extraction_blockers": blockers[:6],
            "extraction_warnings": list(finalized.get("extraction_warnings") or [])[:6],
        }
        if merge_flag:
            entry["merge"] = merge_flag
        prev = by_title.get(matched)
        score = {"clean": 3, "needs_review": 2, "low_quality": 1, "rag_only": 0}.get(quality, 0)
        richness = (
            score * 100
            + int(entry["complete_step_count"]) * 10
            + int(entry["requirements_count"])
            + (5 if entry["office_detected"] else 0)
            + (3 if entry["total_processing_time_detected"] else 0)
            + (20 if merge_flag else 0)
        )
        prev_richness = -1
        if prev is not None:
            prev_score = {"clean": 3, "needs_review": 2, "low_quality": 1, "rag_only": 0}.get(
                str(prev.get("extraction_status") or ""), 0
            )
            prev_richness = (
                prev_score * 100
                + int(prev.get("complete_step_count") or 0) * 10
                + int(prev.get("requirements_count") or 0)
                + (5 if prev.get("office_detected") else 0)
                + (3 if prev.get("total_processing_time_detected") else 0)
                + (20 if prev.get("merge") else 0)
            )
        if prev is None or richness >= prev_richness:
            by_title[matched] = entry

    diagnostics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in (
        "ID Validation",
        "Processing of Student ID",
        "LSPU Entrance Examination",
        "Assessment of Fees",
        "Library Circulation Service",
        "Library Reference Assistance",
        "Issuance of Good Moral Certificate",
        "Scholarship and Financial Assistance",
    ):
        if name in seen:
            continue
        seen.add(name)
        if name in by_title:
            diagnostics.append(by_title[name])
        else:
            diagnostics.append(
                {
                    "title": name,
                    "found": False,
                    "office_detected": False,
                    "requirements_count": 0,
                    "complete_step_count": 0,
                    "total_processing_time_detected": False,
                    "extraction_status": "not_found",
                    "main_blockers": ["service_not_detected"],
                    "extraction_blockers": ["service_not_detected"],
                    "extraction_warnings": [],
                }
            )
    return diagnostics


def render_charter_v2_service_block(service: dict[str, Any]) -> str:
    """Render one V2 service in the Extract & Structure preview format."""
    data = finalize_charter_v2_service_for_extraction(service)
    title = _display(data.get("service_title") or data.get("detected_service_title"))
    office = _display(data.get("office_division") or data.get("office"))
    classification = _display(data.get("classification"))
    transaction = _display(data.get("transaction_type"))
    who = _display(data.get("who_may_avail"))
    total_time = _display(data.get("total_processing_time"))
    lines = [
        f"Office: {office}",
        f"Service: {title}",
        f"Classification: {classification}",
        f"Transaction Type: {transaction}",
        f"Who May Avail: {who}",
        "Requirements:",
    ]
    requirements = data.get("requirements") or []
    if requirements:
        for item in requirements:
            if not isinstance(item, dict):
                continue
            lines.append(f"  - Requirement: {_display(item.get('requirement'))}")
            lines.append(f"    Where to Secure: {_display(item.get('where_to_secure'))}")
    elif bool(data.get("checklist_blank")):
        lines.append(f"  {_BLANK_REQUIREMENTS_LINE}")
    else:
        lines.append(f"  - Requirement: {NEEDS_REVIEW}")
        lines.append(f"    Where to Secure: {NEEDS_REVIEW}")

    lines.append("Steps:")
    steps = [s for s in (data.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        lines.append(f"  1. Client Step: {NEEDS_REVIEW}")
        lines.append(f"     Agency Action: {NEEDS_REVIEW}")
        lines.append(f"     Fees: {NEEDS_REVIEW}")
        lines.append(f"     Processing Time: {NEEDS_REVIEW}")
        lines.append(f"     Responsible Personnel: {NEEDS_REVIEW}")
    else:
        for idx, step in enumerate(steps, start=1):
            if idx > 1:
                lines.append("")
            lines.append(f"  {idx}. Client Step: {_display(step.get('client_step'))}")
            lines.append(f"     Agency Action: {_display(step.get('agency_action'))}")
            lines.append(f"     Fees: {_display(step.get('fees'))}")
            lines.append(f"     Processing Time: {_display(step.get('processing_time'))}")
            lines.append(
                f"     Responsible Personnel: {_display(step.get('person_responsible'))}"
            )

    lines.append(f"Total Processing Time: {total_time}")
    quality = _normalize_space(data.get("extraction_quality")) or "low_quality"
    reason = _normalize_space(data.get("extraction_quality_reason"))
    blockers = list(data.get("extraction_blockers") or [])
    warnings = list(data.get("extraction_warnings") or [])
    if quality != "clean" or blockers or warnings:
        lines.append(f"Extraction Status: {quality}")
        if reason:
            lines.append(f"Extraction Reason: {reason}")
        if blockers:
            lines.append(f"Main Blockers: {', '.join(blockers)}")
            lines.append(f"Extraction Blockers: {', '.join(blockers)}")
        if warnings:
            lines.append(f"Extraction Warnings: {', '.join(warnings)}")
    return "\n".join(lines)


def render_extraction_priority_diagnostics_section(
    diagnostics: list[dict[str, Any]] | None,
) -> str:
    lines = [
        "=" * 48,
        "Priority Service Extraction Diagnostics",
        "=" * 48,
    ]
    for item in diagnostics or []:
        title = item.get("title") or "Unknown"
        found = "yes" if item.get("found") else "no"
        office = "yes" if item.get("office_detected") else "no"
        total = "yes" if item.get("total_processing_time_detected") else "no"
        blockers = item.get("main_blockers") or []
        blocker_text = ", ".join(str(b) for b in blockers) if blockers else "none"
        lines.extend(
            [
                f"- {title}",
                f"  found: {found}",
                f"  office detected: {office}",
                f"  requirements count: {item.get('requirements_count', 0)}",
                f"  complete step count: {item.get('complete_step_count', 0)}",
                f"  total processing time detected: {total}",
                f"  extraction status: {item.get('extraction_status') or 'unknown'}",
                f"  main blockers: {blocker_text}",
            ]
        )
        if item.get("merge"):
            lines.append(f"  merge: {item.get('merge')}")
        warnings = item.get("extraction_warnings") or []
        if warnings:
            lines.append(f"  extraction warnings: {', '.join(str(w) for w in warnings)}")
    return "\n".join(lines)


def render_citizen_charter_v2_extraction_text(
    services: list[dict[str, Any]] | None,
    *,
    include_priority_diagnostics: bool = True,
) -> str:
    """Full Extraction Result body from V2 structured services."""
    finalized = finalize_charter_v2_services_for_extraction(services)
    if not finalized:
        return ""
    blocks = [render_charter_v2_service_block(service) for service in finalized]
    text = ("\n\n" + ("-" * 48) + "\n\n").join(blocks)
    if include_priority_diagnostics:
        diagnostics = build_extraction_priority_diagnostics(finalized)
        text = f"{text}\n\n{render_extraction_priority_diagnostics_section(diagnostics)}"
    return text.strip()

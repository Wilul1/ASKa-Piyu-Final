"""OCR text cleaning utilities for ASKa-Piyu.

This module is intentionally rule-light: it normalizes noisy OCR text without
trying to hardcode one exact document layout. The structuring layer can then use
cleaner text for dynamic extraction.
"""
from __future__ import annotations

import difflib
import re
from typing import Iterable

# Common OCR mistakes observed in scanned university service documents.
# These are safe corrections because they target obvious OCR noise, not policy meaning.
OCR_REPLACEMENTS: dict[str, str] = {
    "Philippincs": "Philippines",
    "philippincs": "Philippines",
    "#tatc": "State",
    "tatc": "State",
    "Polptcchnic": "Polytechnic",
    "Polptecnic": "Polytechnic",
    "Polptechnic": "Polytechnic",
    "Polvtechnic": "Polytechnic",
    "Univcrsity": "University",
    "Univcrsily": "University",
    "Universily": "University",
    "Unlversity": "University",
    "Tochnoloay": "Technology",
    "Nomo": "Name",
    "Collcec/Omcc": "College/Office",
    "Duic": "Date",
    "Dale": "Date",
    "Venve": "Venue",
    "Fma": "Time",
    "Scnvices Needed": "Services Needed",
    "Acceivcd By": "Received By",
    "Acceivcd": "Received",
    "Approved Dy": "Approved By",
    "Printod Mume 5 Enatute": "Printed Name & Signature",
    "Sarvicing": "Servicing",
    "Chjirpurson": "Chairperson",
    "Aukust": "August",
    "Tesling": "Testing",
    "tesling": "testing",
    "Oltico": "Office",
    "Olfice": "Office",
    "Ofiica": "Office",
    "Omics": "Office",
    "Divieion": "Division",
    "Divsioni": "Division",
    "Divisioni": "Division",
    "Classifcation": "Classification",
    "claaaificaton": "Classification",
    "clasalicaton": "Classification",
    "Simplo": "Simple",
    "Simplo": "Simple",
    "Typo Transaction": "Type Transaction",
    "Transacuont": "Transaction",
    "Transacuon": "Transaction",
    "Traneacton": "Transaction",
    "Unirance": "Entrance",
    "Ecteancc": "Entrance",
    "Ecteancs": "Entrance",
    "Eatrance": "Entrance",
    "Cotleoe": "College",
    "Onentation": "Orientation",
    "interpretalion": "interpretation",
    "minules": "minutes",
    "minules": "minutes",
    "mTnUlUS": "minutes",
    "IRepont": "Report",
    "repont": "report",
    "repont;": "report;",
    "pfficial": "official",
    "resuli": "result",
    "relerral": "referral",
    "referraB": "referral",
    "refera": "referral",
    "senvice": "service",
    "brieling": "briefing",
    "lest": "test",
    "sludent": "student",
    "Studenis": "Students",
    "Faculy": "Faculty",
    "Applcants": "Applicants",
    "Identtication": "Identification",
    "Identtfication": "Identification",
    "Puvacy": "Privacy",
    "Gurdance": "Guidance",
    "Gudance": "Guidance",
    "Clent": "Client",
    "Cicnt": "Client",
    "Onlne": "Online",
    "LOnline": "Online",
    "appiication": "application",
    "Acmission": "Admission",
    "Certlied": "Certified",
    "andlor": "and/or",
    "Ihe": "the",
    "IMe": "the",
    "Hesktop": "desktop",
    "inteins": "interns",
    "Stali": "Staff",
    "personne": "personnel",
    "personnell": "personnel",
    "malyavaiE": "May Avail",
    "T-Znours": "1-2 hours",
    "hrand": "hr and",
    "626": "G2G",
    "62C": "G2C",
    "6G2G": "G2G",
}

# Conservative OCR word-split repair. These pairs target common broken
# morphemes where the separated left token is rarely meaningful on its own.
OCR_SPLIT_JOIN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ap", "plicant|plication|plied|proval"),
    ("cam", "pus(?:es)?"),
    ("com", "pleted|pletion|plete|pliance|mittee"),
    ("follow", "ing"),
    ("lim", "ited|its?|itations?"),
    ("psy", "chological|chology|chiatric"),
    ("readi", "ness|ly"),
    ("require", "ments?"),
    ("docu", "ments?|mentation"),
    ("enroll", "ment|ments?"),
    ("admis", "sion|sions"),
    ("regis", "tration|trar"),
    ("classi", "fication|fied|fy"),
    ("quali", "fication|fied|ty"),
    ("certi", "ficate|fication|fied"),
    ("devel", "opment|oped|oping"),
    ("uni", "versit(?:y|ies)"),
)

TABLE_HEADERS = [
    "CLIENT STEPS", "AGENCY ACTIONS", "AGENCY ACTIONS", "AGENCY", "FEES TO BE PAID",
    "FEES TO BE", "TO BE PAID", "PROCESSING TIME", "PERSON RESPONSIBLE",
    "RESPONSIBLE PERSON ACTIONS", "RESPONSIBLE PERSONNEL", "RESPONSIBLE PERSON",
    "PAID", "CHECKLIST OF REQUIREMENTS",
    "WHERE TO SECURE",
]

CANONICAL_FORM_HEADERS = [
    "Office or Division",
    "Service",
    "Classification",
    "Transaction Type",
    "Who May Avail",
    "Checklist of Requirements",
    "Where to Secure",
    "Client Steps",
    "Agency Actions",
    "Fees to be Paid",
    "Processing Time",
    "Responsible Personnel",
]


def _replace_many(text: str, replacements: dict[str, str]) -> str:
    for wrong, right in replacements.items():
        text = text.replace(wrong, right)
    return text


def repair_ocr_word_splits(text: str) -> str:
    """Rejoin high-confidence OCR word splits without using a guessing dictionary."""
    if not text:
        return ""
    for prefix, suffix_pattern in OCR_SPLIT_JOIN_PATTERNS:
        text = re.sub(
            rf"\b({prefix})\s+({suffix_pattern})\b",
            lambda match: match.group(1) + match.group(2),
            text,
            flags=re.I,
        )
    return text


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fix_hyphenated_line_breaks(text: str) -> str:
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def _fix_inline_hyphen_word_breaks(text: str) -> str:
    """Join OCR/PDF hyphen splits that appear on the same line (e.g. 'appertain- ing')."""
    return re.sub(r"(\w)-\s+(\w)", r"\1\2", text)


# Roman-numeral major section markers used by policy manuals (I., II., …).
# Require Title Case after the numeral so middle initials like "C. CALLO" do not match.
_ROMAN_SECTION_RE = re.compile(r"\b([IVX]+)\.\s+[A-Z][a-z]+")
_BREADCRUMB_RE = re.compile(r"\s+>\s+")
_PAGE_MARKER_RE = re.compile(r"^Page\s*:\s*\d+\s*$", re.I)
_PART_ONLY_RE = re.compile(r"^Part\s+\d+\s*$", re.I)
_PART_SUFFIX_RE = re.compile(r"\s+-\s+Part\s+\d+\s*$", re.I)
_SEPARATOR_RE = re.compile(r"^[-–—]{2,}\s*$")
# Numbered leaf in a breadcrumb path, e.g. "1.2.1" or "Section 6.0".
_BREADCRUMB_NUMBER_RE = re.compile(
    r"^(?:Section\s+)?(\d+(?:\.\d+)*)\.?\s*$",
    re.I,
)
_TITLE_CASE_WORD_RE = re.compile(r"^[A-Z][A-Za-z'’]*$")
_LOWERCASE_START_RE = re.compile(r"^[a-z]")
# Major section heading at line start (allows all-caps titles).
_MAJOR_SECTION_LINE_RE = re.compile(r"^[IVXLCDM]+\.\s+\S")
_MAJOR_SECTION_KEY_RE = re.compile(r"^([IVXLCDM]+)\.\s+")


def _is_separator_or_page_artifact(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _SEPARATOR_RE.match(stripped):
        return True
    if _PAGE_MARKER_RE.match(stripped):
        return True
    if _PART_ONLY_RE.match(stripped):
        return True
    return False


def _is_toc_contamination(line: str) -> bool:
    """Detect jammed TOC rows that splice unrelated section titles together."""
    stripped = line.strip()
    if not stripped or len(stripped) < 40:
        return False
    roman_hits = _ROMAN_SECTION_RE.findall(stripped)
    if len(roman_hits) >= 2:
        return True
    # Ellipsis / dotted leaders between titles (common in PDF TOC extracts).
    if "..." in stripped and _ROMAN_SECTION_RE.search(stripped):
        return True
    return False


def _strip_part_suffix(line: str) -> str:
    return _PART_SUFFIX_RE.sub("", line.strip()).strip()


def _normalize_breadcrumb_line(line: str) -> str | None:
    """
    Collapse extraction breadcrumb paths.

    Returns:
    - None to drop the line (duplicate path or pure navigation noise)
    - a reconstructed numbered lead-in when the leaf is a truncated fragment heading
    - the leaf text when it is a real unique heading
    """
    parts = [p.strip() for p in _BREADCRUMB_RE.split(line.strip()) if p.strip()]
    if len(parts) < 2:
        return line.strip()

    # Duplicate section labels: "II. Foo > II. Foo"
    if len(parts) == 2 and parts[0].casefold() == parts[1].casefold():
        return None

    leaf = parts[-1]
    number = None
    for part in reversed(parts[:-1]):
        match = _BREADCRUMB_NUMBER_RE.match(part)
        if match:
            number = match.group(1)
            break

    # Truncated Title Case leaf: reconstruct numbered lead-in for joining.
    if _heading_leaf_is_truncated(leaf):
        if number:
            return f"{number}. {leaf.lower()}" if leaf else None
        return None

    # Real leaf heading from a path: prefer numbered form when available.
    if number:
        return f"{number}. {leaf}"

    # Parent incorrectly prefixed onto a later subsection.
    if any(p.casefold() == leaf.casefold() for p in parts[:-1]):
        return leaf

    return leaf


def _looks_like_title_case_heading(line: str) -> bool:
    words = [w for w in re.split(r"\s+", line.strip()) if w]
    if len(words) < 3:
        return False
    # Allow short connectors inside title-case headings.
    connectors = {"a", "an", "the", "of", "on", "in", "for", "to", "and", "or", "by", "as"}
    title_like = 0
    for word in words:
        bare = word.strip(".,;:()[]\"'/")
        if not bare:
            continue
        if bare.casefold() in connectors:
            title_like += 1
            continue
        if _TITLE_CASE_WORD_RE.match(bare) or bare.isupper():
            title_like += 1
        else:
            return False
    return title_like >= 3


def _looks_like_truncated_title_case_heading(line: str) -> bool:
    """Heuristic: Title Case line that ends mid-word (no terminal punctuation)."""
    stripped = line.strip()
    if not stripped or stripped[-1] in ".:;!?":
        return False
    if re.match(r"^[IVXLCDM]+\.\s+\S", _strip_part_suffix(stripped)):
        return False
    if not _looks_like_title_case_heading(stripped):
        return False
    last = re.split(r"\s+", stripped)[-1].strip(".,;:()[]\"'/")
    if not last or len(last) < 2:
        return True
    # Truncated OCR/PDF heading slices often end on a short stem (Col, Chan, Con).
    vowels = set("aeiouAEIOU")
    if len(last) <= 4 and not last.isupper():
        return True
    if len(last) <= 6 and last[-1] not in "sydnegrt" and sum(ch in vowels for ch in last) <= 1:
        return True
    return False


def _heading_leaf_is_truncated(leaf: str) -> bool:
    """True when a heading leaf ends on a mid-word stem (with or without Title Case)."""
    stripped = leaf.strip()
    if not stripped or stripped[-1] in ".:;!?":
        return False
    if _MAJOR_SECTION_LINE_RE.match(_strip_part_suffix(stripped)):
        return False
    if _looks_like_truncated_title_case_heading(stripped):
        return True
    last = re.split(r"\s+", stripped)[-1].strip(".,;:()[]\"'/")
    if not last:
        return True
    # After lowercasing a reconstructed leaf, still detect short trailing stems.
    return bool(len(last) <= 4 and last.isalpha() and not last.isupper())


def _is_major_section_heading(line: str) -> bool:
    return bool(_MAJOR_SECTION_LINE_RE.match(_strip_part_suffix(line)))


def _major_section_key(line: str) -> str | None:
    match = _MAJOR_SECTION_KEY_RE.match(_strip_part_suffix(line))
    return match.group(1).upper() if match else None


def _roman_value(roman: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(roman.upper()):
        val = values.get(ch, 0)
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total


def _join_truncated_heading_with_continuation(heading: str, continuation: str) -> str:
    """Join '… About A Col' + 'league or…' → '… About A Colleague or…'."""
    h = heading.rstrip()
    c = continuation.lstrip()
    if not h or not c:
        return f"{h} {c}".strip()
    # If heading already includes a reconstructed number prefix, keep it.
    h_words = h.split()
    c_first, _, c_rest = c.partition(" ")
    last = h_words[-1]
    # Mid-word split across the heading/continuation boundary.
    if last and c_first and last[0].isalpha() and c_first[0].islower():
        merged_last = last + c_first
        # Preserve capitalization of the stem when it was Title Case.
        if last[0].isupper() and len(last) <= 6:
            merged_last = merged_last[0].upper() + merged_last[1:]
        joined = " ".join(h_words[:-1] + [merged_last])
        return f"{joined} {c_rest}".strip() if c_rest else joined
    return f"{h} {c}".strip()


def clean_rag_extraction_text(text: str) -> str:
    """
    Clean PDF/OCR extraction text for RAG indexing.

    Applies general heuristics only (no document-specific hardcoded titles):
    - drop TOC mashups, page/part markers, and separator lines
    - drop duplicate breadcrumb section labels and truncated fragment headings
    - repair hyphenated word breaks
    - drop stale major-section restarts that belong to an earlier section number
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _fix_hyphenated_line_breaks(text)
    text = _fix_inline_hyphen_word_breaks(text)

    raw_lines = text.split("\n")
    pending_fragment: str | None = None
    seen_major_sections: set[str] = set()
    highest_major = 0
    out: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_fragment
        if pending_fragment:
            out.append(pending_fragment)
            pending_fragment = None

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        stripped = line.strip()

        if not stripped:
            # Keep pending truncated fragments across blank lines so they can
            # join with a following lowercase continuation.
            if pending_fragment is None:
                out.append("")
            i += 1
            continue

        if _is_separator_or_page_artifact(stripped):
            i += 1
            continue

        if _is_toc_contamination(stripped):
            i += 1
            continue

        stripped = _strip_part_suffix(stripped)
        if not stripped:
            i += 1
            continue

        # Breadcrumb / hierarchy path lines from structured extractors.
        if " > " in stripped:
            normalized = _normalize_breadcrumb_line(stripped)
            if normalized is None:
                # Duplicate path — if we already hold a matching fragment, keep it.
                i += 1
                continue
            leaf = re.sub(r"^\d+(?:\.\d+)*\.\s+", "", normalized)
            if _heading_leaf_is_truncated(leaf):
                pending_fragment = normalized
                i += 1
                continue
            # Non-truncated leaf heading from a path: keep once (preferably numbered).
            flush_pending()
            stripped = normalized

        # Standalone truncated Title Case fragment headings.
        # Also drop Title Case lines that only duplicate the next breadcrumb leaf
        # (generated fragment headings from structured extractors).
        if _looks_like_title_case_heading(stripped) or _looks_like_truncated_title_case_heading(
            stripped
        ):
            j = i + 1
            while j < len(raw_lines) and not raw_lines[j].strip():
                j += 1
            nxt = raw_lines[j].strip() if j < len(raw_lines) else ""
            nxt = _strip_part_suffix(nxt)
            if " > " in nxt:
                leaf = [p.strip() for p in _BREADCRUMB_RE.split(nxt) if p.strip()][-1]
                if leaf.casefold() == stripped.casefold():
                    if _is_major_section_heading(stripped):
                        # Keep the real major heading; breadcrumb duplicate drops later.
                        pass
                    else:
                        # Drop generated Title Case duplicate; breadcrumb keeps leaf once.
                        i += 1
                        continue
            if _looks_like_truncated_title_case_heading(stripped):
                pending_fragment = stripped
                i += 1
                continue

        # Stale major-section restart (earlier roman numeral after a later one).
        major = _major_section_key(stripped)
        if major and _is_major_section_heading(stripped):
            value = _roman_value(major)
            if major in seen_major_sections and value < highest_major:
                # Duplicate earlier section label injected into later content.
                i += 1
                continue
            if major in seen_major_sections and stripped.casefold() in {
                x.casefold() for x in out if _is_major_section_heading(x)
            }:
                i += 1
                continue
            seen_major_sections.add(major)
            highest_major = max(highest_major, value)

        # Join pending truncated fragment with lowercase continuation.
        if pending_fragment and _LOWERCASE_START_RE.match(stripped):
            joined = _join_truncated_heading_with_continuation(pending_fragment, stripped)
            pending_fragment = None
            out.append(joined)
            i += 1
            continue

        flush_pending()
        out.append(stripped)
        i += 1

    flush_pending()

    # Second pass: drop exact duplicate consecutive headings / blank spam.
    deduped: list[str] = []
    prev_nonempty = ""
    for line in out:
        if not line.strip():
            if deduped and deduped[-1] == "":
                continue
            deduped.append("")
            continue
        if line.casefold() == prev_nonempty.casefold() and _is_major_section_heading(line):
            continue
        deduped.append(line)
        prev_nonempty = line

    text = "\n".join(deduped)
    text = _fix_inline_hyphen_word_breaks(text)
    text = repair_ocr_word_splits(text)
    return normalize_whitespace(text)


def _strip_repeated_headers_footers(text: str, page_texts: list[str]) -> str:
    if len(page_texts) < 2:
        return text

    counts: dict[str, int] = {}
    for page in page_texts:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        for candidate in set(lines[:3] + lines[-3:]):
            counts[candidate] = counts.get(candidate, 0) + 1

    threshold = max(2, int(len(page_texts) * 0.6))
    repeated = {line for line, count in counts.items() if count >= threshold}
    if not repeated:
        return text

    return "\n".join(line for line in text.splitlines() if line.strip() not in repeated)


def clean_ocr_text(text: str, remove_table_headers: bool = False) -> str:
    """Return cleaned OCR text while preserving enough context for extraction."""
    if not text:
        return ""
    text = _fix_hyphenated_line_breaks(text)
    text = _replace_many(text, OCR_REPLACEMENTS)
    text = repair_ocr_word_splits(text)
    text = _collapse_repeated_ocr_letters(text)
    text = _replace_many(text, OCR_REPLACEMENTS)
    text = repair_ocr_word_splits(text)
    # Normalize common separator mistakes.
    text = re.sub(r"\s*\|\s*", " | ", text)
    text = _normalize_form_labels(text)
    text = re.sub(r"\bN\s*/\s*A\b|\bn\s*/\s*a\b|\bNIA\b|\bn/a\b", "N/A", text)
    text = re.sub(r"1\s+3\s+days", "1-3 days", text, flags=re.I)
    text = re.sub(r"1-2\s+hoursand", "1-2 hours and", text, flags=re.I)
    text = re.sub(r"1\s+and\s+%", "1 and 1/2", text, flags=re.I)
    text = re.sub(r"1\s+and\s+½", "1 and 1/2", text, flags=re.I)
    text = re.sub(r"\bfirsttime\b", "first time", text, flags=re.I)
    text = re.sub(r"FacultyNon", "Faculty, Non-", text)
    text = re.sub(r"student-applicants", "Student-applicants", text, flags=re.I)
    text = _normalize_form_codes(text)

    if remove_table_headers:
        for h in TABLE_HEADERS:
            text = re.sub(re.escape(h), " ", text, flags=re.I)

    return normalize_whitespace(text)


def _normalize_form_codes(text: str) -> str:
    text = re.sub(r"\bLSPU\s+ICTS\s+5F\b", "LSPU-ICTS-SF", text, flags=re.I)
    text = re.sub(r"\bLSPU\s+ICTS\s+SF\b", "LSPU-ICTS-SF", text, flags=re.I)
    text = re.sub(r"\bLSPU[-\s]+ICTS[-\s]+5F\b", "LSPU-ICTS-SF", text, flags=re.I)
    text = re.sub(r"\bLSPU[-\s]+ICTS[-\s]+SF\b", "LSPU-ICTS-SF", text, flags=re.I)
    text = re.sub(r"\b(?:SF|5F)[-\s]*0[O0]1\b", "SF-001", text, flags=re.I)
    text = re.sub(r"\b(?:SF|5F)[-\s]*[O0]{2}1\b", "SF-001", text, flags=re.I)
    text = re.sub(r"\b(?:SF|5F)[-\s]*0[O0]2\b", "SF-002", text, flags=re.I)
    text = re.sub(r"\b(?:SF|5F)[-\s]*[O0]{2}2\b", "SF-002", text, flags=re.I)
    text = re.sub(r"\b(LSPU-ICTS)-5F-(\d{3})\b", r"\1-SF-\2", text, flags=re.I)
    text = re.sub(r"\b(LSPU-ICTS)-SF[-\s]*(\d{3})\b", lambda m: f"{m.group(1).upper()}-SF-{m.group(2)}", text, flags=re.I)
    return text


def _normalize_form_labels(text: str) -> str:
    text = _normalize_headers_fuzzy(text)
    text = re.sub(r"\bOffice\s+Division\b", "Office or Division:", text, flags=re.I)
    text = re.sub(r"\bOffice\s+or\s+Divisioni?\b", "Office or Division:", text, flags=re.I)
    text = re.sub(r":{2,}", ":", text)
    text = re.sub(r"\bClassification\s*:\s*\|\s*", "Classification: ", text, flags=re.I)
    text = re.sub(r"\bClassification\s*\|\s*", "Classification: ", text, flags=re.I)
    text = re.sub(r"\bTyp[eo]\s+Transaction\s*:\s*\|\s*", "Transaction Type: ", text, flags=re.I)
    text = re.sub(r"\bType\s*\|\s*([Gg]\d[GgCc])\s*Transaction\b", r"Transaction Type: \1", text)
    text = re.sub(r"\bType\s+Transaction\s*:\s*\|\s*", "Transaction Type: ", text, flags=re.I)
    text = re.sub(r"\bWho\s+(?:may\s*)?avail(?:E|l)?\b", "Who May Avail:", text, flags=re.I)
    text = re.sub(r"\bWho\s+(?=CHECK|Checklist|EcK)", "Who May Avail: ", text, flags=re.I)
    text = re.sub(
        r"\b(?:CHECKUISTOE\s+REQUIRET|EcKLIST\s+OF\s*REQUIREMENTS|EcKLESL\s+OF\s*REQUIREMENS|CHECKLIST\s+OF\s*REQUIREMENTS)\b",
        "Checklist of Requirements",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(?:UNERE\s+To\s+SECURE|WHERE\s+TO\s+SECURE|I7o\s*\|\s*UNERE\s+To\s+SECURE)\b",
        "Where to Secure",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bFEES\s+To\s+BE\b", "FEES TO BE", text, flags=re.I)
    text = re.sub(r"\bRESPONSIBLE\s+PERSON\b", "RESPONSIBLE PERSON", text, flags=re.I)
    text = re.sub(r":{2,}", ":", text)
    return text


def _collapse_repeated_ocr_letters(text: str) -> str:
    """Collapse long repeated trailing letters from OCR artifacts."""
    return re.sub(r"\b([A-Za-z]*?)([A-Za-z])\2{2,}\b", r"\1\2", text)


def _normalize_headers_fuzzy(text: str) -> str:
    """Fuzzy-normalize damaged schema headers without changing field values."""
    normalized_lines: list[str] = []
    for line in text.splitlines():
        normalized_lines.append(_normalize_header_line_fuzzy(line))
    return "\n".join(normalized_lines)


def _normalize_header_line_fuzzy(line: str) -> str:
    if not line.strip():
        return line
    if ":" in line and "|" not in line:
        return line

    parts = [part.strip() for part in re.split(r"(\|)", line)]
    changed = False
    for index, part in enumerate(parts):
        if part == "|" or not part:
            continue
        canonical = _closest_header(part)
        if canonical:
            parts[index] = canonical
            changed = True

    if changed:
        line = " ".join(parts)
        line = re.sub(r"\s*\|\s*", " | ", line)
    return line


def _closest_header(value: str) -> str | None:
    candidate = re.sub(r"[^A-Za-z ]", " ", value)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if not candidate:
        return None
    if candidate.upper().endswith("SERVICES") and candidate.upper() != "SERVICE":
        return None

    # Avoid treating ordinary values as headers.
    if len(candidate.split()) > 5:
        return None
    if len(candidate.split()) == 1:
        allowed_single_word_headers = {
            header.split()[0].upper()
            for header in CANONICAL_FORM_HEADERS
        }
        if candidate.upper() not in allowed_single_word_headers:
            return None

    choices = {header.upper(): header for header in CANONICAL_FORM_HEADERS}
    match = difflib.get_close_matches(candidate.upper(), choices.keys(), n=1, cutoff=0.72)
    return choices[match[0]] if match else None


# Backward-compatible aliases that other modules may already import.
def clean_text(text: str) -> str:
    return clean_ocr_text(text)


def normalize_ocr_text(text: str) -> str:
    return clean_ocr_text(text)


def clean_extracted_text(
    text: str = "",
    page_texts: list[str] | None = None,
) -> str:
    """
    Compatibility wrapper for OCR cleaning.

    Supports:
    - clean_extracted_text(text)
    - clean_extracted_text(page_texts=[...])
    """

    if page_texts:
        text = _strip_repeated_headers_footers("\n\n".join(page_texts), page_texts)

    # RAG extraction cleanup (TOC/breadcrumb/fragment artifacts) before OCR norms.
    text = clean_rag_extraction_text(text)
    return clean_ocr_text(text)


def split_into_chunks(
    text: str,
    *,
    max_chars: int = 1200,
    overlap: int = 150,
) -> list[dict]:
    if not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[dict] = []
    current = ""
    char_start = 0

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(
                {
                    "text": current,
                    "chunk_index": len(chunks),
                    "char_start": char_start,
                }
            )
            char_start += max(0, len(current) - overlap)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        else:
            chunks.append(
                {
                    "text": paragraph[:max_chars],
                    "chunk_index": len(chunks),
                    "char_start": char_start,
                }
            )
            current = paragraph[max_chars - overlap :]

    if current:
        chunks.append(
            {
                "text": current,
                "chunk_index": len(chunks),
                "char_start": char_start,
            }
        )

    return chunks

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
    "ICTSERVICES": "ICT SERVICES",
    "Tochnoloay": "Technology",
    "phoro Video": "Photo/Video",
    "Phoro Video": "Photo/Video",
    "Interner": "Internet",
    "Connecion": "Connection",
    "Visuai": "Visual",
    "Preecnudlion": "Presentation",
    "Encading": "Encoding",
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
    "CLIENT STEPS", "AGENCY ACTIONS", "AGENCY", "FEES TO BE PAID",
    "FEES TO BE", "PROCESSING TIME", "PERSON RESPONSIBLE",
    "RESPONSIBLE PERSON ACTIONS", "PAID", "CHECKLIST OF REQUIREMENTS",
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

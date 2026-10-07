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

# --- Generic TOC-entry / heading-candidate detection (2026-10-05) ----------
#
# "Faculty Official Time ........ 12" / "Submission of Grades    15" style
# rows: a short heading-like phrase followed by a bare page number, with
# or without dot/space leaders in between. Deliberately generic -- matches
# on SHAPE only, never a specific document's section names or page-number
# range -- so it works for any PDF's table of contents, not one document.
_TOC_ENTRY_DOTTED_RE = re.compile(r"(?:\.{2,}|…)\s*\|?\s*\d{1,4}\s*$")
# A dot/ellipsis LEADER with no trailing page number at all -- real PDF
# extraction commonly puts the title+leader on one line and the page
# number on the NEXT line entirely (or drops it). Requires a visually
# substantial leader (4+ dots, or 2+ ellipsis characters) so an ordinary
# sentence trailing off with "..." (exactly 3 dots) is never matched.
_TOC_LEADER_ONLY_RE = re.compile(r"^(?P<title>.+?\S)\s*(?:\.{4,}|…{2,})\s*$")
_TOC_ENTRY_BARE_RE = re.compile(r"^([A-Z][A-Za-z0-9 ,&'()/.-]{2,90})\s+(\d{1,4})\s*$")
_CHAPTER_ARTICLE_NUMBERING_RE = re.compile(r"^(?:chapter|article|section|part)$", re.I)
_TOC_NOISE_WORDS_RE = re.compile(
    r"\b(page|year|no\.?|percent|grade|gwa|minutes?|hours?|process|wherein|acceptable|time)\b",
    re.I,
)
_ALLCAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 ,&'()/.-]{2,80}$")
_ARTICLE_CHAPTER_HEADING_RE = re.compile(
    r"^(?:article|chapter|section|part)\s+[IVXLCDM0-9]+[:.]?\s*\S", re.I
)
_DECIMAL_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z]\S")


def _toc_title_is_plausible(title: str) -> bool:
    title = (title or "").strip()
    if not title:
        return False
    if re.search(r"[.!?:;|]$", title):
        return False
    if _TOC_NOISE_WORDS_RE.search(title):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", title)
    if not (1 <= len(words) <= 8):
        return False
    title_like = sum(1 for w in words if w[:1].isupper() or w.isupper())
    return title_like / len(words) >= 0.6


def looks_like_toc_entry_line(line: str) -> bool:
    """True for a single line shaped like one table-of-contents row.

    A single matching line is NOT, on its own, grounds to remove anything
    -- see remove_toc_blocks, which requires a dense run of several such
    lines close together before dropping anything, so an isolated real
    heading that happens to end in a number (e.g. "Appendix 1") is never
    touched just because it matches this shape test once.
    """
    stripped = (line or "").strip()
    if not stripped:
        return False
    if len(stripped) <= 140 and _TOC_ENTRY_DOTTED_RE.search(stripped):
        return True
    if len(stripped) <= 140:
        leader_match = _TOC_LEADER_ONLY_RE.match(stripped)
        if leader_match and _toc_title_is_plausible(leader_match.group("title")):
            return True
    match = _TOC_ENTRY_BARE_RE.match(stripped)
    if not match:
        return False
    title = match.group(1)
    if _CHAPTER_ARTICLE_NUMBERING_RE.match(title.strip()):
        # "Chapter 1" / "Article 9" / "Section 3" / "Part 2" -- this is a
        # real section-numbering heading convention, not a TOC "title
        # followed by a page number" row (which this bare, leader-less
        # shape would otherwise also match): a document's OWN "Chapter
        # 1" heading, immediately introducing its own body paragraph,
        # must never be mistaken for the TOC's "Chapter 1 .... 4" entry
        # just because they share this shape once the leader is gone.
        return False
    return _toc_title_is_plausible(title)


_TOC_HEADING_CORE_RE = re.compile(
    r"^(?:(?:table\s+of\s+)?contents|list\s+of\s+(?:services|tables|figures|appendices|annexes)|index)\b",
    re.I,
)
_TOC_ANCHOR_SUFFIX_RE = re.compile(r"[\s.…]{2,}(?:[ivxlcdm]{1,6}|\d{1,4})?\s*$", re.I)
_TOC_BODY_PROSE_MIN_CHARS = 80


def _is_toc_heading_anchor_line(line: str) -> bool:
    """True for a "Contents" / "Table of Contents" heading line, even
    when -- as real PDF extraction often renders it -- the heading
    itself carries its own trailing dot-leader and/or same-line page
    self-reference, e.g. "Contents .......... ii": the TOC's own
    self-listing is still unambiguous evidence of the TOC heading for
    anchor purposes.
    """
    stripped = (line or "").strip()
    if not stripped or len(stripped) > 60:
        return False
    core = _TOC_ANCHOR_SUFFIX_RE.sub("", stripped).strip()
    return bool(_TOC_HEADING_CORE_RE.match(core)) and len(core) <= 25


def looks_like_toc_region_row(line: str) -> bool:
    """Broader than looks_like_toc_entry_line: true for anything that
    could plausibly be ONE ROW of a table of contents, whether or not a
    page number survived onto the same line at all.

    Real PDF text extraction frequently drops a TOC row's page number
    onto its own separate line (or a separate column that lands far away
    in reading order), or loses it entirely -- so matching only a
    dotted-leader/trailing-page-number shape (looks_like_toc_entry_line)
    misses most real-world TOC rows. A short heading-shaped line (Title
    Case / ALL CAPS / roman-numeral / decimal / "Article"/"Chapter"
    -prefixed -- see is_heading_candidate) is just as much a TOC-row
    candidate, since that is exactly what a TOC entry's title portion
    looks like on its own. Still only ever used by remove_toc_blocks,
    which requires a DENSE RUN of such rows (or an explicit "Contents"
    heading immediately followed by one) before anything is removed --
    see that function's docstring for the full false-positive model.
    """
    return is_heading_candidate(line) or looks_like_toc_entry_line(line)


_BARE_SECTION_MARKER_RE = re.compile(
    r"^(?:[IVXLCDM]{1,6}\.?|\d{1,4}(?:\.\d{1,4})*\.?|(?:article|chapter|section|part)\s+[IVXLCDM0-9]+[:.]?)\s*$",
    re.I,
)


def _is_bare_section_marker(line: str) -> bool:
    """True for a line that is JUST a numbering/page token ("I.", "3.2",
    "Article IV", or a bare "13" page reference) with no title text of
    its own.

    Two uses:
    1. Decides which disqualified lines a bare marker may inherit
       disqualification from (see _disqualify_real_heading_chains).
    2. Fed into remove_toc_blocks's own row-shape arrays as a reliable
       cluster-continuity signal: a real PDF's TOC entry very often
       wraps its title across two or three lines (e.g. "Time Allotment
       for Teaching Loads and other Assignment" / "of Faculty......." /
       "13"), and the wrap point frequently lands such that NEITHER
       fragment alone passes any title-shape test -- but the entry's
       own trailing page-number marker reliably anchors the cluster
       across the wrap regardless, so a run of real TOC entries doesn't
       fragment into disconnected clusters (each individually too small
       or too far from the "Contents" anchor to qualify) purely because
       some of their titles happened to wrap.

    Never, on its own, grounds for removal -- a bare marker carries no
    retrievable information either way, so including it in a cluster's
    index range has no effect on real content.
    """
    return bool(_BARE_SECTION_MARKER_RE.match((line or "").strip()))


def _looks_like_combined_numbered_heading(line: str) -> bool:
    """True for a heading that carries its OWN numbering AND title text
    together on one line -- "I. General Information", "1. Enrollment",
    "Article 6. Procedure..." -- as opposed to a bare marker alone
    ("I.", "1.") or a title alone ("OFFICE OF THE REGISTRAR").
    """
    stripped = (line or "").strip()
    if not stripped:
        return False
    return bool(
        _is_major_section_heading(stripped)
        or _ARTICLE_CHAPTER_HEADING_RE.match(stripped)
        or _DECIMAL_HEADING_RE.match(stripped)
    )


def _disqualify_real_heading_chains(
    lines: list[str], shape: list[bool], *, max_gap: int
) -> list[bool]:
    """Returns ``shape`` with any line disqualified if it leads directly
    into a real prose paragraph -- or, one level deeper, if it leads
    into a NESTED real heading (one that carries its own number and
    title combined, e.g. "1. Enrollment") that itself leads into prose.

    Three passes, deliberately bounded (never a general transitive
    closure -- an unbounded walk would incorrectly cascade all the way
    back through every earlier, separate, self-contained TOC entry too
    -- a real TOC is itself a chain of mutually-adjacent rows that
    eventually leads into body prose by construction, so "leads to
    something that leads to prose" would disqualify the whole TOC):

    1. Any shape-matching line whose own immediate next non-blank line
       is real prose is disqualified. Base case for a plain heading and
       for the trailing (title) half of a multi-line split.
    2. Any shape-matching, non-TOC-dotted line whose own immediate next
       line is itself a COMBINED numbered heading (see
       _looks_like_combined_numbered_heading) that is in turn directly
       disqualified by pass 1 is ALSO disqualified. This is what
       protects a split two-level real heading -- a service catalog's
       "OFFICE OF THE REGISTRAR" immediately followed by "1. Enrollment"
       immediately followed by real explanatory prose: "1. Enrollment"
       combines its own number and title on one line, so pass 1 already
       disqualifies it directly; this pass lets the OFFICE-level title
       immediately before it inherit that same protection, exactly one
       level, never further. Deliberately requires the INTERVENING line
       to be a COMBINED numbered heading specifically (not just any
       disqualified line) -- a TOC's own last entry (e.g. "I. General
       Information", itself a combined heading) immediately followed by
       the real body's first heading ("Grievance Machinery", which
       carries no number of its own at all) never matches this shape,
       so a genuine TOC entry is never granted this protection.
    3. A BARE section-marker line (just "I.", "3.2", "Article IV" -- no
       title text of its own) inherits disqualification from whatever
       immediately follows it, one level deep: this is what lets the
       office-level roman-numeral marker immediately before "OFFICE OF
       THE REGISTRAR" (now disqualified by pass 2) inherit the same
       protection in turn.

    A line that is already confidently TOC-shaped on its own (a same-
    line dotted leader or trailing page number -- looks_like_toc_entry_
    line) is never granted NEW protection by passes 2 or 3 -- it keeps
    its original, narrower pass-1-only exposure, so a genuine TOC row's
    own trailing page-number marker can never let it inherit protection
    from whatever random heading happens to come after the TOC ends.
    """
    disqualified = [False] * len(lines)

    def _first_nonblank_after(i: int) -> int | None:
        for k in range(i + 1, min(i + 1 + max_gap, len(lines))):
            if lines[k].strip():
                return k
        return None

    next_nonblank = [_first_nonblank_after(i) for i in range(len(lines))]

    for i, is_row in enumerate(shape):
        if not is_row:
            continue
        k = next_nonblank[i]
        if k is None:
            continue
        candidate = lines[k].strip()
        if len(candidate) > _TOC_BODY_PROSE_MIN_CHARS and not shape[k]:
            disqualified[i] = True

    for i, is_row in enumerate(shape):
        if (
            not is_row
            or disqualified[i]
            or looks_like_toc_entry_line(lines[i])
            # A line that ALREADY carries its own complete number and
            # title (e.g. a TOC's own last entry, "V. Faculty
            # Responsibilities") relies on pass 1 alone -- it must never
            # borrow protection from an unrelated COMBINED heading that
            # merely happens to sit right after it (e.g. the real body's
            # own first heading, "VI. Grievance Machinery"). Only a line
            # that is NOT itself a complete combined heading -- a bare
            # title with no number of its own, like "OFFICE OF THE
            # REGISTRAR" -- can borrow protection this way, since that is
            # the shape of one half of a genuinely split two-level
            # heading, never of a standalone TOC entry.
            or _looks_like_combined_numbered_heading(lines[i])
        ):
            continue
        k = next_nonblank[i]
        if (
            k is not None
            and shape[k]
            and disqualified[k]
            and not looks_like_toc_entry_line(lines[k])
            and _looks_like_combined_numbered_heading(lines[k])
        ):
            disqualified[i] = True

    for i, is_row in enumerate(shape):
        if not is_row or disqualified[i] or not _is_bare_section_marker(lines[i]):
            continue
        k = next_nonblank[i]
        if k is not None and disqualified[k]:
            disqualified[i] = True

    return [is_row and not disqualified[i] for i, is_row in enumerate(shape)]


def _toc_row_clusters(
    lines: list[str],
    row_like: list[bool],
    *,
    max_gap: int,
    max_connector_chars: int,
    hard_break: list[bool] | None = None,
) -> list[list[int]]:
    """Groups row-like indices into clusters, bridging a gap of up to
    ``max_gap`` NON-BLANK filler lines (never bridging a line longer
    than ``max_connector_chars``, and never bridging across a line
    flagged in ``hard_break``).

    Counting only non-blank lines against the gap budget -- rather than
    raw index distance -- matters because a real PDF's page boundary
    commonly lands as a run of several consecutive blank lines (margin
    whitespace) between two pages; raw index distance would count that
    whole blank run against the budget and could fragment one
    continuous TOC into several small, disconnected clusters purely
    because it happened to span a page break, regardless of how many
    real content lines actually separate two entries.

    ``hard_break`` marks a line that is itself heading-shaped but was
    explicitly EXCLUDED from row-like status by
    _disqualify_real_heading_chains because it leads into real content
    (directly or through a nested real-heading pair) -- e.g. a service
    catalog's "OFFICE OF THE REGISTRAR" sitting between an earlier TOC
    cluster and a later, unrelated row-like line. Without this, such a
    line would correctly be excluded from CLUSTER MEMBERSHIP, but the
    eventual drop range (every index from a cluster's first to its last
    member, inclusive -- the only way to also remove the TOC's own
    non-row-like filler, like blank lines and lone page numbers, sitting
    between its real row-like members) would still silently swallow it
    whole if a cluster happened to bridge across it from an earlier
    point to a later one. A hard-break line always starts a fresh
    cluster instead, exactly like a connector line that is too long.
    """
    indices = [i for i, is_row in enumerate(row_like) if is_row]
    if not indices:
        return []
    clusters: list[list[int]] = [[indices[0]]]
    for idx in indices[1:]:
        prev = clusters[-1][-1]
        between = lines[prev + 1 : idx]
        gap_has_long_line = any(len(l.strip()) > max_connector_chars for l in between)
        gap_has_hard_break = bool(hard_break) and any(hard_break[prev + 1 : idx])
        non_blank_gap = sum(1 for l in between if l.strip())
        if non_blank_gap <= max_gap and not gap_has_long_line and not gap_has_hard_break:
            clusters[-1].append(idx)
        else:
            clusters.append([idx])
    return clusters


def remove_toc_blocks(
    text: str,
    *,
    min_run: int = 3,
    anchored_min_run: int = 2,
    anchor_reach: int = 6,
    max_gap: int = 6,
    max_connector_chars: int = 200,
) -> str:
    """Drops contiguous runs of table-of-contents-shaped lines from text
    before it ever reaches chunking/indexing.

    Two independent passes, each gated differently, because a dense run
    of plain heading-shaped lines (Title Case / ALL CAPS / roman
    numerals, no page number at all) is, by shape alone, indistinguishable
    from a title page or letterhead block (institution name, office name,
    form code) -- which is NOT a table of contents. Real-world validation
    against an actual document surfaced exactly this collision, so the
    broader shape test is only ever trusted with corroborating evidence:

    1. Unanchored, narrow shape (looks_like_toc_entry_line: a dotted
       leader or a bare trailing page number): a dotted-leader-and-
       page-number shape essentially never occurs by coincidence in a
       title page or anywhere outside a real TOC, so a dense cluster of
       at least ``min_run`` such lines (each within ``max_gap`` lines of
       the next, never bridging a line longer than ``max_connector_chars``)
       is removed with no further evidence required.
    2. Anchored, broad shape (looks_like_toc_region_row: also matches a
       plain heading-shaped line with no page number, since real PDF
       extraction frequently drops a TOC row's page number onto its own
       line or loses it entirely): a cluster of at least
       ``anchored_min_run`` such lines is removed only when it starts
       within ``anchor_reach`` lines of an explicit "Contents" / "Table
       of Contents" heading line (same no-long-connector-line rule) --
       that heading is strong, unambiguous evidence the list right after
       it is navigation. The anchor heading line itself is removed too.

    In both passes, a line (or a multi-line chain of them -- e.g. a bare
    section-marker line followed by its title on the next line, a common
    real-world PDF rendering split) that leads directly into a real
    paragraph is never treated as a TOC-row candidate at all, regardless
    of shape -- see _disqualify_real_heading_chains. A true TOC entry is
    never immediately followed by the very paragraph it refers to.

    A single isolated TOC-shaped line with no confirming run or anchor is
    never removed on its own -- this is what keeps a real body section
    that merely happens to be titled "Contents", or a lone heading that
    happens to end in a number (e.g. "Appendix 1"), untouched.
    """
    if not text:
        return text
    lines = text.split("\n")

    drop = [False] * len(lines)

    narrow_shape = [looks_like_toc_entry_line(line) for line in lines]
    narrow_row_like = _disqualify_real_heading_chains(lines, narrow_shape, max_gap=max_gap)
    narrow_hard_break = [s and not r for s, r in zip(narrow_shape, narrow_row_like)]
    for cluster in _toc_row_clusters(
        lines,
        narrow_row_like,
        max_gap=max_gap,
        max_connector_chars=max_connector_chars,
        hard_break=narrow_hard_break,
    ):
        if len(cluster) >= min_run:
            for k in range(cluster[0], cluster[-1] + 1):
                drop[k] = True

    anchor_indices = [i for i, line in enumerate(lines) if _is_toc_heading_anchor_line(line)]
    if anchor_indices:
        # Bare marker lines (a lone "13", "iv", or "Article IV") are
        # ALSO treated as row-like here (unlike the unanchored narrow
        # pass above) -- a real TOC entry's title frequently wraps
        # across two or three lines in a way where NEITHER fragment
        # passes any title-shape test on its own (see
        # _is_bare_section_marker's docstring), which would otherwise
        # fragment one long run of real entries into several small,
        # disconnected clusters -- each too far from the "Contents"
        # anchor to qualify on its own. Scoped to the anchored pass
        # only: without the anchor's corroborating evidence, bare
        # numbers alone are too weak a signal (e.g. a short numbered
        # list in ordinary body prose) to safely treat as TOC rows.
        broad_shape = [
            looks_like_toc_region_row(line) or _is_bare_section_marker(line) for line in lines
        ]
        broad_row_like = _disqualify_real_heading_chains(lines, broad_shape, max_gap=max_gap)
        broad_hard_break = [s and not r for s, r in zip(broad_shape, broad_row_like)]
        for cluster in _toc_row_clusters(
            lines,
            broad_row_like,
            max_gap=max_gap,
            max_connector_chars=max_connector_chars,
            hard_break=broad_hard_break,
        ):
            if len(cluster) < anchored_min_run:
                continue
            start, end = cluster[0], cluster[-1]
            # An anchor confirms this cluster either by falling WITHIN
            # its span (common once bare-marker bridging lets a cluster
            # absorb content from before the literal "Contents" line
            # too -- the cluster's own no-long-line-between guarantee
            # already covers this case) or by sitting just before the
            # cluster's start (the original, narrower case).
            anchor = next(
                (
                    a
                    for a in anchor_indices
                    if start <= a <= end
                    or (
                        0 <= start - a <= anchor_reach
                        and not any(len(lines[k].strip()) > max_connector_chars for k in range(a, start))
                    )
                ),
                None,
            )
            if anchor is None:
                continue
            drop[anchor] = True
            for k in range(cluster[0], cluster[-1] + 1):
                drop[k] = True

    kept = [line for idx, line in enumerate(lines) if not drop[idx]]
    return "\n".join(kept)


def is_heading_candidate(line: str) -> bool:
    """Generic "this line looks like a section/subsection heading" test.

    Reused by the lightweight ingestion pipeline to find the nearest real
    heading for a chunk's title, instead of falling back to an arbitrary
    first-line fragment (which can be a mid-sentence slice or a leftover
    TOC row). Never true for anything that itself looks like a TOC entry.
    """
    stripped = (line or "").strip()
    if not stripped or len(stripped) > 100:
        return False
    if looks_like_toc_entry_line(stripped):
        return False
    if _is_major_section_heading(stripped):
        return True
    if _ARTICLE_CHAPTER_HEADING_RE.match(stripped):
        return True
    if _DECIMAL_HEADING_RE.match(stripped):
        return True
    if (
        _ALLCAPS_HEADING_RE.match(stripped)
        and len(re.findall(r"[A-Z]{2,}", stripped)) >= 1
        and len(stripped.split()) >= 2
    ):
        return True
    if (
        _looks_like_standalone_heading_text(stripped)
        and len(stripped) <= 80
        and not stripped.endswith((".", ":", ";", ","))
    ):
        return True
    return False


_HEADING_CONNECTOR_WORDS = {
    "a", "an", "the", "of", "on", "in", "for", "to", "and", "or", "by", "as",
}


def _looks_like_standalone_heading_text(line: str) -> bool:
    """A short (1-8 word) Title Case or ALL-CAPS phrase, standalone on its
    own line -- e.g. "Grievance Machinery" or "Leave of Absence".

    Deliberately more permissive than _looks_like_title_case_heading
    (which requires >=3 words -- tuned for a different purpose, matching
    multi-word breadcrumb-fragment headings in OCR output, and must not
    be changed here since other callers rely on that exact threshold): a
    real section heading is very often just one or two words.
    """
    words = [w for w in re.split(r"\s+", line.strip()) if w]
    if not (1 <= len(words) <= 8):
        return False
    title_like = 0
    for word in words:
        bare = word.strip(".,;:()[]\"'/")
        if not bare:
            continue
        if bare.casefold() in _HEADING_CONNECTOR_WORDS:
            title_like += 1
            continue
        if _TITLE_CASE_WORD_RE.match(bare) or bare.isupper():
            title_like += 1
        else:
            return False
    return title_like >= 1


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
    - drop whole table-of-contents blocks (see remove_toc_blocks) so TOC
      rows never become retrievable knowledge units or chunk titles
    - drop TOC mashups, page/part markers, and separator lines
    - drop duplicate breadcrumb section labels and truncated fragment headings
    - repair hyphenated word breaks
    - drop stale major-section restarts that belong to an earlier section number
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = remove_toc_blocks(text)
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


_DIGIT_RUN_RE = re.compile(r"\d+")
_ROMAN_PAGE_REF_RE = re.compile(r"(?i)\b(page|p\.?|of)(\s*[:.]?\s*)([ivxlcdm]{1,6})\b")
_BARE_ROMAN_TOKEN_RE = re.compile(r"^[ivxlcdm]{1,6}$", re.I)
_TRAILING_OF_TOTAL_RE = re.compile(r"\s*\bof\s+#\s*$", re.I)


def _furniture_template(line: str) -> str:
    """Normalizes a header/footer candidate so a per-page-varying page
    number doesn't prevent recognizing the same repeated template --
    "Page 5 of 92" and "Page 6 of 92" both normalize to "Page # of #",
    so they count as the same recurring template rather than two
    one-off lines that each only ever appear once.

    Also normalizes a ROMAN-numeral page reference the same way --
    front-matter pages are conventionally paginated "i", "ii", "iii",
    "iv", ... instead of arabic numbers, and _DIGIT_RUN_RE alone never
    touches letters, so "Page: i" / "Page: ii" / "Page: iv" each looked
    like a UNIQUE, non-recurring line (no two pages share the same
    numeral) even though they're all the same running footer template.
    Only normalizes a roman-numeral TOKEN immediately after "page"/
    "p."/"of" (case-insensitive), or when it is the ENTIRE line by
    itself -- never inside unrelated prose, where a short roman-letter-
    shaped word (e.g. "Mix") could otherwise be misread as a numeral.

    Collapses whitespace runs to a single space -- confirmed against the
    real LSPU Student Handbook PDF, PyMuPDF extraction does not render a
    running footer byte-identically on every page: some pages render
    "Page: 5 of 183" with a single space before the total, others
    "Page: 5 of  183" with two (almost certainly a font-kerning artifact
    on those specific pages), and these would otherwise count as two
    DIFFERENT templates, each individually too rare to pass the
    recurrence threshold even though they're the same footer.

    Finally drops a trailing "of #" entirely -- confirmed against the
    real LSPU Faculty Manual PDF, the SAME document can mix "Page: 5"
    (no total) on most pages with "Page: 171 of 173" (WITH a total) on
    a handful of others (e.g. an appendix carrying its own declared page
    count). Dropping the suffix makes "Page: #" and "Page: # of #"
    count as the same template, so the rare variant still joins the
    dominant recurring bucket instead of being individually too rare on
    its own to ever be recognized as furniture.
    """
    normalized = _DIGIT_RUN_RE.sub("#", line)
    normalized = _ROMAN_PAGE_REF_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}#", normalized)
    if _BARE_ROMAN_TOKEN_RE.match(normalized.strip()):
        return "#"
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return _TRAILING_OF_TOTAL_RE.sub("", normalized).strip()


_FURNITURE_MIN_EDGE_LINES = 3
_FURNITURE_MAX_EDGE_LINES = 12
_FURNITURE_LINE_MAX_CHARS = 70


def _furniture_edge_lines(lines: list[str], *, from_start: bool) -> list[str]:
    """Variable-length run of lines from one edge of a page that might
    be running header/footer furniture.

    A real structured-template header/footer (Institution:/Doc. No.:/
    Type:/Revision No.:/Title:/Date:/Page: ..., or a standalone "of N"
    fragment) is often a stack of MORE than 3 short label/value lines --
    the old fixed first-3/last-3 window never even looked at the 4th+
    line of such a block, so those interior lines were never counted as
    recurring furniture no matter how often they repeated. This walks
    inward from the edge, always taking at least
    _FURNITURE_MIN_EDGE_LINES (unchanged floor, so existing short-header
    documents behave exactly as before), and keeps extending (capped at
    _FURNITURE_MAX_EDGE_LINES) only while each further line stays short
    -- a real body paragraph is long, so it naturally stops the walk and
    is never swept into the furniture candidate set.
    """
    ordered = lines if from_start else list(reversed(lines))
    n = len(ordered)
    count = min(_FURNITURE_MIN_EDGE_LINES, n)
    while count < min(n, _FURNITURE_MAX_EDGE_LINES) and len(ordered[count]) <= _FURNITURE_LINE_MAX_CHARS:
        count += 1
    return ordered[:count]


def _strip_repeated_headers_footers(text: str, page_texts: list[str]) -> str:
    if len(page_texts) < 2:
        return text

    counts: dict[str, int] = {}
    for page in page_texts:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        header = _furniture_edge_lines(lines, from_start=True)
        footer = _furniture_edge_lines(lines, from_start=False)
        for candidate in set(header + footer):
            template = _furniture_template(candidate)
            counts[template] = counts.get(template, 0) + 1

    # Lowered from an exact-match-only 0.6 -- a running header/footer
    # legitimately varies per page (page numbers) and is sometimes absent
    # on chapter-start pages, so requiring every instance to be byte-
    # identical and present on 60% of ALL pages missed real furniture.
    threshold = max(2, int(len(page_texts) * 0.4))
    repeated_templates = {template for template, count in counts.items() if count >= threshold}
    if not repeated_templates:
        return text

    return "\n".join(
        line for line in text.splitlines() if _furniture_template(line.strip()) not in repeated_templates
    )


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

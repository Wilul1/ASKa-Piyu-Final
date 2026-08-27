"""PDF helpers for citation-grounded source viewing."""

from __future__ import annotations

import re
from pathlib import Path

import fitz


_NEXT_SECTION_RE = re.compile(
    r"^\s*(?:\d{1,3}|[IVXLC]{1,6})\.\s+[A-ZÀ-ÖØ-Þ]",
)
_LEADING_NUM_RE = re.compile(
    r"^\s*(?:\d{1,3}|[IVXLC]{1,6})\.\s+",
)


def extract_citation_pages_pdf(
    path: Path,
    page_start: int,
    page_end: int | None = None,
    section_title: str | None = None,
) -> bytes:
    """Return a PDF covering the cited page range, cropped to the section when possible.

    - Includes ``page_start`` through ``page_end`` (1-based, inclusive).
    - When ``section_title`` is set, the first page drops content above that
      heading (e.g. leftover ID Validation), and the last page drops the next
      numbered service section so the viewer shows the full cited source only.
    """
    if page_start < 1:
        raise ValueError("page_start must be >= 1")
    end = int(page_end) if page_end is not None else page_start
    if end < page_start:
        end = page_start

    source = fitz.open(path)
    try:
        if page_start > source.page_count:
            raise ValueError(
                f"Page {page_start} not found (document has {source.page_count} pages)."
            )
        end = min(end, source.page_count)
        section = (section_title or "").strip()
        if not section:
            out = fitz.open()
            try:
                out.insert_pdf(source, from_page=page_start - 1, to_page=end - 1)
                return out.tobytes()
            finally:
                out.close()

        return _extract_section_clipped_pdf(
            source,
            page_start=page_start,
            page_end=end,
            section_title=section,
        )
    finally:
        source.close()


def _extract_section_clipped_pdf(
    source: fitz.Document,
    *,
    page_start: int,
    page_end: int,
    section_title: str,
) -> bytes:
    out = fitz.open()
    try:
        first_idx = page_start - 1
        last_idx = page_end - 1
        section_top_on_first: float | None = None

        for page_index in range(first_idx, last_idx + 1):
            page = source[page_index]
            clip = fitz.Rect(page.rect)

            if page_index == first_idx:
                top = _find_section_top(page, section_title)
                if top is not None:
                    section_top_on_first = top
                    clip.y0 = max(page.rect.y0, top)

            # Crop at the next numbered service on *every* page in the range.
            # Soft +1 page extension often lands on a page that is mostly the
            # following service; only clipping the last page left bleed-through.
            min_y = clip.y0 + 12
            if page_index == first_idx and section_top_on_first is not None:
                min_y = section_top_on_first + 24
            bottom = _find_next_section_top(page, section_title, min_y=min_y)
            if bottom is not None and bottom > clip.y0 + 36:
                clip.y1 = min(page.rect.y1, bottom)

            # Continuation page that is only the next service → omit it.
            if page_index > first_idx and clip.height < 72:
                continue

            # Degenerate clip on the first page → keep a usable fallback.
            if clip.height < 40 or clip.width < 40:
                if page_index > first_idx:
                    continue
                clip = fitz.Rect(page.rect)

            new_page = out.new_page(width=clip.width, height=clip.height)
            new_page.show_pdf_page(new_page.rect, source, page_index, clip=clip)

        if out.page_count == 0:
            # Safety: never return an empty PDF.
            page = source[first_idx]
            out.new_page(width=page.rect.width, height=page.rect.height)
            out[0].show_pdf_page(out[0].rect, source, first_idx)

        return out.tobytes()
    finally:
        out.close()


def _section_search_variants(section_title: str) -> list[str]:
    raw = re.sub(r"\s+", " ", (section_title or "").strip())
    if not raw:
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = re.sub(r"\s+", " ", value).strip()
        key = cleaned.casefold()
        if len(cleaned) < 4 or key in seen:
            return
        seen.add(key)
        variants.append(cleaned)

    add(raw)
    without_num = _LEADING_NUM_RE.sub("", raw).strip()
    add(without_num)
    # Drop trailing parenthetical editions: "(Undergraduate)"
    add(re.sub(r"\s*\([^)]*\)\s*$", "", without_num).strip())
    # Short core before em-dash / colon
    for sep in (" — ", " - ", ": "):
        if sep in without_num:
            add(without_num.split(sep, 1)[0])
            break
    # Prefer longer matches first for search_for
    variants.sort(key=len, reverse=True)
    return variants


def _iter_text_lines(page: fitz.Page):
    """Yield (y0, line_text) for each non-empty line on the page.

    PDF blocks often merge several lines; scanning line-by-line finds
    numbered service headings that are not at the start of a block.
    """
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = re.sub(
                r"\s+",
                " ",
                "".join(str(span.get("text") or "") for span in spans),
            ).strip()
            if not text:
                continue
            bbox = line.get("bbox") or (0, 0, 0, 0)
            yield float(bbox[1]), text


def _find_section_top(page: fitz.Page, section_title: str) -> float | None:
    for variant in _section_search_variants(section_title):
        hits = page.search_for(variant, quads=False)
        if hits:
            return float(min(hit.y0 for hit in hits)) - 6.0

    # Fallback: lines that look like "5. Issuance of ..."
    target = _LEADING_NUM_RE.sub("", section_title).strip().casefold()
    target_core = target[:48]
    for y0, line in _iter_text_lines(page):
        line_core = _LEADING_NUM_RE.sub("", line).strip().casefold()
        if target_core and target_core in line_core:
            return float(y0) - 6.0
        if _NEXT_SECTION_RE.match(line) and target_core[:24] in line_core:
            return float(y0) - 6.0
    return None


def _find_next_section_top(
    page: fitz.Page,
    section_title: str,
    *,
    min_y: float,
) -> float | None:
    """Y-position where the *next* numbered section starts (below min_y)."""
    current = _LEADING_NUM_RE.sub("", section_title).strip().casefold()
    current_core = current[:40]
    candidates: list[float] = []
    for y0, line in _iter_text_lines(page):
        if float(y0) < min_y:
            continue
        if not _NEXT_SECTION_RE.match(line):
            continue
        line_core = _LEADING_NUM_RE.sub("", line).strip().casefold()
        # Skip the same section heading if it repeats.
        if current_core and current_core in line_core:
            continue
        candidates.append(float(y0) - 4.0)
    if not candidates:
        return None
    return min(candidates)

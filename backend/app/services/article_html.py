"""Sanitize Knowledge Article HTML and extract plain text.

Existing articles stay ``plain``. New rich articles store sanitized HTML in
``published_articles.content`` with ``content_format='html'``.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

ALLOWED_TAGS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "ul",
        "ol",
        "li",
        "a",
        "img",
        "blockquote",
        "br",
        "span",
    }
)
_VOID_TAGS = frozenset({"br", "img"})
_SAFE_HREF_SCHEMES = frozenset({"http", "https", "mailto"})
_MEDIA_SRC_RE = re.compile(r"^/kb/media/[A-Za-z0-9._-]+$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

CONTENT_FORMAT_PLAIN = "plain"
CONTENT_FORMAT_HTML = "html"


def looks_like_html(text: str | None) -> bool:
    raw = (text or "").lstrip()
    if not raw.startswith("<"):
        return False
    return bool(re.match(r"<(p|h[1-4]|ul|ol|blockquote|div|span|strong|em|img)\b", raw, re.I))


def html_to_plain(text: str | None) -> str:
    """Strip markup for search, RAG chunking, and empty-content checks."""
    raw = str(text or "")
    if not raw.strip():
        return ""
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|h[1-4]|li|blockquote|div)>", "\n", raw)
    raw = _TAG_RE.sub("", raw)
    raw = html.unescape(raw)
    lines = [line.strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _safe_href(value: str) -> str | None:
    href = (value or "").strip()
    if not href or href.startswith("#"):
        return None
    if any(ch.isspace() for ch in href) or "\\" in href:
        return None
    lowered = href.lower()
    if lowered.startswith("javascript:") or lowered.startswith("data:") or lowered.startswith("vbscript:"):
        return None
    # Protocol-relative URLs such as //evil.example must not pass as local paths.
    if href.startswith("//"):
        return None
    parsed = urlparse(href)
    if parsed.scheme and parsed.scheme.lower() not in _SAFE_HREF_SCHEMES:
        return None
    if parsed.netloc and not parsed.scheme:
        return None
    if not parsed.scheme and not href.startswith("/"):
        return None
    return href


def _safe_img_src(value: str) -> str | None:
    src = (value or "").strip()
    if not src:
        return None
    if src.startswith("data:") or src.startswith("javascript:"):
        return None
    parsed = urlparse(src)
    if parsed.scheme in {"http", "https"}:
        path = parsed.path or ""
        if path.startswith("/kb/media/") and _MEDIA_SRC_RE.match(path):
            return path
        return None
    if _MEDIA_SRC_RE.match(src):
        return src
    return None


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._stack: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth or tag in {"script", "style", "iframe", "object", "embed", "svg", "math"}:
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if tag not in ALLOWED_TAGS:
            return
        attr_map = {str(k).lower(): v or "" for k, v in attrs}
        rendered: list[str] = []
        if tag == "a":
            href = _safe_href(attr_map.get("href", ""))
            if href is None:
                return
            rendered.append(f'href="{html.escape(href, quote=True)}"')
            rendered.append('rel="noopener noreferrer"')
            rendered.append('target="_blank"')
        elif tag == "img":
            src = _safe_img_src(attr_map.get("src", ""))
            if src is None:
                return
            alt = html.escape(attr_map.get("alt", "")[:200], quote=True)
            rendered.append(f'src="{html.escape(src, quote=True)}"')
            rendered.append(f'alt="{alt}"')
        attr_html = (" " + " ".join(rendered)) if rendered else ""
        if tag in _VOID_TAGS:
            self._out.append(f"<{tag}{attr_html}>")
            return
        self._stack.append(tag)
        self._out.append(f"<{tag}{attr_html}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag not in _VOID_TAGS:
                self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag not in ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        if tag in self._stack:
            while self._stack:
                current = self._stack.pop()
                self._out.append(f"</{current}>")
                if current == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        self._out.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._out.append(f"&#{name};")

    def result(self) -> str:
        while self._stack:
            self._out.append(f"</{self._stack.pop()}>")
        return "".join(self._out).strip()


def sanitize_article_html(raw: str | None) -> str:
    parser = _Sanitizer()
    parser.feed(str(raw or ""))
    parser.close()
    return parser.result()


def extract_kb_media_filenames(html_text: str | None) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"/kb/media/([A-Za-z0-9._-]+)", str(html_text or "")):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def prepare_article_body(
    *,
    content: str | None,
    content_format: str | None,
    existing_format: str | None = None,
) -> tuple[str, str]:
    """Return ``(stored_content, content_format)`` without rewriting plain articles."""
    requested = (content_format or existing_format or CONTENT_FORMAT_PLAIN).strip().lower()
    raw = str(content or "")
    if requested == CONTENT_FORMAT_HTML or looks_like_html(raw):
        sanitized = sanitize_article_html(raw)
        return sanitized, CONTENT_FORMAT_HTML
    return raw, CONTENT_FORMAT_PLAIN


def display_article_body(content: str | None, content_format: str | None) -> str:
    from app.services.article_content_formatter import strip_embedded_article_metadata

    body = strip_embedded_article_metadata(content)
    fmt = (content_format or CONTENT_FORMAT_PLAIN).strip().lower()
    if fmt == CONTENT_FORMAT_HTML:
        return sanitize_article_html(body)
    return body

"""Store and serve public Knowledge Base article images."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.config import settings
from app.services.ticket_attachments import detect_content_type

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_KB_IMAGE_BYTES = 5 * 1024 * 1024


def _media_root() -> Path:
    root = Path(settings.kb_media_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", (name or "image").strip())[:80]
    stem = Path(cleaned).stem or "image"
    return re.sub(r"\s+", "_", stem)


def save_kb_image(*, filename: str, content: bytes) -> dict[str, str | int]:
    if not content:
        raise ValueError("Image file is empty.")
    if len(content) > MAX_KB_IMAGE_BYTES:
        raise ValueError("Image must be 5 MB or smaller.")

    sniffed = detect_content_type(content)
    if sniffed is None or sniffed not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Only JPG, PNG, WebP, or GIF images are allowed.")

    media_id = str(uuid.uuid4())
    ext = ALLOWED_IMAGE_TYPES[sniffed]
    stored = f"{media_id}_{_safe_stem(filename)}{ext}"
    path = _media_root() / stored
    path.write_bytes(content)
    return {
        "media_id": media_id,
        "filename": stored,
        "content_type": sniffed,
        "size_bytes": len(content),
        "url": f"/kb/media/{stored}",
    }


def resolve_kb_media_path(stored_filename: str) -> Path:
    name = Path(stored_filename or "").name
    if not name or name != stored_filename or ".." in name:
        raise FileNotFoundError("Invalid media path.")
    root = _media_root()
    path = (root / name).resolve()
    if path.parent != root:
        raise FileNotFoundError("Media path escapes storage root.")
    if not path.is_file():
        raise FileNotFoundError("Media file not found.")
    return path

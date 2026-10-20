"""Prepares the How to Use guide's screenshot assets from raw source
screenshots: redacts personally-identifying text (requester names) and
resizes to a reasonable app-bundle width.

Uses Pillow, which is already a backend dependency in this project (see
backend/requirements.txt) -- this script intentionally adds no new
dependency anywhere (not to pubspec.yaml, not to the backend). It is a
one-time/occasional local tool, not something the app or CI runs.

Run from the backend's venv (it already has Pillow installed):
    cd backend && source venv/Scripts/activate
    python ../flutter_app/tool/prepare_how_to_use_screenshots.py

The numbered/highlight/arrow annotations themselves are NOT baked into
these images -- they're drawn at runtime by Flutter's own CustomPainter
(see _AnnotatedScreenshot in office_how_to_use_page.dart), driven by
fractional coordinates defined in Dart. That keeps the pedagogical
markup reviewable as code and easy to adjust without re-running this
script. This script's only job is the one thing that must be permanently
baked into the image file: redacting real names before the screenshot
ever becomes an app asset.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SOURCE_DIR = Path(
    r"C:\Users\Admin\AppData\Local\Temp\claude\c--Users-Admin-Desktop-ASKa-piyu"
    r"\fd854fbc-ff50-496d-9639-6462ccaaf3e7\images"
)
OUT_DIR = (
    Path(__file__).resolve().parent.parent / "assets" / "images" / "how_to_use"
)
MAX_WIDTH = 1280

REDACTION_FILL = (226, 232, 240, 255)
REDACTION_OUTLINE = (148, 163, 184, 255)


def redact(im: Image.Image, boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    draw = ImageDraw.Draw(im)
    for box in boxes:
        draw.rounded_rectangle(box, radius=4, fill=REDACTION_FILL, outline=REDACTION_OUTLINE, width=1)
    return im


def resize(im: Image.Image, max_width: int = MAX_WIDTH) -> Image.Image:
    if im.width <= max_width:
        return im
    ratio = max_width / im.width
    return im.resize((max_width, round(im.height * ratio)), Image.LANCZOS)


JOBS: list[tuple[str, str, list[tuple[int, int, int, int]]]] = [
    (
        "12.png",
        "assigned_tickets_list.png",
        # Three requester names in the ticket list cards -- coordinates
        # calibrated by cropping and visually verifying against this exact
        # source file (not guessed blind).
        [
            (333, 489, 500, 513),
            (333, 649, 500, 679),
            (333, 829, 500, 853),
        ],
    ),
    ("13.png", "kb_extract_index.png", []),
    ("14.png", "kb_review_publish.png", []),
    ("15.png", "knowledge_article_list.png", []),
    ("16.png", "knowledge_article_create.png", []),
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for source_name, out_name, boxes in JOBS:
        src_path = SOURCE_DIR / source_name
        im = Image.open(src_path).convert("RGBA")
        if boxes:
            im = redact(im, boxes)
        im = resize(im)
        # Flatten onto white before saving -- these are opaque screenshots,
        # and RGBA PNGs are larger for no benefit here.
        flat = Image.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.split()[3])
        out_path = OUT_DIR / out_name
        flat.save(out_path, "PNG", optimize=True)
        print(f"{source_name} -> {out_path.relative_to(OUT_DIR.parent.parent.parent)} ({flat.size[0]}x{flat.size[1]})")


if __name__ == "__main__":
    main()

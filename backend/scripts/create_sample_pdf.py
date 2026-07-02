"""Create a small digital PDF for local API testing."""
import fitz
from pathlib import Path

out = Path(__file__).resolve().parent.parent / "samples" / "enrollment_policy.pdf"
out.parent.mkdir(parents=True, exist_ok=True)

doc = fitz.open()
page = doc.new_page()
text = """SECTION I — ENROLLMENT

Students must complete the enrollment form before the start of each semester.
Late enrollment requires approval from the registrar.

SECTION II — DROPPING SUBJECTS

A student may drop a subject within the first two weeks without grade penalty.
After that period, a dropping form must be signed by the adviser.
"""
page.insert_text((72, 72), text, fontsize=11)
doc.save(out)
doc.close()
print(f"Wrote {out}")

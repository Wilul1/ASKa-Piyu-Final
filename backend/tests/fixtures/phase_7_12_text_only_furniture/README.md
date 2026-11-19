# Phase 7.12 text-only furniture fixture

Controlled, programmatically generated PDFs for characterizing text-only
running headers/footers. Not production data. No institution names or
student records.

## Files

| File | Role |
|---|---|
| `generate_fixture.py` | Deterministic generator (word geometry fingerprint) |
| `characterize.py` | Read-only extraction/reconstruction probe |
| `text_only_furniture_digital.pdf` | Digital text-layer PDF (8 pages, 468×612 pt) |
| `text_only_furniture_ocr_twin.pdf` | Image-only raster twin of the same pages |
| `rasters/page_NN_zoom2.png` | Zoom-2 pixmap of each digital page |
| `provenance/generation_manifest.json` | Intended layout and expected classes |
| `provenance/digital_extraction.json` | Production digital extraction dump |
| `provenance/ocr_extraction.json` | Live OCR extraction dump (if EasyOCR ran) |
| `provenance/coordinate_audit.json` | Digital vs OCR coordinate comparison |

## Page map

| PDF page | Role | Header/footer | Folio | Section heading | Native table |
|---:|---|---|---|---|---|
| 1 | Title | no | no | no | no |
| 2 | Content (even duplex x=96) | yes | 1 | yes | no |
| 3 | Content (odd duplex x=36) | yes | 2 | yes | no |
| 4 | Content + table | yes | 3 | yes | yes |
| 5 | Content + numbered items | yes | 4 | yes | no |
| 6 | Content + table + hyphen wrap | yes | 5 | yes | yes |
| 7 | Content + wrap completion | yes | 6 | yes | no |
| 8 | Content | yes | 7 | yes | no |

## Expected classifications

- **Policy Manual Running Header** — candidate text-only furniture, not a table.
- **Internal Review Copy Only** — candidate text-only furniture, not a table.
- **Variable folio** (`1`…`7`) — folio evidence; 7.4A isolation candidate; not header identity.
- **Section Overview** — repeated body heading; negative control.
- **Item / Status / Notes table** — native table; negative control.
- **Controlled Furniture Fixture** — title-page title only; not a running header.

Regenerate with:

```
python tests/fixtures/phase_7_12_text_only_furniture/generate_fixture.py
```

Word-level geometry is deterministic across regenerations. Raw PDF bytes may
differ because PyMuPDF assigns new file identifiers.

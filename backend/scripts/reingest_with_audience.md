# Audience tags for Chroma (BE-05)

Untagged Chroma chunks are treated as **student**-visible only.

## Option A — stamp in place (preferred; no wipe)

```bat
cd backend
python scripts/stamp_legacy_audience.py --dry-run
python scripts/stamp_legacy_audience.py
```

Infers `audience` from `source_filename` / title using the same rules as ingest.

## Option B — full rebuild

1. Set in `backend/.env`:

```env
ASKA_KB_REBUILD_DOCUMENT_PATHS=./data/documents/<id>/Student Handbook.pdf;./data/documents/<id>/Faculty Manual.pdf;./data/documents/<id>/Citizen Charter.pdf
```

2. Ensure admin Bearer login works (`ASKA_ALLOW_ADMIN_API_KEY=false` in production).

3. Call rebuild (maintenance window — wipes Chroma then re-ingests):

```bat
curl -X POST http://localhost:8000/admin/kb/rebuild -H "Authorization: Bearer <admin-token>"
```

4. Confirm Ask Assistant returns faculty-only answers only for faculty accounts.

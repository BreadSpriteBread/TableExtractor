# Saudi Exchange PDF Table Extraction

Web app that bulk-extracts tables from Saudi Exchange financial report PDFs
(and user uploads), shows the results in the UI, caches them in SQLite, and
exports them as JSON.

**Workflow:** Acquire → Select (persistent cart) → Extract → Cache → Browse history → Export.

## Stack

- **Backend** — Python / Flask (port 5000), SQLite (`data.db`, FTS5 for search)
- **Extraction** — swappable engine (`backend/extraction/`): pdfplumber vector
  extraction first, PyMuPDF + tesseract OCR fallback for scanned pages
- **Frontend** — React + Vite + MUI (port 5173), 4 tabs + cart drawer
- **Scraper** — patchright/Playwright (live), stubbed in CI via `SCRAPER_STUB=1`

## Dev setup

```bash
# Backend (Python 3.10+). For OCR also: sudo apt-get install tesseract-ocr
pip install -r requirements.txt
python3 -m backend.app                      # http://localhost:5000

# Frontend (Node 22 — use nvm; system Node 12 is too old for Vite)
cd frontend && npm install && npm run dev   # http://localhost:5173 (proxies /api)
```

## UI tabs

| Tab | Purpose |
|---|---|
| Query Reports | Browse/search the downloaded corpus, multi-select, add to cart |
| Acquire Reports | Upload PDFs; trigger the Saudi Exchange scraper |
| Extract Results | Run extraction over the cart (async batch), per-doc status, export JSON |
| Extracted Tables | Search cached results (filename/status/date/full-text), view, bulk download/delete |

The cart is deduplicated by document content hash, persists for the browser
session, and is visible from every tab (badge + drawer in the app bar).

## API

| Endpoint | Description |
|---|---|
| `GET /api/companies`, `GET /api/reports`, `GET /api/pdf/<id>`, `GET /api/stats` | Corpus browsing |
| `POST /api/documents/register` | Corpus reports → content-addressed documents (`sha256:<hash>` of file bytes) |
| `POST /api/documents/upload` | Multipart PDF upload (field `files`) |
| `POST /api/extract` | Submit batch `{document_ids, force}` → `202 {job_id}` (async) |
| `GET /api/jobs/<id>`, `POST /api/jobs/<id>/cancel` | Batch/per-doc progress; cancel |
| `GET /api/extractions?q=&filename=&status=&date_from=&date_to=` | Search cache (FTS5 over headers/cells) |
| `GET /api/extractions/<document_id>` | Full cached result JSON |
| `POST /api/extractions/export` | Bulk export → `{"documents": [...]}` |
| `POST /api/extractions/delete` | Bulk delete cached results |
| `POST /api/scrape`, `GET /api/scrape/status` | Background scrape (stub in CI) |

## Extraction semantics

- **Identity/caching** — a document is the SHA-256 of its bytes; same file under
  any name hits the cache. Results are cached until deleted; "Re-extract"
  (`force`) overwrites the single latest result.
- **Scope** — text PDFs, scanned (OCR), rotated pages, landscape, borderless
  tables (text-alignment strategy), multi-page tables (merged, contributing
  pages listed, `spans_pages`), nested tables (flattened + `nested` flag).
- **Failure handling** — per document, never aborts the batch: 120 s timeout,
  one auto-retry on crash (each doc runs in a killable child process), failed
  docs cached with error details. Statuses: `success` / `partial` / `failed`.
- **Bulk jobs** — bounded pool (4 workers), results stream to SQLite per doc,
  cancellable, progress polled via `/api/jobs/<id>`.

## Tests

```bash
python3 -m pytest tests/                 # extraction/fixtures, API, jobs, caching, DB
cd frontend && npx vitest run            # cart + progress-state unit tests
cd frontend && npx playwright test       # E2E happy path (boots both servers)
```

Fixture PDFs are generated deterministically (`python3 -m tests.fixtures.generate_fixtures`)
and asserted against hand-verified JSON in `tests/fixtures/expected/`.
CI (`.github/workflows/ci.yml`) runs all three suites on every PR; OCR tests
run for real there (tesseract installed). Live scraping is never exercised in
CI — manual smoke test only.

## Corpus file naming

PDFs under `saudi_exchange_pdfs/{code}_{company}/` follow the Saudi Exchange
convention `AAA_B_CCCC-CC-CC_DD-DD-DD_EE.pdf`:

- **A** company ID, **B** report type (0 = financial statement),
- **C** reporting date, **D** report ID, **E** language.

## Out of scope (v1)

Versioned extraction history, user accounts, in-UI table editing, automatic
cache expiry, cart persistence across browser restarts.

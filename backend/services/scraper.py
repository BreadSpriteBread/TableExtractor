"""Saudi Exchange PDF scraper service (refactor of pdfs_patchwright.py).

Importable without patchright/playwright installed — browser deps are
imported lazily inside `_scrape_live`. In CI set SCRAPER_STUB=1: the stub
performs no network traffic and just re-syncs the DB from the existing
metadata CSV (live scraping is covered by a manual smoke test).
"""
import asyncio
import csv
import random
import threading
from pathlib import Path

from backend.config import BASE_DIR, PDF_DIR, SCRAPER_STUB, get_logger
from backend.database import seed_from_csv

log = get_logger(__name__)

BASE_URL = "https://www.saudiexchange.sa"
PROFILES_CSV = BASE_DIR / "backend" / "saudi_exchange_company_profiles.csv"

_status_lock = threading.Lock()
_status = {"state": "idle", "message": "", "downloaded": 0, "failed": 0}


def get_status():
    with _status_lock:
        return dict(_status)


def _set_status(**fields):
    with _status_lock:
        _status.update(fields)


def _folder_name(code, name):
    """Canonical on-disk directory name for a company, e.g. 2030_SARCO."""
    return f"{code}_{name}".replace("/", "_").replace("\\", "_").replace(" ", "_")


def _read_profiles():
    """Load the company profile rows from the bundled CSV."""
    with open(PROFILES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def list_companies():
    """Return every company in the profiles CSV, marked with scrape state.

    A company counts as ``scraped`` once its ``{code}_{name}`` directory
    exists under ``PDF_DIR`` and holds at least one PDF. Re-scraping an
    already-scraped company is still allowed.
    """
    root = Path(PDF_DIR)
    companies = []
    for row in _read_profiles():
        code, name = row["code"], row["name"]
        folder = root / _folder_name(code, name)
        pdf_count = len(list(folder.glob("*.pdf"))) if folder.is_dir() else 0
        companies.append({
            "code": code,
            "name": name,
            "sector": row.get("sector", ""),
            "folder": folder.name,
            "scraped": pdf_count > 0,
            "pdf_count": pdf_count,
        })
    return companies


def start_scrape_in_background(codes=None, limit=20):
    """Kick off a scrape in a daemon thread. Returns False if already running.

    ``codes`` is an optional list/set of company codes to scrape; when omitted
    the first ``limit`` companies in the profiles CSV are used.
    """
    with _status_lock:
        if _status["state"] == "running":
            return False
        _status.update(state="running", message="starting", downloaded=0, failed=0)

    def _run():
        try:
            if SCRAPER_STUB:
                _stub_scrape()
            else:
                asyncio.run(_scrape_live(codes=codes, limit=limit))
            _set_status(state="done")  # keep the last progress message
        except Exception as e:
            log.error("scrape failed err=%s", e)
            _set_status(state="error", message=str(e))

    threading.Thread(target=_run, daemon=True, name="scraper").start()
    return True


def _stub_scrape():
    """CI/dev stub: no network, just re-seed the corpus from the metadata CSV.

    Also the production path, and the useful one there: after a local scrape is
    pushed up with deploy/04_sync_corpus.sh, this is what makes the new reports
    appear in the deployed UI without a redeploy. The message says so explicitly
    rather than the bare "stub mode", which read like a broken deployment.
    """
    log.info("scraper stub: re-seeding corpus from metadata CSV (no network)")
    _set_status(message="no live scrape here — re-synced corpus from metadata CSV. "
                        "Saudi Exchange blocks datacenter IPs, so scraping runs "
                        "locally (python3 -m backend.batch_scrape N) and is pushed "
                        "up with deploy/04_sync_corpus.sh.")
    seed_from_csv()


# ----------------------------------------------------------------------
# Live scraping (manual smoke test only; requires patchright + a display)
# ----------------------------------------------------------------------

_METADATA_FIELDS = ["company_code", "company_name", "pdf_url", "local_path", "downloaded"]


def _merge_metadata(metadata_file, new_rows):
    """Upsert new rows into download_metadata.csv, keyed by (code, pdf_url).

    Selective scraping only touches a few companies, so existing rows for
    other companies must be preserved rather than clobbered.
    """
    merged = {}
    if metadata_file.exists():
        with open(metadata_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                merged[(row["company_code"], row["pdf_url"])] = row
    for row in new_rows:
        merged[(str(row["company_code"]), row["pdf_url"])] = row

    with open(metadata_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_METADATA_FIELDS)
        writer.writeheader()
        writer.writerows(merged.values())


async def _random_delay(a=1.0, b=3.0):
    await asyncio.sleep(random.uniform(a, b))


async def _create_browser():
    from patchright.async_api import async_playwright

    p = await async_playwright().start()
    browser = await p.chromium.launch(
        # Headed on purpose, and why scraping is local-only: Saudi Exchange's
        # anti-bot checks flag headless Chromium, and a datacenter egress IP on
        # top of that gets challenged outright. Run this from a desktop.
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = await browser.new_context(
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"),
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="Australia/Sydney",
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        window.chrome = { runtime: {} };
    """)
    return p, browser, context


async def _scrape_document_links(context, company_url):
    page = await context.new_page()
    try:
        await page.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        })
        await page.goto(company_url, wait_until="domcontentloaded", timeout=60000)
        await _random_delay(1, 2)
        await page.mouse.wheel(0, random.randint(300, 800))
        await _random_delay(0.5, 1.5)

        target_frame = None
        for frame in page.frames:
            try:
                if await frame.query_selector("#finacialStatementAndReports"):
                    target_frame = frame
                    break
            except Exception:
                pass
        if target_frame is None:
            raise RuntimeError("Financial statements tab not found")

        tab = await target_frame.query_selector("#finacialStatementAndReports")
        await tab.hover()
        await _random_delay(0.5, 1.5)
        await tab.click()
        await target_frame.wait_for_selector(".inner_tab_sub", timeout=15000)
        await _random_delay()

        links = await target_frame.eval_on_selector_all(
            ".inner_tab_sub td a.btn-pdf",
            "els => els.map(el => el.getAttribute('href'))",
        )
        return [BASE_URL + href for href in links if href]
    finally:
        await page.close()


async def _download_pdf(context, pdf_url, output_path):
    import base64

    page = await context.new_page()
    try:
        await page.goto(pdf_url, wait_until="domcontentloaded", timeout=60000)
        pdf_bytes_b64 = await page.evaluate("""async (url) => {
            const response = await fetch(url);
            const buffer = await response.arrayBuffer();
            const bytes = new Uint8Array(buffer);
            let binary = '';
            for (let i = 0; i < bytes.byteLength; i++) {
                binary += String.fromCharCode(bytes[i]);
            }
            return btoa(binary);
        }""", pdf_url)
        body = base64.b64decode(pdf_bytes_b64)
        if not body.startswith(b"%PDF"):
            raise RuntimeError(f"Not a valid PDF, got: {body[:200]}")
        with open(output_path, "wb") as f:
            f.write(body)
        log.info("downloaded path=%s", output_path)
        return True
    except Exception as e:
        log.warning("download failed url=%s err=%s", pdf_url, e)
        return False
    finally:
        await page.close()


async def _scrape_live(codes=None, limit=20):
    root = Path(PDF_DIR)
    root.mkdir(exist_ok=True)

    all_companies = _read_profiles()
    if codes:
        wanted = {str(c) for c in codes}
        companies = [c for c in all_companies if str(c["code"]) in wanted]
    else:
        companies = all_companies[:limit]

    metadata_rows = []
    playwright, browser, context = await _create_browser()
    downloaded = failed = 0
    try:
        for i, company in enumerate(companies, start=1):
            code, name, url = company["code"], company["name"], company["url"]
            _set_status(message=f"[{i}/{len(companies)}] {code} {name}",
                        downloaded=downloaded, failed=failed)

            folder = root / _folder_name(code, name)
            folder.mkdir(parents=True, exist_ok=True)
            try:
                pdf_links = await _scrape_document_links(context, url)
                for idx, pdf_url in enumerate(pdf_links, start=1):
                    filename = pdf_url.split("/")[-1].split("?")[0]
                    if not filename.lower().endswith(".pdf"):
                        filename = f"report_{idx}.pdf"
                    local_path = folder / filename
                    ok = await _download_pdf(context, pdf_url, local_path)
                    downloaded += 1 if ok else 0
                    failed += 0 if ok else 1
                    metadata_rows.append({
                        "company_code": code,
                        "company_name": name,
                        "pdf_url": pdf_url,
                        # Corpus-relative, prefixed with the corpus dir name to
                        # match existing CSV rows. NOT relative to BASE_DIR:
                        # on Cloud Run the corpus is on the mounted bucket
                        # (/data/saudi_exchange_pdfs), which is not under
                        # BASE_DIR (/app), so relative_to(BASE_DIR) raises.
                        # resolve_corpus_path() reads these back.
                        "local_path": str(Path(PDF_DIR.name) / local_path.relative_to(root)),
                        "downloaded": ok,
                    })
            except Exception as e:
                log.warning("company scrape failed code=%s err=%s", code, e)
            await _random_delay(1, 3)
    finally:
        await browser.close()
        await playwright.stop()

    _merge_metadata(root / "download_metadata.csv", metadata_rows)

    seed_from_csv()  # sync new files into the corpus tables
    _set_status(downloaded=downloaded, failed=failed)
    return downloaded, failed


if __name__ == "__main__":
    asyncio.run(_scrape_live(limit=20))

"""Optional LLM fallback for financials extraction (Google Gemini via REST).

Used only to fill fields the deterministic parser could not recognise — e.g.
when a report labels its lines unusually. Called through ``requests`` (already a
dependency) so the CPU serving image gains no new weight, and it degrades
gracefully: no ``LLM_API_KEY``, no network, or a bad response all return None
and the deterministic result stands.

The key is a free-tier Google AI Studio key, supplied as the ``LLM_API_KEY``
environment variable (see CLAUDE.md).
"""
import json
import os

import requests

from backend.config import get_logger
from backend.financials.schema import ALL_FIELDS, STATEMENTS

log = get_logger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "30"))
# Cap how much table text we send — keeps us inside free-tier limits and latency.
_MAX_CHARS = int(os.environ.get("LLM_MAX_CHARS", "12000"))


def available() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def _field_catalogue() -> str:
    lines = []
    for stmt, fields in STATEMENTS.items():
        lines.append(f"{stmt}:")
        for f in fields:
            lines.append(f"  - {f.key}: {f.label}")
    return "\n".join(lines)


def _tables_as_text(tables: list) -> str:
    parts = []
    for t in tables:
        headers = t.get("headers", []) or []
        rows = t.get("rows", []) or []
        block = [" | ".join(str(h) for h in headers)]
        block += [" | ".join("" if c is None else str(c) for c in row) for row in rows]
        parts.append("\n".join(block))
    text = "\n\n".join(parts)
    return text[:_MAX_CHARS]


def _prompt(tables: list) -> str:
    return (
        "You extract company financial figures from tables pulled out of a "
        "financial report PDF. Return ONLY JSON, no prose.\n\n"
        "Target fields (statement: key: description):\n"
        f"{_field_catalogue()}\n\n"
        "Also detect:\n"
        "- scale: the units figures are stated in (Thousands, Millions, "
        "Billions, or Units).\n"
        "- periods: the reporting-period column labels, exactly as written "
        "(e.g. 2025-12-31).\n\n"
        "Return JSON of shape:\n"
        '{\n'
        '  "scale": "Thousands" | null,\n'
        '  "periods": ["2025-12-31", ...],\n'
        '  "values": { "<field_key>": { "<period>": <number or null>, ... }, ... }\n'
        "}\n"
        "Numbers must be plain (no commas, parentheses mean negative). Omit a "
        "field entirely if it is not present. Do not invent values.\n\n"
        "TABLES:\n"
        f"{_tables_as_text(tables)}"
    )


def _call_gemini(prompt: str):
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    url = _ENDPOINT.format(model=_MODEL)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    try:
        resp = requests.post(url, params={"key": key}, json=payload,
                             timeout=_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except Exception as e:  # network, quota, shape, or JSON error — never fatal
        log.warning("llm financials call failed err=%s", e)
        return None


_VALID_KEYS = {f.key for _stmt, f in ALL_FIELDS}


def llm_extract(tables: list):
    """Ask the LLM for financial values. Returns the parsed dict
    ``{scale, periods, values}`` or None. Best-effort; validates key names."""
    if not tables or not available():
        return None
    parsed = _call_gemini(_prompt(tables))
    if not isinstance(parsed, dict):
        return None
    raw_values = parsed.get("values") or {}
    values = {k: v for k, v in raw_values.items()
              if k in _VALID_KEYS and isinstance(v, dict)}
    return {
        "scale": parsed.get("scale"),
        "periods": [str(p) for p in (parsed.get("periods") or [])],
        "values": values,
    }

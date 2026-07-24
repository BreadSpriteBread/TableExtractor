"""Deterministic financials parser.

Turns an extraction result (the ``{tables: [...]}`` JSON the extractor caches)
into the canonical company-financials structure: three statements, each field
aligned to the document's reporting periods. Pure functions, no I/O.
"""
from backend.financials.schema import (ALL_FIELDS, STATEMENTS, detect_scale,
                                       extract_periods, match_field,
                                       parse_number)


def _row_periods(headers, rows):
    """Reporting periods for a table: prefer the header row, else the first
    data row that carries full dates (a merged in-table section header)."""
    periods = extract_periods(headers or [])
    if periods:
        return periods
    for row in rows:
        # Only full YYYY-MM-DD dates here — bare years risk matching values.
        found = [tok for tok in extract_periods(row) if "-" in tok]
        if found:
            return found
    return []


def _has_full_dates(periods) -> bool:
    return any("-" in p for p in periods)


def _canonical_periods(table_periods) -> list:
    """Pick the document's reporting-period axis from each table's detected
    periods. Real reports state the same columns on every statement, so prefer
    the richest date-bearing list: full-date lists beat bare-year lists, and
    longer beats shorter. Returns [] when no table exposed any periods."""
    candidates = [p for p in table_periods if p]
    if not candidates:
        return []
    dated = [p for p in candidates if _has_full_dates(p)]
    pool = dated or candidates
    return max(pool, key=len)


def _numbers_after_label(row):
    """Parsed numbers from every cell after the first (the label), in order,
    dropping cells that aren't numeric (blank separators, stray text)."""
    return [n for n in (parse_number(c) for c in row[1:]) if n is not None]


def derive_financials(result: dict) -> dict:
    """Map an extraction result to canonical financials.

    Returns a structure with detected ``scale`` and ``periods`` plus every
    canonical field (values aligned to ``periods``, null where not found). Only
    the first occurrence of each field is taken, so a repeated summary block
    never overwrites an earlier, cleaner match.
    """
    tables = result.get("tables", []) if result else []

    # Per-table period detection first, so we can settle on ONE period axis
    # before mapping any values. Tables that expose no dates of their own then
    # align positionally to that axis instead of inventing phantom columns.
    table_periods = [_row_periods(t.get("headers", []) or [], t.get("rows", []) or [])
                     for t in tables]
    canonical = _canonical_periods(table_periods)

    # period label -> {field_key: value}
    values: dict = {}
    period_order: list = list(canonical)
    for p in period_order:
        values.setdefault(p, {})
    scale = None
    filled = set()

    def _register_period(p):
        if p not in period_order:
            period_order.append(p)
            values.setdefault(p, {})

    for t, periods in zip(tables, table_periods):
        headers = t.get("headers", []) or []
        rows = t.get("rows", []) or []

        if scale is None:
            scale = detect_scale(headers)
        for row in rows:
            if scale is None:
                scale = detect_scale(row)

        for row in rows:
            if not row:
                continue
            hit = match_field(row[0])
            if not hit:
                continue
            _stmt, key = hit
            if key in filled:
                continue
            nums = _numbers_after_label(row)
            if not nums:
                continue
            # This table's own periods if it has them, else the document axis,
            # else positional columns as a last resort (no dates anywhere).
            targets = periods or canonical or [f"col{i + 1}" for i in range(len(nums))]
            for p in targets:
                _register_period(p)
            for p, n in zip(targets, nums):
                values[p][key] = n
            filled.add(key)

    # Emit statements with every canonical field aligned to the final period order.
    statements: dict = {}
    for stmt, fields in STATEMENTS.items():
        statements[stmt] = {}
        for f in fields:
            statements[stmt][f.key] = {
                "label": f.label,
                "values": [values.get(p, {}).get(f.key) for p in period_order],
            }

    warnings = []
    if not period_order:
        warnings.append("No reporting periods detected in the extracted tables.")
    if not filled:
        warnings.append("No recognisable financial line items were found.")

    return {
        "scale": scale,
        "periods": period_order,
        "statements": statements,
        "found_fields": len(filled),
        "total_fields": len(ALL_FIELDS),
        "warnings": warnings,
    }


def missing_fields(financials: dict) -> list:
    """Canonical (statement, key) pairs that have no value in any period —
    used to decide whether an LLM pass is worth making."""
    out = []
    for stmt, fields in STATEMENTS.items():
        block = financials.get("statements", {}).get(stmt, {})
        for f in fields:
            vals = block.get(f.key, {}).get("values", [])
            if not any(v is not None for v in vals):
                out.append((stmt, f.key))
    return out

"""Canonical company-financials schema + the label/number/period primitives
the deterministic parser is built on.

The Saudi Exchange "financial summary" tables are laid out as one row per line
item and one column per reporting period (a date like ``2025-12-31``). We map
each extracted row's *label* (its first cell) onto a canonical field, parse the
remaining cells as per-period numbers, and detect the reporting periods from the
table header. Everything here is pure text/number logic — no I/O, no network —
so it is cheap, deterministic, and unit-testable in isolation.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    """A canonical financial line item and how to recognise its label.

    A row label (normalised) matches when it contains every token in ``all_of``,
    at least one token in ``any_of`` (when given), and none of ``none_of``.
    """
    key: str
    label: str                       # human-readable name for the UI
    all_of: tuple = ()
    any_of: tuple = ()
    none_of: tuple = ()

    def matches(self, norm_label: str) -> bool:
        if not all(tok in norm_label for tok in self.all_of):
            return False
        if self.any_of and not any(tok in norm_label for tok in self.any_of):
            return False
        if any(tok in norm_label for tok in self.none_of):
            return False
        return True


# Ordered per statement. Order matters: the first matching field wins for a
# given row, and the excludes below are tuned so overlapping labels (e.g.
# "Total Liabilities" vs "Total Liabilities and Shareholders Equity") resolve to
# exactly one field.
STATEMENTS = {
    "balance_sheet": [
        Field("total_assets", "Total Assets", all_of=("total asset",)),
        # exclude the "…and Shareholders Equity" total, which carries both words
        Field("total_liabilities", "Total Liabilities",
              all_of=("total liabilit",), none_of=("shareholder", "equity")),
        Field("total_shareholders_equity", "Total Shareholders Equity",
              all_of=("shareholder", "equit"), none_of=("liabilit",)),
    ],
    "income_statement": [
        Field("total_revenue", "Total Revenue (Sales/Operating)",
              all_of=("revenue",)),
        Field("net_profit_before_tax", "Net Profit (Loss) before Tax",
              all_of=("profit", "before"), any_of=("before tax", "before zakat")),
        Field("income_tax", "Income Tax",
              all_of=("tax",), none_of=("before", "profit", "per share")),
        Field("net_profit_attributable_to_shareholders",
              "Net Profit (Loss) Attributable to Shareholders of the Issuer",
              all_of=("profit", "attributable", "shareholder"),
              none_of=("comprehensive",)),
        Field("total_comprehensive_income_attributable_to_shareholders",
              "Total Comprehensive Income Attributable to Shareholders of the Issuer",
              all_of=("comprehensive", "attributable")),
        Field("profit_per_share", "Profit (Loss) per Share",
              any_of=("per share", "earnings per share", "eps"),
              none_of=("comprehensive",)),
    ],
    "cash_flow": [
        Field("net_cash_operating", "Net Cash From Operating Activities",
              all_of=("operating activit",)),
        Field("net_cash_investing", "Net Cash From Investing Activities",
              all_of=("investing activit",)),
        Field("net_cash_financing", "Net Cash From Financing Activities",
              all_of=("financing activit",)),
        Field("cash_beginning_of_period",
              "Cash and Cash Equivalents, Beginning of the Period",
              all_of=("cash", "beginning")),
        Field("cash_end_of_period",
              "Cash and Cash Equivalents, End of the Period",
              all_of=("cash", "end of"), none_of=("beginning",)),
    ],
}

# Flat view: (statement, Field) in canonical order, for iteration.
ALL_FIELDS = [(stmt, f) for stmt, fields in STATEMENTS.items() for f in fields]

# "All Figures in <Thousands|Millions|…>" — the reporting scale row.
_SCALE_LABEL_TOKENS = ("all figures in", "figures in", "amounts in", "sar in")
_SCALE_VALUES = ("thousands", "millions", "billions", "units")

_DATE_FULL = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DATE_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_PUNCT = re.compile(r"[^a-z0-9]+")


def normalize_label(text) -> str:
    """Lowercase, strip punctuation to spaces, collapse whitespace."""
    return _PUNCT.sub(" ", str(text).lower()).strip()


def match_field(label):
    """Return (statement, key) for the first canonical field a label matches,
    or None. ``label`` is the raw first-cell text."""
    norm = normalize_label(label)
    if not norm:
        return None
    for stmt, f in ALL_FIELDS:
        if f.matches(norm):
            return stmt, f.key
    return None


def parse_number(cell):
    """Parse a financial cell into a number, or None.

    Handles thousands separators, parenthesised negatives ``(1,234)``, a leading
    minus, unicode dashes, and empty / placeholder cells.
    """
    if cell is None:
        return None
    s = str(cell).strip()
    if s in ("", "-", "–", "—", "n/a", "na", "N/A"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.replace(",", "").replace(" ", "").replace("−", "-")
    if s.startswith("-"):
        neg, s = True, s[1:]
    if not re.fullmatch(r"\d*\.?\d+", s):
        return None
    val = float(s)
    val = -val if neg else val
    return int(val) if val.is_integer() else val


def extract_periods(cells) -> list:
    """Pull reporting-period labels (dates/years) from a header-ish row, in
    order, deduped. Prefers full ``YYYY-MM-DD`` dates; falls back to bare years.
    """
    joined = [str(c) for c in cells]
    full = []
    for c in joined:
        full += _DATE_FULL.findall(c)
    if full:
        return list(dict.fromkeys(full))
    years = []
    for c in joined:
        years += _DATE_YEAR.findall(c)
    return list(dict.fromkeys(years))


def detect_scale(cells):
    """If a row is the "All Figures in …" scale row, return its value
    (e.g. "Thousands"), else None."""
    label = normalize_label(cells[0]) if cells else ""
    if not any(tok in label for tok in _SCALE_LABEL_TOKENS):
        return None
    for c in cells[1:]:
        norm = normalize_label(c)
        for val in _SCALE_VALUES:
            if val in norm:
                return val.capitalize()
    return None

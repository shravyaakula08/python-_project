"""Small parsing helpers (missing tokens, numbers, dates, normalisation)."""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Optional, Tuple

MISSING_TOKENS = {"", "n/a", "na", "null", "none", "nan", "-", "--", "?", "missing", "unknown"}

# Day-first formats are tried before month-first ones.
DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y",
]


def is_missing(value) -> bool:
    """True for None, blanks and placeholder tokens such as N/A, null, -."""
    return value is None or str(value).strip().lower() in MISSING_TOKENS


def clean_text(value) -> str:
    """Trim and collapse repeated whitespace."""
    return " ".join(str(value if value is not None else "").split())


def norm_key(value) -> str:
    """Case/punctuation-insensitive key used to group spelling variants."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def parse_number(value, allow_pct: bool = False) -> Optional[float]:
    s = str(value).strip().replace(",", "")
    if allow_pct and s.endswith("%"):
        s = s[:-1].strip()
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def fmt_number(n: float, kind: str = "float") -> str:
    if kind == "int":
        return str(int(round(n)))
    return f"{n:.10g}"


def parse_date(value) -> Tuple[Optional[date], Optional[str]]:
    """Return (date, format_used) or (None, None)."""
    s = clean_text(value)
    if not s:
        return None, None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date(), fmt
        except ValueError:
            continue
    return None, None

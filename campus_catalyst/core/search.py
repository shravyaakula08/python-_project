"""Keyword, category and numeric-range filtering."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from core.models import Issue
from core.parsing import clean_text, parse_number


def search_records(rows: List[dict], columns: List[str], keyword: str = "",
                   filters: Optional[Dict[str, str]] = None,
                   ranges: Optional[Dict[str, Tuple[Optional[float], Optional[float]]]] = None,
                   issue_rows: Optional[Iterable[int]] = None) -> List[Tuple[int, dict]]:
    """Return [(row_no, record)] matching ALL given conditions (1-based row numbers)."""
    kw = clean_text(keyword).lower()
    allowed = set(issue_rows) if issue_rows is not None else None
    out = []
    for i, r in enumerate(rows, 1):
        if allowed is not None and i not in allowed:
            continue
        if kw and not any(kw in str(r.get(c, "")).lower() for c in columns):
            continue
        if filters and not all(clean_text(r.get(c, "")).lower() == clean_text(v).lower()
                               for c, v in filters.items() if clean_text(v)):
            continue
        if ranges:
            ok = True
            for c, (lo, hi) in ranges.items():
                n = parse_number(r.get(c, ""))
                if n is None or (lo is not None and n < lo) or (hi is not None and n > hi):
                    ok = False
                    break
            if not ok:
                continue
        out.append((i, r))
    return out


def rows_with_issue_kind(issues: List[Issue], kind: str) -> List[int]:
    return sorted({i.row for i in issues if i.kind == kind})


def distinct_values(rows: List[dict], col: str, limit: int = 50) -> List[str]:
    vals = sorted({clean_text(r.get(col, "")) for r in rows if clean_text(r.get(col, ""))})
    return vals[:limit]

"""Executive summary: totals, averages, status indicators and trends."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, List

from core.cleaner import category_map
from core.models import Issue
from core.parsing import is_missing, parse_date, parse_number

STATUS_HEALTHY, STATUS_ATTENTION, STATUS_CRITICAL = "Healthy", "Needs Attention", "Critical"


def status_for(score: float) -> str:
    if score >= 97:
        return STATUS_HEALTHY
    if score >= 90:
        return STATUS_ATTENTION
    return STATUS_CRITICAL


def compute_summary(columns: List[str], rows: List[dict], issues: List[Issue],
                    rules: Dict[str, dict]) -> dict:
    n_rows, n_cols = len(rows), len(columns)
    cells = max(n_rows * n_cols, 1)

    missing_cells = sum(1 for i in issues if i.kind == "missing")
    bad_cells = len({(i.row, i.column) for i in issues
                     if i.kind == "inconsistent" and i.subtype != "outlier"})
    dup_rows = len({i.row for i in issues if i.subtype == "exact duplicate"})
    rows_with_issues = len({i.row for i in issues})

    completeness = 100 * (1 - missing_cells / cells)
    validity = 100 * (1 - bad_cells / cells)
    uniqueness = 100 * (1 - dup_rows / max(n_rows, 1))
    score = round(0.4 * completeness + 0.4 * validity + 0.2 * uniqueness, 1) if n_rows else 100.0

    missing_by_col = Counter(i.column for i in issues if i.kind == "missing")
    inconsistent_by_col = Counter(i.column for i in issues if i.kind == "inconsistent")

    # numeric statistics (only values that satisfy the column's range rule)
    numeric = {}
    for c in columns:
        rule = rules.get(c, {})
        if rule.get("type") not in ("int", "float"):
            continue
        lo, hi = rule.get("min"), rule.get("max")
        vals = []
        for r in rows:
            n = parse_number(r.get(c, ""), allow_pct=True)
            if n is None or (lo is not None and n < lo) or (hi is not None and n > hi):
                continue
            vals.append(n)
        if vals:
            numeric[c] = {"count": len(vals), "mean": statistics.fmean(vals),
                          "median": statistics.median(vals), "min": min(vals), "max": max(vals),
                          "stdev": statistics.pstdev(vals) if len(vals) > 1 else 0.0}

    # category distributions (standardised spellings)
    categories = {}
    for c in columns:
        rule = rules.get(c, {})
        if rule.get("type") == "category":
            cmap = category_map(rows, c, rule)
            cnt = Counter(cmap.values())
            categories[c] = cnt.most_common(8)

    return {
        "rows": n_rows, "columns": n_cols, "cells": n_rows * n_cols,
        "missing_cells": missing_cells, "inconsistent_cells": bad_cells,
        "duplicate_rows": dup_rows, "rows_with_issues": rows_with_issues,
        "clean_rows": n_rows - rows_with_issues,
        "clean_rows_pct": round(100 * (n_rows - rows_with_issues) / n_rows, 1) if n_rows else 100.0,
        "completeness": round(completeness, 1), "validity": round(validity, 1),
        "uniqueness": round(uniqueness, 1), "quality_score": score, "status": status_for(score),
        "total_issues": len(issues),
        "by_kind": dict(Counter(i.kind for i in issues)),
        "by_subtype": dict(Counter(i.subtype for i in issues)),
        "by_severity": dict(Counter(i.severity for i in issues)),
        "missing_by_column": {c: missing_by_col.get(c, 0) for c in columns},
        "inconsistent_by_column": {c: inconsistent_by_col.get(c, 0) for c in columns},
        "numeric": numeric, "categories": categories,
        "trend": compute_trend(columns, rows, rules),
    }


def compute_trend(columns: List[str], rows: List[dict], rules: Dict[str, dict]) -> dict:
    """Group records by enrolment period and average the main numeric column."""
    date_col = next((c for c in columns if rules.get(c, {}).get("type") == "date"), None)
    num_cols = [c for c in columns if rules.get(c, {}).get("type") in ("int", "float")]
    num_col = "marks" if "marks" in num_cols else (num_cols[0] if num_cols else None)
    if not date_col or not num_col:
        return {}
    rule = rules[num_col]
    lo, hi = rule.get("min"), rule.get("max")
    buckets = defaultdict(list)
    counts = Counter()
    for r in rows:
        d, _ = parse_date(r.get(date_col, ""))
        if d is None or d > date.today():
            continue
        key = str(d.year)
        counts[key] += 1
        n = parse_number(r.get(num_col, ""), allow_pct=True)
        if n is not None and not ((lo is not None and n < lo) or (hi is not None and n > hi)):
            buckets[key].append(n)
    periods = sorted(counts)
    return {"date_column": date_col, "value_column": num_col, "periods": periods,
            "counts": [counts[p] for p in periods],
            "averages": [round(statistics.fmean(buckets[p]), 2) if buckets[p] else None for p in periods]}

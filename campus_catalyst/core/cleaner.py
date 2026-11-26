"""Core business logic: find missing values, duplicate rows and inconsistent entries, and fix them."""
from __future__ import annotations

import difflib
import re
import statistics
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from core.models import Issue
from core.parsing import (clean_text, fmt_number, is_missing, norm_key,
                          parse_date, parse_number)
from core.schema import EMAIL_REGEX

KIND_ORDER = {"missing": 0, "duplicate": 1, "inconsistent": 2}
SEV_ORDER = {"high": 0, "medium": 1, "low": 2}

FIX_OPTIONS = {
    "trim": "Trim extra spaces and turn placeholders (N/A, null, -) into blanks",
    "numbers": "Strip symbols from numbers (e.g. 92% -> 92)",
    "casing": "Fix name/email casing (Title Case names, lowercase emails)",
    "categories": "Standardise category spellings (comp sci / CS -> Computer Science)",
    "dates": "Convert every date to ISO format (YYYY-MM-DD)",
    "duplicates": "Remove exact duplicate rows (first occurrence is kept)",
    "fill": "Fill missing numeric cells with the median and categories with the most common value",
}


def date_format_label(fmt: str) -> str:
    """'%d/%m/%Y' -> 'DD/MM/YYYY' (friendlier for messages)."""
    for a, b in (("%Y", "YYYY"), ("%m", "MM"), ("%d", "DD"), ("%B", "Month"), ("%b", "Mon")):
        fmt = fmt.replace(a, b)
    return fmt


def _finding(kind, subtype, severity, message, suggestion="") -> dict:
    return dict(kind=kind, subtype=subtype, severity=severity, message=message, suggestion=suggestion)


# --------------------------------------------------------------------------- cell level
def check_cell(col: str, value, rule: dict) -> List[dict]:
    """Context-free validation of a single cell."""
    out: List[dict] = []
    t = rule.get("type", "text")
    sv = "" if value is None else str(value)

    if is_missing(sv):
        placeholder = sv.strip() != ""
        msg = f"Missing value in '{col}'" + (f" (placeholder '{sv.strip()}')" if placeholder else "")
        out.append(_finding("missing", "placeholder" if placeholder else "blank",
                            "high" if rule.get("required") else "medium", msg))
        return out

    s = sv.strip()

    if t in ("int", "float"):
        n = parse_number(s)
        if n is None:
            n2 = parse_number(s, allow_pct=True)
            if n2 is None:
                out.append(_finding("inconsistent", "invalid type", "high",
                                    f"'{s}' is not a number (expected {t})"))
                return out
            out.append(_finding("inconsistent", "invalid type", "medium",
                                f"'{s}' contains a symbol; expected a plain number", fmt_number(n2, t)))
            n = n2
        if t == "int" and n != int(n):
            out.append(_finding("inconsistent", "invalid type", "medium",
                                f"'{s}' is not a whole number", fmt_number(n, "int")))
        lo, hi = rule.get("min"), rule.get("max")
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            out.append(_finding("inconsistent", "out of range", "high",
                                f"{s} is outside the allowed range [{lo}, {hi}]"))
    elif t == "date":
        d, _fmt = parse_date(s)
        if d is None:
            out.append(_finding("inconsistent", "invalid format", "high", f"'{s}' is not a valid date"))
        elif d > date.today():
            out.append(_finding("inconsistent", "out of range", "high",
                                f"{d.isoformat()} is a future date"))
    elif t == "email":
        if not re.match(EMAIL_REGEX, s):
            out.append(_finding("inconsistent", "invalid format", "high", f"'{s}' is not a valid email address"))
        elif s != s.lower():
            out.append(_finding("inconsistent", "casing", "low", "Email should be lowercase", s.lower()))
    else:
        rx = rule.get("regex")
        if rx and not re.match(rx, clean_text(s)):
            out.append(_finding("inconsistent", "invalid format", "high",
                                f"'{s}' does not match the expected pattern" +
                                (f" ({rule['hint']})" if rule.get("hint") else "")))
        if rule.get("title_case") and len(s) > 3 and (s.islower() or s.isupper()):
            out.append(_finding("inconsistent", "casing", "low",
                                "Name should be in Title Case", clean_text(s).title()))

    if t in ("text", "category", "id", "email") and sv != clean_text(sv):
        out.append(_finding("inconsistent", "extra whitespace", "low",
                            "Leading/trailing/double spaces", clean_text(sv)))
    return out


def check_row(row: dict, columns: List[str], rules: Dict[str, dict], skip=()) -> List[str]:
    """Row-level validation used for new entries and bulk-import logs. Returns messages."""
    msgs = []
    for col in columns:
        if col in skip:
            continue
        for f in check_cell(col, row.get(col, ""), rules.get(col, {})):
            if f["subtype"] in ("extra whitespace", "casing"):
                continue  # cosmetic, fixable later
            msgs.append(f"{col}: {f['message']}")
    return msgs


# --------------------------------------------------------------------------- categories
def category_map(rows: List[dict], col: str, rule: dict) -> Dict[str, str]:
    """Map every (whitespace-cleaned) spelling found in a column to its canonical spelling."""
    values = [clean_text(r.get(col, "")) for r in rows if not is_missing(r.get(col, ""))]
    groups: Dict[str, Counter] = defaultdict(Counter)
    for v in values:
        groups[norm_key(v)][v] += 1
    alias_map = {}
    for canon, aliases in (rule.get("aliases") or {}).items():
        for a in list(aliases) + [canon]:
            alias_map[norm_key(a)] = canon

    totals = {k: sum(c.values()) for k, c in groups.items()}
    canon_of: Dict[str, str] = {}
    for key, cnt in groups.items():
        if key in alias_map:
            canon_of[key] = alias_map[key]
        else:
            canon_of[key] = sorted(cnt, key=lambda v: (-cnt[v], v.isupper(), not v[:1].isupper(), v))[0]
    # fuzzy merge for rare typos ("Mechancial" -> "Mechanical")
    for key in list(groups):
        if key in alias_map or totals[key] > 2:
            continue
        bigger = [k for k in groups if totals[k] > totals[key]]
        match = difflib.get_close_matches(key, bigger, n=1, cutoff=0.85)
        if match:
            canon_of[key] = canon_of[match[0]]
    return {v: canon_of[norm_key(v)] for v in values}


# --------------------------------------------------------------------------- duplicates
def exact_duplicates(columns: List[str], rows: List[dict], rules: Dict[str, dict]) -> Dict[int, int]:
    """{duplicate_row_no: first_row_no}; ID columns are ignored when comparing."""
    cmp_cols = [c for c in columns if rules.get(c, {}).get("type") != "id"] or list(columns)
    seen: Dict[tuple, int] = {}
    dups: Dict[int, int] = {}
    for i, row in enumerate(rows, 1):
        vals = tuple(clean_text(row.get(c, "")).lower() for c in cmp_cols)
        if all(is_missing(v) for v in vals):
            continue
        if vals in seen:
            dups[i] = seen[vals]
        else:
            seen[vals] = i
    return dups


def _duplicate_issues(columns, rows, rules) -> List[Issue]:
    issues: List[Issue] = []
    exact = exact_duplicates(columns, rows, rules)
    for i, first in exact.items():
        issues.append(Issue("duplicate", "exact duplicate", i, "(entire row)", f"same as row {first}",
                            f"Row {i} is an exact duplicate of row {first}", "Remove this row", "high"))
    for col in columns:
        t = rules.get(col, {}).get("type")
        if t not in ("id", "email"):
            continue
        seen: Dict[str, int] = {}
        for i, row in enumerate(rows, 1):
            v = clean_text(row.get(col, "")).lower()
            if is_missing(v):
                continue
            if v in seen:
                first = seen[v]
                if exact.get(i) == first:
                    continue
                issues.append(Issue("duplicate", "duplicate key", i, col, row.get(col, ""),
                                    f"'{col}' value '{row.get(col, '')}' already used in row {first}",
                                    "Review: merge or correct one of the rows",
                                    "high" if t == "id" else "medium"))
            else:
                seen[v] = i
    return issues


# --------------------------------------------------------------------------- analysis
def analyze(columns: List[str], rows: List[dict], rules: Dict[str, dict]) -> List[Issue]:
    """Run every detector and return the issues sorted by kind, row and column."""
    issues: List[Issue] = []

    for i, row in enumerate(rows, 1):
        for col in columns:
            for f in check_cell(col, row.get(col, ""), rules.get(col, {})):
                issues.append(Issue(f["kind"], f["subtype"], i, col, str(row.get(col, "")),
                                    f["message"], f["suggestion"], f["severity"]))

    for col in columns:
        rule = rules.get(col, {})
        t = rule.get("type")
        if t == "category":
            cmap = category_map(rows, col, rule)
            for i, row in enumerate(rows, 1):
                raw = row.get(col, "")
                if is_missing(raw):
                    continue
                canon = cmap.get(clean_text(raw))
                if canon and clean_text(raw) != canon:
                    issues.append(Issue("inconsistent", "spelling variant", i, col, str(raw),
                                        f"'{clean_text(raw)}' differs from the standard '{canon}'",
                                        canon, "medium"))
        elif t == "date":
            fmts = {}
            for i, row in enumerate(rows, 1):
                d, fmt = parse_date(row.get(col, ""))
                if d is not None:
                    fmts[i] = (d, fmt)
            counts = Counter(f for _, f in fmts.values())
            if len(counts) > 1:
                dominant = counts.most_common(1)[0][0]
                for i, (d, fmt) in fmts.items():
                    if fmt != dominant:
                        issues.append(Issue("inconsistent", "mixed date format", i, col,
                                            str(rows[i - 1].get(col, "")),
                                            f"Date format differs from the dominant style ({date_format_label(dominant)})",
                                            d.isoformat(), "medium"))
        elif t in ("int", "float") and rule.get("min") is None and rule.get("max") is None:
            # statistical outlier check only for columns without explicit domain bounds
            lo = hi = None
            nums = []
            for i, row in enumerate(rows, 1):
                n = parse_number(row.get(col, ""), allow_pct=True)
                if n is None:
                    continue
                if (lo is not None and n < lo) or (hi is not None and n > hi):
                    continue
                nums.append((i, n))
            if len(nums) >= 8:
                q = statistics.quantiles([n for _, n in nums], n=4)
                iqr = q[2] - q[0]
                if iqr > 0:
                    low, high = q[0] - 3 * iqr, q[2] + 3 * iqr
                    for i, n in nums:
                        if n < low or n > high:
                            issues.append(Issue("inconsistent", "outlier", i, col, str(rows[i - 1].get(col, "")),
                                                f"{n:g} is far outside the typical range ({low:g} to {high:g})",
                                                "", "low"))

    issues.extend(_duplicate_issues(columns, rows, rules))
    issues.sort(key=lambda x: (KIND_ORDER[x.kind], x.row, x.column))
    return issues


# --------------------------------------------------------------------------- fixing
def _valid_numbers(rows, col, rule) -> List[float]:
    lo, hi = rule.get("min"), rule.get("max")
    out = []
    for r in rows:
        n = parse_number(r.get(col, ""), allow_pct=True)
        if n is None:
            continue
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            continue
        out.append(n)
    return out


def apply_fixes(columns: List[str], rows: List[dict], rules: Dict[str, dict],
                options: Set[str]) -> Tuple[List[dict], List[str]]:
    """Return (new_rows, change_log). The input rows are never modified."""
    new = [dict(r) for r in rows]
    log: List[str] = []

    def bump(n, text):
        if n:
            log.append(f"{text}: {n}")

    if "trim" in options:
        n = 0
        for r in new:
            for c in columns:
                old = r.get(c, "")
                v = "" if is_missing(old) else clean_text(old)
                if v != old:
                    r[c] = v
                    n += 1
        bump(n, "Cells trimmed / placeholders blanked")

    if "numbers" in options:
        n = 0
        for c in columns:
            t = rules.get(c, {}).get("type")
            if t not in ("int", "float"):
                continue
            for r in new:
                v = r.get(c, "")
                if is_missing(v) or parse_number(v) is not None:
                    continue
                n2 = parse_number(v, allow_pct=True)
                if n2 is not None:
                    r[c] = fmt_number(n2, t)
                    n += 1
        bump(n, "Numbers cleaned of symbols")

    if "casing" in options:
        n = 0
        for c in columns:
            rule = rules.get(c, {})
            for r in new:
                v = r.get(c, "")
                if is_missing(v):
                    continue
                if rule.get("type") == "email" and v != v.strip().lower():
                    r[c] = v.strip().lower(); n += 1
                elif rule.get("title_case") and len(v.strip()) > 3 and (v.islower() or v.isupper()):
                    r[c] = clean_text(v).title(); n += 1
        bump(n, "Casing fixed")

    if "categories" in options:
        n = 0
        for c in columns:
            rule = rules.get(c, {})
            if rule.get("type") != "category":
                continue
            cmap = category_map(new, c, rule)
            for r in new:
                v = r.get(c, "")
                if is_missing(v):
                    continue
                canon = cmap.get(clean_text(v))
                if canon and v != canon:
                    r[c] = canon; n += 1
        bump(n, "Category spellings standardised")

    if "dates" in options:
        n = 0
        for c in columns:
            if rules.get(c, {}).get("type") != "date":
                continue
            for r in new:
                d, _ = parse_date(r.get(c, ""))
                if d is not None and r[c] != d.isoformat():
                    r[c] = d.isoformat(); n += 1
        bump(n, "Dates converted to YYYY-MM-DD")

    if "duplicates" in options:
        dups = exact_duplicates(columns, new, rules)
        if dups:
            new = [r for i, r in enumerate(new, 1) if i not in dups]
            log.append(f"Exact duplicate rows removed: {len(dups)} (rows {', '.join(map(str, sorted(dups)))})")

    if "fill" in options:
        n = 0
        for c in columns:
            rule = rules.get(c, {})
            t = rule.get("type")
            fill = None
            if t in ("int", "float"):
                nums = _valid_numbers(new, c, rule)
                if nums:
                    fill = fmt_number(statistics.median(nums), t)
            elif t == "category":
                cmap = category_map(new, c, rule)
                if cmap:
                    fill = Counter(cmap.values()).most_common(1)[0][0]
            if fill is None:
                continue
            for r in new:
                if is_missing(r.get(c, "")):
                    r[c] = fill; n += 1
        bump(n, "Missing values filled (median / most common)")

    if not log:
        log.append("Nothing needed fixing for the selected options.")
    return new, log

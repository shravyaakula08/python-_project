"""Multi-format summary export: Markdown report, plain-text audit log, CSV issue report."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.models import Alert, Issue

CSV_FIELDS = ["row", "column", "kind", "subtype", "severity", "value", "message", "suggestion"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def issues_csv_text(issues: List[Issue]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for i in issues:
        w.writerow(i.to_dict())
    return buf.getvalue()


def markdown_report(summary: dict, issues: List[Issue], alerts: List[Alert], source: str = "working dataset",
                    max_issues: int = 200) -> str:
    s = summary
    L = [f"# Data Quality Report", "", f"*Generated {_now()} - source: {source}*", "",
         "## Executive summary", "",
         "| Metric | Value |", "|---|---|",
         f"| Records | {s['rows']} |", f"| Columns | {s['columns']} |",
         f"| Quality score | **{s['quality_score']} / 100** ({s['status']}) |",
         f"| Completeness | {s['completeness']}% |", f"| Validity | {s['validity']}% |",
         f"| Uniqueness | {s['uniqueness']}% |",
         f"| Clean rows | {s['clean_rows']} of {s['rows']} ({s['clean_rows_pct']}%) |",
         f"| Missing cells | {s['missing_cells']} |", f"| Duplicate rows | {s['duplicate_rows']} |",
         f"| Inconsistent cells | {s['inconsistent_cells']} |", "",
         "## Threshold warnings", ""]
    L += [f"- **{a.level}** - {a.message}" for a in alerts] or ["- none"]
    L += ["", "## Issues by type", "", "| Type | Count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(s["by_subtype"].items(), key=lambda kv: -kv[1])] or ["| none | 0 |"]
    if s["numeric"]:
        L += ["", "## Numeric columns (valid values only)", "",
              "| Column | Count | Mean | Median | Min | Max | Std dev |", "|---|---|---|---|---|---|---|"]
        for c, st in s["numeric"].items():
            L.append(f"| {c} | {st['count']} | {st['mean']:.2f} | {st['median']:.2f} | {st['min']:g} | {st['max']:g} | {st['stdev']:.2f} |")
    for c, items in s["categories"].items():
        L += ["", f"## Distribution: {c}", "", "| Value | Records |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in items]
    t = s.get("trend") or {}
    if t.get("periods"):
        L += ["", f"## Trend: average {t['value_column']} by {t['date_column']} year", "",
              "| Year | Records | Average |", "|---|---|---|"]
        L += [f"| {p} | {n} | {a if a is not None else '-'} |" for p, n, a in zip(t["periods"], t["counts"], t["averages"])]
    L += ["", f"## Issue details ({min(len(issues), max_issues)} of {len(issues)} shown)", "",
          "| Row | Column | Type | Severity | Problem | Suggested fix |", "|---|---|---|---|---|---|"]
    for i in issues[:max_issues]:
        L.append(f"| {i.row} | {i.column} | {i.kind}/{i.subtype} | {i.severity} | {i.message.replace('|', '/')} | {i.suggestion.replace('|', '/')} |")
    return "\n".join(L) + "\n"


def audit_log_text(summary: dict, issues: List[Issue], alerts: List[Alert], source: str = "working dataset") -> str:
    s = summary
    L = ["=" * 78, "CAMPUS CATALYST - DATA CLEANING AUDIT LOG", "=" * 78,
         f"Generated : {_now()}", f"Source    : {source}",
         f"Records   : {s['rows']}   Columns: {s['columns']}",
         f"Quality   : {s['quality_score']}/100 ({s['status']})",
         f"Missing   : {s['missing_cells']}   Duplicates: {s['duplicate_rows']}   Inconsistent: {s['inconsistent_cells']}",
         "", "-" * 78, "WARNINGS", "-" * 78]
    L += [f"[{a.level:8}] {a.message}" for a in alerts]
    L += ["", "-" * 78, "FINDINGS", "-" * 78]
    for i in issues:
        L.append(f"[{i.severity.upper():6}] row {i.row:<4} {i.column:<16} {i.kind}/{i.subtype}: {i.message}"
                 + (f"  -> suggested: {i.suggestion}" if i.suggestion else ""))
    if not issues:
        L.append("No issues found.")
    L += ["", "=" * 78, "END OF LOG"]
    return "\n".join(L) + "\n"


def export_reports(outdir, summary, issues, alerts, formats=("md", "txt", "csv"), source="working dataset") -> List[Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    paths = []
    if "md" in formats:
        p = outdir / f"report_{stamp}.md"
        p.write_text(markdown_report(summary, issues, alerts, source), encoding="utf-8"); paths.append(p)
    if "txt" in formats:
        p = outdir / f"audit_log_{stamp}.txt"
        p.write_text(audit_log_text(summary, issues, alerts, source), encoding="utf-8"); paths.append(p)
    if "csv" in formats:
        p = outdir / f"issues_report_{stamp}.csv"
        p.write_text(issues_csv_text(issues), encoding="utf-8", newline=""); paths.append(p)
    return paths

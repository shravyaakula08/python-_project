"""Threshold warning indicators (console flags / GUI banners)."""
from __future__ import annotations

from typing import Dict, List

from core.models import Alert, Issue

DEFAULT_THRESHOLDS = {
    "missing_pct_column": 10.0,       # % of a column that may be blank
    "inconsistent_pct_column": 10.0,  # % of a column with bad entries
    "duplicate_pct": 5.0,             # % of rows that may be duplicates
    "quality_warning": 97.0,
    "quality_critical": 90.0,
}

_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def generate_alerts(summary: dict, issues: List[Issue], thresholds: Dict[str, float] = None) -> List[Alert]:
    th = dict(DEFAULT_THRESHOLDS)
    th.update(thresholds or {})
    n = max(summary["rows"], 1)
    alerts: List[Alert] = []

    if summary["rows"] == 0:
        return [Alert("INFO", "Dataset is empty - add or import records to begin.")]

    for col, cnt in summary["missing_by_column"].items():
        pct = 100 * cnt / n
        if cnt and pct > th["missing_pct_column"]:
            lvl = "CRITICAL" if pct > 2 * th["missing_pct_column"] else "WARNING"
            alerts.append(Alert(lvl, f"{pct:.0f}% of '{col}' is missing ({cnt} of {n} rows) - limit {th['missing_pct_column']:.0f}%"))

    for col, cnt in summary["inconsistent_by_column"].items():
        pct = 100 * cnt / n
        if cnt and pct > th["inconsistent_pct_column"]:
            alerts.append(Alert("WARNING", f"{pct:.0f}% of '{col}' entries are inconsistent ({cnt} of {n} rows)"))

    dups = summary["duplicate_rows"]
    if dups:
        pct = 100 * dups / n
        alerts.append(Alert("CRITICAL" if pct > th["duplicate_pct"] else "WARNING",
                            f"{dups} duplicate row(s) detected ({pct:.1f}% of rows, limit {th['duplicate_pct']:.0f}%)"))

    oor = [i for i in issues if i.subtype == "out of range"]
    if oor:
        cols = sorted({i.column for i in oor})
        alerts.append(Alert("CRITICAL", f"{len(oor)} value(s) breach allowed limits in: {', '.join(cols)}"))

    anomalies = [i for i in issues if i.subtype in ("outlier", "invalid type", "invalid format")]
    if anomalies:
        alerts.append(Alert("WARNING", f"{len(anomalies)} anomalous entr{'y' if len(anomalies)==1 else 'ies'} "
                                       "(invalid types/formats or statistical outliers)"))

    score = summary["quality_score"]
    if score < th["quality_critical"]:
        alerts.append(Alert("CRITICAL", f"Data quality score {score} is below the critical limit ({th['quality_critical']:.0f})"))
    elif score < th["quality_warning"]:
        alerts.append(Alert("WARNING", f"Data quality score {score} is below the target ({th['quality_warning']:.0f})"))

    if not alerts:
        alerts.append(Alert("INFO", "All thresholds are within limits - dataset looks healthy."))
    alerts.sort(key=lambda a: _ORDER[a.level])
    return alerts

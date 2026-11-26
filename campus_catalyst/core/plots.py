"""Matplotlib charts. Figures are built separately from saving so the GUI can embed them."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except ImportError:      # graceful fallback - the rest of the app keeps working
    plt = None
    HAVE_MPL = False

from core.parsing import parse_number

PALETTE = {"missing": "#F59E0B", "duplicate": "#EF4444", "inconsistent": "#6366F1",
           "primary": "#4F46E5", "accent": "#10B981", "grid": "#E5E7EB"}


def _style(ax, title, xlabel="", ylabel=""):
    ax.set_title(title, fontsize=12, fontweight="bold", loc="left", pad=10)
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    ax.grid(axis="y", color=PALETTE["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def _empty(title, msg="No data to plot"):
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.axis("off"); ax.set_title(title, fontsize=12, fontweight="bold", loc="left")
    ax.text(0.5, 0.5, msg, ha="center", va="center", color="#6B7280", fontsize=11)
    return fig


def fig_issue_types(summary: dict):
    data = summary["by_subtype"]
    if not data:
        return _empty("Issues by type", "No issues found - clean dataset!")
    items = sorted(data.items(), key=lambda kv: kv[1])
    kind_of = {}
    fig, ax = plt.subplots(figsize=(7, max(3, 0.45 * len(items) + 1.2)))
    labels = [k for k, _ in items]
    ax.barh(labels, [v for _, v in items], color=PALETTE["inconsistent"])
    for y, (_, v) in enumerate(items):
        ax.text(v + 0.05, y, str(v), va="center", fontsize=9)
    _style(ax, "Issues by type", "Count")
    ax.grid(axis="x", color=PALETTE["grid"]); ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return fig


def fig_kind_breakdown(summary: dict):
    kinds = ["missing", "duplicate", "inconsistent"]
    vals = [summary["by_kind"].get(k, 0) for k in kinds]
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    bars = ax.bar(["Missing", "Duplicate", "Inconsistent"], vals,
                  color=[PALETTE[k] for k in kinds])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.1, str(v), ha="center", fontsize=10)
    _style(ax, "Findings by category", ylabel="Issues")
    fig.tight_layout()
    return fig


def fig_missing_by_column(summary: dict):
    data = summary["missing_by_column"]
    if not data or not any(data.values()):
        return _empty("Missing values per column", "No missing values")
    fig, ax = plt.subplots(figsize=(7, 3.8))
    cols, vals = list(data), list(data.values())
    ax.bar(cols, vals, color=PALETTE["missing"])
    for i, v in enumerate(vals):
        if v:
            ax.text(i, v + 0.05, str(v), ha="center", fontsize=9)
    _style(ax, "Missing values per column", ylabel="Missing cells")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    fig.tight_layout()
    return fig


def fig_trend(summary: dict):
    t = summary.get("trend") or {}
    if not t or not t.get("periods"):
        return _empty("Trend", "No date + numeric column available for a trend")
    fig, ax = plt.subplots(figsize=(7, 3.8))
    periods = t["periods"]
    avgs = [a if a is not None else float("nan") for a in t["averages"]]
    ax.plot(periods, avgs, marker="o", color=PALETTE["primary"], linewidth=2.2, label=f"Average {t['value_column']}")
    for p, a in zip(periods, t["averages"]):
        if a is not None:
            ax.annotate(f"{a:.1f}", (p, a), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    _style(ax, f"Average {t['value_column']} by {t['date_column'].replace('_', ' ')} year", "Year", f"Average {t['value_column']}")
    ax2 = ax.twinx()
    ax2.bar(periods, t["counts"], alpha=0.18, color=PALETTE["accent"], label="Records")
    ax2.set_ylabel("Records"); ax2.spines["top"].set_visible(False)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8, frameon=False)
    fig.tight_layout()
    return fig


def fig_distributions(columns: List[str], rows: List[dict], rules: Dict[str, dict]):
    num_cols = [c for c in columns if rules.get(c, {}).get("type") in ("int", "float")][:4]
    if not num_cols:
        return _empty("Distributions", "No numeric columns")
    fig, axes = plt.subplots(1, len(num_cols), figsize=(3.6 * len(num_cols), 3.4), squeeze=False)
    for ax, c in zip(axes[0], num_cols):
        rule = rules[c]; lo, hi = rule.get("min"), rule.get("max")
        vals = []
        for r in rows:
            n = parse_number(r.get(c, ""), allow_pct=True)
            if n is not None and not ((lo is not None and n < lo) or (hi is not None and n > hi)):
                vals.append(n)
        if vals:
            ax.hist(vals, bins=min(10, max(4, len(vals) // 3)), color=PALETTE["primary"], edgecolor="white")
        _style(ax, f"{c.replace('_', ' ').title()} (valid values)", c, "Records")
    fig.tight_layout()
    return fig


def fig_quality_history(history: List[dict]):
    if not history:
        return _empty("Data quality over time", "Run a scan to start tracking quality")
    xs = list(range(1, len(history) + 1))
    ys = [h.get("quality_score", 0) for h in history]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.plot(xs, ys, marker="o", color=PALETTE["accent"], linewidth=2.2)
    for x, y in zip(xs, ys):
        ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    ax.axhline(97, color=PALETTE["accent"], linestyle="--", linewidth=1, alpha=0.6)
    ax.axhline(90, color=PALETTE["duplicate"], linestyle="--", linewidth=1, alpha=0.6)
    ax.text(xs[-1], 97.2, " healthy", fontsize=8, color=PALETTE["accent"])
    ax.text(xs[-1], 90.2, " critical", fontsize=8, color=PALETTE["duplicate"])
    ax.set_xticks(xs if len(xs) <= 15 else xs[:: max(1, len(xs) // 10)])
    ax.set_ylim(min(80, min(ys) - 2), 101)
    _style(ax, "Data quality score across scans", "Scan #", "Quality score")
    fig.tight_layout()
    return fig


def build_all(columns, rows, rules, summary, history) -> Dict[str, object]:
    if not HAVE_MPL:
        return {}
    return {
        "issues_by_type": fig_issue_types(summary),
        "findings_by_category": fig_kind_breakdown(summary),
        "missing_by_column": fig_missing_by_column(summary),
        "trend": fig_trend(summary),
        "distributions": fig_distributions(columns, rows, rules),
        "quality_history": fig_quality_history(history),
    }


def save_all(figs: Dict[str, object], outdir, prefix: str = "") -> List[Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, fig in figs.items():
        p = outdir / f"{prefix}{name}.png"
        fig.savefig(p, dpi=150, facecolor="white")
        plt.close(fig)
        paths.append(p)
    return paths

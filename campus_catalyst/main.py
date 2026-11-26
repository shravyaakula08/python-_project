#!/usr/bin/env python3
"""Campus Catalyst - Simple Data Cleaning Assistant (terminal app).

Run:  python main.py        (GUI version:  streamlit run app_gui.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

from core import plots, ui
from core import validation as val
from core.alerts import DEFAULT_THRESHOLDS
from core.cleaner import FIX_OPTIONS
from core.importer import ImportFailure
from core.search import distinct_values, rows_with_issue_kind, search_records
from core.service import Workspace
from core.storage import StorageError

MENU = [
    ("1", "View records"),
    ("2", "Add a new record"),
    ("3", "Edit a record"),
    ("4", "Delete a record"),
    ("5", "Run data-quality scan  (missing / duplicates / inconsistent)"),
    ("6", "Search & filter records"),
    ("7", "Executive summary"),
    ("8", "Auto-clean the dataset"),
    ("9", "Generate charts (Matplotlib)"),
    ("10", "Export reports (Markdown / audit log / CSV)"),
    ("11", "Bulk import a legacy CSV"),
    ("12", "Threshold warnings"),
    ("13", "Dataset tools  (sample data, load/save file, undo)"),
    ("0", "Exit"),
]


def record_rows(ws: Workspace, items=None):
    items = items if items is not None else list(enumerate(ws.rows, 1))
    return [[n] + [r.get(c, "") for c in ws.columns] for n, r in items]


def show_records(ws: Workspace, items=None) -> None:
    ui.show_table_paged(["#"] + ws.columns, record_rows(ws, items))


def show_alerts(ws: Workspace) -> None:
    for a in ws.alerts:
        print(f"  {ui.level_tag(a.level)} {a.message}")


# --------------------------------------------------------------------------- handlers
def h_view(ws):
    ui.header(f"Records ({len(ws.rows)})")
    if not ws.rows:
        ui.info("The dataset is empty. Use option 2 to add a record or 13 to load the sample data.")
        return
    show_records(ws)


def h_add(ws):
    ui.header("Add a new record   (type /cancel at any prompt to abort)")
    rec = {}
    for col in ws.columns:
        rec[col] = val.ask_field(col, ws.rules[col], ws.rows)
    errs = ws.validate_record(rec)
    if errs:
        ui.warn("The record was accepted by the prompts but still has problems:")
        for e in errs:
            print(f"        - {e}")
        if not val.ask_yes_no("Save it anyway?", default=False):
            ui.info("Record discarded.")
            return
    row_no = ws.add_record(rec)
    ui.success(f"Record saved as row {row_no} and written to {ws.path.name}.")


def pick_row(ws, prompt="Row number") -> int:
    if not ws.rows:
        raise val.InputAborted()
    return val.ask_int(f"{prompt} (1-{len(ws.rows)})", 1, len(ws.rows))


def h_edit(ws):
    ui.header("Edit a record")
    if not ws.rows:
        ui.info("Nothing to edit - the dataset is empty.")
        return
    n = pick_row(ws)
    print("\n".join(ui.table(["#"] + ws.columns, record_rows(ws, [(n, ws.rows[n - 1])]))))
    col = val.ask_choice("Column to change", ws.columns)
    cur = ws.rows[n - 1].get(col, "")
    new = val.ask_field(col, ws.rules[col], ws.rows, current=cur)
    ws.update_record(n, col, new)
    ui.success(f"Row {n}: {col} changed from '{cur}' to '{new}'.")


def h_delete(ws):
    ui.header("Delete a record")
    if not ws.rows:
        ui.info("Nothing to delete - the dataset is empty.")
        return
    n = pick_row(ws)
    print("\n".join(ui.table(["#"] + ws.columns, record_rows(ws, [(n, ws.rows[n - 1])]))))
    if val.ask_yes_no(f"Delete row {n}?", default=False):
        ws.delete_record(n)
        ui.success("Record deleted (option 13 -> undo can restore it).")
    else:
        ui.info("Cancelled.")


def h_scan(ws):
    ui.header("Data-quality scan")
    ws.scan(log_history=True)
    s = ws.summary
    if not ws.rows:
        ui.info("Dataset is empty - nothing to scan.")
        return
    print(f"  Records scanned : {s['rows']}   Cells: {s['cells']}")
    print(f"  Missing values  : {ui.c(s['missing_cells'], 'yellow', 'bold')}")
    print(f"  Duplicate rows  : {ui.c(s['duplicate_rows'], 'red', 'bold')}   "
          f"(+{s['by_subtype'].get('duplicate key', 0)} duplicate key(s))")
    print(f"  Inconsistent    : {ui.c(s['inconsistent_cells'], 'magenta', 'bold')} cell(s)")
    print(f"  Quality score   : {s['quality_score']} / 100 {ui.status_badge(s['status'])}")
    if not ws.issues:
        ui.success("No issues found - the dataset is clean.")
        return
    print()
    choice = val.ask_choice("Show which findings?", ["All", "Missing values", "Duplicates", "Inconsistent", "Skip"])
    kind = {"All": None, "Missing values": "missing", "Duplicates": "duplicate", "Inconsistent": "inconsistent"}.get(choice, "skip")
    if kind != "skip":
        sel = [i for i in ws.issues if kind is None or i.kind == kind]
        rows = [[i.row, i.column, f"{i.kind}/{i.subtype}", i.severity.upper(), i.message, i.suggestion] for i in sel]
        ui.show_table_paged(["Row", "Column", "Type", "Sev", "Problem", "Suggested fix"], rows, max_col=52)
    print()
    show_alerts(ws)
    ui.info("Use option 8 to apply automatic fixes.")


def h_search(ws):
    ui.header("Search & filter   (press Enter to skip any filter)")
    if not ws.rows:
        ui.info("The dataset is empty.")
        return
    kw = val.ask_str("Keyword (any column)", required=False)
    filters, ranges = {}, {}
    cat_cols = [c for c in ws.columns if ws.rules[c].get("type") == "category"]
    if cat_cols:
        pick = val.ask_choice("Filter by category column", ["(skip)"] + cat_cols)
        if pick != "(skip)":
            vals = distinct_values(ws.rows, pick)
            print(ui.c("    values: " + ", ".join(vals), "grey"))
            v = val.ask_str(f"{pick} equals", required=False)
            if v:
                filters[pick] = v
    num_cols = [c for c in ws.columns if ws.rules[c].get("type") in ("int", "float")]
    if num_cols:
        pick = val.ask_choice("Filter by numeric range", ["(skip)"] + num_cols)
        if pick != "(skip)":
            lo = val.ask_number(f"{pick} minimum (Enter = no limit)", required=False)
            hi = val.ask_number(f"{pick} maximum (Enter = no limit)", required=False)
            ranges[pick] = (float(lo) if lo else None, float(hi) if hi else None)
    issue_rows = None
    kind = val.ask_choice("Only rows with", ["Any rows", "Missing values", "Duplicates", "Inconsistent entries"])
    if kind != "Any rows":
        k = {"Missing values": "missing", "Duplicates": "duplicate", "Inconsistent entries": "inconsistent"}[kind]
        issue_rows = rows_with_issue_kind(ws.issues, k)
    found = search_records(ws.rows, ws.columns, kw, filters, ranges, issue_rows)
    print()
    if not found:
        ui.warn("No records match those filters.")
        return
    ui.success(f"{len(found)} record(s) found.")
    show_records(ws, found)


def _bar_line(label, pct):
    return f"  {label:<14}{ui.c(ui.bar(pct), 'cyan')} {pct:5.1f}%"


def h_summary(ws):
    ui.header("Executive summary")
    ws.scan(log_history=False)
    s = ws.summary
    if not ws.rows:
        ui.info("Dataset is empty.")
        return
    print(f"  Records: {s['rows']}   Columns: {s['columns']}   Clean rows: {s['clean_rows']} ({s['clean_rows_pct']}%)")
    print(f"  Overall quality score: {ui.c(s['quality_score'], 'bold')} / 100  {ui.status_badge(s['status'])}\n")
    print(_bar_line("Completeness", s["completeness"]))
    print(_bar_line("Validity", s["validity"]))
    print(_bar_line("Uniqueness", s["uniqueness"]))
    print(f"\n  Findings: {s['missing_cells']} missing | {s['duplicate_rows']} duplicate rows | "
          f"{s['inconsistent_cells']} inconsistent cells | {s['total_issues']} total issues")
    if s["numeric"]:
        print(ui.c("\n  Numeric columns (valid values only)", "bold"))
        rows = [[c, st["count"], f"{st['mean']:.2f}", f"{st['median']:.2f}", f"{st['min']:g}", f"{st['max']:g}", f"{st['stdev']:.2f}"]
                for c, st in s["numeric"].items()]
        print("\n".join(ui.table(["Column", "Count", "Mean", "Median", "Min", "Max", "StdDev"], rows)))
    for col, items in s["categories"].items():
        print(ui.c(f"\n  Distribution: {col}", "bold"))
        print("\n".join(ui.table([col, "Records"], [[k, v] for k, v in items])))
    t = s.get("trend") or {}
    if t.get("periods"):
        print(ui.c(f"\n  Trend: average {t['value_column']} by {t['date_column']} year", "bold"))
        rows = [[p, n, "-" if a is None else a] for p, n, a in zip(t["periods"], t["counts"], t["averages"])]
        print("\n".join(ui.table(["Year", "Records", f"Avg {t['value_column']}"], rows)))
    print()
    show_alerts(ws)


def h_clean(ws):
    ui.header("Auto-clean")
    if not ws.rows:
        ui.info("Dataset is empty.")
        return
    keys = list(FIX_OPTIONS)
    for i, k in enumerate(keys, 1):
        print(f"    {ui.c(str(i), 'cyan', 'bold')}. {FIX_OPTIONS[k]}")
    mode = val.ask_choice("Apply", ["All fixes", "Let me choose", "Cancel"])
    if mode == "Cancel":
        ui.info("Cancelled.")
        return
    chosen = set(keys) if mode == "All fixes" else {k for k in keys if val.ask_yes_no(FIX_OPTIONS[k] + "?", default=True)}
    if not chosen:
        ui.info("No fixes selected.")
        return
    log = ws.clean(chosen)
    ui.success("Cleaning finished:")
    for line in log:
        print(f"        - {line}")
    left = [i for i in ws.issues]
    if left:
        ui.warn(f"{len(left)} issue(s) still need a manual decision (e.g. out-of-range values, "
                "invalid emails, missing names). Run option 5 to review them, 3 to edit, or 13 -> undo.")
    else:
        ui.success("The dataset is now clean.")


def h_charts(ws):
    ui.header("Charts")
    if not plots.HAVE_MPL:
        ui.error("Matplotlib is not installed. Run:  pip install matplotlib")
        return
    ws.scan(log_history=False)
    paths = ws.save_charts()
    ui.success(f"{len(paths)} charts saved:")
    for p in paths:
        print(f"        {p}")
    ui.info("Open the PNG files to view them (issue types, missing values, trend, distributions, quality history).")


def h_export(ws):
    ui.header("Export reports")
    ws.scan(log_history=False)
    choice = val.ask_choice("Format", ["Markdown report", "Plain-text audit log", "CSV issue report", "All three"])
    fm = {"Markdown report": ("md",), "Plain-text audit log": ("txt",), "CSV issue report": ("csv",),
          "All three": ("md", "txt", "csv")}[choice]
    paths = ws.export(fm)
    ui.success("Exported:")
    for p in paths:
        print(f"        {p}")


def h_import(ws):
    ui.header("Bulk import (legacy CSV)")
    raw = val.ask_str("Path to CSV file").strip('"').strip("'")
    strict = val.ask_yes_no("Strict mode - reject rows that have field errors?", default=False)
    try:
        res = ws.import_csv(Path(raw).expanduser(), strict=strict)
    except ImportFailure as exc:
        ui.error(f"Import failed: {exc}")
        return
    except (OSError, StorageError) as exc:
        ui.error(f"Could not read file: {exc}")
        return
    print(f"\n  Mapped columns: " + ", ".join(f"{k} -> {v}" for k, v in res.columns_mapped.items()))
    print(f"  Rows read {res.total} | accepted {res.accepted} (with warnings: {res.warned}) | "
          f"rejected {res.rejected} | blank lines {res.skipped}")
    print(ui.c(f"\n  Row-by-row log (full copy: {res.log_path})", "bold"))
    body = res.log[4:]
    for line in body[:15]:
        print("   ", ui.c(line, "red") if "REJECTED" in line else ui.c(line, "yellow") if "WARN" in line else line)
    if len(body) > 15:
        print(ui.c(f"    ... {len(body) - 15} more line(s) in the log file", "grey"))
    if res.rows and val.ask_yes_no(f"Add the {res.accepted} accepted row(s) to the dataset?", default=True):
        ws.merge_rows(res.rows)
        ui.success(f"Dataset now has {len(ws.rows)} rows. Run option 5 to scan them.")


def h_thresholds(ws):
    ui.header("Threshold warnings")
    ws.scan(log_history=False)
    show_alerts(ws)
    print(ui.c("\n  Current limits", "bold"))
    names = {"missing_pct_column": "Max % missing per column", "inconsistent_pct_column": "Max % inconsistent per column",
             "duplicate_pct": "Max % duplicate rows", "quality_warning": "Quality score warning below",
             "quality_critical": "Quality score critical below"}
    print("\n".join(ui.table(["Limit", "Value"], [[names[k], ws.thresholds[k]] for k in names])))
    if val.ask_yes_no("Change a limit?", default=False):
        key_label = val.ask_choice("Which one", list(names.values()))
        key = next(k for k, v in names.items() if v == key_label)
        ws.thresholds[key] = float(val.ask_number("New value (0-100)", lo=0, hi=100))
        ws.scan(log_history=False)
        ui.success("Limit updated.")
        show_alerts(ws)


def h_dataset(ws):
    ui.header("Dataset tools")
    choice = val.ask_choice("Action", ["Load the 40-row sample dataset", "Load another CSV/JSON file",
                                       "Save a copy as CSV/JSON", "Undo last change", "Start with an empty dataset", "Back"])
    if choice == "Back":
        return
    if choice.startswith("Load the"):
        if val.ask_yes_no("This replaces the current records. Continue?", default=False):
            ws.load_sample()
            ui.success(f"Sample dataset loaded ({len(ws.rows)} rows).")
    elif choice.startswith("Load another"):
        raw = val.ask_str("Path to .csv or .json file").strip('"').strip("'")
        try:
            n = ws.load_file(Path(raw).expanduser())
            ui.success(f"Loaded {n} rows from {raw}.")
        except FileNotFoundError:
            ui.error("File not found.")
        except Exception as exc:
            ui.error(f"Could not load file: {exc}")
    elif choice.startswith("Save a copy"):
        raw = val.ask_str("Output path (.csv or .json)", regex=r"(?i).+\.(csv|json)$", hint="must end in .csv or .json")
        ui.success(f"Saved to {ws.save_copy(Path(raw).expanduser())}")
    elif choice.startswith("Undo"):
        ui.success("Last change undone.") if ws.undo() else ui.info("Nothing to undo.")
    elif choice.startswith("Start with"):
        if val.ask_yes_no("Remove ALL records?", default=False):
            ws.reset_empty()
            ui.success("Dataset cleared.")


HANDLERS = {"1": h_view, "2": h_add, "3": h_edit, "4": h_delete, "5": h_scan, "6": h_search, "7": h_summary,
            "8": h_clean, "9": h_charts, "10": h_export, "11": h_import, "12": h_thresholds, "13": h_dataset}


def print_menu(ws: Workspace) -> None:
    print()
    s = ws.summary
    state = f"{len(ws.rows)} records | quality {s.get('quality_score', '-')} {s.get('status', '')}"
    print(ui.c(f"  {state}", "grey"))
    for key, label in MENU:
        print(f"  {ui.c(key.rjust(2), 'cyan', 'bold')}  {label}")


def main() -> int:
    ui.banner()
    ws = Workspace()
    for note in ws.notes:
        ui.warn(note)
    ui.info(f"Data auto-saves to data/{ws.path.name} - it will be here next time you launch.")
    while True:
        print_menu(ws)
        try:
            choice = val.ask_menu_choice([k for k, _ in MENU])
        except val.InputAborted:
            choice = "0"
        except KeyboardInterrupt:
            choice = "0"
        if choice == "0":
            ws.save()
            ui.success("Data saved. Goodbye!")
            return 0
        try:
            HANDLERS[choice](ws)
        except val.InputAborted:
            print()
            ui.info("Cancelled - back to the menu.")
        except KeyboardInterrupt:
            print()
            ui.info("Interrupted - back to the menu.")
        except Exception as exc:          # last line of defence: never crash the demo
            ui.error(f"Unexpected problem: {exc}. Your data is safe; returning to the menu.")
        if choice in ("1", "5", "6", "7", "9", "10", "12"):
            try:
                ui.pause()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    sys.exit(main())

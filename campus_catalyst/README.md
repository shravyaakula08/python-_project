# Campus Catalyst - Simple Data Cleaning Assistant (Project #98)

A beginner-friendly Python application that **finds missing values, duplicate rows and
inconsistent entries** in a small dataset, fixes them, and reports on the result.
It ships with two front ends that share one engine:

| Front end | Command |
|---|---|
| Terminal menu app (ANSI colours, branded screen) | `python main.py` |
| Modern Streamlit web GUI | `streamlit run app_gui.py` |

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # terminal app only needs: pip install matplotlib
python main.py
```
Python 3.10+ is required. On the very first launch the app seeds itself with the 40-row sample
dataset (`data/sample_data.csv` / `.json`), so there is something to demo straight away.

## Feature checklist (from the brief)

**Must-have**

| Requirement | Where it lives |
|---|---|
| Interactive terminal interface | `main.py` - 13-option menu, branded banner, paginated tables (`core/ui.py`) |
| Defensive input validation | `core/validation.py` - every prompt loops until valid: type, range, blank, regex, date, unique ID, `/cancel` to abort, EOF/Ctrl-C safe |
| Core logic engine | `core/cleaner.py` - missing / duplicate / inconsistent detection plus 7 automatic fixes |
| Local persistence (CSV/JSON) | `core/storage.py` - autosave after every change, atomic writes, corrupt/missing file recovery |
| Record query & search | `core/search.py` - keyword + category + numeric range + "rows with issue type" filters (menu 6) |
| Executive summary | `core/summary.py` - totals, averages/median/stdev, status indicator, distributions, trend (menu 7) |
| Visual data plotting | `core/plots.py` - 6 Matplotlib charts saved as PNG (menu 9) |

**Stretch**

| Requirement | Where it lives |
|---|---|
| Multi-format export | `core/exporter.py` - Markdown report, plain-text audit log, CSV issue report (menu 10) |
| Threshold warning indicators | `core/alerts.py` - CRITICAL / WARNING / INFO flags with editable limits (menu 12) |
| Modern GUI | `app_gui.py` - Streamlit: dashboard cards, search, add/edit forms, fix preview, charts, import, export |
| Bulk dataset import | `core/importer.py` - header mapping, structural validation, row-by-row `reports/import_errors.log` (menu 11) |

## What counts as a problem?

* **Missing** - blank cells and placeholders (`N/A`, `null`, `-`, `?`...).
* **Duplicate** - exact duplicate rows (ignoring the ID column) and duplicate keys (same ID or same email on different rows).
* **Inconsistent** - spelling variants (`comp sci`, `CS` -> *Computer Science*, typos like `Mechancial`),
  mixed date formats, impossible or future dates, wrong types (`twenty`, `92%`), out-of-range values
  (age 150, marks 105, attendance 101), invalid emails, casing problems, stray whitespace, and
  statistical outliers for columns that have no fixed range.

Boundary values (age 16 and 60, marks 0 and 100) are valid and are deliberately **not** flagged.

The **quality score** is `40% completeness + 40% validity + 20% uniqueness`.
Status: **Healthy** >= 97, **Needs Attention** >= 90, **Critical** < 90.
Dates are read day-first (`15/08/2022` = 15 Aug) before month-first.

## Five-minute demo script

1. `python main.py` - branded welcome screen, sample data auto-loaded.
2. **Option 2 (Add record)** - type bad values on purpose: `abc` for age, `200`, a future date, `rohit@`,
   an unknown department. Each is rejected with a clear message until valid.
3. **Option 5 (Scan)** - missing values, duplicates and inconsistent entries appear in tables, followed by threshold warnings.
4. **Option 6 (Search)** - e.g. department = Civil, marks 80-100, "rows with duplicates".
5. **Option 8 (Auto-clean)** - quality score jumps (96.1 -> 98.6 on the sample); remaining items need a human decision.
6. **Option 7 (Summary)** and **option 9 (Charts)** - tables, status badge, PNG charts in `reports/charts/`.
7. **Option 0 (Exit)**, relaunch, and show the records and score are still there (persistence).
8. **Option 10 (Export)** - Markdown, audit log and CSV in `reports/`. Optionally **option 11** with `data/legacy_import_demo.csv`.
9. Finish with `streamlit run app_gui.py` for the modern GUI.

## Project layout

```
main.py              terminal app            app_gui.py        Streamlit GUI
core/
  parsing.py         missing tokens, numbers, dates
  schema.py          column rules (student schema + auto-inference for any CSV/JSON)
  cleaner.py         detection + fixes      validation.py     input wrappers
  storage.py         CSV/JSON persistence   service.py        Workspace shared by both UIs
  search.py  summary.py  alerts.py  plots.py  exporter.py  importer.py  ui.py  models.py
data/                sample_data.csv/.json, legacy_import_demo.csv (runtime: working_data.json, history.json)
reports/             exports, charts, import_errors.log
tests/test_core.py   21 unit tests
```

## Using your own data

Menu 13 -> *Load another CSV/JSON file* (or Settings in the GUI). Unknown columns get rules
inferred automatically (numbers, dates, emails, categories, IDs), so detection works on any small table.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Troubleshooting

* *Charts say Matplotlib is missing* - `pip install matplotlib`.
* *Garbled colours on an old Windows console* - set `NO_COLOR=1` or use Windows Terminal.
* *Start over* - delete `data/working_data.json` and `data/history.json`, or use menu 13.

"""Local persistence: CSV/JSON read & write with schema checks and corrupt-file recovery."""
from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from core.schema import STUDENT_COLUMNS

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
WORKING_FILE = DATA_DIR / "working_data.json"
SAMPLE_CSV = DATA_DIR / "sample_data.csv"
SAMPLE_JSON = DATA_DIR / "sample_data.json"
HISTORY_FILE = DATA_DIR / "history.json"


class StorageError(Exception):
    """Raised when a data file has an unusable structure."""


def _s(v) -> str:
    return "" if v is None else str(v)


# --------------------------------------------------------------------------- readers
def read_csv(path) -> Tuple[List[str], List[Dict[str, str]]]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    if not text.strip():
        raise StorageError(f"{path.name} is empty")
    reader = csv.DictReader(text.splitlines(), skipinitialspace=False)
    cols = [c for c in (reader.fieldnames or []) if c is not None]
    if not cols:
        raise StorageError(f"{path.name} has no header row")
    rows = []
    for rec in reader:
        rows.append({c: _s(rec.get(c)) for c in cols})
    return cols, rows


def read_json(path) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)          # may raise json.JSONDecodeError
    cols = None
    if isinstance(data, dict):
        cols = data.get("columns")
        data = data.get("records")
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise StorageError("JSON must be a list of objects or {'columns': [...], 'records': [...]}")
    if not cols:
        cols = []
        for r in data:
            for k in r:
                if k not in cols:
                    cols.append(k)
    if not cols:
        raise StorageError("JSON file has no columns")
    return list(cols), [{c: _s(r.get(c)) for c in cols} for r in data]


def load_dataset(path) -> Tuple[List[str], List[Dict[str, str]]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    ext = path.suffix.lower()
    if ext == ".csv":
        return read_csv(path)
    if ext == ".json":
        return read_json(path)
    raise StorageError(f"Unsupported file type '{ext}' (use .csv or .json)")


# --------------------------------------------------------------------------- writers
def save_dataset(path, columns: List[str], rows: List[Dict[str, str]]) -> Path:
    """Atomically write CSV or JSON depending on the extension."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if path.suffix.lower() == ".csv":
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: _s(r.get(c)) for c in columns})
    else:
        payload = {"columns": columns, "saved_at": datetime.now().isoformat(timespec="seconds"),
                   "records": [{c: _s(r.get(c)) for c in columns} for r in rows]}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


# --------------------------------------------------------------------------- startup loading
def load_working(path=None) -> Tuple[List[str], List[Dict[str, str]], List[str]]:
    """Load the autosaved dataset; recover gracefully from missing or corrupt files."""
    path = Path(path or WORKING_FILE)
    notes: List[str] = []
    try:
        cols, rows = load_dataset(path)
        return cols, rows, notes
    except FileNotFoundError:
        try:
            cols, rows = load_dataset(SAMPLE_CSV)
            notes.append(f"First run: no saved data found, loaded the {len(rows)}-row sample dataset.")
        except Exception:
            cols, rows = list(STUDENT_COLUMNS), []
            notes.append("First run: created an empty dataset template.")
    except (StorageError, ValueError, OSError, csv.Error) as exc:   # JSONDecodeError is a ValueError
        backup = path.with_name(path.name + f".corrupt-{datetime.now():%Y%m%d-%H%M%S}")
        try:
            shutil.copy2(path, backup)
            notes.append(f"Saved data was unreadable ({exc}). A backup was kept as {backup.name}.")
        except OSError:
            notes.append(f"Saved data was unreadable ({exc}).")
        cols, rows = list(STUDENT_COLUMNS), []
        notes.append("Started with a clean empty template.")
    save_dataset(path, cols, rows)
    return cols, rows, notes


# --------------------------------------------------------------------------- history
def load_history(path=None) -> List[dict]:
    path = Path(path or HISTORY_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def append_history(entry: dict, path=None, keep: int = 200) -> None:
    path = Path(path or HISTORY_FILE)
    hist = load_history(path)
    probe = {k: v for k, v in entry.items() if k != "timestamp"}
    if hist and {k: v for k, v in hist[-1].items() if k != "timestamp"} == probe:
        return
    hist.append(entry)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(hist[-keep:], f, indent=2)
    except OSError:
        pass

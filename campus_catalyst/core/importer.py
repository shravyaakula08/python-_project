"""Bulk dataset import: header mapping, structural validation and a row-by-row error log."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.cleaner import check_row
from core.models import ImportResult
from core.schema import match_header


class ImportFailure(Exception):
    """The file cannot be imported at all (missing, wrong type, no usable header...)."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def import_csv(path, columns: List[str], rules: Dict[str, dict], strict: bool = False,
               log_path=None) -> ImportResult:
    """Read a legacy CSV. Structurally broken rows are rejected; field-level problems are
    logged as warnings (or rejected too when strict=True). Dirty-but-parseable rows are kept
    so the cleaning engine can deal with them."""
    path = Path(path)
    if not path.exists():
        raise ImportFailure(f"File not found: {path}")
    if path.suffix.lower() != ".csv":
        raise ImportFailure(f"Only .csv files can be bulk-imported (got '{path.suffix or 'no extension'}')")
    try:
        text = _read_text(path)
    except OSError as exc:
        raise ImportFailure(f"Cannot read file: {exc}")
    if not text.strip():
        raise ImportFailure("File is empty")

    reader = csv.reader(io.StringIO(text))
    res = ImportResult(source=path.name)
    header = None
    for raw in reader:
        if any(c.strip() for c in raw):
            header = [h.strip() for h in raw]
            break
    if not header:
        raise ImportFailure("No header row found")

    mapping: Dict[int, str] = {}
    for idx, h in enumerate(header):
        col = match_header(h, columns)
        if col is None:
            res.log.append(f"Header '{h}': no matching column - ignored")
        elif col in mapping.values():
            res.log.append(f"Header '{h}': duplicate of '{col}' - ignored")
        else:
            mapping[idx] = col
            res.columns_mapped[h] = col
    if not mapping:
        raise ImportFailure("None of the file's headers match this dataset's columns "
                            f"({', '.join(columns)})")
    absent = [c for c in columns if c not in mapping.values()]
    for col in absent:
        res.log.append(f"Column '{col}' not found in file - values left blank")

    for raw in reader:
        line = reader.line_num
        if not any(c.strip() for c in raw):
            res.skipped += 1
            res.log.append(f"Line {line}: SKIPPED - blank line")
            continue
        res.total += 1
        if len(raw) != len(header):
            res.rejected += 1
            res.log.append(f"Line {line}: REJECTED - expected {len(header)} fields, found {len(raw)}")
            continue
        rec = {c: "" for c in columns}
        for idx, col in mapping.items():
            rec[col] = raw[idx]
        problems = check_row(rec, columns, rules, skip=absent)
        if problems and strict:
            res.rejected += 1
            res.log.append(f"Line {line}: REJECTED - " + "; ".join(problems))
            continue
        if problems:
            res.warned += 1
            res.log.append(f"Line {line}: IMPORTED WITH WARNINGS - " + "; ".join(problems))
        res.accepted += 1
        res.rows.append(rec)

    summary = [f"Import log for {path.name} - {datetime.now():%Y-%m-%d %H:%M:%S}",
               f"Mode: {'strict (reject rows with field errors)' if strict else 'lenient (warn on field errors)'}",
               f"Data rows read: {res.total} | accepted: {res.accepted} "
               f"(of which {res.warned} with warnings) | rejected: {res.rejected} | blank lines skipped: {res.skipped}",
               "-" * 70]
    out = Path(log_path) if log_path else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(summary + res.log) + "\n", encoding="utf-8")
        res.log_path = str(out)
    res.log = summary + res.log
    return res

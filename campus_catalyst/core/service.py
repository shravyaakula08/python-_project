"""Workspace: one object that ties storage, cleaning, summary, alerts, plots and export together.
Both the terminal app and the Streamlit GUI drive this class, so behaviour is identical."""
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from core import alerts as alerts_mod
from core import cleaner, exporter, importer, plots, schema, storage, summary as summary_mod
from core.models import Alert, ImportResult, Issue
from core.schema import STUDENT_COLUMNS


class Workspace:
    def __init__(self, path=None, history_path=None, reports_dir=None):
        self.path = Path(path or storage.WORKING_FILE)
        self.history_path = Path(history_path or storage.HISTORY_FILE)
        self.reports_dir = Path(reports_dir or storage.REPORTS_DIR)
        self.thresholds: Dict[str, float] = dict(alerts_mod.DEFAULT_THRESHOLDS)
        self.undo_stack: List[tuple] = []
        self.source_label = "working dataset"
        self.columns: List[str] = []
        self.rows: List[Dict[str, str]] = []
        self.rules: Dict[str, dict] = {}
        self.issues: List[Issue] = []
        self.summary: dict = {}
        self.alerts: List[Alert] = []
        self.notes: List[str] = []
        self.load()

    # ------------------------------------------------------------------ persistence
    def load(self) -> None:
        self.columns, self.rows, self.notes = storage.load_working(self.path)
        self.refresh_rules()
        self.scan(log_history=False)

    def save(self) -> None:
        storage.save_dataset(self.path, self.columns, self.rows)

    def refresh_rules(self) -> None:
        self.rules = schema.rules_for(self.columns, self.rows)

    # ------------------------------------------------------------------ analysis
    def scan(self, log_history: bool = True) -> List[Issue]:
        self.issues = cleaner.analyze(self.columns, self.rows, self.rules)
        self.summary = summary_mod.compute_summary(self.columns, self.rows, self.issues, self.rules)
        self.alerts = alerts_mod.generate_alerts(self.summary, self.issues, self.thresholds)
        if log_history and self.rows:
            s = self.summary
            storage.append_history({
                "timestamp": datetime.now().isoformat(timespec="seconds"), "rows": s["rows"],
                "quality_score": s["quality_score"], "issues": s["total_issues"],
                "missing": s["missing_cells"], "duplicates": s["duplicate_rows"],
                "inconsistent": s["inconsistent_cells"]}, self.history_path)
        return self.issues

    def history(self) -> List[dict]:
        return storage.load_history(self.history_path)

    # ------------------------------------------------------------------ editing
    def _snapshot(self) -> None:
        self.undo_stack.append((list(self.columns), copy.deepcopy(self.rows)))
        del self.undo_stack[:-10]

    def _changed(self) -> None:
        self.refresh_rules()
        self.save()
        self.scan(log_history=False)

    def validate_record(self, rec: dict, ignore_row: Optional[int] = None) -> List[str]:
        errs = cleaner.check_row(rec, self.columns, self.rules)
        for col in self.columns:
            if self.rules.get(col, {}).get("type") == "id" and str(rec.get(col, "")).strip():
                for i, r in enumerate(self.rows, 1):
                    if i != ignore_row and str(r.get(col, "")).strip().lower() == str(rec[col]).strip().lower():
                        errs.append(f"{col}: '{rec[col]}' already exists in row {i}")
                        break
        return errs

    def add_record(self, rec: dict) -> int:
        self._snapshot()
        self.rows.append({c: str(rec.get(c, "")).strip() for c in self.columns})
        self._changed()
        return len(self.rows)

    def update_record(self, row_no: int, col: str, value: str) -> None:
        self._snapshot()
        self.rows[row_no - 1][col] = value
        self._changed()

    def replace_rows(self, new_rows: List[dict]) -> None:
        """Replace the whole table (used by the GUI data editor)."""
        self._snapshot()
        self.rows = [{c: ("" if r.get(c) is None else str(r.get(c))) for c in self.columns} for r in new_rows]
        self._changed()

    def delete_record(self, row_no: int) -> dict:
        self._snapshot()
        gone = self.rows.pop(row_no - 1)
        self._changed()
        return gone

    def clean(self, options: Set[str]) -> List[str]:
        self._snapshot()
        before = self.summary.get("quality_score")
        self.rows, log = cleaner.apply_fixes(self.columns, self.rows, self.rules, set(options))
        self._changed()
        self.scan(log_history=True)
        log.append(f"Quality score: {before} -> {self.summary['quality_score']}")
        return log

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.columns, self.rows = self.undo_stack.pop()
        self._changed()
        return True

    # ------------------------------------------------------------------ datasets
    def load_sample(self) -> None:
        cols, rows = storage.load_dataset(storage.SAMPLE_CSV)
        self._snapshot()
        self.columns, self.rows = cols, rows
        self._changed()
        self.scan(log_history=True)

    def load_file(self, path) -> int:
        cols, rows = storage.load_dataset(path)
        self._snapshot()
        self.columns, self.rows = cols, rows
        self.source_label = Path(path).name
        self._changed()
        self.scan(log_history=True)
        return len(rows)

    def reset_empty(self) -> None:
        self._snapshot()
        self.columns, self.rows = list(STUDENT_COLUMNS), []
        self._changed()

    def save_copy(self, path) -> Path:
        return storage.save_dataset(path, self.columns, self.rows)

    def import_csv(self, path, strict: bool = False) -> ImportResult:
        log = self.reports_dir / "import_errors.log"
        return importer.import_csv(path, self.columns, self.rules, strict=strict, log_path=log)

    def merge_rows(self, new_rows: List[dict]) -> None:
        self._snapshot()
        self.rows.extend(new_rows)
        self._changed()
        self.scan(log_history=True)

    # ------------------------------------------------------------------ output
    def charts(self) -> Dict[str, object]:
        return plots.build_all(self.columns, self.rows, self.rules, self.summary, self.history())

    def save_charts(self) -> List[Path]:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        outdir = self.reports_dir / "charts"
        return plots.save_all(self.charts(), outdir, prefix=f"{stamp}_")

    def export(self, formats=("md", "txt", "csv")) -> List[Path]:
        return exporter.export_reports(self.reports_dir, self.summary, self.issues, self.alerts,
                                       formats, self.source_label)

    def markdown(self) -> str:
        return exporter.markdown_report(self.summary, self.issues, self.alerts, self.source_label)

    def audit_log(self) -> str:
        return exporter.audit_log_text(self.summary, self.issues, self.alerts, self.source_label)

    def issues_csv(self) -> str:
        return exporter.issues_csv_text(self.issues)

"""Data structures shared by the terminal app, the Streamlit GUI and the tests."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List


@dataclass
class Issue:
    """One problem found in the dataset."""
    kind: str          # "missing" | "duplicate" | "inconsistent"
    subtype: str       # e.g. "blank", "exact duplicate", "out of range"
    row: int           # 1-based row number
    column: str
    value: str
    message: str
    suggestion: str = ""
    severity: str = "medium"   # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Alert:
    """A threshold warning flag."""
    level: str         # "CRITICAL" | "WARNING" | "INFO"
    message: str


@dataclass
class ImportResult:
    """Outcome of a bulk CSV import."""
    source: str
    columns_mapped: Dict[str, str] = field(default_factory=dict)
    rows: List[Dict[str, str]] = field(default_factory=list)
    log: List[str] = field(default_factory=list)
    total: int = 0
    accepted: int = 0
    warned: int = 0
    rejected: int = 0
    skipped: int = 0
    log_path: str = ""

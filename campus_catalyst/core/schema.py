"""Column rules: the default student-records schema plus automatic inference for any CSV/JSON."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Dict, List, Optional

from core.parsing import is_missing, norm_key, parse_date, parse_number

STUDENT_COLUMNS = [
    "student_id", "name", "department", "age", "marks",
    "attendance", "enrollment_date", "email",
]

DEPARTMENT_ALIASES = {
    "Computer Science": ["cs", "cse", "comp sci", "comp science", "computer sci", "compsci"],
    "Electronics": ["ece", "electronic", "electronics and communication"],
    "Mechanical": ["mech", "mechanical engineering"],
    "Civil": ["civil engineering"],
    "Biotechnology": ["biotech", "bio tech", "bio-technology"],
}

EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

DEFAULT_RULES: Dict[str, dict] = {
    "student_id": {"type": "id", "required": True, "regex": r"^S\d{3,4}$",
                   "hint": "format S001"},
    "name": {"type": "text", "required": True, "title_case": True,
             "regex": r"^[A-Za-z][A-Za-z .'-]{1,59}$", "hint": "letters only"},
    "department": {"type": "category", "required": True, "aliases": DEPARTMENT_ALIASES},
    "age": {"type": "int", "min": 16, "max": 60},
    "marks": {"type": "float", "min": 0, "max": 100},
    "attendance": {"type": "float", "min": 0, "max": 100},
    "enrollment_date": {"type": "date"},
    "email": {"type": "email"},
}

HEADER_ALIASES = {
    "id": "student_id", "studentid": "student_id", "roll_no": "student_id", "roll_number": "student_id",
    "student_name": "name", "full_name": "name",
    "dept": "department", "branch": "department",
    "score": "marks", "grade": "marks",
    "attendance_pct": "attendance", "attendance_percent": "attendance",
    "enrolled_on": "enrollment_date", "enrollment": "enrollment_date",
    "date_of_enrollment": "enrollment_date", "enrolment_date": "enrollment_date",
    "e_mail": "email", "email_id": "email", "mail": "email",
}


def normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h).strip().lower()).strip("_")


def match_header(header: str, columns: List[str]) -> Optional[str]:
    """Map a file header onto one of the dataset's columns (or None)."""
    if header in columns:
        return header
    n = normalize_header(header)
    for c in columns:
        if normalize_header(c) == n:
            return c
    alias = HEADER_ALIASES.get(n)
    if alias and alias in columns:
        return alias
    return None


def infer_rule(col: str, values: List[str]) -> dict:
    """Guess a rule for an unknown column from its values."""
    name = col.lower()
    vals = [str(v) for v in values if not is_missing(v)]
    if "email" in name or name.endswith("mail"):
        return {"type": "email"}
    if name == "id" or name.endswith("_id"):
        return {"type": "id", "required": True}
    if not vals:
        return {"type": "text"}
    n = len(vals)
    nums = [parse_number(v) for v in vals]
    if sum(x is not None for x in nums) / n >= 0.8:
        is_int = all(x is None or x == int(x) for x in nums) and all("." not in v for v in vals)
        return {"type": "int" if is_int else "float"}
    if sum(parse_date(v)[0] is not None for v in vals) / n >= 0.8:
        return {"type": "date"}
    distinct = len({norm_key(v) for v in vals})
    if n >= 6 and distinct <= max(6, 0.25 * n):
        return {"type": "category"}
    return {"type": "text"}


def rules_for(columns: List[str], rows: List[dict]) -> Dict[str, dict]:
    """Known rules for the student schema, inferred rules for everything else."""
    rules: Dict[str, dict] = {}
    for c in columns:
        if c in DEFAULT_RULES:
            rules[c] = deepcopy(DEFAULT_RULES[c])
        else:
            rules[c] = infer_rule(c, [r.get(c, "") for r in rows])
    return rules

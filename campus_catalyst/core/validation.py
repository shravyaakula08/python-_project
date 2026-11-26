"""Defensive input wrappers: every prompt loops until the value is valid (never crashes)."""
from __future__ import annotations

import re
from typing import Callable, Iterable, List, Optional

from core import ui
from core.cleaner import category_map
from core.parsing import clean_text, fmt_number, is_missing, norm_key, parse_date, parse_number
from core.schema import EMAIL_REGEX

CANCEL = "/cancel"


class InputAborted(Exception):
    """The user typed /cancel or input ended (EOF)."""


def _read(prompt: str, input_fn: Callable) -> str:
    try:
        raw = input_fn(prompt)
    except EOFError:
        raise InputAborted()
    raw = "" if raw is None else str(raw)
    if raw.strip().lower() == CANCEL:
        raise InputAborted()
    return raw


def _bad(msg: str, out: Callable = None) -> None:
    (out or ui.error)(msg)


def ask_str(prompt: str, *, required: bool = True, regex: Optional[str] = None, max_len: int = 80,
            hint: str = "", input_fn: Callable = input, out: Callable = None) -> str:
    while True:
        s = clean_text(_read(f"  {prompt}: ", input_fn))
        if not s:
            if required:
                _bad("This field is required - please enter a value.", out); continue
            return ""
        if len(s) > max_len:
            _bad(f"Too long ({len(s)} characters, max {max_len}).", out); continue
        if regex and not re.match(regex, s):
            _bad(f"'{s}' is not valid" + (f" ({hint})" if hint else "") + ".", out); continue
        return s


def ask_number(prompt: str, *, kind: str = "float", lo: Optional[float] = None, hi: Optional[float] = None,
               required: bool = True, input_fn: Callable = input, out: Callable = None) -> str:
    """Returns the number formatted as a string ('' when optional and blank)."""
    while True:
        s = _read(f"  {prompt}: ", input_fn).strip()
        if not s:
            if required:
                _bad("This field is required - please enter a number.", out); continue
            return ""
        n = parse_number(s)
        if n is None:
            _bad(f"'{s}' is not a number. Digits only, e.g. 42" + (".5" if kind == "float" else "") + ".", out); continue
        if kind == "int" and n != int(n):
            _bad("Please enter a whole number.", out); continue
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            _bad(f"{s} is out of range - allowed values are {lo} to {hi}.", out); continue
        return fmt_number(n, kind)


def ask_int(prompt: str, lo: Optional[int] = None, hi: Optional[int] = None, **kw) -> int:
    return int(ask_number(prompt, kind="int", lo=lo, hi=hi, required=True, **kw))


def ask_date(prompt: str, *, required: bool = True, input_fn: Callable = input, out: Callable = None) -> str:
    from datetime import date
    while True:
        s = _read(f"  {prompt} (YYYY-MM-DD): ", input_fn).strip()
        if not s:
            if required:
                _bad("This field is required.", out); continue
            return ""
        d, _ = parse_date(s)
        if d is None:
            _bad(f"'{s}' is not a valid date. Use YYYY-MM-DD, e.g. 2023-08-15.", out); continue
        if d > date.today():
            _bad("Date cannot be in the future.", out); continue
        return d.isoformat()


def ask_yes_no(prompt: str, default: bool = False, input_fn: Callable = input) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            s = _read(f"  {prompt} {suffix}: ", input_fn).strip().lower()
        except InputAborted:
            return False
        if not s:
            return default
        if s in ("y", "yes"):
            return True
        if s in ("n", "no"):
            return False
        ui.error("Please answer y or n.")


def ask_choice(prompt: str, options: List[str], input_fn: Callable = input) -> str:
    """Pick an option by number or by (case-insensitive) name."""
    for i, o in enumerate(options, 1):
        print(f"    {ui.c(str(i), 'cyan', 'bold')}. {o}")
    while True:
        s = _read(f"  {prompt}: ", input_fn).strip()
        if s.isdigit() and 1 <= int(s) <= len(options):
            return options[int(s) - 1]
        for o in options:
            if s.lower() == o.lower():
                return o
        ui.error(f"Choose a number from 1 to {len(options)}.")


def ask_menu_choice(valid: Iterable[str], prompt: str = "Select an option", input_fn: Callable = input) -> str:
    valid = {str(v) for v in valid}
    while True:
        s = _read(f"\n  {prompt}: ", input_fn).strip().lower()
        if s in valid:
            return s
        ui.error(f"'{s}' is not a menu option." if s else "Please choose an option.")


# --------------------------------------------------------------------------- field level
def next_id(rows: List[dict], col: str, rule: dict) -> str:
    """Suggest the next free ID such as S041."""
    best_prefix, best_num, width = "S", 0, 3
    for r in rows:
        m = re.match(r"^([A-Za-z]*)(\d+)$", str(r.get(col, "")).strip())
        if m and int(m.group(2)) >= best_num:
            best_prefix, best_num, width = m.group(1), int(m.group(2)), len(m.group(2))
    return f"{best_prefix}{best_num + 1:0{width}d}"


def ask_field(col: str, rule: dict, rows: List[dict], *, input_fn: Callable = input,
              out: Callable = None, current: str = "") -> str:
    """Prompt for one column using its rule; returns a clean, validated string."""
    t = rule.get("type", "text")
    required = rule.get("required", False)
    label = col.replace("_", " ").title()
    tail = "" if required else " (optional, Enter to skip)"
    if current:
        tail += f" [current: {current}]"

    if t in ("int", "float"):
        lo, hi = rule.get("min"), rule.get("max")
        rng = f" {lo}-{hi}" if lo is not None or hi is not None else ""
        return ask_number(f"{label}{rng}{tail}", kind=t, lo=lo, hi=hi, required=required, input_fn=input_fn, out=out)
    if t == "date":
        return ask_date(f"{label}{tail}", required=required, input_fn=input_fn, out=out)
    if t == "email":
        s = ask_str(f"{label}{tail}", required=required, regex=EMAIL_REGEX, hint="e.g. name@campus.edu",
                    input_fn=input_fn, out=out)
        return s.lower()
    if t == "id":
        while True:
            sugg = next_id(rows, col, rule)
            s = ask_str(f"{label} (suggested {sugg}){tail}", required=required, regex=rule.get("regex"),
                        hint=rule.get("hint", ""), input_fn=input_fn, out=out)
            taken = {clean_text(r.get(col, "")).lower() for r in rows if r.get(col, "") != current}
            if s.lower() in taken:
                _bad(f"ID '{s}' already exists.", out); continue
            return s
    if t == "category":
        known = sorted({clean_text(v) for v in category_map(rows, col, rule).values()})
        closed = sorted((rule.get("aliases") or {}).keys())     # fixed vocabulary, e.g. departments
        shown = closed or known
        alias = {norm_key(a): canon for canon, al in (rule.get("aliases") or {}).items() for a in list(al) + [canon]}
        if shown:
            print(ui.c(f"    allowed values: {', '.join(shown)}", "grey"))
        while True:
            s = ask_str(f"{label}{tail}", required=required, input_fn=input_fn, out=out)
            if not s:
                return s
            if norm_key(s) in alias:
                return alias[norm_key(s)]
            hit = next((k for k in known if norm_key(k) == norm_key(s)), None)
            if hit:
                return hit
            if closed:
                _bad(f"'{s}' is not a recognised {label.lower()}. Choose one of: {', '.join(closed)}.", out)
                continue
            return s
    s = ask_str(f"{label}{tail}", required=required, regex=rule.get("regex"), hint=rule.get("hint", ""),
                input_fn=input_fn, out=out)
    return s.title() if (s and rule.get("title_case")) else s


# --------------------------------------------------------------------------- pure (non-interactive) validation
def validate_field(col: str, rule: dict, raw, rows: List[dict], current: str = ""):
    """Validate one raw value without prompting. Returns (clean_value, error_message_or_None).
    Used by the Streamlit GUI, the tests and anything else that needs the same rules as the CLI."""
    from datetime import date
    t = rule.get("type", "text")
    label = col.replace("_", " ").title()
    s = clean_text(raw)
    if not s:
        return ("", f"{label} is required.") if rule.get("required") else ("", None)
    if t in ("int", "float"):
        n = parse_number(s)
        if n is None:
            return s, f"{label}: '{s}' is not a number."
        if t == "int" and n != int(n):
            return s, f"{label}: please enter a whole number."
        lo, hi = rule.get("min"), rule.get("max")
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            return s, f"{label}: {s} is out of range (allowed {lo} to {hi})."
        return fmt_number(n, t), None
    if t == "date":
        d, _ = parse_date(s)
        if d is None:
            return s, f"{label}: '{s}' is not a valid date (use YYYY-MM-DD)."
        if d > date.today():
            return s, f"{label}: date cannot be in the future."
        return d.isoformat(), None
    if t == "email":
        if not re.match(EMAIL_REGEX, s):
            return s, f"{label}: '{s}' is not a valid email address."
        return s.lower(), None
    if t == "id":
        if rule.get("regex") and not re.match(rule["regex"], s):
            return s, f"{label}: '{s}' is not valid ({rule.get('hint', 'bad format')})."
        taken = {clean_text(r.get(col, "")).lower() for r in rows if r.get(col, "") != current}
        if s.lower() in taken:
            return s, f"{label}: '{s}' already exists."
        return s, None
    if t == "category":
        alias = {norm_key(a): canon for canon, al in (rule.get("aliases") or {}).items() for a in list(al) + [canon]}
        if norm_key(s) in alias:
            return alias[norm_key(s)], None
        known = sorted({clean_text(v) for v in category_map(rows, col, rule).values()})
        hit = next((k for k in known if norm_key(k) == norm_key(s)), None)
        if hit:
            return hit, None
        if rule.get("aliases"):
            return s, f"{label}: '{s}' is not recognised. Choose one of: {', '.join(sorted(rule['aliases']))}."
        return s, None
    if rule.get("regex") and not re.match(rule["regex"], s):
        return s, f"{label}: '{s}' is not valid" + (f" ({rule['hint']})" if rule.get("hint") else "") + "."
    return (s.title() if rule.get("title_case") else s), None

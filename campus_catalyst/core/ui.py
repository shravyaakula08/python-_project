"""Terminal presentation helpers: ANSI colours, banner, fixed-width tables, pagination."""
from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Callable, List, Sequence

if os.name == "nt":          # enable ANSI escape handling on Windows terminals
    os.system("")

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_CODES = {"reset": "0", "bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33",
          "blue": "34", "magenta": "35", "cyan": "36", "white": "97", "grey": "90"}


def c(text, *styles: str) -> str:
    if not USE_COLOR or not styles:
        return str(text)
    start = "".join(f"\033[{_CODES[s]}m" for s in styles)
    return f"{start}{text}\033[0m"


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def width() -> int:
    return max(60, min(shutil.get_terminal_size((100, 24)).columns, 140))


def banner() -> None:
    w = min(width(), 74)
    line = "=" * w
    print(c(line, "cyan"))
    print(c("  CAMPUS CATALYST".ljust(w), "bold", "cyan"))
    print(c("  Simple Data Cleaning Assistant  |  Project #98", "white"))
    print(c("  Find missing values, duplicate rows & inconsistent entries", "grey"))
    print(c(line, "cyan"))


def header(title: str) -> None:
    print()
    print(c(f"  {title}", "bold", "cyan"))
    print(c("  " + "-" * min(len(title) + 4, width() - 4), "grey"))


def success(msg): print(c("  OK  ", "green", "bold") + msg)
def error(msg): print(c(" ERR  ", "red", "bold") + msg)
def warn(msg): print(c(" WARN ", "yellow", "bold") + msg)
def info(msg): print(c(" INFO ", "blue", "bold") + msg)


def level_tag(level: str) -> str:
    colour = {"CRITICAL": "red", "WARNING": "yellow", "INFO": "green"}.get(level, "white")
    return c(f"[{level:8}]", colour, "bold")


def status_badge(status: str) -> str:
    colour = {"Healthy": "green", "Needs Attention": "yellow", "Critical": "red"}.get(status, "white")
    return c(f" {status.upper()} ", colour, "bold")


def sev_colour(sev: str) -> str:
    return {"high": "red", "medium": "yellow", "low": "grey"}.get(sev, "white")


def _cut(text: str, n: int) -> str:
    text = str(text).replace("\n", " ")
    return text if len(text) <= n else text[: max(n - 1, 1)] + "…"


def table(headers: Sequence[str], rows: Sequence[Sequence], max_col: int = 24) -> List[str]:
    """Fixed-width table with column separators. Returns the lines."""
    rows = [[str(x) for x in r] for r in rows]
    n = len(headers)
    avail = width() - 4
    widths = [min(max([len(headers[i])] + [len(r[i]) for r in rows]), max_col) for i in range(n)]
    # shrink the widest columns first until the table fits the terminal
    while sum(widths) + 3 * (n - 1) > avail and max(widths) > 6:
        widths[widths.index(max(widths))] -= 1
    sep = "-+-".join("-" * w for w in widths)
    out = [" | ".join(_cut(headers[i], widths[i]).ljust(widths[i]) for i in range(n)), sep]
    for r in rows:
        out.append(" | ".join(_cut(r[i], widths[i]).ljust(widths[i]) for i in range(n)))
    out[0] = c(out[0], "bold")
    out[1] = c(out[1], "grey")
    return ["  " + ln for ln in out]


def show_table_paged(headers, rows, page_size: int = 15, input_fn: Callable = input, max_col: int = 24) -> None:
    """Print a table with pagination breaks so large result sets stay readable."""
    if not rows:
        info("Nothing to show.")
        return
    pages = (len(rows) + page_size - 1) // page_size
    for p in range(pages):
        chunk = rows[p * page_size:(p + 1) * page_size]
        print("\n".join(table(headers, chunk, max_col)))
        if p < pages - 1:
            try:
                ans = input_fn(c(f"  -- page {p + 1}/{pages}  [Enter] next  [q] stop: ", "grey")).strip().lower()
            except EOFError:
                return
            if ans in ("q", "quit", "stop"):
                return
        else:
            print(c(f"  {len(rows)} row(s)", "grey"))


def bar(pct: float, length: int = 24) -> str:
    filled = int(round(length * max(0.0, min(pct, 100.0)) / 100))
    return "█" * filled + "░" * (length - filled)


def pause(input_fn: Callable = input) -> None:
    try:
        input_fn(c("\n  Press Enter to continue...", "grey"))
    except EOFError:
        pass

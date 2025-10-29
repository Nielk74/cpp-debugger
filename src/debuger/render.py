from __future__ import annotations

from typing import Iterable

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax


console = Console()

_ENC = (console.encoding or "").lower()
_UNICODE = "utf" in _ENC or "utf" in (getattr(console.file, "encoding", "") or "").lower()

_MARK_INFO = "›" if _UNICODE else ">"
_MARK_WARN = "!"
_MARK_ERR = "×" if _UNICODE else "x"
_MARK_OK = "✔" if _UNICODE else "+"


def info(msg: str) -> None:
    console.print(f"[bold cyan]{_MARK_INFO}[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"[bold yellow]{_MARK_WARN}[/] {msg}")


def error(msg: str) -> None:
    console.print(f"[bold red]{_MARK_ERR}[/] {msg}")


def success(msg: str) -> None:
    console.print(f"[bold green]{_MARK_OK}[/] {msg}")


def kv_table(title: str, rows: Iterable[tuple[str, str]]) -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    for k, v in rows:
        table.add_row(f"[bold]{k}[/]", str(v))
    console.print(Panel.fit(table, title=title))


def source_snippet(path: str, line: int, context: int = 3, language: str = "cpp") -> None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        warn(f"Source not available: {path}")
        return
    total = len(lines)
    # Clamp line into valid range, warn if it was out of bounds
    clamped = max(1, min(line, total))
    if clamped != line:
        warn(f"Adjusted source location: {path}:{line} -> {clamped}")
    start = max(1, clamped - context)
    end = min(total, clamped + context)
    code = "".join(lines[start - 1 : end])
    syn = Syntax(code, language, line_numbers=True, line_numbers_start=start, highlight_lines={clamped}, word_wrap=False)
    console.print(Panel(syn, title=f"{path}:{clamped}"))


def render_backtrace(lines: Iterable[str]) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Function", style="bold")
    table.add_column("Location", style="green")
    for line in lines:
        # expected shape: "#0  func at file:line" or "#0  func"
        idx = "?"
        func = line
        loc = ""
        try:
            if line.startswith("#"):
                parts = line.split("  ", 1)
                if len(parts) == 2:
                    idx_part, rest = parts
                    idx = idx_part[1:].strip()
                    func = rest
            if " at " in func:
                func, loc = func.split(" at ", 1)
        except Exception:
            pass
        table.add_row(idx, func.strip(), loc.strip())
    console.print(table)

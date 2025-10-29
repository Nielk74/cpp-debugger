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
    if line < 1 or line > total:
        warn(f"Invalid source location: {path}:{line}")
        return
    start = max(1, line - context)
    end = min(total, line + context)
    code = "".join(lines[start - 1 : end])
    syn = Syntax(code, language, line_numbers=True, line_numbers_start=start, highlight_lines={line}, word_wrap=False)
    console.print(Panel(syn, title=f"{path}:{line}"))

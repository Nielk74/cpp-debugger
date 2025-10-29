from __future__ import annotations

from typing import Iterable

from rich.console import Console
from rich.table import Table
from rich.panel import Panel


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

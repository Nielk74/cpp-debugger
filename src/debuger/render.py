from __future__ import annotations

from typing import Iterable

from rich.console import Console
from rich.table import Table
from rich.panel import Panel


console = Console()


def info(msg: str) -> None:
    console.print(f"[bold cyan]›[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"[bold yellow]![/] {msg}")


def error(msg: str) -> None:
    console.print(f"[bold red]×[/] {msg}")


def success(msg: str) -> None:
    console.print(f"[bold green]✔[/] {msg}")


def kv_table(title: str, rows: Iterable[tuple[str, str]]) -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    for k, v in rows:
        table.add_row(f"[bold]{k}[/]", str(v))
    console.print(Panel.fit(table, title=title))


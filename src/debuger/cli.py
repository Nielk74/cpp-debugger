from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml

from . import __version__
from .config import DebugerConfig, CONFIG_FILENAME
from .adapters import available_adapters, get_adapter, AdapterError
from .render import console, info, warn, error, success, kv_table


app = typer.Typer(help="Good-looking CLI for C/C++ debugging (LLDB/GDB/CDB adapters)")


@app.callback()
def _entry() -> None:
    pass


@app.command()
def version() -> None:
    console.print(f"debuger {__version__}")


@app.command()
def doctor() -> None:
    info("Environment diagnostics")
    rows = [
        ("OS", f"{platform.system()} {platform.release()}"),
        ("Python", sys.version.split(" ")[0]),
        ("CWD", str(Path.cwd())),
    ]
    kv_table("System", rows)

    adap_rows = []
    for a in available_adapters():
        status = "available" if a.available else "missing"
        adap_rows.append((f"{a.name}", f"{status} — {a.detail}"))
    kv_table("Adapters", adap_rows)

    sym = os.environ.get("_NT_SYMBOL_PATH")
    kv_table("Windows Symbols", [("_NT_SYMBOL_PATH", sym or "(not set)")])


@app.command()
def init(
    target: Optional[str] = typer.Option(None, help="Path to executable to debug"),
    cwd: Optional[str] = typer.Option(None, help="Working directory"),
    debugger: Optional[str] = typer.Option(None, help="Preferred adapter: lldb|gdb|cdb"),
) -> None:
    path = Path.cwd() / CONFIG_FILENAME
    if path.exists():
        warn(f"{CONFIG_FILENAME} already exists; overwriting")
    cfg = DebugerConfig(target=target, cwd=cwd, debugger=debugger, args=[], env={}, symbols=[], sourcePaths=[])
    cfg.save(path)
    success(f"Created {CONFIG_FILENAME}")
    console.print(yaml.safe_dump(cfg.to_dict(), sort_keys=False))


@app.command()
def config() -> None:
    try:
        cfg, cfg_path = DebugerConfig.find_in_ancestors(Path.cwd())
        info(f"Resolved config: {cfg_path}")
        console.print(yaml.safe_dump(cfg.to_dict(), sort_keys=False))
    except FileNotFoundError as e:
        error(str(e))
        raise typer.Exit(code=1)


@app.command()
def open(
    path: str = typer.Argument(..., help="Path to executable"),
    debugger: Optional[str] = typer.Option(None, help="Preferred adapter: lldb|gdb|cdb"),
    dry_run: bool = typer.Option(True, help="Show what would happen, don't start yet"),
) -> None:
    abs_path = str(Path(path).resolve())
    if not Path(abs_path).exists():
        error(f"Target not found: {abs_path}")
        raise typer.Exit(code=2)
    cfg = DebugerConfig(target=abs_path, debugger=debugger)
    try:
        adapter = get_adapter(cfg.debugger)
        info(f"Selected adapter: {adapter.name}")
    except AdapterError as e:
        error(str(e))
        raise typer.Exit(code=3)

    if dry_run:
        success("Dry-run: would launch under debugger")
        console.print(f"target: {abs_path}")
        return

    # Placeholder: not implemented yet
    error("Launching under debugger not implemented yet (MVP phase)")
    raise typer.Exit(code=10)


@app.command()
def run(
    dry_run: bool = typer.Option(True, help="Show what would happen, don't start yet"),
) -> None:
    try:
        cfg, cfg_path = DebugerConfig.find_in_ancestors(Path.cwd())
        info(f"Using config: {cfg_path}")
    except FileNotFoundError as e:
        error(str(e))
        raise typer.Exit(code=1)

    if not cfg.target:
        error("No 'target' specified in debuger.yaml")
        raise typer.Exit(code=2)

    if not Path(cfg.target).exists():
        error(f"Target not found: {cfg.target}")
        raise typer.Exit(code=2)

    try:
        adapter = get_adapter(cfg.debugger)
        info(f"Selected adapter: {adapter.name}")
    except AdapterError as e:
        error(str(e))
        raise typer.Exit(code=3)

    if dry_run:
        success("Dry-run: would launch under debugger")
        console.print(yaml.safe_dump(cfg.to_dict(), sort_keys=False))
        return

    error("Launching under debugger not implemented yet (MVP phase)")
    raise typer.Exit(code=10)


@app.command()
def attach(
    pid: int = typer.Option(..., "--pid", help="Process ID to attach to"),
    debugger: Optional[str] = typer.Option(None, help="Preferred adapter: lldb|gdb|cdb"),
    dry_run: bool = typer.Option(True, help="Show what would happen, don't start yet"),
) -> None:
    cfg = DebugerConfig(debugger=debugger)
    try:
        adapter = get_adapter(cfg.debugger)
        info(f"Selected adapter: {adapter.name}")
    except AdapterError as e:
        error(str(e))
        raise typer.Exit(code=3)

    if dry_run:
        success(f"Dry-run: would attach to PID {pid}")
        return

    error("Attach under debugger not implemented yet (MVP phase)")
    raise typer.Exit(code=10)


# Placeholders for core debugging verbs (will operate in a future interactive session)
@app.command()
def bt() -> None:
    error("bt not available outside a running session (future shell mode)")
    raise typer.Exit(code=10)


@app.command()
def cont() -> None:
    error("cont not available outside a running session (future shell mode)")
    raise typer.Exit(code=10)


@app.command()
def step() -> None:
    error("step not available outside a running session (future shell mode)")
    raise typer.Exit(code=10)


@app.command()
def next() -> None:  # noqa: A003 - intentional command name
    error("next not available outside a running session (future shell mode)")
    raise typer.Exit(code=10)


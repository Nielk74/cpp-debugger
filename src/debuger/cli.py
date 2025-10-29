from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
import shutil
from rich.markup import escape
from typing import Optional

import typer
import yaml

from . import __version__
from .config import DebugerConfig, CONFIG_FILENAME
from .adapters import available_adapters, get_adapter, AdapterError
from .render import console, info, warn, error, success, kv_table
from .state import SessionState


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
        adap_rows.append((f"{a.name}", f"{status} - {a.detail}"))
    kv_table("Adapters", adap_rows)

    sym = os.environ.get("_NT_SYMBOL_PATH")
    kv_table("Windows Symbols", [("_NT_SYMBOL_PATH", sym or "(not set)")])

    # Windows-specific hints for LLDB/GDB setup
    if platform.system().lower().startswith("win"):
        pyver = f"python{sys.version_info.major}{sys.version_info.minor}"
        llvm_dirs = [
            Path("C:/Program Files/LLVM/lib/site-packages"),
            Path(f"C:/Program Files/LLVM/lib/{pyver}/site-packages"),
            Path("C:/Program Files/LLVM/bin/..//lib/site-packages"),
        ]
        lldb_candidates = [p for p in llvm_dirs if p.exists()]
        lldb_exe = Path("C:/Program Files/LLVM/bin/lldb.exe")

        console.print("[bold]Hints (Windows)[/]")
        if lldb_candidates:
            console.print("- Potential LLDB Python path(s):")
            for p in lldb_candidates:
                console.print(f"  {p}")
            console.print("  Add to PYTHONPATH for current session:")
            cmd = f"$env:PYTHONPATH = \"{lldb_candidates[0]}\" + ';' + ($env:PYTHONPATH -as [string])"
            console.print(escape("  " + cmd))
        else:
            console.print("- Could not locate LLDB Python site-packages under 'C:\\Program Files\\LLVM'.")
            console.print("  Install LLVM with LLDB and Python bindings enabled.")

        if not shutil.which("lldb.exe") and lldb_exe.exists():
            console.print("- lldb.exe detected but not on PATH. Add it:")
            console.print(escape('  $env:Path = "C:\\Program Files\\LLVM\\bin" + ";" + $env:Path'))

        # Check lldb runtime health (common missing VC++ runtime case)
        exe = shutil.which("lldb.exe") or (str(lldb_exe) if lldb_exe.exists() else None)
        if exe:
            try:
                import subprocess
                cp = subprocess.run([exe, "-v"], capture_output=True, text=True)
                if cp.returncode != 0:
                    console.print("- lldb exists but failed to start (likely missing DLLs).")
                    console.print("  Install the latest Microsoft Visual C++ Redistributable (x64).")
            except Exception:
                pass

        # Show lldb -P (Python path) if available
        if exe:
            try:
                import subprocess
                cp = subprocess.run([exe, "-P"], capture_output=True, text=True)
                if cp.returncode == 0 and cp.stdout.strip():
                    p = cp.stdout.strip()
                    console.print("- lldb Python path (-P):")
                    console.print(escape(f"  $env:PYTHONPATH = \"{p}\" + ';' + ($env:PYTHONPATH -as [string])"))
            except Exception:
                pass

        # GDB typical installs
        gdb_paths = [
            Path("C:/msys64/mingw64/bin/gdb.exe"),
            Path("C:/msys64/usr/bin/gdb.exe"),
            Path("C:/mingw64/bin/gdb.exe"),
        ]
        gdb_found = [p for p in gdb_paths if p.exists()]
        if gdb_found and not shutil.which("gdb.exe"):
            console.print("- gdb.exe detected but not on PATH. Add one of:")
            for p in gdb_found:
                console.print(escape(f"  $env:Path = \"{p.parent}\" + ';' + $env:Path"))


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

    warn("Direct launch is not interactive yet. Use 'debuger shell' for a live session.")
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

    warn("Direct launch is not interactive yet. Use 'debuger shell' for a live session.")
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

    warn("Direct attach is not interactive yet. Use 'debuger shell' for a live session.")
    raise typer.Exit(code=10)


@app.command()
def shell(
    path: Optional[str] = typer.Argument(None, help="Path to executable. If omitted, uses debuger.yaml"),
    debugger: Optional[str] = typer.Option(None, help="Preferred adapter: lldb|gdb|cdb"),
    stop_at_entry: bool = typer.Option(True, help="Break at program entry ('main')"),
) -> None:
    """Start an interactive debugger session (experimental)."""
    # Resolve target/config
    cfg: DebugerConfig
    project_root = Path.cwd()
    if path:
        abs_path = str(Path(path).resolve())
        if not Path(abs_path).exists():
            error(f"Target not found: {abs_path}")
            raise typer.Exit(code=2)
        cfg = DebugerConfig(target=abs_path, debugger=debugger)
    else:
        try:
            cfg, cfg_path = DebugerConfig.find_in_ancestors(Path.cwd())
            info(f"Using config: {cfg_path}")
            if debugger:
                cfg.debugger = debugger
            project_root = Path(cfg_path).parent
        except FileNotFoundError as e:
            error(str(e))
            raise typer.Exit(code=1)

    if not cfg.target:
        error("No target specified")
        raise typer.Exit(code=2)

    # Load persisted state
    state = SessionState.load(project_root)

    try:
        adapter = get_adapter(cfg.debugger)
        info(f"Selected adapter: {adapter.name}")
    except AdapterError as e:
        error(str(e))
        raise typer.Exit(code=3)

    # Launch or attach
    # If adapter is a passthrough one (e.g., lldb CLI), hand control over
    if getattr(adapter, "is_passthrough", False):
        warn("Handing over to LLDB interactive CLI (temporary fallback).")
        adapter.launch(cfg.target, cfg.args, cfg.cwd, cfg.env, stop_at_entry=stop_at_entry)
        success("LLDB session ended")
        raise typer.Exit(code=0)

    try:
        adapter.launch(cfg.target, cfg.args, cfg.cwd, cfg.env, stop_at_entry=stop_at_entry)
    except AdapterError as e:
        error(str(e))
        raise typer.Exit(code=4)

    # Reapply saved breakpoints
    if state.breakpoints:
        for bp in state.breakpoints:
            try:
                bp_id = adapter.bp_add(bp.spec)
                bp.last_id = bp_id
            except AdapterError:
                pass
        state.save(project_root)

    console.print("[bold green]Interactive session started[/] - type 'help' for commands. 'quit' to exit.")
    # Simple REPL
    while True:
        try:
            line = input("debuger> ").strip()
        except (EOFError, KeyboardInterrupt):
            line = "quit"
        if not line:
            continue
        cmd, *rest = line.split()
        try:
            if cmd in ("quit", "exit"):  # end session
                break
            elif cmd in ("help", ":help"):
                console.print(
                    "Commands: help, bt, step, next, finish, cont, threads, thread <id>, frames, frame <n>, locals, regs, disasm, eval <expr>, bp add <spec>, bp ls, bp rm <id>, quit"
                )
            elif cmd == "bt":
                for row in adapter.backtrace():
                    console.print(row)
            elif cmd == "step":
                adapter.step_in()
                for row in adapter.backtrace(1):
                    console.print(row)
            elif cmd == "next":
                adapter.step_over()
                for row in adapter.backtrace(1):
                    console.print(row)
            elif cmd in ("finish", "stepout"):
                adapter.step_out()
                for row in adapter.backtrace(1):
                    console.print(row)
            elif cmd in ("cont", "continue"):
                adapter.continue_run()
                # after continue, show top frame if stopped again
                for row in adapter.backtrace(1):
                    console.print(row)
            elif cmd == "locals":
                try:
                    for row in adapter.locals():
                        console.print(row)
                except AdapterError as e:
                    error(str(e))
            elif cmd == "regs":
                try:
                    for row in adapter.regs():
                        console.print(row)
                except AdapterError as e:
                    error(str(e))
            elif cmd == "disasm":
                try:
                    for row in adapter.disasm():
                        console.print(row)
                except AdapterError as e:
                    error(str(e))
            elif cmd == "eval" and rest:
                expr = " ".join(rest)
                try:
                    console.print(adapter.eval(expr))
                except AdapterError as e:
                    error(str(e))
            elif cmd == "threads":
                for row in adapter.threads():
                    console.print(row)
            elif cmd == "thread" and rest:
                try:
                    tid = int(rest[0], 0)
                except ValueError:
                    console.print("Invalid thread id")
                    continue
                try:
                    adapter.select_thread(tid)
                except AdapterError as e:
                    error(str(e))
            elif cmd == "frames":
                for row in adapter.frames():
                    console.print(row)
            elif cmd == "frame" and rest:
                try:
                    idx = int(rest[0])
                except ValueError:
                    console.print("Invalid frame index")
                    continue
                try:
                    adapter.select_frame(idx)
                except AdapterError as e:
                    error(str(e))
            elif cmd == "bp":
                if not rest:
                    console.print("Usage: bp add <spec> | bp ls | bp rm <id>")
                    continue
                sub = rest[0]
                if sub == "add" and len(rest) >= 2:
                    spec = " ".join(rest[1:])
                    bp_id = adapter.bp_add(spec)
                    console.print(f"breakpoint {bp_id} added")
                    state.add_bp(spec, bp_id)
                    state.save(project_root)
                elif sub == "ls":
                    for row in adapter.bp_list():
                        console.print(row)
                elif sub == "rm" and len(rest) == 2:
                    try:
                        bp_id = int(rest[1])
                    except ValueError:
                        console.print("Invalid breakpoint id")
                        continue
                    adapter.bp_remove(bp_id)
                    console.print(f"breakpoint {bp_id} removed")
                    state.remove_bp_by_id(bp_id)
                    state.save(project_root)
                else:
                    console.print("Usage: bp add <spec> | bp ls | bp rm <id>")
            else:
                console.print(f"Unknown command: {cmd}")
        except AdapterError as e:
            error(str(e))
            continue
        except Exception as e:  # safety net
            error(f"Error: {e}")
            continue

    try:
        # Attempt to shut down adapter
        adapter.shutdown()
    except Exception:
        pass
    success("Session ended")


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

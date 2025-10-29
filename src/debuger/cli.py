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
from .render import console, info, warn, error, success, kv_table, source_snippet, render_backtrace
from .paths import remap_source
from .state import SessionState
from .analysis import generate_report, export_trace


app = typer.Typer(help="Good-looking CLI for C/C++ debugging (LLDB/GDB/CDB adapters)")
analyze_app = typer.Typer(help="Trace executed lines and intersect with recent Git changes")


def _resolve_state(root_opt: Optional[str], state_opt: Optional[str], debug: bool = False) -> tuple[Path, SessionState, Path]:
    """Resolve project root and load SessionState.

    Returns (project_root, state, state_path).
    """
    # If state path provided explicitly, prefer it
    if state_opt:
        spath = Path(state_opt).resolve()
        proj = spath.parent.parent if spath.parent.name == ".debuger" else spath.parent
        if debug:
            info(f"Using explicit state: {spath}")
        st = SessionState.load(proj)
        return proj, st, spath

    # Else resolve project root
    project_root = Path(root_opt).resolve() if root_opt else Path.cwd()
    cfg_path: Optional[Path] = None
    try:
        _, cfg_path = DebugerConfig.find_in_ancestors(project_root)
        project_root = cfg_path.parent
    except FileNotFoundError:
        pass

    # Try standard state path
    spath = project_root / ".debuger" / "session.json"
    if spath.exists():
        if debug:
            info(f"Loading state: {spath}")
        st = SessionState.load(project_root)
        return project_root, st, spath

    # Search upwards for a .debuger/session.json
    for d in [project_root, *project_root.parents]:
        cand = d / ".debuger" / "session.json"
        if cand.exists():
            if debug:
                info(f"Found state in ancestor: {cand}")
            st = SessionState.load(d)
            return d, st, cand

    if debug:
        warn("No state file found; using empty session state")
    return project_root, SessionState(), spath


def _open_location(path: str, line: int, template: Optional[str]) -> None:
    if not template:
        return
    try:
        import subprocess
        cmd = template.format(file=path, line=line)
        subprocess.Popen(cmd, shell=True)
    except Exception:
        pass


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


@analyze_app.command("report")
def analyze_report(
    since: Optional[str] = typer.Option(None, help="Git ref to compare against (e.g., origin/main)"),
    days: Optional[int] = typer.Option(None, help="Number of days for recent changes"),
    commits: Optional[int] = typer.Option(None, help="Number of commits for recent changes"),
    top: Optional[int] = typer.Option(None, help="Show only top N results by hits"),
    root: Optional[str] = typer.Option(None, help="Project root to read .debuger/session.json from"),
    state: Optional[str] = typer.Option(None, help="Explicit path to .debuger/session.json"),
    debug: bool = typer.Option(False, help="Verbose state resolution logging"),
    previews: int = typer.Option(0, help="Number of snippet previews per file (0 = table only)"),
    open: Optional[str] = typer.Option(None, help="Editor cmd template to open top hit, e.g. 'code -g {file}:{line}'"),
) -> None:
    project_root, st, state_path = _resolve_state(root, state, debug)
    # Load cfg near project_root if available
    try:
        cfg, _cfgp = DebugerConfig.find_in_ancestors(project_root)
    except FileNotFoundError:
        cfg = DebugerConfig()
    if debug:
        info(f"project_root={project_root}")
        info(f"state_path={state_path}")
        info(f"trace_files={len(st.trace)}")
    entries = generate_report(project_root, cfg, st, since=since, days=days, commits=commits)
    if top is not None:
        entries = entries[:top]
    if not entries:
        warn("No intersecting executed/recently-changed lines found")
        raise typer.Exit()
    if open and entries:
        _open_location(entries[0].path, entries[0].line, open)
    if previews and previews > 0:
        from collections import defaultdict
        groups = defaultdict(list)
        for e in entries:
            groups[e.path].append(e)
        for path, els in groups.items():
            info(f"File: {path} ({sum(x.hits for x in els)} hits)")
            shown = 0
            for e in els:
                if shown >= previews:
                    break
                source_snippet(path, e.line)
                shown += 1
    else:
        from rich.table import Table
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Hits", justify="right", style="yellow", width=6)
        table.add_column("Location", style="green")
        for e in entries:
            table.add_row(str(e.hits), f"{e.path}:{e.line}")
        console.print(table)


@analyze_app.command("clear")
def analyze_clear(root: Optional[str] = typer.Option(None, help="Project root"), state: Optional[str] = typer.Option(None, help="Path to .debuger/session.json"), debug: bool = typer.Option(False, help="Verbose")) -> None:
    project_root, st, state_path = _resolve_state(root, state, debug)
    st.clear_trace()
    st.save(project_root)
    success("Cleared trace data")


@analyze_app.command("export")
def analyze_export(path: str = typer.Argument(..., help="Output JSON path"), root: Optional[str] = typer.Option(None, help="Project root"), state: Optional[str] = typer.Option(None, help="Path to .debuger/session.json"), debug: bool = typer.Option(False, help="Verbose")) -> None:
    project_root, st, state_path = _resolve_state(root, state, debug)
    export_trace(project_root, st, Path(path))
    success(f"Exported trace to {path}")


app.add_typer(analyze_app, name="analyze")


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
        # Prefer saving state near the target's repository root if present
        # Walk up from target directory to find .git
        target_dir = Path(abs_path).parent
        for d in [target_dir, *target_dir.parents]:
            if (d / ".git").exists():
                project_root = d
                break
        else:
            project_root = target_dir
    else:
        try:
            cfg, cfg_path = DebugerConfig.find_in_ancestors(Path.cwd())
            info(f"Using config: {cfg_path}")
            if debugger:
                cfg.debugger = debugger
            # Prefer the repo containing the target, if configured
            project_root = Path(cfg_path).parent
            if cfg.target:
                tdir = Path(cfg.target).resolve().parent
                for d in [tdir, *tdir.parents]:
                    if (d / ".git").exists():
                        project_root = d
                        break
        except FileNotFoundError as e:
            error(str(e))
            raise typer.Exit(code=1)

    if not cfg.target:
        error("No target specified")
        raise typer.Exit(code=2)

    # Windows: attempt to auto-configure PATH/PYTHONPATH for LLDB
    if platform.system().lower().startswith("win"):
        try:
            bin_dir = Path("C:/Program Files/LLVM/bin")
            if bin_dir.exists():
                # Prepend bin to PATH
                os.environ["Path"] = str(bin_dir) + ";" + os.environ.get("Path", "")
            # Embedded Python folder detection (e.g., python310 extracted here)
            for sub in bin_dir.iterdir():
                if sub.is_dir() and sub.name.startswith("python3"):
                    os.environ["Path"] = str(sub) + ";" + os.environ.get("Path", "")
                    break
        except Exception:
            pass

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
    # Show initial context if available
    try:
        loc = adapter.current_location()
        if loc and loc[0] and loc[1]:
            spath = remap_source(loc[0], cfg)
            source_snippet(spath, int(loc[1]))
    except Exception:
        pass
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
                frames = adapter.backtrace()
                render_backtrace(frames)
                # Show snippet for top frame if available
                try:
                    loc = adapter.current_location()
                    if loc and loc[0] and loc[1]:
                        spath = remap_source(loc[0], cfg)
                        source_snippet(spath, int(loc[1]))
                except Exception:
                    pass
            elif cmd == "step":
                adapter.step_in()
                loc = adapter.current_location()
                if loc and loc[0] and loc[1]:
                    spath = remap_source(loc[0], cfg)
                    source_snippet(spath, int(loc[1]))
                    if state.analyze_active:
                        state.record_hit(spath, int(loc[1]))
                        state.save(project_root)
                else:
                    for row in adapter.backtrace(1):
                        console.print(row)
            elif cmd == "next":
                adapter.step_over()
                loc = adapter.current_location()
                if loc and loc[0] and loc[1]:
                    spath = remap_source(loc[0], cfg)
                    source_snippet(spath, int(loc[1]))
                    if state.analyze_active:
                        state.record_hit(spath, int(loc[1]))
                        state.save(project_root)
                else:
                    for row in adapter.backtrace(1):
                        console.print(row)
            elif cmd in ("finish", "stepout"):
                adapter.step_out()
                loc = adapter.current_location()
                if loc and loc[0] and loc[1]:
                    spath = remap_source(loc[0], cfg)
                    source_snippet(spath, int(loc[1]))
                    if state.analyze_active:
                        state.record_hit(spath, int(loc[1]))
                        state.save(project_root)
                else:
                    for row in adapter.backtrace(1):
                        console.print(row)
            elif cmd in ("cont", "continue"):
                adapter.continue_run()
                # after continue, show top frame if stopped again
                loc = adapter.current_location()
                if loc and loc[0] and loc[1]:
                    spath = remap_source(loc[0], cfg)
                    source_snippet(spath, int(loc[1]))
                    if state.analyze_active:
                        state.record_hit(spath, int(loc[1]))
                        state.save(project_root)
                else:
                    for row in adapter.backtrace(1):
                        console.print(row)
            elif cmd in ("ctx", "context"):
                try:
                    loc = adapter.current_location()
                    if loc and loc[0] and loc[1]:
                        spath = remap_source(loc[0], cfg)
                        source_snippet(spath, int(loc[1]))
                    else:
                        warn("No source location available")
                except AdapterError as e:
                    error(str(e))
            elif cmd == "locals":
                try:
                    locs = adapter.locals()
                    rows = []
                    for item in locs:
                        if "=" in item:
                            name, val = item.split("=", 1)
                            rows.append((name.strip(), val.strip()))
                        else:
                            rows.append((item, ""))
                    kv_table("Locals", rows)
                except AdapterError as e:
                    error(str(e))
            elif cmd == "regs":
                try:
                    regs = adapter.regs()
                    rows = []
                    for item in regs:
                        if "=" in item:
                            name, val = item.split("=", 1)
                            rows.append((name.strip(), val.strip()))
                        else:
                            rows.append((item, ""))
                    kv_table("Registers", rows)
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
            elif cmd == "analyze":
                if not rest:
                    console.print("Usage: analyze start|stop|report|clear|export [options]")
                    continue
                sub = rest[0]
                if sub == "start":
                    opts = {"since": None, "days": None, "commits": None, "sweep": None, "sweep_until_break": False, "max_steps": None}
                    for tok in rest[1:]:
                        if tok.startswith("--since="):
                            opts["since"] = tok.split("=", 1)[1]
                        elif tok.startswith("--days="):
                            try:
                                opts["days"] = int(tok.split("=", 1)[1])
                            except Exception:
                                pass
                        elif tok.startswith("--commits="):
                            try:
                                opts["commits"] = int(tok.split("=", 1)[1])
                            except Exception:
                                pass
                        elif tok.startswith("--sweep="):
                            try:
                                opts["sweep"] = int(tok.split("=", 1)[1])
                            except Exception:
                                pass
                        elif tok == "--sweep-until-break":
                            opts["sweep_until_break"] = True
                        elif tok.startswith("--max-steps="):
                            try:
                                opts["max_steps"] = int(tok.split("=", 1)[1])
                            except Exception:
                                pass
                    state.analyze_active = True
                    state.analyze_window = {k: v for k, v in opts.items() if k != "sweep" and v is not None and k not in ("sweep_until_break", "max_steps")}
                    state.save(project_root)
                    success("Analysis tracing started")
                    # Optional sweep: step N times, recording hits
                    if opts.get("sweep"):
                        steps = int(opts["sweep"]) or 0
                        # Prepare simple breakpoint targets (file:line) from state
                        bp_targets = set()
                        for bp in state.breakpoints:
                            spec = bp.spec
                            if ":" in spec and spec.rsplit(":",1)[-1].isdigit():
                                f,l = spec.rsplit(":",1)
                                try:
                                    bp_targets.add( (str(Path(f).resolve()), int(l)) )
                                except Exception:
                                    bp_targets.add( (f, int(l)) )
                        max_steps = steps
                        if opts.get("sweep_until_break") and opts.get("max_steps"):
                            max_steps = min(max_steps, int(opts["max_steps"]))
                        for i in range(max_steps):
                            try:
                                loc = adapter.current_location()
                                if loc and loc[0] and loc[1]:
                                    spath = remap_source(loc[0], cfg)
                                    line_num = int(loc[1])
                                    state.record_hit(spath, line_num)
                                    if i % 50 == 0:
                                        info(f"sweep progress: {i}/{steps} at {spath}:{line_num}")
                                    if opts.get("sweep_until_break"):
                                        try:
                                            cur_key = (str(Path(spath).resolve()), line_num)
                                        except Exception:
                                            cur_key = (spath, line_num)
                                        if cur_key in bp_targets:
                                            warn("Sweep stopped: reached breakpoint target")
                                            break
                                adapter.step_over()
                            except AdapterError:
                                warn("Sweep stopped: adapter error during step")
                                break
                            except Exception:
                                break
                        state.save(project_root)
                        try:
                            done = i + 1
                        except UnboundLocalError:
                            done = 0
                        success(f"Sweep completed: {done} steps")
                elif sub == "stop":
                    state.analyze_active = False
                    state.save(project_root)
                    success("Analysis tracing stopped")
                elif sub == "report":
                    since = None
                    days = None
                    commits = None
                    previews = 3
                    open_tpl: Optional[str] = None
                    for tok in rest[1:]:
                        if tok.startswith("--since="):
                            since = tok.split("=", 1)[1]
                        elif tok.startswith("--days="):
                            try:
                                days = int(tok.split("=", 1)[1])
                            except Exception:
                                pass
                        elif tok.startswith("--commits="):
                            try:
                                commits = int(tok.split("=", 1)[1])
                            except Exception:
                                pass
                        elif tok.startswith("--previews="):
                            try:
                                previews = int(tok.split("=", 1)[1])
                            except Exception:
                                previews = 3
                        elif tok.startswith("--open="):
                            open_tpl = tok.split("=", 1)[1]
                    if not any([since, days, commits]) and state.analyze_window:
                        since = state.analyze_window.get("since")
                        days = state.analyze_window.get("days")
                        commits = state.analyze_window.get("commits")
                    entries = generate_report(project_root, cfg, state, since=since, days=days, commits=commits)
                    if not entries:
                        warn("No intersecting executed/recently-changed lines found")
                    else:
                        if open_tpl and entries:
                            _open_location(entries[0].path, entries[0].line, open_tpl)
                        # Group by file and render snippet previews for each hit
                        from collections import defaultdict
                        groups = defaultdict(list)
                        for e in entries:
                            groups[e.path].append(e)
                        for path, els in groups.items():
                            info(f"File: {path} ({sum(x.hits for x in els)} hits)")
                            shown = 0
                            for e in els:
                                if shown >= previews:
                                    break
                                source_snippet(path, e.line)
                                shown += 1
                elif sub == "clear":
                    state.clear_trace()
                    state.save(project_root)
                    success("Cleared trace data")
                elif sub == "export" and len(rest) >= 2:
                    outp = Path(rest[1])
                    export_trace(project_root, state, outp)
                    success(f"Exported trace to {outp}")
                else:
                    console.print("Usage: analyze start|stop|report|clear|export [options]")
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

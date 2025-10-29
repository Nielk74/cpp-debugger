# debuger

A modern, good-looking CLI to debug C/C++ programs with a friendly UX, clear output, and portable backends. The goal is to give you the speed and power of native debuggers (LLDB, GDB, WinDbg/CDB) with a simple, cohesive interface that feels great in a terminal.

This repository includes initial docs and a working CLI skeleton with adapters and an interactive shell. LLDB is the primary backend; GDB is a fallback. On Windows, if LLDB's Python API is unavailable, the CLI falls back to native `lldb.exe` (passthrough) so you can still debug.

- Primary target: C++ on Windows, Linux, and macOS
- Adapters: LLDB (primary), GDB (fallback), WinDbg/CDB (Windows-specific, later milestone)
- Nice-by-default output with colors, readable backtraces, pretty-printed variables, and helpful hints
- Git-aware analysis to surface recently changed lines you executed between breakpoints (accelerates triage on large codebases)

See:
- docs/ARCHITECTURE.md
- docs/CLI.md
- docs/ROADMAP.md
- docs/INTEGRATION_WINDOWS.md

## Install

Requires Python 3.10+.

- Editable install for development:
  - `pip install -e .`
- Verify:
  - `debuger version`
  - `debuger doctor`

## Quick Start

- Initialize config in your project:
  - `debuger init --target "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1\\x64\\Debug\\ConsoleApplication1.exe" --debugger lldb`
- Run diagnostics and follow hints (Windows PATH/PYTHONPATH):
  - `debuger doctor`
- Start an interactive session (experimental):
  - `debuger shell` (uses `debuger.yaml`), or
  - `debuger shell "C:\\...\\ConsoleApplication1.exe"`
    - If LLDB Python API isn’t available, we hand off to native `lldb` so you can still debug.

Inside the interactive session:
- `help` to list supported commands
- `bt`, `step`, `next`, `finish`, `cont`
- Breakpoints: `bp add file:line`, `bp ls`, `bp rm <id>`
- Analysis (planned): `analyze start/stop/report --since <git-ref>` or `--days <N>` or `--commits <N>`

Git analysis quick taste (works now):
- `analyze start --commits 50 --sweep=200` then `analyze report`
- Or offline: `debuger analyze report --commits 50 --state "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1\\.debuger\\session.json" --debug`

For your Visual Studio project at `C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1`, point `debuger.yaml` at the built executable (e.g. `x64\\\\Debug\\\\ConsoleApplication1.exe`).

Example `debuger.yaml`:

```
target: "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1\\x64\\Debug\\ConsoleApplication1.exe"
args: []
cwd: "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1"
debugger: lldb
symbols: []
sourcePaths:
  - "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1"
sourceMap:
  - { from: "D:/agent/_work/1/s/ConsoleApplication1", to: "C:/Users/Antoine/source/repos/ConsoleApplication1" }
```

## Windows Notes

- Ensure `lldb.exe` runs: `lldb -v`
  - If it fails with a missing DLL error, install the Microsoft Visual C++ 2015–2022 Redistributable (x64).
- If the LLDB Python module doesn’t import on your Python version:
  - Use passthrough `lldb` (works out of the box), or
  - Set `PYTHONPATH` to the output of `lldb -P` (shown in `debuger doctor`), or
  - Use Python 3.12 which often matches LLDB’s bindings.

### Python Embedded Distribution (quick fix)

If LLDB is built against a specific Python (e.g., 3.10 or 3.11) and you don’t have that runtime, you can use the Python Embedded distribution to satisfy the DLL dependency for `lldb.exe` and the LLDB Python module:

- Download the embedded package that matches your LLDB’s Python version (example used here for 3.10.11):
  - `https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip`
- Place it under `C:\\Program Files\\LLVM\\bin` and extract it:
  - Either extract directly into `bin` so `python310.dll` sits next to `lldb.exe`, or extract to a subfolder (e.g., `bin\\python310`) and add that folder to `PATH`.
  - PowerShell example (subfolder):
    - `Expand-Archive -Path "C:\\Program Files\\LLVM\\bin\\python-3.10.11-embed-amd64.zip" -DestinationPath "C:\\Program Files\\LLVM\\bin\\python310" -Force`
    - `$env:Path = "C:\\Program Files\\LLVM\\bin\\python310" + ";" + $env:Path`
- Set `PYTHONPATH` so LLDB can find its Python package:
  - `$env:PYTHONPATH = (lldb -P) + ';' + ($env:PYTHONPATH -as [string])`
  - Or: `$env:PYTHONPATH = "C:\\Program Files\\LLVM\\lib\\site-packages" + ';' + ($env:PYTHONPATH -as [string])`
- Optional: If using the embedded distribution, edit `python310._pth` inside the extracted folder and add the LLDB site-packages path (or ensure `import site` is enabled) for more standard behavior.
- Verify:
  - `lldb -v` works
  - `python -c "import sys; sys.path.insert(0, r'C:\\Program Files\\LLVM\\lib\\site-packages'); import lldb; print('OK')"`

## Adapters

- LLDB (primary)
  - Python API adapter for integrated experience
  - CLI passthrough adapter when Python bindings aren’t available
- GDB (fallback)
  - Minimal MI2 implementation; best with DWARF (MinGW/MSYS2)
- WinDbg/CDB
  - Planned for deeper Windows/PDB support

## Git-Aware Analysis (planned)

Trace the executed source lines between two breakpoints and intersect them with Git “recently modified” lines, so you can focus on the code most likely related to a regression.

Highlights:
- Start/stop tracing between breakpoints; record (file:line) hits
- Compare with recent changes: by `--since <ref>`, `--days N`, or `--commits N`
- Report sorted by file/function, with context and quick jump

See docs/GIT_ANALYSIS.md for design and CLI usage.

### Usage & Troubleshooting

- Project root and state file
  - When launching with a target exe, `debuger shell` stores trace/state under the nearest parent containing `.git` (the target’s repo).
  - When launching via `debuger.yaml`, the shell prefers the repo that contains `target` from the config.
  - You can always override state resolution: use `--state <path-to-.debuger\session.json>` and `--root <project-root>` on `debuger analyze ...`.
  - Use `--debug` to print the resolved `project_root`, `state_path`, and trace file count.

- Recent changes window
  - If your repo has no remote or `origin/main`, prefer `--commits N` or `--days N` instead of `--since origin/main`.
  - The analyzer falls back to the last 50 commits if a `--since` ref is missing.

- Sweep mode
  - `analyze start --sweep=N` performs N step-overs from the current stop and records hits.
  - Programs that exit quickly may complete early; add breakpoints to pause earlier.

- Large line numbers from PDB
  - Some PDBs report huge line numbers; the tool clamps recorded lines to actual file ranges so reports still match Git changes.

- Windows Unicode
  - Git output is read as UTF-8 to avoid cp1252 decode errors in PowerShell consoles.

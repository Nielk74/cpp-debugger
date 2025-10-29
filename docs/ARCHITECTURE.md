# Architecture

This document outlines the initial architecture for `debuger`, a CLI-first debugger focused on excellent developer experience while leveraging existing native debuggers.

## Goals

- Friendly CLI with a consistent interface across platforms
- High-signal output (clean backtraces, demangled names, helpful hints)
- Portable adapter layer for LLDB, GDB, and later WinDbg/CDB
- Zero-required GUI; optional TUI later
- Simple project config via `debuger.yaml`

## High-Level Components

1) CLI Frontend
   - Parses commands and options, renders output, manages the REPL-like interaction model.
   - Planned stack: Python 3.10+, Typer/Click + Rich for colored output.

2) Session Manager
   - Owns a single debug session lifecycle: launch/attach, stop reasons, active thread/frame, stepping, and teardown.
   - Stores breakpoints, watch expressions, and history.

3) Adapter Layer (Debugger Abstraction)
   - Unified interface: Process, Thread, Frame, Breakpoint, Symbol, Memory, Disassembly.
   - Implementations:
     - LLDB Adapter (primary): uses `lldb` Python API where available.
     - GDB Adapter (fallback): uses `gdb --interpreter=mi2` and parses MI output robustly.
     - WinDbg/CDB Adapter (Windows, later milestone): uses dbgeng (COM) via `comtypes` or an external bridge.

4) Symbolization & Source Mapping
   - Demangling: rely on LLDB/GDB, with optional `llvm-cxxfilt`/`c++filt` fallback.
   - Source mapping: handle path remapping when debugging binaries built on different machines/containers.
   - Symbol paths: support `_NT_SYMBOL_PATH` (Windows) and local `.pdb` discovery; DWARF/ELF on Unix.

5) Presentation Layer
   - Clean, minimal output by default; detail on demand.
   - Pretty printers for common STL types (vector, string, map) via adapter capabilities.
   - Optional TUI milestone using Textual after CLI stabilizes.

6) Configuration
   - Per-project `debuger.yaml` with fields:
     - `target`: path to executable
     - `args`: runtime arguments
     - `cwd`: working directory
     - `env`: environment variables
     - `debugger`: preferred adapter (`lldb`, `gdb`, `cdb`)
     - `symbols`: extra symbol paths
- `sourcePaths`: path remapping rules

7) Git + Trace Analyzer (Planned)
   - Execution Trace Collector: records `(file:line)` hits during step/breakpoint stops
   - Git Change Scanner: collects recently modified line ranges via `git diff`/`git log`
   - Correlator: intersects executed lines with recent changes; outputs ranked, grouped results
   - Storage: `.debuger/trace.json`; configurable ignore patterns


## Data Flow (Launch)

CLI → Config Loader → Session Manager → Adapter:

- Resolve `debugger` selection and binary path
- Launch with symbols and breakpoint bootstrap
- Wait for stop in `main` (optional), hand control to user

## Data Flow (Attach)

CLI → Session Manager → Adapter:

- Attach to PID, resolve symbols, enumerate threads/frames
- Provide immediate `bt` and source context

## Error Handling Philosophy

- Fail noisy with one-line actionable hints (e.g., suggest installing LLVM for LLDB on Windows).
- Annotate adapter errors with clarity: which command failed and why.
- Offer `--debug-io` to show raw adapter traffic for issue reporting.

## Security & Safety

- No code execution beyond debugger operations.
- No telemetry by default.

## Stretch Goals

- DAP (Debug Adapter Protocol) client compatibility to tap into more adapters.
- Record/replay integration where supported.
- Time-travel debugging (Windows) if CDB backend exposes it.

# Roadmap

This roadmap sequences work from a usable MVP to advanced features. Timelines are indicative and can be adjusted based on early feedback.

## Milestone 0 — Planning (this phase)

- Document architecture, CLI, and Windows integration details
- Validate approach and paths to your existing C++ project

## Milestone 1 — MVP (LLDB-first, GDB fallback)

- CLI skeleton with `init`, `run`, `open`, `attach`, `bt`, `step`, `next`, `cont`
- LLDB adapter using Python API (if `lldb` module available)
- GDB adapter using MI2 (when LLDB unavailable)
- `doctor` to detect environment and suggest installs (LLVM, MinGW)
- `debuger.yaml` config and launcher resolution
- Pretty backtrace formatting with source snippets

## Milestone 2 — Breakpoints, Watches, and Quality

- Breakpoint management (file:line, function, address)
- Watch expressions with periodic refresh on stop
- Pretty-printers for STL containers (via adapter capabilities)
- Source path remapping rules
- Solid error messages and hints

## Milestone 3 — Windows Deep Dive

- Optional CDB/WinDbg adapter to maximize PDB/Windows features
- Symbol server support via `_NT_SYMBOL_PATH` and local cache hints
- Disassembly view improvements (Intel syntax, around PC)

## Milestone 4 — TUI (Optional)

- Textual-based TUI with panes: source, bt, locals, watches, console
- Mouse support and layout presets

## Milestone 5 — DAP & Extensibility

- Optional DAP client to leverage ecosystem adapters
- Plugin hooks for custom printers and commands

## Non-Goals (initially)

- Building projects (we assume you build separately, e.g., MSBuild/CMake)
- Kernel-mode debugging
- Remote debugging (considered later via adapter support)


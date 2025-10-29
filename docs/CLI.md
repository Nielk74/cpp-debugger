# CLI Design

The CLI favors small, clear commands and readable output. It supports both one-shot commands and an interactive shell mode.

## Global

- `debuger --version`
- `debuger --help`
- `debuger doctor` — checks environment (adapters found, PATH, symbol settings)

## Project Setup

- `debuger init` — create `debuger.yaml` with sensible defaults
- `debuger config` — print the resolved configuration

## Launch & Attach

- `debuger run` — launch target from `debuger.yaml`
- `debuger open <path-to-exe> [-- <args...>]` — launch explicit binary
- `debuger attach --pid <PID>` — attach to a running process
- Common options: `--cwd`, `--env KEY=VALUE`, `--debugger lldb|gdb|cdb`, `--break file:line`

## Core Debugging

- `debuger cont` — continue execution
- `debuger step` — step into
- `debuger next` — step over
- `debuger finish` — step out
- `debuger bt [--full]` — backtrace
- `debuger frames` — list frames; `debuger frame <N>` to select
- `debuger threads` — list threads; `debuger thread <ID>` to select
- `debuger regs` — show registers (current frame)
- `debuger disasm [--around]` — disassemble around the current PC
- `debuger eval <expr>` — evaluate expression in current frame

## Breakpoints & Watches

- `debuger bp add file:line` or `debuger bp add func` or `debuger bp add addr 0x...`
- `debuger bp ls` — list breakpoints
- `debuger bp rm <id>` — remove
- `debuger watch add <expr>` / `watch rm <id>` / `watch ls`

## Interactive Mode

- `debuger shell` — enter a REPL-like loop with the same commands
- Arrow-key history, `:help`, tab completion (stretch)

## Output Conventions

- Clean frames like: `#3  foo::bar(int) at src/foo.cpp:42`
- Demangled names by default, with `--mangled` to opt in
- Colors for file:line, function, address; minimal noise

## Examples

1) Run using project config:

```bash
debuger init
debuger run
```

2) Launch your Visual Studio debug build (example path):

```bash
debuger open "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1\\x64\\Debug\\ConsoleApplication1.exe"
```

3) Add a breakpoint and step:

```bash
debuger bp add src/main.cpp:12
debuger next
debuger step
debuger bt
```
## Analysis (Planned)

- `debuger analyze start [--since <ref> | --days <N> | --commits <N>]`
  - Begin tracing executed lines on stops/steps
- `debuger analyze stop`
- `debuger analyze report [--top N] [--group-by file|func] [--show-context] [--format table|json]`
- `debuger analyze clear`
- `debuger analyze export <file.json>`

Notes:
- Uses Git CLI to compute recent-change lines; supports path remapping via `debuger.yaml`.
- Tracing requires the integrated LLDB or bridge adapter (GDB MI support planned); lldb passthrough doesn’t support tracing.


# Git-Aware Analysis

Goal: accelerate debugging in large codebases by highlighting the intersection of executed lines and “recently modified” lines from Git.

## Problem

When tracking down regressions in a large C++ codebase, many lines execute between two points of interest. Manually scanning the entire path is slow. Often, the most relevant lines are those changed recently by you or your team.

## Concept

1) You place two breakpoints (start and end) and run the program.
2) `debuger` traces executed source locations between those breakpoints (or during an interval you choose).
3) It computes the set of “recently modified” lines from Git (since a ref, in the last N days, or N commits).
4) It intersects both sets and presents a focused report.

## CLI (planned)

- `debuger analyze start [--since <ref> | --days <N> | --commits <N>]`
  - Starts a trace session; future breakpoints/stepping will record executed (file:line)
- `debuger analyze stop`
  - Stops tracing and writes `.debuger/trace.json`
- `debuger analyze report [--top N] [--group-by file|func] [--show-context] [--format table|json]`
  - Shows the intersection of executed lines and recent changes
- `debuger analyze clear` — clears stored traces
- `debuger analyze export <path.json>` — exports raw execution and git-change sets

## Implementation Plan

### Execution Trace

- MVP: sample on each step operation and at each breakpoint stop.
  - Record current frame `(normalized_path, line)`, increment hit counts.
  - Data structure: `{ "exec": { "C:/path/file.cpp": { "12": 3, "13": 1 } } }`
- Trace Mode (Optional): single-step between start/end breakpoints for higher coverage (slower).
- Interactive convenience: `analyze start --sweep=N` will single-step N times from the current stop, recording hits automatically.
- Store at `.debuger/trace.json` within the project (merge on subsequent runs).

### Git “Recent Changes”

- Input options:
  - `--since <ref>`: `git diff <ref>..HEAD -U0` to collect changed line ranges.
  - `--days <N>`: `git log --since='N days ago' -p -U0`.
  - `--commits <N>`: `git log -n N -p -U0`.
- Parse hunks to build `{ file -> set(line_numbers) }`.
- Rename handling: use `--find-renames` and map to current paths; apply `sourceMap` if needed.
- Matching improvements: intersect by repo-relative paths when possible; otherwise, select the best candidate by longest trailing path match.

### Intersection & Report

- Normalize paths using `sourceMap` and `sourcePaths` from `debuger.yaml`.
- Intersect traced lines with the recent-change line sets.
- Sort by hit counts and recency, group by file and function.
- Optional: show source context; click-to-open via terminal integrations.

### Adapters & Hooks

- LLDB: use Python API to get current `LineEntry` on each stop/step; add a tracing toggle.
- GDB/MI: on `*stopped` events and `-exec-*` commands, sample current frame info.
- Pass-through lldb: limited to manual analysis (no API tracing); recommend bridge or Python-enabled LLDB.

### Storage & Settings

- `.debuger/trace.json` with friendly merge behavior.
- Respect `.gitignore`-like filters to avoid vendor paths.
- Config in `debuger.yaml` (planned):
  - `analyze.ignore: ["third_party/*", "build/**"]`
  - `analyze.defaultWindow: { commits: 50 }`

## Performance & Safety

- Step/breakpoint sampling is fast; full single-stepping is slower (explicit opt-in).
- Only reads Git metadata via `git` CLI; no network calls.
- No source code content is sent anywhere; results stay local.

## Stretch Ideas

- Heatmap overlay in TUI.
- “Blame-aware” filtering: only authors of interest.
- Confidence scoring that combines hits, recency, and call depth.

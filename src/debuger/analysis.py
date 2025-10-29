from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import DebugerConfig
from .paths import remap_source
from .state import SessionState


@dataclass
class ReportEntry:
    path: str
    line: int
    hits: int


def _git_root(cwd: Path) -> Path:
    try:
        cp = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if cp.returncode == 0:
            p = cp.stdout.strip()
            if p:
                return Path(p)
    except Exception:
        pass
    return cwd


def _parse_unified_diff(diff_text: str) -> Dict[str, set[int]]:
    # Collect added/modified line numbers per file from unified diff with -U0
    file_changes: Dict[str, set[int]] = {}
    cur_file: Optional[str] = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            cur_file = line[6:]
            file_changes.setdefault(cur_file, set())
        elif line.startswith("@@") and cur_file:
            # Example: @@ -a,b +c,d @@
            m = re.search(r"\+([0-9]+)(?:,([0-9]+))?", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2) or "1")
                for i in range(start, start + count):
                    file_changes[cur_file].add(i)
    return file_changes


def _git_recent_lines(cwd: Path, since: Optional[str] = None, days: Optional[int] = None, commits: Optional[int] = None) -> Dict[str, set[int]]:
    args: List[str]
    if since:
        args = ["git", "-C", str(cwd), "diff", "--no-color", "--find-renames", "-U0", f"{since}..HEAD"]
    elif days:
        args = ["git", "-C", str(cwd), "log", f"--since={days} days ago", "-p", "--no-color", "--find-renames", "-U0"]
    elif commits:
        args = ["git", "-C", str(cwd), "log", f"-n", str(commits), "-p", "--no-color", "--find-renames", "-U0"]
    else:
        # default: last 50 commits
        args = ["git", "-C", str(cwd), "log", "-n", "50", "-p", "--no-color", "--find-renames", "-U0"]

    try:
        cp = subprocess.run(args, capture_output=True, text=True)
        if cp.returncode != 0:
            return {}
        return _parse_unified_diff(cp.stdout)
    except Exception:
        return {}


def generate_report(project_root: Path, cfg: DebugerConfig, state: SessionState, since: Optional[str] = None, days: Optional[int] = None, commits: Optional[int] = None) -> List[ReportEntry]:
    if not state.trace:
        return []
    repo = _git_root(project_root)
    recent = _git_recent_lines(repo, since=since, days=days, commits=commits)
    # Map recent file paths through sourceMap if needed (inverse mapping not trivial — match by filename if necessary)
    # Build a lookup by filename as a fallback
    by_name: Dict[str, List[Tuple[str, set[int]]]] = {}
    for f, lines in recent.items():
        by_name.setdefault(Path(f).name.lower(), []).append((f, lines))

    entries: List[ReportEntry] = []
    for path, lines_map in state.trace.items():
        try:
            filename = Path(path).name.lower()
            candidates = by_name.get(filename, [])
            if not candidates:
                continue
            # pick the best candidate (first)
            _, changed_lines = candidates[0]
            for line_str, hits in lines_map.items():
                try:
                    ln = int(line_str)
                except ValueError:
                    continue
                if ln in changed_lines:
                    entries.append(ReportEntry(path=path, line=ln, hits=int(hits)))
        except Exception:
            continue

    # sort by hits desc then path, line
    entries.sort(key=lambda e: (-e.hits, e.path, e.line))
    return entries


def export_trace(project_root: Path, state: SessionState, out_path: Path) -> None:
    data = {
        "trace": state.trace,
    }
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


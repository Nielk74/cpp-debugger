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
    common_cfg = [
        "-c",
        "core.quotepath=false",  # print raw UTF-8 filenames
        "-c",
        "i18n.logOutputEncoding=UTF-8",
    ]
    if since:
        args = [
            "git",
            *common_cfg,
            "-C",
            str(cwd),
            "diff",
            "--no-color",
            "--find-renames",
            "-U0",
            f"{since}..HEAD",
        ]
    elif days:
        args = [
            "git",
            *common_cfg,
            "-C",
            str(cwd),
            "log",
            f"--since={days} days ago",
            "-p",
            "--no-color",
            "--find-renames",
            "-U0",
        ]
    elif commits:
        args = [
            "git",
            *common_cfg,
            "-C",
            str(cwd),
            "log",
            f"-n",
            str(commits),
            "-p",
            "--no-color",
            "--find-renames",
            "-U0",
        ]
    else:
        # default: last 50 commits
        args = [
            "git",
            *common_cfg,
            "-C",
            str(cwd),
            "log",
            "-n",
            "50",
            "-p",
            "--no-color",
            "--find-renames",
            "-U0",
        ]

    try:
        cp = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if cp.returncode != 0:
            # If a specific ref was requested and failed (e.g., no origin/main), fall back to a default window
            if since:
                fallback = [
                    "git",
                    *common_cfg,
                    "-C",
                    str(cwd),
                    "log",
                    "-n",
                    "50",
                    "-p",
                    "--no-color",
                    "--find-renames",
                    "-U0",
                ]
                cp2 = subprocess.run(fallback, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if cp2.returncode != 0:
                    return {}
                return _parse_unified_diff(cp2.stdout)
            return {}
        return _parse_unified_diff(cp.stdout)
    except Exception:
        return {}


def _rel_or_name(p: str, repo: Path) -> Tuple[str, str]:
    """Return (repo-relative path if under repo, filename) for matching."""
    try:
        rp = str(Path(p).resolve().relative_to(repo))
    except Exception:
        rp = Path(p).name
    return rp.replace("\\", "/"), Path(p).name.lower()


def _suffix_score(a: str, b: str) -> int:
    """Score paths by longest common suffix on components."""
    ap = a.replace("\\", "/").split("/")
    bp = b.replace("\\", "/").split("/")
    score = 0
    for xa, xb in zip(reversed(ap), reversed(bp)):
        if xa.lower() == xb.lower():
            score += 1
        else:
            break
    return score


def generate_report(project_root: Path, cfg: DebugerConfig, state: SessionState, since: Optional[str] = None, days: Optional[int] = None, commits: Optional[int] = None) -> List[ReportEntry]:
    if not state.trace:
        return []
    repo = _git_root(project_root)
    recent = _git_recent_lines(repo, since=since, days=days, commits=commits)
    # Build lookups by repo-relative path and filename
    by_rel: Dict[str, set[int]] = {}
    by_name: Dict[str, List[Tuple[str, set[int]]]] = {}
    for f, lines in recent.items():
        rel = f.replace("\\", "/")
        by_rel[rel] = lines
        by_name.setdefault(Path(f).name.lower(), []).append((rel, lines))

    entries: List[ReportEntry] = []
    for path, lines_map in state.trace.items():
        try:
            # Compute repo-relative and try direct match; else pick best suffix match
            rel_exec, filename = _rel_or_name(path, repo)
            changed_lines = by_rel.get(rel_exec)
            if changed_lines is None:
                candidates = by_name.get(filename, [])
                if not candidates:
                    continue
                # choose best by longest common suffix
                best = max(candidates, key=lambda c: _suffix_score(rel_exec, c[0]))
                changed_lines = best[1]
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

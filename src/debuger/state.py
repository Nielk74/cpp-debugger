from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


DEFAULT_DIRNAME = ".debuger"
DEFAULT_FILENAME = "session.json"


@dataclass
class BreakpointEntry:
    spec: str
    last_id: Optional[int] = None


@dataclass
class SessionState:
    breakpoints: List[BreakpointEntry] = field(default_factory=list)
    analyze_active: bool = False
    analyze_window: dict = field(default_factory=dict)  # {since|days|commits}
    trace: dict = field(default_factory=dict)  # { path: { line: count } }
    trace_events: List[dict] = field(default_factory=list)  # [{path,line,func,action,ts}]

    @classmethod
    def load(cls, root: Path) -> "SessionState":
        path = root / DEFAULT_DIRNAME / DEFAULT_FILENAME
        if not path.exists():
            return cls()
        try:
            # Use utf-8-sig to tolerate BOM from external editors/tools
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            bps = [BreakpointEntry(**bp) for bp in data.get("breakpoints", [])]
            st = cls(breakpoints=bps)
            st.analyze_active = bool(data.get("analyze_active", False))
            st.analyze_window = dict(data.get("analyze_window", {}))
            st.trace = dict(data.get("trace", {}))
            st.trace_events = list(data.get("trace_events", []))
            return st
        except Exception:
            return cls()

    def save(self, root: Path) -> None:
        dirp = root / DEFAULT_DIRNAME
        dirp.mkdir(parents=True, exist_ok=True)
        path = dirp / DEFAULT_FILENAME
        data = {
            "breakpoints": [asdict(bp) for bp in self.breakpoints],
            "analyze_active": self.analyze_active,
            "analyze_window": dict(self.analyze_window),
            "trace": self.trace,
            "trace_events": self.trace_events,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_bp(self, spec: str, bp_id: Optional[int]) -> None:
        self.breakpoints.append(BreakpointEntry(spec=spec, last_id=bp_id))

    def remove_bp_by_id(self, bp_id: int) -> None:
        # Best-effort: remove first matching id
        for i, bp in enumerate(self.breakpoints):
            if bp.last_id == bp_id:
                del self.breakpoints[i]
                return

    # Trace utilities
    def record_hit(self, path: str, line: int) -> None:
        if not path or not isinstance(line, int) or line <= 0:
            return
        # Clamp line into valid file range when possible to avoid bogus PDB line numbers
        try:
            from pathlib import Path
            p = Path(path)
            if p.exists():
                try:
                    # Read with tolerant encoding
                    total = sum(1 for _ in p.open("r", encoding="utf-8", errors="replace"))
                    if total > 0:
                        if line < 1:
                            line = 1
                        elif line > total:
                            line = total
                except Exception:
                    pass
        except Exception:
            pass
        file_map = self.trace.setdefault(path, {})
        file_map[str(line)] = int(file_map.get(str(line), 0)) + 1

    def record_event(self, path: str, line: int, func: Optional[str], action: str) -> None:
        try:
            from datetime import datetime
            ts = datetime.now().isoformat(timespec="seconds")
        except Exception:
            ts = ""
        # Clamp line similarly to record_hit
        if not path or not isinstance(line, int) or line <= 0:
            return
        try:
            p = Path(path)
            if p.exists():
                try:
                    total = sum(1 for _ in p.open("r", encoding="utf-8", errors="replace"))
                    if total > 0:
                        if line < 1:
                            line = 1
                        elif line > total:
                            line = total
                except Exception:
                    pass
        except Exception:
            pass
        self.trace_events.append({
            "path": path,
            "line": int(line),
            "func": func or "",
            "action": action,
            "ts": ts,
        })

    def clear_trace(self) -> None:
        self.trace = {}

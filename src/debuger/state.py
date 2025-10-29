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

    @classmethod
    def load(cls, root: Path) -> "SessionState":
        path = root / DEFAULT_DIRNAME / DEFAULT_FILENAME
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            bps = [BreakpointEntry(**bp) for bp in data.get("breakpoints", [])]
            st = cls(breakpoints=bps)
            st.analyze_active = bool(data.get("analyze_active", False))
            st.analyze_window = dict(data.get("analyze_window", {}))
            st.trace = dict(data.get("trace", {}))
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
        file_map = self.trace.setdefault(path, {})
        file_map[str(line)] = int(file_map.get(str(line), 0)) + 1

    def clear_trace(self) -> None:
        self.trace = {}

from __future__ import annotations

from typing import List, Optional

from . import BaseAdapter, AdapterError


class LldbAdapter(BaseAdapter):
    name = "lldb"

    def __init__(self) -> None:
        self._session_ready = False

    def launch(self, target: str, args: List[str] | None = None, cwd: Optional[str] = None, env: Optional[dict] = None, stop_at_entry: bool = False) -> None:
        # Placeholder: Real implementation will invoke lldb Python API
        self._session_ready = True
        raise AdapterError("LLDB adapter not implemented yet (MVP phase)")

    def attach(self, pid: int) -> None:
        self._session_ready = True
        raise AdapterError("LLDB adapter attach not implemented yet (MVP phase)")

    def shutdown(self) -> None:
        self._session_ready = False

    def continue_run(self) -> None:
        raise AdapterError("continue not implemented in LLDB adapter MVP")

    def step_in(self) -> None:
        raise AdapterError("step-in not implemented in LLDB adapter MVP")

    def step_over(self) -> None:
        raise AdapterError("step-over not implemented in LLDB adapter MVP")

    def step_out(self) -> None:
        raise AdapterError("step-out not implemented in LLDB adapter MVP")

    def backtrace(self, max_frames: Optional[int] = None) -> List[str]:
        return ["LLDB backtrace placeholder (adapter MVP)"]

    def frames(self) -> List[str]:
        return ["frame placeholder"]

    def threads(self) -> List[str]:
        return ["thread placeholder"]

    def bp_add(self, spec: str) -> int:
        raise AdapterError("breakpoints not implemented in LLDB adapter MVP")

    def bp_list(self) -> List[str]:
        return []

    def bp_remove(self, bp_id: int) -> None:
        raise AdapterError("breakpoint removal not implemented in LLDB adapter MVP")


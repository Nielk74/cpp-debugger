from __future__ import annotations

import os
import subprocess
from typing import List, Optional

from . import BaseAdapter, AdapterError


class LldbCliAdapter(BaseAdapter):
    name = "lldb-cli"
    is_passthrough = True  # indicates the CLI should hand over control

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen[str]] = None

    def _which_lldb(self) -> str:
        import shutil
        from pathlib import Path
        exe = shutil.which("lldb") or shutil.which("lldb.exe")
        if exe:
            return exe
        cand = Path("C:/Program Files/LLVM/bin/lldb.exe")
        if cand.exists():
            return str(cand)
        raise AdapterError("lldb executable not found")

    def launch(self, target: str, args: List[str] | None = None, cwd: Optional[str] = None, env: Optional[dict] = None, stop_at_entry: bool = False) -> None:
        exe = self._which_lldb()
        cmd: List[str] = [exe]
        if stop_at_entry:
            # Set a one-shot breakpoint on main instead of using stop-at-entry.
            cmd += ["-o", "breakpoint set --name main --one-shot true"]
        # Run program immediately under lldb; user interacts directly
        if args:
            cmd += [target, "--", *args]
        else:
            cmd += [target]
        proc_env = os.environ.copy()
        if env:
            proc_env.update({str(k): str(v) for k, v in env.items()})
        subprocess.call(cmd, cwd=cwd or None, env=proc_env)

    def attach(self, pid: int) -> None:
        exe = self._which_lldb()
        cmd = [exe, "-p", str(pid)]
        subprocess.call(cmd)

    # The remaining methods are not used in passthrough mode
    def shutdown(self) -> None:
        pass

    def continue_run(self) -> None:  # pragma: no cover - not used
        raise AdapterError("Not available in lldb CLI passthrough mode")

    def step_in(self) -> None:
        raise AdapterError("Not available in lldb CLI passthrough mode")

    def step_over(self) -> None:
        raise AdapterError("Not available in lldb CLI passthrough mode")

    def step_out(self) -> None:
        raise AdapterError("Not available in lldb CLI passthrough mode")

    def backtrace(self, max_frames: Optional[int] = None):
        return []

    def frames(self):
        return []

    def threads(self):
        return []

    def bp_add(self, spec: str) -> int:
        raise AdapterError("Not available in lldb CLI passthrough mode")

    def bp_list(self):
        return []

    def bp_remove(self, bp_id: int) -> None:
        raise AdapterError("Not available in lldb CLI passthrough mode")

    def read_stdio(self) -> tuple[str, str]:
        return "", ""

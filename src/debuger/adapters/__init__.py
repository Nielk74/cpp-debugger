from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import List, Optional, Protocol


class AdapterError(RuntimeError):
    pass


class BaseAdapter(Protocol):
    name: str

    # Lifecycle
    def launch(self, target: str, args: List[str] | None = None, cwd: Optional[str] = None, env: Optional[dict] = None, stop_at_entry: bool = False) -> None: ...
    def attach(self, pid: int) -> None: ...
    def shutdown(self) -> None: ...

    # Execution control
    def continue_run(self) -> None: ...
    def step_in(self) -> None: ...
    def step_over(self) -> None: ...
    def step_out(self) -> None: ...

    # Introspection
    def backtrace(self, max_frames: Optional[int] = None) -> List[str]: ...
    def frames(self) -> List[str]: ...
    def threads(self) -> List[str]: ...

    # Breakpoints
    def bp_add(self, spec: str) -> int: ...
    def bp_list(self) -> List[str]: ...
    def bp_remove(self, bp_id: int) -> None: ...


@dataclass
class AdapterInfo:
    key: str
    name: str
    available: bool
    detail: str


def detect_lldb() -> AdapterInfo:
    # Try Python module first
    try:
        import importlib
        importlib.import_module("lldb")  # type: ignore
        return AdapterInfo("lldb", "LLDB", True, "lldb Python module found")
    except Exception:
        pass
    # Try binary on PATH
    if shutil.which("lldb") or shutil.which("lldb.exe"):
        return AdapterInfo("lldb", "LLDB", True, "lldb executable found on PATH")
    # Common Windows install path
    from pathlib import Path
    lldb_exe = Path("C:/Program Files/LLVM/bin/lldb.exe")
    if lldb_exe.exists():
        return AdapterInfo("lldb", "LLDB", True, f"lldb executable found at {lldb_exe}")
    return AdapterInfo("lldb", "LLDB", False, "lldb not found")


def detect_gdb() -> AdapterInfo:
    if shutil.which("gdb") or shutil.which("gdb.exe"):
        return AdapterInfo("gdb", "GDB", True, "gdb found on PATH")
    return AdapterInfo("gdb", "GDB", False, "gdb not found")


def available_adapters() -> List[AdapterInfo]:
    return [detect_lldb(), detect_gdb()]


def get_adapter(preferred: Optional[str] = None) -> BaseAdapter:
    from .lldb_adapter import LldbAdapter
    from .gdb_mi_adapter import GdbMiAdapter
    from .lldb_cli_adapter import LldbCliAdapter

    pref = (preferred or "").lower() if preferred else None
    lldb_info = detect_lldb()
    gdb_info = detect_gdb()

    if pref == "lldb" and lldb_info.available:
        # Prefer Python API; fall back to CLI if import fails
        try:
            import importlib
            importlib.import_module("lldb")
            return LldbAdapter()
        except Exception:
            return LldbCliAdapter()
    if pref == "gdb" and gdb_info.available:
        return GdbMiAdapter()

    if lldb_info.available:
        try:
            import importlib
            importlib.import_module("lldb")
            return LldbAdapter()
        except Exception:
            return LldbCliAdapter()
    if gdb_info.available:
        return GdbMiAdapter()

    raise AdapterError("No debugger adapter available. Install LLVM (LLDB) or MinGW (GDB).")

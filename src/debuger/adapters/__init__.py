from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import List, Optional, Protocol
import os
import sys
import subprocess
from pathlib import Path
import sys
import os
from pathlib import Path
import subprocess


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

    # Optional advanced features (may raise AdapterError if unsupported)
    def eval(self, expr: str) -> str: ...
    def locals(self) -> List[str]: ...
    def regs(self) -> List[str]: ...
    def disasm(self, around: bool = True, count: int = 32) -> List[str]: ...
    def select_frame(self, index: int) -> None: ...
    def select_thread(self, tid: int) -> None: ...
    def current_location(self) -> tuple[Optional[str], Optional[int], Optional[str]]: ...


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


def _try_enable_lldb_python() -> bool:
    """Attempt to enable LLDB Python bindings by adjusting sys.path and PATH.

    - Adds `lldb -P` to sys.path if available
    - If python3X.dll is missing, prepends common locations (LLVM\bin and subdirs) to PATH
    Returns True if `import lldb` succeeds after adjustments.
    """
    # Add lldb's site-packages path
    exe = shutil.which("lldb") or shutil.which("lldb.exe") or str(Path("C:/Program Files/LLVM/bin/lldb.exe"))
    if exe and Path(exe).exists():
        try:
            cp = subprocess.run([exe, "-P"], capture_output=True, text=True)
            if cp.returncode == 0 and cp.stdout.strip():
                p = cp.stdout.strip()
                if p and p not in sys.path:
                    sys.path.insert(0, p)
        except Exception:
            pass
    # Ensure python runtime DLL is discoverable for _lldb.pyd
    candidates: List[Path] = []
    bin_dir = Path("C:/Program Files/LLVM/bin")
    if bin_dir.exists():
        candidates.append(bin_dir)
        for child in bin_dir.iterdir():
            if child.is_dir() and child.name.lower().startswith("python3"):
                candidates.append(child)
    # Also include directory of exe, if different
    if exe:
        exe_dir = Path(exe).parent
        if exe_dir.exists() and exe_dir not in candidates:
            candidates.append(exe_dir)
    # Look for python3*.dll
    for d in candidates:
        try:
            dlls = list(d.glob("python3*.dll"))
        except Exception:
            dlls = []
        if dlls:
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    # Try import now
    try:
        import importlib
        importlib.import_module("lldb")
        return True
    except Exception:
        return False


def get_adapter(preferred: Optional[str] = None) -> BaseAdapter:
    from .lldb_adapter import LldbAdapter
    from .gdb_mi_adapter import GdbMiAdapter
    from .lldb_cli_adapter import LldbCliAdapter
    from .lldb_bridge_adapter import LldbBridgeAdapter

    pref = (preferred or "").lower() if preferred else None
    lldb_info = detect_lldb()
    gdb_info = detect_gdb()

    if pref == "lldb" and lldb_info.available:
        # Try to enable Python bindings dynamically
        if _try_enable_lldb_python():
            return LldbAdapter()
        else:
            # Try embedded-python bridge
            try:
                return LldbBridgeAdapter()
            except Exception:
                return LldbCliAdapter()
    if pref == "gdb" and gdb_info.available:
        return GdbMiAdapter()

    if lldb_info.available:
        if _try_enable_lldb_python():
            return LldbAdapter()
        else:
            try:
                return LldbBridgeAdapter()
            except Exception:
                return LldbCliAdapter()
    if gdb_info.available:
        return GdbMiAdapter()

    raise AdapterError("No debugger adapter available. Install LLVM (LLDB) or MinGW (GDB).")

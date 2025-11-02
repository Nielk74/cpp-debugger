from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import List, Optional, Protocol
import os
import sys
import subprocess
from pathlib import Path


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
    def read_stdio(self) -> tuple[str, str]: ...


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
    """Attempt to enable LLDB Python bindings without assuming a fixed install path.

    Strategy:
    - Honor `LLDB_PYTHON_PATH` if set.
    - Use `lldb -P` from the lldb found on PATH.
    - Add DLL lookup dirs near the resolved `lldb` (bin and `python3*` subdirs) to PATH.
    - Fall back to well-known Windows locations only if needed.
    Returns True if `import lldb` succeeds after adjustments.
    """
    # 0) explicit override for site-packages
    override = os.environ.get("LLDB_PYTHON_PATH")
    if override and override not in sys.path and Path(override).exists():
        sys.path.insert(0, override)

    # 1) add lldb's site-packages path via `lldb -P`
    exe_path = shutil.which("lldb") or shutil.which("lldb.exe")
    if not exe_path:
        fallback = Path("C:/Program Files/LLVM/bin/lldb.exe")
        if fallback.exists():
            exe_path = str(fallback)
    if exe_path and Path(exe_path).exists():
        try:
            cp = subprocess.run([exe_path, "-P"], capture_output=True, text=True)
            if cp.returncode == 0 and cp.stdout.strip():
                p = cp.stdout.strip()
                if p and p not in sys.path:
                    sys.path.insert(0, p)
        except Exception:
            pass

    # 2) Ensure python runtime DLL is discoverable for _lldb.pyd
    candidates: List[Path] = []
    if exe_path:
        exe_dir = Path(exe_path).parent
        if exe_dir.exists():
            candidates.append(exe_dir)
            try:
                for child in exe_dir.iterdir():
                    if child.is_dir() and child.name.lower().startswith("python3"):
                        candidates.append(child)
            except Exception:
                pass
    # Also try classic Windows layout as a fallback only
    default_bin = Path("C:/Program Files/LLVM/bin")
    if default_bin.exists():
        candidates.append(default_bin)
        try:
            for child in default_bin.iterdir():
                if child.is_dir() and child.name.lower().startswith("python3"):
                    candidates.append(child)
        except Exception:
            pass
    for d in candidates:
        try:
            if list(d.glob("python3*.dll")):
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass
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
            # Never use CLI fallback; prefer the embedded-python bridge.
            return LldbBridgeAdapter()
    if pref == "gdb" and gdb_info.available:
        return GdbMiAdapter()

    if lldb_info.available:
        if _try_enable_lldb_python():
            return LldbAdapter()
        else:
            # Never use CLI fallback; prefer the embedded-python bridge.
            return LldbBridgeAdapter()
    if gdb_info.available:
        return GdbMiAdapter()

    raise AdapterError("No debugger adapter available. Install LLVM (LLDB) or MinGW (GDB).")

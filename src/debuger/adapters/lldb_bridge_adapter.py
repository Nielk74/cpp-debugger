from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import BaseAdapter, AdapterError


def _resolve_lldb_exe() -> Optional[Path]:
    """Find lldb executable, preferring PATH over hardcoded locations."""
    exe = shutil.which("lldb") or shutil.which("lldb.exe")
    if exe:
        return Path(exe)
    fallback = Path("C:/Program Files/LLVM/bin/lldb.exe")
    return fallback if fallback.exists() else None


def _lldb_python_path() -> Optional[str]:
    """Return LLDB's Python site-packages path.

    Order:
    1) LLDB_PYTHON_PATH env var if set
    2) `lldb -P` using the resolved lldb on PATH
    3) Paths relative to the lldb installation directory
    4) Last‑resort Windows defaults
    """
    # 1) explicit override
    env_override = os.environ.get("LLDB_PYTHON_PATH")
    if env_override and Path(env_override).exists():
        return env_override

    # 2) query lldb -P
    exe_path = _resolve_lldb_exe()
    if exe_path:
        try:
            cp = subprocess.run([str(exe_path), "-P"], capture_output=True, text=True)
            if cp.returncode == 0 and cp.stdout.strip():
                return cp.stdout.strip()
        except Exception:
            pass

    # 3) try relative locations next to lldb.exe/bin
    candidates: List[Path] = []
    if exe_path:
        root = exe_path.parent.parent  # …/LLVM
        pyver = f"python{sys.version_info.major}{sys.version_info.minor}"
        candidates.extend(
            [
                root / "lib" / "site-packages",
                root / "Lib" / "site-packages",
                root / "lib" / pyver / "site-packages",
            ]
        )

    # 4) Windows defaults (keep as a final fallback)
    candidates.extend(
        [
            Path("C:/Program Files/LLVM/lib/site-packages"),
            Path("C:/Program Files/LLVM/Lib/site-packages"),
        ]
    )

    for c in candidates:
        try:
            if c.exists():
                return str(c)
        except Exception:
            continue
    return None


def _find_embedded_python() -> Optional[Path]:
    """Locate an embedded Python near the LLDB install, if present.

    Searches the lldb.exe directory and immediate `python3*` subfolders
    for a `python.exe`. This supports non-default LLVM install roots
    discovered via PATH.
    """
    exe_path = _resolve_lldb_exe()
    search_dirs: List[Path] = []
    if exe_path:
        bin_dir = exe_path.parent
        search_dirs.append(bin_dir)
        try:
            for sub in bin_dir.iterdir():
                if sub.is_dir() and sub.name.lower().startswith("python3"):
                    search_dirs.append(sub)
        except Exception:
            pass
    else:
        default_bin = Path("C:/Program Files/LLVM/bin")
        if default_bin.exists():
            search_dirs.append(default_bin)
            try:
                for sub in default_bin.iterdir():
                    if sub.is_dir() and sub.name.lower().startswith("python3"):
                        search_dirs.append(sub)
            except Exception:
                pass

    for d in search_dirs:
        cand = d / "python.exe"
        if cand.exists():
            return cand
    return None


class LldbBridgeAdapter(BaseAdapter):
    name = "lldb-bridge"

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen[str]] = None
        self._next_id = 1
        self._lock = threading.Lock()

    def _start(self) -> None:
        if self._proc is not None:
            return
        # Prefer embedded python next to lldb; fall back to current interpreter
        py = _find_embedded_python() or Path(sys.executable)
        lldb_p = _lldb_python_path()
        if not lldb_p:
            raise AdapterError("Could not determine LLDB Python path (lldb -P or relative lib)")
        env = os.environ.copy()
        env["PYTHONPATH"] = lldb_p + os.pathsep + env.get("PYTHONPATH", "")

        # Ensure loader finds python3X.dll used by _lldb.pyd by adding likely
        # directories near lldb.exe to PATH (no-op if absent).
        exe_path = _resolve_lldb_exe()
        if exe_path:
            bin_dir = exe_path.parent
            dll_dirs: List[Path] = [bin_dir]
            try:
                for sub in bin_dir.iterdir():
                    if sub.is_dir() and sub.name.lower().startswith("python3"):
                        dll_dirs.append(sub)
            except Exception:
                pass
            for d in dll_dirs:
                try:
                    if list(d.glob("python3*.dll")):
                        env["PATH"] = str(d) + os.pathsep + env.get("PATH", "")
                except Exception:
                    pass
        # Invoke server script by file path so embedded Python doesn't need package imports pre-configured
        server = Path(__file__).resolve().parents[1] / "bridge" / "lldb_server.py"
        cmd = [str(py), "-u", str(server)]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            # Drain stderr to avoid child blocking and forward diagnostics
            if self._proc.stderr is not None:
                def _drain_err(pipe):
                    try:
                        for ln in pipe:
                            try:
                                sys.stderr.write(ln)
                            except Exception:
                                pass
                    except Exception:
                        pass
                t = threading.Thread(target=_drain_err, args=(self._proc.stderr,), daemon=True)
                t.start()
        except Exception as e:
            raise AdapterError(f"Failed to start LLDB bridge: {e}")

    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._start()
        assert self._proc and self._proc.stdin and self._proc.stdout
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            msg = json.dumps({"id": rid, "method": method, "params": params or {}})
            self._proc.stdin.write(msg + "\n")
            self._proc.stdin.flush()
            # Read lines until we get a valid JSON response with matching id
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    raise AdapterError("bridge closed pipe")
                try:
                    resp = json.loads(line)
                except Exception:
                    # Skip non-JSON noise on stdout
                    continue
                if resp.get("id") != rid:
                    # Skip out-of-band messages
                    continue
                if "error" in resp and resp["error"]:
                    err = resp["error"]
                    raise AdapterError(err.get("message") or "bridge error")
                return resp.get("result")

    # BaseAdapter methods delegating to bridge
    def launch(self, target: str, args: List[str] | None = None, cwd: Optional[str] = None, env: Optional[dict] = None, stop_at_entry: bool = False) -> None:
        self._rpc("launch", {"target": target, "args": args, "cwd": cwd, "env": env, "stop_at_entry": stop_at_entry})

    def attach(self, pid: int) -> None:
        self._rpc("attach", {"pid": pid})

    def shutdown(self) -> None:
        try:
            self._rpc("shutdown")
        finally:
            if self._proc:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
            self._proc = None

    def continue_run(self) -> None:
        self._rpc("continue_run")

    def step_in(self) -> None:
        self._rpc("step_in")

    def step_over(self) -> None:
        self._rpc("step_over")

    def step_out(self) -> None:
        self._rpc("step_out")

    def backtrace(self, max_frames: Optional[int] = None) -> List[str]:
        return list(self._rpc("backtrace", {"max_frames": max_frames}))

    def frames(self) -> List[str]:
        return list(self._rpc("frames"))

    def threads(self) -> List[str]:
        return list(self._rpc("threads"))

    def bp_add(self, spec: str) -> int:
        return int(self._rpc("bp_add", {"spec": spec}))

    def bp_list(self) -> List[str]:
        return list(self._rpc("bp_list"))

    def bp_remove(self, bp_id: int) -> None:
        self._rpc("bp_remove", {"bp_id": bp_id})

    def eval(self, expr: str) -> str:
        return str(self._rpc("eval", {"expr": expr}))

    def locals(self) -> List[str]:
        return list(self._rpc("locals"))

    def regs(self) -> List[str]:
        return list(self._rpc("regs"))

    def disasm(self, around: bool = True, count: int = 32) -> List[str]:
        return list(self._rpc("disasm", {"around": around, "count": count}))

    def select_frame(self, index: int) -> None:
        self._rpc("select_frame", {"index": index})

    def select_thread(self, tid: int) -> None:
        self._rpc("select_thread", {"tid": tid})

    def current_location(self) -> tuple[Optional[str], Optional[int], Optional[str]]:
        res = self._rpc("current_location")
        if isinstance(res, list):
            path, line, func = (res + [None, None, None])[:3]
            return (path, line, func)
        if isinstance(res, tuple):
            return res  # type: ignore[return-value]
        # Map dict
        if isinstance(res, dict):
            return (res.get("path"), res.get("line"), res.get("func"))  # type: ignore[return-value]
        return (None, None, None)

    def read_stdio(self) -> tuple[str, str]:
        res = self._rpc("read_stdio")
        if isinstance(res, (list, tuple)):
            out = res[0] if len(res) > 0 else ""
            err = res[1] if len(res) > 1 else ""
            return (str(out or ""), str(err or ""))
        if isinstance(res, dict):
            return (str(res.get("0") or res.get("out") or ""), str(res.get("1") or res.get("err") or ""))
        return ("", "")

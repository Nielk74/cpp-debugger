from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import BaseAdapter, AdapterError


def _lldb_python_path() -> Optional[str]:
    import shutil
    exe = shutil.which("lldb") or shutil.which("lldb.exe")
    if not exe:
        exe = str(Path("C:/Program Files/LLVM/bin/lldb.exe"))
    try:
        cp = subprocess.run([exe, "-P"], capture_output=True, text=True)
        if cp.returncode == 0 and cp.stdout.strip():
            return cp.stdout.strip()
    except Exception:
        pass
    # Fallback
    candidates = [
        "C:/Program Files/LLVM/Lib/site-packages",
        "C:/Program Files/LLVM/lib/site-packages",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _find_embedded_python() -> Optional[Path]:
    bin_dir = Path("C:/Program Files/LLVM/bin")
    py = bin_dir / "python.exe"
    if py.exists():
        return py
    # search subfolders like python310/python.exe
    for sub in bin_dir.iterdir():
        if sub.is_dir() and sub.name.startswith("python3"):
            cand = sub / "python.exe"
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
        py = _find_embedded_python()
        if not py:
            raise AdapterError("Embedded Python interpreter not found under LLVM/bin")
        lldb_p = _lldb_python_path()
        if not lldb_p:
            raise AdapterError("Could not determine LLDB Python path (lldb -P)")
        env = os.environ.copy()
        env["PYTHONPATH"] = lldb_p + ";" + env.get("PYTHONPATH", "")
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
            # Read one response line
            line = self._proc.stdout.readline()
            if not line:
                raise AdapterError("bridge closed pipe")
            resp = json.loads(line)
            if resp.get("id") != rid:
                raise AdapterError("out-of-sync response from bridge")
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

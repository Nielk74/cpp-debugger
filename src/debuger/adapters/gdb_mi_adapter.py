from __future__ import annotations

from typing import List, Optional
import subprocess
import threading
import queue
import os
import time

from . import BaseAdapter, AdapterError


class _Mi:
    def __init__(self, exe: str = "gdb") -> None:
        try:
            self.proc = subprocess.Popen(
                [exe, "--interpreter=mi2"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:
            raise AdapterError("gdb not found on PATH") from e
        self.q: "queue.Queue[str]" = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self._tok = 1

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.q.put(line.rstrip())

    def cmd(self, command: str, timeout: float = 5.0) -> List[str]:
        if not self.proc.stdin:
            raise AdapterError("gdb stdin unavailable")
        tok = self._tok
        self._tok += 1
        msg = f"{tok}{command}\n"
        self.proc.stdin.write(msg)
        self.proc.stdin.flush()
        lines: List[str] = []
        start = time.time()
        while True:
            try:
                line = self.q.get(timeout=timeout)
                lines.append(line)
                if line.startswith(f"{tok}^"):
                    break
            except queue.Empty:
                if time.time() - start > timeout:
                    raise AdapterError(f"gdb command timeout: {command}")
        return lines

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.write("-gdb-exit\n")
                self.proc.stdin.flush()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


def _parse_kv_list(payload: str, key: str) -> List[dict]:
    # Very light-weight parser for responses like: key=[frame={...},frame={...}]
    out: List[dict] = []
    idx = payload.find(key + "=")
    if idx == -1:
        return out
    s = payload[idx + len(key) + 1 :]
    if not s.startswith("["):
        return out
    # crude tokenizer
    cur: dict = {}
    token = ""
    field = None
    depth = 0
    for ch in s:
        if ch == "{" and depth == 0:
            cur = {}
            field = None
            token = ""
            depth = 1
        elif ch == "}" and depth == 1:
            if field:
                cur[field] = token.strip('"')
            out.append(cur)
            field = None
            token = ""
            depth = 0
        elif depth == 1:
            if ch == "=":
                field = token
                token = ""
            elif ch == ",":
                if field:
                    cur[field] = token.strip('"')
                    field = None
                    token = ""
            else:
                token += ch
        elif ch == "]":
            break
    return out


class GdbMiAdapter(BaseAdapter):
    name = "gdb"

    def __init__(self) -> None:
        self._mi: Optional[_Mi] = None
        self._session_ready = False

    def _ensure(self) -> _Mi:
        if not self._mi:
            self._mi = _Mi("gdb")
        return self._mi

    def launch(self, target: str, args: List[str] | None = None, cwd: Optional[str] = None, env: Optional[dict] = None, stop_at_entry: bool = False) -> None:
        mi = self._ensure()
        if cwd:
            mi.cmd(f"-environment-cd {cwd}")
        mi.cmd(f"-file-exec-and-symbols {target}")
        if stop_at_entry:
            mi.cmd("-break-insert main")
        if env:
            for k, v in env.items():
                mi.cmd(f"-gdb-set environment {k}={v}")
        if args:
            # gdb MI will accept args via -exec-arguments
            mi.cmd("-exec-arguments " + " ".join(args))
        mi.cmd("-exec-run")
        self._session_ready = True

    def attach(self, pid: int) -> None:
        mi = self._ensure()
        mi.cmd(f"-target-attach {pid}")
        self._session_ready = True

    def shutdown(self) -> None:
        if self._mi:
            self._mi.close()
        self._mi = None
        self._session_ready = False

    def continue_run(self) -> None:
        mi = self._ensure()
        mi.cmd("-exec-continue")

    def step_in(self) -> None:
        mi = self._ensure()
        mi.cmd("-exec-step")

    def step_over(self) -> None:
        mi = self._ensure()
        mi.cmd("-exec-next")

    def step_out(self) -> None:
        mi = self._ensure()
        mi.cmd("-exec-finish")

    def backtrace(self, max_frames: Optional[int] = None) -> List[str]:
        mi = self._ensure()
        res = mi.cmd("-stack-list-frames")
        payload = "\n".join(res)
        frames = _parse_kv_list(payload, "stack")
        out: List[str] = []
        for i, fr in enumerate(frames):
            func = fr.get("func") or fr.get("fullname") or fr.get("addr") or "(unknown)"
            file = fr.get("file") or fr.get("fullname")
            line = fr.get("line")
            if file and line:
                out.append(f"#{i}  {func} at {file}:{line}")
            else:
                out.append(f"#{i}  {func}")
            if max_frames is not None and i + 1 >= max_frames:
                break
        return out

    def frames(self) -> List[str]:
        return self.backtrace()

    def threads(self) -> List[str]:
        mi = self._ensure()
        res = mi.cmd("-thread-info")
        payload = "\n".join(res)
        threads = _parse_kv_list(payload, "threads")
        out: List[str] = []
        for t in threads:
            tid = t.get("id") or t.get("target-id") or "?"
            out.append(str(tid))
        return out

    def bp_add(self, spec: str) -> int:
        mi = self._ensure()
        res = mi.cmd(f"-break-insert {spec}")
        # Parse id from response like: ^done,bkpt={number="1",...}
        text = "\n".join(res)
        idx = text.find("number=\"")
        if idx != -1:
            end = text.find("\"", idx + 8)
            if end != -1:
                try:
                    return int(text[idx + 8 : end])
                except ValueError:
                    pass
        raise AdapterError("failed to create breakpoint")

    def bp_list(self) -> List[str]:
        mi = self._ensure()
        res = mi.cmd("-break-list")
        payload = "\n".join(res)
        bkpts = _parse_kv_list(payload, "BreakpointTable")
        if not bkpts:
            return []
        # MI returns nested structures; keep simple fallback
        return [line for line in payload.splitlines() if "bkpt" in line]

    def bp_remove(self, bp_id: int) -> None:
        mi = self._ensure()
        mi.cmd(f"-break-delete {bp_id}")

    # Optional features (basic or unsupported)
    def eval(self, expr: str) -> str:
        mi = self._ensure()
        res = mi.cmd(f"-data-evaluate-expression {expr}")
        text = "\n".join(res)
        idx = text.find('value="')
        if idx != -1:
            end = text.find('"', idx + 7)
            if end != -1:
                return text[idx + 7 : end]
        raise AdapterError("evaluation failed")

    def locals(self) -> List[str]:
        mi = self._ensure()
        res = mi.cmd("-stack-list-variables --all-values")
        payload = "\n".join(res)
        vars = _parse_kv_list(payload, "variables")
        return [f"{v.get('name','?')} = {v.get('value','?')}" for v in vars]

    def regs(self) -> List[str]:
        # Not implemented in this minimal adapter
        raise AdapterError("registers not supported in minimal GDB adapter")

    def disasm(self, around: bool = True, count: int = 32) -> List[str]:
        mi = self._ensure()
        # Use current frame address
        res = mi.cmd("-data-evaluate-expression $pc")
        text = "\n".join(res)
        addr = None
        idx = text.find('value="')
        if idx != -1:
            end = text.find('"', idx + 7)
            if end != -1:
                addr = text[idx + 7 : end]
        if not addr:
            raise AdapterError("cannot determine PC")
        # Disassemble around PC
        res = mi.cmd(f"-data-disassemble -s {addr} -e {addr}+{count*8} -- 1")
        return [line for line in ("\n".join(res)).splitlines() if line.strip()]

    def select_frame(self, index: int) -> None:
        mi = self._ensure()
        mi.cmd(f"-stack-select-frame {index}")

    def select_thread(self, tid: int) -> None:
        mi = self._ensure()
        mi.cmd(f"-thread-select {tid}")

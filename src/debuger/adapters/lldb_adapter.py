from __future__ import annotations

from typing import List, Optional

from . import BaseAdapter, AdapterError


class LldbAdapter(BaseAdapter):
    name = "lldb"

    def __init__(self) -> None:
        self._session_ready = False
        self._lldb = None
        self._debugger = None
        self._target = None
        self._process = None

    # Internal helpers
    def _require(self):
        try:
            import lldb  # type: ignore
            return lldb
        except Exception:
            pass
        # Try to discover LLDB Python path (Windows installs)
        import sys
        import os
        import shutil as _shutil
        from pathlib import Path
        cand: list[Path] = []
        # 1) lldb -P
        exe = _shutil.which("lldb") or _shutil.which("lldb.exe")
        if exe:
            try:
                import subprocess
                out = subprocess.check_output([exe, "-P"], text=True, stderr=subprocess.DEVNULL).strip()
                if out:
                    cand.append(Path(out))
            except Exception:
                pass
        # 2) Common LLVM locations
        pyver = f"python{sys.version_info.major}{sys.version_info.minor}"
        common = [
            Path("C:/Program Files/LLVM/lib/site-packages"),
            Path(f"C:/Program Files/LLVM/lib/{pyver}/site-packages"),
            Path("/usr/lib/python3/dist-packages"),
            Path("/usr/local/lib/python3/dist-packages"),
        ]
        for p in common:
            if p.exists():
                cand.append(p)
        # Extend sys.path and retry
        for p in cand:
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
                try:
                    import lldb  # type: ignore
                    return lldb
                except Exception:
                    continue
        raise AdapterError(
            "LLDB Python module not available. Add LLDB's site-packages to PYTHONPATH or install LLVM with LLDB bindings."
        )

    def _ensure_debugger(self):
        if self._debugger is None:
            lldb = self._require()
            dbg = lldb.SBDebugger.Create()
            dbg.SetAsync(False)
            self._lldb = lldb
            self._debugger = dbg

    def _state_str(self) -> str:
        if not self._lldb or not self._process:
            return "unknown"
        lldb = self._lldb
        state = self._process.state
        return {
            lldb.eStateStopped: "stopped",
            lldb.eStateRunning: "running",
            lldb.eStateExited: "exited",
            lldb.eStateCrashed: "crashed",
            lldb.eStateSuspended: "suspended",
        }.get(state, str(state))

    def launch(self, target: str, args: List[str] | None = None, cwd: Optional[str] = None, env: Optional[dict] = None, stop_at_entry: bool = False) -> None:
        lldb = self._require()
        self._ensure_debugger()
        dbg = self._debugger
        assert dbg is not None

        tgt = dbg.CreateTarget(target)
        if not tgt or not tgt.IsValid():
            raise AdapterError(f"Failed to create LLDB target for {target}")

        if stop_at_entry:
            # Break in main or entry
            br = tgt.BreakpointCreateByName("main")
            if not br or not br.IsValid():
                # Not fatal
                pass

        launch_info = lldb.SBLaunchInfo(args or [])
        launch_info.SetWorkingDirectory(cwd or "")
        if env:
            env_list = [f"{k}={v}" for k, v in env.items()]
            launch_info.SetEnvironmentEntries(env_list, True)

        error = lldb.SBError()
        proc = tgt.Launch(launch_info, error)
        if not error.Success():
            raise AdapterError(f"LLDB launch failed: {error.GetCString()}")

        self._target = tgt
        self._process = proc
        self._session_ready = True

    def attach(self, pid: int) -> None:
        lldb = self._require()
        self._ensure_debugger()
        dbg = self._debugger
        assert dbg is not None

        error = lldb.SBError()
        tgt = dbg.CreateTarget(None)
        proc = tgt.AttachToProcessWithID(dbg.GetListener(), pid, error)
        if not error.Success():
            raise AdapterError(f"LLDB attach failed: {error.GetCString()}")

        self._target = tgt
        self._process = proc
        self._session_ready = True

    def shutdown(self) -> None:
        try:
            if self._process and self._process.IsValid():
                self._process.Destroy()
        finally:
            if self._debugger is not None and self._lldb is not None:
                self._lldb.SBDebugger.Destroy(self._debugger)
        self._process = None
        self._target = None
        self._debugger = None
        self._lldb = None
        self._session_ready = False

    def _selected_thread(self):
        if not self._process:
            raise AdapterError("No active process")
        th = self._process.selected_thread
        if not th or not th.IsValid():
            # fallback to first thread
            th = self._process.GetThreadAtIndex(0)
        return th

    def continue_run(self) -> None:
        if not self._process:
            raise AdapterError("No active process")
        self._process.Continue()

    def step_in(self) -> None:
        th = self._selected_thread()
        th.StepInto()

    def step_over(self) -> None:
        th = self._selected_thread()
        th.StepOver()

    def step_out(self) -> None:
        th = self._selected_thread()
        th.StepOut()

    def backtrace(self, max_frames: Optional[int] = None) -> List[str]:
        th = self._selected_thread()
        n = th.num_frames
        out: List[str] = []
        for i in range(n if max_frames is None else min(n, max_frames)):
            fr = th.GetFrameAtIndex(i)
            func = fr.GetFunctionName() or "(unknown)"
            file_spec = fr.GetLineEntry().GetFileSpec()
            file_name = file_spec.GetFilename() if file_spec else None
            line = fr.GetLineEntry().GetLine()
            if file_name and line:
                out.append(f"#{i}  {func} at {file_name}:{line}")
            else:
                out.append(f"#{i}  {func}")
        return out

    def frames(self) -> List[str]:
        th = self._selected_thread()
        out: List[str] = []
        for i in range(th.num_frames):
            fr = th.GetFrameAtIndex(i)
            func = fr.GetFunctionName() or "(unknown)"
            file_spec = fr.GetLineEntry().GetFileSpec()
            file_name = file_spec.GetFilename() if file_spec else None
            line = fr.GetLineEntry().GetLine()
            if file_name and line:
                out.append(f"{i}: {func} at {file_name}:{line}")
            else:
                out.append(f"{i}: {func}")
        return out

    def threads(self) -> List[str]:
        if not self._process:
            raise AdapterError("No active process")
        out: List[str] = []
        for i in range(self._process.GetNumThreads()):
            th = self._process.GetThreadAtIndex(i)
            out.append(f"{th.GetThreadID()} {th.GetName() or ''} state={self._state_str()}")
        return out

    def bp_add(self, spec: str) -> int:
        if not self._target:
            raise AdapterError("No active target")
        # file:line or function name
        bp = None
        if ":" in spec and spec.split(":")[-1].isdigit():
            file, line_s = spec.rsplit(":", 1)
            try:
                line = int(line_s)
            except ValueError as e:
                raise AdapterError("Invalid breakpoint line") from e
            bp = self._target.BreakpointCreateByLocation(file, line)
        else:
            bp = self._target.BreakpointCreateByName(spec)
        if not bp or not bp.IsValid():
            raise AdapterError(f"Failed to create breakpoint for '{spec}'")
        return bp.GetID()

    def bp_list(self) -> List[str]:
        if not self._target:
            raise AdapterError("No active target")
        out: List[str] = []
        for i in range(self._target.GetNumBreakpoints()):
            bp = self._target.GetBreakpointAtIndex(i)
            out.append(f"{bp.GetID()} {bp.GetNumLocations()} locs enabled={bp.IsEnabled()}")
        return out

    def bp_remove(self, bp_id: int) -> None:
        if not self._target:
            raise AdapterError("No active target")
        self._target.BreakpointDelete(bp_id)

    # Advanced features
    def eval(self, expr: str) -> str:
        th = self._selected_thread()
        fr = th.GetFrameAtIndex(0)
        val = fr.EvaluateExpression(expr)
        if not val.IsValid():
            raise AdapterError("evaluation failed")
        return val.GetValue() or val.GetSummary() or str(val)

    def locals(self) -> List[str]:
        th = self._selected_thread()
        fr = th.GetFrameAtIndex(0)
        out: List[str] = []
        vars = fr.GetVariables(True, True, False, True)
        for i in range(vars.GetSize()):
            v = vars.GetValueAtIndex(i)
            name = v.GetName() or "?"
            summary = v.GetSummary()
            value = v.GetValue()
            disp = summary or value or "?"
            out.append(f"{name} = {disp}")
        return out

    def regs(self) -> List[str]:
        th = self._selected_thread()
        fr = th.GetFrameAtIndex(0)
        out: List[str] = []
        reg_sets = fr.GetRegisters()
        for i in range(reg_sets.GetSize()):
            rs = reg_sets.GetValueAtIndex(i)
            for j in range(rs.GetNumChildren()):
                r = rs.GetChildAtIndex(j)
                out.append(f"{r.GetName()} = {r.GetValue()}")
        return out

    def disasm(self, around: bool = True, count: int = 32) -> List[str]:
        th = self._selected_thread()
        fr = th.GetFrameAtIndex(0)
        insts = fr.GetFunction().GetInstructions(self._target)
        out: List[str] = []
        pc_addr = fr.GetPCAddress()
        # Fallback if function unknown
        if not insts or insts.GetSize() == 0:
            insn = self._target.ReadInstructions(pc_addr, count)
            for ins in insn:
                out.append(str(ins))
            return out
        # Find index around current PC
        idx_pc = 0
        for idx in range(insts.GetSize()):
            if insts.GetInstructionAtIndex(idx).GetAddress() == pc_addr:
                idx_pc = idx
                break
        start = max(0, idx_pc - count // 2) if around else idx_pc
        end = min(insts.GetSize(), start + count)
        for idx in range(start, end):
            ins = insts.GetInstructionAtIndex(idx)
            prefix = "=> " if idx == idx_pc else "   "
            out.append(prefix + str(ins))
        return out

    def select_frame(self, index: int) -> None:
        th = self._selected_thread()
        th.SetSelectedFrame(index)

    def select_thread(self, tid: int) -> None:
        if not self._process:
            raise AdapterError("No active process")
        for i in range(self._process.GetNumThreads()):
            th = self._process.GetThreadAtIndex(i)
            if th.GetThreadID() == tid:
                self._process.SetSelectedThread(th)
                return
        raise AdapterError(f"thread {tid} not found")

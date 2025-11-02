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
        self._stdout_file = None
        self._stderr_file = None
        self._stdout_pos = 0
        self._stderr_pos = 0

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
            # Redirect LLDB output away from stdout so the bridge JSON channel stays clean
            try:
                import sys as _sys, os as _os  # local import to avoid top-level deps
                # Prefer stderr; use binary buffer if available
                _fh = getattr(_sys.stderr, "buffer", _sys.stderr)
                try:
                    dbg.SetOutputFileHandle(_fh, False)  # type: ignore[attr-defined]
                    dbg.SetErrorFileHandle(_fh, False)   # type: ignore[attr-defined]
                except Exception:
                    # Fallback: silence to devnull if handle APIs differ on this LLDB build
                    try:
                        _dev = open(_os.devnull, "wb")
                        try:
                            dbg.SetOutputFileHandle(_dev, True)  # transfer ownership
                            dbg.SetErrorFileHandle(_dev, True)
                        except Exception:
                            # Last resort: ignore
                            pass
                    except Exception:
                        pass
            except Exception:
                pass
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

        # Proactively disable any preconfigured exception breakpoints to avoid
        # stopping on language/runtime exceptions.
        try:
            for i in range(tgt.GetNumBreakpoints()):
                bp_i = tgt.GetBreakpointAtIndex(i)
                try:
                    desc = self._lldb.SBStream() if self._lldb else None
                    if desc is not None and bp_i.GetDescription(desc):
                        if "exception" in (desc.GetData() or "").lower():
                            bp_i.SetEnabled(False)
                except Exception:
                    pass
        except Exception:
            pass

        # Prefer stopping at 'main' via a breakpoint rather than using
        # LLDB's stop-at-entry flag. This avoids halting before CRT startup
        # and ensures we land on the first location in main.
        if stop_at_entry:
            br = tgt.BreakpointCreateByName("main")
            bp_set = False
            try:
                if br and br.IsValid():
                    br.SetOneShot(True)
                    bp_set = True
                    import sys
                    sys.stderr.write(f"[debuger] Breakpoint set on 'main' (ID: {br.GetID()})\n")
                    sys.stderr.flush()
                else:
                    import sys
                    sys.stderr.write(f"[debuger] Warning: Failed to set breakpoint on 'main', trying regex fallback\n")
                    sys.stderr.flush()
            except Exception as e:
                import sys
                sys.stderr.write(f"[debuger] Warning: Exception setting breakpoint on 'main': {e}\n")
                sys.stderr.flush()
            # Fallback: source-regex breakpoint that matches typical C/C++ mains
            if not bp_set:
                try:
                    regex = r"^\s*(int|auto|void)\s+main\s*\("
                    fslist = lldb.SBFileSpecList()
                    br2 = tgt.BreakpointCreateBySourceRegex(regex, fslist)
                    if br2 and br2.IsValid():
                        try:
                            br2.SetOneShot(True)
                            import sys
                            sys.stderr.write(f"[debuger] Regex breakpoint set on main pattern (ID: {br2.GetID()})\n")
                            sys.stderr.flush()
                        except Exception:
                            pass
                    else:
                        import sys
                        sys.stderr.write(f"[debuger] Warning: Regex breakpoint on main pattern also failed\n")
                        sys.stderr.flush()
                except Exception as e:
                    import sys
                    sys.stderr.write(f"[debuger] Warning: Exception setting regex breakpoint: {e}\n")
                    sys.stderr.flush()

        launch_info = lldb.SBLaunchInfo(args or [])
        # Never use LLDB's stop-at-entry; we explicitly breakpoint on main.
        try:
            launch_info.SetStopAtEntry(False)
        except Exception:
            # Older LLDB builds may not support this setter; ignore.
            pass
        try:
            flags = launch_info.GetLaunchFlags()
            inherit_flag = getattr(lldb, "eLaunchFlagInheritTTY", None)
            disable_stdio = getattr(lldb, "eLaunchFlagDisableSTDIO", None)

            # Capture STDIO via LLDB so we can relay it through read_stdio.
            # Ensure STDIO is NOT disabled.
            if disable_stdio is not None and (flags & disable_stdio):
                flags &= ~disable_stdio

            # On Windows, we may need to ENABLE InheritTTY for GetSTDOUT/ERR to work
            # Since file redirection APIs don't exist on some LLDB builds, we rely on TTY inheritance as backup
            if inherit_flag is not None:
                if not (flags & inherit_flag):
                    flags |= inherit_flag

            launch_info.SetLaunchFlags(flags)
        except Exception:
            # Be resilient if flags API differs across LLDB builds.
            pass
        launch_info.SetWorkingDirectory(cwd or "")
        if env:
            env_list = [f"{k}={v}" for k, v in env.items()]
            launch_info.SetEnvironmentEntries(env_list, True)

        # On some Windows LLDB builds, GetSTDOUT/ERR may not stream reliably.
        # Redirect inferior stdout/stderr to temp files and tail them from read_stdio.
        stdio_redirect_method = None
        try:
            import tempfile, os as _os
            # Create unique temp files per launch
            fd_out, out_path = tempfile.mkstemp(prefix="debuger_lldb_stdout_", suffix=".log")
            fd_err, err_path = tempfile.mkstemp(prefix="debuger_lldb_stderr_", suffix=".log")
            _os.close(fd_out)
            _os.close(fd_err)
            self._stdout_file = out_path
            self._stderr_file = err_path
            ok_redirect = False

            # Try SetStandardOutputFile/SetStandardErrorFile first
            try:
                if hasattr(launch_info, "SetStandardOutputFile"):
                    # DO NOT transfer ownership (False) - we manage the file lifecycle
                    # Transfer ownership on Windows can cause the file to close prematurely
                    launch_info.SetStandardOutputFile(self._stdout_file, False)
                    ok_redirect = True
                if hasattr(launch_info, "SetStandardErrorFile"):
                    launch_info.SetStandardErrorFile(self._stderr_file, False)
                    ok_redirect = True
                if ok_redirect:
                    stdio_redirect_method = "SetStandardOutputFile/SetStandardErrorFile"
            except Exception:
                ok_redirect = False

            # Try path-based setters if file-based failed
            if not ok_redirect:
                try:
                    if hasattr(launch_info, "SetStandardOutputPath"):
                        launch_info.SetStandardOutputPath(self._stdout_file)
                        ok_redirect = True
                    if hasattr(launch_info, "SetStandardErrorPath"):
                        launch_info.SetStandardErrorPath(self._stderr_file)
                        ok_redirect = True
                    if ok_redirect:
                        stdio_redirect_method = "SetStandardOutputPath/SetStandardErrorPath"
                except Exception:
                    pass

            # Last resort: Use AddOpenFileAction to manually redirect file descriptors
            # This is the most reliable method on older LLDB builds
            if not ok_redirect:
                try:
                    if hasattr(launch_info, "AddOpenFileAction"):
                        # Redirect fd 1 (stdout) and fd 2 (stderr) to our temp files
                        launch_info.AddOpenFileAction(1, self._stdout_file, False, True)
                        launch_info.AddOpenFileAction(2, self._stderr_file, False, True)
                        ok_redirect = True
                        stdio_redirect_method = "AddOpenFileAction"
                except Exception:
                    pass

            if ok_redirect:
                import sys
                sys.stderr.write(f"[debuger] Stdio redirect: {stdio_redirect_method} -> {self._stdout_file}, {self._stderr_file}\n")
                sys.stderr.flush()
            else:
                import sys
                sys.stderr.write(f"[debuger] Warning: All stdio redirection methods failed, output may not be captured\n")
                sys.stderr.flush()

            self._stdout_pos = 0
            self._stderr_pos = 0
        except Exception as e:
            # Fallback silently if redirection APIs are unavailable
            import sys
            sys.stderr.write(f"[debuger] Warning: Stdio redirection setup failed: {e}\n")
            sys.stderr.flush()
            self._stdout_file = None
            self._stderr_file = None
            self._stdout_pos = 0
            self._stderr_pos = 0

        error = lldb.SBError()
        proc = tgt.Launch(launch_info, error)
        if not error.Success():
            raise AdapterError(f"LLDB launch failed: {error.GetCString()}")

        self._target = tgt
        self._process = proc
        self._session_ready = True

        # Log process state immediately after launch
        pid = proc.GetProcessID() if proc else 0
        state = self._state_str()
        import sys
        sys.stderr.write(f"[debuger] Process launched: PID={pid}, state={state}\n")
        sys.stderr.flush()

        # If we stopped at an unhelpful location (e.g., function epilogue or brace),
        # try a few step-ins to land on a meaningful source line inside main.
        try:
            th = self._selected_thread()
            for i in range(5):
                # Check if process has exited
                current_state = self._state_str()
                if current_state in ("exited", "crashed"):
                    import sys
                    sys.stderr.write(f"[debuger] Process {current_state} during stepping, stopping early\n")
                    sys.stderr.flush()
                    break

                path, line, func = self.current_location()
                if not path or not line:
                    import sys
                    sys.stderr.write(f"[debuger] Step {i+1}/5: No source location, stepping into\n")
                    sys.stderr.flush()
                    th.StepInto()
                    continue
                try:
                    # Read the source line and check it's not closing brace / whitespace
                    import io
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        for j, ln in enumerate(f, start=1):
                            if j == line:
                                s = ln.strip()
                                break
                        else:
                            s = ""
                    if s and s not in ("}", "{"):
                        import sys
                        sys.stderr.write(f"[debuger] Stepped to meaningful line: {path}:{line} in {func}\n")
                        sys.stderr.flush()
                        break
                    else:
                        import sys
                        sys.stderr.write(f"[debuger] Step {i+1}/5: At {path}:{line} (brace/empty), stepping into\n")
                        sys.stderr.flush()
                except Exception as e:
                    import sys
                    sys.stderr.write(f"[debuger] Step {i+1}/5: Exception reading source: {e}\n")
                    sys.stderr.flush()
                    break
                th.StepInto()
        except Exception as e:
            import sys
            sys.stderr.write(f"[debuger] Warning: Post-launch stepping failed: {e}\n")
            sys.stderr.flush()

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
        # Cleanup temp stdio files
        try:
            import os as _os
            for p in (self._stdout_file, self._stderr_file):
                try:
                    if p and _os.path.exists(p):
                        _os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass
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

    def current_location(self) -> tuple[Optional[str], Optional[int], Optional[str]]:
        th = self._selected_thread()
        fr = th.GetFrameAtIndex(0)
        le = fr.GetLineEntry()
        fs = le.GetFileSpec()
        func = fr.GetFunctionName() or None
        try:
            directory = fs.GetDirectory() if fs else None
            filename = fs.GetFilename() if fs else None
            if directory and filename:
                path = f"{directory}/{filename}" if directory and filename else (filename or None)
            else:
                path = filename or None
        except Exception:
            path = None
        line = le.GetLine() if le else 0
        return (path, int(line) if line else None, func)

    def read_stdio(self) -> tuple[str, str]:
        # Prefer tailing files if we redirected output; also drain SBProcess pipes
        # First, ensure any buffered data is flushed to disk
        try:
            if self._process:
                # Force flush of process stdio buffers by polling the process
                import os as _os
                if self._stdout_file and _os.path.exists(self._stdout_file):
                    # Wait a tiny bit for OS to flush buffers
                    import time
                    time.sleep(0.01)
        except Exception:
            pass

        try:
            out_file_data = ""
            if self._stdout_file:
                with open(self._stdout_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._stdout_pos)
                    out_file_data = f.read()
                    self._stdout_pos = f.tell()
        except Exception:
            out_file_data = ""
        try:
            err_file_data = ""
            if self._stderr_file:
                with open(self._stderr_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._stderr_pos)
                    err_file_data = f.read()
                    self._stderr_pos = f.tell()
        except Exception:
            err_file_data = ""
        # Combine with direct LLDB drains to be safe
        out_pipe_data = ""
        err_pipe_data = ""
        try:
            if self._process:
                while True:
                    chunk = self._process.GetSTDOUT(8192)
                    if not chunk:
                        break
                    out_pipe_data += chunk
        except Exception:
            pass
        try:
            if self._process:
                while True:
                    chunk = self._process.GetSTDERR(8192)
                    if not chunk:
                        break
                    err_pipe_data += chunk
        except Exception:
            pass
        out_s = (out_file_data or "") + (out_pipe_data or "")
        err_s = (err_file_data or "") + (err_pipe_data or "")
        return (out_s, err_s)

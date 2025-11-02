from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Dict
from pathlib import Path


def main() -> None:
    # Ensure project src (two levels up from this file) is on sys.path
    try:
        src_root = Path(__file__).resolve().parents[2]
        if str(src_root) not in sys.path:
            sys.path.insert(0, str(src_root))
    except Exception:
        pass

    # Late import so we can adjust sys.path above
    from debuger.adapters.lldb_adapter import LldbAdapter
    from debuger.adapters import AdapterError

    adapter = LldbAdapter()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req: Dict[str, Any] = json.loads(line)
            rid = req.get("id")
            method = req.get("method")
            params = req.get("params") or {}
            result = None

            try:
                if method == "launch":
                    adapter.launch(
                        params["target"],
                        params.get("args"),
                        params.get("cwd"),
                        params.get("env"),
                        bool(params.get("stop_at_entry", False)),
                    )
                    result = True
                elif method == "attach":
                    adapter.attach(int(params["pid"]))
                    result = True
                elif method == "shutdown":
                    adapter.shutdown()
                    result = True
                elif method == "continue_run":
                    adapter.continue_run()
                    result = True
                elif method == "step_in":
                    adapter.step_in()
                    result = True
                elif method == "step_over":
                    adapter.step_over()
                    result = True
                elif method == "step_out":
                    adapter.step_out()
                    result = True
                elif method == "backtrace":
                    result = adapter.backtrace(params.get("max_frames"))
                elif method == "frames":
                    result = adapter.frames()
                elif method == "threads":
                    result = adapter.threads()
                elif method == "bp_add":
                    result = adapter.bp_add(params["spec"])
                elif method == "bp_list":
                    result = adapter.bp_list()
                elif method == "bp_remove":
                    adapter.bp_remove(int(params["bp_id"]))
                    result = True
                elif method == "eval":
                    result = adapter.eval(params["expr"])
                elif method == "locals":
                    result = adapter.locals()
                elif method == "regs":
                    result = adapter.regs()
                elif method == "disasm":
                    result = adapter.disasm(bool(params.get("around", True)), int(params.get("count", 32)))
                elif method == "select_frame":
                    adapter.select_frame(int(params["index"]))
                    result = True
                elif method == "select_thread":
                    adapter.select_thread(int(params["tid"]))
                    result = True
                elif method == "current_location":
                    result = adapter.current_location()
                elif method == "read_stdio":
                    result = adapter.read_stdio()
                else:
                    raise AdapterError(f"Unknown method: {method}")

                resp = {"id": rid, "result": result}
            except AdapterError as e:
                resp = {"id": rid, "error": {"code": "AdapterError", "message": str(e)}}
            except Exception as e:
                resp = {
                    "id": rid,
                    "error": {
                        "code": "Exception",
                        "message": str(e),
                        "trace": traceback.format_exc(limit=2),
                    },
                }
        except Exception as e:
            resp = {"id": None, "error": {"code": "BadRequest", "message": str(e)}}

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

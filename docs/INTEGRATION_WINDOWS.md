# Windows Integration Notes

This guide focuses on integrating `debuger` with Windows C++ development, including Visual Studio projects and symbol resolution.

## Your Project

- Path: `C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1`
- Visual Studio typically emits the debug binary under `Debug\\` or `x64\\Debug\\`.
- Example binary path: `C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1\\x64\\Debug\\ConsoleApplication1.exe`

You can launch it with:

```bash
debuger open "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1\\x64\\Debug\\ConsoleApplication1.exe"
```

Or create a `debuger.yaml` in the project root:

```yaml
target: "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1\\x64\\Debug\\ConsoleApplication1.exe"
args: []
cwd: "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1"
debugger: lldb   # try lldb first; fallback to gdb
symbols:
  - "C:\\Users\\Antoine\\source\\repos\\ConsoleApplication1\\x64\\Debug"
sourcePaths: []
```

## Debugger Backends on Windows

1) LLDB (recommended starting point)
   - Install LLVM for Windows (includes `lldb.exe` and Python bindings when selected).
   - `debuger doctor` will check for the `lldb` Python module.
   - LLDB can load PDB symbols for MSVC-built binaries.

2) GDB (fallback)
   - Install MinGW-w64; ensure `gdb.exe` is on PATH.
   - Works best with DWARF symbols (MinGW toolchain). With MSVC-built binaries, this is limited.

3) CDB/WinDbg (later milestone)
   - Uses Windows Debugging Engine (dbgeng). Best PDB support and Windows-specific features.
   - Requires Windows SDK / Debugging Tools for Windows.

## Symbols

- MSVC builds produce `.pdb` files alongside `.exe`/`.dll`.
- LLDB and CDB can consume PDBs. GDB is primarily for DWARF.
- System symbol servers: configure `_NT_SYMBOL_PATH` if needed, e.g.:

```powershell
$env:_NT_SYMBOL_PATH = "srv*C:\\symbols*https://msdl.microsoft.com/download/symbols"
```

## Common Issues & Hints

- If `lldb` module not found: install LLVM with LLDB Python bindings; restart shell.
- If source paths are wrong (e.g., different machine), use `sourcePaths` remapping rules in `debuger.yaml`.
- Ensure you build with debug info: MSVC `/Zi` (Program Database), and do not strip symbols.


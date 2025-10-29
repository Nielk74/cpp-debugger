from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .config import DebugerConfig


def _norm_sep(p: str) -> str:
    # Normalize mixed separators and strip quotes
    p = p.strip().strip('"')
    if os.name == "nt":
        # Replace forward slashes with backslashes for Windows
        p = p.replace("/", "\\")
    return p


def remap_source(path: Optional[str], cfg: DebugerConfig) -> Optional[str]:
    if not path:
        return path
    p = _norm_sep(path)
    # Apply sourceMap prefix replacements
    try:
        maps = cfg.sourceMap or []
    except Exception:
        maps = []
    is_windows = os.name == "nt"
    for m in maps:
        src = _norm_sep(str(m.get("from", "")))
        dst = _norm_sep(str(m.get("to", "")))
        if not src:
            continue
        # Case-insensitive on Windows
        if is_windows:
            if p.lower().startswith(src.lower()):
                return dst + p[len(src) :]
        else:
            if p.startswith(src):
                return dst + p[len(src) :]

    # Try search roots if file not found
    pp = Path(p)
    if pp.exists():
        return str(pp)
    name = pp.name
    for root in cfg.sourcePaths or []:
        cand = Path(root) / name
        if cand.exists():
            return str(cand)
    return str(pp)


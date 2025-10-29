from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


CONFIG_FILENAME = "debuger.yaml"


@dataclass
class DebugerConfig:
    target: Optional[str] = None
    args: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    debugger: Optional[str] = None  # lldb|gdb|cdb
    symbols: List[str] = field(default_factory=list)
    sourcePaths: List[str] = field(default_factory=list)  # search roots for sources
    sourceMap: List[Dict[str, str]] = field(default_factory=list)  # [{from: "C:/build/src", to: "C:/dev/project/src"}, ...]

    @classmethod
    def from_file(cls, path: str | os.PathLike) -> "DebugerConfig":
        p = pathlib.Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config not found: {p}")
        data = yaml.safe_load(p.read_text()) or {}
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__.keys()})

    @classmethod
    def find_in_ancestors(cls, start: str | os.PathLike) -> tuple["DebugerConfig", pathlib.Path]:
        cur = pathlib.Path(start).resolve()
        for d in [cur, *cur.parents]:
            cfg = d / CONFIG_FILENAME
            if cfg.exists():
                return cls.from_file(cfg), cfg
        raise FileNotFoundError("debuger.yaml not found in current directory or parents")

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "args": list(self.args),
            "cwd": self.cwd,
            "env": dict(self.env),
            "debugger": self.debugger,
            "symbols": list(self.symbols),
            "sourcePaths": list(self.sourcePaths),
            "sourceMap": list(self.sourceMap),
        }

    def save(self, path: str | os.PathLike) -> None:
        p = pathlib.Path(path)
        p.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False))

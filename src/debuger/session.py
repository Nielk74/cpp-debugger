from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .config import DebugerConfig
from .adapters import BaseAdapter, AdapterError, get_adapter


@dataclass
class Session:
    adapter: BaseAdapter
    config: DebugerConfig


class SessionManager:
    def __init__(self) -> None:
        self._session: Optional[Session] = None

    def current(self) -> Optional[Session]:
        return self._session

    def start_with_target(self, cfg: DebugerConfig, stop_at_entry: bool = True) -> None:
        if not cfg.target:
            raise ValueError("No target specified in config")
        if not os.path.exists(cfg.target):
            raise FileNotFoundError(f"Target not found: {cfg.target}")
        adapter = get_adapter(cfg.debugger)
        self._session = Session(adapter=adapter, config=cfg)
        # Placeholder behavior: raise to indicate not implemented
        try:
            adapter.launch(cfg.target, cfg.args, cfg.cwd, cfg.env, stop_at_entry=stop_at_entry)
        except AdapterError as e:
            raise AdapterError(str(e))

    def attach(self, cfg: DebugerConfig, pid: int) -> None:
        adapter = get_adapter(cfg.debugger)
        self._session = Session(adapter=adapter, config=cfg)
        try:
            adapter.attach(pid)
        except AdapterError as e:
            raise AdapterError(str(e))


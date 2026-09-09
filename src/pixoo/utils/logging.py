"""Structured logging helpers."""

from __future__ import annotations

import logging
import sys
from collections import deque
from datetime import datetime, timezone
from typing import Deque


class MemoryLogHandler(logging.Handler):
    """Ring buffer of recent log records for the API."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self.buffer: Deque[dict[str, str]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.buffer.append(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "msg": msg,
            }
        )

    def entries(self, *, since: str | None = None, limit: int = 100) -> list[dict[str, str]]:
        items = list(self.buffer)
        if since:
            items = [e for e in items if e["time"] >= since]
        return items[-max(1, limit) :]


def setup_logging(level: int = logging.INFO) -> MemoryLogHandler:
    root = logging.getLogger("pixoo")
    root.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(sh)
    mem = MemoryLogHandler()
    mem.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(mem)
    return mem

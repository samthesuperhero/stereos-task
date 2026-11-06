from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

SERVICE = "stereos-task"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extra = getattr(record, "structured", {})
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": SERVICE,
            "msg": record.getMessage(),
            "extra": extra,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    resolved = getattr(logging, level, logging.INFO)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved)

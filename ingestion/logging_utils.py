"""Shared structured (JSON) logging setup for all ingestion modules.

Every ingestion run (INMET, DataSUS) logs through the standard library
`logging` module, formatted as one JSON object per line, so that each run
is traceable and machine-parseable (e.g. by GitHub Actions log grouping or
a future log aggregator) without pulling in an extra dependency.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_RESERVED_LOG_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Any keyword arguments passed via `logger.info(msg, extra={...})` are
    merged into the JSON output, so callers can attach structured context
    (e.g. station_code, row_count) without string interpolation.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_LOG_RECORD_ATTRS
        }
        if extras:
            payload.update(extras)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """Returns a logger configured to emit structured JSON to stdout.

    Safe to call multiple times for the same name (e.g. across test runs
    or repeated imports) — it will not attach duplicate handlers.
    """
    logger = logging.getLogger(name)
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

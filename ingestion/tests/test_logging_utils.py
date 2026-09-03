"""Tests for the shared structured (JSON) logging setup used by both the
INMET and DataSUS ingestion modules."""

from __future__ import annotations

import json
import logging

from ingestion.logging_utils import JsonFormatter, get_logger


def _format_record(**extra) -> dict:
    logger = logging.getLogger("test-json-formatter")
    logger.setLevel(logging.INFO)
    record = logger.makeRecord(
        name=logger.name,
        level=logging.INFO,
        fn="test.py",
        lno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
        extra=extra or None,
    )
    return json.loads(JsonFormatter().format(record))


def test_json_formatter_includes_standard_fields():
    payload = _format_record()

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test-json-formatter"
    assert payload["message"] == "hello world"
    assert "timestamp" in payload


def test_json_formatter_includes_extra_fields():
    payload = _format_record(station_code="A807", row_count=5)

    assert payload["station_code"] == "A807"
    assert payload["row_count"] == 5


def test_json_formatter_includes_exception_when_present():
    logger = logging.getLogger("test-json-formatter-exc")
    try:
        raise ValueError("boom")
    except ValueError:
        record = logger.makeRecord(
            name=logger.name,
            level=logging.ERROR,
            fn="test.py",
            lno=1,
            msg="failed",
            args=(),
            exc_info=True,
            sinfo=None,
        )
        import sys

        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_get_logger_does_not_attach_duplicate_handlers():
    logger_a = get_logger("test-get-logger-singleton")
    logger_b = get_logger("test-get-logger-singleton")

    assert logger_a is logger_b
    assert len(logger_a.handlers) == 1

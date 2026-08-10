# Copyright 2026 DataRobot, Inc. and its affiliates.
#
# All rights reserved.
#
# DataRobot, Inc. Confidential.
#
# This is unpublished proprietary source code of DataRobot, Inc.
# and its affiliates.
#
# The copyright notice above does not evidence any actual or intended
# publication of such source code.

import io
import json
import logging
import sys

import pytest

from datarobot_opentelemetry.logging import (
    JsonFormatter,
    ReadableFormatter,
    RedactingFormatter,
    TextFormatter,
    get_logger,
    init_logging,
    log_api_call,
    redact_attributes,
)


def _make_record(message: str = "hello", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_includes_extra_fields() -> None:
    record = _make_record("hello", user_id="u1")
    data = json.loads(JsonFormatter().format(record))
    assert data["message"] == "hello"
    assert data["user_id"] == "u1"
    assert data["levelname"] == "INFO"


def test_json_formatter_severity_key_matches_collector_severity_parser() -> None:
    # Regression test: the Chronosphere OTel collector's severity_parser for JSON
    # logs only fires on `attributes.levelname`. A "level" key (the original,
    # upstream-inherited name) silently drops severity for every JSON log line
    # from this formatter, defaulting it to INFO downstream.
    record = _make_record("hello")
    data = json.loads(JsonFormatter().format(record))
    assert data["levelname"] == "INFO"
    assert "level" not in data


def test_json_formatter_serializes_arbitrary_object_via_str_fallback() -> None:
    class Widget:
        def __str__(self) -> str:
            return "widget-repr"

    record = _make_record("hello", widget=Widget())
    data = json.loads(JsonFormatter().format(record))
    assert data["widget"] == "widget-repr"


def test_json_formatter_reports_circular_reference_error() -> None:
    circular: dict = {}
    circular["self"] = circular
    record = _make_record("hello", circular=circular)
    data = json.loads(JsonFormatter().format(record))
    assert "serialization error" in data["circular"]


def test_text_formatter_appends_extra_fields() -> None:
    formatter = TextFormatter("%(message)s")
    record = _make_record("hello", user_id="u1")
    assert formatter.format(record) == "hello | user_id=u1"


def test_text_formatter_indents_every_traceback_line() -> None:
    # Regression test: the DataRobot OTel collector's recombine operator treats any
    # line that doesn't start with whitespace as the start of a new log record. The
    # default (unindented) traceback has two such lines - "Traceback (most recent
    # call last):" and the final "ValueError: ..." line - which would each get split
    # off into their own severity-less record. Every line after the first must be
    # indented.
    try:
        raise ValueError("boom")
    except ValueError:
        record = _make_record("failed")
        record.exc_info = sys.exc_info()

    formatted = TextFormatter("%(message)s").format(record)
    lines = formatted.split("\n")
    assert lines[0] == "failed"
    assert len(lines) > 1
    for line in lines[1:]:
        assert line[:1] in (" ", "\t"), f"unindented continuation line: {line!r}"
    assert "ValueError: boom" in formatted


def test_text_formatter_indents_bare_multiline_message_without_exception() -> None:
    # Regression test: a plain multi-line log call (e.g. a hand-rolled banner like
    # log_api_call's "\n====\nAPI CALL COMPLETE\n====\n") has nothing to do with
    # exceptions, so formatException's indentation never runs for it. The collector's
    # recombine operator would still split it into separate, severity-less records
    # unless format() itself indents every continuation line.
    separator = f"\n{'=' * 20}\n"
    record = _make_record(f"{separator}API CALL COMPLETE: foo{separator}")

    formatted = TextFormatter("%(message)s").format(record)
    lines = formatted.split("\n")
    assert lines[0] == ""
    for line in lines[1:]:
        assert not line or line[:1].isspace(), f"unindented continuation line: {line!r}"
    assert "API CALL COMPLETE: foo" in formatted


def test_readable_formatter_indents_bare_multiline_message_without_exception() -> None:
    separator = f"\n{'=' * 20}\n"
    record = _make_record(f"{separator}API CALL COMPLETE: foo{separator}")

    formatted = ReadableFormatter().format(record)
    lines = formatted.split("\n")
    for line in lines[1:]:
        assert not line or line[:1].isspace(), f"unindented continuation line: {line!r}"
    assert "API CALL COMPLETE: foo" in formatted


def test_readable_formatter_single_line_without_exception() -> None:
    record = _make_record("hello")
    output = ReadableFormatter().format(record)
    assert output.endswith("INFO:test.logger:hello")
    assert "\n" not in output


def test_readable_formatter_indents_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = _make_record("failed")
        record.exc_info = sys.exc_info()
    output = ReadableFormatter().format(record)
    assert "exception:" in output
    assert "ValueError: boom" in output


@pytest.mark.parametrize("sensitive_key", ["access_token", "refresh_token", "api_key"])
def test_redacting_formatter_redacts_direct_attribute(sensitive_key: str) -> None:
    record = _make_record("hello", **{sensitive_key: "super-secret"})
    formatted = RedactingFormatter(TextFormatter("%(message)s")).format(record)
    assert "super-secret" not in formatted
    assert "[REDACTED]" in formatted


def test_redacting_formatter_redacts_nested_dict() -> None:
    record = _make_record("hello", payload={"api_key": "super-secret", "ok": "value"})
    formatted = RedactingFormatter(TextFormatter("%(message)s")).format(record)
    assert "super-secret" not in formatted
    assert "value" in formatted


def test_redacting_formatter_regex_catches_string_representation() -> None:
    record = _make_record("request failed with api_key='super-secret'")
    formatted = RedactingFormatter(TextFormatter("%(message)s")).format(record)
    assert "super-secret" not in formatted


def test_redacting_formatter_does_not_mutate_original_record() -> None:
    record = _make_record("hello", api_key="super-secret")
    RedactingFormatter(TextFormatter("%(message)s")).format(record)
    assert record.api_key == "super-secret"


def test_redact_attributes_redacts_top_level_sensitive_key() -> None:
    assert redact_attributes({"api_key": "super-secret", "ok": "value"}) == {
        "api_key": "[REDACTED]",
        "ok": "value",
    }


def test_redact_attributes_redacts_nested_dict_value() -> None:
    redacted = redact_attributes(
        {"payload": {"api_key": "super-secret", "ok": "value"}}
    )
    assert redacted == {"payload": {"api_key": "[REDACTED]", "ok": "value"}}


def test_redact_attributes_redacts_secret_embedded_in_free_text() -> None:
    # Regression test: a secret embedded as plain text inside a non-sensitive-keyed
    # string value (e.g. an exception message like "Auth failed, api_key=secret")
    # used to survive completely - key-based redaction only caught it when the
    # *key itself* was sensitive, never when it was buried inside a string value.
    redacted = redact_attributes(
        {"exception.message": "Auth failed, api_key=super-secret-token"}
    )
    assert redacted == {"exception.message": "Auth failed, api_key=[REDACTED]"}


def test_init_logging_wires_redacting_formatter_by_default() -> None:
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    stream = io.StringIO()
    try:
        init_logging(stream=stream)
        logging.getLogger("test.init").info("secret api_key=super-secret here")
        output = stream.getvalue()
        assert "super-secret" not in output
        assert "[REDACTED]" in output
    finally:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        for handler in original_handlers:
            root_logger.addHandler(handler)


def test_get_logger_readable_format() -> None:
    stream = io.StringIO()
    logger = get_logger("test.readable", format_type="readable", stream=stream)
    logger.info("hello")
    assert "INFO:test.readable:hello" in stream.getvalue()


async def test_log_api_call_does_not_strip_root_logger_handlers() -> None:
    # Regression test: log_api_call used to call get_logger() (default name="") on every
    # invocation, which resolves to the root logger and unconditionally replaces its
    # handlers - destroying whatever OTel log export handler was attached there.
    root_logger = logging.getLogger()
    sentinel_handler = logging.NullHandler()
    root_logger.addHandler(sentinel_handler)
    try:

        @log_api_call
        async def call() -> str:
            return "ok"

        assert await call() == "ok"
        assert sentinel_handler in root_logger.handlers
    finally:
        root_logger.removeHandler(sentinel_handler)


async def test_log_api_call_logs_start_and_complete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @log_api_call
    async def call() -> str:
        return "ok"

    with caplog.at_level(logging.INFO):
        assert await call() == "ok"

    assert any("API CALL START" in r.message for r in caplog.records)
    assert any("API CALL COMPLETE" in r.message for r in caplog.records)


async def test_log_api_call_logs_error_and_reraises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @log_api_call
    async def call() -> None:
        raise ValueError("boom")

    with caplog.at_level(logging.INFO), pytest.raises(ValueError, match="boom"):
        await call()

    assert any("ERROR IN API CALL" in r.message for r in caplog.records)

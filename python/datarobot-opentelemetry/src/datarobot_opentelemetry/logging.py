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

import copy
import json
import logging
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from functools import wraps
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    ParamSpec,
    Tuple,
    TypeVar,
    Union,
)

from datarobot_opentelemetry.enums import FormatType, LogLevel

_READABLE_INDENT = "   "

_STANDARD_LOG_RECORD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)
_OTHER_LOG_RECORD_ATTRS = set({"asctime", "message", "color_message"})
_ALL_EXCLUDED_LOG_RECORD_ATTRS = _STANDARD_LOG_RECORD_ATTRS.union(
    _OTHER_LOG_RECORD_ATTRS
)


class JsonFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.
    Formats log records as JSON with standard fields like timestamp, level, and message.
    Only includes explicitly added extra parameters from the logging call.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.default_fields: Dict[
            str, Union[Callable[[logging.LogRecord], Any], Any]
        ] = {
            "timestamp": lambda _: datetime.now(timezone.utc).isoformat(),
            # The Chronosphere OTel collector's node daemonset only extracts severity
            # from JSON logs when this key is exactly "levelname" (severity_parser
            # matches on attributes.levelname) - it never looked for "level" and
            # silently defaulted every JSON log line from this formatter to INFO.
            "levelname": lambda record: record.levelname,
            "logger": lambda record: record.name,
        }

    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record as JSON.

        Returns a JSON string containing timestamp, level, logger, message,
        exception details (if present), and any explicitly added extra fields.
        """
        log_data = {
            field: getter(record) if callable(getter) else getter
            for field, getter in self.default_fields.items()
        }

        log_data["message"] = record.getMessage()

        if record.exc_info and record.exc_info[0]:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": "".join(traceback.format_exception(*record.exc_info)),
            }

        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _ALL_EXCLUDED_LOG_RECORD_ATTRS
        }
        for key, value in extra_fields.items():
            try:
                json.dumps(value, default=str)
                log_data[key] = value
            except ValueError as e:
                log_data[key] = f"<serialization error: {str(e)}>"

        return json.dumps(log_data, ensure_ascii=False, default=str)


class ReadableFormatter(logging.Formatter):
    """
    Human-readable formatter: timestamp LEVEL:logger:message (ISO UTC).
    When present, extra fields from the log record are appended as | key=value.
    For records with exception info, appends an indented 'exception:' block
    with the traceback.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        first_line = f"{ts} {record.levelname}:{record.name}:{record.getMessage()}"
        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _ALL_EXCLUDED_LOG_RECORD_ATTRS
        }
        if extra_fields:
            extra_str = " | ".join(f"{k}={v}" for k, v in extra_fields.items())
            first_line = f"{first_line} | {extra_str}"
        if not (record.exc_info and record.exc_info[0]):
            return first_line
        tb_str = "".join(traceback.format_exception(*record.exc_info))
        tb_indented = "\n".join(
            _READABLE_INDENT + line for line in tb_str.rstrip().split("\n")
        )
        return f"{first_line}\n{_READABLE_INDENT}exception:\n{tb_indented}"


class TextFormatter(logging.Formatter):
    """
    Custom text formatter that includes extra fields in the output.
    Formats log records as text with standard fields and any additional fields
    appended to the message in key=value format, separated by ' | '.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as text, including extra fields."""
        message = super().format(record)

        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _ALL_EXCLUDED_LOG_RECORD_ATTRS
        }
        if extra_fields:
            extra_str = " | ".join(f"{k}={v}" for k, v in extra_fields.items())
            message = f"{message} | {extra_str}"

        return message


SENSITIVE_LOG_KEYS: List[str] = ["access_token", "refresh_token", "api_key"]


def redact_value(obj: Any, sensitive_keys: List[str] = SENSITIVE_LOG_KEYS) -> Any:
    """
    Recursively redact sensitive information from dictionaries and objects.
    Returns a new object with redacted values without mutating the original.
    """
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if k in sensitive_keys else redact_value(v, sensitive_keys)
            for k, v in obj.items()
        }
    elif isinstance(obj, (list, tuple)):
        return type(obj)(redact_value(item, sensitive_keys) for item in obj)
    elif hasattr(obj, "__dict__"):
        # create a shallow copy first to avoid mutating the original
        try:
            obj_copy = copy.copy(obj)
            for key in sensitive_keys:
                if hasattr(obj_copy, key):
                    setattr(obj_copy, key, "[REDACTED]")
            return obj_copy
        except (TypeError, AttributeError):
            return obj
    return obj


def redact_attributes(
    attributes: Dict[str, Any], sensitive_keys: List[str] = SENSITIVE_LOG_KEYS
) -> Dict[str, Any]:
    """Redact a flat mapping (e.g. OTel log record attributes), including top-level keys.

    Unlike `redact_value`, which only redacts keys nested *inside* a dict/object value,
    this also treats the mapping's own top-level keys as redactable - so
    `{"api_key": "secret"}` redacts to `{"api_key": "[REDACTED]"}`.
    """
    return {
        k: "[REDACTED]" if k in sensitive_keys else redact_value(v, sensitive_keys)
        for k, v in attributes.items()
    }


class RedactingFormatter(logging.Formatter):
    """Wraps another formatter to redact sensitive values from log output."""

    sensitive_keys: List[str] = SENSITIVE_LOG_KEYS

    def __init__(self, original_formatter: logging.Formatter):
        super().__init__()
        self.original_formatter = original_formatter
        self.patterns: List[Tuple[str, "re.Pattern[str]"]] = []
        for key in self.sensitive_keys:
            # Match key='value' or key="value" or key=value
            pattern = re.compile(
                rf"{re.escape(key)}=(['\"]?)([^'\"\s,)}}]+)\1", re.IGNORECASE
            )
            self.patterns.append((key, pattern))

    def format(self, record: logging.LogRecord) -> str:
        """Format the record, redacting sensitive keys from attributes and their string reprs."""
        record = copy.copy(record)

        for key in self.sensitive_keys:
            if hasattr(record, key):
                setattr(record, key, "[REDACTED]")

        for key, value in list(record.__dict__.items()):
            if key not in _ALL_EXCLUDED_LOG_RECORD_ATTRS:
                record.__dict__[key] = redact_value(value, self.sensitive_keys)

        formatted = self.original_formatter.format(record)

        for key, pattern in self.patterns:
            formatted = pattern.sub(rf"{key}=\1[REDACTED]\1", formatted)

        return formatted


def _build_formatter(format_type: FormatType) -> logging.Formatter:
    if format_type == "json":
        return JsonFormatter()
    if format_type == "readable":
        return ReadableFormatter()
    formatter = TextFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    formatter.converter = time.gmtime
    return formatter


def init_logging(
    level: LogLevel = LogLevel.INFO,
    format_type: FormatType = "text",
    stream: Any = sys.stdout,
) -> None:
    """
    Initialize the root logger globally.

    Call this once at application startup to set the global logging level and
    format. Any logger obtained afterward via `logging.getLogger(__name__)`
    inherits these settings.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level.value)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(_build_formatter(format_type)))

    root_logger.addHandler(handler)


def get_logger(
    name: str = "",
    level: Union[LogLevel, str] = LogLevel.INFO,
    stream: Any = sys.stdout,
    format_type: FormatType = "text",
) -> logging.Logger:
    """
    Get a configured logger instance with its own dedicated handler.

    Note: this replaces `name`'s existing handlers and disables propagation.
    With the default `name=""` that targets the root logger - if OTel log
    export is attached there, prefer `logging.getLogger(name)` instead so you
    don't tear that down. See `log_api_call` for an example.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper())

    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(_build_formatter(format_type)))

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    for existing_handler in logger.handlers[:]:
        logger.removeHandler(existing_handler)

    logger.addHandler(handler)
    return logger


P = ParamSpec("P")
T = TypeVar("T")


def log_api_call(
    func: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Log entry/exit/errors around an async API call, without touching OTel's log handlers.

    Uses a plain `logging.getLogger(func.__module__)`, not `get_logger()`: `get_logger()`
    unconditionally strips and replaces the target logger's handlers, and with the default
    `name=""` that's the root logger - destroying whatever OTel export handler is attached
    there. A plain logger just propagates to whatever's already configured.
    """
    logger = logging.getLogger(func.__module__)

    @wraps(func)
    async def wrapper(*args: "P.args", **kwargs: "P.kwargs") -> T:
        request_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        separator = f"\n{'=' * 80}\n"
        logger.info(
            f"{separator}API CALL START: {func.__name__} [{request_id}]{separator}"
        )
        try:
            result = await func(*args, **kwargs)
            logger.info(
                f"{separator}API CALL COMPLETE: {func.__name__} [{request_id}]{separator}"
            )
            return result
        except Exception as e:
            error_log = (
                f"ERROR IN API CALL [{request_id}]\n"
                "------------------------\n"
                f"Function: {func.__name__}\n"
                f"Error Type: {type(e).__name__}\n"
                f"Error Message: {str(e)}\n\n"
                "Stack Trace:\n"
            )
            logger.error(error_log, exc_info=True)
            raise

    return wrapper

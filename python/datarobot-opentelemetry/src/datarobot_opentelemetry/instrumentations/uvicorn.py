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

import logging

from datarobot_opentelemetry.enums import FormatType
from datarobot_opentelemetry.logging import RedactingFormatter, _build_formatter


class HealthCheckFilter(logging.Filter):
    """Filter out health check requests from access logs."""

    def __init__(self, log_level: str = "INFO"):
        super().__init__()
        self.log_level = log_level

    def filter(self, record: logging.LogRecord) -> bool:
        numeric_log_level = getattr(logging, self.log_level.upper())
        # Filter out health check requests only when log level is INFO or higher
        if numeric_log_level <= logging.DEBUG:
            return True

        if hasattr(record, "getMessage"):
            message = record.getMessage()
            if "/health" in message and "GET" in message:
                return False
        return True


def configure_uvicorn_logging(
    log_format: FormatType = "text", log_level: str = "INFO"
) -> None:
    """Configure uvicorn logging to use our custom formatter and filter."""
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(_build_formatter(log_format)))
    handler.addFilter(HealthCheckFilter(log_level))

    access_logger.addHandler(handler)
    access_logger.setLevel(getattr(logging, log_level.upper()))
    access_logger.propagate = False

    error_logger = logging.getLogger("uvicorn.error")
    error_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(_build_formatter(log_format)))

    error_logger.addHandler(handler)
    error_logger.setLevel(getattr(logging, log_level.upper()))
    error_logger.propagate = False

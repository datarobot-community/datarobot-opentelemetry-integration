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

# mypy: disable-error-code=import-not-found

"""
FastAPI integration for DataRobot Custom Applications.

Layers FastAPI/httpx/requests/SQLAlchemy auto-instrumentation and redacted
log export on top of `datarobot_opentelemetry.integrations.configure()`,
instead of re-implementing OTel provider setup. `configure()` remains the
single place that builds Trace/Log/Metric providers and OTLP exporters;
this module only adds what's specific to FastAPI applications.
"""

from __future__ import annotations

import contextvars
import logging
import os
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Optional
from typing import Protocol

from opentelemetry import context
from opentelemetry import metrics
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs import LoggingHandler

from datarobot_opentelemetry.integrations.configuration import ConfigureResult
from datarobot_opentelemetry.integrations.configuration import (
    configure as configure_providers,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except ImportError:
    FastAPIInstrumentor = None  # type: ignore[assignment, misc]

try:
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
except ImportError:
    RequestsInstrumentor = None  # type: ignore[assignment, misc]

try:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
except ImportError:
    HTTPXClientInstrumentor = None  # type: ignore[assignment, misc]

try:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
except ImportError:
    SQLAlchemyInstrumentor = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

_FASTAPI_EXCLUDED_URLS = r"//[^/]+/$,/health$,/assets/.*"

_otel_handler_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_otel_handler_active", default=False
)


class OTelConfig(Protocol):
    """Structural type for the subset of app config `OTel.configure` needs.

    Any app-specific Settings/Config class that has these three attributes
    satisfies this protocol automatically - no inheritance required.
    """

    otel_exporter_otlp_endpoint: str
    otel_exporter_otlp_headers: str
    otel_sdk_disabled: bool


class _SafeLoggingHandler(LoggingHandler):
    """LoggingHandler with ContextVar recursion guard and redacted export attributes.

    Backport of opentelemetry-python-contrib #4302, plus: `LoggingHandler._translate()`
    reads log record attributes via `_get_attributes(record)` independently of
    `self.format(record)` - so wrapping the formatter in `RedactingFormatter` only
    redacts the exported body string, not the `attributes` dict sent to the OTel
    backend. Override `_get_attributes` to redact those too.
    """

    @staticmethod
    def _get_attributes(record: logging.LogRecord) -> dict[str, Any]:
        from datarobot_opentelemetry.logging import redact_attributes

        attributes = LoggingHandler._get_attributes(record)
        return redact_attributes(dict(attributes))

    def emit(self, record: logging.LogRecord) -> None:
        if _otel_handler_active.get():
            return
        token = _otel_handler_active.set(True)
        try:
            super().emit(record)
        finally:
            _otel_handler_active.reset(token)


class OTLPConnectionErrorFilter(logging.Filter):
    """
    Filter to suppress connection errors from urllib3/requests when the OTLP collector is
    unavailable, so a misconfigured or unreachable endpoint doesn't spam application logs
    with connection-refused noise on every export attempt.
    """

    def __init__(self, warning_callback: Optional[Callable[[], None]] = None):
        super().__init__()
        self.warning_callback = warning_callback

    def filter(self, record: logging.LogRecord) -> bool:
        should_suppress = False

        if record.name.startswith("urllib3.connectionpool"):
            message = record.getMessage()
            if "HTTPConnectionPool" in message and (
                ":4318" in message
                or "/v1/metrics" in message
                or "/v1/traces" in message
                or "/v1/logs" in message
            ):
                should_suppress = True

        if record.name.startswith("requests."):
            message = record.getMessage()
            if "ConnectionError" in message and ":4318" in message:
                should_suppress = True

        if (
            not should_suppress
            and record.name.startswith("opentelemetry.sdk.")
            and record.levelno == logging.ERROR
        ):
            if record.exc_info:
                exc = record.exc_info[1]
                while exc is not None:
                    if type(exc).__name__ in (
                        "ConnectionError",
                        "NewConnectionError",
                        "MaxRetryError",
                    ):
                        should_suppress = True
                        break
                    exc = exc.__cause__ or exc.__context__

        if should_suppress:
            if self.warning_callback:
                self.warning_callback()
            return False

        return True


def _replace_export_handler_with_redacting(log_level: int) -> None:
    """Swap the plain `LoggingHandler` `configure()` attaches for a redacting one.

    `configure()` (via `LoggingInstrumentor().instrument(logger_provider=...)`) attaches a
    plain `opentelemetry.sdk._logs.LoggingHandler` to the root logger, which would export log
    records verbatim - including anything sensitive in `extra` fields. Swap it for
    `_SafeLoggingHandler` wrapped in `RedactingFormatter` so nothing bypasses redaction, while
    still reusing the LoggerProvider/exporter `configure()` already built.
    """
    from datarobot_opentelemetry.logging import RedactingFormatter

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if isinstance(handler, LoggingHandler) and not isinstance(
            handler, _SafeLoggingHandler
        ):
            root_logger.removeHandler(handler)

    safe_handler = _SafeLoggingHandler(
        level=log_level, logger_provider=get_logger_provider()
    )
    safe_handler.setFormatter(RedactingFormatter(logging.Formatter()))
    root_logger.addHandler(safe_handler)


class OTel:
    """
    OpenTelemetry manager for DataRobot FastAPI Custom Applications.

    Singleton: only one instance exists per process. Delegates Trace/Log/Metric provider
    setup to `datarobot_opentelemetry.integrations.configure()` and adds FastAPI-specific
    auto-instrumentation and redacted log export on top.
    """

    _instance: "OTel | None" = None
    _initialized: bool = False
    _auto_instrumentation_setup: bool = False

    def __new__(
        cls, entity_type: str = "custom_application", entity_id: Optional[str] = None
    ) -> "OTel":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self, entity_type: str = "custom_application", entity_id: Optional[str] = None
    ):
        if self._initialized:
            return

        self.entity_type = entity_type
        self.entity_id = entity_id or os.environ.get("APPLICATION_ID")

        self.telemetry_enabled = False
        self._configured = False
        self._startup_logged = False
        self._otlp_warning_logged = False
        self._result: Optional[ConfigureResult] = None

        self._install_otlp_error_filter()

        self._initialized = True

    def configure(self, config: OTelConfig) -> ConfigureResult:
        """Apply OTel settings from app config. Call once during app startup.

        A second call is a no-op (returns the result from the first call) rather than
        re-running provider/handler setup - `configure_providers()` and
        `_replace_export_handler_with_redacting()` are not idempotent themselves,
        so re-entry would stack a second `_SafeLoggingHandler` on the root logger and
        export every log record twice.
        """
        if self._configured:
            assert self._result is not None
            return self._result

        if config.otel_exporter_otlp_endpoint:
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
                config.otel_exporter_otlp_endpoint
            )
        if config.otel_exporter_otlp_headers:
            os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = config.otel_exporter_otlp_headers

        if config.otel_sdk_disabled:
            logger.info(
                "OTel SDK disabled via config; skipping telemetry configuration."
            )
            self._result = ConfigureResult(
                tracing_configured=False,
                metrics_configured=False,
                logger_configured=False,
            )
            self._configured = True
            return self._result

        result = configure_providers(
            entity_type=self.entity_type, entity_id=self.entity_id
        )
        self._result = result
        self.telemetry_enabled = (
            result.tracing_configured
            or result.metrics_configured
            or result.logger_configured
        )

        if result.logger_configured:
            _replace_export_handler_with_redacting(logging.INFO)

        if self.telemetry_enabled and not self._auto_instrumentation_setup:
            self._setup_auto_instrumentation()
            self._auto_instrumentation_setup = True

        self._configured = True
        return result

    def _install_otlp_error_filter(self) -> None:
        """Install logging filter to suppress OTLP connection errors."""
        otlp_filter = OTLPConnectionErrorFilter(self._log_otlp_warning)

        logging.getLogger("urllib3.connectionpool").addFilter(otlp_filter)
        logging.getLogger("requests").addFilter(otlp_filter)

        for sdk_logger_name in (
            "opentelemetry.sdk._logs._internal.export",
            "opentelemetry.sdk.trace.export",
            "opentelemetry.sdk.metrics._internal.export",
        ):
            logging.getLogger(sdk_logger_name).addFilter(otlp_filter)

    def _log_otlp_warning(self) -> None:
        """Log a warning about OTLP connection failure (only once)."""
        if not self._otlp_warning_logged:
            self._otlp_warning_logged = True
            logger.warning(
                "OTLP collector connection failed. Telemetry data may be lost. "
                "Suppressing further connection errors to prevent log spam. "
                "Check OTEL_EXPORTER_OTLP_ENDPOINT configuration."
            )

    def _setup_auto_instrumentation(self) -> None:
        """
        Set up auto-instrumentation for common libraries.

        Automatically instruments requests and httpx (used by API clients).
        FastAPI itself must be instrumented separately via `instrument_fastapi_app`,
        since it needs the app instance.
        """
        if RequestsInstrumentor is not None:
            try:
                RequestsInstrumentor().instrument()
                logger.info("Auto-instrumentation enabled for requests library")
            except Exception as e:
                logger.warning(f"Failed to setup requests auto-instrumentation: {e}")
        else:
            logger.warning(
                "RequestsInstrumentor not available. "
                "Install with: pip install 'datarobot-opentelemetry[fastapi]'"
            )

        if HTTPXClientInstrumentor is not None:
            try:
                HTTPXClientInstrumentor().instrument()
                logger.info("Auto-instrumentation enabled for httpx library")
            except Exception as e:
                logger.warning(f"Failed to setup httpx auto-instrumentation: {e}")

        if SQLAlchemyInstrumentor is not None:
            try:
                SQLAlchemyInstrumentor().instrument()
                logger.info("Auto-instrumentation enabled for SQLAlchemy")
            except Exception as e:
                logger.warning(f"Failed to setup SQLAlchemy auto-instrumentation: {e}")

    def instrument_fastapi_app(self, app: "FastAPI") -> None:
        """
        Instrument a FastAPI application for automatic tracing.

        Call this after creating your FastAPI app instance.
        """
        if FastAPIInstrumentor is None:
            logger.warning(
                "FastAPIInstrumentor not available. "
                "Install with: pip install 'datarobot-opentelemetry[fastapi]'"
            )
            return

        try:
            FastAPIInstrumentor.instrument_app(
                app, excluded_urls=_FASTAPI_EXCLUDED_URLS
            )
            logger.info("Auto-instrumentation enabled for FastAPI application")
        except Exception as e:
            logger.warning(f"Failed to instrument FastAPI app: {e}")

    def get_logger(self, name: str) -> logging.Logger:
        """Get a Python logger. Exported via OTel once `configure` has run."""
        return logging.getLogger(name)

    def get_meter(self, name: str) -> metrics.Meter:
        """Get a meter instance for the given name using the OpenTelemetry global API."""
        return metrics.get_meter(name)

    def get_tracer(self, name: str) -> trace.Tracer:
        """Get a tracer instance for the given name using the OpenTelemetry global API."""
        return trace.get_tracer(name)

    def get_context(self) -> context.Context:
        """
        Return the current OTel context. To cross thread boundaries, call `get_context` in
        the spawning thread and `set_context` in the spawned thread.
        """
        return context.get_current()

    def set_context(self, otel_context: context.Context) -> Any:
        """Set the OTel context."""
        return context.attach(otel_context)

    def reset_context(self, token: Any) -> None:
        context.detach(token)

    def shutdown(self) -> None:
        """Gracefully shut down all telemetry providers configured for this process."""
        if not self._result:
            return

        if self._result.tracing_configured:
            self._shutdown_provider(trace.get_tracer_provider())
        if self._result.metrics_configured:
            self._shutdown_provider(metrics.get_meter_provider())
        if self._result.logger_configured:
            self._shutdown_provider(get_logger_provider())

    @staticmethod
    def _shutdown_provider(provider: Any) -> None:
        # The global getters return the API's NoOp/Proxy type when nothing installed a
        # concrete SDK provider - only shut down when one actually exposes `shutdown`.
        shutdown_fn = getattr(provider, "shutdown", None)
        if shutdown_fn is not None:
            shutdown_fn()

    def log_application_start(self, application_name: str = "Application") -> None:
        """Log application startup event (only once per process)."""
        if self._startup_logged:
            return

        self._startup_logged = True
        self.get_logger(f"{self.entity_type}.startup").info(
            f"{application_name} starting up",
            extra={
                "application_id": self.entity_id,
                "application_type": self.entity_type,
            },
        )

    def __enter__(self) -> "OTel":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown()

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
FastAPI integration for OpenTelemetry.

Layers FastAPI/httpx/requests/SQLAlchemy auto-instrumentation and redacted
log export on top of `datarobot_opentelemetry.integrations.configure()`,
instead of re-implementing OTel provider setup. `configure()` remains the
single place that builds Trace/Log/Metric providers and OTLP exporters;
this module only adds what's specific to FastAPI applications. DataRobot
Custom Applications are the primary consumer today, but nothing here is
Custom-Application-specific.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import os
import time
from collections.abc import AsyncGenerator
from collections.abc import Coroutine
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Optional
from typing import ParamSpec
from typing import Protocol
from typing import TypeVar
from typing import no_type_check
from typing import overload

from opentelemetry import context
from opentelemetry import metrics
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.trace import Span
from opentelemetry.instrumentation.logging.handler import (
    LoggingHandler as _InstrumentationLoggingHandler,
)
from opentelemetry.sdk._logs import LoggingHandler as _SDKLoggingHandler

from datarobot_opentelemetry.enums import EntityType
from datarobot_opentelemetry.integrations.configuration import ConfigureResult
from datarobot_opentelemetry.integrations.configuration import (
    configure as configure_providers,
)
from datarobot_opentelemetry.logging import RedactingFormatter, redact_attributes

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

P = ParamSpec("P")
T = TypeVar("T")

DEFAULT_EXCLUDED_TRACE_SPAN_NAMES: frozenset[str] = frozenset()
"""Span names excluded from tracing by default.

Empty by default - this is a shared library, not any one app, so it has no
opinion on which spans are noisy. Apps add their own via the
OTEL_EXCLUDED_TRACE_SPAN_NAMES env var (comma-separated).
"""

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


class _SafeLoggingHandler(_SDKLoggingHandler):
    """LoggingHandler with ContextVar recursion guard and redacted export attributes.

    Backport of opentelemetry-python-contrib #4302, plus: `LoggingHandler._translate()`
    reads log record attributes via `_get_attributes(record)` independently of
    `self.format(record)` - so wrapping the formatter in `RedactingFormatter` only
    redacts the exported body string, not the `attributes` dict sent to the OTel
    backend. Override `_get_attributes` to redact those too.
    """

    @staticmethod
    def _get_attributes(record: logging.LogRecord) -> dict[str, Any]:
        attributes = _SDKLoggingHandler._get_attributes(record)
        return redact_attributes(dict(attributes))

    def emit(self, record: logging.LogRecord) -> None:
        if _otel_handler_active.get():
            return
        token = _otel_handler_active.set(True)
        try:
            super().emit(record)
        finally:
            _otel_handler_active.reset(token)


_OTLP_EXPORTER_LOGGER_NAMES = frozenset(
    {
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
    }
)


class OTLPConnectionErrorFilter(logging.Filter):
    """
    Filter to suppress OTLP export failure noise so a misconfigured or unreachable
    collector doesn't spam application logs on every export attempt. Covers two distinct
    failure modes: the endpoint being completely unreachable (connection-refused errors
    from urllib3/requests, or wrapped in an opentelemetry.sdk exception chain), and the
    endpoint being reachable but rejecting the request (the exporters' own "Failed to
    export ... batch" errors, e.g. a 404 from a misconfigured path). Either way, retrying
    won't help without a config change, so this warns once via `warning_callback` and
    suppresses the rest.
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
            record.name in _OTLP_EXPORTER_LOGGER_NAMES
            and record.levelno == logging.ERROR
        ):
            should_suppress = True

        if (
            not should_suppress
            and record.name.startswith("opentelemetry.sdk.")
            and record.levelno == logging.ERROR
        ):
            if record.exc_info:
                exc = record.exc_info[1]
                seen: set[int] = set()
                while exc is not None and id(exc) not in seen:
                    if type(exc).__name__ in (
                        "ConnectionError",
                        "NewConnectionError",
                        "MaxRetryError",
                    ):
                        should_suppress = True
                        break
                    seen.add(id(exc))
                    exc = exc.__cause__ or exc.__context__

        if should_suppress:
            if self.warning_callback:
                self.warning_callback()
            return False

        return True


def _replace_export_handler_with_redacting(log_level: int) -> None:
    """Swap the plain log export handler `configure()` attaches for a redacting one.

    `configure()` calls `LoggingInstrumentor().instrument(logger_provider=..., ...)`, which by
    default attaches its own `opentelemetry.instrumentation.logging.handler.LoggingHandler` to
    the root logger - a separate class from `opentelemetry.sdk._logs.LoggingHandler` (not a
    subclass of it), so a check against only one of them misses the other. Either would export
    log records verbatim, including anything sensitive in `extra` fields. Swap whichever is
    attached for `_SafeLoggingHandler` wrapped in `RedactingFormatter` so nothing bypasses
    redaction, while still reusing the LoggerProvider/exporter `configure()` already built.
    """
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if isinstance(
            handler, (_SDKLoggingHandler, _InstrumentationLoggingHandler)
        ) and not isinstance(handler, _SafeLoggingHandler):
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
        cls,
        entity_type: EntityType | str = EntityType.CUSTOM_APPLICATION,
        entity_id: Optional[str] = None,
    ) -> "OTel":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        entity_type: EntityType | str = EntityType.CUSTOM_APPLICATION,
        entity_id: Optional[str] = None,
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

        if config.otel_exporter_otlp_endpoint:
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
                config.otel_exporter_otlp_endpoint
            )
        if config.otel_exporter_otlp_headers:
            os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = config.otel_exporter_otlp_headers

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
            *_OTLP_EXPORTER_LOGGER_NAMES,
        ):
            logging.getLogger(sdk_logger_name).addFilter(otlp_filter)

    def _get_excluded_trace_span_names(self) -> frozenset[str]:
        configured_span_names = {
            span_name.strip()
            for span_name in os.environ.get("OTEL_EXCLUDED_TRACE_SPAN_NAMES", "").split(
                ","
            )
            if span_name.strip()
        }
        return DEFAULT_EXCLUDED_TRACE_SPAN_NAMES | configured_span_names

    def _is_trace_span_excluded(self, span_name: str) -> bool:
        return span_name in self._get_excluded_trace_span_names()

    def _log_otlp_warning(self) -> None:
        """Log a warning about OTLP export failure (only once)."""
        if not self._otlp_warning_logged:
            self._otlp_warning_logged = True
            logger.warning(
                "OTLP export failed (collector unreachable or rejected the request). "
                "Telemetry data may be lost. Suppressing further export errors to "
                "prevent log spam. Check OTEL_EXPORTER_OTLP_ENDPOINT configuration."
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
                app,
                excluded_urls=_FASTAPI_EXCLUDED_URLS,
                exclude_spans=["send", "receive"],
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

    @overload
    def trace(
        self: "OTel",
        func: Callable[P, Coroutine[T, None, None]],
    ) -> Callable[P, Coroutine[T, None, None]]: ...

    @overload
    def trace(
        self: "OTel",
        func: Callable[P, AsyncGenerator[T, None]],
    ) -> Callable[P, AsyncGenerator[T, None]]: ...

    @overload
    def trace(
        self: "OTel",
        func: Callable[P, Generator[T, None, None]],
    ) -> Callable[P, Generator[T, None, None]]: ...

    @overload
    def trace(self: "OTel", func: Callable[P, T]) -> Callable[P, T]: ...

    @overload
    def trace(self: "OTel", name: str) -> Callable[[Any], Any]: ...

    @no_type_check
    def trace(self: "OTel", func: Any) -> Any:
        """
        Wrap the execution of the decorated function in an OTel span.

        Accepts an optional custom span name::

            @otel.trace
            async def my_handler(): ...

            @otel.trace("custom-operation-name")
            async def my_handler(): ...

        WARNING: there are sharp edges with this decorator on functions that get
        reflected on (e.g. via inspect.signature) - it changes the wrapped
        callable's introspectable signature.
        """
        if isinstance(func, str):
            return functools.partial(self._trace_with_name, span_name=func)
        return self._trace_with_name(func)

    @no_type_check
    def _trace_with_name(
        self: "OTel", func: Any, span_name: Optional[str] = None
    ) -> Any:
        name = span_name or f"{func.__module__}.{func.__qualname__}"

        if self._is_trace_span_excluded(name):
            return func

        tracer = self.get_tracer("application-tracer")

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_inner(*args, **kwargs):
                with tracer.start_as_current_span(name):
                    return await func(*args, **kwargs)

            return async_inner
        elif inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def inner_asyncgen(*args, **kwargs):
                with tracer.start_as_current_span(name):
                    async for x in func(*args, **kwargs):
                        yield x

            return inner_asyncgen
        elif inspect.isgeneratorfunction(func):

            @functools.wraps(func)
            def inner_gen(*args, **kwargs):
                with tracer.start_as_current_span(name):
                    for x in func(*args, **kwargs):
                        yield x

            return inner_gen
        elif inspect.isfunction(func):

            @functools.wraps(func)
            def inner(*args, **kwargs):
                with tracer.start_as_current_span(name):
                    return func(*args, **kwargs)

            return inner
        else:
            raise ValueError(
                f"instrument can only decorate a function type, while {name} is a {type(func)}."
            )

    @functools.cache
    def _function_histogram(self: "OTel", name: str) -> metrics.Histogram:
        meter = self.get_meter("application-meter")
        return meter.create_histogram(
            f"function.{name}", "s", "A histogram recording function timings."
        )

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Generator[Span, None, None]:
        """Create a named span as a context manager, with optional initial attributes.

        Use this for ad-hoc spans within a function body where a decorator
        would be too coarse-grained::

            with otel.span("retrieve-documents", query=query_text) as span:
                docs = retrieve(query_text)
                span.set_attribute("doc_count", len(docs))
        """
        with self.get_tracer("application-tracer").start_as_current_span(
            name
        ) as active_span:
            for key, value in attributes.items():
                active_span.set_attribute(key, value)
            yield active_span

    @contextmanager
    def time(self, name: str) -> Generator[None, None, None]:
        start_time = time.time_ns()
        success = True
        try:
            yield
        except Exception:
            success = False
            raise
        finally:
            end_time = time.time_ns()
            histogram = self._function_histogram(name)
            histogram.record((end_time - start_time) / 1e9, {"success": success})

    @overload
    def meter(
        self: "OTel",
        func: Callable[P, Coroutine[T, None, None]],
    ) -> Callable[P, Coroutine[T, None, None]]: ...

    @overload
    def meter(
        self: "OTel",
        func: Callable[P, AsyncGenerator[T, None]],
    ) -> Callable[P, AsyncGenerator[T, None]]: ...

    @overload
    def meter(
        self: "OTel",
        func: Callable[P, Generator[T, None, None]],
    ) -> Callable[P, Generator[T, None, None]]: ...

    @overload
    def meter(self: "OTel", func: Callable[P, T]) -> Callable[P, T]: ...

    @no_type_check
    def meter(self: "OTel", func: Any) -> Any:
        """
        Wrap the execution of the decorated function in a timing histogram sharing
        the function's own name.

        WARNING: there are sharp edges with this decorator on functions that get
        reflected on (e.g. via inspect.signature) - it changes the wrapped
        callable's introspectable signature.
        """
        span_name = f"{func.__module__}.{func.__qualname__}"

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_inner(*args, **kwargs):
                with self.time(span_name):
                    return await func(*args, **kwargs)

            return async_inner
        elif inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def inner_asyncgen(*args, **kwargs):
                with self.time(span_name):
                    async for x in func(*args, **kwargs):
                        yield x

            return inner_asyncgen
        elif inspect.isgeneratorfunction(func):

            @functools.wraps(func)
            def inner_gen(*args, **kwargs):
                with self.time(span_name):
                    for x in func(*args, **kwargs):
                        yield x

            return inner_gen
        elif inspect.isfunction(func):

            @functools.wraps(func)
            def inner(*args, **kwargs):
                with self.time(span_name):
                    return func(*args, **kwargs)

            return inner
        else:
            raise ValueError(
                f"instrument can only decorate a function type, while {span_name} is a {type(func)}."
            )

    @overload
    def meter_and_trace(
        self: "OTel",
        func: Callable[P, Coroutine[T, None, None]],
    ) -> Callable[P, Coroutine[T, None, None]]: ...

    @overload
    def meter_and_trace(
        self: "OTel",
        func: Callable[P, AsyncGenerator[T, None]],
    ) -> Callable[P, AsyncGenerator[T, None]]: ...

    @overload
    def meter_and_trace(
        self: "OTel",
        func: Callable[P, Generator[T, None, None]],
    ) -> Callable[P, Generator[T, None, None]]: ...

    @overload
    def meter_and_trace(self: "OTel", func: Callable[P, T]) -> Callable[P, T]: ...

    @no_type_check
    def meter_and_trace(self: "OTel", func: Any) -> Any:
        """Apply both `meter` and `trace` to the decorated function."""
        return functools.wraps(func)(self.meter(self.trace(func)))

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
import os
import sys
from contextlib import AbstractContextManager
from contextlib import nullcontext
from dataclasses import dataclass

import pytest
from opentelemetry import _logs, metrics, trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.logging.handler import (
    LoggingHandler as InstrumentationLoggingHandler,
)
from opentelemetry.sdk._logs import LoggingHandler

from datarobot_opentelemetry.enums import EntityType
from datarobot_opentelemetry.integrations.configuration import ConfigureResult
from datarobot_opentelemetry.instrumentations.fastapi import (
    _OTLP_EXPORTER_LOGGER_NAMES,
    OTel,
    OTelConfig,
    OTLPConnectionErrorFilter,
    _SafeLoggingHandler,
)
from datarobot_opentelemetry.logging import RedactingFormatter

_OTLP_FILTERED_LOGGER_NAMES = (
    "urllib3.connectionpool",
    "requests",
    "opentelemetry.sdk._logs._internal.export",
    "opentelemetry.sdk.trace.export",
    "opentelemetry.sdk.metrics._internal.export",
    *_OTLP_EXPORTER_LOGGER_NAMES,
)

_ENTITY_HEADER = "x-datarobot-entity-id"
_API_KEY_HEADER = "x-datarobot-api-key"

_ENV_KEYS_TO_CLEAR = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "DATAROBOT_API_TOKEN",
    "DATAROBOT_ENTITY_TYPE",
    "DATAROBOT_ENTITY_ID",
)


@dataclass
class FakeOTelConfig:
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_sdk_disabled: bool = False


class TestEntityTypeDefault:
    def test_defaults_to_custom_application(self):
        otel = OTel()
        assert otel.entity_type == EntityType.CUSTOM_APPLICATION
        assert otel.entity_type == "custom_application"

    def test_accepts_enum_member(self):
        otel = OTel(entity_type=EntityType.DEPLOYMENT)
        assert otel.entity_type == "deployment"

    def test_accepts_plain_string_for_unlisted_types(self):
        # Not every entity type is enumerated; the platform can introduce new
        # ones before this enum is updated, so a plain string must keep working.
        otel = OTel(entity_type="future_entity_kind")
        assert otel.entity_type == "future_entity_kind"


def _reset_otel_singleton() -> None:
    OTel._instance = None
    OTel._initialized = False
    OTel._auto_instrumentation_setup = False
    for logger_name in _OTLP_FILTERED_LOGGER_NAMES:
        target_logger = logging.getLogger(logger_name)
        for existing_filter in list(target_logger.filters):
            if isinstance(existing_filter, OTLPConnectionErrorFilter):
                target_logger.removeFilter(existing_filter)


def _uninstrument_all() -> None:
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    for instrumentor_cls in (RequestsInstrumentor, LoggingInstrumentor):
        instrumentor = instrumentor_cls()
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()

    for module_path, class_name in (
        ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
        ("opentelemetry.instrumentation.sqlalchemy", "SQLAlchemyInstrumentor"),
    ):
        try:
            module = __import__(module_path, fromlist=[class_name])
        except ImportError:
            continue
        instrumentor = getattr(module, class_name)()
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()


@pytest.fixture(autouse=True)
def reset_otel_singleton(monkeypatch: pytest.MonkeyPatch):
    """Undo the process-wide side effects OTel.configure() leaves behind: the singleton,
    env vars it mirrors from config, global library auto-instrumentation, and any
    (Safe)LoggingHandler it attached to the root logger - shutdown() stops the
    provider's export but does not remove the handler itself. The global
    Trace/Log/Meter providers set via trace.set_tracer_provider() etc. have no public
    "unset" API and are not reset here - a test that actually configures one leaves it
    installed for the rest of the session.
    """
    _reset_otel_singleton()
    for key in _ENV_KEYS_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    yield
    if OTel._instance is not None:
        OTel._instance.shutdown()
    _reset_otel_singleton()
    for key in _ENV_KEYS_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    _uninstrument_all()
    root_logger = logging.getLogger()
    for handler in [
        h
        for h in root_logger.handlers
        if isinstance(
            h, (LoggingHandler, InstrumentationLoggingHandler, _SafeLoggingHandler)
        )
    ]:
        root_logger.removeHandler(handler)


def test_otel_config_protocol_is_satisfied_structurally() -> None:
    config: OTelConfig = FakeOTelConfig(
        otel_exporter_otlp_endpoint="http://localhost:4318"
    )
    assert config.otel_exporter_otlp_endpoint == "http://localhost:4318"


def test_otel_is_a_singleton() -> None:
    assert OTel() is OTel()


def test_configure_disabled_via_sdk_disabled_skips_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _fail_if_called(*args: object, **kwargs: object) -> ConfigureResult:
        nonlocal called
        called = True
        raise AssertionError(
            "configure_providers must not be called when SDK is disabled"
        )

    monkeypatch.setattr(
        "datarobot_opentelemetry.instrumentations.fastapi.configure_providers",
        _fail_if_called,
    )

    otel = OTel()
    result = otel.configure(
        FakeOTelConfig(
            otel_exporter_otlp_endpoint="https://otel.datarobot.com",
            otel_exporter_otlp_headers="x-datarobot-api-key=super-secret",
            otel_sdk_disabled=True,
        )
    )

    assert called is False
    assert result == ConfigureResult(
        tracing_configured=False, metrics_configured=False, logger_configured=False
    )
    assert otel.telemetry_enabled is False
    # Regression test: the endpoint/headers used to be mirrored into os.environ
    # before the otel_sdk_disabled check, so a disabled config would still leak
    # them (headers can carry an API key) into the process environment where
    # other OTel-aware libraries could pick them up.
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in os.environ


def test_configure_delegates_to_configure_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OTel.configure() must not rebuild providers itself - it hands off to the shared
    configure_providers() and only adds FastAPI-specific behavior on top."""
    seen_kwargs = {}

    def _fake_configure_providers(**kwargs: object) -> ConfigureResult:
        seen_kwargs.update(kwargs)
        return ConfigureResult(
            tracing_configured=True, metrics_configured=True, logger_configured=False
        )

    monkeypatch.setattr(
        "datarobot_opentelemetry.instrumentations.fastapi.configure_providers",
        _fake_configure_providers,
    )

    otel = OTel(entity_type="custom_application", entity_id="abc-123")
    result = otel.configure(
        FakeOTelConfig(
            otel_exporter_otlp_endpoint="https://otel.datarobot.com",
            otel_exporter_otlp_headers="x-datarobot-api-key=abc",
        )
    )

    assert seen_kwargs == {"entity_type": "custom_application", "entity_id": "abc-123"}
    assert result.tracing_configured is True
    assert otel.telemetry_enabled is True
    assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://otel.datarobot.com"
    assert os.environ["OTEL_EXPORTER_OTLP_HEADERS"] == "x-datarobot-api-key=abc"


def test_configure_second_call_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: configure() used to have no guard against being called
    twice, so a second call re-ran configure_providers() and stacked a second
    _SafeLoggingHandler on the root logger, exporting every log record twice."""
    call_count = 0

    def _fake_configure_providers(**_: object) -> ConfigureResult:
        nonlocal call_count
        call_count += 1
        return ConfigureResult(
            tracing_configured=True, metrics_configured=True, logger_configured=True
        )

    monkeypatch.setattr(
        "datarobot_opentelemetry.instrumentations.fastapi.configure_providers",
        _fake_configure_providers,
    )

    otel = OTel()
    config = FakeOTelConfig(otel_exporter_otlp_endpoint="http://localhost:4318")
    first_result = otel.configure(config)
    second_result = otel.configure(config)

    assert call_count == 1
    assert second_result is first_result
    root_logger = logging.getLogger()
    safe_handlers = [
        h for h in root_logger.handlers if isinstance(h, _SafeLoggingHandler)
    ]
    assert len(safe_handlers) == 1


def test_configure_telemetry_disabled_when_nothing_gets_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "datarobot_opentelemetry.instrumentations.fastapi.configure_providers",
        lambda **_: ConfigureResult(
            tracing_configured=False, metrics_configured=False, logger_configured=False
        ),
    )

    otel = OTel()
    otel.configure(FakeOTelConfig(otel_exporter_otlp_endpoint=""))

    assert otel.telemetry_enabled is False


def test_configure_replaces_plain_logging_handler_with_redacting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plain LoggingHandler configure_providers()/LoggingInstrumentor attaches to the
    root logger would export log records verbatim. OTel.configure() must swap it for a
    redacting one so nothing bypasses redaction."""
    root_logger = logging.getLogger()
    plain_handler = LoggingHandler(logger_provider=_logs.get_logger_provider())
    root_logger.addHandler(plain_handler)
    try:
        monkeypatch.setattr(
            "datarobot_opentelemetry.instrumentations.fastapi.configure_providers",
            lambda **_: ConfigureResult(
                tracing_configured=False,
                metrics_configured=False,
                logger_configured=True,
            ),
        )

        otel = OTel()
        otel.configure(
            FakeOTelConfig(otel_exporter_otlp_endpoint="http://localhost:4318")
        )

        assert plain_handler not in root_logger.handlers
        safe_handlers = [
            h for h in root_logger.handlers if isinstance(h, _SafeLoggingHandler)
        ]
        assert len(safe_handlers) == 1
        assert isinstance(safe_handlers[0].formatter, RedactingFormatter)
    finally:
        for handler in [
            h
            for h in root_logger.handlers
            if isinstance(h, (LoggingHandler, _SafeLoggingHandler))
        ]:
            root_logger.removeHandler(handler)


def test_configure_end_to_end_leaves_only_the_safe_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: configure_providers() calls LoggingInstrumentor().instrument(),
    which by default attaches its own opentelemetry.instrumentation.logging.handler.
    LoggingHandler - a separate class from opentelemetry.sdk._logs.LoggingHandler, not a
    subclass of it. A previous fix only matched the SDK class, so the instrumentation
    handler (unredacted, no formatter) was left attached alongside _SafeLoggingHandler:
    every log record got exported twice, once with no redaction at all. This drives the
    real configure() -> configure_providers() -> LoggingInstrumentor path end to end,
    not a hand-constructed handler, so it actually exercises that code."""
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"{_ENTITY_HEADER}=deployment-abc123,{_API_KEY_HEADER}=secret-token",
    )

    otel = OTel()
    otel.configure(FakeOTelConfig(otel_exporter_otlp_endpoint="http://localhost:4318"))

    root_logger = logging.getLogger()
    export_handlers = [
        h
        for h in root_logger.handlers
        if isinstance(h, (LoggingHandler, InstrumentationLoggingHandler))
    ]
    assert export_handlers == [
        h for h in export_handlers if isinstance(h, _SafeLoggingHandler)
    ], "a non-redacting log export handler is still attached to the root logger"


def test_safe_logging_handler_redacts_exported_attributes() -> None:
    """Regression test: LoggingHandler._translate() reads attributes via
    _get_attributes(record), independent of self.format(record) - so wrapping the
    formatter in RedactingFormatter alone redacted the exported body string but left
    sensitive extra fields exposed in the attributes dict sent to the OTel backend."""
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="calling api",
        args=(),
        exc_info=None,
    )
    record.api_key = "super-secret"

    attributes = _SafeLoggingHandler._get_attributes(record)

    assert attributes["api_key"] == "[REDACTED]"


def test_safe_logging_handler_redacts_secret_embedded_in_exception_message() -> None:
    """Regression test: a secret embedded as free text in an exception message (e.g.
    raise ValueError(f"Auth failed, api_key={token}")) is not caught by key-based
    redaction - the OTel SDK's _get_attributes derives exception.message/
    exception.stacktrace from str(exc) and the traceback text, not from a dict key
    named "api_key". Confirmed empirically before this fix: the secret went out
    verbatim in both attributes."""
    try:
        raise ValueError("Auth failed, api_key=super-secret-token")
    except ValueError:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="call failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    attributes = _SafeLoggingHandler._get_attributes(record)

    assert "super-secret-token" not in attributes["exception.message"]
    assert "super-secret-token" not in attributes["exception.stacktrace"]


def test_shutdown_without_configuring_is_a_no_op() -> None:
    otel = OTel()
    otel.shutdown()  # must not raise


def test_shutdown_calls_shutdown_on_configured_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_calls = []

    class FakeProvider:
        def shutdown(self) -> None:
            shutdown_calls.append(self)

    monkeypatch.setattr(trace, "get_tracer_provider", lambda: FakeProvider())
    monkeypatch.setattr(metrics, "get_meter_provider", lambda: FakeProvider())
    monkeypatch.setattr(_logs, "get_logger_provider", lambda: FakeProvider())
    monkeypatch.setattr(
        "datarobot_opentelemetry.instrumentations.fastapi.get_logger_provider",
        lambda: FakeProvider(),
    )

    otel = OTel()
    otel._result = ConfigureResult(
        tracing_configured=True, metrics_configured=True, logger_configured=True
    )
    otel.shutdown()

    assert len(shutdown_calls) == 3


def test_instrument_fastapi_app_warns_when_instrumentor_unavailable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "datarobot_opentelemetry.instrumentations.fastapi.FastAPIInstrumentor", None
    )

    otel = OTel()
    with caplog.at_level(logging.WARNING):
        otel.instrument_fastapi_app(object())  # type: ignore[arg-type]

    assert "FastAPIInstrumentor not available" in caplog.text


def test_instrument_fastapi_app_excludes_send_receive_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple, dict]] = []

    class FakeFastAPIInstrumentor:
        @staticmethod
        def instrument_app(*args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

    monkeypatch.setattr(
        "datarobot_opentelemetry.instrumentations.fastapi.FastAPIInstrumentor",
        FakeFastAPIInstrumentor,
    )

    otel = OTel()
    otel.instrument_fastapi_app(object())  # type: ignore[arg-type]

    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["exclude_spans"] == ["send", "receive"]


@pytest.mark.parametrize(
    "logger_name",
    [
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
    ],
)
def test_otlp_connection_error_filter_suppresses_exporter_batch_failures(
    logger_name: str,
) -> None:
    # The filter itself calls warning_callback on every suppressed record - dedup to
    # "only once" is the caller's responsibility (see OTel._log_otlp_warning below).
    warnings: list[None] = []
    otlp_filter = OTLPConnectionErrorFilter(lambda: warnings.append(None))
    record = logging.LogRecord(
        name=logger_name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Failed to export span batch code: 404, reason: NOT FOUND",
        args=None,
        exc_info=None,
    )

    first = otlp_filter.filter(record)
    second = otlp_filter.filter(record)

    assert first is False
    assert second is False
    assert len(warnings) == 2


def test_otel_suppresses_repeated_exporter_batch_failures_end_to_end(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Integration-level check that OTel._install_otlp_error_filter actually wires the
    # exporter loggers up to the filter, and that OTel's own dedup logs just one warning
    # no matter how many batches fail.
    OTel()  # constructing the singleton installs the exporter-logger filter
    exporter_logger = logging.getLogger(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter"
    )

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            exporter_logger.error(
                "Failed to export span batch code: 404, reason: NOT FOUND"
            )

    assert "reason: NOT FOUND" not in caplog.text
    warning_lines = [r for r in caplog.records if "OTLP export failed" in r.message]
    assert len(warning_lines) == 1


def test_otlp_connection_error_filter_leaves_unrelated_exporter_logs_alone() -> None:
    otlp_filter = OTLPConnectionErrorFilter()
    record = logging.LogRecord(
        name="opentelemetry.exporter.otlp.proto.http.trace_exporter",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Export succeeded",
        args=None,
        exc_info=None,
    )

    assert otlp_filter.filter(record) is True


def test_log_application_start_only_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    otel = OTel(entity_type="custom_application", entity_id="abc-123")
    with caplog.at_level(logging.INFO):
        otel.log_application_start("My App")
        otel.log_application_start("My App")

    start_messages = [r for r in caplog.records if "My App starting up" in r.message]
    assert len(start_messages) == 1


def test_context_manager_shuts_down_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    shutdown_calls = []
    otel = OTel()
    monkeypatch.setattr(otel, "shutdown", lambda: shutdown_calls.append(True))

    with otel:
        pass

    assert shutdown_calls == [True]


def test_excluded_trace_span_names_empty_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OTEL_EXCLUDED_TRACE_SPAN_NAMES", raising=False)
    otel = OTel()
    assert otel._get_excluded_trace_span_names() == frozenset()


def test_excluded_trace_span_names_reads_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXCLUDED_TRACE_SPAN_NAMES", "app.noisy_span, app.other")
    otel = OTel()
    assert otel._get_excluded_trace_span_names() == {"app.noisy_span", "app.other"}


def test_trace_decorator_skips_excluded_span_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXCLUDED_TRACE_SPAN_NAMES", "app.noisy_span")
    otel = OTel()

    def handler() -> str:
        return "ok"

    wrapped = otel.trace("app.noisy_span")(handler)

    # An excluded span name means the function is returned unwrapped.
    assert wrapped is handler
    assert wrapped() == "ok"


def test_trace_decorator_wraps_and_creates_span() -> None:
    otel = OTel()
    calls = []

    @otel.trace
    def handler(value: int) -> int:
        calls.append(value)
        return value * 2

    assert handler(21) == 42
    assert calls == [21]


async def test_trace_decorator_wraps_async_function() -> None:
    otel = OTel()

    @otel.trace
    async def handler() -> str:
        return "ok"

    assert await handler() == "ok"


def test_trace_decorator_accepts_custom_span_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    otel = OTel()
    seen_span_names = []

    class _FakeTracer:
        def start_as_current_span(self, name: str) -> AbstractContextManager[None]:
            seen_span_names.append(name)
            return nullcontext()

    monkeypatch.setattr(otel, "get_tracer", lambda _name: _FakeTracer())

    @otel.trace("custom-operation-name")
    def handler() -> str:
        return "ok"

    assert handler() == "ok"
    assert seen_span_names == ["custom-operation-name"]


def test_span_context_manager_sets_attributes() -> None:
    otel = OTel()

    with otel.span("my-span", key="value") as active_span:
        assert active_span is not None


# Module-level with a short name: the `meter` decorator builds a metric name as
# f"function.{func.__module__}.{func.__qualname__}", capped at OTel's 63-char
# instrument name limit. A function nested inside a test picks up "<locals>" in
# its qualname and blows that budget immediately - a real, pre-existing
# constraint of this decorator, not something to route around inside the test.
def _m() -> str:
    return "ok"


def _m_raises() -> None:
    raise ValueError("boom")


def test_time_context_manager_records_without_raising() -> None:
    otel = OTel()
    with otel.time("my-timed-block"):
        pass


def test_time_context_manager_reraises_on_exception() -> None:
    otel = OTel()
    with pytest.raises(ValueError, match="boom"), otel.time("my-timed-block"):
        raise ValueError("boom")


def test_meter_decorator_records_without_raising() -> None:
    otel = OTel()
    assert otel.meter(_m)() == "ok"


def test_meter_decorator_records_on_exception() -> None:
    otel = OTel()
    with pytest.raises(ValueError, match="boom"):
        otel.meter(_m_raises)()


def test_meter_and_trace_applies_both() -> None:
    otel = OTel()
    assert otel.meter_and_trace(_m)() == "ok"

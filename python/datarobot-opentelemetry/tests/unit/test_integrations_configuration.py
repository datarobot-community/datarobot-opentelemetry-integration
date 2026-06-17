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

import builtins
import logging
import sys
import types

import pytest

from datarobot_opentelemetry.integrations import configure
from datarobot_opentelemetry.integrations.configuration import _parse_dr_env_vars
from datarobot_opentelemetry.semconv.headers import DataRobotOtelHeaders

ENTITY_HEADER = DataRobotOtelHeaders.ENTITY_ID
API_KEY_HEADER = DataRobotOtelHeaders.API_KEY


@pytest.fixture(autouse=True)
def _clear_datarobot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no ambient DataRobot/OTEL env vars leak into the tests."""
    for name in (
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "DATAROBOT_API_TOKEN",
        "DATAROBOT_ENTITY_TYPE",
        "DATAROBOT_ENTITY_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def _trace_exporter_headers() -> dict[str, str]:
    """Return the headers passed to the configured trace exporter."""
    provider = sys.modules["opentelemetry.trace"]._provider
    return provider.span_processors[0].exporter.headers


def _install_fake_opentelemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    modules: dict[str, types.ModuleType] = {}

    def add_module(name: str) -> types.ModuleType:
        module = types.ModuleType(name)
        modules[name] = module
        return module

    class NoOpTracer:
        pass

    class FakeTracer:
        def __init__(self) -> None:
            self._tracer = NoOpTracer()

    class ProxyTracerProvider:
        def get_tracer(self, _name: str) -> FakeTracer:
            return FakeTracer()

    class TracerProvider:
        def __init__(self, resource: object | None = None) -> None:
            self.resource = resource
            self.span_processors: list[object] = []

        def get_tracer(self, _name: str) -> FakeTracer:
            return FakeTracer()

        def add_span_processor(self, processor: object) -> None:
            self.span_processors.append(processor)

    class ProxyLoggerProvider:
        pass

    class LoggerProvider:
        def __init__(self, resource: object | None = None) -> None:
            self.resource = resource
            self.log_record_processors: list[object] = []

        def add_log_record_processor(self, processor: object) -> None:
            self.log_record_processors.append(processor)

    class _ProxyMeterProvider:
        pass

    class MeterProvider:
        def __init__(self, metric_readers: list[object], resource: object) -> None:
            self.metric_readers = metric_readers
            self.resource = resource

    class LoggingHandler(logging.Handler):
        def __init__(self, level: int = logging.NOTSET, logger_provider: object | None = None) -> None:
            super().__init__(level)
            self.logger_provider = logger_provider

        def emit(self, record: logging.LogRecord) -> None:
            return None

    class LoggingInstrumentor:
        def instrument(self, **_kwargs: object) -> None:
            return None

    class BatchLogRecordProcessor:
        def __init__(self, exporter: object) -> None:
            self.exporter = exporter

    class BatchSpanProcessor:
        def __init__(self, exporter: object) -> None:
            self.exporter = exporter

    class OTLPSpanExporter:
        def __init__(self, endpoint: str | None = None, headers: dict[str, str] | None = None) -> None:
            self.endpoint = endpoint
            self.headers = headers

    class OTLPLogExporter:
        def __init__(self, endpoint: str | None = None, headers: dict[str, str] | None = None) -> None:
            self.endpoint = endpoint
            self.headers = headers

    class OTLPMetricExporter:
        def __init__(self, endpoint: str | None = None, headers: dict[str, str] | None = None) -> None:
            self.endpoint = endpoint
            self.headers = headers

    class PeriodicExportingMetricReader:
        def __init__(self, exporter: object, export_interval_millis: int) -> None:
            self.exporter = exporter
            self.export_interval_millis = export_interval_millis

    class Resource:
        @staticmethod
        def create(attributes: dict[str, str]) -> dict[str, str]:
            return attributes

    opentelemetry = add_module("opentelemetry")
    trace_module = add_module("opentelemetry.trace")
    metrics_module = add_module("opentelemetry.metrics")
    logs_module = add_module("opentelemetry._logs")

    trace_module.NoOpTracer = NoOpTracer
    trace_module.ProxyTracerProvider = ProxyTracerProvider
    trace_module._provider = ProxyTracerProvider()
    trace_module.get_tracer_provider = lambda: trace_module._provider
    trace_module.set_tracer_provider = lambda provider: setattr(trace_module, "_provider", provider)

    logs_module._provider = ProxyLoggerProvider()
    logs_module.get_logger_provider = lambda: logs_module._provider
    logs_module.set_logger_provider = lambda provider: setattr(logs_module, "_provider", provider)

    metrics_module._provider = _ProxyMeterProvider()
    metrics_module.get_meter_provider = lambda: metrics_module._provider
    metrics_module.set_meter_provider = lambda provider: setattr(metrics_module, "_provider", provider)

    opentelemetry.trace = trace_module
    opentelemetry.metrics = metrics_module
    opentelemetry._logs = logs_module

    sdk_logs_module = add_module("opentelemetry.sdk._logs")
    sdk_logs_module.LoggerProvider = LoggerProvider

    instrumentation_module = add_module("opentelemetry.instrumentation")
    instrumentation_logging_module = add_module("opentelemetry.instrumentation.logging")
    instrumentation_logging_module.LoggingHandler = LoggingHandler
    instrumentation_logging_module.LoggingInstrumentor = LoggingInstrumentor
    instrumentation_module.logging = instrumentation_logging_module

    logs_internal_module = add_module("opentelemetry._logs._internal")
    logs_internal_module.ProxyLoggerProvider = ProxyLoggerProvider

    sdk_logs_internal_module = add_module("opentelemetry.sdk._logs._internal")
    sdk_logs_internal_module.ProxyLoggerProvider = ProxyLoggerProvider

    sdk_logs_export_module = add_module("opentelemetry.sdk._logs.export")
    sdk_logs_export_module.BatchLogRecordProcessor = BatchLogRecordProcessor

    sdk_trace_module = add_module("opentelemetry.sdk.trace")
    sdk_trace_module.TracerProvider = TracerProvider

    sdk_trace_export_module = add_module("opentelemetry.sdk.trace.export")
    sdk_trace_export_module.BatchSpanProcessor = BatchSpanProcessor

    sdk_resources_module = add_module("opentelemetry.sdk.resources")
    sdk_resources_module.Resource = Resource

    sdk_metrics_module = add_module("opentelemetry.sdk.metrics")
    sdk_metrics_module.MeterProvider = MeterProvider

    sdk_metrics_export_module = add_module("opentelemetry.sdk.metrics.export")
    sdk_metrics_export_module.PeriodicExportingMetricReader = PeriodicExportingMetricReader

    metrics_internal_module = add_module("opentelemetry.metrics._internal")
    metrics_internal_module._ProxyMeterProvider = _ProxyMeterProvider

    trace_exporter_module = add_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    trace_exporter_module.OTLPSpanExporter = OTLPSpanExporter

    log_exporter_module = add_module("opentelemetry.exporter.otlp.proto.http._log_exporter")
    log_exporter_module.OTLPLogExporter = OTLPLogExporter

    metric_exporter_module = add_module("opentelemetry.exporter.otlp.proto.http.metric_exporter")
    metric_exporter_module.OTLPMetricExporter = OTLPMetricExporter

    for name, module in modules.items():
        monkeypatch.setitem(__import__("sys").modules, name, module)


def test_configure_raises_actionable_error_when_opentelemetry_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _patched_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("opentelemetry"):
            raise ModuleNotFoundError("No module named 'opentelemetry'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched_import)

    with pytest.raises(ModuleNotFoundError) as error:
        configure("https://example.test", "deployment", "abc-123", api_key="token")

    assert "datarobot-opentelemetry[integrations]" in str(error.value)


def test_configure_succeeds_with_fake_opentelemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_opentelemetry(monkeypatch)

    from datarobot_opentelemetry.integrations import ConfigureResult

    result = configure("https://example.test", "deployment", "abc-123", api_key="token")
    assert result == ConfigureResult(tracing_configured=True, metrics_configured=True, logger_configured=True)


class TestParseDrEnvVars:
    def test_returns_none_when_header_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
        assert _parse_dr_env_vars() == (None, None)

    def test_returns_none_when_header_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "")
        assert _parse_dr_env_vars() == (None, None)

    def test_parses_entity_id_and_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_HEADERS",
            f"{ENTITY_HEADER}=deployment-123,{API_KEY_HEADER}=secret",
        )
        assert _parse_dr_env_vars() == ("deployment-123", "secret")

    def test_header_keys_are_case_insensitive_and_trimmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_HEADERS",
            f" {ENTITY_HEADER.upper()} =deployment-123, {API_KEY_HEADER.lower()}=secret",
        )
        assert _parse_dr_env_vars() == ("deployment-123", "secret")

    def test_ignores_items_without_equals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_HEADERS",
            f"garbage,{ENTITY_HEADER}=deployment-123",
        )
        assert _parse_dr_env_vars() == ("deployment-123", None)

    def test_value_may_contain_equals_sign(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_HEADERS",
            f"{API_KEY_HEADER}=a=b=c",
        )
        assert _parse_dr_env_vars() == (None, "a=b=c")

    def test_returns_none_for_unrelated_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer xyz")
        assert _parse_dr_env_vars() == (None, None)


def test_configure_uses_identity_from_otlp_headers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OTLP headers already carry the entity id and api key, configure
    should not require the DATAROBOT_* args/env vars and should not duplicate
    those values into the per-signal exporter headers."""
    _install_fake_opentelemetry(monkeypatch)
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"{ENTITY_HEADER}=deployment-123,{API_KEY_HEADER}=secret",
    )

    from datarobot_opentelemetry.integrations import ConfigureResult

    result = configure(endpoint="https://example.test")

    assert result == ConfigureResult(tracing_configured=True, metrics_configured=True, logger_configured=True)
    assert _trace_exporter_headers() == {}


def test_configure_explicit_args_override_env_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit api_key/entity args are honored even when OTLP headers env is set."""
    _install_fake_opentelemetry(monkeypatch)
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"{ENTITY_HEADER}=deployment-123,{API_KEY_HEADER}=secret",
    )

    configure(
        endpoint="https://example.test",
        entity_type="deployment",
        entity_id="abc-123",
        api_key="token",
    )

    assert _trace_exporter_headers() == {
        ENTITY_HEADER: "deployment-abc-123",
        API_KEY_HEADER: "token",
    }


def test_configure_requires_api_key_when_not_in_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_opentelemetry(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", f"{ENTITY_HEADER}=deployment-123")

    with pytest.raises(ValueError, match="API key is required"):
        configure(endpoint="https://example.test")


def test_configure_requires_entity_when_not_in_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_opentelemetry(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", f"{API_KEY_HEADER}=secret")

    with pytest.raises(ValueError, match="Entity type is required"):
        configure(endpoint="https://example.test")


def test_configure_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_opentelemetry(monkeypatch)
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"{ENTITY_HEADER}=deployment-123,{API_KEY_HEADER}=secret",
    )

    with pytest.raises(ValueError, match="Endpoint is required"):
        configure()
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
from dataclasses import dataclass

import pytest
from opentelemetry import _logs, metrics, trace
from opentelemetry.sdk._logs import LoggingHandler

from datarobot_opentelemetry.integrations.configuration import ConfigureResult
from datarobot_opentelemetry.integrations.fastapi import (
    OTel,
    OTelConfig,
    _SafeLoggingHandler,
)
from datarobot_opentelemetry.logging import RedactingFormatter

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


def _reset_otel_singleton() -> None:
    OTel._instance = None
    OTel._initialized = False
    OTel._auto_instrumentation_setup = False


def _uninstrument_all() -> None:
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    for instrumentor_cls in (RequestsInstrumentor,):
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
    env vars it mirrors from config, and global library auto-instrumentation. The global
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
        "datarobot_opentelemetry.integrations.fastapi.configure_providers",
        _fail_if_called,
    )

    otel = OTel()
    result = otel.configure(FakeOTelConfig(otel_sdk_disabled=True))

    assert called is False
    assert result == ConfigureResult(
        tracing_configured=False, metrics_configured=False, logger_configured=False
    )
    assert otel.telemetry_enabled is False


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
        "datarobot_opentelemetry.integrations.fastapi.configure_providers",
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


def test_configure_telemetry_disabled_when_nothing_gets_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "datarobot_opentelemetry.integrations.fastapi.configure_providers",
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
            "datarobot_opentelemetry.integrations.fastapi.configure_providers",
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
        "datarobot_opentelemetry.integrations.fastapi.get_logger_provider",
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
        "datarobot_opentelemetry.integrations.fastapi.FastAPIInstrumentor", None
    )

    otel = OTel()
    with caplog.at_level(logging.WARNING):
        otel.instrument_fastapi_app(object())  # type: ignore[arg-type]

    assert "FastAPIInstrumentor not available" in caplog.text


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

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

import logging
import os
import sys
from dataclasses import dataclass
from typing import cast

from datarobot_opentelemetry.enums import EntityType
from datarobot_opentelemetry.logging import RedactingFormatter
from datarobot_opentelemetry.semconv.headers import DataRobotOtelHeaders

logger = logging.getLogger(__name__)


@dataclass
class ConfigureResult:
    tracing_configured: bool
    metrics_configured: bool
    logger_configured: bool


def _configure_stdout_fallback_logging(log_level: int) -> None:
    """Attach a basic stdout handler so logs stay visible when OTLP export can't be configured."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    )
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def configure(
    endpoint: str | None = None,
    entity_type: EntityType | str | None = None,
    entity_id: str | None = None,
    api_key: str | None = None,
    log_level: int = logging.INFO,
    metrics_export_interval: int = 60000,
) -> ConfigureResult:
    """
    Configures the OpenTelemetry integration with the provided parameters.

    Args:
        endpoint (str): The endpoint URL for the telemetry data.
        entity_type (EntityType | str): The type of the entity being monitored, e.g.
            EntityType.DEPLOYMENT or EntityType.WORKLOAD. Accepts any string too, since
            the platform can introduce entity kinds before this enum is updated.
        entity_id (str): The unique identifier for the entity being monitored.
        api_key (Optional[str]): An optional API key for authentication, if required by the telemetry backend.
        log_level (int): The logging level for the OpenTelemetry integration. Defaults to logging.INFO.
        metrics_export_interval (int): The interval in milliseconds for exporting metrics. Defaults to 60000.
    Returns:
        ConfigureResult: An object indicating which signals were successfully configured.
    """
    # Ensure that OpenTelemetry dependencies are available before proceeding with configuration.
    try:
        from opentelemetry import (
            _logs,
            metrics,
            trace,
        )
        from opentelemetry._logs._internal import (
            ProxyLoggerProvider,
        )
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.logging import (
            LoggingInstrumentor,
        )
        from opentelemetry.metrics._internal import (
            _ProxyMeterProvider,
        )
        from opentelemetry.sdk._logs import (
            LoggerProvider,
        )
        from opentelemetry.sdk._logs.export import (
            BatchLogRecordProcessor,
        )
        from opentelemetry.sdk.metrics import (
            MeterProvider,
        )
        from opentelemetry.sdk.metrics.export import (
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import (
            Resource,
        )
        from opentelemetry.sdk.trace import (
            TracerProvider,
        )
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
        )
        from opentelemetry.trace import (
            NoOpTracer,
            ProxyTracerProvider,
        )
        from opentelemetry.util.re import parse_env_headers
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "OpenTelemetry integration dependencies are not installed. "
            "Install with: pip install 'datarobot-opentelemetry[integrations]'"
        ) from exc

    def _parse_otel_env_headers() -> dict[str, str]:
        """Parse OTEL_EXPORTER_OTLP_HEADERS into a dict of header name -> value.

        Uses OpenTelemetry's own ``parse_env_headers`` so we honor exactly the same
        parsing rules (and ``liberal`` leniency) as the OTLP exporters do, ensuring
        every header the user configured is preserved. Keys are lower-cased by the
        parser.
        """
        env_var_headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS") or ""
        return dict(parse_env_headers(env_var_headers, liberal=True))

    def _parse_dr_headers(
        env_headers: dict[str, str],
    ) -> tuple[str | None, str | None, str | None]:
        api_key = env_headers.get(DataRobotOtelHeaders.API_KEY.lower())

        entity_type = None
        entity_id = None
        if (
            dr_service_name := env_headers.get(
                DataRobotOtelHeaders.ENTITY_ID.lower(), ""
            )
        ) and "-" in dr_service_name:
            # If it contains a hyphen, we assume it's an entity identifier in the format "type-id" and split it.
            parts = dr_service_name.split("-", 1)
            entity_type = parts[0]
            if len(parts) == 2:
                entity_id = parts[1]

        return api_key, entity_type, entity_id

    otel_headers = _parse_otel_env_headers()
    dr_api_key, dr_entity_type, dr_entity_id = _parse_dr_headers(otel_headers)

    endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    api_key = api_key or dr_api_key or os.environ.get("DATAROBOT_API_TOKEN")
    entity_type = (
        entity_type or dr_entity_type or os.environ.get("DATAROBOT_ENTITY_TYPE")
    )
    entity_id = entity_id or dr_entity_id or os.environ.get("DATAROBOT_ENTITY_ID")

    missing = [
        name
        for name, value in (
            ("endpoint", endpoint),
            ("api_key", api_key),
            ("entity_type", entity_type),
            ("entity_id", entity_id),
        )
        if not value
    ]
    if missing:
        logger.warning(
            "Skipping OTel export configuration, missing: %s. "
            "Provide them as arguments or via OTEL_EXPORTER_OTLP_ENDPOINT / "
            "DATAROBOT_API_TOKEN / DATAROBOT_ENTITY_TYPE / DATAROBOT_ENTITY_ID. "
            "Falling back to stdout logging.",
            ", ".join(missing),
        )
        _configure_stdout_fallback_logging(log_level)
        return ConfigureResult(
            tracing_configured=False,
            metrics_configured=False,
            logger_configured=False,
        )

    assert (
        endpoint and api_key and entity_type and entity_id
    )  # narrowed by the check above

    otel_headers[DataRobotOtelHeaders.ENTITY_ID.lower()] = f"{entity_type}-{entity_id}"
    otel_headers[DataRobotOtelHeaders.API_KEY.lower()] = api_key

    base_endpoint = endpoint.rstrip("/")

    def _signal_endpoint(signal: str) -> str:
        suffix = f"/v1/{signal}"
        if base_endpoint.endswith(suffix):
            return base_endpoint
        return f"{base_endpoint}{suffix}"

    def _build_dr_resource() -> Resource:
        """Build an OTel Resource with DataRobot-standard attributes.

        Deliberately duplicates (not imports) datarobot.core.otel.create_dr_resource()
        in public_api_client: that function's own logic is tiny and stable, but the
        `datarobot` package it lives in unconditionally pulls in pandas/numpy as base
        dependencies - too much weight to add to this package just to reuse ~15 lines
        of attribute-building with no real logic of its own. Keep this in sync with
        create_dr_resource() if that ever changes.
        """
        attrs: dict[str, str] = {"datarobot.service.priority": "p1"}
        if not os.environ.get("OTEL_SERVICE_NAME"):
            attrs["service.name"] = f"{entity_type}-{entity_id}"
        attrs["datarobot.application.id"] = entity_id
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            pod_name = os.environ.get("HOSTNAME")
            if pod_name:
                attrs["k8s.pod.name"] = pod_name
        version = os.environ.get("APP_VERSION") or os.environ.get("SERVICE_VERSION")
        if version:
            attrs["service.version"] = version
        return Resource.create(attrs)

    tracing_configured = False
    metrics_configured = False
    logger_configured = False

    base_resource = _build_dr_resource()

    # Configure tracing
    try:
        trace_provider = cast(TracerProvider, trace.get_tracer_provider())
        tracer = trace_provider.get_tracer(__name__)
        internal_tracer = getattr(tracer, "_tracer", None)
        trace_exporter = OTLPSpanExporter(
            endpoint=_signal_endpoint("traces"), headers=otel_headers
        )
        if isinstance(trace_provider, ProxyTracerProvider) and isinstance(
            internal_tracer, NoOpTracer
        ):
            # Safe to set TracerProvider since none exists yet
            configured_trace_provider = TracerProvider(resource=base_resource)
            configured_trace_provider.add_span_processor(
                BatchSpanProcessor(trace_exporter)
            )
            trace.set_tracer_provider(configured_trace_provider)
            tracing_configured = True
        else:
            logger.info("Opentelemetry TracerProvider is already configured.")
            if hasattr(trace_provider, "add_span_processor"):
                logger.info("Adding span processor to existing TracerProvider.")
                trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
                tracing_configured = True

    except Exception as e:
        logger.warning("Failed to initialize TraceProvider for DataRobot", exc_info=e)

    # configure logging
    try:
        logger_provider_current = _logs.get_logger_provider()

        # Check if Logs provider is uninitialized
        log_exporter = OTLPLogExporter(
            endpoint=_signal_endpoint("logs"), headers=otel_headers
        )
        if isinstance(logger_provider_current, ProxyLoggerProvider):
            configured_logger_provider = LoggerProvider(resource=base_resource)

            configured_logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(log_exporter)
            )
            LoggingInstrumentor().instrument(
                logger_provider=configured_logger_provider, log_level=log_level
            )
            _logs.set_logger_provider(configured_logger_provider)

            logger_configured = True

        else:
            logger.info("OTEL LoggerProvider is already configured.")
            if hasattr(logger_provider_current, "add_log_record_processor"):
                logger.info("Adding log record processor to existing LoggerProvider.")
                logger_provider_current.add_log_record_processor(
                    BatchLogRecordProcessor(log_exporter)
                )
                logger_configured = True
    except Exception as e:
        logger.warning("Failed to initialize LoggerProvider for DataRobot", exc_info=e)

    # configure metrics
    try:
        meter_provider_current = metrics.get_meter_provider()
        # Check if Metrics is uninitialized
        if isinstance(meter_provider_current, _ProxyMeterProvider):
            metric_exporter = OTLPMetricExporter(
                endpoint=_signal_endpoint("metrics"), headers=otel_headers
            )
            metric_reader = PeriodicExportingMetricReader(
                metric_exporter, export_interval_millis=metrics_export_interval
            )
            configured_meter_provider = MeterProvider(
                metric_readers=[metric_reader], resource=base_resource
            )
            metrics.set_meter_provider(configured_meter_provider)
            metrics_configured = True
        else:
            logger.warning("OTEL MeterProvider already set. Cannot override.")
    except Exception as e:
        logger.warning("Failed to initialize MetricsProvider for DataRobot", exc_info=e)

    return ConfigureResult(
        tracing_configured=tracing_configured,
        metrics_configured=metrics_configured,
        logger_configured=logger_configured,
    )

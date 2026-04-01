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
from dataclasses import dataclass
from typing import Optional, cast

from datarobot_opentelemetry.semconv.headers import DataRobotOtelHeaders

logger = logging.getLogger(__name__)


@dataclass
class ConfigureResult:
    tracing_configured: bool
    metrics_configured: bool
    logger_configured: bool


def configure(
    endpoint: str,
    entity_type: str,
    entity_id: str,
    api_key: Optional[str] = None,
    log_level: int = logging.INFO,
    metrics_export_interval: int = 60000,
) -> ConfigureResult:
    """
    Configures the OpenTelemetry integration with the provided parameters.

    Args:
        endpoint (str): The endpoint URL for the telemetry data.
        entity_type (str): The type of the entity being monitored (e.g., "deployment", "workload").
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
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "OpenTelemetry integration dependencies are not installed. "
            "Install with: pip install 'datarobot-opentelemetry[integrations]'"
        ) from exc

    api_key = api_key or os.environ.get("DATAROBOT_API_TOKEN")
    if not api_key:
        raise ValueError(
            "API key is required for authentication. Provide it as an argument or set the DATAROBOT_API_TOKEN environment variable."
        )

    otel_headers = {
        DataRobotOtelHeaders.ENTITY_ID: f"{entity_type}-{entity_id}",
        DataRobotOtelHeaders.API_KEY: api_key,
    }

    base_endpoint = endpoint.rstrip("/")

    def _signal_endpoint(signal: str) -> str:
        suffix = f"/v1/{signal}"
        if base_endpoint.endswith(suffix):
            return base_endpoint
        return f"{base_endpoint}{suffix}"

    tracing_configured = False
    metrics_configured = False
    logger_configured = False

    # Configure tracing
    try:
        trace_provider = cast(TracerProvider, trace.get_tracer_provider())
        tracer = trace_provider.get_tracer(__name__)
        internal_tracer = getattr(tracer, "_tracer", None)
        if isinstance(trace_provider, ProxyTracerProvider) and isinstance(
            internal_tracer, NoOpTracer
        ):
            # Safe to set TracerProvider since none exists yet
            trace_resource = Resource.create({"datarobot.service.priority": "p1"})
            trace_exporter = OTLPSpanExporter(
                endpoint=_signal_endpoint("traces"), headers=otel_headers
            )
            configured_trace_provider = TracerProvider(resource=trace_resource)
            configured_trace_provider.add_span_processor(
                BatchSpanProcessor(trace_exporter)
            )
            trace.set_tracer_provider(configured_trace_provider)
            tracing_configured = True
        else:
            logger.warning(
                "Opentelemetry TracerProvider is already configured and in use. Skipping Otel configuration for DataRobot to avoid conflicts."
            )

    except Exception as e:
        logger.warning("Failed to initialize TraceProvider for DataRobot", exc_info=e)

    # configure logging
    try:
        logger_provider_current = _logs.get_logger_provider()

        # Check if Logs provider is uninitialized
        if isinstance(logger_provider_current, ProxyLoggerProvider):
            logger_resource = Resource.create({"datarobot.service.priority": "p1"})
            configured_logger_provider = LoggerProvider(resource=logger_resource)
            _logs.set_logger_provider(configured_logger_provider)

            log_exporter = OTLPLogExporter(
                endpoint=_signal_endpoint("logs"), headers=otel_headers
            )
            configured_logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(log_exporter)
            )
            LoggingInstrumentor().instrument(
                logger_provider=configured_logger_provider, log_level=log_level
            )

            logger_configured = True

        else:
            logger.warning(
                "OTEL LoggerProvider is already configured and in use. Skipping Otel configuration for DataRobot to avoid conflicts."
            )
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
            metric_resource = Resource.create({"datarobot.service.priority": "p1"})
            configured_meter_provider = MeterProvider(
                metric_readers=[metric_reader], resource=metric_resource
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

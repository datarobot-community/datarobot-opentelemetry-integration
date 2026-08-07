# datarobot-opentelemetry

OpenTelemetry semantic conventions and utilities for DataRobot telemetry integration.

## Installation

```bash
# Install base package with semantic conventions only
pip install datarobot-opentelemetry

# Install with integration module for automatic OpenTelemetry setup
pip install datarobot-opentelemetry[integrations]

# Install with FastAPI instrumentation on top of the integration module
pip install datarobot-opentelemetry[fastapi]
```

The `[integrations]` extra includes all OpenTelemetry dependencies needed for the `configure()` function. The `[fastapi]` extra additionally includes FastAPI/httpx/requests/SQLAlchemy auto-instrumentation and pulls in `[integrations]` automatically.

## Usage

```python
from datarobot_opentelemetry.semconv import SpanAttributes

# Use constants as span attribute keys
span.set_attribute(SpanAttributes.GEN_AI_REQUEST_MODEL, "gpt-4o")
span.set_attribute(SpanAttributes.GEN_AI_USAGE_INPUT_TOKENS, 128)
span.set_attribute(SpanAttributes.GEN_AI_USAGE_OUTPUT_TOKENS, 64)

# DataRobot-specific attributes
span.set_attribute(SpanAttributes.DATAROBOT_TRACE_NAME, "my-agent-trace")
span.set_attribute(SpanAttributes.DATAROBOT_SESSION_ID, session_id)
```

### Available attribute groups

| Group | Prefix | Description |
|---|---|---|
| Gen AI standard | `gen_ai.*` | OpenTelemetry Gen AI semantic conventions |
| Server | `server.*` | Server address/port |
| Error | `error.*` | Error type |
| DataRobot | `datarobot.*` | DataRobot-specific trace metadata |

All constants live in `datarobot_opentelemetry.semconv.SpanAttributes`.

## How to use integration

The integration module provides automatic configuration of OpenTelemetry tracing, metrics, and logging to send telemetry data to DataRobot backends.

### Basic setup

```python
from datarobot_opentelemetry.integrations import configure

# Configure the OpenTelemetry integration
result = configure(
    endpoint="https://your-telemetry-endpoint.example.com",  # optional if OTEL_EXPORTER_OTLP_ENDPOINT is set
    entity_type="deployment",  # optional if DATAROBOT_ENTITY_TYPE is set
    entity_id="your-entity-id",  # optional if DATAROBOT_ENTITY_ID is set
    api_key="your-api-key",  # optional if DATAROBOT_API_TOKEN is set
)

# Check configuration results
print(f"Tracing configured: {result.tracing_configured}")
print(f"Metrics configured: {result.metrics_configured}")
print(f"Logging configured: {result.logger_configured}")
```

You can also configure entirely from environment variables:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://your-telemetry-endpoint.example.com"
export DATAROBOT_ENTITY_TYPE="deployment"
export DATAROBOT_ENTITY_ID="your-entity-id"
export DATAROBOT_API_TOKEN="your-api-key"
```
or using OTEL specific environment variables that take precedence:
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://your-telemetry-endpoint.example.com"
export OTEL_EXPORTER_OTLP_HEADERS="X-DataRobot-Entity-Id=deployment-<your-entity-id>,X-DataRobot-Api-Key=<your-api-key>"
```

```python
from datarobot_opentelemetry.integrations import configure

result = configure()
```

### Configuration parameters

- **endpoint** (optional argument, required value): OTLP HTTP endpoint URL for telemetry data. If not passed, uses `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **entity_type** (optional argument, required value): Type of entity being monitored, e.g. `EntityType.DEPLOYMENT` or `EntityType.WORKLOAD` (`datarobot_opentelemetry.enums.EntityType`). Accepts any string too, since the platform can introduce entity kinds before this enum is updated. If not passed, uses `DATAROBOT_ENTITY_TYPE`.
- **entity_id** (optional argument, required value): Unique identifier for the entity. If not passed, uses `DATAROBOT_ENTITY_ID`.
- **api_key** (optional argument, required value): API key for authentication. If not passed, uses `DATAROBOT_API_TOKEN`.
- **log_level** (optional): Logging level for the integration (default: `logging.INFO`)
- **metrics_export_interval** (optional): Interval in milliseconds for exporting metrics (default: 60000)

Argument values take precedence over environment variables.

### Advanced usage

After calling `configure()`, standard OpenTelemetry APIs work automatically:

```python
from opentelemetry import trace, metrics

# Get tracer and record spans
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("my-operation") as span:
    span.set_attribute("custom.attribute", "value")
    # Your code here

# Get meter and record metrics  
meter = metrics.get_meter(__name__)
counter = meter.create_counter("my.counter")
counter.add(1)
```

## How to use FastAPI instrumentation

`datarobot_opentelemetry.instrumentations.fastapi` layers FastAPI/httpx/requests/SQLAlchemy
auto-instrumentation and redacted log export on top of `configure()`, instead of
re-implementing provider setup. `configure()` remains the single place that builds
Trace/Log/Metric providers; this module adds what's specific to FastAPI applications.

### Basic setup

```python
from datarobot_opentelemetry.enums import EntityType
from datarobot_opentelemetry.instrumentations.fastapi import OTel

otel = OTel(entity_type=EntityType.CUSTOM_APPLICATION, entity_id="your-entity-id")

# config only needs otel_exporter_otlp_endpoint / otel_exporter_otlp_headers /
# otel_sdk_disabled attributes - any app Settings/Config class works, no inheritance required
result = otel.configure(config)

app = FastAPI()
otel.instrument_fastapi_app(app)
```

### Available methods

- **configure(config)**: applies OTel settings from app config. Call once during startup; a
  second call is a no-op.
- **instrument_fastapi_app(app)**: adds FastAPI/httpx/requests/SQLAlchemy auto-instrumentation.
- **trace** / **meter** / **meter_and_trace**: decorators for tracing and recording call-count
  metrics on a function.
- **span(name)** / **time(name)**: context managers for a manual span or a duration metric.
- **get_logger(name)** / **get_tracer(name)** / **get_meter(name)**: pass-through accessors for
  the configured providers.
- **log_application_start(application_name)**: logs a structured startup line.
- **shutdown()**: flushes and shuts down the configured providers.

`OTel` is a singleton, since only one set of providers can be configured per process.

## How to use uvicorn logging

`datarobot_opentelemetry.instrumentations.uvicorn` routes uvicorn's access/error loggers
through the same formatters and redaction as the rest of the app, and filters out health
check request noise.

```python
from datarobot_opentelemetry.instrumentations.uvicorn import configure_uvicorn_logging

configure_uvicorn_logging(log_format="json", log_level="INFO")
```

## Requirements

- Python 3.10+

## Release History

- See CHANGELOG.md for version-by-version release notes.

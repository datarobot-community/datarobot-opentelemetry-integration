# datarobot-opentelemetry

OpenTelemetry semantic conventions and utilities for DataRobot telemetry integration.

## Installation

```bash
# Install base package with semantic conventions only
pip install datarobot-opentelemetry

# Install with integration module for automatic OpenTelemetry setup
pip install datarobot-opentelemetry[integrations]
```

The `[integrations]` extra includes all OpenTelemetry dependencies needed for the `configure()` function.

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
    endpoint="https://your-telemetry-endpoint.example.com",
    entity_type="deployment",
    entity_id="your-entity-id",
    api_key="your-api-key"  # alternatively, set DATAROBOT_API_TOKEN env var
)

# Check configuration results
print(f"Tracing configured: {result.tracing_configured}")
print(f"Metrics configured: {result.metrics_configured}")
print(f"Logging configured: {result.logger_configured}")
```

### Configuration parameters

- **endpoint** (required): The OTLP HTTP endpoint URL for telemetry data
- **entity_type** (required): Type of entity being monitored (e.g., "deployment", "workload")
- **entity_id** (required): Unique identifier for the entity
- **api_key** (optional): API key for authentication. If not provided, uses `DATAROBOT_API_TOKEN` environment variable
- **log_level** (optional): Logging level for the integration (default: `logging.INFO`)
- **metrics_export_interval** (optional): Interval in milliseconds for exporting metrics (default: 60000)

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

## Requirements

- Python 3.10+

## Release History

- See CHANGELOG.md for version-by-version release notes.

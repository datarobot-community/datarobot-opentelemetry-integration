# datarobot-opentelemetry

OpenTelemetry semantic conventions and utilities for DataRobot telemetry integration.

## Installation

```bash
pip install datarobot-opentelemetry
```

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

## Requirements

- Python 3.12+

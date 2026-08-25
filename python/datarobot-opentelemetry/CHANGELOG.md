# Changelog

All notable changes to this project are documented in this file.

## [0.4.0] - 2026-08-24

### Added

- `SpanAttributes.GEN_AI_AGENT_NAME` (`gen_ai.agent.name`), the OTel GenAI semantic
  convention attribute for identifying the agent that produced a span.

## [0.3.0] - 2026-07-20

### Added

- `fastapi` extra with a new `datarobot_opentelemetry.instrumentations.fastapi` module: an
  `OTel` manager for FastAPI applications that layers FastAPI/httpx/requests/
  SQLAlchemy auto-instrumentation and redacted log export on top of `configure()`,
  instead of re-implementing provider setup. Includes `trace`/`meter`/`meter_and_trace`
  decorators, `span`/`time` context managers, and `OTEL_EXCLUDED_TRACE_SPAN_NAMES`-based
  span exclusion.
- `datarobot_opentelemetry.logging` module with structured (`json`/`text`/`readable`)
  log formatters, `RedactingFormatter` for stripping sensitive values from log output,
  and a `log_api_call` decorator.
- `datarobot_opentelemetry.instrumentations.uvicorn.configure_uvicorn_logging` to route
  uvicorn's access/error loggers through the same formatters and redaction.

### Changed

- `configure()` no longer raises `ValueError` when the endpoint, API key, entity type,
  or entity id are missing. It now logs a warning, falls back to a basic stdout logging
  handler, and returns `ConfigureResult` with every signal `False`, so an app without
  telemetry configured (e.g. local development) still starts and logs normally.
- `instrument_fastapi_app()` now passes `exclude_spans=["send", "receive"]` to
  `FastAPIInstrumentor`, dropping the noisy low-level ASGI spans it otherwise creates
  for every message exchanged during a request/response cycle.
- `OTLPConnectionErrorFilter` now also suppresses the OTLP exporters' own "Failed to
  export ... batch" errors (e.g. a 404 from a misconfigured endpoint path), not just
  connection-refused failures. Previously these were a different failure mode the
  filter didn't cover, so a reachable-but-wrong endpoint still spammed logs forever.

### Fixed

- `TextFormatter`/`ReadableFormatter` now indent every continuation line of the final
  formatted message, not just exception tracebacks. The DataRobot OTel collector's
  recombine operator splits any line that doesn't start with whitespace into its own
  record, so a plain multi-line `logger.info(...)` call (e.g. `log_api_call`'s banner)
  was getting split apart the same way an unindented traceback used to.

## [0.2.1] - 2026-06-017

### Added

- Respect `X-DataRobot-Entity-Id` and `X-DataRobot-Api-Key` DataRobot specific headers
  if provided via `OTEL_EXPORTER_OTLP_HEADERS` environment variable.

## [0.2.0] - 2026-04-01

### Added

- Integration module with `configure()` function for automatic OpenTelemetry setup (tracing, metrics, and logging).
- Support for DataRobot OTLP HTTP endpoints with automatic header injection.
- Documentation for using the integration module with environment variables and custom configuration.

## [0.1.1] - 2026-03-30

### Changed

- Updated package metadata to support Python 3.10+.

## [0.1.0] - 2026-03-30

### Added

- Initial release of datarobot-opentelemetry.
- OpenTelemetry semantic convention constants in `datarobot_opentelemetry.semconv.SpanAttributes`.

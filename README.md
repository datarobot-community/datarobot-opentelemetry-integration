# datarobot-opentelemetry


## Overview

This package provides OpenTelemetry semantic conventions and helper utilities used by DataRobot for telemetry collection.

## Requirements

- **Python**: 3.12 or higher
- **uv**: Package manager and Python virtualenv manager ([install uv](https://docs.astral.sh/uv/getting-started/installation/))
- **Docker**: Required for license header checks (for running `make license-check`)
- **make**: For running development tasks

## Local Development

### Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/datarobot/datarobot-opentelemetry.git
   cd datarobot-opentelemetry
   ```

2. **Install dependencies**:
   ```bash
   cd python/datarobot-opentelemetry
   uv sync
   ```

3. **Verify setup**:
   ```bash
   make help
   ```

### Using the Makefile

The `Makefile` in `python/datarobot-opentelemetry/` provides convenient commands for development. Run `make help` to see all available commands:

**Common commands**:

- `make lint` - Run all linting checks (ruff, black, mypy)
- `make fmt` - Format code and fix imports
- `make test` - Run unit tests
- `make cov` - Run tests with coverage report (opens HTML report in browser)
- `make ci` - Run full CI pipeline (all checks, tests, and license verification)
- `make docs` - Start local documentation server at http://localhost:9002

**Linting & Formatting**:

- `make ruff` - Run ruff linter with automatic fixes
- `make test-ruff` - Check ruff compliance without fixing
- `make black` - Format code with black (via ruff)
- `make test-black` - Check code formatting without applying changes
- `make mypy` - Run mypy type checking

**Testing**:

- `make unit-test` - Run unit tests
- `make test` - Run all tests (unit tests only for now)
- `make cov` - Run tests with coverage metrics

**License Management**:

- `make license-check` - Verify all source files have proper copyright headers
- `make license-fix` - Automatically add/update copyright headers
- `make lib-license-check` - Verify all dependencies have approved licenses

## Usage

TODO: Add basic usage examples and common integration patterns.

## Testing

### Unit Tests

```bash
# Run unit tests only
make unit-test

# Run all tests (unit + integration)
make test

# Run tests with coverage report
make cov
```

The coverage report will be generated as HTML and automatically opened in your browser at `file://$(pwd)/htmlcov/index.html`.

### Integration Tests

**Important**: Integration tests require **Datavolt** to be running locally. Datavolt provides the OpenTelemetry collector and DataRobot backend services needed for the tests.

After starting Datavolt, run integration tests with:

```bash
cd python/datarobot-opentelemetry

# Run integration tests with default local Datavolt configuration
make integration-test

# Or run with custom endpoint and credentials
DR_OTEL_ENDPOINT=http://0.0.0.0:4318 \
DR_ENTITY_TYPE=deployment \
DR_ENTITY_ID=68af4e4dab41f0ebc9badb49 \
DATAROBOT_API_TOKEN=datavolt \
DATAVOLT_URL=http://0.0.0.0:7000 \
DATAVOLT_USER=datavolt \
DATAVOLT_PASSWORD=datavolt \
make integration-test
```

**Environment variables** (all optional with sensible defaults for local development):
- `DR_OTEL_ENDPOINT` - OpenTelemetry collector endpoint (default: `http://0.0.0.0:4318`)
- `DR_ENTITY_TYPE` - Entity type being monitored (default: `deployment`)
- `DR_ENTITY_ID` - Unique entity ID (default: `68af4e4dab41f0ebc9badb49`)
- `DATAROBOT_API_TOKEN` - API token for authentication (default: `datavolt`)
- `DATAVOLT_URL` - Datavolt backend URL (default: `http://0.0.0.0:7000`)
- `DATAVOLT_USER` - Datavolt username (default: `datavolt`)
- `DATAVOLT_PASSWORD` - Datavolt password (default: `datavolt`)

## Linting and Formatting

All code must pass linting checks before being merged. We use:

- **ruff**: Fast Python linter for style and import checks
- **black**: Code formatting (via ruff)
- **mypy**: Static type checking with strict mode

### Quick Fix

To automatically fix most issues:

```bash
make fmt
```

This will:
1. Format code with black
2. Fix imports with ruff

### Verify Compliance

To check without making changes:

```bash
make lint
```

This will run all checks: ruff, black, and mypy.

### Individual Tools

```bash
make test-ruff   # Check ruff compliance
make test-black  # Check formatting compliance
make mypy        # Run type checking
```

## Contributing

We welcome contributions! To contribute to this project:

1. **Setup local development**: Follow the [Local Development](#local-development) section
2. **Make your changes**: Create a feature branch
3. **Verify quality**: Run `make ci` to ensure all checks pass:
   - Linting (ruff, black, mypy)
   - Tests pass
   - License headers are correct
4. **Commit and push**: Submit a pull request with a clear description of your changes

### Pre-commit Checklist

Before pushing, ensure:

```bash
# Run full CI pipeline
make ci

# Or run individual checks:
make lint      # All linting checks
make test      # Unit tests
make license-check  # Copyright headers
```

All checks must pass before your PR will be reviewed.

## Release Process

TODO: Add release/versioning guidance and publishing steps.

# Project Guidelines

## Scope
- These guidelines apply to the whole repository.
- The primary code package is in `python/datarobot-opentelemetry`.

## Architecture
- This repository contains a Python package that provides:
  - semantic conventions in `src/datarobot_opentelemetry/semconv`
  - optional OpenTelemetry integration helpers in `src/datarobot_opentelemetry/integrations`
- Keep public APIs stable and prefer additive changes.

## Build And Test
- Use `uv` for dependency and command execution.
- Run commands from `python/datarobot-opentelemetry` unless a task explicitly targets repo root.
- Core local validation commands:
  - `make lint`
  - `make test`
  - `make ci`
- Preferred fast unit-test command:
  - `uv run pytest -v tests/unit`

## Coding Conventions
- Python version target is 3.10+ (see `pyproject.toml`).
- Lint/format/type tools are authoritative:
  - `ruff` for linting and formatting
  - `mypy --strict` for typing
- Add or update unit tests for behavior changes in `tests/unit`.
- Keep changes focused; avoid unrelated refactors.

## Release And Versioning
- Package version is defined in `python/datarobot-opentelemetry/pyproject.toml`.
- User-visible changes should include a changelog update in `python/datarobot-opentelemetry/CHANGELOG.md`.

## Licensing
- Source headers are validated via SkyWalking Eyes (`make license-check`).
- Preserve existing header format and year pattern conventions in this repo.

## References
- See `README.md` for repo-level workflow and release process.
- See `CONTRIBUTING.md` for contribution expectations.
- See `python/datarobot-opentelemetry/Makefile` for canonical developer commands.

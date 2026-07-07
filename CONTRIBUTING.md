# Contributing

Thanks for your interest in contributing to this project.

## Development setup

1. Clone the repository.
2. Change into the Python package directory.
3. Install dependencies with uv.

```bash
git clone git@github.com:datarobot-community/datarobot-opentelemetry-integration.git
cd datarobot-opentelemetry-integration/python/datarobot-opentelemetry
uv sync
```

## Local validation

Run these commands before opening a pull request:

```bash
make lint
make test
make license-check
```

Or run the full local pipeline:

```bash
make ci
```

## Pull requests

1. Create a branch from main.
2. Keep pull requests focused and small where possible.
3. Include tests for behavior changes.
4. Update documentation and changelog when relevant.
5. Ensure all GitHub Actions checks pass.

## Code style and quality

- Linting and formatting: ruff
- Static typing: mypy (strict)
- Tests: pytest

## Licensing

By submitting a contribution, you agree your contribution may be distributed under the license used by this repository.

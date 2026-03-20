.DEFAULT_GOAL := help
.PHONY: help
help:
	@echo "====================="
	@echo "🛠  Available Commands"
	@echo "====================="
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

TESTS ?= .

.PHONY: ci
ci: test-ruff test-black mypy license-check test ## Runs all CI checks including tests

########################################
##@ Lint
.PHONY: lint
lint: test-ruff test-black mypy ## Runs linting targets

.PHONY: ruff
ruff: ## Run ruff with fix
	@echo "🧹 Linting with ruff.."
	uv run ruff check --fix src

.PHONY: test-ruff
test-ruff: ## Run ruff checks
	uv run ruff check src

.PHONY: black
black: ## Run black linting
	@echo "🧹 Linting with black.."
	uv run ruff format src

.PHONY: test-black
test-black: ## Run black checks
	uv run ruff format --check src

.PHONY: fmt
fmt: black  ## Reformats changed code
	@echo "Running code formatters"
	uv run ruff check --select I --fix src

.PHONY: mypy
mypy: ## Run mypy checks
	@echo "🧹 Linting with mypy.."
	uv run mypy --pretty --strict src

########################################
##@ Licenses
.PHONY: license-check
license-check: ## Run license check
	docker run  --rm -v $(shell pwd)/../../:/github/workspace ghcr.io/apache/skywalking-eyes/license-eye:latest -v info -c .licenserc.yaml header check

.PHONY: license-fix
license-fix: ## Run license fix
	docker run  --rm -v $(shell pwd)/../../:/github/workspace ghcr.io/apache/skywalking-eyes/license-eye:latest -v info -c .licenserc.yaml header fix

.PHONY: lib-license-check
lib-license-check: ## Checks all dependencies have only approved licenses
	license_scanner -m whitelist

########################################
##@ Test
.PHONY: unit-test
unit-test: ## Runs unit tests
	uv run pytest -svvv tests/unit

.PHONY: test
test: unit-test ## Run all tests

.PHONY: cov
cov: ## Runs code tests with code coverage
	uv run pytest -s -v  --cov-report term --cov-report html --cov src/datarobot_opentelemetry ./tests
	@echo "open file://`pwd`/htmlcov/index.html"

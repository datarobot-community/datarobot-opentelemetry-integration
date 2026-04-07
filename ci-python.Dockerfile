FROM datarobotdev/mirror_chainguard_datarobot.com_python-fips:3.12-dev

USER root

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PATH="/opt/app/.venv/bin:$PATH" \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT="/opt/app/.venv" \
    APP_VERSION="0.0.1"

# Install system dependencies
RUN apk update && \
    apk add ca-certificates git make shadow jq && \
    python3.12 -m pip install --upgrade pip

WORKDIR /opt/app

# Copy the actual app code
COPY python/datarobot-opentelemetry .

# Install app dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN git config --global --add safe.directory /opt/app && \
    uv version -- $APP_VERSION && \
    uv sync --extra integrations --frozen

ENV RUFF_CACHE_DIR=/tmp
USER nonroot

ENTRYPOINT []

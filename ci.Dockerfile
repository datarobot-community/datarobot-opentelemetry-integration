FROM datarobotdev/mirror_chainguard_datarobot.com_python-fips:3.12-dev

USER root

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore 

# Install system dependencies
# Install system dependencies
RUN apk update && \
    apk upgrade --no-cache && \
    apk add ca-certificates git make shadow jq && \
    python3.12 -m pip install --upgrade pip

WORKDIR /opt/datarobotopentelemetry

# Copy the actual app code
COPY . .

ENV RUFF_CACHE_DIR=/tmp
USER nonroot

ENTRYPOINT []

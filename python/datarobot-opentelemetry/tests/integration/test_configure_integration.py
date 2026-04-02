# Copyright 2026 DataRobot, Inc. and its affiliates.
#
# All rights reserved.
#
# DataRobot, Inc. Confidential.
#
# This is unpublished proprietary source code of DataRobot, Inc.
# and its affiliates.
#
# The copyright notice above does not evidence any actual or intended
# publication of such source code.

"""
Integration test for datarobot_opentelemetry.integrations.configure().

Configuration values can be provided through environment variables and
fall back to defaults suitable for local Datavolt development:
    DR_OTEL_ENDPOINT
    DR_ENTITY_TYPE
    DR_ENTITY_ID
    DATAROBOT_API_TOKEN
    DATAVOLT_URL
    DATAVOLT_USER
    DATAVOLT_PASSWORD
    DR_ORG_ID

Run:
    DR_OTEL_ENDPOINT=http://0.0.0.0:4318 \
    pytest tests/integration/test_configure_integration.py -v
"""

import logging
import os
import time
import uuid
from base64 import b64encode
from json import loads
from urllib.parse import urlencode
from urllib import error, request

import pytest
from opentelemetry import _logs, metrics, trace

from datarobot_opentelemetry.integrations import ConfigureResult, configure
from datarobot_opentelemetry.semconv.traces import SpanAttributes

WAIT_TIMEOUT_SECONDS = 60.0
WAIT_INTERVAL_SECONDS = 2.0
TEST_MARKER_KEY = "integration.test.run_id"

@pytest.fixture(scope="module")
def dr_otel_endpoint() -> str:
    return os.environ.get("DR_OTEL_ENDPOINT", "http://0.0.0.0:4318")


@pytest.fixture(scope="module")
def dr_entity_type() -> str:
    return os.environ.get("DR_ENTITY_TYPE", "deployment")


@pytest.fixture(scope="module")
def dr_entity_id() -> str:
    return os.environ.get("DR_ENTITY_ID", "68af4e4dab41f0ebc9badb49")


@pytest.fixture(scope="module")
def datarobot_api_token() -> str:
    return os.environ.get("DATAROBOT_API_TOKEN", "datavolt")


@pytest.fixture(scope="module")
def datavolt_url() -> str:
    return os.environ.get("DATAVOLT_URL", "http://0.0.0.0:7000")


@pytest.fixture(scope="module")
def datavolt_user() -> str:
    return os.environ.get("DATAVOLT_USER", "datavolt")


@pytest.fixture(scope="module")
def datavolt_password() -> str:
    return os.environ.get("DATAVOLT_PASSWORD", "datavolt")


@pytest.fixture(scope="module")
def dr_org_id() -> str:
    return os.environ.get("DR_ORG_ID", "57eb3347d75f1670ebc5c4bd")


@pytest.fixture(scope="module")
def test_run_id() -> str:
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def datavolt_headers(
    datarobot_api_token: str,
    datavolt_user: str,
    datavolt_password: str,
) -> dict[str, str]:
    basic_auth = b64encode(f"{datavolt_user}:{datavolt_password}".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {basic_auth}",
        "X-DataRobot-Api-Key": datarobot_api_token,
    }


def _datavolt_get_json(
    datavolt_url: str,
    path: str,
    headers: dict[str, str],
    query_params: dict[str, object] | None = None,
) -> dict[str, object]:
    encoded_query = f"?{urlencode(query_params, doseq=True)}" if query_params else ""
    req = request.Request(
        f"{datavolt_url}{path}{encoded_query}",
        headers=headers,
        method="GET",
    )
    with request.urlopen(req, timeout=10) as resp:
        payload = resp.read().decode("utf-8")
    data = loads(payload)
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected Datavolt response type for {path}: {type(data).__name__}")
    return data


def _wait_until(predicate, description: str) -> None:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (error.HTTPError, error.URLError, ValueError, KeyError, TypeError) as exc:
            last_error = exc
        time.sleep(WAIT_INTERVAL_SECONDS)
    if last_error is not None:
        pytest.fail(f"Timed out waiting for {description}. Last error: {last_error}")
    pytest.fail(f"Timed out waiting for {description}")


def _wait_for_services(
    datavolt_url: str,
    datavolt_headers: dict[str, str],
    dr_org_id: str,
    signal: str,
) -> list[str]:
    service_names: list[str] = []
    service_paths = {
        "traces": f"/api/v1/otel/{dr_org_id}/services",
        "logs": f"/api/v1/otel/{dr_org_id}/logs/services",
        "metrics": f"/api/v1/otel/{dr_org_id}/metrics/services",
    }
    if signal not in service_paths:
        raise ValueError(f"Unsupported OTEL signal: {signal}")

    def _has_services() -> bool:
        nonlocal service_names
        response = _datavolt_get_json(
            datavolt_url,
            service_paths[signal],
            datavolt_headers,
        )
        data = response.get("data", [])
        if not isinstance(data, list):
            return False
        service_names = [entry.get("name", "") for entry in data if isinstance(entry, dict)]
        service_names = [name for name in service_names if name]
        return bool(service_names)

    _wait_until(_has_services, f"Datavolt {signal} services")
    return service_names


@pytest.fixture(scope="module", autouse=True)
def ensure_otel_storage(
    datarobot_api_token: str,
    datavolt_url: str,
    datavolt_user: str,
    datavolt_password: str,
    dr_org_id: str,
) -> None:
    url = f"{datavolt_url}/api/v1/storages/otel"
    payload = (
        "{"
        f'"owner_type":"org",'
        f'"owner_id":"{dr_org_id}",'
        '"number_of_shards":1,'
        '"number_of_replicas":0'
        "}"
    ).encode("utf-8")
    basic_auth = b64encode(f"{datavolt_user}:{datavolt_password}".encode("utf-8")).decode("ascii")
    req = request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {basic_auth}",
            "X-DataRobot-Api-Key": datarobot_api_token,
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=10) as resp:
            status = resp.getcode()
    except error.HTTPError as exc:
        status = exc.code
    except error.URLError as exc:
        pytest.fail(f"Unable to call OTEL storage setup API at {url}: {exc}")

    assert status in (200, 201, 409), (
        f"Unexpected status from OTEL storage setup API: {status}"
    )


@pytest.fixture(scope="module")
def configured_result(
    dr_otel_endpoint: str,
    dr_entity_type: str,
    dr_entity_id: str,
    datarobot_api_token: str,
) -> ConfigureResult:
    return configure(
        endpoint=dr_otel_endpoint,
        entity_type=dr_entity_type,
        entity_id=dr_entity_id,
        api_key=datarobot_api_token,
    )


def test_configure_result(configured_result):
    assert isinstance(configured_result, ConfigureResult)
    assert configured_result.tracing_configured, "Tracing was not configured"
    assert configured_result.metrics_configured, "Metrics were not configured"
    assert configured_result.logger_configured, "Logger was not configured"


@pytest.mark.usefixtures("configured_result")
def test_emit_trace(
    dr_entity_type: str,
    dr_entity_id: str,
    datavolt_url: str,
    datavolt_headers: dict[str, str],
    dr_org_id: str,
    test_run_id: str,
):
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("integration-test-span") as span:
        span.set_attribute(
            SpanAttributes.DATAROBOT_TRACE_NAME,
            f"{dr_entity_type}-{dr_entity_id}",
        )
        span.set_attribute(SpanAttributes.DATAROBOT_SESSION_ID, dr_entity_id)
        span.set_attribute(SpanAttributes.GEN_AI_OPERATION_NAME, "integration-test")
        span.set_attribute(SpanAttributes.GEN_AI_PROVIDER_NAME, "datarobot")
        span.set_attribute(SpanAttributes.GEN_AI_REQUEST_MODEL, "test-model")
        span.set_attribute(SpanAttributes.GEN_AI_USAGE_INPUT_TOKENS, 10)
        span.set_attribute(SpanAttributes.GEN_AI_USAGE_OUTPUT_TOKENS, 20)
        span.set_attribute(SpanAttributes.DATAROBOT_INPUT_VALUE, "hello from integration test")
        span.set_attribute(SpanAttributes.DATAROBOT_OUTPUT_VALUE, "hello back")
        span.set_attribute(TEST_MARKER_KEY, test_run_id)
        span.add_event("integration-test-event")

    res = trace.get_tracer_provider().force_flush()  # type: ignore[attr-defined]
    assert res is True, "Traces flush failed"

    def _trace_is_retrievable() -> bool:
        services = _wait_for_services(datavolt_url, datavolt_headers, dr_org_id, "traces")
        response = _datavolt_get_json(
            datavolt_url,
            f"/api/v1/otel/{dr_org_id}/traces",
            datavolt_headers,
            {
                "service_name": services,
                "search_keys": [TEST_MARKER_KEY],
                "search_values": [test_run_id],
                "limit": 50,
            },
        )
        total = response.get("total", 0)
        return isinstance(total, int) and total > 0

    _wait_until(_trace_is_retrievable, "trace retrieval from Datavolt")


@pytest.mark.usefixtures("configured_result")
def test_emit_metric(
    dr_entity_type: str,
    dr_entity_id: str,
    datavolt_url: str,
    datavolt_headers: dict[str, str],
    dr_org_id: str,
    test_run_id: str,
):
    meter = metrics.get_meter(__name__)
    metric_name = f"integration.test.counter.{test_run_id}"
    counter = meter.create_counter(
        name=metric_name,
        description="Counter emitted by the integration test",
        unit="1",
    )
    counter.add(1, {
        SpanAttributes.DATAROBOT_TRACE_NAME: f"{dr_entity_type}-{dr_entity_id}",
        SpanAttributes.GEN_AI_OPERATION_NAME: "integration-test",
        SpanAttributes.GEN_AI_PROVIDER_NAME: "datarobot",
    })

    res = metrics.get_meter_provider().force_flush()  # type: ignore[attr-defined]
    assert res is True, "Metrics flush failed"

    def _metric_is_retrievable() -> bool:
        services = _wait_for_services(datavolt_url, datavolt_headers, dr_org_id, "metrics")
        for service_name in services:
            response = _datavolt_get_json(
                datavolt_url,
                f"/api/v1/otel/{dr_org_id}/metrics/available_metrics",
                datavolt_headers,
                {
                    "service_name": service_name,
                },
            )
            data = response.get("data", [])
            if not isinstance(data, list):
                continue
            metric_names = [entry.get("name") for entry in data if isinstance(entry, dict)]
            if metric_name in metric_names:
                return True
        return False

    _wait_until(_metric_is_retrievable, "metric retrieval from Datavolt")


@pytest.mark.usefixtures("configured_result")
def test_emit_log(
    dr_entity_type: str,
    dr_entity_id: str,
    datavolt_url: str,
    datavolt_headers: dict[str, str],
    dr_org_id: str,
    test_run_id: str,
):
    log = logging.getLogger("integration-test")
    log.setLevel(logging.INFO)
    log.info(
        "Integration test log record",
        extra={
            SpanAttributes.DATAROBOT_TRACE_NAME: f"{dr_entity_type}-{dr_entity_id}",
            SpanAttributes.DATAROBOT_SESSION_ID: dr_entity_id,
            SpanAttributes.GEN_AI_OPERATION_NAME: "integration-test",
            SpanAttributes.GEN_AI_PROVIDER_NAME: "datarobot",
            SpanAttributes.DATAROBOT_INPUT_VALUE: "hello from integration test",
            SpanAttributes.DATAROBOT_OUTPUT_VALUE: "hello back",
            TEST_MARKER_KEY: test_run_id,
        },
    )

    res = _logs.get_logger_provider().force_flush()  # type: ignore[attr-defined]
    assert res is True, "Logs flush failed"

    def _log_is_retrievable() -> bool:
        services = _wait_for_services(datavolt_url, datavolt_headers, dr_org_id, "logs")
        response = _datavolt_get_json(
            datavolt_url,
            f"/api/v1/otel/{dr_org_id}/logs",
            datavolt_headers,
            {
                "service_name": services,
                "search_keys": [TEST_MARKER_KEY],
                "search_values": [test_run_id],
                "limit": 50,
            },
        )
        total = response.get("total", 0)
        return isinstance(total, int) and total > 0

    _wait_until(_log_is_retrievable, "log retrieval from Datavolt")
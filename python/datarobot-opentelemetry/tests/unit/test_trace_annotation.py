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
import pytest

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, InMemorySpanExporter

from datarobot_opentelemetry.annotations import otel_span


@pytest.fixture
def memory_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def tracer(memory_exporter: InMemorySpanExporter) -> Tracer:
    memory_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    span_processor = SimpleSpanProcessor(memory_exporter)
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)
    return tracer_provider.get_tracer(TRACER_NAME)


def test_trace_annotation_sync(memory_exporter: InMemorySpanExporter, tracer: Tracer) -> None:
     @otel_span("sna", tracer=tracer, attributes={"foo": "bar"})
     def func2(a: int, b: int) -> int:
         return a + b

     @otel_span(tracer=tracer)
     def func1(a: int, b: int, c: int) -> int:
         return func2(a, b) * c

     assert func1(1, 2, 3) == 9

     captured_spans = memory_exporter.get_finished_spans()
     assert len(captured_spans) == 2
     # TODO: more checks -- names on each

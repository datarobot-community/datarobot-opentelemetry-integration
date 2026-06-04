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
import inspect
from functools import wraps
from typing import Optional

from opentelemetry.trace import Tracer, get_tracer_provider

from datarobot_opentelemetry.semconv.traces import TRACER_NAME


def otel_span(
    name: Optional[str] = None,
    tracer: Optional[Tracer] = None,
    attributes: Optional[dict[str, str]] = None,
):
    """Decorator: wrap a sync function, async coroutine, or async generator in an OTel span.

    Span name defaults to the decorated function's ``__name__``.
    ``isasyncgenfunction`` is checked before ``iscoroutinefunction`` because async
    generators satisfy the coroutine check in some Python builds.
    """

    def decorator(func):
        _name = name or func.__name__
        _tracer = tracer or get_tracer_provider().get_tracer(TRACER_NAME)

        def _set_attributes(s, attributes: Optional[dict[str, str]]):
            for k, v in (attributes or {}).items():
                s.set_attribute(k, v)

        if inspect.isasyncgenfunction(func):

            @wraps(func)
            async def async_gen_wrapper(*args, **kwargs):
                with _tracer.start_as_current_span(_name) as span:
                    _set_attributes(span)
                    async for item in func(*args, **kwargs):
                        yield item

            return async_gen_wrapper

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                with _tracer.start_as_current_span(_name) as span:
                    _set_attributes(span, attributes)
                    return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with _tracer.start_as_current_span(_name) as span:
                _set_attributes(span, attributes)
                return func(*args, **kwargs)

        return sync_wrapper

    return decorator

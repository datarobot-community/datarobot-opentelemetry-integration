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


from datarobot_opentelemetry.semconv import SpanAttributes
from datarobot_opentelemetry import SpanAttributes as TopLevelSpanAttributes


def test_span_attributes_importable() -> None:
    assert SpanAttributes is TopLevelSpanAttributes


def test_gen_ai_standard_attributes() -> None:
    assert SpanAttributes.GEN_AI_REQUEST_MODEL == "gen_ai.request.model"
    assert SpanAttributes.GEN_AI_RESPONSE_MODEL == "gen_ai.response.model"
    assert SpanAttributes.GEN_AI_USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"
    assert SpanAttributes.GEN_AI_USAGE_OUTPUT_TOKENS == "gen_ai.usage.output_tokens"
    assert SpanAttributes.GEN_AI_AGENT_NAME == "gen_ai.agent.name"


def test_datarobot_specific_attributes() -> None:
    assert SpanAttributes.DATAROBOT_TRACE_NAME == "datarobot.trace_name"
    assert SpanAttributes.DATAROBOT_SESSION_ID == "datarobot.session_id"
    assert SpanAttributes.DATAROBOT_USER_ID == "datarobot.user_id"
    assert SpanAttributes.DATAROBOT_TURN_ID == "datarobot.turn_id"


def test_all_attribute_values_are_strings() -> None:
    attrs = {
        k: v
        for k, v in vars(SpanAttributes).items()
        if not k.startswith("_")
    }
    assert attrs, "SpanAttributes should have at least one constant"
    for name, value in attrs.items():
        assert isinstance(value, str), f"{name} should be a string, got {type(value)}"

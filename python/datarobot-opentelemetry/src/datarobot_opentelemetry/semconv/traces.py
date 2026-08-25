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

from typing import Final


class SpanAttributes:
    """Constants for span attribute keys used in Gen AI telemetry."""

    # Attribute keys from open-telemetry specification:
    # https://opentelemetry.io/docs/reference/specification/trace/semantic_conventions/
    GEN_AI_PROVIDER_NAME: Final = "gen_ai.provider.name"
    GEN_AI_OPERATION_NAME: Final = "gen_ai.operation.name"
    GEN_AI_REQUEST_MODEL: Final = "gen_ai.request.model"
    GEN_AI_RESPONSE_MODEL: Final = "gen_ai.response.model"
    GEN_AI_INPUT_MESSAGES: Final = "gen_ai.input.messages"
    GEN_AI_OUTPUT_MESSAGES: Final = "gen_ai.output.messages"
    GEN_AI_SYSTEM_INSTRUCTIONS: Final = "gen_ai.system_instructions"
    GEN_AI_USAGE_INPUT_TOKENS: Final = "gen_ai.usage.input_tokens"
    GEN_AI_USAGE_OUTPUT_TOKENS: Final = "gen_ai.usage.output_tokens"
    GEN_AI_TOOL_NAME: Final = "gen_ai.tool.name"
    GEN_AI_AGENT_NAME: Final = "gen_ai.agent.name"
    ERROR_TYPE: Final = "error.type"
    SERVER_ADDRESS: Final = "server.address"
    SERVER_PORT: Final = "server.port"
    GEN_AI_CONVERSATION_ID: Final = "gen_ai.conversation.id"
    GEN_AI_OUTPUT_TYPE: Final = "gen_ai.output.type"
    GEN_AI_REQUEST_CHOICE_COUNT: Final = "gen_ai.request.choice.count"
    GEN_AI_REQUEST_SEED: Final = "gen_ai.request.seed"
    GEN_AI_REQUEST_FREQUENCY_PENALTY: Final = "gen_ai.request.frequency_penalty"
    GEN_AI_REQUEST_MAX_TOKENS: Final = "gen_ai.request.max_tokens"
    GEN_AI_REQUEST_PRESENCE_PENALTY: Final = "gen_ai.request.presence_penalty"
    GEN_AI_REQUEST_STOP_SEQUENCES: Final = "gen_ai.request.stop_sequences"
    GEN_AI_REQUEST_TEMPERATURE: Final = "gen_ai.request.temperature"
    GEN_AI_REQUEST_TOP_K: Final = "gen_ai.request.top_k"
    GEN_AI_REQUEST_TOP_P: Final = "gen_ai.request.top_p"
    GEN_AI_RESPONSE_FINISH_REASONS: Final = "gen_ai.response.finish_reasons"
    GEN_AI_RESPONSE_ID: Final = "gen_ai.response.id"
    GEN_AI_TOOL_DEFINITIONS: Final = "gen_ai.tool.definitions"
    GEN_AI_EMBEDDINGS_DIMENSION_COUNT: Final = "gen_ai.embeddings.dimension.count"
    GEN_AI_REQUEST_ENCODING_FORMATS: Final = "gen_ai.request.encoding_formats"
    GEN_AI_DATA_SOURCE_ID: Final = "gen_ai.data_source.id"
    GEN_AI_RETRIEVAL_DOCUMENTS: Final = "gen_ai.retrieval.documents"
    GEN_AI_RETRIEVAL_QUERY_TEXT: Final = "gen_ai.retrieval.query.text"
    GEN_AI_TOOL_CALL_ID: Final = "gen_ai.tool.call.id"
    GEN_AI_TOOL_DESCRIPTION: Final = "gen_ai.tool.description"
    GEN_AI_TOOL_TYPE: Final = "gen_ai.tool.type"
    GEN_AI_TOOL_CALL_ARGUMENTS: Final = "gen_ai.tool.call.arguments"
    GEN_AI_TOOL_CALL_RESULT: Final = "gen_ai.tool.call.result"
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS: Final = (
        "gen_ai.usage.cache_creation.input_tokens"
    )
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: Final = "gen_ai.usage.cache_read.input_tokens"

    # DataRobot specific attributes
    DATAROBOT_TRACE_NAME: Final = "datarobot.trace_name"
    DATAROBOT_USER_ID: Final = "datarobot.user_id"
    DATAROBOT_SESSION_ID: Final = "datarobot.session_id"
    DATAROBOT_TURN_ID: Final = "datarobot.turn_id"
    DATAROBOT_TAGS: Final = "datarobot.tags"
    DATAROBOT_INPUT_VALUE: Final = "datarobot.input.value"
    DATAROBOT_OUTPUT_VALUE: Final = "datarobot.output.value"
    DATAROBOT_ERROR_COUNT: Final = "datarobot.error_count"
    DATAROBOT_COMPLIANCE_LABELS: Final = "datarobot.compliance.labels"
    DATAROBOT_GUARDRAILS_TRIGGERED: Final = "datarobot.guardrails.triggered"
    DATAROBOT_GUARDRAILS_LABELS: Final = "datarobot.guardrails.labels"
    DATAROBOT_GUARDRAILS_ACTIONS: Final = "datarobot.guardrails.actions"
    DATAROBOT_MODERATION_COST: Final = "datarobot.moderation.cost"

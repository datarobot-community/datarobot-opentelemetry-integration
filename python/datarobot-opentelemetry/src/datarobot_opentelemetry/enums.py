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

from enum import Enum
from typing import Literal

FormatType = Literal["json", "text", "readable"]


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    # Python 3.11 changed Enum.__format__ for str-mixin enums to include the
    # class name (f"{LogLevel.INFO}" -> "LogLevel.INFO" instead of "INFO").
    # Pin both back to plain str behavior so interpolation is safe regardless
    # of Python version.
    __str__ = str.__str__
    __format__ = str.__format__  # type: ignore[assignment]


class EntityType(str, Enum):
    """Known DataRobot entity kinds observable via the OTel API.

    Not exhaustive by construction: callers may still pass any string, since
    the platform can introduce new entity kinds before this enum is updated.
    """

    EXPERIMENT_CONTAINER = "experiment_container"
    DEPLOYMENT = "deployment"
    CUSTOM_APPLICATION = "custom_application"
    WORKLOAD = "workload"

    # See LogLevel above: without this, f"{EntityType.CUSTOM_APPLICATION}"
    # renders as "EntityType.CUSTOM_APPLICATION" on Python 3.11+, corrupting
    # the X-DataRobot-Entity-Id header and service.name built from it.
    __str__ = str.__str__
    __format__ = str.__format__  # type: ignore[assignment]


class DataRobotSpanKind(str, Enum):
    """Known DataRobot span kinds observable via the OTel API."""

    EVALUATOR = "evaluator"

    __str__ = str.__str__
    __format__ = str.__format__  # type: ignore[assignment]
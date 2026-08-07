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


class EntityType(str, Enum):
    """Known DataRobot entity kinds observable via the OTel API.

    Not exhaustive by construction: callers may still pass any string, since
    the platform can introduce new entity kinds before this enum is updated.
    """

    EXPERIMENT_CONTAINER = "experiment_container"
    DEPLOYMENT = "deployment"
    CUSTOM_APPLICATION = "custom_application"
    WORKLOAD = "workload"

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


class DataRobotOtelHeaders:
    """Constants for HTTP header keys used in DataRobot OpenTelemetry integration."""

    ENTITY_ID: Final = "X-DataRobot-Entity-Id"
    API_KEY: Final = "X-DataRobot-Api-Key"

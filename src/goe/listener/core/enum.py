# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import enum


class CommandStatus(str, enum.Enum):
    """Enum for command status"""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    EXECUTING = "EXECUTING"

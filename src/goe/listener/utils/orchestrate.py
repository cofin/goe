# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Simple Orchestration utilities."""

from goe.listener import exceptions
from goe.orchestration.orchestration_lock import (
    OrchestrationLockTimeout,
    orchestration_lock_for_table,
)


def check_for_running_command(owner_table: str) -> bool:
    """Validate that no other process holds an orchestration lock on owner_table."""
    parts = owner_table.split(".", 1) if owner_table and "." in owner_table else ["", ""]
    owner_name, table_name = parts[0], parts[1]
    if owner_name and table_name:
        try:
            table_lock = orchestration_lock_for_table(owner_name, table_name)
            table_lock.acquire()
            table_lock.release()
        except OrchestrationLockTimeout as exc:
            raise exceptions.ApplicationError(
                status_code=500,
                message=f"Another job has locked the table {owner_name}.{table_name}.",
            ) from exc
        return False

    raise exceptions.ApplicationError(
        status_code=500,
        message="Could not determine owner and table from supplied input.",
    )

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Pure-value schema diffing and sqlglot-backed DDL synchronization."""

from goe.sync.differ import (
    SCHEMA_SYNC_LOCKED_MESSAGE_TEXT,
    ColumnAddition,
    NullabilityRelaxation,
    PartitionDrop,
    SchemaDiff,
    SchemaSyncService,
    SourceColumnSnapshot,
    TargetColumnSnapshot,
    TypeWidening,
    normalise_schema_sync_options,
    run_schema_sync,
)

__all__ = (
    "SCHEMA_SYNC_LOCKED_MESSAGE_TEXT",
    "ColumnAddition",
    "NullabilityRelaxation",
    "PartitionDrop",
    "SchemaDiff",
    "SchemaSyncService",
    "SourceColumnSnapshot",
    "TargetColumnSnapshot",
    "TypeWidening",
    "normalise_schema_sync_options",
    "run_schema_sync",
)

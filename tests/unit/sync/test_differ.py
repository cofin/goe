# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for SchemaSyncService and SchemaDiff."""

from goe.sync.differ import (
    SchemaSyncService,
    SourceColumnSnapshot,
    TargetColumnSnapshot,
)


def test_compute_diff_additions_widenings_nullability_and_partitions() -> None:
    """Verify compute_diff detects added columns, widened types, relaxed nullability, and dropped partitions."""
    service = SchemaSyncService(dialect="bigquery")
    source_cols = [
        SourceColumnSnapshot(name="ID", data_type="INT64", nullable=False, position=1),
        SourceColumnSnapshot(
            name="AMOUNT", data_type="NUMERIC(18, 2)", nullable=True, precision=18, scale=2, position=2
        ),
        SourceColumnSnapshot(name="STATUS", data_type="STRING", nullable=True, position=3),
        SourceColumnSnapshot(name="NEW_COL", data_type="STRING", nullable=True, position=4),
    ]
    target_cols = [
        TargetColumnSnapshot(name="ID", data_type="INT64", nullable=False, position=1),
        TargetColumnSnapshot(
            name="AMOUNT", data_type="NUMERIC(10, 2)", nullable=True, precision=10, scale=2, position=2
        ),
        TargetColumnSnapshot(name="STATUS", data_type="STRING", nullable=False, position=3),
    ]

    diff = service.compute_diff(
        schema_name="SH",
        table_name="SALES",
        target_schema="sh_bq",
        target_table="sales",
        source_columns=source_cols,
        target_columns=target_cols,
        source_partitions=["P2025"],
        target_partitions=["P2024", "P2025"],
        sync_dropped_partitions=True,
    )

    assert diff.has_changes is True
    assert len(diff.additions) == 1
    assert diff.additions[0].column_name == "NEW_COL"
    assert len(diff.widenings) == 1
    assert diff.widenings[0].column_name == "AMOUNT"
    assert len(diff.nullability_relaxations) == 1
    assert diff.nullability_relaxations[0].column_name == "STATUS"
    assert len(diff.partition_drops) == 1
    assert diff.partition_drops[0].partition_name == "P2024"

    executed: list[str] = []
    statements = service.apply_diff(diff, execute=True, ddl_executor=executed.append)
    assert len(statements) == 4
    assert executed == statements
    assert any("ADD COLUMN `NEW_COL` STRING" in s for s in statements)
    assert any("ALTER COLUMN `AMOUNT` SET DATA TYPE" in s for s in statements)
    assert any("ALTER COLUMN `STATUS` DROP NOT NULL" in s for s in statements)
    assert any("DROP PARTITION `P2024`" in s for s in statements)


def test_apply_diff_dry_run_does_not_invoke_executor() -> None:
    """Verify apply_diff with execute=False generates DDL without calling ddl_executor."""
    service = SchemaSyncService(dialect="snowflake")
    diff = service.compute_diff(
        schema_name="SH",
        table_name="SALES",
        target_schema="SH",
        target_table="SALES",
        source_columns=[SourceColumnSnapshot(name="C1", data_type="VARCHAR(100)", length=100)],
        target_columns=[],
    )
    executed: list[str] = []
    statements = service.apply_diff(diff, execute=False, ddl_executor=executed.append)
    assert len(statements) == 1
    assert executed == []

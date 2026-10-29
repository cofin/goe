# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the consolidated Oracle catalog snapshot service."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from goe.offload.oracle.catalog import (
    OracleCatalogService,
    OracleColumnMeta,
    OracleConstraintMeta,
    OracleIndexMeta,
    OraclePartitionMeta,
    OracleSessionContext,
    OracleStorageStats,
    OracleSubpartitionMeta,
    OracleTableSnapshot,
    decode_oracle_raw_stat,
    parse_high_value_literals,
    split_high_value_tokens,
)


class _FakeDriver:
    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def select(self, sql: str, params: dict[str, Any] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append((sql, params or {}))
        for key, rows in self.responses.items():
            if key in sql:
                return rows
        return []

    def select_one_or_none(
        self, sql: str, params: dict[str, Any] | None = None, **kwargs: Any
    ) -> dict[str, Any] | None:
        rows = self.select(sql, params)
        return rows[0] if rows else None


def test_split_and_parse_high_value_literals() -> None:
    raw = (
        "TO_DATE(' 2026-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN'), "
        "TIMESTAMP' 2026-01-01 12:30:00.123456000', "
        "'US,EAST', "
        "100, "
        "MAXVALUE, "
        "DEFAULT"
    )
    tokens = split_high_value_tokens(raw)
    assert len(tokens) == 6
    parsed = parse_high_value_literals(raw)
    assert parsed[0] == datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert parsed[1] == datetime.datetime(2026, 1, 1, 12, 30, 0, 123456)
    assert parsed[2] == "US,EAST"
    assert parsed[3] == Decimal("100")
    assert parsed[4] == "MAXVALUE"
    assert parsed[5] == "DEFAULT"


def test_decode_oracle_raw_stat_types() -> None:
    assert decode_oracle_raw_stat(b"HELLO", "VARCHAR2") == "HELLO"
    assert decode_oracle_raw_stat(bytes([120, 126, 1, 1, 1, 1, 1]), "DATE") == datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert decode_oracle_raw_stat(bytes([0x80]), "NUMBER") == Decimal(0)
    assert decode_oracle_raw_stat(bytes([0xC1, 0x02]), "NUMBER") == Decimal(1)


def test_fetch_session_context_single_rtt() -> None:
    driver = _FakeDriver(
        {
            "FROM v$instance": [
                {
                    "VERSION": "23.4.0.24.05",
                    "DB_UNIQUE_NAME": "FREE",
                    "CURRENT_SCN": 987654321,
                    "COMPATIBLE": "23.0.0",
                    "DB_BLOCK_SIZE": "8192",
                    "MAX_STRING_SIZE": "STANDARD",
                    "CELL_OFFLOAD_PROCESSING": "FALSE",
                    "CURRENT_USER": "GOE_ADM",
                }
            ]
        }
    )
    svc = OracleCatalogService()
    ctx = svc.fetch_session_context(driver)
    assert isinstance(ctx, OracleSessionContext)
    assert ctx.version == "23.4.0.24.05"
    assert ctx.current_scn == 987654321
    assert ctx.db_block_size == 8192
    assert len(driver.calls) == 1


def test_fetch_table_snapshot_hydrates_partitioned_table() -> None:
    driver = _FakeDriver(
        {
            "FROM all_tables": [
                {
                    "OWNER": "SH",
                    "TABLE_NAME": "SALES",
                    "IOT_TYPE": None,
                    "PARTITIONED": "YES",
                    "PARTITIONING_TYPE": "RANGE",
                    "SUBPARTITIONING_TYPE": "LIST",
                    "DEGREE": "DEFAULT",
                    "COMPRESSION": "ENABLED",
                    "COMPRESS_FOR": "QUERY HIGH",
                    "NUM_ROWS": 1000,
                    "BLOCKS": 50,
                    "AVG_ROW_LEN": 48,
                    "LAST_ANALYZED": datetime.datetime(2026, 1, 1),
                    "SIZE_BYTES": 409600,
                }
            ],
            "FROM all_tab_cols": [
                {
                    "COLUMN_ID": 1,
                    "COLUMN_NAME": "SALE_ID",
                    "DATA_TYPE": "NUMBER",
                    "DATA_TYPE_OWNER": None,
                    "DATA_TYPE_MOD": None,
                    "CHAR_USED": None,
                    "DATA_LENGTH": 22,
                    "CHAR_LENGTH": 0,
                    "DATA_PRECISION": 10,
                    "DATA_SCALE": 0,
                    "NULLABLE": "N",
                    "DATA_DEFAULT": None,
                    "HIDDEN_COLUMN": "NO",
                    "VIRTUAL_COLUMN": "NO",
                    "NUM_DISTINCT": 1000,
                    "NUM_NULLS": 0,
                    "AVG_COL_LEN": 5,
                    "LOW_VALUE": bytes([0xC1, 0x02]),
                    "HIGH_VALUE": bytes([0xC2, 0x0B]),
                    "PART_POS": None,
                    "SUBPART_POS": None,
                },
                {
                    "COLUMN_ID": 2,
                    "COLUMN_NAME": "TIME_ID",
                    "DATA_TYPE": "DATE",
                    "DATA_TYPE_OWNER": None,
                    "DATA_TYPE_MOD": None,
                    "CHAR_USED": None,
                    "DATA_LENGTH": 7,
                    "CHAR_LENGTH": 0,
                    "DATA_PRECISION": None,
                    "DATA_SCALE": None,
                    "NULLABLE": "N",
                    "DATA_DEFAULT": None,
                    "HIDDEN_COLUMN": "NO",
                    "VIRTUAL_COLUMN": "NO",
                    "NUM_DISTINCT": 10,
                    "NUM_NULLS": 0,
                    "AVG_COL_LEN": 7,
                    "LOW_VALUE": None,
                    "HIGH_VALUE": None,
                    "PART_POS": 1,
                    "SUBPART_POS": None,
                },
            ],
            "FROM all_constraints": [
                {
                    "CONSTRAINT_NAME": "SALES_PK",
                    "CONSTRAINT_TYPE": "P",
                    "STATUS": "ENABLED",
                    "VALIDATED": "VALIDATED",
                    "COLUMN_NAME": "SALE_ID",
                    "POSITION": 1,
                }
            ],
            "FROM all_indexes": [
                {
                    "INDEX_OWNER": "SH",
                    "INDEX_NAME": "SALES_PK",
                    "INDEX_TYPE": "NORMAL",
                    "UNIQUENESS": "UNIQUE",
                    "COLUMN_NAME": "SALE_ID",
                    "COLUMN_POSITION": 1,
                }
            ],
            "FROM all_tab_partitions": [
                {
                    "PARTITION_NAME": "P_2025",
                    "PARTITION_POSITION": 1,
                    "HIGH_VALUE": "TO_DATE(' 2026-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')",
                    "SUBPARTITION_COUNT": 1,
                    "NUM_ROWS": 1000,
                    "BLOCKS": 50,
                    "AVG_ROW_LEN": 48,
                    "SIZE_BYTES": 409600,
                }
            ],
            "FROM all_tab_subpartitions": [
                {
                    "PARTITION_NAME": "P_2025",
                    "PARTITION_POSITION": 1,
                    "SUBPARTITION_NAME": "P_2025_US",
                    "SUBPARTITION_POSITION": 1,
                    "HIGH_VALUE": "'US'",
                    "NUM_ROWS": 1000,
                    "BLOCKS": 50,
                    "AVG_ROW_LEN": 48,
                    "SIZE_BYTES": 409600,
                }
            ],
        }
    )

    svc = OracleCatalogService()
    snap = svc.fetch_table_snapshot(driver, "sh", "sales")
    assert isinstance(snap, OracleTableSnapshot)
    assert snap.owner == "SH"
    assert snap.table_name == "SALES"
    assert snap.partitioned is True
    assert snap.partitioning_type == "RANGE"
    assert snap.subpartitioning_type == "LIST"
    assert isinstance(snap.stats, OracleStorageStats)
    assert snap.stats.size_in_bytes == 409600
    assert len(snap.columns) == 2
    assert isinstance(snap.columns[0], OracleColumnMeta)
    assert snap.columns[0].low_value == Decimal(1)
    assert snap.columns[1].partition_position == 1
    assert isinstance(snap.constraints[0], OracleConstraintMeta)
    assert snap.constraints[0].column_names == ("SALE_ID",)
    assert isinstance(snap.indexes[0], OracleIndexMeta)
    assert snap.indexes[0].column_names == ("SALE_ID",)
    assert len(snap.partitions) == 1
    assert isinstance(snap.partitions[0], OraclePartitionMeta)
    assert snap.partitions[0].high_value_literals == (datetime.datetime(2026, 1, 1, 0, 0, 0),)
    assert len(snap.subpartitions) == 1
    assert isinstance(snap.subpartitions[0], OracleSubpartitionMeta)
    assert snap.subpartitions[0].high_value_literals == ("US",)

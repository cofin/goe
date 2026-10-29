# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for StatusReportService."""

from typing import Any

from goe.report.service import StatusReportService


def test_collect_report_concurrent_and_duckdb_rollup() -> None:
    """Verify source and target fetchers run and DuckDB ROLLUP aggregates metrics accurately."""

    def src_fetch(schema: str | None, table: str | None) -> list[dict[str, Any]]:
        return [
            {
                "schema_name": "SH",
                "table_name": "SALES",
                "target_schema": "sh",
                "target_table": "sales",
                "offload_type": "INCREMENTAL",
                "incremental_key": "TIME_ID",
                "incremental_high_value": "2025-01-01",
                "incremental_predicate_type": "RANGE",
                "partition_name": "P2024",
                "high_value": "2025-01-01",
                "offloaded": True,
                "source_rows": 1000,
                "source_bytes": 50000,
            },
            {
                "schema_name": "SH",
                "table_name": "SALES",
                "target_schema": "sh",
                "target_table": "sales",
                "offload_type": "INCREMENTAL",
                "incremental_key": "TIME_ID",
                "incremental_high_value": "2025-01-01",
                "incremental_predicate_type": "RANGE",
                "partition_name": "P2025",
                "high_value": "2026-01-01",
                "offloaded": False,
                "source_rows": 500,
                "source_bytes": 25000,
            },
        ]

    def tgt_fetch(schema: str | None, table: str | None) -> list[dict[str, Any]]:
        return [
            {
                "schema_name": "SH",
                "table_name": "SALES",
                "partition_name": "P2024",
                "target_rows": 1000,
                "target_bytes": 12000,
            }
        ]

    svc = StatusReportService(source_fetcher=src_fetch, target_fetcher=tgt_fetch)
    env = svc.collect_report(schema="SH", table="SALES", database_name="ORCL")

    assert env.total_tables == 1
    assert env.total_source_bytes == 75000
    assert env.total_offloaded_bytes == 12000
    assert env.total_reclaimable_bytes == 50000

    tbl = env.tables[0]
    assert tbl.source_rows == 1500
    assert tbl.offloaded_rows == 1000
    assert tbl.reclaimable_rows == 1000
    assert len(tbl.partitions) == 2

    as_dict = env.to_report_dict()
    assert as_dict["database_name"] == "ORCL"
    assert as_dict["total_tables"] == 1

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the custom Oracle dialect extensions and OracleSqlEngine."""

import ast
from pathlib import Path

import sqlglot
from sqlglot import exp

import goe.offload.oracle.oracle_offload_transport_rdbms_api as transport_rdbms_mod
from goe.offload.oracle.oracle_dialect import (
    OracleSqlEngine,
    get_oracle_dialect_engine,
    register_oracle_dialect_extensions,
)
from goe.offload.sql_engine import OracleExtractionQueryProtocol


def test_oracle_transport_rdbms_api_has_zero_sqlglot_imports() -> None:
    """Verify oracle_offload_transport_rdbms_api.py does not import sqlglot directly."""
    source = Path(transport_rdbms_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)
    assert not any("sqlglot" in name for name in imported_names)


def test_oracle_dialect_extensions_round_trip_partition_and_as_of_scn() -> None:
    """Verify PARTITION, SUBPARTITION, and AS OF SCN parse to exp.Partition/exp.Version and round-trip."""
    register_oracle_dialect_extensions()
    register_oracle_dialect_extensions()
    sql = 'SELECT /*+ FULL(s) */ a FROM "SH"."SALES" PARTITION ("P1") AS OF SCN 123456 s WHERE a > :b1'
    parsed = sqlglot.parse_one(sql, read="oracle")
    table_node = parsed.find(exp.Table)
    assert table_node is not None
    assert isinstance(table_node.args.get("partition"), exp.Partition)
    assert isinstance(table_node.args.get("version"), exp.Version)
    rendered = parsed.sql("oracle")
    assert rendered == 'SELECT /*+ FULL(s) */ a FROM "SH"."SALES" PARTITION("P1") AS OF SCN 123456 s WHERE a > :b1'

    subpart_sql = 'SELECT a FROM "SH"."SALES" SUBPARTITION ("SP1") AS OF SCN :scn_bind s'
    subpart_parsed = sqlglot.parse_one(subpart_sql, read="oracle")
    subpart_table = subpart_parsed.find(exp.Table)
    assert subpart_table is not None
    assert subpart_table.args["partition"].args.get("subpartition") is True
    assert subpart_parsed.sql("oracle") == 'SELECT a FROM "SH"."SALES" SUBPARTITION("SP1") AS OF SCN :scn_bind s'

    versions_sql = 'SELECT a FROM "SH"."SALES" VERSIONS BETWEEN SCN 100 AND 200 s'
    versions_parsed = sqlglot.parse_one(versions_sql, read="oracle")
    assert versions_parsed.sql("oracle") == 'SELECT a FROM "SH"."SALES" VERSIONS BETWEEN SCN 100 AND 200 s'


def test_oracle_dialect_engine_satisfies_protocol_and_builds_extraction_queries() -> None:
    """Verify OracleSqlEngine satisfies OracleExtractionQueryProtocol and builds extraction SQL."""
    engine = get_oracle_dialect_engine()
    assert isinstance(engine, OracleExtractionQueryProtocol)
    assert isinstance(engine, OracleSqlEngine)

    assert engine.snapshot_scn_clause(987654) == "AS OF SCN 987654"
    assert engine.snapshot_scn_clause(None) == ""
    assert engine.iot_partition_clause("P_2025") == 'PARTITION("P_2025")'
    assert engine.iot_partition_clause(None) == ""

    from_clause = engine.table_from_clause(
        owner="SH",
        table_name="SALES",
        alias="g",
        partition_names=["P_2025"],
        is_subpartition=False,
        transport_scn=987654,
    )
    assert from_clause == '"SH"."SALES" PARTITION("P_2025") AS OF SCN 987654 g'

    part_branch = engine.partition_split_branch_query(
        owner="SH",
        table_name="SALES",
        partition_name="P_2025",
        is_subpartition=True,
        transport_scn=987654,
        batch=1,
        batch_col="goe_batch",
    )
    assert part_branch == 'SELECT g.*, 1 AS goe_batch FROM "SH"."SALES" SUBPARTITION("P_2025") AS OF SCN 987654 g'

    id_range_sql = engine.id_range_query(
        owner="SH",
        table_name="SALES",
        id_col_name="PROD_ID",
        iot_partition_name="P_2025",
        where_clause="\"TIME_ID\" >= TIMESTAMP '2020-01-01 00:00:00.123456789'",
    )
    assert 'SELECT MIN(PROD_ID) AS val FROM "SH"."SALES" PARTITION("P_2025")' in id_range_sql
    assert 'SELECT MAX(PROD_ID) AS val FROM "SH"."SALES" PARTITION("P_2025")' in id_range_sql
    assert "TIMESTAMP '2020-01-01 00:00:00.123456789'" in id_range_sql

    extent_branch = engine.extent_split_branch_query(
        owner="SH",
        table_name="SALES",
        transport_scn=987654,
        partition_param="offload_vc2_ntt('P1')",
        subpartition_param="NULL",
        degree=4,
        batch=0,
        batch_col="goe_batch",
        where_clause='"PROD_ID" = 10',
    )
    assert "/*+ NO_INDEX(g) USE_NL(g) LEADING(r) */" in extent_branch
    assert 'FROM "SH"."SALES" AS OF SCN 987654 g' in extent_branch
    assert "TABLE(offload.offload_rowid_ranges('SH', 'SALES', offload_vc2_ntt('P1'), NULL, 4, 0)) r" in extent_branch
    assert 'AND ("PROD_ID" = 10)' in extent_branch

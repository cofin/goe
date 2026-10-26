# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for DuckDBSessionConfig and DuckDBEngine over SQLSpec DuckDBConfig."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from goe.offload.staging.parquet.parquet_column import (
    PARQUET_TYPE_BINARY,
    PARQUET_TYPE_BOOLEAN,
    PARQUET_TYPE_DOUBLE,
    PARQUET_TYPE_INT32,
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
    StagingParquetColumn,
)
from goe.offload.transport.duckdb import (
    CloudStorageSecretSpec,
    DuckDBEngine,
    DuckDBSessionConfig,
    OracleEzConnect,
    attach_oracle,
    build_cast_projection,
    load_oracle_extension,
    parse_ezconnect_dsn,
    verify_batch_scn_invariant,
    verify_duckdb_version,
)


def test_duckdb_session_config_clamps_memory_and_threads_to_cgroup_quota() -> None:
    """DuckDBSessionConfig clamps memory_limit to 75% of CgroupQuota memory and threads to effective CPUs."""
    fake_quota = SimpleNamespace(
        available_memory_bytes=4 * 1024 * 1024 * 1024,
        effective_memory_bytes=4 * 1024 * 1024 * 1024,
        effective_cpus=lambda: 3,
    )
    cfg = DuckDBSessionConfig(
        execution_key="exec01",
        parallelism=4,
        configured_memory_bytes=8 * 1024 * 1024 * 1024,
    )
    with patch("goe.offload.transport.duckdb.engine.CgroupQuota.detect", return_value=fake_quota):
        assert cfg.effective_memory_limit() == "3072MiB"
        assert cfg.effective_threads() == 3
    assert cfg.allow_unsigned_extensions is False


def test_duckdb_engine_initializes_sqlspec_config_and_session_pragmas(tmp_path: Path) -> None:
    """DuckDBEngine.open builds DuckDBConfig, loads parquet/httpfs before metadata cache, and yields cursors."""
    cfg = DuckDBSessionConfig(
        execution_key="exec02",
        parallelism=2,
        memory_limit_override="512MiB",
        threads_override=2,
        temp_directory=str(tmp_path),
    )
    engine = DuckDBEngine(cfg)
    conn = engine.open()
    try:
        assert engine.sqlspec_config is not None
        conn_cfg = engine.sqlspec_config.connection_config
        assert conn_cfg["database"] == ":memory:goe_exec02"
        assert "allow_unsigned_extensions" not in conn_cfg

        row_cache = conn.execute("SELECT current_setting('parquet_metadata_cache')").fetchone()
        row_order = conn.execute("SELECT current_setting('preserve_insertion_order')").fetchone()
        assert row_cache is not None and row_cache[0] is True
        assert row_order is not None and row_order[0] is False

        with engine.cursor() as cur1, engine.cursor() as cur2:
            assert cur1 is not cur2
            assert cur1.execute("SELECT 42").fetchone() == (42,)
            assert cur2.execute("SELECT 99").fetchone() == (99,)
    finally:
        engine.close()


def test_duckdb_engine_loads_preseeded_oracle_extension_before_community_install() -> None:
    """Air-gapped extension_directory executes LOAD oracle first and only installs from community on error."""
    cfg = DuckDBSessionConfig(
        execution_key="exec03",
        extension_directory="/opt/goe/duckdb_extensions",
        extension_repository="community",
    )
    preseeded_conn = MagicMock()
    load_oracle_extension(preseeded_conn, cfg)
    preseeded_conn.execute.assert_called_once_with("LOAD oracle;")

    fallback_conn = MagicMock()
    fallback_conn.execute.side_effect = [duckdb.IOException("not pre-seeded"), None, None]
    load_oracle_extension(fallback_conn, cfg)
    assert [c.args[0] for c in fallback_conn.execute.call_args_list] == [
        "LOAD oracle;",
        "INSTALL oracle FROM community;",
        "LOAD oracle;",
    ]

    local_cfg = DuckDBSessionConfig(
        execution_key="exec04",
        extension_path="/opt/goe/oracle.duckdb_extension",
    )
    assert local_cfg.allow_unsigned_extensions is True
    local_conn = MagicMock()
    load_oracle_extension(local_conn, local_cfg)
    local_conn.execute.assert_called_once_with("LOAD '/opt/goe/oracle.duckdb_extension';")


def test_duckdb_engine_creates_and_rotates_gcs_s3_and_azure_temporary_secrets(tmp_path: Path) -> None:
    """configure_cloud_secret executes CREATE OR REPLACE TEMPORARY SECRET for GCS, S3, and Azure."""
    cfg = DuckDBSessionConfig(execution_key="exec05", temp_directory=str(tmp_path))
    engine = DuckDBEngine(cfg)
    mock_conn = MagicMock()

    engine.configure_cloud_secret(
        CloudStorageSecretSpec(scheme="gs", bearer_token="tok'1"),
        conn=mock_conn,
    )
    engine.configure_cloud_secret(
        CloudStorageSecretSpec(scheme="gs", bearer_token="tok2"),
        conn=mock_conn,
    )
    engine.configure_cloud_secret(
        CloudStorageSecretSpec(
            scheme="s3",
            key_id="AKIA123",
            secret="sec'ret",
            session_token="sess123",
            region="us-east-1",
        ),
        conn=mock_conn,
    )
    engine.configure_cloud_secret(
        CloudStorageSecretSpec(
            scheme="az",
            connection_string="DefaultEndpointsProtocol=https;AccountName=acct;",
            account_name="acct",
        ),
        conn=mock_conn,
    )

    statements = [c.args[0] for c in mock_conn.execute.call_args_list]
    assert statements == [
        "CREATE OR REPLACE TEMPORARY SECRET goe_gcs (TYPE gcs, BEARER_TOKEN 'tok''1');",
        "CREATE OR REPLACE TEMPORARY SECRET goe_gcs (TYPE gcs, BEARER_TOKEN 'tok2');",
        (
            "CREATE OR REPLACE TEMPORARY SECRET goe_s3 "
            "(TYPE s3, KEY_ID 'AKIA123', SECRET 'sec''ret', SESSION_TOKEN 'sess123', REGION 'us-east-1');"
        ),
        (
            "CREATE OR REPLACE TEMPORARY SECRET goe_azure "
            "(TYPE azure, CONNECTION_STRING 'DefaultEndpointsProtocol=https;AccountName=acct;', ACCOUNT_NAME 'acct');"
        ),
    ]


def test_parse_ezconnect_and_attach_oracle_supports_wallet_and_tns() -> None:
    """attach_oracle supports EZConnect, TNS aliases, and Oracle Wallet paths."""
    assert parse_ezconnect_dsn("db.example.com:1522/FREEPDB1") == OracleEzConnect(
        host="db.example.com", port=1522, service="FREEPDB1"
    )
    assert parse_ezconnect_dsn("PRODDB_TNS") is None

    conn = MagicMock()
    attach_oracle(
        conn,
        user="goe_app",
        password="pa'ss",
        dsn="db.example.com:1521/FREEPDB1",
    )
    attach_oracle(
        conn,
        user=None,
        password=None,
        dsn="PRODDB_TNS",
        wallet_path="/opt/oracle/wallet",
    )
    statements = [c.args[0] for c in conn.execute.call_args_list]
    assert statements[0] == (
        "CREATE OR REPLACE TEMPORARY SECRET goe_ora_secret "
        "(TYPE oracle, HOST 'db.example.com', PORT 1521, SERVICE 'FREEPDB1', USER 'goe_app', PASSWORD 'pa''ss');"
    )
    assert statements[1] == "ATTACH IF NOT EXISTS '' AS goe_ora (TYPE oracle, SECRET goe_ora_secret);"
    assert statements[2] == (
        "CREATE OR REPLACE TEMPORARY SECRET goe_ora_secret "
        "(TYPE oracle, SERVICE 'PRODDB_TNS', WALLET_PATH '/opt/oracle/wallet');"
    )


def test_cast_projection_and_scn_invariant(tmp_path: Path) -> None:
    """build_cast_projection supports BINARY/BLOB and verify_batch_scn_invariant enforces AS OF SCN."""
    columns = [
        _column("ID", PARQUET_TYPE_INT64, 0),
        _column("QTY", PARQUET_TYPE_INT32, 1),
        _column("AMOUNT", PARQUET_TYPE_STRING, 2),
        _column("RATIO", PARQUET_TYPE_DOUBLE, 3),
        _column("FLAG", PARQUET_TYPE_BOOLEAN, 4),
        _column("RAW_COL", PARQUET_TYPE_BINARY, 5),
    ]
    projection = build_cast_projection(columns)
    assert 'CAST("RAW_COL" AS BLOB) AS "RAW_COL"' in projection
    target = tmp_path / "part-00000.parquet"
    conn = duckdb.connect()
    source = (
        'SELECT 1 AS "ID", 2 AS "QTY", \'12.50\' AS "AMOUNT", '
        '0.5 AS "RATIO", \'true\' AS "FLAG", \'\\xDEADBEEF\'::BLOB AS "RAW_COL"'
    )
    conn.execute(f"COPY (SELECT {projection} FROM ({source})) TO '{target}' (FORMAT PARQUET)")
    types = dict(conn.execute(f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM '{target}')").fetchall())
    assert types == {
        "ID": "BIGINT",
        "QTY": "INTEGER",
        "AMOUNT": "VARCHAR",
        "RATIO": "DOUBLE",
        "FLAG": "BOOLEAN",
        "RAW_COL": "BLOB",
    }

    verify_batch_scn_invariant('SELECT 1 FROM "SH"."SALES" AS OF SCN 42', True, 42)
    with pytest.raises(ValueError, match="AS OF SCN 42"):
        verify_batch_scn_invariant('SELECT 1 FROM "SH"."SALES"', True, 42)
    verify_duckdb_version("2.0.0")


def _column(name: str, data_type: str, position: int) -> StagingParquetColumn:
    """Return a staging column with its staging file name assigned."""
    column = StagingParquetColumn(name, data_type)
    column.set_simplified_staging_column_name(position)
    return column

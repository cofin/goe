# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""DuckDB engine helper behavior."""

from pathlib import Path
from unittest.mock import MagicMock

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
from goe.offload.transport.duckdb_engine import (
    DuckDBTransportSettings,
    OracleEzConnect,
    attach_oracle,
    build_batch_copy_sql,
    build_cast_projection,
    create_gcs_token_secret,
    load_gcs_extension,
    load_oracle_extension,
    open_batch_connection,
    parse_ezconnect_dsn,
    to_duckdb_gcs_uri,
    verify_batch_scn_invariant,
)

SETTINGS = DuckDBTransportSettings(
    threads=2,
    memory_limit="1GB",
    extension_repository="https://cofin.github.io/duckdb-oracle",
)


def test_parse_ezconnect_dsn() -> None:
    """EZConnect DSNs parse with a default port; TNS aliases and descriptors do not."""
    assert parse_ezconnect_dsn("db.example.com:1522/FREEPDB1") == OracleEzConnect(
        host="db.example.com", port=1522, service="FREEPDB1"
    )
    parsed = parse_ezconnect_dsn("hostname/service")
    assert parsed is not None
    assert parsed.port == 1521
    assert parse_ezconnect_dsn("PRODDB") is None
    assert parse_ezconnect_dsn("(DESCRIPTION=(ADDRESS=(HOST=h)(PORT=1521)))") is None


def test_to_duckdb_gcs_uri() -> None:
    """gs:// and gcs:// are rewritten to gcss://; other URIs are unchanged."""
    assert to_duckdb_gcs_uri("gs://b/p/part-00000.parquet") == "gcss://b/p/part-00000.parquet"
    assert to_duckdb_gcs_uri("gcs://b/p") == "gcss://b/p"
    assert to_duckdb_gcs_uri("gcss://b/p") == "gcss://b/p"


def test_cast_projection_produces_staging_parquet_types(tmp_path: Path) -> None:
    """The cast projection writes exactly the Parquet staging types GOE's BigQuery load expects."""
    columns = [
        _column("ID", PARQUET_TYPE_INT64, 0),
        _column("QTY", PARQUET_TYPE_INT32, 1),
        _column("AMOUNT", PARQUET_TYPE_STRING, 2),
        _column("RATIO", PARQUET_TYPE_DOUBLE, 3),
        _column("FLAG", PARQUET_TYPE_BOOLEAN, 4),
    ]
    projection = build_cast_projection(columns)
    target = tmp_path / "part-00000.parquet"
    conn = duckdb.connect()
    source = 'SELECT 1 AS "ID", 2 AS "QTY", \'12.50\' AS "AMOUNT", 0.5 AS "RATIO", \'true\' AS "FLAG"'
    conn.execute(f"COPY (SELECT {projection} FROM ({source})) TO '{target}' (FORMAT PARQUET)")
    types = dict(conn.execute(f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM '{target}')").fetchall())
    assert types == {"ID": "BIGINT", "QTY": "INTEGER", "AMOUNT": "VARCHAR", "RATIO": "DOUBLE", "FLAG": "BOOLEAN"}


def test_cast_projection_rejects_binary() -> None:
    """Binary staging columns are not supported by the DuckDB transport."""
    with pytest.raises(ValueError, match="BINARY"):
        build_cast_projection([_column("RAW_COL", PARQUET_TYPE_BINARY, 0)])


def test_scn_invariant() -> None:
    """Batch SQL must carry AS OF SCN when consistent read is enabled."""
    verify_batch_scn_invariant('SELECT 1 FROM "SH"."SALES" AS OF SCN 42', True, 42)
    verify_batch_scn_invariant('SELECT 1 FROM "SH"."SALES"', False, 42)
    with pytest.raises(ValueError, match="AS OF SCN 42"):
        verify_batch_scn_invariant('SELECT 1 FROM "SH"."SALES"', True, 42)


def test_copy_sql_escapes_oracle_text() -> None:
    """COPY SQL quotes the Oracle statement and targets the gcss URI."""
    sql = build_batch_copy_sql(
        'CAST("A" AS VARCHAR) AS "A"', "SELECT 'x' AS a FROM dual", "gcss://b/p/part-00000.parquet", "SNAPPY"
    )
    assert "oracle_query('goe_ora', 'SELECT ''x'' AS a FROM dual')" in sql
    assert sql.endswith("TO 'gcss://b/p/part-00000.parquet' (FORMAT PARQUET, COMPRESSION SNAPPY)")


def test_open_batch_connection_bounds_resources(tmp_path: Path) -> None:
    """Batch connections use the configured thread count and spill directory."""
    conn = open_batch_connection(SETTINGS, str(tmp_path))
    row_threads = conn.execute("SELECT current_setting('threads')").fetchone()
    row_temp = conn.execute("SELECT current_setting('temp_directory')").fetchone()
    assert row_threads is not None and row_threads[0] == 2
    assert row_temp is not None and row_temp[0] == str(tmp_path)
    conn.close()


def test_extensions_load_first_then_install_once() -> None:
    """LOAD is attempted first; INSTALL runs only after a failed LOAD."""
    conn = MagicMock()
    conn.execute.side_effect = [duckdb.IOException("missing"), None, None, duckdb.IOException("missing"), None, None]
    load_oracle_extension(conn, SETTINGS)
    load_gcs_extension(conn)
    assert [c.args[0] for c in conn.execute.call_args_list] == [
        "LOAD oracle",
        "INSTALL oracle FROM 'https://cofin.github.io/duckdb-oracle'",
        "LOAD oracle",
        "LOAD gcs",
        "INSTALL gcs FROM community",
        "LOAD gcs",
    ]


def test_extension_path_is_loaded_directly() -> None:
    """EXTENSION_PATH loads the local file without contacting a repository."""
    conn = MagicMock()
    settings = DuckDBTransportSettings(
        threads=2, memory_limit="1GB", extension_repository="r", extension_path="/opt/goe/oracle.duckdb_extension"
    )
    load_oracle_extension(conn, settings)
    conn.execute.assert_called_once_with("LOAD '/opt/goe/oracle.duckdb_extension'")


def test_secrets_are_temporary_and_escaped() -> None:
    """Oracle and GCS secrets are TEMPORARY and quote-escape secret values."""
    conn = MagicMock()
    attach_oracle(conn, "goe_app", "pa'ss", OracleEzConnect(host="h", port=1521, service="S"))
    create_gcs_token_secret(conn, "tok'en", "my-project")
    statements = [c.args[0] for c in conn.execute.call_args_list]
    assert statements[0].startswith("CREATE TEMPORARY SECRET goe_ora_secret (TYPE oracle, HOST 'h', PORT 1521")
    assert "PASSWORD 'pa''ss'" in statements[0]
    assert statements[1] == "ATTACH '' AS goe_ora (TYPE oracle, SECRET goe_ora_secret)"
    assert statements[2] == (
        "CREATE TEMPORARY SECRET goe_gcs (TYPE gcp, PROVIDER access_token, ACCESS_TOKEN 'tok''en', PROJECT_ID 'my-project')"
    )


def _column(name: str, data_type: str, position: int) -> StagingParquetColumn:
    """Return a staging column with its staging file name assigned."""
    column = StagingParquetColumn(name, data_type)
    column.set_simplified_staging_column_name(position)
    return column

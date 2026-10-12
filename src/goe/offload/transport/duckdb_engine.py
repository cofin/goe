# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""DuckDB connection, extension, secret and SQL helpers for the DuckDB offload transport.

SQL that embeds credentials is built only in this module and must never be logged; callers log redacted text.
"""

import re
import threading
from collections.abc import Sequence

import duckdb
import msgspec

from goe.offload.column_metadata import ColumnMetadataInterface
from goe.offload.staging.parquet.parquet_column import (
    PARQUET_TYPE_BOOLEAN,
    PARQUET_TYPE_DOUBLE,
    PARQUET_TYPE_FLOAT,
    PARQUET_TYPE_INT32,
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
)
from goe.offload.transport.duckdb_constants import (
    DUCKDB_GCS_SECRET_NAME,
    DUCKDB_ORACLE_ATTACH_ALIAS,
    DUCKDB_ORACLE_SECRET_NAME,
)

DEFAULT_ORACLE_PORT = 1521
EZCONNECT_DSN_RE = re.compile(r"^(?://)?(?P<host>[A-Za-z0-9_.\-]+)(?::(?P<port>\d+))?/(?P<service>[A-Za-z0-9_.$#\-]+)$")
DUCKDB_PARQUET_CAST_TYPES = {
    PARQUET_TYPE_STRING: "VARCHAR",
    PARQUET_TYPE_INT32: "INTEGER",
    PARQUET_TYPE_INT64: "BIGINT",
    PARQUET_TYPE_FLOAT: "FLOAT",
    PARQUET_TYPE_DOUBLE: "DOUBLE",
    PARQUET_TYPE_BOOLEAN: "BOOLEAN",
}
_EXTENSION_INSTALL_LOCK = threading.Lock()


class DuckDBTransportSettings(msgspec.Struct, frozen=True, kw_only=True):
    """Resource and extension settings applied to every DuckDB batch connection."""

    threads: int
    memory_limit: str
    extension_repository: str
    extension_dir: str | None = None
    extension_path: str | None = None


class OracleEzConnect(msgspec.Struct, frozen=True, kw_only=True):
    """Host, port and service parsed from an EZConnect DSN."""

    host: str
    port: int
    service: str


def parse_ezconnect_dsn(dsn: str | None) -> OracleEzConnect | None:
    """Return the parts of an EZConnect host[:port]/service DSN, or None for TNS aliases and descriptors."""
    match = EZCONNECT_DSN_RE.match((dsn or "").strip())
    if not match:
        return None
    return OracleEzConnect(host=match["host"], port=int(match["port"] or DEFAULT_ORACLE_PORT), service=match["service"])


def sql_string_literal(value: str) -> str:
    """Return value as a single-quoted SQL string literal with embedded quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


def to_duckdb_gcs_uri(uri: str) -> str:
    """Rewrite gs:// and gcs:// URIs to gcss:// so only the community gcs extension (not httpfs) handles them."""
    for scheme in ("gs://", "gcs://"):
        if uri.startswith(scheme):
            return "gcss://" + uri[len(scheme) :]
    return uri


def open_batch_connection(settings: DuckDBTransportSettings, temp_directory: str) -> duckdb.DuckDBPyConnection:
    """Open an in-memory connection bounded by threads, memory_limit and a private spill directory.

    allow_unsigned_extensions is required because duckdb-oracle is distributed unsigned.
    """
    config: dict[str, str | bool | int | float | list[str]] = {
        "allow_unsigned_extensions": "true",
        "threads": str(settings.threads),
        "memory_limit": settings.memory_limit,
        "temp_directory": temp_directory,
    }
    if settings.extension_dir:
        config["extension_directory"] = settings.extension_dir
    return duckdb.connect(":memory:", config=config)


def load_oracle_extension(conn: duckdb.DuckDBPyConnection, settings: DuckDBTransportSettings) -> None:
    """Load duckdb-oracle from extension_path, or LOAD it and install from the custom repository on first use."""
    if settings.extension_path:
        conn.execute(f"LOAD {sql_string_literal(settings.extension_path)}")
        return
    try:
        conn.execute("LOAD oracle")
    except duckdb.Error:
        with _EXTENSION_INSTALL_LOCK:
            conn.execute(f"INSTALL oracle FROM {sql_string_literal(settings.extension_repository)}")
            conn.execute("LOAD oracle")


def load_gcs_extension(conn: duckdb.DuckDBPyConnection) -> None:
    """LOAD the community gcs extension, installing it from the community repository on first use."""
    try:
        conn.execute("LOAD gcs")
    except duckdb.Error:
        with _EXTENSION_INSTALL_LOCK:
            conn.execute("INSTALL gcs FROM community")
            conn.execute("LOAD gcs")


def attach_oracle(conn: duckdb.DuckDBPyConnection, user: str, password: str, ezconnect: OracleEzConnect) -> None:
    """Create a temporary oracle secret and attach it (read-only) under DUCKDB_ORACLE_ATTACH_ALIAS."""
    conn.execute(
        f"CREATE TEMPORARY SECRET {DUCKDB_ORACLE_SECRET_NAME} (TYPE oracle, "
        f"HOST {sql_string_literal(ezconnect.host)}, PORT {int(ezconnect.port)}, "
        f"SERVICE {sql_string_literal(ezconnect.service)}, USER {sql_string_literal(user)}, "
        f"PASSWORD {sql_string_literal(password)})"
    )
    conn.execute(f"ATTACH '' AS {DUCKDB_ORACLE_ATTACH_ALIAS} (TYPE oracle, SECRET {DUCKDB_ORACLE_SECRET_NAME})")


def create_gcs_token_secret(conn: duckdb.DuckDBPyConnection, access_token: str, project_id: str | None) -> None:
    """Create a temporary gcp access_token secret used by the community gcs extension."""
    project_clause = f", PROJECT_ID {sql_string_literal(project_id)}" if project_id else ""
    conn.execute(
        f"CREATE TEMPORARY SECRET {DUCKDB_GCS_SECRET_NAME} (TYPE gcp, PROVIDER access_token, "
        f"ACCESS_TOKEN {sql_string_literal(access_token)}{project_clause})"
    )


def build_cast_projection(staging_columns: Sequence[ColumnMetadataInterface]) -> str:
    """Cast each Oracle result column (aliased with its staging file name) to its exact Parquet staging type."""
    expressions = []
    for column in staging_columns:
        duckdb_type = DUCKDB_PARQUET_CAST_TYPES.get(column.data_type)
        if duckdb_type is None:
            raise ValueError(f"Unsupported Parquet staging type for DuckDB transport: {column.data_type}")
        name = (column.staging_file_column_name or column.name).replace('"', '""')
        expressions.append(f'CAST("{name}" AS {duckdb_type}) AS "{name}"')
    return ", ".join(expressions)


def verify_batch_scn_invariant(batch_sql: str, consistent_read: bool, snapshot_scn: int | None) -> None:
    """Raise ValueError when consistent read is enabled but the batch SQL is not pinned to the transport SCN."""
    expected = f"AS OF SCN {snapshot_scn}"
    if consistent_read and snapshot_scn is not None and expected not in batch_sql.upper():
        raise ValueError(f"DuckDB transport SCN invariant violated: expected '{expected}' in batch SQL")


def build_batch_copy_sql(cast_projection: str, oracle_sql: str, target_uri: str, compression: str) -> str:
    """Return the COPY statement streaming one oracle_query result to a Parquet object."""
    return (
        f"COPY (SELECT {cast_projection} FROM oracle_query("
        f"{sql_string_literal(DUCKDB_ORACLE_ATTACH_ALIAS)}, {sql_string_literal(oracle_sql)})) "
        f"TO {sql_string_literal(target_uri)} (FORMAT PARQUET, COMPRESSION {compression})"
    )

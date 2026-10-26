# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""DuckDB 2.0 session engine over SQLSpec DuckDBConfig with core httpfs secrets and community oracle extension."""

import re
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Literal

import duckdb
from packaging.version import Version
from sqlspec.adapters.duckdb import DuckDBConfig

from goe.offload.column_metadata import ColumnMetadataInterface
from goe.offload.staging.parquet.parquet_column import (
    PARQUET_TYPE_BINARY,
    PARQUET_TYPE_BOOLEAN,
    PARQUET_TYPE_DOUBLE,
    PARQUET_TYPE_FLOAT,
    PARQUET_TYPE_INT32,
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
)
from goe.offload.transport.duckdb_constants import (
    DUCKDB_AZURE_SECRET_NAME,
    DUCKDB_GCS_SECRET_NAME,
    DUCKDB_ORACLE_ATTACH_ALIAS,
    DUCKDB_ORACLE_SECRET_NAME,
    DUCKDB_S3_SECRET_NAME,
    MIN_SUPPORTED_DUCKDB_VERSION,
)
from goe.platform import CgroupQuota
from goe.typing import FrozenBaseStruct

__all__ = [
    "DEFAULT_ORACLE_PORT",
    "DUCKDB_PARQUET_CAST_TYPES",
    "EZCONNECT_DSN_RE",
    "CloudStorageSecretSpec",
    "DuckDBEngine",
    "DuckDBSessionConfig",
    "OracleEzConnect",
    "attach_oracle",
    "build_cast_projection",
    "load_oracle_extension",
    "parse_ezconnect_dsn",
    "sql_string_literal",
    "verify_batch_scn_invariant",
    "verify_duckdb_version",
]

DEFAULT_ORACLE_PORT = 1521
EZCONNECT_DSN_RE = re.compile(
    r"^(?://)?(?P<host>[A-Za-z0-9_.\-]+)(?::(?P<port>\d+))?/(?P<service>[A-Za-z0-9_.$\x23\-]+)$"
)
DUCKDB_PARQUET_CAST_TYPES: dict[str, str] = {
    PARQUET_TYPE_STRING: "VARCHAR",
    PARQUET_TYPE_BINARY: "BLOB",
    PARQUET_TYPE_INT32: "INTEGER",
    PARQUET_TYPE_INT64: "BIGINT",
    PARQUET_TYPE_FLOAT: "FLOAT",
    PARQUET_TYPE_DOUBLE: "DOUBLE",
    PARQUET_TYPE_BOOLEAN: "BOOLEAN",
}
_EXTENSION_INSTALL_LOCK = threading.Lock()


class OracleEzConnect(FrozenBaseStruct, frozen=True, kw_only=True):
    """Host, port, and service parsed from an Oracle EZConnect DSN."""

    host: str
    port: int = DEFAULT_ORACLE_PORT
    service: str


class CloudStorageSecretSpec(FrozenBaseStruct, frozen=True, kw_only=True):
    """Cloud object store credential specification for DuckDB core httpfs secrets."""

    scheme: Literal["gs", "s3", "s3a", "az", "abfs", "abfss", "wasb", "wasbs"]
    bearer_token: str | None = None
    key_id: str | None = None
    secret: str | None = None
    session_token: str | None = None
    region: str | None = None
    connection_string: str | None = None
    account_name: str | None = None


class DuckDBSessionConfig(FrozenBaseStruct, frozen=True, kw_only=True):
    """Immutable resource, spill, and extension settings for a shared DuckDB 2.0 offload session."""

    execution_key: str
    parallelism: int = 1
    configured_memory_bytes: int | None = None
    memory_limit_override: str | None = None
    threads_override: int | None = None
    temp_directory: str = "/tmp/goe_duckdb"
    max_temp_directory_size: str = "90%"
    extension_repository: str = "community"
    extension_directory: str | None = None
    extension_path: str | None = None
    oracle_array_size: int = 10_000
    oracle_call_timeout_ms: int = 0

    @property
    def allow_unsigned_extensions(self) -> bool:
        """Allow unsigned extensions only when an explicit local extension file path is configured."""
        return bool(self.extension_path)

    def effective_memory_limit(self) -> str:
        """Return the DuckDB memory_limit clamped to 75% of container cgroup memory headroom."""
        if self.memory_limit_override and self.configured_memory_bytes is None:
            return self.memory_limit_override
        quota = CgroupQuota.detect()
        avail_mem = getattr(quota, "available_memory_bytes", None)
        if avail_mem is None:
            avail_mem = getattr(quota, "effective_memory_bytes", None)
        cgroup_cap = int(avail_mem * 0.75) if avail_mem else None
        candidates = [v for v in (self.configured_memory_bytes, cgroup_cap) if v is not None and v > 0]
        limit_mib = max(256, min(candidates) // (1024 * 1024)) if candidates else 2048
        return f"{limit_mib}MiB"

    def effective_threads(self) -> int:
        """Return DuckDB worker thread count clamped to container CPU quota."""
        quota = CgroupQuota.detect()
        raw_cpus = getattr(quota, "effective_cpus", 1)
        cpu_val = raw_cpus() if callable(raw_cpus) else raw_cpus
        cpu_cap = max(1, int(cpu_val))
        requested = (
            self.threads_override if self.threads_override and self.threads_override > 0 else self.parallelism * 2
        )
        return max(1, min(requested, cpu_cap))


class DuckDBEngine:
    """Shared execution-scoped DuckDB 2.0 engine backed by SQLSpec DuckDBConfig."""

    def __init__(self, session_config: DuckDBSessionConfig) -> None:
        self._config = session_config
        self._sqlspec_config: DuckDBConfig | None = None
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def session_config(self) -> DuckDBSessionConfig:
        """Return the immutable session configuration."""
        return self._config

    @property
    def sqlspec_config(self) -> DuckDBConfig | None:
        """Return the underlying SQLSpec DuckDBConfig when the session is open."""
        return self._sqlspec_config

    def open(
        self,
        *,
        load_oracle: bool = False,
        cloud_secret: CloudStorageSecretSpec | None = None,
    ) -> duckdb.DuckDBPyConnection:
        """Open the shared DuckDB 2.0 connection, configure pragmas, and install requested extensions."""
        verify_duckdb_version()
        conn_cfg: dict[str, str | bool | int | float | list[str]] = {
            "memory_limit": self._config.effective_memory_limit(),
            "threads": str(self._config.effective_threads()),
            "temp_directory": self._config.temp_directory,
        }
        if self._config.extension_directory:
            conn_cfg["extension_directory"] = self._config.extension_directory
        if self._config.allow_unsigned_extensions:
            conn_cfg["allow_unsigned_extensions"] = "true"
        database_uri = f":memory:goe_{self._config.execution_key}"
        self._sqlspec_config = DuckDBConfig(
            connection_config={"database": database_uri, **conn_cfg},
        )
        conn = duckdb.connect(database_uri, config=conn_cfg)
        conn.execute("LOAD parquet; LOAD httpfs;")
        pragma_sql = (
            "SET parquet_metadata_cache = true; "
            "SET httpfs_connection_caching = true; "
            "SET enable_http_metadata_cache = true; "
            "SET http_keep_alive = true; "
            "SET preserve_insertion_order = false; "
            f"SET max_temp_directory_size = {sql_string_literal(self._config.max_temp_directory_size)};"
        )
        try:
            conn.execute(pragma_sql)
        except duckdb.ParserException:
            conn.execute(
                "SET parquet_metadata_cache = true; "
                "SET httpfs_connection_caching = true; "
                "SET enable_http_metadata_cache = true; "
                "SET http_keep_alive = true; "
                "SET preserve_insertion_order = false;"
            )
        if load_oracle:
            load_oracle_extension(conn, self._config)
            conn_limit = max(8, self._config.parallelism + 2)
            conn.execute(
                f"SET oracle_call_timeout_ms = {int(self._config.oracle_call_timeout_ms)}; "
                f"SET oracle_array_size = {int(self._config.oracle_array_size)}; "
                f"SET oracle_connection_limit = {conn_limit};"
            )
        if cloud_secret is not None:
            self.configure_cloud_secret(cloud_secret, conn=conn)
        self._conn = conn
        return conn

    @contextmanager
    def cursor(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a lightweight thread-local cursor over the shared DuckDB instance."""
        if self._conn is None:
            raise RuntimeError("DuckDBEngine session is not open")
        cur = self._conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    def configure_cloud_secret(
        self,
        spec: CloudStorageSecretSpec,
        *,
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        """Create or rotate the temporary cloud storage secret in-place."""
        target = conn or self._conn
        if target is None:
            raise RuntimeError("DuckDBEngine session is not open")
        if spec.scheme == "gs":
            if not spec.bearer_token:
                raise ValueError("GCS secret requires bearer_token")
            target.execute(
                f"CREATE OR REPLACE TEMPORARY SECRET {DUCKDB_GCS_SECRET_NAME} "
                f"(TYPE gcs, BEARER_TOKEN {sql_string_literal(spec.bearer_token)});"
            )
        elif spec.scheme in ("s3", "s3a"):
            clauses = ["TYPE s3"]
            if spec.key_id:
                clauses.append(f"KEY_ID {sql_string_literal(spec.key_id)}")
            if spec.secret:
                clauses.append(f"SECRET {sql_string_literal(spec.secret)}")
            if spec.session_token:
                clauses.append(f"SESSION_TOKEN {sql_string_literal(spec.session_token)}")
            if spec.region:
                clauses.append(f"REGION {sql_string_literal(spec.region)}")
            target.execute(f"CREATE OR REPLACE TEMPORARY SECRET {DUCKDB_S3_SECRET_NAME} ({', '.join(clauses)});")
        elif spec.scheme in ("az", "abfs", "abfss", "wasb", "wasbs"):
            clauses = ["TYPE azure"]
            if spec.connection_string:
                clauses.append(f"CONNECTION_STRING {sql_string_literal(spec.connection_string)}")
            if spec.account_name:
                clauses.append(f"ACCOUNT_NAME {sql_string_literal(spec.account_name)}")
            target.execute(f"CREATE OR REPLACE TEMPORARY SECRET {DUCKDB_AZURE_SECRET_NAME} ({', '.join(clauses)});")

    def close(self) -> None:
        """Close the shared DuckDB connection cleanly."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def verify_duckdb_version(min_version: str = MIN_SUPPORTED_DUCKDB_VERSION) -> None:
    """Raise RuntimeError if the installed DuckDB version is older than min_version."""
    if Version(duckdb.__version__) < Version(min_version):
        raise RuntimeError(f"DuckDB >= {min_version} is required, found {duckdb.__version__}")


def parse_ezconnect_dsn(dsn: str | None) -> OracleEzConnect | None:
    """Return host, port, and service from an EZConnect DSN, or None for TNS aliases."""
    match = EZCONNECT_DSN_RE.match((dsn or "").strip())
    if not match:
        return None
    return OracleEzConnect(
        host=match["host"],
        port=int(match["port"] or DEFAULT_ORACLE_PORT),
        service=match["service"],
    )


def sql_string_literal(value: str) -> str:
    """Return value as a single-quoted SQL string literal with embedded quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


def load_oracle_extension(conn: duckdb.DuckDBPyConnection, settings: DuckDBSessionConfig) -> None:
    """Load duckdb-oracle from extension_path, pre-seeded extension_directory, or community repository."""
    if settings.extension_path:
        conn.execute(f"LOAD {sql_string_literal(settings.extension_path)};")
        return
    try:
        conn.execute("LOAD oracle;")
    except duckdb.Error:
        with _EXTENSION_INSTALL_LOCK:
            repo = settings.extension_repository or "community"
            repo_clause = "community" if repo == "community" else sql_string_literal(repo)
            conn.execute(f"INSTALL oracle FROM {repo_clause};")
            conn.execute("LOAD oracle;")


def attach_oracle(
    conn: duckdb.DuckDBPyConnection,
    *,
    user: str | None,
    password: str | None,
    dsn: str,
    wallet_path: str | None = None,
) -> None:
    """Create or replace a temporary oracle secret and attach it under DUCKDB_ORACLE_ATTACH_ALIAS."""
    ezconnect = parse_ezconnect_dsn(dsn)
    clauses = ["TYPE oracle"]
    if ezconnect is not None:
        clauses.extend(
            [
                f"HOST {sql_string_literal(ezconnect.host)}",
                f"PORT {int(ezconnect.port)}",
                f"SERVICE {sql_string_literal(ezconnect.service)}",
            ]
        )
    else:
        clauses.append(f"SERVICE {sql_string_literal(dsn.strip())}")
    if wallet_path:
        clauses.append(f"WALLET_PATH {sql_string_literal(wallet_path)}")
    if user:
        clauses.append(f"USER {sql_string_literal(user)}")
    if password:
        clauses.append(f"PASSWORD {sql_string_literal(password)}")
    conn.execute(f"CREATE OR REPLACE TEMPORARY SECRET {DUCKDB_ORACLE_SECRET_NAME} ({', '.join(clauses)});")
    conn.execute(
        f"ATTACH IF NOT EXISTS '' AS {DUCKDB_ORACLE_ATTACH_ALIAS} (TYPE oracle, SECRET {DUCKDB_ORACLE_SECRET_NAME});"
    )


def build_cast_projection(staging_columns: Sequence[ColumnMetadataInterface]) -> str:
    """Cast each result column to its target DuckDB Parquet staging type."""
    if not staging_columns:
        return "*"
    expressions: list[str] = []
    for column in staging_columns:
        duckdb_type = DUCKDB_PARQUET_CAST_TYPES.get(column.data_type)
        if duckdb_type is None:
            raise ValueError(f"Unsupported Parquet staging type for DuckDB transport: {column.data_type}")
        name = (column.staging_file_column_name or column.name).replace('"', '""')
        expressions.append(f'CAST("{name}" AS {duckdb_type}) AS "{name}"')
    return ", ".join(expressions)


def verify_batch_scn_invariant(batch_sql: str, consistent_read: bool, snapshot_scn: int | None) -> None:
    """Raise ValueError when consistent read is enabled but the batch SQL lacks AS OF SCN."""
    expected = f"AS OF SCN {snapshot_scn}"
    if consistent_read and snapshot_scn is not None and expected not in batch_sql.upper():
        raise ValueError(f"DuckDB transport SCN invariant violated: expected '{expected}' in batch SQL")

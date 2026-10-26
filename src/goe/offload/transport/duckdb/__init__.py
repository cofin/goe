# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""DuckDB 2.0 transport engine, Oracle extension pushdown, and multi-file Parquet writer."""

from goe.offload.transport.duckdb.engine import (
    DEFAULT_ORACLE_PORT,
    DUCKDB_PARQUET_CAST_TYPES,
    EZCONNECT_DSN_RE,
    CloudStorageSecretSpec,
    DuckDBEngine,
    DuckDBSessionConfig,
    OracleEzConnect,
    attach_oracle,
    build_cast_projection,
    load_oracle_extension,
    parse_ezconnect_dsn,
    sql_string_literal,
    verify_batch_scn_invariant,
    verify_duckdb_version,
)
from goe.offload.transport.duckdb.oracle_pushdown import (
    MAX_ORACLE_EXTENSION_NUMBER_PRECISION,
    MAX_ORACLE_EXTENSION_PRECISION_CAP,
    ORACLE_EXTENSION_FALLBACK_TYPES,
    OracleExtensionTransport,
    OracleFallbackAssessment,
    OraclePushdownPlan,
)
from goe.offload.transport.duckdb.parquet_writer import (
    DEFAULT_PARQUET_FILE_SIZE_BYTES,
    DuckDBParquetWriter,
    ParquetCompression,
    ParquetWriteOptions,
    StagedFileManifest,
    StagedParquetFile,
)

__all__ = [
    "DEFAULT_ORACLE_PORT",
    "DEFAULT_PARQUET_FILE_SIZE_BYTES",
    "DUCKDB_PARQUET_CAST_TYPES",
    "EZCONNECT_DSN_RE",
    "MAX_ORACLE_EXTENSION_NUMBER_PRECISION",
    "MAX_ORACLE_EXTENSION_PRECISION_CAP",
    "ORACLE_EXTENSION_FALLBACK_TYPES",
    "CloudStorageSecretSpec",
    "DuckDBEngine",
    "DuckDBParquetWriter",
    "DuckDBSessionConfig",
    "OracleExtensionTransport",
    "OracleEzConnect",
    "OracleFallbackAssessment",
    "OraclePushdownPlan",
    "ParquetCompression",
    "ParquetWriteOptions",
    "StagedFileManifest",
    "StagedParquetFile",
    "attach_oracle",
    "build_cast_projection",
    "load_oracle_extension",
    "parse_ezconnect_dsn",
    "sql_string_literal",
    "verify_batch_scn_invariant",
    "verify_duckdb_version",
]

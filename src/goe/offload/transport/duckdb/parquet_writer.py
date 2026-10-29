# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Multi-file DuckDB 2.0 Parquet COPY writer and footer-verified StagedFileManifest."""

from pathlib import Path
from typing import Literal

import duckdb

from goe.offload.transport.duckdb.engine import sql_string_literal
from goe.typing import FrozenBaseStruct

__all__ = [
    "DEFAULT_PARQUET_FILE_SIZE_BYTES",
    "DuckDBParquetWriter",
    "ParquetCompression",
    "ParquetWriteOptions",
    "StagedFileManifest",
    "StagedParquetFile",
]

ParquetCompression = Literal["SNAPPY", "ZSTD", "UNCOMPRESSED"]
DEFAULT_PARQUET_FILE_SIZE_BYTES = 256 * 1024 * 1024


class ParquetWriteOptions(FrozenBaseStruct, frozen=True, kw_only=True):
    """Configuration options for DuckDB Parquet COPY output."""

    compression: ParquetCompression = "SNAPPY"
    file_size_bytes: int | None = DEFAULT_PARQUET_FILE_SIZE_BYTES
    per_thread_output: bool = True
    filename_pattern: str = "part-{i}"


class StagedParquetFile(FrozenBaseStruct, frozen=True, kw_only=True):
    """Metadata for a single staged Parquet file."""

    uri: str
    row_count: int
    size_bytes: int = 0


class StagedFileManifest(FrozenBaseStruct, frozen=True, kw_only=True):
    """Immutable manifest returned after staging Parquet or Avro files."""

    target_uri: str
    compression: str
    files: tuple[StagedParquetFile, ...]
    total_rows: int
    total_bytes: int


class DuckDBParquetWriter:
    """Streams a DuckDB SQL relation or registered Arrow view to Parquet files and returns a StagedFileManifest."""

    def __init__(self, options: ParquetWriteOptions | None = None) -> None:
        self._options = options or ParquetWriteOptions()

    @property
    def options(self) -> ParquetWriteOptions:
        """Return the configured Parquet write options."""
        return self._options

    def build_copy_sql(self, relation_sql: str, target_uri: str) -> str:
        """Build the DuckDB 2.0 COPY ... TO statement with FORMAT PARQUET and RETURN_FILES."""
        clauses = [
            "FORMAT PARQUET",
            f"COMPRESSION {self._options.compression}",
        ]
        use_multi_file = self._options.per_thread_output and not target_uri.lower().endswith(".parquet")
        if use_multi_file:
            if self._options.file_size_bytes and self._options.file_size_bytes > 0:
                clauses.append(f"FILE_SIZE_BYTES {int(self._options.file_size_bytes)}")
            clauses.append("PER_THREAD_OUTPUT true")
            clauses.append("OVERWRITE_OR_IGNORE true")
            clauses.append(f"FILENAME_PATTERN {sql_string_literal(self._options.filename_pattern)}")
        clauses.append("RETURN_FILES true")
        return f"COPY ({relation_sql}) TO {sql_string_literal(target_uri)} ({', '.join(clauses)});"

    def write_relation(
        self,
        cursor: duckdb.DuckDBPyConnection,
        relation_sql: str,
        target_uri: str,
    ) -> StagedFileManifest:
        """Execute COPY ... TO, verify footer row counts, and return a StagedFileManifest."""
        copy_sql = self.build_copy_sql(relation_sql, target_uri)
        rows = cursor.execute(copy_sql).fetchall()
        written_uris = self._extract_written_uris(rows, target_uri)
        staged_files: list[StagedParquetFile] = []
        total_rows = 0
        total_bytes = 0
        for uri in written_uris:
            file_rows = self._read_footer_row_count(cursor, uri)
            file_bytes = self._read_local_file_size(uri)
            staged_files.append(StagedParquetFile(uri=uri, row_count=file_rows, size_bytes=file_bytes))
            total_rows += file_rows
            total_bytes += file_bytes
        return StagedFileManifest(
            target_uri=target_uri,
            compression=self._options.compression,
            files=tuple(staged_files),
            total_rows=total_rows,
            total_bytes=total_bytes,
        )

    @staticmethod
    def _extract_written_uris(rows: list[tuple[object, ...]], fallback_uri: str) -> list[str]:
        """Extract file URI strings returned by DuckDB COPY ... (RETURN_FILES true)."""
        uris: list[str] = []
        for row in rows:
            for cell in row:
                if isinstance(cell, str):
                    uris.append(cell)
                elif isinstance(cell, (list, tuple)):
                    uris.extend(str(item) for item in cell if item)
        if not uris and not fallback_uri.endswith("/"):
            local = Path(fallback_uri)
            if local.is_file():
                uris.append(fallback_uri)
        return uris

    @staticmethod
    def _read_footer_row_count(cursor: duckdb.DuckDBPyConnection, file_uri: str) -> int:
        """Return the total row count recorded in the Parquet footer for file_uri."""
        rows = cursor.execute(
            f"SELECT COALESCE(SUM(num_rows), 0)::BIGINT FROM parquet_file_metadata({sql_string_literal(file_uri)});"
        ).fetchall()
        return int(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0

    @staticmethod
    def _read_local_file_size(file_uri: str) -> int:
        """Return file size in bytes when file_uri refers to a local filesystem path."""
        if "://" in file_uri:
            return 0
        path = Path(file_uri)
        return path.stat().st_size if path.is_file() else 0

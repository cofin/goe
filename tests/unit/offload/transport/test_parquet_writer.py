# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for DuckDBParquetWriter and StagedFileManifest."""

from pathlib import Path

from goe.offload.transport.duckdb import (
    DuckDBEngine,
    DuckDBParquetWriter,
    DuckDBSessionConfig,
    ParquetWriteOptions,
)


def test_parquet_writer_builds_copy_sql_with_file_size_per_thread_and_return_files() -> None:
    """DuckDBParquetWriter.build_copy_sql emits exact multi-file and single-file COPY ... TO syntax."""
    multi_writer = DuckDBParquetWriter(
        ParquetWriteOptions(
            compression="ZSTD",
            file_size_bytes=134_217_728,
            per_thread_output=True,
            filename_pattern="part-{i}",
        )
    )
    multi_sql = multi_writer.build_copy_sql("SELECT * FROM src_rel", "gs://bucket/stage/table_dir")
    assert multi_sql == (
        "COPY (SELECT * FROM src_rel) TO 'gs://bucket/stage/table_dir' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, FILE_SIZE_BYTES 134217728, "
        "PER_THREAD_OUTPUT true, OVERWRITE_OR_IGNORE true, FILENAME_PATTERN 'part-{i}', RETURN_FILES true);"
    )

    single_writer = DuckDBParquetWriter(
        ParquetWriteOptions(
            compression="SNAPPY",
            per_thread_output=False,
        )
    )
    single_sql = single_writer.build_copy_sql("SELECT * FROM src_rel", "gs://bucket/stage/part-00000.parquet")
    assert single_sql == (
        "COPY (SELECT * FROM src_rel) TO 'gs://bucket/stage/part-00000.parquet' "
        "(FORMAT PARQUET, COMPRESSION SNAPPY, RETURN_FILES true);"
    )


def test_parquet_writer_writes_multi_file_parquet_and_returns_verified_manifest(tmp_path: Path) -> None:
    """write_relation streams 10,000 rows to Parquet and verifies footer row counts in StagedFileManifest."""
    engine = DuckDBEngine(
        DuckDBSessionConfig(
            execution_key="pw01",
            parallelism=2,
            temp_directory=str(tmp_path / "spill"),
        )
    )
    engine.open()
    try:
        out_dir = tmp_path / "staged_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        writer = DuckDBParquetWriter(
            ParquetWriteOptions(
                compression="SNAPPY",
                file_size_bytes=64 * 1024,
                per_thread_output=True,
            )
        )
        with engine.cursor() as cur:
            manifest = writer.write_relation(
                cur,
                "SELECT i AS id, 'payload_' || i::VARCHAR AS label FROM range(10000) t(i)",
                str(out_dir),
            )
        assert manifest.total_rows == 10_000
        assert len(manifest.files) >= 1
        assert manifest.total_bytes > 0
        assert manifest.compression == "SNAPPY"
        assert sum(f.row_count for f in manifest.files) == 10_000
    finally:
        engine.close()


def test_parquet_writer_handles_empty_relation_deterministically(tmp_path: Path) -> None:
    """write_relation handles a 0-row empty query without raising footer metadata errors."""
    engine = DuckDBEngine(
        DuckDBSessionConfig(
            execution_key="pw02",
            parallelism=1,
            temp_directory=str(tmp_path / "spill"),
        )
    )
    engine.open()
    try:
        out_dir = tmp_path / "empty_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        writer = DuckDBParquetWriter()
        with engine.cursor() as cur:
            manifest = writer.write_relation(
                cur,
                "SELECT 1::BIGINT AS id, 'none'::VARCHAR AS label WHERE 1 = 0",
                str(out_dir),
            )
        assert manifest.total_rows == 0
    finally:
        engine.close()

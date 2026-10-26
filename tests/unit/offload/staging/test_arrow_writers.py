# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for ArrowParquetStagingWriter and ArrowAvroStagingWriter."""

import base64
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import avro.datafile
import avro.io
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from goe.offload.staging.arrow_writers import (
    ArrowAvroStagingWriter,
    ArrowParquetStagingWriter,
)
from goe.offload.staging.parquet.parquet_column import (
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
    StagingParquetColumn,
)
from goe.offload.transport.duckdb import (
    DuckDBEngine,
    DuckDBSessionConfig,
    ParquetWriteOptions,
)
from goe.util.module_loader import import_optional


def test_arrow_parquet_staging_writer_streams_reader_and_unregisters_view_on_success_and_error(
    tmp_path: Path,
) -> None:
    """ArrowParquetStagingWriter streams RecordBatchReader via DuckDB and always unregisters the view."""
    engine = DuckDBEngine(
        DuckDBSessionConfig(
            execution_key="apw01",
            parallelism=1,
            temp_directory=str(tmp_path / "spill"),
        )
    )
    engine.open()
    try:
        cols = [
            StagingParquetColumn("ID", PARQUET_TYPE_INT64),
            StagingParquetColumn("NAME", PARQUET_TYPE_STRING),
        ]
        schema = pa.schema([("ID", pa.int64()), ("NAME", pa.string())])
        batches = [
            pa.RecordBatch.from_arrays(
                [pa.array([1, 2], type=pa.int64()), pa.array(["alpha", "beta"], type=pa.string())],
                schema=schema,
            ),
            pa.RecordBatch.from_arrays(
                [pa.array([3], type=pa.int64()), pa.array(["gamma"], type=pa.string())],
                schema=schema,
            ),
        ]
        reader = pa.RecordBatchReader.from_batches(schema, iter(batches))
        out_file = tmp_path / "part-00000.parquet"
        writer = ArrowParquetStagingWriter(
            engine,
            write_options=ParquetWriteOptions(compression="SNAPPY", per_thread_output=False),
        )
        manifest = writer.write(reader, cols, str(out_file))
        assert manifest.total_rows == 3
        table = pq.read_table(out_file)
        assert table.to_pylist() == [
            {"ID": 1, "NAME": "alpha"},
            {"ID": 2, "NAME": "beta"},
            {"ID": 3, "NAME": "gamma"},
        ]

        mock_engine = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = duckdb.IOException("simulated write failure")
        cm = MagicMock()
        cm.__enter__.return_value = mock_cursor
        cm.__exit__.return_value = False
        mock_engine.cursor.return_value = cm

        err_writer = ArrowParquetStagingWriter(mock_engine)
        err_reader = pa.RecordBatchReader.from_batches(schema, iter([]))
        with pytest.raises(duckdb.IOException, match="simulated write failure"):
            err_writer.write(err_reader, cols, str(tmp_path / "fail.parquet"))
        mock_cursor.register.assert_called_once()
        registered_view = mock_cursor.register.call_args.args[0]
        mock_cursor.unregister.assert_called_once_with(registered_view)
    finally:
        engine.close()


def test_arrow_avro_staging_writer_streams_batches_with_canonical_goe_schema_and_deflate(
    tmp_path: Path,
) -> None:
    """ArrowAvroStagingWriter writes canonical Avro container files with deflate/null and base64 decoding."""
    avro_schema = {
        "type": "record",
        "name": "orders_stage",
        "namespace": "goe.stage",
        "fields": [
            {"name": "ID", "type": ["null", "long"]},
            {"name": "NAME", "type": ["null", "string"]},
            {"name": "RAW_B64", "type": ["null", "bytes"]},
        ],
    }
    b64_payload = base64.b64encode(b"\x00\x01\x02\xff").decode("ascii")
    pa_schema = pa.schema(
        [
            pa.field("ID", pa.int64()),
            pa.field("NAME", pa.string()),
            pa.field("RAW_B64", pa.string()),
        ]
    )
    batch = pa.RecordBatch.from_arrays(
        [
            pa.array([10, 20], type=pa.int64()),
            pa.array(["row1", None], type=pa.string()),
            pa.array([b64_payload, None], type=pa.string()),
        ],
        schema=pa_schema,
    )
    reader = pa.RecordBatchReader.from_batches(pa_schema, [batch])
    out_path = tmp_path / "part-00000.avro"

    writer = ArrowAvroStagingWriter(
        avro_schema,
        compress=True,
        base64_columns=("RAW_B64",),
    )
    manifest = writer.write(reader, out_path)
    assert manifest.total_rows == 2
    assert manifest.compression == "DEFLATE"
    assert manifest.total_bytes > 0

    records = _read_avro_records(out_path)
    assert records == [
        {"ID": 10, "NAME": "row1", "RAW_B64": b"\x00\x01\x02\xff"},
        {"ID": 20, "NAME": None, "RAW_B64": None},
    ]


def test_arrow_avro_staging_writer_writes_valid_empty_container_for_zero_rows(tmp_path: Path) -> None:
    """A 0-row RecordBatchReader produces a valid 0-record Avro container file with intact header schema."""
    avro_schema = {
        "type": "record",
        "name": "empty_stage",
        "fields": [
            {"name": "ID", "type": ["null", "long"]},
            {"name": "NAME", "type": ["null", "string"]},
        ],
    }
    pa_schema = pa.schema([("ID", pa.int64()), ("NAME", pa.string())])
    reader = pa.RecordBatchReader.from_batches(pa_schema, iter([]))
    out_path = tmp_path / "empty.avro"

    writer = ArrowAvroStagingWriter(avro_schema, compress=False)
    manifest = writer.write(reader, out_path)
    assert manifest.total_rows == 0
    assert manifest.compression == "NULL"
    assert out_path.is_file()
    assert _read_avro_records(out_path) == []


def _read_avro_records(path: Path) -> list[dict[str, Any]]:
    """Read all records from an Avro container file using fastavro or standard avro."""
    fastavro = import_optional("fastavro")
    if fastavro is not None:
        with path.open("rb") as fh:
            return list(fastavro.reader(fh))
    with path.open("rb") as fh:
        with avro.datafile.DataFileReader(fh, avro.io.DatumReader()) as reader:
            return list(reader)

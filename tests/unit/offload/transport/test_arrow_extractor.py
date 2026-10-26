# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for OracleArrowStreamExtractor lazy RecordBatchReader extraction."""

import base64
import math
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pyarrow as pa

from goe.offload.schema.column_spec import (
    ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
    PARQUET_TYPE_BINARY,
    PARQUET_TYPE_DOUBLE,
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
    ColumnDialect,
    ColumnSpec,
)
from goe.offload.transport.arrow_extractor import (
    ArrowExtractionConfig,
    OracleArrowStreamExtractor,
)


class _FakeOracleDataFrame:
    """Fake OracleDataFrame exposing the Arrow PyCapsule __arrow_c_stream__ protocol."""

    def __init__(self, batch: pa.RecordBatch) -> None:
        self._batch = batch

    def __arrow_c_stream__(self, requested_schema: object = None) -> object:
        reader = pa.RecordBatchReader.from_batches(self._batch.schema, [self._batch])
        return reader.__arrow_c_stream__(requested_schema)


def test_arrow_extractor_streams_batches_lazily_without_eager_materialization() -> None:
    """extract_record_batch_reader pulls at most the first batch on construction and streams on demand."""
    pulled_batches = 0
    schema = pa.schema([("ID", pa.int64()), ("NAME", pa.string())])

    def df_generator() -> Iterator[_FakeOracleDataFrame]:
        nonlocal pulled_batches
        for idx in range(3):
            pulled_batches += 1
            batch = pa.RecordBatch.from_arrays(
                [pa.array([idx * 10 + 1, idx * 10 + 2], type=pa.int64()), pa.array(["a", "b"], type=pa.string())],
                schema=schema,
            )
            yield _FakeOracleDataFrame(batch)

    conn = MagicMock()
    conn.fetch_df_batches.return_value = df_generator()
    staging_cols = [
        ColumnSpec(ColumnDialect.PARQUET, "ID", PARQUET_TYPE_INT64),
        ColumnSpec(ColumnDialect.PARQUET, "NAME", PARQUET_TYPE_STRING),
    ]
    extractor = OracleArrowStreamExtractor(ArrowExtractionConfig(batch_size=2))
    reader = extractor.extract_record_batch_reader(conn, "SELECT id, name FROM t", None, staging_cols)
    assert pulled_batches == 1

    first = next(reader)
    assert first.num_rows == 2
    assert pulled_batches == 1

    second = next(reader)
    assert second.num_rows == 2
    assert pulled_batches == 2

    third = next(reader)
    assert third.num_rows == 2
    assert pulled_batches == 3


def test_arrow_extractor_preserves_decimal128_intervals_timestamptz_lobs_and_nanoseconds() -> None:
    """normalize_batch preserves decimal128(38, 9), large LOBs, intervals, nanosecond timestamps, and NaN scrubbing."""
    large_clob = "X" * (130 * 1024)
    large_blob = b"\xab" * (130 * 1024)
    raw_b64 = base64.b64encode(b"raw-bytes-payload").decode("ascii")

    raw_schema = pa.schema(
        [
            pa.field("DEC38", pa.decimal128(38, 9)),
            pa.field("UNBOUNDED_NUM", pa.string()),
            pa.field("INT_YM", pa.string()),
            pa.field("INT_DS", pa.string()),
            pa.field("TS_TZ", pa.string()),
            pa.field("TS_LTZ", pa.string()),
            pa.field("TS_NANO", pa.string()),
            pa.field("CLOB_COL", pa.string()),
            pa.field("BLOB_COL", pa.binary()),
            pa.field("RAW_B64", pa.string()),
            pa.field("DBL_COL", pa.float64()),
        ]
    )
    raw_batch = pa.RecordBatch.from_arrays(
        [
            pa.array([Decimal("12345678901234567890123456789.123456789"), None], type=pa.decimal128(38, 9)),
            pa.array(["99999999999999999999999999999999999999999", None], type=pa.string()),
            pa.array(["+0123-06", None], type=pa.string()),
            pa.array(["+00012 05:06:07.123456", None], type=pa.string()),
            pa.array(["2026-10-24 12:34:56.123456 +00:00", None], type=pa.string()),
            pa.array(["2026-10-24 12:34:56.", None], type=pa.string()),
            pa.array(["2026-10-24 12:34:56.123456789", None], type=pa.string()),
            pa.array([large_clob, None], type=pa.string()),
            pa.array([large_blob, None], type=pa.binary()),
            pa.array([raw_b64, None], type=pa.string()),
            pa.array([math.nan, 42.5], type=pa.float64()),
        ],
        schema=raw_schema,
    )
    staging_cols = [
        ColumnSpec(ColumnDialect.PARQUET, "DEC38", PARQUET_TYPE_STRING),
        ColumnSpec(ColumnDialect.PARQUET, "UNBOUNDED_NUM", PARQUET_TYPE_STRING),
        ColumnSpec(ColumnDialect.PARQUET, "INT_YM", PARQUET_TYPE_STRING),
        ColumnSpec(ColumnDialect.PARQUET, "INT_DS", PARQUET_TYPE_STRING),
        ColumnSpec(ColumnDialect.PARQUET, "TS_TZ", PARQUET_TYPE_STRING),
        ColumnSpec(ColumnDialect.PARQUET, "TS_LTZ", PARQUET_TYPE_STRING),
        ColumnSpec(ColumnDialect.PARQUET, "TS_NANO", PARQUET_TYPE_STRING),
        ColumnSpec(ColumnDialect.PARQUET, "CLOB_COL", PARQUET_TYPE_STRING),
        ColumnSpec(ColumnDialect.PARQUET, "BLOB_COL", PARQUET_TYPE_BINARY),
        ColumnSpec(ColumnDialect.PARQUET, "RAW_B64", PARQUET_TYPE_BINARY),
        ColumnSpec(ColumnDialect.PARQUET, "DBL_COL", PARQUET_TYPE_DOUBLE),
    ]
    source_cols = [
        SimpleNamespace(name=col.name, data_type=(ORACLE_TYPE_TIMESTAMP_LOCAL_TZ if col.name == "TS_LTZ" else "OTHER"))
        for col in staging_cols
    ]

    conn = MagicMock()
    conn.fetch_df_batches.return_value = [_FakeOracleDataFrame(raw_batch)]

    extractor = OracleArrowStreamExtractor(
        ArrowExtractionConfig(
            nan_values_as_null=True,
            base64_columns=frozenset({"RAW_B64"}),
        )
    )
    reader = extractor.extract_record_batch_reader(
        conn,
        "SELECT * FROM t",
        None,
        staging_cols,
        source_columns=source_cols,
    )
    table = reader.read_all()
    assert table.num_rows == 2
    assert table.schema.field("DEC38").type == pa.decimal128(38, 9)
    rows = table.to_pylist()
    assert rows[0]["DEC38"] == Decimal("12345678901234567890123456789.123456789")
    assert rows[0]["TS_LTZ"] == "2026-10-24 12:34:56"
    assert rows[0]["TS_NANO"] == "2026-10-24 12:34:56.123456789"
    assert len(rows[0]["CLOB_COL"]) == 130 * 1024
    assert len(rows[0]["BLOB_COL"]) == 130 * 1024
    assert rows[0]["RAW_B64"] == b"raw-bytes-payload"
    assert rows[0]["DBL_COL"] is None
    assert rows[1]["DBL_COL"] == 42.5


def test_arrow_extractor_returns_typed_empty_reader_for_zero_rows() -> None:
    """A 0-row query returns a typed pa.RecordBatchReader with num_rows == 0."""
    conn = MagicMock()
    conn.fetch_df_batches.return_value = []
    staging_cols = [
        ColumnSpec(ColumnDialect.PARQUET, "ID", PARQUET_TYPE_INT64),
        ColumnSpec(ColumnDialect.PARQUET, "NAME", PARQUET_TYPE_STRING),
    ]
    extractor = OracleArrowStreamExtractor()
    reader = extractor.extract_record_batch_reader(conn, "SELECT id, name FROM t WHERE 1=0", None, staging_cols)
    table = reader.read_all()
    assert table.num_rows == 0
    assert table.schema.names == ["ID", "NAME"]
    assert table.schema.field("ID").type == pa.int64()
    assert table.schema.field("NAME").type == pa.string()

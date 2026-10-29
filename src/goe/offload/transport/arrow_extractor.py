# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Lazy PyCapsule Arrow batch extractor over python-oracledb fetch_df_batches."""

import base64
import math
from collections.abc import Iterator, Sequence
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from goe.offload.schema.column_spec import (
    AVRO_TYPE_BOOLEAN,
    AVRO_TYPE_BYTES,
    AVRO_TYPE_DOUBLE,
    AVRO_TYPE_FLOAT,
    AVRO_TYPE_INT,
    AVRO_TYPE_LONG,
    AVRO_TYPE_STRING,
    ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
    PARQUET_TYPE_BINARY,
    PARQUET_TYPE_BOOLEAN,
    PARQUET_TYPE_DOUBLE,
    PARQUET_TYPE_FLOAT,
    PARQUET_TYPE_INT32,
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
    ColumnSpec,
)
from goe.typing import FrozenBaseStruct
from goe.util.module_loader import import_optional

__all__ = [
    "DEFAULT_ARROW_BATCH_SIZE",
    "STAGING_TO_ARROW_TYPE",
    "ArrowExtractionConfig",
    "OracleArrowStreamExtractor",
]

_oracledb = import_optional("oracledb")

DEFAULT_ARROW_BATCH_SIZE = 65_536
STAGING_TO_ARROW_TYPE: dict[str, pa.DataType] = {
    PARQUET_TYPE_STRING: pa.string(),
    PARQUET_TYPE_BINARY: pa.binary(),
    PARQUET_TYPE_INT32: pa.int32(),
    PARQUET_TYPE_INT64: pa.int64(),
    PARQUET_TYPE_FLOAT: pa.float32(),
    PARQUET_TYPE_DOUBLE: pa.float64(),
    PARQUET_TYPE_BOOLEAN: pa.bool_(),
    AVRO_TYPE_STRING: pa.string(),
    AVRO_TYPE_BYTES: pa.binary(),
    AVRO_TYPE_INT: pa.int32(),
    AVRO_TYPE_LONG: pa.int64(),
    AVRO_TYPE_FLOAT: pa.float32(),
    AVRO_TYPE_DOUBLE: pa.float64(),
    AVRO_TYPE_BOOLEAN: pa.bool_(),
}


class ArrowExtractionConfig(FrozenBaseStruct, frozen=True, kw_only=True):
    """Configuration for streaming Oracle rows as PyArrow RecordBatches."""

    batch_size: int = DEFAULT_ARROW_BATCH_SIZE
    fetch_decimals: bool = True
    nan_values_as_null: bool = False
    base64_columns: frozenset[str] = frozenset()


class OracleArrowStreamExtractor:
    """Streams Oracle extraction queries into a lazy pyarrow.RecordBatchReader."""

    def __init__(self, config: ArrowExtractionConfig | None = None) -> None:
        self._config = config or ArrowExtractionConfig()

    @property
    def config(self) -> ArrowExtractionConfig:
        """Return the extractor configuration."""
        return self._config

    @staticmethod
    def build_expected_arrow_schema(staging_columns: Sequence[ColumnSpec]) -> pa.Schema:
        """Build the target Arrow schema from GOE staging column metadata."""
        fields: list[pa.Field] = []
        for col in staging_columns:
            col_name = col.staging_file_column_name or col.name
            dtype = STAGING_TO_ARROW_TYPE.get(col.data_type, pa.string())
            raw_nullable = getattr(col, "nullable", True)
            nullable = True if raw_nullable is None else bool(raw_nullable)
            fields.append(pa.field(col_name, dtype, nullable=nullable))
        return pa.schema(fields)

    @staticmethod
    def output_type_handler(cursor: Any, metadata: Any) -> Any:
        """Normalize LOBs, intervals, and high-precision numbers when cursor fallback is used."""
        if _oracledb is None:
            return None
        db_type = getattr(metadata, "type_code", None)
        if db_type in (_oracledb.DB_TYPE_CLOB, _oracledb.DB_TYPE_NCLOB, _oracledb.DB_TYPE_LONG):
            return cursor.var(_oracledb.DB_TYPE_LONG_VARCHAR, arraysize=cursor.arraysize)
        if db_type in (_oracledb.DB_TYPE_BLOB, _oracledb.DB_TYPE_LONG_RAW):
            return cursor.var(_oracledb.DB_TYPE_LONG_RAW, arraysize=cursor.arraysize)
        if db_type in (_oracledb.DB_TYPE_INTERVAL_YM, _oracledb.DB_TYPE_INTERVAL_DS):
            return cursor.var(_oracledb.DB_TYPE_VARCHAR, 128, arraysize=cursor.arraysize)
        if db_type == _oracledb.DB_TYPE_NUMBER:
            precision = getattr(metadata, "precision", 0) or 0
            scale = getattr(metadata, "scale", 0) or 0
            if precision > 18 or scale > 0:
                return cursor.var(
                    _oracledb.DB_TYPE_VARCHAR,
                    256,
                    arraysize=cursor.arraysize,
                    outconverter=Decimal,
                )
        return None

    def empty_reader(self, staging_columns: Sequence[ColumnSpec]) -> pa.RecordBatchReader:
        """Return a typed 0-row RecordBatchReader matching staging_columns."""
        target_schema = self.build_expected_arrow_schema(staging_columns)
        return pa.RecordBatchReader.from_batches(target_schema, iter(()))

    def extract_record_batch_reader(
        self,
        conn: Any,
        sql_text: str,
        binds: dict[str, Any] | None,
        staging_columns: Sequence[ColumnSpec],
        *,
        source_columns: Sequence[ColumnSpec] = (),
    ) -> pa.RecordBatchReader:
        """Return a lazy pyarrow.RecordBatchReader streaming batches from conn.fetch_df_batches."""
        target_schema = self.build_expected_arrow_schema(staging_columns)
        df_iter = iter(
            conn.fetch_df_batches(
                statement=sql_text,
                parameters=binds or {},
                size=self._config.batch_size,
                fetch_decimals=self._config.fetch_decimals,
            )
        )
        first_df = next(df_iter, None)
        if first_df is None:
            return pa.RecordBatchReader.from_batches(target_schema, iter(()))
        first_raw_batches = self._batches_from_oracle_df(first_df)
        first_batches = [
            self.normalize_batch(batch, target_schema, source_columns=source_columns) for batch in first_raw_batches
        ]
        effective_schema = first_batches[0].schema if first_batches else target_schema

        def _batch_generator() -> Iterator[pa.RecordBatch]:
            yield from first_batches
            for ora_df in df_iter:
                for raw_batch in self._batches_from_oracle_df(ora_df):
                    yield self.normalize_batch(raw_batch, effective_schema, source_columns=source_columns)

        return pa.RecordBatchReader.from_batches(effective_schema, _batch_generator())

    def from_cursor(
        self,
        cursor: Any,
        staging_columns: Sequence[ColumnSpec],
        *,
        source_columns: Sequence[ColumnSpec] = (),
    ) -> pa.RecordBatchReader:
        """Stream rows from a DB-API cursor into a lazy pyarrow.RecordBatchReader."""
        target_schema = self.build_expected_arrow_schema(staging_columns)

        def _cursor_batch_generator() -> Iterator[pa.RecordBatch]:
            while True:
                rows = cursor.fetchmany(self._config.batch_size) if self._config.batch_size else cursor.fetchmany()
                if not rows:
                    break
                yield self._rows_to_record_batch(rows, target_schema, source_columns=source_columns)

        return pa.RecordBatchReader.from_batches(target_schema, _cursor_batch_generator())

    def from_rows(
        self,
        rows: Sequence[Sequence[Any]],
        staging_columns: Sequence[ColumnSpec],
        *,
        source_columns: Sequence[ColumnSpec] = (),
    ) -> pa.RecordBatchReader:
        """Stream an in-memory sequence of row tuples into a lazy pyarrow.RecordBatchReader."""
        target_schema = self.build_expected_arrow_schema(staging_columns)
        if not rows:
            return pa.RecordBatchReader.from_batches(target_schema, iter(()))
        step = max(1, self._config.batch_size)
        slices = [rows[idx : idx + step] for idx in range(0, len(rows), step)]

        def _row_batch_generator() -> Iterator[pa.RecordBatch]:
            for chunk in slices:
                yield self._rows_to_record_batch(chunk, target_schema, source_columns=source_columns)

        return pa.RecordBatchReader.from_batches(target_schema, _row_batch_generator())

    def normalize_batch(
        self,
        batch: pa.RecordBatch,
        target_schema: pa.Schema,
        *,
        source_columns: Sequence[ColumnSpec] = (),
    ) -> pa.RecordBatch:
        """Align column names, scrub NaN/Inf floats when configured, and cast columns to target_schema."""
        arrays: list[pa.Array] = []
        fields: list[pa.Field] = []
        for idx, col_array in enumerate(batch.columns):
            target_field = target_schema[idx] if idx < len(target_schema) else batch.schema.field(idx)
            src_col = source_columns[idx] if idx < len(source_columns) else None
            arr = col_array
            if self._config.nan_values_as_null and pa.types.is_floating(arr.type):
                mask = pc.or_(pc.is_nan(arr), pc.is_inf(arr))
                arr = pc.if_else(mask, pa.scalar(None, type=arr.type), arr)
            if self._needs_python_wrangling(target_field.name, src_col):
                arr = self._python_fallback_cast(arr, target_field.type, field_name=target_field.name, src_col=src_col)
            elif arr.type != target_field.type and not pa.types.is_decimal(arr.type):
                try:
                    arr = pc.cast(arr, target_field.type)
                except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
                    arr = self._python_fallback_cast(
                        arr, target_field.type, field_name=target_field.name, src_col=src_col
                    )
            arrays.append(arr)
            fields.append(pa.field(target_field.name, arr.type, nullable=target_field.nullable))
        return pa.RecordBatch.from_arrays(arrays, schema=pa.schema(fields))

    @staticmethod
    def _batches_from_oracle_df(ora_df: Any) -> list[pa.RecordBatch]:
        """Extract pyarrow RecordBatches from an OracleDataFrame PyCapsule or PyArrow object."""
        if isinstance(ora_df, pa.RecordBatch):
            return [ora_df]
        if isinstance(ora_df, pa.Table):
            return ora_df.to_batches()
        if isinstance(ora_df, pa.RecordBatchReader):
            return list(ora_df)
        reader = pa.RecordBatchReader.from_stream(ora_df)
        return list(reader)

    def _needs_python_wrangling(self, field_name: str, src_col: ColumnSpec | None) -> bool:
        """Return True when a column requires base64 decoding or TIMESTAMP WITH LOCAL TIME ZONE dot stripping."""
        b64_upper = {getattr(c, "name", str(c)).upper() for c in self._config.base64_columns}
        if b64_upper and field_name.upper() in b64_upper:
            return True
        if src_col is not None:
            if b64_upper and getattr(src_col, "name", "").upper() in b64_upper:
                return True
            if getattr(src_col, "data_type", None) == ORACLE_TYPE_TIMESTAMP_LOCAL_TZ:
                return True
        return False

    def _rows_to_record_batch(
        self,
        rows: Sequence[Sequence[Any]],
        target_schema: pa.Schema,
        *,
        source_columns: Sequence[ColumnSpec] = (),
    ) -> pa.RecordBatch:
        """Convert a batch of Python row tuples into a normalized pyarrow.RecordBatch."""
        arrays: list[pa.Array] = []
        for col_idx, field in enumerate(target_schema):
            src_col = source_columns[col_idx] if col_idx < len(source_columns) else None
            col_values = [row[col_idx] for row in rows]
            arrays.append(self._convert_python_values(col_values, field.type, field_name=field.name, src_col=src_col))
        return pa.RecordBatch.from_arrays(arrays, schema=target_schema)

    def _python_fallback_cast(
        self,
        arr: pa.Array,
        target_type: pa.DataType,
        *,
        field_name: str = "",
        src_col: ColumnSpec | None = None,
    ) -> pa.Array:
        """Convert complex scalar objects (Decimal, memoryview, LOBs, base64, float NaN) to target_type."""
        return self._convert_python_values(arr.to_pylist(), target_type, field_name=field_name, src_col=src_col)

    def _convert_python_values(
        self,
        py_values: Sequence[Any],
        target_type: pa.DataType,
        *,
        field_name: str = "",
        src_col: ColumnSpec | None = None,
    ) -> pa.Array:
        """Normalize a sequence of Python values into a typed PyArrow Array."""
        b64_upper = {getattr(c, "name", str(c)).upper() for c in self._config.base64_columns}
        is_b64 = bool(
            b64_upper
            and (
                field_name.upper() in b64_upper
                or (src_col is not None and getattr(src_col, "name", "").upper() in b64_upper)
            )
        )
        is_tsltz = bool(src_col is not None and getattr(src_col, "data_type", None) == ORACLE_TYPE_TIMESTAMP_LOCAL_TZ)
        converted: list[Any] = []
        for raw_val in py_values:
            val = raw_val.read() if hasattr(raw_val, "read") and callable(raw_val.read) else raw_val
            if val is None:
                converted.append(None)
            elif is_b64:
                if isinstance(val, str):
                    converted.append(base64.b64decode(val))
                elif pa.types.is_string(target_type) or pa.types.is_large_string(target_type):
                    converted.append(base64.b64encode(bytes(val)).decode("ascii"))
                else:
                    converted.append(base64.b64encode(bytes(val)))
            elif isinstance(val, float) and self._config.nan_values_as_null and (math.isnan(val) or math.isinf(val)):
                converted.append(None)
            elif pa.types.is_string(target_type) or pa.types.is_large_string(target_type):
                text = val.decode("utf-8") if isinstance(val, bytes) else str(val)
                if is_tsltz:
                    if text.endswith("."):
                        text = text.rstrip(".")
                    elif not text.endswith(" UTC"):
                        text = f"{text} UTC"
                converted.append(text)
            elif pa.types.is_binary(target_type) or pa.types.is_large_binary(target_type):
                converted.append(bytes(val) if not isinstance(val, str) else val.encode("utf-8"))
            elif pa.types.is_integer(target_type):
                converted.append(int(val))
            elif pa.types.is_floating(target_type):
                fval = float(val)
                if self._config.nan_values_as_null and (math.isnan(fval) or math.isinf(fval)):
                    converted.append(None)
                else:
                    converted.append(fval)
            elif pa.types.is_boolean(target_type):
                converted.append(bool(val))
            else:
                converted.append(val)
        return pa.array(converted, type=target_type)

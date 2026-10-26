# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Streaming Arrow-to-Parquet (DuckDB 2.0) and Arrow-to-Avro staging writers."""

import base64
import uuid
from collections.abc import Iterator, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa

from goe.offload.schema.column_spec import ColumnDialect, ColumnSpec
from goe.offload.transport.arrow_extractor import ArrowExtractionConfig, OracleArrowStreamExtractor
from goe.offload.transport.duckdb.engine import DuckDBEngine, DuckDBSessionConfig, build_cast_projection
from goe.offload.transport.duckdb.parquet_writer import (
    DuckDBParquetWriter,
    ParquetWriteOptions,
    StagedFileManifest,
    StagedParquetFile,
)
from goe.serializers import decode_json, encode_json
from goe.util.module_loader import import_optional

__all__ = [
    "ArrowAvroStagingWriter",
    "ArrowParquetStagingWriter",
]

_avro_datafile = import_optional("avro.datafile")
_avro_io = import_optional("avro.io")
_avro_schema = import_optional("avro.schema")
_fastavro = import_optional("fastavro")


class ArrowParquetStagingWriter:
    """Streams a pyarrow.RecordBatchReader through a DuckDBEngine cursor into Parquet files."""

    def __init__(
        self,
        engine: DuckDBEngine | Sequence[Any] | None = None,
        messages: Any = None,
        *,
        write_options: ParquetWriteOptions | None = None,
        compression: bool = False,
        staging_columns: Sequence[ColumnSpec] = (),
        base64_columns: Sequence[Any] | None = (),
    ) -> None:
        self._engine: Any = engine if hasattr(engine, "cursor") else None
        self._messages = messages
        resolved_options = write_options or ParquetWriteOptions(
            compression="SNAPPY" if compression else "UNCOMPRESSED",
            per_thread_output=False,
        )
        self._writer = DuckDBParquetWriter(resolved_options)
        if staging_columns:
            self._staging_columns: tuple[ColumnSpec, ...] = tuple(staging_columns)
        elif isinstance(engine, Sequence) and not isinstance(engine, (str, bytes)):
            self._staging_columns = _staging_parquet_columns_from_schema(engine)
        else:
            self._staging_columns = ()
        self._base64_columns = _normalize_base64_column_names(base64_columns)

    @property
    def writer(self) -> DuckDBParquetWriter:
        """Return the underlying DuckDBParquetWriter."""
        return self._writer

    def write(
        self,
        reader: pa.RecordBatchReader,
        staging_columns: Sequence[ColumnSpec] | str | Path | None = None,
        target_uri: str | Path = "",
    ) -> StagedFileManifest:
        """Register reader on a cursor, stream COPY ... TO (FORMAT PARQUET), and always unregister."""
        if isinstance(staging_columns, (str, Path)) and not target_uri:
            resolved_uri = str(staging_columns)
            effective_columns: Sequence[ColumnSpec] = self._staging_columns
        else:
            resolved_uri = str(target_uri)
            effective_columns = (
                staging_columns
                if isinstance(staging_columns, Sequence) and not isinstance(staging_columns, (str, bytes))
                else self._staging_columns
            )
        view_name = f"goe_arrow_batch_{uuid.uuid4().hex}"
        cast_projection = build_cast_projection(effective_columns)
        owns_engine = self._engine is None
        engine = self._engine or DuckDBEngine(DuckDBSessionConfig(execution_key=uuid.uuid4().hex[:12]))
        if owns_engine:
            engine.open()
        try:
            with engine.cursor() as cursor:
                registered = False
                try:
                    cursor.register(view_name, reader)
                    registered = True
                    relation_sql = f"SELECT {cast_projection} FROM {view_name}"
                    return self._writer.write_relation(cursor, relation_sql, resolved_uri)
                finally:
                    if registered:
                        cursor.unregister(view_name)
        finally:
            if owns_engine:
                engine.close()

    def write_from_cursor(
        self,
        local_output_path: str,
        extraction_cursor: Any,
        source_columns: Sequence[ColumnSpec],
        fetch_size: int | None = None,
    ) -> int:
        """Stream rows from a DB-API cursor into local_output_path and return the staged row count."""
        effective_staging_columns = self._staging_columns or tuple(source_columns)
        extractor = OracleArrowStreamExtractor(
            ArrowExtractionConfig(
                batch_size=int(fetch_size or 65_536),
                base64_columns=self._base64_columns,
            )
        )
        reader = extractor.from_cursor(
            extraction_cursor,
            effective_staging_columns,
            source_columns=source_columns,
        )
        manifest = self.write(reader, effective_staging_columns, local_output_path)
        return manifest.total_rows


class ArrowAvroStagingWriter:
    """Streams a pyarrow.RecordBatchReader into an Avro container file."""

    def __init__(
        self,
        schema_json: str | dict[str, Any],
        messages: Any = None,
        *,
        compress: bool | None = None,
        compression: bool = False,
        base64_columns: Sequence[Any] | None = (),
        staging_columns: Sequence[ColumnSpec] = (),
    ) -> None:
        self._raw_schema: dict[str, Any] = (
            decode_json(schema_json) if isinstance(schema_json, str) else dict(schema_json)
        )
        self._messages = messages
        self._compress = compression if compress is None else compress
        self._base64_columns = _normalize_base64_column_names(base64_columns)
        self._field_types = self._extract_field_primitives(self._raw_schema)
        self._staging_columns: tuple[ColumnSpec, ...] = (
            tuple(staging_columns) if staging_columns else _staging_avro_columns_from_fields(self._field_types)
        )

    def write(self, reader: pa.RecordBatchReader, target_path: str | Path) -> StagedFileManifest:
        """Stream all RecordBatches from reader into target_path and return a StagedFileManifest."""
        codec = "deflate" if self._compress else "null"
        out_path = Path(target_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        row_count = 0
        b64_upper = {col.upper() for col in self._base64_columns}

        def _record_iterator() -> Iterator[dict[str, Any]]:
            nonlocal row_count
            for batch in reader:
                records = batch.to_pylist()
                for record in records:
                    normalized = self._normalize_record(record, b64_upper)
                    row_count += 1
                    yield normalized

        fastavro_mod = import_optional("fastavro") or _fastavro
        if fastavro_mod is not None:
            parsed_schema = fastavro_mod.parse_schema(self._raw_schema)
            with out_path.open("wb") as fh:
                fastavro_mod.writer(fh, parsed_schema, _record_iterator(), codec=codec)
        else:
            if _avro_schema is None or _avro_datafile is None or _avro_io is None:
                raise RuntimeError("Neither fastavro nor avro is installed in the current environment")
            parsed_schema = _avro_schema.parse(encode_json(self._raw_schema))
            with out_path.open("wb") as fh:
                with _avro_datafile.DataFileWriter(fh, _avro_io.DatumWriter(), parsed_schema, codec=codec) as writer:
                    for record in _record_iterator():
                        writer.append(record)

        size_bytes = out_path.stat().st_size if out_path.is_file() else 0
        return StagedFileManifest(
            target_uri=str(out_path),
            compression=codec.upper(),
            files=(StagedParquetFile(uri=str(out_path), row_count=row_count, size_bytes=size_bytes),),
            total_rows=row_count,
            total_bytes=size_bytes,
        )

    def write_from_cursor(
        self,
        local_output_path: str,
        extraction_cursor: Any,
        source_columns: Sequence[ColumnSpec],
        fetch_size: int | None = None,
    ) -> int:
        """Stream rows from a DB-API cursor into local_output_path and return the staged row count."""
        effective_staging_columns = self._staging_columns or tuple(source_columns)
        extractor = OracleArrowStreamExtractor(
            ArrowExtractionConfig(
                batch_size=int(fetch_size or 65_536),
                base64_columns=self._base64_columns,
            )
        )
        reader = extractor.from_cursor(
            extraction_cursor,
            effective_staging_columns,
            source_columns=source_columns,
        )
        manifest = self.write(reader, local_output_path)
        return manifest.total_rows

    @staticmethod
    def _extract_field_primitives(schema_dict: dict[str, Any]) -> dict[str, str]:
        """Map each Avro field name in schema_dict to its non-null primitive type name."""
        primitives: dict[str, str] = {}
        for field in schema_dict.get("fields", []):
            name = field.get("name", "")
            ftype = field.get("type")
            if isinstance(ftype, list):
                non_null = [t for t in ftype if t != "null"]
                prim = non_null[0] if non_null else "string"
            else:
                prim = ftype
            if isinstance(prim, dict):
                prim = prim.get("type", "string")
            primitives[name] = str(prim).lower()
        return primitives

    def _normalize_record(self, record: dict[str, Any], b64_upper: set[str]) -> dict[str, Any]:
        """Coerce Arrow Python values (Decimal, base64 strings) to match the target Avro field primitives."""
        out: dict[str, Any] = {}
        for key, val in record.items():
            if val is None:
                out[key] = None
                continue
            if b64_upper and key.upper() in b64_upper and isinstance(val, (str, bytes)):
                val = base64.b64decode(val)
            prim = self._field_types.get(key)
            if prim == "string" and not isinstance(val, str):
                out[key] = val.decode("utf-8") if isinstance(val, bytes) else str(val)
            elif prim in ("int", "long") and isinstance(val, (Decimal, str)):
                out[key] = int(val)
            elif prim in ("float", "double") and isinstance(val, Decimal):
                out[key] = float(val)
            else:
                out[key] = val
        return out


def _normalize_base64_column_names(base64_columns: Sequence[Any] | None) -> frozenset[str]:
    """Normalize a sequence of column metadata objects or string names into a frozenset of column names."""
    if not base64_columns:
        return frozenset()
    return frozenset(getattr(col, "name", str(col)) for col in base64_columns if col is not None)


def _staging_parquet_columns_from_schema(schema_tuples: Sequence[Any]) -> tuple[ColumnSpec, ...]:
    """Construct ColumnSpec objects from (name, data_type, nullable) schema tuples."""
    cols: list[ColumnSpec] = []
    for item in schema_tuples:
        if isinstance(item, ColumnSpec):
            cols.append(item)
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            name = str(item[0])
            dtype = str(item[1])
            nullable = bool(item[2]) if len(item) >= 3 else True
            col = ColumnSpec(ColumnDialect.PARQUET, name, dtype, nullable=nullable, staging_file_column_name=name)
            cols.append(col)
    return tuple(cols)


def _staging_avro_columns_from_fields(field_types: dict[str, str]) -> tuple[ColumnSpec, ...]:
    """Construct ColumnSpec objects from extracted Avro field primitive types."""
    cols: list[ColumnSpec] = []
    for name, prim in field_types.items():
        col = ColumnSpec(ColumnDialect.AVRO, name, prim, nullable=True, staging_file_column_name=name)
        cols.append(col)
    return tuple(cols)

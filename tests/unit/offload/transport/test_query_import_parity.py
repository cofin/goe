# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Differential parity suite across all 19 Oracle type families for Query Import Parquet and Avro staging."""

import hashlib
import math
from pathlib import Path
from typing import Any

import avro.datafile
import avro.io
import pyarrow.parquet as pq

from goe.offload.schema.column_spec import (
    AVRO_TYPE_BYTES,
    AVRO_TYPE_DOUBLE,
    AVRO_TYPE_FLOAT,
    AVRO_TYPE_INT,
    AVRO_TYPE_LONG,
    AVRO_TYPE_STRING,
    ORACLE_TYPE_BINARY_DOUBLE,
    ORACLE_TYPE_BINARY_FLOAT,
    ORACLE_TYPE_BLOB,
    ORACLE_TYPE_CHAR,
    ORACLE_TYPE_CLOB,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_FLOAT,
    ORACLE_TYPE_INTERVAL_DS,
    ORACLE_TYPE_INTERVAL_YM,
    ORACLE_TYPE_NCHAR,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_NVARCHAR2,
    ORACLE_TYPE_RAW,
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
    ORACLE_TYPE_TIMESTAMP_TZ,
    ORACLE_TYPE_VARCHAR2,
    ORACLE_TYPE_XMLTYPE,
    PARQUET_TYPE_BINARY,
    PARQUET_TYPE_DOUBLE,
    PARQUET_TYPE_FLOAT,
    PARQUET_TYPE_INT32,
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
    ColumnDialect,
    ColumnSpec,
)
from goe.offload.staging.arrow_writers import (
    ArrowAvroStagingWriter,
    ArrowParquetStagingWriter,
)
from goe.offload.transport.arrow_extractor import (
    ArrowExtractionConfig,
    OracleArrowStreamExtractor,
)
from goe.offload.transport.duckdb import (
    DuckDBEngine,
    DuckDBSessionConfig,
    ParquetWriteOptions,
)
from goe.serializers import decode_json
from goe.util.module_loader import import_optional

GOLDEN_MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "query_import_parity" / "golden_manifest.json"


class _FakeLob:
    """Deterministic stand-in for an oracledb.LOB object with a callable read() method."""

    def __init__(self, payload: str | bytes) -> None:
        self._payload = payload

    def read(self) -> str | bytes:
        return self._payload


def test_parquet_staging_parity_matches_golden_manifest_across_all_19_oracle_types(tmp_path: Path) -> None:
    """ArrowParquetStagingWriter matches the committed golden manifest across all 19 Oracle type families."""
    golden = decode_json(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))
    actual = build_arrow_parity_manifest(tmp_path)
    assert actual["parquet_standard"] == golden["parquet_standard"]


def test_avro_staging_parity_matches_golden_manifest_across_all_19_oracle_types(tmp_path: Path) -> None:
    """ArrowAvroStagingWriter matches the committed golden manifest across all 19 Oracle type families."""
    golden = decode_json(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))
    actual = build_arrow_parity_manifest(tmp_path)
    assert actual["avro_standard"] == golden["avro_standard"]


def test_parquet_and_avro_empty_table_parity(tmp_path: Path) -> None:
    """0-row extraction produces schema-identical Parquet and Avro files matching golden_manifest.json."""
    golden = decode_json(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))
    actual = build_arrow_parity_manifest(tmp_path)
    assert actual["parquet_empty"] == golden["parquet_empty"]
    assert actual["avro_empty"] == golden["avro_empty"]
    assert actual["parquet_empty"]["row_count"] == 0
    assert actual["avro_empty"]["row_count"] == 0


def test_nan_and_inf_scrubbing_parity(tmp_path: Path) -> None:
    """nan_values_as_null=True and False match the golden manifest for NaN, +Inf, and -Inf."""
    golden = decode_json(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))
    actual = build_arrow_parity_manifest(tmp_path)
    assert actual["parquet_nan_as_null"] == golden["parquet_nan_as_null"]
    assert actual["parquet_nan_preserved"] == golden["parquet_nan_preserved"]
    assert actual["avro_nan_as_null"] == golden["avro_nan_as_null"]


def build_arrow_parity_manifest(work_dir: Path) -> dict[str, Any]:
    """Run the 19-type dataset through OracleArrowStreamExtractor and Arrow writers and return canonical metadata."""
    source_cols, parquet_cols, avro_cols, avro_schema = _build_19_type_columns_and_schemas()
    std_rows = _build_standard_rows()
    nan_rows_raw = _build_nan_rows(scrub_nans=False)

    engine = DuckDBEngine(
        DuckDBSessionConfig(
            execution_key=f"parity_{work_dir.name}",
            parallelism=1,
            threads_override=1,
            temp_directory=str(work_dir / "spill"),
        )
    )
    engine.open()
    try:
        extractor_std = OracleArrowStreamExtractor(ArrowExtractionConfig(batch_size=2, nan_values_as_null=False))
        pq_writer = ArrowParquetStagingWriter(
            engine,
            write_options=ParquetWriteOptions(compression="SNAPPY", per_thread_output=False),
        )
        avro_writer = ArrowAvroStagingWriter(
            avro_schema,
            compress=True,
        )

        pq_std_path = work_dir / "arrow_std.parquet"
        pq_writer.write(
            extractor_std.from_rows(std_rows, parquet_cols, source_columns=source_cols),
            parquet_cols,
            str(pq_std_path),
        )

        avro_std_path = work_dir / "arrow_std.avro"
        avro_writer.write(
            extractor_std.from_rows(std_rows, avro_cols, source_columns=source_cols),
            avro_std_path,
        )

        pq_empty_path = work_dir / "arrow_empty.parquet"
        pq_writer.write(
            extractor_std.from_rows([], parquet_cols, source_columns=source_cols),
            parquet_cols,
            str(pq_empty_path),
        )

        avro_empty_path = work_dir / "arrow_empty.avro"
        avro_writer.write(
            extractor_std.from_rows([], avro_cols, source_columns=source_cols),
            avro_empty_path,
        )

        extractor_nan_null = OracleArrowStreamExtractor(ArrowExtractionConfig(batch_size=2, nan_values_as_null=True))
        pq_nan_null_path = work_dir / "arrow_nan_null.parquet"
        pq_writer.write(
            extractor_nan_null.from_rows(nan_rows_raw, parquet_cols, source_columns=source_cols),
            parquet_cols,
            str(pq_nan_null_path),
        )

        avro_nan_null_path = work_dir / "arrow_nan_null.avro"
        avro_writer.write(
            extractor_nan_null.from_rows(nan_rows_raw, avro_cols, source_columns=source_cols),
            avro_nan_null_path,
        )

        pq_nan_keep_path = work_dir / "arrow_nan_keep.parquet"
        pq_writer.write(
            extractor_std.from_rows(nan_rows_raw, parquet_cols, source_columns=source_cols),
            parquet_cols,
            str(pq_nan_keep_path),
        )

        return {
            "parquet_standard": _inspect_parquet_file(pq_std_path),
            "avro_standard": _inspect_avro_file(avro_std_path, avro_schema),
            "parquet_empty": _inspect_parquet_file(pq_empty_path),
            "avro_empty": _inspect_avro_file(avro_empty_path, avro_schema),
            "parquet_nan_as_null": _inspect_parquet_file(pq_nan_null_path),
            "parquet_nan_preserved": _inspect_parquet_file(pq_nan_keep_path),
            "avro_nan_as_null": _inspect_avro_file(avro_nan_null_path, avro_schema),
        }
    finally:
        engine.close()


def _build_19_type_columns_and_schemas() -> tuple[list[ColumnSpec], list[ColumnSpec], list[ColumnSpec], dict[str, Any]]:
    """Construct the 19 Oracle type family definitions and their Parquet and Avro staging counterparts."""
    spec = [
        ("COL_NUM_4_0", ORACLE_TYPE_NUMBER, 4, 0, None, PARQUET_TYPE_INT32, AVRO_TYPE_INT, "int"),
        ("COL_NUM_9_0", ORACLE_TYPE_NUMBER, 9, 0, None, PARQUET_TYPE_INT32, AVRO_TYPE_INT, "int"),
        ("COL_NUM_18_0", ORACLE_TYPE_NUMBER, 18, 0, None, PARQUET_TYPE_INT64, AVRO_TYPE_LONG, "long"),
        ("COL_NUM_38_0", ORACLE_TYPE_NUMBER, 38, 0, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_NUM_38_9", ORACLE_TYPE_NUMBER, 38, 9, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_NUM_UNBOUNDED", ORACLE_TYPE_FLOAT, 126, None, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_BIN_FLOAT", ORACLE_TYPE_BINARY_FLOAT, None, None, None, PARQUET_TYPE_FLOAT, AVRO_TYPE_FLOAT, "float"),
        (
            "COL_BIN_DOUBLE",
            ORACLE_TYPE_BINARY_DOUBLE,
            None,
            None,
            None,
            PARQUET_TYPE_DOUBLE,
            AVRO_TYPE_DOUBLE,
            "double",
        ),
        ("COL_CHAR_10", ORACLE_TYPE_CHAR, None, None, 10, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_NCHAR_10", ORACLE_TYPE_NCHAR, None, None, 10, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_VARCHAR2", ORACLE_TYPE_VARCHAR2, None, None, 4000, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_NVARCHAR2", ORACLE_TYPE_NVARCHAR2, None, None, 2000, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_RAW", ORACLE_TYPE_RAW, None, None, 2000, PARQUET_TYPE_BINARY, AVRO_TYPE_BYTES, "bytes"),
        ("COL_CLOB", ORACLE_TYPE_CLOB, None, None, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_BLOB", ORACLE_TYPE_BLOB, None, None, None, PARQUET_TYPE_BINARY, AVRO_TYPE_BYTES, "bytes"),
        ("COL_DATE", ORACLE_TYPE_DATE, None, None, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_TS9", ORACLE_TYPE_TIMESTAMP, None, 9, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_TSTZ", ORACLE_TYPE_TIMESTAMP_TZ, None, 6, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_TSLTZ", ORACLE_TYPE_TIMESTAMP_LOCAL_TZ, None, 6, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_INT_YM", ORACLE_TYPE_INTERVAL_YM, 4, None, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_INT_DS", ORACLE_TYPE_INTERVAL_DS, 5, 6, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
        ("COL_XMLTYPE", ORACLE_TYPE_XMLTYPE, None, None, None, PARQUET_TYPE_STRING, AVRO_TYPE_STRING, "string"),
    ]
    source_cols: list[ColumnSpec] = []
    parquet_cols: list[ColumnSpec] = []
    avro_cols: list[ColumnSpec] = []
    avro_fields: list[dict[str, Any]] = []

    for name, ora_type, prec, scale, length, pq_type, av_type, av_prim in spec:
        source_cols.append(
            ColumnSpec(
                ColumnDialect.ORACLE,
                name,
                ora_type,
                data_length=length,
                data_precision=prec,
                data_scale=scale,
                nullable=True,
            )
        )
        pq_col = ColumnSpec(ColumnDialect.PARQUET, name, pq_type, nullable=True, staging_file_column_name=name)
        parquet_cols.append(pq_col)

        av_col = ColumnSpec(ColumnDialect.AVRO, name, av_type, nullable=True, staging_file_column_name=name)
        avro_cols.append(av_col)

        avro_fields.append({"name": name, "type": ["null", av_prim]})

    avro_schema = {
        "type": "record",
        "name": "parity_19_types",
        "namespace": "goe.parity",
        "fields": avro_fields,
    }
    return source_cols, parquet_cols, avro_cols, avro_schema


def _build_standard_rows() -> list[tuple[Any, ...]]:
    """Build deterministic boundary, multibyte/large >64 KiB LOB, and all-NULL rows across all 19 type families."""
    raw_bytes_1 = b"\x01\x02\x03\xfe\xff"
    raw_bytes_2 = b"boundary-raw-payload"
    large_clob_str = ("Üñîçødé-日本-🚀-" * 8192)[:98304]
    large_blob_bytes = (b"\xde\xad\xbe\xef\x00\xff" * 16384)[:98304]

    row_boundary = (
        9999,
        999999999,
        999999999999999999,
        "99999999999999999999999999999999999999",
        "12345678901234567890123456789.123456789",
        "3.1415926535897932384626433832795028841971",
        1.5,
        -2.25,
        "FIXED10   ",
        "NFIXED10  ",
        "Hello UTF-8 漢字 🌍",
        "National UTF-8 문자열",
        raw_bytes_1,
        _FakeLob("Small CLOB payload < 64 KiB"),
        _FakeLob(b"\x10\x20\x30\x40"),
        "1999-12-31 23:59:59",
        "2026-10-24 14:25:36.123456789",
        "2026-10-24 14:25:36.123456 +02:00",
        "2026-10-24 14:25:36.123456",
        "+0123-06",
        "+00045 12:34:56.654321",
        "<root><item id='1'>value</item></root>",
    )
    row_large_lob = (
        -9999,
        -999999999,
        -999999999999999999,
        "-99999999999999999999999999999999999999",
        "-12345678901234567890123456789.987654321",
        "-0.00000000000000000000000000000000000001",
        -0.0,
        -0.0,
        "A         ",
        "B         ",
        "Second row",
        "Second national",
        raw_bytes_2,
        _FakeLob(large_clob_str),
        _FakeLob(large_blob_bytes),
        "0001-01-01 00:00:00",
        "1970-01-01 00:00:00.000000001",
        "1970-01-01 00:00:00.000000 -08:00",
        "1970-01-01 00:00:00.123456",
        "-0005-11",
        "-00001 00:00:00.000001",
        "<doc/>",
    )
    row_all_null = tuple(None for _ in range(len(row_boundary)))
    return [row_boundary, row_large_lob, row_all_null]


def _build_nan_rows(*, scrub_nans: bool) -> list[tuple[Any, ...]]:
    """Build rows exercising NaN, +Inf, and -Inf on BINARY_FLOAT and BINARY_DOUBLE."""
    base = list(_build_standard_rows()[0])
    rows: list[tuple[Any, ...]] = []
    for special in (math.nan, math.inf, -math.inf):
        r = list(base)
        r[13] = _FakeLob("Small CLOB payload < 64 KiB")
        r[14] = _FakeLob(b"\x10\x20\x30\x40")
        r[21] = "<root><item id='1'>value</item></root>"
        r[6] = None if scrub_nans else special
        r[7] = None if scrub_nans else special
        rows.append(tuple(r))
    return rows


def _canonicalize_value(val: Any) -> Any:
    """Convert a Python cell value from Parquet or Avro into a deterministic JSON-serializable representation."""
    if val is None:
        return None
    if isinstance(val, float):
        if math.isnan(val):
            return "__NAN__"
        if math.isinf(val):
            return "__POS_INF__" if val > 0 else "__NEG_INF__"
        if val == 0.0:
            return "-0.0" if math.copysign(1.0, val) < 0 else 0.0
        return round(val, 6)
    if isinstance(val, bytes):
        if len(val) > 256:
            return {
                "__large_bytes__": True,
                "len": len(val),
                "sha256": hashlib.sha256(val).hexdigest(),
            }
        return {"__bytes_hex__": val.hex()}
    if isinstance(val, str) and len(val) > 256:
        return {
            "__large_str__": True,
            "len": len(val),
            "sha256": hashlib.sha256(val.encode("utf-8")).hexdigest(),
        }
    return val


def _inspect_parquet_file(path: Path) -> dict[str, Any]:
    """Read a Parquet file with PyArrow and return its canonical schema, row count, and row representations."""
    table = pq.read_table(path)
    meta = pq.read_metadata(path)
    compression = meta.row_group(0).column(0).compression if meta.num_row_groups > 0 else "SNAPPY"
    schema_fields = [
        {"name": field.name, "type": str(field.type), "nullable": bool(field.nullable)} for field in table.schema
    ]
    rows = [{k: _canonicalize_value(v) for k, v in record.items()} for record in table.to_pylist()]
    return {
        "schema": schema_fields,
        "compression": compression,
        "row_count": table.num_rows,
        "rows": rows,
    }


def _inspect_avro_file(path: Path, expected_schema: dict[str, Any]) -> dict[str, Any]:
    """Read an Avro file and return its canonical schema fields, codec, row count, and row representations."""
    fastavro = import_optional("fastavro")
    if fastavro is not None:
        with path.open("rb") as fh:
            reader = fastavro.reader(fh)
            codec = str(getattr(reader, "codec", "deflate")).lower()
            raw_rows = list(reader)
    else:
        with path.open("rb") as fh:
            with avro.datafile.DataFileReader(fh, avro.io.DatumReader()) as reader:
                raw_codec = reader.get_meta("avro.codec")
                codec = raw_codec.decode("utf-8") if isinstance(raw_codec, bytes) else str(raw_codec)
                raw_rows = list(reader)
    rows = [{k: _canonicalize_value(v) for k, v in record.items()} for record in raw_rows]
    return {
        "fields": expected_schema["fields"],
        "codec": codec,
        "row_count": len(rows),
        "rows": rows,
    }

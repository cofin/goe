# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for OffloadTransportQueryImport over Arrow streaming and DuckDB/fastavro writers."""

import importlib.util
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import avro.datafile
import avro.io
import pyarrow.parquet as pq
import pytest

from goe.offload.offload_constants import (
    DBTYPE_BIGQUERY,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.oracle.oracle_column import ORACLE_TYPE_NUMBER, ORACLE_TYPE_VARCHAR2, OracleColumn
from goe.offload.staging.avro.avro_column import AVRO_TYPE_LONG, AVRO_TYPE_STRING, StagingAvroColumn
from goe.offload.staging.parquet.parquet_column import (
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
    StagingParquetColumn,
)
from goe.offload.transport.arrow_extractor import OracleArrowStreamExtractor
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    TRANSPORT_CXT_BYTES,
    TRANSPORT_CXT_ROWS,
)
from goe.offload.transport.query_import import OffloadTransportQueryImport
from goe.serializers import encode_json
from goe.util.module_loader import import_optional


def test_query_import_transport_streams_parquet_via_arrow_and_duckdb(tmp_path: Path) -> None:
    """OffloadTransportQueryImport.transport() extracts via arrow_batch_extraction and writes Parquet via DuckDB."""
    source_cols = [
        OracleColumn("ID", ORACLE_TYPE_NUMBER, data_precision=10, data_scale=0, nullable=True),
        OracleColumn("LABEL", ORACLE_TYPE_VARCHAR2, data_length=50, nullable=True),
    ]
    staging_cols = [
        StagingParquetColumn("ID", PARQUET_TYPE_INT64, nullable=True),
        StagingParquetColumn("LABEL", PARQUET_TYPE_STRING, nullable=True),
    ]
    for col in staging_cols:
        col.staging_file_column_name = col.name

    rows = [(1, "alpha"), (2, "beta"), (3, "gamma")]
    transport, captured_dfs_files, captured_queries = _build_transport_double(
        tmp_path=tmp_path,
        file_format=FILE_STORAGE_FORMAT_PARQUET,
        source_cols=source_cols,
        staging_cols=staging_cols,
        rows=rows,
    )

    transported_rows = transport.transport()

    assert transported_rows == 3
    assert transport.get_transport_bytes() == 1024
    assert transport._transport_context[TRANSPORT_CXT_ROWS] == 3
    assert transport._transport_context[TRANSPORT_CXT_BYTES] == 1024
    transport._target_table.post_transport_tasks.assert_called_once_with(transport._staging_file)
    assert len(captured_queries) == 1
    assert len(captured_dfs_files) == 1

    table = pq.read_table(captured_dfs_files[0])
    assert table.num_rows == 3
    assert table.to_pylist() == [
        {"ID": 1, "LABEL": "alpha"},
        {"ID": 2, "LABEL": "beta"},
        {"ID": 3, "LABEL": "gamma"},
    ]


def test_query_import_transport_streams_avro_via_arrow_and_fastavro(tmp_path: Path) -> None:
    """OffloadTransportQueryImport.transport() writes Avro via ArrowAvroStagingWriter when AVRO is configured."""
    source_cols = [
        OracleColumn("ID", ORACLE_TYPE_NUMBER, data_precision=10, data_scale=0, nullable=True),
        OracleColumn("LABEL", ORACLE_TYPE_VARCHAR2, data_length=50, nullable=True),
    ]
    staging_cols = [
        StagingAvroColumn("ID", AVRO_TYPE_LONG, nullable=True),
        StagingAvroColumn("LABEL", AVRO_TYPE_STRING, nullable=True),
    ]
    for col in staging_cols:
        col.staging_file_column_name = col.name

    avro_schema = {
        "type": "record",
        "name": "qi_avro_test",
        "fields": [
            {"name": "ID", "type": ["null", "long"]},
            {"name": "LABEL", "type": ["null", "string"]},
        ],
    }
    rows = [(10, "first"), (20, "second")]
    transport, captured_dfs_files, _queries = _build_transport_double(
        tmp_path=tmp_path,
        file_format=FILE_STORAGE_FORMAT_AVRO,
        source_cols=source_cols,
        staging_cols=staging_cols,
        rows=rows,
        avro_schema=avro_schema,
    )

    transported_rows = transport.transport()

    assert transported_rows == 2
    assert transport._transport_context[TRANSPORT_CXT_ROWS] == 2
    assert transport._transport_context[TRANSPORT_CXT_BYTES] == 1024
    transport._target_table.post_transport_tasks.assert_called_once_with(transport._staging_file)
    assert len(captured_dfs_files) == 1

    fastavro = import_optional("fastavro")
    if fastavro is not None:
        with captured_dfs_files[0].open("rb") as fh:
            records = list(fastavro.reader(fh))
    else:
        with captured_dfs_files[0].open("rb") as fh:
            with avro.datafile.DataFileReader(fh, avro.io.DatumReader()) as reader:
                records = list(reader)
    assert records == [
        {"ID": 10, "LABEL": "first"},
        {"ID": 20, "LABEL": "second"},
    ]


def test_query_import_transport_honors_parallelism_and_consistent_read_scn(tmp_path: Path) -> None:
    """OffloadTransportQueryImport preserves parallelism and pins extraction SQL to AS OF SCN without warning."""
    source_cols = [OracleColumn("ID", ORACLE_TYPE_NUMBER, data_precision=10, data_scale=0, nullable=True)]
    staging_cols = [StagingParquetColumn("ID", PARQUET_TYPE_INT64, nullable=True)]
    staging_cols[0].staging_file_column_name = "ID"

    transport, _files, captured_queries = _build_transport_double(
        tmp_path=tmp_path,
        file_format=FILE_STORAGE_FORMAT_PARQUET,
        source_cols=source_cols,
        staging_cols=staging_cols,
        rows=[(1,)],
        parallelism=4,
        consistent_read=True,
        snapshot_scn=987654321,
    )

    assert transport._offload_transport_parallelism == 4
    transport.transport()

    assert len(captured_queries) == 1
    assert "AS OF SCN 987654321" in captured_queries[0]
    logged_messages = [str(call.args[0]) for call in transport._messages.log.call_args_list if call.args]
    assert not any("Ignoring --offload-transport-consistent-read" in msg for msg in logged_messages)

    transport._rdbms_api.get_snapshot_clause.side_effect = None
    transport._rdbms_api.get_snapshot_clause.return_value = ""
    with pytest.raises(ValueError, match="AS OF SCN 987654321"):
        transport._build_source_query()


def test_legacy_row_by_row_encoders_are_deleted() -> None:
    """Legacy row-by-row Parquet/Avro encoders and QueryImportInterface are deleted from the repository."""
    removed_modules = (
        "goe.util.parquet_encoder",
        "goe.util.avro_encoder",
        "goe.offload.staging.parquet.parquet_encoder",
        "goe.offload.staging.avro.avro_encoder",
        "goe.offload.query_import_interface",
        "goe.offload.factory.query_import_factory",
    )
    for mod_name in removed_modules:
        try:
            spec = importlib.util.find_spec(mod_name)
        except ModuleNotFoundError:
            spec = None
        assert spec is None, f"Module {mod_name} should be deleted"

    repo_root = Path(__file__).resolve().parents[4]
    forbidden_tokens = ("parquet_encoder", "avro_encoder", "query_import_interface", "query_import_factory")
    for py_file in sorted((repo_root / "src" / "goe").rglob("*.py")):
        source_text = py_file.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source_text, f"Found forbidden reference {token!r} in {py_file}"


def _build_transport_double(
    *,
    tmp_path: Path,
    file_format: str,
    source_cols: list[OracleColumn],
    staging_cols: list[Any],
    rows: list[tuple[Any, ...]],
    avro_schema: dict[str, Any] | None = None,
    parallelism: int = 2,
    consistent_read: bool = False,
    snapshot_scn: int | None = None,
) -> tuple[OffloadTransportQueryImport, list[Path], list[str]]:
    """Construct an isolated OffloadTransportQueryImport instance wired with an in-memory Arrow extraction double."""
    transport = object.__new__(OffloadTransportQueryImport)
    transport._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT
    transport._target = DBTYPE_BIGQUERY
    transport._dry_run = False
    transport._offload_transport_parallelism = parallelism
    transport._offload_transport_fetch_size = 1000
    transport._convert_nans_to_nulls = False
    transport._compress_load_table = True
    transport._staging_format = file_format
    transport._target_owner = "tgt_owner"
    transport._target_table_name = "tgt_tbl"
    transport._rdbms_owner = "src_owner"
    transport._rdbms_table_name = "src_tbl"
    transport._staging_table_location = str(tmp_path / "dfs")
    transport._offload_transport_consistent_read = consistent_read
    transport._offload_transport_snapshot = snapshot_scn
    transport._rdbms_offload_predicate = None
    transport._column_transformations = {}
    transport._rdbms_columns = source_cols
    transport._canonical_columns = []
    transport._rdbms_action = "goe_qi_test"
    transport._rdbms_module = "goe"
    transport._offload_transport_rdbms_session_parameters = {}
    transport._transport_context = {}

    options = MagicMock()
    options.local_staging_path = str(tmp_path)
    transport._offload_options = options

    messages = MagicMock()
    messages.offload_step.side_effect = lambda _step, fn, execute=True: fn() if execute else None
    transport._messages = messages

    rdbms_table = MagicMock()
    rdbms_table.enclose_identifier.side_effect = lambda name: f'"{name}"'
    rdbms_table.max_datetime_scale.return_value = 6
    transport._rdbms_table = rdbms_table

    target_table = MagicMock()
    target_table.transport_binary_data_in_base64.return_value = False
    target_table.max_datetime_scale.return_value = 6
    target_table.backend_type.return_value = DBTYPE_BIGQUERY
    transport._target_table = target_table

    staging_file = MagicMock()
    staging_file.file_format = file_format
    staging_file.get_staging_columns.return_value = staging_cols
    if avro_schema is not None:
        staging_file.get_file_schema_json.return_value = encode_json(avro_schema)
    else:
        staging_file.get_file_schema_json.return_value = [(col.name, col.data_type, True) for col in staging_cols]
    transport._staging_file = staging_file

    captured_queries: list[str] = []
    extractor = OracleArrowStreamExtractor()

    @contextmanager
    def _fake_arrow_batch_extraction(
        stg_cols: Any,
        source_query: str,
        _source_binds: Any,
        _fetch_size: int,
        _compress: bool,
        _session_cmds: Any,
        **_kwargs: Any,
    ):
        captured_queries.append(source_query)
        yield extractor.from_rows(rows, stg_cols, source_columns=source_cols)

    rdbms_api = MagicMock()
    rdbms_api.convert_query_import_expressions_on_rdbms_side.return_value = True
    rdbms_api.get_rdbms_query_cast.side_effect = lambda expr, *_args, **_kwargs: expr
    rdbms_api.get_snapshot_clause.side_effect = lambda scn, cr: f" AS OF SCN {scn}" if cr and scn is not None else ""
    rdbms_api.generate_transport_action.return_value = "goe_qi_action"
    rdbms_api.get_rdbms_session_setup_commands.return_value = []
    rdbms_api.arrow_batch_extraction = _fake_arrow_batch_extraction
    transport._rdbms_api = rdbms_api

    captured_dfs_files: list[Path] = []
    dfs_dir = tmp_path / "dfs_captured"
    dfs_dir.mkdir(parents=True, exist_ok=True)

    def _capture_copy(local_path: str, _dfs_path: str, overwrite: bool = False) -> None:
        del overwrite
        dest = dfs_dir / Path(local_path).name
        shutil.copy2(local_path, dest)
        captured_dfs_files.append(dest)

    dfs_client = MagicMock()
    dfs_client.copy_from_local.side_effect = _capture_copy
    transport._dfs_client = dfs_client
    transport._check_and_log_transported_files = MagicMock(return_value=1024)
    transport.log_dfs_cmd = MagicMock()

    return transport, captured_dfs_files, captured_queries

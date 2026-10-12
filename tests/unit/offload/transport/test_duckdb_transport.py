# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OffloadTransportDuckDB batch planning and execution behavior."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from goe.offload.offload_transport_rdbms_api import (
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION,
)
from goe.offload.staging.parquet.parquet_column import PARQUET_TYPE_INT64, PARQUET_TYPE_STRING, StagingParquetColumn
from goe.offload.transport.base import OffloadTransportException
from goe.offload.transport.constants import TRANSPORT_CXT_BYTES, TRANSPORT_CXT_ROWS
from goe.offload.transport.duckdb_engine import DuckDBTransportSettings
from goe.offload.transport.duckdb_transport import OffloadTransportDuckDB

MODULE = "goe.offload.transport.duckdb_transport"
SCN = 555666777
PASSWORD = "SuperSecretPass123!"


@pytest.mark.parametrize(
    "split_type",
    [
        TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
        TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION,
        TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
        TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD,
        TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE,
    ],
)
def test_batch_queries_cover_every_batch_and_keep_scn(tmp_path: Path, split_type: str) -> None:
    """Every split type yields one SCN-pinned query per batch filtered on goe_offload_batch."""
    transport = _transport(tmp_path, split_type)
    queries = transport._batch_oracle_queries(None)
    assert len(queries) == 2
    for batch, query in enumerate(queries):
        assert f"AS OF SCN {SCN}" in query
        assert query.endswith(f'WHERE "SALES".goe_offload_batch = {batch}')
        assert query.startswith("SELECT /*+ NO_PARALLEL */ /* Offload_SALES */")
    if split_type == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE:
        assert transport._get_transport_row_source_query.call_args.kwargs == {"id_col_min": 1, "id_col_max": 1000}


def test_empty_id_range_falls_back_to_mod(tmp_path: Path) -> None:
    """A blank id range switches the split to MOD like the Spark transports."""
    transport = _transport(tmp_path, TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE)
    transport._rdbms_api.get_id_range.return_value = (None, None)
    transport._batch_oracle_queries(None)
    assert transport._get_transport_row_source_query.call_args.args[0] == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD


def test_missing_scn_fails_before_any_connection(tmp_path: Path) -> None:
    """A row source without AS OF SCN raises before DuckDB or credentials are touched."""
    transport = _transport(tmp_path)
    transport._get_transport_row_source_query.return_value = 'SELECT "ID" FROM "SH"."SALES"'
    with patch(f"{MODULE}.open_batch_connection") as open_conn, pytest.raises(ValueError, match="AS OF SCN"):
        transport.transport()
    open_conn.assert_not_called()


def test_dry_run_logs_and_runs_post_transport_without_duckdb(tmp_path: Path) -> None:
    """Dry-run logs extraction SQL, opens no connection and still runs post-transport tasks."""
    transport = _transport(tmp_path, dry_run=True)
    with patch(f"{MODULE}.open_batch_connection") as open_conn, patch(f"{MODULE}.resolve_gcp_credentials") as creds:
        assert transport.transport() is None
    open_conn.assert_not_called()
    creds.assert_not_called()
    transport._target_table.post_transport_tasks.assert_called_once_with(transport._staging_file)
    logged = " ".join(str(c.args[0]) for c in transport._messages.log.call_args_list)
    assert "gcss://bucket/goe/sales_load/orders/part-00000.parquet" in logged


def test_execute_streams_batches_to_gcss_and_cleans_up(tmp_path: Path) -> None:
    """Execute mode runs one COPY per batch, sums rows, sets context, redacts secrets and removes spill dirs."""
    transport = _transport(tmp_path)
    connections: list[MagicMock] = []

    def fake_connection(_settings: object, _temp_directory: str) -> MagicMock:
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (125,)
        connections.append(conn)
        return conn

    bundle = MagicMock(project="my-project")
    bundle.credentials.token = "test-access-token"
    with (
        patch(f"{MODULE}.open_batch_connection", side_effect=fake_connection),
        patch(f"{MODULE}.load_oracle_extension"),
        patch(f"{MODULE}.load_gcs_extension"),
        patch(f"{MODULE}.attach_oracle") as attach,
        patch(f"{MODULE}.create_gcs_token_secret") as gcs_secret,
        patch(f"{MODULE}.resolve_gcp_credentials", return_value=bundle),
    ):
        assert transport.transport() == 250
    assert os.environ["ORA_SDTZ"] == "UTC"
    copies = sorted(
        c.args[0] for conn in connections for c in conn.execute.call_args_list if c.args[0].startswith("COPY")
    )
    assert "TO 'gcss://bucket/goe/sales_load/orders/part-00000.parquet'" in copies[0]
    assert "TO 'gcss://bucket/goe/sales_load/orders/part-00001.parquet'" in copies[1]
    assert attach.call_args.args[1:3] == ("goe_app", PASSWORD)
    gcs_secret.assert_called_with(gcs_secret.call_args.args[0], "test-access-token", "my-project")
    assert transport._transport_context == {TRANSPORT_CXT_ROWS: 250, TRANSPORT_CXT_BYTES: 4096}
    logged = " ".join(str(c.args[0]) for c in transport._messages.log.call_args_list)
    assert PASSWORD not in logged and "test-access-token" not in logged
    assert all(conn.close.called for conn in connections)
    assert list(Path(transport._duckdb_temp_root).iterdir()) == []


def test_batch_failure_raises_transport_exception_and_cleans_up(tmp_path: Path) -> None:
    """A DuckDB error in any batch surfaces as OffloadTransportException and spill dirs are removed."""
    transport = _transport(tmp_path)
    conn = MagicMock()
    conn.execute.side_effect = duckdb.IOException("ORA-01555: snapshot too old")
    bundle = MagicMock(project=None)
    bundle.credentials.token = "t"
    with (
        patch(f"{MODULE}.open_batch_connection", return_value=conn),
        patch(f"{MODULE}.load_oracle_extension"),
        patch(f"{MODULE}.load_gcs_extension"),
        patch(f"{MODULE}.attach_oracle"),
        patch(f"{MODULE}.create_gcs_token_secret"),
        patch(f"{MODULE}.resolve_gcp_credentials", return_value=bundle),
        pytest.raises(OffloadTransportException, match="ORA-01555"),
    ):
        transport.transport()
    assert list(Path(transport._duckdb_temp_root).iterdir()) == []


def _staging_columns() -> list[StagingParquetColumn]:
    """Return staged ID/NAME columns with staging file names assigned."""
    columns = [StagingParquetColumn("ID", PARQUET_TYPE_INT64), StagingParquetColumn("NAME", PARQUET_TYPE_STRING)]
    for position, column in enumerate(columns):
        column.set_simplified_staging_column_name(position)
    return columns


def _transport(tmp_path: Path, split_type: str = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD, dry_run: bool = False):
    """Build an OffloadTransportDuckDB with collaborators replaced by mocks."""
    transport = object.__new__(OffloadTransportDuckDB)
    transport._dry_run = dry_run
    transport._offload_transport_parallelism = 2
    transport._offload_transport_consistent_read = True
    transport._offload_transport_snapshot = SCN
    transport._offload_transport_rdbms_session_parameters = {}
    transport._offload_transport_dsn = "dbhost:1521/FREEPDB1"
    transport._offload_options = MagicMock(rdbms_app_user="goe_app", rdbms_app_pass=PASSWORD)
    transport._compress_load_table = True
    transport._staging_table_location = "gs://bucket/goe/sales_load/orders"
    transport._staging_file = MagicMock()
    transport._staging_file.get_staging_columns.return_value = _staging_columns()
    transport._rdbms_table_name = "SALES"
    transport._rdbms_table = MagicMock()
    transport._rdbms_table.enclose_identifier.return_value = '"SALES"'
    transport._rdbms_table.predicate_to_where_clause.return_value = None
    transport._rdbms_offload_predicate = None
    transport._rdbms_action = "Offload_SALES"
    transport._rdbms_api = MagicMock()
    transport._rdbms_api.generate_transport_action.return_value = "Offload_SALES"
    transport._rdbms_api.get_rdbms_session_setup_hint.return_value = "/*+ NO_PARALLEL */"
    transport._rdbms_api.get_id_range.return_value = (1, 1000)
    transport._get_max_ts_scale = MagicMock(return_value=6)
    transport._get_transport_split_type = MagicMock(return_value=split_type)
    transport._build_offload_query_lists = MagicMock(return_value=(['"ID"', 'TO_CHAR("NAME")'], ["ID", "NAME"]))
    transport._get_transport_row_source_query = MagicMock(
        return_value=f'SELECT "ID", "NAME", MOD(ORA_HASH("ID"), 2) AS goe_offload_batch FROM "SH"."SALES" AS OF SCN {SCN}'
    )
    transport._check_and_log_transported_files = MagicMock(return_value=4096)
    transport._target_table = MagicMock()
    transport._messages = MagicMock()
    transport._messages.offload_step.side_effect = lambda _step, fn, execute=True: fn()
    transport._duckdb_settings = DuckDBTransportSettings(threads=2, memory_limit="1GB", extension_repository="r")
    transport._duckdb_temp_root = str(tmp_path / "duckdb")
    return transport

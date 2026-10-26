# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for OracleExtensionTransport pushdown and Arrow fallback routing."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from goe.offload.schema.column_spec import (
    ORACLE_TYPE_BFILE,
    ORACLE_TYPE_BLOB,
    ORACLE_TYPE_CLOB,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_INTERVAL_DS,
    ORACLE_TYPE_INTERVAL_YM,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_RAW,
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
    ORACLE_TYPE_TIMESTAMP_TZ,
    ORACLE_TYPE_VARCHAR2,
    ORACLE_TYPE_XMLTYPE,
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
    ColumnDialect,
    ColumnSpec,
)
from goe.offload.transport.duckdb import (
    DuckDBEngine,
    DuckDBSessionConfig,
    OracleExtensionTransport,
    OraclePushdownPlan,
)
from goe.offload.transport.duckdb_transport import OffloadTransportDuckDB


@pytest.mark.parametrize(
    ("data_type", "precision", "scale", "expected_fallback"),
    [
        (ORACLE_TYPE_VARCHAR2, None, None, False),
        (ORACLE_TYPE_DATE, None, None, False),
        (ORACLE_TYPE_TIMESTAMP, None, 6, False),
        (ORACLE_TYPE_RAW, None, None, False),
        (ORACLE_TYPE_NUMBER, 10, 0, False),
        (ORACLE_TYPE_NUMBER, 18, 4, False),
        (ORACLE_TYPE_NUMBER, 19, 0, True),
        (ORACLE_TYPE_NUMBER, 38, 10, True),
        (ORACLE_TYPE_NUMBER, None, None, True),
        (ORACLE_TYPE_INTERVAL_YM, None, None, True),
        (ORACLE_TYPE_INTERVAL_DS, None, None, True),
        (ORACLE_TYPE_TIMESTAMP_TZ, None, 6, True),
        (ORACLE_TYPE_TIMESTAMP_LOCAL_TZ, None, 6, True),
        (ORACLE_TYPE_BFILE, None, None, True),
        (ORACLE_TYPE_XMLTYPE, None, None, True),
        ("SDO_GEOMETRY", None, None, True),
        (ORACLE_TYPE_CLOB, None, None, True),
        (ORACLE_TYPE_BLOB, None, None, True),
        ("JSON", None, None, True),
        ("VECTOR", None, None, True),
    ],
)
def test_assess_oracle_extension_eligibility_routes_unsupported_types_to_arrow(
    data_type: str,
    precision: int | None,
    scale: int | None,
    expected_fallback: bool,
) -> None:
    """assess_table_eligibility routes unsupported Oracle types and >18-digit NUMBER to Arrow."""
    col = SimpleNamespace(name="COL1", data_type=data_type, data_precision=precision, data_scale=scale)
    assessment = OracleExtensionTransport.assess_table_eligibility([col], has_oci_library=True)
    assert assessment.requires_arrow_fallback is expected_fallback
    if expected_fallback:
        assert assessment.reasons
        assert "COL1" in assessment.reasons[0]

    no_oci = OracleExtensionTransport.assess_table_eligibility(
        [SimpleNamespace(name="ID", data_type=ORACLE_TYPE_NUMBER, data_precision=10, data_scale=0)],
        has_oci_library=False,
    )
    assert no_oci.requires_arrow_fallback is True
    assert "libclntsh" in no_oci.reasons[0]


def test_oracle_extension_transport_clears_cache_and_verifies_scn_invariant() -> None:
    """prepare_session executes SELECT oracle_clear_cache() and build_oracle_query_relation_sql enforces SCN."""
    engine = DuckDBEngine(DuckDBSessionConfig(execution_key="push01"))
    transport = OracleExtensionTransport(engine)
    conn = MagicMock()

    transport.prepare_session(
        conn,
        user="goe_app",
        password="secret",
        dsn="dbhost:1521/FREEPDB1",
    )
    executed = [c.args[0] for c in conn.execute.call_args_list]
    assert "SELECT oracle_clear_cache();" in executed

    valid_plan = OraclePushdownPlan(
        batch_queries=('SELECT "ID" FROM "SH"."SALES" AS OF SCN 9001 WHERE goe_offload_batch = 0',),
        cast_projection='CAST("ID" AS BIGINT) AS "ID"',
        consistent_read=True,
        snapshot_scn=9001,
    )
    rel_sql = transport.build_oracle_query_relation_sql(valid_plan, 0)
    assert 'FROM oracle_query(\'goe_ora\', \'SELECT "ID" FROM "SH"."SALES" AS OF SCN 9001' in rel_sql

    invalid_plan = OraclePushdownPlan(
        batch_queries=('SELECT "ID" FROM "SH"."SALES" WHERE goe_offload_batch = 0',),
        cast_projection='CAST("ID" AS BIGINT) AS "ID"',
        consistent_read=True,
        snapshot_scn=9001,
    )
    with pytest.raises(ValueError, match="AS OF SCN 9001"):
        transport.build_oracle_query_relation_sql(invalid_plan, 0)


def test_oracle_extension_transport_shares_single_duckdb_engine_across_parallel_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OffloadTransportDuckDB opens a single DuckDBEngine, spawns worker cursors, and never mutates ORA_SDTZ."""
    monkeypatch.delenv("ORA_SDTZ", raising=False)
    transport = object.__new__(OffloadTransportDuckDB)
    transport._dry_run = False
    transport._offload_transport_method = "DUCKDB"
    transport._offload_transport_parallelism = 3
    transport._offload_transport_consistent_read = True
    transport._offload_transport_snapshot = 777888
    transport._offload_transport_rdbms_session_parameters = {}
    transport._offload_transport_dsn = "dbhost:1521/FREEPDB1"
    transport._offload_options = MagicMock(
        rdbms_app_user="goe_app",
        rdbms_app_pass="pass",
        oracle_wallet_location=None,
    )
    transport._compress_load_table = True
    transport._staging_table_location = "gs://bucket/goe/sales_load/orders"
    transport._staging_file = MagicMock()
    cols = [
        ColumnSpec(ColumnDialect.PARQUET, "ID", PARQUET_TYPE_INT64),
        ColumnSpec(ColumnDialect.PARQUET, "NAME", PARQUET_TYPE_STRING),
    ]
    cols = [col.with_simplified_staging_column_name(idx) for idx, col in enumerate(cols)]
    transport._staging_file.get_staging_columns.return_value = cols
    transport._rdbms_columns = [
        SimpleNamespace(name="ID", data_type=ORACLE_TYPE_NUMBER, data_precision=10, data_scale=0),
        SimpleNamespace(name="NAME", data_type=ORACLE_TYPE_VARCHAR2, data_precision=None, data_scale=None),
    ]
    transport._has_oci_library = True
    transport._rdbms_table_name = "SALES"
    transport._rdbms_table = MagicMock()
    transport._rdbms_table.enclose_identifier.return_value = '"SALES"'
    transport._rdbms_table.predicate_to_where_clause.return_value = None
    transport._rdbms_offload_predicate = None
    transport._rdbms_action = "Offload_SALES"
    transport._rdbms_api = MagicMock()
    transport._rdbms_api.generate_transport_action.return_value = "Offload_SALES"
    transport._rdbms_api.get_rdbms_session_setup_hint.return_value = "/*+ NO_PARALLEL */"
    transport._get_max_ts_scale = MagicMock(return_value=6)
    transport._get_transport_split_type = MagicMock(return_value="MOD")
    transport._build_offload_query_lists = MagicMock(return_value=(['"ID"', '"NAME"'], ["ID", "NAME"]))
    transport._get_transport_row_source_query = MagicMock(
        return_value='SELECT "ID", "NAME", MOD(ORA_HASH("ID"), 3) AS goe_offload_batch FROM "SH"."SALES" AS OF SCN 777888'
    )
    transport._check_and_log_transported_files = MagicMock(return_value=1024)
    transport._target_table = MagicMock()
    transport._messages = MagicMock()
    transport._messages.offload_step.side_effect = lambda _step, fn, execute=True: fn()
    transport._duckdb_temp_root = str(tmp_path / "duckdb")
    transport._session_config = DuckDBSessionConfig(
        execution_key="shared01",
        parallelism=3,
        temp_directory=transport._duckdb_temp_root,
    )

    opened_engines: list[MagicMock] = []
    created_cursors: list[MagicMock] = []

    def fake_open_shared_engine(run_dir: Path, access_token: str) -> MagicMock:
        del run_dir, access_token
        eng = MagicMock()

        def cursor_ctx():
            cur = MagicMock()
            cur.execute.return_value.fetchone.return_value = (50,)
            created_cursors.append(cur)
            cm = MagicMock()
            cm.__enter__.return_value = cur
            cm.__exit__.return_value = False
            return cm

        eng.cursor.side_effect = cursor_ctx
        opened_engines.append(eng)
        return eng

    bundle = MagicMock(project="my-project")
    bundle.credentials.token = "token-xyz"
    with (
        patch.object(transport, "_open_shared_engine", side_effect=fake_open_shared_engine),
        patch("goe.offload.transport.duckdb_transport.resolve_gcp_credentials", return_value=bundle),
    ):
        assert transport.transport() == 150

    assert len(opened_engines) == 1
    assert len(created_cursors) == 3
    opened_engines[0].close.assert_called_once()
    assert "ORA_SDTZ" not in os.environ

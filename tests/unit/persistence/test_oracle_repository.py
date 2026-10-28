# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OracleRepositoryService and 1-RTT offload_metadata_v queries."""

import datetime
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import msgspec
import pytest

from goe.offload.offload_constants import (
    BACKEND_DISTRO_CDH,
    BACKEND_DISTRO_GCP,
    BACKEND_DISTRO_MSAZURE,
    BACKEND_DISTRO_SNOWFLAKE,
)
from goe.offload.offload_messages import OffloadMessages
from goe.orchestration import command_steps, orchestration_constants
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.models import OffloadSourcePartition
from goe.persistence.models import OffloadMetadata
from goe.persistence.oracle.oracle_repository import (
    ORACLE_REPO_SQL_PATH,
    OracleRepositoryService,
)
from goe.persistence.statements import NamedStatements
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options

EXEC_ID = ExecutionId()
STARTED = datetime.datetime(2026, 1, 1, 12, 0, 0)

METADATA_ROW_DICT = {
    "frontend_object_owner": "SH",
    "frontend_object_name": "SALES",
    "backend_object_owner": "sh",
    "backend_object_name": "sales",
    "offload_type": "INCREMENTAL",
    "offload_range_type": "PARTITION",
    "offload_key": "TIME_ID",
    "offload_high_value": "TO_DATE('2026-01-01', 'YYYY-MM-DD')",
    "offload_predicate_type": "RANGE_AND_PREDICATE",
    "offload_predicate_value": '["column(CHANNEL_ID) = numeric(3)"]',
    "offload_snapshot": 1001,
    "offload_hash_column": "PROD_ID",
    "offload_sort_columns": "CUST_ID,TIME_ID",
    "offload_partition_functions": "UDF_BUCKET",
    "command_execution": EXEC_ID.as_bytes(),
}


def test_get_offload_metadata_executes_single_select_without_lob_reads() -> None:
    """Verify get_offload_metadata executes a single SELECT against offload_metadata_v without LOB or gettype calls."""
    service, driver, conn = _build_service(select_rows=[METADATA_ROW_DICT])

    meta = service.get_offload_metadata("sh", "sales")

    assert isinstance(meta, OffloadMetadata)
    assert meta.offloaded_owner == "SH"
    assert meta.offloaded_table == "SALES"
    assert meta.backend_owner == "sh"
    assert meta.backend_table == "sales"
    assert meta.incremental_predicate_value == ["column(CHANNEL_ID) = numeric(3)"]
    assert meta.command_execution == EXEC_ID
    conn.gettype.assert_not_called()
    driver.select.assert_called_once()
    call_args = driver.select.call_args
    assert "offload_metadata_v" in call_args.args[0].lower()
    assert call_args.args[1] == {"frontend_owner": "SH", "frontend_name": "SALES"}

    list_rows = service.list_offload_metadata_by_owner("sh")
    assert len(list_rows) == 1
    assert list_rows[0] == meta


def test_set_offload_metadata_caches_udt_type_per_connection() -> None:
    """Verify set_offload_metadata caches the OFFLOAD_METADATA_OT descriptor per physical connection."""
    service, _driver, conn = _build_service()
    udt_type = MagicMock()
    udt_instance = SimpleNamespace()
    udt_type.newobject.return_value = udt_instance
    conn.gettype.return_value = udt_type
    cursor = MagicMock()
    conn.cursor.return_value = cursor

    meta = OffloadMetadata(
        offloaded_owner="sh",
        offloaded_table="sales",
        backend_owner="sh",
        backend_table="sales",
        offload_type="FULL",
        incremental_predicate_value=["column(CHANNEL_ID) = numeric(3)"],
        command_execution=EXEC_ID,
    )

    service.set_offload_metadata(meta)
    service.set_offload_metadata(meta)

    conn.gettype.assert_called_once_with('"GOE_REPO"."OFFLOAD_METADATA_OT"')
    assert cursor.callproc.call_count == 2
    cursor.callproc.assert_called_with("offload_repo.save_offload_metadata", ["SH", "SALES", udt_instance])
    assert conn.commit.call_count == 2
    assert udt_instance.OFFLOAD_PREDICATE_VALUE == '["column(CHANNEL_ID) = numeric(3)"]'
    assert udt_instance.COMMAND_EXECUTION == EXEC_ID.as_bytes()


def test_set_and_drop_offload_metadata_skip_db_in_dry_run() -> None:
    """Verify set_offload_metadata and drop_offload_metadata skip callproc and commit when dry_run=True."""
    service, _driver, conn = _build_service(dry_run=True)
    cursor = MagicMock()
    conn.cursor.return_value = cursor

    meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="FULL",
        command_execution=EXEC_ID,
    )

    service.set_offload_metadata(meta)
    service.drop_offload_metadata("SH", "SALES")

    conn.gettype.assert_not_called()
    cursor.callproc.assert_not_called()
    conn.commit.assert_not_called()


def test_command_and_step_lifecycle_procedures() -> None:
    """Verify start/end command, step, and chunk procedures, OUT bind extraction, and dry-run behavior."""
    service, _driver, conn = _build_service()
    cursor = MagicMock()
    out_var = MagicMock()
    out_var.getvalue.return_value = [42]
    cursor.var.return_value = out_var
    conn.cursor.return_value = cursor

    ntt_type = MagicMock()
    ntt_obj = MagicMock()
    ntt_type.newobject.return_value = ntt_obj
    part_type = MagicMock()
    part_obj = SimpleNamespace()
    part_type.newobject.return_value = part_obj

    def _gettype(name: str) -> Any:
        if name.endswith('"OFFLOAD_PARTITION_NTT"'):
            return ntt_type
        return part_type

    conn.gettype.side_effect = _gettype

    step_code = next(iter(command_steps.STEP_TITLES))
    cmd_code = orchestration_constants.COMMAND_OFFLOAD

    cmd_id = service.start_command(EXEC_ID, cmd_code, {"table": "SH.SALES"}, {"verify": True})
    assert cmd_id == 42
    service.end_command(cmd_id, orchestration_constants.COMMAND_SUCCESS)

    step_id = service.start_command_step(EXEC_ID, cmd_code, step_code)
    assert step_id == 42
    service.end_command_step(step_id, orchestration_constants.COMMAND_SUCCESS, {"rows": 100})

    partition = OffloadSourcePartition(
        "P2026",
        "'2026-01-01'",
        ("2026-01-01",),
        ("'2026-01-01'",),
        2048,
        50,
        True,
        None,
    )
    chunk_id = service.start_offload_chunk(
        EXEC_ID,
        "SH",
        "SALES",
        "sh",
        "sales",
        chunk_number=1,
        offload_partitions=[partition],
        offload_partition_level=1,
    )
    assert chunk_id == 42
    ntt_obj.append.assert_called_once_with(part_obj)
    assert part_obj.PARTITION_NAME == "P2026"
    assert part_obj.PARTITION_BYTES == 2048
    service.end_offload_chunk(
        chunk_id,
        orchestration_constants.COMMAND_SUCCESS,
        row_count=50,
        frontend_bytes=2048,
        transport_bytes=1024,
        backend_bytes=512,
    )

    service.drop_offload_metadata("sh", "sales")
    conn.commit.assert_called_once()

    dry_service, _dry_driver, dry_conn = _build_service(dry_run=True)
    assert dry_service.start_command(EXEC_ID, cmd_code, "offload", None) is None
    dry_service.end_command(None, orchestration_constants.COMMAND_SUCCESS)
    assert dry_service.start_command_step(EXEC_ID, cmd_code, step_code) is None
    dry_service.end_command_step(None, orchestration_constants.COMMAND_SUCCESS)
    assert dry_service.start_offload_chunk(EXEC_ID, "SH", "SALES", "sh", "sales") is None
    dry_service.end_offload_chunk(None, orchestration_constants.COMMAND_SUCCESS)
    dry_conn.cursor.assert_not_called()


def test_repository_read_queries_and_slot_validation() -> None:
    """Verify repository read queries across backend distributions and identifier slot validation."""
    schema_row = {
        "schema_name": "SH",
        "hybrid_schema_exists": "False",
        "table_count": 12,
        "schema_size_in_bytes": 1048576,
    }
    service, _driver, _conn = _build_service(select_rows=[schema_row])
    assert service.get_offloadable_schemas() == [schema_row]

    table_row = {
        "table_name": "SALES",
        "table_size_in_bytes": 65536,
        "table_offloaded_size_in_bytes": None,
        "table_reclaimed_size_in_bytes": None,
        "estimated_row_count": 1000,
        "statistics_last_gathered_on": STARTED,
        "partitioning_type": "RANGE",
        "subpartitioning_type": None,
        "table_compression": "DISABLED",
        "table_compress_for": None,
        "is_offloaded": "False",
        "is_partitioned": "True",
        "is_subpartitioned": "False",
        "is_compressed": "False",
        "is_offloadable": "True",
        "reason_not_offloadable": None,
    }
    for distro, expected_pattern in [
        (BACKEND_DISTRO_CDH, "unsupported_col_name_1"),
        (BACKEND_DISTRO_GCP, "unsupported_col_name_2"),
        (BACKEND_DISTRO_SNOWFLAKE, "unsupported_col_name_3"),
        (BACKEND_DISTRO_MSAZURE, "unsupported_col_name_4"),
    ]:
        svc, drv, _ = _build_service(select_rows=[table_row], backend_distribution=distro)
        assert svc.get_schema_tables("SH") == [table_row]
        assert expected_pattern in drv.select.call_args.args[0]

    code_svc, _, _ = _build_service(select_rows=[{"code": "OFFLOAD"}, {"code": "VERIFY"}])
    assert code_svc.get_command_step_codes() == ["OFFLOAD", "VERIFY"]

    exec_row = {
        "execution_id": EXEC_ID.as_bytes(),
        "command_type_code": "OFFLOAD",
        "command_type": "Offload",
        "status_code": "SUCCESS",
        "status": "Success",
        "started_at": STARTED,
        "completed_at": None,
        "command_log_path": "/tmp/offload.log",
        "command_input": "offload -t SH.SALES",
        "command_parameters": '{"owner_table": "SH.SALES"}',
        "goe_version": "1.0.0",
        "goe_build": "abc123",
    }
    exec_svc, _, _ = _build_service(select_rows=[exec_row])
    assert exec_svc.get_command_executions() == [exec_row]
    assert exec_svc.get_command_execution(EXEC_ID) == exec_row
    records = exec_svc.get_command_execution_records()
    assert len(records) == 1
    assert records[0].execution_id == EXEC_ID

    step_row = {
        "execution_id": EXEC_ID.as_bytes(),
        "step_id": 7,
        "step_code": "VERIFY",
        "step_title": "Verify exported data",
        "step_status_code": "SUCCESS",
        "step_status": "Success",
        "started_at": STARTED,
        "completed_at": None,
        "step_details": '{"rows": 10}',
    }
    step_svc, step_drv, _ = _build_service(select_rows=[step_row])
    assert step_svc.get_command_execution_steps(None) == [step_row]
    assert step_svc.get_command_execution_steps(EXEC_ID) == [step_row]
    assert step_drv.select.call_args.args[1] == {"execution_id": EXEC_ID.as_bytes()}
    step_records = step_svc.get_command_step_records(EXEC_ID)
    assert len(step_records) == 1
    assert step_records[0].step_details == {"rows": 10}

    bad_opts = build_mock_options(FAKE_ORACLE_BQ_ENV)
    bad_opts.ora_repo_user = "GOE_REPO; DROP TABLE X"
    bad_svc = OracleRepositoryService(bad_opts, OffloadMessages())
    with pytest.raises(ValueError, match="Invalid Oracle identifier"):
        bad_svc.get_command_step_codes()

    statements = NamedStatements(ORACLE_REPO_SQL_PATH, slots={"repo_user": "GOE_REPO"})
    assert "offload_metadata_v" in statements.text("get_offload_metadata")
    assert "offload_metadata_v" in statements.text("list_offload_metadata_by_owner")


def _build_service(
    *,
    select_rows: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    backend_distribution: str = BACKEND_DISTRO_GCP,
) -> tuple[OracleRepositoryService, MagicMock, MagicMock]:
    """Create an OracleRepositoryService wired to a mock OracleDatabaseRegistry and driver."""
    opts = build_mock_options(FAKE_ORACLE_BQ_ENV)
    opts.ora_repo_user = "GOE_REPO"
    opts.ora_adm_user = "GOE_ADM"
    opts.ora_app_user = "GOE_APP"
    opts.backend_distribution = backend_distribution

    conn = MagicMock()
    driver = MagicMock()
    driver.connection = conn

    raw_rows = list(select_rows or [])

    def _select(sql: str, *args: Any, schema_type: Any = None, **kwargs: Any) -> list[Any]:
        if schema_type is not None:
            return [msgspec.convert(row, type=schema_type) for row in raw_rows]
        return list(raw_rows)

    driver.select.side_effect = _select

    registry = MagicMock()

    @contextmanager
    def _adm_session(action: str | None = None):
        yield driver

    registry.adm_session.side_effect = _adm_session
    messages = OffloadMessages()
    messages.get_log_fh_name = MagicMock(return_value="/tmp/offload.log")
    service = OracleRepositoryService(opts, messages, dry_run=dry_run, registry=registry)
    return service, driver, conn

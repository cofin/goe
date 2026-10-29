# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for SystemService repository resolution and metadata methods."""

from unittest.mock import MagicMock, patch

from goe.listener.services.system import SystemService
from goe.offload.offload_messages import OffloadMessages
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.models import OffloadMetadata
from goe.persistence.oracle.oracle_repository import OracleRepositoryService
from goe.report.models import StatusReportEnvelope
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_system_service_get_repo_resolves_oracle_repository_service() -> None:
    """Verify SystemService.get_repo resolves OracleRepositoryService via AdapterRegistry."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()

    repo = SystemService.get_repo(config, messages)

    assert isinstance(repo, OracleRepositoryService)


def test_system_service_delegates_metadata_calls_to_repository() -> None:
    """Verify SystemService schema, table, and command execution queries delegate to OracleRepositoryService."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    service = SystemService(config=config, messages=messages)
    mock_repo = MagicMock(spec=OracleRepositoryService)
    exec_id = ExecutionId()

    mock_repo.get_offloadable_schemas.return_value = [{"schema_name": "SH"}]
    mock_repo.get_schema_tables.return_value = [{"table_name": "SALES"}]
    mock_repo.get_table_columns.return_value = [{"column_name": "PROD_ID"}]
    mock_repo.get_table_partitions.return_value = [{"partition_name": "P1"}]
    mock_repo.get_table_subpartitions.return_value = [{"subpartition_name": "SP1"}]
    mock_repo.get_command_executions.return_value = [{"execution_id": str(exec_id)}]
    mock_repo.get_command_execution.return_value = {"execution_id": str(exec_id)}
    mock_repo.get_command_execution_steps.return_value = [{"step_code": "VERIFY"}]

    with patch.object(SystemService, "get_repo", return_value=mock_repo):
        assert service.get_schemas() == [{"schema_name": "SH"}]
        assert service.get_schema_tables("SH") == [{"table_name": "SALES"}]
        assert service.get_table_columns("SH", "SALES") == [{"column_name": "PROD_ID"}]
        assert service.get_table_partitions("SH", "SALES") == [{"partition_name": "P1"}]
        assert service.get_table_subpartitions("SH", "SALES") == [{"subpartition_name": "SP1"}]
        assert service.get_command_executions() == [{"execution_id": str(exec_id)}]
        assert service.get_command_execution(exec_id) == {"execution_id": str(exec_id)}
        assert service.get_command_execution_steps(exec_id) == [{"step_code": "VERIFY"}]


def test_system_service_get_table_offload_metadata_and_status_report() -> None:
    """Verify SystemService.get_table_offload_metadata and get_status_report (demo and wired fetchers)."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    service = SystemService(config=config, messages=messages)
    mock_repo = MagicMock(spec=OracleRepositoryService)
    expected_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh_bq",
        backend_table="sales",
        offload_type="FULL",
    )
    mock_repo.get_offload_metadata.return_value = expected_meta
    mock_repo.get_table_partitions.return_value = [
        {"partition_name": "P_2025", "high_value": "2025-01-01", "num_rows": 500, "bytes": 4096}
    ]

    with patch.object(SystemService, "get_repo", return_value=mock_repo):
        meta = service.get_table_offload_metadata("sh", "sales")
        assert meta == expected_meta
        mock_repo.get_offload_metadata.assert_called_once_with("SH", "SALES")

        demo_env = service.get_status_report(schema_name="SH", demo=True)
        assert isinstance(demo_env, StatusReportEnvelope)

    with (
        patch.object(SystemService, "get_repo", return_value=mock_repo),
        patch.object(service, "get_db_unique_name", return_value="ORCL"),
    ):
        live_env = service.get_status_report(schema_name="SH", table_name="SALES", demo=False)
        assert isinstance(live_env, StatusReportEnvelope)
        assert live_env.database_name == "ORCL"
        assert live_env.total_tables == 1
        assert live_env.tables[0].schema_name == "SH"
        assert live_env.tables[0].table_name == "SALES"
        assert live_env.tables[0].source_rows == 500
        assert live_env.tables[0].source_bytes == 4096

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for Oracle session tagging, SQLCommenter, and SQLSpec observability."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.db import (
    apply_oracle_session_trace_info,
    attach_db_observability,
    build_db_observability_config,
    build_oracle_client_info_command,
    build_transport_sql_comment,
    format_oracle_client_info,
    format_sqlcommenter,
)
from goe.observability.spans import traced_command
from goe.offload.oracle.oracle_offload_transport_rdbms_api import OffloadTransportOracleApi

EXEC_ID = "2f1b7c1e-0000-4000-8000-000000000040"


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime with SQLCommenter enabled."""
    settings = ObservabilitySettings(enabled=True, exporter="memory", sqlcommenter=True)
    active = runtime.configure_observability(settings, set_global=False)
    yield active
    runtime.shutdown_observability()


def test_disabled_runtime_changes_nothing() -> None:
    runtime.shutdown_observability()
    conn = MagicMock()
    assert format_oracle_client_info() is None
    assert apply_oracle_session_trace_info(conn) is None
    assert "clientinfo" not in vars(conn)
    assert build_transport_sql_comment("GOE_ACTION_1") == "GOE_ACTION_1"
    assert build_db_observability_config() is None
    driver = MagicMock()
    attach_db_observability(driver)
    driver.attach_observability.assert_not_called()
    commands = _transport_api().get_rdbms_session_setup_commands("GOE", "ACT1", {}, for_plsql=True)
    assert not any("SET_CLIENT_INFO" in command for command in commands)


def test_client_info_is_traceparent(memory_runtime: runtime.ObservabilityRuntime) -> None:
    conn = MagicMock()
    with traced_command("OFFLOAD", EXEC_ID):
        info = apply_oracle_session_trace_info(conn)
    assert info is not None and info.startswith("00-") and len(info.encode()) == 55
    assert conn.clientinfo == info
    assert "module" not in vars(conn) and "action" not in vars(conn)


def test_session_setup_keeps_set_module(memory_runtime: runtime.ObservabilityRuntime) -> None:
    with traced_command("OFFLOAD", EXEC_ID):
        plsql = _transport_api().get_rdbms_session_setup_commands("GOE", "ACT1", {}, for_plsql=True)
        sql = _transport_api().get_rdbms_session_setup_commands("GOE", "ACT1", {})
    assert plsql[0] == "DBMS_APPLICATION_INFO.SET_MODULE('GOE','ACT1');"
    assert plsql[1].startswith("DBMS_APPLICATION_INFO.SET_CLIENT_INFO('00-")
    assert sql[1].startswith("BEGIN DBMS_APPLICATION_INFO.SET_CLIENT_INFO('00-") and sql[1].endswith("END;")
    assert build_oracle_client_info_command(for_plsql=True) is None


def test_transport_sql_comment(memory_runtime: runtime.ObservabilityRuntime) -> None:
    with traced_command("OFFLOAD", EXEC_ID):
        full = format_sqlcommenter(action="OFFLOAD")
        comment = build_transport_sql_comment("GOE_ACTION_1")
    assert full is not None and full.startswith("/*") and full.endswith("*/")
    assert "action='OFFLOAD'" in full
    assert f"goe_execution_id='{EXEC_ID}'" in full
    assert "traceparent='00-" in full
    assert comment is not None and comment.startswith(f"GOE_ACTION_1 goe_execution_id='{EXEC_ID}',traceparent='00-")
    assert "/*" not in comment and "*/" not in comment


def test_sqlspec_observability_attached(memory_runtime: runtime.ObservabilityRuntime) -> None:
    config = build_db_observability_config()
    assert config is not None and config.telemetry.enable_spans is True
    assert config.telemetry.provider_factory() is memory_runtime.tracer_provider
    driver = MagicMock()
    statement_config = driver.statement_config
    attach_db_observability(driver)
    driver.attach_observability.assert_called_once()
    statement_config.replace.assert_called_once_with(
        enable_sqlcommenter=True,
        sqlcommenter_attributes={"db_driver": "oracledb", "framework": "goe"},
        sqlcommenter_enable_traceparent=True,
        sqlcommenter_enable_context=True,
    )
    assert driver.statement_config is statement_config.replace.return_value


def _transport_api() -> OffloadTransportOracleApi:
    """Build an OffloadTransportOracleApi without connecting."""
    api = object.__new__(OffloadTransportOracleApi)
    api._fixed_goe_parameters = {}
    return api

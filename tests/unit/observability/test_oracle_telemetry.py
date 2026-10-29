# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for Oracle transport trace helpers, SQLCommenter, and SQLSpec observability."""

from collections.abc import Iterator

import pytest

from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.db import (
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
    """Disabled observability leaves transport SQL comments and session setup commands unchanged."""
    runtime.shutdown_observability()
    assert format_oracle_client_info() is None
    assert build_transport_sql_comment("GOE_ACTION_1") == "GOE_ACTION_1"
    assert build_db_observability_config() is None
    commands = _transport_api().get_rdbms_session_setup_commands("GOE", "ACT1", {}, for_plsql=True)
    assert not any("SET_CLIENT_INFO" in command for command in commands)


def test_session_setup_keeps_set_module(memory_runtime: runtime.ObservabilityRuntime) -> None:
    """Session setup commands preserve SET_MODULE and append SET_CLIENT_INFO when traced."""
    del memory_runtime
    with traced_command("OFFLOAD", EXEC_ID):
        plsql = _transport_api().get_rdbms_session_setup_commands("GOE", "ACT1", {}, for_plsql=True)
        sql = _transport_api().get_rdbms_session_setup_commands("GOE", "ACT1", {})
    assert plsql[0] == "DBMS_APPLICATION_INFO.SET_MODULE('GOE','ACT1');"
    assert plsql[1].startswith("DBMS_APPLICATION_INFO.SET_CLIENT_INFO('00-")
    assert sql[1].startswith("BEGIN DBMS_APPLICATION_INFO.SET_CLIENT_INFO('00-") and sql[1].endswith("END;")
    assert build_oracle_client_info_command(for_plsql=True) is None


def test_transport_sql_comment(memory_runtime: runtime.ObservabilityRuntime) -> None:
    """build_transport_sql_comment appends SQLCommenter attributes inside the existing transport comment."""
    del memory_runtime
    with traced_command("OFFLOAD", EXEC_ID):
        full = format_sqlcommenter(action="OFFLOAD")
        comment = build_transport_sql_comment("GOE_ACTION_1")
    assert full is not None and full.startswith("/*") and full.endswith("*/")
    assert "action='OFFLOAD'" in full
    assert f"goe_execution_id='{EXEC_ID}'" in full
    assert "traceparent='00-" in full
    assert comment is not None and comment.startswith(f"GOE_ACTION_1 goe_execution_id='{EXEC_ID}',traceparent='00-")
    assert "/*" not in comment and "*/" not in comment


def test_db_observability_config_uses_goe_tracer_provider(memory_runtime: runtime.ObservabilityRuntime) -> None:
    """build_db_observability_config wires SQLSpec spans to the active GOE tracer provider."""
    config = build_db_observability_config()
    assert config is not None and config.telemetry.enable_spans is True
    assert config.telemetry.provider_factory() is memory_runtime.tracer_provider


def _transport_api() -> OffloadTransportOracleApi:
    """Build an OffloadTransportOracleApi without connecting."""
    api = object.__new__(OffloadTransportOracleApi)
    api._fixed_goe_parameters = {}
    return api

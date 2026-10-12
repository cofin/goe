# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for DuckDB transport batch spans."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.spans import traced_command
from goe.offload.transport.duckdb_transport import OffloadTransportDuckDB

EXEC_ID = "2f1b7c1e-0000-4000-8000-000000000060"


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime for one test."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_batches_are_children_of_command(
    memory_runtime: runtime.ObservabilityRuntime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = object.__new__(OffloadTransportDuckDB)
    monkeypatch.setenv("ORA_SDTZ", "UTC")
    transport._offload_transport_method = "DUCKDB"
    transport._duckdb_temp_root = str(tmp_path)
    monkeypatch.setattr(transport, "_gcs_access_token", lambda: ("token", "proj"), raising=False)
    monkeypatch.setattr(transport, "_run_batch", lambda batch, sql, token, project, run_dir: 5, raising=False)
    with traced_command("OFFLOAD", EXEC_ID) as command_op:
        assert transport._run_batches(["COPY 1", "COPY 2"]) == 10
    command_span_id = command_op.span.get_span_context().span_id
    batches = [s for s in memory_runtime.get_finished_spans() if s.name == "goe.transport.duckdb.batch"]
    assert sorted(span.attributes["goe.transport.batch.index"] for span in batches) == [0, 1]
    assert all(span.parent.span_id == command_span_id for span in batches)
    assert all(span.attributes["goe.execution.id"] == EXEC_ID for span in batches)
    assert all(span.attributes["goe.transport.batch.rows"] == 5 for span in batches)

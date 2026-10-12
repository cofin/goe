# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for chunk, transport, and subprocess telemetry."""

import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from opentelemetry import trace

from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.spans import traced_command
from goe.observability.transport import inject_spark_trace_properties, submit_with_context
from goe.offload.offload_transport_functions import run_os_cmd, transport_and_load_offload_chunk

EXEC_ID = "2f1b7c1e-0000-4000-8000-000000000050"


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime for one test."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_chunk_contains_transport_span(memory_runtime: runtime.ObservabilityRuntime) -> None:
    target = MagicMock(db_name="SH_LOAD", table_name="SALES")
    target.backend_type.return_value = "bigquery"
    target.get_table_size.side_effect = [1000, 3000]
    source = MagicMock(owner="SH", size_in_bytes=500)
    with traced_command("OFFLOAD", EXEC_ID):
        rows = transport_and_load_offload_chunk(_transport_client(), source, target, EXEC_ID, MagicMock(), MagicMock())
    assert rows == 10
    spans = {span.name: span for span in memory_runtime.get_finished_spans()}
    chunk = spans["goe.chunk"]
    transport = spans["goe.transport.query_import"]
    assert transport.parent.span_id == chunk.get_span_context().span_id
    assert chunk.attributes["goe.chunk.rows_staged"] == 10
    assert chunk.attributes["goe.chunk.backend_bytes"] == 2000
    assert memory_runtime.get_metrics_data() is not None


def test_run_os_cmd_propagates_traceparent(memory_runtime: runtime.ObservabilityRuntime) -> None:
    options = MagicMock(vverbose=True, quiet=False)
    code = "import os; print(os.environ.get('TRACEPARENT', 'none')); print(os.environ.get('GOE_EXECUTION_ID'))"
    with traced_command("OFFLOAD", EXEC_ID):
        returncode, output = run_os_cmd([sys.executable, "-c", code], MagicMock(), options)
    assert returncode == 0
    assert output.splitlines()[0].startswith("00-")
    assert output.splitlines()[1] == EXEC_ID
    span = next(s for s in memory_runtime.get_finished_spans() if s.name.startswith("goe.os_cmd."))
    assert span.attributes["process.exit_code"] == 0


def test_run_os_cmd_disabled_passes_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime.shutdown_observability()
    popen = MagicMock()
    popen.return_value.stdout = []
    popen.return_value.wait.return_value = 0
    monkeypatch.setattr("goe.offload.offload_transport_functions.subprocess.Popen", popen)
    run_os_cmd(["true"], MagicMock(), MagicMock(vverbose=True, quiet=False))
    assert popen.call_args.kwargs["env"] is None


def test_spark_properties_and_thread_context(memory_runtime: runtime.ObservabilityRuntime) -> None:
    assert inject_spark_trace_properties({"a": "b"}) == {"a": "b"}
    with traced_command("OFFLOAD", EXEC_ID):
        props = inject_spark_trace_properties({"a": "b"})
        parent_id = trace.get_current_span().get_span_context().span_id
        with ThreadPoolExecutor(max_workers=1) as executor:
            child_parent = submit_with_context(
                executor, lambda: trace.get_current_span().get_span_context().span_id
            ).result()
    assert props["spark.executorEnv.TRACEPARENT"].startswith("00-")
    assert props["spark.executorEnv.GOE_EXECUTION_ID"] == EXEC_ID
    assert child_parent == parent_id


def _transport_client() -> MagicMock:
    """Return a transport client double reporting 10 rows and 4096 staged bytes."""
    client = MagicMock()
    client.transport.return_value = 10
    client.get_transport_bytes.return_value = 4096
    client.get_transport_method.return_value = "QUERY_IMPORT"
    client.get_telemetry_attributes.return_value = {"goe.transport.method": "QUERY_IMPORT"}
    return client

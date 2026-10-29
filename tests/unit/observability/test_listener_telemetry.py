# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for GOE Listener telemetry wiring."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from litestar.plugins.opentelemetry import OpenTelemetryPlugin
from litestar.testing import TestClient
from opentelemetry.trace import SpanKind, StatusCode

from goe.listener.app import create_app
from goe.listener.telemetry import (
    after_mcp_tool_call,
    before_mcp_tool_call,
    build_listener_otel_plugin,
)
from goe.observability import runtime
from goe.observability.config import ObservabilitySettings


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime for one test."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_builders_disabled() -> None:
    """Verify build_listener_otel_plugin returns None when telemetry is disabled."""
    noop = runtime.ObservabilityRuntime.noop()
    assert build_listener_otel_plugin(noop) is None


def test_builders_enabled(memory_runtime: runtime.ObservabilityRuntime) -> None:
    """Verify build_listener_otel_plugin binds to the active tracer and meter providers."""
    plugin = build_listener_otel_plugin(memory_runtime)
    assert isinstance(plugin, OpenTelemetryPlugin)
    assert plugin.config.tracer_provider is memory_runtime.tracer_provider


def test_http_request_emits_server_span(memory_runtime: runtime.ObservabilityRuntime) -> None:
    """Verify HTTP requests emit SERVER spans when OpenTelemetry is enabled."""
    with TestClient(app=create_app(enable_background_worker=False)) as client:
        response = client.post(
            "/mcp",
            headers={
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/list",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
        )
        assert response.status_code == 200
    assert any(span.kind == SpanKind.SERVER for span in memory_runtime.get_finished_spans())


def test_mcp_hooks_wrap_tool_execution(memory_runtime: runtime.ObservabilityRuntime) -> None:
    """Verify before/after MCP hooks create a child span under the HTTP span."""
    tracer = memory_runtime.get_tracer("test")
    request = SimpleNamespace(state=SimpleNamespace())
    with tracer.start_as_current_span("http.mcp") as http_span:
        before_mcp_tool_call("get_command_execution", {}, request)
        with tracer.start_as_current_span("handler"):
            pass
        after_mcp_tool_call("get_command_execution", {}, request, result=None, exception=None, duration=0.01)
    spans = {span.name: span for span in memory_runtime.get_finished_spans()}
    tool = spans["goe.mcp.tool.get_command_execution"]
    assert tool.parent.span_id == http_span.get_span_context().span_id
    assert spans["handler"].parent.span_id == tool.get_span_context().span_id
    assert tool.attributes["goe.mcp.tool_name"] == "get_command_execution"


def test_mcp_hook_records_failure(memory_runtime: runtime.ObservabilityRuntime) -> None:
    """Verify after_mcp_tool_call marks the span status as ERROR on exception."""
    request = SimpleNamespace(state=SimpleNamespace())
    before_mcp_tool_call("execute_offload", {}, request)
    after_mcp_tool_call("execute_offload", {}, request, result=None, exception=RuntimeError("denied"), duration=0.0)
    tool = next(span for span in memory_runtime.get_finished_spans() if span.name == "goe.mcp.tool.execute_offload")
    assert tool.status.status_code == StatusCode.ERROR

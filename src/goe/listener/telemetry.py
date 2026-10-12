# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OpenTelemetry wiring for the GOE Listener: Litestar plugin, litestar-queues tracing, and MCP tool spans."""

from typing import TYPE_CHECKING, Any

from litestar_queues.observability import ObservabilityConfig as QueueObservabilityConfig
from opentelemetry import context, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.observability.runtime import ObservabilityRuntime, get_observability_runtime, get_tracer

if TYPE_CHECKING:
    from litestar.plugins.opentelemetry import OpenTelemetryConfig, OpenTelemetryPlugin

__all__ = (
    "LISTENER_EXCLUDED_PATHS",
    "after_mcp_tool_call",
    "before_mcp_tool_call",
    "build_listener_otel_plugin",
    "build_queue_observability_config",
)

LISTENER_EXCLUDED_PATHS: list[str] = ["/api/system/status"]
_MCP_SPAN_ATTR = "goe_mcp_tool_span"
_MCP_TOKEN_ATTR = "goe_mcp_tool_token"

_LAZY_IMPORTS: LazyImportMap = {
    "OpenTelemetryConfig": ("litestar.plugins.opentelemetry", "OpenTelemetryConfig"),
    "OpenTelemetryPlugin": ("litestar.plugins.opentelemetry", "OpenTelemetryPlugin"),
}


def build_listener_otel_plugin(active: ObservabilityRuntime) -> "OpenTelemetryPlugin | None":
    """Return Litestar's OpenTelemetryPlugin bound to GOE providers, or None when telemetry is disabled."""
    if not active.enabled:
        return None
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    return OpenTelemetryPlugin(
        OpenTelemetryConfig(
            tracer_provider=active.tracer_provider,
            meter_provider=active.meter_provider,
            exclude=LISTENER_EXCLUDED_PATHS,
        )
    )


def build_queue_observability_config(active: ObservabilityRuntime) -> QueueObservabilityConfig | None:
    """Return litestar-queues observability bound to GOE providers, or None (queue telemetry off) when disabled."""
    if not active.enabled:
        return None
    return QueueObservabilityConfig(
        enable_otel=True,
        tracer_provider=active.tracer_provider,
        meter_provider=active.meter_provider,
    )


def before_mcp_tool_call(tool_name: str, arguments: dict[str, Any], request: Any, /) -> None:
    """Start ``goe.mcp.tool.<tool_name>`` as the current span and stash it on ``request.state``."""
    if request is None or not get_observability_runtime().enabled:
        return
    span = get_tracer().start_span(
        f"goe.mcp.tool.{tool_name}", kind=SpanKind.INTERNAL, attributes={"goe.mcp.tool_name": tool_name}
    )
    setattr(request.state, _MCP_SPAN_ATTR, span)
    setattr(request.state, _MCP_TOKEN_ATTR, context.attach(trace.set_span_in_context(span)))


def after_mcp_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    request: Any,
    /,
    *,
    result: Any,
    exception: Exception | None,
    duration: float,
) -> None:
    """End the tool span started by ``before_mcp_tool_call``, recording failure and dispatch duration."""
    span = getattr(request.state, _MCP_SPAN_ATTR, None) if request is not None else None
    if span is None:
        return
    token = getattr(request.state, _MCP_TOKEN_ATTR, None)
    span.set_attribute("goe.mcp.duration_s", duration)
    if exception is not None:
        span.record_exception(exception)
        span.set_status(Status(StatusCode.ERROR, str(exception)))
    else:
        span.set_status(Status(StatusCode.OK))
    if token is not None:
        context.detach(token)
    span.end()
    setattr(request.state, _MCP_SPAN_ATTR, None)
    setattr(request.state, _MCP_TOKEN_ATTR, None)


def __getattr__(name: str) -> Any:
    """Resolve lazily bound Litestar OpenTelemetry classes on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)

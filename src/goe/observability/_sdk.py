# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OpenTelemetry SDK provider construction for GOE.

This is the only GOE module importing ``opentelemetry.sdk``; ``goe.observability.runtime`` loads it lazily when
telemetry is active. OTLP exporter classes are bound lazily per protocol so the unused transport is never imported.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from socket import gethostname
from typing import TYPE_CHECKING, Any

import msgspec
from google.auth.transport.requests import AuthorizedSession
from opentelemetry.context import Context
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    InMemoryMetricReader,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.config.orchestration_defaults import log_path_default
from goe.observability.config import ObservabilitySettings
from goe.observability.context import current_execution_attributes
from goe.util.gcp_credentials import DEFAULT_GCP_SCOPES, resolve_gcp_credentials
from goe.util.goe_version import goe_version

if TYPE_CHECKING:
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as GrpcMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcSpanExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HttpMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HttpSpanExporter

__all__ = (
    "GCP_TELEMETRY_ENDPOINT",
    "ExecutionContextSpanProcessor",
    "JSONLSpanExporter",
    "SdkProviders",
    "build_metric_readers",
    "build_resource",
    "build_sdk_providers",
    "build_span_exporter",
)

GCP_TELEMETRY_ENDPOINT = "https://telemetry.googleapis.com"

_OTLP_GRPC_IMPORTS: LazyImportMap = {
    "GrpcSpanExporter": ("opentelemetry.exporter.otlp.proto.grpc.trace_exporter", "OTLPSpanExporter"),
    "GrpcMetricExporter": ("opentelemetry.exporter.otlp.proto.grpc.metric_exporter", "OTLPMetricExporter"),
}
_OTLP_HTTP_IMPORTS: LazyImportMap = {
    "HttpSpanExporter": ("opentelemetry.exporter.otlp.proto.http.trace_exporter", "OTLPSpanExporter"),
    "HttpMetricExporter": ("opentelemetry.exporter.otlp.proto.http.metric_exporter", "OTLPMetricExporter"),
}
_LAZY_IMPORTS: LazyImportMap = {**_OTLP_GRPC_IMPORTS, **_OTLP_HTTP_IMPORTS}


class ExecutionContextSpanProcessor(SpanProcessor):
    """Stamp bound GOE execution attributes onto every span when it starts."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Copy ``current_execution_attributes()`` onto the starting span without overwriting set keys."""
        if not span.is_recording():
            return
        existing = span.attributes or {}
        for key, value in current_execution_attributes().items():
            if key not in existing:
                span.set_attribute(key, value)


class JSONLSpanExporter(SpanExporter):
    """Append finished spans to a local JSON Lines file using msgspec."""

    def __init__(self, file_path: str | Path) -> None:
        """Create the parent directory of ``file_path``; reject ``gs://`` paths."""
        if str(file_path).startswith("gs://"):
            raise ValueError(f"JSONL trace export requires a local path, got {file_path}")
        self._file_path = Path(file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Serialize each span to one JSON line and append it to the file."""
        try:
            with self._file_path.open("ab") as handle:
                for span in spans:
                    handle.write(msgspec.json.encode(_span_record(span)) + b"\n")
        except OSError:
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Release nothing; the file is opened per export batch."""

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Return True because every export writes synchronously."""
        return True


@dataclass(frozen=True)
class SdkProviders:
    """SDK providers plus the in-memory harness handles used when ``exporter == "memory"``."""

    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    memory_span_exporter: InMemorySpanExporter | None = None
    memory_metric_reader: InMemoryMetricReader | None = None


def build_resource(settings: ObservabilitySettings, gcp_project_id: str | None = None) -> Resource:
    """Build the OpenTelemetry Resource describing this GOE process."""
    attributes: dict[str, str] = {
        "service.name": settings.service_name,
        "service.version": goe_version(),
        "service.instance.id": f"{gethostname()}:{os.getpid()}",
    }
    if settings.deployment_environment:
        attributes["deployment.environment.name"] = settings.deployment_environment
    if gcp_project_id:
        attributes["gcp.project_id"] = gcp_project_id
    return Resource.create(attributes)


def build_span_exporter(settings: ObservabilitySettings, config: Any | None = None) -> SpanExporter:
    """Return the span exporter selected by ``settings.exporter`` (not valid for ``none`` or ``memory``)."""
    if settings.exporter == "console":
        return ConsoleSpanExporter()
    if settings.exporter == "jsonl":
        return JSONLSpanExporter(_jsonl_path(settings))
    if settings.exporter == "gcp":
        session, _project = _gcp_session(config)
        bind_lazy_imports(__name__, _OTLP_HTTP_IMPORTS)
        return HttpSpanExporter(endpoint=_gcp_url(settings, "traces"), session=session)
    if settings.exporter == "otlp" and settings.protocol == "http/protobuf":
        bind_lazy_imports(__name__, _OTLP_HTTP_IMPORTS)
        return HttpSpanExporter(endpoint=settings.endpoint)
    if settings.exporter == "otlp":
        bind_lazy_imports(__name__, _OTLP_GRPC_IMPORTS)
        return GrpcSpanExporter(endpoint=settings.endpoint)
    raise ValueError(f"No span exporter for exporter={settings.exporter!r}")


def build_metric_readers(settings: ObservabilitySettings, config: Any | None = None) -> list[MetricReader]:
    """Return metric readers for the selected exporter; ``jsonl`` exports no metrics."""
    if settings.exporter == "console":
        return [PeriodicExportingMetricReader(ConsoleMetricExporter())]
    if settings.exporter == "gcp":
        session, _project = _gcp_session(config)
        bind_lazy_imports(__name__, _OTLP_HTTP_IMPORTS)
        return [
            PeriodicExportingMetricReader(HttpMetricExporter(endpoint=_gcp_url(settings, "metrics"), session=session))
        ]
    if settings.exporter == "otlp" and settings.protocol == "http/protobuf":
        bind_lazy_imports(__name__, _OTLP_HTTP_IMPORTS)
        return [PeriodicExportingMetricReader(HttpMetricExporter(endpoint=settings.endpoint))]
    if settings.exporter == "otlp":
        bind_lazy_imports(__name__, _OTLP_GRPC_IMPORTS)
        return [PeriodicExportingMetricReader(GrpcMetricExporter(endpoint=settings.endpoint))]
    return []


def build_sdk_providers(settings: ObservabilitySettings, config: Any | None = None) -> SdkProviders:
    """Build SDK tracer and meter providers for an active ``settings`` (exporter is never ``none``)."""
    gcp_project_id = resolve_gcp_credentials(config).project if settings.exporter == "gcp" else None
    resource = build_resource(settings, gcp_project_id=gcp_project_id)
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=ParentBasedTraceIdRatio(settings.sample_rate),
        shutdown_on_exit=False,
    )
    tracer_provider.add_span_processor(ExecutionContextSpanProcessor())
    if settings.exporter == "memory":
        memory_span_exporter = InMemorySpanExporter()
        memory_metric_reader = InMemoryMetricReader()
        tracer_provider.add_span_processor(SimpleSpanProcessor(memory_span_exporter))
        meter_provider = MeterProvider(resource=resource, metric_readers=[memory_metric_reader], shutdown_on_exit=False)
        return SdkProviders(tracer_provider, meter_provider, memory_span_exporter, memory_metric_reader)
    span_exporter = build_span_exporter(settings, config)
    if settings.exporter in ("console", "jsonl"):
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    else:
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    meter_provider = MeterProvider(
        resource=resource, metric_readers=build_metric_readers(settings, config), shutdown_on_exit=False
    )
    return SdkProviders(tracer_provider, meter_provider)


def __getattr__(name: str) -> Any:
    """Resolve lazily bound OTLP exporter classes on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)


def _span_record(span: ReadableSpan) -> dict[str, Any]:
    """Convert a finished span to a JSON-serializable dict."""
    span_ctx = span.get_span_context()
    parent = span.parent
    return {
        "name": span.name,
        "trace_id": format(span_ctx.trace_id, "032x") if span_ctx else None,
        "span_id": format(span_ctx.span_id, "016x") if span_ctx else None,
        "parent_span_id": format(parent.span_id, "016x") if parent else None,
        "kind": span.kind.name,
        "start_time_ns": span.start_time,
        "end_time_ns": span.end_time,
        "status_code": span.status.status_code.name,
        "status_description": span.status.description,
        "attributes": dict(span.attributes or {}),
        "events": [
            {"name": event.name, "timestamp_ns": event.timestamp, "attributes": dict(event.attributes or {})}
            for event in span.events
        ],
    }


def _jsonl_path(settings: ObservabilitySettings) -> str:
    """Return the configured JSONL path or ``<log dir>/goe_traces.jsonl``."""
    return settings.jsonl_path or os.path.join(log_path_default(), "goe_traces.jsonl")


def _gcp_session(config: Any | None) -> tuple[AuthorizedSession, str | None]:
    """Return an ADC-authorized HTTP session and the resolved Google Cloud project."""
    bundle = resolve_gcp_credentials(config, scopes=DEFAULT_GCP_SCOPES)
    return AuthorizedSession(bundle.credentials), bundle.project


def _gcp_url(settings: ObservabilitySettings, signal: str) -> str:
    """Return the Telemetry API URL for ``signal`` (``traces`` or ``metrics``)."""
    root = (settings.endpoint or GCP_TELEMETRY_ENDPOINT).rstrip("/")
    return f"{root}/v1/{signal}"

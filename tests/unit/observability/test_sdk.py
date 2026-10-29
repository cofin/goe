# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for goe.observability._sdk provider builders."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from google.auth.credentials import AnonymousCredentials
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HttpSpanExporter

from goe.observability import _sdk
from goe.observability.config import ObservabilitySettings
from goe.observability.context import bind_execution_context, bind_step_context
from goe.serializers import decode_json


def test_memory_providers_stamp_execution_attributes() -> None:
    providers = _sdk.build_sdk_providers(ObservabilitySettings(enabled=True, exporter="memory"))
    tracer = providers.tracer_provider.get_tracer("test")
    with bind_execution_context("2f1b7c1e-0000-4000-8000-000000000003", command_type="OFFLOAD"):
        with bind_step_context("stage_data"):
            with tracer.start_as_current_span("third.party.span"):
                pass
    assert providers.memory_span_exporter is not None
    spans = providers.memory_span_exporter.get_finished_spans()
    assert spans[0].attributes is not None
    assert spans[0].attributes["goe.execution.id"] == "2f1b7c1e-0000-4000-8000-000000000003"
    assert spans[0].attributes["goe.step.id"] == "stage_data"
    assert providers.memory_metric_reader is not None
    assert providers.tracer_provider.resource.attributes["service.name"] == "goe"


def test_jsonl_exporter_writes_decodable_lines(tmp_path: Path) -> None:
    target = tmp_path / "traces.jsonl"
    settings = ObservabilitySettings(enabled=True, exporter="jsonl", jsonl_path=str(target))
    providers = _sdk.build_sdk_providers(settings)
    tracer = providers.tracer_provider.get_tracer("test")
    with tracer.start_as_current_span("parent"):
        with tracer.start_as_current_span("child"):
            pass
    providers.tracer_provider.shutdown()
    records = [decode_json(line) for line in target.read_bytes().splitlines()]
    child = next(r for r in records if r["name"] == "child")
    parent = next(r for r in records if r["name"] == "parent")
    assert child["trace_id"] == parent["trace_id"]
    assert child["parent_span_id"] == parent["span_id"]


def test_jsonl_rejects_gcs_path() -> None:
    settings = ObservabilitySettings(enabled=True, exporter="jsonl", jsonl_path="gs://bucket/traces.jsonl")
    with pytest.raises(ValueError, match="local"):
        _sdk.build_span_exporter(settings)


def test_otlp_protocol_selects_exporter() -> None:
    grpc_settings = ObservabilitySettings(enabled=True, exporter="otlp", endpoint="localhost:4317")
    http_settings = ObservabilitySettings(
        enabled=True, exporter="otlp", protocol="http/protobuf", endpoint="http://localhost:4318/v1/traces"
    )
    assert isinstance(_sdk.build_span_exporter(grpc_settings), GrpcSpanExporter)
    assert isinstance(_sdk.build_span_exporter(http_settings), HttpSpanExporter)


def test_gcp_exporter_uses_telemetry_api(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = SimpleNamespace(credentials=AnonymousCredentials(), project="goe-test-project")
    monkeypatch.setattr(_sdk, "resolve_gcp_credentials", lambda config, scopes=None: bundle)
    settings = ObservabilitySettings(enabled=True, exporter="gcp")
    exporter = _sdk.build_span_exporter(settings)
    assert isinstance(exporter, HttpSpanExporter)
    assert exporter._endpoint == "https://telemetry.googleapis.com/v1/traces"
    providers = _sdk.build_sdk_providers(settings)
    assert providers.tracer_provider.resource.attributes["gcp.project_id"] == "goe-test-project"

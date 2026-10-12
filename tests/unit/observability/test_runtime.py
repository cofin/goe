# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for goe.observability.runtime."""

import subprocess
import sys
from collections.abc import Iterator

import pytest
from opentelemetry.trace import NoOpTracerProvider

from goe.observability import _sdk, runtime
from goe.observability.config import ObservabilitySettings


def test_default_runtime_is_noop_and_unconfigured() -> None:
    active = runtime.get_observability_runtime()
    assert isinstance(active.tracer_provider, NoOpTracerProvider)
    assert active.settings.enabled is False
    assert runtime.is_observability_configured() is False


def test_disabled_path_never_imports_sdk() -> None:
    code = (
        "import sys;"
        "from goe.observability.runtime import configure_observability, get_tracer;"
        "configure_observability(set_global=False);"
        "get_tracer().start_span('x').end();"
        "assert 'opentelemetry.sdk' not in sys.modules, 'sdk imported';"
        "assert 'goe.observability._sdk' not in sys.modules, '_sdk imported'"
    )
    env = {"GOE_NO_AUTOLOAD_ENV": "1", "PATH": "/usr/bin:/bin"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_memory_runtime_records_spans_and_metrics() -> None:
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    with runtime.get_tracer().start_as_current_span("goe.test"):
        active.metrics.record_command("OFFLOAD", "success", "bigquery", False, 1.0)
    assert [span.name for span in active.get_finished_spans()] == ["goe.test"]
    assert active.get_metrics_data() is not None
    active.clear_finished_spans()
    assert active.get_finished_spans() == ()


def test_ensure_configures_only_once() -> None:
    first = runtime.ensure_observability(ObservabilitySettings(enabled=True, exporter="memory"))
    second = runtime.ensure_observability(ObservabilitySettings(enabled=False))
    assert first is second
    assert runtime.is_observability_configured() is True


def test_builder_failure_falls_back_to_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_sdk, "build_sdk_providers", _boom)
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="otlp"), set_global=False)
    assert isinstance(active.tracer_provider, NoOpTracerProvider)
    assert active.settings.enabled is False


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    """Forget any runtime configured earlier in the session and after each test."""
    runtime.shutdown_observability()
    yield
    runtime.shutdown_observability()


def _boom(settings: ObservabilitySettings, config: object = None) -> None:
    """Raise an error during SDK provider construction to verify fail-safe fallback."""
    raise RuntimeError("collector unreachable")

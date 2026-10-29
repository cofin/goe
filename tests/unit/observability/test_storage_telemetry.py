# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for storage CLIENT spans."""

from collections.abc import Iterator

import pytest
from opentelemetry.trace import SpanKind, StatusCode

from goe.filesystem.goe_dfs import CloudStorageDfsAdapter
from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.storage import traced_storage_call


class FakeStorage:
    """Minimal storage class exercising the decorator."""

    _dry_run = False

    @traced_storage_call("write", "dfs_path")
    def write(self, dfs_path: str, data: str, overwrite: bool = False) -> int:
        return len(data)

    @traced_storage_call("read", "dfs_path")
    def read(self, dfs_path: str) -> str:
        raise FileNotFoundError(dfs_path)


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime for one test."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_storage_span_attributes(memory_runtime: runtime.ObservabilityRuntime) -> None:
    assert FakeStorage().write("gs://bucket/prefix/file.parquet", "abc") == 3
    span = memory_runtime.get_finished_spans()[0]
    assert span.name == "goe.storage.gs.write"
    assert span.kind == SpanKind.CLIENT
    assert span.attributes["goe.storage.bucket"] == "bucket"
    assert span.attributes["goe.storage.path"] == "prefix/file.parquet"
    assert span.attributes["goe.storage.dry_run"] is False


def test_storage_span_error(memory_runtime: runtime.ObservabilityRuntime) -> None:
    with pytest.raises(FileNotFoundError):
        FakeStorage().read(dfs_path="gs://bucket/missing")
    assert memory_runtime.get_finished_spans()[0].status.status_code == StatusCode.ERROR


def test_disabled_runtime_skips_span() -> None:
    runtime.shutdown_observability()
    assert FakeStorage().write("gs://bucket/x", "ab") == 2


def test_cloud_storage_adapter_methods_are_decorated() -> None:
    for name in ("copy_from_local", "copy_to_local", "delete", "list_dir", "read", "stat", "write"):
        assert getattr(getattr(CloudStorageDfsAdapter, name), "__goe_storage_operation__", None) == name

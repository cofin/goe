# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for StagingStorageService and CloudStorageDfsAdapter."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from goe.filesystem.goe_dfs import (
    DFS_TYPE_DIRECTORY,
    DFS_TYPE_FILE,
    CloudStorageDfsAdapter,
    GOEDfsException,
    azure_fq_container_name,
    gen_fs_uri,
    uri_component_split,
)
from goe.filesystem.storage_service import DELETE_BATCH_LIMIT, StagingStorageService
from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.offload.offload_messages import OffloadMessages


class FakeBackend:
    """In-memory storage backend stand-in recording calls and batch sizes."""

    def __init__(self, initial_objects: dict[str, bytes] | None = None) -> None:
        """Initialize fake backend state."""
        self.objects: dict[str, bytes] = dict(initial_objects or {})
        self.write_calls: list[tuple[str, dict[str, Any]]] = []
        self.list_calls: list[tuple[str, dict[str, Any]]] = []
        self.delete_calls: list[str | list[str]] = []

    def exists_sync(self, path: str, **kwargs: Any) -> bool:
        """Return whether an exact object key exists."""
        key = self._normalize_key(path)
        return key in self.objects

    def read_bytes_sync(self, path: str, **kwargs: Any) -> bytes:
        """Return raw bytes for an object key."""
        key = self._normalize_key(path)
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]

    def write_bytes_sync(self, path: str, data: bytes, **kwargs: Any) -> None:
        """Store raw bytes and record write kwargs."""
        key = self._normalize_key(path)
        self.write_calls.append((key, dict(kwargs)))
        if kwargs.get("if_generation_match") == 0 and key in self.objects:
            raise FileExistsError(f"PreconditionFailed: {key}")
        if kwargs.get("overwrite") is False and key in self.objects:
            raise FileExistsError(f"Already exists: {key}")
        self.objects[key] = bytes(data)

    def delete_sync(self, paths: str | list[str], **kwargs: Any) -> None:
        """Delete one key or a batch of keys."""
        if isinstance(paths, list):
            self.delete_calls.append(list(paths))
            for item in paths:
                self.objects.pop(self._normalize_key(item), None)
        else:
            self.delete_calls.append(paths)
            key = self._normalize_key(paths)
            if key not in self.objects:
                raise FileNotFoundError(key)
            self.objects.pop(key, None)

    def list_objects_sync(self, prefix: str = "", recursive: bool = True, **kwargs: Any) -> list[str]:
        """List matching object keys honouring max_results."""
        norm_prefix = self._normalize_key(prefix)
        self.list_calls.append((norm_prefix, dict(kwargs)))
        matches = [k for k in sorted(self.objects) if k.startswith(norm_prefix)]
        max_results = kwargs.get("max_results")
        if isinstance(max_results, int):
            return matches[:max_results]
        return matches

    @staticmethod
    def _normalize_key(path: str) -> str:
        if "://" in path:
            _, _, remainder = path.partition("://")
            _, _, key = remainder.partition("/")
            return key.lstrip("/")
        return path.lstrip("/")


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory OpenTelemetry runtime for span assertions."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_local_file_round_trip_operations(tmp_path: Path) -> None:
    """StagingStorageService executes upload, download, read, write, stat, list, and delete on file:// URIs."""
    service = StagingStorageService(messages=OffloadMessages(), dry_run=False, do_not_connect=False)
    stage_root = tmp_path / "staging"
    stage_root.mkdir(parents=True, exist_ok=True)

    source_file = tmp_path / "source.txt"
    source_file.write_bytes(b"hello-goe-storage")

    remote_uri = f"file://{stage_root}/table_a/part-0.txt"
    service.upload_file(str(source_file), remote_uri, overwrite=False)

    stat_file = service.stat_uri(remote_uri)
    assert stat_file is not None
    assert stat_file.entry_type == DFS_TYPE_FILE
    assert stat_file.length == len(b"hello-goe-storage")

    dir_uri = f"file://{stage_root}/table_a"
    stat_dir = service.stat_uri(dir_uri)
    assert stat_dir is not None
    assert stat_dir.entry_type == DFS_TYPE_DIRECTORY

    assert service.read_bytes(remote_uri) == b"hello-goe-storage"

    downloaded = tmp_path / "downloaded.txt"
    service.download_file(remote_uri, str(downloaded), overwrite=False)
    assert downloaded.read_bytes() == b"hello-goe-storage"

    with pytest.raises(GOEDfsException, match="Cannot copy file over existing file"):
        service.download_file(remote_uri, str(downloaded), overwrite=False)

    second_uri = f"file://{stage_root}/table_a/part-1.txt"
    service.write_bytes(second_uri, "second-payload", overwrite=False)
    assert service.read_bytes(second_uri) == b"second-payload"

    listed = service.list_prefix(dir_uri)
    assert len(listed) == 2

    assert service.delete_prefix(second_uri, recursive=False) is True
    assert service.stat_uri(second_uri) is None
    assert service.delete_prefix(second_uri, recursive=False) is None

    assert service.delete_prefix(dir_uri, recursive=True) is True
    assert service.stat_uri(remote_uri) is None


def test_overwrite_false_raises_on_existing_target(tmp_path: Path) -> None:
    """upload_file and write_bytes raise GOEDfsException when overwrite=False and object exists."""
    service = StagingStorageService(messages=OffloadMessages(), dry_run=False, do_not_connect=False)
    target_uri = f"file://{tmp_path}/existing.parquet"
    service.write_bytes(target_uri, b"initial", overwrite=False)

    with pytest.raises(GOEDfsException, match="Cannot write to existing file"):
        service.write_bytes(target_uri, b"updated", overwrite=False)

    local_src = tmp_path / "src.parquet"
    local_src.write_bytes(b"from-local")
    with pytest.raises(GOEDfsException, match="Cannot copy file over existing file"):
        service.upload_file(str(local_src), target_uri, overwrite=False)

    service.write_bytes(target_uri, b"overwritten", overwrite=True)
    assert service.read_bytes(target_uri) == b"overwritten"


def test_dry_run_skips_mutating_operations(tmp_path: Path) -> None:
    """dry_run=True performs no writes or deletes while keeping read/stat operational."""
    seed_file = tmp_path / "seed.txt"
    seed_file.write_bytes(b"seed-bytes")
    seed_uri = f"file://{seed_file}"

    dry_service = StagingStorageService(messages=OffloadMessages(), dry_run=True, do_not_connect=False)
    new_uri = f"file://{tmp_path}/never-written.txt"
    dry_service.write_bytes(new_uri, b"ignored", overwrite=False)
    assert dry_service.stat_uri(new_uri) is None

    assert dry_service.stat_uri(seed_uri) is not None
    assert dry_service.delete_prefix(seed_uri, recursive=False) is True
    assert seed_file.exists()


def test_gcs_if_generation_match_and_bounded_stat_probe() -> None:
    """GCS writes pass if_generation_match=0 when overwrite=False and stat_uri bounds list probe with max_results=2."""
    backend = FakeBackend({"stage/table/part-0.parquet": b"abc", "stage/table/part-1.parquet": b"def"})
    service = StagingStorageService(
        messages=OffloadMessages(),
        dry_run=False,
        do_not_connect=True,
        backend_overrides={"gs://my-bucket": backend},
    )

    service.write_bytes("gs://my-bucket/stage/table/new.parquet", b"xyz", overwrite=False)
    assert backend.write_calls[-1][1].get("if_generation_match") == 0

    with pytest.raises(GOEDfsException, match="Cannot write to existing file"):
        service.write_bytes("gs://my-bucket/stage/table/part-0.parquet", b"dup", overwrite=False)

    stat_dir = service.stat_uri("gs://my-bucket/stage/table")
    assert stat_dir is not None
    assert stat_dir.entry_type == DFS_TYPE_DIRECTORY
    assert backend.list_calls[-1][1].get("max_results") == 2


def test_delete_prefix_chunks_large_keysets_in_batches_of_1000() -> None:
    """delete_prefix chunks 2500 keys under a prefix into 1000, 1000, and 500 batch delete calls."""
    initial = {f"stage/big/part-{i:04d}.parquet": b"x" for i in range(2500)}
    backend = FakeBackend(initial)
    service = StagingStorageService(
        messages=OffloadMessages(),
        dry_run=False,
        do_not_connect=True,
        backend_overrides={"s3://my-bucket": backend},
    )

    assert DELETE_BATCH_LIMIT == 1000
    assert service.delete_prefix("s3://my-bucket/stage/big", recursive=True) is True
    batch_lengths = [len(call) for call in backend.delete_calls if isinstance(call, list)]
    assert batch_lengths == [1000, 1000, 500]
    assert len(backend.objects) == 0


def test_cloud_storage_dfs_adapter_emits_single_storage_span(
    memory_runtime: runtime.ObservabilityRuntime,
) -> None:
    """CloudStorageDfsAdapter delegates to StagingStorageService and emits exactly one span per call."""
    backend = FakeBackend()
    service = StagingStorageService(
        messages=OffloadMessages(),
        dry_run=False,
        do_not_connect=True,
        backend_overrides={"gs://span-bucket": backend},
    )
    adapter = CloudStorageDfsAdapter(
        messages=OffloadMessages(),
        dry_run=False,
        do_not_connect=True,
        scheme="gs",
        storage_service=service,
    )

    adapter.write("gs://span-bucket/path/obj.parquet", b"payload", overwrite=True)
    spans = memory_runtime.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "goe.storage.gs.write"


def test_uri_helpers_and_azure_container_formatting() -> None:
    """uri_component_split, gen_fs_uri, and azure_fq_container_name preserve URI contracts."""
    assert uri_component_split("s3a://bucket/dir/file.parquet") == ("s3a", "bucket", "/dir/file.parquet")
    assert gen_fs_uri("stage", scheme="gs", container="bkt", backend_db="db", table_name="tbl") == (
        "gs://bkt/stage/db/tbl"
    )
    assert azure_fq_container_name("acct", "blob.core.windows.net", "cnt", scheme="wasb") == (
        "cnt@acct.blob.core.windows.net"
    )
    assert azure_fq_container_name("acct", "dfs.core.windows.net", "cnt", scheme="abfs") == (
        "cnt@acct.dfs.core.windows.net"
    )
    assert azure_fq_container_name("acct", "dfs.core.windows.net", "cnt", scheme="adl") == (
        "acct.dfs.core.windows.net/cnt"
    )

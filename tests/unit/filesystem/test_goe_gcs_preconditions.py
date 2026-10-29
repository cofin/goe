# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Characterization of CloudStorageDfsAdapter (GCS) upload and delete contracts against an in-memory GCS fake."""

from unittest.mock import patch

import pytest
from google.api_core import exceptions as google_exceptions

from goe.filesystem import storage_service
from goe.filesystem.goe_dfs import CloudStorageDfsAdapter, GOEDfsException
from goe.filesystem.storage_service import StagingStorageService
from goe.offload.offload_messages import OffloadMessages


class FakeBlob:
    """Blob stand-in backed by FakeBucket.objects; counts exists() calls."""

    def __init__(self, bucket: "FakeBucket", name: str, kms_key_name: str | None = None) -> None:
        """Bind the blob to its bucket."""
        self.bucket = bucket
        self.name = name
        self.kms_key_name = kms_key_name
        self.size = 1

    def exists(self) -> bool:
        """Report whether the object is live."""
        self.bucket.exists_calls += 1
        return self.name in self.bucket.objects

    def upload_from_filename(self, filename: str, if_generation_match: int | None = None) -> None:
        """Upload from a local file."""
        self._store(if_generation_match)

    def upload_from_string(self, data: object, if_generation_match: int | None = None) -> None:
        """Upload from memory."""
        self._store(if_generation_match)

    def delete(self) -> None:
        """Delete the object or raise NotFound."""
        if self.name not in self.bucket.objects:
            raise google_exceptions.NotFound("missing")
        self.bucket.objects.discard(self.name)

    def _store(self, if_generation_match: int | None) -> None:
        """Store the object honouring ifGenerationMatch=0."""
        if if_generation_match == 0 and self.name in self.bucket.objects:
            raise google_exceptions.PreconditionFailed("object exists")
        self.bucket.objects.add(self.name)


class FakeBucket:
    """Bucket stand-in holding object names."""

    def __init__(self, objects: set[str]) -> None:
        """Seed the bucket."""
        self.objects = set(objects)
        self.exists_calls = 0

    def blob(self, name: str) -> FakeBlob:
        """Return a blob handle."""
        return FakeBlob(self, name)

    def get_blob(self, name: str) -> FakeBlob | None:
        """Return a blob handle if the object exists, else None."""
        if name in self.objects:
            return FakeBlob(self, name)
        return None

    def delete_blob(self, name: str) -> None:
        """Delete one object by name."""
        FakeBlob(self, name).delete()

    def delete_blobs(self, blobs: list[FakeBlob], on_error=None) -> None:
        """Delete blobs, calling on_error for NotFound."""
        for blob in blobs:
            try:
                blob.delete()
            except google_exceptions.NotFound:
                if on_error is None:
                    raise
                on_error(blob)


class FakeClient:
    """Storage client stand-in."""

    def __init__(self, bucket: FakeBucket) -> None:
        """Wrap one bucket."""
        self.bucket = bucket

    def get_bucket(self, name: str) -> FakeBucket:
        """Return the bucket."""
        return self.bucket

    def list_blobs(
        self,
        bucket: FakeBucket | str,
        prefix: str = "",
        delimiter: str | None = None,
        max_results: int | None = None,
    ) -> list[FakeBlob]:
        """List blobs by prefix."""
        target = self.bucket if isinstance(bucket, str) else bucket
        matches = [FakeBlob(target, n) for n in sorted(target.objects) if n.startswith(prefix)]
        if max_results is not None:
            return matches[:max_results]
        return matches


def test_copy_without_overwrite_onto_existing_raises() -> None:
    """No-overwrite copy onto a live object raises GOEDfsException."""
    gcs, _ = _gcs({"stage/part-0.parquet"})
    with pytest.raises(GOEDfsException, match="Cannot copy file over existing file"):
        gcs.copy_from_local("/tmp/part-0.parquet", "gs://b/stage/part-0.parquet", overwrite=False)


def test_copy_creates_and_overwrites() -> None:
    """Copies create new objects and overwrite when requested."""
    gcs, bucket = _gcs({"stage/part-0.parquet"})
    gcs.copy_from_local("/tmp/part-1.parquet", "gs://b/stage/part-1.parquet", overwrite=False)
    gcs.copy_from_local("/tmp/part-0.parquet", "gs://b/stage/part-0.parquet", overwrite=True)
    assert bucket.objects == {"stage/part-0.parquet", "stage/part-1.parquet"}


def test_write_without_overwrite_onto_existing_raises() -> None:
    """No-overwrite write onto a live object raises GOEDfsException."""
    gcs, _ = _gcs({"stage/ddl.sql"})
    with pytest.raises(GOEDfsException, match="Cannot write to existing file"):
        gcs.write("gs://b/stage/ddl.sql", "SELECT 1", overwrite=False)


def test_single_delete_returns_true_or_none() -> None:
    """Single-object delete returns True, or None when the object is absent."""
    gcs, bucket = _gcs({"stage/part-0.parquet"})
    assert gcs.delete("gs://b/stage/part-0.parquet") is True
    assert bucket.objects == set()
    assert gcs.delete("gs://b/stage/part-0.parquet") is None


def test_recursive_delete_removes_prefix() -> None:
    """Recursive delete removes every object under the prefix and returns True."""
    gcs, bucket = _gcs({"stage/t/part-0.parquet", "stage/t/part-1.parquet", "stage/other.parquet"})
    assert gcs.delete("gs://b/stage/t", recursive=True) is True
    assert bucket.objects == {"stage/other.parquet"}
    assert gcs.delete("gs://b/stage/empty", recursive=True) is True


def test_no_existence_round_trips_or_delete_waits() -> None:
    """Uploads and deletes issue no exists() calls and never wait after deleting."""
    gcs, bucket = _gcs({"stage/t/part-0.parquet"})
    with patch.object(StagingStorageService, "_post_cloud_delete_wait"):
        gcs.copy_from_local("/tmp/part-1.parquet", "gs://b/stage/t/part-1.parquet", overwrite=False)
        gcs.write("gs://b/stage/t/ddl.sql", "SELECT 1", overwrite=False)
        gcs.delete("gs://b/stage/t", recursive=True)
    assert bucket.exists_calls == 0


def _gcs(objects: set[str]) -> tuple[CloudStorageDfsAdapter, FakeBucket]:
    """Return an executing CloudStorageDfsAdapter bound to a fake bucket."""
    gcs = CloudStorageDfsAdapter(OffloadMessages(), scheme="gs", dry_run=False, do_not_connect=True)
    bucket = FakeBucket(objects)
    gcs._client = FakeClient(bucket)
    return gcs, bucket


@pytest.fixture(autouse=True)
def _patch_blob_and_sleep():
    """Bind storage.Blob to FakeBlob and neutralise post-delete sleep."""
    with (
        patch.object(
            storage_service.storage,
            "Blob",
            side_effect=lambda name, bucket, kms_key_name=None: FakeBlob(bucket, name, kms_key_name=kms_key_name),
        ),
        patch.object(StagingStorageService, "_post_cloud_delete_wait"),
    ):
        yield

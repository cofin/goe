# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unified staging storage service backed by sqlspec.storage and cloud SDKs."""

from __future__ import annotations

import logging
import time
from os.path import basename
from os.path import exists as file_exists
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
import google.cloud.storage as storage
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from botocore.exceptions import ClientError
from google.api_core import exceptions as google_exceptions
from google.api_core import retry
from sqlspec.storage import storage_registry
from sqlspec.storage.backends import FSSpecBackend, LocalStore, ObjectStoreBase, ObStoreBackend

from goe.config.gcp_credentials import resolve_gcp_credentials
from goe.observability.storage import traced_storage_call
from goe.typing import FrozenBaseStruct
from goe.util.string_utils import add_suffix_in_same_case

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

DELETE_BATCH_LIMIT = 1000
DFS_RETRY_TIMEOUT = 60

GOE_DFS_GCS = "GOEGcs"
GOE_DFS_S3 = "GOES3"
GOE_DFS_AZURE = "GOEAzure"
GOE_DFS_LOCAL = "GOELocal"

OFFLOAD_FS_SCHEME_GS = "gs"
OFFLOAD_FS_SCHEME_S3 = "s3"
OFFLOAD_FS_SCHEME_S3A = "s3a"
OFFLOAD_FS_SCHEME_ADL = "adl"
OFFLOAD_FS_SCHEME_WASB = "wasb"
OFFLOAD_FS_SCHEME_WASBS = "wasbs"
OFFLOAD_FS_SCHEME_ABFS = "abfs"
OFFLOAD_FS_SCHEME_ABFSS = "abfss"
OFFLOAD_FS_SCHEME_AZ = "az"
OFFLOAD_FS_SCHEME_AZURE = "azure"
OFFLOAD_FS_SCHEME_FILE = "file"
OFFLOAD_FS_SCHEME_HDFS = "hdfs"
OFFLOAD_FS_SCHEME_INHERIT = "inherit"

UNSUPPORTED_URI_SCHEME_EXCEPTION_TEXT = "Unsupported URI scheme"

VALID_OFFLOAD_FS_SCHEMES = [
    OFFLOAD_FS_SCHEME_INHERIT,
    OFFLOAD_FS_SCHEME_GS,
    OFFLOAD_FS_SCHEME_HDFS,
    OFFLOAD_FS_SCHEME_S3A,
    OFFLOAD_FS_SCHEME_S3,
    OFFLOAD_FS_SCHEME_WASB,
    OFFLOAD_FS_SCHEME_WASBS,
    OFFLOAD_FS_SCHEME_ADL,
    OFFLOAD_FS_SCHEME_ABFS,
    OFFLOAD_FS_SCHEME_ABFSS,
]

CLOUD_STORAGE_SCHEMES: frozenset[str] = frozenset(
    {
        OFFLOAD_FS_SCHEME_GS,
        OFFLOAD_FS_SCHEME_S3,
        OFFLOAD_FS_SCHEME_S3A,
        OFFLOAD_FS_SCHEME_ADL,
        OFFLOAD_FS_SCHEME_WASB,
        OFFLOAD_FS_SCHEME_WASBS,
        OFFLOAD_FS_SCHEME_ABFS,
        OFFLOAD_FS_SCHEME_ABFSS,
        OFFLOAD_FS_SCHEME_AZ,
        OFFLOAD_FS_SCHEME_FILE,
    }
)
AZURE_STORAGE_SCHEMES: frozenset[str] = frozenset(
    {
        OFFLOAD_FS_SCHEME_ADL,
        OFFLOAD_FS_SCHEME_WASB,
        OFFLOAD_FS_SCHEME_WASBS,
        OFFLOAD_FS_SCHEME_ABFS,
        OFFLOAD_FS_SCHEME_ABFSS,
        OFFLOAD_FS_SCHEME_AZ,
    }
)
S3_STORAGE_SCHEMES: frozenset[str] = frozenset(
    {
        OFFLOAD_FS_SCHEME_S3,
        OFFLOAD_FS_SCHEME_S3A,
    }
)

URI_SEP = "/"
DFS_TYPE_FILE = "FILE"
DFS_TYPE_DIRECTORY = "DIRECTORY"


class GOEDfsException(Exception):
    """Base exception raised by GOE filesystem and staging storage operations."""


class GOEDfsDeleteError(Exception):
    """Exception raised when a filesystem delete operation fails."""


class GOEDfsDeleteNotComplete(Exception):
    """Transient exception raised when cloud object deletion is still propagating."""


class GOEDfsFilesNotVisible(Exception):
    """Transient exception raised when staged files are not yet visible due to eventual consistency."""


class GOEAzureTryAgainException(Exception):
    """Transient exception raised when Azure Blob listing times out."""


def uri_component_split(dfs_path: str) -> tuple[str, str, str]:
    """Split a filesystem URI into (scheme, container/netloc, path) and validate supported schemes."""
    assert dfs_path
    assert isinstance(dfs_path, str)
    tokens = urlparse(dfs_path, allow_fragments=False)
    scheme = tokens.scheme.lower()
    if scheme and scheme not in (*VALID_OFFLOAD_FS_SCHEMES, OFFLOAD_FS_SCHEME_FILE, OFFLOAD_FS_SCHEME_AZ):
        raise GOEDfsException(f"{UNSUPPORTED_URI_SCHEME_EXCEPTION_TEXT}: {scheme}")
    return scheme, tokens.netloc, tokens.path


def gen_fs_uri(
    path_prefix: str,
    db_path_suffix: str | None = None,
    scheme: str | None = None,
    container: str | None = None,
    backend_db: str | None = None,
    table_name: str | None = None,
) -> str:
    """Construct a storage URI from scheme, container, prefix, database, and table components."""
    assert path_prefix is not None
    assert isinstance(path_prefix, str)
    if container:
        assert isinstance(container, str)
    if backend_db:
        assert isinstance(backend_db, str)
    if table_name:
        assert isinstance(table_name, str)
    scheme_prefix = f"{scheme}://" if scheme else ""
    container_str = container or ""
    if scheme and not path_prefix.startswith("/"):
        path_prefix = "/" + path_prefix
    if backend_db and db_path_suffix:
        backend_db = add_suffix_in_same_case(backend_db, db_path_suffix)
    uri_elements = [el.strip(URI_SEP) for el in [backend_db, table_name] if el is not None and el != ""]
    path = URI_SEP.join(uri_elements)
    if path_prefix.endswith(URI_SEP):
        path = path_prefix + path
    elif path:
        path = path_prefix + URI_SEP + path
    else:
        path = path_prefix
    return scheme_prefix + container_str + path


def azure_fq_container_name(
    azure_account_name: str | None,
    azure_account_domain: str | None,
    container: str,
    account_in_path: bool = False,
    scheme: str | None = None,
) -> str:
    """Return a fully qualified Azure container name (container@account.domain or account.domain/container)."""
    assert azure_account_name
    assert azure_account_domain
    domain = azure_account_domain if azure_account_domain.startswith(".") else "." + azure_account_domain
    fq_account = azure_account_name + domain
    if account_in_path or (scheme and scheme.lower() == OFFLOAD_FS_SCHEME_ADL):
        return fq_account + URI_SEP + container
    return container + "@" + fq_account


class StorageObjectStat(FrozenBaseStruct, frozen=True):
    """Metadata stat record for a staged storage object or directory prefix."""

    uri: str
    object_type: str
    length: int | None = None
    permission: str | None = None

    @property
    def entry_type(self) -> str:
        """Return the normalized entry type (DIRECTORY or FILE)."""
        return self.object_type

    def to_stat_dict(self) -> dict[str, Any]:
        """Convert to the dictionary contract returned by GOEDfs.stat()."""
        return {
            "length": self.length,
            "permission": self.permission,
            "type": self.object_type,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Look up a stat key with dict compatibility."""
        return self.to_stat_dict().get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Index a stat key with dict compatibility."""
        return self.to_stat_dict()[key]


class StagingStorageService:
    """Unified cloud and local staging storage service backed by sqlspec.storage and cloud SDKs."""

    def __init__(
        self,
        messages: Any,
        *,
        scheme: str = OFFLOAD_FS_SCHEME_FILE,
        container: str | None = None,
        dry_run: bool = False,
        do_not_connect: bool = False,
        db_path_suffix: str | None = None,
        google_kms_key_name: str | None = None,
        azure_account_name: str | None = None,
        azure_account_key: str | None = None,
        azure_account_domain: str | None = None,
        config: Any = None,
        client: Any = None,
        backend_store: ObjectStoreBase | LocalStore | Any | None = None,
        backend_overrides: dict[str, Any] | None = None,
        local_root: str | Path | None = None,
    ) -> None:
        assert messages is not None
        self._messages = messages
        self._scheme = (scheme or OFFLOAD_FS_SCHEME_FILE).lower()
        self._container = container
        self._dry_run = bool(dry_run)
        self._do_not_connect = bool(do_not_connect)
        self._db_path_suffix = db_path_suffix
        self._google_kms_key_name = google_kms_key_name
        self._azure_account_name = azure_account_name
        self._azure_account_key = azure_account_key
        if azure_account_domain and not azure_account_domain.startswith("."):
            azure_account_domain = "." + azure_account_domain
        self._azure_account_domain = azure_account_domain
        self._config = config
        self._backend_store: ObjectStoreBase | LocalStore | Any | None = backend_store
        self._backend_overrides: dict[str, Any] = dict(backend_overrides or {})
        self._local_root = Path(local_root) if local_root is not None else Path("/")

        if self._scheme == OFFLOAD_FS_SCHEME_GS:
            self.dfs_mechanism = GOE_DFS_GCS
            self.backend_dfs = "GCS"
        elif self._scheme in S3_STORAGE_SCHEMES:
            self.dfs_mechanism = GOE_DFS_S3
            self.backend_dfs = "S3"
        elif self._scheme in AZURE_STORAGE_SCHEMES:
            self.dfs_mechanism = GOE_DFS_AZURE
            self.backend_dfs = "Azure"
        else:
            self.dfs_mechanism = GOE_DFS_LOCAL
            self.backend_dfs = "Local"

        if client is not None:
            self._client: Any = client
        elif self._do_not_connect or self._backend_overrides or self._scheme == OFFLOAD_FS_SCHEME_FILE:
            self._client = None
        else:
            self._client = self._initialize_client()

        if self._backend_store is None and self._scheme == OFFLOAD_FS_SCHEME_FILE:
            self._backend_store = LocalStore(str(self._local_root))

    @property
    def client(self) -> Any:
        """Return the underlying cloud SDK client or sqlspec backend store."""
        return self._client if self._client is not None else self._backend_store

    @property
    def sqlspec_store(self) -> ObjectStoreBase | LocalStore | Any | None:
        """Return the underlying sqlspec.storage backend store when configured."""
        return self._backend_store

    @staticmethod
    def resolve_sqlspec_backend(uri: str, **kwargs: Any) -> ObjectStoreBase | LocalStore | Any:
        """Resolve a sqlspec.storage backend store for a given URI."""
        parsed = urlparse(uri)
        if parsed.scheme in ("", OFFLOAD_FS_SCHEME_FILE):
            base_dir = parsed.path or "/"
            return LocalStore(base_dir)
        return storage_registry.get(uri, **kwargs)

    def debug(self, msg: str) -> None:
        """Log a debug message through OffloadMessages."""
        self._messages.debug(msg)

    def log(self, msg: str, detail: Any = None) -> None:
        """Log an informational message through OffloadMessages."""
        self._messages.log(msg, detail=detail)

    def container_exists(self, scheme: str, container: str) -> bool:
        """Return True if the target cloud bucket or container exists."""
        assert container
        norm_scheme = (scheme or self._scheme).lower()
        if norm_scheme == OFFLOAD_FS_SCHEME_FILE:
            return Path(container).exists() if container else True
        if not self._client:
            return False
        if norm_scheme == OFFLOAD_FS_SCHEME_GS:
            return bool(self._gcs_bucket(container))
        if norm_scheme in S3_STORAGE_SCHEMES:
            try:
                self._client.meta.client.head_bucket(Bucket=container)
                return True
            except ClientError as exc:
                error_code = int(exc.response["Error"]["Code"])
                if error_code in (403, 404):
                    return False
                raise
        if norm_scheme in AZURE_STORAGE_SCHEMES:
            return self._azure_container_exists(container)
        return False

    @traced_storage_call("copy_from_local", "remote_uri")
    def upload_file(self, local_path: str, remote_uri: str, *, overwrite: bool = False) -> bool | None:
        """Upload a local file to a remote staging URI."""
        return self._upload_file_impl(local_path, remote_uri, overwrite=overwrite)

    @traced_storage_call("copy_to_local", "remote_uri")
    def download_file(self, remote_uri: str, local_path: str, *, overwrite: bool = False) -> None:
        """Download a remote staging URI to a local file path."""
        self._download_file_impl(remote_uri, local_path, overwrite=overwrite)

    @traced_storage_call("read", "remote_uri")
    def read_bytes(self, remote_uri: str, *, as_str: bool = False) -> bytes | str | None:
        """Read the payload of a remote staging URI as bytes or UTF-8 string."""
        return self._read_bytes_impl(remote_uri, as_str=as_str)

    @traced_storage_call("write", "remote_uri")
    def write_bytes(self, remote_uri: str, data: str | bytes, *, overwrite: bool = False) -> None:
        """Write bytes or text data directly to a remote staging URI."""
        self._write_bytes_impl(remote_uri, data, overwrite=overwrite)

    @traced_storage_call("stat", "remote_uri")
    def stat_uri(self, remote_uri: str) -> StorageObjectStat | None:
        """Return StorageObjectStat metadata for a remote file or directory URI, or None when absent."""
        raw = self._stat_uri_impl(remote_uri)
        if raw is None:
            return None
        if isinstance(raw, StorageObjectStat):
            return raw
        return StorageObjectStat(
            uri=remote_uri,
            object_type=raw.get("type", DFS_TYPE_FILE),
            length=raw.get("length"),
            permission=raw.get("permission"),
        )

    @traced_storage_call("list_dir", "remote_uri")
    def list_prefix(self, remote_uri: str) -> list[str] | None:
        """List child URIs immediately within remote_uri."""
        return self._list_prefix_impl(remote_uri)

    @traced_storage_call("delete", "remote_uri")
    def delete_prefix(self, remote_uri: str, *, recursive: bool = False) -> bool | None:
        """Delete a single object or recursively delete a directory prefix in 1000-key batches."""
        return self._delete_prefix_impl(remote_uri, recursive=recursive)

    def gen_uri(
        self,
        scheme: str,
        container: str,
        path_prefix: str,
        backend_db: str | None = None,
        table_name: str | None = None,
        container_override: str | None = None,
    ) -> str:
        """Generate a normalized URI for the configured storage scheme."""
        norm_scheme = (scheme or self._scheme).lower()
        if norm_scheme in AZURE_STORAGE_SCHEMES and self._azure_account_name and self._azure_account_domain:
            fq_container = container_override or azure_fq_container_name(
                self._azure_account_name, self._azure_account_domain, container
            )
            return gen_fs_uri(
                path_prefix,
                self._db_path_suffix,
                scheme=scheme,
                container=fq_container,
                backend_db=backend_db,
                table_name=table_name,
            )
        return gen_fs_uri(
            path_prefix,
            self._db_path_suffix,
            scheme=scheme,
            container=container_override or container,
            backend_db=backend_db,
            table_name=table_name,
        )

    def _initialize_client(self) -> Any:
        if self._scheme == OFFLOAD_FS_SCHEME_GS:
            bundle = resolve_gcp_credentials(self._config)
            if bundle.project:
                return storage.Client(credentials=bundle.credentials, project=bundle.project)
            return storage.Client(credentials=bundle.credentials)
        if self._scheme in S3_STORAGE_SCHEMES:
            return boto3.resource("s3")
        if self._scheme in AZURE_STORAGE_SCHEMES:
            assert self._azure_account_name, "Azure account name is required"
            assert self._azure_account_key, "Azure account key is required"
            azure_url = f"https://{self._azure_account_name}{self._azure_account_domain or ''}"
            return BlobServiceClient(account_url=azure_url, credential=self._azure_account_key)
        return None

    def _resolve_active_store(self, scheme: str, container: str) -> Any:
        norm_scheme = scheme.lower()
        if container:
            uri_key = f"{norm_scheme}://{container}"
            if uri_key in self._backend_overrides:
                return self._backend_overrides[uri_key]
        if norm_scheme in self._backend_overrides:
            return self._backend_overrides[norm_scheme]
        if norm_scheme != OFFLOAD_FS_SCHEME_FILE and self._backend_store is not None and self._client is None:
            if not isinstance(self._backend_store, LocalStore):
                return self._backend_store
        return None

    def _uri_component_split(self, dfs_path: str) -> tuple[str, str, str]:
        scheme, container, path = uri_component_split(dfs_path)
        norm_scheme = (scheme or self._scheme).lower()
        if norm_scheme in (OFFLOAD_FS_SCHEME_GS, *S3_STORAGE_SCHEMES, *AZURE_STORAGE_SCHEMES):
            if path and path.startswith(URI_SEP):
                path = path.lstrip(URI_SEP)
        if norm_scheme in AZURE_STORAGE_SCHEMES and container and "@" in container:
            container = container.split("@")[0]
        return scheme or self._scheme, container, path

    def _upload_file_impl(self, local_path: str, dfs_path: str, *, overwrite: bool = False) -> bool | None:
        assert local_path
        assert dfs_path
        assert isinstance(local_path, str)
        assert isinstance(dfs_path, str)
        logger.info("copy_from_local(%s, %s)", local_path, dfs_path)
        scheme, container, path = self._uri_component_split(dfs_path)
        norm_scheme = scheme.lower()
        if norm_scheme == OFFLOAD_FS_SCHEME_FILE:
            return self._local_upload(local_path, path, overwrite=overwrite)

        target_path = (path + basename(local_path)) if path.endswith(URI_SEP) else path
        self.debug(f"Copying to target scheme/container/path: {[scheme, container, target_path]!s}")
        if self._dry_run:
            return None

        active_store = self._resolve_active_store(norm_scheme, container)
        if active_store is not None:
            payload = Path(local_path).read_bytes()
            write_kwargs: dict[str, Any] = (
                {"if_generation_match": 0}
                if (norm_scheme == OFFLOAD_FS_SCHEME_GS and not overwrite)
                else {"overwrite": overwrite}
            )
            try:
                active_store.write_bytes_sync(target_path, payload, **write_kwargs)
            except FileExistsError as exc:
                raise GOEDfsException(f"Cannot copy file over existing file: {target_path}") from exc
            except TypeError:
                if not overwrite and active_store.exists_sync(target_path):
                    raise GOEDfsException(f"Cannot copy file over existing file: {target_path}")
                active_store.write_bytes_sync(target_path, payload)
            return True

        if norm_scheme == OFFLOAD_FS_SCHEME_GS:
            bucket = self._gcs_bucket(container)
            if not bucket:
                raise GOEDfsException(f"Bucket does not exist: {container}")
            blob = self._gcs_new_blob(bucket, target_path)
            if_generation_match = None if overwrite else 0
            try:
                blob.upload_from_filename(local_path, if_generation_match=if_generation_match)
            except google_exceptions.PreconditionFailed as exc:
                raise GOEDfsException(f"Cannot copy file over existing file: {target_path}") from exc
            return True

        if norm_scheme in S3_STORAGE_SCHEMES:
            if self._s3_blob_exists(container, target_path) and not overwrite:
                raise GOEDfsException(f"Cannot copy file over existing file: {target_path}")
            s3_bucket = self._client.Bucket(container)
            s3_bucket.upload_file(Filename=local_path, Key=target_path)
            return True

        if norm_scheme in AZURE_STORAGE_SCHEMES:
            if not self._azure_container_exists(container):
                raise GOEDfsException(f"Container does not exist: {container}")
            if self._azure_blob_exists(container, target_path) and not overwrite:
                raise GOEDfsException(f"Cannot copy file over existing file: {target_path}")
            container_client = self._client.get_container_client(container)
            with open(local_path, "rb") as handle:
                container_client.upload_blob(name=target_path, data=handle, overwrite=overwrite)
            return True

        raise GOEDfsException(f"Unsupported storage scheme: {scheme}")

    def _download_file_impl(self, dfs_path: str, local_path: str, *, overwrite: bool = False) -> None:
        assert dfs_path
        assert local_path
        assert isinstance(dfs_path, str)
        assert isinstance(local_path, str)
        logger.info("copy_to_local(%s, %s)", dfs_path, local_path)
        scheme, container, path = self._uri_component_split(dfs_path)
        norm_scheme = scheme.lower()
        self.debug(f"Copying from scheme/container/path: {[scheme, container, path]!s}")
        if self._dry_run:
            return

        if norm_scheme == OFFLOAD_FS_SCHEME_FILE:
            self._local_download(path, local_path, overwrite=overwrite)
            return

        active_store = self._resolve_active_store(norm_scheme, container)
        if active_store is not None:
            if file_exists(local_path) and not overwrite:
                raise GOEDfsException(f"Cannot copy file over existing file: {local_path}")
            data = active_store.read_bytes_sync(path)
            Path(local_path).write_bytes(data)
            return

        if norm_scheme == OFFLOAD_FS_SCHEME_GS:
            if file_exists(local_path) and not overwrite:
                raise GOEDfsDeleteError(f"Cannot copy file over existing file: {local_path}")
            bucket = self._gcs_bucket(container)
            if not bucket:
                raise GOEDfsException(f"Bucket does not exist: {container}")
            blob = bucket.get_blob(path)
            if not blob:
                raise GOEDfsException(f"Cannot download non-existent file: {path}")
            blob.download_to_filename(local_path)
            return

        if norm_scheme in S3_STORAGE_SCHEMES:
            if file_exists(local_path) and not overwrite:
                raise GOEDfsException(f"Cannot copy file over existing file: {local_path}")
            s3_bucket = self._client.Bucket(container)
            s3_bucket.download_file(Key=path, Filename=local_path)
            return

        if norm_scheme in AZURE_STORAGE_SCHEMES:
            if file_exists(local_path) and not overwrite:
                raise GOEDfsException(f"Cannot copy file over existing file: {local_path}")
            blob_client = self._client.get_blob_client(container, blob=path)
            with open(local_path, "wb") as handle:
                stream = blob_client.download_blob()
                handle.write(stream.readall())
            return

        raise GOEDfsException(f"Unsupported storage scheme: {scheme}")

    def _read_bytes_impl(self, dfs_path: str, *, as_str: bool = False) -> bytes | str | None:
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("read(%s)", dfs_path)
        scheme, container, path = self._uri_component_split(dfs_path)
        norm_scheme = scheme.lower()
        self.debug(f"Downloading contents of scheme/container/path: {[scheme, container, path]!s}")
        if self._dry_run:
            return None

        if norm_scheme == OFFLOAD_FS_SCHEME_FILE:
            store = self._ensure_local_store()
            rel_path = self._local_relative_path(path)
            if not store.exists_sync(rel_path):
                raise GOEDfsException(f"Cannot download non-existent file: {path}")
            return store.read_text_sync(rel_path) if as_str else store.read_bytes_sync(rel_path)

        active_store = self._resolve_active_store(norm_scheme, container)
        if active_store is not None:
            if not active_store.exists_sync(path):
                raise GOEDfsException(f"Cannot download non-existent file: {path}")
            raw_bytes = active_store.read_bytes_sync(path)
            return raw_bytes.decode("utf-8") if as_str else raw_bytes

        if norm_scheme == OFFLOAD_FS_SCHEME_GS:
            bucket = self._gcs_bucket(container)
            if not bucket:
                raise GOEDfsException(f"Bucket does not exist: {container}")
            blob = bucket.get_blob(path)
            if not blob:
                raise GOEDfsException(f"Cannot download non-existent file: {path}")
            data = blob.download_as_bytes()
            return data.decode() if as_str else data

        if norm_scheme in S3_STORAGE_SCHEMES:
            try:
                s3_object = self._client.Object(container, path)
                s3_response = s3_object.get()
                if s3_response and s3_response.get("Body"):
                    content = s3_response["Body"].read()
                    return content.decode() if as_str else content
                return None
            except self._client.meta.client.exceptions.NoSuchKey as exc:
                raise GOEDfsException(f"Cannot download non-existent file: {path}") from exc

        if norm_scheme in AZURE_STORAGE_SCHEMES:
            if not self._azure_blob_exists(container, path):
                raise GOEDfsException(f"Cannot download non-existent file: {path}")
            blob_client = self._client.get_blob_client(container, blob=path)
            content = blob_client.download_blob().readall()
            return content.decode() if as_str else content

        raise GOEDfsException(f"Unsupported storage scheme: {scheme}")

    def _write_bytes_impl(self, dfs_path: str, data: str | bytes, *, overwrite: bool = False) -> None:
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("write(%s)", dfs_path)
        scheme, container, path = self._uri_component_split(dfs_path)
        norm_scheme = scheme.lower()
        self.debug(f"Writing contents of scheme/container/path: {[scheme, container, path]!s}")
        if self._dry_run:
            return

        if norm_scheme == OFFLOAD_FS_SCHEME_FILE:
            store = self._ensure_local_store()
            rel_path = self._local_relative_path(path)
            if not overwrite and store.exists_sync(rel_path):
                raise GOEDfsException(f"Cannot write to existing file: {path}")
            if isinstance(data, str):
                store.write_text_sync(rel_path, data)
            else:
                store.write_bytes_sync(rel_path, data)
            return

        active_store = self._resolve_active_store(norm_scheme, container)
        if active_store is not None:
            payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
            write_kwargs: dict[str, Any] = (
                {"if_generation_match": 0}
                if (norm_scheme == OFFLOAD_FS_SCHEME_GS and not overwrite)
                else {"overwrite": overwrite}
            )
            try:
                active_store.write_bytes_sync(path, payload, **write_kwargs)
            except FileExistsError as exc:
                raise GOEDfsException(f"Cannot write to existing file: {path}") from exc
            except TypeError:
                if not overwrite and active_store.exists_sync(path):
                    raise GOEDfsException(f"Cannot write to existing file: {path}")
                active_store.write_bytes_sync(path, payload)
            return

        if norm_scheme == OFFLOAD_FS_SCHEME_GS:
            bucket = self._gcs_bucket(container)
            if not bucket:
                raise GOEDfsException(f"Bucket does not exist: {container}")
            blob = self._gcs_new_blob(bucket, path)
            if_generation_match = None if overwrite else 0
            try:
                blob.upload_from_string(data, if_generation_match=if_generation_match)
            except google_exceptions.PreconditionFailed as exc:
                raise GOEDfsException(f"Cannot write to existing file: {path}") from exc
            return

        if norm_scheme in S3_STORAGE_SCHEMES:
            if self._s3_blob_exists(container, path) and not overwrite:
                raise GOEDfsException(f"Cannot write over existing file: {path}")
            s3_bucket = self._client.Bucket(container)
            s3_bucket.put_object(Key=path, Body=data)
            return

        if norm_scheme in AZURE_STORAGE_SCHEMES:
            if not self._azure_container_exists(container):
                raise GOEDfsException(f"Container does not exist: {container}")
            if self._azure_blob_exists(container, path) and not overwrite:
                raise GOEDfsException(f"Cannot write to existing file: {path}")
            container_client = self._client.get_container_client(container)
            container_client.upload_blob(name=path, data=data, overwrite=overwrite)
            return

        raise GOEDfsException(f"Unsupported storage scheme: {scheme}")

    @retry.Retry(
        predicate=retry.if_exception_type(GOEAzureTryAgainException),
        deadline=DFS_RETRY_TIMEOUT,
    )
    def _stat_uri_impl(self, dfs_path: str) -> dict[str, Any] | None:
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("stat(%s)", dfs_path)
        scheme, container, path = self._uri_component_split(dfs_path)
        norm_scheme = scheme.lower()

        if norm_scheme == OFFLOAD_FS_SCHEME_FILE:
            return self._local_stat(path)

        active_store = self._resolve_active_store(norm_scheme, container)
        if active_store is not None:
            clean_path = path.rstrip(URI_SEP)
            if hasattr(active_store, "is_object_sync") and active_store.is_object_sync(clean_path):
                meta = active_store.get_metadata_sync(clean_path)
                size = meta.get("size") if isinstance(meta, dict) else getattr(meta, "size", 0)
                return StorageObjectStat(uri=dfs_path, object_type=DFS_TYPE_FILE, length=size).to_stat_dict()
            if hasattr(active_store, "exists_sync") and active_store.exists_sync(clean_path):
                size = len(active_store.read_bytes_sync(clean_path))
                return StorageObjectStat(uri=dfs_path, object_type=DFS_TYPE_FILE, length=size).to_stat_dict()
            if active_store.list_objects_sync(prefix=clean_path + URI_SEP, max_results=2):
                return StorageObjectStat(uri=dfs_path, object_type=DFS_TYPE_DIRECTORY, length=None).to_stat_dict()
            return None

        if not self._client:
            return None

        self.debug(f"Checking status of scheme/container/path: {[scheme, container, path]!s}")
        path = path.rstrip(URI_SEP)

        if norm_scheme == OFFLOAD_FS_SCHEME_GS:
            if not self._gcs_bucket(container):
                raise GOEDfsException(f"Bucket does not exist: {container}")
            blobs = list(self._client.list_blobs(container, prefix=path, max_results=2))
            if len(blobs) == 1 and blobs[0].name == path:
                return {"length": blobs[0].size, "permission": None, "type": DFS_TYPE_FILE}
            dir_prefix = path + URI_SEP
            blobs = list(self._client.list_blobs(container, prefix=dir_prefix, max_results=2))
            if bool(blobs):
                return {"length": None, "permission": None, "type": DFS_TYPE_DIRECTORY}
            return None

        if norm_scheme in S3_STORAGE_SCHEMES:
            matches = self._s3_list_by_prefix(container, path)
            if path in matches:
                return matches[path]
            if path + URI_SEP in matches:
                return matches[path + URI_SEP]
            self.debug(f"Could not find path in {len(matches)} matched files")
            return None

        if norm_scheme in AZURE_STORAGE_SCHEMES:
            if not self._azure_container_exists(container):
                raise GOEDfsException(f"Container does not exist: {container}")
            try:
                blobs = self._azure_list_blobs(container, path)
            except HttpResponseError as exc:
                if "OperationTimedOut" in str(exc):
                    self.debug(f"Azure list_blobs timeout, retrying operation:\n{exc!s}")
                    raise GOEAzureTryAgainException from exc
                raise
            matched_files = [_ for _ in blobs if _.name == path]
            matched_dirs = [_ for _ in blobs if _.name == path.rstrip(URI_SEP) + URI_SEP]
            if matched_dirs:
                return {"length": 0, "permission": None, "type": DFS_TYPE_DIRECTORY}
            if len(matched_files) > 1:
                self.debug(f"Multiple file matches: {matched_files!s}")
                raise GOEDfsException(f"Path matches multiple files: {dfs_path}")
            if matched_files:
                return {
                    "length": matched_files[0].size,
                    "permission": None,
                    "type": DFS_TYPE_FILE,
                }
            return None

        return None

    def _list_prefix_impl(self, dfs_path: str) -> list[str] | None:
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("list_dir(%s)", dfs_path)
        scheme, container, path = self._uri_component_split(dfs_path)
        norm_scheme = scheme.lower()

        if norm_scheme == OFFLOAD_FS_SCHEME_FILE:
            return self._local_list_dir(path)

        if path and not path.endswith(URI_SEP):
            path += URI_SEP
        self.debug(f"Listing contents of scheme/container/path: {[scheme, container, path]!s}")

        active_store = self._resolve_active_store(norm_scheme, container)
        if active_store is not None:
            objects = active_store.list_objects_sync(prefix=path)
            return [self.gen_uri(scheme, container, str(obj)) for obj in objects if str(obj) != path]

        if not self._client:
            return None

        if norm_scheme == OFFLOAD_FS_SCHEME_GS:
            if not self._gcs_bucket(container):
                raise GOEDfsException(f"Bucket does not exist: {container}")
            blobs = list(self._client.list_blobs(container, prefix=path))
            blob_names = [_.name for _ in blobs if _.name != path]
            return [self.gen_uri(scheme, container, _) for _ in blob_names]

        if norm_scheme in S3_STORAGE_SCHEMES:
            objects = self._s3_list_by_prefix(container, path)
            if objects:
                self.debug(f"Matched objects: {len(objects)}")
                return [self.gen_uri(scheme, container, _) for _ in list(objects.keys())]
            return None

        if norm_scheme in AZURE_STORAGE_SCHEMES:
            if not self._azure_container_exists(container):
                raise GOEDfsException(f"Container does not exist: {container}")
            blob_names = self._azure_list_blob_names(container, path)
            blob_names = [_ for _ in blob_names if _ != path]
            return [self.gen_uri(scheme, container, _) for _ in blob_names]

        return None

    @retry.Retry(
        predicate=retry.if_exception_type(GOEDfsDeleteNotComplete, GOEAzureTryAgainException),
        deadline=DFS_RETRY_TIMEOUT,
    )
    def _delete_prefix_impl(self, dfs_path: str, *, recursive: bool = False) -> bool | None:
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("delete(%s, %s)", dfs_path, recursive)
        scheme, container, path = self._uri_component_split(dfs_path)
        norm_scheme = scheme.lower()
        self.debug(f"Delete scheme/container/path: {[scheme, container, path]!s}")

        if norm_scheme == OFFLOAD_FS_SCHEME_FILE:
            if self._dry_run:
                return True
            return self._local_delete(path, recursive=recursive)

        active_store = self._resolve_active_store(norm_scheme, container)
        if active_store is not None:
            if self._dry_run:
                return True
            if not recursive:
                try:
                    active_store.delete_sync(path)
                except FileNotFoundError:
                    return None
                return True
            prefix = path if path.endswith(URI_SEP) else path + URI_SEP
            keys = [str(k) for k in active_store.list_objects_sync(prefix=prefix)]
            for offset in range(0, len(keys), DELETE_BATCH_LIMIT):
                batch = keys[offset : offset + DELETE_BATCH_LIMIT]
                active_store.delete_sync(batch)
            return True

        if norm_scheme == OFFLOAD_FS_SCHEME_GS:
            return self._gcs_delete(scheme, container, path, dfs_path, recursive=recursive)
        if norm_scheme in S3_STORAGE_SCHEMES:
            return self._s3_delete(scheme, container, path, dfs_path, recursive=recursive)
        if norm_scheme in AZURE_STORAGE_SCHEMES:
            return self._azure_delete(scheme, container, path, dfs_path, recursive=recursive)

        raise GOEDfsException(f"Unsupported storage scheme: {scheme}")

    def _ensure_local_store(self) -> LocalStore:
        if isinstance(self._backend_store, LocalStore):
            return self._backend_store
        store = LocalStore(str(self._local_root))
        self._backend_store = store
        return store

    def _local_relative_path(self, raw_path: str) -> str:
        clean = raw_path
        root_str = str(self._local_root)
        if root_str != "/" and clean.startswith(root_str):
            clean = clean[len(root_str) :]
        return clean.lstrip("/")

    def _local_upload(self, local_path: str, target_uri_path: str, *, overwrite: bool = False) -> bool | None:
        store = self._ensure_local_store()
        rel_target = self._local_relative_path(target_uri_path)
        if target_uri_path.endswith(URI_SEP):
            rel_target = f"{rel_target.rstrip(URI_SEP)}/{basename(local_path)}".lstrip("/")
        if self._dry_run:
            return None
        if store.exists_sync(rel_target) and not overwrite:
            raise GOEDfsException(f"Cannot copy file over existing file: {target_uri_path}")
        payload = Path(local_path).read_bytes()
        store.write_bytes_sync(rel_target, payload)
        return True

    def _local_download(self, source_uri_path: str, local_path: str, *, overwrite: bool = False) -> None:
        store = self._ensure_local_store()
        rel_source = self._local_relative_path(source_uri_path)
        if file_exists(local_path) and not overwrite:
            raise GOEDfsException(f"Cannot copy file over existing file: {local_path}")
        if not store.exists_sync(rel_source):
            raise GOEDfsException(f"Cannot download non-existent file: {source_uri_path}")
        payload = store.read_bytes_sync(rel_source)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(payload)

    def _local_stat(self, target_uri_path: str) -> dict[str, Any] | None:
        fs_path = Path(target_uri_path)
        if not fs_path.exists():
            return None
        if fs_path.is_dir():
            return {"length": None, "permission": None, "type": DFS_TYPE_DIRECTORY}
        return {"length": fs_path.stat().st_size, "permission": None, "type": DFS_TYPE_FILE}

    def _local_list_dir(self, target_uri_path: str) -> list[str] | None:
        fs_path = Path(target_uri_path)
        if not fs_path.exists() or not fs_path.is_dir():
            return None
        return sorted(f"file://{child}" for child in fs_path.iterdir())

    def _local_delete(self, target_uri_path: str, *, recursive: bool = False) -> bool | None:
        store = self._ensure_local_store()
        fs_path = Path(target_uri_path)
        if not fs_path.exists():
            return True if recursive else None
        if fs_path.is_file():
            store.delete_sync(self._local_relative_path(target_uri_path))
            return True
        if not recursive:
            raise GOEDfsException(f"Cannot delete directory without recursive=True: {target_uri_path}")
        all_files = sorted(p for p in fs_path.rglob("*") if p.is_file())
        rel_keys = [self._local_relative_path(str(p)) for p in all_files]
        for offset in range(0, len(rel_keys), DELETE_BATCH_LIMIT):
            batch = rel_keys[offset : offset + DELETE_BATCH_LIMIT]
            for rel_key in batch:
                store.delete_sync(rel_key)
        for dir_path in sorted((p for p in fs_path.rglob("*") if p.is_dir()), reverse=True):
            if dir_path.exists():
                dir_path.rmdir()
        if fs_path.exists():
            fs_path.rmdir()
        return True

    def _post_cloud_delete_wait(self, scheme: str) -> None:
        if scheme.lower() in (
            OFFLOAD_FS_SCHEME_WASB,
            OFFLOAD_FS_SCHEME_WASBS,
            OFFLOAD_FS_SCHEME_ABFS,
            OFFLOAD_FS_SCHEME_ABFSS,
            OFFLOAD_FS_SCHEME_ADL,
            OFFLOAD_FS_SCHEME_AZ,
        ):
            time.sleep(1)

    def _gcs_bucket(self, container: str) -> Any:
        try:
            return self._client.get_bucket(container)
        except google_exceptions.NotFound:
            return None

    def _gcs_new_blob(self, bucket: Any, path: str) -> Any:
        return storage.Blob(path, bucket, kms_key_name=self._google_kms_key_name)

    def _gcs_pragmatic_delete(self, blob: Any) -> None:
        try:
            blob.delete()
        except google_exceptions.NotFound:
            self.debug(f"blob.delete({blob.name}) returned 404 (NotFound), accepting as deleted")

    def _gcs_delete(self, scheme: str, container: str, path: str, dfs_path: str, *, recursive: bool) -> bool | None:
        if not self._client:
            return None
        bucket = self._gcs_bucket(container)
        if not bucket:
            raise GOEDfsException(f"Bucket does not exist: {container}")
        if not recursive or (self._stat_uri_impl(dfs_path) or {}).get("type") == DFS_TYPE_FILE:
            blob = bucket.get_blob(path)
            if not blob:
                return None
            if not self._dry_run:
                self._gcs_pragmatic_delete(blob)
                self._post_cloud_delete_wait(scheme)
                if bucket.get_blob(path):
                    self.debug("GCS delete incomplete, retrying")
                    raise GOEDfsDeleteNotComplete
        else:
            self.debug(f"Recursive delete using directory prefix: {path}")
            prefix = path if path.endswith(URI_SEP) else path + URI_SEP
            blobs = list(self._client.list_blobs(container, prefix=prefix))
            if not self._dry_run and blobs:
                for offset in range(0, len(blobs), DELETE_BATCH_LIMIT):
                    batch = blobs[offset : offset + DELETE_BATCH_LIMIT]
                    for blob in batch:
                        self.debug(f"Deleting blob: {blob.name}")
                        self._gcs_pragmatic_delete(blob)
                self._post_cloud_delete_wait(scheme)
                if list(self._client.list_blobs(container, prefix=prefix)):
                    self.debug("GCS delete incomplete, retrying")
                    raise GOEDfsDeleteNotComplete
        return True

    def _s3_blob_exists(self, container: str, path: str) -> bool:
        s3_object = self._client.Object(container, path)
        try:
            s3_object.get()
            return True
        except self._client.meta.client.exceptions.NoSuchKey:
            return False

    def _s3_list_by_prefix(self, container: str, path: str, recursive: bool = False) -> dict[str, dict[str, Any]]:
        logger.info("_list_by_prefix(%s, %s)", container, path)
        matched_entries: dict[str, dict[str, Any]] = {}
        if self._client:
            s3_client = self._client.meta.client
            paginator = s3_client.get_paginator("list_objects_v2")
            pages = (
                paginator.paginate(Bucket=container, Prefix=path)
                if recursive
                else paginator.paginate(Bucket=container, Prefix=path, Delimiter=URI_SEP)
            )
            for resp in pages:
                for subdir in resp.get("CommonPrefixes") or []:
                    matched_entries[subdir["Prefix"]] = {
                        "length": 0,
                        "permission": None,
                        "type": DFS_TYPE_DIRECTORY,
                    }
                for subobj in resp.get("Contents") or []:
                    matched_entries[subobj["Key"]] = {
                        "length": subobj["Size"],
                        "permission": None,
                        "type": DFS_TYPE_FILE,
                    }
        return matched_entries

    def _s3_delete(self, scheme: str, container: str, path: str, dfs_path: str, *, recursive: bool) -> bool | None:
        if not recursive or (self._stat_uri_impl(dfs_path) or {}).get("type") == DFS_TYPE_FILE:
            if self._dry_run:
                return None
            self._client.Object(container, path).delete()
            self._post_cloud_delete_wait(scheme)
            if self._stat_uri_impl(dfs_path):
                self.debug("S3 delete incomplete, retrying")
                raise GOEDfsDeleteNotComplete
        else:
            self.debug(f"Recursive delete using directory prefix: {path}")
            prefix = path if path.endswith(URI_SEP) else path + URI_SEP
            objects = self._s3_list_by_prefix(container, prefix, recursive=True)
            if self._dry_run or not objects:
                return None
            all_keys = list(objects.keys())
            s3_bucket = self._client.Bucket(container)
            for offset in range(0, len(all_keys), DELETE_BATCH_LIMIT):
                chunk_keys = all_keys[offset : offset + DELETE_BATCH_LIMIT]
                delete_request = [{"Key": key} for key in chunk_keys]
                delete_response = s3_bucket.delete_objects(Delete={"Objects": delete_request})
                if delete_response and delete_response.get("Errors"):
                    problem_keys = [err["Key"] for err in delete_response["Errors"]]
                    raise GOEDfsException(f"Errors deleting following objects from S3: {problem_keys!s}")
            self._post_cloud_delete_wait(scheme)
            if self._s3_list_by_prefix(container, prefix, recursive=True):
                self.debug("S3 delete incomplete, retrying")
                raise GOEDfsDeleteNotComplete
        return True

    def _azure_container_exists(self, container: str) -> bool:
        buckets = self._client.list_containers(name_starts_with=container)
        return bool([_.name for _ in buckets if _.name == container])

    def _azure_list_blobs(self, container: str, prefix: str, recursive: bool = False) -> list[Any]:
        container_client = self._client.get_container_client(container)
        if recursive:
            return list(container_client.list_blobs(name_starts_with=prefix))
        return list(container_client.walk_blobs(name_starts_with=prefix, delimiter=URI_SEP))

    def _azure_list_blob_names(self, container: str, prefix: str, recursive: bool = False) -> list[str]:
        return [_.name for _ in self._azure_list_blobs(container, prefix, recursive=recursive)]

    def _azure_blob_exists(self, container: str, path: str) -> bool:
        blobs = self._azure_list_blob_names(container, path)
        return any(_ == path for _ in blobs)

    def _azure_pragmatic_delete(self, container: str, path: str) -> None:
        try:
            container_client = self._client.get_container_client(container)
            container_client.delete_blob(path)
        except ResourceNotFoundError:
            self.debug(f"delete_blob({container}, {path}) returned 404 (ResourceNotFoundError), accepting as deleted")

    def _azure_delete(self, scheme: str, container: str, path: str, dfs_path: str, *, recursive: bool) -> bool | None:
        if self._dry_run:
            return None
        if not recursive or (self._stat_uri_impl(dfs_path) or {}).get("type") == DFS_TYPE_FILE:
            if not self._azure_blob_exists(container, path):
                return None
            self._azure_pragmatic_delete(container, path)
            self._post_cloud_delete_wait(scheme)
            if self._azure_blob_exists(container, path):
                self.debug("Azure delete incomplete, retrying")
                raise GOEDfsDeleteNotComplete
        else:
            prefix = path if path.endswith(URI_SEP) else path + URI_SEP
            found_files = False
            try:
                blobs_pending_delete = self._azure_list_blob_names(container, prefix, recursive=True)
            except HttpResponseError as exc:
                if "try again after some time" in str(exc):
                    raise GOEAzureTryAgainException from exc
                raise

            if scheme.lower() in (OFFLOAD_FS_SCHEME_ABFS, OFFLOAD_FS_SCHEME_ABFSS):
                blobs_pending_delete = list(reversed(blobs_pending_delete))
            if prefix not in blobs_pending_delete:
                blobs_pending_delete.append(prefix)
            if prefix.rstrip(URI_SEP) not in blobs_pending_delete:
                blobs_pending_delete.append(prefix.rstrip(URI_SEP))

            for offset in range(0, len(blobs_pending_delete), DELETE_BATCH_LIMIT):
                batch = blobs_pending_delete[offset : offset + DELETE_BATCH_LIMIT]
                for blob_name in batch:
                    if self._azure_blob_exists(container, blob_name):
                        found_files = True
                        self._azure_pragmatic_delete(container, blob_name)
                    elif scheme.lower() in (OFFLOAD_FS_SCHEME_ABFS, OFFLOAD_FS_SCHEME_ABFSS):
                        if (self._stat_uri_impl(self.gen_uri(scheme, container, blob_name)) or {}).get(
                            "type"
                        ) == DFS_TYPE_DIRECTORY:
                            found_files = True
                            try:
                                self._azure_pragmatic_delete(container, blob_name.rstrip("/"))
                            except HttpResponseError as exc:
                                if "DirectoryIsNotEmpty" not in str(exc):
                                    raise
                    self._post_cloud_delete_wait(scheme)
            if found_files and self._azure_list_blob_names(container, prefix, recursive=True):
                raise GOEDfsDeleteNotComplete
        return True


__all__ = [
    "AZURE_STORAGE_SCHEMES",
    "CLOUD_STORAGE_SCHEMES",
    "DELETE_BATCH_LIMIT",
    "DFS_RETRY_TIMEOUT",
    "DFS_TYPE_DIRECTORY",
    "DFS_TYPE_FILE",
    "GOE_DFS_AZURE",
    "GOE_DFS_GCS",
    "GOE_DFS_LOCAL",
    "GOE_DFS_S3",
    "OFFLOAD_FS_SCHEME_ABFS",
    "OFFLOAD_FS_SCHEME_ABFSS",
    "OFFLOAD_FS_SCHEME_ADL",
    "OFFLOAD_FS_SCHEME_AZ",
    "OFFLOAD_FS_SCHEME_FILE",
    "OFFLOAD_FS_SCHEME_GS",
    "OFFLOAD_FS_SCHEME_S3",
    "OFFLOAD_FS_SCHEME_S3A",
    "OFFLOAD_FS_SCHEME_WASB",
    "OFFLOAD_FS_SCHEME_WASBS",
    "S3_STORAGE_SCHEMES",
    "URI_SEP",
    "FSSpecBackend",
    "GOEAzureTryAgainException",
    "GOEDfsDeleteError",
    "GOEDfsDeleteNotComplete",
    "GOEDfsException",
    "LocalStore",
    "ObStoreBackend",
    "ObjectStoreBase",
    "StagingStorageService",
    "StorageObjectStat",
    "azure_fq_container_name",
    "gen_fs_uri",
    "storage_registry",
    "uri_component_split",
]

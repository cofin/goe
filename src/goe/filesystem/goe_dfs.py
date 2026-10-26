# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""GOEDfs abstract filesystem interface and CloudStorageDfsAdapter."""

from __future__ import annotations

import logging
import os
import time
from abc import ABCMeta, abstractmethod
from typing import Any

from goe.filesystem.storage_service import (
    AZURE_STORAGE_SCHEMES,
    CLOUD_STORAGE_SCHEMES,
    DELETE_BATCH_LIMIT,
    DFS_RETRY_TIMEOUT,
    DFS_TYPE_DIRECTORY,
    DFS_TYPE_FILE,
    GOE_DFS_AZURE,
    GOE_DFS_GCS,
    GOE_DFS_LOCAL,
    GOE_DFS_S3,
    OFFLOAD_FS_SCHEME_ABFS,
    OFFLOAD_FS_SCHEME_ABFSS,
    OFFLOAD_FS_SCHEME_ADL,
    OFFLOAD_FS_SCHEME_AZ,
    OFFLOAD_FS_SCHEME_AZURE,
    OFFLOAD_FS_SCHEME_FILE,
    OFFLOAD_FS_SCHEME_GS,
    OFFLOAD_FS_SCHEME_HDFS,
    OFFLOAD_FS_SCHEME_INHERIT,
    OFFLOAD_FS_SCHEME_S3,
    OFFLOAD_FS_SCHEME_S3A,
    OFFLOAD_FS_SCHEME_WASB,
    OFFLOAD_FS_SCHEME_WASBS,
    S3_STORAGE_SCHEMES,
    UNSUPPORTED_URI_SCHEME_EXCEPTION_TEXT,
    URI_SEP,
    VALID_OFFLOAD_FS_SCHEMES,
    GOEAzureTryAgainException,
    GOEDfsDeleteError,
    GOEDfsDeleteNotComplete,
    GOEDfsException,
    GOEDfsFilesNotVisible,
    StagingStorageService,
    StorageObjectStat,
    azure_fq_container_name,
    gen_fs_uri,
    uri_component_split,
)
from goe.observability.storage import traced_storage_call
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.util.string_utils import add_suffix_in_same_case

__all__ = [
    "AZURE_OFFLOAD_FS_SCHEMES",
    "AZURE_STORAGE_SCHEMES",
    "CLOUD_STORAGE_SCHEMES",
    "DELETE_BATCH_LIMIT",
    "DFS_RETRY_TIMEOUT",
    "DFS_TYPE_DIRECTORY",
    "DFS_TYPE_FILE",
    "GOE_DFS_AZURE",
    "GOE_DFS_GCS",
    "GOE_DFS_HDFS",
    "GOE_DFS_LOCAL",
    "GOE_DFS_S3",
    "GOE_DFS_SSH",
    "GOE_DFS_WEBHDFS",
    "OFFLOAD_FS_SCHEMES_REQUIRING_ACCOUNT",
    "OFFLOAD_FS_SCHEMES_REQUIRING_CONTAINER",
    "OFFLOAD_FS_SCHEME_ABFS",
    "OFFLOAD_FS_SCHEME_ABFSS",
    "OFFLOAD_FS_SCHEME_ADL",
    "OFFLOAD_FS_SCHEME_AZ",
    "OFFLOAD_FS_SCHEME_AZURE",
    "OFFLOAD_FS_SCHEME_FILE",
    "OFFLOAD_FS_SCHEME_GS",
    "OFFLOAD_FS_SCHEME_HDFS",
    "OFFLOAD_FS_SCHEME_INHERIT",
    "OFFLOAD_FS_SCHEME_S3",
    "OFFLOAD_FS_SCHEME_S3A",
    "OFFLOAD_FS_SCHEME_WASB",
    "OFFLOAD_FS_SCHEME_WASBS",
    "OFFLOAD_NON_HDFS_FS_SCHEMES",
    "OFFLOAD_WEBHDFS_COMPATIBLE_FS_SCHEMES",
    "POST_CLOUD_DELETE_WAIT_SECONDS",
    "S3_STORAGE_SCHEMES",
    "UNSUPPORTED_URI_SCHEME_EXCEPTION_TEXT",
    "URI_SEP",
    "VALID_OFFLOAD_FS_SCHEMES",
    "CloudStorageDfsAdapter",
    "GOEAzureTryAgainException",
    "GOEDfs",
    "GOEDfsDeleteError",
    "GOEDfsDeleteNotComplete",
    "GOEDfsException",
    "GOEDfsFilesNotVisible",
    "StagingStorageService",
    "StorageObjectStat",
    "azure_fq_container_name",
    "gen_fs_uri",
    "gen_load_uri_from_options",
    "get_scheme_from_location_uri",
    "uri_component_split",
]

GOE_DFS_HDFS = "CliHdfs"
GOE_DFS_SSH = "SSH"
GOE_DFS_WEBHDFS = "WebHdfs"
POST_CLOUD_DELETE_WAIT_SECONDS = 0.2

OFFLOAD_FS_SCHEMES_REQUIRING_ACCOUNT = [OFFLOAD_FS_SCHEME_AZURE]
OFFLOAD_FS_SCHEMES_REQUIRING_CONTAINER = [
    OFFLOAD_FS_SCHEME_GS,
    OFFLOAD_FS_SCHEME_S3A,
    OFFLOAD_FS_SCHEME_S3,
    OFFLOAD_FS_SCHEME_WASB,
    OFFLOAD_FS_SCHEME_WASBS,
    OFFLOAD_FS_SCHEME_ADL,
    OFFLOAD_FS_SCHEME_ABFS,
    OFFLOAD_FS_SCHEME_ABFSS,
]
OFFLOAD_NON_HDFS_FS_SCHEMES = [
    _ for _ in VALID_OFFLOAD_FS_SCHEMES if _ not in (OFFLOAD_FS_SCHEME_INHERIT, OFFLOAD_FS_SCHEME_HDFS)
]
OFFLOAD_WEBHDFS_COMPATIBLE_FS_SCHEMES = [
    _ for _ in VALID_OFFLOAD_FS_SCHEMES if _ in (OFFLOAD_FS_SCHEME_INHERIT, OFFLOAD_FS_SCHEME_HDFS)
]
AZURE_OFFLOAD_FS_SCHEMES = [
    OFFLOAD_FS_SCHEME_WASB,
    OFFLOAD_FS_SCHEME_WASBS,
    OFFLOAD_FS_SCHEME_ADL,
    OFFLOAD_FS_SCHEME_ABFS,
    OFFLOAD_FS_SCHEME_ABFSS,
]


def get_scheme_from_location_uri(dfs_path: str) -> str:
    """Extract and validate the scheme from a table/database location URI."""
    scheme = dfs_path.split(":")[0]
    if not scheme or scheme[0] == "/":
        return OFFLOAD_FS_SCHEME_HDFS
    if scheme in VALID_OFFLOAD_FS_SCHEMES:
        return scheme
    raise NotImplementedError(f"Location scheme support {scheme} not implemented")


def gen_load_uri_from_options(
    offload_options: Any,
    hadoop_db: str | None = None,
    table_name: str | None = None,
    scheme_override: str | None = None,
) -> str:
    """Return a Hadoop load file URI constructed from offload options."""
    return gen_fs_uri(
        offload_options.hdfs_load,
        offload_options.hdfs_db_path_suffix,
        backend_db=hadoop_db,
        table_name=table_name,
    )


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class GOEDfs(metaclass=ABCMeta):
    """Abstract interface for filesystem and cloud storage operations."""

    dfs_mechanism: str
    backend_dfs: str
    _client: Any

    def __init__(self, messages: Any, dry_run: bool = False, do_not_connect: bool = False) -> None:
        self._messages = messages
        self._dry_run = dry_run
        self._do_not_connect = do_not_connect

    def debug(self, msg: Any) -> None:
        """Log a debug message."""
        if self._messages:
            self._messages.debug(msg)
        logger.debug(msg)

    def log(self, msg: Any, detail: Any = VERBOSE) -> None:
        """Log an informational message."""
        if self._messages:
            self._messages.log(msg, detail=detail)
        logger.info(msg)

    def notice(self, msg: Any) -> None:
        """Log a notice message."""
        if self._messages:
            self._messages.notice(msg)
        logger.debug(msg)

    def warning(self, msg: Any) -> None:
        """Log a warning message."""
        if self._messages:
            self._messages.warning(msg)
        logger.warning(msg)

    def get_perms(self, dfs_path: str) -> str | None:
        """Return permissions of a file or path in numeric octal form, e.g. '755'."""
        stats = self.stat(dfs_path)
        return stats.get("permission") if stats else None

    @staticmethod
    def convert_rwx_perms_to_oct_str(perm_string: str | None) -> str | None:
        """Convert an ls permission string like '-rwxr-x---' into an octal string like '750'."""
        if not perm_string:
            return None
        assert len(perm_string) >= 10, f"Unexpected permission format {perm_string}"
        perm_values = {"r": 4, "w": 2, "x": 1}
        trimmed = perm_string[1:10]
        oct_parts: list[str] = []
        for idx in range(3):
            group_slice = trimmed[idx * 3 : idx * 3 + 3]
            oct_parts.append(str(sum(perm_values.get(ch, 0) for ch in group_slice)))
        return "".join(oct_parts)

    @staticmethod
    def command_contains_injection_concerns(command_string: str) -> bool:
        """Return True if command_string contains shell metacharacters (';', '|', '>')."""
        return any(char in command_string for char in (";", "|", ">"))

    @abstractmethod
    def chgrp(self, dfs_path: str, group: str) -> Any:
        """Change group ownership of dfs_path."""

    @abstractmethod
    def chmod(self, dfs_path: str, mode: str) -> Any:
        """Change permissions of dfs_path."""

    @abstractmethod
    def client(self) -> Any:
        """Return underlying storage client."""

    @abstractmethod
    def container_exists(self, scheme: str, container: str) -> bool:
        """Return True if the target cloud container/bucket exists."""

    @abstractmethod
    def copy_from_local(self, local_path: str, dfs_path: str, overwrite: bool = False) -> Any:
        """Upload a local file to dfs_path."""

    @abstractmethod
    def copy_to_local(self, dfs_path: str, local_path: str, overwrite: bool = False) -> Any:
        """Download dfs_path to a local file."""

    @abstractmethod
    def delete(self, dfs_path: str, recursive: bool = False) -> Any:
        """Delete a file or directory at dfs_path."""

    @abstractmethod
    def gen_uri(
        self,
        scheme: str,
        container: str,
        path_prefix: str,
        backend_db: str | None = None,
        table_name: str | None = None,
        container_override: str | None = None,
    ) -> str:
        """Generate a normalized storage URI."""

    @abstractmethod
    def list_dir(self, dfs_path: str) -> list[str] | None:
        """List entries in dfs_path."""

    @abstractmethod
    def mkdir(self, dfs_path: str) -> Any:
        """Create directory at dfs_path."""

    @abstractmethod
    def read(self, dfs_path: str, as_str: bool = False) -> bytes | str | None:
        """Read contents of dfs_path."""

    @abstractmethod
    def rename(self, hdfs_src_path: str, hdfs_dst_path: str) -> Any:
        """Rename or move hdfs_src_path to hdfs_dst_path."""

    @abstractmethod
    def rmdir(self, dfs_path: str, recursive: bool = False) -> Any:
        """Remove directory at dfs_path."""

    @abstractmethod
    def stat(self, dfs_path: str) -> dict[str, Any] | None:
        """Return metadata stat dict for dfs_path, or None if not found."""

    @abstractmethod
    def write(self, dfs_path: str, data: str | bytes, overwrite: bool = False) -> Any:
        """Write data to dfs_path."""

    def stat_has_Group(self, stat_dict: dict[str, Any], group: str) -> bool:
        """Return True if stat_dict has matching group."""
        if not stat_dict or not stat_dict.get("group"):
            return False
        return bool(stat_dict["group"].lower() == group.lower())

    def stat_has_permission(self, stat_dict: dict[str, Any], permission: Any) -> bool:
        """Return True if stat_dict has matching permission."""
        if not stat_dict or not stat_dict.get("permission"):
            return False
        return bool(str(stat_dict["permission"]).lower() == str(permission).lower())

    def list_dir_and_wait_for_contents(self, uri: str, timeout: int = 10) -> list[str]:
        """List directory contents, polling until files appear or timeout expires."""
        self.debug(f"Waiting ({timeout}s) for files in: {uri}")
        file_list: list[str] | None = None
        for attempt in range(timeout):
            try:
                file_list = self.list_dir(uri)
            except Exception as exc:
                self.debug(f"Unable to list contents of path on attempt {attempt} ({uri}): {exc!s}")
            if file_list:
                self.debug(f"Found {len(file_list)} entries on attempt {attempt}")
                break
            time.sleep(1)
        if not file_list:
            self.log(f"Found no entries at {uri} after {timeout}s", detail=VVERBOSE)
            return []
        return file_list

    def _post_cloud_delete_wait(self, scheme: str) -> None:
        if scheme in (
            OFFLOAD_FS_SCHEME_WASB,
            OFFLOAD_FS_SCHEME_WASBS,
            OFFLOAD_FS_SCHEME_ABFS,
            OFFLOAD_FS_SCHEME_ABFSS,
            OFFLOAD_FS_SCHEME_ADL,
            OFFLOAD_FS_SCHEME_AZ,
        ):
            time.sleep(1)

    @staticmethod
    def _uri_component_split(dfs_path: str) -> tuple[str, str, str]:
        scheme, container, path = uri_component_split(dfs_path)
        if scheme in (
            OFFLOAD_FS_SCHEME_S3,
            OFFLOAD_FS_SCHEME_S3A,
            OFFLOAD_FS_SCHEME_GS,
            OFFLOAD_FS_SCHEME_ADL,
            OFFLOAD_FS_SCHEME_WASB,
            OFFLOAD_FS_SCHEME_WASBS,
            OFFLOAD_FS_SCHEME_ABFS,
            OFFLOAD_FS_SCHEME_ABFSS,
            OFFLOAD_FS_SCHEME_AZ,
        ):
            if path and path.startswith(URI_SEP):
                path = path.lstrip(URI_SEP)
        return scheme, container, path

    def _add_db_Only_suffix(self, backend_db: str | None, db_path_suffix: str | None) -> str | None:
        if backend_db and db_path_suffix:
            return add_suffix_in_same_case(backend_db, db_path_suffix)
        return backend_db

    def _gen_hdfs_uri(
        self,
        path_prefix: str,
        db_path_suffix: str | None = None,
        scheme: str | None = None,
        container: str | None = None,
        backend_db: str | None = None,
        table_name: str | None = None,
    ) -> str:
        assert path_prefix is not None
        assert isinstance(path_prefix, str)
        if backend_db:
            assert isinstance(backend_db, str)
        if table_name:
            assert isinstance(table_name, str)
        if not path_prefix.startswith("/"):
            path_prefix = "/" + path_prefix
        scheme_prefix = f"{scheme}://" if scheme else ""
        container_str = container or ""
        backend_db = self._add_db_Only_suffix(backend_db, db_path_suffix)
        uri_elements = [path_prefix] + [_ for _ in [backend_db, table_name] if _ is not None and _ != ""]
        return scheme_prefix + container_str + os.path.join(*uri_elements)


class CloudStorageDfsAdapter(GOEDfs):
    """GOEDfs adapter delegating cloud and local staging operations to StagingStorageService."""

    def __init__(
        self,
        messages: Any,
        *,
        scheme: str = OFFLOAD_FS_SCHEME_GS,
        container: str | None = None,
        dry_run: bool = False,
        do_not_connect: bool = False,
        db_path_suffix: str | None = None,
        google_kms_key_name: str | None = None,
        azure_account_name: str | None = None,
        azure_account_key: str | None = None,
        azure_account_domain: str | None = None,
        config: Any = None,
        storage_service: StagingStorageService | None = None,
    ) -> None:
        assert messages is not None
        super().__init__(messages, dry_run=dry_run, do_not_connect=do_not_connect)
        self._storage_service = storage_service or StagingStorageService(
            messages,
            scheme=scheme,
            container=container,
            dry_run=dry_run,
            do_not_connect=do_not_connect,
            db_path_suffix=db_path_suffix,
            google_kms_key_name=google_kms_key_name,
            azure_account_name=azure_account_name,
            azure_account_key=azure_account_key,
            azure_account_domain=azure_account_domain,
            config=config,
        )
        self._db_path_suffix = db_path_suffix
        self._google_kms_key_name = google_kms_key_name
        self._azure_account_name = azure_account_name
        self._azure_account_domain = self._storage_service._azure_account_domain
        self._config = config
        self._client = self._storage_service.client
        self.dfs_mechanism = self._storage_service.dfs_mechanism
        self.backend_dfs = self._storage_service.backend_dfs

    @property
    def storage_service(self) -> StagingStorageService:
        """Return the underlying StagingStorageService instance."""
        return self._storage_service

    def chgrp(self, dfs_path: str, group: str) -> Any:
        """Raise NotImplementedError because cloud object stores do not support POSIX chgrp."""
        raise NotImplementedError(f"chgrp() not implemented for {self.dfs_mechanism}")

    def chmod(self, dfs_path: str, mode: str) -> Any:
        """Raise NotImplementedError because cloud object stores do not support POSIX chmod."""
        raise NotImplementedError(f"chmod() not implemented for {self.dfs_mechanism}")

    def client(self) -> Any:
        """Return the underlying cloud storage SDK client."""
        return self._client

    def container_exists(self, scheme: str, container: str) -> bool:
        """Return True if the specified bucket/container exists."""
        self._sync_service_state()
        return self._storage_service.container_exists(scheme, container)

    @traced_storage_call("copy_from_local", "dfs_path")
    def copy_from_local(self, local_path: str, dfs_path: str, overwrite: bool = False) -> bool | None:
        """Upload a local file to dfs_path."""
        self._sync_service_state()
        return self._storage_service._upload_file_impl(local_path, dfs_path, overwrite=overwrite)

    @traced_storage_call("copy_to_local", "dfs_path")
    def copy_to_local(self, dfs_path: str, local_path: str, overwrite: bool = False) -> None:
        """Download dfs_path to a local file."""
        self._sync_service_state()
        self._storage_service._download_file_impl(dfs_path, local_path, overwrite=overwrite)

    @traced_storage_call("delete", "dfs_path")
    def delete(self, dfs_path: str, recursive: bool = False) -> bool | None:
        """Delete a file or directory prefix at dfs_path."""
        self._sync_service_state()
        return self._storage_service._delete_prefix_impl(dfs_path, recursive=recursive)

    def gen_uri(
        self,
        scheme: str,
        container: str,
        path_prefix: str,
        backend_db: str | None = None,
        table_name: str | None = None,
        container_override: str | None = None,
    ) -> str:
        """Construct a cloud storage URI."""
        return self._storage_service.gen_uri(
            scheme,
            container,
            path_prefix,
            backend_db=backend_db,
            table_name=table_name,
            container_override=container_override,
        )

    @traced_storage_call("list_dir", "dfs_path")
    def list_dir(self, dfs_path: str) -> list[str] | None:
        """List URIs under dfs_path."""
        self._sync_service_state()
        return self._storage_service._list_prefix_impl(dfs_path)

    def mkdir(self, dfs_path: str) -> None:
        """No-op mkdir on cloud object storage."""
        return None

    @traced_storage_call("read", "dfs_path")
    def read(self, dfs_path: str, as_str: bool = False) -> bytes | str | None:
        """Read bytes or string content from dfs_path."""
        self._sync_service_state()
        return self._storage_service._read_bytes_impl(dfs_path, as_str=as_str)

    def rename(self, hdfs_src_path: str, hdfs_dst_path: str) -> Any:
        """Raise NotImplementedError because cloud object stores do not support atomic directory rename."""
        raise NotImplementedError(f"rename() not implemented for {self.dfs_mechanism}")

    def rmdir(self, dfs_path: str, recursive: bool = False) -> bool | None:
        """Remove a directory prefix on cloud storage."""
        return self.delete(dfs_path, recursive=recursive)

    @traced_storage_call("stat", "dfs_path")
    def stat(self, dfs_path: str) -> dict[str, Any] | None:
        """Return stat metadata dict for dfs_path."""
        self._sync_service_state()
        return self._storage_service._stat_uri_impl(dfs_path)

    @traced_storage_call("write", "dfs_path")
    def write(self, dfs_path: str, data: str | bytes, overwrite: bool = False) -> None:
        """Write bytes or text data to dfs_path."""
        self._sync_service_state()
        self._storage_service._write_bytes_impl(dfs_path, data, overwrite=overwrite)

    def _sync_service_state(self) -> None:
        self._storage_service._client = self._client
        self._storage_service._dry_run = self._dry_run
        self._storage_service._google_kms_key_name = self._google_kms_key_name


__all__ = [
    "AZURE_STORAGE_SCHEMES",
    "CLOUD_STORAGE_SCHEMES",
    "DELETE_BATCH_LIMIT",
    "DFS_RETRY_TIMEOUT",
    "DFS_TYPE_DIRECTORY",
    "DFS_TYPE_FILE",
    "GOE_DFS_AZURE",
    "GOE_DFS_GCS",
    "GOE_DFS_HDFS",
    "GOE_DFS_LOCAL",
    "GOE_DFS_S3",
    "GOE_DFS_WEBHDFS",
    "OFFLOAD_FS_SCHEMES_REQUIRING_CONTAINER",
    "OFFLOAD_FS_SCHEME_ABFS",
    "OFFLOAD_FS_SCHEME_ABFSS",
    "OFFLOAD_FS_SCHEME_ADL",
    "OFFLOAD_FS_SCHEME_AZ",
    "OFFLOAD_FS_SCHEME_FILE",
    "OFFLOAD_FS_SCHEME_GS",
    "OFFLOAD_FS_SCHEME_HDFS",
    "OFFLOAD_FS_SCHEME_INHERIT",
    "OFFLOAD_FS_SCHEME_S3",
    "OFFLOAD_FS_SCHEME_S3A",
    "OFFLOAD_FS_SCHEME_WASB",
    "OFFLOAD_FS_SCHEME_WASBS",
    "S3_STORAGE_SCHEMES",
    "URI_SEP",
    "VALID_OFFLOAD_FS_SCHEMES",
    "CloudStorageDfsAdapter",
    "GOEAzureTryAgainException",
    "GOEDfs",
    "GOEDfsDeleteError",
    "GOEDfsDeleteNotComplete",
    "GOEDfsException",
    "StagingStorageService",
    "StorageObjectStat",
    "azure_fq_container_name",
    "gen_fs_uri",
    "uri_component_split",
]

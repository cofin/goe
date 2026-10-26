# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Factory resolving GOEDfs adapters backed by StagingStorageService or HdfsClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from goe.filesystem.goe_dfs import (
    AZURE_OFFLOAD_FS_SCHEMES,
    OFFLOAD_FS_SCHEME_AZ,
    OFFLOAD_FS_SCHEME_FILE,
    OFFLOAD_FS_SCHEME_GS,
    OFFLOAD_FS_SCHEME_S3,
    OFFLOAD_FS_SCHEME_S3A,
    CloudStorageDfsAdapter,
    GOEDfs,
)
from goe.filesystem.hdfs_client import HDFS_MODE_CLI, HDFS_MODE_WEBHDFS, HdfsClient
from goe.filesystem.storage_service import StagingStorageService
from goe.offload.offload_constants import HADOOP_BASED_BACKEND_DISTRIBUTIONS

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig


def get_dfs_from_options(
    config: OrchestrationConfig,
    messages: Any = None,
    force_ssh: bool = False,
    dry_run: bool = True,
    do_not_connect: bool = False,
) -> GOEDfs:
    """Return a GOEDfs adapter for the configured backend distribution and filesystem scheme."""
    if config.backend_distribution in HADOOP_BASED_BACKEND_DISTRIBUTIONS:
        mode = HDFS_MODE_WEBHDFS if (config.webhdfs_host and config.webhdfs_port and not force_ssh) else HDFS_MODE_CLI
        return HdfsClient(
            host=config.webhdfs_host if mode == HDFS_MODE_WEBHDFS else config.hdfs_host,
            port=config.webhdfs_port if mode == HDFS_MODE_WEBHDFS else None,
            ssh_user=config.hadoop_ssh_user,
            mode=mode,
            kerberos_enabled=bool(config.kerberos_service),
            verify_ssl=config.webhdfs_verify_ssl,
            dry_run=dry_run,
            messages=messages,
            do_not_connect=do_not_connect,
            db_path_suffix=config.hdfs_db_path_suffix,
            hdfs_data=config.hdfs_data,
        )

    scheme = (config.offload_fs_scheme or "").lower()
    if scheme in (
        OFFLOAD_FS_SCHEME_GS,
        OFFLOAD_FS_SCHEME_S3,
        OFFLOAD_FS_SCHEME_S3A,
        *AZURE_OFFLOAD_FS_SCHEMES,
        OFFLOAD_FS_SCHEME_AZ,
        OFFLOAD_FS_SCHEME_FILE,
    ):
        azure_account_name = getattr(config, "offload_fs_azure_account_name", None)
        azure_account_key = getattr(config, "offload_fs_azure_account_key", None)
        azure_account_domain = getattr(config, "offload_fs_azure_account_domain", None)
        container = getattr(config, "offload_fs_container", None)
        kms_key_name = getattr(config, "google_kms_key_name", None)
        service = StagingStorageService(
            messages,
            scheme=scheme,
            container=container,
            dry_run=dry_run,
            do_not_connect=do_not_connect,
            db_path_suffix=config.hdfs_db_path_suffix,
            google_kms_key_name=kms_key_name,
            azure_account_name=azure_account_name,
            azure_account_key=azure_account_key,
            azure_account_domain=azure_account_domain,
            config=config,
        )
        return CloudStorageDfsAdapter(
            messages,
            scheme=scheme,
            container=container,
            dry_run=dry_run,
            do_not_connect=do_not_connect,
            db_path_suffix=config.hdfs_db_path_suffix,
            google_kms_key_name=kms_key_name,
            azure_account_name=azure_account_name,
            azure_account_key=azure_account_key,
            azure_account_domain=azure_account_domain,
            config=config,
            storage_service=service,
        )
    if config.offload_fs_scheme:
        raise NotImplementedError(
            f"Backend system/scheme has not been implemented: {config.target}/{config.offload_fs_scheme}"
        )
    raise NotImplementedError(f"Backend system has not been implemented: {config.target}")

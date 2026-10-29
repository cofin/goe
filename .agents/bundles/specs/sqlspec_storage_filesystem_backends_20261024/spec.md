---
type: Spec
flow_id: sqlspec_storage_filesystem_backends_20261024
title: "Chapter 8.4: SQLSpec Storage Filesystem Backends and HDFS Consolidation"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-24T16:45:00Z
description: "Replaces bespoke GCS, S3, Azure, and POSIX filesystem wrappers with StagingStorageService backed by sqlspec.storage, consolidates on-premises HDFS into HdfsClient without MapRFS, and preserves the GOEDfs interface."
tags:
  - refactor
  - storage
  - filesystem
  - sqlspec
parent_prd: prd_08_duckdb2_transport_query_import_parity_and_storage_20261024
depends_on:
  - transport_decomposition_and_auto_selection_20261024
research:
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/duckdb2-arrow-and-storage-dataplane.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 8.4: SQLSpec Storage Filesystem Backends and HDFS Consolidation

## Specification

### 1. Overview and Goals

This chapter consolidates `src/goe/filesystem/` onto `sqlspec.storage` and retires bespoke cloud SDK wrappers:

1. **`StagingStorageService` on `sqlspec.storage` (`storage_service.py`)**: Wraps `sqlspec.storage` (`StorageBridge`, `ObStoreBackend`, `FsspecBackend`, and `LocalStore`) for `file://`, `gs://`, `s3://`, `s3a://`, `abfs://`, `abfss://`, `wasb://`, `wasbs://`, and `adl://` with streaming `upload_stream`, `download_stream`, `list_prefix`, `delete_prefix`, and `stat_uri` methods. Preserves `if_generation_match=0` create-only upload protection on GCS, `dry_run` execution logging, keyless GCP ADC and service-account impersonation from `goe.config.gcp_credentials.resolve_gcp_credentials()`, and `@traced_storage_call` spans while fixing unbounded `GOEGcs.stat()` prefix enumeration, the removed Azure v2 exception (`AzureMissingResourceHttpError`), and S3 batch deletion above 1,000 keys. Retires `src/goe/filesystem/{goe_gcs,goe_s3,goe_azure,goe_posix}.py` (1,622 LOC).
2. **Consolidated `HdfsClient` and `GOEDfs` Compatibility Adapter (`hdfs_client.py`, `goe_dfs.py`)**: Consolidates `src/goe/filesystem/cli_hdfs.py` and `src/goe/filesystem/web_hdfs.py` into `src/goe/filesystem/hdfs_client.py` for on-premises Hadoop `hdfs://` only, removing all MapRFS (`OFFLOAD_FS_SCHEME_MAPRFS`) references. Retains `src/goe/filesystem/goe_dfs.py` as a thin compatibility adapter over `StagingStorageService` and `HdfsClient`.
3. **Transport Staging, Backend Verification, and `ConnectRunner` Storage Probes (`goe_dfs_factory.py`, `staging_file.py`, `connect_functions.py`)**: Wires `get_dfs_from_options`, transport staging verification, backend load file checks, and `ConnectRunner` storage connectivity probes directly to `StagingStorageService` and `HdfsClient`.

### 2. Code Analysis Summary

- `src/goe/filesystem/goe_gcs.py:1-283`: Line `258` (`stat()`) calls `list_blobs(prefix=path)` without `max_results=2`, enumerating entire prefixes when checking virtual directory existence.
- `src/goe/filesystem/goe_azure.py:1-360`: Lines `14, 159, 326` import and catch removed Azure SDK v2 `azure.common.AzureMissingResourceHttpError` while using v12 `BlobServiceClient`, which raises `ResourceNotFoundError`.
- `src/goe/filesystem/goe_s3.py:1-210`: Line `137` (`delete()`) invokes `delete_objects` without chunking keys into S3's 1,000-key batch limit.
- `src/goe/filesystem/goe_posix.py:1-230`: Implements local filesystem operations duplicated by `sqlspec.storage` `LocalStore`.
- `src/goe/filesystem/cli_hdfs.py:1-265` and `src/goe/filesystem/web_hdfs.py:1-260`: Duplicate HDFS path normalization and command execution across SSH CLI and WebHDFS REST paths.
- `src/goe/filesystem/goe_dfs.py:49-62`: Defines `OFFLOAD_FS_SCHEME_MAPRFS = "maprfs"` inside `VALID_OFFLOAD_FS_SCHEMES`.
- `src/goe/filesystem/goe_dfs_factory.py:1-95`: Instantiates `GOEGcs`, `GOES3`, `GOEAzure`, `WebHdfs`, and `CliHdfs`.

### 3. Requirements

- **R1**: Implement `StagingStorageService` and `StorageObjectStat(FrozenBaseStruct)` in `src/goe/filesystem/storage_service.py` wrapping `sqlspec.storage` (`StorageBridge`, `ObStoreBackend`, `FsspecBackend`) for `file://`, `gs://`, `s3://`, `s3a://`, `abfs://`, `abfss://`, `wasb://`, `wasbs://`, and `adl://` with `upload_stream`, `download_stream`, `list_prefix`, `delete_prefix` (chunked at 1,000 keys per batch), and bounded `stat_uri` (`max_results=2`), and delete `src/goe/filesystem/{goe_gcs,goe_s3,goe_azure,goe_posix}.py`.
- **R2**: Consolidate `src/goe/filesystem/cli_hdfs.py` and `src/goe/filesystem/web_hdfs.py` into `src/goe/filesystem/hdfs_client.py` (`HdfsClient` supporting WebHDFS and SSH CLI modes for `hdfs://` only), delete `cli_hdfs.py` and `web_hdfs.py`, and update `src/goe/filesystem/goe_dfs.py` as a thin compatibility adapter over `StagingStorageService` and `HdfsClient` with zero `maprfs` references.
- **R3**: Update `src/goe/filesystem/goe_dfs_factory.py`, `src/goe/offload/staging/staging_file.py`, and `src/goe/connect/connect_functions.py` so transport staging, backend load verification, and `ConnectRunner` storage probes use `StagingStorageService` and `HdfsClient`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | `1.1` | `uv run pytest tests/unit/filesystem/test_storage_service.py -v` |
| R2 | `1.2` | `uv run pytest tests/unit/filesystem/test_hdfs_client.py -v` |
| R3 | `1.3` | `uv run pytest tests/unit/filesystem/test_goe_dfs.py -v` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/filesystem/test_storage_service.py tests/unit/filesystem/test_hdfs_client.py tests/unit/filesystem/test_goe_dfs.py -v
uv run ruff format --check src/goe/filesystem src/goe/offload/staging/staging_file.py src/goe/connect/connect_functions.py tests/unit/filesystem
uv run ruff check src/goe/filesystem src/goe/offload/staging/staging_file.py src/goe/connect/connect_functions.py tests/unit/filesystem
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: SQLSpec Storage Service, HDFS Consolidation, and Integration Wiring
- [ ] 1.1 Implement StagingStorageService on sqlspec.storage and Retire Legacy Cloud Wrappers ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Consolidate HdfsClient and Update GOEDfs Adapter ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Wire Transport Staging, Backend Verification, and Connect Storage Probes to StagingStorageService ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `sqlspec_storage_filesystem_backends_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `StagingStorageService` backs all cloud and local schemes via `sqlspec.storage` while preserving scheme-exact URIs, `if_generation_match=0`, `dry_run`, and `@traced_storage_call`; `HdfsClient` consolidates `cli_hdfs.py` and `web_hdfs.py` for `hdfs://` only; `maprfs` is removed.
- **Discoveries**: none yet.
- **Blockers**: `transport_decomposition_and_auto_selection_20261024` must complete first.
- **Next exact step**: execute task `1.1` (`sqlspec_storage_filesystem_backends_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/storage/gcs.md`, `.agents/bundles/knowledge/storage/s3.md`, `.agents/bundles/knowledge/storage/azure-blob.md`.

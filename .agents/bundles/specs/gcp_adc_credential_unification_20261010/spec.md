---
type: Spec
flow_id: gcp_adc_credential_unification_20261010
title: "Chapter 1.2: Unified GCP Application Default Credentials & Service Account Impersonation"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-10T16:00:00Z
description: "Unify GCP authentication across BigQuery, Cloud KMS, Cloud Storage, fsspec/gcsfs, and Dataproc around Application Default Credentials (ADC) and GOOGLE_IMPERSONATE_SERVICE_ACCOUNT without requiring JSON private key files."
tags: [feature, security, gcp, bigquery]
parent_prd: prd_01_foundation_adc_and_ci_harness_20261010
research:
  - .agents/bundles/specs/gcp_adc_credential_unification_20261010/research/adc_credential_unification.md
---

# Chapter 1.2: Unified GCP Application Default Credentials & Service Account Impersonation

## Specification

### Code Analysis Summary
- **Implicit & Fragmented GCP Client Construction**:
  - `src/goe/offload/bigquery/bigquery_backend_api.py:441-449`: `_get_bq_client()` constructs `bigquery.Client(default_query_job_config=job_config, location=self._bigquery_dataset_location)` without explicit `credentials` or `project`, and `_get_kms_client()` constructs `kms.KeyManagementServiceClient()` without `credentials`.
  - `src/goe/offload/bigquery/bigquery_backend_api.py:203-209`: `_backend_project_name()` returns `self._orchestration_config.bigquery_dataset_project or self._client.project`, which fails or picks an unintended project when user/impersonated ADC is used without `GOOGLE_CLOUD_PROJECT`.
  - `src/goe/filesystem/goe_gcs.py:58-68`: `GOEGcs.__init__` calls `storage.Client()` without passing resolved credentials or project.
  - `src/goe/util/goe_log_fh.py:42-56`: `GOELogFileHandle._get_fs` calls `fsspec.filesystem(scheme, **kwargs)` for `gs://` log URIs with `token=None`, causing `gcsfs` (`gcsfs/credentials.py:325-345`) to silently fall back to `anon` (anonymous access) when ADC fails or when `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is set.
- **Conflated Dataproc Service Account Semantics & `gcloud` Credential Store Divergence**:
  - `src/goe/offload/spark/dataproc_offload_transport.py:121-122` (`OffloadTransportSparkBatchesGcloud._gcloud_dataproc_submit_command`) passes `--service-account=GOOGLE_DATAPROC_SERVICE_ACCOUNT` (runtime worker SA for serverless batches), whereas `src/goe/offload/spark/dataproc_offload_transport.py:468-469` (`OffloadTransportSparkDataprocGcloud._gcloud_dataproc_submit_command`) passes `--impersonate-service-account=GOOGLE_DATAPROC_SERVICE_ACCOUNT` (caller control-plane impersonation for cluster jobs).
  - Neither Dataproc transport propagates `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` / `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT` to `gcloud` subprocesses.
- **Outdated GCS Hadoop Connector & Missing `goe connect` Preflight**:
  - `tools/transport/Makefile:12-13,41-42` bundles `gcs-connector-hadoop3-2.2.11-shaded.jar`, which lacks `fs.gs.auth.type=APPLICATION_DEFAULT` and `fs.gs.auth.impersonation.service.account` (introduced in `gcs-connector` 3.x).
  - `src/goe/connect/connect_backend.py:67-80` and `src/goe/connect/connect_transport.py:235-263` perform no preflight inspection of the active ADC credential type, resolved principal, project, quota project, or JSON key file usage.
- **JSON Key Guidance in Templates & Setup Docs**:
  - `templates/conf/offload.env.template.bigquery:8-9`, `templates/conf/offload.env.template.snowflake:50-51`, and `docs/gcp_setup.md:17-34` instruct users to download service account JSON keys (`GOOGLE_APPLICATION_CREDENTIALS` / `gcloud auth activate-service-account --key-file`).

### Relevant Patterns & Conventions
- [Configuration & Persistence Architecture](../../knowledge/patterns/configuration-and-persistence.md): All environment options are declared in `src/goe/config/orchestration_defaults.py`, validated in `src/goe/config/config_validation_functions.py`, and wired into `OrchestrationConfig` (`src/goe/config/orchestration_config.py`).
- [ADC Credential Unification Audit](research/adc_credential_unification.md): Comprehensive audit of all 36 GCP touchpoints in GOE.

### Requirements
- **REQ-1**: Create `src/goe/util/gcp_credentials.py` providing `GcpCredentialBundle`, `resolve_gcp_credentials(config=None, scopes=None)`, and `build_gcloud_impersonation_env(config=None, base_env=None)` supporting standard ADC (`google.auth.default`), `google.auth.impersonated_credentials.Credentials` when `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is set (preventing double-wrapping when ADC is already impersonated), and explicit project (`GOOGLE_CLOUD_PROJECT` -> `BIGQUERY_DATASET_PROJECT` -> ADC project) and quota project (`GOOGLE_CLOUD_QUOTA_PROJECT`) resolution; register `google_cloud_project`, `google_cloud_quota_project`, `google_impersonate_service_account`, and `google_dataproc_impersonate_service_account` in `OrchestrationConfig`.
- **REQ-2**: Wire `resolve_gcp_credentials(self._orchestration_config)` into `BackendBigQueryApi` (`_get_bq_client`, `_get_kms_client`, `_backend_project_name`, `kms_key_name`), `GOEGcs.__init__`, and `GOELogFileHandle._get_fs` (passing `token=bundle.credentials, project=bundle.project` to `fsspec.filesystem("gs", ...)` to eliminate silent anonymous fallback).
- **REQ-3**: Decouple Dataproc serverless batch runtime SA (`--service-account` from `google_dataproc_service_account`) from control-plane caller impersonation (`--impersonate-service-account` / `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT` from `google_dataproc_impersonate_service_account` or `google_impersonate_service_account`) in `dataproc_offload_transport.py`, upgrade `gcs-connector-hadoop3` to `3.0.2` in `tools/transport/Makefile`, and add ADC principal/project preflight verification and JSON key deprecation warnings to `goe connect` and `config_validation_functions.py`.
- **REQ-4**: Update `templates/conf/offload.env.template.bigquery`, `templates/conf/offload.env.template.snowflake`, and `docs/gcp_setup.md` to document keyless ADC, `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_QUOTA_PROJECT`, and Workload Identity Federation.

### Requirement Traceability Matrix

| Requirement | Task ID | Verification Strategy | Verification Target |
| :--- | :--- | :--- | :--- |
| REQ-1 | `1.1` | `behavior_tdd` | `uv run pytest tests/unit/util/test_gcp_credentials.py tests/unit/config/test_orchestration_config.py` |
| REQ-2 | `1.2` | `behavior_tdd` | `uv run pytest tests/unit/offload/bigquery/ tests/unit/filesystem/ tests/unit/util/test_goe_log_fh.py` |
| REQ-3 | `1.3` | `behavior_tdd` | `uv run pytest tests/unit/offload/test_offload_transport.py tests/unit/connect/` |
| REQ-4 | `1.4` | `documentation_validation` | `! grep -n 'activate-service-account --key-file' docs/gcp_setup.md && grep -n 'GOOGLE_IMPERSONATE_SERVICE_ACCOUNT' templates/conf/offload.env.template.bigquery` |

---

## Implementation Plan

- [ ] 1.1 Create `src/goe/util/gcp_credentials.py` and register GCP ADC/impersonation config options (`tasks/1.1.md`) [P0, behavior_tdd]
- [ ] 1.2 Wire `resolve_gcp_credentials` into BigQuery, KMS, `GOEGcs`, and `GOELogFileHandle` (`tasks/1.2.md`) (depends on: 1.1) [P0, behavior_tdd]
- [ ] 1.3 Separate Dataproc runtime SA vs caller impersonation, upgrade `gcs-connector` to `3.0.x`, and add `goe connect` ADC preflight checks (`tasks/1.3.md`) (depends on: 1.1, 1.2) [P1, behavior_tdd]
- [ ] 1.4 Update `offload.env` templates and `docs/gcp_setup.md` for keyless ADC (`tasks/1.4.md`) (depends on: 1.1, 1.2, 1.3) [P1, documentation_validation]

---

## Continuity Snapshot

- **Current State**: Planned (`state: planned`, `plan_revision: 1`). Research document promoted to `research/adc_credential_unification.md` and tasks `1.1`–`1.4` authored.
- **Next Action**: Claim and execute Task `1.1` (`tasks/1.1.md`) once Chapter 1.1 completes.

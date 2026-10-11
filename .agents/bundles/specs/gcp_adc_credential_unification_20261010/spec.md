---
type: Spec
flow_id: gcp_adc_credential_unification_20261010
title: "Chapter 1.2: Unified GCP Application Default Credentials & Service Account Impersonation"
state: completed
plan_revision: 3
plan_commit: null
state_revision: 7
current_task: null
last_operation: 20261011T154515Z-flow-executor-close-1-6-00
operation_targets: ["1.6"]
last_verified_checkpoint: a3397e7
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-11T15:45:15Z
description: "Unify GCP authentication across BigQuery, Cloud KMS, Cloud Storage, gcsfs log files, and gcloud Managed Spark commands around Application Default Credentials with optional service account impersonation, without service account key files."
tags: [feature, security, gcp, bigquery]
parent: prd_01_foundation_adc_and_ci_harness_20261010
depends_on: [legacy_shim_removal_and_repo_hygiene_20261010]
research:
  - .agents/bundles/specs/gcp_adc_credential_unification_20261010/research/adc_credential_unification.md
---

# Chapter 1.2: Unified GCP Application Default Credentials & Service Account Impersonation

## Specification

### Context

- **Baseline and ordering.** All line numbers in this flow are at commit `46890a8`.
  - This chapter runs after Chapter 1.1 (`legacy_shim_removal_and_repo_hygiene_20261010`) and before Chapter 1.3 (`oracle_ci_and_bigquery_test_harness_20261010`).
  - Files shared with Chapter 1.1 are cited by symbol name as well as line:
    - Chapter 1.1 Task 1.2 edits `src/goe/config/orchestration_config.py`, `src/goe/config/orchestration_defaults.py`, and `tests/unit/config/test_orchestration_config.py`. This flow's Task 1.1 edits them too. Chapter 1.1 also touches `src/goe/goe.py`, `src/goe/offload/offload_messages.py`, `src/goe/connect/connect.py`, and `src/goe/connect/connect_functions.py`, which this flow only reads.
    - Chapter 1.1 Task 1.6 edits `docs/gcp_setup.md:361` and `docs/user_guide.md`. This flow's Task 1.6 edits other sections of both.
- **Current state (verified at `46890a8`).**
  - No GOE code passes `credentials=` or `project=` to a Google client:
    - `BackendBigQueryApi._get_bq_client`/`_get_kms_client` (`src/goe/offload/bigquery/bigquery_backend_api.py:441-449`).
    - `GOEGcs.__init__` (`src/goe/filesystem/goe_gcs.py:68`).
    - `GOELogFileHandle._get_fs` (`src/goe/util/goe_log_fh.py:52`).
  - With `token=None`, gcsfs falls back silently to anonymous access (`gcsfs/credentials.py:304-345`).
  - `OffloadTransportSparkBatchesGcloud._gcloud_dataproc_submit_command` uses `GOOGLE_DATAPROC_SERVICE_ACCOUNT` as the serverless runtime SA (`src/goe/offload/spark/dataproc_offload_transport.py:121-122`). `OffloadTransportSparkDataprocGcloud._gcloud_dataproc_submit_command` reuses it as `--impersonate-service-account` (`:468-469`).
  - `tools/transport/Makefile:12-13,41-42` downloads `gcs-connector-hadoop3-2.2.11-shaded.jar`.
  - `goe connect` reports no credential identity.
  - `templates/conf/offload.env.template.bigquery:8-9`, `templates/conf/offload.env.template.snowflake:50-51`, and `docs/gcp_setup.md:17-33` advertise service account key files.
- **Design facts that shape the tasks.**
  - `gcloud` commands run through `OffloadTransport._run_os_cmd` (`src/goe/offload/offload_transport.py:845-860`), which has no `env` parameter and is optionally prefixed with SSH. Caller impersonation therefore uses the per-command `--impersonate-service-account` flag, not `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT`. The PRD's `build_gcloud_impersonation_env` is replaced by `resolve_gcloud_impersonation_principal`.
  - `storage.Client(project=None)` means "no project", so `project` is passed only when resolved.
  - `import goe.offload.offload_messages` already loads `google.auth`, so module-top imports in `goe.util.gcp_credentials` keep the CLI import budget.
  - Running ADC discovery inside `OrchestrationConfig` construction would execute on every config build, including unit tests. The key-file warning therefore lives in `goe connect` only.
- **Primary sources.**
  - ADC: <https://cloud.google.com/docs/authentication/application-default-credentials>.
  - google-auth `default`: <https://googleapis.dev/python/google-auth/latest/reference/google.auth.html#google.auth.default>.
  - Impersonated credentials: <https://googleapis.dev/python/google-auth/latest/reference/google.auth.impersonated_credentials.html>.
  - gcloud impersonation: <https://cloud.google.com/docs/authentication/use-service-account-impersonation>.
  - gcsfs token: <https://gcsfs.readthedocs.io/en/latest/api.html#gcsfs.core.GCSFileSystem>.
  - Serverless runtime SA: <https://cloud.google.com/sdk/gcloud/reference/dataproc/batches/submit/pyspark>.
  - Cluster SA: <https://cloud.google.com/dataproc/docs/concepts/configuring-clusters/service-accounts>.
  - gcs-connector 3.0.x: <https://repo1.maven.org/maven2/com/google/cloud/bigdataoss/gcs-connector/3.0.20/> and <https://github.com/GoogleCloudDataproc/hadoop-connectors/blob/branch-3.0.x/gcs/CONFIGURATION.md#authentication>.
- **Decision resolved (`D2` — BigQuery job/billing project precedence).** Confirmed: `GOOGLE_CLOUD_PROJECT`, then the ADC default project, then `BIGQUERY_DATASET_PROJECT`. Today's job project is unchanged, and the dataset project is used only where clients currently fail with "Project was not passed and could not be determined".
- **Behavior change (PRD invariant).** Permanent-cluster jobs no longer impersonate `GOOGLE_DATAPROC_SERVICE_ACCOUNT`. Operators set `GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT` or `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` instead. GOE logs `DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED`, and `goe connect` warns.

### Relevant Patterns & Conventions

- [Configuration & Environment Variables](../../knowledge/operations/configuration-and-env.md): options are declared in `src/goe/config/orchestration_defaults.py` and wired into `OrchestrationConfig` (`EXPECTED_CONFIG_ARGS`, annotations, `from_dict`). Its L50 still describes `GOOGLE_APPLICATION_CREDENTIALS` as a key file path; archive synthesis must update it.
- [BigQuery backend](../../knowledge/backends/bigquery.md), [GCS storage](../../knowledge/storage/gcs.md), [Spark Dataproc transport](../../knowledge/transport/spark-dataproc.md): current-state chapters that archive synthesis updates with the credential model.
- [ADC Credential Unification Audit](research/adc_credential_unification.md): inventory of 36 GCP touchpoints, plus the revision 2 verification addendum.

### Requirements

- **REQ-1**: Create `src/goe/util/gcp_credentials.py` with:
  - `GcpCredentialBundle`.
  - `resolve_gcp_credentials(config=None, scopes=None)`, which runs ADC through `google.auth.default`. When `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is set, it wraps the result in `impersonated_credentials.Credentials`, never double-wrapping and rejecting a conflicting impersonated ADC. It resolves the explicit project and quota project (D2) and caches bundles.
  - `resolve_gcloud_impersonation_principal(config=None)`.
  - Register `google_cloud_project`, `google_cloud_quota_project`, `google_impersonate_service_account`, and `google_dataproc_impersonate_service_account` in `OrchestrationConfig`.
- **REQ-2**: Build these clients from `resolve_gcp_credentials`: `BackendBigQueryApi` (`bigquery.Client`, `kms.KeyManagementServiceClient`), `GOEGcs` (`storage.Client`, with config forwarded by `get_dfs_from_options`), and `GOELogFileHandle` (gcsfs `token=<Credentials>`, removing the anonymous fallback), and reorder `BackendBigQueryApi` (`src/goe/offload/bigquery/bigquery_backend_api.py`) and `GOELogFileHandle` (`src/goe/util/goe_log_fh.py`) so public/dunder methods precede private (`_...`) helpers.
- **REQ-3**: Separate the Managed Spark serverless runtime SA (`--service-account` from `GOOGLE_DATAPROC_SERVICE_ACCOUNT`) from gcloud caller impersonation (`--impersonate-service-account` from `GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT` or `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`) on `batches submit`, `batches describe`, and `jobs submit --cluster`, and reorder `OffloadTransportSparkBatchesGcloud`, `OffloadTransportSparkBatchesGcloudCanary`, and `OffloadTransportSparkDataprocGcloudCanary` (`src/goe/offload/spark/dataproc_offload_transport.py`) so public/dunder methods precede private (`_...`) methods.
- **REQ-4**: Add a `goe connect` "Google Cloud credentials" preflight. It reports credential type, principal, impersonated SA, project, and quota project. It fails on missing ADC or a denied token, and warns on a service account key or a missing project. Add a Managed Spark identity report.
- **REQ-5**: Upgrade the bundled Cloud Storage Hadoop connector to 3.0.x (`gcs-connector-3.0.20-shaded.jar`) with `spark.hadoop.fs.gs.auth.type APPLICATION_DEFAULT` in the bundled Spark defaults.
- **REQ-6**: Update `templates/conf/offload.env.template.bigquery`, `templates/conf/offload.env.template.snowflake`, `docs/gcp_setup.md`, and `docs/user_guide.md`. Document keyless ADC, the new settings, Workload Identity Federation, least-privilege IAM, and gcs-connector 3.0.x properties, and remove all key-file guidance.

### Requirement Traceability Matrix

| Requirement | Task ID | Verification Strategy | Verification Target |
| :--- | :--- | :--- | :--- |
| REQ-1 | `1.1` | `behavior_tdd` | `uv run pytest tests/unit/util/test_gcp_credentials.py tests/unit/config/test_orchestration_config.py`; AST public-before-private check on touched files |
| REQ-2 | `1.2` | `behavior_tdd` | `uv run pytest tests/unit/offload/test_bigquery_backend_api_credentials.py tests/unit/filesystem/test_goe_gcs.py tests/unit/util/test_goe_log_fh.py`; AST public-before-private check on `bigquery_backend_api.py`, `goe_gcs.py`, `goe_dfs_factory.py`, `goe_log_fh.py` |
| REQ-3 | `1.3` | `behavior_tdd` | `uv run pytest tests/unit/offload/test_offload_transport.py`; AST public-before-private check on `dataproc_offload_transport.py` |
| REQ-4 | `1.4` | `behavior_tdd` | `uv run pytest tests/unit/connect/test_connect_gcp.py`; AST public-before-private check on `connect_backend.py`, `connect_transport.py` |
| REQ-5 | `1.5` | `static_validation` | `make -C tools/transport -n spark-jars \| grep -F gcs-connector/3.0.20/gcs-connector-3.0.20-shaded.jar` |
| REQ-6 | `1.6` | `documentation_validation` | `grep` structural checks in `tasks/1.6.md` (no `activate-service-account`, `key-file`, or `private key JSON`; required sections present) |

Every code task also runs the AST public-before-private ordering check on its touched Python files, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src/goe`, and `uv run pytest tests/unit`, each prefixed with `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false`.

---

## Implementation Plan

- [x] 1.1 Create the shared GCP credential resolver and register ADC/impersonation config options ([tasks/1.1.md](tasks/1.1.md)) [P1, behavior_tdd]
- [x] 1.2 Wire the shared credential bundle into BigQuery, Cloud KMS, GOEGcs, and GOELogFileHandle ([tasks/1.2.md](tasks/1.2.md)) (depends on: 1.1) [P1, behavior_tdd]
- [x] 1.3 Separate the Managed Spark runtime service account from gcloud caller impersonation ([tasks/1.3.md](tasks/1.3.md)) (depends on: 1.1) [P1, behavior_tdd]
- [x] 1.4 Add goe connect Google Cloud credential preflight and Managed Spark identity report ([tasks/1.4.md](tasks/1.4.md)) (depends on: 1.1, 1.3) [P2, behavior_tdd]
- [x] 1.5 Upgrade the bundled Cloud Storage Hadoop connector to 3.0.20 with ADC authentication ([tasks/1.5.md](tasks/1.5.md)) [P2, static_validation]
- [x] 1.6 Document keyless ADC and impersonation in offload.env templates, gcp_setup.md, and user_guide.md ([tasks/1.6.md](tasks/1.6.md)) (depends on: 1.1, 1.2, 1.3, 1.4, 1.5) [P2, documentation_validation]

---

## Continuity Snapshot

- **Flow / lifecycle**: `gcp_adc_credential_unification_20261010` (`state: completed`).
- **Current task / claimant**: `current_task: null` / `claimed_by: null`, and all six tasks are `closed`.
- **Last verified checkpoint**: `a3397e7`.
- **Plan identity**: `plan_revision: 3`, `plan_commit: null`.
- **State identity**: `state_revision: 7`.
- **Decisions**: `D2` resolved (project precedence: `GOOGLE_CLOUD_PROJECT` -> ADC default project -> `BIGQUERY_DATASET_PROJECT`).
- **Recent discoveries**: (1) `gcloud` runs via `OffloadTransport._run_os_cmd` (optionally over SSH), so caller impersonation uses `--impersonate-service-account` rather than process env vars; (2) `storage.Client(project=None)` disables project resolution, so `project` is passed only when resolved; (3) `gcs-connector-3.0.20-shaded.jar` uses `spark.hadoop.fs.gs.auth.type APPLICATION_DEFAULT`.
- **Blockers**: None.
- **Next exact step**: Proceed to Chapter 1.3 (`oracle_ci_and_bigquery_test_harness_20261010`).
- **Relevant knowledge**:
  - [configuration-and-env.md](../../knowledge/operations/configuration-and-env.md).
  - [backends/bigquery.md](../../knowledge/backends/bigquery.md).
  - [storage/gcs.md](../../knowledge/storage/gcs.md).
  - [transport/spark-dataproc.md](../../knowledge/transport/spark-dataproc.md).
  - [workflow.md](../../knowledge/workflow.md).
  - [research/adc_credential_unification.md](research/adc_credential_unification.md).

---
type: Research
title: ADC Credential Unification Audit
description: Audit of every GCP credential touchpoint in GOE with a keyless Application Default Credentials (ADC) and service-account impersonation design for runtime, connect checks, and local/CI integration tests.
tags: [research, security, gcp, auth]
created_at: 2026-10-10T15:05:00Z
---

# ADC Credential Unification Audit

Branch audited: `feat/bin-files`. Method: `git grep -n` across `src/`, `tests/`, `templates/`, `docs/`, `tools/`, `Makefile`, `.github/`, `sql/`, `bin/`, plus reading the installed library source in `.venv/` (google-auth 2.57.0, google-cloud-bigquery 3.44.0, google-cloud-storage 3.13.1, google-cloud-kms 3.16.0, gcsfs 2026.8.0 per `uv.lock`).

## 1. Executive Summary

- **The Python runtime does not use JSON keys anywhere.** Every Google client is built with no arguments: `bigquery.Client(...)`, `kms.KeyManagementServiceClient()`, `storage.Client()`, `fsspec.filesystem("gs")`. Each one falls back to `google.auth.default()`. No code reads `GOOGLE_APPLICATION_CREDENTIALS`, calls `from_service_account_*`, or calls `Credentials.from_*`. So user ADC, the metadata server (GCE/GKE/Cloud Run), WIF credential-config files, and impersonated ADC files from `gcloud auth application-default login --impersonate-service-account` **already work by accident**.
- **The JSON-key dependency lives in documentation and templates, plus one non-GCP Spark path:**
  - `templates/conf/offload.env.template.bigquery:8-9` and `templates/conf/offload.env.template.snowflake:50-51` describe `GOOGLE_APPLICATION_CREDENTIALS` as the "Path to Google service account private key JSON file".
  - `docs/gcp_setup.md:25-33` tells users to `gcloud auth activate-service-account --key-file=...`.
  - `tools/transport/Makefile:12-13` pins `gcs-connector-hadoop3-2.2.11`. Off GCE, that connector can only authenticate with a key, a user refresh token, or a custom `AccessTokenProvider`. It has no `APPLICATION_DEFAULT` mode.
- **Gaps that block a clean "ADC everywhere" story:**
  1. **There is no explicit credential/project model.** Project is inferred: BigQuery job project = ADC project; `_backend_project_name()` falls back to `client.project`. With user or impersonated ADC there is no project in the file, so it comes from `GOOGLE_CLOUD_PROJECT` or a `gcloud config` subprocess. Containers without gcloud fail or pick the wrong project.
  2. **No first-class impersonation for environments where ADC is not an impersonated file**, e.g. a GCE VM SA that should act as a narrower SA, or Direct WIF.
  3. **`gcloud` subprocesses (Managed Spark/Dataproc transport) do not use ADC.** gcloud has its own credential store, so the Spark identity can silently diverge from the Python identity.
  4. **`GOOGLE_DATAPROC_SERVICE_ACCOUNT` has two different meanings.** Serverless batches use it as the runtime SA (`--service-account`, `dataproc_offload_transport.py:121-122`). Cluster jobs use it as caller impersonation (`--impersonate-service-account`, `:468-469`).
  5. **`gcsfs` with `token=None` silently falls back to anonymous access** when ADC fails (`gcsfs/credentials.py` method chain `google_default → cache → cloud → anon`). Log writes to `gs://` then fail with misleading 401/403 errors instead of a credential error.
  6. **`goe connect` has no credential diagnostics.** It never reports which principal, project, or quota project is in use, never flags SA-key usage, and never checks that gcloud and ADC identities match.
- **Recommendation:**
  - Add one small credential resolver, `goe.util.gcp_credentials`: `google.auth.default()` plus optional `impersonated_credentials`, with explicit project and quota project. Pass it to every Google client and to gcsfs.
  - Propagate impersonation to gcloud via `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT`.
  - Separate runtime-SA from caller-impersonation semantics.
  - Add a `goe connect` "Google Cloud credentials" check.
  - Remove all key-file guidance.
  - Run integration tests with ADC + impersonation locally and with WIF-through-SA via `google-github-actions/auth@v3` in CI.

## 2. Inventory

`JSON-key dep` means GOE requires or advertises an SA key on that path.

| # | Location | Current behavior | JSON-key dep | Proposed ADC behavior |
|---|----------|------------------|:---:|----------------------|
| 1 | `src/goe/offload/bigquery/bigquery_backend_api.py:441-446` | `bigquery.Client(default_query_job_config=..., location=...)`. Implicit ADC, implicit job project. | No | `bigquery.Client(credentials=creds, project=job_project, ...)` using the shared resolver. |
| 2 | `src/goe/offload/bigquery/bigquery_backend_api.py:448-449` | `kms.KeyManagementServiceClient()`. Implicit ADC. | No | `KeyManagementServiceClient(credentials=creds)`. |
| 3 | `src/goe/offload/bigquery/bigquery_backend_api.py:203-209` | `_backend_project_name()` = `BIGQUERY_DATASET_PROJECT` or `client.project` (ADC-inferred). | No | Fall back to resolver project (`GOOGLE_CLOUD_PROJECT` → ADC project). Fail early if none. |
| 4 | `src/goe/offload/bigquery/bigquery_backend_api.py:160-171, 739-780, 1661-1667` | KMS client built only when key ring vars are set. Key path project = `GOOGLE_KMS_KEY_RING_PROJECT` or backend project. | No | Unchanged apart from injected credentials. |
| 5 | `src/goe/filesystem/goe_gcs.py:58-68` | `storage.Client()`. Implicit ADC/project. | No | `storage.Client(credentials=creds, project=project)`. |
| 6 | `src/goe/util/goe_log_fh.py:42-54` | `fsspec.filesystem("gs", block_size=...)`. `token=None` falls back to anon on auth failure. The docstring says this is intentional. | No | `fsspec.filesystem("gs", token=creds, project=project, block_size=...)`, which removes the silent anon fallback. |
| 7 | `src/goe/offload/spark/dataproc_offload_transport.py:93-130` | `gcloud dataproc batches describe/submit pyspark` with `--project/--region/--service-account=GOOGLE_DATAPROC_SERVICE_ACCOUNT`. Auth = gcloud credential store, not ADC. | No | Keep `--service-account` as the **runtime** SA. Add `--impersonate-service-account=<GOOGLE_IMPERSONATE_SERVICE_ACCOUNT>` (or set `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT` in the subprocess env) so the caller identity matches ADC. |
| 8 | `src/goe/offload/spark/dataproc_offload_transport.py:453-470` | `gcloud dataproc jobs submit pyspark --cluster ... --impersonate-service-account=GOOGLE_DATAPROC_SERVICE_ACCOUNT`. Caller impersonation reuses the runtime-SA variable. | No | Use `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` for impersonation. Cluster jobs run as the cluster VM SA, so `GOOGLE_DATAPROC_SERVICE_ACCOUNT` is ignored with a VVERBOSE note. **Behavior change.** |
| 9 | `src/goe/offload/spark/dataproc_offload_transport.py:410-440, 484-537` | Canary classes copy the same Dataproc fields. | No | Inherit the fix from #7/#8. |
| 10 | `src/goe/offload/offload_transport.py:1422-1434` | `config_nolog` redacts `spark.hadoop.fs.gs.auth.service.account.private.key(.id)`. These key-based connector props can be passed via `OFFLOAD_TRANSPORT_SPARK_PROPERTIES`. | Indirect | Keep the redaction for back-compat. Docs should recommend `fs.gs.auth.type=APPLICATION_DEFAULT` / `COMPUTE_ENGINE` and `fs.gs.auth.impersonation.service.account` instead. |
| 11 | `src/goe/offload/offload_transport.py:163, 282-343` | `OFFLOAD_TRANSPORT_SPARK_GCLOUD_EXECUTABLE="gcloud"`. Availability checks only test that the executable exists. | No | Unchanged. Identity check goes in connect (#13). |
| 12 | `src/goe/connect/connect_backend.py:67-80` | "BigQuery connectivity" = construct the backend API. On failure it prints a traceback. | No | Run after a new credential check that reports principal, type, project, and quota project. |
| 13 | `src/goe/connect/connect_transport.py:235-263` | `test_spark_gcloud` checks the gcloud executable plus RDBMS reachability via the canary. | No | Add a gcloud active-account / impersonation check and warn when it differs from the ADC principal. |
| 14 | `src/goe/connect/connect.py:412-430` | `test_offload_fs_container` checks that the bucket exists via the DFS client. | No | Unchanged. Benefits from explicit credentials. |
| 15 | `src/goe/config/orchestration_config.py:53-72, 221-240, 343-400`; `src/goe/config/orchestration_defaults.py:123-232` | BigQuery/KMS/Dataproc fields only. No project, quota project, or impersonation fields. | No | Add `google_cloud_project`, `google_cloud_quota_project`, `google_impersonate_service_account` (§4). |
| 16 | `templates/conf/offload.env.template.bigquery:8-9` | `# Path to Google service account private key JSON file` / `# GOOGLE_APPLICATION_CREDENTIALS=` | **Yes** (advertised) | Replace with an ADC block (§4). |
| 17 | `templates/conf/offload.env.template.bigquery:22-24` | `BIGQUERY_DATASET_PROJECT=`, documented as "default project for the authenticated user/service account". | No | Keep. Reword to point at `GOOGLE_CLOUD_PROJECT`. |
| 18 | `templates/conf/offload.env.template.bigquery:26-32` | `GOOGLE_KMS_KEY_RING_PROJECT/LOCATION/NAME`, `GOOGLE_KMS_KEY_NAME`. | No | Keep. |
| 19 | `templates/conf/offload.env.template.bigquery:34-49` | `GOOGLE_DATAPROC_CLUSTER/PROJECT/REGION/SERVICE_ACCOUNT/BATCHES_VERSION/BATCHES_SUBNET/BATCHES_TTL`. | No | Keep. Redefine `GOOGLE_DATAPROC_SERVICE_ACCOUNT` as "runtime SA for Managed Spark serverless batches". |
| 20 | `templates/conf/offload.env.template.snowflake:50-51` | `#GOOGLE_APPLICATION_CREDENTIALS=`, "required if staging Offload data in Google Cloud Storage". | **Yes** (advertised) | Replace with the same ADC block (GOE writes staging data via `storage.Client`). |
| 21 | `docs/gcp_setup.md:17-33` | `gcloud auth activate-service-account ... --key-file=/path/to/service-account-key.json`. | **Yes** | Delete. Replace with an ADC modes section (§7). |
| 22 | `docs/gcp_setup.md:61` | Recommends attaching the SA to a GCE VM ("preferable to downloading service account keys"). | No | Keep. Promote as the default. |
| 23 | `docs/gcp_setup.md:85-91` | Grants `roles/iam.serviceAccountUser` to the GOE SA **project-wide**. | No | Scope `serviceAccountUser` to the Dataproc runtime SA only (needed for `actAs`). Add `roles/iam.serviceAccountTokenCreator` on the GOE SA for human/CI principals that impersonate it. |
| 24 | `docs/google_cloud_run/README.md:20, 60, 77` | Cloud Run jobs use `--service-account=${SVC_ACCOUNT}` (metadata-server ADC). | No | Keep. Add an explicit "no keys" note and `GOOGLE_CLOUD_PROJECT` guidance. |
| 25 | `docs/google_cloud_run/Dockerfile:4-16` | `google/cloud-sdk:slim` base. `COPY offload.env`. No key copied. | No | Keep. Note that gcloud in the image uses the metadata server. (Separately: the image installs `python3.11` but the repo requires ≥3.12.) |
| 26 | `docs/user_guide.md:686-707` | Lists `GOOGLE_DATAPROC_SERVICE_ACCOUNT` as mandatory for both serverless and permanent. | No | Clarify that it is serverless runtime SA only. Add an authentication section. |
| 27 | `tools/transport/Makefile:12-13, 41-42` | Bundles `gcs-connector-hadoop3-2.2.11-shaded.jar` for non-Dataproc Spark. | **Yes** off-GCE | Move to GCS connector 3.x (`fs.gs.auth.type=APPLICATION_DEFAULT`). Verify Hadoop/Java compatibility of 3.x before switching. |
| 28 | `tools/spark-listener/src/main/scala/GOETaskListener.scala` | Task metrics listener. No Google auth. | No | None. |
| 29 | `.github/workflows/test.yaml:24-30, 50-65` | Unit tests only, `permissions: contents: read`. No GCP auth, no integration job. | No | Add an opt-in `integration-gcp` job with WIF (§6). |
| 30 | `Makefile:39-40, 99-103` | Exports `GOOGLE_API_USE_CLIENT_CERTIFICATE=false`. `test-integration` = `pytest tests/integration -n 4`. | No | Add a `test-integration-gcp` target or marker that runs credential preflight first. |
| 31 | `tests/integration/test_functions.py:22-35` | `OrchestrationConfig.from_dict({"verbose": False})`. Fully env-driven, so it inherits ambient ADC. | No | Add a session preflight fixture (§6). |
| 32 | `tests/integration/scenarios/test_offload_basic.py:830-860` | GCS log-path scenario (exercises gcsfs). | No | Becomes the regression test for removing the anon fallback. |
| 33 | `tests/unit/offload/test_offload_transport.py:192-193`; `tests/unit/test_functions.py:81` | Asserts `--service-account=` in the batches cmd. Fixture sets `GOOGLE_DATAPROC_SERVICE_ACCOUNT`. | No | Add assertions for the impersonation flag/env and the cluster-path change. |
| 34 | `src/goe/listener/config/application.py:42` | `keyfile` = Litestar/Granian TLS key. | N/A | Unrelated to GCP. |
| 35 | `src/goe/util/password_tools.py:107-131` and `PASSWORD_KEY_FILE` users | GOE password encryption key file. | N/A | Unrelated to GCP. |
| 36 | `sql/` | No GCP credential references. | No | None. |

Searches that returned **zero** hits in `src/`, `tests/`, `tools/`, `bin/`: `GOOGLE_APPLICATION_CREDENTIALS` (code), `from_service_account_json`, `from_service_account_file`, `Credentials.from_`, `google.oauth2`, `google.auth` imports, `credentials=`, `credentialsFile`, `spark-bigquery`, `gcpAccessToken`, `spark.hadoop.google.cloud.auth`, `storage_options`. GOE does not use the spark-bigquery-connector. BigQuery loads happen from staged files in GCS.

## 3. Per-component ADC and impersonation mechanics

### 3.1 google-auth (`google.auth.default`)

- Search order:
  1. `GOOGLE_APPLICATION_CREDENTIALS`. Accepts an SA key, a WIF/Workforce credential config (`external_account`), or other types.
  2. The gcloud ADC file `$HOME/.config/gcloud/application_default_credentials.json`, created by `gcloud auth application-default login`, either as a user or as an impersonated SA.
  3. The attached SA via the metadata server.

  Source: <https://cloud.google.com/docs/authentication/application-default-credentials#order>, <https://googleapis.dev/python/google-auth/latest/reference/google.auth.html#google.auth.default>
- Credential file types handled by the installed `google/auth/_default.py:38-49`: `authorized_user`, `service_account`, `external_account`, `external_account_authorized_user`, `impersonated_service_account`, plus GDCH. An impersonated ADC file is therefore fully transparent to every Python client.
- Project resolution:
  - SA key: the `project_id` in the file.
  - WIF: the pool project, if determinable.
  - gcloud ADC: the gcloud active project, read by shelling out to gcloud.
  - Otherwise: the metadata server.
  - `GOOGLE_CLOUD_PROJECT` / `GCLOUD_PROJECT` override.

  Quota project env: `GOOGLE_CLOUD_QUOTA_PROJECT` (installed `google/auth/environment_vars.py:18, 25, 32`).
- Programmatic impersonation: `google.auth.impersonated_credentials.Credentials(source_credentials, target_principal, target_scopes, delegates=None, lifetime=3600, quota_project_id=None)`. It auto-refreshes. The caller needs `roles/iam.serviceAccountTokenCreator` on the target. Sources: <https://googleapis.dev/python/google-auth/latest/reference/google.auth.impersonated_credentials.html>, <https://cloud.google.com/docs/authentication/use-service-account-impersonation>
- Off-GCP latency: metadata probing can be disabled with `NO_GCE_CHECK=true` (also respected by gcsfs).

### 3.2 google-cloud-bigquery / google-cloud-storage / google-cloud-kms

- All accept `credentials=` and `project=` (KMS: `credentials=`). When omitted they call `google.auth.default()`. BigQuery's `project` is the **job/billing project** and is distinct from the dataset project used in table references (`BIGQUERY_DATASET_PROJECT`). Sources: <https://cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.client.Client>, <https://cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.client.Client>, <https://cloud.google.com/python/docs/reference/cloudkms/latest>

### 3.3 gcsfs / fsspec

- `token=None` tries `google_default → cache → cloud → anon` (installed `gcsfs/credentials.py:325-345`). On a `GoogleAuthError`/`ValueError` it resets credentials and moves on, ending at `anon`. `token` also accepts `"google_default"`, `"cloud"`, a file path, or a `google.auth.credentials.Credentials` object. Source: <https://gcsfs.readthedocs.io/en/latest/api.html#gcsfs.core.GCSFileSystem>
- Implication: pass the shared `Credentials` object (preferred) or at least `token="google_default"` so failures are loud.

### 3.4 gcloud CLI (Managed Spark transports)

- gcloud credentials are **distinct from ADC**: <https://cloud.google.com/docs/authentication/application-default-credentials#personal> ("The credentials you provide to ADC by using the gcloud CLI are distinct from your gcloud credentials").
- Impersonation options:
  - Per command: `--impersonate-service-account`.
  - Persistent: `gcloud config set auth/impersonate_service_account`.
  - Environment: `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT`, since gcloud properties map to `CLOUDSDK_<SECTION>_<PROPERTY>`.

  Sources: <https://cloud.google.com/docs/authentication/use-service-account-impersonation#gcloud>, <https://cloud.google.com/sdk/docs/properties>
- On GCE/Cloud Run, gcloud uses the metadata server. In GitHub Actions, `google-github-actions/auth` exports `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE`, so gcloud uses the WIF credential file.

### 3.5 Dataproc / Managed Spark

- **Serverless batches** run as the runtime SA given by `--service-account` (default: Compute Engine default SA). The submitter needs `iam.serviceAccounts.actAs` (`roles/iam.serviceAccountUser`) on it. Executors get tokens from the metadata server, so no keys are needed. Sources: <https://cloud.google.com/sdk/gcloud/reference/dataproc/batches/submit/pyspark>, <https://cloud.google.com/dataproc-serverless/docs/concepts/service-account>
- **Permanent clusters**: the VM SA is fixed at cluster creation (`docs/gcp_setup.md:153`). `jobs submit` has no runtime-SA flag. `--impersonate-service-account` only changes **who submits**. Source: <https://cloud.google.com/dataproc/docs/concepts/configuring-clusters/service-accounts>
- Inside Dataproc, the bundled GCS connector defaults to the VM/runtime SA (metadata server).

### 3.6 Cloud Storage Hadoop connector (non-Dataproc Spark: spark-submit / Livy / Thrift)

- **v2.2.x** (pinned in `tools/transport/Makefile:13`): auth uses `fs.gs.auth.access.token.provider.impl` if set. Otherwise, with `fs.gs.auth.service.account.enable=true`, it uses a configured SA email/key (private-key props, JSON keyfile, P12) and falls back to the GCE VM SA. There is no `APPLICATION_DEFAULT` mode. Source: <https://github.com/GoogleCloudDataproc/hadoop-connectors/blob/branch-2.2.x/gcs/CONFIGURATION.md#authentication>
- **v3.x**: `fs.gs.auth.type` = `COMPUTE_ENGINE` (default) | `APPLICATION_DEFAULT` | `SERVICE_ACCOUNT_JSON_KEYFILE` | `USER_CREDENTIALS` | `ACCESS_TOKEN_PROVIDER` | `UNAUTHENTICATED`. Plus `fs.gs.auth.impersonation.service.account` (and `.for.user.<u>` / `.for.group.<g>`). `APPLICATION_DEFAULT` uses Java google-auth-library ADC, which supports WIF `external_account` configs. Source: <https://github.com/GoogleCloudDataproc/hadoop-connectors/blob/master/gcs/CONFIGURATION.md#authentication>
- **Components that cannot use pure ADC:** Spark executors on non-GCP clusters (on-prem Hadoop, other clouds) have no metadata server and no gcloud ADC file. Options, in recommended order:
  1. Use Managed Spark (serverless or permanent) instead. This is the default recommendation for BigQuery targets (`docs/user_guide.md:712`).
  2. Use GCS connector 3.x with `fs.gs.auth.type=APPLICATION_DEFAULT`. Distribute a **WIF credential configuration** (not a key) to every node. Set `spark.executorEnv.GOOGLE_APPLICATION_CREDENTIALS` and `spark.yarn.appMasterEnv.GOOGLE_APPLICATION_CREDENTIALS`. Optionally set `fs.gs.auth.impersonation.service.account`. This needs an external IdP token source on each node (OIDC file/URL/executable, AWS, or Azure). Source: <https://cloud.google.com/iam/docs/workload-identity-federation-with-other-providers>
  3. `ACCESS_TOKEN_PROVIDER` with a short-lived token minted by the driver. Requires custom code; not recommended.

  GOE cannot remove keys from this path on its own. It must document the alternatives and stop shipping/recommending key props.

### 3.7 spark-bigquery-connector

- Not used by GOE (zero hits). For reference, it defaults to ADC and supports `credentialsFile`, `gcpAccessToken`, and `gcpImpersonationServiceAccount*`. No action needed. Source: <https://github.com/GoogleCloudDataproc/spark-bigquery-connector#how-do-i-authenticate-outside-gce--dataproc>

### 3.8 google-github-actions/auth (CI)

- Three modes:
  1. Direct WIF (preferred by the action).
  2. WIF through a service account (`service_account` input → impersonation).
  3. SA key JSON.

  It requires `permissions: id-token: write` and must run after `actions/checkout`.
- `create_credentials_file` and `export_environment_variables` default to true. The action exports `GOOGLE_APPLICATION_CREDENTIALS`, `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE`, and `GOOGLE_GHA_CREDS_PATH`, plus project variables when `project_id` is given.
- `gsutil` does not use the exported credentials.
- The README warns that the GitHub OIDC token expires in 5 minutes.

Source: <https://github.com/google-github-actions/auth#readme>

## 4. Configuration model proposal

### 4.1 Environment variables

Current names found in `templates/conf/offload.env.template.bigquery`: `GOOGLE_APPLICATION_CREDENTIALS` (commented), `BACKEND_DISTRIBUTION=GCP`, `QUERY_ENGINE=BIGQUERY`, `BIGQUERY_DATASET_LOCATION`, `BIGQUERY_DATASET_PROJECT`, `GOOGLE_KMS_KEY_RING_PROJECT`, `GOOGLE_KMS_KEY_RING_LOCATION`, `GOOGLE_KMS_KEY_RING_NAME`, `GOOGLE_KMS_KEY_NAME`, `GOOGLE_DATAPROC_CLUSTER`, `GOOGLE_DATAPROC_PROJECT`, `GOOGLE_DATAPROC_REGION`, `GOOGLE_DATAPROC_SERVICE_ACCOUNT`, `GOOGLE_DATAPROC_BATCHES_VERSION`, `GOOGLE_DATAPROC_BATCHES_SUBNET`, `GOOGLE_DATAPROC_BATCHES_TTL`. `templates/conf/offload.env.template.snowflake:51` also has `#GOOGLE_APPLICATION_CREDENTIALS=`. (There is no single `offload.env.template`; templates are split per backend: `.common`, `.bigquery`, `.snowflake`, etc.)

| Action | Variable | Semantics |
|--------|----------|-----------|
| Keep | `BIGQUERY_DATASET_PROJECT`, `BIGQUERY_DATASET_LOCATION` | Dataset/table reference project and dataset-create location. |
| Keep | `GOOGLE_KMS_*` (4 vars) | CMEK. Unchanged. |
| Keep | `GOOGLE_DATAPROC_CLUSTER`, `GOOGLE_DATAPROC_PROJECT`, `GOOGLE_DATAPROC_REGION`, `GOOGLE_DATAPROC_BATCHES_*` | Unchanged. |
| Redefine | `GOOGLE_DATAPROC_SERVICE_ACCOUNT` | **Runtime** SA for serverless batches only (`--service-account`). No longer used for impersonation on the cluster path. |
| Remove from templates | `GOOGLE_APPLICATION_CREDENTIALS` | Not GOE-owned. ADC still honors it, so document it only for WIF credential-configuration files and never for SA keys. |
| Add (standard) | `GOOGLE_CLOUD_PROJECT` | Default/job project for BigQuery jobs and the GCS client. google-auth reads it natively; GOE should also read it explicitly and pass `project=`. |
| Add (standard) | `GOOGLE_CLOUD_QUOTA_PROJECT` | Quota/billing project for user/impersonated ADC. google-auth reads it natively. GOE passes it to `default(quota_project_id=...)` for clarity. |
| Add (GOE-defined) | `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` | Optional target SA. GOE wraps ADC in `impersonated_credentials.Credentials`, injects `--impersonate-service-account` (or `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT`) into gcloud subprocesses, and documents `fs.gs.auth.impersonation.service.account` for self-managed Spark. Note: google-auth does **not** read this name natively. |
| Optional (decision) | `GOOGLE_ALLOW_SERVICE_ACCOUNT_KEYS` (default `false`) | If ADC resolves to `service_account` key credentials: `connect` fails (or warns), and runtime logs a warning. Enables a strict "no keys" policy. |

Precedence for impersonation: if the ADC file is already `impersonated_service_account`, do not double-wrap. If `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is also set and differs, fail with a clear message.

### 4.2 Code shape (for the planning phase; no code written here)

- New module `src/goe/util/gcp_credentials.py`:
  - `resolve_gcp_credentials(config) -> GcpCredentialBundle`, a frozen dataclass with `credentials`, `project`, `quota_project`, `principal`, `credential_type`.
  - Process-level cache keyed on (impersonation target, project, quota project).
  - Scopes: `https://www.googleapis.com/auth/cloud-platform`.
  - `lifetime=3600`. Impersonated credentials refresh automatically.
- Consumers:
  - `_get_bq_client` (`credentials=`, `project=` job project)
  - `_get_kms_client` (`credentials=`)
  - `GOEGcs.__init__` (`credentials=`, `project=`)
  - `GOELogFileHandle._get_fs` (`token=credentials`, `project=`)
  - Dataproc transports (subprocess env/flag)
- `OrchestrationConfig`: add `google_cloud_project`, `google_cloud_quota_project`, `google_impersonate_service_account`, `google_dataproc_impersonate_service_account` to the expected-keys list (`orchestration_config.py:53-72`), the dataclass fields (`:221-240`), and `from_dict` (`:343+`). Defaults go in `orchestration_defaults.py`.
- All of the above stay lazily imported (`google.auth` import cost) to preserve the CLI startup budget.

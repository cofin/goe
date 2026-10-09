---
type: Reference
title: Configuration & Environment Variables
description: Comprehensive inventory of GOE configuration parameters, defaults, and validation rules
tags:
  - reference
  - operations
  - configuration
  - env
---

# Configuration & Environment Variables

GOE loads environment variables using a 4-tier discovery architecture via `python-dotenv` ([`src/goe/config/config_file.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/config/config_file.py)), merged and validated by `OrchestrationConfig`.

## Multi-Tier Configuration Discovery (`src/goe/config/config_file.py`)

1. **Tier 1 (Explicit Environment Override)**: Paths specified in `GOE_CONFIG_FILE` or `OFFLOAD_ENV_FILE`.
2. **Tier 2 (Configured Installation Root)**: `$OFFLOAD_HOME/conf/offload.env`.
3. **Tier 3 (Dynamic Workspace Hierarchy)**: Upward directory tree discovery using `find_dotenv("conf/offload.env", usecwd=True)` followed by `find_dotenv("offload.env", usecwd=True)`.
4. **Tier 4 (Standard Production System Paths)**: `/opt/goe/offload/conf/offload.env` and `/u01/app/goe/offload/conf/offload.env`.

### Variable Interpolation & Precedence Rules
- `load_env(override=False, interpolate=True)` preserves ambient container/shell environment variables while resolving `${VAR}` POSIX parameter expansions in definition order.
- **Auto-Export `OFFLOAD_HOME`**: When `OFFLOAD_HOME` is unset and the discovered configuration resides in a `conf/` directory, `load_env()` automatically exports `OFFLOAD_HOME` pointing to the parent installation root.
- **Test Isolation Guard**: Automatic discovery is skipped when `PYTEST_CURRENT_TEST` is present or `GOE_NO_AUTOLOAD_ENV` is set to `"1"`, `"true"`, or `"TRUE"`.

## Core Configuration Parameters

### Common Settings
- `OFFLOAD_HOME`: Absolute path to installation root (must contain `conf/`, `bin/`, `lib/`).
- `LOG_LEVEL`: Logging verbosity (`info`, `detail`, `debug`).
- `OFFLOAD_LOGDIR`: Directory for execution log files (local directory or GCS `gs://` URI).
- `PASSWORD_KEY_FILE`: AES key file used to decrypt encrypted database passwords or tokens.

### Frontend (Oracle) Settings
- `FRONTEND_DISTRIBUTION`: Source DB type (`ORACLE`, `MSSQL`, `TERADATA`). Default `ORACLE`.
- `ORA_CONN`: Oracle TNS connect descriptor (e.g. `host:1521/service`).
- `ORA_ADM_USER` / `ORA_ADM_PASS`: Administrative user (default `goe_adm`).
- `ORA_APP_USER` / `ORA_APP_PASS`: Operational user (default `goe_app`).
- `ORA_REPO_USER`: Repository schema owner (default `goe_repo`).
- `USE_ORACLE_WALLET`: `true` to authenticate via Oracle Wallet instead of plaintext passwords.
- `ORACLEDB_THICK_MODE`: Enables Oracle Instant Client for thick mode features.

### Backend (Google BigQuery) Settings
- `BACKEND_DISTRIBUTION`: Target cloud distribution (`GCP`, `SNOWFLAKE`, `MSAZURE`, `CDH`).
- `QUERY_ENGINE`: Target engine (`BIGQUERY`, `IMPALA`, `HIVE`).
- `BIGQUERY_DATASET_PROJECT`: GCP Project ID hosting BigQuery datasets.
- `BIGQUERY_DATASET_LOCATION`: Region for dataset creation (e.g. `US`, `EU`, `us-central1`).
- `GOOGLE_APPLICATION_CREDENTIALS`: Service account key file path (if not using GCE instance SA).
- `GOOGLE_KMS_KEY_NAME`: Cloud KMS key resource ID for CMEK encryption.

### Cloud Storage Settings
- `OFFLOAD_FS_SCHEME`: Cloud storage scheme (`gs`, `s3a`, `abfss`, `hdfs`). Default `gs`.
- `OFFLOAD_FS_CONTAINER`: Cloud storage bucket name for staging.
- `OFFLOAD_FS_PREFIX`: Root prefix folder inside the staging container (default `goe`).
- `OFFLOAD_STAGING_FORMAT`: Intermediate staging file format (`PARQUET` or `AVRO`).

### Transport & Spark Settings
- `OFFLOAD_TRANSPORT`: Transport method (`AUTO`, `GOE`, `GCP`, `SQOOP`).
- `OFFLOAD_TRANSPORT_PARALLELISM`: Degree of transport query parallelism / executors (default `2`).
- `OFFLOAD_TRANSPORT_FETCH_SIZE`: JDBC fetch size for batch extraction from Oracle (default `5000`).
- `OFFLOAD_TRANSPORT_CONSISTENT_READ`: `true` to enforce consistent Flashback SCN snapshot.
- `GOOGLE_DATAPROC_CLUSTER`: Dataproc cluster name for persistent cluster execution.
- `GOOGLE_DATAPROC_BATCHES_VERSION`: Dataproc Serverless runtime version (e.g. `2.0`, `2.1`).
- `GOOGLE_DATAPROC_BATCHES_SUBNET`: Subnet URI with Private Google Access enabled.

### Listener Settings (Embedded Architecture)
- `OFFLOAD_LISTENER_HOST` / `PORT`: Bind host and port (default `0.0.0.0:8085`).
- `OFFLOAD_LISTENER_SHARED_TOKEN`: API key required in `x-goe-console-key` header (when unset, allows unauthenticated local access).
- `OFFLOAD_LISTENER_HEARTBEAT_INTERVAL`: Periodic endpoint registration interval in seconds (default `30`).
- `OFFLOAD_LISTENER_WORKERS`: Number of Granian ASGI worker processes (default `1`).

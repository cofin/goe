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

GOE loads environment variables from `$OFFLOAD_HOME/conf/offload.env` using `python-dotenv`, merged and validated by `OrchestrationConfig`.

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

### Listener & Redis Settings
- `OFFLOAD_LISTENER_HOST` / `PORT`: Bind host and port (default `0.0.0.0:8085`).
- `OFFLOAD_LISTENER_SHARED_TOKEN`: API key required in `x-goe-console-key` header.
- `OFFLOAD_LISTENER_REDIS_HOST` / `PORT`: Redis host and port for caching and worker queues.

---
type: Reference
title: Snowflake Backend Adapter
description: Snowflake connector lifecycle, stages, storage integrations, and COPY INTO ingestion
tags:
  - reference
  - backends
  - snowflake
  - data-warehouse
---

# Snowflake Backend Adapter

The Snowflake backend adapter (`src/goe/offload/snowflake/`) manages target databases, schemas, stages, clustering keys, and `COPY INTO` data loading.

## Key Modules

- **`BackendSnowflakeApi` (`snowflake_backend_api.py`)**: Connection handling, storage integration, and session setup.
- **`BackendSnowflakeTable` (`snowflake_backend_table.py`)**: Table creation, stage management, and `COPY INTO` execution.
- **`SnowflakeColumn` & `SnowflakeLiteral`**: Column translation and SQL formatting.

## Connection & Security

- **SDK**: `snowflake-connector-python` (`snowflake.connector.connect`).
- **Authentication**: Password or encrypted RSA private key PEM file (PKCS#8 with passphrase).
- **Session Environment**:
  ```sql
  ALTER SESSION SET AUTOCOMMIT = TRUE;
  ALTER SESSION SET QUERY_TAG = 'GOE';
  ALTER SESSION SET TIMESTAMP_NTZ_OUTPUT_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF9';
  ```

## Staging & Ingestion Workflow

1. **Storage Integration & Stage**:
   ```sql
   CREATE STAGE IF NOT EXISTS schema.stage_name
   URL = 's3://bucket/prefix/'
   STORAGE_INTEGRATION = integration_name;
   ```
2. **File Format**:
   ```sql
   CREATE FILE FORMAT IF NOT EXISTS schema.format_name
   TYPE = PARQUET;
   ```
3. **Data Loading (`COPY INTO`)**:
   ```sql
   COPY INTO target_table (col1, col2, ...)
   FROM (
     SELECT $1:COL1::BIGINT, $1:COL2::VARCHAR, ...
     FROM @schema.stage_name/table/
   )
   FILE_FORMAT = (FORMAT_NAME => 'schema.format_name')
   PATTERN = '.*\.parquet';
   ```

## Clustering & Telemetry
- **Clustering**: `CLUSTER BY (col1, col2)`.
- **Query Profiling**: Interrogates `TABLE(information_schema.query_history_by_session())` using cursor query ID `sfqid`.

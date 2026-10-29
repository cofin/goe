---
type: Reference
title: Snowflake Backend Adapter
description: Snowflake connector lifecycle, SNOWFLAKE_CAPABILITIES, CachedBackendCatalog, DialectSqlEngine, stages, storage integrations, and COPY INTO ingestion
tags:
  - reference
  - backends
  - snowflake
  - data-warehouse
updated_at: "2026-10-26T22:40:00Z"
---

# Snowflake Backend Adapter

The Snowflake backend adapter (`src/goe/offload/snowflake/`) manages target databases, schemas, stages, clustering keys, cached metadata snapshots, and `COPY INTO` data loading.

## Key Modules

- **`BackendSnowflakeApi` (`src/goe/offload/snowflake/snowflake_backend_api.py`)**: Exposes `SNOWFLAKE_CAPABILITIES = BackendCapabilities.for_snowflake()`, routes `table_exists`, `get_columns`, `get_table_size`, `get_table_row_count_from_metadata`, and 2-query `warm_schema(db_name)` (`INFORMATION_SCHEMA.TABLES` + `INFORMATION_SCHEMA.COLUMNS`) through `CachedBackendCatalog`, renders SQL via `DialectSqlEngine("snowflake")`, and translates columns via `TYPE_REGISTRY` (`MappingTarget.SNOWFLAKE`).
- **`BackendSnowflakeTable` (`src/goe/offload/snowflake/snowflake_backend_table.py`)**: Coordinates table creation, stage/file-format management, `StagingLoadService` cast verification, and `COPY INTO` execution with write-through catalog invalidation.
- **`ColumnSpec` (`ColumnDialect.SNOWFLAKE`) & `SnowflakeLiteral`**: Column representation and SQL literal formatting.

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

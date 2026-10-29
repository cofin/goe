---
type: Reference
title: Apache Hadoop, Impala & Hive Backend Adapter
description: HiveServer2 Thrift connectivity, HIVE/IMPALA/SPARK_CAPABILITIES, CachedBackendCatalog, DialectSqlEngine, Parquet/ORC storage, and stats computation
tags:
  - reference
  - backends
  - hadoop
  - impala
  - hive
  - spark
updated_at: "2026-10-26T22:40:00Z"
---

# Apache Hadoop, Impala & Hive Backend Adapter

The Hadoop and Spark Thrift backend adapters (`src/goe/offload/hadoop/` and `src/goe/offload/spark/`) manage tables, partitions, and queries on Apache Hive, Impala, and Spark Thrift Server.

## Key Modules

- **`BackendHadoopApi` & `BackendHiveApi` (`src/goe/offload/hadoop/{hadoop_backend_api,hive_backend_api}.py`)**: Exposes `HIVE_CAPABILITIES = BackendCapabilities.for_hive()`, routes `table_exists`, `get_columns`, `get_partition_columns`, `get_table_size`, and `warm_schema(db_name)` through `CachedBackendCatalog`, renders SQL via `DialectSqlEngine("hive")`, and maps columns via `TYPE_REGISTRY` (`MappingTarget.HIVE`).
- **`BackendImpalaApi` (`src/goe/offload/hadoop/impala_backend_api.py`)**: Exposes `IMPALA_CAPABILITIES = BackendCapabilities.for_impala()`, maps columns via `TYPE_REGISTRY` (`MappingTarget.IMPALA`), and manages Impala-specific execution (`SHUFFLE`/`NOSHUFFLE` hints, `SORT BY`, incremental `COMPUTE STATS`).
- **`BackendSparkThriftApi` (`src/goe/offload/spark/spark_thrift_backend_api.py`)**: Exposes `SPARK_CAPABILITIES = BackendCapabilities.for_spark()`, renders SQL via `DialectSqlEngine("spark")`, and caches table existence and `DESCRIBE` column metadata in `CachedBackendCatalog`.
- **`BackendHadoopTable`, `BackendHiveTable`, & `BackendImpalaTable` (`src/goe/offload/hadoop/{hadoop_backend_table,hive_backend_table,impala_backend_table}.py`)**: HDFS/object-store table definitions, `HASH_BUCKET_EXPRESSION` (`PMOD(HASH(...))`), `StagingLoadService` / `FinalTableMerger` execution, and write-through catalog invalidation.

## Connection & Security

- **Driver**: `better_impyla` over HS2 Thrift protocol (Binary/TCP and HTTP transport).
- **Security**: Kerberos ticket authentication (SPNEGO / GSSAPI via `kinit`), LDAP auth, and TLS encryption.
- **Authorization Auditing**: Checks Apache Ranger (`SHOW GRANT USER ...`) and Apache Sentry (`SHOW GRANT ROLE ...`) policies.

## File Formats & Optimization

- **Storage Formats**: Apache Parquet, ORC, and Avro stored on HDFS, AWS S3 (`s3a://`), or Azure ADLS (`abfs://`).
- **Insertion**:
  - Hive: `INSERT INTO ... SELECT ... DISTRIBUTE BY cols SORT BY cols`.
  - Impala: `INSERT INTO ... [SHUFFLE]|[NOSHUFFLE] SELECT ...`.
- **Statistics**:
  - Impala: `COMPUTE INCREMENTAL STATS table [PARTITION (...)]`.
  - Hive: `ANALYZE TABLE table [PARTITION (...)] COMPUTE STATISTICS FOR COLUMNS`.

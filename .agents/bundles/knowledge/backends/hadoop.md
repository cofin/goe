---
type: Reference
title: Apache Hadoop, Impala & Hive Backend Adapter
description: HiveServer2 Thrift connectivity, Kerberos authentication, Parquet/ORC storage, and stats computation
tags:
  - reference
  - backends
  - hadoop
  - impala
  - hive
  - spark
---

# Apache Hadoop, Impala & Hive Backend Adapter

The Hadoop backend adapter (`src/goe/offload/hadoop/`) manages tables, partitions, and queries on Apache Hive, Impala, and Spark Thrift Server.

## Key Modules

- **`BackendHadoopApi` & `BackendHiveApi`**: HiveServer2 Thrift client, DDL execution, and insert queries.
- **`BackendImpalaApi`**: Impala-specific execution (`SHUFFLE`/`NOSHUFFLE` hints, incremental compute stats).
- **`BackendSparkThriftApi`**: Spark SQL execution over Thrift endpoints.
- **`HadoopBackendTable`**: HDFS table definitions, partition specifications, and formats.

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

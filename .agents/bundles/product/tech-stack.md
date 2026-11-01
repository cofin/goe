---
type: product
title: Technology Stack
description: Core programming languages, database drivers, SQL AST engines, cloud platforms, transport engines, and dependencies for GOE.
status: stable
tags:
  - product
  - tech-stack
  - dependencies
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: pyproject
    resource: pyproject.toml::project
    title: Project Metadata and Dependency Specification
  - id: ora-registry
    resource: src/goe/persistence/registry.py::OracleDatabaseRegistry
    title: Pooled SQLSpec Oracle Database Registry
  - id: dialect-engine
    resource: src/goe/offload/sql_ast/dialect_engine.py::DialectSqlEngine
    title: Native SQLGlot Dialect Engine and Oracle Dialect Extension
  - id: duckdb-engine
    resource: src/goe/offload/transport/duckdb/engine.py::DuckDBEngine
    title: DuckDB 2.0 Session and Cloud Secret Engine
---

# Technology Stack

<!-- truth: start -->
- **Language**: Python >= 3.12 (CPython) managed via `uv` and `hatchling.build`, with PEP 585/604 type annotations, `FrozenBaseStruct` / `BaseStruct` (`gc=False` in `src/goe/typing.py`), strict `mypy src/goe`, and `tools/verify_architecture.py`.[^pyproject]
- **Frontend Databases & SQL AST**: Oracle (`oracledb>=3.4.0`, pooled SQLSpec `OracleDatabaseRegistry`, `SQLFileLoader`, `OracleCatalogService`, `OracleRepositoryService`, `FrontendCatalogCache`), Microsoft SQL Server (`mssql-python` via SQLSpec `MssqlPythonConfig` and `mssql_catalog.sql`), and `DialectSqlEngine` (`sqlglot[c]>=30.17.0` with custom `GOEOracleDialect` in `src/goe/offload/sql_ast/dialect_engine.py`).[^ora-registry][^dialect-engine]
- **Cloud DW Backends**: Google BigQuery (`google-cloud-bigquery`, default `BigQueryLoadJobIngestStrategy` `load_table_from_uri` + `INFORMATION_SCHEMA.PARTITIONS`), Snowflake (`snowflake-connector-python`), Azure Synapse (`pyodbc`), and Apache Hadoop (`better_impyla`).
- **Storage Systems**: Unified `StagingStorageService` (`src/goe/filesystem/storage_service.py`) over `sqlspec.storage` (`obstore` for `gs://`, `s3://`, `abfss://`, `file://`), native cloud SDK adapters (`GOEGcs`, `GOES3`, `GOEAzure`), and `HdfsClient` (`hdfs://`, `webhdfs://`).
- **Data Transport & Serialization**: DuckDB (`duckdb>=2.0.0`, signed community `oracle` extension `cofin/duckdb-oracle`, built-in `httpfs` `TEMPORARY SECRET` over `gs://`/`s3://`/`abfss://`), `pyarrow>=20.0.0` (`OracleArrowBatchExtractor`, `ArrowParquetStagingWriter`), PySpark / Dataproc / Livy (`GOETaskListener`), `fastavro`, `msgspec>=0.22.0` (`src/goe/serializers.py`), and `sqlspec[performance,oracledb,adbc,duckdb]>=0.68.0`.[^duckdb-engine]
- **Listener & Observability**: Litestar (`>=2.25.0`), Vertebra ASGI runtime (`src/goe/listener/vertebra_gate.py`), Oracle-backed durable job queue (`OracleJobStore` + `DurableJobWorker` on `GOE_LISTENER_JOBS`), `litestar-security>=0.6.0`, `litestar-autowire>=0.2.0`, `litestar-mcp>=0.16.0` (stateless `2026-07-28` MCP, `ConfirmationGate`, `GOEResourcesController`, `GOEPromptController`, `MCPSkillsConfig`, `MCPTaskConfig`, `goe listener mcp {stdio,bridge,inspect}`), `httpx2>=2.16.0`, bounded LRU + singleflight `ListenerCache`, and OpenTelemetry (`opentelemetry-api>=1.40.0` + optional `otel` extra).
<!-- truth: end -->

## Subsystem Details

### Python Runtime & Core Libraries
- **Base Environment**: Python >= 3.12 managed with `uv` (`pyproject.toml` and `uv.lock`) and packaged via `hatchling.build`.[^pyproject]
- **CLI & Configuration**: Unified `rich-click` CLI (`goe` entrypoint in `src/goe/cli/main.py`) with zero-type-loss lazy binding (`src/goe/cli/_lazy.py`), declarative `OptionSpec` registry (`src/goe/config/option_registry.py`), `GOESettings` (`src/goe/config/settings.py`), and `msgspec.Struct` option models (`src/goe/config/options.py`).
- **Concurrency & Platform Utilities**: `filelock` (`src/goe/platform/locking.py`), `CgroupQuota` / `LocalProcessWorker` / `LameDuckController` (`src/goe/platform/worker.py`), and `run_bounded` (`src/goe/util/concurrency.py`).

### Frontend RDBMS & SQL AST Layer
- **Oracle**: `oracledb` (Thin mode default, Thick mode for Oracle Wallet / OCI features), pooled `OracleDatabaseRegistry` (`src/goe/persistence/registry.py`), `OracleCatalogService` (`src/goe/offload/oracle/catalog.py`), `OracleRepositoryService` (`src/goe/persistence/oracle/repository.py`), and `FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`).[^ora-registry]
- **Microsoft SQL Server**: `mssql-python` managed via SQLSpec `MssqlPythonConfig` and named SQL (`src/goe/offload/microsoft/sql/mssql_catalog.sql`) with deterministic `ARITHABORT ON`, `DATEFORMAT ymd`, and `ANSI_WARNINGS ON` session initialization.
- **SQL AST & Predicate Compilation**: `DialectSqlEngine` and `GOEOracleDialect` (`src/goe/offload/sql_ast/dialect_engine.py`) plus recursive-descent `PredicateParser` and `PredicateCompiler` (`src/goe/offload/predicates/`).[^dialect-engine]

### Data Transport, Staging & Cloud Backends
- **DuckDB 2.0 Data Plane**: `DuckDBEngine` (`src/goe/offload/transport/duckdb/engine.py`) over `sqlspec.adapters.duckdb.DuckDBConfig` with cgroup-aware 75% memory clamping, `:memory:goe_<execution_key>`, `oracle_pushdown.py` (`AS OF SCN` verification + EZConnect DSN), and `parquet_writer.py` (`COPY ... TO ... (FORMAT PARQUET)` over built-in `httpfs` secrets).[^duckdb-engine]
- **Arrow Parquet Query Import**: `OracleArrowBatchExtractor` and `ArrowParquetStagingWriter` (`src/goe/offload/transport/arrow_extractor.py` and `src/goe/offload/staging/arrow_writers.py`) powering `OffloadTransportQueryImport`.
- **Cloud Warehouses**: Google BigQuery (`BigQueryLoadJobIngestStrategy` and `BigQueryExternalTableIngestStrategy`), Snowflake (`BackendSnowflakeApi`), Azure Synapse (`BackendSynapseApi`), and Hadoop Hive/Impala (`BackendHiveApi`, `BackendImpalaApi`).

### Listener, MCP & Observability
- **ASGI Runtime & Job Queue**: Litestar (`src/goe/listener/app.py`) served via Vertebra (`src/goe/listener/vertebra_gate.py`), with `OracleJobStore` (`FOR UPDATE SKIP LOCKED` on `GOE_LISTENER_JOBS` and cooperative `CANCEL_REQUESTED` cancellation) and `DurableJobWorker` (`src/goe/listener/jobs/`).
- **MCP Surface**: Native `litestar-mcp>=0.16.0` (`src/goe/listener/mcp.py`) exposing `@mcp_tool` controllers, `GOEResourcesController` (`goe://`), `GOEPromptController`, `MCPSkillsConfig`, `ConfirmationGate`, and `goe listener mcp {stdio,bridge,inspect}`.
- **OpenTelemetry (`src/goe/observability/`)**: Zero-cost no-op default when `GOE_OTEL_ENABLED=false`; supports OTLP (`grpc` / `http/protobuf`), Google Cloud Telemetry API (`https://telemetry.googleapis.com` via `resolve_gcp_credentials`), and JSONL sidecar log correlation.

[^pyproject]: `pyproject.toml::project` — Package dependencies, optional extras (`gcp`, `snowflake`, `synapse`, `mssql`, `hadoop`, `spark`, `otel`), and tool configurations.
[^ora-registry]: `src/goe/persistence/registry.py::OracleDatabaseRegistry` — Pooled SQLSpec Oracle connection registry with one-time session initialization and `V$SESSION` tagging.
[^dialect-engine]: `src/goe/offload/sql_ast/dialect_engine.py::DialectSqlEngine` — Multi-dialect SQLGlot AST engine and custom `GOEOracleDialect`.
[^duckdb-engine]: `src/goe/offload/transport/duckdb/engine.py::DuckDBEngine` — DuckDB 2.0 session lifecycle, cgroup memory clamping, and `TEMPORARY SECRET` builder.

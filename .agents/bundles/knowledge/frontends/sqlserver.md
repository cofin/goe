---
type: concept
title: Microsoft SQL Server Frontend Adapter
description: SQLSpec MssqlPythonConfig (mssql-python), named catalog SQL, MssqlTableCatalogSnapshot, FrontendCatalogCache, and ColumnSpec type mapping for SQL Server.
status: stable
tags:
  - frontends
  - sqlserver
  - mssql
  - database
  - sqlspec
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: mssql-api
    resource: src/goe/offload/microsoft/mssql_frontend_api.py::MSSQLFrontendApi
    title: SQL Server Frontend API over SQLSpec MssqlPythonConfig
  - id: mssql-table
    resource: src/goe/offload/microsoft/mssql_offload_source_table.py::MSSQLSourceTable
    title: SQL Server Offload Source Table
  - id: column-spec
    resource: src/goe/offload/schema/column_spec.py::ColumnSpec
    title: Canonical ColumnSpec with MSSQL Dialect Support
---

# Microsoft SQL Server Frontend Adapter

<!-- truth: start -->
- `MSSQLFrontendApi` (`src/goe/offload/microsoft/mssql_frontend_api.py`) uses `mssql-python` via `sqlspec.adapters.mssql.MssqlPythonConfig` (`pymssql` is removed) and executes named catalog queries from `src/goe/offload/microsoft/sql/mssql_catalog.sql`.[^mssql-api]
- `MssqlTableCatalogSnapshot` is cached in `FrontendCatalogCache` (`db_type="mssql"`) and invalidated automatically on `execute_ddl()`.
- SQL Server column metadata uses `ColumnSpec` (`ColumnDialect.MSSQL` in `src/goe/offload/schema/column_spec.py`) and `TYPE_REGISTRY` (`MappingTarget.MSSQL` in `src/goe/offload/schema/type_registry.py`).[^column-spec]
<!-- truth: end -->

## Key Modules

- **`MSSQLFrontendApi` & `MssqlTableCatalogSnapshot` (`src/goe/offload/microsoft/mssql_frontend_api.py`)**: `sqlspec.adapters.mssql.MssqlPythonConfig` construction (`build_mssql_config`), session initialization (`setup_mssql_session`), `NamedStatements` catalog execution from `src/goe/offload/microsoft/sql/mssql_catalog.sql`, and `FrontendCatalogCache`-backed `get_table_snapshot(schema_name, table_name)`.[^mssql-api]
- **`MSSQLSourceTable` (`src/goe/offload/microsoft/mssql_offload_source_table.py`)**: Source table metadata hydrated from `MssqlTableCatalogSnapshot` on a single cacheable lookup and canonical column type translation (`to_canonical_column` / `from_canonical_column`).[^mssql-table]
- **`ColumnSpec` (`ColumnDialect.MSSQL` in `src/goe/offload/schema/column_spec.py`)**: MSSQL column model (`BIGINT`, `BIT`, `CHAR`, `DATE`, `DATETIME`, `DATETIME2`, `DATETIMEOFFSET`, `DECIMAL`, `FLOAT`, `INT`, `MONEY`, `NCHAR`, `NUMERIC`, `NVARCHAR`, `REAL`, `SMALLDATETIME`, `SMALLINT`, `SMALLMONEY`, `TIME`, `TINYINT`, `UNIQUEIDENTIFIER`, `VARBINARY`, `VARCHAR`).[^column-spec]
- **`OffloadTransportMSSQLApi` (`src/goe/offload/microsoft/mssql_offload_transport_rdbms_api.py`)**: Spark/JDBC extraction queries (`jdbc:sqlserver://...`), split-column expressions, and snapshot isolation helpers.

## Connection & Session Initialization

- **Driver**: `mssql-python` via `sqlspec.adapters.mssql.MssqlPythonConfig` (declared in `pyproject.toml` under the `sql_server` and `mssql` optional extras).
- **DSN Normalization**: `build_mssql_config()` parses GOE's semicolon-delimited `rdbms_dsn` (`server=host;port=1433;database=db;...` or `host:port;databaseName=db`) into `MssqlPythonConfig(connection_config=..., statement_config=..., observability_config=..., driver_features={"on_connection_create": setup_mssql_session})`.
- **Named Catalog SQL (`src/goe/offload/microsoft/sql/mssql_catalog.sql`)**:
  - 9 named catalog queries (`fetch_server_version`, `check_schema_exists`, `check_table_exists`, `check_view_exists`, `fetch_table_columns`, `fetch_primary_key_columns`, `fetch_table_details`, `fetch_table_size_bytes`, `fetch_hash_bucket_candidate`) using `qmark` (`?`) positional bind parameters.

## Sizing & Catalog Snapshot Caching

- **Consolidated Snapshot (`MssqlTableCatalogSnapshot`)**: `MSSQLFrontendApi.get_table_snapshot(schema_name, table_name)` populates `table_exists`, `num_rows`, `partitioned`, `size_bytes`, `columns`, `primary_key_columns`, and `hash_bucket_candidate` and caches the result in `FrontendCatalogCache` (`db_type="mssql"`), invalidating on `execute_ddl()`.[^mssql-api]
- **Slicing Strategies**:
  - `SPLIT_BY_MOD`: Parallel extraction via `ABS(CHECKSUM(col)) % parallelism = split_id`.
  - `SPLIT_BY_ID_RANGE`: Boundary splitting on integer primary keys.

[^mssql-api]: `src/goe/offload/microsoft/mssql_frontend_api.py::MSSQLFrontendApi` — SQL Server frontend adapter over SQLSpec `MssqlPythonConfig`.
[^mssql-table]: `src/goe/offload/microsoft/mssql_offload_source_table.py::MSSQLSourceTable` — SQL Server source table metadata and column mapping.
[^column-spec]: `src/goe/offload/schema/column_spec.py::ColumnSpec` — Canonical `ColumnSpec` model supporting `ColumnDialect.MSSQL`.

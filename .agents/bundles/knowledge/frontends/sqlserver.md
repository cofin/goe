---
type: Reference
title: Microsoft SQL Server Frontend Adapter
description: SQLSpec MssqlPythonConfig (mssql-python), named catalog SQL, MssqlTableCatalogSnapshot, FrontendCatalogCache, and type mapping for SQL Server
tags:
  - reference
  - frontends
  - sqlserver
  - mssql
  - database
  - sqlspec
---

# Microsoft SQL Server Frontend Adapter

The SQL Server frontend adapter (`src/goe/offload/microsoft/`) provides connectivity, SQLSpec-backed catalog inspection, snapshot caching, and data extraction for Microsoft SQL Server databases.

## Key Modules

- **`MSSQLFrontendApi` & `MssqlTableCatalogSnapshot` (`src/goe/offload/microsoft/mssql_frontend_api.py`)**: `sqlspec.adapters.mssql.MssqlPythonConfig` construction (`build_mssql_config`), session initialization (`setup_mssql_session`), `NamedStatements` catalog execution from `src/goe/offload/microsoft/sql/mssql_catalog.sql`, and `FrontendCatalogCache`-backed `get_table_snapshot(schema_name, table_name)`.
- **`MSSQLSourceTable` (`src/goe/offload/microsoft/mssql_offload_source_table.py`)**: Source table metadata hydrated from `MssqlTableCatalogSnapshot` on a single cacheable lookup and canonical column type translation (`to_canonical_column` / `from_canonical_column`).
- **`MSSQLColumn` (`src/goe/offload/microsoft/mssql_column.py`)**: MSSQL column model (`BIGINT`, `BIT`, `CHAR`, `DATE`, `DATETIME`, `DATETIME2`, `DATETIMEOFFSET`, `DECIMAL`, `FLOAT`, `INT`, `MONEY`, `NCHAR`, `NUMERIC`, `NVARCHAR`, `REAL`, `SMALLDATETIME`, `SMALLINT`, `SMALLMONEY`, `TIME`, `TINYINT`, `UNIQUEIDENTIFIER`, `VARBINARY`, `VARCHAR`).
- **`OffloadTransportMSSQLApi` (`src/goe/offload/microsoft/mssql_offload_transport_rdbms_api.py`)**: Spark/JDBC extraction queries (`jdbc:sqlserver://...`), split-column expressions, and snapshot isolation helpers (`sqoop_rdbms_specific_*` methods removed).

## Connection & Session Initialization

- **Driver**: `mssql-python` via `sqlspec.adapters.mssql.MssqlPythonConfig` (declared in `pyproject.toml` under the `sql_server` and `mssql` optional extras; `pymssql` has been removed).
- **DSN Normalization**: `build_mssql_config()` parses GOE's semicolon-delimited `rdbms_dsn` (`server=host;port=1433;database=db;...` or `host:port;databaseName=db`) into `MssqlPythonConfig(connection_config=..., statement_config=..., observability_config=..., driver_features={"on_connection_create": setup_mssql_session})`.
- **Named Catalog SQL (`src/goe/offload/microsoft/sql/mssql_catalog.sql`)**:
  - 9 named catalog queries (`fetch_server_version`, `check_schema_exists`, `check_table_exists`, `check_view_exists`, `fetch_table_columns`, `fetch_primary_key_columns`, `fetch_table_details`, `fetch_table_size_bytes`, `fetch_hash_bucket_candidate`) using `qmark` (`?`) positional bind parameters (`sqlspec` compiles `:named` binds in `mssql_catalog.sql` to `?` for `mssql-python` when needed, or accepts direct `?` tuples).

## Sizing & Catalog Snapshot Caching

- **Consolidated Snapshot (`MssqlTableCatalogSnapshot`)**: `MSSQLFrontendApi.get_table_snapshot(schema_name, table_name)` populates `table_exists`, `num_rows`, `partitioned`, `size_bytes`, `columns: tuple[MSSQLColumn, ...]`, `primary_key_columns: tuple[str, ...]`, and `hash_bucket_candidate: str | None` and caches the result in `FrontendCatalogCache` (`db_type="mssql"`), invalidating on `execute_ddl()`.
- **Slicing Strategies**:
  - `SPLIT_BY_MOD`: Parallel extraction via `ABS(CHECKSUM(col)) % parallelism = split_id`.
  - `SPLIT_BY_ID_RANGE`: Boundary splitting on integer primary keys.

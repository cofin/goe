---
type: Reference
title: Azure Synapse Analytics Backend Adapter
description: SQLSpec MssqlPythonConfig connectivity, SYNAPSE_CAPABILITIES, CachedBackendCatalog, PolyBase/COPY INTO ingestion, clustered columnstore indexing, and distributions
tags:
  - reference
  - backends
  - synapse
  - azure
  - data-warehouse
updated_at: "2026-10-26T22:40:00Z"
---

# Azure Synapse Analytics Backend Adapter

The Azure Synapse adapter (`src/goe/offload/microsoft/`) manages Dedicated and Serverless SQL Pools on Microsoft Azure Synapse Analytics.

## Key Modules

- **`BackendSynapseApi` & `build_synapse_mssql_config` (`src/goe/offload/microsoft/synapse_backend_api.py`)**: Exposes `SYNAPSE_CAPABILITIES = BackendCapabilities.for_synapse()`, builds `sqlspec.adapters.mssql.MssqlPythonConfig` (`MssqlPythonPoolParams`) for Synapse sessions, routes `table_exists`, `get_columns`, `get_partition_columns`, `get_table_size`, `get_table_row_count_from_metadata`, and 2-query `warm_schema(db_name)` (`INFORMATION_SCHEMA.TABLES` + `INFORMATION_SCHEMA.COLUMNS`) through `CachedBackendCatalog`, renders SQL via `DialectSqlEngine("tsql")`, and translates columns via `TYPE_REGISTRY` (`MappingTarget.SYNAPSE`).
- **`BackendSynapseTable` (`src/goe/offload/microsoft/synapse_backend_table.py`)**: Coordinates PolyBase external table creation, `StagingLoadService` / `FinalTableMerger` data loading, and statistics initialization with write-through catalog invalidation.
- **`ColumnSpec` (`ColumnDialect.SYNAPSE`) & `SynapseLiteral`**: Column representation and SQL literal formatting.

## Connection & Authentication

- **Driver**: `sqlspec.adapters.mssql` (`MssqlPythonConfig` / `mssql-python`) via `build_synapse_mssql_config()`, with optional `pyodbc` fallback for custom ODBC drivers.
- **Authentication Modes**:
  - `ActiveDirectoryMsi` (Azure Managed Identity).
  - `ActiveDirectoryServicePrincipal` (App ID + Secret).
  - `SqlPassword` / `ActiveDirectoryPassword`.
- **DATETIMEOFFSET Unpacking**: Unpacks binary `DATETIMEOFFSET` structs (`struct.unpack("<6hI2h", dto)`).

## Table Architecture & Distributions

- **Index Types**:
  - `CLUSTERED COLUMNSTORE INDEX ORDER (sort_cols)` (Default).
  - `HEAP` (automatically selected for tables containing `VARCHAR(MAX)` or `VARBINARY(MAX)`).
- **Distribution Modes**:
  - `ROUND_ROBIN` (Default for general tables).
  - `HASH(distribution_column)` (For large joined dimension/fact tables).
  - `REPLICATE` (For small lookup tables).
- **Staging**: Uses PolyBase external tables or `COPY INTO` from ADLS Gen2 (`abfss://`).

---
type: Reference
title: Microsoft SQL Server Frontend Adapter
description: Driver lifecycle, metadata extraction, session initializers, space sizing, and type mapping for SQL Server
tags:
  - reference
  - frontends
  - sqlserver
  - mssql
  - database
---

# Microsoft SQL Server Frontend Adapter

The SQL Server frontend adapter (`src/goe/offload/microsoft/`) provides connectivity, metadata inspection, and data extraction for Microsoft SQL Server databases.

## Key Modules

- **`MSSQLFrontendApi` (`mssql_frontend_api.py`)**: Connection handling and session configuration.
- **`MSSQLSourceTable` (`mssql_offload_source_table.py`)**: Catalog inspection (`sys.tables`, `sys.columns`, `INFORMATION_SCHEMA`).
- **`OffloadTransportMSSQLApi` (`mssql_offload_transport_rdbms_api.py`)**: Slicing and parallel query formulation.

## Connection & Session Initialization

- **Driver**: `pymssql`.
- **Session Environment**:
  ```sql
  SET ARITHABORT ON;
  SET NUMERIC_ROUNDABORT OFF;
  SET DATEFORMAT ymd;
  SET CONCAT_NULL_YIELDS_NULL ON;
  SET ANSI_WARNINGS ON;
  SET ANSI_PADDING ON;
  SET ANSI_NULLS ON;
  ```

## Sizing & Catalog Inspection

- **Space Sizing**: Uses system stored procedure `sp_spaceused [schema.table]` to compute data space, index space, and reserved bytes.
- **Partitioning**: Interrogates `sys.partition_schemes`, `sys.partition_functions`, and `sys.partitions`.
- **Statistics**: Interrogates `sp_autostats` and `DBCC SHOW_STATISTICS`.

## Slicing Strategies
- `SPLIT_BY_MOD`: Parallel extraction via `ABS(CHECKSUM(col)) % parallelism = split_id`.
- `SPLIT_BY_ID_RANGE`: Boundary splitting on integer primary keys.

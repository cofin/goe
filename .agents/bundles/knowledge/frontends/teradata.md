---
type: Reference
title: Teradata Frontend Adapter
description: ODBC lifecycle, metadata extraction, batch parameter streaming, and RANGE_N partition parsing
tags:
  - reference
  - frontends
  - teradata
  - database
---

# Teradata Frontend Adapter

The Teradata frontend adapter (`src/goe/offload/teradata/`) provides connectivity, metadata inspection, and data extraction for Teradata RDBMS.

## Key Modules

- **`TeradataFrontendApi` (`teradata_frontend_api.py`)**: Connection handling and DDL extraction.
- **`TeradataSourceTable` (`teradata_offload_source_table.py`)**: Data dictionary inspection (`DBC.ColumnsV`, `DBC.PartitioningConstraintsV`).
- **`OffloadTransportTeradataApi` (`teradata_offload_transport_rdbms_api.py`)**: Slicing and extraction queries.

## Connection & Batch Handling

- **Driver**: `pyodbc` over Teradata ODBC Driver.
- **Fast DML**: Utilizes `_fast_executemany_dml` with `fast_executemany = True`, enforcing a 7MB maximum parameter payload batch limit.
- **Timezone**: Sets `SET TIME ZONE '00:00'`.

## Partitioning & DDL Extraction

- **Partition Expression Parsing**: Regular expression parsing of Teradata partition expressions (`RANGE_N(col BETWEEN start AND end EACH step)`).
- **DDL Extraction**: `SHOW TABLE [db.table]` and `SHOW VIEW [db.view]`.

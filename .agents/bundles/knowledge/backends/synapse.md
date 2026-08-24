---
type: Reference
title: Azure Synapse Analytics Backend Adapter
description: Dedicated/Serverless SQL pools, PolyBase, clustered columnstore indexing, and distributions
tags:
  - reference
  - backends
  - synapse
  - azure
  - data-warehouse
---

# Azure Synapse Analytics Backend Adapter

The Azure Synapse adapter (`src/goe/offload/microsoft/synapse_backend_api.py`) manages Dedicated and Serverless SQL Pools on Microsoft Azure Synapse Analytics.

## Key Modules

- **`BackendSynapseApi` (`synapse_backend_api.py`)**: Connection handling and DDL generation.
- **`BackendSynapseTable` (`synapse_backend_table.py`)**: PolyBase external table creation and data loading.
- **`SynapseColumn` & `SynapseLiteral`**: Column translation and PyODBC converters.

## Connection & Authentication

- **Driver**: `pyodbc` connecting to Synapse SQL Endpoint.
- **Authentication Modes**:
  - `ActiveDirectoryMsi` (Azure Managed Identity).
  - `ActiveDirectoryServicePrincipal` (App ID + Secret).
  - `SqlPassword` / `ActiveDirectoryPassword`.
- **Custom PyODBC Converters**: Unpacks `DATETIMEOFFSET` binary structs (`struct.unpack("<6hI2h", dto)`).

## Table Architecture & Distributions

- **Index Types**:
  - `CLUSTERED COLUMNSTORE INDEX ORDER (sort_cols)` (Default).
  - `HEAP` (automatically selected for tables containing `VARCHAR(MAX)` or `VARBINARY(MAX)`).
- **Distribution Modes**:
  - `ROUND_ROBIN` (Default for general tables).
  - `HASH(distribution_column)` (For large joined dimension/fact tables).
  - `REPLICATE` (For small lookup tables).
- **Staging**: Uses PolyBase external tables or `COPY INTO` from ADLS Gen2 (`abfss://`).

---
type: Reference
title: Frontend RDBMS Adapters
description: Database connection lifecycle, catalog metadata, partitioning, and SQL dialects for source RDBMS
tags:
  - reference
  - frontends
  - database
  - index
---

# Frontend RDBMS Adapters

This section documents the frontend database adapters supported by GOE.

## Adapters

- [Oracle Adapter](oracle.md) - `oracledb` driver, SCN snapshot extraction, PL/SQL packages, partitioning discovery, and extent chunking.
- [SQL Server Adapter](sqlserver.md) - `pymssql` driver, session initialization, space sizing, and catalog extraction.
- [Teradata Adapter](teradata.md) - `pyodbc` driver, fast parameter streaming, and `RANGE_N` partition parsing.

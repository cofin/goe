---
type: Reference
title: Database Installation & Object Lifecycle
description: Oracle DDL scripts, user security grants, repository tables, PL/SQL packages, and migration deltas
tags:
  - reference
  - operations
  - oracle
  - database
  - sql
---

# Database Installation & Object Lifecycle

The database setup scripts in `sql/oracle/source/` manage the installation, upgrade, and maintenance of GOE repository objects in Oracle.

## Schemas & User Privileges

- `goe_adm`: Administrative schema owner of packages and repository tables.
- `goe_app`: Runtime user granted `SELECT ANY TABLE`, `FLASHBACK ANY TABLE`, `SELECT ANY DICTIONARY`, and `EXECUTE` on GOE packages.
- `goe_repo`: Owner of repository views and public synonyms.

## Repository Tables (`create_offload_repo_100.sql`)

- `backend_object`: Registry of target tables created on BigQuery/Cloud storage.
- `command_execution`: Audit log of executions with UUID, timestamps, status, log paths, and JSON options.
- `command_execution_step`: Detailed timings, statuses, and exceptions for individual command steps.
- `hybrid_view`: Metadata definitions linking source Oracle tables to backend offloaded datasets.

## Core Lifecycle Scripts

- `install_offload.sql`: Installs schemas, tables, views, sequences, packages, and grants.
- `upgrade_offload.sql`: Applies schema deltas (`upgrade_offload_repo_deltas.sql`), re-compiles updated packages, and stamps the new version.
- `uninstall_offload.sql`: Drops packages, synonyms, and repository structures upon confirmation.

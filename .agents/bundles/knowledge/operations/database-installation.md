---
type: concept
title: Database Installation & Object Lifecycle
description: Oracle DDL scripts, user security grants, repository tables, PL/SQL packages, and migration deltas.
status: stable
tags:
  - reference
  - operations
  - oracle
  - database
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: ora-repo
    resource: src/goe/persistence/oracle/repository.py::OracleRepositoryService
    title: Oracle Repository Service
---

# Database Installation & Object Lifecycle

<!-- truth: start -->
- Oracle repository DDL and PL/SQL package scripts (`install_offload.sql`, `upgrade_offload.sql`, `uninstall_offload.sql`) are packaged inside the wheel at `src/goe/persistence/oracle/ddl/`.[^ora-repo]
- CI Oracle Free container bootstrap is automated via `tools/scripts/bootstrap_oracle_ci.sh` (`gvenzl/oracle-free:23-slim-faststart`).
<!-- truth: end -->

The database setup scripts packaged in `src/goe/persistence/oracle/ddl/` manage the installation, upgrade, and maintenance of GOE repository objects in Oracle.

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

[^ora-repo]: `src/goe/persistence/oracle/repository.py::OracleRepositoryService` — Oracle Repository Service.

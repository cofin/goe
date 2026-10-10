---
type: Spec
flow_id: sqlspec_oracle_data_layer_migration_20261010
title: "Chapter 3.1: SQLSpec Oracle Data Layer Migration"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-10T16:35:00Z
description: "Migrate GOE's Oracle repository client, OracleQuery utility, and OracleFrontendApi metadata queries to SQLSpec OracleSyncConfig and SQLFileLoader (using sqlspec[performance,oracledb,adbc,duckdb]) with msgspec.Struct row hydration, zero feature loss, and aggressive dead-code deletion."
tags: [refactor, sqlspec, oracle, persistence, frontend]
parent_prd: prd_03_sqlspec_bigquery_and_duckdb_engine_20261010
research:
  - .agents/bundles/research/sql_generation_and_dialects/research.md
---

# Chapter 3.1: SQLSpec Oracle Data Layer Migration

## Specification

## 1. Objective & Scope

Migrate GOE's Oracle database execution and repository persistence layer onto **SQLSpec** (`sqlspec.adapters.oracledb.OracleSyncConfig` and `sqlspec.loader.SQLFileLoader`, configured in `pyproject.toml` as `sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0` without the `mypyc` extra) while **preserving 100% of Oracle enterprise connection and runtime features** and **aggressively deleting replaced inline SQL strings, manual cursor row-zipping loops, and legacy `sqlspec_client` scaffold artifacts**.

### Key Deliverables
1. **Oracle Gateway, Named Repository SQL & Legacy Scaffold Cleanup (`Task 1.1`)**:
   - Ensure `pyproject.toml` specifies `sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0` (using only the `performance` extra group, dropping `mypyc`).
   - Create `src/goe/persistence/oracle_gateway.py` providing `OracleGateway`, a clean gateway around `OracleSyncConfig`, `OracleSyncDriver`, and `SQLFileLoader` that supports both config-managed sessions and wrapping an existing `oracledb.Connection`, enforces `NAMED_COLON` (`:name`) bind dictionaries, configures lowercase column keys, and provides a full PL/SQL (`OUT` binds, refcursors, `oracledb.DB_TYPE_OBJECT`) execution bridge.
   - Delete any lingering `src/goe/persistence/sqlspec_client.py` or `src/goe/persistence/__pycache__/sqlspec_client*.pyc` scaffold artifacts.
   - Externalize all inline f-string SQL queries from `src/goe/persistence/oracle/oracle_orchestration_repo_client.py` (`get_offloadable_schemas`, `get_schema_tables`, `get_table_columns`, `get_table_partitions`, `get_table_subpartitions`, `get_command_step_codes`, `get_command_executions`, `get_command_execution`, `get_command_execution_steps`) into `src/goe/persistence/sql/oracle_repo.sql` loaded via `SQLFileLoader`.
2. **Typed `msgspec.Struct` Hydration & Dead-Code Deletion in `OracleOrchestrationRepoClient` (`Task 1.2`)**:
   - Expand `src/goe/persistence/schemas.py` with `msgspec.Struct` projection models (`OffloadableSchema`, `SchemaTableDetail`, `CommandExecutionRecord`, `CommandExecutionStepRecord`) and `from_row(cls, row: Mapping[str, Any])` hydration on `ColumnDetail`, `PartitionDetail`, and `SubPartitionDetail`.
   - Refactor `src/goe/persistence/oracle/oracle_orchestration_repo_client.py` (`L83-1035`) to execute all repository queries and PL/SQL / `DB_TYPE_OBJECT` calls through `OracleGateway`, and **delete all 550+ lines of inline f-string SQL and raw cursor `.var(int)` boilerplate**.
3. **`OracleQuery` & `OracleFrontendApi` Metadata SQL Migration (`Task 1.3`)**:
   - Refactor `src/goe/util/ora_query.py` (`L40-364`) to delegate query execution and row projection to `OracleGateway` while preserving 100% of thick/thin mode, Wallet/LDAP/TNS/EZConnect, `fromcursor`, `fromconnection`, and `output_type_handler` (`DB_TYPE_LONG` -> `DB_TYPE_LONG_STRING`, `DB_TYPE_LONG_RAW`) behavior.
   - Externalize all 17 static data-dictionary SQL queries in `src/goe/offload/oracle/oracle_frontend_api.py` (`L553-1054`) into `src/goe/offload/oracle/sql/frontend_metadata.sql` via `SQLFileLoader`, **delete the inline SQL literals and manual `[col[0] for col in curs.description]` row-zipping loops**, and preserve 100% of Wallet/Proxy auth (`[%s]`), `MODULE`/`ACTION`/`TRACEFILE_IDENTIFIER` instrumentation, and `ORA-02396`/`ORA-03113`/`ORA-03114`/`ORA-03135` sniped-session reconnect (`#259`) with clean exception handling.
   - Note: Oracle extraction row-source queries (`AS OF SCN`, `PARTITION`, `SUBPARTITION`) in `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py` are migrated in Chapter 3.2 (`sqlglot_ast_and_predicate_engine_20261010:1.2`) via the custom upstreamable `src/goe/offload/oracle/oracle_dialect.py` (`OracleExtractionQueryProtocol` / `OracleSqlEngine`).

---

## 2. Technical Architecture & Invariants

1. **SQLSpec Extras (`performance`, Not `mypyc`)**:
   - `pyproject.toml` declares `sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0` (only the `performance` extra group, not `mypyc`).
2. **Zero Feature Loss Across Oracle Enterprise Modes**:
   - Preserve thick-client (`oracledb.init_oracle_client`) and thin-client modes, Oracle Wallet (`use_oracle_wallet` / external auth), proxy user syntax (`ora_adm_user[proxy_user]`), `SYSDBA`/`SYSOPER` privileges, `output_type_handler` for `LONG` / `LONG RAW`, `MODULE` / `ACTION` / `TRACEFILE_IDENTIFIER` session tagging, `ORA-02396`/`ORA-03113`/`ORA-03114`/`ORA-03135` reconnect (`#259`), and PL/SQL `OUT` binds / refcursors / Oracle object types (`OFFLOAD_METADATA_OBJ`, `OFFLOAD_PARTITION_LIST_IOT`).
3. **Aggressive Dead-Code Deletion**:
   - Delete all inline SQL strings moved to `src/goe/persistence/sql/oracle_repo.sql` and `src/goe/offload/oracle/sql/frontend_metadata.sql`.
   - Delete replaced raw cursor row-zipping loops (`[col[0] for col in curs.description]` / `dict(zip(cols, row))`) in `OracleOrchestrationRepoClient`, `OracleQuery`, and `OracleFrontendApi`.
   - Delete any leftover `sqlspec_client.py` / `sqlspec_client.*.pyc` scaffold artifacts.
4. **Never Mix Positional and Named Parameters**:
   - SQLSpec's `ParameterValidator` discards positional binds when named binds are present. Every Oracle SQLSpec query must use `:param_name` placeholders and pass a `dict[str, Any]` of named parameters (including converting `get_offloadable_schemas` f-string user exclusions at `oracle_orchestration_repo_client.py:463` to `:adm_user`, `:app_user`, `:repo_user`).

---

## 3. Task Breakdown & File Ownership

| Task ID | Title | Strategy | Depends On | Files Owned | Tests Owned |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `1.1` | Create `OracleGateway`, externalize repository SQL to `oracle_repo.sql`, and remove legacy `sqlspec_client` scaffold | `behavior_tdd` | `[]` | `pyproject.toml`, `src/goe/persistence/oracle_gateway.py`, `src/goe/persistence/sql/oracle_repo.sql` | `tests/unit/persistence/test_oracle_gateway.py` |
| `1.2` | Migrate `OracleOrchestrationRepoClient` and `schemas.py` to `OracleGateway` + `msgspec.Struct` and delete inline SQL | `characterization` | `["sqlspec_oracle_data_layer_migration_20261010:1.1"]` | `src/goe/persistence/schemas.py`, `src/goe/persistence/oracle/oracle_orchestration_repo_client.py` | `tests/unit/persistence/test_oracle_orchestration_repo_client.py` |
| `1.3` | Migrate `OracleQuery` and `OracleFrontendApi` metadata SQL with dead-code removal | `characterization` | `["sqlspec_oracle_data_layer_migration_20261010:1.1"]` | `src/goe/util/ora_query.py`, `src/goe/offload/oracle/oracle_frontend_api.py`, `src/goe/offload/oracle/sql/frontend_metadata.sql` | `tests/unit/offload/test_frontend_api.py` |

## Implementation Plan

- [ ] 1.1 Update `pyproject.toml` to `sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0`, create `OracleGateway` (`src/goe/persistence/oracle_gateway.py`), externalize repository queries into `src/goe/persistence/sql/oracle_repo.sql`, remove any legacy `sqlspec_client` scaffold artifacts, and verify in `tests/unit/persistence/test_oracle_gateway.py`.
- [ ] 1.2 Expand `src/goe/persistence/schemas.py` and migrate `src/goe/persistence/oracle/oracle_orchestration_repo_client.py` to `OracleGateway` + `SQLFileLoader`, deleting all inline SQL blocks and raw cursor `OUT`-bind boilerplate, verified in `tests/unit/persistence/test_oracle_orchestration_repo_client.py`.
- [ ] 1.3 Refactor `src/goe/util/ora_query.py` and externalize dictionary queries from `src/goe/offload/oracle/oracle_frontend_api.py` into `src/goe/offload/oracle/sql/frontend_metadata.sql` (deleting inline SQL and manual row-zipping loops while preserving Wallet/Proxy/reconnect/`#259`), verified in `tests/unit/offload/test_frontend_api.py`.

## Continuity Snapshot

- **Current State**: Planned (`plan_revision: 1`).
- **Next Action**: Execute Task `1.1` (`sqlspec_oracle_data_layer_migration_20261010:1.1`).

---
type: Spec
flow_id: oracle_database_registry_and_session_tracing_20261024
title: "Chapter 6.1: OracleDatabaseRegistry and Session Tracing"
state: completed
plan_revision: 1
plan_commit: null
state_revision: 1
current_task: null
last_operation: completed
operation_targets:
  - "1.1"
  - "1.2"
  - "1.3"
  - "1.4"
last_verified_checkpoint: "1.4"
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-25T15:42:00Z
description: "Replace per-query OracleGateway drivers and per-cursor ALTER SESSION round trips with pooled SQLSpec Oracle configurations that share one statement cache and observability runtime, apply the session environment once per physical connection, keep transport MODULE/ACTION intact, and fix the proxy password and partition quoting defects."
tags: [refactor, oracle, sqlspec, persistence, observability]
parent_prd: prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024
depends_on: [prd_05_foundation_typing_settings_and_adapter_reduction_20261024]
research:
  - .agents/bundles/specs/prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 6.1: OracleDatabaseRegistry and Session Tracing

## Specification

### 1. Overview and Goals

Every Oracle interaction in GOE currently borrows an `OracleFrontendApi` connection, re-validates it with an `ALTER SESSION SET TRACEFILE_IDENTIFIER` round trip before every cursor, and wraps it in a brand-new `OracleSyncDriver` per named statement so the SQLSpec statement cache and observability runtime are rebuilt and discarded on every query. Transport code opens throwaway connections for single queries and for reading the server version. This chapter installs one process-wide `OracleDatabaseRegistry` that owns pooled `OracleSyncConfig` configurations for the admin/repository role and the application/transport role plus an `OracleAsyncConfig` for Listener reads, and moves the frontend, repository, and transport code onto it.

Goals:

1. One pooled SQLSpec configuration per Oracle role with a shared `StatementCacheHolder` and one observability runtime per pool.
2. `TRACEFILE_IDENTIFIER` applied once per physical connection by the pool `session_callback`; no per-cursor `ALTER SESSION`.
3. Admin sessions use SQLSpec zero round-trip session tracing (`enable_session_tracing`); transport sessions keep their explicit `MODULE`/`ACTION` so `LOG_SQL_STATS_QUERY_TEXT` still finds transport SQL in `gv$sql`, and receive only `client_identifier` and `econtext_id`.
4. Lost-session recovery that captures the failure inside `except`, leaves the block, and retries once.
5. `OracleGateway` deleted; named statements use `SQLFileLoader` `/* slot: */` markers instead of the hand-rolled `{slot}` interpolation.
6. Proxy connections authenticate with the admin password (fixes `ORA-01017`) and `get_distinct_column_values` encloses partition names.

### 2. Code Analysis Summary

- `src/goe/persistence/oracle_gateway.py:65-158` builds a dummy `OracleSyncConfig` (`:77-81`) and constructs `OracleSyncDriver(connection=..., driver_features=dict(...))` per query in `_driver()` (`:147-158`) without `provide_session()`. `sqlspec/driver/_common.py:591-600` reuses `driver_features["_statement_cache_holder"]` only when the holder's `statement_config` is the driver's `statement_config`; the copied dict plus a fresh holder means every query compiles cold. `_SLOT_RE` `{slot}` interpolation (`:32`, `:84-97`) duplicates `SQLFileLoader` slots (`sqlspec/loader.py:563-626`, `/* slot: name */` markers at `:62`).
- `src/goe/observability/db.py:107-119` (`attach_db_observability`) builds a new `SqlspecObservabilityRuntime` per query and replaces `statement_config`, which breaks the holder identity check above. `apply_oracle_session_trace_info` (`:47-52`) writes `V$SESSION.CLIENT_INFO` on `OracleFrontendApi` connections.
- `src/goe/offload/oracle/oracle_frontend_api.py`: `get_validated_oracle_connection` (`:270-278`) calls `_open_cursor` (`:921-951`), which executes `ALTER SESSION SET TRACEFILE_IDENTIFIER` (`:934`) before every cursor and reconnects on `RECONNECT_ERROR_MARKERS` (`:56-65`) by substring. `_connect` (`:489-522`) opens a dedicated connection per API object and pings it. `_conn_user_and_pass_for_override` (`:454-473`) returns `ora_app_pass` for the `adm_user[proxy]` login at `:471-472` (ORA-01017 whenever the admin and application passwords differ; `src/goe/util/ora_query.py:61-65` uses the admin password correctly). `get_distinct_column_values` (`:230-246`) interpolates `PARTITION ({partition_name})` unquoted at `:236`.
- `src/goe/persistence/oracle/oracle_orchestration_repo_client.py:539-551` builds an `OracleGateway` over `self._frontend_api.get_validated_oracle_connection`; `start_command`, `start_command_step`, and `start_offload_chunk` allocate OUT binds with `self._gateway.new_out_var(int)` (`:111`, `:150`, `:209`) that must live on the same connection as the following `execute_function` call; `_get_ora_type_object` (`:438-440`) creates UDT objects on the frontend connection that `execute_function` binds.
- `src/goe/persistence/sql/oracle_repo.sql` uses `{repo_user}` (for example `:219`, `:423`, `:438-441`) and `{unsupported_col_name}`/`{unsupported_col_name_count}` (`:322-323`) slots.
- `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py`: `get_id_range` (`:126-170`) and `query_import_extraction` (`:706-761`) open standalone connections through `get_rdbms_connection_for_oracle` (`src/goe/offload/offload_transport_functions.py:127-141`, which also runs a per-connection `ALTER SESSION`); `get_offload_transport_sql_stats_function` (`:227-243`) keeps an app connection whose `module` is the transport module; `_get_fixed_goe_parameters` (`:842-851`) opens a whole admin connection only to read `connection.version`; `log_ash_usage` (`:667-701`) is documented as unused and has no caller. `LOG_SQL_STATS_QUERY_TEXT` (`:63-74`) filters `gv$sql` by `module` and `action`.
- `sqlspec==0.68.0` facts: `OracleSyncConfig.__init__` pops `session_callback` into `_pool_session_callback` (`sqlspec/adapters/oracledb/config.py:400-402`); `_create_pool` (`:521-537`) initializes Thick mode when `thick_mode=True` and wraps the callback in `_init_connection` (`:539-572`), which runs once per new physical connection; `OracleAsyncConfig._create_pool` rejects Thick mode (`:824-836`) and awaits awaitable callbacks (`:867-870`); `_session_tracing_enabled` (`sqlspec/adapters/oracledb/driver.py:156-160`) is true for `enable_session_tracing` or `enable_sqlcommenter` and then `_apply_session_tracing` (`:162-181`) overwrites `module`/`action` (default module `"sqlspec"`); `apply_oracle_session_trace_attributes` (`sqlspec/adapters/oracledb/core.py:1190-1244`) falls back to `SQLCommenterContext` for a `None` module or action, so transport sessions pass their explicit module and action; `OracleSyncSessionContext.__enter__` (`sqlspec/adapters/oracledb/_typing.py:195-201`) builds drivers with the config's own `statement_config` and `driver_features`; sqlspec maps Oracle errors to `SQLSpecError` subclasses whose message embeds the original text and whose `__cause__` is the original (`core.py:1652-1707`, `:2760-2777`).
- `python-oracledb==26.0.1`: `ConnectionPool.drop` (`oracledb/pool.py:461`), `POOL_GETMODE_FORCEGET == 2`, write-only `Connection.econtext_id` (`oracledb/connection.py:723-734`).

### 3. Requirements

Functional:

- **R1** `src/goe/persistence/retry.py` detects lost Oracle sessions (`ORA-00028`, `ORA-02396`, `ORA-03113`, `ORA-03114`, `ORA-03135`, `DPY-1001`, `DPY-4011`, padded or unpadded, on the exception or its cause chain) without matching longer codes such as `ORA-28000`, and retries an operation exactly once after leaving the `except` block.
- **R2** `src/goe/persistence/registry.py` provides `OracleDatabaseRegistry` with pooled `OracleSyncConfig` configurations for the `adm` role (`rdbms_dsn`, admin credentials) and the `app` role (`offload_transport_dsn`, application credentials), an `OracleAsyncConfig` for Listener admin reads, and one process-wide instance per connection settings.
- **R3** Pools apply `ALTER SESSION SET TRACEFILE_IDENTIFIER = "GOE"` once per physical connection through `session_callback`, use `ping_interval=60`, `min=0`, `max=8`, and `POOL_GETMODE_FORCEGET`, and keep Wallet (external authentication, non-homogeneous) and Thick mode working.
- **R4** The `adm` configuration enables `enable_session_tracing`; the `app` configuration enables neither `enable_session_tracing` nor `enable_sqlcommenter`; admin driver use runs inside `SQLCommenterContext` with module `GOE`.
- **R5** Transport sessions keep the caller's explicit `MODULE`/`ACTION`; when observability is enabled they also receive `client_identifier` (execution id) and `econtext_id` (W3C `traceparent`); sessions that run `ALTER SESSION` setup commands are dropped from the pool instead of returned.
- **R6** Proxy connections log in as `adm_user[proxy_schema]` with the admin password, or `[proxy_schema]` with Oracle Wallet.
- **R7** `OracleGateway` and its tests are deleted; frontend and repository named statements execute through drivers that share the pool `StatementCacheHolder`; `oracle_repo.sql` uses `/* slot: */` markers.
- **R8** `OracleFrontendApi` leases one pooled connection per API object (released on `close`), pings a lease idle for 60 seconds or more before use, renews a lost lease, and no longer issues per-cursor `ALTER SESSION`.
- **R9** `get_distinct_column_values` encloses the partition name in double quotes.
- **R10** Transport code stops opening throwaway connections: `_get_fixed_goe_parameters` reads the registry's cached server version; `get_id_range`, SQL statistics, and Query Import use registry transport sessions; `get_rdbms_connection_for_oracle` and `log_ash_usage` are deleted.
- **R11** `pyproject.toml` raises the `sqlspec` floor to `>=0.68.0`.

Non-functional:

- **R12** Transport `gv$sql` statistics keep working (`MODULE`/`ACTION` unchanged on transport sessions); `OFFLOAD`/`OFFLOAD_REPO` package contracts unchanged; extraction SQL unchanged.
- **R13** With observability disabled, transport and lease sessions receive no trace attributes (zero-cost default).

Risks and mitigations:

- Pool exhaustion when many API objects hold leases in one thread: `POOL_GETMODE_FORCEGET` creates a connection above `max` instead of blocking.
- Dirty session state returned to the pool by Query Import (`ALTER SESSION`, output type handler): `isolate_session=True` drops the connection.
- Session environment parity: the frontend sets no `TIME_ZONE`/`NLS_*` at HEAD (`oracle_frontend_api.py:921-951` sets only `TRACEFILE_IDENTIFIER`) and transport NLS formats depend on the per-table timestamp scale (`oracle_offload_transport_rdbms_api.py:853-866`), so the pool callback applies `TRACEFILE_IDENTIFIER` only; transport commands keep setting their NLS values per extraction.
- Long-held leases sniped by `IDLE_TIME`: the 60-second idle ping renews the lease before the next statement, matching the old pre-statement probe without re-executing writes.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| --- | --- | --- |
| R1 | 1.1 | `tests/unit/persistence/test_retry.py` |
| R2, R3, R4, R6, R11 | 1.2 | `tests/unit/persistence/test_registry.py`; `uv lock --check` |
| R5, R13 | 1.2, 1.4 | `tests/unit/persistence/test_registry.py`; `tests/unit/offload/test_offload_transport_rdbms_api.py` |
| R7, R8, R9 | 1.3 | `tests/unit/persistence/test_statements.py`; `tests/unit/offload/test_oracle_frontend_metadata.py`; `tests/unit/persistence/test_oracle_orchestration_repo_client.py` |
| R6 (frontend path) | 1.3 | `tests/unit/offload/test_oracle_frontend_metadata.py::test_proxy_override_connects_with_admin_password` |
| R10, R12 | 1.4 | `tests/unit/offload/test_offload_transport_rdbms_api.py`; `tests/unit/observability/test_oracle_telemetry.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/persistence tests/unit/offload/test_oracle_frontend_metadata.py tests/unit/offload/test_frontend_api.py tests/unit/offload/test_offload_transport_rdbms_api.py tests/unit/observability -q
uv run pytest tests/unit -q
uv run ruff format --check src/goe tests/unit
uv run ruff check src/goe tests/unit
uv run mypy src/goe
uv run python tools/verify_architecture.py
make test-integration-oracle
```

## Implementation Plan

### Phase 1: Registry Foundation

- [x] 1.1 Add the Oracle lost-session retry policy ([tasks/1.1.md](tasks/1.1.md))
- [x] 1.2 Add OracleDatabaseRegistry with pooled admin, application, and Listener configurations ([tasks/1.2.md](tasks/1.2.md))

### Phase 2: Caller Migration

- [x] 1.3 Replace OracleGateway with registry leases and named statements ([tasks/1.3.md](tasks/1.3.md))
- [x] 1.4 Move Oracle transport connections onto registry sessions ([tasks/1.4.md](tasks/1.4.md))

## Continuity Snapshot

- **Flow / lifecycle**: `oracle_database_registry_and_session_tracing_20261024`, `completed`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: `1.4` (2026-10-25T15:42:00Z).
- **Decisions**: one process-wide `OracleDatabaseRegistry` per connection settings; `OracleFrontendApi` leases a pooled connection per API object so UDT objects and OUT binds stay on one session; the pool callback applies `TRACEFILE_IDENTIFIER` only; `CLIENT_INFO` tagging stays only in transport session setup commands executed by external engines (`build_oracle_client_info_command`); named statements live in `src/goe/persistence/statements.py`.
- **Discoveries**: `ora_query.py` was moved by Chapter 5.4 to `src/goe/offload/oracle/ora_query.py` and updated with `_rows_as_dicts`; `tools/verify_architecture.py` was updated so `src/goe/persistence/registry.py` is the canonical `oracledb` boundary owner, and `tools/architecture_baseline.toml` had zero remaining `oracledb-boundary` entries.
- **Blockers**: none.
- **Next exact step**: Chapter 6.2 (`offload_metadata_and_repository_service_20261024`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 1`.
- **Relevant knowledge**: `.agents/bundles/knowledge/frontends/oracle.md`, `.agents/bundles/knowledge/standards/database-and-sql.md`, `.agents/bundles/knowledge/operations/observability.md`, `.agents/bundles/knowledge/standards/testing.md`.

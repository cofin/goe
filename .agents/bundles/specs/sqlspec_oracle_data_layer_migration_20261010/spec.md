---
type: Spec
flow_id: sqlspec_oracle_data_layer_migration_20261010
title: "Chapter 3.1: SQLSpec Oracle Data Layer Migration"
state: planned
plan_revision: 3
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-11T00:10:00Z
description: "Introduce a SQLSpec-backed OracleGateway (SQLFileLoader + OracleSyncDriver over GOE's existing oracledb connection), move OracleFrontendApi dictionary queries and OracleOrchestrationRepoClient repository queries into named .sql files with msgspec.Struct row hydration, and keep every Oracle auth, session-tagging, reconnect, dry-run, and PL/SQL behavior unchanged."
tags: [refactor, sqlspec, oracle, persistence, frontend]
parent: prd_03_sqlspec_bigquery_and_duckdb_engine_20261010
research:
  - research/sqlspec_oracle_gateway.md
---

# Chapter 3.1: SQLSpec Oracle Data Layer Migration

## Specification

### Context

- Baseline commit for every line reference in this flow: `46890a8`. Line numbers drift after earlier chapters; each worksheet therefore names the enclosing symbol next to every line range and the executor locates code by symbol first.
- Earlier chapters that change files this flow touches (all execute before PRD 3):
  - `legacy_shim_removal_and_repo_hygiene_20261010:1.5` changes `pyproject.toml` to `sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0` (drops `mypyc` at `:35`, `:98`, `:108`) and `lark-parser` -> `lark>=1.1.9`. This flow does not edit `pyproject.toml`; Task 1.1 only asserts the precondition.
  - `typed_msgspec_option_model_20261010` may replace `tests/unit/test_functions.build_mock_options`; worksheets reuse whatever config fixture `TestOracleFrontendApi.setUp` in `tests/unit/offload/test_frontend_api.py` uses at execution time.
  - `core_god_module_decomposition_20261010` moves `OracleQuery` consumers from `src/goe/offload/offload_status_report.py` into `src/goe/report/`; `OracleQuery`'s public contract stays unchanged here, so no consumer edits are needed.
  - `strict_mypy_type_safety_ratchet_20261010:1.1` annotates `src/goe/util/ora_query.py`, `src/goe/persistence/schemas.py`, and `src/goe/persistence/oracle/oracle_orchestration_repo_client.py`; `:1.4` annotates `src/goe/offload/oracle/oracle_frontend_api.py` and `:1.6` enables strict mypy flags (`disallow_incomplete_defs`, `warn_unused_ignores`). All new code in this flow is fully annotated.
- Later chapter coupling: `database_transport_and_cloud_storage_spans_20261010:1.1` (PRD 4) adds SQLSpec observability to `OracleGateway` at `OracleSyncConfig(...)` and `OracleSyncDriver(connection=...)`; keeping a single `OracleSyncConfig(...)` site in `__init__` and a single `driver = OracleSyncDriver(connection=...)` site in `_driver()` gives it clean seams.
- Verified library facts and source facts with evidence: [`research/sqlspec_oracle_gateway.md`](research/sqlspec_oracle_gateway.md).

### 1. Objective & Scope

Route GOE's static Oracle SQL through **SQLSpec** (`sqlspec.loader.SQLFileLoader`, `sqlspec.adapters.oracledb.OracleSyncConfig`, and `sqlspec.adapters.oracledb.OracleSyncDriver`) behind a single `OracleGateway`, while keeping connection ownership, authentication (Wallet, proxy `user[schema]`), session tagging (`MODULE`, `ACTION`, `TRACEFILE_IDENTIFIER`), sniped-session reconnect, dry-run semantics, and PL/SQL / Oracle object-type calls exactly where they work today (`OracleFrontendApi`).

| ID | Requirement | Task | Verification |
| --- | --- | --- | --- |
| REQ-1 | `OracleGateway` loads named SQL with `SQLFileLoader`, normalizes driver features via `OracleSyncConfig(connection_config=None, ...)`, executes statements through `OracleSyncDriver` over a caller-supplied `oracledb` connection, accepts only `Mapping[str, Any]` named binds, validates identifier template slots, returns lower-case `dict` rows, tuples, or `msgspec.Struct` rows. | 1.1 | `tests/unit/persistence/test_oracle_gateway.py` |
| REQ-2 | The 16 static data-dictionary queries in `OracleFrontendApi` live in `src/goe/offload/oracle/sql/frontend_metadata.sql` and execute through `OracleGateway`; inline literals are deleted; public method results are unchanged. | 1.2 | `tests/unit/offload/test_oracle_frontend_metadata.py` |
| REQ-3 | `OracleFrontendApi._open_cursor` reconnects for the same `ORA-02396/03113/03114/03135` substrings outside the `except` block; a public `get_validated_oracle_connection()` gives `OracleGateway` the same reconnect + `TRACEFILE_IDENTIFIER` behavior. | 1.2 | `tests/unit/offload/test_oracle_frontend_metadata.py` |
| REQ-4 | `OracleQuery.fetch(as_dict=True)` delegates row projection to `goe.persistence.oracle_gateway.rows_as_dicts` (upper-case keys preserved); execution, `cursor_fn`, bulk, commit/rollback, `fromcursor`/`fromconnection`, and `get_oracle_connection` are unchanged. | 1.2 | `tests/unit/util/test_ora_query.py` |
| REQ-5 | The 7 repository statements in `OracleOrchestrationRepoClient` live in `src/goe/persistence/sql/oracle_repo.sql`, execute through `OracleGateway` with `msgspec.Struct` hydration, and return the same `dict` shapes; user names are binds (`:adm_user`, `:app_user`, `:repo_user`), schema names are validated identifier slots; `conn_obj.cursor().var(int)` boilerplate is replaced by `OracleGateway.new_out_var(int)`. | 1.3 | `tests/unit/persistence/test_oracle_orchestration_repo_client.py` |
| REQ-6 | Dead code is deleted: inline SQL literals moved to `.sql` files, the duplicated `OracleQuery` row-zip loop, and the stale git-ignored `src/goe/persistence/__pycache__/sqlspec_client*.pyc`. | 1.1, 1.2, 1.3 | Task acceptance greps |

### 2. Technical Architecture & Invariants

1. **One execution seam.** `OracleGateway` is the only module in this flow that imports `sqlspec.adapters.oracledb` / `sqlspec.loader`. It never opens or closes connections; it constructs `OracleSyncConfig(connection_config=None, driver_features=...)` once in `__init__` for normalized `statement_config` and `driver_features`, then calls a `connection_provider` and wraps the returned connection in `OracleSyncDriver(connection=..., statement_config=..., driver_features=...)` per call.
2. **No pool, no new auth path.** `OracleSyncConfig.create_pool()` / `provide_session()` is never called because a SQLSpec pool would bypass `OracleFrontendApi._connect` (Wallet, proxy, `MODULE`/`ACTION`, `outputtypehandler`) and `_open_cursor` reconnect handling. Decision recorded in `research/sqlspec_oracle_gateway.md` §2.
3. **PL/SQL stays on `FrontendApi.execute_function`.** It already owns `callfunc`/`callproc`, `DB_TYPE_OBJECT` + `gettype`, `not_when_dry_running`, logging, and commit. Moving it would regress dry-run. Only the OUT-variable allocation moves to `OracleGateway.new_out_var`.
4. **`OracleQuery` execution stays native.** Its public contract is `execute(sql, binds, cursor_fn, bulk, as_dict, ignore_errors)` where `cursor_fn` operates on the raw cursor and `bulk` uses `executemany` with `bindarraysize`; `OracleSyncDriver` exposes neither. Only row projection is shared.
5. **Named binds only.** Every gateway call passes a `dict`; positional sequences raise `TypeError`. Identifier slots (`{repo_user}`, `{unsupported_col_name}`) are validated by `validate_oracle_identifier` and substituted with `str.replace`, never `str.format`.
6. **Row-shape parity.** Repository methods keep returning `list[dict[str, Any]]` / `dict[str, Any] | None` with the same lower-case keys and raw values (`bytes` UUIDs, `datetime`), because listener controllers mutate those dicts. Struct hydration validates rows, then `msgspec.structs.asdict` restores the dict shape.
7. **Public-before-private ordering.** Every module and class created or modified in this flow (`oracle_gateway.py`, `oracle_frontend_api.py`, `ora_query.py`, `oracle_orchestration_repo_client.py`, `schemas.py`, and their unit test modules) keeps all public/dunder functions and methods grouped above private (`_...`) helpers, verified via an AST ordering check.

### 3. Task Breakdown & File Ownership

| Task | Title | Strategy | Priority | Depends On | Files Owned | Tests Owned |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `1.1` | Create `OracleGateway` (SQLFileLoader + OracleSyncDriver) | `behavior_tdd` | P1 | — | `src/goe/persistence/oracle_gateway.py` | `tests/unit/persistence/test_oracle_gateway.py` |
| `1.2` | Move `OracleFrontendApi` dictionary SQL to `frontend_metadata.sql`, add validated connection, share `OracleQuery` row projection | `characterization` | P1 | `1.1` | `src/goe/offload/oracle/oracle_frontend_api.py`, `src/goe/offload/oracle/sql/frontend_metadata.sql`, `src/goe/util/ora_query.py` | `tests/unit/offload/test_oracle_frontend_metadata.py`, `tests/unit/util/test_ora_query.py` |
| `1.3` | Move repository SQL to `oracle_repo.sql` with `msgspec.Struct` hydration | `characterization` | P2 | `1.1`, `1.2` | `src/goe/persistence/sql/oracle_repo.sql`, `src/goe/persistence/schemas.py`, `src/goe/persistence/oracle/oracle_orchestration_repo_client.py`, `src/goe/persistence/orchestration_repo_client.py` (annotation only) | `tests/unit/persistence/test_oracle_orchestration_repo_client.py` |

## Implementation Plan

- [ ] 1.1 Create `OracleGateway`, `validate_oracle_identifier`, `load_sql_file`, and `rows_as_dicts` in `src/goe/persistence/oracle_gateway.py` ([tasks/1.1.md](tasks/1.1.md)) [P1, behavior_tdd]
- [ ] 1.2 Move 16 `OracleFrontendApi` dictionary queries to `src/goe/offload/oracle/sql/frontend_metadata.sql`, add `get_validated_oracle_connection`, clean `_open_cursor` reconnect, and delegate `OracleQuery` row projection ([tasks/1.2.md](tasks/1.2.md)) (depends on: 1.1) [P1, characterization]
- [ ] 1.3 Move 7 repository statements to `src/goe/persistence/sql/oracle_repo.sql`, add repository row structs to `schemas.py`, and route `OracleOrchestrationRepoClient` through `OracleGateway` ([tasks/1.3.md](tasks/1.3.md)) (depends on: 1.1, 1.2) [P2, characterization]

## Continuity Snapshot

- **State**: planned; current task: none; claimant: none; last verified checkpoint: none.
- **Plan identity**: `plan_revision: 3`, `plan_commit: null`; state identity `state_revision: 0`.
- **Decisions**: wrap GOE's existing connection with `OracleSyncDriver` (no `OracleSyncConfig` pool); PL/SQL stays on `execute_function`; `OracleQuery` execution stays native (row projection shared); repository rows stay `dict`-shaped after `msgspec.Struct` validation.
- **Blockers**: none. Precondition: PRD 1 and PRD 2 chapters are closed.
- **Next exact step**: claim Task `1.1` and run its Step 1 precondition check.
- **Knowledge paths**: `research/sqlspec_oracle_gateway.md`, `.agents/bundles/knowledge/patterns/serialization-and-utils.md`, `.agents/bundles/knowledge/frontends/`, `.agents/bundles/product/tech-stack.md`.

---
type: Research
title: SQLSpec Oracle Gateway — Verified Facts for Chapter 3.1
description: Primary-source verification of sqlspec, python-oracledb, and GOE Oracle data-layer facts that Chapter 3.1 worksheets depend on.
tags: [research, sqlspec, oracle, persistence]
created_at: 2026-10-10T18:50:00Z
---

# SQLSpec Oracle Gateway — Verified Facts for Chapter 3.1

Baseline: repository commit `46890a8`. Library facts were verified against the locked virtualenv (`uv.lock`) and PyPI.

## 1. Library versions and extras

| Fact | Evidence |
| --- | --- |
| `sqlspec` 0.62.1 is locked; PyPI latest is 0.66.0, so `>=0.61.0` resolves. | `uv.lock:3420-3421`; <https://pypi.org/pypi/sqlspec/json> (`info.version = 0.66.0`) |
| Extras `performance`, `oracledb`, `adbc`, `duckdb`, `mypyc` exist. `performance` = `librt>=0.10.0` + `msgspec`; `mypyc` = `sqlglot[c]`. | `.venv/lib/python3.14/site-packages/sqlspec-0.62.1.dist-info/METADATA:27-93` |
| `sqlspec` requires `sqlglot>=30.13.0`; `sqlglot` 30.17.0 is locked. | `METADATA:24`; `uv.lock:3383-3384` |
| `oracledb` 4.0.2 and `msgspec` 0.21.1 are locked. | `uv.lock:2452-2453`, `uv.lock:2133-2134` |
| The `mypyc` extra is removed from all three `pyproject.toml` occurrences (`:35`, `:98`, `:108`) by `legacy_shim_removal_and_repo_hygiene_20261010:1.3`, not by this chapter. | `.agents/bundles/specs/legacy_shim_removal_and_repo_hygiene_20261010/tasks/1.3.md` Step 2 |

## 2. SQLSpec APIs used by `OracleGateway`

| API | Verified signature / behavior | Evidence |
| --- | --- | --- |
| `from sqlspec.loader import SQLFileLoader` | `SQLFileLoader(*, encoding="utf-8", storage_registry=None)`; `load_sql(*paths)`, `list_queries() -> list[str]`, `has_query(name) -> bool`, `get_query_text(name) -> str`, `get_sql(name) -> SQL`. Statements are declared with `-- name: <query_name>`; hyphens normalize to underscores; `get_query_text` returns the statement body including a trailing `;`. | `sqlspec/loader.py:169-189`, `:556`, `:827-905`; local probe |
| `from sqlspec.adapters.oracledb import OracleSyncDriver` | `OracleSyncDriver(connection, statement_config=None, driver_features=None)`; wraps an existing `oracledb.Connection` without creating a pool. | `sqlspec/adapters/oracledb/driver.py:332-343` |
| `OracleSyncDriver.select(statement, *parameters, schema_type=None)` | Returns `list[dict[str, Any]]`, or `list[SchemaT]` when `schema_type` is given. Named `dict` parameters are passed to `cursor.execute(sql, params)` unchanged. | `sqlspec/driver/_sync.py:661-693`; local probe with a `MagicMock` connection |
| `from sqlspec.core import SQL` | `SQL(text)` wraps raw SQL; `.raw_sql` returns the text. | `sqlspec/core/statement.py:565-579`; local probe |
| Lower-case column keys | Driver feature key is `enable_lowercase_column_names` (not `enable_lowercase_column_keys`); it lowercases only implicit upper-case names. `OracleSyncConfig` defaults it to `True` via `apply_driver_features`, a bare `OracleSyncDriver` does not, so the gateway passes it explicitly. | `sqlspec/adapters/oracledb/core.py:218-228`, `:545-558`; `config.py:147-220` |
| UUID handlers | `enable_uuid_binary` handlers are registered only on pool-created connections in `OracleSyncConfig`; a wrapped existing connection keeps returning `RAW(16)` as `bytes`. | `sqlspec/adapters/oracledb/config.py:431`, `:627` |
| `OracleSyncConfig` | `OracleSyncConfig(*, connection_config=None, connection_instance=None, ..., driver_features=None)` normalizes `statement_config` and `driver_features` in `__init__` without opening a pool (`connection_instance` stays `None` unless `create_pool()` / `provide_session()` is called). GOE connections need Wallet/proxy/`MODULE`/`ACTION`/`outputtypehandler`/reconnect handling owned by `OracleFrontendApi._connect` / `_open_cursor`, so `OracleGateway` uses `OracleSyncConfig(connection_config=None, driver_features=...)` for configuration and wraps the existing connection with `OracleSyncDriver` instead of opening a pool. | `sqlspec/adapters/oracledb/config.py:295-343`; `oracle_frontend_api.py:163-198`, `:610-649` |

## 3. GOE source facts (baseline `46890a8`)

- `oracle_orchestration_repo_client.py` holds inline SQL only in `get_offloadable_schemas` (`L430-509`), `get_schema_tables` (`L511-876`), `get_command_step_codes` (`L942-945`), `get_command_executions` (`L947-973`), `get_command_execution` (`L975-1001`), and `get_command_execution_steps` (`L1003-1034`). `get_table_columns` (`L878-905`), `get_table_partitions` (`L907-923`), and `get_table_subpartitions` (`L925-940`) contain no SQL; they delegate to `OracleFrontendApi.get_columns` / `OffloadSourceTable`.
- All PL/SQL calls already go through `self._frontend_api.execute_function(...)` (`L104-109`, `L118-124`, `L230-235`, `L271-283`, `L295-300`, `L311-321`, `L334-339`, `L377-391`, `L412-424`), which owns dry-run (`not_when_dry_running`), logging, and commit. The only raw cursor boilerplate is `conn_obj = self._frontend_api.get_oracle_connection_object()` + `conn_obj.cursor().var(int)` at `L269-270`, `L309-310`, `L369-370`.
- Listener consumers read repository rows as mutable `dict`s with lower-case keys and raw `bytes` execution ids: `listener/services/periodic_tasks.py:103-120`, `listener/controllers/orchestration.py:44-82` (`item["execution_id"] = ...`, `step.get("execution_id")`, `execution.get("command_log_path")`).
- `OracleQuery.fetch(as_dict=True)` (`ora_query.py:311-317`) keeps Oracle's upper-case column names; consumers depend on that (`offload_status_report.py:86-121` keys such as `SOURCE_OWNER`; `schema_sync_analyzer.py:155-158` lower-cases them itself).
- `OracleQuery` has no thick-mode, LDAP, or `SYSDBA`/`SYSOPER` code; thick mode is initialized in `config/config_validation_functions.py:322-327`. `get_oracle_connection` (`ora_query.py:52-80`) handles Wallet, proxy (`user[proxy]`), and `TRACEFILE_IDENTIFIER`.
- Sniped-session reconnect lives in `OracleFrontendApi._open_cursor` (`oracle_frontend_api.py:610-649`) and matches substrings `ORA-02396`/`ORA-2396`/`ORA-03113`/`ORA-3113`/`ORA-03114`/`ORA-3114`/`ORA-03135`/`ORA-3135` (including `DPI-1080: connection was closed by ORA-2396`). No issue number (`#259`) appears in the source.
- `OracleFrontendApi._connection_output_type_handler` (`L157-161`) maps `DB_TYPE_CLOB -> DB_TYPE_LONG_STRING` and `DB_TYPE_BLOB -> DB_TYPE_LONG_RAW`; `ora_query.output_type_handler` (`L40-49`) does the same.
- `src/goe/persistence/sqlspec_client.py` does not exist in git; only the git-ignored bytecode `src/goe/persistence/__pycache__/sqlspec_client.cpython-314.pyc` remains (`.gitignore:2`).
- Hatchling builds the wheel from `packages = ["src/goe"]` (`pyproject.toml:159-160`), so non-ignored `.sql` files under `src/goe` ship in the wheel.

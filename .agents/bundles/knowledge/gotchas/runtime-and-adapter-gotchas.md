---
type: gotcha
title: Runtime, Driver & Adapter Gotchas
description: Verified footguns across msgspec typing, SQLGlot AST rendering, Oracle pooling, DuckDB 2.0 secrets, Litestar DI, and MCP streams.
status: stable
tags:
  - gotchas
  - oracle
  - bigquery
  - duckdb
  - litestar
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: goe-typing
    resource: src/goe/typing.py::FrozenBaseStruct
    title: Frozen msgspec Struct Base Class
  - id: dialect-engine
    resource: src/goe/offload/sql_ast/dialect_engine.py::GOEOracleDialect
    title: Custom Oracle Dialect and BigQuery DDL Builder
  - id: ora-registry
    resource: src/goe/persistence/registry.py::OracleDatabaseRegistry
    title: Oracle Database Registry Proxy User Formatting
  - id: listener-app
    resource: src/goe/listener/app.py::create_app
    title: Litestar Dependency Injection Wiring
---

# Runtime, Driver & Adapter Gotchas

<!-- truth: start -->
- **`FrozenBaseStruct` + strict `mypy`**: Subclasses of `FrozenBaseStruct` (`src/goe/typing.py`) must explicitly repeat `frozen=True` in the class header (`class MySpec(FrozenBaseStruct, frozen=True):`) so mypy's `msgspec` plugin recognizes the subclass as frozen.[^goe-typing]
- **`sqlglot` BigQuery `CREATE TABLE ... OPTIONS(...)`**: Attaching `exp.Properties` directly via `exp.Create(..., properties=...)` causes `sqlglot`'s BigQuery generator to emit invalid double-wrapped `OPTIONS (OPTIONS (...))`; build BigQuery DDL via `DialectSqlEngine` (`src/goe/offload/sql_ast/dialect_engine.py`).[^dialect-engine]
- **Oracle Proxy Authentication (`user[schema]`)**: Passing `user="app_user[target_schema]"` when `OracleConnectionSettings.oracle_adm_Proxy_user` is already set causes `ORA-01017` double-bracketing; `OracleDatabaseRegistry` formats proxy credentials in a single place.[^ora-registry]
- **`sqlspec` SQLCommenter Formatting**: `sqlspec.core.sqlcommenter.generate_comment(attrs)` returns raw `key='value'` pairs without `/* ... */` delimiters; always wrap with `format_sqlcommenter()` in `src/goe/observability/db.py`.
- **Litestar DI Signature Inspection in Tests**: Patching `goe.listener.app.get_job_store` with `unittest.mock.MagicMock` breaks Litestar's `ParsedSignature.from_fn` because `MagicMock` exposes `*args, **kwargs`; patch `goe.listener.app._default_job_store` or pass `job_store=` into `create_app(job_store=...)` instead.[^listener-app]
- **MCP `run_stdio_async` Stream Contract**: `litestar_mcp` `run_stdio_async` requires `anyio.abc.ByteReceiveStream` (`receive(max_bytes=65536)`) and `ByteSendStream` (`send(bytes)`), not `MemoryObjectReceiveStream` (whose `receive()` accepts 0 positional arguments).
<!-- truth: end -->

## Detailed Gotcha Reference

### Typing, CLI & Configuration
- **`FrozenBaseStruct` Subclassing**: `msgspec` inherits `gc=False` and `kw_only=True` at runtime, but strict `mypy` requires `class Model(FrozenBaseStruct, frozen=True):` on every concrete subclass.[^goe-typing]
- **`rich-click` 1.9+ Global Config**: Assigning `click.rich_click.rich_config = ...` is a no-op because `RichContext` calls `RichHelpConfiguration.load_from_globals()`; always pass `command_groups=COMMAND_GROUPS` and `option_groups=OPTION_GROUPS` to `RichHelpConfiguration(...)` and call `.dump_to_globals()` in `src/goe/cli/config.py`.
- **`goe.cli` Eager `main` Import**: Keep `from goe.cli.main import cli, main` eager in `src/goe/cli/__init__.py`; lazy `__getattr__` lookup for `main` on `goe.cli` collides with the `goe.cli.main` submodule attribute in Python's import machinery.
- **`OffloadOperation` Allowed Argument Keys**: `OffloadOperation.from_dict` validates keys against `EXPECTED_OFFLOAD_ARGS` (which excludes `"dry_run"`, `"quiet"`, and `"verbose"`). For dry-run planning, pass `"execute": False` in options and `dry_run=True` only on gateway constructors.

### Oracle, SQLSpec & SQLGlot
- **Oracle->BigQuery Direct `sqlglot.transpile` Is Unsafe**: Direct `sqlglot.transpile(sql, read="oracle", write="bigquery")` maps `NUMBER(38,0)` to `NUMERIC` (overflowing 29-digit values that require `BIGNUMERIC`), `TIMESTAMP(9)` to `DATETIME`, and `FF9` to invalid `PARSE_TIMESTAMP` masks. Always route type mapping through `ColumnSpec` / `TYPE_REGISTRY` and SQL generation through `DialectSqlEngine`.[^dialect-engine]
- **Oracle `V$SESSION.CLIENT_INFO` 64-Byte Limit**: `DBMS_APPLICATION_INFO.SET_CLIENT_INFO` truncates beyond 64 bytes; W3C `traceparent` strings (`00-<32hex>-<16hex>-<2hex>`, 55 bytes) fit within `CLIENT_INFO` and are applied by `OracleDatabaseRegistry` on checkout.[^ora-registry]

### DuckDB 2.0, Cloud Storage & Listener
- **DuckDB Optional `httpfs` Loading**: When `cloud_secret is None` (local filesystem staging), `DuckDBEngine` skips `LOAD httpfs` unless an `httpfs`-backed URI (`gs://`, `s3://`, `abfss://`) is targeted, allowing offline unit tests to run without pre-installed network extensions.
- **GCS `gcsfs` Anonymous Fallback**: Passing `token=None` to `gcsfs` silently falls back to anonymous access; always pass credentials resolved via `resolve_gcp_credentials()` (`src/goe/config/gcp_credentials.py`).
- **Cooperative Cancellation & Active-Table Uniqueness**: `GOE_LISTENER_JOBS_ACTIVE_TBL_UQ` prevents enqueueing a new job for a table while a prior job is active; `DurableJobWorker` must unwind its thread via `_CooperativeCancelSink` and call `mark_cancelled()` before the table lock and unique index are released.

[^goe-typing]: `src/goe/typing.py::FrozenBaseStruct` — Base `msgspec.Struct` classes with `gc=False` and `kw_only=True`.
[^dialect-engine]: `src/goe/offload/sql_ast/dialect_engine.py::GOEOracleDialect` — Custom Oracle SQLGlot dialect and multi-backend SQL builder.
[^ora-registry]: `src/goe/persistence/registry.py::OracleDatabaseRegistry` — Pooled SQLSpec Oracle connection registry.
[^listener-app]: `src/goe/listener/app.py::create_app` — Litestar ASGI application factory and DI providers.

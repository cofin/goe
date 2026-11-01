---
type: decision
title: "ADR-001: Pooled SQLSpec Oracle Data Layer & SQLGlot AST Boundary"
description: Isolate Oracle driver pooling in SQLSpec OracleDatabaseRegistry and encapsulate all SQLGlot AST generation behind DialectSqlEngine and PredicateCompiler.
status: stable
tags:
  - decision
  - adr
  - sqlspec
  - sqlglot
  - oracle
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: ora-registry
    resource: src/goe/persistence/registry.py::OracleDatabaseRegistry
    title: Pooled SQLSpec Oracle Database Registry
  - id: dialect-engine
    resource: src/goe/offload/sql_ast/dialect_engine.py::DialectSqlEngine
    title: Multi-Dialect SQLGlot AST Engine
  - id: verify-arch
    resource: tools/verify_architecture.py::verify_architecture
    title: AST Boundary Verification Gate
---

# ADR-001: Pooled SQLSpec Oracle Data Layer & SQLGlot AST Boundary

<!-- truth: start -->
- **Status**: Accepted (`stable`).
- **Decision**: Route all Oracle catalog and repository access through pooled `OracleDatabaseRegistry` (`sqlspec.adapters.oracledb.OracleSyncConfig` + `SQLFileLoader`), and isolate all `sqlglot` AST parsing/rendering inside `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/`.[^ora-registry][^dialect-engine]
- **Enforcement**: `tools/verify_architecture.py` enforces `oracledb-boundary` and `sqlglot-boundary` with zero unbaselined exceptions.[^verify-arch]
<!-- truth: end -->

## Context

Legacy GOE opened unpooled `cx_Oracle`/`oracledb` connections per call, re-executed `ALTER SESSION` initialization statements on every borrow, fetched UDT metadata in 4 round-trips per column, and constructed cross-dialect DDL/DML through string concatenation and a fragile Lark-to-string predicate visitor.

## Alternatives Considered

| Option | Summary | Why Rejected / Selected |
| :--- | :--- | :--- |
| **Selected: Pooled SQLSpec `OracleDatabaseRegistry` + `DialectSqlEngine` AST Seam** | Pool Oracle sessions via `OracleSyncConfig`, load named SQL via `SQLFileLoader`, and encapsulate `sqlglot` AST builders behind `DialectSqlEngine` and `PredicateCompiler`. | **Selected**: Eliminates per-query connection/session overhead, preserves statement caching, and isolates `sqlglot` quirks behind a single verified boundary. |
| **Raw `oracledb` + String Templates** | Keep ad-hoc `oracledb.connect()` calls and format SQL strings directly in each backend adapter. | **Rejected**: Causes connection leaks in long-running Listener processes, loses statement cache hits, and risks SQL injection or identifier quoting bugs. |
| **`polyglot-sql` (`tobilg/polyglot` 0.13.3)** | Replace `sqlglot` with Rust/PyO3 `polyglot-sql` for faster parsing. | **Rejected**: Fails to parse BigQuery `CREATE TABLE ... OPTIONS(...)` and mis-orders `PARSE_DATE` arguments. |

## Consequences

- `OracleDatabaseRegistry` initializes session NLS/timezone settings once via pool callback, tags `V$SESSION.CLIENT_INFO` with W3C `traceparent`, and executes named SQL from `src/goe/offload/oracle/sql/oracle_catalog.sql` and `src/goe/persistence/sql/oracle_repo.sql`.[^ora-registry]
- `GOEOracleDialect` (`src/goe/offload/sql_ast/dialect_engine.py`) extends `sqlglot.dialects.oracle.Oracle` to round-trip `PARTITION (...)`, `SUBPARTITION (...)`, and `AS OF SCN <int>` clauses.[^dialect-engine]
- `tools/verify_architecture.py` fails CI if any module outside the designated boundary packages imports `oracledb` or `sqlglot`.[^verify-arch]

[^ora-registry]: `src/goe/persistence/registry.py::OracleDatabaseRegistry` — Pooled SQLSpec Oracle connection registry and session initializer.
[^dialect-engine]: `src/goe/offload/sql_ast/dialect_engine.py::DialectSqlEngine` — Multi-dialect SQLGlot AST engine and custom `GOEOracleDialect`.
[^verify-arch]: `tools/verify_architecture.py::verify_architecture` — AST boundary checker enforcing `oracledb-boundary` and `sqlglot-boundary`.

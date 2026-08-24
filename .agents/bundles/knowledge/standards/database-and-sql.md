---
type: Guide
title: Database & SQL Standards
description: SQL generation standards, dialect abstraction, transactional snapshot consistency, and DDL guidelines
tags:
  - guide
  - standards
  - database
  - sql
  - oracle
---

# Database & SQL Standards

## SQL Generation & Dialect Abstraction

- **Dialect Independence**: Never hardcode database-specific SQL functions directly in core orchestration logic. Use the `format_literal` and `backend_api` abstraction interfaces.
- **AST Predicates**: Filter expressions must be parsed via `src/goe/offload/predicate_offload.py` using Lark grammar to ensure safe expression evaluation and automatic synthetic partition clause injection.
- **Identifier Quoting**: Respect backend identifier case rules (`BACKEND_IDENTIFIER_CASE` setting: `UPPER`, `LOWER`, or `NO_MODIFY`).

## Transactional & Snapshot Consistency

- **Consistent Reads**: Extraction queries against Oracle must utilize Flashback queries (`AS OF SCN <scn>`) to guarantee snapshot isolation across parallel Spark/JDBC worker tasks.
- **Non-Invasive Execution**: Never lock source tables in exclusive mode during normal data offload operations.
- **Repository Atomicity**: Repository state updates (`COMMAND_EXECUTION`, `COMMAND_EXECUTION_STEP`, `backend_object`) must be committed atomically to prevent dangling in-progress state records.

## DDL Best Practices

- DDL operations must support idempotent execution (`IF NOT EXISTS`, `CREATE OR REPLACE`).
- Always strip physical storage attributes (`TABLESPACE`, `STORAGE`, `SEGMENT`) when reverse-engineering DDL via `DBMS_METADATA`.

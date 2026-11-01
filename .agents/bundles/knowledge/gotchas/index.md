---
title: Runtime & Adapter Gotchas
description: Non-obvious driver, SQL dialect, CLI, and concurrency traps verified in GOE production and CI.
---

# Runtime & Adapter Gotchas

This section captures non-obvious runtime, driver, SQL dialect, and concurrency footguns verified across GOE.

## Chapters

- [Runtime, Driver & Adapter Gotchas](runtime-and-adapter-gotchas.md) — Verified traps across `msgspec` + `mypy`, `sqlglot` BigQuery/Oracle AST rendering, `python-oracledb` proxy passwords, DuckDB 2.0 `httpfs`, Litestar DI mocking, and MCP stdio streams.

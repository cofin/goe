# GOE Project-Local Skills & Subagents Registry

This directory contains stack-specific implementation and review skills synthesized from the GOE codebase and [OKF v0.2 Knowledge Base](../bundles/knowledge/index.md).

## Domain Routing Matrix

| Domain | Rule Prefix | Implementation Skill | Review Skill | Paired Subagents | Primary Source Scope |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Core Orchestration, Typing, Settings & CLI** | `ORCH` | [`core-orchestration`](core-orchestration/SKILL.md) | [`review-core-orchestration`](review-core-orchestration/SKILL.md) | [`core-orchestration-specialist`](../agents/core-orchestration-specialist.md), [`core-orchestration-reviewer`](../agents/core-orchestration-reviewer.md) | `src/goe/{orchestration,config,cli,platform,util}/`, `src/goe/{typing,serializers}.py`, `tools/verify_architecture.py` |
| **SQLSpec Data Layer, SQLGlot AST Seam & Predicates** | `SQL` | [`sqlspec-and-sql-ast`](sqlspec-and-sql-ast/SKILL.md) | [`review-sqlspec-and-sql-ast`](review-sqlspec-and-sql-ast/SKILL.md) | [`sqlspec-and-sql-ast-specialist`](../agents/sqlspec-and-sql-ast-specialist.md), [`sqlspec-and-sql-ast-reviewer`](../agents/sqlspec-and-sql-ast-reviewer.md) | `src/goe/persistence/`, `src/goe/offload/{oracle,microsoft,sql_ast,predicates}/`, `src/goe/{validate,sync}/` |
| **Canonical Typing, Cloud Backends, DuckDB 2.0, Arrow & Storage** | `DPL` | [`offload-backends-and-dataplane`](offload-backends-and-dataplane/SKILL.md) | [`review-offload-backends-and-dataplane`](review-offload-backends-and-dataplane/SKILL.md) | [`offload-backends-and-dataplane-specialist`](../agents/offload-backends-and-dataplane-specialist.md), [`offload-backends-and-dataplane-reviewer`](../agents/offload-backends-and-dataplane-reviewer.md) | `src/goe/offload/{schema,bigquery,snowflake,hadoop,spark,staging,transport}/`, `src/goe/filesystem/` |
| **Litestar Listener, Vertebra Runtime, Durable Jobs, MCP & OpenTelemetry** | `LST` | [`listener-and-observability`](listener-and-observability/SKILL.md) | [`review-listener-and-observability`](review-listener-and-observability/SKILL.md) | [`listener-and-observability-specialist`](../agents/listener-and-observability-specialist.md), [`listener-and-observability-reviewer`](../agents/listener-and-observability-reviewer.md) | `src/goe/listener/`, `src/goe/cli/commands/listener.py`, `src/goe/observability/` |

# Gluent Offload Engine (GOE) — Agent Context & Routing

This repository follows the Flow specification-driven development workflow with an Open Knowledge Format (`OKF v0.2`) knowledge bundle under [`.agents/bundles/`](.agents/bundles/index.md).

## Canonical Context & Routing

- **Bundle Manifest**: [`.agents/bundles/index.md`](.agents/bundles/index.md)
- **Product Charter & Invariants**: [`.agents/bundles/product/product.md`](.agents/bundles/product/product.md) and [`.agents/bundles/product/product-guidelines.md`](.agents/bundles/product/product-guidelines.md)
- **Technology Stack**: [`.agents/bundles/product/tech-stack.md`](.agents/bundles/product/tech-stack.md)
- **Developer Workflow & Commands**: [`.agents/bundles/knowledge/workflow.md`](.agents/bundles/knowledge/workflow.md)
- **System Knowledge Base**: [`.agents/bundles/knowledge/index.md`](.agents/bundles/knowledge/index.md) (`domains/`, `decisions/`, `architecture/`, `frontends/`, `backends/`, `transport/`, `storage/`, `listener/`, `operations/`, `patterns/`, `standards/`, `testing/`, `gotchas/`)
- **Active & Archived Specifications**: [`.agents/bundles/specs/index.md`](.agents/bundles/specs/index.md)
- **Project-Local Skills & Subagents**: [`.agents/skills/index.md`](.agents/skills/index.md)

## Domain Skills & Subagents

| Domain | Prefix | Implementation Skill | Review Skill | Subagents |
| :--- | :--- | :--- | :--- | :--- |
| **Core Orchestration, Typing, Settings & CLI** | `ORCH` | [`core-orchestration`](.agents/skills/core-orchestration/SKILL.md) | [`review-core-orchestration`](.agents/skills/review-core-orchestration/SKILL.md) | `core-orchestration-{specialist,reviewer}` |
| **SQLSpec Data Layer, SQLGlot AST Seam & Predicates** | `SQL` | [`sqlspec-and-sql-ast`](.agents/skills/sqlspec-and-sql-ast/SKILL.md) | [`review-sqlspec-and-sql-ast`](.agents/skills/review-sqlspec-and-sql-ast/SKILL.md) | `sqlspec-and-sql-ast-{specialist,reviewer}` |
| **Canonical Typing, Cloud Backends, DuckDB 2.0, Arrow & Storage** | `DPL` | [`offload-backends-and-dataplane`](.agents/skills/offload-backends-and-dataplane/SKILL.md) | [`review-offload-backends-and-dataplane`](.agents/skills/review-offload-backends-and-dataplane/SKILL.md) | `offload-backends-and-dataplane-{specialist,reviewer}` |
| **Litestar Listener, Vertebra Runtime, Durable Jobs, MCP & OpenTelemetry** | `LST` | [`listener-and-observability`](.agents/skills/listener-and-observability/SKILL.md) | [`review-listener-and-observability`](.agents/skills/review-listener-and-observability/SKILL.md) | `listener-and-observability-{specialist,reviewer}` |

## Quick Verification Commands

```bash
# Unit test suite (disable workstation mTLS helper)
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
make test-unit

# Static linting, strict mypy, and AST/token architecture gate
make lint
uv run python tools/verify_architecture.py

# OKF v0.2 bundle validation
python3 ~/.gemini/config/plugins/flow/tools/validate.py --bundle .agents/bundles
```

<!-- project-customization: start -->
## Non-Negotiable Repository Guardrails

- Target Python >= 3.12 (`uv run`, PEP 585 `dict`/`list`, PEP 604 `X | None`, 2-line SPDX header `CPY001`, `ruff` `line-length = 120`, strict `mypy src/goe`).
- Use `FrozenBaseStruct(..., frozen=True)` / `BaseStruct` (`src/goe/typing.py`, `gc=False`) instead of `@dataclass`; repeat `frozen=True` on concrete `FrozenBaseStruct` subclasses for strict `mypy`.
- Enforce all 6 zero-baseline rules in `tools/verify_architecture.py`:
  1. `raw-json`: Route all JSON encoding/decoding through `src/goe/serializers.py`.
  2. `sqlglot-boundary`: Restrict `import sqlglot` to `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/`.
  3. `oracledb-boundary`: Restrict `import oracledb` to `src/goe/persistence/oracle/`, `src/goe/offload/oracle/`, and `src/goe/persistence/registry.py`.
  4. `nested-import`: Keep all imports at module top-level (or `if TYPE_CHECKING:` / `import_optional_dependency`).
  5. `member-ordering`: Order public functions/methods and dunders before private `_` helpers.
  6. `inline-comment`: Zero inline `#` comments inside function/method bodies; put rationale in Google-style docstrings.
- Direct Markdown + Git continuity: Task worksheets (`.agents/bundles/specs/<flow_id>/tasks/<id>-<slug>.md`) and `spec.md` checklists are the sole state authority. Never auto-push or create Git tags.
<!-- project-customization: end -->

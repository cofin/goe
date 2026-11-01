---
name: core-orchestration
description: "Use when implementing or refactoring GOE orchestration stages, ExecutionContext, ExecutionSink, FrozenBaseStruct models, goe.serializers, GOESettings, OptionSpec, or the rich-click CLI."
disable-model-invocation: false
---

# Core Orchestration, Typing, Settings & CLI

<!-- truth: start -->
- Every value object, config, and stage artifact inherits from `FrozenBaseStruct(..., frozen=True)` or `BaseStruct` (`src/goe/typing.py`, `gc=False`); subclasses of `FrozenBaseStruct` must repeat `frozen=True` in the class header for strict `mypy`.
- All JSON encoding/decoding routes through `src/goe/serializers.py` (`encode_json`, `encode_json_bytes`, `encode_json_into`, `format_json`, `decode_json`); direct `json.dumps`/`loads` or `msgspec.json.*` calls outside `serializers.py` fail `[raw-json]` in `tools/verify_architecture.py`.
- `OffloadPipeline` (`src/goe/orchestration/pipeline.py`) executes 4 stateless stages (`DiscoveryStage -> BoundaryStage -> PlanResolutionStage -> OffloadPlanExecutor`) with an explicit `ExecutionContext` (`src/goe/orchestration/context.py`) and table-level `filelock` mutex (`orchestration_lock_for_table`).
- `src/goe/cli/_lazy.py` (`resolve_lazy_attribute` + `bind_lazy_imports`) preserves fast CLI startup (~170ms) while honoring `@patch` mocks already in `module.__dict__`; keep `from goe.cli.main import cli, main` eager in `src/goe/cli/__init__.py`.
- All 6 AST/token rules in `tools/verify_architecture.py` (`raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, `inline-comment`) enforce zero unbaselined violations.
<!-- truth: end -->

## Workflow

1. **Ground in Domain Seams & Knowledge**:
   - Read [Patterns & Seams](references/patterns-and-seams.md) and the linked OKF v0.2 chapters before editing production modules:
- [Orchestration Core Engine](../../bundles/knowledge/architecture/orchestration.md)
- [Offload Execution Lifecycle](../../bundles/knowledge/architecture/offload-lifecycle.md)
- [Centralized Rich-Click CLI](../../bundles/knowledge/patterns/cli-architecture.md)
- [Serialization & Utility Patterns](../../bundles/knowledge/patterns/serialization-and-utils.md)
- [Python Coding Standards](../../bundles/knowledge/standards/python.md)
2. **Verify Public Seams First**:
   - Classify touched dependencies (`In-process`, `Local-substitutable`, `Remote-owned`, `External boundary`) and write or update unit tests in the canonical `tests/unit/` module before changing implementation behavior.
3. **Implement Within Architectural Boundaries**:
   - Preserve `FrozenBaseStruct(..., frozen=True)` / `BaseStruct` contracts, route JSON through `goe.serializers`, keep imports at module top-level (or `if TYPE_CHECKING:` / `import_optional_dependency`), and place public methods/functions above `_` private helpers.
4. **Run Focused & Aggregate Verification**:
   - Run the focused pytest suite, `uv run python tools/verify_architecture.py`, and `make lint`.

## Guardrails

- Never violate the 6 AST/token rules in `tools/verify_architecture.py` (`raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, `inline-comment`).
- Never introduce inline `#` comments inside function or method bodies; document rationale in Google-style docstrings.
- Never add backward-compatibility shims, unused re-exports, or standalone `test_*_remediation.py` files; place tests in the canonical `tests/unit/` file for the module under test.
- Check [Review Checklist](../review-core-orchestration/references/checklist.md) and [False-Positive Suppressions](../review-core-orchestration/references/false-positive-suppressions.md) before finalizing changes.

## Validation

```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit/orchestration tests/unit/config tests/unit/cli -q
uv run python tools/verify_architecture.py
make lint
```

## Output

Summarize modified files, public-seam tests executed, and exact exit statuses for `pytest`, `verify_architecture.py`, and `make lint`.

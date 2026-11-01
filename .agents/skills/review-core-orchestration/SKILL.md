---
name: review-core-orchestration
description: "Use when reviewing GOE changes touching src/goe/orchestration/, src/goe/config/, src/goe/cli/, src/goe/platform/, src/goe/util/, src/goe/typing.py, src/goe/serializers.py, or tools/verify_architecture.py."
disable-model-invocation: false
---

# Review: Core Orchestration, Typing, Settings & CLI (`ORCH`)

<!-- truth: start -->
- Every value object, config, and stage artifact inherits from `FrozenBaseStruct(..., frozen=True)` or `BaseStruct` (`src/goe/typing.py`, `gc=False`); subclasses of `FrozenBaseStruct` must repeat `frozen=True` in the class header for strict `mypy`.
- All JSON encoding/decoding routes through `src/goe/serializers.py` (`encode_json`, `encode_json_bytes`, `encode_json_into`, `format_json`, `decode_json`); direct `json.dumps`/`loads` or `msgspec.json.*` calls outside `serializers.py` fail `[raw-json]` in `tools/verify_architecture.py`.
- `OffloadPipeline` (`src/goe/orchestration/pipeline.py`) executes 4 stateless stages (`DiscoveryStage -> BoundaryStage -> PlanResolutionStage -> OffloadPlanExecutor`) with an explicit `ExecutionContext` (`src/goe/orchestration/context.py`) and table-level `filelock` mutex (`orchestration_lock_for_table`).
- `src/goe/cli/_lazy.py` (`resolve_lazy_attribute` + `bind_lazy_imports`) preserves fast CLI startup (~170ms) while honoring `@patch` mocks already in `module.__dict__`; keep `from goe.cli.main import cli, main` eager in `src/goe/cli/__init__.py`.
- All 6 AST/token rules in `tools/verify_architecture.py` (`raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, `inline-comment`) enforce zero unbaselined violations.
<!-- truth: end -->

## Workflow

1. **Load Suppression & Checklist Catalogs**:
   - Read [Checklist (`ORCH-01..06`)](references/checklist.md) and [False-Positive Suppressions (`FP-ORCH-01..04`)](references/false-positive-suppressions.md) before flagging any finding.
2. **Inspect Changed Files & Surrounding Context**:
   - Read the full target files around every diff hunk in this domain to verify callers, types, resource cleanup, and concurrency invariants.
3. **Evaluate Two-Axis Conformance**:
   - Check spec/behavior correctness, public-seam test strength, and adherence to `ORCH-01..06` and `tools/verify_architecture.py`.
4. **Filter Against Suppressions**:
   - Drop any candidate finding matching a `DO NOT FLAG` rule in [False-Positive Suppressions](references/false-positive-suppressions.md) or lacking a concrete failure mode.

## Guardrails

- Never flag stylistic preferences already enforced by `ruff` or `mypy` unless a real defect is present.
- Never propose inline `#` comments inside function/method bodies or nested function-scoped imports (both violate `tools/verify_architecture.py`).
- Anchor every finding to an exact `path/to/file.py:line` range, rule ID (`ORCH-NN`), concrete failure scenario, and minimal fix.

## Validation

```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit/orchestration tests/unit/config tests/unit/cli -q
uv run python tools/verify_architecture.py
make lint
```

## Output

Return structured findings citing `[<PREFIX>-NN] path/to/file.py:line — <summary>`, severity (`blocking` | `important` | `nit`), reproduction/failure trace, and concrete fix, or state that zero issues were found across `ORCH-01..06`.

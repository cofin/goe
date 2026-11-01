# Core Orchestration, Typing, Settings & CLI — Patterns & Seams

## Canonical Seam & Test Matrix

| Subsystem Seam | Primary Symbol Anchor | Dependency Category | Canonical Unit Tests |
| :--- | :--- | :--- | :--- |
| Staged Offload Pipeline | `src/goe/orchestration/pipeline.py::OffloadPipeline` | In-process / Ports & Adapters | `tests/unit/orchestration/` |
| Execution Context & Sinks | `src/goe/orchestration/context.py::ExecutionContext` | In-process | `tests/unit/orchestration/test_concurrent_offload_safety.py` |
| Declarative Settings & Options | `src/goe/config/settings.py::GOESettings` | In-process | `tests/unit/config/test_settings.py` |
| Option Registry & Structs | `src/goe/config/options.py::OffloadOperationOptions` | In-process | `tests/unit/config/` |
| Rich-Click CLI & Lazy Binding | `src/goe/cli/_lazy.py::bind_lazy_imports` | In-process | `tests/unit/cli/` |
| Architecture Gate | `tools/verify_architecture.py::verify_architecture` | Static Validation | `tests/unit/` |

## Domain Invariants (`ORCH`)

- **`ORCH-01` (FrozenBaseStruct & Strict Mypy Inheritance)**: All config, stage, and option models inherit from `FrozenBaseStruct(..., frozen=True)` or `BaseStruct` (`src/goe/typing.py`), never `@dataclass` or `dict=True`, and concrete subclasses of `FrozenBaseStruct` repeat `frozen=True` in the class header.
- **`ORCH-02` (Centralized JSON Serialization (`raw-json`))**: All JSON encoding/decoding calls route through `goe.serializers` (`encode_json`, `encode_json_bytes`, `encode_json_into`, `format_json`, `decode_json`), never `json.dumps`/`loads` or `msgspec.json.*` directly.
- **`ORCH-03` (Explicit `ExecutionContext` & Table-Level Mutex)**: Orchestration and stage code threads `ExecutionContext` and `ExecutionSink` explicitly without mutating module globals (`log_fh`, `options`), and acquires `orchestration_lock_for_table` (`src/goe/platform/locking.py`) before mutating table state.
- **`ORCH-04` (Option Registry & `EXPECTED_OFFLOAD_ARGS` Parity)**: New CLI or offload options are registered in `OPTION_REGISTRY` (`src/goe/config/option_registry.py`), reflected in `src/goe/config/options.py`, and stripped/normalized in `OffloadOptions.to_params_dict()` when alias or diagnostic-only.
- **`ORCH-05` (Lazy CLI Binding & Rich-Click Global Config)**: CLI commands in `src/goe/cli/commands/*.py` keep heavy imports under `if TYPE_CHECKING:` + `_LAZY_IMPORTS` (`bind_lazy_imports`), while `src/goe/cli/__init__.py` keeps `from goe.cli.main import cli, main` eager.
- **`ORCH-06` (AST Hygiene (`nested-import`, `member-ordering`, `inline-comment`))**: Zero function-scoped imports, public functions/methods and dunders defined before private `_` helpers, and zero inline `#` comments inside function/method bodies (use Google-style docstrings).

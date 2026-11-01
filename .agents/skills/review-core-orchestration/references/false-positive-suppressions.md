# False-Positive Suppressions: Core Orchestration, Typing, Settings & CLI (`FP-ORCH`)

## `FP-ORCH-01`: DO NOT FLAG `from goe.cli.main import cli, main` in `src/goe/cli/__init__.py` as an eager import violation

- **Directive**: DO NOT FLAG `from goe.cli.main import cli, main` in `src/goe/cli/__init__.py` as an eager import violation.
- **Rationale**: Lazy `__getattr__` lookup for `main` on `goe.cli` collides with the `goe.cli.main` submodule attribute in Python's import machinery; keeping `cli, main` eager in `src/goe/cli/__init__.py` is intentional (`src/goe/cli/_lazy.py`).

## `FP-ORCH-02`: DO NOT FLAG redundant `frozen=True` on `class X(FrozenBaseStruct, frozen=True):`

- **Directive**: DO NOT FLAG redundant `frozen=True` on `class X(FrozenBaseStruct, frozen=True):`.
- **Rationale**: While `FrozenBaseStruct` already sets `frozen=True` at runtime, mypy's `msgspec` plugin requires `frozen=True` in the subclass header to type-check frozen inheritance under strict `mypy`.

## `FP-ORCH-03`: DO NOT FLAG `bind_lazy_imports(__name__, _LAZY_IMPORTS)` at the start of Click command callbacks

- **Directive**: DO NOT FLAG `bind_lazy_imports(__name__, _LAZY_IMPORTS)` at the start of Click command callbacks.
- **Rationale**: Calling `bind_lazy_imports` at callback entry populates `globals()` lazily on command execution while skipping symbols already patched into `module.__dict__` by unit tests.

## `FP-ORCH-04`: DO NOT FLAG `CompositeExecutionSink` swallowing non-critical secondary sink exceptions

- **Directive**: DO NOT FLAG `CompositeExecutionSink` swallowing non-critical secondary sink exceptions.
- **Rationale**: `CompositeExecutionSink` (`src/goe/orchestration/sinks.py`) intentionally isolates secondary telemetry/cache sink errors so primary `RepositoryStepSink` persistence is never aborted.

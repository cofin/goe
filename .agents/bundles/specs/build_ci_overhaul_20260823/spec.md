---
type: Spec
flow_id: build_ci_overhaul_20260823
title: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul
state: planned
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-23T01:15:00Z"
description: Modernization of build backend to Hatchling, UV dependency groups, Ruff linter/formatter, modernized Makefile, and multi-matrix GitHub Actions CI with PyApp standalone binary builds.
tags:
  - spec
  - build
  - ci
  - ruff
  - uv
parent_prd: null
research:
  - modernization_overhaul_20260822
---

# Flow: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul

**Flow ID:** `build_ci_overhaul_20260823`

## Specification

### Code Analysis Summary
- **Current Build System**: `setuptools >= 40.6.0` with `setuptools.build_meta` in `pyproject.toml`.
- **Current Dependencies**: Mixed in `[project.dependencies]` and `[project.optional-dependencies]` with unmanaged versions and no `uv.lock`.
- **Current Quality Tools**: Standalone `black` for formatting; missing unified linter, modern typecheck rules, and automated bump versioning.
- **Current Build & Makefiles**: Legacy `Makefile` invoking raw `python3 -m build` and `pip install` without `uv` integration, while managing sub-make packaging for `target`, `spark-listener`, and `offload-env`.
- **Current CI**: Basic GitHub Actions CI workflows in `.github/workflows/*.yml` using legacy `setup-python@v4`/`v5` and `pip install`.

### Relevant Patterns & Prior Art
- **DMA Standards**: Extracted from `~/code/dma/collector`, `~/code/dma/beekeeper`, `~/code/dma/db-skus`, and `~/code/dma/accelerator`.
- **Build Backend**: `hatchling.build` with `[tool.hatch.build]` dev-mode-dirs and packages.
- **Dependency Groups (PEP 735)**: `[dependency-groups]` for `dev`, `test`, `lint`, `docs`, `build`.
- **Backend Extras (PEP 621)**: Preserve connector extras (`hadoop`, `snowflake`, `sql_server`, `synapse`, `teradata`, `sqlspec`) in `[project.optional-dependencies]`.
- **Ruff Rules**: `target-version = "py310"`, `line-length = 120`, Google docstring convention (`pydocstyle.convention = "google"`), `lint.select = ["ALL"]` with tailored ignores matching DMA.
- **CI Workflows**: `actions/checkout@v4`, `astral-sh/setup-uv@v5`, cross-platform matrix testing across Python 3.10-3.13, and PyApp binary compilation via `cargo-zigbuild`.

### Requirements

#### Functional Requirements
1. `pyproject.toml` uses `hatchling.build` as the build backend with PEP 621 metadata and `requires-python = ">=3.10"`.
2. All development, test, lint, docs, and build dependencies are organized into PEP 735 `[dependency-groups]`.
3. Multi-cloud backend extras (`hadoop`, `snowflake`, `sql_server`, `synapse`, `teradata`) are preserved in `[project.optional-dependencies]` alongside `sqlspec`.
4. `uv` is configured as the package manager with a generated, deterministic `uv.lock`.
5. `ruff` is configured for both linting and formatting, replacing separate `black` invocations.
6. `mypy` and `pyright` configurations are standardized for strict type checking.
7. `Makefile` provides colored, self-documenting targets matching DMA standards (`help`, `install`, `upgrade`, `lint`, `format`, `test`, `test-unit`, `test-integration`, `build`, `clean`, `destroy`) while preserving existing sub-make targets (`target`, `spark-listener`, `spark-basic-auth`, `package-spark-standalone`, `offload-env`, `offload-home-check`, `package`).
8. GitHub Actions workflows (`ci.yaml`, `test.yaml`, `release.yaml`) replace legacy `.yml` workflows, providing automated PR testing, matrix testing across Linux/macOS/Windows on Python 3.10-3.13, wheel builds, and standalone PyApp binary releases using `actions/checkout@v4` and `astral-sh/setup-uv@v5`.
9. Flow knowledge chapters (`workflow.md`, `standards/python.md`, `standards/testing.md`), `.agents/bundles/log.md`, and root `AGENTS.md` are updated to reflect the new canonical commands.

#### Non-Functional Requirements
- All existing unit tests in `tests/unit/` must continue to pass 100% cleanly.
- No changes to core offload domain logic during build overhaul.
- Backward compatibility for `make install-dev` and `make package` targets.

---

## Implementation Plan

### Phase 1: PyProject Modernization & Dependency Groups
- [ ] `pyproject_modernization`: Migrate `pyproject.toml` to Hatchling, PEP 735 dependency groups (`dev`, `test`, `lint`, `docs`, `build`), preserve backend extras, configure Ruff/Mypy/UV, and generate `uv.lock`.

### Phase 2: Code Quality & Ruff Formatting Pass
- [ ] `ruff_formatting_lint_pass`: Execute `ruff format` and `ruff check --fix` across `src/`, `tests/`, and `tools/` with zero regression in unit tests.

### Phase 3: Makefile Modernization
- [ ] `makefile_modernization`: Rewrite `Makefile` with DMA developer targets, colored terminal output, UV execution wrappers, and preserved sub-make packaging orchestration.

### Phase 4: GitHub Actions CI & Standalone Binary Tooling
- [ ] `github_actions_ci_workflows`: Clean up legacy `.yml` workflows, scaffold modern `.yaml` workflows (CI, matrix testing, release) using `actions/checkout@v4` and `astral-sh/setup-uv@v5`, and implement `tools/bundle_python.py` for PyApp packaging.

### Phase 5: Knowledge Base & Workflow Reconciliation
- [ ] `knowledge_and_workflow_reconciliation`: Synchronize `.agents/bundles/knowledge/workflow.md`, standards chapters, `.agents/bundles/log.md`, and `AGENTS.md` with the new canonical tooling.

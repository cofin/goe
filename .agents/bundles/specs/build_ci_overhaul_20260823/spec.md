---
type: Spec
flow_id: build_ci_overhaul_20260823
title: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul
state: planned
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-24T21:45:00Z"
description: Modernization of build backend to Hatchling, UV dependency groups, Ruff linter/formatter, modernized Makefile, and multi-matrix GitHub Actions CI with PyApp standalone binary builds.
tags:
  - spec
  - build
  - ci
  - ruff
  - uv
  - hatchling
  - pyapp
parent_prd: modernization_overhaul_20260823
research:
  - modernization_overhaul_20260822
---

# Flow: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul

**Flow ID:** `build_ci_overhaul_20260823`  
**Parent PRD:** `modernization_overhaul_20260823`  
**Promoted Research:** `modernization_overhaul_20260822`  

## 1. Specification & Code Analysis

### 1.1 Current State Analysis
- **Build Backend**: `pyproject.toml` (lines 113–116) uses `setuptools >= 40.6.0` and `setuptools.build_meta` with legacy `requires-python = ">=3.8"` (line 19).
- **Dependency Management**: Mixed unpinned dependencies in `[project.dependencies]` (lines 32–74) and `[project.optional-dependencies]` (lines 80–112) without PEP 735 dependency groups or a deterministic lockfile (`uv.lock`).
- **Code Quality**: Fragmented standalone `black` formatter without an integrated linter, strict typing configuration, or import sorting.
- **Build & Makefiles**: `Makefile` (lines 1–140) uses raw `python3 -m venv`, `pip install`, and `python3 -m build`, lacking ANSI colorization, self-documenting `make help`, and `uv` execution wrappers, while managing critical sub-make orchestration for `target`, `spark-listener`, `offload-env`, and `package`.
- **CI/CD Pipelines**: Outdated `.github/workflows/` (`ci.yml`, `test.yml`, `release.yml`) relying on legacy `actions/setup-python@v4/v5` and pip commands.

### 1.2 Target Architecture & Reference Patterns
- **Build Backend**: `hatchling.build` with explicit wheel package mapping (`packages = ["src/goe"]`) and source directories (`sources = ["src"]`).
- **UV Dependency Groups (PEP 735)**: Structured groups for `dev`, `test`, `lint`, `docs`, and `build` under `[dependency-groups]`.
- **Backend Connector Extras (PEP 621)**: Preserved optional dependencies (`hadoop`, `snowflake`, `sql_server`, `synapse`, `teradata`) in `[project.optional-dependencies]`, adding `sqlspec` and an `all` meta-extra.
- **Ruff Configuration**: `target-version = "py310"`, `line-length = 120`, Google docstring convention, import sorting (`isort`), and comprehensive rule selection (`lint.select = ["ALL"]`) with DMA-aligned ignores.
- **Modernized Makefile**: Self-documenting `make help`, ANSI color scheme, `uv` command execution, standard DMA developer targets (`install`, `upgrade`, `lint`, `format`, `test`, `test-unit`, `test-integration`, `build`, `clean`, `destroy`), and adapted packaging orchestration.
- **GitHub Actions CI/CD**: Matrix testing across Linux, macOS, and Windows on Python 3.10–3.13 using `actions/checkout@v4` and `astral-sh/setup-uv@v5`, pure Python wheel verification, and cross-compiled PyApp standalone binaries via `tools/bundle_python.py` and `cargo-zigbuild`.

---

## 2. Requirements Matrix

### 2.1 Functional Requirements
1. `pyproject.toml` uses `hatchling.build` as the build backend with PEP 621 metadata (`requires-python = ">=3.10"`).
2. All development, test, lint, documentation, and build dependencies are organized into PEP 735 `[dependency-groups]`.
3. Multi-cloud backend extras (`hadoop`, `snowflake`, `sql_server`, `synapse`, `teradata`, `sqlspec`, `all`) are maintained in `[project.optional-dependencies]`.
4. `uv` is configured as the package manager with a generated, deterministic `uv.lock`.
5. `ruff` is configured for formatting and linting (`line-length = 120`, Google docstring convention), replacing standalone `black`.
6. `mypy` and `pyright` configurations are standardized for static type analysis.
7. `Makefile` provides colored, self-documenting targets matching DMA standards while preserving existing sub-make targets (`target`, `spark-listener`, `spark-basic-auth`, `package-spark-standalone`, `offload-env`, `offload-home-check`, `package`).
8. Modernized GitHub Actions workflows (`ci.yaml`, `test.yaml`, `release.yaml`) replace legacy `.yml` workflows using `actions/checkout@v4` and `astral-sh/setup-uv@v5`.
9. `tools/bundle_python.py` enables standalone, cross-compiled PyApp binary builds for Linux (x86_64, aarch64), macOS (aarch64), and Windows (x86_64).
10. Flow knowledge chapters (`workflow.md`, `standards/python.md`, `standards/testing.md`), `.agents/bundles/log.md`, and root `AGENTS.md` are updated to reflect the canonical tooling.

### 2.2 Non-Functional Requirements
- **Test Integrity**: All 62+ unit test suites in `tests/unit/` must continue to pass 100% cleanly without modification to core offload domain logic.
- **Backward Compatibility**: `make install-dev`, `make install-dev-extras`, and `make package` must function seamlessly.
- **Performance**: `uv sync` must execute in < 2 seconds in a warm cache environment.

---

## 3. Implementation Plan Worksheet

| Task ID | Title | State | Dependencies | Target Files | Verification Strategy |
| :--- | :--- | :---: | :--- | :--- | :--- |
| `pyproject_modernization` | Migrate pyproject.toml to Hatchling, PEP 735 Dependency Groups, Ruff, and UV | closed | None | `pyproject.toml`, `uv.lock` | `static_validation` |
| `ruff_formatting_lint_pass` | Code Quality, Formatting & Ruff Linting Pass | closed | `pyproject_modernization` | `src/goe/`, `tests/`, `tools/`, `pyproject.toml` | `characterization` |
| `makefile_modernization` | Modernize Makefile with DMA Standards, UV Execution & Preserved Packaging | closed | `pyproject_modernization`, `ruff_formatting_lint_pass` | `Makefile` | `static_validation` |
| `github_actions_ci_workflows` | Scaffold GitHub Actions CI/CD Workflows & Standalone PyApp Packaging | open | `pyproject_modernization`, `ruff_formatting_lint_pass`, `makefile_modernization` | `.github/workflows/ci.yaml`, `.github/workflows/test.yaml`, `.github/workflows/release.yaml`, `tools/bundle_python.py` | `static_validation` |
| `knowledge_and_workflow_reconciliation` | Reconcile Knowledge Base & Context Files with Modern Tooling | open | `pyproject_modernization`, `ruff_formatting_lint_pass`, `makefile_modernization`, `github_actions_ci_workflows` | `.agents/bundles/knowledge/workflow.md`, `standards/python.md`, `standards/testing.md`, `.agents/bundles/log.md`, `AGENTS.md` | `documentation_validation` |

---

## 4. Verification Gates

1. **Gate 1 (Dependencies & Packaging)**: `uv lock` succeeds and generates `uv.lock`; `uv sync --all-extras --dev` resolves cleanly; `uv build` produces valid wheel and source distribution in `dist/`.
2. **Gate 2 (Linting & Formatting)**: `uv run ruff format --check src tests tools` and `uv run ruff check src tests tools` report 0 errors.
3. **Gate 3 (Unit Test Regression Guard)**: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit` executes 100% green.
4. **Gate 4 (Makefile Automation)**: `make help`, `make lint`, `make format`, `make test-unit`, and `make build` execute successfully.
5. **Gate 5 (CI/CD & PyApp)**: YAML workflow files parse without syntax error; `uv run python tools/bundle_python.py --help` renders CLI options.
6. **Gate 6 (Documentation & Truth Blocks)**: All knowledge chapters and `AGENTS.md` reflect new canonical commands; truth blocks remain <= 40 lines.\n
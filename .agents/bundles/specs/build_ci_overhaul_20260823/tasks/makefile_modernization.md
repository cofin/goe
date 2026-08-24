---
type: Task
id: build_ci_overhaul_20260823:makefile_modernization
title: Modernize Makefile with DMA Standards & UV Commands
description: Modernize top-level Makefile with standard DMA developer targets, color output, and UV execution.
state: open
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-23T01:15:00Z"
tags:
  - refactor
  - build
  - makefile
  - uv
depends_on:
  - build_ci_overhaul_20260823:pyproject_modernization
  - build_ci_overhaul_20260823:ruff_formatting_lint_pass
files:
  - Makefile
tests:
  - tests/unit
verification_strategy: static_validation
---

# Task: Modernize Makefile with DMA Standards & UV Commands

## Objective
Re-engineer the top-level `Makefile` to follow the DMA standard architecture: self-documenting `make help`, ANSI color styling, `uv` command execution, and structured targets for developer lifecycle operations, while preserving all sub-make targets required for deployment packaging.

## Implementation Details

1. **Header & Help Formatting**:
   - Add `.ONESHELL:`, `.EXPORT_ALL_VARIABLES:`, `.DEFAULT_GOAL:=help`, and colorized `help` target parsing doc comments (`##`).
2. **Developer Targets**:
   - `install`: Runs `uv sync --all-extras --dev`.
   - `install-dev`: Backward-compatible alias for `install`.
   - `upgrade`: Updates `uv` and runs `uv sync --upgrade`.
   - `lint`: Runs `uv run ruff check src tests tools` and `uv run mypy src`.
   - `format`: Runs `uv run ruff format src tests tools` and `uv run ruff check --fix src tests tools`.
   - `test`: Runs `uv run pytest tests/unit`.
   - `test-unit`: Explicit target for unit tests with certificate env flag.
   - `test-integration`: Explicit target for parallel integration tests.
   - `build`: Runs `uv build` (producing wheel and sdist into `dist/`).
   - `clean` & `destroy`: Purges caches, `.venv`, `build/`, `dist/`, and test artifacts cleanly.
3. **Preserved Sub-Make & Packaging Orchestration Targets**:
   - `target`: Compiles runtime tree, injects version/build hash into SQL scripts, and stages templates.
   - `spark-listener`: Invokes `tools/spark-listener/Makefile`.
   - `spark-basic-auth`: Invokes `spark-basic-auth/Makefile`.
   - `package-spark-standalone`: Packages transport and Spark listener binaries.
   - `offload-env`: Invokes `templates/conf/Makefile`.
   - `offload-home-check`: Asserts `$OFFLOAD_HOME` is set.
   - `package`: Invokes `target` and `target/Makefile` to generate `goe_<version>.tar.gz`.

## Verification
- **Strategy**: `static_validation`
- **Initial Evidence**: Legacy `Makefile` using raw pip and manual venv commands.
- **Final Evidence**: `make help` renders styled target list; `make lint`, `make format`, `make test-unit`, `make build` execute successfully.

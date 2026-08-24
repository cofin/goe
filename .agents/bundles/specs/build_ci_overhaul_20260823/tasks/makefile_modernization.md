---
type: Task
id: build_ci_overhaul_20260823:makefile_modernization
title: Modernize Makefile with DMA Standards & UV Commands
description: Modernize top-level Makefile with standard DMA developer targets, color output, and UV execution.
state: open
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-24T21:45:00Z"
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
Re-engineer the top-level `Makefile` to follow the DMA standard architecture: self-documenting `make help`, ANSI color styling, `uv` command execution wrappers, and standard targets (`install`, `upgrade`, `lint`, `format`, `test`, `test-unit`, `test-integration`, `build`, `clean`, `destroy`), while preserving all existing sub-make packaging orchestration rules (`target`, `spark-listener`, `spark-basic-auth`, `package-spark-standalone`, `offload-env`, `offload-home-check`, `package`, `python-goe`).

## Implementation Details

1. Implement `.DEFAULT_GOAL:=help`, `.ONESHELL:`, `.EXPORT_ALL_VARIABLES:`, `MAKEFLAGS += --no-print-directory`.
2. Add ANSI color scheme and self-documenting `awk` help target.
3. Wrap `uv sync --all-extras --dev` in `install`, `install-dev`, and `install-dev-extras`.
4. Wrap `uv lock --upgrade` in `upgrade`.
5. Wrap `uv run ruff` and `uv run mypy` in `lint` and `format`.
6. Wrap `uv run pytest` in `test`, `test-unit`, and `test-integration`.
7. Wrap `uv build` in `build` and `python-goe`.
8. Preserve `target` rule constructing `$(TARGET_DIR)`.

## Verification
- **Strategy**: `static_validation`
- **Initial Evidence**: Legacy `Makefile` using raw pip commands.
- **Final Evidence**: `make help` displays styled help menu; `make lint`, `make format`, `make test-unit`, and `make build` execute successfully.\n
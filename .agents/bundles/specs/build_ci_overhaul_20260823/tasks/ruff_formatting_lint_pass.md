---
type: Task
id: build_ci_overhaul_20260823:ruff_formatting_lint_pass
title: Code Quality & Ruff Formatting Pass
description: Execute code quality, formatting, and linting passes with Ruff across src, tests, and tools.
state: open
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - refactor
  - quality
  - ruff
  - format
  - lint
depends_on:
  - build_ci_overhaul_20260823:pyproject_modernization
files:
  - src/goe/
  - tests/
  - tools/
  - pyproject.toml
tests:
  - tests/unit
verification_strategy: characterization
---

# Task: Code Quality & Ruff Formatting Pass

## Objective
Apply automated code formatting, import sorting, and safe lint fixes using `ruff` across the codebase while preserving all existing runtime behavior and maintaining 100% passing unit tests.

## Implementation Details

1. **Format Codebase**:
   ```bash
   uv run ruff format src tests tools
   ```
2. **Apply Safe Lint Fixes**:
   ```bash
   uv run ruff check --fix src tests tools
   ```
3. **Verify Clean Linting**:
   ```bash
   uv run ruff format --check src tests tools
   uv run ruff check src tests tools
   ```

## Verification
- **Strategy**: `characterization`
- **Initial Evidence**: `black` used exclusively without Ruff linting rules.
- **Final Evidence**: `uv run ruff format --check src tests tools` reports 0 modifications; `uv run ruff check src tests tools` reports 0 errors; `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit` passes 100% green.\n
---
type: Task
id: build_ci_overhaul_20260823:github_actions_ci_workflows
title: Scaffold GitHub Actions CI/CD & Standalone PyApp Packaging
description: Scaffold GitHub Actions matrix CI/CD workflows and PyApp standalone binary build scripts.
state: open
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-23T01:15:00Z"
tags:
  - feature
  - ci
  - github-actions
  - pyapp
  - packaging
depends_on:
  - build_ci_overhaul_20260823:pyproject_modernization
  - build_ci_overhaul_20260823:ruff_formatting_lint_pass
  - build_ci_overhaul_20260823:makefile_modernization
files:
  - .github/workflows/ci.yaml
  - .github/workflows/test.yaml
  - .github/workflows/release.yaml
  - .github/workflows/ci.yml
  - .github/workflows/test.yml
  - .github/workflows/release.yml
  - tools/bundle_python.py
tests:
  - tests/unit
verification_strategy: static_validation
---

# Task: Scaffold GitHub Actions CI/CD & Standalone PyApp Packaging

## Objective
Implement modernized GitHub Actions CI/CD workflows using `actions/checkout@v4` and `astral-sh/setup-uv@v5` for matrix testing across Linux, macOS, and Windows on Python 3.10-3.13, automated wheel verification, and PyApp standalone binary builds with `tools/bundle_python.py`, removing stale legacy `.yml` workflows.

## Implementation Details

1. **Cleanup Legacy Workflows**:
   - Remove stale legacy workflows: `.github/workflows/ci.yml`, `.github/workflows/test.yml`, and `.github/workflows/release.yml`.
   - Preserve `.github/workflows/pr-title.yml`.

2. **`tools/bundle_python.py`**:
   - Port the standalone Python bundling script from DMA to package target distributions with PyApp for zero-dependency binary distribution.

3. **`.github/workflows/ci.yaml`**:
   - Main PR and push workflow using `actions/checkout@v4` and `astral-sh/setup-uv@v5`:
     - Linting and typechecking via `ruff` and `mypy`.
     - Unit test execution on Linux, macOS, and Windows across Python 3.10, 3.11, 3.12, 3.13.
     - Pure Python wheel building with `uv build`.
     - Standalone binary build verification using `pyapp` and `cargo-zigbuild`.

4. **`.github/workflows/test.yaml`**:
   - Reusable test workflow with coverage collection and summary generation.

5. **`.github/workflows/release.yaml`**:
   - Tagged release workflow: builds wheels, signs artifacts, generates PyApp standalone executables for Linux (x86_64, aarch64), macOS (aarch64), and Windows (x86_64), and attaches them to GitHub Releases.

## Verification
- **Strategy**: `static_validation`
- **Initial Evidence**: Legacy `.yml` workflows using old pip commands.
- **Final Evidence**: YAML schema validation passes for all `.yaml` workflow files under `.github/workflows/`; legacy `.yml` files removed; `uv run python tools/bundle_python.py --help` executes without syntax or import errors.

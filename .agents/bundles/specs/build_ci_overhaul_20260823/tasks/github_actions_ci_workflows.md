---
type: Task
id: build_ci_overhaul_20260823:github_actions_ci_workflows
title: Scaffold GitHub Actions CI/CD & Standalone PyApp Packaging
description: Scaffold GitHub Actions matrix CI/CD workflows and PyApp standalone binary build scripts.
state: open
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-24T21:45:00Z"
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
  - tools/bundle_python.py
tests:
  - tests/unit
verification_strategy: static_validation
---

# Task: Scaffold GitHub Actions CI/CD & Standalone PyApp Packaging

## Objective
Implement modernized GitHub Actions CI/CD workflows using `actions/checkout@v4` and `astral-sh/setup-uv@v5` for matrix testing across Linux, macOS, and Windows on Python 3.10–3.13, automated pure Python wheel builds, PyApp standalone cross-compiled binary compilation via `tools/bundle_python.py` and `cargo-zigbuild`, removing legacy `.yml` workflows while preserving `pr-title.yml`.

## Implementation Details

1. Remove legacy `.github/workflows/ci.yml`, `test.yml`, `release.yml`.
2. Create `.github/workflows/test.yaml` (reusable matrix test workflow with `setup-uv@v5`).
3. Create `.github/workflows/ci.yaml` (main PR/push workflow running linting, cross-OS matrix testing, wheel building).
4. Create `.github/workflows/release.yaml` (release workflow creating tarballs, wheels, and PyApp cross-platform standalone binaries).
5. Implement `tools/bundle_python.py` for standalone CPython packaging.

## Verification
- **Strategy**: `static_validation`
- **Initial Evidence**: Outdated `.yml` workflows using legacy `setup-python@v4/v5`.
- **Final Evidence**: Modern `.yaml` workflows validated with YAML syntax checking; `uv run python tools/bundle_python.py --help` executes cleanly.\n
---
type: Task
id: build_ci_overhaul_20260823:knowledge_and_workflow_reconciliation
title: Reconcile Knowledge Base & Context Files with Modern Tooling
description: Reconcile Flow knowledge chapters, development standards, and root instructions with modernized tooling.
state: closed
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-24T22:26:00Z"
tags:
  - docs
  - workflow
  - standards
  - knowledge
depends_on:
  - build_ci_overhaul_20260823:pyproject_modernization
  - build_ci_overhaul_20260823:ruff_formatting_lint_pass
  - build_ci_overhaul_20260823:makefile_modernization
  - build_ci_overhaul_20260823:github_actions_ci_workflows
files:
  - .agents/bundles/knowledge/workflow.md
  - .agents/bundles/knowledge/standards/python.md
  - .agents/bundles/knowledge/standards/testing.md
  - .agents/bundles/log.md
  - AGENTS.md
tests:
  - tests/unit
verification_strategy: static_validation
---

# Task: Reconcile Knowledge Base & Context Files with Modern Tooling

## Objective
Update all Flow knowledge chapters, development standards, change logs, and root context files (`AGENTS.md`) to reflect the modernized Hatchling, UV, Ruff, and Makefile tooling, ensuring all "truth" markers and code snippets remain accurate.

## Implementation Details

1. Update `.agents/bundles/knowledge/workflow.md`:
   - Update truth block with `uv run ruff format`, `uv run ruff check`, `make install`, `uv run pytest tests/unit`.
2. Update `.agents/bundles/knowledge/standards/python.md`:
   - Document Python 3.10+ requirement, Ruff linter/formatter rules (`line-length = 120`), Mypy configuration.
3. Update `.agents/bundles/knowledge/standards/testing.md`:
   - Document pytest commands with UV prefix and client certificate suppression.
4. Append change entry to `.agents/bundles/log.md`.
5. Synchronize root `AGENTS.md`.

## Verification
- **Strategy**: `static_validation`
- **Initial Evidence**: Documentation references legacy `black` formatting and `setuptools`.
- **Final Evidence**: All knowledge documents and `AGENTS.md` reflect current tooling commands; all links resolve cleanly.\n
---
type: Task
id: build_ci_overhaul_20260823:knowledge_and_workflow_reconciliation
title: Reconcile Knowledge Base & Context Files with Modern Tooling
description: Reconcile Flow knowledge chapters, development standards, and root instructions with modernized tooling.
state: open
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-23T01:15:00Z"
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
verification_strategy: documentation_validation
---

# Task: Reconcile Knowledge Base & Context Files with Modern Tooling

## Objective
Update all Flow knowledge chapters, development standards, and root context files to reflect the modernized Hatchling, UV, Ruff, and Makefile canonical commands and workflows.

## Implementation Details

1. **`knowledge/workflow.md`**:
   - Update truth markers and canonical commands: `make install`, `make lint`, `make format`, `make test-unit`, `uv run pytest`, `uv build`.
2. **`knowledge/standards/python.md` & `standards/testing.md`**:
   - Document `ruff` as the single authoritative linter and formatter.
   - Document `uv sync` and PEP 735 dependency groups for test execution.
3. **`AGENTS.md`**:
   - Synchronize core invariants and developer command references.
4. **`bundles/log.md`**:
   - Record completion of `build_ci_overhaul_20260823`.

## Verification
- **Strategy**: `documentation_validation`
- **Initial Evidence**: Knowledge chapters contain stale references to `setuptools` and `black`.
- **Final Evidence**: All knowledge chapters updated; all internal markdown links resolve; truth blocks remain <= 40 lines.

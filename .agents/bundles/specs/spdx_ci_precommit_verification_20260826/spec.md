---
type: Spec
flow_id: spdx_ci_precommit_verification_20260826
title: "Chapter 4: CI Enforcement, Pre-commit Integration & Developer Documentation"
state: completed
plan_revision: 1
plan_commit: null
state_revision: 3
current_task: null
last_operation: checkpoint
operation_targets:
  - .github/workflows/ci.yaml
  - .github/workflows/test.yaml
  - AGENTS.md
  - README.md
  - Makefile
last_verified_checkpoint: "CI workflows and developer documentation updated, full test and lint gates passing"
created_at: "2026-08-26T15:20:00Z"
updated_at: "2026-08-26T21:31:00Z"
description: Integrate SPDX validation into CI workflows, pre-commit configuration, and developer guidelines.
tags:
  - spec
  - ci
  - ruff
  - spdx
parent_prd: spdx_copyright_migration_20260826
research: []
---

# Flow: CI Enforcement, Pre-commit Integration & Developer Documentation

**Flow ID:** `spdx_ci_precommit_verification_20260826`  
**Parent PRD:** `spdx_copyright_migration_20260826` (Chapter 4)

## 1. Specification

### 1.1 Scope
1. Ensure GitHub Actions CI (`.github/workflows/ci.yaml` / `test.yaml`) executes lint checks enforcing `CPY001`.
2. Update project guidelines in `AGENTS.md` and `README.md` to document the SPDX 2-line header requirement for new files.
3. Execute full repository validation (`make lint`, `make test-unit`).

---

## 2. Implementation Plan

### Phase 1: CI & Pre-commit Configuration
- [x] `4.1`: Verify and update `.github/workflows/ci.yaml` and `.github/workflows/test.yaml`.

### Phase 2: Project Documentation & Guidelines
- [x] `4.2`: Update `AGENTS.md` and repository guidelines specifying the SPDX header requirement.

### Phase 3: Final Verification Gate
- [x] `4.3`: Run `make lint` and `make test-unit` to guarantee clean CI pass.


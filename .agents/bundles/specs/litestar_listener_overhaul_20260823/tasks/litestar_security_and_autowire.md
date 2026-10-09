---
type: Task
id: litestar_listener_overhaul_20260823:litestar_security_and_autowire
title: Implement litestar-security Authentication Guards and Autowire DI
description: Implement litestar-security authentication guards for API keys and litestar-autowire dependency injection.
state: closed
priority: P1
verification_strategy: behavior_tdd
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
files:
  - src/goe/listener/security.py
  - src/goe/listener/app.py
tests:
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
plan_revision: 1
plan_commit: 57f84ab
state_revision: 2
claimed_by: null
claimed_at: null
blocked_reason: null
unblock_condition: null
next_step: null
last_operation: null
operation_targets: []
last_verified_at: "2026-08-26T15:25:00Z"
last_verified_commit: 57f84ab
verification_evidence:
  - command: "uv run pytest tests/unit/listener/ -v"
    result: "passed"
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-26T15:25:00Z"
commit: 57f84ab
tags:
  - feature
  - litestar
  - security
  - autowire
---

# Task: Implement litestar-security Authentication Guards and Autowire DI

## Objective
Implement authentication guards via `litestar-security` to validate `x-goe-console-key` request headers using constant-time equality checks (`secrets.compare_digest`) and configure `litestar-autowire` for dependency injection of repository clients, cache connections, and configuration objects into controller endpoints.

## Context
All `/api/*` routes require constant-time API key verification and clean dependency injection without global singletons.

## Steps
1. Create `src/goe/listener/security.py` with `console_key_guard`.
2. Configure `AutowirePlugin` and `Provide` dependencies for `SystemService` and repository clients in `src/goe/listener/app.py`.
3. Attach guard and DI dependencies to `/api` routes while keeping `/docs` and `/schema` accessible.

## Verification
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/ -v
  ```
- **Expected Output**: Security guard and DI tests pass green.

## Acceptance Criteria
- [x] `console_key_guard` enforces constant-time verification of `x-goe-console-key`.
- [x] `AutowirePlugin` registers domain packages for `goe.listener`.

## Notes & Discoveries
- `2026-08-26T15:25:00Z` (`57f84ab`): Completed and verified in PR #5.\n
---
type: Task
id: litestar_listener_overhaul_20260823:litestar_security_and_autowire
title: Implement litestar-security Authentication Guards and Autowire DI
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - task
  - litestar
  - security
  - autowire
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
files:
  - src/goe/listener/security.py
  - src/goe/listener/autowire.py
tests:
  - tests/unit/listener/
verification_strategy: behavior_tdd
---

# Task: Implement litestar-security Authentication Guards and Autowire DI

## Objective
Implement security guards using `litestar-security` verifying `x-goe-console-key` tokens and configure `litestar-autowire` for dependency injection of repository clients, Redis pools, and configuration objects.

## Implementation Details

1. Create `src/goe/listener/security.py`:
   - Implement `ConsoleKeyGuard` checking header `x-goe-console-key` against configured cluster credentials.
   - Attach security plugin to Litestar application.
2. Create `src/goe/listener/autowire.py`:
   - Register `AutowirePlugin` with domain providers (`OrchestrationRepoClient`, `OffloadConfig`).

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Missing security guard allowing unauthenticated requests or raw header checks.
- **Final Evidence**: Requests without `x-goe-console-key` to protected endpoints return 401 Unauthorized; requests with valid key return 200 OK.

---
type: Task
id: litestar_listener_overhaul_20260823:litestar_security_and_autowire
title: Implement litestar-security Authentication Guards and Autowire DI
description: Implement litestar-security authentication guards for API keys and litestar-autowire dependency injection.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - feature
  - litestar
  - security
  - autowire
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
files:
  - src/goe/listener/security.py
  - src/goe/listener/autowire.py
  - src/goe/listener/app.py
tests:
  - tests/unit/listener/test_security_guards.py
  - tests/unit/listener/test_autowire_di.py
verification_strategy: behavior_tdd
---

# Task: Implement litestar-security Authentication Guards and Autowire DI

## Objective
Implement authentication guards via `litestar-security` to validate `x-goe-console-key` request headers using constant-time equality checks (`secrets.compare_digest`) and configure `litestar-autowire` for dependency injection of repository clients, Redis pools, and configuration objects into controller endpoints.

## Implementation Details
1. Create `src/goe/listener/security.py` with `console_key_guard`.
2. Create `src/goe/listener/autowire.py` with DI providers for `OrchestrationConfig`, `OffloadMessages`, `OrchestrationRepoClientInterface`, `SystemService`, and `RedisClient`.
3. Update `src/goe/listener/app.py` to attach guard and DI dependencies to `/api` router while keeping `/schema` public.

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_security_guards.py tests/unit/listener/test_autowire_di.py -v
  ```
- **Expected Output**: Security guard and DI tests pass green.\n
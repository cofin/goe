---
type: Task
id: litestar_listener_overhaul_20260823:listener_api_verification_tests
title: Implement End-to-End Litestar Listener API & Contract Test Suite
description: Implement comprehensive end-to-end API test suite using Litestar TestClient and AsyncTestClient.
state: closed
priority: P1
verification_strategy: behavior_tdd
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
  - litestar_listener_overhaul_20260823:litestar_security_and_autowire
  - litestar_listener_overhaul_20260823:litestar_queues_and_workers
  - litestar_listener_overhaul_20260823:litestar_granian_and_mcp
files:
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
  - tests/unit/listener/test_jobs.py
  - tests/unit/listener/test_mcp.py
tests:
  - tests/unit/listener/
plan_revision: 1
plan_commit: 57f84ab
state_revision: 5
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
  - command: "export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/ -v"
    result: "passed"
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-26T15:25:00Z"
commit: 57f84ab
tags:
  - test
  - testing
  - litestar
  - api
---

# Task: Implement End-to-End Litestar Listener API & Contract Test Suite

## Objective
Author a comprehensive unit and contract test suite in `tests/unit/listener/` using Litestar's testing utilities to verify all REST routes, security guards, error responses, dependency injection, and OpenAPI schema compliance.

## Context
End-to-end controller and task tests guarantee backwards-compatible JSON contracts across all Listener endpoints.

## Steps
1. Implement `test_system_controllers.py` covering `/status/`, `/config/`, `/schemas/`, `/schemas/{schema}/`, `/columns/`, and `/partitions/`.
2. Implement `test_orchestration_controllers.py` covering `/executions/`, `/executions/{id}/`, `/executions/{id}/execution-log/`, and `/offload/`.
3. Implement `test_jobs.py` and `test_mcp.py` covering background job execution and MCP discovery endpoints.

## Verification
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/ -v
  ```
- **Expected Output**: 100% passing tests with zero regressions.

## Acceptance Criteria
- [x] All `/api/system/*` and `/api/orchestration/*` endpoints verified with `TestClient`.
- [x] Authentication guard and MCP endpoints verified.

## Notes & Discoveries
- `2026-08-26T15:25:00Z` (`57f84ab`): Completed and verified in PR #5.\n
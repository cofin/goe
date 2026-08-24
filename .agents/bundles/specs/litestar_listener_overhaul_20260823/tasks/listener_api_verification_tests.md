---
type: Task
id: litestar_listener_overhaul_20260823:listener_api_verification_tests
title: Implement End-to-End Litestar Listener API & Contract Test Suite
description: Implement comprehensive end-to-end API test suite using Litestar AsyncTestClient.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - test
  - testing
  - litestar
  - api
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
  - litestar_listener_overhaul_20260823:litestar_security_and_autowire
  - litestar_listener_overhaul_20260823:litestar_queues_and_workers
  - litestar_listener_overhaul_20260823:litestar_granian_and_mcp
files:
  - tests/unit/listener/__init__.py
  - tests/unit/listener/conftest.py
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
  - tests/unit/listener/test_security_guards.py
  - tests/unit/listener/test_queues_and_workers.py
  - tests/unit/listener/test_granian_server.py
  - tests/unit/listener/test_mcp_tools.py
tests:
  - tests/unit/listener/
verification_strategy: behavior_tdd
---

# Task: Implement End-to-End Litestar Listener API & Contract Test Suite

## Objective
Author a comprehensive unit and integration test suite in `tests/unit/listener/` using Litestar's `AsyncTestClient` to verify all REST routes, security guards, error responses, dependency injection, and OpenAPI schema compliance.

## Test Matrix
- `test_system_controllers.py`: `/status/`, `/config/`, `/schemas/`, `/schemas/{schema}/`, `/columns/`, `/partitions/`
- `test_orchestration_controllers.py`: `/executions/`, `/executions/{id}/`, `/executions/{id}/execution-log/`, `/offload/`
- `test_security_guards.py`: Missing token (401), invalid token (401), valid token (200), OpenAPI docs bypass
- `test_queues_and_workers.py`: `litestar-queues` tasks execution and cron scheduling
- `test_granian_server.py`: Granian server configuration assembly
- `test_mcp_tools.py`: `litestar-mcp` tools and resources endpoints

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/ -v
  ```
- **Expected Output**: 100% passing tests with zero regressions.\n
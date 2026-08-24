---
type: Task
id: litestar_listener_overhaul_20260823:listener_api_verification_tests
title: Implement End-to-End Litestar Listener API & Contract Test Suite
description: Implement comprehensive end-to-end API test suite using Litestar AsyncTestClient.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
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
  - tests/unit/listener/
tests:
  - tests/unit/listener/
verification_strategy: behavior_tdd
---

# Task: Implement End-to-End Litestar Listener API & Contract Test Suite

## Objective
Author a comprehensive unit and integration test suite using Litestar's `TestClient` and `AsyncTestClient` to verify all REST routes, security guards, error responses, and OpenAPI schema compliance.

## Implementation Details

1. Create `tests/unit/listener/conftest.py` providing test client fixtures with security mocks.
2. Create test modules:
   - `test_system_routes.py`: Verifies `/api/system/health`, `/api/system/version`, and OpenAPI docs.
   - `test_orchestration_routes.py`: Verifies `/api/orchestration/executions`, `/api/orchestration/offload`, and `/api/orchestration/schemas`.
   - `test_security_guards.py`: Verifies header token validation, missing keys, and invalid tokens.
   - `test_mcp_endpoints.py`: Verifies MCP tool invocation and response structures.

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Legacy tests targeting FastAPI routes.
- **Final Evidence**: `uv run pytest tests/unit/listener/` passes 100% green; zero FastAPI dependencies remaining.

---
type: testing
title: Public-Seam TDD & Test Matrix
description: Public-seam TDD rules, dependency seam classification, offline Oracle/BigQuery doubles, and CI verification matrix for GOE.
status: stable
tags:
  - testing
  - tdd
  - pytest
  - seams
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: int-conftest
    resource: tests/integration/conftest.py::pytest_collection_modifyitems
    title: Offline-Safe Integration Test Collection Hook
  - id: listener-conftest
    resource: tests/unit/listener/conftest.py::FakeOracleConnection
    title: Offline Oracle Job Store Test Doubles
  - id: verify-arch
    resource: tools/verify_architecture.py::verify_architecture
    title: AST and Token Architecture Verification Gate
---

# Public-Seam TDD & Test Matrix

<!-- truth: start -->
- Export `GOOGLE_API_USE_CLIENT_CERTIFICATE=false` before running `uv run pytest` so Google Cloud SDK imports do not probe workstation mTLS certificates.
- Exercise public module entrypoints (`OffloadPipeline`, `DialectSqlEngine`, `PredicateCompiler`, `DuckDBEngine`, `OracleJobStore`, `AsyncTestClient`) rather than mocking private `_` methods or asserting internal call sequences.
- Prevent `dotenv` auto-loading in tests via the built-in `PYTEST_CURRENT_TEST` / `GOE_NO_AUTOLOAD_ENV` guard in `src/goe/config/settings.py`; when a test explicitly mutates `os.environ` (such as `OFFLOAD_LISTENER_PORT`), clean up via `monkeypatch` so subsequent tests are unaffected.
- Use `click.unstyle(result.output)` when asserting multi-span Rich CLI output in `CliRunner` tests because `GITHUB_ACTIONS=true` with `TERM=xterm-256color` emits ANSI escape sequences in CI.
- Verify unit tests in a base-dependency environment (`uv sync --dev --locked` without `--all-extras`) so optional-extra imports (`snowflake`, `impyla`, `azure`, `otel`) remain properly guarded.[^verify-arch]
<!-- truth: end -->

## Dependency Seam Classification

| Category | GOE Components | Test Strategy |
| :--- | :--- | :--- |
| **In-process** | `ColumnSpec`, `TYPE_REGISTRY`, `DialectSqlEngine`, `PredicateParser`/`PredicateCompiler`, `GOESettings`, `OffloadPlan`, `ListenerCache` | Instantiate real objects directly in `tests/unit/`; never mock pure domain transforms or SQL AST compilers. |
| **Local-substitutable** | `DuckDBEngine` (`:memory:goe_*`), `ArrowParquetStagingWriter` (`tmp_path`), `StagingStorageService` (`file://`), Litestar `AsyncTestClient` | Run against real in-memory DuckDB sessions, temporary Parquet files, local `file://` obstore backends, and in-process ASGI test clients. |
| **Remote-owned (Ports & Adapters)** | `OracleDatabaseRegistry`, `OracleJobStore`, `BackendBigQueryApi`, `BackendSnowflakeApi`, `BackendSynapseApi` | Inject narrow driver/cursor doubles (`FakeOracleConnection`/`FakeOracleCursor` in `tests/unit/listener/conftest.py`) at the driver boundary for unit tests; verify live SQL against `gvenzl/oracle-free:23-slim-faststart` and opt-in GCP ADC in `tests/integration/`.[^listener-conftest][^int-conftest] |
| **External boundary (Mock)** | `gcloud dataproc` subprocesses, Livy HTTP REST calls, OTLP network exporters | Stub external CLI/HTTP transport boundaries (`InMemorySpanExporter`, mock transport adapters) and assert emitted payloads/spans. |

## Test Suite Layout & Commands

- **Unit Suite (`tests/unit/`)**: Fast, offline-safe tests covering `cli/`, `config/`, `connect/`, `filesystem/`, `listener/`, `observability/`, `offload/`, `orchestration/`, `persistence/`, `report/`, `sync/`, and `validate/`.
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
  uv run pytest tests/unit -q
  ```
- **Integration Suite (`tests/integration/`)**: Offline-collectable integration suite (`tests/integration/conftest.py` defers `OrchestrationConfig.from_dict()` until fixture execution so `pytest --collect-only` works without `ORA_CONN`).[^int-conftest]
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false GOE_TEST_USER_PASS="<pass>"
  uv run pytest tests/integration -n 4
  ```
- **Static & Architecture Gates (`make lint`)**:
  ```bash
  uv run ruff check .
  uv run mypy src/goe
  uv run python tools/verify_architecture.py
  ```

[^int-conftest]: `tests/integration/conftest.py::pytest_collection_modifyitems` — Offline-safe pytest collection and credential skip hooks for integration tests.
[^listener-conftest]: `tests/unit/listener/conftest.py::FakeOracleConnection` — Deterministic in-memory Oracle connection and cursor test double for `OracleJobStore`.
[^verify-arch]: `tools/verify_architecture.py::verify_architecture` — Repository AST and token boundary gate.

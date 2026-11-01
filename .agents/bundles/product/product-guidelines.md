---
type: product
title: Product Guidelines & Invariants
description: Non-negotiable architectural invariants, safety constraints, and project customization rules for GOE.
status: stable
tags:
  - product
  - guidelines
  - safety
  - invariants
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: verify-arch
    resource: tools/verify_architecture.py::verify_architecture
    title: AST and Token Architecture Verification Gate
  - id: column-spec
    resource: src/goe/offload/schema/column_spec.py::ColumnSpec
    title: Immutable Canonical Column Specification
  - id: locking
    resource: src/goe/platform/locking.py::orchestration_lock_for_table
    title: Table-Level Filelock Mutex
---

# Product Guidelines & Invariants

<!-- truth: start -->
- Never acquire exclusive DDL locks or mutate source application schemas during offload; all source reads use snapshot-consistent `AS OF SCN` queries, and repository writes are restricted to `GOE_ADM` and `GOE_REPO`.
- Acquire a table-level mutex (`orchestration_lock_for_table` via `filelock` in `$OFFLOAD_HOME/run/`) before every offload, schema sync, or validation command.[^locking]
- Route all data type conversions through `ColumnSpec` (`src/goe/offload/schema/column_spec.py`) and `TYPE_REGISTRY` (`src/goe/offload/schema/type_registry.py`); implicit lossy downcasting (`NUMBER(38)` to 32-bit `INT` or unscaled `DECIMAL` to float) is forbidden.[^column-spec]
- Enforce all 6 AST/token rules in `tools/verify_architecture.py` (`raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, `inline-comment`) with zero unbaselined violations.[^verify-arch]
- Use `FrozenBaseStruct(..., frozen=True)` / `BaseStruct` (`src/goe/typing.py`, `gc=False`) instead of `@dataclass` across config, metadata, spec, and wire DTO models.
<!-- truth: end -->

## Core Architectural Invariants

### Non-Invasive RDBMS Operations
- GOE never acquires exclusive DDL locks or alters table structures in production RDBMS source application schemas during data offload.
- Source reads execute under a consistent System Change Number (`AS OF SCN`) snapshot so concurrent OLTP writes neither block nor introduce phantom reads.
- Repository persistence is isolated to the administrative schemas (`GOE_ADM`, `GOE_REPO`).

### Concurrency & Execution Isolation
- Every offload, schema evolution, and validation command acquires a table-level execution lock (`orchestration_lock_for_table` in `src/goe/platform/locking.py`).[^locking]
- Concurrent operations targeting the same source table fail fast (`OrchestrationLockTimeout`) rather than corrupting staging metadata.
- Every execution threads an explicit `ExecutionContext` (`src/goe/orchestration/context.py`) and `ExecutionSink` (`src/goe/orchestration/sinks.py`) rather than mutating module-level state.

### Data Integrity & Lossless Transformation
- All column metadata uses the immutable `ColumnSpec` (`src/goe/offload/schema/column_spec.py`) and declarative `TYPE_REGISTRY` (`src/goe/offload/schema/type_registry.py`).[^column-spec]
- Ambiguous Oracle `NUMBER` columns without explicit precision/scale are sampled (`--data-sample-pct`) prior to target DDL generation.
- Data is extracted to isolated staging prefixes (`StagingStorageService`) and loaded atomically via native load jobs (`BigQueryLoadJobIngestStrategy`) or staged `INSERT ... SELECT` / `COPY INTO` merges (`FinalTableMerger`), with guaranteed cleanup of temporary staging objects.

<!-- project-customization: start -->
## Project-Specific Engineering Rules

- Maintain Python >= 3.12 compatibility, format with `ruff` (`line-length = 120`), type-check with strict `mypy src/goe`, use PEP 585 built-in collections (`dict`, `list`) and PEP 604 unions (`str | None`), and place explanations in Google-style docstrings rather than inline `#` comments.[^verify-arch]
- Start all source files with the 2-line SPDX header (`# SPDX-FileCopyrightText: <year> The GOE Authors` and `# SPDX-License-Identifier: Apache-2.0`), enforced via Ruff `CPY001`.
- Export `GOOGLE_API_USE_CLIENT_CERTIFICATE=false` prior to running unit or integration test suites.
- Route all JSON encoding/decoding through `goe.serializers` (`encode_json`, `encode_json_bytes`, `encode_json_into`, `format_json`, `decode_json`) rather than calling `msgspec.json.*` or `json.dumps`/`loads` directly.
- Restrict `import sqlglot` to `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/`; restrict `import oracledb` to `src/goe/persistence/oracle/`, `src/goe/offload/oracle/`, and `src/goe/persistence/registry.py`.
- Keep all imports at module top-level (or under `if TYPE_CHECKING:` / `import_optional*` helpers) and order public functions/methods and dunders above private `_` helpers.
- Never import `vertebra` in core GOE engine modules; the Listener starts via `vertebra run goe.listener.asgi:app` after `verify_vertebra_runtime_gate()` in `src/goe/listener/vertebra_gate.py`.
- Gate all mutating MCP tools (`execute_offload`, `reset_offload_metadata`, `apply_schema_sync`, `cancel_offload_job`) with handler-level `require_mcp_confirmation` (`MCPInputRequiredResult` multi-round-trip challenge + HMAC-SHA256 `confirmation_token`), while keeping direct HTTP REST `POST` callers un-gated.
<!-- project-customization: end -->

[^verify-arch]: `tools/verify_architecture.py::verify_architecture` — Repository AST and token boundary gate enforcing `raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, and `inline-comment`.
[^column-spec]: `src/goe/offload/schema/column_spec.py::ColumnSpec` — Immutable `FrozenBaseStruct` canonical column specification.
[^locking]: `src/goe/platform/locking.py::orchestration_lock_for_table` — Table-scoped `filelock` mutex preventing concurrent mutations on the same source table.

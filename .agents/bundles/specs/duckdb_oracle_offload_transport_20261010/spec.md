---
type: Spec
flow_id: duckdb_oracle_offload_transport_20261010
title: "Chapter 3.4: Opt-In DuckDB Oracle Offload Transport (duckdb-oracle + community gcs)"
state: planned
plan_revision: 3
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-11T00:10:00Z
description: Add an opt-in DUCKDB offload transport that runs one SCN-pinned oracle_query per GOE transport batch through cofin/duckdb-oracle and writes Parquet directly to gcss:// with the community gcs extension using GOE's central ADC credentials, for Oracle-to-BigQuery offloads.
tags: [feature, duckdb, oracle, gcs, bigquery, transport, parquet]
parent: prd_03_sqlspec_bigquery_and_duckdb_engine_20261010
depends_on:
  - sqlspec_oracle_data_layer_migration_20261010
  - sqlglot_ast_and_predicate_engine_20261010
  - bigquery_first_backend_modernization_20261010
research: [research/duckdb_integration.md]
---

# Chapter 3.4: Opt-In DuckDB Oracle Offload Transport

## Specification

### Context & Baseline

- Citations use baseline commit `46890a8`. Transport code moves into `src/goe/offload/transport/` (`constants.py`, `base.py`, `query_import.py`, `factory.py`, ...) in `core_god_module_decomposition_20261010:1.4`; every task names the post-PRD-2 module plus the baseline symbol/line.
- Earlier chapters this flow builds on:
  - `gcp_adc_credential_unification_20261010:1.1` — `goe.util.gcp_credentials.resolve_gcp_credentials(config, scopes)`; PRD 1 requires every GCP client to use it.
  - `sqlglot_ast_and_predicate_engine_20261010:1.3` — Oracle row-source/SCN SQL is produced by `OracleSqlEngine` behind unchanged `OffloadTransportOracleApi` signatures; output still contains literal `AS OF SCN <n>`.
  - `bigquery_first_backend_modernization_20261010:1.1` — Parquet is the default BigQuery staging format; `:1.3` — native BigQuery load of `part*` files; `:1.5` — GCP `AUTO` order in `factory.py`.
- Verified upstream facts (full matrix and URLs in `research/duckdb_integration.md`):
  - `cofin/duckdb-oracle` v0.2.2 is built only for DuckDB 1.5.5, unsigned, installed from `https://cofin.github.io/duckdb-oracle`, not a community extension; `oracle_query(conn_ref, sql)` takes an ATTACH alias (bare secret names rejected); oracle secrets accept `HOST/PORT/SERVICE/USER/PASSWORD`; SQL passes through verbatim (literal `AS OF SCN` works); auth is `OCI_CRED_RDBMS` only; 30 s OCI call timeout and 64 KiB value buffers are hard-coded; no session-init, timeout, LOB or time-zone settings exist.
  - Community `gcs` (`northpolesec/duckdb-gcs`, v0.0.8, signed): `INSTALL gcs FROM community`; claims `gs://`, `gcs://`, `gcss://` (use `gcss://` because core `httpfs` also claims `gs://` and only supports HMAC keys); secrets `TYPE gcp` with `PROVIDER credential_chain|service_account|access_token`; supports `COPY ... TO` writes; caches its storage client per connection.
  - GOE locks `duckdb==1.5.5` transitively (`uv.lock:886-887`); PyPI latest is 1.5.6.

### Problem & Goal

`OffloadTransportQueryImport` (baseline `offload_transport.py:2366-2511`) extracts with one Python thread, ignores `--offload-transport-consistent-read` (`L2421-2425`) and encodes rows in Python before uploading; larger tables need Spark/Dataproc. An opt-in DuckDB transport reuses GOE split planning (`_get_transport_split_type`, `_get_transport_row_source_query` with `AS OF SCN`) and Oracle-side `TO_CHAR` casts (`_build_offload_query_lists(convert_expressions_on_rdbms_side=True, for_qi=True)`) to run one `oracle_query` per batch in parallel, writing `part-NNNNN.parquet` objects straight to GCS for the existing BigQuery load.

### Requirements

- **REQ-1 Configuration:** `OFFLOAD_TRANSPORT_DUCKDB_{VERSION, EXTENSION_PATH, EXTENSION_DIR, EXTENSION_REPOSITORY, THREADS, MEMORY_LIMIT, TEMP_DIRECTORY, MAX_BYTES}` on `OrchestrationConfig`. → Task 1.1
- **REQ-2 Engine helpers:** bounded batch connections, `oracle`/`gcs` LOAD-then-INSTALL, temporary escaped secrets, ATTACH alias, `gcss://` rewriting, Parquet cast projection, SCN invariant, `COPY` SQL. → Task 1.2
- **REQ-3 Transport:** `OffloadTransportDuckDB` with SCN-pinned per-batch queries for PARTITION/SUBPARTITION/EXTENT/MOD/ID_RANGE splits, `ORA_SDTZ=UTC`, one ADC access token per run, fresh connection per batch, row/byte context, `post_transport_tasks`, secret-free logging, spill cleanup, dry-run parity. → Task 1.3
- **REQ-4 Registration:** `DUCKDB` method and `OFFLOAD_TRANSPORT=DUCKDB` rule set, offline availability gate, factory branch, CLI help; never in `AUTO`. → Task 1.4
- **REQ-5 Public-Before-Private Function & Method Ordering:** In all new and modified Python modules and test suites (`duckdb_constants.py`, `duckdb_engine.py`, `duckdb_transport.py`, `duckdb_availability.py`, `factory.py`, `orchestration_defaults.py`, `orchestration_config.py`, `config_validation_functions.py`, `offload.py`, and their unit tests), all public functions/methods and dunder lifecycle methods (`__init__`, etc.) are grouped at the top of each module and class body, with private (`_...`) helpers placed at the bottom. → Tasks 1.1–1.4

### Non-Goals & Limits

- No DuckDB cross-engine validation and no DuckDB dev/test backend (research §1).
- No local-file fallback: DuckDB is gated to BigQuery, whose staging is always `gs://`.
- Ineligible (gate returns False with a logged reason): non-BigQuery targets, non-`gs` filesystems, Avro staging, DuckDB version drift, Oracle Wallet auth, non-EZConnect DSNs, tables above `OFFLOAD_TRANSPORT_DUCKDB_MAX_BYTES`, CLOB/NCLOB/BLOB/LONG/LONG RAW/RAW/XMLTYPE columns.
- Known runtime limits documented to operators: 30 s per OCI round trip; one access token per run (a batch must finish within the token lifetime, default 3600 s); `ORA_SDTZ=UTC` is process-global; extension INSTALL needs network unless `OFFLOAD_TRANSPORT_DUCKDB_EXTENSION_DIR`/`EXTENSION_PATH` is pre-seeded.
- **`DUCK-D1` (RESOLVED)**: `DUCKDB` is strictly opt-in (`--offload-transport-method=DUCKDB` / `OFFLOAD_TRANSPORT=DUCKDB`) and excluded from `AUTO`, and adds no DuckDB verification engine because `cofin/duckdb-oracle` is unsigned, has hard-coded timeouts/buffers and password-only auth, and `CrossDbValidator` already pushes validation to Oracle and BigQuery. If `AUTO` is chosen later, the hook is `GCP_AUTO_TRANSPORT_METHODS` in `src/goe/offload/transport/factory.py`.
- **`DUCK-D2` (RESOLVED)**: DuckDB version control uses the runtime gate (`OFFLOAD_TRANSPORT_DUCKDB_VERSION`, default `1.5.5`) rather than pinning `duckdb==1.5.5` in `pyproject.toml`, preserving transitive dependency flexibility while failing fast on ABI mismatch.
- **`DUCK-D3` (RESOLVED)**: Extension supply chain supports local air-gapped loading via `OFFLOAD_TRANSPORT_DUCKDB_EXTENSION_PATH` / `OFFLOAD_TRANSPORT_DUCKDB_EXTENSION_DIR` and falls back to `INSTALL oracle FROM <repository>` with `allow_unsigned_extensions` when unset.

### Task Breakdown & File Ownership

| Task | Title | Strategy | Priority | Depends On | Files | Tests |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1.1 | `OFFLOAD_TRANSPORT_DUCKDB_*` options | `behavior_tdd` | P1 | — | `src/goe/config/orchestration_defaults.py`, `src/goe/config/orchestration_config.py`, `src/goe/config/config_validation_functions.py`, `templates/conf/offload.env.template.bigquery` | `tests/unit/config/test_duckdb_transport_config.py` |
| 1.2 | Constants and engine helpers | `behavior_tdd` | P1 | — | `src/goe/offload/transport/duckdb_constants.py`, `src/goe/offload/transport/duckdb_engine.py`, `tests/unit/offload/transport/__init__.py` | `tests/unit/offload/transport/test_duckdb_engine.py` |
| 1.3 | `OffloadTransportDuckDB` | `behavior_tdd` | P2 | 1.1, 1.2 | `src/goe/offload/transport/duckdb_transport.py` | `tests/unit/offload/transport/test_duckdb_transport.py` |
| 1.4 | Registration, availability gate, factory, CLI help | `behavior_tdd` | P2 | 1.1, 1.3 | `src/goe/offload/offload_constants.py`, `src/goe/offload/transport/constants.py`, `src/goe/offload/transport/duckdb_availability.py`, `src/goe/offload/transport/factory.py`, `src/goe/cli/commands/offload.py`, `tests/unit/offload/test_offload_transport.py` | `tests/unit/offload/transport/test_duckdb_registration.py`, `tests/unit/offload/test_offload_transport.py` |

## Implementation Plan

- [ ] 1.1 Add `OFFLOAD_TRANSPORT_DUCKDB_*` orchestration options ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement DuckDB transport constants and engine helpers ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Implement `OffloadTransportDuckDB` (SCN-pinned batches to `gcss://` Parquet) ([tasks/1.3.md](tasks/1.3.md))
- [ ] 1.4 Register the opt-in `DUCKDB` method, availability gate and factory branch ([tasks/1.4.md](tasks/1.4.md))

## Verification Commands

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/config/test_duckdb_transport_config.py tests/unit/offload/transport -q
uv run pytest tests/unit -q
uv run python -c "import ast,sys; is_priv=lambda n:n.startswith('_') and not (n.startswith('__') and n.endswith('__')); bad=[(p,getattr(s,'name','<module>'),f.name) for p in sys.argv[1:] for s in ast.walk(ast.parse(open(p).read())) if isinstance(s,(ast.Module,ast.ClassDef)) for funcs in [[n for n in s.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]] for i,f in enumerate(funcs) if not is_priv(f.name) and any(is_priv(g.name) for g in funcs[:i])]; assert not bad, bad" src/goe/config/orchestration_defaults.py src/goe/config/orchestration_config.py src/goe/config/config_validation_functions.py src/goe/offload/transport/duckdb_constants.py src/goe/offload/transport/duckdb_engine.py src/goe/offload/transport/duckdb_transport.py src/goe/offload/transport/duckdb_availability.py src/goe/offload/transport/factory.py src/goe/cli/commands/offload.py tests/unit/config/test_duckdb_transport_config.py tests/unit/offload/transport/test_duckdb_engine.py tests/unit/offload/transport/test_duckdb_transport.py tests/unit/offload/transport/test_duckdb_registration.py
uv run ruff check src/goe tests/unit
uv run ruff format --check src/goe tests/unit
uv run mypy src/goe
```

## Continuity Snapshot

- **State:** `planned`; current task: none.
- **Next exact step:** after `bigquery_first_backend_modernization_20261010` completes, claim Task `1.1` (`tasks/1.1.md`), then execute `1.2` → `1.3` → `1.4` sequentially.
- **Plan identity:** `plan_revision: 3`, `plan_commit: null`.
- **Decisions:** `DUCK-D1` (resolved — opt-in only, excluded from `AUTO`), `DUCK-D2` (resolved — runtime version gate), `DUCK-D3` (resolved — local extension path/dir with repository fallback).
- **Knowledge:** `.agents/bundles/knowledge/patterns/index.md`, `.agents/bundles/product/tech-stack.md`, `research/duckdb_integration.md`.

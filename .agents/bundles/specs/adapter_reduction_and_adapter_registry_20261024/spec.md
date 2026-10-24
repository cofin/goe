---
type: Spec
flow_id: adapter_reduction_and_adapter_registry_20261024
title: "Chapter 5.1: Adapter Reduction and AdapterRegistry"
state: completed
plan_revision: 1
plan_commit: null
state_revision: 1
current_task: null
last_operation: finish
operation_targets: ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7"]
last_verified_checkpoint: "1.7"
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-24T19:21:00Z
description: "Removes the Sqoop transport, the MapRFS filesystem scheme, and the Teradata frontend and repository client, and replaces the adapter factory modules with one declarative AdapterRegistry."
tags: [refactor, adapters, transport, configuration]
parent_prd: prd_05_foundation_typing_settings_and_adapter_reduction_20261024
depends_on: []
research:
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/goe-architecture-redesign.md
---

# Chapter 5.1: Adapter Reduction and AdapterRegistry

## Specification

### 1. Overview and Goals

1. Delete the Sqoop transport (`SQOOP`, `SQOOP_BY_QUERY`, the `SQOOP` value of `OFFLOAD_TRANSPORT`), its availability checks, canary, RDBMS hooks, options, configuration keys, CLI flags, Listener fields, template variables, and tests.
2. Delete the MapRFS filesystem scheme (`maprfs`) and the `MAPR` backend distribution with their validation, Hive DDL location pattern, test framework reference, and template text.
3. Delete the Teradata frontend (`src/goe/offload/teradata/`), the Teradata repository client (`src/goe/persistence/teradata/`), their configuration keys, template, `teradata` extra, test framework, tests, and knowledge chapter.
4. Replace `src/goe/offload/factory/*.py` and `src/goe/persistence/factory/orchestration_repo_client_factory.py` with `src/goe/offload/registry.py`: a declarative table of frozen `LazyTarget` entries keyed by adapter kind and key (frontend type, backend type, transport method, staging format, repository type), one `resolve_dry_run()` lookup path that never imports adapter modules, and `create_*` constructors that keep every factory's defaulting behavior. Every caller migrates in the task that deletes the factory it used.

Implementation order is registry first, then the test harness, then transport, transport RDBMS API, backend, frontend and repository adapters, then the configuration surface. This order keeps every file in exactly one task: each factory module is deleted (with its Teradata or Sqoop branch) in the task that migrates its last caller, and the Teradata and Sqoop modules are deleted only after nothing imports them.

### 2. Code Analysis Summary

- Sqoop transport: `src/goe/offload/hadoop/sqoop_offload_transport.py` (511 LOC). Selection and validation in `src/goe/offload/transport/factory.py:17,27-28,42-44,101-107,150-192,220-247,374-381`, constants in `src/goe/offload/transport/constants.py:11,16-17,24-25,47,56-59`, availability in `src/goe/offload/transport/availability.py:29-30,243-338`, base-class hooks in `src/goe/offload/transport/base.py:57-60,104-115,170-181,294-296,412-426,688-723`, facades in `src/goe/offload/offload_transport.py:21-22,51-53` and `src/goe/offload/factory/offload_transport_factory.py:473`, RDBMS hooks in `src/goe/offload/offload_transport_rdbms_api.py:117,207-237,241-247`, `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py:250-318,763-853`, `src/goe/offload/microsoft/mssql_offload_transport_rdbms_api.py:78,155-177`, connect checks in `src/goe/connect/connect.py:36,321` and `src/goe/connect/connect_transport.py:31,68-70,107-131`, options in `src/goe/config/options.py:107-109,312-316`, configuration in `src/goe/config/orchestration_config.py:165-169,329-333,757-767`, defaults in `src/goe/config/orchestration_defaults.py:683-685,717-724,735-737,841-862`, validation in `src/goe/config/config_validation_functions.py:372`, CLI in `src/goe/cli/commands/offload.py:347,477-492` and `src/goe/cli/config.py:122-124`, Listener fields in `src/goe/listener/schemas.py:238-240`, operation fields in `src/goe/orchestration/operation.py:341,632-634,1539-1541,1709-1714`.
- Shared code that only mentions Sqoop in its name and stays: the fixed Oracle session parameters returned by `_get_fixed_sqoop_parameters` (`oracle_offload_transport_rdbms_api.py:853`) are applied to every transport session (`include_fixed_sqoop` defaults to `True` everywhere except `sqoop_offload_transport.py:330`), so they are kept and renamed `_get_fixed_session_parameters`. Docstrings in `src/goe/offload/query_import_interface.py:52`, `src/goe/offload/staging/staging_file.py:91`, and `src/goe/offload/microsoft/mssql_frontend_api.py:288-290` are reworded; the formats they describe stay.
- MSSQL frontend: `choose_offload_transport_method` returns `SQOOP` for every MSSQL offload (`transport/factory.py:191-192`) and the MSSQL transport RDBMS API raises `NotImplementedError` for Query Import and Spark row-source queries (`mssql_offload_transport_rdbms_api.py:46-150`). After Sqoop removal no transport can move MSSQL data; MSSQL offloads fail with `OffloadTransportException("Unsupported DB type: mssql")`.
- MapRFS: `src/goe/filesystem/goe_dfs.py:49,62`, `src/goe/config/config_validation_functions.py:17,28,156-159`, `src/goe/offload/offload_constants.py:48,55`, `src/goe/filesystem/cli_hdfs.py:33,76`, `src/goe/util/hive_ddl_transform.py:222-238`, `tests/testlib/test_framework/hadoop/hadoop_backend_testing_api.py:16,849`, `templates/conf/offload.env.template.hadoop:102`.
- Teradata: `src/goe/offload/teradata/` (7 modules), `src/goe/persistence/teradata/teradata_orchestration_repo_client.py`, `DBTYPE_TERADATA` and `TERADATA_FRONTEND_CAPABILITIES` in `src/goe/offload/offload_constants.py:20,488`, split-type constants in `src/goe/offload/offload_transport_rdbms_api.py:34-35`, rule list in `transport/factory.py:168`, configuration in `orchestration_config.py:33,185-190,349-354,801-809,845-846`, defaults in `orchestration_defaults.py:27,168,596-617`, validation in `config_validation_functions.py:35,281-282,312-313,375-395`, template `templates/conf/offload.env.template.teradata` and `templates/conf/Makefile:17-20,48-74,84-87`, extra `pyproject.toml` `teradata = ["pyodbc"]`, test framework `tests/testlib/test_framework/teradata/` and `tests/testlib/test_framework/factory/frontend_testing_api_factory.py:8,39-48`, unit tests listed in task 1.6, knowledge `.agents/bundles/knowledge/frontends/teradata.md` with index lines `.agents/bundles/knowledge/frontends/index.md:20` and `.agents/bundles/knowledge/index.md:34`.
- Factories: `backend_api_factory.py` (119 LOC), `backend_table_factory.py` (142), `frontend_api_factory.py` (85), `offload_source_table_factory.py` (77), `offload_transport_factory.py` (20, facade), `offload_transport_rdbms_api_factory.py` (45), `query_import_factory.py` (29), `staging_file_factory.py` (76), `persistence/factory/orchestration_repo_client_factory.py` (30). The `*_factory_ctx` context managers (`backend_api_factory.py:108-119`, `frontend_api_factory.py:74-85`) have no callers and are not ported. `OffloadSourceTable.create` returns `None` for an unknown frontend type (`offload_source_table_factory.py:39-77`); the registry raises instead. 26 production modules and 46 test modules import a factory (task worksheets list each call site).
- Mypy runs with `ignore_missing_imports = true` and `follow_imports = "silent"` (`pyproject.toml` `[tool.mypy]`); the plan still deletes every lazy import of a deleted module in the same task, so no task relies on that setting.

### 3. Requirements

- R1: `src/goe/offload/registry.py` defines `AdapterKind`, frozen `LazyTarget` and `AdapterEntry` structs, `AdapterNotRegisteredError`, `AdapterRegistry` with `keys()`, `resolve_dry_run()` (no adapter import), and `resolve()`, the default entry table for retained adapters only, and `create_frontend_api`, `create_source_table`, `create_transport_rdbms_api`, `create_transport`, `create_backend_api`, `create_backend_table`, `create_staging_file`, `create_query_import_encoder`, `create_repository_client` with the factories' `dry_run`, metadata, and subpartition behavior.
- R2: Every factory module under `src/goe/offload/factory/` and `src/goe/persistence/factory/` is deleted and no module imports `goe.offload.factory` or `goe.persistence.factory`.
- R3: Sqoop transport code, constants, availability checks, canary, RDBMS hooks, CLI flags, option and configuration keys, Listener fields, `SQOOP_*` environment fallbacks, templates, and tests are deleted; `AUTO` on non-GCP backends evaluates `OFFLOAD_TRANSPORT_GOE_METHODS + OFFLOAD_TRANSPORT_GCP_METHODS`; `--offload-transport-method=SQOOP` fails with `Unsupported transport method: SQOOP`; `OFFLOAD_TRANSPORT=SQOOP` fails configuration validation.
- R4: MapRFS scheme and MapR distribution handling are deleted; `OFFLOAD_FS_SCHEME=maprfs` fails `normalise_filesystem_options` with the existing "must be one of" message.
- R5: Teradata frontend, repository client, configuration keys, template, extra, test framework, tests, and knowledge chapter are deleted; `FRONTEND_DISTRIBUTION=TERADATA` resolves to the Oracle default exactly as any unknown value does in `frontend_db_type_default`.
- R6: Retained behavior is unchanged: Oracle and MSSQL frontends, Oracle repository, BigQuery, Snowflake, Synapse, Hive, Impala, and Spark backends, Query Import, Spark Submit, Spark Thrift, Livy, Dataproc, Dataproc Batches, and DuckDB transports, Avro and Parquet staging, and the golden characterization suite.
- R7: Integration tests still collect offline (`GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only -q`).
- R8 (risk): MSSQL loses its only data transport. Mitigation: explicit refusal message and a focused test; the decision on an MSSQL transport belongs to Chapter 6.4.
- R9 (risk): mixed-concern files are edited once. Mitigation: task file lists are disjoint, and each task lists the Sqoop or Teradata edits it makes in files it owns for registry reasons.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/offload/test_registry.py` |
| R2 | 1.3, 1.4, 1.5, 1.6 | `git grep -n "goe.offload.factory\|goe.persistence.factory" -- src tests` returns nothing after 1.6 |
| R3 | 1.2, 1.3, 1.4, 1.5, 1.6, 1.7 | `tests/unit/offload/test_offload_transport.py`, `tests/unit/offload/test_gcp_transport_selection.py`, `tests/unit/cli/test_offload_command.py`, `tests/unit/config/test_config_validation_functions.py` |
| R4 | 1.2, 1.7 | `tests/unit/config/test_config_validation_functions.py`, `tests/unit/filesystem/test_goe_dfs.py` |
| R5 | 1.2, 1.4, 1.6, 1.7 | `tests/unit/config/test_orchestration_config.py`, `tests/unit/offload/test_offload_source_table.py`, `git grep -i teradata -- src tests templates pyproject.toml` returns nothing after 1.7 |
| R6 | 1.3–1.6 | `tests/unit/characterization/test_offload_bigquery_golden.py`, `tests/unit/offload` |
| R7 | 1.2 | offline integration collection |
| R8 | 1.3 | `test_choose_method_refuses_mssql` |
| R9 | all | disjoint `files` lists |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run ruff format --check src/goe tests/unit tests/integration tests/testlib
uv run ruff check src/goe tests/unit tests/integration tests/testlib
uv run mypy src/goe
GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only -q
uv run pytest tests/unit -q
git grep -n -i "sqoop\|teradata\|maprfs\|BACKEND_DISTRO_MAPR" -- src tests templates pyproject.toml
git grep -n "goe.offload.factory\|goe.persistence.factory" -- src tests
uv run python -c "import ast,pathlib; is_priv=lambda n:n.startswith('_') and not (n.startswith('__') and n.endswith('__')); bad=[(str(p),getattr(s,'name','<module>'),f.name) for p in sorted(pathlib.Path('src/goe').rglob('*.py')) for s in ast.walk(ast.parse(p.read_text())) if isinstance(s,(ast.Module,ast.ClassDef)) for funcs in [[n for n in s.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]] for i,f in enumerate(funcs) if not is_priv(f.name) and any(is_priv(g.name) for g in funcs[:i])]; print(len(bad))"
```

Expected: format, lint, mypy, collection, and unit tests pass; both `git grep` commands print nothing; the ordering command prints a number no larger than its value before the chapter started (the chapter adds no ordering violations; modules it rewrites are fully ordered).

## Implementation Plan

### Phase 1: Registry and Test Harness
- [x] 1.1 Add AdapterRegistry with lazy targets for retained adapters ([tasks/1.1.md](tasks/1.1.md))
- [x] 1.2 Remove Sqoop, MapRFS, and Teradata cases from integration scenarios and the test framework ([tasks/1.2.md](tasks/1.2.md))

### Phase 2: Adapter Removal and Factory Retirement
- [x] 1.3 Delete the Sqoop transport and construct transports through the registry ([tasks/1.3.md](tasks/1.3.md))
- [x] 1.4 Construct transport RDBMS APIs, staging files, and Query Import encoders through the registry ([tasks/1.4.md](tasks/1.4.md))
- [x] 1.5 Construct backend APIs and backend tables through the registry ([tasks/1.5.md](tasks/1.5.md))
- [x] 1.6 Construct frontend APIs, source tables, and repository clients through the registry and delete the Teradata frontend ([tasks/1.6.md](tasks/1.6.md))

### Phase 3: Configuration Surface
- [x] 1.7 Remove the Sqoop, MapRFS, and Teradata configuration surface ([tasks/1.7.md](tasks/1.7.md))

## Continuity Snapshot

- **Flow / lifecycle**: `adapter_reduction_and_adapter_registry_20261024`, `completed`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: `1.7` (`2026-10-24T19:21:00Z`).
- **Decisions**: registry first so factories are deleted with their Teradata and Sqoop branches; `AdapterNotRegisteredError` subclasses `OffloadException`; `LazyTarget.load()` delegates to `goe.util.module_loader.ensure_module`; canary connectivity checkers stay in `goe.offload.transport.factory` (Chapter 8.3 replaces them with `TransportCanaryProbe`); MSSQL offloads are refused after Sqoop removal; Teradata knowledge mentions outside `frontends/teradata.md` and its index lines are reconciled at chapter archive.
- **Discoveries**: `EXPECTED_OFFLOAD_ARGS` decreased from 85 to 82 keys after removing the 3 Sqoop option fields in task 1.7; `create_transport` falls back to `resolve_dry_run(...).attribute` when a patched `MagicMock` class has no `__name__`.
- **Blockers**: none.
- **Next exact step**: proceed to Chapter 5.2 (`core_typing_serializers_platform_and_architecture_gate_20261024`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 1`.
- **Relevant knowledge**: `AGENTS.md`, `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/transport/index.md`, `.agents/bundles/knowledge/frontends/index.md`, `.agents/bundles/knowledge/standards/python.md`, `.agents/bundles/knowledge/standards/testing.md`.

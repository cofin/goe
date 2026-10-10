---
type: Spec
flow_id: legacy_shim_removal_and_repo_hygiene_20261010
title: "Chapter 1.1: Remove Deprecated Shims, Merge Upstream #275/#278, Purge Dead Modules, and Clean Up Dependencies"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-10T16:26:00Z
description: "Remove deprecated bin/* wrapper scripts, port upstream #278 non-Litestar Redis/listener cleanup and ExecutionId.from_uuid validation, purge 9 unimported dead modules, port upstream #275 release-please + PyPI publish workflow, and migrate stale dependencies (configparser, lark-parser, termcolor) while synchronizing documentation and OKF knowledge bundles."
tags: [chore, cli, dependencies]
parent_prd: prd_01_foundation_adc_and_ci_harness_20261010
research: []
---

# Chapter 1.1: Remove Deprecated Shims, Merge Upstream `#275`/`#278`, Purge Dead Modules, and Clean Up Dependencies

## Specification

### Code Analysis Summary
- **Legacy `bin/*` CLI Wrapper Scripts**: Seven deprecated bash/Python wrapper scripts remain in `bin/`:
  - `bin/offload` (`bin/offload:1-21`), `bin/connect` (`bin/connect:1-21`), `bin/listener` (`bin/listener:1-21`), `bin/logmgr` (`bin/logmgr:1-21`), `bin/agg_validate` (`bin/agg_validate:1-21`), `bin/offload_status_report` (`bin/offload_status_report:1-21`), and `bin/schema_sync` (`bin/schema_sync:1-21`).
  - `Makefile:174-175` creates `$(TARGET_DIR)/bin` and copies `bin/{offload,connect,logmgr,agg_validate}` during `build-package`.
  - `pyproject.toml:289` (`"^bin/",` in `[tool.mypy].exclude`) and `pyproject.toml:354` (`"bin/*",` in `[tool.coverage.run].omit`) still reference `bin/`.
  - `docs/google_cloud_run/goe.sh:20` invokes `${OFFLOAD_HOME}/bin/$*` instead of `goe "$@"`.
- **Upstream `#278` (`dee61e8`, `chore: Remove Offload Listener code`) Non-Litestar Cleanup & Bugfixes**:
  - While `next` retains our modernized Litestar Listener (`src/goe/listener/`) and the 5 `OracleOrchestrationRepoClient` schema introspection methods (`get_offloadable_schemas`, `get_schema_tables`, `get_table_columns`, `get_table_partitions`, `get_table_subpartitions`), the following legacy Redis/listener remnants and bugfixes from `#278` must be ported:
    - `src/goe/util/redis_tools.py:1-35` and `RedisClient` shims in `src/goe/listener/utils/cache.py:189-203,340-350`.
    - Eight `listener_redis_*` config attributes (`listener_redis_host`, `listener_redis_port`, `listener_redis_db`, `listener_redis_username`, `listener_redis_password`, `listener_redis_ssl_cert`, `listener_redis_use_ssl`, `listener_redis_use_sentinel_default`) and `cache_enabled()` in `src/goe/config/orchestration_config.py:98-105,263-270,473-496`, `src/goe/config/orchestration_defaults.py:856-906`, `src/goe/config/config_validation_functions.py:200-201`, and `src/goe/listener/config/application.py:45-54,65-79,83-104`.
    - Legacy `redis_execution_id`, `redis_in_error`, `init_redis_execution_id()`, `redis_publish` parameter on `log()`, and `cache.rpush` blocks in `src/goe/goe.py:24,248-283,303-307`, `src/goe/offload/offload_messages.py:84,106,109,127,143-144,155,165,177-178,189,313-327`, `src/goe/orchestration/orchestration_runner.py:24,210,305`, `src/goe/connect/connect_functions.py:22-25`, `tests/testlib/test_framework/test_functions.py:111-116`, and `tests/testlib/test_framework/offload_test_messages.py`.
    - Dead `test_listener()` function and call in `src/goe/connect/connect.py:227-276,405` and `PRODUCT_NAME_GEL` in `src/goe/orchestration/orchestration_constants.py:16`.
    - `OFFLOAD_LISTENER_REDIS_*` variables in `templates/conf/offload.env.template.listener:13-21`.
    - Legacy scripts `tools/caller.py`, `tools/redis_subscribe.py`, `tools/goe-listener.service`, `tools/goe-listener.sh`, and one-off `tools/migrate_spdx_headers.py`.
    - `ExecutionId._uuid_as_uuid(u)` validation in `src/goe/orchestration/execution_id.py:36-37,75-77` (`from_uuid` validating `isinstance(u, uuid.UUID)`) and `test_orchestration_execution_id_from_uuid_invalid` in `tests/unit/persistence/test_orchestration_repo_client.py:25-39`.
    - Dead `get_offloadable_schemas()` and `get_schema_tables()` `NotImplementedError` stubs (and unused `UUID` / `UUID4` imports) in `src/goe/offload/teradata/teradata_frontend_api.py:15,643-645,694-696` and `src/goe/offload/microsoft/mssql_frontend_api.py:443-445,487-489`.
- **9 Confirmed Unimported Dead Modules**:
  - `src/goe/conductor/__init__.py`, `src/goe/conductor/hybrid_view_service.py`, and `tests/conductor/test_hybrid_view_service.py` (`HybridViewService.__init__` unconditionally raises `NotImplementedError` on line 75).
  - `src/goe/listener/services/hybrid_view.py` (unimported duplicate of `HybridViewService`).
  - `src/goe/util/serialization.py` (redundant wrapper around `src/goe/util/json_tools.py` with zero `src/` imports; `tests/unit/util/test_json_tools.py:20-28,44-45` imports from `goe.util.serialization` instead of `goe.util.json_tools`).
  - `src/goe/util/env.py`, `src/goe/util/text.py`, `src/goe/util/uuids.py` (unused pass-through shims with zero `src/` or `tests/` imports).
  - `src/goe/util/exception_trigger.py`, `src/goe/util/local_cache.py`, `src/goe/util/retry_logic.py` (legacy 2016 modules with zero `src/` or `tests/` imports).
- **Upstream `#275` (`e12a818`, `chore: Add release-please workflow`), Stale Dependencies & Container Build**:
  - `.github/workflows/release.yaml:1-172` builds wheels and PyApp binaries on `release.created` / `workflow_dispatch`, but lacks `release-please-config.json`, `.release-please-manifest.json`, and the `release-please` (`googleapis/release-please-action@v4`) + `pypi-publish` (`pypa/gh-action-pypi-publish@release/v1` with `attestations: true`) jobs from upstream `#275`.
  - `pyproject.toml:29` declares `"configparser"` (stdlib in Python 3).
  - `pyproject.toml:32` declares `"lark-parser"` (legacy package name for `lark`; `src/goe/offload/predicate_offload.py:19,147-183` and `src/goe/offload/teradata/teradata_partition_expression.py:19,114-136` import `lark`).
  - `pyproject.toml:35,98,108` declares `"sqlspec[performance,mypyc,oracledb,adbc,duckdb]>=0.61.0"`; the `mypyc` extra should be removed in favor of using only the `performance` group (`"sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0"`).
  - `pyproject.toml:39` declares `"termcolor"`, used only in `src/goe/util/hive_table_stats.py:13` (`from termcolor import colored, cprint`) and lines `637, 642, 647, 652, 659, 672`.
  - `docs/google_cloud_run/Dockerfile:1-21` installs `python3.11` and `pip install -r requirements.txt` instead of Python >=3.12, `uv`, and the `goe` CLI entrypoint.
- **Documentation & OKF Knowledge Drift**:
  - `docs/user_guide.md` contains 22 occurrences of `$OFFLOAD_HOME/bin/offload` (lines 31, 49, 106, 120, 142, 218, 226, 236, 271, 291, 326, 353, 363, 382–386, 601, 769, 837, 883).
  - `.agents/bundles/knowledge/patterns/cli-architecture.md:33-36` documents legacy `bin/` wrapper delegators.
  - `.agents/bundles/knowledge/patterns/serialization-and-utils.md:1-54` and `.agents/bundles/product/product.md:19` still reference `Valkey` or lack explicit notes on `MemorySyncCache`.

### Relevant Patterns & Conventions
- [CLI Architecture & Entrypoint Routing](../../knowledge/patterns/cli-architecture.md): `goe` console script (`src/goe/cli/__init__.py`) is the single top-level CLI entrypoint.
- [Serialization, Polars, and Core Utilities](../../knowledge/patterns/serialization-and-utils.md): Core utilities avoid redundant third-party wrappers when standard library or native ANSI helpers suffice.

### Requirements
- **REQ-1**: Delete all seven `bin/*` wrapper scripts (`bin/offload`, `bin/connect`, `bin/listener`, `bin/logmgr`, `bin/agg_validate`, `bin/offload_status_report`, `bin/schema_sync`), remove `bin/` packaging from `Makefile`, update `docs/google_cloud_run/goe.sh` to invoke `goe`, and remove `test_legacy_bin_wrapper_deprecation` from `tests/unit/listener/test_deprecation_shims.py`.
- **REQ-2**: Port upstream `#278` (`dee61e8`) non-Litestar cleanup and bugfixes and purge all 9 confirmed dead modules:
  - Delete `src/goe/util/redis_tools.py`, `tests/unit/listener/test_deprecation_shims.py`, `tools/caller.py`, `tools/redis_subscribe.py`, `tools/goe-listener.service`, `tools/goe-listener.sh`, and `tools/migrate_spdx_headers.py`.
  - Delete the 9 dead modules (`src/goe/conductor/__init__.py`, `src/goe/conductor/hybrid_view_service.py`, `tests/conductor/test_hybrid_view_service.py`, `src/goe/listener/services/hybrid_view.py`, `src/goe/util/serialization.py`, `src/goe/util/env.py`, `src/goe/util/text.py`, `src/goe/util/uuids.py`, `src/goe/util/exception_trigger.py`, `src/goe/util/local_cache.py`, `src/goe/util/retry_logic.py`) and update `tests/unit/util/test_json_tools.py` to test `goe.util.json_tools` directly.
  - Remove `RedisClient` deprecation shims from `src/goe/listener/utils/cache.py`.
  - Remove all 8 `listener_redis_*` config attributes and `cache_enabled()` from `src/goe/config/orchestration_config.py`, `src/goe/config/orchestration_defaults.py`, `src/goe/config/config_validation_functions.py`, `src/goe/listener/config/application.py`, and `templates/conf/offload.env.template.listener`.
  - Remove `redis_execution_id`, `redis_in_error`, `init_redis_execution_id()`, `redis_publish` parameter on `log()`, and `cache.rpush` blocks from `src/goe/goe.py`, `src/goe/offload/offload_messages.py`, `src/goe/orchestration/orchestration_runner.py`, `src/goe/connect/connect_functions.py`, `tests/testlib/test_framework/test_functions.py`, and `tests/testlib/test_framework/offload_test_messages.py`.
  - Remove `test_listener()` and call from `src/goe/connect/connect.py:227-276,405` and `PRODUCT_NAME_GEL` from `src/goe/orchestration/orchestration_constants.py:16`.
  - Port `ExecutionId._uuid_as_uuid(u)` validation in `src/goe/orchestration/execution_id.py` and `test_orchestration_execution_id_from_uuid_invalid` in `tests/unit/persistence/test_orchestration_repo_client.py`.
  - Remove dead `get_offloadable_schemas()` / `get_schema_tables()` stubs from `src/goe/offload/teradata/teradata_frontend_api.py` and `src/goe/offload/microsoft/mssql_frontend_api.py`.
- **REQ-3**: Port upstream `#275` (`e12a818`) `release-please` workflow (`release-please-config.json`, `.release-please-manifest.json`, and `release-please` + `pypi-publish` jobs in `.github/workflows/release.yaml`), remove `"configparser"`, `"termcolor"`, and `bin/` exclusions from `pyproject.toml`, replace `"lark-parser"` with `"lark>=1.1.9"` and replace all 3 occurrences of `"sqlspec[performance,mypyc,oracledb,adbc,duckdb]>=0.61.0"` (lines 35, 98, 108) with `"sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0"` in `pyproject.toml` and `uv.lock`, replace `termcolor` in `src/goe/util/hive_table_stats.py` with native ANSI escape formatting, ensure `src/goe/offload/predicate_offload.py` and `src/goe/offload/teradata/teradata_partition_expression.py` pass all parser unit tests under `lark>=1.1.9`, and modernize `docs/google_cloud_run/Dockerfile` to Python >=3.12 + `uv`.
- **REQ-4**: Replace all `$OFFLOAD_HOME/bin/offload` occurrences in `docs/user_guide.md` with `goe offload` (including a migration note for `bin/*` and `goe.util.redis_tools` removal), and update `.agents/bundles/knowledge/patterns/cli-architecture.md`, `.agents/bundles/knowledge/patterns/serialization-and-utils.md`, and `.agents/bundles/product/product.md`.

### Requirement Traceability Matrix

| Requirement | Task ID | Verification Strategy | Verification Target |
| :--- | :--- | :--- | :--- |
| REQ-1 | `1.1` | `static_validation` | `test ! -d bin && uv run ruff check && uv run pytest tests/unit/cli/` |
| REQ-2 | `1.2` | `regression_tdd` | `test ! -f src/goe/util/redis_tools.py && test ! -d src/goe/conductor && uv run pytest tests/unit/listener/ tests/unit/persistence/test_orchestration_repo_client.py tests/unit/util/test_json_tools.py` |
| REQ-3 | `1.3` | `regression_tdd` | `test -f release-please-config.json && test -f .release-please-manifest.json && ! git grep -q "sqlspec\[.*mypyc" pyproject.toml && uv lock --check && uv run pytest tests/unit/offload/test_predicate_offload.py tests/unit/offload/teradata/ tests/unit/util/` |
| REQ-4 | `1.4` | `documentation_validation` | `! grep -n 'bin/offload' docs/user_guide.md && ! grep -n 'Valkey' .agents/bundles/product/product.md` |

---

## Implementation Plan

- [ ] 1.1 Delete `bin/*` CLI wrapper scripts and update build/shell entrypoints (`tasks/1.1.md`) [P0, static_validation]
- [ ] 1.2 Port upstream `#278` Redis/listener cleanup, remove `redis_tools.py` & `RedisClient` shims, and purge 9 dead modules (`tasks/1.2.md`) (depends on: 1.1) [P0, regression_tdd]
- [ ] 1.3 Port upstream `#275` `release-please` workflow, migrate `lark-parser` to `lark>=1.1.9`, remove `configparser` and `termcolor`, and modernize Cloud Run `Dockerfile` (`tasks/1.3.md`) (depends on: 1.2) [P1, regression_tdd]
- [ ] 1.4 Synchronize `docs/user_guide.md` and OKF knowledge bundle files (`tasks/1.4.md`) (depends on: 1.1, 1.2, 1.3) [P1, documentation_validation]

---

## Continuity Snapshot

- **Current State**: Planned (`state: planned`, `plan_revision: 1`). All 4 task worksheets (`1.1`–`1.4`) are authored with disjoint file ownership, incorporating upstream commits `#275` and `#278` and purging 9 dead modules.
- **Next Action**: Claim and execute Task `1.1` (`tasks/1.1.md`).

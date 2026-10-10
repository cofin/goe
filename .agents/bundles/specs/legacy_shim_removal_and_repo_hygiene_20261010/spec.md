---
type: Spec
flow_id: legacy_shim_removal_and_repo_hygiene_20261010
title: "Chapter 1.1: Remove Deprecated Shims, Port Upstream #278/#275, Purge Dead Modules, and Clean Up Dependencies"
state: planned
plan_revision: 3
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-10T22:20:00Z
description: "Remove the bin/* and Redis deprecation shims, port the non-listener parts of upstream gluent/goe #278 and the release-please workflow of #275, fix ExecutionId.from_uuid validation, purge 9 unimported dead modules, migrate stale dependencies (configparser, lark-parser, termcolor, sqlspec mypyc extra), modernize the Cloud Run image, and synchronize documentation and OKF knowledge."
tags: [chore, cli, dependencies]
parent: prd_01_foundation_adc_and_ci_harness_20261010
depends_on: []
research: []
---

# Chapter 1.1: Remove Deprecated Shims, Port Upstream `#278`/`#275`, Purge Dead Modules, and Clean Up Dependencies

## Specification

### Context

- **Baseline**: every line number in this flow refers to commit `46890a8` (branch `feat/bin-files`). Tasks run sequentially; when a later task edits a file an earlier task of this flow already changed, it cites the symbol name next to the baseline line number.
- **Upstream sources (verified 2026-10-10)**:
  - `gluent/goe#278` = commit `dee61e8f2d9e385cead5fc0f876b7a8fe5b05d1d` "chore: Remove Offload Listener code" (<https://github.com/gluent/goe/commit/dee61e8>). Upstream deleted the whole HTTP listener (`src/goe/listener/**`, `bin/listener`), `src/goe/util/redis_tools.py`, `templates/conf/offload.env.template.listener`, `tools/caller.py`, `tools/redis_subscribe.py`, `tools/goe-listener.service`, `tools/goe-listener.sh`; removed all `listener_*` config, `cache_enabled()`, `normalise_listener_options()`, `test_listener()`, `PRODUCT_NAME_GEL`, Redis publishing in `goe.py`/`offload_messages.py`/`orchestration_runner.py`/`connect_functions.py`/`test_functions.py`; removed the five listener schema-introspection methods from the Oracle/Teradata/base repo clients and the `get_offloadable_schemas`/`get_schema_tables` stubs from Teradata/MSSQL frontend APIs; added `ExecutionId._uuid_as_uuid` plus `test_orchestration_execution_id_from_uuid_invalid`. It did **not** touch `tools/migrate_spdx_headers.py` (fork-local).
  - `gluent/goe#275` = commit `e12a818d35b6996c5750355af886e4cfaa63c3e2` "chore: Add release-please workflow" (<https://github.com/gluent/goe/commit/e12a818>). Upstream changed `.github/workflows/release.yml` (trigger `push: branches: [main]`, new `release-please` job using `googleapis/release-please-action@v4` with `config-file`/`manifest-file`, downstream jobs gated on `needs.release-please.outputs.release_created`, new `pypi-publish` job with `environment: pypi`, `permissions: id-token: write`, `pypa/gh-action-pypi-publish@release/v1` `attestations: true`), added `release-please-config.json` (`{"packages": {".": {"release-type": "python"}}}`) and `.release-please-manifest.json` (`{".": "1.1.0"}`), and set `pyproject.toml` `version` from `1.1.1.dev0` to `1.1.0`.
- **Fork divergence that must be preserved**: this fork keeps the modernized Litestar listener (`src/goe/listener/`). Therefore the port keeps `listener_host`, `listener_port`, `listener_heartbeat_interval`, `listener_shared_token` (`src/goe/config/orchestration_config.py:94-97,252-255,451-460`, `src/goe/config/orchestration_defaults.py:860-873`, `normalise_listener_options()` in `src/goe/config/config_validation_functions.py:184-201`), the five `OracleOrchestrationRepoClient` introspection methods and their base/Teradata declarations (`src/goe/persistence/orchestration_repo_client.py:321,327`, `src/goe/persistence/teradata/teradata_orchestration_repo_client.py:293-297`, used by `src/goe/listener/services/system.py:76-79` and `src/goe/listener/controllers/system.py:47-63`), the listener section of `templates/conf/offload.env.template.listener:1-12`, `templates/conf/Makefile`, and the `OrchestrationRunner` module docstring (`src/goe/orchestration/orchestration_runner.py:4-6`). Only Redis-specific pieces and dead legacy listener helpers (`PRODUCT_NAME_GEL` and `src/goe/listener/utils/ping.py`) are removed.
- **Fork-local Redis plumbing at HEAD** (differs from upstream): `src/goe/goe.py:24`, `src/goe/offload/offload_messages.py:16`, and `src/goe/connect/connect.py:52` import `MemorySyncCache` from `src/goe/listener/utils/cache.py` aliased as `RedisClient`/`cache`; `src/goe/util/redis_tools.py:1-34` and the `RedisClient` branches of `MemoryCache.__getattr__` (`src/goe/listener/utils/cache.py:189-203`) and module `__getattr__` (`src/goe/listener/utils/cache.py:340-350`) are `DeprecationWarning` shims.
- **Legacy CLI wrappers**: seven 20-line Python delegators `bin/offload`, `bin/connect`, `bin/listener`, `bin/logmgr`, `bin/agg_validate`, `bin/offload_status_report`, `bin/schema_sync`; packaged by the `target` recipe at `Makefile:174-175`; exercised by `tests/unit/cli/test_bin_wrappers.py` (fails at baseline because the subprocess uses the system interpreter: `ModuleNotFoundError: No module named 'goe'`) and `tests/unit/listener/test_deprecation_shims.py:32-56`; invoked by `docs/google_cloud_run/goe.sh:20` and `tools/goe-listener.sh:43`. The sole console script is `[project.scripts] goe = "goe.cli.main:cli"` (`pyproject.toml:71`); subcommands registered in `src/goe/cli/main.py:47-53` are `offload`, `connect`, `validate`, `sync`, `report`, `listener`, `logmgr`.
- **Dead modules (verified unimported with `git grep` over `src tests tools bin`)**: `src/goe/conductor/__init__.py`, `src/goe/conductor/hybrid_view_service.py` (`HybridViewService.__init__` raises `NotImplementedError` at line 75; only importer `tests/conductor/test_hybrid_view_service.py`), `src/goe/listener/services/hybrid_view.py` (not exported by `src/goe/listener/services/__init__.py`), `src/goe/util/serialization.py` (only importer `tests/unit/util/test_json_tools.py:20-28`), `src/goe/util/env.py`, `src/goe/util/text.py`, `src/goe/util/uuids.py`, `src/goe/util/exception_trigger.py`, `src/goe/util/local_cache.py`, `src/goe/util/retry_logic.py`.
- **Dependencies**: `pyproject.toml:29` `"configparser"` (stdlib), `:32` `"lark-parser"` (locked `0.12.0`; `lark` 1.3.1 passes all 44 parser-adjacent unit tests unchanged — verified by shadowing the uv-cached wheel on `PYTHONPATH`), `:35,98,108` `"sqlspec[performance,mypyc,oracledb,adbc,duckdb]>=0.61.0"`, `:39` `"termcolor"` (only importer `src/goe/util/hive_table_stats.py:13`, calls at `637,642,647,652,659,672`), `:289` `"^bin/"` (`[tool.mypy].exclude`), `:354` `"bin/*"` (`[tool.coverage.run].omit`), `:10` and `:163` version `1.1.1.dev0`.
- **Cloud Run image**: `docs/google_cloud_run/Dockerfile:1-20` installs `python3.11` from apt and pip-installs the wheel from the release tarball; build context is `docs/google_cloud_run/` with a downloaded `goe.tar.gz` and `offload.env` (`docs/google_cloud_run/README.md:25-50`).
- **Repo gate baselines at `46890a8`**: `uv run ruff check` passes; `uv run mypy src/goe` passes; `uv run ruff format --check src tests` passes (repo-wide `ruff format --check` fails on Python blocks inside 22 Markdown files, including `.agents/bundles/knowledge/patterns/serialization-and-utils.md:37`); `uv run pytest tests/unit` = 1 failed (`tests/unit/cli/test_bin_wrappers.py`), 619 passed, 5 skipped.
- **Plan dry-run evidence (2026-10-10, scratch copy of `src/` + `tests/`)**: applying the exact line edits of Tasks `1.1`-`1.4` and the `hive_table_stats.py` change of Task `1.5` yields `ruff check` clean, `ruff format --check src tests` clean, `mypy src/goe` "no issues found in 219 source files", and `pytest tests/unit` = 595 passed, 5 skipped, 0 failed; Task `1.3`'s regression test was observed red (`AssertionError not raised`) before and green after the fix.
- **Decision resolved (`D-1.1-GEL`)**: `PRODUCT_NAME_GEL` (`src/goe/orchestration/orchestration_constants.py:9`, named after the legacy "Gluent Enterprise Listener") and `src/goe/listener/utils/ping.py` (whose only caller was the removed `test_listener()` in `src/goe/connect/connect.py:240`) are deleted in Task `1.2` along with `"ping"` in `src/goe/listener/utils/__init__.py`, matching upstream `#278`.

### Relevant Patterns & Conventions

- [CLI Architecture & Entrypoint Routing](../../knowledge/patterns/cli-architecture.md)
- [Serialization, Polars, and Core Utilities](../../knowledge/patterns/serialization-and-utils.md)
- [Listener Workers & Embedded Caching](../../knowledge/listener/worker-and-redis.md)
- [Testing Standards](../../knowledge/standards/testing.md)

### Requirements

- **REQ-1**: Delete the seven `bin/*` wrappers and their packaging/test/shell references, and delete the Redis deprecation shims (`src/goe/util/redis_tools.py`, the `RedisClient` branches in `src/goe/listener/utils/cache.py`, `tests/unit/listener/test_deprecation_shims.py`).
- **REQ-2**: Port the non-listener Redis cleanup of upstream `#278`: remove the seven `listener_redis_*` config attributes and the eight `listener_redis_*_default()`/`cache_enabled()` defaults, `redis_execution_id`, `redis_in_error`, `init_redis_execution_id()`, the `redis_publish` parameter, the `cache_enabled` parameter and `cache.rpush` blocks, `test_listener()`, `PRODUCT_NAME_GEL`, `src/goe/listener/utils/ping.py` (and its re-export in `src/goe/listener/utils/__init__.py`), the `ListenerSettings` Redis fields, the `OFFLOAD_LISTENER_REDIS_*` template lines, the Teradata/MSSQL `get_offloadable_schemas`/`get_schema_tables` stubs, and the obsolete `tools/` scripts (`caller.py`, `redis_subscribe.py`, `goe-listener.service`, `goe-listener.sh`, and fork-local `migrate_spdx_headers.py` with its test), while preserving everything listed under "Fork divergence".
- **REQ-3**: Port the upstream `#278` `ExecutionId.from_uuid` validation (`_uuid_as_uuid`) with its regression test.
- **REQ-4**: Delete the nine dead modules plus `tests/conductor/`, and repoint `tests/unit/util/test_json_tools.py` at `goe.util.json_tools`.
- **REQ-5**: Port upstream `#275` release-please (config, manifest, version reset, `release-please` + `pypi-publish` jobs merged into the fork's `uv build`/PyApp `release.yaml`), drop `configparser`/`termcolor`/`bin` exclusions/the `sqlspec` `mypyc` extra, migrate `lark-parser` -> `lark>=1.1.9`, replace `termcolor` with the existing `OffloadMessages.ansi_wrap` helper, re-lock `uv.lock`, and modernize `docs/google_cloud_run/Dockerfile` to Python 3.12 via `uv`.
- **REQ-6**: Remove every remaining `bin/` wrapper, Redis-shim, removed-module, and `lark-parser` reference from user docs, internal design docs, `AGENTS.md`, `.agents/skills/flow-memory-keeper/SKILL.md`, and the OKF knowledge/product bundle.

### Requirement Traceability Matrix

| Requirement | Task | Verification Strategy | Verification Target |
| :--- | :--- | :--- | :--- |
| REQ-1 | `1.1` | `characterization` | `uv run pytest tests/unit/cli tests/unit/listener` green before (deselecting the env-broken bin test) and after; `test ! -e bin`; `! git grep -n "redis_tools" -- src tests` |
| REQ-2 | `1.2` | `characterization` | `uv run pytest tests/unit/config tests/unit/connect tests/unit/offload/test_offload_messages.py tests/unit/listener tests/unit/orchestration` green before/after; `! git grep -n -E "listener_redis\|cache_enabled\|redis_publish\|redis_execution_id\|redis_in_error\|PRODUCT_NAME_GEL\|listener\.utils\.ping" -- src tests templates` |
| REQ-3 | `1.3` | `regression_tdd` | `uv run pytest tests/unit/persistence/test_orchestration_repo_client.py` fails first (`AssertionError not raised`), then passes |
| REQ-4 | `1.4` | `characterization` | `uv run pytest tests/unit/util/test_json_tools.py tests/unit/listener` green before/after; `uv run mypy src/goe` |
| REQ-5 | `1.5` | `static_validation` | `uv lock --check`; YAML/JSON parse of workflow/config; `uv run pytest tests/unit/offload/test_predicate_offload.py tests/unit/offload/test_teradata_partition_expression.py`; `! git grep -n -E "termcolor\|lark-parser\|configparser\|mypyc" -- pyproject.toml src` |
| REQ-6 | `1.6` | `documentation_validation` | `! git grep -n -E "bin/(offload\|connect\|listener\|logmgr\|agg_validate\|offload_status_report\|schema_sync)" -- docs AGENTS.md .agents/skills .agents/bundles/knowledge .agents/bundles/product`; Markdown Python blocks pass `uv run ruff format --check` on edited files |

---

## Implementation Plan

- [ ] 1.1 Remove `bin/*` wrappers and Redis deprecation shims ([tasks/1.1.md](tasks/1.1.md)) [P1, characterization]
- [ ] 1.2 Port upstream `#278` Redis/listener-config cleanup, frontend stubs, and legacy `tools/` scripts ([tasks/1.2.md](tasks/1.2.md)) (depends on: 1.1) [P1, characterization]
- [ ] 1.3 Port upstream `#278` `ExecutionId.from_uuid` validation ([tasks/1.3.md](tasks/1.3.md)) (depends on: 1.2) [P2, regression_tdd]
- [ ] 1.4 Purge 9 unimported dead modules ([tasks/1.4.md](tasks/1.4.md)) (depends on: 1.3) [P2, characterization]
- [ ] 1.5 Port upstream `#275` release-please, migrate dependencies, and modernize the Cloud Run image ([tasks/1.5.md](tasks/1.5.md)) (depends on: 1.4) [P2, static_validation]
- [ ] 1.6 Synchronize docs, `AGENTS.md`, project skill nuance, and OKF knowledge ([tasks/1.6.md](tasks/1.6.md)) (depends on: 1.1, 1.2, 1.3, 1.4, 1.5) [P2, documentation_validation]

---

## Continuity Snapshot

- **Lifecycle**: `state: planned`; current task: none; claimant: none; last verified checkpoint: none.
- **Plan identity**: `plan_revision: 3`, `plan_commit: null`; state identity `state_revision: 0`.
- **Decisions**: `D-1.1-GEL` resolved (delete `PRODUCT_NAME_GEL` and `src/goe/listener/utils/ping.py` in Task `1.2`); `release-please` runs on `push` to `main` (matches upstream `#275` and `.github/workflows/ci.yaml:7-9`).
- **Recent discoveries**: (1) `tests/unit/cli/test_bin_wrappers.py` and `tests/unit/test_migrate_spdx_headers.py` must be deleted with the code they test; (2) `lark` 1.3.1 needs no code change; (3) `goe.util.json_tools` does not export `DEFAULT_TYPE_ENCODERS` (import it from `sqlspec.utils.serializers`); (4) repo-wide `ruff format --check` fails at baseline on Markdown code blocks; (5) `src/goe/listener/utils/ping.py` has zero callers once `test_listener()` is removed and is deleted alongside `PRODUCT_NAME_GEL`.
- **Blockers**: none.
- **Next exact step**: claim Task `1.1` and record the characterization baseline `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/cli tests/unit/listener --deselect tests/unit/cli/test_bin_wrappers.py::test_bin_wrappers_executable`.
- **Relevant knowledge**: `.agents/bundles/knowledge/patterns/cli-architecture.md`, `.agents/bundles/knowledge/listener/worker-and-redis.md`, `.agents/bundles/knowledge/patterns/serialization-and-utils.md`, `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/standards/testing.md`.

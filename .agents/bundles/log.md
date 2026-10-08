---
type: Reference
description: Append-only operational and structural change log for the GOE OKF knowledge bundle.
tags:
  - changelog
  - okf
  - flow
updated_at: "2026-10-04T18:30:00Z"
---

# Change Log

This file records significant lifecycle operations, structural additions, and major evolutions to the GOE knowledge bundle.

## 2026-10-04

- **GOE v2 `main` Baseline Alignment & Functional Parity Remediation (`v2_main_alignment_remediation_20261004`)**:
  - **Chapter 1 (`cli_execution_and_common_options_parity_20261004`, commits `ab561ba`..`c635ac7`)**:
    - Created `src/goe/cli/common.py` (`@common_options` and `extract_common_options`) registering and resolving all 11 global/common options (`--version`, `-v/--verbose`, `--vv/--vverbose`, `-q/--quiet`, `--no-ansi`, `--log-path`, `--log-level`, `--no-version-check`, `--error-before-step`, `--error-after-step`, `--error-on-token`, `--suppress-stdout`) across root `goe`, subcommands, and `bin/*` wrappers.
    - Updated `src/goe/cli/commands/listener.py` with `invoke_without_command=True` so `bin/listener` and `goe listener` invoke `_start_listener_server(...)` by default while preserving `goe listener start` and `goe listener status`.
    - Fixed `goe sync` (`src/goe/cli/commands/sync.py`) to delegate to `normalise_schema_sync_options`, `orchestration_repo_client_factory(..., trace_action="repo_client(schema_sync)")`, and `run_schema_sync(options, messages, execution_id, repo_client)` with non-zero exit propagation.
    - Fixed `goe validate` (`src/goe/cli/commands/validate.py`) to expose `--target-name` and hidden `--dev-log-level`, type `--as-of-scn` as `int`, call `post_process_args(options)` before `run_agg_validate(options)`, and exit via `sys.exit(0 if ret else 1)`; reordered `load_env()` before `check_config_path()` in `src/goe/scripts/agg_validate.py`.
  - **Chapter 2 (`cli_subcommand_options_and_defaults_parity_20261004`, commits `8c85b161`..`ff03d608`)**:
    - Restored all 12 missing `goe offload` options in `src/goe/cli/commands/offload.py` (`--force-Decimal-scale`, `--not-null-columns`, `--allow-nanosecond-timestamp-columns`, `--offload-predicate-type`, `--offload-predicate-modify-hybrid-view`, `--ipa-predicate-type`, `--hash-distribution-threshold`, `--Synthetic-partition-digits`, `--create-backend-db`, `--dev-log-level`, `--verify-row-count`, `--ver-check`), changed `--older-than-days` to `str`, and registered the 6 visible options in `OPTION_GROUPS["goe offload"]` (`src/goe/cli/config.py`).
    - Added hidden `--create-backend-db` (`default=False`) to `goe connect` (`src/goe/cli/commands/connect.py`).
    - Restored `goe report` (`src/goe/cli/commands/report.py`) defaults (`-o/--output-format` default `"text"`, `--output-level` default `"summary"`), added hidden `-d/--demo`, and propagated `"ansi"` into `options_dict`.
    - Updated `goe logmgr` (`src/goe/cli/commands/logmgr.py`) to resolve `LOG_MV_MINS` from the environment when `--min-age-minutes` is omitted on the CLI.
  - **Chapter 3 (`listener_and_persistence_schema_alignment_20261004`, commits `3dacccd8`..`3908785a`)**:
    - Expanded `OffloadOptions` (`src/goe/listener/schemas.py`) with all 84 canonical `EXPECTED_OFFLOAD_ARGS` fields and 12 backward-compatible alias fields, added `OffloadOptions.to_params_dict()`, updated `OrchestrationController.offload` (`src/goe/listener/controllers/orchestration.py`) to pass `data.to_params_dict()`, and added optional `offload_options`, `present_options`, and `prepare_options` to `ListenerConfig`.
    - Updated `SystemController.get_table_partitions` (`src/goe/listener/controllers/system.py`) to normalize `SubPartitionDetail` structs via `p.to_dict()`, added `data_precision: int | None = None` to `ColumnDetail` (`src/goe/persistence/schemas.py`, `src/goe/listener/schemas.py`), added `partition_name` and `partition_position` to `SubPartitionDetail` and `_GET_TABLE_SUBPARTITIONS_SQL` (`src/goe/persistence/oracle/oracle_orchestration_repo_client.py`), and delegated `src/goe/util/serialization.py` to `goe.util.json_tools`.

## 2026-10-02

- **Flow Review, Revision & Completion (`embedded_listener_and_task_execution_20260826`, `python_dotenv_autoload_20260826`, `litestar_listener_overhaul_20260823`, `rich_click_cli_overhaul_20260823`, `msgspec_sqlspec_overhaul_20260823`)**:
  - Removed `valkey[libvalkey]>=6.1.1` from `pyproject.toml` and `uv.lock` while retaining first-party `litestar-queues` (`queue_backend="memory"`, `WorkerConfig(placement="asgi")`), and purged 15 dead legacy FastAPI/Starlette/Gunicorn/worker files under `src/goe/listener/`.
  - Implemented thread-safe embedded TTL caches (`MemoryCache` and `MemorySyncCache` sharing a common in-process store) in `src/goe/listener/utils/cache.py`, refactored `src/goe/util/redis_tools.py` into a `DeprecationWarning` shim, and wired real `periodic_tasks` (`publish_heartbeat`, `publish_schemas`, `publish_command_executions`) into `src/goe/listener/jobs.py`.
  - Implemented `src/goe/listener/security.py` using `litestar-security==0.6.0` (`ConsoleKeySlot`, `ConsoleKeyAuthenticator`, `ConsoleKeyIdentityResolver`, `SecurityScheme(type="apiKey", name="x-goe-console-key", security_scheme_in="header")`) to enforce `x-goe-console-key` against `OFFLOAD_LISTENER_SHARED_TOKEN` (`settings.shared_token`) when configured while allowing local unauthenticated access when unset.
  - Upgraded `SystemController` and `OrchestrationController` to subclass `SecureController`, use Litestar 2.24 native `NamedDependency`, `FromPath`, `FromQuery`, and `JSONBody` annotations (eliminating all `LitestarDeprecationWarning`s), and expose routes to `LitestarMCP` via `mcp_tool=` markers.
  - Wired early `load_env()` execution into `src/goe/cli/main.py`, `src/goe/listener/asgi.py`, `src/goe/listener/app.py`, and `src/goe/listener/config/application.py`; added `configure_cli()` rich-click option group wiring; added all 65 `@click.option` flags across all 10 `OPTION_GROUPS["goe offload"]` panels in `src/goe/cli/commands/offload.py`; forwarded `--upgrade-environment-file` in `goe connect`; fixed `goe validate --execute/--no-execute`; and implemented `goe listener status`.
  - Standardized `"and will be removed in GOE 2.0.0"` `DeprecationWarning` messages across all `bin/*` wrapper scripts, fixed `msgspec.field(default_factory=list)` in `src/goe/persistence/schemas.py`, and moved `from msgspec.json import Encoder` to module top-level in `src/goe/util/json_tools.py`.
- **Flow Setup Alignment & OKF v0.2 Resynthesis**:
  - Decomposed monolithic `.agents/bundles/knowledge/patterns.md` into topic-scoped pattern chapters under `.agents/bundles/knowledge/patterns/` (`index.md`, `serialization-and-utils.md`, `cli-architecture.md`, `offload-and-typing.md`) and updated all inbound links across `AGENTS.md`, `.agents/skills/flow-memory-keeper/SKILL.md`, and bundle indexes.
  - Resynthesized `.agents/bundles/product/product.md`, `.agents/bundles/product/tech-stack.md`, `.agents/bundles/knowledge/listener/` (`index.md`, `rest-api.md`, `worker-and-redis.md`), and `.agents/bundles/knowledge/operations/cli-tools.md` to reflect the Litestar 2.8+ / Granian / Python 3.12+ / `rich-click` `goe` CLI architecture (replacing stale FastAPI, Python 3.8, `orjson`, and `passlib` descriptions).
  - Synced `.agents/bundles/knowledge/workflow.md` with the `flow-template-v2` template (`templates/agent/workflow.md`) while preserving the `<!-- truth -->` block and GOE canonical commands, and wrapped `## Project Nuances` in `.agents/skills/flow-memory-keeper/SKILL.md` with `<!-- project-customization: start/end -->` markers.
  - Backfilled normative Spec and Task frontmatter (`plan_revision`, `state_revision`, Work Kind tags, `verification_strategy` enums, and required section headings) across `.agents/bundles/specs/` (`modernization_overhaul_20260823`, `litestar_listener_overhaul_20260823`, `embedded_listener_and_task_execution_20260826`, `python_dotenv_autoload_20260826`), removed duplicate unpromoted research under `.agents/bundles/research/python_dotenv_autoload_install_lifecycle/`, and swept terminal transaction journals from `.agents/transactions/`.
  - Updated `.agents/setup-state.json` canonical commands (`make install`, `make test-unit`, `make test-integration`, `make format`, `make lint`, `goe connect`) and `project_install` metadata.

## 2026-08-26

- **SPDX Copyright & License Header Migration (Master PRD `spdx_copyright_migration_20260826`)**:
  - Replaced verbose legacy Apache 2.0 headers across 470+ source files (Python, Shell, Makefiles, SQL, HTML/Jinja templates, CSS, JS, and Scala) with standardized, concise 2-line SPDX headers (`# SPDX-FileCopyrightText: <year> The GOE Authors` and `# SPDX-License-Identifier: Apache-2.0`), preserving historical copyright provenance years and leading shebangs.
  - Configured Ruff's `CPY001` (`flake8-copyright`) rule in `pyproject.toml` (`notice-rgx`) to continuously enforce copyright header presence across the entire Python codebase.
  - Implemented automated multi-format migration CLI tool `tools/migrate_spdx_headers.py` and accompanying 16-test suite in `tests/unit/test_migrate_spdx_headers.py` supporting dry-run execution, comment style detection, and CRLF normalization.
  - Updated developer guidelines in `AGENTS.md`, `README.md`, and knowledge bundle standards; broadened CI Ruff checks in `.github/workflows/test.yaml` and `Makefile` to check all repository root Python files.

## 2026-08-24

- **Rich-Click CLI Overhaul (Chapter 3)**:
  - Established a centralized, modern CLI suite powered by `rich-click` under `src/goe/cli/` with a single authoritative entrypoint registered in `pyproject.toml` (`[project.scripts] goe = "goe.cli.main:cli"`).
  - Implemented modular subcommands under `src/goe/cli/commands/`: `goe offload` (with 5 structured option groups), `goe connect` (pre-flight checks), `goe validate` (aggregate comparisons), `goe sync` (schema drift detection), `goe report` (status reporting), `goe logmgr` (cross-platform log retention), and `goe listener` (ASGI server runner with Granian/Uvicorn runtime support).
  - Modernized all legacy entrypoint scripts in `bin/` (`bin/offload`, `bin/connect`, `bin/agg_validate`, `bin/schema_sync`, `bin/logmgr`, `bin/listener`, `bin/offload_status_report`) into lightweight Python delegators that emit `DeprecationWarning` notices and execute `goe <subcommand>` in-process.
  - Authored comprehensive `CliRunner` unit test suite in `tests/unit/cli/` (21 tests); verified 100% green test pass and CI workflow checks across all Python versions.

- **Msgspec & SQLSpec Modernization (Chapter 2)**:
  - Added `sqlspec[performance,mypyc,oracledb,adbc,duckdb]>=0.61.0` and `msgspec>=0.19.0` to core dependencies and completely removed `orjson` across the entire codebase.
  - Rebuilt utility ecosystem under `src/goe/util/` to cleanly re-export `sqlspec.utils`: `serialization.py` (`to_json`, `from_json`, `schema_dump`), `sync_tools.py` (`async_`, `await_`, `ensure_async_`, `Portal`), `text.py` (`camelize`, `pascalize`, `snake_case`, `slugify`), `env.py` (`get_env`, `get_config_val`), and `uuids.py` (`uuid4`, `uuid7`, `nanoid`).
  - Defined typed `msgspec.Struct` persistence schemas in `src/goe/persistence/schemas.py` (`StepDetailSchema`, `CommandExecutionSchema`, `OffloadMetadataSchema`, `LogEventSchema`, `PartitionMetadataSchema`).
  - Refactored `src/goe/persistence/orchestration_repo_client.py`, Oracle/Teradata repo clients, offload messaging, and Listener routes to use `msgspec` and `sqlspec`.
  - Added unit test characterization in `tests/unit/util/test_json_tools.py` and `tests/unit/persistence/test_schemas.py`; verified all 499 unit tests passing green.
- **Build & CI Infrastructure Modernization (Chapter 1)**:
  - Migrated build backend from `setuptools` to `hatchling.build` with explicit wheel package mapping (`packages = ["src/goe"]`).
  - Structured PEP 735 `[dependency-groups]` (`dev`, `test`, `lint`, `docs`, `build`) and preserved multi-cloud connector extras (`hadoop`, `snowflake`, `sql_server`, `synapse`, `teradata`, `sqlspec`, `all`).
  - Automated formatting and linting pass with `ruff` (`line-length = 120`), resolving legacy style discrepancies across 360 files.
  - Modernized top-level `Makefile` with standard developer lifecycle targets (`setup-env`, `install`, `upgrade`, `lint`, `format`, `test-unit`, `test-integration`, `build`, `clean`, `destroy`) and kernel-aware `uv.toml` sourcing.
  - Re-scaffolded GitHub Actions CI/CD workflows (`ci.yaml`, `test.yaml`, `release.yaml`) with `actions/checkout@v4`, `astral-sh/setup-uv@v5`, and standalone PyApp distribution bundling via `tools/bundle_python.py`.
- **Flow Alignment & OKF Validation**: Revalidated bundle structure, verified link integrity across 84 cross-document links, backfilled complete OKF v0.2 frontmatter across all 20 task worksheets, and linked child specs to `modernization_overhaul_20260823`.
- **Research Promotion**: Promoted `modernization_overhaul_20260822` research document to `.agents/bundles/specs/modernization_overhaul_20260823/research/` matching the master PRD roadmap.
- **Harness & Environment Verification**: Confirmed Antigravity plugin and skills environment configuration.

## 2026-08-22

- **Initial Flow Setup**: Initialized OKF v0.2 knowledge bundle for Next-GOE framework.
- **Deep Codebase Ingestion**: Scaffolding complete knowledge hierarchy covering Architecture, Frontends (Oracle, SQL Server, Teradata), Backends (BigQuery, Snowflake, Synapse, Hadoop), Storage (GCS, S3, Azure Blob, HDFS), Transport (Spark, Dataproc, Avro/Parquet staging), Listener REST service, CLI tooling, and Development standards.
- **Operational Skills**: Installed project-local `flow-memory-keeper` consumer skill.

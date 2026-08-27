# Change Log

This file records significant lifecycle operations, structural additions, and major evolutions to the GOE knowledge bundle.

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
  - Rebuilt utility ecosystem under `src/goe/util/` to cleanly re-export `sqlspec.utils` (matching DMA accelerator conventions): `serialization.py` (`to_json`, `from_json`, `schema_dump`), `sync_tools.py` (`async_`, `await_`, `ensure_async_`, `Portal`), `text.py` (`camelize`, `pascalize`, `snake_case`, `slugify`), `env.py` (`get_env`, `get_config_val`), and `uuids.py` (`uuid4`, `uuid7`, `nanoid`).
  - Defined typed `msgspec.Struct` persistence schemas in `src/goe/persistence/schemas.py` (`StepDetailSchema`, `CommandExecutionSchema`, `OffloadMetadataSchema`, `LogEventSchema`, `PartitionMetadataSchema`).
  - Refactored `src/goe/persistence/orchestration_repo_client.py`, Oracle/Teradata repo clients, offload messaging, and Listener routes to use `msgspec` and `sqlspec`.
  - Added unit test characterization in `tests/unit/util/test_json_tools.py` and `tests/unit/persistence/test_schemas.py`; verified all 499 unit tests passing green.
- **Build & CI Infrastructure Modernization (Chapter 1)**:
  - Migrated build backend from `setuptools` to `hatchling.build` with explicit wheel package mapping (`packages = ["src/goe"]`).
  - Structured PEP 735 `[dependency-groups]` (`dev`, `test`, `lint`, `docs`, `build`) and preserved multi-cloud connector extras (`hadoop`, `snowflake`, `sql_server`, `synapse`, `teradata`, `sqlspec`, `all`).
  - Automated formatting and linting pass with `ruff` (`line-length = 120`), resolving legacy style discrepancies across 360 files.
  - Modernized top-level `Makefile` with DMA developer lifecycle standards (`setup-env`, `install`, `upgrade`, `lint`, `format`, `test-unit`, `test-integration`, `build`, `clean`, `destroy`) and kernel-aware `uv.toml` sourcing.
  - Re-scaffolded GitHub Actions CI/CD workflows (`ci.yaml`, `test.yaml`, `release.yaml`) with `actions/checkout@v4`, `astral-sh/setup-uv@v5`, and standalone PyApp distribution bundling via `tools/bundle_python.py`.
- **Flow Alignment & OKF Validation**: Revalidated bundle structure, verified link integrity across 84 cross-document links, backfilled complete OKF v0.2 frontmatter across all 20 task worksheets, and linked child specs to `modernization_overhaul_20260823`.
- **Research Promotion**: Promoted `modernization_overhaul_20260822` research document to `.agents/bundles/specs/modernization_overhaul_20260823/research/` matching the master PRD roadmap.
- **Harness & Environment Verification**: Confirmed Antigravity plugin and skills environment configuration.

## 2026-08-22

- **Initial Flow Setup**: Initialized OKF v0.2 knowledge bundle for Next-GOE framework.
- **Deep Codebase Ingestion**: Scaffolding complete knowledge hierarchy covering Architecture, Frontends (Oracle, SQL Server, Teradata), Backends (BigQuery, Snowflake, Synapse, Hadoop), Storage (GCS, S3, Azure Blob, HDFS), Transport (Spark, Dataproc, Avro/Parquet staging), Listener REST service, CLI tooling, and Development standards.
- **Operational Skills**: Installed project-local `flow-memory-keeper` consumer skill.


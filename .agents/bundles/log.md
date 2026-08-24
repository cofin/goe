# Change Log

This file records significant lifecycle operations, structural additions, and major evolutions to the GOE knowledge bundle.

## 2026-08-24

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


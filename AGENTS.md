# AI Agent Instructions (Flow Framework)

You are an AI coding assistant helping develop the **GOE (Gluent Offload Engine)** framework repository. Always adhere to the following guidelines and consult the OKF knowledge bundle at `.agents/bundles/` when researching, planning, and writing code.

## 1. Project Context & Tech Stack
- **Core Domain**: High-performance data offloading and copying from Oracle Database to modern cloud data warehouses (Google BigQuery, Snowflake, Azure Synapse, Teradata) and Hadoop.
- **Supporting Infrastructure**: Relies on Apache Spark, Cloud Storage (GCS, S3, Azure Blob), and Oracle RDBMS.
- **Knowledge Bundle Root**: `.agents/bundles/` (OKF v0.2)
- **Product Overview**: [Product Definition](.agents/bundles/product/product.md) & [Product Guidelines](.agents/bundles/product/product-guidelines.md)
- **Technology Stack**: [Tech Stack](.agents/bundles/product/tech-stack.md)
- **Workflow & Commands**: [Workflow](.agents/bundles/knowledge/workflow.md)
- **Patterns & Gotchas**: [Patterns](.agents/bundles/knowledge/patterns.md)

## 2. Core Operational Invariants
- **Language**: Python >= 3.12.
- **Environment & Dependency Management**:
  - Development virtual environment is managed with `uv` in `.venv/` (activate via `source .venv/bin/activate`).
  - Initialize and sync dependencies via `make install` (uses `uv sync --all-extras --dev`).
  - Run commands with `uv run` where applicable (`uv run pytest tests/unit`).
  - Build backend is `hatchling.build` and dependencies are managed via PEP 735 `[dependency-groups]` in `pyproject.toml` with lockfile `uv.lock`.
  - Runtime configuration relies on the `OFFLOAD_HOME` environment variable and `offload.env` configuration file (constructed from `templates/conf/offload.env.template`).
- **Code Style & Formatting**:
  - Format all code with `ruff` (`line-length = 120`). Run `make format` (`uv run ruff format` and `uv run ruff check --fix`) and `make lint` (`uv run ruff check` and `uv run mypy src/goe`).
  - Always place all imports at the top of the file, rather than within function scopes.
  - Adhere to PEP 257 docstrings (one-line summary, blank line, and detailed description for multi-line docstrings).
  - Use PEP 585 built-in collection types (`list`, `dict`, etc.) and PEP 604 union syntax (`str | None`).
  - **Copyright & License Headers**: All source files must start with the standard 2-line SPDX header (`# SPDX-FileCopyrightText: <year> The GOE Authors` and `# SPDX-License-Identifier: Apache-2.0`), automatically enforced via Ruff `CPY001`.
  - **Never** use in-line comments in Python functions; place explanations in docstrings.
- **Testing Requirements**:
  - New features and bug fixes must be covered by corresponding unit tests in `tests/unit/`.
  - Prior to running tests, export client certificate suppression:
    ```bash
    export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
    ```
  - **Unit Tests**:
    ```bash
    uv run pytest tests/unit
    # or via Makefile
    make test-unit
    ```
  - **Integration Tests**: Require an active database, credentials, and project config (e.g. `GOE_TEST_USER_PASS`, `GOOGLE_CLOUD_PROJECT`):
    ```bash
    export GOOGLE_API_USE_CLIENT_CERTIFICATE=false GOE_TEST_USER_PASS="<password>"
    uv run pytest tests/integration -n 4
    # or via Makefile
    make test-integration
    ```
- **Concurrency & Locking**: Always acquire table locks via `OrchestrationLockInterface` (`filelock` in `$OFFLOAD_HOME/run/`).
- **Data Integrity**: Use canonical column types (`column_metadata.py`) and snapshot-consistent reads (`FLASHBACK ANY TABLE` / SCN).

## 3. Planning & Design Documentation
- **Flow Specs**: Active flow planning worksheets reside in `.agents/bundles/specs/<flow_id>/`.
- **Internal Design Documents & Walkthroughs**: Place broader architectural proposals, migration plans, and design walkthroughs in `docs/internal/design_docs/` following structured markdown conventions (Executive Summary, Architecture/Analysis, Step-by-Step Plan, Verification, Risks/Mitigation).

## 4. Repository Structure
- `src/goe/`: Core Python framework package (orchestration, offload engine, frontend/backend adapters, filesystem, listener REST service).
- `tests/`: Unit tests (`tests/unit/`) and integration test suites (`tests/integration/`).
- `docs/`: Public documentation and internal design specifications (`docs/internal/design_docs/`).
- `bin/`: CLI utilities (`offload`, `connect`, `listener`, `logmgr`, `agg_validate`).
- `sql/`: Oracle database DDL, packages (`OFFLOAD`, `OFFLOAD_REPO`), and repository tables.
- `templates/conf/`: Environment configuration templates (`offload.env.template`).
- `tools/`: Spark listener (Scala/SBT), transport scripts, and shell helper functions.
- `.agents/bundles/`: Authoritative Flow OKF knowledge bundle (architecture, adapters, storage, operations, standards).
- `.agents/skills/`: Operational consumer skills (`flow-memory-keeper`).

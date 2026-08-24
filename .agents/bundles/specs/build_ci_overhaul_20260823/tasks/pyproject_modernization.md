---
type: Task
id: build_ci_overhaul_20260823:pyproject_modernization
title: Migrate pyproject.toml to Hatchling, PEP 735 Dependency Groups, Ruff, and UV
description: Migrate pyproject.toml to Hatchling build backend, PEP 735 dependency groups, Ruff, and UV lockfile.
state: open
created_at: "2026-08-23T01:15:00Z"
updated_at: "2026-08-23T01:15:00Z"
tags:
  - migration
  - build
  - pyproject
  - hatchling
  - uv
depends_on:
files:
  - pyproject.toml
  - uv.lock
tests:
  - tests/unit
verification_strategy: static_validation
---

# Task: Migrate pyproject.toml to Hatchling, PEP 735 Dependency Groups, Ruff, and UV

## Objective
Update `pyproject.toml` to replace legacy `setuptools` build backend with `hatchling.build`, structure dependencies using PEP 621 and PEP 735 `[dependency-groups]`, preserve multi-cloud backend connector extras under `[project.optional-dependencies]`, configure `[tool.ruff]`, `[tool.mypy]`, `[tool.pyright]`, `[tool.bumpversion]`, and `[tool.pytest.ini_options]`, and generate a deterministic `uv.lock`.

## Implementation Details

1. **Build System & Metadata**:
   - Change `[build-system]` to `requires = ["hatchling"]` and `build-backend = "hatchling.build"`.
   - Add `[tool.hatch.build.targets.wheel]` with `packages = ["src/goe"]` or `[tool.hatch.build]` with `dev-mode-dirs = ["src/"]` and `sources = ["src"]`.
   - Update `[project]` with `requires-python = ">=3.10"`.

2. **Dependency Groups (PEP 735)**:
   - Configure `[tool.uv]` with `managed = true` and `package = true`.
   - Define `[dependency-groups]`:
     - `dev = ["bump-my-version", { include-group = "lint" }, { include-group = "test" }, { include-group = "docs" }, { include-group = "build" }]`
     - `test = ["pytest>=9.0", "pytest-cov>=5.0", "pytest-xdist>=3.6", "filelock>=3.0"]`
     - `lint = ["mypy>=1.13.0", "ruff>=0.14.0", "types-pyyaml", "types-requests", "pre-commit"]`
     - `docs = ["sphinx>=8.0.0", "myst-parser>=4.0.0", "sphinxawesome-theme>=6.0.2", "sphinx-copybutton>=0.5.2", "sphinx-design>=0.6.1"]`
     - `build = ["bump-my-version", "build>=1.2.0"]`

3. **Backend Optional Dependencies (PEP 621)**:
   - Preserve existing connector extras under `[project.optional-dependencies]`:
     - `hadoop = ["hdfs", "impyla", "requests-kerberos", "thrift-sasl"]`
     - `snowflake = ["snowflake-connector-python"]`
     - `sql_server = ["pymssql"]`
     - `synapse = ["pyodbc"]`
     - `teradata = ["pyodbc"]`
     - `sqlspec = ["sqlspec[duckdb,performance,asyncpg,mypyc,fsspec,uuid,adbc,oracledb,adk]>=0.61.0"]`
     - `all = [{ include-optional = "hadoop" }, { include-optional = "snowflake" }, { include-optional = "sql_server" }, { include-optional = "synapse" }, { include-optional = "teradata" }, { include-optional = "sqlspec" }]`

4. **Tool Configurations**:
   - `[tool.ruff]`: `line-length = 120`, `target-version = "py310"`, Google docstring convention, `lint.select = ["ALL"]` with tailored ignores matching DMA.
   - `[tool.mypy]` and `[tool.pyright]`.
   - `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, filters, and markers (`unit`, `integration`).

5. **Lockfile Generation**:
   - Execute `uv lock` and `uv sync --all-extras --dev` to create `uv.lock`.

## Verification
- **Strategy**: `static_validation`
- **Initial Evidence**: `pyproject.toml` contains legacy `setuptools` build backend.
- **Final Evidence**: `uv lock` succeeds; `uv sync --all-extras --dev` succeeds without dependency conflict; `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit` executes all unit tests green; `uv run ruff --version` executes successfully.

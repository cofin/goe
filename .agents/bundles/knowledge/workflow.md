---
type: Guide
title: Project Workflow
description: Canonical development, testing, packaging, and validation workflows for GOE
tags:
  - guide
  - workflow
  - commands
  - development
---

# Project Workflow

<!-- truth: start -->
- Virtual environment setup: `make install` (or `make setup-env` to configure kernel index).
- Development packages & lockfile: Managed via `uv` with `pyproject.toml` (`[dependency-groups]`) and `uv.lock`.
- Unit testing: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit` (or `make test-unit`).
- Integration testing: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false GOE_TEST_USER_PASS=... && uv run pytest tests/integration -n 4` (or `make test-integration`).
- Code formatting & linting: `make format` (`uv run ruff format` and `uv run ruff check --fix`) and `make lint` (`uv run ruff check` and `uv run mypy src/goe`).
- Packaging & release build: `make build` (produces wheel and sdist in `dist/`) and `make package` (produces `goe_<version>.tar.gz`).
- Pre-flight environment check: `bin/connect` (checks configuration, frontend DB, backend DW, and transport connectivity).
- Offload CLI: `bin/offload -t <owner.table> -x` (executes offload with execution lock and audit trail).
<!-- truth: end -->

## Canonical Commands

### 1. Development Environment Setup
```bash
# Display self-documenting make target menu
make help

# Configure environment and generate kernel-appropriate uv.toml
make setup-env

# Install GOE in editable mode with all development dependency groups
make install

# Upgrade all dependencies in uv.lock
make upgrade
```

### 2. Testing Workflows
```bash
# Ensure client certificate check is disabled for Google client libraries
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false

# Run unit test suite via Makefile
make test-unit

# Run focused unit tests directly with uv
uv run pytest tests/unit

# Run focused unit test file or expression
uv run pytest tests/unit/offload/test_column_metadata.py -k "test_canonical_types"

# Run parallel integration tests against active database
export GOE_TEST_USER_PASS="<db_password>"
export GOOGLE_CLOUD_PROJECT="<gcp_project_id>"
uv run pytest tests/integration -n 4
```

### 3. Formatting & Code Quality
```bash
# Run Ruff formatter and auto-fix lint issues
make format

# Run Ruff linter and Mypy static typecheck
make lint
```

### 4. Building & Packaging
```bash
# Build the target runtime tree, inject versions into SQL scripts, and compile conf templates
make target

# Package everything into distributable tar.gz archive
make package
```

### 5. Runtime Operations & Validation
```bash
# Validate connectivity, permissions, and configuration pre-flight
bin/connect

# Auto-upgrade offload.env with missing template variables
bin/connect --upgrade-environment-file

# Run a test offload in execute mode (-x)
bin/offload -t SH.SALES -x

# Validate data consistency and aggregations between source Oracle and target BigQuery
bin/agg_validate -t SH.SALES --verify-row-count aggregate
```

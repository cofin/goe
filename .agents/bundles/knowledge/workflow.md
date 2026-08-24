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
- Virtual environment setup: `make install-dev` (core + dev dependencies) or `make install-dev-extras` (includes Hadoop, Snowflake, SQL Server, Teradata).
- Unit testing: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit` (or `.venv/bin/pytest tests/unit`).
- Integration testing: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false GOE_TEST_USER_PASS=... && pytest tests/integration -n 4`.
- Code formatting & linting: `black src tests`.
- Packaging & release build: `make clean && make package` (produces `goe_<version>.tar.gz` and wheel under `dist/`).
- Pre-flight environment check: `bin/connect` (checks configuration, frontend DB, backend DW, and transport connectivity).
- Offload CLI: `bin/offload -t <owner.table> -x` (executes offload with execution lock and audit trail).
<!-- truth: end -->

## Canonical Commands

### 1. Development Environment Setup
```bash
# Clean previous build artifacts and virtual environment
make clean

# Create .venv and install GOE in editable mode with development dependencies
make install-dev

# Install optional backend dependencies (Snowflake, MSSQL, Teradata, Hadoop)
make install-dev-extras
```

### 2. Testing Workflows
```bash
# Ensure client certificate check is disabled for Google client libraries
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false

# Run focused unit tests
pytest tests/unit

# Run focused unit test file or expression
pytest tests/unit/test_column_metadata.py -k "test_canonical_types"

# Run parallel integration tests against active database
export GOE_TEST_USER_PASS="<db_password>"
export GOOGLE_CLOUD_PROJECT="<gcp_project_id>"
pytest tests/integration -n 4
```

### 3. Formatting & Code Quality
```bash
# Format Python source files using black
black src tests

# Verify formatting without modifying files
black --check src tests
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

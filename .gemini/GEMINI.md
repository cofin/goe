# Gemini Agent Configuration for GOE

This file provides guidance to the Gemini agent when working with the GOE (Gluent Offload Engine) repository.

## Project Overview

GOE (Gluent Offload Engine) is a data offloading framework that copies data from RDBMS frontends (Oracle, SQL Server, Teradata) to cloud backends (BigQuery, Snowflake, Synapse). It uses Spark for large-scale data transport and supports multiple offload strategies including incremental, partition-based, and query-based offloads.

## Development Workflow

The project uses a checkpoint-based workflow enforced by the Gemini agent system. The primary commands are:

- `/prd "<feature description>"`: Starts the planning phase for a new feature, creating a Product Requirements Document.
- `/implement <slug>`: Implements the feature based on the approved PRD.
- `/test <slug>`: (Usually auto-invoked) Runs the testing phase, ensuring 90%+ coverage.
- `/review <slug>`: (Usually auto-invoked) Runs the final quality gates and archives the work.

Refer to the `.gemini/commands/*.toml` files for the detailed, mandatory checkpoints for each phase.

### Initial Setup

```bash
# Create development environment
make install-dev
source ./.venv/bin/activate
export PYTHONPATH=${PWD}/src
```

### Running Tests

```bash
# Unit tests (no external dependencies required)
pytest tests/unit

# Run tests in parallel
pytest tests/unit -n auto

# Run tests with coverage
pytest --cov=src/goe --cov-report=term-missing
```

### Linting

```bash
# Check formatting and linting
black --check .
nox -s lint
```

## Architecture

GOE uses a multi-tier plugin architecture. See `specs/guides/architecture.md` for a detailed breakdown of the layers (Frontend, Backend, Transport, Factory, etc.).

## Code Style

- **Formatting**: `black` is used for code formatting.
- **Type Hinting**: Use modern type hints (`T | None` instead of `Optional[T]`).
- **Docstrings**: Follow Google-style docstrings.

See `specs/guides/code-style.md` for more details.

## Testing

- **Framework**: `pytest`
- **Style**: Function-based tests are required. Class-based tests are considered a critical anti-pattern.
- **Coverage**: 90%+ coverage is required for all new or modified modules.

See `specs/guides/testing.md` for detailed examples and patterns.

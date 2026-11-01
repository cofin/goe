---
type: concept
title: Offload Home Runtime & Packaging
description: OFFLOAD_HOME directory layout, build targets, Makefile automation, and virtualenv management.
status: stable
tags:
  - reference
  - operations
  - packaging
  - makefile
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: settings
    resource: src/goe/config/settings.py::find_environment_file
    title: OFFLOAD_HOME and Environment File Discovery
  - id: locking
    resource: src/goe/platform/locking.py::orchestration_lock_for_table
    title: Run Directory Table Lock
---

# Offload Home Runtime & Packaging

<!-- truth: start -->
- `$OFFLOAD_HOME` roots runtime configuration (`conf/offload.env`), execution logs (`log/`), and table lock files (`run/orchestration_<owner>_<table>.lock`).[^settings][^locking]
- Packaged Oracle DDL (`src/goe/persistence/oracle/ddl/`) and HTML report templates (`src/goe/report/templates/`) ship inside the `goe` Python wheel.
<!-- truth: end -->

GOE separates development source trees from the operational runtime environment identified by `$OFFLOAD_HOME`.

## `$OFFLOAD_HOME` Directory Layout

```
$OFFLOAD_HOME/
├── .venv/               # Isolated Python virtual environment
├── conf/                # Configuration (offload.env)
├── lib/                 # Packaged Python wheel (goe_framework-*.whl)
├── log/                 # Active execution log directory
│   └── archive/         # Rotated logs (YYYY.MM.DD/)
├── run/                 # Runtime PID and table lock files
├── cache/               # Local cache storage
├── setup/               # Database SQL scripts (install_offload.sql, etc.)
├── tools/               # Shell helper scripts (goe-shell-functions.sh)
└── version_build        # Version identifier and short commit hash
```

## Build & Packaging Automation (`Makefile`)

- **`make install-dev`**: Recreates local `.venv/` and installs package in editable mode with development dependencies (`pip install -e .[dev]`).
- **`make install-dev-extras`**: Installs optional connectors for Snowflake, MSSQL, and Hadoop.
- **`make target`**:
  - Builds Python wheel into `dist/` (which packages `src/goe/report/templates/` and `src/goe/persistence/oracle/ddl/`).
  - Assembles runtime directory structure under `target/offload/`.
  - Copies Oracle setup scripts from `src/goe/persistence/oracle/ddl/` into `setup/`.
  - Injects semantic version and git commit hash into `setup/` scripts and package specs.
  - Sets strict directory permissions (`775` on `run/` and `log/`, `640` on `conf/*`).
- **`make package`**: Compiles `target/offload/` into deployment tarball `goe_<version>.tar.gz`.
- **`make install`**: Unpacks `goe_<version>.tar.gz` into `$OFFLOAD_HOME`, creates virtual environment in `$OFFLOAD_HOME/.venv`, and installs the wheel.

[^settings]: `src/goe/config/settings.py::find_environment_file` — OFFLOAD_HOME and Environment File Discovery.
[^locking]: `src/goe/platform/locking.py::orchestration_lock_for_table` — Run Directory Table Lock.

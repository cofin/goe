---
type: Reference
title: Offload Home Runtime & Packaging
description: OFFLOAD_HOME directory layout, build targets, Makefile automation, and virtualenv management
tags:
  - reference
  - operations
  - packaging
  - makefile
  - deployment
---

# Offload Home Runtime & Packaging

GOE separates development source trees from the operational runtime environment identified by `$OFFLOAD_HOME`.

## `$OFFLOAD_HOME` Directory Layout

```
$OFFLOAD_HOME/
├── .venv/               # Isolated Python virtual environment
├── bin/                 # Executable CLI tools (offload, connect, listener, etc.)
├── conf/                # Configuration (offload.env, templates)
├── lib/                 # Packaged Python wheel (goe_framework-*.whl)
├── log/                 # Active execution log directory
│   └── archive/         # Rotated logs (YYYY.MM.DD/)
├── run/                 # Runtime PID and table lock files
├── cache/               # Local cache storage
├── setup/               # Database SQL scripts (install_offload.sql, etc.)
├── templates/           # HTML templates & status report assets
├── tools/               # Shell helper scripts (goe-shell-functions.sh)
└── version_build        # Version identifier and short commit hash
```

## Build & Packaging Automation (`Makefile`)

- **`make install-dev`**: Recreates local `.venv/` and installs package in editable mode with development dependencies (`pip install -e .[dev]`).
- **`make install-dev-extras`**: Installs optional connectors for Snowflake, MSSQL, Teradata, and Hadoop.
- **`make target`**:
  - Builds Python wheel into `dist/`.
  - Assembles runtime directory structure under `target/offload/`.
  - Generates configuration templates via `templates/conf/Makefile`.
  - Injects semantic version and git commit hash into `setup/sql/` scripts and package specs.
  - Sets strict directory permissions (`775` on `run/` and `log/`, `640` on `conf/*`).
- **`make package`**: Compiles `target/offload/` into deployment tarball `goe_<version>.tar.gz`.
- **`make install`**: Unpacks `goe_<version>.tar.gz` into `$OFFLOAD_HOME`, creates virtual environment in `$OFFLOAD_HOME/.venv`, and installs the wheel.

---
type: concept
title: Shell & Tooling Standards
description: Bash scripting best practices, error handling, command logging, and Makefile conventions.
status: stable
tags:
  - guide
  - standards
  - shell
  - bash
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: bootstrap-ci
    resource: tools/scripts/bootstrap_oracle_ci.sh
    title: Oracle Free CI Bootstrap Script
  - id: subproc
    resource: src/goe/util/subprocess_utils.py::run_os_cmd
    title: Subprocess Execution Helper
---

# Shell & Tooling Standards

<!-- truth: start -->
- Shell scripts (`tools/scripts/bootstrap_oracle_ci.sh`) require `set -euo pipefail`, 2-line SPDX headers, and quoted variable expansions.[^bootstrap-ci]
- Python subprocess invocations route through `run_os_cmd` (`src/goe/util/subprocess_utils.py`) with argument lists (`shell=False`) and credential redaction.[^subproc]
<!-- truth: end -->

## Bash Scripting Guidelines

- **Interpreter**: Always declare `#!/bin/bash` with explicit error handling options:
  ```bash
  set -euo pipefail
  ```
- **Portability**: Avoid Bash-specific syntax when standard POSIX utilities suffice, but ensure compatibility across RedHat / CentOS / Rocky Linux, Debian / Ubuntu, and SUSE Enterprise Linux.
- **Environment Checks**: Scripts must verify mandatory environment variables (such as `$OFFLOAD_HOME`) and provide actionable error messages if missing.

## Build Automation (`Makefile`)

- Every `Makefile` target that does not produce a physical file matching its name must be declared `.PHONY`.
- Clean targets (`make clean`, `make python-goe-clean`) must remove all build directories (`dist/`, `build/`, `.pytest_cache/`, `*.egg-info`) without throwing errors if they do not exist.

[^bootstrap-ci]: `tools/scripts/bootstrap_oracle_ci.sh` — Oracle Free CI Bootstrap Script.
[^subproc]: `src/goe/util/subprocess_utils.py::run_os_cmd` — Subprocess Execution Helper.

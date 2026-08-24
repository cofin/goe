---
type: Guide
title: Shell & Tooling Standards
description: Bash scripting best practices, error handling, command logging, and Makefile conventions
tags:
  - guide
  - standards
  - shell
  - bash
  - tooling
---

# Shell & Tooling Standards

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

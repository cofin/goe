---
type: Task
id: embedded_listener_and_task_execution_20260826:deprecation_shims
title: Add Deprecation Shims for Legacy Redis Modules, bin/ Scripts, and Complete CLI Options
description: Add runtime DeprecationWarning shims to goe.util.redis_tools, goe.listener.utils.cache (RedisClient alias), and legacy bin/ scripts, and complete CLI option parity across offload, connect, validate, and listener.
state: closed
priority: P2
plan_revision: 2
plan_commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
state_revision: 5
claimed_by: null
claimed_at: null
blocked_reason: null
unblock_condition: null
next_step: null
last_operation: 20261002T211500Z-flow-finish-00
operation_targets: []
last_verified_at: "2026-10-02T21:15:00Z"
last_verified_commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
verification_evidence: "uv run pytest tests/unit/listener/test_deprecation_shims.py tests/unit/cli/"
commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
created_at: "2026-08-26T21:20:00Z"
updated_at: "2026-10-02T21:15:00Z"
tags:
  - refactor
  - deprecations
  - shims
  - compatibility
  - cli
depends_on:
  - embedded_listener_and_task_execution_20260826:native_task_execution
files:
  - src/goe/util/redis_tools.py
  - src/goe/listener/utils/cache.py
  - src/goe/cli/commands/offload.py
  - src/goe/cli/commands/connect.py
  - src/goe/cli/commands/validate.py
  - src/goe/cli/commands/listener.py
  - src/goe/util/json_tools.py
  - src/goe/persistence/schemas.py
  - bin/offload
  - bin/listener
  - bin/connect
  - bin/logmgr
  - bin/agg_validate
  - bin/offload_status_report
  - bin/schema_sync
tests:
  - tests/unit/listener/test_deprecation_shims.py
  - tests/unit/cli/test_offload_command.py
  - tests/unit/cli/test_connect_command.py
  - tests/unit/cli/test_validate_command.py
  - tests/unit/cli/test_listener_command.py
verification_strategy: behavior_tdd
---

# Task: Add Deprecation Shims for Legacy Redis Modules, bin/ Scripts, and Complete CLI Options

## Objective
1. Replace `valkey` in `src/goe/util/redis_tools.py` with an in-memory synchronous TTL cache facade (`RedisClient` / `cache`) and emit a runtime `DeprecationWarning` on import.
2. Support `RedisClient` in `src/goe/listener/utils/cache.py` via module `__getattr__` emitting a `DeprecationWarning`.
3. Standardize deprecation warnings across all `bin/` wrapper scripts (`bin/offload`, `bin/listener`, `bin/connect`, `bin/logmgr`, `bin/agg_validate`, `bin/offload_status_report`, `bin/schema_sync`).
4. Complete CLI subcommands:
   - `src/goe/cli/commands/offload.py`: Add all options declared in `src/goe/cli/config.py`'s `OPTION_GROUPS["goe offload"]` mapped to their `optparse` attribute destinations.
   - `src/goe/cli/commands/connect.py`: Forward `--upgrade-environment-file` and global verbosity/quiet/ansi flags to `run_connect()`.
   - `src/goe/cli/commands/validate.py`: Support `--execute` / `--no-execute` (or default `execute=False` matching `agg_validate.py` / `offload.py`) so dry-run preview is accessible.
   - `src/goe/cli/commands/listener.py`: Use `settings.host`, `settings.port`, `settings.http_workers` defaults, implement `goe listener status` via `ping()`, and support `--worker-only`.
5. Fix `src/goe/util/json_tools.py` top-level `Encoder` import and `src/goe/persistence/schemas.py` `msgspec.field(default_factory=list)`.

## Steps
- [x] Replace `valkey` in `src/goe/util/redis_tools.py` with in-memory synchronous cache and `DeprecationWarning`.
- [x] Add `RedisClient` deprecated alias in `src/goe/listener/utils/cache.py`.
- [x] Standardize deprecation warnings across all `bin/` wrapper scripts.
- [x] Complete `src/goe/cli/commands/offload.py`, `connect.py`, `validate.py`, and `listener.py`.
- [x] Clean up `src/goe/util/json_tools.py` and `src/goe/persistence/schemas.py`.
- [x] Create `tests/unit/listener/test_deprecation_shims.py` and update CLI unit tests.

## Verification
```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_deprecation_shims.py tests/unit/cli/
```

## Acceptance Criteria
- [x] All deprecation warnings are properly triggered and captured in test assertions.
- [x] Every option in `OPTION_GROUPS["goe offload"]` is accepted by `goe offload` and forwarded to `offload_by_cli`.
- [x] `goe connect --upgrade-environment-file` forwards its flag to `run_connect`.
- [x] `goe listener status` pings the listener endpoint and reports status.

## Notes & Discoveries
- Added all 65 Click options across all 10 option groups in `src/goe/cli/commands/offload.py` and verified 100% parity with `OPTION_GROUPS["goe offload"]` in `tests/unit/cli/test_offload_command.py`.

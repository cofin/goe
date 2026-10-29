---
name: goe-offload-operations
description: Operational runbook for planning, previewing, confirming, executing, and validating GOE table offloads.
---

# GOE Offload Operations Runbook

## Pre-Flight Checks

1. Verify RDBMS and backend connectivity via `goe://system/connectivity` (`check_connectivity`) and inspect runtime configuration via `goe://system/config` (`get_listener_config`).
2. Inspect candidate schemas via `goe://schemas` (`get_offloadable_schemas`) and schema tables via `goe://schemas/{schema_name}/tables` (`get_offloadable_tables`).
3. Review table columns (`goe://schemas/{schema_name}/{table_name}/columns`), partitions (`goe://schemas/{schema_name}/{table_name}/partitions`), current offload status (`goe://schemas/{schema_name}/{table_name}/status`), and repository metadata (`goe://schemas/{schema_name}/{table_name}/metadata`).

## Dry-Run Preview & Confirmation Gate

1. Always invoke `preview_offload_plan` (`POST /api/orchestration/offload/preview/`) with `execute=false` before running an offload.
2. Verify the returned `OffloadPlanPreview`:
   - `resolved_boundary` (`partition_columns`, `high_value_literal`, `common_predicate`)
   - `target_backend` and `target_table`
   - `confirmation_challenge` containing a time-bounded HMAC-SHA256 `confirmation_token` bound to `execute_offload`, `owner_table`, and normalized options.
3. Invoke `execute_offload` (`POST /api/orchestration/offload/`) with `execute=true` and either:
   - Pass `confirmation_token` from `preview_offload_plan.confirmation_challenge.confirmation_token`, or
   - Respond to the Mid-Request Tool Confirmation (`input_required`) challenge with `confirm=true`.

## Job Monitoring & Post-Offload Validation

1. Poll `goe://jobs/{execution_id}` (`get_offload_job`) and `goe://executions/{execution_id}` (`get_command_execution`).
2. Inspect execution logs via `get_execution_log_link` and `goe://executions/{execution_id}/log`.
3. Run `validate_table` (`POST /api/orchestration/validate/`) using `"count"` or `"aggregate"` validation (with optional `scn` for Oracle Flashback consistency) to verify data integrity.

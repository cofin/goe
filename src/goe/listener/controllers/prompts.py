# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Guided DBA workflow prompts controller for GOE Listener MCP."""

from __future__ import annotations

from litestar.params import FromQuery
from litestar_mcp import PromptController, prompt
from litestar_security.authentication import AUTH_POLICY_OPT_KEY, required

__all__ = ("GOEPromptController",)


class GOEPromptController(PromptController):
    """Guided DBA workflow prompts served over the Model Context Protocol."""

    path = "/api/prompts"
    tags = ["MCP Prompts"]
    include_in_schema = False
    opt = {AUTH_POLICY_OPT_KEY: required("console-key")}
    instructions = (
        "Follow Gluent Offload Engine (GOE) operational safety protocols: "
        "always verify connectivity and preview mutations before executing changes."
    )

    @prompt(
        name="plan_table_offload",
        title="Plan Table Offload",
        description="Guided DBA runbook for planning, previewing, executing, and validating a table offload.",
    )
    async def plan_table_offload(
        self,
        schema_name: FromQuery[str],
        table_name: FromQuery[str],
        offload_goal: FromQuery[str] = "incremental",
    ) -> str:
        """Render a step-by-step DBA runbook to plan and execute a table offload."""
        owner = schema_name.strip().upper()
        table = table_name.strip().upper()
        goal = offload_goal.strip().lower() or "incremental"
        return (
            f"# GOE Table Offload Workflow: {owner}.{table} ({goal})\n\n"
            "1. **Verify Connectivity & Runtime Configuration**:\n"
            "   - Read `goe://system/connectivity` (or call `check_connectivity`) and `goe://system/config` "
            "(or call `get_listener_config`) to confirm frontend/backend connectivity.\n"
            "2. **Inspect Table Partitioning, Status & Metadata**:\n"
            f"   - Read `goe://schemas/{owner}/{table}/partitions`, `goe://schemas/{owner}/{table}/status`, "
            f"and `goe://schemas/{owner}/{table}/metadata`.\n"
            "3. **Preview Dry-Run Offload Plan**:\n"
            f"   - Call `preview_offload_plan` with `owner_table='{owner}.{table}'` (`execute=false`) to inspect "
            "resolved partition boundaries, target backend location, and the signed `confirmation_challenge`.\n"
            "4. **Execute Offload with Confirmation**:\n"
            f"   - Call `execute_offload` with `owner_table='{owner}.{table}'`, `execute=true`, and the "
            "`confirmation_token` issued by `preview_offload_plan` (or respond to the interactive MRTR challenge).\n"
            "5. **Monitor & Validate**:\n"
            "   - Poll `goe://jobs/{execution_id}` and `goe://executions/{execution_id}` until completion, "
            f"then call `validate_table` for `{owner}.{table}` to verify row counts and aggregates."
        )

    @prompt(
        name="diagnose_failed_execution",
        title="Diagnose Failed Execution",
        description="Guided DBA triage workflow for failed, stalled, or lock-contended offload jobs.",
    )
    async def diagnose_failed_execution(self, execution_id: FromQuery[str]) -> str:
        """Render a diagnostic workflow for an offload job or command execution."""
        exec_id = execution_id.strip()
        return (
            f"# GOE Execution Triage: {exec_id}\n\n"
            "1. **Inspect Job & Execution Metadata**:\n"
            f"   - Read `goe://jobs/{exec_id}` (or call `get_offload_job`) and `goe://executions/{exec_id}` "
            "(or call `get_command_execution`) to review status, steps, error messages, and lock state.\n"
            "2. **Retrieve Execution Log**:\n"
            f"   - Call `get_execution_log_link` for `{exec_id}` and read `goe://executions/{exec_id}/log` "
            "(or call `get_command_execution_log`) to inspect stack traces and RDBMS/backend errors.\n"
            "3. **Resolve Lock Contention or Stalled Execution**:\n"
            f"   - If the job is stuck in `QUEUED` or `RUNNING` or holding a table lock (`409`), call "
            f"`cancel_offload_job` with `execution_id='{exec_id}'` to request cooperative cancellation and "
            "release the table lock before retrying."
        )

    @prompt(
        name="reconcile_schema_drift",
        title="Reconcile Schema Drift",
        description="Guided DBA workflow for inspecting frontend/backend schema drift and applying synchronization.",
    )
    async def reconcile_schema_drift(self, schema_name: FromQuery[str], table_name: FromQuery[str]) -> str:
        """Render a workflow for inspecting and reconciling frontend-to-backend schema drift."""
        owner = schema_name.strip().upper()
        table = table_name.strip().upper()
        return (
            f"# GOE Schema Drift Reconciliation: {owner}.{table}\n\n"
            "1. **Inspect Live Drift & Generated DDL**:\n"
            f"   - Read `goe://schemas/{owner}/{table}/drift` or call `preview_schema_drift` for `{owner}.{table}` "
            "to inspect added columns, missing columns, type mismatches, `ddl_statements`, and the signed "
            "`confirmation_challenge`.\n"
            "2. **Evaluate Compatibility**:\n"
            "   - Verify whether drift is additive (`add_columns`) or contains incompatible type mismatches that "
            "require manual review before synchronization.\n"
            "3. **Apply Schema Synchronization**:\n"
            f"   - Call `apply_schema_sync` for `{owner}.{table}` with `execute=true` and the preview's "
            "`confirmation_token` (or confirm via MRTR).\n"
            "4. **Verify Post-Sync State**:\n"
            f"   - Re-run `preview_schema_drift` and `validate_table` on `{owner}.{table}` to confirm zero drift."
        )

    @prompt(
        name="audit_schema_readiness",
        title="Audit Schema Readiness",
        description="Guided DBA workflow for auditing schema tables, partition layouts, and offload coverage.",
    )
    async def audit_schema_readiness(self, schema_name: FromQuery[str]) -> str:
        """Render a schema-wide readiness and coverage audit workflow."""
        owner = schema_name.strip().upper()
        return (
            f"# GOE Schema Readiness Audit: {owner}\n\n"
            "1. **Verify Schema Discovery**:\n"
            "   - Read `goe://schemas` (or call `get_offloadable_schemas`) and "
            f"`goe://schemas/{owner}/tables` (or call `get_offloadable_tables`) to enumerate candidate tables.\n"
            "2. **Generate Schema Status Report**:\n"
            f"   - Read `goe://reports/status/{owner}` (or call `generate_status_report` with "
            f"`schema_filter='{owner}'`) to evaluate offloaded vs non-offloaded bytes and row counts.\n"
            "3. **Inspect High-Volume Partitioned Tables**:\n"
            f"   - For each partitioned table in `{owner}`, inspect `goe://schemas/{owner}/{{table_name}}/partitions` "
            "and call `preview_offload_plan` to validate boundary predicates prior to scheduling offloads."
        )

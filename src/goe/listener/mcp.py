# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Model Context Protocol (MCP) configuration, confirmation gate, and diagnostic tools for GOE Listener."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable
from typing import Any

from litestar.params import FromQuery
from litestar_mcp import LitestarMCP, MCPConfig, Tool

from goe.connect.models import ConnectivityReport
from goe.exceptions import GOEError
from goe.listener.config import settings
from goe.listener.jobs.models import JobRecord, normalize_table_key
from goe.listener.jobs.store import JobStoreProtocol, create_job_store
from goe.listener.schemas import TableDetail, TableDetails
from goe.listener.services.system import SystemService, get_system_service
from goe.listener.telemetry import after_mcp_tool_call, before_mcp_tool_call
from goe.report.models import TableStatusReport
from goe.serializers import encode_json_bytes
from goe.typing import FrozenBaseStruct

__all__ = (
    "ConfirmationChallenge",
    "ConfirmationGate",
    "ConfirmationRequiredError",
    "JobStatusSummary",
    "OffloadPlanPreview",
    "build_mcp_config",
    "build_mcp_plugin",
    "get_connectivity_report",
    "get_job_status",
    "get_table_status_report",
    "list_offloaded_tables",
    "preview_offload_plan",
)

MUTATING_MCP_TOOLS = frozenset({"execute_offload"})


class ConfirmationChallenge(FrozenBaseStruct, frozen=True):
    """Confirmation token challenge returned when a mutating MCP tool is called without confirmation."""

    confirmation_required: bool
    tool_name: str
    owner_table: str
    confirmation_token: str
    expires_at_epoch: int


class ConfirmationRequiredError(GOEError, PermissionError):
    """Raised when a mutating MCP tool is invoked without a valid confirmation token."""

    def __init__(self, challenge: ConfirmationChallenge) -> None:
        self.challenge = challenge
        super().__init__(f"Confirmation token required for {challenge.tool_name} on {challenge.owner_table}")


class JobStatusSummary(FrozenBaseStruct, frozen=True):
    """Structured durable job status response returned by get_job_status."""

    execution_id: str
    found: bool
    status: str
    table_key: str | None = None
    attempt: int = 0
    max_attempts: int = 3
    error_message: str | None = None
    job: JobRecord | None = None


class OffloadPlanPreview(FrozenBaseStruct, frozen=True):
    """Dry-run offload plan preview returned by preview_offload_plan."""

    owner_table: str
    execute: bool
    dry_run: bool
    planned_options: dict[str, Any]


class ConfirmationGate:
    """HMAC-SHA256 confirmation token generator and verifier for mutating MCP tools."""

    def __init__(self, secret: str | None = None, ttl_seconds: int = 300) -> None:
        resolved_secret = secret or settings.shared_token or "goe-local-mcp-confirmation-key"
        self._secret_bytes = resolved_secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def issue_token(
        self,
        *,
        tool_name: str,
        owner_table: str,
        payload: dict[str, Any],
        now_epoch: int | None = None,
    ) -> ConfirmationChallenge:
        """Issue a time-bounded HMAC token bound to tool_name, owner_table, and payload."""
        issued_at = int(time.time()) if now_epoch is None else now_epoch
        expires_at = issued_at + self._ttl_seconds
        signature = self._sign(tool_name=tool_name, owner_table=owner_table, payload=payload, expires_at=expires_at)
        token = f"{expires_at}.{signature}"
        return ConfirmationChallenge(
            confirmation_required=True,
            tool_name=tool_name,
            owner_table=owner_table.strip().upper(),
            confirmation_token=token,
            expires_at_epoch=expires_at,
        )

    def verify_token(
        self,
        *,
        token: str,
        tool_name: str,
        owner_table: str,
        payload: dict[str, Any],
        now_epoch: int | None = None,
    ) -> bool:
        """Verify that token is authentic and unexpired for the given tool call."""
        if "." not in token:
            return False
        raw_expiry, provided_sig = token.split(".", 1)
        try:
            expires_at = int(raw_expiry)
        except ValueError:
            return False
        current_time = int(time.time()) if now_epoch is None else now_epoch
        if current_time >= expires_at:
            return False
        expected_sig = self._sign(
            tool_name=tool_name,
            owner_table=owner_table,
            payload=payload,
            expires_at=expires_at,
        )
        return hmac.compare_digest(provided_sig, expected_sig)

    def enforce(
        self,
        *,
        tool_name: str,
        owner_table: str,
        payload: dict[str, Any],
        token: str | None = None,
        now_epoch: int | None = None,
    ) -> None:
        """Verify token for mutating tool calls or raise ConfirmationRequiredError with a fresh challenge."""
        candidate = token or str(payload.get("confirmation_token") or "")
        if candidate and self.verify_token(
            token=candidate,
            tool_name=tool_name,
            owner_table=owner_table,
            payload=payload,
            now_epoch=now_epoch,
        ):
            return
        challenge = self.issue_token(
            tool_name=tool_name,
            owner_table=owner_table,
            payload=payload,
            now_epoch=now_epoch,
        )
        raise ConfirmationRequiredError(challenge)

    def _sign(
        self,
        *,
        tool_name: str,
        owner_table: str,
        payload: dict[str, Any],
        expires_at: int,
    ) -> str:
        filtered = {k: v for k, v in sorted(payload.items()) if k != "confirmation_token"}
        digest = hashlib.sha256(encode_json_bytes(filtered)).hexdigest()
        message = f"{tool_name}:{owner_table.strip().upper()}:{expires_at}:{digest}".encode()
        return hmac.new(self._secret_bytes, message, hashlib.sha256).hexdigest()


def get_connectivity_report(*, system_service: SystemService | None = None) -> ConnectivityReport:
    """Run read-only connectivity probes and return a ConnectivityReport."""
    service = system_service or get_system_service()
    return service.check_connectivity()


def get_table_status_report(
    owner_table: str,
    *,
    system_service: SystemService | None = None,
) -> TableStatusReport:
    """Return a read-only TableStatusReport for owner_table."""
    normalized = normalize_table_key(owner_table)
    schema_name, table_name = normalized.split(".", 1)
    service = system_service or get_system_service()
    return service.get_table_offload_status(schema_name, table_name)


def list_offloaded_tables(
    schema_name: str,
    *,
    system_service: SystemService | None = None,
) -> TableDetails:
    """Return read-only table metadata for schema_name."""
    service = system_service or get_system_service()
    raw_tables = service.get_schema_tables(schema_name)
    results = [TableDetail.from_item(item) for item in (raw_tables or [])]
    return TableDetails(count=len(results), results=results)


def preview_offload_plan(
    owner_table: str,
    *,
    options: dict[str, Any] | None = None,
    runner_factory: Callable[[], Any] | None = None,
) -> OffloadPlanPreview:
    """Build a read-only dry-run offload plan with execute=False forced."""
    normalized = normalize_table_key(owner_table)
    merged: dict[str, Any] = dict(options or {})
    merged["owner_table"] = normalized
    merged["execute"] = False
    if runner_factory is not None:
        runner = runner_factory()
        runner.offload(dict(merged))
    return OffloadPlanPreview(
        owner_table=normalized,
        execute=False,
        dry_run=True,
        planned_options=merged,
    )


def get_job_status(
    execution_id: str,
    *,
    job_store: JobStoreProtocol | None = None,
) -> JobStatusSummary:
    """Query the durable job store for execution_id without mutating state."""
    store = job_store or create_job_store()
    record = store.get_job_by_execution_id(execution_id)
    if record is None:
        return JobStatusSummary(
            execution_id=execution_id,
            found=False,
            status="NOT_FOUND",
        )
    return JobStatusSummary(
        execution_id=record.execution_id,
        found=True,
        status=record.status.value,
        table_key=record.table_key,
        attempt=record.attempt,
        max_attempts=record.max_attempts,
        error_message=record.error_message,
        job=record,
    )


def build_mcp_config(*, gate: ConfirmationGate | None = None) -> MCPConfig:
    """Build the LitestarMCP configuration for GOE Listener."""
    active_gate = gate or ConfirmationGate()

    def _before_hook(tool_name: str, arguments: dict[str, Any], request: Any, /) -> None:
        before_mcp_tool_call(tool_name, arguments, request)
        if tool_name in MUTATING_MCP_TOOLS:
            raw_data = arguments.get("data")
            payload = dict(raw_data) if isinstance(raw_data, dict) else dict(arguments)
            owner_table = str(payload.get("owner_table") or arguments.get("owner_table") or "")
            token = str(arguments.get("confirmation_token") or payload.get("confirmation_token") or "")
            if not token and request is not None:
                headers = getattr(request, "headers", None)
                if headers is not None and hasattr(headers, "get"):
                    token = str(headers.get("x-goe-mcp-confirmation-token") or "")
            active_gate.enforce(
                tool_name=tool_name,
                owner_table=owner_table,
                payload=payload,
                token=token,
            )

    return MCPConfig(
        name="GOE Listener MCP",
        before_tool_call=_before_hook,
        after_tool_call=after_mcp_tool_call,
    )


def build_mcp_plugin(*, gate: ConfirmationGate | None = None) -> LitestarMCP:
    """Build the LitestarMCP plugin instance and register standalone read-only diagnostic tools."""
    plugin = LitestarMCP(build_mcp_config(gate=gate))
    for fn, tool_name, desc in (
        (_tool_get_connectivity_report, "get_connectivity_report", "Run read-only connectivity checks."),
        (_tool_get_table_status_report, "get_table_status_report", "Inspect read-only table offload status."),
        (_tool_list_offloaded_tables, "list_offloaded_tables", "List tables in a schema."),
        (_tool_preview_offload_plan, "preview_offload_plan", "Preview a dry-run offload plan with execute=False."),
        (_tool_get_job_status, "get_job_status", "Query durable job queue status by execution_id."),
    ):
        plugin.register_tool(Tool(fn, name=tool_name, description=desc))
    return plugin


def _tool_get_connectivity_report() -> ConnectivityReport:
    """MCP route wrapper for get_connectivity_report."""
    return get_connectivity_report()


def _tool_get_table_status_report(owner_table: FromQuery[str]) -> TableStatusReport:
    """MCP route wrapper for get_table_status_report."""
    return get_table_status_report(owner_table)


def _tool_list_offloaded_tables(schema_name: FromQuery[str]) -> TableDetails:
    """MCP route wrapper for list_offloaded_tables."""
    return list_offloaded_tables(schema_name)


def _tool_preview_offload_plan(owner_table: FromQuery[str]) -> OffloadPlanPreview:
    """MCP route wrapper for preview_offload_plan."""
    return preview_offload_plan(owner_table)


def _tool_get_job_status(execution_id: FromQuery[str]) -> JobStatusSummary:
    """MCP route wrapper for get_job_status."""
    return get_job_status(execution_id)

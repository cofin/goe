# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Stateless Model Context Protocol (MCP) configuration and MRTR/HMAC confirmation gate for GOE Listener."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Mapping
from typing import Any

import msgspec
from litestar_mcp import (
    MCPConfig,
    MCPInputRequiredResult,
    MCPTaskConfig,
    get_mcp_request_context,
)
from litestar_security.authentication import AUTH_POLICY_OPT_KEY, required

from goe.listener.config import ListenerSettings
from goe.listener.config import settings as default_settings
from goe.listener.schemas import ConfirmationChallenge
from goe.listener.telemetry import after_mcp_tool_call, before_mcp_tool_call
from goe.serializers import encode_json_bytes

__all__ = (
    "CONFIRMATION_HEADER",
    "DESTRUCTIVE_TOOL_ANNOTATIONS",
    "IDEMPOTENT_MUTATION_ANNOTATIONS",
    "READ_ONLY_TOOL_ANNOTATIONS",
    "ConfirmationChallenge",
    "ConfirmationGate",
    "build_mcp_config",
)

CONFIRMATION_HEADER = "x-goe-mcp-confirmation-token"
_EPHEMERAL_CONFIRMATION_SECRET = secrets.token_hex(32)

READ_ONLY_TOOL_ANNOTATIONS: dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

DESTRUCTIVE_TOOL_ANNOTATIONS: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}

IDEMPOTENT_MUTATION_ANNOTATIONS: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

_SERVER_INSTRUCTIONS = (
    "Gluent Offload Engine (GOE) Listener MCP Server. "
    "Always inspect connectivity (check_connectivity), schema/table metadata "
    "(get_table_offload_status, get_table_offload_metadata), and preview plans "
    "(preview_offload_plan or preview_schema_drift) before invoking mutating tools "
    "(execute_offload or apply_schema_sync). Mutating tools require either interactive "
    "MRTR confirmation or the signed confirmation_token issued by the matching preview tool."
)


class ConfirmationGate:
    """HMAC-SHA256 and MRTR confirmation gate for mutating MCP tool calls."""

    def __init__(
        self,
        active_settings: ListenerSettings | None = None,
        *,
        secret: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        cfg = active_settings or default_settings
        raw_secret = secret or cfg.shared_token or _EPHEMERAL_CONFIRMATION_SECRET
        self._secret_bytes = raw_secret.encode("utf-8")
        self._ttl_seconds = max(30, ttl_seconds if ttl_seconds is not None else cfg.confirmation_ttl_seconds)

    def issue_challenge(
        self,
        *,
        tool_name: str,
        owner_table: str,
        payload: Mapping[str, Any],
        now_epoch: int | None = None,
    ) -> ConfirmationChallenge:
        """Issue a signed time-bounded ConfirmationChallenge bound to tool_name, owner_table, and payload."""
        issued_at = int(time.time()) if now_epoch is None else now_epoch
        expires_at = issued_at + self._ttl_seconds
        normalized_table = owner_table.strip().upper()
        signature = self._sign(
            tool_name=tool_name,
            owner_table=normalized_table,
            payload=payload,
            expires_at=expires_at,
        )
        token = f"{expires_at}.{signature}"
        return ConfirmationChallenge(
            tool_name=tool_name,
            owner_table=normalized_table,
            confirmation_token=token,
            expires_at_epoch=expires_at,
            expires_in_seconds=self._ttl_seconds,
            instructions=(
                f"Confirm execution of {tool_name} on {normalized_table} by supplying confirmation_token "
                f"(valid for {self._ttl_seconds}s) or responding with confirm=true to the MCP input challenge."
            ),
        )

    def issue_token(
        self,
        *,
        tool_name: str,
        owner_table: str,
        payload: Mapping[str, Any],
        now_epoch: int | None = None,
    ) -> ConfirmationChallenge:
        """Issue a signed ConfirmationChallenge for tool_name, owner_table, and payload."""
        return self.issue_challenge(
            tool_name=tool_name,
            owner_table=owner_table,
            payload=payload,
            now_epoch=now_epoch,
        )

    def verify_token(
        self,
        *,
        token: str,
        tool_name: str,
        owner_table: str,
        payload: Mapping[str, Any],
        now_epoch: int | None = None,
    ) -> bool:
        """Verify that token is authentic and unexpired for the given tool call and payload."""
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
            owner_table=owner_table.strip().upper(),
            payload=payload,
            expires_at=expires_at,
        )
        return hmac.compare_digest(provided_sig, expected_sig)

    def require_mcp_confirmation(
        self,
        *,
        tool_name: str,
        owner_table: str,
        payload: Mapping[str, Any],
        confirmation_token: str | None = None,
        now_epoch: int | None = None,
    ) -> MCPInputRequiredResult | None:
        """Enforce MRTR or signed confirmation_token for active MCP requests, returning None when authorized."""
        try:
            ctx = get_mcp_request_context()
        except RuntimeError:
            ctx = None
        if ctx is None:
            return None

        normalized_table = owner_table.strip().upper()
        header_token: str | None = None
        if ctx.request is not None:
            headers = getattr(ctx.request, "headers", None)
            if headers is not None and hasattr(headers, "get"):
                raw_hdr = headers.get(CONFIRMATION_HEADER)
                if raw_hdr:
                    header_token = str(raw_hdr).strip()

        candidate = (confirmation_token or header_token or str(payload.get("confirmation_token") or "")).strip()
        rejection_reason: str | None = None
        if candidate:
            if self.verify_token(
                token=candidate,
                tool_name=tool_name,
                owner_table=normalized_table,
                payload=payload,
                now_epoch=now_epoch,
            ):
                return None
            rejection_reason = "Invalid, expired, or payload-mismatched confirmation_token."

        if isinstance(ctx.input_responses, Mapping):
            response_token = str(ctx.input_responses.get("confirmation_token") or "").strip()
            if response_token and self.verify_token(
                token=response_token,
                tool_name=tool_name,
                owner_table=normalized_table,
                payload=payload,
                now_epoch=now_epoch,
            ):
                return None

            confirmed_flag = ctx.input_responses.get("confirm")
            if confirmed_flag is True and ctx.request_state is not None:
                if isinstance(ctx.request_state, str):
                    state_token = ctx.request_state.strip()
                elif isinstance(ctx.request_state, Mapping):
                    state_token = str(ctx.request_state.get("confirmation_token") or "").strip()
                else:
                    state_token = ""
                if state_token and self.verify_token(
                    token=state_token,
                    tool_name=tool_name,
                    owner_table=normalized_table,
                    payload=payload,
                    now_epoch=now_epoch,
                ):
                    return None
                rejection_reason = "Invalid or expired MRTR requestState confirmation binding."

        challenge = self.issue_challenge(
            tool_name=tool_name,
            owner_table=normalized_table,
            payload=payload,
            now_epoch=now_epoch,
        )
        challenge_dict = msgspec.structs.asdict(challenge)
        confirm_field: dict[str, Any] = {
            "type": "boolean",
            "description": f"Set true to confirm executing {tool_name} on {normalized_table}.",
            "confirmation_challenge": challenge_dict,
        }
        if rejection_reason:
            confirm_field["rejection_reason"] = rejection_reason

        return MCPInputRequiredResult(
            input_requests={
                "confirm": confirm_field,
                "confirmation_token": {
                    "type": "string",
                    "description": "Optional signed confirmation_token from preview or challenge.",
                    "confirmation_challenge": challenge_dict,
                },
            },
            request_state=challenge.confirmation_token,
        )

    def _sign(
        self,
        *,
        tool_name: str,
        owner_table: str,
        payload: Mapping[str, Any],
        expires_at: int,
    ) -> str:
        filtered = {k: v for k, v in sorted(payload.items()) if k != "confirmation_token" and v is not None}
        digest = hashlib.sha256(encode_json_bytes(filtered)).hexdigest()
        message = f"{tool_name}:{owner_table.strip().upper()}:{expires_at}:{digest}".encode()
        return hmac.new(self._secret_bytes, message, hashlib.sha256).hexdigest()


def build_mcp_config(active_settings: ListenerSettings | None = None) -> MCPConfig:
    """Build the stateless LitestarMCP configuration for GOE Listener."""
    cfg = active_settings or default_settings
    return MCPConfig(
        name="GOE Listener MCP",
        instructions=_SERVER_INSTRUCTIONS,
        route_opt={AUTH_POLICY_OPT_KEY: required("console-key")},
        tasks=MCPTaskConfig(),
        max_blob_bytes=max(1_048_576, cfg.max_log_bytes * 2),
        before_tool_call=before_mcp_tool_call,
        after_tool_call=after_mcp_tool_call,
    )

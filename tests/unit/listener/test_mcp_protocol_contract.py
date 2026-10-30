# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""End-to-end MCP 2026-07-28 protocol contract and refusal acceptance suite for GOE Listener."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from unittest.mock import patch

import anyio
import msgspec
import pytest
from anyio.abc import ByteReceiveStream, ByteSendStream
from litestar.di import Provide
from litestar.testing import AsyncTestClient
from litestar_autowire import clear_autowire_cache
from litestar_mcp.mcp.stdio import MCPStdioContext, run_stdio_async

import goe.listener.app as app_module
from goe.listener import schemas
from goe.listener.app import create_app
from goe.listener.config import settings
from goe.listener.mcp import ConfirmationGate
from goe.listener.services.operations import ListenerOperationsService
from goe.listener.services.system import SystemService
from goe.serializers import decode_json, encode_json_bytes
from goe.sync.differ import (
    ColumnAddition,
    SchemaDiff,
    SchemaSyncService,
    SourceColumnSnapshot,
    TargetColumnSnapshot,
)
from tests.unit.listener.conftest import make_fake_oracle_job_store

MCP_PROTOCOL_VERSION = "2026-07-28"


class _ContractSystemService(SystemService):
    """Deterministic SystemService double for MCP protocol contract testing."""

    def get_schemas(self) -> list[dict[str, str | Any]]:
        return [{"schema_name": "SH", "table_count": 1, "schema_size_in_bytes": 1024.0}]

    def get_schema_tables(self, schema_name: str) -> list[dict[str, str | Any]]:
        return [
            {
                "owner": schema_name.upper(),
                "table_name": "SALES",
                "table_size_in_bytes": 1024.0,
                "num_rows": 100,
                "partitioned": True,
                "offloaded": True,
                "offload_type": "INCREMENTAL",
            }
        ]

    def preview_schema_drift(
        self,
        schema_name: str,
        table_name: str,
        *,
        source_columns: Sequence[SourceColumnSnapshot] = (),
        target_columns: Sequence[TargetColumnSnapshot] = (),
        sync_service: SchemaSyncService | None = None,
        confirmation_gate: ConfirmationGate | None = None,
    ) -> SchemaDiff:
        owner_table = f"{schema_name.strip().upper()}.{table_name.strip().upper()}"
        gate = confirmation_gate or app_module.get_confirmation_gate()
        challenge = gate.issue_challenge(
            tool_name="apply_schema_sync",
            owner_table=owner_table,
            payload={"owner_table": owner_table, "execute": True},
        )
        return SchemaDiff(
            schema_name=schema_name.upper(),
            table_name=table_name.upper(),
            target_schema=schema_name.lower(),
            target_table=table_name.lower(),
            additions=(ColumnAddition(column_name="PROMO_CODE", source_type="VARCHAR2(30)", target_type="STRING"),),
            ddl_statements=("ALTER TABLE `sh.sales` ADD COLUMN `PROMO_CODE` STRING",),
            confirmation_challenge=challenge,
        )


class _ContractOperationsService(ListenerOperationsService):
    """Deterministic ListenerOperationsService double for MCP protocol contract testing."""

    def preview_offload(self, data: schemas.OffloadOptions) -> schemas.OffloadPlanPreview:
        owner_table = data.owner_table.strip().upper()
        payload = data.to_params_dict()
        payload["owner_table"] = owner_table
        payload["execute"] = True
        challenge = app_module.get_confirmation_gate().issue_challenge(
            tool_name="execute_offload",
            owner_table=owner_table,
            payload=payload,
        )
        return schemas.OffloadPlanPreview(
            owner_table=owner_table,
            target_owner="sh",
            target_table="sales",
            offload_mode="INCREMENTAL",
            offload_type="RANGE",
            nothing_to_offload=False,
            partition_names=["SALES_Q1"],
            chunk_count=1,
            estimated_row_count=50,
            estimated_size_bytes=512,
            transport_method="SPARK",
            staging_format="PARQUET",
            ingest_strategy="LOAD_TABLE",
            create_backend_table=False,
            create_table_ddl=[],
            alter_table_ddl=["ALTER TABLE sh.sales ADD PARTITION"],
            frontend_where_clause="TIME_ID < DATE '2025-01-01'",
            notices=[],
            confirmation_challenge=challenge,
        )

    def synchronize_schema(self, data: schemas.SchemaSyncRequest) -> schemas.SchemaSyncExecutionResult:
        owner_table = data.owner_table.strip().upper()
        return schemas.SchemaSyncExecutionResult(
            owner_table=owner_table,
            backend="BIGQUERY",
            has_drift=True,
            applied=bool(data.execute),
            added_columns=["PROMO_CODE"],
            widened_columns=[],
            ddl_statements=["ALTER TABLE `sh.sales` ADD COLUMN `PROMO_CODE` STRING"],
            warnings=[],
        )

    def validate_table(self, data: schemas.ValidateTableRequest) -> schemas.ValidationResultSummary:
        return schemas.ValidationResultSummary(
            owner_table=data.owner_table.strip().upper(),
            passed=True,
            execute=bool(data.execute),
            aggregate_functions=list(data.aggregate_functions or ["COUNT"]),
            safe_boundary_applied=not data.skip_boundary_check,
            summary_message="Validation succeeded.",
            differing_rows=[],
        )


@pytest.mark.anyio
async def test_mcp_2026_07_28_discover_catalog_and_openapi_hygiene() -> None:
    """Verify server/discover, full catalog endpoints, legacy route removal, and OpenAPI schema exclusions."""
    clear_autowire_cache()
    store = make_fake_oracle_job_store()
    with patch.object(app_module, "_default_job_store", store):
        app = create_app(dependencies=_contract_dependencies(), enable_background_worker=False)
        async with AsyncTestClient(app=app) as client:
            get_mcp = await client.get("/mcp")
            assert get_mcp.status_code == 405
            del_mcp = await client.delete("/mcp")
            assert del_mcp.status_code == 405
            well_known = await client.get("/.well-known/mcp-server.json")
            assert well_known.status_code == 404

            discover_resp = await _post_mcp(client, "server/discover", req_id=1)
            assert discover_resp.status_code == 200
            discover_result = discover_resp.json()["result"]
            assert discover_result["supportedVersions"] == [MCP_PROTOCOL_VERSION]
            assert discover_result["instructions"]
            caps = discover_result["capabilities"]
            assert "tools" in caps
            assert "resources" in caps
            assert "prompts" in caps
            assert "io.modelcontextprotocol/tasks" in caps["extensions"]
            assert caps["extensions"]["io.modelcontextprotocol/skills"] == {"directoryRead": True}

            tools_resp = await _post_mcp(client, "tools/list", req_id=2)
            tool_names = {entry["name"] for entry in tools_resp.json()["result"]["tools"]}
            assert "health_check" not in tool_names
            assert {
                "check_connectivity",
                "get_listener_config",
                "generate_status_report",
                "get_offloadable_schemas",
                "get_offloadable_tables",
                "get_table_columns",
                "get_table_partitions",
                "get_table_offload_status",
                "preview_schema_drift",
                "get_table_offload_metadata",
                "get_command_executions",
                "get_command_execution",
                "get_command_execution_log",
                "get_execution_log_link",
                "list_offload_jobs",
                "get_offload_job",
                "preview_offload_plan",
                "execute_offload",
                "validate_table",
                "apply_schema_sync",
                "cancel_offload_job",
            }.issubset(tool_names)

            res_resp = await _post_mcp(client, "resources/list", req_id=3)
            res_uris = {entry["uri"] for entry in res_resp.json()["result"]["resources"]}
            assert {
                "litestar://openapi",
                "goe://system/status",
                "goe://system/connectivity",
                "goe://system/config",
                "goe://reports/status",
                "goe://schemas",
                "goe://executions",
                "goe://jobs",
                "skill://goe-offload-operations/SKILL.md",
                "skill://goe-diagnostics-and-recovery/SKILL.md",
                "skill://goe-schema-drift-and-validation/SKILL.md",
            }.issubset(res_uris)

            tmpl_resp = await _post_mcp(client, "resources/templates/list", req_id=4)
            templates = {entry["uriTemplate"] for entry in tmpl_resp.json()["result"]["resourceTemplates"]}
            assert {
                "goe://reports/status/{schema_filter}",
                "goe://schemas/{schema_name}/tables",
                "goe://schemas/{schema_name}/{table_name}/columns",
                "goe://schemas/{schema_name}/{table_name}/partitions",
                "goe://schemas/{schema_name}/{table_name}/status",
                "goe://schemas/{schema_name}/{table_name}/drift",
                "goe://schemas/{schema_name}/{table_name}/metadata",
                "goe://executions/{execution_id}",
                "goe://executions/{execution_id}/log",
                "goe://jobs/{execution_id}",
            }.issubset(templates)

            prompts_resp = await _post_mcp(client, "prompts/list", req_id=5)
            prompt_names = {entry["name"] for entry in prompts_resp.json()["result"]["prompts"]}
            assert {
                "plan_table_offload",
                "diagnose_failed_execution",
                "reconcile_schema_drift",
                "audit_schema_readiness",
            }.issubset(prompt_names)

            skills_resp = await _post_mcp(client, "skills/list", req_id=6)
            skill_uris = {entry["uri"] for entry in skills_resp.json()["result"]["skills"]}
            assert {
                "skill://goe-offload-operations/SKILL.md",
                "skill://goe-diagnostics-and-recovery/SKILL.md",
                "skill://goe-schema-drift-and-validation/SKILL.md",
            } == skill_uris

            openapi_resp = await client.get("/schema/openapi.json")
            assert openapi_resp.status_code == 200
            paths = openapi_resp.json()["paths"]
            assert "/mcp" not in paths
            assert not any(path.startswith("/api/prompts") for path in paths)
            assert not any(path.startswith("/api/_mcp/resources") for path in paths)
            assert "/api/system/status" in paths or "/api/system/status/" in paths
            assert "/api/orchestration/offload" in paths or "/api/orchestration/offload/" in paths


@pytest.mark.anyio
async def test_mcp_end_to_end_dba_workflows_and_rest_compat() -> None:
    """Verify preview -> MRTR/token execute -> job read -> cancel -> drift/sync -> validate and REST POST parity."""
    clear_autowire_cache()
    store = make_fake_oracle_job_store()
    with patch.object(app_module, "_default_job_store", store):
        app = create_app(dependencies=_contract_dependencies(), enable_background_worker=False)
        async with AsyncTestClient(app=app) as client:
            preview_resp = await _post_mcp(
                client,
                "tools/call",
                req_id=10,
                mcp_name="preview_offload_plan",
                extra_params={
                    "name": "preview_offload_plan",
                    "arguments": {"data": {"owner_table": "SH.SALES", "execute": False}},
                },
            )
            assert preview_resp.status_code == 200
            preview_body = decode_json(preview_resp.json()["result"]["content"][0]["text"])
            preview_token = preview_body["confirmation_challenge"]["confirmation_token"]

            mrtr_round1 = await _post_mcp(
                client,
                "tools/call",
                req_id=11,
                mcp_name="execute_offload",
                client_capabilities={"extensions": {"io.modelcontextprotocol/tasks": {}}},
                extra_params={
                    "name": "execute_offload",
                    "arguments": {"data": {"owner_table": "SH.SALES", "execute": True}},
                },
            )
            assert mrtr_round1.status_code == 200
            r1_result = mrtr_round1.json()["result"]
            assert r1_result["resultType"] == "input_required"
            request_state = r1_result["requestState"]

            mrtr_round2 = await _post_mcp(
                client,
                "tools/call",
                req_id=12,
                mcp_name="execute_offload",
                extra_params={
                    "name": "execute_offload",
                    "arguments": {"data": {"owner_table": "SH.SALES", "execute": True}},
                    "requestState": request_state,
                    "inputResponses": {"confirm": True},
                },
            )
            assert mrtr_round2.status_code == 200
            r2_result = mrtr_round2.json()["result"]
            scheduled_1 = r2_result["structuredContent"]
            exec_id_1 = scheduled_1["execution_id"]
            assert scheduled_1["status"] == "QUEUED"

            job_read_1 = await _post_mcp(
                client,
                "resources/read",
                req_id=13,
                mcp_name=f"goe://jobs/{exec_id_1}",
                extra_params={"uri": f"goe://jobs/{exec_id_1}"},
            )
            assert job_read_1.status_code == 200
            job_data_1 = decode_json(job_read_1.json()["result"]["contents"][0]["text"])
            assert job_data_1["status"] == "PENDING"

            cancel_resp = await _post_mcp(
                client,
                "tools/call",
                req_id=14,
                mcp_name="cancel_offload_job",
                extra_params={"name": "cancel_offload_job", "arguments": {"execution_id": exec_id_1}},
            )
            assert cancel_resp.status_code == 200
            cancelled_job = decode_json(cancel_resp.json()["result"]["content"][0]["text"])
            assert cancelled_job["status"] == "CANCELLED"

            token_exec = await _post_mcp(
                client,
                "tools/call",
                req_id=15,
                mcp_name="execute_offload",
                extra_params={
                    "name": "execute_offload",
                    "arguments": {
                        "data": {
                            "owner_table": "SH.SALES",
                            "execute": True,
                            "confirmation_token": preview_token,
                        }
                    },
                },
            )
            assert token_exec.status_code == 200
            scheduled_2 = token_exec.json()["result"]["structuredContent"]
            exec_id_2 = scheduled_2["execution_id"]
            await client.post(f"/api/orchestration/executions/{exec_id_2}/cancel/")

            drift_resp = await _post_mcp(
                client,
                "resources/read",
                req_id=16,
                mcp_name="goe://schemas/SH/SALES/drift",
                extra_params={"uri": "goe://schemas/SH/SALES/drift"},
            )
            assert drift_resp.status_code == 200
            drift_data = decode_json(drift_resp.json()["result"]["contents"][0]["text"])
            sync_token = drift_data["confirmation_challenge"]["confirmation_token"]

            sync_resp = await _post_mcp(
                client,
                "tools/call",
                req_id=17,
                mcp_name="apply_schema_sync",
                extra_params={
                    "name": "apply_schema_sync",
                    "arguments": {
                        "data": {
                            "owner_table": "SH.SALES",
                            "execute": True,
                            "confirmation_token": sync_token,
                        }
                    },
                },
            )
            assert sync_resp.status_code == 200
            sync_body = decode_json(sync_resp.json()["result"]["content"][0]["text"])
            assert sync_body["applied"] is True
            assert sync_body["added_columns"] == ["PROMO_CODE"]

            val_resp = await _post_mcp(
                client,
                "tools/call",
                req_id=18,
                mcp_name="validate_table",
                extra_params={
                    "name": "validate_table",
                    "arguments": {"data": {"owner_table": "SH.SALES", "execute": True}},
                },
            )
            assert val_resp.status_code == 200
            val_body = decode_json(val_resp.json()["result"]["content"][0]["text"])
            assert val_body["passed"] is True

            rest_offload = await client.post(
                "/api/orchestration/offload/",
                json={"owner_table": "SH.CUSTOMERS", "execute": True},
            )
            assert rest_offload.status_code == 201
            assert rest_offload.json()["status"] == "QUEUED"

            rest_sync = await client.post(
                "/api/orchestration/sync/",
                json={"owner_table": "SH.CUSTOMERS", "execute": True},
            )
            assert rest_sync.status_code == 201
            assert rest_sync.json()["applied"] is True


@pytest.mark.anyio
async def test_mcp_negative_refusal_paths() -> None:
    """Verify 401 auth refusal, tampered confirmation refusal, invalid cursor -32602, and 409 active-table conflict."""
    clear_autowire_cache()
    store = make_fake_oracle_job_store()
    secured = msgspec.structs.replace(settings, shared_token="contract-secret")
    with (
        patch.object(app_module, "_default_job_store", store),
        patch("goe.listener.security.settings", secured),
    ):
        app = create_app(dependencies=_contract_dependencies(), enable_background_worker=False)
        async with AsyncTestClient(app=app) as client:
            status_get = await client.get("/api/system/status/")
            assert status_get.status_code == 200
            status_head = await client.head("/api/system/status/")
            assert status_head.status_code == 200

            unauth_cfg = await client.get("/api/system/config/")
            assert unauth_cfg.status_code == 401
            unauth_mcp = await _post_mcp(client, "tools/list", req_id=1)
            assert unauth_mcp.status_code == 401

            wrong_url, wrong_headers, wrong_json = _rpc_parts("tools/list", req_id=2)
            wrong_headers["x-goe-console-key"] = "wrong-token"
            wrong_mcp = await client.post(wrong_url, headers=wrong_headers, json=wrong_json)
            assert wrong_mcp.status_code == 401

            auth_headers = {"x-goe-console-key": "contract-secret"}

            tampered_url, tampered_hdrs, tampered_json = _rpc_parts(
                "tools/call",
                req_id=3,
                mcp_name="execute_offload",
                extra_params={
                    "name": "execute_offload",
                    "arguments": {
                        "data": {
                            "owner_table": "SH.SALES",
                            "execute": True,
                            "confirmation_token": "9999999999.invalidhmac",
                        }
                    },
                },
            )
            tampered_resp = await client.post(
                tampered_url, headers={**tampered_hdrs, **auth_headers}, json=tampered_json
            )
            assert tampered_resp.status_code == 200
            tampered_res = tampered_resp.json()["result"]
            assert tampered_res["resultType"] == "input_required"
            assert "rejection_reason" in tampered_res["inputRequests"]["confirm"]
            assert store.list_jobs() == []

            cursor_url, cursor_hdrs, cursor_json = _rpc_parts(
                "tools/list",
                req_id=4,
                extra_params={"cursor": "!!!not-a-valid-cursor!!!"},
            )
            cursor_resp = await client.post(cursor_url, headers={**cursor_hdrs, **auth_headers}, json=cursor_json)
            assert cursor_resp.json()["error"]["code"] == -32602

            await client.post(
                "/api/orchestration/offload/",
                headers=auth_headers,
                json={"owner_table": "SH.SALES", "execute": True},
            )
            gate = app_module.get_confirmation_gate()
            dup_challenge = gate.issue_challenge(
                tool_name="execute_offload",
                owner_table="SH.SALES",
                payload={"owner_table": "SH.SALES", "execute": True},
            )
            dup_url, dup_hdrs, dup_json = _rpc_parts(
                "tools/call",
                req_id=5,
                mcp_name="execute_offload",
                extra_params={
                    "name": "execute_offload",
                    "arguments": {
                        "data": {
                            "owner_table": "SH.SALES",
                            "execute": True,
                            "confirmation_token": dup_challenge.confirmation_token,
                        }
                    },
                },
            )
            dup_resp = await client.post(dup_url, headers={**dup_hdrs, **auth_headers}, json=dup_json)
            assert dup_resp.status_code == 200
            assert dup_resp.json()["result"]["isError"] is True


@pytest.mark.anyio
async def test_mcp_run_stdio_async_authenticated_smoke() -> None:
    """Verify run_stdio_async dispatches server/discover and resources/read over AnyIO streams with shared_token."""
    clear_autowire_cache()
    secured = msgspec.structs.replace(settings, shared_token="stdio-contract-token")
    with patch("goe.listener.security.settings", secured):
        app = create_app(enable_background_worker=False)
        discover_frame = encode_json_bytes(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION}},
            }
        )
        status_frame = encode_json_bytes(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/read",
                "params": {
                    "uri": "goe://system/status",
                    "_meta": {"io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION},
                },
            }
        )
        stdin_stream = _MemoryByteReceiveStream(discover_frame + b"\n" + status_frame + b"\n")
        stdout_stream = _MemoryByteSendStream()

        exit_code = await run_stdio_async(
            app,
            stdio_context=MCPStdioContext(client_id="stdio-smoke", owner_id="dba-smoke"),
            headers={"x-goe-console-key": "stdio-contract-token"},
            header_name="x-goe-console-key",
            token_prefix="",
            stdin=stdin_stream,
            stdout=stdout_stream,
        )
        assert exit_code == 0

        lines = [line for line in b"".join(stdout_stream.chunks).splitlines() if line.strip()]
        assert len(lines) == 2
        by_id = {decode_json(line)["id"]: decode_json(line) for line in lines}
        assert by_id[1]["result"]["supportedVersions"] == [MCP_PROTOCOL_VERSION]
        status_payload = decode_json(by_id[2]["result"]["contents"][0]["text"])
        assert status_payload["status"] == "OK"


class _MemoryByteReceiveStream(ByteReceiveStream):
    """In-memory AnyIO ByteReceiveStream for testing run_stdio_async."""

    def __init__(self, payload: bytes) -> None:
        self._buffer = bytearray(payload)

    async def receive(self, max_bytes: int = 65536) -> bytes:
        if not self._buffer:
            raise anyio.EndOfStream
        chunk = bytes(self._buffer[:max_bytes])
        del self._buffer[:max_bytes]
        return chunk

    async def aclose(self) -> None:
        self._buffer.clear()


class _MemoryByteSendStream(ByteSendStream):
    """In-memory AnyIO ByteSendStream for testing run_stdio_async."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    async def send(self, item: bytes) -> None:
        self.chunks.append(bytes(item))

    async def aclose(self) -> None:
        return None


def _provide_system_service() -> SystemService:
    """Return the contract test SystemService double."""
    return _ContractSystemService()


def _provide_operations_service() -> ListenerOperationsService:
    """Return the contract test ListenerOperationsService double."""
    return _ContractOperationsService()


def _contract_dependencies() -> dict[str, Any]:
    """Return Litestar DI overrides for the contract test suite."""
    return {
        "system_service": Provide(_provide_system_service, sync_to_thread=False),
        "operations_service": Provide(_provide_operations_service, sync_to_thread=False),
    }


async def _post_mcp(
    client: AsyncTestClient[Any],
    method: str,
    *,
    req_id: int,
    mcp_name: str | None = None,
    client_capabilities: dict[str, Any] | None = None,
    extra_params: dict[str, Any] | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> Any:
    """Send a JSON-RPC 2.0 POST request to /mcp via AsyncTestClient."""
    url, headers, payload = _rpc_parts(
        method,
        req_id=req_id,
        mcp_name=mcp_name,
        client_capabilities=client_capabilities,
        extra_params=extra_params,
        extra_meta=extra_meta,
    )
    return await client.post(url, headers=headers, json=payload)


def _rpc_parts(
    method: str,
    *,
    req_id: int,
    mcp_name: str | None = None,
    client_capabilities: dict[str, Any] | None = None,
    extra_params: dict[str, Any] | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Construct (/mcp, headers, json_payload) for a stateless MCP 2026-07-28 request."""
    meta: dict[str, Any] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": client_capabilities or {},
    }
    if extra_meta:
        meta.update(extra_meta)
    params: dict[str, Any] = {"_meta": meta}
    if extra_params:
        params.update(extra_params)
    headers: dict[str, str] = {
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if mcp_name is not None:
        headers["Mcp-Name"] = mcp_name
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params,
    }
    return "/mcp", headers, payload

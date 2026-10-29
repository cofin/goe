# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for SystemController endpoints and console-key authentication."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec
from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.cache import ListenerCache
from goe.listener.config import settings
from goe.listener.jobs.store import SqliteJobStore
from goe.listener.services.system import SystemService
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.models import OffloadMetadata
from goe.report.models import StatusReportEnvelope, TableStatusReport
from goe.serializers import decode_json


def test_system_status(tmp_path: Path) -> None:
    """Verify /api/system/status/ returns 200 OK."""
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={"job_store": Provide(lambda: store, sync_to_thread=False)},
        enable_background_worker=False,
    )
    with TestClient(app=app) as client:
        response = client.get("/api/system/status/")
        assert response.status_code == 200
        assert response.json() == {"status": "OK"}


def test_system_config(tmp_path: Path) -> None:
    """Verify /api/system/config/ returns listener and database metadata."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.generate_listener_endpoint_id.return_value = "00000000-0000-0000-0000-000000000001"
    mock_service.generate_listener_group_id.return_value = "00000000-0000-0000-0000-000000000002"
    mock_service.get_db_unique_name.return_value = "ORCL"
    mock_service.get_version.return_value = "1.1.1"
    mock_service.get_frontend_type.return_value = "ORACLE"
    mock_service.get_backend_type.return_value = "BIGQUERY"

    async def mock_active_endpoints() -> list:
        return []

    mock_service.get_active_listener_endpoints = mock_active_endpoints

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    with TestClient(app=app) as client:
        response = client.get("/api/system/config/")
        assert response.status_code == 200
        data = response.json()
        assert data["endpoint_id"] == "00000000-0000-0000-0000-000000000001"
        assert data["db_unique_name"] == "ORCL"
        assert data["frontend_type"] == "ORACLE"


def test_system_schemas(tmp_path: Path) -> None:
    """Verify /api/system/schemas/ returns offloadable schemas."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_schemas.return_value = [
        {"schema_name": "SH", "hybrid_schema_exists": True, "table_count": 5, "schema_size_in_bytes": 1024.0}
    ]

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    with TestClient(app=app) as client:
        response = client.get("/api/system/schemas/")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["schema_name"] == "SH"


def test_system_console_key_enforcement(tmp_path: Path) -> None:
    """Verify x-goe-console-key header enforcement when settings.shared_token is configured."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_schemas.return_value = [
        {"schema_name": "SH", "hybrid_schema_exists": True, "table_count": 5, "schema_size_in_bytes": 1024.0}
    ]

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    secured_settings = msgspec.structs.replace(settings, shared_token="secret-token-123")
    with patch("goe.listener.security.settings", secured_settings), TestClient(app=app) as client:
        status_resp = client.get("/api/system/status/")
        assert status_resp.status_code == 200

        unauth_resp = client.get("/api/system/schemas/")
        assert unauth_resp.status_code == 401

        invalid_resp = client.get("/api/system/schemas/", headers={"x-goe-console-key": "wrong-token"})
        assert invalid_resp.status_code == 401

        valid_resp = client.get("/api/system/schemas/", headers={"x-goe-console-key": "secret-token-123"})
        assert valid_resp.status_code == 200
        assert valid_resp.json()["count"] == 1


def test_table_metadata_and_status_report_endpoints(tmp_path: Path) -> None:
    """Verify /metadata/ and /reports/status/ endpoints and HEAD /api/system/status/ public probe."""
    mock_service = MagicMock(spec=SystemService)
    exec_id = ExecutionId.from_str("00000000-0000-0000-0000-000000000042")
    sample_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh_bq",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_key="TIME_ID",
        incremental_high_value="TIMESTAMP' 2026-01-01 00:00:00'",
        incremental_range="PARTITION",
        command_execution=exec_id,
    )
    mock_service.get_table_offload_metadata.side_effect = lambda schema_name, table_name: (
        sample_meta if (schema_name.upper(), table_name.upper()) == ("SH", "SALES") else None
    )
    sample_envelope = StatusReportEnvelope(
        generated_at="2026-10-29T00:00:00+00:00",
        database_name="ORCL",
        total_tables=1,
        total_source_bytes=2048,
        total_offloaded_bytes=1024,
        total_reclaimable_bytes=1024,
        tables=(
            TableStatusReport(
                schema_name="SH",
                table_name="SALES",
                target_schema="sh_bq",
                target_table="sales",
                offload_type="INCREMENTAL",
                source_rows=100,
                source_bytes=2048,
                offloaded_rows=50,
                offloaded_bytes=1024,
                reclaimable_rows=50,
                reclaimable_bytes=1024,
            ),
        ),
    )
    mock_service.get_status_report.return_value = sample_envelope

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    with TestClient(app=app) as client:
        head_resp = client.head("/api/system/status/")
        assert head_resp.status_code == 200

        meta_resp = client.get("/api/system/schemas/SH/SALES/metadata/")
        assert meta_resp.status_code == 200
        meta_body = meta_resp.json()
        assert meta_body["offloaded_owner"] == "SH"
        assert meta_body["offloaded_table"] == "SALES"
        assert meta_body["backend_owner"] == "sh_bq"
        assert meta_body["command_execution"] == str(exec_id)

        missing_resp = client.get("/api/system/schemas/SH/UNKNOWN/metadata/")
        assert missing_resp.status_code == 404
        assert "SH.UNKNOWN" in missing_resp.json()["detail"]

        report_resp = client.get("/api/system/reports/status/", params={"schema_name": "SH", "demo": "true"})
        assert report_resp.status_code == 200
        report_body = report_resp.json()
        assert report_body["database_name"] == "ORCL"
        assert report_body["total_tables"] == 1
        mock_service.get_status_report.assert_called_once_with(
            schema_name="SH",
            table_name=None,
            demo=True,
        )


def test_mcp_simultaneous_tools_and_goe_resources_discovery(tmp_path: Path) -> None:
    """Verify POST /mcp simultaneously discovers @mcp_tool handlers and GOEResourcesController goe:// URIs."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.generate_listener_endpoint_id.return_value = "00000000-0000-0000-0000-000000000001"
    mock_service.generate_listener_group_id.return_value = "00000000-0000-0000-0000-000000000002"
    mock_service.get_db_unique_name.return_value = "ORCL"
    mock_service.get_version.return_value = "2.4.0"
    mock_service.get_frontend_type.return_value = "ORACLE"
    mock_service.get_backend_type.return_value = "BIGQUERY"
    mock_service.get_schemas.return_value = [
        {"schema_name": "SH", "hybrid_schema_exists": True, "table_count": 2, "schema_size_in_bytes": 2048.0}
    ]
    mock_service.get_schema_tables.return_value = [
        {"table_name": "SALES", "offload_status": "OFFLOADED", "table_size_in_bytes": 1024.0}
    ]
    mock_service.get_table_columns.return_value = [
        {"column_name": "PROD_ID", "data_type": "NUMBER", "data_precision": 10, "data_scale": 0, "is_nullable": False}
    ]
    mock_service.get_table_offload_metadata.return_value = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh_bq",
        backend_table="sales",
        offload_type="FULL",
    )

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    base_meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }

    with TestClient(app=app) as client:
        openapi_resp = client.get("/schema/openapi.json")
        assert openapi_resp.status_code == 200
        openapi_paths = set(openapi_resp.json().get("paths", {}).keys())
        assert not any(p.startswith("/api/_mcp/resources") for p in openapi_paths)

        tools_resp = client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": base_meta}},
        )
        assert tools_resp.status_code == 200
        tools_by_name = {t["name"]: t for t in tools_resp.json()["result"]["tools"]}
        expected_read_only_tools = {
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
        }
        assert expected_read_only_tools.issubset(tools_by_name.keys())
        assert "health_check" not in tools_by_name
        for name in expected_read_only_tools:
            assert tools_by_name[name]["annotations"]["readOnlyHint"] is True

        res_resp = client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "resources/list"},
            json={"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {"_meta": base_meta}},
        )
        assert res_resp.status_code == 200
        resource_uris = {r["uri"] for r in res_resp.json()["result"]["resources"]}
        assert {
            "litestar://openapi",
            "goe://system/status",
            "goe://system/connectivity",
            "goe://system/config",
            "goe://reports/status",
            "goe://schemas",
        }.issubset(resource_uris)

        tmpl_resp = client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "resources/templates/list"},
            json={"jsonrpc": "2.0", "id": 3, "method": "resources/templates/list", "params": {"_meta": base_meta}},
        )
        assert tmpl_resp.status_code == 200
        template_uris = {t["uriTemplate"] for t in tmpl_resp.json()["result"]["resourceTemplates"]}
        assert {
            "goe://schemas/{schema_name}/tables",
            "goe://schemas/{schema_name}/{table_name}/columns",
            "goe://schemas/{schema_name}/{table_name}/partitions",
            "goe://schemas/{schema_name}/{table_name}/status",
            "goe://schemas/{schema_name}/{table_name}/drift",
            "goe://schemas/{schema_name}/{table_name}/metadata",
        }.issubset(template_uris)

        for req_id, uri in enumerate(
            (
                "goe://system/config",
                "goe://schemas",
                "goe://schemas/SH/tables",
                "goe://schemas/SH/SALES/columns",
                "goe://schemas/SH/SALES/metadata",
            ),
            start=10,
        ):
            read_resp = client.post(
                "/mcp",
                headers={
                    "MCP-Protocol-Version": "2026-07-28",
                    "Mcp-Method": "resources/read",
                    "Mcp-Name": uri,
                },
                json={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "resources/read",
                    "params": {"uri": uri, "_meta": base_meta},
                },
            )
            assert read_resp.status_code == 200
            contents = read_resp.json()["result"]["contents"]
            assert len(contents) == 1
            assert contents[0]["uri"] == uri
            assert contents[0]["mimeType"] == "application/json"
            decoded = decode_json(contents[0]["text"])
            assert isinstance(decoded, dict)

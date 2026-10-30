# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ListenerCache, ListenerCacheSink, and refactored Listener controllers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.cache import ListenerCache, ListenerCacheSink
from goe.listener.services.system import SystemService
from goe.platform.locking import OrchestrationLockTimeout
from tests.unit.listener.conftest import make_fake_oracle_job_store


@pytest.mark.anyio
async def test_listener_cache_lru_ttl_singleflight_and_sink_invalidation() -> None:
    """Verify ListenerCache LRU eviction, monotonic TTL, singleflight coalescing, and sink prefix invalidation."""
    cache = ListenerCache(max_entries=2, default_ttl_seconds=60.0)
    await cache.set("k1", "v1")
    await cache.set("k2", "v2")
    assert await cache.get("k1") == "v1"
    await cache.set("k3", "v3")
    assert await cache.get("k2") is None
    assert await cache.get("k1") == "v1"
    assert await cache.get("k3") == "v3"

    await cache.set("short", "ephemeral", ttl_seconds=0.0)
    assert await cache.get("short") is None

    call_count = 0

    async def slow_loader() -> dict[str, int]:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.03)
        return {"loaded": call_count}

    concurrent_results = await asyncio.gather(*(cache.get_or_load("schemas:all", slow_loader) for _ in range(10)))
    assert call_count == 1
    assert all(item == {"loaded": 1} for item in concurrent_results)

    invalidation_cache = ListenerCache(max_entries=16, default_ttl_seconds=60.0)
    await invalidation_cache.set("executions:list:steps=0", ["exec-1"])
    await invalidation_cache.set("schemas:SH:tables", ["SALES"])
    await invalidation_cache.set("tables:SH:SALES:columns", ["PROD_ID"])
    await invalidation_cache.set("tables:HR:EMPLOYEES:columns", ["EMP_ID"])

    sink = ListenerCacheSink(invalidation_cache, owner_table="sh.sales")
    sink.emit(SimpleNamespace(kind="step_finished"))

    assert await invalidation_cache.get("executions:list:steps=0") is None
    assert await invalidation_cache.get("schemas:SH:tables") is None
    assert await invalidation_cache.get("tables:SH:SALES:columns") is None
    assert await invalidation_cache.get("tables:HR:EMPLOYEES:columns") == ["EMP_ID"]
    sink.close()


def test_post_offload_enqueues_durable_job_and_returns_409_on_conflict(tmp_path: Path) -> None:
    """Verify POST /api/orchestration/offload/ enqueues into JobStore and returns 409 on lock or duplicate job."""
    store = make_fake_oracle_job_store()
    cache = ListenerCache()
    app = create_app(
        dependencies={
            "job_store": Provide(lambda: store, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    with (
        patch("goe.listener.utils.orchestrate.check_for_running_command", return_value=False),
        TestClient(app=app) as client,
    ):
        first = client.post("/api/orchestration/offload/", json={"owner_table": "SH.SALES", "execute": True})
        assert first.status_code in (200, 201)
        exec_id = first.json()["execution_id"]
        assert store.get_job_by_execution_id(exec_id) is not None

        dup = client.post("/api/orchestration/offload/", json={"owner_table": "sh.sales", "execute": True})
        assert dup.status_code == 409
        assert "SH.SALES" in dup.json()["detail"]

    mock_lock = MagicMock()
    mock_lock.acquire.side_effect = OrchestrationLockTimeout("locked")
    with (
        patch("goe.listener.utils.orchestrate.orchestration_lock_for_table", return_value=mock_lock),
        TestClient(app=app) as client,
    ):
        locked = client.post("/api/orchestration/offload/", json={"owner_table": "SH.CUSTOMERS", "execute": True})
        assert locked.status_code == 409
        assert "SH.CUSTOMERS" in locked.json()["detail"]


def test_execution_log_path_containment_bounded_read_and_gcs_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify execution-log endpoint enforces OFFLOAD_LOGDIR containment, is_file=False when missing, and gs:// reads."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    monkeypatch.setenv("OFFLOAD_LOGDIR", str(log_dir))

    mock_service = MagicMock(spec=SystemService)
    mock_dfs = MagicMock()
    mock_service.get_dfs_client.return_value = mock_dfs
    cache = ListenerCache()
    store = make_fake_oracle_job_store()

    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    exec_id = "00000000-0000-0000-0000-000000000001"
    with TestClient(app=app) as client:
        mock_service.get_command_execution.return_value = {
            "execution_id": exec_id,
            "command_log_path": str(log_dir / "missing_offload.log"),
        }
        missing_resp = client.get(f"/api/orchestration/executions/{exec_id}/execution-log/")
        assert missing_resp.status_code == 200
        assert missing_resp.json()["is_file"] is False

        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("top-secret", encoding="utf-8")
        mock_service.get_command_execution.return_value = {
            "execution_id": exec_id,
            "command_log_path": str(outside_file),
        }
        traversal_resp = client.get(f"/api/orchestration/executions/{exec_id}/execution-log/")
        assert traversal_resp.status_code == 403

        valid_log = log_dir / "offload_sh_sales.log"
        valid_log.write_text("line-1\nline-2\n", encoding="utf-8")
        mock_service.get_command_execution.return_value = {
            "execution_id": exec_id,
            "command_log_path": str(valid_log),
        }
        valid_resp = client.get(f"/api/orchestration/executions/{exec_id}/execution-log/")
        assert valid_resp.status_code == 200
        body = valid_resp.json()
        assert body["is_file"] is True
        assert body["name"] == "offload_sh_sales"
        assert "line-2" in body["message"]

        mock_dfs.read.return_value = b"gcs-log-output"
        mock_service.get_command_execution.return_value = {
            "execution_id": exec_id,
            "command_log_path": "gs://goe-logs-bucket/offload_gcs.log",
        }
        gcs_resp = client.get(f"/api/orchestration/executions/{exec_id}/execution-log/")
        assert gcs_resp.status_code == 200
        gcs_body = gcs_resp.json()
        assert gcs_body["is_file"] is True
        assert gcs_body["name"] == "offload_gcs"
        assert gcs_body["message"] == "gcs-log-output"


def test_split_system_schemas_and_tables_controllers(tmp_path: Path) -> None:
    """Verify SystemController, SchemasController, and TablesController serve cached FrozenBaseStruct responses."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.generate_listener_endpoint_id.return_value = "ep-1"
    mock_service.generate_listener_group_id.return_value = "grp-1"
    mock_service.get_db_unique_name.return_value = "ORCL_PROD"
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
    mock_service.get_table_partitions.return_value = [
        {"partition_name": "P_2026", "partition_position": 1, "high_value": "2026-01-01"}
    ]
    mock_service.get_table_subpartitions.return_value = [
        {"partition_name": "P_2026", "subpartition_name": "SP_Q1", "subpartition_position": 1, "high_value": "Q1"}
    ]

    cache = ListenerCache()
    store = make_fake_oracle_job_store()
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    with TestClient(app=app) as client:
        assert client.get("/api/system/status/").status_code == 200
        cfg = client.get("/api/system/config/").json()
        assert cfg["db_unique_name"] == "ORCL_PROD"

        schemas_resp = client.get("/api/system/schemas/").json()
        assert schemas_resp["count"] == 1
        assert schemas_resp["results"][0]["schema_name"] == "SH"

        tables_resp = client.get("/api/system/schemas/SH/").json()
        assert tables_resp["count"] == 1
        assert tables_resp["results"][0]["table_name"] == "SALES"

        cols_resp = client.get("/api/system/schemas/SH/SALES/columns/").json()
        assert cols_resp["count"] == 1
        assert cols_resp["results"][0]["column_name"] == "PROD_ID"

        parts_resp = client.get("/api/system/schemas/SH/SALES/partitions/").json()
        assert parts_resp["count"] == 1
        assert parts_resp["results"][0]["partition_name"] == "P_2026"
        assert parts_resp["results"][0]["subpartitions"][0]["subpartition_name"] == "SP_Q1"

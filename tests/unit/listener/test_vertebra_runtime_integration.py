# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""End-to-end integration tests for Listener ASGI lifespan, CORS OPTIONS, HEAD, streaming, and 64-way concurrency."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from litestar import Litestar
from litestar.di import Provide
from litestar.testing import AsyncTestClient

from goe.listener.app import create_app
from goe.listener.cache import ListenerCache
from goe.listener.config.application import ListenerSettings
from goe.listener.services.system import SystemService
from tests.unit.listener.conftest import make_fake_oracle_job_store


def test_listener_settings_to_vertebra_env_preserves_caller_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ListenerSettings.to_vertebra_env exports defaults while preserving caller-supplied VERTEBRA_* keys."""
    monkeypatch.setenv("OFFLOAD_LISTENER_TOPOLOGY", "embedded")
    monkeypatch.setenv("OFFLOAD_LISTENER_THREADS", "4")
    monkeypatch.setenv("OFFLOAD_LISTENER_DRAIN_TIMEOUT", "45")

    cfg = ListenerSettings(global_config=None, host="127.0.0.1", port=8000, http_workers=3)
    assert cfg.topology == "embedded"
    assert cfg.threads == 4
    assert cfg.drain_timeout_seconds == 45
    assert cfg.shutdown_timeout_seconds == 50

    env = cfg.to_vertebra_env({"VERTEBRA_PORT": "9999", "VERTEBRA_WORKERS": "8", "CUSTOM_VAR": "1"})
    assert env["VERTEBRA_HOST"] == "127.0.0.1"
    assert env["VERTEBRA_PORT"] == "9999"
    assert env["VERTEBRA_WORKERS"] == "8"
    assert env["VERTEBRA_TOPOLOGY"] == "embedded"
    assert env["VERTEBRA_THREADS"] == "4"
    assert env["VERTEBRA_DRAIN_TIMEOUT"] == "45"
    assert env["VERTEBRA_SHUTDOWN_TIMEOUT"] == "50"
    assert env["CUSTOM_VAR"] == "1"


@pytest.mark.anyio
async def test_asgi_lifespan_startup_shutdown_and_failure_refusal() -> None:
    """Verify create_app populates app.state during lifespan and aborts startup when a startup_hook raises."""
    store = make_fake_oracle_job_store()
    with patch("goe.listener.app._default_job_store", store):
        app = create_app(enable_background_worker=True)
        async with AsyncTestClient(app=app) as client:
            resp = await client.get("/api/system/status/")
            assert resp.status_code == 200
            assert isinstance(app.state.listener_cache, ListenerCache)
            assert app.state.job_store is store
            assert app.state.job_worker is not None

    def failing_hook(_app: Litestar) -> None:
        raise RuntimeError("simulated startup failure")

    with patch("goe.listener.app._default_job_store", store):
        bad_app = create_app(startup_hooks=(failing_hook,), enable_background_worker=False)
        with pytest.raises((RuntimeError, BaseExceptionGroup)) as exc_info:
            async with AsyncTestClient(app=bad_app) as client:
                await client.get("/api/system/status/")
        assert "simulated startup failure" in str(exc_info.value) or any(
            "simulated startup failure" in str(sub) for sub in getattr(exc_info.value, "exceptions", ())
        )


@pytest.mark.anyio
async def test_cors_options_preflight_and_head_status_probe() -> None:
    """Verify OPTIONS /api/orchestration/offload/ returns CORS preflight headers and HEAD /api/system/status/ returns 200."""
    store = make_fake_oracle_job_store()
    app = create_app(
        dependencies={"job_store": Provide(lambda: store, sync_to_thread=False)},
        enable_background_worker=False,
    )
    async with AsyncTestClient(app=app) as client:
        options_resp = await client.options(
            "/api/orchestration/offload/",
            headers={
                "Origin": "https://console.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-goe-console-key",
            },
        )
        assert options_resp.status_code in (200, 204)
        lower_headers = {k.lower(): v for k, v in options_resp.headers.items()}
        assert "access-control-allow-origin" in lower_headers
        assert "access-control-allow-methods" in lower_headers
        assert "access-control-allow-headers" in lower_headers

        head_resp = await client.head("/api/system/status/")
        assert head_resp.status_code == 200
        assert head_resp.content == b""


@pytest.mark.anyio
async def test_bounded_log_response_and_64_way_concurrent_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify bounded log responses and 64 concurrent requests across Listener routes complete within 5s with zero 500s."""
    store = make_fake_oracle_job_store()
    cache = ListenerCache()
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    monkeypatch.setenv("OFFLOAD_LOGDIR", str(log_dir))
    log_file = log_dir / "offload_sh_sales.log"
    log_file.write_bytes(b"A" * 2048 + b"\nFINAL_MARKER_LINE\n")

    exec_id = str(uuid4())
    store.enqueue(
        execution_id=exec_id,
        owner_table="SH.SALES",
        payload={"owner_table": "SH.SALES"},
    )

    class _FastSystemService(SystemService):
        def get_schemas(self) -> list[dict[str, Any]]:
            return [{"schema_name": "SH"}, {"schema_name": "HR"}]

        def get_command_executions(self) -> list[dict[str, Any]]:
            return [{"execution_id": exec_id, "command_type": "OFFLOAD", "status": "SUCCESS"}]

        def get_command_execution(self, execution_id: Any) -> dict[str, Any]:
            return {
                "execution_id": str(execution_id),
                "command_type": "OFFLOAD",
                "status": "SUCCESS",
                "command_log_path": str(log_file),
            }

    fast_service = _FastSystemService()
    app = create_app(
        dependencies={
            "job_store": Provide(lambda: store, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "system_service": Provide(lambda: fast_service, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    async with AsyncTestClient(app=app) as client:
        log_resp = await client.get(f"/api/orchestration/executions/{exec_id}/execution-log/")
        assert log_resp.status_code == 200
        body = log_resp.json()
        assert body["is_file"] is True
        assert body["message"].endswith("FINAL_MARKER_LINE\n")

        async def _fire(idx: int) -> int:
            mod = idx % 4
            if mod == 0:
                r = await client.get("/api/system/status/")
                return r.status_code
            if mod == 1:
                r = await client.get("/api/system/schemas/")
                return r.status_code
            if mod == 2:
                r = await client.get("/api/orchestration/executions/")
                return r.status_code
            r = await client.post(
                "/mcp",
                headers={
                    "MCP-Protocol-Version": "2026-07-28",
                    "Mcp-Method": "tools/list",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": idx,
                    "method": "tools/list",
                    "params": {
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                            "io.modelcontextprotocol/clientCapabilities": {},
                        }
                    },
                },
            )
            return r.status_code

        statuses = await asyncio.wait_for(
            asyncio.gather(*(_fire(i) for i in range(64))),
            timeout=5.0,
        )
        assert len(statuses) == 64
        assert all(code < 500 for code in statuses)
        assert statuses.count(200) == 64

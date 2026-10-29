# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Vertebra runtime release-gate verifier (R1-R6)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from goe.listener.vertebra_gate import (
    REQUIRED_WHEEL_PLATFORMS,
    REQUIRED_WHEEL_PYTHON_TAGS,
    VertebraGateReport,
    VertebraReleaseGateError,
    check_r1_asgi_lifespan,
    check_r2_http_methods,
    check_r3_bundled_binary,
    check_r4_concurrency_bridge,
    check_r5_public_supervisor_and_env,
    check_r6_wheel_metadata,
    verify_vertebra_runtime_gate,
)


class _CompliantAsgiRunner:
    """In-memory ASGI runner satisfying R1, R2, and R4 contracts."""

    def __init__(
        self, app: Any, *, drop_lifespan: bool = False, reject_options: bool = False, hang: bool = False
    ) -> None:
        self._app = app
        self._drop_lifespan = drop_lifespan
        self._reject_options = reject_options
        self._hang = hang
        self._state: dict[str, Any] = {}

    async def exercise_lifespan_and_request(self, method: str, path: str) -> tuple[int, bytes]:
        """Run lifespan startup, one HTTP request, and lifespan shutdown."""
        if not self._drop_lifespan:
            await self._run_lifespan_event("lifespan.startup")
        status, body = await self.exercise_request(method, path)
        if not self._drop_lifespan:
            await self._run_lifespan_event("lifespan.shutdown")
        return status, body

    async def exercise_request(self, method: str, path: str) -> tuple[int, bytes]:
        """Dispatch one HTTP request to the mounted ASGI app."""
        if self._hang:
            await asyncio.sleep(10.0)
        if self._reject_options and method in ("OPTIONS", "HEAD"):
            return 405, b""

        status_code = 500
        chunks: list[bytes] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                chunks.append(bytes(message.get("body", b"")))

        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "state": self._state,
        }
        await self._app(scope, receive, send)
        return status_code, b"".join(chunks)

    async def _run_lifespan_event(self, event_type: str) -> None:
        completed = asyncio.Event()

        async def send(message: dict[str, Any]) -> None:
            if message["type"] in ("lifespan.startup.complete", "lifespan.shutdown.complete"):
                completed.set()

        scope = {"type": "lifespan", "state": self._state}
        if event_type == "lifespan.startup":
            msg_sent = False

            async def startup_only_receive() -> dict[str, Any]:
                nonlocal msg_sent
                if not msg_sent:
                    msg_sent = True
                    return {"type": "lifespan.startup"}
                await asyncio.sleep(3600)
                return {"type": "lifespan.shutdown"}

            task = asyncio.create_task(self._app(scope, startup_only_receive, send))
            await asyncio.wait_for(completed.wait(), timeout=1.0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        else:
            sent_steps = 0

            async def shutdown_receive() -> dict[str, Any]:
                nonlocal sent_steps
                sent_steps += 1
                return {"type": "lifespan.shutdown"}

            await self._app(scope, shutdown_receive, send)


@pytest.mark.anyio
async def test_vertebra_gate_individual_criteria_pass_and_fail(tmp_path: Path) -> None:
    """Verify R1-R6 checks pass when compliant and return descriptive failures when violated."""
    r1_ok = await check_r1_asgi_lifespan(runner_factory=lambda app: _CompliantAsgiRunner(app))
    assert r1_ok.passed is True

    r1_fail = await check_r1_asgi_lifespan(runner_factory=lambda app: _CompliantAsgiRunner(app, drop_lifespan=True))
    assert r1_fail.passed is False
    assert "uninitialized" in r1_fail.detail or "events=" in r1_fail.detail

    r2_ok = await check_r2_http_methods(runner_factory=lambda app: _CompliantAsgiRunner(app))
    assert r2_ok.passed is True

    r2_fail = await check_r2_http_methods(runner_factory=lambda app: _CompliantAsgiRunner(app, reject_options=True))
    assert r2_fail.passed is False
    assert "405" in r2_fail.detail

    pkg_root = tmp_path / "vertebra"
    (pkg_root / "bin").mkdir(parents=True)
    r3_missing = check_r3_bundled_binary(package_root=pkg_root)
    assert r3_missing.passed is False

    (pkg_root / "bin" / "vertebra-server").write_bytes(b"\x7fELF")
    r3_ok = check_r3_bundled_binary(package_root=pkg_root)
    assert r3_ok.passed is True

    r4_ok = await check_r4_concurrency_bridge(
        concurrency=64,
        timeout_seconds=2.0,
        runner_factory=lambda app: _CompliantAsgiRunner(app),
    )
    assert r4_ok.passed is True

    r4_timeout = await check_r4_concurrency_bridge(
        concurrency=16,
        timeout_seconds=0.05,
        runner_factory=lambda app: _CompliantAsgiRunner(app, hang=True),
    )
    assert r4_timeout.passed is False
    assert "Deadlock or timeout" in r4_timeout.detail

    valid_sup = SimpleNamespace(__all__=("Supervisor", "run_supervisor"), Supervisor=object, PRESERVES_CALLER_ENV=True)
    r5_ok = check_r5_public_supervisor_and_env(supervisor_module=valid_sup)
    assert r5_ok.passed is True

    empty_sup = SimpleNamespace(__all__=())
    r5_fail = check_r5_public_supervisor_and_env(supervisor_module=empty_sup)
    assert r5_fail.passed is False

    r6_ok = check_r6_wheel_metadata(
        supported_tags=REQUIRED_WHEEL_PYTHON_TAGS,
        supported_platforms=REQUIRED_WHEEL_PLATFORMS,
        vertebra_version="0.2.0",
    )
    assert r6_ok.passed is True

    r6_fail = check_r6_wheel_metadata(
        supported_tags=("cp312",),
        supported_platforms=REQUIRED_WHEEL_PLATFORMS,
        vertebra_version="0.2.0",
    )
    assert r6_fail.passed is False
    assert "cp313" in r6_fail.detail


@pytest.mark.anyio
async def test_verify_vertebra_runtime_gate_aggregate_and_error(tmp_path: Path) -> None:
    """Verify verify_vertebra_runtime_gate returns VertebraGateReport or raises VertebraReleaseGateError."""
    pkg_root = tmp_path / "vertebra"
    (pkg_root / "bin").mkdir(parents=True)
    (pkg_root / "bin" / "vertebra-server").write_bytes(b"binary")
    valid_sup = SimpleNamespace(__all__=("Supervisor",), Supervisor=object, PRESERVES_CALLER_ENV=True)

    report = await verify_vertebra_runtime_gate(
        require_passed=True,
        runner_factory=lambda app: _CompliantAsgiRunner(app),
        package_root=pkg_root,
        supervisor_module=valid_sup,
        supported_tags=REQUIRED_WHEEL_PYTHON_TAGS,
        supported_platforms=REQUIRED_WHEEL_PLATFORMS,
        vertebra_version="0.2.0",
    )
    assert isinstance(report, VertebraGateReport)
    assert report.passed is True
    assert report.failed_ids() == ()

    with pytest.raises(VertebraReleaseGateError) as exc_info:
        await verify_vertebra_runtime_gate(
            require_passed=True,
            runner_factory=lambda app: _CompliantAsgiRunner(app, drop_lifespan=True, reject_options=True),
            package_root=tmp_path / "empty_pkg",
            supervisor_module=SimpleNamespace(__all__=()),
            supported_tags=("cp312",),
            supported_platforms=REQUIRED_WHEEL_PLATFORMS,
            vertebra_version="0.2.0",
        )
    failed_ids = exc_info.value.report.failed_ids()
    assert {"R1", "R2", "R3", "R5", "R6"}.issubset(set(failed_ids))

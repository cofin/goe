# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe.orchestration.context."""

from __future__ import annotations

import asyncio
import gc
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from goe.orchestration.context import (
    ExecutionContext,
    bind_execution_context,
    current_execution_context,
)
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.sinks import NORMAL, VERBOSE, LogEvent


def test_execution_context_is_frozen_and_gc_untracked() -> None:
    """Verify ExecutionContext is immutable and omitted from cyclic garbage collection."""
    ctx = ExecutionContext.for_console(detail=NORMAL, ansi=False, include_telemetry=False)
    assert not gc.is_tracked(ctx)
    with pytest.raises(AttributeError):
        ctx.detail = VERBOSE  # type: ignore[misc]


def test_bind_execution_context_nesting_restores_previous() -> None:
    """Verify nested bind_execution_context scopes restore the outer context on exit."""
    assert current_execution_context() is None
    ctx1 = ExecutionContext.for_console(detail=NORMAL, include_telemetry=False)
    ctx2 = ExecutionContext.for_console(detail=VERBOSE, include_telemetry=False)

    with bind_execution_context(ctx1):
        assert current_execution_context() is ctx1
        with bind_execution_context(ctx2):
            assert current_execution_context() is ctx2
        assert current_execution_context() is ctx1
    assert current_execution_context() is None


def test_execution_context_thread_pool_isolation(tmp_path: Path) -> None:
    """Verify 4 concurrent threads each write exclusively to their own ExecutionContext sinks."""

    def _worker(worker_idx: int) -> tuple[str, str]:
        buf = io.StringIO()
        exec_id = ExecutionId()
        ctx = ExecutionContext.for_console(
            detail=VERBOSE,
            ansi=False,
            execution_id=exec_id,
            stream=buf,
            include_telemetry=False,
        ).with_log_file(f"WORKER_{worker_idx}", log_dir=str(tmp_path))
        try:
            with bind_execution_context(ctx):
                for step in range(25):
                    active = current_execution_context()
                    assert active is ctx
                    active.emit(LogEvent(line=f"w{worker_idx}-line-{step}", detail=NORMAL))
        finally:
            ctx.close()
        assert ctx.log_file_sink is not None
        assert ctx.log_file_sink.name is not None
        return buf.getvalue(), Path(ctx.log_file_sink.name).read_text(encoding="utf-8")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_worker, range(4)))

    for idx, (console_out, file_out) in enumerate(results):
        for step in range(25):
            assert f"w{idx}-line-{step}\n" in console_out
            assert f"w{idx}-line-{step}\n" in file_out
        for other_idx in range(4):
            if other_idx != idx:
                assert f"w{other_idx}-line-" not in console_out
                assert f"w{other_idx}-line-" not in file_out


def test_execution_context_asyncio_task_isolation() -> None:
    """Verify concurrent asyncio tasks maintain isolated ExecutionContext bindings."""

    async def _coro(task_id: int) -> str:
        buf = io.StringIO()
        ctx = ExecutionContext.for_console(detail=NORMAL, stream=buf, include_telemetry=False)
        with bind_execution_context(ctx):
            for idx in range(10):
                await asyncio.sleep(0)
                active = current_execution_context()
                assert active is ctx
                active.emit(LogEvent(line=f"async-{task_id}-{idx}", detail=NORMAL))
        return buf.getvalue()

    async def _run_all() -> list[str]:
        return list(await asyncio.gather(*(_coro(i) for i in range(4))))

    outputs = asyncio.run(_run_all())
    for task_id, out in enumerate(outputs):
        assert f"async-{task_id}-0\n" in out
        assert f"async-{task_id}-9\n" in out
        for other_id in range(4):
            if other_id != task_id:
                assert f"async-{other_id}-" not in out

---
type: Task
id: embedded_listener_and_task_execution_20260826:native_task_execution
title: Implement Accelerator-Pattern WorkerPlugin, Jobs Registry & Continuous Worker Runner
description: Implement WorkerPlugin (CLIPlugin, InitPluginProtocol), in-process @task decorator, CronParser, task registry, and continuous worker loop modeled on dma/accelerator, replacing QueuePlugin and litestar-queues.
state: open
created_at: "2026-08-26T21:20:00Z"
updated_at: "2026-08-26T21:23:00Z"
tags:
  - litestar
  - worker
  - accelerator-pattern
  - jobs
  - background-tasks
depends_on:
  - embedded_listener_and_task_execution_20260826:embedded_memory_cache
files:
  - src/goe/listener/jobs.py
  - src/goe/listener/worker.py
  - src/goe/listener/controllers/orchestration.py
  - src/goe/listener/app.py
tests:
  - tests/unit/listener/test_jobs.py
  - tests/unit/listener/test_orchestration_controllers.py
verification_strategy: behavior_tdd
---

# Task: Implement Accelerator-Pattern WorkerPlugin, Jobs Registry & Continuous Worker Runner

## Objective
Model the GOE Listener's worker and task execution architecture directly on `~/code/dma/accelerator` (`src/py/dma/utils/worker/` and `src/py/dma/lib/jobs.py`):
1. **`WorkerPlugin(CLIPlugin, InitPluginProtocol)`**: Hooks into Granian's `server_lifespan` in `src/goe/listener/app.py` to own and supervise the worker child process when `goe listener start` runs, and supports standalone execution via `goe listener start --worker-only`.
2. **`goe.listener.jobs`**: `@task` decorator, `Task` wrapper, `CronParser`, in-process registry `_job_registry`, and progress beat tracking (`beat()`).
3. **Continuous Worker Loop**: `run_continuous_worker` in `src/goe/listener/worker.py` polling and executing registered tasks (offload operations, heartbeats, schema syncs).
4. **`OrchestrationController`**: Dispatches offload tasks into the native task runner and returns `Response[schemas.CommandScheduled]`.

## Implementation Details

### 1. `src/goe/listener/jobs.py`
Implement `Task`, `@task` decorator, `CronParser`, and progress `beat()` sink:
```python
"""Job function registry for background tasks (DMA Accelerator Pattern)."""

from collections.abc import Callable
import contextlib
import contextvars
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import inspect
from typing import Any, Literal
from uuid import UUID

from goe.listener.services.orchestrate import orchestration_runner
from goe.orchestration.execution_id import ExecutionId

_job_registry: dict[str, "Task"] = {}
_current_beat_sink: contextvars.ContextVar[Callable[[str | None], None] | None] = contextvars.ContextVar(
    "goe_beat_sink", default=None
)


def beat(detail: str | None = None) -> None:
    """Record a progress point for the currently running job."""
    sink = _current_beat_sink.get()
    if sink is None:
        return
    with contextlib.suppress(Exception):
        sink(detail)


class CronParser:
    """Cron expression parser supporting standard 5-part cron syntax and aliases."""

    ALIASES = {
        "@yearly": "0 0 1 1 *",
        "@monthly": "0 0 1 * *",
        "@weekly": "0 0 * * 0",
        "@daily": "0 0 * * *",
        "@hourly": "0 * * * *",
    }

    def __init__(self, cron_expr: str) -> None:
        if cron_expr in self.ALIASES:
            cron_expr = self.ALIASES[cron_expr]
        self.cron_expr = cron_expr
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}")
        self.parts = parts


@dataclass
class Task:
    """Wrapped task definition."""

    fn: Callable[..., Any]
    name: str
    queue: str = "default"
    timeout: int = 3600
    interval: timedelta | None = None
    cron: str | None = None

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutinefunction(self.fn):
            return await self.fn(*args, **kwargs)
        return self.fn(*args, **kwargs)


def task(
    name: str,
    *,
    queue: str = "default",
    timeout: int = 3600,
    interval: timedelta | None = None,
    cron: str | None = None,
) -> Callable[[Callable[..., Any]], Task]:
    """Decorator to register a task in the in-process job registry."""

    def decorator(fn: Callable[..., Any]) -> Task:
        t = Task(fn=fn, name=name, queue=queue, timeout=timeout, interval=interval, cron=cron)
        _job_registry[name] = t
        return t

    return decorator


def get_job_registry() -> dict[str, Task]:
    """Return registered jobs."""
    return _job_registry


# Built-in background jobs
@task("orchestration.offload", queue="orchestration", timeout=86400)
async def run_offload_job(params: dict[str, Any], execution_id: str) -> dict[str, Any]:
    """Execute an offload operation asynchronously in background."""
    beat(f"Starting offload for execution {execution_id}")
    execution_identifier = ExecutionId.from_str(execution_id)
    orchestration_runner.offload(params=params, execution_id=execution_identifier)
    beat(f"Completed offload for execution {execution_id}")
    return {"execution_id": execution_id, "status": "COMPLETED"}


@task("system.heartbeat", queue="system", interval=timedelta(seconds=30))
async def system_heartbeat_job() -> dict[str, str]:
    """Publish periodic heartbeat check for active listener nodes."""
    return {"status": "HEALTHY"}


@task("system.sync_schemas", queue="system", interval=timedelta(minutes=15))
async def sync_schemas_job() -> dict[str, str]:
    """Synchronize metadata schemas in background."""
    return {"status": "SYNCED"}
```

### 2. `src/goe/listener/worker.py` (WorkerPlugin & Runner)
```python
"""WorkerPlugin and continuous background worker runner (DMA Accelerator Pattern)."""

import asyncio
from contextlib import contextmanager
import logging
import multiprocessing
from typing import TYPE_CHECKING, Iterator, Literal

from litestar.plugins import CLIPlugin, InitPluginProtocol

from goe.listener.jobs import get_job_registry

if TYPE_CHECKING:
    from click import Group
    from litestar import Litestar
    from litestar.config.app import AppConfig

logger = logging.getLogger(__name__)


def _worker_child_main() -> None:
    """Fresh process entrypoint for server-owned worker."""
    asyncio.run(run_continuous_worker())


async def run_continuous_worker() -> None:
    """Continuous worker execution loop."""
    logger.info("Starting GOE continuous task worker")
    registry = get_job_registry()
    logger.info("Loaded %d registered tasks", len(registry))
    while True:
        await asyncio.sleep(1.0)


class WorkerPlugin(CLIPlugin, InitPluginProtocol):
    """Litestar plugin managing worker process lifecycle within Granian server lifespan."""

    def __init__(self, placement: Literal["server", "external"] = "server") -> None:
        self.placement = placement
        self._worker_process: multiprocessing.Process | None = None

    def on_cli_init(self, cli: "Group") -> None:
        pass

    def on_app_init(self, app_config: "AppConfig") -> "AppConfig":
        return app_config

    @contextmanager
    def server_lifespan(self, app: "Litestar") -> Iterator[None]:
        if self.placement != "server":
            yield
            return
        self._start_worker_process()
        try:
            yield
        finally:
            self._stop_worker_process()

    def _start_worker_process(self) -> None:
        if self._worker_process is not None and self._worker_process.is_alive():
            return
        ctx = multiprocessing.get_context("spawn")
        self._worker_process = ctx.Process(target=_worker_child_main, name="goe-worker")
        self._worker_process.start()
        logger.info("Started server-owned worker process [PID %d]", self._worker_process.pid)

    def _stop_worker_process(self) -> None:
        if self._worker_process and self._worker_process.is_alive():
            self._worker_process.terminate()
            self._worker_process.join(timeout=5.0)
            if self._worker_process.is_alive():
                self._worker_process.kill()
            logger.info("Stopped worker process")
        self._worker_process = None
```

### 3. `src/goe/listener/controllers/orchestration.py`
```python
from litestar.background_tasks import BackgroundTask
from litestar.response import Response

@post("/offload/")
async def execute_offload_command(
    self,
    data: schemas.OffloadOptions,
) -> Response[schemas.CommandScheduled]:
    """Submit a background offload operation."""
    utils.orchestrate.check_for_running_command(data.owner_table)
    execution_identifier = ExecutionId()
    params = {k: v for k, v in msgspec.structs.asdict(data).items() if v is not None}

    # Dispatch background execution natively via Litestar BackgroundTask
    return Response(
        schemas.CommandScheduled(execution_id=str(execution_identifier.id)),
        background=BackgroundTask(
            jobs.run_offload_job,
            params=params,
            execution_id=execution_identifier.as_str(),
        ),
    )
```

### 4. `src/goe/listener/app.py`
Replace `QueuePlugin` with `WorkerPlugin`:
```python
plugins=[
    GranianPlugin(),
    WorkerPlugin(placement="server"),
    LitestarMCP(MCPConfig(name="GOE Listener MCP")),
    AutowirePlugin(AutowireConfig(domain_packages=["goe.listener"])),
]
```

## Implementation Checklist
- [ ] Implement `Task`, `@task`, `CronParser`, `beat()` and `_job_registry` in `src/goe/listener/jobs.py`.
- [ ] Implement `WorkerPlugin(CLIPlugin, InitPluginProtocol)` and `run_continuous_worker` in `src/goe/listener/worker.py`.
- [ ] Update `OrchestrationController.execute_offload_command` in `src/goe/listener/controllers/orchestration.py`.
- [ ] Register `WorkerPlugin` and remove `QueuePlugin` in `src/goe/listener/app.py`.
- [ ] Author unit tests in `tests/unit/listener/test_jobs.py` testing job registration, cron parsing, and task execution.

## Verification Strategy
- **Command:**
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_jobs.py tests/unit/listener/test_orchestration_controllers.py
  ```
- **Success Criteria:** `POST /api/orchestration/offload/` returns 200/201, schedules background execution, and completes without external queue daemons.

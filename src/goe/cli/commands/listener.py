# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe listener' subcommand group for REST API and background worker management."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import rich_click as click

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.cli.common import common_options, extract_common_options
from goe.cli.console import print_info, print_success, print_warning

if TYPE_CHECKING:
    import httpx

    from goe.listener.config import settings
    from goe.listener.jobs.store import create_job_store
    from goe.listener.jobs.worker import DurableJobWorker
    from goe.listener.vertebra_gate import verify_vertebra_runtime_gate
    from goe.platform.worker import CgroupQuota

__all__ = (
    "build_vertebra_command",
    "listener",
    "start",
    "status",
)

_LAZY_IMPORTS: LazyImportMap = {
    "CgroupQuota": ("goe.platform.worker", "CgroupQuota"),
    "DurableJobWorker": ("goe.listener.jobs.worker", "DurableJobWorker"),
    "create_job_store": ("goe.listener.jobs.store", "create_job_store"),
    "httpx": ("httpx", None),
    "settings": ("goe.listener.config", "settings"),
    "verify_vertebra_runtime_gate": ("goe.listener.vertebra_gate", "verify_vertebra_runtime_gate"),
}


def build_vertebra_command(
    *,
    host: str,
    port: int,
    workers: int,
    threads: int = 1,
    topology: str = "shm",
    drain_timeout: int = 30,
    shutdown_timeout: int = 35,
    ssl_enabled: bool = False,
    certfile: str | None = None,
    keyfile: str | None = None,
    reload: bool = False,
    app_target: str = "goe.listener.asgi:app",
) -> list[str]:
    """Construct the Vertebra CLI command line for the GOE Listener ASGI service."""
    cmd = [
        sys.executable,
        "-m",
        "vertebra",
        "run",
        app_target,
        "--interface",
        "asgi",
        "--topology",
        str(topology),
        "--host",
        str(host),
        "--port",
        str(port),
        "--workers",
        str(workers),
        "--threads",
        str(threads),
        "--drain-timeout",
        str(drain_timeout),
        "--shutdown-timeout",
        str(shutdown_timeout),
    ]
    if ssl_enabled:
        if certfile:
            cmd.extend(["--tls-cert", str(certfile)])
        if keyfile:
            cmd.extend(["--tls-key", str(keyfile)])
    if reload:
        cmd.append("--reload")
    return cmd


@click.group(
    name="listener",
    help="Manage GOE Listener REST service and background workers.",
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.option(
    "--host",
    default=None,
    help="Bind host interface (defaults to OFFLOAD_LISTENER_HOST or 127.0.0.1).",
)
@click.option(
    "-p",
    "--port",
    type=int,
    default=None,
    help="Bind TCP port (defaults to OFFLOAD_LISTENER_PORT or 8000).",
)
@click.option(
    "-w",
    "--workers",
    type=int,
    default=None,
    help="Number of worker processes (defaults to OFFLOAD_LISTENER_HTTP_WORKERS or CgroupQuota).",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development.",
)
@click.option(
    "--worker-only",
    is_flag=True,
    help="Run only the durable background job worker process.",
)
@common_options
@click.pass_context
def listener(
    ctx: click.Context,
    host: str | None = None,
    port: int | None = None,
    workers: int | None = None,
    reload: bool = False,
    worker_only: bool = False,
    **kwargs: Any,
) -> None:
    """Listener service control group."""
    extract_common_options(ctx, kwargs)
    ctx.ensure_object(dict)
    ctx.obj["listener_host"] = host
    ctx.obj["listener_port"] = port
    ctx.obj["listener_workers"] = workers
    ctx.obj["listener_reload"] = reload
    ctx.obj["listener_worker_only"] = worker_only
    if ctx.invoked_subcommand is None:
        _start_listener_server(
            host=host,
            port=port,
            workers=workers,
            reload=reload,
            worker_only=worker_only,
        )


@listener.command(
    name="start",
    help="Start GOE Listener ASGI server and embedded background worker.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--host",
    default=None,
    help="Bind host interface (defaults to OFFLOAD_LISTENER_HOST or 127.0.0.1).",
)
@click.option(
    "-p",
    "--port",
    type=int,
    default=None,
    help="Bind TCP port (defaults to OFFLOAD_LISTENER_PORT or 8000).",
)
@click.option(
    "-w",
    "--workers",
    type=int,
    default=None,
    help="Number of worker processes (defaults to OFFLOAD_LISTENER_HTTP_WORKERS or CgroupQuota).",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development.",
)
@click.option(
    "--worker-only",
    is_flag=True,
    help="Run only the durable background job worker process.",
)
@common_options
@click.pass_context
def start(
    ctx: click.Context,
    host: str | None = None,
    port: int | None = None,
    workers: int | None = None,
    reload: bool = False,
    worker_only: bool = False,
    **kwargs: Any,
) -> None:
    """Start listener HTTP server or background worker."""
    extract_common_options(ctx, kwargs)
    parent_obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    _start_listener_server(
        host=host if host is not None else parent_obj.get("listener_host"),
        port=port if port is not None else parent_obj.get("listener_port"),
        workers=workers if workers is not None else parent_obj.get("listener_workers"),
        reload=bool(reload or parent_obj.get("listener_reload", False)),
        worker_only=bool(worker_only or parent_obj.get("listener_worker_only", False)),
    )


@listener.command(
    name="status",
    help="Check status of running GOE Listener service.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@common_options
@click.pass_context
def status(ctx: click.Context, **kwargs: Any) -> None:
    """Check listener operational status via the health endpoint."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    extract_common_options(ctx, kwargs)
    url = f"http://{settings.host}:{settings.port}/api/system/status/"
    print_info(f"Checking GOE Listener status at {url}...")
    try:
        response = httpx.get(url, timeout=2.0)
        if response.status_code == 200:
            print_success(f"GOE Listener is healthy ({response.text}).")
        else:
            print_warning(f"GOE Listener returned status {response.status_code}.")
    except Exception:
        print_warning("GOE Listener is not reachable.")


def __getattr__(name: str) -> Any:
    """Lazily import runtime dependencies and listener settings on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)


def _start_listener_server(
    host: str | None = None,
    port: int | None = None,
    workers: int | None = None,
    reload: bool = False,
    worker_only: bool = False,
) -> None:
    """Start the Vertebra ASGI server or standalone durable background job worker process."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    resolved_host = host if host is not None else settings.host
    resolved_port = int(port) if port is not None else int(settings.port)
    if workers is not None:
        resolved_workers = int(workers)
    elif "OFFLOAD_LISTENER_HTTP_WORKERS" in os.environ:
        resolved_workers = int(settings.http_workers)
    else:
        resolved_workers = int(CgroupQuota.detect().recommended_workers)

    if worker_only:
        print_info("Starting GOE Listener durable job worker process...")
        store = create_job_store()
        worker = DurableJobWorker(
            store=store,
            heartbeat_interval_seconds=float(settings.heartbeat_interval),
        )
        asyncio.run(worker.run_forever())
        return

    asyncio.run(verify_vertebra_runtime_gate(require_passed=True))
    cmd = build_vertebra_command(
        host=resolved_host,
        port=resolved_port,
        workers=resolved_workers,
        threads=int(settings.threads),
        topology=str(settings.topology),
        drain_timeout=int(settings.drain_timeout_seconds),
        shutdown_timeout=int(settings.shutdown_timeout_seconds),
        ssl_enabled=bool(settings.ssl_enabled),
        certfile=settings.certfile,
        keyfile=settings.keyfile,
        reload=bool(reload or settings.reload),
    )
    env = settings.to_vertebra_env(os.environ)
    if host is not None or "VERTEBRA_HOST" not in os.environ:
        env["VERTEBRA_HOST"] = str(resolved_host)
    if port is not None or "VERTEBRA_PORT" not in os.environ:
        env["VERTEBRA_PORT"] = str(resolved_port)
    if workers is not None or "VERTEBRA_WORKERS" not in os.environ:
        env["VERTEBRA_WORKERS"] = str(resolved_workers)
    print_info(f"Starting GOE Listener on http://{resolved_host}:{resolved_port} with {resolved_workers} worker(s)...")
    subprocess.run(cmd, env=env, check=True)

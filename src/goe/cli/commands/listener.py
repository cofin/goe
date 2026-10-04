# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe listener' subcommand group for REST API and background worker management."""

from typing import Any

import httpx
import rich_click as click
from granian import Granian
from granian.constants import Interfaces

from goe.cli.common import common_options, extract_common_options
from goe.cli.console import print_info, print_success, print_warning
from goe.listener.config import settings


def _start_listener_server(
    host: str | None = None,
    port: int | None = None,
    workers: int | None = None,
    reload: bool = False,
    worker_only: bool = False,
) -> None:
    """Start the Granian ASGI server or background worker process."""
    resolved_host = host if host is not None else settings.host
    resolved_port = port if port is not None else int(settings.port)
    resolved_workers = workers if workers is not None else int(settings.http_workers)

    if worker_only:
        print_info("Starting GOE Listener worker process...")
        return

    print_info(f"Starting GOE Listener on http://{resolved_host}:{resolved_port} with {resolved_workers} worker(s)...")
    server = Granian(
        "goe.listener.asgi:app",
        address=resolved_host,
        port=resolved_port,
        interface=Interfaces.ASGI,
        workers=resolved_workers,
        reload=reload,
    )
    server.serve()


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
    help="Number of worker processes (defaults to OFFLOAD_LISTENER_HTTP_WORKERS or 1).",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development.",
)
@click.option(
    "--worker-only",
    is_flag=True,
    help="Run only the background worker process.",
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
    help="Number of worker processes (defaults to OFFLOAD_LISTENER_HTTP_WORKERS or 1).",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development.",
)
@click.option(
    "--worker-only",
    is_flag=True,
    help="Run only the background worker process.",
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
    _start_listener_server(
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        worker_only=worker_only,
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

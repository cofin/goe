# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe listener' subcommand group for REST API and background worker management."""

import rich_click as click
from granian import Granian
from granian.constants import Interfaces

from goe.cli.console import print_info


@click.group(
    name="listener",
    help="Manage GOE Listener REST service and background workers.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
def listener() -> None:
    """Listener service control group."""
    pass


@listener.command(
    name="start",
    help="Start GOE Listener ASGI server or background worker.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Bind host interface.",
)
@click.option(
    "--port",
    type=int,
    default=8000,
    show_default=True,
    help="Bind TCP port.",
)
@click.option(
    "--workers",
    type=int,
    default=1,
    show_default=True,
    help="Number of worker processes.",
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
def start(host: str, port: int, workers: int, reload: bool, worker_only: bool = False) -> None:
    """Start listener HTTP server or background worker."""
    if worker_only:
        print_info("Starting GOE Listener worker process...")
        return

    print_info(f"Starting GOE Listener on http://{host}:{port} with {workers} worker(s)...")
    server = Granian(
        "goe.listener.asgi:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        workers=workers,
        reload=reload,
    )
    server.serve()


@listener.command(
    name="status",
    help="Check status of running GOE Listener service.",
)
def status() -> None:
    """Check listener operational status."""
    print_info("Checking GOE Listener status...")

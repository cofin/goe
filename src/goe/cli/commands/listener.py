# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""'goe listener' subcommand group for REST API and background worker management."""

import rich_click as click
import uvicorn

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
    help="Start GOE Listener ASGI server.",
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
def start(host: str, port: int, workers: int, reload: bool) -> None:
    """Start listener HTTP server with Granian or Uvicorn."""
    print_info(f"Starting GOE Listener on http://{host}:{port} with {workers} worker(s)...")
    try:
        from granian.constants import Interfaces
        from granian.server import Granian

        server = Granian(
            "goe.listener.asgi:app",
            address=host,
            port=port,
            interface=Interfaces.ASGI,
            workers=workers,
            reload=reload,
        )
        server.serve()
    except ImportError:
        import uvicorn

        uvicorn.run(
            "goe.listener.asgi:app",
            host=host,
            port=port,
            workers=workers,
            reload=reload,
        )


@listener.command(
    name="status",
    help="Check status of running GOE Listener service.",
)
def status() -> None:
    """Check listener operational status."""
    print_info("Checking GOE Listener status...")

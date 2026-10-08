# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Granian ASGI server runner for GOE Listener."""

from granian import Granian
from granian.constants import Interfaces

from goe.listener.config.application import settings


def run_granian_server(
    host: str | None = None,
    port: int | None = None,
    workers: int | None = None,
    reload: bool | None = None,
) -> None:
    """Start the GOE Listener using the Granian ASGI server runtime."""
    resolved_host = host if host is not None else settings.host
    resolved_port = int(port if port is not None else settings.port)
    resolved_workers = int(workers if workers is not None else settings.http_workers)
    resolved_reload = bool(reload if reload is not None else settings.reload)

    server = Granian(
        "goe.listener.asgi:app",
        address=resolved_host,
        port=resolved_port,
        interface=Interfaces.ASGI,
        workers=resolved_workers,
        reload=resolved_reload,
    )
    server.serve()

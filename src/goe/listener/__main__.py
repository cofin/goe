#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Application ASGI entrypoint for GOE Listener."""

from goe.listener.config.application import settings
from goe.listener.server import run_granian_server


def run_listener(
    host: str = settings.host,
    port: int = settings.port,
    workers: int = settings.http_workers,
    reload: bool = settings.reload,
) -> None:
    """Run GOE Listener using Granian ASGI server."""
    run_granian_server(host=host, port=port, workers=workers, reload=reload)


if __name__ == "__main__":
    run_listener()

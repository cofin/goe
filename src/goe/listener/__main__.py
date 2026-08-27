#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Application Web Server Gateway Interface - gunicorn."""

# GOE
from goe.listener.config.application import settings
from goe.listener.wsgi import run_wsgi


def run_listener(
    host: str = settings.host,
    port: int = settings.port,
    workers: int = settings.http_workers,
):
    """Run GOE Listener."""
    run_wsgi(host, port, workers)


if __name__ == "__main__":
    run_listener()

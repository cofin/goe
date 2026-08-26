# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Litestar application factory for GOE Listener."""

from typing import Any

from litestar import Litestar
from litestar.config.compression import CompressionConfig
from litestar.config.cors import CORSConfig
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import SwaggerRenderPlugin
from litestar_autowire import AutowireConfig, AutowirePlugin
from litestar_granian import GranianPlugin
from litestar_mcp import LitestarMCP, MCPConfig
from litestar_queues import QueueConfig, QueuePlugin, WorkerConfig

from goe.listener.exceptions.handlers import (
    generic_exception_handler,
    http_exception_handler,
)
from goe.listener.services.system import SystemService
from goe.util.goe_version import goe_version


def create_app(dependencies: dict[str, Any] | None = None) -> Litestar:
    """Create and configure the Litestar application instance."""
    deps: dict[str, Any] = {
        "system_service": Provide(SystemService, sync_to_thread=False),
    }
    if dependencies:
        deps.update(dependencies)

    return Litestar(
        exception_handlers={
            HTTPException: http_exception_handler,
            Exception: generic_exception_handler,
        },
        dependencies=deps,
        plugins=[
            GranianPlugin(),
            QueuePlugin(QueueConfig(queue_backend="memory", worker=WorkerConfig(placement="asgi"))),
            LitestarMCP(MCPConfig(name="GOE Listener MCP")),
            AutowirePlugin(AutowireConfig(domain_packages=["goe.listener"])),
        ],
        cors_config=CORSConfig(
            allow_origins=["*"],
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        ),
        compression_config=CompressionConfig(backend="gzip"),
        openapi_config=OpenAPIConfig(
            title="GOE Listener REST API",
            version=goe_version(),
            description="REST service and orchestration engine for Gluent Offload Engine.",
            render_plugins=[SwaggerRenderPlugin(path="/docs")],
        ),
    )


app = create_app()

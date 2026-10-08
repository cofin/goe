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
from litestar_queues import QueueConfig, QueuePlugin, WorkerConfig
from litestar_security import SecurityPlugin

from goe.config.config_file import load_env
from goe.listener.exceptions.handlers import (
    generic_exception_handler,
    http_exception_handler,
)
from goe.listener.mcp import build_mcp_plugin
from goe.listener.security import build_security_config
from goe.listener.services.system import get_system_service
from goe.util.goe_version import goe_version


def create_app(dependencies: dict[str, Any] | None = None) -> Litestar:
    """Create and configure the Litestar application instance."""
    load_env()
    deps: dict[str, Any] = {
        "system_service": Provide(get_system_service, sync_to_thread=False),
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
            SecurityPlugin(build_security_config()),
            GranianPlugin(),
            QueuePlugin(QueueConfig(queue_backend="memory", worker=WorkerConfig(placement="asgi"))),
            build_mcp_plugin(),
            AutowirePlugin(AutowireConfig(domain_packages=["goe.listener"], integrations=["queues"])),
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

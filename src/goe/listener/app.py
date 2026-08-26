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

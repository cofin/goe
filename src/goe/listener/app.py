# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Litestar application factory for GOE Listener."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from litestar import Litestar
from litestar.config.compression import CompressionConfig
from litestar.config.cors import CORSConfig
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import SwaggerRenderPlugin
from litestar_autowire import AutowireConfig, AutowirePlugin
from litestar_mcp import LitestarMCP
from litestar_security import SecurityPlugin

from goe.config.config_file import load_env
from goe.listener.cache import ListenerCache, ListenerCacheSink, get_listener_cache
from goe.listener.config import settings
from goe.listener.exceptions.handlers import (
    generic_exception_handler,
    http_exception_handler,
)
from goe.listener.jobs.store import JobStoreProtocol, create_job_store
from goe.listener.jobs.worker import DurableJobWorker
from goe.listener.mcp import ConfirmationGate, build_mcp_config
from goe.listener.security import build_security_config
from goe.listener.services.system import get_system_service
from goe.listener.telemetry import build_listener_otel_plugin
from goe.observability.runtime import ensure_observability
from goe.util import goe_version
from goe.util.module_loader import import_optional

__all__ = (
    "app",
    "create_app",
    "get_confirmation_gate",
    "get_job_store",
)

_default_job_store: JobStoreProtocol | None = None


def get_job_store() -> JobStoreProtocol:
    """Return a lazily initialized process-wide JobStoreProtocol instance."""
    global _default_job_store
    if _default_job_store is None:
        _default_job_store = create_job_store()
    return _default_job_store


def get_confirmation_gate() -> ConfirmationGate:
    """Return a ConfirmationGate bound to active ListenerSettings."""
    return ConfirmationGate()


def create_app(
    dependencies: dict[str, Any] | None = None,
    *,
    startup_hooks: Sequence[Callable[[Litestar], Awaitable[None] | None]] = (),
    enable_background_worker: bool = True,
) -> Litestar:
    """Create and configure the Litestar application instance."""
    load_env()
    telemetry = ensure_observability()
    deps: dict[str, Any] = {
        "system_service": Provide(get_system_service, sync_to_thread=False),
        "listener_cache": Provide(get_listener_cache, sync_to_thread=False),
        "job_store": Provide(get_job_store, sync_to_thread=False),
        "confirmation_gate": Provide(get_confirmation_gate, sync_to_thread=False),
    }
    if dependencies:
        deps.update(dependencies)

    plugins: list[Any] = [
        SecurityPlugin(build_security_config()),
    ]
    vertebra_litestar = import_optional("vertebra.extensions.litestar")
    if vertebra_litestar is not None and hasattr(vertebra_litestar, "LitestarPlugin"):
        plugins.append(vertebra_litestar.LitestarPlugin())

    plugins.extend(
        [
            LitestarMCP(build_mcp_config()),
            AutowirePlugin(AutowireConfig(domain_packages=["goe.listener"])),
        ]
    )
    otel_plugin = build_listener_otel_plugin(telemetry)
    if otel_plugin is not None:
        plugins.append(otel_plugin)

    @asynccontextmanager
    async def _lifespan(app_instance: Litestar) -> AsyncIterator[None]:
        for hook in startup_hooks:
            outcome = hook(app_instance)
            if inspect.isawaitable(outcome):
                await outcome

        cache = ListenerCache()
        store = get_job_store()
        worker = DurableJobWorker(
            store=store,
            heartbeat_interval_seconds=float(settings.heartbeat_interval),
            sinks_factory=lambda record: (ListenerCacheSink(cache, record.table_key),),
        )
        app_instance.state.listener_cache = cache
        app_instance.state.job_store = store
        app_instance.state.job_worker = worker
        if enable_background_worker:
            worker.start()
        try:
            yield
        finally:
            await worker.stop()

    return Litestar(
        lifespan=[_lifespan],
        exception_handlers={
            HTTPException: http_exception_handler,
            Exception: generic_exception_handler,
        },
        dependencies=deps,
        plugins=plugins,
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

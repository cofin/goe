# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe listener' subcommand group for REST API, MCP transports, and background worker management."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import rich_click as click
from rich.table import Table

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.cli.common import common_options, extract_common_options
from goe.cli.console import console, print_info, print_success, print_warning

if TYPE_CHECKING:
    import httpx2 as httpx
    from litestar_mcp import LitestarMCP
    from litestar_mcp.mcp.bridge import run_stdio_streamable_http_bridge
    from litestar_mcp.mcp.stdio import MCPStdioContext, run_stdio

    from goe.listener.app import create_app
    from goe.listener.config import settings
    from goe.listener.jobs.store import create_job_store
    from goe.listener.jobs.worker import DurableJobWorker
    from goe.listener.vertebra_gate import verify_vertebra_runtime_gate
    from goe.platform.worker import CgroupQuota
    from goe.serializers import encode_json

__all__ = (
    "bridge",
    "build_vertebra_command",
    "inspect",
    "listener",
    "mcp",
    "start",
    "status",
    "stdio",
)

_LAZY_IMPORTS: LazyImportMap = {
    "CgroupQuota": ("goe.platform.worker", "CgroupQuota"),
    "DurableJobWorker": ("goe.listener.jobs.worker", "DurableJobWorker"),
    "LitestarMCP": ("litestar_mcp", "LitestarMCP"),
    "MCPStdioContext": ("litestar_mcp.mcp.stdio", "MCPStdioContext"),
    "create_app": ("goe.listener.app", "create_app"),
    "create_job_store": ("goe.listener.jobs.store", "create_job_store"),
    "encode_json": ("goe.serializers", "encode_json"),
    "httpx": ("httpx2", None),
    "httpx2": ("httpx2", None),
    "run_stdio": ("litestar_mcp.mcp.stdio", "run_stdio"),
    "run_stdio_streamable_http_bridge": ("litestar_mcp.mcp.bridge", "run_stdio_streamable_http_bridge"),
    "settings": ("goe.listener.config", "settings"),
    "verify_vertebra_runtime_gate": ("goe.listener.vertebra_gate", "verify_vertebra_runtime_gate"),
}


def build_vertebra_command(
    *,
    host: str,
    port: int,
    workers: int,
    threads: int = 1,
    topology: str = "shm",
    drain_timeout: int = 30,
    shutdown_timeout: int = 35,
    ssl_enabled: bool = False,
    certfile: str | None = None,
    keyfile: str | None = None,
    reload: bool = False,
    app_target: str = "goe.listener.asgi:app",
) -> list[str]:
    """Construct the Vertebra CLI command line for the GOE Listener ASGI service."""
    cmd = [
        sys.executable,
        "-m",
        "vertebra",
        "run",
        app_target,
        "--interface",
        "asgi",
        "--topology",
        str(topology),
        "--host",
        str(host),
        "--port",
        str(port),
        "--workers",
        str(workers),
        "--threads",
        str(threads),
        "--drain-timeout",
        str(drain_timeout),
        "--shutdown-timeout",
        str(shutdown_timeout),
    ]
    if ssl_enabled:
        if certfile:
            cmd.extend(["--tls-cert", str(certfile)])
        if keyfile:
            cmd.extend(["--tls-key", str(keyfile)])
    if reload:
        cmd.append("--reload")
    return cmd


@click.group(
    name="listener",
    help="Manage GOE Listener REST service, MCP transports, and background workers.",
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
    help="Number of worker processes (defaults to OFFLOAD_LISTENER_HTTP_WORKERS or CgroupQuota).",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development.",
)
@click.option(
    "--worker-only",
    is_flag=True,
    help="Run only the durable background job worker process.",
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
    ctx.ensure_object(dict)
    ctx.obj["listener_host"] = host
    ctx.obj["listener_port"] = port
    ctx.obj["listener_workers"] = workers
    ctx.obj["listener_reload"] = reload
    ctx.obj["listener_worker_only"] = worker_only
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
    help="Number of worker processes (defaults to OFFLOAD_LISTENER_HTTP_WORKERS or CgroupQuota).",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development.",
)
@click.option(
    "--worker-only",
    is_flag=True,
    help="Run only the durable background job worker process.",
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
    parent_obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    _start_listener_server(
        host=host if host is not None else parent_obj.get("listener_host"),
        port=port if port is not None else parent_obj.get("listener_port"),
        workers=workers if workers is not None else parent_obj.get("listener_workers"),
        reload=bool(reload or parent_obj.get("listener_reload", False)),
        worker_only=bool(worker_only or parent_obj.get("listener_worker_only", False)),
    )


@listener.command(
    name="status",
    help="Check status of running GOE Listener service.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@common_options
@click.pass_context
def status(ctx: click.Context, **kwargs: Any) -> None:
    """Check listener operational status via the health and config endpoints."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    extract_common_options(ctx, kwargs)
    base_url = settings.base_url.rstrip("/")
    url = f"{base_url}/api/system/status/"
    print_info(f"Checking GOE Listener status at {url}...")
    try:
        response = httpx.get(url, timeout=2.0)
        config_status = 200
        if response.status_code == 200 and settings.shared_token:
            config_url = f"{base_url}/api/system/config/"
            config_resp = httpx.get(
                config_url,
                headers={"x-goe-console-key": settings.shared_token},
                timeout=2.0,
            )
            config_status = config_resp.status_code
    except Exception:
        print_warning("GOE Listener is not reachable.")
        ctx.exit(1)

    if response.status_code != 200:
        print_warning(f"GOE Listener returned status {response.status_code}.")
        ctx.exit(1)
    if config_status != 200:
        print_warning(f"GOE Listener authenticated probe returned status {config_status}.")
        ctx.exit(1)
    print_success(f"GOE Listener is healthy ({response.text}).")


@listener.group(
    name="mcp",
    help="Model Context Protocol (MCP) transports and catalog inspection.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@common_options
@click.pass_context
def mcp(ctx: click.Context, **kwargs: Any) -> None:
    """Model Context Protocol transport and catalog commands."""
    extract_common_options(ctx, kwargs)


@mcp.command(
    name="stdio",
    help="Serve the GOE Listener MCP endpoint in-process over stdio.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--client-id",
    default="goe-cli-stdio",
    show_default=True,
    help="MCP client identity reported to the in-process ASGI session.",
)
@click.option(
    "--owner-id",
    default=None,
    help="Optional owner identifier bound to in-process MCP tasks.",
)
@click.option(
    "--header",
    "header_values",
    multiple=True,
    help="Additional static HTTP header in 'Name: value' format.",
)
@click.option(
    "--bearer-env",
    default=None,
    help="Environment variable containing the console key token.",
)
@click.option(
    "--header-name",
    default="x-goe-console-key",
    show_default=True,
    help="Authentication header name forwarded to the ASGI app.",
)
@click.option(
    "--token-prefix",
    default="",
    show_default=True,
    help="Prefix prepended to authentication token values.",
)
@click.option(
    "--sse-read-timeout",
    type=float,
    default=300.0,
    show_default=True,
    help="SSE subscription read timeout in seconds.",
)
@click.option(
    "--max-message-size",
    type=int,
    default=16_777_216,
    show_default=True,
    help="Maximum bytes allowed per JSON-RPC message.",
)
@common_options
@click.pass_context
def stdio(
    ctx: click.Context,
    client_id: str = "goe-cli-stdio",
    owner_id: str | None = None,
    header_values: tuple[str, ...] = (),
    bearer_env: str | None = None,
    header_name: str = "x-goe-console-key",
    token_prefix: str = "",
    sse_read_timeout: float = 300.0,
    max_message_size: int = 16_777_216,
    **kwargs: Any,
) -> None:
    """Run an in-process MCP stdio session backed by the GOE Listener Litestar app."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    extract_common_options(ctx, kwargs)
    _redirect_stdout_log_handlers()
    headers = _parse_header_options(header_values)
    token = os.getenv(bearer_env) if bearer_env else settings.shared_token
    if token and header_name not in headers:
        headers[header_name] = f"{token_prefix}{token}"
    stdio_context = MCPStdioContext(
        client_id=client_id,
        owner_id=owner_id,
        auth={"token": token} if token else None,
    )
    app = create_app(enable_background_worker=False)
    exit_code = run_stdio(
        app,
        stdio_context=stdio_context,
        headers=headers,
        header_name=header_name,
        token_prefix=token_prefix,
        sse_read_timeout=sse_read_timeout,
        max_message_size=max_message_size,
        stderr=sys.stderr,
    )
    if exit_code != 0:
        ctx.exit(exit_code)


@mcp.command(
    name="bridge",
    help="Bridge local stdio JSON-RPC to a remote GOE Listener Streamable HTTP /mcp endpoint.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--endpoint",
    default=None,
    help="Full Streamable HTTP MCP endpoint URL (defaults to <settings.base_url>/mcp).",
)
@click.option(
    "--header",
    "header_values",
    multiple=True,
    help="Additional static HTTP header in 'Name: value' format.",
)
@click.option(
    "--bearer-env",
    default="OFFLOAD_LISTENER_SHARED_TOKEN",
    show_default=True,
    help="Environment variable containing the console key token.",
)
@click.option(
    "--header-name",
    default="x-goe-console-key",
    show_default=True,
    help="Header name used for authentication tokens.",
)
@click.option(
    "--token-prefix",
    default="",
    show_default=True,
    help="Prefix prepended to authentication token values.",
)
@click.option(
    "--timeout",
    type=float,
    default=30.0,
    show_default=True,
    help="HTTP connect/write/pool timeout in seconds.",
)
@click.option(
    "--sse-read-timeout",
    type=float,
    default=300.0,
    show_default=True,
    help="SSE stream read timeout in seconds.",
)
@click.option(
    "--max-message-size",
    type=int,
    default=16_777_216,
    show_default=True,
    help="Maximum bytes allowed per JSON-RPC message.",
)
@common_options
@click.pass_context
def bridge(
    ctx: click.Context,
    endpoint: str | None = None,
    header_values: tuple[str, ...] = (),
    bearer_env: str | None = "OFFLOAD_LISTENER_SHARED_TOKEN",
    header_name: str = "x-goe-console-key",
    token_prefix: str = "",
    timeout: float = 30.0,
    sse_read_timeout: float = 300.0,
    max_message_size: int = 16_777_216,
    **kwargs: Any,
) -> None:
    """Bridge stdio JSON-RPC frames to a running GOE Listener /mcp endpoint."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    extract_common_options(ctx, kwargs)
    _redirect_stdout_log_handlers()
    resolved_endpoint = endpoint or f"{settings.base_url.rstrip('/')}/mcp"
    headers = _parse_header_options(header_values)
    token_provider = _resolve_token_provider(bearer_env, settings.shared_token)
    exit_code = asyncio.run(
        run_stdio_streamable_http_bridge(
            resolved_endpoint,
            headers=headers,
            token_provider=token_provider,
            header_name=header_name,
            token_prefix=token_prefix,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
            max_message_size=max_message_size,
            stderr=sys.stderr,
        )
    )
    if exit_code != 0:
        ctx.exit(exit_code)


@mcp.command(
    name="inspect",
    help="Inspect registered GOE Listener MCP tools, resources, templates, prompts, and skills.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the MCP catalog summary as JSON.",
)
@common_options
@click.pass_context
def inspect(ctx: click.Context, as_json: bool = False, **kwargs: Any) -> None:
    """Display the registered GOE Listener MCP catalog in Rich table or JSON format."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    extract_common_options(ctx, kwargs)
    summary = _build_mcp_catalog_summary()
    if as_json:
        sys.stdout.write(f"{encode_json(summary)}\n")
        return

    table = Table(box=None, show_header=True, pad_edge=False)
    table.add_column("Category", style="bold #4285F4")
    table.add_column("Identifier / URI", style="cyan")
    for name in summary["tools"]:
        table.add_row("Tool", name)
    for uri in summary["resources"]:
        table.add_row("Resource", uri)
    for template in summary["resource_templates"]:
        table.add_row("Template", template)
    for prompt_name in summary["prompts"]:
        table.add_row("Prompt", prompt_name)
    for skill_uri in summary["skills"]:
        table.add_row("Skill", skill_uri)
    console.print(table)


def __getattr__(name: str) -> Any:
    """Lazily import runtime dependencies and listener settings on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)


def _start_listener_server(
    host: str | None = None,
    port: int | None = None,
    workers: int | None = None,
    reload: bool = False,
    worker_only: bool = False,
) -> None:
    """Start the Vertebra ASGI server or standalone durable background job worker process."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    resolved_host = host if host is not None else settings.host
    resolved_port = int(port) if port is not None else int(settings.port)
    if workers is not None:
        resolved_workers = int(workers)
    elif "OFFLOAD_LISTENER_HTTP_WORKERS" in os.environ:
        resolved_workers = int(settings.http_workers)
    else:
        resolved_workers = int(CgroupQuota.detect().recommended_workers)

    if worker_only:
        print_info("Starting GOE Listener durable job worker process...")
        store = create_job_store()
        worker = DurableJobWorker(
            store=store,
            heartbeat_interval_seconds=float(settings.heartbeat_interval),
        )
        asyncio.run(worker.run_forever())
        return

    asyncio.run(verify_vertebra_runtime_gate(require_passed=True))
    cmd = build_vertebra_command(
        host=resolved_host,
        port=resolved_port,
        workers=resolved_workers,
        threads=int(settings.threads),
        topology=str(settings.topology),
        drain_timeout=int(settings.drain_timeout_seconds),
        shutdown_timeout=int(settings.shutdown_timeout_seconds),
        ssl_enabled=bool(settings.ssl_enabled),
        certfile=settings.certfile,
        keyfile=settings.keyfile,
        reload=bool(reload or settings.reload),
    )
    env = settings.to_vertebra_env(os.environ)
    if host is not None or "VERTEBRA_HOST" not in os.environ:
        env["VERTEBRA_HOST"] = str(resolved_host)
    if port is not None or "VERTEBRA_PORT" not in os.environ:
        env["VERTEBRA_PORT"] = str(resolved_port)
    if workers is not None or "VERTEBRA_WORKERS" not in os.environ:
        env["VERTEBRA_WORKERS"] = str(resolved_workers)
    print_info(f"Starting GOE Listener on http://{resolved_host}:{resolved_port} with {resolved_workers} worker(s)...")
    subprocess.run(cmd, env=env, check=True)


def _redirect_stdout_log_handlers() -> None:
    """Redirect any stdlib StreamHandler targeting stdout to sys.stderr to keep stdio JSON-RPC frames pure."""
    root = logging.getLogger()
    for handler in root.handlers:
        if type(handler) is logging.StreamHandler and getattr(handler, "stream", None) is not sys.stderr:
            handler.setStream(sys.stderr)


def _parse_header_options(header_values: tuple[str, ...]) -> dict[str, str]:
    """Parse 'Name: value' CLI options into a dictionary of HTTP headers."""
    headers: dict[str, str] = {}
    for item in header_values:
        if ":" not in item:
            msg = f"Invalid header {item!r}; expected 'Name: value'."
            raise click.BadParameter(msg)
        key, val = item.split(":", 1)
        key = key.strip()
        if not key:
            msg = f"Invalid header {item!r}; header name cannot be empty."
            raise click.BadParameter(msg)
        headers[key] = val.strip()
    return headers


def _resolve_token_provider(bearer_env: str | None, fallback_token: str | None) -> Callable[[], str] | None:
    """Return a zero-argument token provider when an environment variable or configured shared_token is available."""
    env_value = os.getenv(bearer_env) if bearer_env else None
    resolved = env_value or fallback_token
    if not resolved:
        return None

    def _provider() -> str:
        current = os.getenv(bearer_env) if bearer_env else None
        return current or fallback_token or ""

    return _provider


def _build_mcp_catalog_summary() -> dict[str, list[str]]:
    """Construct the Litestar app and extract sorted lists of tools, resources, templates, prompts, and skills."""
    app = create_app(enable_background_worker=False)
    plugin = app.plugins.get(LitestarMCP)
    plugin.on_startup(app)
    try:
        tools = sorted(plugin.discovered_tools.keys())
        resources: list[str] = []
        for name, handler in plugin.discovered_resources.items():
            opt = getattr(handler, "opt", None) or {}
            uri = opt.get(plugin.config.opt_keys.resource_uri) or f"litestar://{name}"
            resources.append(str(uri))
        resources.sort()
        resource_templates = sorted(entry.template for entry in plugin.registry.templates.values())
        prompts = sorted(plugin.discovered_prompts.keys())
        skills: list[str] = []
        if plugin.skill_catalog is not None:
            for source in plugin.skill_catalog.sources:
                for skill in getattr(source, "skills", ()):
                    skills.append(skill.uri)
        skills.sort()
        return {
            "tools": tools,
            "resources": resources,
            "resource_templates": resource_templates,
            "prompts": prompts,
            "skills": skills,
        }
    finally:
        asyncio.run(plugin.on_shutdown(app))

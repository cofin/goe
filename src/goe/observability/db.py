# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Oracle session trace tagging, SQLSpec SQLCommenter helpers, and SQLSpec observability wiring.

Every helper is a no-op when telemetry is disabled so Oracle sessions, transport SQL text, and SQLSpec statement
caching behave exactly as before. ``MODULE``/``ACTION`` are never modified because ``LOG_SQL_STATS_QUERY_TEXT``
locates transport SQL in ``gv$sql`` by those values.
"""

from typing import Any

from sqlspec.core.sqlcommenter import generate_comment
from sqlspec.observability import LoggingConfig, RedactionConfig, TelemetryConfig
from sqlspec.observability import ObservabilityConfig as SqlspecObservabilityConfig
from sqlspec.observability import ObservabilityRuntime as SqlspecObservabilityRuntime

from goe.observability.context import get_current_trace_context
from goe.observability.runtime import get_observability_runtime, get_tracer_provider

__all__ = (
    "ORACLE_CLIENT_INFO_MAX_BYTES",
    "apply_oracle_session_trace_info",
    "attach_db_observability",
    "build_db_observability_config",
    "build_oracle_client_info_command",
    "build_transport_sql_comment",
    "format_oracle_client_info",
    "format_sqlcommenter",
)

ORACLE_CLIENT_INFO_MAX_BYTES = 64


def format_oracle_client_info() -> str | None:
    """Return the value for ``V$SESSION.CLIENT_INFO``: traceparent, else ``goe:<execution_id>``, else None."""
    if not get_observability_runtime().enabled:
        return None
    snapshot = get_current_trace_context()
    if snapshot.traceparent:
        return _truncate_utf8(snapshot.traceparent, ORACLE_CLIENT_INFO_MAX_BYTES)
    if snapshot.execution_id:
        return _truncate_utf8(f"goe:{snapshot.execution_id}", ORACLE_CLIENT_INFO_MAX_BYTES)
    return None


def apply_oracle_session_trace_info(db_conn: Any) -> str | None:
    """Set ``db_conn.clientinfo`` to the current trace identity; never touches ``module`` or ``action``."""
    client_info = format_oracle_client_info()
    if client_info is not None and db_conn is not None:
        db_conn.clientinfo = client_info
    return client_info


def build_oracle_client_info_command(for_plsql: bool = False) -> str | None:
    """Return a ``DBMS_APPLICATION_INFO.SET_CLIENT_INFO`` command shaped like the existing SET_MODULE command."""
    client_info = format_oracle_client_info()
    if client_info is None:
        return None
    literal = client_info.replace("'", "''")
    if for_plsql:
        return f"DBMS_APPLICATION_INFO.SET_CLIENT_INFO('{literal}');"
    return f"BEGIN DBMS_APPLICATION_INFO.SET_CLIENT_INFO('{literal}'); END;"


def format_sqlcommenter(**attributes: str) -> str | None:
    """Return a spec-compliant ``/*...*/`` SQLCommenter comment via ``sqlspec.core.sqlcommenter``, or None."""
    snapshot = get_current_trace_context()
    attrs: dict[str, str] = {key: value for key, value in attributes.items() if value}
    if snapshot.traceparent:
        attrs.setdefault("traceparent", snapshot.traceparent)
    if snapshot.tracestate:
        attrs.setdefault("tracestate", snapshot.tracestate)
    if snapshot.execution_id:
        attrs.setdefault("goe_execution_id", snapshot.execution_id)
    if not attrs:
        return None
    rendered = generate_comment(attrs)
    if not rendered:
        return None
    return rendered if rendered.startswith("/*") else f"/*{rendered}*/"


def build_transport_sql_comment(existing_comment: str | None) -> str | None:
    """Append SQLCommenter key-value pairs to a transport SQL comment when telemetry and ``sqlcommenter`` are enabled."""
    active = get_observability_runtime()
    if not active.enabled or not active.settings.sqlcommenter:
        return existing_comment
    comment = format_sqlcommenter()
    if comment is None:
        return existing_comment
    inner = comment.removeprefix("/*").removesuffix("*/").strip()
    return f"{existing_comment} {inner}" if existing_comment else inner


def build_db_observability_config() -> SqlspecObservabilityConfig | None:
    """Return a SQLSpec ObservabilityConfig emitting CLIENT spans through GOE's provider, or None when disabled."""
    if not get_observability_runtime().enabled:
        return None
    return SqlspecObservabilityConfig(
        telemetry=TelemetryConfig(enable_spans=True, provider_factory=get_tracer_provider),
        redaction=RedactionConfig(mask_parameters=True),
        logging=LoggingConfig(include_sql_hash=True, include_trace_context=True),
    )


def attach_db_observability(driver: Any) -> None:
    """Attach a SQLSpec observability runtime and optional SQLCommenter transform to ``driver`` when enabled."""
    active = get_observability_runtime()
    config = build_db_observability_config()
    if config is not None:
        driver.attach_observability(SqlspecObservabilityRuntime(config, config_name="OracleGateway"))
    if active.enabled and active.settings.sqlcommenter and getattr(driver, "statement_config", None) is not None:
        driver.statement_config = driver.statement_config.replace(
            enable_sqlcommenter=True,
            sqlcommenter_attributes={"db_driver": "oracledb", "framework": "goe"},
            sqlcommenter_enable_traceparent=True,
            sqlcommenter_enable_context=True,
        )


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Truncate ``value`` to at most ``max_bytes`` UTF-8 bytes without splitting a character."""
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")

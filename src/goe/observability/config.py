# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Typed OpenTelemetry and structured logging settings for GOE.

Resolution order for every field: a non-None attribute on the supplied config object (``CommonOptions`` or any
object exposing ``otel_*`` / ``log_*`` attributes), then the ``GOE_OTEL_*`` / ``GOE_LOG_*`` environment variable,
then the field default. Invalid values never raise; they log a warning and fall back to the default so telemetry
misconfiguration can never abort an offload.
"""

import logging
import os
from typing import Any, Literal, cast

from goe.typing import FrozenBaseStruct

__all__ = (
    "VALID_EXPORTERS",
    "VALID_LOG_FORMATS",
    "VALID_PROTOCOLS",
    "ExporterType",
    "LogFormatType",
    "OTLPProtocolType",
    "ObservabilitySettings",
)

logger = logging.getLogger(__name__)

ExporterType = Literal["none", "console", "jsonl", "otlp", "gcp", "memory"]
OTLPProtocolType = Literal["grpc", "http/protobuf"]
LogFormatType = Literal["text", "json"]

VALID_EXPORTERS: frozenset[str] = frozenset({"none", "console", "jsonl", "otlp", "gcp", "memory"})
VALID_PROTOCOLS: frozenset[str] = frozenset({"grpc", "http/protobuf"})
VALID_LOG_FORMATS: frozenset[str] = frozenset({"text", "json"})
_TRUE_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on", "y"})


class ObservabilitySettings(FrozenBaseStruct, frozen=True, kw_only=True):
    """Immutable GOE telemetry settings.

    ``exporter`` selects the span/metric sink: ``none`` (no SDK), ``console``, ``jsonl`` (local file),
    ``otlp`` (collector at ``endpoint`` over ``protocol``), ``gcp`` (Google Cloud Telemetry OTLP API), or
    ``memory`` (in-process test harness).
    """

    enabled: bool = False
    service_name: str = "goe"
    deployment_environment: str | None = None
    exporter: ExporterType = "none"
    endpoint: str | None = None
    protocol: OTLPProtocolType = "grpc"
    sample_rate: float = 1.0
    log_correlation: bool = True
    sqlcommenter: bool = False
    jsonl_path: str | None = None
    log_format: LogFormatType = "text"
    log_json_sidecar: bool = False

    @property
    def tracing_active(self) -> bool:
        """Return True only when telemetry is enabled and a real exporter is selected."""
        return self.enabled and self.exporter != "none"

    @classmethod
    def from_env_and_config(cls, config: Any | None = None) -> "ObservabilitySettings":
        """Build settings from config attributes, ``GOE_OTEL_*`` / ``GOE_LOG_*`` variables, and defaults."""
        exporter = _resolve_choice(config, "otel_exporter", "GOE_OTEL_EXPORTER", VALID_EXPORTERS, "none")
        protocol = _resolve_choice(config, "otel_protocol", "GOE_OTEL_PROTOCOL", VALID_PROTOCOLS, "grpc")
        log_format = _resolve_choice(config, "log_format", "GOE_LOG_FORMAT", VALID_LOG_FORMATS, "text")
        sample_rate = _resolve_float(config, "otel_sample_rate", "GOE_OTEL_SAMPLE_RATE", 1.0)
        return cls(
            enabled=_resolve_bool(config, "otel_enabled", "GOE_OTEL_ENABLED", False),
            service_name=_resolve_str(config, "otel_service_name", "GOE_OTEL_SERVICE_NAME") or "goe",
            deployment_environment=_resolve_str(config, "otel_environment", "GOE_OTEL_ENVIRONMENT"),
            exporter=cast(ExporterType, exporter),
            endpoint=_resolve_str(config, "otel_endpoint", "GOE_OTEL_ENDPOINT"),
            protocol=cast(OTLPProtocolType, protocol),
            sample_rate=max(0.0, min(1.0, sample_rate)),
            log_correlation=_resolve_bool(config, "otel_log_correlation", "GOE_OTEL_LOG_CORRELATION", True),
            sqlcommenter=_resolve_bool(config, "otel_sqlcommenter", "GOE_OTEL_SQLCOMMENTER", False),
            jsonl_path=_resolve_str(config, "otel_jsonl_path", "GOE_OTEL_JSONL_PATH"),
            log_format=cast(LogFormatType, log_format),
            log_json_sidecar=_resolve_bool(config, "log_json_sidecar", "GOE_LOG_JSON_SIDECAR", False),
        )


def _config_value(config: Any | None, attr_name: str) -> Any | None:
    """Return a non-None attribute from config, or None when absent."""
    if config is None:
        return None
    return getattr(config, attr_name, None)


def _resolve_str(config: Any | None, attr_name: str, env_name: str) -> str | None:
    """Resolve a string from a config attribute, then a non-empty environment variable."""
    value = _config_value(config, attr_name)
    if value is not None:
        return str(value)
    env_value = os.environ.get(env_name)
    return env_value if env_value else None


def _resolve_bool(config: Any | None, attr_name: str, env_name: str, default: bool) -> bool:
    """Resolve a boolean from a config attribute, then an environment variable, then the default."""
    value = _config_value(config, attr_name)
    if isinstance(value, bool):
        return value
    raw = str(value) if value is not None else os.environ.get(env_name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _resolve_float(config: Any | None, attr_name: str, env_name: str, default: float) -> float:
    """Resolve a float, logging a warning and returning the default when the value is not numeric."""
    raw = _resolve_str(config, attr_name, env_name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s value %r; using %s", env_name, raw, default)
        return default


def _resolve_choice(config: Any | None, attr_name: str, env_name: str, choices: frozenset[str], default: str) -> str:
    """Resolve a lower-cased enumerated value, logging a warning and returning the default when invalid."""
    raw = _resolve_str(config, attr_name, env_name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value not in choices:
        logger.warning("Ignoring invalid %s value %r; using %r", env_name, raw, default)
        return default
    return value

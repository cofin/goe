# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Process-wide OpenTelemetry runtime for GOE.

The default runtime is a shared no-op: ``NoOpTracerProvider`` and ``NoOpMeterProvider`` with no SDK import, no
threads, and no I/O. ``configure_observability`` builds SDK providers only when settings enable a real exporter and
falls back to the no-op runtime (with one warning) if provider construction fails, so telemetry can never abort an
offload.
"""

import atexit
import logging
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter, MeterProvider, NoOpMeterProvider
from opentelemetry.trace import NoOpTracerProvider, Tracer, TracerProvider

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.observability.config import ObservabilitySettings
from goe.observability.log_correlation import install_log_record_correlation, uninstall_log_record_correlation
from goe.observability.metrics import GOEMetrics

if TYPE_CHECKING:
    from goe.observability import _sdk

__all__ = (
    "TRACER_NAME",
    "ObservabilityRuntime",
    "configure_observability",
    "ensure_observability",
    "get_meter",
    "get_meter_provider",
    "get_observability_runtime",
    "get_tracer",
    "get_tracer_provider",
    "is_observability_configured",
    "shutdown_observability",
)

logger = logging.getLogger(__name__)

TRACER_NAME = "goe"

_LAZY_IMPORTS: LazyImportMap = {"_sdk": ("goe.observability._sdk", None)}


class ObservabilityRuntime:
    """Settings, providers, and the GOEMetrics recorder for one GOE process."""

    def __init__(
        self,
        settings: ObservabilitySettings,
        tracer_provider: TracerProvider,
        meter_provider: MeterProvider,
        memory_span_exporter: Any | None = None,
        memory_metric_reader: Any | None = None,
    ) -> None:
        """Store providers and create the GOEMetrics instruments from the meter provider."""
        self.settings = settings
        self.tracer_provider = tracer_provider
        self.meter_provider = meter_provider
        self.metrics = GOEMetrics(meter_provider.get_meter(TRACER_NAME))
        self._memory_span_exporter = memory_span_exporter
        self._memory_metric_reader = memory_metric_reader

    @property
    def enabled(self) -> bool:
        """Return True when SDK providers are active."""
        return self.settings.tracing_active

    @classmethod
    def noop(cls, settings: ObservabilitySettings | None = None) -> "ObservabilityRuntime":
        """Return a runtime backed by API no-op providers."""
        return cls(settings or ObservabilitySettings(), NoOpTracerProvider(), NoOpMeterProvider())

    def get_tracer(self, name: str = TRACER_NAME) -> Tracer:
        """Return a tracer from this runtime's provider."""
        return self.tracer_provider.get_tracer(name)

    def get_meter(self, name: str = TRACER_NAME) -> Meter:
        """Return a meter from this runtime's provider."""
        return self.meter_provider.get_meter(name)

    def get_finished_spans(self) -> tuple[Any, ...]:
        """Return finished spans captured by the memory exporter, or an empty tuple."""
        if self._memory_span_exporter is None:
            return ()
        return tuple(self._memory_span_exporter.get_finished_spans())

    def clear_finished_spans(self) -> None:
        """Clear spans captured by the memory exporter."""
        if self._memory_span_exporter is not None:
            self._memory_span_exporter.clear()

    def get_metrics_data(self) -> Any | None:
        """Return collected metrics from the memory reader, or None."""
        if self._memory_metric_reader is None:
            return None
        return self._memory_metric_reader.get_metrics_data()

    def shutdown(self) -> None:
        """Flush and shut down SDK providers; no-op providers have no shutdown method."""
        for provider in (self.tracer_provider, self.meter_provider):
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()


_NOOP_RUNTIME = ObservabilityRuntime.noop()
_state: dict[str, Any] = {"runtime": None, "global_set": False, "atexit": False}


def configure_observability(
    settings: ObservabilitySettings | None = None,
    config: Any | None = None,
    set_global: bool = True,
) -> ObservabilityRuntime:
    """Replace the process runtime using ``settings`` or settings resolved from ``config`` and the environment."""
    previous = _state["runtime"]
    if previous is not None:
        previous.shutdown()
    resolved = settings or ObservabilitySettings.from_env_and_config(config)
    active = _build_runtime(resolved, config)
    _state["runtime"] = active
    if active.enabled and resolved.log_correlation:
        install_log_record_correlation()
    else:
        uninstall_log_record_correlation()
    if set_global and active.enabled and not _state["global_set"]:
        trace.set_tracer_provider(active.tracer_provider)
        metrics.set_meter_provider(active.meter_provider)
        _state["global_set"] = True
    if not _state["atexit"]:
        atexit.register(shutdown_observability)
        _state["atexit"] = True
    return active


def ensure_observability(config: Any | None = None) -> ObservabilityRuntime:
    """Configure the runtime once per process; later calls return the existing runtime.

    ``config`` may be an ``ObservabilitySettings`` instance or any object accepted by
    ``ObservabilitySettings.from_env_and_config``.
    """
    current = _state["runtime"]
    if current is not None:
        return cast(ObservabilityRuntime, current)
    if isinstance(config, ObservabilitySettings):
        return configure_observability(settings=config)
    return configure_observability(config=config)


def is_observability_configured() -> bool:
    """Return True after ``configure_observability`` or ``ensure_observability`` has run."""
    return _state["runtime"] is not None


def get_observability_runtime() -> ObservabilityRuntime:
    """Return the configured runtime or the shared no-op runtime (without marking the process configured)."""
    return cast(ObservabilityRuntime, _state["runtime"]) or _NOOP_RUNTIME


def get_tracer(name: str = TRACER_NAME) -> Tracer:
    """Return a tracer from the active runtime."""
    return get_observability_runtime().get_tracer(name)


def get_meter(name: str = TRACER_NAME) -> Meter:
    """Return a meter from the active runtime."""
    return get_observability_runtime().get_meter(name)


def get_tracer_provider() -> TracerProvider:
    """Return the active tracer provider (used as sqlspec ``provider_factory``)."""
    return get_observability_runtime().tracer_provider


def get_meter_provider() -> MeterProvider:
    """Return the active meter provider."""
    return get_observability_runtime().meter_provider


def shutdown_observability() -> None:
    """Flush and forget the configured runtime; safe to call repeatedly and from ``atexit``."""
    uninstall_log_record_correlation()
    current = _state["runtime"]
    _state["runtime"] = None
    if current is not None:
        current.shutdown()


def __getattr__(name: str) -> Any:
    """Resolve the lazily bound ``_sdk`` module on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)


def _build_runtime(settings: ObservabilitySettings, config: Any | None) -> ObservabilityRuntime:
    """Build an SDK-backed runtime, or a no-op runtime when tracing is inactive or construction fails."""
    if not settings.tracing_active:
        return ObservabilityRuntime.noop(settings)
    try:
        bind_lazy_imports(__name__, _LAZY_IMPORTS)
        providers = _sdk.build_sdk_providers(settings, config)
    except Exception as exc:
        logger.warning("OpenTelemetry disabled: failed to build %s exporter: %s", settings.exporter, exc)
        return ObservabilityRuntime.noop()
    return ObservabilityRuntime(
        settings,
        providers.tracer_provider,
        providers.meter_provider,
        providers.memory_span_exporter,
        providers.memory_metric_reader,
    )

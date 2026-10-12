# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""CLIENT span decorator for GOE cloud storage operations."""

import functools
import inspect
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlparse

from opentelemetry.trace import SpanKind

from goe.observability.runtime import get_observability_runtime, get_tracer
from goe.observability.spans import TracedOperation

__all__ = ("traced_storage_call",)


def traced_storage_call[F: Callable[..., Any]](operation: str, uri_param: str, scheme: str = "gs") -> Callable[[F], F]:
    """Decorate a storage method so each call runs in ``goe.storage.<scheme>.<operation>`` (CLIENT)."""

    def decorator(fn: F) -> F:
        """Wrap ``fn``; bind arguments only when telemetry is enabled."""
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Invoke ``fn`` directly when disabled, otherwise inside a CLIENT span."""
            if not get_observability_runtime().enabled:
                return fn(*args, **kwargs)
            bound = signature.bind_partial(*args, **kwargs)
            owner = bound.arguments.get("self")
            attributes = _storage_attributes(
                operation, scheme, bound.arguments.get(uri_param), getattr(owner, "_dry_run", None)
            )
            with get_tracer().start_as_current_span(
                f"goe.storage.{scheme}.{operation}",
                kind=SpanKind.CLIENT,
                attributes=attributes,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                traced = TracedOperation(span)
                try:
                    return fn(*args, **kwargs)
                except BaseException as exc:
                    traced.fail(exc)
                    raise

        setattr(wrapper, "__goe_storage_operation__", operation)
        return cast(F, wrapper)

    return decorator


def _storage_attributes(operation: str, scheme: str, uri: Any, dry_run: Any) -> dict[str, Any]:
    """Build span attributes for a storage call."""
    attributes: dict[str, Any] = {"goe.storage.scheme": scheme, "goe.storage.operation": operation}
    if isinstance(dry_run, bool):
        attributes["goe.storage.dry_run"] = dry_run
    if isinstance(uri, str) and uri:
        parsed = urlparse(uri)
        attributes["goe.storage.uri"] = uri
        if parsed.netloc:
            attributes["goe.storage.bucket"] = parsed.netloc
        if parsed.path.lstrip("/"):
            attributes["goe.storage.path"] = parsed.path.lstrip("/")
    return attributes

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Cached optional module loader and PEP 562 lazy package export helpers."""

import importlib
import importlib.util
from collections.abc import Callable, Mapping
from functools import lru_cache
from types import ModuleType
from typing import Any

from goe.exceptions import OffloadException

__all__ = [
    "MissingOptionalDependencyError",
    "ensure_module",
    "import_optional",
    "lazy_exports",
    "module_available",
]


class MissingOptionalDependencyError(OffloadException, ImportError):
    """Raised when an optional dependency module cannot be imported."""

    def __init__(self, module_name: str, *, extra: str | None = None) -> None:
        hint = f" (install extra '{extra}' via 'uv sync --extra {extra}')" if extra else ""
        super().__init__(f"Optional dependency '{module_name}' is not installed{hint}")
        self.module_name = module_name
        self.extra = extra


@lru_cache(maxsize=256)
def module_available(module_name: str) -> bool:
    """Return True when module_name can be located without importing it."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


@lru_cache(maxsize=256)
def import_optional(module_name: str) -> ModuleType | None:
    """Import and return module_name, or return None if it is not installed."""
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


@lru_cache(maxsize=256)
def ensure_module(module_name: str, *, extra: str | None = None) -> ModuleType:
    """Import and return module_name, raising MissingOptionalDependencyError on failure."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise MissingOptionalDependencyError(module_name, extra=extra) from exc


def lazy_exports(
    package_globals: dict[str, Any],
    targets: Mapping[str, tuple[str, str]],
    *,
    extra: str | None = None,
) -> tuple[Callable[[str], Any], Callable[[], list[str]]]:
    """Build PEP 562 __getattr__ and __dir__ functions for lazy package exports."""

    def _getattr(name: str) -> Any:
        if name not in targets:
            raise AttributeError(f"module {package_globals.get('__name__', '')!r} has no attribute {name!r}")
        module_path, attr_name = targets[name]
        mod = ensure_module(module_path, extra=extra)
        value = getattr(mod, attr_name)
        package_globals[name] = value
        return value

    def _dir() -> list[str]:
        return sorted(set(package_globals) | set(targets))

    return _getattr, _dir

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Type-safe lazy attribute resolution and binding helpers for the GOE CLI."""

import importlib
import sys
from typing import Any

__all__ = (
    "LazyImportMap",
    "bind_lazy_imports",
    "resolve_lazy_attribute",
)

LazyImportMap = dict[str, tuple[str, str | None]]


def resolve_lazy_attribute(module_name: str, lazy_imports: LazyImportMap, name: str) -> Any:
    """Resolve and cache a lazily imported attribute on a module namespace."""
    target = lazy_imports.get(name)
    if target is None:
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
    target_module_name, target_attr = target
    imported = importlib.import_module(target_module_name)
    value = imported if target_attr is None else getattr(imported, target_attr)
    setattr(sys.modules[module_name], name, value)
    return value


def bind_lazy_imports(module_name: str, lazy_imports: LazyImportMap) -> None:
    """Populate module globals for all declared lazy imports not already bound or patched."""
    module_dict = sys.modules[module_name].__dict__
    for name in lazy_imports:
        if name not in module_dict:
            resolve_lazy_attribute(module_name, lazy_imports, name)

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for cached optional module loader and PEP 562 lazy export helpers."""

import pytest

from goe.util.module_loader import (
    MissingOptionalDependencyError,
    ensure_module,
    import_optional,
    lazy_exports,
    module_available,
)


def test_module_available_and_import_optional() -> None:
    """module_available and import_optional inspect and load installed modules safely."""
    assert module_available("json") is True
    assert module_available("nonexistent_pkg_xyz_999") is False
    imported = import_optional("json")
    assert imported is not None
    assert hasattr(imported, "dumps")
    assert import_optional("nonexistent_pkg_xyz_999") is None


def test_ensure_module_raises_with_extra_hint() -> None:
    """ensure_module raises MissingOptionalDependencyError with uv sync extra guidance."""
    with pytest.raises(MissingOptionalDependencyError, match="snowflake") as exc_info:
        ensure_module("nonexistent_pkg_xyz_999", extra="snowflake")
    assert exc_info.value.module_name == "nonexistent_pkg_xyz_999"
    assert exc_info.value.extra == "snowflake"


def test_lazy_exports_resolves_and_caches_attributes() -> None:
    """lazy_exports builds PEP 562 __getattr__ and __dir__ functions that resolve attributes on demand."""
    ns: dict[str, object] = {"__name__": "sample_pkg"}
    getattr_fn, dir_fn = lazy_exports(
        ns,
        {"Path": ("pathlib", "Path")},
        extra="core",
    )
    assert "Path" in dir_fn()
    resolved = getattr_fn("Path")
    assert resolved.__name__ == "Path"
    assert ns["Path"] is resolved

    with pytest.raises(AttributeError, match="has no attribute 'Unknown'"):
        getattr_fn("Unknown")

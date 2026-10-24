# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for core typing primitives and GC-exempt msgspec Struct base classes."""

import gc

import msgspec
import pytest

from goe.typing import (
    UNSET,
    BaseStruct,
    CamelStruct,
    FrozenBaseStruct,
    FrozenCamelStruct,
    UnsetType,
    WireFrameStruct,
    filter_unset,
)


class _SampleMutable(BaseStruct):
    name: str
    count: int = 0


class _SampleFrozen(FrozenBaseStruct, frozen=True):
    name: str
    optional_field: str | None | UnsetType = UNSET


class _SampleWire(WireFrameStruct, frozen=True):
    seq: int
    payload: str


class _SampleCamel(CamelStruct):
    table_owner: str
    row_count: int = 1


class _SampleFrozenCamel(FrozenCamelStruct, frozen=True):
    table_owner: str
    row_count: int = 1


def test_struct_hierarchy_disables_cyclic_gc() -> None:
    """All base struct subclasses disable CPython cyclic GC tracking and enforce mutability/layout."""
    mutable = _SampleMutable(name="alpha", count=1)
    frozen = _SampleFrozen(name="beta")
    wire = _SampleWire(seq=7, payload="ok")
    camel = _SampleCamel(table_owner="SH")
    frozen_camel = _SampleFrozenCamel(table_owner="SH")

    for instance in (mutable, frozen, wire, camel, frozen_camel):
        assert not gc.is_tracked(instance)

    mutable.count = 2
    assert mutable.to_dict() == {"name": "alpha", "count": 2}

    with pytest.raises(AttributeError):
        setattr(frozen, "name", "mutated")

    with pytest.raises(AttributeError):
        setattr(wire, "seq", 9)

    with pytest.raises(AttributeError):
        setattr(frozen_camel, "row_count", 9)

    assert _SampleWire.__struct_config__.array_like is True
    assert msgspec.structs.fields(_SampleCamel)[0].encode_name == "tableOwner"
    assert msgspec.structs.fields(_SampleFrozenCamel)[0].encode_name == "tableOwner"


def test_unset_and_filter_unset() -> None:
    """filter_unset strips UNSET fields while preserving None and concrete values."""
    assert isinstance(UNSET, UnsetType)

    struct_with_unset = _SampleFrozen(name="gamma", optional_field=UNSET)
    assert struct_with_unset.to_dict(exclude_unset=True) == {"name": "gamma"}
    assert filter_unset(struct_with_unset) == {"name": "gamma"}

    struct_with_none = _SampleFrozen(name="delta", optional_field=None)
    assert struct_with_none.to_dict(exclude_unset=True) == {"name": "delta", "optional_field": None}

    raw_mapping = {"keep_none": None, "drop_unset": UNSET, "value": 42}
    assert filter_unset(raw_mapping) == {"keep_none": None, "value": 42}

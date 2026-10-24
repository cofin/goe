# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for centralized msgspec JSON serialization and deserialization utilities."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import msgspec
import numpy as np
import pytest

from goe.serializers import (
    decode_json,
    encode_json,
    encode_json_bytes,
    encode_json_into,
    format_json,
)
from goe.typing import FrozenBaseStruct


class _SamplePayload(FrozenBaseStruct, frozen=True):
    amount: Decimal
    path: Path
    tags: list[str]


class _AsStrDomainObject:
    def __init__(self, value: str) -> None:
        self._value = value

    def as_str(self) -> str:
        return self._value


class _DslDomainObject:
    def __init__(self, dsl: str) -> None:
        self.dsl = dsl


class _IdDomainObject:
    def __init__(self, identifier: str) -> None:
        self.id = identifier


def test_encode_and_decode_roundtrip() -> None:
    """encode_json, encode_json_bytes, and decode_json support structs and domain types."""
    sample_uuid: UUID = uuid4()
    timestamp = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    sample_date = date(2026, 10, 24)
    envelope = {
        "decimal": Decimal("12345678901234567890.123456789"),
        "timestamp": timestamp,
        "date": sample_date,
        "path": Path("/tmp/x"),
        "uuid": sample_uuid,
        "set": {"b", "a"},
        "as_str": _AsStrDomainObject("exec-001"),
        "dsl": _DslDomainObject("COL_A = 1"),
        "id_obj": _IdDomainObject("id-99"),
        "np_int": np.int64(42),
        "np_array": np.array([1, 2, 3]),
    }

    encoded_str = encode_json(envelope)
    encoded_bytes = encode_json_bytes(envelope)
    assert isinstance(encoded_str, str)
    assert isinstance(encoded_bytes, bytes)

    decoded = decode_json(encoded_bytes)
    assert decoded["decimal"] == "12345678901234567890.123456789"
    assert decoded["timestamp"] == "2026-10-24T12:00:00Z"
    assert decoded["date"] == "2026-10-24"
    assert decoded["path"] == "/tmp/x"
    assert decoded["uuid"] == str(sample_uuid)
    assert sorted(decoded["set"]) == ["a", "b"]
    assert decoded["as_str"] == "exec-001"
    assert decoded["dsl"] == "COL_A = 1"
    assert decoded["id_obj"] == "id-99"
    assert decoded["np_int"] == 42
    assert decoded["np_array"] == [1, 2, 3]

    typed = _SamplePayload(
        amount=Decimal("12345678901234567890.123456789"),
        path=Path("/tmp/x"),
        tags=["a", "b"],
    )
    reconstructed = decode_json(encode_json(typed), target_type=_SamplePayload)
    assert reconstructed == typed


def test_encode_json_into_writes_to_bytearray() -> None:
    """encode_json_into writes UTF-8 JSON bytes into a pre-allocated bytearray buffer."""
    buf = bytearray()
    payload = {"owner": "SH", "table": "SALES", "rows": 100}
    encode_json_into(payload, buf)
    assert decode_json(buf) == payload


def test_format_json_compact_and_indented() -> None:
    """format_json validates JSON input and formats compact or indented output."""
    indented = format_json('{"a":1,"b":[2,3]}', indent=2)
    assert "\n  " in indented
    compact = format_json('{"a": 1, "b": [2, 3]}', indent=0)
    assert "\n" not in compact
    assert decode_json(compact) == {"a": 1, "b": [2, 3]}

    with pytest.raises(msgspec.DecodeError):
        format_json("{invalid json", indent=2)

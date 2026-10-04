# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import datetime
import uuid
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from goe.orchestration.execution_id import ExecutionId
from goe.util.json_tools import (
    convert_field_to_camel_case,
    deserialize_object,
    encode_datetime_object,
    serialize_object,
    serialize_object_bytes,
)
from goe.util.serialization import (
    DEFAULT_TYPE_ENCODERS,
)
from goe.util.serialization import (
    serialize_object as serialization_serialize_object,
)
from goe.util.serialization import (
    serialize_object_bytes as serialization_serialize_object_bytes,
)


class MockExecutionId:
    def __init__(self, val: str):
        self.val = val

    def __str__(self) -> str:
        return self.val


class MockPredicate:
    def __init__(self, dsl: str):
        self.dsl = dsl


DEFAULT_TYPE_ENCODERS[MockExecutionId] = str
DEFAULT_TYPE_ENCODERS[MockPredicate] = lambda obj: obj.dsl


def test_serialize_primitives():
    data = {"str": "hello", "int": 42, "float": 3.14, "bool": True, "none": None}
    serialized = serialize_object(data)
    deserialized = deserialize_object(serialized)
    assert deserialized == data


def test_serialize_decimal():
    data = {"amount": Decimal("12345.6789")}
    serialized = serialize_object(data)
    deserialized = deserialize_object(serialized)
    assert deserialized == {"amount": "12345.6789"}


def test_serialize_datetime_and_date():
    dt = datetime.datetime(2026, 8, 24, 22, 0, 0, tzinfo=datetime.UTC)
    d = datetime.date(2026, 8, 24)
    data = {"timestamp": dt, "date": d}
    serialized = serialize_object(data)
    deserialized = deserialize_object(serialized)
    assert "2026-08-24" in deserialized["timestamp"]
    assert deserialized["date"] == "2026-08-24"


def test_serialize_uuid():
    u = uuid.uuid4()
    data = {"id": u}
    serialized = serialize_object(data)
    deserialized = deserialize_object(serialized)
    assert deserialized == {"id": str(u)}


def test_serialize_numpy():
    data = {
        "np_int": np.int64(100),
        "np_float": np.float64(3.14159),
        "np_array": np.array([1, 2, 3]),
    }
    serialized = serialize_object(data)
    deserialized = deserialize_object(serialized)
    assert deserialized["np_int"] == 100
    assert abs(deserialized["np_float"] - 3.14159) < 1e-5
    assert deserialized["np_array"] == [1, 2, 3]


def test_serialize_custom_types():
    exec_id = MockExecutionId("exec-12345")
    pred = MockPredicate("COL_A = 10")
    p = Path("/tmp/test.txt")
    data = {"exec": exec_id, "pred": pred, "path": p, "set": {1, 2, 3}}
    serialized = serialize_object(data)
    deserialized = deserialize_object(serialized)
    assert deserialized["exec"] == "exec-12345"
    assert deserialized["pred"] == "COL_A = 10"
    assert deserialized["path"] == "/tmp/test.txt"
    assert sorted(deserialized["set"]) == [1, 2, 3]


def test_serialize_bytes():
    data = {"key": "value"}
    raw_bytes = serialize_object_bytes(data)
    assert isinstance(raw_bytes, bytes)
    assert deserialize_object(raw_bytes) == data


def test_encode_datetime_object():
    dt = datetime.datetime(2026, 8, 24, 12, 30, 0)
    iso = encode_datetime_object(dt)
    assert iso.endswith("Z")
    assert "2026-08-24T12:30:00" in iso


def test_convert_field_to_camel_case():
    assert convert_field_to_camel_case("user_name") == "userName"
    assert convert_field_to_camel_case("offload_execution_id") == "offloadExecutionId"
    assert convert_field_to_camel_case("alreadyCamel") == "alreadyCamel"


def test_serialization_module_domain_fallback():
    """Verify goe.util.serialization.serialize_object and serialize_object_bytes support unregistered .id and .dsl objects."""

    class UnregisteredIdObject:
        def __init__(self, val: str):
            self.id = val

    class UnregisteredDslObject:
        def __init__(self, dsl: str):
            self.dsl = dsl

    payload = {"exec_id": UnregisteredIdObject("exec-99"), "pred": UnregisteredDslObject("COL_B = 42")}
    json_str = serialization_serialize_object(payload)
    json_bytes = serialization_serialize_object_bytes(payload)
    assert deserialize_object(json_str) == {"exec_id": "exec-99", "pred": "COL_B = 42"}
    assert deserialize_object(json_bytes) == {"exec_id": "exec-99", "pred": "COL_B = 42"}

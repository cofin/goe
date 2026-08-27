# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Serialization utilities for GOE leveraging sqlspec/msgspec."""

import datetime
from typing import Any

from sqlspec.utils.serializers import (
    DEFAULT_TYPE_ENCODERS,
    from_json,
    schema_dump,
    to_json,
)


def serialize_object(obj: Any) -> str:
    """Encodes an object to a JSON string using sqlspec."""
    return to_json(obj)


def serialize_object_bytes(obj: Any) -> bytes:
    """Encodes an object to JSON bytes using sqlspec."""
    return to_json(obj, as_bytes=True)


def deserialize_object(obj: bytes | bytearray | memoryview | str) -> Any:
    """Decodes a JSON payload to a Python object using sqlspec."""
    return from_json(obj)


def encode_datetime_object(dt: datetime.datetime) -> str:
    """Handles datetime serialization for nested timestamps in models/dataclasses."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.isoformat().replace("+00:00", "Z")


__all__ = (
    "DEFAULT_TYPE_ENCODERS",
    "deserialize_object",
    "encode_datetime_object",
    "from_json",
    "schema_dump",
    "serialize_object",
    "serialize_object_bytes",
    "to_json",
)

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Centralized msgspec JSON serialization and deserialization utilities."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, overload
from uuid import UUID

import msgspec

__all__ = [
    "decode_json",
    "encode_json",
    "encode_json_bytes",
    "encode_json_into",
    "format_json",
]


def encode_json_bytes(value: Any) -> bytes:
    """Serialize value to UTF-8 JSON bytes using the shared msgspec encoder."""
    return _ENCODER.encode(value)


def encode_json(value: Any) -> str:
    """Serialize value to a UTF-8 JSON string."""
    return _ENCODER.encode(value).decode("utf-8")


def encode_json_into(value: Any, buffer: bytearray, offset: int = 0) -> None:
    """Serialize value directly into a pre-allocated bytearray at offset."""
    _ENCODER.encode_into(value, buffer, offset)


def format_json(value: str | bytes, *, indent: int = 2) -> str:
    """Validate and format a JSON string or bytes payload."""
    raw = value.encode("utf-8") if isinstance(value, str) else value
    _DECODER.decode(raw)
    formatted = msgspec.json.format(raw, indent=indent)
    return formatted.decode("utf-8")


@overload
def decode_json[T](payload: str | bytes | bytearray | memoryview, *, target_type: type[T]) -> T: ...


@overload
def decode_json(payload: str | bytes | bytearray | memoryview, *, target_type: None = None) -> Any: ...


def decode_json[T](
    payload: str | bytes | bytearray | memoryview,
    *,
    target_type: type[T] | None = None,
) -> T | Any:
    """Deserialize a JSON string or byte buffer into target_type or generic Python primitives."""
    if target_type is None:
        return _DECODER.decode(payload)
    return msgspec.json.decode(payload, type=target_type, dec_hook=_default_dec_hook)


def _default_enc_hook(obj: Any) -> Any:
    """Encode non-native domain types into JSON-compatible primitives."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (Path, UUID)):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    if hasattr(obj, "as_str") and callable(obj.as_str):
        return obj.as_str()
    if hasattr(obj, "dsl"):
        return obj.dsl
    if hasattr(obj, "id"):
        return str(obj.id)
    if hasattr(obj, "tolist") and callable(obj.tolist):
        return obj.tolist()
    if hasattr(obj, "item") and callable(obj.item):
        return obj.item()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _default_dec_hook(target_type: type[Any], obj: Any) -> Any:
    """Decode custom domain types during typed msgspec deserialization."""
    if target_type is Decimal and isinstance(obj, (str, int, float)):
        return Decimal(str(obj))
    if target_type is Path and isinstance(obj, str):
        return Path(obj)
    if hasattr(target_type, "from_str") and callable(target_type.from_str) and isinstance(obj, str):
        return target_type.from_str(obj)
    raise TypeError(f"Cannot decode {type(obj).__name__} into {target_type}")


_ENCODER = msgspec.json.Encoder(enc_hook=_default_enc_hook)
_DECODER = msgspec.json.Decoder()

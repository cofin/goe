# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""ExecutionId: Orchestration execution identifier generated and converted from/to str/bytes."""

from __future__ import annotations

import uuid
from typing import Any

__all__ = [
    "ExecutionId",
]


class ExecutionId:
    """Orchestration execution identifier generated and converted from/to str/bytes."""

    __slots__ = ("id",)

    def __init__(self, **kwargs: Any) -> None:
        self.id: uuid.UUID | None
        if "from_str" in kwargs:
            self.id = self._str_as_uuid(kwargs["from_str"])
        elif "from_bytes" in kwargs:
            self.id = self._bytes_as_uuid(kwargs["from_bytes"])
        elif "from_uuid" in kwargs:
            self.id = self._uuid_as_uuid(kwargs["from_uuid"])
        else:
            self.id = self._new_id()

    def __repr__(self) -> str:
        return f"ExecutionId(id={self.id!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExecutionId):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __str__(self) -> str:
        return self.as_str()

    def __bytes__(self) -> bytes:
        return self.as_bytes()

    @staticmethod
    def from_str(s: str | None) -> ExecutionId:
        """Construct an ExecutionId from a 36-character UUID string."""
        return ExecutionId(from_str=s)

    @staticmethod
    def from_bytes(b: bytes | None) -> ExecutionId:
        """Construct an ExecutionId from 16 raw UUID bytes."""
        return ExecutionId(from_bytes=b)

    @staticmethod
    def from_uuid(u: uuid.UUID | None) -> ExecutionId:
        """Construct an ExecutionId from a uuid.UUID instance."""
        return ExecutionId(from_uuid=u)

    def as_str(self) -> str:
        """Return the string representation of the UUID."""
        return str(self.id)

    def as_bytes(self) -> bytes:
        """Return the 16-byte raw representation of the UUID."""
        assert self.id is not None
        return self.id.bytes

    @staticmethod
    def _bytes_as_uuid(b: bytes | None) -> uuid.UUID | None:
        if b is None:
            return None
        assert isinstance(b, bytes)
        assert len(b) == 16
        return uuid.UUID(bytes=b)

    @staticmethod
    def _str_as_uuid(s: str | None) -> uuid.UUID | None:
        if s is None:
            return None
        assert isinstance(s, str)
        assert len(s) == 36, f"len(str) ({len(s)}) != 36"
        return uuid.UUID(s)

    @staticmethod
    def _uuid_as_uuid(u: uuid.UUID | None) -> uuid.UUID | None:
        if u is None:
            return None
        assert isinstance(u, uuid.UUID)
        return u

    @staticmethod
    def _new_id() -> uuid.UUID:
        return uuid.uuid4()

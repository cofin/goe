# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Transport protocol, value objects, and exceptions for GOE offload transport."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from goe.exceptions import GOEError
from goe.typing import FrozenBaseStruct, WireFrameStruct


class OffloadTransportException(GOEError):
    """Exception raised when an offload transport operation or validation fails."""


class TransportBatchSplit(WireFrameStruct, frozen=True, array_like=True):
    """Single parallel extraction split specification."""

    split_id: int
    predicate: str
    lower_bound: str | int | None = None
    upper_bound: str | int | None = None


class TransportPlan(FrozenBaseStruct, frozen=True):
    """Transport execution plan describing target staging and parallelism."""

    method: str
    parallelism: int
    staging_format: str
    target_uris: tuple[str, ...] = ()
    splits: tuple[TransportBatchSplit, ...] = ()
    compression_codec: str | None = None


class TransportExecutionSummary(FrozenBaseStruct, frozen=True):
    """Summary metrics produced by an offload transport execution."""

    method: str
    rows_transported: int
    bytes_staged: int = 0
    files_written: int = 0
    elapsed_seconds: float = 0.0
    metadata: dict[str, Any] = {}


@runtime_checkable
class OffloadTransportProtocol(Protocol):
    """Structural protocol implemented by all offload transport engines."""

    def transport(self, partition_chunk: Any = None) -> int | None:
        """Execute data transport for the given partition chunk and return row count."""
        ...

    def ping_source_rdbms(self) -> bool:
        """Verify connectivity from the transport tier to the source RDBMS."""
        ...


__all__ = [
    "OffloadTransportException",
    "OffloadTransportProtocol",
    "TransportBatchSplit",
    "TransportExecutionSummary",
    "TransportPlan",
]

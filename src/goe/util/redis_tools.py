# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Deprecated Redis client compatibility shim."""

import warnings
from typing import Any

from goe.listener.utils.cache import MemorySyncCache

warnings.warn(
    "goe.util.redis_tools is deprecated and will be removed in GOE 2.0.0; "
    "use goe.listener.utils.cache.MemorySyncCache instead.",
    DeprecationWarning,
    stacklevel=2,
)


class RedisClient(MemorySyncCache):
    """Deprecated synchronous cache shim backed by MemorySyncCache."""

    @classmethod
    def connect(cls, redis_connection_kwargs: dict[str, Any] | None = None) -> type["RedisClient"]:
        """Return the synchronous in-memory cache shim."""
        warnings.warn(
            "RedisClient.connect() is deprecated and will be removed in GOE 2.0.0; "
            "use goe.listener.utils.cache.MemorySyncCache instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls


cache = RedisClient

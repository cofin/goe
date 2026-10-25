# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Lost-session detection and single-retry policy for pooled Oracle sessions.

A lost session is a killed (``ORA-00028``), idle-sniped (``ORA-02396``), or disconnected (``ORA-03113``,
``ORA-03114``, ``ORA-03135``, ``DPY-1001``, ``DPY-4011``) session, reported padded or unpadded by python-oracledb
or embedded in a SQLSpec exception message or cause chain. The retry runs after the ``except`` block has exited so
MyPyC-compiled SQLSpec drivers never execute while an exception is active.
"""

import logging
import re
from collections.abc import Callable
from typing import Final

__all__ = ("LOST_SESSION_PATTERN", "is_lost_session_error", "run_with_session_retry")

logger = logging.getLogger(__name__)

LOST_SESSION_PATTERN: Final = re.compile(r"\b(?:ORA-0*(?:28|2396|3113|3114|3135)|DPY-(?:1001|4011))\b")
_MAX_CAUSE_DEPTH: Final = 8


def is_lost_session_error(exc: BaseException) -> bool:
    """Return True when ``exc`` or an exception in its cause or context chain reports a lost Oracle session.

    Args:
        exc: The exception raised by python-oracledb or SQLSpec.

    Returns:
        True for the lost-session codes listed in the module docstring, otherwise False.
    """
    current: BaseException | None = exc
    for _ in range(_MAX_CAUSE_DEPTH):
        if current is None:
            return False
        if LOST_SESSION_PATTERN.search(str(current)):
            return True
        current = current.__cause__ or current.__context__
    return False


def run_with_session_retry[T](operation: Callable[[], T], on_retry: Callable[[BaseException], None] | None = None) -> T:
    """Run ``operation`` and retry it once after a lost-session error, outside the ``except`` block.

    Args:
        operation: Zero-argument callable that acquires its own session and returns a result.
        on_retry: Optional callback receiving the first failure before the retry, for example to renew a lease.

    Returns:
        The result of the first successful attempt.

    Raises:
        Exception: Any non lost-session error from the first attempt, or any error from the retry.
    """
    failure: BaseException | None = None
    try:
        return operation()
    except Exception as exc:
        if not is_lost_session_error(exc):
            raise
        failure = exc
    logger.info("Retrying Oracle operation after lost session: %s", failure)
    if on_retry is not None:
        on_retry(failure)
    return operation()

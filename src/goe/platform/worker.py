# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Container-aware cgroup quotas, lame-duck drain control, and local process worker helpers."""

import math
import os
import tempfile
import threading
from collections.abc import Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from goe.typing import FrozenBaseStruct
from goe.util.subprocess_utils import CommandResult, run_checked_cmd

__all__ = [
    "CgroupQuota",
    "LameDuckController",
    "LocalProcessWorker",
]

_DEFAULT_CGROUP_ROOT = Path("/sys/fs/cgroup")
_DEFAULT_MAX_SPOOL_BYTES = 16 * 1024 * 1024


class CgroupQuota(FrozenBaseStruct, frozen=True):
    """Detected CPU and memory quota for the current host or Linux cgroup v2 container."""

    effective_cpus: int
    effective_memory_bytes: int

    @classmethod
    def detect(cls, *, cgroup_root: str | Path = _DEFAULT_CGROUP_ROOT) -> "CgroupQuota":
        """Inspect cgroup v2 cpu.max and memory.max files with fallback to host OS limits."""
        root = Path(cgroup_root)
        cpus = _parse_cgroup_cpus(root / "cpu.max") or (os.cpu_count() or 1)
        memory_bytes = _parse_cgroup_memory(root / "memory.max") or _host_memory_bytes()
        return cls(effective_cpus=max(1, cpus), effective_memory_bytes=max(256 * 1024 * 1024, memory_bytes))

    @property
    def recommended_duckdb_memory_limit(self) -> str:
        """Return a 75% clamped memory limit string in MB suitable for DuckDB."""
        clamped_mb = max(128, int((self.effective_memory_bytes * 0.75) // (1024 * 1024)))
        return f"{clamped_mb}MB"

    @property
    def recommended_workers(self) -> int:
        """Return a bounded worker thread count derived from effective CPUs."""
        return max(1, min(32, self.effective_cpus))


class LameDuckController:
    """Thread-safe controller coordinating graceful drain on shutdown signals."""

    def __init__(self) -> None:
        self._draining = threading.Event()

    @property
    def is_draining(self) -> bool:
        """Return True when the process has entered lame-duck draining state."""
        return self._draining.is_set()

    def enter_lame_duck(self) -> None:
        """Transition the controller into lame-duck draining mode."""
        self._draining.set()


class LocalProcessWorker:
    """Local process execution and spooled temporary buffer manager."""

    def __init__(self, *, max_spool_bytes: int = _DEFAULT_MAX_SPOOL_BYTES) -> None:
        self._max_spool_bytes = max_spool_bytes

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        check: bool = True,
        input_text: str | None = None,
        redact_tokens: Iterable[str] = (),
    ) -> CommandResult:
        """Execute a local command via run_checked_cmd."""
        return run_checked_cmd(
            cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
            check=check,
            input_text=input_text,
            redact_tokens=redact_tokens,
        )

    @contextmanager
    def spooled_buffer(
        self,
        *,
        max_size: int | None = None,
    ) -> Generator[tempfile.SpooledTemporaryFile[bytes], None, None]:
        """Yield a SpooledTemporaryFile that stays in RAM up to max_size before spilling to disk."""
        limit = self._max_spool_bytes if max_size is None else max_size
        with tempfile.SpooledTemporaryFile(max_size=limit, mode="w+b") as handle:
            yield handle


def _parse_cgroup_cpus(cpu_max_path: Path) -> int | None:
    """Parse effective CPU count from a cgroup v2 cpu.max file."""
    try:
        raw = cpu_max_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    parts = raw.split()
    if len(parts) != 2 or parts[0] == "max":
        return None
    try:
        quota = int(parts[0])
        period = int(parts[1])
    except ValueError:
        return None
    if quota <= 0 or period <= 0:
        return None
    return max(1, math.ceil(quota / period))


def _parse_cgroup_memory(memory_max_path: Path) -> int | None:
    """Parse byte limit from a cgroup v2 memory.max file."""
    try:
        raw = memory_max_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or raw == "max":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _host_memory_bytes() -> int:
    """Determine physical host memory bytes via os.sysconf."""
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if pages > 0 and page_size > 0:
            return pages * page_size
    except (ValueError, OSError, AttributeError):
        pass
    return 4 * 1024 * 1024 * 1024

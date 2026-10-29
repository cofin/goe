# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for LocalProcessWorker, CgroupQuota, and LameDuckController."""

import sys
from pathlib import Path

from goe.platform.worker import CgroupQuota, LameDuckController, LocalProcessWorker
from goe.typing import FrozenBaseStruct


def test_local_process_worker_executes_command_and_spools_output() -> None:
    """LocalProcessWorker executes checked commands and provides spooled byte buffers."""
    worker = LocalProcessWorker()
    result = worker.run([sys.executable, "-c", "import sys; sys.stdout.write('hello')"])
    assert result.returncode == 0
    assert result.stdout == "hello"

    with worker.spooled_buffer(max_size=1024) as buf:
        buf.write(b"payload-bytes")
        buf.seek(0)
        assert buf.read() == b"payload-bytes"


def test_cgroup_quota_parses_limits_and_clamps_duckdb_memory(tmp_path: Path) -> None:
    """CgroupQuota parses cgroup v2 cpu.max and memory.max and clamps DuckDB memory at 75%."""
    assert issubclass(CgroupQuota, FrozenBaseStruct)
    (tmp_path / "cpu.max").write_text("200000 100000\n", encoding="utf-8")
    (tmp_path / "memory.max").write_text("4294967296\n", encoding="utf-8")

    quota = CgroupQuota.detect(cgroup_root=tmp_path)
    assert quota.effective_cpus == 2
    assert quota.effective_memory_bytes == 4294967296
    assert quota.recommended_duckdb_memory_limit == "3072MB"
    assert quota.recommended_workers == 2


def test_lame_duck_controller_transitions_to_draining() -> None:
    """LameDuckController transitions cleanly into draining state."""
    controller = LameDuckController()
    assert controller.is_draining is False
    controller.enter_lame_duck()
    assert controller.is_draining is True

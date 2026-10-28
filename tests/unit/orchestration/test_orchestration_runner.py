# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for stateless OrchestrationRunner and concurrent command isolation."""

from __future__ import annotations

import threading
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from goe.offload.offload_messages import OffloadMessages
from goe.orchestration import orchestration_runner as runner_mod
from goe.orchestration.context import current_execution_context
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.orchestration_runner import OrchestrationRunner
from goe.orchestration.sinks import ExecutionEvent, LogEvent
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


class _RecordingSink:
    """In-memory ExecutionSink that records emitted events."""

    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    def emit(self, event: ExecutionEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass


def test_runner_has_no_per_command_instance_state_and_deletes_hybrid_length_helper() -> None:
    """Verify OrchestrationRunner has no per-command instance state and removes _get_max_hybrid_identifier_length."""
    settings = build_mock_options(FAKE_ORACLE_BQ_ENV)
    with patch.object(runner_mod, "ensure_observability"):
        runner = OrchestrationRunner(settings=settings)

    assert not hasattr(runner, "_execution_id")
    assert not hasattr(runner, "_messages")
    assert not hasattr(runner, "_max_hybrid_name_length")
    assert not hasattr(runner, "_get_max_hybrid_identifier_length")


def test_concurrent_offloads_on_one_runner_isolate_execution_id_messages_and_sinks() -> None:
    """Verify concurrent offloads isolate ExecutionId, OffloadMessages, repository command calls, and sinks."""
    settings = build_mock_options(FAKE_ORACLE_BQ_ENV)
    sink_a = _RecordingSink()
    sink_b = _RecordingSink()
    id_a = ExecutionId()
    id_b = ExecutionId()
    barrier = threading.Barrier(2)

    repo_a = MagicMock()
    repo_a.start_command.return_value = 101
    repo_b = MagicMock()
    repo_b.start_command.return_value = 202

    seen_context_ids: dict[ExecutionId, ExecutionId | None] = {}
    seen_message_ids: dict[ExecutionId, Any] = {}

    def _fake_offload_table(
        cfg: Any,
        operation: Any,
        source_table: Any,
        target_table: Any,
        messages: OffloadMessages,
    ) -> bool:
        del cfg, operation, source_table, target_table
        barrier.wait()
        active_ctx = current_execution_context()
        exec_id = messages.execution_id
        seen_context_ids[exec_id] = active_ctx.execution_id if active_ctx else None
        seen_message_ids[exec_id] = messages.execution_id
        messages.log(f"run-{exec_id}")
        return True

    def _run_branch(
        exec_id: ExecutionId,
        sink: _RecordingSink,
        repo: MagicMock,
    ) -> None:
        runner = OrchestrationRunner(settings=settings, sinks=(sink,))
        op = Mock(owner="SH", table_name="SALES", execute=False)
        op.vars.return_value = {"owner_table": "SH.SALES"}
        src_table = MagicMock(owner="SH", table_name="SALES")
        tgt_table = MagicMock()
        tgt_table.backend_db_name.return_value = "BigQuery"
        tgt_table.target_version.return_value = "1.0"

        with (
            patch.object(runner, "_build_repo_client", return_value=repo),
            patch.object(runner, "_gen_offload_operation", return_value=op),
            patch.object(runner, "_build_offload_source_table", return_value=src_table),
        ):
            runner.offload(
                params={"owner_table": "SH.SALES", "execute": False},
                execution_id=exec_id,
                reuse_log=True,
            )

    with (
        patch.object(runner_mod, "ensure_observability"),
        patch.object(runner_mod, "init"),
        patch.object(runner_mod, "get_offload_target_table") as mock_get_target,
        patch.object(runner_mod, "orchestration_lock_for_table", side_effect=lambda *_a, **_k: nullcontext()),
        patch.object(runner_mod, "offload_table", side_effect=_fake_offload_table),
    ):
        mock_target = MagicMock()
        mock_target.backend_db_name.return_value = "BigQuery"
        mock_target.target_version.return_value = "1.0"
        mock_get_target.return_value = mock_target

        t_a = threading.Thread(target=_run_branch, args=(id_a, sink_a, repo_a))
        t_b = threading.Thread(target=_run_branch, args=(id_b, sink_b, repo_b))
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()

    assert seen_context_ids[id_a] == id_a
    assert seen_context_ids[id_b] == id_b
    assert seen_message_ids[id_a] == id_a
    assert seen_message_ids[id_b] == id_b
    assert repo_a.start_command.call_args.args[0] == id_a
    assert repo_b.start_command.call_args.args[0] == id_b

    lines_a = [e.line for e in sink_a.events if isinstance(e, LogEvent)]
    lines_b = [e.line for e in sink_b.events if isinstance(e, LogEvent)]
    assert f"run-{id_a}" in lines_a
    assert f"run-{id_b}" not in lines_a
    assert f"run-{id_b}" in lines_b
    assert f"run-{id_a}" not in lines_b

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for offload execution settings derivation, target validation, and concurrency isolation."""

from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from goe.exceptions import OffloadException
from goe.offload.offload_messages import NORMAL, OffloadMessages
from goe.orchestration import pipeline as execution_mod
from goe.orchestration.context import ExecutionContext, bind_execution_context, current_execution_context
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.logging_init import log
from goe.orchestration.pipeline import (
    derive_execution_settings,
    get_offload_target_table,
    offload_table,
)
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_offload_table_rejects_unsupported_target() -> None:
    """Verify offload_table raises OffloadException when target is not in SUPPORTED_OFFLOAD_TARGETS."""
    config = copy.copy(build_mock_options(FAKE_ORACLE_BQ_ENV))
    config.target = "unsupported_backend"
    messages = OffloadMessages()
    source = Mock(columns=[], owner="SH", table_name="SALES")
    target = Mock()
    target.identifier_contains_invalid_characters.return_value = None
    target.get_backend_api.return_value.valid_offload_fs_schemes.return_value = ["gs"]
    operation = Mock(
        offload_fs_scheme=None,
        offload_fs_container=None,
        offload_fs_prefix="override_prefix",
        target_owner_name="SH.SALES",
        execute=False,
        ver_check=False,
    )

    with (
        patch.object(execution_mod, "version_abort", return_value=(False, "1.0", "1.0")),
        pytest.raises(OffloadException, match="Unsupported Offload target: unsupported_backend"),
    ):
        offload_table(config, operation, source, target, messages)


def test_offload_table_does_not_mutate_settings() -> None:
    """Verify offload_table does not mutate caller settings in place when applying filesystem overrides."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    original_prefix = config.offload_fs_prefix
    messages = OffloadMessages()
    source = Mock(columns=[], owner="SH", table_name="SALES")
    target = Mock()
    target.identifier_contains_invalid_characters.return_value = None
    target.get_backend_api.return_value.valid_offload_fs_schemes.return_value = ["gs"]
    operation = Mock(
        offload_fs_scheme=None,
        offload_fs_container=None,
        offload_fs_prefix="override_prefix",
        target_owner_name="SH.SALES",
        execute=False,
        ver_check=False,
    )

    with patch.object(execution_mod, "version_abort", return_value=(False, "1.0", "1.0")):
        result = offload_table(config, operation, source, target, messages)

    assert result is False
    assert config.offload_fs_prefix == original_prefix


def test_derive_execution_settings_applies_operation_overrides() -> None:
    """Verify derive_execution_settings returns a copy with overrides applied and returns original when none exist."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    original_prefix = config.offload_fs_prefix

    operation_with_override = Mock(
        offload_fs_scheme=None,
        offload_fs_container=None,
        offload_fs_prefix="override_prefix",
    )
    derived = derive_execution_settings(config, operation_with_override)
    assert derived is not config
    assert derived.offload_fs_prefix == "override_prefix"
    assert config.offload_fs_prefix == original_prefix

    operation_no_override = Mock(
        offload_fs_scheme=None,
        offload_fs_container=None,
        offload_fs_prefix=None,
    )
    unchanged = derive_execution_settings(config, operation_no_override)
    assert unchanged is config


def test_get_offload_target_table_uses_derived_settings() -> None:
    """Verify get_offload_target_table passes derived execution settings to create_backend_table."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    original_prefix = config.offload_fs_prefix
    messages = OffloadMessages()
    operation = Mock(
        offload_fs_scheme=None,
        offload_fs_container=None,
        offload_fs_prefix="override_prefix",
        target_owner="SH",
        target_name="SALES",
    )
    operation.get_hybrid_metadata.return_value = None

    with (
        patch.object(execution_mod, "check_and_set_nls_lang"),
        patch.object(execution_mod, "create_backend_table") as mock_create_backend,
    ):
        get_offload_target_table(operation, config, messages)

    mock_create_backend.assert_called_once()
    passed_settings = mock_create_backend.call_args.args[3]
    assert passed_settings is not config
    assert passed_settings.offload_fs_prefix == "override_prefix"
    assert config.offload_fs_prefix == original_prefix


def test_concurrent_offload_executions_do_not_cross_contaminate_logs_or_ids(tmp_path: Path) -> None:
    """Verify 4 concurrent worker threads isolate ExecutionId and log files without cross-talk."""
    barrier = threading.Barrier(4)

    def _run_worker(worker_idx: int) -> tuple[str, str]:
        worker_dir = tmp_path / f"worker_{worker_idx}"
        worker_dir.mkdir(parents=True, exist_ok=True)
        exec_id = ExecutionId()
        ctx = ExecutionContext.for_console(
            detail=NORMAL,
            ansi=False,
            execution_id=exec_id,
            command_type="OFFLOAD",
            log_dir=str(worker_dir),
        ).with_log_file(f"offload_worker_{worker_idx}")

        with bind_execution_context(ctx):
            messages = OffloadMessages.from_context(ctx)
            barrier.wait()
            log(f"logging_init_from_worker_{worker_idx}")
            messages.log(f"messages_from_worker_{worker_idx}")
            active = current_execution_context()
            assert active is not None
            assert active.execution_id == exec_id
            log_path = ctx.log_path
            assert log_path is not None
            ctx.close()
            return str(exec_id), Path(log_path).read_text(encoding="utf-8")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_run_worker, range(4)))

    seen_ids = {exec_id for exec_id, _ in results}
    assert len(seen_ids) == 4
    for idx, (_, content) in enumerate(results):
        assert f"logging_init_from_worker_{idx}" in content
        assert f"messages_from_worker_{idx}" in content
        for other_idx in range(4):
            if other_idx != idx:
                assert f"worker_{other_idx}" not in content

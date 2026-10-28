# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for CLI orchestration entrypoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from goe.orchestration import cli_entry_points
from goe.orchestration.cli_entry_points import offload_by_cli


def test_offload_by_cli_builds_settings_once_and_passes_to_runner() -> None:
    """Verify offload_by_cli builds OrchestrationConfig once and passes settings=config to OrchestrationRunner."""
    options = SimpleNamespace(
        owner_table="SH.SALES",
        verbose=False,
        vverbose=False,
        offload_transport_dsn=None,
        error_on_token=None,
        operation_name=None,
    )
    mock_config = MagicMock()
    mock_runner = MagicMock()

    with (
        patch.object(cli_entry_points, "ensure_observability"),
        patch.object(cli_entry_points, "init"),
        patch.object(cli_entry_points, "init_log"),
        patch.object(cli_entry_points, "log"),
        patch.object(cli_entry_points, "log_command_line"),
        patch.object(cli_entry_points, "log_close"),
        patch.object(cli_entry_points, "normalise_options"),
        patch.object(cli_entry_points, "get_log_fh_name", return_value="/tmp/offload.log"),
        patch.object(cli_entry_points, "version", return_value="6.0.0"),
        patch.object(cli_entry_points.OrchestrationConfig, "from_dict", return_value=mock_config) as mock_from_dict,
        patch.object(cli_entry_points, "OrchestrationRunner", return_value=mock_runner) as mock_runner_cls,
    ):
        offload_by_cli(options)

    mock_from_dict.assert_called_once()
    mock_runner_cls.assert_called_once_with(settings=mock_config)
    mock_runner.offload.assert_called_once_with(
        options,
        reuse_log=True,
        messages_override=None,
    )

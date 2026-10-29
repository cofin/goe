# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe sync, goe report, and Listener system service delegation."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli
from goe.listener.services.system import SystemService
from goe.report import StatusReportService, TableStatusReport
from goe.sync import (
    SchemaDiff,
    SchemaSyncService,
    SourceColumnSnapshot,
    TargetColumnSnapshot,
)


def test_goe_sync_cli_invokes_schema_sync_service_and_returns_zero(tmp_path: Path) -> None:
    """Verify goe sync CLI dispatches to SchemaSyncService with execute=False/True and writes command file."""
    cmd_file = tmp_path / "sync_cmds.txt"
    runner = CliRunner()
    with (
        patch("goe.cli.commands.sync.init", create=True),
        patch("goe.cli.commands.sync.init_log", create=True),
        patch("goe.cli.commands.sync.log_close", create=True),
        patch("goe.cli.commands.sync.get_log_fh", return_value=None, create=True),
        patch("goe.cli.commands.sync.OrchestrationConfig.from_dict"),
        patch("goe.cli.commands.sync.OffloadMessages.from_options"),
        patch("goe.cli.commands.sync.create_repository_client"),
    ):
        result_preview = runner.invoke(
            cli,
            ["sync", "--include", "SH.SALES", "--command-file", str(cmd_file)],
        )
        assert result_preview.exit_code == 0
        assert cmd_file.exists()

        with patch.object(SchemaSyncService, "run_from_options", return_value=0) as mock_run:
            result_exec = runner.invoke(
                cli,
                ["sync", "--include", "SH.SALES", "-x", "--command-file", str(cmd_file)],
            )
            assert result_exec.exit_code == 0
            mock_run.assert_called_once()
            options = mock_run.call_args[0][0]
            assert options.execute is True
            assert options.include == "SH.SALES"


def test_goe_sync_cli_exits_nonzero_on_unhandled_sync_error() -> None:
    """Verify goe sync CLI exits with code 1 when SchemaSyncService raises an unhandled error."""
    runner = CliRunner()
    with (
        patch("goe.cli.commands.sync.init", create=True),
        patch("goe.cli.commands.sync.init_log", create=True),
        patch("goe.cli.commands.sync.log_close", create=True),
        patch("goe.cli.commands.sync.get_log_fh", return_value=None, create=True),
        patch("goe.cli.commands.sync.OrchestrationConfig.from_dict"),
        patch("goe.cli.commands.sync.OffloadMessages.from_options"),
        patch("goe.cli.commands.sync.create_repository_client"),
        patch.object(SchemaSyncService, "run_from_options", side_effect=RuntimeError("sync failed")),
    ):
        result = runner.invoke(cli, ["sync", "--include", "SH.SALES"])
    assert result.exit_code == 1


def test_goe_report_cli_demo_and_json_modes_delegate_to_status_report_service(tmp_path: Path) -> None:
    """Verify goe report CLI dispatches --demo -o JSON and -s SH -t SALES -o TEXT --output-level detail."""
    envelope = StatusReportService.load_demo_envelope(schema="SH", table="COSTS")
    assert envelope.total_tables == 1
    assert envelope.tables[0].schema_name == "SH"
    assert envelope.tables[0].table_name == "COSTS"

    runner = CliRunner()
    with patch("goe.cli.commands.report.StatusReportService.run_from_options") as mock_run:
        res_demo = runner.invoke(
            cli,
            [
                "report",
                "--demo",
                "-o",
                "JSON",
                "--report-directory",
                str(tmp_path),
            ],
        )
        assert res_demo.exit_code == 0
        opts_demo = mock_run.call_args[0][0]
        assert opts_demo.demo_mode is True
        assert opts_demo.output_format == "JSON"

        res_detail = runner.invoke(
            cli,
            [
                "report",
                "-s",
                "SH",
                "-t",
                "SALES",
                "-o",
                "TEXT",
                "--output-level",
                "detail",
            ],
        )
        assert res_detail.exit_code == 0
        opts_detail = mock_run.call_args[0][0]
        assert opts_detail.schema == "SH"
        assert opts_detail.table == "SALES"
        assert opts_detail.output_format == "TEXT"
        assert opts_detail.output_level == "detail"


def test_listener_system_service_delegates_status_and_schema_drift_to_services() -> None:
    """Verify Listener SystemService returns TableStatusReport and SchemaDiff via StatusReportService and SchemaSyncService."""
    sys_service = SystemService(config=None)
    sys_service.config = None
    status = sys_service.get_table_offload_status("SH", "COSTS")
    assert isinstance(status, TableStatusReport)
    assert status.schema_name == "SH"
    assert status.table_name == "COSTS"
    assert status.offloaded_rows > 0

    diff = sys_service.preview_schema_drift(
        "SH",
        "SALES",
        source_columns=[
            SourceColumnSnapshot(name="ID", data_type="INT64", nullable=False),
            SourceColumnSnapshot(name="PROMO_CODE", data_type="STRING", nullable=True),
        ],
        target_columns=[
            TargetColumnSnapshot(name="ID", data_type="INT64", nullable=False),
        ],
    )
    assert isinstance(diff, SchemaDiff)
    assert diff.has_changes is True
    assert len(diff.additions) == 1
    assert diff.additions[0].column_name == "PROMO_CODE"

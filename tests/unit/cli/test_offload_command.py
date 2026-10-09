# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the goe offload CLI subcommand and option groups."""

from unittest.mock import MagicMock, patch

import rich_click as click
from click.testing import CliRunner

from goe.cli.commands.offload import offload
from goe.cli.main import cli


def test_offload_help() -> None:
    """Verify goe offload --help displays option groups and flags."""
    runner = CliRunner()
    result = runner.invoke(cli, ["offload", "--help"])
    assert result.exit_code == 0
    assert "--table" in result.output
    assert "--execute" in result.output
    assert "--offload-type" in result.output
    assert "--older-than-date" in result.output
    assert "Target & Source Selection" in result.output


def test_offload_all_option_group_flags_defined() -> None:
    """Verify every flag listed in OPTION_GROUPS['goe offload'] is defined on the offload command."""
    defined_opts: set[str] = set()
    for param in offload.params:
        defined_opts.update(param.opts)
        defined_opts.update(param.secondary_opts)

    for group in click.rich_click.OPTION_GROUPS["goe offload"]:
        for flag in group["options"]:
            assert flag in defined_opts, f"Missing CLI flag on goe offload: {flag}"


def test_offload_missing_required_table() -> None:
    """Verify goe offload requires -t/--table."""
    runner = CliRunner()
    result = runner.invoke(cli, ["offload"])
    assert result.exit_code != 0
    assert "Missing option" in result.output or "required" in result.output.lower()


@patch("goe.cli.commands.offload.offload_by_cli")
def test_offload_dispatch(mock_offload: MagicMock) -> None:
    """Verify goe offload populates both common and offload-specific options."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "offload",
            "-t",
            "SH.SALES",
            "-x",
            "--storage-format",
            "PARQUET",
            "--verify",
            "aggregate",
            "--decimal-columns",
            "AMOUNT_SOLD",
            "--decimal-columns-type",
            "18,2",
            "--no-modify-hybrid-view",
        ],
    )
    assert result.exit_code == 0
    assert mock_offload.called
    options = mock_offload.call_args[0][0]
    assert options.owner_table == "SH.SALES"
    assert options.execute is True
    assert options.storage_format == "PARQUET"
    assert options.verify_row_count == "aggregate"
    assert options.decimal_columns_csv_list == ["AMOUNT_SOLD"]
    assert options.decimal_columns_type_list == ["18,2"]
    assert options.offload_predicate_modify_hybrid_view is False
    assert hasattr(options, "allow_decimal_scale_rounding")


@patch("goe.cli.commands.offload.offload_by_cli")
def test_offload_missing_options_and_older_than_days_str_type(mock_offload: MagicMock) -> None:
    """Verify goe offload accepts all 12 restored options, common options, and passes --older-than-days as str."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "offload",
            "-t",
            "SH.SALES",
            "-x",
            "-v",
            "--older-than-days",
            "30",
            "--bucket-hash-column",
            "PROD_ID",
            "--hive-column-stats",
            "--offload-stats",
            "COPY",
            "--offload-chunk-impala-insert-hint",
            "SHUFFLE",
            "--not-null-propagation",
            "AUTO",
            "--dev-log",
            "stdout",
            "--dev-log-level",
            "DEBUG",
            "--transform-column",
            "COL1=ENCRYPT()",
            "--offload-transport-validation-polling-interval",
            "5",
            "--sqoop-additional-options",
            "--direct",
            "--sqoop-mapreduce-map-memory-mb",
            "4096",
            "--sqoop-mapreduce-map-java-opts",
            "-Xmx3072m",
            "--error-before-step",
            "STEP_X",
            "--no-version-check",
        ],
    )
    assert result.exit_code == 0
    assert mock_offload.called
    options = mock_offload.call_args[0][0]
    assert options.older_than_days == "30"
    assert isinstance(options.older_than_days, str)
    assert options.bucket_hash_col == "PROD_ID"
    assert options.hive_column_stats is True
    assert options.offload_stats_method == "COPY"
    assert options.impala_insert_hint == "SHUFFLE"
    assert options.not_null_propagation == "AUTO"
    assert options.dev_log == "stdout"
    assert options.dev_log_level == "DEBUG"
    assert options.column_transformation_list == ["COL1=ENCRYPT()"]
    assert options.offload_transport_validation_polling_interval == "5"
    assert options.sqoop_additional_options == "--direct"
    assert options.sqoop_mapreduce_map_memory_mb == 4096
    assert options.sqoop_mapreduce_map_java_opts == "-Xmx3072m"
    assert options.verbose is True
    assert options.ver_check is False
    assert options.error_before_step == "STEP_X"
    assert isinstance(options.log_path, str) and options.log_path

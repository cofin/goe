# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from goe.cli.main import cli
from goe.scripts import agg_validate


def test_validate_help() -> None:
    """Verify goe validate --help renders expected options."""
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--help"])
    assert result.exit_code == 0
    assert "--table" in result.output
    assert "--target-name" in result.output
    assert "--selects" in result.output
    assert "--filters" in result.output
    assert "--aggregate-functions" in result.output


def test_validate_missing_table() -> None:
    """Verify goe validate requires -t/--table."""
    runner = CliRunner()
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code != 0
    assert "Missing option" in result.output or "required" in result.output.lower()


@patch("goe.cli.commands.validate.run_agg_validate")
def test_validate_dispatch(mock_validate) -> None:
    """Verify goe validate runs post_process_args on selects and exits 0 when run_agg_validate returns True."""
    mock_validate.return_value = True
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "-t", "SH.SALES", "-S", "AMOUNT_SOLD"])
    assert result.exit_code == 0
    assert mock_validate.called
    options = mock_validate.call_args[0][0]
    assert options.owner_table == "SH.SALES"
    assert options.selects == ["AMOUNT_SOLD"]
    assert options.execute is False
    assert isinstance(options.log_path, str) and options.log_path


@patch("goe.cli.commands.validate.run_agg_validate")
def test_validate_execute_flag(mock_validate) -> None:
    """Verify goe validate -x sets options.execute to True."""
    mock_validate.return_value = True
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "-t", "SH.SALES", "-x"])
    assert result.exit_code == 0
    options = mock_validate.call_args[0][0]
    assert options.execute is True


@patch("goe.cli.commands.validate.run_agg_validate")
def test_validate_post_process_args_and_common_options(mock_validate) -> None:
    """Verify goe validate post-processes filters, selects, group-bys, aggs, target-name, as-of-scn, and common options."""
    mock_validate.return_value = True
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "validate",
            "-t",
            "SH.SALES",
            "--target-name",
            "prod_sh.sales",
            "-F",
            "TIME_ID > 100",
            "-S",
            "AMOUNT_SOLD,QUANTITY_SOLD",
            "-G",
            "CHANNEL_ID",
            "-A",
            "MIN,MAX",
            "--as-of-scn",
            "12345",
            "--dev-log-level",
            "DEBUG",
            "-v",
        ],
    )
    assert result.exit_code == 0
    options = mock_validate.call_args[0][0]
    assert options.target_owner_name == "prod_sh.sales"
    assert options.filters == [("TIME_ID", ">", 100)]
    assert options.selects == ["AMOUNT_SOLD", "QUANTITY_SOLD"]
    assert options.group_bys == ["CHANNEL_ID"]
    assert options.aggregate_functions == ["MIN", "MAX"]
    assert options.as_of_scn == 12345
    assert options.dev_log_level == "DEBUG"
    assert options.verbose is True


@patch("goe.cli.commands.validate.run_agg_validate", return_value=False)
def test_validate_exits_nonzero_on_failure(mock_validate) -> None:
    """Verify goe validate exits with code 1 when run_agg_validate returns False."""
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "-t", "SH.SALES"])
    assert result.exit_code == 1


def test_agg_validate_main_loads_env_before_check_config_path(monkeypatch) -> None:
    """Verify agg_validate.main() calls config_file.load_env() before config_file.check_config_path()."""
    call_order: list[str] = []
    monkeypatch.setattr(agg_validate.config_file, "load_env", lambda: call_order.append("load_env"))
    monkeypatch.setattr(
        agg_validate.config_file,
        "check_config_path",
        lambda: call_order.append("check_config_path"),
    )
    monkeypatch.setattr(agg_validate, "parse_args", lambda: object())
    monkeypatch.setattr(agg_validate, "run_agg_validate", lambda _args: True)

    with pytest.raises(SystemExit) as exc_info:
        agg_validate.main()

    assert exc_info.value.code == 0
    assert call_order == ["load_env", "check_config_path"]

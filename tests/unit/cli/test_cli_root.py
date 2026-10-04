# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the root goe CLI group and environment initialization."""

from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli
from goe.util.goe_version import goe_version


def test_cli_help() -> None:
    """Verify goe --help renders all subcommands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Gluent Offload Engine (GOE)" in result.output
    assert "offload" in result.output
    assert "connect" in result.output
    assert "validate" in result.output
    assert "sync" in result.output
    assert "listener" in result.output
    assert "logmgr" in result.output


def test_cli_version() -> None:
    """Verify goe --version prints the package version."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "goe version" in result.output
    assert goe_version() in result.output


@patch("goe.cli.main.load_env")
def test_cli_bare_invocation_loads_env(mock_load_env) -> None:
    """Verify bare goe invocation calls load_env() and displays help."""
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "Usage: goe" in result.output
    assert mock_load_env.called


def test_cli_quiet_short_flag() -> None:
    """Verify goe -q --help succeeds and exposes the short quiet flag."""
    runner = CliRunner()
    result = runner.invoke(cli, ["-q", "--help"])
    assert result.exit_code == 0
    assert "-q" in result.output
    assert "--quiet" in result.output

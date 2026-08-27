# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from click.testing import CliRunner

from goe.cli.main import cli
from goe.util.goe_version import goe_version


def test_cli_help():
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


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "goe version" in result.output
    assert goe_version() in result.output


def test_cli_bare_invocation():
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "Usage: goe" in result.output

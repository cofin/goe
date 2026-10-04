# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for shared GOE CLI common options and context extraction."""

import os
from unittest.mock import patch

import rich_click as click
from click.testing import CliRunner

from goe.cli.common import common_options, extract_common_options
from goe.cli.main import cli


def test_extract_common_options_merges_parent_and_subcommand(monkeypatch) -> None:
    """Verify extract_common_options merges root context and subcommand kwargs."""
    monkeypatch.setenv("OFFLOAD_LOGFILE", "/tmp/default_offload.log")

    @click.group()
    @common_options
    @click.pass_context
    def dummy_group(ctx: click.Context, **kwargs) -> None:
        extract_common_options(ctx, kwargs)

    captured: dict[str, object] = {}

    @dummy_group.command(name="sub")
    @common_options
    @click.pass_context
    def dummy_sub(ctx: click.Context, **kwargs) -> None:
        captured.update(extract_common_options(ctx, kwargs))

    runner = CliRunner()
    result = runner.invoke(
        dummy_group,
        [
            "-v",
            "--no-ansi",
            "sub",
            "--vv",
            "-q",
            "--log-level",
            "debug",
            "--no-version-check",
            "--error-before-step",
            "STEP_A",
            "--error-after-step",
            "STEP_B",
            "--error-on-token",
            "TOK_1",
            "--suppress-stdout",
        ],
    )
    assert result.exit_code == 0
    assert captured["verbose"] is True
    assert captured["vverbose"] is True
    assert captured["quiet"] is True
    assert captured["ansi"] is False
    assert captured["log_path"] == "/tmp/default_offload.log"
    assert captured["log_level"] == "debug"
    assert captured["ver_check"] is False
    assert captured["error_before_step"] == "STEP_A"
    assert captured["error_after_step"] == "STEP_B"
    assert captured["error_on_token"] == "TOK_1"
    assert captured["suppress_stdout"] is True


def test_extract_common_options_defaults() -> None:
    """Verify extract_common_options returns canonical default values when unset."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OFFLOAD_LOGFILE", None)
        kwargs = {
            "verbose": None,
            "vverbose": None,
            "quiet": None,
            "no_ansi": None,
            "log_path": None,
            "log_level": None,
            "ver_check": None,
            "error_before_step": None,
            "error_after_step": None,
            "error_on_token": None,
            "suppress_stdout": None,
        }
        resolved = extract_common_options(None, kwargs)
        assert resolved == {
            "verbose": False,
            "vverbose": False,
            "quiet": False,
            "ansi": True,
            "log_path": None,
            "log_level": "info",
            "ver_check": True,
            "error_before_step": None,
            "error_after_step": None,
            "error_on_token": None,
            "suppress_stdout": False,
        }
        assert kwargs == {}


@patch("goe.cli.commands.listener.httpx.get")
def test_listener_status_accepts_trailing_common_options(mock_get) -> None:
    """Verify goe listener status accepts trailing -v and --no-version-check."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = '{"status":true}'
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "status", "-v", "--no-version-check"])
    assert result.exit_code == 0
    assert "healthy" in result.output.lower()

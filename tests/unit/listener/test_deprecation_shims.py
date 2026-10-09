# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for RedisClient, redis_tools, and legacy bin/ deprecation shims."""

import importlib
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import goe.listener.utils.cache as cache_module


def test_cache_redis_client_deprecation_shim() -> None:
    """Verify accessing RedisClient on goe.listener.utils.cache emits DeprecationWarning."""
    with pytest.deprecated_call(match="RedisClient is deprecated"):
        alias = cache_module.RedisClient
    assert alias is cache_module.MemoryCache


def test_redis_tools_module_deprecation_shim() -> None:
    """Verify importing goe.util.redis_tools emits DeprecationWarning and exposes MemorySyncCache."""
    sys.modules.pop("goe.util.redis_tools", None)
    with pytest.deprecated_call(match="goe.util.redis_tools is deprecated"):
        redis_tools = importlib.import_module("goe.util.redis_tools")
    assert issubclass(redis_tools.RedisClient, cache_module.MemorySyncCache)


@pytest.mark.parametrize(
    ("script_name", "expected_subcommand"),
    [
        ("offload", "offload"),
        ("listener", "listener"),
        ("connect", "connect"),
        ("logmgr", "logmgr"),
        ("agg_validate", "validate"),
        ("offload_status_report", "report"),
        ("schema_sync", "sync"),
    ],
)
def test_legacy_bin_wrapper_deprecation(script_name: str, expected_subcommand: str) -> None:
    """Verify legacy bin/* scripts emit a GOE 2.0.0 DeprecationWarning and delegate to goe CLI."""
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "bin" / script_name

    with (
        patch("goe.cli.main.cli") as mock_cli,
        patch.object(sys, "argv", [str(script_path), "--help"]),
        pytest.deprecated_call(match="will be removed in GOE 2.0.0"),
    ):
        runpy.run_path(str(script_path), run_name="__main__")
        assert mock_cli.called
        assert sys.argv[1] == expected_subcommand

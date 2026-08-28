# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
from unittest import mock

import pytest

from goe.config.config_file import (
    CONFIG_FILE_NAME,
    STANDARD_CONFIG_PATHS,
    find_environment_file,
    get_environment_file_path,
)


def test_find_environment_file_explicit_goe_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tier 1: Explicit GOE_CONFIG_FILE points to an existing file."""
    custom_env = tmp_path / "custom.env"
    custom_env.write_text("TEST_VAR=1\n")
    monkeypatch.setenv("GOE_CONFIG_FILE", str(custom_env))
    monkeypatch.delenv("OFFLOAD_ENV_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)

    assert find_environment_file() == str(custom_env.resolve())


def test_find_environment_file_explicit_offload_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tier 1: Explicit OFFLOAD_ENV_FILE points to an existing file."""
    custom_env = tmp_path / "offload_custom.env"
    custom_env.write_text("TEST_VAR=1\n")
    monkeypatch.delenv("GOE_CONFIG_FILE", raising=False)
    monkeypatch.setenv("OFFLOAD_ENV_FILE", str(custom_env))
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)

    assert find_environment_file() == str(custom_env.resolve())


def test_find_environment_file_explicit_nonexistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tier 1: Explicit path does not exist, so discovery falls through."""
    monkeypatch.setenv("GOE_CONFIG_FILE", str(tmp_path / "missing.env"))
    monkeypatch.delenv("OFFLOAD_ENV_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)

    with mock.patch("goe.config.config_file.find_dotenv", return_value=""):
        assert find_environment_file() is None


def test_find_environment_file_offload_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tier 2: Configured OFFLOAD_HOME directory containing conf/offload.env."""
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    env_file = conf_dir / CONFIG_FILE_NAME
    env_file.write_text("TEST_VAR=2\n")

    monkeypatch.delenv("GOE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_ENV_FILE", raising=False)
    monkeypatch.setenv("OFFLOAD_HOME", str(tmp_path))

    assert find_environment_file() == str(env_file.resolve())


def test_find_environment_file_dynamic_conf_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tier 3: Dynamic search finds conf/offload.env in working directory tree."""
    monkeypatch.delenv("GOE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_ENV_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)

    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    env_file = conf_dir / CONFIG_FILE_NAME
    env_file.write_text("TEST_VAR=3\n")

    monkeypatch.chdir(tmp_path)
    assert find_environment_file() == str(env_file.resolve())


def test_find_environment_file_dynamic_root_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tier 3: Dynamic search finds offload.env in root working directory tree."""
    monkeypatch.delenv("GOE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_ENV_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)

    env_file = tmp_path / CONFIG_FILE_NAME
    env_file.write_text("TEST_VAR=4\n")

    monkeypatch.chdir(tmp_path)
    assert find_environment_file() == str(env_file.resolve())


def test_find_environment_file_standard_paths(monkeypatch: pytest.MonkeyPatch):
    """Tier 4: Standard system paths check."""
    monkeypatch.delenv("GOE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_ENV_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)

    target_path = STANDARD_CONFIG_PATHS[0]
    with (
        mock.patch("goe.config.config_file.find_dotenv", return_value=""),
        mock.patch("os.path.isfile", side_effect=lambda p: p == target_path),
    ):
        assert find_environment_file() == os.path.abspath(target_path)


def test_find_environment_file_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Returns None when no environment configuration file exists anywhere."""
    monkeypatch.delenv("GOE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_ENV_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)
    monkeypatch.chdir(tmp_path)

    with (
        mock.patch("goe.config.config_file.find_dotenv", return_value=""),
        mock.patch("os.path.isfile", return_value=False),
    ):
        assert find_environment_file() is None


def test_get_environment_file_path_delegates(monkeypatch: pytest.MonkeyPatch):
    """get_environment_file_path delegates to find_environment_file for compatibility."""
    with mock.patch("goe.config.config_file.find_environment_file", return_value="/mock/path/offload.env") as mock_find:
        result = get_environment_file_path()
        mock_find.assert_called_once()
        assert result == "/mock/path/offload.env"


def test_load_env_posix_interpolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_env expands nested variables in definition order."""
    env_file = tmp_path / "offload.env"
    env_file.write_text('BASE_VAR="hello"\nDERIVED_VAR="${BASE_VAR}_world"\nNESTED_VAR="prefix_${DERIVED_VAR}"\n')
    monkeypatch.delenv("BASE_VAR", raising=False)
    monkeypatch.delenv("DERIVED_VAR", raising=False)
    monkeypatch.delenv("NESTED_VAR", raising=False)

    from goe.config.config_file import load_env

    assert load_env(str(env_file)) is True
    assert os.environ.get("BASE_VAR") == "hello"
    assert os.environ.get("DERIVED_VAR") == "hello_world"
    assert os.environ.get("NESTED_VAR") == "prefix_hello_world"


def test_load_env_override_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_env respects override=False by default and allows override=True."""
    env_file = tmp_path / "offload.env"
    env_file.write_text("EXISTING_KEY=from_file\nNEW_KEY=from_file\n")

    monkeypatch.setenv("EXISTING_KEY", "initial_val")
    monkeypatch.delenv("NEW_KEY", raising=False)

    from goe.config.config_file import load_env

    assert load_env(str(env_file), override=False) is True
    assert os.environ.get("EXISTING_KEY") == "initial_val"
    assert os.environ.get("NEW_KEY") == "from_file"

    assert load_env(str(env_file), override=True) is True
    assert os.environ.get("EXISTING_KEY") == "from_file"


def test_load_env_auto_export_offload_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_env populates OFFLOAD_HOME when file is located inside a conf directory."""
    home_dir = tmp_path / "my_goe_home"
    conf_dir = home_dir / "conf"
    conf_dir.mkdir(parents=True)
    env_file = conf_dir / "offload.env"
    env_file.write_text("FOO=BAR\n")

    monkeypatch.delenv("OFFLOAD_HOME", raising=False)

    from goe.config.config_file import load_env

    assert load_env(str(env_file)) is True
    assert os.environ.get("OFFLOAD_HOME") == str(home_dir.resolve())


def test_load_env_no_auto_export_outside_conf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_env does not populate OFFLOAD_HOME when file is not in a conf directory."""
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    env_file = other_dir / "offload.env"
    env_file.write_text("FOO=BAR\n")

    monkeypatch.delenv("OFFLOAD_HOME", raising=False)

    from goe.config.config_file import load_env

    assert load_env(str(env_file)) is True
    assert "OFFLOAD_HOME" not in os.environ


def test_load_env_json_and_quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_env parses JSON properties and single/double quoted values intact."""
    env_file = tmp_path / "offload.env"
    env_file.write_text(
        'OFFLOAD_TRANSPORT_SPARK_PROPERTIES=\'{"spark.executor.memory": "4g"}\'\nSIMPLE_QUOTE="double quoted string"\n'
    )
    monkeypatch.delenv("OFFLOAD_TRANSPORT_SPARK_PROPERTIES", raising=False)
    monkeypatch.delenv("SIMPLE_QUOTE", raising=False)

    from goe.config.config_file import load_env

    assert load_env(str(env_file)) is True
    assert os.environ.get("OFFLOAD_TRANSPORT_SPARK_PROPERTIES") == '{"spark.executor.memory": "4g"}'
    assert os.environ.get("SIMPLE_QUOTE") == "double quoted string"


def test_load_env_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_env returns False when no configuration file can be resolved."""
    monkeypatch.delenv("GOE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_ENV_FILE", raising=False)
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)
    monkeypatch.chdir(tmp_path)

    from goe.config.config_file import load_env

    with (
        mock.patch("goe.config.config_file.find_dotenv", return_value=""),
        mock.patch("os.path.isfile", return_value=False),
    ):
        assert load_env() is False

# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import os
import re
import sys

from dotenv import find_dotenv, load_dotenv

CONFIG_FILE_NAME = "offload.env"
KEY_VALUE_PATTERN = re.compile(r"#?[ ]*([A-Z_0-9]+)=(.*)")
STANDARD_CONFIG_PATHS = (
    "/opt/goe/offload/conf/offload.env",
    "/u01/app/goe/offload/conf/offload.env",
)


def check_config_path():
    """Check OFFLOAD_HOME in top level command wrappers"""
    if not os.environ.get("OFFLOAD_HOME"):
        print("OFFLOAD_HOME environment variable missing")
        sys.exit(1)


def find_environment_file() -> str | None:
    """Discover the path to the GOE environment configuration file.

    Resolves the configuration file using a 4-tier precedence:
    1. Explicit path via GOE_CONFIG_FILE or OFFLOAD_ENV_FILE environment variables.
    2. Configured OFFLOAD_HOME directory ($OFFLOAD_HOME/conf/offload.env).
    3. Dynamic search upward from the current working directory for conf/offload.env
       or offload.env via dotenv.find_dotenv(..., usecwd=True).
    4. Standard system locations (/opt/goe/offload/... and /u01/app/goe/offload/...).

    Returns:
        The absolute path to the configuration file if found, otherwise None.
    """
    explicit_file = os.environ.get("GOE_CONFIG_FILE") or os.environ.get("OFFLOAD_ENV_FILE")
    if explicit_file and os.path.isfile(explicit_file):
        return os.path.abspath(explicit_file)

    offload_home = os.environ.get("OFFLOAD_HOME")
    if offload_home:
        home_config = os.path.join(offload_home, "conf", CONFIG_FILE_NAME)
        if os.path.isfile(home_config):
            return os.path.abspath(home_config)

    conf_dotenv = find_dotenv(filename=f"conf/{CONFIG_FILE_NAME}", usecwd=True)
    if conf_dotenv and os.path.isfile(conf_dotenv):
        return os.path.abspath(conf_dotenv)

    root_dotenv = find_dotenv(filename=CONFIG_FILE_NAME, usecwd=True)
    if root_dotenv and os.path.isfile(root_dotenv):
        return os.path.abspath(root_dotenv)

    for system_path in STANDARD_CONFIG_PATHS:
        if os.path.isfile(system_path):
            return os.path.abspath(system_path)

    return None


def get_environment_file_path() -> str | None:
    """Return the resolved environment file path or None if not found.

    Delegates to find_environment_file() for backward compatibility.
    """
    return find_environment_file()


def load_env(path: str | None = None):
    """Load GOE environment from a configuration file.

    By default this is a fixed location: $OFFLOAD_HOME/conf/offload.env.
    In time this will become a parameter and support cloud storage locations.
    """
    if not path:
        path = get_environment_file_path()

    if path and os.path.exists(path):
        load_dotenv(path)


def env_key_value_pair(line_from_file: str) -> tuple | None:
    """Used by connect to get the key names from a configuration file"""
    m = KEY_VALUE_PATTERN.match(line_from_file)
    return m.groups() if m else None

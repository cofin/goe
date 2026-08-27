# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import os
import re
import sys

from dotenv import load_dotenv

CONFIG_FILE_NAME = "offload.env"
KEY_VALUE_PATTERN = re.compile(r"#?[ ]*([A-Z_0-9]+)=(.*)")


def check_config_path():
    """Check OFFLOAD_HOME in top level command wrappers"""
    if not os.environ.get("OFFLOAD_HOME"):
        print("OFFLOAD_HOME environment variable missing")
        sys.exit(1)


def get_environment_file_path() -> str | None:
    offload_home = os.environ.get("OFFLOAD_HOME")
    if not offload_home:
        return None
    return os.path.join(offload_home, "conf", CONFIG_FILE_NAME)


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

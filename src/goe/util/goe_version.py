# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import importlib.metadata
import os

try:
    from packaging.version import Version as GOEVersion
except ModuleNotFoundError:
    pass


def goe_version() -> str:
    """Returns the installed GOE framework version string."""
    offload_home = os.environ.get("OFFLOAD_HOME")
    if offload_home:
        version_file = os.path.join(offload_home, "version_build")
        if os.path.exists(version_file):
            with open(version_file) as f:
                return f.read().strip()
    try:
        return importlib.metadata.version("goe-framework")
    except Exception:
        return "1.1.1.dev0"


__all__ = ("GOEVersion", "goe_version")

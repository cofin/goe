# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for SPDX header migration tooling (tools/migrate_spdx_headers.py)."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.migrate_spdx_headers import (
    CommentStyle,
    cli,
    detect_comment_style,
    extract_copyright_year,
    migrate_content,
    migrate_file,
)

LEGACY_PYTHON_HEADER = """# Copyright 2016 The GOE Authors. All rights reserved.
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

\"\"\"Module docstring.\"\"\"
"""

EXPECTED_SPDX_PYTHON = """# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

\"\"\"Module docstring.\"\"\"
"""

LEGACY_SHEBANG_PYTHON = """#! /usr/bin/env python3

# Copyright 2024 The GOE Authors. All rights reserved.
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

import sys
"""

EXPECTED_SPDX_SHEBANG_PYTHON = """#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import sys
"""

LEGACY_SQL_BLOCK_HEADER = """/*
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
*/

SET SERVEROUTPUT ON
"""

EXPECTED_SPDX_SQL = """-- SPDX-FileCopyrightText: 2016 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

SET SERVEROUTPUT ON
"""

LEGACY_SCALA_HEADER = """/*
# Copyright 2016-2024 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
*/

import org.apache.spark.scheduler.SparkListener
"""

EXPECTED_SPDX_SCALA = """/*
 * SPDX-FileCopyrightText: 2016-2024 The GOE Authors
 * SPDX-License-Identifier: Apache-2.0
 */

import org.apache.spark.scheduler.SparkListener
"""

LEGACY_HTML_HEADER = """<!--
# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
-->
<html><body></body></html>
"""

EXPECTED_SPDX_HTML = """<!--
SPDX-FileCopyrightText: 2016 The GOE Authors
SPDX-License-Identifier: Apache-2.0
-->
<html><body></body></html>
"""

LEGACY_JINJA_HEADER = """{#
# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#}

{% extends "goe_base.html" %}
"""

EXPECTED_SPDX_JINJA = """{#
# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0
#}

{% extends "goe_base.html" %}
"""


def test_detect_comment_style() -> None:
    """Verify file path extension to comment style detection."""
    assert detect_comment_style(Path("src/goe/cli/main.py")) == CommentStyle.HASH
    assert detect_comment_style(Path("bin/offload")) == CommentStyle.HASH
    assert detect_comment_style(Path("Makefile")) == CommentStyle.HASH
    assert detect_comment_style(Path("sql/oracle/source/install.sql")) == CommentStyle.DASH_DASH
    assert detect_comment_style(Path("tools/spark-listener/src/GOETaskListener.scala")) == CommentStyle.C_BLOCK
    assert detect_comment_style(Path("templates/styles.css")) == CommentStyle.C_BLOCK
    assert detect_comment_style(Path("templates/index.html")) == CommentStyle.HTML_BLOCK
    assert detect_comment_style(Path("templates/macros.jinja")) == CommentStyle.JINJA_BLOCK
    assert detect_comment_style(Path("spark-defaults.conf")) == CommentStyle.HASH


def test_extract_copyright_year() -> None:
    """Verify year and year range extraction from legacy headers."""
    assert extract_copyright_year("Copyright 2016 The GOE Authors.") == "2016"
    assert extract_copyright_year("Copyright 2016-2024 The GOE Authors.") == "2016-2024"
    assert extract_copyright_year("Copyright 2024 The GOE Authors") == "2024"
    assert extract_copyright_year("No copyright notice here") == "2016"


def test_migrate_python_header() -> None:
    """Verify Python file header migration without shebang."""
    new_content, changed = migrate_content(LEGACY_PYTHON_HEADER, Path("test.py"))
    assert changed is True
    assert new_content == EXPECTED_SPDX_PYTHON


def test_migrate_python_shebang_header() -> None:
    """Verify Python file header migration preserving shebang line."""
    new_content, changed = migrate_content(LEGACY_SHEBANG_PYTHON, Path("test.py"))
    assert changed is True
    assert new_content == EXPECTED_SPDX_SHEBANG_PYTHON


def test_migrate_sql_header() -> None:
    """Verify SQL file header migration from block comment to dash-dash SPDX."""
    new_content, changed = migrate_content(LEGACY_SQL_BLOCK_HEADER, Path("test.sql"))
    assert changed is True
    assert new_content == EXPECTED_SPDX_SQL


def test_migrate_scala_header() -> None:
    """Verify Scala / C-style file header migration."""
    new_content, changed = migrate_content(LEGACY_SCALA_HEADER, Path("test.scala"))
    assert changed is True
    assert new_content == EXPECTED_SPDX_SCALA


def test_migrate_html_header() -> None:
    """Verify HTML / XML comment header migration."""
    new_content, changed = migrate_content(LEGACY_HTML_HEADER, Path("test.html"))
    assert changed is True
    assert new_content == EXPECTED_SPDX_HTML


def test_migrate_jinja_header() -> None:
    """Verify Jinja comment header migration."""
    new_content, changed = migrate_content(LEGACY_JINJA_HEADER, Path("test.jinja"))
    assert changed is True
    assert new_content == EXPECTED_SPDX_JINJA


def test_idempotency() -> None:
    """Verify already migrated content is left untouched."""
    new_content, changed = migrate_content(EXPECTED_SPDX_PYTHON, Path("test.py"))
    assert changed is False
    assert new_content == EXPECTED_SPDX_PYTHON


def test_unrecognized_file() -> None:
    """Verify file without Apache header is not modified."""
    plain_content = "def hello():\n    return 'world'\n"
    new_content, changed = migrate_content(plain_content, Path("test.py"))
    assert changed is False
    assert new_content == plain_content


def test_cli_dry_run(tmp_path: Path) -> None:
    """Verify CLI dry run mode reports changes without writing to disk."""
    runner = CliRunner()
    test_file = tmp_path / "sample.py"
    test_file.write_text(LEGACY_PYTHON_HEADER, encoding="utf-8")

    result = runner.invoke(cli, ["--path", str(test_file), "--dry-run"])
    assert result.exit_code == 0
    assert "Would update:" in result.output
    assert test_file.read_text(encoding="utf-8") == LEGACY_PYTHON_HEADER


def test_cli_write(tmp_path: Path) -> None:
    """Verify CLI writes updated header to disk."""
    runner = CliRunner()
    test_file = tmp_path / "sample.py"
    test_file.write_text(LEGACY_PYTHON_HEADER, encoding="utf-8")

    result = runner.invoke(cli, ["--path", str(test_file)])
    assert result.exit_code == 0
    assert "Updated:" in result.output
    assert test_file.read_text(encoding="utf-8") == EXPECTED_SPDX_PYTHON

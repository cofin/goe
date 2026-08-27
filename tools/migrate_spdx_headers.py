#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Automated migration tooling for standardizing source file headers to SPDX format."""

import enum
import re
import sys
from pathlib import Path

import click


class CommentStyle(enum.Enum):
    """Supported comment syntax styles for source headers."""

    HASH = "hash"
    DASH_DASH = "dash_dash"
    C_BLOCK = "c_block"
    HTML_BLOCK = "html_block"
    JINJA_BLOCK = "jinja_block"


APACHE_LICENSE_MARKERS = (
    "Licensed under the Apache License, Version 2.0",
    "http://www.apache.org/licenses/LICENSE-2.0",
    "http://www.apache.org/licenses/LICENSE-2.0",
)


def detect_comment_style(path: Path) -> CommentStyle:
    """Determine the comment syntax style for a given file path based on suffix and name."""
    name = path.name
    suffix = path.suffix.lower()

    if suffix in (".sql",):
        return CommentStyle.DASH_DASH
    if suffix in (".scala", ".sbt", ".css", ".js", ".c", ".cpp", ".h"):
        return CommentStyle.C_BLOCK
    if suffix in (".html", ".xml"):
        return CommentStyle.HTML_BLOCK
    if suffix in (".jinja",):
        return CommentStyle.JINJA_BLOCK
    return CommentStyle.HASH


def extract_copyright_year(content: str) -> str:
    """Extract copyright year or year range from the legacy license header."""
    match = re.search(
        r"Copyright\s+(?P<year>\d{4}(?:\s*-\s*\d{4})?)\s+The\s+GOE\s+Authors",
        content,
        re.IGNORECASE,
    )
    if match:
        year_str = match.group("year")
        return re.sub(r"\s+", "", year_str)

    fallback_match = re.search(r"Copyright\s+(?P<year>\d{4}(?:\s*-\s*\d{4})?)", content, re.IGNORECASE)
    if fallback_match:
        year_str = fallback_match.group("year")
        return re.sub(r"\s+", "", year_str)

    return "2016"


def format_spdx_header(year: str, style: CommentStyle) -> str:
    """Format the 2-line SPDX header according to the specified comment style."""
    if style == CommentStyle.HASH:
        return f"# SPDX-FileCopyrightText: {year} The GOE Authors\n# SPDX-License-Identifier: Apache-2.0"
    if style == CommentStyle.DASH_DASH:
        return f"-- SPDX-FileCopyrightText: {year} The GOE Authors\n-- SPDX-License-Identifier: Apache-2.0"
    if style == CommentStyle.C_BLOCK:
        return f"/*\n * SPDX-FileCopyrightText: {year} The GOE Authors\n * SPDX-License-Identifier: Apache-2.0\n */"
    if style == CommentStyle.HTML_BLOCK:
        return f"<!--\nSPDX-FileCopyrightText: {year} The GOE Authors\nSPDX-License-Identifier: Apache-2.0\n-->"
    if style == CommentStyle.JINJA_BLOCK:
        return f"{{#\n# SPDX-FileCopyrightText: {year} The GOE Authors\n# SPDX-License-Identifier: Apache-2.0\n#}}"
    return f"# SPDX-FileCopyrightText: {year} The GOE Authors\n# SPDX-License-Identifier: Apache-2.0"


def is_legacy_apache_header(content: str) -> bool:
    """Check whether the content contains legacy Apache 2.0 header text."""
    if "SPDX-License-Identifier: Apache-2.0" in content:
        return False
    for marker in APACHE_LICENSE_MARKERS:
        if marker in content:
            return True
    return bool(re.search(r"Copyright\s+\d{4}.*?The GOE Authors", content, re.IGNORECASE))


def migrate_content(content: str, path: Path) -> tuple[str, bool]:
    """Transform legacy Apache 2.0 license notice into concise SPDX header."""
    if "SPDX-License-Identifier: Apache-2.0" in content:
        return content, False

    if not is_legacy_apache_header(content):
        return content, False

    year = extract_copyright_year(content)
    style = detect_comment_style(path)
    spdx_header = format_spdx_header(year, style)

    shebang_match = re.match(r"^(#!.*?\n(?:[ \t]*\n)?)", content)
    prefix = ""
    rest = content
    if shebang_match:
        prefix = shebang_match.group(1)
        if not prefix.endswith("\n\n"):
            prefix = prefix.rstrip("\n") + "\n\n"
        rest = content[shebang_match.end() :]
    else:
        xml_match = re.match(r"^(<\?xml.*?\?>\n)", content)
        if xml_match:
            prefix = xml_match.group(1)
            rest = content[xml_match.end() :]

    replaced = False

    if style == CommentStyle.JINJA_BLOCK:
        jinja_pattern = re.compile(r"\{#[\s\S]*?#\}(?:\r?\n)*", re.DOTALL)
        if jinja_pattern.search(rest):
            rest = jinja_pattern.sub(spdx_header + "\n\n", rest, count=1)
            replaced = True

    elif style == CommentStyle.HTML_BLOCK:
        html_pattern = re.compile(r"<!--[\s\S]*?-->", re.DOTALL)
        if html_pattern.search(rest):
            rest = html_pattern.sub(spdx_header, rest, count=1)
            replaced = True

    elif style in (CommentStyle.C_BLOCK, CommentStyle.DASH_DASH):
        c_pattern = re.compile(r"/\*[\s\S]*?\*/(?:\r?\n)*", re.DOTALL)
        if c_pattern.search(rest):
            rest = c_pattern.sub(spdx_header + "\n\n", rest, count=1)
            replaced = True
        elif style == CommentStyle.DASH_DASH:
            dash_pattern = re.compile(r"(?:--[^\n]*\n)+(?:\r?\n)*")
            if dash_pattern.search(rest):
                rest = dash_pattern.sub(spdx_header + "\n\n", rest, count=1)
                replaced = True

    if not replaced:
        hash_pattern = re.compile(r"(?:#[^\n]*\n)+(?:\r?\n)*")
        if hash_pattern.search(rest):
            rest = hash_pattern.sub(spdx_header + "\n\n", rest, count=1)
            replaced = True

    if not replaced:
        return content, False

    result = prefix + rest
    return result, True


def migrate_file(file_path: Path, dry_run: bool = False, check_only: bool = False) -> bool:
    """Migrate a single file on disk and return True if changes were made or needed."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return False

    new_content, changed = migrate_content(content, file_path)
    if not changed:
        return False

    if dry_run or check_only:
        return True

    file_path.write_text(new_content, encoding="utf-8")
    return True


@click.command()
@click.option(
    "--path",
    "-p",
    "target_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("."),
    help="Target directory or file path to migrate.",
)
@click.option(
    "--ext",
    "-e",
    "extensions",
    multiple=True,
    help="File extensions to include (e.g. .py, .sql, .sh).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show files that would be modified without making changes.",
)
@click.option(
    "--check",
    is_flag=True,
    help="Check for unmigrated files and return non-zero exit code if found.",
)
def cli(target_path: Path, extensions: tuple[str, ...], dry_run: bool, check: bool) -> None:
    """Automated CLI tool to migrate source file headers to SPDX format."""
    valid_exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
    files_to_process: list[Path] = []

    if target_path.is_file():
        files_to_process.append(target_path)
    else:
        excluded_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".ruff_cache",
            ".mypy_cache",
            "dist",
            "build",
            ".nox",
            "node_modules",
            ".agents",
        }
        for item in target_path.rglob("*"):
            if item.is_file():
                if any(part in excluded_dirs for part in item.parts):
                    continue
                if valid_exts and item.suffix.lower() not in valid_exts:
                    continue
                files_to_process.append(item)

    changed_count = 0
    for file_path in files_to_process:
        if migrate_file(file_path, dry_run=dry_run, check_only=check):
            changed_count += 1
            if dry_run:
                click.echo(f"Would update: {file_path}")
            elif check:
                click.echo(f"Unmigrated: {file_path}")
            else:
                click.echo(f"Updated: {file_path}")

    if check and changed_count > 0:
        click.echo(f"Found {changed_count} unmigrated file(s).")
        sys.exit(1)

    click.echo(f"Done. Processed {len(files_to_process)} file(s), modified {changed_count} file(s).")


if __name__ == "__main__":
    cli()

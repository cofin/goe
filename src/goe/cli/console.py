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

"""Shared Rich console and terminal message formatting helpers for GOE."""

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from goe.cli.config import (
    ERROR_COLOR,
    INFO_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
)

console = Console()
heading_console = Console(stderr=True)


def print_heading(context: str | None = None) -> None:
    """Print the minimal GOE product heading shown at the start of command invocations."""
    heading = Text()
    heading.append("Gluent ", style="bold blue")
    heading.append("Offload Engine", style="bold white")
    heading.append(" (GOE)", style="dim blue")
    if context:
        heading.append(f"  ·  {context}", style="dim")
    heading_console.print(heading)


def left_aligned_rule(title: str, style: str = "blue") -> None:
    """Create a left-aligned rule with title."""
    console.print(Rule(title, style=style, align="left"))


def print_success(message: str) -> None:
    """Print a success message with green color and checkmark."""
    console.print(f"[{SUCCESS_COLOR}]✔[/{SUCCESS_COLOR}] {message}")


def print_info(message: str) -> None:
    """Print an info message with blue color and info symbol."""
    console.print(f"[{INFO_COLOR}]ℹ[/{INFO_COLOR}] {message}")


def print_warning(message: str) -> None:
    """Print a warning message with yellow color and warning symbol."""
    console.print(f"[{WARNING_COLOR}]⚠[/{WARNING_COLOR}] {message}")


def print_error(message: str) -> None:
    """Print an error message with red color and error symbol."""
    console.print(f"[{ERROR_COLOR}]✗[/{ERROR_COLOR}] {message}")


__all__ = (
    "console",
    "heading_console",
    "left_aligned_rule",
    "print_error",
    "print_heading",
    "print_info",
    "print_success",
    "print_warning",
)

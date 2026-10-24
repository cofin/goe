# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""CLI command definition for goe connect."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import rich_click as click

from goe.cli._lazy import LazyImportMap, resolve_lazy_attribute
from goe.cli.options import common_options
from goe.config.settings import GOESettings
from goe.connect.runner import ConnectRunner
from goe.exceptions import GOEError

if TYPE_CHECKING:
    pass

__all__ = (
    "connect",
    "connect_cmd",
)

_LAZY_IMPORTS: LazyImportMap = {
    "check_config_path": ("goe.config.config_file", "check_config_path"),
}


@click.command(
    name="connect",
    help="Verify connectivity across frontend, backend, storage, and transport targets.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@common_options
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit connectivity report as JSON.")
def connect_cmd(*, verbose: bool = False, as_json: bool = False, **_: object) -> None:
    """Execute connectivity probes and print text or JSON report."""
    try:
        settings = GOESettings.from_env()
        runner = ConnectRunner(settings)
        report = runner.run()
    except GOEError as exc:
        click.echo(str(exc), err=True)
        sys.exit(exc.exit_code)

    if as_json:
        click.echo(report.to_json())
    else:
        click.echo(report.format_text(include_details=verbose))
    sys.exit(report.exit_code)


connect = connect_cmd


def __getattr__(name: str) -> Any:
    """Lazily resolve check_config_path attribute on first access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)

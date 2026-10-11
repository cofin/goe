# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe report' subcommand for generating offload status reports."""

from typing import TYPE_CHECKING, Any

import rich_click as click

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.cli.common import common_options, extract_common_options

if TYPE_CHECKING:
    from goe.config.options import StatusReportOptions
    from goe.offload.offload_status_report import offload_status_report_run

_LAZY_IMPORTS: LazyImportMap = {
    "StatusReportOptions": ("goe.config.options", "StatusReportOptions"),
    "offload_status_report_run": ("goe.offload.offload_status_report", "offload_status_report_run"),
}


@click.command(
    name="report",
    help="Generate comprehensive offload status, storage, and partition reports.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("-s", "--schema", help="Source schema name.")
@click.option("-t", "--table", help="Source table name.")
@click.option(
    "-o",
    "--output-format",
    type=click.Choice(["HTML", "TEXT", "JSON", "RAW", "CSV"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Report output format.",
)
@click.option(
    "--output-level",
    type=click.Choice(["detail", "summary"], case_sensitive=False),
    default="summary",
    show_default=True,
    help="Level of report detail.",
)
@click.option("--report-name", help="Custom report output filename.")
@click.option("--report-directory", help="Target directory for report artifacts.")
@click.option("--csv-delimiter", default=",", show_default=True, help="Delimiter for CSV output.")
@click.option("--csv-enclosure", default='"', show_default=True, help="Enclosure character for CSV output.")
@click.option(
    "-d",
    "--demo",
    "demo_mode",
    is_flag=True,
    default=None,
    hidden=True,
    help="Generate report using synthetic demo dataset.",
)
@common_options
@click.pass_context
def report(ctx: click.Context, **kwargs: Any) -> None:
    """Generate offload status report."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    common_opts = extract_common_options(ctx, kwargs)
    overrides: dict[str, Any] = dict(common_opts)
    for key, value in kwargs.items():
        if value is None:
            continue
        if key == "output_format" and ctx.get_parameter_source(key) == click.core.ParameterSource.DEFAULT:
            overrides[key] = value.lower()
        else:
            overrides[key] = value
    offload_status_report_run(StatusReportOptions.from_mapping(overrides))


def __getattr__(name: str) -> Any:
    """Lazily import offload_status_report dependencies on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)

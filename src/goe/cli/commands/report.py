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

"""'goe report' subcommand for generating offload status reports."""

from optparse import Values

import rich_click as click

from goe.offload.offload_status_report import (
    get_offload_status_report_opts,
    offload_status_report_run,
)


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
    default="HTML",
    show_default=True,
    help="Report output format.",
)
@click.option(
    "--output-level",
    type=click.Choice(["detail", "summary"], case_sensitive=False),
    default="detail",
    show_default=True,
    help="Level of report detail.",
)
@click.option("--report-name", help="Custom report output filename.")
@click.option("--report-directory", help="Target directory for report artifacts.")
@click.option("--csv-delimiter", default=",", show_default=True, help="Delimiter for CSV output.")
@click.option("--csv-enclosure", default='"', show_default=True, help="Enclosure character for CSV output.")
@click.pass_context
def report(ctx: click.Context, **kwargs) -> None:
    """Generate offload status report."""
    parser = get_offload_status_report_opts()
    defaults = parser.get_default_values()
    options_dict = defaults.__dict__.copy()

    if ctx.obj:
        options_dict.update(
            {
                "verbose": ctx.obj.get("verbose", False),
                "vverbose": ctx.obj.get("vverbose", False),
                "quiet": ctx.obj.get("quiet", False),
            }
        )

    for k, v in kwargs.items():
        if v is not None:
            options_dict[k] = v

    options = Values(options_dict)
    offload_status_report_run(options)

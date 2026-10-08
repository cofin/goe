# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""CLI configuration and rich-click styling rules for GOE."""

import rich_click as click
from rich_click.utils import CommandGroupDict, OptionGroupDict

ERROR_COLOR = "#EA4335"
WARNING_COLOR = "#FBBC04"
SUCCESS_COLOR = "#34A853"
INFO_COLOR = "#4285F4"

COMMAND_GROUPS: dict[str, list[CommandGroupDict]] = {
    "goe": [
        {
            "name": "Core Orchestration Commands",
            "commands": ["offload", "connect", "validate", "sync", "report"],
        },
        {
            "name": "Service & Maintenance Commands",
            "commands": ["listener", "logmgr"],
        },
    ]
}

OPTION_GROUPS: dict[str, list[OptionGroupDict]] = {
    "goe offload": [
        {
            "name": "Target & Source Selection",
            "options": ["--table", "--target", "--target-name"],
        },
        {
            "name": "Execution & Control",
            "options": [
                "--execute",
                "--force",
                "--skip-steps",
                "--ddl-file",
                "--create-backend-db",
                "--reset-backend-table",
                "--reuse-backend-table",
                "--reset-hybrid-view",
                "--purge",
                "--preserve-load-table",
                "--compute-load-table-stats",
                "--compress-load-table",
            ],
        },
        {
            "name": "Partitioning & Incremental Controls",
            "options": [
                "--offload-type",
                "--older-than-date",
                "--older-than-days",
                "--less-than-value",
                "--equal-to-values",
                "--partition-names",
                "--partition-columns",
                "--partition-granularity",
                "--partition-digits",
                "--partition-functions",
                "--partition-lower-value",
                "--partition-upper-value",
                "--offload-by-subpartition",
                "--max-offload-chunk-size",
                "--max-offload-chunk-count",
                "--offload-chunk-column",
                "--offload-predicate",
                "--offload-predicate-type",
                "--no-modify-hybrid-view",
            ],
        },
        {
            "name": "Data Types & Schema Controls",
            "options": [
                "--storage-format",
                "--storage-compression",
                "--not-null-columns",
                "--integer-1-columns",
                "--integer-2-columns",
                "--integer-4-columns",
                "--integer-8-columns",
                "--integer-38-columns",
                "--decimal-columns",
                "--decimal-columns-type",
                "--date-columns",
                "--unicode-string-columns",
                "--double-columns",
                "--variable-string-columns",
                "--timestamp-tz-columns",
                "--decimal-padding-digits",
                "--allow-decimal-scale-rounding",
                "--allow-floating-point-conversions",
                "--allow-nanosecond-timestamp-columns",
                "--data-sample-percent",
                "--data-sample-parallelism",
            ],
        },
        {
            "name": "Transport & Performance",
            "options": [
                "--offload-transport-method",
                "--offload-transport-parallelism",
                "--offload-transport-dsn",
                "--offload-transport-fetch-size",
                "--offload-transport-consistent-read",
                "--offload-transport-snapshot",
                "--offload-transport-spark-properties",
                "--offload-transport-queue-name",
                "--offload-transport-jvm-overrides",
                "--offload-transport-small-table-threshold",
                "--offload-fs-scheme",
                "--offload-fs-prefix",
                "--offload-fs-container",
                "--bucket-hash-column",
                "--sort-columns",
                "--offload-distribute-enabled",
                "--hive-column-stats",
                "--offload-stats",
                "--offload-chunk-impala-insert-hint",
                "--sqoop-additional-options",
                "--sqoop-mapreduce-map-memory-mb",
                "--sqoop-mapreduce-map-java-opts",
                "--verify",
                "--no-verify",
                "--verify-parallelism",
            ],
        },
    ]
}


def configure_cli() -> None:
    """Configure rich-click with a borderless modern theme and structured command/option groups."""
    help_config = click.RichHelpConfiguration(
        theme="slim",
        text_markup="rich",
        style_command="bold #4285F4",
        style_option="bold #34A853",
        style_switch="bold #34A853",
        style_argument="bold cyan",
        style_metavar="#FBBC04",
        style_usage="bold #FBBC04",
        style_usage_command="bold #4285F4",
        style_helptext="",
        style_helptext_first_line="bold",
        style_option_help="",
        style_errors_suggestion="italic #FBBC04",
        style_required_short="#EA4335",
        style_required_long="dim #EA4335",
        style_errors_panel_border="#EA4335",
        style_aborted="#EA4335",
        style_options_panel_box="BLANK",
        style_commands_panel_box="BLANK",
        style_options_table_box=None,
        style_commands_table_box=None,
        style_options_panel_border="none",
        style_commands_panel_border="none",
        style_options_panel_title_style="bold #4285F4",
        style_commands_panel_title_style="bold #4285F4",
        panel_title_string="{}",
        panel_title_padding=0,
        style_options_panel_padding=(0, 0, 0, 2),
        style_commands_panel_padding=(0, 0, 0, 2),
        width=120,
        max_width=120,
        show_arguments=True,
        group_arguments_options=True,
        command_groups=COMMAND_GROUPS,
        option_groups=OPTION_GROUPS,
    )
    help_config.dump_to_globals()


configure_cli()

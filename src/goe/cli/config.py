# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""CLI configuration and rich-click styling rules for GOE."""

import rich_click as click

ERROR_COLOR = "#EA4335"
WARNING_COLOR = "#FBBC04"
SUCCESS_COLOR = "#34A853"
INFO_COLOR = "#4285F4"

click.rich_click.rich_config = click.RichHelpConfiguration(
    text_markup="rich",
    style_command="bold #4285F4",
    style_option="bold #34A853",
    style_switch="bold #34A853",
    style_argument="bold cyan",
    style_metavar="#FBBC04",
    style_usage="bold",
    style_usage_command="bold #4285F4",
    style_helptext="dim",
    style_helptext_first_line="",
    style_option_help="",
    style_errors_suggestion="italic #FBBC04",
    style_required_short="#EA4335",
    style_required_long="dim #EA4335",
    style_errors_panel_border="#EA4335",
    style_aborted="#EA4335",
    style_options_panel_border="none",
    style_commands_panel_border="none",
    width=120,
    max_width=120,
    show_arguments=True,
    group_arguments_options=True,
)

click.rich_click.COMMAND_GROUPS = {
    "goe": [
        {
            "name": "🚀 Core Orchestration Commands",
            "commands": ["offload", "connect", "validate", "sync", "report"],
        },
        {
            "name": "⚙️ Service & Maintenance Commands",
            "commands": ["listener", "logmgr"],
        },
    ]
}

click.rich_click.OPTION_GROUPS = {
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
                "--sort-columns",
                "--offload-distribute-enabled",
                "--verify",
                "--no-verify",
                "--verify-parallelism",
            ],
        },
    ]
}

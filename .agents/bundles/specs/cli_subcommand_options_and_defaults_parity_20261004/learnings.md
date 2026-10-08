---
type: Reference
title: "Learnings: CLI Subcommand Option Completeness & Default Parity (cli_subcommand_options_and_defaults_parity_20261004)"
description: Durable learnings and patterns from restoring goe offload, connect, report, and logmgr option and default parity
tags:
  - learnings
  - cli
  - offload
  - report
  - logmgr
---

# Learnings: `cli_subcommand_options_and_defaults_parity_20261004`

## 1. `click.Choice(..., case_sensitive=False)` Default Value Normalization
- **Problem**: In Click 8.x, `click.Choice(["HTML", "TEXT", "JSON", "RAW", "CSV"], case_sensitive=False)` runs `Choice.convert()` on the default value (`default="text"`), converting it to uppercase `"TEXT"` when the choice list is uppercase.
- **Resolution**: In [`src/goe/cli/commands/report.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/report.py), check `ctx.get_parameter_source("output_format") == click.core.ParameterSource.DEFAULT` so default invocations preserve lowercase `"text"` matching `DEFAULT_OUTPUT_FORMAT = "text"` in `offload_status_report.py:71`, while explicit `-o JSON` CLI invocations preserve the matched choice value.

## 2. Legacy `optparse` String Validation Contracts (`--older-than-days`)
- **Problem**: `check_opt_is_posint("--older-than-days", options.older_than_days)` in `src/goe/offload/offload.py:345` expects a string value (from `optparse`) and raises `TypeError` when Click converts `--older-than-days` via `type=int`.
- **Resolution**: Keep `--older-than-days` as a string option in [`src/goe/cli/commands/offload.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/offload.py) when delegating to legacy `optparse`-validated routines.

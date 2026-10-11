# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Constants shared by GOE orchestration operations and their log verbosity levels."""

OFFLOAD_OP_NAME = "offload"

NLS_LANG_MISSING_CHARACTER_SET_EXCEPTION_TEMPLATE = "NLS_LANG value %s missing character set delimiter (.)"
OFFLOAD_STATS_COPY_EXCEPTION_TEXT = "Invalid --offload-stats value"
RETAINING_PARTITITON_FUNCTIONS_MESSAGE_TEXT = "Retaining partition functions from backend target"

normal, verbose, vverbose = list(range(3))

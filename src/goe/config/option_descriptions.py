#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""option_descriptions: Library of constants defining descriptions for options.
In the future we expect to refactor all option processing, including descriptions, and this module will
may become redundant at that time.
"""

DATA_SAMPLE_PARALLELISM = (
    "Degree of parallelism to use when sampling RDBMS data for columns with no precision/scale properties. "
    "Values of 0 or 1 will execute the query without parallelism"
)

RESET_BACKEND_TABLE = (
    "Remove backend data table. Use with caution - this will delete previously offloaded data for this table!"
)

REUSE_BACKEND_TABLE = (
    "Allow Offload to re-use an empty backend table when there is already Offload metadata. "
    "This may be useful if a backend table had data removed by an administrator and a re-offload is required"
)

VERIFY_PARALLELISM = (
    "Degree of parallelism to use for the RDBMS query executed when validating an offload. "
    "Values of 0 or 1 will execute the query without parallelism. Values > 1 will force a parallel query of the given degree. "
    "If unset, the RDBMS query will fall back to using the behavior specified by RDBMS defaults"
)

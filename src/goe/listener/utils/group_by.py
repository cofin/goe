# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Utility library."""

from collections import defaultdict


def groupby(key, seq):
    grouped = defaultdict(list)
    for val in seq:
        grouped[key(val)].append(val)
    return grouped

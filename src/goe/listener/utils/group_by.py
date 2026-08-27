# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Utility library."""

from collections import defaultdict
from functools import reduce  # import needed for python3; builtin in python2


def groupby(key, seq):
    return reduce(lambda grp, val: grp[key(val)].append(val) or grp, seq, defaultdict(list))

# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0


class OffloadException(Exception):
    pass


class OffloadOptionError(Exception):
    def __init__(self, detail):
        self.detail = detail

    def __str__(self):
        return repr(self.detail)

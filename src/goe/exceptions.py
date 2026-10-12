# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Core exception hierarchy for GOE."""

__all__ = (
    "OffloadException",
    "OffloadOptionError",
    "OptionValueError",
)


class OffloadException(Exception):
    """Base exception for GOE offload operations."""


class OffloadOptionError(Exception):
    """Raised when an option value or option combination is invalid."""

    def __init__(self, detail: object) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return repr(self.detail)


OptionValueError = OffloadOptionError

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Canonical exception hierarchy for GOE."""

from __future__ import annotations

from typing import ClassVar

__all__ = (
    "AuthenticationError",
    "BackendError",
    "ConfigurationError",
    "FrontendError",
    "GOEError",
    "OffloadException",
    "OffloadOptionError",
    "OptionValueError",
    "OrchestrationError",
    "PersistenceError",
    "TransportError",
    "ValidationError",
)


class GOEError(Exception):
    """Root exception for all GOE domain and operational errors."""

    default_code: ClassVar[str] = "GOE_ERROR"
    default_exit_code: ClassVar[int] = 1

    def __init__(
        self,
        detail: object = "",
        *,
        code: str | None = None,
        details: dict[str, object] | None = None,
        exit_code: int | None = None,
    ) -> None:
        message = detail if isinstance(detail, str) else repr(detail)
        super().__init__(message)
        self.detail = detail
        self.message = message
        self.code = code or self.default_code
        self.details: dict[str, object] = dict(details) if details is not None else {}
        self.exit_code = exit_code if exit_code is not None else self.default_exit_code

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, object]:
        """Return a structured dictionary representation for CLI and HTTP error payloads."""
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "exit_code": self.exit_code,
        }


class ConfigurationError(GOEError):
    """Raised when environment settings or configuration files are invalid or missing."""

    default_code: ClassVar[str] = "CONFIGURATION_ERROR"
    default_exit_code: ClassVar[int] = 2


class ValidationError(GOEError):
    """Raised when CLI options, table targets, predicates, or schema contracts fail validation."""

    default_code: ClassVar[str] = "VALIDATION_ERROR"
    default_exit_code: ClassVar[int] = 2


class AuthenticationError(GOEError):
    """Raised when database, cloud provider, Kerberos, or Listener authentication fails."""

    default_code: ClassVar[str] = "AUTHENTICATION_ERROR"
    default_exit_code: ClassVar[int] = 1


class FrontendError(GOEError):
    """Raised when a frontend RDBMS adapter operation or query fails."""

    default_code: ClassVar[str] = "FRONTEND_ERROR"
    default_exit_code: ClassVar[int] = 1


class BackendError(GOEError):
    """Raised when a backend cloud data warehouse or Hadoop operation fails."""

    default_code: ClassVar[str] = "BACKEND_ERROR"
    default_exit_code: ClassVar[int] = 1


class TransportError(GOEError):
    """Raised when DuckDB, Spark, Dataproc, Livy, or staging transport execution fails."""

    default_code: ClassVar[str] = "TRANSPORT_ERROR"
    default_exit_code: ClassVar[int] = 1


class PersistenceError(GOEError):
    """Raised when repository metadata reading or writing fails."""

    default_code: ClassVar[str] = "PERSISTENCE_ERROR"
    default_exit_code: ClassVar[int] = 1


class OrchestrationError(GOEError):
    """Raised when offload planning, locking, or step execution fails."""

    default_code: ClassVar[str] = "ORCHESTRATION_ERROR"
    default_exit_code: ClassVar[int] = 1


class OffloadException(GOEError):
    """Base exception for GOE offload operations."""


class OffloadOptionError(ValidationError):
    """Raised when an option value or option combination is invalid."""


OptionValueError = OffloadOptionError

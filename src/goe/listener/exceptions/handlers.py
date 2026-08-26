# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Litestar exception classes and global error handlers for GOE Listener."""

from litestar.exceptions import HTTPException, NotAuthorizedException, NotFoundException
from litestar.response import Response

from goe.listener.schemas import ErrorMessage


class DatabaseConnectivityError(HTTPException):
    """Database connectivity error."""

    status_code = 500
    detail = "Could not connect to the backend database."


class HybridViewMetadataNotFoundError(NotFoundException):
    """Hybrid view metadata not found."""

    def __init__(self, hybrid_view: str) -> None:
        super().__init__(detail=f"No metadata found for {hybrid_view}")


class CredentialValidationError(NotAuthorizedException):
    """Authentication validation failure."""

    detail = "Could not validate credentials"


class LogFileNotFoundError(NotFoundException):
    """Log file not found error."""

    def __init__(self, file_name: str) -> None:
        super().__init__(detail=f"Log File {file_name} not found")


class CommandExecutionNotFound(NotFoundException):
    """Command execution not found."""

    def __init__(self, execution_id: str) -> None:
        super().__init__(detail=f"Command Execution {execution_id} was not found")


def generic_exception_handler(request, exc: Exception) -> Response:
    """Handle generic unhandled exceptions."""
    detail = str(exc)
    status_code = getattr(exc, "status_code", 500)
    return Response(
        content=ErrorMessage(detail=detail, status_code=status_code),
        status_code=status_code,
    )


def http_exception_handler(request, exc: HTTPException) -> Response:
    """Handle HTTPException instances."""
    return Response(
        content=ErrorMessage(detail=exc.detail, status_code=exc.status_code),
        status_code=exc.status_code,
    )

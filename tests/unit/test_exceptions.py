# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for the canonical GOEError exception hierarchy."""

from __future__ import annotations

import pytest

from goe.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    FrontendError,
    GOEError,
    OffloadException,
    OffloadOptionError,
    OptionValueError,
    OrchestrationError,
    PersistenceError,
    TransportError,
    ValidationError,
)


def test_goe_error_hierarchy_inheritance() -> None:
    """All domain exceptions and legacy compatibility exceptions inherit from GOEError."""
    domain_classes = (
        ConfigurationError,
        ValidationError,
        AuthenticationError,
        FrontendError,
        BackendError,
        TransportError,
        PersistenceError,
        OrchestrationError,
        OffloadException,
        OffloadOptionError,
    )
    for exc_cls in domain_classes:
        assert issubclass(exc_cls, GOEError)
        instance = exc_cls("boom")
        assert isinstance(instance, GOEError)
        assert isinstance(instance, Exception)

    assert issubclass(OffloadOptionError, ValidationError)
    assert OptionValueError is OffloadOptionError


def test_exit_codes_for_validation_vs_runtime_errors() -> None:
    """ConfigurationError and ValidationError default to exit_code 2; runtime errors default to 1."""
    assert ConfigurationError("bad env").exit_code == 2
    assert ValidationError("bad option").exit_code == 2
    assert OffloadOptionError("bad option").exit_code == 2

    runtime_classes = (
        GOEError,
        AuthenticationError,
        FrontendError,
        BackendError,
        TransportError,
        PersistenceError,
        OrchestrationError,
        OffloadException,
    )
    for exc_cls in runtime_classes:
        assert exc_cls("failure").exit_code == 1


def test_structured_details_and_to_dict() -> None:
    """GOEError stores code, message, details copy, and serializes via to_dict()."""
    raw_details: dict[str, object] = {"field": "port", "value": 70000}
    err = ConfigurationError(
        "Port out of range",
        code="INVALID_PORT",
        details=raw_details,
        exit_code=2,
    )
    raw_details["mutated"] = True
    assert "mutated" not in err.details
    assert err.code == "INVALID_PORT"
    assert err.message == "Port out of range"
    assert err.detail == "Port out of range"
    assert err.to_dict() == {
        "error": "ConfigurationError",
        "code": "INVALID_PORT",
        "message": "Port out of range",
        "details": {"field": "port", "value": 70000},
        "exit_code": 2,
    }


def test_error_str_and_detail_formatting() -> None:
    """String and non-string detail values format deterministically."""
    err_str = FrontendError("ORA-00942: table or view does not exist")
    assert str(err_str) == "ORA-00942: table or view does not exist"
    assert err_str.code == "FRONTEND_ERROR"

    err_obj = ValidationError(404)
    assert str(err_obj) == "404"
    assert err_obj.detail == 404

    with pytest.raises(ValidationError, match="invalid predicate"):
        raise OptionValueError("invalid predicate")

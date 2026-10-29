# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Backend session parameter management, credential decryption, and log redaction."""

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from goe.config.password_tools import PasswordTools
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.typing import FrozenBaseStruct

__all__ = [
    "BackendSessionManager",
    "LogRedactionRule",
]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class LogRedactionRule(FrozenBaseStruct, frozen=True):
    """Single sensitive-token replacement rule for backend SQL and command logs."""

    item: str
    sub: str = "?"


class BackendSessionManager:
    """Manages session parameter merging, option validation, password decryption, and log redaction."""

    def __init__(
        self,
        connection_options: Any,
        backend_display_name: str,
        messages: Any,
        *,
        fixed_parameters: Mapping[str, Any] | None = None,
        do_not_connect: bool = False,
    ) -> None:
        self._connection_options = connection_options
        self._backend_display_name = backend_display_name
        self._messages = messages
        self._fixed_parameters = dict(fixed_parameters or {})
        user_params = getattr(connection_options, "backend_session_parameters", None)
        self._global_session_parameters = self.merge_session_parameters(
            user_params,
            self._fixed_parameters,
            log_clashes=not do_not_connect,
        )

    @property
    def global_session_parameters(self) -> dict[str, Any]:
        """Return the merged global session parameters dictionary."""
        return dict(self._global_session_parameters)

    def merge_session_parameters(
        self,
        user_parameters: Mapping[str, Any] | None,
        fixed_parameters: Mapping[str, Any] | None = None,
        *,
        log_clashes: bool = True,
    ) -> dict[str, Any]:
        """Merge user session parameters with fixed backend parameters, giving fixed keys precedence."""
        merged: dict[str, Any] = {}
        if user_parameters:
            merged.update(user_parameters)
        fixed = dict(fixed_parameters if fixed_parameters is not None else self._fixed_parameters)
        if fixed:
            fixed_lower = {k.lower() for k in fixed}
            for existing_key in [k for k in list(merged) if k.lower() in fixed_lower]:
                if log_clashes:
                    self.log(
                        f"Removing OFFLOAD_BACKEND_SESSION_PARAMETERS[{existing_key}] because of fixed parameter clash",
                        detail=VVERBOSE,
                    )
                del merged[existing_key]
            merged.update(fixed)
        return merged

    def validate_connection_options(
        self,
        required_options: Sequence[str],
        exc_factory: Callable[[str], Exception],
    ) -> None:
        """Raise via exc_factory when any required attribute is missing on connection_options."""
        missing = [opt for opt in required_options if not hasattr(self._connection_options, opt)]
        if missing:
            raise exc_factory("Missing connection options: %s" % ", ".join(missing))

    def decrypt_password(self, password: str | None) -> str | None:
        """Decrypt an encrypted backend password when password_key_file is configured."""
        key_file = getattr(self._connection_options, "password_key_file", None)
        if key_file and password is not None:
            pass_tool = PasswordTools()
            goe_key = pass_tool.get_password_key_from_key_file(key_file)
            self.log(f"Decrypting {self._backend_display_name} password", detail=VVERBOSE)
            return pass_tool.b64decrypt(password, goe_key)
        return password

    @staticmethod
    def validate_no_log_items(
        no_log_items: Mapping[str, str] | Sequence[Mapping[str, str]] | None,
    ) -> list[dict[str, str]] | None:
        """Validate and normalize no_log_items into a list of replacement dicts."""
        if no_log_items is None:
            return None
        if isinstance(no_log_items, Mapping):
            items = [dict(no_log_items)]
        elif isinstance(no_log_items, Sequence):
            items = [dict(entry) for entry in no_log_items]
        else:
            raise AssertionError(f"Invalid no_log_items type: {type(no_log_items)}")
        assert all(k in ("item", "sub") for k in items[0])
        return items

    @classmethod
    def redact_message(
        cls,
        msg: str,
        no_log_items: Mapping[str, str] | Sequence[Mapping[str, str]] | None = None,
    ) -> str:
        """Return msg with all sensitive items replaced by their substitution token."""
        validated = cls.validate_no_log_items(no_log_items)
        if not validated:
            return msg
        redacted = msg
        for entry in validated:
            redacted = redacted.replace(entry["item"], entry.get("sub", "?"))
        return redacted

    def log(
        self,
        msg: str,
        detail: int | None = None,
        ansi_code: str | None = None,
        no_log_items: Mapping[str, str] | Sequence[Mapping[str, str]] | None = None,
    ) -> None:
        """Write a redacted log line to OffloadMessages and standard Python logger."""
        log_msg = self.redact_message(msg, no_log_items=no_log_items)
        self._messages.log(log_msg, detail=detail, ansi_code=ansi_code)
        if detail == VVERBOSE:
            logger.debug(log_msg)
        else:
            logger.info(log_msg)

    def log_or_not(
        self,
        msg: str,
        log_level: int | None = VERBOSE,
        no_log_items: Mapping[str, str] | Sequence[Mapping[str, str]] | None = None,
    ) -> None:
        """Log msg only when log_level is not None."""
        if log_level is not None:
            self.log(msg, detail=log_level, no_log_items=no_log_items)

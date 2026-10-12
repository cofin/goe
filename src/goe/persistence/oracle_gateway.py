# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""SQLSpec-backed execution of named Oracle SQL statements.

``OracleGateway`` loads statements with ``SQLFileLoader``, normalizes driver features with ``OracleSyncConfig``
(without creating a pool), and executes statements through ``OracleSyncDriver`` wrapped around an existing
``oracledb`` connection returned by a caller-supplied provider. Connection ownership, authentication, session
tagging, and reconnect handling stay with the provider (``OracleFrontendApi``).
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import msgspec
from sqlspec.adapters.oracledb import OracleSyncConfig, OracleSyncDriver
from sqlspec.core import SQL
from sqlspec.core.sqlcommenter import SQLCommenterContext
from sqlspec.loader import SQLFileLoader

if TYPE_CHECKING:
    import oracledb

__all__ = ("OracleGateway", "load_sql_file", "rows_as_dicts", "validate_oracle_identifier")

_IDENTIFIER_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_$#]*")
_SLOT_RE: Final = re.compile(r"\{([a-z_]+)\}")
_DRIVER_FEATURES: Final[dict[str, Any]] = {"enable_lowercase_column_names": True, "fetch_lobs": False}


def validate_oracle_identifier(identifier: str) -> str:
    """Return ``identifier`` upper-cased after enforcing Oracle unquoted-identifier rules.

    Surrounding double quotes are stripped first. Any other character outside ``[A-Za-z0-9_$#]``, or a leading
    non-letter, raises ``ValueError``; this blocks SQL injection through schema-name template slots.
    """
    candidate = identifier.strip()
    if len(candidate) >= 2 and candidate.startswith('"') and candidate.endswith('"'):
        candidate = candidate[1:-1]
    if not _IDENTIFIER_RE.fullmatch(candidate):
        msg = f"Invalid Oracle identifier: {identifier!r}"
        raise ValueError(msg)
    return candidate.upper()


@cache
def load_sql_file(path: Path) -> SQLFileLoader:
    """Return a process-wide cached ``SQLFileLoader`` holding the named statements in ``path``."""
    loader = SQLFileLoader()
    loader.load_sql(path)
    return loader


def rows_as_dicts(column_names: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[dict[str, Any]]:
    """Zip every row with ``column_names`` without changing column-name case."""
    names = list(column_names)
    return [dict(zip(names, row)) for row in rows]


class OracleGateway:
    """Execute named SQL statements through SQLSpec over a provider-supplied Oracle connection."""

    def __init__(
        self,
        connection_provider: "Callable[[], oracledb.Connection | None]",
        loader: SQLFileLoader,
        slots: Mapping[str, str] | None = None,
    ) -> None:
        """Store the connection provider, statement loader, normalized config, and validated identifier slots."""
        self._connection_provider = connection_provider
        self._loader = loader
        self._config = OracleSyncConfig(connection_config=None, driver_features=dict(_DRIVER_FEATURES))
        self._slots = {key: validate_oracle_identifier(value) for key, value in (slots or {}).items()}

    def statement_text(self, name: str, slots: Mapping[str, str] | None = None) -> str:
        """Return statement ``name`` with identifier slots substituted and the trailing semicolon removed.

        Raises ``ValueError`` when a ``{slot}`` placeholder has no value.
        """
        merged = {**self._slots, **{key: validate_oracle_identifier(value) for key, value in (slots or {}).items()}}
        text = self._loader.get_query_text(name).strip().removesuffix(";").rstrip()
        for key, value in merged.items():
            text = text.replace("{" + key + "}", value)
        unresolved = sorted(set(_SLOT_RE.findall(text)))
        if unresolved:
            msg = f"Unresolved SQL slots in {name}: {unresolved}"
            raise ValueError(msg)
        return text

    def select(
        self, name: str, params: Mapping[str, Any] | None = None, *, slots: Mapping[str, str] | None = None
    ) -> list[dict[str, Any]] | None:
        """Return all rows of statement ``name`` as dicts with lower-case keys, or ``None`` without a connection."""
        driver = self._driver()
        if driver is None:
            return None
        statement = SQL(self.statement_text(name, slots))
        binds = self._bind_dict(params)
        with SQLCommenterContext.scope({"action": name}):
            return driver.select(statement, binds) if binds else driver.select(statement)

    def select_structs[S: msgspec.Struct](
        self,
        name: str,
        schema_type: type[S],
        params: Mapping[str, Any] | None = None,
        *,
        slots: Mapping[str, str] | None = None,
    ) -> list[S] | None:
        """Return all rows of statement ``name`` hydrated into ``schema_type``, or ``None`` without a connection."""
        driver = self._driver()
        if driver is None:
            return None
        statement = SQL(self.statement_text(name, slots))
        binds = self._bind_dict(params)
        with SQLCommenterContext.scope({"action": name}):
            if binds:
                return driver.select(statement, binds, schema_type=schema_type)
            return driver.select(statement, schema_type=schema_type)

    def select_tuples(
        self, name: str, params: Mapping[str, Any] | None = None, *, slots: Mapping[str, str] | None = None
    ) -> list[tuple[Any, ...]] | None:
        """Return all rows of statement ``name`` as tuples in projection order, or ``None`` without a connection."""
        rows = self.select(name, params, slots=slots)
        if rows is None:
            return None
        return [tuple(row.values()) for row in rows]

    def new_out_var(self, python_type: type) -> Any:
        """Return an ``oracledb`` OUT bind variable of ``python_type`` allocated on the provider connection."""
        connection = self._connection_provider()
        if connection is None:
            msg = "No Oracle connection is available to allocate an OUT bind variable"
            raise RuntimeError(msg)
        return connection.cursor().var(python_type)

    def _driver(self) -> OracleSyncDriver | None:
        """Wrap the provider connection in a SQLSpec driver, or return ``None`` when there is no connection."""
        connection = self._connection_provider()
        if connection is None:
            return None
        driver = OracleSyncDriver(
            connection=connection,
            statement_config=self._config.statement_config,
            driver_features=dict(self._config.driver_features),
        )
        return driver

    @staticmethod
    def _bind_dict(params: Mapping[str, Any] | None) -> dict[str, Any]:
        """Return named binds as a dict, rejecting positional sequences."""
        if params is None:
            return {}
        if not isinstance(params, Mapping):
            msg = f"OracleGateway requires named binds as a mapping, got {type(params).__name__}"
            raise TypeError(msg)
        return dict(params)

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Named SQL statements loaded with SQLSpec SQLFileLoader and filled with validated identifier slots."""

import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Final

from sqlspec.loader import SQLFileLoader

__all__ = ("NamedStatements", "load_sql_file", "validate_oracle_identifier")

_IDENTIFIER_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_$#]*")


def validate_oracle_identifier(identifier: str) -> str:
    """Return ``identifier`` upper-cased after enforcing Oracle unquoted-identifier rules.

    Surrounding double quotes are stripped first; any other character outside ``[A-Za-z0-9_$#]`` or a leading
    non-letter raises ``ValueError``, which blocks SQL injection through identifier slots.
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


class NamedStatements:
    """Executable texts of the named statements in one SQL file, cached per slot values."""

    def __init__(self, path: Path, slots: Mapping[str, str] | None = None) -> None:
        """Load ``path`` and validate the identifier ``slots`` shared by every statement."""
        self._loader = load_sql_file(path)
        self._slots = {key: validate_oracle_identifier(value) for key, value in (slots or {}).items()}
        self._texts: dict[tuple[str, tuple[tuple[str, str], ...]], str] = {}

    def names(self) -> list[str]:
        """Return the statement names defined in the file."""
        return self._loader.list_queries()

    def text(self, name: str, slots: Mapping[str, str] | None = None) -> str:
        """Return statement ``name`` with slots filled and the trailing semicolon removed.

        Raises:
            ValueError: A slot value is not a valid Oracle identifier.
            SQLSlotError: A slot the statement declares has no value.
        """
        extra = tuple(sorted((key, validate_oracle_identifier(value)) for key, value in (slots or {}).items()))
        key = (name, extra)
        cached = self._texts.get(key)
        if cached is None:
            values = {**self._slots, **dict(extra)}
            declared = {slot.name for slot in self._loader.get_query_slots(name)}
            statement = self._loader.get_sql(name, **{k: v for k, v in values.items() if k in declared})
            cached = statement.raw_sql.strip().removesuffix(";").rstrip()
            self._texts[key] = cached
        return cached

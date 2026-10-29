# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the library-agnostic SQL engine protocol seam."""

import ast
from pathlib import Path
from typing import get_args

import msgspec
import pytest

import goe.offload.sql_engine as sql_engine_mod
from goe.offload.sql_ast.dialect_engine import SqlDialect, get_dialect_engine
from goe.offload.sql_engine import (
    DialectSqlEngineProtocol,
    PredicateDialectEngineProtocol,
    RenderedSQL,
    ValidationQueryEngineProtocol,
    ValidationQuerySpec,
)


def test_sql_engine_module_has_zero_sqlglot_imports() -> None:
    """Verify src/goe/offload/sql_engine.py has no dependency on sqlglot."""
    source = Path(sql_engine_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)
    assert not any("sqlglot" in name for name in imported_names)


def test_rendered_sql_and_validation_query_spec_are_frozen_structs() -> None:
    """Verify RenderedSQL and ValidationQuerySpec enforce immutability and defaults."""
    rendered = RenderedSQL(sql='SELECT * FROM "SH"."SALES" WHERE "ID" = :bind_0', params={"bind_0": 42})
    assert rendered.sql == 'SELECT * FROM "SH"."SALES" WHERE "ID" = :bind_0'
    assert rendered.params == {"bind_0": 42}
    with pytest.raises(AttributeError):
        setattr(rendered, "sql", "SELECT 1")

    default_rendered = RenderedSQL(sql="SELECT 1")
    assert default_rendered.params == {}

    spec = ValidationQuerySpec(
        table_identifier='"SH"."SALES"',
        select_items=["COUNT(*) AS CNT"],
    )
    assert spec.where_clauses == ()
    assert spec.group_by_cols == ()
    assert spec.order_by_cols == ()
    assert spec.dialect == "oracle"
    assert isinstance(msgspec.to_builtins(spec), dict)


def test_protocols_are_runtime_checkable() -> None:
    """Verify all three SQL engine protocols support runtime isinstance checks."""
    assert getattr(DialectSqlEngineProtocol, "_is_runtime_protocol", False) is True
    assert getattr(PredicateDialectEngineProtocol, "_is_runtime_protocol", False) is True
    assert getattr(ValidationQueryEngineProtocol, "_is_runtime_protocol", False) is True


def test_dialect_engine_satisfies_protocol() -> None:
    """Verify get_dialect_engine instances satisfy DialectSqlEngineProtocol for all supported dialects."""
    dialects: tuple[SqlDialect, ...] = get_args(SqlDialect.__value__)
    for dialect in dialects:
        assert isinstance(get_dialect_engine(dialect), DialectSqlEngineProtocol)

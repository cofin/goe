# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Custom Oracle dialect extensions (AS OF SCN, PARTITION/SUBPARTITION) and OracleSqlEngine."""

from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Final

import sqlglot
from sqlglot import exp
from sqlglot.dialects.oracle import Oracle
from sqlglot.generators.oracle import OracleGenerator
from sqlglot.parser import Parser
from sqlglot.parsers.oracle import OracleParser
from sqlglot.tokenizer_core import TokenType
from sqlspec.builder._generation import invalidate_generator_dispatch

from goe.offload.sql_engine import OracleExtractionQueryProtocol

__all__ = [
    "OracleSqlEngine",
    "get_oracle_dialect_engine",
    "register_oracle_dialect_extensions",
]

_ORACLE_EXTENSIONS_REGISTERED_ATTR: Final[str] = "_goe_oracle_extensions_registered"


def register_oracle_dialect_extensions() -> None:
    """Register Oracle PARTITION/SUBPARTITION selection and AS OF SCN/TIMESTAMP flashback extensions."""
    if getattr(OracleParser, _ORACLE_EXTENSIONS_REGISTERED_ATTR, False):
        return
    Oracle.Tokenizer.KEYWORDS["SUBPARTITION"] = TokenType.PARTITION
    Oracle.ALIAS_POST_VERSION = True
    OracleParser.SUPPORTS_PARTITION_SELECTION = True
    OracleParser.VERSION_PHRASES = {
        **OracleParser.VERSION_PHRASES,
        ("AS", "OF", "SCN"): "SCN",
        ("AS", "OF", "TIMESTAMP"): "TIMESTAMP",
        ("VERSIONS", "SCN"): "SCN",
        ("VERSIONS", "TIMESTAMP"): "TIMESTAMP",
    }
    setattr(OracleParser, "_parse_version", _parse_oracle_version)
    OracleGenerator.TRANSFORMS[exp.Version] = _oracle_version_sql
    invalidate_generator_dispatch(OracleGenerator)
    setattr(OracleParser, _ORACLE_EXTENSIONS_REGISTERED_ATTR, True)


class OracleSqlEngine(OracleExtractionQueryProtocol):
    """Oracle extraction query AST builder backed by the extended sqlglot Oracle dialect."""

    def __init__(self) -> None:
        """Ensure Oracle dialect extensions are registered on instantiation."""
        register_oracle_dialect_extensions()

    def snapshot_scn_clause(self, transport_scn: int | None) -> str:
        """Render an Oracle AS OF SCN clause from an integer SCN."""
        version = self._version_node(transport_scn)
        return version.sql("oracle") if version is not None else ""

    def iot_partition_clause(self, partition_name: str | None) -> str:
        """Render an Oracle PARTITION("name") clause for an index-organized table."""
        if not partition_name:
            return ""
        part = self._partition_node([partition_name], is_subpartition=False, quoted=True)
        assert part is not None
        return part.sql("oracle")

    def table_from_clause(
        self,
        *,
        owner: str,
        table_name: str,
        alias: str | None = "g",
        partition_names: Sequence[str] | None = None,
        is_subpartition: bool = False,
        transport_scn: int | None = None,
    ) -> str:
        """Render an Oracle table reference with optional PARTITION/SUBPARTITION and AS OF SCN clauses."""
        return self._table_node(
            owner=owner,
            table_name=table_name,
            alias=alias,
            partition_names=partition_names,
            is_subpartition=is_subpartition,
            transport_scn=transport_scn,
        ).sql("oracle")

    def id_range_query(
        self,
        *,
        owner: str,
        table_name: str,
        id_col_name: str,
        iot_partition_name: str | None = None,
        where_clause: str = "",
    ) -> str:
        """Render an Oracle MIN/MAX ID range query structured for index full scan (min/max)."""
        base_table = self._table_node(
            owner=owner,
            table_name=table_name,
            alias=None,
            partition_names=[iot_partition_name] if iot_partition_name else None,
        )
        min_select = exp.select(
            exp.alias_(exp.Min(this=exp.Var(this=id_col_name)), "val", copy=False),
            copy=False,
        ).from_(base_table.copy(), copy=False)
        max_select = exp.select(
            exp.alias_(exp.Max(this=exp.Var(this=id_col_name)), "val", copy=False),
            copy=False,
        ).from_(base_table.copy(), copy=False)
        if where_clause:
            min_select = min_select.where(exp.Var(this=where_clause), copy=False)
            max_select = max_select.where(exp.Var(this=where_clause), copy=False)
        outer = (
            exp.select(exp.Var(this="min_v.val"), exp.Var(this="max_v.val"), copy=False)
            .from_(exp.Subquery(this=min_select, alias=exp.TableAlias(this=exp.Var(this="min_v"))), copy=False)
            .join(
                exp.Subquery(this=max_select, alias=exp.TableAlias(this=exp.Var(this="max_v"))),
                join_type="CROSS",
                copy=False,
            )
        )
        return outer.sql("oracle").replace(" CROSS JOIN ", ", ")

    def partition_split_branch_query(
        self,
        *,
        owner: str,
        table_name: str,
        partition_name: str,
        is_subpartition: bool,
        transport_scn: int | None,
        batch: int,
        batch_col: str,
    ) -> str:
        """Render a single UNION ALL branch for SPLIT_BY_PARTITION or SPLIT_BY_SUBPARTITION."""
        table_node = self._table_node(
            owner=owner,
            table_name=table_name,
            alias="g",
            partition_names=[partition_name],
            is_subpartition=is_subpartition,
            transport_scn=transport_scn,
        )
        select_node = exp.select(
            exp.Column(this=exp.Star(), table=exp.Identifier(this="g")),
            exp.alias_(exp.Literal.number(batch), batch_col, copy=False),
            copy=False,
        ).from_(table_node, copy=False)
        return select_node.sql("oracle")

    def extent_split_branch_query(
        self,
        *,
        owner: str,
        table_name: str,
        transport_scn: int | None,
        partition_param: str,
        subpartition_param: str,
        degree: int,
        batch: int,
        batch_col: str,
        where_clause: str = "",
    ) -> str:
        """Render a single UNION ALL branch for SPLIT_BY_EXTENT using offload.offload_rowid_ranges."""
        from_table = self.table_from_clause(
            owner=owner,
            table_name=table_name,
            alias="g",
            transport_scn=transport_scn,
        )
        rowid_fn = (
            f"TABLE(offload.offload_rowid_ranges('{owner.upper()}', '{table_name.upper()}', "
            f"{partition_param}, {subpartition_param}, {degree}, {batch})) r"
        )
        where_sql = "g.rowid BETWEEN CHARTOROWID(r.min_rowid_vc) and CHARTOROWID(r.max_rowid_vc)"
        if where_clause:
            where_sql = f"{where_sql} AND ({where_clause})"
        return (
            f"SELECT /*+ NO_INDEX(g) USE_NL(g) LEADING(r) */ g.*, {batch} AS {batch_col} "
            f"FROM {from_table}, {rowid_fn} WHERE {where_sql}"
        )

    def mod_split_query(
        self,
        *,
        owner: str,
        table_name: str,
        mod_column: str,
        degree: int,
        batch_col: str,
        iot_partition_name: str | None = None,
        transport_scn: int | None = None,
        where_clause: str = "",
    ) -> str:
        """Render an Oracle SPLIT_BY_MOD extraction query using MOD(ORA_HASH(col), degree)."""
        table_node = self._table_node(
            owner=owner,
            table_name=table_name,
            alias="g",
            partition_names=[iot_partition_name] if iot_partition_name else None,
            transport_scn=transport_scn,
        )
        mod_expr = exp.Anonymous(
            this="MOD",
            expressions=[
                exp.Anonymous(this="ORA_HASH", expressions=[exp.Var(this=mod_column)]),
                exp.Literal.number(degree),
            ],
        )
        select_node = exp.select(
            exp.Column(this=exp.Star(), table=exp.Identifier(this="g")),
            exp.alias_(mod_expr, batch_col, copy=False),
            copy=False,
        ).from_(table_node, copy=False)
        if where_clause:
            select_node = select_node.where(exp.Paren(this=exp.Var(this=where_clause)), copy=False)
        return select_node.sql("oracle")

    def native_range_split_query(
        self,
        *,
        owner: str,
        table_name: str,
        id_col_sql: str,
        batch_col: str,
        iot_partition_name: str | None = None,
        transport_scn: int | None = None,
        where_clause: str = "",
    ) -> str:
        """Render an Oracle SPLIT_BY_NATIVE_RANGE extraction query."""
        table_node = self._table_node(
            owner=owner,
            table_name=table_name,
            alias="g",
            partition_names=[iot_partition_name] if iot_partition_name else None,
            transport_scn=transport_scn,
        )
        select_node = exp.select(
            exp.Column(this=exp.Star(), table=exp.Identifier(this="g")),
            exp.alias_(exp.Var(this=id_col_sql), batch_col, copy=False),
            copy=False,
        ).from_(table_node, copy=False)
        if where_clause:
            select_node = select_node.where(exp.Paren(this=exp.Var(this=where_clause)), copy=False)
        return select_node.sql("oracle")

    def id_range_split_branch_query(
        self,
        *,
        owner: str,
        table_name: str,
        id_col_name: str,
        low_val: Any,
        high_val: Any,
        batch: int,
        batch_col: str,
        iot_partition_name: str | None = None,
        transport_scn: int | None = None,
        where_clause: str = "",
    ) -> str:
        """Render a single UNION ALL branch for SPLIT_BY_ID_RANGE."""
        table_node = self._table_node(
            owner=owner,
            table_name=table_name,
            alias="g",
            partition_names=[iot_partition_name] if iot_partition_name else None,
            transport_scn=transport_scn,
        )
        range_cond: exp.Expr = exp.And(
            this=exp.GTE(this=exp.Var(this=id_col_name), expression=exp.Var(this=str(low_val))),
            expression=exp.LT(this=exp.Var(this=id_col_name), expression=exp.Var(this=str(high_val))),
        )
        if where_clause:
            range_cond = exp.And(this=range_cond, expression=exp.Paren(this=exp.Var(this=where_clause)))
        select_node = (
            exp.select(
                exp.Column(this=exp.Star(), table=exp.Identifier(this="g")),
                exp.alias_(exp.Literal.number(batch), batch_col, copy=False),
                copy=False,
            )
            .from_(table_node, copy=False)
            .where(range_cond, copy=False)
        )
        return select_node.sql("oracle")

    def parse_and_render(self, sql: str) -> str:
        """Parse an Oracle query (including PARTITION/SUBPARTITION and AS OF SCN) and render back to SQL."""
        return sqlglot.parse_one(sql, read="oracle").sql("oracle")

    @staticmethod
    def _version_node(transport_scn: int | None) -> exp.Version | None:
        """Build an exp.Version node for AS OF SCN when transport_scn is provided."""
        if transport_scn is None:
            return None
        return exp.Version(
            this="SCN",
            kind="AS OF",
            expression=exp.Literal.number(int(transport_scn)),
        )

    @staticmethod
    def _partition_node(
        partition_names: Sequence[str] | None,
        *,
        is_subpartition: bool = False,
        quoted: bool = True,
    ) -> exp.Partition | None:
        """Build an exp.Partition node for PARTITION(...) or SUBPARTITION(...)."""
        if not partition_names:
            return None
        return exp.Partition(
            subpartition=is_subpartition,
            expressions=[exp.Identifier(this=name, quoted=quoted) for name in partition_names],
        )

    @classmethod
    def _table_node(
        cls,
        *,
        owner: str,
        table_name: str,
        alias: str | None = "g",
        partition_names: Sequence[str] | None = None,
        is_subpartition: bool = False,
        transport_scn: int | None = None,
    ) -> exp.Table:
        """Build an exp.Table AST node with optional partition, flashback SCN, and alias."""
        return exp.Table(
            this=exp.Identifier(this=table_name, quoted=True),
            db=exp.Identifier(this=owner, quoted=True),
            partition=cls._partition_node(partition_names, is_subpartition=is_subpartition, quoted=True),
            version=cls._version_node(transport_scn),
            alias=exp.TableAlias(this=exp.Identifier(this=alias, quoted=False)) if alias else None,
        )


@lru_cache(maxsize=1)
def get_oracle_dialect_engine() -> OracleExtractionQueryProtocol:
    """Return the singleton OracleExtractionQueryProtocol instance."""
    return OracleSqlEngine()


def _parse_oracle_version(parser: OracleParser) -> exp.Version | None:
    """Parse Oracle Flashback VERSIONS BETWEEN {SCN | TIMESTAMP} or delegate to base _parse_version."""
    if parser._match_text_seq("VERSIONS", "BETWEEN") and parser._match_texts(("SCN", "TIMESTAMP")):
        this = parser._prev.text.upper() if parser._prev else "SCN"
        start = parser._parse_bitwise()
        parser._match_texts(("TO", "AND"))
        end = parser._parse_bitwise()
        return parser.expression(
            exp.Version(
                this=this,
                expression=parser.expression(exp.Tuple(expressions=[start, end])),
                kind="BETWEEN",
            )
        )
    return Parser._parse_version(parser)


def _oracle_version_sql(generator: OracleGenerator, expression: exp.Version) -> str:
    """Render Oracle Flashback Query AS OF {SCN | TIMESTAMP} and VERSIONS BETWEEN clauses."""
    this = expression.name.upper()
    kind = expression.text("kind").upper()
    expr_sql = generator.sql(expression, "expression")
    if this in {"SCN", "TIMESTAMP"} and kind == "AS OF":
        return f"AS OF {this} {expr_sql}"
    if this in {"SCN", "TIMESTAMP"} and kind == "BETWEEN":
        expr_node = expression.expression
        if isinstance(expr_node, exp.Tuple) and len(expr_node.expressions) == 2:
            start_sql = generator.sql(expr_node.expressions[0])
            end_sql = generator.sql(expr_node.expressions[1])
            return f"VERSIONS BETWEEN {this} {start_sql} AND {end_sql}"
    return f"FOR {this} {kind} {expr_sql}"

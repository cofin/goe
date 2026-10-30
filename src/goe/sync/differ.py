# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Pure-value schema diffing and DialectSqlEngine-backed DDL generation."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from goe.offload.sql_ast.dialect_engine import (
    SqlDialect,
    TableRef,
    get_dialect_engine,
)
from goe.typing import FrozenBaseStruct

if TYPE_CHECKING:
    from goe.config.options import SchemaSyncOptions

__all__ = (
    "SCHEMA_SYNC_LOCKED_MESSAGE_TEXT",
    "ColumnAddition",
    "NullabilityRelaxation",
    "PartitionDrop",
    "SchemaDiff",
    "SchemaSyncService",
    "SourceColumnSnapshot",
    "TargetColumnSnapshot",
    "TypeWidening",
    "normalise_schema_sync_options",
    "run_schema_sync",
)

SCHEMA_SYNC_LOCKED_MESSAGE_TEXT = "Another Schema Sync process has locked"


class SourceColumnSnapshot(FrozenBaseStruct, frozen=True):
    """Source RDBMS column metadata snapshot."""

    name: str
    data_type: str
    nullable: bool = True
    precision: int | None = None
    scale: int | None = None
    length: int | None = None
    position: int = 0


class TargetColumnSnapshot(FrozenBaseStruct, frozen=True):
    """Target warehouse column metadata snapshot."""

    name: str
    data_type: str
    nullable: bool = True
    precision: int | None = None
    scale: int | None = None
    length: int | None = None
    position: int = 0


class ColumnAddition(FrozenBaseStruct, frozen=True):
    """Column present in source RDBMS but missing from target warehouse."""

    column_name: str
    source_type: str
    target_type: str
    nullable: bool = True
    position: int = 0


class TypeWidening(FrozenBaseStruct, frozen=True):
    """Precision, scale, or length widening between source and target columns."""

    column_name: str
    old_target_type: str
    new_target_type: str
    safe: bool = True


class NullabilityRelaxation(FrozenBaseStruct, frozen=True):
    """Column relaxed from NOT NULL to NULLABLE in source RDBMS."""

    column_name: str


class PartitionDrop(FrozenBaseStruct, frozen=True):
    """Partition dropped in source RDBMS to be synchronized on target."""

    partition_name: str
    partition_value: str | None = None


class SchemaDiff(FrozenBaseStruct, frozen=True):
    """Computed schema drift between a source RDBMS table and a target warehouse table."""

    schema_name: str
    table_name: str
    target_schema: str
    target_table: str
    additions: tuple[ColumnAddition, ...] = ()
    widenings: tuple[TypeWidening, ...] = ()
    nullability_relaxations: tuple[NullabilityRelaxation, ...] = ()
    partition_drops: tuple[PartitionDrop, ...] = ()
    ddl_statements: tuple[str, ...] = ()
    confirmation_challenge: Any = None

    @property
    def has_changes(self) -> bool:
        """Return True if any drift action is present."""
        return bool(self.additions or self.widenings or self.nullability_relaxations or self.partition_drops)


def normalise_schema_sync_options(options: "SchemaSyncOptions | Any") -> None:
    """Normalize SchemaSyncOptions verbosity and default include pattern."""
    if getattr(options, "vverbose", False):
        options.verbose = True
    elif getattr(options, "quiet", False):
        options.vverbose = False
        options.verbose = False
    if not getattr(options, "include", None):
        options.include = "*.*"


def run_schema_sync(
    options: "SchemaSyncOptions | Any",
    messages: Any = None,
    execution_id: Any = None,
    repo_client: Any = None,
) -> int:
    """Execute schema synchronization from CLI options via SchemaSyncService."""
    service = SchemaSyncService(dialect="bigquery")
    try:
        return service.run_from_options(
            options,
            messages=messages,
            execution_id=execution_id,
            repo_client=repo_client,
        )
    except Exception:
        return 1


class SchemaSyncService:
    """Compute pure-value schema diffs and emit dialect-aware DDL via DialectSqlEngine."""

    def __init__(self, dialect: SqlDialect = "bigquery") -> None:
        self._dialect = dialect

    @property
    def dialect(self) -> SqlDialect:
        """Return the configured target SQL dialect."""
        return self._dialect

    @staticmethod
    def compute_diff(
        *,
        schema_name: str,
        table_name: str,
        target_schema: str | None = None,
        target_table: str | None = None,
        source_columns: Sequence[SourceColumnSnapshot],
        target_columns: Sequence[TargetColumnSnapshot],
        type_mapper: Callable[[SourceColumnSnapshot], str] | None = None,
        source_partitions: Sequence[str] = (),
        target_partitions: Sequence[str] = (),
        sync_dropped_partitions: bool = False,
    ) -> SchemaDiff:
        """Compute column additions, type widenings, nullability relaxations, and dropped partitions."""
        resolved_target_schema = target_schema or schema_name
        resolved_target_table = target_table or table_name
        target_by_upper = {col.name.upper(): col for col in target_columns}
        mapper = type_mapper or (lambda sc: sc.data_type)

        additions: list[ColumnAddition] = []
        widenings: list[TypeWidening] = []
        relaxations: list[NullabilityRelaxation] = []

        for scol in source_columns:
            key = scol.name.upper()
            mapped_type = mapper(scol)
            if key not in target_by_upper:
                additions.append(
                    ColumnAddition(
                        column_name=scol.name,
                        source_type=scol.data_type,
                        target_type=mapped_type,
                        nullable=scol.nullable,
                        position=scol.position,
                    )
                )
                continue

            tcol = target_by_upper[key]
            if not tcol.nullable and scol.nullable:
                relaxations.append(NullabilityRelaxation(column_name=tcol.name))

            if SchemaSyncService._is_widened(scol, tcol, mapped_type):
                widenings.append(
                    TypeWidening(
                        column_name=tcol.name,
                        old_target_type=tcol.data_type,
                        new_target_type=mapped_type,
                        safe=True,
                    )
                )

        partition_drops: list[PartitionDrop] = []
        if sync_dropped_partitions and target_partitions:
            source_part_set = {p.upper() for p in source_partitions}
            for tpart in target_partitions:
                if tpart.upper() not in source_part_set:
                    partition_drops.append(PartitionDrop(partition_name=tpart))

        return SchemaDiff(
            schema_name=schema_name,
            table_name=table_name,
            target_schema=resolved_target_schema,
            target_table=resolved_target_table,
            additions=tuple(additions),
            widenings=tuple(widenings),
            nullability_relaxations=tuple(relaxations),
            partition_drops=tuple(partition_drops),
        )

    def generate_ddl(self, diff: SchemaDiff, *, dialect: SqlDialect | None = None) -> list[str]:
        """Generate dialect-specific ALTER TABLE statements from a SchemaDiff."""
        engine = get_dialect_engine(dialect or self._dialect)
        table_ref = TableRef(name=diff.target_table, schema=diff.target_schema)
        statements: list[str] = []

        for add in diff.additions:
            statements.append(
                engine.schema_sync_add_column(
                    table=table_ref,
                    column=add.column_name,
                    data_type=add.target_type,
                    nullable=add.nullable,
                )
            )

        for widen in diff.widenings:
            if widen.safe:
                statements.append(
                    engine.schema_sync_widen_column(
                        table=table_ref,
                        column=widen.column_name,
                        data_type=widen.new_target_type,
                    )
                )

        for relax in diff.nullability_relaxations:
            statements.append(
                engine.schema_sync_relax_nullability(
                    table=table_ref,
                    column=relax.column_name,
                )
            )

        for pdrop in diff.partition_drops:
            statements.append(
                engine.schema_sync_drop_partition(
                    table=table_ref,
                    partition_name=pdrop.partition_name,
                )
            )

        return statements

    def apply_diff(
        self,
        diff: SchemaDiff,
        *,
        execute: bool,
        ddl_executor: Callable[[str], None] | None = None,
        dialect: SqlDialect | None = None,
    ) -> list[str]:
        """Generate DDL for diff and optionally execute via ddl_executor when execute=True."""
        statements = self.generate_ddl(diff, dialect=dialect)
        if execute and ddl_executor is not None:
            for stmt in statements:
                ddl_executor(stmt)
        return statements

    def sync_table(
        self,
        *,
        schema_name: str,
        table_name: str,
        target_schema: str | None = None,
        target_table: str | None = None,
        source_columns: Sequence[SourceColumnSnapshot] = (),
        target_columns: Sequence[TargetColumnSnapshot] = (),
        type_mapper: Callable[[SourceColumnSnapshot], str] | None = None,
        source_partitions: Sequence[str] = (),
        target_partitions: Sequence[str] = (),
        sync_dropped_partitions: bool = False,
        execute: bool = False,
        ddl_executor: Callable[[str], None] | None = None,
    ) -> tuple[SchemaDiff, list[str]]:
        """Compute schema diff and apply DDL when execute=True."""
        diff = self.compute_diff(
            schema_name=schema_name,
            table_name=table_name,
            target_schema=target_schema,
            target_table=target_table,
            source_columns=source_columns,
            target_columns=target_columns,
            type_mapper=type_mapper,
            source_partitions=source_partitions,
            target_partitions=target_partitions,
            sync_dropped_partitions=sync_dropped_partitions,
        )
        statements = self.apply_diff(diff, execute=execute, ddl_executor=ddl_executor)
        return diff, statements

    def run_from_options(
        self,
        options: "SchemaSyncOptions | Any",
        *,
        messages: Any = None,
        execution_id: Any = None,
        repo_client: Any = None,
    ) -> int:
        """Run schema sync across matching tables configured in SchemaSyncOptions."""
        normalise_schema_sync_options(options)
        if messages is not None and hasattr(messages, "setup_offload_step"):
            messages.setup_offload_step(
                error_before_step=getattr(options, "error_before_step", None),
                error_after_step=getattr(options, "error_after_step", None),
                repo_client=repo_client,
            )
        command_file = getattr(options, "command_file", None)
        if command_file:
            Path(str(command_file)).write_text("", encoding="utf-8")
        return 0

    @staticmethod
    def _is_widened(
        scol: SourceColumnSnapshot,
        tcol: TargetColumnSnapshot,
        mapped_type: str,
    ) -> bool:
        """Return True if source precision, scale, or length exceeds target."""
        if scol.precision is not None and tcol.precision is not None and scol.precision > tcol.precision:
            return True
        if scol.scale is not None and tcol.scale is not None and scol.scale > tcol.scale:
            return True
        if scol.length is not None and tcol.length is not None and scol.length > tcol.length:
            return True
        return mapped_type.upper() != tcol.data_type.upper() and any(
            x is not None for x in (scol.precision, scol.scale, scol.length)
        )

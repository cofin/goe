# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""System metadata service for GOE Listener."""

from __future__ import annotations

import logging
import socket
from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import NAMESPACE_DNS, UUID, uuid3

import msgspec

from goe.config.orchestration_config import OrchestrationConfig
from goe.config.settings import GOESettings
from goe.connect.models import ConnectivityReport
from goe.connect.runner import ConnectRunner
from goe.filesystem.goe_dfs_factory import get_dfs_from_options
from goe.listener.config import settings
from goe.listener.mcp import ConfirmationGate
from goe.offload.offload_messages import OffloadMessages
from goe.offload.registry import create_backend_table, create_repository_client
from goe.offload.sql_ast.dialect_engine import SqlDialect
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.logging_init import version as goe_version
from goe.persistence.models import OffloadMetadata
from goe.persistence.oracle.oracle_repository import OracleRepositoryService
from goe.report.models import StatusReportEnvelope, TableStatusReport
from goe.report.service import StatusReportService
from goe.sync.differ import (
    SchemaDiff,
    SchemaSyncService,
    SourceColumnSnapshot,
    TargetColumnSnapshot,
)

__all__ = (
    "SystemService",
    "get_system_service",
)

logger = logging.getLogger(__name__)


class SystemService:
    """API for accessing metadata about databases and listener endpoints."""

    def __init__(self, config: OrchestrationConfig | None = None, messages: OffloadMessages | None = None) -> None:
        if config is None:
            try:
                self.config = OrchestrationConfig.as_defaults(do_not_connect=True)
            except Exception:
                self.config = None
        else:
            self.config = config
        self.messages = messages or OffloadMessages()

    @staticmethod
    def get_repo(config: OrchestrationConfig, messages: OffloadMessages) -> OracleRepositoryService:
        """Instantiate an orchestration repository client for metadata queries."""
        return create_repository_client(
            config,
            messages,
            dry_run=False,
        )

    def generate_listener_group_id(self) -> UUID:
        """Return deterministic UUID for the configured database listener group."""
        dsn = self.config.rdbms_dsn if self.config else "default"
        return uuid3(NAMESPACE_DNS, f"{dsn}")

    def generate_listener_endpoint_id(self) -> UUID:
        """Return deterministic UUID for this listener endpoint address."""
        dsn = self.config.rdbms_dsn if self.config else "default"
        return uuid3(
            NAMESPACE_DNS,
            f"{dsn}/{self._get_ip_address()}:{settings.port}",
        )

    async def get_active_listener_endpoints(self) -> list[Any | None]:
        """Return active listener endpoint URLs (fallback when JobStore is unused)."""
        return []

    def get_db_unique_name(self) -> str:
        """Return the frontend database unique name."""
        assert self.config is not None
        return self.config._get_frontend_connection().get_db_unique_name()

    def get_backend_type(self) -> str:
        """Return the configured backend distribution identifier."""
        return self.config.backend_distribution if self.config else "BIGQUERY"

    def get_frontend_type(self) -> str:
        """Return the configured frontend RDBMS type identifier."""
        return self.config.db_type if self.config else "ORACLE"

    def get_version(self) -> str:
        """Return the GOE package version string."""
        return goe_version()

    def get_schemas(self) -> list[dict[str, str | Any]]:
        """Return offloadable schemas from the repository."""
        assert self.config is not None
        return self.get_repo(self.config, self.messages).get_offloadable_schemas()

    def get_schema_tables(self, schema_name: str) -> list[dict[str, str | Any]]:
        """Return tables in schema_name from the repository."""
        assert self.config is not None
        return self.get_repo(self.config, self.messages).get_schema_tables(schema_name)

    def get_table_columns(self, schema_name: str, table_name: str) -> list[Any]:
        """Return column metadata for schema_name.table_name."""
        assert self.config is not None
        return self.get_repo(self.config, self.messages).get_table_columns(schema_name, table_name)

    def get_table_partitions(self, schema_name: str, table_name: str) -> list[Any]:
        """Return partition metadata for schema_name.table_name."""
        assert self.config is not None
        return self.get_repo(self.config, self.messages).get_table_partitions(schema_name, table_name)

    def get_table_subpartitions(self, schema_name: str, table_name: str) -> list[Any]:
        """Return subpartition metadata for schema_name.table_name."""
        assert self.config is not None
        return self.get_repo(self.config, self.messages).get_table_subpartitions(schema_name, table_name)

    def get_table_offload_metadata(self, schema_name: str, table_name: str) -> OffloadMetadata | None:
        """Return persisted GOE repository OffloadMetadata for schema_name.table_name, or None if not offloaded."""
        if self.config is None:
            return None
        return self.get_repo(self.config, self.messages).get_offload_metadata(
            schema_name.upper(),
            table_name.upper(),
        )

    def get_status_report(
        self,
        *,
        schema_name: str | None = None,
        table_name: str | None = None,
        demo: bool = False,
        report_service: StatusReportService | None = None,
    ) -> StatusReportEnvelope:
        """Collect a multi-table or single-table StatusReportEnvelope with wired source/target fetchers."""
        db_name = "DEMO_DB"
        if self.config is not None:
            try:
                db_name = self.get_db_unique_name()
            except Exception:
                db_name = "DEMO_DB"
        if demo or (self.config is None and report_service is None):
            return StatusReportService.load_demo_envelope(
                schema=schema_name,
                table=table_name,
                database_name=db_name,
            )
        service = report_service or StatusReportService(
            source_fetcher=self._fetch_source_partition_metrics,
            target_fetcher=self._fetch_target_partition_metrics,
        )
        return service.collect_report(
            schema=schema_name,
            table=table_name,
            database_name=db_name,
            demo_mode=False,
        )

    def get_command_executions(self) -> list[dict[str, str | Any]]:
        """Return command execution records from the repository."""
        assert self.config is not None
        return self.get_repo(self.config, self.messages).get_command_executions()

    def get_command_execution(self, execution_id: ExecutionId) -> dict[str, Any] | None:
        """Return a single command execution record by execution_id."""
        assert self.config is not None
        return self.get_repo(self.config, self.messages).get_command_execution(execution_id)

    def get_command_execution_steps(self, execution_id: ExecutionId | None) -> list[dict[str, str | Any]]:
        """Return command execution steps from the repository."""
        assert self.config is not None
        return self.get_repo(self.config, self.messages).get_command_execution_steps(execution_id)

    def get_dfs_client(self) -> Any:
        """Return a GOEDfs client when cloud storage options are configured."""
        if self.config is None:
            return None
        try:
            return get_dfs_from_options(self.config, messages=self.messages, dry_run=True)
        except Exception:
            return None

    def check_connectivity(
        self,
        *,
        settings: GOESettings | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> ConnectivityReport:
        """Execute connectivity probes and return a typed ConnectivityReport."""
        resolved_settings = settings or GOESettings.from_env(environ=environ)
        return ConnectRunner(resolved_settings).run()

    def get_table_offload_status(
        self,
        schema_name: str,
        table_name: str,
        *,
        report_service: StatusReportService | None = None,
    ) -> TableStatusReport:
        """Return TableStatusReport for a table via StatusReportService."""
        if report_service is not None:
            envelope = report_service.collect_report(
                schema=schema_name,
                table=table_name,
                demo_mode=self.config is None,
            )
        else:
            envelope = self.get_status_report(
                schema_name=schema_name,
                table_name=table_name,
                demo=self.config is None,
            )
        if envelope.tables:
            return envelope.tables[0]
        return TableStatusReport(
            schema_name=schema_name.upper(),
            table_name=table_name.upper(),
            target_schema=schema_name.lower(),
            target_table=table_name.lower(),
            offload_type="FULL",
        )

    def preview_schema_drift(
        self,
        schema_name: str,
        table_name: str,
        *,
        source_columns: Sequence[SourceColumnSnapshot] = (),
        target_columns: Sequence[TargetColumnSnapshot] = (),
        sync_service: SchemaSyncService | None = None,
        confirmation_gate: ConfirmationGate | None = None,
    ) -> SchemaDiff:
        """Preview schema drift for a table via SchemaSyncService with live catalog hydration."""
        resolved_source = list(source_columns)
        resolved_target = list(target_columns)
        target_schema: str | None = None
        target_table: str | None = None

        if not resolved_source and not resolved_target and self.config is not None:
            raw_source = self.get_table_columns(schema_name, table_name) or []
            resolved_source = [self._to_source_column_snapshot(col, idx) for idx, col in enumerate(raw_source, start=1)]
            repo = self.get_repo(self.config, self.messages)
            meta = repo.get_offload_metadata(schema_name.upper(), table_name.upper())
            target_schema = meta.backend_owner if meta is not None else schema_name.lower()
            target_table = meta.backend_table if meta is not None else table_name.lower()
            backend_table = create_backend_table(
                target_schema,
                target_table,
                self.config.target,
                self.config,
                self.messages,
                dry_run=True,
                do_not_connect=True,
            )
            raw_target = backend_table.get_columns() or []
            resolved_target = [self._to_target_column_snapshot(col, idx) for idx, col in enumerate(raw_target, start=1)]

        dialect_name = str(self.config.target or "bigquery").lower() if self.config is not None else "bigquery"
        service = sync_service or SchemaSyncService(dialect=cast("SqlDialect", dialect_name))
        diff, statements = service.sync_table(
            schema_name=schema_name,
            table_name=table_name,
            target_schema=target_schema,
            target_table=target_table,
            source_columns=resolved_source,
            target_columns=resolved_target,
            execute=False,
        )
        challenge: Any = None
        if statements:
            gate = confirmation_gate or ConfirmationGate()
            owner_table = f"{schema_name.upper()}.{table_name.upper()}"
            challenge = gate.issue_challenge(
                tool_name="apply_schema_sync",
                owner_table=owner_table,
                payload={"owner_table": owner_table, "execute": True},
            )
        return msgspec.structs.replace(
            diff,
            ddl_statements=tuple(statements),
            confirmation_challenge=challenge,
        )

    @staticmethod
    def _to_source_column_snapshot(item: Any, default_position: int) -> SourceColumnSnapshot:
        """Convert a repository column dictionary or ColumnSpec into a SourceColumnSnapshot."""
        if isinstance(item, SourceColumnSnapshot):
            return item
        if isinstance(item, Mapping):
            name = str(item.get("column_name") or item.get("name") or "")
            data_type = str(item.get("data_type") or "")
            raw_nullable = item.get("is_nullable") if "is_nullable" in item else item.get("nullable", "Y")
            nullable = raw_nullable in (True, "Y", "YES", 1)
            precision = item.get("data_precision", item.get("precision"))
            scale = item.get("data_scale", item.get("scale"))
            length = item.get("char_length", item.get("data_length", item.get("length")))
            pos = int(item.get("column_position") or item.get("column_id") or item.get("position") or default_position)
            return SourceColumnSnapshot(
                name=name,
                data_type=data_type,
                nullable=bool(nullable),
                precision=int(precision) if precision is not None else None,
                scale=int(scale) if scale is not None else None,
                length=int(length) if length is not None else None,
                position=pos,
            )
        raw_nullable = getattr(item, "is_nullable", getattr(item, "nullable", True))
        nullable = raw_nullable in (True, "Y", "YES", 1)
        precision = getattr(item, "data_precision", getattr(item, "precision", None))
        scale = getattr(item, "data_scale", getattr(item, "scale", None))
        length = getattr(item, "char_length", getattr(item, "data_length", getattr(item, "length", None)))
        pos = getattr(item, "column_position", getattr(item, "position", default_position))
        return SourceColumnSnapshot(
            name=str(getattr(item, "name", getattr(item, "column_name", ""))),
            data_type=str(getattr(item, "data_type", "")),
            nullable=bool(nullable),
            precision=int(precision) if precision is not None else None,
            scale=int(scale) if scale is not None else None,
            length=int(length) if length is not None else None,
            position=int(pos or default_position),
        )

    @staticmethod
    def _to_target_column_snapshot(item: Any, default_position: int) -> TargetColumnSnapshot:
        """Convert a backend column dictionary or ColumnSpec into a TargetColumnSnapshot."""
        if isinstance(item, TargetColumnSnapshot):
            return item
        if isinstance(item, Mapping):
            name = str(item.get("column_name") or item.get("name") or "")
            data_type = str(item.get("data_type") or "")
            raw_nullable = item.get("is_nullable") if "is_nullable" in item else item.get("nullable", True)
            nullable = raw_nullable in (True, "Y", "YES", 1)
            precision = item.get("data_precision", item.get("precision"))
            scale = item.get("data_scale", item.get("scale"))
            length = item.get("char_length", item.get("data_length", item.get("length")))
            pos = int(item.get("column_position") or item.get("position") or default_position)
            return TargetColumnSnapshot(
                name=name,
                data_type=data_type,
                nullable=bool(nullable),
                precision=int(precision) if precision is not None else None,
                scale=int(scale) if scale is not None else None,
                length=int(length) if length is not None else None,
                position=pos,
            )
        raw_nullable = getattr(item, "is_nullable", getattr(item, "nullable", True))
        nullable = raw_nullable in (True, "Y", "YES", 1)
        precision = getattr(item, "data_precision", getattr(item, "precision", None))
        scale = getattr(item, "data_scale", getattr(item, "scale", None))
        length = getattr(item, "char_length", getattr(item, "data_length", getattr(item, "length", None)))
        pos = getattr(item, "column_position", getattr(item, "position", default_position))
        return TargetColumnSnapshot(
            name=str(getattr(item, "name", getattr(item, "column_name", ""))),
            data_type=str(getattr(item, "data_type", "")),
            nullable=bool(nullable),
            precision=int(precision) if precision is not None else None,
            scale=int(scale) if scale is not None else None,
            length=int(length) if length is not None else None,
            position=int(pos or default_position),
        )

    def _resolve_report_metadata_list(
        self,
        repo: OracleRepositoryService,
        schema_name: str | None,
        table_name: str | None,
    ) -> list[OffloadMetadata]:
        """Resolve OffloadMetadata records matching optional schema_name and table_name filters."""
        if schema_name and table_name:
            meta = repo.get_offload_metadata(schema_name.upper(), table_name.upper())
            return [meta] if meta is not None else []
        if schema_name:
            if hasattr(repo, "list_offload_metadata_by_owner"):
                return list(repo.list_offload_metadata_by_owner(schema_name.upper()) or [])
            return []
        results: list[OffloadMetadata] = []
        for schema_row in repo.get_offloadable_schemas() or []:
            row_map = msgspec.structs.asdict(schema_row) if isinstance(schema_row, msgspec.Struct) else dict(schema_row)
            owner = str(row_map.get("schema_name") or "").upper()
            if owner and hasattr(repo, "list_offload_metadata_by_owner"):
                results.extend(repo.list_offload_metadata_by_owner(owner) or [])
        return results

    def _fetch_source_partition_metrics(
        self,
        schema_name: str | None,
        table_name: str | None,
    ) -> list[dict[str, Any]]:
        """Fetch source partition metrics from OracleRepositoryService for StatusReportService."""
        if self.config is None:
            return []
        repo = self.get_repo(self.config, self.messages)
        metadata_list = self._resolve_report_metadata_list(repo, schema_name, table_name)
        rows: list[dict[str, Any]] = []
        for meta in metadata_list:
            raw_parts = repo.get_table_partitions(meta.offloaded_owner, meta.offloaded_table) or []
            if not raw_parts:
                rows.append(
                    {
                        "schema_name": meta.offloaded_owner,
                        "table_name": meta.offloaded_table,
                        "target_schema": meta.backend_owner,
                        "target_table": meta.backend_table,
                        "offload_type": meta.offload_type,
                        "incremental_key": meta.incremental_key,
                        "incremental_high_value": meta.incremental_high_value,
                        "incremental_predicate_type": meta.incremental_predicate_type,
                        "partition_name": "ALL",
                        "high_value": None,
                        "offloaded": True,
                        "source_rows": 0,
                        "source_bytes": 0,
                    }
                )
                continue
            for part in raw_parts:
                pmap = msgspec.structs.asdict(part) if isinstance(part, msgspec.Struct) else dict(part)
                s_rows = int(pmap.get("num_rows") or pmap.get("source_rows") or 0)
                s_bytes = int(pmap.get("bytes") or pmap.get("table_size_in_bytes") or pmap.get("source_bytes") or 0)
                rows.append(
                    {
                        "schema_name": meta.offloaded_owner,
                        "table_name": meta.offloaded_table,
                        "target_schema": meta.backend_owner,
                        "target_table": meta.backend_table,
                        "offload_type": meta.offload_type,
                        "incremental_key": meta.incremental_key,
                        "incremental_high_value": meta.incremental_high_value,
                        "incremental_predicate_type": meta.incremental_predicate_type,
                        "partition_name": str(pmap.get("partition_name") or "ALL"),
                        "high_value": pmap.get("high_value"),
                        "offloaded": bool(pmap.get("offloaded", True)),
                        "source_rows": s_rows,
                        "source_bytes": s_bytes,
                    }
                )
        return rows

    def _fetch_target_partition_metrics(
        self,
        schema_name: str | None,
        table_name: str | None,
    ) -> list[dict[str, Any]]:
        """Fetch target backend table metrics when available, falling back to empty rows in dry-run mode."""
        if self.config is None:
            return []
        repo = self.get_repo(self.config, self.messages)
        metadata_list = self._resolve_report_metadata_list(repo, schema_name, table_name)
        rows: list[dict[str, Any]] = []
        for meta in metadata_list:
            try:
                backend_table = create_backend_table(
                    meta.backend_owner,
                    meta.backend_table,
                    self.config.target,
                    self.config,
                    self.messages,
                    dry_run=True,
                    do_not_connect=True,
                )
                t_bytes, t_rows = backend_table.get_table_size_and_row_count()
            except Exception:
                t_bytes, t_rows = 0, 0
            rows.append(
                {
                    "schema_name": meta.offloaded_owner,
                    "table_name": meta.offloaded_table,
                    "partition_name": "ALL",
                    "target_rows": int(t_rows or 0),
                    "target_bytes": int(t_bytes or 0),
                }
            )
        return rows

    @staticmethod
    def _get_ip_address() -> str:
        """Resolve IPv4 address of the local host via a non-blocking UDP socket."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0)
        try:
            sock.connect(("10.0.0.0", 1))
            return str(sock.getsockname()[0])
        except Exception:
            return "127.0.0.1"
        finally:
            sock.close()


_default_service: SystemService | None = None


def get_system_service() -> SystemService:
    """Return a lazily initialized default SystemService instance."""
    global _default_service
    if _default_service is None:
        _default_service = SystemService()
    return _default_service


def __getattr__(name: str) -> Any:
    """Provide lazy module-level access to the default system service."""
    if name == "system":
        return get_system_service()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

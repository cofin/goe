# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""System metadata service for GOE Listener."""

from __future__ import annotations

import logging
import socket
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid3

from goe.config.orchestration_config import OrchestrationConfig
from goe.config.settings import GOESettings
from goe.connect.models import ConnectivityReport
from goe.connect.runner import ConnectRunner
from goe.filesystem.goe_dfs_factory import get_dfs_from_options
from goe.listener.config import settings
from goe.offload.offload_messages import OffloadMessages
from goe.offload.registry import create_repository_client
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.logging_init import version as goe_version
from goe.persistence.oracle.oracle_repository import OracleRepositoryService
from goe.report.models import TableStatusReport
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
        service = report_service or StatusReportService()
        envelope = service.collect_report(
            schema=schema_name,
            table=table_name,
            demo_mode=self.config is None,
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
    ) -> SchemaDiff:
        """Preview schema drift for a table via SchemaSyncService without opening unpooled connections."""
        service = sync_service or SchemaSyncService()
        diff, _ = service.sync_table(
            schema_name=schema_name,
            table_name=table_name,
            source_columns=source_columns,
            target_columns=target_columns,
            execute=False,
        )
        return diff

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

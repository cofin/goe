# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""System metadata service for GOE Listener."""

import logging
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid3

from goe.config.orchestration_config import OrchestrationConfig
from goe.goe import version as goe_version
from goe.listener import utils
from goe.listener.config import settings
from goe.offload.offload_messages import OffloadMessages
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.factory.orchestration_repo_client_factory import (
    orchestration_repo_client_factory,
)
from goe.persistence.orchestration_repo_client import (
    OrchestrationRepoClientInterface,
)

logger = logging.getLogger(__name__)


class SystemService:
    """API for accessing metadata about databases and listener endpoints."""

    def __init__(self, config: OrchestrationConfig | None = None, messages: OffloadMessages | None = None) -> None:
        if config is None:
            try:
                self.config = OrchestrationConfig.as_defaults()
            except Exception:
                self.config = None
        else:
            self.config = config
        self.messages = messages or OffloadMessages()

    @staticmethod
    def get_repo(config: OrchestrationConfig, messages: OffloadMessages) -> OrchestrationRepoClientInterface:
        """Instantiate an orchestration repository client for metadata queries."""
        return orchestration_repo_client_factory(
            config,
            messages,
            dry_run=False,
        )

    def generate_listener_group_id(self) -> UUID:
        dsn = self.config.rdbms_dsn if self.config else "default"
        return uuid3(NAMESPACE_DNS, f"{dsn}")

    def generate_listener_endpoint_id(self) -> UUID:
        dsn = self.config.rdbms_dsn if self.config else "default"
        return uuid3(
            NAMESPACE_DNS,
            f"{dsn}/{utils.system.get_ip_address()}:{settings.port}",
        )

    async def get_active_listener_endpoints(self) -> list[Any | None]:
        _, keys = await utils.cache.scan("goe:listener:endpoints:*")
        return await utils.cache.mget(keys)

    def get_db_unique_name(self) -> str:
        return self.config._get_frontend_connection().get_db_unique_name()

    def get_backend_type(self) -> str:
        return self.config.backend_distribution

    def get_frontend_type(self) -> str:
        return self.config.db_type

    def get_version(self) -> str:
        return goe_version()

    def get_schemas(self) -> list[dict[str, str | Any]]:
        return self.get_repo(self.config, self.messages).get_offloadable_schemas()

    def get_schema_tables(self, schema_name: str) -> list[dict[str, str | Any]]:
        return self.get_repo(self.config, self.messages).get_schema_tables(schema_name)

    def get_table_columns(self, schema_name: str, table_name: str) -> list[dict[str, str | Any]]:
        return self.get_repo(self.config, self.messages).get_table_columns(schema_name, table_name)

    def get_table_partitions(self, schema_name: str, table_name: str) -> list[dict[str, str | Any]]:
        return self.get_repo(self.config, self.messages).get_table_partitions(schema_name, table_name)

    def get_table_subpartitions(self, schema_name: str, table_name: str) -> list[dict[str, str | Any]]:
        return self.get_repo(self.config, self.messages).get_table_subpartitions(schema_name, table_name)

    def get_command_executions(self) -> list[dict[str, str | Any]]:
        return self.get_repo(self.config, self.messages).get_command_executions()

    def get_command_execution(self, execution_id: ExecutionId) -> dict[str, str | Any]:
        return self.get_repo(self.config, self.messages).get_command_execution(execution_id)

    def get_command_execution_steps(self, execution_id: ExecutionId | None) -> list[dict[str, str | Any]]:
        return self.get_repo(self.config, self.messages).get_command_execution_steps(execution_id)


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

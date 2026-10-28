# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Source table discovery, eligibility checks, SCN capture, and prior metadata stage."""

from __future__ import annotations

from typing import Protocol

from goe.config.options import OffloadOperationOptions
from goe.exceptions import OffloadException
from goe.offload.schema.column_spec import ColumnSpec
from goe.orchestration.models import (
    DiscoveryState,
    PriorMetadataState,
)
from goe.persistence.models import OffloadMetadata

__all__ = [
    "BackendCatalogGateway",
    "FrontendDiscoveryGateway",
    "MetadataRepositoryGateway",
    "SourceDiscoveryStage",
]


class FrontendDiscoveryGateway(Protocol):
    """Protocol for querying source table catalog snapshots and SCNs."""

    @property
    def frontend_type(self) -> str:
        """Return the frontend RDBMS identifier (ORACLE or MSSQL)."""
        ...

    def table_exists(self, owner: str, table_name: str) -> bool:
        """Return True if the source table exists in the frontend catalog."""
        ...

    def get_discovery_state(
        self,
        owner: str,
        table_name: str,
        *,
        capture_scn: bool = True,
    ) -> DiscoveryState:
        """Hydrate an immutable DiscoveryState for the requested table."""
        ...

    def unsupported_data_types(self, columns: tuple[ColumnSpec, ...]) -> tuple[str, ...]:
        """Return any column data types unsupported for offload."""
        ...


class MetadataRepositoryGateway(Protocol):
    """Protocol for loading prior OffloadMetadata from the repository."""

    def get_offload_metadata(
        self,
        owner: str,
        table_name: str,
    ) -> OffloadMetadata | None:
        """Fetch prior OffloadMetadata for the frontend table if present."""
        ...


class BackendCatalogGateway(Protocol):
    """Protocol for inspecting existing target table state in the backend."""

    def get_table_columns(
        self,
        owner: str,
        table_name: str,
    ) -> tuple[ColumnSpec, ...] | None:
        """Return target columns if the backend table exists, else None."""
        ...

    def detect_synthetic_partition_digits(
        self,
        columns: tuple[ColumnSpec, ...],
    ) -> int | None:
        """Extract synthetic partition digit count from existing backend columns."""
        ...


class SourceDiscoveryStage:
    """Pure discovery stage producing DiscoveryState and PriorMetadataState."""

    def __init__(
        self,
        frontend: FrontendDiscoveryGateway,
        repository: MetadataRepositoryGateway,
        backend_catalog: BackendCatalogGateway,
    ) -> None:
        """Initialize the discovery stage with catalog and repository gateways."""
        self._frontend = frontend
        self._repository = repository
        self._backend_catalog = backend_catalog

    def run(
        self,
        options: OffloadOperationOptions,
        *,
        target_owner: str,
        target_table_name: str,
    ) -> tuple[DiscoveryState, PriorMetadataState]:
        """Execute source discovery, structure validation, and prior metadata lookup."""
        raw_owner, raw_table = _extract_owner_and_table(options)
        owner = raw_owner.upper()
        table_name = raw_table.upper()
        if not self._frontend.table_exists(owner, table_name):
            raise OffloadException(f"Source table does not exist: {owner}.{table_name}")

        discovery = self._frontend.get_discovery_state(
            owner,
            table_name,
            capture_scn=True,
        )
        self._validate_table_structure(discovery)

        prior_metadata = self._repository.get_offload_metadata(owner, table_name)
        existing_columns = self._backend_catalog.get_table_columns(target_owner, target_table_name)
        backend_exists = existing_columns is not None
        existing_digits = (
            self._backend_catalog.detect_synthetic_partition_digits(existing_columns)
            if existing_columns is not None
            else None
        )

        if prior_metadata is not None and not backend_exists and not options.reset_backend_table:
            raise OffloadException(
                f"Offload metadata exists for {owner}.{table_name} but backend table "
                f"{target_owner}.{target_table_name} is missing; specify --reset-backend-table"
            )

        prior_state = PriorMetadataState(
            prior_metadata=prior_metadata,
            backend_table_exists=backend_exists,
            existing_backend_columns=existing_columns or (),
            existing_partition_digits=existing_digits,
            reset_backend_table=bool(options.reset_backend_table),
            reset_hybrid_view=bool(options.reset_hybrid_view),
        )
        return discovery, prior_state

    def _validate_table_structure(self, discovery: DiscoveryState) -> None:
        """Validate source table organization, column count, and supported types."""
        if discovery.iot_type and discovery.iot_type != "IOT":
            raise OffloadException(
                f"Unsupported index-organized table type {discovery.iot_type} on "
                f"{discovery.source_owner}.{discovery.source_table_name}"
            )
        if not discovery.columns:
            raise OffloadException(f"No columns discovered for {discovery.source_owner}.{discovery.source_table_name}")
        unsupported = self._frontend.unsupported_data_types(discovery.columns)
        if unsupported:
            joined = ", ".join(unsupported)
            raise OffloadException(
                f"Table {discovery.source_owner}.{discovery.source_table_name} contains "
                f"unsupported column data types: {joined}"
            )


def _extract_owner_and_table(options: OffloadOperationOptions) -> tuple[str, str]:
    """Extract source owner and table name from OffloadOperationOptions."""
    if options.owner and options.table_name:
        return str(options.owner), str(options.table_name)
    if options.owner_table and "." in options.owner_table:
        owner, table_name = options.owner_table.split(".", 1)
        return owner, table_name
    raise OffloadException("Source owner and table_name are required for discovery")

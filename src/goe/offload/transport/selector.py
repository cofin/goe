# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Transport method availability checks, validation, and AUTO selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from goe.offload.offload_constants import (
    BACKEND_DISTRO_GCP,
    DBTYPE_ORACLE,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
    OFFLOAD_TRANSPORT_AUTO,
    OFFLOAD_TRANSPORT_DUCKDB,
    OFFLOAD_TRANSPORT_GCP,
    OFFLOAD_TRANSPORT_GOE,
)
from goe.offload.offload_messages import VVERBOSE
from goe.offload.offload_transport_functions import (
    run_os_cmd,
    ssh_cmd_prefix,
)
from goe.offload.transport.constants import (
    DEFAULT_DUCKDB_MAX_BYTES,
    DEFAULT_QUERY_IMPORT_MAX_BYTES,
    OFFLOAD_TRANSPORT_GCP_METHODS,
    OFFLOAD_TRANSPORT_GOE_METHODS,
    OFFLOAD_TRANSPORT_METHOD_DUCKDB,
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_SPARK_GCLOUD_EXECUTABLE,
    VALID_OFFLOAD_TRANSPORT_METHODS,
)
from goe.offload.transport.duckdb_availability import is_duckdb_available
from goe.offload.transport.protocol import OffloadTransportException

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_table import OffloadSourceTableInterface

GCP_AUTO_TRANSPORT_METHODS = [
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_DUCKDB,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
]

SPARK_CLUSTER_FALLBACK_ORDER = [
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
]


def spark_submit_executable_exists(
    config: OrchestrationConfig,
    messages: OffloadMessages,
    executable_override: Any = None,
) -> bool:
    """Return True when the spark-submit or gcloud executable exists on the command host."""
    spark_submit_executable = executable_override or config.offload_transport_spark_submit_executable
    cmd = ["which", spark_submit_executable]
    cmd = (
        ssh_cmd_prefix(
            config.offload_transport_user,
            config.offload_transport_cmd_host,
        )
        + cmd
    )
    rc, _ = run_os_cmd(cmd, messages, config, optional=True, force=True, silent=True)
    return bool(rc == 0)


def is_spark_thrift_available(
    config: OrchestrationConfig,
    offload_source_table: OffloadSourceTableInterface | None,
    messages: OffloadMessages | None = None,
) -> bool:
    """Return True when Spark Thrift Server host and port are configured."""
    if not config.offload_transport_spark_thrift_host or not config.offload_transport_spark_thrift_port:
        if messages:
            messages.log(
                "OFFLOAD_TRANSPORT_SPARK_THRIFT_HOST and OFFLOAD_TRANSPORT_SPARK_THRIFT_PORT required for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
                detail=VVERBOSE,
            )
        return False
    return True


def is_livy_available(
    config: OrchestrationConfig,
    offload_source_table: OffloadSourceTableInterface | None,
    messages: OffloadMessages | None = None,
) -> bool:
    """Return True when Livy REST API URL is configured."""
    if not config.offload_transport_livy_api_url:
        if messages:
            messages.log(
                "OFFLOAD_TRANSPORT_LIVY_API_URL required for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
                detail=VVERBOSE,
            )
        return False
    return True


def is_spark_submit_available(
    config: OrchestrationConfig,
    offload_source_table: OffloadSourceTableInterface | None,
    messages: OffloadMessages | None = None,
    executable_override: Any = None,
) -> bool:
    """Return True when spark-submit host and executable are configured and present."""
    if not config.offload_transport_cmd_host:
        if messages:
            messages.log(
                "OFFLOAD_TRANSPORT_CMD_HOST required for transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
                detail=VVERBOSE,
            )
        return False
    if not config.offload_transport_spark_submit_executable:
        if messages:
            messages.log(
                "OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE required for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
                detail=VVERBOSE,
            )
        return False
    if messages and not spark_submit_executable_exists(config, messages, executable_override=executable_override):
        messages.log(
            "Spark submit executable required for transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
            detail=VVERBOSE,
        )
        return False
    return True


def is_spark_gcloud_available(
    config: OrchestrationConfig,
    offload_source_table: OffloadSourceTableInterface | None,
    messages: OffloadMessages | None = None,
) -> bool:
    """Return True when GCP backend distribution, command host, and gcloud binary are available."""
    if not config.offload_transport_cmd_host:
        if messages:
            messages.log(
                "OFFLOAD_TRANSPORT_CMD_HOST required for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
                detail=VVERBOSE,
            )
        return False
    if config.backend_distribution != BACKEND_DISTRO_GCP:
        if messages:
            messages.log(
                "BACKEND_DISTRIBUTION not valid for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
                detail=VVERBOSE,
            )
        return False
    if messages and not spark_submit_executable_exists(
        config,
        messages,
        executable_override=OFFLOAD_TRANSPORT_SPARK_GCLOUD_EXECUTABLE,
    ):
        messages.log(
            "gcloud executable required for transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
            detail=VVERBOSE,
        )
        return False
    return True


def is_spark_gcloud_dataproc_available(
    config: OrchestrationConfig,
    offload_source_table: OffloadSourceTableInterface | None,
    messages: OffloadMessages | None = None,
) -> bool:
    """Return True when Dataproc cluster and gcloud CLI are available."""
    return bool(
        config.google_dataproc_cluster and is_spark_gcloud_available(config, offload_source_table, messages=messages)
    )


def is_spark_gcloud_batches_available(
    config: OrchestrationConfig,
    offload_source_table: OffloadSourceTableInterface | None,
    messages: OffloadMessages | None = None,
) -> bool:
    """Return True when Dataproc Serverless Batches version and gcloud CLI are available."""
    return bool(
        config.google_dataproc_batches_version
        and is_spark_gcloud_available(config, offload_source_table, messages=messages)
    )


def is_query_import_available(
    offload_operation: Any,
    config: OrchestrationConfig,
    offload_source_table: OffloadSourceTableInterface | None = None,
    messages: OffloadMessages | None = None,
) -> bool:
    """Return True when Query Import supports the staging format and table size threshold."""
    if config.offload_staging_format not in [
        FILE_STORAGE_FORMAT_AVRO,
        FILE_STORAGE_FORMAT_PARQUET,
    ]:
        if messages:
            messages.log(
                "Staging file format %s not supported by transport method: %s"
                % (
                    config.offload_staging_format,
                    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
                ),
                detail=VVERBOSE,
            )
        return False

    if offload_source_table and offload_operation:
        small_table_threshold = getattr(
            offload_operation,
            "offload_transport_small_table_threshold",
            DEFAULT_QUERY_IMPORT_MAX_BYTES,
        )
        if small_table_threshold is not None and (offload_source_table.size_in_bytes or 0) > small_table_threshold:
            if messages:
                messages.log(
                    "Table size (%s) > %s (OFFLOAD_TRANSPORT_SMALL_TABLE_THRESHOLD) is not valid with transport method: %s"
                    % (
                        offload_source_table.size_in_bytes or 0,
                        small_table_threshold,
                        OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
                    ),
                    detail=VVERBOSE,
                )
            return False

    return True


def get_offload_transport_method_validation_fns(
    config: OrchestrationConfig,
    offload_operation: Any = None,
    offload_source_table: OffloadSourceTableInterface | None = None,
    messages: OffloadMessages | None = None,
) -> dict[str, Any]:
    """Return mapping of transport method constants to zero-arg availability callables."""
    return {
        OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT: lambda: is_spark_thrift_available(
            config, offload_source_table, messages=messages
        ),
        OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY: lambda: is_livy_available(config, offload_source_table, messages=messages),
        OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT: lambda: is_spark_submit_available(
            config, offload_source_table, messages=messages
        ),
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD: lambda: is_spark_gcloud_batches_available(
            config, offload_source_table, messages=messages
        ),
        OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD: lambda: is_spark_gcloud_dataproc_available(
            config, offload_source_table, messages=messages
        ),
        OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT: lambda: is_query_import_available(
            offload_operation,
            config,
            offload_source_table=offload_source_table,
            messages=messages,
        ),
        OFFLOAD_TRANSPORT_METHOD_DUCKDB: lambda: is_duckdb_available(
            offload_operation,
            config,
            offload_source_table=offload_source_table,
            messages=messages,
        ),
    }


def validate_offload_transport_method(
    offload_transport_method: str,
    config: OrchestrationConfig,
    offload_operation: Any = None,
    offload_source_table: OffloadSourceTableInterface | None = None,
    messages: OffloadMessages | None = None,
    exception_class: Any = OffloadTransportException,
) -> None:
    """Validate that a requested transport method is supported and compatible with config."""
    assert offload_transport_method
    assert exception_class

    if offload_transport_method not in VALID_OFFLOAD_TRANSPORT_METHODS:
        raise exception_class("Unsupported transport method: %s" % offload_transport_method)

    validation_fn = get_offload_transport_method_validation_fns(
        config, offload_operation, offload_source_table, messages
    )[offload_transport_method]

    if not validation_fn():
        raise exception_class("Transport method is incompatible with this offload: %s" % offload_transport_method)


class TransportSelector:
    """Deterministic selector for offload transport methods across AUTO, GOE, GCP, and DUCKDB."""

    @staticmethod
    def select_transport_method(
        estimated_bytes: int,
        *,
        explicit_method: str | None = None,
        query_import_max_bytes: int = DEFAULT_QUERY_IMPORT_MAX_BYTES,
        duckdb_max_bytes: int = DEFAULT_DUCKDB_MAX_BYTES,
        query_import_available: bool = True,
        duckdb_available: bool = True,
        available_spark_methods: tuple[str, ...] | list[str] = (OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,),
    ) -> str:
        """Select a transport method using byte-threshold AUTO rules or an explicit override."""
        if explicit_method:
            if explicit_method not in VALID_OFFLOAD_TRANSPORT_METHODS:
                raise OffloadTransportException(f"Unsupported transport method: {explicit_method}")
            return explicit_method

        if estimated_bytes <= query_import_max_bytes and query_import_available:
            return OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT

        if estimated_bytes <= duckdb_max_bytes and duckdb_available:
            return OFFLOAD_TRANSPORT_METHOD_DUCKDB

        for method in SPARK_CLUSTER_FALLBACK_ORDER:
            if method in available_spark_methods:
                return method

        raise OffloadTransportException("No valid transport methods found for offload transport: AUTO")

    @staticmethod
    def choose_offload_transport_method(
        offload_operation: Any,
        offload_source_table: OffloadSourceTableInterface,
        config: OrchestrationConfig,
        messages: OffloadMessages,
    ) -> str:
        """Select the data transport method based on configured rules and runtime availability."""
        assert config.offload_transport

        validation_fns = get_offload_transport_method_validation_fns(
            config, offload_operation, offload_source_table, messages
        )

        if config.db_type != DBTYPE_ORACLE:
            raise OffloadTransportException("Unsupported DB type: %s" % config.db_type)

        if offload_operation.offload_transport_method:
            explicit = offload_operation.offload_transport_method
            if explicit not in VALID_OFFLOAD_TRANSPORT_METHODS:
                raise OffloadTransportException("Unsupported transport method: %s" % explicit)
            rules = [explicit]
        elif config.offload_transport == OFFLOAD_TRANSPORT_AUTO and config.backend_distribution == BACKEND_DISTRO_GCP:
            rules = GCP_AUTO_TRANSPORT_METHODS
        elif config.offload_transport == OFFLOAD_TRANSPORT_AUTO:
            rules = OFFLOAD_TRANSPORT_GOE_METHODS + OFFLOAD_TRANSPORT_GCP_METHODS
        elif config.offload_transport == OFFLOAD_TRANSPORT_GOE:
            rules = OFFLOAD_TRANSPORT_GOE_METHODS
        elif config.offload_transport == OFFLOAD_TRANSPORT_GCP:
            rules = OFFLOAD_TRANSPORT_GCP_METHODS
        elif config.offload_transport == OFFLOAD_TRANSPORT_DUCKDB:
            rules = [OFFLOAD_TRANSPORT_METHOD_DUCKDB]
        else:
            raise OffloadTransportException("Unsupported offload transport: %s" % config.offload_transport)

        for rule in rules:
            if validation_fns[rule]():
                return rule

        raise OffloadTransportException(
            "No valid transport methods found for offload transport: %s" % config.offload_transport
        )


def choose_offload_transport_method(
    offload_operation: Any,
    offload_source_table: OffloadSourceTableInterface,
    config: OrchestrationConfig,
    messages: OffloadMessages,
) -> str:
    """Module-level entry point delegating to TransportSelector.choose_offload_transport_method."""
    return TransportSelector.choose_offload_transport_method(
        offload_operation,
        offload_source_table,
        config,
        messages,
    )


__all__ = [
    "GCP_AUTO_TRANSPORT_METHODS",
    "SPARK_CLUSTER_FALLBACK_ORDER",
    "TransportSelector",
    "choose_offload_transport_method",
    "get_offload_transport_method_validation_fns",
    "is_duckdb_available",
    "is_livy_available",
    "is_query_import_available",
    "is_spark_gcloud_available",
    "is_spark_gcloud_batches_available",
    "is_spark_gcloud_dataproc_available",
    "is_spark_submit_available",
    "is_spark_thrift_available",
    "spark_submit_executable_exists",
    "validate_offload_transport_method",
]

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Declarative adapter registry and lazy constructors for GOE frontends, backends, and transports."""

import logging
from collections.abc import Iterable
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from goe.exceptions import OffloadException
from goe.offload.offload_constants import (
    DBTYPE_BIGQUERY,
    DBTYPE_HIVE,
    DBTYPE_IMPALA,
    DBTYPE_MSSQL,
    DBTYPE_ORACLE,
    DBTYPE_SNOWFLAKE,
    DBTYPE_SPARK,
    DBTYPE_SYNAPSE,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.offload_messages import VVERBOSE
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
)
from goe.offload.transport.duckdb_constants import OFFLOAD_TRANSPORT_METHOD_DUCKDB
from goe.typing import FrozenBaseStruct
from goe.util.module_loader import ensure_module

if TYPE_CHECKING:
    from goe.offload.backend_api import BackendApiInterface
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_transport_rdbms_api import OffloadTransportRdbmsApiInterface
    from goe.offload.staging.staging_file import OffloadStagingFileInterface
    from goe.persistence.oracle.oracle_repository import OracleRepositoryService

__all__ = [
    "ADAPTER_REGISTRY",
    "AdapterEntry",
    "AdapterKind",
    "AdapterNotRegisteredError",
    "AdapterRegistry",
    "LazyTarget",
    "create_backend_api",
    "create_backend_table",
    "create_frontend_api",
    "create_query_import_encoder",
    "create_repository_client",
    "create_source_table",
    "create_staging_file",
    "create_transport",
    "create_transport_rdbms_api",
    "staging_file_key",
]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class AdapterKind(StrEnum):
    """Kinds of pluggable adapters that GOE resolves by key."""

    FRONTEND_API = "frontend_api"
    SOURCE_TABLE = "source_table"
    TRANSPORT_RDBMS_API = "transport_rdbms_api"
    TRANSPORT = "transport"
    BACKEND_API = "backend_api"
    BACKEND_TABLE = "backend_table"
    STAGING_FILE = "staging_file"
    QUERY_IMPORT_ENCODER = "query_import_encoder"
    REPOSITORY_CLIENT = "repository_client"


class LazyTarget(FrozenBaseStruct, frozen=True):
    """Import location of an adapter class, loaded on first use.

    Attributes:
        module: Dotted path of the module that defines the adapter class.
        attribute: Class name inside the module.
        extra: Optional goe-framework extra that installs third-party dependencies of the module.
    """

    module: str
    attribute: str
    extra: str | None = None

    @property
    def path(self) -> str:
        """Return the target as ``module:attribute``."""
        return f"{self.module}:{self.attribute}"

    def load(self) -> Any:
        """Import the module and return the adapter class."""
        return getattr(ensure_module(self.module, extra=self.extra), self.attribute)


class AdapterEntry(FrozenBaseStruct, frozen=True):
    """One registry row: an adapter kind, its lookup key, and its import target."""

    kind: AdapterKind
    key: str
    target: LazyTarget


class AdapterNotRegisteredError(OffloadException):
    """Raised when no adapter is registered for an adapter kind and key."""

    def __init__(self, kind: AdapterKind, key: str) -> None:
        super().__init__(f"No {kind.value} adapter registered for: {key}")
        self.kind = kind
        self.key = key


class AdapterRegistry:
    """Immutable table of adapter import targets keyed by adapter kind and key."""

    __slots__ = ("_entries", "_targets")

    def __init__(self, entries: Iterable[AdapterEntry]) -> None:
        targets: dict[tuple[AdapterKind, str], LazyTarget] = {}
        for entry in entries:
            if (entry.kind, entry.key) in targets:
                raise ValueError(f"Duplicate adapter registration: {entry.kind.value} {entry.key}")
            targets[(entry.kind, entry.key)] = entry.target
        self._entries = tuple(AdapterEntry(kind, key, target) for (kind, key), target in targets.items())
        self._targets = MappingProxyType(targets)

    def entries(self) -> tuple[AdapterEntry, ...]:
        """Return every registered entry in registration order."""
        return self._entries

    def keys(self, kind: AdapterKind) -> tuple[str, ...]:
        """Return the sorted keys registered for one adapter kind."""
        return tuple(sorted(key for entry_kind, key in self._targets if entry_kind is kind))

    def resolve_dry_run(self, kind: AdapterKind, key: str) -> LazyTarget:
        """Return the import target for kind and key without importing the adapter module."""
        target = self._targets.get((kind, key))
        if target is None:
            raise AdapterNotRegisteredError(kind, key)
        return target

    def resolve(self, kind: AdapterKind, key: str) -> Any:
        """Return the adapter class for kind and key, importing its module on first use."""
        return self.resolve_dry_run(kind, key).load()


def staging_file_key(staging_file_format: str, target: str) -> str:
    """Build the composite registry key for a staging file format and backend target."""
    return f"{staging_file_format}:{target}"


ADAPTER_REGISTRY = AdapterRegistry(
    (
        AdapterEntry(
            AdapterKind.FRONTEND_API,
            DBTYPE_ORACLE,
            LazyTarget("goe.offload.oracle.oracle_frontend_api", "OracleFrontendApi"),
        ),
        AdapterEntry(
            AdapterKind.FRONTEND_API,
            DBTYPE_MSSQL,
            LazyTarget("goe.offload.microsoft.mssql_frontend_api", "MSSQLFrontendApi", "sql_server"),
        ),
        AdapterEntry(
            AdapterKind.SOURCE_TABLE,
            DBTYPE_ORACLE,
            LazyTarget("goe.offload.oracle.oracle_offload_source_table", "OracleSourceTable"),
        ),
        AdapterEntry(
            AdapterKind.SOURCE_TABLE,
            DBTYPE_MSSQL,
            LazyTarget("goe.offload.microsoft.mssql_offload_source_table", "MSSQLSourceTable", "sql_server"),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT_RDBMS_API,
            DBTYPE_ORACLE,
            LazyTarget("goe.offload.oracle.oracle_offload_transport_rdbms_api", "OffloadTransportOracleApi"),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT_RDBMS_API,
            DBTYPE_MSSQL,
            LazyTarget(
                "goe.offload.microsoft.mssql_offload_transport_rdbms_api",
                "OffloadTransportMSSQLApi",
                "sql_server",
            ),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT,
            OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
            LazyTarget("goe.offload.transport.query_import", "OffloadTransportQueryImport"),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT,
            OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
            LazyTarget("goe.offload.transport.spark_thrift", "OffloadTransportSparkThrift"),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT,
            OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
            LazyTarget("goe.offload.transport.spark_submit", "OffloadTransportSparkSubmit"),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT,
            OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
            LazyTarget("goe.offload.spark.dataproc_offload_transport", "OffloadTransportSparkDataprocGcloud"),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT,
            OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
            LazyTarget("goe.offload.spark.dataproc_offload_transport", "OffloadTransportSparkBatchesGcloud"),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT,
            OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
            LazyTarget("goe.offload.spark.livy_offload_transport", "OffloadTransportSparkLivy"),
        ),
        AdapterEntry(
            AdapterKind.TRANSPORT,
            OFFLOAD_TRANSPORT_METHOD_DUCKDB,
            LazyTarget("goe.offload.transport.duckdb_transport", "OffloadTransportDuckDB"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_API,
            DBTYPE_BIGQUERY,
            LazyTarget("goe.offload.bigquery.bigquery_backend_api", "BackendBigQueryApi"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_API,
            DBTYPE_HIVE,
            LazyTarget("goe.offload.hadoop.hive_backend_api", "BackendHiveApi", "hadoop"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_API,
            DBTYPE_IMPALA,
            LazyTarget("goe.offload.hadoop.impala_backend_api", "BackendImpalaApi", "hadoop"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_API,
            DBTYPE_SPARK,
            LazyTarget("goe.offload.spark.spark_thrift_backend_api", "BackendSparkThriftApi", "hadoop"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_API,
            DBTYPE_SNOWFLAKE,
            LazyTarget("goe.offload.snowflake.snowflake_backend_api", "BackendSnowflakeApi", "snowflake"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_API,
            DBTYPE_SYNAPSE,
            LazyTarget("goe.offload.microsoft.synapse_backend_api", "BackendSynapseApi", "synapse"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_TABLE,
            DBTYPE_BIGQUERY,
            LazyTarget("goe.offload.bigquery.bigquery_backend_table", "BackendBigQueryTable"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_TABLE,
            DBTYPE_HIVE,
            LazyTarget("goe.offload.hadoop.hive_backend_table", "BackendHiveTable", "hadoop"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_TABLE,
            DBTYPE_IMPALA,
            LazyTarget("goe.offload.hadoop.impala_backend_table", "BackendImpalaTable", "hadoop"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_TABLE,
            DBTYPE_SNOWFLAKE,
            LazyTarget("goe.offload.snowflake.snowflake_backend_table", "BackendSnowflakeTable", "snowflake"),
        ),
        AdapterEntry(
            AdapterKind.BACKEND_TABLE,
            DBTYPE_SYNAPSE,
            LazyTarget("goe.offload.microsoft.synapse_backend_table", "BackendSynapseTable", "synapse"),
        ),
        AdapterEntry(
            AdapterKind.STAGING_FILE,
            staging_file_key(FILE_STORAGE_FORMAT_AVRO, DBTYPE_IMPALA),
            LazyTarget("goe.offload.staging.avro.avro_staging_file", "OffloadStagingAvroImpalaFile"),
        ),
        AdapterEntry(
            AdapterKind.STAGING_FILE,
            staging_file_key(FILE_STORAGE_FORMAT_AVRO, DBTYPE_HIVE),
            LazyTarget("goe.offload.staging.avro.avro_staging_file", "OffloadStagingAvroFile"),
        ),
        AdapterEntry(
            AdapterKind.STAGING_FILE,
            staging_file_key(FILE_STORAGE_FORMAT_AVRO, DBTYPE_BIGQUERY),
            LazyTarget("goe.offload.staging.avro.avro_staging_file", "OffloadStagingAvroFile"),
        ),
        AdapterEntry(
            AdapterKind.STAGING_FILE,
            staging_file_key(FILE_STORAGE_FORMAT_AVRO, DBTYPE_SNOWFLAKE),
            LazyTarget("goe.offload.staging.avro.avro_staging_file", "OffloadStagingAvroFile"),
        ),
        AdapterEntry(
            AdapterKind.STAGING_FILE,
            staging_file_key(FILE_STORAGE_FORMAT_PARQUET, DBTYPE_BIGQUERY),
            LazyTarget("goe.offload.staging.parquet.parquet_staging_file", "OffloadStagingParquetFile"),
        ),
        AdapterEntry(
            AdapterKind.STAGING_FILE,
            staging_file_key(FILE_STORAGE_FORMAT_PARQUET, DBTYPE_SNOWFLAKE),
            LazyTarget("goe.offload.staging.parquet.parquet_staging_file", "OffloadStagingParquetFile"),
        ),
        AdapterEntry(
            AdapterKind.STAGING_FILE,
            staging_file_key(FILE_STORAGE_FORMAT_PARQUET, DBTYPE_SYNAPSE),
            LazyTarget("goe.offload.staging.parquet.parquet_staging_file", "OffloadStagingParquetFile"),
        ),
        AdapterEntry(
            AdapterKind.QUERY_IMPORT_ENCODER,
            FILE_STORAGE_FORMAT_AVRO,
            LazyTarget("goe.offload.staging.avro.avro_encoder", "AvroEncoder"),
        ),
        AdapterEntry(
            AdapterKind.QUERY_IMPORT_ENCODER,
            FILE_STORAGE_FORMAT_PARQUET,
            LazyTarget("goe.offload.staging.parquet.parquet_encoder", "ParquetEncoder"),
        ),
        AdapterEntry(
            AdapterKind.REPOSITORY_CLIENT,
            DBTYPE_ORACLE,
            LazyTarget("goe.persistence.oracle.oracle_repository", "OracleRepositoryService"),
        ),
    )
)


def create_frontend_api(
    frontend_type: str,
    connection_options: Any,
    messages: "OffloadMessages | None",
    conn_user_override: str | None = None,
    existing_connection: Any = None,
    dry_run: bool | None = None,
    do_not_connect: bool = False,
    trace_action: str | None = None,
) -> Any:
    """Construct a frontend database API instance for frontend_type."""
    assert frontend_type
    resolved_dry_run = _execute_dry_run(connection_options) if dry_run is None else dry_run
    frontend_cls = ADAPTER_REGISTRY.resolve(AdapterKind.FRONTEND_API, frontend_type)
    return frontend_cls(
        connection_options,
        frontend_type,
        messages,
        conn_user_override=conn_user_override,
        existing_connection=existing_connection,
        dry_run=resolved_dry_run,
        do_not_connect=do_not_connect,
        trace_action=trace_action,
    )


def create_source_table(
    schema_name: str,
    table_name: str,
    connection_options: Any,
    messages: "OffloadMessages | None",
    dry_run: bool = False,
    offload_by_subpartition: bool = False,
    conn: Any = None,
    do_not_connect: bool = False,
) -> Any:
    """Construct a source table metadata adapter for connection_options.db_type."""
    logger.info("OffloadSourceTable constructing for %s", connection_options.db_type)
    source_cls = ADAPTER_REGISTRY.resolve(AdapterKind.SOURCE_TABLE, connection_options.db_type)
    kwargs: dict[str, Any] = {
        "dry_run": dry_run,
        "do_not_connect": do_not_connect,
    }
    if conn is not None:
        kwargs["conn"] = conn
    rdbms_table = source_cls(
        schema_name,
        table_name,
        connection_options,
        messages,
        **kwargs,
    )
    if offload_by_subpartition:
        rdbms_table.enable_offload_by_subpartition()
    return rdbms_table


def create_transport_rdbms_api(
    rdbms_owner: str,
    rdbms_table_name: str,
    offload_options: Any,
    messages: "OffloadMessages",
    dry_run: bool = False,
) -> "OffloadTransportRdbmsApiInterface":
    """Construct a transport RDBMS API adapter for offload_options.db_type."""
    api_cls = ADAPTER_REGISTRY.resolve(AdapterKind.TRANSPORT_RDBMS_API, offload_options.db_type)
    return cast(
        "OffloadTransportRdbmsApiInterface",
        api_cls(
            rdbms_owner,
            rdbms_table_name,
            offload_options,
            messages,
            dry_run=dry_run,
        ),
    )


def create_transport(
    offload_transport_method: str,
    offload_source_table: Any,
    offload_target_table: Any,
    offload_operation: Any,
    offload_options: Any,
    messages: "OffloadMessages",
    dfs_client: Any,
) -> Any:
    """Construct a data transport adapter for offload_transport_method."""
    transport_cls = ADAPTER_REGISTRY.resolve(AdapterKind.TRANSPORT, offload_transport_method)
    cls_name = (
        getattr(transport_cls, "__name__", None)
        or ADAPTER_REGISTRY.resolve_dry_run(AdapterKind.TRANSPORT, offload_transport_method).attribute
    )
    log_fn: Any = messages.log
    log_fn(f"Data transport method: {cls_name}", detail=VVERBOSE)
    return transport_cls(
        offload_source_table,
        offload_target_table,
        offload_operation,
        offload_options,
        messages,
        dfs_client,
    )


def create_backend_api(
    backend_type: str,
    connection_options: Any,
    messages: "OffloadMessages",
    dry_run: bool | None = None,
    no_caching: bool = False,
    do_not_connect: bool = False,
) -> "BackendApiInterface":
    """Construct a backend database API adapter for backend_type."""
    resolved_dry_run = _backend_dry_run(connection_options, do_not_connect) if dry_run is None else dry_run
    backend_cls = ADAPTER_REGISTRY.resolve(AdapterKind.BACKEND_API, backend_type)
    return cast(
        "BackendApiInterface",
        backend_cls(
            connection_options,
            backend_type,
            messages,
            dry_run=resolved_dry_run,
            no_caching=no_caching,
            do_not_connect=do_not_connect,
        ),
    )


def create_backend_table(
    db_name: str,
    table_name: str,
    backend_type: str,
    orchestration_options: Any,
    messages: "OffloadMessages",
    orchestration_operation: Any = None,
    hybrid_metadata: Any = None,
    dry_run: bool | None = None,
    frontend_owner_override: str | None = None,
    frontend_name_override: str | None = None,
    existing_backend_api: Any = None,
    do_not_connect: bool = False,
) -> "BackendTableInterface":
    """Construct a backend table adapter for backend_type."""
    resolved_dry_run = (
        _backend_table_dry_run(orchestration_options, orchestration_operation, do_not_connect)
        if dry_run is None
        else dry_run
    )
    resolved_metadata = hybrid_metadata or _hybrid_metadata_for(
        orchestration_options,
        messages,
        orchestration_operation,
        frontend_owner_override,
        frontend_name_override,
    )
    table_cls = ADAPTER_REGISTRY.resolve(AdapterKind.BACKEND_TABLE, backend_type)
    return cast(
        "BackendTableInterface",
        table_cls(
            db_name,
            table_name,
            backend_type,
            orchestration_options,
            messages,
            orchestration_operation=orchestration_operation,
            hybrid_metadata=resolved_metadata,
            dry_run=resolved_dry_run,
            existing_backend_api=existing_backend_api,
            do_not_connect=do_not_connect,
        ),
    )


def create_staging_file(
    load_db_name: str,
    table_name: str,
    staging_file_format: str,
    canonical_columns: list[Any],
    orchestration_options: Any,
    binary_data_as_base64: bool,
    messages: "OffloadMessages",
    dry_run: bool = False,
) -> "OffloadStagingFileInterface":
    """Construct a staging file adapter for staging_file_format and orchestration_options.target."""
    staging_cls = ADAPTER_REGISTRY.resolve(
        AdapterKind.STAGING_FILE,
        staging_file_key(staging_file_format, orchestration_options.target),
    )
    return cast(
        "OffloadStagingFileInterface",
        staging_cls(
            load_db_name,
            table_name,
            staging_file_format,
            canonical_columns,
            binary_data_as_base64,
            messages,
            dry_run=dry_run,
        ),
    )


def create_query_import_encoder(
    staging_file: Any,
    messages: "OffloadMessages",
    compression: bool = False,
    base64_columns: Any = None,
) -> Any:
    """Construct a Query Import file encoder for staging_file.file_format."""
    encoder_cls = ADAPTER_REGISTRY.resolve(AdapterKind.QUERY_IMPORT_ENCODER, staging_file.file_format)
    schema = staging_file.get_file_schema_json(as_string=staging_file.file_format == FILE_STORAGE_FORMAT_AVRO)
    return encoder_cls(
        schema,
        messages,
        compression=compression,
        base64_columns=base64_columns,
    )


def create_repository_client(
    connection_options: Any,
    messages: "OffloadMessages",
    dry_run: bool | None = None,
    trace_action: str | None = None,
) -> "OracleRepositoryService":
    """Construct a repository persistence client for connection_options.db_type."""
    resolved_dry_run = _execute_dry_run(connection_options) if dry_run is None else dry_run
    repo_cls = ADAPTER_REGISTRY.resolve(AdapterKind.REPOSITORY_CLIENT, connection_options.db_type)
    return cast(
        "OracleRepositoryService",
        repo_cls(
            connection_options,
            messages,
            dry_run=resolved_dry_run,
            trace_action=trace_action,
        ),
    )


def _execute_dry_run(options: Any) -> bool:
    """Derive dry_run from options.execute when present."""
    if hasattr(options, "execute"):
        return bool(not options.execute)
    return False


def _backend_dry_run(options: Any, do_not_connect: bool) -> bool:
    """Derive backend API dry_run from options.execute or do_not_connect."""
    if hasattr(options, "execute"):
        return bool(not options.execute)
    if do_not_connect:
        return True
    return False


def _backend_table_dry_run(options: Any, operation: Any, do_not_connect: bool) -> bool:
    """Derive backend table dry_run from operation.execute, options.execute, or do_not_connect."""
    if operation:
        return bool(not operation.execute)
    if hasattr(options, "execute"):
        return bool(not options.execute)
    if do_not_connect:
        return True
    return False


def _hybrid_metadata_for(
    options: Any,
    messages: Any,
    operation: Any,
    owner: str | None,
    name: str | None,
) -> Any:
    """Resolve hybrid metadata from operation or frontend owner/table overrides."""
    if operation:
        return operation.get_hybrid_metadata()
    if owner and name:
        client = create_repository_client(options, messages)
        return client.get_offload_metadata(owner, name)
    return None

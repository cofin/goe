# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Transport method selection, validation, and factory instantiation."""

from typing import TYPE_CHECKING, Any

from goe.offload.offload_constants import (
    BACKEND_DISTRO_GCP,
    DBTYPE_MSSQL,
    DBTYPE_ORACLE,
    DBTYPE_TERADATA,
    OFFLOAD_TRANSPORT_AUTO,
    OFFLOAD_TRANSPORT_GCP,
    OFFLOAD_TRANSPORT_GOE,
    OFFLOAD_TRANSPORT_SQOOP,
)
from goe.offload.offload_messages import VVERBOSE
from goe.offload.transport.availability import (
    is_livy_available,
    is_query_import_available,
    is_spark_gcloud_batches_available,
    is_spark_gcloud_dataproc_available,
    is_spark_submit_available,
    is_spark_thrift_available,
    is_sqoop_available,
    is_sqoop_by_query_available,
)
from goe.offload.transport.base import (
    OffloadTransportException,
)
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_GCP_METHODS,
    OFFLOAD_TRANSPORT_GOE_METHODS,
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_METHOD_SQOOP,
    OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY,
    OFFLOAD_TRANSPORT_SQOOP_METHODS,
    VALID_OFFLOAD_TRANSPORT_METHODS,
)
from goe.offload.transport.query_import import OffloadTransportQueryImport
from goe.offload.transport.spark_submit import (
    OffloadTransportSparkSubmit,
    OffloadTransportSparkSubmitCanary,
)
from goe.offload.transport.spark_thrift import (
    OffloadTransportSparkThrift,
    OffloadTransportSparkThriftCanary,
)

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_table import OffloadSourceTableInterface

GCP_AUTO_TRANSPORT_METHODS = [
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
]


def get_offload_transport_method_validation_fns(
    config: "OrchestrationConfig",
    offload_operation: Any = None,
    offload_source_table: "OffloadSourceTableInterface | None" = None,
    messages: "OffloadMessages | None" = None,
) -> dict[str, Any]:
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
        OFFLOAD_TRANSPORT_METHOD_SQOOP: lambda: is_sqoop_available(
            offload_operation,
            config,
            offload_source_table=offload_source_table,
            messages=messages,
        ),
        OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY: lambda: is_sqoop_by_query_available(config, messages=messages),
    }


def validate_offload_transport_method(
    offload_transport_method: str,
    config: "OrchestrationConfig",
    offload_operation: Any = None,
    offload_source_table: "OffloadSourceTableInterface | None" = None,
    messages: "OffloadMessages | None" = None,
    exception_class: Any = OffloadTransportException,
) -> None:
    """If a specific method is requested then we can do certain config checks.
    This is not a health check, just confirming we have the config we need.
    Query Import and Sqoop methods can only be validated if optional operation config is passed in.
    """
    assert offload_transport_method
    assert exception_class

    if offload_transport_method not in VALID_OFFLOAD_TRANSPORT_METHODS:
        raise exception_class("Unsupported transport method: %s" % offload_transport_method)

    validation_fn = get_offload_transport_method_validation_fns(
        config, offload_operation, offload_source_table, messages
    )[offload_transport_method]

    if not validation_fn():
        raise exception_class("Transport method is incompatible with this offload: %s" % offload_transport_method)


def choose_offload_transport_method(
    offload_operation: Any,
    offload_source_table: "OffloadSourceTableInterface",
    config: "OrchestrationConfig",
    messages: "OffloadMessages",
) -> str:
    """Select the data transport method based on a series of rules:
    AUTO: On GCP backends pick QUERY_IMPORT, SPARK_DATAPROC_GCLOUD, SPARK_BATCHES_GCLOUD, SPARK_SUBMIT, SPARK_THRIFT, SPARK_LIVY (Sqoop is never valid there); otherwise work through GOE rules, then SQOOP rules, then GCP rules.
    GOE:
        Pick a method using the following priorities: SPARK_THRIFT, QUERY_IMPORT, SPARK_LIVY, SPARK_SUBMIT
    GCP:
        Pick a method using the following priorities: SPARK_DATAPROC_GCLOUD, SPARK_BATCHES_GCLOUD
    SQOOP:
        Pick a method using the following priorities: SQOOP, SQOOP_BY_QUERY

    An override was supplied if we get to here then no rule was accepted
    """
    assert config.offload_transport

    validation_fns = get_offload_transport_method_validation_fns(
        config, offload_operation, offload_source_table, messages
    )

    if config.db_type in [DBTYPE_ORACLE, DBTYPE_TERADATA]:
        if offload_operation.offload_transport_method:
            rules = [offload_operation.offload_transport_method]
        elif config.offload_transport == OFFLOAD_TRANSPORT_AUTO and config.backend_distribution == BACKEND_DISTRO_GCP:
            rules = GCP_AUTO_TRANSPORT_METHODS
        elif config.offload_transport == OFFLOAD_TRANSPORT_AUTO:
            rules = OFFLOAD_TRANSPORT_GOE_METHODS + OFFLOAD_TRANSPORT_SQOOP_METHODS + OFFLOAD_TRANSPORT_GCP_METHODS
        elif config.offload_transport == OFFLOAD_TRANSPORT_GOE:
            rules = OFFLOAD_TRANSPORT_GOE_METHODS
        elif config.offload_transport == OFFLOAD_TRANSPORT_SQOOP:
            rules = OFFLOAD_TRANSPORT_SQOOP_METHODS
        elif config.offload_transport == OFFLOAD_TRANSPORT_GCP:
            rules = OFFLOAD_TRANSPORT_GCP_METHODS

        for rule in rules:
            if validation_fns[rule]():
                return rule

        raise OffloadTransportException(
            "No valid transport methods found for offload transport: %s" % config.offload_transport
        )
    if config.db_type == DBTYPE_MSSQL:
        return OFFLOAD_TRANSPORT_METHOD_SQOOP
    raise OffloadTransportException("Unsupported DB type: %s" % config.db_type)


def offload_transport_factory(
    offload_transport_method,
    offload_source_table,
    offload_target_table,
    offload_operation,
    offload_options,
    messages,
    dfs_client,
):
    """Constructs and returns an appropriate data transport object based on user inputs and RDBMS table.

    Dataproc, Livy, and Sqoop classes are imported inside this function because their modules import
    goe.offload.offload_transport, which re-exports this module.
    """
    if offload_transport_method == OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT:
        messages.log("Data transport method: OffloadTransportQueryImport", detail=VVERBOSE)
        return OffloadTransportQueryImport(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
    if offload_transport_method == OFFLOAD_TRANSPORT_METHOD_SQOOP:
        from goe.offload.hadoop.sqoop_offload_transport import (
            OffloadTransportStandardSqoop,
        )

        messages.log("Data transport method: OffloadTransportStandardSqoop", detail=VVERBOSE)
        return OffloadTransportStandardSqoop(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
    if offload_transport_method == OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY:
        from goe.offload.hadoop.sqoop_offload_transport import (
            OffloadTransportSqoopByQuery,
        )

        messages.log("Data transport method: OffloadTransportSqoopByQuery", detail=VVERBOSE)
        return OffloadTransportSqoopByQuery(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
    if offload_transport_method == OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT:
        messages.log("Data transport method: OffloadTransportSparkThrift", detail=VVERBOSE)
        return OffloadTransportSparkThrift(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
    if offload_transport_method == OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT:
        messages.log("Data transport method: OffloadTransportSparkSubmit", detail=VVERBOSE)
        return OffloadTransportSparkSubmit(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
    if offload_transport_method == OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD:
        from goe.offload.spark.dataproc_offload_transport import (
            OffloadTransportSparkDataprocGcloud,
        )

        messages.log(
            "Data transport method: OffloadTransportSparkDataprocGcloud",
            detail=VVERBOSE,
        )
        return OffloadTransportSparkDataprocGcloud(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
    if offload_transport_method == OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD:
        from goe.offload.spark.dataproc_offload_transport import (
            OffloadTransportSparkBatchesGcloud,
        )

        messages.log("Data transport method: OffloadTransportSparkBatchesGcloud", detail=VVERBOSE)
        return OffloadTransportSparkBatchesGcloud(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
    if offload_transport_method == OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY:
        from goe.offload.spark.livy_offload_transport import OffloadTransportSparkLivy

        messages.log("Data transport method: OffloadTransportSparkLivy", detail=VVERBOSE)
        return OffloadTransportSparkLivy(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
    raise NotImplementedError("Offload transport method not implemented: %s" % offload_transport_method)


def spark_thrift_jdbc_connectivity_checker(offload_options, messages):
    """Connect needs a cut down client to simply check RDBMS connectivity from Spark
    back to the source RDBMS is correctly configured
    """
    messages.log("Invoking OffloadTransportSparkThriftCanary", detail=VVERBOSE)
    return OffloadTransportSparkThriftCanary(offload_options, messages)


def spark_submit_jdbc_connectivity_checker(offload_options, messages):
    """Connect needs a cut down client to simply check RDBMS connectivity from Spark
    back to the source RDBMS is correctly configured
    """
    messages.log("Invoking OffloadTransportSparkSubmitCanary", detail=VVERBOSE)
    return OffloadTransportSparkSubmitCanary(offload_options, messages)


def spark_livy_jdbc_connectivity_checker(offload_options, messages):
    """Connect needs a cut down client to simply check RDBMS connectivity from Spark
    back to the source RDBMS is correctly configured
    """
    from goe.offload.spark.livy_offload_transport import OffloadTransportSparkLivyCanary

    messages.log("Invoking OffloadTransportSparkLivyCanary", detail=VVERBOSE)
    return OffloadTransportSparkLivyCanary(offload_options, messages)


def spark_dataproc_jdbc_connectivity_checker(offload_options, messages):
    """Connect needs a cut down client to simply check RDBMS connectivity from Managed Spark
    back to the source RDBMS is correctly configured
    """
    from goe.offload.spark.dataproc_offload_transport import (
        OffloadTransportSparkDataprocGcloudCanary,
    )

    messages.log("Invoking OffloadTransportSparkDataprocGcloudCanary", detail=VVERBOSE)
    return OffloadTransportSparkDataprocGcloudCanary(offload_options, messages)


def spark_dataproc_batches_jdbc_connectivity_checker(offload_options, messages):
    """Connect needs a cut down client to simply check RDBMS connectivity from Managed
    Spark serverless back to the source RDBMS is correctly configured
    """
    from goe.offload.spark.dataproc_offload_transport import (
        OffloadTransportSparkBatchesGcloudCanary,
    )

    messages.log("Invoking OffloadTransportSparkBatchesGcloudCanary", detail=VVERBOSE)
    return OffloadTransportSparkBatchesGcloudCanary(offload_options, messages)


def sqoop_jdbc_connectivity_checker(offload_options, messages):
    """Connect needs a cut down client to simply check RDBMS connectivity from Sqoop
    back to the source RDBMS is correctly configured
    """
    from goe.offload.hadoop.sqoop_offload_transport import OffloadTransportSqoopCanary

    messages.log("Invoking OffloadTransportSqoopCanary", detail=VVERBOSE)
    return OffloadTransportSqoopCanary(offload_options, messages)

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Transport method selection, validation, and factory instantiation."""

from typing import TYPE_CHECKING, Any

from goe.offload.offload_constants import (
    BACKEND_DISTRO_GCP,
    DBTYPE_ORACLE,
    OFFLOAD_TRANSPORT_AUTO,
    OFFLOAD_TRANSPORT_DUCKDB,
    OFFLOAD_TRANSPORT_GCP,
    OFFLOAD_TRANSPORT_GOE,
)
from goe.offload.offload_messages import VVERBOSE
from goe.offload.transport.availability import (
    is_livy_available,
    is_query_import_available,
    is_spark_gcloud_batches_available,
    is_spark_gcloud_dataproc_available,
    is_spark_submit_available,
    is_spark_thrift_available,
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
    VALID_OFFLOAD_TRANSPORT_METHODS,
)
from goe.offload.transport.duckdb_availability import is_duckdb_available
from goe.offload.transport.duckdb_constants import OFFLOAD_TRANSPORT_METHOD_DUCKDB
from goe.offload.transport.spark_submit import OffloadTransportSparkSubmitCanary
from goe.offload.transport.spark_thrift import OffloadTransportSparkThriftCanary

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
        OFFLOAD_TRANSPORT_METHOD_DUCKDB: lambda: is_duckdb_available(
            offload_operation,
            config,
            offload_source_table=offload_source_table,
            messages=messages,
        ),
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
    Query Import can only be validated if optional operation config is passed in.
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
    AUTO: On GCP backends pick QUERY_IMPORT, SPARK_DATAPROC_GCLOUD, SPARK_BATCHES_GCLOUD, SPARK_SUBMIT, SPARK_THRIFT, SPARK_LIVY; otherwise work through GOE rules, then GCP rules.
    GOE:
        Pick a method using the following priorities: SPARK_THRIFT, QUERY_IMPORT, SPARK_LIVY, SPARK_SUBMIT
    GCP:
        Pick a method using the following priorities: SPARK_DATAPROC_GCLOUD, SPARK_BATCHES_GCLOUD
    DUCKDB:
        Opt-in only: DUCKDB (never chosen by AUTO)

    An override was supplied if we get to here then no rule was accepted
    """
    assert config.offload_transport

    validation_fns = get_offload_transport_method_validation_fns(
        config, offload_operation, offload_source_table, messages
    )

    if config.db_type == DBTYPE_ORACLE:
        if offload_operation.offload_transport_method:
            rules = [offload_operation.offload_transport_method]
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

        for rule in rules:
            if validation_fns[rule]():
                return rule

        raise OffloadTransportException(
            "No valid transport methods found for offload transport: %s" % config.offload_transport
        )
    raise OffloadTransportException("Unsupported DB type: %s" % config.db_type)


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

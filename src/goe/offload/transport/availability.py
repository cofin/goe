# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Transport availability predicates for Spark, Dataproc, Livy, Query Import, and Sqoop."""

from typing import TYPE_CHECKING

from goe.offload.offload_constants import (
    BACKEND_DISTRO_GCP,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
    HADOOP_BASED_BACKEND_DISTRIBUTIONS,
)
from goe.offload.offload_messages import VVERBOSE
from goe.offload.offload_transport_functions import (
    run_os_cmd,
    ssh_cmd_prefix,
)
from goe.offload.oracle.oracle_column import (
    ORACLE_TYPE_TIMESTAMP_TZ,
    ORACLE_TYPE_XMLTYPE,
)
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_METHOD_SQOOP,
    OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY,
    OFFLOAD_TRANSPORT_SPARK_GCLOUD_EXECUTABLE,
)

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_table import OffloadSourceTableInterface


def spark_submit_executable_exists(
    config: "OrchestrationConfig", messages: "OffloadMessages", executable_override=None
):
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
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface",
    messages: "OffloadMessages" = None,
):
    """If messages is passed in then we'll log any reason for a False return"""
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
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface",
    messages: "OffloadMessages" = None,
):
    """If messages is passed in then we'll log any reason for a False return"""
    if not config.offload_transport_livy_api_url:
        (
            messages.log(
                "OFFLOAD_TRANSPORT_LIVY_API_URL required for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
                detail=VVERBOSE,
            )
            if messages
            else None
        )
        return False
    return True


def is_spark_submit_available(
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface",
    messages: "OffloadMessages" = None,
    executable_override=None,
):
    """If messages is passed in then we'll log any reason for a False return
    If messages is not passed in then we can't yet run OS cmds, hence no spark_submit_executable_exists()
    """
    if not config.offload_transport_cmd_host:
        (
            messages.log(
                "OFFLOAD_TRANSPORT_CMD_HOST required for transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
                detail=VVERBOSE,
            )
            if messages
            else None
        )
        return False
    if not config.offload_transport_spark_submit_executable:
        (
            messages.log(
                "OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE required for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
                detail=VVERBOSE,
            )
            if messages
            else None
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
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface",
    messages: "OffloadMessages" = None,
):
    """If messages is passed in then we'll log any reason for a False return
    If messages is not passed in then we can't yet run OS cmds, hence no spark_submit_executable_exists()
    """
    if not config.offload_transport_cmd_host:
        (
            messages.log(
                "OFFLOAD_TRANSPORT_CMD_HOST required for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
                detail=VVERBOSE,
            )
            if messages
            else None
        )
        return False
    if config.backend_distribution != BACKEND_DISTRO_GCP:
        (
            messages.log(
                "BACKEND_DISTRIBUTION not valid for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
                detail=VVERBOSE,
            )
            if messages
            else None
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
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface",
    messages: "OffloadMessages" = None,
):
    return bool(
        config.google_dataproc_cluster and is_spark_gcloud_available(config, offload_source_table, messages=messages)
    )


def is_spark_gcloud_batches_available(
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface",
    messages: "OffloadMessages" = None,
):
    return bool(
        config.google_dataproc_batches_version
        and is_spark_gcloud_available(config, offload_source_table, messages=messages)
    )


def is_query_import_available(
    offload_operation,
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface" = None,
    messages: "OffloadMessages" = None,
):
    """If messages is passed in then we'll log any reason for a False return
    Query Import can only be validated if operational config is passed in. Without that we just assume True
    """

    def log(msg, messages):
        if messages:
            messages.log(msg, detail=VVERBOSE)

    if config.offload_staging_format not in [
        FILE_STORAGE_FORMAT_AVRO,
        FILE_STORAGE_FORMAT_PARQUET,
    ]:
        log(
            "Staging file format %s not supported by transport method: %s"
            % (
                config.offload_staging_format,
                OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
            ),
            messages,
        )
        return False

    if offload_source_table:
        if (
            offload_operation
            and (offload_source_table.size_in_bytes or 0) > offload_operation.offload_transport_small_table_threshold
        ):
            log(
                "Table size (%s) > %s (OFFLOAD_TRANSPORT_SMALL_TABLE_THRESHOLD) is not valid with transport method: %s"
                % (
                    offload_source_table.size_in_bytes or 0,
                    offload_operation.offload_transport_small_table_threshold,
                    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
                ),
                messages,
            )
            return False

    return True


def is_sqoop_available(
    offload_operation,
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface" = None,
    messages: "OffloadMessages" = None,
):
    """If messages is passed in then we'll log any reason for a False return
    Sqoop can only be validated if operational config is passed in. Without that we just assume True
    """
    if config.backend_distribution and config.backend_distribution not in HADOOP_BASED_BACKEND_DISTRIBUTIONS:
        if messages:
            messages.log(
                "Transport method only valid on Hadoop systems: %s/%s"
                % (
                    OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY,
                    config.backend_distribution,
                ),
                detail=VVERBOSE,
            )
        return False
    if not config.offload_transport_cmd_host:
        if messages:
            messages.log(
                "OFFLOAD_TRANSPORT_CMD_HOST required for transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SQOOP,
                detail=VVERBOSE,
            )
        return False
    if offload_operation and offload_operation.offload_by_subpartition:
        if messages:
            messages.log(
                "Subpartition level offloads are not valid with transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SQOOP,
                detail=VVERBOSE,
            )
        return False
    if offload_operation and offload_operation.column_transformations:
        if messages:
            messages.log(
                "Column transformations are not valid with transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SQOOP,
                detail=VVERBOSE,
            )
        return False
    if offload_operation and offload_operation.offload_predicate:
        if messages:
            messages.log(
                "Predicate offloads are not valid with transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SQOOP,
                detail=VVERBOSE,
            )
        return False
    if offload_source_table and ORACLE_TYPE_TIMESTAMP_TZ in offload_source_table.data_types_in_use():
        if messages:
            messages.log(
                "TIMESTAMP WITH TIME ZONE offloads are not valid with transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SQOOP,
                detail=VVERBOSE,
            )
        return False
    if offload_source_table and ORACLE_TYPE_XMLTYPE in offload_source_table.data_types_in_use():
        if messages:
            messages.log(
                "XMLTYPE offloads are not valid with transport method: %s" % OFFLOAD_TRANSPORT_METHOD_SQOOP,
                detail=VVERBOSE,
            )
        return False
    if not offload_operation:
        return True
    return True


def is_sqoop_by_query_available(config: "OrchestrationConfig", messages: "OffloadMessages" = None):
    """If messages is passed in then we'll log any reason for a False return"""
    if config.backend_distribution and config.backend_distribution not in HADOOP_BASED_BACKEND_DISTRIBUTIONS:
        (
            messages.log(
                "Transport method only valid on Hadoop systems: %s/%s"
                % (
                    OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY,
                    config.backend_distribution,
                ),
                detail=VVERBOSE,
            )
            if messages
            else None
        )
        return False
    if not config.offload_transport_cmd_host:
        (
            messages.log(
                "OFFLOAD_TRANSPORT_CMD_HOST required for transport method: %s"
                % OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY,
                detail=VVERBOSE,
            )
            if messages
            else None
        )
        return False
    return True

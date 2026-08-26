#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from goe.offload.offload_constants import (
    DBTYPE_BIGQUERY,
    DBTYPE_HIVE,
    DBTYPE_IMPALA,
    DBTYPE_SNOWFLAKE,
    DBTYPE_SYNAPSE,
)
from goe.persistence.orchestration_metadata import OrchestrationMetadata


def backend_table_factory(
    db_name,
    table_name,
    backend_type,
    orchestration_options,
    messages,
    orchestration_operation=None,
    hybrid_metadata=None,
    dry_run=None,
    frontend_owner_override=None,
    frontend_name_override=None,
    existing_backend_api=None,
    do_not_connect=False,
):
    """Return a BackendTable object for the appropriate backend.
    hybrid_owner_override/hybrid_view_override are for use from modules that do not have
    an orchestration_operation or a means of getting hybrid_metadata.
    """
    if dry_run is None:
        if orchestration_operation:
            dry_run = bool(not orchestration_operation.execute)
        elif hasattr(orchestration_options, "execute"):
            dry_run = bool(not orchestration_options.execute)
        elif do_not_connect:
            dry_run = True
        else:
            dry_run = False

    if not hybrid_metadata:
        if orchestration_operation:
            hybrid_metadata = orchestration_operation.get_hybrid_metadata()
        elif frontend_owner_override and frontend_name_override:
            hybrid_metadata = OrchestrationMetadata.from_name(
                frontend_owner_override,
                frontend_name_override,
                connection_options=orchestration_options,
                messages=messages,
            )

    if backend_type == DBTYPE_HIVE:
        from goe.offload.hadoop.hive_backend_table import BackendHiveTable

        return BackendHiveTable(
            db_name,
            table_name,
            backend_type,
            orchestration_options,
            messages,
            orchestration_operation=orchestration_operation,
            hybrid_metadata=hybrid_metadata,
            dry_run=dry_run,
            existing_backend_api=existing_backend_api,
            do_not_connect=do_not_connect,
        )
    if backend_type == DBTYPE_IMPALA:
        from goe.offload.hadoop.impala_backend_table import BackendImpalaTable

        return BackendImpalaTable(
            db_name,
            table_name,
            backend_type,
            orchestration_options,
            messages,
            orchestration_operation=orchestration_operation,
            hybrid_metadata=hybrid_metadata,
            dry_run=dry_run,
            existing_backend_api=existing_backend_api,
            do_not_connect=do_not_connect,
        )
    if backend_type == DBTYPE_BIGQUERY:
        from goe.offload.bigquery.bigquery_backend_table import BackendBigQueryTable

        return BackendBigQueryTable(
            db_name,
            table_name,
            backend_type,
            orchestration_options,
            messages,
            orchestration_operation=orchestration_operation,
            hybrid_metadata=hybrid_metadata,
            dry_run=dry_run,
            existing_backend_api=existing_backend_api,
            do_not_connect=do_not_connect,
        )
    if backend_type == DBTYPE_SNOWFLAKE:
        from goe.offload.snowflake.snowflake_backend_table import BackendSnowflakeTable

        return BackendSnowflakeTable(
            db_name,
            table_name,
            backend_type,
            orchestration_options,
            messages,
            orchestration_operation=orchestration_operation,
            hybrid_metadata=hybrid_metadata,
            dry_run=dry_run,
            existing_backend_api=existing_backend_api,
            do_not_connect=do_not_connect,
        )
    if backend_type == DBTYPE_SYNAPSE:
        from goe.offload.microsoft.synapse_backend_table import BackendSynapseTable

        return BackendSynapseTable(
            db_name,
            table_name,
            backend_type,
            orchestration_options,
            messages,
            orchestration_operation=orchestration_operation,
            hybrid_metadata=hybrid_metadata,
            dry_run=dry_run,
            existing_backend_api=existing_backend_api,
            do_not_connect=do_not_connect,
        )
    raise NotImplementedError("Unsupported backend system type: %s" % backend_type)


def get_backend_table_from_metadata(hybrid_metadata, options, messages, offload_operation=None):
    return backend_table_factory(
        hybrid_metadata.backend_owner,
        hybrid_metadata.backend_table,
        options.target,
        options,
        messages,
        orchestration_operation=offload_operation,
        hybrid_metadata=hybrid_metadata,
    )

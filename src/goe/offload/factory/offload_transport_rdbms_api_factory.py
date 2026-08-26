#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from goe.offload.offload_constants import (
    DBTYPE_MSSQL,
    DBTYPE_ORACLE,
    DBTYPE_TERADATA,
)


def offload_transport_rdbms_api_factory(
    rdbms_owner,
    rdbms_table_name,
    offload_options,
    messages,
    dry_run=False,
):
    """Constructs and returns an appropriate data transport object based on source RDBMS"""
    if offload_options.db_type == DBTYPE_ORACLE:
        from goe.offload.oracle.oracle_offload_transport_rdbms_api import (
            OffloadTransportOracleApi,
        )

        return OffloadTransportOracleApi(
            rdbms_owner,
            rdbms_table_name,
            offload_options,
            messages,
            dry_run=dry_run,
        )
    if offload_options.db_type == DBTYPE_MSSQL:
        from goe.offload.microsoft.mssql_offload_transport_rdbms_api import (
            OffloadTransportMSSQLApi,
        )

        return OffloadTransportMSSQLApi(rdbms_owner, rdbms_table_name, offload_options, messages, dry_run=dry_run)
    if offload_options.db_type == DBTYPE_TERADATA:
        from goe.offload.teradata.teradata_offload_transport_rdbms_api import (
            OffloadTransportTeradataApi,
        )

        return OffloadTransportTeradataApi(rdbms_owner, rdbms_table_name, offload_options, messages, dry_run=dry_run)
    raise NotImplementedError("Offload transport source RDBMS not implemented: %s" % offload_options.db_type)

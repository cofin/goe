# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Factory function for selecting the OffloadSourceDataInterface implementation."""

from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_source_table import (
    OFFLOAD_PARTITION_TYPE_LIST,
    OFFLOAD_PARTITION_TYPE_RANGE,
)
from goe.offload.source_data.base import (
    OFFLOAD_OP_TERMS,
    OFFLOAD_PARTITION_APPEND_CAPABLE_TYPES,
)
from goe.offload.source_data.full import OffloadSourceDataFull, OffloadSourceDataFullPartitioned
from goe.offload.source_data.ipa_list import OffloadSourceDataIpaList
from goe.offload.source_data.ipa_range import OffloadSourceDataIpaListAsRange, OffloadSourceDataIpaRange
from goe.offload.source_data.predicate import OffloadSourceDataPredicate
from goe.persistence.models import (
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_PREDICATE,
)


def offload_source_data_factory(
    offload_source_table,
    offload_target_table,
    offload_operation,
    hybrid_metadata,
    messages,
    source_client_type,
    rdbms_partition_columns_override=None,
    col_offload_source_table_override=None,
):
    """Constructs and returns an appropriate data source object based on user inputs and the RDBMS table type"""
    assert source_client_type in OFFLOAD_OP_TERMS
    terms = OFFLOAD_OP_TERMS[source_client_type]
    if (
        offload_operation.offload_predicate
        or offload_operation.ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_PREDICATE
    ):
        messages.log("Offload source data type: OffloadSourceDataPredicate", detail=VVERBOSE)
        return OffloadSourceDataPredicate(
            offload_source_table,
            offload_target_table,
            offload_operation,
            hybrid_metadata,
            messages,
            source_client_type=source_client_type,
            rdbms_partition_columns_override=rdbms_partition_columns_override,
            col_offload_source_table_override=col_offload_source_table_override,
        )
    if not offload_source_table.partition_type:
        messages.log("Offload source data type: OffloadSourceDataFull", detail=VVERBOSE)
        return OffloadSourceDataFull(
            offload_source_table,
            offload_target_table,
            offload_operation,
            hybrid_metadata,
            messages,
            source_client_type=source_client_type,
        )
    if offload_source_table.partition_type not in OFFLOAD_PARTITION_APPEND_CAPABLE_TYPES:
        messages.log(
            "Offload source data type: OffloadSourceDataFullPartitioned",
            detail=VVERBOSE,
        )
        return OffloadSourceDataFullPartitioned(
            offload_source_table,
            offload_target_table,
            offload_operation,
            hybrid_metadata,
            messages,
            source_client_type=source_client_type,
            rdbms_partition_columns_override=rdbms_partition_columns_override,
            col_offload_source_table_override=col_offload_source_table_override,
        )
    if offload_source_table.partition_type in (
        OFFLOAD_PARTITION_TYPE_RANGE,
        OFFLOAD_PARTITION_TYPE_LIST,
    ):
        bad_data_types = offload_source_table.unsupported_partition_data_types()
        if bad_data_types:
            messages.log(
                "Table %s.%s is %s partitioned by %s (not %s), incremental %s is not supported"
                % (
                    offload_source_table.owner,
                    offload_source_table.table_name,
                    offload_source_table.partition_type,
                    ", ".join(bad_data_types),
                    ", ".join(offload_source_table.supported_partition_data_types()),
                    terms["name"],
                ),
                detail=VERBOSE,
            )
            messages.log(
                "Offload source data type: OffloadSourceDataFullPartitioned",
                detail=VVERBOSE,
            )
            return OffloadSourceDataFullPartitioned(
                offload_source_table,
                offload_target_table,
                offload_operation,
                hybrid_metadata,
                messages,
                source_client_type=source_client_type,
                rdbms_partition_columns_override=rdbms_partition_columns_override,
                col_offload_source_table_override=col_offload_source_table_override,
            )

        if offload_source_table.partition_type == OFFLOAD_PARTITION_TYPE_RANGE:
            messages.log("Offload source data type: OffloadSourceDataIpaRange", detail=VVERBOSE)
            return OffloadSourceDataIpaRange(
                offload_source_table,
                offload_target_table,
                offload_operation,
                hybrid_metadata,
                messages,
                source_client_type=source_client_type,
                rdbms_partition_columns_override=rdbms_partition_columns_override,
                col_offload_source_table_override=col_offload_source_table_override,
            )
        if (
            offload_source_table.partition_type == OFFLOAD_PARTITION_TYPE_LIST
            and offload_operation.ipa_predicate_type
            in (
                INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
                INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
            )
        ):
            messages.log(
                "Offload source data type: OffloadSourceDataIpaListAsRange",
                detail=VVERBOSE,
            )
            return OffloadSourceDataIpaListAsRange(
                offload_source_table,
                offload_target_table,
                offload_operation,
                hybrid_metadata,
                messages,
                source_client_type=source_client_type,
                rdbms_partition_columns_override=rdbms_partition_columns_override,
                col_offload_source_table_override=col_offload_source_table_override,
            )
        if offload_source_table.partition_type == OFFLOAD_PARTITION_TYPE_LIST:
            messages.log("Offload source data type: OffloadSourceDataIpaList", detail=VVERBOSE)
            return OffloadSourceDataIpaList(
                offload_source_table,
                offload_target_table,
                offload_operation,
                hybrid_metadata,
                messages,
                source_client_type=source_client_type,
                rdbms_partition_columns_override=rdbms_partition_columns_override,
                col_offload_source_table_override=col_offload_source_table_override,
            )
        raise NotImplementedError(
            "Offload source data method not implemented for partition type: %s" % offload_source_table.partition_type
        )
    raise NotImplementedError(
        "Offload source data method not implemented for partition type: %s" % offload_source_table.partition_type
    )

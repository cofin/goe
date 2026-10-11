# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Full (unpartitioned and partitioned) offload source-data implementations."""

from goe.offload.source_data.base import (
    OffloadSourceDataInterface,
    OffloadSourcePartitions,
)


class OffloadSourceDataFull(OffloadSourceDataInterface):
    """Full non-partitioned 100/0 offloads"""

    def __init__(
        self,
        offload_source_table,
        offload_target_table,
        offload_operation,
        hybrid_metadata,
        messages,
        source_client_type,
    ):
        """CONSTRUCTOR"""
        self._partition_append_capable = False
        self._incremental_append_capable = False
        self._partition_append_predicate_type = None

        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            hybrid_metadata,
            messages,
            source_client_type=source_client_type,
        )

        self._messages.notice(
            "Table %s.%s is not partitioned, %s entire table"
            % (
                offload_source_table.owner,
                offload_source_table.table_name,
                self._terms["now"],
            )
        )

    def offload_data_detection(self):
        """For a heap table there's always something to offload - even if it's empty"""
        self.populate_source_partitions()
        self._offloaded_partitions = OffloadSourcePartitions()
        self._populate_partitions_to_offload()
        self._nothing_to_offload = False

    def get_incremental_high_values(self):
        return []

    def offloading_open_ended_partition(self):
        return False

    def _ida_options_have_been_specified(self):
        return False


class OffloadSourceDataFullPartitioned(OffloadSourceDataInterface):
    """Full partitioned 100/0 offloads"""

    def __init__(
        self,
        offload_source_table,
        offload_target_table,
        offload_operation,
        hybrid_metadata,
        messages,
        source_client_type,
        rdbms_partition_columns_override=None,
        col_offload_source_table_override=None,
    ):
        """CONSTRUCTOR"""
        self._partition_append_capable = False
        self._incremental_append_capable = False
        self._partition_append_predicate_type = None

        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            hybrid_metadata,
            messages,
            source_client_type=source_client_type,
            rdbms_partition_columns_override=rdbms_partition_columns_override,
            col_offload_source_table_override=col_offload_source_table_override,
        )

        messages.notice(
            "Table %s.%s is %s partitioned, %s entire table"
            % (
                offload_source_table.owner,
                offload_source_table.table_name,
                offload_source_table.partition_type,
                self._terms["now"],
            )
        )

    def offload_data_detection(self):
        self.populate_source_partitions()
        self._report_source_partitions()
        self._offloaded_partitions = OffloadSourcePartitions()
        self._populate_partitions_to_offload()
        self._nothing_to_offload = bool(self._partitions_to_offload.count() == 0)

    def get_incremental_high_values(self):
        return []

    def offloading_open_ended_partition(self):
        if not self.partitions_to_offload:
            return False
        return bool(
            self.partitions_to_offload.has_maxvalue_partition() or self.partitions_to_offload.has_default_partition()
        )

    def _ida_options_have_been_specified(self):
        if self._user_requested_partition_names:
            raise NotImplementedError("Partition name filter is not valid for this offload")
        return False

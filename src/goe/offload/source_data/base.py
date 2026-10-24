# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Base abstractions, partition models, and shared constants for offload source data."""

import logging
from abc import ABCMeta, abstractmethod
from datetime import datetime
from typing import Any

from goe.offload import offload_constants
from goe.offload.backend_table import BackendTableInterface
from goe.offload.column_metadata import valid_column_list
from goe.offload.offload_functions import (
    datetime_literal_to_python,
)
from goe.offload.offload_messages import VVERBOSE
from goe.offload.offload_metadata_functions import (
    OFFLOAD_TYPE_FULL,
    OFFLOAD_TYPE_INCREMENTAL,
    incremental_hv_list_from_csv,
)
from goe.offload.offload_source_table import (
    OFFLOAD_PARTITION_TYPE_LIST,
    OFFLOAD_PARTITION_TYPE_RANGE,
    OffloadSourceTableInterface,
)
from goe.offload.oracle.oracle_column import (
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_TIMESTAMP_TZ,
)


class OffloadSourceDataException(Exception):
    pass


OFFLOAD_PARTITION_APPEND_CAPABLE_TYPES = [
    OFFLOAD_PARTITION_TYPE_RANGE,
    OFFLOAD_PARTITION_TYPE_LIST,
]

OFFLOAD_SOURCE_CLIENT_OFFLOAD = "offload"
OFFLOAD_OP_TERMS = {
    OFFLOAD_SOURCE_CLIENT_OFFLOAD: {
        "name": "offload",
        "now": "offloading",
        "past": "offloaded",
    },
}

LAPBO_TYPE_90_10 = "90/10"
LAPBO_TYPE_100_10 = "100/10"
LAPBO_TYPE_100_0 = "100/0"

NO_DEFAULT_PARTITION_NOTICE_TEXT = f"with high_value of {offload_constants.PART_OUT_OF_LIST}"
NO_MATCHING_PARTITION_EXCEPTION_TEXT = "No partition found matching name"
NO_MAXVALUE_PARTITION_NOTICE_TEXT = f"with high_value of {offload_constants.PART_OUT_OF_RANGE}"
INCREMENTAL_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT = "Offload type invalid when DEFAULT partition has been offloaded"
INVALID_HV_FOR_LIST_AS_RANGE_EXCEPTION_TEXT = (
    "Partitions have key values which are incompatible with LIST_AS_RANGE offloading"
)
IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT = f"Cannot offload {offload_constants.PART_OUT_OF_LIST} partition"
OFFLOAD_TYPE_CHANGE_FOR_PBO_EXCEPTION_TEXT = (
    "Switching between offload type FULL/INCREMENTAL is not supported for Predicate-Based Offload"
)
PREDICATE_APPEND_HWM_MESSAGE_TEXT = "Appended IPA high value to offload predicate"
PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT = "--offload-predicate is incompatible with INCREMENTAL_PREDICATE_TYPE"
PREDICATE_TYPE_NO_MODIFY_HV_EXCEPTION_TEXT = (
    "Option --no-modify-hybrid-view cannot be used with INCREMENTAL_PREDICATE_TYPE"
)
PREDICATE_TYPE_NO_MODIFY_RESET_EXCEPTION_TEXT = (
    "Options --no-modify-hybrid-view and --reset-hybrid-view are not compatible"
)
PREDICATE_TYPE_OFFLOAD_TYPE_FULL_EXCEPTION_TEXT = "OFFLOAD_TYPE FULL is not compatible with INCREMENTAL_PREDICATE_TYPE"
PREDICATE_TYPE_REQUIRED_EXCEPTION_TEXT = "--offload-predicate-type required for existing predicate type"
RANGE_AND_PREDICATE_WITHOUT_PART_KEY_EXCEPTION_TEXT = (
    "Offload predicate must contain a predicate for all existing partition key columns"
)
TOO_MANY_PARTITION_NAMES_EXCEPTION_TEXT = "Only one partition name can be included"

MAX_QUERY_OPTIMISTIC_PRUNE_CLAUSE = "max_query_optimistic_prune_clause"


def get_offload_type_for_config(
    owner,
    table_name,
    user_requested_offload_type,
    incr_append_capable,
    ida_options_specified,
    hybrid_metadata,
    messages,
    with_messages=True,
):
    """The user has specified which OT they want The user has not specified an override but hybrid objects already exist - derive settings The user has implied a 90/10 or 100/10 in the hybrid view"""
    offload_type = OFFLOAD_TYPE_FULL
    pred_for_90_10_in_hybrid_view = False

    if user_requested_offload_type:
        offload_type = user_requested_offload_type
        if offload_type == OFFLOAD_TYPE_INCREMENTAL and not incr_append_capable:
            if with_messages:
                messages.warning(
                    'Offload type %s incompatible with table %s.%s, continuing with type "FULL"'
                    % (offload_type, owner, table_name),
                    ansi_type="red",
                )
            offload_type = OFFLOAD_TYPE_FULL
    elif hybrid_metadata:
        offload_type = hybrid_metadata.offload_type
        if hybrid_metadata.incremental_high_value or hybrid_metadata.incremental_predicate_value:
            if with_messages:
                if hybrid_metadata.incremental_high_value:
                    messages.log(
                        "Including HWM in hybrid view due to existing INCREMENTAL_HIGH_VALUE metadata",
                        detail=VVERBOSE,
                    )
                else:
                    messages.log(
                        "Including HWM in hybrid view due to existing INCREMENTAL_PREDICATE_VALUE metadata",
                        detail=VVERBOSE,
                    )
            pred_for_90_10_in_hybrid_view = True
    elif incr_append_capable and ida_options_specified:
        offload_type = OFFLOAD_TYPE_INCREMENTAL

    if not pred_for_90_10_in_hybrid_view:
        if offload_type == OFFLOAD_TYPE_INCREMENTAL:
            pred_for_90_10_in_hybrid_view = True
        elif ida_options_specified:
            if with_messages:
                messages.log(
                    "Including HWM in hybrid view due to command options",
                    detail=VVERBOSE,
                )
            pred_for_90_10_in_hybrid_view = True

    return offload_type, pred_for_90_10_in_hybrid_view


def is_default_partition(partition):
    """Return True/False is the partition is a DEFAULT partition
    Global fn because shared by both partition and source data classes
    """
    upper_fn = lambda s: s.upper() if isinstance(s, str) else s
    return (
        True
        if [upper_fn(_) for _ in partition.partition_values_python] == [offload_constants.PART_OUT_OF_LIST]
        else False
    )


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class OffloadSourcePartition:
    """Holds a list of partitions for an RDBMS table:
    Basis is this is format Oracle uses, this should be refined in future to be more generic
    [
      partition name
    , high value CSV string (for Oracle dba_tab_partitions.high_value)
    , high values as Python values
    , partition size in bytes
    , number of rows in partition (according to stats)
    , HVs as individual strings
    , is the boundary a common boundary (True or False and only applies when subpartition range offloads are in play)
    , [ is a list of subpartitions for the partition (only applies for partition range offloads) ]
    ]
    """

    def __init__(
        self,
        partition_name,
        partition_literal,
        partition_values_python,
        partition_values_individual,
        size_in_bytes,
        row_count,
        common_partition_literal,
        subpartitions,
    ):
        self.partition_name = partition_name
        self.partition_literal = partition_literal
        self.partition_values_python = partition_values_python
        self.partition_values_individual = partition_values_individual
        self.size_in_bytes = size_in_bytes
        self.row_count = row_count
        self.common_partition_literal = common_partition_literal
        self.subpartitions = subpartitions

    def __str__(self):
        return "OffloadSourcePartition(partition_name=%s, partition_literal=%r)" % (
            self.partition_name,
            self.partition_literal,
        )

    def as_legacy_tuple(self):
        return (
            self.partition_name,
            self.partition_literal,
            self.partition_values_python,
            self.size_in_bytes,
            self.row_count,
            self.partition_values_individual,
            self.common_partition_literal,
            self.subpartitions,
        )


class OffloadSourcePartitions:
    """Holds partitions in scope for offload"""

    def __init__(self, partitions=[]):
        self._partitions = partitions

    def __str__(self):
        if self._partitions:
            return "OffloadSourcePartitions(partitions=%s, partition range=%s-%s)" % (
                len(self._partitions),
                self._partitions[0].partition_name,
                self._partitions[-1].partition_name,
            )
        return "OffloadSourcePartitions(None)"

    @staticmethod
    def from_source_table(offload_source_table, partition_append_capable):
        """Constructor to return partitions from an OffloadSourceTable"""
        if offload_source_table.offload_by_subpartition:
            rdbms_partitions = offload_source_table.get_subpartitions(strict=partition_append_capable)
            name_fn = lambda x: x.subpartition_name
            hwm_info = offload_source_table.get_subpartition_boundary_info()
            common_hwm_fn = lambda x: hwm_info[x.high_values_python]["common"]
        else:
            rdbms_partitions = offload_source_table.get_partitions(strict=partition_append_capable)
            name_fn = lambda x: x.partition_name
            common_hwm_fn = lambda x: True

        partitions = []
        if rdbms_partitions:
            for ora_partition in rdbms_partitions:
                partitions.append(
                    OffloadSourcePartition(
                        name_fn(ora_partition),
                        ora_partition.high_values_csv,
                        ora_partition.high_values_python,
                        ora_partition.high_values_individual,
                        ora_partition.partition_size,
                        ora_partition.num_rows,
                        common_hwm_fn(ora_partition),
                        ora_partition.subpartition_names,
                    )
                )
        return OffloadSourcePartitions(partitions)

    def as_legacy_list(self):
        """For (hopefully short term) use in goe.py matching goe.py constants:
        pc_name, pc_hv, pc_hv_values, pc_size, pc_rows, pc_hv_literals, pc_common_hwm, subpartitions
        """
        return [_.as_legacy_tuple() for _ in self._partitions]

    def count(self):
        return len(self._partitions)

    def get_partitions(self):
        return self._partitions

    def partition_names(self):
        return [_.partition_name for _ in self._partitions]

    def row_count(self):
        return sum(_.row_count for _ in self._partitions)

    def set_partitions(self, partitions):
        self._partitions = partitions

    def size_in_bytes(self):
        return sum(_.size_in_bytes for _ in self._partitions)

    def sort_partitions(self, sort_fn, reverse=False):
        """When sorting partitions we need to be sure any DEFAULT partition remains the "latest" Insert the open ended partition back on the latest end of the list"""
        if self._partitions:
            default_partition = self.remove_default_partition()
            self._partitions.sort(key=sort_fn, reverse=reverse)
            if default_partition:
                if reverse:
                    self._partitions.insert(0, default_partition)
                else:
                    self._partitions.append(default_partition)

    def subpartition_names(self):
        return [s for p in self._partitions if p.subpartitions is not None for s in p.subpartitions]

    def report_partitions(self, offload_by_subpartition, messages, include_stats=True):
        """Reports partitions in a standard format, used in offload stdout"""

        def partition_attr_report_value(list_of_attrs):
            if any(_ is None for _ in list_of_attrs):
                return "Unknown"
            return sum(list_of_attrs)

        part_description = "subpartitions" if offload_by_subpartition else "partitions"
        if not self._partitions:
            messages.log("0 %s" % part_description)
            return
        size = partition_attr_report_value([_.size_in_bytes for _ in self._partitions])
        rows = partition_attr_report_value([_.row_count for _ in self._partitions])
        if include_stats:
            messages.log(
                "%s %s (%s - %s), total size %s, total rows (from stats) %s"
                % (
                    len(self._partitions),
                    part_description,
                    self._partitions[-1].partition_name,
                    self._partitions[0].partition_name,
                    size,
                    rows,
                )
            )
        else:
            messages.log("%s %s" % (len(self._partitions), part_description))
        if messages.debug_enabled():
            for p in self._partitions:
                messages.log("%s" % str(p), detail=VVERBOSE)

    def get_partition(self, partition_name=None, partition_values_python=None):
        """Get a single partition based on either name or partition_values_python

        It's possible to match multiple partitions by value due to sub-partitioning Return the first in the list
        """
        assert partition_name or partition_values_python
        if partition_values_python:
            assert isinstance(partition_values_python, (list, tuple))

        if partition_name:
            filter_fn = lambda x: x.partition_name == partition_name
        else:
            filter_fn = lambda x: x.partition_values_python == tuple(partition_values_python)
        filtered_partitions = self.search_by_filter(filter_fn)
        if not filtered_partitions:
            return None
        if partition_name and len(filtered_partitions) > 1:
            raise OffloadSourceDataException(
                "Unexpected partition count for partition name %s: %s" % (partition_name, len(filtered_partitions))
            )
        return filtered_partitions[0]

    def get_partition_by_index(self, index):
        return self._partitions[index] if self._partitions else None

    def get_prior_partition(self, partition=None, partition_name=None, partition_values_python=None):
        """Get a single partition based on finding a particular partition_values_python and then
        finding the partition_values_python before the parameter.
        We can use any of a whole partition, partition name or HV as a jumping off point.
        This is not as simple as index-1 because of sub-partitioned tables with repeating HVs.
        This operation only really makes sense for RANGE based partition sets.
        """
        logger.debug("get_prior_partition")
        assert partition or partition_name or partition_values_python
        if partition_values_python:
            assert isinstance(partition_values_python, (list, tuple))
        if partition:
            assert isinstance(partition, OffloadSourcePartition)

        start_partition = partition or self.get_partition(
            partition_name=partition_name,
            partition_values_python=partition_values_python,
        )
        if not start_partition:
            if partition_name:
                raise OffloadSourceDataException("%s: %s" % (NO_MATCHING_PARTITION_EXCEPTION_TEXT, partition_name))
            raise OffloadSourceDataException(
                "No partition found matching high value: %s" % str(partition_values_python)
            )
        logger.debug("get_prior_partition filter partition: %s" % start_partition.partition_name)

        def filter_fn(p):
            if is_default_partition(p):
                return False
            return bool(tuple(p.partition_values_python) < tuple(start_partition.partition_values_python))

        true_part_list, _ = self.split_partitions(filter_fn)
        return true_part_list.get_partitions()[0] if true_part_list.count() > 0 else None

    def has_maxvalue_partition(self):
        """Partitions are sorted new to old therefore, if there's an OUT-OF-RANGE partition it will be first
        For convenience return the partition name/None rather than True/False
        """
        if (not self._partitions) or (self._partitions[0].partition_literal is None):
            return None
        if offload_constants.PART_OUT_OF_RANGE in self._partitions[0].partition_values_individual:
            return self._partitions[0].partition_name
        return None

    def remove_maxvalue_partition(self):
        """Partitions are sorted new to old therefore, if there's a MAXVALUE partition it will be first
        Returns the removed partition for convenience
        """
        if self.has_maxvalue_partition():
            return self._partitions.pop(0)
        return None

    def remove_default_partition(self):
        """Remove the DEFAULT partition from the list of partitions and return the partition object
        for convenience.
        """
        default_partition = self.get_default_partition()
        if default_partition:
            self._partitions.remove(default_partition)
        return default_partition

    def get_default_partition(self):
        """Return partition object for default partition."""
        return self.has_default_partition(return_partition_object=True)

    def has_default_partition(self, return_partition_object=False):
        """For convenience returns a matching partition name/None instead of True/False"""
        if self._partitions:
            default_partitions = [_ for _ in self._partitions if is_default_partition(_)]
            if default_partitions:
                return default_partitions[0] if return_partition_object else default_partitions[0].partition_name
        return None

    def search_by_filter(self, filter_fn):
        """Use filter_fn() on each partition and keep/reject them based on truthyness of filter_fn return"""
        filtered_partitions = []
        for p in self._partitions:
            if filter_fn(p):
                filtered_partitions.append(p)
        return filtered_partitions

    def apply_filter(self, filter_fn):
        """Apply filtered partitions to the object state"""
        self._partitions = self.search_by_filter(filter_fn)

    def split_partitions(self, split_fn):
        """Divvy up _partitions based on split_fn
        Return the two parts:
            (partitions where split_fn(), partitions where not split_fn())
        Does not change the underlying _partitions list
        """
        true_partitions, false_partitions = [], []
        for p in self._partitions:
            true_partitions.append(p) if split_fn(p) else false_partitions.append(p)
        return OffloadSourcePartitions(true_partitions), OffloadSourcePartitions(false_partitions)


class OffloadSourceDataInterface(metaclass=ABCMeta):
    """Abstract base class which acts as an interface for "offload type" specific sub-classes.
    Library for logic/interaction with data that is the source of an offload.
    Goes hand in hand with OffloadSourceTable but is more about interacting with the source data,
    applying filters to it etc.
    Any RDBMS specifics should be catered for in OffloadSourceTable, this module should be generic
    offload logic.
    """

    _incremental_append_capable: Any
    _partition_append_capable: Any
    _partition_append_predicate_type: Any
    _source_partitions: Any
    _offloaded_partitions: Any
    _partitions_to_offload: Any
    _target_table_max: Any
    _rdbms_min: Any

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
        """We have two offload_source_table objects, one for partition logic and one for column access This is because materialized joins need to work from base offloaded table for partitions but have different column names Caching partition_columns independently because join materialization requires an override. This informs us whether we are offloading, materializing a join, or presenting Cache attributes from offload_operation/options that we are interested in For joins we need a version of the predicate with adjusted column names cache any offload_source_table attributes that are used frequently - just for convenience Ideally we should initialize the attributes below here but the constructors reference them in a mish mash of ways and setting them here (or re-orging the constructor calls) is proving a risky business. Having nothing to offload is not always a bad thing, this attribute lets a calling program check this via self.nothing_to_offload() variables to hold assorted lists of partitions, these can consume significant memory and have associated free_* methods to blat them if required"""
        assert offload_source_table and isinstance(offload_source_table, OffloadSourceTableInterface)
        assert offload_target_table and isinstance(offload_target_table, BackendTableInterface)
        if col_offload_source_table_override:
            assert col_offload_source_table_override and isinstance(
                col_offload_source_table_override, OffloadSourceTableInterface
            )
        if rdbms_partition_columns_override:
            assert valid_column_list(rdbms_partition_columns_override)

        self._messages = messages
        self.debug("OffloadSourceData setup")
        self._part_offload_source_table = offload_source_table
        if col_offload_source_table_override:
            self.log(
                "Overriding source RDBMS columns with: %s.%s.columns"
                % (
                    col_offload_source_table_override.owner,
                    col_offload_source_table_override.table_name,
                ),
                detail=VVERBOSE,
            )
        self._col_offload_source_table = col_offload_source_table_override or offload_source_table
        self._offload_target_table = offload_target_table
        self._pre_offload_hybrid_metadata = hybrid_metadata
        self.debug("Pre-offload metadata: %s" % str(hybrid_metadata))
        if rdbms_partition_columns_override:
            self.log(
                "Overriding source data partition columns with: %s" % str(rdbms_partition_columns_override),
                detail=VVERBOSE,
            )
        self._partition_columns = rdbms_partition_columns_override or offload_source_table.partition_columns
        self._source_client_type = source_client_type
        self._terms = OFFLOAD_OP_TERMS[source_client_type]
        self._offload_predicate = offload_operation.offload_predicate
        self._inflight_offload_predicate = self._offload_predicate
        self._offload_predicate_modify_hybrid_view = offload_operation.offload_predicate_modify_hybrid_view
        self._post_offload_predicates = None
        self._col_offload_predicate = self._offload_predicate
        self._user_requested_offload_type = offload_operation.offload_type
        self._user_requested_table_reset = offload_operation.reset_backend_table
        self._user_requested_hybrid_view_reset = offload_operation.reset_hybrid_view
        self._user_requested_predicate_type = offload_operation.ipa_predicate_type
        self._user_requested_partition_names = offload_operation.partition_names
        self._user_requested_max_offload_chunk_size = offload_operation.max_offload_chunk_size
        self._user_requested_max_offload_chunk_count = offload_operation.max_offload_chunk_count
        self._offload_by_subpartition = offload_source_table.offload_by_subpartition

        self._target_table_max = None
        self._offload_type = None
        self._pred_for_90_10_in_hybrid_view = None
        self._backend_synth_part_expr = None

        self._nothing_to_offload = False

        self._set_offload_type()

        self._source_partitions = None
        self._offloaded_partitions = None
        self._partitions_to_offload = None

    def log(self, msg, detail=None):
        self._messages.log(msg, detail=detail)
        if detail == VVERBOSE:
            logger.debug(msg)
        else:
            logger.info(msg)

    def debug(self, msg):
        self._messages.debug(msg)
        logger.debug(msg)

    def get_offload_type(self):
        return self._offload_type

    def nothing_to_offload(self):
        return self._nothing_to_offload

    def pred_for_90_10_in_hybrid_view(self):
        return self._pred_for_90_10_in_hybrid_view

    @abstractmethod
    def offload_data_detection(self):
        pass

    @abstractmethod
    def get_incremental_high_values(self):
        pass

    def get_pre_offload_predicates(self, as_dsl=False):
        if self._pre_offload_hybrid_metadata:
            return self._pre_offload_hybrid_metadata.decode_incremental_predicate_values(as_dsl=as_dsl)
        return None

    def get_post_offload_predicates(self):
        return self._post_offload_predicates

    def get_offload_predicate(self):
        return self._offload_predicate

    def get_pre_offload_predicate_type(self):
        if self._pre_offload_hybrid_metadata:
            return self._pre_offload_hybrid_metadata.incremental_predicate_type
        return None

    def get_inflight_offload_predicate(self):
        return self._inflight_offload_predicate

    def is_incremental_append_capable(self):
        return self._incremental_append_capable

    def is_partition_append_capable(self):
        return self._partition_append_capable

    def get_partition_append_predicate_type(self):
        return self._partition_append_predicate_type

    def incremental_hv_list_from_csv(self, metadata_high_value_string):
        logger.debug("incremental_hv_list_from_csv")
        return incremental_hv_list_from_csv(metadata_high_value_string, self._partition_append_predicate_type)

    @property
    def source_partitions(self):
        return self._source_partitions

    def populate_source_partitions(self, sort_by_hv=False):
        logger.debug("populate_source_partitions")
        if not self._source_partitions:
            source_partitions = OffloadSourcePartitions.from_source_table(
                self._part_offload_source_table,
                partition_append_capable=self._partition_append_capable,
            )
            if sort_by_hv:
                self.log(
                    "Sorting %s partitions by partition value" % source_partitions.count(),
                    detail=VVERBOSE,
                )
                source_partitions.sort_partitions(sort_fn=lambda x: x.partition_values_python, reverse=True)
            self.debug("populate_source_partitions, partition count: %s" % source_partitions.count())
            self._source_partitions = source_partitions
        return self._source_partitions

    def free_source_partitions(self):
        logger.debug("free_source_partitions")
        self._source_partitions = None

    @property
    def offloaded_partitions(self):
        return self._offloaded_partitions

    def free_offloaded_partitions(self):
        logger.debug("free_offloaded_partitions")
        self._offloaded_partitions = None

    @property
    def partitions_to_offload(self):
        return self._partitions_to_offload

    def split_partitions_to_offload_by_no_segment(self):
        """Split the partitions to offload on whether they have a segment or not"""
        logger.debug("split_partitions_to_offload_by_no_segment")
        filter_fn = lambda p: bool(p.size_in_bytes != 0)
        return self._partitions_to_offload.split_partitions(filter_fn)

    def discard_partitions_to_offload_by_no_segment(self):
        """Remove no-segment partitions from the to-offload list"""
        logger.debug("discard_partitions_to_offload_by_no_segment")
        filter_fn = lambda p: bool(p.size_in_bytes != 0)
        self.partitions_to_offload.apply_filter(filter_fn)

    @abstractmethod
    def offloading_open_ended_partition(self):
        pass

    def get_partitions_to_offload_chunks(self):
        """Break a list of offloadable partitions up in to chunks
        Allows user to control volume of data processed in one pass (smaller chunks = less Impala memory)

        TODO nj@2019-06-07 Don't like the double reverse but didn't want to dig into why right now If there are partitions with a matching HWM then they should be included in the chunk, overriding max chunk size/count. This prevents failed offloads from believing a HWM is completely offloaded (important for offload by subpartition) Remaining was reversed before we started so let's reverse the chunk before yielding it
        """

        remaining = self.partitions_to_offload.get_partitions()[:]
        remaining.reverse()
        while remaining:
            chunk = [remaining.pop(0)]
            chunk_size = chunk[0].size_in_bytes
            while (
                remaining
                and (chunk_size + remaining[0].size_in_bytes) < self._user_requested_max_offload_chunk_size
                and len(chunk) < self._user_requested_max_offload_chunk_count
            ):
                p = remaining.pop(0)
                chunk.append(p)
                chunk_size += p.size_in_bytes
            with_matching_hwm = self._partitions_of_matching_hwm(chunk[-1].partition_values_python, remaining)
            if with_matching_hwm:
                chunk.extend(with_matching_hwm)
                chunk_size += sum(p.size_in_bytes for p in with_matching_hwm)
                remaining = remaining[len(with_matching_hwm) :]
            chunk.reverse()
            yield (
                OffloadSourcePartitions(chunk),
                OffloadSourcePartitions(remaining[:]),
            )

    def _get_backend_synth_part_expr(self):
        """Return a list defining how the backend is partitioned. Importantly, because of as_python_fns=True,
        this includes Python functions that convert values to any synthetic values.
        """
        if not self._target_table_exists():
            self._backend_synth_part_expr = []
        elif not self._backend_synth_part_expr:
            self._backend_synth_part_expr = self._offload_target_table.gen_synthetic_partition_col_expressions(
                as_python_fns=True
            )
        return self._backend_synth_part_expr

    def _is_synthetic_partition_column(self, partition_column):
        return self._offload_target_table.is_synthetic_partition_column(partition_column)

    def _target_table_exists(self):
        if self._user_requested_table_reset:
            return False
        return self._offload_target_table.table_exists()

    def _set_offload_type(self):
        (
            self._offload_type,
            self._pred_for_90_10_in_hybrid_view,
        ) = get_offload_type_for_config(
            self._part_offload_source_table.owner,
            self._part_offload_source_table.table_name,
            self._user_requested_offload_type,
            self._incremental_append_capable,
            self._ida_options_have_been_specified(),
            self._pre_offload_hybrid_metadata,
            self._messages,
            with_messages=True,
        )

    def _populate_partitions_to_offload(self):
        """Get and store the remaining partitions after filtering offloaded_partitions from source_partitions"""
        logger.debug("_populate_partitions_to_offload")
        assert self._source_partitions
        assert self._offloaded_partitions
        if not self._partitions_to_offload:
            partition_delta = [
                _
                for _ in self._source_partitions.get_partitions()
                if _.partition_name not in self._offloaded_partitions.partition_names()
            ]
            self._partitions_to_offload = OffloadSourcePartitions(partition_delta)
            self.debug("Partitions to Offload initial count: %s" % self._partitions_to_offload.count())
        return self._partitions_to_offload

    def _datetime_literal_to_python(self, dt_literal):
        logger.debug("_datetime_literal_to_python")
        return datetime_literal_to_python(dt_literal)

    @abstractmethod
    def _ida_options_have_been_specified(self):
        pass

    def _partitions_of_matching_hwm(self, more_of_this_hwm, remaining_partitions):
        """Return a list of partitions with the same hwm as more_of_this_hwm
        Used when collecting more sub-partitions of the same HWM in a range offload
        This is not checking for contiguous partitions, just collecting them into a single list
        """
        if not more_of_this_hwm:
            return []
        return [subp for subp in remaining_partitions if subp.partition_values_python == more_of_this_hwm]

    def _make_rpa_hwm_gte_clause(self):
        """If this is a partition append incremental offload then we can attempt to build a where clause to optimise
        the backend scan to get the current data HWM.
        Only returns a clause if:
          - RDBMS table has a single partition column (i.e. not multi-column-partitioning, nothing to do
            with sub-partitioning). This is because the hwm clause for multi-col would be excessively complex.
          - There is previous metadata.
          - We're not resetting.
          - The relevant backend partition column is a synthetic one, otherwise we trust backend engine to optimise.

        Not an IPA offload RDBMS part col not used as a synthetic partition column in the backend Workaround referenced in GOE-1572, we cannot trust synthetic partition values for negative numbers
        """
        if self._user_requested_table_reset:
            return None

        if self._source_partitions.count() == 0 or not self._pre_offload_hybrid_metadata:
            return None

        if not self._partition_columns or len(self._partition_columns) > 1:
            return None

        partition_column = self._partition_columns[0]

        backend_synth_part_expr = self._get_backend_synth_part_expr()

        assert type(backend_synth_part_expr) is list
        if backend_synth_part_expr:
            assert len(backend_synth_part_expr[0]) == 4, "_backend_synth_part_expr is malformed"

        matching_backend_part_col = None
        synthetic_conv_fn = None
        for part_expr in backend_synth_part_expr:
            if part_expr[3].upper() == partition_column.name.upper():
                matching_backend_part_col = self._offload_target_table.get_column(part_expr[0])
                synthetic_conv_fn = part_expr[2]
                break

        if not matching_backend_part_col:
            return None

        if not self._is_synthetic_partition_column(matching_backend_part_col.name):
            self.debug("Partition column is native therefore no extra predicate is required")
            return None

        prior_offload_partition = self._get_prior_partition_to_offload_by_hv_literal()
        prior_rdbms_hv = prior_offload_partition.partition_literal if prior_offload_partition else None
        hv_tuple = (
            self._part_offload_source_table.decode_partition_high_values(prior_rdbms_hv) if prior_rdbms_hv else None
        )
        self.debug("Prior partition HV tuple: %s" % str(hv_tuple))

        if hv_tuple and self._partition_columns[0].is_number_based() and hv_tuple[0] < 0:
            self.debug("No synthetic partition predicate for negative numeric: %s" % str(hv_tuple[0]))
            return None

        if hv_tuple and synthetic_conv_fn:
            converted_hv = synthetic_conv_fn(hv_tuple[0])
            backend_literal = self._offload_target_table.to_backend_literal(
                converted_hv, data_type=matching_backend_part_col.data_type
            )
            return "%s >= %s" % (matching_backend_part_col.name, backend_literal)

    def _combine_part_cols_with_values(self, row_values):
        """Helper function for Oracle min values row & backend max values row"""
        if not row_values:
            return None
        new_row = [
            (self._datetime_literal_to_python(row_val) if part_col.is_date_based() else row_val)
            for part_col, row_val in zip(self._partition_columns, row_values)
        ]
        return tuple(new_row)

    def _get_pre_offload_offload_type(self):
        if self._pre_offload_hybrid_metadata:
            return self._pre_offload_hybrid_metadata.offload_type
        return None

    def _get_pre_offload_incremental_key(self):
        if self._pre_offload_hybrid_metadata:
            return self._pre_offload_hybrid_metadata.incremental_key
        return None

    def _get_prior_partition_to_offload_by_hv_literal(self):
        """Find a particular RDBMS hwm in the list of candidate partitions and return the prior offloaded partition

        Use pop() below to take last partition with matching HWM This only matters when multiple partitions have the same HWM (offload_by_subpartition)
        """
        hv = self._pre_offload_hybrid_metadata.incremental_high_value if self._pre_offload_hybrid_metadata else None
        self.debug("Finding partition prior to: %s" % str(hv))
        source_partitions = self._source_partitions.get_partitions()

        def match_fn(p):
            match = bool(p.partition_literal == hv)
            if match:
                self.debug("Matched %s: %s == %s" % (p.partition_name, p.partition_literal, hv))
            return match

        hv_partition_indices = [i for i, p in enumerate(source_partitions) if match_fn(p)]
        if not hv_partition_indices:
            return None
        hv_partition_index = hv_partition_indices.pop()
        if hv_partition_index >= len(source_partitions) - 1:
            return None
        return source_partitions[hv_partition_index + 1]

    def _select_target_table_max(self):
        """Get highest point of data stored in target table and store in state.
        Impyla and oracledb both truncate nanoseconds hence TIMESTAMP columns are returned as string.
        optimistic_prune_clause is used to limit the partitions scanned when looking for existing rows:
            If no data is returned then we resort to scanning without the clause
            optimistic_prune_clause is only applicable for single column partition schemes
        Also returns the max value for convenience.

        TODO Ideally we should check frontend system as part of data type check below.
        """
        if not self._target_table_exists():
            return None

        column_names = [_.name for _ in self._partition_columns]
        ts_columns = [
            _.name for _ in self._partition_columns if _.data_type in (ORACLE_TYPE_TIMESTAMP, ORACLE_TYPE_TIMESTAMP_TZ)
        ]
        prune_clause = self._make_rpa_hwm_gte_clause()
        if prune_clause:
            self._messages.event(MAX_QUERY_OPTIMISTIC_PRUNE_CLAUSE)
        t1 = datetime.now().replace(microsecond=0)
        try:
            max_row = self._offload_target_table.get_max_column_values(
                column_names,
                columns_to_cast_to_string=ts_columns,
                optimistic_prune_clause=prune_clause,
            )
        finally:
            t2 = datetime.now().replace(microsecond=0)
            self.log(
                "Elapsed time to retrieve maximum backend partition key data: %s" % (t2 - t1),
                detail=VVERBOSE,
            )
        return self._combine_part_cols_with_values(max_row)

    def _report_source_partitions(self):
        logger.debug("_report_source_partitions")
        assert self._source_partitions
        self.log(f"In {self._col_offload_source_table.frontend_db_name()}:")
        self._source_partitions.report_partitions(
            self._part_offload_source_table.offload_by_subpartition, self._messages
        )

    def _report_offloaded_partitions(self):
        logger.debug("_report_offloaded_partitions")
        assert self._offloaded_partitions
        self.log("Already %s:" % self._terms["past"])
        self._offloaded_partitions.report_partitions(
            self._part_offload_source_table.offload_by_subpartition, self._messages
        )

    def _report_partitions_to_offload(self):
        logger.debug("_report_partitions_to_offload")
        assert self._offloaded_partitions
        self.log("To %s:" % self._terms["name"])
        self._partitions_to_offload.report_partitions(
            self._part_offload_source_table.offload_by_subpartition, self._messages
        )

    def _override_partitions_to_offload(self, new_partitions):
        logger.debug("_override_partitions_to_offload")
        if isinstance(new_partitions, OffloadSourcePartitions):
            self._partitions_to_offload = new_partitions
            self._nothing_to_offload = bool(self._partitions_to_offload.count() == 0)
        elif isinstance(new_partitions, list):
            self._partitions_to_offload.set_partitions(new_partitions)
        else:
            raise NotImplementedError("Unsupported partition override of type: %s" % type(new_partitions))
        return self._partitions_to_offload

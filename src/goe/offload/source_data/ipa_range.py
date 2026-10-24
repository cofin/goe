# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Range and list-as-range Incremental Partition Append (IPA) source-data implementations."""

import re
from datetime import date, datetime
from typing import Any

from numpy import datetime64

from goe.offload import offload_constants
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_metadata_functions import (
    OFFLOAD_TYPE_INCREMENTAL,
)
from goe.offload.offload_source_table import (
    OFFLOAD_PARTITION_TYPE_RANGE,
)
from goe.offload.source_data.base import (
    INVALID_HV_FOR_LIST_AS_RANGE_EXCEPTION_TEXT,
    NO_DEFAULT_PARTITION_NOTICE_TEXT,
    NO_MATCHING_PARTITION_EXCEPTION_TEXT,
    NO_MAXVALUE_PARTITION_NOTICE_TEXT,
    TOO_MANY_PARTITION_NAMES_EXCEPTION_TEXT,
    OffloadSourceDataException,
    OffloadSourceDataInterface,
    OffloadSourcePartitions,
    is_default_partition,
    logger,
)
from goe.persistence.orchestration_metadata import (
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
    INCREMENTAL_PREDICATE_TYPE_RANGE,
)


class OffloadSourceDataIpaRange(OffloadSourceDataInterface):
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
        """CONSTRUCTOR

        cache attributes from offload_operation that we are interested in
        """
        self._user_requested_rpa_filter = offload_operation.less_than_value

        self._partition_append_capable = True
        self._incremental_append_capable = True
        self._partition_append_predicate_type = INCREMENTAL_PREDICATE_TYPE_RANGE

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

        self._rdbms_min = None
        self._rpa_filter = None
        self._rpa_hwm_partition = None

        self.log(
            "Table %s.%s is %s partitioned by %s (%s)"
            % (
                offload_source_table.owner,
                offload_source_table.table_name,
                offload_source_table.partition_type,
                ", ".join([_.data_type for _ in self._partition_columns]),
                ", ".join([_.name for _ in self._partition_columns]),
            ),
            detail=VERBOSE,
        )

    def offload_data_detection(self):
        """Review candidate partitions and filter them by what's already been offloaded and any user requested options
        Report the different partition categories as appropriate and any warnings/notices
        Partitions in each category (offloaded, to offload, etc) are held in state - not returned

        Keep and discard lists are just for reporting. We need to continue with the to-offload partition set after reporting this indicates that all offloaded partitions have been removed from the RDBMS, we may get verification errors
        """
        self._populate_source_partitions_rpa()
        self._report_source_partitions()
        if not self.is_partition_append_capable():
            return

        self._populate_offloaded_partitions()
        if self.offloaded_partitions.count() > 0:
            self._report_offloaded_partitions()

        self._populate_partitions_to_offload()
        self._discard_partitions_using_filters()
        self._nothing_to_offload = bool(self._partitions_to_offload.count() == 0)

        self._set_incremental_high_values()

        if self.partitions_to_offload.count() == 0:
            self.log("No partitions to %s" % self._terms["name"])
        else:
            (
                keep_partitions,
                discard_partitions,
            ) = self.split_partitions_to_offload_by_no_segment()

            self.log("To %s:" % self._terms["name"])
            keep_partitions.report_partitions(self._part_offload_source_table.offload_by_subpartition, self._messages)

            if discard_partitions.count() > 0:
                self.log("To skip (no segments):")
                discard_partitions.report_partitions(
                    self._part_offload_source_table.offload_by_subpartition,
                    self._messages,
                )

            if self.partitions_to_offload.has_maxvalue_partition():
                self._messages.notice(
                    "%s partition %s with high_value of %s"
                    % (
                        self._terms["now"].capitalize(),
                        self.partitions_to_offload.has_maxvalue_partition(),
                        offload_constants.PART_OUT_OF_RANGE,
                    )
                )

            if self._target_table_max and (not self._rdbms_min or self._target_table_max < self._rdbms_min):
                self._messages.warning(
                    "Offloaded data is less than RDBMS data, data verification may fail due to purged historical RDBMS data"
                )

    def get_incremental_high_values(self):
        logger.debug("get_incremental_high_values")
        if self._rpa_hwm_partition:
            return self._rpa_hwm_partition.partition_values_individual
        return []

    def offloading_open_ended_partition(self):
        if not self.partitions_to_offload:
            return False
        return self.partitions_to_offload.has_maxvalue_partition()

    def _check_number_of_partition_append_filters(self, check_tokens):
        assert type(check_tokens) in (list, tuple)
        if len(check_tokens) != len(self._partition_columns):
            raise OffloadSourceDataException(
                "Partition filter %s has incorrect value. %d partition values required"
                % (str(check_tokens), len(self._partition_columns))
            )

    def _convert_string_literal_for_rpa(self, part_col, token):
        return self._col_offload_source_table.char_literal_to_python(token)

    def _normalise_rpa_partition_append_csv(self, csv_str):
        """Breaks up a user specified partition append string and returns a tuple of correctly
        typed Python values ready for comparison with partition_values_python.
        """
        assert isinstance(csv_str, str)
        logger.debug("_normalise_rpa_partition_append_csv")
        tokens = self._col_offload_source_table.split_partition_high_value_string(csv_str)
        pa_list = []
        self._check_number_of_partition_append_filters(tokens)
        for part_col, token in zip(self._partition_columns, tokens):
            try:
                if part_col.is_date_based():
                    pa_list.append(self._datetime_literal_to_python(token))
                elif part_col.is_number_based():
                    converted_token = self._col_offload_source_table.numeric_literal_to_python(token)
                    pa_list.append(converted_token)
                elif part_col.is_string_based():
                    converted_token = self._convert_string_literal_for_rpa(part_col, token)
                    pa_list.append(converted_token)
                else:
                    raise OffloadSourceDataException("Unsupported partition key type: %s" % part_col.data_type)
            except ValueError:
                self.log("Failed to parse %s value: %s" % (part_col.data_type, token))
                raise
        return tuple(pa_list)

    def _normalise_rpa_partition_filter(self, user_requested_less_than_value):
        """Create a standard comparison tuple that can be compared with partition high values
        from the user requested input.
        Also validates that the items in the tuple match the RDBMS columns in both number
        and type.
        """
        logger.debug("_normalise_rpa_partition_filter")
        if isinstance(user_requested_less_than_value, str):
            rpa_filter_tuple = self._normalise_rpa_partition_append_csv(user_requested_less_than_value)
        elif isinstance(user_requested_less_than_value, (list, tuple)):
            rpa_filter_tuple = tuple(user_requested_less_than_value)
        elif isinstance(user_requested_less_than_value, date):
            rpa_filter_tuple = (datetime64(user_requested_less_than_value),)
        else:
            rpa_filter_tuple = (user_requested_less_than_value,)

        self._check_number_of_partition_append_filters(rpa_filter_tuple)

        for part_col, col_val in zip(self._partition_columns, rpa_filter_tuple):
            if part_col.is_date_based() != isinstance(col_val, (datetime64, date)):
                raise OffloadSourceDataException(
                    "Filter %s is incompatible with partition key %s of type %s"
                    % (str(col_val), part_col.name, part_col.data_type)
                )

        logger.debug("final filter: %s" % str(rpa_filter_tuple))
        return rpa_filter_tuple

    def _get_rpa_filter(self):
        logger.debug("_get_ipa_filter")
        if self._rpa_filter is None:
            self._normalise_rpa_filter()
        return self._rpa_filter

    def _normalise_rpa_partition_name(self):
        """Convert a partition name to a HV and then convert that HV to a tuple used for partition filtering
        Locates the partition in _source_partitions so this must be populated
        Doesn't validate the number of partition columns or data types because HV is coming directly from RDBMS data dictionary
        """
        logger.debug("_normalise_rpa_partition_name")
        if len(self._user_requested_partition_names) != 1:
            raise OffloadSourceDataException(
                "%s for %s offloaded table"
                % (
                    TOO_MANY_PARTITION_NAMES_EXCEPTION_TEXT,
                    self._partition_append_predicate_type,
                )
            )

        partition_name = self._user_requested_partition_names[0]
        matched_partition = self._source_partitions.get_partition(partition_name)
        if matched_partition:
            return matched_partition.partition_values_python
        raise OffloadSourceDataException("%s: %s" % (NO_MATCHING_PARTITION_EXCEPTION_TEXT, partition_name))

    def _ida_options_have_been_specified(self):
        if self._user_requested_rpa_filter or self._user_requested_partition_names:
            return True
        return False

    def _normalise_rpa_filter(self):
        if self._user_requested_rpa_filter:
            self._rpa_filter = self._normalise_rpa_partition_filter(self._user_requested_rpa_filter)
        elif self._user_requested_partition_names:
            self._rpa_filter = self._normalise_rpa_partition_name()
        else:
            self._rpa_filter = tuple()
        return self._rpa_filter

    def _rpa_hv_not_offloaded(self, partition):
        match = bool(tuple(partition.partition_values_python) > self._target_table_max)
        self.debug(
            "Partition %s not offloaded check: %s: %s > %s"
            % (
                partition.partition_name,
                match,
                tuple(partition.partition_values_python),
                self._target_table_max,
            )
        )
        return match

    def _rpa_partition_already_offloaded(self, partition, partition_already_marked_offloaded):
        """This method is used to differentiate between true RANGE and LIST_AS_RANGE.
        rdbms_min <= backend_max: If there's data in Oracle older than backend max then current partition must
                                  be offloaded and we'll stop iterating when we find a HWM beyond backend max
        p.partition_values_python <= backend_max: If the HV for current partition is older than backend max then it must
                                                  be offloaded this latter check is required for truncated/empty partitions
        partition_already_marked_offloaded: When looping through partitions the next partition beyond the one with the HV
                                            matching backend data is also offloaded, due to less-than nature of RANGE HV.
        """

        def rpa_hv_already_offloaded(partition):
            match = bool(
                (self._rdbms_min is not None and self._rdbms_min <= self._target_table_max)
                or tuple(partition.partition_values_python) <= self._target_table_max
            )
            self.debug(
                "Partition %s already offloaded check: %s: %s <= %s"
                % (
                    partition.partition_name,
                    bool(tuple(partition.partition_values_python) <= self._target_table_max),
                    tuple(partition.partition_values_python),
                    self._target_table_max,
                )
            )
            self.log(
                "Partition %s already offloaded check: %s" % (partition.partition_name, match),
                detail=VVERBOSE,
            )
            return match

        if partition_already_marked_offloaded:
            self.debug(
                "Partition %s already marked as offloaded: %s"
                % (partition.partition_name, partition_already_marked_offloaded)
            )
        return bool(partition_already_marked_offloaded or rpa_hv_already_offloaded(partition))

    def _rpa_partitions_already_offloaded(self):
        """Return partitions already offloaded based on a HWM and min/max values
        i.e. this is not comparing all partitions but looking for the HWM in the backend and assuming
             all older RDBMS partitions have been offloaded

        We only need oracle_min if there is already data in the backend traverse old to new Reached a partition with a HWM beyond the backend max, therefore time to break out of the loop When offloading by subpartition we may find repeating HWM, gobble up any other partitions of the same HWM There is an assumption here that partitions of matching HWM are contiguous. This will be true of Oracle, we need to be careful when introducing more RDBMSs
        """
        assert self._source_partitions
        already_offloaded: list[Any] = []

        if self._set_target_table_max():
            self._set_rdbms_min()

            self.log("backend_max: " + str(self._target_table_max), detail=VVERBOSE)
            self.log("rdbms_min: " + str(self._rdbms_min), detail=VVERBOSE)

            reversed_offload_partitions = list(reversed(self._source_partitions.get_partitions()))
            for i, p in enumerate(reversed_offload_partitions):
                if self._rpa_partition_already_offloaded(p, bool(already_offloaded)):
                    already_offloaded.append(p)
                if self._rpa_hv_not_offloaded(p):
                    if self._part_offload_source_table.offload_by_subpartition and i < len(reversed_offload_partitions):
                        with_matching_hwm = self._partitions_of_matching_hwm(
                            p.partition_values_python,
                            reversed_offload_partitions[i + 1 :],
                        )
                        if with_matching_hwm:
                            self.log(
                                "Skipping %s partitions with matching HWM" % len(with_matching_hwm),
                                detail=VVERBOSE,
                            )
                            already_offloaded.extend(with_matching_hwm)
                    break
            already_offloaded.reverse()
        return already_offloaded

    def _set_incremental_high_values(self):
        """Identify a HWM partition for a RANGE 90/10 config.
        HWM is filtered HWM or highest partition to be offloaded or what's already been offloaded.
        Filtered HWM is checked against source partitions because the HWM may be positioned anywhere (100/10).
        """
        logger.debug("_set_incremental_high_values")
        if self._rpa_hwm_partition:
            return self._rpa_hwm_partition

        self._rpa_hwm_partition = None
        if self._ida_options_have_been_specified():
            filter_fn = self._get_less_than_rpa_filter_fn()
            filtered_partitions = self._source_partitions.search_by_filter(filter_fn)
            if filtered_partitions:
                self.log(
                    "HWM partition %s derived from HWM filter" % filtered_partitions[0].partition_name,
                    detail=VVERBOSE,
                )
                self._rpa_hwm_partition = filtered_partitions[0]

        if not self._rpa_hwm_partition:
            if self._partitions_to_offload.count() > 0:
                logger.debug("get_hwm_partition from partitions_to_offload")
                self._rpa_hwm_partition = self._partitions_to_offload.get_partition_by_index(0)
            elif self._offloaded_partitions.count() > 0:
                logger.debug("get_hwm_partition from offloaded_partitions")
                self._rpa_hwm_partition = self._offloaded_partitions.get_partition_by_index(0)

        return self._rpa_hwm_partition

    def _check_hwm_is_a_valid_boundary(self, hwm_partition, retained_partitions, offload_type):
        """When RANGE offloading at subpartition level we need to ensure that any HWM for offload is a valid common boundary

        It's a valid HWM and the subpartition offload list is good to be used. It's the last HWM in the table... regardless of the messages and tests above, we don't have a valid HWM so need to stop here
        """
        logger.debug("_check_hwm_is_a_valid_boundary")

        def is_valid_common_boundary(check_partition, retained_partitions_ascending):
            """A valid common boundary is one that is:
            a) a common boundary
            b) not the last HWM in the table (i.e. there are HWMs in the retain set)...
            """
            return bool(
                check_partition.common_partition_literal
                and retained_partitions_ascending
                and check_partition.partition_values_python != retained_partitions_ascending[-1].partition_values_python
            )

        def more_human_readable_python_hwm(python_hwm):
            """convert to str to remove datatype info and chop off any redundant trailing fractional seconds"""
            str_fn = lambda x: re.sub(r"\.000000$", "", str(x)) if type(x) is datetime64 else str(x)
            return str([str_fn(hv) for hv in python_hwm])

        hwm_check_retained = list(reversed(retained_partitions)) if retained_partitions else []
        if is_valid_common_boundary(hwm_partition, hwm_check_retained):
            self.log(
                "Usable common boundary found: %s"
                % more_human_readable_python_hwm(hwm_partition.partition_values_python),
                detail=VVERBOSE,
            )
        else:
            next_common_boundary = None
            for p in hwm_check_retained:
                if p.common_partition_literal:
                    next_common_boundary = p
                    break
            if next_common_boundary and is_valid_common_boundary(next_common_boundary, hwm_check_retained):
                self._messages.warning(
                    "Minimum recommended common boundary is: --less-than-values=%s"
                    % more_human_readable_python_hwm(next_common_boundary.partition_values_python)
                )
            elif offload_type == OFFLOAD_TYPE_INCREMENTAL:
                raise OffloadSourceDataException(
                    "Table is not valid for range subpartition offloading due to incompatible high value boundaries. Offload with --offload-type=FULL"
                )
            if offload_type == OFFLOAD_TYPE_INCREMENTAL:
                if self._get_rpa_filter():
                    raise OffloadSourceDataException(
                        "No common boundary at HWM filter: %s" % more_human_readable_python_hwm(self._get_rpa_filter())
                    )
                raise OffloadSourceDataException(
                    "No common boundary at HWM: %s"
                    % more_human_readable_python_hwm(hwm_partition.partition_values_python)
                )

    def _maxvalue_partition_has_been_offloaded(self):
        logger.debug("_maxvalue_partition_has_been_offloaded")
        assert self._offloaded_partitions
        return self._offloaded_partitions.has_maxvalue_partition()

    def _do_not_offload_maxvalue_partition(self):
        """If there's a MAXVALUE partition to offload then remove it and return the partition object"""
        logger.debug("_do_not_offload_maxvalue_partition")
        if self._part_offload_source_table.partition_type == OFFLOAD_PARTITION_TYPE_RANGE:
            return self._partitions_to_offload.remove_maxvalue_partition()
        return None

    def _get_less_than_rpa_filter_fn(self):
        logger.debug("_get_less_than_rpa_filter_fn")
        less_than_list = self._get_rpa_filter()

        def filter_fn(p):
            try:
                match = bool(tuple(p.partition_values_python) <= tuple(less_than_list))
            except TypeError as exc:
                self.log(
                    f"{p.partition_values_python!s} <= {less_than_list!s} throws: {exc!s}",
                    detail=VERBOSE,
                )
                raise
            self.debug(
                "Matching partition %s (%s <= %s): %s"
                % (
                    p.partition_name,
                    str(p.partition_values_python),
                    str(less_than_list),
                    match,
                )
            )
            return match

        return filter_fn

    def _split_partitions_to_offload_by_rpa_filter(self):
        """Split the partitions to offload by the user filter returning both those to keep and those to discard"""
        logger.debug("_split_partitions_to_offload_by_rpa_filter")
        filter_fn = self._get_less_than_rpa_filter_fn()
        return self._partitions_to_offload.split_partitions(filter_fn)

    def _set_target_table_max(self):
        if not self._target_table_max:
            self._target_table_max = self._select_target_table_max()
        return self._target_table_max

    def _set_rdbms_min(self):
        """Get the RDBMS max values for partition columns and store in state
        Also return the value for convenience
        """
        t1 = datetime.now().replace(microsecond=0)
        self._rdbms_min = None
        try:
            min_row = self._part_offload_source_table.get_minimum_partition_key_data()
        finally:
            t2 = datetime.now().replace(microsecond=0)
            self.log(
                "Elapsed time to retrieve minimum RDBMS partition key data: %s" % (t2 - t1),
                detail=VVERBOSE,
            )
        self._rdbms_min = self._combine_part_cols_with_values(min_row)
        return self._rdbms_min

    def _populate_offloaded_partitions(self):
        """Inspects _source_partitions and populates a new list of offloaded partitions"""
        logger.debug("_populate_offloaded_partitions")
        if not self._offloaded_partitions:
            if not self._target_table_exists():
                self._offloaded_partitions = OffloadSourcePartitions()
            else:
                self._offloaded_partitions = OffloadSourcePartitions(self._rpa_partitions_already_offloaded())

            if self._offload_type == OFFLOAD_TYPE_INCREMENTAL and self._maxvalue_partition_has_been_offloaded():
                raise OffloadSourceDataException(
                    f"Offload type {self._offload_type} invalid when {offload_constants.PART_OUT_OF_RANGE} partition has been offloaded"
                )

        return self._offloaded_partitions

    def _populate_source_partitions_rpa(self):
        self.populate_source_partitions()

    def _do_not_offload_open_ended_partition(self):
        """For INCREMENTAL RANGE do not offload a MAXVALUE partition."""
        removed_maxval_partition = None
        if self._offload_type == OFFLOAD_TYPE_INCREMENTAL and self.partitions_to_offload.has_maxvalue_partition():
            removed_maxval_partition = self._do_not_offload_maxvalue_partition()
        return removed_maxval_partition

    def _do_not_offload_open_ended_partition_notice(self):
        return NO_MAXVALUE_PARTITION_NOTICE_TEXT

    def _discard_partitions_using_filters(self):
        """Apply RPA filters to the list of partitions to be offloaded.

        Ignore filtering and offload all partitions, however we still use filter to define view HWM (100/10 pattern).
        Add the MAXVALUE/DEFAULT partition to the retained list. This call stores the HWM partition in state.
        """
        logger.debug("_discard_partitions_using_filters")

        removed_open_partition = self._do_not_offload_open_ended_partition()

        retained_partition_list = []
        if self._ida_options_have_been_specified():
            (
                filtered_partitions,
                discarded_partitions,
            ) = self._split_partitions_to_offload_by_rpa_filter()
            self.debug("Filter retained %s partitions" % filtered_partitions.count())
            self.debug("Filter discarded %s partitions" % discarded_partitions.count())
            filtered_partition_list = filtered_partitions.as_legacy_list()
            if self._offload_type == OFFLOAD_TYPE_INCREMENTAL:
                self._override_partitions_to_offload(filtered_partitions)
                retained_partition_list = discarded_partitions.get_partitions()
            elif filtered_partition_list:
                self.log(
                    "Offloading all partitions when OFFLOAD_TYPE is %s" % self._offload_type,
                    detail=VERBOSE,
                )

        if removed_open_partition:
            self._messages.notice(
                "Not %s partition %s %s"
                % (
                    self._terms["now"],
                    removed_open_partition.partition_name,
                    self._do_not_offload_open_ended_partition_notice(),
                )
            )
            retained_partition_list.append(removed_open_partition)

        hwm_partition = self._set_incremental_high_values()

        if self.partitions_to_offload.count() > 0 and self._offload_by_subpartition:
            self._check_hwm_is_a_valid_boundary(hwm_partition, retained_partition_list, self._offload_type)


class OffloadSourceDataIpaListAsRange(OffloadSourceDataIpaRange):
    """This is a limited extension of OffloadSourceDataIpaRange used when customers have partitioned Oracle
    by LIST but to mimic RANGE partitioning.
    This class inherits most functionality from Range but with these additions:
        1) RDBMS partitions are sorted by HIGH_VALUE in order to ensure matched RANGE behaviour
        2) HIGH_VALUE logic is changed from <= to < to match RANGE logic
    """

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
        """CONSTRUCTOR

        Cache attributes from offload_operation that we are interested in
        """
        self._user_requested_list_rpa_lte_filter = offload_operation.less_or_equal_value

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

        self._partition_append_predicate_type = INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE
        self._list_rpa_lte_filter = None

    def _check_for_unsupported_partitions(self):
        """For LIST_AS_RANGE we cannot allow any partitions with multiple HVs on a single partition.
        This should be called after populating self._source_partitions.
        """
        assert self._source_partitions

        def filter_fn(p):
            if len(p.partition_values_python) > 1:
                self.debug("Partition has multiple multiple high values: %s" % p.partition_literal)
                return True
            return False

        matching_partitions = self._source_partitions.search_by_filter(filter_fn)
        if matching_partitions:
            raise OffloadSourceDataException(
                "%s: %s"
                % (
                    INVALID_HV_FOR_LIST_AS_RANGE_EXCEPTION_TEXT,
                    [_.partition_name for _ in matching_partitions],
                )
            )

    def _do_not_offload_default_partition(self):
        """If there's a DEFAULT partition to offload then remove it and return the partition name"""
        logger.debug("_do_not_offload_default_partition")
        return self._partitions_to_offload.remove_default_partition()

    def _do_not_offload_open_ended_partition(self):
        """For INCREMENTAL LIST_AS_RANGE do not offload a DEFAULT partition."""
        removed_default_partition = None
        if self._offload_type == OFFLOAD_TYPE_INCREMENTAL and self.partitions_to_offload.has_default_partition():
            removed_default_partition = self._do_not_offload_default_partition()
        return removed_default_partition

    def _do_not_offload_open_ended_partition_notice(self):
        return NO_DEFAULT_PARTITION_NOTICE_TEXT

    def _get_less_than_rpa_filter_fn(self):
        logger.debug("_get_less_than_rpa_filter_fn")
        if self._get_list_rpa_lte_filter():
            lte_list = self._get_list_rpa_lte_filter()
            less_than_list = None
        else:
            lte_list = None
            less_than_list = self._get_rpa_filter()

        def filter_fn(p):
            if is_default_partition(p):
                self.log(
                    f"Rejecting {offload_constants.PART_OUT_OF_LIST} partition {p.partition_name}",
                    detail=VVERBOSE,
                )
                return False
            if less_than_list:
                match = bool(tuple(p.partition_values_python) < tuple(less_than_list))
                self.debug(
                    "Matching partition %s (%s < %s): %s"
                    % (
                        p.partition_name,
                        str(p.partition_values_python),
                        str(less_than_list),
                        match,
                    )
                )
            else:
                match = bool(tuple(p.partition_values_python) <= tuple(lte_list))
                self.debug(
                    "Matching partition %s (%s <= %s): %s"
                    % (
                        p.partition_name,
                        str(p.partition_values_python),
                        str(lte_list),
                        match,
                    )
                )
            return match

        return filter_fn

    def _get_list_rpa_lte_filter(self):
        logger.debug("_list_rpa_lte_filter")
        if self._list_rpa_lte_filter is None:
            self._normalise_list_rpa_lte_filter()
        return self._list_rpa_lte_filter

    def _ida_options_have_been_specified(self):
        if (
            self._user_requested_rpa_filter
            or self._user_requested_partition_names
            or self._user_requested_list_rpa_lte_filter
        ):
            return True
        return False

    def _normalise_list_rpa_lte_filter(self):
        if self._user_requested_list_rpa_lte_filter:
            self._list_rpa_lte_filter = self._normalise_rpa_partition_filter(self._user_requested_list_rpa_lte_filter)
        else:
            self._list_rpa_lte_filter = tuple()
        return self._list_rpa_lte_filter

    def _populate_source_partitions_rpa(self):
        """Populate source_partitions from the source RDBMS.
        For LIST_AS_RANGE we cannot allow any partitions with multiple HVs on a single partitions.
        """
        self.populate_source_partitions(sort_by_hv=True)
        self._check_for_unsupported_partitions()

    def _populate_offloaded_partitions(self):
        """Inspects _source_partitions and populates a new list of offloaded partitions"""
        logger.debug("_populate_offloaded_partitions")
        if not self._offloaded_partitions:
            if self._user_requested_table_reset or not self._target_table_exists():
                self._offloaded_partitions = OffloadSourcePartitions()
            else:
                self._offloaded_partitions = OffloadSourcePartitions(self._rpa_partitions_already_offloaded())

            if self._offload_type == OFFLOAD_TYPE_INCREMENTAL and self._maxvalue_partition_has_been_offloaded():
                raise OffloadSourceDataException(
                    f"Offload type {self._offload_type} invalid when {offload_constants.PART_OUT_OF_RANGE} partition has been offloaded"
                )

        return self._offloaded_partitions

    def _rpa_partition_already_offloaded(self, partition, partition_already_marked_offloaded):
        """This method is used to differentiate between true RANGE and LIST_AS_RANGE.
        We can ignore partition_already_marked_offloaded because LIST_AS_RANGE HVs are like-for-like.
        """
        match = bool(tuple(partition.partition_values_python) <= self._target_table_max)
        self.debug("Partition %s already offloaded check: %s" % (partition.partition_name, match))
        return match

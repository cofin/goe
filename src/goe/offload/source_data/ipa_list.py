# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""List-partitioned Incremental Partition Append (IPA) source-data implementation."""

from datetime import datetime
from typing import Any

from goe.offload import offload_constants
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_metadata_functions import (
    OFFLOAD_TYPE_INCREMENTAL,
    decode_metadata_incremental_high_values_from_metadata,
)
from goe.offload.oracle.oracle_column import (
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_TIMESTAMP_TZ,
)
from goe.offload.source_data.base import (
    INCREMENTAL_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT,
    IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT,
    NO_MATCHING_PARTITION_EXCEPTION_TEXT,
    OffloadSourceDataException,
    OffloadSourceDataInterface,
    OffloadSourcePartitions,
    is_default_partition,
    logger,
)
from goe.persistence.orchestration_metadata import (
    INCREMENTAL_PREDICATE_TYPE_LIST,
)


class OffloadSourceDataIpaList(OffloadSourceDataInterface):
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
        self._user_requested_lpa_filters = offload_operation.equal_to_values

        self._partition_append_capable = True
        self._incremental_append_capable = True
        self._partition_append_predicate_type = INCREMENTAL_PREDICATE_TYPE_LIST

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

        self._lpa_incremental_high_values = None
        self._lpa_partition_filters = None

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

        Keep and discard lists are just for reporting. We need to continue with the to-offload partition set after reporting
        """
        self.populate_source_partitions()
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

            if self.partitions_to_offload.has_default_partition():
                self._messages.notice(
                    "%s partition %s with high_value of %s"
                    % (
                        self._terms["now"].capitalize(),
                        self.partitions_to_offload.has_default_partition(),
                        offload_constants.PART_OUT_OF_LIST,
                    )
                )

    def get_incremental_high_values(self):
        logger.debug("get_incremental_high_values")
        if self._lpa_incremental_high_values:
            return self._lpa_incremental_high_values
        return []

    def offloading_open_ended_partition(self):
        if not self.partitions_to_offload:
            return False
        return self.partitions_to_offload.has_default_partition()

    def _default_partition_has_been_offloaded(self):
        logger.debug("_default_partition_has_been_offloaded")
        assert self._offloaded_partitions
        return self._offloaded_partitions.has_default_partition()

    def _default_partition_has_matching_keys(self, list_of_keys):
        """Return True if an RDBMS DEFAULT partition has keys in list_of_keys."""
        if not list_of_keys:
            return False
        default_partition = self._source_partitions.has_default_partition()
        self.log(
            f"LPA table has {offload_constants.PART_OUT_OF_LIST} partition, fetching partition keys from {offload_constants.PART_OUT_OF_LIST} partition: {default_partition}",
            detail=VVERBOSE,
        )
        keys_in_default = self._get_lpa_keys_for_default_partition(default_partition)
        self.log("LPA keys in open partition: %s" % str(keys_in_default), detail=VVERBOSE)
        matching_keys = [_ for _ in keys_in_default if _ in list_of_keys]
        if matching_keys:
            self.log(
                "LPA keys indicating open partition has been offloaded: %s" % str(matching_keys),
                detail=VVERBOSE,
            )
            return True
        return False

    def _normalise_lpa_partition_append_csv(self, csv_str):
        """Breaks up a user specified partition append string and returns a tuple of correctly
        typed Python values ready for comparison with partition_values_python

        For dates check for human input date formats, don't use RDBMS literal checking For all other data types use RDBMS literal checking
        """
        assert isinstance(csv_str, str)
        logger.debug("_normalise_lpa_partition_append_csv")
        pa_list: Any = []
        if self._partition_columns[0].is_date_based():
            tokens = self._col_offload_source_table.split_partition_high_value_string(csv_str)
            pa_list.extend([self._datetime_literal_to_python(token) for token in tokens])
        else:
            pa_list = self._part_offload_source_table.decode_partition_high_values(csv_str)
        return tuple(pa_list)

    def _get_lpa_partition_filters(self):
        """Create a standard list of comparison tuples that can be compared with partition high values
        from the user requested input
        Also validates that the items in the tuple match the RDBMS column in both number
        and type

        the user request should be a list of csvs find the named partitions and construct a list for comparison with p.partition_values_python
        """
        logger.debug("_get_lpa_partition_filters")

        if self._lpa_partition_filters is None:
            lpa_filter_list = []
            if self._user_requested_lpa_filters:
                logger.debug("filtering by user_requested_lpa_filters: %s" % (self._user_requested_lpa_filters))
                if type(self._user_requested_lpa_filters) not in (list, tuple):
                    raise OffloadSourceDataException(
                        "Invalid type for partition append filter: %s" % type(self._user_requested_lpa_filters)
                    )
                for lpa_filter in self._user_requested_lpa_filters:
                    if isinstance(lpa_filter, str):
                        lpa_filter_list.append(self._normalise_lpa_partition_append_csv(lpa_filter))
                    elif isinstance(lpa_filter, tuple):
                        lpa_filter_list.append(lpa_filter)
                    else:
                        raise OffloadSourceDataException(
                            "Invalid type for partition append filter: %s" % type(lpa_filter)
                        )
            elif self._user_requested_partition_names:
                logger.debug("filtering by user_requested_partition_names")
                for partition_name in self._user_requested_partition_names:
                    matched_partition = self._source_partitions.get_partition(partition_name)
                    if matched_partition:
                        lpa_filter_list.append(matched_partition.partition_values_python)
                    else:
                        raise OffloadSourceDataException(
                            "%s: %s" % (NO_MATCHING_PARTITION_EXCEPTION_TEXT, partition_name)
                        )
            self.debug(f"Final filters: {lpa_filter_list}")
            self._lpa_partition_filters = lpa_filter_list

        return self._lpa_partition_filters

    def _get_lpa_keys_from_target(self):
        """Runs a query getting a list of all backend values for RDBMS partition key"""
        logger.debug("_get_lpa_keys_from_target")
        if not self._partition_columns:
            return []

        column_names = [_.name for _ in self._partition_columns]
        ts_columns = [
            _.name for _ in self._partition_columns if _.data_type in (ORACLE_TYPE_TIMESTAMP, ORACLE_TYPE_TIMESTAMP_TZ)
        ]
        rows = self._offload_target_table.get_distinct_column_values(column_names, columns_to_cast_to_string=ts_columns)
        return self._get_lpa_keys_normalise_rows(self._partition_columns[0], rows)

    def _get_lpa_keys_for_default_partition(self, default_partition_name=None):
        """Gets a list of distinct partition keys in a default partition which we
        use to identify whether the partition has been offloaded or not.

        Use partition_column from _part_offload_source_table and not self._partition_columns because, for join pushdown, it will not contain the correct column name.
        """
        if not default_partition_name:
            default_partition_name = self._source_partitions.has_default_partition()
            if not default_partition_name:
                return []

        partition_column = self._part_offload_source_table.partition_columns[0]
        t1 = datetime.now().replace(microsecond=0)
        try:
            rows = self._part_offload_source_table.get_distinct_column(partition_column.name, default_partition_name)
        finally:
            t2 = datetime.now().replace(microsecond=0)
            self.log(
                "Elapsed time to retrieve distinct RDBMS partition key data: %s" % (t2 - t1),
                detail=VVERBOSE,
            )
        return self._get_lpa_keys_normalise_rows(partition_column, rows)

    def _get_lpa_keys_normalise_rows(self, partition_column, rows):
        to_unicode_fn = lambda s: s.decode("utf_8") if isinstance(s, bytes) else s
        assert partition_column
        if not rows:
            return []
        if partition_column.is_string_based():
            keys = [to_unicode_fn(_[0]) for _ in rows]
        else:
            keys = [_[0] for _ in rows]
        return keys

    def _get_source_partitions_matching_lpa_filters(self):
        """Inspects _source_partitions and returns a new list of partitions matching the user inputs
        This is required for metadata/hybrid view predicates
        """
        logger.debug("_get_source_partitions_matching_lpa_filters")
        lpa_filters = self._get_lpa_partition_filters()
        self.debug("_get_source_partitions_matching_lpa_filters lpa_filters: %s" % str(lpa_filters))
        filter_fn = self._lpa_partition_filter_fn(lpa_filters)
        matching_partitions = self._source_partitions.search_by_filter(filter_fn)
        return matching_partitions

    def _ida_options_have_been_specified(self):
        logger.debug("_ida_options_have_been_specified")
        if self._user_requested_lpa_filters or self._user_requested_partition_names:
            return True
        return False

    def _set_incremental_high_values(self):
        """Identify incremental high values for this offload for a 90/10 config
        Incremental high values means:
          - partitions matching the user requested filters
          - plus what hybrid metadata thinks has been offloaded (in case RDBMS partitions have been dropped)
        Does not add:
          - partitions in process of being offloaded. For FULL it is possible to offload partitions the user
            didn't specify. That's fine but we don't want them in the metadata
        Uses str() around each literal in order to be sure no mix of str/unicode
        De-dupes the final list before sorting

        90/10 and 100/10 - we need to use whatever the user has requested and also metadata This is not good, we have a UNION ALL so MUST have predicates for the IN/NOT IN lists The order shouldn't really matter but we do have processes that check for changed metadata and this at least ensures a no-op update of metadata does not flag up as a change in what's offloaded 100/0 - no incremental values in views or metadata, also ignore any reset hybrid view request
        """

        def get_metadata_list():
            if self._pre_offload_hybrid_metadata:
                (
                    _,
                    _,
                    hv_individual_list,
                ) = decode_metadata_incremental_high_values_from_metadata(
                    self._pre_offload_hybrid_metadata, self._col_offload_source_table
                )
                return hv_individual_list
            return []

        logger.debug("_set_incremental_high_values")
        if self._lpa_incremental_high_values is not None:
            self.debug("Retaining LPA incremental high values: %s" % str(self._lpa_incremental_high_values))
            return self._lpa_incremental_high_values

        if self._pred_for_90_10_in_hybrid_view:
            if self._get_lpa_partition_filters():
                self.debug("new HVs from filtered source partitions")
                matching_list_hvs = [
                    _.partition_values_individual for _ in self._get_source_partitions_matching_lpa_filters()
                ]
            elif self._partitions_to_offload.count() > 0:
                self.debug("new HVs from partitions to offload")
                matching_list_hvs = [
                    _.partition_values_individual for _ in self._partitions_to_offload.get_partitions()
                ]
            else:
                matching_list_hvs = []
            self.debug("matching_list_hvs: %s" % str(matching_list_hvs))

            if self._user_requested_hybrid_view_reset:
                if not matching_list_hvs:
                    raise OffloadSourceDataException("No matching partitions for hybrid view reset")
                metadata_hvs = []
            else:
                metadata_hvs = get_metadata_list()
                self.debug("metadata_hvs: %s" % str(metadata_hvs))

            self._lpa_incremental_high_values = sorted(list(set(matching_list_hvs + metadata_hvs)))
        else:
            self._lpa_incremental_high_values = []

    def _populate_offloaded_partitions(self):
        """Inspects _source_partitions and populates a new list of offloaded partitions

        Add DEFAULT to target_list_keys to indicate it has been offloaded
        """
        logger.debug("_populate_offloaded_partitions")
        if not self._offloaded_partitions:
            if not self._target_table_exists():
                self._offloaded_partitions = OffloadSourcePartitions()
            else:
                target_list_keys = self._get_lpa_keys_from_target()
                self.log("LPA keys in backend: %s" % str(target_list_keys), detail=VVERBOSE)
                if self._source_partitions.has_default_partition():
                    if self._default_partition_has_matching_keys(target_list_keys):
                        default_partition = self._source_partitions.get_default_partition()
                        target_list_keys.append(default_partition.partition_values_python[0])

                def filter_fn(p):
                    """Using any() below because some key values may not exists but if "any" of them are in the backend then the partition has been offloaded"""
                    if any(_ in target_list_keys for _ in p.partition_values_python):
                        self.debug("Partition has been offloaded (i.e. is in backend keys): %s" % p.partition_literal)
                        return True
                    return False

                offloaded_partitions = self._source_partitions.search_by_filter(filter_fn)
                self._offloaded_partitions = OffloadSourcePartitions(offloaded_partitions)

            if self._offload_type == OFFLOAD_TYPE_INCREMENTAL and self._default_partition_has_been_offloaded():
                raise OffloadSourceDataException(
                    "%s: %s"
                    % (
                        INCREMENTAL_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT,
                        self._offload_type,
                    )
                )

        return self._offloaded_partitions

    def _lpa_partition_filter_fn(self, lpa_filters):
        """Returns a function to be used when filtering partitions with p.apply_filter()
        The function first checks if the user is offloading a DEFAULT partition before
        going on to check for other partitions they may have requested. We do it that way
        around to avoid duck typing issues when comparing offload_constants.PART_OUT_OF_LIST with other types
        """

        def filter_fn(p):
            """Check if p is a requested DEFAULT partition User has requested a default partition Check if partition p is a requested partition Partition p isn't in the requested list"""
            if is_default_partition(p):
                upper_fn = lambda s: s.upper() if isinstance(s, str) else s
                if any(
                    upper_fn(list_item) == offload_constants.PART_OUT_OF_LIST
                    for lpa_filter in lpa_filters
                    for list_item in lpa_filter
                ):
                    return True
                return False
            if p.partition_values_python in lpa_filters:
                return True
            return False

        return filter_fn

    def _partitions_to_offload_apply_lpa_filter(self, lpa_filters):
        """Reduce the list of partitions to offload by the user filter
        Default partition processing is a bit gnarly because:
            1) It can be any case
            2) It is a string value but valid in a non-string column
        """
        filter_fn = self._lpa_partition_filter_fn(lpa_filters)
        if lpa_filters:
            self.log("lpa_filters: %s" % str(lpa_filters), detail=VVERBOSE)
            self._partitions_to_offload.apply_filter(filter_fn)

    def _discard_partitions_using_filters(self):
        """Apply LPA filters to the list of partitions to be offloaded"""
        logger.debug("_discard_partitions_using_filters")
        lpa_filters = self._get_lpa_partition_filters()
        self._partitions_to_offload_apply_lpa_filter(lpa_filters)
        if self._offload_type == OFFLOAD_TYPE_INCREMENTAL and self.partitions_to_offload.has_default_partition():
            raise OffloadSourceDataException(
                "%s %s for offload type %s"
                % (
                    IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT,
                    self.partitions_to_offload.has_default_partition(),
                    self._offload_type,
                )
            )
        if self._offload_by_subpartition:
            raise NotImplementedError("LIST subpartition level offload is not supported")

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Predicate-based offload source-data implementation."""

from functools import partial

from goe.offload import predicate_offload
from goe.offload.offload_functions import (
    get_dsl_threshold_clauses,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_metadata_functions import (
    OFFLOAD_TYPE_FULL,
    OFFLOAD_TYPE_INCREMENTAL,
    decode_metadata_incremental_high_values_from_metadata,
)
from goe.offload.source_data.base import (
    LAPBO_TYPE_90_10,
    LAPBO_TYPE_100_0,
    LAPBO_TYPE_100_10,
    OFFLOAD_TYPE_CHANGE_FOR_PBO_EXCEPTION_TEXT,
    PREDICATE_APPEND_HWM_MESSAGE_TEXT,
    PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT,
    PREDICATE_TYPE_NO_MODIFY_HV_EXCEPTION_TEXT,
    PREDICATE_TYPE_NO_MODIFY_RESET_EXCEPTION_TEXT,
    PREDICATE_TYPE_OFFLOAD_TYPE_FULL_EXCEPTION_TEXT,
    PREDICATE_TYPE_REQUIRED_EXCEPTION_TEXT,
    RANGE_AND_PREDICATE_WITHOUT_PART_KEY_EXCEPTION_TEXT,
    OffloadSourceDataException,
    OffloadSourceDataInterface,
    OffloadSourcePartitions,
)
from goe.persistence.models import (
    INCREMENTAL_PREDICATE_TYPE_LIST,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_RANGE,
    INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
)


class OffloadSourceDataPredicate(OffloadSourceDataInterface):
    """Offload data selected by predicate only"""

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
        self._incremental_append_capable = True
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

        self._incremental_hvs = []

        self._messages.log(
            "Predicates (%s) supplied, %s selected rows from %s.%s"
            % (
                offload_operation.offload_predicate.dsl,
                self._terms["now"],
                offload_source_table.owner,
                offload_source_table.table_name,
            ),
            detail=VERBOSE,
        )

    def offload_data_detection(self):
        """Case 3 needs to retain RANGE HVs"""
        self._partitions_to_offload = OffloadSourcePartitions()

        pre_offload_predicate_type = self.get_pre_offload_predicate_type()

        self.debug("pre_offload_predicate_type: %s" % self.get_pre_offload_predicate_type())
        self.debug("user_requested_predicate_type: %s" % self._user_requested_predicate_type)

        if self._offload_predicate_case_1():
            if not self._offload_predicate_modify_hybrid_view:
                raise OffloadSourceDataException(
                    "%s: %s"
                    % (
                        PREDICATE_TYPE_NO_MODIFY_HV_EXCEPTION_TEXT,
                        INCREMENTAL_PREDICATE_TYPE_PREDICATE,
                    )
                )
            if self._user_requested_predicate_type not in (
                None,
                INCREMENTAL_PREDICATE_TYPE_PREDICATE,
            ):
                raise OffloadSourceDataException(
                    "%s: %s"
                    % (
                        PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT,
                        self._user_requested_predicate_type,
                    )
                )

            source_has_rows = self._predicate_has_rows_check(self._offload_predicate)

            self._no_offload_type_full(INCREMENTAL_PREDICATE_TYPE_PREDICATE)

            self._set_post_offload_predicates(source_has_rows)

            self._partition_append_predicate_type = INCREMENTAL_PREDICATE_TYPE_PREDICATE

        elif self._offload_predicate_case_2():
            if self._user_requested_hybrid_view_reset:
                raise OffloadSourceDataException(PREDICATE_TYPE_NO_MODIFY_RESET_EXCEPTION_TEXT)

            if self._offload_predicate_modify_hybrid_view:
                self._offload_predicate_modify_hybrid_view = False
                self.log(
                    "Setting --no-modify-hybrid-view for late arriving predicate offload",
                    detail=VVERBOSE,
                )

            self._post_offload_predicates = self.get_pre_offload_predicates()
            self._partition_append_predicate_type = pre_offload_predicate_type

            (
                hv_columns,
                _,
                self._incremental_hvs,
            ) = decode_metadata_incremental_high_values_from_metadata(
                self._pre_offload_hybrid_metadata, self._col_offload_source_table
            )

            if self._offload_predicate_case_2_type() in (
                LAPBO_TYPE_90_10,
                LAPBO_TYPE_100_10,
            ):
                self.populate_source_partitions()
                target_table_max = self._select_target_table_max()
                max_lt_dsl, _ = get_dsl_threshold_clauses(
                    hv_columns,
                    pre_offload_predicate_type,
                    target_table_max,
                    equality_with_gt=False,
                )
                self._messages.notice("%s: %s" % (PREDICATE_APPEND_HWM_MESSAGE_TEXT, str(max_lt_dsl)))
                hv_col_predicates = [predicate_offload.GenericPredicate(max_lt_dsl)]
                self._inflight_offload_predicate = predicate_offload.create_and_relation_predicate(
                    hv_col_predicates + [self._offload_predicate]
                )
                _ = self._predicate_has_rows_check(self._inflight_offload_predicate)
            else:
                _ = self._predicate_has_rows_check(self._offload_predicate)

        elif self._offload_predicate_case_3():
            if pre_offload_predicate_type == INCREMENTAL_PREDICATE_TYPE_RANGE:
                self._partition_append_predicate_type = INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE
            elif pre_offload_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE:
                self._partition_append_predicate_type = INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE
            else:
                self._partition_append_predicate_type = pre_offload_predicate_type

            source_has_rows = self._predicate_has_rows_check(self._offload_predicate)

            self._no_offload_type_full(self._partition_append_predicate_type)

            if not self._offload_predicate_contains_hwm_cols():
                raise OffloadSourceDataException(RANGE_AND_PREDICATE_WITHOUT_PART_KEY_EXCEPTION_TEXT)

            self._set_post_offload_predicates(source_has_rows)

            (
                _,
                _,
                self._incremental_hvs,
            ) = decode_metadata_incremental_high_values_from_metadata(
                self._pre_offload_hybrid_metadata, self._col_offload_source_table
            )

        elif pre_offload_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST:
            raise OffloadSourceDataException(
                "%s: %s"
                % (
                    PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT,
                    pre_offload_predicate_type,
                )
            )

        else:
            self.log(
                "pre_offload_predicate_type: %s" % pre_offload_predicate_type,
                detail=VVERBOSE,
            )
            self.log(
                "offload_predicate_modify_hybrid_view: %s" % self._offload_predicate_modify_hybrid_view,
                detail=VVERBOSE,
            )
            if pre_offload_predicate_type in (
                INCREMENTAL_PREDICATE_TYPE_RANGE,
                INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
            ):
                raise OffloadSourceDataException(
                    f"{PREDICATE_TYPE_REQUIRED_EXCEPTION_TEXT}: {pre_offload_predicate_type}"
                )
            raise OffloadSourceDataException("Incompatible --offload-predicate options")

    def get_incremental_high_values(self):
        return self._incremental_hvs

    def offloading_open_ended_partition(self):
        return False

    def _ida_options_have_been_specified(self):
        return bool(self._offload_predicate and not self._offload_predicate_case_2())

    def _no_offload_type_full(self, predicate_type):
        if self._user_requested_offload_type == OFFLOAD_TYPE_FULL or self._offload_type == OFFLOAD_TYPE_FULL:
            raise OffloadSourceDataException(
                "%s: %s" % (PREDICATE_TYPE_OFFLOAD_TYPE_FULL_EXCEPTION_TEXT, predicate_type)
            )

    def _offload_predicate_case_1(self):
        case_1 = bool(
            not self._pre_offload_hybrid_metadata
            or self.get_pre_offload_predicate_type() == INCREMENTAL_PREDICATE_TYPE_PREDICATE
        )
        if case_1:
            self.log(
                "Pre-offload predicate type is case 1: %s" % self.get_pre_offload_predicate_type(),
                detail=VVERBOSE,
            )
        return case_1

    def _offload_predicate_case_2_type(self):
        """Take OFFLOAD_TYPE from metadata and not self._offload_type because this method is used to set it. Cannot have LAPBO if there's no pre-offload metadata If the predicate type remains the same"""
        case_2_predicate_types = (
            INCREMENTAL_PREDICATE_TYPE_RANGE,
            INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
        )
        pre_offload_offload_type = self._get_pre_offload_offload_type()
        pre_offload_inc_key = self._get_pre_offload_incremental_key()

        if not self._pre_offload_hybrid_metadata:
            return None
        if (
            pre_offload_offload_type == OFFLOAD_TYPE_INCREMENTAL
            and self.get_pre_offload_predicate_type() in case_2_predicate_types
            and self._user_requested_predicate_type == self.get_pre_offload_predicate_type()
        ):
            return LAPBO_TYPE_90_10
        if (
            pre_offload_offload_type == OFFLOAD_TYPE_FULL
            and pre_offload_inc_key is not None
            and self.get_pre_offload_predicate_type() in case_2_predicate_types
            and self._user_requested_predicate_type == self.get_pre_offload_predicate_type()
        ):
            return LAPBO_TYPE_100_10
        if pre_offload_offload_type == OFFLOAD_TYPE_FULL and pre_offload_inc_key is None:
            return LAPBO_TYPE_100_0
        return None

    def _offload_predicate_case_2(self):
        """In theory we could support switching OFFLOAD_TYPE during PBO but in practice we choose not to."""
        lapbo_type = self._offload_predicate_case_2_type()
        case_2 = bool(lapbo_type)
        if case_2:
            pre_offload_offload_type = self._get_pre_offload_offload_type()
            if (
                self._user_requested_offload_type
                and pre_offload_offload_type
                and self._user_requested_offload_type != pre_offload_offload_type
            ):
                raise OffloadSourceDataException(OFFLOAD_TYPE_CHANGE_FOR_PBO_EXCEPTION_TEXT)

            self.log(
                "Pre-offload/user requested predicate type is case 2 (%s late arriving data): %s/%s"
                % (
                    lapbo_type,
                    self.get_pre_offload_predicate_type(),
                    self._user_requested_predicate_type,
                ),
                detail=VVERBOSE,
            )
        return case_2

    def _offload_predicate_case_3(self):
        case_3 = bool(
            (
                self.get_pre_offload_predicate_type()
                in (
                    INCREMENTAL_PREDICATE_TYPE_RANGE,
                    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
                )
                and self._user_requested_predicate_type
                in (
                    INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
                    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
                )
            )
            or self.get_pre_offload_predicate_type()
            in (
                INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
                INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
            )
        )
        if case_3:
            self.log(
                "Pre-offload/user requested predicate type is case 3 (intra day): %s/%s"
                % (
                    self.get_pre_offload_predicate_type(),
                    self._user_requested_predicate_type,
                ),
                detail=VVERBOSE,
            )
        return case_3

    def _offload_predicate_contains_hwm_cols(self):
        """all HWM columns must have a corresponding predicate, and optionally the value must be < hwm"""

        def is_column_predicate(column_name, tree):
            if len(tree.children) == 2:
                lhs, rhs = tree.children
                if lhs.data == "column" and lhs.children[-1] == column_name.upper():
                    return True
                if rhs.data == "column" and rhs.children[-1] == column_name.upper():
                    return True
            return False

        (
            hv_columns,
            hv_values,
            hv_sql_exprs,
        ) = decode_metadata_incremental_high_values_from_metadata(
            self._pre_offload_hybrid_metadata, self._col_offload_source_table
        )
        return all(
            list(self._offload_predicate.ast.find_pred(partial(is_column_predicate, hv_col.name)))
            for hv_col, hv in zip(hv_columns, hv_values)
        )

    def _offload_predicate_in_pre_offload_metadata(self):
        return bool(self._offload_predicate.dsl in (self.get_pre_offload_predicates(as_dsl=True) or []))

    def _predicate_has_rows_check(self, offload_predicate):
        """Returns True if the predicate matches data to Offload

        This is a new predicate but it matches previously offloaded data
        """
        source_has_rows = self._part_offload_source_table.predicate_has_rows(offload_predicate)
        source_where_clause = self._part_offload_source_table.predicate_to_where_clause(offload_predicate)

        if self._user_requested_table_reset:
            dest_has_rows = False
        else:
            dest_has_rows = self._offload_target_table.predicate_has_rows(offload_predicate)

        if not source_has_rows:
            self._nothing_to_offload = True
            self.log("No rows in source:\n%s\nNo data to offload." % source_where_clause)
        elif dest_has_rows:
            self._nothing_to_offload = True
            if self._offload_predicate_in_pre_offload_metadata():
                self.log("Already %s:\n%s" % (self._terms["past"], source_where_clause))
            else:
                self.log("Already %s (overlap):\n%s" % (self._terms["past"], source_where_clause))
        else:
            self.log("To %s:\n%s" % (self._terms["name"], source_where_clause))
        return source_has_rows

    def _set_post_offload_predicates(self, source_has_rows):
        """Keep the same values we had before"""
        if self._user_requested_hybrid_view_reset:
            self._post_offload_predicates = [self._offload_predicate]
        elif (self.nothing_to_offload() and not source_has_rows) or not self._offload_predicate_modify_hybrid_view:
            self._post_offload_predicates = self.get_pre_offload_predicates()
        elif not self._offload_predicate_in_pre_offload_metadata():
            self._post_offload_predicates = (self.get_pre_offload_predicates() or []) + [self._offload_predicate]
        else:
            self._post_offload_predicates = self.get_pre_offload_predicates()

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""General functions for use in Offload.

Ideally these would migrate to better locations in time.
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from goe.exceptions import OffloadException
from goe.offload import offload_constants
from goe.offload.offload_messages import VVERBOSE, OffloadMessages
from goe.offload.offload_metadata_functions import (
    decode_metadata_incremental_high_values_from_metadata,
    incremental_key_csv_from_part_keys,
)
from goe.offload.offload_source_data import offload_source_data_factory
from goe.offload.offload_source_table import (
    OFFLOAD_PARTITION_TYPE_LIST,
)
from goe.offload.operation.ddl_file import write_ddl_to_ddl_file
from goe.offload.operation.sort_columns import check_and_alter_backend_sort_columns
from goe.offload.option_validation import (
    active_data_append_options,
    check_ipa_predicate_type_option_conflicts,
    check_opt_is_posint,
)
from goe.offload.registry import create_source_table
from goe.orchestration import command_steps
from goe.persistence.orchestration_metadata import (
    INCREMENTAL_PREDICATE_TYPE_LIST,
    INCREMENTAL_PREDICATE_TYPES_WITH_PREDICATE_IN_HV,
    hwm_column_names_from_predicates,
)

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.goe import OffloadOperation
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.offload_source_data import OffloadSourceDataInterface
    from goe.offload.offload_source_table import OffloadSourceTableInterface
    from goe.persistence.orchestration_repo_client import (
        OrchestrationRepoClientInterface,
    )


def create_ddl_file_step(
    offload_target_table: "BackendTableInterface",
    offload_operation: "OffloadOperation",
    config: "OrchestrationConfig",
    messages: OffloadMessages,
) -> None:
    """Create a DDL file for the final backend table."""
    if not offload_operation.ddl_file:
        return

    def step_fn():
        ddl = []
        if offload_operation.create_backend_db and offload_target_table.create_database_supported():
            ddl.extend(offload_target_table.create_db(with_terminator=True))
            ddl.extend(offload_target_table.create_load_db(with_terminator=True))
        ddl.extend(offload_target_table.create_backend_table(with_terminator=True))
        assert offload_operation.ddl_file is not None
        write_ddl_to_ddl_file(offload_operation.ddl_file, ddl, config, messages)

    messages.offload_step(command_steps.STEP_DDL_FILE, step_fn, execute=False)


def create_final_backend_table_step(
    offload_target_table: "BackendTableInterface",
    offload_operation: "OffloadOperation",
) -> None:
    """Create the final backend table."""
    if not offload_target_table.table_exists() or offload_operation.reset_backend_table:
        offload_target_table.create_backend_table_step()
    else:
        check_and_alter_backend_sort_columns(offload_target_table, offload_operation)


def drop_backend_table_step(
    owner: str,
    table_name: str,
    backend_table: "BackendTableInterface",
    messages: OffloadMessages,
    repo_client: "OrchestrationRepoClientInterface",
    execute: Any,
    purge: bool = False,
) -> None:
    def step_fn():
        """Also remove any metadata attached to the table"""
        if backend_table.table_exists():
            backend_table.drop_table(purge=purge)
        repo_client.drop_offload_metadata(owner, table_name)

    messages.offload_step(command_steps.STEP_DROP_TABLE, step_fn, execute=execute)


def get_current_offload_hv(
    offload_source_table: "OffloadSourceTableInterface",
    source_data_client: "OffloadSourceDataInterface",
    offload_operation: Any,
    messages: OffloadMessages,
) -> Any:
    """Identifies the HV for an IPA offload
    If there are partitions in flight then we can use those otherwise we will fall back to using pre-offload metadata
    Returns a list of length 2 containing:
      [RDBMS hv literals, python hv equivalents]

    we are offloading partitions so use the latest one from that list, this works for verification mode too
    if no partitions in flight then get metadata in order to understand HWM
    """
    new_hvs = None

    if source_data_client.partitions_to_offload.count() > 0:
        if offload_operation.ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST:
            hvs_individual, hvs_python = [], []
            for p in source_data_client.partitions_to_offload.get_partitions():
                hvs_individual.append(p.partition_values_individual)
                hvs_python.append(p.partition_values_python)
            new_hvs = [hvs_individual, hvs_python]
        else:
            max_partition = source_data_client.partitions_to_offload.get_partition_by_index(0)
            new_hvs = [
                max_partition.partition_values_individual,
                max_partition.partition_values_python,
            ]
        messages.log(
            "Identified new_hvs from partitions_to_offload: %s" % str(new_hvs),
            detail=VVERBOSE,
        )
    elif offload_operation.offload_type == "INCREMENTAL" and not offload_operation.reset_backend_table:
        current_metadata = offload_operation.get_hybrid_metadata()
        (
            _,
            _,
            partition_literal_hvs,
        ) = decode_metadata_incremental_high_values_from_metadata(current_metadata, offload_source_table)
        new_hvs = [partition_literal_hvs, partition_literal_hvs]
        messages.log("Identified new_hvs from metadata: %s" % str(new_hvs), detail=VVERBOSE)

    return new_hvs


def get_prior_offloaded_hv(
    rdbms_table: "OffloadSourceTableInterface",
    source_data_client: "OffloadSourceDataInterface",
    offload_operation: Any,
    messages: OffloadMessages,
) -> Any:
    """Identifies the HV for a RANGE offload of the partition prior to the offload
    If there is pre-offload metadata we can use that otherwise we need to go back to the list of partitions

    use metadata to get the prior high value
    we haven't gotten values from metadata so let's look at the partition list for the prior HV
    """
    prior_hvs = None

    if (
        offload_operation
        and offload_operation.pre_offload_hybrid_metadata
        and offload_operation.pre_offload_hybrid_metadata.incremental_high_value
    ):
        messages.log("Assigning prior_hv from pre-offload metadata", detail=VVERBOSE)
        (
            _,
            real_hvs,
            literal_hvs,
        ) = decode_metadata_incremental_high_values_from_metadata(
            offload_operation.pre_offload_hybrid_metadata, rdbms_table
        )
        messages.log("pre-offload metadata real values: %s" % str(real_hvs), detail=VVERBOSE)
        messages.log(
            "pre-offload metadata rdbms literals: %s" % str(literal_hvs),
            detail=VVERBOSE,
        )
        prior_hvs = [literal_hvs, real_hvs]

    if not prior_hvs and source_data_client:
        min_offloaded_partition = source_data_client.partitions_to_offload.get_partition_by_index(-1)
        if min_offloaded_partition:
            messages.log(
                "Searching original partitions for partition prior to: %s"
                % str(min_offloaded_partition.partition_values_python),
                detail=VVERBOSE,
            )
            prior_partition = source_data_client.source_partitions.get_prior_partition(
                partition=min_offloaded_partition
            )
            if prior_partition:
                prior_hvs = [
                    prior_partition.partition_values_individual,
                    prior_partition.partition_values_python,
                ]

    messages.log("Found prior_hvs: %s" % str(prior_hvs), detail=VVERBOSE)
    return prior_hvs


def get_offload_data_manager(
    offload_source_table: "OffloadSourceTableInterface",
    offload_target_table: "BackendTableInterface",
    offload_operation: "OffloadOperation",
    offload_options: Any,
    messages: OffloadMessages,
    existing_metadata: Any,
    source_client_type: Any,
    partition_columns: Any = None,
    include_col_offload_source_table: bool = False,
) -> "OffloadSourceDataInterface":
    """Return a source data manager object which has methods for slicing and dicing RDBMS partitions and state
    containing which partitions to offload and data to construct hybrid view/verification predicates

    "not offload_target_table.is_view()" because we pass through here for presented joins too and do not expect previous metadata
    """
    if (
        offload_target_table.exists()
        and not offload_target_table.is_view()
        and not offload_operation.reset_backend_table
    ):
        messages.log("Pre-offload metadata: " + str(existing_metadata), detail=VVERBOSE)

    if include_col_offload_source_table and existing_metadata:
        col_offload_source_table_override = create_source_table(
            existing_metadata.hybrid_owner,
            existing_metadata.hybrid_view,
            offload_options,
            messages,
            offload_by_subpartition=offload_source_table.offload_by_subpartition,
        )
    else:
        col_offload_source_table_override = None

    source_data_client = offload_source_data_factory(
        offload_source_table,
        offload_target_table,
        offload_operation,
        existing_metadata,
        messages,
        source_client_type,
        rdbms_partition_columns_override=partition_columns,
        col_offload_source_table_override=col_offload_source_table_override,
    )

    source_data_client.offload_data_detection()

    return source_data_client


def offload_backend_db_message(messages: OffloadMessages, db_type: Any, backend_table: Any, execute_mode: Any) -> None:
    """Construct messages when backend databases do not exists.
    Either throw exception in execute mode or output warnings in preview mode.

    Stop here to avoid subsequent exception further along the process
    """
    if backend_table.create_database_supported():
        message = (
            "Offload %s does not exist or is incomplete, please create it or include --create-backend-db option"
            % db_type
        )
    else:
        message = "Offload %s does not exist or is incomplete, please create it before re-executing command" % db_type
    if execute_mode:
        raise OffloadException(message)
    messages.warning(message, ansi_code="red")


def offload_type_force_effects(
    hybrid_operation: "OffloadOperation",
    source_data_client: "OffloadSourceDataInterface",
    original_metadata: Any,
    offload_source_table: "OffloadSourceTableInterface",
    messages: OffloadMessages,
) -> None:
    """Once we have switched to FULL we cannot trust the HWM with subpartition offloads,

    what if another HWM appeared for already offloaded HWM!
    We're switching OFFLOAD_TYPE for a LIST table, this is tricky for the user because we don't know the correct
    INCREMENTAL_HIGH_VALUE value for metadata/hybrid view. So best we can do is try to alert them.
    """
    if source_data_client.is_incremental_append_capable():
        original_offload_type = original_metadata.offload_type
        new_offload_type = hybrid_operation.offload_type
        if hybrid_operation.offload_by_subpartition and (
            original_offload_type,
            new_offload_type,
        ) == ("FULL", "INCREMENTAL"):
            raise OffloadException(offload_constants.OFFLOAD_TYPE_CHANGE_FOR_SUBPART_EXCEPTION_TEXT)

        if hybrid_operation.ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST and (
            original_offload_type,
            new_offload_type,
        ) == ("FULL", "INCREMENTAL"):
            active_lpa_opts = active_data_append_options(hybrid_operation, partition_type=OFFLOAD_PARTITION_TYPE_LIST)
            if active_lpa_opts:
                messages.notice(
                    "%s, only the partitions identified by %s will be queried from offloaded data"
                    % (
                        offload_constants.OFFLOAD_TYPE_CHANGE_FOR_LIST_MESSAGE_TEXT,
                        active_lpa_opts[0],
                    )
                )
            else:
                raise OffloadException(offload_constants.OFFLOAD_TYPE_CHANGE_FOR_LIST_EXCEPTION_TEXT)

        if not hybrid_operation.force:
            new_inc_key = None
            original_inc_key = original_metadata.incremental_key
            if hybrid_operation.hwm_in_hybrid_view and source_data_client.get_incremental_high_values():
                new_inc_key = incremental_key_csv_from_part_keys(offload_source_table.partition_columns)

            original_pred_cols, new_pred_cols = None, None
            if hybrid_operation.ipa_predicate_type in INCREMENTAL_PREDICATE_TYPES_WITH_PREDICATE_IN_HV:
                original_pred_cols = original_metadata.hwm_column_names()
                new_pred_cols = hwm_column_names_from_predicates(source_data_client.get_post_offload_predicates())

            if original_offload_type != new_offload_type:
                messages.notice(
                    'Enabling force option when switching OFFLOAD_TYPE ("%s" -> "%s")'
                    % (original_offload_type, new_offload_type)
                )
                hybrid_operation.force = True
            elif original_inc_key != new_inc_key:
                messages.notice(
                    'Enabling force option when switching INCREMENTAL_KEY ("%s" -> "%s")'
                    % (original_inc_key, new_inc_key)
                )
                hybrid_operation.force = True
            elif original_pred_cols != new_pred_cols and not source_data_client.nothing_to_offload():
                messages.notice(
                    'Enabling force option when columns in INCREMENTAL_PREDICATE_VALUE change ("%s" -> "%s")'
                    % (original_pred_cols, new_pred_cols)
                )
                hybrid_operation.force = True


def normalise_less_than_options(options, exc_cls=OffloadException):
    """We mustn't be in offload so should just drop out

    move the value into less_than_value
    """
    if not hasattr(options, "older_than_date"):
        return

    active_pa_opts = active_data_append_options(options, from_options=True)
    if len(active_pa_opts) > 1:
        raise exc_cls(
            "%s: %s"
            % (
                offload_constants.CONFLICTING_DATA_ID_OPTIONS_EXCEPTION_TEXT,
                ", ".join(active_pa_opts),
            )
        )

    if options.reset_hybrid_view and len(active_pa_opts) == 0:
        raise exc_cls(offload_constants.RESET_HYBRID_VIEW_EXCEPTION_TEXT)

    if options.older_than_date:
        try:
            options.less_than_value = parse_yyyy_mm_dd(options.older_than_date)
            options.older_than_date = None
        except ValueError as exc:
            raise exc_cls("option --older-than-date: %s" % str(exc))
    elif options.older_than_days:
        options.older_than_days = check_opt_is_posint("--older-than-days", options.older_than_days, allow_zero=True)
        options.less_than_value = datetime.today() - timedelta(options.older_than_days)
        options.older_than_days = None

    check_ipa_predicate_type_option_conflicts(options, exc_cls=exc_cls)


def parse_yyyy_mm_dd(ds):
    return datetime.strptime(ds, "%Y-%m-%d")

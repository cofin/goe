# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Offload data verification, operation logic, and target table orchestration entrypoints."""

from typing import TYPE_CHECKING, Any

from goe.exceptions import OffloadException, OffloadOptionError
from goe.filesystem.goe_dfs import (
    OFFLOAD_FS_SCHEME_INHERIT,
)
from goe.filesystem.goe_dfs_factory import get_dfs_from_options
from goe.offload import offload_constants
from goe.offload.factory.backend_table_factory import (
    backend_table_factory,
    get_backend_table_from_metadata,
)
from goe.offload.factory.offload_transport_factory import offload_transport_factory
from goe.offload.offload import (
    create_ddl_file_step,
    create_final_backend_table_step,
    drop_backend_table_step,
    get_current_offload_hv,
    get_offload_data_manager,
    get_prior_offloaded_hv,
    offload_backend_db_message,
    offload_type_force_effects,
)
from goe.offload.offload_functions import convert_backend_identifier_case, data_db_name
from goe.offload.offload_messages import (
    VERBOSE,
    VVERBOSE,
    OffloadMessages,
)
from goe.offload.offload_metadata_functions import gen_and_save_offload_metadata
from goe.offload.offload_source_data import (
    OFFLOAD_SOURCE_CLIENT_OFFLOAD,
)
from goe.offload.offload_source_table import (
    OffloadSourceTableInterface,
)
from goe.offload.offload_transport import (
    choose_offload_transport_method,
    validate_offload_transport_method,
)
from goe.offload.offload_validation import (
    BackendCountValidator,
    CrossDbValidator,
    build_verification_clauses,
)
from goe.offload.operation.data_type_controls import (
    offload_source_to_canonical_mappings,
)
from goe.offload.operation.partition_controls import (
    derive_partition_digits,
)
from goe.offload.operation.table_structure_checks import check_table_structure
from goe.offload.operation.transport import (
    offload_data_to_target,
)
from goe.orchestration import command_steps, logging_init
from goe.orchestration.constants import (
    RETAINING_PARTITITON_FUNCTIONS_MESSAGE_TEXT,
)
from goe.orchestration.logging_init import version_abort
from goe.orchestration.operation import (
    OffloadOperation,
    check_and_set_nls_lang,
    get_default_location_fs_scheme,
)
from goe.persistence.orchestration_metadata import (
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
    INCREMENTAL_PREDICATE_TYPE_RANGE,
)

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.offload_source_data import OffloadSourceDataInterface


def incremental_offload_partition_overrides(offload_operation, existing_part_digits, messages):
    if existing_part_digits and existing_part_digits != offload_operation.synthetic_partition_digits:
        offload_operation.synthetic_partition_digits = existing_part_digits
        messages.notice("Retaining partition digits from backend target (ignoring --partition-digits)")
    if offload_operation.offload_partition_columns:
        messages.notice("Retaining partition column scheme from backend target (ignoring --partition-columns)")
    if offload_operation.offload_partition_functions:
        messages.notice(f"{RETAINING_PARTITITON_FUNCTIONS_MESSAGE_TEXT} (ignoring --partition-functions)")


def verify_offload_by_backend_count(
    offload_source_table,
    offload_target_table,
    offload_operation,
    messages,
    verification_hvs,
    prior_hvs,
    inflight_offload_predicate=None,
):
    """Verify (by row counts) the data offloaded in the current operation.
    For partitioned tables the partition columns and verification_hvs and prior_hvs are used to limit
    scanning to the relevant data in both frontend abd backend.

    TODO NJ@2017-03-15 We need a second set of backend filters for synthetic partition keys (GOE-790)
    """
    ipa_predicate_type = offload_operation.ipa_predicate_type
    verify_parallelism = offload_operation.verify_parallelism
    validator = BackendCountValidator(
        offload_source_table,
        offload_target_table,
        messages,
        dry_run=bool(not offload_operation.execute),
    )
    bind_predicates = bool(
        ipa_predicate_type in [INCREMENTAL_PREDICATE_TYPE_RANGE, INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE]
    )
    frontend_filters, query_binds = build_verification_clauses(
        offload_source_table,
        ipa_predicate_type,
        verification_hvs,
        prior_hvs,
        inflight_offload_predicate,
        with_binds=bind_predicates,
    )
    backend_filters, _ = build_verification_clauses(
        offload_source_table,
        ipa_predicate_type,
        verification_hvs,
        prior_hvs,
        inflight_offload_predicate,
        with_binds=False,
        backend_table=offload_target_table,
    )
    query_hint_block = offload_source_table.enclose_query_hints(
        offload_source_table.parallel_query_hint(verify_parallelism)
    )
    num_diff, source_rows, hybrid_rows = validator.validate(
        frontend_filters,
        query_binds,
        backend_filters,
        frontend_hint_block=query_hint_block,
    )
    return num_diff, source_rows, hybrid_rows


def verify_row_count_by_aggs(
    offload_source_table,
    offload_target_table,
    offload_operation,
    options,
    messages,
    verification_hvs,
    prior_hvs,
    inflight_offload_predicate=None,
):
    """Light verification by running aggregate queries in both Oracle and backend
    and comparing their results

    TODO NJ@2017-03-15 We need a second set of backend filters for Hadoop partition keys (GOE-790)
    """
    ipa_predicate_type = offload_operation.ipa_predicate_type
    verify_parallelism = offload_operation.verify_parallelism
    validator = CrossDbValidator(
        db_name=offload_source_table.owner,
        table_name=offload_source_table.table_name,
        connection_options=options,
        backend_obj=offload_target_table.get_backend_api(),
        messages=messages,
        backend_db=offload_target_table.db_name,
        backend_table=offload_target_table.table_name,
        execute=offload_operation.execute,
    )

    bind_predicates = bool(
        ipa_predicate_type in [INCREMENTAL_PREDICATE_TYPE_RANGE, INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE]
    )
    frontend_filters, query_binds = build_verification_clauses(
        offload_source_table,
        ipa_predicate_type,
        verification_hvs,
        prior_hvs,
        inflight_offload_predicate,
        with_binds=bind_predicates,
    )
    backend_filters, _ = build_verification_clauses(
        offload_source_table,
        ipa_predicate_type,
        verification_hvs,
        prior_hvs,
        inflight_offload_predicate,
        with_binds=False,
        backend_table=offload_target_table,
    )
    status, _ = validator.validate(
        safe=False,
        filters=backend_filters,
        execute=offload_operation.execute,
        frontend_filters=frontend_filters,
        frontend_query_params=query_binds,
        frontend_parallelism=verify_parallelism,
    )
    return status


def offload_data_verification(
    offload_source_table: OffloadSourceTableInterface,
    offload_target_table: "BackendTableInterface",
    offload_operation: OffloadOperation,
    offload_options: "OrchestrationConfig",
    messages: OffloadMessages,
    source_data_client: "OffloadSourceDataInterface",
) -> None:
    """Verify offloaded data by either rowcount or sampling aggregation functions.
    Boundary conditions used to verify only those partitions offloaded by the current operation.

    Let's add query boundary conditions Leave prior_hvs unset for LIST because we don't have a lower bound
    """
    new_hvs = None
    prior_hvs = None
    if source_data_client.is_partition_append_capable():
        offloading_open_ended_partition = source_data_client.offloading_open_ended_partition()
        if source_data_client.get_partition_append_predicate_type() in [
            INCREMENTAL_PREDICATE_TYPE_RANGE,
            INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
        ]:
            if source_data_client.partitions_to_offload.count() > 0:
                prior_hv_tuple = get_prior_offloaded_hv(
                    offload_source_table,
                    source_data_client,
                    offload_operation,
                    messages,
                )
                if prior_hv_tuple:
                    prior_hvs = prior_hv_tuple[1]

        if offloading_open_ended_partition:
            messages.log(
                "MAXVALUE/DEFAULT partition was offloaded therefore cannot add upper bound to verification query",
                detail=VVERBOSE,
            )
        else:
            new_hv_tuple = get_current_offload_hv(offload_source_table, source_data_client, offload_operation, messages)
            if new_hv_tuple:
                new_hvs = new_hv_tuple[1]

    if offload_operation.verify_row_count == "minus":
        verify_fn = lambda: verify_offload_by_backend_count(
            offload_source_table,
            offload_target_table,
            offload_operation,
            messages,
            new_hvs,
            prior_hvs,
            inflight_offload_predicate=source_data_client.get_inflight_offload_predicate(),
        )
        verify_by_count_results = messages.offload_step(
            command_steps.STEP_VERIFY_EXPORTED_DATA,
            verify_fn,
            execute=offload_operation.execute,
        )
        if offload_operation.execute and verify_by_count_results:
            num_diff, source_rows, hybrid_rows = verify_by_count_results
            if num_diff == 0:
                messages.log(
                    f"Source and {offload_target_table.backend_db_name()} table data matches: offload successful"
                    + (" (with warnings)" if messages.get_warnings() else ""),
                    ansi_code="green",
                )
                messages.log(
                    "%s origin_rows, %s backend_rows" % (source_rows, hybrid_rows),
                    detail=VERBOSE,
                )
            else:
                raise OffloadException(
                    "Source and Hybrid mismatch: %s differences, %s origin_rows, %s backend_rows"
                    % (num_diff, source_rows, hybrid_rows)
                )
    else:
        verify_fn = lambda: verify_row_count_by_aggs(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            new_hvs,
            prior_hvs,
            inflight_offload_predicate=source_data_client.get_inflight_offload_predicate(),
        )
        if messages.offload_step(
            command_steps.STEP_VERIFY_EXPORTED_DATA,
            verify_fn,
            execute=offload_operation.execute,
        ):
            messages.log(
                "Source and target table data matches: offload successful%s"
                % (" (with warnings)" if messages.get_warnings() else ""),
                ansi_code="green",
            )
        else:
            raise OffloadException("Source and target mismatch")


def offload_operation_logic(
    offload_operation: OffloadOperation,
    offload_source_table: OffloadSourceTableInterface,
    offload_target_table: "BackendTableInterface",
    offload_options: "OrchestrationConfig",
    source_data_client: "OffloadSourceDataInterface",
    existing_metadata: Any,
    messages: OffloadMessages,
) -> bool:
    """Logic defining what will be offloaded and what the final objects will look like
    There's a lot goes on in here but one key item to note is there are 2 distinct routes through:
    1) The table either is new or is being reset, we take on board lots of options to define the final table
    2) The table already exists and we are adding data, many options are ignored to remain consistent with the target table

    Cache some source data attributes in offload_operation to carry through rest of offload logic Drop out early We are creating a fresh table and therefore don't need to concern ourselves with existing structure Need to add partition information after we've tuned operation settings The backend table already exists therefore some options should be ignored/defaulted For incremental append offload we ignore user data type controls, let them know they are being ignored here If the user tried to influence the fs scheme for the table then we should tell them we're ignoring the attempt There's a user defined transport method and we now have enough information to fully check it
    """

    if offload_operation.reset_backend_table and not offload_operation.force:
        messages.log("Enabling force mode based on --reset-backend-table", detail=VVERBOSE)
        offload_operation.force = True

    offload_operation.offload_type = source_data_client.get_offload_type()
    offload_operation.hwm_in_hybrid_view = source_data_client.pred_for_90_10_in_hybrid_view()
    incr_append_capable = source_data_client.is_incremental_append_capable()

    if existing_metadata:
        offload_type_force_effects(
            offload_operation,
            source_data_client,
            existing_metadata,
            offload_source_table,
            messages,
        )

    if source_data_client.nothing_to_offload():
        return False

    if not offload_target_table.exists() or offload_operation.reset_backend_table:
        canonical_columns = messages.offload_step(
            command_steps.STEP_ANALYZE_DATA_TYPES,
            lambda: offload_source_to_canonical_mappings(
                offload_source_table,
                offload_target_table,
                offload_operation,
                offload_options.not_null_propagation,
                messages,
            ),
            execute=offload_operation.execute,
            mandatory_step=True,
        )

        offload_operation.defaults_for_fresh_offload(
            offload_source_table, offload_options, messages, offload_target_table
        )

        canonical_columns = offload_operation.set_partition_info_on_canonical_columns(
            canonical_columns, offload_source_table.columns, offload_target_table
        )
        backend_columns = offload_target_table.convert_canonical_columns_to_backend(canonical_columns)

        offload_target_table.set_columns(backend_columns)
    else:
        existing_part_digits = derive_partition_digits(offload_target_table)
        incremental_offload_partition_overrides(offload_operation, existing_part_digits, messages)
        offload_operation.unicode_string_columns_csv = offload_target_table.derive_unicode_string_columns(as_csv=True)

        if incr_append_capable:
            if offload_operation.gen_canonical_overrides(
                offload_target_table, columns_override=offload_source_table.columns
            ):
                messages.notice(
                    "Retaining column data types from original offload (any data type control options are ignored)"
                )

            if offload_operation.not_null_columns_csv:
                messages.notice("Retaining NOT NULL columns from original offload (ignoring --not-null-columns)")

            if (
                offload_options.offload_fs_scheme
                and offload_options.offload_fs_scheme != OFFLOAD_FS_SCHEME_INHERIT
                and get_default_location_fs_scheme(offload_target_table)
                not in (offload_options.offload_fs_scheme, None)
            ):
                messages.notice(
                    "Original table filesystem scheme will be used for new partitions (ignoring --offload-fs-scheme, using %s)"
                    % get_default_location_fs_scheme(offload_target_table)
                )

    offload_operation.validate_sort_columns(
        offload_source_table,
        messages,
        offload_options,
        offload_target_table.get_columns(),
        existing_metadata,
        backend_api=offload_target_table.get_backend_api(),
    )
    if offload_operation.offload_transport_method:
        validate_offload_transport_method(
            offload_operation.offload_transport_method,
            offload_options,
            offload_operation=offload_operation,
            offload_source_table=offload_source_table,
            messages=messages,
        )

    if offload_target_table.exists() and offload_target_table.has_rows() and not offload_operation.reset_backend_table:
        if incr_append_capable:
            if source_data_client.nothing_to_offload():
                return False
        else:
            messages.notice(
                offload_constants.TARGET_HAS_DATA_MESSAGE_TEMPLATE
                % (offload_target_table.db_name, offload_target_table.table_name)
            )
            return False

    return True


def offload_table(
    offload_options: "OrchestrationConfig",
    offload_operation: OffloadOperation,
    offload_source_table: OffloadSourceTableInterface,
    offload_target_table: "BackendTableInterface",
    messages: OffloadMessages,
) -> bool:
    """As of GOE-2334 we only support BigQuery as a target. We need to pickup defaults for an existing table here, BEFORE we start looking for data to offload (get_offload_data_manager()). Call validate_offload_by_subpartition early so we can switch it on before any partition related information is requested. The ipa_predicate_type checks are intertwined with offload_by_subpartition. Write ipa_predicate_type back to operation in case the source_data_client has defined a new one. source_data_client may modify offload-predicate provided as input, this variable contains those changes for transport and verification. We need to set defaults for a fresh offload here, AFTER get_offload_data_manager() has decided what type of offload we'll do. This happens inside offload_operation_logic(). For a fresh offload we may have tuned offload_operation attributes For DDL file creation we need to drop out early, before we concern ourselves with database creation or table drop commands. Pre-offload SCN will be stored in metadata. Only run verification if data has been transferred"""
    if offload_options.db_type == offload_constants.DBTYPE_ORACLE:
        abort, v_goe, v_ora = version_abort(offload_operation.ver_check, offload_source_table.get_frontend_api())
        if abort:
            raise OffloadException(
                "Mismatch between Oracle component version (" + v_ora + ") and binary version (" + v_goe + ")"
            )

    if offload_options.target != offload_constants.DBTYPE_BIGQUERY:
        OffloadException(f"Unsupported Offload target: {offload_options.target}")
    logging_init.suppress_stdout_override = True if messages.verbosity == 3 else False

    offload_options.override_offload_dfs_config(
        offload_operation.offload_fs_scheme,
        offload_operation.offload_fs_container,
        offload_operation.offload_fs_prefix,
    )
    offload_options.check_backend_support(offload_target_table.get_backend_api())
    repo_client = offload_operation.repo_client

    if offload_target_table.identifier_contains_invalid_characters(offload_operation.target_owner_name.split(".")[0]):
        messages.warning(
            "Unsupported character(s) %s in Oracle schema name. Use --target-name to specify a compatible backend database name."
            % offload_target_table.identifier_contains_invalid_characters(
                offload_operation.target_owner_name.split(".")[0]
            )
        )
        if offload_operation.execute:
            raise OffloadOptionError("Unsupported character(s) in Oracle schema name.")

    if not offload_source_table.columns:
        messages.log(
            "No columns found for table: %s.%s" % (offload_source_table.owner, offload_source_table.table_name)
        )
        return False

    if not offload_source_table.check_data_types_supported(
        offload_target_table.max_datetime_scale(),
        offload_target_table.nan_supported(),
        offload_operation.allow_nanosecond_timestamp_columns,
        offload_operation.allow_floating_point_conversions,
    ):
        return False

    if not offload_operation.create_backend_db:
        if not offload_target_table.db_exists():
            offload_backend_db_message(
                messages,
                "target database %s" % offload_target_table.db_name,
                offload_target_table,
                offload_operation.execute,
            )
        if not offload_target_table.staging_area_exists():
            offload_backend_db_message(
                messages,
                "staging area",
                offload_target_table,
                offload_operation.execute,
            )

    existing_metadata: Any = None
    if offload_target_table.exists() and not offload_operation.reset_backend_table:
        existing_metadata = offload_operation.defaults_for_existing_table(offload_target_table, messages)
        check_table_structure(offload_source_table, offload_target_table, messages)
        offload_target_table.refresh_operational_settings(offload_operation, rdbms_columns=offload_source_table.columns)

    offload_operation.default_ipa_predicate_type(offload_source_table, messages)
    offload_operation.validate_offload_by_subpartition(offload_source_table, messages, existing_metadata)
    offload_operation.validate_ipa_predicate_type(offload_source_table)

    if not offload_target_table.is_valid_staging_format():
        raise OffloadException(
            "OFFLOAD_STAGING_FORMAT is not valid for backend system %s: %s"
            % (
                offload_target_table.backend_type(),
                offload_options.offload_staging_format,
            )
        )

    source_data_client: "OffloadSourceDataInterface" = messages.offload_step(
        command_steps.STEP_FIND_OFFLOAD_DATA,
        lambda: get_offload_data_manager(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            existing_metadata,
            OFFLOAD_SOURCE_CLIENT_OFFLOAD,
        ),
        execute=offload_operation.execute,
        mandatory_step=True,
    )

    offload_operation.ipa_predicate_type = source_data_client.get_partition_append_predicate_type()

    offload_operation.inflight_offload_predicate = source_data_client.get_inflight_offload_predicate()

    if not offload_operation_logic(
        offload_operation,
        offload_source_table,
        offload_target_table,
        offload_options,
        source_data_client,
        existing_metadata,
        messages,
    ):
        return False

    offload_operation.offload_transport_method = choose_offload_transport_method(
        offload_operation, offload_source_table, offload_options, messages
    )
    dfs_client = get_dfs_from_options(offload_options, messages, dry_run=(not offload_operation.execute))

    offload_target_table.refresh_operational_settings(
        offload_operation,
        rdbms_columns=offload_source_table.columns,
    )

    if offload_operation.ddl_file:
        create_ddl_file_step(offload_target_table, offload_operation, offload_options, messages)
        return True

    if offload_operation.create_backend_db:
        offload_target_table.create_backend_db_step()

    if offload_operation.reset_backend_table:
        drop_backend_table_step(
            offload_source_table.owner,
            offload_source_table.table_name,
            offload_target_table,
            messages,
            repo_client,
            offload_operation.execute,
            purge=offload_operation.purge_backend_table,
        )

    rows_offloaded = None

    create_final_backend_table_step(offload_target_table, offload_operation)

    data_transport_client = offload_transport_factory(
        offload_operation.offload_transport_method,
        offload_source_table,
        offload_target_table,
        offload_operation,
        offload_options,
        messages,
        dfs_client,
    )

    pre_offload_snapshot = None
    if offload_options.db_type == offload_constants.DBTYPE_ORACLE:
        pre_offload_snapshot = data_transport_client.get_transport_snapshot()

    offload_target_table.set_final_table_casts(
        offload_source_table.columns,
        data_transport_client.get_staging_file().get_staging_columns(),
    )
    offload_target_table.setup_staging_area_step(data_transport_client.get_staging_file())

    rows_offloaded = offload_data_to_target(
        data_transport_client,
        offload_source_table,
        offload_target_table,
        offload_operation,
        offload_options,
        source_data_client,
        messages,
    )
    messages.log(
        "%s: %s" % (offload_constants.TOTAL_ROWS_OFFLOADED_LOG_TEXT, str(rows_offloaded)),
        detail=VVERBOSE,
    )

    if not offload_operation.preserve_load_table:
        offload_target_table.cleanup_staging_area_step()

    new_metadata = gen_and_save_offload_metadata(
        repo_client,
        messages,
        offload_operation,
        offload_options,
        offload_source_table,
        offload_target_table,
        offload_source_table.partition_columns,
        source_data_client.get_incremental_high_values(),
        source_data_client.get_post_offload_predicates(),
        pre_offload_snapshot,
        existing_metadata,
    )
    offload_operation.reset_hybrid_metadata(new_metadata)

    if offload_operation.verify_row_count:
        if rows_offloaded != 0:
            offload_data_verification(
                offload_source_table,
                offload_target_table,
                offload_operation,
                offload_options,
                messages,
                source_data_client,
            )
        else:
            messages.log("Skipped data verification, no data was transferred", detail=VERBOSE)

    return True


def get_offload_target_table(offload_operation, offload_options, messages, metadata_override=None):
    check_and_set_nls_lang(offload_options, messages)
    existing_metadata = metadata_override or offload_operation.get_hybrid_metadata()
    if existing_metadata:
        backend_table = get_backend_table_from_metadata(
            existing_metadata,
            offload_options,
            messages,
            offload_operation=offload_operation,
        )
        if (backend_table.db_name, backend_table.table_name) != (
            offload_operation.target_owner,
            offload_operation.target_name,
        ):
            messages.log(
                "Re-using backend table name from metadata: %s.%s" % (backend_table.db_name, backend_table.table_name),
                detail=VVERBOSE,
            )

    else:
        db_name = data_db_name(offload_operation.target_owner, offload_options)
        db_name, table_name = convert_backend_identifier_case(offload_options, db_name, offload_operation.target_name)
        if (db_name, table_name) != (
            offload_operation.target_owner,
            offload_operation.target_name,
        ):
            messages.log(
                f"{offload_constants.ADJUSTED_BACKEND_IDENTIFIER_MESSAGE_TEXT}: {db_name}.{table_name}",
                detail=VVERBOSE,
            )
        backend_table = backend_table_factory(
            db_name,
            table_name,
            offload_options.target,
            offload_options,
            messages,
            orchestration_operation=offload_operation,
        )
    return backend_table

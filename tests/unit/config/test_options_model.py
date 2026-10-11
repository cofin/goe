# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for the typed option models in goe.config.options."""

import pytest

from goe.config.options import (
    EXPECTED_OFFLOAD_ARGS,
    LISTENER_OFFLOAD_CSV_ALIASES,
    LISTENER_OFFLOAD_RENAME_ALIASES,
    AggValidateOptions,
    CommonOptions,
    ConnectOptions,
    OffloadOperationOptions,
    SchemaSyncOptions,
    StatusReportOptions,
    TableOperationOptions,
)
from goe.exceptions import OffloadOptionError, OptionValueError
from goe.goe import EXPECTED_OFFLOAD_ARGS as GOE_EXPECTED_OFFLOAD_ARGS
from goe.goe import normalise_owner_table_options
from goe.offload import offload_status_report, offload_validation


def test_option_value_error_is_offload_option_error() -> None:
    """OptionValueError is an alias of OffloadOptionError."""
    assert OptionValueError is OffloadOptionError
    with pytest.raises(OffloadOptionError):
        raise OptionValueError("invalid option")


def test_expected_offload_args_match_orchestration_contract() -> None:
    """EXPECTED_OFFLOAD_ARGS holds the 85 ordered keys accepted by OffloadOperation."""
    assert len(EXPECTED_OFFLOAD_ARGS) == 85
    assert len(set(EXPECTED_OFFLOAD_ARGS)) == 85
    assert EXPECTED_OFFLOAD_ARGS == tuple(GOE_EXPECTED_OFFLOAD_ARGS)


def test_listener_alias_tables() -> None:
    """Listener alias tables map REST alias fields onto canonical keys."""
    assert LISTENER_OFFLOAD_RENAME_ALIASES == {
        "target_table_name": "target_owner_name",
        "bucket_hash_column": "bucket_hash_col",
        "offload_chunk_count": "max_offload_chunk_count",
        "allow_floating_point": "allow_floating_point_conversions",
        "compress_backend_table": "compress_load_table",
        "replace_hybrid_view": "reset_hybrid_view",
    }
    assert LISTENER_OFFLOAD_CSV_ALIASES == {
        "partitions": "partition_names_csv",
        "sort_columns": "sort_columns_csv",
        "partition_functions": "offload_partition_functions",
    }
    assert set(LISTENER_OFFLOAD_RENAME_ALIASES.values()) | set(LISTENER_OFFLOAD_CSV_ALIASES.values()) <= set(
        EXPECTED_OFFLOAD_ARGS
    )


def test_offload_struct_covers_expected_offload_args() -> None:
    """Every EXPECTED_OFFLOAD_ARGS key is a field of OffloadOperationOptions."""
    assert set(EXPECTED_OFFLOAD_ARGS) <= set(OffloadOperationOptions.__struct_fields__)


def test_environment_defaults_are_evaluated_per_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment-backed defaults are read when each struct is instantiated."""
    monkeypatch.setenv("OFFLOAD_LOGDIR", "/tmp/goe_logs_a")
    monkeypatch.setenv("QUERY_ENGINE", "BIGQUERY")
    assert CommonOptions().log_path == "/tmp/goe_logs_a"
    assert TableOperationOptions().target == "bigquery"
    monkeypatch.setenv("OFFLOAD_LOGDIR", "/tmp/goe_logs_b")
    assert CommonOptions().log_path == "/tmp/goe_logs_b"


def test_structs_reject_unknown_keys_and_attributes() -> None:
    """Structs refuse undeclared keys and attributes instead of silently storing them."""
    with pytest.raises(TypeError):
        ConnectOptions.from_mapping({"not_an_option": 1})
    opts = SchemaSyncOptions()
    with pytest.raises(AttributeError):
        opts.not_an_option = 1


def test_owner_table_normalisation_populates_derived_fields() -> None:
    """normalise_owner_table_options can populate the declared derived fields."""
    opts = AggValidateOptions(owner_table="SH.SALES")
    normalise_owner_table_options(opts)
    assert (opts.owner, opts.table_name) == ("SH", "SALES")
    assert (opts.target_owner, opts.target_name) == ("SH", "SALES")
    assert (opts.base_owner, opts.base_name) == ("SH", "SALES")


def test_literal_defaults_track_their_source_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Literal defaults stay equal to the constants they mirror."""
    monkeypatch.delenv("OFFLOAD_HOME", raising=False)
    report = StatusReportOptions()
    assert report.output_format == offload_status_report.DEFAULT_OUTPUT_FORMAT
    assert report.output_level == offload_status_report.DEFAULT_OUTPUT_LEVEL
    assert report.report_name == offload_status_report.DEFAULT_REPORT_NAME
    assert report.report_directory == offload_status_report.DEFAULT_REPORT_DIRECTORY
    assert report.csv_delimiter == offload_status_report.DEFAULT_CSV_DELIMITER
    assert report.csv_enclosure == offload_status_report.DEFAULT_CSV_ENCLOSURE
    assert report.demo_mode == offload_status_report.DEFAULT_DEMO_MODE
    validate = AggValidateOptions()
    assert validate.selects == [offload_validation.DEFAULT_SELECT_COLS]
    assert validate.aggregate_functions == offload_validation.DEFAULT_AGGS


def test_to_dict_returns_every_field() -> None:
    """to_dict returns a plain dict containing every declared field."""
    opts = OffloadOperationOptions(owner_table="SH.SALES", execute=True)
    as_dict = opts.to_dict()
    assert set(as_dict) == set(OffloadOperationOptions.__struct_fields__)
    assert as_dict["owner_table"] == "SH.SALES"
    assert as_dict["execute"] is True

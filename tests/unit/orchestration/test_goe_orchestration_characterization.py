# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Characterization tests for orchestration helpers in goe.orchestration."""

import pytest

from goe.config.options import OffloadOperationOptions
from goe.exceptions import OffloadOptionError
from goe.orchestration.constants import (
    NLS_LANG_MISSING_CHARACTER_SET_EXCEPTION_TEMPLATE,
    OFFLOAD_OP_NAME,
)
from goe.orchestration.logging_init import strict_version_ready
from goe.orchestration.stages.plan_resolution import (
    nls_lang_exists,
    nls_lang_has_charset,
    normalise_options,
    option_is_in_list,
    valid_canonical_decimal_spec,
    verify_json_option,
)


@pytest.fixture
def bigquery_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the query engine so normalise_options is deterministic."""
    monkeypatch.setenv("QUERY_ENGINE", "BIGQUERY")


def test_constants() -> None:
    """Message constants keep their values."""
    assert OFFLOAD_OP_NAME == "offload"
    assert (
        NLS_LANG_MISSING_CHARACTER_SET_EXCEPTION_TEMPLATE % "X"
        == "NLS_LANG value X missing character set delimiter (.)"
    )


def test_normalise_options_derives_and_normalises(bigquery_env: None) -> None:
    """normalise_options derives owner/table fields and normalises case and lists."""
    opts = OffloadOperationOptions(
        owner_table="SH.SALES",
        skip="Step_A,STEP_B",
        storage_compression="snappy",
        vverbose=True,
        reset_backend_table=True,
        execute=False,
    )
    normalise_options(opts)
    assert (opts.owner, opts.table_name) == ("SH", "SALES")
    assert (opts.target_owner, opts.target_name) == ("SH", "SALES")
    assert opts.skip == ["step_a", "step_b"]
    assert opts.storage_compression == "SNAPPY"
    assert opts.verbose is True
    assert opts.force is False


def test_normalise_options_rejects_conflicting_table_actions(bigquery_env: None) -> None:
    """Reset and reuse of the backend table cannot be combined."""
    opts = OffloadOperationOptions(owner_table="SH.SALES", reset_backend_table=True, reuse_backend_table=True)
    with pytest.raises(OffloadOptionError):
        normalise_options(opts)


def test_option_is_in_list() -> None:
    """option_is_in_list upper-cases valid values and rejects others."""
    opts = OffloadOperationOptions(offload_type="full")
    assert option_is_in_list(opts, "offload_type", "--offload-type", ["FULL", "INCREMENTAL"]) == "FULL"
    opts.offload_type = "bogus"
    with pytest.raises(OffloadOptionError):
        option_is_in_list(opts, "offload_type", "--offload-type", ["FULL", "INCREMENTAL"])


def test_pure_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Version, decimal-spec, NLS and JSON helpers keep their behavior."""
    assert strict_version_ready("6.0.1-RC") == "6.0.1"
    assert valid_canonical_decimal_spec(10, 2, 38, 37) is True
    assert valid_canonical_decimal_spec(10, 11, 38, 37) is False
    monkeypatch.setenv("NLS_LANG", "AMERICAN_AMERICA.AL32UTF8")
    assert nls_lang_exists() == "AMERICAN_AMERICA.AL32UTF8"
    assert nls_lang_has_charset() is True
    verify_json_option("--offload-transport-spark-properties", '{"spark.executor.cores": 2}')
    with pytest.raises(OffloadOptionError):
        verify_json_option("--offload-transport-spark-properties", "{not json")

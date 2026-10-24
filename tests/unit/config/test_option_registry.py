# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the declarative OptionSpec registry and OffloadOptions structs."""

from __future__ import annotations

import msgspec
import pytest

from goe.config.option_registry import (
    OPTION_GROUPS,
    OPTION_SPECS,
    OptionSpec,
    get_option_spec,
    get_option_specs_for_group,
    listener_alias_map,
    options_for_command,
)
from goe.config.options import OffloadOptions, TestModeFaults
from goe.exceptions import ValidationError


def test_option_specs_have_unique_names_and_cli_flags() -> None:
    """Every OptionSpec has a unique canonical name and non-overlapping CLI flags."""
    assert len(OPTION_SPECS) > 0
    seen_names: set[str] = set()
    seen_flags: set[str] = set()
    for spec in OPTION_SPECS:
        assert isinstance(spec, OptionSpec)
        assert spec.name not in seen_names, f"Duplicate OptionSpec name: {spec.name}"
        seen_names.add(spec.name)
        assert len(spec.cli_flags) > 0
        for flag in spec.cli_flags:
            assert flag.startswith("-"), f"Invalid CLI flag {flag} on {spec.name}"
            assert flag not in seen_flags, f"Duplicate CLI flag {flag} on {spec.name}"
            seen_flags.add(flag)


def test_removed_legacy_options_are_absent_from_registry() -> None:
    """Legacy options removed in PRD 5 are absent from OPTION_SPECS."""
    removed_names = {
        "create_frontend_db",
        "impala_insert_hint",
        "less_than_value",
        "not_VERIFY",
    }
    registered_names = {spec.name for spec in OPTION_SPECS}
    assert registered_names.isdisjoint(removed_names)


def test_option_groups_and_lookup_helpers() -> None:
    """OPTION_GROUPS, get_option_spec, options_for_command, and listener_alias_map work consistently."""
    table_spec = get_option_spec("table")
    assert table_spec is not None
    assert "-t" in table_spec.cli_flags
    assert "--table" in table_spec.cli_flags
    assert get_option_spec("nonexistent_option_xyz") is None

    common_specs = get_option_specs_for_group("common")
    common_names = {spec.name for spec in common_specs}
    assert {
        "execute",
        "verbose",
        "quiet",
        "ansi",
        "otel_enabled",
        "otel_service_name",
        "otel_exporter_protocol",
        "otel_endpoint",
        "otel_sample_ratio",
    }.issubset(common_names)
    assert OPTION_GROUPS["common"] == common_specs

    offload_specs = options_for_command("offload")
    assert any(spec.name == "table" for spec in offload_specs)
    assert all(not spec.deprecated for spec in offload_specs)

    aliases = listener_alias_map()
    assert aliases["owner_table"] == "table"
    assert aliases["reset_Target_table"] == "reset_backend_table"


def test_offload_options_owner_and_table_parsing() -> None:
    """OffloadOptions parses owner.table and respects preserve_case."""
    opts = OffloadOptions.from_mapping({"owner_table": "sh.sales", "execute": True})
    assert opts.owner == "SH"
    assert opts.table_name == "SALES"
    assert opts.execute is True

    preserved = OffloadOptions.from_mapping({"table": "MixedOwner.MixedTable", "preserve_case": True})
    assert preserved.owner == "MixedOwner"
    assert preserved.table_name == "MixedTable"

    with pytest.raises(ValidationError):
        OffloadOptions.from_mapping({"table": "INVALID_TABLE_WITHOUT_DOT"})


def test_offload_options_and_test_mode_faults_immutability() -> None:
    """OffloadOptions and TestModeFaults are frozen structs that reject mutation and invalid choices."""
    opts = OffloadOptions(table="SH.SALES")
    with pytest.raises(AttributeError):
        opts.execute = True  # type: ignore[misc]

    faults = TestModeFaults(enabled=True)
    with pytest.raises(AttributeError):
        faults.enabled = False  # type: ignore[misc]

    assert isinstance(msgspec.to_builtins(opts), dict)

    with pytest.raises(ValidationError):
        OffloadOptions.from_mapping({"table": "SH.SALES", "offload_type": "INVALID_TYPE"})

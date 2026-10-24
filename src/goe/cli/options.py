# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OptionSpec-driven Click option builders for GOE CLI commands."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

import rich_click as click

from goe.config.option_registry import (
    OptionGroupName,
    OptionSpec,
    get_option_specs_for_group,
    options_for_command,
)

__all__ = [
    "apply_option_specs",
    "build_click_options",
    "column_transform_options",
    "common_options",
    "partition_options",
    "table_target_options",
    "transport_options",
]


def build_click_options(specs: Sequence[OptionSpec]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Build a Click decorator from an ordered sequence of OptionSpec definitions."""

    def decorator[F: Callable[..., Any]](func: F) -> F:
        wrapped: Any = func
        for spec in reversed(specs):
            option_kwargs: dict[str, Any] = {
                "default": spec.default,
                "help": spec.help_text,
            }
            if spec.is_flag:
                option_kwargs["is_flag"] = True
            if spec.is_multiple:
                option_kwargs["multiple"] = True
            if spec.choices is not None:
                option_kwargs["type"] = click.Choice(list(spec.choices), case_sensitive=False)
            if spec.env_var is not None:
                option_kwargs["envvar"] = spec.env_var
            wrapped = click.option(*spec.cli_flags, spec.name, **option_kwargs)(wrapped)
        return cast(F, wrapped)

    return decorator


def apply_option_specs(
    command_name: str,
    *,
    groups: Sequence[OptionGroupName] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach OptionSpec entries registered for command_name, optionally filtered by group."""
    specs = options_for_command(command_name)
    if groups is not None:
        allowed = set(groups)
        specs = tuple(spec for spec in specs if spec.group in allowed)
    return build_click_options(specs)


def common_options[F: Callable[..., Any]](func: F) -> F:
    """Attach common CLI options from the canonical OptionSpec registry."""
    return cast(F, build_click_options(get_option_specs_for_group("common"))(func))


def table_target_options[F: Callable[..., Any]](func: F) -> F:
    """Attach table target options from the canonical OptionSpec registry."""
    return cast(F, build_click_options(get_option_specs_for_group("table_target"))(func))


def partition_options[F: Callable[..., Any]](func: F) -> F:
    """Attach partitioning options from the canonical OptionSpec registry."""
    return cast(F, build_click_options(get_option_specs_for_group("partitioning"))(func))


def transport_options[F: Callable[..., Any]](func: F) -> F:
    """Attach transport options from the canonical OptionSpec registry."""
    return cast(F, build_click_options(get_option_specs_for_group("transport"))(func))


def column_transform_options[F: Callable[..., Any]](func: F) -> F:
    """Attach column transformation options from the canonical OptionSpec registry."""
    return cast(F, build_click_options(get_option_specs_for_group("column_transform"))(func))

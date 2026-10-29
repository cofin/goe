# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for pure string, case-conversion, CSV, and redaction utilities."""

from goe.util.string_utils import (
    camel_to_snake,
    redact_text,
    snake_to_camel,
    split_csv,
    truncate_middle,
)


def test_snake_and_camel_case_conversions() -> None:
    """snake_to_camel and camel_to_snake convert identifier casing deterministically."""
    assert snake_to_camel("offload_execution_id") == "offloadExecutionId"
    assert snake_to_camel("alreadyCamel") == "alreadyCamel"
    assert snake_to_camel("single") == "single"
    assert camel_to_snake("offloadExecutionId") == "offload_execution_id"
    assert camel_to_snake("HTTPResponseCode") == "http_response_code"


def test_split_csv_and_truncate_middle() -> None:
    """split_csv strips whitespace/empty items and truncate_middle preserves head/tail context."""
    assert split_csv(" a , b,, c ") == ["a", "b", "c"]
    assert split_csv("") == []
    assert split_csv(None) == []
    assert truncate_middle("short", max_length=10) == "short"
    truncated = truncate_middle("abcdefghijklmnopqrstuvwxyz", max_length=11)
    assert len(truncated) == 11
    assert truncated.startswith("abcd")
    assert truncated.endswith("xyz")


def test_redact_text_masks_sensitive_tokens() -> None:
    """redact_text masks all non-empty sensitive tokens in text."""
    raw = "connect user/secret_pass@db with token=top_secret"
    redacted = redact_text(raw, ["secret_pass", "top_secret", ""])
    assert "secret_pass" not in redacted
    assert "top_secret" not in redacted
    assert "***" in redacted

# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Pure string, identifier case-conversion, CSV, numeric formatting, and redaction utilities."""

from __future__ import annotations

import datetime
import decimal
import getpass
import inspect
import logging
import math
import os
import random
import re
import string
import uuid
from base64 import b64encode
from collections.abc import Callable, Iterable, Iterator, Sequence
from copy import copy
from hashlib import md5
from pathlib import Path
from typing import Any

from goe.util import GOEVersion, goe_version

__all__ = [
    "LINUX_FILE_NAME_LENGTH_LIMIT",
    "MAX_SUPPORTED_PRECISION",
    "REGEX_FALSE",
    "REGEX_NONE",
    "REGEX_TRUE",
    "GOEVersion",
    "add_prefix_in_same_case",
    "add_suffix_in_same_case",
    "all_int_chars",
    "ansi_c_string_safe",
    "backtick_sandwich",
    "begin_with",
    "bytes_to_human_size",
    "camel_to_snake",
    "case_insensitive_in",
    "chunk_list",
    "csv_split",
    "csvkv_to_dict",
    "double_quote_sandwich",
    "end_by",
    "format_json_list",
    "format_list_for_logging",
    "get_decimal_precision_and_scale",
    "get_integral_part_magnitude",
    "get_option",
    "get_os_username",
    "get_temp_path",
    "goe_version",
    "human_size_to_bytes",
    "id_generator",
    "is_number",
    "is_pos_int",
    "is_power_of_10",
    "isclose",
    "match_case",
    "nvl",
    "obscure_list_items",
    "parse_python_from_string",
    "plural",
    "rdbms_max_descriptor_length",
    "redact_text",
    "remove_chars",
    "set_goelib_logging",
    "snake_to_camel",
    "split_csv",
    "split_not_in_quotes",
    "standard_file_name",
    "standard_log_name",
    "str_floatlike",
    "str_summary_of_self",
    "substitute_in_same_case",
    "surround",
    "timedelta_to_str",
    "to_bytes",
    "to_str",
    "trunc_with_hash",
    "truncate_middle",
    "truncate_number",
    "typed_property",
    "unsurround",
    "wildcard_matches_in_list",
    "write_temp_file",
]

REGEX_TRUE = re.compile("True", re.IGNORECASE)
REGEX_FALSE = re.compile("False", re.IGNORECASE)
REGEX_NONE = re.compile("None", re.IGNORECASE)

rdbms_max_descriptor_length = 30
LINUX_FILE_NAME_LENGTH_LIMIT = 255
MAX_SUPPORTED_PRECISION = 38

_CAMEL_BOUNDARY_1 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_2 = re.compile(r"([a-z0-9])([A-Z])")


def snake_to_camel(value: str) -> str:
    """Convert a snake_case identifier into lower camelCase."""
    if "_" not in value:
        return value
    parts = [part for part in value.split("_") if part]
    if not parts:
        return value
    return parts[0].lower() + "".join(part.capitalize() for part in parts[1:])


def camel_to_snake(value: str) -> str:
    """Convert a camelCase or PascalCase identifier into lower snake_case."""
    step1 = _CAMEL_BOUNDARY_1.sub(r"\1_\2", value)
    step2 = _CAMEL_BOUNDARY_2.sub(r"\1_\2", step1)
    return step2.replace("-", "_").lower()


def split_csv(value: str | None) -> list[str]:
    """Split a comma-separated string into stripped non-empty tokens."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def redact_text(text: str, tokens: Iterable[str], *, replacement: str = "***") -> str:
    """Replace all non-empty sensitive tokens in text with replacement."""
    result = text
    for token in tokens:
        if token:
            result = result.replace(token, replacement)
    return result


def truncate_middle(text: str, *, max_length: int = 120, marker: str = "...") -> str:
    """Truncate text in the middle when it exceeds max_length."""
    if len(text) <= max_length or max_length <= len(marker):
        return text[:max_length]
    budget = max_length - len(marker)
    head = (budget + 1) // 2
    tail = budget - head
    return f"{text[:head]}{marker}{text[len(text) - tail :] if tail else ''}"


def all_int_chars(int_str: object, allow_negative: bool = False) -> bool:
    """Return True if all characters in int_str represent an integer."""
    if allow_negative:
        return bool(re.match(r"^-?\d+$", str(int_str)))
    return bool(re.match(r"^\d+$", str(int_str)))


def end_by(s: str, ch: str) -> str:
    """Ensure that character ch is at the end of string s."""
    if s.endswith(ch):
        return s
    return s + ch


def begin_with(s: str, ch: str) -> str:
    """Ensure that character ch is at the beginning of string s."""
    if s.startswith(ch):
        return s
    return ch + s


def surround(s: str, ch: str) -> str:
    """Surround string s with ch before and after."""
    return end_by(begin_with(s, ch), ch)


def unsurround(s: str, ch: str, endch: str | None = None) -> str:
    """Strip surrounding delimiters ch and optional endch from s."""
    first_ch = ch
    last_ch = endch or ch
    if s and s.startswith(first_ch) and s.endswith(last_ch):
        return s[1:-1]
    return s


def chunk_list[T](lst: Sequence[T], chunk_size: int) -> Iterator[Sequence[T]]:
    """Yield consecutive slices of lst of length up to chunk_size."""
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]


def set_goelib_logging(log_level: str | int, extra_loggers: Sequence[str] | None = None) -> None:
    """Configure root logging and silence non-goelib loggers."""
    allowed = list(extra_loggers) if extra_loggers else []
    for logger_name in logging.Logger.manager.loggerDict:
        if logger_name != "__main__" and logger_name not in allowed and not logger_name.startswith("goelib"):
            logging.getLogger(logger_name).level = logging.CRITICAL
    resolved_level = logging.getLevelName(log_level) if isinstance(log_level, str) else log_level
    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_python_from_string(value: str) -> Any:
    """Translate string value into a native Python scalar based on appearance."""
    assert isinstance(value, str)
    if is_number(value):
        return float(value) if "." in value else int(value)
    if REGEX_TRUE.match(value):
        return True
    if REGEX_FALSE.match(value):
        return False
    if REGEX_NONE.match(value):
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return value


def csv_split(csv: str, sep: str = ",") -> list[str]:
    """Split a delimited string and strip each token."""
    return [token.strip() for token in csv.split(sep)]


def csvkv_to_dict(csvkv: str, sep: str = ",", pythonize: bool = True) -> dict[str, Any]:
    """Transform a comma-separated key=value string into a dictionary."""
    ret: dict[str, Any] = {}
    for kv_chunk in csvkv.split(sep):
        key, value = csv_split(kv_chunk, sep="=")
        ret[key] = parse_python_from_string(value) if pythonize else value
    return ret


def split_not_in_quotes(to_split: str, sep: str = " ", exclude_empty_tokens: bool = False) -> list[str]:
    """Split a string by sep only when sep is not inside single or double quotes."""
    pattern = rf"""{sep}(?=(?:[^'"]|'[^']*'|"[^"]*")*$)"""
    if exclude_empty_tokens:
        return [token for token in re.split(pattern, to_split) if token]
    return re.split(pattern, to_split)


def timedelta_to_str(td: datetime.timedelta) -> str:
    """Convert a timedelta to a days HH:MM:SS string."""
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    prefix = str(td.days) if td.days > 0 else ""
    return f"{prefix}{hours:02d}:{minutes:02d}:{seconds:02d}"


def is_number(s: object) -> bool:
    """Return True if s can be converted to a float and is not a boolean."""
    if s is None or isinstance(s, bool):
        return False
    if not isinstance(s, (int, float, str, bytes, decimal.Decimal)):
        return False
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def is_pos_int(val: object, allow_zero: bool = False) -> bool:
    """Return True if val represents a positive integer (or zero when allow_zero is True)."""
    if isinstance(val, bool) or not isinstance(val, (int, float, str, decimal.Decimal)):
        return False
    lower_bound = 0 if allow_zero else 1
    try:
        n = int(val)
        if n < lower_bound:
            return False
        return decimal.Decimal(str(val)) == n
    except (TypeError, ValueError, decimal.InvalidOperation):
        return False


def is_power_of_10(n: object) -> bool:
    """Return True if n is an integer power of 10."""
    if n is None or isinstance(n, bool) or not isinstance(n, (int, float, str, decimal.Decimal)):
        return False
    dec_val = decimal.Decimal(str(n)) if isinstance(n, (str, float)) else decimal.Decimal(n)
    return bool(dec_val and (dec_val / (decimal.Decimal(10) ** (len(str(n)) - 1))) == 1)


def truncate_number(
    n: int | float | decimal.Decimal,
    digits_to_keep: int = 0,
) -> int | float | decimal.Decimal:
    """Truncate a number to a specific number of decimal places toward zero."""
    num = n if isinstance(n, decimal.Decimal) else decimal.Decimal(str(n))
    original_context = decimal.getcontext()
    tn_context = decimal.Context(prec=MAX_SUPPORTED_PRECISION + abs(digits_to_keep) + 1)
    decimal.setcontext(tn_context)
    multiplier = tn_context.power(decimal.Decimal(10), digits_to_keep)
    n_multiplied = (num * multiplier).to_integral_value(rounding=decimal.ROUND_DOWN)
    if n_multiplied == 0:
        n_final = decimal.Decimal(0)
    else:
        divided = n_multiplied / multiplier
        n_final = divided.quantize(decimal.Decimal(1)) if divided == divided.to_integral() else divided.normalize()
    decimal.setcontext(original_context)
    if isinstance(n, int):
        return int(n_final)
    if isinstance(n, float):
        return float(n_final)
    return n_final


def nvl[T](val: T | None, repl: T) -> T:
    """Return val if truthy, otherwise repl."""
    return val or repl


def backtick_sandwich(s: str, ch: str = "`") -> str:
    """Return a copy of s enclosed by a single pair of ch characters."""
    return ch + s.strip(ch) + ch


def double_quote_sandwich(s: str) -> str:
    """Return a copy of s enclosed by double quotes."""
    return backtick_sandwich(s, '"')


def isclose(a: float, b: float, rel_tol: float = 1e-09, abs_tol: float = 0.0) -> bool:
    """Return True if two numbers are close within relative or absolute tolerance."""
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def typed_property(name: str, expected_type: type[Any]) -> property:
    """Define a type-checked property backed by a private attribute."""
    storage_name = "_" + name

    def fget(self: Any) -> Any:
        return getattr(self, storage_name)

    def fset(self: Any, value: Any) -> None:
        if not isinstance(value, expected_type):
            raise TypeError(f"{name} must be a {expected_type}")
        setattr(self, storage_name, value)

    return property(fget, fset)


def get_option(options: object, name: str, repl: Any = None) -> Any:
    """Return options attribute name if present, else repl."""
    return getattr(options, name) if (options and hasattr(options, name)) else repl


def str_floatlike(maybe_float: Any) -> Any:
    """Strip redundant trailing zeros from a float or float-like string."""
    if is_number(maybe_float) and not float(maybe_float).is_integer():
        return str(maybe_float).rstrip("0").rstrip(".")
    return maybe_float


def trunc_with_hash(
    s: str,
    hash_length: int,
    max_length: int,
    force_append_hash: bool = False,
    hash_case_conv_fn: Callable[[str], str] | None = None,
) -> str:
    """Truncate a string with a suffix of a hash of its original value so final length is max_length."""
    assert s
    assert hash_length
    assert max_length
    if hash_case_conv_fn:
        assert callable(hash_case_conv_fn)
    if len(s) <= max_length and not force_append_hash:
        return s
    stem = s[: max_length - hash_length - 1]
    minihash = b64encode(md5(s.encode()).digest()).decode()
    minihash = re.sub(r"[\W\s]", "", minihash)[:hash_length]
    if hash_case_conv_fn:
        minihash = hash_case_conv_fn(minihash)
    return stem + "_" + minihash


def standard_file_name(
    file_prefix: str,
    name_suffix: str = "",
    extension: str = "",
    max_name_length: int = LINUX_FILE_NAME_LENGTH_LIMIT,
    with_datetime: bool = False,
    max_name_length_extra_slack: int = 0,
    hash_case_conv_fn: Callable[[str], str] | None = None,
) -> str:
    """Generate a standardized file name truncated safely within max_name_length."""
    assert file_prefix
    assert isinstance(file_prefix, str)
    assert "/" not in file_prefix
    assert isinstance(name_suffix, str)
    assert isinstance(extension, str)
    assert isinstance(max_name_length_extra_slack, int)
    if hash_case_conv_fn:
        assert callable(hash_case_conv_fn)

    log_append = ""
    if name_suffix:
        log_append += "_" + name_suffix
    if with_datetime:
        log_append += "_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    over_limit = (len(file_prefix) + len(log_append) + len(extension) + max_name_length_extra_slack) - max_name_length
    if over_limit > 0:
        new_log_prefix = trunc_with_hash(
            file_prefix,
            4,
            len(file_prefix) - over_limit,
            hash_case_conv_fn=hash_case_conv_fn,
        )
    else:
        new_log_prefix = file_prefix
    return f"{new_log_prefix}{log_append}{extension}"


def standard_log_name(log_prefix: str) -> str:
    """Generate a standardized timestamped .log file name."""
    return standard_file_name(log_prefix, extension=".log", with_datetime=True)


def get_decimal_precision_and_scale(data_type_string: str) -> tuple[int, int] | None:
    """Parse precision and scale out of DECIMAL(p,s) or DECIMAL(p)."""
    if "," in data_type_string:
        pattern = r"^DECIMAL\s*\(([1-9][0-9]?)\s*,\s*([0-9][0-9]?)\)$"
    else:
        pattern = r"^DECIMAL\s*\(([1-9][0-9]?)\s*\)$"
    match = re.match(pattern, data_type_string, flags=re.IGNORECASE)
    if not match or len(match.groups()) not in (1, 2):
        return None
    precision = int(match.group(1))
    scale = int(match.group(2)) if len(match.groups()) == 2 else 0
    return (precision, scale)


def get_integral_part_magnitude(py_val: int | float | decimal.Decimal) -> int:
    """Return the digit magnitude of the integral part of a number."""
    int_part = abs(int(py_val))
    return 1 if int_part == 0 else int(math.log10(int_part)) + 1


def bytes_to_human_size(size_bytes: int | float, scale: int = 1) -> str:
    """Format a byte count into a human-friendly B/KB/MB/GB/TB string."""
    assert size_bytes is not None
    pattern = f"%.{scale}f"
    if size_bytes < 1024:
        return f"{int(size_bytes)}B"
    if size_bytes < 1024 * 1024:
        return (pattern % round(size_bytes / 1024.0, scale)) + "KB"
    if size_bytes < 1024 * 1024 * 1024:
        return (pattern % round(size_bytes / 1024.0 / 1024, scale)) + "MB"
    if size_bytes < 1024 * 1024 * 1024 * 1024:
        return (pattern % round(size_bytes / 1024.0 / 1024 / 1024, scale)) + "GB"
    return (pattern % round(size_bytes / 1024.0 / 1024 / 1024 / 1024, scale)) + "TB"


def human_size_to_bytes(size: int | float | str | bytes | None, binary_sizes: bool = True) -> int | None:
    """Parse a human-friendly size string (e.g. 64KB, 10M) into an integer byte count."""
    if size is None:
        return None
    if isinstance(size, bytes):
        size_str = size.decode()
    elif not isinstance(size, str):
        size_str = str(size)
    else:
        size_str = size
    match = re.match(r"^([\d\.]+)([BKMGT])?$", size_str) or re.match(r"^([\d\.]+)([KMGT]B)?$", size_str)
    if not match:
        return None
    mag_dict = (
        {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}
        if binary_sizes
        else {"B": 1, "K": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15}
    )
    unit = match.group(2)
    if unit:
        mag_key = unit[0] if len(unit) == 2 else unit
        mag = mag_dict[mag_key]
    else:
        mag = 1
    return int(float(match.group(1)) * mag)


def get_temp_path(tmp_dir: str = "/tmp", prefix: str = "goe_tmp_", suffix: str = "") -> str:
    """Generate a temporary file path with a controlled prefix, UUID, and suffix."""
    suffix_str = f".{suffix.lstrip('.')}" if suffix else ""
    return str(Path(tmp_dir) / f"{prefix}{uuid.uuid4()}{suffix_str}")


def write_temp_file(data: str, prefix: str = "goe_tmp_", suffix: str = "") -> str:
    """Write data to a temporary file and return its path."""
    tmp_path = get_temp_path(prefix=prefix, suffix=suffix)
    Path(tmp_path).write_text(data, encoding="utf-8")
    return tmp_path


def id_generator(size: int = 8, chars: str = string.ascii_uppercase + string.digits) -> str:
    """Generate a random alphanumeric identifier of the given length."""
    return "".join(random.choice(chars) for _ in range(size))


def obscure_list_items(
    list_of_items: list[str],
    to_obscure: Sequence[dict[str, str]] | None,
) -> list[str]:
    """Return a copy of list_of_items with matching sensitive elements obscured."""
    safe_list = copy(list_of_items)
    if not to_obscure:
        return safe_list
    for itm in to_obscure:
        safe_list = [
            (
                itm.get("sub", "?")
                if safe_list[i] == itm["item"]
                and (not itm.get("prior") or (i > 0 and itm.get("prior") == safe_list[i - 1]))
                else safe_list[i]
            )
            for i in range(len(safe_list))
        ]
    return safe_list


def get_os_username() -> str | None:
    """Return the current operating system username without relying on os.getlogin."""
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER")


def ansi_c_string_safe(shell_command: str) -> str:
    """Wrap a shell string in ANSI-C $'...' quoting with escaped backslashes and single quotes."""
    escaped = shell_command.replace("\\", r"\\").replace("'", r"\'")
    return f"$'{escaped}'"


def match_case(token: str, affix: str, position: str | None, operation: str) -> str:
    """Concatenate or substitute affix with token while matching token's case."""
    assert token and operation in ("concatenate", "substitute")
    if operation == "concatenate":
        assert position in ("prefix", "suffix") and affix
        if token.isupper():
            return (
                (affix.upper() if position == "prefix" else "")
                + token
                + (affix.upper() if position == "suffix" else "")
            )
        if token.islower():
            return (
                (affix.lower() if position == "prefix" else "")
                + token
                + (affix.lower() if position == "suffix" else "")
            )
        return (affix if position == "prefix" else "") + token + (affix if position == "suffix" else "")
    if affix.isupper():
        return (token % affix).upper()
    if affix.islower():
        return (token % affix).lower()
    return token % affix


def add_suffix_in_same_case(token: str, suffix: str) -> str:
    """Append suffix to token in the same case (upper or lower)."""
    assert token and suffix
    return match_case(token, suffix, "suffix", "concatenate")


def add_prefix_in_same_case(token: str, prefix: str) -> str:
    """Prepend prefix to token in the same case (upper or lower)."""
    assert token and prefix
    return match_case(token, prefix, "prefix", "concatenate")


def substitute_in_same_case(pattern: str, token: str) -> str:
    """Substitute token into a %-format pattern in the same case (upper or lower)."""
    assert pattern and "%" in pattern
    return match_case(pattern, token, None, "substitute")


def case_insensitive_in(token: str | None, search_list: Iterable[str] | str | None) -> str | None:
    """Search for token in search_list case-insensitively and return the matched element."""
    if not search_list or token is None:
        return None
    token_upper = token.upper()
    if isinstance(search_list, str):
        return search_list if token_upper == search_list.upper() else None
    matches = [item for item in search_list if item is not None and token_upper == item.upper()]
    return matches[0] if matches else None


def format_json_list(json_list: Iterable[object] | None, separator: str = "\n", indent: int = 0) -> str:
    """Format an iterable of items as separated strings with optional indentation."""
    if json_list is None:
        return ""
    sep = separator + (" " * indent)
    return sep.join(item if isinstance(item, str) else str(item) for item in json_list)


def plural(s: str, n: int, caps: bool = False) -> str:
    """Format a singular word s into its plural form when n != 1."""
    if s[-1].lower() != "y":
        suffix = "s" if n != 1 else ""
        ps = f"{s}{suffix}"
    else:
        stem = s[:-1] if n != 1 else s
        suffix = "ies" if n != 1 else ""
        ps = f"{stem}{suffix}"
    return ps.upper() if caps else ps


def format_list_for_logging(content_list: list[tuple[Any, ...]], underline_char: str = "=") -> str:
    """Format a list of row tuples into an aligned text table suitable for logging."""
    assert content_list
    assert isinstance(content_list, list), f"{type(content_list)} is not list"
    assert isinstance(content_list[0], tuple)
    widths = [
        max(len(row[i]) if isinstance(row[i], str) else len(str(row[i])) for row in content_list)
        for i in range(len(content_list[0]))
    ]
    header_format = " ".join(f"{{{i}: <{w}}}" for i, w in enumerate(widths))
    table_rows = [
        header_format.format(*content_list[0]).rstrip(),
        header_format.format(*[(underline_char * w) for w in widths]),
    ]
    if len(content_list) < 2:
        return "\n".join([*table_rows, "No data"])
    row_format = " ".join(
        f"{{{i}: {'<' if isinstance(c, str) else '>'}{w}}}"
        for i, (w, c) in enumerate(zip(widths, content_list[1], strict=False))
    )
    return "\n".join([*table_rows, *[row_format.format(*row).rstrip() for row in content_list[1:]]])


def remove_chars(input_string: str | None, chars_to_remove: str) -> str | None:
    """Remove all characters in chars_to_remove from input_string."""
    if input_string is None:
        return None
    assert isinstance(input_string, str)
    assert isinstance(chars_to_remove, str)
    return "".join(ch for ch in input_string if ch not in chars_to_remove)


def str_summary_of_self(other_self: object) -> str:
    """Create a string summary of public non-callable attributes on an object."""
    assert other_self
    fields = ", ".join(
        f"{k}={v}"
        for k, v in inspect.getmembers(other_self)
        if not inspect.ismethod(v) and not inspect.isfunction(v) and not k.startswith("_")
    )
    return f"({fields})"


def to_bytes(bytes_or_str: bytes | str) -> bytes:
    """Encode a string to UTF-8 bytes or return bytes unchanged."""
    if isinstance(bytes_or_str, str):
        return bytes_or_str.encode("utf-8")
    return bytes_or_str


def to_str(bytes_or_str: bytes | str) -> str:
    """Decode UTF-8 bytes to a string or return str unchanged."""
    if isinstance(bytes_or_str, bytes):
        return bytes_or_str.decode("utf-8")
    return bytes_or_str


def wildcard_matches_in_list(
    pattern: str,
    list_of_names: Sequence[str] | None,
    case_sensitive: bool = True,
) -> list[str]:
    """Return all strings in list_of_names matching the '*' wildcard pattern."""
    if not list_of_names:
        return []
    escaped = re.escape(pattern).replace("\\*", ".*")
    anchored = rf"^{escaped}$"
    pattern_re = re.compile(anchored) if case_sensitive else re.compile(anchored, re.IGNORECASE)
    return [item for item in list_of_names if pattern_re.match(item)]

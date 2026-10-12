#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""TeradataLiteral: Format an Teradata literal based on data type."""

import logging
import re
from datetime import date, time

from numpy import datetime64

from goe.offload.format_literal import RE_TIMEZONE_NO_COLON, FormatLiteralInterface
from goe.offload.teradata.teradata_column import (
    TERADATA_TYPE_BYTE,
    TERADATA_TYPE_DATE,
    TERADATA_TYPE_TIME,
    TERADATA_TYPE_TIMESTAMP,
    TERADATA_TYPE_TIMESTAMP_TZ,
    TERADATA_TYPE_VARBYTE,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class TeradataLiteral(FormatLiteralInterface):
    """Format a Teradata literal based on data type"""

    @classmethod
    def format_literal(cls, python_value, data_type=None):
        """Translate a Python value to a Teradata literal.
        Without a data type the code should infer a literal from the Python type.
        No special formatting is required for numeric literals, we just convert to str().

        Assuming DATE based on string length
        Assuming TIMESTAMP if no data_type specified
        """

        def format_date_for_data_type(str_val, data_type):
            """Value is date part only

            Value is up to seconds only
            %z in strftime does not have a colon in the timezone offset which Teradata requires
            """
            if data_type == TERADATA_TYPE_DATE:
                return "DATE '%s'" % str_val[:10]
            if data_type == TERADATA_TYPE_TIMESTAMP:
                adjusted_str = str_val
                if len(adjusted_str) == 10:
                    adjusted_str += " 00:00:00.0"
                elif len(adjusted_str) == 19:
                    adjusted_str += ".0"
                ts_maxscale = 6
                adjusted_str = str_val[: 20 + ts_maxscale]
                return "TIMESTAMP '%s'" % cls._strip_unused_time_scale(adjusted_str)
            if data_type == TERADATA_TYPE_TIME:
                return "TIME '%s'" % str_val
            if data_type == TERADATA_TYPE_TIMESTAMP_TZ and re.match(RE_TIMEZONE_NO_COLON, str_val):
                return f"'{str_val[:-2]}:{str_val[-2:]}'"
            return str_val

        logger.debug("Formatting %s literal: %r" % (type(python_value), python_value))
        logger.debug("For data type: %s" % data_type)
        if isinstance(python_value, datetime64):
            if data_type == TERADATA_TYPE_TIME:
                new_py_val = format_date_for_data_type(str(python_value).split("T")[1], data_type)
            elif data_type:
                new_py_val = format_date_for_data_type(str(python_value).replace("T", " "), data_type)
            elif len(str(python_value)) <= 10:
                new_py_val = format_date_for_data_type(str(python_value).replace("T", " "), TERADATA_TYPE_DATE)
            else:
                new_py_val = format_date_for_data_type(str(python_value).replace("T", " "), TERADATA_TYPE_TIMESTAMP)
        elif isinstance(python_value, date):
            if data_type == TERADATA_TYPE_DATE:
                new_py_val = format_date_for_data_type(python_value.strftime("%Y-%m-%d"), data_type)
            elif data_type == TERADATA_TYPE_TIMESTAMP_TZ:
                if not getattr(python_value, "tzinfo", None):
                    new_py_val = format_date_for_data_type(
                        python_value.strftime("%Y-%m-%d %H:%M:%S.%f +00:00"), data_type
                    )
                else:
                    new_py_val = format_date_for_data_type(python_value.strftime("%Y-%m-%d %H:%M:%S.%f%z"), data_type)
            elif data_type == TERADATA_TYPE_TIME:
                new_py_val = format_date_for_data_type(python_value.strftime("%H:%M:%S.%f"), data_type)
            elif data_type:
                new_py_val = format_date_for_data_type(python_value.strftime("%Y-%m-%d %H:%M:%S.%f"), data_type)
            elif len(str(python_value)) <= 10:
                new_py_val = format_date_for_data_type(python_value.strftime("%Y-%m-%d"), TERADATA_TYPE_DATE)
            else:
                new_py_val = format_date_for_data_type(
                    python_value.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    TERADATA_TYPE_TIMESTAMP,
                )
        elif python_value is None:
            return "NULL"
        elif data_type == TERADATA_TYPE_TIME:
            if isinstance(python_value, time):
                new_py_val = format_date_for_data_type(python_value.strftime("%H:%M:%S.%f"), data_type)
            else:
                new_py_val = format_date_for_data_type(python_value, data_type)
        elif data_type in [TERADATA_TYPE_BYTE, TERADATA_TYPE_VARBYTE]:
            suffix = "XB" if data_type == TERADATA_TYPE_BYTE else "XBV"
            if isinstance(python_value, str):
                new_py_val = f"{python_value.encode().hex()}{suffix}"
            else:
                new_py_val = f"{python_value.hex()}{suffix}"
        elif isinstance(python_value, str):
            new_py_val = "'%s'" % python_value
        elif isinstance(python_value, bytes):
            new_py_val = "'%s'" % python_value.decode()
        elif isinstance(python_value, float):
            new_py_val = repr(python_value)
        else:
            new_py_val = str(python_value)
        return new_py_val

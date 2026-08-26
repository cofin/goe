# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import pytest

from goe.offload import option_validation as module_under_test


@pytest.mark.parametrize(
    "input,expect_exception",
    [
        ("s", True),
        (None, True),
        (-1, True),
        (0, True),
        (1.1, True),
        (0.1, True),
        (123456789012345.1, True),
        (1, False),
        (123456789012345, False),
    ],
)
def test_check_opt_is_posint(input: str, expect_exception: bool):
    if expect_exception:
        with pytest.raises(Exception):
            _ = module_under_test.check_opt_is_posint("fake-option", input)
    else:
        output = module_under_test.check_opt_is_posint("fake-option", input)
        assert output == input

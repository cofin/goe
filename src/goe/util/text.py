# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Text transformation and identifier normalization utilities for GOE."""

from sqlspec.utils.text import (
    camelize,
    kebabize,
    normalize_identifier,
    pascalize,
    quote_backtick_identifier,
    quote_identifier,
    slugify,
    snake_case,
    split_qualified_identifier,
)

__all__ = (
    "camelize",
    "kebabize",
    "normalize_identifier",
    "pascalize",
    "quote_backtick_identifier",
    "quote_identifier",
    "slugify",
    "snake_case",
    "split_qualified_identifier",
)

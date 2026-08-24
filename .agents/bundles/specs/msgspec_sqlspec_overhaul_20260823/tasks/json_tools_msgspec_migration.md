---
type: Task
id: msgspec_sqlspec_overhaul_20260823:json_tools_msgspec_migration
title: Modernize json_tools with msgspec Encoder/Decoder and Custom enc_hook
description: Modernize json_tools serialization utility with msgspec encoder, decoder, and custom domain encoding hook.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - migration
  - serialization
  - msgspec
  - json
depends_on:
files:
  - src/goe/util/json_tools.py
tests:
  - tests/unit
verification_strategy: behavior_tdd
---

# Task: Modernize json_tools with msgspec Encoder/Decoder and Custom enc_hook

## Objective
Replace `orjson` and standard `json` usage in `src/goe/util/json_tools.py` with `msgspec.json.Encoder` (configured with `enc_hook=_default`) and `msgspec.json.Decoder()`, handling `Decimal`, `datetime`, `date`, `ExecutionId`, `GenericPredicate`, and NumPy types.

## Implementation Details

1. Implement `_default(value: Any) -> Any` enc_hook function:
   - Convert `decimal.Decimal`, `datetime.datetime`, `datetime.date`, `ExecutionId` to strings.
   - Extract `.dsl` for `GenericPredicate`.
   - Convert `np.integer`, `np.floating`, `np.ndarray` to standard Python equivalents.
2. Implement `serialize_object(obj: Any) -> str`:
   - Encode with `_msgspec_json_encoder.encode(obj).decode("utf-8")`.
3. Implement `deserialize_object(payload: str | bytes) -> Any`:
   - Decode with `msgspec.json.decode(payload)`.
4. Remove `import orjson` and eliminate any `orjson` exceptions.

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Unit test exercising `serialize_object` on `Decimal` and `GenericPredicate` with `msgspec`.
- **Final Evidence**: Unit tests in `tests/unit/` for serialization pass green; zero `orjson` references in `src/goe/util/json_tools.py`.

---
type: Task
id: msgspec_sqlspec_overhaul_20260823:json_tools_msgspec_migration
title: Modernize json_tools with msgspec Encoder/Decoder and Custom enc_hook
description: Modernize json_tools serialization utility with msgspec encoder, decoder, and custom domain encoding hook.
state: closed
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T22:47:00Z"
tags:
  - migration
  - serialization
  - msgspec
  - json
depends_on: []
files:
  - src/goe/util/json_tools.py
  - src/goe/goe.py
tests:
  - tests/unit/util/test_json_tools.py
verification_strategy: behavior_tdd
---

# Task: Modernize json_tools with msgspec Encoder/Decoder and Custom enc_hook

## Objective
Replace `orjson` and legacy serialization routines in `src/goe/util/json_tools.py` and `src/goe/goe.py` with `msgspec.json.Encoder(enc_hook=_default)` and `msgspec.json.Decoder()`, handling complex domain types including `Decimal`, `datetime.datetime`, `datetime.date`, `ExecutionId`, `GenericPredicate`, `np.generic`, and `np.ndarray`.

## Target File Changes

### 1. `src/goe/util/json_tools.py` (Full Replacement)
Implement `_default(value: Any)` encoding hook:
- `decimal.Decimal` -> `str(value)`
- `datetime.datetime` / `datetime.date` -> `value.isoformat()`
- `ExecutionId` -> `str(value)`
- `GenericPredicate` -> `value.dsl`
- `np.generic` -> `value.item()`
- `np.ndarray` -> `value.tolist()`
- `uuid.UUID` -> `str(value)`
- `set` / `frozenset` -> `list(value)`

Define `_msgspec_json_encoder = msgspec.json.Encoder(enc_hook=_default)` and `_msgspec_json_decoder = msgspec.json.Decoder()`.
Implement `serialize_object`, `serialize_object_bytes`, `deserialize_object`, `encode_datetime_object`, and `convert_field_to_camel_case`.

### 2. `src/goe/goe.py`
- Remove line 27: `import orjson`
- Replace lines 276–286: Import `serialize_object` from `goe.util.json_tools`.

## Itemized Checklist
- [ ] Implement `_default(value: Any)` in `src/goe/util/json_tools.py` supporting all domain and NumPy types.
- [ ] Define `_msgspec_json_encoder` and `_msgspec_json_decoder`.
- [ ] Implement `serialize_object(obj)` and `deserialize_object(payload)`.
- [ ] Remove `import orjson` and duplicate serializer in `src/goe/goe.py`.
- [ ] Author `tests/unit/util/test_json_tools.py`.

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Absence of `msgspec` encoder in `src/goe/util/json_tools.py`.
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/util/test_json_tools.py -v
  ```
- **Expected Output**: All serialization round-trip tests pass green.\n
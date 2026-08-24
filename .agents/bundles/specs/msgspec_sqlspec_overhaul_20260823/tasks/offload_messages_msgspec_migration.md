---
type: Task
id: msgspec_sqlspec_overhaul_20260823:offload_messages_msgspec_migration
title: Migrate OffloadMessages Redis Publishing to msgspec
description: Migrate OffloadMessages Redis pub/sub message encoding and log telemetry to msgspec.
state: closed
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T22:50:00Z"
tags:
  - migration
  - messaging
  - redis
  - msgspec
depends_on:
  - msgspec_sqlspec_overhaul_20260823:json_tools_msgspec_migration
files:
  - src/goe/offload/offload_messages.py
tests:
  - tests/unit/offload/test_offload_messages.py
verification_strategy: characterization
---

# Task: Migrate OffloadMessages Redis Publishing to msgspec

## Objective
Update `src/goe/offload/offload_messages.py` to eliminate `orjson` and serialize real-time log messages published to Redis using `msgspec`, ensuring zero-overhead encoding and resilient exception handling.

## Target File Changes
- Remove `import orjson` from line 28.
- Import `serialize_object` from `goe.util.json_tools`.
- Delete duplicate `serialize_object` definition (lines 85–95).
- Use `serialize_object({"message": line})` for Redis `cache.rpush`.

## Itemized Checklist
- [ ] Remove `import orjson` from `src/goe/offload/offload_messages.py`.
- [ ] Import `serialize_object` from `goe.util.json_tools`.
- [ ] Remove duplicate `serialize_object` function body.
- [ ] Verify Redis list pushing (`goe:run:{execution_id}`) functions identically.
- [ ] Run `tests/unit/offload/test_offload_messages.py`.

## Verification Strategy
- **Strategy**: `characterization`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/offload/test_offload_messages.py -v
  ```
- **Expected Output**: Offload messages unit tests pass 100% green.\n
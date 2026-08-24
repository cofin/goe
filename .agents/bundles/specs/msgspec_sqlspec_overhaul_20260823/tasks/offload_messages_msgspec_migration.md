---
type: Task
id: msgspec_sqlspec_overhaul_20260823:offload_messages_msgspec_migration
title: Migrate OffloadMessages Redis Publishing to msgspec
description: Migrate OffloadMessages Redis pub/sub message encoding and log telemetry to msgspec.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
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
  - tests/unit
verification_strategy: characterization
---

# Task: Migrate OffloadMessages Redis Publishing to msgspec

## Objective
Update `src/goe/offload/offload_messages.py` to serialize log messages and execution status events published to Redis using `msgspec`, eliminating `orjson`.

## Implementation Details

1. Replace `orjson.dumps(dict_msg).decode()` in `OffloadMessages._publish_to_redis()` with `msgspec.json.encode(dict_msg).decode("utf-8")`.
2. Ensure message dictionary structuring remains intact for downstream Redis subscribers.

## Verification
- **Strategy**: `characterization`
- **Initial Evidence**: Baseline tests passing for offload messaging.
- **Final Evidence**: Unit tests in `tests/unit/` pass cleanly; zero `orjson` imports in `offload_messages.py`.

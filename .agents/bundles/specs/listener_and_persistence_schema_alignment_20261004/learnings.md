---
type: Reference
title: "Learnings: Listener REST & Persistence Schema Alignment (listener_and_persistence_schema_alignment_20261004)"
description: Durable learnings and patterns from aligning Listener OffloadOptions, ListenerConfig, ColumnDetail, SubPartitionDetail, and serialization.py
tags:
  - learnings
  - listener
  - persistence
  - msgspec
  - serialization
---

# Learnings: `listener_and_persistence_schema_alignment_20261004`

## 1. Avoiding Circular Imports Between `goe.listener.schemas` and `goe.goe`
- **Problem**: Importing `EXPECTED_OFFLOAD_ARGS` from `goe.goe` at the top of [`src/goe/listener/schemas.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/schemas.py) creates a circular import (`goe.goe` -> `goe.config.config_validation_functions` -> `goe.filesystem.goe_dfs` -> `goe.offload.offload_messages` -> `goe.listener.utils.cache` -> `goe.listener.utils` -> `goe.listener.exceptions` -> `goe.listener.schemas`).
- **Resolution**: Define the 84 canonical `EXPECTED_OFFLOAD_ARGS` fields and the 12 alias fields directly on `OffloadOptions` in `src/goe/listener/schemas.py` and normalize/pop the 12 alias keys inside `OffloadOptions.to_params_dict()` without importing `goe.goe` in `schemas.py`; enforce strict subset membership against `EXPECTED_OFFLOAD_ARGS` in `tests/unit/listener/test_offload_options_schema.py`.

## 2. Normalizing Mixed `msgspec.Struct` and `dict` Returns in Listener Controllers
- **Problem**: `OracleOrchestrationRepoClient.get_table_partitions` returns `list[dict]`, whereas `get_table_subpartitions` returns `list[SubPartitionDetail]` (`msgspec.Struct`). Calling `p.get("partition_name")` directly in `SystemController.get_table_partitions` raised `AttributeError`.
- **Resolution**: Normalize items via `item.to_dict() if hasattr(item, "to_dict") else dict(item)` before grouping by `"partition_name"`.

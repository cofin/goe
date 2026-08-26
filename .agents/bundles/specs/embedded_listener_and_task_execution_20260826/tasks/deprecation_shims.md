---
type: Task
id: embedded_listener_and_task_execution_20260826:deprecation_shims
title: Add Deprecation Shims for Legacy Redis Modules and bin/ Scripts
description: Add runtime DeprecationWarning shims to goe.util.redis_tools, goe.listener.utils.cache (RedisClient alias), and legacy bin/ scripts scheduled for removal in GOE 2.0.0.
state: open
created_at: "2026-08-26T21:20:00Z"
updated_at: "2026-08-26T21:23:00Z"
tags:
  - deprecations
  - shims
  - compatibility
  - cli
depends_on:
  - embedded_listener_and_task_execution_20260826:native_task_execution
files:
  - src/goe/util/redis_tools.py
  - src/goe/listener/utils/cache.py
  - bin/offload
  - bin/listener
  - bin/connect
  - bin/logmgr
  - bin/agg_validate
tests:
  - tests/unit/listener/test_deprecation_shims.py
verification_strategy: behavior_tdd
---

# Task: Add Deprecation Shims for Legacy Redis Modules and bin/ Scripts

## Objective
Add explicit runtime `DeprecationWarning`s to legacy modules and scripts scheduled for removal in GOE 2.0.0:
1. `src/goe/util/redis_tools.py`
2. `src/goe/listener/utils/cache.py` (`RedisClient` alias)
3. Shell entry point scripts in `bin/` (`bin/offload`, `bin/listener`, `bin/connect`, `bin/logmgr`, `bin/agg_validate`)

## Implementation Details

### 1. `src/goe/util/redis_tools.py`
Add top-level deprecation warning on import:
```python
import warnings

warnings.warn(
    "goe.util.redis_tools is deprecated and will be removed in GOE 2.0.0. "
    "Use embedded in-memory cache (goe.listener.utils.cache.MemoryCache) or Oracle repository persistence instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

### 2. `src/goe/listener/utils/cache.py`
Support `RedisClient` backwards compatibility with deprecation warning via module `__getattr__`:
```python
def __getattr__(name: str) -> Any:
    if name == "RedisClient":
        import warnings
        warnings.warn(
            "RedisClient in goe.listener.utils.cache is deprecated and will be removed in GOE 2.0.0. "
            "Use MemoryCache instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return MemoryCache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### 3. Legacy `bin/` Scripts
Verify each wrapper contains standard deprecation warnings with `stacklevel=1`:
- `bin/offload`: `"Invoking 'bin/offload' is deprecated and will be removed in GOE 2.0.0. Please use 'goe offload' instead."`
- `bin/listener`: `"Invoking 'bin/listener' is deprecated and will be removed in GOE 2.0.0. Please use 'goe listener' instead."`
- `bin/connect`: `"Invoking 'bin/connect' is deprecated and will be removed in GOE 2.0.0. Please use 'goe connect' instead."`
- `bin/logmgr`: `"Invoking 'bin/logmgr' is deprecated and will be removed in GOE 2.0.0. Please use 'goe logmgr' instead."`
- `bin/agg_validate`: `"Invoking 'bin/agg_validate' is deprecated and will be removed in GOE 2.0.0. Please use 'goe validate' instead."`

## Implementation Checklist
- [ ] Add module-level `DeprecationWarning` in `src/goe/util/redis_tools.py`.
- [ ] Add `RedisClient` deprecated alias in `src/goe/listener/utils/cache.py`.
- [ ] Standardize deprecation warnings across all `bin/` wrapper scripts.
- [ ] Create `tests/unit/listener/test_deprecation_shims.py` testing that `DeprecationWarning` is raised on each shim.

## Verification Strategy
- **Command:**
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_deprecation_shims.py
  ```
- **Success Criteria:** All deprecation warnings are properly triggered and captured in test assertions.

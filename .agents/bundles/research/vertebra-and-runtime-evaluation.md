---
type: Research
research_id: "goe-architecture-redesign-vertebra"
title: "Vertebra Runtime, Worker, and Queue Evaluation for the GOE Listener"
description: "Primary-source evaluation of the cofin/vertebra ASGI, RSGI, and WSGI server runtime, worker supervision, queue framework, and pure-Python idioms for GOE, including the release gate GOE needs before it replaces Granian."
scope: architecture
tags: [vertebra, runtime, asgi, rsgi, workers, queues, msgspec, packaging]
status: stable
state: promoted
promoted_to: prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024
created_at: 2026-10-24T15:52:00Z
updated_at: 2026-10-24T16:40:00Z
---

# Vertebra Runtime, Worker, and Queue Evaluation for the GOE Listener

This chapter evaluates `cofin/vertebra` at `df36a30` (branch `perf/runtime-throughput-and-315`, one commit ahead of `main` at `cf5979e`) against GOE at `d6a02fe`. It covers the complete Vertebra application runtime: the Rust ingress server, the ASGI, RSGI, and WSGI gateway workers, the embedded and shared-memory topologies, worker supervision, the multi-lane worker runner, the queue framework, packaging, and the pure-Python idioms GOE adopts.

## Recommended Decision

1. **Run the GOE Listener on Vertebra and remove Granian.** Vertebra is a full multi-protocol application server: a Hyper/Tokio ingress process with HTTP/1.1, HTTP/2, h2c, TLS and mTLS, backpressure, and a circuit breaker, plus Python gateway workers for ASGI 3.0, RSGI 1.6, and WSGI in an embedded (in-process PyO3) topology or a shared-memory multi-process topology with crash sweeping and respawn. GOE launches `goe.listener.asgi:app` through the public `vtb run` contract with `--interface asgi`, replacing `granian`, `litestar-granian`, and `GranianPlugin`.
2. **Gate the switch on a Vertebra release that closes six verified integration gaps** (listed below): the ASGI lifespan protocol, `OPTIONS`/`HEAD` routing for mounted apps, a wheel that ships the `vertebra-server` binary, the embedded-topology deadlock fix already planned in Vertebra's `runtime-throughput-and-315` spec, a public launcher contract, and published `cp312`–`cp314` wheels. Until that release exists, GOE keeps serving on Granian; every other chapter of the redesign proceeds independently.
3. **Replace `litestar-queues` with a GOE-owned durable job queue on `sqlspec`** rather than adopting Vertebra's queue framework. GOE needs exactly one durable job type (an offload run that may last 24 hours) with per-table exclusivity, heartbeat-renewed leases, and Oracle repository persistence (`GOE_LISTENER_JOBS` and `GOE_LISTENER_ENDPOINTS`). Vertebra's `OracleQueueBackend` still executes against an in-memory emulator, its claim SQL cannot run on Oracle, its `QueueBackend` protocol has no lease extension, and `WorkerRunner` processes one envelope at a time.
4. **Keep GOE's core engine free of a runtime dependency on Vertebra.** `vertebra` becomes a Listener dependency only. The pure-Python idioms GOE adopts (`FrozenBaseStruct`, cached `module_loader`, singleton serializers, `CgroupQuota`, `LameDuckController`, the AST architecture gate) are ported into `src/goe/` because the offload engine, CLI, and transports must not import a web runtime with a native extension to obtain base types.

---

## What Vertebra Provides

| Capability | Primary Source (`cofin/vertebra` at `df36a30`) | Relevance to GOE |
| :--- | :--- | :--- |
| **`vtb run` server CLI** | `src/py/vertebra/cli/run.py:26-145`: `--interface auto\|asgi\|rsgi\|wsgi`, `--topology embedded\|shm`, `--workers`, `--threads`, `--tls-cert`/`--tls-key`, `--drain-timeout`, `--shutdown-timeout`, `--worker-only`, `--oneshot-job`, `--config`. | Direct replacement for `Granian("goe.listener.asgi:app", interface=Interfaces.ASGI, workers=...)` in `src/goe/cli/commands/listener.py:178-204`. |
| **Rust ingress process** | `src/rs/vertebra-http/src/main.rs:168-363` (route table from the Python app, `RequestBatcher` pool of 8 shards, graceful shutdown); `config.rs:150-277` (`VERTEBRA_HOST`, `VERTEBRA_PORT`, `VERTEBRA_TOPOLOGY`, `VERTEBRA_WORKERS`, `VERTEBRA_THREADS`, `VERTEBRA_TLS_*`, broker and backpressure knobs). | HTTP/1.1, HTTP/2, h2c, TLS/mTLS, admission control, and keep-alive without Python in the accept loop. |
| **ASGI 3.0 gateway** | `src/py/vertebra/server/_asgi/_runner.py:64-140` (`AsgiRunner` single, batch, and streaming lifecycles), `_asgi/_queues.py`, `_asgi/_sse.py`, `_asgi/_websocket.py`; `src/rs/vertebra-py/src/asgi.rs` (`AsgiScope`). | Runs the Litestar Listener (`src/goe/listener/app.py:33-82`) as a mounted ASGI app. |
| **RSGI 1.6 and WSGI gateways** | `src/py/vertebra/server/_rsgi/_adapter.py`, `src/rs/vertebra-py/src/rsgi/{scope,http}.rs`; `src/py/vertebra/server/_wsgi/`, `src/rs/vertebra-py/src/wsgi/{environ,input,runner}.rs`. | Not needed by Litestar, available for other GOE surfaces. |
| **Shared-memory multi-process topology** | `main.rs:234-295` (`RingFactory`, `ShmDispatcher`, `shm_reader::spawn_response_readers`, `spawn_all`, `Supervisor::spawn`); `src/rs/vertebra-http/src/workers/supervisor.rs:41-136` (in-flight sweep with `502`, ring reclaim, broker lease reclaim, exponential-backoff respawn, per-worker circuit breaker). | Process isolation for CPU-heavy offload planning across GIL-bound workers. |
| **Python worker loop** | `src/py/vertebra/supervisor/_worker.py:35-94` (`resolve_worker_targets`, interface detection); `src/py/vertebra/server/worker.py:280-388` (transport init, `CgroupQuota.detect()`, `EventLoopPool`, batch loop, lame-duck drain). | Worker processes import `goe.listener.asgi:app` once and serve batches. |
| **Litestar integration** | `src/py/vertebra/extensions/litestar/plugin.py:32-166` (`LitestarPlugin`: route extraction, compression and CORS offload, health endpoint, `LitestarMCP`/`LitestarA2A` wiring, direct handler fast path; `enter_litestar_server_lifespan`). | Optional accelerations for the Listener once the base runtime is adopted. |
| **Worker lanes and one-shot jobs** | `src/py/vertebra/server/lanes.py:54-317` (`WorkerRunner`, `LaneConfig`, `run_oneshot` inside `app.lifespan()`); `src/py/vertebra/cli/workers.py:19-78` (`vtb workers run`). | `run_oneshot` matches a serverless offload run (Cloud Run Jobs); GOE implements its own job worker (see Queue Decision). |
| **Queue framework** | `src/py/vertebra/framework/queues/base.py:38-726` (`TaskDef`, `TaskEnvelope`, `TaskRetryPolicy`, `DeadLetterEntry`, `CronLease`, `QueueBackend`, `MemoryQueueBackend`, `QueueService`, `@task`); `oracle.py`, `postgres.py`, `redis.py`, `scheduler.py` (`CronScheduler`). | Evaluated and not adopted for GOE (defects below). |
| **Platform utilities** | `src/py/vertebra/server/platform.py` (`CgroupQuota`, `LameDuckController`, `ShmAllocationPolicy`, `ZPagesRegistry`). | Ported into `src/goe/util/platform.py` for the core engine. |
| **Wheel build and release** | `pyproject.toml:1-3, 73-77` (`maturin`, module `vertebra._vertebra`); `.github/workflows/release.yaml:28-75` (cibuildwheel `cp312`–`cp314` on Linux `x86_64`/`aarch64`, macOS `x86_64`/`arm64`, Windows `AMD64`, published to PyPI); `.github/workflows/release-binaries.yml` (separate `vertebra-server` binary artifacts). | GOE consumes prebuilt wheels; GOE never builds Rust. |

### Benchmark Baseline

Measured at `cf5979e` (CPython 3.12, Granian 2.8.4, `oha` pinned to separate CPUs):

- **Single core**: `vtb-shm-native-1w` beats Granian RSGI 1w and Granian ASGI 1w on `hello c=1` (19,733 vs 14,031 vs 11,959 req/s) and on `echo 1 KB c=64` (42,753 vs 27,560 vs 15,859 req/s). The Vertebra ASGI mount on one SHM worker reaches 23,433 req/s (`hello c=64`) and 21,791 req/s (`echo 1 KB c=64`), the latter ahead of Granian ASGI 1w.
- **Eight cores**: Granian scales further on small GETs at 4 and 8 workers (Granian RSGI 246.6k req/s at 8w `c=256` versus 97.8k for `vtb-shm-native-8w`) because Vertebra's single ingress process shares the CPU budget with its Python workers; `vtb-shm-native-4w` still beats Granian ASGI 4w on `echo 1 KB c=64` (116,252 vs 85,657 req/s).
- **Embedded topology** deadlocks at `c >= 16` on one core and `c >= 32` on eight cores (the `BatchBridge` bounded channels); Vertebra's active `runtime-throughput-and-315` spec (Task 2.1) removes this.

The GOE Listener is a low-request-rate control plane (offload submission, catalog reads, execution status, MCP tools). Throughput does not decide the runtime choice; lifespan correctness, CORS preflight handling, packaging, graceful drain, and crash recovery do.

---

## Integration Gaps GOE Requires Vertebra to Close

Each gap was verified in primary source at `df36a30`. The GOE chapter that switches the Listener runtime depends on a Vertebra release that resolves all six.

| Gap | Evidence | Consequence for GOE | Required Release Behavior |
| :--- | :--- | :--- | :--- |
| **R1: ASGI lifespan protocol is never driven** | No module under `src/py/vertebra/` emits `lifespan.startup` or `lifespan.shutdown`; `server/worker.py:308-318` only enters Litestar CLI-plugin `server_lifespan` contexts through `enter_litestar_server_lifespan`. | Litestar `on_startup`, `on_shutdown`, and `lifespan=[...]` hooks never run, so GOE's repository pool, `ListenerCache`, job worker, OpenTelemetry plugin, and MCP session state are never initialized or disposed. | Each worker sends `lifespan.startup` before serving and `lifespan.shutdown` during drain, fails the worker when startup reports `lifespan.startup.failed`, and shares the lifespan `state` with request scopes (the `lifespan_state` plumbing in `_asgi/_runner.py:84-99, 266-267` already exists). |
| **R2: Mounted apps only receive five HTTP methods** | `src/rs/vertebra-http/src/main.rs:62-77` registers mount prefixes for `GET`, `POST`, `PUT`, `DELETE`, and `PATCH` only. | Browser CORS preflight (`OPTIONS`, allowed by `src/goe/listener/app.py:67-71`) and `HEAD` probes never reach Litestar. | Mount prefixes register every method (including `OPTIONS` and `HEAD`), or the router forwards unmatched methods to the mount. |
| **R3: Wheels do not contain the server binary** | `dist/vertebra-0.1.0-cp312-cp312-linux_x86_64.whl` contains only `vertebra/_vertebra.cpython-312-x86_64-linux-gnu.so`; `supervisor/_supervisor.py:78-104` looks for `vertebra/bin/vertebra-server`, `VERTEBRA_SERVER_BINARY`, or a repository `target/` directory. | `pip install vertebra` cannot start a server; GOE wheels, containers, and `tools/bundle_python.py` bundles would need a separately downloaded binary. | Wheels ship `vertebra/bin/vertebra-server` for every published platform, or expose the server as an entry point inside the extension module. |
| **R4: Embedded topology deadlock** | `vertebra-core/src/bridge.rs` bounded channels; Vertebra spec `runtime-throughput-and-315` Task 2.1. | `vtb run` defaults to the embedded topology. | Task 2.1 lands; until then GOE launches with `--topology shm --workers N` (N >= 1). |
| **R5: No public launcher API** | `src/py/vertebra/supervisor/__init__.py` contains its imports only inside the module docstring and exports nothing; `vtb run` overwrites `VERTEBRA_*` variables (Vertebra Task 1.2 fixes this). | GOE cannot call `run_supervisor` without importing a private module. | GOE invokes the documented `vtb run` command contract (`[sys.executable, "-m", "vertebra", "run", ...]`), and `VERTEBRA_*` values set by GOE survive. |
| **R6: Published wheels** | `release.yaml` publishes to PyPI only on a GitHub release; the lock file GOE resolves against must contain the release. | `uv sync --locked` in GOE CI fails without a published version. | A tagged release with `cp312`–`cp314` wheels for Linux `x86_64`/`aarch64` and macOS `arm64`/`x86_64`. |

Non-blocking observations: `response.rs:97` collects request bodies in full before dispatch (GOE request bodies are small JSON documents); `VERTEBRA_APP` must name an application instance rather than a factory (`main.rs:197-213`), so `goe.listener.asgi` keeps a module-level `app` whose construction performs no I/O; `vtb run --worker-only` sets `VERTEBRA_WORKER_ONLY` (`cli/run.py:108`) but no module reads it, and GOE does not rely on it because the GOE job worker runs without HTTP on its own.

---

## Queue Decision

| Candidate | Verified Behavior | Verdict for GOE |
| :--- | :--- | :--- |
| **`litestar-queues` (current)** | `src/goe/listener/app.py:46-52` uses `QueueConfig(queue_backend="memory", worker=WorkerConfig(placement="asgi"))`: each HTTP worker owns a private in-memory queue, the worker starts through ASGI lifespan, and the three periodic jobs in `src/goe/listener/jobs.py:25-43` only write cache keys that no endpoint reads. | Remove. |
| **Vertebra `vertebra.framework.queues`** | `OracleQueueBackend._build_executor` (`framework/queues/oracle.py:569-574`) returns `_InMemoryOracleQueueExecutor` even when `oracledb` is installed. `CLAIM_ORACLE_JOBS_SQL` (`oracle.py:69-81`) binds a Python list to `IN (:lanes)`, combines `FETCH FIRST` with `FOR UPDATE` (Oracle rejects a row-limiting clause with `FOR UPDATE`), declares three placeholders while `dequeue` passes six values (`oracle.py:348-356`), and never moves claimed rows to `running`. `acquire_lease` reads a row back from a `MERGE` (`oracle.py:525-544`). The `QueueBackend` protocol (`base.py:133-202`) has no visibility extension while `visibility_timeout_seconds` defaults to 60 (`base.py:124`), `WorkerRunner.run` awaits `process_once` serially (`lanes.py:214-233`), and `vtb workers run` builds a `WorkerRunner` without a `QueueService` and exits after entering the lifespan (`cli/workers.py:19-46`). | Do not adopt. A 24-hour offload would be reclaimed and re-run after 60 seconds. |
| **GOE-owned durable job queue on `sqlspec`** | One job type (`offload`), Oracle repository tables (`GOE_LISTENER_JOBS` and `GOE_LISTENER_ENDPOINTS`) with `SELECT ... FOR UPDATE SKIP LOCKED` claims (row-limited in the cursor fetch, not in SQL), heartbeat-renewed leases, a function-based unique index enforcing one active job per frontend table across hosts, cooperative cancellation (`CANCEL_REQUESTED`), and repository-backed status. | Adopt. `OracleJobStore` backed by `OracleDatabaseRegistry.for_options(config)` persists jobs in the Oracle repository schema. |

The GOE job worker runs inside the Listener lifespan by default and alone (no HTTP) under `goe listener start --worker-only`. The listener heartbeat becomes a durable node row in the same store, which `/api/system/status/` reports.

---

## Vertebra Subsystems GOE Does Not Adopt

| Subsystem | Evidence | Reason |
| :--- | :--- | :--- |
| **`vertebra.db` drivers** | `src/rs/vertebra-db/Cargo.toml:14-35` declares no database driver crate; `src/py/vertebra/db/oracle.py:688-694` (`SyncOracleDriver`) executes on `sqlite3.connect(":memory:")`. | GOE keeps `sqlspec` with `python-oracledb` 26.0.1. |
| **`vertebra.storage` / `vertebra-storage`** | At `cf5979e`, `ObjectStoreEngine::put_file` reads whole files with `tokio::fs::read` and the store lacks `if_generation_match=0` and `dry_run`. | GOE consolidates on `sqlspec.storage` (`obstore`). |
| **`vertebra.telemetry.SqlTracePropagator`** | `telemetry/db_propagation.py:18-62` overwrites `conn.module` and `conn.action`. | GOE's transport statistics query `gv$sql` by `MODULE` and `ACTION` (`LOG_SQL_STATS_QUERY_TEXT`). |
| **`vertebra.build.packaging` (`OnefileBuilder`)** | `build/packaging/onefile.py` launches the host `python3`. | `tools/bundle_python.py` with `python-build-standalone` and PyApp already produces self-contained executables. |

---

## Pure-Python Idioms Ported into GOE

### `goe.typing` and `goe._typing`

`msgspec.Struct` models in `src/goe/persistence/schemas.py:11-190`, `src/goe/config/options.py:1-365`, and `src/goe/listener/schemas.py` omit `gc=False`, and `src/goe/listener/config/application.py:19-67` uses a `@dataclass`. On wide tables with tens of thousands of subpartitions, every struct instance carries a `PyGC_Head` and is traversed by cyclic garbage collection. The port follows `src/py/vertebra/typing.py:1-143` and `_typing.py:1-295`:

```python
from typing import Any

import msgspec


class EmptyType(msgspec.Struct, frozen=True, gc=False):
    """Sentinel representing an explicitly unset optional field."""


UNSET = EmptyType()
type MaybeEmpty[T] = T | EmptyType


class BaseStruct(msgspec.Struct, gc=False, omit_defaults=True, repr_omit_defaults=True):
    """Mutable GC-exempt msgspec Struct base for local builders."""


class FrozenBaseStruct(
    msgspec.Struct,
    frozen=True,
    gc=False,
    omit_defaults=True,
    repr_omit_defaults=True,
):
    """Immutable, hashable, GC-exempt msgspec Struct base for GOE value objects."""

    def to_dict(self) -> dict[str, Any]:
        """Convert struct fields into a plain dictionary."""
        return msgspec.structs.asdict(self)
```

Hot-path tuple-like records (`SourcePartitionSlice`) add `array_like=True`.

### Cached `module_loader` and PEP 562 `lazy_exports`

`src/goe/cli/_lazy.py:1-36` reduced `goe --help` from 1,476 ms to 169 ms, while factories and optional adapters still probe imports ad hoc. `src/goe/util/module_loader.py` (modeled on `src/py/vertebra/utils/module_loader.py:1-192`) provides a positive module cache, negative lookup caching with `reset_dependency_cache()`, `module_available`, `import_optional`, `ensure_module(name, extra=...)` with standard `pip install goe[<extra>]` remediation, and `lazy_exports` that binds resolved attributes into `module.__dict__`.

### Centralized `msgspec` Serializers

`src/goe/util/json_tools.py:15-36` allocates a new `msgspec.json.Encoder` on every fallback call. `src/goe/util/serializers.py` (modeled on `src/py/vertebra/utils/serializers/_json.py:1-199`) exposes `encode_json`, `encode_json_bytes`, `encode_json_into`, `decode_json`, and `format_json` over one module-level encoder whose hook covers `UUID`, `Path`, `Decimal`, `datetime`, `ExecutionId`, and predicate objects.

### Container-Aware `CgroupQuota` and `LameDuckController`

Inside Kubernetes and Cloud Run, `os.cpu_count()` and `/proc/meminfo` report the host node. `src/goe/util/platform.py` (from `src/py/vertebra/server/platform.py`) supplies:
- **DuckDB memory ceiling**: `memory_limit = min(configured, floor(0.75 * cgroup_available_bytes))`, with `tmpfs` detection for spill directories.
- **CPU sizing**: DuckDB `threads`, Arrow worker pools, and Listener worker counts clamp to `CgroupQuota.detect().effective_cpus()`.
- **Graceful drain**: readiness returns `503` during SIGTERM drain while running offload jobs record their final repository step status.

### AST Architecture Gate (`tools/verify_architecture.py`)

Modeled on `tools/scripts/review_setup.py:1504-1818`, the gate runs in `make lint` and enforces: top-level imports only (outside `if TYPE_CHECKING:`), optional dependencies through `goe.util.module_loader`, `FrozenBaseStruct`/`BaseStruct` instead of `@dataclass` or bare `msgspec.Struct`, JSON through `goe.util.serializers`, no inline `#` comments after the SPDX header, and valid OKF frontmatter and relative links under `.agents/bundles/`.

---

## Primary Sources, Contradictions, and Limitations

### Cited Primary Sources
- `cofin/vertebra` at `df36a30`: `pyproject.toml:1-119`, `README.md:1-70`, `.github/workflows/{release.yaml,release-binaries.yml}`, `src/rs/vertebra-http/src/{main.rs:1-363, config.rs:1-284, response.rs:97, workers/supervisor.rs:1-204}`, `src/rs/vertebra-db/{Cargo.toml, src/oracle.rs}`, `src/py/vertebra/cli/{run.py:1-188, workers.py:1-78, _launch.py:1-44}`, `src/py/vertebra/supervisor/{__init__.py, _supervisor.py:1-162, _worker.py:1-149}`, `src/py/vertebra/server/{worker.py:280-400, lanes.py:1-321, _asgi/_runner.py:1-140, platform.py}`, `src/py/vertebra/extensions/litestar/plugin.py:1-198`, `src/py/vertebra/framework/queues/{__init__.py, base.py:1-726, oracle.py:1-574}`, `src/py/vertebra/db/oracle.py:688-694`, `.agents/bundles/specs/runtime-throughput-and-315/spec.md`.
- GOE at `d6a02fe`: `pyproject.toml:25-71`, `src/goe/listener/{app.py:1-82, jobs.py:1-43, services/periodic_tasks.py:22-34}`, `src/goe/cli/commands/listener.py:1-204`.

### Contradictions Resolved
1. **Request-body buffering versus runtime fitness**: `response.rs:97` buffers request bodies and SHM ring tiers bound payload sizes, which matters for upload-heavy services but not for the GOE Listener's small JSON payloads; the blockers for GOE are the six gaps above, so the decision is adoption behind a release gate.
2. **Queue docstrings versus implementation**: `framework/queues/oracle.py:1` describes an Oracle `FOR UPDATE SKIP LOCKED` backend while `_build_executor` returns the in-memory emulator; resolved by a GOE-owned queue.
3. **Wheel contents versus `vtb run`**: `vtb run` requires `vertebra-server` while the wheel contains only the extension module; resolved by gap R3.

### Limitations
- Findings come from static reading at `df36a30` plus the benchmark baseline recorded at `cf5979e`. The GOE Listener has not been served by Vertebra end to end; the release-gate chapter adds that integration test.

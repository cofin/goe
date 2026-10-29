---
type: Research
research_id: "goe-architecture-redesign-module-blueprint"
title: "Module-by-Module Redesign Blueprint, Defect Ledger, and Consolidation Budget"
description: "Complete subsystem-by-subsystem functional preservation contract, primary-source defect ledger, target package topology, and line-of-code consolidation budget across GOE."
scope: architecture
tags: [redesign, modules, consolidation, defects, cli, orchestration, frontends, backends, listener]
status: stable
state: promoted
promoted_to: prd_05_foundation_typing_settings_and_adapter_reduction_20261024
created_at: 2026-10-24T15:57:00Z
updated_at: 2026-10-24T16:40:00Z
---

# Module-by-Module Redesign Blueprint, Defect Ledger, and Consolidation Budget

This chapter maps every package in `src/goe/` (74,758 LOC across ~200 Python files), `sql/`, `templates/conf/`, `tools/`, and `pyproject.toml` to its target architecture, enumerates every latent runtime defect uncovered during the parallel primary-source audit, and specifies the exact preservation contract ensuring 100% functional parity.

---

## Codebase Consolidation Budget (74,758 LOC -> ~22,800 LOC, -69.5%)

The budget below removes the Sqoop transport (511 LOC), the MapRFS filesystem scheme, and the Teradata frontend and repository client (3,154 LOC, plus 2,135 LOC of Teradata test framework code) instead of carrying them forward.

| Domain Subsystem | Current Packages | Current LOC | Target Packages | Target LOC | Reduction | Primary Consolidation Driver |
| :--- | :--- | ---: | :--- | ---: | ---: | :--- |
| **Core Typing, Platform & Utilities** | `src/goe/util/` (19 files, 5,906 LOC, including 3,386 LOC of misplaced Hadoop modules) | ~2,520 *(non-Hadoop)* | `src/goe/typing.py`, `src/goe/_typing.py`, `src/goe/util/{module_loader,serializers,platform}.py` | ~750 | **-70%** | Dissolve `misc_functions.py` (723), `ora_query.py` (348), `json_tools.py` (56), `sync_tools.py` (30), `simple_timer.py` (33); move Hadoop/staging/config/log helpers to owning domains. |
| **CLI, Settings, Options, Exceptions & `goe connect`** | `src/goe/cli/`, `src/goe/config/`, `src/goe/connect/`, `src/goe/exceptions.py` | ~6,373 | `src/goe/cli/`, `src/goe/config/{settings,option_registry,password_tools,gcp_credentials}.py`, `src/goe/connect/` | ~3,130 | **-51%** | Declarative `OptionSpec` registry + side-effect-free `GOESettings(FrozenBaseStruct)` replacing 6-way option/config duplication; concurrent `ConnectRunner` returning `ConnectReport`. |
| **Orchestration, Offload Planner, Metadata, IPA & Registry** | `src/goe/orchestration/`, `src/goe/offload/{offload,column_metadata,offload_source_table,offload_source_data,factory,operation}/`, `goe.py` | ~12,500 | `src/goe/orchestration/{context,sinks,executor,locks}.py`, `src/goe/offload/{plan,boundary,schema,registry}.py` | ~4,800 | **-62%** | Pure staged planner -> `OffloadPlan(FrozenBaseStruct)` + `StatelessOffloadExecutor` + `ContextVar` `ExecutionContext`; `ColumnSpec` + `ColumnDialectMapper` replacing 10 `*_column.py` subclasses; 1 `AdapterRegistry` replacing 8 `factory/*.py` files. |
| **SQL AST, Predicates & Cross-DB Validation** | `src/goe/offload/{sql_engine,predicate_offload,offload_predicate,*_literal,*_predicate,offload_validation}.py`, `scripts/agg_validate.py` | ~2,988 | `src/goe/offload/sql_engine.py`, `src/goe/offload/sql_ast/{predicate_ir,predicate_compiler,dialect_engine}.py`, `src/goe/offload/validation/` | ~610 | **-80%** | `@lru_cache` Lark -> `PredicateIR` -> `sqlglot` (`copy=False`) + `NamespacedCache` retiring 8 `*_literal.py` and 6 `*_predicate.py` classes; concurrent `CrossDbValidator` + `goe validate --diff`. |
| **Frontends (Oracle, MSSQL) & Persistence** | `src/goe/offload/{frontend_api,offload_transport_rdbms_api,oracle,microsoft/mssql_*}/`, `src/goe/persistence/` (Teradata removed) | ~6,350 | `src/goe/persistence/{registry,models,oracle_repo_service,retry,sql}/`, `src/goe/frontend/{base,oracle,mssql}/` | ~3,000 | **-53%** | Pooled `SQLSpec` (`OracleSyncConfig`, `MssqlPythonConfig`), 1-RTT `OffloadMetadata(FrozenBaseStruct)`, 3-query cached `OracleTableCatalogSnapshot`, pure-Python stats RAW decoder + Arrow column sampler. |
| **Backend Cloud DW Adapters (BigQuery, Snowflake, Synapse, Hadoop)** | `src/goe/offload/{backend_api,backend_table,bigquery,snowflake,microsoft/synapse_*,hadoop,spark}/` + relocated Hadoop utils (`3,386` LOC) | ~23,847 | `src/goe/backend/{capabilities,catalog_cache,type_registry,ingest,table_operations,bigquery,snowflake,synapse,hadoop}/` | ~4,950 | **-79%** | Replace 96-method `BackendApiInterface` + 50-forwarder `BackendTableInterface` + 57 dead `NotImplementedError` stubs with `BackendCapabilities`, `CachedBackendCatalog`, `DialectSqlEngine`, `CanonicalTypeRegistry`, and `BackendIngestStrategy` (direct BigQuery load / Storage Write). |
| **Transport, Staging & Cloud/HDFS Filesystems** | `src/goe/offload/transport/`, `src/goe/offload/staging/`, `src/goe/filesystem/` | ~8,930 | `src/goe/transport/{planner,stats_poller,canary,duckdb,spark}/`, `src/goe/filesystem/{dfs,object_store,hdfs,sftp}.py` | ~2,800 | **-69%** | Unified DuckDB 2.0 (`duckdb-oracle` v0.3.1 OCI + Clientless Thin Arrow -> Parquet -> `httpfs`) retiring row-by-row `QueryImport` encoders; decomposed `transport/base.py` + 1 `TransportCanaryProbe`; `sqlspec.storage` (`ObStoreBackend`) cloud DFS. |
| **Schema Sync & Offload Status Report** | `src/goe/schema_sync/` (1,192), `src/goe/report/` (3,799) | ~4,991 | `src/goe/schema_sync/{models,planner,service}.py`, `src/goe/report/{models,collector,rollup,renderers}.py` + `demo_report.json.gz` | ~820 | **-84%** | Single-pass catalog diffing + `sqlglot` `exp.Alter`; 2 set-based `SQLFileLoader` queries + `:memory:` DuckDB 2.0 `GROUP BY ROLLUP` + compressed JSON demo fixture replacing 1,502-LOC `demo_data.py`. |
| **Litestar Listener & OpenTelemetry Observability** | `src/goe/listener/` (1,979), `src/goe/observability/` (1,590) | ~3,569 | `src/goe/listener/` (~1,560), `src/goe/observability/` (~1,470) | ~3,030 | **-15%** | Vertebra runtime, async/pooled non-blocking endpoints, GOE-owned durable job queue on `sqlspec` (`OracleJobStore` on `GOE_LISTENER_JOBS` and `GOE_LISTENER_ENDPOINTS`), bounded `ListenerCache`, authenticated `/mcp` + native `litestar-mcp` tools/resources/prompts/skills + `ConfirmationGate`, zero-RTT TTC session tracing. |
| **Total Application Codebase** | **`src/goe/` (~200 `.py` files)** | **~74,758** | **`src/goe/` (~100 `.py` files)** | **~22,800** | **-69.5%** | **Functional parity for every retained capability with a unified `msgspec` + `SQLSpec` + `sqlglot` + DuckDB 2.0 + Litestar + Vertebra architecture.** |

---

## Primary-Source Defect Ledger (Verified Across `src/goe/` at `HEAD`)

Every defect listed below was verified directly in primary source files during the module audit and must be resolved with dedicated regression unit tests during redesign execution:

### A. Concurrency, Thread-Safety, and Event-Loop Blocking Defects
1. `src/goe/orchestration/logging_init.py:35-145`: Module-global mutable `log_fh`, `options`, `suppress_stdout_override`, and `ts` race and cross-contaminate log files when concurrent `litestar-queues` jobs execute in one process.
2. `src/goe/listener/services/orchestration.py:24-62` & `src/goe/orchestration/orchestration_runner.py:112-160`: Shared `_runner` singleton mutates `self._execution_id` and `self._messages` across concurrent jobs.
3. `src/goe/orchestration/execution.py:442`: Calls `config.override_offload_dfs_config(...)`, mutating `OrchestrationConfig` in place during table execution.
4. `src/goe/orchestration/operation.py:181-196` & `src/goe/offload/transport/duckdb_transport.py:209`: Mutates process-global `os.environ["NLS_LANG"]` and `os.environ["ORA_SDTZ"]` at runtime from execution/worker threads.
5. `src/goe/offload/transport/duckdb_transport.py:164-220`: Opens $N$ separate `:memory:` DuckDB `DatabaseInstance` objects across `ThreadPoolExecutor` workers, multiplying `memory_limit` by `parallelism` (`N * memory_limit` container OOM risk).
6. `src/goe/listener/controllers/system.py:34, 43-95` & `src/goe/listener/app.py:38`: `Provide(get_system_service, sync_to_thread=False)` and unwrapped `repo.get_db_unique_name()` execute synchronous `oracledb` TCP round-trips directly on the ASGI event loop; `utils/network.py:15-52` runs blocking `socket.getfqdn()` / `connect()` DNS/UDP probes on the event loop.
7. `src/goe/listener/controllers/orchestration.py:55-98`: Blocks the ASGI event loop on synchronous `filelock` checks and unbounded `Path.read_text()` log slurping, fails to support `gs://` `OFFLOAD_LOGDIR`, does not validate `execution.options.log_path` containment, and hardcodes `is_file=True` in `get_command_execution_log` (`exceptions/handlers.py:64` `LogFileNotFoundError` is never raised).
8. `src/goe/listener/app.py:46-52` & `src/goe/listener/config/application.py:27`: `QueueConfig(queue_backend="memory")` combined with `http_workers: int = 2` creates isolated per-worker in-memory queues (jobs enqueued on Worker A return `404` or stall on Worker B, and periodic cron tasks run $N$ duplicate times); `cli/commands/listener.py:191-193` `--worker-only` is a dead flag ignored by `Granian`.

### B. Database Connection Leaks, Auth Bugs, and Broken SQL/Transport Wiring
9. `src/goe/offload/oracle/oracle_frontend_api.py:472`: Proxy connection override `(f"{ora_adm_user}[{override}]", ora_app_pass)` passes `ora_app_pass` instead of `ora_adm_pass`, failing with `ORA-01017` whenever `ORA_ADM_PASS != ORA_APP_PASS` without an Oracle Wallet.
10. `src/goe/offload/oracle/oracle_frontend_api.py:237`: `get_distinct_column_values` interpolates `f" PARTITION ({partition_name})"` without `enclose_identifier(partition_name)`, breaking mixed-case or hyphenated partition names (`ORA-00926` / `ORA-14108`).
11. `src/goe/persistence/oracle/oracle_orchestration_repo_client.py:304-366` & `src/goe/listener/services/system.py:26-34`: Every Listener `/schemas`, `/tables`, `/columns`, and `/partitions` request instantiates a fresh unpooled `OracleFrontendApi` + `OffloadSourceTable.create(...)` and never closes them, leaking 1–3 Oracle sessions per HTTP/MCP call until Python GC runs.
12. `src/goe/orchestration/operation.py:1181, 1194`: Hardcodes `created_api = False` (leaking newly opened `BackendApi` connections on exit) and calls `get_hybrid_metadata(offload_options)` (passing the options object into `force: bool`).
13. `src/goe/orchestration/execution.py:438-439`: Instantiates `OffloadException("...")` as a bare statement without `raise`, silently continuing execution past a fatal guard failure.
14. `src/goe/offload/transport/duckdb_constants.py:6`, `duckdb_availability.py:42-60`, `duckdb_engine.py:75-120`: Pins `"1.5.5"` against installed `duckdb==2.0.0` (disabling DuckDB transport 100% of the time), uses unported `northpolesec/duckdb-gcs` (`gcss://`), sets `allow_unsigned_extensions="true"`, and omits `SET oracle_call_timeout_ms = 0;` (leaving `duckdb-oracle` v0.3.1's 30s `OCI_ATTR_CALL_TIMEOUT` active on long full scans).
15. `src/goe/listener/security.py:114`: `SecurityConfig(exclude=[..., r"^/mcp"])` bypasses `ConsoleKeyAuthenticator` on `POST /mcp`, exposing `initialize`/`tools/list` unauthenticated and starving `SecureController` MCP tool sub-requests of `SecurityContext` after `LitestarMCP` strips inbound HTTP headers.
16. `src/goe/listener/services/periodic_tasks.py:34-145` & `src/goe/listener/utils/cache.py:18`: Periodic jobs write double-JSON-encoded metadata keys (`goe:listener:metadata:*`) into an unbounded `dict` that **zero** controller or service paths ever read, while `OrchestrationRunner` runs in a child worker/thread context where `CommandStepEvent` step progress never reaches the HTTP worker's cache.

### C. Precision, Validation, Cloud Storage, Schema Sync, Report, and CLI Defects
17. `src/goe/offload/offload_predicate.py:130-155` & `src/goe/offload/offload_validation.py:695, 725-770`: `float()` conversion in `GenericPredicateToTyped` and `OffloadValidation` corrupts 16..38-digit `Decimal` values and 9-digit nanoseconds; positional `zip()` misaligns `GROUP BY` validation rows when `NULL` sort order differs across dialects.
18. `src/goe/scripts/agg_validate.py:92-145`: `REGEX_FILTER` rejects valid SQL expressions and `.replace('"', '`')` corrupts string literals containing double quotes.
19. `src/goe/filesystem/goe_gcs.py:258`, `goe_azure.py:14, 159, 326`, `goe_s3.py:137`: `GOEGcs.stat()` calls unbounded `list_blobs(prefix=...)` without `max_results=2`; `GOEAzure` catches removed v2 `AzureMissingResourceHttpError` instead of v12 `ResourceNotFoundError`; `GOES3.delete()` fails to chunk >1,000 keys per `delete_objects` request.
20. `src/goe/schema_sync/schema_sync_analyzer.py:49-57`, `steps/add_oracle_column.py:55-65`, `present_table`: Dead `ddl_compare` has raw f-string SQL injection; `add_oracle_column.py` leaks its proxy Oracle connection; `PRESENT_TABLE` raises `NotImplementedError`; generated command files emit stray trailing `}');`.
21. `src/goe/report/renderers.py` & `goe_components.html:352`: Broken Jinja2 `templates/` resolution path, missing `INCREMENTAL_PREDICATE_TYPE` variable reference, and undeclared transitive `jinja2` dependency in `pyproject.toml`.
22. `src/goe/offload/microsoft/mssql_frontend_api.py:295-363` & `src/goe/persistence/teradata/teradata_orchestration_repo_client.py:210-266`: `MSSQLFrontendApi` quotes `'%s'` inside SQL literals (fixed by `MssqlPythonConfig` with `?` parameters); the Teradata `_set_metadata` `MERGE` references nonexistent `OFFLOADED_OWNER`/`OFFLOADED_TABLE` columns on normalized `offload_metadata` (resolved by removing the Teradata frontend and repository client).
23. `src/goe/config/orchestration_config.py:120-290`, `cli/common.py`, `connect/connect_functions.py`: `OrchestrationConfig.__init__` connects to live DBs and calls global `oracledb.init_oracle_client()` during config construction and mutates multi-host CSV lists via `random.choice()`; 5 OTel settings in `ObservabilitySettings` lack CLI flags in `cli/common.py`; Listener port/heartbeat defaults drift (`8085` vs `8000`, `30s` vs `60s`); `goe connect` uses module-global `failures`/`warnings` booleans, raw `SYS_CONTEXT` SQL concatenation, `/etc/os-release` `lines[0]` parsing, and aborts all remaining SSH hosts on first failure.

---

## Removed Adapters

The redesign removes three adapters instead of porting them:

| Adapter | Current Footprint | Removal Scope |
| :--- | :--- | :--- |
| **Sqoop transport** | `src/goe/offload/hadoop/sqoop_offload_transport.py` (511 LOC) plus `SQOOP` constants, availability checks, factory branches, canary probe, `--offload-transport-method=SQOOP`, Sqoop option keys, `templates/conf/offload.env.template.hadoop` variables, integration scenarios, and unit tests (25 `src/goe` files reference Sqoop). | Delete the transport, its options and configuration keys, template variables, documentation, and tests; `AUTO` transport selection no longer considers Sqoop. |
| **MapRFS filesystem scheme** | `OFFLOAD_FS_SCHEME_MAPRFS` and `BACKEND_DISTRO_MAPR` handling in `src/goe/filesystem/goe_dfs.py:49-62`, `src/goe/config/config_validation_functions.py:17, 156`, and the `maprfs:` location pattern in `src/goe/util/hive_ddl_transform.py:222-238`. | Delete the scheme, the MapR distribution value, its validation, and the DDL location pattern. |
| **Teradata frontend** | `src/goe/offload/teradata/` (2,886 LOC), `src/goe/persistence/teradata/` (268 LOC), factory branches, `templates/conf/offload.env.template.teradata`, the `teradata` extra, `tests/testlib/test_framework/teradata/` (1,826 LOC), `tests/unit/offload/test_teradata_partition_expression.py`, and `.agents/bundles/knowledge/frontends/teradata.md`. | Delete the frontend, repository client, configuration template, extra, test framework, tests, and knowledge chapter. |

## Subsystem-by-Subsystem Redesign Blueprint and Preservation Contracts

### 1. Core Foundation (`src/goe/typing.py`, `src/goe/_typing.py`, `src/goe/util/`, `pyproject.toml`)
- **Target Topology**:
  - `src/goe/typing.py` & `src/goe/_typing.py`: `FrozenBaseStruct`, `BaseStruct`, `EmptyType` / `UNSET`, `OptionalDependency`.
  - `src/goe/util/module_loader.py`: Cached `import_optional`, `ensure_module`, `module_available`, PEP 562 `lazy_exports`.
  - `src/goe/util/serializers.py`: Centralized `msgspec` `JSONSerializer` (`encode_json`, `encode_json_bytes`, `encode_json_into`, `decode_json`, `format_json` with `ExecutionId` / `Decimal` / `datetime` hooks).
  - `src/goe/util/platform.py`: Container-aware `CgroupQuota` (`effective_cpus`, `effective_memory_bytes`, `recommended_duckdb_memory_limit`, `recommended_workers`) and `LameDuckController`.
- **Preservation Contract**:
  - Relocate `password_tools.py` and `gcp_credentials.py` to `src/goe/config/`, preserving **100% binary compatibility with AES-256-CBC + PKCS7 `$OFFLOAD_HOME` keyfiles** (`PasswordTools` interoperates with external C++ `pass_tool` and existing encrypted `offload.env` passwords; strip only the 31-line `__main__` demo block).
  - Relocate the 3,386 LOC of Hadoop/Hive/Impala helpers (`better_impyla.py`, `hive_table_stats.py`, `hive_ddl_transform.py`, `hs2_connection.py`) into `src/goe/backend/hadoop/` behind `lazy_exports` so non-Hadoop workflows never import `impala`, `thrift`, or `sasl`.
  - Slim `pyproject.toml` core dependencies from 31 to 22 packages (removing unused `PyYAML`, `tenacity`, `brotli`, superseded `fsspec[gcs]` and `python-dateutil`, deprecated `azure-common`, moving `boto3`, `azure-storage-blob`, and `fastavro` to extras, and adding explicit `jinja2>=3.1.4`), and eliminate the 13 bug-masking Ruff rule ignores (`E722`, `B006`, `B008`, `B012`, `B020`, `B023`, `B904`, `F504`, `F507`, `F811`, `RUF006`, `RUF012`, `RUF013`) by fixing the underlying code.

### 2. CLI, Configuration, Options, Templates & `goe connect` (`src/goe/cli/`, `src/goe/config/`, `src/goe/connect/`)
- **Target Topology**:
  - `src/goe/config/settings.py`: Immutable `GOESettings(FrozenBaseStruct)` loaded purely from environment + `offload.env` (`config_file.py` 4-tier discovery preserved unchanged) with **zero network connections, zero global `oracledb.init_oracle_client()` side effects, and zero `random.choice()` mutation** during construction.
  - `src/goe/config/option_registry.py`: Single declarative `OptionSpec(FrozenBaseStruct)` catalog driving `rich-click` CLI flags, `OPTION_GROUPS`, `OffloadOperationOptions(FrozenBaseStruct)`, `AggValidateOptions`, `ConnectOptions`, `StatusReportOptions`, `SchemaSyncOptions`, and Listener `MsgspecDTO[OffloadOperationOptions]` (deleting `listener/schemas.py::OffloadOptions` and `operation.py::from_dict`).
  - `src/goe/exceptions.py`: Cohesive `GOEError` hierarchy (with `OffloadException = GOEError` alias preserving existing caller catches and CLI exit codes `0`/`1`/`2`).
  - `src/goe/connect/runner.py`: Stateless concurrent `ConnectRunner` executing independent frontend, backend, storage, SSH, and DuckDB 2.0 + `oracle` v0.3.1 + `httpfs` probes in parallel and returning `ConnectReport(FrozenBaseStruct)` (`ConnectCheckResult` items rendered via Rich console or JSON for Listener `/api/system/connectivity/`).
  - `templates/conf/`: Reconcile `offload.env.template.*` with `GOESettings` (documenting DuckDB 2.0, `GOE_OTEL_*`, keyless GCP ADC/WIF, and aligned Listener port/worker/queue defaults).
- **Preservation Contract**: Every `goe` subcommand (`offload`, `connect`, `validate`, `sync`, `report`, `listener`, `logmgr`), every CLI flag/alias, and 4-tier `offload.env` auto-discovery (`GOE_NO_AUTOLOAD_ENV=1` / `PYTEST_CURRENT_TEST` bypass) behave identically.

### 3. Orchestration, Offload Planner, Boundary/IPA Math & Registry (`src/goe/orchestration/`, `src/goe/offload/`)
- **Target Topology**:
  - `src/goe/orchestration/context.py` & `sinks.py`: `ContextVar`-bound `ExecutionContext(FrozenBaseStruct)` routing structured events to `LogFileSink` (local `Path.open` or `google.cloud.storage.Blob.open("w")` with zero `fsspec`), `ConsoleSink` (preserving byte-exact stdout text formatting), `TelemetrySink` (OTel spans/metrics), `RepositoryStepSink` (`COMMAND_EXECUTIONS` / `COMMAND_EXECUTION_STEPS`), and `ListenerMemoryCacheSink`.
  - `src/goe/offload/plan/`: Pure staged planner (`SourceDiscoveryStage` -> `PartitionBoundaryStage` -> `TypeResolutionStage` -> `TargetTableStage` -> `TransportPlanStage`) producing an immutable, serializable `OffloadPlan(FrozenBaseStruct)` (`SourcePartitionSlice` with `array_like=True, frozen=True, gc=False`). `--dry-run` (`execute=False`) and MCP `plan_offload_dry_run` simply run the planner and render `OffloadPlan` without touching target state.
  - `src/goe/orchestration/executor.py`: `StatelessOffloadExecutor` acquiring `OrchestrationLockInterface` (`filelock` in `$OFFLOAD_HOME/run/`) and executing `OffloadPlan` steps deterministically.
  - `src/goe/offload/schema/`: Frozen `ColumnSpec(FrozenBaseStruct)` + stateless `ColumnDialectMapper` replacing mutable `ColumnMetadataInterface` and 10 `*_column.py` subclasses.
  - `src/goe/offload/registry.py`: Single declarative `AdapterRegistry` (`LazyTarget` + unified `resolve_dry_run()`) replacing 8 `src/goe/offload/factory/*.py` modules.
- **Preservation Contract**: Preserves 100% of Incremental Partition Append (`IPA`) semantics (`100/0`, `90/10`, `100/10`, `RANGE`, `LIST`, composite `SUBPARTITION`, Partition-Based Offload `PBO`, `--older-than-date`, `--older-than-days`, `--less-than-value`, `--equal-to-values`, predicate-based offload, `--reset-backend-table`, `--reset-hybrid-view`, `--offload-chunk-column`, `--offload-chunk-size`, and post-offload verification).

### 4. Frontends, Persistence & `sql/oracle/` (`src/goe/persistence/`, `src/goe/frontend/`)
- **Target Topology**:
  - `src/goe/persistence/registry.py`: `OracleDatabaseRegistry` (`OracleSyncConfig` / `OracleAsyncConfig` pools for `oracle_adm` and `oracle_app`, `proxy_ddl_session` using `ora_adm_pass`, shared `StatementCacheHolder` + `ObservabilityRuntime`, 1-time `session_callback`, and mypyc-safe sniped-session retry).
  - `src/goe/persistence/models.py` & `oracle_repo_service.py`: Immutable `OffloadMetadata(FrozenBaseStruct)` loaded in 1 RTT from `offload_metadata_v` (`fetch_lobs=False`) and persisted via per-connection cached `OFFLOAD_METADATA_OT` / `OFFLOAD_PARTITION_NTT` UDTs.
  - `src/goe/frontend/oracle/`: `OracleCatalogService` (3-query consolidated snapshot cached in `FrontendCatalogCache` without cartesian `P * S` `LONG` `high_value` duplication, supporting Oracle 23ai `high_value_clob`), pure-Python `DBA_TAB_COL_STATISTICS` `RAW` decoder + `select_to_arrow` `SAMPLE BLOCK` column precision sampler, and `OracleExtractionQueryBuilder` (`ROWID` extent, `PARTITION`, `SUBPARTITION`, `ORA_HASH`, `ID_RANGE` with `AS OF SCN`).
  - `src/goe/frontend/mssql/`: Backed by `MssqlPythonConfig` (`?` parameters, Entra ID, native Arrow + `bulkcopy`).
- **Preservation Contract**: Zero breaking changes to installed Oracle `OFFLOAD` / `OFFLOAD_REPO` PL/SQL packages or repository tables (`sql/oracle/**`), full Wallet/Kerberos/LDAP/Thick/Thin parity, and intact `gv$sql` `MODULE`/`ACTION` transport SQL statistics.

### 5. Backend Cloud DW Adapters (`src/goe/backend/`)
- **Target Topology**:
  - `BackendCapabilities(FrozenBaseStruct)` replacing 34-key capability dicts and 57 dead `NotImplementedError` methods.
  - `CachedBackendCatalog` (write-through TTL `BackendTableSnapshot` + 2-query `warm_schema` `INFORMATION_SCHEMA` loader).
  - `DialectSqlEngine` (`sqlglot` ASTs) + `CanonicalTypeRegistry` (table-driven bidirectional canonical <-> physical type resolution with precision/scale/byte-length guards and synthetic partition transforms `GOE_PART_*`).
  - Pluggable `BackendIngestStrategy`:
    - `BigQueryDirectLoadStrategy`: Single atomic `load_table_from_uri(..., WRITE_APPEND)` job over target-typed DuckDB Parquet (`DecimalTargetTypes = [NUMERIC, BIGNUMERIC, STRING]`, CMEK via `BigQueryConfig.default_load_job_config`) — **1 BigQuery job instead of 6, 0 SQL scan bytes billed, 0 paid query slots**.
    - `BigQueryStorageWritePendingStrategy`: Opt-in / low-latency `PENDING` Arrow stream + atomic `BatchCommitWriteStreams` with zero GCS staging files.
    - `StagedLoadInsertStrategy`: Automatic fallback for stringified Spark staging transports, backend GoogleSQL UDF synthetic partition expressions, `--offload-chunk-column`, and `--preserve-load-table`, plus Snowflake (`COPY INTO` / staged `INSERT`), Synapse (`COPY INTO` / PolyBase / CTAS), and Hive/Impala (`LOAD DATA` / `INSERT INTO` + `hive_table_stats`).
- **Preservation Contract**: Every BigQuery, Snowflake, Azure Synapse, Hive, Impala, and Spark Thrift target capability (partitioning, clustering/bucketing/sorting, CMEK, labels, materialization, statistics, and staging cleanup) is preserved.

### 6. Transport, Staging, Cloud/HDFS Filesystems & `tools/` (`src/goe/transport/`, `src/goe/filesystem/`, `tools/`)
- **Target Topology**:
  - `src/goe/transport/duckdb/`: Shared execution-scoped `:memory:goe_<execution_id>` DuckDB 2.0 engine (`CgroupQuota` 75% memory clamp, per-worker `cursor()`, `SET oracle_call_timeout_ms = 0;`, `LOAD parquet; LOAD httpfs;`, `TEMPORARY SECRET` over canonical `gs://`/`s3://`/`az://`) routing automatically between signed community `duckdb-oracle` v0.3.1 OCI vectorized `oracle_query` and Clientless `python-oracledb` Thin `fetch_df_batches` -> lazy `RecordBatchReader` (`cursor.register` + `finally: cursor.unregister()`).
  - `src/goe/transport/{planner,stats_poller,command_runner,canary}.py`: Decomposed from 1,215-LOC `transport/base.py`, replacing 6 `*Canary` subclasses with 1 `TransportCanaryProbe` (adding `DUCKDB` probe coverage) and safe `PySparkCodegen` JSON/AST config injection for retained Spark/Dataproc/Livy/Thrift transports.
  - `src/goe/filesystem/`: `GOEDfs` backed by `sqlspec.storage` (`ObStoreBackend` + `LocalStore`) for `gs`, `s3`/`s3a`, `abfs`/`abfss`/`wasb`/`wasbs`, and local paths (preserving `if_generation_match=0`, `dry_run`, keyless GCP ADC/impersonation, 1,000-key S3 delete chunking, `max_results=2` virtual-dir stat, and `@traced_storage_call`), retaining `HdfsBackend`/`WebHdfsBackend` and `SftpBackend` as lazy extras.
  - `tools/`: Upgrade `GOETaskListener.scala` to SLF4J / Log4j2 and Spark `3.5.3`+, remove dead `tools/goe-shell-functions.sh`, clean `tools/bundle_python.py:64`, and add `tools/verify_architecture.py` to `make lint`.

### 7. Litestar Listener & OpenTelemetry Observability (`src/goe/listener/`, `src/goe/observability/`)
- **Target Topology**:
  - Vertebra runtime (`vtb run goe.listener.asgi:app --interface asgi`, replacing Granian once the Vertebra release gate is met), an I/O-free module-level `app`, lifespan-managed `OracleDatabaseRegistry` + `ListenerCache` + job worker, and a GOE-owned durable job queue on `sqlspec` (`OracleJobStore` backed by `OracleDatabaseRegistry.for_options(config)` on `GOE_LISTENER_JOBS` and `GOE_LISTENER_ENDPOINTS` in `ora_repo_user`) with a working `goe listener start --worker-only`; `litestar-queues` is removed.
  - End-to-end frozen `msgspec.Struct` responses (deleting `[msgspec.structs.asdict(r) for r in rows]` churn and `OffloadOptions` duplication), HTTP `409 Conflict` fast-fail on held table locks, async bounded local + `gs://` log streaming with path-containment validation, `r"^/mcp"` authenticated via `SecurityPlugin`, 4 read-only MCP diagnostic tools (`plan_offload_dry_run`, `get_table_offload_status`, `preview_schema_drift`, `check_connectivity`), and HMAC `ConfirmationGate` tokens on mutating MCP tools.
  - Zero-RTT `ObservabilityRuntime` integration across CLI, Listener, `SQLSpec`, DuckDB 2.0 batch spans, `sqlspec.storage`, and BigQuery jobs (`RowIterator` stats hook).

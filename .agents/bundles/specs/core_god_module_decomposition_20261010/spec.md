---
type: Spec
flow_id: core_god_module_decomposition_20261010
title: "Core God-Module Decomposition (Orchestration, Status Report, Source Data & Transport)"
state: planned
plan_revision: 2
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: "2026-10-10T16:00:00Z"
updated_at: "2026-10-10T16:28:00Z"
description: "Decompose the four largest core GOE god-modules (goe.py, offload_status_report.py, offload_source_data.py, offload_transport.py) totaling 12,310 lines into cohesive sub-packages with 100% feature preservation, strict dead-code elimination, and <= 60 LOC re-export facades."
tags:
  - refactoring
  - architecture
  - orchestration
  - report
  - source-data
  - transport
  - dead-code-elimination
parent_prd: prd_02_core_typing_options_and_decomposition_20261010
research: []
---

# Core God-Module Decomposition (Orchestration, Status Report, Source Data & Transport)

## Specification

### Parent Context
- **Parent PRD**: `prd_02_core_typing_options_and_decomposition_20261010` (Part B — Core God-Module Decomposition)
- **Architectural Mandate**:
  1. **100% Feature Preservation**: Do not lose any runtime feature, CLI/Listener entrypoint, offload pattern, report format/detail level, or transport validation behavior when decomposing the 4 core god-modules (`src/goe/goe.py` at 3,128 LOC, `src/goe/offload/offload_status_report.py` at 3,795 LOC, `src/goe/offload/offload_source_data.py` at 2,875 LOC, and `src/goe/offload/offload_transport.py` at 2,512 LOC — 12,310 LOC combined).
  2. **Strict Dead-Code Elimination**: Every extracted class, function, and constant **must be deleted** from the original monolith file, reducing each original file (`src/goe/goe.py`, `src/goe/offload/offload_status_report.py`, `src/goe/offload/offload_source_data.py`, `src/goe/offload/offload_transport.py`, and `src/goe/offload/factory/offload_transport_factory.py`) strictly to a **`<= 60 LOC` re-export module**, while actively purging unreachable/dead legacy functions, redundant global Redis state in `goe.py`, and commented-out code blocks.
- **Downstream Enablement**: Prepares `src/goe/offload/transport/` for clean plug-in of `OffloadTransportDuckDB` in PRD 3 and isolates `EXPECTED_OFFLOAD_ARGS` into `src/goe/orchestration/constants.py` so `src/goe/listener/schemas.py` (`OffloadOptions.to_params_dict()`) can reference canonical parameter keys without circular imports.

### Code Analysis Summary

#### 1. `src/goe/goe.py` (3,128 lines) -> `src/goe/orchestration/`
- **Constants (`src/goe/goe.py:141-242` -> `src/goe/orchestration/constants.py`)**:
  - `OFFLOAD_PATTERN_100_0, OFFLOAD_PATTERN_90_10, OFFLOAD_PATTERN_100_10 = list(range(3))` (`L143`), `OFFLOAD_OP_NAME = "offload"` (`L145`).
  - Message templates: `HYBRID_SCHEMA_STEPS_DUE_TO_HWM_CHANGE_MESSAGE_TEXT` (`L148`), `NLS_LANG_MISSING_CHARACTER_SET_EXCEPTION_TEMPLATE` (`L149`), `OFFLOAD_STATS_COPY_EXCEPTION_TEXT` (`L150`), `RETAINING_PARTITITON_FUNCTIONS_MESSAGE_TEXT` (`L151`).
  - `EXPECTED_OFFLOAD_ARGS` (`L154-240`) and `normal, verbose, vverbose = list(range(3))` (`L242`).
- **Logging, Version & Global State Initialization (`src/goe/goe.py:243-312`, `442-450`, `1032-1105` -> `src/goe/orchestration/logging_init.py`)**:
  - `dev_logger` (`L141`), `options`, `log_fh`, `suppress_stdout_override`, `execution_id` (`L243-246`), `ts` (`L442-443`).
  - `ansi` (`L252-253`), `log` (`L256-297`), `get_log_fh` (`L299-300`), `log_command_line` (`L303-306`), `log_close` (`L309-311`), `log_timestamp` (`L446-450`).
  - `version` (`L1032-1044`), `comp_ver_check` (`L1047-1050`), `version_abort` (`L1053-1057`), `strict_version_ready` (`L1060-1066`), `init_log` (`L1069-1091`), `get_log_fh_name` (`L1093-1095`), `init` (`L1098-1104`).
- **Operation Models & Option Normalization (`src/goe/goe.py:314-404`, `454-471`, `757-1030`, `1112-2241`, `2666-3127` -> `src/goe/orchestration/operation.py`)**:
  - RDBMS/NLS helpers (`ora_single_item_query`, `get_db_unique_name`, `get_rdbms_db_name`, `get_db_charset`, `nls_lang_exists`, `nls_lang_has_charset`, `set_nls_lang_default`, `check_and_set_nls_lang`, `oracle_connection`, `oracle_offload_transport_connection`).
  - Option normalization (`bool_option_from_string`, `normalise_owner_table_options`, `normalise_datatype_control_options`, `normalise_insert_select_options`, `normalise_offload_transport_method`, `normalise_offload_transport_user_options`, `valid_canonical_decimal_spec`, `option_is_in_list`, `normalise_options`, `verify_json_option`, `get_default_location_fs_scheme`, `normalise_storage_options`).
  - `BaseOperation` (`L1135-1855`) and `OffloadOperation(BaseOperation)` (`L1857-2240`).
  - CLI option builders (`check_posint`, `GOEOptionTypes`, `get_common_options`, `get_options`, `get_options_from_list`).
- **Execution & Verification Workflow (`src/goe/goe.py:414-440`, `473-691`, `2261-2659` -> `src/goe/orchestration/execution.py`)**:
  - `get_offload_type` (`L414-439`), `incremental_offload_partition_overrides` (`L473-480`), `verify_offload_by_backend_count` (`L483-534`), `verify_row_count_by_aggs` (`L537-592`), `offload_data_verification` (`L595-690`).
  - `offload_operation_logic` (`L2261-2383`), `offload_table` (`L2386-2618`), `get_offload_target_table` (`L2621-2659`).
- **Dead Code Identified in `src/goe/goe.py` for Deletion**:
  - `silent_close` (`L406-411`): 0 callers in repository.
  - `normalise_column_transformations` (`L693-754`): 62-line top-level function superseded by `BaseOperation._normalise_column_transformations` (`L1303`); 0 callers in repository.
  - `canonical_to_rdbms_mappings` (`L2243-2258`): 0 callers in repository.
  - `get_synthetic_partition_cols` (`L2662-2663`): 0 callers in repository.
  - `get_oracle_options` (`L2775-2824`): 50-line OptParse helper with 0 callers in repository.
  - Legacy `redis_execution_id`, `redis_in_error`, `init_redis_execution_id` (`L248-249`, `L269-282`, `L1071-1074`, `L1107-1109`) and `from goe.listener.utils.cache import MemorySyncCache as RedisClient` (`L24`): redundant global state superseded by `OffloadMessages` cache publishing (`src/goe/offload/offload_messages.py`).

#### 2. `src/goe/offload/offload_status_report.py` (3,795 lines) -> `src/goe/report/`
- **Models & Constants (`src/goe/offload/offload_status_report.py:63-160`, `3701-3731` -> `src/goe/report/models.py`)**:
  - Output formats (`HTML`, `TEXT`, `JSON`, `RAW`, `CSV`), levels (`DETAIL_LEVEL`, `SUMMARY_LEVEL`), defaults, dictionary keys (`SOURCE_OWNER`..`REPORT_END`), `SUMMARY_KEYS` (`L131-142`), `MULTIVALUE_KEYS` (`L144-151`), `OffloadStatusReportException` (`L159-160`), `datetime_literal_to_hv` (`L3701-3715`), `incremental_partition_match` (`L3718-3731`).
- **Collector (`src/goe/offload/offload_status_report.py:163-2680`, `3441-3698`, `3734-3794` -> `src/goe/report/collector.py`)**:
  - `OffloadStatusReport` metadata/RDBMS/backend space & partition collector, `get_offload_status_report_opts`, `normalise_offload_status_report_options`, `offload_status_report_run`.
- **Renderers (`src/goe/offload/offload_status_report.py:2682-3436` -> `src/goe/report/renderers/`)**:
  - `text_renderer.py`: `_gen_text_report` (`L2768-3344`) supporting `SUMMARY_LEVEL`, `DETAIL_LEVEL`, partition/subpartition tables, and ANSI colors.
  - `html_renderer.py`: `_gen_html_report` (`L3346-3356`) loading `src/goe/templates/offload_status_report/goe_offload_status_report.html` via `Path(__file__).resolve().parents[2] / "templates"`.
  - `structured_renderer.py`: `_gen_csv_report` (`L2682-2766`), `_gen_json_report` (`L3358-3361`), `_gen_raw_report` (`L3363-3366`), `_pretty_print_report_data` (`L3396-3436`).

#### 3. `src/goe/offload/offload_source_data.py` (2,875 lines) -> `src/goe/offload/source_data/`
- **Base (`src/goe/offload/offload_source_data.py:54-108`, `255-1145` -> `src/goe/offload/source_data/base.py`)**:
  - `OffloadSourceDataException`, constants, `get_offload_type_for_config`, `is_default_partition`, `OffloadSourcePartition`, `OffloadSourcePartitions`, `OffloadSourceDataInterface`.
- **RBO (`L1517-1650`, `L2807-2874` -> `src/goe/offload/source_data/rbo.py`)**:
  - `OffloadSourceDataFull`, `OffloadSourceDataFullPartitioned`, `OffloadSourceDataIUPartitioned`.
- **IPA Range (`L1658-2196`, `L2624-2795` -> `src/goe/offload/source_data/ipa_range.py`)**:
  - `OffloadSourceDataIpaRange`, `OffloadSourceDataIpaListAsRange`.
- **IPA List (`L2204-2617` -> `src/goe/offload/source_data/ipa_list.py`)**:
  - `OffloadSourceDataIpaList`.
- **PBO (`L1152-1510` -> `src/goe/offload/source_data/pbo.py`)**:
  - `OffloadSourceDataPredicate` (`GenericPredicate` evaluation and HWM predicate tracking).
- **Factory (`L115-252` -> `src/goe/offload/source_data/factory.py`)**:
  - `offload_source_data_factory`.

#### 4. `src/goe/offload/offload_transport.py` (2,512 lines) & `src/goe/offload/factory/offload_transport_factory.py` (201 lines) -> `src/goe/offload/transport/`
- **Constants (`L94-179` -> `src/goe/offload/transport/constants.py`)**:
  - All `OFFLOAD_TRANSPORT_METHOD_*`, `VALID_OFFLOAD_TRANSPORT_METHODS`, `SPARK_*`, `GOE_LISTENER_*`, and `TRANSPORT_CXT_*` constants.
- **Base (`L86-87`, `598-1708` -> `src/goe/offload/transport/base.py`)**:
  - `OffloadTransportException`, `derive_rest_api_verify_value_from_url`, `convert_nans_to_nulls`, `get_offload_transport_value`, `OffloadTransport` (including `PollingThread` SQL statistics validation queue draining and SCN/staging verification), `OffloadTransportSpark`.
- **Transport Implementations & Availability (`query_import.py`, `spark_submit.py`, `dataproc.py`, `livy.py`, `sqoop.py`)**:
  - `query_import.py`: `is_query_import_available`, `OffloadTransportQueryImport`.
  - `spark_submit.py`: `spark_submit_executable_exists`, `is_spark_thrift_available`, `is_spark_submit_available`, `OffloadTransportSparkThrift`, `OffloadTransportSparkThriftCanary`, `OffloadTransportSparkSubmit`, `OffloadTransportSparkSubmitCanary`.
  - `dataproc.py`: `is_spark_gcloud_available`, `is_spark_gcloud_dataproc_available`, `is_spark_gcloud_batches_available`, `OffloadTransportSparkDataprocGcloud`, `OffloadTransportSparkBatchesGcloud`, `OffloadTransportSparkDataprocGcloudCanary`, `OffloadTransportSparkBatchesGcloudCanary`.
  - `livy.py`: `is_livy_available`, `OffloadTransportSparkLivy`, `OffloadTransportSparkLivyCanary`.
  - `sqoop.py`: `is_sqoop_available`, `is_sqoop_by_query_available`, `OffloadTransportStandardSqoop`, `OffloadTransportSqoopByQuery`, `OffloadTransportSqoopCanary`.
- **Factory (`L537-595` & `offload_transport_factory.py:1-201` -> `src/goe/offload/transport/factory.py`)**:
  - `get_offload_transport_method_validation_fns`, `validate_offload_transport_method`, `choose_offload_transport_method`, `offload_transport_factory`, and the 6 `*_jdbc_connectivity_checker` functions.

### Functional Requirements & Feature-Parity Matrix
- **FR-1 (`goe.py` -> `src/goe/orchestration/`)**:
  - Preserve 100% of orchestration steps (`command_steps.STEP_*`), table lock acquisition (`OrchestrationLockInterface` / `orchestration_lock_for_table`), `OrchestrationRepoClientInterface` command lifecycle (`start_command` / `end_command`), dry-run vs execute modes, and CLI/Listener entrypoints (`offload_by_cli`, `OrchestrationRunner.offload`).
  - Delete all extracted definitions and dead code (`silent_close`, `normalise_column_transformations`, `canonical_to_rdbms_mappings`, `get_synthetic_partition_cols`, `get_oracle_options`, `redis_execution_id`, `init_redis_execution_id`, `redis_in_error`) from `src/goe/goe.py`, reducing `src/goe/goe.py` to **`<= 60 LOC`**.
- **FR-2 (`offload_status_report.py` -> `src/goe/report/`)**:
  - Preserve all 5 output formats (`TEXT`, `HTML`, `JSON`, `CSV`, `RAW`), all 3 detail/partition levels (`SUMMARY_LEVEL`, `DETAIL_LEVEL`, and `OFFLOADED_PARTITIONS` / `OFFLOADED_SUBPARTITIONS` partition breakdowns), `--demo` mode (`_get_demo_table_data`), and ANSI color rendering.
  - Delete all extracted classes, functions, and constants from `src/goe/offload/offload_status_report.py`, reducing it to **`<= 60 LOC`**.
- **FR-3 (`offload_source_data.py` -> `src/goe/offload/source_data/`)**:
  - Preserve RBO (`100/0` & `90/10` / `OffloadSourceDataFull`, `OffloadSourceDataFullPartitioned`, `OffloadSourceDataIUPartitioned`), IPA `RANGE` (`OffloadSourceDataIpaRange`), IPA `LIST` (`OffloadSourceDataIpaList`, `OffloadSourceDataIpaListAsRange`), subpartition offload (`offload_by_subpartition`), PBO (`GenericPredicate` / `OffloadSourceDataPredicate`), and column-addition schema evolution checks.
  - Delete all extracted classes, functions, and constants from `src/goe/offload/offload_source_data.py`, reducing it to **`<= 60 LOC`**.
- **FR-4 (`offload_transport.py` -> `src/goe/offload/transport/`)**:
  - Preserve `QueryImport`, `SparkSubmit`, `SparkDataprocGcloud`, `SparkBatchesGcloud`, `SparkThrift`, `Livy`, `Sqoop` (`StandardSqoop` & `SqoopByQuery`), `PollingThread` SQL statistics validation queue draining (`_start_validation_polling_thread` / `_stop_validation_polling_thread`), and SCN/staging file verification.
  - Delete all extracted classes, functions, and constants from `src/goe/offload/offload_transport.py` and `src/goe/offload/factory/offload_transport_factory.py`, reducing both files strictly to **`<= 60 LOC`**.

### Non-Functional Requirements
- **NFR-1 (Facade Line Budget `<= 60 LOC`)**: `src/goe/goe.py`, `src/goe/offload/offload_status_report.py`, `src/goe/offload/offload_source_data.py`, `src/goe/offload/offload_transport.py`, and `src/goe/offload/factory/offload_transport_factory.py` must each be `<= 60` lines of code (`wc -l`) containing only SPDX headers, module docstring, and clean re-exports.
- **NFR-2 (Zero Dead Code or Unused Imports)**: All unreachable functions, unused private helpers, legacy `redis_execution_id` remnants in `goe.py`, and commented-out code blocks must be removed; `uv run ruff check` (`F401`, `F841`, `ERA001`) must pass with zero warnings.
- **NFR-3 (Code Style & Standards)**: All newly created and modified files must start with the 2-line SPDX header (`# SPDX-FileCopyrightText: 2026 The GOE Authors` / `# SPDX-License-Identifier: Apache-2.0`), use PEP 585/604 type annotations, contain zero inline `#` comments inside Python code blocks, and pass `uv run ruff check` and `uv run mypy src/goe`.

### Requirement-to-Task Traceability Matrix

| Requirement | Task ID | Verification Artifact |
| :--- | :--- | :--- |
| FR-1, NFR-1, NFR-2, NFR-3 | `core_god_module_decomposition_20261010:1.1` | `tests/unit/orchestration/test_goe_decomposition.py`, `tests/unit/cli/test_offload_command.py` |
| FR-2, NFR-1, NFR-2, NFR-3 | `core_god_module_decomposition_20261010:1.2` | `tests/unit/report/test_offload_status_report_decomposition.py`, `tests/unit/cli/test_report_command.py` |
| FR-3, NFR-1, NFR-2, NFR-3 | `core_god_module_decomposition_20261010:1.3` | `tests/unit/offload/test_offload_source_data.py`, `tests/unit/offload/test_predicate_offload.py` |
| FR-4, NFR-1, NFR-2, NFR-3 | `core_god_module_decomposition_20261010:1.4` | `tests/unit/offload/test_offload_transport.py` |

## Implementation Plan

### Phase 1: Core God-Module Decomposition
- [ ] **Task 1.1**: Decompose `src/goe/goe.py` into `src/goe/orchestration/`, eliminate dead code, and reduce `src/goe/goe.py` to `<= 60 LOC` (`tasks/1.1.md`)
  - **Depends On**: None
  - **Verification Strategy**: `characterization`
  - **Owned Files**: `src/goe/orchestration/__init__.py`, `src/goe/orchestration/constants.py`, `src/goe/orchestration/logging_init.py`, `src/goe/orchestration/operation.py`, `src/goe/orchestration/execution.py`, `src/goe/orchestration/orchestration_runner.py`, `src/goe/goe.py`, `tests/unit/orchestration/test_goe_decomposition.py`
- [ ] **Task 1.2**: Decompose `src/goe/offload/offload_status_report.py` into `src/goe/report/`, eliminate dead code, and reduce `offload_status_report.py` to `<= 60 LOC` (`tasks/1.2.md`)
  - **Depends On**: None
  - **Verification Strategy**: `characterization`
  - **Owned Files**: `src/goe/report/__init__.py`, `src/goe/report/models.py`, `src/goe/report/collector.py`, `src/goe/report/renderers/__init__.py`, `src/goe/report/renderers/text_renderer.py`, `src/goe/report/renderers/html_renderer.py`, `src/goe/report/renderers/structured_renderer.py`, `src/goe/offload/offload_status_report.py`, `tests/unit/report/test_offload_status_report_decomposition.py`
- [ ] **Task 1.3**: Decompose `src/goe/offload/offload_source_data.py` into `src/goe/offload/source_data/`, eliminate dead code, and reduce `offload_source_data.py` to `<= 60 LOC` (`tasks/1.3.md`)
  - **Depends On**: None
  - **Verification Strategy**: `characterization`
  - **Owned Files**: `src/goe/offload/source_data/__init__.py`, `src/goe/offload/source_data/base.py`, `src/goe/offload/source_data/rbo.py`, `src/goe/offload/source_data/ipa_range.py`, `src/goe/offload/source_data/ipa_list.py`, `src/goe/offload/source_data/pbo.py`, `src/goe/offload/source_data/factory.py`, `src/goe/offload/offload_source_data.py`, `tests/unit/offload/test_offload_source_data.py`
- [ ] **Task 1.4**: Decompose `src/goe/offload/offload_transport.py` and `offload_transport_factory.py` into `src/goe/offload/transport/`, eliminate dead code, and reduce both facades to `<= 60 LOC` (`tasks/1.4.md`)
  - **Depends On**: None
  - **Verification Strategy**: `characterization`
  - **Owned Files**: `src/goe/offload/transport/__init__.py`, `src/goe/offload/transport/constants.py`, `src/goe/offload/transport/base.py`, `src/goe/offload/transport/query_import.py`, `src/goe/offload/transport/spark_submit.py`, `src/goe/offload/transport/dataproc.py`, `src/goe/offload/transport/livy.py`, `src/goe/offload/transport/sqoop.py`, `src/goe/offload/transport/factory.py`, `src/goe/offload/offload_transport.py`, `src/goe/offload/factory/offload_transport_factory.py`, `tests/unit/offload/test_offload_transport.py`

## Continuity Snapshot
- **Current State**: `planned` (`plan_revision: 2`, `state_revision: 0`).
- **Completed Tasks**: None.
- **Next Action**: Execute Tasks `1.1`, `1.2`, `1.3`, and `1.4`.

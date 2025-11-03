# Claude Agent System: GOE (Gluent Offload Engine)

**Version**: 1.0
**Last Updated**: Sunday, November 03, 2025
**Project**: Data offloading framework (RDBMS → Cloud)

This document is the **single source of truth** for the Claude Code multi-agent workflow in GOE.

## Philosophy

This system is built on **"Continuous Knowledge Capture"** - ensuring documentation evolves with code. Every feature implementation contributes to institutional knowledge.

## Agent Architecture

Claude uses a **multi-agent system** where specialized agents handle specific phases:

| Agent | File | Mission |
|-------|------|---------|
| **PRD** | `.claude/agents/prd.md` | Requirements analysis, PRD creation, task breakdown |
| **Expert** | `.claude/agents/expert.md` | Implementation with deep technical knowledge |
| **Testing** | `.claude/agents/testing.md` | Comprehensive test creation (90%+ coverage) |
| **Docs & Vision** | `.claude/agents/docs-vision.md` | Documentation, quality gate, knowledge capture |
| **Sync Guides** | `.claude/agents/sync-guides.md` | Documentation synchronization |

## Workflow

### Sequential Development Phases

1. **Phase 1: PRD** - Agent creates workspace in `specs/active/{slug}/`
2. **Phase 2: Expert Research** - Research patterns, libraries, best practices
3. **Phase 3: Implementation** - Expert writes production code
4. **Phase 4: Testing** - Testing agent creates comprehensive tests (auto-invoked by Expert)
5. **Phase 5: Documentation** - Docs & Vision updates guides (auto-invoked after Testing)
6. **Phase 6: Quality Gate** - Full validation and knowledge capture
7. **Phase 7: Archive** - Workspace moved to `specs/archive/`

## Workspace Structure

```
specs/active/{slug}/
├── prd.md          # Product Requirements Document
├── tasks.md        # Implementation checklist
├── recovery.md     # Session resume instructions
├── research/       # Research findings
└── tmp/            # Temporary files
```

## Project Context

**Language**: Python 3.7-3.11
**Primary Frameworks**: Custom plugin architecture, Factory pattern
**Test Framework**: pytest with pytest-asyncio, pytest-xdist
**Build Tool**: GNU Make + SBT (Scala Spark Listener)
**Documentation**: Markdown in specs/guides/
**Architecture**: Multi-tier plugin system with factory pattern

### Supported Systems

- **Frontends**: Oracle, SQL Server, Teradata
- **Backends**: BigQuery, Snowflake, Synapse, Hive, Impala, Spark
- **Transport Methods**: GOE, Sqoop, GCP Dataflow, Spark (Dataproc/Batches), Livy

## Development Commands

### Setup

```bash
# Create development environment
make clean && make install-dev
source ./.venv/bin/activate
export PYTHONPATH=${PWD}/src

# Install optional dependencies
make install-dev-extras
```

### Build

```bash
make package              # Full distribution build (Python + Scala)
make python-goe          # Python wheel only
make spark-listener      # Scala JAR only
make clean               # Clean all artifacts
```

### Test

```bash
# Unit tests (no external dependencies)
pytest tests/unit

# Unit tests across all Python versions (3.7-3.11)
nox -s unit

# Integration tests (requires Oracle + GOE_TEST user)
export GOE_TEST_USER_PASS=my_secret_123
pytest tests/integration -n 4

# Coverage report
pytest tests/unit --cov=src/goe --cov-report=term-missing
```

### Lint

```bash
# Black formatting (configured but not strictly enforced)
black src/goe tests/

# Check imports and basic style
python -m py_compile src/goe/**/*.py
```

### Documentation

```bash
# Review architecture guides
ls specs/guides/

# Update guides after implementation
# (Use Sync Guides agent)
```

## Code Quality Standards

### Type Hints

- **Adoption Status**: ~25% of codebase (57/228 files use typing)
- **Style**: Progressive adoption - new code should include type hints
- **Pattern**: Use `from typing import` and `TYPE_CHECKING` for circular imports
- **Goal**: All new functions/methods must have type hints

**Example**:

```python
from typing import Optional, List
from __future__ import annotations  # For forward references

def process_offload(
    source_table: str,
    backend_type: str,
    partition_keys: Optional[List[str]] = None
) -> OffloadResult:
    """Process an offload operation."""
    ...
```

### Formatting

- **Tool**: Black (configured in dev dependencies)
- **Style**: Follow existing patterns in the module being modified
- **Enforcement**: Not strict, but recommended for new code
- **Line Length**: Default Black settings

### Documentation

- **Docstring Style**: Google-style docstrings
- **Coverage**: 1063 docstrings across 132 files
- **Requirement**: All public APIs (classes, functions, methods) must be documented
- **Include**: Purpose, parameters, return values, exceptions, examples

**Example**:

```python
def create_backend_api(backend_type: str, config: OrchestrationConfig) -> BackendApiInterface:
    """Create a backend API instance using the factory pattern.

    Args:
        backend_type: One of DBTYPE_BIGQUERY, DBTYPE_SNOWFLAKE, etc.
        config: Orchestration configuration with connection details

    Returns:
        Backend API implementation for the specified type

    Raises:
        NotImplementedError: If backend_type is not supported

    Example:
        >>> config = OrchestrationConfig.from_env()
        >>> api = create_backend_api(DBTYPE_BIGQUERY, config)
    """
    ...
```

### Testing

- **Framework**: pytest 7.x with pytest-asyncio, pytest-xdist
- **Coverage Target**: **90%+ for all modified modules** (strictly enforced)
- **Test Organization**:
  - `tests/unit/` - Isolated tests (no external dependencies)
  - `tests/integration/` - Real database/cloud tests (requires setup)
- **Parallel Execution**: Use `-n 4` or `-n auto` with pytest-xdist

#### Test Types Required

1. **Unit Tests** - Isolated component testing

   ```python
   def test_canonical_type_mapping():
       """Test Oracle NUMBER maps to GOE_TYPE_DECIMAL."""
       column = OracleColumn("test_col", "NUMBER(10,2)")
       assert column.canonical_type == GOE_TYPE_DECIMAL
   ```

2. **Integration Tests** - Real dependencies (databases, cloud services)

   ```python
   @pytest.mark.integration
   def test_oracle_to_bigquery_offload(oracle_conn, bigquery_client):
       """Test complete offload flow."""
       ...
   ```

3. **Edge Cases** - NULL, empty, boundary conditions

   ```python
   @pytest.mark.parametrize("input_value", [None, "", "0", "-1", "9999999999"])
   def test_type_conversion_edge_cases(input_value):
       """Test type conversion handles edge cases."""
       ...
   ```

4. **Performance Tests** - **N+1 query detection** (MANDATORY for DB operations)

   ```python
   def test_no_n_plus_one_queries(db_session, query_counter):
       """Test batch operations avoid N+1 queries."""
       query_counter.reset()
       tables = fetch_all_tables_with_columns(limit=100)
       assert query_counter.count <= 2, f"N+1 detected: {query_counter.count} queries"
   ```

5. **Concurrent Access Tests** - Race conditions, deadlocks

   ```python
   import asyncio

   @pytest.mark.asyncio
   async def test_concurrent_offload_operations():
       """Test concurrent offloads handle locking correctly."""
       tasks = [offload_table(f"table_{i}") for i in range(10)]
       results = await asyncio.gather(*tasks, return_exceptions=True)
       assert all(isinstance(r, OffloadResult) for r in results)
   ```

### Async Patterns

**Status**: Limited async usage (FastAPI listener service)

- Listener service uses FastAPI with async endpoints
- Most core offload logic is synchronous
- Database operations use synchronous drivers (cx_Oracle, pymssql)

**When Adding Async**:

- Use `asyncio` for I/O-bound operations
- Use `pytest-asyncio` for async tests
- Consider backward compatibility with Python 3.7

## Project Structure

```
/home/cody/code/gluent/goe/
├── src/goe/                         # Main source (228 Python files)
│   ├── offload/                    # Core offload logic
│   │   ├── factory/               # 9 factory classes
│   │   ├── oracle/                # Oracle frontend adapter
│   │   ├── microsoft/             # SQL Server/Synapse adapters
│   │   ├── teradata/              # Teradata frontend adapter
│   │   ├── bigquery/              # BigQuery backend adapter
│   │   ├── snowflake/             # Snowflake backend adapter
│   │   ├── hadoop/                # Hadoop/Hive/Impala adapters
│   │   ├── spark/                 # Spark integration
│   │   ├── staging/               # Staging file handling (Avro/Parquet)
│   │   └── operation/             # Offload operations
│   ├── orchestration/             # Workflow execution (7 files)
│   ├── persistence/               # Metadata storage
│   ├── config/                    # Configuration management (6 files)
│   ├── listener/                  # FastAPI progress monitoring service
│   ├── util/                      # Utilities
│   ├── schema_sync/               # Schema synchronization
│   └── connect/                   # Connectivity testing
├── tests/
│   ├── unit/                      # Unit tests (no external deps)
│   ├── integration/               # Integration tests (requires databases)
│   └── testlib/                   # Test framework adapters
├── tools/
│   └── spark-listener/            # Scala Spark Listener (SBT project)
├── bin/                           # CLI entry points (7 commands)
├── templates/conf/                # 9 configuration templates
└── specs/                         # Agent system documentation
    ├── active/                    # Active workspaces (gitignored)
    ├── archive/                   # Archived workspaces (gitignored)
    ├── guides/                    # Architecture/testing guides
    └── template-spec/             # Workspace templates
```

## Key Architectural Patterns

### 1. Multi-Adapter Plugin Architecture ⭐

**Core Pattern**: Factory-based plugin system supporting multiple frontends and backends

**Implementation**:

- **12 abstract interfaces** using `ABCMeta` and `@abstractmethod`
- **9 factory classes** in `src/goe/offload/factory/`
- **Adapter structure** (consistent across Oracle/MSSQL/Teradata/BigQuery/Snowflake/Hadoop):

  ```
  {adapter_name}/
  ├── {adapter}_api.py                  # Main API implementation
  ├── {adapter}_column.py               # Type mappings
  ├── {adapter}_literal.py              # SQL literal formatting
  ├── {adapter}_table.py                # Table representation
  ├── {adapter}_predicate.py            # Predicate handling
  └── {adapter}_offload_transport_rdbms_api.py  # Transport optimizations
  ```

**Key Interfaces**:

- `BackendApiInterface` (2003 lines, ~100+ abstract methods)
- `FrontendApiInterface` (876 lines)
- `ColumnMetadataInterface` (672 lines)
- `OffloadSourceTableInterface`
- `StagingFileInterface`

### 2. Canonical Type System

**Three-Tier Type Mapping**:

```
Frontend Types → GOE Canonical Types → Backend Types
Oracle NUMBER  → GOE_TYPE_DECIMAL   → BigQuery NUMERIC
Oracle DATE    → GOE_TYPE_DATE      → BigQuery DATE
```

**Implementation**: `column_metadata.py` defines 20 canonical types (GOE_TYPE_*)

**Usage**:

```python
from goe.offload.column_metadata import GOE_TYPE_DECIMAL, GOE_TYPE_DATE

# Frontend column converts to canonical type
oracle_col = OracleColumn("amount", "NUMBER(10,2)")
canonical_type = oracle_col.canonical_type  # → GOE_TYPE_DECIMAL

# Backend column converts from canonical type
bigquery_col = BigQueryColumn.from_canonical(canonical_type)
bigquery_type = bigquery_col.backend_type  # → "NUMERIC"
```

### 3. Factory Pattern with Context Managers

**Standard Factory Pattern**:

```python
from goe.offload.factory.backend_api_factory import backend_api_factory

api = backend_api_factory(backend_type=DBTYPE_BIGQUERY, config=config)
try:
    api.create_table(...)
finally:
    api.close()
```

**Context Manager Pattern** (preferred):

```python
from goe.offload.factory.backend_api_factory import backend_api_factory_ctx

with backend_api_factory_ctx(backend_type=DBTYPE_BIGQUERY, config=config) as api:
    api.create_table(...)
    # Automatic cleanup on exit
```

### 4. Transport Layer Abstraction

**Multiple Transport Methods**:

- **GOE Transport** - Custom Python implementation
- **Sqoop** - Hadoop Sqoop integration
- **GCP Dataflow** - Google Cloud Dataflow
- **Spark** - Dataproc, Dataproc Batches, standalone
- **Livy** - Spark Livy REST API

**Factory Usage**:

```python
from goe.offload.factory.offload_transport_factory import offload_transport_factory

transport = offload_transport_factory(
    transport_method="spark",
    frontend_api=frontend_api,
    backend_api=backend_api,
    config=config
)
transport.transport_data(source_table, staging_files)
```

### 5. Orchestration Pattern

**Workflow Management**:

```python
from goe.orchestration.orchestration_runner import OrchestrationRunner

runner = OrchestrationRunner(
    execution_id=execution_id,
    config=config,
    messages=messages
)

with runner:
    runner.run_offload(
        source_schema="SALES",
        source_table="ORDERS",
        backend_type=DBTYPE_BIGQUERY
    )
```

**Components**:

- `OrchestrationRunner` - Main workflow manager
- `OrchestrationLock` - Prevents concurrent table operations
- `OrchestrationMetadata` - Persists execution history
- `ExecutionId` - Tracks execution instances

## MCP Tools Available

### Context7 (Library Documentation)

**Purpose**: Fetch up-to-date documentation for external libraries

**Usage**:

```python
# Step 1: Resolve library ID
mcp__context7__resolve_library_id(libraryName="pytest")

# Step 2: Fetch documentation
mcp__context7__get_library_docs(
    context7CompatibleLibraryID="/pytest-dev/pytest",
    topic="async fixtures and pytest-asyncio",
    tokens=5000
)
```

**When to Use**:

- Researching external library APIs (pytest, FastAPI, cx_Oracle, google-cloud-bigquery)
- Understanding best practices for third-party integrations
- Verifying correct usage patterns

### Zen MCP (Multi-Purpose AI Tools)

#### zen.planner - Multi-Step Planning

**Purpose**: Break down complex tasks with revision capabilities

**Usage**:

```python
mcp__zen__planner(
    step="Analyze feature scope: Map affected adapters, factory changes, type mappings",
    step_number=1,
    total_steps=8,
    next_step_required=True,
    use_assistant_model=True
)
```

**When to Use**:

- Planning new frontend/backend adapter implementations
- Designing complex features affecting multiple layers
- Architectural decision-making

#### zen.chat - Collaborative Thinking

**Purpose**: Brainstorming and exploring ideas

**Usage**:

```python
mcp__zen__chat(
    prompt="How should we handle NULL value mapping between Oracle NUMBER(0) and BigQuery INTEGER?",
    working_directory_absolute_path="/home/cody/code/gluent/goe",
    absolute_file_paths=["src/goe/offload/column_metadata.py"]
)
```

#### zen.thinkdeep - Deep Analysis

**Purpose**: Complex architectural analysis and investigation

**Usage**:

```python
mcp__zen__thinkdeep(
    step="Investigating caching strategy for metadata queries",
    step_number=1,
    total_steps=4,
    next_step_required=True,
    findings="Current implementation queries Oracle data dictionary 50+ times per offload",
    hypothesis="In-memory cache with TTL would reduce DB load",
    confidence="high",
    focus_areas=["performance", "scalability"]
)
```

#### zen.analyze - Code Analysis

**Purpose**: Systematic code review and quality assessment

**Usage**:

```python
mcp__zen__analyze(
    step="Analyzing factory layer for consistency across adapters",
    step_number=1,
    total_steps=3,
    next_step_required=True,
    findings="BigQuery and Snowflake factories follow consistent patterns, Hadoop differs",
    analysis_type="architecture",
    relevant_files=[
        "/home/cody/code/gluent/goe/src/goe/offload/factory/backend_api_factory.py"
    ]
)
```

#### zen.debug - Systematic Debugging

**Purpose**: Root cause analysis for bugs

**Usage**:

```python
mcp__zen__debug(
    step="Investigating Oracle connection leak in integration tests",
    step_number=1,
    total_steps=3,
    next_step_required=True,
    findings="Connections not closed when exceptions occur in transport layer",
    hypothesis="Missing finally block in oracle_offload_transport_rdbms_api.py",
    confidence="medium",
    relevant_files=[
        "/home/cody/code/gluent/goe/src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py"
    ]
)
```

### WebSearch

**Purpose**: Research modern best practices and industry standards

**Usage**:

```python
WebSearch(query="Python factory pattern best practices 2025")
WebSearch(query="BigQuery batch loading performance optimization")
```

**When to Use**:

- Novel problems not covered in existing documentation
- Modern best practices for architecture patterns
- Performance optimization techniques

## Anti-Patterns (Avoid These)

### 1. Breaking Interface Contracts

❌ **Don't**: Add methods to `BackendApiInterface` without implementing in all backends
✅ **Do**: Add optional methods with default implementations or use capability flags

### 2. Bypassing Factory Pattern

❌ **Don't**: Directly instantiate `BackendBigQueryApi()` in business logic
✅ **Do**: Use `backend_api_factory()` or `backend_api_factory_ctx()`

### 3. Hardcoding Backend-Specific Logic

❌ **Don't**: Check `if backend_type == DBTYPE_BIGQUERY` in orchestration layer
✅ **Do**: Implement backend-specific behavior in backend adapter classes

### 4. Skipping Context Managers

❌ **Don't**: Manually manage `api.close()` calls
✅ **Do**: Use `*_factory_ctx()` context managers for automatic cleanup

### 5. N+1 Query Anti-Pattern

❌ **Don't**: Query metadata in loops without batching
✅ **Do**: Batch queries or use JOINs to fetch related data

Example:

```python
# ❌ Bad: N+1 queries
tables = get_all_tables()
for table in tables:
    columns = get_columns(table.name)  # N queries

# ✅ Good: Single query
tables_with_columns = get_all_tables_with_columns()  # 1 query
```

### 6. Mixing Test Isolation Levels

❌ **Don't**: Use real Oracle connections in `tests/unit/`
✅ **Do**: Mock external dependencies in unit tests, use real connections only in `tests/integration/`

### 7. Type Mapping Shortcuts

❌ **Don't**: Map frontend types directly to backend types
✅ **Do**: Always map through canonical GOE types

```python
# ❌ Bad
if oracle_type == "NUMBER":
    bigquery_type = "NUMERIC"

# ✅ Good
canonical_type = oracle_column.canonical_type  # GOE_TYPE_DECIMAL
bigquery_type = BigQueryColumn.from_canonical(canonical_type).backend_type
```

## Dependencies

### Core Dependencies

```toml
# From pyproject.toml
python = ">=3.7,<3.12"
pyarrow = "^10.0.0"          # Parquet file handling
avro = "^1.11.0"             # Avro file handling
cx-Oracle = "^8.3.0"         # Oracle connectivity
google-cloud-bigquery = "^3.11.0"  # BigQuery backend
fastapi = "^0.77.0"          # Listener service
redis = "^4.4.4"             # Progress tracking
pydantic = "^1.10.0"         # Data validation
```

### Optional Dependencies (Adapters)

```toml
# Hadoop ecosystem
hdfs = {version = "^2.7.0", optional = true}
impyla = {version = "^0.18.0", optional = true}

# Snowflake
snowflake-connector-python = {version = "^3.0.0", optional = true}

# SQL Server / Synapse
pymssql = {version = "^2.2.0", optional = true}
pyodbc = {version = "^4.0.0", optional = true}

# Teradata
teradatasql = {version = "^17.0.0", optional = true}
```

### Development Dependencies

```toml
black = "^23.0.0"
nox = "^2023.4.22"
pytest = "^7.4.0"
pytest-asyncio = "^0.21.0"
pytest-xdist = "^3.3.0"
pytest-cov = "^4.1.0"
pytest-mock = "^3.11.0"
```

## Knowledge Capture Protocol

After every significant feature implementation:

1. **Update specs/guides/** with new patterns discovered
2. **Ensure all public APIs documented** with docstrings and examples
3. **Add working code examples** to relevant guides
4. **Update AGENTS.md** if workflow improvements identified
5. **Archive workspace** to specs/archive/ for future reference

### Guide Update Checklist

- [ ] `specs/guides/architecture.md` - New architectural patterns
- [ ] `specs/guides/testing.md` - New test patterns or fixtures
- [ ] `specs/guides/code-style.md` - New conventions adopted
- [ ] `specs/guides/adding-adapters.md` - Adapter implementation insights
- [ ] `specs/guides/configuration.md` - Configuration changes

## Version Control

### Git Workflow

```bash
# Feature branch workflow
git checkout -b feat/new-snowflake-optimization
# ... make changes ...
git add src/goe/offload/snowflake/
git commit -m "feat: Add batch loading optimization for Snowflake"
git push origin feat/new-snowflake-optimization
# Create PR on GitHub
```

### Commit Message Conventions

```
feat: Add new feature
fix: Bug fix
refactor: Code refactoring (no behavior change)
test: Add/update tests
docs: Documentation updates
chore: Build/tooling changes
perf: Performance improvement
```

### Branch Protection

- **Main branch**: `main` (protected)
- **Feature branches**: `feat/*`, `fix/*`, `refactor/*`
- **PR required**: All changes must go through PR review
- **CI checks**: Must pass before merge

---

## Starting a New Feature

### Using PRD Agent

```python
# Invoke PRD agent via Claude Code
Task(
    description="Create PRD for Snowflake batch optimization",
    prompt="""Create comprehensive PRD for implementing batch loading optimization
    in Snowflake backend adapter.

    Requirements:
    - Reduce loading time for large tables (1M+ rows)
    - Maintain existing error handling
    - Add performance metrics
    - Ensure compatibility with existing Snowflake adapter patterns
    """,
    subagent_type="prd",
    model="sonnet"
)
```

### Using Expert Agent

```python
# Invoke Expert agent for implementation
Task(
    description="Implement Snowflake batch optimization",
    prompt="""Implement feature from specs/active/snowflake-batch-optimization.

    Context:
    - PRD completed and approved
    - Implementation must follow factory pattern
    - Auto-invoke testing agent after completion
    """,
    subagent_type="expert",
    model="sonnet"
)
```

### Using Sync Guides Agent

```python
# Sync documentation after implementation
Task(
    description="Sync guides with codebase changes",
    prompt="""Ensure specs/guides/ documentation matches current codebase state.

    Recent changes:
    - Snowflake batch optimization added
    - New performance testing patterns introduced
    """,
    subagent_type="sync-guides",
    model="sonnet"
)
```

---

**System Status**: ✅ Complete multi-agent workflow configured
**Coverage Target**: 90%+ for all modified modules
**Quality Gate**: Enforced via Docs & Vision agent
**Knowledge Capture**: Continuous via guide updates

# PRD: [Feature Name]

**Status**: Draft | In Progress | Complete
**Created**: YYYY-MM-DD
**Author**: Claude PRD Agent
**Workspace**: specs/active/{slug}/

## Overview

### Problem Statement
[What problem does this solve? Why is it needed? What pain point are users experiencing?]

### Solution Summary
[High-level description of the solution approach - 2-3 sentences]

### Affected Components

- [ ] Frontend Adapters: [Oracle | SQL Server | Teradata | None]
- [ ] Backend Adapters: [BigQuery | Snowflake | Synapse | Hive | Impala | None]
- [ ] Transport Layer: [GOE | Sqoop | GCP | Spark | Livy | None]
- [ ] Factory Layer: [Which factories need changes?]
- [ ] Orchestration Layer: [OrchestrationRunner | OrchestrationLock | None]
- [ ] Configuration: [New env vars | Template updates | None]
- [ ] Type System: [Canonical type changes | None]

## Architecture

### Current State
[Describe current implementation, limitations, and why changes are needed]

###  Proposed Changes

#### Layer-by-Layer Impact

**Frontend Layer** (if applicable):
- Files affected: `src/goe/offload/oracle/oracle_*.py`
- Interface changes: [None | New methods | Modified signatures]
- Type mapping changes: [None | New canonical types | Modified mappings]

**Backend Layer** (if applicable):
- Files affected: `src/goe/offload/bigquery/bigquery_*.py`
- Interface changes: [None | New methods | Modified signatures]
- Factory registration: [None | New factory pattern | Modified factory]

**Transport Layer** (if applicable):
- Files affected: `src/goe/offload/offload_transport*.py`
- Transport methods affected: [GOE | Sqoop | GCP | Spark | Livy]

**Factory Layer** (if applicable):
- Factories affected: `backend_api_factory.py` | `frontend_api_factory.py` | etc.
- Registration pattern: [Standard | Context manager | Both]

**Configuration** (if applicable):
- New environment variables: [List with defaults]
- Template updates: `templates/conf/offload.env.template.[oracle|bigquery|etc.]`

### Design Decisions

**Decision 1: [Title]**
- **Options Considered**: A, B, C
- **Chosen**: A
- **Rationale**: [Why A was chosen over B and C]
- **Trade-offs**: [What we gain and what we lose]

**Decision 2: [Title]**
[Repeat for each major decision]

### Adapter-Specific Strategy (if multi-adapter feature)

| Adapter | Implementation Approach | Complexity | Notes |
|---------|------------------------|------------|-------|
| Oracle | [Approach description] | Low/Med/High | [Special considerations] |
| BigQuery | [Approach description] | Low/Med/High | [Special considerations] |
| Snowflake | [Approach description] | Low/Med/High | [Special considerations] |

### Canonical Type Mappings (if type system affected)

**New GOE Types** (if any):
- `GOE_TYPE_[NAME]` - [Description and purpose]

**Modified Mappings**:

| Frontend Type | GOE Type | Backend Type (BigQuery) | Backend Type (Snowflake) | Notes |
|---------------|----------|-------------------------|---------------------------|-------|
| Oracle NUMBER | GOE_TYPE_DECIMAL | NUMERIC | NUMBER | [Notes] |
| Oracle DATE | GOE_TYPE_DATE | DATE | DATE | [Notes] |

## Implementation Details

### Interface Changes

**BackendApiInterface** (if applicable):
```python
@abstractmethod
def new_method(self, param: str, options: Optional[dict] = None) -> Result:
    """Description of new method.

    This method provides [functionality description]. It should be
    implemented by all backend adapters to support [feature].

    Args:
        param: Description of parameter
        options: Optional configuration dictionary

    Returns:
        Result object with [description]

    Raises:
        NotImplementedError: If backend doesn't support this operation
        ValueError: If parameters are invalid

    Example:
        >>> api = backend_api_factory_ctx(DBTYPE_BIGQUERY, config)
        >>> result = api.new_method("value")
    """
    pass
```

**FrontendApiInterface** (if applicable):
```python
# [Interface changes with full docstrings]
```

### Factory Pattern Updates

**backend_api_factory.py**:
```python
if backend_type == DBTYPE_BIGQUERY:
    from goe.offload.bigquery.bigquery_backend_api import BackendBigQueryApi
    return BackendBigQueryApi(
        connection_options=connection_options,
        backend_type=backend_type,
        messages=messages,
        # New parameter added for this feature
        enable_new_feature=config.get_bool("BIGQUERY_NEW_FEATURE", default=True),
        ...
    )
```

### Configuration Schema

**New Environment Variables**:
```bash
# templates/conf/offload.env.template.bigquery

# [Feature Name] settings (Added YYYY-MM-DD)
export BIGQUERY_NEW_FEATURE=true  # Enable new feature
export BIGQUERY_FEATURE_PARAM=value  # Feature-specific parameter
```

## Testing Strategy

### Unit Tests (tests/unit/)
- [ ] Test new/modified methods in isolation
- [ ] Mock external dependencies (databases, cloud APIs)
- [ ] Test canonical type mappings (if applicable)
- [ ] Test factory instantiation with new parameters
- [ ] Edge cases: NULL, empty, boundary values
- [ ] Error handling and exceptions
- **Coverage Target**: 90%+

**Test Files**:
- `tests/unit/offload/bigquery/test_bigquery_backend_api.py`
- `tests/unit/offload/factory/test_backend_api_factory.py`

### Integration Tests (tests/integration/)
- [ ] Test with real Oracle database
- [ ] Test with real BigQuery backend
- [ ] Test complete offload flow end-to-end
- [ ] Test error handling and rollback scenarios
- **Requires**: GOE_TEST user, BigQuery project access

**Test Files**:
- `tests/integration/offload/test_oracle_to_bigquery_offload.py`

### Performance Tests (MANDATORY if performance feature)
- [ ] N+1 query detection (CRITICAL for DB operations)
- [ ] Batch operation efficiency
- [ ] Connection pooling effectiveness
- [ ] Memory usage profiling
- **Metrics**: Query count, execution time, memory footprint

### Concurrent Access Tests (if applicable)
- [ ] Race condition testing with OrchestrationLock
- [ ] Deadlock detection
- [ ] Multiple simultaneous offloads
- **Scenarios**: Same table, different tables, mixed operations

## Acceptance Criteria

- [ ] **AC1**: [Specific, measurable, testable criterion]
- [ ] **AC2**: [Specific, measurable, testable criterion]
- [ ] **AC3**: [Specific, measurable, testable criterion]
- [ ] **AC4**: All unit tests pass with 90%+ coverage
- [ ] **AC5**: All integration tests pass
- [ ] **AC6**: Black formatting applied to all modified files
- [ ] **AC7**: Type hints present on all new functions
- [ ] **AC8**: Docstrings present on all public APIs
- [ ] **AC9**: Documentation updated (specs/guides/)
- [ ] **AC10**: Configuration templates updated
- [ ] **AC11**: No breaking changes to existing adapters
- [ ] **AC12**: Performance benchmarks met (if applicable)

## Risks & Mitigation

| Risk | Impact | Probability | Mitigation Strategy |
|------|--------|-------------|---------------------|
| [Risk 1: Description] | High/Med/Low | High/Med/Low | [How we'll mitigate this risk] |
| [Risk 2: Description] | High/Med/Low | High/Med/Low | [How we'll mitigate this risk] |
| [Risk 3: Description] | High/Med/Low | High/Med/Low | [How we'll mitigate this risk] |

## Dependencies

### External Libraries
- [ ] [Library name version] - [Purpose and why it's needed]
- [ ] [Library name version] - [Purpose and why it's needed]

### Internal Dependencies
- [ ] [Module name] - [What it provides]
- [ ] [Module name] - [What it provides]

### Data Dependencies
- [ ] [Schema/table requirements]
- [ ] [Permission requirements]

## Documentation Requirements

- [ ] Update `specs/guides/architecture.md` with new patterns
- [ ] Update `specs/guides/adding-new-backend-frontend.md` if adapter guidelines change
- [ ] Update `specs/guides/configuration.md` with new environment variables
- [ ] Update `specs/guides/testing.md` if new test patterns introduced
- [ ] Add working code examples to relevant guides
- [ ] Update CLAUDE.md if development workflow changes
- [ ] Add inline docstrings to all new functions/classes

## Research Questions for Expert Agent

1. [Specific technical question requiring code investigation]
2. [Library version compatibility question - can we use feature X?]
3. [Performance optimization approach - what's the best pattern?]
4. [Error handling pattern for edge case Y]
5. [Integration point Z - how should this work with existing code?]

## Success Metrics

- **Performance**: [Specific metric, e.g., "Reduce offload time by 30% for tables >1M rows"]
- **Quality**: [Code coverage 90%+, zero P0 bugs in first month]
- **Adoption**: [Usage target, e.g., "Used in 10+ production offloads"]
- **Reliability**: [Error rate < 1%, 99.9% success rate]

## Timeline Estimate

- **Research**: [X hours/days - studying existing code and patterns]
- **Implementation**: [X hours/days - writing production code]
- **Testing**: [X hours/days - unit + integration + performance tests]
- **Documentation**: [X hours/days - guides, docstrings, examples]
- **Total**: [X hours/days]

## Rollback Plan

[How to rollback if this feature causes issues in production]

- Feature flag: `BIGQUERY_NEW_FEATURE=false`
- Configuration change: [What to change]
- Code rollback: [Which commits to revert]

---

**Next Steps**:
1. ✅ Review and approve this PRD
2. ⏳ Expert agent begins research phase
3. ⏳ Implementation follows factory pattern and canonical type system
4. ⏳ Testing agent ensures 90%+ coverage
5. ⏳ Docs & Vision agent handles quality gate and archival

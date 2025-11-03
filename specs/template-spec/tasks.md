# Tasks: [Feature Name]

**Workspace**: specs/active/{slug}/
**Status**: Planning | In Progress | Testing | Complete

## Phase 1: Planning & Research ✓

- [x] PRD created and reviewed
- [x] Architecture analyzed
- [x] Risks identified
- [x] Research questions documented

## Phase 2: Expert Research

### Research Tasks
- [ ] **R1**: Study existing [adapter] implementation patterns
  - Files: `src/goe/offload/[adapter]/*.py`
  - Focus: [Specific aspect to study]

- [ ] **R2**: Research [external library] documentation via Context7
  - Library: [library name]
  - Topic: [specific topic]

- [ ] **R3**: Analyze factory registration patterns
  - Files: `src/goe/offload/factory/*_factory.py`
  - Verify context manager usage

- [ ] **R4**: Review canonical type system
  - File: `src/goe/offload/column_metadata.py`
  - Understand existing GOE_TYPE_* mappings

## Phase 3: Core Implementation

### Interface Changes (if applicable)
- [ ] **I1**: Update `BackendApiInterface`
  - File: `src/goe/offload/backend_api.py`
  - Add abstract methods with complete docstrings

- [ ] **I2**: Update `FrontendApiInterface` (if needed)
  - File: `src/goe/offload/frontend_api.py`

### Adapter Implementation
- [ ] **A1**: Implement [adapter_name]_api.py changes
  - File: `src/goe/offload/[adapter]/[adapter]_api.py`
  - Methods: [list specific methods]

- [ ] **A2**: Update [adapter]_column.py (if type mappings change)
  - File: `src/goe/offload/[adapter]/[adapter]_column.py`
  - Add canonical type mappings

- [ ] **A3**: Update [adapter]_literal.py (if needed)
- [ ] **A4**: Update [adapter]_table.py (if needed)
- [ ] **A5**: Update [adapter]_predicate.py (if needed)

### Factory Registration
- [ ] **F1**: Update factory to instantiate with new parameters
  - File: `src/goe/offload/factory/[adapter]_factory.py`
  - Ensure context manager variant works

- [ ] **F2**: Test factory instantiation
  - Verify all code paths
  - Test with different configurations

### Configuration
- [ ] **C1**: Add environment variables to templates
  - Files: `templates/conf/offload.env.template.*`
  - Add defaults and documentation comments

- [ ] **C2**: Update OrchestrationConfig (if needed)
  - File: `src/goe/config/orchestration_config.py`

## Phase 4: Integration

- [ ] **INT1**: Integrate with orchestration layer
  - File: `src/goe/orchestration/orchestration_runner.py`
  - Ensure workflow compatibility

- [ ] **INT2**: Test with existing offload operations
  - Verify backward compatibility
  - Confirm no breaking changes

- [ ] **INT3**: Error handling and rollback
  - Implement error scenarios
  - Test rollback mechanisms

## Phase 5: Testing (Auto-invoked by Expert)

### Unit Tests (tests/unit/)
- [ ] **UT1**: Test [specific component/method]
- [ ] **UT2**: Test [specific component/method]
- [ ] **UT3**: Edge cases (NULL, empty, boundaries)
- [ ] **UT4**: Factory instantiation tests
- [ ] **UT5**: Type mapping tests (if applicable)
- [ ] **UT6**: Error handling tests
- [ ] **Coverage**: Achieve 90%+ for modified modules

### Integration Tests (tests/integration/)
- [ ] **IT1**: Test with real [frontend database]
- [ ] **IT2**: Test with real [backend system]
- [ ] **IT3**: Test complete offload flow
- [ ] **IT4**: Test error handling and recovery

### Performance Tests (if applicable)
- [ ] **PT1**: N+1 query detection (MANDATORY for DB ops)
- [ ] **PT2**: Batch operation efficiency
- [ ] **PT3**: Memory profiling
- [ ] **PT4**: Benchmark against baseline

### Concurrent Tests (if applicable)
- [ ] **CT1**: Race condition testing
- [ ] **CT2**: Deadlock detection
- [ ] **CT3**: OrchestrationLock validation

## Phase 6: Documentation (Auto-invoked by Expert)

- [ ] **D1**: Update specs/guides/architecture.md
- [ ] **D2**: Update specs/guides/adding-new-backend-frontend.md (if applicable)
- [ ] **D3**: Update specs/guides/configuration.md
- [ ] **D4**: Add docstrings to all new functions/classes
- [ ] **D5**: Add working code examples to guides
- [ ] **D6**: Update CLAUDE.md (if workflow changes)

## Phase 7: Quality Gate & Archive (Auto-invoked by Expert)

- [ ] **QG1**: Run full quality gate scan
- [ ] **QG2**: Anti-pattern detection
- [ ] **QG3**: Knowledge capture in AGENTS.md
- [ ] **QG4**: Archive workspace to specs/archive/

---

**Progress Tracking**:
- Total Tasks: [Auto-calculated]
- Completed: [Auto-calculated]
- Remaining: [Auto-calculated]
- Blocked: [List any blocked tasks]

**Current Focus**: [Task ID currently being worked on]

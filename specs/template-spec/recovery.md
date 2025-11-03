# Session Recovery: [Feature Name]

**Workspace**: specs/active/{slug}/
**Last Updated**: [Date/Time - update this with each session]
**Current Phase**: [Planning | Research | Implementation | Testing | Documentation | QA]

## Quick Context

**What we're building**: [One-sentence summary of the feature]

**Why**: [One-sentence problem statement]

**Status**: [Current state in 1-2 sentences - where we are, what's working, what's next]

## Current State

### Completed
- [x] [Completed item 1]
- [x] [Completed item 2]
- [x] [Completed item 3]

### In Progress
- [ ] **Current focus**: [Specific task from tasks.md - e.g., "A1: Implement bigquery_api.py changes"]
- **File being modified**: `[full file path]`
- **Line range**: [Lines X-Y if applicable]
- **What's working**: [Brief status of current work]
- **What's not working**: [Issues encountered, if any]
- **Last action**: [Last thing that was done]

### Blocked
- [ ] [Blocked item 1] - **Blocker**: [What's blocking it and what's needed to unblock]
- [ ] [Blocked item 2] - **Blocker**: [What's blocking it]

## Key Decisions Made

1. **[Decision Title]**: [Brief explanation of decision and rationale]
2. **[Decision Title]**: [Brief explanation of decision and rationale]
3. **[Decision Title]**: [Brief explanation of decision and rationale]

## Files Modified So Far

- `src/goe/offload/[adapter]/[file].py` - [Brief description of changes]
- `src/goe/offload/factory/[factory].py` - [Brief description of changes]
- `templates/conf/[template].env` - [Brief description of changes]

## Next Steps

1. **Immediate**: [Exact next task to work on - be specific]
2. **After that**: [Following task]
3. **Then**: [Task after that]
4. **Finally**: [Last task before completion]

## Research Findings

### [Topic 1]
- **Source**: [Context7 | WebSearch | Codebase analysis]
- **Key Finding**: [Summary of what was learned]
- **Applied?**: Yes | No | Partially
- **Impact**: [How this affects implementation]

### [Topic 2]
- **Source**: [Context7 | WebSearch | Codebase analysis]
- **Key Finding**: [Summary of what was learned]
- **Applied?**: Yes | No | Partially
- **Impact**: [How this affects implementation]

## Open Questions

1. [Question 1] - **Status**: [Answered | Investigating | Need expert input | Blocked]
2. [Question 2] - **Status**: [Answered | Investigating | Need expert input | Blocked]
3. [Question 3] - **Status**: [Answered | Investigating | Need expert input | Blocked]

## Test Status

- **Unit Tests**: [Passing | Failing | Not yet written | Partially written]
  - Coverage: [X% | Not measured yet]
  - Passing: [X/Y tests]
  - Issues: [None | List specific issues]

- **Integration Tests**: [Passing | Failing | Not yet written]
  - Issues: [None | List specific issues]

- **Performance Tests**: [Passing | Failing | Not yet written]
  - Metrics: [Current metrics if available]

## Code Quality Checklist

- [ ] Type hints added to new functions
- [ ] Docstrings added to public APIs
- [ ] Black formatting applied
- [ ] No direct adapter instantiation (using factories)
- [ ] Canonical type system used for type mappings
- [ ] Context managers used for resource management
- [ ] Error handling implemented
- [ ] Configuration parameters documented

## Commands to Resume Work

```bash
# Activate environment
source ./.venv/bin/activate
export PYTHONPATH=${PWD}/src

# Navigate to workspace
cd /home/cody/code/gluent/goe

# Check current git status
git status
git diff src/goe/offload/[adapter]/

# Run tests for this feature
pytest tests/unit/offload/[adapter]/ -v

# Run with coverage
pytest tests/unit/offload/[adapter]/ --cov=src/goe/offload/[adapter] --cov-report=term-missing

# Apply Black formatting
black src/goe/offload/[adapter]/

# Run specific test
pytest tests/unit/offload/[adapter]/test_[name].py::test_function_name -v
```

## Agent Handoff Notes

**For Expert Agent**:
- [Specific guidance or context that Expert should know]
- [Files that need particular attention]
- [Patterns to follow from existing code]

**For Testing Agent**:
- [Test scenarios to prioritize]
- [Edge cases discovered during implementation]
- [Performance benchmarks to target]

**For Docs & Vision Agent**:
- [Documentation sections that need updating]
- [New patterns to capture in guides]
- [Examples to add]

## Integration Points

**Upstream Dependencies**:
- [What this feature depends on]

**Downstream Consumers**:
- [What will use this feature]

## Performance Considerations

- **Expected Impact**: [Faster/slower/same performance]
- **Benchmarks**: [Target metrics]
- **Memory Usage**: [Expected memory footprint]
- **N+1 Queries**: [Status of N+1 detection]

## Rollback Information

- **Feature Flag**: `[ENV_VAR_NAME]=false`
- **Configuration**: [How to disable via configuration]
- **Code Changes**: [Which files would need to be reverted]

---

**Recovery Instructions for New Session**:
1. Read this file top to bottom for full context
2. Read `prd.md` for requirements and acceptance criteria
3. Check `tasks.md` for detailed task breakdown and status
4. Review "Current State" section above for immediate context
5. Execute commands in "Commands to Resume Work" section
6. Continue with task listed in "Next Steps - Immediate"

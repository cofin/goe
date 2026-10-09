---
type: Guide
title: Project Workflow
description: Canonical development, testing, packaging, validation, and Flow state workflows for GOE
tags:
  - guide
  - workflow
  - commands
  - development
---

# Project Workflow

<!-- truth: start -->
- Virtual environment setup: `make install` (or `make setup-env` to configure kernel index).
- Development packages & lockfile: Managed via `uv` with `pyproject.toml` (`[dependency-groups]`) and `uv.lock`.
- Unit testing: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit` (or `make test-unit`).
- Integration testing: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false GOE_TEST_USER_PASS=... && uv run pytest tests/integration -n 4` (or `make test-integration`).
- Code formatting & linting: `make format` (`uv run ruff format` and `uv run ruff check --fix`) and `make lint` (`uv run ruff check` and `uv run mypy src/goe`).
- Packaging & release build: `make build` (produces wheel and sdist in `dist/`), `make target` (compiles runtime tree in `target/offload`), and `make package` (produces `goe_<version>.tar.gz`).
- Pre-flight environment check: `goe connect` / `bin/connect` (checks configuration, frontend DB, backend DW, and transport connectivity).
- Offload CLI: `goe offload -t <owner.table> -x` / `bin/offload -t <owner.table> -x` (executes offload with execution lock and audit trail).
- Task files under `.agents/bundles/specs/<flow_id>/tasks/` are authoritative; `spec.md` is the synchronized checklist and continuity view.
- Consumer operational skills install only under `.agents/skills/`. Product, knowledge, research, and specs remain under `.agents/bundles/`.
- Flow never creates, moves, force-updates, or deletes Git tags, and never pushes automatically.
<!-- truth: end -->

## Canonical commands

Prefer repository-native Makefile targets and `uv run` wrappers over ad hoc tool invocations:

```bash
# setup & dependency sync
make setup-env
make install
make upgrade

# focused & aggregate unit tests
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
make test-unit
uv run pytest tests/unit/offload/test_column_metadata.py -q

# parallel integration tests (requires active DB & GCP credentials)
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false GOE_TEST_USER_PASS="<db_password>" GOOGLE_CLOUD_PROJECT="<gcp_project_id>"
make test-integration

# formatting, linting, and static typechecking
make format
make lint

# runtime distribution & release packaging
make build
make target
make package

# pre-flight & operational validation
goe connect
goe connect --upgrade-environment-file
goe offload -t SH.SALES -x
goe validate -t SH.SALES --verify-row-count aggregate
```

Use non-interactive modes in automation. Before claiming a result, run the exact command freshly, read its complete output and exit status, and report limitations.

## Direct-read continuity

1. Resolve `.agents/setup-state.json:root_directory`, defaulting to `.agents/`.
2. Before selecting a flow or doing normal work, scan `<configured-root>/transactions/*/journal.md` and the retired `<configured-root>/tasks/transactions/*/journal.md`. Jointly arbitrate every nonterminal journal (`prepared`, `task_writes_started`, `recovery_required`, `contended`, or `rollback_in_progress`); recover the selected transaction from its recorded fragments, or stop on unresolved conflict.
3. Resolve the configured bundle root, then read its index and candidate spec frontmatter under `specs/<flow_id>/`.
4. Read authoritative task frontmatter in `tasks/*.md`.
5. Verify plan/state identity, task dependencies, claims, and checklist agreement.
6. Select an explicit task, the sole in-progress task, or the first ready task.
7. Read the complete worksheet, direct dependencies, newest discoveries, and relevant knowledge chapters.

Hooks and prior conversation are routing hints, not authority. Task files are the single authority for task state.

## Task and state operations

A task is ready when `state: open`, all `depends_on` tasks are `closed`, its worksheet is complete, and its plan identity matches the spec.

Resolve the canonical state authority through the active Flow installation. In plugin/default-skip mode, load the active packaged `flow-state` skill and its sibling `references/state.md`; do not require or synthesize a project-local skill path. In a standalone project install, load `.agents/skills/flow-state/SKILL.md` and resolve `references/state.md` relative to it. If neither authority is available, stop before mutation. Follow the resolved contract with ordinary file read/write/edit tools. Every existing-flow mutation must carry the exact observed `expected_plan_revision`, `expected_plan_commit`, and `expected_state_revision`. Refuse stale identity or unresolved journals without tracked writes. For an accepted mutation, create the prepared transaction journal before tracked state changes, write in its canonical task-first/spec-last order, reread the journal and semantic read set around each write, and record final validation before marking the journal terminal. Recovery resumes the selected journal's recorded finish-or-rollback direction; it never starts a replacement mutation.

| Operation | Purpose |
| --- | --- |
| `claim` | Move one ready task to `in_progress`. |
| `note` | Append investigation findings to `## Notes & Discoveries`. |
| `block` / `unblock` | Record or resolve an exact blocker and next step. |
| `release` | Return an in-progress task to open when the claimant stops. |
| `close` | Close the sole claimed task with recorded commit SHA. |
| `reconcile` | Update spec checklist markers from task-file frontmatter via `/flow:sync`. |
| `complete` | Move an active spec whose tasks are all closed or skipped to `completed` after verification and review. |
| `archive` | Finish a completed spec: elevate knowledge, log summary, then contract the spec directory. |
| `recover` | Resume an unresolved transaction journal in its recorded finish-or-rollback direction. |

Use `/flow:sync` to reconcile `spec.md` checklist markers from task files. Task files remain authoritative for state. A worksheet mismatch stops production mutation and routes through refinement.

## Verification strategies

| Strategy | Select for | Required evidence |
| --- | --- | --- |
| `behavior_tdd` | New observable behavior | Focused behavior fails because it is absent; minimal implementation makes it green. |
| `regression_tdd` | Defect correction | Focused reproduction demonstrates the defect; the narrow fix makes it green. |
| `characterization` | Behavior-preserving refactor/deletion | Green focused baseline before and unchanged behavior after. |
| `static_validation` | Manifest, config, generated surface, tooling | Native parser/lint/type/build; isolated representative violation proves a new/replacement gate fails with the expected diagnostic. |
| `documentation_validation` | Links, examples, docs structure | Docs-native baseline and final link/example/build/structure checks. |
| `integration_acceptance` | Composition of existing contracts | Green focused baseline; end-to-end scenario plus injected negative states proving refusal paths. |

A waiver does not replace the selected strategy. It requires an explicit rationale, approver, and compensating evidence. Never manufacture a failing unit test for documentation, configuration, generated output, prose, or behavior-preserving cleanup. Integration acceptance routes missing implementation through revise instead of absorbing it.

## Execution sequence

1. Preflight the worksheet, live targets, dependencies, strategy, plan identity, state revision, and worktree.
2. Claim the task through the state contract.
3. Record discoveries in `## Notes & Discoveries`.
4. Obtain the strategy's required initial evidence.
5. Make the minimum worksheet-scoped change.
6. Obtain focused green evidence, refactor only while green, and run relevant aggregate gates.
7. Review the diff and stage exact task-owned paths only.
8. Commit once with a conventional message.
9. Close the task with the commit, exact commands/results, and checked acceptance criteria; reconcile the spec in the same state transaction.

Use one task per delegated invocation and one functional commit per task. Never stage broadly in a shared or dirty checkout. Commits remain local unless the user separately authorizes publication.

## Low-signal test and gate policy

Reject tests that lock incidental prompt phrases, private implementation shape, duplicate snapshots, or file existence without an operational contract. Prefer native parser, lint, type, and build contracts to source scanners when they express the complete rule. Retain tests for observable behavior, public contracts, proven regressions, error paths, interoperability, and operationally meaningful structure such as signatures, exports, hashing, memory layout, compilation, serialization, and isolation.

When replacing a gate, prove the replacement against an isolated violation before removing the old check. Confirm aggregate discovery includes new and untracked files where relevant.

## Commits and checkpoints

Use `<type>(<scope>): <description>` and stage exact paths. Do not force-add ignored Flow artifacts. A phase checkpoint records affected task ids, the last functional commit, and fresh aggregate evidence; never create an empty checkpoint commit.

Flow may append supplementary Git notes under `refs/notes/flow` only after the canonical Markdown transaction succeeds. Notes are optional, stay local by default, and never become state authority. Git tags are prohibited as evidence or fallback transport.

## Knowledge lifecycle

1. **Capture:** append dated discoveries to the owning task and reusable learnings to the flow's `learnings.md`.
2. **Synthesize:** integrate reusable current-state guidance into the best matching chapter anywhere under `.agents/bundles/knowledge/**/*.md`; preserve project-shaped nesting such as `architecture/`, `frontends/`, `backends/`, `storage/`, `transport/`, `listener/`, `operations/`, `standards/`, or `patterns/`.
3. **Log:** history belongs in `.agents/bundles/log.md`, not in current-state knowledge prose.
4. **Contract:** after verified completion and archive review, delete the archived spec directory; Git history is the archive.

Operational project skills live only at `.agents/skills/`. Never create `.agents/bundles/skills/`.

## Quality gates

Before close or checkpoint, require:

- worksheet acceptance criteria satisfied with fresh evidence;
- selected verification strategy followed, including isolated gate proof when required;
- focused and relevant aggregate commands green;
- repository-defined lint, type, build, docs, coverage, security, and performance gates run when applicable;
- no accidental public API, typing, performance, import-boundary, or behavior change;
- no unrelated paths staged and `git diff --check` clean;
- discoveries and verification limitations recorded.

Coverage follows repository and worksheet requirements. Compare affected lines/branches when deleting behavioral tests; there is no universal percentage or one-test-file-per-module mandate.

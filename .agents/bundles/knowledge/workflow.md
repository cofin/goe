---
type: concept
title: Developer Workflow & Commands
description: Canonical development, testing, linting, architecture verification, and Flow task continuity workflows for GOE.
status: stable
tags:
  - workflow
  - commands
  - verification
  - flow
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: makefile
    resource: Makefile::lint
    title: Repository Makefile Targets
  - id: verify-arch
    resource: tools/verify_architecture.py::main
    title: AST Architecture Verification Script
  - id: cli-main
    resource: src/goe/cli/main.py::cli
    title: Unified GOE Rich-Click CLI Entrypoint
---

# Developer Workflow & Commands

<!-- truth: start -->
- Virtual environment setup: `make install` (or `make setup-env` to configure kernel index).[^makefile]
- Development packages & lockfile: Managed via `uv` with `pyproject.toml` (`[dependency-groups]`) and `uv.lock`.
- Unit testing: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit` (or `make test-unit`).
- Integration testing: `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false GOE_TEST_USER_PASS=... && uv run pytest tests/integration -n 4` (or `make test-integration`).
- Code formatting & linting: `make format` (`uv run ruff format` and `uv run ruff check --fix`) and `make lint` (`uv run ruff check .`, `uv run mypy src/goe`, and `uv run python tools/verify_architecture.py`).[^verify-arch]
- Base CI environment simulation: `.github/workflows/test.yaml` runs `uv sync --dev --locked` (without `--all-extras`); verify unit tests in an isolated base CI environment via `UV_PROJECT_ENVIRONMENT=/tmp/ci-venv uv sync --python .venv/bin/python --dev --locked --offline && UV_PROJECT_ENVIRONMENT=/tmp/ci-venv GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit -q`.
- Packaging & release build: `make build` (produces wheel and sdist in `dist/`), `make target` (compiles runtime tree in `target/offload`), and `make package` (produces `goe_<version>.tar.gz`).
- Pre-flight & operational CLI: `goe connect` (or `goe connect --json`), `goe offload -t <owner.table> -x`, `goe listener start`, and `goe listener mcp {stdio,bridge,inspect}`.[^cli-main]
- Direct Markdown + Git continuity: Task worksheets under `.agents/bundles/specs/<flow_id>/tasks/<id>-<slug>.md` and `spec.md` checklists (`[ ]`, `[~]`, `[x] [<sha>]`, `[!]`, `[-]`) are the sole authority for task state and commits.
- Project-local skills live at `.agents/skills/` and paired subagents live at `.agents/agents/` (with Codex parity at `.codex/agents/`).
<!-- truth: end -->

## Canonical Commands

Prefer repository-native Makefile targets and `uv run` invocations:

```bash
# Setup & dependency sync
make setup-env
make install
make upgrade

# Focused & aggregate unit tests
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
make test-unit
uv run pytest tests/unit/offload/test_column_metadata.py -q

# Parallel integration tests (requires active Oracle & GCP credentials)
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false GOE_TEST_USER_PASS="<db_password>" GOOGLE_CLOUD_PROJECT="<gcp_project_id>"
make test-integration

# Formatting, linting, static typechecking & architecture boundary verification
make format
make lint
uv run python tools/verify_architecture.py

# OKF v0.2 bundle validation
python3 ~/.gemini/config/plugins/flow/tools/validate.py --bundle .agents/bundles

# Runtime distribution & release packaging
make build
make target
make package

# Pre-flight & operational CLI validation
uv run goe connect
uv run goe offload -t SH.SALES -x
uv run goe validate -t SH.SALES --verify-row-count aggregate
```

## Direct Markdown + Git Continuity

1. Read `.agents/setup-state.json` to resolve `bundle_root` (`.agents/bundles`) and `ignore_policy` (`shared`).
2. Discover active flows by scanning `.agents/bundles/specs/<flow_id>/spec.md` YAML frontmatter (`state: draft | planned | active | completed | archived`).
3. Read authoritative task frontmatter in `.agents/bundles/specs/<flow_id>/tasks/<id>-<slug>.md` (`state: pending | in_progress | completed | blocked | deferred`).
4. Run the 5-check task preflight before claiming any task:
   - Worksheet completeness (`Objective`, `Verification Strategy`, `Files Owned`, `Acceptance Criteria`).
   - Dependency readiness (`depends_on` tasks all `completed` with recorded `commit` SHAs).
   - Live target existence and baseline green check.
   - Clean working tree (`git status --short` has no conflicting modifications).
   - Checklist alignment between `tasks/<id>-<slug>.md` and `spec.md`.
5. Execute one vertical slice per task (production change + canonical unit tests in `tests/unit/`), verify focused and aggregate gates (`make lint` and targeted `uv run pytest`), stage exact task-owned paths, create one signed commit (`<type>(<scope>): <summary>`), and update both `tasks/<id>-<slug>.md` (`state: completed`, `commit: <sha>`) and `spec.md` (`- [x] [<sha>]`).

## Verification Strategies

| Strategy | Select For | Required Evidence |
| :--- | :--- | :--- |
| `behavior_tdd` | New observable behavior | Focused test fails because behavior is absent (`Red`); minimal implementation makes it pass (`Green`). |
| `regression_tdd` | Defect correction | Focused test reproduces the defect (`Red`); narrow fix makes it pass (`Green`). |
| `characterization` | Behavior-preserving refactor or deletion | Focused baseline passes before and unchanged behavior passes after. |
| `static_validation` | Config, typing, or AST boundary gate | Native parser, `ruff`, `mypy src/goe`, and `tools/verify_architecture.py` pass; isolated violation proves gate failure when adding a rule. |
| `documentation_validation` | Docs, OKF chapters, skills, or links | `validate.py --bundle .agents/bundles` and relative Markdown link checks pass. |
| `integration_acceptance` | Multi-component contract composition | End-to-end scenario plus negative/refusal path tests pass. |

## Knowledge & Archive Lifecycle

1. **Capture**: Record mid-task discoveries in the task worksheet's `## Notes & Discoveries` section and flow-level insights in `.agents/bundles/specs/<flow_id>/learnings.md`.
2. **Synthesize**: On `/flow:learn` or `/flow:archive`, promote durable truths into `.agents/bundles/knowledge/**/*.md` (including `domains/`, `decisions/`, `testing/`, and `gotchas/`) and synchronize `.agents/skills/` and `.agents/agents/`.
3. **Log & Contract**: Record the summary in `.agents/bundles/log.md` and `.agents/bundles/specs/index.md`, then delete the completed spec directory from `.agents/bundles/specs/`.

[^makefile]: `Makefile::lint` — Repository build, test, format, and lint orchestration targets.
[^verify-arch]: `tools/verify_architecture.py::main` — AST and token boundary checker enforcing GOE architectural invariants.
[^cli-main]: `src/goe/cli/main.py::cli` — Root `goe` Click group and lazy command loader.

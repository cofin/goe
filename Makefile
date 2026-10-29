# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash

# -----------------------------------------------------------------------------
# Display Formatting and Colors
# -----------------------------------------------------------------------------
BLUE := $(shell printf "\033[1;34m")
GREEN := $(shell printf "\033[1;32m")
RED := $(shell printf "\033[1;31m")
YELLOW := $(shell printf "\033[1;33m")
NC := $(shell printf "\033[0m")
INFO := $(shell printf "$(BLUE)ℹ$(NC)")
OK := $(shell printf "$(GREEN)✓$(NC)")
WARN := $(shell printf "$(YELLOW)⚠$(NC)")
ERROR := $(shell printf "$(RED)✖$(NC)")

# =============================================================================
# Configuration and Environment Variables
# =============================================================================
.DEFAULT_GOAL:=help
.ONESHELL:
.EXPORT_ALL_VARIABLES:
MAKEFLAGS += --no-print-directory

BUILD_DIR=dist
OFFLOAD_VERSION=$(shell sed -rn 's/version = "([a-zA-Z0-9.-]+)"/\1/p' pyproject.toml)
GOE_WHEEL=goe_framework-$(shell echo $(OFFLOAD_VERSION)-py3-none-any.whl)
BUILD=$(strip $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev"))
VENV_PREFIX=.venv

# If uv.toml exists, force public PyPI for pip (used by pre-commit)
ifneq (,$(wildcard uv.toml))
export PIP_INDEX_URL=https://pypi.org/simple
endif

# Suppress Google client library certificate warnings during tests
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false

# =============================================================================
# Help & Documentation
# =============================================================================
.PHONY: help
help:                                               ## Display this help menu
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

# =============================================================================
# Developer Environment & Lifecycle
# =============================================================================
.PHONY: setup-env
setup-env:                                          ## Configure local environment and kernel-appropriate uv.toml
	@tools/scripts/setup-env.sh

.PHONY: install
install: setup-env                                  ## Install project dependencies in editable mode using uv
	@echo "${INFO} Installing dependencies with uv..."
	@uv sync --all-extras --dev
	@echo "${OK} Installation complete 🎉"

.PHONY: install-dev
install-dev: install                                ## Backward-compatible alias for install

.PHONY: install-dev-extras
install-dev-extras: install                         ## Backward-compatible alias for install with all extras

.PHONY: upgrade
upgrade: setup-env                                  ## Upgrade all dependencies to latest stable versions
	@echo "${INFO} Upgrading uv lockfile..."
	@uv lock --upgrade
	@uv sync --all-extras --dev
	@echo "${OK} Dependencies upgraded 🔄"

.PHONY: lint
lint:                                               ## Run Ruff linter and Mypy static typecheck
	@echo "${INFO} Running Ruff linting..."
	@uv run ruff check .
	@echo "${INFO} Running Mypy typecheck..."
	@uv run mypy src/goe
	@echo "${INFO} Running architecture boundary verifier..."
	@uv run python tools/verify_architecture.py
	@echo "${OK} Linting and typechecks passed ✓"

.PHONY: format
format:                                             ## Run Ruff formatter and auto-fix lint issues
	@echo "${INFO} Formatting codebase with Ruff..."
	@uv run ruff format .
	@uv run ruff check --fix .
	@echo "${OK} Code formatted ✓"

.PHONY: test
test: test-unit                                     ## Run default test suite (unit tests)

.PHONY: test-unit
test-unit:                                          ## Run unit tests
	@echo "${INFO} Running unit tests..."
	@uv run pytest tests/unit
	@echo "${OK} Unit tests completed successfully ✓"

.PHONY: test-integration
test-integration:                                   ## Run parallel integration tests
	@echo "${INFO} Running integration tests..."
	@uv run pytest tests/integration -n 4
	@echo "${OK} Integration tests completed ✓"

.PHONY: test-integration-oracle
test-integration-oracle:                            ## Run Oracle persistence and frontend integration tests
	@echo "${INFO} Running Oracle integration tests..."
	@uv run pytest tests/integration/persistence/test_orchestration_metadata.py tests/integration/persistence/test_orchestration_repo_client.py -v
	@echo "${OK} Oracle integration tests completed ✓"

.PHONY: test-integration-gcp
test-integration-gcp:                               ## Run BigQuery and GCS integration tests using ADC
	@echo "${INFO} Running BigQuery/GCS integration tests..."
	@uv run pytest tests/integration -m "bigquery or gcs" -n 4
	@echo "${OK} BigQuery/GCS integration tests completed ✓"

.PHONY: build
build: clean                                        ## Build wheel and source distribution into dist/
	@echo "${INFO} Building wheel and sdist with uv..."
	@uv build
	@echo "${OK} Build complete in dist/ ✓"

.PHONY: bundle
bundle:                                             ## Build standalone PyApp distribution
	@echo "${INFO} Bundling standalone PyApp artifact..."
	@uv run python tools/bundle_python.py
	@echo "${OK} Bundle complete ✓"

.PHONY: spark-listener
spark-listener:                                     ## Build Spark listener JARs
	@cd tools/spark-listener && make target

# =============================================================================
# Cleanup Rules
# =============================================================================
.PHONY: clean
clean:                                              ## Clean build and test artifacts
	@echo "${INFO} Cleaning working directory..."
	@rm -rf .pytest_cache .ruff_cache .mypy_cache build/ dist/ .eggs/ .coverage coverage.xml htmlcov/ >/dev/null 2>&1
	@find . -name '*.egg-info' -exec rm -rf {} + >/dev/null 2>&1
	@find . -name '*.pyc' -exec rm -f {} + >/dev/null 2>&1
	@[ ! -d tools/spark-listener ] || (cd tools/spark-listener && make clean >/dev/null 2>&1 || true)
	@echo "${OK} Clean complete ✓"

.PHONY: destroy
destroy:                                            ## Destroy local .venv environment
	@echo "${INFO} Destroying virtual environment..."
	@rm -rf .venv
	@echo "${OK} Virtual environment destroyed 🗑️"

.PHONY: deep-clean
deep-clean: clean destroy                           ## Clean everything including uv cache
	@uv cache clean >/dev/null 2>&1 || true
	@echo "${OK} Deep clean complete ✓"

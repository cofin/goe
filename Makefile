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

TARGET_DIR=target/offload
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
	@uv run ruff check src tests tools
	@echo "${INFO} Running Mypy typecheck..."
	@uv run mypy src/goe
	@echo "${OK} Linting and typechecks passed ✓"

.PHONY: format
format:                                             ## Run Ruff formatter and auto-fix lint issues
	@echo "${INFO} Formatting codebase with Ruff..."
	@uv run ruff format src tests tools
	@uv run ruff check --fix src tests tools
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

.PHONY: build
build: clean                                        ## Build wheel and source distribution into dist/
	@echo "${INFO} Building wheel and sdist with uv..."
	@uv build
	@echo "${OK} Build complete in dist/ ✓"

# =============================================================================
# Cleanup Rules
# =============================================================================
.PHONY: clean
clean:                                              ## Clean build and test artifacts
	@echo "${INFO} Cleaning working directory..."
	@rm -rf .pytest_cache .ruff_cache .mypy_cache build/ dist/ target/offload target/transport .eggs/ .coverage coverage.xml htmlcov/ >/dev/null 2>&1
	@find . -name '*.egg-info' -exec rm -rf {} + >/dev/null 2>&1
	@find . -name '*.pyc' -exec rm -f {} + >/dev/null 2>&1
	@[ ! -d templates/conf ] || (cd templates/conf && make clean >/dev/null 2>&1 || true)
	@[ ! -d tools/spark-listener ] || (cd tools/spark-listener && make clean >/dev/null 2>&1 || true)
	@[ ! -d target ] || (cd target && make clean >/dev/null 2>&1 || true)
	@rm -f goe_[0-9]*.[0-9]*.*.tar.gz >/dev/null 2>&1 || true
	@echo "${OK} Clean complete ✓"

.PHONY: destroy
destroy:                                            ## Destroy local .venv environment
	@echo "${INFO} Destroying virtual environment..."
	@rm -rf .venv
	@echo "${OK} Virtual environment destroyed 🗑️"

.PHONY: python-goe-destroy
python-goe-destroy: destroy                         ## Backward-compatible alias for destroy

.PHONY: python-goe-clean
python-goe-clean: clean                             ## Backward-compatible alias for clean

.PHONY: deep-clean
deep-clean: clean destroy                           ## Clean everything including uv cache
	@uv cache clean >/dev/null 2>&1 || true
	@echo "${OK} Deep clean complete ✓"

# =============================================================================
# Packaging & Sub-Make Orchestration
# =============================================================================
.PHONY: python-goe
python-goe:                                         ## Build Python distribution
	@uv build

.PHONY: spark-basic-auth
spark-basic-auth:                                   ## Build Spark basic auth helper
	@cd spark-basic-auth && make

.PHONY: spark-listener
spark-listener:                                     ## Build Spark listener package
	@cd tools/spark-listener && make target

.PHONY: package-spark-standalone
package-spark-standalone: spark-listener            ## Package Spark transport standalone binaries
	@cd tools/transport && make spark-target
	@cd target && make package-spark

.PHONY: offload-env
offload-env:                                        ## Compile offload configuration templates
	@cd templates/conf && make

.PHONY: offload-home-check
offload-home-check:                                 ## Verify OFFLOAD_HOME environment variable
	@[ "$$OFFLOAD_HOME" ] || (echo "${ERROR} OFFLOAD_HOME is not set" && exit 1)

.PHONY: target
target: python-goe spark-listener offload-env       ## Compile full runtime target tree
	@echo "${INFO} Building target distribution in $(TARGET_DIR)..."
	@mkdir -p $(TARGET_DIR)/bin
	@cp bin/{offload,connect,logmgr,agg_validate} $(TARGET_DIR)/bin 2>/dev/null || true
	@mkdir -p $(TARGET_DIR)/tools
	@cp tools/goe-shell-functions.sh $(TARGET_DIR)/tools 2>/dev/null || true
	@rm -rf $(TARGET_DIR)/setup/sql $(TARGET_DIR)/setup/python
	@mkdir -p $(TARGET_DIR)/cache
	@mkdir -p $(TARGET_DIR)/setup/sql && cp -a sql/oracle/source/* $(TARGET_DIR)/setup 2>/dev/null || true
	@mkdir -p $(TARGET_DIR)/lib && cp dist/goe_framework-*.whl $(TARGET_DIR)/lib 2>/dev/null || true
	@cp LICENSE AUTHORS $(TARGET_DIR)/ 2>/dev/null || true
	@echo "$(OFFLOAD_VERSION) ($(BUILD))" > $(TARGET_DIR)/version_build
	@sed -i -e "s/VERSION/$(OFFLOAD_VERSION)/" -e "s/BUILD/$(BUILD)/" $(TARGET_DIR)/setup/sql/{install,upgrade}_env.sql 2>/dev/null || true
	@sed -i "s/'%s-SNAPSHOT'/'$(OFFLOAD_VERSION) ($(BUILD))'/" $(TARGET_DIR)/setup/sql/create_offload*_package_spec.sql 2>/dev/null || true
	@mkdir -p $(TARGET_DIR)/templates
	@cp -r templates/goe_base.html templates/offload_status_report $(TARGET_DIR)/templates/ 2>/dev/null || true
	@mkdir -p $(TARGET_DIR)/run $(TARGET_DIR)/log
	@chmod 775 $(TARGET_DIR)/run $(TARGET_DIR)/log 2>/dev/null || true
	@chmod 640 $(TARGET_DIR)/conf/*offload.env.template 2>/dev/null || true
	@echo "${OK} Target build complete ✓"

.PHONY: package
package: target                                     ## Package full GOE release tarball
	@cd target && make package
	@echo "${OK} Packaging complete ✓"

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
DBT_DIR := transform
DUCKDB_DIR := $(CURDIR)/data/duckdb
FIXTURE_DIR := $(CURDIR)/data/fixtures/ga4
DBT_CI_ENV := DBT_PROFILES_DIR=$(CURDIR)/$(DBT_DIR)/ci DBT_DUCKDB_PATH=$(DUCKDB_DIR)/ci.duckdb
SQL_DIRS := $(wildcard transform infra)
DBT_CI := cd $(DBT_DIR) && $(DBT_CI_ENV) $(UV) run dbt

.PHONY: help setup lint format test fixtures dbt-deps dbt-ci docs secrets clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

setup: ## Install pinned dependencies, git hooks and dbt packages
	$(UV) sync --all-groups --locked
	$(UV) run pre-commit install
	$(DBT_CI) deps

lint: ## Run ruff and sqlfluff without changing files
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run sqlfluff lint $(SQL_DIRS)

format: ## Apply ruff formatting and safe fixes
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

test: ## Run the Python test suite with coverage
	$(UV) run pytest

fixtures: ## Generate synthetic GA4 fixture data (fixed seed)
	$(UV) run python -m scripts.generate_fixtures --output-dir $(FIXTURE_DIR)

dbt-deps: ## Install dbt packages
	$(DBT_CI) deps

dbt-ci: fixtures dbt-deps ## Build and test every dbt model on DuckDB fixtures
	mkdir -p $(DUCKDB_DIR)
	$(DBT_CI) build --target ci

docs: dbt-deps ## Generate static dbt docs from the DuckDB target
	mkdir -p $(DUCKDB_DIR)
	$(DBT_CI) docs generate --static --target ci

secrets: ## Scan git history and staged changes for secrets (needs gitleaks installed)
	gitleaks git --redact --no-banner .
	gitleaks git --redact --no-banner --staged .

clean: ## Remove generated data and build output
	rm -rf $(CURDIR)/data/fixtures $(DUCKDB_DIR) $(DBT_DIR)/target $(DBT_DIR)/dbt_packages $(DBT_DIR)/logs
